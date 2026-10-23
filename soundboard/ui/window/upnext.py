"""Up next above the pads: one chip, "Up next" and how many wait, that opens the whole
list in a pop-up card, each with its whole name (as wide as the card allows, the rest in
its tooltip), its ✕, and Clear for all of them. The row used to show five chips and
"+n more": the names were cut at 150 px and the ones past the fifth couldn't be reached
at all, so a 10th queued sound couldn't be taken out.

Each row also has a grip to drag it to another place (among its own kind: web search /
link songs wait before the board's sounds) and a ▶ that plays it now."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSizePolicy, QStyle, QStyleOptionButton,
                               QVBoxLayout, QWidget)
from shiboken6 import isValid as qt_valid

from soundboard.i18n import _, ngettext
from soundboard.ui.kit import icons, panel
from soundboard.ui.kit.plaintext import plain_tip
from soundboard.ui.kit.panel import icon_button

POPUP_W = 400        # the list's card: narrow, a long name still fits most of itself
POPUP_ROWS = 9       # rows shown before the list scrolls
CHIP_H = 30          # as tall as the now-playing chips beside it
ROW_H = 32           # a row: its 24 px ✕, margins and the 4 px gap
LIST_GAP = 8         # between a scrolling list and its scroll bar (DESIGN: breathing room)

@dataclass
class Waiting:
    """One waiting sound: its name, what clicking the name, its ▶ and its ✕ do, and
    `on_move(to)`: dragged to place `to` among the rows of its own `group`."""
    text: str
    on_click: Callable[[], object]
    on_x: Callable[[], object]
    on_play: Callable[[], object]
    on_move: Callable[[int], object]
    group: str = ""


class _Name(QPushButton):
    """A row's name: the whole name, cut with "…" once, at the width the row really
    gives it (it was cut to a width worked out ahead, ~50 px short of the room there
    was). Its whole name is its tooltip."""

    def __init__(self, text: str):
        super().__init__()
        self.full = text
        self.setObjectName("chipname")
        self.setToolTip(plain_tip(text))   # a sound's name: web / board text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._fit()

    def sizeHint(self) -> QSize:
        return QSize(0, super().sizeHint().height())

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def _fit(self):
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        # inside the style sheet's padding
        room = self.style().subElementRect(QStyle.SubElement.SE_PushButtonContents,
                                           opt, self).width()
        text = self.fontMetrics().elidedText(self.full, Qt.TextElideMode.ElideRight,
                                             max(room, 0))
        self.setText(text.replace("&", "&&"))   # "R&B", not "RB"

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()


class _Grip(QLabel):
    """A row's drag handle: press, drag up or down, let go. The popup moves the row
    as the mouse goes and says where it ended up."""

    def __init__(self, popup: UpNextPopup, row: QFrame):
        super().__init__()
        self._popup, self._row = popup, row
        icons.set_label_icon(self, "grip", "muted", size=14)
        self.setFixedWidth(16)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(_("Drag to change the order"))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self._popup._drag_start(self._row)
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        self._popup._drag_move(e.globalPosition().toPoint())
        e.accept()

    def mouseReleaseEvent(self, e):
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._popup._drag_end()
        e.accept()


class UpNextChip(QPushButton):
    """The row's one Up next chip: a list icon, "Up next", how many wait ("3 waiting")
    and ^, one even 6 px apart and in one font (a button's own text and a smaller
    number made the gaps uneven, so they're labels inside it). A bare "3" read as
    everything, the sound playing too: it's only what waits (what plays has its own
    chip before it, the list the same 3). A button, so a screen reader says "button":
    a click, Enter or Space opens the list."""

    def __init__(self, count: int):
        super().__init__()
        self.setObjectName("upnextchip")
        self.setAutoDefault(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(_("See everything waiting to play"))
        self.setAccessibleDescription(_("See everything waiting to play"))
        self.setFixedHeight(CHIP_H)
        h = QHBoxLayout(self)
        h.setContentsMargins(11, 0, 11, 0)   # 10 inside its 1 px edge, as the frame had
        h.setSpacing(6)
        pic = QLabel()
        icons.set_label_icon(pic, "list", "muted", size=14)   # a theme colour, kept on switch
        name = QLabel(_("Up next"))
        self.count = QLabel()
        self.count.setObjectName("muted")
        bold = name.font()
        bold.setWeight(QFont.Weight.DemiBold)   # the chips' names are 600 too
        for w in (name, self.count):
            w.setFont(bold)
        fold = QLabel()
        icons.set_label_icon(fold, "fold_up", "muted", size=12)
        for w in (pic, name, self.count, fold):
            h.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)
        self.set_count(count)

    def sizeHint(self):
        # a button's own hint is for its (empty) text: the labels' row is its size
        lay = self.layout()
        return lay.sizeHint() if lay is not None else super().sizeHint()

    def minimumSizeHint(self):
        return self.sizeHint()

    def set_count(self, n: int):
        self.count.setText(ngettext("{n} waiting", "{n} waiting", n))
        # its name for a screen reader: the words it shows, "Up next 3 waiting"
        self.setAccessibleName(f"{_('Up next')} {self.count.text()}")

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):   # Space is a button's own
            self.click()
            return
        super().keyPressEvent(e)


class UpNextPopup(QWidget):
    """Everything waiting to play, in order. Escape or a click outside closes it; it
    stays open while sounds are taken out (`show_items` refills it in place)."""

    def __init__(self, parent: QWidget, on_clear: Callable[[], object]):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._outer = outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.count = QLabel()
        self.count.setObjectName("muted")
        self.clear = QPushButton(_("Clear"))
        self.clear.setObjectName("small")
        self.clear.setToolTip(_("Take everything out of the queue"))
        self.clear.clicked.connect(on_clear)
        self.clear.clicked.connect(self.close)
        close = icon_button("fold_open", _("Close"), size=14)
        close.clicked.connect(self.close)
        # the standard card (DESIGN: card recipe): its heading, and 14 px all round
        card, v = panel.card(_("Up next"), icon="list", beside=self.count,
                             end=(self.clear, close))
        card.setProperty("popup", True)
        outer.addWidget(card)
        self.card = card
        self.rows = QWidget()
        self.rows_v = QVBoxLayout(self.rows)
        # 8 px between the rows and the scroll bar: a row's ✕ never touches it
        self.rows_v.setContentsMargins(0, 0, LIST_GAP, 0)
        self.rows_v.setSpacing(4)
        self.list_area = QScrollArea()
        self.list_area.setWidgetResizable(True)
        self.list_area.setFrameShape(QFrame.Shape.NoFrame)
        self.list_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_area.setWidget(self.rows)
        v.addWidget(self.list_area)
        self.setFixedWidth(POPUP_W)
        self._anchor: QWidget | None = None
        self._rows: list[tuple[QFrame, QLabel, Waiting]] = []
        self._drag: tuple[QFrame, int] | None = None   # the row dragged, its place before

    def show_items(self, items: Sequence[Waiting]):
        """Fill the list (again): every waiting sound, numbered, with its grip, ▶ and ✕."""
        self._drag = None   # a row being dragged is gone with the rest
        self._rows = []
        while self.rows_v.count():
            item = self.rows_v.takeAt(0)
            w = item.widget() if item else None
            if w:
                w.setParent(None)
                w.deleteLater()
        self.count.setText(str(len(items)))
        a = self._anchor
        win = a.window().width() if a is not None and qt_valid(a) else POPUP_W + 16
        self.setFixedWidth(max(240, min(POPUP_W, win - 16)))   # inside a narrow window
        for i, it in enumerate(items):
            row = QFrame()
            row.setObjectName("chip")
            h = QHBoxLayout(row)
            h.setContentsMargins(4, 2, 2, 2)
            h.setSpacing(6)
            num = QLabel(str(i + 1))
            num.setObjectName("muted")
            num.setFixedWidth(22)
            name = _Name(it.text)
            name.clicked.connect(it.on_click)
            play = QPushButton()
            play.setObjectName("chipstop")
            play.setToolTip(_("Play it now"))
            play.setAccessibleName(_("Play it now"))
            icons.set_icon(play, "play", "accent", size=14)
            play.setFixedSize(24, 24)
            play.clicked.connect(it.on_play)
            x = QPushButton()
            x.setObjectName("chipstop")
            x.setToolTip(_("Take it out of the queue"))
            icons.close_button(x, 24)
            x.clicked.connect(it.on_x)
            h.addWidget(_Grip(self, row))
            h.addWidget(num)
            h.addWidget(name, 1)
            h.addWidget(play)
            h.addWidget(x)
            self.rows_v.addWidget(row)
            self._rows.append((row, num, it))
        self.rows_v.addStretch(1)
        # as tall as its rows really are (no scroll bar for a few), up to POPUP_ROWS
        shown = [r for r, _n, _it in self._rows[:POPUP_ROWS]]
        self.list_area.setFixedHeight(sum(r.sizeHint().height() for r in shown)
                                      + self.rows_v.spacing() * max(len(shown) - 1, 0))
        # its whole height (adjustSize caps a window at 2/3 of the screen, which
        # squeezed the heading of a long list on a small screen); the card's new size
        # first, or the longer list's (cached by this layout) keeps it tall, a gap over
        # the rows, when sounds are taken out with it open
        self.card.updateGeometry()
        self._outer.activate()
        self.resize(self.width(), self.sizeHint().height())
        self._place()

    def _group_rows(self, group: str) -> list[QFrame]:
        return [r for r, _n, it in self._rows if it.group == group]

    def _drag_start(self, row: QFrame):
        hit = next((it for r, _n, it in self._rows if r is row), None)
        if hit is None:
            return
        self._drag = (row, self._group_rows(hit.group).index(row))

    def _drag_move(self, gpos: QPoint):
        """The row follows the mouse, a place at a time, among its own group's rows
        (the list scrolls when the mouse goes past its top or bottom)."""
        if self._drag is None:
            return
        row = self._drag[0]
        if not qt_valid(row):
            self._drag = None
            return
        area = self.list_area.viewport()
        at = area.mapFromGlobal(gpos).y()
        bar = self.list_area.verticalScrollBar()
        if at < 0:
            bar.setValue(bar.value() - ROW_H // 2)
        elif at > area.height():
            bar.setValue(bar.value() + ROW_H // 2)
        y = self.rows.mapFromGlobal(gpos).y()
        idx = next(i for i, (r, _n, _it) in enumerate(self._rows) if r is row)
        group = self._rows[idx][2].group
        same = [i for i, (r, _n, it) in enumerate(self._rows) if it.group == group]
        # its place: after every other row of its group whose middle the mouse is below
        # (a group's rows are next to each other)
        to = same[0] + sum(1 for i in same if i != idx
                           and y > self._rows[i][0].y() + self._rows[i][0].height() // 2)
        if to == idx:
            return
        self._rows.insert(to, self._rows.pop(idx))
        self.rows_v.removeWidget(row)
        self.rows_v.insertWidget(to, row)
        for i, (_r, num, _it) in enumerate(self._rows):
            num.setText(str(i + 1))

    def _drag_end(self):
        """Let go: the row's new place goes to its list (which refills this one)."""
        drag, self._drag = self._drag, None
        if drag is None or not qt_valid(drag[0]):
            return
        row, was = drag
        hit = next((it for r, _n, it in self._rows if r is row), None)
        if hit is None:
            return
        now = self._group_rows(hit.group).index(row)
        if now != was:
            hit.on_move(now)

    def open_at(self, anchor: QWidget, items: Sequence[Waiting]):
        self._anchor = anchor
        self.show_items(items)
        self.list_area.verticalScrollBar().setValue(0)   # from the top, every time
        self.show()
        self._place()

    def _place(self):
        """Above its chip, left edges lined up (right edges in a right-to-left
        language), kept inside the window and on its screen; below it when there's no
        room above."""
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
        win = a.window().geometry()
        left, right = max(scr.left(), win.left()), min(scr.right(), win.right())
        x = max(left, min(top.x(), right - self.width()))
        self.move(x, y)
