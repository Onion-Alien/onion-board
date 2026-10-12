"""Whole-pixel painting at fractional display scales (125 %, 150 %, ...).

At those scales a widget often starts between two screen pixels (x = 10 at 125 %
is pixel 12.5). Qt keeps the widget to the whole pixels from 13, but paints it from
12.5, so the left or top half pixel of anything drawn to its edge is lost: a round
button came out flat on its left. Moving the painter by that leftover half pixel
puts the drawing on the pixels Qt keeps."""
import math

from PySide6.QtGui import QPainter


def snap_to_pixels(p: QPainter):
    """Shift `p` (fresh from QPainter(widget)) so the widget's edge is a whole pixel.
    A no-op at 100 % and 200 %, and on pictures (grab) that start on one already."""
    t = p.deviceTransform()
    if not t.m11() or not t.m22():
        return
    dx = math.floor(t.dx() + 0.5) - t.dx()   # Qt rounds halves up (qRound), not to even
    dy = math.floor(t.dy() + 0.5) - t.dy()
    if dx or dy:
        p.translate(dx / t.m11(), dy / t.m22())
