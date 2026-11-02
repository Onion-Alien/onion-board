"""The main window: pads, transport, web search, the audio panel, auto push-to-talk."""
from __future__ import annotations

import logging
import sys
from typing import Any

import numpy as np
from PySide6.QtCore import QEvent, QObject, QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QMainWindow, QMessageBox, QPushButton,
                               QSystemTrayIcon)
from PySide6.QtWidgets import QMenu  # noqa: F401  (tests swap menus in here)

from soundboard.ui.kit import theme
from soundboard.online import ytworker
from soundboard.audio.engine import SR, Engine
from soundboard.audio.engineparts import LITE_BLOCK_S
from soundboard.core import exitwatch
from soundboard.audio import appaudio
from soundboard.mic import directmic, voicesdk
from soundboard.core import achievements, autostart, reset, trash
from soundboard.sounds import library
from soundboard import voicefx
from soundboard.control import remote
from soundboard.online import ffmpegget, net, netlog, tor
from soundboard.mic import profiles
from soundboard.online import quality
from soundboard.core import usage
from soundboard.win import shellicon, thumbbar
from soundboard.addons import watchaddon
from soundboard.audio.replay import InstantReplay
from soundboard.sounds.library import Config, SoundMeta
from soundboard.ui.kit.crashdialog import free_dialog
from soundboard.ui.kit import restyled, worker
from soundboard.ui.window.achievepop import AchievementPops
from soundboard.ui.window.ffmpegcontrol import FfmpegControl
from soundboard.ui.window import invitecontrol
from soundboard.ui.window.netcontrol import NetControl
from soundboard.ui.window.soundscontrol import SoundsControl
from soundboard.ui.window.windowbuild import (WindowBuilder, version_text)  # noqa: F401  (settings imports it here)
from soundboard.ui.window.fitcontrol import FitControl
from soundboard.ui.window.transportcontrol import TransportControl
from soundboard.ui.window.tickcontrol import TickControl
from soundboard.ui.window.tickcontrol import TICK_MS
from soundboard.ui.window.searchcontrol import SearchControl
from soundboard.ui.window.playbackcontrol import PlaybackControl
from soundboard.ui.window.appsetupcontrol import AppSetupControl
from soundboard.ui.window.languagecontrol import LanguageControl
from soundboard.ui.window.tipcontrol import TipControl
from soundboard.ui.window.hotkeycontrol import HotkeyControl
from soundboard.ui.window.aboutcontrol import AboutControl
from soundboard.ui.window.themecontrol import ThemeControl
from soundboard.ui.window.settingscontrol import SettingsControl
from soundboard.ui.window.tabcontrol import TAB_INDEX, TabControl
from soundboard.ui.window.statuscontrol import StatusControl
from soundboard.ui.window.miccontrol import MIC_OFFER_MS, MicControl
from soundboard.ui.window.routecontrol import RouteControl
from soundboard.ui.window.devicecontrol import DeviceControl
from soundboard.ui.window.editcontrol import EditControl
from soundboard.ui.window.addonnotice import AddonNotice
from soundboard.ui.window.enjoycontrol import EnjoyControl
from soundboard.ui.window.removecontrol import RemoveControl
from soundboard.ui.window.padcontrol import PadControl
from soundboard.ui.window.remoteaccess import RemoteAccess
from soundboard.ui.window.buncontrol import BunControl
from soundboard.ui.window.alertcontrol import AlertControl
from soundboard.ui.window.categorycontrol import CategoryControl
from soundboard.ui.window.importcontrol import ImportControl
from soundboard.ui.window.updatecontrol import UpdateControl
from soundboard.ui.window.hearcheck import HearCheck
from soundboard.ui.window.windowlife import WindowLife
from soundboard.ui.window.windowoptions import WindowOptions
from soundboard.ui.window.windowtabs import WindowTabs
from soundboard.ui.window.windowtoasts import (TOAST_EXPAND, _TONE_SPAN,  # noqa: F401  (moved)
                                              WindowToasts)
from soundboard.ui.kit import a11y, busy, icons
from soundboard.ui.kit import reveal as reveal_kit
from soundboard.ui.kit.plaintext import plain_tip
from soundboard.ui.settings import lite
from soundboard.ui.window import livesize, responsive
from soundboard.ui.window import sidebar  # noqa: F401  (tests read it here)
from soundboard.ui.bun import splash
from soundboard.ui.setup import tabtours
from soundboard.ui.sounds.linkbar import PLAY_ID as LINK_ID
from soundboard.ui.window import konami, mouseback
from soundboard.ui.window.newsounds import NewSounds
from soundboard.ui.window.spacekey import SpaceKey
from soundboard.ui.window import winwatch
from soundboard.ui.sounds.overlay import Overlay
from soundboard.ui.voice import voicefxpanel
from soundboard.ui.kit.widgets import Pad, expand_dropped
from soundboard.control.winkeys import Hotkeys
from soundboard.i18n import _

log = logging.getLogger(__name__)


DEFAULT_POLL_MS = 1500   # how often Windows' default output is checked
DISCORD_POLL_MS = 10000  # how often Discord's voice settings are looked at (discordcfg)
RAW_POLL_MS = 2000       # how often the apps recording the mic are counted (rawmic)
TLS_WARM_MS = 2500     # Qt's TLS is set up this long after the start (_warm_tls)
FF_CHECK_MS = 1500     # the FFmpeg check's answer is taken this long after the start
VOICE_POLL_MS = 3000  # how often the game in front is looked at (soundboard.mic.voicesdk)


class Bridge(QObject):
    loaded = Signal(str, object, str)          # id, data|None, error
    exported = Signal(str, int, str, int)      # file, sounds written, error, left out
    unpacked = Signal(object, object, str)     # backup.Imported|None, backup.Package, error
    worked = Signal(object, object, object)    # _on_worker: then, result|None, error|None
    update = Signal(object, str, bool)         # updates.Release|None, error, asked by the user
    update_progress = Signal(object, object)   # bytes of the new version downloaded, of
                                               # how many (0: not known)
    update_ready = Signal(object, str)         # its installer's Path|None, error
    update_started = Signal(object, object, str)  # Release, what start_install raised|None,
                                                  # its traceback
    watch_update = Signal(object)              # a newer Onion Watch: watchaddon.Offer
    discord = Signal(object)                   # [discordcfg.Settings] read in the background
    mic_users = Signal(object)                 # [appaudio.App] recording the mic (rawmic)
    counted = Signal(object)                   # a usage count went: what it clears (usage.py)
    imported = Signal(object, object, object)  # meta|None, data|None, Skipped|None
    preview = Signal(str, object, float, int)  # id, audio with unsaved effects|None, gain, gen
    render_progress = Signal(str, int, float)  # id, which render (gen), how far 0..1
    ffmpeg = Signal(object, object)            # ffmpegget.Health, after a fix: "" or its error
    ffmpeg_progress = Signal(int)              # percent of FFmpeg downloaded (-1: not known)


START_W, START_H = 1180, 720   # the window's first size, on a screen with room for it
FRAME_ROOM = 48   # the title bar and borders, which the size doesn't count


def start_size(screen) -> tuple[int, int]:
    """START_W x START_H, less high on a screen without room for it: on a 768 px high
    screen, 720 and the title bar put the bottom strip under the taskbar. (The width
    the window's fitter handles: it folds the bars on a narrow window.)"""
    if screen is None:
        return START_W, START_H
    return START_W, max(1, min(START_H, screen.availableGeometry().height() - FRAME_ROOM))


class MainWindow(WindowToasts, WindowTabs, WindowLife, WindowOptions, HearCheck,
                 QMainWindow):
    update_done = Signal(object, str)   # an update check finished: Release|None, error
    update_state = Signal()             # the update card changed (Settings > Updates follows)
    mic_attached = Signal(str, str)     # attach_mic finished: the mic, error ("" = done)
    mic_probed = Signal(object)         # probe_mic finished: micprobe.Result | None
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

    # the slim bars across the top of the window (urgent fix, app offer, FFmpeg, language,
    # the survey): one look, ui/kit/topbar.py
    TOP_BARS = ("urgent_bar", "setup_bar", "ff_bar", "addon_bar", "lang_bar", "enjoy_bar")

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
        self.enjoyctl = EnjoyControl(self)
        self.addonctl = AddonNotice(self)
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
        self.newctl = NewSounds(self)
        # shutdown() ran (app.py also calls it on aboutToQuit). Set first: the splash
        # pumps events while the window is built, so its timers can run
        # before the end of __init__
        self._shut_down = False
        self.title = "Onion Board"   # the version is on the rail, under the name
        self.setWindowTitle(self.title)
        self.setAcceptDrops(True)   # files dropped outside the pad grid: see dropEvent
        self.cfg = Config.load()
        # left off last time: ON starts from no picked voice, not one from an old run
        self.cfg.voice_fx = voicefxpanel.at_start(self.cfg.voice_fx)
        self.achievepops = AchievementPops(self)   # first: attach() can earn some
        achievements.attach(self.cfg)   # Settings > Achievements counts from here
        achievements.set_goal("rainbow_road", len(theme.THEMES))
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
        lite.set_on(self.cfg.lite_mode)   # (before anything that animates is built)
        voicefx.set_light(self.light_voice_on())
        directmic.set_helper(self.cfg.mic_helper)   # (before anything asks for admin)
        # before the UI is built, so everything polishes in-theme
        if isinstance(app, QApplication):
            theme.textures_on = self.cfg.theme_texture and not self.cfg.lite_mode
            kept = self.cfg.kept_themes if isinstance(self.cfg.kept_themes, list) else []
            theme.kept = {n for n in kept if isinstance(n, str)}   # (a hand-edited file)
            self.cfg.theme = theme.apply(app, self.cfg.theme, self.cfg.live_color)
            self.themectl.keep_limited(save=False)   # (saved with the next change)
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
        self.bridge.update_started.connect(self.updctl._on_update_started)
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
        self.engine.set_block(LITE_BLOCK_S if self.cfg.lite_mode else 0.0)   # (lite.py)
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
        from soundboard.ui.voice.livesetups import LiveSetups
        self.livesetups = LiveSetups(self)   # My voice combos in the three Live controls
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
        # Settings → Remote's Connect Twitch: listens only once the streamer has connected
        from soundboard.control.twitchlink import TwitchLink
        self.twitch = TwitchLink(self)
        self.twitch.apply()
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
        self._konami = konami.KonamiCode(self, lambda: konami.react(self))
        # the mouse's back side button presses the page's Back, as in a browser
        self._mouse_back = mouseback.MouseBack(self)
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
        self.enjoyctl.start()   # *Enjoying Onion Board?* once it's due (enjoy.py)
        self.addonctl.start()   # an add-on install the app closed in the middle of
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
        self.resize(*start_size(QApplication.primaryScreen()))
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
        from soundboard.addons import modules
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

    def _added_sound(self, url: str) -> str | None:
        """The pad a download was added as, while it's still a sound (the download
        card's ▶ and Show)."""
        sid = self.linkbar.added_ids.get(url)
        return sid if sid and self.meta(sid) is not None else None

    def _show_sound(self, sid: str, ring: bool = False):
        """The download card's Show: the Sounds tab, the pad picked and scrolled to.
        `ring`: a yellow ring pulses round it too."""
        self.tabs.setCurrentIndex(TAB_INDEX["sounds"])
        self.playctl.select(sid)

        def reveal():   # once the tab has laid its pads out
            pad = self.pads.get(sid)
            if pad is None:
                return
            area = self._pads_scroll
            if ring and (inner := area.widget()) is not None:   # in the middle, not at an edge
                mid = pad.mapTo(inner, pad.rect().center()).y()
                area.verticalScrollBar().setValue(mid - area.viewport().height() // 2)
                reveal_kit.ring(pad)
            else:
                area.ensureWidgetVisible(pad)
        QTimer.singleShot(0, self._pads_scroll, reveal)

    def _show_existing(self, fp: str):
        """An Add refused as already in the library: that sound's pad, ringed. The
        category showing switches when it isn't in it (to All, or the sound's own
        category when it's hidden from All)."""
        m = next((m for m in self.cfg.sounds if m.fingerprint == fp), None)
        if m is None:
            return
        cfg = self.cfg
        if not library.in_view(m.tags, cfg.category, cfg.subcategory, cfg.hidden_from_all):
            if library.in_view(m.tags, cfg.category, "", cfg.hidden_from_all):
                self.catctl.set_subcategory("")
            elif library.in_view(m.tags, "", "", cfg.hidden_from_all):
                self.catctl.set_category("")
            else:
                self.catctl.set_category(library.split_tag(m.tags[0])[0])
        self._show_sound(m.id, ring=True)

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
        if hasattr(self, "mic_lbl"):   # the bottom strip says it the same way
            title = _("My mic") if on else _("Mic muted")
            changed = title != self.mic_lbl.text()
            self.mic_lbl.setText(title)
            icons.set_label_icon(self.mic_icon, "mic" if on else "mic_off", "muted")
            tab = self._deck_tabs[0]
            tab.setToolTip(title)
            tab.setAccessibleName(title)
            icons.set_icon(tab, "mic" if on else "mic_off", "muted")
            if changed and hasattr(self.fitctl, "_fit"):   # another width: fit again
                self.fitctl._fit.reset()
                self.fitctl._refit()

    def _set_np_name(self, text: str):
        self._name_seek.set_text(text)   # (cut to its room, with "…")
        self.np_name.setToolTip(plain_tip(text))   # a sound's name: web / board text
        self.mini_name.setText(text)   # hides itself when it has no room
        for p in self.editctl.players():
            p.set_name(text, self.np_name.toolTip())
        if text == _("Pick a sound"):   # nothing picked: no time either
            self._set_np_time("")

    def _set_np_time(self, text: str):
        """The player's time. Blank (nothing picked) it hides, so the seek line runs
        all the way to the buttons instead of stopping at an empty gap."""
        self.np_time.setText(text)
        self.mini_time.setText(text)
        for p in self.editctl.players():
            p.set_time(text)
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

    # ------------------------------------------------------------------ devices
    RESCAN_SHOWN_S = 3.0   # a Re-scan button shows what it found this long

    _direct_shown: Any = None


    DIRECT_GRACE_S = 4.0   # the board's own mic open this long, and still no sign of it
    SETTLE_S = 20.0        # after setting it up: how long Windows gets to load it
    SETTLE_MORE_S = 25.0   # ...and once more, if it isn't working when that runs out
    MIC_SILENT_S = 20.0    # the mic sent only exact zeros this long: it's stuck (or muted)

    _backdrop: Any = None

    def setup_backdrop(self):
        """The very first launch: a plain backdrop over the window until the guide is
        done (nothing behind the guide but the theme and the logo). Put up before the
        window first shows (app.py), so the app never flashes up before the guide."""
        if self._backdrop is None and not self.cfg.use_mode:
            from soundboard.ui.setup.setupbackdrop import Backdrop
            self._backdrop = Backdrop(self)
        return self._backdrop

    def run_setup(self, resumed: bool = False):
        """The quick-setup guide (first launch, or the Setup tab's Step-by-step guide).
        `resumed`: reopened by itself after the restart the virtual cable needed."""
        from soundboard.ui.setup.setupbackdrop import Backdrop
        from soundboard.ui.setup.setupwizard import SetupWizard
        backdrop = self.setup_backdrop()
        if backdrop is None:   # opened again: the guide's a card in the window, so the
            backdrop = Backdrop(self, logo=False)   # board behind it goes plain too
        backdrop.settle()   # its logo fades as the guide comes in
        wiz = SetupWizard(self, resumed=resumed)
        wiz.exec()
        free_dialog(wiz)
        self._backdrop = None
        backdrop.reveal()
        self.routectl._prepare_all()
        # the installer's "from Soundpad" box waits for this, so its progress card
        # isn't stuck over the guide (a no-op once it's done)
        QTimer.singleShot(300, self.impctl.import_queued)
        QTimer.singleShot(500, lambda: invitecontrol.welcome(self))   # "{name} invited you"


    QUICK_HOTKEYS = ("stop_hotkey", "pause_hotkey", "skip_hotkey", "random_hotkey",
                     "last_hotkey", "mic_hotkey", "hotkeys_off_hotkey", "overlay_hotkey")

    # ------------------------------------------------------------------ FFmpeg
    # (ui/window/ffmpegcontrol.py: the check, getting it, and its bar)
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
    # updates, the remote's add-ons): built afresh in a kept Settings when shown again
    SETTINGS_LIVE_PAGES = ("data", "connection", "help", "updates", "remote", "about")
    # config that changes without Settings showing it (counts, tips, the tab shown, the
    # Voice tab's speech) or that it keeps up to date itself (app_setup_changed)
    SETTINGS_PRINT_SKIP = ("sounds", "tab", "category", "tip_day", "tips_seen",
                           "update_checked", "update_auto_tried", "whats_new_seen", "load_note",
                           "speech",
                           "app_setup", "settings_advanced", "edit_advanced")

    CUES = {"start": (660, 990), "stop": (990, 660), "saved": (880, 880, 1320), "fail": (330, 247)}

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
                p.activated.connect(self.playctl.clicked)
                p.space.connect(self.playctl.space_pad)
                p.chosen.connect(self.playctl.select)
                p.pick.connect(self.selection.on_pick)
                p.step.connect(self.grid.focus_step)
                p.menu.connect(self.padctl.pad_menu)
                p.nudge.connect(self.padctl.nudge_volume)
                p.rename.connect(self.soundctl.rename_sound)
                p.edit.connect(self.editctl.edit)
                p.stop_render.connect(self.editctl.stop_render)
                p.seen.connect(self.newctl.seen)
                self.pads[m.id] = p
                r = self.editctl.rendering(m.id)
                if r is not None:   # (a new pad for a sound whose effects are rendering)
                    p.state, p.render_frac, p.can_stop = "rendering", r.frac, r.old_fx is not None
            p.state = "ready" if m.id in self.audio else p.state
            p.selected = m.id == self.current
            ordered.append(p)
        self.newctl.pads_rebuilt()   # (sounds not seen before glow)
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

    # ------------------------------------------------------------------ tick
    # The window's visibility sets the UI timer's pace: 24/s for the meters and
    # visualisers while it's on screen, even behind another program, TICK_IDLE_MS while it's
    # hidden in the tray or minimised (nothing to paint, but push-to-talk, the stream
    # watchdog must go on). Qt tells us through these three
    # events and applicationStateChanged.
    def showEvent(self, ev):
        shellicon.on_show(self)   # the Jump List icon, before the taskbar button exists
        shellicon.paint_background(self, theme.T["bg"])
        shellicon.cloak_until_drawn(self)   # back from the tray: never a white window first
        winwatch.watch(self).attach()   # Space and the drop veil: a new QWindow after Always on top
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
                     self.micctl.sonar_poll.stop,
                     self.hkctl._release_ptt,
                     self.alertctl.discord_quit,
                     self._remember_usage, self._count_at_quit, self.cfg.save,
                     self.overlay.shutdown,
                     self.achievepops.shutdown,
                     self.hotkeys.stop, self.replay.stop, self.remote.stop, self.twitch.quit,
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
