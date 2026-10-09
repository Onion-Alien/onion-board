"""The main window's tabs as a thin rail down the left: one icon per tab, and a
button at the bottom that opens it out to show their names, with the onion and
"by Onion Alien" on top. The QTabWidget stays (its pages, live marks and settings
all work as before); only its bar is hidden, and the rail mirrors it: each tab's
icon (live badge, voice picture, warning tint), name, tip and whether it's shown."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QFrame, QLabel, QPushButton, QSizePolicy, QTabWidget,
                               QToolButton, QVBoxLayout, QWidget)

from soundboard import theme
from soundboard.i18n import _
from soundboard.ui import icons

ICON = 20          # a tab's icon on the rail
SHUT_W = 43        # the rail's width, shut: its 1 px edge, 4, a 34 px button, 4...
OPEN_W = 168       # ...and opened out
LOGO_SHUT = 24     # the onion, shut: with its 5 px glow room, a tab button's width
LOGO_OPEN = 32
SIDE_SHUT = 4      # the rail's own side margins, shut (a 34 px button)...
SIDE_OPEN = 10     # ...and open
LIVE_BAR_W = 3     # a live tab's bar on the rail's outer edge (Settings > Live tabs: tint)
TEXT_W = OPEN_W - 2 * SIDE_OPEN - ICON - 24   # a name's room on the open rail (icon,
                                              # padding, border, the gap after the icon)
TINT_ALPHA = 0.16  # the current tab's soft accent fill (an outlined box looked heavy)


class SideTabs(QTabWidget):
    """A QTabWidget whose bar is never shown (the rail stands in for it), and that
    says when anything the rail shows has changed."""

    changed = Signal()

    def __init__(self):
        super().__init__()
        self.tabBar().hide()
        self.tabBar().installEventFilter(self)

    def eventFilter(self, obj: QObject, e: QEvent) -> bool:
        if obj is self.tabBar() and e.type() == QEvent.Show:
            obj.hide()   # QTabWidget shows it again when it lays itself out
        return False

    # what changes a tab's look, all through here
    def setTabText(self, i, text):
        super().setTabText(i, text)
        self.changed.emit()

    def setTabToolTip(self, i, tip):
        super().setTabToolTip(i, tip)
        self.changed.emit()

    def setTabIcon(self, i, icon):   # a theme or highlight colour change (icons.retheme)
        super().setTabIcon(i, icon)
        self.changed.emit()

    def setTabVisible(self, i, on):
        super().setTabVisible(i, on)
        self.changed.emit()

    def tabInserted(self, i):
        super().tabInserted(i)
        self.changed.emit()

    def tabRemoved(self, i):
        super().tabRemoved(i)
        self.changed.emit()


class RailTab(QToolButton):
    """One tab on the rail. Paints the current tab's fill (a live one's mark is the
    rail's: SideRail.paintEvent; or, with Settings' dot, the dot in its icon)."""

    def __init__(self, rail: SideRail, index: int):
        super().__init__()
        self.rail, self.index = rail, index
        self.setObjectName("railtab")
        self.setCheckable(True)   # (the rail checks the current one: see SideRail.sync)
        self.setCursor(Qt.PointingHandCursor)
        self.setIconSize(QSize(ICON, ICON))
        self.setFocusPolicy(Qt.TabFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setContextMenuPolicy(Qt.CustomContextMenu)

    def paintEvent(self, e):
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.isChecked():   # the current tab: a soft accent fill under the icon
            self._fill(r, theme.T["accent"], TINT_ALPHA)
        super().paintEvent(e)

    def keyPressEvent(self, e):
        """Up / down: the tab before / after it, as the arrows did on the old top bar
        (left / right too; mirrored, left is the next one)."""
        step = {Qt.Key_Up: -1, Qt.Key_Down: 1, Qt.Key_Left: -1, Qt.Key_Right: 1}.get(e.key())
        if step is None or e.modifiers() & ~Qt.KeypadModifier:
            return super().keyPressEvent(e)
        if self.isRightToLeft() and e.key() in (Qt.Key_Left, Qt.Key_Right):
            step = -step
        shown = [b for b in self.rail.buttons if b.isVisible()]
        if self in shown:
            b = shown[(shown.index(self) + step) % len(shown)]
            b.setFocus(Qt.TabFocusReason)
            b.click()

    def is_live(self) -> bool:
        return bool(self.rail.tabs.tabBar().property(f"_live{self.index}"))

    def _fill(self, r: QRectF, color: str, alpha: float):
        c = QColor(color)
        c.setAlphaF(alpha)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(r, 8, 8)


class SideRail(QFrame):
    """The rail. `extras` (More tabs, ⓘ) sit under the tabs and `foot` (Settings) at
    the bottom, over the open / shut button; each shows its "railtext" property as
    its words while open. `on_open(bool)` is called when the user opens or shuts it
    (to save it)."""

    def __init__(self, tabs: SideTabs, logo: QWidget, brand: QLabel, byline: QLabel,
                 extras: list[QPushButton], is_open: bool, foot: list[QPushButton] = (),
                 on_open=None):
        super().__init__()
        self.setObjectName("sidebar")
        self.tabs = tabs
        self._open = is_open
        self._squeezed = False   # a narrow window: shut, whatever was picked
        self._on_open = on_open
        lay = self._lay = QVBoxLayout(self)
        lay.setSpacing(4)
        # the onion, and when open, the name and "by Onion Alien" under it
        self.logo = logo
        lay.addWidget(logo, 0, Qt.AlignHCenter)
        self.brand, self.byline = brand, byline
        brand.setAlignment(Qt.AlignHCenter)
        byline.setAlignment(Qt.AlignHCenter)
        byline.setWordWrap(True)
        lay.addWidget(self.brand)
        lay.addWidget(self.byline)
        lay.addSpacing(10)
        self.buttons: list[RailTab] = []
        for i in range(tabs.count()):
            b = RailTab(self, i)
            b.clicked.connect(lambda _c=False, i=i: (tabs.setCurrentIndex(i), self.sync()))
            lay.addWidget(b)
            self.buttons.append(b)
        self.extras = [*extras, *foot]
        for w in self.extras:   # the keyboard's ring, not one left by a click
            w.setFocusPolicy(Qt.TabFocus)
        lay.addSpacing(10)   # More tabs and ⓘ aren't tabs
        for w in extras:
            lay.addWidget(w)
        lay.addStretch(1)
        for w in foot:
            lay.addWidget(w)
        self.toggle = QPushButton()
        self.toggle.setObjectName("railtoggle")
        self.toggle.setCursor(Qt.PointingHandCursor)
        self.toggle.setFocusPolicy(Qt.TabFocus)
        self.toggle.clicked.connect(lambda: self.set_open(not self._open))
        self.toggle.setFixedWidth(SHUT_W - 2 * SIDE_SHUT - 1)   # a tab button's, open too
        lay.addWidget(self.toggle, 0, Qt.AlignLeft)   # (mirrored: the right)
        tabs.changed.connect(self.sync)
        tabs.currentChanged.connect(self.sync)
        self._apply()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.LayoutDirectionChange and hasattr(self, "toggle"):
            self._apply()

    def paintEvent(self, e):
        """A live tab's mark (Settings > Live tabs, "tint"): a bar on the rail's edge
        beside it, in the highlight colour, with its icon in that colour too. A wash
        like the old tab bar's looked just like the current tab's fill."""
        super().paintEvent(e)
        if not self.tabs.property("_live_tint"):
            return   # the dot: in the icon itself (livedot / icons.set_tab_icon)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.T["live_text"]))
        for b in self.buttons:
            if b.isVisible() and b.is_live():
                g = b.geometry()
                h = g.height() * 0.6
                # on the window's edge: the right one when mirrored (Arabic)
                x = self.width() - LIVE_BAR_W if self.isRightToLeft() else -LIVE_BAR_W
                r = QRectF(x, g.center().y() - h / 2, 2 * LIVE_BAR_W, h)
                p.drawRoundedRect(r, LIVE_BAR_W, LIVE_BAR_W)   # (half of it off the edge)

    # ---- the tab widget's state, on the rail
    def sync(self, *_a):
        bar = self.tabs.tabBar()
        cur = self.tabs.currentIndex()
        shown = self.is_open()
        for b in self.buttons:
            i = b.index
            if i >= self.tabs.count():
                b.hide()
                continue
            name = self.tabs.tabText(i).replace("&&", "&")
            tip = self.tabs.tabToolTip(i)
            b.setVisible(self.tabs.isTabVisible(i))
            b.setIcon(bar.tabIcon(i))
            text = self._fit(b, name) if shown else ""
            b.setText(text)
            b.setAccessibleName(name)
            # shut (or cut short), the name goes on hover, after the "● ON" line when live
            b.setToolTip(tip if text == name else "\n".join(filter(None, (tip, name))))
            b.setChecked(i == cur)
            b.update()
        self.update()   # the live bars

    @staticmethod
    def _fit(w: QWidget, text: str) -> str:
        """`text` cut with "…" to what fits beside the icon on the open rail (a long
        translation pushed past the rail's edge)."""
        return w.fontMetrics().elidedText(text, Qt.ElideRight, TEXT_W)

    def _label(self, w: QPushButton, name: str, tip: str, shown: bool):
        """A button under the tabs: its name while open (cut to fit), and on hover its
        tip, with the name in front when it isn't all there to read."""
        text = self._fit(w, name) if shown else ""
        w.setText(text)
        w.setAccessibleName(name)
        w.setToolTip(tip if text == name or tip == name or not tip else
                     f"{name}\n{tip}" if tip else name)

    # ---- open / shut
    def is_open(self) -> bool:
        return self._open and not self._squeezed

    def set_open(self, on: bool):
        if on == self._open:
            return
        self._open = on
        self._apply()
        if self._on_open:
            self._on_open(on)

    def squeeze(self, tight: bool):
        """A narrow window shuts it (a responsive step); it opens again with room."""
        if tight != self._squeezed:
            self._squeezed = tight
            self._apply()

    def _apply(self):
        shown = self.is_open()
        if self.property("rtl") != self.isRightToLeft():   # its border on the inner edge
            self.setProperty("rtl", self.isRightToLeft())
            self.style().unpolish(self)
            self.style().polish(self)
        self.setFixedWidth(OPEN_W if shown else SHUT_W)
        side = SIDE_OPEN if shown else SIDE_SHUT
        self._lay.setContentsMargins(side, 10, side, 10)
        if hasattr(self.logo, "set_mark"):   # shut, it's as wide as a tab button
            self.logo.set_mark(LOGO_OPEN if shown else LOGO_SHUT)
        self.brand.setVisible(shown)
        self.byline.setVisible(shown)
        style = Qt.ToolButtonTextBesideIcon if shown else Qt.ToolButtonIconOnly
        for b in self.buttons:
            b.setToolButtonStyle(style)
            b.setProperty("open", shown)
        for w in self.extras:
            if w.property("railtip") is None:   # its own tip, kept under the name
                w.setProperty("railtip", w.toolTip())
            w.setProperty("railopen", shown)
            self._label(w, w.property("railtext") or "", w.property("railtip"), shown)
            w.style().unpolish(w)
            w.style().polish(w)
        self.toggle.setVisible(not self._squeezed)
        # the arrow points the way the rail will go: mirrored (Arabic), it opens leftwards
        icons.set_icon(self.toggle, "back" if shown != self.isRightToLeft() else "forward",
                       size=ICON)
        # only the arrow, open or shut ("Hide tab names" was cut short in most
        # languages); its name is what it does now, on hover and for a screen reader
        self._label(self.toggle, _("Hide tab names") if shown else _("Show tab names"), "",
                    False)
        self.sync()
        # one height for everything on the rail: the buttons under the tabs came out
        # 3 px shorter, so their focus ring and hover box didn't match the tabs'
        everything = [*self.buttons, *self.extras, self.toggle]
        for w in everything:
            w.setMinimumHeight(0)
            w.setMaximumHeight(16777215)
        h = max(w.sizeHint().height() for w in everything)
        for w in everything:
            w.setFixedHeight(h)
