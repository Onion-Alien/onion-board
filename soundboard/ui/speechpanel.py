"""The Voice tab's Languages card: `SpeechPanel` (text-to-speech and live
voice-to-speech, with translation).

It follows panel.py's pattern: it owns its widgets and emits plain dicts
(`changed`) that the main window stores in the config.
"""
from __future__ import annotations

import html
import threading
import time

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar,
                               QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget)

from soundboard import applog
from soundboard import modules as mods
from soundboard import langnames, library, net, netlog, theme, usage
from soundboard.speech import customvoices, spoken, translation, tts, winvoices
from soundboard.speech.live import SpeechController, clean_settings
from soundboard.ui import busy, fit, icons
from soundboard.ui.panel import (bar, fold_button, hint_label, icon_button, icon_label,
                                 section_label)
from soundboard.ui.voicefxpanel import Switch, _enable
from soundboard.wheelguard import no_wheel
from soundboard import errors
from soundboard.i18n import _, ngettext


LIVE_MODULE = "live-voice"
IDLE_HINT = _("Press Start, then just talk.")
MODELS = [(_("Fast (base.en)"), "base.en"), (_("Fastest (tiny.en)"), "tiny.en"),
          (_("Accurate (small.en)"), "small.en"), (_("Any language (base)"), "base"),
          (_("Any language, accurate (small)"), "small")]


def default_speech_settings() -> dict:
    return {"voice": "", "rate": 0, "gain": 1.0, "model": "base.en", "language": "en",
            "mute_real_voice": True, "voice_fx": True, "translate": "",
            "translate_on": False}


def translations(module_list: list[mods.ModuleInfo]) -> list[mods.ModuleInfo]:
    """The languages the live voice can speak in (translation add-ons), A to Z."""
    return sorted((m for m in module_list if m.kind == "translation" and not m.error),
                  key=langnames.sort_key)


def _download_bar() -> QProgressBar:
    """A thin download bar (the theme's `downloadprogress`), hidden until there's one."""
    bar = QProgressBar()
    bar.setObjectName("downloadprogress")
    bar.setRange(0, 1000)
    bar.setTextVisible(False)
    bar.setFixedSize(320, 6)
    bar.setAccessibleName(_("Speech model download"))
    bar.hide()
    return bar



class _SameWidth(QObject):
    """Keeps the list `follower` as wide as `source` (two lists in different rows),
    or wider when its picked item wouldn't fit (a narrow window)."""

    def __init__(self, source: QWidget, follower: QComboBox):
        super().__init__(source)
        self._source, self._follower = source, follower
        source.installEventFilter(self)
        follower.currentIndexChanged.connect(lambda _i: self.fit())

    def fit(self):
        f = self._follower
        need = f.fontMetrics().horizontalAdvance(f.currentText()) + 56   # padding + arrow
        if self._source.width() > 0:
            f.setFixedWidth(max(self._source.width(), need))

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Type.Resize:
            self.fit()
        return False


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
        self._dl_cancel = False
        self._dl_busy: mods.ModuleInfo | None = None
        self._installing = False
        self._last_said = ""   # Save as sound with the box empty keeps this line
        # a typed line plays like a sound, so the bottom bar's volumes set how loud it
        # is; its own volume on the Say bar was one more to find (the saved "gain"
        # stays in the settings for older versions)
        controller.gain = 1.0
        controller.speaker.voice = self.s["voice"]
        controller.speaker.rate = int(self.s["rate"])
        controller.mute_real_voice = self.s["mute_real_voice"]
        controller.voice_fx = self.s["voice_fx"]
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
        self._warming = False         # _warm_for_a_line's start is under way
        self._loading_since = time.monotonic()   # a voice (re)load is in flight; 0 when not
        # a voice installed any way at all (here, in Settings, by a script) is noticed
        # by its registry token appearing, and the speech engine reloads to use it
        self._voice_timer = QTimer(self)
        self._voice_timer.setInterval(3000)
        self._voice_timer.timeout.connect(self._poll_voices)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)

        # ---- live voice to speech
        self.title = section_label(_("Speak another language"))
        v.addWidget(self.title)
        self.start_box = QWidget()   # Start and its state: shown with live_box
        sv = QVBoxLayout(self.start_box)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(8)
        action = QHBoxLayout()
        sv.addLayout(action)
        action.setSpacing(14)
        self.b_live = QPushButton(_("Start the computer voice"))
        icons.set_icon(self.b_live, "mic", "on_accent", "on_accent")
        self.b_live.setCheckable(True)
        self.b_live.setMinimumHeight(40)
        self.b_live.setObjectName("primary")
        self.b_live.toggled.connect(self._toggle_live)
        action.addWidget(self.b_live, 0, Qt.AlignmentFlag.AlignTop)
        self.lbl_state = QLabel(IDLE_HINT)
        self.lbl_state.setTextFormat(Qt.TextFormat.PlainText)   # shows the module's error text
        self.lbl_state.setObjectName("muted")
        self.lbl_state.setWordWrap(True)
        self.lbl_state.setMinimumWidth(0)
        action.addWidget(self.lbl_state, 1)
        # the speech model's first download (the helper's "download" events)
        self.dl_bar = _download_bar()
        sv.addWidget(self.dl_bar, 0, Qt.AlignmentFlag.AlignLeft)
        v.addWidget(self.start_box)
        self.lbl_intro = hint_label(_(
            "Talk in your language and others hear another one. Turn on the switch below: the AI "
            "voice or the voice changer says it when one of them is on; otherwise press "
            "Start and a computer voice does."))
        v.addWidget(self.lbl_intro)
        # Speak in belongs to every voice on the tab (VoicePanel._sync_translate).
        # your language in, the chosen one out (through English: spoken.py).
        self.bg_for = ""             # translating for the "ai" voice or the "fx" changer
        self._bg_key: tuple = ()     # (who, language) the running helper was started for
        self._bg_failed: tuple = ()  # the key it last stopped with an error for
        self._bg_warning = False     # lbl_bg shows a ⚠ problem (not a hint)
        self.lang_box = QWidget()
        lv = QVBoxLayout(self.lang_box)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(8)
        trow = QHBoxLayout()
        # its own on/off: turning on a voice elsewhere never starts translating
        self.sw_lang = Switch(_("Translate what you say into this language. Off: every "
                                "voice says it as you do, and the language stays picked."))
        self.sw_lang.setAccessibleName(_("Speak in"))
        self.sw_lang.setChecked(bool(self.s["translate_on"]))
        trow.addWidget(self.sw_lang)
        self.lbl_lang = QLabel(_("Speak in"))
        trow.addWidget(self.lbl_lang)
        self.cb_lang = QComboBox()
        self.cb_lang.setToolTip(_("Say it in your language; whichever voice is on says it in this "
                                  "language. Each language is a one-time download."))
        # as wide as the voice list below (_SameWidth), not a bar across the card:
        # its list opens as wide as the box
        trow.setSpacing(12)                             # the voice grid's spacing
        trow.addWidget(self.cb_lang)
        trow.addStretch(1)
        lv.addLayout(trow)
        self.lbl_delay = hint_label("")
        theme.set_tone(self.lbl_delay, "warn")
        self.lbl_delay.hide()
        lv.addWidget(self.lbl_delay)
        self.lbl_bg = hint_label("")
        self.lbl_bg.setTextFormat(Qt.TextFormat.PlainText)     # shows the helper's error text
        self.lbl_bg.hide()
        lv.addWidget(self.lbl_bg)
        self.bg_bar = _download_bar()   # the same, while translating for another voice
        lv.addWidget(self.bg_bar, 0, Qt.AlignmentFlag.AlignLeft)
        self.tr_box = QWidget()
        tv = QVBoxLayout(self.tr_box)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(4)
        self.lbl_tr = hint_label("")
        tv.addWidget(self.lbl_tr)
        tb = QHBoxLayout()
        self.b_dl = QPushButton(_("Download"))
        icons.set_icon(self.b_dl, "plus")
        self.b_dl.clicked.connect(self._download)
        self.b_dl_cancel = QPushButton(_("Cancel"))
        self.b_dl_cancel.clicked.connect(self._cancel_download)
        self.b_voice_install = QPushButton(_("Install the voice"))
        icons.set_icon(self.b_voice_install, "plus")
        self._voice_install_tip = _("Windows asks for permission once, then downloads its "
                                    "free voice for this language. It's used as soon as "
                                    "it's in; no restart.")
        self.b_voice_install.setToolTip(self._voice_install_tip)
        net.on_change(self._refresh_translation)   # Settings > Privacy's switches
        net.on_change(self._net_changed)
        self.b_voice_install.clicked.connect(self._install_voice)
        self.b_voices = QPushButton(_("Windows settings"))
        self.b_voices.setObjectName("small")
        self.b_voices.setToolTip(_("Do it by hand: Settings \u2192 Time & language \u2192 "
                                   "Speech \u2192 Add voices. It's picked up by itself once "
                                   "it's in."))
        self.b_voices.clicked.connect(self._get_voice)
        self.b_voices_check = QPushButton(_("Reload voices"))
        self.b_voices_check.setObjectName("small")
        self.b_voices_check.setToolTip(_("Restart the speech engine to pick up new Windows "
                                         "voices (it also does this by itself)"))
        self.b_voices_check.clicked.connect(self._recheck_voices_asked)
        self._voices_asked = False   # the button was pressed: say what it found
        self._voices_again = False   # a reload was asked for while one ran
        self._voice_wait = False     # sent to Windows settings for a voice; look on return
        self.b_dl_remove = QPushButton(_("Delete download"))
        self.b_dl_remove.setObjectName("small")
        self.b_dl_remove.clicked.connect(self._remove_download)
        for b in (self.b_dl, self.b_dl_cancel, self.b_voice_install, self.b_voices,
                  self.b_voices_check, self.b_dl_remove):
            tb.addWidget(b)
        tb.addStretch(1)
        tv.addLayout(tb)
        lv.addWidget(self.tr_box)
        # the voice's settings, together in one inner area: Speak in, the voice, speed
        self.settings_box = QFrame()
        self.settings_box.setObjectName("voicebox")
        sbl = QVBoxLayout(self.settings_box)
        sbl.setContentsMargins(14, 12, 14, 14)
        sbl.setSpacing(14)
        sbl.addWidget(self.lang_box)
        v.addWidget(self.settings_box)

        # ---- the voice (shared by live and typed speech): set before you press Start
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(14)
        lbl_voice = QLabel(_("Computer voice"))
        grid.addWidget(lbl_voice, 0, 0)
        # Speak in's box starts where the voice list does
        self.lbl_lang.setMinimumWidth(max(self.lbl_lang.sizeHint().width(),
                                          lbl_voice.sizeHint().width()))
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
            w.setMinimumWidth(160)                # the whole card at full screen (and
            w.setMaximumWidth(380)                # Add voices fits a narrow window)
        _SameWidth(self.cb_voice, self.cb_lang)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 2)
        sbl.addLayout(grid)

        # everything the voice was asked to say, live or typed, newest at the bottom
        lrow = QHBoxLayout()
        lrow.setSpacing(8)
        lrow.addWidget(section_label(_("What the voice said")), 0,
                       Qt.AlignmentFlag.AlignBottom)
        # beside the title, and only once there's something to clear (alone at the far
        # end of an empty list it read as part of some other row)
        self.b_clear = b_clear = QPushButton(_("Clear"))
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
        self.missing = QFrame()
        self.missing.setObjectName("voicebox")
        mv = QVBoxLayout(self.missing)
        mv.setContentsMargins(14, 12, 14, 14)
        mv.setSpacing(10)
        self.lbl_missing = hint_label("")
        mv.addWidget(self.lbl_missing)
        mrow = QHBoxLayout()
        self.b_install = QPushButton(_("Install speech recognition"))
        icons.set_icon(self.b_install, "plus")
        self.b_install.setToolTip(_("One-time download, about 300 MB."))
        self.b_install.clicked.connect(self._install)
        mrow.addWidget(self.b_install)
        b_open = icon_button("folder", _("Open folder"), hover=False)
        b_open.clicked.connect(lambda: self._open_folder(self.module, b_open))
        mrow.addWidget(b_open)
        mrow.addStretch(1)
        mv.addLayout(mrow)
        v.insertWidget(v.indexOf(self.settings_box), self.missing)   # first thing to do
        # install / update progress: outside `missing`, which is hidden for an update
        self.lbl_install = hint_label("")
        self.lbl_install.hide()
        v.addWidget(self.lbl_install)

        self.btn_opts = fold_button(_("More options"))
        v.addWidget(self.btn_opts, 0, Qt.AlignmentFlag.AlignLeft)
        self.opts = QWidget()
        ov = QVBoxLayout(self.opts)
        ov.setContentsMargins(0, 0, 0, 0)
        grid = QGridLayout()
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
        grid.setColumnStretch(1, 1)
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
        self.b_update = QPushButton(_("Update speech recognition"))
        self.b_update.setToolTip(_("Runs its install again: picks up what a newer Onion Board "
                                   "needs (translation, for one)."))
        self.b_update.clicked.connect(self._install)
        ov.addWidget(self.b_update, 0, Qt.AlignmentFlag.AlignLeft)
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
        self.sw_lang.toggled.connect(self._lang_switched)
        self.sw_lang.clicked.connect(lambda on: on and usage.used("translate-on"))
        self._refresh_module()

        app = QGuiApplication.instance()
        if isinstance(app, QGuiApplication):
            app.applicationStateChanged.connect(self._app_state)
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
        self._loading_since = 0.0
        if not error:
            self._remember_voices()
        busy.set_busy(self.b_voices_check, False)
        self.b_voices_check.setText(_("Reload voices"))
        if self._voices_again:   # asked for while that load ran (e.g. a server was added)
            self._voices_again = False
            QTimer.singleShot(0, self, self._recheck_voices)
        if self._voices_asked:
            self._voices_asked = False
            busy.flash(self.b_voices_check,
                       ngettext("✓ {n} voice", "✓ {n} voices", len(voices)) if not error
                       else _("Couldn't load them"))
        m = self._lang()
        voice = self._voice_for(m) if m is not None else ""
        if m is None or voice:
            self._voice_wait = False
            self._voice_note = ""
        if self.ctl.live and m is not None and voice and self.ctl.live_voice != voice:
            # talking already: switch to the new voice now, no restart needed
            self.ctl.live_voice = voice
            short = customvoices.label(voice)
            self.lbl_state.setText(_("✓ {language} voice found: {voice} speaks from the "
                                     "next line on.", language=langnames.of(m), voice=short))
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
            self._recheck_voices_asked()

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
                      translate=self.cb_lang.currentData() or "",
                      translate_on=self.sw_lang.isChecked())
        self.ctl.speaker.rate = self.s["rate"]
        self.ctl.set_mute_real_voice(self.s["mute_real_voice"])
        if self.ctl.live and not self.bg_for:
            self.ctl.set_replace(self.s["mute_real_voice"])
        self.ctl.voice_fx = self.s["voice_fx"]
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
        self.cb_lang.addItem(_("As you say it"), "")
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
        self.cb_lang.setCurrentIndex(max(0, self.cb_lang.findData(self.s["translate"])))
        self.cb_lang.blockSignals(False)
        self.lang_box.setVisible(self.module is not None and self.module.installed
                                 and bool(self.langs))
        self._refresh_translation()

    def _lang_picked(self, *_):
        # picking a language means speaking it; As you say it is off
        self.sw_lang.blockSignals(True)
        self.sw_lang.setChecked(bool(self.cb_lang.currentData()))
        self.sw_lang.blockSignals(False)
        self._lang_switched()

    def _lang_switched(self, *_):
        if self.sw_lang.isChecked() and not self.cb_lang.currentData():
            self.sw_lang.blockSignals(True)
            self.sw_lang.setChecked(False)    # no language yet: pick one first
            self.sw_lang.blockSignals(False)
            self.cb_lang.showPopup()
            return
        self._settings_edited()
        self._refresh_translation()
        self.lang_changed.emit()

    def _lang_on(self) -> mods.ModuleInfo | None:
        """The language picked under Speak in while its switch is on."""
        return self._lang() if self.sw_lang.isChecked() else None

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
        if focused is not None and focused in (
                self.b_dl, self.b_dl_cancel, self.b_voice_install, self.b_voices,
                self.b_voices_check, self.b_dl_remove) and focused.isVisible():
            focused.setFocus(Qt.FocusReason.OtherFocusReason)

    def _refresh_translation_state(self):
        """The box under "Speak in": download it, get its Windows voice, or all set."""
        busy.set_busy(self.b_voice_install, self._voice_installing is not None)
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
        downloading = self._dl_busy is not None
        self.tr_box.setVisible(m is not None or downloading)
        for b in (self.b_dl, self.b_dl_cancel, self.b_voice_install, self.b_voices,
                  self.b_voices_check, self.b_dl_remove):
            b.hide()
        self._watch_voices(False)
        if downloading:
            self.b_dl.show()
            self.b_dl_cancel.show()
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
            self.b_dl.setText(_("Download {language}", language=name))
            self.b_dl.setVisible(not net.offline())   # Offline mode: no dead button
            if net.offline():
                self.lbl_tr.setText(_("{language} needs a one-time download of its "
                                      "translation model ({size} MB). Offline mode is on, so "
                                      "it can't be downloaded now.", language=name,
                                      size=translation.size_mb(m)))
            # downloading voices switched off in Settings > Privacy: greyed, saying why
            self.b_dl.setEnabled(not live and net.allowed("voices"))
            self.b_dl.setToolTip(net.off_message("voices") if not net.allowed("voices") else
                                 _("Stop the voice to download this") if live else "")
            return
        self.b_dl_remove.setVisible(not live)
        if not self.ctl.tts.voices:        # still loading, or no speech at all
            self.lbl_tr.setText(_("Say it in your language; the voice says it in {language}.",
                                  language=name))
            return
        voice = self._voice_for(m)
        if voice:
            short = customvoices.label(voice)
            self.lbl_tr.setText(_("Say it in your language; {voice} says it in {language}. "
                                  "Translation is quick but not perfect with slang.",
                                  voice=short, language=name))
        else:
            self._watch_voices(True)
            for b in (self.b_voice_install, self.b_voices, self.b_voices_check):
                b.show()
            if self._voice_installing is not None:
                self.lbl_tr.setText(_("Installing the {language} voice\u2026 Say Yes to "
                                      "Windows' permission prompt, then it downloads (a minute "
                                      "or two). It's used by itself as soon as it's in.",
                                      language=name))
                self.b_voice_install.setText(_("Installing\u2026"))
                busy.set_busy(self.b_voice_install, True)
                self.b_voices.hide()
                return
            self.b_voice_install.setText(_("Install the {language} voice", language=name))
            self.b_voice_install.setVisible(not net.offline())   # Windows Update: online
            # Windows Update can't go through the app's connection: off means not at all
            self.b_voice_install.setEnabled(net.allowed("voices"))
            self.b_voice_install.setToolTip(
                self._voice_install_tip if net.allowed("voices") else net.off_message("voices"))
            self.lbl_tr.setText(self._voice_note or (_(
                "\u26a0 Windows has no {language} voice yet, so {language} can't be spoken "
                "properly. Offline mode is on, so it can't be installed now.", language=name)
                if net.offline() else _(
                "\u26a0 Windows has no {language} voice yet, so {language} can't be spoken "
                "properly. Press Install (free, one click); it's picked up by itself "
                "once it's in, even mid-sentence.", language=name)))

    # ---- Windows voices
    def _install_voice(self):
        m = self._lang()
        if m is None or self._voice_installing is not None:
            return
        self._voice_installing, self._voice_note = m, ""
        self._refresh_translation()

        def work():
            try:
                busy.emit(self._voice_done, winvoices.install(m.language), "")
            except winvoices.Cancelled:
                busy.emit(self._voice_done, "cancelled", "")
            except RuntimeError as e:
                busy.emit(self._voice_done, "", errors.plain(e))
            except Exception as e:  # noqa: BLE001 - the button must come back
                applog.report(where="windows voice install")
                busy.emit(self._voice_done, "", errors.plain(e))

        threading.Thread(target=work, name="voice-install", daemon=True).start()

    def _on_voice_installed(self, result: str, err: str):
        m, self._voice_installing = self._voice_installing, None
        m = m or self._lang()
        name = langnames.of(m) if m is not None else ""
        if err:
            self._voice_note = _("\u26a0 Couldn't install the {language} voice: {error}. "
                                 "Press Install to try again, or add it in Windows settings.",
                                 language=name, error=errors.plain(err))
        elif result == "cancelled":
            self._voice_note = _("Windows' permission prompt was closed, so the {language} "
                                 "voice wasn't installed. Press Install to try again.",
                                 language=name)
        elif result == "restart":
            self._voice_note = _("The {language} voice is installed, but Windows wants the "
                                 "PC restarted to finish. After that it's picked up by "
                                 "itself.", language=name)
        else:
            self._voice_note = _("The {language} voice is installed; loading it\u2026 If it "
                                 "doesn't appear in a minute, press Reload voices or restart "
                                 "the PC.", language=name)
        self._refresh_translation()
        if not err and result != "cancelled":
            self._recheck_voices()

    def _get_voice(self):
        self._voice_wait = busy.open_url(
            "ms-settings:speech", self.b_voices, opened=_("✓ Opened Windows settings"),
            failed=_("Couldn't open Windows settings. Go to Settings → Time & language → "
                     "Speech → Add voices yourself"))

    def _app_state(self, state):
        # back from Windows settings: a voice may have just been installed
        if state == Qt.ApplicationState.ApplicationActive and self._voice_wait:
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

    def _recheck_voices_asked(self):
        self._voices_asked = not self._loading()
        self._recheck_voices()

    def _recheck_voices(self):
        """Look for Windows voices again, off the UI thread. Safe while talking: a line
        being spoken waits a second for the engine to come back."""
        if self._loading():
            self._voices_again = True   # run once more when this load is done
            return
        self._loading_since = time.monotonic()
        busy.set_busy(self.b_voices_check, True)
        self.b_voices_check.setText(_("Reloading\u2026"))

        def work():
            self._voice_fp = winvoices.fingerprint()
            voices = self.ctl.tts.refresh()
            busy.emit(self._voices, voices, self.ctl.tts.error)
        threading.Thread(target=work, name="tts-refresh", daemon=True).start()

    def _download(self):
        m = self._lang()
        if m is None or self._dl_busy is not None:
            return
        self._dl_busy, self._dl_cancel = m, False
        busy.set_busy(self.b_dl, True)
        _enable(self.cb_lang, False, _("Waiting for the download to finish"))
        _enable(self.b_live, False, _("Waiting for the download to finish"))
        self._refresh_translation()
        self.lbl_tr.setText(_("Downloading {language}\u2026 {percent}%",
                              language=langnames.of(m), percent=0))
        netlog.cause("voices",
                     f"You downloaded the {m.language_name or m.language} translation model")

        def work():
            try:
                translation.download(m, lambda *a: busy.emit(self._dl_progress, *a),
                                     lambda: self._dl_cancel)
                busy.emit(self._dl_done, "")
            except translation.Cancelled:
                busy.emit(self._dl_done, "cancelled")
            except RuntimeError as e:
                busy.emit(self._dl_done, errors.plain(e))
            except Exception as e:  # noqa: BLE001 - the UI must never stay on "Downloading…"
                applog.report(where="translation download")
                busy.emit(self._dl_done, errors.plain(e))

        threading.Thread(target=work, name="translation-download", daemon=True).start()

    def _cancel_download(self):
        self._dl_cancel = True
        busy.set_busy(self.b_dl_cancel, True)
        if self._dl_busy is not None:
            self.lbl_tr.setText(_("Cancelling…"))

    def _on_dl_progress(self, done: int, total: int):
        m = self._dl_busy
        if m is not None and not self._dl_cancel:
            self.lbl_tr.setText(
                _("Downloading {language}\u2026 {percent}%", language=langnames.of(m),
                  percent=done * 100 // total) if total else
                _("Downloading {language}\u2026 {size} MB", language=langnames.of(m),
                  size=done // 1_000_000))

    def _on_dl_done(self, err: str):
        m, self._dl_busy = self._dl_busy, None
        busy.set_busy(self.b_dl, False)
        _enable(self.cb_lang, not self.ctl.live, _("Stop the computer voice to change this"))
        _enable(self.b_live, not self._installing, _("Waiting for the install to finish"))
        busy.set_busy(self.b_dl_cancel, False)
        self._fill_langs()
        if err == "cancelled" and m is not None:
            busy.toast(self, html.escape(_("Download cancelled.")))
        elif err and m is not None:
            busy.toast(self, html.escape(_(
                "⚠ {language}: {error}. Check your internet connection and press "
                "Download again.", language=langnames.of(m), error=errors.plain(err))
                .removeprefix("⚠ ")), "error")
        self.downloaded.emit()

    def _remove_download(self):
        m = self._lang()
        if m is None or self.ctl.live:
            return
        if QMessageBox.question(
                self, _("Delete download"),
                _("Delete the downloaded {language} translation? You can download it again "
                  "any time.", language=langnames.of(m))) != QMessageBox.StandardButton.Yes:
            return

        def go():
            translation.remove(m)
            self._fill_langs()
            self.downloaded.emit()
            return not translation.model_dir(m).exists()

        def said(gone: bool):
            if gone:
                busy.toast(self, _("✓ Deleted the {language} download",
                                   language=html.escape(langnames.of(m))), "ok")
            else:
                busy.toast(self, _("Couldn't delete all of it (a file is in use). Restart "
                                   "Onion Board and try again."), "warn")
        busy.run_busy(self.b_dl_remove, _("Deleting…"), go, said)

    def _net_changed(self):
        """Offline mode on or off: the install buttons follow (not mid-install)."""
        if not self._installing:
            self._refresh_module()

    def _refresh_module(self):
        m = self.module
        ok = m is not None and m.installed
        self.lang_box.setVisible(ok and bool(self.langs))
        self.start_box.setVisible(ok)
        self.missing.setVisible(not ok)
        self.b_install.setVisible(m is not None and not ok and not net.offline())
        self.b_update.setVisible(m is not None and not net.offline())   # pip: online
        if m is not None and not ok and net.offline():
            self.lbl_missing.setText(_("Speaking another language needs speech recognition "
                                       "installed first, which is a download. Offline mode "
                                       "is on, so it can't be installed now."))
        elif m is None:
            self.lbl_missing.setText(_(
                "The live-voice add-on is missing from this copy of Onion Board. Run the "
                "installer again (it comes with every install), then press Refresh below."))
        elif m.broken:   # the Python it was set up with is gone (soundboard.pyget)
            self.lbl_missing.setText(_("Speech recognition stopped working: the Python it "
                                       "was set up with is gone from this PC. Press Repair "
                                       "to set it up again."))
        elif not ok:
            self.lbl_missing.setText(_("Speaking another language needs speech recognition "
                                       "installed first (runs on this PC; what you say never "
                                       "leaves it)."))
        if not self._installing:
            fix = m is not None and m.broken
            self.b_install.setText(_("Repair") if fix else _("Install speech recognition"))
            icons.set_icon(self.b_install, "reload" if fix else "plus")

    def _install(self):
        m = self.module
        if m is None or self._installing:
            return          # one pip at a time: two into the same environment break it
        self._installing = True
        for b in (self.b_install, self.b_update, self.b_live):
            busy.set_busy(b, True)
        self.b_install.setText(_("Installing… (a few minutes)"))
        self.b_update.setText(_("Updating… (a few minutes)"))
        self.lbl_install.show()
        self.lbl_install.setText(_("starting…"))

        def work():
            try:
                ok = mods.install(m, lambda line: busy.emit(self._install_line, line))
                busy.emit(self._install_done, ok, "")
            except Exception as e:  # noqa: BLE001 - the buttons must come back
                if not isinstance(e, (mods.ModuleError, OSError)):   # a bug: report it
                    applog.report(where="module install")
                busy.emit(self._install_done, False, errors.plain(e))

        threading.Thread(target=work, name="module-install", daemon=True).start()

    def _on_install_done(self, ok: bool, err: str = ""):
        self._installing = False
        for b in (self.b_install, self.b_update, self.b_live):
            busy.set_busy(b, False)
        self.b_install.setEnabled(True)
        self.b_install.setText(_("Install speech recognition"))
        _enable(self.b_update, not self.ctl.live, _("Stop the computer voice to change this"))
        self.b_update.setText(_("Update speech recognition"))
        _enable(self.b_live, self._dl_busy is None, _("Waiting for the download to finish"))
        if ok:
            self.lbl_install.hide()
            self._refresh_module()
            self.lbl_state.setText(_("Installed. Press Start and talk."))
        else:
            last = self.lbl_install.text()
            self.lbl_install.hide()
            self._refresh_module()   # Repair stays Repair
            busy.toast(self, html.escape(_(
                "⚠ Install failed: {error}. Press it again to retry; if it keeps failing, "
                "run install.bat in the add-on's folder to see why.",
                error=err or last).removeprefix("⚠ ")), "error")

    def _live_args(self) -> list[str]:
        """The live-voice helper's arguments; sets the voice translated lines use."""
        # only our own models: any other name makes the helper download that repo
        model = self.s["model"] if self.s["model"] in {d for _n, d in MODELS} else MODELS[0][1]
        lang = spoken.spoken(self.s)
        # an English-only model can't hear another language: its "Any language" one
        args = ["--model", spoken.model_for(model, lang), "--language", lang]
        m = self._lang_on()
        self.ctl.live_voice = None
        if m is not None and m.installed:
            if not spoken.same(m.language, lang):   # said in it already: just spoken
                if lang != "en":   # the translations go from English: Whisper's first
                    args += ["--task", "translate"]
                args += ["--translate", str(translation.model_dir(m))]
            self.ctl.live_voice = self._voice_for(m) or None
        return args

    def _toggle_live(self, on: bool):
        if on and self.bg_for:           # Start takes over from translating for a voice
            self._stop_bg()
        if on and not self.ctl.live:
            m = self._lang_on()
            if m is not None and not m.installed:
                self._set_live_ui(False, _("Download {language} first (above).",
                                           language=langnames.of(m)))
                return
            module = self.module
            assert module is not None   # start_live needs it (it failed on None before too)
            try:
                self.ctl.start_live(module, self._live_args())
            except RuntimeError as e:
                self._set_live_ui(False, f"⚠ {errors.plain(e)}")
                return
            self._warm_for_a_line()   # its first line would otherwise wait for speech
            self._set_live_ui(True, _("starting…"))
        elif not on and self.ctl.live:
            self.ctl.stop_live()
            self._set_live_ui(False, IDLE_HINT)

    # ---- translating for the AI voice or the voice changer (VoicePanel decides)
    def translate_for(self, who: str):
        """Run speech recognition + translation in the background so the voice that's
        on ("ai" or "fx") speaks the language picked under Speak in; "" stops it.
        Text-to-speech's own Start, when on, already does this and wins."""
        if self.b_live.isChecked():
            who = ""
        m = self.translating() if who else None
        key = (who, m.language) if m is not None else ()
        if not key:
            self._bg_failed = ()      # switched off: the next switch-on tries again
        if key == self._bg_key and (not key or self.ctl.live):
            return
        if key and key == self._bg_failed:
            return        # it stopped with an error: not again on every slider step
        if key and self.bg_for and self.ctl.live and key[1] == self._bg_key[1]:
            # the other voice took over: same helper, only the real-mic mute changes
            self.bg_for, self._bg_key = who, key
            self.ctl.set_replace(who == "fx")
            return
        if self.bg_for:
            self._stop_bg()
        if not key:
            self._refresh_translation()
            return
        module = self.module
        assert module is not None   # start_live needs it (it failed on None before too)
        try:
            self.ctl.start_live(module, self._live_args(), replace=(who == "fx"))
        except RuntimeError as e:
            self._bg_note(_("⚠ Couldn't start translating: {error}", error=errors.plain(e)),
                          warning=True)
            return
        self.bg_for, self._bg_key = who, key
        self._bg_note(_("Starting the translation…"))
        self._refresh_translation()

    def _stop_bg(self):
        self.bg_for, self._bg_key, self._bg_failed = "", (), ()
        self.ctl.stop_live()
        self._bg_note("")
        self.bg_bar.hide()

    def _bg_note(self, text: str, warning: bool = False):
        self.lbl_bg.setText(text)
        self._bg_warning = warning and bool(text)
        self.lbl_bg.setVisible(bool(text))

    def _set_live_ui(self, on: bool, state: str):
        self.b_live.blockSignals(True)
        self.b_live.setChecked(on)
        self.b_live.blockSignals(False)
        self.b_live.setText(_("Stop the computer voice") if on else _("Start the computer voice"))
        self.live_changed.emit(on)
        for w in (self.cb_model, self.ed_lang, self.cb_lang, self.sw_lang):
            _enable(w, not on, _("Stop the computer voice to change this"))
        _enable(self.b_update, not on,
                _("Stop the computer voice to change this") if on
                else _("Waiting for the install to finish"))
        self.lbl_state.setText(state)
        if not on:
            self.dl_bar.hide()
        self._refresh_translation()

    def _download_note(self, ev: dict) -> str:
        """A "download" event: its bar filled, the words that go with it."""
        done, total = int(ev.get("done") or 0), int(ev.get("total") or 0)
        bar = self.bg_bar if self.bg_for else self.dl_bar
        bar.setValue(min(1000, done * 1000 // total) if total > 0 else 0)
        bar.show()
        return _("Downloading the speech model (one time only)… {done} of {total} MB",
                 done=done // 1_000_000, total=total // 1_000_000)

    def _on_event(self, ev: dict):
        t = ev.get("type")
        text = str(ev.get("text", ""))
        if t != "download":
            (self.bg_bar if self.bg_for else self.dl_bar).hide()
        if self.bg_for and t != "tts_error":
            self._on_bg_event(t, text, ev)
            return
        if t == "download":
            self.lbl_state.setText(self._download_note(ev))
        elif t == "tts_error":
            self._tts_error(_("Couldn't speak that line: {error}", error=text))
        elif t == "status":
            self.lbl_state.setText(text)
        elif t == "ready":
            self.lbl_state.setText(_("● listening"))
        elif t == "vad":
            self.lbl_state.setText(_("● hearing you…") if ev.get("speaking")
                                   else _("● listening"))
        elif t == "final" and text:
            orig = str(ev.get("original", ""))
            self._log_said(_("{text}   (you said: {original})", text=text, original=orig)
                           if orig else text)
        elif t == "error":
            self.lbl_state.setText(f"⚠ {text}")
        elif t == "stopped":
            self._set_live_ui(False, _("⚠ stopped: {error}", error=text) if text
                              else _("stopped"))

    def _on_bg_event(self, t, text: str, ev: dict):
        name = self._bg_key[1] if self._bg_key else ""
        m = self._lang()
        name = langnames.of(m) if m is not None else name
        if t == "download":
            self._bg_note(self._download_note(ev))
        elif t == "ready" or (t == "vad" and not ev.get("speaking")):
            self._bg_note(_("● Listening: say it in your language, it comes out in {language}.",
                            language=name))
        elif t == "vad":
            self._bg_note(_("● Hearing you…"))
        elif t == "status":
            self._bg_note(text)
        elif t == "final" and text:
            orig = str(ev.get("original", ""))
            self._log_said(_("{text}   (you said: {original})", text=text, original=orig)
                           if orig else text)
        elif t == "error":
            self._bg_note(f"⚠ {text}", warning=True)
        elif t == "stopped":
            self._bg_failed = self._bg_key
            self.bg_for, self._bg_key = "", ()
            self._bg_note(_("⚠ Translating stopped: {error}", error=text) if text
                          else _("Translating stopped."), warning=bool(text))
            self._refresh_translation()

    @staticmethod
    def _open_folder(module: mods.ModuleInfo | None = None, btn=None):
        """The module's own folder, or the user add-ons folder when it isn't there yet."""
        d = module.path if module is not None else library.APP_DIR / "modules"

        def make():
            d.mkdir(parents=True, exist_ok=True)
            return d
        busy.open_folder(make, btn)
