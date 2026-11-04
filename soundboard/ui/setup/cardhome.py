"""One card shown in two places: its home on the Setup tab, and a visit to a Settings
page while that page is on screen (Settings → Audio's Your mic).

The card itself moves, so both places show the same live widgets (its status, its
level meter, its buttons) and nothing has to be kept in step with a copy. It's back
home whenever the visit isn't on show: Settings closed or another of its pages picked
(Settings is only ever freed once it's closed, so never with the card in it)."""
from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from soundboard.ui.window.responsive import touch


class CardHome(QWidget):
    """The card's place on the Setup tab: the Setup layouts hold this, never the card,
    so placing Setup's columns never takes the card back while it's visiting."""

    def __init__(self, card: QWidget, parent: QWidget | None = None):
        super().__init__(parent)
        self.card = card
        # its heading, as Setup's other cards have (card(): lined up with theirs)
        self.heading_title = getattr(card, "heading_title", None)
        self.heading_marks = getattr(card, "heading_marks", ())
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.addWidget(card)

    def take_back(self):
        if self.card.parentWidget() is not self:
            self._lay.addWidget(self.card)
            self.card.show()
            touch(self.card)


class CardVisit(QWidget):
    """Where the card shows on another page, while that page is on screen."""

    def __init__(self, home: CardHome, parent: QWidget | None = None):
        super().__init__(parent)
        self.home = home
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)

    def borrow(self):
        card = self.home.card
        if card.parentWidget() is not self:
            self._lay.addWidget(card)
            card.show()
            touch(card)

    def showEvent(self, e):
        super().showEvent(e)
        if not e.spontaneous():   # (not the window coming back from minimised)
            self.borrow()

    def hideEvent(self, e):
        if not e.spontaneous():
            self.home.take_back()
        super().hideEvent(e)

    def sizeHint(self):
        # empty while the card is home: as big as the card, so the page doesn't jump
        # when it arrives
        return self.home.card.sizeHint() if self.home.card.parentWidget() is not self \
            else super().sizeHint()
