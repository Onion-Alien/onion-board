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
from PySide6.QtCore import (QAbstractAnimation, QEvent, QFileSystemWatcher, QObject,
                            QPropertyAnimation, QSignalBlocker, QSize, Qt, QTimer, QUrl,
                            Signal)
from PySide6.QtGui import QDesktopServices, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
                               QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
                               QPushButton, QScrollArea, QSizePolicy, QSlider, QStackedWidget,
                               QSystemTrayIcon, QTabBar, QTabWidget, QVBoxLayout, QWidget)

from soundboard import engine as eng
from soundboard import theme, winkeys, ytdl
from soundboard.engine import SR, Engine
from soundboard.engine import is_virtual as is_virtual_cable
from soundboard import (appaudio, autostart, backup, catswitch, destination, library, midi,
                        remote, otherboards, soundfx, thumbs, trash, updates, videos, voicesdk)
from soundboard import directmic, net, netlog, profiles, quality, shellicon, tor, usage, watchaddon
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
from soundboard.ui import (a11y, alsosend, appstate, busy, clipeditor, icons, responsive, splash,
                           taboff)
from soundboard.ui.speedpitch import SpeedPitchButton
from soundboard.ui.panel import (EqPanel, Flow, VolumeControl, bar, card, hint_label,
                                 icon_label, vsep)
from soundboard.ui.linkbar import PLAY_ID as LINK_ID
from soundboard.ui.linkbar import LinkBar
from soundboard.ui.livedot import is_tab_live, set_tab_live
from soundboard.ui.livedot import set_tint as set_live_tint
from soundboard.ui.logowidget import LogoWidget, glow_icon
from soundboard.ui.ytsearch import SearchResults
from soundboard.ui.padbatch import PadSelection
from soundboard.ui.overlay import Overlay
from soundboard.ui.appspanel import AppsTab, ElidedLabel
from soundboard.ui.triggershost import BoardHost
from soundboard.ui.triggerstab import TriggersTab
from soundboard.ui.radiopanel import RadioOff, RadioTab
from soundboard.ui.voicepanel import VoicePanel
from soundboard.ui.widgets import (Meter, NameAndSeek, Pad, PadGrid, SeekSlider, SteadyTabs,
                                   TabInfoCorner, expand_dropped, fmt_pos, pad_height, spectrum,
                                   SLIM_PAD_H)
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
        ("Setup", "Pick where your sounds go (Discord, games, OBS…), test it"))
TAB_INDEX = {text.lower(): i for i, (text, _tip) in enumerate(TABS)}


UNDO_S = 10          # how long "Removed … · Undo" stays up
CHIPS_ROW_H = 30      # the now-playing row: a chip's 24 px ■ button, its margins and border
TICK_MS = 33         # the UI timer while the window is on screen (meters, visualisers)
TICK_BG_MS = 100     # ...while it's on screen but another program is in front (a game)
TICK_IDLE_MS = 250   # ...and while it's in the tray or minimised (push-to-talk, watchdog)
TICK_QUIET_MS = 100  # on screen with nothing moving: no sound, radio, recording or level
LEVEL_QUIET = 0.003  # a level below this (-50 dB) shows as nothing on the meters
TRIGGERS_LOAD_MS = 50   # Onion Watch loads this long after the window is built
GLOW_STEPS = 4       # how many glow levels the taskbar / tray icon has while sound plays
ICON_GLOW_MS = 120   # ...and how often at most it changes
ICON_GLOW_BG_MS = 400   # ...while another program (a game) is in front
DEFAULT_POLL_MS = 1500   # how often Windows' default output is checked
DEFAULT_POLL_IDLE_S = 5  # ...while the window is in the tray or minimised (seconds)
# a device that won't open while Windows lists it: re-scan, then wait this long
# (seconds) before the next re-scan, so one that really won't open isn't re-scanned
# over and over (each re-scan reopens every stream)
RECOVER_WAIT_S = (20, 40, 80, 160, 300)
# ...and one Windows doesn't list (unplugged): looked for at the timer's pace for a
# few checks (a quick re-plug), then only this often (seconds)
GONE_CHECKS, GONE_WAIT_S = 4, 6
LOOSE_WAIT_MS = 1500   # a file dragged into the sounds folder is looked at again (ms)
LOOSE_EMPTY_LOOKS = 20   # an empty file that long (~30 s) waits for the folder to change
MINI_SIZE = QSize(440, 380)   # below this the window becomes the mini player...
MINI_PAD_ROWS = 1             # ...which has the pads above it when this many rows fit
QUEUE_CHIPS = 5          # queued sounds shown by name above the pads (then "+n more")
SEARCH_WAIT_MS = 100     # typing in the search box filters the pads once it pauses this long
PAD_SIZE_WAIT_MS = 50    # dragging Pad size re-lays the pads at most this often
RANDOM = "__random__:"   # hotkey action prefix: a random sound from the category after it
ALL = "All"          # the category tab that shows every sound
VOICE_POLL_MS = 3000  # how often the game in front is looked at (soundboard.voicesdk)
VOICE_POLL_IDLE_S = 15   # ...while nobody sees the hint and nothing switches by itself
# Setup -> Devices -> Send my sounds to (Config.route, library.ROUTES): the mic, nobody,
# or one of the output devices by name (ROUTE_DEVICE + its name: "cable" for a virtual
# cable, "device" for anything else)
SEND_TO = "Send my sounds to"
ROUTE_CHOICES = (("My mic (normal)", "mic"),
                 ("Nobody: only I hear them", "off"))
ROUTE_DEVICE = "device:"


class StatusLine(QLabel):
    """The status message under the mixer. Hidden while there's nothing to say, so
    the window doesn't keep an empty row at the bottom, and while the window is too
    short for it (set_room)."""

    room = True

    def __init__(self, *a):
        super().__init__(*a)
        # always rich text: callers pass html.escape()d text, which auto-detection
        # showed as "&#x27;" when it had no tags in it
        self.setTextFormat(Qt.RichText)

    def setText(self, text: str):
        super().setText(text)
        self.setVisible(self.room and bool(text))

    def set_room(self, compact: bool):
        self.room = not compact
        self.setVisible(self.room and bool(self.text()))
        responsive.touch(self)


class BannerButton(QPushButton):
    """A one-line button that never makes the window wider: in less room it shows
    `short`, and in less than that its text is cut with "…". A banner as wide as its
    whole text pushed a ~750 px window into the mini player, banner and all."""

    def __init__(self, text: str, short: str):
        super().__init__(text)
        self._full, self._short = text, short
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setToolTip(text)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        room = self.width() - self.iconSize().width() - 48   # icon, padding, gap
        fm = self.fontMetrics()
        if fm.horizontalAdvance(self._full) <= room:
            text = self._full
        else:
            text = fm.elidedText(self._short, Qt.ElideRight, max(0, room))
        if text != self.text():
            self.setText(text)


class Bridge(QObject):
    loaded = Signal(str, object, str)          # id, data|None, error
    exported = Signal(str, int, str)           # file, sounds written, error
    unpacked = Signal(object, object, str)     # backup.Imported|None, backup.Package, error
    update = Signal(object, str, bool)         # updates.Release|None, error, asked by the user
    update_progress = Signal(int)              # percent of the new version downloaded
    update_ready = Signal(object, str)         # its installer's Path|None, error
    watch_update = Signal(object)              # a newer Onion Watch: watchaddon.Offer
    counted = Signal()                         # the daily usage count was sent (usage.py)
    imported = Signal(object, object, str)     # meta|None, data|None, error/filename
    preview = Signal(str, object, float, int)  # id, audio with unsaved effects|None, gain, gen


def is_hands_free(name: str | None) -> bool:
    """A Bluetooth headset's phone-call mic ("Headset (… Hands-Free AG Audio)")."""
    n = (name or "").lower()
    return "hands-free" in n or "hands free" in n


def _listed(name: str, names) -> bool:
    """`name` (as the app saved it) is one of `names` (Windows' own), spacing aside."""
    squash = " ".join(name.split()).lower()
    return any(" ".join(n.split()).lower() == squash for n in names)


class MainWindow(QMainWindow):
    update_done = Signal(object, str)   # an update check finished: Release|None, error
    mic_attached = Signal(str, str)     # attach_mic finished: the mic, error ("" = done)
    cable_removed = Signal(str)         # remove_cable finished: error ("" = done)
    config_saved = Signal(bool)         # the background save finished: ok
    voice_engine = Signal(object)       # the voice engine of the game in front (a mode key|None)
    default_found = Signal(object)      # Windows' default output, asked on a thread (str|None)
    tab_switched = Signal(str, bool)    # Settings > Tabs: a tab (taboff.KEYS) off / on again
    category_programs_changed = Signal()   # a program -> category rule added / removed

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
            self.cfg.theme = theme.apply(app, self.cfg.theme, self.cfg.live_color)
            self.cfg.live_color = theme.live_override
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
        self.bridge.watch_update.connect(self._on_watch_update)
        self.bridge.counted.connect(self._save_later)   # stats_sent
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
        self.watch_offer: watchaddon.Offer | None = None   # an urgent Onion Watch fix
        self._urgent_hidden: set[str] = set()   # "board 1.9.6" / "watch 0.8.2", this run
        self._preview_gen = 0            # newest effects preview (older renders are dropped)
        self._preview_done = None         # its done(ok) callback while it renders
        self._ptt_held: str | None = None   # PTT key we're currently holding
        self._pending_imports = 0
        self._imported_ok = 0
        self._exporting = False
        self._import_errors: list[str] = []
        # sound id -> the hotkey it had in another soundboard (Import from Soundpad),
        # given to it once it's in if nothing here has that key
        self._import_keys: dict[str, str] = {}
        self._rec_playing = False
        self.current: str | None = None   # sound shown in the transport bar
        self._link_meta: SoundMeta | None = None   # the link bar's Play once
        self.start_frac = 0.0             # where ▶ starts if it isn't playing
        self._seeking = False
        self._tick_n = 0                  # ticks since start (the watchdog runs ~once a second)
        self._ui_live = True              # the window is on screen (see _set_tick_rate)
        self._tick_busy = True            # something moves with the tick (see _busy)
        self._sounds_live = False         # the Sounds tab's live dot is shown
        self._icon_step, self._icon_next = -1, 0.0   # the icons' glow step (_glow_icons)
        self._tray_step = -1              # ...and the tray icon's
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
        # written on a background thread: a slow disk froze the window for seconds
        self._saver = library.Saver(self.cfg, done=self.config_saved.emit)
        self.config_saved.connect(self._on_saved)

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
        self.remote_addons = self._load_remote_addons()
        a11y.label_tree(self, force=True)   # names for the icon-only buttons

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(TICK_MS)
        QApplication.instance().applicationStateChanged.connect(self._set_tick_rate)
        # which voice chat the game you're playing uses: a hint by Who's listening
        self.voice_suggestion: str | None = None
        self.voice_why = ""   # why it's suggested, for the hint ("Discord is listening…")
        self.voice_hints: list[profiles.Hint] = []   # everything seen, for the simple modes
        self.mode_why = ""    # why the simple mode picked the shaping it uses
        self.listeners = voicesdk.Listeners() if sys.platform == "win32" else None
        # who's still set to the cable while sounds go straight into the mic (_cable_tip)
        self._cable_watch = voicesdk.Listeners() if sys.platform == "win32" else None
        self.voice_watch = voicesdk.Watcher() if sys.platform == "win32" else None
        self._voice_timer = QTimer(self)
        self._voice_timer.timeout.connect(self._voice_tick)
        self._voice_at = 0.0   # when _poll_voice last ran (see _voice_tick)
        if self.voice_watch is not None:
            self._voice_timer.start(VOICE_POLL_MS)
        # Switch category when a program is in front: a cheap look at the window in
        # front each second, only while a rule exists (and runs while the board is hidden)
        self.cat_switch = catswitch.Switcher()
        self._cat_timer = QTimer(self, interval=catswitch.POLL_MS)
        self._cat_timer.timeout.connect(self._cat_tick)
        self._update_cat_timer()
        # the headphones follow Windows' default output when it changes
        self._default_timer = QTimer(self)
        self._default_timer.timeout.connect(self._default_tick)
        self._default_timer.timeout.connect(self._recover_devices)
        self._default_at = 0.0   # when Windows' default was last looked at (_default_tick)
        self._default_asking = False   # ...and a thread is asking it now
        self.default_found.connect(self._on_default_found)
        self._recover_n, self._recover_at = 0, 0.0   # see _recover_devices
        self._gone_n = 0   # checks in a row that found the failing device unplugged
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

        # only a sign: the one switch is "Hear what they hear" in the mixer at the bottom
        self.mic_banner = BannerButton("YOU'RE HEARING YOUR MIC OUTPUT  —  mic + sounds, "
                                       "exactly what others hear",
                                       "HEARING YOUR MIC OUTPUT")
        self.mic_banner.setObjectName("micbanner")
        self.mic_banner.setFocusPolicy(Qt.NoFocus)
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

        # an urgent fix (a release whose notes say "Urgent: …", updates.urgent): a bar
        # across the window, not only the small Update pill. Hidden only until next start.
        self.urgent_bar = QFrame()
        self.urgent_bar.setObjectName("urgentbar")
        uh = QHBoxLayout(self.urgent_bar)
        uh.setContentsMargins(12, 6, 6, 6)
        uh.setSpacing(8)
        self.urgent_lbl = QLabel()
        self.urgent_lbl.setTextFormat(Qt.PlainText)   # the reason is release-note text
        self.urgent_lbl.setWordWrap(True)   # never makes the window wider
        uh.addWidget(self.urgent_lbl, 1)
        self.urgent_btn = QPushButton()
        self.urgent_btn.setObjectName("primary")
        self.urgent_btn.clicked.connect(self._urgent_clicked)
        uh.addWidget(self.urgent_btn)
        hide = QPushButton("✕")
        hide.setObjectName("urgenthide")
        hide.setAccessibleName("Hide")
        hide.setToolTip("Hide until Onion Board starts again")
        hide.setFixedSize(28, 28)
        hide.clicked.connect(self._hide_urgent)
        uh.addWidget(hide)
        self.urgent_bar.hide()
        rv.addWidget(self.urgent_bar)

        # ---- tabs
        self.tab_info: dict[str, tuple[str, str]] = {}   # page attr -> (title, text) for ⓘ
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setIconSize(QSize(18, 18))
        self.tabs.tabBar().setUsesScrollButtons(False)   # small windows drop the tab text
        SteadyTabs(self.tabs)   # a change inside a page doesn't repaint the whole board
        rv.addWidget(self.tabs, 1)
        self.sounds_page = self._build_sounds_page()
        self.tabs.addTab(self.sounds_page, "")
        # the Radio tab, or the panel saying it's switched off (Settings > Privacy)
        self.radio_page = QStackedWidget()
        self.radio = self._make_radio()
        self.tabs.addTab(self.radio_page, "")
        # the rest are made by _make_tab: each one or, switched off in Settings > Tabs,
        # a stand-in that loads nothing (ui/taboff.py)
        self.apps = self._make_tab("apps")
        self.tabs.addTab(self.apps, "")
        self.triggers = self._make_tab("triggers")
        self.tabs.addTab(self.triggers, "")
        self.voice = self._make_tab("voice")
        self.tabs.addTab(self.voice, "")
        self.setup_page = self._build_setup_page()
        self.tabs.addTab(self.setup_page, "")
        for i, (text, tip) in enumerate(TABS):
            self.tabs.setTabText(i, text)
            self.tabs.setTabToolTip(i, tip)
            icons.set_tab_icon(self.tabs, i, text.lower())
        for key in taboff.KEYS:
            self.tabs.setTabVisible(TAB_INDEX[key], self.tab_on(key))
        # one ⓘ at the end of the tab bar: the tab's explanation, instead of a banner
        self.btn_info = QPushButton()
        self.btn_info.setObjectName("tabinfo")
        self.btn_info.setFixedSize(32, 32)
        self.btn_info.setAccessibleName("About this tab")
        icons.set_icon(self.btn_info, "info", size=20)
        self.btn_info.setCursor(Qt.PointingHandCursor)
        self.btn_info.setToolTip("What's this tab for?")
        self.btn_info.clicked.connect(self._show_tab_info)
        info_corner = TabInfoCorner(self.tabs, self.btn_info)
        self.tabs.setCornerWidget(info_corner, Qt.TopRightCorner)
        self._update_info_btn = lambda *_: self.btn_info.setVisible(
            self._current_tab_info() is not None)
        self.tabs.currentChanged.connect(self._update_info_btn)
        self._update_info_btn()
        tab = self.cfg.tab if 0 <= self.cfg.tab < self.tabs.count() else 0
        self.tabs.setCurrentIndex(tab if self.tabs.isTabVisible(tab) else 0)
        self.tabs.currentChanged.connect(lambda i: self.set_option("tab", i))
        self.tabs.currentChanged.connect(self._count_tab)   # names only (usage.py)
        self._count_tab(self.tabs.currentIndex())
        self.tabs.currentChanged.connect(lambda _i: self._update_status())
        self.tabs.currentChanged.connect(self._focus_sounds_page)
        # a badge on a tab's icon (or, by default, a wash) in the theme's live colour while
        # its feature is live — the voice changer, a radio station, a program being
        # sent, the screen watched — so it's never left on without you noticing
        set_live_tint(self.tabs, self.cfg.live_tab_green)
        for key in ("voice", "triggers", "apps"):
            self._tab_live(key, getattr(self, key).is_active())
        QTimer.singleShot(TRIGGERS_LOAD_MS, self, self.load_triggers)
        self._radio_live(self.radio.is_active())
        self._search_follow_switch()
        net.on_change(self._follow_switches)

        # ---- mixer strip: the things that apply whatever tab you're on
        rv.addWidget(self._build_mixer())

        self.status = StatusLine()
        self.status.setWordWrap(True)
        self.status.setObjectName("muted")
        self.status.hide()
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
        self.mini_name = ElidedLabel(self.np_name.text(), hide_overflow=True)
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
        self._name_seek.relayout()
        self.mini_name.setText(text)   # hides itself when it has no room

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
                              "Everything going out to others right now (Discord, a game, "
                              "OBS…): your mic plus whatever is live")
        self.out_meter = Meter()
        self.out_meter.setMinimumWidth(60)
        self.out_meter.setToolTip("Level of what others receive (Discord, the game, OBS…)")
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
        # short, so it isn't cut to "Search sounds… …" at normal widths; the tooltip
        # has the rest
        self.search.setPlaceholderText("Search sounds or paste a link")
        self.search.setToolTip("Type to filter your sounds; Enter searches the web (YouTube, "
                               "TikTok, Myinstants…). Or paste a link (YouTube, SoundCloud, "
                               "TikTok, most media sites) to add or play it")
        self.search.setClearButtonEnabled(True)
        # typing regrids only when the pads shown change (35 ms a key with 600 pads),
        # and only once it pauses (_on_search_text); text set by the app filters at once
        self._search_wait = QTimer(self, singleShot=True, interval=SEARCH_WAIT_MS)
        self._search_wait.timeout.connect(
            lambda: self.apply_filter(self.search.text(), lazy=True))
        self._search_typed = None
        self.search.textEdited.connect(self._on_search_edited)
        self.search.textChanged.connect(self._on_search_text)
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
        om = mm.addMenu("Import from another soundboard")
        for src in otherboards.sources():
            om.addAction(f"{src.name}…", lambda src=src: self.import_other(src))
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
        # a drag re-lays every pad at most every PAD_SIZE_WAIT_MS, not on each step
        self._pad_size_wait = QTimer(self, singleShot=True, interval=PAD_SIZE_WAIT_MS)
        self._pad_size_wait.timeout.connect(lambda: self.set_pad_width(size.value()))
        size.valueChanged.connect(lambda _v: self._pad_size_wait.isActive()
                                  or self._pad_size_wait.start())
        no_wheel(size)
        # Who's listening, one click away (the full picker is on the Setup tab)
        from soundboard.ui.destpanel import ModeCombo
        mode_lbl = QLabel("Listening:")
        mode_lbl.setObjectName("muted")
        self.mode_combo = ModeCombo(self)
        tb.addWidget(mode_lbl)
        tb.addWidget(self.mode_combo)
        self._mode_pick = (mode_lbl, self.mode_combo)
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
        # Ctrl+V anywhere on the page (a text box keeps its own): a copied clip from
        # the Apps tab's editor becomes a sound; a copied picture goes on the selected
        # pad (or the picked ones)
        page.setFocusPolicy(Qt.ClickFocus)   # a click on the page's bare parts lands here
        paste = QShortcut(QKeySequence.Paste, page)
        paste.setContext(Qt.WidgetWithChildrenShortcut)
        paste.activated.connect(self.paste_picture)

        # ---- "now playing" chips: shown while 2+ sounds overlap, so every one of
        # them can be stopped (■) or taken into the player (name) without clicking
        # its pad, which would restart it
        self.playing_row = QWidget()
        # wraps onto more lines: one line of four overlapping sounds' chips (~900 px)
        # turned a narrower window into the mini player, and every playing sound must
        # stay reachable, so none are left out
        self._chips_hl = Flow(self.playing_row, gap=6)
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
        # the row's height, set by its buttons; its width follows the text inside
        # NameAndSeek, which never asks the page for a new layout (the name changes
        # with every pad press, and a relayout repainted every pad on the board)
        self.np_name.setFixedHeight(34)
        self.np_name.setStyleSheet("font-weight:600;")
        self.seek = SeekSlider(Qt.Horizontal)
        self.seek.setRange(0, 1000)
        self.seek.setObjectName("seek")
        self.seek.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.seek.sliderReleased.connect(self.do_seek)
        self.seek.valueChanged.connect(self._seek_preview)
        no_wheel(self.seek)
        self.np_time = QLabel("0:00 / 0:00")
        # room for a long sound's "75:12 / 112:40" in this font (84 px cut it, and
        # "12:34 / 45:67" too in the Consolas themes)
        self.np_time.setFixedWidth(
            self.np_time.fontMetrics().horizontalAdvance("888:88 / 888:88") + 4)
        self.np_time.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.np_time.setObjectName("muted")
        th.addWidget(self.btn_pp)
        th.addWidget(self.btn_st)
        self._name_seek = NameAndSeek(self.np_name, self.seek, 190)
        th.addWidget(self._name_seek, 1)
        th.addWidget(self.np_time)
        # only for a pad made from a video (soundboard.videos): shows it in step
        self.btn_video = QPushButton("Video")
        self.btn_video.setToolTip("Watch this sound's video while it plays. The sound "
                                  "still goes out as normal; the video is only for you.")
        icons.set_icon(self.btn_video, "video", size=16)
        self.btn_video.clicked.connect(self.show_video)
        self.btn_video.hide()
        self._video_for: tuple[str | None, Path | None] = ("", None)   # (sid, its video)
        self._video_win = None   # ui/videowindow.VideoWindow, made on first use
        th.addWidget(self.btn_video)
        self.speed_btn = SpeedPitchButton(
            "sounds", "Changes every sound while it plays. To save a version, "
                      "right-click a pad → Effects.")
        self.speed_btn.changed.connect(self.on_live_speed)
        self.speed_btn.fx_changed.connect(lambda fx: setattr(self.engine, "sound_fx", fx))
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
        and the queue, each with its own ✕. A web search / link's Play once counts
        too: it isn't a pad, but it plays over them and needs its own ■. So does one
        lone sound the player isn't showing (another pad was picked while it played):
        its chip is the only way back to it."""
        ids = tuple(s for s in self.pads if s in playing)
        if LINK_ID in playing:
            ids += (LINK_ID,)
        queue = tuple(self._queue)
        lone = len(ids) == 1 and self.current not in (None, ids[0])
        if (ids, queue, lone) != self._chip_ids:
            self._chip_ids = (ids, queue, lone)
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
            if len(ids) >= 2 or lone:
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
                    name = QPushButton(chip.fontMetrics().elidedText(   # && : "R&B" not "RB"
                        m.name if m else sid, Qt.ElideRight, 150).replace("&", "&&"))
                    name.setObjectName("chipname")
                    name.setToolTip("Show this sound in the player (keeps playing)")
                    name.clicked.connect(lambda _=False, s=sid: self.select(s))
                    stop = QPushButton()
                    stop.setObjectName("chipstop")
                    stop.setToolTip("Stop this sound")
                    icons.set_icon(stop, "stop", "danger_text", size=12)
                    stop.setFixedSize(24, 24)
                    stop.clicked.connect(lambda _=False, s=sid: self._stop_sound(s))
                    ch.addWidget(name)
                    ch.addWidget(stop)
                    self._chips_hl.addWidget(chip)
                    self._chips[sid] = chip
            # at least a line high, taller when the chips wrap (the Flow's height for
            # its width); a row that shrank and grew back with every overlapping
            # sound resized and repainted the whole board under it
            self.playing_row.setMinimumHeight(CHIPS_ROW_H)
            self.playing_row.setVisible(len(ids) >= 2 or bool(queue) or lone)
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
        name = QPushButton(chip.fontMetrics().elidedText(text, Qt.ElideRight, 150)
                           .replace("&", "&&"))   # "R&B", not "RB" with a shortcut
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
        cols.setContentsMargins(4, 12, 8, 12)
        cols.setSpacing(16)
        lcol, rcol = QVBoxLayout(), QVBoxLayout()
        for col in (lcol, rcol):
            col.setSpacing(16)
            cols.addLayout(col, 1)
        page.setWidget(inner)

        # ---- how it works + the one thing to set in Discord
        howcard, cv = card("YOUR VIRTUAL MIC", roomy=True)
        self.how_title = cv.itemAt(0).widget()   # renamed when not using the cable
        self.flow_mic = QLabel()
        self.flow_snd = QLabel("Your sounds, radio and voice effects")
        arrow = QLabel("↓   the app mixes them together")
        arrow.setObjectName("muted")
        self.flow_out = QLabel()
        for ic, w in (("mic", self.flow_mic), ("volume", self.flow_snd), ("", arrow),
                      ("live", self.flow_out)):   # mic or cable alike
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
        self.btn_install.clicked.connect(
            lambda: self.attach_mic() if self.cfg.route == "mic" else self.install_cable())
        self.btn_attach = QPushButton("Straight into my mic instead (no cable)")
        self.btn_attach.setToolTip("Onion Board puts your sounds into your real mic, so "
                                   "Discord and games need no virtual cable and nothing "
                                   "picked")
        self.btn_attach.clicked.connect(self.attach_mic)
        icons.set_icon(self.btn_attach, "mic")
        self.btn_attach.hide()
        cv.addWidget(self.btn_attach)
        self.btn_usecable = QPushButton("Use the virtual cable instead")
        self.btn_usecable.setToolTip("The other way to reach Discord and games: a free "
                                     "virtual cable you pick as the mic there")
        self.btn_usecable.clicked.connect(self.use_cable_instead)
        icons.set_icon(self.btn_usecable, "cable")
        self.btn_usecable.hide()
        self.mic_attached.connect(self._mic_attached)
        self._attaching = False
        self._attach_release = None   # busy.hold on btn_install while it's being set up
        self._settle_until = 0.0      # just set up: Windows is still loading it
        icons.set_icon(self.btn_install, "cable", "on_accent")
        cv.addWidget(self.btn_install)
        cv.addWidget(self.btn_usecable)   # (under the mic's own button: the second way)
        # straight into the mic works: the cable is only a fallback, so offer to remove it
        self.btn_rmcable = QPushButton("Remove the virtual cable")
        self.btn_rmcable.setToolTip("Uninstalls VB-Cable. Your sounds go straight into "
                                    "your mic, so Onion Board doesn't need it")
        icons.set_icon(self.btn_rmcable, "cable")
        self.btn_rmcable.clicked.connect(self.remove_cable)
        self.btn_rmcable.hide()
        self.cable_removed.connect(self._cable_removed)
        self._cable_gone = False   # removed this session (Windows lists it till a restart)
        self.rmcable_note = hint_label(
            "<b>You don't need the virtual cable any more</b> — it was only the backup. "
            "Remove it, or keep it if another program uses it (Voicemeeter, another "
            "soundboard).")
        self.rmcable_note.setTextFormat(Qt.RichText)
        self.rmcable_note.hide()
        cv.addWidget(self.rmcable_note)
        cv.addWidget(self.btn_rmcable, 0, Qt.AlignLeft)
        self.btn_rescan = QPushButton("I've installed it — check again")
        self.btn_rescan.clicked.connect(lambda: self.rescan_with_feedback(self.btn_rescan))
        icons.set_icon(self.btn_rescan, "reload")
        cv.addWidget(self.btn_rescan)
        helpcard, hv = card("CONNECT YOUR CHAT",
                            "Choose your app for the recommended microphone settings.", roomy=True)
        self.btn_chat = QPushButton("Make it sound clean in Discord")
        self.btn_chat.setToolTip("The Discord settings that stop it chopping up your sounds, "
                                 "and a check that listens to what Discord does to them")
        icons.set_icon(self.btn_chat, "headphones")
        self.btn_chat.clicked.connect(lambda: self.show_chat_guide("discord"))
        hv.addWidget(self.btn_chat)
        self.btn_game = QPushButton("Set up game voice chat")
        self.btn_game.clicked.connect(lambda: self.show_chat_guide("game"))
        hv.addWidget(self.btn_game)
        self.btn_meeting = QPushButton("Zoom, Teams or a browser call")
        self.btn_meeting.setToolTip("The settings in Zoom, Microsoft Teams and calls in a "
                                    "web page that stop them treating your sounds as noise")
        self.btn_meeting.clicked.connect(lambda: self.show_chat_guide("meeting"))
        hv.addWidget(self.btn_meeting)
        self.btn_nomic = QPushButton("Game has no microphone setting?")
        self.btn_nomic.clicked.connect(self.open_windows_mic)
        hv.addWidget(self.btn_nomic)
        guide = QPushButton("Step-by-step guide")
        guide.setToolTip("Walks you through mic, headphones, where your sounds go "
                        "(your mic, the cable, another device or nowhere) and Discord")
        icons.set_icon(guide, "check")
        guide.clicked.connect(self.run_setup)
        hv.addWidget(guide)
        lcol.addWidget(howcard)
        lcol.addWidget(helpcard)

        # ---- devices
        devcard, av = card("DEVICES", "Already set up for you — only change these if "
                                      "something's wrong.", roomy=True)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(12)
        self.cb_main, self.cb_mon, self.cb_mic = QComboBox(), QComboBox(), QComboBox()
        # your mic (the normal way), nobody, or a device by name (set_route). cb_main
        # isn't shown: it keeps the device list the picked device is checked against.
        self.cb_route = QComboBox()
        self.cb_route.setToolTip("Normally your sounds go into your mic, so everyone who "
                                 "hears your mic hears them. Only pick something else to "
                                 "send them somewhere instead: Voicemeeter, a mixer, a "
                                 "device OBS captures, or a virtual cable.")
        for r, (ic, text, cb) in enumerate((
                ("headphones", "My headphones", self.cb_mon),
                ("mic", "My mic", self.cb_mic),
                ("live", SEND_TO, self.cb_route))):
            row = (icon_label(ic), QLabel(text), cb)
            row[1].setBuddy(cb)   # a screen reader reads the label as the box's name
            for col, w in enumerate(row):
                grid.addWidget(w, r, col)
            cb.setMinimumWidth(120)
            # sized for a short name, not the longest device ("Headphones (2- Arctis Nova
            # Pro Wireless Game)" gave the Setup tab a sideways scroll bar); the list
            # opens wide enough for whole names
            cb.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(16)
        grid.setColumnStretch(2, 1)
        av.addLayout(grid)
        self.cb_main.setParent(devcard)   # never a window of its own
        self.cb_main.hide()
        # more places at once (streamers): a row per extra device, + and − (alsosend)
        self.also_views = []
        self.also_rows = alsosend.build(self, grid, 3, icons_col=True)
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
        no_wheel(self.cb_main, self.cb_mon, self.cb_mic, self.cb_route)
        for cb, attr in ((self.cb_main, "main_device"), (self.cb_mon, "mon_device"),
                         (self.cb_mic, "mic_device"), (self.cb_route, "route")):
            cb.activated.connect(lambda _i, cb=cb, attr=attr: self.on_device(cb, attr))
        ref = QPushButton("Re-scan devices")
        icons.set_icon(ref, "reload")
        ref.clicked.connect(lambda: self.rescan_with_feedback(ref))
        av.addWidget(ref, 0, Qt.AlignLeft)
        lcol.addWidget(devcard)

        # ---- who's listening: shape the sounds for the voice chat on the other end
        destcard, dv = card("WHO'S LISTENING", "Where people hear you: a game, a voice "
                                               "chat app, or a stream. Your sounds are "
                                               "shaped to come through clearly.", roomy=True)
        from soundboard.ui.destpanel import DestPanel
        self.dest_panel = DestPanel(self)
        dv.addWidget(self.dest_panel)
        lcol.addStretch(1)

        # ---- test
        testcard, tv = card("TEST IT", "Talk while a sound plays. Records what goes out to "
                                       "others (what Discord, the game or OBS receives), plays "
                                       "it back, and tells you if your voice + sounds are in "
                                       "it.", roomy=True)
        self.btn_rec = QPushButton("Record 6s → play back")
        self.btn_rec.setObjectName("primary")
        icons.set_icon(self.btn_rec, "record", "on_accent")
        self.btn_rec.clicked.connect(self.start_test)
        tv.addWidget(self.btn_rec)
        tv.addWidget(hint_label("To hear it live instead, use Hear what they hear at the "
                                "bottom."))
        self.test_result = QLabel()
        self.test_result.setWordWrap(True)
        self.test_result.setTextFormat(Qt.RichText)
        self.test_result.setObjectName("resultbox")
        self.test_result.hide()
        tv.addWidget(self.test_result)
        rcol.addWidget(testcard)

        # ---- sound shaping
        eqcard, ev = card(roomy=True)
        self.eq = EqPanel(c.eq_enabled, c.eq_target, c.eq_preset, c.eq_gains)
        self.eq.changed.connect(self.on_eq)
        ev.addWidget(self.eq)
        rcol.addWidget(eqcard)
        rcol.addWidget(destcard)
        utilitycard, uv = card("VOLUME & SHORTCUTS", roomy=True)
        self.chk_level = QCheckBox("Level volumes (all sounds equally loud)")
        self.chk_level.setChecked(c.level_volumes)
        self.chk_level.toggled.connect(self.on_level_toggle)
        uv.addWidget(self.chk_level)
        hk = QPushButton("Hotkeys && auto push-to-talk…")
        hk.setToolTip("Opens Settings → Hotkeys")
        hk.clicked.connect(lambda: self.open_settings("hotkeys"))
        uv.addWidget(hk, 0, Qt.AlignLeft)
        rcol.addWidget(utilitycard)
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
        if self.cfg.route == "cable" and not any(is_virtual_cable(d["name"]) for d in outs):
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
        # only the cable route picks the cable for you: another device stays the one
        # picked by hand, even while it's unplugged (it's retried until it's back)
        if c.route == "cable" and (not c.main_device
                                   or eng.find_device("output", c.main_device) is None):
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
        self._show_route()

        e = self.engine
        e.sound_vol, e.mic_vol, e.mon_vol = c.sound_vol, c.mic_vol, c.mon_vol
        e.mic_enabled, e.monitor_sounds = c.mic_enabled, c.monitor_sounds
        e.obs_vol, e.obs_voice = c.obs_vol, c.obs_voice
        e.set_mic_device(c.mic_device)
        e.set_main_device(self._main_name())
        e.set_tap_device(self._tap_name())
        e.set_mon_device(c.mon_device)
        e.set_obs_device(self._obs_name(c.obs_device))
        e.set_copy_devices(self._copy_names())
        self._check_cable_format()
        self._update_status()

    def _default_output(self) -> str | None:
        """Windows' default output as the device lists name it (None: unknown, or the
        cable, which is never the headphones)."""
        idx = eng.find_device("output", self._default_out)
        name = eng.list_name(idx) if idx is not None else None
        return None if name is None or is_virtual_cable(name) else name

    def _recover_devices(self):
        """A device the app uses won't open, but Windows lists it: PortAudio's device
        list is out of date (it was plugged in after the last scan, or its format was
        changed in Windows' sound settings), and the engine's retries can't fix that.
        Re-scan, waiting longer each time it doesn't help (RECOVER_WAIT_S)."""
        e = self.engine
        failing = [(k, e.names[k]) for k in ("main", "mon", "mic", "obs")
                   if e.names.get(k) and getattr(e, f"{k}_stream") is None
                   and k in e.errors_snapshot()]
        if not failing:
            self._recover_n = self._gone_n = 0
            return
        now = time.monotonic()
        if now < self._recover_at:
            return
        listed: dict[str, set[str] | None] = {}
        for key, name in failing:
            kind = "input" if key == "mic" else "output"
            if kind not in listed:
                listed[kind] = appaudio.endpoint_names(kind)
            if _listed(name, listed[kind] or ()):
                break
        else:
            # really gone (unplugged): the engine's retries pick it up again. Asking
            # Windows for its device list every check while it stays unplugged is
            # wasted work, so after a few checks look less often
            self._gone_n += 1
            if self._gone_n >= GONE_CHECKS:
                self._recover_at = now + GONE_WAIT_S
            return
        self._gone_n = 0
        self._recover_at = now + RECOVER_WAIT_S[min(self._recover_n, len(RECOVER_WAIT_S) - 1)]
        self._recover_n += 1
        log.info("%s device %r is listed by Windows but won't open: re-scanning", key, name)
        self.refresh_devices()

    def _default_tick(self):
        """The timer's look at Windows' default output (a COM call): only while the
        headphones follow it, as nothing else uses the answer (picking a device by hand
        looks again), and every few seconds rather than constantly while the window is
        in the tray or minimised. Asked on a thread (it took ~5 ms of the UI thread every
        1.5 s); the answer comes back through default_found."""
        if not self.cfg.mon_follows_default or self._default_asking:
            return
        now = time.monotonic()
        if not self._ui_live and now - self._default_at < DEFAULT_POLL_IDLE_S:
            return
        self._default_at = now
        self._default_asking = True
        threading.Thread(target=self._ask_default, daemon=True, name="default-output").start()

    def _ask_default(self):
        try:
            name = appaudio.default_output_name()
        except Exception:  # noqa: BLE001 - never let the poll's thread die loudly
            log.debug("asking for Windows' default output failed", exc_info=True)
            name = None
        try:
            self.default_found.emit(name)
        except RuntimeError:   # the window is gone (quitting)
            pass

    def _on_default_found(self, name):
        self._default_asking = False
        if self.cfg.mon_follows_default:   # not picked by hand meanwhile
            self._follow_default_output(name)

    def _follow_default_output(self, *found: str | None):
        """Windows' default output changed (headphones → speakers): the headphones
        output moves with it, unless another device was picked for it by hand.
        `found`: its name, already asked (on a thread); asked now if not given."""
        now = found[0] if found else appaudio.default_output_name()
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
        self._apply_send_outputs()
        self._save_now()
        self._update_status()
        self.status.setText(f"You hear your sounds on {html.escape(name)} now: it's "
                            "Windows' default output.")

    def _check_cable_format(self):
        """Note which ends of the cable in use aren't at 48 kHz (shown on the Setup tab)."""
        from soundboard import cableformat
        main = self._main_name()
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
        cb.view().setMinimumWidth(cb.view().sizeHintForColumn(0) + 32)   # whole names
        cb.blockSignals(False)

    def on_device(self, cb, attr):
        name = cb.currentData()
        if attr == "route":
            if name and name.startswith(ROUTE_DEVICE):   # a device by name
                dev = name[len(ROUTE_DEVICE):] or None
                self.set_route("cable" if dev is None or is_virtual_cable(dev) else "device",
                               dev)
            else:
                self.set_route(name)
            return
        setattr(self.cfg, attr, name)
        if attr == "mon_device":
            self.engine.set_mon_device(name)
            # picking Windows' default keeps following it; anything else stays put
            if not self.cfg.mon_follows_default:   # not looked at while not following
                self._default_out = appaudio.default_output_name() or self._default_out
            self.cfg.mon_follows_default = name is not None and name == self._default_output()
        elif attr == "mic_device":
            self.engine.set_mic_device(name)
            if self.cfg.route == "mic" and directmic.status(name) == "other":
                self.attach_mic()   # it follows you to the new mic
        self._apply_send_outputs(force_main=attr == "main_device")
        self._save_now()
        if attr == "mon_device":
            self._show_route()   # the headphones aren't offered as where sounds go
        self._update_status()
        if attr == "mic_device" and is_hands_free(name):   # after: it'd be overwritten
            self.status.setText(
                f"<span style='color:{theme.status('warn')}'>That's a Bluetooth headset's "
                "phone-call mic: while it's open, Windows switches the headset to call "
                "quality, so everything you hear sounds muffled. A wired mic, or the "
                "headset's own USB dongle, sounds much better.</span>")
        self._prepare_all()

    def set_route(self, route: str, device: str | None = None):
        """Setup -> Devices -> Send my sounds to: your mic, the virtual cable, another
        device (Voicemeeter, a mixer, a device OBS captures) or nobody (only you, and the
        stream output). `device`: send into that one too (the picker and the setup guide
        pick both at once). Otherwise the picked device is kept, so switching back
        restores it."""
        c = self.cfg
        if route not in library.ROUTES or (route == c.route and device is None):
            self._show_route()
            return
        if route == "mic" and directmic.status(c.mic_device) != "ready":
            self._show_route()   # not attached yet: the picker stays put until it is
            self.attach_mic()
            return
        log.info("send to others through: %s -> %s (%s)", c.route, route,
                 device or c.main_device)
        c.route = route
        if device is not None:
            c.main_device = device
        elif route == "cable" and not is_virtual_cable(c.main_device):
            c.main_device = next(iter(eng.virtual_outputs()), None) or c.main_device
        self._fill_combo(self.cb_main, [d["name"] for d in eng.list_devices("output")],
                         c.main_device)
        self._show_route()
        self._apply_send_outputs(force_main=True)
        self._save_now()
        self._update_status()
        self._prepare_all()

    def _show_route(self):
        """The Setup tab follows the route: "Send my sounds to" lists your mic, nobody
        and every output but the headphones, with the current one picked."""
        c, cb = self.cfg, self.cb_route
        route = c.route
        cb.blockSignals(True)
        cb.clear()
        for text, key in ROUTE_CHOICES:
            cb.addItem(text, key)
        names = [d["name"] for d in eng.list_devices("output")]
        target = c.main_device if route in ("cable", "device") else None
        if route in ("cable", "device") and target not in names:
            names.append(target)   # unplugged, or no cable yet: still shown as picked
        for n in names:
            if n is None:
                cb.addItem("A virtual cable (not installed yet)", ROUTE_DEVICE)
            elif n != c.mon_device or n == target:
                cb.addItem(n, ROUTE_DEVICE + n)
        key = route if route in ("mic", "off") else ROUTE_DEVICE + (target or "")
        cb.setCurrentIndex(max(0, cb.findData(key)))
        cb.view().setMinimumWidth(cb.view().sizeHintForColumn(0) + 32)   # whole names
        cb.blockSignals(False)
        for v in list(getattr(self, "also_views", ())):   # (not built yet at start)
            v.rebuild()
        self.how_title.setText("YOUR VIRTUAL MIC" if route == "cable" else
                               "YOUR MIC" if route == "mic" else "WHERE YOUR SOUNDS GO")

    def _main_name(self) -> str | None:
        """The device that gets what others hear: none when sending nowhere, and
        never the headphones (you'd hear everything twice, your own voice included)."""
        c = self.cfg
        if c.route == "mic":
            if directmic.works(directmic.status()):
                return directmic.DEVICE
            # not on the mic yet (or Windows took it off): the cable meanwhile, so
            # a voice app set to it still hears you
            cable = self._cable_out()
            return cable if cable != c.mon_device else None
        if c.route == "off" or not c.main_device or c.main_device == c.mon_device:
            return None
        return c.main_device

    def _cable_out(self) -> str | None:
        """The virtual cable's input (what plays into it): the one picked, else the
        first one installed. None once removed (Windows lists it till a restart)."""
        c = self.cfg
        if getattr(self, "_cable_gone", False):
            return None
        if c.main_device and is_virtual_cable(c.main_device):
            return c.main_device
        return next(iter(eng.virtual_outputs()), None)

    def _apply_send_outputs(self, force_main: bool = False):
        """(Re)open what others hear and the stream output for the current devices and
        route. Each is reopened only if its device changed (or `force_main`)."""
        e = self.engine
        main = self._main_name()
        if force_main or e.names["main"] != main:
            e.set_main_device(main)
            self._check_cable_format()
        tap = self._tap_name()
        if e.tap_name != tap:
            e.set_tap_device(tap)
        obs = self._obs_name(self.cfg.obs_device)   # never the cable or headphones too
        if e.names["obs"] != obs:
            e.set_obs_device(obs)
        copies = self._copy_names()
        if list(e.copy_names) != copies:
            e.set_copy_devices(copies)

    def _copy_names(self) -> list[str]:
        """Setup -> Devices -> Also send to: the devices that get a copy of what others
        hear. None while sending to nobody; never the headphones (you'd hear it twice),
        and never a device that gets it already (what others hear, the cable alongside
        the mic, the stream output, or another end of one of those cables)."""
        c = self.cfg
        if c.route == "off":
            return []
        taken = self.sending_to()
        out = []
        for n in c.also_send:
            if (isinstance(n, str) and n and n != c.mon_device and n not in out
                    and not any(n == t or eng.same_cable(n, t) for t in taken)):
                out.append(n)
        return out

    def sending_to(self) -> list[str]:
        """The devices that get what others hear already: the picked one, the cable
        alongside the mic, and the stream output ("Also send to" can't add them again)."""
        return [t for t in (self._main_name(), self._tap_name(),
                            self._obs_name(self.cfg.obs_device)) if t]

    def set_also_send_at(self, i: int, name: str | None):
        """Setup -> Devices -> Also send to: row `i` sends to `name` (one past the last
        row adds one; None removes that row)."""
        c = self.cfg
        lst = list(c.also_send)
        if name is None:
            if i < len(lst):
                del lst[i]
        elif i < len(lst):
            lst[i] = name
        else:
            lst.append(name)
        c.also_send = list(dict.fromkeys(lst))
        log.info("also send to: %s", c.also_send)
        self._apply_send_outputs()
        self._show_route()
        self._save_now()
        self._update_status()

    def _tap_name(self) -> str | None:
        """Straight into the mic: the cable gets the same (engine.CableTap), for a voice
        app still set to it. None otherwise, or if the cable is the headphones."""
        if self._main_name() != directmic.DEVICE:
            return None
        tap = self._cable_out()
        return None if tap == self.cfg.mon_device else tap

    def _obs_name(self, name: str | None) -> str | None:
        """The stream output's device, unless it's what others hear (or another end of
        the same cable: everyone in the call would get everything twice) or the
        headphones (you'd hear it twice). Sending nowhere frees the cable for it."""
        main = self._main_name()
        if (name in (None, main, self.cfg.mon_device)
                or eng.same_cable(name, main) or eng.same_cable(name, self._tap_name())):
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
        c = self.cfg
        main = self._main_name() or ""
        self.virtual_mic = eng.virtual_mic_for(main)
        if c.route == "off":
            self.setup_hint.setText("Sending to others is off: your sounds play in your "
                                    "headphones and on the stream output (Settings → "
                                    "Audio) only.")
        elif c.route == "device" and c.main_device and c.main_device == c.mon_device:
            self.setup_hint.setText(f"<span style='color:{theme.status('warn')}'>"
                                    "That's your headphones too, so nothing is sent "
                                    "(you'd hear everything twice). Pick another device, "
                                    "or pick <b>Nobody</b>: your sounds already play in "
                                    "your headphones, where OBS's Desktop Audio picks "
                                    "them up.</span>")
        elif c.route == "mic":
            self.setup_hint.setText("Your sounds go straight into <b>My mic</b>, so "
                                    "Discord and games hear them through the mic they "
                                    "already use.")
        elif self.virtual_mic:
            hint = (f"A virtual cable is a pipe: audio goes in at <b>{main}</b> "
                    f"and comes out at <b>{self.virtual_mic}</b>, which Discord "
                    "/ the game uses as your mic.")
            if self.cable_bad:
                rates = " and ".join(f"{x.rate / 1000:g} kHz" for x in self.cable_bad)
                hint += (f"<br><span style='color:{theme.status('warn')}'>One end of the "
                         f"cable is on {rates}, so it converts your sound on the way "
                         "through. Fix it for the cleanest sound.</span>")
            self.setup_hint.setText(hint)
        elif main and c.route == "device":
            self.setup_hint.setText(f"Whatever listens to <b>{html.escape(main)}</b> gets "
                                    "your sounds (and your voice, if you send it): OBS, "
                                    "Voicemeeter, a mixer or a capture card.")
        elif main:
            self.setup_hint.setText(f"<span style='color:{theme.status('warn')}'>"
                                    "That's a normal speaker/headphone "
                                    "device, so only you will hear the sounds. Set <b>Send "
                                    "my sounds to</b> back to <b>My mic</b>, unless that's "
                                    "on purpose.</span>")
        else:
            self.setup_hint.setText(f"<span style='color:{theme.status('warn')}'>"
                                    "Nothing picked — only you "
                                    "will hear sounds.</span>")
        down = [n for n in self.engine.copies_down() if n in self._copy_names()]
        if down:
            self.setup_hint.setText(
                self.setup_hint.text() + f"<br><span style='color:{theme.status('warn')}'>"
                "Can't open " + ", ".join(f"<b>{html.escape(n)}</b>" for n in down)
                + " (under Also send to). Plugged in? It's tried again by itself.</span>")
        self.set_sending(self.btn_air.isChecked())   # its label follows the route
        self._update_flow()
        errs = [f"{'stream output' if k == 'obs' else k}: {v}"
                for k, v in e.errors_snapshot().items()]
        if errs:
            self.status.setText(f"<span style='color:{theme.status('error')}'>"
                                "Audio device problem — "
                                + html.escape(" · ".join(errs)) + "</span>")
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
        route = self.cfg.route
        dev = self._main_name()
        any_cable = bool(eng.virtual_outputs())
        direct = directmic.status(self.cfg.mic_device) if route == "mic" else ""
        warn = theme.status("warn")
        # just set up: until Windows has it running, say so (not "Repair" straight away)
        settling = (route == "mic" and not self._attaching
                    and time.monotonic() < self._settle_until)
        if route == "mic" and self._attaching:
            state = "missing"
            out = "Into your mic  <b>setting up…</b>"
            step = ("Click <b>Yes</b> when Windows asks for permission. Your PC's sound "
                    "drops out for a second while Windows reloads it.")
        elif settling and not (e.main_stream is not None and directmic.works(direct)
                               and e.effect_alive()):
            state = "missing"
            out = "Into your mic  <b>starting…</b>"
            step = ("Windows is reloading your sound with Onion Board on your mic. This "
                    "takes a few seconds.")
        elif route == "mic" and directmic.needs_repair(direct):
            state = "missing"
            out = f"Into your mic  <b style='color:{bad}'>✗ needs a quick repair</b>"
            step = (f"<b style='color:{warn}'>One click:</b> Windows took Onion Board off "
                    "your mic (a driver or Windows update does that). Windows asks for "
                    "permission once, and your sounds are back in your mic.")
        elif route == "mic" and not directmic.works(direct):
            state = "missing"
            out = (f"Into your mic  <b style='color:{warn}'>one click to go</b>"
                   if direct == "missing" else
                   f"Into your mic  <b style='color:{warn}'>set up on another mic</b>")
            step = (f"<b style='color:{warn}'>One click:</b> put your sounds straight into "
                    "your mic. Windows asks for permission once; after that Discord and "
                    "games hear them through your normal mic, with nothing to set there.")
        elif route == "mic" and e.main_stream is not None and self._direct_not_running():
            state = "unrouted"
            out = (f"Into your mic  <b style='color:{bad}'>✗ Windows isn't running "
                   "Onion Board on it</b>")
            step = ("Another app may have your mic to itself (an <b>exclusive mode</b> "
                    "setting), or Windows hasn't loaded Onion Board on it. Repair it below, "
                    "or send through the virtual cable instead.")
        elif route == "mic" and e.main_stream is not None:
            state = "ok"
            name = html.escape(self.cfg.mic_device or "your mic")
            apps = e.direct_apps()
            out = (f"<b style='color:{ok}'>{name}</b> — your sounds are in it "
                   f"<b style='color:{ok}'>✓</b>"
                   + (f"  <b style='color:{ok}'>(live)</b>" if apps else ""))
            step = ("<b>Nothing to set.</b> Discord and games keep your normal mic, and "
                    "your sounds are in it. If sounds get chopped up, switch off the "
                    "voice app's noise suppression (Discord: <b>Input Profile → Studio</b>)."
                    + ("<br><br><b>Optional:</b> your mic part works, and a newer "
                       "version is here. It's not needed — update below whenever suits "
                       "you (Windows asks once, and your sound drops out for a second)."
                       if direct == "outdated" else ""))
        elif route == "mic":
            state = "unrouted"
            out = f"Into your mic  <b style='color:{bad}'>✗ can't reach it</b>"
            err = html.escape(e.errors_snapshot().get("main", ""))
            step = ((f"{err}. " if err else "Something went wrong sending into your mic. ")
                    + "Repair it below, or send through the virtual cable instead.")
        elif route == "off":
            state = "off"
            out = "Sent to others  <b>nowhere (your choice)</b>"
            step = ("<b>Nothing goes out as a mic</b>, so Discord and games don't hear your "
                    "sounds. They play in your headphones (OBS's <b>Desktop Audio</b> picks "
                    "them up there) and on the <b>stream output</b> if you set one "
                    "(Settings → Audio). To send them out, set <b>Send my sounds to</b> "
                    "back to <b>My mic</b> under Devices.")
        elif route == "device" and dev and e.main_stream is not None and not vm:
            state = "ok"
            name = html.escape(dev)
            out = f"<b style='color:{ok}'>{name}</b> — sending <b style='color:{ok}'>✓</b>"
            step = (f"<b>Your sounds go to {name}.</b> Whatever listens there gets them. "
                    "In OBS: Sources → + → <b>Audio Output Capture</b> → "
                    f"<b>{name}</b>. In Voicemeeter or a mixer, send that input on "
                    "to wherever it should go. Not going on to a voice chat? Untick "
                    "<b>Send in mono</b> under Who's listening to keep it stereo.")
        elif route == "device" and not (dev and e.main_stream is not None):
            state = "unrouted"
            if self.cfg.main_device and dev is None:
                out = f"Sending  <b style='color:{bad}'>✗ same device as your headphones</b>"
            elif dev:
                out = f"Sending  <b style='color:{bad}'>✗ can't open {html.escape(dev)}</b>"
            else:
                out = f"Sending  <b style='color:{bad}'>✗ no device picked</b>"
            almost = f"<b style='color:{theme.status('warn')}'>Almost:</b> under <b>Devices</b>, "
            step = almost + (
                "set <b>Send my sounds to</b> to another device than your headphones, or "
                "to <b>My mic</b>." if self.cfg.main_device and dev is None
                else "set <b>Send my sounds to</b> to the device that should get your "
                "sounds (and check it's plugged in), or to <b>My mic</b>.")
        elif route == "device":   # another virtual cable: its other end is the mic
            state = "ok"
            out = (f"<b style='color:{ok}'>{vm}</b> — your new mic "
                   f"<b style='color:{ok}'>✓ working</b>")
            step = (f"<b>The only thing you set:</b> in Discord, your game or OBS, pick "
                    f"<b style='color:{ok}'>{vm}</b> as the <b>microphone</b> / audio input.")
        elif not any_cable:
            state = "missing"
            out = f"Virtual mic  <b style='color:{bad}'>✗ not installed yet</b>"
            step = (f"<b style='color:{theme.status('warn')}'>"
                    "One-time setup:</b> install the free virtual "
                    "cable. It's what lets Discord and games hear your sounds — without it, "
                    "only you can hear them. Easier: set <b>Send my sounds to</b> to "
                    "<b>My mic</b> (nothing to install). Voicemeeter, a mixer or OBS? Pick "
                    "that device there.")
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
                    "<b>Send my sounds to</b> to your virtual cable, or to <b>My mic</b>.")
        self.flow_mic.setText(mic)
        self.flow_out.setText(out)
        self.step_lbl.setText(step)
        update = route == "mic" and state == "ok" and direct == "outdated"
        # setting up, or Windows still loading it: the button stays "Setting up…" and
        # takes no clicks (attach_mic holds it) until it works or the wait is over
        mic_busy = route == "mic" and (self._attaching or (settling and state != "ok"))
        if self._attach_release is not None and not mic_busy:
            release, self._attach_release = self._attach_release, None
            release()
        self.btn_install.setVisible(state == "missing" or update
                                    or (route == "mic" and state != "ok"))
        if not busy.is_busy(self.btn_install):
            self.btn_install.setText(
                "Install the free virtual cable" if route != "mic" else
                "Optional: update the mic part" if update else
                "Put my sounds straight into my mic" if direct in ("missing", "other") else
                "Repair (one click)")
            icons.set_icon(self.btn_install, "mic" if route == "mic" else "cable",
                           "on_accent")
        # the mic is the main way: on the cable route the cable's button comes second
        self._set_primary(self.btn_install, route == "mic" and not update)   # (optional)
        self._set_primary(self.btn_attach, route == "cable")
        self.btn_usecable.setVisible(route == "mic" and state != "ok" and not mic_busy)
        spare = route == "mic" and state == "ok" and self._spare_cable()
        self.btn_rmcable.setVisible(spare)
        self.rmcable_note.setVisible(spare)
        if route == "mic":
            self._direct_shown = self._direct_health()
        self._cable_follow_switch()
        self.btn_rescan.setVisible(state == "missing" and route != "mic")
        self.btn_attach.setVisible(route == "cable" and not self._attaching)
        if route == "mic":
            self._cable_tip()
        # Discord / the game picks a mic, or keeps its own one: help with its settings
        mic_side = state == "ok" and (bool(vm) or route == "mic")
        self.btn_nomic.setVisible(mic_side and route != "mic")   # (no mic to switch to)
        self.btn_chat.setVisible(mic_side)
        self.btn_game.setVisible(mic_side)
        self.btn_meeting.setVisible(mic_side)
        self.btn_cablefix.setVisible(state == "ok" and bool(vm) and bool(self.cable_bad))
        # "off" was picked on purpose: it's set up, as far as the rest of the app goes
        self.setup_state = "ok" if state == "off" else state
        short = self._pill_short
        if state == "off":
            pill = "Only you" if short else "Not sending to others (only you hear sounds)"
        elif state == "ok" and route == "mic":
            pill = "Connected" if short else "In your mic — Discord / games hear your sounds"
        elif mic_busy:
            pill = "Setting up…" if short else "Setting up your mic…"
        elif route == "mic" and state != "missing":
            pill = "Not working" if short else "Not reaching your mic — click to fix"
        elif route == "mic" and directmic.needs_repair(direct):
            pill = "Repair needed" if short else "One click needed — repair your mic"
        elif route == "mic":
            pill = ("One click" if short
                    else "One click: put your sounds straight into your mic")
        elif state == "ok" and not vm:
            pill = "Connected" if short else f"Sending to:  {dev}"
        elif state == "ok":
            pill = "Connected" if short else f"Your mic in Discord / games:  {vm}"
        elif state == "missing":
            pill = ("Setup needed" if short
                    else "One-time setup needed — others can't hear you yet")
        elif route == "device":
            pill = ("Not connected" if short
                    else "Not sending — pick a device on the Setup tab")
        else:   # (the Setup tab offers straight into the mic first)
            pill = ("Not connected" if short
                    else "Not connected — click to fix")
        if self.pill.text() != pill:
            good = state in ("ok", "off")
            self.pill.setText(pill)
            self.pill.setIcon(icons.icon("headphones", "live_text") if state == "off" else
                              icons.icon("check", "live_text") if good else
                              icons.icon("warn", "warn_text"))
            self.pill.setProperty("state", "ok" if good else "warn")
            self.pill.style().unpolish(self.pill)
            self.pill.style().polish(self.pill)

    def attach_mic(self):
        """Put the mic effect on the mic in use (Windows asks for admin once), then send
        what others hear into it. The admin step waits, so it runs on a thread."""
        if self._attaching:
            return
        mic = self.cfg.mic_device
        if not mic:
            self.toast("Pick your mic first (Setup tab → Devices).", "warn")
            return
        self._attaching = True
        if self._attach_release is None:   # released by _update_flow once it works
            self._attach_release = busy.hold(self.btn_install, "Setting up…")
        self._update_flow()
        log.info("attaching the mic effect to %s", mic)
        threading.Thread(target=lambda: self.mic_attached.emit(mic, directmic.install(mic) or ""),
                         daemon=True, name="mic-attach").start()

    def _mic_attached(self, mic: str, err: str):
        self._attaching = False
        directmic.forget_status()
        if err:
            if self._attach_release is not None:
                release, self._attach_release = self._attach_release, None
                release("✗ Didn't work")
            log.warning("not put on the mic: %s", err)
            # the route stays on the mic: until it's set up, the cable carries the
            # sounds meanwhile (_main_name), and the one-click stays on offer
            err += "\n\nTry again any time from the Setup tab."
            QMessageBox.warning(self, "Couldn't put Onion Board on your mic", err)
        else:
            log.info("on the mic now: %s", mic)
            # Windows takes a few seconds to load it: "starting…" meanwhile, then a
            # redraw when the wait is over (it works by then, or Repair comes back)
            self._settle_until = time.monotonic() + self.SETTLE_S
            QTimer.singleShot(int(self.SETTLE_S * 1000) + 200, self._update_flow)
            self.cfg.route = "cable"   # so set_route() applies "mic" in full
            self.set_route("mic")
            self.toast("Done — Discord and games hear your sounds through your mic now.")
            if is_hands_free(mic):
                self.toast("That's a Bluetooth headset's call mic: some of them skip "
                           "Windows' sound effects. If nobody hears your sounds, use the "
                           "headset's USB dongle or the virtual cable.", "warn")
        self._show_route()
        self._update_status()

    @staticmethod
    def _set_primary(btn, on: bool):
        name = "primary" if on else ""
        if btn.objectName() != name:
            btn.setObjectName(name)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _cable_tip(self):
        """Once: straight into the mic works, and a voice app is still set to the
        cable's far end. It still hears you (the cable gets the same), but its normal
        mic is the simpler setting."""
        c = self.cfg
        watch = getattr(self, "_cable_watch", None)   # (not made yet while starting up)
        if c.cable_tip_done or self.engine.tap is None or watch is None:
            return
        far = eng.virtual_mic_for(self.engine.tap_name)
        apps = set(voicesdk.VOICE_APPS.values())
        heard = [h for h in watch.poll(far) if h in apps]
        if heard:
            c.cable_tip_done = True
            self._save_now()
            self.toast(f"{heard[0][1]} still uses the virtual cable as its mic. It still "
                       "hears you, but you can set its input back to your normal mic: "
                       "your sounds are in it now.")

    def use_cable_instead(self):
        """Straight into my mic isn't working here: send through the virtual cable (set
        it up first if it isn't installed)."""
        if eng.virtual_outputs():
            self.set_route("cable")
            self.toast("Sending through the virtual cable — pick it as the mic in Discord "
                       "and games (Setup tab).")
        else:
            self.cfg.route = "cable"
            self._show_route()
            self._update_status()
            self.install_cable()

    _direct_shown = None

    def _direct_health(self):
        """What the Setup tab shows about straight into my mic, to redraw it when that
        changes (checked about once a second)."""
        e = self.engine
        h = (directmic.status(self.cfg.mic_device), e.main_stream is not None,
             self._direct_not_running(), bool(e.direct_apps()),
             time.monotonic() < self._settle_until and e.effect_alive())   # "starting…" ends
        return h

    DIRECT_GRACE_S = 4.0   # the board's own mic open this long, and still no sign of it
    SETTLE_S = 20.0        # after setting it up: how long Windows gets to load it

    def _spare_cable(self) -> bool:
        """Straight into the mic, and VB-Cable still installed: it's only the fallback
        now, so the Setup tab offers to remove it."""
        if self._cable_gone or not eng.virtual_outputs():
            return False
        from soundboard import cableremove
        return cableremove.setup_exe() is not None

    def remove_cable(self):
        """Setup tab → Remove the virtual cable: VB-Audio's uninstaller, as admin (it
        waits for Windows' prompt, so it runs on a thread)."""
        if busy.is_busy(self.btn_rmcable):
            return
        from soundboard import cableremove
        self._rmcable_release = busy.hold(self.btn_rmcable,
                                          "Removing… click Yes when Windows asks")
        threading.Thread(target=lambda: self.cable_removed.emit(cableremove.remove() or ""),
                         daemon=True, name="cable-remove").start()

    def _cable_removed(self, err: str):
        if err:
            log.warning("virtual cable not removed: %s", err)
            self._rmcable_release("✗ Not removed")
            self.toast(f"The virtual cable wasn't removed: {html.escape(err)}", "warn")
            return
        self._rmcable_release()
        self._cable_gone = True   # stop sending into it now (Windows lists it till a restart)
        self._apply_send_outputs()
        self.toast("✓ The virtual cable is removed. Restart your PC to finish: until then "
                   "Windows still lists “CABLE Input” / “CABLE Output”.", "ok")
        self._update_status()

    def _direct_not_running(self) -> bool:
        """Set up on the mic, the board's own mic stream open on it for a while, and the
        effect still never ran: Windows isn't running it (exclusive mode, a driver that
        skips effects, a failed load)."""
        e = self.engine
        if e.mic_stream is None or e.effect_alive():
            self._direct_dead_since = None
            return False
        if directmic.endpoint_for(self.cfg.mic_device) not in directmic.installed_on():
            return False
        now = time.monotonic()
        since = getattr(self, "_direct_dead_since", None) or now
        self._direct_dead_since = since
        return now - since > self.DIRECT_GRACE_S

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

    def _voice_tick(self):
        """The timer's _poll_voice: every VOICE_POLL_MS while the window is on screen
        (the hint shows) or *Pick the mode by itself* is ticked (it switches), else only
        every VOICE_POLL_IDLE_S: snapshotting the programs and recording sessions is
        wasted work while nobody sees the answer."""
        d = self.cfg.dest if isinstance(self.cfg.dest, dict) else {}
        now = time.monotonic()
        if (not self._ui_live and not d.get("auto")
                and not profiles.auto_picks(profiles.current(d))
                and now - self._voice_at < VOICE_POLL_IDLE_S):
            return
        self._voice_at = now
        self._poll_voice()

    def _heard_device(self):
        """The recording device(s) whose listeners are the voice chat: the cable's far
        end, or with straight into my mic, the mic itself (Discord and games record it)
        and, if there's a cable, its far end too (a voice app still set to the cable)."""
        if self.cfg.route == "mic":
            if self.engine.direct_stream() is None:
                return None
            cables = [eng.virtual_mic_for(o) for o in eng.virtual_outputs()]
            return tuple(dict.fromkeys(d for d in (self.cfg.mic_device, *cables) if d))
        return eng.virtual_mic_for(self._main_name())

    def _poll_voice(self):
        """Which Who's listening mode suits: the program recording the cable's far end
        (voicesdk.Listeners), else the voice engine of the game in front. The simple
        modes (soundboard.profiles) pick within their family from all of it; in
        Advanced, *Pick the mode by itself* switches to the one suggested."""
        key = self.voice_watch.poll() if self.voice_watch is not None else None
        why = (f"The game you have open uses {voicesdk.NAMES.get(key, key)} for voice "
               "chat") if key else ""
        heard = ()
        if self.listeners is not None:
            heard = self.listeners.poll(self._heard_device())
        # for the simple modes, in order: voice chat apps on the cable, the game in
        # front, games on the cable (a per-program list would go first)
        apps = set(voicesdk.VOICE_APPS.values())
        where = "your mic" if self.cfg.route == "mic" else "the virtual cable"
        hints = [profiles.Hint(h[0], f"{h[1]} is listening to {where}",
                               profiles.VOICE.key) for h in heard if h in apps]
        if key:
            hints.append(profiles.Hint(key, why, profiles.GAME.key))
        hints += [profiles.Hint(h[0], f"{h[1]} is listening to {where}",
                                profiles.GAME.key) for h in heard if h not in apps]
        if heard:   # the game in front, if it's one of them; else the first
            key, name = next((h for h in heard if h[0] == key), heard[0])
            why = f"{name} is listening to {where}"
        if (key != self.voice_suggestion or why != self.voice_why
                or hints != self.voice_hints):
            self.voice_suggestion, self.voice_why, self.voice_hints = key, why, hints
            self._auto_dest()
            self.voice_engine.emit(key)

    def _auto_dest(self):
        """Game and Voice chat: the shaping that suits what's seen, as soon as it's
        seen. Advanced with *Pick the mode by itself*: the suggested mode. Nothing seen
        keeps the mode it has."""
        d = self.cfg.dest if isinstance(self.cfg.dest, dict) else {}
        self.cfg.dest = d
        p = profiles.current(d)
        if profiles.auto_picks(p):
            was = destination.resolve(d).key
            key, self.mode_why = profiles.choose(p, self.voice_hints, was)
            if key == was:
                return
            d["simple"], d["mode"] = p.key, key
            mode = destination.apply(self.cfg, self.engine)
            self._save_later()
            log.info("who's listening: %s mode switched to %s (%s)", p.key, key,
                     self.mode_why)
            self.toast(f"{p.label} mode: shaping for {mode.label}. {self.mode_why}.")
            return
        key = self.voice_suggestion
        if not d.get("auto") or key not in destination.BUILTIN_BY_KEY:
            return
        if destination.resolve(d).key == key:
            return
        d["mode"] = key
        mode = destination.apply(self.cfg, self.engine)
        self._save_later()
        log.info("who's listening: switched to %s (%s)", key, self.voice_why)
        self.toast(f"Who's listening: {mode.label}. {self.voice_why}.")

    def _save_later(self):
        self._save_timer.start(400)

    def toast(self, text: str, kind: str = ""):
        """A result the user should see now, whatever tab or dialog is in front (the
        status line is rewritten on every tab change and hidden in small windows)."""
        busy.toast(self, text, kind)

    def _make_radio(self):
        """The Radio tab, or with Radio switched off in Settings > Privacy & security a
        panel saying so: then no directory, player or web view is made at all. (The
        same panel stands in, hidden, while the tab is switched off in Settings > Tabs.)"""
        if net.allowed("radio") and self.tab_on("radio"):
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

    def tab_on(self, key: str) -> bool:
        """Whether a tab (taboff.KEYS) is switched on in Settings > Tabs."""
        return key not in self.cfg.tabs_off

    def _make_tab(self, key: str):
        """The Apps, Triggers or Voice tab, wired to the window; or, switched off in
        Settings > Tabs, its stand-in (nothing of the tab is made or loaded)."""
        if not self.tab_on(key):
            self.tab_info.pop(key, None)
            if key != "voice":
                return taboff.TabOff()
            # effects add-ons still load: a sound's effects (Edit sound) use them too
            from soundboard import modules
            modules.load_effects(modules.discover())
            return taboff.VoiceOff()
        if key == "voice":
            v = VoicePanel(self.engine, self.cfg.voice_fx, self.cfg.speech)
            v.fx_changed.connect(lambda spec: self.set_option("voice_fx", spec))
            v.speech_changed.connect(lambda s: self.set_option("speech", s))
            v.fx.set_tip_enabled(not self.cfg.voice_discord_tip_shown)
            v.fx.chat_help.connect(lambda: self.show_chat_guide("discord"))
            v.fx.tip_dismissed.connect(
                lambda: self.set_option("voice_discord_tip_shown", True))
        elif key == "apps":
            v = AppsTab(self.engine, self.cfg, self._save_later, Meter)
            v.clip_ready.connect(self.on_clip)
            self.tab_info["apps"] = v.info
        else:
            # the Onion Watch add-on, or Hoot and its download button until it's
            # installed; loaded by load_triggers
            v = TriggersTab(BoardHost(self), defer=True)
            v.loaded.connect(lambda: self._update_info_btn())   # Onion Watch can arrive late
        v.active_changed.connect(lambda on, k=key: self._tab_live(k, on))
        return v

    def _tab_live(self, key: str, on: bool):
        """The live badge on the Voice, Triggers or Apps tab."""
        page = getattr(self, key)
        if key == "voice":   # the active voice's picture, when there is one
            set_tab_live(self.tabs, TAB_INDEX[key], on,
                         "● ON: others hear your changed / computer voice", page.tab_icon())
        elif key == "triggers":
            set_tab_live(self.tabs, TAB_INDEX[key], on, "● ON: watching your screen",
                         "triggers")
        else:
            set_tab_live(self.tabs, TAB_INDEX[key], on, page.live_tip(), "apps")

    def set_tab_on(self, key: str, on: bool):
        """Settings > Tabs: switch a tab off (what it was doing stops, it's shut down
        and hidden, and it isn't made again, even at the next start) or back on (made
        afresh and shown)."""
        if key not in taboff.KEYS or self.tab_on(key) == on:
            return
        off = [k for k in self.cfg.tabs_off if k != key]
        self.set_option("tabs_off", off if on else [*off, key])
        i = TAB_INDEX[key]
        if not on and self.tabs.currentIndex() == i:
            self.tabs.setCurrentIndex(0)
        if key == "radio":
            self._radio_follow_switch()
        else:
            self._swap_tab(key)
        self.tabs.setTabVisible(i, on)
        self._update_info_btn()
        log.info("tab %s switched %s", key, "on" if on else "off")
        self.tab_switched.emit(key, on)

    def _swap_tab(self, key: str):
        """Put a freshly made `key` tab (or its stand-in) in place of the one there."""
        i, old = TAB_INDEX[key], getattr(self, key)
        if key == "triggers":
            old.cancel_pending()   # sounds still waiting out a trigger's wait
        old.shutdown()   # first: a new Voice tab sets the engine's voice chain
        steps = self._tab_steps.pop(key, []) if hasattr(self, "_fit") else []
        if steps:
            self._fit.remove(steps)
        new = self._make_tab(key)
        setattr(self, key, new)
        bar = self.tabs.tabBar()
        text, tip, name = self.tabs.tabText(i), self.tabs.tabToolTip(i), bar.accessibleTabName(i)
        cur = self.tabs.currentIndex()
        with QSignalBlocker(self.tabs):   # no tab change saved, no status rewritten
            self.tabs.removeTab(i)
            self.tabs.insertTab(i, new, text)
            self.tabs.setTabToolTip(i, tip)
            bar.setAccessibleTabName(i, name)
            self.tabs.setCurrentIndex(cur)
        icons.set_tab_icon(self.tabs, i, key)
        old.deleteLater()
        self._tab_live(key, False)
        if key == "triggers":
            self.load_triggers()
        if hasattr(self, "_fit"):
            if key in ("voice", "triggers"):
                self._tab_steps[key] = new.fit_steps()
                self._fit.extend(self._tab_steps[key])
            if key == "voice":
                self._stack_cols = (self._stack_cols[0], *new.stack_steps())
            self._refit()

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
        if (net.allowed("radio") and self.tab_on("radio")) == isinstance(self.radio, RadioTab):
            return
        old, playing = self.radio, self.radio.is_active()
        old.shutdown()
        if hasattr(self, "_fit"):   # undone while the old tab's widgets still exist
            self._fit.remove(self._radio_steps)
        self.radio = self._make_radio()
        self.radio_page.removeWidget(old)
        old.deleteLater()
        if hasattr(self, "_fit"):
            self._radio_steps = self.radio.fit_steps()
            self._fit.extend(self._radio_steps)
            self._refit()
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
        """The debounced save: the settings are copied now and written on the saver's
        thread (library.Saver), then _on_saved says how it went."""
        self._saver.cfg = self.cfg
        self._saver.save()

    def _on_saved(self, ok: bool):
        """A failure (disk full, antivirus lock) is logged by the writer; here it's
        shown once so the user knows settings aren't sticking."""
        if ok:
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

    def set_live_color(self, colour: str) -> bool:
        """The user's own highlight colour ("" = the theme's). Only what's drawn in it
        is restyled (quick); False when it's the colour in use already."""
        if theme.valid_colour(colour) == theme.live_override:
            return False
        self.set_option("live_color", theme.apply_live(QApplication.instance(), colour))
        icons.retheme_live()
        self.pill.setText("")   # forces _update_flow to repaint its icon
        self._update_status()
        return True

    def set_live_tab_tint(self, on: bool):
        self.set_option("live_tab_green", on)
        set_live_tint(self.tabs, on)

    def on_top_toggle(self, b):
        self.set_option("always_on_top", b)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, b)
        self.show()

    def set_pad_width(self, w):
        self._pad_size_wait.stop()
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
                                + html.escape(", ".join(pretty_key(c) for c in failed))
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
        dlg = SettingsDialog(self, page, lazy=True)
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
        (at most every ICON_GLOW_MS, or ICON_GLOW_BG_MS behind a game), back to the plain
        icon when it goes quiet."""
        step = min(GLOW_STEPS, round(min(1.0, level * 1.4) * GLOW_STEPS))
        if not self.isVisible() or self.isMinimized():
            # nobody sees it, and each swap makes Windows rebuild the taskbar and tray
            # icons in Explorer, several times a second while a game runs
            step = 0
        tray = getattr(self, "tray", None)
        tray_due = tray is not None and tray.isVisible() and step != self._tray_step
        if not force and ((step == self._icon_step and not tray_due) or now < self._icon_next):
            return
        wait = ICON_GLOW_MS if appstate.active() else ICON_GLOW_BG_MS
        self._icon_next = now + wait / 1000
        icon = glow_icon(theme.T["accent"], theme.T["accent2"], step / GLOW_STEPS)
        if force:   # a theme change: every window (dialogs too) gets the plain icon
            QApplication.setWindowIcon(glow_icon(theme.T["accent"], theme.T["accent2"], 0.0))
        if force or step != self._icon_step:
            # only this window's own icon: the app-wide one restyles every window,
            # hidden dialogs included, on each swap
            self.setWindowIcon(icon)
            self._icon_step = step
        # the tray icon follows the theme too; a hidden one is caught up once it shows
        if tray is not None and (force or tray_due):
            tray.setIcon(icon)
            self._tray_step = step

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
            # the Voice tab switched off: nothing went on, so no "on" beep either
            self.cue("fail" if not self.tab_on("voice") else "start" if on else "stop")
        elif action == "__voicehold__":
            if self._voice_was is None and self.tab_on("voice"):
                self._voice_was = self.voice.fx.btn_power.isChecked()
            self._set_voice(True)
        elif action == "__replay__":
            self.save_replay()
        elif action == "__pause__":
            self.engine.pause_all()
            self._wake()
        elif action == "__random__":
            self.play_random()
        elif action.startswith(RANDOM):
            self.play_random(action[len(RANDOM):])
        else:
            self.play(action)

    def _set_voice(self, on: bool):
        """The voice changer's big ON / OFF switch, from a hotkey."""
        if not self.tab_on("voice"):
            if on:
                self.toast("The Voice tab is switched off (Settings > Tabs).")
            return
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
        # sending nowhere (or the send device is the headphones): Live doesn't claim
        # others hear you; muting still silences the stream output, if there is one
        others = self._main_name() is not None
        stream = bool(self.engine.names["obs"])
        if not on:
            text = ("Muted — others hear nothing", "Muted", "")
        elif others:
            text = ("Live — others hear you", "Live", "")
        elif stream:
            text = ("Live — stream output only", "Live", "")
        else:
            text = ("Only you hear sounds", "Only you", "")
        self.btn_air.setText(text[self._air_size])
        if not on:
            tip = "Click to go live again: others hear you and your sounds"
        elif others:
            tip = ("Click to mute: nothing at all goes out to others (Discord, the game, "
                   "OBS…). You still hear everything")
        elif stream:
            tip = ("Nothing goes out to others, only to the stream output. Click to mute "
                   "that too (you still hear everything)")
        else:
            tip = ("Nothing goes out to others: pick where to send on the Setup tab "
                   "(Send my sounds to)")
        self.btn_air.setToolTip(tip)
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

    def load_triggers(self):
        """Put the Onion Watch add-on into the Triggers tab. It took 0.4-1 s on the UI
        thread, so it waits until the window is up: a 0 ms timer would still run before
        Windows' first paint message, a TRIGGERS_LOAD_MS one runs after it. Runs once."""
        if not self.triggers.pending or self._shut_down:
            return
        self.triggers.load()
        if self.triggers.needs_nudge():
            self._nudge_triggers(self.tabs.indexOf(self.triggers))

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
                self._nudge_seen = None
                self.triggers.nudged()
                icons.set_tab_icon(self.tabs, index, "triggers")
        if getattr(self, "_nudge_seen", None) is not None:   # the tab made again (Settings
            self.tabs.currentChanged.disconnect(self._nudge_seen)   # > Tabs): one hook
            self._nudge_seen = None
        if self.tabs.currentWidget() is self.triggers:
            self.triggers.nudged()
            icons.set_tab_icon(self.tabs, index, "triggers")
        else:
            self._nudge_seen = seen
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
        self.flush_search()
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
        self.flush_search()   # a link pasted a moment ago: the link bar has it now
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
        self._wake()
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
                                "Stop all clears the queue")
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
            self._wake()
            return
        m, data = self.meta(sid), self.audio.get(sid)
        if m and data is not None:
            frac = 0.0 if self.start_frac >= 0.995 else self.start_frac
            self.engine.play(sid, data, self.gain_for(m), loop=m.loop, mode="restart", start=frac,
                             fade_in=m.fade_in if frac == 0 else 0.0, fade_out=m.fade_out)
            self._wake()

    def space_pad(self, sid: str):
        """Space on a pad: pause or resume it while it's playing (or paused), like a
        media player; play it when it isn't."""
        if self.engine.state(sid):
            self.select(sid)
            self.engine.set_paused(sid, not self.engine.state(sid)[1])
            self._wake()
        else:
            self.play(sid)

    def stop_current(self):
        if self.current:
            self._stop_sound(self.current)
        self.start_frac = 0.0

    def _stop_sound(self, sid: str):
        """Stop one sound. If it was the player's and others still play, the player
        moves to the newest of them, so its ⏸ / ■ reach them (stopping the shown pad
        used to leave a web search's sound playing with no way back to it)."""
        self.engine.stop(sid)
        if sid != self.current:
            return
        others = [s for s in self.engine.playing()
                  if s != sid and (s in self._meta or s == LINK_ID)]
        if others:
            self.select(others[-1])

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
            self.drop_preview()   # an effects render still going mustn't play over it
            self.engine.play(sid + ":preview", data, gain, mode="restart", preview=True,
                             **self._preview_fades)
            return "playing"
        self.drop_preview()
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
                self.bridge.preview.emit(sid, out, gain, gen)
        threading.Thread(target=run, daemon=True, name="fx-preview").start()
        return "rendering"

    def drop_preview(self):
        """Forget an effects preview still rendering (a newer preview, or its Edit
        dialog closed): it won't play, and the status stops saying it's rendering.
        Its done() isn't called: the dialog it belongs to may be gone."""
        self._preview_gen += 1
        if self._preview_done is not None:
            self._preview_done = None
            self._update_status()

    def _on_fx_preview(self, sid, data, gain, gen=None):
        if gen is not None and gen != self._preview_gen:
            return   # dropped while it rendered (checked here too: the signal is queued)
        self._update_status()
        done, self._preview_done = self._preview_done, None
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
                p.space.connect(self.space_pad)
                p.chosen.connect(self.select)
                p.pick.connect(self.selection.on_pick)
                p.step.connect(self.grid.focus_step)
                p.menu.connect(self.pad_menu)
                self.pads[m.id] = p
            p.state = "ready" if m.id in self.audio else p.state
            p.selected = m.id == self.current
            ordered.append(p)
        self.grid.set_pads(ordered, layout=False)   # laid out once, by the filter next
        self.apply_filter(self.search.text())
        self._update_status()

    def _results_closed(self):
        """"My sounds": all of them. The search box also filters the pads, so the web
        search still in it left a board of only the pads matching "cat meow" (often
        none, with nothing saying why). Something else typed in it since stays."""
        query = " ".join(self.ytresults.query.split())
        if query and " ".join(self.search.text().split()) == query:
            self.search.clear()

    def _on_search_edited(self, text: str):
        # typed: Qt sends this just before textChanged (the box's clear button sends
        # it just after; that change has filtered at once, and the next one is unequal)
        self._search_typed = text

    def _on_search_text(self, text: str):
        typed, self._search_typed = self._search_typed == text, None
        if typed:
            self._search_wait.start()   # each key restarts it: filter once typing pauses
        else:
            self.apply_filter(text, lazy=True)

    def flush_search(self):
        """Filter the pads for the search box now, if typing left that waiting."""
        if self._search_wait.isActive():
            self.apply_filter(self.search.text(), lazy=True)

    def apply_filter(self, text, lazy: bool = False):
        """Show the pads that match the search box (name or category) and are in the
        category picked above the pads. `lazy`: skip the regrid when no pad changed."""
        self._search_wait.stop()   # this is the filter typing was waiting for
        self.linkbar.set_text(text)
        if getattr(self, "overlay", None) is not None:   # every sounds / category edit ends here
            self.overlay.sounds_changed()
        # a link filters nothing, and nor does the box in the mini player, which hides
        # it: a web search's words left there showed a blank mini player
        t = "" if self.linkbar.url or self.is_mini() else text.strip().lower()
        cat = self.cfg.category
        changed = False
        for m in self.cfg.sounds:
            p = self.pads.get(m.id)
            if p:
                hit = not t or t in m.name.lower() or any(t in g.lower() for g in m.tags)
                hide = not hit or bool(cat and cat not in m.tags)
                changed = changed or bool(p.property("filtered")) != hide
                p.setProperty("filtered", hide)
        if changed or not lazy:
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
            progs = catswitch.programs_for(self.cfg.category_programs, c)
            tb.setTabToolTip(i, f"{n} sound{'s' if n != 1 else ''}"
                             + (f" · {pretty_key(hk)} plays a random one" if hk else "")
                             + (f" · shows by itself when {', '.join(progs)} is in front"
                                if progs else "")
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
            if self.cfg.scoped_hotkeys:   # its key now works only in its categories
                self.register_hotkeys()
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
        if self.cfg.scoped_hotkeys:   # where its key works changed with its categories
            self.register_hotkeys()
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
        for exe, cat in self.cfg.category_programs.items():   # its programs come along
            if cat == old:
                self.cfg.category_programs[exe] = new
        if self.cat_switch.shown == old:
            self.cat_switch.shown = new
        if self.cat_switch.before == old:
            self.cat_switch.before = new
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
        self.cfg.category_programs = {exe: cat for exe, cat
                                      in self.cfg.category_programs.items() if cat != name}
        self._update_cat_timer()
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
        a_prog = menu.addAction(icons.icon("apps"), "Show this when a program is in front…")
        a_unprog = {menu.addAction(f"Stop showing this for {exe}"): exe
                    for exe in catswitch.programs_for(self.cfg.category_programs, name)}
        menu.addSeparator()
        a_del = menu.addAction(icons.icon("trash", "danger_text"),
                               "Delete category (keeps the sounds)")
        act = menu.exec(self.cat_tabs.mapToGlobal(pos))
        menu.deleteLater()   # its actions stay valid until this returns
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
        elif act == a_prog:
            self.pick_category_programs(name)
        elif act in a_unprog:
            self.remove_category_program(a_unprog[act])

    # ------------------------------------------------------------ program -> category
    def _update_cat_timer(self):
        on = bool(self.cfg.category_programs_on and self.cfg.category_programs)
        if on and not self._cat_timer.isActive():
            self._cat_timer.start()
        elif not on:
            self._cat_timer.stop()
            self.cat_switch.reset()

    def _cat_tick(self):
        sw = self.cat_switch.poll(self.cfg.category_programs, self.cfg.category,
                                  self.cfg.categories)
        if sw is None:
            return
        self.set_category(sw.category)
        names = ["", *self.cfg.categories]
        n = names.index(sw.category) if sw.category in names else 0
        self.cue((523,) if n == 0 else ((784, 0) * min(n, 5))[:-1])   # as step_category
        shown = html.escape(sw.category or ALL)
        self.toast(f"Back to “{shown}” ({html.escape(sw.exe)} closed)" if sw.back
                   else f"Switched to “{shown}” ({html.escape(sw.exe)} is in front)")

    def pick_category_programs(self, name: str):
        """A category's menu → Show this when a program is in front…"""
        from soundboard.ui.programpick import ProgramPicker
        d = ProgramPicker(name, dict(self.cfg.category_programs), self)
        picked = d.picked if d.exec() else []
        free_dialog(d)
        for exe in picked:
            self.add_category_program(name, exe, quiet=True)
        if picked:
            self.toast(f"✓ “{html.escape(name)}” shows by itself when "
                       f"{html.escape(', '.join(picked))} is in front", "ok")

    def add_category_program(self, name: str, exe: str, quiet: bool = False):
        exe = catswitch.exe_name(exe)
        if not exe or name not in self.cfg.categories:
            return
        self.cfg.category_programs[exe] = name   # one category per program
        self._category_programs_changed()
        if not quiet:
            self.toast(f"✓ “{html.escape(name)}” shows by itself when "
                       f"{html.escape(exe)} is in front", "ok")

    def remove_category_program(self, exe: str):
        if self.cfg.category_programs.pop(exe, None) is not None:
            self._category_programs_changed()

    def set_category_programs_on(self, on: bool):
        self.cfg.category_programs_on = bool(on)
        self._category_programs_changed()

    def _category_programs_changed(self):
        self.cat_switch.reset()
        self.cat_switch.front_pid = 0   # the program in front now counts as arriving
        self._update_cat_timer()
        self._save_now()
        self._fill_categories()
        self.category_programs_changed.emit()

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
        self._loose_empty: dict[Path, tuple[tuple[int, int], int]] = {}   # sig, looks
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
        seen, ready, empty = {}, [], {}
        for p in loose_sounds(self.cfg):
            if p in self._loose_taken:
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            sig = (st.st_size, st.st_mtime_ns)
            if not st.st_size:   # never "ready": don't look again every 1.5 s forever
                was = self._loose_empty.get(p)
                looks = was[1] + 1 if was and was[0] == sig else 0
                empty[p] = (sig, looks)
                if looks >= LOOSE_EMPTY_LOOKS:
                    continue   # the folder changing (it's written to) looks again
            if st.st_size and self._loose_sizes.get(p) == sig:
                ready.append(p)
            else:
                seen[p] = sig
        self._loose_sizes, self._loose_empty = seen, empty
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

    def import_files(self, files, extras: dict[str, otherboards.Entry] | None = None):
        """Add sound files (and zips / backups). `extras`: file -> its name, hotkey and
        categories from another soundboard; those already here are skipped quietly."""
        files = [f for f in files if f]
        extras = extras or {}
        for f in list(files):
            if (src := otherboards.for_file(f)) is not None:
                files.remove(f)   # another soundboard's saved board dropped on the window
                self.import_other(src, f)
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
                        if f in extras:
                            self.bridge.imported.emit(None, None, "")   # already moved over
                            continue
                        raise RuntimeError(f"already in your library as “{known[fp]}”")
                    meta, data = import_file(f, PAD_COLORS[(start + i) % len(PAD_COLORS)])
                    if (x := extras.get(f)) is not None:
                        meta.name = x.name or meta.name
                        meta.tags = clean_tags(x.tags)
                        if x.hotkey:
                            self._import_keys[meta.id] = x.hotkey
                    meta.image = thumbs.extract_art(f, meta.id)   # cover art / first frame
                    videos.link_import(meta.id, f)   # the player can show a video file
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
            for t in meta.tags:
                if t not in self.cfg.categories:
                    self.cfg.categories.append(t)
            key = self._import_keys.pop(meta.id, "")
            if key and not self._hotkey_taken(key):
                meta.hotkey = key
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
            self._fill_categories()   # categories and hotkeys from an Import from Soundpad
            self.register_hotkeys()
            n, self._imported_ok = self._imported_ok, 0
            busy.set_busy(self.btn_add, False)
            if n:
                self.toast(f"✓ Added {n} sound{'s' if n != 1 else ''}", "ok")
            elif not self._import_errors:
                self.toast("Nothing new to add")
            self.triggers.import_done()   # a trigger's sound that failed to import
            if self._import_errors:
                # in <p>: escaped text with no tag in it (one error alone) was shown as
                # plain text, "&#x27;" and all
                errs, self._import_errors = self._import_errors[:15], []
                QMessageBox.warning(self, "Some files weren't added",
                                    "<p>" + "<br>".join(html.escape(e) for e in errs) + "</p>")

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
                        "picture on it, or copy one, click the pad and press Ctrl+V)")
        menu.addSeparator()
        a_export = add(("folder",), "Export…", "Save it as a file to share with friends")
        a_del = add(("trash", "danger_text"), "Remove", "Goes to Recently deleted")
        act = menu.exec(pos)
        menu.deleteLater()   # its actions stay valid until this returns
        if act is None:
            return
        if act in cat_acts:
            self.toggle_tag(sid, cat_acts[act])
        elif act == a_newcat:
            self.new_category(sid)
        elif act == a_export:
            self.export_sounds([m], m.name)
        elif act == a_stop:
            self._stop_sound(sid)
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

    def _focus_sounds_page(self, _i: int):
        """Switched to Sounds with the focus left behind on another tab (a hidden clip
        editor): the page takes it, so its Ctrl+V works straight away."""
        page = self.sounds_page
        fw = QApplication.focusWidget()
        if self.tabs.currentWidget() is page and (fw is None or not page.isAncestorOf(fw)):
            page.setFocus(Qt.OtherFocusReason)

    def paste_picture(self):
        """Ctrl+V on the Sounds tab: a clip copied in the Apps tab's editor (or its
        Saved clips) is added as a sound; a copied picture goes on the picked pads,
        or else on the selected one."""
        clip = clipeditor.pasted_clip()
        if clip is not None:
            self.on_clip(clip.copy(), f"Clip {time.strftime('%H.%M.%S')}")
            return
        sids = [m.id for m in self.selection.sounds()] or (
            [self.current] if self.current in self.pads else [])
        if not sids:
            return
        img = thumbs.from_clipboard(QApplication.clipboard().mimeData())
        if img is None:
            self.status.setText("Nothing to paste: copy a picture first (in a browser: "
                                "right-click it → Copy image), then press Ctrl+V on a pad.")
            return
        done = [sid for sid in sids if (m := self.meta(sid)) and thumbs.set_image(m, img)]
        if not done:
            return
        self._save_now()
        for sid in done:
            self.pads[sid].update()
        m = self.meta(done[0])
        self.status.setText(f"Picture pasted on “{html.escape(m.name)}”." if len(done) == 1
                            else f"Picture pasted on {len(done)} pads.")

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
        answer = box.exec()
        free_dialog(box)
        if answer != QMessageBox.Yes:
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
        # let go of their audio first: Windows won't delete a mapped cache file
        # (soundboard.mapped) while an array still points into it
        done, self._removed = [(m, i) for m, i, _d in self._removed], []
        for m, i in done:
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
        d = DeletedDialog(trash.SOUND, "sounds", self._restore_deleted, self)
        d.exec()
        free_dialog(d)
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
        if self.cfg.ptt_key == m.hotkey:   # as everywhere else a key is set
            self.cfg.ptt_key = ""
            lost.append("auto push-to-talk")
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
            free_dialog(d)
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
            free_dialog(d)
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
        self.drop_preview()                        # a preview still rendering
        self.engine.stop(f"{sid}~fx:preview")
        try:
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
        finally:
            free_dialog(d)
        self.register_hotkeys()

    def _save_copy(self, m: SoundMeta, d: EditDialog):
        """'Save as new sound': the edits go onto a copy placed after the original."""
        name = d.name.text().strip() or m.name
        try:
            new = duplicate(m, name if name != m.name else f"{name} (edit)")
        except OSError as e:
            errors.warn(self, "Couldn't copy the sound", e)
            return
        videos.copy_link(m.id, new.id)
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

    def import_queued(self):
        """The installer's "Bring my sounds over from …" boxes, ticked: they left a
        note for this start. The tick was their yes, so nothing is asked again."""
        note = library.APP_DIR / otherboards.QUEUED_NAME
        if not note.is_file():
            return
        try:
            keys = note.read_text(encoding="utf-8", errors="replace").split()
        except OSError:
            keys = []
        note.unlink(missing_ok=True)
        for key in dict.fromkeys(keys):
            if (src := otherboards.by_key(key)) is not None:
                self.import_other(src, ask=False)

    def import_other(self, src: otherboards.Source, path: str = "", ask: bool = True):
        """Bring another soundboard's board over: its sound files (copied, it keeps its
        own), names, categories and the hotkeys nothing here uses yet. `ask`: False
        when they already said yes (the installer's box): no questions or pop-ups."""
        title = f"Import from {src.name}"
        if not path:
            try:
                path = str(src.find() or "")
            except OSError:
                path = ""
        if not path and not ask:
            return   # its board went away since the install
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, f"{title}: pick a saved board", str(Path.home()),
                f"{src.name} board ({' '.join('*' + x for x in src.suffixes)})")
            if not path:
                return
        try:
            entries = src.read(Path(path))
        except (OSError, ValueError) as e:
            if not ask:
                log.warning("can't read %s's board: %s", src.name, e)
                self.toast(f"Couldn't bring your {src.name} sounds over: {errors.plain(e)}",
                           "warn")
            else:
                errors.warn(self, f"Couldn't read the {src.name} board", e)
            return
        ok, bad = otherboards.importable(entries)
        if not ok:
            msg = (f"No sounds to bring over: the sound files {src.name} points at have "
                   "been moved or deleted." if entries else
                   f"There are no sounds on your {src.name} board.")
            if ask:
                QMessageBox.information(self, title, msg)
            else:
                self.toast(msg, "warn")
            return
        if ask:
            keys = sum(1 for e in ok if e.hotkey)
            cats = {t for e in ok for t in e.tags}
            lines = [f"Found <b>{len(ok)}</b> sound{'s' if len(ok) != 1 else ''} "
                     f"in {src.name}"]
            extra = [f"{len(cats)} categor{'ies' if len(cats) != 1 else 'y'}" if cats else "",
                     f"{keys} hotkey{'s' if keys != 1 else ''}" if keys else ""]
            if any(extra):
                lines[0] += " with " + " and ".join(x for x in extra if x)
            lines[0] += "."
            lines.append(f"They're copied into Onion Board; {src.name} keeps its own. Ones "
                         "already here are skipped, and a hotkey something here already "
                         "uses is left off.")
            if bad:
                lines.append(f"{len(bad)} more can't be brought over (the file was moved "
                             "or deleted, or isn't a sound): "
                             + html.escape(", ".join(e.name for e in bad[:5]))
                             + ("…" if len(bad) > 5 else ""))
            if QMessageBox.question(self, title, "<br><br>".join(lines),
                                    QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                return
        self.import_files([e.path for e in ok], {e.path: e for e in ok})

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
            clicked = box.clickedButton()
            free_dialog(box)
            if clicked is cancel:
                return
            use_settings = clicked is yes
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
        was_off = list(self.cfg.tabs_off)
        had_programs = dict(self.cfg.category_programs)
        changed = backup.apply_settings(self.cfg, raw)
        if "category_programs" in changed:   # added to the rules here, not in their place
            self.cfg.category_programs = {**had_programs, **self.cfg.category_programs}
            self.cat_switch.reset()
            self._update_cat_timer()
            self._fill_categories()
        if "tabs_off" in changed:   # the tabs follow now: a list saying one thing while
            # the window shows another left the Voice tab unreachable, and Settings
            # crashed reaching into a stand-in
            off, self.cfg.tabs_off = self.cfg.tabs_off, was_off
            for key in taboff.KEYS:
                self.set_tab_on(key, key not in off)
            self.set_option("tabs_off", off)   # with a newer version's keys
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
        if self.cfg.ptt_key:   # pressed by us for the game: never a sound's hotkey
            taken.add(self.cfg.ptt_key)
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

    def _load_remote_addons(self) -> list:
        """[(ModuleInfo, add-on or None)] for every "remote" add-on (soundboard.modules),
        e.g. Onion Pocket. One that fails is noted on its info (and the log;
        Settings → Remote leaves it out) and never stops the app."""
        from soundboard import modules
        return [(info, self._start_remote_addon(info))
                for info in modules.discover() if info.kind == "remote"]

    def _start_remote_addon(self, info):
        """The add-on's object, or None (the reason noted on `info`)."""
        from soundboard import modules
        from soundboard.ui.remotehost import RemoteHost
        if info.error:
            return None
        try:
            return modules.load_package(info).create(RemoteHost(self, info.id))
        except Exception as e:  # noqa: BLE001 - a bad add-on can't stop the app
            log.exception("remote add-on %s didn't start", info.id)
            info.error = str(e) if isinstance(e, modules.ModuleError) \
                else f"failed to start: {errors.plain(e)}"
            return None

    def load_remote_addon(self, info):
        """Start a remote add-on installed while the app runs (Settings → Remote's
        *Get Onion Pocket*, or its *Update* button), in place of any copy of it. A
        running copy is stopped first (its server lets go of the port) and its package
        forgotten, so the new version's code loads; its settings in
        Config.remote_addons are the board's and stay as they are. If the new one
        doesn't start, the old one is started again and stays. The add-on's object,
        or None."""
        from soundboard import modules
        old = next(((i, a) for i, a in self.remote_addons if i.id == info.id), None)
        saved = {}
        if old is not None and old[1] is not None:
            try:
                old[1].stop()
            except Exception:  # noqa: BLE001
                log.exception("remote add-on %s didn't stop cleanly", info.id)
            pkg = old[0].package
            saved = {n: m for n, m in sys.modules.items()
                     if pkg and (n == pkg or n.startswith(pkg + "."))}
            modules._forget(pkg)
        addon = self._start_remote_addon(info)
        if addon is None and saved:
            log.warning("remote add-on %s %s didn't start (%s): keeping %s",
                        info.id, info.version, info.error, old[0].version)
            if info.package:
                modules._forget(info.package)
            sys.modules.update(saved)
            try:
                restart = getattr(old[1], "apply", None)
                if callable(restart):
                    restart()
            except Exception:  # noqa: BLE001
                log.exception("remote add-on %s didn't start again", info.id)
            return None
        self.remote_addons = [(i, a) for i, a in self.remote_addons if i.id != info.id]
        self.remote_addons.append((info, addon))
        return addon

    def remove_remote_addon(self, info, base=None):
        """Uninstall a remote add-on (Settings' *Remove Onion Pocket…*): the running
        copy is stopped (its server lets go of the port), its folder in `base` (the
        modules folder in %APPDATA%) deleted and its package forgotten. Its settings
        in Config.remote_addons stay, for when it's got again. If the folder can't be
        deleted, it's started again. Raises modules.ModuleError."""
        from soundboard import modules
        cur = next(((i, a) for i, a in self.remote_addons if i.id == info.id), None)
        if cur is not None and cur[1] is not None:
            try:
                cur[1].stop()
            except Exception:  # noqa: BLE001 - it's being removed anyway
                log.exception("remote add-on %s didn't stop cleanly", info.id)
        try:
            modules.uninstall(info.id, base)
        except modules.ModuleError:
            if cur is not None and cur[1] is not None:
                restart = getattr(cur[1], "apply", None)
                try:
                    if callable(restart):
                        restart()
                except Exception:  # noqa: BLE001
                    log.exception("remote add-on %s didn't start again", info.id)
            raise
        if info.package:
            modules._forget(info.package)
        self.remote_addons = [(i, a) for i, a in self.remote_addons if i.id != info.id]
        log.info("remote add-on %s %s was removed", info.id, info.version)

    def _stop_remote_addons(self):
        for info, addon in self.remote_addons:
            if addon is not None:
                try:
                    addon.stop()
                except Exception:  # noqa: BLE001
                    log.exception("remote add-on %s didn't stop cleanly", info.id)

    def set_autostart(self, on: bool) -> bool:
        return autostart.set_enabled(on, self.cfg.autostart_hidden)

    def set_autostart_hidden(self, hidden: bool):
        self.set_option("autostart_hidden", hidden)
        autostart.refresh(hidden)

    # ------------------------------------------------------------------ updates
    def check_updates(self, force: bool = False, why: str = ""):
        """Look for a newer release on a thread (see updates.py). Without `force` only
        if the box is ticked, and at most every 6 hours. `why`: the click that asked,
        for Network activity (none: the app's own timer)."""
        if not force and not self.cfg.update_check:
            return

        due = force or time.time() - self.cfg.update_checked >= updates.EVERY_S
        why = why or "Automatic update check (at most every 6 hours)"
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

    def send_usage(self):
        """The anonymous daily usage count, if it's due and switched on (usage.py)."""
        usage.maybe_send(self.cfg, self.bridge.counted.emit, app_dir=library.APP_DIR)

    def _mark_stopped(self):
        usage.mark_stopped(library.APP_DIR)

    def _count_tab(self, i: int):
        if 0 <= i < len(TABS):
            usage.tab_opened(self.cfg, TABS[i][0].lower())

    def _on_update(self, rel, err: str, asked: bool):
        self._save_later()   # update_checked
        busy = self._downloading or self._update_file is not None
        if rel is not None and not busy:
            self.release = rel
            self._set_update_pill(f"Update: {rel.version}",
                                  f"Onion Board {rel.version} is out — click for details")
            if self.tray is not None and not self.isVisible():
                self.tray.showMessage(
                    "Onion Board", f"Important fix: {rel.urgent}" if rel.urgent
                    else f"Version {rel.version} is out.",
                    QSystemTrayIcon.Warning if rel.urgent else QSystemTrayIcon.Information,
                    8000)
            self._show_urgent()
        self.update_done.emit(rel, err)   # for the Settings window's "Check now"
        if asked and rel is not None:
            self.show_update()

    def _on_watch_update(self, offer):
        """A newer Onion Watch (check_updates): its Triggers tab offers it, and an
        urgent one gets the banner too."""
        self.triggers.offer_update(offer)
        if offer.urgent:
            self.watch_offer = offer
            self._show_urgent()

    def _urgent_now(self) -> tuple[str, str, str] | None:
        """The urgent fix to show on the banner: (key, text, button), Onion Board's
        before Onion Watch's; None when there's none, or it was hidden."""
        rel = self.release
        if (rel is not None and rel.urgent and not self._downloading
                and f"board {rel.version}" not in self._urgent_hidden):
            button = ("Restart to update" if self._update_file is not None
                      else "Update now" if updates.can_install() and rel.asset_url
                      else "Details")
            return (f"board {rel.version}",
                    f"Important fix in Onion Board {rel.version}: {rel.urgent}", button)
        o = self.watch_offer
        if o is not None and f"watch {o.version}" not in self._urgent_hidden:
            return (f"watch {o.version}",
                    f"Important fix in Onion Watch {o.version}: {o.urgent}",
                    "Update Onion Watch")
        return None

    def _show_urgent(self):
        now = self._urgent_now()
        if now is None:
            self.urgent_bar.hide()
            return
        _key, text, button = now
        self.urgent_lbl.setText(text)
        self.urgent_btn.setText(button)
        self.urgent_bar.show()

    def _hide_urgent(self):
        now = self._urgent_now()
        if now is not None:
            self._urgent_hidden.add(now[0])
        self._show_urgent()   # the next one, if any

    def _urgent_clicked(self):
        now = self._urgent_now()
        if now is None:
            return
        if now[0].startswith("board"):
            if self._update_file is not None:
                self.install_update()
            elif updates.can_install() and self.release.asset_url:
                self.download_update()
            else:
                self.show_update()
            return
        # Onion Watch: its tab does the updating (and shows how it's going)
        self.tabs.setCurrentWidget(self.triggers)
        if self.triggers.offer is not None and not self.triggers._busy:
            self.triggers.get()
        self.watch_offer = None
        self._show_urgent()

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
        box = QMessageBox(QMessageBox.Warning if rel.urgent else QMessageBox.Information,
                          "Important fix available" if rel.urgent else "Update available",
                          f"Onion Board {rel.version} is out (you have {__version__}).",
                          QMessageBox.NoButton, self)
        info = (f"<p><b>Important fix:</b> {html.escape(rel.urgent)}</p>"
                if rel.urgent else "")
        info += html.escape(rel.notes).replace("\n", "<br>") if rel.notes else ""
        installable = updates.can_install() and bool(rel.asset_url)
        if installable:
            info += ("<p>Update now downloads it in the background (about 180 MB); you "
                     "choose when the app restarts to install it. Your sounds and "
                     "settings stay as they are.</p>")
        elif not updates.can_install():
            info += "<p>This copy runs from source: update it with <code>git pull</code>.</p>"
        if info:
            box.setInformativeText(f"<p>{info}</p>")
        get = box.addButton("Update now" if installable else "Open the download page",
                            QMessageBox.AcceptRole)
        page = box.addButton("Release page", QMessageBox.HelpRole) if installable else None
        # an urgent fix can't be skipped for good, only put off
        skip = (None if rel.urgent
                else box.addButton("Skip this version", QMessageBox.DestructiveRole))
        box.addButton("Later", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        free_dialog(box)
        if clicked is get and installable:
            self.download_update()
        elif clicked is get or (page is not None and clicked is page):
            QDesktopServices.openUrl(QUrl(rel.url))
        elif skip is not None and clicked is skip:
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
        usage.maybe_send(self.cfg, event=usage.update_event(rel.version))
        self._set_update_pill("Downloading update…",
                              f"Downloading Onion Board {rel.version}", enabled=False)
        self._show_urgent()   # the pill shows how it's going
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
        self._show_urgent()   # back, as "Update now" or "Restart to update"
        if path is None:
            self._set_update_pill(f"Update: {rel.version}",
                                  f"Onion Board {rel.version} is out — click for details")
            box = QMessageBox(QMessageBox.Warning, "Couldn't update",
                              f"Onion Board {rel.version} couldn't be downloaded: "
                              f"{errors.plain(err).rstrip('.')}.",
                              QMessageBox.NoButton, self)
            page = box.addButton("Open the download page", QMessageBox.AcceptRole)
            box.addButton("Close", QMessageBox.RejectRole)
            box.exec()
            clicked = box.clickedButton()
            free_dialog(box)
            if clicked is page:
                QDesktopServices.openUrl(QUrl(rel.url))
            return
        self._update_file = path
        self._show_urgent()
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
        clicked = box.clickedButton()
        free_dialog(box)
        if clicked is not now:
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
        clicked = box.clickedButton()
        free_dialog(box)
        if clicked is new:
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
        clicked = box.clickedButton()
        free_dialog(box)
        if clicked is page:
            QDesktopServices.openUrl(QUrl(updates.RELEASES))
        elif logb is not None and clicked is logb:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(updates.INSTALL_LOG)))

    # ------------------------------------------------------------------ test mode
    def on_mic_check(self, on):
        self.engine.ring_mon.clear()
        self.engine.mic_check = on
        text = "Stop hearing it" if on else "Hear what they hear"
        self.btn_check.setProperty("full_text", text)   # what a compact window restores
        if self.btn_check.text():   # blank while the window is too narrow for words
            self.btn_check.setText(text)
        self.mic_banner.setVisible(on)
        if on:
            self._pulse.start()   # impossible to miss, and cheap
            if not self._ui_live:   # turned on from the tray: pulses once it's shown
                self._pulse.pause()
        else:
            self._pulse.stop()
            self._banner_fx.setOpacity(1.0)
        self.mic_lbl.setStyleSheet(f"color:{theme.status('error')};" if on else "")
        self.mic_meter.hot = on
        if on and not self.cfg.mic_enabled:
            self.status.setText(f"<span style='color:{theme.status('warn')}'>"
                                "Sounds only: your mic isn't "
                                "sent, so nobody (including you) hears it.</span>")

    def start_test(self):
        if self.engine.main_stream is None:
            route = self.cfg.route
            QMessageBox.information(
                self, "Test",
                "Sending to others is off, so there's nothing to record. Change it under "
                "Setup → Devices → Send my sounds to." if route == "off" else
                "Pick the device to send to first (Setup tab → Devices → Send my sounds "
                "to)."
                if route == "device" else
                "Put your sounds in your mic first (Setup tab → Put my sounds straight "
                "into my mic), or use the virtual cable." if route == "mic" else
                "Set up the virtual cable first (Setup tab → Step-by-step guide), or pick "
                "another device under Send my sounds to.")
            return
        # Capture the far end of the virtual cable too, so the test hears exactly
        # what Discord / the game hears (not just our internal mix).
        self._stop_capture()
        self._cap, self._cap_rate = [], None
        # straight into my mic: the mic itself, which carries exactly what others get
        vm = (self.cfg.mic_device if self.cfg.route == "mic"
              else eng.virtual_mic_for(self.cfg.main_device))
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
        if not self._ui_live and not self.overlay.is_open:
            return TICK_IDLE_MS
        if not self._tick_busy:   # nothing moves: 10 ticks a second instead of 30
            return TICK_QUIET_MS
        if self.overlay.is_open:   # the in-game overlay shows what's playing, over the game
            return TICK_MS
        return TICK_MS if appstate.active() else TICK_BG_MS

    def _wake(self):
        """A sound started or resumed: full pace now, not after a quiet tick (auto
        push-to-talk presses its key from the tick)."""
        if not self._tick_busy:
            self._tick_busy = True
            pace = self._tick_pace()
            if self.timer.interval() != pace:
                self.timer.start(pace)

    def _busy(self, playing) -> bool:
        """Something on screen moves with the tick: a sound playing (not paused), the
        radio, the test recording, a meter or the mic level still showing."""
        e = self.engine
        return (any(not paused for _p, paused in playing.values())
                or self.radio.is_active() or e.recording or e.rec_done is not None
                or self._rec_playing or bool(self._queue) or bool(e.aux)
                or max(e.level_play, e.level_main,
                       e.level_mic if e.mic_stream is not None else 0.0) > LEVEL_QUIET)

    def _set_tick_rate(self, *_):
        live = self.isVisible() and not self.isMinimized()
        was, self._ui_live = self._ui_live, live
        # the mic-check banner's pulse (~60 frames a second) only while it can be seen
        if not live and self._pulse.state() == QAbstractAnimation.Running:
            self._pulse.pause()
        elif live and self._pulse.state() == QAbstractAnimation.Paused:
            self._pulse.resume()
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
            elif self.cfg.route == "mic" and self._direct_health() != self._direct_shown:
                self._update_flow()
            self.voice.poll()
        playing = e.playing()
        if self._queue and not any(sid in self._meta for sid in playing):
            self._next_in_queue()
            playing = e.playing()
        live = any(sid in self._meta and not paused for sid, (_p, paused) in playing.items())
        if live != self._sounds_live:   # the Sounds tab glows while a sound plays
            self._sounds_live = live
            set_tab_live(self.tabs, self.tabs.indexOf(self.sounds_page), live,
                         "● ON: a sound is playing", "sounds")
        self._tick_busy = self._busy(playing)
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
                                         "The test stopped: the send "
                                         "device's output went away. Check Devices "
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
        shown = self.isVisible()
        for sid, p in self.pads.items():
            prog, paused = playing.get(sid, (None, False))
            if prog is not None and not paused and on_board and not p.isHidden():
                # scrolled out of view: skip the FFT (the next tick after it scrolls
                # back in catches up)
                if not (shown and p.visibleRegion().isEmpty()):
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
        self._update_video(sid, m, playing)
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

    def _video_of(self, sid: str | None) -> Path | None:
        """The current sound's video, looked up once per selection."""
        if self._video_for[0] != sid:
            self._video_for = (sid, videos.get(sid) if sid else None)
        return self._video_for[1]

    def _update_video(self, sid, m, playing):
        path = self._video_of(sid) if m else None
        if self.btn_video.isHidden() == (path is not None):
            self.btn_video.setVisible(path is not None)
        w = self._video_win
        if w is None or not w.isVisible():
            return
        if path is not None and w.sid != sid:   # a newly picked video pad takes it over
            w.show_for(sid, m.name, path)
        shown = self.meta(w.sid)
        data = self.audio.get(w.sid)
        if shown is None or data is None:
            w.follow(None, 0.0)
            return
        w.follow(playing.get(w.sid), len(data) / SR, self.engine.sound_speed)

    def show_video(self):
        """The player's Video button: open the current sound's video (and play the
        sound if it isn't playing)."""
        sid = self.current
        m = self.meta(sid) if sid else None
        path = videos.get(sid) if m else None
        self._video_for = (sid, path)
        if path is None:
            self.btn_video.hide()
            self.toast("This sound's video isn't there any more", "warn")
            return
        if self._video_win is None:
            try:   # imported here: a build missing QtMultimediaWidgets must still start
                from soundboard.ui.videowindow import VideoWindow
            except ImportError:
                log.exception("can't show videos")
                self.btn_video.hide()
                self.toast("Videos can't be shown in this copy of Onion Board", "warn")
                return
            self._video_win = VideoWindow(self)
            self._video_win.setWindowIcon(self.windowIcon())
        self._video_win.show_for(sid, m.name, path)
        if self.engine.state(sid) is None:
            self.toggle_play_pause()

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
        f.add(16, "w", r.hide(self._mode_pick[0]))   # the dropdown's tooltip says what it is
        f.add(38, "w", r.hide(self._mode_pick[1]))   # also on the Setup tab
        # the ear button shrinks to its icon first: the level bar is the live part
        f.add(12, "w", r.icon_only(self.btn_check))
        f.add(14, "w", r.hide(self.np_time))
        f.add(45, "w", r.hide(self.speed_btn))
        f.add(20, "w", self._shorten_pill)
        f.add(58, "w", r.icon_only(self.stop_btn))
        f.add(24, "w", self._shorten_air(1))
        f.add(65, "w", self._shorten_air(2))
        f.add(22, "w", r.icon_only(self.gear))
        f.add(30, "w", r.hide(self.chk_monitor))
        f.add(28, "w", r.icon_only(self.chk_mic))   # its tooltip still explains it
        f.add(55, "w", r.hide(*self._mixer_hp))
        f.add(40, "w", r.hide(*self._transport_vol))
        f.add(50, "w", r.hide(self.np_name))
        f.add(60, "w", r.hide(self.wordmark))
        f.add(60, "w", r.icon_only(self.btn_add))
        f.add(35, "w", r.hide(self.btn_more))   # also in Settings → General
        f.add(15, "w", r.icon_only(self.btn_folder))
        f.add(33, "w", r.hide(self.btn_folder))   # also in the Backup menu
        f.add(60, "w", self._tab_icons_only)
        f.add(70, "w", r.hide(self.btn_check, *self._mixer_send, *self._mixer_others))
        f.add(80, "w", r.hide(self.pill))
        f.add(85, "w", self._tabs_tight)   # else the icons alone held it at ~480 px
        self._radio_steps = self.radio.fit_steps()   # swapped with the tab (Privacy)
        f.extend(self._radio_steps)
        self._tab_steps = {k: getattr(self, k).fit_steps() for k in ("voice", "triggers")}
        for steps in self._tab_steps.values():
            f.extend(steps)
        # height: the status line, then the whole mixer strip
        f.add(10, "h", self.status.set_room)
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
            self.tabs.tabBar().setAccessibleTabName(i, text)   # icon-only tabs aren't silent
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
            need = self._fit.fit(size)   # even the smallest layout won't fit
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
                     self._stop_remote_addons,
                     self.radio.shutdown, tor.shutdown, self.apps.shutdown,
                     self.triggers.shutdown,
                     self.linkbar.shutdown,
                     self.voice.shutdown, self.engine.shutdown, shellicon.detach,
                     netlog.flush,   # what's still open, once the rest closed
                     self._mark_stopped):   # last: this run ended cleanly (usage.py)
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
