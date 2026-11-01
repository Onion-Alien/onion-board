"""What Bun (ui/bun/bunny.py) holds and wears on top: his props (mic, hammer, bat,
wrench, survey, ...), the nightcap, and the music notes, stars and sparkles that the
animated widget throws too (`music_note`, `sparkle`)."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

from soundboard.ui.kit import theme
from soundboard.ui.bun.bunpalette import (
    BAT, FUR, FUR_LINE, GADGET, GADGET_SCREEN, GRIP, INK, NOSE_EDGE, ROBOT_BOLT, ROBOT_CYAN,
    ROBOT_INK, STEEL, WOOD, WOOD_DARK)
from soundboard.ui.bun.bunshapes import _arc, _ellipse, _glow, _stroke
from soundboard.style.owldraw import sparkle as _sparkle


SWUNG = ("hammer", "hammer_broken", "wrench")   # props his arm swings with


def tool_paw(swing: float) -> tuple[float, float]:
    """His paw on a hammer or wrench as `swing` goes 0 (raised) .. 1 (on the plank):
    lifted out beside his head, then in and down to the plank (in close by mid-swing,
    so the hammer clears what he builds beside him), so his
    arm swings the tool instead of the tool turning in a still paw."""
    s = max(0.0, min(1.0, swing))
    return (round(80 + 9 * (1 - s) ** 2, 1), round(81 + 11 * s, 1))


def _draw_prop(p: QPainter, prop: str | None, ink: QPen, swing: float = 0.0,
               fur: QColor = FUR):
    if prop == "mic":           # holding a mic up in the right paw
        p.setPen(ink)
        p.setBrush(QColor("#3a3452"))
        p.drawRoundedRect(QRectF(76, 88, 7, 20), 3, 3)
        _ellipse(p, 79.5, 84, 15, 15, QColor("#9aa0b4"), ink)
        p.setPen(QPen(QColor("#6d7288"), 1))
        for dy in (-3, 0, 3):
            p.drawLine(QPointF(74, 84 + dy), QPointF(85, 84 + dy))
        _ellipse(p, 76, 97, 12, 10, fur, ink)
    elif prop == "headphones":  # a paw pressed to the ear cup, listening
        _ellipse(p, 86, 72, 12, 11, fur, ink)
        _music_note(p, 91, 44, 1.0)
    elif prop == "plug":        # holding a cable with a plug
        cable = QPainterPath(QPointF(80, 104))
        cable.cubicTo(QPointF(96, 112), QPointF(98, 92), QPointF(90, 86))
        p.setPen(QPen(QColor(theme.T["accent"]), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(cable)
        p.setPen(ink)
        p.setBrush(QColor("#3a3452"))
        p.drawRoundedRect(QRectF(84, 76, 11, 12), 2.5, 2.5)
        p.setPen(QPen(QColor("#c9ccd8"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(87, 76), QPointF(87, 70))
        p.drawLine(QPointF(92, 76), QPointF(92, 70))
        _ellipse(p, 78, 100, 12, 10, fur, ink)
    elif prop == "star":        # celebrating: paws up, a gold star held high, sparkles
        _ellipse(p, 20, 92, 12, 10, fur, ink, -30)
        _star(p, 89, 79, 12.5, ink)
        _ellipse(p, 80, 92, 12, 10, fur, ink, 30)
        _sparkle(p, 10, 30, 7, QColor("#ffcf40"))
        _sparkle(p, 92, 40, 5.5, QColor("#ff8fae"))
        _sparkle(p, 88, 12, 4, QColor("#1fb6ff"))
    elif prop in ("hammer", "hammer_broken"):   # building: a plank by his feet, a hammer
        # in his paw. Broken: the plank snapped in a V and the hammer's head gone
        broken = prop == "hammer_broken"
        if broken:
            for pivot, x, turn in ((56, 56, 7), (112, 85, -7)):
                p.save()
                p.translate(pivot, 113)
                p.rotate(turn)
                p.translate(-pivot, -113)
                p.setPen(ink)
                p.setBrush(WOOD)
                p.drawRoundedRect(QRectF(x, 109, 27, 8), 2, 2)
                p.setPen(QPen(WOOD_DARK, 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                edge = x + 27 if turn > 0 else x   # splinters along the break
                k = 1 if turn > 0 else -1
                p.drawLine(QPointF(edge, 110.5), QPointF(edge + 3 * k, 112))
                p.drawLine(QPointF(edge, 115.5), QPointF(edge + 2.5 * k, 114))
                p.restore()
        else:
            p.setPen(ink)
            p.setBrush(WOOD)
            p.drawRoundedRect(QRectF(56, 109, 56, 8), 2, 2)
            p.setPen(QPen(WOOD_DARK, 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(70, 113), QPointF(86, 113))
            p.drawLine(QPointF(92, 111.5), QPointF(106, 111.5))
        # the hammer pivots at the other paw, on his right so it never crosses his
        # face: up beside his head at 0, down on the plank at 1
        px, py = tool_paw(swing)
        p.save()
        p.translate(px, py)
        p.rotate(25 + 98 * max(0.0, min(1.0, swing)))
        p.setPen(ink)
        p.setBrush(WOOD)
        p.drawRoundedRect(QRectF(-3, -30, 6, 34), 2.5, 2.5)
        if broken:   # a splintered stub where the head was
            p.setPen(QPen(WOOD_DARK, 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(-2, -30), QPointF(-0.5, -33))
            p.drawLine(QPointF(1.5, -30), QPointF(2.5, -32.5))
        else:
            p.setBrush(STEEL)
            p.drawRoundedRect(QRectF(-10, -38, 20, 10), 2.5, 2.5)
        p.restore()
        _ellipse(p, px, py, 12, 10, fur, ink)
    elif prop == "bat":         # a baseball bat in his right paw: over his shoulder at
        # 0, swung down and out to his right at 1 (never across his face)
        p.save()
        p.translate(80, 92)
        p.rotate(15 + 105 * max(0.0, min(1.0, swing)))
        bat = QPainterPath(QPointF(-2.2, 6))
        bat.lineTo(-2.2, -14)
        bat.cubicTo(QPointF(-2.6, -24), QPointF(-6, -30), QPointF(-6, -40))
        bat.cubicTo(QPointF(-6, -48), QPointF(6, -48), QPointF(6, -40))
        bat.cubicTo(QPointF(6, -30), QPointF(2.6, -24), QPointF(2.2, -14))
        bat.lineTo(2.2, 6)
        bat.closeSubpath()
        p.setPen(ink)
        p.setBrush(BAT)
        p.drawPath(bat)
        p.setPen(QPen(WOOD, 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(-1.5, -40), QPointF(-2.5, -30))   # a bit of wood grain
        p.setPen(ink)
        p.setBrush(GRIP)
        p.drawRoundedRect(QRectF(-2.6, -4, 5.2, 9), 1.5, 1.5)
        _ellipse(p, 0, 7, 7.5, 3.5, GRIP, ink)              # the knob
        p.restore()
        _ellipse(p, 80, 92, 12, 10, fur, ink)
    elif prop == "survey":      # *Enjoying Onion Board?*: a clipboard in both paws
        _survey(p, ink, fur)
    elif prop == "wrench":      # assembling: an AI gadget by his feet, a wrench in his paw
        # (light metal with an ink outline and a glowing screen: it reads on dark and
        # light themes alike)
        p.setPen(ink)
        p.setBrush(GADGET)
        p.drawRoundedRect(QRectF(56, 106, 54, 12), 3, 3)
        p.setPen(QPen(ROBOT_CYAN, 1.2))
        p.setBrush(QColor("#181e2b"))
        p.drawRoundedRect(GADGET_SCREEN, 1.5, 1.5)
        _ellipse(p, 98, 113.5, 3.2, 3.2, QColor("#13ce66"), QPen(ROBOT_INK, 0.8))   # power
        _ellipse(p, 104, 108.5, 6, 6, ROBOT_BOLT, ink)        # the bolt he's tightening
        p.setPen(QPen(ROBOT_INK, 1))
        p.drawLine(QPointF(102.3, 108.5), QPointF(105.7, 108.5))
        px, py = tool_paw(swing)
        p.save()
        p.translate(px, py)
        p.rotate(25 + 98 * max(0.0, min(1.0, swing)))
        p.setPen(ink)
        p.setBrush(QColor("#9aa3b5"))
        p.drawRoundedRect(QRectF(-3, -28, 6, 32), 2, 2)
        p.drawRoundedRect(QRectF(-8, -36, 16, 10), 2, 2)
        p.setBrush(fur)
        p.drawRect(QRectF(-3, -37, 6, 6))
        p.restore()
        _ellipse(p, px, py, 12, 10, fur, ink)


def _survey(p: QPainter, ink: QPen, fur: QColor):
    """A clipboard held up in both paws, turned to face you (he's showing you the
    survey): a heart, a ticked box and an empty one, and a few sparkles. *Enjoying
    Onion Board?*"""
    p.save()
    p.translate(50, 102)
    p.rotate(-6)
    p.setPen(ink)
    p.setBrush(WOOD)
    p.drawRoundedRect(QRectF(-16, -19, 32, 36), 4, 4)        # the board
    p.setBrush(QColor("#fffdf6"))
    p.drawRoundedRect(QRectF(-12.5, -14, 25, 28), 2, 2)      # the paper
    p.setBrush(STEEL)
    p.drawRoundedRect(QRectF(-7, -22, 14, 7), 2.5, 2.5)      # the clip
    heart = QPainterPath(QPointF(0, -2.5))                   # a big heart at the top
    heart.cubicTo(QPointF(-7.5, -7.5), QPointF(-4, -13.5), QPointF(0, -9.5))
    heart.cubicTo(QPointF(4, -13.5), QPointF(7.5, -7.5), QPointF(0, -2.5))
    p.setPen(QPen(NOSE_EDGE, 1.1))
    p.setBrush(QColor("#ff6f91"))
    p.drawPath(heart)
    line = QPen(QColor("#b9b2c8"), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    for y, ticked in ((3, True), (9, False)):
        p.setPen(QPen(QColor("#6d6880"), 1.1))
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(QRectF(-9, y - 2.5, 5, 5), 1, 1)
        if ticked:
            p.setPen(QPen(QColor("#13ce66"), 1.8, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawPolyline([QPointF(-8.4, y - 0.2), QPointF(-6.7, y + 1.6),
                            QPointF(-3.4, y - 3.4)])
        p.setPen(line)
        p.drawLine(QPointF(-1.5, y), QPointF(8.5, y))
    p.restore()
    _ellipse(p, 33, 105, 12, 10, fur, ink, -20)              # his paws on its sides
    _ellipse(p, 67, 105, 12, 10, fur, ink, 20)
    _sparkle(p, 12, 34, 6, QColor("#ffcf40"))
    _sparkle(p, 90, 38, 5, QColor("#ff8fae"))
    _sparkle(p, 86, 14, 3.5, QColor("#1fb6ff"))


def _nightcap(p: QPainter, ink: QPen):
    """A floppy sleeping cap over the headphone band, dotted with little stars, its
    tip and fluffy bobble flopped down to his left (the viewer's right)."""
    cap = QColor(theme.T["accent"])
    star = cap.lighter(160)
    body = QPainterPath(QPointF(23, 50))
    body.cubicTo(QPointF(22, 30), QPointF(39, 18), QPointF(56, 19))
    body.cubicTo(QPointF(75, 20), QPointF(89, 31), QPointF(92, 48))
    body.cubicTo(QPointF(86, 41), QPointF(80, 39), QPointF(77, 48))
    body.quadTo(QPointF(50, 40), QPointF(23, 50))
    p.setPen(ink)
    p.setBrush(cap)
    p.drawPath(body)
    p.save()
    p.setClipPath(body)
    p.setPen(Qt.PenStyle.NoPen)
    _glow(p, 66, 46, 70, 26, cap.darker(125))   # a fold of shade low down
    for x, y, r in ((34, 37, 2.6), (48, 27, 2.2), (62, 34, 2.8), (76, 28, 2.2),
                    (83, 40, 2.0), (54, 41, 1.8)):
        _star(p, x, y, r, None, star)
    p.restore()
    p.setPen(ink)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(body)
    brim = QPainterPath(QPointF(21, 51))   # the soft white band round the bottom
    brim.quadTo(QPointF(50, 39.5), QPointF(79, 49))
    p.setPen(QPen(INK, 9.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawPath(brim)
    p.setPen(QPen(FUR, 6.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawPath(brim)
    _ellipse(p, 92, 50, 12, 12, FUR, ink)   # the bobble, with a tuft of fluff
    _stroke(p, _arc(88.5, 48, 90, 46, 92.5, 46.5), FUR_LINE, 1.1)


NOTE_SHAPES = 4   # an eighth note, a quarter note, two eighths and two sixteenths
                  # (♪ ♩ ♫ ♬)


def _music_note(p: QPainter, x, y, k, col: QColor | None = None, shape: int = 0):
    """A note in the 9 x 15 box at (x, y) (`k`: its size); shapes 2 and 3 are a beamed
    pair, 15 wide."""
    col = col or QColor(theme.T["accent"])
    pen = QPen(col, 2.2 * k, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.drawLine(QPointF(x + 4 * k, y), QPointF(x + 4 * k, y + 12 * k))
    if shape == 0:   # its flag
        p.drawLine(QPointF(x + 4 * k, y), QPointF(x + 9 * k, y + 3 * k))
    elif shape >= 2:   # the second note, a little higher, and the beam over both
        p.drawLine(QPointF(x + 13 * k, y - 2 * k), QPointF(x + 13 * k, y + 10 * k))
        for i in range(shape - 1):
            d = i * 4.6 * k
            beam = QPainterPath(QPointF(x + 3 * k, y + d - 1.2 * k))
            beam.lineTo(x + 14 * k, y + d - 3.2 * k)
            beam.lineTo(x + 14 * k, y + d - 0.6 * k)
            beam.lineTo(x + 3 * k, y + d + 1.4 * k)
            beam.closeSubpath()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawPath(beam)
        _ellipse(p, x + 10.5 * k, y + 10.5 * k, 6 * k, 4.5 * k, col, None, -20)
    _ellipse(p, x + 1.5 * k, y + 12.5 * k, 6 * k, 4.5 * k, col, None, -20)


music_note = _music_note   # for the animated widget's floating notes


def _star(p: QPainter, x, y, r, ink: QPen | None, col: QColor | None = None):
    """A chunky five-pointed gold star with a shine (or a plain one in `col`)."""
    path = QPainterPath()
    for i in range(10):
        a = math.radians(-90 + 36 * i)
        rr = r if i % 2 == 0 else r * 0.48
        pt = QPointF(x + math.cos(a) * rr, y + math.sin(a) * rr)
        if i == 0:
            path.moveTo(pt)
        else:
            path.lineTo(pt)
    path.closeSubpath()
    if ink is None:
        p.setPen(Qt.PenStyle.NoPen)
    else:
        pen = QPen(ink)
        pen.setWidthF(1.8)
        p.setPen(pen)
    p.setBrush(col or QColor("#ffcf40"))
    p.drawPath(path)
    if col is None:
        _ellipse(p, x - r * 0.22, y - r * 0.22, r * 0.3, r * 0.22, QColor("#fff3c4"), None, -30)


sparkle = _sparkle
