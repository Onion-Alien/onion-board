"""The small painting helpers Bun (ui/bun/bunny.py) is drawn with: ellipses, ovals,
glows, shading, strokes, arcs and beans, his paw pads, navel and fluff."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QRadialGradient, QTransform



def _ellipse(p: QPainter, cx, cy, w, h, fill, pen: QPen | None = None, angle=0.0):
    p.save()
    p.translate(cx, cy)
    p.rotate(angle)
    p.setPen(pen or Qt.PenStyle.NoPen)
    p.setBrush(fill)
    p.drawEllipse(QRectF(-w / 2, -h / 2, w, h))
    p.restore()


def _oval(x, y, w, h) -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(QRectF(x - w / 2, y - h / 2, w, h))
    return path


def _glow(p: QPainter, x, y, w, h, col: QColor):
    """A soft oval spot (a blush, a shine): `col` in the middle, fading out to nothing
    at its w x h edge."""
    g = QRadialGradient(QPointF(0, 0), w / 2)
    g.setColorAt(0.0, col)
    g.setColorAt(0.5, col)
    edge = QColor(col)
    edge.setAlpha(0)
    g.setColorAt(1.0, edge)
    p.save()
    p.translate(x, y)
    p.scale(1, h / w)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawEllipse(QPointF(0, 0), w / 2, w / 2)
    p.restore()


def _shade(p: QPainter, shape: QPainterPath, x, y, r, col: QColor, alpha: int):
    """A soft round shade inside `shape`, darkest at x, y and gone `r` away."""
    c = QColor(col)
    c.setAlpha(alpha)
    edge = QColor(col)
    edge.setAlpha(0)
    g = QRadialGradient(QPointF(x, y), r)
    g.setColorAt(0.0, c)
    g.setColorAt(1.0, edge)
    p.save()
    p.setClipPath(shape)
    p.fillRect(QRectF(x - r, y - r, 2 * r, 2 * r), g)
    p.restore()


def _smooth(k: float) -> float:
    k = max(0.0, min(1.0, k))
    return k * k * (3 - 2 * k)


def _stroke(p: QPainter, path: QPainterPath, col: QColor, width: float):
    p.setPen(QPen(col, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)


def _arc(x0, y0, cx, cy, x1, y1) -> QPainterPath:
    path = QPainterPath(QPointF(x0, y0))
    path.quadTo(QPointF(cx, cy), QPointF(x1, y1))
    return path


def _lerp(a, b, k):
    return tuple(x0 + (x1 - x0) * k for x0, x1 in zip(a, b))


def _bean(x, y, w, h, lean) -> QPainterPath:
    """A paw: a soft bean, rounder at the bottom (its toes), leaning `lean` degrees."""
    path = QPainterPath(QPointF(0, -h / 2))
    path.cubicTo(QPointF(w * 0.42, -h / 2), QPointF(w / 2, -h * 0.05), QPointF(w / 2, h * 0.12))
    path.cubicTo(QPointF(w / 2, h * 0.38), QPointF(w * 0.3, h / 2), QPointF(0, h / 2))
    path.cubicTo(QPointF(-w * 0.3, h / 2), QPointF(-w / 2, h * 0.38), QPointF(-w / 2, h * 0.12))
    path.cubicTo(QPointF(-w / 2, -h * 0.05), QPointF(-w * 0.42, -h / 2), QPointF(0, -h / 2))
    path.closeSubpath()
    return QTransform().translate(x, y).rotate(lean).map(path)


def _pads(p: QPainter, col: QColor):
    """Pad prints on the bottom of a foot (its frame, centred): a heart-ish pad and
    four toe beans round its top, plain shapes with no outline."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(col)
    heel = QPainterPath(QPointF(0, -0.4))   # a soft heart-ish main pad, low in the foot
    heel.cubicTo(QPointF(1.6, -1.6), QPointF(4.4, -0.6), QPointF(3.8, 1.6))
    heel.cubicTo(QPointF(3.3, 3.4), QPointF(-3.3, 3.4), QPointF(-3.8, 1.6))
    heel.cubicTo(QPointF(-4.4, -0.6), QPointF(-1.6, -1.6), QPointF(0, -0.4))
    heel.closeSubpath()
    p.drawPath(heel)
    for x, y, a in ((-4.6, -1.0, -28), (-1.6, -2.6, -9), (1.6, -2.6, 9), (4.6, -1.0, 28)):
        _ellipse(p, x, y, 2.3, 2.7, col, None, a)   # four little toe beans round its top
    shine = QColor(255, 255, 255, 120)
    _ellipse(p, -1.4, 0.6, 1.6, 0.9, shine, None, -15)


def _navel(belly: QColor) -> QColor:
    """His belly button: a little curve a shade darker than his tummy patch."""
    col = belly.darker(150)
    col.setAlpha(190)
    return col


def _poof(p: QPainter, fill: QColor):
    """The fluffy poof on his chest, just under his chin: a soft cloud of lighter fur
    ending in little pointed tufts, the longest in the middle (his chin hides its top)."""
    tips = ((38.6, 99.5), (44, 104.2), (50, 106.4), (56, 104.2), (61.4, 99.5))
    dips = ((41.4, 99.6), (47, 102.4), (53, 102.4), (58.6, 99.6))
    path = QPainterPath(QPointF(35.5, 89))
    path.cubicTo(QPointF(35, 94), QPointF(36.5, 97.5), QPointF(*tips[0]))
    for (tx, ty), (vx, vy), (nx, ny) in zip(tips, dips, tips[1:]):
        path.quadTo(QPointF(tx + 1.6, ty - 0.2), QPointF(vx, vy))
        path.quadTo(QPointF(nx - 2.4, ny - 2.4), QPointF(nx, ny))
    path.cubicTo(QPointF(63.5, 97.5), QPointF(65, 94), QPointF(64.5, 89))
    path.quadTo(QPointF(50, 83), QPointF(35.5, 89))
    path.closeSubpath()
    edge = fill.darker(128)
    edge.setAlpha(230)
    p.save()
    p.setPen(QPen(edge, 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    p.setBrush(fill)
    p.drawPath(path)
    p.restore()
