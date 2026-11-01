"""The Voice tab's Languages card: `SpeechPanel` (text-to-speech and live
voice-to-speech, with translation).

It looks and works as the voice changer's and AI voices' cards: the big ON/OFF switch
next to its name (`head`), chips (All, Favorites, Downloaded), cards or a list, and a
card per language. A language that isn't downloaded yet is grey; clicking it asks to
download it (and to add its Windows voice). Clicking a downloaded one turns it on (the
AI voice or the voice changer says it, else the computer voice starts); clicking the
lit one turns it off. The hidden `cb_lang` list keeps which language is on.

It follows panel.py's pattern: it owns its widgets and emits plain dicts
(`changed`) that the main window stores in the config. Two helpers it owns do the
rest: `livevoice` (Start, translating for another voice: livevoice.py) and
`installs` (Windows voices, translation downloads, speech recognition:
speechinstall.py). Its methods live in three mixins beside it: `speechsay` (text to
speech), `speechtiles` (the language cards) and `speechlangs` (translation).
"""
from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton, QSlider, QVBoxLayout,
                               QWidget)

from soundboard.addons import modules as mods
from soundboard.ui.kit import theme
from soundboard.online import net
from soundboard.speech import customvoices, spoken, tts, winvoices
from soundboard.speech.live import SpeechController, clean_settings
from soundboard.ui.kit import busy, icons
from soundboard.ui.kit.panel import (ViewToggle, bar, fold_button, hint_label, icon_label,
                                     section_label)
from soundboard.ui.kit.restyled import measured, on_restyle
from soundboard.ui.voice.livevoice import MODELS, LiveVoice
from soundboard.ui.voice.speechinstall import SpeechInstalls
from soundboard.ui.voice.groupbar import GroupBar
from soundboard.ui.voice.voicefxpanel import TILE_GAP, BigSwitch, VoiceTile
from soundboard.ui.voice.voiceservers import ServerList
from soundboard.ui.kit.widgets import fit_placeholder
from soundboard.ui.kit.wheelguard import no_wheel
from soundboard.i18n import _
# the card's parts (callers import their names from here too)
from soundboard.ui.voice.speechsay import SpeechSay
from soundboard.ui.voice.speechtiles import ALL, FAVS, READY, SpeechTiles, lang_icon  # noqa: F401
from soundboard.ui.voice.speechlangs import LIVE_MODULE, SpeechLangs, translations  # noqa: F401


log = logging.getLogger(__name__)


def default_speech_settings() -> dict:
    return {"voice": "", "rate": 0, "gain": 1.0, "model": "base.en", "language": "en",
            "mute_real_voice": True, "voice_fx": True, "translate": "",
            "translate_on": False}


class SpeechPanel(SpeechSay, SpeechTiles, SpeechLangs, QWidget):
    """Text-to-speech box and live voice-to-speech. `changed(settings)` for the config."""
    changed = Signal(dict)
    _voices = Signal(list, str)
    _voices_quiet = Signal(list, str)   # the launch's own listing: its error isn't shown
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
        self._ready: dict[int, bool] = {}   # see _is_ready
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
        self._voices_quiet.connect(lambda v, e: self._fill_voices(v, e, quiet=True))
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
        # ---- the big ON/OFF, as the voice changer's and AI voices': the Voice tab puts
        # `head` right after the card's name. Clicking a language turns it on too
        self.b_on = BigSwitch(_("Languages"))
        self.b_on.setText(_("Off"))
        self.b_on.clicked.connect(self._switch_clicked)
        self.head = QWidget()
        hh = QHBoxLayout(self.head)
        hh.setContentsMargins(0, 0, 0, 0)
        hh.addWidget(self.b_on)
        self.lbl_intro = hint_label(_("Talk in your language and others hear another one. "
                                      "Pick a language to turn it on."))
        v.addWidget(self.lbl_intro)
        v.addWidget(live.start_box)   # how the computer voice is doing (listening, a problem)
        live._fit_start_box()   # placed now: hidden while it has nothing to say

        # ---- the language cards: chips over them, cards or a list at the right
        favs = self.s.get("lang_favorites")
        self._favs: list[str] = ([c for c in favs if isinstance(c, str)]
                                 if isinstance(favs, list) else [])
        self._group = ALL
        self._wanted = ""        # a grey card's language, downloading: on once it's in
        self.cards = QWidget()
        cv = QVBoxLayout(self.cards)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(12)
        self._listed = False
        self.view_toggle = ViewToggle("grid", _("Languages"))
        self.view_toggle.changed.connect(self.set_view)
        self.bar = GroupBar(
            [(ALL, _("All"), "sounds"), (FAVS, _("Favorites"), "star_filled"),
             (READY, _("Downloaded"), "download")],
            self.view_toggle, self._group_count,
            (_("Search languages"), _("Search")), _("Which languages show"))
        self.bar.picked.connect(self.show_group)
        self.bar.searched.connect(lambda _t: self._place_tiles())
        cv.addWidget(self.bar)
        self._heads = {}
        for key, text in ((READY, _("Downloaded")), ("get", _("Not downloaded yet"))):
            lbl = QLabel(text)
            lbl.setObjectName("fxgroup")
            lbl.hide()
            self._heads[key] = lbl
        self._tile_grid = QGridLayout()
        self._tile_grid.setSpacing(TILE_GAP)
        self._tile_cols = 3
        self._tile: dict[str, VoiceTile] = {}
        cv.addLayout(self._tile_grid)
        self.no_favs = hint_label(_("No favorites yet. Click the star on a language to keep "
                                    "it here."))
        self.no_favs.hide()
        cv.addWidget(self.no_favs)
        self.no_ready = hint_label(_("None downloaded yet. Click a grey language to get it."))
        self.no_ready.hide()
        cv.addWidget(self.no_ready)
        self.no_match = hint_label("")
        self.no_match.hide()
        cv.addWidget(self.no_match)
        v.addWidget(self.cards)
        self._lang_ready = False   # speech recognition is in and there are languages
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
        self.lbl_lang.hide()   # the cards pick the language now; the list keeps it
        trow.addWidget(self.lbl_lang)
        self.cb_lang = QComboBox()
        self.cb_lang.setAccessibleName(_("Speak in"))
        self.cb_lang.setToolTip(_("Say it in your language; whichever voice is on says it in this "
                                  "language. Each language is a one-time download."))
        on_restyle(self.cb_lang.view(), self._fit_lang_list)   # (see restyled)
        self.cb_lang.setMinimumWidth(120)   # a list, not a bar across the card: it
        self.cb_lang.setMaximumWidth(380)   # opens as wide as its names need
        self.cb_lang.hide()
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

        def heads():   # the two row heads as wide as each other (in the theme's font)
            for lbl in (self.lbl_said_by, self.lbl_lang):
                lbl.setMinimumWidth(0)   # (a label's size hint grows to its minimum)
            w = max(self.lbl_said_by.sizeHint().width(), self.lbl_lang.sizeHint().width())
            self.lbl_said_by.setMinimumWidth(w)
            self.lbl_lang.setMinimumWidth(w)

        measured(self.lbl_said_by, heads)
        self._said_row.addLayout(srow)
        self._who = ""   # "ai:name" / "fx:name" / "": who's on elsewhere (said_by)
        # the language voices read through the AI voices add-on: "get" (it isn't in),
        # "update" (one from before they came), "" (ready). VoicePanel sets it.
        self.voices_need = ""
        # the language and who says it, together in one inner area; Start under it
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
        # each language speaks with its own voice now: no list of Windows voices on the
        # card. The list stays as the hidden pick that custom voice switches set
        for w in (lbl_voice, self.cb_voice, self.b_add_voices):
            w.hide()
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
        # (the computer voice's own Start is gone: a language speaks with its own voice
        # as soon as it's picked; kept, never shown, for the code that asks if it's on)
        ov.addWidget(live.b_live, 0, Qt.AlignmentFlag.AlignLeft)
        live.b_live.hide()
        grid = voice_grid
        lbl_model = QLabel(_("Recognition"))
        grid.addWidget(lbl_model, 2, 0)
        self.cb_model = QComboBox()
        for label, key in MODELS:
            self.cb_model.addItem(label, key)
        self.cb_model.setCurrentIndex(max(0, self.cb_model.findData(self.s["model"])))
        grid.addWidget(self.cb_model, 2, 1)
        lbl_spoken = QLabel(_("Language"))
        grid.addWidget(lbl_spoken, 3, 0)
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
        # what only works with speech recognition in: hidden until it's installed (a
        # Start button above "Install speech recognition" made no sense)
        self._needs_recognition = (lbl_model, self.cb_model, lbl_spoken, self.ed_lang)
        self.chk_mute.hide()   # (only the computer voice's Start used it)
        self.chk_fx = QCheckBox(_("Put the voice changer on the computer voice"))
        self.chk_fx.setToolTip(_("With a voice picked under Voice changer, the computer voice "
                                 "gets the same effect (a chipmunk robot voice, say)."))
        self.chk_fx.setChecked(self.s["voice_fx"])
        ov.addWidget(self.chk_fx)
        urow = QHBoxLayout()
        urow.setSpacing(8)
        urow.addWidget(inst.b_update)
        urow.addWidget(inst.b_remove)
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
                                  "voices folder.")))
        self.servers = ServerList()     # each server: online or not, on / off, settings
        self.servers.switched.connect(self._server_switched)
        self.servers.saved.connect(self.installs._recheck_voices_asked)
        self.servers.remove_asked.connect(self._remove_server)
        ov.addWidget(self.servers)
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
        fit_placeholder(self.ed, _("Type a line and press Enter"), _("Type here"))
        self.ed.returnPressed.connect(self._say)
        self.ed.textEdited.connect(self._warm_for_a_line)
        row.addWidget(self.ed, 1)
        b_say = self.b_say = QPushButton(_("Say"))
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
        b_keep.setAccessibleName(_("Save as sound"))
        self.say_bar.installEventFilter(self)   # narrow: Save as sound goes down to its +

        self.cb_voice.currentIndexChanged.connect(self._voice_picked)
        for sig in (self.sl_rate.valueChanged,
                    self.cb_model.currentIndexChanged,
                    self.chk_mute.toggled, self.chk_fx.toggled):
            sig.connect(self._settings_edited)
        self.ed_lang.editingFinished.connect(self._settings_edited)
        self._fill_langs()
        self.cb_lang.currentIndexChanged.connect(self._lang_picked)
        self.downloaded.connect(self._after_download)
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
            # nobody asked for speech yet (they may be on the Sounds tab): a slow or
            # stuck Windows speech is only logged; a line said later reports its own
            busy.emit(self._voices_quiet, voices, controller.tts.error)
        threading.Thread(target=warm_up, name="tts-warmup", daemon=True).start()

    def eventFilter(self, obj, e):   # noqa: N802 - Qt
        try:
            if obj is self.say_bar and e.type() in (QEvent.Type.Resize, QEvent.Type.Show,
                                                    QEvent.Type.LayoutRequest):
                self._fit_say_bar()
        except Exception:  # noqa: BLE001 - never raise from a Qt override (AGENT-RULES)
            log.exception("speech: say bar resize")
        return super().eventFilter(obj, e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if e.size().width() != e.oldSize().width():
            self._fit_width(self.width())

