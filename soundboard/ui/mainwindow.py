"""The main window: pads, transport, web search, the audio panel, auto push-to-talk."""
from __future__ import annotations

import copy
import html
import re
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Literal, overload

import numpy as np
from PySide6.QtCore import (QEvent, QObject, QPoint, QSignalBlocker,
                            QSize, Qt, QTimer, Signal)
from PySide6.QtGui import (QIcon,
                           QKeySequence, QShortcut)
from PySide6.QtWidgets import (QApplication, QBoxLayout, QCheckBox, QComboBox, QDialog, QFrame,
                               QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QProgressBar,
                               QPushButton, QScrollArea, QSizePolicy, QSlider, QStackedWidget,
                               QSystemTrayIcon, QVBoxLayout, QWidgetItem,
                               QWidget)
from shiboken6 import isValid as qt_valid

from soundboard import engine as eng
from soundboard import bunny, theme, winkeys, ytdl, ytworker
from soundboard.engine import SR, Engine
from soundboard.engine import is_virtual as is_virtual_cable
from soundboard import exitwatch
from soundboard import (appaudio, autostart, backup, destination, library, midi,
                        remote, otherboards, reset, soundfx, thumbs, trash, updates, videos,
                        voicesdk)
from soundboard import (appsetup, ffmpegget, net, netlog,
                        profiles, quality, shellicon, sourceinfo, thumbbar, tips, tor,
                        usage, watchaddon)
from soundboard.replay import InstantReplay
from soundboard.library import (PAD_COLORS, PRESS_MODE, Config,
                                SoundMeta, cache_keep, fingerprint,
                                load_original, load_sound, prune_cache, save_clip)
from soundboard.settings import HOTKEY_ACTIONS, HotkeyDialog, SettingsDialog, pretty_key
from soundboard.shuffle import ShuffleBag
from soundboard.ui.crashdialog import free_dialog, rehome_crash_reports
from soundboard.ui.dialogs import EditDialog, TabHelpPopup
from soundboard.ui.iconrow import CapIcon
from soundboard.ui import routewarn
from soundboard.ui import worker
from soundboard.ui.dropveil import DropVeil
from soundboard.ui.ffmpegcontrol import FfmpegControl
from soundboard.ui.tabcontrol import TAB_INDEX, TAB_KEYS, TABS, TabControl
from soundboard.ui.statuscontrol import StatusControl
from soundboard.ui.miccontrol import MIC_OFFER_MS, MicControl
from soundboard.ui.routecontrol import ROUTE_DEVICE, RouteControl
from soundboard.ui.devicecontrol import DeviceControl
from soundboard.ui.editcontrol import EditControl
from soundboard.ui.removecontrol import RemoveControl
from soundboard.ui.padcontrol import PadControl
from soundboard.ui.remoteaccess import RemoteAccess
from soundboard.ui.buncontrol import BUN_TIP, BunControl
from soundboard.ui.alertcontrol import AlertControl
from soundboard.ui.categorycontrol import CategoryControl
from soundboard.ui.importcontrol import ImportControl
from soundboard.ui.updatecontrol import UpdateControl
from soundboard.ui import toast as toastmod
from soundboard.ui import (a11y, alsosend, appstate, busy, icons, responsive,
                           splash, taboff, themecover)
from soundboard.ui.speedpitch import SpeedPitchButton
from soundboard.ui.panel import (BAR_H, CONTROL_H, EqPanel, Flow, VolumeControl, bar,
                                 alt_tile, capped, card, hint_label, icon_label,
                                 info_button,
                                 steady_number, TileRow, vsep)
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
from soundboard.ui.padbatch import PadSelection
from soundboard.ui.overlay import Overlay
from soundboard.ui.appspanel import AppsTab, ElidedLabel
from soundboard.ui.triggershost import BoardHost
from soundboard.ui.triggerstab import TriggersTab
from soundboard.ui.radiopanel import RadioOff, RadioTab
from soundboard.ui.voicepanel import VoicePanel
from soundboard.ui.playbutton import PlayButton
from soundboard.ui.widgets import (DropdownMenu, Meter, NameAndSeek, Pad, PadGrid, SeekSlider,
                                   SteadyTabs, WindowRoot, expand_dropped, fmt_pos, loudness,
                                   pad_height, spectrum, take_out, SLIM_PAD_H)
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




# an effects preview of a sound longer than this renders only its first PREVIEW_S
# (soundfx.preview_part): a 2-hour song's pitch shift took minutes to start playing
PREVIEW_WHOLE_S = 5 * 60
PREVIEW_S = 30
TOAST_EXPAND = QSize(900, 640)   # a shrunk card clicked: the window grows to this
# shown when instant replay goes on: it records whoever is talking in a call
REPLAY_NOTE = _("Instant replay is on: your key keeps the last seconds you heard. In some "
                "places recording a call needs everyone's OK, so only keep clips of people "
                "who are fine with it.")
CHIPS_GAP = 6         # between the now-playing row's chips
CHIPS_ROW_H = 30      # the now-playing row: a chip's 24 px ■ button, its margins and border
TICK_MS = 33         # the UI timer while the window is on screen (meters, visualisers)
TICK_IDLE_MS = 250   # ...and while it's in the tray or minimised (push-to-talk, watchdog)
TICK_QUIET_MS = 100  # on screen with nothing moving: no sound, radio, recording or level
LEVEL_QUIET = 0.003  # a level below this (-50 dB) shows as nothing on the meters
PULSE_MS = 1200      # the mic-check banner's throb: bright, dimmer, bright again
PULSE_LOW = 0.55     # ...down to this opacity
PULSE_FRAME_MS = 60  # ...a step this often (~16 a second still reads as a smooth pulse)
DEFAULT_POLL_MS = 1500   # how often Windows' default output is checked
SETUP_SWITCHED_MS = 8000   # how long "Voice chat mode for Discord. Undo" stays
SETUP_DONE_MS = 15000      # the set-up card with nothing left to do
DISCORD_POLL_MS = 10000  # how often Discord's voice settings are looked at (discordcfg)
RAW_POLL_MS = 2000       # how often the apps recording the mic are counted (rawmic)
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
TLS_WARM_MS = 2500     # Qt's TLS is set up this long after the start (_warm_tls)
TIP_DELAY_MS = 8000    # the first tip waits this long after the start
TIP_RETRY_MS = 60_000  # ...and is tried again this often while it can't show
LANG_OFFER_SEEN = "language-offer"   # in Config.tips_seen: the language bar was turned down
FF_CHECK_MS = 1500     # the FFmpeg check's answer is taken this long after the start
SEARCH_MIN_W = 220    # the Sounds tab's search box, until the window gets narrow
# ...and its most: a few words go in it, so past this it's only a longer empty bar
# (456 px at 1180x720, so normal windows are unchanged). The seek bar, the levels and
# the drop box still follow the window: wider is useful there.
SEARCH_MAX_W = 480
VOICE_POLL_MS = 3000  # how often the game in front is looked at (soundboard.voicesdk)
VOICE_POLL_IDLE_S = 15   # ...while nobody sees the hint and nothing switches by itself
# Setup -> Devices -> Send my sounds to (Config.route, library.ROUTES): the mic, nobody,
# or one of the output devices by name (ROUTE_DEVICE + its name: "cable" for a virtual
# cable, "device" for anything else)
SEND_TO = _("Send my sounds to")


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
        self.setAccessibleName(text)

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
            self.setToolTip("" if text == self._full else self._full)   # only when cut


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
    exported = Signal(str, int, str, int)      # file, sounds written, error, left out
    unpacked = Signal(object, object, str)     # backup.Imported|None, backup.Package, error
    worked = Signal(object, object, object)    # _on_worker: then, result|None, error|None
    update = Signal(object, str, bool)         # updates.Release|None, error, asked by the user
    update_progress = Signal(object, object)   # bytes of the new version downloaded, of
                                               # how many (0: not known)
    update_ready = Signal(object, str)         # its installer's Path|None, error
    watch_update = Signal(object)              # a newer Onion Watch: watchaddon.Offer
    discord = Signal(object)                   # [discordcfg.Settings] read in the background
    mic_users = Signal(object)                 # [appaudio.App] recording the mic (rawmic)
    counted = Signal(object)                   # a usage count went: what it clears (usage.py)
    imported = Signal(object, object, object)  # meta|None, data|None, Skipped|None
    preview = Signal(str, object, float, int)  # id, audio with unsaved effects|None, gain, gen
    ffmpeg = Signal(object, object)            # ffmpegget.Health, after a fix: "" or its error
    ffmpeg_progress = Signal(int)              # percent of FFmpeg downloaded (-1: not known)


def _holds_focus(w: QWidget) -> bool:
    """The keyboard focus is in `w`."""
    fw = QApplication.focusWidget()
    return fw is not None and w.isAncestorOf(fw)


def _polish(w: QWidget, size=None):
    """Style a hidden widget and its children now, and lay it out at `size` (Qt waits
    for the first show for both)."""
    w.ensurePolished()
    for c in w.findChildren(QWidget):
        c.ensurePolished()
    if size is not None:
        w.resize(size)
    for lay in [c.layout() for c in (w, *w.findChildren(QWidget))]:
        if lay is not None:
            lay.activate()


class MainWindow(QMainWindow):
    update_done = Signal(object, str)   # an update check finished: Release|None, error
    update_state = Signal()             # the update card changed (Settings > Updates follows)
    mic_attached = Signal(str, str)     # attach_mic finished: the mic, error ("" = done)
    helper_checked = Signal()           # michelper.ready() asked again (on a thread)
    cable_removed = Signal(str)         # remove_cable finished: error ("" = done)
    remote_changed = Signal()           # a remote control server started or stopped
    cable_setup_found = Signal(bool)    # VB-Cable's setup program is on this PC (asked on a thread)
    video_found = Signal(str, object)   # a sound's video (Path|None), looked up on a thread
    board_read = Signal(object, str, bool, object)   # import_other read on a thread: Source,
                                        # its board's path ("" = not found), ask, otherboards
                                        # .importable()'s (ok, bad) and entries, or the error
    config_saved = Signal(bool)         # the background save finished: ok
    voice_engine = Signal(object)       # the voice engine of the game in front (a mode key|None)
    default_found = Signal(object)      # Windows' default output, asked on a thread (str|None)
    device_step = Signal(object)        # the device thread's next step for the UI (_off_ui)
    tab_switched = Signal(str, bool)    # Settings > Tabs: a tab (taboff.KEYS) off / on again
    category_programs_changed = Signal()   # a program -> category rule added / removed
    app_setup_changed = Signal()   # an app remembered / forgotten (appsetup)
    bin_filled = Signal(object)    # removed sounds are in the bin: its sound count|None

    # the slim bars across the top of the window (urgent fix, tip, app offer, FFmpeg, language)
    TOP_BARS = ("urgent_bar", "tip_bar", "setup_bar", "ff_bar", "lang_bar")

    def __init__(self):
        super().__init__()
        self.tabctl = TabControl(self)
        self.statusctl = StatusControl(self)
        self.micctl = MicControl(self)
        self.routectl = RouteControl(self)
        self.devctl = DeviceControl(self)
        self.editctl = EditControl(self)
        self.rmctl = RemoveControl(self)
        self.padctl = PadControl(self)
        self.remctl = RemoteAccess(self)
        self.bunctl = BunControl(self)
        self.alertctl = AlertControl(self)
        self.catctl = CategoryControl(self)
        self.impctl = ImportControl(self)
        self.updctl = UpdateControl(self)
        # shutdown() ran (app.py also calls it on aboutToQuit). Set first: the splash
        # pumps events while the window is built, so its timers can run
        # before the end of __init__
        self._shut_down = False
        self.title = "Onion Board"   # the version is on the rail, under the name
        self.setWindowTitle(self.title)
        self.setAcceptDrops(True)   # files dropped outside the pad grid: see dropEvent
        self.cfg = Config.load()
        # sounds left on the Undo bar by a crash: into Recently deleted (before the
        # sounds folder is scanned, or their audio joins the board again bare)
        trash.finish_held({m.id for m in self.cfg.sounds})
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
            theme.textures_on = self.cfg.theme_texture
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
        def counted(do):   # a taskbar button pressed (usage.py), then what it does
            return lambda: (usage.used("taskbar-buttons"), do())
        self.thumbbar = tb.ThumbBar(self, {
            tb.LAST: counted(self.play_last),
            tb.PAUSE: counted(self._pause_clicked),
            tb.STOP: counted(self._stop_all_clicked),
            tb.RANDOM: counted(self.play_random),
            tb.LIVE: counted(lambda: self.set_sending(not self.engine.sending))})
        self._radio_paused = None   # the station Pause stopped, for Play to turn back on
        self.replay.state_changed.connect(self.on_replay_state)
        self.overlay = Overlay(self, self.cfg.overlay)
        self._save_failed_shown = False
        self.bridge = Bridge()
        self.bridge.loaded.connect(self.on_loaded)
        self.bridge.imported.connect(self.impctl.on_imported)
        self.bridge.preview.connect(self._on_fx_preview)
        self.bridge.exported.connect(self.impctl._on_exported)
        self.bridge.unpacked.connect(self.impctl._on_unpacked)
        self.bridge.worked.connect(self.impctl._on_worked)
        self.bridge.update.connect(self.updctl._on_update)
        self.bridge.update_progress.connect(self.updctl._on_update_progress)
        self.bridge.update_ready.connect(self.updctl._on_update_ready)
        self.bridge.watch_update.connect(self.updctl._on_watch_update)
        self.bridge.discord.connect(self.alertctl._on_discord)
        self.bridge.mic_users.connect(self.alertctl._on_mic_users)
        self.bridge.counted.connect(self._usage_counted)
        self.ffctl = FfmpegControl(self)
        self.bridge.ffmpeg.connect(self.ffctl.on_answer)
        self.bridge.ffmpeg_progress.connect(self.ffctl.on_progress)
        # windows beside the board, not over it: the one Settings, and an Edit
        # sound for each sound being edited
        self._settings_dlg: SettingsDialog | None = None
        self._spare_editor: EditDialog | None = None   # a closed one, reused (edit)
        self._settings_kept: SettingsDialog | None = None   # closed Settings, reused
        self._settings_kept_print = None
        self.shuffle = ShuffleBag()       # the random-sound hotkeys
        self._last_sid: str | None = None   # the last sound played (its replay hotkey)
        self._queue: list[str] = []       # sounds waiting for the ones playing to finish
        self._stopped_at = (0.0, "")       # (when, which) a ■ for one sound last stopped
        self._cool: dict[str, float] = {}   # sid -> time.monotonic() its cooldown ends
        self._waiting: dict[str, list[QTimer]] = {}   # sid -> its delayed starts
        self._hotkeys_off = False         # "All hotkeys off": only that key still works
        self._voice_was: bool | None = None   # voice changer state before a held key
        Pad.single_click = self.cfg.single_click
        self._quitting = False            # a real quit (not "close to the tray")
        self._tray_told = False           # the "still running in the tray" note was shown
        self.tray: QSystemTrayIcon | None = None
        self.watch_offer: watchaddon.Offer | None = None   # an urgent Onion Watch fix
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
        self._discord_timer = QTimer(self, interval=DISCORD_POLL_MS)
        self._discord_timer.timeout.connect(self.alertctl._discord_tick)
        if sys.platform == "win32":
            self._discord_timer.start()
            QTimer.singleShot(3000, self.alertctl._discord_tick)
        self._raw_timer = QTimer(self, interval=RAW_POLL_MS)
        self._raw_timer.timeout.connect(self.alertctl._raw_tick)
        if sys.platform == "win32":
            self._raw_timer.start()
        self._preview_gen = 0            # newest effects preview (older renders are dropped)
        self._preview_done = None         # its done(ok) callback while it renders
        self._ptt_held: str | None = None   # PTT key we're currently holding
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
        self._talk_until = 0.0            # "hearing you" indicator holds until this time
        self._talk_shown: bool | None = None
        self._load_thread: threading.Thread | None = None
        self._loading: set[str] = set()   # sids a load thread is decoding right now
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
        self.bin_filled.connect(self.rmctl._label_bin)

        self._pill_long = ""              # the setup pill's whole text (its tip, its name)
        self._pill_good = False           # set up: the pill hides (_show_pill)
        self._default_out = appaudio.default_output_name()   # see _follow_default_output
        self._build_ui()
        splash.pump()
        self.devctl._init_devices()
        splash.pump()
        if self.statusctl.setup_state != "ok":
            self.tabs.blockSignals(True)
            self.tabs.setCurrentWidget(self.setup_page)
            self.tabs.blockSignals(False)
            self.rail.sync()   # (it heard nothing)
        if reset.before_update(self.cfg):   # a restore point first, when this is an update
            usage.used("restore-point-update")
        library.tidy_files(self.cfg)   # files from before library folders move in
        self._rebuild_pads()
        splash.pump()
        self._load_all()
        splash.pump()
        self.load_triggers()   # behind the loading screen, not on the tab's first click
        splash.pump()
        self.impctl._watch_sounds_folder()
        self._fit_overlay_key()
        self.register_hotkeys()
        # Stream Deck / scripts (Settings → Remote), only if turned on
        self.remote = remote.RemoteControl(lambda a, p: remote.dispatch(self, a, p), self)
        self.remctl.apply_remote()
        self.remctl.remote_addons = self.remctl._load_remote_addons()
        a11y.label_tree(self, force=True)   # names for the icon-only buttons

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(TICK_MS)
        app = QApplication.instance()
        assert isinstance(app, QApplication)   # made before the window
        app.applicationStateChanged.connect(self._set_tick_rate)
        app.applicationStateChanged.connect(self.micctl._app_state)
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
        self.catctl._update_cat_timer()   # program -> category rules (catswitch.py)
        # the headphones follow Windows' default output when it changes
        self._default_timer = QTimer(self)
        self._default_timer.timeout.connect(self.devctl._default_tick)
        self._default_timer.timeout.connect(self.devctl._recover_devices)
        self.default_found.connect(self.devctl._on_default_found)
        self.device_step.connect(lambda step: step())
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
        worker.run(lambda: modules.precompile(modules.discover(), engine.any_playing),
                   name="addon-precompile")

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

    _show_bun = False       # the set-up running is the first one: Bun's show explains it

    def _show_load_note(self):
        """Started hidden in the tray (--tray at sign-in)? Then the box waits for the
        window to be opened, instead of popping up over whatever the user is doing."""
        if self.isVisible():
            self._tell_load_note(self.cfg.load_note)
        else:
            self._pending_note = self.cfg.load_note

    def _tell_load_note(self, note: str):
        """Settings lost or taken from a backup: a card that stays until it's closed (a
        timed one was gone before anyone read it), with the settings folder a click away."""
        self.tell(_("Settings were restored"), note, "warn", 0, key="load-note",
                  action=(_("Open folder"),
                          lambda: busy.open_folder(library.CONFIG_PATH.parent, window=self)))

    # ------------------------------------------------------------------ UI build
    # Layout: the tab rail (with Live, Stop all and the setup pill) / tabs / mixer strip.
    # Every tab is built the same way: a toolbar row on top, its content, and a
    # bottom bar ending in "Volume [slider %] | Hear it myself" for that source.
    def _build_ui(self):
        # page 0 the whole window, page 1 the mini player it turns into when it's
        # made too small to use (see _refit)
        self._pages = QStackedWidget()
        self.setCentralWidget(self._pages)
        root = self._full = WindowRoot()
        root.setObjectName("root")   # the theme's window background (flat or the glow)
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
        # on the rail: the name over a quiet "by Onion Alien · v1.9.28" (the title bar
        # is just the name; "from source" is in the tips)
        self.tagline = sidebar.ClickLabel(
            f"{_('by {name}', name='Onion Alien')} · v{__version__}")
        self.tagline.setObjectName("tagline")
        about = _("an app by Onion Alien · v{version_text}", version_text=version_text())
        for w in (self.logo, self.wordmark):
            w.setToolTip(about)
        whats_new = _("What's new")   # the version is a button to it
        self.tagline.setToolTip(f"{about}\n{whats_new}")
        self.tagline.clicked.connect(
            lambda: (usage.used("whats-new"), self.updctl.show_whats_new()))
        self.pill = QPushButton()
        self.pill.setObjectName("pill")
        self.pill.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pill.setIconSize(QSize(sidebar.ICON, sidebar.ICON))
        self.pill.clicked.connect(lambda: self.tabs.setCurrentWidget(self.setup_page))
        # a new version: a card over the On Air card (an icon, shut) that follows it
        # from found to downloading to ready (_show_update_state)
        self.btn_update = sidebar.UpdateCard()
        self.btn_update.clicked.connect(self.updctl._update_clicked)
        self.btn_update.copy.clicked.connect(self.updctl._copy_update_error)
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
        self.urgent_btn.clicked.connect(self.alertctl._urgent_clicked)
        uh.addWidget(self.urgent_btn)
        hide = QPushButton()
        hide.setObjectName("urgenthide")
        hide.setAccessibleName(_("Hide"))
        hide.setToolTip(_("Hide until Onion Board starts again"))
        icons.close_button(hide, 28, "warn_text")
        hide.clicked.connect(self.alertctl._hide_urgent)
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

        self.ff_bar = self.ffctl.build_bar()   # FFmpeg (ui/ffmpegcontrol.py)
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

        # the bars' buttons take focus from Tab only, never a click: a clicked ✕ held the
        # focus, its bar hid, and Qt passed the focus on to the sidebar's Sounds button
        for name in self.TOP_BARS:
            for b in getattr(self, name).findChildren(QPushButton):
                b.setFocusPolicy(Qt.FocusPolicy.TabFocus)

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
            self.tabs.setTabVisible(TAB_INDEX[key], self.tabctl.tab_shown(key))
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
        mt.aboutToShow.connect(lambda: self.tabctl._fill_more_tabs(mt))
        mt.aboutToHide.connect(self.tabctl._more_tabs_hidden)
        self.btn_more_tabs.clicked.connect(mt.pop)
        self.tabctl._update_more_tabs()
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
                      activated=lambda n=n: self.tabctl._go_tab(n - 1, absolute=True))
        QShortcut(QKeySequence("Ctrl+Tab"), self, activated=lambda: self.tabctl._go_tab(1))   # pyright: ignore[reportCallIssue]
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self, activated=lambda: self.tabctl._go_tab(-1))   # pyright: ignore[reportCallIssue]
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
                lambda pos, b=b: self.tabctl.tab_menu(b.index).exec(b.mapToGlobal(pos)))
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
        self.tabctl._focus_open_tab()
        self.tabs.currentChanged.connect(lambda i: self.set_option("tab", i))
        self.tabs.currentChanged.connect(lambda _i: self._fit_dl_bar())
        self.tabs.currentChanged.connect(self.tabctl._count_tab)   # names only (usage.py)
        self.tabctl._count_tab(self.tabs.currentIndex())
        self.tabs.currentChanged.connect(lambda _i: self.statusctl._update_status())
        self.tabs.currentChanged.connect(self._focus_sounds_page)
        # an urgent Onion Watch fix's banner shows on the Triggers tab only
        self.tabs.currentChanged.connect(
            lambda _i: self.watch_offer is not None and self.alertctl._show_urgent())
        # a badge on a tab's icon (or, by default, a wash) in the theme's live colour while
        # its feature is live — the voice changer, a radio station, a program being
        # sent, the screen watched — so it's never left on without you noticing
        set_live_tint(self.tabs, self.cfg.live_tab_green)
        for key in ("voice", "triggers", "apps"):
            self.tabctl._tab_live(key, getattr(self, key).is_active())
        self.tabctl._radio_live(self.radio.is_active())
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
        self.mini_pp.setAccessibleName(_("Play / pause"))
        self.mini_pp.clicked.connect(self.toggle_play_pause)
        self.mini_st = QPushButton()
        self.mini_st.setObjectName("transport_stop")
        self.mini_st.setAccessibleName(_("Stop"))
        self.mini_st.clicked.connect(self.stop_current)
        icons.set_icon(self.mini_st, "stop", size=16)
        self.mini_skip = QPushButton()
        self.mini_skip.setObjectName("transport_stop")
        self.mini_skip.setAccessibleName(_("Skip to the next sound in Up next"))
        self.mini_skip.clicked.connect(self.skip_next)
        icons.set_icon(self.mini_skip, "next", size=16)
        for b in (self.mini_pp, self.mini_st, self.mini_skip):
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
        self.mini_mic.toggled.connect(self.routectl.on_mic_toggle)
        self.mini_mic.clicked.connect(lambda: usage.used("mini-mic-mute"))   # clicks only
        self.mini_mic.clicked.connect(self.routectl._warn_mute_does_nothing)
        connection.addWidget(self.mini_mic)
        self.mini_bun = QPushButton()
        self.mini_bun.setFixedSize(34, 28)
        self.mini_bun.setToolTip(BUN_TIP)
        self.mini_bun.setAccessibleName(_("Turn into Bun"))
        self.mini_bun.setIconSize(QSize(20, 20))
        self._paint_mini_bun()
        self.mini_bun.clicked.connect(self.bunctl.enter_bun_mode)
        connection.addWidget(self.mini_bun)
        cv.addLayout(connection)
        v.addWidget(card)
        self._sync_mini_mic()
        icons.set_icon(self.mini_pp, "play", "on_accent", size=16)
        return page

    def _paint_mini_bun(self):
        """The mini player's Bun button: him in this theme's outfit."""
        self.mini_bun.setIcon(self._bun_icon())
        if getattr(self, "_tray_bun", None) is not None:   # (the tray's menu: theme changes)
            self._tray_bun.setIcon(self._bun_icon())

    def _bun_icon(self) -> QIcon:
        """Bun in this theme's outfit, drawn at the exact size shown."""
        return icons.sharp_icon(lambda px, _mode, _state: bunny.bunny_pixmap(px))

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
        # the state in words and a struck-through mic when muted (as voice apps show it),
        # so "Mic on" reads as how it is, not as what a click does
        self.mini_mic.setText(_("Mic on") if on else _("Mic muted"))
        icons.set_icon(self.mini_mic, "mic" if on else "mic_off", None, "on_accent", size=16)
        self.mini_mic.setAccessibleName(_("My mic"))   # a toggle: "checked" says the state
        self.mini_mic.setAccessibleDescription(self.mini_mic.text())

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
            lbl = QLabel(title)
            lbl.setObjectName("decktitle")
            lbl.setToolTip(tip)
            row.addWidget(CapIcon(lbl, icon, tip=tip))
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
        self.chk_mic.toggled.connect(self.routectl.on_mic_toggle)
        self.chk_mic.clicked.connect(self.routectl._warn_mute_does_nothing)   # clicks only
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

        for box, key in ((self.vol_mic, "mic_vol"), (self.vol_mon, "mon_vol")):
            box.changed.connect(lambda v, key=key: self.set_option(key, v))
        return f

    def _fit_mixer(self, tight: bool):
        """The levels strip's responsive step. Only when the strip itself is too wide
        (not for whatever else is): one group whole, the other two as icons; still too
        wide, the % boxes go (the sliders still say it). "Others hear it" keeps its
        words: an empty box beside a mic icon said nothing, and it's the switch a warning
        sends you to."""
        stages = (lambda: self._mixer_one_at_a_time(True),
                  lambda: (self.vol_mic.spin.hide(), self.vol_mon.spin.hide()))
        self._mixer_one_at_a_time(False)
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
        icons.set_icon(am.addAction(_("Sound files"), self.impctl.add_dialog), "music")
        icons.set_icon(am.addAction(_("A whole folder"), self.impctl.add_folder_dialog), "folder")
        icons.set_icon(am.addAction(_("Record"), self.record_dialog), "mic")
        icons.set_icon(am.addAction(_("From a link"), self.impctl.add_from_link), "link")
        icons.set_icon(am.addAction(_("Free sound packs"), self.impctl.show_packs), "download")
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
        icons.clear_button(self.search)
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
        icons.set_icon(self.btn_yt, "youtube", "accent", "accent", size=18)
        # which site Enter searches: the button shows it, its menu picks another
        self._site_menu = DropdownMenu(self.btn_yt)
        self.btn_yt.setMenu(self._site_menu)
        self.btn_yt.setProperty("toolbarMenu", True)
        more = self.btn_more = QPushButton(_("Library"))
        more.setToolTip(_("Export your sounds and settings to a file, or import a backup or "
                          "sound pack"))
        icons.set_icon(more, "archive", size=18)
        mm = DropdownMenu(more)
        icons.set_icon(mm.addAction(_("Import a backup or sound pack"), self.impctl.import_dialog),
                       "folder")
        icons.set_icon(mm.addAction(_("Free sound packs"), self.impctl.show_packs), "download")
        om = mm.addMenu(_("Import from another soundboard"))
        icons.set_icon(om.menuAction(), "copy")
        for src in otherboards.sources():
            icons.set_icon(om.addAction(f"{src.name}…",
                                        lambda src=src: self.impctl.import_other(src)),
                           "sounds")
        pm = self._packs_menu = mm.addMenu(_("My sound packs"))
        icons.set_icon(pm.menuAction(), "sounds")
        pm.aboutToShow.connect(lambda: self.impctl._fill_packs_menu(pm))
        mm.addSeparator()
        icons.set_icon(mm.addAction(_("Export everything (sounds + settings)"),
                                    self.impctl.export_board), "download")
        self._act_export_cat = mm.addAction(_("Export this category"), self.impctl.export_category)
        icons.set_icon(self._act_export_cat, "download")
        mm.addSeparator()
        icons.set_icon(mm.addAction(_("Recently deleted sounds"), self.rmctl.show_deleted), "trash")
        icons.set_icon(mm.addAction(_("Open the sounds folder"), self.impctl.open_sounds_folder),
                       "folder")   # here too, for when the window's too narrow for its button
        mm.aboutToShow.connect(lambda: (
            self._act_export_cat.setEnabled(bool(self.cfg.category)),
            pm.menuAction().setVisible(bool(backup.packs()))))
        more.setMenu(mm)
        more.setProperty("toolbarMenu", True)
        self.btn_bin = QPushButton()
        self.btn_bin.setToolTip(_("Sounds you removed: bring them back, exactly as they were"))
        icons.set_icon(self.btn_bin, "trash")
        self.btn_bin.clicked.connect(self.rmctl.show_deleted)
        self.btn_folder = QPushButton(_("Sounds folder"))
        self.btn_folder.setToolTip(_("Open the folder your sounds are kept in. Sound files you "
                                     "drag into it join the board by themselves."))
        icons.set_icon(self.btn_folder, "folder", size=18)
        self.btn_folder.clicked.connect(self.impctl.open_sounds_folder)
        self.rmctl._label_bin()
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
        vm.aboutToShow.connect(lambda: self.padctl._fill_view_menu(vm))
        self.btn_view.setMenu(vm)
        self.btn_view.setProperty("toolbarMenu", True)
        self.padctl._label_view()
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
        size.setToolTip(_("Card size"))
        # a drag re-lays every pad at most every PAD_SIZE_WAIT_MS, not on each step
        self._pad_size_wait = QTimer(self, singleShot=True, interval=PAD_SIZE_WAIT_MS)
        self._pad_size_wait.timeout.connect(lambda: self.set_pad_width(size.value()))
        size.valueChanged.connect(lambda _v: self._pad_size_wait.isActive()
                                  or self._pad_size_wait.start())
        no_wheel(size)
        size_lbl = QLabel(_("Card size"))
        size_lbl.setObjectName("muted")
        tb.addWidget(size_lbl)
        tb.addWidget(size)
        self._pad_size = (size_lbl, size)
        # the list view has rows, not cards: a row size takes the slider's place there
        rows_lbl = QLabel(_("Row size"))
        rows_lbl.setObjectName("muted")
        self.btn_rows = QPushButton()
        self.btn_rows.setAccessibleName(_("Row size"))
        self.btn_rows.setToolTip(_("How tall the rows in the list are"))
        rm = DropdownMenu(self.btn_rows)
        rm.aboutToShow.connect(lambda: self.padctl._fill_rows_menu(rm))
        self.btn_rows.setMenu(rm)
        self.btn_rows.setProperty("toolbarMenu", True)
        self.btn_rows.setProperty("quiet", True)
        self.btn_rows.setFixedHeight(CONTROL_H)
        tb.addWidget(rows_lbl)
        tb.addWidget(self.btn_rows)
        self._row_size = (rows_lbl, self.btn_rows)
        self._size_tight = False   # the window too narrow for either (_init_fit)
        self.padctl._label_rows()
        self.padctl._show_size_picker()
        for b in (add, self.btn_yt, self.btn_folder, more, self.btn_keys,
                  self.btn_bin, self.btn_view, self.search):
            b.setFixedHeight(CONTROL_H)
        # held in a row whose margins make the toolbar span exactly the pads below it
        # (_fit_toolbar): its edges line up with the first and last card
        hold = self._toolbar_hold = QWidget()
        hl = QHBoxLayout(hold)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(self.sounds_toolbar)
        left.addWidget(hold)
        self.cat_bar = self.catctl._build_categories()
        left.addWidget(self.cat_bar)
        self.linkbar = LinkBar(
            self.engine, c, lambda: PAD_COLORS[len(self.cfg.sounds) % len(PAD_COLORS)],
            lambda: {m.fingerprint: m.name for m in self.cfg.sounds if m.fingerprint})
        self.linkbar.sound_ready.connect(self.on_downloaded)
        self.linkbar.played.connect(self.on_link_played)
        self.linkbar.board_busy = self._board_song_playing
        self.linkbar.up_next_changed.connect(lambda *__: self._update_chips(self.engine.playing()))
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
        self.grid.row_size = c.list_rows
        self.grid._spacing()
        self.grid.reorder.connect(self.on_reorder)
        # queued: the import (and any question it asks) runs after the drop returns,
        # so Explorer isn't frozen until a dialog is answered
        self.grid.files_dropped.connect(self.impctl.import_files,
                                        Qt.ConnectionType.QueuedConnection)
        self.grid.image_dropped.connect(self.padctl.set_picture, Qt.ConnectionType.QueuedConnection)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.grid)
        scroll.verticalScrollBar().valueChanged.connect(self._scroll_background_board)
        self._pad_scroll = scroll
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        # the pads fit the width
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left.addWidget(scroll, 1)
        scroll.verticalScrollBar().rangeChanged.connect(lambda *_r: self._fit_toolbar())
        self.grid.laid_out.connect(self._fit_toolbar)
        self._fit_toolbar()
        self._pads_home = (left, left.indexOf(scroll))   # the mini player borrows it
        self.ytresults.closed.connect(scroll.show)   # the results take the pads' place
        self.ytresults.closed.connect(self.catctl._cat_row.show)   # ...and the categories' row
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
        paste.activated.connect(self.padctl.paste_picture)
        # Ctrl+F anywhere on the page: into the search box
        find = QShortcut(QKeySequence.StandardKey.Find, page)
        find.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        find.activated.connect(self.focus_search)

        # ---- "now playing" chips: every sound playing, so each can be stopped (■) or
        # taken into the player (name) without clicking its pad, which would restart it
        self.playing_row = QWidget()
        # the playing chips wrap onto more lines: one line of four overlapping sounds'
        # chips (~900 px) turned a narrower window into the mini player, and every
        # playing sound must stay reachable, so none are left out. Up next only fills
        # what's left of the line (_fit_up_next)
        self._chips_hl = Flow(self.playing_row, gap=CHIPS_GAP)
        self._chips: dict[str, QWidget] = {}
        self._chip_ids: tuple = ()
        self._waiting_chips = None   # (Up next label, its chips, "+n more", how many wait)
        _Moved(self.playing_row, self._fit_up_next)
        self.playing_row.hide()
        left.addWidget(self.playing_row)


        f, th = bar()
        self.btn_pp = PlayButton()
        self.btn_pp.setObjectName("transport_play")
        self.btn_pp.setAccessibleName(_("Play / pause"))
        self.btn_pp.clicked.connect(self.toggle_play_pause)
        self._pp_icon = None
        self.btn_st = QPushButton()
        self.btn_st.setObjectName("transport_stop")
        self.btn_st.setAccessibleName(_("Stop"))
        self.btn_st.clicked.connect(self.stop_current)
        icons.set_icon(self.btn_st, "stop", size=16)
        self.btn_skip = QPushButton()
        self.btn_skip.setObjectName("transport_stop")   # the same quiet square as ■
        self.btn_skip.setAccessibleName(_("Skip to the next sound in Up next"))
        self.btn_skip.clicked.connect(self.skip_next)
        icons.set_icon(self.btn_skip, "next", size=16)
        for b in (self.btn_pp, self.btn_st, self.btn_skip):
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
        th.addWidget(self.btn_skip)
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
        self.board_read.connect(self.impctl._board_read)
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
        links = tuple(self.linkbar.up_next())   # web search / link Plays waiting their turn
        if (ids, queue, links) != self._chip_ids:
            self._chip_ids = (ids, queue, links)
            while self._chips_hl.count():
                item = self._chips_hl.takeAt(0)
                w = item.widget() if item else None
                if w:
                    w.deleteLater()
            self._chips = {}
            # Now playing first, then Up next: one line, read the way the app reads
            # (the Flow mirrors it in Arabic)
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
                    stop.setAccessibleName(_("Stop this sound"))
                    icons.set_icon(stop, "stop", "danger_text", size=12)
                    stop.setFixedSize(24, 24)
                    stop.clicked.connect(lambda __=False, s=sid: self._stop_one(s))
                    ch.addWidget(name)
                    ch.addWidget(stop)
                    self._chips_hl.addWidget(chip)
                    self._chips[sid] = chip
            self._waiting_chips = None
            if queue or links:
                lbl = QLabel(_("Up next"))
                lbl.setObjectName("muted")
                self._chips_hl.addWidget(lbl)
                # web search / link songs, then the board's queued sounds
                waiting: list[tuple] = [(title,
                            lambda __=False, i=i, q=links: self.linkbar.play_next(i, q),
                            lambda __=False, i=i, q=links: self.linkbar.drop_up_next(i, q))
                           for i, title in enumerate(links)]
                for i, sid in enumerate(queue):
                    m = self.meta(sid)
                    waiting.append((m.name if m else sid,
                                    lambda __=False, s=sid: self.select(s),
                                    lambda __=False, i=i, q=queue: self._unqueue(i, q)))
                chips = []
                for text, on_click, on_x in waiting[:QUEUE_CHIPS]:
                    chips.append(self._chip(text, _("Waits for the sounds playing to finish"),
                                            on_click, _("Take it out of the queue"), on_x))
                    self._chips_hl.addWidget(chips[-1])
                more = QLabel()
                more.setObjectName("muted")
                self._chips_hl.addWidget(more)
                self._waiting_chips = (lbl, chips, more, len(waiting))
            self._fit_up_next()
            # at least a line high, taller when the chips wrap (the Flow's height for
            # its width); a row that shrank and grew back with every overlapping
            # sound resized and repainted the whole board under it
            self.playing_row.setMinimumHeight(CHIPS_ROW_H)
            self.playing_row.setVisible(bool(ids) or bool(queue) or bool(links))
        for sid, chip in self._chips.items():
            sel = "true" if sid == self.current else "false"
            if chip.property("sel") != sel:
                chip.setProperty("sel", sel)
                chip.style().unpolish(chip)
                chip.style().polish(chip)

    def _fit_up_next(self):
        """Up next shares the Now playing line and never starts a line of its own: the
        playing chips always show (every playing sound keeps its ■), then as many Up
        next chips as fit beside them, then "+n more". If not one fits (a narrow
        window), Up next isn't shown at all."""
        if not self._waiting_chips:
            return
        lbl, chips, more, total = self._waiting_chips
        if not all(qt_valid(w) for w in (lbl, more, *chips)):
            return
        gap = CHIPS_GAP
        room = self.playing_row.width()
        for i in range(self._chips_hl.count()):   # the Now playing label and chips
            item = self._chips_hl.itemAt(i)
            w = item.widget() if item is not None else None
            if w is None:
                continue
            if w is lbl:
                break
            room -= w.sizeHint().width() + gap
        room -= lbl.sizeHint().width() + gap
        fm = more.fontMetrics()
        shown = 0
        for i, c in enumerate(chips):
            left = total - i - 1
            need = c.sizeHint().width() + gap
            tail = fm.horizontalAdvance(_("+{value} more", value=left)) + gap if left else 0
            if need + tail > room:
                break
            room -= need
            shown += 1
        lbl.setVisible(shown > 0)
        for i, c in enumerate(chips):
            c.setVisible(i < shown)
        more.setText(_("+{value} more", value=total - shown))
        more.setVisible(0 < shown < total)

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
        # a grid, not two columns: your mic and who's listening share its first row, so
        # they're always the same height and the cards under them line up
        cols = self._setup_cols = QGridLayout()
        sections.addLayout(cols)
        sections.addStretch(1)
        cols.setContentsMargins(0, 0, 0, 0)
        cols.setSpacing(16)
        lcol, rcol = self._setup_lr = QVBoxLayout(), QVBoxLayout()
        for i, col in enumerate((lcol, rcol)):
            col.setSpacing(16)
            cols.addLayout(col, 2, i)   # (rows 0 and 1: the card pairs, when side by side)
        page.setWidget(inner)

        # ---- how it works + the one thing to set in Discord
        # straight into the mic: what to do if a voice app chops the sounds up sits
        # behind an ⓘ (DESIGN section 4), not as a paragraph under "Nothing to set"
        self.btn_mictips = info_button(_("Sounds chopped up?"))
        self.btn_mictips.clicked.connect(self._show_mic_tips)
        self.btn_mictips.hide()
        # the heading: a mic, the title, its ⓘ, then the status pill at the end, all on
        # the title's cap height (DESIGN section 4, *Card headings*)
        self.mic_pill = QLabel(_("Not set up"))   # (its height: the text changes later)
        self.mic_pill.setObjectName("pill")
        self.mic_pill.hide()
        howcard, cv = card(_("Your virtual mic"), roomy=True, icon="mic",
                           beside=self.btn_mictips, end=(self.mic_pill,))
        assert howcard.heading_title is not None   # (titled)
        self.how_title = howcard.heading_title   # renamed for the other routes
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
        # working: a fresh copy or off, right here (Settings → Audio has every mic)
        from soundboard.ui.audiorecovery import explanation
        self.btn_michange = QPushButton(_("Change mic"))
        self.btn_michange.setProperty("quiet", True)
        self.btn_michange.setToolTip(_("Put your sounds into another mic instead"))
        self.btn_michange.clicked.connect(self.micctl._pick_mic)
        self.btn_micredo = QPushButton(_("Reinstall"))
        self.btn_micredo.setProperty("quiet", True)
        self.btn_micredo.setToolTip(explanation("reinstall"))
        self.btn_micredo.clicked.connect(lambda: self.micctl._ask_mic_effect("reinstall"))
        self.btn_micoff = QPushButton(_("Remove"))
        self.btn_micoff.setObjectName("danger")
        self.btn_micoff.setProperty("quiet", True)
        self.btn_micoff.setToolTip(explanation("remove"))
        self.btn_micoff.clicked.connect(lambda: self.micctl._ask_mic_effect("remove"))
        lines.addLayout(top)
        # line 2, when there's something to say or do: why, then the buttons
        self.mic_reason = QLabel()
        self.mic_reason.setWordWrap(True)
        self.mic_reason.setTextFormat(Qt.TextFormat.RichText)
        self.mic_reason.hide()
        lines.addWidget(self.mic_reason)
        self.mic_ways = Flow(gap=8)
        lines.addLayout(self.mic_ways)
        for b in (self.btn_michange, self.btn_micredo, self.btn_micoff):   # (wraps when narrow)
            b.hide()
            self.mic_ways.addWidget(b)
        box.hide()
        self._mic_icon: tuple[str, str] | None = None
        self._ways_in: bool | None = None   # which row the set-up buttons are in (_place_ways)
        cv.addWidget(box)
        cv.addWidget(box)
        self.helper_checked.connect(self.micctl._helper_known)
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
        self.btn_micupdate.clicked.connect(self.micctl._accept_mic_update)
        nh.addWidget(self.btn_micupdate, 0, Qt.AlignmentFlag.AlignVCenter)
        self.mic_update_note.hide()
        cv.addWidget(self.mic_update_note)
        self.setup_show = SetupShow(height=96, left=True)   # Bun builds it, by the buttons
        self.setup_show.done.connect(self.statusctl._update_flow)   # (the button's back, if needed)
        cv.addWidget(self.setup_show)
        self.btn_install = QPushButton(_("Install the free virtual cable"))
        self.btn_install.setObjectName("primary")
        self.btn_install.clicked.connect(
            lambda: self.micctl.attach_mic() if self.cfg.route == "mic"
            else self.micctl.install_cable())
        # what set_icon last put on it (only set when it changes)
        self._install_icon: tuple | None = None
        self.btn_attach = QPushButton(_("Straight into my mic instead"))   # (tip: no cable)
        self.btn_attach.setToolTip(_("Onion Board puts your sounds into your real mic, so "
                                     "Discord and games need no virtual cable and nothing picked"))
        self.btn_attach.clicked.connect(self.micctl.attach_mic)
        icons.set_icon(self.btn_attach, "mic")
        self.btn_attach.hide()
        # the ways to set it up, side by side at their own size (wraps when narrow)
        ways = Flow(gap=8)
        ways.addWidget(self.btn_attach)
        self.btn_usecable = QPushButton(_("Use the cable"))   # (in its tile, below)
        self.btn_usecable.setToolTip(_("Use a free virtual cable instead: you pick it as the "
                                       "mic in Discord and games"))
        self.btn_usecable.clicked.connect(self.micctl.use_cable_instead)
        icons.set_icon(self.btn_usecable, "cable")
        self.btn_usecable.hide()
        self.mic_attached.connect(self.micctl._mic_attached)
        self._attaching = False
        self._attach_release: Any = None   # busy.hold on btn_install while it's being set up
        self._settle_until = 0.0      # just set up: Windows is still loading it
        self._done_toast: str | None = None   # "done" / "updated": said once it works
        icons.set_icon(self.btn_install, "cable", "on_accent")
        ways.addWidget(self.btn_install)
        # Connect your chat is hidden until there's a chat to connect: its guide is here
        # meanwhile (that card held nothing else, while nothing was set up or on Nobody)
        self.btn_guide = self._guide_button()
        self.btn_guide.hide()
        self.btn_guide.setProperty("quiet", True)
        ways.addWidget(self.btn_guide)
        cv.addLayout(ways)
        self._ways = ways
        # straight into the mic works: the cable is only a fallback, so offer to remove it
        self.btn_rmcable = QPushButton(_("Remove"))   # (in the cable's tile: it says which)
        self.btn_rmcable.setAccessibleName(_("Remove the virtual cable"))
        self.btn_rmcable.setToolTip(_("Uninstalls VB-Cable. Your sounds go straight into your "
                                      "mic, so Onion Board doesn't need it"))
        icons.set_icon(self.btn_rmcable, "cable")
        self.btn_rmcable.clicked.connect(self.micctl.remove_cable)
        self.btn_rmcable.hide()
        self.cable_removed.connect(self.micctl._cable_removed)
        self._cable_gone = False   # removed this session (Windows lists it till a restart)
        # is VB-Cable's setup program there to remove it with: looked up on a thread (a
        # file check in Program Files, on every redraw, could stall on a slow disk) and
        # asked again when the devices are re-scanned. None = not known yet
        self._vb_setup: bool | None = None
        self._vb_setup_asking = False
        self.cable_setup_found.connect(self.micctl._cable_setup_found)
        self.rmcable_note = hint_label(
            _("<b>You don't need the virtual cable any more</b>, it was only the backup. Remove "
              "it, or keep it if another program uses it (Voicemeeter, another soundboard)."))
        self.rmcable_note.setTextFormat(Qt.TextFormat.RichText)
        self.rmcable_note.hide()
        cv.addWidget(self.rmcable_note)
        self.btn_rmcable.setProperty("quiet", True)   # (beside Use the cable, in its tile)
        self.btn_rescan = QPushButton(_("I've installed it: check again"))
        self.btn_rescan.clicked.connect(lambda: self.devctl.rescan_with_feedback(self.btn_rescan))
        icons.set_icon(self.btn_rescan, "reload")
        ways.addWidget(self.btn_rescan)   # with the other ways, not a row of its own
        # straight into the mic: the other ways as two tiles under the status, like the
        # setup guide's (before, two lone buttons said "use the cable" and "remove the
        # cable" side by side with no why, over an empty card)
        alt = self.mic_alt = QWidget()
        al = QVBoxLayout(alt)
        al.setContentsMargins(0, 4, 0, 0)
        al.setSpacing(10)
        head = QLabel(_("Optional: other ways to send your sounds"))
        head.setObjectName("section")
        head.setProperty("head", True)
        al.addWidget(head)
        tiles = self.mic_alt_tiles = TileRow()   # stacked when narrow, never clipped
        self.alt_cable, self.alt_cable_words = alt_tile(
            "cable", _("Virtual cable"), "", self.btn_usecable, self.btn_rmcable)
        tiles.addTile(self.alt_cable)
        self.btn_pickdev = QPushButton(_("Pick a device"))
        icons.set_icon(self.btn_pickdev, "sliders")
        self.btn_pickdev.clicked.connect(self.micctl._pick_send_device)
        self.alt_device = alt_tile(
            "sliders", _("Another device"),
            _("For streamers and mixers: send your sounds to Voicemeeter, OBS, a mixer or a "
              "capture card, or to nobody."), self.btn_pickdev)[0]
        tiles.addTile(self.alt_device)
        al.addWidget(tiles)
        alt.hide()
        cv.addWidget(alt)
        helpcard, hv = card(_("Connect your chat"), roomy=True, icon="speech")
        hv.addWidget(hint_label(_("Choose your app for the recommended microphone settings.")))
        chat = Flow(gap=8)   # at their own size, wrapping, not five full-width bars
        self.btn_chat = QPushButton(_("Make it sound clean in Discord"))
        self.btn_chat.setToolTip(_("The Discord settings that stop it chopping up your sounds, "
                                   "and a check that listens to what Discord does to them"))
        icons.set_icon(self.btn_chat, "headphones")
        self.btn_chat.clicked.connect(lambda: self.statusctl.show_chat_guide("discord"))
        chat.addWidget(self.btn_chat)
        self.btn_game = QPushButton(_("Set up game voice chat"))
        self.btn_game.clicked.connect(lambda: self.statusctl.show_chat_guide("game"))
        chat.addWidget(self.btn_game)
        self.btn_meeting = QPushButton(_("Zoom, Teams or a browser call"))
        self.btn_meeting.setToolTip(_("The settings in Zoom, Microsoft Teams and calls in a web "
                                      "page that stop them treating your sounds as noise"))
        self.btn_meeting.clicked.connect(lambda: self.statusctl.show_chat_guide("meeting"))
        chat.addWidget(self.btn_meeting)
        self.btn_nomic = QPushButton(_("Game has no microphone setting?"))
        self.btn_nomic.clicked.connect(self.micctl.open_windows_mic)
        chat.addWidget(self.btn_nomic)
        chat.addWidget(self._guide_button())
        hv.addLayout(chat)
        self.helpcard = helpcard


        # ---- devices
        devcard, av = card(_("Devices"), roomy=True, icon="headphones")
        self.dev_card = devcard
        av.addWidget(hint_label(_("Already set up for you, only change these if "
                                  "something's wrong.")))
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
            self.btn_cablefix, _("Switching the cable to 48 kHz…"), self.micctl.fix_cable_format,
            lambda ok: _("✓ Done") if ok and not self.micctl.cable_bad
            else _("Couldn't, see below")))
        self.btn_cablefix.hide()
        av.addWidget(self.btn_cablefix, 0, Qt.AlignmentFlag.AlignLeft)
        no_wheel(self.cb_main, self.cb_mon, self.cb_mic, self.cb_route)
        for cb, attr in ((self.cb_main, "main_device"), (self.cb_mon, "mon_device"),
                         (self.cb_mic, "mic_device"), (self.cb_route, "route")):
            cb.activated.connect(lambda _i, cb=cb, attr=attr: self.routectl.on_device(cb, attr))
        ref = QPushButton(_("Re-scan devices"))
        icons.set_icon(ref, "reload")
        ref.clicked.connect(lambda: self.devctl.rescan_with_feedback(ref))
        av.addWidget(ref, 0, Qt.AlignmentFlag.AlignLeft)

        # ---- who's listening: shape the sounds for the voice chat on the other end
        from soundboard.ui.destpanel import DestPanel
        self.dest_panel = DestPanel(self)
        destcard, dv = card(_("Who's listening"), _("Where people hear you: a game, a voice "
                                                    "chat app, or a stream. Your sounds are "
                                                    "shaped to come through clearly."),
                            roomy=True, icon="ear",
                            beside=self.dest_panel.help_btn)   # What do these do?
        dv.addWidget(self.dest_panel)
        dv.addStretch(1)   # as tall as your mic beside it: the room goes at the bottom

        # ---- sound shaping
        eqcard, ev = card(_("Equalizer and volume"), roomy=True, icon="sliders")
        self.eq_card = eqcard
        self.eq = EqPanel(c.eq_enabled, c.eq_target, c.eq_preset, c.eq_gains, fold=True)
        self.eq.changed.connect(self.on_eq)
        ev.addWidget(self.eq)
        self.chk_level = QCheckBox(_("Level volumes (all sounds equally loud)"))
        self.chk_level.setChecked(c.level_volumes)
        self.chk_level.toggled.connect(self.on_level_toggle)
        ev.addWidget(self.chk_level)
        for lay in (cv, av, ev):   # as tall as the card beside it: the room goes at the bottom
            lay.addStretch(1)
        # side by side, in pairs that share a grid row (the same height, so their tops
        # and bottoms line up): your mic and who's listening, then devices and the EQ;
        # connect your chat under the devices. All open: they fit the screen, so
        # nothing folds away. One column when narrow: what you check every day first
        self._setup_top = (howcard, destcard)
        self._setup_pairs = (self._setup_top, (devcard, eqcard))
        self._setup_wide = ((howcard, devcard, helpcard), (destcard, eqcard))
        self._setup_narrow = (howcard, destcard, devcard, helpcard, eqcard)
        self._setup_stacked = None
        self._stack_setup(False)
        self.on_eq(*self.eq.state())   # push the saved EQ into the engine
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
        grid = self._setup_cols
        for col in self._setup_lr:
            while col.count():
                take_out(col)   # the cards stay on the page, only their places change
        paired = [w for pair in self._setup_pairs for w in pair]
        for w in paired:
            grid.removeWidget(w)
        if not compact:
            for r, pair in enumerate(self._setup_pairs):
                for c, w in enumerate(pair):
                    grid.addWidget(w, r, c)
        grid.setColumnStretch(1, 0 if compact else 1)   # (stacked: column 1 is empty)
        grid.setColumnStretch(0, 1)
        lcol, rcol = self._setup_lr
        for w in self._setup_narrow if compact else ():
            lcol.addWidget(w)
        if not compact:   # the rest under the pairs, in their own column
            for col, cards in zip(self._setup_lr, self._setup_wide):
                for w in cards:
                    if w not in paired:
                        col.addWidget(w)
        for col in self._setup_lr:
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
    # ------------------------------------------------------------------ devices
    RESCAN_SHOWN_S = 3.0   # a Re-scan button shows what it found this long

    _direct_shown: Any = None


    DIRECT_GRACE_S = 4.0   # the board's own mic open this long, and still no sign of it
    SETTLE_S = 20.0        # after setting it up: how long Windows gets to load it
    MIC_SILENT_S = 20.0    # the mic sent only exact zeros this long: it's stuck (or muted)

    def run_setup(self, resumed: bool = False):
        """The quick-setup guide (first launch, or the Setup tab's Step-by-step guide).
        `resumed`: reopened by itself after the restart the virtual cable needed."""
        from soundboard.ui.setupwizard import SetupWizard
        wiz = SetupWizard(self, resumed=resumed)
        wiz.exec()
        free_dialog(wiz)
        self.routectl._prepare_all()
        # the installer's "from Soundpad" box waits for this, so its progress card
        # isn't stuck over the guide (a no-op once it's done)
        QTimer.singleShot(300, self.impctl.import_queued)

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
        return eng.virtual_mic_for(self.routectl._main_name())

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
            if self.alertctl.discord_problems():
                return lines, ""   # the urgent bar above says which, with Fix Discord
            if self.alertctl.discord_found:
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
            self.statusctl.show_chat_guide(app.guide)
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
        if net.allowed("radio") and self.tabctl.tab_on("radio"):
            r = RadioTab(self.engine, self.cfg, self._save_later, Meter)
            r.clip_ready.connect(self.on_clip)
        else:
            r = RadioOff()
            r.open_settings.connect(lambda: self.open_settings("privacy"))
        r.active_changed.connect(self.tabctl._radio_live)
        self.radio_page.addWidget(r)
        self.radio_page.setCurrentWidget(r)
        return r

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
        if not self.tabctl.tab_on(key):
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
            v.fx.chat_help.connect(lambda: self.statusctl.show_chat_guide("discord"))
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
        v.active_changed.connect(lambda on, k=key: self.tabctl._tab_live(k, on))
        return v

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

    def _follow_switches(self):
        """Settings > Privacy & security changed: the parts of the window that go
        online follow their switches."""
        self._radio_follow_switch()
        self.statusctl._update_flow()   # the cable's install button (_cable_follow_switch)
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
            shown = self.tabctl.tab_shown(key)
            if not shown and self.tabs.currentIndex() == i:
                self.tabs.move_to(0)   # (Settings, where this is done, stays up)
            self.tabs.setTabVisible(i, shown)
        self.tabctl._update_more_tabs()

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
        on = net.allowed("radio") and self.tabctl.tab_on("radio")
        if on == isinstance(self.radio, RadioTab):
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
        self.tabctl._radio_live(False)
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

    def _save_now(self, then=None):
        """The debounced save: the settings are copied now and written on the saver's
        thread (library.Saver), then _on_saved says how it went. `then(ok)` is called on
        the UI thread once this copy (or a newer one) is written, or failed to be."""
        self._saver.cfg = self.cfg
        self._saver.save(then)

    def _on_saved(self, ok: bool):
        """A failure (disk full, antivirus lock) is logged by the writer; here it's
        shown once so the user knows settings aren't sticking."""
        for then, was_ok in self._saver.finished():   # _save_now(then)s now on disk (or not)
            try:
                then(was_ok)
            except Exception:  # noqa: BLE001 - one mustn't stop the report
                log.exception("after saving settings")
        if ok:
            self._save_failed_shown = False
        elif not self._save_failed_shown:
            self._save_failed_shown = True
            self.toast(_("Couldn't save your settings, see the log in %APPDATA%\\OnionBoard."),
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
        self._pill_long = ""   # forces _update_flow to repaint its icon
        self.statusctl._update_status()
        return True

    def set_theme_texture(self, on: bool):
        """Textured (each theme's own pattern on the panels) or Plain (flat panels)."""
        if on == theme.textures_on:
            return
        self.set_option("theme_texture", on)
        theme.textures_on = on
        self.apply_theme(self.cfg.theme)

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

    QUICK_HOTKEYS = ("stop_hotkey", "pause_hotkey", "skip_hotkey", "random_hotkey",
                     "last_hotkey", "mic_hotkey", "hotkeys_off_hotkey", "overlay_hotkey")

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
    # (ui/ffmpegcontrol.py: the check, getting it, and its bar)
    @property
    def ffmpeg(self) -> ffmpegget.Health | None:
        """The last FFmpeg check's answer."""
        return self.ffctl.health

    def check_ffmpeg(self):
        self.ffctl.check()

    def fix_ffmpeg_clicked(self, btn: QPushButton, force: bool = False):
        self.ffctl.fix_clicked(btn, force)

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
        tip = tips.due(self.cfg, self.tabctl.tab_on)
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
            self.rmctl.show_deleted()
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
            dlg, self._settings_kept = self._settings_kept, None
            # nothing it shows changed since it closed: the same one, as it was left
            if dlg is not None and qt_valid(dlg) \
                    and self._settings_print() == self._settings_kept_print:
                dlg.show_page(page or "privacy")
                if getattr(dlg, "dev_combos", None):
                    dlg._sync_devices()
            else:
                if dlg is not None and qt_valid(dlg):
                    free_dialog(dlg)
                dlg = SettingsDialog(self, page or "privacy", lazy=True)
                dlg.finished.connect(lambda _r, d=dlg: self._settings_closed(d))
            self._settings_dlg = dlg
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
        had_focus = getattr(dlg, "had_focus", False) or _holds_focus(dlg)
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
        if self._settings_reusable(dlg):   # opened again as it is: no 100-300 ms rebuild
            rehome_crash_reports(dlg)
            old, self._settings_kept = self._settings_kept, dlg
            self._settings_kept_print = self._settings_print()
            if old is not None and old is not dlg and qt_valid(old):
                QTimer.singleShot(0, lambda: free_dialog(old))
        else:   # freed once its finished signal is over (deleting it inside that crashed)
            QTimer.singleShot(0, lambda: free_dialog(dlg))
        self.register_hotkeys()   # in case a capture was cancelled
        self._check_route_pick()

    # Settings pages showing state from outside the config (downloads, add-ons, Tor,
    # updates, the remote's add-ons): a kept Settings with one of them built is rebuilt
    SETTINGS_LIVE_PAGES = ("data", "connection", "help", "updates", "remote", "about")
    # config that changes without Settings showing it (counts, tips, the tab shown, the
    # Voice tab's speech) or that it keeps up to date itself (app_setup_changed)
    SETTINGS_PRINT_SKIP = ("sounds", "tab", "category", "tip_day", "tips_seen",
                           "update_checked", "whats_new_seen", "load_note", "speech",
                           "app_setup")

    def _settings_reusable(self, dlg) -> bool:
        if not qt_valid(dlg) or dlg.search_box.text():
            return False
        built = [k for i, k in enumerate(dlg._page_keys) if i not in dlg._unbuilt]
        return not any(k in self.SETTINGS_LIVE_PAGES for k in built)

    def _settings_print(self) -> str:
        """What a kept Settings shows: the config (less what it doesn't show) and the
        device lists. Anything else changed since it closed: a new one is built."""
        from dataclasses import fields
        c = self.cfg
        state = {f.name: getattr(c, f.name) for f in fields(c)
                 if f.name not in self.SETTINGS_PRINT_SKIP and not f.name.startswith("stats_")}
        for key, cb in (("~mic", self.cb_mic), ("~mon", self.cb_mon), ("~route", self.cb_route)):
            state[key] = (
                [cb.itemData(i) for i in range(cb.count())], cb.currentIndex())
        return repr(sorted(state.items()))

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
                self.routectl.set_route("mic", by_hand=True)
            elif code == routewarn.CABLE:
                # on the cable, then Setup: it shows the cable working, or installing it
                self.routectl.set_route("cable", cables[0] if cables else None, by_hand=True)
                self.tabs.setCurrentWidget(self.setup_page)
                if not cables:
                    self.micctl.install_cable()
        box.finished.connect(done)
        box.open()

    def apply_theme(self, name: str):
        # a still of the window with Bun over it while every widget restyles: no frame
        # of a half-styled window, and it fades to the new theme (ui/themecover.py)
        with themecover.covered(self, name):
            self._apply_theme(name)

    def _apply_theme(self, name: str):
        self.cfg.theme = theme.apply(QApplication.instance(), name)
        self._drop_spare_dialogs()
        icons.retheme()
        self.radio.retheme()
        self.apps.retheme()
        self.triggers.retheme()
        self.download_bar.retheme()
        self.mini_download_bar.retheme()
        self.ytresults.retheme()
        self._paint_mini_bun()
        if self.bunctl.bun_mode is not None:
            self.bunctl.bun_mode.retheme()
        pp, self._pp_icon = self._pp_icon, None
        self._set_pp_icon(pp or "play")
        self._pill_long = ""   # forces _update_flow to repaint its icon
        self.statusctl._update_status()   # the hints and flow, in this theme's status colours
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
        icons.set_icon(m.addAction(f"{news} (v{__version__})", self.updctl.show_whats_new), "info")

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
            self.cue("fail" if not self.tabctl.tab_on("voice") else "start" if on else "stop")
        elif action == "__voicehold__":
            if self._voice_was is None and self.tabctl.tab_on("voice"):
                self._voice_was = self.voice.fx.btn_power.isChecked()
            self._set_voice(True)
        elif action == "__replay__":
            self.save_replay()
        elif action == "__pause__":
            self._pause_clicked()
        elif action == "__skip__":
            self.skip_next()
        elif action == "__random__":
            self.play_random()
        elif action.startswith(RANDOM):
            self.play_random(action[len(RANDOM):])
        else:
            self.play(action)

    def _set_voice(self, on: bool):
        """The voice changer's big ON / OFF switch, from a hotkey."""
        if not self.tabctl.tab_on("voice"):
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
        self.catctl.set_category(name)
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
        others = self.routectl._main_name() is not None
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
        usage.used("stop-all")
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
        usage.used("pause")
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
        self.linkbar.drop_up_next()
        for sid in list(self._waiting):
            self._cancel_waiting(sid)
        self.engine.stop_all()
        self.radio.stop()
        self.apps.stop_all()
        self.triggers.cancel_pending()
        self.voice.stop_all()   # the voice changer and the other voices go off too

    def load_triggers(self):
        """Put the Onion Watch add-on into the Triggers tab (~0.4 s on the UI thread).
        At the start it's done while the window is built, behind the loading screen (it
        draws on its own thread), so opening the tab is instant; also when the tab is
        switched back on in Settings > Tabs. Runs once."""
        if not isinstance(self.triggers, TriggersTab) or not self.triggers.pending \
                or self._shut_down:   # (switched off: its stand-in has nothing pending)
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
        icons.set_icon(self.btn_yt, key, "accent", "accent", size=18)
        self._drop_link()   # the last site's song, if it's over: its card goes too
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
        self.catctl._cat_row.hide()
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
        self.catctl._cat_row.hide()
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
        pad = self._pad_for_link(r.url) if play else None
        if pad is not None:   # it's on the board already: the pad plays, from the start
            self.play(pad)
            return
        kind = "play" if play else "add"
        self.linkbar.open(r.url, r.title, r.seconds)
        self.ytresults.mark(r.url, kind)   # its button greys out until the link bar's done
        if not (self.linkbar.play_once() if play else self.linkbar.add()):
            self.ytresults.mark(r.url, kind, False)

    def _pad_for_link(self, url: str) -> str | None:
        """The board's sound downloaded from this link (its audio loaded), or None."""
        key = sourceinfo.link_key(url)
        if not key:
            return None
        for m in self.cfg.sounds:
            if (self.audio.get(m.id) is not None and isinstance(m.source, dict)
                    and sourceinfo.link_key(m.source.get("link", "")) == key):
                return m.id
        return None

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
        if (sid != LINK_ID and LINK_ID in self.engine.playing()
                and self._pad_for_link(self._link_url) == sid):
            # the web song played from a search, now saved as this pad: one song, so
            # it starts again from the top instead of a second copy playing over it
            self._stop_sound(LINK_ID)
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

    def _board_song_playing(self, playing=None) -> bool:
        """Is one of the board's sounds playing or paused? A web search's Play waits
        for it (Up next), as a pad's Play next does. A looping one (rain, a hum) is a
        background: that would never end, so a song doesn't wait for it."""
        playing = self.engine.playing() if playing is None else playing
        return any(sid in self._meta and not self._meta[sid].loop for sid in playing)

    def queue_sound(self, sid: str) -> bool:
        """Play `sid` once the board's sounds playing now have finished (now, if none are:
        True then)."""
        if (not self._pads_playing() and not self._queue
                and not self.linkbar.up_next() and LINK_ID not in self.engine.playing()):
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

    def skip_next(self):
        """The player's ⏭ (and its hotkey): the next sound in Up next starts now. The
        board's queue waits for every pad sound, so they all make way (as Play all
        does); a web search's Up next waits for its song. Nothing waiting: it stops
        the player's sound, like ■."""
        if self._queue:
            for sid in self.engine.playing():   # (it waits for a web search's song too)
                if sid in self._meta or sid == LINK_ID:
                    self.engine.stop(sid)
            self._drop_link()
            self._next_in_queue()
        elif self.linkbar.up_next():
            for sid in self.engine.playing():   # it waits for your sounds too
                if sid == LINK_ID or (sid in self._meta and not self._meta[sid].loop):
                    self.engine.stop(sid)
            self.linkbar.play_next()
        elif self.current:
            self._stop_sound(self.current)
            self.start_frac = 0.0
        else:
            self.cue("fail")
            return
        self._wake()

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
        if sid == LINK_ID:   # a web song isn't on the board: stopped, it leaves the player
            self._drop_link()
        if sid != self.current and self.current:
            return
        others = [s for s in self.engine.playing()
                  if s != sid and (s in self._meta or s == LINK_ID)]
        if others:
            self.select(others[-1])

    def _drop_link(self):
        """Take a stopped web song out of the player. It stayed there as the player's
        sound, and once its card was gone (another site searched) nothing took it out:
        ■ only stopped it and its name sat in the bar for good."""
        if LINK_ID in self.engine.playing():
            return   # still playing or paused: the player keeps it
        self._link_meta, self._link_url = None, ""
        self.audio.pop(LINK_ID, None)
        if self.current == LINK_ID:
            self.current = None
            self.start_frac = 0.0
            self._set_np_name(_("Pick a sound"))
            self.np_name.setToolTip(_("Select a sound pad to use these playback controls."))

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

        def answer(out):
            return (sid, out, gain, gen) if gen == self._preview_gen else worker.SKIP

        def run():
            try:
                src = load_original(m)
                if len(src) > PREVIEW_WHOLE_S * SR:   # long: only what plays first
                    part, pfx = soundfx.preview_part(src, fx, PREVIEW_S)
                    out = soundfx.render(part, pfx)
                else:
                    # into the cache file for these effects: saving them afterwards
                    # finds it rendered
                    out = library.render_cached(m.id, src, fx,
                                                cancel=lambda: gen != self._preview_gen)
            except library.Cancelled:
                return worker.SKIP   # a newer preview (or the dialog closed): nothing to play
            return answer(out)
        worker.run(run, self.bridge.preview, "fx-preview", error=lambda _e: answer(None),
                   owner=self)
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
                p.menu.connect(self.padctl.pad_menu)
                p.nudge.connect(self.padctl.nudge_volume)
                p.rename.connect(self.rename_sound)
                p.edit.connect(self.editctl.edit)
                self.pads[m.id] = p
            p.state = "ready" if m.id in self.audio else p.state
            p.selected = m.id == self.current
            ordered.append(p)
        self.grid.set_pads(ordered, layout=False)   # laid out once, by the filter next
        self.apply_filter(self.search.text())
        self.statusctl._update_status()

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
        cat, sub = self.cfg.category, self.cfg.subcategory
        changed = False
        for m in self.cfg.sounds:
            p = self.pads.get(m.id)
            if p:
                hit = not t or t in m.name.lower() or any(t in g.lower() for g in m.tags)
                hide = not hit or not library.in_view(m.tags, cat, sub)
                changed = changed or bool(p.property("filtered")) != hide
                p.setProperty("filtered", hide)
        if changed or not lazy:
            self.grid.relayout(force=True)
            self.selection.sync()

    def _fit_toolbar(self):
        """The toolbar spans the pads: in by the grid's margin on both sides, and by the
        scroll bar too while it shows (and the odd pixels a row can't split). The
        category tabs start on the same line as the toolbar and the first card."""
        m = self.grid.grid.contentsMargins()
        sb = self._pad_scroll.verticalScrollBar()
        right = (m.right() + self.grid.slack()
                 + (sb.sizeHint().width() if sb.maximum() > 0 else 0))
        hold = self._toolbar_hold.layout()
        row = self.catctl._cat_row.layout()
        if hold is None or row is None:
            return
        hold.setContentsMargins(m.left(), 0, right, 0)
        row.setContentsMargins(m.left(), 0, 0, 0)
        if sub := self.catctl._sub_row.layout():
            sub.setContentsMargins(m.left(), 6, right, 0)

    # ------------------------------------------------------------------ search, rename
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

    # ------------------------------------------------------------------ loading sounds
    def _load_all(self):
        # one still being loaded by an earlier call (a pack import or Undo during a slow
        # first load) isn't decoded again: two writers of one cache file garble it
        todo = [m for m in self.cfg.sounds if m.id not in self.audio and m.id not in self._loading]
        self._loading.update(m.id for m in todo)
        prev = self._load_thread

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
                finally:
                    self._loading.discard(m.id)
            if prev is not None:   # done only once the sounds it skipped are, too
                prev.join()
            live = self._live_metas()   # as of now, not of the start
            prune_cache(cache_keep(live))
            thumbs.prune({m.image for m in live if m.image})
            trash.prune()   # what's been in Recently deleted for too long
            log.info("loaded %d sounds in %.1fs", len(todo), time.monotonic() - t0)
        self._load_thread = worker.run(run, name="load")

    def on_loaded(self, sid, data, err):
        # removed while it was loading (the index can lag behind cfg.sounds: check both)
        if (sid != LINK_ID and sid not in self._meta
                and all(m.id != sid for m in self.cfg.sounds)):
            for i, (m, index, _d) in enumerate(self.rmctl._removed):
                if m.id == sid:   # still undo-able: keep the audio with it
                    self.rmctl._removed[i] = (m, index, data)
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
        return list(self.cfg.sounds) + [m for m, _i, _d in list(self.rmctl._removed)]

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
        self.catctl._tag_new(meta)
        self.cfg.sounds.append(meta)
        self._index()
        self.audio[meta.id] = data
        usage.used("clip")
        usage.step(self.cfg, "added-sound")
        worker.run(lambda: self.engine.prepare(meta.id, data), name="prepare")
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
        self.catctl._tag_new(meta)
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
                         how=self.padctl._sort_names()[self.cfg.pad_sort]))
            return
        self.cfg.sounds.remove(m)
        self.cfg.sounds.insert(min(target, len(self.cfg.sounds)), m)
        self._save_now()
        self._rebuild_pads()

    # ------------------------------------------------------------------ order and view
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

    def _hotkey_taken(self, combo: str) -> bool:
        """Does a sound, an app-wide action, the push-to-talk key or a category's
        random-sound key already have `combo`?"""
        return (any(o.hotkey == combo for o in self.cfg.sounds)
                or any(getattr(self.cfg, attr) == combo for attr, *__ in HOTKEY_ACTIONS)
                or self.cfg.ptt_key == combo
                or combo in self.cfg.category_hotkeys.values())

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
        self.catctl._fill_categories()
        self.register_hotkeys()

    def preload_dialogs(self):
        """Behind the loading screen: Settings (its first page) and an Edit sound are
        built now, so even the first click of the cog or Edit opens at once (each took
        100-300 ms to build); Settings' other pages follow one at a time once it's up."""
        if self._settings_dlg is None and self._settings_kept is None:
            dlg = SettingsDialog(self, "privacy", lazy=True)
            dlg.hide()
            dlg.finished.connect(lambda _r, d=dlg: self._settings_closed(d))
            _polish(dlg, self._content.size())
            self._settings_kept, self._settings_kept_print = dlg, self._settings_print()
            self._preload_pages = [i for i, k in enumerate(dlg._page_keys)
                                   if i in dlg._unbuilt and k not in self.SETTINGS_LIVE_PAGES]
            QTimer.singleShot(1500, self._preload_next_page)
        if self._spare_editor is None and self.cfg.sounds:
            d = self.editctl._new_editor(self.cfg.sounds[0], "sound")
            d.hide()
            _polish(d)
            self._spare_editor = d

    def warm_settings(self):
        """Still behind the loading screen, the window up: the kept Settings goes in
        the window's place once, with drawing off (nothing changes on screen), so Qt's
        first-show work (~100 ms) isn't left for the first click of the cog."""
        dlg = self._settings_kept
        if dlg is None or not qt_valid(dlg) or not self.isVisible() or self.settings_open():
            return
        self.setUpdatesEnabled(False)
        try:
            self._content.addWidget(dlg)
            self._content.setCurrentWidget(dlg)
            QApplication.processEvents()
            dlg.grab()
        finally:
            self._content.setCurrentWidget(self._tabs_area)
            self._content.removeWidget(dlg)
            dlg.hide()
            self.setUpdatesEnabled(True)

    def warm_triggers(self):
        """Like warm_settings, for the Triggers tab: Onion Watch is loaded while the
        window is built, but its first show at full size still lays out the list and
        builds the editor beside it (~100-300 ms). Shown once here, with drawing off and
        the tab's signals quiet (nothing saved or counted), then the tab picked before."""
        t = self.triggers
        if (not isinstance(t, TriggersTab) or t.panel is None or not self.isVisible()
                or self.settings_open() or self.tabs.currentWidget() is t):
            return
        before = self.tabs.currentIndex()
        self.setUpdatesEnabled(False)
        self.tabs.blockSignals(True)
        try:
            self.tabs.setCurrentWidget(t)
            QApplication.processEvents()
            t.grab()
        finally:
            self.tabs.setCurrentIndex(before)
            self.tabs.blockSignals(False)
            self.setUpdatesEnabled(True)

    def _preload_next_page(self):
        """One more of the kept Settings' pages built (~20-60 ms each), while it's closed."""
        dlg, pages = self._settings_kept, getattr(self, "_preload_pages", [])
        if dlg is None or not qt_valid(dlg) or not pages:
            return
        dlg._build_page(pages.pop(0))
        _polish(dlg, self._content.size())
        QTimer.singleShot(60, self._preload_next_page)

    def _drop_spare_dialogs(self):
        """The kept Edit sound and Settings go (a new theme: built again in it)."""
        for attr in ("_spare_editor", "_settings_kept"):
            d = getattr(self, attr, None)
            setattr(self, attr, None)
            if d is not None and qt_valid(d):
                free_dialog(d)

    # ------------------------------------------------------------------ backup
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
        self._tray_bun = menu.addAction(self._bun_icon(), _("Turn into Bun"),
                                        self.bunctl.enter_bun_mode)
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

    # ------------------------------------------------------------------ Bun mode
    def show_from_tray(self):
        self.bunctl._bun_away()
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

    def set_autostart(self, on: bool) -> bool:
        return autostart.set_enabled(on, self.cfg.autostart_hidden)

    def set_autostart_hidden(self, hidden: bool):
        self.set_option("autostart_hidden", hidden)
        autostart.refresh(hidden)

    # ------------------------------------------------------------------ usage count
    def send_usage(self):
        """The anonymous daily usage count, if it's due and switched on (usage.py)."""
        usage.maybe_send(self.cfg, self.bridge.counted.emit, app_dir=library.APP_DIR)

    def _usage_counted(self, apply):
        """A usage count went: here, on the UI thread that also adds to them, its
        stats_* are cleared (only what it sent) and saved."""
        apply()
        self._save_later()

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
    # visualisers while it's on screen, even behind another program, TICK_IDLE_MS while it's
    # hidden in the tray or minimised (nothing to paint, but push-to-talk, the stream
    # watchdog must go on). Qt tells us through these three
    # events and applicationStateChanged.
    def showEvent(self, ev):
        shellicon.on_show(self)   # the Jump List icon, before the taskbar button exists
        shellicon.paint_background(self, theme.T["bg"])
        super().showEvent(ev)
        if not getattr(self, "_start_focus_set", False):
            # (again here: start-up can still switch the tab after __init__, to Setup)
            self._start_focus_set = True
            self.tabctl._focus_open_tab()
        self._set_tick_rate()
        note, self._pending_note = getattr(self, "_pending_note", None), None
        if note:   # held back while the window was in the tray (see __init__)
            QTimer.singleShot(400, lambda: self._tell_load_note(note))
        later, self.updctl._whats_new_later = getattr(self.updctl, "_whats_new_later", None), None
        if later is not None:   # held back while the window was in the tray
            QTimer.singleShot(700, lambda: self.updctl.whats_new(later))
        # an older mic part: its update is offered a moment after the window opens
        QTimer.singleShot(MIC_OFFER_MS, self, self.micctl._offer_mic_update)

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
        if not self._ui_live and not self.overlay.is_open and not self.bunctl.bun_up():
            return TICK_IDLE_MS
        if not self._tick_busy:   # nothing moves: 10 ticks a second instead of 30
            return TICK_QUIET_MS
        # Visible and busy: meters stay smooth even when a game has focus.
        return TICK_MS

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
                or self.radio.is_active() or bool(e.aux)
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
                self.micctl._follow_mic_effect()
            if e.check_streams() or sum(e.xruns.values()) != self.statusctl._xruns_shown:
                self.statusctl._update_status()
            elif self.cfg.route == "mic" and self.micctl._direct_health() != self._direct_shown:
                self.statusctl._update_flow()
            self.voice.poll()
        playing = e.playing()
        if self._queue and LINK_ID not in playing and not any(sid in self._meta
                                                              for sid in playing):
            self._next_in_queue()   # it waits for a web search's song too
            playing = e.playing()
        if (LINK_ID not in playing and self.linkbar.up_next()
                and not self._board_song_playing(playing) and self.linkbar.play_next()):
            playing = e.playing()   # the web search song ended: the next one waiting
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
        if self.bunctl.bun_mode is not None and self.bunctl.bun_mode.isVisible():
            bar = self.download_bar
            self.bunctl.bun_mode.tick(
                live=live, level=e.level_play, sending=e.sending, mic=self.cfg.mic_enabled,
                paused=any(paused for sid, (_p, paused) in playing.items()
                           if sid in self._meta or sid == LINK_ID),
                downloading=bar.running(), failed=bar.failed_count())
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

    def _heard_level(self) -> float:
        """The "What others hear" meter. Sending into the mic but not in it yet (no mic
        effect): voice apps still take the real mic as it is, so others hear your voice
        even with nothing sent; the meter showed nothing while you talked."""
        e = self.engine
        if self.cfg.route == "mic" and not e.main_direct and e.mic_stream is not None:
            return max(e.level_main, e.level_mic)
        return e.level_main

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
        self.out_meter.set_level(self._heard_level())
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
            self.statusctl._update_flow(talking)

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
                return sid, videos.get(sid)
            except Exception:  # noqa: BLE001 - never leave _video_asking stuck
                log.debug("video lookup failed", exc_info=True)   # (a sleeping drive)
                return sid, None
        worker.run(look, self.video_found, "video-lookup", error=(sid, None))

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
        f.add(10, "w", self.padctl._fit_size_picker)
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
        if getattr(self, "_refitting", False):
            return
        self._refitting = True
        try:
            with responsive.hold_updates(self):
                self._refit_layout()
        finally:
            self._refitting = False

    def _refit_layout(self):
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
            # close_settings requests a refit, which the outer transaction guards.
            # Finish it here with Settings removed, before painting resumes.
            self._refit_layout()
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
        with responsive.hold_updates(self):
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
            QTimer.singleShot(0, lambda: self.impctl.import_files(expand_dropped(files)))

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
        if self.bunctl.bun_mode is not None:   # (cfg.bun["on"] stays: it starts as Bun next time)
            self.bunctl.bun_mode.close()
        for step in (self.rmctl._finish_removals, self.rmctl._wait_bin, self.timer.stop,
                     self._voice_timer.stop, self.devctl._default_poll.stop,
                     self.alertctl._discord_poll.stop, self._release_ptt,
                     self._remember_usage, self.cfg.save, self.overlay.shutdown,
                     self.hotkeys.stop, self.replay.stop, self.remote.stop,
                     self.remctl._stop_remote_addons,
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
