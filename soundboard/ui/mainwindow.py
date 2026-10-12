"""The main window: pads, transport, web search, the audio panel, auto push-to-talk."""
from __future__ import annotations

import copy
import html
import re
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Literal, overload

import numpy as np
from PySide6.QtCore import (QEvent, QFileSystemWatcher, QObject, QPoint, QSignalBlocker, QSize,
                            Qt, QTimer, QUrl, QVariantAnimation, Signal)
from PySide6.QtGui import (QActionGroup, QColor, QCursor, QDesktopServices, QIcon,
                           QKeySequence, QPainter, QPixmap, QShortcut)
from PySide6.QtWidgets import (QApplication, QBoxLayout, QCheckBox, QComboBox, QDialog, QFileDialog,
                               QFrame,
                               QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QProgressBar,
                               QPushButton, QScrollArea, QSizePolicy, QSlider, QStackedWidget,
                               QSystemTrayIcon, QTabBar, QToolTip, QVBoxLayout, QWidgetItem,
                               QWidget, QWidgetAction)
from shiboken6 import isValid as qt_valid

from soundboard import engine as eng
from soundboard import bunny, theme, winkeys, winpath, ytdl, ytworker
from soundboard.engine import SR, Engine
from soundboard.engine import is_virtual as is_virtual_cable
from soundboard import exitwatch
from soundboard import (appaudio, autostart, backup, catswitch, destination, library, midi,
                        remote, otherboards, reset, soundfx, thumbs, trash, updates, videos,
                        voicesdk)
from soundboard import (appsetup, directmic, discordcfg, ffmpegget, michelper, net, netlog,
                        profiles, quality, rawmic, shellicon, sourceinfo, thumbbar, tips, tor,
                        usage, watchaddon)
from soundboard.replay import InstantReplay
from soundboard.library import (AUDIO_EXTS, PAD_COLORS, PRESS_MODE, RESOURCE_DIR, Config,
                                SoundMeta, cache_keep, clean_tags, duplicate, fingerprint,
                                import_file, load_original, load_sound, loose_sounds,
                                prune_cache, save_clip)
from soundboard.settings import HOTKEY_ACTIONS, HotkeyDialog, SettingsDialog, pretty_key
from soundboard.shuffle import ShuffleBag
from soundboard.ui.crashdialog import free_dialog
from soundboard.ui.dialogs import EditDialog, TabHelpPopup
from soundboard.ui import importreport
from soundboard.ui import routewarn
from soundboard.ui.dropveil import DropVeil
from soundboard.ui import toast as toastmod
from soundboard.ui import (a11y, alsosend, appstate, busy, clipeditor, icons, responsive,
                           sourcedialog, splash, taboff, themecover)
from soundboard.ui.speedpitch import SpeedPitchButton
from soundboard.ui.panel import (BAR_H, CONTROL_H, EqPanel, Flow, FoldCard, VolumeControl, bar,
                                 capped, card, hint_label, icon_label, info_button,
                                 steady_number, vsep)
from soundboard.ui.downloadbar import DownloadBar
from soundboard.ui.linkbar import PLAY_ID as LINK_ID
from soundboard.ui.linkbar import LinkBar
from soundboard.ui.livedot import set_tab_live
from soundboard.ui.livedot import set_tint as set_live_tint
from soundboard.ui.logowidget import LogoWidget, glow_icon
from soundboard.ui import sidebar
from soundboard.ui.sidebar import SHUT_W, SideTabs
from soundboard.ui.ytsearch import SearchResults
from soundboard.ui.setupshow import SetupShow
from soundboard.ui.spacekey import SpaceKey
from soundboard.ui.padbatch import PadSelection, fill_colour_menu
from soundboard.ui.overlay import Overlay
from soundboard.ui.appspanel import AppsTab, ElidedLabel
from soundboard.ui.triggershost import BoardHost
from soundboard.ui.triggerstab import TriggersTab
from soundboard.ui.radiopanel import RadioOff, RadioTab
from soundboard.ui.voicepanel import VoicePanel
from soundboard.ui.playbutton import PlayButton
from soundboard.ui.widgets import (DropdownMenu, Meter, NameAndSeek, Pad, PadGrid, SeekSlider,
                                   SteadyTabs, expand_dropped, fmt_pos, loudness, pad_height,
                                   spectrum, take_out, SLIM_PAD_H)
from soundboard.wheelguard import AppStyle, no_wheel
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


SHORT_SOUND_S = 0.3   # an added sound shorter than this gets a "very short" note
UNDO_S = 10          # how long "Removed … · Undo" stays up
UNDO_KEY = "undo-sounds"   # its card (toast key)
TOAST_EXPAND = QSize(900, 640)   # a shrunk card clicked: the window grows to this
# shown when instant replay goes on: it records whoever is talking in a call
REPLAY_NOTE = _("Instant replay is on: your key keeps the last seconds you heard. In some "
                "places recording a call needs everyone's OK, so only keep clips of people "
                "who are fine with it.")
CHIPS_ROW_H = 30      # the now-playing row: a chip's 24 px ■ button, its margins and border
TICK_MS = 33         # the UI timer while the window is on screen (meters, visualisers)
TICK_BG_MS = 100     # ...while it's on screen but another program is in front (a game)
HELPER_RETRY_S = 60.0   # a mic helper check that failed is tried again after this long
TICK_IDLE_MS = 250   # ...and while it's in the tray or minimised (push-to-talk, watchdog)
TICK_QUIET_MS = 100  # on screen with nothing moving: no sound, radio, recording or level
LEVEL_QUIET = 0.003  # a level below this (-50 dB) shows as nothing on the meters
TRIGGERS_LOAD_MS = 50   # Onion Watch loads this long after the window is built
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
BODY_SIDE = 14         # the gap around the window's content (beside the tab rail too)...
BODY_SIDE_TIGHT = 8    # ...and beside the rail in a narrow window
SETTINGS_ROOM = QSize(480, 520)   # what Settings opened from the mini player grows it to
MINI_SIZE = QSize(440, 380)   # below this the window becomes the mini player...
MINI_PAD_ROWS = 1             # ...which has the pads above it when this many rows fit
QUEUE_CHIPS = 5          # queued sounds shown by name above the pads (then "+n more")
SEARCH_WAIT_MS = 100     # typing in the search box filters the pads once it pauses this long
LINK_WAIT_MS = 400       # a link in the search box is looked up once it stays this long
PAD_SIZE_WAIT_MS = 50    # dragging Pad size re-lays the pads at most this often
RANDOM = "__random__:"   # hotkey action prefix: a random sound from the category after it
ALL = _("All")       # the category tab that shows every sound
MIC_OFFER_MS = 1000   # an older mic part's update is offered this long after the window shows
TLS_WARM_MS = 2500     # Qt's TLS is set up this long after the start (_warm_tls)
TIP_DELAY_MS = 8000    # the first tip waits this long after the start
TIP_RETRY_MS = 60_000  # ...and is tried again this often while it can't show
LANG_OFFER_SEEN = "language-offer"   # in Config.tips_seen: the language bar was turned down
FF_CHECK_MS = 1500     # the FFmpeg check's answer is taken this long after the start
FF_ASK_OFF = "ffmpeg-offer"   # in Config.tips_seen: the FFmpeg bar's Don't ask again
SEARCH_MIN_W = 220    # the Sounds tab's search box, until the window gets narrow
# ...and its most: a few words go in it, so past this it's only a longer empty bar
# (456 px at 1180x720, so normal windows are unchanged). The seek bar, the levels and
# the drop box still follow the window: wider is useful there (U11).
SEARCH_MAX_W = 480
VOICE_POLL_MS = 3000  # how often the game in front is looked at (soundboard.voicesdk)
VOICE_POLL_IDLE_S = 15   # ...while nobody sees the hint and nothing switches by itself
# Setup -> Devices -> Send my sounds to (Config.route, library.ROUTES): the mic, nobody,
# or one of the output devices by name (ROUTE_DEVICE + its name: "cable" for a virtual
# cable, "device" for anything else)
SEND_TO = _("Send my sounds to")
ROUTE_CHOICES = ((_("My mic (normal)"), "mic"),
                 (_("Nobody: only I hear them"), "off"))
ROUTE_DEVICE = "device:"


class SnugTabBar(QTabBar):
    """A tab bar no wider than its tabs. Qt's minimum keeps room for the scroll
    arrows even with one short tab, which left a wide gap before the "+" after it."""

    def minimumSizeHint(self) -> QSize:
        m = super().minimumSizeHint()
        return QSize(min(m.width(), self.sizeHint().width()), m.height())


class WidthScroll(QScrollArea):
    """While it's the page showing, it needs its content's width, so a narrow window
    shuts the rail before the page gets a sideways scroll bar (that only worked while
    the levels strip happened to shut the rail first). Only when shutting it would be
    enough (`room()`: the page's width with the rail shut): wider content scrolls
    sideways rather than turn the window into the mini player."""

    dl_column: QWidget | None = None   # the column the download bar lines up with

    def __init__(self, room, narrowest=None):
        super().__init__()
        self._room = room
        # the content's width in its narrowest arrangement (Setup: one column). What it
        # needs, not what it has now: two columns side by side mustn't shut the rail
        self._narrowest = narrowest

    def minimumSizeHint(self) -> QSize:
        m = super().minimumSizeHint()
        page = self.widget()
        if page is None or not self.isVisible():   # a page not showing
            return m
        content = (self._narrowest() if self._narrowest is not None
                   else page.minimumSizeHint().width())
        need = content + self.verticalScrollBar().sizeHint().width()
        return QSize(max(m.width(), need), m.height()) if need <= self._room() else m


class BannerButton(QPushButton):
    """A one-line button that never makes the window wider: in less room it shows
    `short`, and in less than that its text is cut with "…". A banner as wide as its
    whole text pushed a ~750 px window into the mini player, banner and all."""

    def __init__(self, text: str, short: str):
        super().__init__(text)
        self._full, self._short = text, short
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setToolTip(text)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        room = self.width() - self.iconSize().width() - 48   # icon, padding, gap
        fm = self.fontMetrics()
        if fm.horizontalAdvance(self._full) <= room:
            text = self._full
        else:
            text = fm.elidedText(self._short, Qt.TextElideMode.ElideRight, max(0, room))
        if text != self.text():
            self.setText(text)


class _Moved(QObject):
    """Calls `fn` (once, after the layout settles) when the watched widget moves or
    changes size."""

    def __init__(self, widget: QWidget, fn):
        super().__init__(widget)
        self._fn = fn
        widget.installEventFilter(self)

    def eventFilter(self, obj, e):
        if e.type() in (QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.Show):
            QTimer.singleShot(0, self, self._fn)
        return False


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


# the colour wrapper old status-line texts carry (MainWindow.say drops it)
_TONE_SPAN = re.compile(r"<span style='color:[^']*'>(.*)</span>", re.S)


class Bridge(QObject):
    loaded = Signal(str, object, str)          # id, data|None, error
    exported = Signal(str, int, str)           # file, sounds written, error
    unpacked = Signal(object, object, str)     # backup.Imported|None, backup.Package, error
    update = Signal(object, str, bool)         # updates.Release|None, error, asked by the user
    update_progress = Signal(object, object)   # bytes of the new version downloaded, of
                                               # how many (0: not known)
    update_ready = Signal(object, str)         # its installer's Path|None, error
    watch_update = Signal(object)              # a newer Onion Watch: watchaddon.Offer
    discord = Signal(object)                   # [discordcfg.Settings] read in the background
    mic_users = Signal(object)                 # [appaudio.App] recording the mic (rawmic)
    counted = Signal()                         # the daily usage count was sent (usage.py)
    imported = Signal(object, object, object)  # meta|None, data|None, Skipped|None
    preview = Signal(str, object, float, int)  # id, audio with unsaved effects|None, gain, gen
    ffmpeg = Signal(object, object)            # ffmpegget.Health, after a fix: "" or its error
    ffmpeg_progress = Signal(int)              # percent of FFmpeg downloaded (-1: not known)


def is_hands_free(name: str | None) -> bool:
    """A Bluetooth headset's phone-call mic ("Headset (… Hands-Free AG Audio)")."""
    n = (name or "").lower()
    return "hands-free" in n or "hands free" in n


def _holds_focus(w: QWidget) -> bool:
    """The keyboard focus is in `w`."""
    fw = QApplication.focusWidget()
    return fw is not None and w.isAncestorOf(fw)


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
    update_state = Signal()             # the update card changed (Settings > Updates follows)
    mic_attached = Signal(str, str)     # attach_mic finished: the mic, error ("" = done)
    helper_checked = Signal()           # michelper.ready() asked again (on a thread)
    cable_removed = Signal(str)         # remove_cable finished: error ("" = done)
    remote_changed = Signal()           # a remote control server started or stopped
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
        # before the UI is built, so everything polishes in-theme
        if isinstance(app, QApplication):
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
        # buttons in the taskbar's hover preview, like Discord's mute / deafen
        tb = thumbbar
        self.thumbbar = tb.ThumbBar(self, {
            tb.LAST: self.play_last,
            tb.PAUSE: self._pause_clicked,
            tb.STOP: self._stop_all_clicked,
            tb.RANDOM: self.play_random,
            tb.LIVE: lambda: self.set_sending(not self.engine.sending)})
        self._radio_paused = None   # the station Pause stopped, for Play to turn back on
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
        self.bridge.ffmpeg.connect(self._on_ffmpeg)
        self.bridge.ffmpeg_progress.connect(self._on_ffmpeg_progress)
        self._removed: list[tuple[SoundMeta, int, np.ndarray | None]] = []   # undo-able
        # windows beside the board, not over it (U4): the one Settings, and an Edit
        # sound for each sound being edited
        self._settings_dlg: SettingsDialog | None = None
        self._editors: dict[str, EditDialog] = {}
        self._packs_removed: set[str] = set()   # sound packs to stop keeping after Undo
        self._render_gen: dict[str, int] = {}   # sid -> newest effects render (_rerender)
        self.shuffle = ShuffleBag()       # the random-sound hotkeys
        self._last_sid: str | None = None   # the last sound played (its replay hotkey)
        self._queue: list[str] = []       # sounds waiting for the ones playing to finish
        self._stopped_at = (0.0, "")       # (when, which) a ■ for one sound last stopped
        self._cool: dict[str, float] = {}   # sid -> time.monotonic() its cooldown ends
        self._waiting: dict[str, list[QTimer]] = {}   # sid -> its delayed starts
        self._hotkeys_off = False         # "All hotkeys off": only that key still works
        self._voice_was: bool | None = None   # voice changer state before a held key
        Pad.single_click = self.cfg.single_click
        self._imported_short = False      # a sound added in this batch is under SHORT_SOUND_S
        self._quitting = False            # a real quit (not "close to the tray")
        self._tray_told = False           # the "still running in the tray" note was shown
        self.tray: QSystemTrayIcon | None = None
        self.release: updates.Release | None = None   # a newer version, once found
        self._update_file: Path | None = None   # its downloaded, checked installer
        self._downloading = False
        self._update_got = (0, 0)     # bytes downloaded, of how many (0: not known)
        self._update_cancel = False   # Cancel was clicked: the download stops at its next chunk
        self._update_err = ""         # why the last try failed ("" = it didn't)
        self._update_detail = ""      # what went wrong, for Copy error
        self._update_fails = 0        # failed tries in a row: from 2, Copy error
        self._update_box: QMessageBox | None = None   # "Downloading…" open over it
        self.watch_offer: watchaddon.Offer | None = None   # an urgent Onion Watch fix
        self._urgent_hidden: set[str] = set()   # "board 1.9.6" / "watch 0.8.2", this run
        # set up for the app you're using (appsetup): the bar's app and what it shows.
        # Before the Discord check below: on a slow start its answer (_on_discord) comes
        # in while the splash pumps events, before the end of __init__
        self._setup_tracker = appsetup.Tracker()
        self._setup_app: appsetup.Seen | None = None
        self._setup_state = ""        # "offer", "done" or "" (hidden)
        self._setup_skipped: set[str] = set()   # answered Not now, this run
        self._setup_undo: dict | None = None    # the dest settings before a switch
        self._setup_hide = QTimer(self, singleShot=True)
        self._setup_hide.timeout.connect(self._hide_setup)
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
        # boards the installer's ticked box brought over: asked once they're in
        self._ask_keep: list[str] = []
        self._exporting = False
        self._import_errors: list[importreport.Skipped] = []
        self._import_total = 0      # this batch, for the toast's "3 of 12"
        self._import_card_shut = False   # its card closed with ✕: the import goes on
        self._import_stop = threading.Event()   # its Stop: the files not started are skipped
        # the pads come in a few at a time while a big import runs, each playable at once
        self._import_pads = QTimer(self, singleShot=True, interval=300,
                                   timeout=self._rebuild_pads)   # pyright: ignore[reportCallIssue]
        self._import_ids: list[str] = []   # added in this batch: Undo takes them off
        # sound id -> the hotkey it had in another soundboard (Import from Soundpad),
        # given to it once it's in if nothing here has that key
        self._import_keys: dict[str, str] = {}
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
        self._xruns_shown = 0             # drop-out count last told (the "audio" toast)
        self._audio_said = ""             # what that toast says now
        self._talk_until = 0.0            # "hearing you" indicator holds until this time
        self._talk_shown: bool | None = None
        self.virtual_mic: str | None = None
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
        self._pill_long = ""              # the setup pill's whole text (its tip, its name)
        self._pill_good = False           # set up: the pill hides (_show_pill)
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
            self.rail.sync()   # (it heard nothing)
        reset.before_update(self.cfg)   # a restore point first, when this is an update
        library.tidy_files(self.cfg)   # files from before library folders move in
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
        app = QApplication.instance()
        assert isinstance(app, QApplication)   # made before the window
        app.applicationStateChanged.connect(self._set_tick_rate)
        app.applicationStateChanged.connect(self._app_state)
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
        # the check started behind the loading screen (app.py); its answer, and a
        # download if one is needed, once the window is up
        QTimer.singleShot(FF_CHECK_MS, self, self.check_ffmpeg)
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
        # (PySide takes properties and signals as keywords; the stubs don't know)
        self._dev_retry = QTimer(self, singleShot=True, interval=100, timeout=self._dev_pump)   # pyright: ignore[reportCallIssue]
        self._recover_n, self._recover_at = 0, 0.0   # see _recover_devices
        self._gone_n = 0   # checks in a row that found the failing device unplugged
        if sys.platform == "win32":
            self._default_timer.start(DEFAULT_POLL_MS)
        self._init_fit()
        self.resize(1180, 720)
        if self.cfg.always_on_top:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self._init_tray()
        if autostart.available():
            autostart.refresh(self.cfg.autostart_hidden)   # the app may have moved
        self._pending_note: str | None = None
        if self.cfg.load_note:   # settings came from a backup or the defaults: say so
            QTimer.singleShot(1200, self._show_load_note)
        QTimer.singleShot(TLS_WARM_MS, self, self._warm_tls)
        QTimer.singleShot(TLS_WARM_MS, self, self._precompile_addons)

    def _precompile_addons(self):
        """The add-ons' compiled files (modules.precompile), written on a thread while
        nothing plays, so opening the Triggers tab doesn't skip a sound. Once per
        add-on version: after that it only checks they're there."""
        from soundboard import modules
        engine = self.engine
        threading.Thread(target=lambda: modules.precompile(modules.discover(),
                                                           engine.any_playing),
                         daemon=True, name="addon-precompile").start()

    def _warm_tls(self, tries: int = 0):
        """Qt sets up its TLS (reads Windows' certificates) on the first https request,
        on the UI thread and holding Python's lock: ~17 ms, long enough to skip a sound
        playing as the Radio tab or a web search's pictures first load. Done here, soon
        after the start and while nothing plays (no network: nothing is sent)."""
        if self._shut_down:
            return
        if self.engine.any_playing() and tries < 20:
            QTimer.singleShot(TLS_WARM_MS, self, lambda: self._warm_tls(tries + 1))
            return
        try:
            from PySide6.QtNetwork import QSslConfiguration
            QSslConfiguration.defaultConfiguration()
        except Exception:  # noqa: BLE001 - a later request sets it up as before
            log.debug("warming up TLS failed", exc_info=True)

    _mic_offer = None       # the open MicUpdateOffer
    _mic_updating = False   # attach_mic was started from it (its own result messages)
    _autofixing = False     # attach_mic(auto=True): the app's own repair, nobody clicked
    _autofix_err = ""       # that repair failed: the card asks for a click until it works
    _autofix_tried = False  # it ran since the mic last worked (once per time it's off)
    _declined = False       # the last set-up's Windows prompt got a No
    _show_bun = False       # the set-up running is the first one: Bun's show explains it
    _helper_checking = False
    _helper_failed = False  # the last check raised: the next waits HELPER_RETRY_S
    _helper_check_at = 0.0  # when the last check started (time.monotonic())
    _mic_offered = False    # shown this start (it comes back next start until updated)
    _silent_said = False    # the "your mic sends no sound" toast came this run

    def _mic_update_due(self) -> bool:
        cfg = self.cfg
        return (cfg.route == "mic" and bool(cfg.mic_device) and not self._attaching
                and directmic.status(cfg.mic_device) == "outdated")

    def _offer_mic_update(self):
        """An older mic part (1.9.20 and before sat where raw streams skip it: Discord's
        Studio, Chrome, Edge) is offered an update a second after the window opens, not
        left to a button nobody looks for. Windows' admin prompt only comes after
        *Install update*: never by itself, and never from the tray (showEvent asks again
        once the window is open). Offered again each start until it's updated: an old
        part may not reach every app. Setup keeps the button meanwhile."""
        if self._shut_down or self._mic_offer is not None or self._mic_offered:
            return
        if not self.isVisible():
            return
        if self.isMinimized() or QApplication.activeModalWidget() is not None:
            QTimer.singleShot(MIC_OFFER_MS, self, self._offer_mic_update)   # once it's free
            return
        if not self._mic_update_due():
            return
        self._mic_offered = True
        log.info("offering the newer mic part")
        from soundboard.ui.micupdate import MicUpdateOffer
        offer = self._mic_offer = MicUpdateOffer(self)
        offer.accepted.connect(self._accept_mic_update)
        offer.finished.connect(self._mic_offer_closed)
        offer.popup()

    def _mic_offer_closed(self):
        self._mic_offer = None

    def _accept_mic_update(self):
        """Install update: the mic, the route or the part may have changed while the
        offer was up, so check again before Windows is asked."""
        if not self._mic_update_due():
            cfg = self.cfg
            if cfg.route == "mic" and directmic.works(directmic.status(cfg.mic_device)):
                self.toast(_("Your mic is already up to date."), "ok")
            else:
                self.toast(_("Nothing to update now: your mic settings changed."))
            return
        log.info("updating the mic part (asked)")
        self._mic_updating = True
        self.toast(_("Updating Onion Board's part of your mic so every app hears your "
                     "sounds: click Yes when Windows asks.") if michelper.will_ask() else
                   _("Updating Onion Board's part of your mic so every app hears your sounds."))
        self.attach_mic(clean=True)

    def _show_load_note(self):
        """Started hidden in the tray (--tray at sign-in)? Then the box waits for the
        window to be opened, instead of popping up over whatever the user is doing."""
        if self.isVisible():
            self.tell(_("Settings were restored"), self.cfg.load_note, "warn", 20000)
        else:
            self._pending_note = self.cfg.load_note

    # ------------------------------------------------------------------ UI build
    # Layout: the tab rail (with Live, Stop all and the setup pill) / tabs / mixer strip.
    # Every tab is built the same way: a toolbar row on top, its content, and a
    # bottom bar ending in "Volume [slider %] | Hear it myself" for that source.
    def _build_ui(self):
        # page 0 the whole window, page 1 the mini player it turns into when it's
        # made too small to use (see _refit)
        self._pages = QStackedWidget()
        self.setCentralWidget(self._pages)
        root = self._full = QWidget()
        root.setObjectName("root")   # the theme's window gradient
        self._pages.addWidget(root)
        self._full_row = QHBoxLayout(root)   # the tab rail (ui/sidebar.py), then the rest
        self._full_row.setContentsMargins(0, 0, 0, 0)
        self._full_row.setSpacing(0)
        body = QWidget()
        self._full_row.addWidget(body, 1)
        rv = QVBoxLayout(body)
        self._body_lay = rv
        rv.setContentsMargins(BODY_SIDE, 10, BODY_SIDE, 10)
        rv.setSpacing(8)

        # ---- what was the header: the onion and name, the setup pill, Live, Stop all and
        # Settings, all on the tab rail now (ui/sidebar.py); made here for _paint_logo
        self.logo = LogoWidget()
        self.wordmark = QLabel("Onion Board")
        self.wordmark.setObjectName("wordmark")
        from soundboard import __version__
        # on the rail: the name over a quiet "v1.9.28" (the title bar says "from source");
        # who made it is a tip on all three
        self.tagline = sidebar.ClickLabel(f"v{__version__}")
        self.tagline.setObjectName("tagline")
        about = _("an app by Onion Alien · v{version_text}", version_text=version_text())
        for w in (self.logo, self.wordmark):
            w.setToolTip(about)
        whats_new = _("What's new")   # the version is a button to it
        self.tagline.setToolTip(f"{about}\n{whats_new}")
        self.tagline.clicked.connect(lambda: (usage.used("whats-new"), self.show_whats_new()))
        self.pill = QPushButton()
        self.pill.setObjectName("pill")
        self.pill.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pill.setIconSize(QSize(sidebar.ICON, sidebar.ICON))
        self.pill.clicked.connect(lambda: self.tabs.setCurrentWidget(self.setup_page))
        # a new version: a card over the On Air card (an icon, shut) that follows it
        # from found to downloading to ready (_show_update_state)
        self.btn_update = sidebar.UpdateCard()
        self.btn_update.clicked.connect(self._update_clicked)
        self.btn_update.copy.clicked.connect(self._copy_update_error)
        # the two switches for everything at once, whatever tab you're on
        self.btn_air = QPushButton()
        self.btn_air.setObjectName("onair")
        self.btn_air.setCheckable(True)
        self.btn_air.setChecked(True)
        self.btn_air.toggled.connect(self.set_sending)
        self.btn_air.clicked.connect(
            lambda on: usage.used("on-air-on" if on else "on-air-off"))
        icons.set_icon(self.btn_air, "live", "danger_text", "on_live", size=sidebar.ICON, gap=False)
        self.set_sending(True)
        # Keep the mode controller for shared commands; its full picker lives on Setup.
        from soundboard.ui.destpanel import ModeButton
        self.mode_btn = ModeButton(self)
        self.mode_btn.setParent(self)
        self.mode_btn.hide()
        self.stop_btn = QPushButton()
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setProperty("quiet", True)   # red text, no box: Live is the loud one
        sidebar.put(self.stop_btn, _("Stop all"),
                    tip=_("Stops every sound, the radio and every program, and turns "
                          "the voices off"))
        self.stop_btn.clicked.connect(self._stop_all_clicked)
        icons.set_icon(self.stop_btn, "stop", "danger_text", size=sidebar.ICON, gap=False)
        self.gear = QPushButton(_("Settings"))
        self.gear.setObjectName("settings")
        self.gear.setProperty("quiet", True)
        self.gear.setToolTip(_("Themes, hotkeys and more"))
        self.gear.clicked.connect(lambda: self.open_settings())
        # (showing its page: the accent, as a selected tab's icon; on_accent was white
        # on the soft fill, all but gone in Light)
        icons.set_icon(self.gear, "settings", checked_color="accent", size=sidebar.ICON, gap=False)
        self.gear.setProperty("railtext", _("Settings"))   # at the foot of the tab rail
        # the onion beside it: the Discord, feedback, a bug report, the code (each only
        # opens a page in the browser, feedback.py)
        self.btn_about = QPushButton(_("Help and community"))
        self.btn_about.setObjectName("settings")   # Settings' look: a quiet square
        self.btn_about.setProperty("quiet", True)
        self.btn_about.setToolTip(_("Help and community"))
        self.btn_about.setProperty("railtext", _("Help and community"))
        icons.set_icon(self.btn_about, "onion", size=sidebar.ICON, gap=False)
        self.about_menu = DropdownMenu(self.btn_about)
        self.about_menu.aboutToShow.connect(self._fill_about_menu)
        self.btn_about.clicked.connect(self._show_about_menu)
        self._paint_logo()

        # only a sign: the one switch is "Hear what they hear" in the mixer at the bottom
        self.mic_banner = BannerButton(_("You're hearing your mic output: mic + sounds, "
                                         "exactly what others hear"),
                                       _("Hearing your mic output"))
        self.mic_banner.setObjectName("micbanner")
        self.mic_banner.setFocusPolicy(Qt.FocusPolicy.NoFocus)
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
        self.urgent_lbl.setTextFormat(Qt.TextFormat.PlainText)   # the reason is release-note text
        self.urgent_lbl.setWordWrap(True)   # never makes the window wider
        # Onion Board's fix downloading: the update card's bar and words, not new ones
        self.urgent_prog = QProgressBar()
        self.urgent_prog.setObjectName("updatebar")
        self.urgent_prog.setRange(0, 100)
        self.urgent_prog.setTextVisible(False)
        self.urgent_prog.setFixedHeight(sidebar.UpdateCard.BAR_H)
        self.urgent_prog.hide()
        self.urgent_sub = QLabel()
        self.urgent_sub.setObjectName("hint")
        self.urgent_sub.setTextFormat(Qt.TextFormat.PlainText)
        self.urgent_sub.setWordWrap(True)
        self.urgent_sub.hide()
        uv = QVBoxLayout()
        uv.setSpacing(4)
        uv.addWidget(self.urgent_lbl)
        uv.addWidget(self.urgent_prog)
        uv.addWidget(self.urgent_sub)
        uh.addLayout(uv, 1)
        self.urgent_btn = QPushButton()
        self.urgent_btn.setObjectName("primary")
        self.urgent_btn.clicked.connect(self._urgent_clicked)
        uh.addWidget(self.urgent_btn)
        hide = QPushButton()
        hide.setObjectName("urgenthide")
        hide.setAccessibleName(_("Hide"))
        hide.setToolTip(_("Hide until Onion Board starts again"))
        icons.close_button(hide, 28, "warn_text")
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
        self.tip_lbl.setTextFormat(Qt.TextFormat.PlainText)
        self.tip_lbl.setWordWrap(True)
        th.addWidget(self.tip_lbl, 1)
        self.tip_btn = QPushButton(_("Show me"))
        self.tip_btn.setObjectName("small")
        self.tip_btn.clicked.connect(self._tip_show_me)
        th.addWidget(self.tip_btn)
        hide = QPushButton()
        hide.setObjectName("urgenthide")
        hide.setAccessibleName(_("Hide the tip"))
        hide.setToolTip(_("Hide this tip (Settings → General turns tips off)"))
        icons.close_button(hide, 28)
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
        self.setup_lbl.setTextFormat(Qt.TextFormat.RichText)
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
        self.setup_x = QPushButton()
        self.setup_x.setObjectName("urgenthide")
        icons.close_button(self.setup_x, 28)
        self.setup_x.clicked.connect(self._setup_x_clicked)
        sh.addWidget(self.setup_x)
        self.setup_bar.hide()
        rv.addWidget(self.setup_bar)

        # FFmpeg (check_ffmpeg): its download's progress with Stop, or, when the app
        # couldn't get it by itself, what stops working and Fix it. The same slim bar as
        # the Discord offer, never a window
        self.ff_bar = QFrame()
        self.ff_bar.setObjectName("tipbar")
        fh = QHBoxLayout(self.ff_bar)
        fh.setContentsMargins(12, 6, 6, 6)
        fh.setSpacing(8)
        self.ff_lbl = QLabel()
        self.ff_lbl.setTextFormat(Qt.TextFormat.PlainText)   # winget's own words may be in it
        self.ff_lbl.setWordWrap(True)
        fh.addWidget(self.ff_lbl, 1)
        self.ff_fix = QPushButton(_("Fix it"))
        self.ff_fix.setObjectName("primary")
        self.ff_fix.clicked.connect(self._ffmpeg_fix_clicked)
        fh.addWidget(self.ff_fix)
        self.ff_stop = QPushButton(_("Stop"))
        self.ff_stop.setObjectName("small")
        self.ff_stop.clicked.connect(self._ffmpeg_stop)
        fh.addWidget(self.ff_stop)
        self.ff_never = QPushButton(_("Don't ask again"))
        self.ff_never.setObjectName("small")
        self.ff_never.setToolTip(_("Settings → Data & quality still has it"))
        self.ff_never.clicked.connect(self._ffmpeg_never)
        fh.addWidget(self.ff_never)
        hide = QPushButton()
        hide.setObjectName("urgenthide")
        hide.setAccessibleName(_("Hide"))
        hide.setToolTip(_("Hide until Onion Board starts again"))
        icons.close_button(hide, 28)
        hide.clicked.connect(self._ffmpeg_not_now)
        fh.addWidget(hide)
        self.ff_hide = hide
        self.ff_bar.hide()
        self.ffmpeg: ffmpegget.Health | None = None   # the last check's answer
        self._ff_checking = False
        self._ff_not_now = False   # hidden until the next start
        self._ff_error = ""        # the last fix's error, shown on the bar
        self._ff_waiting: list = []   # (button, release) of fixes still going
        self._ff_getting = False   # a fix is going (by itself or clicked)
        self._ff_percent = -1      # ...how far its download is (-1: not known)
        self._ff_stop_flag: threading.Event | None = None   # Stop sets it
        self._ff_auto_tried = False   # got by itself once this start (not again)
        self._ff_auto_now = False     # the get running now is that one (for the count)
        self._ff_done = False         # the last fix worked (Settings says so)
        rv.addWidget(self.ff_bar)

        # Windows is in a language the board has but isn't showing: offered in that
        # language, so someone who can't read English finds it (_offer_language)
        self.lang_bar = QFrame()
        self.lang_bar.setObjectName("tipbar")
        lh = QHBoxLayout(self.lang_bar)
        lh.setContentsMargins(12, 6, 6, 6)
        lh.setSpacing(8)
        self.lang_lbl = QLabel()
        self.lang_lbl.setTextFormat(Qt.TextFormat.PlainText)
        self.lang_lbl.setWordWrap(True)
        lh.addWidget(self.lang_lbl, 1)
        self.lang_btn = QPushButton()
        self.lang_btn.setObjectName("small")
        self.lang_btn.clicked.connect(lambda: self.switch_language(self._lang_offered))
        lh.addWidget(self.lang_btn)
        hide = QPushButton()
        hide.setObjectName("urgenthide")
        icons.close_button(hide, 28)
        hide.clicked.connect(self._no_language)
        lh.addWidget(hide)
        self.lang_hide = hide
        self.lang_bar.hide()
        self._lang_offered = ""
        rv.addWidget(self.lang_bar)

        # the bar and the tabs share a box with no gap of its own: every tab page already
        # starts 8 px down, so the bar's gap to the first row matches the rows below it
        tabs_box = self._tabs_box = QWidget()
        tv = QVBoxLayout(tabs_box)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(0)
        self._tabs_lay = tv
        # in a box of its own, so its edges can follow the page's cards (_fit_dl_bar)
        dl_box = QWidget()
        self._dl_lay = QHBoxLayout(dl_box)
        self._dl_lay.setContentsMargins(0, 0, 0, 0)
        self.download_bar = DownloadBar(self)
        self._dl_lay.addWidget(self.download_bar)
        tv.addWidget(dl_box)
        self.download_bar.shown_changed.connect(self._dl_bar_gap)
        self.download_bar.shown_changed.connect(lambda _on: self._refit_dl_bar())
        self.download_bar.room_changed.connect(self._refit_dl_bar)

        # ---- tabs
        self.tab_info: dict[str, tuple[str, str]] = {}   # page attr -> (title, text) for ⓘ
        self.tabs = SideTabs()   # its bar hidden: the rail down the left shows the tabs
        self.tabs.setDocumentMode(True)
        self.tabs.setIconSize(QSize(sidebar.ICON, sidebar.ICON))
        SteadyTabs(self.tabs)   # a change inside a page doesn't repaint the whole board
        tv.addWidget(self.tabs, 1)
        # the tabs with the bars over them, or Settings in their place (open_settings):
        # the rail and the player and mixer below stay, so sounds can still be stopped
        area = self._tabs_area = QWidget()
        av = QVBoxLayout(area)
        av.setContentsMargins(0, 0, 0, 0)
        av.setSpacing(rv.spacing())
        for strip in (self.mic_banner, self.urgent_bar, self.tip_bar, self.setup_bar,
                      self.ff_bar, self.lang_bar):
            rv.removeWidget(strip)
            av.addWidget(strip)
        av.addWidget(tabs_box, 1)
        self._content = QStackedWidget()
        self._content.addWidget(area)
        rv.addWidget(self._content, 1)
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
        # + More tabs: the tabs switched off (a new user starts with the basic ones), one
        # click to add one; only there while one is off. Right after the last tab
        self.btn_more_tabs = QPushButton(_("More tabs"))
        self.btn_more_tabs.setObjectName("moretabs")
        icons.set_icon(self.btn_more_tabs, "plus", size=sidebar.ICON, gap=False)
        self.btn_more_tabs.setProperty("railtext", _("More tabs"))
        self.btn_more_tabs.setCursor(Qt.CursorShape.PointingHandCursor)
        # a click left an accent ring on it
        self.btn_more_tabs.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.btn_more_tabs.setToolTip(_("Add a tab: radio, sending a program's sound, screen "
                                        "triggers"))
        from soundboard.ui import moretabs
        mt = self.more_menu = moretabs.Menu(self.btn_more_tabs)
        mt.aboutToShow.connect(lambda: self._fill_more_tabs(mt))
        mt.aboutToHide.connect(self._more_tabs_hidden)
        self.btn_more_tabs.clicked.connect(mt.pop)
        self._update_more_tabs()
        self.rail = sidebar.SideRail(
            self.tabs, self.logo, self.wordmark, self.tagline,
            [self.btn_more_tabs], self.cfg.sidebar_open, [self.gear, self.btn_about],
            self._rail_opened,
            # Live and Stop all never move; the pills (what needs attention) sit above
            # them and only show when needed (at the rail's foot, as icons)
            [self.btn_air, self.stop_btn],
            order=[TAB_INDEX[k] for k in self.cfg.sidebar_order if k in TAB_INDEX],
            alerts=[self.pill], update=self.btn_update)
        # Proxy, Tor or Offline mode, a phone remote listening: lines in the On Air card
        # (_net_follow), each one click to its Settings page
        if self.rail.output is not None:
            self.rail.output.lineClicked.connect(self.open_settings)
            self.rail.output.lineClicked.connect(lambda _p: usage.used("on-air-line"))
        self.remote_changed.connect(self._net_follow, Qt.ConnectionType.QueuedConnection)
        remote.on_change(self._remote_watch)
        self._net_follow()
        # Ctrl+1... jump to the tabs in the rail's order, Ctrl+Tab / Ctrl+Shift+Tab step
        # through them (the tab widget does that only while it has the focus)
        for n in range(1, 10):
            QShortcut(QKeySequence(f"Ctrl+{n}"), self,   # pyright: ignore[reportCallIssue]  # signal keyword
                      activated=lambda n=n: self._go_tab(n - 1, absolute=True))
        QShortcut(QKeySequence("Ctrl+Tab"), self, activated=lambda: self._go_tab(1))   # pyright: ignore[reportCallIssue]
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self, activated=lambda: self._go_tab(-1))   # pyright: ignore[reportCallIssue]
        self.rail.orderChanged.connect(
            lambda order: self.set_option("sidebar_order", [TAB_KEYS[i] for i in order]))
        # a tab asked for (the rail, Ctrl+1..., a link) while Settings is up: back to the
        # tabs, on that one
        self.tabs.picked.connect(self.close_settings)
        self._full_row.insertWidget(0, self.rail)
        # Tab goes header, rail, page (as it did with the top tabs), not page, rail; the
        # page's box holds the download bar too, so the bar's buttons come just before it
        prev = self._tabs_box.previousInFocusChain()
        assert prev is not None   # (the chain is a ring)
        status_focus: list[QWidget] = []
        for button in self.rail.status:
            if button is self.btn_air and self.rail.output:
                out = self.rail.output   # (shut: its switch; open: Mute and Stop all)
                status_focus.extend(w for w in (out.switch, out.mute, out.stop, out.setup)
                                    if w is not None)
            status_focus.append(button)
        for w in (*self.rail.buttons, self.btn_more_tabs, *status_focus,
                  self.gear, self.btn_about,
                  self.rail.toggle, self._tabs_box):
            QWidget.setTabOrder(prev, w)
            prev = w
        # right-click a tab: what it's for, or hide it (+ More tabs or Settings > Tabs
        # bring it back)
        for b in self.rail.buttons:
            b.customContextMenuRequested.connect(
                lambda pos, b=b: self.tab_menu(b.index).exec(b.mapToGlobal(pos)))
        # every tab has a line for its right-click "About this tab" (the Apps tab brings
        # its own)
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
        tab = self.cfg.tab if 0 <= self.cfg.tab < self.tabs.count() else 0
        self.tabs.setCurrentIndex(tab if self.tabs.isTabVisible(tab) else 0)
        self.tabs.currentChanged.connect(lambda i: self.set_option("tab", i))
        self.tabs.currentChanged.connect(lambda _i: self._fit_dl_bar())
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

        # the Sounds tab's player; right under the page, where it sat inside it
        rv.addWidget(self.transport)
        self.tabs.currentChanged.connect(lambda _i: self._show_transport())
        self._show_transport()
        self._fit_tab = self.tabs.currentWidget()
        self.tabs.currentChanged.connect(self._fit_setup_tab)

        # ---- mixer strip: the things that apply whatever tab you're on
        rv.addWidget(self._build_mixer())

        self.drop_veil = DropVeil(self)   # "Drop to add 4 files" while files are dragged in
        self._pages.addWidget(self._build_mini())

        self.linkbar.download_started.connect(self._on_download_started)
        self.linkbar.progress.connect(self.download_bar.set_progress)
        self.linkbar.progress.connect(self.mini_download_bar.set_progress)
        self.linkbar.done.connect(self.download_bar.set_done)
        self.linkbar.failed.connect(self.download_bar.set_failed)
        self.linkbar.failed.connect(self.mini_download_bar.set_failed)
        self.linkbar.done.connect(self.mini_download_bar.set_done)
        self.download_bar.retry_requested.connect(self._retry_download)
        self.mini_download_bar.retry_requested.connect(self._retry_download)
        self.download_bar.front_requested.connect(self.linkbar.move_to_front)
        self.mini_download_bar.front_requested.connect(self.linkbar.move_to_front)
        self.linkbar.queue_updated.connect(self.download_bar.set_queue)
        self.linkbar.queue_updated.connect(self.mini_download_bar.set_queue)
        self.download_bar.cancel_requested.connect(self.linkbar.cancel)
        self.mini_download_bar.cancel_requested.connect(self.linkbar.cancel)
        self.download_bar.stop_all_requested.connect(self.linkbar.cancel_all)
        self.mini_download_bar.stop_all_requested.connect(self.linkbar.cancel_all)
        for b in (self.download_bar, self.mini_download_bar):
            b.thumb_lookup = self.ytresults.thumb_for   # (typed in downloadbar.py)
        self.linkbar.queued.connect(self.ytresults.queued)
        self.ytresults.thumb_ready.connect(self.download_bar.set_thumb)
        self.ytresults.thumb_ready.connect(self.mini_download_bar.set_thumb)

    def _on_download_started(self, url: str, title: str, kind: str, secs: float = 0.0):
        pm = self.ytresults.thumb_for(url)
        channel, card_secs = self.ytresults.meta_for(url)
        self.download_bar.set_active(url, title, kind, pm, channel, secs or card_secs)
        self.mini_download_bar.set_active(url, title, kind, pm, channel, secs or card_secs)

    def _build_mini(self) -> QWidget:
        """The mini player: what's playing, play / stop, where it's at, Live and Stop
        all, and the pads above them if there's room. The pads are the real ones,
        moved in and out of the Sounds tab (_set_mini)."""
        page = QWidget()
        v = self._mini_v = QVBoxLayout(page)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)
        self.mini_download_bar = DownloadBar(self)
        self.mini_download_bar.set_mini(True)
        v.addWidget(self.mini_download_bar)
        v.addStretch(0)   # keeps the player at the bottom when the pads don't fit
        card = self._mini_card = QFrame()
        card.setObjectName("transport")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(8, 6, 8, 6)
        cv.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.mini_pp = PlayButton()
        self.mini_pp.setObjectName("transport_play")
        self.mini_pp.setProperty("mini", True)
        self.mini_pp.setToolTip(_("Play / pause"))
        self.mini_pp.clicked.connect(self.toggle_play_pause)
        self.mini_st = QPushButton()
        self.mini_st.setObjectName("transport_stop")
        self.mini_st.setToolTip(_("Stop"))
        self.mini_st.clicked.connect(self.stop_current)
        icons.set_icon(self.mini_st, "stop", size=16)
        for b in (self.mini_pp, self.mini_st):
            b.setFixedSize(34, 30)
            top.addWidget(b)
        self.mini_name = ElidedLabel(self.np_name.text(), hide_overflow=True)
        self.mini_name.setTextFormat(Qt.TextFormat.PlainText)   # sound names are user / web text
        self.mini_name.setStyleSheet("font-weight:600;")
        self.mini_name.setMinimumWidth(30)
        self.mini_name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        top.addWidget(self.mini_name, 1)
        self.mini_air = QPushButton()
        self.mini_air.setObjectName("onair")
        self.mini_air.setCheckable(True)
        self.mini_air.setChecked(self.btn_air.isChecked())
        self.mini_air.setToolTip(self.btn_air.toolTip())
        self.mini_air.toggled.connect(self.set_sending)
        self.mini_air.clicked.connect(
            lambda on: usage.used("on-air-on" if on else "on-air-off"))
        icons.set_icon(self.mini_air, "live", "danger_text", "on_live")
        # "All" in words: an icon-only ■ here looked just like the one-sound ■ on
        # the left, and stopped everything
        self.mini_stop = QPushButton(_("All"))
        self.mini_stop.setObjectName("danger")
        self.mini_stop.setToolTip(self.stop_btn.toolTip())
        self.mini_stop.clicked.connect(self.stop_all)
        icons.set_icon(self.mini_stop, "stop", "danger_text", size=14)
        self.mini_air.setFixedSize(38, 30)
        self.mini_stop.setFixedHeight(30)
        self.mini_stop.setMinimumWidth(38)
        for b in (self.mini_air, self.mini_stop):
            top.addWidget(b)
        cv.addLayout(top)
        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        self.mini_seek = SeekSlider(Qt.Orientation.Horizontal)
        self.mini_seek.setRange(0, 1000)
        self.mini_seek.setObjectName("seek")
        self.mini_seek.setFixedHeight(24)
        self.mini_seek.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.mini_seek.sliderReleased.connect(lambda: self.do_seek(self.mini_seek))
        self.mini_seek.valueChanged.connect(self._seek_preview)
        no_wheel(self.mini_seek)
        bottom.addWidget(self.mini_seek, 1)
        self.mini_time = QLabel(self.np_time.text())
        self.mini_time.setObjectName("muted")
        steady_number(self.mini_time, "00:00 / 00:00")
        bottom.addWidget(self.mini_time)
        cv.addLayout(bottom)
        connection = QHBoxLayout()
        self.mini_connection = QPushButton()
        self.mini_connection.setObjectName("pill")
        self.mini_connection.setMinimumWidth(0)
        self.mini_connection.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.mini_connection.clicked.connect(self._mini_setup)
        connection.addWidget(self.mini_connection, 1)
        self.mini_mic = QPushButton()
        self.mini_mic.setCheckable(True)
        self.mini_mic.setFixedHeight(28)
        self.mini_mic.setToolTip(_("Mute or unmute your mic for others. Your sounds still "
                                   "play for them."))
        self.mini_mic.toggled.connect(self.on_mic_toggle)
        self.mini_mic.clicked.connect(lambda: usage.used("mini-mic-mute"))   # clicks only
        connection.addWidget(self.mini_mic)
        cv.addLayout(connection)
        v.addWidget(card)
        self._sync_mini_mic()
        icons.set_icon(self.mini_pp, "play", "on_accent", size=16)
        return page

    def _mini_setup(self):
        self.resize(max(800, self.width()), max(600, self.height()))
        self.tabs.setCurrentWidget(self.setup_page)
        self._refit()

    def _sync_mini_mic(self):
        if not hasattr(self, "mini_mic"):
            return
        on = self.cfg.mic_enabled
        with QSignalBlocker(self.mini_mic), QSignalBlocker(self.chk_mic):
            self.mini_mic.setChecked(on)
            self.chk_mic.setChecked(on)
        self.mini_mic.setText(_("Mic on") if on else _("Mic muted"))
        self.mini_mic.setAccessibleName(self.mini_mic.text())

    def _set_np_name(self, text: str):
        self.np_name.setText(self.np_name.fontMetrics().elidedText(
            text, Qt.TextElideMode.ElideRight, 186))
        self.np_name.setToolTip(text)
        self._name_seek.relayout()
        self.mini_name.setText(text)   # hides itself when it has no room
        if text == _("Pick a sound"):   # nothing picked: no time either
            self._set_np_time("")

    def _set_np_time(self, text: str):
        """The player's time. Blank (nothing picked) it hides, so the seek line runs
        all the way to the buttons instead of stopping at an empty gap."""
        self.np_time.setText(text)
        self.mini_time.setText(text)
        self._show_np_time()

    def _show_np_time(self, tight: bool | None = None):
        if tight is not None:
            self._np_time_tight = tight   # the fitter's say: no room for it
        show = bool(self.np_time.text()) and not getattr(self, "_np_time_tight", False)
        if show == self.np_time.isHidden():
            self.np_time.setVisible(show)
            responsive.touch(self.np_time)

    def _build_mixer(self) -> QFrame:
        """The levels strip along the bottom, the same on every tab: three labelled
        boxes, left to right the way the sound flows — your mic, what others hear,
        your own headphones. (Each tab's own volume sits in that tab's bar.)"""
        c = self.cfg
        # one slim bar: three groups side by side with a thin line between, each
        # labelled inline (a title row over each box made the strip twice as tall)
        f = QFrame()
        f.setObjectName("deck")
        f.setMinimumHeight(BAR_H)
        h = self._mixer_layout = QHBoxLayout(f)
        h.setContentsMargins(12, 6, 12, 6)
        h.setSpacing(14)
        self.mixer = f
        self._deck_titles: list[QWidget] = []
        self._deck_rows: list[QHBoxLayout] = []
        self._decks: list[tuple[QWidget, ...]] = []   # each group, with the line before it
        # too narrow for all three: one group shown whole (what others hear, unless
        # you pick another) and the other two as icon buttons that bring theirs up
        self._deck_tabs: list[QPushButton] = []
        self._mixer_one = self._mixer_tight = False
        self._mixer_focus = 1

        def group(icon: str, title: str, tip: str) -> tuple[QLabel, QHBoxLayout]:
            sep = vsep() if self._decks else None
            if sep is not None:
                h.addWidget(sep)
            tab = QPushButton()
            tab.setObjectName("iconbutton")
            tab.setProperty("quiet", True)
            tab.setToolTip(title)
            tab.setAccessibleName(title)
            icons.set_icon(tab, icon, "muted")
            tab.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            tab.clicked.connect(lambda _c=False, i=len(self._decks): self._focus_deck(i))
            tab.hide()
            h.addWidget(tab)
            self._deck_tabs.append(tab)
            deck = QWidget()
            deck.setObjectName("decktop")
            row = QHBoxLayout(deck)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            self._deck_rows.append(row)
            row.addWidget(icon_label(icon, tip))
            lbl = QLabel(title)
            lbl.setObjectName("decktitle")
            lbl.setToolTip(tip)
            row.addWidget(lbl)
            self._deck_titles.append(lbl)
            self._decks.append((deck,) if sep is None else (sep, deck))
            h.addWidget(deck)
            return lbl, row

        self.mic_lbl, row = group("mic", _("My mic"),
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
        mic_meter = self.vol_mic.meter
        assert mic_meter is not None   # meter=True
        self.mic_meter = mic_meter
        # shown alone (_mixer_one_at_a_time) its slider takes the room, up to its own
        # most (150 px), with what's left after it
        row.addWidget(self.vol_mic, 1)
        row.addStretch(0)

        send_lbl, row = group("live", _("What others hear"),
                              _("Everything going out to others right now (Discord, a game, "
                                "OBS…): your mic plus whatever is live"))
        self.out_meter = Meter()
        self.out_meter.setMinimumWidth(60)
        self.out_meter.setToolTip(_("Level of what others receive (Discord, the game, OBS…)"))
        row.addWidget(self.out_meter, 1)
        self.btn_check = QPushButton(_("Hear what they hear"))
        self.btn_check.setObjectName("miccheck")
        self.btn_check.setCheckable(True)
        self.btn_check.setToolTip(_("Plays your mic into your headphones on top of the sounds, "
                                    "exactly what others hear. A red banner shows while it's on."))
        self.btn_check.toggled.connect(self.on_mic_check)
        icons.set_icon(self.btn_check, "ear", checked_color="#ffffff")
        row.addWidget(self.btn_check)
        self.btn_check.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        h.setStretchFactor(self._decks[1][-1], 1)   # the "what others hear" group takes the room

        self.hp_lbl, row = group("headphones", _("My headphones"),
                                 _("Only what YOU hear. Doesn't change anything for others."))
        self.vol_mon = VolumeControl(c.mon_vol, tip=_("Only what YOU hear, doesn't change "
                                                      "anything for others"))
        row.addWidget(self.vol_mon, 1)
        row.addStretch(0)
        for vol in (self.vol_mic, self.vol_mon):   # no gap between the slider and its %
            lay = vol.layout()
            assert lay is not None   # made in VolumeControl.__init__
            vol.setMaximumWidth(lay.maximumSize().width())
        self._mic_text = self.chk_mic.text()

        for box, key in ((self.vol_mic, "mic_vol"), (self.vol_mon, "mon_vol")):
            box.changed.connect(lambda v, key=key: self.set_option(key, v))
        return f

    def _fit_mixer(self, tight: bool):
        """The levels strip's responsive step. Only when the strip itself is too wide
        (not for whatever else is): one group whole, the other two as icons; still too
        wide, that group's words go too."""
        stages = (lambda: self._mixer_one_at_a_time(True),
                  lambda: self.chk_mic.setText(""),   # its tooltip says what it is
                  lambda: (self.vol_mic.spin.hide(), self.vol_mon.spin.hide()))
        self._mixer_one_at_a_time(False)
        self.chk_mic.setText(self._mic_text)
        self.vol_mic.spin.show()
        self.vol_mon.spin.show()
        self._touch_mixer()
        self._mixer_tight = tight
        if not tight:
            return
        side = self._body_lay.contentsMargins()
        room = self._pages.width() - self.rail.minimumWidth() - side.left() - side.right()
        for stage in stages:
            if self.mixer.minimumSizeHint().width() <= room:
                break
            stage()
            self._touch_mixer()

    def _touch_mixer(self):
        responsive.touch(*self._deck_tabs, self.chk_mic, self.vol_mic.spin,
                         self.vol_mon.spin, self.out_meter)

    def _mixer_one_at_a_time(self, on: bool):
        """Too narrow for the three groups: show one whole, the others as icons."""
        self._mixer_one = on
        for i, (deck, tab, title) in enumerate(zip(
                (g[-1] for g in self._decks), self._deck_tabs, self._deck_titles)):
            whole = not on or i == self._mixer_focus
            deck.setVisible(whole)
            tab.setVisible(not whole)
            title.setVisible(not on)   # the icon beside it (and its tooltip) says which
            # the shown group takes the room (what others hear, with all three)
            self._mixer_layout.setStretchFactor(deck, int(i == (self._mixer_focus if on else 1)))

    def _focus_deck(self, i: int):
        """An icon in the narrow levels strip clicked: its group is the one shown."""
        self._mixer_focus = i
        if self._deck_tabs[i].hasFocus():   # it just hid: keep the keyboard in the strip
            self._deck_tabs[i - 1 if i else 1].setFocus()
        self._fit.reset()   # the groups aren't the same width: fit again
        self._refit()

    def _fit_dl_bar(self):
        """A page whose cards stop short of the edges (Setup: room for its scroll bar,
        and centred past the width cap on a wide window) names that column `dl_column`:
        the download bar then takes the cards' own left and right edges."""
        col = getattr(self.tabs.currentWidget(), "dl_column", None)
        left = right = 0
        if col is not None and col.isVisible():
            x = col.mapTo(self._tabs_box, QPoint(0, 0)).x()
            left, right = max(0, x), max(0, self._tabs_box.width() - x - col.width())
        m = self._dl_lay.contentsMargins()
        if (m.left(), m.right()) != (left, right):
            self._dl_lay.setContentsMargins(left, 0, right, 0)

    def _refit_dl_bar(self):
        """The download bar came, went or needs another height (rows added, opened):
        fit the window again for it, once the change is laid out."""
        if getattr(self, "_dl_refit_due", False) or not hasattr(self, "_dl_steps"):
            return
        self._dl_refit_due = True

        def run():
            self._dl_refit_due = False
            self._fit.retry(self._dl_steps)   # open again if it fits now
            self._refit()
        QTimer.singleShot(0, self, run)   # with the window: not after it's gone

    def _dl_bar_gap(self, shown: bool):
        """Under the download bar: its own 8 px (so a page's scroll bar doesn't touch it)
        and none from the Sounds page, whose first row then sits 8 px down like the rest."""
        self._tabs_lay.setSpacing(8 if shown else 0)
        self._sounds_lay.setContentsMargins(0, 0 if shown else 8, 0, 0)

    def _build_sounds_page(self) -> QWidget:
        c = self.cfg
        page = QWidget()
        left = QVBoxLayout(page)
        left.setContentsMargins(0, 8, 0, 0)
        self._sounds_lay = left
        left.setSpacing(8)
        # one framed surface for the toolbar, every control the same height
        self.sounds_toolbar = QFrame()
        self.sounds_toolbar.setObjectName("soundstoolbar")
        tb = QHBoxLayout(self.sounds_toolbar)
        tb.setContentsMargins(8, 6, 8, 6)
        tb.setSpacing(6)
        # every way in under one button: a stray click opens a menu, not a file picker
        add = self.btn_add = QPushButton(_("Add"))
        # flat like the rest of the toolbar; the accent colour marks it as the main one
        add.setObjectName("soundadd")
        add.setToolTip(_("Add sounds: files, a folder, a recording, a link or a free pack "
                         "(or drag files onto the window)"))
        icons.set_icon(add, "music", "accent", size=18)
        am = self._add_menu = DropdownMenu(add)
        icons.set_icon(am.addAction(_("Sound files"), self.add_dialog), "music")
        icons.set_icon(am.addAction(_("A whole folder"), self.add_folder_dialog), "folder")
        icons.set_icon(am.addAction(_("Record"), self.record_dialog), "mic")
        icons.set_icon(am.addAction(_("From a link"), self.add_from_link), "link")
        icons.set_icon(am.addAction(_("Free sound packs"), self.show_packs), "download")
        add.setMenu(am)
        add.setProperty("toolbarMenu", True)
        self.search = QLineEdit()
        self.search.setObjectName("soundssearch")
        # short, so it isn't cut to "Search sounds… …" at normal widths; the tooltip
        # has the rest
        self.search.setPlaceholderText(_("Search sounds or paste a link"))
        self._search_tip = _("Type to filter your sounds; Enter searches the web (YouTube, "
                             "TikTok, Myinstants…). Or paste a link (YouTube, SoundCloud, "
                             "TikTok, most media sites) to see it, then play or add it")
        self.search.setToolTip(self._search_tip)
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(SEARCH_MIN_W)   # until the window gets narrow (_init_fit)
        self.search.setMaximumWidth(SEARCH_MAX_W)
        # typing regrids only when the pads shown change (35 ms a key with 600 pads),
        # and only once it pauses (_on_search_text); text set by the app filters at once
        self._search_wait = QTimer(self, singleShot=True, interval=SEARCH_WAIT_MS)
        self._search_wait.timeout.connect(
            lambda: self.apply_filter(self.search.text(), lazy=True))
        self._search_typed = None
        self.search.textEdited.connect(self._on_search_edited)
        self.search.textChanged.connect(self._on_search_text)
        self.search.returnPressed.connect(self.on_search_enter)
        icons.set_icon(self.search.addAction(QIcon(), QLineEdit.ActionPosition.LeadingPosition),
                       "search",
                       "muted")
        # the web search: Enter does it; this button shows the site it goes to and picks
        # another from its menu
        self.btn_yt = QPushButton()
        self.btn_yt.setAccessibleName(_("Search"))
        self.btn_yt.setToolTip(_("Search YouTube, SoundCloud, TikTok sounds, Myinstants… for "
                                 "what's typed (or press Enter), play or add the audio"))
        icons.set_icon(self.btn_yt, "youtube", size=18)
        # which site Enter searches: the button shows it, its menu picks another
        self._site_menu = DropdownMenu(self.btn_yt)
        self.btn_yt.setMenu(self._site_menu)
        self.btn_yt.setProperty("toolbarMenu", True)
        more = self.btn_more = QPushButton(_("Library"))
        more.setToolTip(_("Export your sounds and settings to a file, or import a backup or "
                          "sound pack"))
        icons.set_icon(more, "archive", size=18)
        mm = DropdownMenu(more)
        icons.set_icon(mm.addAction(_("Import a backup or sound pack"), self.import_dialog),
                       "folder")
        icons.set_icon(mm.addAction(_("Free sound packs"), self.show_packs), "download")
        om = mm.addMenu(_("Import from another soundboard"))
        icons.set_icon(om.menuAction(), "copy")
        for src in otherboards.sources():
            icons.set_icon(om.addAction(f"{src.name}…", lambda src=src: self.import_other(src)),
                           "sounds")
        pm = self._packs_menu = mm.addMenu(_("My sound packs"))
        icons.set_icon(pm.menuAction(), "sounds")
        pm.aboutToShow.connect(lambda: self._fill_packs_menu(pm))
        mm.addSeparator()
        icons.set_icon(mm.addAction(_("Export everything (sounds + settings)"),
                                    self.export_board), "download")
        self._act_export_cat = mm.addAction(_("Export this category"), self.export_category)
        icons.set_icon(self._act_export_cat, "download")
        mm.addSeparator()
        icons.set_icon(mm.addAction(_("Recently deleted sounds"), self.show_deleted), "trash")
        icons.set_icon(mm.addAction(_("Open the sounds folder"), self.open_sounds_folder),
                       "folder")   # here too, for when the window's too narrow for its button
        mm.aboutToShow.connect(lambda: (
            self._act_export_cat.setEnabled(bool(self.cfg.category)),
            pm.menuAction().setVisible(bool(backup.packs()))))
        more.setMenu(mm)
        more.setProperty("toolbarMenu", True)
        self.btn_bin = QPushButton()
        self.btn_bin.setToolTip(_("Sounds you removed: bring them back, exactly as they were"))
        icons.set_icon(self.btn_bin, "trash")
        self.btn_bin.clicked.connect(self.show_deleted)
        self.btn_folder = QPushButton(_("Sounds folder"))
        self.btn_folder.setToolTip(_("Open the folder your sounds are kept in. Sound files you "
                                     "drag into it join the board by themselves."))
        icons.set_icon(self.btn_folder, "folder", size=18)
        self.btn_folder.clicked.connect(self.open_sounds_folder)
        self._label_bin()
        # the most-used app-wide hotkeys in one click; the full list is in Settings
        self.btn_keys = QPushButton()
        self.btn_keys.setToolTip(_("Quick hotkeys: set the ones people use most, or open every "
                                   "hotkey in Settings"))
        icons.set_icon(self.btn_keys, "keyboard", size=18)
        km = DropdownMenu(self.btn_keys)
        km.aboutToShow.connect(lambda: self._fill_quick_hotkeys(km))
        self.btn_keys.setMenu(km)
        self.btn_keys.setProperty("toolbarMenu", True)
        km.setTitle(_("Quick hotkeys"))
        mm.addSeparator()
        mm.addMenu(km)
        for utility in (self.btn_folder, self.btn_keys, self.btn_bin):
            utility.setParent(page)
            utility.hide()
        # make things, find things, then the library's tools
        tb.addWidget(add)
        tb.addWidget(vsep())
        tb.addWidget(self.search, 1)
        tb.addWidget(self.btn_yt)
        tb.addStretch(0)   # past SEARCH_MAX_W: the room goes here, the library tools stay right
        tb.addWidget(vsep())
        tb.addWidget(more)
        tb.addWidget(vsep())
        # the pads' order (as dragged, A-Z, newest, most played) and cards or a list
        self.btn_view = QPushButton()
        self.btn_view.setAccessibleName(_("Order and view"))
        vm = DropdownMenu(self.btn_view)
        vm.setToolTipsVisible(True)
        vm.aboutToShow.connect(lambda: self._fill_view_menu(vm))
        self.btn_view.setMenu(vm)
        self.btn_view.setProperty("toolbarMenu", True)
        self._label_view()
        tb.addWidget(self.btn_view)
        # Creation actions have their own surfaces; library tools stay quiet.
        for b in (self.btn_folder, more, self.btn_bin, self.btn_keys,
                  self.btn_yt, self.btn_view):
            b.setProperty("quiet", True)
        size = QSlider(Qt.Orientation.Horizontal)
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
        size_lbl = QLabel(_("Pad size"))
        size_lbl.setObjectName("muted")
        tb.addWidget(size_lbl)
        tb.addWidget(size)
        self._pad_size = (size_lbl, size)
        for b in (add, self.btn_yt, self.btn_folder, more, self.btn_keys,
                  self.btn_bin, self.btn_view, self.search):
            b.setFixedHeight(CONTROL_H)
        left.addWidget(self.sounds_toolbar)
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
        self.grid.files_dropped.connect(self.import_files, Qt.ConnectionType.QueuedConnection)
        self.grid.image_dropped.connect(self.set_picture, Qt.ConnectionType.QueuedConnection)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.grid)
        scroll.verticalScrollBar().valueChanged.connect(self._scroll_background_board)
        self._pad_scroll = scroll
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        # the pads fit the width
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left.addWidget(scroll, 1)
        self._pads_home = (left, left.indexOf(scroll))   # the mini player borrows it
        self.ytresults.closed.connect(scroll.show)   # the results take the pads' place
        self.ytresults.closed.connect(self._cat_row.show)   # ...and the categories' row
        self.ytresults.closed.connect(self._results_closed)
        self.ytresults.fill_site_menu(self._site_menu)
        self.ytresults.source_changed.connect(self._on_site_picked)
        self._pads_scroll = scroll
        # ---- "3 selected · Colour · Volume · Delete": Ctrl / Shift+click picks pads
        self.selection = PadSelection(self, scroll)
        left.addWidget(self.selection.bar)
        # Ctrl+V anywhere on the page (a text box keeps its own): a copied clip from
        # the Apps tab's editor becomes a sound; a copied picture goes on the selected
        # pad (or the picked ones)
        # a click on the page's bare parts lands here
        page.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        paste = QShortcut(QKeySequence.StandardKey.Paste, page)
        paste.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        paste.activated.connect(self.paste_picture)
        # Ctrl+F anywhere on the page: into the search box
        find = QShortcut(QKeySequence.StandardKey.Find, page)
        find.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
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


        f, th = bar()
        self.btn_pp = PlayButton()
        self.btn_pp.setObjectName("transport_play")
        self.btn_pp.setToolTip(_("Play / pause"))
        self.btn_pp.clicked.connect(self.toggle_play_pause)
        self._pp_icon = None
        self.btn_st = QPushButton()
        self.btn_st.setObjectName("transport_stop")
        self.btn_st.setToolTip(_("Stop"))
        self.btn_st.clicked.connect(self.stop_current)
        icons.set_icon(self.btn_st, "stop", size=16)
        for b in (self.btn_pp, self.btn_st):
            b.setFixedSize(CONTROL_H, CONTROL_H)
        self.np_name = QLabel(_("Pick a sound"))
        self.np_name.setToolTip(_("Select a sound pad to use these playback controls."))
        self.np_name.setTextFormat(Qt.TextFormat.PlainText)   # sound names are user / web text
        # the row's height, set by its buttons; its width follows the text inside
        # NameAndSeek, which never asks the page for a new layout (the name changes
        # with every pad press, and a relayout repainted every pad on the board)
        self.np_name.setFixedHeight(CONTROL_H)
        self.np_name.setStyleSheet("font-weight:600;")
        self.seek = SeekSlider(Qt.Orientation.Horizontal)
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
        self.np_time.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.np_time.setObjectName("muted")
        self.np_time.hide()   # until there is a time to show (_set_np_time)
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
        vol_icon = QLabel(_("Sounds"))
        vol_icon.setObjectName("decktitle")
        th.addWidget(vol_icon)
        self.vol_sound = VolumeControl(c.sound_vol, tip=_("How loud your sounds are, type up to "
                                                          "1000% in the box"))
        self.vol_sound.changed.connect(lambda v: self.set_option("sound_vol", v))
        th.addWidget(self.vol_sound)
        self.chk_monitor = QCheckBox(_("Hear it myself"))
        self.chk_monitor.setChecked(c.monitor_sounds)
        self.chk_monitor.toggled.connect(lambda b: self.set_option("monitor_sounds", b))
        th.addWidget(self.chk_monitor)
        self._transport_vol = (sep, vol_icon, self.vol_sound)
        # under the tabs, not in this page: the other tabs show it too while a sound
        # plays, so it can be paused or stopped from anywhere (_show_transport)
        self.transport = f
        self._set_pp_icon("play")
        return page

    def _update_chips(self, playing):
        """The row above the pads: every sound playing, each with its own ■, and the
        queue, each with its own ✕. A web search / link's Play once counts too: it
        isn't a pad, but it plays over them and needs its own ■. One rule, whatever
        played before: a sound has a chip while it plays. (The row used to show only
        for two or more, so stopping one of two hid the other's chip too and it looked
        like ■ had stopped both.)"""
        ids = tuple(s for s in self.pads if s in playing)
        if LINK_ID in playing:
            ids += (LINK_ID,)
        queue = tuple(self._queue)
        if (ids, queue) != self._chip_ids:
            self._chip_ids = (ids, queue)
            while self._chips_hl.count():
                item = self._chips_hl.takeAt(0)
                w = item.widget() if item else None
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
            if ids:
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
                        m.name if m else sid, Qt.TextElideMode.ElideRight, 150).replace("&", "&&"))
                    name.setObjectName("chipname")
                    name.setToolTip(_("Show this sound in the player (keeps playing)"))
                    name.clicked.connect(lambda __=False, s=sid: self.select(s))
                    stop = QPushButton()
                    stop.setObjectName("chipstop")
                    stop.setToolTip(_("Stop this sound"))
                    icons.set_icon(stop, "stop", "danger_text", size=12)
                    stop.setFixedSize(24, 24)
                    stop.clicked.connect(lambda __=False, s=sid: self._stop_one(s))
                    ch.addWidget(name)
                    ch.addWidget(stop)
                    self._chips_hl.addWidget(chip)
                    self._chips[sid] = chip
            # at least a line high, taller when the chips wrap (the Flow's height for
            # its width); a row that shrank and grew back with every overlapping
            # sound resized and repainted the whole board under it
            self.playing_row.setMinimumHeight(CHIPS_ROW_H)
            self.playing_row.setVisible(bool(ids) or bool(queue))
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
        name = QPushButton(chip.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, 150)
                           .replace("&", "&&"))   # "R&B", not "RB" with a shortcut
        name.setObjectName("chipname")
        name.setToolTip(tip)
        name.clicked.connect(on_click)
        x = QPushButton()
        x.setObjectName("chipstop")
        x.setToolTip(x_tip)
        icons.close_button(x, 24)
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
                    icons.set_icon(b, name, "on_accent", size=16)

    def _build_setup_page(self) -> WidthScroll:
        """One-time setup and the rarely-touched stuff: where the audio goes,
        devices, the recorded test, EQ, levelling."""
        c = self.cfg
        page = WidthScroll(lambda: self._pages.width() - SHUT_W - 2 * BODY_SIDE,
                           lambda: self._setup_one_col())
        page.setWidgetResizable(True)
        page.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        page.dl_column = body   # the download bar lines up with these cards
        _Moved(body, self._fit_dl_bar)
        inner = capped(body, margins=(0, 12, 12, 12))   # not a 900 px wide card at full screen; the
        # cards' left edge lines up with the download bar and the other tabs
        sections = QVBoxLayout(body)
        sections.setContentsMargins(0, 0, 0, 0)
        sections.setSpacing(16)
        cols = self._setup_cols = QHBoxLayout()
        sections.addLayout(cols)
        sections.addStretch(1)
        cols.setContentsMargins(0, 0, 0, 0)
        cols.setSpacing(16)
        lcol, rcol = self._setup_lr = QVBoxLayout(), QVBoxLayout()
        for col in (lcol, rcol):
            col.setSpacing(16)
            cols.addLayout(col, 1)
        page.setWidget(inner)

        # ---- how it works + the one thing to set in Discord
        # straight into the mic: what to do if a voice app chops the sounds up sits
        # behind an ⓘ (DESIGN section 4), not as a paragraph under "Nothing to set"
        self.btn_mictips = info_button(_("Sounds chopped up?"))
        self.btn_mictips.clicked.connect(self._show_mic_tips)
        self.btn_mictips.hide()
        # the heading on one centre line: a mic, the title, its ⓘ, then the status pill
        # at the end (DESIGN section 5)
        howcard, cv = card(roomy=True)
        head = QHBoxLayout()
        head.setContentsMargins(0, 8, 0, 0)   # (card() leaves room for a title's padding)
        head.setSpacing(8)
        center = Qt.AlignmentFlag.AlignVCenter
        head.addWidget(icon_label("mic", color="text"), 0, center)
        self.how_title = QLabel(_("Your virtual mic"))   # renamed for the other routes
        self.how_title.setObjectName("section")
        self.how_title.setProperty("head", True)   # (no padding above: centred with the rest)
        head.addWidget(self.how_title, 0, center)
        head.addWidget(self.btn_mictips, 0, center)
        head.addStretch(1)
        self.mic_pill = QLabel()
        self.mic_pill.setObjectName("pill")
        self.mic_pill.hide()
        head.addWidget(self.mic_pill, 0, center)
        cv.addLayout(head)
        flow = self.mic_flow = QFrame()
        flow.setObjectName("micflow")
        fv = QVBoxLayout(flow)
        fv.setContentsMargins(14, 14, 14, 14)
        fv.setSpacing(10)
        self.flow_mic = QLabel()
        self.flow_snd = QLabel(_("Your sounds, radio and voice effects"))
        arrow = QLabel(_("↓   the app mixes them together"))
        arrow.setObjectName("hint")
        self.flow_out = QLabel()
        for ic, w in (("mic", self.flow_mic), ("volume", self.flow_snd), ("", arrow),
                      ("live", self.flow_out)):   # mic or cable alike
            w.setTextFormat(Qt.TextFormat.RichText)
            w.setWordWrap(True)
            row = QHBoxLayout()
            row.setSpacing(8)
            if ic:
                row.addWidget(icon_label(ic))
            else:
                row.addSpacing(26)
            row.addWidget(w, 1)
            if w is self.flow_out:
                output = QFrame()
                output.setObjectName("micoutput")
                ov = QVBoxLayout(output)
                ov.setContentsMargins(12, 12, 12, 12)
                ov.addLayout(row)
                fv.addWidget(output)
            else:
                fv.addLayout(row)
        cv.addWidget(flow)
        # straight into the mic: one status box instead of the picture above (it works
        # by itself, and the mic helper puts it back when Windows takes it off): a big
        # icon, what's happening, the mic's name and its live level. The step below
        # only when it needs a click.
        box = self.mic_status = QFrame()
        box.setObjectName("micstatus")
        bh = QHBoxLayout(box)
        bh.setContentsMargins(12, 10, 12, 10)
        bh.setSpacing(10)
        self.mic_state_icon = QLabel()
        self.mic_state_icon.setFixedSize(20, 20)
        bh.addWidget(self.mic_state_icon, 0, Qt.AlignmentFlag.AlignTop)
        lines = QVBoxLayout()
        lines.setSpacing(8)
        bh.addLayout(lines, 1)
        # line 1: what's happening, the mic, its live level
        top = QHBoxLayout()
        top.setSpacing(10)
        self.mic_line = QLabel()
        self.mic_line.setObjectName("micline")
        top.addWidget(self.mic_line, 0, Qt.AlignmentFlag.AlignVCenter)
        self.mic_sub = ElidedLabel()
        self.mic_sub.setObjectName("hint")
        self.mic_sub.setMinimumWidth(40)
        top.addWidget(self.mic_sub, 0, Qt.AlignmentFlag.AlignVCenter)
        self.card_meter = Meter()
        self.card_meter.setFixedWidth(90)
        self.card_meter.setToolTip(_("Your mic"))
        top.addWidget(self.card_meter, 0, Qt.AlignmentFlag.AlignVCenter)   # by its name
        top.addStretch(1)
        lines.addLayout(top)
        # line 2, when there's something to say or do: why, then the buttons
        self.mic_reason = QLabel()
        self.mic_reason.setWordWrap(True)
        self.mic_reason.setTextFormat(Qt.TextFormat.RichText)
        self.mic_reason.hide()
        lines.addWidget(self.mic_reason)
        self.mic_ways = Flow(gap=8)
        lines.addLayout(self.mic_ways)
        box.hide()
        self._mic_icon = None
        self._ways_in = None   # which row the set-up buttons are in (_place_ways)
        cv.addWidget(box)
        cv.addWidget(box)
        self.helper_checked.connect(self._helper_known)
        self.step_lbl = QLabel()
        self.step_lbl.setWordWrap(True)
        self.step_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.step_lbl.setObjectName("micguide")
        cv.addWidget(self.step_lbl)
        # an old mic part: one amber banner with its one button, in the step's place
        self.mic_update_note = QFrame()
        self.mic_update_note.setObjectName("micupdatebar")
        nh = QHBoxLayout(self.mic_update_note)
        nh.setContentsMargins(14, 10, 10, 10)
        nh.setSpacing(12)
        self.mic_update_icon = icon_label("warn", color="warn_text")
        nh.addWidget(self.mic_update_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        self.mic_update_text = QLabel()
        self.mic_update_text.setTextFormat(Qt.TextFormat.RichText)
        self.mic_update_text.setWordWrap(True)
        nh.addWidget(self.mic_update_text, 1)
        self.btn_micupdate = QPushButton(_("Update now"))
        self.btn_micupdate.setObjectName("primary")
        from soundboard.ui.micupdate import _shield
        _shield(self.btn_micupdate)
        self.btn_micupdate.clicked.connect(self._accept_mic_update)
        nh.addWidget(self.btn_micupdate, 0, Qt.AlignmentFlag.AlignVCenter)
        self.mic_update_note.hide()
        cv.addWidget(self.mic_update_note)
        self.setup_show = SetupShow(height=96, left=True)   # Bun builds it, by the buttons
        self.setup_show.done.connect(self._update_flow)   # (the button's back, if needed)
        cv.addWidget(self.setup_show)
        self.btn_install = QPushButton(_("Install the free virtual cable"))
        self.btn_install.setObjectName("primary")
        self.btn_install.clicked.connect(
            lambda: self.attach_mic() if self.cfg.route == "mic" else self.install_cable())
        self._install_icon = None   # what set_icon last put on it (only set when it changes)
        self.btn_attach = QPushButton(_("Straight into my mic instead"))   # (tip: no cable)
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
        self._done_toast = None       # "done" / "updated": said once it works
        icons.set_icon(self.btn_install, "cable", "on_accent")
        ways.addWidget(self.btn_install)
        ways.addWidget(self.btn_usecable)   # (after the mic's own button: the second way)
        for b in (self.btn_usecable,):
            b.setProperty("quiet", True)   # the rarer ways: plain words, no fill
        # Connect your chat is hidden until there's a chat to connect: its guide is here
        # meanwhile (that card held nothing else, while nothing was set up or on Nobody)
        self.btn_guide = self._guide_button()
        self.btn_guide.hide()
        self.btn_guide.setProperty("quiet", True)
        ways.addWidget(self.btn_guide)
        cv.addLayout(ways)
        self._ways = ways
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
            _("<b>You don't need the virtual cable any more</b>, it was only the backup. Remove "
              "it, or keep it if another program uses it (Voicemeeter, another soundboard)."))
        self.rmcable_note.setTextFormat(Qt.TextFormat.RichText)
        self.rmcable_note.hide()
        cv.addWidget(self.rmcable_note)
        self.btn_rmcable.setProperty("quiet", True)
        ways.addWidget(self.btn_rmcable)   # beside the other ways, when there's one
        self.btn_rescan = QPushButton(_("I've installed it: check again"))
        self.btn_rescan.clicked.connect(lambda: self.rescan_with_feedback(self.btn_rescan))
        icons.set_icon(self.btn_rescan, "reload")
        ways.addWidget(self.btn_rescan)   # with the other ways, not a row of its own
        helpcard = FoldCard("speech", _("Connect your chat"))
        helpcard.set_summary(_("Discord, games, Zoom and Teams"))
        helpcard.head.clicked.connect(lambda on: on and usage.used("setup-opened-chat"))
        hv = helpcard.body
        hv.addWidget(hint_label(_("Choose your app for the recommended microphone settings.")))
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
        chat.addWidget(self._guide_button())
        hv.addLayout(chat)
        self.helpcard = helpcard


        # ---- devices
        devcard = self.dev_fold = FoldCard("headphones", _("Devices"))
        devcard.head.clicked.connect(lambda on: on and usage.used("setup-opened-devices"))
        av = devcard.body
        av.addWidget(hint_label(_("Already set up for you, only change these if "
                                  "something's wrong.")))
        self._cablefix_shown = False
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
            # a short floor, so a long device name ("Headphones (2- Arctis Nova Pro
            # Wireless Game)") can't give the Setup tab a sideways scroll bar; the list
            # opens wide enough for whole names
            cb.setMinimumWidth(120)
            # one column: the three boxes share the widest one's width (up to the cap)
            # instead of each fitting its own names, which left My mic's edge short
            cb.setProperty("snug", False)   # (wheelguard.snug_combo: sized here)
            cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
            cb.setMaximumWidth(AppStyle.COMBO_CAP)
        grid.setColumnStretch(3, 1)   # the room past the boxes, not the boxes' column
        av.addLayout(grid)
        self.setup_connection = QLabel()
        self.setup_connection.setObjectName("hint")
        self.setup_connection.setWordWrap(True)
        av.addWidget(self.setup_connection)
        self.cb_main.setParent(devcard)   # never a window of its own
        self.cb_main.hide()
        # more places at once (streamers): a row per extra device, + and − (alsosend)
        self.also_views = []
        self.also_rows = alsosend.build(self, grid, 3, icons_col=True)
        self.setup_hint = hint_label("")
        self.setup_hint.setTextFormat(Qt.TextFormat.RichText)
        av.addWidget(self.setup_hint)
        self.btn_cablefix = QPushButton(_("Fix the cable: both ends to 48 kHz"))
        self.btn_cablefix.setToolTip(_("Sets the cable's playback and recording side to 48 kHz, "
                                       "so it passes your sound through without converting it"))
        self.btn_cablefix.clicked.connect(lambda: busy.run_busy(
            self.btn_cablefix, _("Switching the cable to 48 kHz…"), self.fix_cable_format,
            lambda ok: _("✓ Done") if ok and not self.cable_bad else _("Couldn't, see below")))
        self.btn_cablefix.hide()
        av.addWidget(self.btn_cablefix, 0, Qt.AlignmentFlag.AlignLeft)
        no_wheel(self.cb_main, self.cb_mon, self.cb_mic, self.cb_route)
        for cb, attr in ((self.cb_main, "main_device"), (self.cb_mon, "mon_device"),
                         (self.cb_mic, "mic_device"), (self.cb_route, "route")):
            cb.activated.connect(lambda _i, cb=cb, attr=attr: self.on_device(cb, attr))
        ref = QPushButton(_("Re-scan devices"))
        icons.set_icon(ref, "reload")
        ref.clicked.connect(lambda: self.rescan_with_feedback(ref))
        av.addWidget(ref, 0, Qt.AlignmentFlag.AlignLeft)

        # ---- who's listening: shape the sounds for the voice chat on the other end
        from soundboard.ui.destpanel import DestPanel
        self.dest_panel = DestPanel(self)
        destcard, dv = card(_("Who's listening"), _("Where people hear you: a game, a voice "
                                                    "chat app, or a stream. Your sounds are "
                                                    "shaped to come through clearly."),
                            roomy=True, beside=self.dest_panel.help_btn)   # What do these do?
        dv.addWidget(self.dest_panel)

        # ---- sound shaping
        eqcard = self.sound_fold = FoldCard("sliders", _("Equalizer and volume"))
        eqcard.head.clicked.connect(lambda on: on and usage.used("setup-opened-sound"))
        ev = eqcard.body
        self.eq = EqPanel(c.eq_enabled, c.eq_target, c.eq_preset, c.eq_gains, fold=True)
        self.eq.changed.connect(self.on_eq)
        ev.addWidget(self.eq)
        self.chk_level = QCheckBox(_("Level volumes (all sounds equally loud)"))
        self.chk_level.setChecked(c.level_volumes)
        self.chk_level.toggled.connect(self.on_level_toggle)
        ev.addWidget(self.chk_level)
        # side by side: your mic and the rarely-touched parts under it (each shut to one
        # line with a summary) on the left, who's listening on the right. One column
        # when narrow: what you check every day first, the shut ones last
        self._setup_wide = ((howcard, devcard, helpcard, eqcard), (destcard,))
        self._setup_narrow = (howcard, destcard, devcard, helpcard, eqcard)
        self._setup_stacked = None
        self._stack_setup(False)
        self.on_eq(*self.eq.state())   # push the saved EQ into the engine
        self._fold_summaries()
        destination.apply(self.cfg, self.engine)   # ...and the destination mode (Who's listening)
        from soundboard.ui.destpanel import apply_send
        apply_send(self.cfg, self.engine)          # ...and mono / ducking
        return page

    def _guide_button(self) -> QPushButton:
        guide = QPushButton(_("Step-by-step guide"))
        guide.setToolTip(_("Walks you through mic, headphones, where your sounds go (your mic, "
                           "the cable, another device or nowhere) and Discord"))
        icons.set_icon(guide, "check")
        guide.clicked.connect(lambda: (usage.used("setup-guide-opened"), self.run_setup()))
        return guide

    def _stack_setup(self, compact: bool):
        """Setup's cards in two columns, or in one column in setup order."""
        if compact == self._setup_stacked:
            return
        self._setup_stacked = compact
        self._setup_cols.setDirection(QBoxLayout.Direction.TopToBottom if compact
                                      else QBoxLayout.Direction.LeftToRight)
        for col, cards in zip(self._setup_lr,
                              (self._setup_narrow, ()) if compact else self._setup_wide):
            while col.count():
                take_out(col)   # the cards stay on the page, only their places change
            for w in cards:
                col.addWidget(w)
            col.addStretch(1)

    def _setup_one_col(self) -> int:
        """The width Setup needs in one column: its widest card, and the page's margins."""
        widest = max(QWidgetItem(w).minimumSize().width() for w in self._setup_narrow)
        inner = self.setup_page.widget()
        lay = inner.layout() if inner is not None else None
        if lay is None:   # (built in _build_setup_page: always there)
            return widest
        m = lay.contentsMargins()
        return widest + m.left() + m.right()

    def _setup_need(self) -> int:
        """The width Setup's two columns need side by side, measured the same way
        whether they're stacked or not (stacked, the right column is empty)."""
        return sum(max(QWidgetItem(w).minimumSize().width() for w in cards)
                   for cards in self._setup_wide) + self._setup_cols.spacing()

    def on_eq(self, gains, enabled, target, preset):
        c = self.cfg
        c.eq_enabled, c.eq_target, c.eq_preset, c.eq_gains = enabled, target, preset, list(gains)
        self.engine.eq_target = target
        self.engine.eq_gains = list(gains) if enabled else None
        self._save_later()
        if hasattr(self, "sound_fold"):
            self._fold_summaries()

    def _fold_summaries(self):
        """The one-line summaries on Setup's shut cards: the devices in use, and
        whether the EQ and levelling are on."""
        self.dev_fold.set_summary(" · ".join(
            t for t in (self.cb_mon.currentText(), self.cb_mic.currentText()) if t))
        self.sound_fold.set_summary(" · ".join((
            _("EQ on") if self.cfg.eq_enabled else _("EQ off"),
            _("Volumes levelled") if self.cfg.level_volumes else _("Volumes as they are"))))
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
            self.say(_("<span style='color:{status}'>Couldn't re-scan devices, "
                       "restart the app to pick up new ones.</span>",
                       status=theme.status('warn')), "warn")
            return _("Couldn't re-scan")
        if self.cfg.route == "cable" and not any(is_virtual_cable(d["name"]) for d in outs):
            self.say(_("<span style='color:{status}'>Still no virtual cable. If you "
                       "just installed it, restart your PC, Windows often only shows "
                       "it after a restart.</span>", status=theme.status('warn')), "warn")
            return _("No cable found yet")
        n = len({d["name"] for d in outs} | {d["name"] for d in eng.list_devices("input")})
        return ngettext("✓ Found {n} device", "✓ Found {n} devices", n)

    RESCAN_SHOWN_S = 3.0   # a Re-scan button shows what it found this long

    def rescan_with_feedback(self, btn, after=None):
        """A Re-scan button: "Scanning…" while it runs (on the device thread: the
        window stays usable even if a driver is stuck), then what it found."""
        if busy.is_busy(btn) or time.monotonic() < (btn.property("scanned_until") or 0):
            # already scanning, or still showing what it found: a re-scan closes and
            # reopens every device, so spam clicks restarted them all over and over
            return
        release = busy.hold(btn, _("Scanning…"))

        def done(msg):
            if after:
                try:
                    after()
                except RuntimeError:   # its dialog was closed while it scanned
                    pass
            try:
                btn.setProperty("scanned_until", time.monotonic() + self.RESCAN_SHOWN_S)
            except RuntimeError:   # (its dialog was closed)
                pass
            release(msg, int(self.RESCAN_SHOWN_S * 1000))
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
        self._say_back_on_mic()

    def _say_back_on_mic(self):
        """After a restart or an audio buffering change: tell them the board is on the
        mic again (the only other sign is the status strip)."""
        if self.cfg.route == "mic" and directmic.works(directmic.status()):
            self.toast(_("Your sounds are back on your mic."), "ok")

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
        if "--restart-after" in sys.argv:   # started again by the app (Settings > Reset)
            self._say_back_on_mic()

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
        failing: list[tuple[str, str]] = [
            (k, name) for k in ("main", "mon", "mic", "obs")
            if (name := e.names.get(k)) and getattr(e, f"{k}_stream") is None
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
        busy.emit(self.default_found, name)

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
        self.toast(_("You hear your sounds on {name} now: it's Windows' default output.",
                     name=html.escape(name)), "ok")

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
            self.toast(msg, kind)
        return ok

    def show_chat_guide(self, which: str):
        from soundboard.ui.chatguide import show_guide
        show_guide(which, self, self, self.virtual_mic or "CABLE Output")

    def _fill_combo(self, cb, names, current):
        cb.blockSignals(True)
        cb.clear()
        cb.addItem(_("(none)"), None)
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
                self.say(
                    _("<span style='color:{status}'>That's a Bluetooth headset's phone-call "
                      "mic: while it's open, Windows switches the headset to call quality, so "
                      "everything you hear sounds muffled. A wired mic, or the headset's own "
                      "USB dongle, sounds much better.</span>", status=theme.status('warn')),
                    "warn", 10000)
            self._prepare_all()
        self._device_job(plan, opened)

    def set_route(self, route: str, device: str | None = None, by_hand: bool = False,
                  attached: bool = False):
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
        # an older copy of the effect ('outdated') still works: picking the mic never
        # asks for admin for it (the update stays optional). `attached`: it was just
        # put on, and Windows may still be loading it; asking again would loop prompts.
        if route == "mic" and not attached and not directmic.works(directmic.status(c.mic_device)):
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
        self.how_title.setText(_("Your virtual mic") if route == "cable" else
                               _("Your mic") if route == "mic" else _("Where your sounds go"))

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
        present = eng.virtual_outputs()
        # the picked one only while it's plugged in: a cable saved in the settings but
        # not installed (any more) was opened anyway, and "device not found: CABLE
        # Input" stood where "not in your mic yet" should have been the only news
        if c.main_device and is_virtual_cable(c.main_device) and c.main_device in present:
            return c.main_device
        return next(iter(present), None)

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
        self._sync_mini_mic()
        self._update_status()

    def _update_status(self):
        e = self.engine
        c = self.cfg
        if hasattr(self, "dev_fold"):
            self._fold_summaries()   # (the devices may have changed)
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
        elif c.route == "cable":
            # the cable is picked, just not installed yet: the line above it and Your
            # virtual mic already say so ("Nothing picked" was wrong, and said it twice)
            self.setup_hint.setText("")
        else:
            self.setup_hint.setText(_("<span style='color:{status}'>Nothing picked: only you "
                                      "will hear sounds.</span>", status=theme.status('warn')))
        down = [n for n in self.engine.copies_down() if n in self._copy_names()]
        if down:
            devices = ", ".join(f"<b>{html.escape(n)}</b>" for n in down)
            self.setup_hint.setText(
                self.setup_hint.text()
                + _("<br><span style='color:{status}'>Can't open {devices} (under Also send to). "
                    "Plugged in? It's tried again by itself.</span>",
                    status=theme.status('warn'), devices=devices))
        self.setup_hint.setVisible(bool(self.setup_hint.text()))   # (no empty gap)
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
            self._say_audio(_("<span style='color:{status}'>Audio device problem: "
                              "{problems}</span>", status=theme.status('error'),
                              problems=html.escape(" · ".join(errs))), "error")
            return
        text = ""
        xr = sum(e.xruns.values())
        self._xruns_shown = xr
        if xr:
            tip = ("" if self.cfg.latency == "high" else
                   _(", try Settings → Audio → Audio buffering: Safer"))
            text += ("<br>" if text else "") + ngettext(
                "<span style='color:{colour}'>{n} audio drop-out since start{tip}</span>",
                "<span style='color:{colour}'>{n} audio drop-outs since start{tip}</span>",
                xr, colour=theme.status('warn'), tip=tip)
        self._say_audio(text, "warn")

    def _say_audio(self, text: str, kind: str):
        """The audio devices' state as one card: new text updates it, none takes it
        down (called on every status redraw, so the same text again does nothing)."""
        if text == self._audio_said:
            return
        self._audio_said = text
        if text:
            self.say(re.sub(r"<span style='color:[^']*'>(.*?)</span>", r"\1", text, flags=re.S),
                     kind, 10000, key="audio")
        else:
            self.unsay("audio")

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
        any_cable = not self._cable_gone and bool(eng.virtual_outputs())
        direct = directmic.status(self.cfg.mic_device) if route == "mic" else ""
        warn = theme.status("warn")
        # just set up: until Windows has it running, say so (not "Repair" straight away)
        settling = (route == "mic" and not self._attaching
                    and time.monotonic() < self._settle_until)
        if route == "mic" and self._attaching:
            state = "missing"
            out = _("Into your mic  <b>setting up…</b>")
            step = ("" if self._autofixing else
                    _("Click <b>Yes</b> when Windows asks for permission. Your PC's sound "
                      "drops out for a second while Windows reloads it.")
                    if michelper.will_ask() else
                    _("Your PC's sound drops out for a second while Windows reloads it."))
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
            out = _("Into your mic  <b style='color:{colour}'>✗ not running</b>", colour=bad)
            step = _("Another app may have your mic to itself (an <b>exclusive mode</b> "
                     "setting), or Windows hasn't loaded Onion Board on it. Repair it below, "
                     "or send through the virtual cable instead.")
        elif route == "mic" and e.main_stream is not None:
            state = "ok"
            name = html.escape(self.cfg.mic_device or _("your mic"))
            apps = e.direct_apps()
            out = (_("<b style='color:{colour}'>{name}</b>, your sounds are in it "
                     "<b style='color:{colour}'>✓</b>", colour=ok, name=name)
                   + ("  " + _("<b style='color:{colour}'>(live)</b>", colour=ok)
                      if apps else ""))
            step = _("<b>Nothing to set.</b> Discord and games keep your normal mic, and "
                     "your sounds are in it.").replace("</b>", "</b><br>", 1)
            if direct == "outdated":   # works, but an old part: the banner below says so
                out = _("<b style='color:{colour}'>{name}</b>, with an old version of "
                        "Onion Board's mic part", colour=warn, name=name)
                step = ""
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
            out = _("<b style='color:{colour}'>{name}</b>, sending "
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
            out = _("<b style='color:{colour}'>{device}</b>, your new mic "
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
                      "cable. It's what lets Discord and games hear your sounds. Without it, "
                      "only you can hear them. Easier: set <b>Send my sounds to</b> to "
                      "<b>My mic</b> (nothing to install). Voicemeeter, a mixer or OBS? Pick "
                      "that device there.", colour=warn))
        elif vm and e.main_stream is not None:
            state = "ok"
            out = _("<b style='color:{colour}'>{device}</b>, your new mic "
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
        # the app's own painted tick and cross, not the font's ✓ / ✗ (a brushy x)
        dpr = self.flow_out.devicePixelRatioF() or 1.0

        def marks(text: str) -> str:
            return (text.replace("✗", icons.inline("cross", bad, dpr=dpr))
                    .replace("✓", icons.inline("check", ok, dpr=dpr)))
        self.flow_mic.setText(marks(mic))
        self.flow_out.setText(marks(out))
        mic_route = route == "mic"
        button = None   # straight into the mic: the one button, when it needs a click
        self._place_ways(mic_route)
        if mic_route:
            reason, button = self._show_mic_status(direct, state, settling, step)
            self.mic_reason.setText(reason)
            self.mic_reason.setVisible(bool(reason))
            step = ""   # (said in the box)
        self.mic_flow.setVisible(not mic_route)
        self.mic_status.setVisible(mic_route)
        self.mic_pill.setVisible(mic_route)
        self.step_lbl.setText(step)
        self.btn_mictips.setVisible(route == "mic")
        update = route == "mic" and state == "ok" and direct == "outdated"
        self.step_lbl.setVisible(bool(step))   # (the update banner says it instead)
        if update:
            self.mic_update_text.setText(_(
                "<b style='color:{colour}'>Update your mic part</b><br>It's from an older "
                "version of Onion Board, so some games, calls and browsers may not hear "
                "your sounds. Windows asks once, and your sound drops out for a second.",
                colour=warn) if michelper.will_ask() else _(
                "<b style='color:{colour}'>Update your mic part</b><br>It's from an older "
                "version of Onion Board, so some games, calls and browsers may not hear "
                "your sounds. Your sound drops out for a second.", colour=warn))
        # setting up, or Windows still loading it: the button stays "Setting up…" and
        # takes no clicks (attach_mic holds it) until it works or the wait is over
        mic_busy = route == "mic" and (self._attaching or (settling and state != "ok"))
        if self._attach_release is not None and not mic_busy:
            release, self._attach_release = self._attach_release, None
            release()
        if self.setup_show.on and not mic_busy:
            self.setup_show.finish(route == "mic" and state == "ok")
        elif mic_busy and self._show_bun and not self.setup_show.on:
            # still setting up or starting, but Bun's show ended (he left while the tab
            # was hidden): back on, never a Repair button beside "starting…"
            self.setup_show.start()
        if not mic_busy:
            self._show_bun = False
        said = self._done_toast
        if said and not mic_busy:
            self._done_toast = None
            if route != "mic" or state != "ok":
                usage.used("mic-effect-no-load")   # set up, not working when the wait ran out
            if route == "mic" and state == "ok":   # (the wait ran out: no "Done")
                self.toast(_("Mic updated: games, calls and browsers hear your sounds.")
                           if said == "updated" else
                           _("Done: your sounds are back in your mic.") if said == "fixed" else
                           _("Done: Discord and games hear your sounds through your mic now."),
                           "ok")
        # an old part: the banner and its button, until Bun's show is over
        self.mic_update_note.setVisible(update and not self.setup_show.on)
        self.btn_install.setVisible((button is not None if mic_route else state == "missing")
                                    and not self.setup_show.on)   # Bun's show instead
        if not busy.is_busy(self.btn_install):
            self.btn_install.setText(button or _("Install the free virtual cable"))
            # Windows' shield when its prompt comes, like Windows' own buttons
            # white only while it's the filled main button: on the cable route it's a
            # plain one, and white vanished on Light's grey
            look = (("shield" if michelper.will_ask() else "mic") if mic_route else "cable",
                    "muted" if update else "on_accent" if route == "mic" else None)
            if look != self._install_icon:
                self._install_icon = look
                if look[0] == "shield":
                    from soundboard.ui.micupdate import _shield
                    _shield(self.btn_install)
                else:
                    icons.set_icon(self.btn_install, *look)
        # the mic is the main way: on the cable route the cable's button comes second
        self._set_primary(self.btn_install, route == "mic" and not update)   # (optional)
        self._set_primary(self.btn_attach, route == "cable")
        # the other ways sit beside the main button as plain words, every time
        self.btn_usecable.setVisible(route == "mic" and not mic_busy   # also when it works
                                     and not self._cable_gone)   # (back after a restart)
        spare = route == "mic" and state == "ok" and self._spare_cable()
        self.btn_rmcable.setVisible(spare)
        self.rmcable_note.hide()   # (its tooltip says it)
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
        # one rule: Connect your chat shows when there's a chat to connect; until then
        # its one button (the guide) sits in the mic card
        self.helpcard.setVisible(mic_side)
        self.btn_guide.setVisible(not mic_side)   # (Connect your chat has it then)
        cablefix = state == "ok" and bool(vm) and bool(self.cable_bad)
        self.btn_cablefix.setVisible(cablefix)
        if cablefix and not self._cablefix_shown:
            self.dev_fold.set_open(True)   # (the fix is in there: don't hide it)
        self._cablefix_shown = cablefix
        # "off" was picked on purpose: it's set up, as far as the rest of the app goes
        self.setup_state = "ok" if state == "off" else state
        # a device is picked to send to (not the headphones): failing is "Not working",
        # never "Not configured"
        picked = (self.cfg.main_device if route in ("cable", "device")
                  and self.cfg.main_device != self.cfg.mon_device else None)
        pills = []   # (short, whole): the open rail shows the short one
        for short in (True, False):
            if state == "off":
                pill = _("Only you") if short else _("Not sending to others (only you hear sounds)")
            elif state == "ok" and route == "mic":
                pill = (_("Connected") if short
                        else _("In your mic: Discord / games hear your sounds"))
            elif mic_busy and self._autofixing:
                pill = _("Fixing your mic…")
            elif mic_busy:
                pill = _("Setting up…") if short else _("Setting up your mic…")
            elif route == "mic" and state != "missing":
                pill = _("Not working") if short else _("Not reaching your mic, click to fix")
            elif route == "mic" and directmic.needs_repair(direct):
                pill = _("Repair needed") if short else _("One click needed: repair your mic")
            elif route == "mic":
                pill = (_("One click") if short
                        else _("One click: put your sounds straight into your mic"))
            elif state == "ok" and not vm:
                pill = _("Connected") if short else _("Sending to:  {dev}", dev=dev)
            elif state == "ok":
                pill = _("Connected") if short else _("Your mic in Discord / games:  {vm}", vm=vm)
            elif state == "missing":
                pill = (_("Setup needed") if short
                        else _("One-time setup needed, others can't hear you yet"))
            elif picked:   # set up, but it won't open (or the cable's mic end is gone)
                pill = (_("Not working") if short
                        else _("Can't send to {device}, click to fix", device=picked))
            elif route == "device":
                pill = (_("Not configured") if short
                        else _("Not sending: pick a device on the Setup tab"))
            else:   # (the Setup tab offers straight into the mic first)
                pill = (_("Not configured") if short
                        else _("Not configured: click to fix"))
            pills.append(pill)
        pill_short, pill = pills
        self.setup_connection.setText(pill)
        self.setup_connection.setVisible(route != "mic")   # (the mic card's pill says it)
        self.setup_connection.setProperty("tone", "ok" if state in ("ok", "off") else "warn")
        self.setup_connection.style().unpolish(self.setup_connection)
        self.setup_connection.style().polish(self.setup_connection)
        if hasattr(self, "mini_connection"):
            route_name = (_("My mic") if route == "mic" else
                          _("Only you") if state == "off" else _("Output"))
            self.mini_connection.setText(_("{route}: {status}",
                                          route=route_name, status=pill_short))
            self.mini_connection.setToolTip(pill)
            self.mini_connection.setAccessibleName(pill)
            self.mini_connection.setProperty("state", "ok" if state in ("ok", "off")
                                              else "warn")
            self.mini_connection.style().unpolish(self.mini_connection)
            self.mini_connection.style().polish(self.mini_connection)
        good = state in ("ok", "off")
        if good != self._pill_good:
            # all set: Live says it, so the pill only shows when something needs a click
            self._pill_good = good
            self._show_pill()
        if self._pill_long != pill:
            self._pill_long = pill
            sidebar.put(self.pill, pill_short, pill,
                        _("Where your sounds go, click for setup and testing"))
            self.pill.setIcon(icons.icon("headphones", "live_text") if state == "off" else
                              icons.icon("check", "live_text") if good else
                              icons.icon("warn", "warn_text"))
            self.pill.setProperty("state", "ok" if good else "warn")
            self.pill.style().unpolish(self.pill)
            self.pill.style().polish(self.pill)
            self.set_sending(self.btn_air.isChecked())   # its tooltip carries the pill's text

    def _place_ways(self, mic: bool):
        """The set-up buttons sit in the status box on the mic route (one place for
        the state and what to do about it), in their row under the picture otherwise."""
        if self._ways_in == mic:
            return
        self._ways_in = mic
        src, dst = (self._ways, self.mic_ways) if mic else (self.mic_ways, self._ways)
        # (check again too: it stays last, after them)
        for b in (self.btn_install, self.btn_usecable, self.btn_guide, self.btn_rmcable,
                  self.btn_rescan):
            src.removeWidget(b)
            dst.addWidget(b)
        self.mic_ways.invalidate()
        self._ways.invalidate()

    def _show_mic_status(self, direct: str, state: str, settling: bool,
                         step: str) -> tuple[str, str | None]:
        """Straight into the mic, on the Setup tab: fills the status box and the pill,
        and gives (the reason the user is needed or "", the one button's words or
        None). One rule: the card asks for a click only when the app can't go on
        without one (the first set-up, a No, no usable mic helper, a repair that
        failed); otherwise it's the status box, and Windows taking it off the mic is
        fixed by itself. `step`: what the old card said for this state."""
        e = self.engine
        ask = michelper.will_ask()
        if michelper.known() is None:
            self._check_helper()   # once, at start: the texts follow its answer
        name = self.cfg.mic_device or _("your mic")
        needed_no = _("You clicked <b>No</b>, so nothing changed. Try again and click "
                      "<b>Yes</b> when Windows asks.")

        def needed(reason):   # a No beats every other reason: it's what just happened
            return needed_no if self._declined else reason

        if directmic.works(direct):
            self._autofix_tried = False   # working: the next time it's off is fixed again
        # (tone, icon, headline, pill, reason, button)
        if self._attaching and self._autofixing:
            look = ("warn", "reload", _("Fixing your mic…"), _("Fixing…"),
                    _("Windows took Onion Board off your mic. It's going back on: your "
                      "sound drops out for a second."), None)
        elif self._attaching:
            look = ("warn", "reload", _("Setting up…"), _("Setting up…"), step, None)
        elif state == "missing" and settling:
            look = ("warn", "reload", _("Starting…"), _("Setting up…"), step, None)
        elif directmic.needs_repair(direct):
            known = michelper.known()
            if known and self._autofix_tried and not self._autofix_err:
                # fixed, and Windows took it off again: no loop of audio restarts
                self._autofix_err = _("Windows took it off again")
            if known and not self._autofix_err:
                QTimer.singleShot(0, self, lambda: self._auto_fix(direct))
                look = ("warn", "reload", _("Fixing your mic…"), _("Fixing…"),
                        _("Windows took Onion Board off your mic. It's going back on: "
                          "your sound drops out for a second."), None)
            elif known is None:
                look = ("", "reload", _("Checking your mic…"), _("Setting up…"), "", None)
            elif self._autofix_err:
                look = ("error", "warn", _("Windows took Onion Board off your mic"),
                        _("Repair needed"), needed(_(
                            "Onion Board couldn't fix it by itself: {error}. Click <b>Try "
                            "again</b>, and if Windows asks for permission, click <b>Yes</b>.",
                            error=html.escape(self._autofix_err.rstrip(".")))),
                        _("Try again"))
            else:
                look = ("error", "warn", _("Windows took Onion Board off your mic"),
                        _("Repair needed"), needed(_(
                            "A driver or Windows update does that. Click <b>Repair</b>, then "
                            "<b>Yes</b> when Windows asks.")), _("Repair (one click)"))
        elif not directmic.works(direct):
            look = ("warn", "mic",
                    _("Not in your mic yet") if direct == "missing" else _("On another mic"),
                    _("Not set up"), needed(
                        _("One click puts your sounds straight into your mic, so Discord and "
                          "games hear them. Windows asks once: click <b>Yes</b>.") if ask else
                        _("One click puts your sounds straight into your mic, so Discord and "
                          "games hear them.")), _("Put my sounds straight into my mic"))
        elif state == "ok" and self._mic_sends_nothing():
            # the mic itself sends nothing (stuck after an audio restart, or its own mute):
            # Repair restarts the audio and listens to it again
            if not self._silent_said:
                self._silent_said = True
                self.toast(_("Your mic sends no sound: see the Setup tab."), "warn")
            look = ("warn", "warn", _("Your mic sends no sound"), _("No sound"), needed(
                _("Discord and games hear nothing from your mic. If its mute is on, switch "
                  "it off. If not, click <b>Repair</b>, then <b>Yes</b> when Windows asks.")
                if ask else
                _("Discord and games hear nothing from your mic. If its mute is on, switch "
                  "it off. If not, click <b>Repair</b>: your sound drops out for a few "
                  "seconds.")), _("Repair (one click)"))
        elif state == "ok":
            look = ("ok", "check", _("Your sounds go into your mic"), _("Connected"), "", None)
        else:   # set up, but Windows isn't running it or it won't open: the step says why
            look = ("error", "warn",
                    _("Not running") if state == "unrouted" and e.main_stream is not None
                    else _("Can't reach it"), _("Not working"), needed(step),
                    _("Repair (one click)"))
        tone, icon, headline, pill, reason, button = look
        if state == "ok" and not self.cfg.mic_enabled:
            sub = _("{mic} · not sent, sounds only", mic=name)
        elif state == "ok" and e.mic_stream is None:
            sub = _("{mic} · off", mic=name)
        else:
            sub = name
        self.mic_sub.setToolTip(sub)
        self.mic_line.setText(headline)
        theme.set_tone(self.mic_line, tone)
        self.mic_sub.setText(sub)
        self.card_meter.setVisible(state == "ok" and e.mic_stream is not None)
        colour = {"ok": "ok_text", "warn": "warn_text", "error": "error_text"}.get(tone, "muted")
        if (icon, colour) != self._mic_icon:
            self._mic_icon = (icon, colour)
            icons.set_label_icon(self.mic_state_icon, icon, colour, size=20)
        self.mic_pill.setText(pill)
        theme.set_tone(self.mic_pill, tone)
        return reason or "", button

    def _auto_fix(self, direct: str):
        """Windows took the effect off the mic (a driver or Windows update): put it back
        through the mic helper, no click and no prompt (a toast says what's happening).
        Once per time it's found off: if it fails, the card asks for the click."""
        if (self._shut_down or self._attaching or self._autofix_err
                or self.cfg.route != "mic" or not michelper.known()):
            return
        if not directmic.needs_repair(directmic.status(self.cfg.mic_device)):
            return
        log.info("the mic effect was taken off the mic (%s): fixing it by itself", direct)
        usage.used("mic-effect-taken-off")
        self._autofix_tried = True
        self.attach_mic(auto=True)

    def _app_state(self, state):
        """Back in front after a while (behind a game for an hour, say): the mic
        helper's answer may be stale (another account removed or set it up), so check
        it again; the card's "click Yes" and the fix-by-itself follow the new answer."""
        if (state != Qt.ApplicationState.ApplicationActive or self._shut_down
                or self.cfg.route != "mic"):
            return
        ago = michelper.checked_ago()
        if ago is not None and ago > michelper.RECHECK_S:
            self._check_helper("window back")

    def _check_helper(self, via: str = "card"):
        """Is the mic helper usable (michelper.ready runs a process: on a thread)? The
        card redraws with the answer."""
        if self._helper_checking:
            return
        # (a check that failed leaves known() None, which every card redraw asks about:
        # one schtasks call a minute at most, not one per redraw)
        if (self._helper_failed
                and time.monotonic() - self._helper_check_at < HELPER_RETRY_S):
            return
        self._helper_checking, self._helper_check_at = True, time.monotonic()

        def work():
            self._helper_failed = not directmic._helper_check(via)
            if qt_valid(self):
                try:
                    self.helper_checked.emit()
                except (RuntimeError, TypeError):
                    pass
        threading.Thread(target=work, daemon=True, name="mic-helper-check").start()

    def _helper_known(self):
        self._helper_checking = False
        self._update_flow()

    def attach_mic(self, clean: bool = False, auto: bool = False):
        """Put the mic effect on the mic in use (Windows asks for admin once; with the
        mic helper set up, not at all), then send what others hear into it. The admin
        step waits, so it runs on a thread. `clean` (the update offer): the old part
        comes off completely first, then the new one goes on, under the same one prompt.
        `auto`: the app's own repair when Windows took it off (_mic_view), through the
        helper only: Windows' prompt never comes up for a click nobody made."""
        if self._attaching:
            return
        mic = self.cfg.mic_device
        if not mic:
            if not auto:
                self.toast(_("Pick your mic first (Setup tab → Devices)."), "warn")
            return
        self._attaching = True
        self._autofixing = auto
        self._declined = False   # (whatever happens now is what the card says)
        if auto:
            self.toast(_("Fixing your mic… (your sound drops for a second)"))
        else:
            self._autofix_err = ""
            # Bun's show explains the first set-up's wait and Yes; a repair or an
            # update says it in the card instead
            self._show_bun = directmic.status(mic) in ("missing", "other")
            if self._attach_release is None:   # released by _update_flow once it works
                self._attach_release = busy.hold(self.btn_install, _("Setting up…"))
            if self._show_bun:
                self.setup_show.start()
        self._update_flow()
        log.info("attaching the mic effect to %s%s", mic, " (by itself)" if auto else "")
        threading.Thread(target=self._attach_mic_work, args=(mic, clean, auto),
                         daemon=True, name="mic-attach").start()

    def _attach_mic_work(self, mic: str, clean: bool = False, auto: bool = False):
        err = directmic.install(mic, clean=clean, ask_windows=not auto) or ""
        # the admin prompt can outlast the window (closed and freed meanwhile): then
        # there's nobody to tell, and emitting on the freed window raises TypeError
        if qt_valid(self):
            try:
                self.mic_attached.emit(mic, err)
            except (RuntimeError, TypeError):   # freed between the check and the emit
                pass

    def _mic_attached(self, mic: str, err: str):
        self._attaching = False
        self._done_toast = None
        updating, self._mic_updating = self._mic_updating, False
        auto, self._autofixing = self._autofixing, False
        directmic.forget_status()
        if err:
            if self._attach_release is not None:
                release, self._attach_release = self._attach_release, None
                release(_("✗ Didn't work"))
            log.warning("not put on the mic: %s", err)
            # an older mic part can still be working (the optional update failed): the
            # status then reads fine, but this attempt didn't work, so Bun mustn't cheer
            self.setup_show.finish(False)
            usage.used("mic-effect-fix-failed" if auto else
                       "mic-effect-said-no" if err == directmic.declined() else
                       "mic-effect-failed")
            if auto:
                # the card turns into its one button with the reason (_mic_view)
                self._autofix_err = err
                self.toast(_("Couldn't fix your mic by itself: see the Setup tab."), "warn")
            elif err == directmic.declined() and not updating:
                self._declined = True   # the card says so, with its button to try again
            elif updating and err == directmic.declined():
                # No to the optional update: the old part keeps working, no box needed
                self.toast(_("Update cancelled. Your mic part is still the old one: "
                             "update it from the Setup tab."), "warn")
            elif err == directmic.mic_silent():
                # it's on the mic, but the mic came back from the audio restart dead
                self.tell(_("Your mic sends no sound"), err, "error")
            else:
                # the route stays on the mic: until it's set up, the cable carries the
                # sounds meanwhile (_main_name), and the one-click stays on offer
                err = _("{error}\n\nTry again any time from the Setup tab.", error=err)
                self.tell(_("Couldn't put Onion Board on your mic"), err, "error")
        else:
            log.info("on the mic now: %s", mic)
            usage.used("mic-effect-updated" if updating else
                       "mic-effect-fixed" if auto else "mic-effect-on")
            # Windows takes a few seconds to load it: "starting…" meanwhile, then a
            # redraw when the wait is over (it works by then, or Repair comes back)
            self._settle_until = time.monotonic() + self.SETTLE_S
            QTimer.singleShot(int(self.SETTLE_S * 1000) + 200, self._update_status)
            self.cfg.route = "cable"   # so set_route() applies "mic" in full
            self.set_route("mic", attached=True)
            from soundboard.ui.setupwizard import SetupWizard
            modal = QApplication.activeModalWidget()
            # said once it works (_update_flow), with the card turning green and Bun
            # cheering: said now, it came while the card still read "starting…" and Bun
            # was still hammering, and Windows can still fail to load it
            self._done_toast = ("updated" if updating else "fixed" if auto else
                                None if isinstance(modal, SetupWizard) else "done")
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
        if self._cable_gone:
            # removed this session: Windows still lists it until a restart, but it won't
            # open (sending into it lost the mic until it was set up again)
            self.toast(_("The virtual cable was removed. Restart your PC before you "
                         "install it again."), "warn")
            return
        if eng.virtual_outputs():
            self.set_route("cable")
            self.toast(_("Sending through the virtual cable. Pick it as the mic in Discord and "
                         "games (Setup tab)."), "ok")
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
             time.monotonic() < self._settle_until and e.effect_alive(),   # "starting…" ends
             self._mic_sends_nothing())
        return h

    def _mic_sends_nothing(self) -> bool:
        """The mic, with the effect on it, has sent only exact zeros for MIC_SILENT_S."""
        return self.engine.direct_mic_silent_s() >= self.MIC_SILENT_S

    _following_effect = False

    def _follow_mic_effect(self):
        """Sending into the mic, and the mic effect started (or stopped) working since
        what others hear was opened: switch to it (or back to the cable) now. Before,
        sounds stayed on the cable until the app restarted, e.g. when Windows loaded the
        effect a while after the app started. Checked about once a second; the streams
        open on the device thread."""
        if self._attaching or self._following_effect:
            return
        if self.engine.names["main"] == self._main_name():
            return
        self._following_effect = True
        log.info("the mic effect %s: what others hear follows",
                 "works now" if self._main_name() == directmic.DEVICE else "stopped working")

        def opened(ends):
            self._following_effect = False
            if ends is not None:
                self._set_cable_bad(ends)
            self._update_status()
            self._prepare_all()

        def plan():   # worked out when its turn comes
            send = self._send_plan()
            return lambda: self._open_send(send)
        self._device_job(plan, opened)

    DIRECT_GRACE_S = 4.0   # the board's own mic open this long, and still no sign of it
    SETTLE_S = 20.0        # after setting it up: how long Windows gets to load it
    MIC_SILENT_S = 20.0    # the mic sent only exact zeros this long: it's stuck (or muted)

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
            self.tell(_("Installer missing"), _("Can't find {name}.", name=script.name),
                      "error")
            return
        try:
            subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                              "-File", str(script)],
                             creationflags=subprocess.CREATE_NEW_CONSOLE)
        except OSError as e:
            log.warning("couldn't start the cable installer", exc_info=True)
            self.tell(
                _("Couldn't start the installer"),
                _("Windows wouldn't run PowerShell ({e}).\n\nYou can install VB-Cable by hand: "
                  "download it from vb-audio.com, unzip it, right-click VBCABLE_Setup_x64.exe → "
                  "Run as administrator → Install Driver.", e=errors.plain(e)), "error")
            return
        QMessageBox.information(
            self, _("Installing the virtual cable"),
            _("A window opened that downloads VB-Cable (free) from the official VB-Audio "
              "site.\n\nWindows will ask for permission, click Yes, then click “Install "
              "Driver”.\n\nWhen it's done, click “I've installed it, check again”. If it "
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
            self.tell(_("Couldn't open the Sound settings"),
                      _("Open it yourself: press Win+R, type  mmsys.cpl  and press "
                        "Enter, then go to the Recording tab."), "warn", 15000)
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
        if attr in ("playing_background", "playing_background_opacity"):
            self._update_playing_background(self.engine.playing())
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
        why = i18n.keep_english(lambda: _("The game you have open uses {engine} for voice chat",
                                          engine=voicesdk.NAMES.get(key, key))) if key else ""
        heard = ()
        if self.listeners is not None:
            heard = self.listeners.poll(self._heard_device())
        # for the simple modes, in order: voice chat apps on the cable, the game in
        # front, games on the cable (a per-program list would go first)
        apps = set(voicesdk.VOICE_APPS.values())
        def listening(name: str) -> str:
            return i18n.keep_english(lambda: _("{name} is listening to your mic", name=name)
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
            self._hide_setup()   # (what it said was about before the switch)
            self.toast(_("{mode} mode for <b>{name}</b>.", mode=profiles.BY_KEY[app.simple].name,
                         name=html.escape(app.name)), "ok", SETUP_SWITCHED_MS,
                       key="app-switch", action=(_("Undo"), self._undo_app_switch),
                       on_close=self._forget_app_switch)
            return
        self._show_setup("offer", app)

    def _undo_app_switch(self):
        """Undo on "Game mode for X": the mode goes back to how it was."""
        if self._setup_undo is not None:
            from soundboard.ui.destpanel import _refresh_views
            self.cfg.dest = self._setup_undo
            self._setup_undo = None
            self.mode_why = ""
            destination.apply(self.cfg, self.engine)
            self._save_later()
            _refresh_views(self)

    def _forget_app_switch(self):
        self._setup_undo = None

    def _show_setup(self, state: str, app: appsetup.Seen):
        if state == "offer" and not self.urgent_bar.isHidden():
            # The urgent bar (a Discord warning, a fix...) is already saying its piece:
            # never two bars at once. The offer waits; the warning wins (_show_urgent).
            self._setup_app, self._setup_state = None, ""
            return
        self._setup_app, self._setup_state = app, state
        self._setup_hide.stop()
        name = html.escape(app.name)
        self.setup_x.setToolTip(_("Hide"))
        self.setup_x.setAccessibleName(_("Hide"))
        self.setup_no.setVisible(state == "offer")
        if state == "offer":
            self.setup_lbl.setText(_("Looks like you're using <b>{name}</b>. Set up for it?",
                                     name=name))
            self.setup_yes.setText(_("Set up"))
            self.setup_x.setToolTip(_("Don't ask about {name} again", name=app.name))
            self.setup_x.setAccessibleName(self.setup_x.toolTip())
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
        self._save_timer.start(100)   # short: a crash loses at most this much

    def toast(self, text: str, kind: str = "", ms: int = busy.TOAST_MS, **kw):
        """A result the user should see now, whatever tab or dialog is in front (the
        status line is rewritten on every tab change and hidden in small windows)."""
        return busy.toast(self, text, kind, ms, **kw)

    def say(self, text: str, kind: str = "", ms: int = busy.TOAST_MS, **kw):
        """A toast for a text written for the old status line: its coloured
        ``<span style='color:…'>`` wrapper (still in the translations) is dropped, the
        card's colour says it now."""
        m = _TONE_SPAN.fullmatch(text)
        return self.toast(m.group(1) if m else text, kind, ms, **kw)

    def tell(self, title: str, text: str, kind: str, ms: int = 8000, **kw):
        """What a message box would have said (a title and plain words, maybe on
        several lines) as one toast: the title bold on its own line."""
        return self.toast(toastmod.titled(title, text), kind, ms, **kw)

    def unsay(self, key: str):
        """Take the toast with this key down (what it said is over)."""
        toastmod.close(self, key)

    def toast_floor(self) -> int | None:
        """Where toasts stand (window y): just above the player, or the mixer strip
        when the player's hidden."""
        bar = next((w for w in (self.transport, self.mixer) if w.isVisible()), None)
        return None if bar is None else bar.mapTo(self, QPoint(0, 0)).y()

    def toast_mode(self) -> str:
        """How the corner cards show (ui/toast.py): as cards in the window; as icons on
        top of the mini player's pads; not at all in the mini player with no pads (a
        remote: errors wait for the window to grow)."""
        if not self.is_mini():
            return "cards"
        return "icons" if self._pads_scroll.isVisible() else "hidden"

    def toast_expand(self):
        """A card shrunk to its icon was clicked: make the window big enough to read
        the cards (and leave the mini player), kept on its screen."""
        if self.isMinimized():
            self.showNormal()
        if self.isMaximized() or self.isFullScreen():
            return
        room = self.screen().availableGeometry()
        want = QSize(min(max(self.width(), TOAST_EXPAND.width()), room.width()),
                     min(max(self.height(), TOAST_EXPAND.height()), room.height()))
        if want == self.size():
            return
        frame = self.frameGeometry()
        extra = frame.size() - self.size()   # the title bar and borders
        x = min(max(frame.x(), room.left()), room.right() + 1 - want.width() - extra.width())
        y = min(max(frame.y(), room.top()), room.bottom() + 1 - want.height() - extra.height())
        self.resize(want)
        self.move(max(room.left(), x), max(room.top(), y))

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

    @overload
    def _make_tab(self, key: Literal["voice"]) -> VoicePanel | taboff.VoiceOff: ...
    @overload
    def _make_tab(self, key: Literal["apps"]) -> AppsTab | taboff.TabOff: ...
    @overload
    def _make_tab(self, key: Literal["triggers"]) -> TriggersTab | taboff.TabOff: ...
    @overload
    def _make_tab(self, key: str) -> (VoicePanel | AppsTab | TriggersTab
                                      | taboff.TabOff): ...

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

    def _squeeze_rail(self, tight: bool):
        """A narrow window: the rail shut (opened out, it shuts again) and the gap
        beside it narrower, so the pages keep their room before the mini player."""
        self.rail.squeeze(tight)
        side = (BODY_SIDE_TIGHT if tight else BODY_SIDE, BODY_SIDE)
        if self.isRightToLeft():   # mirrored (Arabic): the rail is on the right
            side = side[::-1]
        self._body_lay.setContentsMargins(side[0], self._body_top(), side[1], 10)
        if getattr(self, "_mixer_tight", False):   # its room changed: measure it again
            self._fit_mixer(True)

    def _fit_setup_tab(self, _i: int):
        """Into or out of Setup: its width counts only while it shows (WidthScroll),
        so what gives way is worked out again."""
        was, self._fit_tab = self._fit_tab, self.tabs.currentWidget()
        if hasattr(self, "_fit") and self.setup_page in (was, self._fit_tab):
            self._fit.reset()
            self._refit()

    def _rail_opened(self, on: bool):
        """The rail opened out or shut: save it, and fit the window to its new width
        (shut, what had given way for it comes back)."""
        self.set_option("sidebar_open", on)
        if hasattr(self, "_fit"):
            self._fit.reset()
            self._refit()

    def tab_menu(self, i: int) -> QMenu:
        key = TAB_KEYS[i]
        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        if self._tab_info_at(i) is not None:
            menu.addAction(icons.icon("info"), _("About this tab"),
                           lambda: self._show_tab_info(i))
            menu.addSeparator()
        if key in taboff.KEYS:
            act = menu.addAction(icons.icon("offline"), _("Hide this tab"))
            act.triggered.connect(lambda: self.hide_tab(key))
        else:
            act = menu.addAction(icons.icon("check"), _("This tab is always shown"))
            act.setEnabled(False)
        menu.addSeparator()
        menu.addAction(icons.icon("settings"), _("Choose tabs in Settings"),
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
            self.tabs.move_to(0)   # (Settings, where this is done, stays up)
        if key == "radio":
            self._radio_follow_switch()
        else:
            self._swap_tab(key)
        self.tabs.setTabVisible(i, self.tab_shown(key))
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
        self.rail.sync()
        icons.set_tab_icon(self.tabs, i, key)
        old.deleteLater()
        self._tab_live(key, False)
        if key == "triggers":
            self.load_triggers(now=False)   # (or once it's shown)
        if hasattr(self, "_fit"):
            if key in ("voice", "triggers"):
                assert not isinstance(new, AppsTab)
                self._tab_steps[key] = new.fit_steps()
                self._fit.extend(self._tab_steps[key])
            if key == "voice":
                assert isinstance(new, (VoicePanel, taboff.TabOff))
                self._stack_cols = (*self._stack_cols[:1], *new.stack_steps())
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
        """Offline mode: Offline in the On Air card, and the tabs that only work online
        (needs_online) out of the tab bar and + More tabs; back when it's off."""
        self._net_follow()
        for key in ("radio", "triggers"):
            i = TAB_INDEX[key]
            shown = self.tab_shown(key)
            if not shown and self.tabs.currentIndex() == i:
                self.tabs.move_to(0)   # (Settings, where this is done, stays up)
            self.tabs.setTabVisible(i, shown)
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

    def card_lines(self) -> list[sidebar.Line]:
        """What the On Air card says under its status (OutputBlock.set_lines): how the
        app goes online, and a remote control listening."""
        return [line for line in (self._network_line(), self._remote_line()) if line]

    def _network_line(self) -> sidebar.Line | None:
        """Offline mode, a proxy or Tor (and how far Tor got), or None when direct."""
        if net.offline():
            return sidebar.Line("offline", _("Offline"), "",
                                _("Offline mode is on: nothing goes online, and what needs "
                                  "the internet is hidden. Click to change it."), "privacy")
        mode = net.mode()
        click = _("Click to change it.")
        if mode == net.TOR:
            t = tor.manager()
            tip = "\n".join((t.status_text(), click))
            if t.state == tor.READY:
                return sidebar.Line("tor", _("Through Tor"), "ok", tip, "privacy")
            if t.state == tor.STARTING:
                return sidebar.Line("tor", _("Tor {percent}%", percent=t.progress), "", tip,
                                    "privacy")
            if t.state == tor.FAILED:
                return sidebar.Line("tor", _("Tor failed"), "warn", tip, "privacy")
            return sidebar.Line("tor", _("Tor"), "", tip, "privacy")
        if mode == net.PROXY:
            p = net.proxy()
            if p is None:
                return sidebar.Line("shield", _("Proxy not working"), "warn",
                                    "\n".join((net.describe(), click)), "privacy")
            return sidebar.Line("shield", _("Through proxy"), "ok",
                                "\n".join((_("Everything goes through your proxy "
                                             "({address}).", address=p.where), click)),
                                "privacy")
        return None

    def _remote_line(self) -> sidebar.Line | None:
        """A phone remote (a remote add-on such as Onion Pocket) listening on the home
        network, or else the control API listening on this PC; None when neither."""
        servers = remote.listening()
        click = _("Click to change it.")
        phone = [s for s in servers if s.lan]
        if phone:
            return sidebar.Line("phone", _("Phone remote on"), "ok",
                                "\n".join((_("Phones on your home network can control the "
                                             "board ({address}).",
                                             address=f"{phone[0].host}:{phone[0].port}"),
                                            click)), "remote")
        if servers:
            return sidebar.Line("phone", _("Remote control on"), "",
                                "\n".join((_("Stream Deck buttons and scripts on this PC "
                                             "can control the board (port {port}).",
                                             port=servers[0].port), click)), "remote")
        return None

    def _remote_watch(self):
        self.remote_changed.emit()   # (maybe from the thread that stopped it)

    def _net_follow(self):
        output = getattr(getattr(self, "rail", None), "output", None)
        if output is not None:
            output.set_lines(self.card_lines())
            self.rail.refresh_output()   # (the card's widest line can change its scale)

    def _on_tor(self):
        """Something is waiting for Tor: say so (once), and when it's ready or failed."""
        self._net_follow()
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
            self.toast(_("Couldn't save your settings, see the log in %APPDATA%\\OnionBoard."),
                       "error")

    def on_level_toggle(self, b):
        self.set_option("level_volumes", b)
        self._fold_summaries()
        for m in self.cfg.sounds:
            self.engine.set_gain(m.id, self.gain_for(m))

    def set_live_color(self, colour: str) -> bool:
        """The user's own highlight colour ("" = the theme's). Only what's drawn in it
        is restyled (quick); False when it's the colour in use already."""
        if theme.valid_colour(colour) == theme.live_override:
            return False
        self.set_option("live_color", theme.apply_live(QApplication.instance(), colour))
        icons.retheme_live()
        self._pill_long = ""   # forces _update_flow to repaint its icon
        self._update_status()
        return True

    def set_live_tab_tint(self, on: bool):
        self.set_option("live_tab_green", on)
        set_live_tint(self.tabs, on)

    def on_top_toggle(self, b):
        self.set_option("always_on_top", b)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, b)
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
        if self._hotkeys_off and not self.cfg.hotkeys_off_hotkey:
            # the key that turns them back on was cleared or given to something else:
            # nothing could turn them on again until a restart, so they're on now
            self._hotkeys_off = False
            self.toast(_("Hotkeys are on again."), "ok", key="hotkeys")
        if self._hotkeys_off:   # only the key that turns them back on
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
            self.say(_("<span style='color:{status}'>{devices} is open in another "
                       "program (a music app?), so its pads don't work here until "
                       "that program lets go of it.</span>",
                       status=theme.status('warn'),
                       devices=html.escape(", ".join(busy))), "warn")

    def on_replay_state(self):
        if self.replay.enabled and self.replay.error:
            self.say(_("<span style='color:{status}'>Instant replay can't listen: "
                       "{error}</span>", status=theme.status('warn'),
                       error=html.escape(self.replay.error)), "warn")

    def save_replay(self):
        """The instant-replay hotkey: the last seconds of what you heard become a pad."""
        data = self.replay.clip()
        if len(data) < int(0.2 * SR):
            self.cue("fail")
            why = self.replay.error or ngettext(
                "nothing has played on this PC in the last {n} second",
                "nothing has played on this PC in the last {n} seconds", self.replay.seconds)
            self.say(_("<span style='color:{status}'>Nothing to save: {why}.</span>",
                       status=theme.status('warn'), why=html.escape(why)), "warn")
            return
        self.on_clip(data, _("Replay {time}", time=time.strftime("%H.%M.%S")))
        self.cue("saved")

    def on_hotkeys_failed(self, failed: list[str]):
        if not failed:
            return
        log.warning("hotkeys that couldn't be claimed: %s", failed)
        self.say(_("<span style='color:{status}'>Another program is already "
                   "using {keys}, pick a different hotkey.</span>",
                   status=theme.status('warn'),
                   keys=html.escape(", ".join(pretty_key(c) for c in failed))), "warn")

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
            self.toast(_("{hotkey} is {what} now, it was the key for {lost}",
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
            icons.set_icon(menu.addAction(f"{labels[attr]}	{key}",
                                          lambda a=attr: self._quick_set_hotkey(a)), "keyboard")
        menu.addSeparator()
        icons.set_icon(menu.addAction(_("All hotkeys"), lambda: self.open_settings("hotkeys")),
                       "settings")

    def _quick_set_hotkey(self, attr: str):
        d = HotkeyDialog(self.hotkeys, self, pads=attr != "ptt_key")
        if d.exec() and d.result_combo:
            self.set_global_hotkey(attr, d.result_combo)
        else:
            self.register_hotkeys()   # the capture paused them
        free_dialog(d)

    def _tab_info_at(self, i: int) -> tuple[str, str] | None:
        page = self.tabs.widget(i)
        return next((v for k, v in self.tab_info.items() if getattr(self, k, None) is page),
                    None)

    def _show_tab_info(self, i: int):
        """A tab's right-click "About this tab": its explanation, next to the tab."""
        info = self._tab_info_at(i)
        if info:
            button = next((b for b in self.rail.buttons if b.index == i), self.tabs)
            self._show_help(TabHelpPopup(*info, owl=self.tabs.widget(i) is self.triggers,
                                         parent=self), button)

    def _show_mic_tips(self):
        """Your mic's ⓘ: the voice app settings that stop it chopping your sounds up."""
        box = TabHelpPopup(
            _("Sounds chopped up?"),
            _("If sounds get chopped up, switch off the voice app's noise suppression "
              "(Discord: <b>Input Profile → Custom</b>, <b>Noise Suppression → None</b>, "
              "<b>Echo Cancellation</b> off. Not Studio: it skips Onion Board)."),
            parent=self)
        box.body.setTextFormat(Qt.TextFormat.RichText)   # (the setting names in bold)
        self._show_help(box, self.btn_mictips)

    def _show_help(self, box: QDialog, beside: QWidget):
        """Open a help card to the right of `beside` (a rail button), inside the
        window: never off its left edge."""
        lay = box.layout()
        assert lay is not None   # the popup's own
        lay.activate()   # wrapped text: as tall as the words need
        box.resize(box.width(), box.heightForWidth(box.width()) if box.hasHeightForWidth()
                   else box.sizeHint().height())
        top_left = beside.mapToGlobal(QPoint(beside.width() + 8, 0))
        area = self.geometry() & beside.screen().availableGeometry()
        x = max(area.left(), min(top_left.x(), area.right() - box.width() + 1))
        y = max(area.top(), min(top_left.y(), area.bottom() - box.height() + 1))
        box.move(x, y)
        box.exec()
        box.deleteLater()

    # ------------------------------------------------------------------ FFmpeg
    def check_ffmpeg(self):
        """Is FFmpeg there and does it start? The answer of the check started behind the
        loading screen (ffmpegget.start_check), or a new one, taken on a worker (it runs
        ffmpeg); it comes back to _on_ffmpeg, which gets FFmpeg by itself when needed."""
        if self._ff_checking:
            return
        self._ff_checking = True

        def work():
            try:
                h = ffmpegget.answer()
            except Exception:  # noqa: BLE001 - no answer, never a crash
                log.exception("FFmpeg check failed")
                h = None
            busy.emit(self.bridge.ffmpeg, h, None)
        threading.Thread(target=work, daemon=True, name="ffmpeg-check").start()

    def _may_get_ffmpeg(self) -> bool:
        """Get FFmpeg without asking: unless the user said not to go online for it
        (Offline mode, its switch, Low data mode) or not to ask about it again."""
        return (not self._ff_auto_tried and FF_ASK_OFF not in self.cfg.tips_seen
                and not ffmpegget.why_not() and not quality.current.low_data)

    def fix_ffmpeg_clicked(self, btn: QPushButton, force: bool = False):
        """Fix it / Get FFmpeg / Reinstall (the bar or Settings): pressing it is a yes,
        so a switched-off FFmpeg download is switched back on. Offline mode stays: it
        says so instead."""
        if self._ff_getting or busy.is_busy(btn):
            return
        if net.offline():
            self.toast(html.escape(net.off_message(ffmpegget.FEATURE)), "warn", 8000)
            return
        if not net.allowed(ffmpegget.FEATURE):
            off = [k for k in self.cfg.net_off if k != ffmpegget.FEATURE]
            self.set_option("net_off", off)
            net.configure_features(self.cfg.net_off, self.cfg.net_offline)
            self.toast(_("FFmpeg downloads are switched on again (Settings → Privacy & "
                         "security)."))
        self.fix_ffmpeg(btn, force)

    def fix_ffmpeg(self, btn: QPushButton | None = None, force: bool = False,
                   auto: bool = False):
        """Get FFmpeg, or repair one that won't start (``force``: reinstall a working
        one), on a worker: winget, then the app's own download (ffmpegget.fix). The bar
        shows how far it is, with Stop; ``btn`` shows it's busy and then whether it
        worked; the bar and Settings show the new state."""
        if self._ff_getting:
            return
        usage.used("get-ffmpeg-auto" if auto else "get-ffmpeg")
        self._ff_getting, self._ff_percent, self._ff_error = True, -1, ""
        self._ff_auto_now = auto
        self._ff_auto_tried = self._ff_auto_tried or auto
        stop = self._ff_stop_flag = threading.Event()
        if btn is not None:
            self._ff_waiting.append((btn, busy.hold(btn, _("Getting FFmpeg…"))))
        seen = [-1]

        def progress(done: int, total: int):
            pct = min(99, done * 100 // total) if total else -1
            if pct != seen[0]:
                seen[0] = pct
                busy.emit(self.bridge.ffmpeg_progress, pct)

        def work():
            netlog.cause(ffmpegget.FEATURE,
                         "FFmpeg was missing or wouldn't start when the app started" if auto
                         else "You clicked Fix it, Get FFmpeg or Reinstall (the FFmpeg bar, "
                              "or Settings > Data & quality)")
            err: object = ""
            try:
                ffmpegget.fix(force, progress, stop)
            except ffmpegget.GetError as e:
                err = e
            except Exception as e:  # noqa: BLE001 - shown, never a stuck button
                log.exception("Get FFmpeg failed")
                err = ffmpegget.GetError(_("Couldn't get FFmpeg ({error}).",
                                           error=errors.plain(e)))
            busy.emit(self.bridge.ffmpeg, ffmpegget.last(), err)
        threading.Thread(target=work, daemon=True, name="ffmpeg-get").start()
        self._ffmpeg_news()

    def _on_ffmpeg_progress(self, pct: int):
        if self._ff_getting:
            self._ff_percent = pct
            self._ffmpeg_news()

    def _on_ffmpeg(self, h, err):
        """A check's answer (``err`` None) or a fix's (``err`` "" when it worked, else
        the GetError)."""
        if h is not None:
            self.ffmpeg = h
        if err is None:
            self._ff_checking = False
            if h is not None and h.state != ffmpegget.OK and self._may_get_ffmpeg():
                self.fix_ffmpeg(auto=True)
                return
        else:
            self._ff_getting, self._ff_stop_flag = False, None
            stopped = isinstance(err, ffmpegget.Stopped)
            if err and not stopped:
                usage.used("get-ffmpeg-auto-failed" if self._ff_auto_now
                           else "get-ffmpeg-failed")
            for btn, release in self._ff_waiting:
                if qt_valid(btn):
                    release(None if stopped else _("✗ Failed") if err else _("✓ Got FFmpeg"))
            self._ff_waiting.clear()
            self._ff_error = "" if stopped else errors.plain(err) if err else ""
            self._ff_done = not err
            if stopped:
                pass
            elif err:
                self.toast(html.escape(self._ff_error), "error", 8000)
            elif h is not None and h.version:
                self.toast(_("FFmpeg works now (version {version}).",
                             version=html.escape(h.version)), "ok")
            else:
                self.toast(_("FFmpeg works now."), "ok")
        self._ffmpeg_news()

    def _ffmpeg_news(self):
        """The bar, and Settings' FFmpeg row if it's built, show the current state."""
        self._show_ffmpeg_bar()
        dlg = self._settings_dlg
        if dlg is not None and qt_valid(dlg):
            dlg._ffmpeg_sync()

    def _show_ffmpeg_bar(self):
        """While FFmpeg downloads: how far, with Stop. When it's missing or won't start
        and the app couldn't get it by itself: what stops working, and Fix it. Hidden by
        ✕ until the next start, and for good by Don't ask again."""
        h = self.ffmpeg
        if self._ff_not_now or (not self._ff_getting and (
                h is None or h.state == ffmpegget.OK or FF_ASK_OFF in self.cfg.tips_seen)):
            self.ff_bar.hide()
            return
        if self._ff_getting:
            text = (_("Getting FFmpeg, so M4A, AAC and video files play and videos can be "
                      "saved… {percent}%", percent=self._ff_percent)
                    if self._ff_percent >= 0 else
                    _("Getting FFmpeg, so M4A, AAC and video files play and videos can be "
                      "saved…"))
            why = ""
        else:
            assert h is not None
            if h.state == ffmpegget.MISSING:
                text = _("FFmpeg is missing, so M4A, AAC and video files won't play and "
                         "videos can't be saved.")
            else:
                text = _("FFmpeg won't start ({error}), so M4A, AAC and video files won't "
                         "play and videos can't be saved.", error=h.why or _("no reason given"))
            why = (self._ff_error or ffmpegget.why_not()
                   or (_("Low data mode is on, so it wasn't downloaded by itself (about "
                         "110 MB).") if quality.current.low_data else ""))
        self.ff_lbl.setText("\n".join(t for t in (text, why) if t))
        for b, on in ((self.ff_fix, not self._ff_getting), (self.ff_never, not self._ff_getting),
                      (self.ff_stop, self._ff_getting)):
            if not on and b.hasFocus():
                self.ff_hide.setFocus()   # hiding a focused button jumps focus elsewhere
            b.setVisible(on)
        self.ff_bar.show()

    def _ffmpeg_fix_clicked(self):
        self.fix_ffmpeg_clicked(self.ff_fix)

    def _ffmpeg_stop(self):
        if self._ff_stop_flag is not None:
            self._ff_stop_flag.set()
            busy.flash(self.ff_stop, _("Stopping…"))

    def _ffmpeg_not_now(self):
        self._ff_not_now = True
        self.ff_bar.hide()

    def _ffmpeg_never(self):
        self.ff_bar.hide()
        if FF_ASK_OFF not in self.cfg.tips_seen:
            self.cfg.tips_seen.append(FF_ASK_OFF)
        self._save_later()
        self.toast(_("Won't ask about FFmpeg again. Settings → Data & quality still has it."))

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
            w.setLayoutDirection(Qt.LayoutDirection.RightToLeft if i18n.is_rtl(code)
                                 else Qt.LayoutDirection.LeftToRight)
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

    def open_settings(self, page: str | None = None):
        """Settings as a page in the window, in the tabs' place (the rail stays, its
        cog selected): they apply as they change, and sounds and hotkeys keep working
        while it's up. [Done], Escape or any tab on the rail goes back to the tab you
        were on. Asked for again while up: the same page, on `page` if one is named."""
        dlg = self._settings_dlg
        fresh = dlg is None or not qt_valid(dlg)
        if dlg is not None and not fresh:
            if page:
                dlg.show_page(page)
        else:
            dlg = self._settings_dlg = SettingsDialog(self, page or "privacy", lazy=True)
            dlg.finished.connect(lambda _r, d=dlg: self._settings_closed(d))
            # (what "Send my sounds to" was: a new pick is checked on the way out)
            self._route_at_open = (self.cfg.route, self.cfg.main_device)
            self._content.addWidget(dlg)
        self._content.setCurrentWidget(dlg)
        self._fit_body_top()
        self._opening_settings = True   # (_refit: not closed again for being too small)
        try:
            self._board_counts(False)
            if self.is_mini():
                self._grow_for_settings()
        finally:
            self._opening_settings = False
        self.rail.select_foot(self.gear)
        self._show_transport()
        # (Escape is for it now; fresh, not the back arrow: the mini player's swap
        # handed the focus on to it, ringed)
        if fresh or not _holds_focus(dlg):
            dlg.categories.setFocus(Qt.FocusReason.OtherFocusReason)
        return dlg

    def _board_counts(self, on: bool):
        """The tabs hidden behind Settings don't count towards the room the window
        needs (a stack takes its widest page's): the board needs 464 px, Settings fits
        in less, so a 440 px window stayed the mini player with Settings out of sight."""
        policy = QSizePolicy.Policy.Preferred if on else QSizePolicy.Policy.Ignored
        self._tabs_area.setSizePolicy(policy, policy)
        if hasattr(self, "_fit"):
            self._refit()

    def _grow_for_settings(self):
        """Settings asked for from the mini player: the window grows to the smallest
        size that shows them (SETTINGS_ROOM, or what the window needs), on the screen."""
        screen = self.screen().availableGeometry() if self.screen() else None
        for _try in range(4):
            size = self._pages.size()
            need = self._fit.fit(size).expandedTo(SETTINGS_ROOM)
            if (not self.is_mini() and size.width() >= need.width()
                    and size.height() >= need.height()):
                break
            grow = need.expandedTo(size) - size
            w, h = self.width() + grow.width(), self.height() + grow.height()
            if screen is not None:
                w, h = min(w, screen.width()), min(h, screen.height())
            self.resize(w, h)
            self._refit()

    def _body_top(self) -> int:
        """The body's top margin: none under Settings, whose heading rises level with
        the rail's name and keeps its pages where a tab's start (SettingsDialog)."""
        return 0 if self.settings_open() else 10

    def _fit_body_top(self):
        m = self._body_lay.contentsMargins()
        self._body_lay.setContentsMargins(m.left(), self._body_top(), m.right(), m.bottom())

    def settings_open(self) -> bool:
        dlg = self._settings_dlg
        return dlg is not None and qt_valid(dlg) and self._content.currentWidget() is dlg

    def close_settings(self):
        """Back from Settings to the tabs, as [Done] does (nothing to undo: it's live)."""
        if self.settings_open() and self._settings_dlg is not None:   # (settings_open checked)
            self._settings_dlg.accept()

    def _settings_closed(self, dlg):
        if self._settings_dlg is dlg:
            self._settings_dlg = None
        had_focus = _holds_focus(dlg)
        self._content.setCurrentWidget(self._tabs_area)
        self._content.removeWidget(dlg)
        self._fit_body_top()
        self._board_counts(True)
        self.rail.select_foot(None)
        self._show_transport()
        if had_focus:   # (not left on a page that's gone)
            self._focus_sounds_page(self.tabs.currentIndex())
            if not _holds_focus(self._tabs_area):
                self.tabs.currentWidget().setFocus(Qt.FocusReason.OtherFocusReason)
        # freed once its finished signal is over (deleting it inside that crashed)
        QTimer.singleShot(0, lambda: free_dialog(dlg))
        self.register_hotkeys()   # in case a capture was cancelled
        self._check_route_pick()

    def _check_route_pick(self):
        """Leaving Settings with "Send my sounds to" newly on a device that isn't a
        virtual cable (speakers, a headset): asks whether that's meant, since Discord
        and games don't hear it. Only for a new pick, so OBS and mixer users who chose
        it on purpose aren't asked every time."""
        c = self.cfg
        before = getattr(self, "_route_at_open", None)
        self._route_at_open = None
        if before == (c.route, c.main_device) or not c.main_device \
                or not routewarn.needs_warning(c.route, c.main_device, c.mon_device):
            return
        # (the picker already lists the outputs: no device call here)
        names = [self.cb_route.itemData(i) or "" for i in range(self.cb_route.count())]
        cables = [n[len(ROUTE_DEVICE):] for n in names
                  if n.startswith(ROUTE_DEVICE) and is_virtual_cable(n[len(ROUTE_DEVICE):])]
        box = self._route_warning = routewarn.RouteWarning(c.main_device, bool(cables), self)

        def done(code, dev=c.main_device):
            self._route_warning = None
            QTimer.singleShot(0, lambda: free_dialog(box))   # (not inside finished)
            # (still that device: not changed elsewhere while it was up)
            if self.cfg.main_device != dev or self.cfg.route != "device":
                return
            if code == routewarn.MIC:
                self.set_route("mic", by_hand=True)
            elif code == routewarn.CABLE:
                # on the cable, then Setup: it shows the cable working, or installing it
                self.set_route("cable", cables[0] if cables else None, by_hand=True)
                self.tabs.setCurrentWidget(self.setup_page)
                if not cables:
                    self.install_cable()
        box.finished.connect(done)
        box.open()

    def apply_theme(self, name: str):
        # a still of the window with Bun over it while every widget restyles: no frame
        # of a half-styled window, and it fades to the new theme (ui/themecover.py)
        with themecover.covered(self):
            self._apply_theme(name)

    def _apply_theme(self, name: str):
        self.cfg.theme = theme.apply(QApplication.instance(), name)
        icons.retheme()
        self.radio.retheme()
        self.apps.retheme()
        self.triggers.retheme()
        self.download_bar.retheme()
        self.mini_download_bar.retheme()
        self.ytresults.retheme()
        pp, self._pp_icon = self._pp_icon, None
        self._set_pp_icon(pp or "play")
        self._pill_long = ""   # forces _update_flow to repaint its icon
        self._update_status()   # the hints and flow, in this theme's status colours
        self.rail.refresh_output()   # its status icon is a copy of the pill's: redrawn
        self._paint_logo()
        self._save_later()

    def _show_about_menu(self):
        # (a foot button is checkable for Settings' "showing" fill: this one never is)
        self.btn_about.setChecked(False)
        # up from the rail's foot, its edge over the onion's (down, it ran off the window)
        m = self.about_menu
        self._fill_about_menu()
        edge = 0 if not self.isRightToLeft() else self.btn_about.width() - m.sizeHint().width()
        m.popup(self.btn_about.mapToGlobal(QPoint(edge, -m.sizeHint().height())))

    def _fill_about_menu(self):
        """The onion at the rail's foot: where to talk to us, and where the app lives."""
        from soundboard import __version__, feedback
        m = self.about_menu
        m.clear()
        icons.set_icon(m.addAction(_("Join the Discord"), lambda: self._open_page(
            feedback.DISCORD_URL)), "speech")
        icons.set_icon(m.addAction(_("Send feedback"), self.ask_feedback), "edit")
        icons.set_icon(m.addAction(_("Report a problem"), lambda: self._open_page(
            feedback.problem_url(__version__))), "warn")
        m.addSeparator()
        icons.set_icon(m.addAction(_("Onion Board on GitHub"), lambda: self._open_page(
            f"https://github.com/{updates.REPO}")), "folder")
        news = _("What's new")
        icons.set_icon(m.addAction(f"{news} (v{__version__})", self.show_whats_new), "info")

    def _paint_logo(self):
        self.logo.update()   # it reads the theme colours itself
        # title bar + taskbar follow the theme too, and so do the taskbar's right-click
        # menu, a pin and the app's own Desktop / Start menu shortcuts (shellicon)
        # (they stay still while sound plays: only the header logo glows. Swapping
        # them made Windows redraw the taskbar button, which flickered its layers)
        icon = glow_icon(theme.T["accent"], theme.T["accent2"], 0.0)
        QApplication.setWindowIcon(icon)   # every window, dialogs too
        self.setWindowIcon(icon)
        tray = getattr(self, "tray", None)
        if tray is not None:
            tray.setIcon(icon)
        shellicon.follow_theme(self, theme.T["accent"], theme.T["accent2"])
        shellicon.paint_background(self, theme.T["bg"])   # fast resizes: no white edge

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
            self.play_last()
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
            self._pause_clicked()
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
                self.toast(_("The Voice tab is switched off (Settings > Tabs)."), "warn")
            return
        if self.voice.fx.btn_power.isChecked() != on:
            self.voice.fx.btn_power.setChecked(on)   # its toggled handler applies it

    def toggle_hotkeys(self):
        """All hotkeys off (they type normally again), or back on. Not saved: the app
        always opens with them on."""
        if not self._hotkeys_off and not self.cfg.hotkeys_off_hotkey:
            return   # no key to turn them back on with
        self._hotkeys_off = not self._hotkeys_off
        if self._hotkeys_off and self._voice_was is not None:   # a held voice key
            self._set_voice(self._voice_was)
            self._voice_was = None
        self.register_hotkeys()
        self.cue("stop" if self._hotkeys_off else "start")
        key = pretty_key(self.cfg.hotkeys_off_hotkey)
        if self._hotkeys_off:
            self.say(_("<span style='color:{status}'>Hotkeys are off: {key} turns them back "
                       "on.</span>", status=theme.status('warn'), key=html.escape(key)),
                     "warn", key="hotkeys")
        else:
            self.toast(_("Hotkeys are on again."), "ok", key="hotkeys")

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
        self.toast(_("Category: {value}", value=html.escape(name or 'All')), key="category")

    def step_sound_volume(self, step: int):
        """The louder / quieter hotkeys: the sounds' volume box by 10 % a press."""
        pct = self.vol_sound.spin.value()
        new = min(max((round(pct / 10) + step) * 10, 0), self.vol_sound.spin.maximum())
        self.vol_sound.spin.setValue(new)   # -> set_option("sound_vol")
        self.cue((880, 1175) if step > 0 else (880, 659))
        self.toast(_("Sounds: {new}%", new=new), key="volume")

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
        """The master switch, "Others hear": on (others hear your mic and whatever is
        live) or off (they hear nothing at all, or only your plain voice while your mic is
        sent and no voice changer is on: engine.mic_only). Everything keeps playing for
        you. Not saved: the app always opens live, so nobody's left wondering why they're
        silent."""
        self.engine.sending = on
        if self.btn_air.isChecked() != on:
            self.btn_air.setChecked(on)   # comes back here
            return
        # sending nowhere (or the send device is the headphones): Live doesn't claim
        # others hear you; muting still silences the stream output, if there is one
        others = self._main_name() is not None
        stream = bool(self.engine.names["obs"])
        voice = not on and others and self.engine.mic_only()
        if voice:
            text = (_("Others hear only your mic"), _("Only your mic"), "")
        elif not on:
            text = (_("Muted: others hear nothing"), _("Muted"), "")
        elif others:
            text = (_("Live: others hear you"), _("Live"), "")
        elif stream:
            text = (_("Live: stream output only"), _("Live"), "")
        else:
            text = (_("Only you hear sounds"), _("Only you"), "")
        # one word ("Live") on the open rail; the whole sentence leads its tooltip and
        # is what a screen reader says
        if voice:
            tip = _("Click to send your sounds again: right now others hear only your mic")
        elif not on:
            tip = _("Click to go live again: others hear you and your sounds")
        elif others:
            tip = (_("Click to mute your sounds for others (Discord, the game, OBS…). Your "
                     "mic still goes out unless a voice changer is on. You still hear "
                     "everything"))
        elif stream:
            tip = (_("Nothing goes out to others, only to the stream output. Click to mute that "
                     "too (you still hear everything)"))
        else:
            tip = (_("Nothing goes out to others: pick where to send on the Setup tab (Send my "
                     "sounds to)"))
        if self._pill_good and self._pill_long:   # the hidden pill's "In your mic…"
            tip = f"{self._pill_long}\n{tip}"
        sidebar.put(self.btn_air, text[1], text[0], tip)
        if hasattr(self, "thumbbar"):
            self.thumbbar.set_live(on)
        if hasattr(self, "mini_air"):
            self.mini_air.setChecked(on)
            self.mini_air.setToolTip(self.btn_air.toolTip())

    def _stop_all_clicked(self):
        self.stop_all()
        # only an icon on the rail: a tick for a moment says it worked
        icons.set_icon(self.stop_btn, "check", "live_text", size=sidebar.ICON, gap=False)
        QTimer.singleShot(1200, self.stop_btn,   # (the button: never after it's gone)
                          lambda: icons.set_icon(self.stop_btn, "stop", "danger_text",
                                                 size=sidebar.ICON))
        card = self.rail.output.stop if self.rail.output else None
        if card is not None:   # the open card's Stop all: the same tick
            icons.set_icon(card, "check", "live_text", gap=False)
            QTimer.singleShot(1200, card, lambda: icons.set_icon(card, "stop", "danger_text",
                                                                 gap=False))

    def play_last(self):
        if self._last_sid is None or self.meta(self._last_sid) is None:
            self.cue("fail")
        else:
            self.play(self._last_sid)

    def _pause_clicked(self):
        """Pause everything playing (sounds and the radio), or bring it all back. A
        station is live, so pausing it stops it and Play turns the same one back on."""
        playing = self.engine.playing()
        radio_on = self.radio.is_active()
        if radio_on or any(not paused for _p, paused in playing.values()):
            if any(not paused for _p, paused in playing.values()):
                self.engine.pause_all()   # something still plays: pauses them all
            if radio_on:
                self._radio_paused = getattr(getattr(self.radio, "player", None), "station", None)
                self.radio.stop()
        else:
            if playing:
                self.engine.pause_all()   # all paused: resumes them
            station, self._radio_paused = self._radio_paused, None
            play = getattr(self.radio, "play", None)   # (the Radio tab switched off: none)
            if station is not None and play is not None:
                play(station)
        self._wake()

    def stop_all(self):
        self._radio_paused = None
        self._queue.clear()
        self._say_queue()
        for sid in list(self._waiting):
            self._cancel_waiting(sid)
        self.engine.stop_all()
        self.radio.stop()
        self.apps.stop_all()
        self.triggers.cancel_pending()
        self.voice.stop_all()   # the voice changer and the other voices go off too

    def load_triggers(self, now: bool = True):
        """Put the Onion Watch add-on into the Triggers tab. It took 0.4-1 s on the UI
        thread, so it waits until the window is up: a 0 ms timer would still run before
        Windows' first paint message, a TRIGGERS_LOAD_MS one runs after it. Runs once.
        `now` False (the window's start, the tab switched back on): only if it has to
        run now (watching was on); otherwise the tab loads it when first shown."""
        if not isinstance(self.triggers, TriggersTab) or not self.triggers.pending \
                or self._shut_down:   # (switched off: its stand-in has nothing pending)
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
        QTimer.singleShot(0, self, lambda: self.say(
            _("<span style='color:{status}'>Your screen triggers now come from the free Onion "
              "Watch add-on: open the Triggers tab to get it.</span>",
              status=theme.status('warn')), "warn", 10000,
            action=(_("Open Triggers"), lambda: self.tabs.setCurrentWidget(self.triggers))))

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

    def on_link_played(self, title: str, data, gain: float, url: str = ""):
        """The link bar's Play once: show it in the transport bar like a pad, so it
        can be paused, stopped and seeked. It isn't a sound in the library."""
        self._link_meta = SoundMeta(id=LINK_ID, name=title, file="", level_gain=gain,
                                    duration=len(data) / SR)
        self._link_url = url or self.linkbar.url   # its own page (another card may show)
        self.audio[LINK_ID] = data
        if self.current == LINK_ID:
            self.current = None   # a new link: refresh the name
        self.select(LINK_ID)

    def _on_site_picked(self, key: str):
        """A site picked in the search button's menu: it shows that site, and the
        search box's words are searched there now (open results re-run themselves)."""
        icons.set_icon(self.btn_yt, key, size=18)
        if self.ytresults.isHidden() and self.search.text().strip():
            self.search_youtube()

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
        self._results_open = True
        self._sync_cat_bar()

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
        if not url or self.is_mini():
            return
        if not ytdl.site_allowed(url):
            # Offline mode or that site switched off: say so once per link, not nothing
            if url != getattr(self, "_link_off_said", None):
                self._link_off_said = url
                self.toast(net.off_message(ytdl.site_feature(url)))
            return
        if not self.ytresults.show_link(url):
            return
        self._pads_scroll.hide()
        self._cat_row.hide()
        self._results_open = True
        self._sync_cat_bar()

    def _retry_download(self, item: dict):
        """The download bar's Retry on a pick that failed: picked again, as if its
        search card was clicked (it starts, or waits its turn)."""
        kind = item["kind"]
        self.linkbar.open(item["url"], item["title"], item["seconds"])
        self.ytresults.mark(item["url"], kind)
        if not (self.linkbar.play_once() if kind == "play" else self.linkbar.add()):
            self.ytresults.mark(item["url"], kind, False)

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
        """Play a pad's sound as its settings say (by default one at a time: a new
        sound stops the others, PRESS_MODE): its cooldown, a Queue sound waiting
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
                self.say(_("<span style='color:{status}'>Can't play “{name}”{why}. If "
                           "the file was moved or deleted, remove the pad and add the "
                           "sound again.</span>",
                           status=theme.status('error'), name=name, why=why), "error")
            else:
                self.toast(_("“{name}” is still loading…", name=html.escape(m.name)), "warn")
            return
        self.select(sid)
        self._last_sid = sid
        if sid != LINK_ID:
            m.plays += 1   # Most played
            if not self._count_save.isActive():
                self._count_save.start()
        v = self.engine.play(sid, data, self.gain_for(m), loop=m.loop,
                             mode=PRESS_MODE.get(m.mode, m.mode),
                             fade_in=m.fade_in, fade_out=m.fade_out,
                             only=("main", "obs") if m.only_them else None)
        self._wake()
        if v is not None:   # a new install's first steps (usage.py; once each, if counted)
            usage.step(self.cfg, "played-sound")
            if self.cfg.route != "off":
                usage.step(self.cfg, "sent-to-others")
        if v is None and not self.engine.active_outputs():
            self.say(_("<span style='color:{status}'>No audio device is open, pick "
                       "one in Setup.</span>", status=theme.status('warn')), "warn")

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

    def queue_sound(self, sid: str) -> bool:
        """Play `sid` once the board's sounds playing now have finished (now, if none are:
        True then)."""
        if not self._pads_playing() and not self._queue:
            self.play(sid, now=True)
            return True
        self._queue.append(sid)
        self._say_queue()
        return False

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
            self.toast(self._queue_said, key="queue")
        elif getattr(self, "_queue_said", None):   # ran out / cleared
            self._queue_said = None
            self.unsay("queue")

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
            st = self.engine.state(sid)
            self.engine.set_paused(sid, not (st is not None and st[1]))
            self._wake()
        else:
            self.play(sid)

    def stop_current(self):
        """The player's ■. A second press within a double-click of the first that
        would stop a different sound is a double click (or a bouncy mouse): the queue's
        next sound had already taken the player, and it went too."""
        if self.current:
            self._stop_one(self.current)
        self.start_frac = 0.0

    def _stop_one(self, sid: str):
        """A ■ for one sound (the player's, or a Now playing chip's). A second press
        within a double-click of one that stopped a different sound does nothing: the
        player had moved to the next sound, or the chips row was remade and the next
        sound's ■ slid in under the mouse, and a double click (or a bouncy mouse)
        stopped that one too, so stopping one sound stopped two or all of them."""
        now, (at, was) = time.monotonic(), self._stopped_at
        if was and sid != was and now - at < QApplication.doubleClickInterval() / 1000:
            return
        self._stopped_at = (now, sid)
        self._stop_sound(sid)

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
                self._set_np_time(fmt_pos(v / 1000 * m.duration, m.duration))

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
        self._preview_fades: dict[str, Any] = {"fade_in": fade_in, "fade_out": fade_out}
        if fx is None or soundfx.key(fx) == soundfx.key(m.fx):
            self.drop_preview()   # an effects render still going mustn't play over it
            self.engine.play(sid + ":preview", data, gain, mode="restart", preview=True,
                             **self._preview_fades)
            return "playing"
        self.drop_preview()
        gen = self._preview_gen
        self._preview_done = done
        self.toast(_("Rendering the preview…"), "busy", key="preview")

        def run():
            try:
                # into the cache file for these effects: a long sound is never all in
                # memory, and saving them afterwards finds it rendered
                out = library.render_cached(m.id, load_original(m), fx)
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
            self.unsay("preview")

    def _on_fx_preview(self, sid, data, gain, gen=None):
        if gen is not None and gen != self._preview_gen:
            return   # dropped while it rendered (checked here too: the signal is queued)
        self.unsay("preview")
        done, self._preview_done = self._preview_done, None
        if done is not None:
            done(data is not None)
        if data is None:
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
        self._results_open = False
        self._sync_cat_bar()
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
        self.cat_tabs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
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
        h.addWidget(add, 0, Qt.AlignmentFlag.AlignVCenter)
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
        app = QApplication.instance()
        dpr = app.devicePixelRatio() if isinstance(app, QApplication) else 1.0
        pm = QPixmap(round(12 * dpr), round(12 * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
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
            self.toast(_("“{all}” is the built-in tab, pick another name", all=ALL), "warn")
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
        self.search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search.selectAll()

    def rename_sound(self, sid: str, new: str | None = None):
        """F2 on a pad (and the pad menu's Rename): just the name, without the Edit
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
            self.toast(_("“{all}” is the built-in tab, pick another name", all=ALL), "warn")
            return
        if not new or new == old or old not in self.cfg.categories:
            return
        if new.lower() in {c.lower() for c in self.cfg.categories if c != old}:
            self.toast(_("There's already a “{new}”.", new=html.escape(new)), "warn")
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
                         n, name=name)) != QMessageBox.StandardButton.Yes:
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
        a_ren = menu.addAction(icons.icon("edit"), _("Rename"))
        hk = self.cfg.category_hotkeys.get(name, "")
        a_hk = menu.addAction(icons.icon("keyboard"),
                              _("Random-sound hotkey: {hk} (change…)", hk=pretty_key(hk)) if hk
                              else _("Set a random-sound hotkey"))
        a_nohk = menu.addAction(icons.icon("trash"),
                               _("Clear the random-sound hotkey")) if hk else None
        a_rand = menu.addAction(icons.icon("play"), _("Play a random sound from it"))
        a_all = menu.addAction(icons.icon("next"), _("Play them all, in order"))
        a_shuf = menu.addAction(icons.icon("shuffle"), _("Play them all, shuffled"))
        a_exp = menu.addAction(icons.icon("folder"), _("Export as a sound pack"))
        cm = menu.addMenu(icons.icon("palette"), _("Colour"))
        # the same colour list as the bulk Colour menu: names, the current one ticked
        fill_colour_menu(cm, self.cfg.category_colors.get(name, ""),
                         lambda col: self.set_category_color(name, col), none=True)
        menu.addSeparator()
        a_prog = menu.addAction(icons.icon("apps"), _("Show this when a program is in front"))
        a_unprog = {menu.addAction(icons.icon("offline"),
                                  _("Stop showing this for {exe}", exe=exe)): exe
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
        """A category's menu → Show this when a program is in front"""
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
            self.toast(_("Opened your sounds folder"), "ok")
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

    def add_folder_dialog(self):
        """Add every sound in a folder (and its subfolders), as a drop of it would."""
        folder = QFileDialog.getExistingDirectory(self, _("Add sounds"), str(Path.home()))
        if folder:
            self.import_files(expand_dropped([folder]))

    def add_from_link(self):
        """A link already copied goes straight into the search box (its card shows);
        otherwise the box is focused for one to be pasted."""
        copied = QApplication.clipboard().text().strip()
        if ytdl.as_link(copied):
            self.search.setText(copied)
            self._show_link()
        else:
            self.toast(_("Paste a link into the search box"))
        self.search.setFocus()
        self.search.selectAll()

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
        copy_local = self.cfg.copy_local_sounds
        local_files = set(files)   # ZIP extraction adds temporary files later
        stop = self._import_stop

        def run():
            with tempfile.TemporaryDirectory(prefix="onionboard-zip-") as tmp:
                todo = list(files)
                for k, (z, names) in enumerate(zips.items()):
                    if stop.is_set():   # Stop: not unpacked, only counted down
                        for __ in names:
                            self.bridge.imported.emit(None, None, None)
                        continue
                    try:
                        res = backup.extract_loose(z, names, Path(tmp) / str(k))
                    except Exception as e:  # noqa: BLE001 - too big, no room, damaged
                        log.warning("can't unpack %s: %s", z, e)
                        # one message for the zip; the rest only count down
                        self.bridge.imported.emit(None, None, importreport.classify(z, e))
                        for __ in names[1:]:
                            self.bridge.imported.emit(None, None, None)
                        continue
                    for _n, dest, err in res:
                        if dest is None:
                            sk = importreport.classify(z, err)
                            sk.file = f"{Path(z).name} → {_n}"
                            self.bridge.imported.emit(None, None, sk)
                        else:
                            todo.append(str(dest))
                import_all(todo)

        def import_all(files):
            for i, shown in enumerate(files):
                if stop.is_set():   # Stop: the rest only count down, the ones in stay
                    self.bridge.imported.emit(None, None, None)
                    continue
                f = shown   # read through any folder link Windows won't follow
                try:
                    f = str(winpath.usable(shown))
                    fp = fingerprint(f)
                    if fp and fp in known:
                        if shown in extras:
                            self.bridge.imported.emit(None, None, None)   # already moved over
                            continue
                        raise importreport.AlreadyAdded(known[fp])
                    x = extras.get(shown)   # from another soundboard: named as it was there
                    meta, data = import_file(f, PAD_COLORS[(start + i) % len(PAD_COLORS)],
                                             name=x.name if x is not None else "",
                                             copy=copy_local or shown not in local_files
                                             or library.owns(Path(f)))
                    if x is not None:
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
                    self.bridge.imported.emit(meta, data, None)   # it's in there as ours
                except Exception as e:  # noqa: BLE001
                    log.warning("can't import %s: %s", f, e)
                    self.bridge.imported.emit(None, None, importreport.classify(shown, e))
        threading.Thread(target=run, daemon=True, name="import").start()
        busy.set_busy(self.btn_add, True)   # back in on_imported, when they're all in
        self._import_total += count
        self._import_progress()

    def _import_progress(self):
        """The import's toast while it runs: "Adding 3 of 12…", with a bar. Several
        files get a bigger card with Bun; closing it (✕) only hides it: the import goes
        on, its sounds keep showing up, and the finished card still comes."""
        total = self._import_total
        done = total - self._pending_imports
        text = (ngettext("Adding {count} sound…", "Adding {count} sounds…", total, count=total)
                if not done else _("Adding {done} of {total}…", done=done, total=total))
        if total <= 1:
            self.toast(text, "busy", 0, key="import")   # up until it's in, however slow
            return
        if self._import_card_shut:
            return
        text = "<b>{}</b><br>{}".format(text, _("Each sound shows up as soon as it's in. "
                                                 "Closing this doesn't stop it."))
        t = self.toast(text, "busy", 0, key="import", progress=(done, total),
                       action=(_("Stop"), self._stop_import),
                       picture=bunny.bunny_pixmap(44, dpr=self.devicePixelRatioF()))
        if t is not None and not t.property("import_card"):
            t.setProperty("import_card", True)
            t.card.btn_close.clicked.connect(self._shut_import_card)

    def _shut_import_card(self):
        if self._pending_imports > 0:
            self._import_card_shut = True

    def _stop_import(self):
        """The card's Stop: the file being read finishes, the rest are skipped; the
        sounds already in stay (the finished card's Undo takes them off too)."""
        if self._pending_imports > 0:
            usage.used("import-stopped")
            self._import_stop.set()
            self._import_card_shut = True

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
            if meta.duration < SHORT_SOUND_S:
                self._imported_short = True
            self._import_ids.append(meta.id)
            usage.used("add-files")
            usage.step(self.cfg, "added-sound")
        elif err:
            self._import_errors.append(err)
        if self._pending_imports > 0:
            if meta is not None and not self._import_pads.isActive():
                self._import_pads.start()   # on the board soon, with the next few
            self._import_progress()
            return
        self._import_pads.stop()
        self._pending_imports = 0
        self._import_card_shut = False
        self._import_stop.clear()
        self._save_now()
        self._rebuild_pads()
        self._fill_categories()   # categories and hotkeys from an Import from Soundpad
        self.register_hotkeys()
        n, self._imported_ok = self._imported_ok, 0
        short, self._imported_short = self._imported_short, False
        ids, self._import_ids = self._import_ids, []
        skipped, self._import_errors = self._import_errors, []
        self._import_total = 0
        busy.set_busy(self.btn_add, False)
        self.triggers.import_done()   # a trigger's sound that failed to import
        boards, self._ask_keep = self._ask_keep, []
        if boards and ids and not self._keep_imported(boards, ids):
            return
        if not n and not skipped:
            self.toast(_("Nothing new to add"), key="import")
            return
        text, kind = importreport.summary(n, skipped)
        if skipped:
            usage.used("import-skipped")
            action = (_("See why"), lambda: self._show_skipped(skipped))
        else:
            action = (_("Undo"), lambda: self.remove_sounds(ids))
        self.toast(text, kind, 8000 if skipped else 6000, key="import", action=action)
        self._flash_new(ids)
        if short:
            self.toast(_("A sound you added is very short, so it may be barely "
                         "heard."), "warn")

    def _keep_imported(self, boards: list[str], ids: list[str]) -> bool:
        """The installer's box brought another soundboard's sounds over without asking:
        ask now whether to keep them, so nobody has to delete a big board pad by pad.
        False: they're removed (Undo and Recently deleted still have them)."""
        text = (ngettext("We brought over <b>{n}</b> sound from {name}. Keep it?",
                         "We brought over <b>{n}</b> sounds from {name}. Keep them?",
                         len(ids), name=boards[0]) if len(boards) == 1 else
                ngettext("We brought over <b>{n}</b> sound from your other soundboards. "
                         "Keep it?",
                         "We brought over <b>{n}</b> sounds from your other soundboards. "
                         "Keep them?", len(ids)))
        box = QMessageBox(QMessageBox.Icon.Question, _("Keep your imported sounds?"), text,
                          QMessageBox.StandardButton.NoButton, self)
        # Bun, smug: got your board and its settings in one go
        box.setIconPixmap(bunny.bunny_pixmap(84, dpr=self.devicePixelRatioF(), smug=True))
        keep = box.addButton(_("Keep"), QMessageBox.ButtonRole.YesRole)
        remove = box.addButton(_("Remove"), QMessageBox.ButtonRole.NoRole)
        box.setInformativeText(_("Removed sounds come back with Undo, or later from Backup "
                                 "→ Recently deleted sounds."))
        box.setDefaultButton(keep)
        box.setEscapeButton(keep)   # closing it never deletes anything
        box.exec()
        kept = box.clickedButton() is not remove   # closed some other way: kept
        free_dialog(box)
        if not kept:
            self.remove_sounds(ids)
        return kept

    def _show_skipped(self, skipped):
        dlg = importreport.SkippedDialog(skipped, self)
        dlg.show()   # not modal: sounds keep playing

    def _flash_new(self, ids: list[str]):
        """The pads just added light up once (their hover glow), the first scrolled
        into view, so it's clear where they went."""
        pads = [self.pads[i] for i in ids if i in self.pads]
        if not pads:
            return
        self._pad_scroll.ensureWidgetVisible(pads[0])
        if not toastmod.animations_on():
            return
        for pad in pads:
            a = QVariantAnimation(pad)
            a.setDuration(900)
            a.setKeyValueAt(0.0, 0.0)
            a.setKeyValueAt(0.3, 1.0)
            a.setKeyValueAt(1.0, 0.0)
            a.valueChanged.connect(lambda v, pad=pad: pad.hover or pad._on_hover_k(v))
            a.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

    def on_clip(self, data, name) -> SoundMeta | None:
        """A clip recorded in the Radio or Apps tab (or with the mic) becomes a normal
        sound pad."""
        try:
            meta, data = save_clip(data, name, PAD_COLORS[len(self.cfg.sounds) % len(PAD_COLORS)])
        except Exception as e:  # noqa: BLE001
            log.exception("can't save clip")
            src = self.sender()
            if src is not None and hasattr(src, "clip_error"):
                src.clip_error = errors.plain(e)   # pyright: ignore[reportAttributeAccessIssue]  # the tab says so on its row (hasattr)
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
        self.toast(_("Added “{name}” ({duration:.1f}s) to Sounds: right-click it there "
                     "to rename or set a hotkey.",
                     name=html.escape(meta.name), duration=meta.duration), "ok")
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
                         playing_name=self._playing_name,
                         playing_picture=self._playing_picture)
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

    def _playing_picture(self) -> str:
        """The picture of the pad playing now ("" for none, or not a pad), for a
        recording of it."""
        sid = self.current
        st = self.engine.state(sid) if sid else None
        m = self.meta(sid) if st is not None and not st[1] else None
        return m.image if m is not None and m.image and Path(m.image).is_file() else ""

    def add_recording(self, data, name, picture: str = "") -> bool:
        """A mic recording becomes a pad: selected, scrolled to, and a toast says so.
        `picture`: the picture of the pad it was recorded from (copied onto it)."""
        meta = self.on_clip(data, name)
        if meta is None:
            return False
        if picture and thumbs.set_image(meta, picture):
            self._save_now()
            if meta.id in self.pads:
                self.pads[meta.id].update()
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
        self.toast(_("Added “{name}” ({duration:.1f}s) to Sounds: right-click it there "
                     "to rename or set a hotkey.",
                     name=html.escape(meta.name), duration=meta.duration), "ok")

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
        sort_icons = {"custom": "sort", "name": "rename", "newest": "history",
                      "plays": "star"}
        for key, name in self._sort_names().items():
            a = menu.addAction(name, lambda k=key: self.set_pad_sort(k))
            icons.set_icon(a, sort_icons[key], checked_color="accent")
            a.setCheckable(True)
            a.setChecked(self.cfg.pad_sort == key)
            a.setToolTip(tips[key])
            group.addAction(a)
        menu.addSeparator()
        views = QActionGroup(menu)
        for key, name, icon, tip in (
                ("grid", _("Pads"), "sounds", _("Cards, with pictures")),
                ("list", _("List"), "list", _("One line each: many more sounds on the screen"))):
            a = menu.addAction(name, lambda k=key: self.set_pad_view(k))
            icons.set_icon(a, icon, checked_color="accent")
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
        sl = QSlider(Qt.Orientation.Horizontal)
        sl.setRange(0, 200)
        sl.setSingleStep(5)
        sl.setPageStep(10)
        sl.setValue(round(m.volume * 100))
        sl.setFixedWidth(120)
        sl.setAccessibleName(_("Volume"))
        val = QLabel(f"{sl.value()}%")
        val.setObjectName("muted")
        steady_number(val, "200%")

        def moved(v: int):
            val.setText(f"{v}%")
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
        QToolTip.showText(QCursor.pos(), _("{name}: {pct}%", name=m.name,
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
        vol_before = m.volume
        menu.addAction(self._volume_action(menu, m))
        menu.addSeparator()
        a_edit = add(("edit",), _("Edit"), _("Name, colour, picture, volume, hotkey, "
                                              "timing and effects"))
        a_ren = add(("rename",), _("Rename"), _("Just the name (F2 on the pad does it too)"))
        a_hk_clear = None
        if m.hotkey:
            hk = menu.addMenu(icons.icon("keyboard"), _("Hotkey: {hotkey}",
                                                        hotkey=pretty_key(m.hotkey)))
            hk.setToolTipsVisible(True)
            a_hk = add(("keyboard",), _("Change"), _("Press a new key or combo for it"), hk)
            a_hk_clear = add(("trash",), _("Remove hotkey"), "", hk)
        else:
            a_hk = add(("keyboard",), _("Set hotkey"), _("A key or combo that plays it, even "
                                                          "in-game"))
        cats = menu.addMenu(icons.icon("tag"), _("Categories"))
        cat_acts = {}
        for c in self.cfg.categories:
            a = cats.addAction(icons.icon("tag", checked_color="accent"), c.replace("&", "&&"))
            a.setCheckable(True)
            a.setChecked(c in m.tags)
            cat_acts[a] = c
        if cat_acts:
            cats.addSeparator()
        a_newcat = cats.addAction(icons.icon("plus"), _("New category"))
        menu.addSeparator()
        a_dup = add(("copy",), _("Duplicate"), _("A second pad with the same sound, to give "
                                                 "its own effects or hotkey"))
        a_export = add(("download",), _("Export"), _("Save it as a file to share with friends"))
        a_src_open = a_src_copy = a_src_info = None
        if src := sourceinfo.shown(m):   # downloaded from YouTube, TikTok…
            site = sourceinfo.site_name(src)
            sm = menu.addMenu(icons.icon(sourceinfo.icon(src)), site)
            sm.setToolTipsVisible(True)
            a_src_open = add(("browser",), _("Open on {site}", site=site), src["link"], sm)
            a_src_copy = add(("copy",), _("Copy link"), src["link"], sm)
            a_src_info = add(("info",), _("Details"), _("Channel, upload date, length, views"),
                             sm)
        a_show = add(("folder",), _("Open file location"))
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
        elif act is not None and act == a_src_open:
            sourcedialog.open_link(src, self)
        elif act is not None and act == a_src_copy:
            sourcedialog.copy_link(src, self)
        elif act is not None and act == a_src_info:
            d = sourcedialog.SourceDialog(m, self)
            d.forgotten.connect(self._save_now)
            d.show()
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
        elif act == a_hk:
            self.set_sound_hotkey(sid)
        elif act is not None and act == a_hk_clear:
            self.set_sound_hotkey(sid, "")
        elif act == a_del:
            self.ask_remove([sid])

    def set_picture(self, sid: str, path: str):
        """Put a picture on a pad (an image dropped on it)."""
        m = self.meta(sid)
        if not m:
            return
        if not thumbs.set_image(m, path):
            self.tell(_("Couldn't use that picture"),
                      _("{name} isn't a picture this app can read.", name=Path(path).name),
                      "warn")
            return
        self._save_now()
        self.pads[sid].update()

    def _focus_sounds_page(self, _i: int):
        """Switched to Sounds with the focus left behind on another tab (a hidden clip
        editor): the page takes it, so its Ctrl+V works straight away. Not from the tab
        rail: going down it with the arrow keys, the focus stays there."""
        page = self.sounds_page
        fw = QApplication.focusWidget()
        if (own := self.focusWidget()) is not None and self.rail.isAncestorOf(own):
            return
        if self.tabs.currentWidget() is page and (fw is None or not page.isAncestorOf(fw)):
            page.setFocus(Qt.FocusReason.OtherFocusReason)

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
            self.toast(_("Nothing to paste: copy a picture first (in a browser: "
                         "right-click it → Copy image), then press Ctrl+V on a pad."), "warn")
            return
        done = [sid for sid in sids if (m := self.meta(sid)) and thumbs.set_image(m, img)]
        if not done:
            return
        self._save_now()
        for sid in done:
            self.pads[sid].update()
        m = self.meta(done[0])
        assert m is not None   # done holds only sounds with a meta
        self.toast(_("Picture pasted on “{name}”.",
                     name=html.escape(m.name)) if len(done) == 1
                   else ngettext("Picture pasted on {n} pad.",
                                 "Picture pasted on {n} pads.", len(done)), "ok")

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
        box = QMessageBox(QMessageBox.Icon.Question, _("Remove sound") if len(gone) == 1
                          else _("Remove sounds"), ask,
                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, self)
        box.button(QMessageBox.StandardButton.Yes).setText(_("Remove"))
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        answer = box.exec()
        free_dialog(box)
        if answer != QMessageBox.StandardButton.Yes:
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
        self._close_editors([m.id for m in gone])
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
        # "Removed X · Undo" for a while; after that they're in Recently deleted
        if len(gone) == 1:
            name = self.fontMetrics().elidedText(gone[0].name, Qt.TextElideMode.ElideRight, 260)
            text = _("Removed “{name}”", name=name)
        else:
            text = _("Removed {n} sounds", n=len(gone))
        t = self.toast(html.escape(text), "", UNDO_S * 1000, key=UNDO_KEY,
                       action=(_("Undo"), self.undo_remove), on_close=self._finish_removals)
        if t is not None:
            t.card.action.setToolTip(_("Put the sound back, exactly as it was. Later: Backup "
                                       "→ Recently deleted sounds"))

    def undo_remove(self):
        """Put the last removed sound(s) back where they were, with everything they had."""
        if not self._removed:
            return
        done, self._removed = self._removed, []
        self._put_back(done)
        # Ctrl+Z, not its button: its card goes too (after the sounds are back, so its
        # on_close finds their pack still in use)
        toastmod.close(self, UNDO_KEY)

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
        # let go of their audio first: Windows won't delete a mapped cache file
        # (soundboard.mapped) while an array still points into it
        done, self._removed = [(m, i) for m, i, _d in self._removed], []
        toastmod.close(self, UNDO_KEY)   # (its on_close comes back here: nothing left)
        for m, i in done:
            trash.put_sound(m, i)
        if done:
            self._label_bin()
        for pid in self._packs_removed:   # not undone: the pack is no longer kept
            if not any(m.pack == pid for m in self.cfg.sounds):
                backup.forget_pack(pid)
        self._packs_removed.clear()

    def _label_bin(self):
        """Keep the compatibility button's count; Library holds the visible action."""
        n = len(trash.items(trash.SOUND))
        self.btn_bin.setText(_("Recently deleted ({n})", n=n))
        self.btn_bin.hide()   # Recently deleted is in the Library menu

    def show_deleted(self):
        """Library → Recently deleted sounds"""
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
            self.say(
                _("<span style='color:{status}'>{hotkey} plays “{name}” now, it was the key for "
                  "{lost}.</span>",
                  status=theme.status('warn'), hotkey=html.escape(pretty_key(m.hotkey)),
                  name=html.escape(m.name), lost=html.escape(_(" and ").join(lost))),
                "warn", 8000, key="hotkey")
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
            lost = self._clear_dupe_hotkey(m)
            self._save_now()
            if sid in self.pads:
                self.pads[sid].update()
            if not lost:   # else its warning already says what the key plays now
                self.toast(_("✓ {combo} plays “{name}”",
                             combo=html.escape(combo), name=html.escape(m.name)) if combo
                           else _("Hotkey removed from “{name}”", name=html.escape(m.name)),
                           key="hotkey")
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
                msg = _("✓ {combo} plays a random “{name}” sound, it was the key for {lost}",
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
        """Edit sound beside the board, not over it: sounds, hotkeys and the other
        pads keep working. It's still a draft: nothing changes until Save, and Cancel
        (or Escape, or closing it) drops it. One window per sound: editing the same
        sound again raises the open one."""
        d = self._editors.get(sid)
        if d is not None and qt_valid(d):
            if tab == "effects":
                d.tabs.setCurrentIndex(1)
            d.showNormal() if d.isMinimized() else d.show()
            d.raise_()
            d.activateWindow()
            return d
        m = self.meta(sid)
        if m is None:
            return None
        d = self._editors[sid] = EditDialog(m, self.hotkeys, self.preview, self, tab=tab)
        d.hotkeys_changed.connect(self.register_hotkeys)
        d.source_forgotten.connect(self._save_now)
        d.finished.connect(lambda ok, sid=sid, d=d: self._edit_done(sid, d, ok))
        d.show()
        return d

    def _edit_done(self, sid: str, d: EditDialog, ok: int):
        """An Edit sound window closed: Save puts its draft on the sound (or a copy)."""
        if self._editors.get(sid) is d:
            del self._editors[sid]
        self.drop_preview()                        # a preview still rendering
        self.engine.stop(f"{sid}:preview")         # and the one playing, either kind
        self.engine.stop(f"{sid}~fx:preview")
        # the sound as it is now: gone (removed while the window was open: nothing to
        # save it onto), or the same sound in a new object (Undo put it back)
        m = self.meta(sid)
        try:
            if ok and m is not None and d.as_copy:
                self._save_copy(m, d)
            elif ok and m is not None:
                old_key = soundfx.key(m.fx)
                d.apply(m)
                self._clear_dupe_hotkey(m)
                self.engine.set_gain(sid, self.gain_for(m))
                if soundfx.key(m.fx) != old_key:
                    self._rerender(m)
                self._save_now()
                self.pads[sid].update()
                self.apply_filter(self.search.text())
        finally:
            # freed once its finished signal is over (deleting it inside that crashed)
            QTimer.singleShot(0, lambda: free_dialog(d))
        self.register_hotkeys()

    def _close_editors(self, sids):
        """The sounds are going: their open Edit sound windows close, unsaved (the
        Undo bar brings the sound back as it was)."""
        for sid in sids:
            d = self._editors.get(sid)
            if d is not None and qt_valid(d):
                d.reject()

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
        """The pad menu's Open file location: Explorer with the file picked
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
        """'Save a copy': the edits go onto a copy placed after the original."""
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
                == QMessageBox.StandardButton.Yes:
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
            self.toast(_("There are no sounds in it to export."), "warn")
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
            self.toast(_("Still exporting the last one, try again when it's done"), "warn")
            return
        self._exporting = True
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
        if err:
            self.tell(_("Export failed"),   # in place of the "Exporting…" card
                      _("Couldn't write {name}:\n{err}",
                        name=Path(path).name, err=errors.plain(err)), "error")
            return
        msg = (ngettext("Exported {n} sound to {name}.",
                        "Exported {n} sounds to {name}.",
                        n, name=html.escape(Path(path).name)))
        self.toast(msg, "ok")

    def show_packs(self):
        """The Free packs window (soundboard.packs): a pack it downloads is imported the
        way dropping its zip on the window is."""
        from soundboard.ui.packsdialog import PacksDialog
        dlg = PacksDialog(lambda path: self.import_files([str(path)]), self)
        dlg.exec()
        free_dialog(dlg)

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
                self._ask_keep.append(src.name)
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
            self.toast(html.escape(msg), "warn")
            return
        for e in ok:   # all in a category named after it too, so they're easy to find
            e.tags = [src.name, *(t for t in e.tags if t != src.name)]
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
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                                    ) != QMessageBox.StandardButton.Yes:
                return
        self.import_files([e.path for e in ok], {e.path: e for e in ok})

    def import_package(self, path: str):
        """Add the sounds from a backup / sound pack (ones already here are skipped).
        A full backup's settings are only applied if the user says so."""
        # reading a big zip takes a moment
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            pkg = backup.read(path)
        except backup.BackupError as e:
            QApplication.restoreOverrideCursor()
            errors.warn(self, _("Can't import"), e)
            return
        except Exception as e:  # noqa: BLE001 - a damaged or odd file, never a crash
            QApplication.restoreOverrideCursor()
            log.warning("couldn't read %s", path, exc_info=True)
            self.tell(_("Can't import"),
                      _("{name} is damaged or in a format Onion Board can't read ({e}).",
                        name=Path(path).name, e=errors.plain(e)), "error")
            return
        QApplication.restoreOverrideCursor()
        use_settings = False
        if pkg.settings:
            box = QMessageBox(QMessageBox.Icon.Question, _("Import backup"),
                              ngettext("{name} has {n} sound and the settings they were saved "
                                       "with (theme, hotkeys, overlay, voice effects…).\n\nUse "
                                       "its settings too? Your devices stay as they are.",
                                       "{name} has {n} sounds and the settings they were saved "
                                       "with (theme, hotkeys, overlay, voice effects…).\n\nUse "
                                       "its settings too? Your devices stay as they are.",
                                       len(pkg.sounds), name=Path(path).name),
                              QMessageBox.StandardButton.NoButton, self)
            yes = box.addButton(_("Sounds and settings"), QMessageBox.ButtonRole.YesRole)
            box.addButton(_("Just the sounds"), QMessageBox.ButtonRole.NoRole)
            cancel = box.addButton(QMessageBox.StandardButton.Cancel)
            box.exec()
            clicked = box.clickedButton()
            free_dialog(box)
            if clicked is cancel:
                return
            use_settings = clicked is yes
        if use_settings and pkg.settings:   # (only asked when there are some)
            self._apply_backup_settings(pkg.settings)
        if not pkg.sounds:
            return
        # only what's on the board: a sound removed a moment ago (still undo-able) must
        # come back from its backup, or deleting all then restoring leaves nothing
        known = {m.fingerprint for m in self.cfg.sounds if m.fingerprint}
        have = {(m.pack, m.pack_item) for m in self.cfg.sounds if m.pack}
        start = len(self.cfg.sounds)
        self.toast(ngettext("Importing {n} sound…", "Importing {n} sounds…", len(pkg.sounds)))

        def run():
            try:
                if pkg.is_pack:   # kept, so it can be reset or removed in one go later
                    backup.keep_pack(pkg)
                res = backup.install(
                    pkg, known, lambda i: PAD_COLORS[(start + i) % len(PAD_COLORS)], have)
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
            self.tell(_("Settings imported"),
                      _("Done. Hotkeys and the theme apply now; everything else "
                        "the next time Onion Board starts."), "ok")

    def _take_pack_hotkeys(self, clashes: list[tuple[str, SoundMeta, SoundMeta]],
                           name: str) -> bool:
        """Some sounds in a pack use hotkeys sounds here already have: give those keys
        to the pack's sounds? No (the default, and Esc) keeps them on yours."""
        lines = "\n".join(f"{pretty_key(k)}: {old.name} → {new.name}"
                          for k, old, new in clashes[:10])
        if len(clashes) > 10:
            lines += "\n…"
        box = QMessageBox(QMessageBox.Icon.Question, _("Same hotkeys"),
                          ngettext("A sound in “{name}” uses a hotkey one of your sounds "
                                   "already has:\n\n{lines}\n\nGive it to the new sound?",
                                   "{n} sounds in “{name}” use hotkeys your sounds already "
                                   "have:\n\n{lines}\n\nGive them to the new sounds?",
                                   len(clashes), name=name, lines=lines),
                          QMessageBox.StandardButton.NoButton, self)
        yes = box.addButton(_("Use the new ones"), QMessageBox.ButtonRole.YesRole)
        keep = box.addButton(_("Keep mine"), QMessageBox.ButtonRole.NoRole)
        box.setDefaultButton(keep)
        box.setEscapeButton(keep)   # closing it never deletes anything
        box.setEscapeButton(keep)
        box.exec()
        clicked = box.clickedButton()
        free_dialog(box)
        return clicked is yes

    def _on_unpacked(self, res, pkg, err: str):
        self._update_status()
        if res is None:
            self.tell(_("Import failed"), err, "error")
            return
        self._settle_hotkeys(res.sounds + pkg.restored, self._pack_name(pkg))
        from soundboard.library import merge_tags
        order = [ps.folder for ps in pkg.sounds]
        for m in pkg.restored + res.sounds:
            # "memes" goes into the "Memes" already here (and a new one gets a tab)
            m.tags = merge_tags(m.tags, self.cfg.categories)
        for m in res.sounds:
            self.cfg.sounds.insert(self._pack_spot(m, order), m)
        merge_tags(pkg.categories, self.cfg.categories)   # a full backup's empty ones too
        for m in pkg.restored:
            self.engine.set_gain(m.id, self.gain_for(m))
        self._save_now()
        self._rebuild_pads()
        self._fill_categories()
        self._load_all()
        self.register_hotkeys()
        n = len(res.sounds)
        if pkg.restored:   # Backup → My sound packs → Reset to how it came
            msg = _("“{name}” is back how it came", name=self._pack_name(pkg))
            if n:
                msg += ngettext(" ({n} removed sound put back)",
                                " ({n} removed sounds put back)", n)
        elif res.skipped:
            msg = ngettext("Imported {n} sound ({skipped} already in your library)",
                           "Imported {n} sounds ({skipped} already in your library)", n,
                           skipped=len(res.skipped))
        else:
            msg = ngettext("Imported {n} sound", "Imported {n} sounds", n)
        self.toast(msg, "ok" if n or pkg.restored else "")
        if res.failed:
            skipped = [importreport.Skipped(line, "", "unreadable") for line in res.failed]
            self.toast(html.escape(_("Some sounds weren't imported")), "warn", 10000,
                       action=(_("See why"), lambda: self._show_skipped(skipped)))

    def _settle_hotkeys(self, incoming: list[SoundMeta], name: str):
        """Hotkeys coming in with a pack that are already in use. Ones a sound here has:
        ask whether the pack's sounds take them. App-wide keys, category keys and
        push-to-talk always stay where they are. Whatever's still taken is cleared on
        the incoming sound (and a key twice in the pack goes to the first)."""
        taken = {getattr(self.cfg, a) for a, *__ in HOTKEY_ACTIONS if getattr(self.cfg, a)}
        taken |= {k for k in self.cfg.category_hotkeys.values() if k}
        if self.cfg.ptt_key:   # pressed by us for the game: never a sound's hotkey
            taken.add(self.cfg.ptt_key)
        ids = {m.id for m in incoming}
        mine = {o.hotkey: o for o in self.cfg.sounds if o.hotkey and o.id not in ids}
        clashes, seen = [], set(taken)
        for m in incoming:
            if m.hotkey and m.hotkey not in seen and m.hotkey in mine:
                clashes.append((m.hotkey, mine[m.hotkey], m))
            seen.add(m.hotkey)
        if clashes and self._take_pack_hotkeys(clashes, name):
            for _key, old, _new in clashes:
                old.hotkey = ""   # the pack's sound gets it instead
        taken |= {o.hotkey for o in self.cfg.sounds if o.hotkey and o.id not in ids}
        for m in incoming:
            if m.hotkey in taken:
                m.hotkey = ""   # the sounds already here keep theirs
            taken.add(m.hotkey)

    def _pack_name(self, pkg) -> str:
        return backup.packs().get(pkg.pack_id) or Path(pkg.path).name

    def _pack_spot(self, m: SoundMeta, order: list[str]) -> int:
        """Where a sound coming back into its pack goes: after the pack's sound before it
        (or before the one after it) on the board; anything else goes on the end."""
        if not m.pack or m.pack_item not in order:
            return len(self.cfg.sounds)
        at = {o.pack_item: i for i, o in enumerate(self.cfg.sounds) if o.pack == m.pack}
        k = order.index(m.pack_item)
        for f in reversed(order[:k]):
            if f in at:
                return at[f] + 1
        for f in order[k + 1:]:
            if f in at:
                return at[f]
        return len(self.cfg.sounds)

    def _fill_packs_menu(self, menu: QMenu):
        """Backup → My sound packs: each pack imported, to reset or remove in one go."""
        menu.clear()
        for pid, name in backup.packs().items():
            n = sum(m.pack == pid for m in self.cfg.sounds)
            sub = menu.addMenu(ngettext("{name} ({n} sound)", "{name} ({n} sounds)", n,
                                        name=name.replace("&", "&&")))   # not a shortcut
            sub.addAction(_("Reset to how it came"), lambda pid=pid: self.reset_pack(pid))
            act = sub.addAction(_("Remove from the board"), lambda pid=pid: self.remove_pack(pid))
            act.setEnabled(bool(n))

    def reset_pack(self, pid: str, ask: bool = True):
        """Put a sound pack back how it came: its sounds' names, hotkeys, volume,
        effects, categories and pictures, and its removed sounds come back."""
        try:
            pkg = backup.read_pack(pid)
        except backup.BackupError as e:
            errors.warn(self, _("Can't reset the sound pack"), e)
            return
        name = self._pack_name(pkg)
        if ask and QMessageBox.question(
                self, _("Reset sound pack"),
                _("Put the sounds from “{name}” back how they came?\n\nChanges you made to "
                  "them (names, hotkeys, volume, effects, pictures…) are undone, and ones you "
                  "removed come back. Your other sounds aren't touched.", name=name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
                ) != QMessageBox.StandardButton.Yes:
            return
        on_board = {}
        for m in self.cfg.sounds:
            if m.pack == pid:
                on_board.setdefault(m.pack_item, m)
        fx_before = {m.id: soundfx.key(m.fx) for m in on_board.values()}
        try:
            pkg.restored = backup.reset_sounds(pkg, on_board)
        except (OSError, backup.BackupError) as e:
            errors.warn(self, _("Can't reset the sound pack"), e)
            return
        for m in pkg.restored:
            if soundfx.key(m.fx) != fx_before[m.id]:
                self._rerender(m)
            if p := self.pads.get(m.id):
                p.update()
        missing = [ps for ps in pkg.sounds if ps.folder not in on_board]
        if not missing:
            self._on_unpacked(backup.Imported(), pkg, "")
            return
        full = list(pkg.sounds)
        pkg.sounds = missing
        start = len(self.cfg.sounds)

        def run():
            try:
                res = backup.install(
                    pkg, set(), lambda i: PAD_COLORS[(start + i) % len(PAD_COLORS)])
            except Exception as e:  # noqa: BLE001
                log.exception("reset of the sound pack %s failed", pid)
                res, err = None, errors.plain(e)
            else:
                err = ""
            pkg.sounds = full   # for _pack_spot's order
            self.bridge.unpacked.emit(res, pkg, err)
        threading.Thread(target=run, daemon=True, name="reset-pack").start()

    def remove_pack(self, pid: str, ask: bool = True):
        """Take every sound of a sound pack off the board (one Undo brings them back);
        once the Undo bar is gone, the pack is no longer kept."""
        gone = [m.id for m in self.cfg.sounds if m.pack == pid]
        if not gone:
            return
        name = backup.packs().get(pid, pid)
        if ask and QMessageBox.question(
                self, _("Remove sound pack"),
                ngettext("Remove the {n} sound from “{name}”?",
                         "Remove the {n} sounds from “{name}”?", len(gone), name=name)
                + "\n\n" + _("You can undo this, or bring them back from Recently deleted."),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
                ) != QMessageBox.StandardButton.Yes:
            return
        self.remove_sounds(gone)
        self._packs_removed.add(pid)

    # ------------------------------------------------------------------ tray
    def _init_tray(self):
        """The tray icon: closing the window keeps the app (and its hotkeys) running
        there, unless turned off in Settings. No tray (some desktops): close quits."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        t = self.tray = QSystemTrayIcon(glow_icon(theme.T["accent"], theme.T["accent2"], 0.0), self)
        t.setToolTip(self.title)
        menu = QMenu(self)
        icons.set_icon(menu.addAction(_("Open Onion Board"), self.show_from_tray), "sounds")
        icons.set_icon(menu.addAction(_("Stop all sounds"), self.stop_all), "stop")
        menu.addSeparator()
        # the Discord opens in the browser (feedback.py); Send feedback asks first
        from soundboard import feedback
        icons.set_icon(menu.addAction(_("Join the Discord"), lambda: self._open_page(
            feedback.DISCORD_URL)), "speech")
        icons.set_icon(menu.addAction(_("Send feedback"), self.ask_feedback), "edit")
        menu.addSeparator()
        icons.set_icon(menu.addAction(_("Quit"), self.quit_app), "stop")
        t.setContextMenu(menu)
        t.activated.connect(self._on_tray)
        t.messageClicked.connect(self.show_from_tray)
        t.show()
        QApplication.setQuitOnLastWindowClosed(False)

    def ask_feedback(self):
        """*Send feedback*: "What would you improve?" (ui/feedbackdialog.py)."""
        from soundboard.ui import feedbackdialog
        self.show_from_tray()
        self.feedback_box = feedbackdialog.ask(self.cfg, self)

    def _open_page(self, url: str):
        busy.open_url(url, window=self, failed=_("Couldn't open your browser. The page is"))

    def _on_tray(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
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
        exitwatch.closed_by_windows()   # ended before the quit finishes: not a crash

    def apply_remote(self) -> str:
        """Start / stop the local control API to match the settings; "" or an error."""
        err = remote.apply(self, self.remote)
        if err:
            self.say(_("<span style='color:{status}'>Remote control is off: "
                       "{err}.</span>",
                       status=theme.status('warn'), err=html.escape(err)), "warn")
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
        if addon is None and saved and old is not None:   # (saved: only with an old one)
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
        """Uninstall a remote add-on (Settings' *Remove Onion Pocket*): the running
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
        # off, a voice changer decides whether your mic still goes out: the switch says so
        # (tied to the button: a window closing meanwhile drops it)
        QTimer.singleShot(0, self.btn_air, lambda: self.set_sending(self.btn_air.isChecked()))

    def _remember_usage(self):   # features used and time open, for the next daily count
        usage.open_tick(self.cfg)
        usage.remember(self.cfg)

    def tick_usage(self):   # every usage.OPEN_TICK_S: how long the app has been open
        usage.open_tick(self.cfg)

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
            if self.release is None or self.release.version != rel.version:
                self._update_err, self._update_fails = "", 0   # a new version: a fresh start
            self.release = rel
            self._show_update_state()
            if self.tray is not None and not self.isVisible():
                self.tray.showMessage(
                    "Onion Board", _("Important fix: {fix}", fix=rel.urgent) if rel.urgent
                    else _("Version {version} is out.", version=rel.version),
                    QSystemTrayIcon.MessageIcon.Warning if rel.urgent
                    else QSystemTrayIcon.MessageIcon.Information,
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
        if (rel is not None and rel.urgent
                and f"board {rel.version}" not in self._urgent_hidden):
            # the same steps as the update card (its progress shows under the words)
            button = (_("Cancel") if self._downloading
                      else _("Restart to update") if self._update_file is not None
                      and not self._update_err
                      else _("Try again") if self._update_err
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
        culprits = self.raw_watch.update(apps, self.engine.direct_apps(),
                                        time.monotonic() if now is None else now)
        if [a.exe for a in culprits] != before:
            log.info("recording the mic without Onion Board: %s",
                     [a.exe for a in culprits] or "nobody")
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
        key, text, button = now
        self.urgent_lbl.setText(text)
        self.urgent_btn.setText(button)
        self.urgent_btn.setVisible(bool(button))   # a warning with nothing to click
        # Onion Board's own fix: the update card's progress and words, under the reason
        board = key.startswith("board") and (self._downloading or bool(self._update_err))
        self.urgent_prog.setVisible(board and self._downloading)
        self.urgent_prog.setValue(self._update_pct())
        self.urgent_sub.setVisible(board)
        if board:
            state = self._update_words()   # failed: the reason (Try again is beside it)
            self.urgent_sub.setText(state[3] if state[0] == "failed"
                                    else " · ".join(filter(None, (state[1], state[2]))))
        self.urgent_bar.show()
        if self._setup_state == "offer":
            self._hide_setup()   # one bar at a time: the warning beats "Set up for it?"

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
            if self._downloading:
                self.cancel_update()
            elif self._update_file is not None and not self._update_err:
                self.install_update()
            elif updates.can_install() and self.release is not None and self.release.asset_url:
                self.download_update()
            else:
                self.show_update()
            return
        # Onion Watch: its tab does the updating (and shows how it's going)
        self.tabs.setCurrentWidget(self.triggers)
        if (isinstance(self.triggers, TriggersTab) and self.triggers.offer is not None
                and not self.triggers._busy):
            self.triggers.get()
        self.watch_offer = None
        self._show_urgent()

    def show_update(self):
        """The update pill was clicked: what's new, and what can be done about it."""
        if self._update_file is not None:
            self.install_update()
            return
        rel = self.release
        if rel is None or self._downloading:
            return
        from soundboard import __version__
        box = QMessageBox(QMessageBox.Icon.Warning if rel.urgent else QMessageBox.Icon.Information,
                          _("Important fix available") if rel.urgent else _("Update available"),
                          _("Onion Board {version} is out (you have {current}).",
                            version=rel.version, current=__version__),
                          QMessageBox.StandardButton.NoButton, self)
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
                            QMessageBox.ButtonRole.AcceptRole)
        page = (box.addButton(_("Release page"), QMessageBox.ButtonRole.HelpRole)
                if installable else None)
        # an urgent fix can't be skipped for good, only put off
        skip = (None if rel.urgent
                else box.addButton(_("Skip this version"), QMessageBox.ButtonRole.DestructiveRole))
        box.addButton(_("Later"), QMessageBox.ButtonRole.RejectRole)
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
            self._show_update_state()

    # ---- Onion Board's own update: one state, shown on the card, the urgent bar and
    # in Settings > Updates in the same words
    def _update_pct(self) -> int:
        done, total = self._update_got
        return min(done * 100 // total, 100) if total else 0

    def _update_words(self) -> tuple[str, str, str, str]:
        """(state, title, hint, tip) for the update as it is now; state "" when
        there's none."""
        rel = self.release
        if rel is None:
            return "", "", "", ""
        if self._downloading:
            done, total = self._update_got
            mb = 1024 * 1024
            hint = (_("{done} of {total} MB", done=done // mb, total=max(1, round(total / mb)))
                    if total else _("{done} MB", done=done // mb))
            return ("downloading", _("Downloading {pct}%", pct=self._update_pct()), hint,
                    _("Downloading Onion Board {version}: click to see how far it is, "
                      "or to cancel.", version=rel.version))
        if self._update_err:
            return ("failed", _("Couldn't update"), _("Click to try again"),
                    _("Updating to Onion Board {version} didn't work: {rstrip}.",
                      version=rel.version, rstrip=self._update_err.rstrip(".")))
        if self._update_file is not None:
            return ("ready", _("Restart to update"), "",
                    _("Onion Board {version} is downloaded, click to install it",
                      version=rel.version))
        return ("available", _("Update to {version}", version=rel.version), "",
                _("Onion Board {version} is out, click for details", version=rel.version))

    def update_status(self) -> str:
        """The update's state in one line (Settings > Updates): the card's words."""
        state, title, hint, tip = self._update_words()
        if state == "failed":
            return tip   # (with the reason)
        return " · ".join(filter(None, (title, hint)))

    def _show_update_state(self):
        """The card (and the urgent bar, Settings, a Downloading box) say where the
        update is."""
        state, title, hint, tip = self._update_words()
        if not state:
            self.btn_update.hide()
        else:
            self.btn_update.set_state(state, title, hint, tip,
                                      pct=self._update_pct() if state == "downloading" else None,
                                      copy=state == "failed" and self._update_fails >= 2)
            self.btn_update.show()
        box = self._update_box
        if box is not None and qt_valid(box):
            box.setText(self._update_box_text())
        self._show_urgent()
        self.update_state.emit()

    def _update_clicked(self):
        """The update card: the next step from where it is."""
        if self._downloading:
            self._update_info()
        elif self._update_err:
            self.download_update()   # "Couldn't update, try again"
        else:
            self.show_update()

    def _update_box_text(self) -> str:
        rel = self.release
        done, total = self._update_got
        mb = 1024 * 1024
        if total:
            return _("Downloading Onion Board {version}: {done} of {total} MB ({pct}%).",
                     version=rel.version if rel else "", done=done // mb,
                     total=max(1, round(total / mb)), pct=self._update_pct())
        return _("Downloading Onion Board {version}: {done} MB so far.",
                 version=rel.version if rel else "", done=done // mb)

    def _update_info(self):
        """Clicked while it downloads: how far it is, and a way to stop it."""
        if self._update_box is not None or self.release is None:
            return   # (never a second one)
        box = QMessageBox(QMessageBox.Icon.Information, _("Downloading the update"),
                          self._update_box_text(), QMessageBox.StandardButton.NoButton, self)
        box.setInformativeText(_("You can keep using Onion Board meanwhile. When it's done, "
                                 "the button says Restart to update."))
        stop = box.addButton(_("Cancel download"), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(_("Keep going"), QMessageBox.ButtonRole.RejectRole)
        self._update_box = box
        box.exec()
        clicked = box.clickedButton()
        self._update_box = None
        free_dialog(box)
        if clicked is stop and self._downloading:
            self.cancel_update()

    def cancel_update(self):
        """Stop the download (updates.download checks between chunks)."""
        if self._downloading:
            self._update_cancel = True

    def _copy_update_error(self):
        """Copy error: what went wrong, where, for the user to send to the developer."""
        usage.used("update-copy-error")
        QApplication.clipboard().setText(self._update_detail or self._update_err)
        self.toast(_("Error details copied: paste them into a message to the developer."),
                   "ok")

    def _update_report(self, rel, err: str, trace: str = "", step: str = "download") -> str:
        """Copy error's text: everything needed to find the cause, nothing private
        beyond what the error itself says."""
        import platform
        from datetime import UTC, datetime

        from soundboard import __version__
        done, total = self._update_got
        lines = [
            f"Onion Board update failed ({step}), try {self._update_fails + 1}",
            f"From {__version__} to {rel.version}",
            f"Windows: {platform.platform()}  frozen: {bool(getattr(sys, 'frozen', False))}",
            f"Time (UTC): {datetime.now(UTC):%Y-%m-%d %H:%M:%S}",
            f"URL: {rel.asset_url}",
            f"File: {updates.installer_path(rel)}",
            f"Got: {done} of {total or rel.size or '?'} bytes",
            f"Error: {err}",
        ]
        if trace:
            lines += ["", trace.strip()]
        return "\n".join(lines)

    def download_update(self):
        """Fetch the new version's installer on a thread (updates.download)."""
        rel = self.release
        if rel is None or self._downloading:
            return
        if not net.allowed(updates.FEATURE):   # switched off since it was found
            self.toast(html.escape(net.off_message(updates.FEATURE)), "warn")
            return
        self._downloading = True
        self._update_cancel = False
        self._update_err = ""
        self._update_got = (0, rel.size or 0)
        netlog.cause(updates.FEATURE, f"You clicked to download Onion Board {rel.version}")
        usage.maybe_send(self.cfg, event=usage.update_event(rel.version))
        self._show_update_state()
        last = [-1]

        def progress(done, total):
            pct = min(done * 100 // total, 100) if total else done // (1024 * 1024)
            if pct != last[0]:
                last[0] = pct
                self.bridge.update_progress.emit(done, total)

        def run():
            import traceback
            try:
                path = updates.download(rel, progress,
                                        lambda: self._shut_down or self._update_cancel)
                self.bridge.update_ready.emit(path, "")
            except updates.UpdateError as e:
                self._update_detail_next = traceback.format_exc(limit=8)
                self.bridge.update_ready.emit(None, errors.plain(e))
            except Exception as e:  # noqa: BLE001 - never leave the card stuck
                log.exception("update download failed")
                self._update_detail_next = traceback.format_exc(limit=8)
                self.bridge.update_ready.emit(None, errors.plain(e))
        self._update_detail_next = ""
        threading.Thread(target=run, daemon=True, name="update-download").start()

    def _on_update_progress(self, done, total):
        if self._downloading and qt_valid(self):
            self._update_got = (int(done), int(total or 0))
            self._show_update_state()

    def _on_update_ready(self, path, err: str):
        if not qt_valid(self) or self._shut_down:
            return
        self._downloading = False
        box, self._update_box = self._update_box, None
        if box is not None and qt_valid(box):
            box.reject()   # the Downloading box: done, one way or the other
        rel = self.release
        if rel is None:
            return
        if path is None and self._update_cancel:   # Cancel: back to "Update to …"
            self._update_cancel = False
            usage.used("update-cancelled")
            self._update_got = (0, 0)
            self._show_update_state()
            return
        if path is None:
            self._update_detail = self._update_report(rel, err,
                                                      getattr(self, "_update_detail_next", ""))
            self._update_fails += 1
            self._update_err = errors.plain(err) or _("the download failed")
            usage.used("update-download-failed")
            self._show_update_state()
            url = rel.url
            self.tell(_("Couldn't update"),
                      _("Onion Board {version} couldn't be downloaded: {rstrip}.",
                        version=rel.version, rstrip=errors.plain(err).rstrip('.')), "error",
                      action=(_("Open the download page"),
                              lambda: QDesktopServices.openUrl(QUrl(url))))
            return
        self._update_file = path
        self._update_err, self._update_fails = "", 0
        self._show_update_state()
        if self.tray is not None and not self.isVisible():
            # hidden in the tray, maybe mid-game: don't pop a question, just say so
            self.tray.showMessage("Onion Board", _("Version {version} is ready to install: "
                                                   "open Onion Board and click Restart to "
                                                   "update.", version=rel.version),
                                  QSystemTrayIcon.MessageIcon.Information, 8000)
            return
        if QApplication.activeModalWidget() is not None:
            return   # something else is open: the card says Restart to update
        self.install_update()

    def install_update(self):
        """Ask, then close the app and let the downloaded installer replace it (it
        opens the app again when it's done)."""
        rel, path = self.release, self._update_file
        if rel is None or path is None:
            return
        box = QMessageBox(QMessageBox.Icon.Question, _("Install the update"),
                          _("Onion Board {version} is ready. Restart now to install it?",
                            version=rel.version),
                          QMessageBox.StandardButton.NoButton, self)
        box.setInformativeText(_("Onion Board closes, installs the new version and opens again "
                                 "by itself, usually within a minute. Sounds that are playing "
                                 "stop."))
        now = box.addButton(_("Restart now"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(_("Later"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        free_dialog(box)
        if clicked is not now:
            usage.used("update-later")
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
            import traceback
            self._update_detail = self._update_report(rel, errors.plain(e),
                                                      traceback.format_exc(limit=8), "install")
            self._update_fails += 1
            self._update_err = errors.plain(e)
            usage.used("update-install-failed")
            self._show_update_state()   # "Couldn't update", click to try again
            self.tell(_("Couldn't update"),
                      _("The installer couldn't be started ({e}). You can download it "
                        "from the release page instead.", e=errors.plain(e)), "error",
                      action=(_("Open the download page"),
                              lambda: QDesktopServices.openUrl(QUrl(updates.RELEASES))))
            return
        exitwatch.closed_by_windows()   # the installer closes us if the quit is slow
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

    def _go_tab(self, n: int, absolute: bool = False):
        """The n-th tab on the rail (`absolute`), or the one n steps from this one."""
        shown = [b for b in self.rail.buttons if b.isVisible()]
        if not shown:
            return
        usage.used("tab-keys")
        if absolute:
            if n < len(shown):
                shown[n].click()
            return
        cur = next((k for k, b in enumerate(shown) if b.index == self.tabs.currentIndex()), 0)
        shown[(cur + n) % len(shown)].click()

    def show_whats_new(self):
        """The header's version, clicked: the newest release's notes, any time."""
        from soundboard.ui import whatsnew
        if not whatsnew.NOTES:
            return
        dlg = whatsnew.WhatsNewDialog(self, [whatsnew.NOTES[0]])
        dlg.exec()
        page = dlg.page
        free_dialog(dlg)
        if page:
            self.open_settings(page)

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
        url = f"https://github.com/{updates.REPO}/releases/tag/v{__version__}"
        self.toast(_("Onion Board is up to date: version {version}.", version=__version__),
                   "ok", 10000,
                   action=(_("What's new"), lambda: QDesktopServices.openUrl(QUrl(url))))

    def _update_failed(self, pending: str):
        from soundboard import __version__
        log.warning("the update to %s didn't finish (still %s)", pending, __version__)
        usage.used("update-didnt-finish")
        box = QMessageBox(QMessageBox.Icon.Warning, _("The update didn't finish"),
                          _("Onion Board {pending} wasn't installed; this is still {version}. "
                            "You can download it from its page and run it yourself.",
                            pending=pending, version=__version__),
                          QMessageBox.StandardButton.NoButton, self)
        page = box.addButton(_("Open the download page"), QMessageBox.ButtonRole.AcceptRole)
        logb = (box.addButton(_("Show the install log"), QMessageBox.ButtonRole.HelpRole)
                if updates.INSTALL_LOG.is_file() else None)
        box.addButton(_("Close"), QMessageBox.ButtonRole.RejectRole)
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
            self.say(_("<span style='color:{status}'>Sounds only: your mic isn't "
                       "sent, so nobody (including you) hears it.</span>",
                       status=theme.status('warn')), "warn", key="sounds-only")

    # ------------------------------------------------------------------ tick
    # The window's visibility sets the UI timer's pace: 30/s for the meters and
    # visualisers while it's on screen, TICK_BG_MS while it's on screen behind another
    # program (a game: the meters still move, a third as often), TICK_IDLE_MS while it's
    # hidden in the tray or minimised (nothing to paint, but push-to-talk, the stream
    # watchdog must go on). Qt tells us through these three
    # events and applicationStateChanged.
    def showEvent(self, ev):
        shellicon.on_show(self)   # the Jump List icon, before the taskbar button exists
        shellicon.paint_background(self, theme.T["bg"])
        super().showEvent(ev)
        self._set_tick_rate()
        note, self._pending_note = getattr(self, "_pending_note", None), None
        if note:   # held back while the window was in the tray (see __init__)
            QTimer.singleShot(400, lambda: self.tell(
                _("Settings were restored"), note, "warn", 20000))
        later, self._whats_new_later = getattr(self, "_whats_new_later", None), None
        if later is not None:   # held back while the window was in the tray
            QTimer.singleShot(700, lambda: self.whats_new(later))
        # an older mic part: its update is offered a moment after the window opens
        QTimer.singleShot(MIC_OFFER_MS, self, self._offer_mic_update)

    def nativeEvent(self, event_type, message):
        # every Windows message passes here: keep it a few attribute reads. The handle
        # can exist before __init__ has made the taskbar buttons
        tb = getattr(self, "thumbbar", None)
        if tb is not None and tb.native_event(message):
            return True, 0
        return super().nativeEvent(event_type, message)

    def hideEvent(self, ev):
        super().hideEvent(ev)
        self._set_tick_rate()

    def changeEvent(self, ev):
        super().changeEvent(ev)
        if ev.type() == QEvent.Type.WindowStateChange:
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
            if self.timer.interval() != pace and not self._shut_down:
                self.timer.start(pace)

    def _busy(self, playing) -> bool:
        """Something on screen moves with the tick: a sound playing (not paused), the
        radio, a meter or the mic level still showing."""
        e = self.engine
        return (any(not paused for _p, paused in playing.values())
                or self.radio.is_active() or bool(self._queue) or bool(e.aux)
                or max(e.level_play, e.level_main,
                       e.level_mic if e.mic_stream is not None else 0.0) > LEVEL_QUIET)

    def _set_tick_rate(self, *__):
        live = self.isVisible() and not self.isMinimized()
        was, self._ui_live = self._ui_live, live
        # the mic-check banner pulses only while it can be seen, in front
        self._pulse.set_live(live and appstate.active())
        pace = self._tick_pace()
        if (live == was and self.timer.interval() == pace) or getattr(self, "_shut_down", False):
            return
        self.timer.start(pace)
        if not live:   # a level frozen mid-flight would show as stuck on the next show
            self.out_meter.set_level(0.0)
            self.mic_meter.set_level(0.0)
            if not self.isVisible():   # to the tray: the pads' pictures are made again
                thumbs.trim()          # from their small files when it's back

    def tick(self):
        if self._shut_down:   # a tick already queued when the window shut down
            return
        e = self.engine
        now = time.monotonic()
        self._tick_n += 1
        if self._tick_n % max(1, 1000 // self.timer.interval()) == 0:   # about once a second
            if self.cfg.route == "mic":
                self._follow_mic_effect()
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
        # the taskbar preview's Pause button turns into Play while all of it is paused
        # (a station Pause stopped counts as paused, until anything plays again)
        if live or self.radio.is_active():
            self._radio_paused = None
        self.thumbbar.set_paused(not live and not self.radio.is_active() and (
            self._radio_paused is not None or any(
                paused for sid, (_p, paused) in playing.items()
                if sid in self._meta or sid == LINK_ID)))
        self._tick_busy = self._busy(playing)
        pace = self._tick_pace()
        if self.timer.interval() != pace:
            self.timer.start(pace)
        if self._ui_live:
            self._tick_visuals(playing, now)
        self.overlay.tick(playing)
        e.level_play *= 0.9
        e.level_main *= 0.9
        e.level_mic *= 0.9

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
        self._update_playing_background(playing)
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
                    data = self.audio.get(sid)
                    p.set_levels(spectrum(data, prog, p.n_bands))
                    p.set_meter(loudness(data, prog, self.gain_for(p.meta)))
            elif prog is None and p.bands is not None:
                p.set_levels(None)
                p.set_meter(None)
            if prog != p.progress or paused != p.paused:
                p.progress, p.paused = prog, paused
                p.update()
            if p.progress is not None or p.bands is not None:
                lit.add(sid)
        self._pads_lit = lit
        self._update_transport(playing)
        self._show_transport(playing)
        if not self.ytresults.isHidden():   # the result in the player says so
            prog, paused = playing.get(LINK_ID, (None, False))
            self.ytresults.show_now(self._link_url, "" if prog is None else
                                    "paused" if paused else "playing")
        self._update_chips(playing)
        self.out_meter.set_level(e.level_main)
        self.logo.set_level(e.level_play)   # anything playing, not your voice
        self.mic_meter.set_level(e.level_mic if e.mic_stream else 0.0)
        if self.card_meter.isVisible():
            self.card_meter.set_level(e.level_mic if e.mic_stream else 0.0)
        talking = e.mic_stream is not None and e.level_mic > 0.05
        if talking:
            self._talk_until = now + 0.8
        talking = now < self._talk_until
        if talking != self._talk_shown:
            self._talk_shown = talking
            self._update_flow(talking)

    def _show_transport(self, playing=None):
        """The player bar: always on the Sounds tab; on the others only while a sound
        plays or is paused, so it can be stopped without going back to the pads (and
        doesn't take the room the rest of the time)."""
        if self.tabs.currentWidget() is self.sounds_page and not self.settings_open():
            want = True
        else:
            if playing is None:
                playing = self.engine.playing()
            want = any(sid in self._meta or sid == LINK_ID for sid in playing)
        if self.transport.isHidden() == want:
            self.transport.setVisible(want)

    def _scroll_background_board(self, value):
        if not self.grid.background_image:
            return
        step = getattr(self, "_background_row_step", 0)
        bar = self._pad_scroll.verticalScrollBar()
        if step:
            snapped = min(round(value / step), bar.maximum() // step) * step
            if snapped != value:
                bar.setValue(snapped)
        self.grid.update()

    def _update_playing_background(self, playing):
        on = self.cfg.playing_background
        fitted_height, step = 0, 0
        if on and self.grid.pads and self.grid._shape is not None:
            margins = self.grid.grid.contentsMargins()
            height = self.grid.natural_pad_h(self.grid._shape[1])
            spacing = self.grid.grid.spacing()
            step = height + spacing
            room = self._pad_scroll.height() - margins.top() - margins.bottom()
            if room >= height:
                rows = max(1, (room + spacing) // step)
                fitted_height = (room - spacing * (rows - 1)) // rows
                step = fitted_height + spacing
        if fitted_height != self.grid.background_pad_height:
            self.grid.background_pad_height = fitted_height
            self.grid.relayout(force=True)
        self._background_row_step = step
        gap = (on, step)
        if getattr(self, "_background_gap", None) != gap:
            self._background_gap = gap
            bar = self._pad_scroll.verticalScrollBar()
            if not hasattr(self, "_background_scroll_step"):
                self._background_scroll_step = bar.singleStep()
            # The gap belongs outside the viewport, so the backdrop contains
            # every card rather than cutting inside their edges.
            rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
            self._pad_scroll.setViewportMargins(12 if on and rtl else 0, 0,
                                               12 if on and not rtl else 0, 0)
            bar.setSingleStep(step or self._background_scroll_step)
        image = ""
        if on:
            # The first active sound owns the backdrop, including while paused.
            # Waiting sounds and a merely selected pad never claim it.
            sid = next((sid for sid in playing if sid in self._meta), None)
            m = self.meta(sid) if sid else None
            image = m.image if m else ""
        self.grid.set_background(image, self.cfg.playing_background_opacity)
        if image and step and self._pad_scroll.verticalScrollBar().value() % step:
            self._scroll_background_board(self._pad_scroll.verticalScrollBar().value())

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
            self._set_np_time(fmt_pos(frac * m.duration, m.duration))

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
            busy.emit(self.video_found, sid, found)
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
        path = videos.get(sid) if m and sid else None
        self._video_for = (sid, path)
        if path is None or sid is None or m is None:   # (a path: there's a sound)
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
        self._results_open = False      # web results are taking the pads' place
        self._cat_bar_compact = False   # the fitter's last say on the category bar
        # last: opened out, the rail stays open until nothing else can give (it shut
        # again at once when opened in a mid-sized window)
        f.add(90, "w", self._squeeze_rail)
        f.add(10, "w", r.hide(*self._pad_size))
        f.add(18, "w", r.icon_only(self.btn_view))   # its tooltip says what it is
        # the label and the dropdown go together: a lone "Clean" said nothing (the full
        # picker is on the Setup tab)
        # the ear button shrinks to its icon first: the level bar is the live part
        f.add(12, "w", r.icon_only(self.btn_check))
        f.add(14, "w", self._show_np_time)   # also hidden while it's blank
        f.add(45, "w", r.hide(self.speed_btn))
        f.add(30, "w", r.hide(self.chk_monitor))
        # the levels strip never drops a group: one is shown whole and the other two
        # become icons that bring theirs up (_fit_mixer)
        f.add(52, "w", self._fit_mixer)
        f.add(40, "w", r.hide(*self._transport_vol))
        f.add(50, "w", r.hide(self.np_name))
        f.add(60, "w", r.icon_only(self.btn_add))
        # the search box keeps room to type in until the buttons beside it have shrunk
        f.add(62, "w", lambda tight: (self.search.setMinimumWidth(0 if tight else SEARCH_MIN_W),
                                      r.touch(self.search)))
        # very narrow: the search button (and its site menu) goes; Enter still searches
        # the site picked last
        f.add(63, "w", lambda tight: (
            self.btn_yt.setVisible(not tight and self.ytresults.available()),
            r.touch(self.btn_yt)))
        f.add(64, "w", r.icon_only(self.btn_more))
        self._radio_steps = self.radio.fit_steps()   # swapped with the tab (Privacy)
        f.extend(self._radio_steps)
        self._tab_steps = {k: getattr(self, k).fit_steps() for k in ("voice", "triggers")}
        for steps in self._tab_steps.values():
            f.extend(steps)
        # height: the whole mixer strip
        f.add(5, "h", self.rail.compact)   # the rail's buttons closer together, first
        f.add(40, "h", lambda tight: r.hide(self.mixer)(
            tight and (self.height() < 520 or self.width() < 760)))
        f.add(50, "h", self._cat_bar_step)   # the overlay's category key still works
        # the download list folds to its running row, then to its summary line, before
        # the mixer goes (a long queue at 800x600 isn't a reason for the mini player)
        self._dl_steps = self.download_bar.fit_steps()
        f.extend(self._dl_steps)
        self._stack_cols = (self._stack_setup,
                            *self.voice.stack_steps())
        self.setMinimumSize(responsive.MIN_SIZE)

    def _cat_bar_step(self, compact: bool):
        """The fitter's say on the category bar: it hides it when the window is short."""
        self._cat_bar_compact = compact
        self._sync_cat_bar()

    def _sync_cat_bar(self):
        """The category bar is hidden when the window is short (the fitter) or when web
        results take the pads' place: leaving its empty row in the layout kept a gap
        between the toolbar and the results' buttons."""
        self.cat_bar.setVisible(not self._cat_bar_compact and not self._results_open)
        responsive.touch(self.cat_bar)

    def _show_pill(self):
        """The setup pill: only while something needs fixing."""
        self.pill.setVisible(not self._pill_good)
        self.pill.setProperty("outputgood", self._pill_good)
        if hasattr(self, "rail"):
            self.rail.refresh_output()

    def _refit(self):
        size = self._pages.size()
        mini = size.width() < MINI_SIZE.width() or size.height() < MINI_SIZE.height()
        if not mini:
            # measured with the whole window in place: while the mini player shows, the
            # hidden page's sizes go stale and it stayed the mini player at sizes the
            # whole window fits (nothing is painted before this returns)
            self._set_mini(False)
            self.rail.compact(self.rail._compact)
            self._mixer_layout.setDirection(QBoxLayout.Direction.LeftToRight)
            self._mixer_layout.setSpacing(14)
            for group in self._decks[1:]:
                group[0].setMaximumHeight(16777215)
            responsive.touch(self._pads_scroll)
            # room for a whole row of pads comes before the mixer, the status line and
            # the rest: without it they kept their room and the pads got a slit
            self._pads_scroll.setMinimumHeight(self.grid.row_height())
            narrow = self.width() < 860   # two cards side by side get cramped below this
            # Translated controls can need more room than the fixed breakpoint.
            # Measure both Setup columns even while they are stacked, so growing
            # the window brings them back only when neither will be clipped.
            body = self.setup_page.widget()
            lay = body.layout() if body is not None else None
            holder = self._setup_cols.parentWidget()
            assert lay is not None and holder is not None   # built in _build_setup_page
            margins = lay.contentsMargins()
            room = self.setup_page.viewport().width() - margins.left() - margins.right()
            available = min(room, holder.maximumWidth())
            self._stack_cols[0](narrow or self._setup_need() > available)
            for apply in self._stack_cols[1:]:
                apply(narrow)
            need = self._fit.fit(size)   # even the smallest layout won't fit
            if need.width() > size.width() or need.height() > size.height():
                # A restored mixer needs one width pass before considering a wrap.
                need = self._fit.fit(size)
            if (self.width() >= 760 and need.width() > size.width()
                    and self.mixer.minimumSizeHint().width() + self.rail.width() > size.width()):
                # Wrap only when the visible groups need it, e.g. with larger fonts.
                self._mixer_layout.setDirection(QBoxLayout.Direction.TopToBottom)
                self._mixer_layout.setSpacing(4)
                for group in self._decks[1:]:
                    group[0].setMaximumHeight(0)
                self.mixer.setMinimumSize(0, 0)
                self._mixer_layout.activate()
                responsive.touch(self.mixer)
                need = self._fit.fit(size)
            mini = need.width() > size.width() or need.height() > size.height()
            if mini and not self.is_mini():
                log.info("mini player at %dx%d: the window needs %dx%d (tab %s)",
                         size.width(), size.height(), need.width(), need.height(),
                         type(self.tabs.currentWidget()).__name__)
        if mini and self.settings_open() and not getattr(self, "_opening_settings", False):
            # made too small for Settings: they close (as Done does), the mini player shows
            self.close_settings()
            return
        self._set_mini(mini)
        if mini:   # the pads too: cards with room for a couple of rows of them, else
            # one-line rows, so they can still be seen and played however small it gets
            room = self._mini_pad_room(size)
            self.grid.set_slim(room < MINI_PAD_ROWS * self._mini_row(size))
            m = self.grid.grid.contentsMargins()
            show = room >= SLIM_PAD_H + m.top() + m.bottom()
            if self._pads_scroll.isHidden() == show:
                self._pads_scroll.setVisible(show)
                toastmod.relayout(self)   # icons on the pads, or none without them

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
        toastmod.relayout(self)   # cards in the window, icons in the mini player

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
        hiding = (self.tray is not None and self.tray.isVisible() and self.cfg.tray
                  and not self._quitting)
        if (not hiding and not self._shut_down and self.linkbar.downloading()
                and QMessageBox.question(
                    self, _("Download running"),
                    _("A download is still running. If you close now, it's lost. "
                      "Close anyway?")) != QMessageBox.StandardButton.Yes):
            ev.ignore()
            self._quitting = False
            return
        if self.tray is not None and self.tray.isVisible() and self.cfg.tray \
                and not self._quitting:
            ev.ignore()   # keep running in the tray: hotkeys, overlay and sounds go on
            self.hide()
            if not self._tray_told:
                self._tray_told = True
                self.tray.showMessage(_("Onion Board is still running"),
                                      _("Your hotkeys keep working. Right-click this icon "
                                        "to quit."), QSystemTrayIcon.MessageIcon.Information, 5000)
            return
        if self.tray is not None:
            self.tray.hide()
            QTimer.singleShot(0, QApplication.quit)
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
                     self._remember_usage, self.cfg.save, self.overlay.shutdown,
                     self.hotkeys.stop, self.replay.stop, self.remote.stop,
                     self._stop_remote_addons,
                     self.radio.shutdown, tor.shutdown, self.apps.shutdown,
                     self.triggers.shutdown,
                     self.linkbar.shutdown, ytworker.drop_all,
                     self.voice.shutdown, self.engine.shutdown, shellicon.detach,
                     self.thumbbar.close,
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
