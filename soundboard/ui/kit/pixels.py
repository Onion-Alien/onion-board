"""Whole-pixel painting at fractional display scales (125 %, 150 %, ...): lives in the
style kit (soundboard/style/appstate.py), which Hoot shares with Onion Watch; the rail's
rings and fills are here."""
import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from soundboard.style.appstate import snap_to_pixels

__all__ = ["draw_ring", "on_pixels", "snap_to_pixels"]


def _round(v: float) -> int:
    return math.floor(v + 0.5)   # Qt rounds halves up (qRound), not to even


def on_pixels(p: QPainter, r: QRectF) -> QRectF:
    """`r` with its edges on the screen pixels Qt keeps for it. At 125 % a widget 39 tall
    can start at pixel 72.5 and end at 121.25: Qt shows rows 73 to 120, so anything drawn
    to its edge loses part of its top or bottom line."""
    t = p.deviceTransform()
    sx, sy = t.m11(), t.m22()
    if not sx or not sy:
        return QRectF(r)
    left, right = (_round(t.dx() + v * sx) for v in (r.left(), r.right()))
    top, bottom = (_round(t.dy() + v * sy) for v in (r.top(), r.bottom()))
    return QRectF((left - t.dx()) / sx, (top - t.dy()) / sy,
                  (right - left) / sx, (bottom - top) / sy)


def draw_ring(p: QPainter, r: QRectF, colour: str, radius: float):
    """A line of whole pixels just inside `r`, as thick on every side."""
    scale = p.deviceTransform().m22() or 1.0
    width = max(1, math.floor(scale + 0.25)) / scale   # (150 %: thin, not 2 px)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(colour), width)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    half = width / 2
    p.drawRoundedRect(on_pixels(p, r).adjusted(half, half, -half, -half), radius, radius)
    p.restore()
