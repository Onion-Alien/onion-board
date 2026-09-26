"""The Voice panel: voice changer, text-to-speech, live voice-to-speech, add-ons.

`VoiceFxPanel` and `SpeechPanel` follow panel.py's pattern: they own their widgets
and emit plain dicts (`changed`) that the main window stores in the config.
`VoicePanel` lays them out as the Voice tab (cards + the tab's bottom bar).
"""
from __future__ import annotations

import os
import threading
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                               QScrollArea, QSlider, QVBoxLayout, QWidget)

from soundboard import modules as mods
from soundboard import voicefx
from soundboard import library
from soundboard.speech.live import SpeechController
from soundboard.ui import icons
from soundboard.ui.panel import (VolumeControl, bar, card, hint_label, icon_label,
                                 section_label, vsep)
from soundboard.ui.widgets import Meter
from soundboard.wheelguard import no_wheel

CUSTOM = "Custom"
LIVE_MODULE = "live-voice"
IDLE_HINT = "Press Start, then just talk."
MODELS = [("Fast (base.en)", "base.en"), ("Fastest (tiny.en)", "tiny.en"),
          ("Accurate (small.en)", "small.en"), ("Any language (base)", "base"),
          ("Any language, accurate (small)", "small")]


def default_fx_spec() -> dict:
    return {"enabled": False, "preset": CUSTOM, "effects": {}}


def default_speech_settings() -> dict:
    return {"voice": "", "rate": 0, "gain": 1.0, "model": "base.en", "language": "en",
            "mute_real_voice": True}


# =========================================================================== voice changer

class ParamSlider(QWidget):
    changed = Signal()

    def __init__(self, q: voicefx.Param, value: float):
        super().__init__()
        self.q = q
        self.steps = int(round((q.hi - q.lo) / q.step)) if q.step else 200
        self.setMinimumHeight(26)
        h = QHBoxLayout(self)
        h.setContentsMargins(22, 0, 0, 0)
        name = QLabel(q.label)
        name.setFixedWidth(78)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, self.steps)
        self.val = QLabel()
        self.val.setFixedWidth(64)
        self.val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.val.setObjectName("eqlabel")
        h.addWidget(name)
        h.addWidget(self.slider, 1)
        h.addWidget(self.val)
        no_wheel(self.slider)
        self.set_value(value)
        self.slider.valueChanged.connect(self._moved)

    def value(self) -> float:
        return self.q.lo + (self.q.hi - self.q.lo) * self.slider.value() / self.steps

    def set_value(self, v: float):
        v = self.q.clamp(v)
        self.slider.blockSignals(True)
        self.slider.setValue(int(round((v - self.q.lo) / (self.q.hi - self.q.lo) * self.steps)))
        self.slider.blockSignals(False)
        self._label()

    def _label(self):
        v = self.value()
        if self.q.unit:
            txt = f"{v:+g}{self.q.unit}" if self.q.lo < 0 else f"{v:g}{self.q.unit}"
        else:
            txt = f"{round(v * 100)}%" if self.q.hi <= 1 else f"{v:g}"
        self.val.setText(txt)

    def _moved(self, _v):
        self._label()
        self.changed.emit()


class EffectRow(QWidget):
    changed = Signal()

    def __init__(self, cls: type[voicefx.Effect], cfg: dict):
        super().__init__()
        self.cls = cls
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        self.chk = QCheckBox(cls.name)
        self.chk.setToolTip(cls.description)
        self.chk.setChecked(bool(cfg.get("on")))
        v.addWidget(self.chk)
        self.err = hint_label("")
        self.err.setStyleSheet("color:#ff4d4f;")
        self.err.hide()
        v.addWidget(self.err)
        self.body = QWidget()
        b = QVBoxLayout(self.body)
        b.setContentsMargins(0, 0, 0, 4)
        b.setSpacing(2)
        self.sliders = []
        for q in cls.params:
            s = ParamSlider(q, cfg.get(q.key, q.default))
            s.changed.connect(self.changed)
            b.addWidget(s)
            self.sliders.append(s)
        v.addWidget(self.body)
        self.body.setVisible(self.chk.isChecked())
        self.chk.toggled.connect(self._toggled)

    def _toggled(self, on):
        self.body.setVisible(on)
        self.changed.emit()

    def state(self) -> dict:
        d = {"on": self.chk.isChecked()}
        d.update({s.q.key: s.value() for s in self.sliders})
        return d

    def load(self, cfg: dict | None):
        self.chk.blockSignals(True)
        self.chk.setChecked(bool(cfg and cfg.get("on", True)))
        self.chk.blockSignals(False)
        self.body.setVisible(self.chk.isChecked())
        for s in self.sliders:
            s.set_value((cfg or {}).get(s.q.key, s.q.default))

    def set_error(self, msg: str):
        self.err.setText(f"⚠ Turned off after an error: {msg}" if msg else "")
        self.err.setVisible(bool(msg))


PRESET_ICONS = {"Chipmunk": "🐿️", "Deep voice": "🐻", "Giant / demon": "👹", "Robot": "🤖",
                "Alien": "👽", "Walkie-talkie": "📻", "Old telephone": "☎️", "Megaphone": "📢",
                "Cave": "🦇", "Stadium announcer": "🏟️"}
POWER_TEXT = {False: "Voice changer is OFF  —  pick a voice below to turn it on",
              True: "ON  —  everyone hears your changed voice"}


class VoiceFxPanel(QWidget):
    """The voice changer: one big on/off switch, a grid of voices to pick from, a
    way to hear yourself, and (folded away) the individual effects for fine-tuning.

    `changed(spec)` with spec = {"enabled", "preset", "effects": {type: {...}}}.
    `hear_toggled(bool)` asks the window to switch "Hear what they hear" on or off."""
    changed = Signal(dict)
    hear_toggled = Signal(bool)

    COLS = 3

    def __init__(self, spec: dict):
        super().__init__()
        spec = {**default_fx_spec(), **(spec or {})}
        self._preset = spec.get("preset") if spec.get("preset") in voicefx.PRESETS else CUSTOM
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        v.addWidget(section_label("VOICE CHANGER"))
        v.addWidget(hint_label("Changes your real voice as you talk, live. There's nothing "
                               "to start: while it's on, Discord and your game hear the "
                               "changed voice every time you speak."))

        # ---- the switch
        self.btn_power = QPushButton()
        self.btn_power.setObjectName("power")
        self.btn_power.setCheckable(True)
        self.btn_power.setMinimumHeight(42)
        self.btn_power.setCursor(Qt.PointingHandCursor)
        icons.set_icon(self.btn_power, "mic", checked_color="#ffffff")
        self.btn_power.setChecked(spec["enabled"])
        self.btn_power.toggled.connect(self._on_power)
        v.addWidget(self.btn_power)

        # ---- pick a voice
        v.addWidget(QLabel("<b>Pick a voice</b>"))
        grid = QGridLayout()
        grid.setSpacing(6)
        self.tiles = QButtonGroup(self)
        self.tiles.setExclusive(True)
        self._tile: dict[str, QPushButton] = {}
        names = list(voicefx.PRESETS) + [CUSTOM]
        for i, name in enumerate(names):
            label = (f"{PRESET_ICONS.get(name, '🎛️')}  {name}" if name != CUSTOM
                     else "🎚️  My own mix")
            b = QPushButton(label)
            b.setObjectName("voicetile")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip("Your own settings from Fine-tune below" if name == CUSTOM else
                         f"Sound like: {name}. Click to turn the voice changer on with it.")
            b.clicked.connect(lambda _=False, n=name: self.pick(n))
            self.tiles.addButton(b)
            grid.addWidget(b, i // self.COLS, i % self.COLS)
            self._tile[name] = b
        for c in range(self.COLS):
            grid.setColumnStretch(c, 1)
        v.addLayout(grid)

        # ---- hear it
        hear = QHBoxLayout()
        hear.setSpacing(8)
        self.btn_hear = QPushButton("Hear my voice (only me)")
        self.btn_hear.setObjectName("miccheck")
        self.btn_hear.setCheckable(True)
        self.btn_hear.setToolTip("Plays your mic, changed, into your headphones, the same "
                                 "as “Hear what they hear” at the bottom. Click again to stop.")
        icons.set_icon(self.btn_hear, "ear", checked_color="#ffffff")
        self.btn_hear.toggled.connect(self.hear_toggled)
        hear.addWidget(self.btn_hear)
        hear.addWidget(icon_label("mic", "Your mic level"))
        self.meter = Meter()
        self.meter.setToolTip("Your mic level: it moves when you talk")
        hear.addWidget(self.meter, 1)
        v.addLayout(hear)

        # ---- fine-tune (folded away)
        self.btn_more = QPushButton()
        self.btn_more.setObjectName("small")
        self.btn_more.setCheckable(True)
        self.btn_more.toggled.connect(self._show_more)
        v.addWidget(self.btn_more, 0, Qt.AlignLeft)
        self.more = QWidget()
        self.box = QVBoxLayout(self.more)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(4)
        self.box.addWidget(hint_label("Tick effects and drag their sliders to make your own "
                                      "voice. Changing anything here switches to "
                                      "“My own mix”."))
        v.addWidget(self.more)
        self.rows: dict[str, EffectRow] = {}
        self._spec_effects = dict(spec.get("effects", {}))
        self.add_new_effects()
        self._show_more(False)
        self._refresh()

    # ------------------------------------------------------------------ public
    @property
    def preset(self) -> str:
        return self._preset

    def pick(self, name: str):
        """Choose a voice (a preset name or CUSTOM) and turn the changer on."""
        self._preset = name
        fx = voicefx.PRESETS.get(name)
        if fx is not None:
            for t, r in self.rows.items():
                r.load({"on": True, **fx[t]} if t in fx else None)
        elif name == CUSTOM:
            self.btn_more.setChecked(True)   # your own mix lives in Fine-tune
        self.btn_power.blockSignals(True)
        self.btn_power.setChecked(True)
        self.btn_power.blockSignals(False)
        self._refresh()
        self._emit()

    def set_hearing(self, on: bool):
        """Mirror the window's "Hear what they hear" state."""
        self.btn_hear.blockSignals(True)
        self.btn_hear.setChecked(on)
        self.btn_hear.blockSignals(False)

    def set_level(self, level: float):
        self.meter.set_level(level)

    def add_new_effects(self):
        """Add rows for effect types registered since (modules loaded later)."""
        for etype, cls in voicefx.REGISTRY.items():
            if etype in self.rows:
                continue
            r = EffectRow(cls, self._spec_effects.get(etype, {}))
            r.changed.connect(self._edited)
            self.box.addWidget(r)
            self.rows[etype] = r

    def spec(self) -> dict:
        return {"enabled": self.btn_power.isChecked(), "preset": self._preset,
                "effects": {t: r.state() for t, r in self.rows.items()}}

    def show_errors(self, errors: dict[str, str]):
        for t, r in self.rows.items():
            r.set_error(errors.get(t, ""))

    # ------------------------------------------------------------------ internals
    def _on_power(self, on: bool):
        self._refresh()
        self._emit()

    def _show_more(self, on: bool):
        self.more.setVisible(on)
        self.btn_more.setText("▾  Fine-tune effects" if on else "▸  Fine-tune effects")

    def _refresh(self):
        on = self.btn_power.isChecked()
        self.btn_power.setText(POWER_TEXT[on])
        # only a voice that's actually in use is highlighted
        self.tiles.setExclusive(False)
        for name, b in self._tile.items():
            b.setChecked(on and name == self._preset)
        self.tiles.setExclusive(True)

    def _edited(self):
        self._preset = CUSTOM
        if not self.btn_power.isChecked() and any(r.chk.isChecked() for r in self.rows.values()):
            self.btn_power.blockSignals(True)
            self.btn_power.setChecked(True)   # touching an effect means you want it on
            self.btn_power.blockSignals(False)
        self._refresh()
        self._emit()

    def _emit(self):
        self.changed.emit(self.spec())


# =========================================================================== speech

class SpeechPanel(QWidget):
    """Text-to-speech box and live voice-to-speech. `changed(settings)` for the config."""
    changed = Signal(dict)
    _event = Signal(dict)          # module / TTS events, hopped onto the UI thread
    _voices = Signal(list, str)
    _install_line = Signal(str)
    _install_done = Signal(bool)

    def __init__(self, controller: SpeechController, settings: dict,
                 module_list: list[mods.ModuleInfo]):
        super().__init__()
        self.ctl = controller
        self.s = {**default_speech_settings(), **(settings or {})}
        self.module = next((m for m in module_list if m.id == LIVE_MODULE and not m.error),
                           None)
        controller.gain = self.s["gain"]
        controller.speaker.voice = self.s["voice"]
        controller.speaker.rate = int(self.s["rate"])
        controller.mute_real_voice = self.s["mute_real_voice"]
        controller.on_event = self._event.emit
        self._event.connect(self._on_event)
        self._voices.connect(self._fill_voices)
        self._install_line.connect(lambda t: self.lbl_install.setText(t[-160:]))
        self._install_done.connect(self._on_install_done)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        # ---- live voice to speech: the main event
        v.addWidget(section_label("TALK AS A COMPUTER VOICE"))
        v.addWidget(hint_label("Press Start and talk normally. Each sentence you say is typed "
                               "out on this PC and read aloud by the computer voice below, a "
                               "second or two after you finish it, so others hear that voice "
                               "instead of yours. Press Stop when you're done."))
        self.live_box = QWidget()
        lv = QVBoxLayout(self.live_box)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(6)
        self.b_live = QPushButton("Start talking as the voice")
        icons.set_icon(self.b_live, "mic", "on_accent", "on_accent")
        self.b_live.setCheckable(True)
        self.b_live.setMinimumHeight(40)
        self.b_live.setObjectName("primary")
        self.b_live.toggled.connect(self._toggle_live)
        lv.addWidget(self.b_live)
        self.lbl_state = QLabel(IDLE_HINT)
        self.lbl_state.setObjectName("muted")
        lv.addWidget(self.lbl_state)
        v.addWidget(self.live_box)
        # everything the voice was asked to say, live or typed, newest at the bottom
        lrow = QHBoxLayout()
        lrow.addWidget(section_label("WHAT THE VOICE SAID"))
        lrow.addStretch(1)
        b_clear = QPushButton("Clear")
        b_clear.setObjectName("small")
        lrow.addWidget(b_clear)
        v.addLayout(lrow)
        self.said_log = QPlainTextEdit()
        self.said_log.setReadOnly(True)
        self.said_log.setMaximumBlockCount(500)
        self.said_log.setFixedHeight(130)
        self.said_log.setPlaceholderText("Nothing yet. Lines show up here as they're spoken.")
        b_clear.clicked.connect(self.said_log.clear)
        v.addWidget(self.said_log)

        self.missing = QWidget()
        mv = QVBoxLayout(self.missing)
        mv.setContentsMargins(0, 0, 0, 0)
        self.lbl_missing = hint_label("")
        mv.addWidget(self.lbl_missing)
        mrow = QHBoxLayout()
        self.b_install = QPushButton("Install speech recognition (one time, ~300 MB)")
        icons.set_icon(self.b_install, "plus")
        self.b_install.clicked.connect(self._install)
        mrow.addWidget(self.b_install)
        b_open = QPushButton("Open folder")
        b_open.clicked.connect(lambda: self._open_folder(self.module))
        mrow.addWidget(b_open)
        mrow.addStretch(1)
        mv.addLayout(mrow)
        self.lbl_install = hint_label("")
        self.lbl_install.hide()
        mv.addWidget(self.lbl_install)
        v.addWidget(self.missing)

        # ---- the voice (shared by live and typed speech)
        grid = QGridLayout()
        grid.addWidget(QLabel("Voice"), 0, 0)
        self.cb_voice = QComboBox()
        self.cb_voice.addItem("Loading voices…", "")
        self.cb_voice.setEnabled(False)
        grid.addWidget(self.cb_voice, 0, 1)
        grid.addWidget(QLabel("Speed"), 1, 0)
        self.sl_rate = QSlider(Qt.Horizontal)
        self.sl_rate.setRange(-10, 10)
        self.sl_rate.setValue(int(self.s["rate"]))
        grid.addWidget(self.sl_rate, 1, 1)
        grid.setColumnStretch(1, 1)
        v.addLayout(grid)
        self.btn_opts = QPushButton("▸  More options")
        self.btn_opts.setObjectName("small")
        self.btn_opts.setCheckable(True)
        v.addWidget(self.btn_opts, 0, Qt.AlignLeft)
        self.opts = QWidget()
        ov = QVBoxLayout(self.opts)
        ov.setContentsMargins(0, 0, 0, 0)
        grid = QGridLayout()
        grid.addWidget(QLabel("Recognition"), 2, 0)
        self.cb_model = QComboBox()
        for label, key in MODELS:
            self.cb_model.addItem(label, key)
        self.cb_model.setCurrentIndex(max(0, self.cb_model.findData(self.s["model"])))
        grid.addWidget(self.cb_model, 2, 1)
        grid.addWidget(QLabel("Language"), 3, 0)
        self.ed_lang = QLineEdit(self.s["language"])
        self.ed_lang.setPlaceholderText("en, es, de… or auto")
        self.ed_lang.setToolTip("Language you speak (two-letter code). 'auto' guesses; needs "
                                "an 'Any language' recognition model for anything but English.")
        grid.addWidget(self.ed_lang, 3, 1)
        grid.setColumnStretch(1, 1)
        ov.addLayout(grid)
        no_wheel(self.cb_voice, self.sl_rate, self.cb_model)
        self.chk_mute = QCheckBox("Mute my real mic while the computer voice is on")
        self.chk_mute.setToolTip("Others hear only the spoken voice, not your real one.")
        self.chk_mute.setChecked(self.s["mute_real_voice"])
        ov.addWidget(self.chk_mute)
        v.addWidget(self.opts)
        self.opts.hide()
        self.btn_opts.toggled.connect(lambda on: (
            self.opts.setVisible(on),
            self.btn_opts.setText("▾  More options" if on else "▸  More options")))
        self.tts_err = hint_label("")
        self.tts_err.setStyleSheet("color:#ff4d4f;")
        self.tts_err.hide()
        v.addWidget(self.tts_err)
        # ---- the tab's bottom bar (placed by VoicePanel, like every tab's bar):
        # typing a line is the extra, then the voice's volume
        self.say_bar, row = bar()
        row.addWidget(icon_label("speech", "Or type a line and it's spoken in the voice"))
        self.ed = QLineEdit()
        self.ed.setPlaceholderText("Or type a line and press Enter…")
        self.ed.returnPressed.connect(self._say)
        row.addWidget(self.ed, 1)
        b_say = QPushButton("Say")
        b_say.clicked.connect(self._say)
        b_stop = QPushButton("Stop")
        b_stop.clicked.connect(controller.stop_speaking)
        row.addWidget(b_say)
        row.addWidget(b_stop)
        sep = vsep()
        row.addWidget(sep)
        vol_icon = icon_label("volume", "How loud the spoken voice is")
        row.addWidget(vol_icon)
        self.sl_gain = VolumeControl(self.s["gain"], slider_max=200, typed_max=400,
                                     tip="How loud the spoken voice is")
        row.addWidget(self.sl_gain)
        self.say_vol_group = (sep, vol_icon, self.sl_gain)
        self.say_stop = b_stop

        for sig in (self.cb_voice.currentIndexChanged, self.sl_rate.valueChanged,
                    self.sl_gain.changed, self.cb_model.currentIndexChanged,
                    self.chk_mute.toggled):
            sig.connect(self._settings_edited)
        self.ed_lang.editingFinished.connect(self._settings_edited)
        self._refresh_module()

        threading.Thread(target=lambda: self._voices.emit(controller.tts.warm_up(),
                                                          controller.tts.error),
                         name="tts-warmup", daemon=True).start()

    # ---- text to speech
    def _say(self):
        text = self.ed.text().strip()
        if text:
            self.ctl.say(text)
            self._log_said(text)
            self.ed.clear()

    def _log_said(self, text: str):
        self.said_log.appendPlainText(f"{time.strftime('%H:%M:%S')}  {text}")
        bar_ = self.said_log.verticalScrollBar()
        bar_.setValue(bar_.maximum())

    def _fill_voices(self, voices: list, error: str):
        self.cb_voice.blockSignals(True)
        self.cb_voice.clear()
        self.cb_voice.addItem("Windows default", "")
        for name in voices:
            self.cb_voice.addItem(name.replace("Microsoft ", "").replace(" Desktop", ""), name)
        self.cb_voice.setCurrentIndex(max(0, self.cb_voice.findData(self.s["voice"])))
        self.cb_voice.setEnabled(bool(voices))
        self.cb_voice.blockSignals(False)
        if error:
            self._tts_error(f"Text-to-speech isn't available: {error}")

    def _tts_error(self, msg: str):
        self.tts_err.setText(f"⚠ {msg}")
        self.tts_err.show()

    def _settings_edited(self, *_):
        self.s.update(voice=self.cb_voice.currentData() or "", rate=self.sl_rate.value(),
                      gain=self.sl_gain.value(), model=self.cb_model.currentData(),
                      language=self.ed_lang.text().strip() or "en",
                      mute_real_voice=self.chk_mute.isChecked())
        self.ctl.speaker.voice = self.s["voice"]
        self.ctl.speaker.rate = self.s["rate"]
        self.ctl.gain = self.s["gain"]
        self.ctl.set_mute_real_voice(self.s["mute_real_voice"])
        self.changed.emit(dict(self.s))

    # ---- live
    def set_modules(self, module_list: list[mods.ModuleInfo]):
        self.module = next((m for m in module_list if m.id == LIVE_MODULE and not m.error),
                           None)
        self._refresh_module()

    def _refresh_module(self):
        m = self.module
        ok = m is not None and m.installed
        self.live_box.setVisible(ok)
        self.missing.setVisible(not ok)
        self.b_install.setVisible(m is not None and not ok)
        if m is None:
            self.lbl_missing.setText(
                "The live-voice add-on is missing from this copy of Soundboard. Run the "
                "installer again (it comes with every install), then press Refresh below.")
        elif not ok:
            self.lbl_missing.setText("Live voice needs its speech recognition installed first "
                                     "(runs on this PC; what you say never leaves it). "
                                     "Needs Python 3.12+ from python.org.")
            self.lbl_missing.setToolTip(str(m.path))

    def _install(self):
        m = self.module
        self.b_install.setEnabled(False)
        self.b_install.setText("Installing… (a few minutes)")
        self.lbl_install.show()
        self.lbl_install.setText("starting…")

        def work():
            ok = mods.install(m, self._install_line.emit)
            self._install_done.emit(ok)

        threading.Thread(target=work, name="module-install", daemon=True).start()

    def _on_install_done(self, ok: bool):
        self.b_install.setEnabled(True)
        self.b_install.setText("Install speech recognition (one time, ~300 MB)")
        if ok:
            self.lbl_install.hide()
            self._refresh_module()
            self.lbl_state.setText("Installed. Press Start and talk.")
        else:
            self.lbl_install.setText("⚠ Install failed: " + self.lbl_install.text())

    def _toggle_live(self, on: bool):
        if on and not self.ctl.live:
            try:
                self.ctl.start_live(self.module, ["--model", self.s["model"],
                                                  "--language", self.s["language"]])
            except RuntimeError as e:
                self._set_live_ui(False, f"⚠ {e}")
                return
            self._set_live_ui(True, "starting…")
        elif not on and self.ctl.live:
            self.ctl.stop_live()
            self._set_live_ui(False, IDLE_HINT)

    def _set_live_ui(self, on: bool, state: str):
        self.b_live.blockSignals(True)
        self.b_live.setChecked(on)
        self.b_live.blockSignals(False)
        self.b_live.setText("Stop the computer voice" if on else "Start talking as the voice")
        for w in (self.cb_model, self.ed_lang):
            w.setEnabled(not on)
        self.lbl_state.setText(state)

    def _on_event(self, ev: dict):
        t = ev.get("type")
        text = str(ev.get("text", ""))
        if t == "tts_error":
            self._tts_error(f"Couldn't speak that line: {text}")
        elif t == "status":
            self.lbl_state.setText(text)
        elif t == "ready":
            self.lbl_state.setText("● listening")
        elif t == "vad":
            self.lbl_state.setText("● hearing you…" if ev.get("speaking") else "● listening")
        elif t == "final" and text:
            self._log_said(text)
        elif t == "error":
            self.lbl_state.setText(f"⚠ {text}")
        elif t == "stopped":
            self._set_live_ui(False, f"⚠ stopped: {text}" if text else "stopped")

    @staticmethod
    def _open_folder(module: mods.ModuleInfo | None = None):
        """The module's own folder, or the user add-ons folder when it isn't there yet."""
        d = module.path if module is not None else library.APP_DIR / "modules"
        d.mkdir(parents=True, exist_ok=True)
        os.startfile(d)  # noqa: S606


# =========================================================================== add-ons list

class ModulesList(QWidget):
    refresh = Signal()

    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        v.addWidget(section_label("ADD-ONS"))
        self.list = QVBoxLayout()
        v.addLayout(self.list)
        row = QHBoxLayout()
        b = QPushButton("Refresh")
        b.clicked.connect(self.refresh)
        o = QPushButton("Open add-ons folder")
        o.clicked.connect(lambda: SpeechPanel._open_folder())
        row.addWidget(b)
        row.addWidget(o)
        row.addStretch(1)
        v.addLayout(row)

    def show_modules(self, infos: list[mods.ModuleInfo]):
        while self.list.count():
            w = self.list.takeAt(0).widget()
            if w:
                w.deleteLater()
        if not infos:
            self.list.addWidget(hint_label("No add-ons installed."))
        for m in infos:
            if m.error:
                state = f"⚠ {m.error}"
            elif m.kind == "service" and not m.installed:
                state = "not set up: run its install.bat"
            elif m.kind == "effects":
                state = "loaded" if m.loaded else "not loaded"
            else:
                state = "ready"
            lbl = hint_label(f"<b>{m.name}</b> {m.version} · {state}<br>{m.description}")
            lbl.setTextFormat(Qt.RichText)
            lbl.setToolTip(str(m.path))
            self.list.addWidget(lbl)


class VoicePanel(QWidget):
    """The Voice tab, shaped like the others: cards (live voice first, then the
    voice changer and add-ons) and the tab's bottom bar. Owns the chain wiring for
    the engine.

    `fx_changed(spec)` and `speech_changed(settings)` are for the main window to
    save in the config."""
    fx_changed = Signal(dict)
    speech_changed = Signal(dict)

    def __init__(self, engine, fx_spec: dict | None = None, speech: dict | None = None):
        super().__init__()
        self.engine = engine
        self.chain = voicefx.VoiceChain()
        engine.voice_chain = self.chain
        self.modules = mods.discover()
        mods.load_effects(self.modules)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        page = QWidget()
        cols = self._cols = QHBoxLayout(page)
        cols.setContentsMargins(0, 2, 4, 2)
        cols.setSpacing(12)
        lcol, rcol = QVBoxLayout(), QVBoxLayout()
        for col in (lcol, rcol):
            col.setSpacing(12)
            cols.addLayout(col, 1)
        scroll.setWidget(page)
        outer.addWidget(scroll, 1)

        # left: the voice changer. It always starts off (the voice you picked is kept):
        # left on from last time, it changed your mic the moment the app opened.
        self.fx = VoiceFxPanel({**(fx_spec or {}), "enabled": False})
        self.fx.changed.connect(self._fx_changed)
        fx_card, fv = card()
        fv.addWidget(self.fx)
        lcol.addWidget(fx_card)
        lcol.addStretch(1)

        # right: talk as a computer voice, then add-ons
        self.controller = SpeechController(engine, self.chain, lambda ev: None)
        self.speech = SpeechPanel(self.controller, speech or {}, self.modules)
        self.speech.changed.connect(self.speech_changed)
        live_card, lv = card()
        lv.addWidget(self.speech)
        rcol.addWidget(live_card)
        self.addons = ModulesList()
        self.addons.refresh.connect(self.rescan_modules)
        self.addons.show_modules(self.modules)
        add_card, av = card()
        av.addWidget(self.addons)
        rcol.addWidget(add_card)
        rcol.addStretch(1)

        outer.addWidget(self.speech.say_bar)
        self.chain.configure(self.fx.spec())

        # the voice changer's mic meter (only while the tab is showing)
        self._meter_timer = QTimer(self)
        self._meter_timer.timeout.connect(self._meter)
        self._meter_timer.start(50)

    def _meter(self):
        if self.isVisible():
            e = self.engine
            self.fx.set_level(e.level_mic if e.mic_stream is not None else 0.0)

    def fit_steps(self):
        """What the main window may hide here when it gets small (ui/responsive.py)."""
        from soundboard.ui import responsive as r
        return [(40, "w", r.hide(*self.speech.say_vol_group)),
                (50, "w", r.hide(self.speech.say_stop))]

    def stack_steps(self):
        from soundboard.ui import responsive as r
        return [r.stack(self._cols)]

    def _fx_changed(self, spec: dict):
        self.chain.clear_errors()          # give a bypassed effect another go after an edit
        self.chain.configure(spec)
        self.fx.show_errors({})
        self.fx_changed.emit(spec)

    def poll(self):
        """Call from the UI's status timer: surfaces effects the chain had to bypass."""
        if self.chain.errors:
            self.fx.show_errors(self.chain.errors)

    def rescan_modules(self):
        self.modules = mods.discover()
        mods.load_effects(self.modules)
        self.fx.add_new_effects()
        self.chain.configure(self.fx.spec())
        self.speech.set_modules(self.modules)
        self.addons.show_modules(self.modules)

    def shutdown(self):
        self._meter_timer.stop()
        self.controller.shutdown()
        self.engine.voice_chain = None
