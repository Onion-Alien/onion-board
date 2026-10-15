"""The Voice tab's Languages card: `SpeechPanel` (text-to-speech and live
voice-to-speech, with translation).

It follows panel.py's pattern: it owns its widgets and emits plain dicts
(`changed`) that the main window stores in the config. Two helpers it owns do the
rest: `livevoice` (Start, translating for another voice: livevoice.py) and
`installs` (Windows voices, translation downloads, speech recognition:
speechinstall.py).
"""
from __future__ import annotations

import html
import threading
import time

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
                               QScrollArea, QSlider, QVBoxLayout, QWidget)

from soundboard import modules as mods
from soundboard import langnames, library, net, theme, usage
from soundboard.speech import customvoices, spoken, translation, tts, winvoices
from soundboard.speech.live import SpeechController, clean_settings
from soundboard.ui import busy, fit, icons
from soundboard.ui.panel import bar, fold_button, hint_label, icon_label, section_label
from soundboard.ui.livevoice import MODELS, LiveVoice
from soundboard.ui.speechinstall import SpeechInstalls
from soundboard.wheelguard import no_wheel
from soundboard import errors
from soundboard.i18n import _, ngettext


LIVE_MODULE = "live-voice"
def default_speech_settings() -> dict:
    return {"voice": "", "rate": 0, "gain": 1.0, "model": "base.en", "language": "en",
            "mute_real_voice": True, "voice_fx": True, "translate": "",
            "translate_on": False}


def translations(module_list: list[mods.ModuleInfo]) -> list[mods.ModuleInfo]:
    """The languages the live voice can speak in (translation add-ons), A to Z."""
    return sorted((m for m in module_list if m.kind == "translation" and not m.error),
                  key=langnames.sort_key)


class SpeechPanel(QWidget):
    """Text-to-speech box and live voice-to-speech. `changed(settings)` for the config."""
    changed = Signal(dict)
    _voices = Signal(list, str)
    downloaded = Signal()           # a translation was downloaded or removed
    live_changed = Signal(bool)     # "talk as a computer voice" started / stopped
    lang_changed = Signal()         # Speak in: another language picked (VoicePanel)
    custom_wanted = Signal()        # Add voices: VoicePanel shows the Add-ons tab
    clip_ready = Signal(object, str)   # Save as sound: the line's audio, its name
    _line_saved = Signal(object, str, str)   # its worker: audio (or None), name, error

    def __init__(self, controller: SpeechController, settings: dict,
                 module_list: list[mods.ModuleInfo]):
        super().__init__()
        self.ctl = controller
        self.s = {**default_speech_settings(), **clean_settings(settings)}
        self.module = next((m for m in module_list if m.id == LIVE_MODULE and not m.error),
                           None)
        self.langs = translations(module_list)
        self._last_said = ""   # Save as sound with the box empty keeps this line
        # a typed line plays like a sound, so the bottom bar's volumes set how loud it
        # is; its own volume on the Say bar was one more to find (the saved "gain"
        # stays in the settings for older versions)
        controller.gain = 1.0
        controller.speaker.voice = self.s["voice"]
        controller.speaker.rate = int(self.s["rate"])
        controller.mute_real_voice = self.s["mute_real_voice"]
        controller.voice_fx = self.s["voice_fx"]
        self._voices.connect(self._fill_voices)
        self._voice_fp: frozenset[str] | None = None   # voice tokens when last loaded
        self._warming = False         # _warm_for_a_line's start is under way
        net.on_change(self._refresh_translation)   # Settings > Privacy's switches
        # the live voice / translating (Start, translate_for) and the downloads and
        # installs it needs: each builds its own widgets, placed below
        self.livevoice = live = LiveVoice(self)
        self.installs = inst = SpeechInstalls(self)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)

        # ---- live voice to speech
        # in the order you use it: the language, who says it, then Start
        self.title = section_label(_("Speak another language"))
        v.addWidget(self.title)
        self.lbl_intro = hint_label(_("Talk in your language and others hear another one. "
                                      "Pick it under Speak in."))
        v.addWidget(self.lbl_intro)
        # Speak in belongs to every voice on the tab (VoicePanel._sync_translate).
        # your language in, the chosen one out (through English: spoken.py).
        self.lang_box = QWidget()
        lv = QVBoxLayout(self.lang_box)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(8)
        trow = QHBoxLayout()
        # a language here is on; Don't translate (the list's first) is off. Turning on
        # a voice elsewhere never changes it
        self.lbl_lang = QLabel(_("Speak in"))
        trow.addWidget(self.lbl_lang)
        self.cb_lang = QComboBox()
        self.cb_lang.setAccessibleName(_("Speak in"))
        self.cb_lang.setToolTip(_("Say it in your language; whichever voice is on says it in this "
                                  "language. Each language is a one-time download."))
        self.cb_lang.setMinimumWidth(120)   # a list, not a bar across the card: it
        self.cb_lang.setMaximumWidth(380)   # opens as wide as its names need
        trow.setSpacing(12)
        trow.addWidget(self.cb_lang, 1)
        trow.addStretch(1)
        lv.addLayout(trow)
        self._said_row = QHBoxLayout()   # Said by: filled below, once the voice list is
        lv.addLayout(self._said_row)
        self.lbl_delay = hint_label("")
        theme.set_tone(self.lbl_delay, "warn")
        self.lbl_delay.hide()
        lv.addWidget(self.lbl_delay)
        lv.addWidget(live.lbl_bg)
        lv.addWidget(live.bg_bar, 0, Qt.AlignmentFlag.AlignLeft)
        self.tr_box = QWidget()
        tv = QVBoxLayout(self.tr_box)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(4)
        self.lbl_tr = hint_label("")
        tv.addWidget(self.lbl_tr)
        tv.addLayout(inst.tr_row)
        lv.addWidget(self.tr_box)
        # who says it: the AI voice or the voice changer when one is on, else the
        # computer voice (VoicePanel tells it which: said_by)
        srow = QHBoxLayout()
        srow.setSpacing(12)
        self.lbl_said_by = QLabel(_("Said by"))
        srow.addWidget(self.lbl_said_by, 0, Qt.AlignmentFlag.AlignTop)
        self.lbl_who = QLabel("")
        self.lbl_who.setWordWrap(True)
        self.lbl_who.setMinimumWidth(0)
        self.lbl_who.setTextFormat(Qt.TextFormat.PlainText)
        srow.addWidget(self.lbl_who, 1)
        heads = max(self.lbl_said_by.sizeHint().width(), self.lbl_lang.sizeHint().width())
        self.lbl_said_by.setMinimumWidth(heads)
        self.lbl_lang.setMinimumWidth(heads)
        self._said_row.addLayout(srow)
        self._who = ""   # "ai:name" / "fx:name" / "": who's on elsewhere (said_by)
        # the language and who says it, together in one inner area; Start under it
        self.settings_box = QFrame()
        self.settings_box.setObjectName("voicebox")
        sbl = QVBoxLayout(self.settings_box)
        sbl.setContentsMargins(14, 12, 14, 14)
        sbl.setSpacing(14)
        sbl.addWidget(self.lang_box)
        v.addWidget(self.settings_box)
        v.addWidget(live.start_box)   # Start and its state: shown once it's installed

        # ---- the voice (shared by live and typed speech): set before you press Start
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(14)
        lbl_voice = QLabel(_("Computer voice"))
        grid.addWidget(lbl_voice, 0, 0)
        self.cb_voice = QComboBox()
        self.cb_voice.setToolTip(_("Speaks for you when no AI voice or voice changer is on, "
                                   "and says lines you type"))
        self.cb_voice.addItem(_("Loading voices…"), "")
        self.cb_voice.setEnabled(False)
        # the list shows a stand-in, not the saved voice (still loading, speech failed,
        # or that voice isn't installed now): other settings changes keep the saved one
        self._voice_standin = True
        grid.addWidget(self.cb_voice, 0, 1)
        # custom voices have their own box, opened from next to the list itself
        self.b_add_voices = QPushButton(_("Add voices"))
        icons.set_icon(self.b_add_voices, "plus")
        self.b_add_voices.setToolTip(_("Your own voices: a TTS server on your PC (Kokoro, "
                                       "AllTalk…) or Piper voice packs"))
        self.b_add_voices.clicked.connect(self.show_custom_voices)
        grid.addWidget(self.b_add_voices, 0, 2)
        grid.addWidget(QLabel(_("Speed")), 1, 0)
        self.sl_rate = QSlider(Qt.Orientation.Horizontal)
        self.sl_rate.setMinimumHeight(28)
        self.sl_rate.setRange(-10, 10)
        self.sl_rate.setValue(int(self.s["rate"]))
        grid.addWidget(self.sl_rate, 1, 1)
        for w in (self.cb_voice, self.sl_rate):   # a list and a slider, not bars across
            w.setMinimumWidth(100)                # the whole card at full screen (and
            w.setMaximumWidth(380)                # Add voices fits a narrow window)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 2)
        voice_grid = grid   # under More options: Said by names the voice

        # everything the voice was asked to say, live or typed, newest at the bottom
        lrow = QHBoxLayout()
        lrow.setSpacing(8)
        lrow.addWidget(section_label(_("What the voice said")), 0,
                       Qt.AlignmentFlag.AlignBottom)
        # beside the title, and only once there's something to clear (alone at the far
        # end of an empty list it read as part of some other row)
        self.b_clear = b_clear = QPushButton(_("Clear"), self)
        b_clear.setObjectName("reset")
        b_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        b_clear.hide()
        lrow.addWidget(b_clear, 0, Qt.AlignmentFlag.AlignBottom)
        lrow.addStretch(1)
        self.said_log = QPlainTextEdit()
        self.said_log.setObjectName("speechlog")
        self.said_log.setReadOnly(True)
        self.said_log.setMaximumBlockCount(500)
        # short while empty, growing with what's said up to a few lines, then it scrolls
        def fit_log():
            fm = self.said_log.fontMetrics()
            lines = min(5, max(2, self.said_log.document().blockCount()))
            pad = self.said_log.frameWidth() * 2 + 16
            self.said_log.setFixedHeight(lines * fm.lineSpacing() + pad)
            b_clear.setVisible(not self.said_log.document().isEmpty())
        self.said_log.textChanged.connect(fit_log)
        fit_log()
        self.said_log.setPlaceholderText(_("Nothing yet. Lines show up here as they're "
                                           "spoken."))
        b_clear.clicked.connect(self.said_log.clear)

        # what to install first, in its own inner area above the settings
        v.insertWidget(v.indexOf(self.settings_box), inst.missing)
        v.addWidget(inst.lbl_install)   # install / update progress

        self.btn_opts = fold_button(_("More options"))
        v.addWidget(self.btn_opts, 0, Qt.AlignmentFlag.AlignLeft)
        self.opts = QWidget()
        ov = QVBoxLayout(self.opts)
        ov.setContentsMargins(0, 0, 0, 0)
        ov.setSpacing(10)
        grid = voice_grid
        grid.addWidget(QLabel(_("Recognition")), 2, 0)
        self.cb_model = QComboBox()
        for label, key in MODELS:
            self.cb_model.addItem(label, key)
        self.cb_model.setCurrentIndex(max(0, self.cb_model.findData(self.s["model"])))
        grid.addWidget(self.cb_model, 2, 1)
        grid.addWidget(QLabel(_("Language")), 3, 0)
        self.ed_lang = QLineEdit(spoken.typed(self.s))
        self.ed_lang.setPlaceholderText(_("en, es, de… or auto"))
        self.ed_lang.setToolTip(_("Language you speak (two-letter code). Empty: the app's "
                                  "language. 'auto' guesses."))
        grid.addWidget(self.ed_lang, 3, 1)
        for w in (self.cb_model, self.ed_lang):
            w.setMaximumWidth(380)
        ov.addLayout(grid)
        no_wheel(self.cb_lang, self.cb_voice, self.sl_rate, self.cb_model)
        self.chk_mute = QCheckBox(_("Mute my real mic while the computer voice is on"))
        self.chk_mute.setToolTip(_("Others hear only the spoken voice, not your real one."))
        self.chk_mute.setChecked(self.s["mute_real_voice"])
        ov.addWidget(self.chk_mute)
        self.chk_fx = QCheckBox(_("Put the voice changer on the computer voice"))
        self.chk_fx.setToolTip(_("With a voice picked under Voice changer, the computer voice "
                                 "gets the same effect (a chipmunk robot voice, say)."))
        self.chk_fx.setChecked(self.s["voice_fx"])
        ov.addWidget(self.chk_fx)
        urow = QHBoxLayout()
        urow.setSpacing(8)
        urow.addWidget(inst.b_update)
        inst.tr_row.removeWidget(inst.b_dl_remove)   # rarely wanted: not by Speak in
        urow.addWidget(inst.b_dl_remove)
        urow.addStretch(1)
        ov.addLayout(urow)
        v.addWidget(self.opts)
        self.opts.hide()
        # the log after the options: More options sits with the controls it adds to
        # (DESIGN section 0), not under a box of past lines
        v.addLayout(lrow)
        v.addWidget(self.said_log)
        # ---- custom voices: a TTS server on this PC, a TTS program, Piper voice packs.
        # In the Add-ons tab, under the add-ons list (VoicePanel puts them there);
        # "Add voices" opens it and scrolls to them
        self.custom_box = QWidget()
        ov = QVBoxLayout(self.custom_box)
        ov.setContentsMargins(0, 0, 0, 0)
        ov.setSpacing(8)
        self.custom_title = section_label(_("Custom voices"))   # the card's head
        ov.addWidget(hint_label(_("Use a TTS server running on your PC (Kokoro, AllTalk, any "
                                  "OpenAI-style one) or drop voice packs (Piper) into the "
                                  "voices folder. They join the Voice list above.")))
        crow = QHBoxLayout()
        b_server = QPushButton(_("Add a voice server"))
        icons.set_icon(b_server, "plus")
        b_server.clicked.connect(self._add_voice_server)
        crow.addWidget(b_server)
        b_vfolder = QPushButton(_("Open voices folder"))
        b_vfolder.setToolTip(_("Voice packs and voice settings go here; README.txt in it "
                               "says how"))
        b_vfolder.clicked.connect(lambda: busy.open_folder(customvoices.ensure_folder, b_vfolder))
        crow.addWidget(b_vfolder)
        crow.addStretch(1)
        ov.addLayout(crow)
        self.lbl_custom = hint_label("")
        self.lbl_custom.setTextFormat(Qt.TextFormat.PlainText)    # shows file names and errors
        self.lbl_custom.hide()
        ov.addWidget(self.lbl_custom)
        self.btn_opts.toggled.connect(self.opts.setVisible)
        # ---- the Say bar (placed by VoicePanel at the top of the tab, out of the
        # crowded bottom): typing a line, then the voice's volume
        self.say_bar, row = bar()
        row.addWidget(icon_label("speech", _("Or type a line and it's spoken in the voice")))
        self.ed = QLineEdit()
        self.ed.setPlaceholderText(_("Type a line and press Enter"))
        self.ed.returnPressed.connect(self._say)
        self.ed.textEdited.connect(self._warm_for_a_line)
        row.addWidget(self.ed, 1)
        b_say = QPushButton(_("Say"))
        b_say.clicked.connect(self._say)
        b_stop = QPushButton(_("Stop"))
        b_stop.clicked.connect(lambda: (controller.stop_speaking(),
                                        busy.flash(b_stop, _("✓ Stopped"), 1200)))
        b_keep = self.b_keep = QPushButton(_("Save as sound"))
        b_keep.setToolTip(_("Keep the line typed here as a pad on the Sounds tab, in this "
                            "voice (with the voice changer, if it's on for the computer voice)"))
        # its small icon keeps Qt's own gap: the wider one pushed the Voice tab past the
        # mini player's width
        icons.set_icon(b_keep, "plus", size=12, gap=False)
        b_keep.clicked.connect(self._save_line)
        self._line_saved.connect(self._line_done)
        row.addWidget(b_say)
        row.addWidget(b_keep)
        row.addWidget(b_stop)
        self.say_stop = b_stop

        self.cb_voice.currentIndexChanged.connect(self._voice_picked)
        for sig in (self.sl_rate.valueChanged,
                    self.cb_model.currentIndexChanged,
                    self.chk_mute.toggled, self.chk_fx.toggled):
            sig.connect(self._settings_edited)
        self.ed_lang.editingFinished.connect(self._settings_edited)
        self._fill_langs()
        self.cb_lang.currentIndexChanged.connect(self._lang_picked)
        inst._refresh_module()

        app = QGuiApplication.instance()
        if isinstance(app, QGuiApplication):
            app.applicationStateChanged.connect(inst._app_state)
        def warm_up():
            # the voice list from the last run, if Windows' voices are the same: no
            # speech helper is started for it (it starts when there's a line to say)
            fp = self._voice_fp = winvoices.fingerprint()
            known = tts.remembered_voices(self.s.get(tts.VOICE_CACHE), fp)
            voices = (controller.tts.use_listing(*known) if known
                      else controller.tts.warm_up())
            busy.emit(self._voices, voices, controller.tts.error)
        threading.Thread(target=warm_up, name="tts-warmup", daemon=True).start()

    # ---- text to speech
    def _warm_for_a_line(self, *_):
        """A line is being typed (or the live voice starts): start Windows speech now,
        not when the line is said. With the voice list remembered from the last run it
        isn't running yet, and starting it takes ~2 s."""
        t = self.ctl.tts
        if (self._warming or getattr(t, "running", True)
                or self.ctl.speaker.voice.startswith(customvoices.PREFIX)):
            return
        self._warming = True

        def work():
            try:
                busy.emit(self._voices, t.warm_up(), t.error)
            finally:
                self._warming = False
        threading.Thread(target=work, name="tts-warmup", daemon=True).start()

    def _remember_voices(self):
        """Keep the list the speech helper gave (with the Windows voices it was for) in
        the settings, so the next launch needn't start the helper to list them."""
        listed = getattr(self.ctl.tts, "listed", None)
        if not listed or not self._voice_fp:
            return
        names, langs = listed
        entry = tts.remember_voices(names, langs, self._voice_fp)
        if self.s.get(tts.VOICE_CACHE) != entry:
            self.s[tts.VOICE_CACHE] = entry
            self.changed.emit(dict(self.s))

    def _say(self):
        text = self.ed.text().strip()
        if text:
            self.say_line(text)
            self.ed.clear()

    def say_line(self, text: str):
        """Speak `text` (the Say button, or the control API's /api/say)."""
        usage.used("text-to-speech")   # the name only (usage.py)
        self.ctl.say(text)
        self._log_said(text)
        self._last_said = text

    def _save_line(self):
        """Save as sound: the typed line (else the last one said) spoken into a pad."""
        text = self.ed.text().strip() or self._last_said
        if not text:
            busy.flash(self.b_keep, _("Type a line first"), 1600)
            return
        busy.set_busy(self.b_keep, True)
        name = " ".join(text.split())[:40]

        def work():
            try:
                data, err = self.ctl.render_line(text), ""
            except Exception as e:  # noqa: BLE001 - said under the bar
                data, err = None, errors.plain(e)
            busy.emit(self._line_saved, data, name, err)
        threading.Thread(target=work, name="tts-save", daemon=True).start()

    def _line_done(self, data, name: str, err: str):
        busy.set_busy(self.b_keep, False)
        if data is None:
            self._tts_error(_("Couldn't save that line: {error}", error=err))
            return
        self.clip_ready.emit(data, name)
        busy.flash(self.b_keep, _("✓ Added to Sounds"), 1800)

    def _log_said(self, text: str):
        self.said_log.appendPlainText(f"{time.strftime('%H:%M:%S')}  {text}")
        bar_ = self.said_log.verticalScrollBar()
        bar_.setValue(bar_.maximum())

    def _fill_voices(self, voices: list, error: str):
        self.cb_voice.blockSignals(True)
        self.cb_voice.clear()
        self.cb_voice.addItem(_("Windows default"), "")
        for name in voices:
            self.cb_voice.addItem(customvoices.label(name), name)
        found = self.cb_voice.findData(self.s["voice"])
        self._voice_standin = found < 0
        self.cb_voice.setCurrentIndex(max(0, found))
        self.cb_voice.setEnabled(bool(voices))
        self.cb_voice.blockSignals(False)
        # speak in the voice the list shows: a saved voice that's been uninstalled
        # shows as "Windows default", and asking for it would fail every line
        self.ctl.speaker.voice = self.cb_voice.currentData() or ""
        if not error:
            self._remember_voices()
        m = self._lang()
        voice = self._voice_for(m) if m is not None else ""
        self.installs.voices_loaded(len(voices), error, m is None or bool(voice))
        if self.ctl.live and m is not None and voice and self.ctl.live_voice != voice:
            # talking already: switch to the new voice now, no restart needed
            self.ctl.live_voice = voice
            short = customvoices.label(voice)
            self.livevoice.lbl_state.setText(_("✓ {language} voice found: {voice} speaks from the "
                                               "next line on.", language=langnames.of(m),
                                               voice=short))
        self._refresh_translation()
        problems = getattr(self.ctl.tts, "problems", [])
        custom = getattr(self.ctl.tts, "custom", {})
        self.lbl_custom.setText("\n".join(f"⚠ {p}" for p in problems) if problems else
                                ngettext("{n} custom voice loaded.", "{n} custom voices loaded.",
                                         len(custom)) if custom else "")
        self.lbl_custom.setVisible(bool(self.lbl_custom.text()))
        if error:
            self._tts_error(_("Text-to-speech isn't available: {error}",
                              error=errors.plain(error)))

    def show_custom_voices(self):
        """Open the Add-ons tab (VoicePanel shows it) and bring custom voices into view."""
        self.custom_wanted.emit()
        w = self.custom_box.parentWidget()
        while w is not None and not isinstance(w, QScrollArea):
            w = w.parentWidget()
        if w is not None:
            QTimer.singleShot(0, self, lambda a=w: a.ensureWidgetVisible(
                self.custom_title, 0, 40))   # from its heading

    def _add_voice_server(self):
        """A small form for a TTS server's address; saved as a .json in the voices folder."""
        dlg = QDialog(self)
        fit.watch(dlg)
        dlg.setWindowTitle(_("Add a voice server"))
        form = QFormLayout(dlg)
        form.addRow(hint_label(_("A text-to-speech server running on your PC. Most have an "
                                 "OpenAI-style address ending in /v1/audio/speech; one that "
                                 "takes the text in the address can use {text} in it instead.",
                                 text="{text}")))
        ed_name = QLineEdit()
        ed_name.setPlaceholderText("Kokoro")
        ed_url = QLineEdit()
        ed_url.setPlaceholderText("http://127.0.0.1:8880/v1/audio/speech")
        ed_voice = QLineEdit()
        ed_voice.setPlaceholderText(_("the server's voice name, e.g. af_bella (optional)"))
        ed_model = QLineEdit()
        ed_model.setPlaceholderText(_("optional"))
        ed_key = QLineEdit()
        ed_key.setEchoMode(QLineEdit.EchoMode.Password)
        ed_key.setPlaceholderText(_("only if the server asks for one"))
        for lbl, w in ((_("Name"), ed_name), (_("Address"), ed_url), (_("Voice"), ed_voice),
                       (_("Model"), ed_model), (_("API key"), ed_key)):
            form.addRow(lbl, w)
        err = hint_label("")
        theme.set_tone(err, "error")
        err.hide()
        form.addRow(err)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")
        form.addRow(btns)
        btns.rejected.connect(dlg.reject)

        def ok():
            url = ed_url.text().strip()
            if not url.lower().startswith(("http://", "https://")):
                err.setText(_("The address starts with http:// or https://"))
                err.show()
                return
            name = ed_name.text().strip() or "Voice server"
            try:
                if customvoices.server_path(name).exists() and QMessageBox.question(
                        dlg, _("Add a voice server"),
                        _("There's already a voice server called “{name}”. Replace it?",
                          name=name)
                ) != QMessageBox.StandardButton.Yes:
                    return
                customvoices.save_server(name, url, ed_voice.text().strip(),
                                         ed_model.text().strip(), ed_key.text().strip())
            except OSError as e:
                err.setText(_("Couldn't save it in the voices folder: {error}",
                              error=errors.plain(e)))
                err.show()
                return
            self.s["voice"] = customvoices.PREFIX + name   # pick it once it's loaded
            dlg.accept()
        btns.accepted.connect(ok)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.changed.emit(dict(self.s))
            busy.toast(self, _("✓ Saved “{name}”: loading its voices…",
                               name=html.escape(ed_name.text().strip() or "Voice server")),
                       "ok")
            self.installs._recheck_voices_asked()

    def _tts_error(self, msg: str):
        busy.toast(self, html.escape(msg), "error")

    def _voice_picked(self, *_):
        self._voice_standin = False   # the user chose this one
        self._settings_edited()

    def _settings_edited(self, *_):
        if not self._voice_standin:
            self.s["voice"] = self.cb_voice.currentData() or ""
            self.ctl.speaker.voice = self.s["voice"]
        self.s.update(rate=self.sl_rate.value(),
                      model=self.cb_model.currentData(),
                      spoken=self.ed_lang.text().strip().lower(),
                      mute_real_voice=self.chk_mute.isChecked(),
                      voice_fx=self.chk_fx.isChecked(),
                      # Don't translate keeps the last language (older versions show
                      # it picked, switched off)
                      translate=self.cb_lang.currentData() or self.s["translate"],
                      translate_on=bool(self.cb_lang.currentData()))
        self.ctl.speaker.rate = self.s["rate"]
        self.ctl.set_mute_real_voice(self.s["mute_real_voice"])
        if self.ctl.live and not self.livevoice.bg_for:
            self.ctl.set_replace(self.s["mute_real_voice"])
        self.ctl.voice_fx = self.s["voice_fx"]
        self.changed.emit(dict(self.s))

    # ---- live
    def set_modules(self, module_list: list[mods.ModuleInfo]):
        self.module = next((m for m in module_list if m.id == LIVE_MODULE and not m.error),
                           None)
        self.langs = translations(module_list)
        self._fill_langs()
        self.installs._refresh_module()
        # "Refresh" may come right after installing a voice in Windows settings
        self.installs._recheck_voices()

    # ---- translation
    def _lang(self) -> mods.ModuleInfo | None:
        code = self.cb_lang.currentData()
        return next((m for m in self.langs if m.language == code), None)

    def _fill_langs(self):
        self.cb_lang.blockSignals(True)
        self.cb_lang.clear()
        self.cb_lang.addItem(_("Don't translate"), "")
        for m in self.langs:
            name = langnames.of(m)
            self.cb_lang.addItem(name if m.installed
                                 else _("{language}  (download {size} MB)", language=name,
                                        size=translation.size_mb(m)),
                                 m.language)
        self.cb_lang.setIconSize(QSize(20, 20))
        # the open list shows every name whole, even past the box's own width
        view = self.cb_lang.view()
        view.setMinimumWidth(view.sizeHintForColumn(0) + 40)    # + padding, scroll bar
        self.cb_lang.setCurrentIndex(max(0, self.cb_lang.findData(self.s["translate"]))
                                     if self.s["translate_on"] else 0)
        self.cb_lang.blockSignals(False)
        self.lang_box.setVisible(self.module is not None and self.module.installed
                                 and bool(self.langs))
        self._refresh_translation()

    def _lang_picked(self, *_):
        """A language picked means speaking it; Don't translate is off."""
        if self.cb_lang.currentData():
            usage.used("translate-on")
        self._settings_edited()
        self._refresh_translation()
        self.lang_changed.emit()

    def stop_translating(self):
        """Back to Don't translate (Stop all)."""
        self.cb_lang.setCurrentIndex(0)

    def _lang_on(self) -> mods.ModuleInfo | None:
        """The language picked under Speak in (None: Don't translate)."""
        return self._lang()

    def said_by(self, who: str, name: str = ""):
        """Who's on elsewhere on the tab: "ai" (the AI voice `name`), "fx" (the voice
        changer's voice `name`) or "" (nobody: the computer voice). From VoicePanel."""
        self._who = f"{who}:{name}" if who else ""
        self._show_who()

    def _show_who(self):
        """Said by: who others will hear, and Start's words to match."""
        who, _c, name = self._who.partition(":")
        m = self._lang_on()
        lang = langnames.of(m) if m is not None else ""
        voice = self._voice_for(m) if m is not None and self.ctl.tts.voices else ""
        computer = (customvoices.label(voice or self.cb_voice.currentData() or "")
                    or self.cb_voice.currentText())
        if m is not None and self.ctl.tts.voices and not voice:
            text = _("A {language} computer voice, once it's on this PC (below).",
                     language=lang)
        elif who == "ai" and m is not None:
            text = _("Your AI voice, {voice}. It's on: just talk.", voice=name)
        elif who == "fx" and m is not None:
            text = _("{voice} with your {effect} voice changer. It's on: just talk.",
                     voice=computer, effect=name)
        elif self.livevoice.b_live.isChecked():
            text = _("{voice}, the computer voice. It's on: just talk.", voice=computer)
        else:
            text = _("{voice}, the computer voice, once you press Start.", voice=computer)
        self.lbl_who.setText(text)
        # its height for its width changed: the layouts around keep the old one until told
        self.settings_box.updateGeometry()
        self.livevoice.show_button(lang, bool(who) and m is not None)

    def translating(self) -> mods.ModuleInfo | None:
        """The language picked under Speak in, switched on, downloaded and ready."""
        m = self._lang_on()
        ok = self.module is not None and self.module.installed
        return m if ok and m is not None and m.installed else None

    def _voice_for(self, m: mods.ModuleInfo) -> str:
        return self.ctl.tts.voice_for(m.language, self.s["voice"])

    def _refresh_translation(self):
        # Computing this state temporarily hides its buttons. Restore focus only
        # when the same action is still available in the resulting state.
        focused = self.focusWidget()
        self._refresh_translation_state()
        self._show_who()
        if (focused is not None and focused in self.installs.tr_buttons()
                and focused.isVisible()):
            focused.setFocus(Qt.FocusReason.OtherFocusReason)

    def _refresh_translation_state(self):
        """The box under "Speak in": download it, get its Windows voice, or all set."""
        i = self.installs
        busy.set_busy(i.b_voice_install, i._voice_installing is not None)
        m = self._lang()
        on = self._lang_on()
        if on is not None:
            name = langnames.of(on)
            self.lbl_delay.setText(_(
                "⏱ Others hear you in {language} a few seconds late: each sentence is "
                "written down, translated, then spoken once you've finished it. It works "
                "with the AI voice, the voice changer and the computer voice; your real voice "
                "is muted meanwhile.", language=name))
        self.lbl_delay.setVisible(on is not None)
        downloading = i._dl_busy is not None
        self.tr_box.setVisible(m is not None or downloading)
        for b in i.tr_buttons():
            b.hide()
        i._watch_voices(False)
        if downloading:
            i.b_dl.show()
            i.b_dl_cancel.show()
            return
        if m is None:
            return
        name = langnames.of(m)
        live = self.ctl.live
        if not m.installed:
            self.lbl_tr.setText(_("{language} needs a one-time download of its translation "
                                  "model ({size} MB). After that, translating happens on this "
                                  "PC; what you say never leaves it.", language=name,
                                  size=translation.size_mb(m)))
            i.b_dl.setText(_("Download {language}", language=name))
            i.b_dl.setVisible(not net.offline())   # Offline mode: no dead button
            if net.offline():
                self.lbl_tr.setText(_("{language} needs a one-time download of its "
                                      "translation model ({size} MB). Offline mode is on, so "
                                      "it can't be downloaded now.", language=name,
                                      size=translation.size_mb(m)))
            # downloading voices switched off in Settings > Privacy: greyed, saying why
            i.b_dl.setEnabled(not live and net.allowed("voices"))
            i.b_dl.setToolTip(net.off_message("voices") if not net.allowed("voices") else
                              _("Stop the voice to download this") if live else "")
            return
        i.b_dl_remove.setText(_("Delete the {language} download", language=name))
        i.b_dl_remove.setVisible(not live)
        if not self.ctl.tts.voices:        # still loading, or no speech at all
            self.lbl_tr.setText(_("Translation is quick but not perfect with slang."))
            return
        voice = self._voice_for(m)
        if voice:
            # (Said by names the voice)
            self.lbl_tr.setText(_("Translation is quick but not perfect with slang."))
        else:
            i._watch_voices(True)
            for b in (i.b_voice_install, i.b_voices, i.b_voices_check):
                b.show()
            if i._voice_installing is not None:
                self.lbl_tr.setText(_("Installing the {language} voice\u2026 Say Yes to "
                                      "Windows' permission prompt, then it downloads (a minute "
                                      "or two). It's used by itself as soon as it's in.",
                                      language=name))
                i.b_voice_install.setText(_("Installing\u2026"))
                busy.set_busy(i.b_voice_install, True)
                i.b_voices.hide()
                return
            i.b_voice_install.setText(_("Install the {language} voice", language=name))
            i.b_voice_install.setVisible(not net.offline())   # Windows Update: online
            # Windows Update can't go through the app's connection: off means not at all
            i.b_voice_install.setEnabled(net.allowed("voices"))
            i.b_voice_install.setToolTip(
                i._voice_install_tip if net.allowed("voices") else net.off_message("voices"))
            self.lbl_tr.setText(i._voice_note or (_(
                "\u26a0 Windows has no {language} voice yet, so {language} can't be spoken "
                "properly. Offline mode is on, so it can't be installed now.", language=name)
                if net.offline() else _(
                "\u26a0 Windows has no {language} voice yet, so {language} can't be spoken "
                "properly. Press Install (free, one click); it's picked up by itself "
                "once it's in, even mid-sentence.", language=name)))

    @staticmethod
    def _open_folder(module: mods.ModuleInfo | None = None, btn=None):
        """The module's own folder, or the user add-ons folder when it isn't there yet."""
        d = module.path if module is not None else library.APP_DIR / "modules"

        def make():
            d.mkdir(parents=True, exist_ok=True)
            return d
        busy.open_folder(make, btn)
