"""The mouse's back side button (Mouse 4, back in a browser) presses the Back button of
the page you're on: Free sound packs, Settings, search results, the setup guide. A
button takes part with `mark(button)`; a page without one ignores the press.

Watched on the window's own native window (winwatch.py). Some mouse software sends the
button as the keyboard's Back key instead, so that counts too; one press that arrives
as both goes back once (SAME_PRESS_MS)."""
from __future__ import annotations

import time

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import QAbstractButton, QWidget

from soundboard.ui.window import winwatch

PROP = "mouse_back"
SAME_PRESS_MS = 250


def mark(button: QAbstractButton) -> QAbstractButton:
    """`button` is its page's Back: the mouse's back button presses it."""
    button.setProperty(PROP, True)
    return button


def back_button(under: QWidget | None, window: QWidget) -> QAbstractButton | None:
    """The shown, enabled Back nearest `under` (the widget under the pointer): its
    own page's first, then the pages around it, up to the window."""
    w = under or window
    while w is not None:
        for b in w.findChildren(QAbstractButton):
            if b.property(PROP) and b.isVisible() and b.isEnabled():
                return b
        if w is window:
            break
        w = w.parentWidget()
    return None


class MouseBack:
    def __init__(self, window: QWidget):
        self.window = window
        self._last = -1e9   # when Back was last pressed this way (time.monotonic, s)
        winwatch.watch(window).add(
            (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress), self._event)

    def _event(self, ev) -> bool:
        if ev.type() == QEvent.Type.KeyPress:
            if ev.key() != Qt.Key.Key_Back:
                return False
            under = self.window.focusWidget()
        else:
            if ev.button() != Qt.MouseButton.BackButton:
                return False
            under = self.window.childAt(self.window.mapFromGlobal(
                ev.globalPosition().toPoint()))
        return self.press(under)

    def press(self, under: QWidget | None) -> bool:
        """Press the Back for `under`; True when there was one to press."""
        now = time.monotonic()
        if (now - self._last) * 1000 < SAME_PRESS_MS:
            return True   # the same press again, as the Back key
        b = back_button(under, self.window)
        if b is None:
            return False
        self._last = now
        # after this press is done with: Back can delete the page it's on
        QTimer.singleShot(0, b, b.click)
        return True
