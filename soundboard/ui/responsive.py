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
from contextlib import contextmanager

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QBoxLayout, QLayout, QPushButton, QWidget

from soundboard.ui import icons

Step = tuple[int, str, Callable[[bool], object]]   # (priority, "w" / "h", apply(compact))

MIN_SIZE = QSize(260, 120)   # the mini player (see FitControl._refit)


@contextmanager
def hold_updates(widget: QWidget):
    """Keep nested layout changes inside the caller's paint transaction."""
    enabled = widget.updatesEnabled()
    if enabled:
        widget.setUpdatesEnabled(False)
    try:
        yield
    finally:
        if enabled:
            # Commit the visible layout before painting resumes. Hidden pages
            # must keep their deferred layout until they are shown.
            layout = widget.layout()
            if layout is not None:
                layout.activate()
            widget.setUpdatesEnabled(True)


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
    """A layout and the rows / columns nested in it (each caches its own size).

    The nested ones are found as the layout's children, never with itemAt(): that
    gives each item a Python wrapper the layout keeps, and a page removed from a
    QStackedWidget (Radio switched off) frees its item behind PySide's back. The next
    object made at that address then got the dead wrapper: a native crash."""
    layout.invalidate()
    for sub in layout.findChildren(QLayout):
        sub.invalidate()


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
        icons.text_gap(button)
        touch(button)
    return apply


def stack(layout: QBoxLayout) -> Callable[[bool], None]:
    """Side-by-side columns become one column."""
    def apply(compact: bool):
        layout.setDirection(QBoxLayout.Direction.TopToBottom if compact
                            else QBoxLayout.Direction.LeftToRight)
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
        # applied step index -> the (width, height) it was applied at, and whether it
        # went for the other axis' sake (the diagonal pass in fit)
        self._at: dict[int, tuple[int, int, bool]] = {}
        # while fit() runs: the root's layouts (found once, not on every measure) and
        # the last need() (good until a step is applied or undone)
        self._layouts: list[QLayout] | None = None
        self._known: QSize | None = None
        # the window's edge is being dragged (FitControl.live): need() trusts the sizes
        # Qt has cached, a step's touch() having dropped those it changed. Walking and
        # invalidating every layout made Qt measure the whole window again on each
        # mouse move; a fit with live off, on release, measures it all fresh
        self.live = False

    def add(self, priority: int, axis: str, apply: Callable[[bool], object]):
        self.reset()
        self.steps.append((priority, axis, apply))
        self.steps.sort(key=lambda s: s[0])   # stable: same priority keeps its order

    def extend(self, steps: list[Step]):
        for s in steps:
            self.add(*s)

    def remove(self, steps: list[Step]):
        """Drop steps (by their apply function), e.g. those of a panel being replaced.
        Everything is undone first, so call it while the old panel still exists."""
        gone = {id(s[2]) for s in steps}
        self.reset()
        self.steps = [s for s in self.steps if id(s[2]) not in gone]

    def retry(self, steps: list[Step]):
        """Undo these steps (by their apply function) if they're applied, so the next
        fit() applies them again only if they're still needed: for a part whose own
        size changed without the window's (the download bar showing a longer list)."""
        again = {id(s[2]) for s in steps}
        for i in sorted(self._at, reverse=True):
            if id(self.steps[i][2]) in again:
                self.steps[i][2](False)
                del self._at[i]
        self._known = None

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
        mini player. ~250 layouts: well under a millisecond, but fit() used to
        measure 5-6 times a resize step; inside it, it's measured again only after a
        step changed something."""
        if self._known is not None:
            return QSize(self._known)
        if not self.live:
            for lay in (self._layouts if self._layouts is not None
                        else self.root.findChildren(QLayout)):
                lay.invalidate()
        need = self.root.minimumSizeHint()
        if self._layouts is not None:
            self._known = QSize(need)
        return need

    def _over(self, size: QSize, axis: str) -> bool:
        need = self.need()
        return (need.width() > size.width() if axis == "w"
                else need.height() > size.height())

    def _apply(self, i: int, on: bool):
        self.steps[i][2](on)
        self._known = None   # measure again

    def _fits(self, size: QSize) -> bool:
        return not (self._over(size, "w") or self._over(size, "h"))

    def _give_back(self, new: list[int], size: QSize):
        """Undo the steps in `new` (applied in that order, until it fit) that weren't
        needed after all, last first. Steps go in order until one fits, and the ones
        before it may not have narrowed the widest part: at 1100 px the levels strip
        was it, and the speed button, the radio's volume and Say's Stop went first for
        nothing, staying hidden until the window grew past 1100."""
        for i in reversed(new[:-1]):
            self._apply(i, False)
            if self._fits(size):
                del self._at[i]
            else:
                self._apply(i, True)

    def fit(self, size: QSize) -> QSize:
        """Apply as few steps as it takes for the content to fit `size`. Returns
        need() for what it left."""
        dim = {"w": size.width(), "h": size.height()}
        # found once for the whole fit, not on each need(): with a few hundred pads the
        # search through every widget took longer than the measuring (a step only
        # shows, hides or retitles things, so the layouts stay the same meanwhile)
        self._layouts = [] if self.live else self.root.findChildren(QLayout)
        self._known = None
        with hold_updates(self.root):
            new: list[int] = []   # applied by this fit
            for axis in ("h", "w"):   # hiding the mixer (height) narrows the window too
                for i, (_, ax, _fn) in enumerate(self.steps):
                    if ax != axis or i in self._at:
                        continue
                    if not self._over(size, axis):
                        break
                    self._apply(i, True)
                    self._at[i] = (dim["w"], dim["h"], False)
                    new.append(i)
            # still over (a diagonal drag): the other axis' steps can help too (hiding
            # the mixer narrows the window), so try them before anyone calls it too small
            for i in range(len(self.steps)):
                if self._fits(size):
                    break
                if i not in self._at:
                    self._apply(i, True)
                    self._at[i] = (dim["w"], dim["h"], True)
                    new.append(i)
            self._give_back(new, size)
            for axis in ("w", "h"):   # grown: bring back what fits again, last-hidden first
                for i in sorted((i for i in self._at if self.steps[i][1] == axis),
                                reverse=True):
                    if i not in self._at:
                        continue   # given back meanwhile
                    w, h, cross = self._at[i]
                    grown = dim[axis] > (w if axis == "w" else h)
                    if cross:   # hidden for the other axis: that one growing counts too
                        grown = grown or (dim["h"] > h if axis == "w" else dim["w"] > w)
                    if not grown:
                        continue   # no bigger than when it had to go
                    self._apply(i, False)
                    if self._fits(size):
                        del self._at[i]
                        continue
                    # still too big: the steps that go before it make room first
                    room = []
                    for j in range(i):
                        if self._fits(size):
                            break
                        if j not in self._at and self.steps[j][1] == axis:
                            self._apply(j, True)
                            self._at[j] = (dim["w"], dim["h"], False)
                            room.append(j)
                    if self._fits(size):
                        del self._at[i]
                        self._give_back(room, size)
                        continue
                    # no room yet: try it again once the window is as big as it needs
                    # with them out of the way, not on every pixel of a drag. The others
                    # go on: one in another row may fit
                    need = self.need()
                    for j in reversed(room):
                        self._apply(j, False)
                        del self._at[j]
                    self._apply(i, True)
                    self._at[i] = (max(dim["w"], need.width() - 1),
                                   max(dim["h"], need.height() - 1), cross)
        try:
            return self.need()
        finally:
            self._layouts = self._known = None

    def compact_count(self) -> int:
        return len(self._at)
