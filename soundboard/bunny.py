"""Bun, the mascot: a cartoon bunny in gaming headphones, drawn with QPainter so it's
crisp at any size and needs no image files. Used by the quick-setup guide (a
different prop on each page) and by make_bunny.py for the installer's artwork.

    bunny_image(160, prop="mic")   # QImage, transparent background
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap

# drawn on a 100 x 120 canvas, scaled to the requested height
W, H = 100.0, 120.0

FUR = QColor("#fbf7f2")
FUR_SHADE = QColor("#ece3da")
INK = QColor("#2b2340")
PINK = QColor("#ffb3c7")
CHEEK = QColor(255, 128, 160, 110)
PHONES = QColor("#7c5cff")       # the app's accent purple
PHONES_HI = QColor("#a48bff")

PROPS = (None, "mic", "headphones", "plug", "star", "hammer")
WOOD = QColor("#c98a4b")
WOOD_DARK = QColor("#9a6532")
STEEL = QColor("#9aa0b4")


def _ellipse(p: QPainter, cx, cy, w, h, fill: QColor, pen: QPen | None = None, angle=0.0):
    p.save()
    p.translate(cx, cy)
    p.rotate(angle)
    p.setPen(pen or Qt.NoPen)
    p.setBrush(fill)
    p.drawEllipse(QRectF(-w / 2, -h / 2, w, h))
    p.restore()


def draw_bunny(p: QPainter, rect: QRectF, prop: str | None = None, *,
               blink: float = 0.0, mouth: float = 0.0, ears: float = 0.0,
               swing: float = 0.0):
    """Draw Bun fitted (aspect kept, centred) into `rect`. The keywords pose Bun for
    animation (ui/bunnywidget.py): `blink` 0..1 closes the eyes, `mouth` 0..1 opens
    the mouth (talking), `ears` tilts both ears outward by that many degrees, and
    `swing` 0..1 brings the hammer down (0 = raised, 1 = striking the plank)."""
    s = min(rect.width() / W, rect.height() / H)
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.translate(rect.center().x() - W * s / 2, rect.center().y() - H * s / 2)
    p.scale(s, s)
    ink = QPen(INK, 2.4)
    ink.setJoinStyle(Qt.RoundJoin)
    ink.setCapStyle(Qt.RoundCap)

    # ears (behind the head): the right one flops a little for character
    for bx, cx, cy, h, a, tilt in ((36, 36, 26, 50, -10, -ears), (64, 66, 28, 48, 18, ears)):
        p.save()
        p.translate(bx, 48)   # pivot at the base of the ear, where it meets the head
        p.rotate(tilt)
        p.translate(-bx, -48)
        _ellipse(p, cx, cy, 19, h, FUR, ink, a)
        _ellipse(p, cx, cy + 2, 9, h - 14, PINK, None, a)
        p.restore()

    # body, feet, head
    _ellipse(p, 50, 100, 50, 36, FUR, ink)
    _ellipse(p, 50, 104, 30, 22, FUR_SHADE)
    _ellipse(p, 37, 116, 16, 8, FUR, ink)
    _ellipse(p, 63, 116, 16, 8, FUR, ink)
    _ellipse(p, 50, 64, 68, 56, FUR, ink)

    # headphones: band over the head, cups on the sides
    band = QPainterPath(QPointF(17, 64))
    band.cubicTo(QPointF(15, 26), QPointF(85, 26), QPointF(83, 64))
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(INK, 8.5, Qt.SolidLine, Qt.RoundCap))
    p.drawPath(band)
    p.setPen(QPen(PHONES, 5, Qt.SolidLine, Qt.RoundCap))
    p.drawPath(band)
    for x in (10, 80):
        p.setPen(ink)
        p.setBrush(PHONES)
        p.drawRoundedRect(QRectF(x, 54, 11, 22), 5, 5)
        p.setPen(Qt.NoPen)
        p.setBrush(PHONES_HI)
        p.drawRoundedRect(QRectF(x + 2.5, 57, 3, 10), 1.5, 1.5)

    # face
    for x in (39, 61):
        if blink > 0.6:       # shut: a happy little arc
            arc = QPainterPath(QPointF(x - 4.5, 62))
            arc.quadTo(x, 65.5, x + 4.5, 62)
            p.setPen(QPen(INK, 2.2, Qt.SolidLine, Qt.RoundCap))
            p.setBrush(Qt.NoBrush)
            p.drawPath(arc)
            continue
        _ellipse(p, x, 62, 9, 11.5 * (1 - blink), INK)
        _ellipse(p, x + 1.6, 59, 3.4, 3.8, QColor("white"))
        _ellipse(p, x - 1.6, 65.5, 1.6, 1.6, QColor("white"))
    _ellipse(p, 30, 72, 11, 6.5, CHEEK)
    _ellipse(p, 70, 72, 11, 6.5, CHEEK)
    nose = QPainterPath(QPointF(46.5, 69))
    nose.lineTo(53.5, 69)
    nose.quadTo(50, 74, 50, 74)
    nose.closeSubpath()
    p.setPen(QPen(QColor("#e0708f"), 1.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(QColor("#ff8fae"))
    p.drawPath(nose)
    if mouth > 0.08:          # open, as if talking
        oh = 2.5 + 6.5 * min(1.0, mouth)
        _ellipse(p, 50, 76 + oh / 2, 7 + 2 * mouth, oh, QColor("#5a2238"), QPen(INK, 1.6))
        _ellipse(p, 50, 76 + oh * 0.78, 4.5, oh * 0.4, QColor("#ff8fae"))
    else:
        path = QPainterPath(QPointF(44, 75))
        path.quadTo(47, 79.5, 50, 75.5)
        path.quadTo(53, 79.5, 56, 75)
        p.setPen(QPen(INK, 1.8, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

    _draw_prop(p, prop, ink, swing)
    p.restore()


def _draw_prop(p: QPainter, prop: str | None, ink: QPen, swing: float = 0.0):
    if prop == "mic":           # holding a mic up in the right paw
        p.setPen(ink)
        p.setBrush(QColor("#3a3452"))
        p.drawRoundedRect(QRectF(76, 88, 7, 20), 3, 3)
        _ellipse(p, 79.5, 84, 15, 15, QColor("#9aa0b4"), ink)
        p.setPen(QPen(QColor("#6d7288"), 1))
        for dy in (-3, 0, 3):
            p.drawLine(QPointF(74, 84 + dy), QPointF(85, 84 + dy))
        _ellipse(p, 76, 97, 12, 10, FUR, ink)
    elif prop == "headphones":  # a paw pressed to the ear cup, listening
        _ellipse(p, 86, 72, 12, 11, FUR, ink)
        _music_note(p, 91, 44, 1.0)
    elif prop == "plug":        # holding a cable with a plug
        cable = QPainterPath(QPointF(80, 104))
        cable.cubicTo(QPointF(96, 112), QPointF(98, 92), QPointF(90, 86))
        p.setPen(QPen(PHONES, 3, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawPath(cable)
        p.setPen(ink)
        p.setBrush(QColor("#3a3452"))
        p.drawRoundedRect(QRectF(84, 76, 11, 12), 2.5, 2.5)
        p.setPen(QPen(QColor("#c9ccd8"), 2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(87, 76), QPointF(87, 70))
        p.drawLine(QPointF(92, 76), QPointF(92, 70))
        _ellipse(p, 78, 100, 12, 10, FUR, ink)
    elif prop == "star":        # celebrating: paws up, sparkles
        _ellipse(p, 20, 92, 12, 10, FUR, ink, -30)
        _ellipse(p, 80, 92, 12, 10, FUR, ink, 30)
        _sparkle(p, 10, 30, 7, QColor("#ffcf40"))
        _sparkle(p, 92, 40, 5.5, QColor("#ff8fae"))
        _sparkle(p, 88, 12, 4, QColor("#1fb6ff"))
    elif prop == "hammer":      # building: a plank by his feet, a hammer in his paw
        p.setPen(ink)
        p.setBrush(WOOD)
        p.drawRoundedRect(QRectF(56, 109, 56, 8), 2, 2)
        p.setPen(QPen(WOOD_DARK, 1.2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(70, 113), QPointF(86, 113))
        p.drawLine(QPointF(92, 111.5), QPointF(106, 111.5))
        _ellipse(p, 66, 108, 12, 10, FUR, ink)                 # a paw holding the plank
        # the hammer pivots at the other paw, on his right so it never crosses his
        # face: up beside his head at 0, down on the plank at 1
        p.save()
        p.translate(80, 92)
        p.rotate(25 + 98 * max(0.0, min(1.0, swing)))
        p.setPen(ink)
        p.setBrush(WOOD)
        p.drawRoundedRect(QRectF(-3, -30, 6, 34), 2.5, 2.5)
        p.setBrush(STEEL)
        p.drawRoundedRect(QRectF(-10, -38, 20, 10), 2.5, 2.5)
        p.restore()
        _ellipse(p, 80, 92, 12, 10, FUR, ink)


def _music_note(p: QPainter, x, y, k, col: QColor = PHONES):
    p.setPen(QPen(col, 2.2 * k, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(x + 4 * k, y), QPointF(x + 4 * k, y + 12 * k))
    p.drawLine(QPointF(x + 4 * k, y), QPointF(x + 9 * k, y + 3 * k))
    _ellipse(p, x + 1.5 * k, y + 12.5 * k, 6 * k, 4.5 * k, col, None, -20)


music_note = _music_note   # for the animated widget's floating notes


def _sparkle(p: QPainter, x, y, r, col: QColor):
    path = QPainterPath(QPointF(x, y - r))
    path.quadTo(QPointF(x, y), QPointF(x + r, y))
    path.quadTo(QPointF(x, y), QPointF(x, y + r))
    path.quadTo(QPointF(x, y), QPointF(x - r, y))
    path.quadTo(QPointF(x, y), QPointF(x, y - r))
    p.setPen(Qt.NoPen)
    p.setBrush(col)
    p.drawPath(path)


sparkle = _sparkle


def bunny_image(height: int, prop: str | None = None, dpr: float = 1.0) -> QImage:
    h = max(1, round(height * dpr))
    w = max(1, round(h * W / H))
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    draw_bunny(p, QRectF(0, 0, w, h), prop)
    p.end()
    img.setDevicePixelRatio(dpr)
    return img


def bunny_pixmap(height: int, prop: str | None = None, dpr: float = 1.0) -> QPixmap:
    return QPixmap.fromImage(bunny_image(height, prop, dpr))
