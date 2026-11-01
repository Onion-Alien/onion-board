"""Building the main window's Sounds page (ui/window/windowbuild.py): its toolbar, the
search box, the pads and the bars around them.

A mixin WindowBuilder inherits, so every `self.` lookup is the same as before; it runs
once, on the UI thread, while the window is made."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from soundboard.core import backup
from soundboard import otherboards
from soundboard.i18n import _
from soundboard.sounds.library import PAD_COLORS
from soundboard.ui.kit import a11y, icons
from soundboard.ui.window.fitcontrol import SEARCH_MAX_W, SEARCH_MIN_W
from soundboard.ui.sounds.linkbar import LinkBar
from soundboard.ui.sounds.padbatch import PadSelection
from soundboard.ui.kit.panel import (
    ViewToggle,
    CONTROL_H,
    Flow,
    VolumeControl,
    bar,
    vsep,
)
from soundboard.ui.window.playbackcontrol import CHIPS_GAP
from soundboard.ui.kit.playbutton import PlayButton
from soundboard.ui.sounds.speedpitch import SpeedPitchButton
from soundboard.ui.kit.widgets import (
    DropdownMenu,
    NameAndSeek,
    PadGrid,
    SeekSlider,
    fit_placeholder,
)
from soundboard.ui.sounds.ytsearch import SearchResults
from soundboard.ui.kit.wheelguard import no_wheel

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

SEARCH_WAIT_MS = 100     # typing in the search box filters the pads once it pauses this long
LINK_WAIT_MS = 400       # a link in the search box is looked up once it stays this long
PAD_SIZE_WAIT_MS = 50    # dragging Pad size re-lays the pads at most this often
WIDE_TOOLBAR_W = 1500   # the Sounds toolbar this wide (about full screen) spreads out...
WIDE_GAP = 8            # ...its library tools by this much more each side


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


class _WideGaps(QObject):
    """The Sounds toolbar's library tools get WIDE_GAP more room each side once the bar
    is WIDE_TOOLBAR_W wide: full screen, they sat squeezed together beside a big empty
    middle. Narrower, the gaps are 0 again and the fitter works as before."""

    def __init__(self, bar: QWidget, gaps: list[QSpacerItem]):
        super().__init__(bar)
        self._gaps = gaps
        self._wide: bool | None = None
        bar.installEventFilter(self)

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Type.Resize:
            wide = obj.width() >= WIDE_TOOLBAR_W
            if wide != self._wide:
                self._wide = wide
                for gap in self._gaps:
                    gap.changeSize(WIDE_GAP if wide else 0, 0,
                                   QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
                lay = obj.layout()
                if lay is not None:
                    lay.invalidate()
        return False


class SoundsPageBuild:
    """The Sounds page of WindowBuilder's window (``mw``)."""

    if TYPE_CHECKING:   # WindowBuilder's (Controller)
        mw: MainWindow

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
        add.setToolTip(_("Add sounds: files, a folder, a recording or a link "
                         "(or drag files onto the window)"))
        icons.set_icon(add, "music", "accent", size=18)
        am = mw._add_menu = DropdownMenu(add)
        icons.set_icon(am.addAction(_("Sound files"), mw.impctl.add_dialog), "music")
        icons.set_icon(am.addAction(_("A whole folder"), mw.impctl.add_folder_dialog), "folder")
        icons.set_icon(am.addAction(_("Record"), mw.soundctl.record_dialog), "mic")
        icons.set_icon(am.addAction(_("From a link"), mw.impctl.add_from_link), "link")
        # (Free sound packs lives in the Library menu, once)
        add.setMenu(am)
        add.setProperty("toolbarMenu", True)
        mw.search = QLineEdit()
        mw.search.setObjectName("soundssearch")
        # short, so it isn't cut to "Search sounds… …" at normal widths; the tooltip
        # has the rest
        fit_placeholder(mw.search, _("Search sounds or paste a link"), _("Search sounds"),
                        _("Search"))
        # its whole job, whatever hint fits (a narrow window shows only "Search")
        mw.search.setAccessibleName(_("Search sounds or paste a link"))
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
        icons.set_icon(km.menuAction(), "keyboard")
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
        gaps: list[QSpacerItem] = []

        def gap():   # more room here when the bar is wide (_WideGaps)
            gaps.append(QSpacerItem(0, 0, QSizePolicy.Policy.Fixed,
                                    QSizePolicy.Policy.Minimum))
            tb.addItem(gaps[-1])
        tb.addWidget(vsep())
        gap()
        tb.addWidget(more)
        gap()
        tb.addWidget(vsep())
        gap()
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
        gap()
        # cards or a list, the same switch as the Apps and Voice tabs
        mw.pad_view_toggle = ViewToggle(c.pad_view, _("Sounds"))
        mw.pad_view_toggle.changed.connect(mw.padctl.set_pad_view)
        tb.addWidget(mw.pad_view_toggle)
        gap()
        _WideGaps(mw.sounds_toolbar, gaps)   # the toolbar owns it
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
        mw.linkbar.already_have.connect(mw._show_existing)
        mw.linkbar.played.connect(mw.searchctl.on_link_played)
        mw.linkbar.board_busy = mw.playctl._board_song_playing
        mw.linkbar.picture_for = lambda url: mw.ytresults.thumb_for(url)   # (made below)
        mw.linkbar.up_next_changed.connect(
            lambda *__: mw.playctl._update_chips(mw.engine.playing()))
        # a link in the search box shows as a result card (nothing downloads until Play / Add)
        mw._link_wait = QTimer(mw, singleShot=True, interval=LINK_WAIT_MS)
        mw._link_wait.timeout.connect(mw.searchctl._show_link)
        mw.linkbar.link_changed.connect(mw.searchctl._on_link_changed)
        mw.linkbar.links_changed.connect(mw.searchctl._on_links_changed)
        left.addWidget(mw.linkbar)
        mw.ytresults = SearchResults()
        mw.ytresults.play.connect(lambda r: mw.searchctl._from_youtube(r, play=True))
        mw.ytresults.add.connect(lambda r: mw.searchctl._from_youtube(r, play=False))
        mw.ytresults.add_all.connect(mw.searchctl.add_all)
        mw.linkbar.done.connect(lambda url, kind, ok: mw.ytresults.mark(url, kind, ok))
        mw.linkbar.progress.connect(mw.ytresults.progress)
        left.addWidget(mw.ytresults, 1)

        mw.grid = PadGrid()
        mw.grid.pad_w = c.pad_width
        mw.grid.listed = c.pad_view == "list"
        mw.grid.row_size = c.list_rows
        mw.grid._spacing()
        mw.grid.tab_after = mw.catctl.btn_cat_add   # Tab: categories, pads, player bar
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
        # only for a pad made from a video (soundboard.sounds.videos): shows it in step
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
            "sounds", _("Changes every sound while it plays. Save as new pad keeps it "
                        "as a pad of its own."))
        mw.speed_btn.changed.connect(mw.editctl.speed_changed)
        mw.speed_btn.fx_changed.connect(mw.editctl.fx_changed)
        mw.speed_btn.opening.connect(mw.editctl.pad_opening)   # the playing pad's own
        mw.speed_btn.closed.connect(mw.editctl.pad_closed)
        mw.speed_btn.save_new.connect(lambda: mw.editctl.save_live_copy())
        th.addWidget(mw.speed_btn)
        sep = vsep()
        th.addWidget(sep)
        # what it changes said where it shows: people took it for their headphones' volume
        # (that's "My headphones" in the levels strip; the send path uses sound_vol only)
        vol_tip = _("How loud others hear your sounds (and your stream). Your own "
                    "headphones have their own volume: My headphones, at the bottom. "
                    "Type up to 1000% in the box.")
        vol_icon = QLabel(_("Sounds for others"))
        vol_icon.setObjectName("decktitle")
        vol_icon.setToolTip(vol_tip)
        th.addWidget(vol_icon)
        mw.vol_sound = VolumeControl(c.sound_vol, tip=vol_tip)
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
