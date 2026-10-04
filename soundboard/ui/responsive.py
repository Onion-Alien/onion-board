"""Keeps the main window usable at any size, down to where it becomes the mini player.

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
from PySide6.QtWidgets import QBoxLayout, QLayout, QPushButton, QWidget

Step = tuple[int, str, Callable[[bool], None]]   # (priority, "w" / "h", apply(compact))

MIN_SIZE = QSize(260, 120)   # the mini player (see MainWindow._refit)


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


class FitWidth(QWidget):
    """What a scroll area holds when its content fits itself to the width it's given
    (rows that tighten, tiles that re-flow): it's never wider than the scroll area,
    so the content gets that width instead of running off the edge. Pair it with
    the scroll area's horizontal bar off."""

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())

    def sizeHint(self):
        return QSize(0, super().sizeHint().height())


class Fitter:
    """Steps are applied lowest priority first, per axis, and undone in reverse.

    Incremental: a resize only touches the steps at the edge it crossed, so dragging
    the window's border doesn't show and hide every registered widget on each mouse
    move (that made parts of the window flash in two places while resizing)."""

    def __init__(self, root: QWidget):
        self.root = root
        self.steps: list[Step] = []
        self._at: dict[int, int] = {}   # applied step index -> the size it was applied at

    def add(self, priority: int, axis: str, apply: Callable[[bool], None]):
        self.reset()
        self.steps.append((priority, axis, apply))
        self.steps.sort(key=lambda s: s[0])   # stable: same priority keeps its order

    def extend(self, steps: list[Step]):
        for s in steps:
            self.add(*s)

    def reset(self):
        """Undo every step (everything shows again)."""
        for i in sorted(self._at, reverse=True):
            self.steps[i][2](False)
        self._at.clear()

    def need(self) -> QSize:
        """The smallest size the root's content fits now, measured fresh: a step that
        changed a text deep in a row (the status pill getting its long words back)
        left a nested layout's cached size behind, so growing 640 -> 900 px wide with
        search results brought back more than fits and the main window fell into the
        mini player. ~250 layouts: well under a millisecond."""
        for lay in self.root.findChildren(QLayout):
            lay.invalidate()
        return self.root.minimumSizeHint()

    def _over(self, size: QSize, axis: str) -> bool:
        need = self.need()
        return (need.width() > size.width() if axis == "w"
                else need.height() > size.height())

    def fit(self, size: QSize):
        """Apply as few steps as it takes for the content to fit `size`."""
        dim = {"w": size.width(), "h": size.height()}
        self.root.setUpdatesEnabled(False)
        try:
            for axis in ("h", "w"):   # hiding the mixer (height) narrows the window too
                for i, (_, ax, apply) in enumerate(self.steps):
                    if ax != axis or i in self._at:
                        continue
                    if not self._over(size, axis):
                        break
                    apply(True)
                    self._at[i] = dim[axis]
            # still over (a diagonal drag): the other axis' steps can help too (hiding
            # the mixer narrows the window), so try them before anyone calls it too small
            for i, (_, ax, apply) in enumerate(self.steps):
                if not (self._over(size, "w") or self._over(size, "h")):
                    break
                if i not in self._at:
                    apply(True)
                    self._at[i] = dim[ax]
            for axis in ("w", "h"):   # grown: bring back what fits again, last-hidden first
                for i in sorted((i for i in self._at if self.steps[i][1] == axis),
                                reverse=True):
                    if dim[axis] <= self._at[i]:
                        break   # no bigger than when it had to go
                    self.steps[i][2](False)
                    if self._over(size, "w") or self._over(size, "h"):
                        self.steps[i][2](True)
                        self._at[i] = dim[axis]
                        break
                    del self._at[i]
        finally:
            self.root.setUpdatesEnabled(True)

    def compact_count(self) -> int:
        return len(self._at)
