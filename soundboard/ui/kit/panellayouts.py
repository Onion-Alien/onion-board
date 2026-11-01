"""The page kit's layouts (ui/kit/panel.py): `ShownStack` (as tall as the page it shows), keeping
focus off a page being switched away, `Flow` (wrapping, right to left too) and `CardGrid`
(equal columns of cards). `panel` re-exports them."""
from __future__ import annotations

from contextlib import contextmanager

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QApplication, QLayout, QStackedWidget, QStyle, QTabWidget, QWidget
from shiboken6 import isValid as qt_valid


@contextmanager
def keep_focus_off(stack: QTabWidget | QStackedWidget):
    """Switching `stack`'s page with the focus on the page going away: Qt hands it to the
    first button on the new page (an ⓘ, a combo), ringed as if tabbed to though nobody
    pressed a key. The new page itself takes it instead, as a click on the rail leaves
    it: no ring, and Tab still starts at its first control."""
    old = stack.currentWidget()
    fw = QApplication.focusWidget()
    moving = old is not None and fw is not None and (fw is old or old.isAncestorOf(fw))
    yield
    page = stack.currentWidget()
    if moving and page is not None and page is not old:
        page.setFocus(Qt.FocusReason.OtherFocusReason)


class ShownStack(QStackedWidget):
    """A QStackedWidget whose height at a width is its page on show's. Qt's asks every
    page, and the hidden ones' wrapped text was laid out again at each new width: on
    every step of a window resize, for the window's pages, the Settings page and the
    tabs. Its smallest size still counts every page, as Qt's does."""

    def heightForWidth(self, w: int) -> int:
        page, lay = self.currentWidget(), self.layout()
        if page is None or lay is None or not page.hasHeightForWidth():
            return super().heightForWidth(w)
        m, lm = self.contentsMargins(), lay.contentsMargins()
        h = page.heightForWidth(w - m.left() - m.right() - lm.left() - lm.right())
        return h + m.top() + m.bottom() + lm.top() + lm.bottom() if h >= 0 else h

    def setCurrentIndex(self, i: int):
        with keep_focus_off(self):
            super().setCurrentIndex(i)

    def setCurrentWidget(self, w: QWidget):
        with keep_focus_off(self):
            super().setCurrentWidget(w)


class Flow(QLayout):
    """Lays its widgets out left to right, wrapping onto new lines (the Radio tab's
    genre chips, the Triggers tab's settings)."""

    def __init__(self, parent=None, gap: int = 6):
        super().__init__(parent)
        self._items, self._gap = [], gap
        self._widgets: list = []   # each item's widget (None for a spacer), in step
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)
        self._widgets.append(item.widget())

    def _alive(self) -> list:
        """Its items, with any whose Qt side is already gone made again for their widget
        (or dropped, the widget gone too). One went once, around loading and removing
        Onion Watch: every layout pass raised on it and the app crashed; dropping it
        then left its button where it was while the row thought itself empty, 0 px
        tall, so the line under Who's listening's modes sat on top of them."""
        if all(qt_valid(it) for it in self._items):
            return self._items
        items, widgets, again = [], [], []
        for it, w in zip(self._items, self._widgets):
            if qt_valid(it):
                items.append(it)
                widgets.append(w)
            elif w is not None and qt_valid(w):
                again.append((len(items) + len(again), w))
        self._items, self._widgets = items, widgets
        for i, w in again:   # Qt makes (and owns) its new item, appended by addItem
            self.addWidget(w)
            self._items.insert(i, self._items.pop())
            self._widgets.insert(i, self._widgets.pop())
        return self._items

    def count(self):
        return len(self._alive())

    def itemAt(self, i):
        items = self._alive()
        return items[i] if 0 <= i < len(items) else None

    def takeAt(self, i):
        items = self._alive()
        if not 0 <= i < len(items):
            return None
        self._widgets.pop(i)
        return items.pop(i)

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._place(QRect(0, 0, w, 0), move=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._place(rect, move=True)

    def sizeHint(self):
        # its lines at the width it has (all on one line before it's been laid out).
        # Not the narrowest width: Qt sizes a widget holding this at the height for
        # its hint's width, and a box whose height can't shrink (the Radio tab's genre
        # chips) then asked for every chip on its own line. That made the Radio tab
        # need ~300 px more whenever the window was big enough to show the chips, so
        # a maximized window restored to an ordinary size became the mini player.
        w = self.geometry().width()
        if w <= 0:
            w = sum(it.sizeHint().width() + self._gap for it in self._alive()
                    if not it.isEmpty()) - self._gap
        w = max(w, self.minimumSize().width())
        return QSize(w, self.heightForWidth(w))

    def minimumSize(self):
        size = QSize()
        for it in self._alive():
            size = size.expandedTo(it.minimumSize())
        return size

    def _place(self, rect: QRect, move: bool) -> int:
        """Each item is centred on its line's height: a label beside taller chips
        ("Now playing" before the sounds' ■ chips) sat at their top edge instead."""
        x, y, line = rect.x(), rect.y(), 0
        row: list = []   # (item, x, hint) of the line being filled

        owner = self.parentWidget()
        rtl = owner is not None and owner.layoutDirection() == Qt.LayoutDirection.RightToLeft

        def put():
            if move:
                for it, ix, hint in row:
                    r = QRect(QPoint(ix, y + (line - hint.height()) // 2), hint)
                    # Arabic: the lines fill from the right, like the rest of the app
                    it.setGeometry(QStyle.visualRect(Qt.LayoutDirection.RightToLeft, rect, r)
                                   if rtl else r)
            row.clear()

        for it in self._alive():
            if it.isEmpty():
                continue
            hint = it.sizeHint()
            if hint.width() > rect.width() > 0:   # wider than the whole row: as narrow
                hint.setWidth(max(rect.width(), it.minimumSize().width()))   # as it goes
                if it.hasHeightForWidth():   # and as tall as it then needs (WrapButton)
                    hint.setHeight(it.heightForWidth(hint.width()))
            if line and x + hint.width() > rect.right() + 1:
                put()
                x, y, line = rect.x(), y + line + self._gap, 0
            row.append((it, x, hint))
            x += hint.width() + self._gap
            line = max(line, hint.height())
        put()
        return y + line - rect.y()


class CardGrid(QLayout):
    """Lays its widgets out as a grid of equal-width cards, as many across as fit
    at `min_w` each (at most `max_cols`), stretched to fill the row. Each row is as
    tall as its tallest card; the cards in it too, unless `even` is off (the Apps
    tab: one card's open clip editor mustn't stretch its neighbours)."""

    def __init__(self, parent=None, min_w: int = 240, gap: int = 10, max_cols: int = 0,
                 even: bool = True):
        super().__init__(parent)
        self._items, self._gap = [], gap
        self.min_w, self.max_cols = min_w, max_cols
        self.even = even   # False: each card keeps its own height, top-aligned in its row
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._place(QRect(0, 0, w, 0), move=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._place(rect, move=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        return QSize(self.min_w, 0)

    def columns(self, width: int) -> int:
        """How many cards fit across `width`."""
        n = max(1, (width + self._gap) // (self.min_w + self._gap))
        return min(n, self.max_cols) if self.max_cols else n

    def _place(self, rect: QRect, move: bool) -> int:
        shown = [it for it in self._items if not it.isEmpty()]
        if not shown:
            return 0
        cols = self.columns(rect.width())
        cw = max(1, (rect.width() - self._gap * (cols - 1)) // cols)
        y = rect.y()
        for i in range(0, len(shown), cols):
            line = shown[i:i + cols]
            hs = [max(it.heightForWidth(cw) if it.hasHeightForWidth() else it.sizeHint().height(),
                      it.minimumSize().height()) for it in line]
            h = max(hs)
            if move:
                for j, it in enumerate(line):
                    it.setGeometry(QRect(rect.x() + j * (cw + self._gap), y, cw,
                                         h if self.even else hs[j]))
            y += h + self._gap
        return y - self._gap - rect.y()
