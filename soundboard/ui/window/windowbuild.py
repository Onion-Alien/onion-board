"""Building the main window's parts: the frame (tab rail, tabs, mixer strip, the bars on
top), the mini player, the mixer, the Sounds page and the Setup page. Runs once, while
the window is made; the parts it makes are the window's own (declared on MainWindow), and
what they do lives in the window's other controllers.

MainWindow makes one ``WindowBuilder`` (``MainWindow.builder``) and calls ``_build_ui``
from ``__init__``; everything here runs on the UI thread. The pages are built by the
mixins it inherits: the mini player and the mixer (playerbuild.py), the Sounds page
(soundsbuild.py) and the Setup page (setupbuild.py)."""
from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from soundboard.core import usage
from soundboard.online import net
from soundboard.control import remote
from soundboard.i18n import _
from soundboard.ui.kit import icons
from soundboard.ui.window import sidebar, taboff
from soundboard.ui.window.controller import Controller
from soundboard.ui.window.downloadbar import DownloadBar
from soundboard.ui.window.dropveil import DropVeil
from soundboard.ui.window.fitcontrol import BODY_SIDE
from soundboard.ui.kit.topbar import TopBar
from soundboard.ui.window.livedot import set_tint as set_live_tint
from soundboard.ui.bun.logowidget import LogoWidget
from soundboard.ui.kit.panel import ShownStack
from soundboard.ui.window.playerbuild import PlayerBuild
from soundboard.ui.window.setupbuild import SetupPageBuild
from soundboard.ui.window.soundsbuild import SoundsPageBuild
from soundboard.ui.window.sidebar import SideTabs
from soundboard.ui.window.tabcontrol import TAB_INDEX, TAB_KEYS, TABS, rail_order
from soundboard.ui.kit.widgets import (
    DropdownMenu,
    SteadyTabs,
    WindowRoot,
)

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow


def version_text() -> str:
    """The version, as the title bar and header show it: "1.5.5", or "1.5.5 from
    source" when run with Python rather than the installed app."""
    from soundboard import __version__
    if getattr(sys, "frozen", False):
        return __version__
    return _("{version} from source", version=__version__)


class WindowBuilder(Controller, PlayerBuild, SoundsPageBuild, SetupPageBuild):
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
        mw._full_row = QHBoxLayout(root)   # the tab rail (ui/window/sidebar.py), then the rest
        mw._full_row.setContentsMargins(0, 0, 0, 0)
        mw._full_row.setSpacing(0)
        body = QWidget()
        mw._full_row.addWidget(body, 1)
        rv = QVBoxLayout(body)
        mw._body_lay = rv
        rv.setContentsMargins(BODY_SIDE, 10, BODY_SIDE, 10)
        rv.setSpacing(8)

        # ---- what was the header: the onion and name, the setup pill, Live, Stop all and
        # Settings, all on the tab rail now (ui/window/sidebar.py); made here for _paint_logo
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
        from soundboard.ui.setup.destpanel import ModeButton
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
        icons.set_icon(mw.btn_about, "bun", size=sidebar.ICON, gap=False)
        mw.about_menu = DropdownMenu(mw.btn_about)
        mw.about_menu.aboutToShow.connect(mw.aboutctl._fill_about_menu)
        mw.btn_about.clicked.connect(mw.aboutctl._show_about_menu)
        mw.themectl._paint_logo()

        # the bars across the top: one look for all of them (ui/kit/topbar.py), and only
        # one shows at a time
        # an urgent fix (a release whose notes say "Urgent: …", updates.urgent), a chat
        # app setting that eats the sounds, an app using the mic raw: a bar across the
        # window, not only the small Update pill. Hidden only until next start.
        mw.urgent_bar = TopBar("warn", "warn")
        mw.urgent_lbl = mw.urgent_bar.words
        # Onion Board's fix downloading: the update card's bar and words, not new ones
        mw.urgent_prog = QProgressBar()
        mw.urgent_prog.setObjectName("updatebar")
        mw.urgent_prog.setRange(0, 100)
        mw.urgent_prog.setTextVisible(False)
        mw.urgent_prog.setFixedHeight(sidebar.UpdateCard.BAR_H)
        mw.urgent_prog.hide()
        mw.urgent_bar.add_row(mw.urgent_prog)
        mw.urgent_sub = QLabel()
        mw.urgent_sub.setObjectName("hint")
        mw.urgent_sub.setTextFormat(Qt.TextFormat.PlainText)
        mw.urgent_sub.setWordWrap(True)
        mw.urgent_sub.hide()
        mw.urgent_bar.add_row(mw.urgent_sub)
        mw.urgent_btn = mw.urgent_bar.add_button(primary=True)
        mw.urgent_btn.clicked.connect(mw.alertctl._urgent_clicked)
        mw.urgent_bar.close_btn.setAccessibleName(_("Hide"))
        mw.urgent_bar.close_btn.setToolTip(_("Hide until Onion Board starts again"))
        mw.urgent_bar.close_btn.clicked.connect(mw.alertctl._hide_urgent)
        mw.urgent_bar.hide()
        rv.addWidget(mw.urgent_bar)

        # "Looks like you're using Discord. Set up for it?" (appsetup, _app_setup): one
        # slim bar, never a window, so it's safe while a game is up
        mw.setup_bar = TopBar("chat")
        mw.setup_lbl = mw.setup_bar.words
        mw.setup_no = mw.setup_bar.add_button(_("Not now"))
        mw.setup_no.clicked.connect(mw.appsetctl._setup_not_now)
        mw.setup_yes = mw.setup_bar.add_button(primary=True)
        mw.setup_yes.clicked.connect(mw.appsetctl._setup_yes_clicked)
        mw.setup_x = mw.setup_bar.close_btn
        mw.setup_x.clicked.connect(mw.appsetctl._setup_x_clicked)
        mw.setup_bar.hide()
        rv.addWidget(mw.setup_bar)

        mw.ff_bar = mw.ffctl.build_bar()   # FFmpeg (ui/window/ffmpegcontrol.py)
        rv.addWidget(mw.ff_bar)

        # Windows is in a language the board has but isn't showing: offered in that
        # language, so someone who can't read English finds it (_offer_language)
        mw.lang_bar = TopBar("speech")
        mw.lang_lbl = mw.lang_bar.words
        mw.lang_btn = mw.lang_bar.add_button(primary=True)
        mw.lang_btn.clicked.connect(lambda: mw.langctl.switch_language(mw._lang_offered))
        mw.lang_hide = mw.lang_bar.close_btn
        mw.lang_hide.clicked.connect(mw.langctl._no_language)
        mw.lang_bar.hide()
        mw._lang_offered = ""
        rv.addWidget(mw.lang_bar)

        # *Enjoying Onion Board?* (ui/window/enjoycontrol.py)
        mw.enjoy_bar = mw.enjoyctl.build_bar()
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
        # downloads: a card over the page's bottom-right corner, on every tab, never
        # pushing the page down; the toasts stand on it (toast_floor)
        mw.download_bar = DownloadBar(mw)
        # (the window's own slot, not a lambda: Qt drops it with the window)
        mw.download_bar.placed.connect(mw._relayout_toasts)

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
        for strip in (mw.urgent_bar, mw.setup_bar, mw.ff_bar, mw.lang_bar, mw.enjoy_bar):
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
        # a stand-in that loads nothing (ui/window/taboff.py)
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
        from soundboard.ui.window import moretabs
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
            mw.rail.output.lineClicked.connect(mw.netctl.open_line)
            mw.rail.output.lineClicked.connect(lambda _p: usage.used("on-air-line"))
        mw.remote_changed.connect(mw.netctl._net_follow, Qt.ConnectionType.QueuedConnection)
        remote.on_change(mw.netctl._remote_watch)
        tabs_live = getattr(getattr(mw, "voice", None), "live_tabs_changed", None)
        if tabs_live is not None:   # a Voice tab on: a line in the card too (_voice_lines)
            tabs_live.connect(mw.netctl._net_follow)
        mw.netctl._net_follow()
        # Ctrl+1... (or a tab's own key) jump to the tabs, Ctrl+Tab / Ctrl+Shift+Tab step
        # through them (the tab widget does that only while it has the focus)
        mw.tabctl.bind_tab_keys()
        QShortcut(QKeySequence("Ctrl+Tab"), mw, activated=lambda: mw.tabctl._go_tab(1))   # pyright: ignore[reportCallIssue]
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), mw, activated=lambda: mw.tabctl._go_tab(-1))   # pyright: ignore[reportCallIssue]
        mw.rail.orderChanged.connect(
            lambda order: mw.set_option("sidebar_order", [TAB_KEYS[i] for i in order]))
        # a tab asked for (the rail, Ctrl+1..., a link) while Settings is up: back to the
        # tabs, on that one
        mw.tabs.picked.connect(mw.setctl.close_settings)
        mw.tabs.picked.connect(mw.impctl.close_packs)
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
        mw.tab_info.setdefault("store", (
            _("Community"),
            _("Sounds and voices players share. Hear one first, add the ones you like, and "
              "vote so the best rise to the top. Share a sound puts one of yours up for "
              "everyone once it's been checked.")))
        tab =mw.cfg.tab if 0 <= mw.cfg.tab < mw.tabs.count() else 0
        mw.tabs.setCurrentIndex(tab if mw.tabs.isTabVisible(tab) else 0)
        mw.tabctl._focus_open_tab()
        mw.tabs.currentChanged.connect(lambda i: mw.set_option("tab", i))
        mw.tabs.currentChanged.connect(mw.tabctl._count_tab)   # names only (usage.py)
        mw.tabctl._count_tab(mw.tabs.currentIndex())
        # Setup's hints and flow, fresh as it's opened (only there: on every tab it was
        # ~4 ms here and ~15 on a slower PC of each switch, for nothing that changed)
        mw.tabs.currentChanged.connect(
            lambda i: i == TAB_INDEX["setup"] and mw.statusctl._update_status())
        mw.tabs.currentChanged.connect(mw._focus_sounds_page)
        mw.tabctl.mark_store_new()
        mw.tabs.currentChanged.connect(mw.newctl.follow)   # new sounds: seen, or counted
        mw.newctl.follow()
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
        # the download card stands on what shows at the page's foot
        mw.download_bar.float_in(body, mw._tabs_box, (mw.playing_row, mw.transport, mw.mixer))

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
            b.sound_for = mw._added_sound
        mw.download_bar.play_sound.connect(mw.playctl.play)
        mw.download_bar.show_sound.connect(mw._show_sound)
        mw.linkbar.queued.connect(mw.ytresults.queued)
        mw.ytresults.thumb_ready.connect(mw.download_bar.set_thumb)
        mw.ytresults.thumb_ready.connect(mw.mini_download_bar.set_thumb)


