"""Keeps the main window usable at any size, down to about 300 x 300.

Each part of the window registers "steps": a way to make itself smaller (hide a
label, drop a button's text, stack two columns) with a priority. On every resize
all steps are undone, then applied in priority order, lowest first, only while
the window's content still doesn't fit. So a big window shows everything, and a
small one keeps the controls that matter most (pads, play / stop, the radio's
LIVE button, the mic's send box) and hides the rest.

Only register widgets whose visibility nothing else manages: undoing a step shows
them again.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QBoxLayout, QPushButton, QWidget

Step = tuple[int, str, Callable[[bool], None]]   # (priority, "w" / "h", apply(compact))

MIN_SIZE = QSize(300, 300)


def touch(*widgets: QWidget):
    """Mark every layout above `widgets` as stale. Qt does this itself for widgets
    on screen, but not for ones on a tab that isn't showing, and the tab widget's
    minimum size counts every tab."""
    for w in widgets:
        p = w.parentWidget()
        while p is not None:
            if p.layout() is not None:
                _invalidate(p.layout())
            p.updateGeometry()   # drops the size its parent's layout cached for it
            p = p.parentWidget()


def _invalidate(layout):
    """A layout and the rows / columns nested in it (each caches its own size)."""
    layout.invalidate()
    for i in range(layout.count()):
        sub = layout.itemAt(i).layout()
        if sub is not None:
            _invalidate(sub)


def hide(*widgets: QWidget) -> Callable[[bool], None]:
    def apply(compact: bool):
        for w in widgets:
            w.setVisible(not compact)
        touch(*widgets)
    return apply


def icon_only(button: QPushButton) -> Callable[[bool], None]:
    """Drop a button's text but keep its icon (its tooltip still explains it).

    The full text is kept in the "full_text" property, read back when it grows again,
    so a label the app changes meanwhile (set that property too) isn't lost."""
    def apply(compact: bool):
        if compact:
            if button.text():
                button.setProperty("full_text", button.text())
            button.setText("")
        elif not button.text() and button.property("full_text"):
            button.setText(button.property("full_text"))
        touch(button)
    return apply


def stack(layout: QBoxLayout) -> Callable[[bool], None]:
    """Side-by-side columns become one column."""
    def apply(compact: bool):
        layout.setDirection(QBoxLayout.TopToBottom if compact else QBoxLayout.LeftToRight)
    return apply


class Fitter:
    def __init__(self, root: QWidget):
        self.root = root
        self.steps: list[Step] = []
        self._applied: tuple[bool, ...] = ()

    def add(self, priority: int, axis: str, apply: Callable[[bool], None]):
        self.steps.append((priority, axis, apply))
        self.steps.sort(key=lambda s: s[0])   # stable: same priority keeps its order

    def extend(self, steps: list[Step]):
        for s in steps:
            self.add(*s)

    def fit(self, size: QSize):
        """Apply as few steps as it takes for the content to fit `size`."""
        self.root.setUpdatesEnabled(False)
        try:
            for _, _, apply in self.steps:
                apply(False)
            applied = []
            for _, axis, apply in self.steps:
                need = self.root.minimumSizeHint()
                over = (need.width() > size.width() if axis == "w"
                        else need.height() > size.height())
                if over:
                    apply(True)
                applied.append(over)
            self._applied = tuple(applied)
        finally:
            self.root.setUpdatesEnabled(True)

    def compact_count(self) -> int:
        return sum(self._applied)
