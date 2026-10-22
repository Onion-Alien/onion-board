"""The Konami code (↑ ↑ ↓ ↓ ← → ← → B A) typed anywhere in the main window: every
Bun on screen hops and cheers, a toast says he got 30 extra lives, and it's the Old
School achievement. Watched on the window's own native window (winwatch.py), the key
press still goes where it was going; nothing counts while typing in a text box."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QWidget

from soundboard.ui.window import winwatch
from soundboard.ui.window.spacekey import types_text

K = Qt.Key
CODE = (K.Key_Up, K.Key_Up, K.Key_Down, K.Key_Down, K.Key_Left, K.Key_Right, K.Key_Left,
        K.Key_Right, K.Key_B, K.Key_A)


class KonamiCode(QObject):
    """`done()` runs each time the whole code has been typed."""

    def __init__(self, window: QWidget, done: Callable[[], None]):
        super().__init__(window)
        self.window = window
        self.done = done
        self.at = 0   # how much of CODE has been typed
        winwatch.watch(window).add((QEvent.Type.KeyPress,), self._key)

    def _key(self, ev) -> bool:
        if ev.isAutoRepeat():
            return False
        if types_text(self.window.focusWidget()) or ev.modifiers() not in (
                Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier):
            self.at = 0
            return False
        self.press(ev.key())
        return False

    def press(self, key) -> None:
        if key == CODE[self.at]:
            self.at += 1
        else:   # a wrong key; ↑ may still be the start of a new try (↑ ↑ ↑ ↓ …)
            self.at = 2 if key == CODE[0] and self.at == 2 else int(key == CODE[0])
        if self.at == len(CODE):
            self.at = 0
            self.done()


def react(window: QWidget) -> None:
    """What the code does: the achievement, every Bun showing hops and cheers, a toast."""
    from soundboard.core import achievements
    from soundboard.i18n import _
    from soundboard.ui.bun.bunnywidget import BunnyWidget
    achievements.bump("konami")
    line = _("30 extra lives!")
    for bun in window.findChildren(BunnyWidget):
        if bun.isVisible():
            bun.cheer(line)
    toast = getattr(window, "toast", None)
    if toast is not None:
        toast(_("↑ ↑ ↓ ↓ ← → ← → B A: Bun got 30 extra lives."), key="konami")
