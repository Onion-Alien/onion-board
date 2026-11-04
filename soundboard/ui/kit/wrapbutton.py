"""A push button whose words go onto a second line when the room is too narrow for
them on one, instead of making its row wider than the window."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QCheckBox, QLabel, QPushButton, QSizePolicy, QStyle,
                               QStyleOptionButton)


def two_lines(text: str) -> str:
    """``text`` split where its two lines come out most even: at a space, or between
    any two characters of Chinese or Japanese (one word in a language with spaces stays
    whole)."""
    if any(ord(c) >= 0x2E80 for c in text):   # (Latin words among them stay whole)
        parts, sep = re.findall(r"[\u2e80-\U0010ffff]|[^\u2e80-\U0010ffff]+", text), ""
    else:
        parts, sep = text.split(" "), " "
    if len(parts) < 2:
        return text
    best, cut = None, 1
    for i in range(1, len(parts)):
        longer = max(len(sep.join(parts[:i])), len(sep.join(parts[i:])))
        if best is None or longer < best:
            best, cut = longer, i
    return sep.join(parts[:cut]).rstrip() + "\n" + sep.join(parts[cut:]).lstrip()


if TYPE_CHECKING:
    _Base = QPushButton   # (for the checker: each real class below brings its own Qt base)
else:
    _Base = object


class _Wraps(_Base):
    """One line whenever it fits; two when its layout can only give it less (a long
    translation at a narrow window: German's "Star Onion Board on GitHub" pushed
    Settings > About under the scroll bar at 440 px). ``text()`` is the whole label
    on one line."""

    _SIZE = QStyle.ContentsType.CT_PushButton

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full = ""
        policy = self.sizePolicy()
        # a QPushButton's own (Minimum, Fixed) never lets a layout make it narrower
        # than one line, nor taller than one
        policy.setHorizontalPolicy(QSizePolicy.Policy.Preferred)
        policy.setVerticalPolicy(QSizePolicy.Policy.Minimum)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setText(text)

    def text(self) -> str:
        return self._full

    def setText(self, text: str):
        self._full = text
        self._show_fitting()
        self.updateGeometry()

    def _hint_for(self, text: str) -> QSize:
        # what QPushButton.sizeHint works out, for a label it isn't showing yet
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        opt.text = text
        w = h = 0
        if not self.icon().isNull():
            w, h = self.iconSize().width() + 4, self.iconSize().height()
        size = self.fontMetrics().size(Qt.TextFlag.TextShowMnemonic, text or "XXXX")
        w, h = w + size.width(), max(h, size.height())
        opt.rect.setSize(QSize(w, h))
        return self.style().sizeFromContents(self._SIZE, opt, QSize(w, h), self)

    def sizeHint(self) -> QSize:
        return self._hint_for(self._full)

    def minimumSizeHint(self) -> QSize:
        # as narrow as two lines, but only as tall as one: the height comes from
        # heightForWidth, or every button on one line would stand two lines tall
        return QSize(self._hint_for(two_lines(self._full)).width(), self.sizeHint().height())

    def heightForWidth(self, width: int) -> int:
        one = self.sizeHint()
        return (one.height() if width >= one.width()
                else self._hint_for(two_lines(self._full)).height())

    def _show_fitting(self):
        fits = self.width() >= self.sizeHint().width() or not self.isVisible()
        shown = self._full if fits else two_lines(self._full)
        if super().text() != shown:
            super().setText(shown)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._show_fitting()

    def showEvent(self, e):
        super().showEvent(e)
        self._show_fitting()


class WrapLabel(QLabel):
    """Asks for its whole text on one line, and wraps only when the row is too narrow for
    it (a plain wrapping label asks for about half that)."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)

    def sizeHint(self):
        width = self.fontMetrics().horizontalAdvance(self.text()) + 2
        return QSize(width, self.heightForWidth(width))


class WrapButton(_Wraps, QPushButton):
    """A push button that goes onto two lines rather than widen its row."""


class WrapCheck(_Wraps, QCheckBox):
    """A tick box that goes onto two lines rather than widen its row."""

    _SIZE = QStyle.ContentsType.CT_CheckBox
