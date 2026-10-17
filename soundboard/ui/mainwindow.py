"""The main window: pads, transport, web search, the audio panel, auto push-to-talk."""
from __future__ import annotations

import re
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, overload

import numpy as np
from PySide6.QtCore import (QEvent, QObject, QPoint, QSignalBlocker,
                            QSize, Qt, QTimer, Signal)
from PySide6.QtWidgets import (QApplication, QDialog, QMainWindow, QMenu, QMessageBox, QPushButton,
                               QSystemTrayIcon)

from soundboard import theme, ytworker
from soundboard.engine import SR, Engine
from soundboard import exitwatch
from soundboard import (appaudio, autostart, library, remote, reset, trash, voicesdk)
from soundboard import (ffmpegget, net, netlog,
                        profiles, quality, shellicon, thumbbar, tor,
                        usage, watchaddon)
from soundboard.replay import InstantReplay
from soundboard.library import (Config,
                                SoundMeta)
from soundboard.ui.crashdialog import free_dialog
from soundboard.ui import restyled, worker
from soundboard.ui.ffmpegcontrol import FfmpegControl
from soundboard.ui.netcontrol import NetControl
from soundboard.ui.soundscontrol import SoundsControl
from soundboard.ui.windowbuild import WindowBuilder, version_text  # noqa: F401  (settings imports it here)
from soundboard.ui.fitcontrol import FitControl
from soundboard.ui.transportcontrol import TransportControl
from soundboard.ui.tickcontrol import TickControl
from soundboard.ui.tickcontrol import TICK_MS
from soundboard.ui.searchcontrol import SearchControl
from soundboard.ui.playbackcontrol import PlaybackControl
from soundboard.ui.appsetupcontrol import AppSetupControl
from soundboard.ui.languagecontrol import LanguageControl
from soundboard.ui.tipcontrol import TipControl
from soundboard.ui.hotkeycontrol import HotkeyControl
from soundboard.ui.aboutcontrol import AboutControl
from soundboard.ui.themecontrol import ThemeControl
from soundboard.ui.settingscontrol import SettingsControl
from soundboard.ui.tabcontrol import TabControl
from soundboard.ui.statuscontrol import StatusControl
from soundboard.ui.miccontrol import MIC_OFFER_MS, MicControl
from soundboard.ui.routecontrol import RouteControl
from soundboard.ui.devicecontrol import DeviceControl
from soundboard.ui.editcontrol import EditControl
from soundboard.ui.removecontrol import RemoveControl
from soundboard.ui.padcontrol import PadControl
from soundboard.ui.remoteaccess import RemoteAccess
from soundboard.ui.buncontrol import BunControl
from soundboard.ui.alertcontrol import AlertControl
from soundboard.ui.categorycontrol import CategoryControl
from soundboard.ui.importcontrol import ImportControl
from soundboard.ui.updatecontrol import UpdateControl
from soundboard.ui import toast as toastmod
from soundboard.ui import (a11y, appstate, busy, icons, livesize, responsive,
                           splash, taboff, tabtours)
from soundboard.ui.linkbar import PLAY_ID as LINK_ID
from soundboard.ui.logowidget import glow_icon
from soundboard.ui import sidebar
from soundboard.ui.spacekey import SpaceKey
from soundboard.ui.overlay import Overlay
from soundboard.ui.appspanel import AppsTab
from soundboard.ui.triggershost import BoardHost
from soundboard.ui.triggerstab import TriggersTab
from soundboard.ui.radiopanel import RadioOff, RadioTab
from soundboard.ui.storetab import PREVIEW as STORE_PREVIEW, StoreTab
from soundboard.ui.voicepanel import VoicePanel
from soundboard.ui.widgets import (Meter, Pad, expand_dropped)
from soundboard.winkeys import Hotkeys
from soundboard.i18n import _

log = logging.getLogger(__name__)


TOAST_EXPAND = QSize(900, 640)   # a shrunk card clicked: the window grows to this
DEFAULT_POLL_MS = 1500   # how often Windows' default output is checked
DISCORD_POLL_MS = 10000  # how often Discord's voice settings are looked at (discordcfg)
RAW_POLL_MS = 2000       # how often the apps recording the mic are counted (rawmic)
TLS_WARM_MS = 2500     # Qt's TLS is set up this long after the start (_warm_tls)
TIP_DELAY_MS = 8000    # the first tip waits this long after the start
FF_CHECK_MS = 1500     # the FFmpeg check's answer is taken this long after the start
VOICE_POLL_MS = 3000  # how often the game in front is looked at (soundboard.voicesdk)


# the colour wrapper old status-line texts carry (MainWindow.say drops it)
_TONE_SPAN = re.compile(r"<span style='color:[^']*'>(.*)</span>", re.S)



if TYPE_CHECKING:
    from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGraphicsOpacityEffect,
                                   QGridLayout, QHBoxLayout, QLabel, QLineEdit, QProgressBar,
                                   QStackedWidget, QVBoxLayout, QWidget)
    from soundboard import tips
    from soundboard.ui import moretabs
    from soundboard.ui.appspanel import ElidedLabel
    from soundboard.ui.destpanel import DestPanel, ModeButton
    from soundboard.ui.downloadbar import DownloadBar
    from soundboard.ui.dropveil import DropVeil
    from soundboard.ui.linkbar import LinkBar
    from soundboard.ui.logowidget import LogoWidget
    from soundboard.ui.padbatch import PadSelection
    from soundboard.ui.panel import EqPanel, Flow, TileRow, ViewToggle, VolumeControl
    from soundboard.ui.playbutton import PlayButton
    from soundboard.ui.setupshow import SetupShow
    from soundboard.ui.sidebar import SideTabs
    from soundboard.ui.speedpitch import SpeedPitchButton
    from soundboard.ui.widgets import (DropdownMenu, EdgeMatch, NameAndSeek, PadGrid, SeekSlider,
                                       WindowRoot)
    from soundboard.ui.windowbuild import BannerButton, Pulse
    from soundboard.ui.ytsearch import SearchResults

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
    render_progress = Signal(str, int, float)  # id, which render (gen), how far 0..1
    ffmpeg = Signal(object, object)            # ffmpegget.Health, after a fix: "" or its error
    ffmpeg_progress = Signal(int)              # percent of FFmpeg downloaded (-1: not known)


class MainWindow(QMainWindow):
    # ---- the window's parts: made once by WindowBuilder (ui/windowbuild.py), used by
    # the window and its controllers
    about_menu: DropdownMenu
    _act_export_cat: Any
    _add_menu: DropdownMenu
    also_rows: Any
    also_views: Any
    alt_cable: Any
    alt_cable_words: Any
    alt_device: Any
    apps: Any
    _attach_release: Any
    _attaching: bool
    _banner_fx: QGraphicsOpacityEffect
    _body_lay: Any
    btn_about: QPushButton
    btn_add: QPushButton
    btn_air: QPushButton
    btn_attach: QPushButton
    btn_bin: QPushButton
    btn_cablefix: QPushButton
    btn_chat: QPushButton
    btn_check: QPushButton
    btn_folder: QPushButton
    btn_game: QPushButton
    btn_guide: Any
    btn_install: QPushButton
    btn_keys: QPushButton
    btn_meeting: QPushButton
    btn_michange: QPushButton
    btn_micoff: QPushButton
    btn_micredo: QPushButton
    btn_mictips: Any
    btn_micupdate: QPushButton
    btn_more: QPushButton
    btn_more_tabs: QPushButton
    btn_nomic: QPushButton
    btn_pickdev: QPushButton
    btn_pp: PlayButton
    btn_rescan: QPushButton
    btn_rmcable: QPushButton
    btn_rows: QPushButton
    btn_skip: QPushButton
    btn_st: QPushButton
    btn_update: sidebar.UpdateCard
    btn_usecable: QPushButton
    btn_video: QPushButton
    btn_view: QPushButton
    pad_view_toggle: ViewToggle
    btn_yt: QPushButton
    _cable_gone: bool
    card_meter: Meter
    cat_bar: Any
    cb_main: Any
    cb_mic: Any
    cb_mon: Any
    cb_route: QComboBox
    _chip_ids: tuple
    _chips: dict[str, QWidget]
    _chips_hl: Flow
    chk_level: QCheckBox
    chk_mic: QCheckBox
    chk_monitor: QCheckBox
    _content: QStackedWidget
    _deck_rows: list[QHBoxLayout]
    _deck_tabs: list[QPushButton]
    _deck_titles: list[QWidget]
    _decks: list[tuple[QWidget, ...]]
    dest_panel: DestPanel
    dev_card: Any
    _dl_lay: QHBoxLayout
    _done_toast: str | None
    download_bar: DownloadBar
    drop_veil: DropVeil
    eq: EqPanel
    eq_card: Any
    ff_bar: Any
    _fit_tab: Any
    flow_mic: QLabel
    flow_out: QLabel
    flow_snd: QLabel
    _full: WindowRoot
    _full_row: QHBoxLayout
    gear: QPushButton
    grid: PadGrid
    helpcard: Any
    how_title: Any
    hp_lbl: Any
    _install_icon: tuple | None
    lang_bar: QFrame
    lang_btn: QPushButton
    lang_hide: Any
    lang_lbl: QLabel
    _lang_offered: Any
    _link_wait: QTimer
    linkbar: LinkBar
    logo: LogoWidget
    mic_alt: QWidget
    mic_alt_tiles: TileRow
    mic_banner: BannerButton
    mic_flow: QFrame
    _mic_icon: tuple[str, str] | None
    mic_lbl: Any
    mic_line: QLabel
    mic_meter: Any
    mic_pill: QLabel
    mic_reason: QLabel
    mic_state_icon: QLabel
    mic_status: QFrame
    mic_sub: ElidedLabel
    mic_update_icon: Any
    mic_update_note: QFrame
    mic_update_text: QLabel
    mic_voice: QFrame
    mic_voice_sub: ElidedLabel
    mic_ways: Flow
    mini_air: QPushButton
    mini_bun: QPushButton
    _mini_card: QFrame
    mini_connection: QPushButton
    mini_download_bar: DownloadBar
    mini_mic: QPushButton
    mini_name: ElidedLabel
    mini_pp: PlayButton
    mini_seek: SeekSlider
    mini_skip: QPushButton
    mini_st: QPushButton
    mini_stop: QPushButton
    mini_time: QLabel
    _mini_v: QVBoxLayout
    mixer: Any
    _mixer_layout: QHBoxLayout
    _mixer_one: bool
    _mixer_tight: bool
    mode_btn: ModeButton
    more_menu: moretabs.Menu
    _name_seek: NameAndSeek
    _bar_edges: EdgeMatch   # seek slider and "What others hear" meter end in line
    np_name: QLabel
    np_time: QLabel
    out_meter: Meter
    _packs_menu: Any
    _pad_scroll: Any
    _pad_size: Any
    _pad_size_wait: QTimer
    _pads_home: Any
    _pads_scroll: Any
    _pages: QStackedWidget
    pill: QPushButton
    playing_row: QWidget
    _pp_icon: str | None
    _pulse: Pulse
    radio: RadioTab | RadioOff
    radio_page: QStackedWidget
    _radio_steps: list
    rail: sidebar.SideRail
    rmcable_note: Any
    _row_size: Any
    search: QLineEdit
    _search_tip: Any
    _search_typed: str | None
    _search_wait: QTimer
    seek: SeekSlider
    selection: PadSelection
    _settle_until: Any
    setup_bar: QFrame
    _setup_cols: QGridLayout
    setup_connection: QLabel
    setup_hint: Any
    setup_lbl: QLabel
    _setup_lr: Any
    _setup_cards: Any
    _setup_narrow: Any
    setup_no: QPushButton
    setup_page: Any
    _setup_pairs: Any
    setup_show: SetupShow
    _setup_stacked: bool | None
    _setup_top: Any
    _setup_wide: Any
    setup_x: QPushButton
    setup_yes: QPushButton
    _site_menu: DropdownMenu
    _size_tight: bool
    _sounds_lay: Any
    sounds_page: Any
    sounds_toolbar: QFrame
    speed_btn: SpeedPitchButton
    step_lbl: QLabel
    stop_btn: QPushButton
    tab_info: dict[str, tuple[str, str]]
    tabs: SideTabs
    _tabs_area: QWidget
    _tabs_box: QWidget
    _tabs_lay: Any
    tagline: sidebar.ClickLabel
    tip: tips.Tip | None
    tip_bar: QFrame
    tip_btn: QPushButton
    tip_lbl: QLabel
    _toolbar_hold: QWidget
    transport: Any
    _transport_vol: Any
    triggers: Any
    urgent_bar: QFrame
    urgent_btn: QPushButton
    urgent_lbl: QLabel
    urgent_prog: QProgressBar
    urgent_sub: QLabel
    _vb_setup: bool | None
    _vb_setup_asking: bool
    _video_asking: str | None
    _video_for: tuple[str | None, Path | None]
    _video_win: Any
    voice: Any
    voice_meter: Meter
    voice_only: QPushButton
    store: Any   # the Store tab (StoreTab), or its stand-in while switched off
    vol_mic: VolumeControl
    vol_mon: VolumeControl
    vol_sound: VolumeControl
    _up_next_chip: Any
    _up_next_popup: Any
    _ways: Any
    _ways_in: bool | None
    wordmark: QLabel
    ytresults: SearchResults

    # ---- kept by Settings → Remote across openings (ui/settingspages/addons.py)
    pocket_card: Any
    pocket_checked: float
    pocket_offer: Any

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
        self.netctl = NetControl(self)
        self.soundctl = SoundsControl(self)
        self.builder = WindowBuilder(self)
        self.fitctl = FitControl(self)
        self.transctl = TransportControl(self)
        self.tickctl = TickControl(self)
        self.searchctl = SearchControl(self)
        self.playctl = PlaybackControl(self)
        self.appsetctl = AppSetupControl(self)
        self.langctl = LanguageControl(self)
        self.tipctl = TipControl(self)
        self.hkctl = HotkeyControl(self)
        self.aboutctl = AboutControl(self)
        self.themectl = ThemeControl(self)
        self.setctl = SettingsControl(self)
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
        tor.qt_status().changed.connect(self.netctl._on_tor)
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
        self.hotkeys.fired.connect(self.hkctl.on_hotkey)
        self.hotkeys.released.connect(self.hkctl.on_hotkey_released)
        self.hotkeys.failed_changed.connect(self.hkctl.on_hotkeys_failed)
        self.hotkeys.midi.busy_changed.connect(self.hkctl.on_midi_busy)
        self.replay = InstantReplay(self.cfg.replay_seconds)
        # buttons in the taskbar's hover preview, like Discord's mute / deafen
        tb = thumbbar
        def counted(do):   # a taskbar button pressed (usage.py), then what it does
            return lambda: (usage.used("taskbar-buttons"), do())
        self.thumbbar = tb.ThumbBar(self, {
            tb.LAST: counted(self.playctl.play_last),
            tb.PAUSE: counted(self.playctl._pause_clicked),
            tb.STOP: counted(self.playctl._stop_all_clicked),
            tb.RANDOM: counted(self.playctl.play_random),
            tb.LIVE: counted(lambda: self.set_sending(not self.engine.sending))})
        self._radio_paused = None   # the station Pause stopped, for Play to turn back on
        self.replay.state_changed.connect(self.hkctl.on_replay_state)
        self.overlay = Overlay(self, self.cfg.overlay)
        self._save_failed_shown = False
        self.bridge = Bridge()
        self.bridge.loaded.connect(self.soundctl.on_loaded)
        self.bridge.loaded.connect(self.editctl._on_loaded)   # after: the pad is ready
        self.bridge.render_progress.connect(self.editctl._on_progress)
        self.bridge.imported.connect(self.impctl.on_imported)
        self.bridge.preview.connect(self.playctl._on_fx_preview)
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
        Pad.single_click = self.cfg.single_click
        self._quitting = False            # a real quit (not "close to the tray")
        self._tray_told = False           # the "still running in the tray" note was shown
        self.tray: QSystemTrayIcon | None = None
        self.watch_offer: watchaddon.Offer | None = None   # an urgent Onion Watch fix
        self._discord_timer = QTimer(self, interval=DISCORD_POLL_MS)
        self._discord_timer.timeout.connect(self.alertctl._discord_tick)
        if sys.platform == "win32":
            self._discord_timer.start()
            QTimer.singleShot(3000, self.alertctl._discord_tick)
        self._raw_timer = QTimer(self, interval=RAW_POLL_MS)
        self._raw_timer.timeout.connect(self.alertctl._raw_tick)
        if sys.platform == "win32":
            self._raw_timer.start()
        self._ptt_held: str | None = None   # PTT key we're currently holding
        self.current: str | None = None   # sound shown in the transport bar
        self.start_frac = 0.0             # where ▶ starts if it isn't playing
        self._ui_live = True              # the window is on screen (see _set_tick_rate)
        self.engine.latency = self.cfg.latency if self.cfg.latency in ("low", "high") else "low"
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_now)
        # written on a background thread: a slow disk froze the window for seconds
        self._saver = library.Saver(self.cfg, done=self.config_saved.emit)
        self.config_saved.connect(self._on_saved)
        self.bin_filled.connect(self.rmctl._label_bin)

        self._pill_long = ""              # the setup pill's whole text (its tip, its name)
        self._pill_good = False           # set up: the pill hides (_show_pill)
        self._default_out = appaudio.default_output_name()   # see _follow_default_output
        with theme.styled_after(QApplication.instance()):
            self.builder._build_ui()
        restyled.again()   # what measured text, in the theme's fonts now
        from soundboard.ui.livesetups import LiveSetups
        self.livesetups = LiveSetups(self)   # My setups in the three Live controls
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
        if reset.is_update(self.cfg) and not self.cfg.setup_done:
            # they used an earlier version: an update never opens the setup guide again
            # (What's new comes first; the Setup tab still says what isn't set up)
            self.cfg.setup_done = True
        library.tidy_files(self.cfg)   # files from before library folders move in
        self._rebuild_pads()
        splash.pump()
        self.soundctl._load_all()
        splash.pump()
        self.load_triggers()   # behind the loading screen, not on the tab's first click
        splash.pump()
        self.impctl._watch_sounds_folder()
        self.hkctl._fit_overlay_key()
        self.hkctl.register_hotkeys()
        # Stream Deck / scripts (Settings → Remote), only if turned on
        self.remote = remote.RemoteControl(lambda a, p: remote.dispatch(self, a, p), self)
        self.remctl.apply_remote()
        self.remctl.remote_addons = self.remctl._load_remote_addons()
        self.pocket_card.refresh()   # its own card on Setup, if it's installed
        a11y.label_tree(self, force=True)   # names for the icon-only buttons

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tickctl.tick)
        self.timer.start(TICK_MS)
        app = QApplication.instance()
        assert isinstance(app, QApplication)   # made before the window
        app.applicationStateChanged.connect(self.tickctl._set_tick_rate)
        app.applicationStateChanged.connect(self.micctl._app_state)
        # Space plays / pauses on the Sounds and Radio tabs, wherever the focus is
        self._space = SpaceKey(self, self.playctl._space_action)
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
        self._voice_timer.timeout.connect(self.appsetctl._voice_tick)
        if self.voice_watch is not None:
            self._voice_timer.start(VOICE_POLL_MS)
        # a tip once things have settled; tried again now and then while the window is
        # hidden or a game is up, until one has been shown this start
        QTimer.singleShot(TIP_DELAY_MS, self, self.tipctl._start_tips)
        tabtours.hook(self)   # each tab's quick how-to on its first visit
        self.langctl._offer_language()
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
        self.fitctl._init_fit()
        self.resize(1180, 720)
        if self.cfg.window_maximized:   # shows maximised, as it was when it closed
            self.setWindowState(Qt.WindowState.WindowMaximized)
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
    def _on_download_started(self, url: str, title: str, kind: str, secs: float = 0.0):
        pm = self.ytresults.thumb_for(url)
        channel, card_secs = self.ytresults.meta_for(url)
        self.download_bar.set_active(url, title, kind, pm, channel, secs or card_secs)
        self.mini_download_bar.set_active(url, title, kind, pm, channel, secs or card_secs)

    def _mini_setup(self):
        self.resize(max(800, self.width()), max(600, self.height()))
        self.tabs.setCurrentWidget(self.setup_page)
        self.fitctl._refit()

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

    def _focus_deck(self, i: int):
        """An icon in the narrow levels strip clicked: its group is the one shown."""
        self._mixer_focus = i
        if self._deck_tabs[i].hasFocus():   # it just hid: keep the keyboard in the strip
            self._deck_tabs[i - 1 if i else 1].setFocus()
        self.fitctl._fit.reset()   # the groups aren't the same width: fit again
        self.fitctl._refit()

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
            self.transctl._update_playing_background(self.engine.playing())
        if hasattr(self.engine, attr):
            setattr(self.engine, attr, v)
        self._save_later()

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
        if not self.fitctl.is_mini():
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
            r.clip_ready.connect(self.soundctl.on_clip)
        else:
            r = RadioOff()
            r.open_settings.connect(lambda: self.setctl.open_settings("privacy"))
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
    def _make_tab(self, key: Literal["store"]) -> StoreTab | taboff.TabOff: ...
    @overload
    def _make_tab(self, key: str) -> (VoicePanel | AppsTab | TriggersTab | StoreTab
                                      | taboff.TabOff): ...

    def _make_tab(self, key: str):
        """The Apps, Triggers, Voice, Store or Chat tab, wired to the window; or, switched off in
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
            v.clip_ready.connect(self.soundctl.on_clip)
            v.fx.set_tip_enabled(not self.cfg.voice_discord_tip_shown)
            v.fx.chat_help.connect(lambda: self.statusctl.show_chat_guide("discord"))
            v.fx.hotkey_asked.connect(self.hkctl.set_voice_hotkey)
            v.share_asked.connect(self.share_voice)
            v.fx.hotkey_cleared.connect(lambda n: self.hkctl.set_voice_hotkey(n, ""))
            v.fx.renamed.connect(self.hkctl.voice_renamed)
            v.fx.keys = dict(self.cfg.voice_hotkeys)
            v.board_sounds = lambda: self.cfg.sounds   # the Background's "from my board"
            v.board_changed()
            v.fx.set_view(self.cfg.voice_view)
            v.fx.view_toggle.changed.connect(lambda view: self.set_option("voice_view", view))
            v.fx.tip_dismissed.connect(
                lambda: self.set_option("voice_discord_tip_shown", True))
        elif key == "apps":
            v = AppsTab(self.engine, self.cfg, self._save_later, Meter)
            v.clip_ready.connect(self.soundctl.on_clip)
            self.tab_info["apps"] = v.info
        elif key == "store":
            v = StoreTab(self.cfg, lambda path: self.impctl.import_files([path]),
                         self._store_sample, lambda: self.setctl.open_settings("privacy"),
                         self._save_later, self._store_link, self._voice_hooks())
            return v
        else:
            # the Onion Watch add-on, or Hoot and its download button until it's
            # installed; loaded by load_triggers
            v = TriggersTab(BoardHost(self), defer=True)
        v.active_changed.connect(lambda on, k=key: self.tabctl._tab_live(k, on))
        return v

    def _voice_hooks(self):
        """What the Store's Voices use of the Voice tab (its lists of your voices)."""
        from soundboard.ui.storevoices import VoiceHooks
        return VoiceHooks(lambda: (self.voice if isinstance(getattr(self, "voice", None),
                                                            VoicePanel) else None))

    def share_voice(self, pick: str = ""):
        """The Voice tab's "Share to the store…": the Share a voice window on that voice."""
        import html

        from soundboard import net, store
        from soundboard.ui.storevoices import open_share
        if not net.allowed(store.FEATURE):
            busy.toast(self, html.escape(net.off_message(store.FEATURE)), "error")
            return
        new = not getattr(self.cfg, "store_id", "")
        install = store.install_id(self.cfg)
        if new:
            self._save_later()
        open_share(self, install, self._voice_hooks(), pick)

    def _store_link(self, url: str, name: str, kind: str):
        """A shared link in the Store tab: played once or added, downloaded from its
        site the way a pasted link is (the download bar shows how far it is)."""
        self.linkbar.open(url, name)
        if kind == "play":
            self.linkbar.play_once()
        else:
            self.linkbar.add()

    def _store_sample(self, data, gain: float) -> bool:
        """The Store tab's "hear it first": to your headphones only (None stops it).
        False: no headphones to play it on."""
        if data is None:
            self.engine.stop(STORE_PREVIEW)
            return True
        return self.engine.play(STORE_PREVIEW, data, gain, mode="restart",
                                preview=True) is not None

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
    def set_single_click(self, on: bool):
        """Settings -> General: one click on a pad plays it."""
        self.set_option("single_click", on)
        Pad.single_click = on

    QUICK_HOTKEYS = ("stop_hotkey", "pause_hotkey", "skip_hotkey", "random_hotkey",
                     "last_hotkey", "mic_hotkey", "hotkeys_off_hotkey", "overlay_hotkey")

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
    # ------------------------------------------------------------------ tips
    # Settings pages showing state from outside the config (downloads, add-ons, Tor,
    # updates, the remote's add-ons): a kept Settings with one of them built is rebuilt
    SETTINGS_LIVE_PAGES = ("data", "connection", "help", "updates", "remote", "about")
    # config that changes without Settings showing it (counts, tips, the tab shown, the
    # Voice tab's speech) or that it keeps up to date itself (app_setup_changed)
    SETTINGS_PRINT_SKIP = ("sounds", "tab", "category", "tip_day", "tips_seen",
                           "update_checked", "update_auto_tried", "whats_new_seen", "load_note",
                           "speech",
                           "app_setup", "settings_advanced")

    CUES = {"start": (660, 990), "stop": (990, 660), "saved": (880, 880, 1320), "fail": (330, 247)}

    def set_sending(self, on: bool):
        """The master switch, "Others hear": on (others hear your mic and whatever is
        live) or off (they hear nothing at all, or only your plain voice while your mic is
        sent and no voice changer is on: engine.mic_only). Everything keeps playing for
        you. Not saved: the app always opens live, so nobody's left wondering why they're
        silent."""
        self.engine.sending = on
        self.playctl.sending_changed(on)
        if self.btn_air.isChecked() != on:
            self.btn_air.setChecked(on)   # comes back here
            return
        # sending nowhere (or the send device is the headphones): Live doesn't claim
        # others hear you; muting still silences the stream output, if there is one
        others = self.routectl._main_name() is not None
        stream = bool(self.engine.names["obs"])
        voice = not on and others and self.engine.mic_only()
        self.btn_air.setProperty("voiceonly", voice)   # the rail's word: sidebar.names
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
            return self.searchctl._link_meta
        return self._meta.get(sid)

    def gain_for(self, m: SoundMeta, volume=None) -> float:
        v = m.volume if volume is None else volume
        return v * (m.level_gain if self.cfg.level_volumes else 1.0)

    def _rebuild_pads(self):
        """Sync the pad widgets with cfg.sounds: keep the ones that still exist, create
        the new ones, drop the removed ones."""
        self._index()
        if getattr(self, "triggers", None) is not None:   # not built yet on the first call
            self.triggers.sounds_changed()
        board_changed = getattr(getattr(self, "voice", None), "board_changed", None)
        if board_changed is not None:   # the Voice tab's Background card's board sounds
            board_changed()
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
                p.activated.connect(self.playctl.play)
                p.space.connect(self.playctl.space_pad)
                p.chosen.connect(self.playctl.select)
                p.pick.connect(self.selection.on_pick)
                p.step.connect(self.grid.focus_step)
                p.menu.connect(self.padctl.pad_menu)
                p.nudge.connect(self.padctl.nudge_volume)
                p.rename.connect(self.soundctl.rename_sound)
                p.edit.connect(self.editctl.edit)
                p.stop_render.connect(self.editctl.stop_render)
                self.pads[m.id] = p
                r = self.editctl.rendering(m.id)
                if r is not None:   # (a new pad for a sound whose effects are rendering)
                    p.state, p.render_frac, p.can_stop = "rendering", r.frac, r.old_fx is not None
            p.state = "ready" if m.id in self.audio else p.state
            p.selected = m.id == self.current
            ordered.append(p)
        self.grid.set_pads(ordered, layout=False)   # laid out once, by the filter next
        self.searchctl.apply_filter(self.search.text())
        self.statusctl._update_status()

    # ------------------------------------------------------------------ search, rename
    # ------------------------------------------------------------------ loading sounds
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
        icons.set_icon(menu.addAction(_("Stop all sounds"), self.playctl.stop_all), "stop")
        self._tray_bun = menu.addAction(self.builder._bun_icon(), _("Turn into Bun"),
                                        self.bunctl.tray_bun)
        menu.aboutToShow.connect(self._name_tray_bun)
        self._tray_voices = menu.addMenu(_("Voice changer"))
        icons.set_icon(self._tray_voices.menuAction(), "wave")
        self._tray_voices.aboutToShow.connect(self._fill_tray_voices)
        menu.addSeparator()
        # the Discord opens in the browser (feedback.py); Send feedback asks first
        from soundboard import feedback
        icons.set_icon(menu.addAction(_("Join the Discord"), lambda: self.aboutctl._open_page(
            feedback.DISCORD_URL)), "speech")
        icons.set_icon(menu.addAction(_("Send feedback"), self.aboutctl.ask_feedback), "edit")
        menu.addSeparator()
        icons.set_icon(menu.addAction(_("Quit"), self.quit_app), "stop")
        t.setContextMenu(menu)
        t.activated.connect(self._on_tray)
        t.messageClicked.connect(self.show_from_tray)
        t.show()
        QApplication.setQuitOnLastWindowClosed(False)

    def _fill_tray_voices(self):
        """The tray's Voice changer menu: on / off, then your favorite and saved voices
        (the one in use ticked). Made each time it opens, so it's never out of date."""
        m = self._tray_voices
        m.clear()
        fx = self.hkctl._voice_fx()
        if fx is None:
            m.addAction(_("The Voice tab is switched off")).setEnabled(False)
            return
        on = fx.btn_power.isChecked()
        m.addAction(_("Turn off") if on else _("Turn on"),
                    lambda: (usage.used("tray-voice-toggle"), self.hkctl._set_voice(not on)))
        names = [n for n in fx.favorites if n in fx.voice_names()]
        names += [n for n in fx.saved_names() if n not in names]
        if not names:
            m.addSeparator()
            m.addAction(_("Star voices on the Voice tab to list them here")).setEnabled(False)
            return
        m.addSeparator()
        for n in names:
            a = m.addAction(fx.title_of(n), lambda n=n: (usage.used("tray-voice-pick"),
                                                         self.hkctl.pick_voice(n)))
            a.setCheckable(True)
            a.setChecked(on and fx.preset == n)

    def _name_tray_bun(self):
        """The tray's Bun item says what it does now: Bun up, it brings the window back."""
        self._tray_bun.setText(_("Back to the board") if self.bunctl.bun_up()
                               else _("Turn into Bun"))

    def _on_tray(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_from_tray()

    # ------------------------------------------------------------------ Bun mode
    def show_from_tray(self):
        self.bunctl._bun_away()
        if self.isMinimized():   # back the way it was: showNormal() un-maximised it
            self.showMaximized() if self.cfg.window_maximized else self.showNormal()
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

    def _count_at_quit(self):   # what waits for the next count goes now (usage.at_quit)
        self._quit_count = usage.at_quit(self.cfg, app_dir=library.APP_DIR)

    def _finish_count_at_quit(self):   # waits at most usage.QUIT_WAIT_S, all told
        finish, self._quit_count = getattr(self, "_quit_count", None), None
        if finish is not None and finish():
            self.cfg.save()

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
        self.btn_check.setAccessibleName(text)
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
        self.tickctl._set_tick_rate()
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
        if drag := livesize.drag_edge(message):   # the edge held / let go
            self.fitctl.live(drag > 0)
        return super().nativeEvent(event_type, message)

    def hideEvent(self, ev):
        super().hideEvent(ev)
        self.tickctl._set_tick_rate()

    def changeEvent(self, ev):
        super().changeEvent(ev)
        if ev.type() == QEvent.Type.WindowStateChange:
            self.tickctl._set_tick_rate()
            if self.isVisible() and not self.isMinimized():   # (minimised keeps what it was)
                self.cfg.window_maximized = self.isMaximized()

    # ------------------------------------------------------------------ small windows
    def _show_pill(self):
        """The setup pill: only while something needs fixing."""
        self.pill.setVisible(not self._pill_good)
        self.pill.setProperty("outputgood", self._pill_good)
        if hasattr(self, "rail"):
            self.rail.refresh_output()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if hasattr(self.fitctl, "_fit"):
            # right away, before the frame is painted: a queued refit let each frame
            # paint twice, before and after, which made parts of the window flash
            self.fitctl._refit()

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
        # the steps below block the window by design (some wait a little each): gone
        # from the screen at once, and a slow quit isn't a freeze (exitwatch covers a
        # quit that never ends)
        self.hide()
        hangwatch = getattr(QApplication.instance(), "hangwatch", None)
        if hangwatch is not None:
            hangwatch.stop()
        if self.bunctl.bun_mode is not None:   # (cfg.bun["on"] stays: it starts as Bun next time)
            self.bunctl.bun_mode.close()
        for step in (self.rmctl._finish_removals, self.rmctl._wait_bin, self.timer.stop,
                     self._voice_timer.stop, self.devctl._default_poll.stop,
                     self.alertctl._discord_poll.stop, self.alertctl._raw_poll.stop,
                     self.hkctl._release_ptt,
                     self.alertctl.discord_quit,
                     self._remember_usage, self._count_at_quit, self.cfg.save,
                     self.overlay.shutdown,
                     self.hotkeys.stop, self.replay.stop, self.remote.stop,
                     self.remctl._stop_remote_addons,
                     self._finish_count_at_quit,   # sent meanwhile; before Tor stops
                     self.radio.shutdown, tor.shutdown, self.apps.shutdown,
                     self.triggers.shutdown, self.store.shutdown,
                     self.linkbar.shutdown, ytworker.drop_all,
                     self.livesetups.shutdown,
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
