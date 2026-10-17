"""Sizes worked out from a widget's text, worked out again when its style or font
changes. The window is built with the app's style sheet off (theme.styled_after) and
gets its fonts and padding at the end, so a width or height measured while it's built
would be the plain font's; a theme switch changes them too."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid as qt_valid

_AGAIN = (QEvent.Type.StyleChange, QEvent.Type.FontChange)
_all: list[_Again] = []


class _Again(QObject):
    def __init__(self, w: QWidget, fn: Callable[[], None]):
        super().__init__(w)
        self._fn = fn
        self._busy = False   # fn itself may set a font (steady_number): no loop
        w.installEventFilter(self)
        _all.append(self)

    def run(self):
        if not self._busy:
            self._busy = True
            try:
                self._fn()
            finally:
                self._busy = False

    def eventFilter(self, obj, ev):   # noqa: N802 - Qt API
        if ev.type() in _AGAIN:
            self.run()
        return False


def on_restyle(w: QWidget, fn: Callable[[], None]) -> None:
    """Call `fn` again whenever `w`'s style or font changes (not now)."""
    _Again(w, fn)


def again() -> None:
    """Every measurement again, now. After a whole app's sheet goes on: a widget hears
    StyleChange while Qt is still restyling, and some sizes (a label's padding) are
    only right once it has finished."""
    _all[:] = [a for a in _all if qt_valid(a)]
    for a in list(_all):
        if qt_valid(a):
            a.run()


def measured(w: QWidget, fn: Callable[[], None]) -> None:
    """`fn` now, and again whenever `w`'s style or font changes."""
    fn()
    _Again(w, fn)
