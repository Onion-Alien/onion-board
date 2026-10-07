"""Space plays and pauses, like a media player, on the tabs that play things (Sounds
and Radio), wherever the focus is: after clicking a result's Play, a slider or a
station, Space used to click that button again (downloading the song again) or do
nothing, instead of pausing.

It steps aside where Space means something else: typing in a text box, a pad or a
search result (they pause / play themselves), and a button or check box reached
with Tab, where Space is how the keyboard presses it."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (QAbstractButton, QAbstractSpinBox, QApplication, QComboBox,
                               QLineEdit, QPlainTextEdit, QTextEdit, QWidget)

KEYBOARD_FOCUS = (Qt.TabFocusReason, Qt.BacktabFocusReason)


def types_text(w: QWidget) -> bool:
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
    """Installed on the application. `action()` gives what Space does right now (a
    callable, or None to leave Space alone: another tab, a dialog in front);
    `window` is the main window, so other windows keep their Space."""

    def __init__(self, window: QWidget, action: Callable[[], Callable[[], None] | None]):
        super().__init__(window)
        self.window = window
        self.action = action
        self._kbd: QWidget | None = None   # the widget the keyboard last moved focus to

    def eventFilter(self, obj, ev) -> bool:
        t = ev.type()
        if t == QEvent.FocusIn:
            self._kbd = obj if ev.reason() in KEYBOARD_FOCUS else None
            return False
        if t != QEvent.KeyPress or ev.key() != Qt.Key_Space or ev.modifiers() not in (
                Qt.NoModifier, Qt.KeypadModifier):
            return False
        fw = QApplication.focusWidget()
        # the key goes to the focus widget first, then up to its parents: act once
        target = fw if fw is not None else obj
        if obj is not target or not isinstance(obj, QWidget) or obj.window() is not self.window:
            return False
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
