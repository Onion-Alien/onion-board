"""A still of a window over it while the app restyles, faded in and out: switching a
theme, its texture or the highlight colour blends instead of flashing.

Restyling every widget takes a moment (half a second on a full board, seconds on a
busy PC), and a frame painted part way through showed the app half styled. So the
window shows a picture of itself, dimming with the app's mascot in the middle until
the new look is in, then fades to it. The UI thread is about to be busy restyling, so
the fade in is painted by hand, a few frames before the restyle starts; the fade out
is an animation once the event loop is back. A `plain` cover (the highlight colour:
a quick restyle) has no dimming and no mascot, just the blend. The cover is a child
of the window: no window of its own appears.

Part of the style kit (see __init__.py): imports nothing from either app.

    with cover.covered([window], scrim, mascot):   # scrim: the new theme's background
        restyle()
"""
from __future__ import annotations

import time

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

from .appstate import snap_to_pixels

FADE_IN_MS = 100    # the dimming and the mascot come in (painted by hand)...
FADE_IN_STEPS = 4   # ...in this many frames, before the restyle starts
FADE_MS = 260       # then the picture fades to the restyled window
SCRIM_ALPHA = 150   # how far the picture dims (0..255) once it's in


class Cover(QWidget):
    """A picture of `window` over it: `scrim` (dimming) and `mascot` (a picture in the
    middle) fade in with cover(); uncover() fades it all to what's under it. Both
    None: a plain blend."""

    def __init__(self, window: QWidget, scrim: QColor | None = None,
                 mascot: QPixmap | None = None):
        super().__init__(window)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setGeometry(window.rect())
        self.still: QPixmap = window.grab()
        self.scrim = QColor(scrim) if scrim is not None else None
        if self.scrim is not None:
            self.scrim.setAlpha(SCRIM_ALPHA)
        self.mascot = mascot
        self.k = 0.0        # 0..1, how far the dimming and the mascot are in
        self._fade: QPropertyAnimation | None = None

    def paintEvent(self, _e):
        p = QPainter(self)
        # opaque: the full picture goes down before snap_to_pixels, or its nudge leaves
        # an edge row of whatever was on screen before
        p.drawPixmap(self.rect(), self.still)
        if self.k > 0 and self.scrim is not None:
            c = QColor(self.scrim)
            c.setAlpha(round(self.scrim.alpha() * self.k))
            p.fillRect(self.rect(), c)
        snap_to_pixels(p)
        if self.k > 0 and self.mascot is not None and not self.mascot.isNull():
            size = self.mascot.deviceIndependentSize()
            at = QRectF((self.width() - size.width()) / 2,
                        (self.height() - size.height()) / 2, size.width(), size.height())
            p.setOpacity(self.k)
            p.drawPixmap(at, self.mascot, QRectF(self.mascot.rect()))
        p.end()

    def cover(self):
        """Up on screen now, and faded in, before the UI thread gets busy restyling.
        The picture is the window as it is: going up changes nothing on screen."""
        _fade_in([self])

    def uncover(self):
        """Fade to the restyled window, then go."""
        self.raise_()
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        fade = self._fade = QPropertyAnimation(effect, b"opacity", self)
        fade.setDuration(FADE_MS)
        fade.setStartValue(1.0)
        fade.setEndValue(0.0)
        fade.setEasingCurve(QEasingCurve.Type.InOutQuad)
        fade.finished.connect(self.deleteLater)
        fade.start()


def _fade_in(covers: list[Cover]):
    """Put `covers` up (each its window as it is: nothing changes on screen), then
    fade their dimming and mascots in together, a frame at a time."""
    for c in covers:
        c.raise_()
        c.show()
        c.repaint()
    dims = [c for c in covers if c.scrim is not None or c.mascot is not None]
    if not dims:
        return
    for i in range(1, FADE_IN_STEPS + 1):
        time.sleep(FADE_IN_MS / 1000 / FADE_IN_STEPS)
        k = i / FADE_IN_STEPS
        for c in dims:
            c.k = k * k * (3 - 2 * k)
            c.repaint()


def on_screen(w: QWidget) -> bool:
    return w.isVisible() and not w.isMinimized()


class covered:
    """Covers over `windows` (those on screen) for a `with` block. `make(window)` gives
    each one's Cover (default: a plain blend). A quick second switch: the covers
    still fading go first, or a picture taken through one would show the look before
    that one."""

    def __init__(self, windows, make=None):
        direct = Qt.FindChildOption.FindDirectChildrenOnly
        self.covers: list[Cover] = []
        for w in windows:
            for old in w.findChildren(Cover, options=direct):
                old.hide()
                old.deleteLater()
        for w in windows:
            if on_screen(w):
                self.covers.append(make(w) if make is not None else Cover(w))

    def __enter__(self):
        _fade_in(self.covers)
        return self.covers

    def __exit__(self, *_exc):
        for c in self.covers:
            c.uncover()
        return False
