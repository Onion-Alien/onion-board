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
from PySide6.QtCore import (QEvent, QFileSystemWatcher, QObject, QSignalBlocker, QSize, Qt,
                            QTimer, QUrl, Signal)
from PySide6.QtGui import (QActionGroup, QColor, QCursor, QDesktopServices, QFontMetricsF, QIcon,
                           QKeySequence, QPainter, QPixmap, QShortcut)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
                               QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
                               QPushButton, QScrollArea, QSizePolicy, QSlider, QStackedWidget,
                               QSystemTrayIcon, QTabBar, QTabWidget, QToolTip, QVBoxLayout,
                               QWidget, QWidgetAction)
from shiboken6 import isValid as qt_valid

from soundboard import engine as eng
from soundboard import theme, winkeys, ytdl, ytworker
from soundboard.engine import SR, Engine
from soundboard.engine import is_virtual as is_virtual_cable
from soundboard import exitwatch
from soundboard import (appaudio, autostart, backup, catswitch, destination, library, midi,
                        remote, otherboards, soundfx, thumbs, trash, updates, videos, voicesdk)
from soundboard import (appsetup, directmic, discordcfg, net, netlog, profiles, quality, rawmic,
                        shellicon, tips, tor, usage, watchaddon)
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
from soundboard.ui.dialogs import COLOUR_NAMES, EditDialog
from soundboard.ui import (a11y, alsosend, appstate, busy, clipeditor, icons, responsive, splash,
                           taboff)
from soundboard.ui.speedpitch import SpeedPitchButton
from soundboard.ui.panel import (EqPanel, Flow, VolumeControl, bar, capped, card,
                                 hint_label, icon_label, vsep)
from soundboard.ui.linkbar import PLAY_ID as LINK_ID
from soundboard.ui.linkbar import LinkBar
from soundboard.ui.livedot import is_tab_live, set_tab_live
from soundboard.ui.livedot import set_tint as set_live_tint
from soundboard.ui.logowidget import LogoWidget, glow_icon
from soundboard.ui.ytsearch import SearchResults
from soundboard.ui.setupshow import SetupShow
from soundboard.ui.spacekey import SpaceKey
from soundboard.ui.padbatch import PadSelection
from soundboard.ui.overlay import Overlay
from soundboard.ui.appspanel import AppsTab, ElidedLabel
from soundboard.ui.triggershost import BoardHost
from soundboard.ui.triggerstab import TriggersTab
from soundboard.ui.radiopanel import RadioOff, RadioTab
from soundboard.ui.voicepanel import VoicePanel
from soundboard.ui.widgets import (Meter, NameAndSeek, Pad, PadGrid, SeekSlider, SteadyTabs,
                                   TabEndCorner, expand_dropped, fmt_pos, pad_height, spectrum,
                                   SLIM_PAD_H)
from soundboard.wheelguard import no_wheel
from soundboard.winkeys import Hotkeys
from soundboard import errors
from soundboard import i18n
from soundboard.i18n import _, ngettext

log = logging.getLogger(__name__)


def version_text() -> str:
    """The version, as the title bar and header show it: "1.5.5", or "1.5.5 from
    source" when run with Python rather than the installed app."""
    from soundboard import __version__
    if getattr(sys, "frozen", False):
        return __version__
    return _("{version} from source", version=__version__)


# The tabs, in order: each one is a thing you can play (or, last, the setup). The
# tooltip says what it's for in a few words.
# the tabs' keys (never translated: settings, Tabs on/off, the usage count) and labels
TAB_KEYS = ("sounds", "radio", "apps", "triggers", "voice", "setup")
TABS = ((_("Sounds"), _("Your sound buttons: click one to play it")),
        (_("Radio"), _("Internet radio stations from around the world")),
        (_("Apps"), _("Send another program's sound (music player, game…)")),
        (_("Triggers"), _("Play a sound when something shows up on your screen (“YOU DIED”…)")),
        (_("Voice"), _("Change your voice, speak another language, or use text-to-speech")),
        (_("Setup"), _("Pick where your sounds go (Discord, games, OBS…), test it")))
TAB_INDEX = {key: i for i, key in enumerate(TAB_KEYS)}


UNDO_S = 10          # how long "Removed … · Undo" stays up
# shown when instant replay goes on: it records whoever is talking in a call
REPLAY_NOTE = _("Instant replay is on: your key keeps the last seconds you heard. In some "
                "places recording a call needs everyone's OK, so only keep clips of people "
                "who are fine with it.")
CHIPS_ROW_H = 30      # the now-playing row: a chip's 24 px ■ button, its margins and border
TICK_MS = 33         # the UI timer while the window is on screen (meters, visualisers)
TICK_BG_MS = 100     # ...while it's on screen but another program is in front (a game)
TICK_IDLE_MS = 250   # ...and while it's in the tray or minimised (push-to-talk, watchdog)
TICK_QUIET_MS = 100  # on screen with nothing moving: no sound, radio, recording or level
LEVEL_QUIET = 0.003  # a level below this (-50 dB) shows as nothing on the meters
TRIGGERS_LOAD_MS = 50   # Onion Watch loads this long after the window is built
GLOW_STEPS = 4       # how many glow levels the taskbar / tray icon has while sound plays
ICON_GLOW_MS = 250   # ...and how often at most it changes
ICON_GLOW_BG_MS = 1000  # ...while another program (a game) is in front
# ...and a step is kept until the level is this far (in steps) past the middle between
# it and the next: a level hovering on a boundary flipped the icon back and forth
ICON_GLOW_HOLD = 0.25
PULSE_MS = 1200      # the mic-check banner's throb: bright, dimmer, bright again
PULSE_LOW = 0.55     # ...down to this opacity
PULSE_FRAME_MS = 60  # ...a step this often (~16 a second still reads as a smooth pulse)
DEFAULT_POLL_MS = 1500   # how often Windows' default output is checked
SETUP_SWITCHED_MS = 8000   # how long "Voice chat mode for Discord. Undo" stays
SETUP_DONE_MS = 15000      # the set-up card with nothing left to do
DISCORD_POLL_MS = 10000  # how often Discord's voice settings are looked at (discordcfg)
RAW_POLL_MS = 2000       # how often the apps recording the mic are counted (rawmic)
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
LINK_WAIT_MS = 400       # a link in the search box is looked up once it stays this long
PAD_SIZE_WAIT_MS = 50    # dragging Pad size re-lays the pads at most this often
RANDOM = "__random__:"   # hotkey action prefix: a random sound from the category after it
ALL = _("All")       # the category tab that shows every sound
AUTO_MIC_UPDATE_MS = 4000   # an older mic part moves on by itself this long after the start
TIP_DELAY_MS = 8000    # the first tip waits this long after the start
TIP_RETRY_MS = 60_000  # ...and is tried again this often while it can't show
LANG_OFFER_SEEN = "language-offer"   # in Config.tips_seen: the language bar was turned down
SEARCH_MIN_W = 220    # the Sounds tab's search box, until the window gets narrow
VOICE_POLL_MS = 3000  # how often the game in front is looked at (soundboard.voicesdk)
VOICE_POLL_IDLE_S = 15   # ...while nobody sees the hint and nothing switches by itself
# Setup -> Devices -> Send my sounds to (Config.route, library.ROUTES): the mic, nobody,
# or one of the output devices by name (ROUTE_DEVICE + its name: "cable" for a virtual
# cable, "device" for anything else)
SEND_TO = _("Send my sounds to")
ROUTE_CHOICES = ((_("My mic (normal)"), "mic"),
                 (_("Nobody: only I hear them"), "off"))
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


class SnugTabBar(QTabBar):
    """A tab bar no wider than its tabs. Qt's minimum keeps room for the scroll
    arrows even with one short tab, which left a wide gap before the "+" after it."""

    def minimumSizeHint(self) -> QSize:
        m = super().minimumSizeHint()
        return QSize(min(m.width(), self.sizeHint().width()), m.height())


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


class Pulse(QObject):
    """The mic-check banner's throb: its opacity goes from 1 down to PULSE_LOW and back
    every PULSE_MS, a step every PULSE_FRAME_MS. Each step draws the whole banner again
    off-screen, so it runs only while it's on and the window can be seen in front
    (set_live); otherwise the banner stands still, fully bright. An animation did this
    at 60 frames a second, behind a game too."""

    def __init__(self, fx: QGraphicsOpacityEffect, parent: QObject):
        super().__init__(parent)
        self.fx = fx
        fx.setOpacity(1.0)     # (Qt's own start is 0.7)
        fx.setEnabled(False)   # a still banner is drawn straight, not through the effect
        self.on, self.live = False, True
        self._t0 = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(PULSE_FRAME_MS)
        self.timer.timeout.connect(self._step)

    def running(self) -> bool:
        return self.timer.isActive()

    def set_on(self, on: bool):
        self.on = on
        self._apply()

    def set_live(self, live: bool):
        self.live = live
        self._apply()

    def _apply(self):
        run = self.on and self.live
        if run == self.timer.isActive():
            return
        if run:
            self._t0 = time.monotonic()
            self.fx.setEnabled(True)
            self._step()
            self.timer.start()
        else:
            self.timer.stop()
            self.fx.setOpacity(1.0)
            self.fx.setEnabled(False)

    def opacity_at(self, ms: float) -> float:
        t = (ms % PULSE_MS) / PULSE_MS   # 0..1 through one throb
        return PULSE_LOW + (1.0 - PULSE_LOW) * abs(2.0 * t - 1.0)

    def _step(self):
        self.fx.setOpacity(self.opacity_at((time.monotonic() - self._t0) * 1000.0))


class Bridge(QObject):
    loaded = Signal(str, object, str)          # id, data|None, error
    exported = Signal(str, int, str)           # file, sounds written, error
    unpacked = Signal(object, object, str)     # backup.Imported|None, backup.Package, error
    update = Signal(object, str, bool)         # updates.Release|None, error, asked by the user
    update_progress = Signal(int)              # percent of the new version downloaded
    update_ready = Signal(object, str)         # its installer's Path|None, error
    watch_update = Signal(object)              # a newer Onion Watch: watchaddon.Offer
    discord = Signal(object)                   # [discordcfg.Settings] read in the background
    mic_users = Signal(object)                 # [appaudio.App] recording the mic (rawmic)
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


# the urgent bar's line for the worst thing in Discord's settings (discordcfg)
DISCORD_URGENT = {
    discordcfg.STUDIO: _("{name} isn't hearing your sounds: its Input Profile is Studio, "
                         "which skips Onion Board. Set it to Custom."),
    discordcfg.BYPASS: _("{name} isn't hearing your sounds: \"Bypass System Audio Input "
                         "Processing\" is on, which skips Onion Board."),
    discordcfg.VAD: _("{name}'s Advanced Voice Activity cuts most of your sounds in calls. "
                      "Turn it off (Voice & Video → Show Advanced Voice Settings)."),
    discordcfg.AUTO: _("{name}'s automatic input sensitivity keeps cutting your sounds out "
                       "in calls. Turn it off (Voice & Video → Input Sensitivity)."),
    discordcfg.ISOLATION: _("{name}'s Voice Isolation is wiping out your sounds. Set its "
                            "Input Profile to Custom and Noise Suppression to None."),
    discordcfg.KRISP: _("{name}'s noise suppression (Krisp) is wiping out your sounds. Set "
                        "Noise Suppression to None."),
    discordcfg.SUPPRESSION: _("{name}'s noise suppression is eating your sounds. Set Noise "
                              "Suppression to None."),
    discordcfg.ECHO: _("{name}'s echo cancellation is making your sounds dip and pump. "
                       "Turn it off."),
    discordcfg.AGC: _("{name}'s automatic gain control is making your sounds' volume jump. "
                      "Turn it off."),
}


class MainWindow(QMainWindow):
    update_done = Signal(object, str)   # an update check finished: Release|None, error
    mic_attached = Signal(str, str)     # attach_mic finished: the mic, error ("" = done)
    cable_removed = Signal(str)         # remove_cable finished: error ("" = done)
    cable_setup_found = Signal(bool)    # VB-Cable's setup program is on this PC (asked on a thread)
    video_found = Signal(str, object)   # a sound's video (Path|None), looked up on a thread
    config_saved = Signal(bool)         # the background save finished: ok
    voice_engine = Signal(object)       # the voice engine of the game in front (a mode key|None)
    default_found = Signal(object)      # Windows' default output, asked on a thread (str|None)
    device_step = Signal(object)        # the device thread's next step for the UI (_off_ui)
    tab_switched = Signal(str, bool)    # Settings > Tabs: a tab (taboff.KEYS) off / on again
    category_programs_changed = Signal()   # a program -> category rule added / removed
    app_setup_changed = Signal()   # an app remembered / forgotten (appsetup)

    def __init__(self):
        super().__init__()
        # shutdown() ran (app.py also calls it on aboutToQuit). Set first: the splash
        # pumps events while the window is built, so its timers (load_triggers) can run
        # before the end of __init__
        self._shut_down = False
        self.title = _("Onion Board {version_text}", version_text=version_text())
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
        self.bridge.discord.connect(self._on_discord)
        self.bridge.mic_users.connect(self._on_mic_users)
        self.bridge.counted.connect(self._save_later)   # stats_sent
        self._removed: list[tuple[SoundMeta, int, np.ndarray | None]] = []   # undo-able
        self._render_gen: dict[str, int] = {}   # sid -> newest effects render (_rerender)
        self.shuffle = ShuffleBag()       # the random-sound hotkeys
        self._last_sid: str | None = None   # the last sound played (its replay hotkey)
        self._queue: list[str] = []       # sounds waiting for the ones playing to finish
        self._stopped_at = (0.0, "")       # (when, which) the player's ■ last stopped
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
        # Discord's own voice settings (discordcfg), read while it runs: the ones that
        # wipe out sounds get the urgent bar
        self.discord_found: list = []
        self._discord_sig = None
        self._discord_reading = False
        self._discord_timer = QTimer(self, interval=DISCORD_POLL_MS)
        self._discord_timer.timeout.connect(self._discord_tick)
        if sys.platform == "win32":
            self._discord_timer.start()
            QTimer.singleShot(3000, self._discord_tick)
        # straight into my mic: an app recording the mic in raw mode skips Onion Board
        # and hears none of the sounds (rawmic)
        self.raw_watch = rawmic.BypassWatch()
        self._raw_looking = False
        self._raw_timer = QTimer(self, interval=RAW_POLL_MS)
        self._raw_timer.timeout.connect(self._raw_tick)
        if sys.platform == "win32":
            self._raw_timer.start()
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
        self._link_url = ""                        # ...and the page it came from
        self.start_frac = 0.0             # where ▶ starts if it isn't playing
        self._seeking = False
        self._tick_n = 0                  # ticks since start (the watchdog runs ~once a second)
        self._ui_live = True              # the window is on screen (see _set_tick_rate)
        self._tick_busy = True            # something moves with the tick (see _busy)
        self._pads_lit: set[str] = set()  # pads showing a sound (see _tick_visuals)
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
        # play counts and Ctrl+wheel volumes: saved within a few seconds, not on each press
        # (a spammed hotkey wrote the whole config every time); closing saves the rest
        self._count_save = QTimer(self, singleShot=True, interval=5000)
        self._count_save.timeout.connect(self._save_now)
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
        # Space plays / pauses on the Sounds and Radio tabs, wherever the focus is
        self._space = SpaceKey(self, self._space_action)
        theme.app_filter(QApplication.instance(), self._space)
        # which voice chat the game you're playing uses: a hint by Who's listening
        self.voice_suggestion: str | None = None
        self.voice_why = ""   # why it's suggested, for the hint ("Discord is listening…")
        self.voice_hints: list[profiles.Hint] = []   # everything seen, for the simple modes
        self.mode_why = ""    # why the simple mode picked the shaping it uses
        self.listeners = voicesdk.Listeners() if sys.platform == "win32" else None
        # who's still set to the cable while sounds go straight into the mic (_cable_tip)
        self._cable_watch = voicesdk.Listeners() if sys.platform == "win32" else None
        self.voice_watch = voicesdk.Watcher() if sys.platform == "win32" else None
        # set up for the app you're using (appsetup): the bar's app and what it shows
        self._setup_tracker = appsetup.Tracker()
        self._setup_app: appsetup.Seen | None = None
        self._setup_state = ""        # "offer", "done", "switched" or "" (hidden)
        self._setup_skipped: set[str] = set()   # answered Not now, this run
        self._setup_undo: dict | None = None    # the dest settings before a switch
        self._setup_hide = QTimer(self, singleShot=True)
        self._setup_hide.timeout.connect(self._hide_setup)
        self._voice_timer = QTimer(self)
        self._voice_timer.timeout.connect(self._voice_tick)
        self._voice_at = 0.0   # when _poll_voice last ran (see _voice_tick)
        if self.voice_watch is not None:
            self._voice_timer.start(VOICE_POLL_MS)
        # a tip once things have settled; tried again now and then while the window is
        # hidden or a game is up, until one has been shown this start
        self._tip_timer = QTimer(self, interval=TIP_RETRY_MS)
        self._tip_timer.timeout.connect(self._maybe_tip)
        QTimer.singleShot(TIP_DELAY_MS, self, self._start_tips)
        self._offer_language()
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
        self.device_step.connect(lambda step: step())
        self._dev_waiting: list = []   # device changes waiting their turn (_when_devices_free)
        self._dev_retry = QTimer(self, singleShot=True, interval=100, timeout=self._dev_pump)
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
        self._pending_note: str | None = None
        if self.cfg.load_note:   # settings came from a backup or the defaults: say so
            QTimer.singleShot(1200, self._show_load_note)
        QTimer.singleShot(AUTO_MIC_UPDATE_MS, self, self._auto_mic_update)

    def _auto_mic_update(self):
        """An older mic part (1.9.20 and before sat where raw streams skip it: Discord's
        Studio, Chrome, Edge) is moved on the first start of a new version, not left to
        a button nobody looks for. Windows asks once; a No waits for the next version.
        Only with the window open: a prompt at sign-in, in the tray, would be a surprise."""
        from soundboard import __version__
        cfg = self.cfg
        if cfg.route != "mic" or not cfg.mic_device or cfg.mic_update_tried == __version__:
            return
        if not self.isVisible():
            QTimer.singleShot(AUTO_MIC_UPDATE_MS, self, self._auto_mic_update)
            return
        if directmic.status(cfg.mic_device) != "outdated" or self._attaching:
            return
        cfg.mic_update_tried = __version__
        cfg.save()
        log.info("moving the older mic part on by itself")
        self.toast(_("Updating Onion Board's part of your mic so every app hears your "
                     "sounds: click Yes when Windows asks."))
        self.attach_mic()

    def _show_load_note(self):
        """Started hidden in the tray (--tray at sign-in)? Then the box waits for the
        window to be opened, instead of popping up over whatever the user is doing."""
        if self.isVisible():
            QMessageBox.warning(self, _("Settings were restored"), self.cfg.load_note)
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
        self.tagline = QLabel(_("an app by Onion Alien · v{version_text}",
                                version_text=version_text()))
        self.tagline.setObjectName("tagline")
        names.addWidget(self.wordmark)
        names.addWidget(self.tagline)
        head.addLayout(names)
        head.addStretch(1)
        self.pill = QPushButton()
        self.pill.setObjectName("pill")
        self.pill.setCursor(Qt.PointingHandCursor)
        self.pill.setToolTip(_("Where your sounds go — click for setup and testing"))
        self.pill.clicked.connect(lambda: self.tabs.setCurrentWidget(self.setup_page))
        head.addWidget(self.pill)
        # Offline mode: what only works online is out of the way, and this says why
        # (one click to the switch)
        self.btn_offline = QPushButton(_("Offline"))
        self.btn_offline.setObjectName("pill")
        self.btn_offline.setCursor(Qt.PointingHandCursor)
        self.btn_offline.setToolTip(_("Offline mode is on: nothing goes online, and what needs "
                                      "the internet is hidden. Click to change it."))
        self.btn_offline.clicked.connect(lambda: self.open_settings("privacy"))
        icons.set_icon(self.btn_offline, "offline")
        self.btn_offline.setVisible(net.offline())
        head.addWidget(self.btn_offline)
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
        self.stop_btn = QPushButton(_("Stop all"))
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setToolTip(_("Stops every sound, the radio and every program"))
        self.stop_btn.clicked.connect(lambda: (self.stop_all(),
                                               busy.flash(self.stop_btn, _("✓ Stopped"), 1200)))
        icons.set_icon(self.stop_btn, "stop", "danger_text", size=14)
        head.addWidget(self.stop_btn)
        self.gear = QPushButton(_("Settings"))
        self.gear.setObjectName("settings")
        self.gear.setToolTip(_("Themes, hotkeys and more"))
        self.gear.clicked.connect(lambda: self.open_settings())
        icons.set_icon(self.gear, "settings")
        head.addWidget(self.gear)
        rv.addLayout(head)
        self._paint_logo()

        # only a sign: the one switch is "Hear what they hear" in the mixer at the bottom
        self.mic_banner = BannerButton(_("YOU'RE HEARING YOUR MIC OUTPUT  —  mic + sounds, "
                                         "exactly what others hear"),
                                       _("HEARING YOUR MIC OUTPUT"))
        self.mic_banner.setObjectName("micbanner")
        self.mic_banner.setFocusPolicy(Qt.NoFocus)
        self.mic_banner.hide()
        icons.set_icon(self.mic_banner, "ear", "#ffffff", size=20)
        # pulse: an opacity animation, not a stylesheet rewrite 30x a second (each
        # setStyleSheet re-parses and re-polishes the widget)
        self._banner_fx = QGraphicsOpacityEffect(self.mic_banner)
        self.mic_banner.setGraphicsEffect(self._banner_fx)
        self._pulse = Pulse(self._banner_fx, self)
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
        hide.setAccessibleName(_("Hide"))
        hide.setToolTip(_("Hide until Onion Board starts again"))
        hide.setFixedSize(28, 28)
        hide.clicked.connect(self._hide_urgent)
        uh.addWidget(hide)
        self.urgent_bar.hide()
        rv.addWidget(self.urgent_bar)

        # "Did you know?": one tip per start (soundboard.tips), with a Show me
        self.tip_bar = QFrame()
        self.tip_bar.setObjectName("tipbar")
        th = QHBoxLayout(self.tip_bar)
        th.setContentsMargins(12, 6, 6, 6)
        th.setSpacing(8)
        self.tip_lbl = QLabel()
        self.tip_lbl.setTextFormat(Qt.PlainText)
        self.tip_lbl.setWordWrap(True)
        th.addWidget(self.tip_lbl, 1)
        self.tip_btn = QPushButton(_("Show me"))
        self.tip_btn.setObjectName("small")
        self.tip_btn.clicked.connect(self._tip_show_me)
        th.addWidget(self.tip_btn)
        hide = QPushButton("✕")
        hide.setObjectName("urgenthide")
        hide.setAccessibleName(_("Hide the tip"))
        hide.setToolTip(_("Hide this tip (Settings → General turns tips off)"))
        hide.setFixedSize(28, 28)
        hide.clicked.connect(self.tip_bar.hide)
        th.addWidget(hide)
        self.tip_bar.hide()
        self.tip: tips.Tip | None = None
        rv.addWidget(self.tip_bar)

        # "Looks like you're using Discord. Set up for it?" (appsetup, _app_setup): one
        # slim bar, never a window, so it's safe while a game is up
        self.setup_bar = QFrame()
        self.setup_bar.setObjectName("tipbar")
        sh = QHBoxLayout(self.setup_bar)
        sh.setContentsMargins(12, 6, 6, 6)
        sh.setSpacing(8)
        self.setup_lbl = QLabel()
        self.setup_lbl.setTextFormat(Qt.RichText)
        self.setup_lbl.setWordWrap(True)
        sh.addWidget(self.setup_lbl, 1)
        self.setup_yes = QPushButton()
        self.setup_yes.setObjectName("primary")
        self.setup_yes.clicked.connect(self._setup_yes_clicked)
        sh.addWidget(self.setup_yes)
        self.setup_no = QPushButton(_("Not now"))
        self.setup_no.setObjectName("small")
        self.setup_no.clicked.connect(self._setup_not_now)
        sh.addWidget(self.setup_no)
        self.setup_x = QPushButton("✕")
        self.setup_x.setObjectName("urgenthide")
        self.setup_x.setFixedSize(28, 28)
        self.setup_x.clicked.connect(self._setup_x_clicked)
        sh.addWidget(self.setup_x)
        self.setup_bar.hide()
        rv.addWidget(self.setup_bar)

        # Windows is in a language the board has but isn't showing: offered in that
        # language, so someone who can't read English finds it (_offer_language)
        self.lang_bar = QFrame()
        self.lang_bar.setObjectName("tipbar")
        lh = QHBoxLayout(self.lang_bar)
        lh.setContentsMargins(12, 6, 6, 6)
        lh.setSpacing(8)
        self.lang_lbl = QLabel()
        self.lang_lbl.setTextFormat(Qt.PlainText)
        self.lang_lbl.setWordWrap(True)
        lh.addWidget(self.lang_lbl, 1)
        self.lang_btn = QPushButton()
        self.lang_btn.setObjectName("small")
        self.lang_btn.clicked.connect(lambda: self.switch_language(self._lang_offered))
        lh.addWidget(self.lang_btn)
        hide = QPushButton("✕")
        hide.setObjectName("urgenthide")
        hide.setFixedSize(28, 28)
        hide.clicked.connect(self._no_language)
        lh.addWidget(hide)
        self.lang_hide = hide
        self.lang_bar.hide()
        self._lang_offered = ""
        rv.addWidget(self.lang_bar)

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
        for i, (text, _tip) in enumerate(TABS):   # no hover tip: the name says it
            self.tabs.setTabText(i, text)
            icons.set_tab_icon(self.tabs, i, TAB_KEYS[i])
        for key in taboff.KEYS:
            self.tabs.setTabVisible(TAB_INDEX[key], self.tab_shown(key))
        # one ⓘ at the end of the tab bar: the tab's explanation, instead of a banner
        self.btn_info = QPushButton()
        self.btn_info.setObjectName("tabinfo")
        self.btn_info.setFixedSize(32, 32)
        self.btn_info.setAccessibleName(_("About this tab"))
        icons.set_icon(self.btn_info, "info", size=20)
        self.btn_info.setCursor(Qt.PointingHandCursor)
        self.btn_info.setToolTip(_("What's this tab for?"))
        self.btn_info.clicked.connect(self._show_tab_info)
        # + More tabs: the tabs switched off (a new user starts with the basic ones), one
        # click to add one; only there while one is off. Right after the last tab
        self.btn_more_tabs = QPushButton(_("More tabs"))
        self.btn_more_tabs.setObjectName("moretabs")
        icons.set_icon(self.btn_more_tabs, "plus")
        self.btn_more_tabs.setCursor(Qt.PointingHandCursor)
        self.btn_more_tabs.setFocusPolicy(Qt.TabFocus)   # a click left an accent ring on it
        self.btn_more_tabs.setToolTip(_("Add a tab: radio, sending a program's sound, screen "
                                        "triggers…"))
        from soundboard.ui import moretabs
        mt = moretabs.Menu(self.btn_more_tabs)
        mt.aboutToShow.connect(lambda: self._fill_more_tabs(mt))
        mt.aboutToHide.connect(self._more_tabs_hidden)
        self.btn_more_tabs.setMenu(mt)
        self._update_more_tabs()
        self.tabs.setCornerWidget(TabEndCorner(self.tabs, self.btn_more_tabs, self.btn_info),
                                  Qt.TopRightCorner)
        # right-click a tab: hide it (+ More tabs or Settings > Tabs bring it back)
        bar = self.tabs.tabBar()
        bar.setContextMenuPolicy(Qt.CustomContextMenu)
        bar.customContextMenuRequested.connect(self._tab_menu)
        # every tab has a line for the ⓘ (the Apps tab brings its own): one tab with
        # the button and the rest without looked like a slip
        self.tab_info.setdefault("sounds_page", (
            _("Your sounds"),
            _("Your pads. Add sounds with the button, by dropping files or folders here, "
              "or from a web search; double-click (or Enter) plays one, right-click it "
              "for its hotkey, effects, categories and picture. The transport bar "
              "plays what's picked, and the bottom strip is your mic, what others hear "
              "and your headphones.")))
        self.tab_info.setdefault("radio_page", (
            _("Radio"),
            _("Internet radio stations from all over the world. Click a dot on the map or "
              "search by name, genre, country or city; it plays in your headphones, and "
              "Send puts it out to whoever's listening. Record keeps a bit as a pad.")))
        self.tab_info.setdefault("triggers", (
            _("Triggers"),
            _("Plays a sound when a picture shows up in your game: a \"YOU DIED\", a rare "
              "spawn, a queue popping. It's the Onion Watch add-on; everything happens on "
              "your PC and the screen is never saved or sent anywhere.")))
        self.tab_info.setdefault("voice", (
            _("Voice"),
            _("Change your voice live for whoever you send sounds to (pick a voice to "
              "turn it on), turn it into someone else's with AI voices, or type a line "
              "and a computer voice says it. Hear what they hear at the bottom tries it.")))
        self.tab_info.setdefault("setup_page", (
            _("Setup"),
            _("Where your sounds go (straight into your mic, the virtual cable, another "
              "device or nobody), your devices, who's listening, the equalizer, and a "
              "test that records what goes out and plays it back.")))
        self._update_info_btn = lambda *__: self.btn_info.setVisible(
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
        # only if watching has to pick up again; else when the tab is first shown
        QTimer.singleShot(TRIGGERS_LOAD_MS, self, lambda: self.load_triggers(now=False))
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
        self.mini_pp.setToolTip(_("Play / pause"))
        self.mini_pp.clicked.connect(self.toggle_play_pause)
        self.mini_st = QPushButton()
        self.mini_st.setObjectName("round")
        self.mini_st.setToolTip(_("Stop"))
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
        if text == _("Pick a sound"):   # nothing picked: no time either
            self.np_time.setText("")
            self.mini_time.setText("")

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

        self.mic_lbl, row = group("mic", _("MY MIC"),
                                  _("Your real microphone, and how loud your voice is for others"))
        self.chk_mic = QCheckBox(_("Others hear it"))
        self.chk_mic.setToolTip(_("Send your voice to others along with the sounds.\nUntick for "
                                  "sounds only: they hear your sounds but not your mic."))
        self.chk_mic.setChecked(c.mic_enabled)
        self.chk_mic.toggled.connect(self.on_mic_toggle)
        row.addWidget(self.chk_mic)
        self.vol_mic = VolumeControl(c.mic_vol, meter=True,
                                     tip=_("How loud your voice is for others. The dot shows "
                                           "activity when you talk"))
        self.mic_meter = self.vol_mic.meter
        row.addWidget(self.vol_mic)

        send_lbl, row = group("live", _("WHAT OTHERS HEAR"),
                              _("Everything going out to others right now (Discord, a game, "
                                "OBS…): your mic plus whatever is live"))
        self.out_meter = Meter()
        self.out_meter.setMinimumWidth(60)
        self.out_meter.setToolTip(_("Level of what others receive (Discord, the game, OBS…)"))
        row.addWidget(self.out_meter, 1)
        self.btn_check = QPushButton(_("Hear what they hear"))
        self.btn_check.setObjectName("miccheck")
        self.btn_check.setCheckable(True)
        self.btn_check.setToolTip(_("Plays your mic into your headphones on top of the sounds — "
                                    "exactly what others hear. A red banner shows while it's on."))
        self.btn_check.toggled.connect(self.on_mic_check)
        icons.set_icon(self.btn_check, "ear", checked_color="#ffffff")
        row.addWidget(self.btn_check)
        h.setStretch(1, 1)   # the "what others hear" box takes the room

        self.hp_lbl, row = group("headphones", _("MY HEADPHONES  ·  ONLY YOU"),
                                 _("Only what YOU hear. Doesn't change anything for others."))
        self.vol_mon = VolumeControl(c.mon_vol, tip=_("Only what YOU hear — doesn't change "
                                                      "anything for others"))
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
        add = self.btn_add = QPushButton(_("Add sounds"))
        add.setObjectName("primary")
        add.setToolTip(_("Add sound files (or drag them onto the window)"))
        add.clicked.connect(self.add_dialog)
        icons.set_icon(add, "plus", "on_accent")
        self.btn_record = QPushButton(_("Record"))
        icons.set_icon(self.btn_record, "record", "#ff4d4f")
        self.btn_record.clicked.connect(self.record_dialog)
        self.search = QLineEdit()
        # short, so it isn't cut to "Search sounds… …" at normal widths; the tooltip
        # has the rest
        self.search.setPlaceholderText(_("Search sounds or paste a link"))
        self._search_tip = _("Type to filter your sounds; Enter searches the web (YouTube, "
                             "TikTok, Myinstants…). Or paste a link (YouTube, SoundCloud, "
                             "TikTok, most media sites) to see it, then play or add it")
        self.search.setToolTip(self._search_tip)
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(SEARCH_MIN_W)   # until the window gets narrow (_init_fit)
        # typing regrids only when the pads shown change (35 ms a key with 600 pads),
        # and only once it pauses (_on_search_text); text set by the app filters at once
        self._search_wait = QTimer(self, singleShot=True, interval=SEARCH_WAIT_MS)
        self._search_wait.timeout.connect(
            lambda: self.apply_filter(self.search.text(), lazy=True))
        self._search_typed = None
        self.search.textEdited.connect(self._on_search_edited)
        self.search.textChanged.connect(self._on_search_text)
        self.search.returnPressed.connect(self.on_search_enter)
        self.btn_yt = QPushButton(_("Search"))
        self.btn_yt.setToolTip(_("Search YouTube, SoundCloud, TikTok sounds, Myinstants… for "
                                 "what's typed (or press Enter) — play or add the audio"))
        icons.set_icon(self.btn_yt, "play", size=14)
        self.btn_yt.clicked.connect(self.search_youtube)
        more = self.btn_more = QPushButton(_("Backup"))
        more.setToolTip(_("Export your sounds and settings to a file, or import a backup or "
                          "sound pack"))
        icons.set_icon(more, "history")
        mm = QMenu(more)
        icons.set_icon(mm.addAction(_("Import a backup or sound pack…"), self.import_dialog),
                       "folder")
        om = mm.addMenu(_("Import from another soundboard"))
        for src in otherboards.sources():
            om.addAction(f"{src.name}…", lambda src=src: self.import_other(src))
        mm.addSeparator()
        mm.addAction(_("Export everything (sounds + settings)…"), self.export_board)
        self._act_export_cat = mm.addAction(_("Export this category…"), self.export_category)
        mm.addSeparator()
        icons.set_icon(mm.addAction(_("Recently deleted sounds…"), self.show_deleted), "trash")
        icons.set_icon(mm.addAction(_("Open the sounds folder"), self.open_sounds_folder),
                       "folder")   # here too, for when the window's too narrow for its button
        mm.aboutToShow.connect(lambda: self._act_export_cat.setEnabled(bool(self.cfg.category)))
        more.setMenu(mm)
        self.btn_bin = QPushButton()
        self.btn_bin.setToolTip(_("Sounds you removed: bring them back, exactly as they were"))
        icons.set_icon(self.btn_bin, "trash")
        self.btn_bin.clicked.connect(self.show_deleted)
        self.btn_folder = QPushButton(_("Sounds folder"))
        self.btn_folder.setToolTip(_("Open the folder your sounds are kept in. Sound files you "
                                     "drag into it join the board by themselves."))
        icons.set_icon(self.btn_folder, "folder")
        self.btn_folder.clicked.connect(self.open_sounds_folder)
        tb.addWidget(add)
        tb.addWidget(self.btn_record)
        tb.addWidget(self.btn_folder)
        tb.addWidget(more)
        tb.addWidget(self.btn_bin)
        self._label_bin()
        # the most-used app-wide hotkeys in one click; the full list is in Settings
        self.btn_keys = QPushButton()
        self.btn_keys.setToolTip(_("Quick hotkeys: set the ones people use most, or open every "
                                   "hotkey in Settings"))
        icons.set_icon(self.btn_keys, "keyboard")
        km = QMenu(self.btn_keys)
        km.aboutToShow.connect(lambda: self._fill_quick_hotkeys(km))
        self.btn_keys.setMenu(km)
        tb.addWidget(self.btn_keys)
        tb.addWidget(self.search, 1)
        tb.addWidget(self.btn_yt)
        # the pads' order (as dragged, A-Z, newest, most played) and cards or a list
        self.btn_view = QPushButton()
        self.btn_view.setAccessibleName(_("Order and view"))
        vm = QMenu(self.btn_view)
        vm.setToolTipsVisible(True)
        vm.aboutToShow.connect(lambda: self._fill_view_menu(vm))
        self.btn_view.setMenu(vm)
        self._label_view()
        tb.addWidget(self.btn_view)
        size = QSlider(Qt.Horizontal)
        size.setRange(110, 240)
        c.pad_width = min(max(c.pad_width, 110), 240)   # the pads are built with it next
        size.setValue(c.pad_width)
        size.setFixedWidth(90)
        size.setToolTip(_("Pad size"))
        # a drag re-lays every pad at most every PAD_SIZE_WAIT_MS, not on each step
        self._pad_size_wait = QTimer(self, singleShot=True, interval=PAD_SIZE_WAIT_MS)
        self._pad_size_wait.timeout.connect(lambda: self.set_pad_width(size.value()))
        size.valueChanged.connect(lambda _v: self._pad_size_wait.isActive()
                                  or self._pad_size_wait.start())
        no_wheel(size)
        # Who's listening, one click away (the full picker is on the Setup tab)
        from soundboard.ui.destpanel import ModeCombo
        mode_lbl = QLabel(_("Listening:"))
        mode_lbl.setObjectName("muted")
        self.mode_combo = ModeCombo(self)
        tb.addWidget(mode_lbl)
        tb.addWidget(self.mode_combo)
        self._mode_pick = (mode_lbl, self.mode_combo)
        size_lbl = QLabel(_("Pad size"))
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
        # a link in the search box shows as a result card (nothing downloads until Play / Add)
        self._link_wait = QTimer(self, singleShot=True, interval=LINK_WAIT_MS)
        self._link_wait.timeout.connect(self._show_link)
        self.linkbar.link_changed.connect(self._on_link_changed)
        left.addWidget(self.linkbar)
        self.ytresults = SearchResults()
        self.ytresults.play.connect(lambda r: self._from_youtube(r, play=True))
        self.ytresults.add.connect(lambda r: self._from_youtube(r, play=False))
        self.linkbar.done.connect(lambda url, kind, ok: self.ytresults.mark(url, kind, ok))
        self.linkbar.progress.connect(self.ytresults.progress)
        left.addWidget(self.ytresults, 1)

        self.grid = PadGrid()
        self.grid.pad_w = c.pad_width
        self.grid.listed = c.pad_view == "list"
        self.grid._spacing()
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
        # Ctrl+F anywhere on the page: into the search box
        find = QShortcut(QKeySequence.Find, page)
        find.setContext(Qt.WidgetWithChildrenShortcut)
        find.activated.connect(self.focus_search)

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
        undo = QPushButton(_("Undo"))
        undo.setObjectName("primary")
        undo.setToolTip(_("Put the sound back, exactly as it was. Later: Backup → Recently "
                          "deleted sounds…"))
        undo.clicked.connect(self.undo_remove)
        uh.addWidget(undo)
        dismiss = QPushButton()
        dismiss.setObjectName("chipstop")
        dismiss.setToolTip(_("Dismiss"))
        dismiss.setFixedSize(24, 24)
        icons.set_icon(dismiss, "stop", size=10)
        dismiss.clicked.connect(self._finish_removals)
        uh.addWidget(dismiss)
        self.undo_bar.hide()
        left.addWidget(self.undo_bar)

        f, th = bar()
        self.btn_pp = QPushButton()
        self.btn_pp.setObjectName("round")
        self.btn_pp.setToolTip(_("Play / pause"))
        self.btn_pp.clicked.connect(self.toggle_play_pause)
        self._pp_icon = None
        self.btn_st = QPushButton()
        self.btn_st.setObjectName("round")
        self.btn_st.setToolTip(_("Stop"))
        self.btn_st.clicked.connect(self.stop_current)
        icons.set_icon(self.btn_st, "stop", size=16)
        for b in (self.btn_pp, self.btn_st):
            b.setFixedSize(38, 34)
        self.np_name = QLabel(_("Pick a sound"))
        self.np_name.setToolTip(_("Select a sound pad to use these playback controls."))
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
        self.np_time = QLabel("")   # blank until a sound is picked: "0:00 / 0:00" said nothing
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
        self.btn_video = QPushButton(_("Video"))
        self.btn_video.setToolTip(_("Watch this sound's video while it plays. The sound still "
                                    "goes out as normal; the video is only for you."))
        icons.set_icon(self.btn_video, "video", size=16)
        self.btn_video.clicked.connect(self.show_video)
        self.btn_video.hide()
        self._video_for: tuple[str | None, Path | None] = ("", None)   # (sid, its video)
        self._video_asking: str | None = None   # the sound whose video a thread looks up
        self.video_found.connect(self._video_found)
        self._video_win = None   # ui/videowindow.VideoWindow, made on first use
        th.addWidget(self.btn_video)
        self.speed_btn = SpeedPitchButton(
            "sounds", _("Changes every sound while it plays. To save a version, "
                        "right-click a pad → Effects."))
        self.speed_btn.changed.connect(self.on_live_speed)
        self.speed_btn.fx_changed.connect(lambda fx: setattr(self.engine, "sound_fx", fx))
        th.addWidget(self.speed_btn)
        sep = vsep()
        th.addWidget(sep)
        vol_icon = icon_label("volume", _("Volume of all your sounds"))
        th.addWidget(vol_icon)
        self.vol_sound = VolumeControl(c.sound_vol, tip=_("How loud your sounds are — type up to "
                                                          "1000% in the box"))
        self.vol_sound.changed.connect(lambda v: self.set_option("sound_vol", v))
        th.addWidget(self.vol_sound)
        self.chk_monitor = QCheckBox(_("Hear it myself"))
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
                lbl = QLabel(_("Up next"))
                lbl.setObjectName("muted")
                self._chips_hl.addWidget(lbl)
                for i, sid in enumerate(queue[:QUEUE_CHIPS]):
                    m = self.meta(sid)
                    self._chips_hl.addWidget(self._chip(
                        m.name if m else sid, _("Waits for the sounds playing to finish"),
                        lambda __=False, s=sid: self.select(s),
                        _("Take it out of the queue"),
                        lambda __=False, i=i, q=queue: self._unqueue(i, q)))
                if len(queue) > QUEUE_CHIPS:
                    more = QLabel(_("+{value} more", value=len(queue) - QUEUE_CHIPS))
                    more.setObjectName("muted")
                    self._chips_hl.addWidget(more)
            if len(ids) >= 2 or lone:
                lbl = QLabel(_("Now playing"))
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
                    name.setToolTip(_("Show this sound in the player (keeps playing)"))
                    name.clicked.connect(lambda __=False, s=sid: self.select(s))
                    stop = QPushButton()
                    stop.setObjectName("chipstop")
                    stop.setToolTip(_("Stop this sound"))
                    icons.set_icon(stop, "stop", "danger_text", size=12)
                    stop.setFixedSize(24, 24)
                    stop.clicked.connect(lambda __=False, s=sid: self._stop_sound(s))
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

    def _unqueue(self, i: int, shown: tuple[str, ...] | None = None):
        """The ✕ on the queue's chip `i`, of the queue as its row `shown` it. A row
        that's out of date does nothing: the chips are remade on the next tick, so a
        double click (or a bouncy mouse) hit the same ✕ twice, and the second took out
        the sound that had moved into that place. The row is remade at once."""
        if shown is not None and tuple(self._queue) != shown:
            return
        if 0 <= i < len(self._queue):
            del self._queue[i]
            self._say_queue()
            self._update_chips(self.engine.playing())

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
        body = QWidget()
        inner = capped(body, margins=(4, 12, 8, 12))   # not a 900 px wide card at full screen
        cols = self._setup_cols = QHBoxLayout(body)
        cols.setContentsMargins(0, 0, 0, 0)
        cols.setSpacing(16)
        lcol, rcol = QVBoxLayout(), QVBoxLayout()
        for col in (lcol, rcol):
            col.setSpacing(16)
            cols.addLayout(col, 1)
        page.setWidget(inner)

        # ---- how it works + the one thing to set in Discord
        howcard, cv = card(_("YOUR VIRTUAL MIC"), roomy=True)
        self.how_title = cv.itemAt(0).widget()   # renamed when not using the cable
        self.flow_mic = QLabel()
        self.flow_snd = QLabel(_("Your sounds, radio and voice effects"))
        arrow = QLabel(_("↓   the app mixes them together"))
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
        self.setup_show = SetupShow(height=96)   # Bun builds your mic (instead of the button)
        self.setup_show.done.connect(self._update_flow)   # (the button's back, if needed)
        cv.addWidget(self.setup_show)
        self.btn_install = QPushButton(_("Install the free virtual cable"))
        self.btn_install.setObjectName("primary")
        self.btn_install.clicked.connect(
            lambda: self.attach_mic() if self.cfg.route == "mic" else self.install_cable())
        self.btn_attach = QPushButton(_("Straight into my mic instead (no cable)"))
        self.btn_attach.setToolTip(_("Onion Board puts your sounds into your real mic, so "
                                     "Discord and games need no virtual cable and nothing picked"))
        self.btn_attach.clicked.connect(self.attach_mic)
        icons.set_icon(self.btn_attach, "mic")
        self.btn_attach.hide()
        # the ways to set it up, side by side at their own size (wraps when narrow)
        ways = Flow(gap=8)
        ways.addWidget(self.btn_attach)
        self.btn_usecable = QPushButton(_("Use the virtual cable instead"))
        self.btn_usecable.setToolTip(_("The other way to reach Discord and games: a free virtual "
                                       "cable you pick as the mic there"))
        self.btn_usecable.clicked.connect(self.use_cable_instead)
        icons.set_icon(self.btn_usecable, "cable")
        self.btn_usecable.hide()
        self.mic_attached.connect(self._mic_attached)
        self._attaching = False
        self._attach_release = None   # busy.hold on btn_install while it's being set up
        self._settle_until = 0.0      # just set up: Windows is still loading it
        icons.set_icon(self.btn_install, "cable", "on_accent")
        ways.addWidget(self.btn_install)
        ways.addWidget(self.btn_usecable)   # (after the mic's own button: the second way)
        cv.addLayout(ways)
        # straight into the mic works: the cable is only a fallback, so offer to remove it
        self.btn_rmcable = QPushButton(_("Remove the virtual cable"))
        self.btn_rmcable.setToolTip(_("Uninstalls VB-Cable. Your sounds go straight into your "
                                      "mic, so Onion Board doesn't need it"))
        icons.set_icon(self.btn_rmcable, "cable")
        self.btn_rmcable.clicked.connect(self.remove_cable)
        self.btn_rmcable.hide()
        self.cable_removed.connect(self._cable_removed)
        self._cable_gone = False   # removed this session (Windows lists it till a restart)
        # is VB-Cable's setup program there to remove it with: looked up on a thread (a
        # file check in Program Files, on every redraw, could stall on a slow disk) and
        # asked again when the devices are re-scanned. None = not known yet
        self._vb_setup: bool | None = None
        self._vb_setup_asking = False
        self.cable_setup_found.connect(self._cable_setup_found)
        self.rmcable_note = hint_label(
            _("<b>You don't need the virtual cable any more</b> — it was only the backup. Remove "
              "it, or keep it if another program uses it (Voicemeeter, another soundboard)."))
        self.rmcable_note.setTextFormat(Qt.RichText)
        self.rmcable_note.hide()
        cv.addWidget(self.rmcable_note)
        cv.addWidget(self.btn_rmcable, 0, Qt.AlignLeft)
        self.btn_rescan = QPushButton(_("I've installed it — check again"))
        self.btn_rescan.clicked.connect(lambda: self.rescan_with_feedback(self.btn_rescan))
        icons.set_icon(self.btn_rescan, "reload")
        cv.addWidget(self.btn_rescan, 0, Qt.AlignLeft)
        helpcard, hv = card(_("CONNECT YOUR CHAT"),
                            _("Choose your app for the recommended microphone settings."),
                            roomy=True)
        chat = Flow(gap=8)   # at their own size, wrapping, not five full-width bars
        self.btn_chat = QPushButton(_("Make it sound clean in Discord"))
        self.btn_chat.setToolTip(_("The Discord settings that stop it chopping up your sounds, "
                                   "and a check that listens to what Discord does to them"))
        icons.set_icon(self.btn_chat, "headphones")
        self.btn_chat.clicked.connect(lambda: self.show_chat_guide("discord"))
        chat.addWidget(self.btn_chat)
        self.btn_game = QPushButton(_("Set up game voice chat"))
        self.btn_game.clicked.connect(lambda: self.show_chat_guide("game"))
        chat.addWidget(self.btn_game)
        self.btn_meeting = QPushButton(_("Zoom, Teams or a browser call"))
        self.btn_meeting.setToolTip(_("The settings in Zoom, Microsoft Teams and calls in a web "
                                      "page that stop them treating your sounds as noise"))
        self.btn_meeting.clicked.connect(lambda: self.show_chat_guide("meeting"))
        chat.addWidget(self.btn_meeting)
        self.btn_nomic = QPushButton(_("Game has no microphone setting?"))
        self.btn_nomic.clicked.connect(self.open_windows_mic)
        chat.addWidget(self.btn_nomic)
        guide = QPushButton(_("Step-by-step guide"))
        guide.setToolTip(_("Walks you through mic, headphones, where your sounds go (your mic, "
                           "the cable, another device or nowhere) and Discord"))
        icons.set_icon(guide, "check")
        guide.clicked.connect(self.run_setup)
        chat.addWidget(guide)
        hv.addLayout(chat)
        lcol.addWidget(howcard)
        lcol.addWidget(helpcard)

        # ---- devices
        devcard, av = card(_("DEVICES"), _("Already set up for you — only change these if "
                                           "something's wrong."), roomy=True)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(12)
        self.cb_main, self.cb_mon, self.cb_mic = QComboBox(), QComboBox(), QComboBox()
        # your mic (the normal way), nobody, or a device by name (set_route). cb_main
        # isn't shown: it keeps the device list the picked device is checked against.
        self.cb_route = QComboBox()
        self.cb_route.setToolTip(_("Normally your sounds go into your mic, so everyone who hears "
                                   "your mic hears them. Only pick something else to send them "
                                   "somewhere instead: Voicemeeter, a mixer, a device OBS "
                                   "captures, or a virtual cable."))
        for r, (ic, text, cb) in enumerate((
                ("headphones", _("My headphones"), self.cb_mon),
                ("mic", _("My mic"), self.cb_mic),
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
        self.btn_cablefix = QPushButton(_("Fix the cable: both ends to 48 kHz"))
        self.btn_cablefix.setToolTip(_("Sets the cable's playback and recording side to 48 kHz, "
                                       "so it passes your sound through without converting it"))
        self.btn_cablefix.clicked.connect(lambda: busy.run_busy(
            self.btn_cablefix, _("Switching the cable to 48 kHz…"), self.fix_cable_format,
            lambda ok: _("✓ Done") if ok and not self.cable_bad else _("Couldn't — see below")))
        self.btn_cablefix.hide()
        av.addWidget(self.btn_cablefix, 0, Qt.AlignLeft)
        no_wheel(self.cb_main, self.cb_mon, self.cb_mic, self.cb_route)
        for cb, attr in ((self.cb_main, "main_device"), (self.cb_mon, "mon_device"),
                         (self.cb_mic, "mic_device"), (self.cb_route, "route")):
            cb.activated.connect(lambda _i, cb=cb, attr=attr: self.on_device(cb, attr))
        ref = QPushButton(_("Re-scan devices"))
        icons.set_icon(ref, "reload")
        ref.clicked.connect(lambda: self.rescan_with_feedback(ref))
        av.addWidget(ref, 0, Qt.AlignLeft)
        lcol.addWidget(devcard)

        # ---- who's listening: shape the sounds for the voice chat on the other end
        destcard, dv = card(_("WHO'S LISTENING"), _("Where people hear you: a game, a voice "
                                                    "chat app, or a stream. Your sounds are "
                                                    "shaped to come through clearly."),
                            roomy=True)
        from soundboard.ui.destpanel import DestPanel
        self.dest_panel = DestPanel(self)
        dv.addWidget(self.dest_panel)
        lcol.addStretch(1)

        # ---- test
        testcard, tv = card(_("TEST IT"), _("Talk while a sound plays. Records what goes out "
                                            "to others (what Discord, the game or OBS "
                                            "receives), plays it back, and tells you if your "
                                            "voice + sounds are in it."), roomy=True)
        self.btn_rec = QPushButton(_("Record 6s → play back"))
        self.btn_rec.setObjectName("primary")
        icons.set_icon(self.btn_rec, "record", "on_accent")
        self.btn_rec.clicked.connect(self.start_test)
        tv.addWidget(self.btn_rec, 0, Qt.AlignLeft)
        tv.addWidget(hint_label(_("To hear it live instead, use Hear what they hear at the "
                                  "bottom.")))
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
        utilitycard, uv = card(_("VOLUME & SHORTCUTS"), roomy=True)
        self.chk_level = QCheckBox(_("Level volumes (all sounds equally loud)"))
        self.chk_level.setChecked(c.level_volumes)
        self.chk_level.toggled.connect(self.on_level_toggle)
        uv.addWidget(self.chk_level)
        hk = QPushButton(_("Hotkeys && auto push-to-talk…"))
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
        for the button that asked ("✓ Found 7 devices", "No cable yet", …).
        Runs on the UI thread: the app's own recoveries use _refresh_off_ui."""
        self.engine.shutdown()
        rescanned = eng.rescan()
        self._vb_setup = None     # installed or removed since: look again
        self._init_devices()
        return self._rescanned(rescanned)

    def _off_ui(self, work, then):
        """work() on the engine's device thread, then then(its result) back on the UI
        thread. The caller holds the device thread's claim (engine.devices.claim())."""
        def done(result):
            def step():
                try:
                    then(result)
                except Exception:
                    self.engine.devices.release()   # the next recovery can still run
                    raise
            try:
                self.device_step.emit(step)
            except RuntimeError:   # the window is gone (quitting)
                self.engine.devices.release()
        self.engine.devices.run(work, done)

    def _refresh_off_ui(self, then=None):
        """refresh_devices without the slow part on the UI thread: closing every
        stream, the re-scan, opening them again and the cable's format (asked of
        Windows) run on the device thread. The caller holds its claim; it's released
        when this is done, then then() runs."""
        e = self.engine

        def scanned(rescanned):
            if rescanned is None:   # it raised (logged): leave the streams to the watchdog
                rescanned = False
            self._pick_devices()
            plan = self._device_plan()
            self._off_ui(lambda: self._open_devices(plan), lambda ends: opened(ends, rescanned))

        def opened(ends, rescanned):
            self._devices_opened(ends or [])
            msg = self._rescanned(rescanned)
            e.devices.release()
            if then is not None:
                then(msg)

        self._off_ui(lambda: (e.shutdown(), eng.rescan())[1], scanned)

    def _when_devices_free(self, start):
        """start() on the UI thread once it holds the device thread's claim: a
        recovery (or an earlier click) still running there finishes first, and clicks
        take their turns in order. start() hands the claim on to its _off_ui steps,
        and the last of them releases it."""
        self._dev_waiting.append(start)
        self._dev_pump()

    def _dev_pump(self):
        if not self._dev_waiting or getattr(self, "_shut_down", False):
            return
        if not self.engine.devices.claim():
            self._dev_retry.start()   # busy: look again in a moment
            return
        start = self._dev_waiting.pop(0)
        try:
            start()
        except Exception:
            self.engine.devices.release()
            raise
        finally:
            if self._dev_waiting:
                self._dev_retry.start()

    def _device_job(self, plan, then=None):
        """A device change asked for by hand, without the UI thread waiting on a slow
        driver (one stuck after a headset was pulled can take seconds, or hang): once
        the device thread is free, plan() on the UI thread returns the work, work() opens
        and closes streams on the device thread, then then(its result) back here."""
        e = self.engine

        def start():
            work = plan()

            def guarded():
                with eng.DEVICES:   # not after the app quit meanwhile
                    return None if getattr(self, "_shut_down", False) else work()

            def finish(result):
                e.devices.release()
                if then is not None and not getattr(self, "_shut_down", False):
                    then(result)
            self._off_ui(guarded, finish)
        self._when_devices_free(start)

    def _rescanned(self, rescanned: bool) -> str:
        """After a re-scan: the sounds are prepared for the new rates, and the result."""
        self._prepare_all()
        outs = eng.list_devices("output")
        if not rescanned:   # after _init_devices, whose status update would hide it
            self.status.setText(_("<span style='color:{status}'>Couldn't re-scan devices — "
                                  "restart the app to pick up new ones.</span>",
                                  status=theme.status('warn')))
            return _("Couldn't re-scan")
        if self.cfg.route == "cable" and not any(is_virtual_cable(d["name"]) for d in outs):
            self.status.setText(_("<span style='color:{status}'>Still no virtual cable. If you "
                                  "just installed it, restart your PC — Windows often only shows "
                                  "it after a restart.</span>", status=theme.status('warn')))
            return _("No cable found yet")
        n = len({d["name"] for d in outs} | {d["name"] for d in eng.list_devices("input")})
        return ngettext("✓ Found {n} device", "✓ Found {n} devices", n)

    def rescan_with_feedback(self, btn, after=None):
        """A Re-scan button: "Scanning…" while it runs (on the device thread: the
        window stays usable even if a driver is stuck), then what it found."""
        if busy.is_busy(btn):
            return   # already scanning: a double click mustn't queue a second one
        release = busy.hold(btn, _("Scanning…"))

        def done(msg):
            if after:
                try:
                    after()
                except RuntimeError:   # its dialog was closed while it scanned
                    pass
            release(msg, 3000)
        self._when_devices_free(lambda: self._refresh_off_ui(done))

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
        self._pick_devices()
        self._devices_opened(self._open_devices(self._device_plan()))

    def _pick_devices(self):
        """_init_devices' quick part (UI thread): the devices to use, from the lists."""
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

    def _device_plan(self) -> dict:
        """What _open_devices opens, worked out on the UI thread (it reads the config)."""
        c = self.cfg
        main = self._main_name()
        return {"mic": c.mic_device, "main": main, "tap": self._tap_name(),
                "mon": c.mon_device, "obs": self._obs_name(c.obs_device),
                "copies": self._copy_names(), "vm": eng.virtual_mic_for(main)}

    def _open_devices(self, plan: dict) -> list:
        """_init_devices' slow part (any thread; the app's recoveries run it on the
        device thread): open the streams and ask Windows for the cable's format.
        Returns the ends of the cable in use (cableformat.CableEnd)."""
        e = self.engine
        with eng.DEVICES:   # all of them, or none if the app quit meanwhile
            if getattr(self, "_shut_down", False):   # (not set yet while starting)
                return []
            e.set_mic_device(plan["mic"])
            e.set_main_device(plan["main"])
            e.set_tap_device(plan["tap"])
            e.set_mon_device(plan["mon"])
            e.set_obs_device(plan["obs"])
            e.set_copy_devices(plan["copies"])
        return self._cable_ends(plan["main"], plan["vm"])

    def _devices_opened(self, ends: list):
        """_init_devices' last part (UI thread): what the cable check found, the status."""
        self._set_cable_bad(ends)
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
        if time.monotonic() < self._recover_at or not e.devices.claim():
            return   # waiting, or the device thread is busy: the next check looks again

        def ask():   # Windows' device lists (COM): on the device thread
            listed: dict[str, set[str] | None] = {}
            for key, name in failing:
                kind = "input" if key == "mic" else "output"
                if kind not in listed:
                    listed[kind] = appaudio.endpoint_names(kind)
                if _listed(name, listed[kind] or ()):
                    return key, name
            return None

        self._off_ui(ask, self._recover_found)

    def _recover_found(self, found: tuple[str, str] | None):
        """_recover_devices' answer from Windows (UI thread, holding the device thread)."""
        now = time.monotonic()
        if found is None:
            # really gone (unplugged): the engine's retries pick it up again. Asking
            # Windows for its device list every check while it stays unplugged is
            # wasted work, so after a few checks look less often
            self._gone_n += 1
            if self._gone_n >= GONE_CHECKS:
                self._recover_at = now + GONE_WAIT_S
            self.engine.devices.release()
            return
        key, name = found
        self._gone_n = 0
        self._recover_at = now + RECOVER_WAIT_S[min(self._recover_n, len(RECOVER_WAIT_S) - 1)]
        self._recover_n += 1
        log.info("%s device %r is listed by Windows but won't open: re-scanning", key, name)
        self._refresh_off_ui()

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
        was, self._default_out = self._default_out, now
        c = self.cfg
        if not c.mon_follows_default:
            return
        name = self._default_output()
        if name is None and not is_virtual_cable(now):
            # plugged in since the app started: not listed yet. Re-scanned on the device
            # thread; if it's busy, the next poll sees the change again
            if not self.engine.devices.claim():
                self._default_out = was
                return
            self._refresh_off_ui(lambda _msg: self._use_default_output(self._default_output()))
            return
        self._use_default_output(name)

    def _use_default_output(self, name: str | None):
        """The headphones move to Windows' default output, `name` (as listed)."""
        c = self.cfg
        if name is None or name == c.mon_device or not c.mon_follows_default:
            return
        log.info("Windows' default output changed: headphones %r -> %r", c.mon_device, name)
        c.mon_device = name
        self._fill_combo(self.cb_mon, [d["name"] for d in eng.list_devices("output")], name)
        self.engine.set_mon_device(name)
        self._apply_send_outputs()
        self._save_now()
        self._update_status()
        self.status.setText(_("You hear your sounds on {name} now: it's Windows' default output.",
                              name=html.escape(name)))

    def _check_cable_format(self):
        """Note which ends of the cable in use aren't at 48 kHz (shown on the Setup tab)."""
        main = self._main_name()
        self._set_cable_bad(self._cable_ends(main, eng.virtual_mic_for(main)))

    @staticmethod
    def _cable_ends(main: str | None, vm: str | None) -> list:
        """The ends of the cable `main` -> `vm` with their formats (a COM call: any thread)."""
        from soundboard import cableformat
        try:
            return cableformat.pair(cableformat.cable_ends(), main, vm) if vm else []
        except Exception:  # noqa: BLE001 - only a hint
            log.debug("cable format check failed", exc_info=True)
            return []

    def _set_cable_bad(self, ends: list):
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
                msg, kind = _("✓ The cable is on 48 kHz both ends now. If Discord goes "
                              "quiet, rejoin the voice channel."), "ok"
            else:
                msg, kind = _("Couldn't change the cable's format. Set it by hand: Sound "
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
        cb.addItem(_("— none —"), None)
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
                               dev, by_hand=True)
            else:
                self.set_route(name, by_hand=True)
            return
        setattr(self.cfg, attr, name)
        if attr == "mon_device":
            # picking Windows' default keeps following it; anything else stays put
            if not self.cfg.mon_follows_default:   # not looked at while not following
                self._default_out = appaudio.default_output_name() or self._default_out
            self.cfg.mon_follows_default = name is not None and name == self._default_output()
        self._save_now()
        if attr == "mon_device":
            self._show_route()   # the headphones aren't offered as where sounds go
        e = self.engine

        def plan():   # the streams are opened on the device thread (_device_job)
            send = self._send_plan(force_main=attr == "main_device")

            def work():
                if attr == "mon_device":
                    e.set_mon_device(name)
                elif attr == "mic_device":
                    e.set_mic_device(name)
                return self._open_send(send)
            return work

        def opened(ends):
            if ends is not None:
                self._set_cable_bad(ends)
            if attr == "mic_device" and self.cfg.route == "mic" \
                    and directmic.status(name) == "other":
                self.attach_mic()   # it follows you to the new mic
            self._update_status()
            if attr == "mic_device" and is_hands_free(name):   # after: it'd be overwritten
                self.status.setText(
                    _("<span style='color:{status}'>That's a Bluetooth headset's phone-call "
                      "mic: while it's open, Windows switches the headset to call quality, so "
                      "everything you hear sounds muffled. A wired mic, or the headset's own "
                      "USB dongle, sounds much better.</span>", status=theme.status('warn')))
            self._prepare_all()
        self._device_job(plan, opened)

    def set_route(self, route: str, device: str | None = None, by_hand: bool = False):
        """Setup -> Devices -> Send my sounds to: your mic, the virtual cable, another
        device (Voicemeeter, a mixer, a device OBS captures) or nobody (only you, and the
        stream output). `device`: send into that one too (the picker and the setup guide
        pick both at once). Otherwise the picked device is kept, so switching back
        restores it. `by_hand`: picked in the box, so the streams open on the device
        thread (_device_job) and the window never waits on a slow driver."""
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
        self._save_now()
        if by_hand:
            def opened(ends):
                if ends is not None:
                    self._set_cable_bad(ends)
                self._update_status()
                self._prepare_all()

            def plan():   # worked out when its turn comes
                send = self._send_plan(force_main=True)
                return lambda: self._open_send(send)
            self._device_job(plan, opened)
            return
        self._apply_send_outputs(force_main=True)
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
                cb.addItem(_("A virtual cable (not installed yet)"), ROUTE_DEVICE)
            elif n != c.mon_device or n == target:
                cb.addItem(n, ROUTE_DEVICE + n)
        key = route if route in ("mic", "off") else ROUTE_DEVICE + (target or "")
        cb.setCurrentIndex(max(0, cb.findData(key)))
        cb.view().setMinimumWidth(cb.view().sizeHintForColumn(0) + 32)   # whole names
        cb.blockSignals(False)
        for v in list(getattr(self, "also_views", ())):   # (not built yet at start)
            v.rebuild()
        self.how_title.setText(_("YOUR VIRTUAL MIC") if route == "cable" else
                               _("YOUR MIC") if route == "mic" else _("WHERE YOUR SOUNDS GO"))

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
        ends = self._open_send(self._send_plan(force_main))
        if ends is not None:
            self._set_cable_bad(ends)

    def _send_plan(self, force_main: bool = False) -> dict:
        """What _apply_send_outputs reopens, worked out on the UI thread (it reads the
        config): only what changed."""
        e = self.engine
        plan = {}
        main = self._main_name()
        if force_main or e.names["main"] != main:
            plan["main"], plan["vm"] = main, eng.virtual_mic_for(main)
        tap = self._tap_name()
        if e.tap_name != tap:
            plan["tap"] = tap
        obs = self._obs_name(self.cfg.obs_device)   # never the cable or headphones too
        if e.names["obs"] != obs:
            plan["obs"] = obs
        copies = self._copy_names()
        if list(e.copy_names) != copies:
            plan["copies"] = copies
        return plan

    def _open_send(self, plan: dict) -> list | None:
        """_apply_send_outputs' slow part (any thread): open what `plan` says. Returns
        the cable's ends if what others hear was reopened (see _cable_ends), else None."""
        e = self.engine
        if "main" in plan:
            e.set_main_device(plan["main"])
        if "tap" in plan:
            e.set_tap_device(plan["tap"])
        if "obs" in plan:
            e.set_obs_device(plan["obs"])
        if "copies" in plan:
            e.set_copy_devices(plan["copies"])
        return self._cable_ends(plan["main"], plan["vm"]) if "main" in plan else None

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
        """The stream output: Setup -> Devices -> Also send to -> a row set to Clean,
        for streaming. None switches it off."""
        self.cfg.obs_device = name
        self.engine.set_obs_device(self._obs_name(name))
        copies = self._copy_names()   # (a copy row on it may be free to open again)
        if list(self.engine.copy_names) != copies:
            self.engine.set_copy_devices(copies)
        self._show_route()            # the rows
        self._save_now()
        self._update_status()
        self._prepare_all()

    def set_send_kind(self, name: str, stream: bool):
        """Also send to: the row on `name` gets the clean stream mix (`stream`; the
        one that had it before goes back to a copy of the call, in its place) or the
        same as the call."""
        c = self.cfg
        lst = list(c.also_send)
        if stream:
            if c.obs_device == name:
                return
            i = lst.index(name) if name in lst else len(lst)
            lst = [n for n in lst if n != name]
            if c.obs_device and c.route != "off":
                lst.insert(i, c.obs_device)
            c.also_send = lst
            log.info("also send to: %s, clean: %s", lst, name)
            self.set_obs_device(name)
        elif c.obs_device == name:
            c.also_send = list(dict.fromkeys([*lst, name]))
            log.info("also send to: %s, clean: none", c.also_send)
            self.set_obs_device(None)

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
            self.setup_hint.setText(_("Sending to others is off: your sounds play in your "
                                      "headphones and on a device set to Clean, for streaming "
                                      "(Also send to) only."))
        elif c.route == "device" and c.main_device and c.main_device == c.mon_device:
            self.setup_hint.setText(_("<span style='color:{status}'>That's your headphones too, "
                                      "so nothing is sent (you'd hear everything twice). Pick "
                                      "another device, or pick <b>Nobody</b>: your sounds "
                                      "already play in your headphones, where OBS's Desktop "
                                      "Audio picks them up.</span>", status=theme.status('warn')))
        elif c.route == "mic":
            self.setup_hint.setText(_("Your sounds go straight into <b>My mic</b>, so Discord "
                                      "and games hear them through the mic they already use."))
        elif self.virtual_mic:
            hint = (_("A virtual cable is a pipe: audio goes in at <b>{main}</b> and comes out "
                      "at <b>{virtual_mic}</b>, which Discord / the game uses as your mic.",
                      main=main, virtual_mic=self.virtual_mic))
            if self.cable_bad:
                rates = [f"{x.rate / 1000:g} kHz" for x in self.cable_bad]
                if len(rates) > 1:
                    rates = [_("{first} and {second}", first=", ".join(rates[:-1]),
                               second=rates[-1])]
                hint += _("<br><span style='color:{colour}'>One end of the cable is on "
                          "{rates}, so it converts your sound on the way through. Fix it for "
                          "the cleanest sound.</span>", colour=theme.status('warn'),
                          rates=rates[0])
            self.setup_hint.setText(hint)
        elif main and c.route == "device":
            self.setup_hint.setText(_("Whatever listens to <b>{main}</b> gets your sounds (and "
                                      "your voice, if you send it): OBS, Voicemeeter, a mixer or "
                                      "a capture card.", main=html.escape(main)))
        elif main:
            self.setup_hint.setText(_("<span style='color:{status}'>That's a normal "
                                      "speaker/headphone device, so only you will hear the "
                                      "sounds. Set <b>Send my sounds to</b> back to <b>My "
                                      "mic</b>, unless that's on purpose.</span>",
                                      status=theme.status('warn')))
        else:
            self.setup_hint.setText(_("<span style='color:{status}'>Nothing picked — only you "
                                      "will hear sounds.</span>", status=theme.status('warn')))
        down = [n for n in self.engine.copies_down() if n in self._copy_names()]
        if down:
            devices = ", ".join(f"<b>{html.escape(n)}</b>" for n in down)
            self.setup_hint.setText(
                self.setup_hint.text()
                + _("<br><span style='color:{status}'>Can't open {devices} (under Also send to). "
                    "Plugged in? It's tried again by itself.</span>",
                    status=theme.status('warn'), devices=devices))
        self.set_sending(self.btn_air.isChecked())   # its label follows the route
        self._update_flow()
        where = {"main": _("sending"), "mon": _("headphones"), "mic": _("mic"),
                 "obs": _("stream output")}
        errs = [f"{where.get(k, k)}: {v}" for k, v in e.errors_snapshot().items()]
        if errs and (self._attaching or time.monotonic() < self._settle_until):
            # setting up straight into my mic restarts Windows' audio on purpose: every
            # device drops for a few seconds and comes back by itself, so that's no error
            # (still failing once the wait is over, it shows: _mic_attached redraws then)
            errs = []
        if errs:
            self.status.setText(_("<span style='color:{status}'>Audio device problem — "
                                  "{problems}</span>", status=theme.status('error'),
                                  problems=html.escape(" · ".join(errs))))
            return
        text = ""
        xr = sum(e.xruns.values())
        self._xruns_shown = xr
        if xr:
            tip = ("" if self.cfg.latency == "high" else
                   _(" — try Settings → Audio → Audio buffering: Safer"))
            text += ("<br>" if text else "") + ngettext(
                "<span style='color:{colour}'>{n} audio drop-out since start{tip}</span>",
                "<span style='color:{colour}'>{n} audio drop-outs since start{tip}</span>",
                xr, colour=theme.status('warn'), tip=tip)
        self.status.setText(text)

    def _update_flow(self, talking=False):
        e = self.engine
        ok, bad = theme.status("ok"), theme.status("error")
        if not self.cfg.mic_enabled:
            mic = _("Your mic  <b style='color:{colour}'>not sent (sounds only)</b>",
                    colour=theme.status('warn'))
        elif e.mic_stream is None:
            mic = _("Your mic  <b style='color:{colour}'>✗ off</b>", colour=bad)
        elif talking:
            mic = _("Your mic  <b style='color:{colour}'>✓ hearing you</b>", colour=ok)
        else:
            mic = _("Your mic  <b style='color:{colour}'>✓</b>", colour=ok)
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
            out = _("Into your mic  <b>setting up…</b>")
            step = _("Click <b>Yes</b> when Windows asks for permission. Your PC's sound "
                     "drops out for a second while Windows reloads it.")
        elif settling and not (e.main_stream is not None and directmic.works(direct)
                               and e.effect_alive()):
            state = "missing"
            out = _("Into your mic  <b>starting…</b>")
            step = _("Windows is reloading your sound with Onion Board on your mic. This "
                     "takes a few seconds.")
        elif route == "mic" and directmic.needs_repair(direct):
            state = "missing"
            out = _("Into your mic  <b style='color:{colour}'>✗ needs a quick repair</b>",
                    colour=bad)
            step = _("<b style='color:{colour}'>One click:</b> Windows took Onion Board off "
                     "your mic (a driver or Windows update does that). Windows asks for "
                     "permission once, and your sounds are back in your mic.", colour=warn)
        elif route == "mic" and not directmic.works(direct):
            state = "missing"
            out = (_("Into your mic  <b style='color:{colour}'>one click to go</b>",
                     colour=warn) if direct == "missing" else
                   _("Into your mic  <b style='color:{colour}'>set up on another mic</b>",
                     colour=warn))
            step = _("<b style='color:{colour}'>One click:</b> put your sounds straight into "
                     "your mic. Windows asks for permission once; after that Discord and "
                     "games hear them through your normal mic, with nothing to set there.",
                     colour=warn)
        elif route == "mic" and e.main_stream is not None and self._direct_not_running():
            state = "unrouted"
            out = _("Into your mic  <b style='color:{colour}'>✗ Windows isn't running "
                    "Onion Board on it</b>", colour=bad)
            step = _("Another app may have your mic to itself (an <b>exclusive mode</b> "
                     "setting), or Windows hasn't loaded Onion Board on it. Repair it below, "
                     "or send through the virtual cable instead.")
        elif route == "mic" and e.main_stream is not None:
            state = "ok"
            name = html.escape(self.cfg.mic_device or _("your mic"))
            apps = e.direct_apps()
            out = (_("<b style='color:{colour}'>{name}</b> — your sounds are in it "
                     "<b style='color:{colour}'>✓</b>", colour=ok, name=name)
                   + ("  " + _("<b style='color:{colour}'>(live)</b>", colour=ok)
                      if apps else ""))
            step = (_("<b>Nothing to set.</b> Discord and games keep your normal mic, and "
                      "your sounds are in it. If sounds get chopped up, switch off the "
                      "voice app's noise suppression (Discord: <b>Input Profile → Custom</b>, "
                      "<b>Noise Suppression → None</b>, <b>Echo Cancellation</b> off. Not "
                      "Studio: it skips Onion Board).")
                    + (_("<br><br><b>Optional:</b> your mic part works, and a newer "
                         "version is here. It's not needed — update below whenever suits "
                         "you (Windows asks once, and your sound drops out for a second).")
                       if direct == "outdated" else ""))
        elif route == "mic":
            state = "unrouted"
            out = _("Into your mic  <b style='color:{colour}'>✗ can't reach it</b>",
                    colour=bad)
            err = html.escape(e.errors_snapshot().get("main", ""))
            step = (_("{error}. Repair it below, or send through the virtual cable instead.",
                      error=err) if err else
                    _("Something went wrong sending into your mic. Repair it below, or send "
                      "through the virtual cable instead."))
        elif route == "off":
            state = "off"
            out = _("Sent to others  <b>nowhere (your choice)</b>")
            step = _("<b>Nothing goes out as a mic</b>, so Discord and games don't hear your "
                     "sounds. They play in your headphones (OBS's <b>Desktop Audio</b> picks "
                     "them up there) and on the <b>stream output</b> if you set one "
                     "(Settings → Audio). To send them out, set <b>Send my sounds to</b> "
                     "back to <b>My mic</b> under Devices.")
        elif route == "device" and dev and e.main_stream is not None and not vm:
            state = "ok"
            name = html.escape(dev)
            out = _("<b style='color:{colour}'>{name}</b> — sending "
                    "<b style='color:{colour}'>✓</b>", colour=ok, name=name)
            step = _("<b>Your sounds go to {name}.</b> Whatever listens there gets them. "
                     "In OBS: Sources → + → <b>Audio Output Capture</b> → "
                     "<b>{name}</b>. In Voicemeeter or a mixer, send that input on "
                     "to wherever it should go. Not going on to a voice chat? Untick "
                     "<b>Send in mono</b> under Who's listening to keep it stereo.", name=name)
        elif route == "device" and not (dev and e.main_stream is not None):
            state = "unrouted"
            if self.cfg.main_device and dev is None:
                out = _("Sending  <b style='color:{colour}'>✗ same device as your "
                        "headphones</b>", colour=bad)
            elif dev:
                out = _("Sending  <b style='color:{colour}'>✗ can't open {device}</b>",
                        colour=bad, device=html.escape(dev))
            else:
                out = _("Sending  <b style='color:{colour}'>✗ no device picked</b>", colour=bad)
            step = (_("<b style='color:{colour}'>Almost:</b> under <b>Devices</b>, set <b>Send "
                      "my sounds to</b> to another device than your headphones, or to <b>My "
                      "mic</b>.", colour=warn)
                    if self.cfg.main_device and dev is None else
                    _("<b style='color:{colour}'>Almost:</b> under <b>Devices</b>, set <b>Send "
                      "my sounds to</b> to the device that should get your sounds (and check "
                      "it's plugged in), or to <b>My mic</b>.", colour=warn))
        elif route == "device":   # another virtual cable: its other end is the mic
            state = "ok"
            out = _("<b style='color:{colour}'>{device}</b> — your new mic "
                    "<b style='color:{colour}'>✓ working</b>", colour=ok, device=vm)
            step = _("<b>The only thing you set:</b> in Discord, your game or OBS, pick "
                     "<b style='color:{colour}'>{device}</b> as the <b>microphone</b> / audio "
                     "input.", colour=ok, device=vm)
        elif not any_cable:
            state = "missing"
            # not wrong, just not done yet: orange like the step below, not a red cross
            out = _("Virtual mic  <b style='color:{colour}'>not installed yet</b>",
                    colour=warn)
            step = (_("<b style='color:{colour}'>One-time setup:</b> put your sounds straight "
                      "into your mic, so Discord and games hear them (nothing to install). The "
                      "virtual cable is a download, and Offline mode is on. Voicemeeter, a "
                      "mixer or OBS? Pick that device under <b>Send my sounds to</b>.",
                      colour=warn) if net.offline() else
                    _("<b style='color:{colour}'>One-time setup:</b> install the free virtual "
                      "cable. It's what lets Discord and games hear your sounds — without it, "
                      "only you can hear them. Easier: set <b>Send my sounds to</b> to "
                      "<b>My mic</b> (nothing to install). Voicemeeter, a mixer or OBS? Pick "
                      "that device there.", colour=warn))
        elif vm and e.main_stream is not None:
            state = "ok"
            out = _("<b style='color:{colour}'>{device}</b> — your new mic "
                    "<b style='color:{colour}'>✓ working</b>", colour=ok, device=vm)
            step = _("<b>The only thing you set:</b> in Discord or your game, pick "
                     "<b style='color:{colour}'>{device}</b> as your <b>microphone</b>, and "
                     "switch off its noise suppression (Discord: <b>Input Profile → "
                     "Studio</b>), or it chops your sounds up.", colour=ok, device=vm)
        else:
            state = "unrouted"
            out = _("Virtual mic  <b style='color:{colour}'>✗ not connected</b>", colour=bad)
            step = _("<b style='color:{colour}'>Almost:</b> under <b>Devices</b>, set "
                     "<b>Send my sounds to</b> to your virtual cable, or to <b>My mic</b>.",
                     colour=warn)
        if state == "missing" and self.cfg.mic_enabled and e.mic_stream is None:
            # nothing is set up yet: the mic being closed is part of that, not a second
            # fault (the card showed two red crosses and the header a warning over
            # one thing to do)
            mic = _("Your mic  <b style='color:{colour}'>after the setup below</b>",
                    colour=warn)
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
        if self.setup_show.on and not mic_busy:
            self.setup_show.finish(route == "mic" and state == "ok")
        self.btn_install.setVisible((state == "missing" or update
                                     or (route == "mic" and state != "ok"))
                                    and not self.setup_show.on)   # Bun's show instead
        if not busy.is_busy(self.btn_install):
            self.btn_install.setText(
                _("Install the free virtual cable") if route != "mic" else
                _("Optional: update the mic part") if update else
                _("Put my sounds straight into my mic") if direct in ("missing", "other") else
                _("Repair (one click)"))
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
            pill = _("Only you") if short else _("Not sending to others (only you hear sounds)")
        elif state == "ok" and route == "mic":
            pill = _("Connected") if short else _("In your mic — Discord / games hear your sounds")
        elif mic_busy:
            pill = _("Setting up…") if short else _("Setting up your mic…")
        elif route == "mic" and state != "missing":
            pill = _("Not working") if short else _("Not reaching your mic — click to fix")
        elif route == "mic" and directmic.needs_repair(direct):
            pill = _("Repair needed") if short else _("One click needed — repair your mic")
        elif route == "mic":
            pill = (_("One click") if short
                    else _("One click: put your sounds straight into your mic"))
        elif state == "ok" and not vm:
            pill = _("Connected") if short else _("Sending to:  {dev}", dev=dev)
        elif state == "ok":
            pill = _("Connected") if short else _("Your mic in Discord / games:  {vm}", vm=vm)
        elif state == "missing":
            pill = (_("Setup needed") if short
                    else _("One-time setup needed — others can't hear you yet"))
        elif route == "device":
            pill = (_("Not connected") if short
                    else _("Not sending — pick a device on the Setup tab"))
        else:   # (the Setup tab offers straight into the mic first)
            pill = (_("Not connected") if short
                    else _("Not connected — click to fix"))
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
            self.toast(_("Pick your mic first (Setup tab → Devices)."), "warn")
            return
        self._attaching = True
        if self._attach_release is None:   # released by _update_flow once it works
            self._attach_release = busy.hold(self.btn_install, _("Setting up…"))
        self.setup_show.start()
        self._update_flow()
        log.info("attaching the mic effect to %s", mic)
        threading.Thread(target=self._attach_mic_work, args=(mic,),
                         daemon=True, name="mic-attach").start()

    def _attach_mic_work(self, mic: str):
        err = directmic.install(mic) or ""
        # the admin prompt can outlast the window (closed and freed meanwhile): then
        # there's nobody to tell, and emitting on the freed window raises TypeError
        if qt_valid(self):
            try:
                self.mic_attached.emit(mic, err)
            except (RuntimeError, TypeError):   # freed between the check and the emit
                pass

    def _mic_attached(self, mic: str, err: str):
        self._attaching = False
        directmic.forget_status()
        if err:
            if self._attach_release is not None:
                release, self._attach_release = self._attach_release, None
                release(_("✗ Didn't work"))
            log.warning("not put on the mic: %s", err)
            # an older mic part can still be working (the optional update failed): the
            # status then reads fine, but this attempt didn't work, so Bun mustn't cheer
            self.setup_show.finish(False)
            # the route stays on the mic: until it's set up, the cable carries the
            # sounds meanwhile (_main_name), and the one-click stays on offer
            err = _("{error}\n\nTry again any time from the Setup tab.", error=err)
            QMessageBox.warning(self, _("Couldn't put Onion Board on your mic"), err)
        else:
            log.info("on the mic now: %s", mic)
            # Windows takes a few seconds to load it: "starting…" meanwhile, then a
            # redraw when the wait is over (it works by then, or Repair comes back)
            self._settle_until = time.monotonic() + self.SETTLE_S
            QTimer.singleShot(int(self.SETTLE_S * 1000) + 200, self._update_status)
            self.cfg.route = "cable"   # so set_route() applies "mic" in full
            self.set_route("mic")
            self.toast(_("Done — Discord and games hear your sounds through your mic now."))
            if is_hands_free(mic):
                self.toast(_("That's a Bluetooth headset's call mic: some of them skip Windows' "
                             "sound effects. If nobody hears your sounds, use the headset's USB "
                             "dongle or the virtual cable."), "warn")
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
            self.toast(_("{value} still uses the virtual cable as its mic. It still hears you, "
                         "but you can set its input back to your normal mic: your sounds are in "
                         "it now.", value=heard[0][1]))

    def use_cable_instead(self):
        """Straight into my mic isn't working here: send through the virtual cable (set
        it up first if it isn't installed)."""
        if eng.virtual_outputs():
            self.set_route("cable")
            self.toast(_("Sending through the virtual cable — pick it as the mic in Discord and "
                         "games (Setup tab)."))
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
        if self._vb_setup is None:      # shown once it's known (_cable_setup_found)
            self._ask_cable_setup()
            return False
        return self._vb_setup

    def _ask_cable_setup(self):
        if self._vb_setup_asking:
            return
        from soundboard import cableremove
        self._vb_setup_asking = True
        threading.Thread(target=lambda: self.cable_setup_found.emit(
            cableremove.setup_exe() is not None), daemon=True, name="cable-setup").start()

    def _cable_setup_found(self, found: bool):
        self._vb_setup_asking = False
        if found != self._vb_setup:
            self._vb_setup = found
            self._update_flow()

    def remove_cable(self):
        """Setup tab → Remove the virtual cable: VB-Audio's uninstaller, as admin (it
        waits for Windows' prompt, so it runs on a thread)."""
        if busy.is_busy(self.btn_rmcable):
            return
        from soundboard import cableremove
        self._rmcable_release = busy.hold(self.btn_rmcable,
                                          _("Removing… click Yes when Windows asks"))
        threading.Thread(target=lambda: self.cable_removed.emit(cableremove.remove() or ""),
                         daemon=True, name="cable-remove").start()

    def _cable_removed(self, err: str):
        if err:
            log.warning("virtual cable not removed: %s", err)
            self._rmcable_release(_("✗ Not removed"))
            self.toast(_("The virtual cable wasn't removed: {err}", err=html.escape(err)), "warn")
            return
        self._rmcable_release()
        self._cable_gone = True   # stop sending into it now (Windows lists it till a restart)
        self._apply_send_outputs()
        self.toast(_("✓ The virtual cable is removed. Restart your PC to finish: until then "
                     "Windows still lists “CABLE Input” / “CABLE Output”."), "ok")
        self._update_status()

    def _direct_not_running(self) -> bool:
        """Set up on the mic, the board's own mic stream open on it for a while, and the
        effect still never ran: Windows isn't running it (exclusive mode, a driver that
        skips effects, a failed load)."""
        e = self.engine
        if e.mic_stream is None or e.effect_alive():
            self._direct_dead_since = None
            return False
        # the cached status, not endpoint_for / installed_on: those walk the registry,
        # and this runs every second on the UI thread
        if not self.cfg.mic_device or directmic.status(self.cfg.mic_device) in ("missing",
                                                                                "other"):
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
            QMessageBox.warning(self, _("Installer missing"),
                                _("Can't find {name}.", name=script.name))
            return
        try:
            subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                              "-File", str(script)],
                             creationflags=subprocess.CREATE_NEW_CONSOLE)
        except OSError as e:
            log.warning("couldn't start the cable installer", exc_info=True)
            QMessageBox.warning(
                self, _("Couldn't start the installer"),
                _("Windows wouldn't run PowerShell ({e}).\n\nYou can install VB-Cable by hand: "
                  "download it from vb-audio.com, unzip it, right-click VBCABLE_Setup_x64.exe → "
                  "Run as administrator → Install Driver.", e=errors.plain(e)))
            return
        QMessageBox.information(
            self, _("Installing the virtual cable"),
            _("A window opened that downloads VB-Cable (free) from the official VB-Audio "
              "site.\n\nWindows will ask for permission — click Yes, then click “Install "
              "Driver”.\n\nWhen it's done, click “I've installed it — check again”. If it "
              "doesn't show up, restart your PC."))

    def run_setup(self, resumed: bool = False):
        """The quick-setup guide (first launch, or the Setup tab's Step-by-step guide).
        `resumed`: reopened by itself after the restart the virtual cable needed."""
        from soundboard.ui.setupwizard import SetupWizard
        wiz = SetupWizard(self, resumed=resumed)
        wiz.exec()
        free_dialog(wiz)
        self._prepare_all()

    def open_windows_mic(self):
        vm = self.virtual_mic or _("your virtual cable")
        try:
            subprocess.Popen(["control", "mmsys.cpl,,1"], creationflags=0x08000000)
        except OSError:
            log.warning("couldn't open the Sound control panel", exc_info=True)
            QMessageBox.warning(self, _("Couldn't open the Sound settings"),
                                _("Open it yourself: press Win+R, type  mmsys.cpl  and press "
                                  "Enter, then go to the Recording tab."))
            return
        QMessageBox.information(
            self, _("Game with no mic setting"),
            _("Some games just use Windows' main mic. A sound window just opened:\n\n1.  "
              "Right-click  {vm}  →  Set as Default Device\n2.  Right-click it again  →  Set as "
              "Default Communication Device\n     (voice chat in many games asks Windows for "
              "that one)\n3.  Restart the game.\n\nHeads-up: voice typing will then also hear "
              "your sounds.\nTo undo, do the same on your normal mic.", vm=vm))

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
                and not appsetup.settings(self.cfg)["apps"]   # a remembered app switches
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
        why = (_("The game you have open uses {engine} for voice chat",
                 engine=voicesdk.NAMES.get(key, key))) if key else ""
        heard = ()
        if self.listeners is not None:
            heard = self.listeners.poll(self._heard_device())
        # for the simple modes, in order: voice chat apps on the cable, the game in
        # front, games on the cable (a per-program list would go first)
        apps = set(voicesdk.VOICE_APPS.values())
        def listening(name: str) -> str:
            return (_("{name} is listening to your mic", name=name)
                    if self.cfg.route == "mic" else
                    _("{name} is listening to the virtual cable", name=name))
        hints = [profiles.Hint(h[0], listening(h[1]),
                               profiles.VOICE.key) for h in heard if h in apps]
        if key:
            hints.append(profiles.Hint(key, why, profiles.GAME.key))
        hints += [profiles.Hint(h[0], listening(h[1]),
                                profiles.GAME.key) for h in heard if h not in apps]
        if heard:   # the game in front, if it's one of them; else the first
            key, name = next((h for h in heard if h[0] == key), heard[0])
            why = listening(name)
        if (key != self.voice_suggestion or why != self.voice_why
                or hints != self.voice_hints):
            self.voice_suggestion, self.voice_why, self.voice_hints = key, why, hints
            self._auto_dest()
            self.voice_engine.emit(key)
        self._app_setup(self._apps_seen())

    def _apps_seen(self) -> list[appsetup.Seen]:
        """The apps using your sounds now, ranked as _poll_voice ranks its hints: voice
        chat apps listening, the game in front, games listening."""
        heard = getattr(self.listeners, "apps", ())   # (a stand-in may not have them)
        voice = [appsetup.Seen(exe, name, profiles.VOICE.key) for exe, _k, name in heard
                 if exe in voicesdk.VOICE_APPS]
        games = [appsetup.Seen(exe, name, profiles.GAME.key) for exe, _k, name in heard
                 if exe not in voicesdk.VOICE_APPS]
        w = self.voice_watch
        path = getattr(w, "path", "")
        if path and getattr(w, "suggestion", None):
            base = os.path.basename(path)
            games.insert(0, appsetup.Seen(base.lower(), os.path.splitext(base)[0],
                                          profiles.GAME.key))
        out: dict[str, appsetup.Seen] = {}
        for app in voice + games:
            out.setdefault(app.exe, app)
        return list(out.values())

    def _app_setup(self, seen, now: float | None = None):
        """An app that just started using your sounds: switch to its remembered mode,
        or offer to set up for it (appsetup.decide). Nothing before the setup guide is
        done: that one picks the mode."""
        now = time.monotonic() if now is None else now
        new = self._setup_tracker.update(seen, now)
        app = self._setup_app
        if (self._setup_state == "offer" and app is not None
                and not self._setup_tracker.here(app.exe, now)):
            self._hide_setup()   # it closed: nothing to set up any more
        if not new or not self.cfg.setup_done:
            return
        d = self.cfg.dest if isinstance(self.cfg.dest, dict) else {}
        act = appsetup.decide(self.cfg, new, profiles.current(d).key, self._setup_skipped)
        if act is None:
            return
        what, app = act
        if what == "switch":
            from soundboard.ui.destpanel import set_simple
            self._setup_undo = copy.deepcopy(d)
            set_simple(self, app.simple)
            log.info("app setup: %s -> %s mode (remembered)", app.exe, app.simple)
        self._show_setup("switched" if what == "switch" else "offer", app)

    def _show_setup(self, state: str, app: appsetup.Seen):
        self._setup_app, self._setup_state = app, state
        self._setup_hide.stop()
        name = html.escape(app.name)
        mode = profiles.BY_KEY[app.simple].name
        self.setup_x.setToolTip(_("Hide"))
        self.setup_x.setAccessibleName(_("Hide"))
        self.setup_no.setVisible(state == "offer")
        if state == "offer":
            self.setup_lbl.setText(_("Looks like you're using <b>{name}</b>. Set up for it?",
                                     name=name))
            self.setup_yes.setText(_("Set up"))
            self.setup_x.setToolTip(_("Don't ask about {name} again", name=app.name))
            self.setup_x.setAccessibleName(self.setup_x.toolTip())
        elif state == "switched":
            self.setup_lbl.setText(_("{mode} mode for <b>{name}</b>.", mode=mode, name=name))
            self.setup_yes.setText(_("Undo"))
            self._setup_hide.start(SETUP_SWITCHED_MS)
        else:
            lines, button = self._setup_checks(app)
            self.setup_lbl.setText("<br>".join(lines))
            self.setup_yes.setText(button)
            if not button:
                self._setup_hide.start(SETUP_DONE_MS)
        self.setup_yes.setVisible(bool(self.setup_yes.text()))
        self.setup_bar.show()

    def _setup_checks(self, app: appsetup.Seen) -> tuple[list[str], str]:
        """The "done" card: what was set, what the app's own settings say, and the
        button for what's left ("" for none). Discord's problems already have the
        urgent bar, so they aren't said twice here."""
        ok = "<span style='color:#3fb950'>✓</span>"
        warn = "<span style='color:#d29922'>⚠</span>"
        mode = profiles.BY_KEY[app.simple].name
        lines = [_("{ok} {mode} mode on for <b>{name}</b>. Next time it switches by itself.",
                   ok=ok, mode=mode, name=html.escape(app.name))]
        guide = app.guide
        if guide == "discord":
            if self.discord_problems():
                return lines, ""   # the urgent bar above says which, with Fix Discord
            if self.discord_found:
                lines.append(_("{ok} Discord's voice settings let your sounds through.",
                               ok=ok))
                return lines, ""
            return lines, _("Check Discord")
        if guide == "meeting":
            lines.append(_("{warn} Its noise removal can wipe out music: set it to keep "
                           "the original sound.", warn=warn))
            return lines, _("Show me how")
        return lines, ""

    def _setup_yes_clicked(self):
        app, state = self._setup_app, self._setup_state
        if app is None:
            return
        if state == "offer":
            from soundboard.ui.destpanel import set_simple
            appsetup.remember(self.cfg, app.exe, app.simple)
            set_simple(self, app.simple)
            log.info("app setup: %s -> %s mode (set up)", app.exe, app.simple)
            self._show_setup("done", app)
            self.app_setup_changed.emit()
        elif state == "switched":
            if self._setup_undo is not None:
                from soundboard.ui.destpanel import _refresh_views
                self.cfg.dest = self._setup_undo
                self._setup_undo = None
                self.mode_why = ""
                destination.apply(self.cfg, self.engine)
                self._save_later()
                _refresh_views(self)
            self._hide_setup()
        elif app.guide:
            self.show_chat_guide(app.guide)
            if self._setup_state == "done":
                self._show_setup("done", app)   # the ticks, as they are now

    def _setup_not_now(self):
        if self._setup_app is not None:
            self._setup_skipped.add(self._setup_app.exe)
        self._hide_setup()

    def _setup_x_clicked(self):
        if self._setup_state == "offer" and self._setup_app is not None:
            appsetup.never(self.cfg, self._setup_app.exe)
            self._save_later()
            self.app_setup_changed.emit()
            self.toast(_("Won't ask about {name} again. Settings → General can change that.",
                         name=html.escape(self._setup_app.name)))
        self._hide_setup()

    def _hide_setup(self):
        self._setup_hide.stop()
        self._setup_state = ""
        self.setup_bar.hide()

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
            self.toast(_("{mode} mode: shaping for {target}. {mode_why}.",
                         mode=p.name, target=mode.name, mode_why=self.mode_why))
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
        self.toast(_("Who's listening: {label}. {voice_why}.",
                     label=mode.name, voice_why=self.voice_why))

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

    def needs_online(self, key: str) -> bool:
        """In Offline mode, whether a tab is of no use at all: Radio, and Triggers
        until Onion Watch is installed (its page is only the Get button). Those are
        hidden, and + More tabs doesn't offer them."""
        if not net.offline():
            return False
        if key == "radio":
            return True
        if key == "triggers":
            has = getattr(self.triggers, "has_addon", None)   # (switched off: a stand-in)
            if has is not None:
                return not has()
            from soundboard import watchaddon
            return watchaddon.installed() is None and watchaddon.local_zip() is None
        return False

    def tab_shown(self, key: str) -> bool:
        """Whether a tab is in the tab bar: switched on, and of use (needs_online)."""
        return self.tab_on(key) and not self.needs_online(key)

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
            v.fx_changed.connect(self._voice_fx_changed)
            v.speech_changed.connect(lambda s: self.set_option("speech", s))
            v.clip_ready.connect(self.on_clip)
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

    def _more_tab_keys(self) -> list[str]:
        """The tabs + More tabs offers: switched off, and of use (not Radio offline)."""
        return [k for k in taboff.KEYS if not self.tab_on(k) and not self.needs_online(k)]

    def _update_more_tabs(self):
        self.btn_more_tabs.setVisible(bool(self._more_tab_keys()))

    def _fill_more_tabs(self, menu: QMenu):
        """+ More tabs: a card for each tab that's switched off, with what it's good
        for (click: it's added and opened), then Settings > Tabs to pick them all."""
        from soundboard.ui import moretabs
        off = [(k, *TABS[TAB_INDEX[k]]) for k in self._more_tab_keys()]
        self._more_added = False
        usage.used("more-tabs-opened")
        moretabs.fill(menu, off, self._add_from_more, lambda: self.open_settings("tabs"))

    def _more_tabs_hidden(self):
        """+ More tabs closed: counted when nothing was added (a pick's triggered
        signal comes after the menu hides, so this looks once that's through)."""
        def check():
            if not getattr(self, "_more_added", True):
                usage.used("more-tabs-closed")
            self._more_added = True
        QTimer.singleShot(0, check)

    def _add_from_more(self, key: str):
        self._more_added = True
        usage.used(f"more-tabs-added-{key}")
        self._add_tab(key)

    def _add_tab(self, key: str):
        self.set_tab_on(key, True)
        self.tabs.setCurrentIndex(TAB_INDEX[key])

    def _tab_menu(self, pos):
        """Right-click on a tab: Hide this tab (not Sounds or Setup)."""
        bar = self.tabs.tabBar()
        i = bar.tabAt(pos)
        if i >= 0:
            self.tab_menu(i).exec(bar.mapToGlobal(pos))

    def tab_menu(self, i: int) -> QMenu:
        key = TAB_KEYS[i]
        menu = QMenu(self)
        menu.setAttribute(Qt.WA_DeleteOnClose)
        if key in taboff.KEYS:
            act = menu.addAction(_("Hide this tab"))
            act.triggered.connect(lambda: self.hide_tab(key))
        else:
            act = menu.addAction(_("This tab is always shown"))
            act.setEnabled(False)
        menu.addSeparator()
        menu.addAction(icons.icon("settings"), _("Choose tabs in Settings…"),
                       lambda: self.open_settings("tabs"))
        return menu

    def hide_tab(self, key: str):
        """Hide a tab from its right-click menu, saying where to get it back."""
        self.set_tab_on(key, False)
        usage.used(f"tab-hidden-{key}")
        self.toast(_("{tab} hidden. Bring it back with + More tabs or Settings > Tabs.",
                     tab=TABS[TAB_INDEX[key]][0]))

    def _tab_live(self, key: str, on: bool):
        """The live badge on the Voice, Triggers or Apps tab."""
        page = getattr(self, key)
        if key == "voice":   # the active voice's picture, when there is one
            set_tab_live(self.tabs, TAB_INDEX[key], on,
                         _("● ON: others hear your changed / computer voice"), page.tab_icon())
        elif key == "triggers":
            set_tab_live(self.tabs, TAB_INDEX[key], on, _("● ON: watching your screen"),
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
        self.tabs.setTabVisible(i, self.tab_shown(key))
        self._update_info_btn()
        self._update_more_tabs()
        log.info("tab %s switched %s", key, "on" if on else "off")
        if on:   # once per install, sent now (usage.py: a daily count could be a day off)
            usage.step(self.cfg, f"added-{key}-tab")
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
            self.load_triggers(now=False)   # (or once it's shown)
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
        self._update_flow()   # the cable's install button (_cable_follow_switch)
        self._search_follow_switch()
        self._offline_follow()
        if hasattr(self, "_fit"):   # buttons came or went: what fits is measured again
            self._refit()

    def _offline_follow(self):
        """Offline mode: the Offline pill in the header, and the tabs that only work
        online (needs_online) out of the tab bar and + More tabs; back when it's off."""
        self.btn_offline.setVisible(net.offline())
        for key in ("radio", "triggers"):
            i = TAB_INDEX[key]
            shown = self.tab_shown(key)
            if not shown and self.tabs.currentIndex() == i:
                self.tabs.setCurrentIndex(0)
            self.tabs.setTabVisible(i, shown)
        self._update_info_btn()
        self._update_more_tabs()

    def _search_follow_switch(self):
        """Finding sounds online switched off: no Search button, and the search box
        only filters your own sounds (and says so)."""
        online = self.ytresults.available()
        self.btn_yt.setVisible(online)
        self.search.setPlaceholderText(_("Search sounds or paste a link") if online else
                                       _("Search your sounds"))
        self.search.setToolTip(self._search_tip if online else _("Type to filter your sounds"))

    def _cable_follow_switch(self):
        """The cable's install button downloads it (from vb-audio.com): gone in Offline
        mode, greyed with its switch off. On the mic route the same button sets up the
        mic, which goes nowhere online."""
        if busy.is_busy(self.btn_install):
            return
        cable = self.cfg.route != "mic"
        allowed = not cable or net.allowed("setup_downloads")
        if cable and net.offline():
            self.btn_install.hide()
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
            self.toast(html.escape(_("Radio was switched off, so the station stopped.")))

    def _on_tor(self):
        """Something is waiting for Tor: say so (once), and when it's ready or failed."""
        t = tor.manager()
        if t.state == tor.STARTING and t.waiting:
            say = ("starting", _("Connecting to Tor… what you asked for goes once it's "
                                  "connected (Settings → Privacy & security shows how far "
                                  "it is)."), "")
        elif t.state == tor.READY and self._tor_told == "starting":
            say = ("ready", _("✓ Connected to Tor."), "ok")
        elif t.state == tor.FAILED and self._tor_told in ("starting", "") and t.waiting:
            say = ("failed", _("Couldn't connect to Tor: {error}. Nothing was sent "
                               "without it.", error=t.message), "error")
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
            self.status.setText(_("<span style='color:{status}'>Couldn't save your settings — "
                                  "see the log in %APPDATA%\\OnionBoard.</span>",
                                  status=theme.status('error')))
            self.toast(_("Couldn't save your settings — see the log in %APPDATA%\\OnionBoard."),
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
        return ([getattr(self.cfg, a) for a, *__ in HOTKEY_ACTIONS if getattr(self.cfg, a)]
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
            self.status.setText(_("<span style='color:{status}'>{devices} is open in another "
                                  "program (a music app?), so its pads don't work here until "
                                  "that program lets go of it.</span>",
                                  status=theme.status('warn'),
                                  devices=html.escape(", ".join(busy))))

    def on_replay_state(self):
        if self.replay.enabled and self.replay.error:
            self.status.setText(_("<span style='color:{status}'>Instant replay can't listen: "
                                  "{error}</span>", status=theme.status('warn'),
                                  error=html.escape(self.replay.error)))

    def save_replay(self):
        """The instant-replay hotkey: the last seconds of what you heard become a pad."""
        data = self.replay.clip()
        if len(data) < int(0.2 * SR):
            self.cue("fail")
            why = self.replay.error or ngettext(
                "nothing has played on this PC in the last {n} second",
                "nothing has played on this PC in the last {n} seconds", self.replay.seconds)
            self.status.setText(_("<span style='color:{status}'>Nothing to save: {why}.</span>",
                                  status=theme.status('warn'), why=html.escape(why)))
            return
        self.on_clip(data, _("Replay {time}", time=time.strftime("%H.%M.%S")))
        self.cue("saved")

    def on_hotkeys_failed(self, failed: list[str]):
        if failed:
            log.warning("hotkeys another program already owns: %s", failed)
            self.status.setText(_("<span style='color:{status}'>Another program is already "
                                  "using {keys} — pick a different hotkey.</span>",
                                  status=theme.status('warn'),
                                  keys=html.escape(", ".join(pretty_key(c) for c in failed))))

    def set_global_hotkey(self, attr: str, combo: str):
        """Set one of the app-wide hotkeys (or ptt_key). A combo can only do one thing,
        so it's taken off any other action or sound that had it, and a toast says what
        lost it: a key quietly going off a pad was a surprise the next time it was
        pressed in a game."""
        lost = []
        if combo:
            for other, _action, label, _desc in HOTKEY_ACTIONS:
                if other != attr and getattr(self.cfg, other) == combo:
                    setattr(self.cfg, other, "")
                    lost.append(label)
            for m in self.cfg.sounds:
                if m.hotkey == combo:
                    m.hotkey = ""
                    lost.append(f"“{m.name}”")
                    if m.id in self.pads:
                        self.pads[m.id].update()
            lost += [_("a random sound from “{name}”", name=c)
                     for c, k in self.cfg.category_hotkeys.items() if k == combo]
            self._clear_category_hotkey(combo)
            if attr != "ptt_key" and self.cfg.ptt_key == combo:
                self.cfg.ptt_key = ""
                lost.append(_("auto push-to-talk"))
        if attr == "replay_hotkey" and combo and not self.cfg.replay_hotkey:
            self.toast(REPLAY_NOTE)   # instant replay just went on
        setattr(self.cfg, attr, combo)
        self._save_now()
        self.register_hotkeys()
        if lost:
            what = (_("auto push-to-talk") if attr == "ptt_key"
                    else next((label for a, _ac, label, _d in HOTKEY_ACTIONS if a == attr), attr))
            self.toast(_("{hotkey} is {what} now — it was the key for {lost}",
                         hotkey=html.escape(pretty_key(combo)), what=html.escape(what),
                         lost=html.escape(_(" and ").join(lost))), "warn")

    QUICK_HOTKEYS = ("stop_hotkey", "pause_hotkey", "random_hotkey", "last_hotkey",
                     "mic_hotkey", "hotkeys_off_hotkey", "overlay_hotkey")

    def _fill_quick_hotkeys(self, menu: QMenu):
        """The Sounds tab's keyboard button: the common hotkeys with their keys (click
        one to set it), then a way into Settings → Hotkeys for the rest."""
        menu.clear()
        labels = {attr: label for attr, _a, label, _d in HOTKEY_ACTIONS}
        labels["ptt_key"] = _("Auto push-to-talk key")
        for attr in (*self.QUICK_HOTKEYS, "ptt_key"):
            combo = getattr(self.cfg, attr)
            key = pretty_key(combo) or (_("Off") if attr == "ptt_key" else _("not set"))
            menu.addAction(f"{labels[attr]}	{key}",
                           lambda a=attr: self._quick_set_hotkey(a))
        menu.addSeparator()
        icons.set_icon(menu.addAction(_("All hotkeys…"), lambda: self.open_settings("hotkeys")),
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

    # ------------------------------------------------------------------ language
    def _offer_language(self):
        """Windows speaks a language the board has, and no language was ever picked:
        a bar, in that language, offering to switch (until switched or dismissed)."""
        code = i18n.offer()
        if not code or self.cfg.language or LANG_OFFER_SEEN in self.cfg.tips_seen:
            return
        name = i18n.name_of(code)
        self._lang_offered = code
        text, button, hide = i18n.in_language(code, lambda: (
            # the way there in the catalog's own words for the gear, the page and the box
            _("Onion Board is also in {name}. You can change it any time in {where}.",
              name=name, where=" → ".join((_("Settings"), _("Appearance"), _("Language")))),
            _("Switch to {name}", name=name), _("No thanks")))
        # a right-to-left line that starts with "Onion Board" still reads right to left
        self.lang_lbl.setText("‏" + text if i18n.is_rtl(code) else text)
        self.lang_btn.setText(button)
        self.lang_hide.setAccessibleName(hide)
        self.lang_hide.setToolTip(hide)
        for w in (self.lang_lbl, self.lang_btn):   # its own direction (Arabic offered
            w.setLayoutDirection(Qt.RightToLeft if i18n.is_rtl(code) else Qt.LeftToRight)
        self.lang_bar.show()

    def _no_language(self):
        self.lang_bar.hide()
        if LANG_OFFER_SEEN not in self.cfg.tips_seen:
            self.cfg.tips_seen.append(LANG_OFFER_SEEN)
        self._save_later()

    def switch_language(self, code: str, restart: bool = True):
        """Show the app in language `code` from the next start (now, with `restart`:
        text already on screen can't change language)."""
        if not code:
            return
        self.cfg.language = code
        self.lang_bar.hide()
        self._save_later()
        log.info("language picked: %s", code)
        if restart and code != i18n.current():
            self.restart_app()

    # ------------------------------------------------------------------ tips
    def _start_tips(self):
        if not self._maybe_tip():
            self._tip_timer.start()

    def _game_up(self) -> bool:
        return self.overlay.is_open or tips.fullscreen_in_front()

    def _maybe_tip(self) -> bool:
        """Show today's tip if it's time. True when there's nothing more to try this
        start (one shown, or none due)."""
        tip = tips.due(self.cfg, self.tab_on)
        if tip is None:
            self._tip_timer.stop()
            return True
        if not self.isVisible() or self.isMinimized() or self._game_up():
            return False
        self.show_tip(tip)
        self._tip_timer.stop()
        return True

    def show_tip(self, tip: tips.Tip):
        self.tip = tip
        self.tip_lbl.setText(_("💡 Did you know? {text}", text=tip.text))
        self.tip_bar.show()
        if tip.key not in self.cfg.tips_seen:
            self.cfg.tips_seen.append(tip.key)
        self.cfg.tip_day = tips.today()
        self._save_later()

    def _tip_show_me(self):
        tip, self.tip = self.tip, None
        self.tip_bar.hide()
        if tip is None:
            return
        kind, __, where = tip.show.partition(":")
        if kind == "tab":
            self.tabs.setCurrentIndex(TAB_INDEX[where])
        elif kind == "settings":
            self.open_settings(where)
        elif kind == "search":
            self.tabs.setCurrentWidget(self.sounds_page)
            self.search.setFocus()
        elif kind == "record" and hasattr(self, "record_dialog"):
            self.tabs.setCurrentWidget(self.sounds_page)
            self.record_dialog()
        elif kind == "deleted":
            self.show_deleted()
        else:
            self.tabs.setCurrentWidget(self.sounds_page)

    def set_tips_on(self, on: bool):
        self.cfg.tips_on = bool(on)
        if not on:
            self.tip_bar.hide()
        self._save_later()

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
        icon when it goes quiet. Each swap makes Windows redraw the taskbar and tray
        icons in Explorer, so a step is held until the level clearly leaves it
        (ICON_GLOW_HOLD): on songs that's 3-10 times fewer swaps for the same glow."""
        x = min(1.0, level * 1.4) * GLOW_STEPS
        step = min(GLOW_STEPS, round(x))
        if self._icon_step >= 0 and abs(x - self._icon_step) < 0.5 + ICON_GLOW_HOLD:
            step = self._icon_step
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
                self.toast(_("The Voice tab is switched off (Settings > Tabs)."))
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
            _("<span style='color:{status}'>Hotkeys are off — {key} turns them back on.</span>",
              status=theme.status('warn'), key=html.escape(key)) if self._hotkeys_off
            else _("Hotkeys are on again."))

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
        self.status.setText(_("Category: {value}", value=html.escape(name or 'All')))

    def step_sound_volume(self, step: int):
        """The louder / quieter hotkeys: the sounds' volume box by 10 % a press."""
        pct = self.vol_sound.spin.value()
        new = min(max((round(pct / 10) + step) * 10, 0), self.vol_sound.spin.maximum())
        self.vol_sound.spin.setValue(new)   # -> set_option("sound_vol")
        self.cue((880, 1175) if step > 0 else (880, 659))
        self.status.setText(_("Sounds: {new}%", new=new))

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
            self.toast(_("No sounds in “{cat}” to play yet", cat=html.escape(cat)) if cat
                       else _("No sounds to play yet"), "warn")
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
            text = (_("Muted — others hear nothing"), _("Muted"), "")
        elif others:
            text = (_("Live — others hear you"), _("Live"), "")
        elif stream:
            text = (_("Live — stream output only"), _("Live"), "")
        else:
            text = (_("Only you hear sounds"), _("Only you"), "")
        self.btn_air.setText(text[self._air_size])
        if not on:
            tip = _("Click to go live again: others hear you and your sounds")
        elif others:
            tip = (_("Click to mute: nothing at all goes out to others (Discord, the game, "
                     "OBS…). You still hear everything"))
        elif stream:
            tip = (_("Nothing goes out to others, only to the stream output. Click to mute that "
                     "too (you still hear everything)"))
        else:
            tip = (_("Nothing goes out to others: pick where to send on the Setup tab (Send my "
                     "sounds to)"))
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

    def load_triggers(self, now: bool = True):
        """Put the Onion Watch add-on into the Triggers tab. It took 0.4-1 s on the UI
        thread, so it waits until the window is up: a 0 ms timer would still run before
        Windows' first paint message, a TRIGGERS_LOAD_MS one runs after it. Runs once.
        `now` False (the window's start, the tab switched back on): only if it has to
        run now (watching was on); otherwise the tab loads it when first shown."""
        if not self.triggers.pending or self._shut_down:
            return
        if not now and not self.triggers.needed_now():
            return
        self.triggers.load()
        if self.triggers.needs_nudge():
            self._nudge_triggers(self.tabs.indexOf(self.triggers))

    def _nudge_triggers(self, index: int):
        """Triggers were being watched before they moved into the Onion Watch add-on,
        which isn't installed: tint the tab and say so once, until the tab is opened."""
        icons.set_tab_icon(self.tabs, index, "triggers", "warn_text")
        QTimer.singleShot(0, self, lambda: self.status.setText(
            _("<span style='color:{status}'>Your screen triggers now come from the free Onion "
              "Watch add-on: open the Triggers tab to get it.</span>",
              status=theme.status('warn'))))

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
        self._link_url = self.linkbar.url
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
        if ytdl.as_link(text):
            self._show_link()
            return
        if not self.ytresults.available():
            return
        if not self.ytresults.search(text):
            if not text.strip():
                self.search.setFocus()
                busy.flash(self.btn_yt, _("Type something first"))
            return
        self._pads_scroll.hide()
        self._cat_row.hide()

    def on_search_enter(self):
        self.flush_search()   # a link pasted a moment ago: the link bar has it now
        if ytdl.as_link(self.search.text()):
            self._show_link()   # its card, at once: nothing downloads until Play / Add
        else:
            self.search_youtube()

    def _on_link_changed(self, url: str):
        """The search box's link changed: show its card once it stays (a link typed by
        hand is a new one at every key); no link any more: its card goes."""
        if url:
            self._link_wait.start()
            return
        self._link_wait.stop()
        if self.ytresults.link and not self.ytresults.isHidden():
            self.ytresults.close_results()

    def _show_link(self):
        """The search box's link as a result card: looked up, not downloaded."""
        self._link_wait.stop()
        url = self.linkbar.url
        if not url or self.is_mini() or not self.ytresults.show_link(url):
            return
        self._pads_scroll.hide()
        self._cat_row.hide()

    def _from_youtube(self, r, play: bool):
        if play and r.url == self._link_url and self.audio.get(LINK_ID) is not None:
            self.select(LINK_ID)   # already in the player: Play / Space pause and resume it
            self.toggle_play_pause()
            return
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
                self.status.setText(_("<span style='color:{status}'>Can't play “{name}”{why}. If "
                                      "the file was moved or deleted, remove the pad and add the "
                                      "sound again.</span>",
                                      status=theme.status('error'), name=name, why=why))
            else:
                self.status.setText(_("“{name}” is still loading…", name=html.escape(m.name)))
            return
        self.select(sid)
        self._last_sid = sid
        if sid != LINK_ID:
            m.plays += 1   # Most played
            if not self._count_save.isActive():
                self._count_save.start()
        v = self.engine.play(sid, data, self.gain_for(m), loop=m.loop,
                             mode="restart" if m.mode == "queue" else m.mode,
                             fade_in=m.fade_in, fade_out=m.fade_out,
                             only=("main", "obs") if m.only_them else None)
        self._wake()
        if v is not None:   # a new install's first steps (usage.py; once each, if counted)
            usage.step(self.cfg, "played-sound")
            if self.cfg.route != "off":
                usage.step(self.cfg, "sent-to-others")
        if v is None and not self.engine.active_outputs():
            self.status.setText(_("<span style='color:{status}'>No audio device is open — pick "
                                  "one in Setup.</span>", status=theme.status('warn')))

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
            self.toast(_("No sounds in “{name}” to play yet", name=html.escape(name)), "warn")
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
            name, n = html.escape(m.name if m else "?"), len(self._queue) - 1
            self._queue_said = (
                _("Up next: “{name}” (+{n} more) · Stop all clears the queue", name=name, n=n)
                if n else _("Up next: “{name}” · Stop all clears the queue", name=name))
            self.status.setText(self._queue_said)
        elif getattr(self, "_queue_said", None) == self.status.text():   # ran out / cleared
            self._queue_said = None
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

    def _space_action(self):
        """What Space does on the tab showing (ui/spacekey.py): play / pause the
        player's sound on Sounds, play / stop the radio on Radio; None elsewhere."""
        page = self.tabs.currentWidget()
        if page is self.sounds_page:
            return self.toggle_play_pause if self.current else None
        if page is self.radio_page:
            return getattr(self.radio, "toggle_play", None)
        return None

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
        """The player's ■. A second press within a double-click of the first that
        would stop a different sound is a double click (or a bouncy mouse): the queue's
        next sound had already taken the player, and it went too."""
        now, (at, was) = time.monotonic(), self._stopped_at
        if (self.current and was and self.current != was
                and now - at < QApplication.doubleClickInterval() / 1000):
            return
        if self.current:
            self._stopped_at = (now, self.current)
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
        self.status.setText(_("Rendering the preview…"))

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
            self.status.setText(_("<span style='color:{status}'>Couldn't render the preview (see "
                                  "the log).</span>", status=theme.status('warn')))
            self.toast(_("Couldn't render the preview with these effects (see the log)."), "warn")
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
        for m in library.sorted_sounds(self.cfg.sounds, self.cfg.pad_sort):
            p = self.pads.get(m.id)
            if p is None:
                p = Pad(m, self.cfg.pad_width)
                p.activated.connect(self.play)
                p.space.connect(self.space_pad)
                p.chosen.connect(self.select)
                p.pick.connect(self.selection.on_pick)
                p.step.connect(self.grid.focus_step)
                p.menu.connect(self.pad_menu)
                p.nudge.connect(self.nudge_volume)
                p.rename.connect(self.rename_sound)
                p.edit.connect(self.edit)
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
        self.cat_tabs = SnugTabBar()
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
        add.setAccessibleName(_("New category"))
        add.setToolTip(_("New category (a page of pads). Right-click a pad to put it in one; "
                         "right-click a category to rename or delete it."))
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
        for c in self.cfg.categories:
            n = sum(1 for m in self.cfg.sounds if c in m.tags)
            i = tb.addTab(c.replace("&", "&&"))   # a lone & would be a shortcut key
            tb.setTabData(i, c)                   # the real name; All's data stays None
            col = self.cfg.category_colors.get(c)
            tb.setTabIcon(i, self._dot_icon(col) if col else QIcon())
            hk = self.cfg.category_hotkeys.get(c)
            progs = catswitch.programs_for(self.cfg.category_programs, c)
            tb.setTabToolTip(i, ngettext("{n} sound", "{n} sounds", n)
                             + (_(" · {hk} plays a random one", hk=pretty_key(hk)) if hk else "")
                             + (_(" · shows by itself when {progs} is in front",
                                  progs=', '.join(progs))
                                if progs else "")
                             + _(" · right-click to rename, delete or give it a random-sound "
                                 "hotkey · drag to reorder"))
        cat = self.cfg.category
        tb.setCurrentIndex(self.cfg.categories.index(cat) + 1 if cat in self.cfg.categories
                           else 0)
        tb.blockSignals(False)

    @staticmethod
    def _dot_icon(color: str) -> QIcon:
        """A category's colour on its tab: a round dot."""
        dpr = QApplication.instance().devicePixelRatio() if QApplication.instance() else 1.0
        pm = QPixmap(round(12 * dpr), round(12 * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        p.drawEllipse(1, 1, 10, 10)
        p.end()
        return QIcon(pm)

    def set_category_color(self, name: str, color: str):
        """A category's colour on its tab and the overlay ("" takes it off)."""
        if color:
            self.cfg.category_colors[name] = color
        else:
            self.cfg.category_colors.pop(name, None)
        self._save_now()
        self._fill_categories()
        if getattr(self, "overlay", None) is not None:
            self.overlay.sounds_changed()

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
            name, ok = QInputDialog.getText(self, _("New category"),
                                            _("Name (e.g. Memes, Music, Game 1):"))
            name = name if ok else ""
        name = (clean_tags([name]) or [""])[0]
        if name.lower() == ALL.lower():   # would look like the built-in tab
            self.toast(_("“{all}” is the built-in tab — pick another name", all=ALL), "warn")
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
            msg = _("Took “{name}” out of {category}",
                    name=html.escape(m.name), category=html.escape(name))
        else:
            m.tags.append(name)
            msg = _("✓ Added “{name}” to {category}",
                    name=html.escape(m.name), category=html.escape(name))
        if self.cfg.scoped_hotkeys:   # where its key works changed with its categories
            self.register_hotkeys()
        self._save_now()
        self._fill_categories()
        self.apply_filter(self.search.text())
        self.toast(msg)

    def focus_search(self):
        """Ctrl+F: the cursor into Search sounds, with what's there selected."""
        self.search.setFocus(Qt.ShortcutFocusReason)
        self.search.selectAll()

    def rename_sound(self, sid: str, new: str | None = None):
        """F2 on a pad (and the pad menu's Rename…): just the name, without the Edit
        window."""
        m = self.meta(sid)
        if m is None:
            return
        if new is None:
            new, ok = QInputDialog.getText(self, _("Rename sound"), _("New name:"), text=m.name)
            new = new if ok else ""
        new = new.strip()
        if not new or new == m.name:
            return
        m.name = new
        if sid in self.pads:
            self.pads[sid].update()
        if self.current == sid:
            self._set_np_name(new)
        self._save_now()
        self.toast(_("✓ Renamed to “{new}”", new=html.escape(new)), "ok")

    def rename_category(self, old: str, new: str | None = None):
        if new is None:
            new, ok = QInputDialog.getText(self, _("Rename category"), _("New name:"), text=old)
            new = new if ok else ""
        new = (clean_tags([new]) or [""])[0]
        if new.lower() == ALL.lower():
            self.toast(_("“{all}” is the built-in tab — pick another name", all=ALL), "warn")
            return
        if not new or new == old or old not in self.cfg.categories:
            return
        if new.lower() in {c.lower() for c in self.cfg.categories if c != old}:
            QMessageBox.information(self, _("Rename category"), _("There's already a “{new}”.",
                                                               new=new))
            return
        self.cfg.categories[self.cfg.categories.index(old)] = new
        if old in self.cfg.category_hotkeys:
            self.cfg.category_hotkeys[new] = self.cfg.category_hotkeys.pop(old)
        if old in self.cfg.category_colors:
            self.cfg.category_colors[new] = self.cfg.category_colors.pop(old)
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
        self.toast(_("✓ Renamed to “{new}”", new=html.escape(new)), "ok")

    def delete_category(self, name: str):
        """Delete a category. Its sounds stay (in All and their other categories)."""
        if name not in self.cfg.categories:
            return
        n = sum(name in m.tags for m in self.cfg.sounds)
        if n and QMessageBox.question(
                self, _("Delete category"),
                ngettext("Delete the “{name}” category? Its {n} sound stay in All (and any other "
                         "categories they're in).",
                         "Delete the “{name}” category? Its {n} sounds stay in All (and any "
                         "other categories they're in).",
                         n, name=name)) != QMessageBox.Yes:
            return
        self.cfg.categories.remove(name)
        self.cfg.category_hotkeys.pop(name, None)
        self.cfg.category_colors.pop(name, None)
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
        a_ren = menu.addAction(icons.icon("edit"), _("Rename…"))
        hk = self.cfg.category_hotkeys.get(name, "")
        a_hk = menu.addAction(icons.icon("keyboard"),
                              _("Random-sound hotkey: {hk} (change…)", hk=pretty_key(hk)) if hk
                              else _("Set a random-sound hotkey…"))
        a_nohk = menu.addAction(_("Clear the random-sound hotkey")) if hk else None
        a_rand = menu.addAction(icons.icon("play"), _("Play a random sound from it"))
        a_all = menu.addAction(icons.icon("next"), _("Play them all, in order"))
        a_shuf = menu.addAction(icons.icon("next"), _("Play them all, shuffled"))
        a_exp = menu.addAction(icons.icon("folder"), _("Export as a sound pack…"))
        cm = menu.addMenu(icons.icon("palette"), _("Colour"))
        now = self.cfg.category_colors.get(name, "")
        a_cols = {}
        for col in PAD_COLORS:
            picked = col.lower() == now.lower()
            # the dot sits where a tick would: the one it has now is bold, with a ✓
            a = cm.addAction(self._dot_icon(col), COLOUR_NAMES.get(col, col)
                             + ("  ✓" if picked else ""))
            if picked:
                bold = a.font()
                bold.setBold(True)
                a.setFont(bold)
            a_cols[a] = col
        if now:
            cm.addSeparator()
            a_cols[cm.addAction(_("No colour"))] = ""
        menu.addSeparator()
        a_prog = menu.addAction(icons.icon("apps"), _("Show this when a program is in front…"))
        a_unprog = {menu.addAction(_("Stop showing this for {exe}", exe=exe)): exe
                    for exe in catswitch.programs_for(self.cfg.category_programs, name)}
        menu.addSeparator()
        a_del = menu.addAction(icons.icon("trash", "danger_text"),
                               _("Delete category (keeps the sounds)"))
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
        elif act in a_cols:
            self.set_category_color(name, a_cols[act])
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
        self.toast(_("Back to “{shown}” ({exe} closed)",
                     shown=shown, exe=html.escape(sw.exe)) if sw.back
                   else _("Switched to “{shown}” ({exe} is in front)",
                          shown=shown, exe=html.escape(sw.exe)))

    def pick_category_programs(self, name: str):
        """A category's menu → Show this when a program is in front…"""
        from soundboard.ui.programpick import ProgramPicker
        d = ProgramPicker(name, dict(self.cfg.category_programs), self)
        picked = d.picked if d.exec() else []
        free_dialog(d)
        for exe in picked:
            self.add_category_program(name, exe, quiet=True)
        if picked:
            self.toast(_("✓ “{name}” shows by itself when {picked} is in front",
                         name=html.escape(name), picked=html.escape(', '.join(picked))), "ok")

    def add_category_program(self, name: str, exe: str, quiet: bool = False):
        exe = catswitch.exe_name(exe)
        if not exe or name not in self.cfg.categories:
            return
        self.cfg.category_programs[exe] = name   # one category per program
        self._category_programs_changed()
        if not quiet:
            self.toast(_("✓ “{name}” shows by itself when {exe} is in front",
                         name=html.escape(name), exe=html.escape(exe)), "ok")

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
            self.toast(_("Opened your sounds folder"))
        else:
            self.toast(_("Couldn't open the sounds folder: {sounds_dir}",
                         sounds_dir=html.escape(str(library.SOUNDS_DIR))), "warn")

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
        # a sound on the Undo bar is off the board but its file is still here: not a
        # new one (it came back as a copy, without its hotkey, and its bin entry broke)
        undoable = {os.path.normcase(m.file) for m, *_rest in self._removed}
        for p in loose_sounds(self.cfg):
            if p in self._loose_taken or os.path.normcase(str(p)) in undoable:
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
        files, __ = QFileDialog.getOpenFileNames(
            self, _("Add sounds"), str(Path.home()),
            _("Sounds and zips ({exts} *.zip);;Audio ({exts});;Zip of sounds, backup or "
              "sound pack (*.zip);;All files (*)", exts=exts))
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
                        for __ in names[1:]:
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
                        raise RuntimeError(_("already in your library as “{name}”",
                                             name=known[fp]))
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
        self.status.setText(_("Importing {count} file(s)…", count=count))
        busy.set_busy(self.btn_add, True)   # back in on_imported, when they're all in
        self.toast(ngettext("Adding {count} sound…", "Adding {count} sounds…", count, count=count))

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
            usage.used("add-files")
            usage.step(self.cfg, "added-sound")
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
                self.toast(ngettext("✓ Added {n} sound", "✓ Added {n} sounds", n), "ok")
            elif not self._import_errors:
                self.toast(_("Nothing new to add"))
            self.triggers.import_done()   # a trigger's sound that failed to import
            if self._import_errors:
                # in <p>: escaped text with no tag in it (one error alone) was shown as
                # plain text, "&#x27;" and all
                errs, self._import_errors = self._import_errors[:15], []
                QMessageBox.warning(self, _("Some files weren't added"),
                                    "<p>" + "<br>".join(html.escape(e) for e in errs) + "</p>")

    def on_clip(self, data, name) -> SoundMeta | None:
        """A clip recorded in the Radio or Apps tab (or with the mic) becomes a normal
        sound pad."""
        try:
            meta, data = save_clip(data, name, PAD_COLORS[len(self.cfg.sounds) % len(PAD_COLORS)])
        except Exception as e:  # noqa: BLE001
            log.exception("can't save clip")
            src = self.sender()
            if src is not None and hasattr(src, "clip_error"):
                src.clip_error = errors.plain(e)   # the tab says so on its row
            else:
                errors.warn(self, _("Couldn't save clip"), e)
            return None
        self._tag_new(meta)
        self.cfg.sounds.append(meta)
        self._index()
        self.audio[meta.id] = data
        usage.used("clip")
        usage.step(self.cfg, "added-sound")
        threading.Thread(target=self.engine.prepare, args=(meta.id, data), daemon=True).start()
        self._save_now()
        self._rebuild_pads()
        self.status.setText(_("Added “{name}” ({duration:.1f}s) to Sounds — right-click it there "
                              "to rename or set a hotkey.",
                              name=html.escape(meta.name), duration=meta.duration))
        return meta

    def record_dialog(self):
        """Sounds tab → Record: record a sound with the mic, or a bit of what's playing.
        The window doesn't block the board: pads, web results, the radio and Space
        still work while it's open (to play what's being recorded)."""
        from soundboard.ui.recordmic import RecordDialog
        d = getattr(self, "_record_dlg", None)
        if d is not None:   # already open: bring it forward
            d.raise_()
            d.activateWindow()
            return
        voice = getattr(self, "voice", None)

        def voice_on() -> bool:
            on = getattr(voice, "is_active", None)
            return bool(on()) if on is not None else False

        def open_devices():
            self.tabs.setCurrentWidget(self.setup_page)

        d = RecordDialog(self.engine, voice_on, lambda: [m.name for m in self.cfg.sounds],
                         self.add_recording, open_devices, self,
                         playing_name=self._playing_name)
        self._record_dlg = d

        def closed(_r):
            self._record_dlg = None
            # after its own signal returns; tied to `d`, so nothing runs if the window
            # (and the dialog with it) is gone first
            QTimer.singleShot(0, d, lambda: free_dialog(d))
        d.finished.connect(closed)
        d.setModal(False)
        d.show()

    def _playing_name(self) -> str:
        """What's playing now, for naming a recording of it: the player's sound (a pad
        or a web result) or the radio station; "" for nothing."""
        sid = self.current
        st = self.engine.state(sid) if sid else None
        if st is not None and not st[1]:
            m = self.meta(sid)
            if m is not None:
                return m.name
        station = getattr(getattr(self.radio, "player", None), "station", None)
        return station.name if station is not None else ""

    def add_recording(self, data, name) -> bool:
        """A mic recording becomes a pad: selected, scrolled to, and a toast says so."""
        meta = self.on_clip(data, name)
        if meta is None:
            return False
        usage.used("record")
        self.select(meta.id)

        def reveal():   # once the grid has laid the new pad out
            pad = self.pads.get(meta.id)
            if pad is not None:
                self._pads_scroll.ensureWidgetVisible(pad)
        QTimer.singleShot(0, self._pads_scroll, reveal)   # not after the window's gone
        self.toast(_("✓ Added “{name}”", name=html.escape(meta.name)), "ok")
        return True

    def on_downloaded(self, meta, data):
        """"Add as sound" (link bar / web search) finished: already decoded, stored and
        prepared."""
        self._tag_new(meta)
        self.cfg.sounds.append(meta)
        self._index()
        self.audio[meta.id] = data
        usage.used("youtube")
        usage.step(self.cfg, "added-sound")
        self._save_now()
        self._rebuild_pads()
        self.status.setText(_("Added “{name}” ({duration:.1f}s) to Sounds — right-click it there "
                              "to rename or set a hotkey.",
                              name=html.escape(meta.name), duration=meta.duration))

    def on_reorder(self, sid, target):
        m = self.meta(sid)
        if not m:
            return
        if self.cfg.pad_sort != "custom":   # the drop index is into the sorted pads
            self.toast(_("The pads are sorted {how}: pick “My order” (the ⇣ button by the "
                         "search box) to drag them into place.",
                         how=self._sort_names()[self.cfg.pad_sort]))
            return
        self.cfg.sounds.remove(m)
        self.cfg.sounds.insert(min(target, len(self.cfg.sounds)), m)
        self._save_now()
        self._rebuild_pads()

    # ------------------------------------------------------------------ order and view
    @staticmethod
    def _sort_names() -> dict[str, str]:
        return {"custom": _("My order"), "name": _("A–Z"), "newest": _("Newest"),
                "plays": _("Most played")}

    def _label_view(self):
        """The order button by the search box: the order it shows, and the list icon in
        the list view."""
        b, c = self.btn_view, self.cfg
        b.setText(self._sort_names().get(c.pad_sort, ""))
        icons.set_icon(b, "list" if c.pad_view == "list" else "sort")
        b.setToolTip(_("Sort the pads (my order, A–Z, newest, most played) and show them as "
                       "cards or a list"))

    def _fill_view_menu(self, menu: QMenu):
        menu.clear()
        tips = {"custom": _("As you dragged them"), "name": _("By name"),
                "newest": _("The sounds added last first"),
                "plays": _("The sounds you play most first (counted from now on)")}
        group = QActionGroup(menu)
        for key, name in self._sort_names().items():
            a = menu.addAction(name, lambda k=key: self.set_pad_sort(k))
            a.setCheckable(True)
            a.setChecked(self.cfg.pad_sort == key)
            a.setToolTip(tips[key])
            group.addAction(a)
        menu.addSeparator()
        views = QActionGroup(menu)
        for key, name, icon, tip in (
                ("grid", _("Pads"), "sounds", _("Cards, with pictures")),
                ("list", _("List"), "list", _("One line each: many more sounds on the screen"))):
            a = menu.addAction(icons.icon(icon), name, lambda k=key: self.set_pad_view(k))
            a.setCheckable(True)
            a.setChecked(self.cfg.pad_view == key)
            a.setToolTip(tip)
            views.addAction(a)

    def set_pad_sort(self, how: str):
        if how not in library.PAD_SORTS or how == self.cfg.pad_sort:
            return
        self.cfg.pad_sort = how
        self._label_view()
        self._save_now()
        self._rebuild_pads()

    def set_pad_view(self, view: str):
        if view not in library.PAD_VIEWS or view == self.cfg.pad_view:
            return
        self.cfg.pad_view = view
        self._label_view()
        self._save_now()
        self.grid.set_listed(view == "list")
        self.selection.sync()

    def _volume_action(self, menu: QMenu, m: SoundMeta) -> QWidgetAction:
        """A pad menu's volume slider: changes it as it's dragged (a playing sound too)."""
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(10, 4, 10, 4)
        h.setSpacing(8)
        h.addWidget(icon_label("volume", _("This sound's volume (Ctrl+wheel on the pad "
                                            "changes it too)")))
        sl = QSlider(Qt.Horizontal)
        sl.setRange(0, 200)
        sl.setSingleStep(5)
        sl.setPageStep(10)
        sl.setValue(round(m.volume * 100))
        sl.setFixedWidth(120)
        sl.setAccessibleName(_("Volume"))
        val = QLabel(f"{sl.value()} %")
        val.setObjectName("muted")
        val.setMinimumWidth(QFontMetricsF(val.font()).horizontalAdvance("200 %") + 2)

        def moved(v: int):
            val.setText(f"{v} %")
            m.volume = v / 100
            self.engine.set_gain(m.id, self.gain_for(m))
        sl.valueChanged.connect(moved)
        h.addWidget(sl)
        h.addWidget(val)
        a = QWidgetAction(menu)
        a.setText(_("Volume"))   # what a screen reader says for the row
        a.setDefaultWidget(w)
        return a

    def nudge_volume(self, sid: str, steps: int):
        """Ctrl+wheel on a pad: its volume in 5 % steps (0-200 %, as in Edit)."""
        m = self.meta(sid)
        if m is None:
            return
        m.volume = round(min(2.0, max(0.0, m.volume + 0.05 * steps)), 2)
        self.engine.set_gain(sid, self.gain_for(m))
        QToolTip.showText(QCursor.pos(), _("{name}: {pct} %", name=m.name,
                                           pct=round(m.volume * 100)), self.pads.get(sid))
        if not self._count_save.isActive():
            self._count_save.start()

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
        a_stop = add(("stop",), _("Stop")) if self.engine.state(sid) else None
        a_next = add(("play",), _("Play next"), _("Plays it after the sounds playing now"))
        menu.addSeparator()
        a_edit = add(("edit",), _("Edit…"), _("Name, volume, hotkey, what a press does, loop, "
                                              "fades, wait first, cooldown, colour"))
        a_ren = add(None, _("Rename…"), _("Just the name (F2 on the pad does it too)"))
        a_fx = add(("wave",), _("Effects…"), _("Speed, pitch, EQ, boost"))
        vol_before = m.volume
        menu.addAction(self._volume_action(menu, m))
        a_hk_clear = None
        if m.hotkey:
            hk = menu.addMenu(icons.icon("keyboard"), _("Hotkey: {hotkey}",
                                                        hotkey=pretty_key(m.hotkey)))
            hk.setToolTipsVisible(True)
            a_hk = add(None, _("Change…"), _("Press a new key or combo for it"), hk)
            a_hk_clear = add(None, _("Remove hotkey"), "", hk)
        else:
            a_hk = add(("keyboard",), _("Set hotkey…"), _("A key or combo that plays it, even "
                                                          "in-game"))
        cats = menu.addMenu(_("Categories"))
        cat_acts = {}
        for c in self.cfg.categories:
            a = cats.addAction(c.replace("&", "&&"))
            a.setCheckable(True)
            a.setChecked(c in m.tags)
            cat_acts[a] = c
        if cat_acts:
            cats.addSeparator()
        a_newcat = cats.addAction(icons.icon("plus"), _("New category…"))
        a_nopic = None
        if m.image:
            pic = menu.addMenu(icons.icon("image"), _("Picture"))
            a_pic = pic.addAction(_("Change…"))
            a_nopic = pic.addAction(_("Remove picture"))
        else:
            a_pic = add(("image",), _("Add picture…"), _("Shown on the pad (you can also drop "
                                                         "a picture on it, or copy one, click "
                                                         "the pad and press Ctrl+V)"))
        menu.addSeparator()
        a_dup = add(("plus",), _("Duplicate"), _("A second pad with the same sound, to give "
                                                 "its own effects or hotkey"))
        a_export = add(("folder",), _("Export…"), _("Save it as a file to share with friends"))
        a_show = add(None, _("Show the file in its folder"))
        a_del = add(("trash", "danger_text"), _("Remove"), _("Goes to Recently deleted"))
        act = menu.exec(pos)
        menu.deleteLater()   # its actions stay valid until this returns
        if m.volume != vol_before:
            self._save_now()
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
        elif act == a_ren:
            self.rename_sound(sid)
        elif act == a_dup:
            self.duplicate_sound(sid)
        elif act == a_show:
            self.show_sound_file(sid)
        elif act == a_fx:
            self.edit(sid, tab="effects")
        elif act == a_hk:
            self.set_sound_hotkey(sid)
        elif act is not None and act == a_hk_clear:
            self.set_sound_hotkey(sid, "")
        elif act == a_pic:
            f, __ = QFileDialog.getOpenFileName(
                self, _("Pick a picture"), str(Path.home()),
                _("Pictures ({patterns})",
                  patterns=" ".join(f"*{x}" for x in sorted(thumbs.IMAGE_EXTS))))
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
            QMessageBox.warning(self, _("Couldn't use that picture"),
                                _("{name} isn't a picture this app can read.",
                                  name=Path(path).name))
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
            self.on_clip(clip.copy(), _("Clip {time}", time=time.strftime('%H.%M.%S')))
            return
        sids = [m.id for m in self.selection.sounds()] or (
            [self.current] if self.current in self.pads else [])
        if not sids:
            return
        img = thumbs.from_clipboard(QApplication.clipboard().mimeData())
        if img is None:
            self.status.setText(_("Nothing to paste: copy a picture first (in a browser: "
                                  "right-click it → Copy image), then press Ctrl+V on a pad."))
            return
        done = [sid for sid in sids if (m := self.meta(sid)) and thumbs.set_image(m, img)]
        if not done:
            return
        self._save_now()
        for sid in done:
            self.pads[sid].update()
        m = self.meta(done[0])
        self.status.setText(_("Picture pasted on “{name}”.",
                              name=html.escape(m.name)) if len(done) == 1
                            else ngettext("Picture pasted on {n} pad.",
                                          "Picture pasted on {n} pads.", len(done)))

    def ask_remove(self, sids: list[str]) -> bool:
        """Remove from the menu / picked pads: ask first. They go to Recently deleted."""
        gone = [m for m in (self.meta(s) for s in sids) if m]
        if not gone:
            return False
        if len(gone) == 1:
            ask = _("Remove “{name}”?\n\nRemoved sounds go to Recently deleted, where you "
                    "can bring them back for {keep_days} days.",
                    name=gone[0].name, keep_days=trash.KEEP_DAYS)
        else:
            ask = ngettext("Remove this {n} sound?\n\nRemoved sounds go to Recently deleted, "
                           "where you can bring them back for {keep_days} days.",
                           "Remove these {n} sounds?\n\nRemoved sounds go to Recently "
                           "deleted, where you can bring them back for {keep_days} days.",
                           len(gone), keep_days=trash.KEEP_DAYS)
        box = QMessageBox(QMessageBox.Question, _("Remove sound") if len(gone) == 1
                          else _("Remove sounds"), ask,
                          QMessageBox.Yes | QMessageBox.Cancel, self)
        box.button(QMessageBox.Yes).setText(_("Remove"))
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
                self._set_np_name(_("Pick a sound"))
                self.np_name.setToolTip(_("Select a sound pad to use these playback controls."))
        self._save_now()
        self._rebuild_pads()
        self._fill_categories()
        self.register_hotkeys()
        if len(gone) == 1:
            name = self.undo_lbl.fontMetrics().elidedText(gone[0].name, Qt.ElideRight, 260)
            self.undo_lbl.setText(_("Removed “{name}”", name=name))
        else:
            self.undo_lbl.setText(_("Removed {n} sounds", n=len(gone)))
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
                or any(getattr(self.cfg, attr) == combo for attr, *__ in HOTKEY_ACTIONS)
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
        self.btn_bin.setText(_("Recently deleted ({n})", n=n))
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
        lost += [_("a random sound from “{name}”", name=c)
                 for c, k in self.cfg.category_hotkeys.items() if k == m.hotkey]
        self._clear_category_hotkey(m.hotkey)
        if self.cfg.ptt_key == m.hotkey:   # as everywhere else a key is set
            self.cfg.ptt_key = ""
            lost.append(_("auto push-to-talk"))
        if lost:
            self.status.setText(
                _("<span style='color:{status}'>{hotkey} plays “{name}” now — it was the key for "
                  "{lost}.</span>",
                  status=theme.status('warn'), hotkey=html.escape(pretty_key(m.hotkey)),
                  name=html.escape(m.name), lost=html.escape(_(" and ").join(lost))))
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
            self.toast(_("✓ {combo} plays “{name}”",
                         combo=html.escape(combo), name=html.escape(m.name)) if combo
                       else _("Hotkey removed from “{name}”", name=html.escape(m.name)))
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
            for attr, *__ in HOTKEY_ACTIONS:
                if getattr(self.cfg, attr) == combo:
                    setattr(self.cfg, attr, "")
                    taken_from.append(_("another action"))
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
            if taken_from:
                msg = _("✓ {combo} plays a random “{name}” sound — it was the key for {lost}",
                        combo=html.escape(combo), name=html.escape(name),
                        lost=html.escape(", ".join(taken_from)))
            else:
                msg = _("✓ {combo} plays a random “{name}” sound",
                        combo=html.escape(combo), name=html.escape(name))
            self.toast(msg, "ok")
        else:
            self.cfg.category_hotkeys.pop(name, None)
            self.toast(_("Random-sound hotkey for “{name}” cleared", name=html.escape(name)))
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

    def duplicate_sound(self, sid: str) -> SoundMeta | None:
        """The pad menu's Duplicate: a copy right after the original, with its own
        file, so each can get its own effects, hotkey or category."""
        m = self.meta(sid)
        if m is None:
            return None
        try:
            new = duplicate(m, _("{name} (copy)", name=m.name)[:40])
        except OSError as e:
            errors.warn(self, _("Couldn't copy the sound"), e)
            return None
        videos.copy_link(m.id, new.id)
        self._tag_new(new)   # stays in sight in the category showing
        self.cfg.sounds.insert(self.cfg.sounds.index(m) + 1, new)
        self._index()
        self._save_now()
        self._rebuild_pads()
        self._rerender(new)
        self.toast(_("✓ Added “{name}”", name=html.escape(new.name)), "ok")
        return new

    def show_sound_file(self, sid: str):
        """The pad menu's Show the file in its folder: Explorer with the file picked
        (elsewhere, the folder it's in)."""
        m = self.meta(sid)
        if m is None:
            return
        path = Path(m.file)
        if not path.is_file():
            self.toast(_("The file for “{name}” isn't there any more", name=html.escape(m.name)),
                       "warn")
            return
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def _save_copy(self, m: SoundMeta, d: EditDialog):
        """'Save as new sound': the edits go onto a copy placed after the original."""
        name = d.name.text().strip() or m.name
        try:
            new = duplicate(m, name if name != m.name else f"{name} (edit)")
        except OSError as e:
            errors.warn(self, _("Couldn't copy the sound"), e)
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
        f, __ = QFileDialog.getSaveFileName(self, title, str(start), _("Zip file (*.zip)"))
        if f and not f.lower().endswith(".zip"):
            f += ".zip"
        return f

    def export_board(self):
        """Everything: every sound (with its picture, effects, hotkey, categories) and
        the app's settings, to move to another PC or keep as a backup."""
        if not self.cfg.sounds and not QMessageBox.question(
                self, _("Export"), _("There are no sounds yet. Export just your settings?")) \
                == QMessageBox.Yes:
            return
        f = self._save_name(_("Export everything"),
                            f"Onion Board backup {time.strftime('%Y-%m-%d')}.zip")
        if f:
            self._export(f, list(self.cfg.sounds), with_settings=True)

    def export_category(self):
        if self.cfg.category:
            self.export_sounds(self.category_sounds(), self.cfg.category)

    def export_sounds(self, sounds: list[SoundMeta], name: str):
        """A sound pack: just these sounds (no settings), e.g. to share with friends."""
        if not sounds:
            QMessageBox.information(self, _("Export"), _("There are no sounds in it to export."))
            return
        f = self._save_name(_("Export sounds"), backup._safe(name) + ".zip")
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
            self.toast(_("Still exporting the last one — try again when it's done"), "warn")
            return
        self._exporting = True
        self.status.setText(_("Exporting…"))
        self.toast(ngettext("Exporting {n} sound…", "Exporting {n} sounds…", len(sounds)))

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
            QMessageBox.warning(self, _("Export failed"),
                                _("Couldn't write {name}:\n{err}",
                                  name=Path(path).name, err=errors.plain(err)))
            return
        msg = (ngettext("Exported {n} sound to {name}.",
                        "Exported {n} sounds to {name}.",
                        n, name=html.escape(Path(path).name)))
        self.status.setText(msg)
        self.toast("✓ " + msg, "ok")

    def import_dialog(self):
        files, __ = QFileDialog.getOpenFileNames(
            self, _("Import a backup, sound pack or zip of sounds"), str(Path.home()),
            _("Zip file (*.zip)"))
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
        usage.used("import-board")
        title = _("Import from {name}", name=src.name)
        if not path:
            try:
                path = str(src.find() or "")
            except OSError:
                path = ""
        if not path and not ask:
            return   # its board went away since the install
        if not path:
            path, __ = QFileDialog.getOpenFileName(
                self, _("{title}: pick a saved board", title=title), str(Path.home()),
                _("{name} board ({patterns})", name=src.name,
                  patterns=" ".join("*" + x for x in src.suffixes)))
            if not path:
                return
        try:
            entries = src.read(Path(path))
        except (OSError, ValueError) as e:
            if not ask:
                log.warning("can't read %s's board: %s", src.name, e)
                self.toast(_("Couldn't bring your {name} sounds over: {e}",
                             name=src.name, e=errors.plain(e)),
                           "warn")
            else:
                errors.warn(self, _("Couldn't read the {name} board", name=src.name), e)
            return
        ok, bad = otherboards.importable(entries)
        if not ok:
            msg = (_("No sounds to bring over: the sound files {name} points at have been moved "
                     "or deleted.", name=src.name) if entries else
                   _("There are no sounds on your {name} board.", name=src.name))
            if ask:
                QMessageBox.information(self, title, msg)
            else:
                self.toast(msg, "warn")
            return
        if ask:
            keys = sum(1 for e in ok if e.hotkey)
            cats = {t for e in ok for t in e.tags}
            n_cats = ngettext("{n} category", "{n} categories", len(cats))
            n_keys = ngettext("{n} hotkey", "{n} hotkeys", keys)
            if cats and keys:
                found = ngettext("Found <b>{n}</b> sound in {name} with {categories} and "
                                 "{hotkeys}.", "Found <b>{n}</b> sounds in {name} with "
                                 "{categories} and {hotkeys}.", len(ok), name=src.name,
                                 categories=n_cats, hotkeys=n_keys)
            elif cats or keys:
                found = ngettext("Found <b>{n}</b> sound in {name} with {what}.",
                                 "Found <b>{n}</b> sounds in {name} with {what}.", len(ok),
                                 name=src.name, what=n_cats if cats else n_keys)
            else:
                found = ngettext("Found <b>{n}</b> sound in {name}.",
                                 "Found <b>{n}</b> sounds in {name}.", len(ok), name=src.name)
            lines = [found,
                     _("They're copied into Onion Board; {name} keeps its own. Ones "
                       "already here are skipped, and a hotkey something here already "
                       "uses is left off.", name=src.name)]
            if bad:
                lines.append(ngettext(
                    "{n} more can't be brought over (the file was moved or deleted, or isn't "
                    "a sound): {names}", "{n} more can't be brought over (the file was moved "
                    "or deleted, or isn't a sound): {names}", len(bad),
                    names=html.escape(", ".join(e.name for e in bad[:5]))
                    + ("…" if len(bad) > 5 else "")))
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
            errors.warn(self, _("Can't import"), e)
            return
        except Exception as e:  # noqa: BLE001 - a damaged or odd file, never a crash
            QApplication.restoreOverrideCursor()
            log.warning("couldn't read %s", path, exc_info=True)
            QMessageBox.warning(self, _("Can't import"),
                                _("{name} is damaged or in a format Onion Board can't read ({e}).",
                                  name=Path(path).name, e=errors.plain(e)))
            return
        QApplication.restoreOverrideCursor()
        use_settings = False
        if pkg.settings:
            box = QMessageBox(QMessageBox.Question, _("Import backup"),
                              ngettext("{name} has {n} sound and the settings they were saved "
                                       "with (theme, hotkeys, overlay, voice effects…).\n\nUse "
                                       "its settings too? Your devices stay as they are.",
                                       "{name} has {n} sounds and the settings they were saved "
                                       "with (theme, hotkeys, overlay, voice effects…).\n\nUse "
                                       "its settings too? Your devices stay as they are.",
                                       len(pkg.sounds), name=Path(path).name),
                              QMessageBox.NoButton, self)
            yes = box.addButton(_("Sounds and settings"), QMessageBox.YesRole)
            box.addButton(_("Just the sounds"), QMessageBox.NoRole)
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
        self.status.setText(_("Importing {n} sound(s)…", n=len(pkg.sounds)))
        self.toast(ngettext("Importing {n} sound…", "Importing {n} sounds…", len(pkg.sounds)))

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
            QMessageBox.information(self, _("Settings imported"),
                                    _("Done. Hotkeys and the theme apply now; everything else "
                                      "the next time Onion Board starts."))

    def _on_unpacked(self, res, pkg, err: str):
        self._update_status()
        if res is None:
            QMessageBox.warning(self, _("Import failed"), err)
            return
        taken = {o.hotkey for o in self.cfg.sounds if o.hotkey}
        taken |= {getattr(self.cfg, a) for a, *__ in HOTKEY_ACTIONS if getattr(self.cfg, a)}
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
        msg = (ngettext("Imported {n} sound ({skipped} already in your library)",
                        "Imported {n} sounds ({skipped} already in your library)", n,
                        skipped=len(res.skipped)) if res.skipped else
               ngettext("Imported {n} sound", "Imported {n} sounds", n))
        self.status.setText(msg + ".")
        self.toast(f"✓ {msg}", "ok" if n else "")
        if res.failed:
            QMessageBox.warning(self, _("Some sounds weren't imported"),
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
        menu.addAction(_("Open Onion Board"), self.show_from_tray)
        icons.set_icon(menu.addAction(_("Stop all sounds"), self.stop_all), "stop")
        menu.addSeparator()
        # both only open a page in the browser (feedback.py)
        from soundboard import __version__, feedback
        icons.set_icon(menu.addAction(_("Join the Discord"), lambda: self._open_page(
            feedback.DISCORD_URL)), "speech")
        icons.set_icon(menu.addAction(_("Send feedback"), lambda: self._open_page(
            feedback.feedback_url(__version__))), "edit")
        menu.addSeparator()
        menu.addAction(_("Quit"), self.quit_app)
        t.setContextMenu(menu)
        t.activated.connect(self._on_tray)
        t.messageClicked.connect(self.show_from_tray)
        t.show()
        QApplication.instance().setQuitOnLastWindowClosed(False)

    def _open_page(self, url: str):
        busy.open_url(url, window=self, failed=_("Couldn't open your browser. The page is"))

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
            self.toast(_("Close Onion Board and open it again to finish."), "warn")
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
            self.status.setText(_("<span style='color:{status}'>Remote control is off: "
                                  "{err}.</span>",
                                  status=theme.status('warn'), err=html.escape(err)))
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
                else _("failed to start: {error}", error=errors.plain(e))
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

    def _voice_fx_changed(self, spec: dict):
        if spec.get("enabled"):
            usage.used("voice-changer")
        self.set_option("voice_fx", spec)

    def _remember_usage(self):   # features used this run, for the next daily count
        usage.remember(self.cfg)

    def _mark_stopped(self):
        usage.mark_stopped(library.APP_DIR)
        exitwatch.stopped()

    def _count_tab(self, i: int):
        if 0 <= i < len(TABS):
            usage.tab_opened(self.cfg, TAB_KEYS[i])

    def _on_update(self, rel, err: str, asked: bool):
        self._save_later()   # update_checked
        busy = self._downloading or self._update_file is not None
        if rel is not None and not busy:
            self.release = rel
            self._set_update_pill(_("Update: {version}", version=rel.version),
                                  _("Onion Board {version} is out — click for details",
                                    version=rel.version))
            if self.tray is not None and not self.isVisible():
                self.tray.showMessage(
                    "Onion Board", _("Important fix: {fix}", fix=rel.urgent) if rel.urgent
                    else _("Version {version} is out.", version=rel.version),
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
            button = (_("Restart to update") if self._update_file is not None
                      else _("Update now") if updates.can_install() and rel.asset_url
                      else _("Details"))
            return (f"board {rel.version}",
                    _("Important fix in Onion Board {version}: {fix}",
                      version=rel.version, fix=rel.urgent), button)
        o = self.watch_offer
        if o is not None and f"watch {o.version}" not in self._urgent_hidden:
            return (f"watch {o.version}",
                    _("Important fix in Onion Watch {version}: {fix}",
                      version=o.version, fix=o.urgent),
                    _("Update Onion Watch"))
        probs = self.discord_problems()
        key = "discord " + ",".join(probs)
        if probs and key not in self._urgent_hidden:
            return key, DISCORD_URGENT[probs[0]].format(
                name=self.discord_found[0].client), _("Fix Discord")
        raw = self._raw_culprits()
        key = "rawmic " + ",".join(a.exe.lower() for a in raw)
        if raw and key not in self._urgent_hidden:
            if len(raw) == 1:
                text = _("{name} is using your mic without Onion Board, so it won't hear "
                         "your sounds. Look for a \"raw\", \"bypass processing\" or "
                         "\"studio\" option in its voice settings and turn it off.",
                         name=raw[0].name)
            else:
                text = _("One of these apps is using your mic without Onion Board, so it "
                         "won't hear your sounds: {names}. Look for a \"raw\", \"bypass "
                         "processing\" or \"studio\" option in its voice settings and turn "
                         "it off.", names=", ".join(a.name for a in raw))
            return key, text, ""
        return None

    def _raw_culprits(self) -> list:
        """The apps recording the mic in raw mode (rawmic), but not a Discord whose own
        settings already have their line (Studio, Bypass)."""
        raw = self.raw_watch.culprits
        if raw and self.discord_problems():
            from soundboard.ui.chatguide import DISCORD_EXES
            raw = [a for a in raw if a.exe.lower() not in DISCORD_EXES]
        return raw

    def _raw_tick(self):
        """Every RAW_POLL_MS while sending straight into the mic: who records it, on a
        worker (Windows' session list); compared with the effect's streams after."""
        e = self.engine
        mic = self.cfg.mic_device
        if (self.cfg.route != "mic" or e.direct_stream() is None or not mic
                or self._direct_not_running()):
            shown = bool(self.raw_watch.culprits)
            self.raw_watch.reset()
            if shown:
                self._show_urgent()
            return
        if self._raw_looking:
            return
        self._raw_looking = True

        def run():
            apps = None
            try:
                # in the endpoint effect nobody can skip it, and one copy serves every
                # app (its stream count isn't per app): nobody to name
                apps = [] if directmic.endpoint_wide() else \
                    appaudio.recording_apps(mic, mine=True)
            except Exception:  # noqa: BLE001 - a check that can't run shows nothing
                log.debug("listing who records the mic failed", exc_info=True)
            self.bridge.mic_users.emit(apps)
        threading.Thread(target=run, daemon=True, name="raw-mic").start()

    def _on_mic_users(self, apps, now: float | None = None):
        self._raw_looking = False
        if apps is None or self.engine.direct_stream() is None:
            return
        before = [a.exe for a in self.raw_watch.culprits]
        now = self.raw_watch.update(apps, self.engine.direct_apps(),
                                   time.monotonic() if now is None else now)
        if [a.exe for a in now] != before:
            log.info("recording the mic without Onion Board: %s",
                     [a.exe for a in now] or "nobody")
            self._show_urgent()

    def discord_problems(self) -> list[str]:
        """What in the running Discord's own settings hurts your sounds (discordcfg),
        worst first; [] when it's fine, not running, or couldn't be read."""
        if not self.discord_found:
            return []
        from soundboard.ui.chatguide import raw_skips
        return self.discord_found[0].problems(raw_skips(self))

    def _discord_tick(self):
        """Every DISCORD_POLL_MS: while Discord runs, re-read its settings when its
        files changed. On a worker: the process list and the files take a few ms."""
        if self._discord_reading:
            return
        self._discord_reading = True
        last = self._discord_sig

        def run():
            found, sig = [], None
            try:
                from soundboard.ui.chatguide import DISCORD_EXES
                names = {n for _p, n in appaudio._process_table().values()}
                if names & set(DISCORD_EXES):
                    sig = discordcfg.signature()
                    found = None if sig == last else discordcfg.read()
            except Exception:  # noqa: BLE001 - a check that can't run shows nothing
                log.debug("reading Discord's settings failed", exc_info=True)
            self.bridge.discord.emit((found, sig))
        threading.Thread(target=run, daemon=True, name="discord-settings").start()

    def _on_discord(self, res):
        found, sig = res
        self._discord_reading = False
        self._discord_sig = sig
        if found is None:   # unchanged
            return
        before = self.discord_problems()
        self.discord_found = found
        now = self.discord_problems()
        if now != before:
            log.info("Discord settings: %s", now or "fine")
            self._show_urgent()
        app = self._setup_app
        if self._setup_state == "done" and app is not None and app.guide == "discord":
            self._show_setup("done", app)   # its ticks, live

    def _show_urgent(self):
        now = self._urgent_now()
        if now is None:
            self.urgent_bar.hide()
            return
        _key, text, button = now
        self.urgent_lbl.setText(text)
        self.urgent_btn.setText(button)
        self.urgent_btn.setVisible(bool(button))   # a warning with nothing to click
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
        if now[0].startswith("discord"):
            self.show_chat_guide("discord")
            self._show_urgent()   # fixed meanwhile, or still to do
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
                          _("Important fix available") if rel.urgent else _("Update available"),
                          _("Onion Board {version} is out (you have {current}).",
                            version=rel.version, current=__version__),
                          QMessageBox.NoButton, self)
        info = (_("<p><b>Important fix:</b> {fix}</p>", fix=html.escape(rel.urgent))
                if rel.urgent else "")
        info += html.escape(rel.notes).replace("\n", "<br>") if rel.notes else ""
        installable = updates.can_install() and bool(rel.asset_url)
        if installable:
            info += _("<p>Update now downloads it in the background (about 180 MB); you "
                      "choose when the app restarts to install it. Your sounds and "
                      "settings stay as they are.</p>")
        elif not updates.can_install():
            info += _("<p>This copy runs from source: update it with <code>git pull</code>.</p>")
        if info:
            box.setInformativeText(f"<p>{info}</p>")
        get = box.addButton(_("Update now") if installable else _("Open the download page"),
                            QMessageBox.AcceptRole)
        page = box.addButton(_("Release page"), QMessageBox.HelpRole) if installable else None
        # an urgent fix can't be skipped for good, only put off
        skip = (None if rel.urgent
                else box.addButton(_("Skip this version"), QMessageBox.DestructiveRole))
        box.addButton(_("Later"), QMessageBox.RejectRole)
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
        self._set_update_pill(_("Downloading update…"),
                              _("Downloading Onion Board {version}", version=rel.version),
                              enabled=False)
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
            self.btn_update.setText(_("Downloading update… {pct}%", pct=pct))

    def _on_update_ready(self, path, err: str):
        self._downloading = False
        rel = self.release
        if rel is None:
            return
        self._show_urgent()   # back, as "Update now" or "Restart to update"
        if path is None:
            self._set_update_pill(_("Update: {version}", version=rel.version),
                                  _("Onion Board {version} is out — click for details",
                                    version=rel.version))
            box = QMessageBox(QMessageBox.Warning, _("Couldn't update"),
                              _("Onion Board {version} couldn't be downloaded: {rstrip}.",
                                version=rel.version, rstrip=errors.plain(err).rstrip('.')),
                              QMessageBox.NoButton, self)
            page = box.addButton(_("Open the download page"), QMessageBox.AcceptRole)
            box.addButton(_("Close"), QMessageBox.RejectRole)
            box.exec()
            clicked = box.clickedButton()
            free_dialog(box)
            if clicked is page:
                QDesktopServices.openUrl(QUrl(rel.url))
            return
        self._update_file = path
        self._show_urgent()
        self._set_update_pill(_("Restart to update"),
                              _("Onion Board {version} is downloaded — click to install it",
                                version=rel.version))
        if self.tray is not None and not self.isVisible():
            # hidden in the tray, maybe mid-game: don't pop a question, just say so
            self.tray.showMessage("Onion Board", _("Version {version} is ready to install: "
                                                   "open Onion Board and click Restart to "
                                                   "update.", version=rel.version),
                                  QSystemTrayIcon.Information, 8000)
            return
        self.install_update()

    def install_update(self):
        """Ask, then close the app and let the downloaded installer replace it (it
        opens the app again when it's done)."""
        rel, path = self.release, self._update_file
        if rel is None or path is None:
            return
        box = QMessageBox(QMessageBox.Question, _("Install the update"),
                          _("Onion Board {version} is ready. Restart now to install it?",
                            version=rel.version),
                          QMessageBox.NoButton, self)
        box.setInformativeText(_("Onion Board closes, installs the new version and opens again "
                                 "by itself, usually within a minute. Sounds that are playing "
                                 "stop."))
        now = box.addButton(_("Restart now"), QMessageBox.AcceptRole)
        box.addButton(_("Later"), QMessageBox.RejectRole)
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
            QMessageBox.warning(self, _("Couldn't update"),
                                _("The installer couldn't be started ({e}). You can download it "
                                  "from the release page instead.", e=errors.plain(e)))
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
        box = QMessageBox(QMessageBox.Information, _("Updated"),
                          _("Onion Board is up to date: version {version}.", version=__version__),
                          QMessageBox.NoButton, self)
        new = box.addButton(_("What's new"), QMessageBox.HelpRole)
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
        box = QMessageBox(QMessageBox.Warning, _("The update didn't finish"),
                          _("Onion Board {pending} wasn't installed; this is still {version}. "
                            "You can download it from its page and run it yourself.",
                            pending=pending, version=__version__), QMessageBox.NoButton, self)
        page = box.addButton(_("Open the download page"), QMessageBox.AcceptRole)
        logb = (box.addButton(_("Show the install log"), QMessageBox.HelpRole)
                if updates.INSTALL_LOG.is_file() else None)
        box.addButton(_("Close"), QMessageBox.RejectRole)
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
        text = _("Stop hearing it") if on else _("Hear what they hear")
        self.btn_check.setProperty("full_text", text)   # what a compact window restores
        if self.btn_check.text():   # blank while the window is too narrow for words
            self.btn_check.setText(text)
        self.mic_banner.setVisible(on)
        # impossible to miss; turned on from the tray or behind a game it pulses once
        # the window is shown in front (_set_tick_rate)
        self._pulse.set_live(self._ui_live and appstate.active())
        self._pulse.set_on(on)
        self.mic_lbl.setStyleSheet(f"color:{theme.status('error')};" if on else "")
        self.mic_meter.hot = on
        if on and not self.cfg.mic_enabled:
            self.status.setText(_("<span style='color:{status}'>Sounds only: your mic isn't "
                                  "sent, so nobody (including you) hears it.</span>",
                                  status=theme.status('warn')))

    def start_test(self):
        if self.engine.main_stream is None:
            route = self.cfg.route
            QMessageBox.information(
                self, _("Test"),
                _("Sending to others is off, so there's nothing to record. Change it under Setup "
                  "→ Devices → Send my sounds to.") if route == "off" else
                _("Pick the device to send to first (Setup tab → Devices → Send my sounds to).")
                if route == "device" else
                _("Put your sounds in your mic first (Setup tab → Put my sounds straight into my "
                  "mic), or use the virtual cable.") if route == "mic" else
                _("Set up the virtual cable first (Setup tab → Step-by-step guide), or pick "
                  "another device under Send my sounds to."))
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
                _("<span style='color:{status}'>Test analysis failed: {ex}</span>",
                  status=theme.status('error'), ex=errors.plain(ex)))
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
                self, _("Settings were restored"), note))
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

    def _set_tick_rate(self, *__):
        live = self.isVisible() and not self.isMinimized()
        was, self._ui_live = self._ui_live, live
        # the mic-check banner pulses only while it can be seen, in front
        self._pulse.set_live(live and appstate.active())
        pace = self._tick_pace()
        if live == was and self.timer.interval() == pace:
            return
        self.timer.start(pace)
        if not live:   # a level frozen mid-flight would show as stuck on the next show
            self.out_meter.set_level(0.0)
            self.mic_meter.set_level(0.0)
            if not self.isVisible():   # to the tray: the pads' pictures are made again
                thumbs.trim()          # from their small files when it's back

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
        live = any((sid in self._meta or sid == LINK_ID) and not paused   # a web search's
                   for sid, (_p, paused) in playing.items())                # Play too
        if live != self._sounds_live:   # the Sounds tab glows while a sound plays
            self._sounds_live = live
            set_tab_live(self.tabs, self.tabs.indexOf(self.sounds_page), live,
                         _("● ON: a sound is playing"), "sounds")
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
            self.btn_rec.setText(_("Recording… talk / play sounds  ({max:.0f}s)", max=max(left, 0)))
            if left < -4:   # the output stopped (device unplugged): give up
                e.cancel_test_record()
                self._stop_capture()
                self.btn_rec.setEnabled(True)
                self.btn_rec.setText(_("Record 6s → play back"))
                self.test_result.setText(_("<span style='color:{status}'>The test stopped: the "
                                           "send device's output went away. Check Devices and "
                                           "try again.</span>", status=theme.status('error')))
                self.test_result.show()
        elif e.rec_done is not None:
            data, rate = e.rec_done
            e.rec_done = None
            data, rate = self._finish_test(data, rate)
            e.play("__test__", data, 1.0, preview=True, src_rate=rate)
            self._rec_playing = True
            self.btn_rec.setText(_("Playing back what they heard…"))
        elif self._rec_playing and "__test__" not in playing:
            self._rec_playing = False
            self.btn_rec.setEnabled(True)
            self.btn_rec.setText(_("Record 6s → play back"))

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
        # only the pads playing now and the ones still showing a sound (cleared on the
        # tick after it stops): going over all of them, 30 times a second, cost more
        # than the rest of the tick on a big board with nothing playing
        pads, lit = self.pads, set()
        for sid in self._pads_lit.union(playing):
            p = pads.get(sid)
            if p is None:   # not a pad (a preview, the test recording) or gone
                continue
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
            if p.progress is not None or p.bands is not None:
                lit.add(sid)
        self._pads_lit = lit
        self._update_transport(playing)
        if not self.ytresults.isHidden():   # the result in the player says so
            prog, paused = playing.get(LINK_ID, (None, False))
            self.ytresults.show_now(self._link_url, "" if prog is None else
                                    "paused" if paused else "playing")
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
        """The current sound's video, looked up once per selection, on a thread (it
        reads videos.json and checks the video is there, maybe on a sleeping drive):
        None until it's known."""
        if self._video_for[0] != sid:
            self._video_for = (sid, None)
            if sid:
                self._ask_video(sid)
        return self._video_for[1]

    def _ask_video(self, sid: str):
        if self._video_asking is not None:   # one at a time: its answer asks for the next
            return
        self._video_asking = sid

        def look():
            try:
                found = videos.get(sid)
            except Exception:  # noqa: BLE001 - never leave _video_asking stuck
                log.debug("video lookup failed", exc_info=True)
                found = None
            try:
                self.video_found.emit(sid, found)
            except RuntimeError:   # the window closed meanwhile
                pass
        threading.Thread(target=look, daemon=True, name="video-lookup").start()

    def _video_found(self, sid: str, path):
        self._video_asking = None
        now = self._video_for[0]
        if now != sid:             # another sound was picked meanwhile
            if now:
                self._ask_video(now)
            return
        self._video_for = (sid, path)
        if self.btn_video.isHidden() == (path is not None):
            self.btn_video.setVisible(path is not None)

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
            self.toast(_("This sound's video isn't there any more"), "warn")
            return
        if self._video_win is None:
            try:   # imported here: a build missing QtMultimediaWidgets must still start
                from soundboard.ui.videowindow import VideoWindow
            except ImportError:
                log.exception("can't show videos")
                self.btn_video.hide()
                self.toast(_("Videos can't be shown in this copy of Onion Board"), "warn")
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
        f.add(18, "w", r.icon_only(self.btn_view))   # its tooltip says what it is
        # the label and the dropdown go together: a lone "Clean" said nothing (the full
        # picker is on the Setup tab)
        f.add(38, "w", r.hide(*self._mode_pick))
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
        # a bare red dot read as a warning light, so Record keeps its word until the
        # folder, Backup and the Listening dropdown have gone
        f.add(39, "w", r.icon_only(self.btn_record))
        # the search box keeps room to type in until the buttons beside it have shrunk
        f.add(62, "w", lambda tight: (self.search.setMinimumWidth(0 if tight else SEARCH_MIN_W),
                                      r.touch(self.search)))
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
        for i, (text, _tip) in enumerate(TABS):
            self.tabs.setTabText(i, "" if compact else text)
            self.tabs.tabBar().setAccessibleTabName(i, text)   # icon-only tabs aren't silent
            base = text if compact else ""   # only an icon-only tab needs its name on hover
            old = self.tabs.property(f"_tip{i}")   # set_tab_live's copy of the plain tip
            if old is not None:
                cur = self.tabs.tabToolTip(i)
                self.tabs.setProperty(f"_tip{i}", base)
                live = None   # keep its "● ON" line
                if is_tab_live(self.tabs, i):
                    live = cur if not old else cur[:-len(old) - 1] if cur.endswith(
                        "\n" + old) else None
                if live:
                    base = f"{live}\n{base}" if base else live
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
                self.tray.showMessage(_("Onion Board is still running"),
                                      _("Your hotkeys keep working. Right-click this icon "
                                        "to quit."), QSystemTrayIcon.Information, 5000)
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
        exitwatch.quitting()   # a run that dies from here on died closing (exitwatch.py)
        for step in (self._finish_removals, self.timer.stop, self._voice_timer.stop,
                     self._release_ptt,
                     self._stop_capture, self._remember_usage, self.cfg.save, self.overlay.shutdown,
                     self.hotkeys.stop, self.replay.stop, self.remote.stop,
                     self._stop_remote_addons,
                     self.radio.shutdown, tor.shutdown, self.apps.shutdown,
                     self.triggers.shutdown,
                     self.linkbar.shutdown, ytworker.drop_all,
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
