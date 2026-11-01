"""WindowParts, the base of MainWindow's mixins (windowtoasts, windowtabs, windowlife,
windowoptions, hearcheck): the window's parts that WindowBuilder makes, and for the type
checker only, what MainWindow itself provides. At run time it's a plain, empty class
(MainWindow itself is the QMainWindow)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtWidgets import QMainWindow

if TYPE_CHECKING:
    from pathlib import Path

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QPushButton
    from soundboard.ui.kit.widgets import Meter
    from soundboard.ui.radio.radiopanel import RadioOff, RadioTab
    from soundboard.ui.window import sidebar
    from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout,
                                   QLabel, QLineEdit, QProgressBar, QStackedWidget,
                                   QVBoxLayout, QWidget)
    from soundboard.ui.window import moretabs
    from soundboard.ui.apps.appspanel import ElidedLabel
    from soundboard.ui.setup.destpanel import DestPanel, ModeButton
    from soundboard.ui.window.downloadbar import DownloadBar
    from soundboard.ui.window.dropveil import DropVeil
    from soundboard.ui.sounds.linkbar import LinkBar
    from soundboard.ui.bun.logowidget import LogoWidget
    from soundboard.ui.sounds.padbatch import PadSelection
    from soundboard.ui.kit.panel import EqPanel, Flow, TileRow, ViewToggle, VolumeControl
    from soundboard.ui.kit.failreport import FailReport
    from soundboard.ui.kit.playbutton import PlayButton
    from soundboard.ui.kit.topbar import TopBar
    from soundboard.ui.setup.setupshow import SetupShow
    from soundboard.ui.window.sidebar import SideTabs
    from soundboard.ui.sounds.speedpitch import SpeedPitchButton
    from soundboard.ui.kit.widgets import (DropdownMenu, EdgeMatch, NameAndSeek, PadGrid,
                                           SeekSlider, WindowRoot)
    from soundboard.ui.sounds.ytsearch import SearchResults

# WindowParts is a plain, empty class at run time
_Window = QMainWindow if TYPE_CHECKING else object


class WindowParts(_Window):
    # ---- the window's parts: made once by WindowBuilder (ui/window/windowbuild.py), used by
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
    attach_glow: Any   # ui/kit/glow.py Glow on btn_attach
    _body_lay: Any
    btn_about: QPushButton
    btn_add: QPushButton
    btn_air: QPushButton
    btn_attach: QPushButton
    route_switch: QWidget   # Virtual cable | My mic, on top of the mic card
    seg_cable: QPushButton
    seg_mic: QPushButton
    btn_bin: QPushButton
    btn_cablefix: QPushButton
    _cable_started: bool   # Install the free virtual cable was clicked (check again shows)
    install_glow: Any      # ui/kit/glow.py Glow on btn_install (the mic route's main button)
    ways_or: Any           # the "or" before the cable's buttons on the Setup tab
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
    btn_cableinfo: Any
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
    _done_toast: str | None
    download_bar: DownloadBar
    drop_veil: DropVeil
    eq: EqPanel
    eq_card: Any
    ff_bar: TopBar
    addon_bar: TopBar
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
    lang_bar: TopBar
    lang_btn: QPushButton
    lang_hide: Any
    lang_lbl: QLabel
    _lang_offered: Any
    _link_wait: QTimer
    linkbar: LinkBar
    logo: LogoWidget
    mic_alt: QWidget
    mic_alt_tiles: TileRow
    mic_flow: QFrame
    _mic_icon: tuple[str, str] | None
    _mic_tone: str | None
    mic_lbl: Any
    mic_icon: Any
    mic_line: QLabel
    mic_meter: Any
    mic_pill: QLabel
    mic_reason: QLabel
    mic_report: FailReport
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
    mini_full: QPushButton
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
    _settle_more: bool
    setup_bar: TopBar
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
    enjoy_bar: TopBar
    _toolbar_hold: QWidget
    transport: Any
    _transport_vol: Any
    triggers: Any
    urgent_bar: TopBar
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

    # ---- kept by Settings → Remote across openings (ui/settings/addons.py)
    pocket_card: Any
    pocket_checked: float
    pocket_offer: Any

    if TYPE_CHECKING:   # ---- what MainWindow itself provides (__init__ and its methods)
        from PySide6.QtCore import Signal
        from soundboard.audio.engine import Engine
        from soundboard.sounds import library
        from soundboard.sounds.library import Config, SoundMeta
        from soundboard.win.thumbbar import ThumbBar
        from soundboard.ui.window.aboutcontrol import AboutControl
        from soundboard.ui.window.buncontrol import BunControl
        from soundboard.ui.window.fitcontrol import FitControl
        from soundboard.ui.window.hotkeycontrol import HotkeyControl
        from soundboard.ui.window.importcontrol import ImportControl
        from soundboard.ui.window.mainwindow import Bridge
        from soundboard.ui.window.playbackcontrol import PlaybackControl
        from soundboard.ui.window.routecontrol import RouteControl
        from soundboard.ui.window.settingscontrol import SettingsControl
        from soundboard.ui.window.soundscontrol import SoundsControl
        from soundboard.ui.window.tabcontrol import TabControl
        from soundboard.ui.window.tickcontrol import TickControl
        from soundboard.ui.window.transportcontrol import TransportControl
        from soundboard.ui.window.windowbuild import WindowBuilder
        cfg: Config
        engine: Engine
        bridge: Bridge
        thumbbar: ThumbBar
        title: str
        _saver: library.Saver
        _save_timer: QTimer
        _shut_down: bool
        _pill_long: str
        _pill_good: bool
        device_step: Signal
        aboutctl: AboutControl
        builder: WindowBuilder
        bunctl: BunControl
        fitctl: FitControl
        hkctl: HotkeyControl
        impctl: ImportControl
        playctl: PlaybackControl
        routectl: RouteControl
        setctl: SettingsControl
        soundctl: SoundsControl
        tabctl: TabControl
        tickctl: TickControl
        transctl: TransportControl

        def gain_for(self, m: SoundMeta, volume=None) -> float: ...
        # (the mixins', for each other)
        def toast(self, text: str, kind: str = ..., ms: int = ..., **kw) -> Any: ...
        def say(self, text: str, kind: str = ..., ms: int = ..., **kw) -> Any: ...
        def unsay(self, key: str) -> None: ...
        def set_option(self, attr: str, v) -> None: ...
        def light_voice_on(self) -> bool: ...
        def set_light_voice(self, on: bool) -> None: ...
        def set_sending(self, on: bool) -> None: ...
        def _save_later(self) -> None: ...
