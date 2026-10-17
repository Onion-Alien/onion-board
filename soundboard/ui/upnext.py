"""Up next above the pads: one chip, "Up next" and how many wait, that opens the whole
list in a pop-up card, each with its whole name (as wide as the card allows, the rest in
its tooltip), its ✕, and Clear for all of them. The row used to show five chips and
"+n more": the names were cut at 150 px and the ones past the fifth couldn't be reached
at all, so a 10th queued sound couldn't be taken out."""
from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)
from shiboken6 import isValid as qt_valid

from soundboard.i18n import _
from soundboard.ui import icons
from soundboard.ui.panel import icon_button

POPUP_W = 400        # the list's card: narrow, a long name still fits most of itself
POPUP_ROWS = 9       # rows shown before the list scrolls
ROW_H = 32           # a row: its 24 px ✕, margins and the 4 px gap

# one waiting sound: its name, what clicking the name does, what its ✕ does
Waiting = tuple[str, Callable[[], object], Callable[[], object]]


class UpNextChip(QFrame):
    """The row's one Up next chip: a list icon, "Up next", the count and ^. A click
    anywhere on it opens the list."""
    clicked = Signal()

    def __init__(self, count: int):
        super().__init__()
        self.setObjectName("chip")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 2, 2, 2)
        h.setSpacing(4)
        pic = QLabel()
        pic.setPixmap(icons.pixmap("list", 14, "accent"))
        self.name = QPushButton(_("Up next"))
        self.name.setObjectName("chipname")
        self.name.setToolTip(_("See everything waiting to play"))
        self.name.clicked.connect(self.clicked)
        self.count = QLabel(str(count))
        self.count.setObjectName("decktitle")
        self.open = QPushButton()
        self.open.setObjectName("chipstop")
        self.open.setAccessibleName(_("See everything waiting to play"))
        icons.set_icon(self.open, "fold_up", "muted", size=12)
        self.open.setFixedSize(24, 24)
        self.open.clicked.connect(self.clicked)
        h.addWidget(pic)
        h.addWidget(self.name)
        h.addWidget(self.count)
        h.addWidget(self.open)

    def set_count(self, n: int):
        self.count.setText(str(n))

    def mouseReleaseEvent(self, e):   # the icon and the number open it too
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)


class UpNextPopup(QWidget):
    """Everything waiting to play, in order. Escape or a click outside closes it; it
    stays open while sounds are taken out (`show_items` refills it in place)."""

    def __init__(self, parent: QWidget, on_clear: Callable[[], object]):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("card")
        card.setProperty("popup", True)
        outer.addWidget(card)
        v = QVBoxLayout(card)
        v.setContentsMargins(10, 8, 10, 10)
        v.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(6)
        pic = QLabel()
        pic.setPixmap(icons.pixmap("list", 16, "accent"))
        title = QLabel(_("Up next"))
        title.setObjectName("decktitle")
        self.count = QLabel()
        self.count.setObjectName("muted")
        self.clear = QPushButton(_("Clear"))
        self.clear.setObjectName("small")
        self.clear.setToolTip(_("Take everything out of the queue"))
        self.clear.clicked.connect(on_clear)
        self.clear.clicked.connect(self.close)
        close = icon_button("fold_open", _("Close"), size=14)
        close.clicked.connect(self.close)
        top.addWidget(pic)
        top.addWidget(title)
        top.addWidget(self.count)
        top.addStretch(1)
        top.addWidget(self.clear)
        top.addWidget(close)
        v.addLayout(top)
        self.rows = QWidget()
        self.rows_v = QVBoxLayout(self.rows)
        self.rows_v.setContentsMargins(0, 0, 0, 0)
        self.rows_v.setSpacing(4)
        self.list_area = QScrollArea()
        self.list_area.setWidgetResizable(True)
        self.list_area.setFrameShape(QFrame.Shape.NoFrame)
        self.list_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_area.setWidget(self.rows)
        v.addWidget(self.list_area)
        self.setFixedWidth(POPUP_W)
        self._anchor: QWidget | None = None

    def show_items(self, items: Sequence[Waiting]):
        """Fill the list (again): every waiting sound, numbered, with its ✕."""
        while self.rows_v.count():
            item = self.rows_v.takeAt(0)
            w = item.widget() if item else None
            if w:
                w.setParent(None)
                w.deleteLater()
        self.count.setText(str(len(items)))
        name_w = POPUP_W - 130   # the card's margins, the number, the ✕ and a scroll bar
        for i, (text, on_click, on_x) in enumerate(items):
            row = QFrame()
            row.setObjectName("chip")
            h = QHBoxLayout(row)
            h.setContentsMargins(8, 2, 2, 2)
            h.setSpacing(6)
            num = QLabel(str(i + 1))
            num.setObjectName("muted")
            num.setFixedWidth(22)
            name = QPushButton(row.fontMetrics().elidedText(
                text, Qt.TextElideMode.ElideRight, name_w).replace("&", "&&"))
            name.setObjectName("chipname")
            name.setToolTip(text)
            name.clicked.connect(on_click)
            x = QPushButton()
            x.setObjectName("chipstop")
            x.setToolTip(_("Take it out of the queue"))
            icons.close_button(x, 24)
            x.clicked.connect(on_x)
            h.addWidget(num)
            h.addWidget(name, 1)
            h.addWidget(x)
            self.rows_v.addWidget(row)
        self.rows_v.addStretch(1)
        self.list_area.setFixedHeight(min(len(items), POPUP_ROWS) * ROW_H)
        self.adjustSize()
        self._place()

    def open_at(self, anchor: QWidget, items: Sequence[Waiting]):
        self._anchor = anchor
        self.show_items(items)
        self.show()
        self._place()

    def _place(self):
        """Above its chip, left edges lined up (right edges in a right-to-left
        language), kept on the window's screen; below it when there's no room above."""
        a = self._anchor
        if a is None or not qt_valid(a) or not a.isVisible():
            return
        rtl = a.layoutDirection() == Qt.LayoutDirection.RightToLeft
        x = a.width() - self.width() if rtl else 0
        top = a.mapToGlobal(QPoint(x, 0))
        y = top.y() - self.height() - 6
        scr = a.screen().availableGeometry()
        if y < scr.top():
            y = a.mapToGlobal(QPoint(0, a.height())).y() + 6
        x = max(scr.left(), min(top.x(), scr.right() - self.width()))
        self.move(x, y)
