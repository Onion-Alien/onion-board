"""The main window: pads, transport, web search, the audio panel, auto push-to-talk."""
from __future__ import annotations

import copy
import html
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
import sounddevice as sd
from PySide6.QtCore import (QEvent, QFileSystemWatcher, QObject, QPropertyAnimation, QSize, Qt,
                            QTimer, QUrl, Signal)
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
                               QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton,
                               QScrollArea, QSizePolicy, QSlider, QStackedWidget,
                               QSystemTrayIcon, QTabBar, QTabWidget, QVBoxLayout, QWidget)

from soundboard import engine as eng
from soundboard import theme, winkeys, ytdl
from soundboard.engine import SR, Engine
from soundboard.engine import is_virtual as is_virtual_cable
from soundboard import (appaudio, autostart, backup, destination, library, midi, remote,
                        soundfx, thumbs, trash, updates, voicesdk)
from soundboard import net, netlog, quality, shellicon, tor, watchaddon
from soundboard.replay import InstantReplay
from soundboard.library import (AUDIO_EXTS, PAD_COLORS, RESOURCE_DIR, Config, SoundMeta,
                                cache_keep, clean_tags, duplicate, fingerprint,
                                import_file, load_original, load_sound, loose_sounds,
                                prune_cache, save_clip)
from soundboard.settings import HOTKEY_ACTIONS, HotkeyDialog, SettingsDialog, pretty_key
from soundboard.shuffle import ShuffleBag
from soundboard.testcheck import analyze as analyze_output
from soundboard.testcheck import summary_html
from soundboard.ui.crashdialog import free_dialog
from soundboard.ui.dialogs import EditDialog
from soundboard.ui import a11y, appstate, busy, icons, responsive, splash
from soundboard.ui.speedpitch import SpeedPitchButton
from soundboard.ui.panel import (EqPanel, VolumeControl, bar, card, hint_label, icon_label,
                                 vsep)
from soundboard.ui.linkbar import PLAY_ID as LINK_ID
from soundboard.ui.linkbar import LinkBar
from soundboard.ui.livedot import is_tab_live, set_tab_live
from soundboard.ui.logowidget import LogoWidget, glow_icon
from soundboard.ui.ytsearch import SearchResults
from soundboard.ui.padbatch import PadSelection
from soundboard.ui.overlay import Overlay
from soundboard.ui.appspanel import AppsTab, ElidedLabel
from soundboard.ui.triggershost import BoardHost
from soundboard.ui.triggerstab import TriggersTab
from soundboard.ui.radiopanel import RadioOff, RadioTab
from soundboard.ui.voicepanel import VoicePanel
from soundboard.ui.widgets import (Meter, Pad, PadGrid, SeekSlider, expand_dropped, fmt_pos,
                                   pad_height, spectrum, SLIM_PAD_H)
from soundboard.wheelguard import no_wheel
from soundboard.winkeys import Hotkeys

from soundboard import errors
log = logging.getLogger(__name__)


def version_text() -> str:
    """The version, as the title bar and header show it: "1.5.5", or "1.5.5 from
    source" when run with Python rather than the installed app."""
    from soundboard import __version__
    return __version__ if getattr(sys, "frozen", False) else f"{__version__} from source"


# The tabs, in order: each one is a thing you can play (or, last, the setup). The
# tooltip says what it's for in a few words.
TABS = (("Sounds", "Your sound buttons: click one to play it"),
        ("Radio", "Internet radio stations from around the world"),
        ("Apps", "Send another program's sound (music player, game…)"),
        ("Triggers", "Play a sound when something shows up on your screen (“YOU DIED”…)"),
        ("Voice", "Change your voice, or talk as a computer voice"),
        ("Setup", "Connect to Discord / games, pick devices, test it"))


UNDO_S = 10          # how long "Removed … · Undo" stays up
TICK_MS = 33         # the UI timer while the window is on screen (meters, visualisers)
TICK_BG_MS = 100     # ...while it's on screen but another program is in front (a game)
TICK_IDLE_MS = 250   # ...and while it's in the tray or minimised (push-to-talk, watchdog)
GLOW_STEPS = 4       # how many glow levels the taskbar / tray icon has while sound plays
ICON_GLOW_MS = 120   # ...and how often at most it changes
DEFAULT_POLL_MS = 1500   # how often Windows' default output is checked
LOOSE_WAIT_MS = 1500   # a file dragged into the sounds folder is looked at again (ms)
MINI_SIZE = QSize(440, 380)   # below this the window becomes the mini player...
MINI_PAD_ROWS = 1             # ...which has the pads above it when this many rows fit
QUEUE_CHIPS = 5          # queued sounds shown by name above the pads (then "+n more")
RANDOM = "__random__:"   # hotkey action prefix: a random sound from the category after it
ALL = "All"          # the category tab that shows every sound
VOICE_POLL_MS = 3000  # how often the game in front is looked at (soundboard.voicesdk)


class Bridge(QObject):
    loaded = Signal(str, object, str)          # id, data|None, error
    exported = Signal(str, int, str)           # file, sounds written, error
    unpacked = Signal(object, object, str)     # backup.Imported|None, backup.Package, error
    update = Signal(object, str, bool)         # updates.Release|None, error, asked by the user
    update_progress = Signal(int)              # percent of the new version downloaded
    update_ready = Signal(object, str)         # its installer's Path|None, error
    watch_update = Signal(object)              # a newer Onion Watch: watchaddon.Offer
    imported = Signal(object, object, str)     # meta|None, data|None, error/filename
    preview = Signal(str, object, float)       # id, audio with unsaved effects|None, gain


class MainWindow(QMainWindow):
    update_done = Signal(object, str)   # an update check finished: Release|None, error
    voice_engine = Signal(object)       # the voice engine of the game in front (a mode key|None)

    def __init__(self):
        super().__init__()
        self.title = f"Onion Board {version_text()}"
        self.setWindowTitle(self.title)
        self.setAcceptDrops(True)   # files dropped outside the pad grid: see dropEvent
        self.cfg = Config.load()
        if self.cfg.netlog_keep:   # the kept network history: listed, and saved from now
            netlog.keep(library.APP_DIR / netlog.FILE_NAME)
        net.configure_from(self.cfg)   # before anything goes online
        quality.load(self.cfg.data)    # ...and how much it fetches when it does
        tor.configure_from(self.cfg)   # Connection = Tor: starts when something goes online
        self._tor_told = ""             # what the last Tor toast said (one per change)
        tor.qt_status().changed.connect(self._on_tor)
        app = QApplication.instance()
        if app is not None:   # before the UI is built, so everything polishes in-theme
            self.cfg.theme = theme.apply(app, self.cfg.theme)
            app.commitDataRequest.connect(self._on_session_end)   # log-off / installer
        self.engine = Engine()
        self.audio: dict[str, np.ndarray] = {}
        self.pads: dict[str, Pad] = {}
        self._meta: dict[str, SoundMeta] = {}   # id -> meta, rebuilt when the list changes
        self._index()
        self.hotkeys = Hotkeys()
        self.hotkeys.fired.connect(self.on_hotkey)
        self.hotkeys.released.connect(self.on_hotkey_released)
        self.hotkeys.failed_changed.connect(self.on_hotkeys_failed)
        self.hotkeys.midi.busy_changed.connect(self.on_midi_busy)
        self.replay = InstantReplay(self.cfg.replay_seconds)
        self.replay.state_changed.connect(self.on_replay_state)
        self.overlay = Overlay(self, self.cfg.overlay)
        self._save_failed_shown = False
        self.bridge = Bridge()
        self.bridge.loaded.connect(self.on_loaded)
        self.bridge.imported.connect(self.on_imported)
        self.bridge.preview.connect(self._on_fx_preview)
        self.bridge.exported.connect(self._on_exported)
        self.bridge.unpacked.connect(self._on_unpacked)
        self.bridge.update.connect(self._on_update)
        self.bridge.update_progress.connect(self._on_update_progress)
        self.bridge.update_ready.connect(self._on_update_ready)
        self.bridge.watch_update.connect(lambda offer: self.triggers.offer_update(offer))
        self._removed: list[tuple[SoundMeta, int, np.ndarray | None]] = []   # undo-able
        self._render_gen: dict[str, int] = {}   # sid -> newest effects render (_rerender)
        self.shuffle = ShuffleBag()       # the random-sound hotkeys
        self._last_sid: str | None = None   # the last sound played (its replay hotkey)
        self._queue: list[str] = []       # sounds waiting for the ones playing to finish
        self._cool: dict[str, float] = {}   # sid -> time.monotonic() its cooldown ends
        self._waiting: dict[str, list[QTimer]] = {}   # sid -> its delayed starts
        self._hotkeys_off = False         # "All hotkeys off": only that key still works
        self._voice_was: bool | None = None   # voice changer state before a held key
        Pad.single_click = self.cfg.single_click
        self._undo_timer = QTimer(self)
        self._undo_timer.setSingleShot(True)
        self._undo_timer.timeout.connect(self._finish_removals)
        self._quitting = False            # a real quit (not "close to the tray")
        self._tray_told = False           # the "still running in the tray" note was shown
        self.tray: QSystemTrayIcon | None = None
        self.release: updates.Release | None = None   # a newer version, once found
        self._update_file: Path | None = None   # its downloaded, checked installer
        self._downloading = False
        self._preview_gen = 0             # newest effects preview (older renders are dropped)
        self._ptt_held: str | None = None   # PTT key we're currently holding
        self._pending_imports = 0
        self._imported_ok = 0
        self._exporting = False
        self._import_errors: list[str] = []
        self._rec_playing = False
        self.current: str | None = None   # sound shown in the transport bar
        self._link_meta: SoundMeta | None = None   # the link bar's Play once
        self.start_frac = 0.0             # where ▶ starts if it isn't playing
        self._seeking = False
        self._tick_n = 0                  # ticks since start (the watchdog runs ~once a second)
        self._ui_live = True              # the window is on screen (see _set_tick_rate)
        self._icon_step, self._icon_next = -1, 0.0   # the icons' glow step (_glow_icons)
        self._xruns_shown = 0             # drop-out count last written to the status line
        self._talk_until = 0.0            # "hearing you" indicator holds until this time
        self._talk_shown: bool | None = None
        self.virtual_mic: str | None = None
        self._cap: list[np.ndarray] = []  # Record-6s test: capture of the cable's far end
        self._cap_stream = None
        self._cap_rate: int | None = None
        self._cap_name: str | None = None
        self._rec_started = 0.0
        self._load_thread: threading.Thread | None = None
        self.engine.latency = self.cfg.latency if self.cfg.latency in ("low", "high") else "low"
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_now)

        self.setup_state = ""
        self._pill_short = False          # the header pill's short text (narrow window)
        self.cable_bad = []               # cable ends not at 48 kHz (_check_cable_format)
        self._default_out = appaudio.default_output_name()   # see _follow_default_output
        self._build_ui()
        splash.pump()
        self._init_devices()
        splash.pump()
        if self.setup_state != "ok":
            self.tabs.blockSignals(True)
            self.tabs.setCurrentWidget(self.setup_page)
            self.tabs.blockSignals(False)
        self._rebuild_pads()
        splash.pump()
        self._load_all()
        splash.pump()
        self._watch_sounds_folder()
        self._fit_overlay_key()
        self.register_hotkeys()
        # Stream Deck / scripts (Settings → Remote), only if turned on
        self.remote = remote.RemoteControl(lambda a, p: remote.dispatch(self, a, p), self)
        self.apply_remote()
        a11y.label_tree(self, force=True)   # names for the icon-only buttons

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(TICK_MS)
        QApplication.instance().applicationStateChanged.connect(self._set_tick_rate)
        # which voice chat the game you're playing uses: a hint by Who's listening
        self.voice_suggestion: str | None = None
        self.voice_watch = voicesdk.Watcher() if sys.platform == "win32" else None
        self._voice_timer = QTimer(self)
        self._voice_timer.timeout.connect(self._poll_voice)
        if self.voice_watch is not None:
            self._voice_timer.start(VOICE_POLL_MS)
        # the headphones follow Windows' default output when it changes
        self._default_timer = QTimer(self)
        self._default_timer.timeout.connect(self._follow_default_output)
        if sys.platform == "win32":
            self._default_timer.start(DEFAULT_POLL_MS)
        self._init_fit()
        self.resize(1180, 720)
        if self.cfg.always_on_top:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self._init_tray()
        if autostart.available():
            autostart.refresh(self.cfg.autostart_hidden)   # the app may have moved
        self._shut_down = False   # shutdown() ran (app.py also calls it on aboutToQuit)
        self._pending_note: str | None = None
        if self.cfg.load_note:   # settings came from a backup or the defaults: say so
            QTimer.singleShot(1200, self._show_load_note)

    def _show_load_note(self):
        """Started hidden in the tray (--tray at sign-in)? Then the box waits for the
        window to be opened, instead of popping up over whatever the user is doing."""
        if self.isVisible():
            QMessageBox.warning(self, "Settings were restored", self.cfg.load_note)
        else:
            self._pending_note = self.cfg.load_note

    # ------------------------------------------------------------------ UI build
    # Layout: header (setup pill, Stop all, Settings) / tabs / mixer strip / status.
    # Every tab is built the same way: a toolbar row on top, its content, and a
    # bottom bar ending in "Volume [slider %] | Hear it myself" for that source.
    def _build_ui(self):
        # page 0 the whole window, page 1 the mini player it turns into when it's
        # made too small to use (see _refit)
        self._pages = QStackedWidget()
        self.setCentralWidget(self._pages)
        root = self._full = QWidget()
        self._pages.addWidget(root)
        rv = QVBoxLayout(root)
        rv.setContentsMargins(14, 10, 14, 10)
        rv.setSpacing(8)

        # ---- header: logo + name, then setup status, Stop all, Settings
        head = QHBoxLayout()
        head.setSpacing(10)
        self.logo = LogoWidget()
        head.addWidget(self.logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        self.wordmark = QLabel("ONION BOARD")
        self.wordmark.setObjectName("wordmark")
        self.tagline = QLabel(f"an app by Onion Alien · v{version_text()}")
        self.tagline.setObjectName("tagline")
        names.addWidget(self.wordmark)
        names.addWidget(self.tagline)
        head.addLayout(names)
        head.addStretch(1)
        self.pill = QPushButton()
        self.pill.setObjectName("pill")
        self.pill.setCursor(Qt.PointingHandCursor)
        self.pill.setToolTip("Where your sounds go — click for setup and testing")
        self.pill.clicked.connect(lambda: self.tabs.setCurrentWidget(self.setup_page))
        head.addWidget(self.pill)
        self.btn_update = QPushButton()
        self.btn_update.setObjectName("pill")
        self.btn_update.setProperty("state", "ok")
        self.btn_update.setCursor(Qt.PointingHandCursor)
        self.btn_update.clicked.connect(self.show_update)
        icons.set_icon(self.btn_update, "next")
        self.btn_update.hide()
        head.addWidget(self.btn_update)
        # the two switches for everything at once, whatever tab you're on
        self.btn_air = QPushButton()
        self.btn_air.setObjectName("onair")
        self.btn_air.setCheckable(True)
        self.btn_air.setChecked(True)
        self.btn_air.toggled.connect(self.set_sending)
        icons.set_icon(self.btn_air, "live", "danger_text", "#ffffff")
        head.addWidget(self.btn_air)
        self._air_size = 0   # 0 full text, 1 one word, 2 icon only (small windows)
        self.set_sending(True)
        self.stop_btn = QPushButton("Stop all")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setToolTip("Stops every sound, the radio and every program")
        self.stop_btn.clicked.connect(lambda: (self.stop_all(),
                                               busy.flash(self.stop_btn, "✓ Stopped", 1200)))
        icons.set_icon(self.stop_btn, "stop", "danger_text", size=14)
        head.addWidget(self.stop_btn)
        self.gear = QPushButton("Settings")
        self.gear.setObjectName("settings")
        self.gear.setToolTip("Themes, hotkeys and more")
        self.gear.clicked.connect(lambda: self.open_settings())
        icons.set_icon(self.gear, "settings")
        head.addWidget(self.gear)
        rv.addLayout(head)
        self._paint_logo()

        self.mic_banner = QPushButton("YOU'RE HEARING YOUR MIC OUTPUT  —  mic + sounds, "
                                      "exactly what others hear   ·   click to turn off")
        self.mic_banner.setObjectName("micbanner")
        self.mic_banner.setCursor(Qt.PointingHandCursor)
        self.mic_banner.clicked.connect(lambda: self.btn_check.setChecked(False))
        self.mic_banner.hide()
        icons.set_icon(self.mic_banner, "ear", "#ffffff", size=20)
        # pulse: an opacity animation, not a stylesheet rewrite 30x a second (each
        # setStyleSheet re-parses and re-polishes the widget)
        self._banner_fx = QGraphicsOpacityEffect(self.mic_banner)
        self.mic_banner.setGraphicsEffect(self._banner_fx)
        self._pulse = QPropertyAnimation(self._banner_fx, b"opacity", self)
        self._pulse.setDuration(1200)
        self._pulse.setStartValue(1.0)
        self._pulse.setKeyValueAt(0.5, 0.55)
        self._pulse.setEndValue(1.0)
        self._pulse.setLoopCount(-1)
        rv.addWidget(self.mic_banner)

        # ---- tabs
        self.tab_info: dict[str, tuple[str, str]] = {}   # page attr -> (title, text) for ⓘ
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setIconSize(QSize(18, 18))
        self.tabs.tabBar().setUsesScrollButtons(False)   # small windows drop the tab text
        rv.addWidget(self.tabs, 1)
        self.sounds_page = self._build_sounds_page()
        self.tabs.addTab(self.sounds_page, "")
        # the Radio tab, or the panel saying it's switched off (Settings > Privacy)
        self.radio_page = QStackedWidget()
        self.radio = self._make_radio()
        self.tabs.addTab(self.radio_page, "")
        self.apps = AppsTab(self.engine, self.cfg, self._save_later, Meter)
        self.apps.clip_ready.connect(self.on_clip)
        self.tabs.addTab(self.apps, "")
        # the Onion Watch add-on, or Hoot and its download button until it's installed
        self.triggers = TriggersTab(BoardHost(self))
        self.tabs.addTab(self.triggers, "")
        self.voice = VoicePanel(self.engine, self.cfg.voice_fx, self.cfg.speech)
        self.voice.fx_changed.connect(lambda spec: self.set_option("voice_fx", spec))
        self.voice.speech_changed.connect(lambda s: self.set_option("speech", s))
        self.tabs.addTab(self.voice, "")
        self.setup_page = self._build_setup_page()
        self.tabs.addTab(self.setup_page, "")
        for i, (text, tip) in enumerate(TABS):
            self.tabs.setTabText(i, text)
            self.tabs.setTabToolTip(i, tip)
            icons.set_tab_icon(self.tabs, i, text.lower())
        self.tab_info["apps"] = self.apps.info
        # one ⓘ at the end of the tab bar: the tab's explanation, instead of a banner
        self.btn_info = QPushButton("ⓘ")
        self.btn_info.setObjectName("small")
        self.btn_info.setCursor(Qt.PointingHandCursor)
        self.btn_info.setToolTip("What's this tab for?")
        self.btn_info.clicked.connect(self._show_tab_info)
        self.tabs.setCornerWidget(self.btn_info, Qt.TopRightCorner)
        self._update_info_btn = lambda *_: self.btn_info.setVisible(
            self._current_tab_info() is not None)
        self.tabs.currentChanged.connect(self._update_info_btn)
        self.triggers.loaded.connect(self._update_info_btn)   # Onion Watch can arrive late
        self._update_info_btn()
        self.tabs.setCurrentIndex(self.cfg.tab if 0 <= self.cfg.tab < self.tabs.count() else 0)
        self.tabs.currentChanged.connect(lambda i: self.set_option("tab", i))
        self.tabs.currentChanged.connect(lambda _i: self._update_status())
        # a glowing dot (and a green name) on a tab while its feature is live — the
        # voice changer, a radio station, a program being sent, the screen watched —
        # so it's never left on without you noticing
        vi = self.tabs.indexOf(self.voice)
        self.voice.active_changed.connect(lambda on: set_tab_live(
            self.tabs, vi, on, "● ON: others hear your changed / computer voice",
            self.voice.tab_icon()))   # the active voice's picture, when there is one
        set_tab_live(self.tabs, vi, self.voice.is_active(), icon=self.voice.tab_icon())
        ti = self.tabs.indexOf(self.triggers)
        self.triggers.active_changed.connect(lambda on: set_tab_live(
            self.tabs, ti, on, "● ON: watching your screen", "triggers"))
        set_tab_live(self.tabs, ti, self.triggers.is_active(), icon="triggers")
        if self.triggers.needs_nudge():
            self._nudge_triggers(ti)
        self._radio_live(self.radio.is_active())
        self._search_follow_switch()
        net.on_change(self._follow_switches)
        ai = self.tabs.indexOf(self.apps)
        self.apps.active_changed.connect(lambda on: set_tab_live(
            self.tabs, ai, on, self.apps.live_tip(), "apps"))
        set_tab_live(self.tabs, ai, self.apps.is_active(), icon="apps")

        # ---- mixer strip: the things that apply whatever tab you're on
        rv.addWidget(self._build_mixer())
        # the Voice tab's "Hear my voice" and the mixer's "Hear what they hear" are one switch
        self.voice.fx.hear_toggled.connect(self.btn_check.setChecked)
        self.btn_check.toggled.connect(self.voice.fx.set_hearing)
        # ... and so is the Setup tab's, in TEST IT
        self.btn_check.toggled.connect(self.btn_check_test.setChecked)
        self.btn_check_test.toggled.connect(self.btn_check.setChecked)
        self.voice.fx.set_tip_enabled(not self.cfg.voice_discord_tip_shown)
        self.voice.fx.chat_help.connect(lambda: self.show_chat_guide("discord"))
        self.voice.fx.tip_dismissed.connect(
            lambda: self.set_option("voice_discord_tip_shown", True))

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName("muted")
        rv.addWidget(self.status)
        self._pages.addWidget(self._build_mini())

    def _build_mini(self) -> QWidget:
        """The mini player: what's playing, play / stop, where it's at, Live and Stop
        all, and the pads above them if there's room. The pads are the real ones,
        moved in and out of the Sounds tab (_set_mini)."""
        page = QWidget()
        v = self._mini_v = QVBoxLayout(page)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)
        v.addStretch(0)   # keeps the player at the bottom when the pads don't fit
        card = self._mini_card = QFrame()
        card.setObjectName("transport")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(8, 6, 8, 6)
        cv.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.mini_pp = QPushButton()
        self.mini_pp.setObjectName("round")
        self.mini_pp.setToolTip("Play / pause")
        self.mini_pp.clicked.connect(self.toggle_play_pause)
        self.mini_st = QPushButton()
        self.mini_st.setObjectName("round")
        self.mini_st.setToolTip("Stop")
        self.mini_st.clicked.connect(self.stop_current)
        icons.set_icon(self.mini_st, "stop", size=16)
        for b in (self.mini_pp, self.mini_st):
            b.setFixedSize(34, 30)
            top.addWidget(b)
        self.mini_name = ElidedLabel(self.np_name.text())
        self.mini_name.setTextFormat(Qt.PlainText)   # sound names are user / web text
        self.mini_name.setStyleSheet("font-weight:600;")
        self.mini_name.setMinimumWidth(30)
        self.mini_name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        top.addWidget(self.mini_name, 1)
        self.mini_air = QPushButton()
        self.mini_air.setObjectName("onair")
        self.mini_air.setCheckable(True)
        self.mini_air.setChecked(self.btn_air.isChecked())
        self.mini_air.setToolTip(self.btn_air.toolTip())
        self.mini_air.toggled.connect(self.set_sending)
        icons.set_icon(self.mini_air, "live", "danger_text", "#ffffff")
        self.mini_stop = QPushButton()
        self.mini_stop.setObjectName("danger")
        self.mini_stop.setToolTip(self.stop_btn.toolTip())
        self.mini_stop.clicked.connect(self.stop_all)
        icons.set_icon(self.mini_stop, "stop", "danger_text", size=14)
        for b in (self.mini_air, self.mini_stop):
            b.setFixedSize(38, 30)
            top.addWidget(b)
        cv.addLayout(top)
        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        self.mini_seek = SeekSlider(Qt.Horizontal)
        self.mini_seek.setRange(0, 1000)
        self.mini_seek.setObjectName("seek")
        self.mini_seek.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.mini_seek.sliderReleased.connect(lambda: self.do_seek(self.mini_seek))
        self.mini_seek.valueChanged.connect(self._seek_preview)
        no_wheel(self.mini_seek)
        bottom.addWidget(self.mini_seek, 1)
        self.mini_time = QLabel(self.np_time.text())
        self.mini_time.setObjectName("muted")
        self.mini_time.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        bottom.addWidget(self.mini_time)
        cv.addLayout(bottom)
        v.addWidget(card)
        icons.set_icon(self.mini_pp, "play", size=16)
        return page

    def _set_np_name(self, text: str):
        self.np_name.setText(self.np_name.fontMetrics().elidedText(text, Qt.ElideRight, 186))
        self.np_name.setToolTip(text)
        self.mini_name.setText(text)   # elides itself to whatever room it has

    def _build_mixer(self) -> QFrame:
        """The levels strip along the bottom, the same on every tab: three labelled
        boxes, left to right the way the sound flows — your mic, what others hear,
        your own headphones. (Each tab's own volume sits in that tab's bar.)"""
        c = self.cfg
        f = QFrame()
        f.setObjectName("mixer")
        h = QHBoxLayout(f)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        self.mixer = f
        self._deck_titles: list[QWidget] = []
        self._decks: list[QFrame] = []

        def group(icon: str, title: str, tip: str) -> tuple[QLabel, QHBoxLayout]:
            deck = QFrame()
            deck.setObjectName("deck")
            self._decks.append(deck)
            box = QVBoxLayout(deck)
            box.setContentsMargins(12, 4, 12, 8)
            box.setSpacing(2)
            top = QWidget()
            top.setObjectName("decktop")
            th = QHBoxLayout(top)
            th.setContentsMargins(0, 0, 0, 0)
            th.setSpacing(6)
            th.addWidget(icon_label(icon, tip))
            lbl = QLabel(title)
            lbl.setObjectName("decktitle")
            lbl.setToolTip(tip)
            th.addWidget(lbl)
            th.addStretch(1)
            box.addWidget(top)
            self._deck_titles.append(top)
            row = QHBoxLayout()
            row.setSpacing(8)
            box.addLayout(row)
            h.addWidget(deck)
            return lbl, row

        self.mic_lbl, row = group("mic", "MY MIC",
                                  "Your real microphone, and how loud your voice is for others")
        self.chk_mic = QCheckBox("Others hear it")
        self.chk_mic.setToolTip("Send your voice to others along with the sounds.\n"
                                "Untick for sounds only: they hear your sounds but not "
                                "your mic.")
        self.chk_mic.setChecked(c.mic_enabled)
        self.chk_mic.toggled.connect(self.on_mic_toggle)
        row.addWidget(self.chk_mic)
        self.vol_mic = VolumeControl(c.mic_vol, meter=True,
                                     tip="How loud your voice is for others. The dot "
                                         "shows activity when you talk")
        self.mic_meter = self.vol_mic.meter
        row.addWidget(self.vol_mic)

        send_lbl, row = group("live", "WHAT OTHERS HEAR",
                              "Everything going out to Discord / the game right now: "
                              "your mic plus whatever is live")
        self.out_meter = Meter()
        self.out_meter.setMinimumWidth(60)
        self.out_meter.setToolTip("Level of what Discord / the game receives")
        row.addWidget(self.out_meter, 1)
        self.btn_check = QPushButton("Hear what they hear")
        self.btn_check.setObjectName("miccheck")
        self.btn_check.setCheckable(True)
        self.btn_check.setToolTip("Plays your mic into your headphones on top of the sounds — "
                                  "exactly what others hear. A red banner shows while it's on.")
        self.btn_check.toggled.connect(self.on_mic_check)
        icons.set_icon(self.btn_check, "ear", checked_color="#ffffff")
        row.addWidget(self.btn_check)
        h.setStretch(1, 1)   # the "what others hear" box takes the room

        self.hp_lbl, row = group("headphones", "MY HEADPHONES  ·  ONLY YOU",
                                 "Only what YOU hear. Doesn't change anything for others.")
        self.vol_mon = VolumeControl(c.mon_vol, tip="Only what YOU hear — doesn't change "
                                                    "anything for others")
        row.addWidget(self.vol_mon)
        self._mixer_hp = (self._decks[2],)
        self._mixer_send = (self.out_meter,)
        self._mixer_others = (self._decks[1],)

        for box, key in ((self.vol_mic, "mic_vol"), (self.vol_mon, "mon_vol")):
            box.changed.connect(lambda v, key=key: self.set_option(key, v))
        return f

    def _build_sounds_page(self) -> QWidget:
        c = self.cfg
        page = QWidget()
        left = QVBoxLayout(page)
        left.setContentsMargins(0, 8, 0, 0)
        left.setSpacing(8)
        tb = QHBoxLayout()
        tb.setSpacing(8)
        add = self.btn_add = QPushButton("Add sounds")
        add.setObjectName("primary")
        add.setToolTip("Add sound files (or drag them onto the window)")
        add.clicked.connect(self.add_dialog)
        icons.set_icon(add, "plus", "on_accent")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search sounds… Enter searches the web (YouTube, TikTok, "
                                       "Myinstants…), or paste a link")
        self.search.setToolTip("Type to filter your sounds, or paste a link (YouTube, "
                               "SoundCloud, TikTok, most media sites) to add or play it")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.apply_filter)
        self.search.returnPressed.connect(self.on_search_enter)
        self.btn_yt = QPushButton("Search")
        self.btn_yt.setToolTip("Search YouTube, SoundCloud, TikTok sounds, Myinstants… for "
                               "what's typed (or press Enter) — play or add the audio")
        icons.set_icon(self.btn_yt, "play", size=14)
        self.btn_yt.clicked.connect(self.search_youtube)
        more = self.btn_more = QPushButton("Backup")
        more.setToolTip("Export your sounds and settings to a file, or import a backup "
                        "or sound pack")
        icons.set_icon(more, "history")
        mm = QMenu(more)
        icons.set_icon(mm.addAction("Import a backup or sound pack…", self.import_dialog),
                       "folder")
        mm.addSeparator()
        mm.addAction("Export everything (sounds + settings)…", self.export_board)
        self._act_export_cat = mm.addAction("Export this category…", self.export_category)
        mm.addSeparator()
        icons.set_icon(mm.addAction("Recently deleted sounds…", self.show_deleted), "trash")
        icons.set_icon(mm.addAction("Open the sounds folder", self.open_sounds_folder),
                       "folder")   # here too, for when the window's too narrow for its button
        mm.aboutToShow.connect(lambda: self._act_export_cat.setEnabled(bool(self.cfg.category)))
        more.setMenu(mm)
        self.btn_bin = QPushButton()
        self.btn_bin.setToolTip("Sounds you removed: bring them back, exactly as they were")
        icons.set_icon(self.btn_bin, "trash")
        self.btn_bin.clicked.connect(self.show_deleted)
        self.btn_folder = QPushButton("Sounds folder")
        self.btn_folder.setToolTip("Open the folder your sounds are kept in. Sound files you "
                                   "drag into it join the board by themselves.")
        icons.set_icon(self.btn_folder, "folder")
        self.btn_folder.clicked.connect(self.open_sounds_folder)
        tb.addWidget(add)
        tb.addWidget(self.btn_folder)
        tb.addWidget(more)
        tb.addWidget(self.btn_bin)
        self._label_bin()
        # the most-used app-wide hotkeys in one click; the full list is in Settings
        self.btn_keys = QPushButton()
        self.btn_keys.setToolTip("Quick hotkeys: set the ones people use most, or open "
                                 "every hotkey in Settings")
        icons.set_icon(self.btn_keys, "keyboard")
        km = QMenu(self.btn_keys)
        km.aboutToShow.connect(lambda: self._fill_quick_hotkeys(km))
        self.btn_keys.setMenu(km)
        tb.addWidget(self.btn_keys)
        tb.addWidget(self.search, 1)
        tb.addWidget(self.btn_yt)
        size = QSlider(Qt.Horizontal)
        size.setRange(110, 240)
        c.pad_width = min(max(c.pad_width, 110), 240)   # the pads are built with it next
        size.setValue(c.pad_width)
        size.setFixedWidth(90)
        size.setToolTip("Pad size")
        size.valueChanged.connect(self.set_pad_width)
        no_wheel(size)
        size_lbl = QLabel("Pad size")
        size_lbl.setObjectName("muted")
        tb.addWidget(size_lbl)
        tb.addWidget(size)
        self._pad_size = (size_lbl, size)
        left.addLayout(tb)
        self.cat_bar = self._build_categories()
        left.addWidget(self.cat_bar)
        self.linkbar = LinkBar(
            self.engine, c, lambda: PAD_COLORS[len(self.cfg.sounds) % len(PAD_COLORS)],
            lambda: {m.fingerprint: m.name for m in self.cfg.sounds if m.fingerprint})
        self.linkbar.sound_ready.connect(self.on_downloaded)
        self.linkbar.played.connect(self.on_link_played)
        left.addWidget(self.linkbar)
        self.ytresults = SearchResults()
        self.ytresults.play.connect(lambda r: self._from_youtube(r, play=True))
        self.ytresults.add.connect(lambda r: self._from_youtube(r, play=False))
        self.linkbar.done.connect(lambda url, kind, ok: self.ytresults.mark(url, kind, ok))
        self.linkbar.progress.connect(self.ytresults.progress)
        left.addWidget(self.ytresults, 1)

        self.grid = PadGrid()
        self.grid.pad_w = c.pad_width
        self.grid.reorder.connect(self.on_reorder)
        # queued: the import (and any question it asks) runs after the drop returns,
        # so Explorer isn't frozen until a dialog is answered
        self.grid.files_dropped.connect(self.import_files, Qt.QueuedConnection)
        self.grid.image_dropped.connect(self.set_picture, Qt.QueuedConnection)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.grid)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)   # the pads fit the width
        left.addWidget(scroll, 1)
        self._pads_home = (left, left.indexOf(scroll))   # the mini player borrows it
        self.ytresults.closed.connect(scroll.show)   # the results take the pads' place
        self.ytresults.closed.connect(self._cat_row.show)   # ...and the categories' row
        self.ytresults.closed.connect(self._results_closed)
        self._pads_scroll = scroll
        # ---- "3 selected · Colour · Volume… · Delete": Ctrl / Shift+click picks pads
        self.selection = PadSelection(self, scroll)
        left.addWidget(self.selection.bar)

        # ---- "now playing" chips: shown while 2+ sounds overlap, so every one of
        # them can be stopped (■) or taken into the player (name) without clicking
        # its pad, which would restart it
        self.playing_row = QWidget()
        self._chips_hl = QHBoxLayout(self.playing_row)
        self._chips_hl.setContentsMargins(0, 0, 0, 0)
        self._chips_hl.setSpacing(6)
        self._chips: dict[str, QWidget] = {}
        self._chip_ids: tuple = ()
        self.playing_row.hide()
        left.addWidget(self.playing_row)

        # ---- "Removed X · Undo": a removed sound can be brought back for a while
        self.undo_bar = QFrame()
        self.undo_bar.setObjectName("chip")
        uh = QHBoxLayout(self.undo_bar)
        uh.setContentsMargins(10, 4, 4, 4)
        self.undo_lbl = QLabel()
        self.undo_lbl.setTextFormat(Qt.PlainText)   # sound names are user / web text
        uh.addWidget(self.undo_lbl, 1)
        undo = QPushButton("Undo")
        undo.setObjectName("primary")
        undo.setToolTip("Put the sound back, exactly as it was. Later: Backup → "
                        "Recently deleted sounds…")
        undo.clicked.connect(self.undo_remove)
        uh.addWidget(undo)
        dismiss = QPushButton()
        dismiss.setObjectName("chipstop")
        dismiss.setToolTip("Dismiss")
        dismiss.setFixedSize(24, 24)
        icons.set_icon(dismiss, "stop", size=10)
        dismiss.clicked.connect(self._finish_removals)
        uh.addWidget(dismiss)
        self.undo_bar.hide()
        left.addWidget(self.undo_bar)

        f, th = bar()
        self.btn_pp = QPushButton()
        self.btn_pp.setObjectName("round")
        self.btn_pp.setToolTip("Play / pause")
        self.btn_pp.clicked.connect(self.toggle_play_pause)
        self._pp_icon = None
        self.btn_st = QPushButton()
        self.btn_st.setObjectName("round")
        self.btn_st.setToolTip("Stop")
        self.btn_st.clicked.connect(self.stop_current)
        icons.set_icon(self.btn_st, "stop", size=16)
        for b in (self.btn_pp, self.btn_st):
            b.setFixedSize(38, 34)
        self.np_name = QLabel("Pick a sound")
        self.np_name.setToolTip("Select a sound pad to use these playback controls.")
        self.np_name.setTextFormat(Qt.PlainText)   # sound names are user / web text
        self.np_name.setFixedWidth(190)
        self.np_name.setStyleSheet("font-weight:600;")
        self.seek = SeekSlider(Qt.Horizontal)
        self.seek.setRange(0, 1000)
        self.seek.setObjectName("seek")
        self.seek.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.seek.sliderReleased.connect(self.do_seek)
        self.seek.valueChanged.connect(self._seek_preview)
        no_wheel(self.seek)
        self.np_time = QLabel("0:00 / 0:00")
        self.np_time.setFixedWidth(84)
        self.np_time.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.np_time.setObjectName("muted")
        th.addWidget(self.btn_pp)
        th.addWidget(self.btn_st)
        th.addWidget(self.np_name)
        th.addWidget(self.seek, 1)
        th.addWidget(self.np_time)
        self.speed_btn = SpeedPitchButton(
            "sounds", "Changes every sound while it plays. To save a version, "
                      "right-click a pad → Effects.")
        self.speed_btn.changed.connect(self.on_live_speed)
        th.addWidget(self.speed_btn)
        sep = vsep()
        th.addWidget(sep)
        vol_icon = icon_label("volume", "Volume of all your sounds")
        th.addWidget(vol_icon)
        self.vol_sound = VolumeControl(c.sound_vol, tip="How loud your sounds are — type up "
                                                        "to 1000% in the box")
        self.vol_sound.changed.connect(lambda v: self.set_option("sound_vol", v))
        th.addWidget(self.vol_sound)
        self.chk_monitor = QCheckBox("Hear it myself")
        self.chk_monitor.setToolTip("Also play your sounds into your headphones")
        self.chk_monitor.setChecked(c.monitor_sounds)
        self.chk_monitor.toggled.connect(lambda b: self.set_option("monitor_sounds", b))
        th.addWidget(self.chk_monitor)
        self._transport_vol = (sep, vol_icon, self.vol_sound)
        left.addWidget(f)
        self._set_pp_icon("play")
        return page

    def _update_chips(self, playing):
        """The row above the pads: what's playing (when it's more than the player shows)
        and the queue, each with its own ✕."""
        ids = tuple(s for s in self.pads if s in playing)
        queue = tuple(self._queue)
        if (ids, queue) != self._chip_ids:
            self._chip_ids = (ids, queue)
            while self._chips_hl.count():
                w = self._chips_hl.takeAt(0).widget()
                if w:
                    w.deleteLater()
            self._chips = {}
            if queue:
                lbl = QLabel("Up next")
                lbl.setObjectName("muted")
                self._chips_hl.addWidget(lbl)
                for i, sid in enumerate(queue[:QUEUE_CHIPS]):
                    m = self.meta(sid)
                    self._chips_hl.addWidget(self._chip(
                        m.name if m else sid, "Waits for the sounds playing to finish",
                        lambda _=False, s=sid: self.select(s),
                        "Take it out of the queue", lambda _=False, i=i: self._unqueue(i)))
                if len(queue) > QUEUE_CHIPS:
                    more = QLabel(f"+{len(queue) - QUEUE_CHIPS} more")
                    more.setObjectName("muted")
                    self._chips_hl.addWidget(more)
            if len(ids) >= 2:
                lbl = QLabel("Now playing")
                lbl.setObjectName("muted")
                self._chips_hl.addWidget(lbl)
                for sid in ids:
                    m = self.meta(sid)
                    chip = QFrame()
                    chip.setObjectName("chip")
                    ch = QHBoxLayout(chip)
                    ch.setContentsMargins(4, 2, 2, 2)
                    ch.setSpacing(2)
                    name = QPushButton(chip.fontMetrics().elidedText(
                        m.name if m else sid, Qt.ElideRight, 150))
                    name.setObjectName("chipname")
                    name.setToolTip("Show this sound in the player (keeps playing)")
                    name.clicked.connect(lambda _=False, s=sid: self.select(s))
                    stop = QPushButton()
                    stop.setObjectName("chipstop")
                    stop.setToolTip("Stop this sound")
                    icons.set_icon(stop, "stop", "danger_text", size=12)
                    stop.setFixedSize(24, 24)
                    stop.clicked.connect(lambda _=False, s=sid: self.engine.stop(s))
                    ch.addWidget(name)
                    ch.addWidget(stop)
                    self._chips_hl.addWidget(chip)
                    self._chips[sid] = chip
            if queue or len(ids) >= 2:
                self._chips_hl.addStretch(1)
            self.playing_row.setVisible(len(ids) >= 2 or bool(queue))
        for sid, chip in self._chips.items():
            sel = "true" if sid == self.current else "false"
            if chip.property("sel") != sel:
                chip.setProperty("sel", sel)
                chip.style().unpolish(chip)
                chip.style().polish(chip)

    def _chip(self, text: str, tip: str, on_click, x_tip: str, on_x) -> QFrame:
        """A queued sound's chip: its name, and a ✕."""
        chip = QFrame()
        chip.setObjectName("chip")
        ch = QHBoxLayout(chip)
        ch.setContentsMargins(4, 2, 2, 2)
        ch.setSpacing(2)
        name = QPushButton(chip.fontMetrics().elidedText(text, Qt.ElideRight, 150))
        name.setObjectName("chipname")
        name.setToolTip(tip)
        name.clicked.connect(on_click)
        x = QPushButton("✕")
        x.setObjectName("chipstop")
        x.setToolTip(x_tip)
        x.setFixedSize(24, 24)
        x.clicked.connect(on_x)
        ch.addWidget(name)
        ch.addWidget(x)
        return chip

    def _unqueue(self, i: int):
        if 0 <= i < len(self._queue):
            del self._queue[i]
            self._say_queue()

    def drop_pending(self, sid: str):
        """`sid` won't start later after all: off the queue, and not when its wait
        before playing is over (what pressed it is gone, e.g. a deleted trigger)."""
        self._cancel_waiting(sid)
        if sid in self._queue:
            self._queue = [s for s in self._queue if s != sid]
            self._say_queue()

    def _set_pp_icon(self, name: str):
        if name != self._pp_icon:
            self._pp_icon = name
            for b in (self.btn_pp, getattr(self, "mini_pp", None)):
                if b is not None:
                    b.setIcon(icons.icon(name))
                    b.setIconSize(QSize(16, 16))

    def _build_setup_page(self) -> QWidget:
        """One-time setup and the rarely-touched stuff: where the audio goes,
        devices, the recorded test, EQ, levelling."""
        c = self.cfg
        page = QScrollArea()
        page.setWidgetResizable(True)
        page.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        cols = self._setup_cols = QHBoxLayout(inner)
        cols.setContentsMargins(0, 10, 4, 10)
        cols.setSpacing(12)
        lcol, rcol = QVBoxLayout(), QVBoxLayout()
        for col in (lcol, rcol):
            col.setSpacing(12)
            cols.addLayout(col, 1)
        page.setWidget(inner)

        # ---- how it works + the one thing to set in Discord
        howcard, cv = card("YOUR VIRTUAL MIC")
        self.flow_mic = QLabel()
        self.flow_snd = QLabel("Your sounds, radio and voice effects")
        arrow = QLabel("↓   the app mixes them together")
        arrow.setObjectName("muted")
        self.flow_out = QLabel()
        for ic, w in (("mic", self.flow_mic), ("volume", self.flow_snd), ("", arrow),
                      ("cable", self.flow_out)):
            w.setTextFormat(Qt.RichText)
            w.setWordWrap(True)
            row = QHBoxLayout()
            row.setSpacing(8)
            if ic:
                row.addWidget(icon_label(ic))
            else:
                row.addSpacing(26)
            row.addWidget(w, 1)
            cv.addLayout(row)
        self.step_lbl = QLabel()
        self.step_lbl.setWordWrap(True)
        self.step_lbl.setTextFormat(Qt.RichText)
        self.step_lbl.setObjectName("stepbox")
        cv.addWidget(self.step_lbl)
        self.btn_install = QPushButton("Install the free virtual cable")
        self.btn_install.setObjectName("primary")
        self.btn_install.clicked.connect(self.install_cable)
        icons.set_icon(self.btn_install, "cable", "on_accent")
        cv.addWidget(self.btn_install)
        self.btn_rescan = QPushButton("I've installed it — check again")
        self.btn_rescan.clicked.connect(lambda: self.rescan_with_feedback(self.btn_rescan))
        icons.set_icon(self.btn_rescan, "reload")
        cv.addWidget(self.btn_rescan)
        self.btn_chat = QPushButton("Make it sound clean in Discord")
        self.btn_chat.setToolTip("The Discord settings that stop it chopping up your sounds, "
                                 "and a check that listens to what Discord does to them")
        icons.set_icon(self.btn_chat, "headphones")
        self.btn_chat.clicked.connect(lambda: self.show_chat_guide("discord"))
        cv.addWidget(self.btn_chat)
        self.btn_game = QPushButton("…or in a game's voice chat")
        self.btn_game.clicked.connect(lambda: self.show_chat_guide("game"))
        cv.addWidget(self.btn_game)
        self.btn_nomic = QPushButton("Game has no microphone setting?")
        self.btn_nomic.clicked.connect(self.open_windows_mic)
        cv.addWidget(self.btn_nomic)
        guide = QPushButton("Step-by-step guide")
        guide.setToolTip("Walks you through mic, headphones, the cable and Discord")
        icons.set_icon(guide, "check")
        guide.clicked.connect(self.run_setup)
        cv.addWidget(guide)
        lcol.addWidget(howcard)

        # ---- devices
        devcard, av = card("DEVICES", "Already set up for you — only change these if "
                                      "something's wrong.")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        self.cb_main, self.cb_mon, self.cb_mic = QComboBox(), QComboBox(), QComboBox()
        for r, (ic, text, cb) in enumerate((
                ("cable", "Send into (the cable)", self.cb_main),
                ("headphones", "My headphones", self.cb_mon),
                ("mic", "My real mic", self.cb_mic))):
            grid.addWidget(icon_label(ic), r, 0)
            grid.addWidget(QLabel(text), r, 1)
            grid.addWidget(cb, r, 2)
            cb.setMinimumWidth(120)
        grid.setColumnStretch(2, 1)
        av.addLayout(grid)
        self.setup_hint = hint_label("")
        self.setup_hint.setTextFormat(Qt.RichText)
        av.addWidget(self.setup_hint)
        self.btn_cablefix = QPushButton("Fix the cable: both ends to 48 kHz")
        self.btn_cablefix.setToolTip("Sets the cable's playback and recording side to "
                                     "48 kHz, so it passes your sound through without "
                                     "converting it")
        self.btn_cablefix.clicked.connect(lambda: busy.run_busy(
            self.btn_cablefix, "Switching the cable to 48 kHz…", self.fix_cable_format,
            lambda ok: "✓ Done" if ok and not self.cable_bad else "Couldn't — see below"))
        self.btn_cablefix.hide()
        av.addWidget(self.btn_cablefix, 0, Qt.AlignLeft)
        no_wheel(self.cb_main, self.cb_mon, self.cb_mic)
        for cb, attr in ((self.cb_main, "main_device"), (self.cb_mon, "mon_device"),
                         (self.cb_mic, "mic_device")):
            cb.activated.connect(lambda _i, cb=cb, attr=attr: self.on_device(cb, attr))
        ref = QPushButton("Re-scan devices")
        icons.set_icon(ref, "reload")
        ref.clicked.connect(lambda: self.rescan_with_feedback(ref))
        av.addWidget(ref, 0, Qt.AlignLeft)
        lcol.addWidget(devcard)

        # ---- who's listening: shape the sounds for the voice chat on the other end
        destcard, dv = card("WHO'S LISTENING", "Where people hear you. Your sounds are "
                                               "shaped to come through that voice chat's "
                                               "compression clearly.")
        from soundboard.ui.destpanel import DestPanel
        self.dest_panel = DestPanel(self)
        dv.addWidget(self.dest_panel)
        lcol.addWidget(destcard)
        lcol.addStretch(1)

        # ---- test
        testcard, tv = card("TEST IT", "Talk while a sound plays. Records what Discord / the "
                                       "game actually receives, plays it back, and tells you "
                                       "if your voice + sounds are in it.")
        self.btn_rec = QPushButton("Record 6s → play back")
        self.btn_rec.setObjectName("primary")
        icons.set_icon(self.btn_rec, "record", "on_accent")
        self.btn_rec.clicked.connect(self.start_test)
        tv.addWidget(self.btn_rec)
        # a live check right here, the same switch as the mixer's at the bottom
        live = QHBoxLayout()
        self.btn_check_test = QPushButton("Hear what they hear")
        self.btn_check_test.setObjectName("miccheck")
        self.btn_check_test.setCheckable(True)
        self.btn_check_test.setToolTip("A live check: plays your output (your mic and sounds) "
                                       "into your headphones. Click again to stop.")
        icons.set_icon(self.btn_check_test, "ear", checked_color="#ffffff")
        live.addWidget(self.btn_check_test)
        live.addWidget(hint_label("Live: hear exactly what they hear, in your headphones."), 1)
        tv.addLayout(live)
        self.test_result = QLabel()
        self.test_result.setWordWrap(True)
        self.test_result.setTextFormat(Qt.RichText)
        self.test_result.setObjectName("resultbox")
        self.test_result.hide()
        tv.addWidget(self.test_result)
        rcol.addWidget(testcard)

        # ---- sound shaping
        eqcard, ev = card()
        self.eq = EqPanel(c.eq_enabled, c.eq_target, c.eq_preset, c.eq_gains)
        self.eq.changed.connect(self.on_eq)
        ev.addWidget(self.eq)
        self.chk_level = QCheckBox("Level volumes (all sounds equally loud)")
        self.chk_level.setChecked(c.level_volumes)
        self.chk_level.toggled.connect(self.on_level_toggle)
        ev.addWidget(self.chk_level)
        hk = QPushButton("Hotkeys && auto push-to-talk…")
        hk.setToolTip("Opens Settings → Hotkeys")
        hk.clicked.connect(lambda: self.open_settings("hotkeys"))
        ev.addWidget(hk, 0, Qt.AlignLeft)
        rcol.addWidget(eqcard)
        rcol.addStretch(1)
        self.on_eq(*self.eq.state())   # push the saved EQ into the engine
        destination.apply(self.cfg, self.engine)   # ...and the destination mode (Who's listening)
        from soundboard.ui.destpanel import apply_send
        apply_send(self.cfg, self.engine)          # ...and mono / ducking
        return page

    def on_eq(self, gains, enabled, target, preset):
        c = self.cfg
        c.eq_enabled, c.eq_target, c.eq_preset, c.eq_gains = enabled, target, preset, list(gains)
        self.engine.eq_target = target
        self.engine.eq_gains = list(gains) if enabled else None
        self._save_later()

    # ------------------------------------------------------------------ devices
    def refresh_devices(self) -> str:
        """Re-scan the sound devices and reopen the streams. Returns a short result
        for the button that asked ("✓ Found 7 devices", "No cable yet", …)."""
        e = self.engine
        e.shutdown()
        rescanned = eng.rescan()
        self._init_devices()
        self._prepare_all()
        outs = eng.list_devices("output")
        if not rescanned:   # after _init_devices, whose status update would hide it
            self.status.setText(f"<span style='color:{theme.status('warn')}'>"
                                "Couldn't re-scan devices — "
                                "restart the app to pick up new ones.</span>")
            return "Couldn't re-scan"
        if not any(is_virtual_cable(d["name"]) for d in outs):
            self.status.setText(f"<span style='color:{theme.status('warn')}'>"
                                "Still no virtual cable. If you "
                                "just installed it, restart your PC — Windows often only "
                                "shows it after a restart.</span>")
            return "No cable found yet"
        n = len({d["name"] for d in outs} | {d["name"] for d in eng.list_devices("input")})
        return f"✓ Found {n} device{'s' if n != 1 else ''}"

    def rescan_with_feedback(self, btn, after=None):
        """A Re-scan button: "Scanning…" while it runs, then what it found."""
        def go():
            msg = self.refresh_devices()
            if after:
                after()
            return msg
        busy.run_busy(btn, "Scanning…", go, lambda msg: msg, ms=3000)

    def set_latency(self, mode: str):
        """'low' (default) or 'high' (bigger buffers: more delay, fewer drop-outs)."""
        if mode not in ("low", "high") or mode == self.cfg.latency:
            return
        self.cfg.latency = mode
        self.engine.latency = mode
        self.engine.reopen_all()
        self._save_now()
        self._update_status()

    def _init_devices(self):
        outs = [d["name"] for d in eng.list_devices("output")]
        # a virtual cable as the *mic* would record our own output and feed it back
        # into itself (a loud feedback screech), so cables never appear here
        ins = [d["name"] for d in eng.list_devices("input") if not is_virtual_cable(d["name"])]
        c = self.cfg
        if c.mic_device and is_virtual_cable(c.mic_device):
            c.mic_device = None   # was set to the cable: fall back to the real mic
        if not c.main_device or eng.find_device("output", c.main_device) is None:
            c.main_device = next(iter(eng.virtual_outputs()), None) or c.main_device
        if c.mon_follows_default:   # Windows' default now, not when PortAudio started
            c.mon_device = self._default_output() or c.mon_device
        if not c.mon_device:
            dflt = eng.default_device_name("output")
            c.mon_device = dflt if dflt and not is_virtual_cable(dflt) else \
                next((n for n in outs if not is_virtual_cable(n)), None)
        if not c.mic_device:
            dflt = eng.default_device_name("input")
            c.mic_device = dflt if dflt and not is_virtual_cable(dflt) else \
                next(iter(ins), None)
        self._fill_combo(self.cb_main, outs, c.main_device)
        self._fill_combo(self.cb_mon, outs, c.mon_device)
        self._fill_combo(self.cb_mic, ins, c.mic_device)

        e = self.engine
        e.sound_vol, e.mic_vol, e.mon_vol = c.sound_vol, c.mic_vol, c.mon_vol
        e.mic_enabled, e.monitor_sounds = c.mic_enabled, c.monitor_sounds
        e.obs_vol, e.obs_voice = c.obs_vol, c.obs_voice
        e.set_mic_device(c.mic_device)
        e.set_main_device(c.main_device)
        e.set_mon_device(c.mon_device)
        e.set_obs_device(self._obs_name(c.obs_device))
        self._check_cable_format()
        self._update_status()

    def _default_output(self) -> str | None:
        """Windows' default output as the device lists name it (None: unknown, or the
        cable, which is never the headphones)."""
        idx = eng.find_device("output", self._default_out)
        name = eng.list_name(idx) if idx is not None else None
        return None if name is None or is_virtual_cable(name) else name

    def _follow_default_output(self):
        """Windows' default output changed (headphones → speakers): the headphones
        output moves with it, unless another device was picked for it by hand."""
        now = appaudio.default_output_name()
        if not now or now == self._default_out:
            return
        self._default_out = now
        c = self.cfg
        if not c.mon_follows_default:
            return
        name = self._default_output()
        if name is None and not is_virtual_cable(now):
            self.refresh_devices()   # plugged in since the app started: not listed yet
            name = self._default_output()
        if name is None or name == c.mon_device:
            return
        log.info("Windows' default output changed: headphones %r -> %r", c.mon_device, name)
        c.mon_device = name
        self._fill_combo(self.cb_mon, [d["name"] for d in eng.list_devices("output")], name)
        self.engine.set_mon_device(name)
        obs = self._obs_name(c.obs_device)
        if self.engine.names["obs"] != obs:
            self.engine.set_obs_device(obs)
        self._save_now()
        self._update_status()
        self.status.setText(f"You hear your sounds on {html.escape(name)} now: it's "
                            "Windows' default output.")

    def _check_cable_format(self):
        """Note which ends of the cable in use aren't at 48 kHz (shown on the Setup tab)."""
        from soundboard import cableformat
        main = self.cfg.main_device
        vm = eng.virtual_mic_for(main)
        try:
            ends = cableformat.pair(cableformat.cable_ends(), main, vm) if vm else []
        except Exception:  # noqa: BLE001 - only a hint
            log.debug("cable format check failed", exc_info=True)
            ends = []
        self.cable_bad = [x for x in ends if not x.ok]
        if self.cable_bad:
            log.info("cable not at 48 kHz: %s",
                     ", ".join(f"{x.name} @ {x.rate}" for x in self.cable_bad))

    def fix_cable_format(self, quiet: bool = False) -> bool:
        """Put both ends of the cable on 48 kHz, then reopen the streams at the new rate."""
        from soundboard import cableformat
        self._check_cable_format()
        if not self.cable_bad:
            return True
        ok = cableformat.fix(self.cable_bad)
        self.refresh_devices()   # the rates changed: rescan and reopen (re-checks too)
        if not quiet:
            if ok and not self.cable_bad:
                msg, kind = ("✓ The cable is on 48 kHz both ends now. If Discord goes "
                             "quiet, rejoin the voice channel."), "ok"
            else:
                msg, kind = ("Couldn't change the cable's format. Set it by hand: Sound "
                             "settings → the cable → Advanced → 48000 Hz."), "warn"
            self.status.setText(f"<span style='color:{theme.status(kind)}'>{msg}</span>")
            self.toast(msg, kind)
        return ok

    def show_chat_guide(self, which: str):
        from soundboard.ui.chatguide import show_guide
        show_guide(which, self, self, self.virtual_mic or "CABLE Output")

    def _fill_combo(self, cb, names, current):
        cb.blockSignals(True)
        cb.clear()
        cb.addItem("— none —", None)
        for n in names:
            cb.addItem(n, n)
        i = cb.findData(current) if current else 0
        cb.setCurrentIndex(i if i >= 0 else 0)
        cb.blockSignals(False)

    def on_device(self, cb, attr):
        name = cb.currentData()
        setattr(self.cfg, attr, name)
        if attr == "main_device":
            self.engine.set_main_device(name)
            self._check_cable_format()
        elif attr == "mon_device":
            self.engine.set_mon_device(name)
            # picking Windows' default keeps following it; anything else stays put
            self.cfg.mon_follows_default = name is not None and name == self._default_output()
        else:
            self.engine.set_mic_device(name)
        obs = self._obs_name(self.cfg.obs_device)   # never the cable or headphones too
        if self.engine.names["obs"] != obs:
            self.engine.set_obs_device(obs)
        self._save_now()
        self._update_status()
        self._prepare_all()

    def _obs_name(self, name: str | None) -> str | None:
        """The stream output's device, unless it's the cable (or another end of the
        same cable: everyone in the call would get everything twice) or the
        headphones (you'd hear it twice)."""
        if (name in (None, self.cfg.main_device, self.cfg.mon_device)
                or eng.same_cable(name, self.cfg.main_device)):
            return None
        return name

    def set_obs_device(self, name: str | None):
        """Settings -> Audio -> Stream output (OBS): None switches it off."""
        self.cfg.obs_device = name
        self.engine.set_obs_device(self._obs_name(name))
        self._save_now()
        self._update_status()
        self._prepare_all()

    def _prepare_all(self):
        items = list(self.audio.items())
        threading.Thread(target=lambda: [self.engine.prepare(s, d) for s, d in items],
                         daemon=True, name="prepare").start()

    def on_mic_toggle(self, b):
        """Send my mic to others, or sounds only. The mic itself stays open either
        way (the meter, the tests and live voice-to-speech still hear it); this only
        decides whether it's mixed into what others get."""
        self.set_option("mic_enabled", b)
        self._update_status()

    def _update_status(self):
        e = self.engine
        main = self.cfg.main_device or ""
        self.virtual_mic = eng.virtual_mic_for(main)
        if self.virtual_mic:
            hint = (f"A virtual cable is a pipe: audio goes in at <b>{main}</b> "
                    f"and comes out at <b>{self.virtual_mic}</b>, which Discord "
                    "/ the game uses as your mic.")
            if self.cable_bad:
                rates = " and ".join(f"{x.rate / 1000:g} kHz" for x in self.cable_bad)
                hint += (f"<br><span style='color:{theme.status('warn')}'>One end of the "
                         f"cable is on {rates}, so it converts your sound on the way "
                         "through. Fix it for the cleanest sound.</span>")
            self.setup_hint.setText(hint)
        elif main:
            self.setup_hint.setText(f"<span style='color:{theme.status('warn')}'>"
                                    "That's a normal speaker/headphone "
                                    "device, so only you will hear the sounds. Pick a virtual "
                                    "cable here.</span>")
        else:
            self.setup_hint.setText(f"<span style='color:{theme.status('warn')}'>"
                                    "Nothing picked — only you "
                                    "will hear sounds.</span>")
        self._update_flow()
        errs = [f"{'stream output' if k == 'obs' else k}: {v}"
                for k, v in e.errors_snapshot().items()]
        if errs:
            self.status.setText(f"<span style='color:{theme.status('error')}'>"
                                "Audio device problem — "
                                + " · ".join(errs) + "</span>")
            return
        text = ""
        xr = sum(e.xruns.values())
        self._xruns_shown = xr
        if xr:
            tip = ("" if self.cfg.latency == "high" else
                   " — try Settings → Audio → Audio buffering: Safer")
            text += (f"{'<br>' if text else ''}<span style='color:{theme.status('warn')}'>"
                     f"{xr} audio drop-out"
                     f"{'s' if xr != 1 else ''} since start{tip}</span>")
        self.status.setText(text)

    def _update_flow(self, talking=False):
        e = self.engine
        ok, bad = theme.status("ok"), theme.status("error")
        if not self.cfg.mic_enabled:
            mic = f"Your mic  <b style='color:{theme.status('warn')}'>not sent (sounds only)</b>"
        elif e.mic_stream is None:
            mic = f"Your mic  <b style='color:{bad}'>✗ off</b>"
        elif talking:
            mic = f"Your mic  <b style='color:{ok}'>✓ hearing you</b>"
        else:
            mic = f"Your mic  <b style='color:{ok}'>✓</b>"
        vm = self.virtual_mic
        any_cable = bool(eng.virtual_outputs())
        if not any_cable:
            state = "missing"
            out = f"Virtual mic  <b style='color:{bad}'>✗ not installed yet</b>"
            step = (f"<b style='color:{theme.status('warn')}'>"
                    "One-time setup:</b> install the free virtual "
                    "cable. It's what lets Discord and games hear your sounds — without it, "
                    "only you can hear them.")
        elif vm and e.main_stream is not None:
            state = "ok"
            out = (f"<b style='color:{ok}'>{vm}</b> — your new mic "
                   f"<b style='color:{ok}'>✓ working</b>")
            step = (f"<b>The only thing you set:</b> in Discord or your game, pick "
                    f"<b style='color:{ok}'>{vm}</b> as your <b>microphone</b>, and switch "
                    "off its noise suppression (Discord: <b>Input Profile → Studio</b>), "
                    "or it chops your sounds up.")
        else:
            state = "unrouted"
            out = f"Virtual mic  <b style='color:{bad}'>✗ not connected</b>"
            step = (f"<b style='color:{theme.status('warn')}'>"
                    "Almost:</b> under <b>Devices</b>, set "
                    "“Send into (the cable)” to your virtual cable.")
        self.flow_mic.setText(mic)
        self.flow_out.setText(out)
        self.step_lbl.setText(step)
        self.btn_install.setVisible(state == "missing")
        self._cable_follow_switch()
        self.btn_rescan.setVisible(state == "missing")
        self.btn_nomic.setVisible(state == "ok")
        self.btn_chat.setVisible(state == "ok")
        self.btn_game.setVisible(state == "ok")
        self.btn_cablefix.setVisible(state == "ok" and bool(self.cable_bad))
        self.setup_state = state
        short = self._pill_short
        if state == "ok":
            pill = "Connected" if short else f"Your mic in Discord / games:  {vm}"
        elif state == "missing":
            pill = ("Setup needed" if short
                    else "One-time setup needed — others can't hear you yet")
        else:
            pill = ("Not connected" if short
                    else "Not connected to the virtual cable — click to fix")
        if self.pill.text() != pill:
            self.pill.setText(pill)
            self.pill.setIcon(icons.icon("check", "ok_text") if state == "ok" else
                              icons.icon("warn", "warn_text"))
            self.pill.setProperty("state", "ok" if state == "ok" else "warn")
            self.pill.style().unpolish(self.pill)
            self.pill.style().polish(self.pill)

    def install_cable(self):
        if not net.allowed("setup_downloads"):   # its download can't go through the app
            self.toast(html.escape(net.off_message("setup_downloads")), "warn")
            return
        script = RESOURCE_DIR / "install-vbcable.ps1"
        if not script.exists():
            QMessageBox.warning(self, "Installer missing", f"Can't find {script.name}.")
            return
        try:
            subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                              "-File", str(script)],
                             creationflags=subprocess.CREATE_NEW_CONSOLE)
        except OSError as e:
            log.warning("couldn't start the cable installer", exc_info=True)
            QMessageBox.warning(
                self, "Couldn't start the installer",
                f"Windows wouldn't run PowerShell ({errors.plain(e)}).\n\nYou can install "
                "VB-Cable by hand: download it from vb-audio.com, unzip it, right-click "
                "VBCABLE_Setup_x64.exe → Run as administrator → Install Driver.")
            return
        QMessageBox.information(
            self, "Installing the virtual cable",
            "A window opened that downloads VB-Cable (free) from the official VB-Audio site.\n\n"
            "Windows will ask for permission — click Yes, then click “Install Driver”.\n\n"
            "When it's done, click “I've installed it — check again”. If it doesn't show up, "
            "restart your PC.")

    def run_setup(self, resumed: bool = False):
        """The quick-setup guide (first launch, or the Setup tab's Step-by-step guide).
        `resumed`: reopened by itself after the restart the virtual cable needed."""
        from soundboard.ui.setupwizard import SetupWizard
        wiz = SetupWizard(self, resumed=resumed)
        wiz.exec()
        free_dialog(wiz)
        self._prepare_all()

    def open_windows_mic(self):
        vm = self.virtual_mic or "your virtual cable"
        try:
            subprocess.Popen(["control", "mmsys.cpl,,1"], creationflags=0x08000000)
        except OSError:
            log.warning("couldn't open the Sound control panel", exc_info=True)
            QMessageBox.warning(self, "Couldn't open the Sound settings",
                                "Open it yourself: press Win+R, type  mmsys.cpl  and press "
                                "Enter, then go to the Recording tab.")
            return
        QMessageBox.information(
            self, "Game with no mic setting",
            "Some games just use Windows' main mic. A sound window just opened:\n\n"
            f"1.  Right-click  {vm}  →  Set as Default Device\n"
            "2.  Right-click it again  →  Set as Default Communication Device\n"
            "     (voice chat in many games asks Windows for that one)\n"
            "3.  Restart the game.\n\n"
            "Heads-up: voice typing will then also hear your sounds.\n"
            "To undo, do the same on your normal mic.")

    # ------------------------------------------------------------------ settings
    def set_option(self, attr: str, v):
        """Change one config value (mirrored onto the engine when it has the same
        attribute) and save shortly after. The small public surface the Settings
        window and dialogs use."""
        setattr(self.cfg, attr, v)
        if hasattr(self.engine, attr):
            setattr(self.engine, attr, v)
        self._save_later()

    def _poll_voice(self):
        key = self.voice_watch.poll() if self.voice_watch is not None else None
        if key != self.voice_suggestion:
            self.voice_suggestion = key
            self.voice_engine.emit(key)

    def _save_later(self):
        self._save_timer.start(400)

    def toast(self, text: str, kind: str = ""):
        """A result the user should see now, whatever tab or dialog is in front (the
        status line is rewritten on every tab change and hidden in small windows)."""
        busy.toast(self, text, kind)

    def _make_radio(self):
        """The Radio tab, or with Radio switched off in Settings > Privacy & security a
        panel saying so: then no directory, player or web view is made at all."""
        if net.allowed("radio"):
            r = RadioTab(self.engine, self.cfg, self._save_later, Meter)
            r.clip_ready.connect(self.on_clip)
        else:
            r = RadioOff()
            r.open_settings.connect(lambda: self.open_settings("privacy"))
        r.active_changed.connect(self._radio_live)
        self.radio_page.addWidget(r)
        self.radio_page.setCurrentWidget(r)
        return r

    def _radio_live(self, on: bool):
        set_tab_live(self.tabs, self.tabs.indexOf(self.radio_page), on,
                     self.radio.live_tip(), "radio")

    def _follow_switches(self):
        """Settings > Privacy & security changed: the parts of the window that go
        online follow their switches."""
        self._radio_follow_switch()
        self._cable_follow_switch()
        self._search_follow_switch()

    def _search_follow_switch(self):
        """Finding sounds online switched off: no Search button, and the search box
        only filters your own sounds."""
        self.btn_yt.setVisible(self.ytresults.available())

    def _cable_follow_switch(self):
        allowed = net.allowed("setup_downloads")
        self.btn_install.setEnabled(allowed)
        self.btn_install.setToolTip("" if allowed else net.off_message("setup_downloads"))

    def _radio_follow_switch(self):
        """Radio switched off: the tab becomes the "off" panel (a playing station
        stops); switched back on, the tab is built again."""
        if net.allowed("radio") == isinstance(self.radio, RadioTab):
            return
        old, playing = self.radio, self.radio.is_active()
        old.shutdown()
        self.radio = self._make_radio()
        self.radio_page.removeWidget(old)
        old.deleteLater()
        self._radio_live(False)
        if playing:
            self.toast(html.escape("Radio was switched off, so the station stopped."))

    def _on_tor(self):
        """Something is waiting for Tor: say so (once), and when it's ready or failed."""
        t = tor.manager()
        if t.state == tor.STARTING and t.waiting:
            say = ("starting", "Connecting to Tor… what you asked for goes once it's "
                                "connected (Settings → Privacy & security shows how far "
                                "it is).", "")
        elif t.state == tor.READY and self._tor_told == "starting":
            say = ("ready", "✓ Connected to Tor.", "ok")
        elif t.state == tor.FAILED and self._tor_told in ("starting", "") and t.waiting:
            say = ("failed", f"Couldn't connect to Tor: {t.message}. Nothing was sent "
                               "without it.", "error")
        elif t.state == tor.OFF:
            self._tor_told = ""
            return
        else:
            return
        if say[0] != self._tor_told:
            self._tor_told = say[0]
            self.toast(html.escape(say[1]), say[2])

    def _save_now(self):
        """The debounced save. A failure (disk full, antivirus lock) is logged by
        Config.save; here it's shown once so the user knows settings aren't sticking."""
        if self.cfg.save():
            self._save_failed_shown = False
        elif not self._save_failed_shown:
            self._save_failed_shown = True
            self.status.setText(f"<span style='color:{theme.status('error')}'>"
                                "Couldn't save your settings — "
                                r"see the log in %APPDATA%\OnionBoard.</span>")
            self.toast(r"Couldn't save your settings — see the log in %APPDATA%\OnionBoard.",
                       "error")

    def on_level_toggle(self, b):
        self.set_option("level_volumes", b)
        for m in self.cfg.sounds:
            self.engine.set_gain(m.id, self.gain_for(m))

    def on_top_toggle(self, b):
        self.set_option("always_on_top", b)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, b)
        self.show()

    def set_pad_width(self, w):
        self.cfg.pad_width = w
        self.grid.set_pad_width(w)
        self._save_later()

    # ------------------------------------------------------------------ hotkeys
    def _fit_overlay_key(self):
        """The default overlay key is the one left of 1 on a US keyboard, where it types
        a rarely used `. On most other layouts that key types a letter or everyday
        punctuation (ö, ñ, ù, UK '@), which a bare global hotkey would take away from
        typing everywhere: there it becomes Alt + that key. Checked once, so a key the
        user picks later is left alone."""
        if self.cfg.overlay_key_checked:
            return
        self.cfg.overlay_key_checked = True
        if self.cfg.overlay_hotkey == "`" and winkeys.key_char(winkeys.VK["`"]) not in ("`", ""):
            self.cfg.overlay_hotkey = "alt+`"
            log.info("overlay hotkey moved to Alt+` for this keyboard layout")
        self._save_later()

    def register_hotkeys(self):
        mapping = {}
        if self._hotkeys_off:   # only the key that turns them back on
            if self.cfg.hotkeys_off_hotkey:
                mapping[self.cfg.hotkeys_off_hotkey] = "__hotkeys__"
            self.hotkeys.register(mapping)
            self.replay.set_enabled(bool(self.cfg.replay_hotkey), self.cfg.replay_seconds)
            return
        for attr, action, _label, _desc in HOTKEY_ACTIONS:
            combo = getattr(self.cfg, attr)
            if combo:
                mapping.setdefault(combo, action)
        for m in self.cfg.sounds:
            if m.hotkey and self._hotkey_live(m):
                mapping.setdefault(m.hotkey, m.id)
        for cat, combo in self.cfg.category_hotkeys.items():
            if combo and cat in self.cfg.categories:
                mapping.setdefault(combo, RANDOM + cat)
        mapping.update(self.overlay.layer())   # its keys, only while it's open
        # the game's push-to-talk key is pressed by us (auto-PTT) and by the player: as a
        # hotkey of ours, Windows would hand those presses to us instead of the game
        mapping.pop(self.cfg.ptt_key, None)
        self.hotkeys.register(mapping)
        # instant replay listens only while its hotkey is set
        self.replay.set_enabled(bool(self.cfg.replay_hotkey), self.cfg.replay_seconds)

    def _hotkey_live(self, m: SoundMeta) -> bool:
        """Does m's hotkey work right now? Always, unless hotkeys follow the category
        (scoped_hotkeys): then only while a category it's in is showing (All shows
        every sound; one in no category always keeps its key)."""
        cat = self.cfg.category
        return not self.cfg.scoped_hotkeys or not cat or not m.tags or cat in m.tags

    def set_scoped_hotkeys(self, on: bool):
        """Settings -> Hotkeys: a set of sound hotkeys per category."""
        self.cfg.scoped_hotkeys = on
        if not on:   # one key, one sound again: the first sound (in board order) keeps it
            seen = set(self._global_combos())
            for m in self.cfg.sounds:
                if m.hotkey and m.hotkey in seen:
                    m.hotkey = ""
                    if m.id in self.pads:
                        self.pads[m.id].update()
                elif m.hotkey:
                    seen.add(m.hotkey)
        self._save_now()
        self.register_hotkeys()

    def _global_combos(self) -> list[str]:
        """Combos the app-wide actions, the push-to-talk key and category keys hold."""
        return ([getattr(self.cfg, a) for a, *_ in HOTKEY_ACTIONS if getattr(self.cfg, a)]
                + [c for c in (self.cfg.ptt_key, *self.cfg.category_hotkeys.values()) if c])

    def set_single_click(self, on: bool):
        """Settings -> General: one click on a pad plays it."""
        self.set_option("single_click", on)
        Pad.single_click = on

    def on_hotkey_released(self, action: str):
        """A hotkey or MIDI pad was let go: a hold-to-play sound stops, and an overlay
        in hold mode opened by a MIDI pad closes (a key's release it watches itself)."""
        m = self._meta.get(action)
        if action == "__voicehold__":
            if self._voice_was is not None:
                self._set_voice(self._voice_was)
                self._voice_was = None
        elif m is not None and m.hold:
            self._cancel_waiting(action)
            self.engine.stop(action)
        elif (action == "__overlay__" and self.overlay.s.mode == "hold"
              and midi.is_midi(self.cfg.overlay_hotkey) and self.overlay.is_open):
            self.overlay.close()

    def on_midi_busy(self, busy: list[str]):
        if busy:
            self.status.setText(f"<span style='color:{theme.status('warn')}'>"
                                + html.escape(", ".join(busy))
                                + " is open in another program (a music app?), so its pads "
                                "don't work here until that program lets go of it.</span>")

    def on_replay_state(self):
        if self.replay.enabled and self.replay.error:
            self.status.setText(f"<span style='color:{theme.status('warn')}'>"
                                "Instant replay can't listen: "
                                + html.escape(self.replay.error) + "</span>")

    def save_replay(self):
        """The instant-replay hotkey: the last seconds of what you heard become a pad."""
        data = self.replay.clip()
        if len(data) < int(0.2 * SR):
            self.cue("fail")
            why = self.replay.error or (
                f"nothing has played on this PC in the last {self.replay.seconds} seconds")
            self.status.setText(f"<span style='color:{theme.status('warn')}'>"
                                f"Nothing to save: {html.escape(why)}.</span>")
            return
        self.on_clip(data, "Replay " + time.strftime("%H.%M.%S"))
        self.cue("saved")

    def on_hotkeys_failed(self, failed: list[str]):
        if failed:
            log.warning("hotkeys another program already owns: %s", failed)
            self.status.setText(f"<span style='color:{theme.status('warn')}'>"
                                "Another program is already using "
                                + ", ".join(pretty_key(c) for c in failed)
                                + " — pick a different hotkey.</span>")

    def set_global_hotkey(self, attr: str, combo: str):
        """Set one of the app-wide hotkeys (or ptt_key). A combo can only do one thing,
        so it's taken off any other action or sound that had it."""
        if combo:
            for other, *_ in HOTKEY_ACTIONS:
                if other != attr and getattr(self.cfg, other) == combo:
                    setattr(self.cfg, other, "")
            for m in self.cfg.sounds:
                if m.hotkey == combo:
                    m.hotkey = ""
                    if m.id in self.pads:
                        self.pads[m.id].update()
            self._clear_category_hotkey(combo)
            if attr != "ptt_key" and self.cfg.ptt_key == combo:
                self.cfg.ptt_key = ""
        setattr(self.cfg, attr, combo)
        self._save_now()
        self.register_hotkeys()

    QUICK_HOTKEYS = ("stop_hotkey", "pause_hotkey", "random_hotkey", "last_hotkey",
                     "mic_hotkey", "hotkeys_off_hotkey", "overlay_hotkey")

    def _fill_quick_hotkeys(self, menu: QMenu):
        """The Sounds tab's keyboard button: the common hotkeys with their keys (click
        one to set it), then a way into Settings → Hotkeys for the rest."""
        menu.clear()
        labels = {attr: label for attr, _a, label, _d in HOTKEY_ACTIONS}
        labels["ptt_key"] = "Auto push-to-talk key"
        for attr in (*self.QUICK_HOTKEYS, "ptt_key"):
            combo = getattr(self.cfg, attr)
            key = pretty_key(combo) or ("Off" if attr == "ptt_key" else "not set")
            menu.addAction(f"{labels[attr]}	{key}",
                           lambda a=attr: self._quick_set_hotkey(a))
        menu.addSeparator()
        icons.set_icon(menu.addAction("All hotkeys…", lambda: self.open_settings("hotkeys")),
                       "settings")

    def _quick_set_hotkey(self, attr: str):
        d = HotkeyDialog(self.hotkeys, self, pads=attr != "ptt_key")
        if d.exec() and d.result_combo:
            self.set_global_hotkey(attr, d.result_combo)
        else:
            self.register_hotkeys()   # the capture paused them
        free_dialog(d)

    def _current_tab_info(self) -> tuple[str, str] | None:
        page = self.tabs.currentWidget()
        return next((v for k, v in self.tab_info.items() if getattr(self, k, None) is page),
                    None)

    def _show_tab_info(self):
        info = self._current_tab_info()
        if info:
            QMessageBox.information(self, info[0], info[1])

    def open_settings(self, page: str = "privacy"):
        dlg = SettingsDialog(self, page)
        dlg.exec()
        free_dialog(dlg)
        self.register_hotkeys()   # in case a capture was cancelled

    def apply_theme(self, name: str):
        self.cfg.theme = theme.apply(QApplication.instance(), name)
        icons.retheme()
        self.radio.retheme()
        self.apps.retheme()
        self.triggers.retheme()
        pp, self._pp_icon = self._pp_icon, None
        self._set_pp_icon(pp or "play")
        self.pill.setText("")   # forces _update_flow to repaint its icon
        self._update_status()   # the hints and flow, in this theme's status colours
        self._paint_logo()
        self._save_later()

    def _paint_logo(self):
        self.logo.update()   # it reads the theme colours itself
        # title bar + taskbar follow the theme too, and so do the taskbar's right-click
        # menu, a pin and the app's own Desktop / Start menu shortcuts (shellicon)
        self._icon_step = -1
        self._glow_icons(0.0, time.monotonic(), force=True)
        shellicon.follow_theme(self, theme.T["accent"], theme.T["accent2"])
        shellicon.paint_background(self, theme.T["bg"])   # fast resizes: no white edge

    def _glow_icons(self, level: float, now: float, force: bool = False):
        """The title bar / taskbar and tray icons glow warm with whatever is playing,
        like the header logo: a few steps of glow, swapped only when the step changes
        (at most every ICON_GLOW_MS), back to the plain icon when it goes quiet."""
        step = min(GLOW_STEPS, round(min(1.0, level * 1.4) * GLOW_STEPS))
        if not force and (step == self._icon_step or now < self._icon_next):
            return
        self._icon_step, self._icon_next = step, now + ICON_GLOW_MS / 1000
        amount = step / GLOW_STEPS
        icon = glow_icon(theme.T["accent"], theme.T["accent2"], amount)
        QApplication.setWindowIcon(icon)
        tray = getattr(self, "tray", None)
        if tray is not None:   # the tray icon follows the theme too
            tray.setIcon(icon)

    def on_hotkey(self, action):
        if action == "__hotkeys__":
            self.toggle_hotkeys()
            return
        if self._hotkeys_off:   # one already on its way when they were turned off
            return
        if self.overlay.handle(action):
            return
        if action == "__stop__":
            self.stop_all()
        elif action == "__last__":
            if self._last_sid is None or self.meta(self._last_sid) is None:
                self.cue("fail")
            else:
                self.play(self._last_sid)
        elif action in ("__nextcat__", "__prevcat__"):
            self.step_category(1 if action == "__nextcat__" else -1)
        elif action in ("__volup__", "__voldown__"):
            self.step_sound_volume(1 if action == "__volup__" else -1)
        elif action == "__mic__":
            self.chk_mic.setChecked(not self.chk_mic.isChecked())   # -> on_mic_toggle
            self.cue("start" if self.cfg.mic_enabled else "stop")
        elif action == "__voice__":
            on = not self.voice.fx.btn_power.isChecked()
            self._voice_was = None
            self._set_voice(on)
            self.cue("start" if on else "stop")
        elif action == "__voicehold__":
            if self._voice_was is None:
                self._voice_was = self.voice.fx.btn_power.isChecked()
            self._set_voice(True)
        elif action == "__replay__":
            self.save_replay()
        elif action == "__pause__":
            self.engine.pause_all()
        elif action == "__random__":
            self.play_random()
        elif action.startswith(RANDOM):
            self.play_random(action[len(RANDOM):])
        else:
            self.play(action)

    def _set_voice(self, on: bool):
        """The voice changer's big ON / OFF switch, from a hotkey."""
        if self.voice.fx.btn_power.isChecked() != on:
            self.voice.fx.btn_power.setChecked(on)   # its toggled handler applies it

    def toggle_hotkeys(self):
        """All hotkeys off (they type normally again), or back on. Not saved: the app
        always opens with them on."""
        self._hotkeys_off = not self._hotkeys_off
        if self._hotkeys_off and self._voice_was is not None:   # a held voice key
            self._set_voice(self._voice_was)
            self._voice_was = None
        self.register_hotkeys()
        self.cue("stop" if self._hotkeys_off else "start")
        key = pretty_key(self.cfg.hotkeys_off_hotkey)
        self.status.setText(
            f"<span style='color:{theme.status('warn')}'>Hotkeys are off — "
            f"{html.escape(key)} turns them back on.</span>" if self._hotkeys_off
            else "Hotkeys are on again.")

    def step_category(self, step: int):
        """Next / previous category (with All at the front), with a beep for each
        place along it, so you can tell where you are without looking."""
        names = ["", *self.cfg.categories]
        if len(names) < 2:
            self.cue("fail")
            return
        i = names.index(self.cfg.category) if self.cfg.category in names else 0
        name = names[(i + step) % len(names)]
        self.set_category(name)
        n = names.index(name)
        # All: one low beep; the 1st category one high beep, the 2nd two... (up to 5)
        self.cue((523,) if n == 0 else ((784, 0) * min(n, 5))[:-1])
        self.status.setText(f"Category: {html.escape(name or 'All')}")

    def step_sound_volume(self, step: int):
        """The louder / quieter hotkeys: the sounds' volume box by 10 % a press."""
        pct = self.vol_sound.spin.value()
        new = min(max((round(pct / 10) + step) * 10, 0), self.vol_sound.spin.maximum())
        self.vol_sound.spin.setValue(new)   # -> set_option("sound_vol")
        self.cue((880, 1175) if step > 0 else (880, 659))
        self.status.setText(f"Sounds: {new}%")

    def play_random(self, category: str | None = None) -> str | None:
        """Play a random loaded sound from `category` (None = the one showing, "" = all
        of them): each comes up once before any repeats. Returns its id."""
        cat = self.cfg.category if category is None else category
        if cat and cat not in self.cfg.categories:
            return None
        pool = [m.id for m in self.cfg.sounds
                if (not cat or cat in m.tags) and m.id in self.audio]
        sid = self.shuffle.next(cat, pool)
        if sid is None:
            self.cue("fail")
            self.toast(f"No sounds in “{html.escape(cat)}” to play yet" if cat
                       else "No sounds to play yet", "warn")
            return None
        self.play(sid)
        return sid

    CUES = {"start": (660, 990), "stop": (990, 660), "saved": (880, 880, 1320), "fail": (330, 247)}

    def cue(self, kind: str | tuple):
        """A short beep in the headphones only (others never hear it), so a hotkey pressed
        in-game is confirmed without looking at the app. `kind` is a CUES name or the
        notes themselves (Hz; 0 = a gap)."""
        if not self.cfg.cue_sounds or self.engine.mon_stream is None:
            return
        notes, n = self.CUES[kind] if isinstance(kind, str) else kind, int(0.075 * SR)
        t = np.arange(n) / SR
        env = np.minimum(1.0, np.minimum(t, t[::-1]) / 0.008)   # 8 ms fade in/out
        tone = np.concatenate([np.sin(2 * np.pi * f * t) * env for f in notes]) * 0.18
        self.engine.play("__cue__", np.stack([tone, tone], 1).astype(np.float32), 1.0,
                         mode="restart", preview=True)

    def set_sending(self, on: bool):
        """The header's master switch: Live (others hear your mic and whatever is live)
        or Muted (they hear nothing at all). Everything keeps playing for you. Not
        saved: the app always opens live, so nobody's left wondering why they're silent."""
        self.engine.sending = on
        if self.btn_air.isChecked() != on:
            self.btn_air.setChecked(on)   # comes back here
            return
        text = (("Live — others hear you", "Live", "") if on else
                ("Muted — others hear nothing", "Muted", ""))[self._air_size]
        self.btn_air.setText(text)
        self.btn_air.setToolTip(
            "Click to mute: nothing at all goes out to Discord / the game (you still hear "
            "everything)" if on else "Click to go live again: others hear you and your sounds")
        if hasattr(self, "mini_air"):
            self.mini_air.setChecked(on)
            self.mini_air.setToolTip(self.btn_air.toolTip())

    def _shorten_air(self, size: int) -> Callable[[bool], None]:
        def apply(compact: bool):
            size_now = max(self._air_size, size) if compact else min(self._air_size, size - 1)
            if size_now != self._air_size:
                self._air_size = size_now
                self.set_sending(self.btn_air.isChecked())
                responsive.touch(self.btn_air)
        return apply

    def stop_all(self):
        self._queue.clear()
        self._say_queue()
        for sid in list(self._waiting):
            self._cancel_waiting(sid)
        self.engine.stop_all()
        self.radio.stop()
        self.apps.stop_all()
        self.triggers.cancel_pending()

    def _nudge_triggers(self, index: int):
        """Triggers were being watched before they moved into the Onion Watch add-on,
        which isn't installed: tint the tab and say so once, until the tab is opened."""
        icons.set_tab_icon(self.tabs, index, "triggers", "warn_text")
        QTimer.singleShot(0, self, lambda: self.status.setText(
            f"<span style='color:{theme.status('warn')}'>Your screen triggers now come from "
            "the free Onion Watch add-on: open the Triggers tab to get it.</span>"))

        def seen(i: int):
            if self.tabs.widget(i) is self.triggers:
                self.tabs.currentChanged.disconnect(seen)
                self.triggers.nudged()
                icons.set_tab_icon(self.tabs, index, "triggers")
        if self.tabs.currentWidget() is self.triggers:
            self.triggers.nudged()
            icons.set_tab_icon(self.tabs, index, "triggers")
        else:
            self.tabs.currentChanged.connect(seen)

    # ------------------------------------------------------------------ sounds
    def _index(self):
        """Rebuild the id -> meta lookup (call after any change to cfg.sounds)."""
        self._meta = {m.id: m for m in self.cfg.sounds}

    def meta(self, sid) -> SoundMeta | None:
        if sid == LINK_ID:
            return self._link_meta
        return self._meta.get(sid)

    def on_link_played(self, title: str, data, gain: float):
        """The link bar's Play once: show it in the transport bar like a pad, so it
        can be paused, stopped and seeked. It isn't a sound in the library."""
        self._link_meta = SoundMeta(id=LINK_ID, name=title, file="", level_gain=gain,
                                    duration=len(data) / SR)
        self.audio[LINK_ID] = data
        if self.current == LINK_ID:
            self.current = None   # a new link: refresh the name
        self.select(LINK_ID)

    def search_youtube(self):
        """Enter / the Search button: search the site the results header has
        picked (ytdl.SOURCES) for the search box's text (a pasted link is the
        link bar's instead)."""
        text = self.search.text()
        if ytdl.as_link(text) or not self.ytresults.available():
            return
        if not self.ytresults.search(text):
            if not text.strip():
                self.search.setFocus()
                busy.flash(self.btn_yt, "Type something first")
            return
        self._pads_scroll.hide()
        self._cat_row.hide()

    def on_search_enter(self):
        if ytdl.as_link(self.search.text()):
            self.linkbar.add()
        else:
            self.search_youtube()

    def _from_youtube(self, r, play: bool):
        kind = "play" if play else "add"
        self.linkbar.open(r.url, r.title, r.seconds)
        self.ytresults.mark(r.url, kind)   # its button greys out until the link bar's done
        if not (self.linkbar.play_once() if play else self.linkbar.add()):
            self.ytresults.mark(r.url, kind, False)

    def gain_for(self, m: SoundMeta, volume=None) -> float:
        v = m.volume if volume is None else volume
        return v * (m.level_gain if self.cfg.level_volumes else 1.0)

    def play(self, sid, now: bool = False):
        """Play a pad's sound as its settings say: its cooldown, a Queue sound waiting
        for the ones playing, its wait before playing. now=True skips all of that (the
        queue and a delayed start, whose press was already checked)."""
        m = self.meta(sid)
        data = self.audio.get(sid)
        if m is None:
            return
        if not now and data is not None:
            t = time.monotonic()
            if t < self._cool.get(sid, 0.0):
                return   # in its cooldown: a spammed key does nothing
            if m.cooldown:
                self._cool[sid] = t + m.delay + m.cooldown
            if m.mode == "queue" and (self._pads_playing() or self._queue):
                self.queue_sound(sid)
                return
            if m.delay > 0:
                timer = QTimer(self)
                timer.setSingleShot(True)
                timer.timeout.connect(lambda s=sid, tm=timer: self._waited(s, tm))
                self._waiting.setdefault(sid, []).append(timer)
                timer.start(int(m.delay * 1000))
                self.select(sid)
                return
        if data is None:   # say why nothing happens instead of silently ignoring the press
            p = self.pads.get(sid)
            if p is not None and p.state == "error":
                why = f": {html.escape(p.error)}" if p.error else ""
                name = html.escape(m.name)
                self.status.setText(f"<span style='color:{theme.status('error')}'>"
                                    f"Can't play “{name}”{why}. "
                                    "If the file was moved or deleted, remove the pad and "
                                    "add the sound again.</span>")
            else:
                self.status.setText(f"“{html.escape(m.name)}” is still loading…")
            return
        self.select(sid)
        self._last_sid = sid
        v = self.engine.play(sid, data, self.gain_for(m), loop=m.loop,
                             mode="restart" if m.mode == "queue" else m.mode,
                             fade_in=m.fade_in, fade_out=m.fade_out,
                             only=("main", "obs") if m.only_them else None)
        if v is None and not self.engine.active_outputs():
            self.status.setText(f"<span style='color:{theme.status('warn')}'>"
                                "No audio device is open — pick one "
                                "in Setup.</span>")

    def _waited(self, sid: str, timer: QTimer):
        """A sound's wait before playing is over."""
        timers = self._waiting.get(sid, [])
        if timer in timers:
            timers.remove(timer)
            if not timers:
                del self._waiting[sid]
            self.play(sid, now=True)
        timer.deleteLater()

    def _cancel_waiting(self, sid: str):
        for timer in self._waiting.pop(sid, []):
            timer.stop()
            timer.deleteLater()

    def _pads_playing(self) -> bool:
        """Is one of the board's sounds playing (not a preview, cue or the radio)?"""
        return any(sid in self._meta and not paused
                   for sid, (_p, paused) in self.engine.playing().items())

    def queue_sound(self, sid: str):
        """Play `sid` once the board's sounds playing now have finished (now, if none are)."""
        if not self._pads_playing() and not self._queue:
            self.play(sid, now=True)
            return
        self._queue.append(sid)
        self._say_queue()

    def queue_category(self, name: str, shuffled: bool):
        """Play every sound in category `name`, one after another."""
        sids = [m.id for m in self.cfg.sounds if name in m.tags and m.id in self.audio]
        if not sids:
            self.cue("fail")
            self.toast(f"No sounds in “{html.escape(name)}” to play yet", "warn")
            return
        if shuffled:
            self.shuffle.rng.shuffle(sids)
        self._queue = sids
        for sid in self.engine.playing():   # the board's sounds make way (not the radio)
            if sid in self._meta:
                self.engine.stop(sid)
        self._next_in_queue()

    def _next_in_queue(self):
        while self._queue:
            sid = self._queue.pop(0)
            if self.meta(sid) is not None and sid in self.audio:
                self.play(sid, now=True)
                self._say_queue()
                return

    def _say_queue(self):
        if self._queue:
            m = self.meta(self._queue[0])
            more = f" (+{len(self._queue) - 1} more)" if len(self._queue) > 1 else ""
            self.status.setText(f"Up next: “{html.escape(m.name if m else '?')}”{more} · "
                                "Stop everything clears the queue")
        elif self.status.text().startswith("Up next:"):   # the queue ran out / was cleared
            self._update_status()

    def select(self, sid):
        if self.current != sid:
            if self.current in self.pads:
                self.pads[self.current].selected = False
                self.pads[self.current].update()
            self.current = sid
            self.start_frac = 0.0
            if sid in self.pads:
                self.pads[sid].selected = True
                self.pads[sid].update()
            m = self.meta(sid)
            self._set_np_name(m.name if m else "")

    def toggle_play_pause(self):
        sid = self.current
        if not sid:
            return
        st = self.engine.state(sid)
        if st:
            self.engine.set_paused(sid, not st[1])
            return
        m, data = self.meta(sid), self.audio.get(sid)
        if m and data is not None:
            frac = 0.0 if self.start_frac >= 0.995 else self.start_frac
            self.engine.play(sid, data, self.gain_for(m), loop=m.loop, mode="restart", start=frac,
                             fade_in=m.fade_in if frac == 0 else 0.0, fade_out=m.fade_out)

    def stop_current(self):
        if self.current:
            self.engine.stop(self.current)
        self.start_frac = 0.0

    def _seek_preview(self, v):
        if self._seeking:
            m = self.meta(self.current) if self.current else None
            if m:
                self.np_time.setText(fmt_pos(v / 1000 * m.duration, m.duration))
                self.mini_time.setText(self.np_time.text())

    def do_seek(self, slider=None):
        self._seeking = False
        if not self.current:
            return
        frac = (slider or self.seek).value() / 1000
        if not self.engine.seek(self.current, frac):
            self.start_frac = frac   # not playing: ▶ will start from here

    def preview(self, sid, volume=None, fx=None, fades=None, done=None) -> str:
        """Play a sound to your headphones only. With `fx` (the Edit dialog's unsaved
        effects) it's rendered with those first, in the background; `fades` is the
        dialog's unsaved (fade in, fade out). Returns "playing", "rendering" (then
        `done(ok)` is called when it plays or fails) or "missing" (not loaded)."""
        m = self.meta(sid)
        data = self.audio.get(sid)
        if not m or data is None:
            return "missing"
        gain = self.gain_for(m, volume)
        fade_in, fade_out = fades if fades is not None else (m.fade_in, m.fade_out)
        self._preview_fades = {"fade_in": fade_in, "fade_out": fade_out}
        if fx is None or soundfx.key(fx) == soundfx.key(m.fx):
            self.engine.play(sid + ":preview", data, gain, mode="restart", preview=True,
                             **self._preview_fades)
            return "playing"
        self._preview_gen += 1
        gen = self._preview_gen
        self._preview_done = done
        self.status.setText("Rendering the preview…")

        def run():
            try:
                out = soundfx.render(load_original(m), fx)
            except Exception:  # noqa: BLE001
                log.exception("effects preview failed")
                out = None
            if gen == self._preview_gen:
                self.bridge.preview.emit(sid, out, gain)
        threading.Thread(target=run, daemon=True, name="fx-preview").start()
        return "rendering"

    def _on_fx_preview(self, sid, data, gain):
        self._update_status()
        done, self._preview_done = getattr(self, "_preview_done", None), None
        if done is not None:
            done(data is not None)
        if data is None:
            self.status.setText(f"<span style='color:{theme.status('warn')}'>"
                                "Couldn't render the preview "
                                "(see the log).</span>")
            self.toast("Couldn't render the preview with these effects (see the log).", "warn")
            return
        # its own id: it mustn't share the pad's resample cache or its preview voice
        self.engine.play(sid + "~fx:preview", data, gain, mode="restart", preview=True,
                         **getattr(self, "_preview_fades", {}))

    def on_live_speed(self, speed: float, pitch: float, keep: bool):
        e = self.engine
        e.sound_speed, e.sound_pitch, e.sound_keep_pitch = speed, pitch, keep

    def _rebuild_pads(self):
        """Sync the pad widgets with cfg.sounds: keep the ones that still exist, create
        the new ones, drop the removed ones."""
        self._index()
        if getattr(self, "triggers", None) is not None:   # not built yet on the first call
            self.triggers.sounds_changed()
        keep = {m.id for m in self.cfg.sounds}
        for sid in [s for s in self.pads if s not in keep]:
            p = self.pads.pop(sid)
            p.setParent(None)
            p.deleteLater()
        ordered = []
        for m in self.cfg.sounds:
            p = self.pads.get(m.id)
            if p is None:
                p = Pad(m, self.cfg.pad_width)
                p.activated.connect(self.play)
                p.chosen.connect(self.select)
                p.pick.connect(self.selection.on_pick)
                p.step.connect(self.grid.focus_step)
                p.menu.connect(self.pad_menu)
                self.pads[m.id] = p
            p.state = "ready" if m.id in self.audio else p.state
            p.selected = m.id == self.current
            ordered.append(p)
        self.grid.set_pads(ordered)
        self.apply_filter(self.search.text())
        self._update_status()

    def _results_closed(self):
        """"My sounds": all of them. The search box also filters the pads, so the web
        search still in it left a board of only the pads matching "cat meow" (often
        none, with nothing saying why). Something else typed in it since stays."""
        query = " ".join(self.ytresults.query.split())
        if query and " ".join(self.search.text().split()) == query:
            self.search.clear()

    def apply_filter(self, text):
        """Show the pads that match the search box (name or category) and are in the
        category picked above the pads."""
        self.linkbar.set_text(text)
        # a link filters nothing, and nor does the box in the mini player, which hides
        # it: a web search's words left there showed a blank mini player
        t = "" if self.linkbar.url or self.is_mini() else text.strip().lower()
        cat = self.cfg.category
        for m in self.cfg.sounds:
            p = self.pads.get(m.id)
            if p:
                hit = not t or t in m.name.lower() or any(t in g.lower() for g in m.tags)
                p.setProperty("filtered", not hit or bool(cat and cat not in m.tags))
        self.grid.relayout(force=True)
        self.selection.sync()

    # ------------------------------------------------------------------ categories
    # A sound can be in any number of categories (SoundMeta.tags); the bar above the
    # pads shows one at a time. The overlay shows the same category's sounds.
    def _build_categories(self) -> QWidget:
        # two layers: the window's fit hides the outer one when it's short, while web
        # results showing in the pads' place hide the inner row (its tabs pick pads)
        outer = QWidget()
        ov = QVBoxLayout(outer)
        ov.setContentsMargins(0, 0, 0, 0)
        w = self._cat_row = QWidget()
        ov.addWidget(w)
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        self.cat_tabs = QTabBar()
        self.cat_tabs.setDrawBase(False)
        self.cat_tabs.setExpanding(False)
        self.cat_tabs.setUsesScrollButtons(True)
        self.cat_tabs.setMovable(True)
        self.cat_tabs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.cat_tabs.customContextMenuRequested.connect(self._category_menu)
        self.cat_tabs.currentChanged.connect(self._on_category_tab)
        self.cat_tabs.tabMoved.connect(self._on_category_moved)
        h.addWidget(self.cat_tabs)
        # "+" right after the last tab, like a browser's new-tab button
        add = QPushButton()
        add.setObjectName("small")
        add.setAccessibleName("New category")
        add.setToolTip("New category (a page of pads). Right-click a pad to put it in "
                       "one; right-click a category to rename or delete it.")
        icons.set_icon(add, "plus", size=12)
        add.clicked.connect(lambda: self.new_category())
        h.addWidget(add, 0, Qt.AlignVCenter)
        h.addStretch(1)
        self.btn_cat_add = add
        self._fill_categories()
        return outer

    def _fill_categories(self):
        tb = self.cat_tabs
        tb.blockSignals(True)
        while tb.count():
            tb.removeTab(0)
        tb.addTab(ALL)
        tb.setTabToolTip(0, "Every sound")
        for c in self.cfg.categories:
            n = sum(1 for m in self.cfg.sounds if c in m.tags)
            i = tb.addTab(c.replace("&", "&&"))   # a lone & would be a shortcut key
            tb.setTabData(i, c)                   # the real name; All's data stays None
            hk = self.cfg.category_hotkeys.get(c)
            tb.setTabToolTip(i, f"{n} sound{'s' if n != 1 else ''}"
                             + (f" · {pretty_key(hk)} plays a random one" if hk else "")
                             + " · right-click to rename, delete or give it a "
                               "random-sound hotkey · drag to reorder")
        cat = self.cfg.category
        tb.setCurrentIndex(self.cfg.categories.index(cat) + 1 if cat in self.cfg.categories
                           else 0)
        tb.blockSignals(False)

    def _on_category_tab(self, i: int):
        self.set_category(self.cfg.categories[i - 1] if 1 <= i <= len(self.cfg.categories)
                          else "")

    def _on_category_moved(self, _frm: int, _to: int):
        if self.cat_tabs.tabData(0) is not None:   # All was dragged away from the front
            self._fill_categories()
            return
        names = [self.cat_tabs.tabData(i) for i in range(1, self.cat_tabs.count())]
        if sorted(names) == sorted(self.cfg.categories):
            self.cfg.categories = names
            self._save_later()

    def set_category(self, name: str):
        """Show one category's pads ("" = all of them). The overlay follows."""
        name = name if name in self.cfg.categories else ""
        changed = name != self.cfg.category
        self.cfg.category = name
        want = self.cfg.categories.index(name) + 1 if name else 0
        if self.cat_tabs.currentIndex() != want:
            self.cat_tabs.blockSignals(True)
            self.cat_tabs.setCurrentIndex(want)
            self.cat_tabs.blockSignals(False)
        if changed:
            self.overlay.page = 0
            self.apply_filter(self.search.text())
            self._save_later()
            if self.cfg.scoped_hotkeys:   # this category's set of sound hotkeys
                self.register_hotkeys()

    def category_sounds(self) -> list[SoundMeta]:
        cat = self.cfg.category
        return [m for m in self.cfg.sounds if not cat or cat in m.tags]

    def new_category(self, sid: str | None = None, name: str | None = None) -> str:
        """Add a category (asking for its name unless given), with `sid`'s sound in it
        when made from a pad's menu. Returns the name, or "" if cancelled."""
        if name is None:
            name, ok = QInputDialog.getText(self, "New category",
                                            "Name (e.g. Memes, Music, Game 1):")
            name = name if ok else ""
        name = (clean_tags([name]) or [""])[0]
        if name.lower() == ALL.lower():   # would look like the built-in tab
            self.toast(f"“{ALL}” is the built-in tab — pick another name", "warn")
            return ""
        if not name:
            return ""
        name = {c.lower(): c for c in self.cfg.categories}.get(name.lower(), name)
        if name not in self.cfg.categories:
            self.cfg.categories.append(name)
        m = self.meta(sid) if sid else None
        if m and name not in m.tags:
            m.tags.append(name)
        self._save_now()
        self._fill_categories()
        if not sid:
            self.set_category(name)
        self.apply_filter(self.search.text())
        return name

    def toggle_tag(self, sid: str, name: str):
        m = self.meta(sid)
        if not m or name not in self.cfg.categories:
            return
        if name in m.tags:
            m.tags.remove(name)
            msg = f"Took “{html.escape(m.name)}” out of {html.escape(name)}"
        else:
            m.tags.append(name)
            msg = f"✓ Added “{html.escape(m.name)}” to {html.escape(name)}"
        self._save_now()
        self._fill_categories()
        self.apply_filter(self.search.text())
        self.toast(msg)

    def rename_category(self, old: str, new: str | None = None):
        if new is None:
            new, ok = QInputDialog.getText(self, "Rename category", "New name:", text=old)
            new = new if ok else ""
        new = (clean_tags([new]) or [""])[0]
        if new.lower() == ALL.lower():
            self.toast(f"“{ALL}” is the built-in tab — pick another name", "warn")
            return
        if not new or new == old or old not in self.cfg.categories:
            return
        if new.lower() in {c.lower() for c in self.cfg.categories if c != old}:
            QMessageBox.information(self, "Rename category", f"There's already a “{new}”.")
            return
        self.cfg.categories[self.cfg.categories.index(old)] = new
        if old in self.cfg.category_hotkeys:
            self.cfg.category_hotkeys[new] = self.cfg.category_hotkeys.pop(old)
        self.shuffle.forget(old)
        for m in self._live_metas():   # removed ones too, or Undo brings `old` back
            m.tags = [new if t == old else t for t in m.tags]
        if self.cfg.category == old:
            self.cfg.category = new
        self._save_now()
        self._fill_categories()
        self.register_hotkeys()   # its random-sound hotkey now plays `new`
        self.toast(f"✓ Renamed to “{html.escape(new)}”", "ok")

    def delete_category(self, name: str):
        """Delete a category. Its sounds stay (in All and their other categories)."""
        if name not in self.cfg.categories:
            return
        n = sum(name in m.tags for m in self.cfg.sounds)
        if n and QMessageBox.question(
                self, "Delete category",
                f"Delete the “{name}” category? Its {n} sound{'s' if n != 1 else ''} "
                "stay in All (and any other categories they're in).") != QMessageBox.Yes:
            return
        self.cfg.categories.remove(name)
        self.cfg.category_hotkeys.pop(name, None)
        self.shuffle.forget(name)
        for m in self._live_metas():   # removed ones too, or Undo brings it back
            if name in m.tags:
                m.tags.remove(name)
        if self.cfg.category == name:
            self.cfg.category = ""
        self._save_now()
        self._fill_categories()
        self.apply_filter(self.search.text())
        self.register_hotkeys()   # let go of its random-sound hotkey

    def _category_menu(self, pos):
        i = self.cat_tabs.tabAt(pos)
        if i < 1:
            return
        name = self.cat_tabs.tabData(i)
        menu = QMenu(self)
        a_ren = menu.addAction(icons.icon("edit"), "Rename…")
        hk = self.cfg.category_hotkeys.get(name, "")
        a_hk = menu.addAction(icons.icon("keyboard"),
                              f"Random-sound hotkey: {pretty_key(hk)} (change…)" if hk
                              else "Set a random-sound hotkey…")
        a_nohk = menu.addAction("Clear the random-sound hotkey") if hk else None
        a_rand = menu.addAction(icons.icon("play"), "Play a random sound from it")
        a_all = menu.addAction(icons.icon("next"), "Play them all, in order")
        a_shuf = menu.addAction(icons.icon("next"), "Play them all, shuffled")
        a_exp = menu.addAction(icons.icon("folder"), "Export as a sound pack…")
        menu.addSeparator()
        a_del = menu.addAction(icons.icon("trash", "danger_text"),
                               "Delete category (keeps the sounds)")
        act = menu.exec(self.cat_tabs.mapToGlobal(pos))
        if act is None:
            return
        if act == a_ren:
            self.rename_category(name)
        elif act == a_hk:
            self.set_category_hotkey(name)
        elif act is not None and act == a_nohk:
            self.set_category_hotkey(name, "")
        elif act == a_rand:
            self.play_random(name)
        elif act in (a_all, a_shuf):
            self.queue_category(name, shuffled=act == a_shuf)
        elif act == a_exp:
            self.export_sounds([m for m in self.cfg.sounds if name in m.tags], name)
        elif act == a_del:
            self.delete_category(name)

    def _tag_new(self, meta: SoundMeta):
        """A sound added while a category is showing goes into it (so it doesn't seem
        to vanish)."""
        if self.cfg.category and self.cfg.category not in meta.tags:
            meta.tags.append(self.cfg.category)

    def _load_all(self):
        todo = [m for m in self.cfg.sounds if m.id not in self.audio]

        def run():
            t0 = time.monotonic()
            for m in todo:
                try:
                    data = load_sound(m)   # from the cache after the first run
                    self.engine.prepare(m.id, data)
                    self.bridge.loaded.emit(m.id, data, "")
                except Exception as e:  # noqa: BLE001
                    log.warning("can't load %s: %s", m.file, e)
                    self.bridge.loaded.emit(m.id, None, errors.plain(e))
            live = self._live_metas()   # as of now, not of the start
            prune_cache(cache_keep(live))
            thumbs.prune({m.image for m in live if m.image})
            trash.prune()   # what's been in Recently deleted for too long
            log.info("loaded %d sounds in %.1fs", len(todo), time.monotonic() - t0)
        self._load_thread = threading.Thread(target=run, daemon=True, name="load")
        self._load_thread.start()

    def on_loaded(self, sid, data, err):
        # removed while it was loading (the index can lag behind cfg.sounds: check both)
        if (sid != LINK_ID and sid not in self._meta
                and all(m.id != sid for m in self.cfg.sounds)):
            for i, (m, index, _d) in enumerate(self._removed):
                if m.id == sid:   # still undo-able: keep the audio with it
                    self._removed[i] = (m, index, data)
                    return
            self.engine.forget(sid)   # gone for good: don't keep its audio around
            return
        p = self.pads.get(sid)
        if data is not None:
            self.audio[sid] = data
            m = self.meta(sid)
            if m and abs(m.duration - len(data) / SR) > 0.005:   # effects change the length
                m.duration = len(data) / SR
                self._save_later()
            if m and not m.fingerprint:   # sounds imported before fingerprints existed
                m.fingerprint = fingerprint(m.file)
                self._save_later()
        if p:
            p.state = "ready" if data is not None else "error"
            p.error = err
            p.update()

    def _live_metas(self) -> list[SoundMeta]:
        """Every sound whose files must be kept: the library, and removed ones that
        can still be undone."""
        return list(self.cfg.sounds) + [m for m, _i, _d in list(self._removed)]

    def open_sounds_folder(self):
        try:
            library.SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
            opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(library.SOUNDS_DIR)))
        except OSError as e:
            log.warning("can't make the sounds folder: %s", e)
            opened = False
        if opened:
            self.toast("Opened your sounds folder")
        else:
            self.toast("Couldn't open the sounds folder: "
                       f"{html.escape(str(library.SOUNDS_DIR))}", "warn")

    def _watch_sounds_folder(self):
        """Sound files dragged into the sounds folder in Explorer join the board,
        even ones put there while the app was closed."""
        self._loose_sizes: dict[Path, tuple[int, int]] = {}
        self._loose_taken: set[Path] = set()   # imported or failed: not tried again
        self._loose_timer = QTimer(self)
        self._loose_timer.setSingleShot(True)
        self._loose_timer.setInterval(LOOSE_WAIT_MS)
        self._loose_timer.timeout.connect(self._take_loose)
        try:
            library.SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        self._folder_watch = QFileSystemWatcher([str(library.SOUNDS_DIR)], self)
        self._folder_watch.directoryChanged.connect(lambda _p: self._loose_timer.start())
        self._loose_timer.start()

    def _take_loose(self):
        """Import the sounds folder's loose files once they're done copying in (the
        same size on two looks in a row)."""
        seen, ready = {}, []
        for p in loose_sounds(self.cfg):
            if p in self._loose_taken:
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            sig = (st.st_size, st.st_mtime_ns)
            if st.st_size and self._loose_sizes.get(p) == sig:
                ready.append(p)
            else:
                seen[p] = sig
        self._loose_sizes = seen
        if seen:
            self._loose_timer.start()   # still copying: look again
        if ready:
            self._loose_taken.update(ready)
            log.info("adding %d sound(s) put in the sounds folder", len(ready))
            self.import_files([str(p) for p in ready])

    def add_dialog(self):
        exts = " ".join(f"*{e}" for e in sorted(AUDIO_EXTS))
        files, _ = QFileDialog.getOpenFileNames(
            self, "Add sounds", str(Path.home()),
            f"Sounds and zips ({exts} *.zip);;Audio ({exts});;Zip of sounds, backup or "
            "sound pack (*.zip);;All files (*)")
        if files:
            self.import_files(files)

    def import_files(self, files):
        files = [f for f in files if f]
        zips = {}   # a plain zip of sound files: unpacked, then imported like the rest
        # a backup / sound pack (a .zip, or a folder with its JSON) is unpacked instead
        for f in [f for f in files if self._is_package(f)]:
            files.remove(f)
            names = backup.loose_audio(f)
            if names:
                zips[f] = names
            else:
                self.import_package(f)
        count = len(files) + sum(len(n) for n in zips.values())
        if not count:
            return
        self._pending_imports += count
        start = len(self.cfg.sounds)
        known = {m.fingerprint: m.name for m in self.cfg.sounds if m.fingerprint}

        def run():
            with tempfile.TemporaryDirectory(prefix="onionboard-zip-") as tmp:
                todo = list(files)
                for k, (z, names) in enumerate(zips.items()):
                    try:
                        res = backup.extract_loose(z, names, Path(tmp) / str(k))
                    except Exception as e:  # noqa: BLE001 - too big, no room, damaged
                        log.warning("can't unpack %s: %s", z, e)
                        # one message for the zip; the rest only count down
                        self.bridge.imported.emit(None, None, f"{Path(z).name}: {errors.plain(e)}")
                        for _ in names[1:]:
                            self.bridge.imported.emit(None, None, "")
                        continue
                    for _n, dest, err in res:
                        if dest is None:
                            self.bridge.imported.emit(None, None,
                                                      f"{Path(z).name} → {errors.plain(err)}")
                        else:
                            todo.append(str(dest))
                import_all(todo)

        def import_all(files):
            for i, f in enumerate(files):
                try:
                    fp = fingerprint(f)
                    if fp and fp in known:
                        raise RuntimeError(f"already in your library as “{known[fp]}”")
                    meta, data = import_file(f, PAD_COLORS[(start + i) % len(PAD_COLORS)])
                    meta.image = thumbs.extract_art(f, meta.id)   # cover art / first frame
                    if fp:
                        known[fp] = meta.name   # the same file twice in one drop
                    self.engine.prepare(meta.id, data)
                    if Path(f).parent == library.SOUNDS_DIR and Path(meta.file) != Path(f):
                        Path(f).unlink(missing_ok=True)   # dragged into the folder: now
                    self.bridge.imported.emit(meta, data, "")   # it's in there as ours
                except Exception as e:  # noqa: BLE001
                    log.warning("can't import %s: %s", f, e)
                    self.bridge.imported.emit(None, None, f"{Path(f).name}: {errors.plain(e)}")
        threading.Thread(target=run, daemon=True, name="import").start()
        self.status.setText(f"Importing {count} file(s)…")
        busy.set_busy(self.btn_add, True)   # back in on_imported, when they're all in
        self.toast(f"Adding {count} sound{'s' if count != 1 else ''}…")

    def on_imported(self, meta, data, err):
        self._pending_imports -= 1
        if meta is not None:
            self._tag_new(meta)
            self.cfg.sounds.append(meta)
            self._index()
            self.audio[meta.id] = data
            self._imported_ok += 1
        elif err:
            self._import_errors.append(err)
        if self._pending_imports <= 0:
            self._pending_imports = 0
            self._save_now()
            self._rebuild_pads()
            n, self._imported_ok = self._imported_ok, 0
            busy.set_busy(self.btn_add, False)
            if n:
                self.toast(f"✓ Added {n} sound{'s' if n != 1 else ''}", "ok")
            elif not self._import_errors:
                self.toast("Nothing new to add")
            self.triggers.import_done()   # a trigger's sound that failed to import
            if self._import_errors:
                QMessageBox.warning(self, "Some files weren't added",
                                    "<br>".join(html.escape(e) for e in self._import_errors[:15]))
                self._import_errors = []

    def on_clip(self, data, name):
        """A clip recorded in the Radio or Apps tab becomes a normal sound pad."""
        try:
            meta, data = save_clip(data, name, PAD_COLORS[len(self.cfg.sounds) % len(PAD_COLORS)])
        except Exception as e:  # noqa: BLE001
            log.exception("can't save clip")
            src = self.sender()
            if src is not None and hasattr(src, "clip_error"):
                src.clip_error = errors.plain(e)   # the tab says so on its row
            else:
                errors.warn(self, "Couldn't save clip", e)
            return
        self._tag_new(meta)
        self.cfg.sounds.append(meta)
        self._index()
        self.audio[meta.id] = data
        threading.Thread(target=self.engine.prepare, args=(meta.id, data), daemon=True).start()
        self._save_now()
        self._rebuild_pads()
        self.status.setText(f"Added “{html.escape(meta.name)}” ({meta.duration:.1f}s) to Sounds — "
                            "right-click it there to rename or set a hotkey.")

    def on_downloaded(self, meta, data):
        """"Add as sound" (link bar / web search) finished: already decoded, stored and
        prepared."""
        self._tag_new(meta)
        self.cfg.sounds.append(meta)
        self._index()
        self.audio[meta.id] = data
        self._save_now()
        self._rebuild_pads()
        self.status.setText(f"Added “{html.escape(meta.name)}” ({meta.duration:.1f}s) to Sounds — "
                            "right-click it there to rename or set a hotkey.")

    def on_reorder(self, sid, target):
        m = self.meta(sid)
        if not m:
            return
        self.cfg.sounds.remove(m)
        self.cfg.sounds.insert(min(target, len(self.cfg.sounds)), m)
        self._save_now()
        self._rebuild_pads()

    def pad_menu(self, sid, pos):
        m = self.meta(sid)
        if not m:
            return
        if sid in self.selection.picked and len(self.selection.picked) > 1:
            self.selection.menu(pos)   # right-click on a picked pad: act on all of them
            return
        # short labels in three groups (play / change / share & remove); what each does
        # in more words is its tooltip
        menu = QMenu(self)
        menu.setToolTipsVisible(True)

        def add(icon, text, tip="", parent=menu):
            a = parent.addAction(icons.icon(*icon) if icon else QIcon(), text)
            a.setToolTip(tip or text)
            return a
        a_stop = add(("stop",), "Stop") if self.engine.state(sid) else None
        a_prev = add(("headphones",), "Preview", "Plays it to you alone, not into the call")
        a_next = add(("play",), "Play next", "Plays it after the sounds playing now")
        menu.addSeparator()
        a_edit = add(("edit",), "Edit…", "Name, volume, hotkey, what a press does, loop, "
                     "fades, wait first, cooldown, colour")
        a_fx = add(("wave",), "Effects…", "Speed, pitch, EQ, boost")
        a_hk_clear = None
        if m.hotkey:
            hk = menu.addMenu(icons.icon("keyboard"), f"Hotkey: {pretty_key(m.hotkey)}")
            hk.setToolTipsVisible(True)
            a_hk = add(None, "Change…", "Press a new key or combo for it", hk)
            a_hk_clear = add(None, "Remove hotkey", "", hk)
        else:
            a_hk = add(("keyboard",), "Set hotkey…", "A key or combo that plays it, even "
                       "in-game")
        cats = menu.addMenu("Categories")
        cat_acts = {}
        for c in self.cfg.categories:
            a = cats.addAction(c.replace("&", "&&"))
            a.setCheckable(True)
            a.setChecked(c in m.tags)
            cat_acts[a] = c
        if cat_acts:
            cats.addSeparator()
        a_newcat = cats.addAction(icons.icon("plus"), "New category…")
        a_nopic = None
        if m.image:
            pic = menu.addMenu(icons.icon("image"), "Picture")
            a_pic = pic.addAction("Change…")
            a_nopic = pic.addAction("Remove picture")
        else:
            a_pic = add(("image",), "Add picture…", "Shown on the pad (you can also drop a "
                        "picture on it)")
        menu.addSeparator()
        a_export = add(("folder",), "Export…", "Save it as a file to share with friends")
        a_del = add(("trash", "danger_text"), "Remove", "Goes to Recently deleted")
        act = menu.exec(pos)
        if act is None:
            return
        if act in cat_acts:
            self.toggle_tag(sid, cat_acts[act])
        elif act == a_newcat:
            self.new_category(sid)
        elif act == a_export:
            self.export_sounds([m], m.name)
        elif act == a_stop:
            self.engine.stop(sid)
        elif act == a_prev:
            self.preview(sid)
        elif act == a_next:
            self.queue_sound(sid)
        elif act == a_edit:
            self.edit(sid)
        elif act == a_fx:
            self.edit(sid, tab="effects")
        elif act == a_hk:
            self.set_sound_hotkey(sid)
        elif act is not None and act == a_hk_clear:
            self.set_sound_hotkey(sid, "")
        elif act == a_pic:
            f, _ = QFileDialog.getOpenFileName(
                self, "Pick a picture", str(Path.home()),
                "Pictures (" + " ".join(f"*{x}" for x in sorted(thumbs.IMAGE_EXTS)) + ")")
            if f:
                self.set_picture(sid, f)
        elif act is not None and act == a_nopic:
            thumbs.clear(m)
            self._save_now()
            self.pads[sid].update()
        elif act == a_del:
            self.ask_remove([sid])

    def set_picture(self, sid: str, path: str):
        """Put a picture on a pad (from the menu, or an image dropped on it)."""
        m = self.meta(sid)
        if not m:
            return
        if not thumbs.set_image(m, path):
            QMessageBox.warning(self, "Couldn't use that picture",
                                f"{Path(path).name} isn't a picture this app can read.")
            return
        self._save_now()
        self.pads[sid].update()

    def ask_remove(self, sids: list[str]) -> bool:
        """Remove from the menu / picked pads: ask first. They go to Recently deleted."""
        gone = [m for m in (self.meta(s) for s in sids) if m]
        if not gone:
            return False
        what = f"“{gone[0].name}”" if len(gone) == 1 else f"these {len(gone)} sounds"
        box = QMessageBox(QMessageBox.Question, "Remove sound" if len(gone) == 1
                          else "Remove sounds",
                          f"Remove {what}?\n\nRemoved sounds go to Recently deleted, "
                          f"where you can bring them back for {trash.KEEP_DAYS} days.",
                          QMessageBox.Yes | QMessageBox.Cancel, self)
        box.button(QMessageBox.Yes).setText("Remove")
        box.setDefaultButton(QMessageBox.Cancel)
        if box.exec() != QMessageBox.Yes:
            return False
        self.remove_sounds([m.id for m in gone])
        return True

    def remove_sound(self, sid: str):
        """Take a sound off the board. Its files stay until the Undo bar goes away
        (or the app closes); then the audio file goes to the Recycle Bin."""
        self.remove_sounds([sid])

    def remove_sounds(self, sids: list[str]):
        """Take several sounds off the board at once; one Undo brings them all back."""
        gone = [m for m in (self.meta(s) for s in sids) if m]
        if not gone:
            return
        self._finish_removals()   # only the latest removal can be undone
        for m in gone:
            self.engine.stop(m.id)
            self.engine.stop(f"{m.id}:preview")
            index = self.cfg.sounds.index(m)
            self.cfg.sounds.remove(m)
            self._removed.append((m, index, self.audio.pop(m.id, None)))
            self.engine.forget(m.id)
            if self.current == m.id:
                self.current = None
                self._set_np_name("Pick a sound")
                self.np_name.setToolTip("Select a sound pad to use these playback controls.")
        self._save_now()
        self._rebuild_pads()
        self._fill_categories()
        self.register_hotkeys()
        if len(gone) == 1:
            name = self.undo_lbl.fontMetrics().elidedText(gone[0].name, Qt.ElideRight, 260)
            self.undo_lbl.setText(f"Removed “{name}”")
        else:
            self.undo_lbl.setText(f"Removed {len(gone)} sounds")
        self.undo_bar.show()
        self._undo_timer.start(UNDO_S * 1000)

    def undo_remove(self):
        """Put the last removed sound(s) back where they were, with everything they had."""
        self._undo_timer.stop()
        self.undo_bar.hide()
        if not self._removed:
            return
        done, self._removed = self._removed, []
        self._put_back(done)

    def _put_back(self, entries: list[tuple[SoundMeta, int, np.ndarray | None]]):
        """Put removed sounds back on the board: (meta, the index it had, its audio or
        None to load it). The last one goes in first, so each lands where it was."""
        entries = list(entries)
        while entries:
            m, index, data = entries.pop()
            if any(o.id == m.id for o in self.cfg.sounds):
                continue   # already back
            if m.hotkey and self._hotkey_taken(m.hotkey):
                m.hotkey = ""   # given to something else in the meantime
            self.cfg.sounds.insert(min(index, len(self.cfg.sounds)), m)
            for t in m.tags:
                if t not in self.cfg.categories:
                    self.cfg.categories.append(t)
            if data is not None:
                self.audio[m.id] = data
                threading.Thread(target=self.engine.prepare, args=(m.id, data),
                                 daemon=True).start()
        self._save_now()
        self._rebuild_pads()
        self._fill_categories()
        if any(m.id not in self.audio for m in self.cfg.sounds):
            self._load_all()
        self.register_hotkeys()

    def _hotkey_taken(self, combo: str) -> bool:
        """Does a sound, an app-wide action, the push-to-talk key or a category's
        random-sound key already have `combo`?"""
        return (any(o.hotkey == combo for o in self.cfg.sounds)
                or any(getattr(self.cfg, attr) == combo for attr, *_ in HOTKEY_ACTIONS)
                or self.cfg.ptt_key == combo
                or combo in self.cfg.category_hotkeys.values())

    def _finish_removals(self):
        """The undo window is over: the removed sounds go to Recently deleted
        (soundboard.trash), where they can still be brought back for a while."""
        self._undo_timer.stop()
        self.undo_bar.hide()
        done, self._removed = self._removed, []
        for m, i, _d in done:
            trash.put_sound(m, i)
        if done:
            self._label_bin()

    def _label_bin(self):
        """The "Recently deleted (n)" button: there while the bin has sounds in it."""
        n = len(trash.items(trash.SOUND))
        self.btn_bin.setText(f"Recently deleted ({n})")
        self.btn_bin.setVisible(n > 0)

    def show_deleted(self):
        """Backup → Recently deleted sounds…"""
        from soundboard.ui.deleted import DeletedDialog
        self._finish_removals()   # the ones on the Undo bar are listed too
        DeletedDialog(trash.SOUND, "sounds", self._restore_deleted, self).exec()
        self._label_bin()

    def _restore_deleted(self, item: trash.Item) -> bool:
        m = trash.meta_of(item)
        if m is None or not Path(m.file).exists():
            return False
        self._put_back([(m, item.index, None)])
        return True

    def _shares_keys(self, a: SoundMeta, b: SoundMeta) -> bool:
        """Can a and b's hotkeys be live at the same time? With a set of hotkeys per
        category, two sounds with no category in common can share a key."""
        return (not self.cfg.scoped_hotkeys or not a.tags or not b.tags
                or bool(set(a.tags) & set(b.tags)))

    def _clear_dupe_hotkey(self, m) -> list[str]:
        """A combo does one thing: m's hotkey comes off whatever else had it. Returns
        what lost it ("“Boom”", "Stop everything"...), and says so in the status line,
        so a key taken from another sound or action is never a silent surprise."""
        lost = []
        if not m.hotkey:
            return lost
        for o in self.cfg.sounds:
            if (o is not m and o.hotkey and o.hotkey == m.hotkey
                    and self._shares_keys(o, m)):
                o.hotkey = ""
                lost.append(f"“{o.name}”")
                if o.id in self.pads:
                    self.pads[o.id].update()
        for attr, _action, label, _desc in HOTKEY_ACTIONS:
            if m.hotkey == getattr(self.cfg, attr):
                setattr(self.cfg, attr, "")
                lost.append(label)
        lost += [f"a random sound from “{c}”" for c, k in self.cfg.category_hotkeys.items()
                 if k == m.hotkey]
        self._clear_category_hotkey(m.hotkey)
        if lost:
            self.status.setText(
                f"<span style='color:{theme.status('warn')}'>"
                f"{html.escape(pretty_key(m.hotkey))} plays “{html.escape(m.name)}” now — "
                f"it was the key for {html.escape(' and '.join(lost))}.</span>")
        return lost

    def set_sound_hotkey(self, sid: str, combo: str | None = None):
        """The pad menu's hotkey: asks for one unless given ("" removes it)."""
        m = self.meta(sid)
        if m is None:
            return
        if combo is None:
            d = HotkeyDialog(self.hotkeys, self)
            combo = d.result_combo if d.exec() and d.result_combo else None
        if combo is not None and combo != m.hotkey:
            m.hotkey = combo
            self._clear_dupe_hotkey(m)
            self._save_now()
            if sid in self.pads:
                self.pads[sid].update()
            self.toast(f"✓ {html.escape(combo)} plays “{html.escape(m.name)}”" if combo
                       else f"Hotkey removed from “{html.escape(m.name)}”")
        self.register_hotkeys()   # the capture paused them

    def _clear_category_hotkey(self, combo: str, keep: str | None = None):
        """A combo does one thing: take it off any category's random-sound hotkey."""
        if combo:
            for cat in [c for c, k in self.cfg.category_hotkeys.items()
                        if k == combo and c != keep]:
                del self.cfg.category_hotkeys[cat]

    def set_category_hotkey(self, name: str, combo: str | None = None):
        """The hotkey that plays a random sound from category `name` (asks for it
        unless given; "" clears it)."""
        if name not in self.cfg.categories:
            return
        if combo is None:
            d = HotkeyDialog(self.hotkeys, self)
            combo = d.result_combo if d.exec() and d.result_combo else None
            if combo is None:
                self.register_hotkeys()   # the capture paused them
                return
        taken_from = []
        if combo:
            for attr, *_ in HOTKEY_ACTIONS:
                if getattr(self.cfg, attr) == combo:
                    setattr(self.cfg, attr, "")
                    taken_from.append("another action")
            for m in self.cfg.sounds:
                if m.hotkey == combo:
                    taken_from.append(f"“{m.name}”")
                    m.hotkey = ""
                    if m.id in self.pads:
                        self.pads[m.id].update()
            self._clear_category_hotkey(combo, keep=name)
            if self.cfg.ptt_key == combo:
                self.cfg.ptt_key = ""
            self.cfg.category_hotkeys[name] = combo
            msg = f"✓ {html.escape(combo)} plays a random “{html.escape(name)}” sound"
            if taken_from:
                msg += " — it was the key for " + html.escape(", ".join(taken_from))
            self.toast(msg, "ok")
        else:
            self.cfg.category_hotkeys.pop(name, None)
            self.toast(f"Random-sound hotkey for “{html.escape(name)}” cleared")
        self._save_now()
        self._fill_categories()
        self.register_hotkeys()

    def edit(self, sid, tab: str = "sound"):
        m = self.meta(sid)
        d = EditDialog(m, self.hotkeys, self.preview, self, tab=tab)
        d.hotkeys_changed.connect(self.register_hotkeys)
        ok = d.exec()
        self._preview_gen += 1                     # drop a preview still rendering
        self.engine.stop(f"{sid}~fx:preview")
        if ok and d.as_copy:
            self._save_copy(m, d)
        elif ok:
            old_key = soundfx.key(m.fx)
            d.apply()
            self._clear_dupe_hotkey(m)
            self.engine.set_gain(sid, self.gain_for(m))
            if soundfx.key(m.fx) != old_key:
                self._rerender(m)
            self._save_now()
            self.pads[sid].update()
            self.apply_filter(self.search.text())
        self.register_hotkeys()

    def _save_copy(self, m: SoundMeta, d: EditDialog):
        """'Save as new sound': the edits go onto a copy placed after the original."""
        name = d.name.text().strip() or m.name
        try:
            new = duplicate(m, name if name != m.name else f"{name} (edit)")
        except OSError as e:
            errors.warn(self, "Couldn't copy the sound", e)
            return
        d.apply(new)
        if new.name == m.name:
            new.name = f"{m.name} (edit)"[:40]
        if new.hotkey == m.hotkey:
            new.hotkey = ""   # the original keeps its hotkey
        self._clear_dupe_hotkey(new)
        self._tag_new(new)   # stays in sight in the category showing
        self.cfg.sounds.insert(self.cfg.sounds.index(m) + 1, new)
        self._index()
        self._save_now()
        self._rebuild_pads()
        self._rerender(new)

    def _rerender(self, m: SoundMeta):
        """Load a sound again after its effects changed. They're rendered in the
        background; the pad says 'applying effects…' until it's ready."""
        self.engine.stop(m.id)
        self.audio.pop(m.id, None)
        self.engine.forget(m.id)
        p = self.pads.get(m.id)
        if p:
            p.state = "rendering"
            p.update()
        gen = self._render_gen[m.id] = self._render_gen.get(m.id, 0) + 1

        def run():
            try:
                data = load_sound(m)
                if self._render_gen.get(m.id) != gen:
                    return   # edited again meanwhile: a newer render is on its way
                self.engine.prepare(m.id, data)
                self.bridge.loaded.emit(m.id, data, "")
            except Exception as e:  # noqa: BLE001
                log.warning("can't apply effects to %s: %s", m.name, e)
                self.bridge.loaded.emit(m.id, None, errors.plain(e))
            prune_cache(cache_keep(self._live_metas()))
        threading.Thread(target=run, daemon=True, name="fx-render").start()

    # ------------------------------------------------------------------ backup
    # Export / import: see soundboard/backup.py and docs/BACKUP-FORMAT.md. The file
    # work runs on a thread; the result comes back through the bridge.
    @staticmethod
    def _is_package(path: str) -> bool:
        p = Path(path)
        if p.is_dir():
            return (p / backup.MANIFEST).is_file() or (p / backup.SOUND_JSON).is_file()
        return p.suffix.lower() == ".zip"

    def _save_name(self, title: str, name: str) -> str:
        docs = Path.home() / "Documents"
        start = (docs if docs.is_dir() else Path.home()) / name
        f, _ = QFileDialog.getSaveFileName(self, title, str(start), "Zip file (*.zip)")
        if f and not f.lower().endswith(".zip"):
            f += ".zip"
        return f

    def export_board(self):
        """Everything: every sound (with its picture, effects, hotkey, categories) and
        the app's settings, to move to another PC or keep as a backup."""
        if not self.cfg.sounds and not QMessageBox.question(
                self, "Export", "There are no sounds yet. Export just your settings?") \
                == QMessageBox.Yes:
            return
        f = self._save_name("Export everything",
                            f"Onion Board backup {time.strftime('%Y-%m-%d')}.zip")
        if f:
            self._export(f, list(self.cfg.sounds), with_settings=True)

    def export_category(self):
        if self.cfg.category:
            self.export_sounds(self.category_sounds(), self.cfg.category)

    def export_sounds(self, sounds: list[SoundMeta], name: str):
        """A sound pack: just these sounds (no settings), e.g. to share with friends."""
        if not sounds:
            QMessageBox.information(self, "Export", "There are no sounds in it to export.")
            return
        f = self._save_name("Export sounds", backup._safe(name) + ".zip")
        if f:
            self._export(f, sounds, with_settings=False)

    def _export(self, path: str, sounds: list[SoundMeta], with_settings: bool):
        self._save_now()
        # snapshot on this thread: the UI keeps editing the live config (and each
        # sound's fx dict) while the export thread would be iterating over them
        cfg = copy.deepcopy(self.cfg) if with_settings else None
        sounds = copy.deepcopy(sounds)
        cats = list(self.cfg.categories)
        if self._exporting:
            self.toast("Still exporting the last one — try again when it's done", "warn")
            return
        self._exporting = True
        self.status.setText("Exporting…")
        self.toast(f"Exporting {len(sounds)} sound{'s' if len(sounds) != 1 else ''}…")

        def run():
            try:
                n = backup.export(path, sounds, cfg, cats)
                self.bridge.exported.emit(path, n, "")
            except Exception as e:  # noqa: BLE001 - disk full, no permission…
                log.exception("export to %s failed", path)
                self.bridge.exported.emit(path, 0, errors.plain(e))
        threading.Thread(target=run, daemon=True, name="export").start()

    def _on_exported(self, path: str, n: int, err: str):
        self._exporting = False
        self._update_status()
        if err:
            QMessageBox.warning(self, "Export failed",
                                f"Couldn't write {Path(path).name}:\n{errors.plain(err)}")
            return
        msg = (f"Exported {n} sound{'s' if n != 1 else ''} to "
               f"{html.escape(Path(path).name)}.")
        self.status.setText(msg)
        self.toast("✓ " + msg, "ok")

    def import_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Import a backup, sound pack or zip of sounds", str(Path.home()),
            "Zip file (*.zip)")
        if files:
            self.import_files(files)   # a plain zip of sounds is imported too

    def import_package(self, path: str):
        """Add the sounds from a backup / sound pack (ones already here are skipped).
        A full backup's settings are only applied if the user says so."""
        QApplication.setOverrideCursor(Qt.WaitCursor)   # reading a big zip takes a moment
        try:
            pkg = backup.read(path)
        except backup.BackupError as e:
            QApplication.restoreOverrideCursor()
            errors.warn(self, "Can't import", e)
            return
        except Exception as e:  # noqa: BLE001 - a damaged or odd file, never a crash
            QApplication.restoreOverrideCursor()
            log.warning("couldn't read %s", path, exc_info=True)
            QMessageBox.warning(self, "Can't import",
                                f"{Path(path).name} is damaged or in a format Onion Board "
                                f"can't read ({errors.plain(e)}).")
            return
        QApplication.restoreOverrideCursor()
        use_settings = False
        if pkg.settings:
            box = QMessageBox(QMessageBox.Question, "Import backup",
                              f"{Path(path).name} has {len(pkg.sounds)} sound"
                              f"{'s' if len(pkg.sounds) != 1 else ''} and the settings "
                              "they were saved with (theme, hotkeys, overlay, voice "
                              "effects…).\n\nUse its settings too? Your devices stay as "
                              "they are.", QMessageBox.NoButton, self)
            yes = box.addButton("Sounds and settings", QMessageBox.YesRole)
            box.addButton("Just the sounds", QMessageBox.NoRole)
            cancel = box.addButton(QMessageBox.Cancel)
            box.exec()
            if box.clickedButton() is cancel:
                return
            use_settings = box.clickedButton() is yes
        if use_settings:
            self._apply_backup_settings(pkg.settings)
        if not pkg.sounds:
            return
        # only what's on the board: a sound removed a moment ago (still undo-able) must
        # come back from its backup, or deleting all then restoring leaves nothing
        known = {m.fingerprint for m in self.cfg.sounds if m.fingerprint}
        start = len(self.cfg.sounds)
        self.status.setText(f"Importing {len(pkg.sounds)} sound(s)…")
        self.toast(f"Importing {len(pkg.sounds)} sound{'s' if len(pkg.sounds) != 1 else ''}…")

        def run():
            try:
                res = backup.install(
                    pkg, known, lambda i: PAD_COLORS[(start + i) % len(PAD_COLORS)])
                self.bridge.unpacked.emit(res, pkg, "")
            except Exception as e:  # noqa: BLE001
                log.exception("import of %s failed", path)
                self.bridge.unpacked.emit(None, pkg, errors.plain(e))
        threading.Thread(target=run, daemon=True, name="import-pack").start()

    def _apply_backup_settings(self, raw: dict):
        changed = backup.apply_settings(self.cfg, raw)
        if self.voice.fx.merge_saved(raw.get(backup.SAVED_VOICES)):   # their own file
            changed.append("saved voices")
        if "theme" in changed:
            self.apply_theme(self.cfg.theme)
        self._save_now()
        self.register_hotkeys()
        if changed:
            QMessageBox.information(self, "Settings imported",
                                    "Done. Hotkeys and the theme apply now; everything else "
                                    "the next time Onion Board starts.")

    def _on_unpacked(self, res, pkg, err: str):
        self._update_status()
        if res is None:
            QMessageBox.warning(self, "Import failed", err)
            return
        taken = {o.hotkey for o in self.cfg.sounds if o.hotkey}
        taken |= {getattr(self.cfg, a) for a, *_ in HOTKEY_ACTIONS if getattr(self.cfg, a)}
        taken |= {k for k in self.cfg.category_hotkeys.values() if k}
        from soundboard.library import merge_tags
        for m in res.sounds:
            if m.hotkey in taken:
                m.hotkey = ""   # the sounds already here keep theirs
            taken.add(m.hotkey)
            # "memes" goes into the "Memes" already here (and a new one gets a tab)
            m.tags = merge_tags(m.tags, self.cfg.categories)
            self.cfg.sounds.append(m)
        merge_tags(pkg.categories, self.cfg.categories)   # a full backup's empty ones too
        self._save_now()
        self._rebuild_pads()
        self._fill_categories()
        self._load_all()
        self.register_hotkeys()
        n = len(res.sounds)
        msg = f"Imported {n} sound{'s' if n != 1 else ''}"
        if res.skipped:
            msg += f" ({len(res.skipped)} already in your library)"
        self.status.setText(msg + ".")
        self.toast(f"✓ {msg}", "ok" if n else "")
        if res.failed:
            QMessageBox.warning(self, "Some sounds weren't imported",
                                "\n".join(res.failed[:15]))

    # ------------------------------------------------------------------ tray
    def _init_tray(self):
        """The tray icon: closing the window keeps the app (and its hotkeys) running
        there, unless turned off in Settings. No tray (some desktops): close quits."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        t = self.tray = QSystemTrayIcon(glow_icon(theme.T["accent"], theme.T["accent2"], 0.0), self)
        t.setToolTip(self.title)
        menu = QMenu(self)
        menu.addAction("Open Onion Board", self.show_from_tray)
        icons.set_icon(menu.addAction("Stop all sounds", self.stop_all), "stop")
        menu.addSeparator()
        menu.addAction("Quit", self.quit_app)
        t.setContextMenu(menu)
        t.activated.connect(self._on_tray)
        t.messageClicked.connect(self.show_from_tray)
        t.show()
        QApplication.instance().setQuitOnLastWindowClosed(False)

    def _on_tray(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_from_tray()

    def show_from_tray(self):
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def can_hide(self) -> bool:
        """Whether the window may start hidden (--tray): only with a tray icon to get
        it back, and once the setup guide is done."""
        return self.tray is not None and self.tray.isVisible() and self.cfg.setup_done

    def quit_app(self):
        self._quitting = True
        self.close()

    def restart_app(self):
        """Quit and start again (a reset or restore point runs at start-up: see
        soundboard.reset). The new copy waits for this one to be gone first."""
        for w in QApplication.topLevelWidgets():   # Settings, the guide
            if isinstance(w, QDialog) and w.isVisible():
                w.reject()
        skip = {autostart.TRAY_ARG, "--resume-setup"}
        args = [a for a in sys.argv[1 if getattr(sys, "frozen", False) else 0:]
                if a not in skip]
        if "--restart-after" in args:   # restarted before: drop the old pid
            i = args.index("--restart-after")
            del args[i:i + 2]
        try:
            subprocess.Popen([sys.executable, *args, "--restart-after", str(os.getpid())],
                             creationflags=0x00000008 | 0x00000200,   # detached, own group
                             close_fds=True)
        except OSError:
            log.exception("couldn't start the app again")
            self.toast("Close Onion Board and open it again to finish.", "warn")
            return
        self.quit_app()

    def _on_session_end(self, _manager=None):
        """Windows is logging off, shutting down, or an installer / updater asked the
        app to close (the Restart Manager sends the same message). Closing then really
        quits: hiding to the tray would veto it, and an upgrade run while the app is
        open would fail with "Setup was unable to close all applications"."""
        self._quitting = True

    def apply_remote(self) -> str:
        """Start / stop the local control API to match the settings; "" or an error."""
        err = remote.apply(self, self.remote)
        if err:
            self.status.setText(f"<span style='color:{theme.status('warn')}'>"
                                "Remote control is off: "
                                f"{html.escape(err)}.</span>")
        return err

    def set_autostart(self, on: bool) -> bool:
        return autostart.set_enabled(on, self.cfg.autostart_hidden)

    def set_autostart_hidden(self, hidden: bool):
        self.set_option("autostart_hidden", hidden)
        autostart.refresh(hidden)

    # ------------------------------------------------------------------ updates
    def check_updates(self, force: bool = False, why: str = ""):
        """Look for a newer release on a thread (see updates.py). Without `force` only
        if the box is ticked, and at most once a day. `why`: the click that asked, for
        Network activity (none: the app's own timer)."""
        if not force and not self.cfg.update_check:
            return

        due = force or time.time() - self.cfg.update_checked >= updates.EVERY_S
        why = why or "Automatic update check (at most once a day)"
        netlog.cause(updates.FEATURE, why)
        netlog.cause(watchaddon.FEATURE, f"{why}: Onion Watch add-on")

        def run():
            try:
                rel = updates.check(self.cfg, force=force)
                self.bridge.update.emit(rel, "", force)
            except Exception as e:  # noqa: BLE001 - offline etc.
                self.bridge.update.emit(None, errors.plain(e), force)
            if due:   # and the Onion Watch add-on, once it's installed (else nothing asked)
                offer = watchaddon.check_update()
                if offer is not None:
                    self.bridge.watch_update.emit(offer)
        threading.Thread(target=run, daemon=True, name="update-check").start()

    def _on_update(self, rel, err: str, asked: bool):
        self._save_later()   # update_checked
        busy = self._downloading or self._update_file is not None
        if rel is not None and not busy:
            self.release = rel
            self._set_update_pill(f"Update: {rel.version}",
                                  f"Onion Board {rel.version} is out — click for details")
            if self.tray is not None and not self.isVisible():
                self.tray.showMessage("Onion Board", f"Version {rel.version} is out.",
                                      QSystemTrayIcon.Information, 8000)
        self.update_done.emit(rel, err)   # for the Settings window's "Check now"
        if asked and rel is not None:
            self.show_update()

    def _set_update_pill(self, text: str, tip: str, enabled: bool = True):
        self.btn_update.setText(text)
        self.btn_update.setToolTip(tip)
        self.btn_update.setEnabled(enabled)
        self.btn_update.show()

    def show_update(self):
        """The update pill was clicked: what's new, and what can be done about it."""
        if self._update_file is not None:
            self.install_update()
            return
        rel = self.release
        if rel is None or self._downloading:
            return
        from soundboard import __version__
        box = QMessageBox(QMessageBox.Information, "Update available",
                          f"Onion Board {rel.version} is out (you have {__version__}).",
                          QMessageBox.NoButton, self)
        info = html.escape(rel.notes).replace("\n", "<br>") if rel.notes else ""
        installable = updates.can_install() and bool(rel.asset_url)
        if installable:
            info += ("<p>Update now downloads it in the background (about 140 MB); you "
                     "choose when the app restarts to install it. Your sounds and "
                     "settings stay as they are.</p>")
        elif not updates.can_install():
            info += "<p>This copy runs from source: update it with <code>git pull</code>.</p>"
        if info:
            box.setInformativeText(f"<p>{info}</p>")
        get = box.addButton("Update now" if installable else "Open the download page",
                            QMessageBox.AcceptRole)
        page = box.addButton("Release page", QMessageBox.HelpRole) if installable else None
        skip = box.addButton("Skip this version", QMessageBox.DestructiveRole)
        box.addButton("Later", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is get and installable:
            self.download_update()
        elif clicked is get or (page is not None and clicked is page):
            QDesktopServices.openUrl(QUrl(rel.url))
        elif clicked is skip:
            self.set_option("update_skip", rel.version)
            self.release = None
            self.btn_update.hide()

    def download_update(self):
        """Fetch the new version's installer on a thread (updates.download)."""
        rel = self.release
        if rel is None or self._downloading:
            return
        if not net.allowed(updates.FEATURE):   # switched off since it was found
            self.toast(html.escape(net.off_message(updates.FEATURE)), "warn")
            return
        self._downloading = True
        netlog.cause(updates.FEATURE, f"You clicked to download Onion Board {rel.version}")
        self._set_update_pill("Downloading update…",
                              f"Downloading Onion Board {rel.version}", enabled=False)
        last = [-1]

        def progress(done, total):
            pct = min(done * 100 // total, 100) if total else 0
            if pct != last[0]:
                last[0] = pct
                self.bridge.update_progress.emit(pct)

        def run():
            try:
                path = updates.download(rel, progress, lambda: self._shut_down)
                self.bridge.update_ready.emit(path, "")
            except updates.UpdateError as e:
                self.bridge.update_ready.emit(None, errors.plain(e))
            except Exception as e:  # noqa: BLE001 - never leave the pill stuck
                log.exception("update download failed")
                self.bridge.update_ready.emit(None, errors.plain(e))
        threading.Thread(target=run, daemon=True, name="update-download").start()

    def _on_update_progress(self, pct: int):
        if self._downloading:
            self.btn_update.setText(f"Downloading update… {pct}%")

    def _on_update_ready(self, path, err: str):
        self._downloading = False
        rel = self.release
        if rel is None:
            return
        if path is None:
            self._set_update_pill(f"Update: {rel.version}",
                                  f"Onion Board {rel.version} is out — click for details")
            box = QMessageBox(QMessageBox.Warning, "Couldn't update",
                              f"Onion Board {rel.version} couldn't be downloaded: "
                              f"{errors.plain(err)}.",
                              QMessageBox.NoButton, self)
            page = box.addButton("Open the download page", QMessageBox.AcceptRole)
            box.addButton("Close", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is page:
                QDesktopServices.openUrl(QUrl(rel.url))
            return
        self._update_file = path
        self._set_update_pill("Restart to update",
                              f"Onion Board {rel.version} is downloaded — click to install it")
        if self.tray is not None and not self.isVisible():
            # hidden in the tray, maybe mid-game: don't pop a question, just say so
            self.tray.showMessage("Onion Board", f"Version {rel.version} is ready to install: "
                                  "open Onion Board and click Restart to update.",
                                  QSystemTrayIcon.Information, 8000)
            return
        self.install_update()

    def install_update(self):
        """Ask, then close the app and let the downloaded installer replace it (it
        opens the app again when it's done)."""
        rel, path = self.release, self._update_file
        if rel is None or path is None:
            return
        box = QMessageBox(QMessageBox.Question, "Install the update",
                          f"Onion Board {rel.version} is ready. Restart now to install it?",
                          QMessageBox.NoButton, self)
        box.setInformativeText("Onion Board closes, installs the new version and opens "
                               "again by itself, usually within a minute. Sounds that are "
                               "playing stop.")
        now = box.addButton("Restart now", QMessageBox.AcceptRole)
        box.addButton("Later", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not now:
            return
        if not path.is_file():   # removed meanwhile: fetch it again
            self._update_file = None
            self.download_update()
            return
        self.cfg.update_pending = rel.version
        self.cfg.save()
        try:
            updates.start_install(path)
        except OSError as e:
            log.warning("couldn't start the update installer: %s", e)
            self.cfg.update_pending = ""
            self._save_later()
            QMessageBox.warning(self, "Couldn't update",
                                f"The installer couldn't be started ({errors.plain(e)}). You can "
                                "download it from the release page instead.")
            return
        self.quit_app()

    def after_update(self):
        """At start: remove downloaded installers and, the first time after an update
        was started, say whether it worked; then What's new, once per version."""
        pending, self.cfg.update_pending = self.cfg.update_pending, ""
        updates.cleanup()
        from soundboard import __version__
        if pending:
            self._save_later()
            if not updates.finished(pending):
                self._update_failed(pending)
                return
            log.info("updated to %s", __version__)
        self.whats_new(updated=bool(pending))

    def whats_new(self, updated: bool = False):
        """What's new in this version (ui/whatsnew.py), if they haven't seen it: once,
        with a button to the settings it's about. Waits while the window is in the tray
        or the setup guide is about to run. `updated`: the app updated itself."""
        from soundboard import __version__
        from soundboard.ui import whatsnew
        if not self.cfg.setup_done:   # the guide comes first; this waits for next time
            return
        if not self.isVisible():   # started with Windows, in the tray: when it's opened
            self._whats_new_later = updated
            return
        notes = whatsnew.unseen(self.cfg.whats_new_seen)
        if updates.newer(__version__, self.cfg.whats_new_seen or "0"):
            self.cfg.whats_new_seen = __version__
            self._save_later()
        if notes:
            dlg = whatsnew.WhatsNewDialog(self, notes, updated)
            dlg.exec()
            page = dlg.page
            free_dialog(dlg)
            if page:
                self.open_settings(page)
            return
        if not updated:
            return
        box = QMessageBox(QMessageBox.Information, "Updated",
                          f"Onion Board is up to date: version {__version__}.",
                          QMessageBox.NoButton, self)
        new = box.addButton("What's new", QMessageBox.HelpRole)
        box.addButton(QMessageBox.Ok)
        box.exec()
        if box.clickedButton() is new:
            QDesktopServices.openUrl(QUrl(
                f"https://github.com/{updates.REPO}/releases/tag/v{__version__}"))

    def _update_failed(self, pending: str):
        from soundboard import __version__
        log.warning("the update to %s didn't finish (still %s)", pending, __version__)
        box = QMessageBox(QMessageBox.Warning, "The update didn't finish",
                          f"Onion Board {pending} wasn't installed; this is still "
                          f"{__version__}. You can download it from its page and "
                          "run it yourself.", QMessageBox.NoButton, self)
        page = box.addButton("Open the download page", QMessageBox.AcceptRole)
        logb = (box.addButton("Show the install log", QMessageBox.HelpRole)
                if updates.INSTALL_LOG.is_file() else None)
        box.addButton("Close", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is page:
            QDesktopServices.openUrl(QUrl(updates.RELEASES))
        elif logb is not None and box.clickedButton() is logb:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(updates.INSTALL_LOG)))

    # ------------------------------------------------------------------ test mode
    def on_mic_check(self, on):
        self.engine.ring_mon.clear()
        self.engine.mic_check = on
        text = "Stop hearing it" if on else "Hear what they hear"
        self.btn_check.setProperty("full_text", text)   # what a compact window restores
        self.btn_check_test.setText(text)
        if self.btn_check.text():   # blank while the window is too narrow for words
            self.btn_check.setText(text)
        self.mic_banner.setVisible(on)
        if on:
            self._pulse.start()   # impossible to miss, and cheap
        else:
            self._pulse.stop()
            self._banner_fx.setOpacity(1.0)
        self.setWindowTitle(f"● MIC LIVE IN HEADPHONES — {self.title}" if on else self.title)
        self.mic_lbl.setStyleSheet(f"color:{theme.status('error')};" if on else "")
        self.mic_meter.hot = on
        if on and not self.cfg.mic_enabled:
            self.status.setText(f"<span style='color:{theme.status('warn')}'>"
                                "Sounds only: your mic isn't "
                                "sent, so nobody (including you) hears it.</span>")

    def start_test(self):
        if self.engine.main_stream is None:
            QMessageBox.information(self, "Test",
                                    "Set up the virtual cable first (Setup tab → "
                                    "Step-by-step guide).")
            return
        # Capture the far end of the virtual cable too, so the test hears exactly
        # what Discord / the game hears (not just our internal mix).
        self._stop_capture()
        self._cap, self._cap_rate = [], None
        vm = eng.virtual_mic_for(self.cfg.main_device)
        self._cap_name = vm
        if vm:
            idx = eng.find_device("input", vm)
            if idx is not None:
                try:
                    self._cap_rate = int(sd.query_devices(idx)["default_samplerate"])
                    self._cap_stream = sd.InputStream(
                        device=idx, samplerate=self._cap_rate, channels=2, dtype="float32",
                        callback=lambda i, f, t, s: self._cap.append(i.copy()))
                    self._cap_stream.start()
                except Exception:  # noqa: BLE001 - fall back to the internal mix
                    log.warning("can't capture %s for the test; using the internal mix",
                                vm, exc_info=True)
                    self._cap_stream = None
        self.engine.start_test_record(6.0)
        self.btn_rec.setEnabled(False)
        self.test_result.hide()
        self._rec_started = time.monotonic()

    def _stop_capture(self) -> bool:
        """Close the test's cable-capture stream if one is open. True if there was one."""
        s, self._cap_stream = self._cap_stream, None
        if s is None:
            return False
        try:
            s.stop()
            s.close()
        except Exception:  # noqa: BLE001
            log.debug("closing the test capture stream raised", exc_info=True)
        return True

    def _finish_test(self, internal, rate):
        e = self.engine
        cable = False
        data = internal
        if self._stop_capture() and self._cap:
            data, rate, cable = np.concatenate(self._cap), self._cap_rate, True
        mic = e.take_mic_recording()
        if not self.cfg.mic_enabled:   # sounds only: don't go looking for the voice
            mic = None
        try:
            r = analyze_output(data, rate, mic[0] if mic else None, mic[1] if mic else SR,
                               self.cfg.sound_vol)
            self.test_result.setText(summary_html(r, self._cap_name if cable else None,
                                                  mic_sent=self.cfg.mic_enabled))
        except Exception as ex:  # noqa: BLE001
            log.exception("test analysis failed")
            self.test_result.setText(
                f"<span style='color:{theme.status('error')}'>Test analysis failed: "
                f"{errors.plain(ex)}</span>")
        self.test_result.show()
        return data, rate

    # ------------------------------------------------------------------ tick
    # The window's visibility sets the UI timer's pace: 30/s for the meters and
    # visualisers while it's on screen, TICK_BG_MS while it's on screen behind another
    # program (a game: the meters still move, a third as often), TICK_IDLE_MS while it's
    # hidden in the tray or minimised (nothing to paint, but push-to-talk, the stream
    # watchdog and the test recording must go on). Qt tells us through these three
    # events and applicationStateChanged.
    def showEvent(self, ev):
        shellicon.on_show(self)   # the Jump List icon, before the taskbar button exists
        shellicon.paint_background(self, theme.T["bg"])
        super().showEvent(ev)
        self._set_tick_rate()
        note, self._pending_note = getattr(self, "_pending_note", None), None
        if note:   # held back while the window was in the tray (see __init__)
            QTimer.singleShot(400, lambda: QMessageBox.warning(
                self, "Settings were restored", note))
        later, self._whats_new_later = getattr(self, "_whats_new_later", None), None
        if later is not None:   # held back while the window was in the tray
            QTimer.singleShot(700, lambda: self.whats_new(later))

    def hideEvent(self, ev):
        super().hideEvent(ev)
        self._set_tick_rate()

    def changeEvent(self, ev):
        super().changeEvent(ev)
        if ev.type() == QEvent.WindowStateChange:
            self._set_tick_rate()

    def _tick_pace(self) -> int:
        if self.overlay.is_open:   # the in-game overlay shows what's playing, over the game
            return TICK_MS
        if not self._ui_live:
            return TICK_IDLE_MS
        return TICK_MS if appstate.active() else TICK_BG_MS

    def _set_tick_rate(self, *_):
        live = self.isVisible() and not self.isMinimized()
        was, self._ui_live = self._ui_live, live
        pace = self._tick_pace()
        if live == was and self.timer.interval() == pace:
            return
        self.timer.start(pace)
        if not live:   # a level frozen mid-flight would show as stuck on the next show
            self.out_meter.set_level(0.0)
            self.mic_meter.set_level(0.0)

    def tick(self):
        e = self.engine
        now = time.monotonic()
        self._tick_n += 1
        if self._tick_n % max(1, 1000 // self.timer.interval()) == 0:   # about once a second
            if e.check_streams() or sum(e.xruns.values()) != self._xruns_shown:
                self._update_status()
            self.voice.poll()
        playing = e.playing()
        if self._queue and not any(sid in self._meta for sid in playing):
            self._next_in_queue()
            playing = e.playing()
        pace = self._tick_pace()
        if self.timer.interval() != pace:
            self.timer.start(pace)
        if self._ui_live:
            self._tick_visuals(playing, now)
        self.overlay.tick(playing)
        self._glow_icons(e.level_play, now)
        e.level_play *= 0.9
        e.level_main *= 0.9
        e.level_mic *= 0.9

        # test recording
        if e.recording:
            left = 6.0 - (now - self._rec_started)
            self.btn_rec.setText(f"Recording… talk / play sounds  ({max(left, 0):.0f}s)")
            if left < -4:   # the output stopped (device unplugged): give up
                e.cancel_test_record()
                self._stop_capture()
                self.btn_rec.setEnabled(True)
                self.btn_rec.setText("Record 6s → play back")
                self.test_result.setText(f"<span style='color:{theme.status('error')}'>"
                                         "The test stopped: the "
                                         "virtual cable's output went away. Check Devices "
                                         "and try again.</span>")
                self.test_result.show()
        elif e.rec_done is not None:
            data, rate = e.rec_done
            e.rec_done = None
            data, rate = self._finish_test(data, rate)
            e.play("__test__", data, 1.0, preview=True, src_rate=rate)
            self._rec_playing = True
            self.btn_rec.setText("Playing back what they heard…")
        elif self._rec_playing and "__test__" not in playing:
            self._rec_playing = False
            self.btn_rec.setEnabled(True)
            self.btn_rec.setText("Record 6s → play back")

        # auto push-to-talk: hold the game's PTT key only while a sound (or live
        # radio / a program) goes out. _ptt_held remembers exactly which key we pressed, so it's
        # always released even if the setting changes mid-sound.
        on_air = e.sending and (e.any_playing() or e.radio_on_air()
                                or e.aux_on_air())
        want = self.cfg.ptt_key if (self.cfg.ptt_key and on_air) else None
        if want != self._ptt_held:
            if not self._release_ptt():
                return   # still held: try the key-up again next tick
            if want and winkeys.press(want):
                self._ptt_held = want

    def _tick_visuals(self, playing, now: float):
        """The part of tick() that only matters while the window is on screen."""
        e = self.engine
        on_board = self.tabs.currentWidget() is self.sounds_page   # no visualiser off-screen
        for sid, p in self.pads.items():
            prog, paused = playing.get(sid, (None, False))
            if prog is not None and not paused and on_board and not p.isHidden():
                p.set_levels(spectrum(self.audio.get(sid), prog, p.n_bands))
            elif prog is None and p.bands is not None:
                p.set_levels(None)
            if prog != p.progress or paused != p.paused:
                p.progress, p.paused = prog, paused
                p.update()
        self._update_transport(playing)
        self._update_chips(playing)
        self.out_meter.set_level(e.level_main)
        self.logo.set_level(e.level_play)   # anything playing, not your voice
        self.mic_meter.set_level(e.level_mic if e.mic_stream else 0.0)
        talking = e.mic_stream is not None and e.level_mic > 0.05
        if talking:
            self._talk_until = now + 0.8
        talking = now < self._talk_until
        if talking != self._talk_shown:
            self._talk_shown = talking
            self._update_flow(talking)

    def _update_transport(self, playing):
        sid = self.current
        m = self.meta(sid) if sid else None
        enabled = m is not None
        for w in (self.btn_pp, self.btn_st, self.seek, self.mini_pp, self.mini_st,
                  self.mini_seek):
            w.setEnabled(enabled)
        if not m:
            return
        prog, paused = playing.get(sid, (None, False))
        live = prog is not None
        self._set_pp_icon("pause" if live and not paused else "play")
        if not self._seeking:
            frac = prog if live else self.start_frac
            for slider in (self.seek, self.mini_seek):
                slider.blockSignals(True)
                slider.setValue(int(frac * 1000))
                slider.blockSignals(False)
            self.np_time.setText(fmt_pos(frac * m.duration, m.duration))
            self.mini_time.setText(self.np_time.text())

    def _release_ptt(self) -> bool:
        """Let go of the PTT key we hold. False if Windows refused the key-up (an
        admin window or a UAC prompt in front blocks it): it stays ours to release,
        or the game's push-to-talk would stay stuck down."""
        if self._ptt_held:
            if not winkeys.release(self._ptt_held):
                return False
            self._ptt_held = None
        return True

    # ------------------------------------------------------------------ small windows
    def _init_fit(self):
        """What gives way when the window gets small (see ui/responsive.py). Lower
        numbers go first; width and height are handled separately."""
        r = responsive
        f = self._fit = r.Fitter(self._full)
        f.add(10, "w", r.hide(self.tagline))
        f.add(10, "w", r.hide(*self._pad_size))
        f.add(12, "w", r.hide(*self._mixer_send))
        f.add(14, "w", r.hide(self.np_time))
        f.add(45, "w", r.hide(self.speed_btn))
        f.add(20, "w", self._shorten_pill)
        f.add(58, "w", r.icon_only(self.stop_btn))
        f.add(24, "w", self._shorten_air(1))
        f.add(65, "w", self._shorten_air(2))
        f.add(22, "w", r.icon_only(self.gear))
        f.add(30, "w", r.hide(self.chk_monitor))
        f.add(28, "w", r.icon_only(self.chk_mic))   # its tooltip still explains it
        f.add(34, "w", r.icon_only(self.btn_check))
        f.add(55, "w", r.hide(*self._mixer_hp))
        f.add(40, "w", r.hide(*self._transport_vol))
        f.add(50, "w", r.hide(self.np_name))
        f.add(60, "w", r.hide(self.wordmark))
        f.add(60, "w", r.icon_only(self.btn_add))
        f.add(35, "w", r.hide(self.btn_more))   # also in Settings → General
        f.add(15, "w", r.icon_only(self.btn_folder))
        f.add(33, "w", r.hide(self.btn_folder))   # also in the Backup menu
        f.add(60, "w", self._tab_icons_only)
        f.add(70, "w", r.hide(self.btn_check, *self._mixer_others))
        f.add(80, "w", r.hide(self.pill))
        f.add(85, "w", self._tabs_tight)   # else the icons alone held it at ~480 px
        f.extend(self.radio.fit_steps())
        f.extend(self.voice.fit_steps())
        f.extend(self.triggers.fit_steps())
        # height: the status line, then the whole mixer strip
        f.add(10, "h", r.hide(self.status))
        f.add(30, "h", r.hide(*self._deck_titles))
        f.add(40, "h", r.hide(self.mixer))
        f.add(50, "h", r.hide(self.cat_bar))   # the overlay's category key still works
        self._stack_cols = (r.stack(self._setup_cols), *self.voice.stack_steps())
        self.setMinimumSize(responsive.MIN_SIZE)

    def _shorten_pill(self, short: bool):
        if short != self._pill_short:
            self._pill_short = short
            self._update_flow()

    def _tab_icons_only(self, compact: bool):
        for i, (text, tip) in enumerate(TABS):
            self.tabs.setTabText(i, "" if compact else text)
            base = f"{text}: {tip}" if compact else tip
            old = self.tabs.property(f"_tip{i}")   # set_tab_live's copy of the plain tip
            if old is not None:
                cur = self.tabs.tabToolTip(i)
                self.tabs.setProperty(f"_tip{i}", base)
                if is_tab_live(self.tabs, i) and cur.endswith(old):   # keep its "● ON" line
                    base = cur[:len(cur) - len(old)] + base
            self.tabs.setTabToolTip(i, base)

    def _tabs_tight(self, compact: bool):
        """Icon-only tabs packed close: their padding was the widest thing left, so a
        window the rest fits turned into the mini player."""
        bar = self.tabs.tabBar()
        bar.setStyleSheet("QTabBar::tab { padding:8px 6px; margin-right:0px; }"
                          if compact else "")
        responsive.touch(bar)

    def _refit(self):
        size = self._pages.size()
        mini = size.width() < MINI_SIZE.width() or size.height() < MINI_SIZE.height()
        if not mini:
            # measured with the whole window in place: while the mini player shows, the
            # hidden page's sizes go stale and it stayed the mini player at sizes the
            # whole window fits (nothing is painted before this returns)
            self._set_mini(False)
            # room for a whole row of pads comes before the mixer, the status line and
            # the rest: without it they kept their room and the pads got a slit
            self._pads_scroll.setMinimumHeight(self.grid.row_height())
            narrow = self.width() < 860   # two cards side by side get cramped below this
            for apply in self._stack_cols:
                apply(narrow)
            self._fit.fit(size)
            need = self._fit.need()   # even the smallest layout won't fit
            mini = need.width() > size.width() or need.height() > size.height()
            if mini and not self.is_mini():
                log.info("mini player at %dx%d: the window needs %dx%d (tab %s)",
                         size.width(), size.height(), need.width(), need.height(),
                         type(self.tabs.currentWidget()).__name__)
        self._set_mini(mini)
        if mini:   # the pads too: cards with room for a couple of rows of them, else
            # one-line rows, so they can still be seen and played however small it gets
            room = self._mini_pad_room(size)
            self.grid.set_slim(room < MINI_PAD_ROWS * self._mini_row(size))
            m = self.grid.grid.contentsMargins()
            show = room >= SLIM_PAD_H + m.top() + m.bottom()
            if self._pads_scroll.isHidden() == show:
                self._pads_scroll.setVisible(show)

    def _mini_pad_room(self, size: QSize) -> int:
        """The height above the mini player's card."""
        m = self._mini_v.contentsMargins()
        return (size.height() - m.top() - m.bottom() - self._mini_v.spacing()
                - self._mini_card.sizeHint().height())

    def _mini_row(self, size: QSize) -> int:
        """How tall a row of pads is in the mini player at this size."""
        m, g = self._mini_v.contentsMargins(), self.grid.grid.contentsMargins()
        bar = self._pads_scroll.verticalScrollBar().sizeHint().width()
        room = size.width() - m.left() - m.right() - g.left() - g.right() - bar
        return pad_height(self.grid.fit_width(room, slim=False)[1]) + 10

    def is_mini(self) -> bool:
        return self._pages.currentIndex() == 1

    def _set_mini(self, on: bool):
        """Swap the whole window for the mini player (or back). The pads move with it."""
        if on == self.is_mini():
            return
        scroll = self._pads_scroll
        self.setUpdatesEnabled(False)
        try:
            self.grid.set_two_up(on)
            if not on:
                self.grid.set_slim(False)
            if on:
                scroll.setMinimumHeight(0)
                self._mini_v.insertWidget(0, scroll, 1)
            else:
                home, index = self._pads_home
                home.insertWidget(index, scroll, 1)
                scroll.setVisible(self.ytresults.isHidden())   # results take the pads' place
            self._pages.setCurrentIndex(1 if on else 0)
            self.apply_filter(self.search.text())
        finally:
            self.setUpdatesEnabled(True)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if hasattr(self, "_fit"):
            # right away, before the frame is painted: a queued refit let each frame
            # paint twice, before and after, which made parts of the window flash
            self._refit()

    # Files dropped anywhere else on the window (the toolbar, another tab, the edge of
    # the pad area) are added just like ones dropped on the pads.
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, e):
        files = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if files:
            e.acceptProposedAction()
            # after the drop returns, so Explorer isn't frozen until a dialog is answered
            QTimer.singleShot(0, lambda: self.import_files(expand_dropped(files)))

    def closeEvent(self, ev):
        if self.tray is not None and self.tray.isVisible() and self.cfg.tray \
                and not self._quitting:
            ev.ignore()   # keep running in the tray: hotkeys, overlay and sounds go on
            self.hide()
            if not self._tray_told:
                self._tray_told = True
                self.tray.showMessage("Onion Board is still running",
                                      "Your hotkeys keep working. Right-click this icon "
                                      "to quit.", QSystemTrayIcon.Information, 5000)
            return
        if self.tray is not None:
            self.tray.hide()
            QTimer.singleShot(0, QApplication.instance().quit)
        self.shutdown()
        super().closeEvent(ev)

    def shutdown(self):
        """Everything a real quit must do, once: from closeEvent, or from aboutToQuit
        when Windows ends the session while the window is hidden in the tray. Each
        step runs even if an earlier one failed, so a held push-to-talk key is always
        let go and settings are always saved."""
        if self._shut_down:
            return
        self._shut_down = True
        for step in (self._finish_removals, self.timer.stop, self._voice_timer.stop,
                     self._release_ptt,
                     self._stop_capture, self.cfg.save, self.overlay.shutdown,
                     self.hotkeys.stop, self.replay.stop, self.remote.stop,
                     self.radio.shutdown, tor.shutdown, self.apps.shutdown,
                     self.triggers.shutdown,
                     self.linkbar.shutdown,
                     self.voice.shutdown, self.engine.shutdown, shellicon.detach,
                     netlog.flush):   # last: what's still open, once the rest closed
            try:
                step()
            except Exception:  # noqa: BLE001 - keep shutting the rest down
                log.exception("shutdown step %s failed", getattr(step, "__name__", step))
        e = self.engine
        log.info("closed cleanly (drop-outs %s, callback errors %s, stalls %d, "
                 "radio gaps %d / skips %d, cushion %d ms, mic into cable gaps %d / "
                 "skips %d%s)",
                 e.xruns, e.cb_errors, e.stalls,
                 e.ring_rmon.underruns + e.ring_rmain.underruns,
                 e.ring_rmon.overflows + e.ring_rmain.overflows,
                 e.ring_rmon.prefill * 1000 // max(e.rates.get("mon", SR), 1),
                 e.ring_main.underruns, e.ring_main.overflows,
                 ", drift tracked" if e.ring_main.track_drift else "")
