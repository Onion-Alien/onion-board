"""The Voice tab's AI voices card: pick a character, press Start, talk.

The add-on (modules/ai-voices) does the converting in its own process; this card
installs it, starts and stops it (soundboard.speech.aivoice) and shows how it's
doing. Settings are a plain dict (`changed`) the Voice tab keeps in the speech
settings under "ai".
"""
from __future__ import annotations

import json
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QSlider, QVBoxLayout, QWidget)

from soundboard import aiaddon, applog, errors
from soundboard import modules as mods
from soundboard.speech import aivoice
from soundboard.ui import busy, icons
from soundboard.ui.panel import hint_label, section_label
from soundboard.wheelguard import no_wheel

IDLE = "Pick a voice, press Start, then just talk."
BACKUP_LABELS = [("A built-in voice (still hides yours)", "voice"),
                 ("My real voice", "mic"), ("Silence", "mute")]


def read_voices(module: mods.ModuleInfo | None) -> list[dict]:
    """The add-on's voices.json "voices" (id, name, description, emoji…); [] if unreadable."""
    if module is None:
        return []
    try:
        data = json.loads((module.path / "voices.json").read_text(encoding="utf-8"))
        return [v for v in data.get("voices", [])
                if isinstance(v, dict) and isinstance(v.get("id"), str) and v.get("name")]
    except (OSError, ValueError, AttributeError):
        return []


def model_downloaded(module: mods.ModuleInfo | None) -> bool:
    return module is not None and all(
        (module.path / "model" / f).is_file()
        for f in ("stream.onnx", "speaker.onnx", "voices.npz"))


class AiVoicePanel(QWidget):
    changed = Signal(dict)
    live_changed = Signal(bool)
    modules_changed = Signal()      # got or removed the add-on: the Voice tab rescans
    _event = Signal(dict)
    _install_line = Signal(str)
    _install_done = Signal(bool, str)

    def __init__(self, controller: aivoice.AiVoiceController, settings: dict,
                 module_list: list[mods.ModuleInfo]):
        super().__init__()
        self.ctl = controller
        self.s = aivoice.clean_settings(settings)
        controller.on_event = self._event.emit
        controller.set_backup(self.s["backup"])
        self._event.connect(self._on_event)
        self._install_line.connect(lambda t: self.lbl_install.setText(t[-160:]))
        self._install_done.connect(self._on_install_done)
        self._installing = False
        self._voice_name = ""
        self.module: mods.ModuleInfo | None = None
        self.voices: list[dict] = []

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        v.addWidget(section_label("AI VOICES"))
        v.addWidget(hint_label("Talk, and others hear a different person: your words and "
                               "tone, another voice, live. It runs on this PC (about one CPU "
                               "core while you talk, nothing while you're quiet); what you "
                               "say never leaves it."))

        self.ready_box = QWidget()
        rv = QVBoxLayout(self.ready_box)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(12)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.addWidget(QLabel("Voice"), 0, 0)
        self.cb_voice = QComboBox()
        self.cb_voice.setToolTip("The character you sound like")
        grid.addWidget(self.cb_voice, 0, 1)
        self.lbl_about = hint_label("")
        grid.addWidget(self.lbl_about, 1, 1)
        grid.addWidget(QLabel("Pitch"), 2, 0)
        prow = QHBoxLayout()
        self.chk_auto = QCheckBox("Match the voice")
        self.chk_auto.setToolTip("Moves your pitch to where this voice naturally sits, "
                                 "whoever is talking. Off: your own pitch.")
        self.chk_auto.setChecked(self.s["auto_pitch"])
        prow.addWidget(self.chk_auto)
        self.sl_pitch = QSlider(Qt.Horizontal)
        self.sl_pitch.setRange(-24, 24)            # half semitones
        self.sl_pitch.setValue(int(round(self.s["pitch"] * 2)))
        self.sl_pitch.setMinimumHeight(28)
        self.sl_pitch.setToolTip("Higher or lower than that, in semitones")
        prow.addWidget(self.sl_pitch, 1)
        self.lbl_pitch = QLabel("")
        self.lbl_pitch.setMinimumWidth(48)
        prow.addWidget(self.lbl_pitch)
        grid.addLayout(prow, 2, 1)
        grid.setColumnStretch(1, 1)
        rv.addLayout(grid)
        self.b_start = QPushButton("Start the AI voice")
        icons.set_icon(self.b_start, "mic", "on_accent", "on_accent")
        self.b_start.setCheckable(True)
        self.b_start.setMinimumHeight(40)
        self.b_start.setObjectName("primary")
        self.b_start.toggled.connect(self._toggle)
        rv.addWidget(self.b_start, 0, Qt.AlignLeft)
        self.lbl_state = QLabel(IDLE)
        self.lbl_state.setTextFormat(Qt.PlainText)
        self.lbl_state.setObjectName("muted")
        self.lbl_state.setWordWrap(True)
        rv.addWidget(self.lbl_state)
        v.addWidget(self.ready_box)

        self.missing = QWidget()
        mv = QVBoxLayout(self.missing)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(12)
        self.lbl_missing = hint_label("")
        mv.addWidget(self.lbl_missing)
        mrow = QHBoxLayout()
        self.b_install = QPushButton("Install AI voices")
        icons.set_icon(self.b_install, "plus")
        self.b_install.setToolTip("One-time download, about 90 MB. Needs Python 3.12+.")
        self.b_install.clicked.connect(self._install)
        mrow.addWidget(self.b_install)
        self.b_get = QPushButton("Get AI voices")
        icons.set_icon(self.b_get, "plus")
        self.b_get.setToolTip("An optional add-on: about 55 MB, from this project's GitHub "
                              "page. Needs Python 3.12+ from python.org.")
        self.b_get.clicked.connect(self._get)
        mrow.addWidget(self.b_get)
        mrow.addStretch(1)
        mv.addLayout(mrow)
        v.addWidget(self.missing)
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
        ov.setSpacing(10)
        brow = QHBoxLayout()
        brow.addWidget(QLabel("If the AI voice stops"))
        self.cb_backup = QComboBox()
        for label, key in BACKUP_LABELS:
            self.cb_backup.addItem(label, key)
        self.cb_backup.setCurrentIndex(max(0, self.cb_backup.findData(self.s["backup"])))
        self.cb_backup.setToolTip("What others hear if the AI voice crashes or can't keep "
                                  "up: by default a built-in voice changer preset, so your "
                                  "real voice still isn't heard.")
        brow.addWidget(self.cb_backup, 1)
        ov.addLayout(brow)
        self.b_update = QPushButton("Update AI voices")
        self.b_update.setToolTip("Runs its install again (and fetches the voice model if "
                                 "it's missing). Needs Python 3.12+.")
        self.b_update.clicked.connect(self._install)
        urow = QHBoxLayout()
        urow.addWidget(self.b_update)
        self.b_remove = QPushButton("Remove AI voices")
        self.b_remove.setToolTip("Deletes the add-on, its voice model and its Python "
                                 "environment from this PC. Get it again any time.")
        self.b_remove.clicked.connect(self._remove)
        urow.addWidget(self.b_remove)
        urow.addStretch(1)
        ov.addLayout(urow)
        self.lbl_credits = hint_label("")
        ov.addWidget(self.lbl_credits)
        v.addWidget(self.opts)
        self.opts.hide()
        self.btn_opts.toggled.connect(lambda on: (
            self.opts.setVisible(on),
            icons.set_icon(self.btn_opts, "fold_open" if on else "fold", "muted", "text",
                           size=12)))
        no_wheel(self.cb_voice, self.sl_pitch, self.cb_backup)

        self.cb_voice.currentIndexChanged.connect(self._voice_picked)
        self.chk_auto.toggled.connect(self._auto_toggled)
        self.sl_pitch.valueChanged.connect(self._pitch_moved)
        self.sl_pitch.sliderReleased.connect(self._pitch_released)
        self.cb_backup.currentIndexChanged.connect(self._backup_picked)
        self._show_pitch()
        self.set_modules(module_list)

    # ------------------------------------------------------------ modules
    def set_modules(self, module_list: list[mods.ModuleInfo], voices: list[dict] | None = None):
        """`voices`: the add-on's read_voices(), when a worker already read them."""
        self.module = next((m for m in module_list
                            if m.id == aivoice.MODULE_ID and not m.error), None)
        self.voices = read_voices(self.module) if voices is None else voices
        self.cb_voice.blockSignals(True)
        self.cb_voice.clear()
        for vo in self.voices:
            self.cb_voice.addItem(f"{vo.get('emoji', '')} {vo['name']}".strip(), vo["id"])
        i = self.cb_voice.findData(self.s["voice"])
        self.cb_voice.setCurrentIndex(max(0, i))
        self.cb_voice.blockSignals(False)
        self._show_about()
        self.lbl_credits.setText(self.module.credits if self.module else "")
        self._refresh()

    def _refresh(self):
        m = self.module
        ok = m is not None and m.installed and model_downloaded(m) and bool(self.voices)
        self.ready_box.setVisible(ok)
        self.missing.setVisible(not ok)
        self.b_install.setVisible(m is not None and not ok)
        self.b_get.setVisible(m is None)
        self.b_update.setVisible(m is not None)
        self.b_remove.setVisible(m is not None and aiaddon.removable(m))
        self.btn_opts.setVisible(m is not None)
        if m is None:
            self.opts.hide()
            self.btn_opts.setChecked(False)
            self.lbl_missing.setText(
                "AI voices are an optional add-on (about 55 MB, the voice model and its "
                "runtime). Nothing is downloaded until you press Get AI voices.")
        elif not ok:
            self.lbl_missing.setText("AI voices need a one-time install first: about 90 MB "
                                     "(the voice model and its runtime). Needs Python 3.12+ "
                                     "from python.org.")
            self.lbl_missing.setToolTip(str(m.path))

    # ------------------------------------------------------------ settings
    def _emit(self):
        self.changed.emit(dict(self.s))

    def _voice(self) -> dict:
        vid = self.cb_voice.currentData() or ""
        return next((vo for vo in self.voices if vo["id"] == vid), {})

    def _show_about(self):
        self.lbl_about.setText(str(self._voice().get("description", "")))

    def _voice_picked(self, *_):
        self.s["voice"] = self.cb_voice.currentData() or ""
        self._show_about()
        if self.ctl.running:
            self.ctl.set_voice(self.s["voice"], self.s["pitch"])
            self._voice_name = self._voice().get("name", "")
            self.lbl_state.setText(f"● switching to {self._voice_name}…")
        self._emit()

    def _auto_toggled(self, on: bool):
        self.s["auto_pitch"] = on
        self.ctl.set_auto_pitch(on)
        self._emit()

    def _show_pitch(self):
        st = self.sl_pitch.value() / 2
        self.lbl_pitch.setText("0" if st == 0 else f"{st:+g}")

    def _pitch_moved(self, _v):
        self._show_pitch()
        if not self.sl_pitch.isSliderDown():
            self._pitch_released()

    def _pitch_released(self):
        st = self.sl_pitch.value() / 2
        if st != self.s["pitch"]:
            self.s["pitch"] = st
            if self.ctl.running:
                self.ctl.set_voice(self.s["voice"], st)
            self._emit()

    def _backup_picked(self, *_):
        self.s["backup"] = self.cb_backup.currentData() or "voice"
        self.ctl.set_backup(self.s["backup"])
        self._emit()

    # ------------------------------------------------------------ start / stop
    def is_on(self) -> bool:
        return self.b_start.isChecked()

    def stop(self):
        if self.b_start.isChecked():
            self.b_start.setChecked(False)

    def _toggle(self, on: bool):
        if on and not self.ctl.running:
            if self.module is None:
                self._set_ui(False, IDLE)
                return
            try:
                self.ctl.start(self.module, self.s["voice"] or self.cb_voice.currentData() or "",
                               self.s["auto_pitch"], self.s["pitch"])
            except RuntimeError as e:
                self._set_ui(False, f"⚠ {errors.plain(e)}")
                return
            self._voice_name = self._voice().get("name", "")
            self._set_ui(True, "starting… (a built-in voice covers you until it's ready)")
        elif not on and self.ctl.running:
            self.ctl.stop()
            self._set_ui(False, IDLE)

    def _set_ui(self, on: bool, state: str):
        self.b_start.blockSignals(True)
        self.b_start.setChecked(on)
        self.b_start.blockSignals(False)
        self.b_start.setText("Stop the AI voice" if on else "Start the AI voice")
        self.b_update.setEnabled(not on and not self._installing)
        self.lbl_state.setText(state)
        self.live_changed.emit(on)

    def _on_event(self, ev: dict):
        t = ev.get("type")
        text = str(ev.get("text", ""))
        if t == "status":
            self.lbl_state.setText(text)
        elif t == "ready":
            msg = f"● you sound like {self._voice_name or 'the voice'}"
            if ev.get("slow"):
                msg += (" ⚠ This PC is slow for AI voices: games may stutter. A voice "
                        "changer preset (left) is much lighter.")
            self.lbl_state.setText(msg)
        elif t == "stats":
            self.lbl_state.setText(
                f"● you sound like {self._voice_name or 'the voice'} · CPU "
                f"{float(ev.get('cpu', 0)):.0f}% · about "
                f"{aivoice.LATENCY_S * 1000:.0f} ms behind you")
        elif t == "error":
            self.lbl_state.setText(f"⚠ {text}")
        elif t == "stopped" and self.ctl.running:
            backup = self.cb_backup.currentText().lower()
            self.lbl_state.setText(f"⚠ The AI voice stopped{': ' + text if text else ''}. "
                                   f"Others now hear {backup}. Press Stop, then Start to "
                                   "try again.")

    # ------------------------------------------------------------ get / remove
    def _get(self):
        if self._installing:
            return
        self._installing = True
        self.b_get.setEnabled(False)
        self.b_get.setText("Getting AI voices…")
        self.lbl_install.show()
        self.lbl_install.setText("asking GitHub for the add-on…")

        def progress(done: int, total: int):
            if total:
                busy.emit(self._install_line, f"downloading: {done * 100 // total} % of "
                                              f"{total / 1e6:.0f} MB")

        def work():
            try:
                offer = aiaddon.latest()
                if offer is None:
                    raise mods.ModuleError("there's no AI voices add-on to download yet")
                info = aiaddon.install(aiaddon.fetch(offer, progress))
                busy.emit(self._install_line, "setting up its Python environment (a few minutes)…")
                ok = mods.install(info, lambda line: busy.emit(self._install_line, line))
                busy.emit(self._install_done, ok, "")
            except Exception as e:  # noqa: BLE001 - the button must come back
                if not isinstance(e, (mods.ModuleError, OSError)):   # a bug: report it
                    applog.report(where="AI voices download")
                busy.emit(self._install_done, False, aiaddon.friendly(e))

        threading.Thread(target=work, name="ai-voices-get", daemon=True).start()

    def _remove(self):
        m = self.module
        if m is None or self.ctl.running or self._installing:
            return

        def go():
            aiaddon.remove(m)

        def done(_r=None):
            self.modules_changed.emit()
            busy.toast(self, "AI voices are removed.", "ok")

        busy.run_busy(self.b_remove, "Removing…", go, done)

    # ------------------------------------------------------------ install
    def _install(self):
        m = self.module
        if m is None or self._installing:
            return
        self._installing = True
        for b in (self.b_install, self.b_update, self.b_start):
            b.setEnabled(False)
        self.b_install.setText("Installing… (a few minutes)")
        self.lbl_install.show()
        self.lbl_install.setText("starting…")

        def work():
            try:
                ok = mods.install(m, lambda line: busy.emit(self._install_line, line))
                busy.emit(self._install_done, ok, "")
            except Exception as e:  # noqa: BLE001 - the buttons must come back
                applog.report(where="module install")
                busy.emit(self._install_done, False, errors.plain(e))

        threading.Thread(target=work, name="ai-voices-install", daemon=True).start()

    def _on_install_done(self, ok: bool, err: str = ""):
        self._installing = False
        for b in (self.b_install, self.b_update, self.b_start, self.b_get):
            b.setEnabled(True)
        self.b_install.setText("Install AI voices")
        self.b_get.setText("Get AI voices")
        if ok:
            self.lbl_install.hide()
            self.modules_changed.emit()     # a fresh download is a new module folder
            self._refresh()
            busy.toast(self, "AI voices are installed. Pick a voice and press Start.", "ok")
        else:
            self.lbl_install.setText(f"⚠ Install failed: {err or self.lbl_install.text()}. "
                                     "Press it again to retry; if it keeps failing, run "
                                     "install.bat in the add-on's folder to see why.")

    def shutdown(self):
        self.ctl.shutdown()
