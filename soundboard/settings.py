"""Settings window: themes, every global hotkey in one place, the in-game overlay,
general options."""
from __future__ import annotations

import html
import logging
import math
import re
import threading
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QPoint, QPointF, QSignalBlocker, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QImage, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractButton, QApplication, QCheckBox, QComboBox, QDialog, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QScrollArea, QStyle,
                               QStyleOptionButton, QTabWidget, QVBoxLayout, QWidget)

from shiboken6 import isValid as qt_valid

from soundboard.ui import busy, icons
from soundboard.wheelguard import no_wheel
from soundboard import errors, usage
from soundboard.i18n import _
from soundboard.ui.settingspages import Built, _button_row
from soundboard.ui.settingspages.help import HelpPage
from soundboard.ui.settingspages.audio import AudioPage
from soundboard.ui.settingspages.appearance import AppearancePage, ThemeCard, ThemeGrid as ThemeGrid
from soundboard.ui.settingspages.keys import (KeysPage, HOTKEY_ACTIONS as HOTKEY_ACTIONS,
                                              HotkeyDialog as HotkeyDialog,
                                              pretty_key as pretty_key)
from soundboard.ui.settingspages.general import GeneralPage
from soundboard.ui.settingspages.connection import ConnectionPage
from soundboard.ui.settingspages.privacy import PrivacyPage

log = logging.getLogger(__name__)


# Settings > About. The note is the author's own words, kept casual on purpose.
NOTE = _("Hey, thanks for actually using this. Onion Board started because every soundboard "
          "I tried was either ugly, full of ads, or quietly phoning home, so I made my own "
          "and it kind of snowballed from there. It's just me building it, a lot of late "
          "nights and a lot of testing, so if something's broken, ugly or confusing, tell "
          "me. Honestly. I'd way rather hear \"this part is cooked\" than have you quietly "
          "uninstall it.\n\nIt's free and it's staying free. Have fun with it, don't be a "
          "menace with it, and go make your friends jump in voice chat.\n\nOnionAlien")


class _AddonGrid(QWidget):
    """Settings → Add-ons: each add-on's name, status line and buttons, the buttons in
    shared columns so they line up from one add-on to the next. As many columns as
    fit (4, else 2, else 1): it never makes the page wider than its window."""
    GAP = 8

    def __init__(self, cols: int):
        super().__init__()
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(self.GAP)
        self.grid.setVerticalSpacing(6)
        self.max_cols = self.cols = cols
        self.rows: list[tuple[QLabel, QLabel, list[list[QPushButton]]]] = []

    def add(self, title: QLabel, status: QLabel, cells: list[list[QPushButton]]):
        for cell in cells:
            for b in cell:
                b.setMinimumWidth(40)    # the columns decide; resizeEvent keeps it readable
        self.rows.append((title, status, cells))
        self._place()

    def _need(self, cols: int) -> int:
        w = max((b.sizeHint().width() for _t, _s, cells in self.rows
                 for cell in cells for b in cell), default=0)
        return cols * w + (cols - 1) * self.GAP

    def _place(self):
        g, cols = self.grid, self.cols
        from soundboard.ui.widgets import take_out   # (it imports this module)
        while g.count():
            take_out(g)
        for r in range(g.rowCount()):
            g.setRowMinimumHeight(r, 0)
        r = 0
        for i, (title, status, cells) in enumerate(self.rows):
            if i:
                g.setRowMinimumHeight(r, 6)      # a gap between add-ons
                r += 1
            g.addWidget(title, r, 0, 1, cols)
            g.addWidget(status, r + 1, 0, 1, cols)
            r += 2
            for n, cell in enumerate(cells):
                for b in cell:
                    g.addWidget(b, r + n // cols, n % cols)
            r += (len(cells) + cols - 1) // cols
        for c in range(self.max_cols):
            g.setColumnStretch(c, 1 if c < cols else 0)

    def resizeEvent(self, e):
        cols = self.max_cols
        while cols > 1 and self._need(cols) > e.size().width():
            cols //= 2
        if cols != self.cols:
            self.cols = cols
            self._place()
        super().resizeEvent(e)


def _ink_rows(img: QImage) -> float:
    """The middle of an image's ink between its top and bottom edge, in device px from
    its top: a blurred end row counts by how much of a typical inked row it covers."""
    img = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    line, data = img.bytesPerLine(), bytes(img.constBits())
    ink = [sum(data[y * line + 3:y * line + img.width() * 4:4]) for y in range(img.height())]
    rows = [y for y, a in enumerate(ink) if a]
    if not rows:
        return img.height() / 2
    typical = sorted(ink[y] for y in rows)[len(rows) // 2]
    first, last = rows[0], rows[-1]
    return (first + 1 - min(1.0, ink[first] / typical) + last + min(1.0, ink[last] / typical)) / 2


_DRAWN: dict[tuple, tuple[QPixmap, float]] = {}   # (_draw_icon)


def _draw_icon(p: QPainter, w: QWidget, name: str, color: str, side: int, x: float,
               mid: float):
    """Icon `name` drawn `side` px at `x` with its ink's middle (not its box's: an
    icon's drawing isn't always in the middle of its picture) on `mid`, in `w`, to a
    fraction of a screen pixel: a picture lands on whole ones, 0.4 px off at 125%."""
    k = w.devicePixelRatioF()
    px = max(1, round(side * k))
    wy = w.mapTo(w.window(), QPoint(0, 0)).y()
    plain = _DRAWN.get((name, px))
    if plain is None:
        pm = icons.pixmap(name, px, "#000000")
        plain = _DRAWN[(name, px)] = (pm, _ink_rows(pm.toImage()))
    at = (wy + mid) * k - plain[1]   # the picture's top, in screen px
    whole = math.floor(at)
    frac = round((at - whole) * 8) / 8
    key = (name, px, icons.resolve(color), frac)
    drawn = _DRAWN.get(key)
    if drawn is None:
        if len(_DRAWN) > 64:
            _DRAWN.clear()
        pm = icons.pixmap(name, px, key[2], frac)
        pm.setDevicePixelRatio(k)
        drawn = _DRAWN[key] = (pm, 0.0)
    p.drawPixmap(QPointF(x, whole / k - wy), drawn[0])


class _Mark(QWidget):
    """The heading's cog, drawn `dy` px below its box's middle (_draw_icon): a label's
    picture moves in whole px, 1.25 screen px at 125%."""

    dy = 0.0

    def __init__(self, name: str, color: str, side: int):
        super().__init__()
        self.name, self.color, self.side = name, color, side
        self.setFixedWidth(side)

    def sizeHint(self):
        return QSize(self.side, self.side)

    def paintEvent(self, e):
        p = QPainter(self)
        _draw_icon(p, self, self.name, self.color, self.side, 0,
                   self.height() / 2 + self.dy)
        p.end()


class _BackArrow(QPushButton):
    """The heading's back arrow, drawn `dy` px below the button's middle to the screen
    pixel (as _Mark): its button, hover and focus look as any quiet one's."""

    dy = 0.0
    BACK_LEFT = 3   # (the padding's left: SettingsDialog.BACK_PAD)

    def paintEvent(self, e):
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        opt.icon = QIcon()
        p = QPainter(self)
        self.style().drawControl(QStyle.ControlElement.CE_PushButton, opt, p, self)
        side, left = self.iconSize().height(), self.BACK_LEFT
        _draw_icon(p, self, "back", "text" if self.isEnabled() else "muted", side,
                   left + (self.width() - left - side) / 2, self.height() / 2 + self.dy)
        p.end()


class SettingsDialog(QDialog, Built):
    """All settings in one place. `mw` is the MainWindow; changes apply immediately."""

    # narrower than this, the categories are icons only and the search box goes over
    # the page (the list and box took 212 px of a 440 px window)
    NARROW_W = 640
    TITLE_COG = 18   # the heading's cog, px
    PAGE_TOP = 18    # the pages start this far down: where a tab's do (its 10 + 8)
    BACK_PAD = "padding:7px 0px 7px 3px"   # (the arrow is moved by _level_icons)

    def __init__(self, mw, page: str = "privacy", lazy: bool = False):
        """A page in the main window, in place of the tabs (SettingsControl.open_settings),
        never a window of its own. `lazy`: build only `page` now and each other page
        the first time it's shown. Building all twelve under the app's style sheet took
        a second or two on every click of the cog; the tests build them all at once."""
        super().__init__(mw)
        # The pages (soundboard/ui/settingspages), before anything builds one.
        self.help = HelpPage(self)
        self.audio = AudioPage(self)
        self.appearance = AppearancePage(self)
        self.keys = KeysPage(self)
        self.general = GeneralPage(self)
        self.connection = ConnectionPage(self)
        self.privacy = PrivacyPage(self)
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
        pages = (("privacy", _("Privacy && security"), "shield", self.privacy._privacy),
                 ("connection", _("Connection"), "radio", self.connection._connection),
                 ("data", _("Data && quality"), "wave", self.privacy._data),
                 ("general", _("General"), "settings", self.general._general),
                 ("tabs", _("Tabs"), "sounds", self._tabs),
                 ("appearance", _("Appearance"), "palette", self.appearance._appearance),
                 ("audio", _("Audio"), "volume", self.audio._audio),
                 ("hotkeys", _("Hotkeys"), "keyboard", self.keys._hotkeys),
                 ("overlay", _("Overlay"), "gamepad", self.keys._overlay),
                 ("updates", _("Updates"), "reload", self.connection._updates),
                 ("help", _("Add-ons"), "plus", self.help._help),
                 ("remote", _("Remote"), "cable", self._remote),
                 ("about", _("About"), "star", self.help._about))
        self.categories = QListWidget()
        self.categories.setObjectName("settingscategories")
        self.categories.setAccessibleName(_("Settings categories"))
        self.categories.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.categories.setFixedWidth(196)
        self._unbuilt: dict[int, Callable[[], QWidget]] = {}   # tab index -> its page's builder
        for i, (key, title, icon, build) in enumerate(pages):
            sa = self._scroll()
            if lazy and key != page:
                self._unbuilt[i] = build
            else:
                self._fill(sa, build())
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
        self.categories.currentRowChanged.connect(self.tabs.setCurrentIndex)
        self.tabs.currentChanged.connect(self._build_page)
        self.tabs.currentChanged.connect(self.categories.setCurrentRow)
        self._page_keys = [p[0] for p in pages]
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

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_width(self.width())
        QTimer.singleShot(0, self._level_with_rail)   # once the rows have their places

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self._level_with_rail)

    def _caps_mid(self, label: QLabel, dy: int = 0) -> float:
        """The middle of a one-line label's capitals in the window, in screen pixels
        (what the eye lines up: not the box, not the descenders), were it `dy` px lower.
        Measured on an "H" drawn the way the label draws its text, on the same part of a
        pixel: where Qt and the font's hinting put a line can't be worked out from the
        font's numbers (Consolas and Tahoma at 125% drew theirs up to 2 px off them)."""
        k = label.devicePixelRatioF()
        at = (label.mapTo(self.window(), QPoint(0, 0)).y() + dy) * k
        whole = math.floor(at)
        rect = label.contentsRect()
        key = (label.font().key(), rect.getRect(), int(label.alignment()), k, at - whole)
        mid = self._caps_cache.get(key)
        if mid is None:   # (not an alpha-only image: Windows drew its text 4 px off)
            img = QImage(max(1, math.ceil(label.width() * k)),
                         math.ceil(label.height() * k) + 2,
                         QImage.Format.Format_ARGB32_Premultiplied)
            img.setDevicePixelRatio(k)
            img.fill(0)
            p = QPainter(img)
            p.translate(0, (at - whole) / k)
            p.setFont(label.font())
            p.setPen(Qt.GlobalColor.black)
            p.drawText(rect, int(label.alignment()), "H")
            p.end()
            mid = _ink_rows(img)   # (the H's top and bottom edge)
            self._caps_cache[key] = mid
        return whole + mid

    def _level_with_rail(self):
        """The heading row moves down until the middle of "Settings"' capitals is level
        with the rail's "Onion Board" (the arrow and cog are centred on it); with the
        name hidden (the rail shut) or a bar above the pages, it sits where the pages
        start."""
        if not qt_valid(self) or self.back_btn is None:
            return
        lay = self.layout()
        if lay is not None:
            lay.activate()   # (a lift just set: measured where it put the row)
        side = self._side.contentsMargins()
        lift = self.PAGE_TOP
        wm = getattr(self.mw, "wordmark", None)
        if wm is not None and qt_valid(wm) and wm.isVisible():
            want = self._caps_mid(wm)
            titled = self.page_title.isVisible()
            k = self.back_btn.devicePixelRatioF()
            at = self.back_btn.mapTo(self.window(), QPoint(0, 0)).y()

            def off(dy):   # how far off the name, in screen pixels, dy px lower
                if titled:
                    return abs(self._caps_mid(self.page_title, dy) - want)
                return abs((at + dy + self.back_btn.height() / 2) * k - want)   # (narrow)
            # the whole-pixel lifts either side of the exact one: the nearer on screen
            near = (want - self._caps_mid(self.page_title)) / self.devicePixelRatioF()
            dy = min(range(math.floor(near) - 1, math.ceil(near) + 2), key=off)
            lift = max(0, min(self.PAGE_TOP, side.top() + dy))
        if lift != side.top():
            self._side.setContentsMargins(side.left(), lift, side.right(), side.bottom())
            if lay is not None:
                lay.activate()
        self._level_icons()

    def _level_icons(self):
        """The arrow and cog centred on the middle of "Settings"' capitals as drawn,
        wherever the theme's font puts them (_caps_mid): Consolas and Tahoma draw theirs
        lower in the line than Bahnschrift, Comic Sans higher."""
        title = self.page_title
        if not title.isVisible():   # (narrow: the arrow on its own, in its middle)
            if self.back_btn.dy:
                self.back_btn.dy = 0.0
                self.back_btn.update()
            return
        caps = (self._caps_mid(title) / title.devicePixelRatioF()
                - self.mapTo(self.window(), QPoint(0, 0)).y())
        # both to the screen pixel (_BackArrow, _Mark)
        for w in (self.back_btn, self.title_cog):
            dy = caps - w.mapTo(self, QPoint(0, 0)).y() - w.height() / 2
            if abs(dy - w.dy) > 0.01:
                w.dy = dy
                w.update()

    def _fit_width(self, width: int):
        """Narrow: the categories as an icon column (the name is the tip) and the
        search box over the page, so a 440 px window has room for the page itself."""
        narrow = width < self.NARROW_W
        if narrow == self._narrow:
            return
        self._narrow = narrow
        box = self.search_box
        (self._side if narrow else self._right).removeWidget(box)
        if narrow:
            self._right.insertWidget(0, box)
            box.setMinimumWidth(0)
            box.setMaximumWidth(16777215)
        else:
            self._side.insertWidget(1 if self.back_btn is not None else 0, box)
            box.setFixedWidth(196)
        if self.back_btn is not None:
            self.page_title.setVisible(not narrow)
            self.title_cog.setVisible(not narrow)
        self._content.setSpacing(8 if narrow else 16)
        for i in range(self.categories.count()):
            item = self.categories.item(i)
            title = item.data(Qt.ItemDataRole.UserRole + 1)
            item.setText("" if narrow else title)
            item.setToolTip(title if narrow else "")
            item.setSizeHint(QSize(40 if narrow else 180, 38))
        self.categories.setFixedWidth(48 if narrow else 196)

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
        i = keys.index(page) if page in keys else 0
        self.categories.setCurrentRow(i)
        self.tabs.setCurrentIndex(i)
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
                for i in list(self._unbuilt):   # a page not built yet can't be searched
                    self._build_page(i)
            finally:
                self._searching = False
        first = named = None
        for i in range(self.tabs.count()):
            title = self.categories.item(i).data(Qt.ItemDataRole.UserRole + 1).lower()
            if self._page_keys[i] in self._offline_pages():   # hidden in Offline mode
                self.categories.item(i).setHidden(True)
                continue
            if i in self._unbuilt:   # (only with no words: spaces, or cleared first)
                self.categories.item(i).setHidden(False)
                continue
            page = self._tab_page(i)
            hits = 0
            for card in page.findChildren(QFrame, "setcard"):
                if card.property("offline_hid"):   # (_offline_hide) as if it weren't there
                    continue
                match = not words or all(w in title or w in self._words_of(card) for w in words)
                if not match and not card.isHidden():
                    card.hide()
                    card.setProperty("search_hid", True)
                elif match and card.property("search_hid"):
                    card.show()
                    card.setProperty("search_hid", False)
                hits += match
            self.categories.item(i).setHidden(bool(words) and not hits)
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
        on_hidden = self.categories.item(self.tabs.currentIndex()).isHidden()
        if named is not None:
            self.tabs.setCurrentIndex(named)
        elif words and first is not None and on_hidden:
            self.tabs.setCurrentIndex(first)

    def _category_icons(self):
        for i in range(self.categories.count()):
            item = self.categories.item(i)
            name = item.data(Qt.ItemDataRole.UserRole)
            item.setIcon(icons.icon(name, selected="text_hi"))
        if getattr(self, "title_cog", None) is not None:
            self._title_cog()
            QTimer.singleShot(0, self._level_with_rail)   # (a new theme: maybe a new font)

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
        """A lazy page, the first time it's shown."""
        build = self._unbuilt.pop(i, None)
        if build is not None:
            self._fill(self._tab_area(i), build())

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
    def _card(title: str, hint: str = ""):
        card = QFrame()
        card.setObjectName("setcard")
        v = QVBoxLayout(card)
        v.setContentsMargins(14, 12, 14, 14)
        v.setSpacing(8)
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
    }

    def _tabs(self):
        w, v = self._page()
        card, cv = self._card(
            _("Tabs"),
            _("Switch off the tabs you don't use. A switched-off tab is gone from the window and "
              "doesn't load at all, so nothing of it runs in the background. Switch it back on "
              "any time, here or with + More tabs after the tabs. Right-click a tab to hide it."))
        from soundboard.ui.tabcontrol import TAB_KEYS, TABS
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
        card, cv = self._card(_("Saved clips"))
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
            self.voices_card.setVisible(on)

    def _remote(self):
        w, v = self._page()
        v.addWidget(self._remote_card())
        for card in self._remote_addon_cards():
            v.addWidget(card)
        v.addWidget(self._remote_easy_card())
        v.addStretch(1)
        return w

    def _link_button(self, text: str, url: str, icon: str = "") -> QPushButton:
        btn = QPushButton(text)
        if icon:
            icons.set_icon(btn, icon)
        btn.clicked.connect(lambda: busy.open_url(
            url, btn, opened=_("✓ Opened in your browser"),
            failed=_("Couldn't open your browser. The page is")))
        return btn

    def _note_card(self):
        card, cv = self._card(_("A note from me"))
        note = QLabel(NOTE)
        note.setWordWrap(True)
        cv.addWidget(note)
        return card

    # ------------------------------------------------------------------ add-ons
    ADDONS_W = 760   # the Add-ons page's cards stop growing here (a wide window
    #                  stretched them into long thin bars with the buttons far apart)

    class _AddonRelay(QObject):
        """A check for a newer add-on, back on the UI thread: (offer, error text)."""
        done = Signal(object, str)

    def _addons_card(self):
        """Every add-on in one place, each with the same row of buttons in the same
        order: Check for updates (Update to X once one is out), Reinstall (a fresh
        copy of the newest; the user's triggers / paired phones are the board's and
        stay), Report a problem, Remove. Not installed: Get it, and Report a problem.
        One grid for all of them (_AddonGrid): the buttons share columns, so they line
        up from one add-on to the next, folding to two columns in a narrow window."""
        card, cv = self._card(_("Add-ons"),
                              _("Free add-ons from GitHub. Removing or reinstalling one keeps "
                                "your triggers and paired phones."))
        grid = _AddonGrid(len(self.ADDON_COLUMNS))
        cv.addWidget(grid)      # in the card first: a button shown without a parent
        self._watch_block(grid)  # is a window of its own
        self._pocket_block(grid)
        self._addons_card_w = card
        self._watch_refresh()   # (_addon_offline: the card, now it's known)
        return card

    # the button columns, in order; "get" stands in for "check" while it isn't in
    ADDON_COLUMNS = (("check", "get"), ("report",), ("reinstall",), ("remove",))

    def _addon_block(self, grid, name: str, blurb: str):
        """An add-on's name and what it's for, a status line, and its buttons, as rows
        of the Add-ons grid. (status label, {key: button})."""
        title = QLabel(f"<b>{html.escape(name)}</b> · {html.escape(blurb)}")
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setWordWrap(True)
        status = QLabel()
        status.setObjectName("hint")
        status.setWordWrap(True)
        btns = {}
        for key, text, icon in (("get", _("Get {name}", name=name), ""),
                                ("check", _("Check for updates"), "reload"),
                                ("reinstall", _("Reinstall"), ""),
                                ("report", _("Report a problem"), ""),
                                ("remove", _("Remove"), "trash")):
            b = QPushButton(text)
            if icon:
                icons.set_icon(b, icon, "danger_text" if key == "remove" else None)
            btns[key] = b
        btns["get"].setObjectName("primary")
        btns["reinstall"].setToolTip(_("Downloads the newest {name} again and puts it in place "
                                       "of this one. Your own things are kept.", name=name))
        btns["report"].setToolTip(_("Opens a bug report on GitHub in your browser, with the "
                                    "versions filled in"))
        grid.add(title, status, [[btns[k] for k in keys] for keys in self.ADDON_COLUMNS])
        if not hasattr(self, "_addon_titles"):
            self._addon_titles = {}
        self._addon_titles[status] = title
        return status, btns

    def _addon_offline(self, status, b, have: bool, can_get: bool):
        """Offline mode on an add-on's row (after its refresh): Check for updates and
        Reinstall go; not installed, with nothing on this PC to install it from, the
        whole row goes. The Add-ons card goes when no row is left."""
        from soundboard import net
        if not net.offline():
            row = True
        else:
            row = have or can_get
            for k in ("check", "reinstall"):
                b[k].hide()
            if not row:
                for btn in b.values():
                    btn.hide()
        b["report"].setVisible(row)
        title = self._addon_titles.get(status)
        for w in (title, status):
            if w is not None:
                w.setVisible(row)
        card = getattr(self, "_addons_card_w", None)
        if card is not None and qt_valid(card):
            self.privacy._offline_card(card, lambda: not any(
                s.isVisibleTo(card) for s in self._addon_titles if qt_valid(s)))

    def _addon_report(self, btn, what: str):
        from soundboard import __version__, feedback
        busy.open_url(feedback.problem_url(__version__, what), btn,
                      opened=_("✓ Opened in your browser"),
                      failed=_("Couldn't open your browser. The page is"))

    def _addon_check(self, btn, feature: str, latest, newer_than: str, on_offer):
        """Check for updates: asks GitHub on a thread (`latest()` -> offer or None);
        a newer one calls `on_offer(offer)`, else the button says it's up to date."""
        from soundboard import net, netlog, updates
        if not net.allowed(feature):
            busy.toast(self, html.escape(_("Add-on downloads are off (Privacy)")), "warn")
            return
        release = busy.hold(btn, _("Checking…"))
        relay = self._AddonRelay(self)
        netlog.cause(feature, "You clicked Check for updates (Settings > Add-ons)")

        def done(offer, error):
            relay.deleteLater()
            if not qt_valid(btn):
                return
            if error:
                release(_("Couldn't check"))
                busy.toast(self, html.escape(error), "warn")
            elif offer is not None and updates.newer(offer.version, newer_than):
                release()
                on_offer(offer)
            else:
                release(_("✓ Up to date"))

        def ask():
            try:
                offer, error = latest(), ""
            except Exception as e:  # noqa: BLE001 - offline, rate-limited, switched off…
                offer, error = None, _("Couldn't reach GitHub ({error}).",
                                       error=errors.plain(e))
            try:
                relay.done.emit(offer, error)
            except RuntimeError:        # Settings was closed meanwhile
                pass
        relay.done.connect(done)
        threading.Thread(target=ask, daemon=True, name="addon-check").start()

    # ---- Onion Watch (the Triggers tab's add-on, soundboard.watchaddon)
    def _watch_block(self, grid):
        from soundboard import watchaddon
        status, b = self._addon_block(grid, "Onion Watch", _("the Triggers tab"))
        self.addon_label, self.addon_remove = status, b["remove"]
        self.watch_buttons = b
        state = {}

        def tab():
            """The Triggers tab there now: switched off and on again (Settings > Tabs)
            while this is open, it's a new one; switched off, None (nothing of it is
            loaded)."""
            return self.mw.triggers if self.mw.tabctl.tab_on("triggers") else None

        def refresh(note: str = ""):
            if not qt_valid(status):
                return
            t = tab()
            if t is None:
                status.setText(_("The Triggers tab is switched off (Settings > Tabs)."))
                for btn in b.values():
                    btn.hide()
                return
            b["report"].setVisible(True)   # back on (Settings > Tabs)
            info = t.info
            have = info is not None and watchaddon.removable(info, t._base())
            status.setText(note or (_("Version {version} is installed.", version=info.version)
                                    if have and info is not None
                                    else _("Onion Watch isn't installed.")))
            b["get"].setVisible(not have)
            for k in ("check", "reinstall", "remove"):
                b[k].setVisible(have)
            if not have:
                state.pop("offer", None)
            self._label_update(b["check"], state.get("offer"))
            self._addon_offline(status, b, have, watchaddon.local_zip() is not None)

        def run_get(offer, btn, text):
            """tab.get() does the work (and shows it on the Triggers tab too)."""
            t = tab()
            if t is None:
                return
            if t._busy:
                busy.flash(btn, _("Already downloading"))
                return
            t.offer = offer
            release = busy.hold(btn, text)

            def finished(info, error, _update):
                t._finished.disconnect(finished)
                if not qt_valid(btn):
                    return
                release(_("✗ Didn't work") if error else _("✓ Done"))
                state.pop("offer", None)
                refresh(_("Onion Watch wasn't installed: {error}", error=errors.plain(error))
                        if error else
                        (_("Version {version} is in. Restart Onion Board to start using it.",
                           version=info.version) if _update else ""))
                QTimer.singleShot(0, lambda: refresh() if not error and not _update
                                  else None)
            t._finished.connect(finished)
            t.get()

        def check():
            if state.get("offer") is not None:      # "Update to X"
                run_get(state["offer"], b["check"], _("Updating…"))
                return
            t = tab()
            if t is None:
                return
            info = t.info

            def found(offer):
                state["offer"] = offer
                t = tab()
                if t is not None:
                    t.offer_update(offer)
                refresh()
            self._addon_check(b["check"], watchaddon.FEATURE, watchaddon.latest,
                              info.version if info else "0", found)

        def remove():
            t = tab()
            if t is not None:
                t.remove()              # asks first
            refresh()

        b["get"].clicked.connect(lambda: run_get(None, b["get"], _("Getting it…")))
        b["check"].clicked.connect(check)
        b["reinstall"].clicked.connect(lambda: run_get(None, b["reinstall"],
                                                       _("Reinstalling…")))
        def report():
            t = tab()
            info = t.info if t is not None else None
            self._addon_report(b["report"],
                               f"Onion Watch {info.version}" if info else "Onion Watch")
        b["report"].clicked.connect(report)
        b["remove"].clicked.connect(remove)
        self._watch_refresh = refresh   # the Tabs page switched Triggers off or on
        refresh()   # in the card first: shown without a parent, it's a window of its own

    @staticmethod
    def _label_update(btn, offer):
        """Check for updates, or *Update to X* (primary) once a newer one is found."""
        text = _("Update to {version}",
                 version=offer.version) if offer is not None else _("Check for updates")
        if btn.text() != text and not busy.is_busy(btn):
            btn.setText(text)
            btn.setObjectName("primary" if offer is not None else "")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    # ---- Onion Pocket (the phone remote, soundboard.pocketaddon)
    def _pocket_block(self, grid):
        from soundboard import pocketaddon, updates
        status, b = self._addon_block(grid, "Onion Pocket", _("your pads on your phone"))
        self.pocket_remove_addons = b["remove"]
        self.pocket_buttons = b
        state = {}

        def refresh(note: str = ""):
            if not qt_valid(status):
                return
            info = self._pocket_info()
            have = info is not None and pocketaddon.removable(info)
            if info is not None and info.error and have:
                note = note or _("Version {version} is installed but didn't start: "
                                 "{error}. Reinstall it, or report the problem.",
                                 version=info.version, error=info.error)
            status.setText(note or (_("Version {version} is installed. Its settings are on "
                                      "the Remote page.", version=info.version)
                                    if have and info is not None else
                                    _("Onion Pocket isn't installed.")))
            b["get"].setVisible(not have and pocketaddon.offered())
            for k in ("check", "reinstall", "remove"):
                b[k].setVisible(have)
            offer = state.get("offer")
            if not have or (offer is not None and info is not None
                            and not updates.newer(offer.version, info.version)):
                state.pop("offer", None)
            self._label_update(b["check"], state.get("offer"))
            self._addon_offline(status, b, have, pocketaddon.local_zip() is not None)

        def check():
            if state.get("offer") is not None:      # "Update to X"
                self._pocket_install(b["check"], state["offer"], _("Updating…"))
                return
            info = self._pocket_info()

            def found(offer):
                state["offer"] = offer
                self.mw.pocket_offer = offer
                refresh()
            self._addon_check(b["check"], pocketaddon.FEATURE, pocketaddon.latest,
                              info.version if info else "0", found)

        b["get"].clicked.connect(lambda: self._pocket_install(b["get"], None,
                                                              _("Getting it…")))
        b["check"].clicked.connect(check)
        b["reinstall"].clicked.connect(lambda: self._pocket_install(b["reinstall"], None,
                                                                    _("Reinstalling…")))
        b["report"].clicked.connect(lambda: self._addon_report(
            b["report"], f"Onion Pocket {i.version}" if (i := self._pocket_info())
            else "Onion Pocket"))
        b["remove"].clicked.connect(lambda: self._remove_pocket(b["remove"]))
        self._pocket_refresh = refresh
        refresh()

    def _pocket_install(self, btn, offer, text: str):
        """Get / reinstall / update Onion Pocket from the Add-ons card: downloads it
        (pocketaddon.get), the main window swaps it in for any running copy (paired
        phones stay), and its card on Settings → Remote is replaced by the new one's."""
        from soundboard import netlog, pocketaddon

        class Relay(QObject):
            done = Signal(object)

        release = busy.hold(btn, text)
        netlog.cause(pocketaddon.FEATURE, "You clicked to get Onion Pocket "
                                          "(Settings > Add-ons)")
        relay = Relay(self.mw)   # the main window's: it's loaded even if Settings closes

        def finish(new):
            relay.deleteLater()
            addon = self.mw.remctl.load_remote_addon(new) if new is not None else None
            if new is not None:
                self.mw.pocket_offer = None
            if not qt_valid(btn):
                return
            if addon is None:
                release(_("✗ Didn't work"))
                busy.toast(self, _("Couldn't get Onion Pocket right now. Check your "
                                   "internet connection and try again."), "warn")
                self._pocket_changed()
                return
            release(_("✓ Done"))
            assert new is not None   # (addon is None without it)
            if getattr(self, "_pocket_slot", None) is not None:
                fresh = self._addon_card(new, addon)
                if fresh is not None:
                    self._pocket_remove_button(fresh, new)
                self._swap_pocket_slot(fresh)
            self._pocket_changed()
            busy.toast(self, _("✓ Onion Pocket {version} is in.",
                               version=html.escape(new.version)), "ok")

        relay.done.connect(finish)
        threading.Thread(target=lambda: relay.done.emit(pocketaddon.get(offer=offer)),
                         daemon=True, name="onion-pocket-addons").start()


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

    # what each switch contacts, and when (soundboard.net.FEATURES)
    NET_HINTS = {
        "sounds_web": _("Searches and pasted links on the Sounds tab go to that site, and "
                        "search results show its thumbnails. Off: the search bar only "
                        "searches your own sounds."),
        "sound_packs": _("Free sound packs (Sounds tab → Backup) reads the list of packs "
                         "from GitHub, and downloads one from there when you press Add."),
        "ytdlp_update": _("Fetches a newer yt-dlp from PyPI when you press Update now or "
                          "Reset downloader (Updates page), or by itself if you ticked "
                          "Update automatically there."),
        "radio": _("The station directory (Radio Browser) and the stations you play. Off: "
                   "the Radio tab contacts nobody."),
        "app_update": _("Asks GitHub for the latest release, and downloads its installer "
                        "when you press Update now."),
        "addons": _("GitHub, for Onion Watch (Triggers tab) and its updates, and the "
                    "packages an add-on's Install step downloads (pip)."),
        "voices": _("Translation models (Voice tab), live voice's speech model (Hugging "
                    "Face) and Windows' own voices (Windows Update). Off: live voice still "
                    "works with a model it already has."),
        "voice_servers": _("Voices in your voices folder that are a server on the "
                           "internet. Ones on this PC (127.0.0.1) always work."),
        "setup_downloads": _("The setup guide's Install button downloads VB-Cable (the "
                             "virtual cable) from vb-audio.com. Not needed if your sounds go "
                             "straight into your mic, to another device or nowhere. Off: "
                             "install it yourself from there."),
        "tor_download": _("Get Tor / Update Tor (Connection page) downloads Tor from the "
                          "Tor Project (dist.torproject.org). Off: a Tor that's already "
                          "here still works."),
        "ffmpeg_download": _("Get FFmpeg (Data & quality) installs FFmpeg with winget, "
                             "Microsoft's package manager, so M4A, AAC and video files "
                             "play and can be added. Off: install FFmpeg yourself from "
                             "ffmpeg.org."),
        "usage_stats": _("Anonymous usage stats once a day, to see what to improve. "
                         "Never your name, IP address or device info."),
    }

    # ---- Offline mode: what only works online is hidden, not left greyed out
    OFFLINE_PAGES = ("data", "updates")   # whole pages about downloads and updates

    @classmethod
    def _offline_pages(cls) -> tuple[str, ...]:
        from soundboard import net
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

    # ------------------------------------------------------------------ remote control
    def _remote_card(self):
        """The local control API (soundboard.remote): on / off, port, key."""
        from PySide6.QtWidgets import QApplication, QLineEdit, QSpinBox

        from soundboard import remote
        mw, cfg = self.mw, self.mw.cfg
        card, cv = self._card(_("Remote control (Stream Deck, scripts)"),
                              _("Lets programs on this PC play your sounds: a Stream Deck (its "
                                "API-request or website buttons, Bitfocus Companion, Touch "
                                "Portal), AutoHotkey or a script. Only this PC can connect, and "
                                "only with the key below, treat it like a password."))
        on = QCheckBox(_("Enable remote control"))
        on.setChecked(cfg.api_enabled)
        cv.addWidget(on)
        row = QGridLayout()
        row.addWidget(QLabel(_("Port")), 0, 0)
        port = QSpinBox()
        port.setRange(1024, 65535)
        port.setValue(cfg.api_port)
        port.setAccessibleName(_("Port"))
        no_wheel(port)
        row.addWidget(port, 0, 1)
        row.addWidget(QLabel(_("Key")), 1, 0)
        key = QLineEdit()
        key.setReadOnly(True)
        key.setEchoMode(QLineEdit.EchoMode.Password)
        key.setAccessibleName(_("Key"))
        row.addWidget(key, 1, 1)
        show = QPushButton(_("Show"))
        show.setCheckable(True)

        def show_key(b: bool):
            key.setEchoMode(QLineEdit.EchoMode.Normal if b else QLineEdit.EchoMode.Password)
            show.setText(_("Hide") if b else _("Show"))

        show.toggled.connect(show_key)
        row.addWidget(show, 1, 2)
        new = QPushButton(_("New key"))
        new.setToolTip(_("Make a new key: anything using the old one stops working"))
        row.addWidget(new, 1, 3)
        cv.addLayout(row)
        crow = QHBoxLayout()
        copy = QPushButton(_("Copy an example link"))
        copy.setToolTip(_("A link that plays a random sound, paste it into a Stream Deck "
                          "website / API-request button, or open it to try it"))
        crow.addWidget(copy)
        state = QLabel()
        state.setObjectName("hint")
        state.setWordWrap(True)
        crow.addWidget(state, 1)
        cv.addLayout(crow)
        help_ = QLabel(_("Endpoints: {endpoints}. E.g. /api/play?name=Airhorn, "
                         "/api/random?category=Memes, /api/live?on=toggle. Send the key as "
                         "?token=…, an X-Token header or Authorization: Bearer …. /api/help "
                         "describes each one.",
                         endpoints=" · ".join(f"/api/{a}" for a in remote.ENDPOINTS)))
        help_.setObjectName("hint")
        help_.setWordWrap(True)
        help_.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cv.addWidget(help_)

        def refresh(err: str = ""):
            key.setText(cfg.api_token)
            if not cfg.api_enabled:
                show.setChecked(False)   # turning it off hides the key again
            for w in (port, key, show, new, copy):
                w.setEnabled(cfg.api_enabled)
            if not cfg.api_enabled:
                state.setText(_("Off."))
            elif err or not mw.remote.running:
                state.setText(_("Couldn't start: {error}", error=err or mw.remote.error))
            else:
                state.setText(_("On: listening on {host}:{port}.",
                                host=remote.HOST, port=mw.remote.port))

        # saved on the saver's thread (mw._save_now: its _on_saved says when it fails),
        # never cfg.save() here: the whole config written on the UI thread
        def set_on(b: bool):
            cfg.api_enabled = b
            mw._save_now()
            refresh(mw.remctl.apply_remote())

        def set_port():
            if port.value() != cfg.api_port:
                cfg.api_port = port.value()
                mw._save_now()
                refresh(mw.remctl.apply_remote())

        def new_key():
            cfg.api_token = remote.new_token()
            refresh(mw.remctl.apply_remote())
            running = mw.remote.running

            def saved(ok: bool):   # only now is it the key after a restart too
                if not qt_valid(self) or not qt_valid(new):
                    return
                if not ok:   # it'd go back to the old one: no "made"
                    busy.toast(self, html.escape(_(
                        "Couldn't save your settings, see the log in %APPDATA%\\OnionBoard.")),
                        "error")
                    return
                busy.flash(new, _("✓ New key made"))
                if running:
                    busy.toast(self, html.escape(_(
                        "New key made: anything using the old one has stopped working. Copy "
                        "the example link for the new one.")), "warn")
            mw._save_now(saved)

        def copy_link():
            QApplication.clipboard().setText(
                f"http://{remote.HOST}:{cfg.api_port}/api/random?token={cfg.api_token}")
            busy.toast(self, html.escape(_("Copied. It holds your key: only paste it into your "
                                           "own tools.")), "ok")

        on.toggled.connect(set_on)
        port.editingFinished.connect(set_port)
        new.clicked.connect(new_key)
        copy.clicked.connect(copy_link)
        refresh()
        self.remote_on = on   # the streamer guide can turn it on: keep the box in step
        return card

    def _remote_addon_cards(self) -> list:
        """The cards of the "remote" add-ons (soundboard.modules), e.g. Onion Pocket.
        They're optional: one that's broken is left out (it's in the log), never an
        error box. Without a working Onion Pocket, a card offering to get it."""
        from soundboard import pocketaddon
        out, have = [], set()
        for info, addon in getattr(getattr(self.mw, "remctl", None), "remote_addons", []):
            card = self._addon_card(info, addon)
            if card is not None:
                if info.id == pocketaddon.MODULE_ID:
                    self._pocket_update(card, info)
                    self._pocket_remove_button(card, info)
                    self._pocket_slot = card
                out.append(card)
                have.add(info.id)
        if pocketaddon.MODULE_ID not in have and pocketaddon.offered():
            self._pocket_slot = self._get_pocket_card()
            out.append(self._pocket_slot)
        return out

    # ------------------------------------------------------------ Onion Pocket: remove
    def _pocket_info(self):
        """The installed Onion Pocket the app knows of (running or not), or None."""
        from soundboard import pocketaddon
        return next((i for i, _a in getattr(getattr(self.mw, "remctl", None), "remote_addons", [])
                     if i.id == pocketaddon.MODULE_ID), None)

    def _pocket_remove_button(self, card, info):
        """*Remove Onion Pocket* at the foot of its own card on Settings → Remote."""
        from soundboard import pocketaddon
        lay = card.layout()
        if lay is None or not pocketaddon.removable(info):
            return
        btn = QPushButton(_("Remove Onion Pocket"))
        btn.setToolTip(_("Takes the add-on out of Onion Board: phones can't play your pads any "
                         "more. Paired phones are kept for when you get it again."))
        icons.set_icon(btn, "trash", "danger_text")
        btn.clicked.connect(lambda: self._remove_pocket(btn))
        row = _button_row()
        row.addWidget(btn)
        lay.addLayout(row)
        self.pocket_remove = btn

    def _swap_pocket_slot(self, new):
        """Put `new` (a card, or None) where Onion Pocket's card is on Settings →
        Remote, if that page is built."""
        old = getattr(self, "_pocket_slot", None)
        self._pocket_slot = new
        if old is None or not qt_valid(old):
            return
        lay = old.parentWidget().layout() if old.parentWidget() else None
        if new is not None and lay is not None:
            lay.insertWidget(lay.indexOf(old), new)
        old.hide()
        old.deleteLater()

    def _pocket_changed(self):
        refresh = getattr(self, "_pocket_refresh", None)
        if refresh is not None:
            refresh()

    def _remove_pocket(self, btn):
        """Uninstall Onion Pocket, after asking: its server stops, and its card on
        Settings → Remote turns back into *Get Onion Pocket*."""
        from PySide6.QtWidgets import QMessageBox

        from soundboard import modules, pocketaddon
        info = self._pocket_info()
        if info is None:
            return
        if QMessageBox.question(
                self, _("Remove Onion Pocket?"),
                _("Remove the Onion Pocket add-on from Onion Board? Phones won't be able to play "
                  "your pads any more. Paired phones are kept for when you get it again.\n\nYou "
                  "can get it again from Settings → Remote any time."),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.mw.remctl.remove_remote_addon(info)
        except modules.ModuleError as e:
            log.warning("Onion Pocket couldn't be removed: %s", e)
            busy.toast(self, html.escape(_("Onion Pocket wasn't removed: {error}",
                                           error=errors.plain(e))), "error")
            return
        self.mw.pocket_offer = None
        if getattr(self, "_pocket_slot", None) is not None:
            self._swap_pocket_slot(self._get_pocket_card() if pocketaddon.offered()
                                   else None)
        self._pocket_changed()
        busy.toast(self, _("✓ Onion Pocket removed."), "ok")

    def _addon_card(self, info, addon):
        if addon is None:
            log.info("remote add-on %s left out of Settings: %s", info.id, info.error)
            return None
        try:
            return addon.card(self)
        except Exception as e:  # noqa: BLE001 - an add-on can't break Settings
            log.exception("add-on %s couldn't make its card", info.id)
            info.error = _("its settings failed: {error}", error=errors.plain(e))
            return None

    POCKET_CHECK_S = 3600   # how often Settings → Remote asks GitHub for a newer one

    def _pocket_update(self, card, info):
        """*Update Onion Pocket to X* on its card (soundboard.pocketaddon), once GitHub
        says a newer one is out: asked on a thread when Settings → Remote opens, at most
        once an hour (the answer is kept on the main window). Clicking it downloads the
        new one, and the main window swaps it in for the running copy, settings and
        all; then its new card takes this one's place. Optional and quiet: if anything
        fails, the old copy keeps running and the button just says it didn't work."""
        from soundboard import net, netlog, pocketaddon, updates
        mw = self.mw
        lay = card.layout()
        if lay is None:
            return

        class Relay(QObject):
            found = Signal(object)
            done = Signal(object)

        btn = QPushButton()
        btn.setObjectName("primary")
        btn.hide()
        row = _button_row()
        row.addWidget(btn)
        lay.addLayout(row)
        found = Relay(card)
        state = {}

        def show(offer):
            if offer is None or not qt_valid(btn) or not updates.newer(offer.version,
                                                                       info.version):
                return
            state["offer"] = offer
            btn.setText(_("Update Onion Pocket to {version}", version=offer.version))
            btn.setToolTip(_("You have {version}. Downloads it from GitHub and restarts Onion "
                             "Pocket: paired phones stay paired.", version=info.version))
            btn.show()

        def checked(offer):
            mw.pocket_offer = offer
            show(offer)

        def finish(new, relay):
            relay.deleteLater()
            addon = mw.remctl.load_remote_addon(new) if new is not None else None
            if new is not None:
                mw.pocket_offer = None      # installed: on disk now, whatever happens
            if not qt_valid(btn):
                return                      # Settings was closed: it's loaded anyway
            if addon is None:
                state["release"](_("Couldn't update it right now"))
                if new is not None:
                    btn.hide()
                return
            assert new is not None   # (addon is None without it)
            box = card.parentWidget().layout() if card.parentWidget() else None
            fresh = self._addon_card(new, addon)
            if fresh is not None and box is not None:
                self._pocket_remove_button(fresh, new)
                self._pocket_slot = card
                self._swap_pocket_slot(fresh)
                self._pocket_changed()
            else:
                state["release"]()
                btn.hide()
            busy.toast(self, _("✓ Onion Pocket {version} is in.",
                               version=html.escape(new.version)), "ok")

        def run():
            offer = state.get("offer")
            if offer is None:
                return
            state["release"] = busy.hold(btn, _("Updating Onion Pocket…"))
            netlog.cause(pocketaddon.FEATURE, "You clicked to update Onion Pocket "
                                              "(Settings > Remote)")
            relay = Relay(mw)   # the main window's: it's swapped in even if Settings closes
            relay.done.connect(lambda new: finish(new, relay))
            threading.Thread(target=lambda: relay.done.emit(pocketaddon.get(offer=offer)),
                             daemon=True, name="onion-pocket-update").start()

        btn.clicked.connect(run)
        found.found.connect(checked)
        self.pocket_update = btn
        offer = getattr(mw, "pocket_offer", None)
        if offer is not None:
            show(offer)
        elif (time.time() - getattr(mw, "pocket_checked", 0.0) >= self.POCKET_CHECK_S
              and (pocketaddon.local_zip() is not None or net.allowed(pocketaddon.FEATURE))):
            mw.pocket_checked = time.time()
            netlog.cause(pocketaddon.FEATURE, "Settings > Remote: is a newer Onion Pocket out?")
            def ask():
                offer = pocketaddon.check_update(info)
                try:
                    found.found.emit(offer)
                except RuntimeError:        # Settings was closed meanwhile
                    pass
            threading.Thread(target=ask, daemon=True, name="onion-pocket-check").start()

    def _get_pocket_card(self):
        """*Get Onion Pocket* (soundboard.pocketaddon): downloads, installs and starts
        it, then its own card takes this one's place. If that fails, this card just
        goes away; Onion Pocket is optional."""
        from soundboard import netlog, pocketaddon

        class Relay(QObject):
            done = Signal(object)

        card, cv = self._card(_("Onion Pocket: your pads on your phone"),
                              _("Scan a code with your phone's camera and tap a pad on the phone "
                                "to play it here. iPhone or Android, in the browser: nothing to "
                                "install on the phone. A free add-on from GitHub."))
        get = QPushButton(_("Get Onion Pocket"))
        row = _button_row()
        row.addWidget(get)
        cv.addLayout(row)
        relay = Relay(card)

        def finish(info):
            if not qt_valid(card):
                return
            addon = self.mw.remctl.load_remote_addon(info) if info is not None else None
            new = self._addon_card(info, addon) if addon is not None else None
            if new is not None:
                self._pocket_remove_button(new, info)
            self._pocket_slot = card
            self._swap_pocket_slot(new)
            self._pocket_changed()

        def run():
            busy.hold(get, _("Getting Onion Pocket…"))
            netlog.cause(pocketaddon.FEATURE, "You clicked to get Onion Pocket "
                                              "(Settings > Remote)")
            threading.Thread(target=lambda: relay.done.emit(pocketaddon.get()),
                             daemon=True, name="onion-pocket").start()
        relay.done.connect(finish)
        get.clicked.connect(run)
        self.get_pocket = get
        # Offline mode: gone, unless there's a zip on this PC to install it from
        return self.privacy._offline_card(card, lambda: pocketaddon.local_zip() is None)

    def _remote_easy_card(self):
        """The easy way in: the streamer guide, and a prompt for an AI assistant."""
        from soundboard.ui.crashdialog import free_dialog
        from soundboard.ui.streamguide import StreamerGuide, copy_prompt
        mw = self.mw
        card, cv = self._card(_("Set it up the easy way"),
                              _("New to this? The streamer guide shows how to put your sounds on "
                                "Stream Deck keys, channel points and chat commands, step by "
                                "step. Or copy a ready-made message for ChatGPT, Claude or any "
                                "AI chat: it explains Onion Board's links and lists your sounds, "
                                "so the AI can set up whatever tools you use with you."))
        # side by side, wrapping (not widening the window) when Settings is narrow
        btns = _button_row()
        guide = QPushButton(_("Streamer guide"))
        guide.setObjectName("primary")
        btns.addWidget(guide)
        ai = QPushButton(_("Copy AI prompt"))
        icons.set_icon(ai, "copy")
        ai.setToolTip(_("Paste it into ChatGPT / Claude and say which tools you use"))
        btns.addWidget(ai)
        cv.addLayout(btns)
        with_key = QCheckBox(_("Put my key in the prompt"))
        with_key.setToolTip(_("Saves pasting it in yourself. The key only works on this PC, but "
                              "it's still a password: leave this off if you'd rather the AI "
                              "never sees it"))
        cv.addWidget(with_key)
        state = QLabel()
        state.setObjectName("hint")
        state.setWordWrap(True)
        cv.addWidget(state)

        def open_guide():
            g = StreamerGuide(self, mw)
            g.exec()
            free_dialog(g)
            box = getattr(self, "remote_on", None)
            if box is not None and box.isChecked() != mw.cfg.api_enabled:
                box.setChecked(mw.cfg.api_enabled)   # turned on there

        def copy_ai():
            state.setText(copy_prompt(mw, with_key.isChecked()))
            busy.flash(ai, _("✓ Copied"))

        guide.clicked.connect(open_guide)
        ai.clicked.connect(copy_ai)
        return card


