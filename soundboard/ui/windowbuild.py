"""Building the main window's parts: the frame (tab rail, tabs, mixer strip, the bars on
top), the mini player, the mixer, the Sounds page and the Setup page. Runs once, while
the window is made; the parts it makes are the window's own (declared on MainWindow), and
what they do lives in the window's other controllers.

MainWindow makes one ``WindowBuilder`` (``MainWindow.builder``) and calls ``_build_ui``
from ``__init__``; everything here runs on the UI thread."""
from __future__ import annotations

import logging
import sys
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpacerItem,
    QStyle,
    QStyleOptionButton,
    QStylePainter,
    QVBoxLayout,
    QWidget,
)

from soundboard import backup, destination, engine, net, otherboards, remote, theme, usage
from soundboard.i18n import _
from soundboard.library import PAD_COLORS
from soundboard.ui import a11y, alsosend, busy, icons, sidebar, taboff
from soundboard.ui.appspanel import ElidedLabel
from soundboard.ui.buncontrol import BUN_TIP
from soundboard.ui.controller import Controller
from soundboard.ui.downloadbar import DownloadBar
from soundboard.ui.dropveil import DropVeil
from soundboard.ui.fitcontrol import BODY_SIDE, SEARCH_MIN_W
from soundboard.ui.iconrow import CapIcon
from soundboard.ui.linkbar import LinkBar
from soundboard.ui.livedot import set_tint as set_live_tint
from soundboard.ui.logowidget import LogoWidget
from soundboard.ui.padbatch import PadSelection
from soundboard.ui.panel import (
    ViewToggle,
    BAR_H,
    CONTROL_H,
    EqPanel,
    Flow,
    ShownStack,
    TileRow,
    VolumeControl,
    alt_tile,
    bar,
    capped,
    card,
    hint_label,
    icon_label,
    info_button,
    steady_number,
    vsep,
)
from soundboard.ui.playbackcontrol import CHIPS_GAP
from soundboard.ui.playbutton import PlayButton
from soundboard.ui.setupshow import SetupShow
from soundboard.ui.sidebar import SHUT_W, SideTabs
from soundboard.ui.speedpitch import SpeedPitchButton
from soundboard.ui.tabcontrol import TAB_INDEX, TAB_KEYS, TABS, rail_order
from soundboard.ui import cableconfirm
from soundboard.ui.glow import Glow
from soundboard.ui.widgets import (
    DropdownMenu,
    EdgeMatch,
    Meter,
    NameAndSeek,
    PadGrid,
    SeekSlider,
    SteadyTabs,
    WindowRoot,
)
from soundboard.ui.ytsearch import SearchResults
from soundboard.wheelguard import AppStyle, no_wheel

if TYPE_CHECKING:
    from soundboard.ui.mainwindow import MainWindow

log = logging.getLogger(__name__)

PULSE_MS = 1200      # the mic-check banner's throb: bright, dimmer, bright again
PULSE_LOW = 0.55     # ...down to this opacity
PULSE_FRAME_MS = 60  # ...a step this often (~16 a second still reads as a smooth pulse)
SEARCH_WAIT_MS = 100     # typing in the search box filters the pads once it pauses this long
LINK_WAIT_MS = 400       # a link in the search box is looked up once it stays this long
PAD_SIZE_WAIT_MS = 50    # dragging Pad size re-lays the pads at most this often
# ...and its most: a few words go in it, so past this it's only a longer empty bar
# (456 px at 1180x720, so normal windows are unchanged). The seek bar, the levels and
# the drop box still follow the window: wider is useful there.
SEARCH_MAX_W = 480
# Setup -> Devices -> Send my sounds to (Config.route, library.ROUTES): the mic, nobody,
# or one of the output devices by name (ROUTE_DEVICE + its name: "cable" for a virtual
# cable, "device" for anything else)
SEND_TO = _("Send my sounds to")


def version_text() -> str:
    """The version, as the title bar and header show it: "1.5.5", or "1.5.5 from
    source" when run with Python rather than the installed app."""
    from soundboard import __version__
    if getattr(sys, "frozen", False):
        return __version__
    return _("{version} from source", version=__version__)


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


class CutPill(QPushButton):
    """A button that never cuts its words off on both sides when it's squeezed: it
    drops its icon first, then ends the words in "…". A plain button showed "ic: Conne"
    and "■ A" in the mini player's narrowest sizes (and fonts)."""

    def shown(self) -> QStyleOptionButton:
        """What it paints at its width: its icon only when the words still fit."""
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        room = self.style().subElementRect(QStyle.SubElement.SE_PushButtonContents,
                                           opt, self).width()
        words = self.fontMetrics().horizontalAdvance(opt.text)
        if not opt.icon.isNull() and opt.iconSize.width() + words > room:
            opt.icon = QIcon()
        if opt.icon.isNull() and opt.text:
            opt.text = self.fontMetrics().elidedText(opt.text, Qt.TextElideMode.ElideRight,
                                                     max(0, room))
        return opt

    def paintEvent(self, _e):
        QStylePainter(self).drawControl(QStyle.ControlElement.CE_PushButton, self.shown())


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


class WindowBuilder(Controller):
    """Builds the parts of one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)

    # Layout: the tab rail (with Live, Stop all and the setup pill) / tabs / mixer strip.
    # Every tab is built the same way: a toolbar row on top, its content, and a
    # bottom bar ending in "Volume [slider %] | Hear it myself" for that source.
    def _build_ui(self):
        # page 0 the whole window, page 1 the mini player it turns into when it's
        # made too small to use (see _refit)
        mw = self.mw
        mw._pages = ShownStack()
        mw.setCentralWidget(mw._pages)
        root = mw._full = WindowRoot()
        root.setObjectName("root")   # the theme's window background (flat or the glow)
        mw._pages.addWidget(root)
        mw._full_row = QHBoxLayout(root)   # the tab rail (ui/sidebar.py), then the rest
        mw._full_row.setContentsMargins(0, 0, 0, 0)
        mw._full_row.setSpacing(0)
        body = QWidget()
        mw._full_row.addWidget(body, 1)
        rv = QVBoxLayout(body)
        mw._body_lay = rv
        rv.setContentsMargins(BODY_SIDE, 10, BODY_SIDE, 10)
        rv.setSpacing(8)

        # ---- what was the header: the onion and name, the setup pill, Live, Stop all and
        # Settings, all on the tab rail now (ui/sidebar.py); made here for _paint_logo
        mw.logo = LogoWidget()
        mw.wordmark = QLabel("Onion Board")
        mw.wordmark.setObjectName("wordmark")
        from soundboard import __version__
        # on the rail: the name over a quiet "by Onion Alien · v1.9.28" (the title bar
        # is just the name; "from source" is in the tips)
        mw.tagline = sidebar.ClickLabel(
            f"{_('by {name}', name='Onion Alien')} · v{__version__}")
        mw.tagline.setObjectName("tagline")
        about = _("an app by Onion Alien · v{version_text}", version_text=version_text())
        for w in (mw.logo, mw.wordmark):
            w.setToolTip(about)
        whats_new = _("What's new")   # the version is a button to it
        mw.tagline.setToolTip(f"{about}\n{whats_new}")
        mw.tagline.clicked.connect(
            lambda: (usage.used("whats-new"), mw.updctl.show_whats_new()))
        mw.pill = QPushButton()
        mw.pill.setObjectName("pill")
        mw.pill.setCursor(Qt.CursorShape.PointingHandCursor)
        mw.pill.setIconSize(QSize(sidebar.ICON, sidebar.ICON))
        mw.pill.clicked.connect(lambda: mw.tabs.setCurrentWidget(mw.setup_page))
        # a new version: a card over the On Air card (an icon, shut) that follows it
        # from found to downloading to ready (_show_update_state)
        mw.btn_update = sidebar.UpdateCard()
        mw.btn_update.clicked.connect(mw.updctl._update_clicked)
        mw.btn_update.copy.clicked.connect(mw.updctl._copy_update_error)
        # the two switches for everything at once, whatever tab you're on
        mw.btn_air = QPushButton()
        mw.btn_air.setObjectName("onair")
        mw.btn_air.setCheckable(True)
        mw.btn_air.setChecked(True)
        mw.btn_air.toggled.connect(mw.set_sending)
        mw.btn_air.clicked.connect(
            lambda on: usage.used("on-air-on" if on else "on-air-off"))
        icons.set_icon(mw.btn_air, "live", "danger_text", "on_live", size=sidebar.ICON, gap=False)
        mw.set_sending(True)
        # Keep the mode controller for shared commands; its full picker lives on Setup.
        from soundboard.ui.destpanel import ModeButton
        mw.mode_btn = ModeButton(mw)
        mw.mode_btn.setParent(mw)
        mw.mode_btn.hide()
        mw.stop_btn = QPushButton()
        mw.stop_btn.setObjectName("danger")
        mw.stop_btn.setProperty("quiet", True)   # red text, no box: Live is the loud one
        sidebar.put(mw.stop_btn, _("Stop all"),
                    tip=_("Stops every sound, the radio and every program, and turns "
                          "the voices off"))
        mw.stop_btn.clicked.connect(mw.playctl._stop_all_clicked)
        icons.set_icon(mw.stop_btn, "stop", "danger_text", size=sidebar.ICON, gap=False)
        mw.gear = QPushButton(_("Settings"))
        mw.gear.setObjectName("settings")
        mw.gear.setProperty("quiet", True)
        mw.gear.setToolTip(_("Themes, hotkeys and more"))
        mw.gear.clicked.connect(lambda: mw.setctl.open_settings())
        # (showing its page: the accent, as a selected tab's icon; on_accent was white
        # on the soft fill, all but gone in Light)
        icons.set_icon(mw.gear, "settings", checked_color="accent", size=sidebar.ICON, gap=False)
        mw.gear.setProperty("railtext", _("Settings"))   # at the foot of the tab rail
        # the onion beside it: the Discord, feedback, a bug report, the code (each only
        # opens a page in the browser, feedback.py)
        mw.btn_about = QPushButton(_("Help and community"))
        mw.btn_about.setObjectName("settings")   # Settings' look: a quiet square
        mw.btn_about.setProperty("quiet", True)
        mw.btn_about.setToolTip(_("Help and community"))
        mw.btn_about.setProperty("railtext", _("Help and community"))
        icons.set_icon(mw.btn_about, "onion", size=sidebar.ICON, gap=False)
        mw.about_menu = DropdownMenu(mw.btn_about)
        mw.about_menu.aboutToShow.connect(mw.aboutctl._fill_about_menu)
        mw.btn_about.clicked.connect(mw.aboutctl._show_about_menu)
        mw.themectl._paint_logo()

        # only a sign: the one switch is "Hear what they hear" in the mixer at the bottom
        mw.mic_banner = BannerButton(_("You're hearing your mic output: mic + sounds, "
                                         "exactly what others hear"),
                                       _("Hearing your mic output"))
        mw.mic_banner.setObjectName("micbanner")
        mw.mic_banner.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        mw.mic_banner.hide()
        icons.set_icon(mw.mic_banner, "ear", "#ffffff", size=20)
        # pulse: an opacity animation, not a stylesheet rewrite 30x a second (each
        # setStyleSheet re-parses and re-polishes the widget)
        mw._banner_fx = QGraphicsOpacityEffect(mw.mic_banner)
        mw.mic_banner.setGraphicsEffect(mw._banner_fx)
        mw._pulse = Pulse(mw._banner_fx, mw)
        rv.addWidget(mw.mic_banner)

        # an urgent fix (a release whose notes say "Urgent: …", updates.urgent): a bar
        # across the window, not only the small Update pill. Hidden only until next start.
        mw.urgent_bar = QFrame()
        mw.urgent_bar.setObjectName("urgentbar")
        uh = QHBoxLayout(mw.urgent_bar)
        uh.setContentsMargins(12, 6, 6, 6)
        uh.setSpacing(8)
        mw.urgent_lbl = QLabel()
        mw.urgent_lbl.setTextFormat(Qt.TextFormat.PlainText)   # the reason is release-note text
        mw.urgent_lbl.setWordWrap(True)   # never makes the window wider
        # Onion Board's fix downloading: the update card's bar and words, not new ones
        mw.urgent_prog = QProgressBar()
        mw.urgent_prog.setObjectName("updatebar")
        mw.urgent_prog.setRange(0, 100)
        mw.urgent_prog.setTextVisible(False)
        mw.urgent_prog.setFixedHeight(sidebar.UpdateCard.BAR_H)
        mw.urgent_prog.hide()
        mw.urgent_sub = QLabel()
        mw.urgent_sub.setObjectName("hint")
        mw.urgent_sub.setTextFormat(Qt.TextFormat.PlainText)
        mw.urgent_sub.setWordWrap(True)
        mw.urgent_sub.hide()
        uv = QVBoxLayout()
        uv.setSpacing(4)
        uv.addWidget(mw.urgent_lbl)
        uv.addWidget(mw.urgent_prog)
        uv.addWidget(mw.urgent_sub)
        uh.addLayout(uv, 1)
        mw.urgent_btn = QPushButton()
        mw.urgent_btn.setObjectName("primary")
        mw.urgent_btn.clicked.connect(mw.alertctl._urgent_clicked)
        uh.addWidget(mw.urgent_btn)
        hide = QPushButton()
        hide.setObjectName("urgenthide")
        hide.setAccessibleName(_("Hide"))
        hide.setToolTip(_("Hide until Onion Board starts again"))
        icons.close_button(hide, 28, "warn_text")
        hide.clicked.connect(mw.alertctl._hide_urgent)
        uh.addWidget(hide)
        mw.urgent_bar.hide()
        rv.addWidget(mw.urgent_bar)

        # "Did you know?": one tip per start (soundboard.tips), with a Show me
        mw.tip_bar = QFrame()
        mw.tip_bar.setObjectName("tipbar")
        th = QHBoxLayout(mw.tip_bar)
        th.setContentsMargins(12, 6, 6, 6)
        th.setSpacing(8)
        mw.tip_lbl = QLabel()
        mw.tip_lbl.setTextFormat(Qt.TextFormat.PlainText)
        mw.tip_lbl.setWordWrap(True)
        th.addWidget(mw.tip_lbl, 1)
        mw.tip_btn = QPushButton(_("Show me"))
        mw.tip_btn.setObjectName("small")
        mw.tip_btn.clicked.connect(mw.tipctl._tip_show_me)
        th.addWidget(mw.tip_btn)
        hide = QPushButton()
        hide.setObjectName("urgenthide")
        hide.setAccessibleName(_("Hide the tip"))
        hide.setToolTip(_("Hide this tip (Settings → General turns tips off)"))
        icons.close_button(hide, 28)
        hide.clicked.connect(mw.tip_bar.hide)
        th.addWidget(hide)
        mw.tip_bar.hide()
        mw.tip = None
        rv.addWidget(mw.tip_bar)

        # "Looks like you're using Discord. Set up for it?" (appsetup, _app_setup): one
        # slim bar, never a window, so it's safe while a game is up
        mw.setup_bar = QFrame()
        mw.setup_bar.setObjectName("tipbar")
        sh = QHBoxLayout(mw.setup_bar)
        sh.setContentsMargins(12, 6, 6, 6)
        sh.setSpacing(8)
        mw.setup_lbl = QLabel()
        mw.setup_lbl.setTextFormat(Qt.TextFormat.RichText)
        mw.setup_lbl.setWordWrap(True)
        sh.addWidget(mw.setup_lbl, 1)
        mw.setup_yes = QPushButton()
        mw.setup_yes.setObjectName("primary")
        mw.setup_yes.clicked.connect(mw.appsetctl._setup_yes_clicked)
        sh.addWidget(mw.setup_yes)
        mw.setup_no = QPushButton(_("Not now"))
        mw.setup_no.setObjectName("small")
        mw.setup_no.clicked.connect(mw.appsetctl._setup_not_now)
        sh.addWidget(mw.setup_no)
        mw.setup_x = QPushButton()
        mw.setup_x.setObjectName("urgenthide")
        icons.close_button(mw.setup_x, 28)
        mw.setup_x.clicked.connect(mw.appsetctl._setup_x_clicked)
        sh.addWidget(mw.setup_x)
        mw.setup_bar.hide()
        rv.addWidget(mw.setup_bar)

        mw.ff_bar = mw.ffctl.build_bar()   # FFmpeg (ui/ffmpegcontrol.py)
        rv.addWidget(mw.ff_bar)

        # Windows is in a language the board has but isn't showing: offered in that
        # language, so someone who can't read English finds it (_offer_language)
        mw.lang_bar = QFrame()
        mw.lang_bar.setObjectName("tipbar")
        lh = QHBoxLayout(mw.lang_bar)
        lh.setContentsMargins(12, 6, 6, 6)
        lh.setSpacing(8)
        mw.lang_lbl = QLabel()
        mw.lang_lbl.setTextFormat(Qt.TextFormat.PlainText)
        mw.lang_lbl.setWordWrap(True)
        lh.addWidget(mw.lang_lbl, 1)
        mw.lang_btn = QPushButton()
        mw.lang_btn.setObjectName("small")
        mw.lang_btn.clicked.connect(lambda: mw.langctl.switch_language(mw._lang_offered))
        lh.addWidget(mw.lang_btn)
        hide = QPushButton()
        hide.setObjectName("urgenthide")
        icons.close_button(hide, 28)
        hide.clicked.connect(mw.langctl._no_language)
        lh.addWidget(hide)
        mw.lang_hide = hide
        mw.lang_bar.hide()
        mw._lang_offered = ""
        rv.addWidget(mw.lang_bar)

        mw.enjoy_bar = mw.enjoyctl.build_bar()   # *Enjoying Onion Board?* (ui/enjoycontrol.py)
        rv.addWidget(mw.enjoy_bar)

        # the bars' buttons take focus from Tab only, never a click: a clicked ✕ held the
        # focus, its bar hid, and Qt passed the focus on to the sidebar's Sounds button
        for name in mw.TOP_BARS:
            for b in getattr(mw, name).findChildren(QPushButton):
                b.setFocusPolicy(Qt.FocusPolicy.TabFocus)

        # the bar and the tabs share a box with no gap of its own: every tab page already
        # starts 8 px down, so the bar's gap to the first row matches the rows below it
        tabs_box = mw._tabs_box = QWidget()
        tv = QVBoxLayout(tabs_box)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(0)
        mw._tabs_lay = tv
        # in a box of its own, so its edges can follow the page's cards (_fit_dl_bar)
        dl_box = QWidget()
        mw._dl_lay = QHBoxLayout(dl_box)
        mw._dl_lay.setContentsMargins(0, 0, 0, 0)
        mw.download_bar = DownloadBar(mw)
        mw._dl_lay.addWidget(mw.download_bar)
        tv.addWidget(dl_box)
        mw.download_bar.shown_changed.connect(mw.fitctl._dl_bar_gap)
        # (the controller's own slot, not a lambda: Qt drops it with the window)
        mw.download_bar.shown_changed.connect(mw.fitctl._refit_dl_bar)
        mw.download_bar.room_changed.connect(mw.fitctl._refit_dl_bar)

        # ---- tabs
        mw.tab_info = {}   # page attr -> (title, text) for ⓘ
        mw.tabs = SideTabs()   # its bar hidden: the rail down the left shows the tabs
        mw.tabs.setDocumentMode(True)
        mw.tabs.setIconSize(QSize(sidebar.ICON, sidebar.ICON))
        SteadyTabs(mw.tabs)   # a change inside a page doesn't repaint the whole board
        tv.addWidget(mw.tabs, 1)
        # the tabs with the bars over them, or Settings in their place (open_settings):
        # the rail and the player and mixer below stay, so sounds can still be stopped
        area = mw._tabs_area = QWidget()
        av = QVBoxLayout(area)
        av.setContentsMargins(0, 0, 0, 0)
        av.setSpacing(rv.spacing())
        for strip in (mw.mic_banner, mw.urgent_bar, mw.tip_bar, mw.setup_bar,
                      mw.ff_bar, mw.lang_bar, mw.enjoy_bar):
            rv.removeWidget(strip)
            av.addWidget(strip)
        av.addWidget(tabs_box, 1)
        mw._content = ShownStack()
        mw._content.addWidget(area)
        rv.addWidget(mw._content, 1)
        mw.sounds_page = self._build_sounds_page()
        mw.tabs.addTab(mw.sounds_page, "")
        # the Radio tab, or the panel saying it's switched off (Settings > Privacy)
        mw.radio_page = ShownStack()
        mw.radio = mw._make_radio()
        mw.tabs.addTab(mw.radio_page, "")
        # the rest are made by _make_tab: each one or, switched off in Settings > Tabs,
        # a stand-in that loads nothing (ui/taboff.py)
        mw.apps = mw._make_tab("apps")
        mw.tabs.addTab(mw.apps, "")
        mw.triggers = mw._make_tab("triggers")
        mw.tabs.addTab(mw.triggers, "")
        mw.voice = mw._make_tab("voice")
        mw.tabs.addTab(mw.voice, "")
        mw.setup_page = self._build_setup_page()
        mw.tabs.addTab(mw.setup_page, "")
        mw.store = mw._make_tab("store")
        mw.tabs.addTab(mw.store, "")
        for i, (text, _tip) in enumerate(TABS):   # no hover tip: the name says it
            mw.tabs.setTabText(i, text)
            icons.set_tab_icon(mw.tabs, i, TAB_KEYS[i])
        for key in taboff.KEYS:
            mw.tabs.setTabVisible(TAB_INDEX[key], mw.tabctl.tab_shown(key))
        # + More tabs: the tabs switched off (a new user starts with the basic ones), one
        # click to add one; only there while one is off. Right after the last tab
        mw.btn_more_tabs = QPushButton(_("More tabs"))
        mw.btn_more_tabs.setObjectName("moretabs")
        icons.set_icon(mw.btn_more_tabs, "plus", size=sidebar.ICON, gap=False)
        mw.btn_more_tabs.setProperty("railtext", _("More tabs"))
        mw.btn_more_tabs.setCursor(Qt.CursorShape.PointingHandCursor)
        # a click left an accent ring on it
        mw.btn_more_tabs.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        mw.btn_more_tabs.setToolTip(_("Add a tab: radio, sending a program's sound, screen "
                                        "triggers"))
        from soundboard.ui import moretabs
        mt = mw.more_menu = moretabs.Menu(mw.btn_more_tabs)
        mt.aboutToShow.connect(lambda: mw.tabctl._fill_more_tabs(mt))
        mt.aboutToHide.connect(mw.tabctl._more_tabs_hidden)
        mw.btn_more_tabs.clicked.connect(mt.pop)
        mw.tabctl._update_more_tabs()
        mw.rail = sidebar.SideRail(
            mw.tabs, mw.logo, mw.wordmark, mw.tagline,
            [mw.btn_more_tabs], mw.cfg.sidebar_open, [mw.gear, mw.btn_about],
            mw.fitctl._rail_opened,
            # Live and Stop all never move; the pills (what needs attention) sit above
            # them and only show when needed (at the rail's foot, as icons)
            [mw.btn_air, mw.stop_btn],
            order=[TAB_INDEX[k] for k in rail_order(mw.cfg.sidebar_order)],
            alerts=[mw.pill], update=mw.btn_update)
        # Proxy, Tor or Offline mode, a phone remote listening: lines in the On Air card
        # (_net_follow), each one click to its Settings page
        if mw.rail.output is not None:
            mw.rail.output.lineClicked.connect(mw.setctl.open_settings)
            mw.rail.output.lineClicked.connect(lambda _p: usage.used("on-air-line"))
        mw.remote_changed.connect(mw.netctl._net_follow, Qt.ConnectionType.QueuedConnection)
        remote.on_change(mw.netctl._remote_watch)
        mw.netctl._net_follow()
        # Ctrl+1... jump to the tabs in the rail's order, Ctrl+Tab / Ctrl+Shift+Tab step
        # through them (the tab widget does that only while it has the focus)
        for n in range(1, 10):
            QShortcut(QKeySequence(f"Ctrl+{n}"), mw,   # pyright: ignore[reportCallIssue]  # signal keyword
                      activated=lambda n=n: mw.tabctl._go_tab(n - 1, absolute=True))
        QShortcut(QKeySequence("Ctrl+Tab"), mw, activated=lambda: mw.tabctl._go_tab(1))   # pyright: ignore[reportCallIssue]
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), mw, activated=lambda: mw.tabctl._go_tab(-1))   # pyright: ignore[reportCallIssue]
        mw.rail.orderChanged.connect(
            lambda order: mw.set_option("sidebar_order", [TAB_KEYS[i] for i in order]))
        # a tab asked for (the rail, Ctrl+1..., a link) while Settings is up: back to the
        # tabs, on that one
        mw.tabs.picked.connect(mw.setctl.close_settings)
        mw._full_row.insertWidget(0, mw.rail)
        # Tab goes header, rail, page (as it did with the top tabs), not page, rail; the
        # page's box holds the download bar too, so the bar's buttons come just before it
        prev = mw._tabs_box.previousInFocusChain()
        assert prev is not None   # (the chain is a ring)
        status_focus: list[QWidget] = []
        for button in mw.rail.status:
            if button is mw.btn_air and mw.rail.output:
                out = mw.rail.output   # (shut: its switch; open: Mute and Stop all)
                status_focus.extend(w for w in (out.switch, out.mute, out.stop, out.setup)
                                    if w is not None)
            status_focus.append(button)
        for w in (*mw.rail.buttons, mw.btn_more_tabs, *status_focus,
                  mw.gear, mw.btn_about,
                  mw.rail.toggle, mw._tabs_box):
            QWidget.setTabOrder(prev, w)
            prev = w
        # right-click a tab: what it's for, or hide it (+ More tabs or Settings > Tabs
        # bring it back)
        for b in mw.rail.buttons:
            b.customContextMenuRequested.connect(
                lambda pos, b=b: mw.tabctl.tab_menu(b.index).exec(b.mapToGlobal(pos)))
        # every tab has a line for its right-click "About this tab" (the Apps tab brings
        # its own)
        mw.tab_info.setdefault("sounds_page", (
            _("Your sounds"),
            _("Your pads. Add sounds with the button, by dropping files or folders here, "
              "or from a web search; double-click (or Enter) plays one, right-click it "
              "for its hotkey, effects, categories and picture. The transport bar "
              "plays what's picked, and the bottom strip is your mic, what others hear "
              "and your headphones.")))
        mw.tab_info.setdefault("radio_page", (
            _("Radio"),
            _("Internet radio stations from all over the world. Click a dot on the map or "
              "search by name, genre, country or city; it plays in your headphones, and "
              "Send puts it out to whoever's listening. Record keeps a bit as a pad.")))
        mw.tab_info.setdefault("triggers", (
            _("Triggers"),
            _("Plays a sound when a picture shows up in your game: a \"YOU DIED\", a rare "
              "spawn, a queue popping. It's the Onion Watch add-on; everything happens on "
              "your PC and the screen is never saved or sent anywhere.")))
        mw.tab_info.setdefault("voice", (
            _("Voice"),
            _("Change your voice live for whoever you send sounds to (pick a voice to "
              "turn it on), turn it into someone else's with AI voices, or type a line "
              "and a computer voice says it. Hear what they hear at the bottom tries it.")))
        mw.tab_info.setdefault("setup_page", (
            _("Setup"),
            _("Where your sounds go (straight into your mic, the virtual cable, another "
              "device or nobody), your devices, who's listening, the equalizer, and a "
              "test that records what goes out and plays it back.")))
        tab = mw.cfg.tab if 0 <= mw.cfg.tab < mw.tabs.count() else 0
        mw.tabs.setCurrentIndex(tab if mw.tabs.isTabVisible(tab) else 0)
        mw.tabctl._focus_open_tab()
        mw.tabs.currentChanged.connect(lambda i: mw.set_option("tab", i))
        mw.tabs.currentChanged.connect(lambda _i: mw.fitctl._fit_dl_bar())
        mw.tabs.currentChanged.connect(mw.tabctl._count_tab)   # names only (usage.py)
        mw.tabctl._count_tab(mw.tabs.currentIndex())
        mw.tabs.currentChanged.connect(lambda _i: mw.statusctl._update_status())
        mw.tabs.currentChanged.connect(mw._focus_sounds_page)
        # an urgent Onion Watch fix's banner shows on the Triggers tab only
        mw.tabs.currentChanged.connect(
            lambda _i: mw.watch_offer is not None and mw.alertctl._show_urgent())
        # a badge on a tab's icon (or, by default, a wash) in the theme's live colour while
        # its feature is live — the voice changer, a radio station, a program being
        # sent, the screen watched — so it's never left on without you noticing
        set_live_tint(mw.tabs, mw.cfg.live_tab_green)
        for key in ("voice", "triggers", "apps"):
            mw.tabctl._tab_live(key, getattr(mw, key).is_active())
        mw.tabctl._radio_live(mw.radio.is_active())
        mw.netctl._search_follow_switch()
        net.on_change(mw.netctl._follow_switches)

        # Now playing and Up next, over the player: on every tab, so a sound played from
        # Community (or anywhere) that waits its turn is seen waiting, not lost
        rv.addWidget(mw.playing_row)
        # the Sounds tab's player; right under the page, where it sat inside it
        rv.addWidget(mw.transport)
        mw.tabs.currentChanged.connect(lambda _i: mw.transctl._show_transport())
        mw.transctl._show_transport()
        mw._fit_tab = mw.tabs.currentWidget()
        mw.tabs.currentChanged.connect(mw.fitctl._fit_setup_tab)

        # ---- mixer strip: the things that apply whatever tab you're on
        rv.addWidget(self._build_mixer())

        mw.drop_veil = DropVeil(mw)   # "Drop to add 4 files" while files are dragged in
        mw._pages.addWidget(self._build_mini())

        mw.linkbar.download_started.connect(mw._on_download_started)
        mw.linkbar.progress.connect(mw.download_bar.set_progress)
        mw.linkbar.progress.connect(mw.mini_download_bar.set_progress)
        mw.linkbar.done.connect(mw.download_bar.set_done)
        mw.linkbar.failed.connect(mw.download_bar.set_failed)
        mw.linkbar.failed.connect(mw.mini_download_bar.set_failed)
        mw.linkbar.done.connect(mw.mini_download_bar.set_done)
        mw.download_bar.retry_requested.connect(mw.searchctl._retry_download)
        mw.mini_download_bar.retry_requested.connect(mw.searchctl._retry_download)
        mw.download_bar.front_requested.connect(mw.linkbar.move_to_front)
        mw.mini_download_bar.front_requested.connect(mw.linkbar.move_to_front)
        mw.linkbar.queue_updated.connect(mw.download_bar.set_queue)
        mw.linkbar.queue_updated.connect(mw.mini_download_bar.set_queue)
        for b in (mw.download_bar, mw.mini_download_bar):
            # a Play that waits for the song playing says Up next there, not Playing
            mw.linkbar.up_next_changed.connect(
                lambda *__, b=b: b.set_up_next(mw.linkbar.up_next_items()))
            mw.linkbar.played.connect(lambda *a, b=b: b.set_playing(a[3]))
            b.up_next_drop.connect(mw.linkbar.drop_up_next_url)
        mw.download_bar.cancel_requested.connect(mw.linkbar.cancel)
        mw.mini_download_bar.cancel_requested.connect(mw.linkbar.cancel)
        mw.download_bar.stop_all_requested.connect(mw.linkbar.cancel_all)
        mw.mini_download_bar.stop_all_requested.connect(mw.linkbar.cancel_all)
        for b in (mw.download_bar, mw.mini_download_bar):
            b.thumb_lookup = mw.ytresults.thumb_for   # (typed in downloadbar.py)
        mw.linkbar.queued.connect(mw.ytresults.queued)
        mw.ytresults.thumb_ready.connect(mw.download_bar.set_thumb)
        mw.ytresults.thumb_ready.connect(mw.mini_download_bar.set_thumb)

    def _build_mini(self) -> QWidget:
        """The mini player: what's playing, play / stop, where it's at, Live and Stop
        all, and the pads above them if there's room. The pads are the real ones,
        moved in and out of the Sounds tab (_set_mini)."""
        mw = self.mw
        page = QWidget()
        v = mw._mini_v = QVBoxLayout(page)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)
        mw.mini_download_bar = DownloadBar(mw)
        mw.mini_download_bar.set_mini(True)
        v.addWidget(mw.mini_download_bar)
        v.addStretch(0)   # keeps the player at the bottom when the pads don't fit
        card = mw._mini_card = QFrame()
        card.setObjectName("transport")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(8, 6, 8, 6)
        cv.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(6)
        mw.mini_pp = PlayButton()
        mw.mini_pp.setObjectName("transport_play")
        mw.mini_pp.setProperty("mini", True)
        mw.mini_pp.setAccessibleName(_("Play / pause"))
        mw.mini_pp.clicked.connect(mw.playctl.toggle_play_pause)
        mw.mini_st = QPushButton()
        mw.mini_st.setObjectName("transport_stop")
        mw.mini_st.setAccessibleName(_("Stop"))
        mw.mini_st.clicked.connect(mw.playctl.stop_current)
        icons.set_icon(mw.mini_st, "stop", size=16)
        mw.mini_skip = QPushButton()
        mw.mini_skip.setObjectName("transport_stop")
        mw.mini_skip.setAccessibleName(_("Skip to the next sound in Up next"))
        mw.mini_skip.clicked.connect(mw.playctl.skip_next)
        icons.set_icon(mw.mini_skip, "next", size=16)
        for b in (mw.mini_pp, mw.mini_st, mw.mini_skip):
            b.setFixedSize(34, 30)
            top.addWidget(b)
        mw.mini_name = ElidedLabel(mw.np_name.text(), hide_overflow=True)
        mw.mini_name.setTextFormat(Qt.TextFormat.PlainText)   # sound names are user / web text
        mw.mini_name.setStyleSheet("font-weight:600;")
        mw.mini_name.setMinimumWidth(0)   # it hides when it doesn't fit: its room goes to "■ All"
        mw.mini_name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        top.addWidget(mw.mini_name, 1)
        mw.mini_air = QPushButton()
        mw.mini_air.setObjectName("onair")
        mw.mini_air.setCheckable(True)
        mw.mini_air.setChecked(mw.btn_air.isChecked())
        mw.mini_air.setToolTip(mw.btn_air.toolTip())
        mw.mini_air.toggled.connect(mw.set_sending)
        mw.mini_air.clicked.connect(
            lambda on: usage.used("on-air-on" if on else "on-air-off"))
        icons.set_icon(mw.mini_air, "live", "danger_text", "on_live")
        # "All" in words: an icon-only ■ here looked just like the one-sound ■ on
        # the left, and stopped everything
        mw.mini_stop = CutPill(_("All"))   # squeezed: the word stays, the ■ goes
        mw.mini_stop.setObjectName("danger")
        mw.mini_stop.setProperty("mini", True)   # slim padding: never squeezed to "■ A"
        mw.mini_stop.setToolTip(mw.stop_btn.toolTip())
        mw.mini_stop.setAccessibleName(_("Stop all"))   # read out whole, not just "All"
        mw.mini_stop.clicked.connect(mw.playctl.stop_all)
        icons.set_icon(mw.mini_stop, "stop", "danger_text", size=14)
        mw.mini_air.setFixedSize(38, 30)
        mw.mini_stop.setFixedHeight(30)
        mw.mini_stop.setMinimumWidth(38)
        for b in (mw.mini_air, mw.mini_stop):
            top.addWidget(b)
        cv.addLayout(top)
        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        mw.mini_seek = SeekSlider(Qt.Orientation.Horizontal)
        mw.mini_seek.setRange(0, 1000)
        mw.mini_seek.setObjectName("seek")
        mw.mini_seek.setFixedHeight(24)
        mw.mini_seek.sliderPressed.connect(lambda: setattr(mw.playctl, "_seeking", True))
        mw.mini_seek.sliderReleased.connect(lambda: mw.playctl.do_seek(mw.mini_seek))
        mw.mini_seek.valueChanged.connect(mw.playctl._seek_preview)
        no_wheel(mw.mini_seek)
        bottom.addWidget(mw.mini_seek, 1)
        mw.mini_time = QLabel(mw.np_time.text())
        mw.mini_time.setObjectName("muted")
        steady_number(mw.mini_time, "00:00 / 00:00")
        bottom.addWidget(mw.mini_time)
        cv.addLayout(bottom)
        connection = QHBoxLayout()
        mw.mini_connection = CutPill()
        mw.mini_connection.setObjectName("pill")
        mw.mini_connection.setMinimumWidth(0)
        mw.mini_connection.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        mw.mini_connection.clicked.connect(mw._mini_setup)
        connection.addWidget(mw.mini_connection, 1)
        mw.mini_mic = QPushButton()
        mw.mini_mic.setCheckable(True)
        mw.mini_mic.setFixedHeight(28)
        mw.mini_mic.setToolTip(_("Mute or unmute your mic for others. Your sounds still "
                                   "play for them."))
        mw.mini_mic.toggled.connect(mw.routectl.on_mic_toggle)
        mw.mini_mic.clicked.connect(lambda: usage.used("mini-mic-mute"))   # clicks only
        mw.mini_mic.clicked.connect(mw.routectl._warn_mute_does_nothing)
        connection.addWidget(mw.mini_mic)
        mw.mini_bun = QPushButton()
        mw.mini_bun.setFixedSize(34, 28)
        mw.mini_bun.setToolTip(BUN_TIP)
        mw.mini_bun.setAccessibleName(_("Turn into Bun"))
        mw.mini_bun.setIconSize(QSize(20, 20))
        self._paint_mini_bun()
        mw.mini_bun.clicked.connect(mw.bunctl.enter_bun_mode)
        connection.addWidget(mw.mini_bun)
        # the way back: dragged too small for the board, the window turned into this by
        # itself, with nothing on it saying so or how to get the board back
        mw.mini_full = QPushButton()
        mw.mini_full.setFixedSize(34, 28)
        mw.mini_full.setToolTip(_("Full board: the window got too small for the board, so "
                                  "it shows this mini player. Click (or drag the window "
                                  "bigger) to get the board back."))
        mw.mini_full.setAccessibleName(_("Full board"))
        icons.set_icon(mw.mini_full, "expand", size=18)
        mw.mini_full.clicked.connect(mw.fitctl.grow_to_board)
        connection.addWidget(mw.mini_full)
        cv.addLayout(connection)
        v.addWidget(card)
        mw._sync_mini_mic()
        icons.set_icon(mw.mini_pp, "play", "on_accent", size=16)
        return page

    def _build_mixer(self) -> QFrame:
        """The levels strip along the bottom, the same on every tab: three labelled
        boxes, left to right the way the sound flows — your mic, what others hear,
        your own headphones. (Each tab's own volume sits in that tab's bar.)"""
        mw = self.mw
        c = mw.cfg
        # one slim bar: three groups side by side with a thin line between, each
        # labelled inline (a title row over each box made the strip twice as tall)
        f = QFrame()
        f.setObjectName("deck")
        f.setMinimumHeight(BAR_H)
        h = mw._mixer_layout = QHBoxLayout(f)
        h.setContentsMargins(12, 6, 12, 6)
        h.setSpacing(14)
        mw.mixer = f
        mw._deck_titles = []
        mw._deck_rows = []
        mw._decks = []   # each group, with the line before it
        # too narrow for all three: one group shown whole (what others hear, unless
        # you pick another) and the other two as icon buttons that bring theirs up
        mw._deck_tabs = []
        mw._mixer_one = mw._mixer_tight = False
        mw._mixer_focus = 1

        def group(icon: str, title: str, tip: str) -> tuple[QLabel, QHBoxLayout]:
            sep = vsep() if mw._decks else None
            if sep is not None:
                h.addWidget(sep)
            tab = QPushButton()
            tab.setObjectName("iconbutton")
            tab.setProperty("quiet", True)
            tab.setToolTip(title)
            tab.setAccessibleName(title)
            icons.set_icon(tab, icon, "muted")
            tab.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            tab.clicked.connect(lambda _c=False, i=len(mw._decks): mw._focus_deck(i))
            tab.hide()
            h.addWidget(tab)
            mw._deck_tabs.append(tab)
            deck = QWidget()
            deck.setObjectName("decktop")
            row = QHBoxLayout(deck)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            mw._deck_rows.append(row)
            lbl = QLabel(title)
            lbl.setObjectName("decktitle")
            lbl.setToolTip(tip)
            row.addWidget(CapIcon(lbl, icon, tip=tip))
            row.addWidget(lbl)
            mw._deck_titles.append(lbl)
            mw._decks.append((deck,) if sep is None else (sep, deck))
            h.addWidget(deck)
            return lbl, row

        mw.mic_lbl, row = group("mic", _("My mic"),
                                  _("Your real microphone, and how loud your voice is for others"))
        mw.chk_mic = QCheckBox(_("Others hear it"))
        mw.chk_mic.setToolTip(_("Send your voice to others along with the sounds.\nUntick for "
                                  "sounds only: they hear your sounds but not your mic."))
        mw.chk_mic.setChecked(c.mic_enabled)
        mw.chk_mic.toggled.connect(mw.routectl.on_mic_toggle)
        mw.chk_mic.clicked.connect(mw.routectl._warn_mute_does_nothing)   # clicks only
        row.addWidget(mw.chk_mic)
        mw.vol_mic = VolumeControl(c.mic_vol, meter=True,
                                     tip=_("How loud your voice is for others. The dot shows "
                                           "activity when you talk"))
        mic_meter = mw.vol_mic.meter
        assert mic_meter is not None   # meter=True
        mw.mic_meter = mic_meter
        # shown alone (_mixer_one_at_a_time) its slider takes the room, up to its own
        # most (150 px), with what's left after it
        row.addWidget(mw.vol_mic, 1)
        row.addStretch(0)

        send_lbl, row = group("live", _("What others hear"),
                              _("Everything going out to others right now (Discord, a game, "
                                "OBS…): your mic plus whatever is live"))
        mw.out_meter = Meter()
        mw.out_meter.setMinimumWidth(60)
        mw.out_meter.setToolTip(_("Level of what others receive (Discord, the game, OBS…)"))
        row.addWidget(mw.out_meter, 1)
        # straight into the mic, not in it yet: the meter moves with your voice, but the
        # sounds don't reach anyone. Said right by it, until they're in (statuscontrol)
        mw.voice_only = QPushButton(_("Voice only"))
        mw.voice_only.setObjectName("vchip")
        mw.voice_only.setProperty("state", "warn")
        mw.voice_only.setCursor(Qt.CursorShape.PointingHandCursor)
        mw.voice_only.setToolTip(_("Others hear your voice, but not your sounds: they aren't "
                                     "in your mic yet. Click to set it up."))
        mw.voice_only.clicked.connect(lambda: mw.tabs.setCurrentWidget(mw.setup_page))
        mw.voice_only.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        mw.voice_only.hide()
        row.addWidget(mw.voice_only)
        # its right end in line with the seek slider's above (EdgeMatch)
        meter_pad = QSpacerItem(0, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        row.addItem(meter_pad)

        def set_meter_pad(px: int, row=row):
            meter_pad.changeSize(px, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
            row.invalidate()

        mw._bar_edges = EdgeMatch(mw.seek, mw._name_seek.set_pad_right,
                                  mw.out_meter, set_meter_pad)
        mw.btn_check = QPushButton(_("Hear what they hear"))
        mw.btn_check.setObjectName("miccheck")
        # its name by hand: a narrow window blanks the words (on_mic_check keeps it)
        mw.btn_check.setAccessibleName(_("Hear what they hear"))
        mw.btn_check.setProperty("short_text", _("Listen"))   # a narrow window's word
        mw.btn_check.setCheckable(True)
        mw.btn_check.setToolTip(_("Plays your mic into your headphones on top of the sounds, "
                                    "exactly what others hear. A red banner shows while it's on."))
        mw.btn_check.toggled.connect(mw.on_mic_check)
        icons.set_icon(mw.btn_check, "ear", checked_color="#ffffff")
        row.addWidget(mw.btn_check)
        mw.btn_check.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        h.setStretchFactor(mw._decks[1][-1], 1)   # the "what others hear" group takes the room

        mw.hp_lbl, row = group("headphones", _("My headphones"),
                                 _("Only what YOU hear. Doesn't change anything for others."))
        mw.vol_mon = VolumeControl(c.mon_vol, tip=_("Only what YOU hear, doesn't change "
                                                      "anything for others"))
        row.addWidget(mw.vol_mon, 1)
        row.addStretch(0)
        for vol in (mw.vol_mic, mw.vol_mon):   # no gap between the slider and its %
            lay = vol.layout()
            assert lay is not None   # made in VolumeControl.__init__
            vol.setMaximumWidth(lay.maximumSize().width())

        for box, key in ((mw.vol_mic, "mic_vol"), (mw.vol_mon, "mon_vol")):
            box.changed.connect(lambda v, key=key: mw.set_option(key, v))
        return f

    def _build_sounds_page(self) -> QWidget:
        mw = self.mw
        c = mw.cfg
        page = QWidget()
        left = QVBoxLayout(page)
        left.setContentsMargins(0, 8, 0, 0)
        mw._sounds_lay = left
        left.setSpacing(8)
        # one framed surface for the toolbar, every control the same height
        mw.sounds_toolbar = QFrame()
        mw.sounds_toolbar.setObjectName("soundstoolbar")
        tb = QHBoxLayout(mw.sounds_toolbar)
        tb.setContentsMargins(8, 6, 8, 6)
        tb.setSpacing(6)
        # every way in under one button: a stray click opens a menu, not a file picker
        add = mw.btn_add = QPushButton(_("Add"))
        # flat like the rest of the toolbar; the accent colour marks it as the main one
        add.setObjectName("soundadd")
        add.setToolTip(_("Add sounds: files, a folder, a recording, a link or a free pack "
                         "(or drag files onto the window)"))
        icons.set_icon(add, "music", "accent", size=18)
        am = mw._add_menu = DropdownMenu(add)
        icons.set_icon(am.addAction(_("Sound files"), mw.impctl.add_dialog), "music")
        icons.set_icon(am.addAction(_("A whole folder"), mw.impctl.add_folder_dialog), "folder")
        icons.set_icon(am.addAction(_("Record"), mw.soundctl.record_dialog), "mic")
        icons.set_icon(am.addAction(_("From a link"), mw.impctl.add_from_link), "link")
        icons.set_icon(am.addAction(_("Free sound packs"), mw.impctl.show_packs), "download")
        add.setMenu(am)
        add.setProperty("toolbarMenu", True)
        mw.search = QLineEdit()
        mw.search.setObjectName("soundssearch")
        # short, so it isn't cut to "Search sounds… …" at normal widths; the tooltip
        # has the rest
        mw.search.setPlaceholderText(_("Search sounds or paste a link"))
        mw._search_tip = _("Type to filter your sounds; Enter searches the web (YouTube, "
                             "TikTok, Myinstants…). Or paste a link (YouTube, SoundCloud, "
                             "TikTok, most media sites) to see it, then play or add it")
        mw.search.setToolTip(mw._search_tip)
        icons.clear_button(mw.search)
        mw.search.setMinimumWidth(SEARCH_MIN_W)   # until the window gets narrow (_init_fit)
        mw.search.setMaximumWidth(SEARCH_MAX_W)
        # typing regrids only when the pads shown change (35 ms a key with 600 pads),
        # and only once it pauses (_on_search_text); text set by the app filters at once
        mw._search_wait = QTimer(mw, singleShot=True, interval=SEARCH_WAIT_MS)
        mw._search_wait.timeout.connect(
            lambda: mw.searchctl.apply_filter(mw.search.text(), lazy=True))
        mw._search_typed = None
        mw.search.textEdited.connect(mw.searchctl._on_search_edited)
        mw.search.textChanged.connect(mw.searchctl._on_search_text)
        mw.search.returnPressed.connect(mw.searchctl.on_search_enter)
        icons.set_icon(mw.search.addAction(QIcon(), QLineEdit.ActionPosition.LeadingPosition),
                       "search",
                       "muted")
        # the web search: Enter does it; this button shows the site it goes to and picks
        # another from its menu
        # its words while there's room: a lone site logo didn't say it searches the web
        mw.btn_yt = QPushButton(_("Search online"))
        mw.btn_yt.setAccessibleName(_("Search online"))
        mw.btn_yt.setToolTip(_("Search YouTube, SoundCloud, TikTok sounds, Myinstants… for "
                                 "what's typed (or press Enter), play or add the audio"))
        icons.set_icon(mw.btn_yt, "youtube", "accent", "accent", size=18)
        # which site Enter searches: the button shows it, its menu picks another
        mw._site_menu = DropdownMenu(mw.btn_yt)
        mw.btn_yt.setMenu(mw._site_menu)
        mw.btn_yt.setProperty("toolbarMenu", True)
        more = mw.btn_more = QPushButton(_("Library"))
        more.setToolTip(_("Export your sounds and settings to a file, or import a backup or "
                          "sound pack"))
        icons.set_icon(more, "archive", size=18)
        mm = DropdownMenu(more)
        icons.set_icon(mm.addAction(_("Import a backup or sound pack"), mw.impctl.import_dialog),
                       "folder")
        icons.set_icon(mm.addAction(_("Free sound packs"), mw.impctl.show_packs), "download")
        om = mm.addMenu(_("Import from another soundboard"))
        icons.set_icon(om.menuAction(), "copy")
        for src in otherboards.sources():
            icons.set_icon(om.addAction(f"{src.name}…",
                                        lambda src=src: mw.impctl.import_other(src)),
                           "sounds")
        pm = mw._packs_menu = mm.addMenu(_("My sound packs"))
        icons.set_icon(pm.menuAction(), "sounds")
        pm.aboutToShow.connect(lambda: mw.impctl._fill_packs_menu(pm))
        mm.addSeparator()
        icons.set_icon(mm.addAction(_("Export everything (sounds + settings)"),
                                    mw.impctl.export_board), "download")
        mw._act_export_cat = mm.addAction(_("Export this category"), mw.impctl.export_category)
        icons.set_icon(mw._act_export_cat, "download")
        mm.addSeparator()
        icons.set_icon(mm.addAction(_("Recently deleted sounds"), mw.rmctl.show_deleted), "trash")
        icons.set_icon(mm.addAction(_("Open the sounds folder"), mw.impctl.open_sounds_folder),
                       "folder")   # here too, for when the window's too narrow for its button
        mm.aboutToShow.connect(lambda: (
            mw._act_export_cat.setEnabled(bool(mw.cfg.category)),
            pm.menuAction().setVisible(bool(backup.packs()))))
        more.setMenu(mm)
        more.setProperty("toolbarMenu", True)
        mw.btn_bin = QPushButton()
        mw.btn_bin.setToolTip(_("Sounds you removed: bring them back, exactly as they were"))
        icons.set_icon(mw.btn_bin, "trash")
        mw.btn_bin.clicked.connect(mw.rmctl.show_deleted)
        mw.btn_folder = QPushButton(_("Sounds folder"))
        mw.btn_folder.setToolTip(_("Open the folder your sounds are kept in. Sound files you "
                                     "drag into it join the board by themselves."))
        icons.set_icon(mw.btn_folder, "folder", size=18)
        mw.btn_folder.clicked.connect(mw.impctl.open_sounds_folder)
        mw.rmctl._label_bin()
        # the most-used app-wide hotkeys in one click; the full list is in Settings
        mw.btn_keys = QPushButton()
        mw.btn_keys.setToolTip(_("Quick hotkeys: set the ones people use most, or open every "
                                   "hotkey in Settings"))
        icons.set_icon(mw.btn_keys, "keyboard", size=18)
        km = DropdownMenu(mw.btn_keys)
        km.aboutToShow.connect(lambda: mw.hkctl._fill_quick_hotkeys(km))
        mw.btn_keys.setMenu(km)
        mw.btn_keys.setProperty("toolbarMenu", True)
        km.setTitle(_("Quick hotkeys"))
        mm.addSeparator()
        mm.addMenu(km)
        for utility in (mw.btn_folder, mw.btn_keys, mw.btn_bin):
            utility.setParent(page)
            utility.hide()
        # make things, find things, then the library's tools
        tb.addWidget(add)
        tb.addWidget(vsep())
        tb.addWidget(mw.search, 1)
        tb.addWidget(mw.btn_yt)
        tb.addStretch(0)   # past SEARCH_MAX_W: the room goes here, the library tools stay right
        tb.addWidget(vsep())
        tb.addWidget(more)
        tb.addWidget(vsep())
        # the pads' order (as dragged, A-Z, newest, most played)
        mw.btn_view = QPushButton()
        mw.btn_view.setAccessibleName(_("Sort by"))
        vm = DropdownMenu(mw.btn_view)
        vm.setToolTipsVisible(True)
        vm.aboutToShow.connect(lambda: mw.padctl._fill_view_menu(vm))
        mw.btn_view.setMenu(vm)
        mw.btn_view.setProperty("toolbarMenu", True)
        mw.padctl._label_view()
        tb.addWidget(mw.btn_view)
        # cards or a list, the same switch as the Apps and Voice tabs
        mw.pad_view_toggle = ViewToggle(c.pad_view, _("Sounds"))
        mw.pad_view_toggle.changed.connect(mw.padctl.set_pad_view)
        tb.addWidget(mw.pad_view_toggle)
        # Creation actions have their own surfaces; library tools stay quiet.
        for b in (mw.btn_folder, more, mw.btn_bin, mw.btn_keys,
                  mw.btn_yt, mw.btn_view):
            b.setProperty("quiet", True)
        size = QSlider(Qt.Orientation.Horizontal)
        size.setRange(110, 240)
        c.pad_width = min(max(c.pad_width, 110), 240)   # the pads are built with it next
        size.setValue(c.pad_width)
        size.setFixedWidth(90)
        size.setToolTip(_("Card size"))
        # a drag re-lays every pad at most every PAD_SIZE_WAIT_MS, not on each step
        mw._pad_size_wait = QTimer(mw, singleShot=True, interval=PAD_SIZE_WAIT_MS)
        mw._pad_size_wait.timeout.connect(lambda: mw.set_pad_width(size.value()))
        size.valueChanged.connect(lambda _v: mw._pad_size_wait.isActive()
                                  or mw._pad_size_wait.start())
        no_wheel(size)
        size_lbl = QLabel(_("Card size"))
        size_lbl.setObjectName("muted")
        tb.addWidget(size_lbl)
        tb.addWidget(size)
        mw._pad_size = (size_lbl, size)
        # the list view has rows, not cards: a row size takes the slider's place there
        rows_lbl = QLabel(_("Row size"))
        rows_lbl.setObjectName("muted")
        mw.btn_rows = QPushButton()
        mw.btn_rows.setAccessibleName(_("Row size"))
        mw.btn_rows.setToolTip(_("How tall the rows in the list are"))
        rm = DropdownMenu(mw.btn_rows)
        rm.aboutToShow.connect(lambda: mw.padctl._fill_rows_menu(rm))
        mw.btn_rows.setMenu(rm)
        mw.btn_rows.setProperty("toolbarMenu", True)
        mw.btn_rows.setProperty("quiet", True)
        mw.btn_rows.setFixedHeight(CONTROL_H)
        tb.addWidget(rows_lbl)
        tb.addWidget(mw.btn_rows)
        mw._row_size = (rows_lbl, mw.btn_rows)
        mw._size_tight = False   # the window too narrow for either (_init_fit)
        mw.padctl._label_rows()
        mw.padctl._show_size_picker()
        for b in (add, mw.btn_yt, mw.btn_folder, more, mw.btn_keys,
                  mw.btn_bin, mw.btn_view, mw.search):
            b.setFixedHeight(CONTROL_H)
        # held in a row whose margins make the toolbar span exactly the pads below it
        # (_fit_toolbar): its edges line up with the first and last card
        hold = mw._toolbar_hold = QWidget()
        hl = QHBoxLayout(hold)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(mw.sounds_toolbar)
        left.addWidget(hold)
        mw.cat_bar = mw.catctl._build_categories()
        left.addWidget(mw.cat_bar)
        mw.linkbar = LinkBar(
            mw.engine, c, lambda: PAD_COLORS[len(mw.cfg.sounds) % len(PAD_COLORS)],
            lambda: {m.fingerprint: m.name for m in mw.cfg.sounds if m.fingerprint})
        mw.linkbar.sound_ready.connect(mw.soundctl.on_downloaded)
        mw.linkbar.played.connect(mw.searchctl.on_link_played)
        mw.linkbar.board_busy = mw.playctl._board_song_playing
        mw.linkbar.up_next_changed.connect(
            lambda *__: mw.playctl._update_chips(mw.engine.playing()))
        # a link in the search box shows as a result card (nothing downloads until Play / Add)
        mw._link_wait = QTimer(mw, singleShot=True, interval=LINK_WAIT_MS)
        mw._link_wait.timeout.connect(mw.searchctl._show_link)
        mw.linkbar.link_changed.connect(mw.searchctl._on_link_changed)
        left.addWidget(mw.linkbar)
        mw.ytresults = SearchResults()
        mw.ytresults.play.connect(lambda r: mw.searchctl._from_youtube(r, play=True))
        mw.ytresults.add.connect(lambda r: mw.searchctl._from_youtube(r, play=False))
        mw.linkbar.done.connect(lambda url, kind, ok: mw.ytresults.mark(url, kind, ok))
        mw.linkbar.progress.connect(mw.ytresults.progress)
        left.addWidget(mw.ytresults, 1)

        mw.grid = PadGrid()
        mw.grid.pad_w = c.pad_width
        mw.grid.listed = c.pad_view == "list"
        mw.grid.row_size = c.list_rows
        mw.grid._spacing()
        mw.grid.reorder.connect(mw.soundctl.on_reorder)
        # queued: the import (and any question it asks) runs after the drop returns,
        # so Explorer isn't frozen until a dialog is answered
        mw.grid.files_dropped.connect(mw.impctl.import_files,
                                        Qt.ConnectionType.QueuedConnection)
        mw.grid.image_dropped.connect(mw.padctl.set_picture, Qt.ConnectionType.QueuedConnection)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(mw.grid)
        scroll.verticalScrollBar().valueChanged.connect(mw.transctl._scroll_background_board)
        mw._pad_scroll = scroll
        a11y.scroll_stop(scroll, _("Your sounds"))   # the pads are the Tab stops
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        # the pads fit the width
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left.addWidget(scroll, 1)
        scroll.verticalScrollBar().rangeChanged.connect(lambda *_r: mw.fitctl._fit_toolbar())
        mw.grid.laid_out.connect(mw.fitctl._fit_toolbar)
        mw.fitctl._fit_toolbar()
        mw._pads_home = (left, left.indexOf(scroll))   # the mini player borrows it
        mw.ytresults.closed.connect(scroll.show)   # the results take the pads' place
        mw.ytresults.closed.connect(mw.catctl._cat_row.show)   # ...and the categories' row
        mw.ytresults.closed.connect(mw.searchctl._results_closed)
        mw.ytresults.fill_site_menu(mw._site_menu)
        mw.ytresults.source_changed.connect(mw.searchctl._on_site_picked)
        mw.ytresults.trend_asked.connect(mw.searchctl.show_trending)
        mw._pads_scroll = scroll
        # ---- "3 selected · Colour · Volume · Delete": Ctrl / Shift+click picks pads
        mw.selection = PadSelection(mw, scroll)
        left.addWidget(mw.selection.bar)
        # Ctrl+V anywhere on the page (a text box keeps its own): a copied clip from
        # the Apps tab's editor becomes a sound; a copied picture goes on the selected
        # pad (or the picked ones)
        # a click on the page's bare parts lands here
        page.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        page.setAccessibleName(_("Sounds"))   # (a screen reader says it when it has the focus)
        paste = QShortcut(QKeySequence.StandardKey.Paste, page)
        paste.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        paste.activated.connect(mw.padctl.paste_picture)
        # Ctrl+F anywhere on the page: into the search box
        find = QShortcut(QKeySequence.StandardKey.Find, page)
        find.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        find.activated.connect(mw.searchctl.focus_search)

        # ---- "now playing" chips: every sound playing, so each can be stopped (■) or
        # taken into the player (name) without clicking its pad, which would restart it
        mw.playing_row = QWidget()
        # the playing chips wrap onto more lines: one line of four overlapping sounds'
        # chips (~900 px) turned a narrower window into the mini player, and every
        # playing sound must stay reachable, so none are left out. Up next is one chip
        # after them, its list a pop-up (upnext.py)
        mw._chips_hl = Flow(mw.playing_row, gap=CHIPS_GAP)
        mw._chips = {}
        mw._chip_ids = ()
        mw._up_next_chip = None     # the row's Up next chip, when anything waits
        mw._up_next_popup = None    # its list, made the first time it's opened
        _Moved(mw.playing_row, mw.playctl._fit_up_next)
        mw.playing_row.hide()   # (placed over the player bar, on every tab: _build)


        f, th = bar()
        mw.btn_pp = PlayButton()
        mw.btn_pp.setObjectName("transport_play")
        mw.btn_pp.setAccessibleName(_("Play / pause"))
        mw.btn_pp.clicked.connect(mw.playctl.toggle_play_pause)
        mw._pp_icon = None
        mw.btn_st = QPushButton()
        mw.btn_st.setObjectName("transport_stop")
        mw.btn_st.setAccessibleName(_("Stop"))
        mw.btn_st.clicked.connect(mw.playctl.stop_current)
        icons.set_icon(mw.btn_st, "stop", size=16)
        mw.btn_skip = QPushButton()
        mw.btn_skip.setObjectName("transport_stop")   # the same quiet square as ■
        mw.btn_skip.setAccessibleName(_("Skip to the next sound in Up next"))
        mw.btn_skip.clicked.connect(mw.playctl.skip_next)
        icons.set_icon(mw.btn_skip, "next", size=16)
        for b in (mw.btn_pp, mw.btn_st, mw.btn_skip):
            b.setFixedSize(CONTROL_H, CONTROL_H)
        mw.np_name = QLabel(_("Pick a sound"))
        mw.np_name.setToolTip(_("Select a sound pad to use these playback controls."))
        mw.np_name.setTextFormat(Qt.TextFormat.PlainText)   # sound names are user / web text
        # the row's height, set by its buttons; its width follows the text inside
        # NameAndSeek, which never asks the page for a new layout (the name changes
        # with every pad press, and a relayout repainted every pad on the board)
        mw.np_name.setFixedHeight(CONTROL_H)
        mw.np_name.setStyleSheet("font-weight:600;")
        mw.seek = SeekSlider(Qt.Orientation.Horizontal)
        mw.seek.setRange(0, 1000)
        mw.seek.setObjectName("seek")
        mw.seek.sliderPressed.connect(lambda: setattr(mw.playctl, "_seeking", True))
        mw.seek.sliderReleased.connect(mw.playctl.do_seek)
        mw.seek.valueChanged.connect(mw.playctl._seek_preview)
        no_wheel(mw.seek)
        mw.np_time = QLabel("")   # blank until a sound is picked: "0:00 / 0:00" said nothing
        # room for a long sound's "75:12 / 112:40" in this font (84 px cut it, and
        # "12:34 / 45:67" too in the Consolas themes)
        mw.np_time.setFixedWidth(
            mw.np_time.fontMetrics().horizontalAdvance("888:88 / 888:88") + 4)
        mw.np_time.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        mw.np_time.setObjectName("muted")
        mw.np_time.hide()   # until there is a time to show (_set_np_time)
        th.addWidget(mw.btn_pp)
        th.addWidget(mw.btn_st)
        th.addWidget(mw.btn_skip)
        mw._name_seek = NameAndSeek(mw.np_name, mw.seek, 190)
        th.addWidget(mw._name_seek, 1)
        th.addWidget(mw.np_time)
        # only for a pad made from a video (soundboard.videos): shows it in step
        mw.btn_video = QPushButton(_("Video"))
        mw.btn_video.setToolTip(_("Watch this sound's video while it plays. The sound still "
                                    "goes out as normal; the video is only for you."))
        icons.set_icon(mw.btn_video, "video", size=16)
        mw.btn_video.clicked.connect(mw.transctl.show_video)
        mw.btn_video.hide()
        mw._video_for = ("", None)   # (sid, its video)
        mw._video_asking = None   # the sound whose video a thread looks up
        mw.video_found.connect(mw.transctl._video_found)
        mw.board_read.connect(mw.impctl._board_read)
        mw._video_win = None   # ui/videowindow.VideoWindow, made on first use
        th.addWidget(mw.btn_video)
        mw.speed_btn = SpeedPitchButton(
            "sounds", _("Changes every sound while it plays. To save a version, "
                        "right-click a pad → Effects."))
        mw.speed_btn.changed.connect(mw.playctl.on_live_speed)
        mw.speed_btn.fx_changed.connect(lambda fx: setattr(mw.engine, "sound_fx", fx))
        th.addWidget(mw.speed_btn)
        sep = vsep()
        th.addWidget(sep)
        vol_icon = QLabel(_("Sounds"))
        vol_icon.setObjectName("decktitle")
        th.addWidget(vol_icon)
        mw.vol_sound = VolumeControl(c.sound_vol, tip=_("How loud your sounds are, type up to "
                                                          "1000% in the box"))
        mw.vol_sound.changed.connect(lambda v: mw.set_option("sound_vol", v))
        mw.vol_sound.changed.connect(lambda v: mw.playctl.sound_volume_changed(v))
        th.addWidget(mw.vol_sound)
        mw.chk_monitor = QCheckBox(_("Hear it myself"))
        mw.chk_monitor.setChecked(c.monitor_sounds)
        mw.chk_monitor.toggled.connect(lambda b: mw.set_option("monitor_sounds", b))
        th.addWidget(mw.chk_monitor)
        mw._transport_vol = (sep, vol_icon, mw.vol_sound)
        # under the tabs, not in this page: the other tabs show it too while a sound
        # plays, so it can be paused or stopped from anywhere (_show_transport)
        mw.transport = f
        mw.playctl._set_pp_icon("play")
        return page

    def _build_setup_page(self) -> WidthScroll:
        """One-time setup and the rarely-touched stuff: where the audio goes,
        devices, the recorded test, EQ, levelling."""
        mw = self.mw
        c = mw.cfg
        page = WidthScroll(lambda: mw._pages.width() - SHUT_W - 2 * BODY_SIDE,
                           lambda: mw.fitctl._setup_one_col())
        page.setWidgetResizable(True)
        page.setFrameShape(QFrame.Shape.NoFrame)
        a11y.scroll_stop(page, _("Setup"))
        body = QWidget()
        page.dl_column = body   # the download bar lines up with these cards
        _Moved(body, mw.fitctl._fit_dl_bar)
        inner = capped(body, margins=(0, 12, 12, 12))   # not a 900 px wide card at full screen; the
        # cards' left edge lines up with the download bar and the other tabs
        sections = QVBoxLayout(body)
        sections.setContentsMargins(0, 0, 0, 0)
        sections.setSpacing(16)
        # a grid, not two columns: your mic and who's listening share its first row, so
        # they're always the same height and the cards under them line up
        cols = mw._setup_cols = QGridLayout()
        sections.addLayout(cols)
        sections.addStretch(1)
        cols.setContentsMargins(0, 0, 0, 0)
        cols.setSpacing(16)
        lcol, rcol = mw._setup_lr = QVBoxLayout(), QVBoxLayout()
        for i, col in enumerate((lcol, rcol)):
            col.setSpacing(16)
            cols.addLayout(col, 2, i)   # (rows 0 and 1: the card pairs, when side by side)
        page.setWidget(inner)

        # ---- how it works + the one thing to set in Discord
        # straight into the mic: what to do if a voice app chops the sounds up sits
        # behind an ⓘ (DESIGN section 4), not as a paragraph under "Nothing to set"
        mw.btn_mictips = info_button(_("Sounds chopped up?"))
        mw.btn_mictips.clicked.connect(mw.tipctl._show_mic_tips)
        mw.btn_mictips.hide()
        # the heading: a mic, the title, its ⓘ, then the status pill at the end, all on
        # the title's cap height (DESIGN section 4, *Card headings*)
        mw.mic_pill = QLabel(_("Not set up"))   # (its height: the text changes later)
        mw.mic_pill.setObjectName("pill")
        mw.mic_pill.hide()
        howcard, cv = card(_("Your virtual mic"), roomy=True, icon="mic",
                           beside=mw.btn_mictips, end=(mw.mic_pill,))
        assert howcard.heading_title is not None   # (titled)
        mw.how_title = howcard.heading_title   # renamed for the other routes
        flow = mw.mic_flow = QFrame()
        flow.setObjectName("micflow")
        fv = QVBoxLayout(flow)
        fv.setContentsMargins(14, 14, 14, 14)
        fv.setSpacing(10)
        mw.flow_mic = QLabel()
        mw.flow_snd = QLabel(_("Your sounds, radio and voice effects"))
        arrow = QLabel(_("↓   the app mixes them together"))
        arrow.setObjectName("hint")
        mw.flow_out = QLabel()
        for ic, w in (("mic", mw.flow_mic), ("volume", mw.flow_snd), ("", arrow),
                      ("live", mw.flow_out)):   # mic or cable alike
            w.setTextFormat(Qt.TextFormat.RichText)
            w.setWordWrap(True)
            row = QHBoxLayout()
            row.setSpacing(8)
            if ic:
                row.addWidget(icon_label(ic))
            else:
                row.addSpacing(26)
            row.addWidget(w, 1)
            if w is mw.flow_out:
                output = QFrame()
                output.setObjectName("micoutput")
                ov = QVBoxLayout(output)
                ov.setContentsMargins(12, 12, 12, 12)
                ov.addLayout(row)
                fv.addWidget(output)
            else:
                fv.addLayout(row)
        cv.addWidget(flow)
        # straight into the mic, not in it yet: the mic itself works (its level moves)
        # and the sounds aren't in it, two different things. A box of its own says the
        # first, with a tick and the live level, so "Not set up" under it can't read as
        # "your mic is broken"
        voice = mw.mic_voice = QFrame()
        voice.setObjectName("micstatus")
        vh = QHBoxLayout(voice)
        vh.setContentsMargins(12, 10, 12, 10)
        vh.setSpacing(10)
        tick = QLabel()
        tick.setFixedSize(20, 20)
        icons.set_label_icon(tick, "check", "ok_text", size=20)
        vh.addWidget(tick, 0, Qt.AlignmentFlag.AlignTop)
        vlines = QVBoxLayout()
        vlines.setSpacing(4)
        vh.addLayout(vlines, 1)
        vtop = QHBoxLayout()
        vtop.setSpacing(10)
        works = QLabel(_("Your mic works"))
        works.setObjectName("micline")
        theme.set_tone(works, "ok")
        vtop.addWidget(works, 0, Qt.AlignmentFlag.AlignVCenter)
        mw.mic_voice_sub = ElidedLabel()
        mw.mic_voice_sub.setObjectName("hint")
        mw.mic_voice_sub.setMinimumWidth(40)
        vtop.addWidget(mw.mic_voice_sub, 0, Qt.AlignmentFlag.AlignVCenter)
        mw.voice_meter = Meter()
        mw.voice_meter.setFixedWidth(90)
        mw.voice_meter.setToolTip(_("Your voice"))
        vtop.addWidget(mw.voice_meter, 0, Qt.AlignmentFlag.AlignVCenter)
        vtop.addStretch(1)
        vlines.addLayout(vtop)
        heard = QLabel(_("Onion Board hears you, and Discord and games already hear your "
                         "voice through it."))
        heard.setWordWrap(True)
        vlines.addWidget(heard)
        voice.hide()
        cv.addWidget(voice)
        # straight into the mic: one status box instead of the picture above (it works
        # by itself, and the mic helper puts it back when Windows takes it off): a big
        # icon, what's happening, the mic's name and its live level. The step below
        # only when it needs a click.
        box = mw.mic_status = QFrame()
        box.setObjectName("micstatus")
        bh = QHBoxLayout(box)
        bh.setContentsMargins(12, 10, 12, 10)
        bh.setSpacing(10)
        mw.mic_state_icon = QLabel()
        mw.mic_state_icon.setFixedSize(20, 20)
        bh.addWidget(mw.mic_state_icon, 0, Qt.AlignmentFlag.AlignTop)
        lines = QVBoxLayout()
        lines.setSpacing(8)
        bh.addLayout(lines, 1)
        # line 1: what's happening, the mic, its live level
        top = QHBoxLayout()
        top.setSpacing(10)
        mw.mic_line = QLabel()
        mw.mic_line.setObjectName("micline")
        top.addWidget(mw.mic_line, 0, Qt.AlignmentFlag.AlignVCenter)
        mw.mic_sub = ElidedLabel()
        mw.mic_sub.setObjectName("hint")
        mw.mic_sub.setMinimumWidth(40)
        top.addWidget(mw.mic_sub, 0, Qt.AlignmentFlag.AlignVCenter)
        mw.card_meter = Meter()
        mw.card_meter.setFixedWidth(90)
        mw.card_meter.setToolTip(_("Your mic"))
        top.addWidget(mw.card_meter, 0, Qt.AlignmentFlag.AlignVCenter)   # by its name
        top.addStretch(1)
        # working: a fresh copy or off, right here (Settings → Audio has every mic)
        from soundboard.ui.audiorecovery import explanation
        mw.btn_michange = QPushButton(_("Change mic"))
        mw.btn_michange.setProperty("quiet", True)
        mw.btn_michange.setToolTip(_("Put your sounds into another mic instead"))
        mw.btn_michange.clicked.connect(mw.micctl._pick_mic)
        mw.btn_micredo = QPushButton(_("Reinstall"))
        mw.btn_micredo.setProperty("quiet", True)
        mw.btn_micredo.setToolTip(explanation("reinstall"))
        mw.btn_micredo.clicked.connect(lambda: mw.micctl._ask_mic_effect("reinstall"))
        mw.btn_micoff = QPushButton(_("Remove"))
        mw.btn_micoff.setObjectName("danger")
        mw.btn_micoff.setProperty("quiet", True)
        mw.btn_micoff.setToolTip(explanation("remove"))
        mw.btn_micoff.clicked.connect(lambda: mw.micctl._ask_mic_effect("remove"))
        lines.addLayout(top)
        # line 2, when there's something to say or do: why, then the buttons
        mw.mic_reason = QLabel()
        mw.mic_reason.setWordWrap(True)
        mw.mic_reason.setTextFormat(Qt.TextFormat.RichText)
        mw.mic_reason.hide()
        lines.addWidget(mw.mic_reason)
        mw.mic_ways = Flow(gap=8)
        lines.addLayout(mw.mic_ways)
        for b in (mw.btn_michange, mw.btn_micredo, mw.btn_micoff):   # (wraps when narrow)
            b.hide()
            mw.mic_ways.addWidget(b)
        box.hide()
        mw._mic_icon = None
        mw._mic_tone = None   # the mic box's last tone (a flash when it turns "ok")
        mw._ways_in = None   # which row the set-up buttons are in (_place_ways)
        cv.addWidget(box)
        cv.addWidget(box)
        mw.helper_checked.connect(mw.micctl._helper_known)
        mw.step_lbl = QLabel()
        mw.step_lbl.setWordWrap(True)
        mw.step_lbl.setTextFormat(Qt.TextFormat.RichText)
        mw.step_lbl.setObjectName("micguide")
        cv.addWidget(mw.step_lbl)
        # an old mic part: one amber banner with its one button, in the step's place
        mw.mic_update_note = QFrame()
        mw.mic_update_note.setObjectName("micupdatebar")
        nh = QHBoxLayout(mw.mic_update_note)
        nh.setContentsMargins(14, 10, 10, 10)
        nh.setSpacing(12)
        mw.mic_update_icon = icon_label("warn", color="warn_text")
        nh.addWidget(mw.mic_update_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        mw.mic_update_text = QLabel()
        mw.mic_update_text.setTextFormat(Qt.TextFormat.RichText)
        mw.mic_update_text.setWordWrap(True)
        nh.addWidget(mw.mic_update_text, 1)
        mw.btn_micupdate = QPushButton(_("Update now"))
        mw.btn_micupdate.setObjectName("primary")
        from soundboard.ui.micupdate import _shield
        _shield(mw.btn_micupdate)
        mw.btn_micupdate.clicked.connect(mw.micctl._accept_mic_update)
        nh.addWidget(mw.btn_micupdate, 0, Qt.AlignmentFlag.AlignVCenter)
        mw.mic_update_note.hide()
        cv.addWidget(mw.mic_update_note)
        mw.setup_show = SetupShow(height=96, left=True)   # Bun builds it, by the buttons
        mw.setup_show.done.connect(mw.statusctl._update_flow)   # (the button's back, if needed)
        cv.addWidget(mw.setup_show)
        mw.btn_install = QPushButton(_("Install the free virtual cable"))
        mw.btn_install.setObjectName("primary")
        mw._cable_started = False   # (I've installed it: check again waits for this)
        def install_clicked():
            if mw.cfg.route == "mic":
                mw.micctl.attach_mic()
                return

            def install():
                mw._cable_started = True
                mw.micctl.install_cable()
            cableconfirm.ask(mw, install, mw.micctl.attach_mic)   # (only if they need it)
        mw.btn_install.clicked.connect(install_clicked)
        # what set_icon last put on it (only set when it changes)
        mw._install_icon = None
        # on the mic route it's the main button (put my sounds into my mic): it glows then
        mw.install_glow = Glow(mw.btn_install)
        mw.install_glow.set_on(False)
        mw.btn_attach = QPushButton(_("Put my sounds into my mic"))   # (tip: no cable)
        mw.btn_attach.setToolTip(_("Onion Board puts your sounds into your real mic, so "
                                     "Discord and games need no virtual cable and nothing picked"))
        mw.btn_attach.clicked.connect(mw.micctl.attach_mic)
        icons.set_icon(mw.btn_attach, "mic")
        mw.attach_glow = Glow(mw.btn_attach)   # the one to press, among the card's colours
        mw.btn_attach.hide()
        # the ways to set it up, side by side at their own size (wraps when narrow)
        ways = Flow(gap=8)
        # the mic on a row of its own, then "or" and the rest: the cable is the fallback
        # for the few who'd rather not, not the next step
        # (straight in the card, at its own width: a row with a stretch kept a gap of
        # its own while the button was hidden, and the card came up short)
        cv.addWidget(mw.btn_attach, 0, Qt.AlignmentFlag.AlignLeft)
        mw.ways_or = QLabel(_("or"))
        mw.ways_or.setObjectName("hint")
        mw.ways_or.hide()
        ways.addWidget(mw.ways_or)   # first in the row, level with the buttons' middle
        mw.btn_usecable = QPushButton(_("Use the cable"))   # (in its tile, below)
        mw.btn_usecable.setToolTip(_("Use a free virtual cable instead: you pick it as the "
                                       "mic in Discord and games"))
        # not installed yet: asked first (only for those who need it); there already,
        # it just switches
        mw.btn_usecable.clicked.connect(lambda: mw.micctl.use_cable_instead()
                                        if engine.virtual_outputs() else cableconfirm.ask(
            mw, mw.micctl.use_cable_instead, lambda: None, _("Keep using my mic")))
        icons.set_icon(mw.btn_usecable, "cable")
        mw.btn_usecable.hide()
        mw.mic_attached.connect(mw.micctl._mic_attached)
        mw._attaching = False
        mw._attach_release = None   # busy.hold on btn_install while it's being set up
        mw._settle_until = 0.0      # just set up: Windows is still loading it
        mw._done_toast = None   # "done" / "updated": said once it works
        icons.set_icon(mw.btn_install, "cable", "on_accent")
        mw.ways_or.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        mw.ways_or.setMinimumHeight(mw.btn_install.sizeHint().height())   # (the buttons')
        ways.addWidget(mw.btn_install)
        # Connect your chat is hidden until there's a chat to connect: its guide is here
        # meanwhile (that card held nothing else, while nothing was set up or on Nobody)
        mw.btn_guide = self._guide_button()
        mw.btn_guide.hide()
        mw.btn_guide.setProperty("quiet", True)
        ways.addWidget(mw.btn_guide)
        # (the row straight in the card: inside another row its height came up short)
        cv.addLayout(ways)
        mw._ways = ways
        # straight into the mic works: the cable is only a fallback, so offer to remove it
        mw.btn_rmcable = QPushButton(_("Remove"))   # (in the cable's tile: it says which)
        mw.btn_rmcable.setAccessibleName(_("Remove the virtual cable"))
        mw.btn_rmcable.setToolTip(_("Uninstalls VB-Cable. Your sounds go straight into your "
                                      "mic, so Onion Board doesn't need it"))
        icons.set_icon(mw.btn_rmcable, "cable")
        mw.btn_rmcable.clicked.connect(mw.micctl.remove_cable)
        mw.btn_rmcable.hide()
        mw.cable_removed.connect(mw.micctl._cable_removed)
        mw._cable_gone = False   # removed this session (Windows lists it till a restart)
        # is VB-Cable's setup program there to remove it with: looked up on a thread (a
        # file check in Program Files, on every redraw, could stall on a slow disk) and
        # asked again when the devices are re-scanned. None = not known yet
        mw._vb_setup = None
        mw._vb_setup_asking = False
        mw.cable_setup_found.connect(mw.micctl._cable_setup_found)
        mw.rmcable_note = hint_label(
            _("<b>You don't need the virtual cable any more</b>, it was only the backup. Remove "
              "it, or keep it if another program uses it (Voicemeeter, another soundboard)."))
        mw.rmcable_note.setTextFormat(Qt.TextFormat.RichText)
        mw.rmcable_note.hide()
        cv.addWidget(mw.rmcable_note)
        mw.btn_rmcable.setProperty("quiet", True)   # (beside Use the cable, in its tile)
        mw.btn_rescan = QPushButton(_("I've installed it: check again"))
        mw.btn_rescan.clicked.connect(lambda: mw.devctl.rescan_with_feedback(mw.btn_rescan))
        icons.set_icon(mw.btn_rescan, "reload")
        ways.addWidget(mw.btn_rescan)   # with the other ways, not a row of its own
        # straight into the mic: the other ways as two tiles under the status, like the
        # setup guide's (before, two lone buttons said "use the cable" and "remove the
        # cable" side by side with no why, over an empty card)
        alt = mw.mic_alt = QWidget()
        al = QVBoxLayout(alt)
        al.setContentsMargins(0, 4, 0, 0)
        al.setSpacing(10)
        head = QLabel(_("Optional: other ways to send your sounds"))
        head.setObjectName("section")
        head.setProperty("head", True)
        al.addWidget(head)
        tiles = mw.mic_alt_tiles = TileRow()   # stacked when narrow, never clipped
        mw.alt_cable, mw.alt_cable_words = alt_tile(
            "cable", _("Virtual cable"), "", mw.btn_usecable, mw.btn_rmcable)
        tiles.addTile(mw.alt_cable)
        mw.btn_pickdev = QPushButton(_("Pick a device"))
        icons.set_icon(mw.btn_pickdev, "sliders")
        mw.btn_pickdev.clicked.connect(mw.micctl._pick_send_device)
        mw.alt_device = alt_tile(
            "sliders", _("Another device"),
            _("For streamers and mixers: send your sounds to Voicemeeter, OBS, a mixer or a "
              "capture card, or to nobody."), mw.btn_pickdev)[0]
        tiles.addTile(mw.alt_device)
        al.addWidget(tiles)
        alt.hide()
        cv.addWidget(alt)
        helpcard, hv = card(_("Connect your chat"), roomy=True, icon="speech")
        hv.addWidget(hint_label(_("Choose your app for the recommended microphone settings.")))
        chat = Flow(gap=8)   # at their own size, wrapping, not five full-width bars
        mw.btn_chat = QPushButton(_("Make it sound clean in Discord"))
        mw.btn_chat.setToolTip(_("The Discord settings that stop it chopping up your sounds, "
                                   "and a check that listens to what Discord does to them"))
        icons.set_icon(mw.btn_chat, "headphones")
        mw.btn_chat.clicked.connect(lambda: mw.statusctl.show_chat_guide("discord"))
        chat.addWidget(mw.btn_chat)
        mw.btn_game = QPushButton(_("Set up game voice chat"))
        mw.btn_game.clicked.connect(lambda: mw.statusctl.show_chat_guide("game"))
        chat.addWidget(mw.btn_game)
        mw.btn_meeting = QPushButton(_("Zoom, Teams or a browser call"))
        mw.btn_meeting.setToolTip(_("The settings in Zoom, Microsoft Teams and calls in a web "
                                      "page that stop them treating your sounds as noise"))
        mw.btn_meeting.clicked.connect(lambda: mw.statusctl.show_chat_guide("meeting"))
        chat.addWidget(mw.btn_meeting)
        mw.btn_nomic = QPushButton(_("Game has no microphone setting?"))
        mw.btn_nomic.clicked.connect(mw.micctl.open_windows_mic)
        chat.addWidget(mw.btn_nomic)
        chat.addWidget(self._guide_button())
        hv.addLayout(chat)
        mw.helpcard = helpcard


        # ---- devices
        devcard, av = card(_("Devices"), roomy=True, icon="headphones")
        mw.dev_card = devcard
        av.addWidget(hint_label(_("Already set up for you, only change these if "
                                  "something's wrong.")))
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(12)
        mw.cb_main, mw.cb_mon, mw.cb_mic = QComboBox(), QComboBox(), QComboBox()
        # your mic (the normal way), nobody, or a device by name (set_route). cb_main
        # isn't shown: it keeps the device list the picked device is checked against.
        mw.cb_route = QComboBox()
        mw.cb_route.setToolTip(_("Normally your sounds go into your mic, so everyone who hears "
                                   "your mic hears them. Only pick something else to send them "
                                   "somewhere instead: Voicemeeter, a mixer, a device OBS "
                                   "captures, or a virtual cable."))
        for r, (ic, text, cb) in enumerate((
                ("headphones", _("My headphones"), mw.cb_mon),
                ("mic", _("My mic"), mw.cb_mic),
                ("live", SEND_TO, mw.cb_route))):
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
        mw.setup_connection = QLabel()
        mw.setup_connection.setObjectName("hint")
        mw.setup_connection.setWordWrap(True)
        av.addWidget(mw.setup_connection)
        mw.cb_main.setParent(devcard)   # never a window of its own
        mw.cb_main.hide()
        # more places at once (streamers): a row per extra device, + and − (alsosend)
        mw.also_views = []
        mw.also_rows = alsosend.build(mw, grid, 3, icons_col=True)
        mw.setup_hint = hint_label("")
        mw.setup_hint.setTextFormat(Qt.TextFormat.RichText)
        av.addWidget(mw.setup_hint)
        mw.btn_cablefix = QPushButton(_("Fix the cable: both ends to 48 kHz"))
        mw.btn_cablefix.setToolTip(_("Sets the cable's playback and recording side to 48 kHz, "
                                       "so it passes your sound through without converting it"))
        mw.btn_cablefix.clicked.connect(lambda: busy.run_busy(
            mw.btn_cablefix, _("Switching the cable to 48 kHz…"), mw.micctl.fix_cable_format,
            lambda ok: _("✓ Done") if ok and not mw.micctl.cable_bad
            else _("Couldn't, see below")))
        mw.btn_cablefix.hide()
        av.addWidget(mw.btn_cablefix, 0, Qt.AlignmentFlag.AlignLeft)
        no_wheel(mw.cb_main, mw.cb_mon, mw.cb_mic, mw.cb_route)
        for cb, attr in ((mw.cb_main, "main_device"), (mw.cb_mon, "mon_device"),
                         (mw.cb_mic, "mic_device"), (mw.cb_route, "route")):
            cb.activated.connect(lambda _i, cb=cb, attr=attr: mw.routectl.on_device(cb, attr))
        ref = QPushButton(_("Re-scan devices"))
        icons.set_icon(ref, "reload")
        ref.clicked.connect(lambda: mw.devctl.rescan_with_feedback(ref))
        av.addWidget(ref, 0, Qt.AlignmentFlag.AlignLeft)

        # ---- who's listening: shape the sounds for the voice chat on the other end
        from soundboard.ui.destpanel import DestPanel
        mw.dest_panel = DestPanel(mw)
        destcard, dv = card(_("Who's listening"), _("Where people hear you: a game, a voice "
                                                    "chat app, or a stream. Your sounds are "
                                                    "shaped to come through clearly."),
                            roomy=True, icon="ear",
                            beside=mw.dest_panel.help_btn)   # What do these do?
        dv.addWidget(mw.dest_panel)
        dv.addStretch(1)   # as tall as your mic beside it: the room goes at the bottom

        # ---- sound shaping
        eqcard, ev = card(_("Equalizer and volume"), roomy=True, icon="sliders")
        mw.eq_card = eqcard
        mw.eq = EqPanel(c.eq_enabled, c.eq_target, c.eq_preset, c.eq_gains, fold=True)
        mw.eq.changed.connect(mw.on_eq)
        ev.addWidget(mw.eq)
        mw.chk_level = QCheckBox(_("Level volumes (all sounds equally loud)"))
        mw.chk_level.setChecked(c.level_volumes)
        mw.chk_level.toggled.connect(mw.on_level_toggle)
        ev.addWidget(mw.chk_level)
        for lay in (cv, av, ev):   # as tall as the card beside it: the room goes at the bottom
            lay.addStretch(1)
        # side by side, in pairs that share a grid row (the same height, so their tops
        # and bottoms line up): your mic and who's listening, then devices and the EQ;
        # connect your chat under the devices. All open: they fit the screen, so
        # nothing folds away. One column when narrow: what you check every day first
        mw._setup_top = (howcard, destcard)
        mw._setup_pairs = (mw._setup_top, (devcard, eqcard))
        mw._setup_wide = ((howcard, devcard, helpcard), (destcard, eqcard))
        mw._setup_narrow = (howcard, destcard, devcard, helpcard, eqcard)
        # Onion Pocket, once it's installed: a card on the left, in Connect your chat's
        # place (that moves to the right, under the EQ). fitctl._place_pocket
        from soundboard.ui.pocketcard import PocketCard
        mw.pocket_card = PocketCard(mw)
        mw._setup_cards = (howcard, devcard, helpcard, destcard, eqcard)
        mw._setup_stacked = None
        mw.fitctl._stack_setup(False)
        mw.on_eq(*mw.eq.state())   # push the saved EQ into the engine
        destination.apply(mw.cfg, mw.engine)   # ...and the destination mode (Who's listening)
        from soundboard.ui.destpanel import apply_send
        apply_send(mw.cfg, mw.engine)          # ...and mono / ducking
        return page

    def _paint_mini_bun(self):
        """The mini player's Bun button, in this theme's colours."""
        mw = self.mw
        mw.mini_bun.setIcon(self._bun_icon())
        if getattr(mw, "_tray_bun", None) is not None:   # (the tray's menu: theme changes)
            mw._tray_bun.setIcon(self._bun_icon())

    def _bun_icon(self) -> QIcon:
        """A line-drawn bunny like the other icons (the cartoon Bun looked out of place
        among them)."""
        return icons.icon("bun")

    def _guide_button(self) -> QPushButton:
        mw = self.mw
        guide = QPushButton(_("Step-by-step guide"))
        guide.setToolTip(_("Walks you through mic, headphones, where your sounds go (your mic, "
                           "the cable, another device or nowhere) and Discord"))
        icons.set_icon(guide, "check")
        guide.clicked.connect(lambda: (usage.used("setup-guide-opened"), mw.run_setup()))
        return guide
