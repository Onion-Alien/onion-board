"""A push button whose words go onto a second line when the room is too narrow for
them on one, instead of making its row wider than the window."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QPushButton, QSizePolicy, QStyle, QStyleOptionButton


def two_lines(text: str) -> str:
    """``text`` split where its two lines come out most even: at a space, or between
    any two characters when it has none and is Chinese or Japanese (one word in a
    language with spaces stays whole)."""
    words = text.split(" ")
    if len(words) > 1:
        parts, sep = words, " "
    elif any(ord(c) >= 0x2E80 for c in text):
        parts, sep = list(text), ""
    else:
        return text
    if len(parts) < 2:
        return text
    best, cut = None, 1
    for i in range(1, len(parts)):
        longer = max(len(sep.join(parts[:i])), len(sep.join(parts[i:])))
        if best is None or longer < best:
            best, cut = longer, i
    return sep.join(parts[:cut]) + "\n" + sep.join(parts[cut:])


class WrapButton(QPushButton):
    """One line whenever it fits; two when its layout can only give it less (a long
    translation at a narrow window: German's "Star Onion Board on GitHub" pushed
    Settings > About under the scroll bar at 440 px). ``text()`` is the whole label
    on one line."""

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
        return self.style().sizeFromContents(QStyle.ContentsType.CT_PushButton, opt,
                                             QSize(w, h), self)

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
