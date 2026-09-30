"""Hoot, Onion Watch's mascot: a cartoon owl (owls keep watch), drawn with QPainter
in the same style as Bun, so it's crisp at any size and needs no image files. The
Triggers tab shows Hoot until the Onion Watch add-on is installed (a copy of
onionwatch/owl.py from the Onion Watch project: the tab needs it before there's
any Onion Watch to take it from).

    owl_image(160)   # QImage, transparent background
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen

# drawn on a 100 x 120 canvas, scaled to the requested height
W, H = 100.0, 120.0
INK = QColor("#2b2340")
FEATHER = QColor("#4fc3b0")
FEATHER_DARK = QColor("#2f9c8c")
BELLY = QColor("#f4efe6")
BELLY_MARK = QColor("#d9cfbf")
BEAK = QColor("#ffb347")
EYE_RING = QColor("#fff6d8")
CHEEK = QColor(255, 128, 160, 110)


def _e(p, cx, cy, w, h, fill, pen=None, angle=0.0):
    p.save()
    p.translate(cx, cy)
    p.rotate(angle)
    p.setPen(pen or Qt.NoPen)
    p.setBrush(fill)
    p.drawEllipse(QRectF(-w / 2, -h / 2, w, h))
    p.restore()


def draw_owl(p: QPainter, rect: QRectF, look: float = 0.0, feather=FEATHER, dark=FEATHER_DARK):
    """`look` -1..1 turns the pupils left / right: watching."""
    s = min(rect.width() / W, rect.height() / H)
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.translate(rect.center().x() - W * s / 2, rect.center().y() - H * s / 2)
    p.scale(s, s)
    ink = QPen(INK, 2.4)
    ink.setJoinStyle(Qt.RoundJoin)
    ink.setCapStyle(Qt.RoundCap)

    # ear tufts
    for sx in (-1, 1):
        tuft = QPainterPath(QPointF(50 + sx * 16, 34))
        tuft.quadTo(QPointF(50 + sx * 30, 22), QPointF(50 + sx * 34, 10))
        tuft.quadTo(QPointF(50 + sx * 36, 30), QPointF(50 + sx * 34, 44))
        tuft.closeSubpath()
        p.setPen(ink)
        p.setBrush(dark)
        p.drawPath(tuft)
    # body (one round egg: owls are all head)
    body = QPainterPath()
    body.addRoundedRect(QRectF(16, 24, 68, 88), 34, 36)
    p.setPen(ink)
    p.setBrush(feather)
    p.drawPath(body)
    # wings
    for sx, ang in ((-1, 12), (1, -12)):
        _e(p, 50 + sx * 33, 80, 16, 38, dark, ink, ang)
    # belly with little feather marks
    _e(p, 50, 88, 42, 40, BELLY)
    p.setPen(QPen(BELLY_MARK, 1.8, Qt.SolidLine, Qt.RoundCap))
    p.setBrush(Qt.NoBrush)
    for x, y in ((42, 80), (50, 84), (58, 80), (46, 92), (54, 92), (50, 100)):
        m = QPainterPath(QPointF(x - 3, y))
        m.quadTo(x, y + 3, x + 3, y)
        p.drawPath(m)
    # feet
    for x in (40, 60):
        p.setPen(ink)
        p.setBrush(BEAK)
        for dx in (-3.5, 0, 3.5):
            _e(p, x + dx, 113, 4.2, 6, BEAK, QPen(INK, 1.6))
    # face disc
    face = QPainterPath(QPointF(50, 40))
    face.cubicTo(QPointF(40, 30), QPointF(18, 34), QPointF(20, 54))
    face.cubicTo(QPointF(22, 70), QPointF(42, 72), QPointF(50, 64))
    face.cubicTo(QPointF(58, 72), QPointF(78, 70), QPointF(80, 54))
    face.cubicTo(QPointF(82, 34), QPointF(60, 30), QPointF(50, 40))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 70))
    p.drawPath(face)
    # the big eyes
    for x in (36, 64):
        _e(p, x, 53, 24, 24, EYE_RING, ink)
        _e(p, x + 3.5 * look, 54, 13, 14, INK)
        _e(p, x + 3.5 * look + 2.2, 50.5, 4.6, 4.8, QColor("white"))
        _e(p, x + 3.5 * look - 2.4, 57.5, 2, 2, QColor("white"))
    _e(p, 25, 68, 10, 6, CHEEK)
    _e(p, 75, 68, 10, 6, CHEEK)
    # beak
    beak = QPainterPath(QPointF(45.5, 62))
    beak.lineTo(54.5, 62)
    beak.quadTo(52, 70, 50, 72)
    beak.quadTo(48, 70, 45.5, 62)
    p.setPen(QPen(INK, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(BEAK)
    p.drawPath(beak)
    p.restore()


def owl_image(height: int, look: float = 0.5) -> QImage:
    h = max(1, height)
    w = max(1, round(h * W / H))
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    draw_owl(p, QRectF(0, 0, w, h), look)
    p.end()
    return img
