"""Settings window (a page inside the main window): the dialog, its categories and search,
and the card helpers its pages share. The pages themselves are in ui/settings/."""
from __future__ import annotations

import html
import logging
import re
from collections.abc import Callable

from PySide6.QtCore import QElapsedTimer, QEvent, QObject, QSignalBlocker, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (QAbstractButton, QApplication, QCheckBox, QComboBox, QDialog, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QScrollArea, QStyle, QStyledItemDelegate,
                               QStyleOptionViewItem, QTabWidget, QVBoxLayout, QWidget)
import shiboken6
from shiboken6 import isValid as qt_valid


from soundboard.ui.kit import busy, icons
from soundboard.ui.bun import onionalien
from soundboard.ui.kit import theme
from soundboard.ui.kit.wrapbutton import WrapButton
from soundboard.core import usage
from soundboard.i18n import _
from soundboard.ui.settings import Built, _button_row as _button_row
from soundboard.ui.settings.help import HelpPage
from soundboard.ui.settings.audio import AudioPage
from soundboard.ui.settings.appearance import AppearancePage, ThemeCard, ThemeGrid as ThemeGrid
from soundboard.ui.settings.keys import (KeysPage, HOTKEY_ACTIONS as HOTKEY_ACTIONS,
                                         HotkeyDialog as HotkeyDialog, pretty_key as pretty_key)
from soundboard.ui.settings.general import GeneralPage
from soundboard.ui.settings.connection import ConnectionPage
from soundboard.ui.settings.privacy import PrivacyPage
from soundboard.ui.settings.achievements import AchievementsPage
from soundboard.ui.settings.addons import AddonsPage
from soundboard.ui.settings.heading import Heading, _BackArrow, _Mark
from soundboard.ui.window.railsizes import ICON as RAIL_ICON

log = logging.getLogger(__name__)

# a search moves off the page you're on when another says the words this many times as often
BUSIER = 3


# Settings > About. The note is the author's own words, kept casual on purpose.
NOTE = _("No ads, no account, no spying, free forever. Found a bug? Tell me. Have fun."
         "\n\nOnionAlien")


class _Row(QStyledItemDelegate):
    """A category row. Narrow, it's an icon with no name: the icon goes in the middle
    of its highlight (the style put it at the left, with twice the room on its right)."""

    def paint(self, painter: QPainter, option, index):
        if index.data(Qt.ItemDataRole.DisplayRole):
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        icon = QIcon(opt.icon)   # (a copy: opt.icon is the option's own, blanked next)
        size = QSize(opt.decorationSize)
        opt.icon = QIcon()
        opt.features &= ~QStyleOptionViewItem.ViewItemFeature.HasDecoration
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        box = QStyle.alignedRect(opt.direction, Qt.AlignmentFlag.AlignCenter,
                                 size, opt.rect)
        icon.paint(painter, box, Qt.AlignmentFlag.AlignCenter,
                   QIcon.Mode.Selected if selected else QIcon.Mode.Normal)


class _AdvancedRow(_Row):
    """The Show advanced row: a clear gap over it with a thin line across, so the
    everyday pages above read as their own group. Only the row under the gap
    highlights."""
    GAP = 28

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(size.height() + self.GAP)
        return size

    def paint(self, painter: QPainter, option, index):
        line = QColor(theme.tokens().get("border", "#444"))
        y = option.rect.top() + self.GAP // 2
        painter.save()
        painter.setPen(QPen(line, 1))
        painter.drawLine(option.rect.left() + 8, y, option.rect.right() - 8, y)
        painter.restore()
        option.rect.setTop(option.rect.top() + self.GAP)
        super().paint(painter, option, index)


class SettingsDialog(QDialog, Built):
    """All settings in one place. `mw` is the MainWindow; changes apply immediately."""

    # narrower than this, the categories are icons only and the search box goes over
    # the page (the list and box took 212 px of a 440 px window)
    NARROW_W = 640
    TITLE_COG = 18   # the heading's cog, px
    PAGE_TOP = 18    # the pages start this far down: where a tab's do (its 10 + 8)
    BACK_PAD = "padding:7px 0px 7px 3px"   # (the arrow is moved by _level_icons)

    # the row between the everyday pages and the rest: Show advanced / Hide advanced.
    # It has an empty page of its own, so a row is still its page's tab index.
    ADVANCED = "advanced"

    def __init__(self, mw, page: str = "audio", lazy: bool = False):
        """A page in the main window, in place of the tabs (SettingsControl.open_settings),
        never a window of its own. `lazy`: build only `page` now and each other page
        the first time it's shown. Building all twelve under the app's style sheet took
        a second or two on every click of the cog; the tests build them all at once."""
        super().__init__(mw)
        # The pages (soundboard/ui/settings), before anything builds one.
        self.help = HelpPage(self)
        self.audio = AudioPage(self)
        self.appearance = AppearancePage(self)
        self.keys = KeysPage(self)
        self.general = GeneralPage(self)
        self.connection = ConnectionPage(self)
        self.privacy = PrivacyPage(self)
        self.addons = AddonsPage(self)
        self.achievements = AchievementsPage(self)
        self.heading = Heading(self)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.setObjectName("settingspage")   # the window's own background
        self.mw = mw
        self._caps_cache: dict[tuple, float] = {}   # (_caps_mid)
        if hasattr(mw, "tab_switched"):
            mw.tab_switched.connect(self._tab_switched)
        self.setWindowTitle(_("Settings"))
        lay = QVBoxLayout(self)
        # the main window's body has the side margins and none on top under Settings:
        # the heading rises level with the rail's name (_level_with_rail) and the pages
        # start PAGE_TOP down, where a tab's do
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.hk_buttons: dict[str, list[QPushButton]] = {}
        # what most people change first; the rest waits behind Show advanced
        pages = (("audio", _("Audio"), "volume", self.audio._audio),
                 ("appearance", _("Appearance"), "palette", self.appearance._appearance),
                 ("hotkeys", _("Hotkeys"), "keyboard", self.keys._hotkeys),
                 ("tabs", _("Tabs"), "sounds", self._tabs),
                 ("general", _("General"), "settings", self.general._general),
                 ("about", _("About"), "star", self.help._about),
                 (self.ADVANCED, _("Show advanced"), "sliders", None),
                 ("overlay", _("Overlay"), "gamepad", self.keys._overlay),
                 ("privacy", _("Privacy && security"), "shield", self.privacy._privacy),
                 ("connection", _("Connection"), "radio", self.connection._connection),
                 ("data", _("Data && quality"), "wave", self.privacy._data),
                 ("updates", _("Updates"), "reload", self.connection._updates),
                 ("help", _("Add-ons"), "plus", self.help._help),
                 ("remote", _("Remote"), "cable", self.addons._remote),
                 ("achievements", _("Achievements"), "trophy", self.achievements._achievements))
        self.categories = QListWidget()
        self.categories.setObjectName("settingscategories")
        self.categories.setAccessibleName(_("Settings categories"))
        self.categories.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.categories.setFixedWidth(196)
        self.categories.setIconSize(QSize(RAIL_ICON, RAIL_ICON))   # as the rail's tabs
        # the rows came out 1-4 px taller than the room at every window size (the last
        # row's padding), and a scroll bar showed for that: only for real overflow
        self.categories.verticalScrollBar().rangeChanged.connect(self._categories_bar)
        self._unbuilt: dict[int, Callable[[], QWidget]] = {}   # tab index -> its page's builder
        self._builders: dict[int, Callable[[], QWidget]] = {}  # every page's (mark_stale)
        self._page_attrs: dict[int, set[str]] = {}   # what each page keeps on the dialog
        self._stale: set[int] = set()   # built, to be built afresh when next shown
        for i, (key, title, icon, build) in enumerate(pages):
            sa = self._scroll()
            if build is not None:
                self._builders[i] = build
            if build is None:   # (the Show advanced row: nothing to show)
                self._fill(sa, QWidget())
            elif lazy and key != page:
                self._unbuilt[i] = build
            else:
                self._fill(sa, self._make(i))
            self.tabs.addTab(sa, title)
            icons.set_tab_icon(self.tabs, i, icon)
            item = QListWidgetItem(icons.icon(icon), title.replace("&&", "&"))
            item.setData(Qt.ItemDataRole.UserRole, icon)
            # (narrow: no text)
            item.setData(Qt.ItemDataRole.UserRole + 1, title.replace("&&", "&"))
            item.setSizeHint(QSize(180, 38))
            self.categories.addItem(item)
        self._category_icons()
        self.tabs.tabBar().hide()
        # the list is the tab bar now: the hidden one stayed in the Tab order (the tab
        # widget hands its focus to it), so Tab from the list went nowhere
        self.tabs.tabBar().setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabs.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabs.setFocusProxy(None)   # pyright: ignore[reportArgumentType]  # None clears it
        self._page_keys = [p[0] for p in pages]
        self._adv_row = self._page_keys.index(self.ADVANCED)
        adv = self.categories.item(self._adv_row)
        adv.setFlags(Qt.ItemFlag.ItemIsEnabled)   # a switch, never the page you're on
        self.categories.setItemDelegate(_Row(self.categories))
        self._adv_delegate = _AdvancedRow(self.categories)
        self.categories.setItemDelegateForRow(self._adv_row, self._adv_delegate)
        self.categories.currentRowChanged.connect(self._row_picked)
        self.categories.itemClicked.connect(self._row_clicked)
        self.categories.itemActivated.connect(self._row_clicked)   # (Enter)
        # a mouse press on the Show advanced row would make it the current row until the
        # release, so the page's own row lost its highlight and got it back on every
        # click: the press does the switch here instead, and the list never sees it
        self.categories.viewport().installEventFilter(self)
        self._adv_clicked = QElapsedTimer()
        self.tabs.currentChanged.connect(self._build_page)
        self.tabs.currentChanged.connect(self._page_shown)
        self._advanced = bool(getattr(mw.cfg, "settings_advanced", False))
        self._fold()
        self.show_page(page)
        self.privacy._offline_sync()
        # a search box over the categories: 13 pages are a lot to look through for one
        # switch. Typing hides every card without the word and every page without a card.
        self.search_box = QLineEdit()
        # (a page: "Settings" is the heading right over it)
        self.search_box.setPlaceholderText(_("Search"))
        icons.clear_button(self.search_box)
        self.search_box.setAccessibleName(_("Search settings"))
        self.search_box.setFixedWidth(196)
        # no right-click menu over a few words: Ctrl+C / Ctrl+V still copy and paste
        self.search_box.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._search_wait = QTimer(self, singleShot=True, interval=150)
        self._search_wait.timeout.connect(lambda: self._apply_search(self.search_box.text()))
        self.search_box.textChanged.connect(lambda _t: self._search_wait.start())
        find = QShortcut(QKeySequence.StandardKey.Find, self)
        find.activated.connect(lambda: (
            self.search_box.setFocus(Qt.FocusReason.ShortcutFocusReason),
            self.search_box.selectAll()))
        side = self._side = QVBoxLayout()
        side.setContentsMargins(0, self.PAGE_TOP, 0, 0)   # (raised by _level_with_rail)
        side.setSpacing(8)
        # a page, not a window: back to the tab you were on (as Escape or a rail
        # tab does), on its own row over the search with the page's name, so the
        # search box still lines up with the categories; narrow, over the icons
        back = self.back_btn = _BackArrow()
        back.setProperty("quiet", True)
        icons.set_icon(back, "back")
        back.setAccessibleName(_("Back"))
        back.setAutoDefault(False)
        back.clicked.connect(self.accept)
        # the page's name in the rail's "Onion Board" size, with a cog after it in the
        # theme's colour (decoration, not a button)
        self.page_title = QLabel(_("Settings"))
        self.page_title.setObjectName("pagetitle")
        self.title_cog = _Mark("settings", "accent", self.TITLE_COG)
        self.title_cog.setObjectName("pagetitlecog")   # (moved by _level_icons)
        self._title_cog()
        # Keep the arrow over the category icons, with room between its hover
        # background and the heading.
        back.setFixedWidth(26)   # (just round the arrow: the heading right after it)
        # 14 px of padding: the controls' height
        back.setStyleSheet(self.BACK_PAD)
        top = self._top = QHBoxLayout()
        top.setSpacing(2)   # (the heading close after the arrow)
        top.addWidget(back)
        top.addWidget(self.page_title)
        top.addSpacing(4)   # (the cog as close as the arrow)
        top.addWidget(self.title_cog)
        top.addStretch(1)
        side.addLayout(top)
        side.addWidget(self.search_box)
        side.addWidget(self.categories, 1)
        right = self._right = QVBoxLayout()   # (narrow: the search box on top)
        right.setContentsMargins(0, self.PAGE_TOP, 0, 0)
        right.setSpacing(8)
        right.addWidget(self.tabs, 1)
        content = self._content = QHBoxLayout()
        content.setSpacing(16)
        content.addLayout(side)
        content.addLayout(right, 1)
        # a search that finds nothing says so, in place of the pages
        self.no_match = QLabel()
        self.no_match.setObjectName("hint")
        self.no_match.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.no_match.setWordWrap(True)
        self.no_match.hide()
        right.addWidget(self.no_match, 1)
        lay.addLayout(content, 1)
        self._narrow = False

    BAR_SLACK = 8   # px the list may run over before its scroll bar shows

    def _categories_bar(self, _lo: int, hi: int):
        self.categories.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff if hi <= self.BAR_SLACK
            else Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    # ------------------------------------------------------------------ advanced
    def _row_picked(self, row: int):
        """A row became the current one: its page (the Show advanced row has none)."""
        if row >= 0 and row != self._adv_row:
            self.tabs.setCurrentIndex(row)

    def _row_clicked(self, item):
        """The Show advanced row clicked (or Enter on it). A double click's second
        click (and its activation) is the same click, not a second switch."""
        if self.categories.row(item) != self._adv_row:
            return
        clicked = self._adv_clicked
        if clicked.isValid() and clicked.elapsed() < QApplication.doubleClickInterval():
            self.categories.setCurrentRow(self.tabs.currentIndex())
            return
        self._adv_clicked.start()
        self._set_advanced(not self._advanced)

    def eventFilter(self, obj, e):
        cats = getattr(self, "categories", None)
        if (cats is not None and obj is cats.viewport()
                and e.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick,
                                 QEvent.Type.MouseButtonRelease)
                and cats.indexAt(e.position().toPoint()).row() == self._adv_row):
            # (a double click's second press comes as a DblClick: the same click)
            if e.type() == QEvent.Type.MouseButtonPress and e.button() == Qt.MouseButton.LeftButton:
                self._set_advanced(not self._advanced)
            return True
        return super().eventFilter(obj, e)

    def _page_shown(self, i: int):
        """The list follows the page; an advanced page opened from elsewhere (a link,
        Offline mode's Privacy page) opens the advanced rows too."""
        if i > self._adv_row and not self._advanced:
            self._set_advanced(True)
        if 0 <= i < len(self._page_keys):
            usage.used(f"settings-page-{self._page_keys[i]}")   # the page's name only
        self.categories.setCurrentRow(i)

    def _advanced_only(self, w: QWidget, show_when_basic: bool = False,
                       also: Callable[[], bool] | None = None) -> QWidget:
        """A card (or `show_when_basic`: its "more" button) on a basic page that only
        shows with Show advanced on: the expert ones (buffering, speech servers…) read as
        things a new user had to understand. `also`: another rule it must pass too
        (the voices card: only with the Voice tab)."""
        if not hasattr(self, "_adv_widgets"):
            self._adv_widgets: list[tuple[QWidget, bool]] = []
        self._adv_widgets.append((w, show_when_basic))
        w.setProperty("adv_card", not show_when_basic)
        w._adv_also = also   # pyright: ignore[reportAttributeAccessIssue]
        if not self._adv_shows(w, show_when_basic):
            w.hide()   # (never show() it here: not in its page yet, it'd flash up as a
        return w       # little window of its own)

    def _adv_shows(self, w: QWidget, basic: bool = False) -> bool:
        on = getattr(self, "_advanced", bool(getattr(self.mw.cfg, "settings_advanced", False)))
        also = getattr(w, "_adv_also", None)
        return on != basic and (also is None or also())

    def _sync_advanced_cards(self):
        for w, basic in getattr(self, "_adv_widgets", ()):
            if qt_valid(w):
                w.setVisible(self._adv_shows(w, basic))
                w.setProperty("search_hid", False)

    def _set_advanced(self, on: bool):
        self._advanced = on
        self._sync_advanced_cards()
        if on:
            usage.used("settings-advanced")
        if getattr(self.mw.cfg, "settings_advanced", None) != on:
            self.mw.set_option("settings_advanced", on)
        if not on and self.tabs.currentIndex() > self._adv_row:
            self.tabs.setCurrentIndex(0)   # (its row is about to go)
        self._fold()
        self.categories.setCurrentRow(self.tabs.currentIndex())

    def _fold(self, searching: bool | None = None):
        """The advanced rows hidden or shown, and the switch's words to match. A search
        shows every page it finds, and hides the switch. `searching`: whether words
        are being searched for (None: whether the box has any)."""
        item = self.categories.item(self._adv_row)
        title = (_("Hide advanced") + "  ▾") if self._advanced else (_("Show advanced") + "  ▸")
        item.setData(Qt.ItemDataRole.UserRole + 1, title)
        narrow = getattr(self, "_narrow", False)
        item.setText("" if narrow else title)
        item.setToolTip(title if narrow else "")
        if searching is None:
            box = getattr(self, "search_box", None)
            searching = box is not None and bool(box.text().split())
        item.setHidden(searching)
        if searching:
            return
        offline = self._offline_pages()
        for i in range(self._adv_row + 1, self.categories.count()):
            self.categories.item(i).setHidden(
                not self._advanced or self._page_keys[i] in offline)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.heading._fit_width(self.width())
        QTimer.singleShot(0, self.heading._level_with_rail)   # once the rows have their places

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self.heading._level_with_rail)

    def show_page(self, page: str):
        """Go to `page` (also when the window is open already and asked for another).
        Hidden in Offline mode: the Privacy page with its switch instead; an unknown
        page: the first one. A search in the box is cleared first, or it hid the page."""
        box = getattr(self, "search_box", None)
        if box is not None and box.text():
            box.clear()
            self._apply_search("")
        keys = self._page_keys
        if page in self._offline_pages():
            page = "privacy"
        i = keys.index(page) if page in keys and page != self.ADVANCED else 0
        self.tabs.setCurrentIndex(i)
        self._page_shown(i)
        self._build_page(self.tabs.currentIndex())

    # ------------------------------------------------------------------ search
    @staticmethod
    def _words_of(card: QWidget) -> str:
        """Every word a card shows, lower-cased: its labels, buttons, boxes and
        dropdown items (tags stripped: some labels are rich text)."""
        bits = []
        for w in card.findChildren(QWidget):
            # a painted name (ThemeCard): only text, not a widget kept as `name`
            if isinstance(name := getattr(w, "name", None), str) and name:
                bits.append(name)
            if isinstance(w, ThemeCard):
                bits.extend(("themes colors colours", _("Theme style"), _("Highlight colour")))
            if isinstance(w, (QLabel, QAbstractButton)):
                bits.append(w.text())
            elif isinstance(w, QComboBox):
                bits += [w.itemText(i) for i in range(w.count())]
            elif isinstance(w, QLineEdit):
                bits.append(w.placeholderText())
        return html.unescape(re.sub(r"<[^>]+>", " ", " ".join(bits))).lower()

    def _apply_search(self, text: str):
        """Hide every card without the words, and every page without a card left;
        land on the first page that has one. Empty: everything back."""
        words = text.lower().split()
        if words:
            self._searching = True
            try:
                # a page not built yet can't be searched (nor a stale one trusted: and
                # built afresh when shown, it would lose what the search hid)
                for i in [*self._unbuilt, *sorted(self._stale)]:
                    self._build_page(i)
            finally:
                self._searching = False
        first = named = None
        # whole words (at a word's start): the page that says them most, unless the one
        # you're on says them too, nearly as often ("tor" is inside "history" and
        # "monitor" on General: it goes to Connection, not the first page with the
        # letters; "theme", once in Lite mode's words on General, goes to Appearance)
        starts = [re.compile(r"\b" + re.escape(w)) for w in words]
        best, best_n, cur_n = None, 0, 0
        for i in range(self.tabs.count()):
            if i == self._adv_row:
                continue   # (_fold)
            title = self.categories.item(i).data(Qt.ItemDataRole.UserRole + 1).lower()
            if self._page_keys[i] in self._offline_pages():   # hidden in Offline mode
                self.categories.item(i).setHidden(True)
                continue
            if i in self._unbuilt:   # (only with no words: spaces, or cleared first)
                self.categories.item(i).setHidden(False)
                continue
            page = self._tab_page(i)
            hits = whole = 0
            for card in page.findChildren(QFrame, "setcard"):
                if card.property("offline_hid"):   # (_offline_hide) as if it weren't there
                    continue
                said = self._words_of(card) if words else ""
                match = all(w in title or w in said for w in words)
                if card.property("adv_card") and not self._advanced:
                    # an advanced card on a basic page: only a search brings it out
                    also = getattr(card, "_adv_also", None)
                    match = match and (also is None or also())
                    card.setVisible(bool(words) and match)
                    hits += bool(words) and match
                    if match and words:
                        whole += min(len(r.findall(f"{title} {said}")) for r in starts)
                    continue
                if not match and not card.isHidden():
                    card.hide()
                    card.setProperty("search_hid", True)
                elif match and card.property("search_hid"):
                    card.show()
                    card.setProperty("search_hid", False)
                if match and words and card is getattr(self, "look_box", None):
                    self._look_pick(words)   # (the look box: show the tab with the words)
                hits += match
                if match and words:
                    whole += min(len(r.findall(f"{title} {said}")) for r in starts)
            self.categories.item(i).setHidden(bool(words) and not hits)
            if whole > best_n:
                best, best_n = i, whole
            if i == self.tabs.currentIndex():
                cur_n = whole
            if hits and first is None:
                first = i
            # "hotkey" goes to the Hotkeys page, not the first page that mentions one
            if hits and named is None and words and all(w in title for w in words):
                named = i
        nothing = bool(words) and first is None
        if words:   # the names only, never what was typed (usage.py)
            usage.used("settings-search-nothing" if nothing else "settings-search")
        self.no_match.setText(_("No settings match “{text}”", text=text.strip()))
        self.no_match.setVisible(nothing)
        self.tabs.setVisible(not nothing)
        self._fold(bool(words))
        on_hidden = self.categories.item(self.tabs.currentIndex()).isHidden()
        if named is not None:
            self.tabs.setCurrentIndex(named)
        elif best is not None and cur_n * BUSIER <= best_n:
            self.tabs.setCurrentIndex(best)
        elif words and first is not None and on_hidden:
            self.tabs.setCurrentIndex(first)

    def _category_icons(self):
        for i in range(self.categories.count()):
            item = self.categories.item(i)
            name = item.data(Qt.ItemDataRole.UserRole)
            item.setIcon(icons.icon(name, "muted", selected="text_hi"))   # (as the rail's)
        if getattr(self, "title_cog", None) is not None:
            self._title_cog()
            QTimer.singleShot(0, self.heading._level_with_rail)   # (a new theme: maybe a new font)

    def _title_cog(self):
        """The heading's cog in this theme's accent (redrawn when the theme changes)."""
        self.title_cog.update()

    # ------------------------------------------------------------------ pages
    @staticmethod
    def _scroll() -> QScrollArea:
        """Pages scroll: a tall one (Hotkeys) otherwise gets squashed, rows on top of
        each other, whenever the window can't grow to fit it (maximized, small screen)."""
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QScrollArea.Shape.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sa.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # Tab goes straight to the page's first control
        return sa

    @staticmethod
    def _fill(sa: QScrollArea, page: QWidget):
        for label in page.findChildren(QLabel):
            # (a short field label beside its control keeps one line: wrapping, the
            # row squeezed it onto two with room to spare)
            label.setWordWrap(not label.property("keepline"))
        for combo in page.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(6)
        sa.setWidget(page)

    def _build_page(self, i: int):
        """A lazy page, the first time it's shown; a stale one (mark_stale) afresh."""
        if i in self._stale:
            self._rebuild_page(i)
        elif self._unbuilt.pop(i, None) is not None:
            self._fill(self._tab_area(i), self._make(i))

    def _make(self, i: int) -> QWidget:
        """Page i built, noting the attributes it keeps on the dialog (its widgets, its
        callbacks) for _rebuild_page."""
        before = set(vars(self))
        page = self._builders[i]()
        self._page_attrs[i] = set(vars(self)) - before
        return page

    def mark_stale(self, keys) -> None:
        """Those pages (the ones built) are built afresh the next time they're shown or
        searched: they show state from outside the config (downloads, add-ons, updates).
        A closed Settings that showed one is kept, not built again from scratch (a
        few hundred ms on a slower PC, and every page loaded again behind it)."""
        self._stale |= {i for i, k in enumerate(self._page_keys)
                        if k in keys and i in self._builders and i not in self._unbuilt}

    def _rebuild_page(self, i: int):
        """A stale page built afresh, in one go: what the old one kept on the dialog
        goes first (lists and dicts several pages fill stay), the new one is filled in,
        then the old one is freed. Until now the old one was alive, hidden, so anything
        still holding it (a download's answer) found it as it was; after, its widgets
        are gone, as when a whole Settings was freed (and out of those lists)."""
        self._stale.discard(i)
        for name in self._page_attrs.pop(i, ()):
            if not isinstance(vars(self).get(name), (dict, list)):
                vars(self).pop(name, None)
        sa = self._tab_area(i)
        old = sa.takeWidget()
        self._fill(sa, self._make(i))
        if old is not None:
            shiboken6.delete(old)

        def gone(x) -> bool:
            if isinstance(x, tuple):
                return any(gone(y) for y in x)
            return isinstance(x, QObject) and not qt_valid(x)
        for v in list(vars(self).values()):
            if isinstance(v, dict):
                for k in [k for k, w in v.items() if gone(k) or gone(w)]:
                    del v[k]
            elif isinstance(v, list):
                v[:] = [x for x in v if not gone(x)]

    def _tab_area(self, i: int) -> QScrollArea:
        """Page i's scroll area (each tab is one)."""
        sa = self.tabs.widget(i)
        assert isinstance(sa, QScrollArea)
        return sa

    def _tab_page(self, i: int) -> QWidget:
        """Page i's contents (a lazy one not built yet: its placeholder)."""
        page = self._tab_area(i).widget()
        assert page is not None
        return page

    @staticmethod
    def _card(title: str, hint: str = "", icon: str = "", end=()):
        """A Settings card: `icon` in front of the title (panel.heading_row, centred on
        its cap height), `end` at the far end of it (a status pill), the hint under it."""
        card = QFrame()
        card.setObjectName("setcard")
        theme.vary_texture(card)
        v = QVBoxLayout(card)
        v.setContentsMargins(14, 12, 14, 14)
        v.setSpacing(8)
        if icon:
            from soundboard.ui.kit.panel import heading_row
            row, t, _marks = heading_row(title, icon, end=end)
            # the title takes the room the row has, so it only wraps when it doesn't
            # fit (sharing it with the row's stretch, it wrapped at half the width)
            row.setStretch(row.count() - 1, 0)
            row.setStretch(1, 1)
            # one widget, so a page can hide the whole heading (the look box's tabs)
            head = QWidget()
            head.setLayout(row)
            v.addWidget(head)
        else:
            t = QLabel(title)
            t.setObjectName("section")
            v.addWidget(t)
        if hint:
            h = QLabel(hint)
            h.setObjectName("hint")
            h.setWordWrap(True)
            v.addWidget(h)
        return card, v

    def _page(self):
        w = QWidget()
        v = QVBoxLayout(w)
        # no top margin: the first card starts level with the search box
        v.setContentsMargins(0, 0, 16, 12)
        v.setSpacing(12)
        return w, v

    # Settings > Tabs: what each tab that can be switched off is for (taboff.KEYS)
    TAB_HINTS = {
        "radio": _("Internet radio stations from around the world."),
        "apps": _("Send another program's sound (a music player, a game) to others."),
        "triggers": _("Play a sound when something shows up on your screen (Onion Watch)."),
        "voice": _("The voice changer, AI voices and talking as a computer voice. Off: "
                   "your mic goes out as it is."),
        "store": _("Sounds and voices other players shared, voted on: add them, or share "
                   "your own."),
    }

    def _tabs(self):
        w, v = self._page()
        card, cv = self._card(
            _("Tabs"),
            _("Switch off the tabs you don't use. A switched-off tab is gone from the window and "
              "doesn't load at all, so nothing of it runs in the background. Switch it back on "
              "any time, here or with + More tabs after the tabs. Right-click a tab to hide it."),
            icon="sounds")
        from soundboard.ui.window.tabcontrol import TAB_KEYS, TABS
        self.tab_boxes: dict[str, QCheckBox] = {}
        for key, (text, _tip) in zip(TAB_KEYS, TABS):
            if key in self.TAB_HINTS:
                self.tab_boxes[key] = self._option(
                    cv, text, self.TAB_HINTS[key], self.mw.tabctl.tab_on(key),
                    lambda on, k=key: self.mw.tabctl.set_tab_on(k, on))
            else:   # Sounds and Setup: the board itself, and where it sends
                box = self._option(cv, text, _("Always on."), True, lambda _on: None)
                box.setEnabled(False)
        self.tabs_offline_note = QLabel(_("Offline mode is on, so the tabs that need the "
                                          "internet are hidden and greyed out here. Switch it "
                                          "off in Privacy & security to use them."))
        self.tabs_offline_note.setObjectName("hint")
        self.tabs_offline_note.setWordWrap(True)
        cv.addWidget(self.tabs_offline_note)
        v.addWidget(card)
        self.privacy._offline_sync()
        card, cv = self._card(_("Saved clips"), icon="scissors")
        self.keep_clips = self._option(
            cv, _("Keep forever"),
            _("Otherwise, clips are removed after 7 days without previewing, sending, copying, "
              "renaming or adding them to Sounds."),
            self.mw.cfg.app_clips_keep_forever,
            lambda on: self.mw.set_option("app_clips_keep_forever", on))
        v.addWidget(card)
        v.addStretch(1)
        return w

    def _tab_switched(self, key: str, on: bool):
        """A tab was switched off or on (here, or by importing settings): its box, and
        the other pages' parts that belong to it (built already, they'd still point at
        the tab that was there)."""
        box = getattr(self, "tab_boxes", {}).get(key)
        if box is not None and box.isChecked() != on:
            with QSignalBlocker(box):
                box.setChecked(on)
        if key == "triggers" and hasattr(self, "_watch_refresh"):
            self._watch_refresh()
        if key == "voice" and hasattr(self, "voices_card"):
            self.voices_card.setVisible(on and (self._advanced or not self.voices_card.property(
                "adv_card")))

    def _link_button(self, text: str, url: str, icon: str = "") -> QPushButton:
        btn = WrapButton(text)   # a long translation wraps rather than widen the page
        if icon:
            icons.set_icon(btn, icon)
        btn.clicked.connect(lambda: busy.open_url(
            url, btn, opened=_("✓ Opened in your browser"),
            failed=_("Couldn't open your browser. The page is")))
        return btn

    def _note_card(self):
        card, cv = self._card(_("A note from me"), icon="edit")
        self.alien_note = onionalien.AlienNote(NOTE)
        cv.addWidget(self.alien_note)
        return card

    # ------------------------------------------------------------------ add-ons
    ADDONS_W = 760   # the Add-ons page's cards stop growing here (a wide window
    #                  stretched them into long thin bars with the buttons far apart)

    class _AddonRelay(QObject):
        """A check for a newer add-on, back on the UI thread: (offer, error text)."""
        done = Signal(object, str)

    # the button columns, in order; "get" stands in for "check" while it isn't in
    ADDON_COLUMNS = (("check", "get"), ("report",), ("reinstall",), ("remove",))


    _data_syncing = False

    def _option(self, cv, text: str, hint: str, on: bool, changed, extra=None):
        """A checkbox with a short label and its explanation underneath (a long label
        can't wrap, and would make the whole page wider than the window). `extra` (an
        icon button) sits right after the box's text."""
        box = QCheckBox(text)
        box.setChecked(on)
        box.toggled.connect(changed)
        if extra is None:
            cv.addWidget(box)
        else:
            row = QHBoxLayout()
            row.setSpacing(4)
            row.addWidget(box)
            row.addWidget(extra)
            row.addStretch(1)
            cv.addLayout(row)
        h = QLabel(hint)
        h.setObjectName("hint")
        h.setWordWrap(True)
        h.setContentsMargins(26, 0, 0, 4)   # under the box's text, not its tick
        cv.addWidget(h)
        return box

    # what each switch contacts, and when (soundboard.online.net.FEATURES)
    NET_HINTS = {
        "sounds_web": _("Searches and pasted links on the Sounds tab go to that site, and "
                        "search results show its thumbnails. Off: the search bar only "
                        "searches your own sounds."),
        "sound_packs": _("Free sound packs (Sounds tab → Backup) reads the list of packs "
                         "from GitHub, and downloads one from there when you press Add."),
        "sound_store": _("The Community tab: the project's own store, for its list, the "
                         "sounds and voices you play or add, your votes and what you share."),
        "ytdlp_update": _("Keeps downloading from YouTube and other sites working: checks "
                          "GitHub for a version of yt-dlp the app's makers approved and "
                          "gets it from PyPI when you update it (Updates > Helper "
                          "programs), or by itself if you ticked Update automatically."),
        "radio": _("The station directory (Radio Browser) and the stations you play. Off: "
                   "the Radio tab contacts nobody."),
        "app_update": _("Asks GitHub for the latest release, and downloads its installer "
                        "when you press Update now."),
        "addons": _("Downloads Onion Watch (Triggers tab), its updates, and what an "
                    "add-on needs when you install it (from GitHub and PyPI)."),
        "voices": _("Downloads the extra voices and languages you pick on the Voice tab "
                    "(from Hugging Face and Windows Update). Off: what's already here still "
                    "works."),
        "voice_servers": _("Voices you added that run on another computer over the "
                           "internet. Ones running on this PC always work."),
        "setup_downloads": _("The setup guide's Install button downloads VB-Cable (the "
                             "virtual cable) from vb-audio.com. Not needed if your sounds go "
                             "straight into your mic, to another device or nowhere. Off: "
                             "install it yourself from there."),
        "tor_download": _("Get Tor / Update Tor (Connection page) downloads Tor from the "
                          "Tor Project (dist.torproject.org). Off: a Tor that's already "
                          "here still works."),
        "ffmpeg_download": _("Get FFmpeg (Data & quality) installs FFmpeg, the free tool "
                             "that plays M4A, AAC and video files (through Microsoft's "
                             "winget). Off: install it yourself from ffmpeg.org."),
        "usage_stats": _("Anonymous usage stats once a day, to see what to improve. "
                         "Never your name, IP address or device info."),
        "twitch": _("Only once you click Connect Twitch (Settings > Remote): channel points, "
                    "alerts and chat commands from your channel. Off: never contacts Twitch."),
    }

    # ---- Offline mode: what only works online is hidden, not left greyed out
    OFFLINE_PAGES = ("data", "updates")   # whole pages about downloads and updates

    @classmethod
    def _offline_pages(cls) -> tuple[str, ...]:
        from soundboard.online import net
        return cls.OFFLINE_PAGES if net.offline() else ()

    def done(self, r):
        # unhooking a slot that was never hooked (Updates card not built, or done()
        # twice) only prints PySide's "Failed to disconnect" RuntimeWarning
        if getattr(self, "_upd_wired", False):
            self._upd_wired = False
            for sig, slot in ((self.mw.update_done, self.connection._updates_done),
                              (self.mw.update_state, self.connection._updates_state)):
                try:
                    sig.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
        # hiding it hands the focus on as if Tab were pressed (a keyboard ring on the
        # Sounds rail tab): the window takes it back, but only knows to if told here
        fw = QApplication.focusWidget()
        self.had_focus = fw is not None and self.isAncestorOf(fw)
        super().done(r)


    POCKET_CHECK_S = 3600   # how often Settings → Remote asks GitHub for a newer one


