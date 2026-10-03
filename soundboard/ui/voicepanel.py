"""The Voice panel: voice changer, text-to-speech, live voice-to-speech, add-ons.

`VoiceFxPanel` and `SpeechPanel` follow panel.py's pattern: they own their widgets
and emit plain dicts (`changed`) that the main window stores in the config.
`VoicePanel` lays them out as the Voice tab (cards + the tab's bottom bar).
"""
from __future__ import annotations

import html
import os
import re
import threading
import time

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFormLayout, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                               QScrollArea, QSlider, QVBoxLayout, QWidget)

from soundboard import applog
from soundboard import modules as mods
from soundboard import voicefx
from soundboard import library, theme
from soundboard.speech import customvoices, translation, winvoices
from soundboard.speech.live import SpeechController, clean_settings
from soundboard.ui import art, icons
from soundboard.ui.panel import (VolumeControl, bar, card, hint_label, icon_label,
                                 section_label, vsep)
from soundboard.ui.responsive import FitWidth
from soundboard.ui.widgets import Meter
from soundboard.wheelguard import no_wheel

CUSTOM = "Custom"
TILE_ART = 30     # px: a voice tile's picture (when there is one, see ui/art.py)
LIVE_MODULE = "live-voice"
IDLE_HINT = "Press Start, then just talk."
MODELS = [("Fast (base.en)", "base.en"), ("Fastest (tiny.en)", "tiny.en"),
          ("Accurate (small.en)", "small.en"), ("Any language (base)", "base"),
          ("Any language, accurate (small)", "small")]


def default_fx_spec() -> dict:
    return {"enabled": False, "preset": CUSTOM, "effects": {}}


def default_speech_settings() -> dict:
    return {"voice": "", "rate": 0, "gain": 1.0, "model": "base.en", "language": "en",
            "mute_real_voice": True, "translate": ""}


def translations(module_list: list[mods.ModuleInfo]) -> list[mods.ModuleInfo]:
    """The languages the live voice can speak in (translation add-ons), A to Z."""
    return sorted((m for m in module_list if m.kind == "translation" and not m.error),
                  key=lambda m: m.language_name or m.language)


# =========================================================================== voice changer

class ParamSlider(QWidget):
    changed = Signal()

    def __init__(self, q: voicefx.Param, value: float):
        super().__init__()
        self.q = q
        self.steps = max(1, int(round((q.hi - q.lo) / q.step))) if q.step else 200
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

    def set_param(self, q: voicefx.Param):
        """Swap the range (keeps the value, clamped into the new one)."""
        v = self.value()
        self.q = q
        self.steps = max(1, int(round((q.hi - q.lo) / q.step))) if q.step else 200
        self.slider.blockSignals(True)
        self.slider.setRange(0, self.steps)
        self.slider.blockSignals(False)
        self.set_value(v)

    def value(self) -> float:
        return self.q.lo + (self.q.hi - self.q.lo) * self.slider.value() / self.steps

    def set_value(self, v: float):
        v = self.q.clamp(v)
        span = (self.q.hi - self.q.lo) or 1.0
        self.slider.blockSignals(True)
        self.slider.setValue(int(round((v - self.q.lo) / span * self.steps)))
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
        theme.set_tone(self.err, "error")
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


PRESET_ICONS = voicefx.PRESET_ICONS
POWER_TEXT = {False: "Voice changer is OFF  —  pick a voice below to turn it on",
              True: "ON  —  everyone hears your changed voice"}
POWER_SHORT = {False: "Voice changer is OFF", True: "ON  —  everyone hears it"}   # narrow


class VoiceFxPanel(QWidget):
    """The voice changer: one big on/off switch, a grid of voices to pick from, a
    way to hear yourself, and (folded away) the individual effects for fine-tuning.

    `changed(spec)` with spec = {"enabled", "preset", "effects": {type: {...}}}.
    `hear_toggled(bool)` asks the window to switch "Hear what they hear" on or off.
    `chat_help()` asks for the Discord guide; `tip_dismissed()` means "Got it" on the
    Discord notice (the window remembers it)."""
    changed = Signal(dict)
    hear_toggled = Signal(bool)
    chat_help = Signal()
    tip_dismissed = Signal()

    COLS = 3

    def __init__(self, spec: dict):
        super().__init__()
        # cleaned: a damaged setting (hand-edited, an old backup) mustn't stop the app
        spec = {**default_fx_spec(), **voicefx.clean_spec(spec)}
        self._preset = spec.get("preset") if spec.get("preset") in voicefx.PRESETS else CUSTOM
        # "My own mix" while a preset is on, so picking a preset never loses it
        effects, custom = dict(spec.get("effects", {})), dict(spec.get("custom", {}))
        self._custom: dict = custom or (effects if self._preset == CUSTOM else {})
        # Fine-tune holds your own mix, not a preset you nudged (that shows as Custom
        # too, but mustn't replace the mix you made)
        self._own = self._preset == CUSTOM and self._custom == effects
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
        # the switch, your mic level and "Hear my voice" side by side: everything you
        # need to try a voice is up here, next to the voice tiles
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(self.btn_power, 3)
        self.btn_hear = QPushButton("Hear my voice")
        self.btn_hear.setObjectName("miccheck")
        self.btn_hear.setCheckable(True)
        self.btn_hear.setMinimumHeight(42)
        self.btn_hear.setToolTip("Hear my voice (only me): plays your mic, changed, into your "
                                 "headphones, the same as “Hear what they hear”. Click again "
                                 "to stop.")
        icons.set_icon(self.btn_hear, "ear", checked_color="#ffffff")
        self.btn_hear.toggled.connect(self.hear_toggled)
        top.addWidget(icon_label("mic", "Your mic level"))
        self.meter = Meter()
        self.meter.setMinimumWidth(60)
        self.meter.setToolTip("Your mic level: it moves when you talk")
        top.addWidget(self.meter, 1)
        top.addWidget(self.btn_hear)
        v.addLayout(top)

        # ---- the Discord catch (shown with the changer on, until "Got it")
        # Measured in a real call: with Discord's default Input Profile (Voice
        # Isolation) a deep voice arrived ~20% of the time; on Studio, 93% at -0.8 dB.
        self.tip = QFrame()
        tl = QHBoxLayout(self.tip)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(8)
        tip_text = hint_label("⚠ Discord deletes most of a changed voice unless its "
                              "<b>Input Profile</b> is <b>Studio</b> (Settings → Voice & "
                              "Video). Game voice chats' noise suppression does the same.")
        theme.set_tone(tip_text, "warn")
        tl.addWidget(tip_text, 1)
        self.btn_tip_help = QPushButton("Show me how")
        self.btn_tip_help.clicked.connect(self.chat_help)
        tl.addWidget(self.btn_tip_help)
        self.btn_tip_ok = QPushButton("Got it")
        self.btn_tip_ok.clicked.connect(self._tip_ok)
        tl.addWidget(self.btn_tip_ok)
        self._tip_enabled = True
        v.addWidget(self.tip)

        # ---- pick a voice
        v.addWidget(QLabel("<b>Pick a voice</b>"))
        grid = self._tile_grid = QGridLayout()
        grid.setSpacing(6)
        self._tile_cols = self.COLS
        self._short = False   # the switch's short text (a narrow window)
        self.tiles = QButtonGroup(self)
        self.tiles.setExclusive(True)
        self._tile: dict[str, QPushButton] = {}
        names = list(voicefx.PRESETS) + [CUSTOM]
        for i, name in enumerate(names):
            title = "My own mix" if name == CUSTOM else name
            pic = art.icon(art.voice_key(name))
            if pic is not None:
                b = QPushButton(pic, title)
                b.setIconSize(QSize(TILE_ART, TILE_ART))
                b.setProperty("art", True)
            else:
                b = QPushButton(f"{PRESET_ICONS.get(name, '🎛️')}  {title}" if name != CUSTOM
                                else f"🎚️  {title}")
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

        # ---- fine-tune (folded away)
        self.btn_more = QPushButton("Fine-tune effects")
        self.btn_more.setObjectName("fold")
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
        """Choose a voice (a preset name or CUSTOM) and turn the changer on. Your own
        mix is kept aside while a preset is on, and comes back with "My own mix"."""
        mine = self._mine()
        if mine and name != CUSTOM:
            self._custom = {t: r.state() for t, r in self.rows.items()}
        self._preset = name
        fx = voicefx.PRESETS.get(name)
        if fx is not None:
            self._own = False
            for t, r in self.rows.items():
                r.load({"on": True, **fx[t]} if t in fx else None)
        elif name == CUSTOM:
            if not mine and self._custom:
                for t, r in self.rows.items():
                    r.load(self._custom.get(t))
            self._own = True
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

    def set_tip_enabled(self, on: bool):
        """Whether the Discord notice may show (False once it's been dismissed)."""
        self._tip_enabled = on
        self._refresh()

    def add_new_effects(self):
        """Add rows for effect types registered since (modules loaded later)."""
        for etype, cls in voicefx.REGISTRY.items():
            if etype in self.rows:
                continue
            r = EffectRow(cls, self._spec_effects.get(etype, {}))
            r.changed.connect(self._edited)
            self.box.addWidget(r)
            self.rows[etype] = r

    def _mine(self) -> bool:
        """Is Fine-tune showing your own mix? A nudged preset counts only while you
        haven't made one."""
        made = any(isinstance(e, dict) and e.get("on") for e in self._custom.values())
        return self._preset == CUSTOM and (self._own or not made)

    def spec(self) -> dict:
        effects = {t: r.state() for t, r in self.rows.items()}
        return {"enabled": self.btn_power.isChecked(), "preset": self._preset,
                "effects": effects,
                "custom": effects if self._mine() else self._custom}

    def show_errors(self, errors: dict[str, str]):
        for t, r in self.rows.items():
            r.set_error(errors.get(t, ""))

    # ------------------------------------------------------------------ internals
    def _on_power(self, on: bool):
        self._refresh()
        self._emit()

    def _tip_ok(self):
        self.set_tip_enabled(False)
        self.tip_dismissed.emit()

    def _show_more(self, on: bool):
        self.more.setVisible(on)
        icons.set_icon(self.btn_more, "fold_open" if on else "fold", "muted", "text", size=12)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_width(self.width())

    def _fit_width(self, width: int):
        """Narrow: the switch's shorter text, then fewer voices a row, down to one."""
        for short, cols in ((False, self.COLS), (True, self.COLS), (True, 2), (True, 1)):
            self._set_shape(short, cols)
            if self.minimumSizeHint().width() <= width:
                return

    def _set_shape(self, short: bool, cols: int):
        if short != self._short:
            self._short = short
            self.btn_power.setText((POWER_SHORT if short else POWER_TEXT)[
                self.btn_power.isChecked()])
        if cols != self._tile_cols:
            self._tile_cols = cols
            g = self._tile_grid
            for b in self.tiles.buttons():
                g.removeWidget(b)
            for i, b in enumerate(self.tiles.buttons()):
                g.addWidget(b, i // cols, i % cols)
            for c in range(self.COLS):
                g.setColumnStretch(c, 1 if c < cols else 0)
        self.layout().activate()

    def _refresh(self):
        on = self.btn_power.isChecked()
        self.btn_power.setText((POWER_SHORT if self._short else POWER_TEXT)[on])
        self.tip.setVisible(on and self._tip_enabled)
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
    _install_done = Signal(bool, str)   # ok, and what went wrong when it wasn't
    _dl_progress = Signal(int, int)
    _dl_done = Signal(str)          # "" when it worked, else what went wrong
    _voice_done = Signal(str, str)  # a Windows voice install: result, what went wrong
    downloaded = Signal()           # a translation was downloaded or removed
    live_changed = Signal(bool)     # "talk as a computer voice" started / stopped

    def __init__(self, controller: SpeechController, settings: dict,
                 module_list: list[mods.ModuleInfo]):
        super().__init__()
        self.ctl = controller
        self.s = {**default_speech_settings(), **clean_settings(settings)}
        self.module = next((m for m in module_list if m.id == LIVE_MODULE and not m.error),
                           None)
        self.langs = translations(module_list)
        self._dl_cancel = False
        self._dl_busy: mods.ModuleInfo | None = None
        self._installing = False
        controller.gain = self.s["gain"]
        controller.speaker.voice = self.s["voice"]
        controller.speaker.rate = int(self.s["rate"])
        controller.mute_real_voice = self.s["mute_real_voice"]
        controller.on_event = self._event.emit
        self._event.connect(self._on_event)
        self._voices.connect(self._fill_voices)
        self._install_line.connect(lambda t: self.lbl_install.setText(t[-160:]))
        self._install_done.connect(self._on_install_done)
        self._dl_progress.connect(self._on_dl_progress)
        self._dl_done.connect(self._on_dl_done)
        self._voice_done.connect(self._on_voice_installed)
        self._voice_installing: mods.ModuleInfo | None = None
        self._voice_note = ""        # how the last voice install went, until it's found
        self._voice_fp: frozenset[str] | None = None   # voice tokens when last loaded
        self._loading_since = time.monotonic()   # a voice (re)load is in flight; 0 when not
        # a voice installed any way at all (here, in Settings, by a script) is noticed
        # by its registry token appearing, and the speech engine reloads to use it
        self._voice_timer = QTimer(self)
        self._voice_timer.setInterval(3000)
        self._voice_timer.timeout.connect(self._poll_voices)

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
        # speak in another language: English in, the chosen language out
        trow = QHBoxLayout()
        self.lbl_lang = QLabel("Speak in")
        trow.addWidget(self.lbl_lang)
        self.cb_lang = QComboBox()
        self.cb_lang.setToolTip("Say it in English; the computer voice says it in this "
                                "language. Each language is a one-time download.")
        trow.addWidget(self.cb_lang, 1)
        lv.addLayout(trow)
        self.tr_box = QWidget()
        tv = QVBoxLayout(self.tr_box)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(4)
        self.lbl_tr = hint_label("")
        tv.addWidget(self.lbl_tr)
        tb = QHBoxLayout()
        self.b_dl = QPushButton("Download")
        icons.set_icon(self.b_dl, "plus")
        self.b_dl.clicked.connect(self._download)
        self.b_dl_cancel = QPushButton("Cancel")
        self.b_dl_cancel.clicked.connect(self._cancel_download)
        self.b_voice_install = QPushButton("Install the voice")
        icons.set_icon(self.b_voice_install, "plus")
        self.b_voice_install.setToolTip("Windows asks for permission once, then downloads its "
                                        "free voice for this language. It's used as soon as "
                                        "it's in; no restart.")
        self.b_voice_install.clicked.connect(self._install_voice)
        self.b_voices = QPushButton("Windows settings")
        self.b_voices.setObjectName("small")
        self.b_voices.setToolTip("Do it by hand: Settings \u2192 Time & language \u2192 Speech "
                                 "\u2192 Add voices. It's picked up by itself once it's in.")
        self.b_voices.clicked.connect(self._get_voice)
        self.b_voices_check = QPushButton("Reload voices")
        self.b_voices_check.setObjectName("small")
        self.b_voices_check.setToolTip("Restart the speech engine to pick up new Windows "
                                       "voices (it also does this by itself)")
        self.b_voices_check.clicked.connect(self._recheck_voices)
        self._voice_wait = False     # sent to Windows settings for a voice; look on return
        self.b_dl_remove = QPushButton("Delete download")
        self.b_dl_remove.setObjectName("small")
        self.b_dl_remove.clicked.connect(self._remove_download)
        for b in (self.b_dl, self.b_dl_cancel, self.b_voice_install, self.b_voices,
                  self.b_voices_check, self.b_dl_remove):
            tb.addWidget(b)
        tb.addStretch(1)
        tv.addLayout(tb)
        lv.addWidget(self.tr_box)
        v.addWidget(self.live_box)

        # ---- the voice (shared by live and typed speech): set before you press Start
        grid = QGridLayout()
        grid.addWidget(QLabel("Voice"), 0, 0)
        self.cb_voice = QComboBox()
        self.cb_voice.addItem("Loading voices…", "")
        self.cb_voice.setEnabled(False)
        grid.addWidget(self.cb_voice, 0, 1)
        # custom voices sit under More options: this gets you there from the list itself
        self.b_add_voices = QPushButton("Add voices…")
        icons.set_icon(self.b_add_voices, "plus")
        self.b_add_voices.setToolTip("Your own voices: a TTS server on your PC (Kokoro, "
                                     "AllTalk…) or Piper voice packs")
        self.b_add_voices.clicked.connect(self.show_custom_voices)
        grid.addWidget(self.b_add_voices, 0, 2)
        grid.addWidget(QLabel("Speed"), 1, 0)
        self.sl_rate = QSlider(Qt.Horizontal)
        self.sl_rate.setRange(-10, 10)
        self.sl_rate.setValue(int(self.s["rate"]))
        grid.addWidget(self.sl_rate, 1, 1)
        grid.setColumnStretch(1, 1)
        v.addLayout(grid)

        self.start_box = QWidget()   # Start and its state: shown with live_box
        lv = QVBoxLayout(self.start_box)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(6)
        self.b_live = QPushButton("Start talking as the voice")
        if (pic := art.icon(art.COMPUTER_VOICE)) is not None:
            self.b_live.setIcon(pic)
            self.b_live.setIconSize(QSize(26, 26))
        else:
            icons.set_icon(self.b_live, "mic", "on_accent", "on_accent")
        self.b_live.setCheckable(True)
        self.b_live.setMinimumHeight(40)
        self.b_live.setObjectName("primary")
        self.b_live.toggled.connect(self._toggle_live)
        lv.addWidget(self.b_live)
        self.lbl_state = QLabel(IDLE_HINT)
        self.lbl_state.setTextFormat(Qt.PlainText)   # shows the module's error text
        self.lbl_state.setObjectName("muted")
        lv.addWidget(self.lbl_state)
        v.addWidget(self.start_box)
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
        v.addWidget(self.missing)
        # install / update progress: outside `missing`, which is hidden for an update
        self.lbl_install = hint_label("")
        self.lbl_install.hide()
        v.addWidget(self.lbl_install)

        self.btn_opts = QPushButton("More options")
        self.btn_opts.setObjectName("fold")
        icons.set_icon(self.btn_opts, "fold", "muted", "text", size=12)
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
        self.b_update = QPushButton("Update speech recognition")
        self.b_update.setToolTip("Runs its install again: picks up what a newer Onion Board "
                                 "needs (translation, for one). Needs Python 3.12+.")
        self.b_update.clicked.connect(self._install)
        ov.addWidget(self.b_update, 0, Qt.AlignLeft)
        # ---- custom voices: a TTS server on this PC, a TTS program, Piper voice packs
        self.custom_head = section_label("CUSTOM VOICES")
        ov.addWidget(self.custom_head)
        ov.addWidget(hint_label("Use a TTS server running on your PC (Kokoro, AllTalk, any "
                                "OpenAI-style one) or drop voice packs (Piper) into the "
                                "voices folder. They join the Voice list above."))
        crow = QHBoxLayout()
        b_server = QPushButton("Add a voice server…")
        icons.set_icon(b_server, "plus")
        b_server.clicked.connect(self._add_voice_server)
        crow.addWidget(b_server)
        b_vfolder = QPushButton("Open voices folder")
        b_vfolder.setToolTip("Voice packs and voice settings go here; README.txt in it says how")
        b_vfolder.clicked.connect(lambda: os.startfile(customvoices.ensure_folder()))  # noqa: S606
        crow.addWidget(b_vfolder)
        crow.addStretch(1)
        ov.addLayout(crow)
        self.lbl_custom = hint_label("")
        self.lbl_custom.setTextFormat(Qt.PlainText)    # shows file names and errors
        self.lbl_custom.hide()
        ov.addWidget(self.lbl_custom)
        v.addWidget(self.opts)
        self.opts.hide()
        self.btn_opts.toggled.connect(lambda on: (
            self.opts.setVisible(on),
            icons.set_icon(self.btn_opts, "fold_open" if on else "fold", "muted", "text",
                           size=12)))
        self.tts_err = hint_label("")
        theme.set_tone(self.tts_err, "error")
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
        vol_lbl = QLabel("Voice volume")
        row.addWidget(vol_lbl)
        self.sl_gain = VolumeControl(self.s["gain"], slider_max=200, typed_max=400,
                                     tip="How loud the spoken voice is")
        row.addWidget(self.sl_gain)
        self.say_vol_group = (sep, vol_icon, vol_lbl, self.sl_gain)
        self.say_stop = b_stop

        for sig in (self.cb_voice.currentIndexChanged, self.sl_rate.valueChanged,
                    self.sl_gain.changed, self.cb_model.currentIndexChanged,
                    self.chk_mute.toggled):
            sig.connect(self._settings_edited)
        self.ed_lang.editingFinished.connect(self._settings_edited)
        self._fill_langs()
        self.cb_lang.currentIndexChanged.connect(self._lang_picked)
        self._refresh_module()

        app = QGuiApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._app_state)
        def warm_up():
            self._voice_fp = winvoices.fingerprint()
            voices, err = controller.tts.warm_up(), controller.tts.error
            try:
                self._voices.emit(voices, err)
            except RuntimeError:   # the panel was closed while the voices loaded
                pass
        threading.Thread(target=warm_up, name="tts-warmup", daemon=True).start()

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
            self.cb_voice.addItem(customvoices.label(name), name)
        self.cb_voice.setCurrentIndex(max(0, self.cb_voice.findData(self.s["voice"])))
        self.cb_voice.setEnabled(bool(voices))
        self.cb_voice.blockSignals(False)
        # speak in the voice the list shows: a saved voice that's been uninstalled
        # shows as "Windows default", and asking for it would fail every line
        self.ctl.speaker.voice = self.cb_voice.currentData() or ""
        self._loading_since = 0.0
        self.b_voices_check.setEnabled(True)
        self.b_voices_check.setText("Reload voices")
        m = self._lang()
        voice = self._voice_for(m) if m is not None else ""
        if m is None or voice:
            self._voice_wait = False
            self._voice_note = ""
        if self.ctl.live and m is not None and voice and self.ctl.live_voice != voice:
            # talking already: switch to the new voice now, no restart needed
            self.ctl.live_voice = voice
            short = customvoices.label(voice)
            self.lbl_state.setText(f"✓ {m.language_name} voice found: {short} speaks "
                                   "from the next line on.")
        self._refresh_translation()
        problems = getattr(self.ctl.tts, "problems", [])
        custom = getattr(self.ctl.tts, "custom", {})
        self.lbl_custom.setText("\n".join(f"⚠ {p}" for p in problems) if problems else
                                f"{len(custom)} custom voice(s) loaded." if custom else "")
        self.lbl_custom.setVisible(bool(self.lbl_custom.text()))
        if error:
            self._tts_error(f"Text-to-speech isn't available: {error}")

    def show_custom_voices(self):
        """Open More options and bring its Custom voices part into view."""
        self.btn_opts.setChecked(True)
        w = self.parentWidget()
        while w is not None and not isinstance(w, QScrollArea):
            w = w.parentWidget()
        if w is not None:
            QTimer.singleShot(0, self, lambda a=w: a.ensureWidgetVisible(self.custom_head, 0, 40))

    def _add_voice_server(self):
        """A small form for a TTS server's address; saved as a .json in the voices folder."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Add a voice server")
        form = QFormLayout(dlg)
        form.addRow(hint_label("A text-to-speech server running on your PC. Most have an "
                               "OpenAI-style address ending in /v1/audio/speech; one that takes "
                               "the text in the address can use {text} in it instead."))
        ed_name = QLineEdit()
        ed_name.setPlaceholderText("Kokoro")
        ed_url = QLineEdit()
        ed_url.setPlaceholderText("http://127.0.0.1:8880/v1/audio/speech")
        ed_voice = QLineEdit()
        ed_voice.setPlaceholderText("the server's voice name, e.g. af_bella (optional)")
        ed_model = QLineEdit()
        ed_model.setPlaceholderText("optional")
        ed_key = QLineEdit()
        ed_key.setEchoMode(QLineEdit.Password)
        ed_key.setPlaceholderText("only if the server asks for one")
        for lbl, w in (("Name", ed_name), ("Address", ed_url), ("Voice", ed_voice),
                       ("Model", ed_model), ("API key", ed_key)):
            form.addRow(lbl, w)
        err = hint_label("")
        theme.set_tone(err, "error")
        err.hide()
        form.addRow(err)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        form.addRow(btns)
        btns.rejected.connect(dlg.reject)

        def ok():
            url = ed_url.text().strip()
            if not url.lower().startswith(("http://", "https://")):
                err.setText("The address starts with http:// or https://")
                err.show()
                return
            name = ed_name.text().strip() or "Voice server"
            customvoices.save_server(name, url, ed_voice.text().strip(),
                                     ed_model.text().strip(), ed_key.text().strip())
            self.s["voice"] = customvoices.PREFIX + name   # pick it once it's loaded
            dlg.accept()
        btns.accepted.connect(ok)
        if dlg.exec() == QDialog.Accepted:
            self.changed.emit(dict(self.s))
            self._recheck_voices()

    def _tts_error(self, msg: str):
        self.tts_err.setText(f"⚠ {msg}")
        self.tts_err.show()

    def _settings_edited(self, *_):
        self.s.update(voice=self.cb_voice.currentData() or "", rate=self.sl_rate.value(),
                      gain=self.sl_gain.value(), model=self.cb_model.currentData(),
                      language=self.ed_lang.text().strip() or "en",
                      mute_real_voice=self.chk_mute.isChecked(),
                      translate=self.cb_lang.currentData() or "")
        self.ctl.speaker.voice = self.s["voice"]
        self.ctl.speaker.rate = self.s["rate"]
        self.ctl.gain = self.s["gain"]
        self.ctl.set_mute_real_voice(self.s["mute_real_voice"])
        self.changed.emit(dict(self.s))

    # ---- live
    def set_modules(self, module_list: list[mods.ModuleInfo]):
        self.module = next((m for m in module_list if m.id == LIVE_MODULE and not m.error),
                           None)
        self.langs = translations(module_list)
        self._fill_langs()
        self._refresh_module()
        # "Refresh" may come right after installing a voice in Windows settings
        self._recheck_voices()

    # ---- translation
    def _lang(self) -> mods.ModuleInfo | None:
        code = self.cb_lang.currentData()
        return next((m for m in self.langs if m.language == code), None)

    def _fill_langs(self):
        self.cb_lang.blockSignals(True)
        self.cb_lang.clear()
        self.cb_lang.addItem("English (as you say it)", "")
        if (pic := art.icon(art.language_key("en"))) is not None:
            self.cb_lang.setItemIcon(0, pic)
        for m in self.langs:
            name = m.language_name or m.language
            self.cb_lang.addItem(name if m.installed
                                 else f"{name}  (download {translation.size_mb(m)} MB)",
                                 m.language)
            if (pic := art.icon(art.language_key(m.language))) is not None:
                self.cb_lang.setItemIcon(self.cb_lang.count() - 1, pic)
        self.cb_lang.setIconSize(QSize(20, 20))
        self.cb_lang.setCurrentIndex(max(0, self.cb_lang.findData(self.s["translate"])))
        self.cb_lang.blockSignals(False)
        self.lbl_lang.setVisible(bool(self.langs))
        self.cb_lang.setVisible(bool(self.langs))
        self._refresh_translation()

    def _lang_picked(self, *_):
        self._settings_edited()
        self._refresh_translation()

    def _voice_for(self, m: mods.ModuleInfo) -> str:
        return self.ctl.tts.voice_for(m.language, self.s["voice"])

    def _refresh_translation(self):
        """The box under "Speak in": download it, get its Windows voice, or all set."""
        m = self._lang()
        busy = self._dl_busy is not None
        self.tr_box.setVisible(m is not None or busy)
        for b in (self.b_dl, self.b_dl_cancel, self.b_voice_install, self.b_voices,
                  self.b_voices_check, self.b_dl_remove):
            b.hide()
        self._watch_voices(False)
        if busy:
            self.b_dl_cancel.show()
            return
        if m is None:
            return
        name = m.language_name or m.language
        live = self.ctl.live
        if not m.installed:
            self.lbl_tr.setText(f"{name} needs a one-time download of its translation model "
                                f"({translation.size_mb(m)} MB). After that, translating "
                                "happens on this PC; what you say never leaves it.")
            self.b_dl.setText(f"Download {name}")
            self.b_dl.show()
            self.b_dl.setEnabled(not live)
            return
        self.b_dl_remove.setVisible(not live)
        if not self.ctl.tts.voices:        # still loading, or no speech at all
            self.lbl_tr.setText(f"Say it in English; the voice says it in {name}.")
            return
        voice = self._voice_for(m)
        if voice:
            short = customvoices.label(voice)
            self.lbl_tr.setText(f"Say it in English; {short} says it in {name}. "
                                "Translation is quick but not perfect with slang.")
        else:
            self._watch_voices(True)
            for b in (self.b_voice_install, self.b_voices, self.b_voices_check):
                b.show()
            if self._voice_installing is not None:
                self.lbl_tr.setText(f"Installing the {name} voice\u2026 Say Yes to Windows' "
                                    "permission prompt, then it downloads (a minute or two). "
                                    "It's used by itself as soon as it's in.")
                self.b_voice_install.setText("Installing\u2026")
                self.b_voice_install.setEnabled(False)
                self.b_voices.hide()
                return
            self.b_voice_install.setText(f"Install the {name} voice")
            self.b_voice_install.setEnabled(True)
            self.lbl_tr.setText(self._voice_note or (
                f"\u26a0 Windows has no {name} voice yet, so {name} can't be spoken "
                "properly. Press Install (free, one click); it's picked up by itself "
                "once it's in, even mid-sentence."))

    # ---- Windows voices
    def _install_voice(self):
        m = self._lang()
        if m is None or self._voice_installing is not None:
            return
        self._voice_installing, self._voice_note = m, ""
        self._refresh_translation()

        def work():
            try:
                self._voice_done.emit(winvoices.install(m.language), "")
            except winvoices.Cancelled:
                self._voice_done.emit("cancelled", "")
            except RuntimeError as e:
                self._voice_done.emit("", str(e))
            except Exception as e:  # noqa: BLE001 - the button must come back
                applog.report(where="windows voice install")
                self._voice_done.emit("", str(e) or type(e).__name__)

        threading.Thread(target=work, name="voice-install", daemon=True).start()

    def _on_voice_installed(self, result: str, err: str):
        m, self._voice_installing = self._voice_installing, None
        name = (m.language_name or m.language) if m is not None else "the"
        if err:
            self._voice_note = (f"\u26a0 Couldn't install the {name} voice: {err}. Press "
                                "Install to try again, or add it in Windows settings.")
        elif result == "cancelled":
            self._voice_note = (f"Windows' permission prompt was closed, so the {name} "
                                "voice wasn't installed. Press Install to try again.")
        elif result == "restart":
            self._voice_note = (f"The {name} voice is installed, but Windows wants the PC "
                                "restarted to finish. After that it's picked up by itself.")
        else:
            self._voice_note = (f"The {name} voice is installed; loading it\u2026 If it "
                                "doesn't appear in a minute, press Reload voices or restart "
                                "the PC.")
        self._refresh_translation()
        if not err and result != "cancelled":
            self._recheck_voices()

    def _get_voice(self):
        self._voice_wait = True
        QDesktopServices.openUrl(QUrl("ms-settings:speech"))

    def _app_state(self, state):
        # back from Windows settings: a voice may have just been installed
        if state == Qt.ApplicationActive and self._voice_wait:
            self._recheck_voices()

    def _watch_voices(self, on: bool):
        if on and not self._voice_timer.isActive():
            self._voice_timer.start()
        elif not on:
            self._voice_timer.stop()

    def _loading(self) -> bool:
        # a load that never answered (it times out well before this) doesn't block forever
        return bool(self._loading_since) and time.monotonic() - self._loading_since < 90

    def _poll_voices(self):
        """Reload the speech engine when Windows' voice list changed since it loaded."""
        if not self._loading() and winvoices.fingerprint() != self._voice_fp:
            self._recheck_voices()

    def _recheck_voices(self):
        """Look for Windows voices again, off the UI thread. Safe while talking: a line
        being spoken waits a second for the engine to come back."""
        if self._loading():
            return
        self._loading_since = time.monotonic()
        self.b_voices_check.setEnabled(False)
        self.b_voices_check.setText("Reloading\u2026")

        def work():
            self._voice_fp = winvoices.fingerprint()
            voices = self.ctl.tts.refresh()
            try:
                self._voices.emit(voices, self.ctl.tts.error)
            except RuntimeError:   # the panel was closed meanwhile
                pass
        threading.Thread(target=work, name="tts-refresh", daemon=True).start()

    def _download(self):
        m = self._lang()
        if m is None or self._dl_busy is not None:
            return
        self._dl_busy, self._dl_cancel = m, False
        self.cb_lang.setEnabled(False)
        self.b_live.setEnabled(False)
        self._refresh_translation()
        self.lbl_tr.setText(f"Downloading {m.language_name}\u2026 0%")

        def work():
            try:
                translation.download(m, self._dl_progress.emit, lambda: self._dl_cancel)
                self._dl_done.emit("")
            except translation.Cancelled:
                self._dl_done.emit("cancelled")
            except RuntimeError as e:
                self._dl_done.emit(str(e))
            except Exception as e:  # noqa: BLE001 - the UI must never stay on "Downloading…"
                applog.report(where="translation download")
                self._dl_done.emit(str(e) or type(e).__name__)

        threading.Thread(target=work, name="translation-download", daemon=True).start()

    def _cancel_download(self):
        self._dl_cancel = True
        self.b_dl_cancel.setEnabled(False)
        if self._dl_busy is not None:
            self.lbl_tr.setText("Cancelling…")

    def _on_dl_progress(self, done: int, total: int):
        m = self._dl_busy
        if m is not None and not self._dl_cancel:
            pct = f"{done * 100 // total}%" if total else f"{done // 1_000_000} MB"
            self.lbl_tr.setText(f"Downloading {m.language_name}\u2026 {pct}")

    def _on_dl_done(self, err: str):
        m, self._dl_busy = self._dl_busy, None
        self.cb_lang.setEnabled(not self.ctl.live)
        self.b_live.setEnabled(not self._installing)
        self.b_dl_cancel.setEnabled(True)
        self._fill_langs()
        if err and m is not None:
            self.lbl_tr.setText("Download cancelled." if err == "cancelled"
                                else f"\u26a0 {m.language_name}: {err}. Check your internet "
                                     "connection and press Download again.")
        self.downloaded.emit()

    def _remove_download(self):
        m = self._lang()
        if m is not None and not self.ctl.live:
            translation.remove(m)
            self._fill_langs()
            self.downloaded.emit()

    def _refresh_module(self):
        m = self.module
        ok = m is not None and m.installed
        self.live_box.setVisible(ok)
        self.start_box.setVisible(ok)
        self.missing.setVisible(not ok)
        self.b_install.setVisible(m is not None and not ok)
        self.b_update.setVisible(m is not None)
        if m is None:
            self.lbl_missing.setText(
                "The live-voice add-on is missing from this copy of Onion Board. Run the "
                "installer again (it comes with every install), then press Refresh below.")
        elif not ok:
            self.lbl_missing.setText("Live voice needs its speech recognition installed first "
                                     "(runs on this PC; what you say never leaves it). "
                                     "Needs Python 3.12+ from python.org.")
            self.lbl_missing.setToolTip(str(m.path))

    def _install(self):
        m = self.module
        if m is None or self._installing:
            return          # one pip at a time: two into the same environment break it
        self._installing = True
        for b in (self.b_install, self.b_update, self.b_live):
            b.setEnabled(False)
        self.b_install.setText("Installing… (a few minutes)")
        self.b_update.setText("Updating… (a few minutes)")
        self.lbl_install.show()
        self.lbl_install.setText("starting…")

        def work():
            try:
                ok = mods.install(m, self._install_line.emit)
                self._install_done.emit(ok, "")
            except Exception as e:  # noqa: BLE001 - the buttons must come back
                applog.report(where="module install")
                self._install_done.emit(False, str(e) or type(e).__name__)

        threading.Thread(target=work, name="module-install", daemon=True).start()

    def _on_install_done(self, ok: bool, err: str = ""):
        self._installing = False
        self.b_install.setEnabled(True)
        self.b_install.setText("Install speech recognition (one time, ~300 MB)")
        self.b_update.setEnabled(not self.ctl.live)
        self.b_update.setText("Update speech recognition")
        self.b_live.setEnabled(self._dl_busy is None)
        if ok:
            self.lbl_install.hide()
            self._refresh_module()
            self.lbl_state.setText("Installed. Press Start and talk.")
        else:
            self.lbl_install.setText(f"⚠ Install failed: {err or self.lbl_install.text()}. "
                                     "Press it again to retry; if it keeps failing, run "
                                     "install.bat in the add-on's folder to see why.")

    def _toggle_live(self, on: bool):
        if on and not self.ctl.live:
            # only our own models: any other name makes the helper download that repo
            model = self.s["model"] if self.s["model"] in {d for _n, d in MODELS} else MODELS[0][1]
            lang = str(self.s["language"]).strip().lower()
            lang = lang if re.fullmatch(r"auto|[a-z]{2,3}", lang) else "en"
            args = ["--model", model, "--language", lang]
            m = self._lang()
            self.ctl.live_voice = None
            if m is not None:
                if not m.installed:
                    self._set_live_ui(False, f"Download {m.language_name} first (above).")
                    return
                args += ["--translate", str(translation.model_dir(m))]
                self.ctl.live_voice = self._voice_for(m) or None
            try:
                self.ctl.start_live(self.module, args)
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
        self.live_changed.emit(on)
        for w in (self.cb_model, self.ed_lang, self.cb_lang):
            w.setEnabled(not on)
        self.b_update.setEnabled(not on and not self._installing)
        self.lbl_state.setText(state)
        self._refresh_translation()

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
            orig = str(ev.get("original", ""))
            self._log_said(f"{text}   (you said: {orig})" if orig else text)
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
            elif m.kind == "translation":
                state = ("downloaded" if m.installed else
                         f"not downloaded ({translation.size_mb(m)} MB): pick it under "
                         "Speak in")
            elif m.kind == "effects":
                state = "loaded" if m.loaded else "not loaded"
            elif m.kind == "triggers":
                state = "on the Triggers tab"
            else:
                state = "ready"
            e = html.escape   # error text is often "<class ...>"-shaped
            lbl = hint_label(f"<b>{e(m.name)}</b> {e(m.version)} · {e(state)}<br>"
                             f"{e(m.description)}")
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
    active_changed = Signal(bool)   # the voice changer or the computer voice is on / off

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
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        page = FitWidth()   # the voice changer fits itself to the width (_fit_width)
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
        self.fx = VoiceFxPanel({**voicefx.clean_spec(fx_spec), "enabled": False})
        self.fx.changed.connect(self._fx_changed)
        fx_card, fv = card()
        fv.addWidget(self.fx)
        lcol.addWidget(fx_card)
        lcol.addStretch(1)

        # right: talk as a computer voice, then add-ons
        self.controller = SpeechController(engine, self.chain, lambda ev: None)
        self.speech = SpeechPanel(self.controller, speech or {}, self.modules)
        self.speech.changed.connect(self.speech_changed)
        self.speech.changed.connect(lambda _s: self._emit_active())   # the tab's picture
        self.speech.downloaded.connect(lambda: self.addons.show_modules(self.modules))
        self.speech.live_changed.connect(lambda _on: self._emit_active())
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

    def showEvent(self, e):
        super().showEvent(e)
        self._meter_timer.start(50)

    def hideEvent(self, e):
        super().hideEvent(e)
        self._meter_timer.stop()   # no wake-ups while another tab is showing

    def _meter(self):
        if self.isVisible():
            e = self.engine
            self.fx.set_level(e.level_mic if e.mic_stream is not None else 0.0)

    def fit_steps(self):
        """What the main window may hide here when it gets small (ui/responsive.py)."""
        from soundboard.ui import responsive as r
        return [(35, "w", r.icon_only(self.fx.btn_hear)),
                (40, "w", r.hide(*self.speech.say_vol_group)),
                (50, "w", r.hide(self.speech.say_stop))]

    def stack_steps(self):
        from soundboard.ui import responsive as r
        return [r.stack(self._cols)]

    def _fx_changed(self, spec: dict):
        self.chain.clear_errors()          # give a bypassed effect another go after an edit
        self.chain.configure(spec)
        self.fx.show_errors({})
        self.fx_changed.emit(spec)
        self._emit_active()

    def is_active(self) -> bool:
        """Something here is changing what others hear from your mic."""
        return self.fx.btn_power.isChecked() or self.speech.b_live.isChecked()

    def _emit_active(self):
        self.active_changed.emit(self.is_active())

    def tab_icon(self) -> str:
        """The Voice tab's icon (icons.set_tab_icon name): while something here is on,
        the picture of who's talking for you (the translated language, the computer
        voice, or the voice changer's voice) when there is one; else the mask."""
        if self.speech.b_live.isChecked():
            key = art.first(art.language_key(self.speech.cb_lang.currentData() or ""),
                            art.COMPUTER_VOICE)
        elif self.fx.btn_power.isChecked():
            key = art.first(art.voice_key(self.fx.preset))
        else:
            key = ""
        return f"art:{key}" if key else "voice"

    def poll(self):
        """Call from the UI's status timer: surfaces effects the chain had to bypass."""
        errors = dict(self.chain.errors)   # the mic thread writes it
        if errors:
            self.fx.show_errors(errors)

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
