"""Space plays and pauses, like a media player, on the tabs that play things (Sounds
and Radio), wherever the focus is: after clicking a result's Play, a slider or a
station, Space used to click that button again (downloading the song again) or do
nothing, instead of pausing.

It steps aside where Space means something else: typing in a text box, a pad or a
search result (they pause / play themselves), and a button or check box reached
with Tab, where Space is how the keyboard presses it."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import (QAbstractButton, QAbstractSpinBox, QApplication, QComboBox,
                               QLineEdit, QPlainTextEdit, QTextEdit, QWidget)

from soundboard.ui.window import winwatch

def types_text(w: QWidget | None) -> bool:
    """Space types a space here."""
    if isinstance(w, (QLineEdit, QAbstractSpinBox)):
        return True
    if isinstance(w, (QTextEdit, QPlainTextEdit)):
        return not w.isReadOnly()
    return isinstance(w, QComboBox) and w.isEditable()


def handles_space(w: QWidget | None) -> bool:
    """`w` or a parent of it has its own Space (a pad, a search result): its
    `own_space` property."""
    while w is not None:
        if w.property("own_space"):
            return True
        w = w.parentWidget()
    return False


class SpaceKey(QObject):
    """On the main window's own native window (winwatch.py), so other windows keep
    their Space. `action()` gives what Space does right now (a callable, or None to
    leave Space alone: another tab, a dialog in front)."""

    def __init__(self, window: QWidget, action: Callable[[], Callable[[], None] | None]):
        super().__init__(window)
        self.window = window
        self.action = action
        self._kbd: QWidget | None = None   # the widget the keyboard last moved focus to
        self._tabbing = False              # a Tab press is moving the focus right now
        app = QApplication.instance()
        assert isinstance(app, QApplication)
        app.focusChanged.connect(self._focus_moved)
        winwatch.watch(window).add((QEvent.Type.KeyPress,), self._key)

    def _focus_moved(self, _old, new) -> None:
        # Qt's own Tab handling moves the focus inside the key press (a FocusIn with
        # TabFocusReason); anything else (a click, the window coming back) doesn't count
        self._kbd = new if self._tabbing else None

    def _done_tabbing(self) -> None:
        self._tabbing = False

    def _key(self, ev) -> bool:
        key = ev.key()
        if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            self._tabbing = True   # until this press has been handled
            QTimer.singleShot(0, self, self._done_tabbing)
            return False
        if key != Qt.Key.Key_Space or ev.modifiers() not in (
                Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier):
            return False
        fw = self.window.focusWidget()   # where the window hands the key
        if types_text(fw) or handles_space(fw):
            return False
        if isinstance(fw, QAbstractButton) and fw is self._kbd:
            return False   # reached with Tab: Space presses it, as everywhere
        do = self.action()
        if do is None:
            return False
        if not ev.isAutoRepeat():   # held down: once, not on and off
            do()
        return True
