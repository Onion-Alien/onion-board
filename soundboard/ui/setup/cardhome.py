"""One card shown in two places: its home on the Setup tab, and a visit to a Settings
page while that page is on screen (Settings → Audio's Your mic).

The card itself moves, so both places show the same live widgets (its status, its
level meter, its buttons) and nothing has to be kept in step with a copy. Each move
makes Qt work out the style of every widget in the card again (~12 ms, several times
that on a slower PC), so it only moves when it has to: to the visit when that shows,
home when Setup shows. Settings closed onto another tab leaves it where it was, and
opened again it's already there. While it's away its home keeps the card's size, so
Setup (and the room the window needs) don't change. A Settings (or a page of it) about
to be freed gives it back first: give_back."""
from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QLayout, QVBoxLayout, QWidget
from shiboken6 import isValid

from soundboard.ui.window.responsive import touch


def _layout(card: QWidget) -> QLayout:
    lay = card.layout()
    assert lay is not None   # (card() always gives it one)
    return lay


class CardHome(QWidget):
    """The card's place on the Setup tab: the Setup layouts hold this, never the card,
    so placing Setup's columns never takes the card back while it's visiting."""

    def __init__(self, card: QWidget, parent: QWidget | None = None):
        super().__init__(parent)
        self.card = card
        # its heading, as Setup's other cards have (card(): lined up with theirs)
        self.heading_title = getattr(card, "heading_title", None)
        self.heading_marks = getattr(card, "heading_marks", ())
        self._margins = _layout(card).contentsMargins()
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.addWidget(card)

    def away(self) -> bool:
        return self.card.parentWidget() is not self

    def take_back(self):
        if self.away():
            _layout(self.card).setContentsMargins(self._margins)
            self._lay.addWidget(self.card)
            self.card.show()
            touch(self.card)

    def showEvent(self, e):
        super().showEvent(e)
        if not e.spontaneous():   # (Setup shown, not the window back from minimised)
            self.take_back()

    # away: the card's sizes as they are here (its own margins, not the visit's)
    def _extra(self) -> tuple[int, int]:
        home, now = self._margins, _layout(self.card).contentsMargins()
        return (home.left() + home.right() - now.left() - now.right(),
                home.top() + home.bottom() - now.top() - now.bottom())

    def _grown(self, s: QSize) -> QSize:
        dw, dh = self._extra()
        return QSize(s.width() + dw, s.height() + dh)

    def sizeHint(self):
        return self._grown(self.card.sizeHint()) if self.away() else super().sizeHint()

    def minimumSizeHint(self):
        if self.away():
            return self._grown(self.card.minimumSizeHint())
        return super().minimumSizeHint()

    def hasHeightForWidth(self):
        return self.card.hasHeightForWidth() if self.away() else super().hasHeightForWidth()

    def heightForWidth(self, w: int):
        if not self.away():
            return super().heightForWidth(w)
        dw, dh = self._extra()
        h = self.card.heightForWidth(w - dw)
        return h + dh if h >= 0 else h


class CardVisit(QWidget):
    """Where the card shows on another page, while that page is on screen."""

    def __init__(self, home: CardHome, parent: QWidget | None = None,
                 margins: tuple[int, int, int, int] | None = None):
        super().__init__(parent)
        self.home = home
        self.margins = margins   # the card's, while it's here (as the page's own cards)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)

    def has_card(self) -> bool:
        return self.home.card.parentWidget() is self

    def borrow(self):
        card = self.home.card
        if not self.has_card():
            if self.margins is not None:
                _layout(card).setContentsMargins(*self.margins)
            self._lay.addWidget(card)
            card.show()
            touch(card)

    def showEvent(self, e):
        super().showEvent(e)
        if not e.spontaneous():   # (not the window coming back from minimised)
            self.borrow()

    def sizeHint(self):
        # empty while the card is home: as big as the card, so the page doesn't jump
        # when it arrives
        return super().sizeHint() if self.has_card() else self.home.card.sizeHint()


def give_back(widget: QWidget | None):
    """A card visiting anywhere in `widget` goes home: `widget` is about to be freed,
    and the card would go with it."""
    if widget is None or not isValid(widget):   # (already gone: nothing in it to save)
        return
    for visit in widget.findChildren(CardVisit):
        if visit.has_card():
            visit.home.take_back()
