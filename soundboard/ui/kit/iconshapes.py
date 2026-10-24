"""The line icons' drawings: SHAPES maps each icon's name to the function that draws it.

Each draws in a 24x24 box with the pen already set (2px round strokes); `fill` paints
solid shapes in the same colour. icons.py turns them into pixmaps and icons."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QPainter, QPainterPath, QTransform)


def _grid(p, fill):
    for x, y in ((3, 3), (13, 3), (3, 13), (13, 13)):
        p.drawRoundedRect(QRectF(x, y, 8, 8), 2, 2)


def _globe(p, fill):
    p.drawEllipse(QRectF(3, 3, 18, 18))
    p.drawEllipse(QRectF(8, 3, 8, 18))
    p.drawLine(QPointF(3, 12), QPointF(21, 12))


def _search(p, fill):
    p.drawEllipse(QRectF(4, 4, 12, 12))
    p.drawLine(QPointF(14.5, 14.5), QPointF(20, 20))


def _offline(p, fill):
    """Offline mode: the globe, struck through."""
    _globe(p, fill)
    p.drawLine(QPointF(3.5, 3.5), QPointF(20.5, 20.5))


def _tor(p, fill):
    """Connection = Tor: layers round a middle (onion routing), not an onion: the
    About button's is one."""
    p.drawEllipse(QPointF(12, 12), 8.5, 8.5)
    p.drawEllipse(QPointF(12, 12), 5, 5)
    dot = QPainterPath()
    dot.addEllipse(QPointF(12, 12), 1.8, 1.8)
    fill(dot)


def _phone(p, fill):
    """A phone remote listening: a phone, its speaker slot and button."""
    p.drawRoundedRect(QRectF(7, 3, 10, 18), 2.2, 2.2)
    p.drawLine(QPointF(10.5, 6), QPointF(13.5, 6))
    dot = QPainterPath()
    dot.addEllipse(QPointF(12, 17.6), 1.1, 1.1)
    fill(dot)


def _wave(p, fill):
    """A sound wave: rounded bars, tallest in the middle."""
    bars = QPainterPath()
    for x, h in ((3, 5), (6.6, 10), (10.2, 16), (13.8, 12), (17.4, 7), (21, 3.5)):
        bars.addRoundedRect(QRectF(x - 1.15, 12 - h / 2, 2.3, h), 1.15, 1.15)
    fill(bars)


def _scissors(p, fill):
    """Cutting a clip out of something."""
    p.drawEllipse(QPointF(6, 6), 3, 3)
    p.drawEllipse(QPointF(6, 18), 3, 3)
    p.drawLine(QPointF(20, 4), QPointF(8.1, 15.9))
    p.drawLine(QPointF(14.5, 14.5), QPointF(20, 20))
    p.drawLine(QPointF(8.1, 8.1), QPointF(12, 12))


def _music(p, fill):
    """A pair of beamed notes, matching the toolbar's round line icons."""
    path = QPainterPath(QPointF(9, 17))
    path.lineTo(9, 6)
    path.lineTo(20, 3)
    path.lineTo(20, 14)
    p.drawPath(path)
    p.drawLine(QPointF(9, 10), QPointF(20, 7))
    for x, y in ((6, 18), (17, 15)):
        fill(QPainterPath(), lambda pp, x=x, y=y: pp.addEllipse(QPointF(x, y), 3, 2.5))


def _sliders(p, fill):
    for y, k in ((6, 15), (12, 8), (18, 13)):
        p.drawLine(QPointF(3, y), QPointF(21, y))
        fill(QPainterPath(), lambda pp, k=k, y=y: pp.addEllipse(QPointF(k, y), 2.6, 2.6))


def _mic(p, fill):
    """A microphone: a solid capsule in a cradle, on a short stand."""
    head = QPainterPath()
    head.addRoundedRect(QRectF(8.6, 2.5, 6.8, 11.5), 3.4, 3.4)
    fill(head)
    p.drawArc(QRectF(5, 5, 14, 12.5), 200 * 16, 140 * 16)
    p.drawLine(QPointF(12, 17.5), QPointF(12, 21))
    p.drawLine(QPointF(8.5, 21), QPointF(15.5, 21))


def _mic_off(p, fill):
    """Muted for others: the mic, struck through."""
    _mic(p, fill)
    p.drawLine(QPointF(4, 4), QPointF(20, 20))


def _headphones(p, fill):
    """Headphones: a band and two solid ear cups."""
    p.drawArc(QRectF(4, 4, 16, 16), 0, 180 * 16)
    p.drawLine(QPointF(4, 12), QPointF(4, 14))
    p.drawLine(QPointF(20, 12), QPointF(20, 14))
    cups = QPainterPath()
    cups.addRoundedRect(QRectF(2.6, 12.5, 5.4, 8.5), 2.2, 2.2)
    cups.addRoundedRect(QRectF(16, 12.5, 5.4, 8.5), 2.2, 2.2)
    fill(cups)


def _speaker(fill):
    """The solid speaker _volume and _volume_off draw."""
    body = QPainterPath(QPointF(3.6, 9.2))
    for pt in ((7, 9.2), (11.2, 5.4), (12.4, 5.6), (12.4, 18.4), (11.2, 18.6), (7, 14.8),
               (3.6, 14.8)):
        body.lineTo(*pt)
    body.quadTo(QPointF(2.6, 14.8), QPointF(2.6, 13.8))
    body.lineTo(2.6, 10.2)
    body.quadTo(QPointF(2.6, 9.2), QPointF(3.6, 9.2))
    body.closeSubpath()
    fill(body)


def _volume(p, fill):
    """A solid speaker with two sound waves."""
    _speaker(fill)
    p.drawArc(QRectF(11, 8, 6, 8), -75 * 16, 150 * 16)
    p.drawArc(QRectF(11, 4.5, 10, 15), -75 * 16, 150 * 16)


def _volume_off(p, fill):
    """The speaker with a cross where its sound waves were: muted."""
    _speaker(fill)
    p.drawLine(QPointF(15.5, 9), QPointF(21, 15))
    p.drawLine(QPointF(21, 9), QPointF(15.5, 15))


def _play(p, fill):
    path = QPainterPath()
    path.moveTo(8.2, 5.8)
    path.quadTo(7.2, 5.1, 7.2, 6.4)
    path.lineTo(7.2, 17.6)
    path.quadTo(7.2, 18.9, 8.2, 18.2)
    path.lineTo(18.2, 12.6)
    path.quadTo(19.2, 12.0, 18.2, 11.4)
    path.closeSubpath()
    fill(path)


def _pause(p, fill):
    for x in (6.4, 13.6):
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, 5, 4, 14), 2, 2)
        fill(path)


def _stop(p, fill):
    path = QPainterPath()
    path.addRoundedRect(QRectF(6, 6, 12, 12), 2.8, 2.8)
    fill(path)


def _stop_all(p, fill):
    """Two stop squares, one behind the other: everything stops, not just this sound."""
    back = QPainterPath()
    back.addRoundedRect(QRectF(10, 4, 10, 10), 2.4, 2.4)
    p.drawPath(back)
    front = QPainterPath()
    front.addRoundedRect(QRectF(4, 10, 10, 10), 2.4, 2.4)
    fill(front)


def _expand(p, fill):
    """Four corners pointing out: make it big."""
    for x, y, dx, dy in ((4, 4, 1, 1), (20, 4, -1, 1), (4, 20, 1, -1), (20, 20, -1, -1)):
        path = QPainterPath(QPointF(x + 6 * dx, y))
        path.lineTo(x, y)
        path.lineTo(x, y + 6 * dy)
        p.drawPath(path)


def _record(p, fill):
    path = QPainterPath()
    path.addEllipse(QPointF(12, 12), 7, 7)
    fill(path)


def _plus(p, fill):
    p.drawLine(QPointF(12, 5), QPointF(12, 19))
    p.drawLine(QPointF(5, 12), QPointF(19, 12))


def _close(p, fill):
    """An x: closes a pop-up (the help card)."""
    p.drawLine(QPointF(6.5, 6.5), QPointF(17.5, 17.5))
    p.drawLine(QPointF(17.5, 6.5), QPointF(6.5, 17.5))


def _download(p, fill):
    """An arrow down into an open tray."""
    p.drawLine(QPointF(12, 3.5), QPointF(12, 14.5))
    p.drawPolyline([QPointF(7.5, 10.5), QPointF(12, 15), QPointF(16.5, 10.5)])
    p.drawPolyline([QPointF(4, 15), QPointF(4, 20), QPointF(20, 20), QPointF(20, 15)])


def _gear(p, fill):
    """Six chunky rounded teeth on a solid wheel with a hole: reads as a gear even at
    16 px."""
    body = QPainterPath()
    body.addEllipse(QPointF(12, 12), 7.2, 7.2)
    for i in range(6):
        tooth = QPainterPath()
        tooth.addRoundedRect(QRectF(-2.6, -10.2, 5.2, 5.6), 1.4, 1.4)
        a = math.degrees(math.pi * 2 * i / 6)
        body = body.united(QTransform().translate(12, 12).rotate(a).map(tooth))
    hole = QPainterPath()
    hole.addEllipse(QPointF(12, 12), 2.9, 2.9)
    fill(body.simplified().subtracted(hole))


def _history(p, fill):
    """Clip the last N seconds: a clock with a back-arrow."""
    p.drawArc(QRectF(4, 4, 16, 16), 150 * 16, -300 * 16)
    p.drawLine(QPointF(5.2, 8), QPointF(4, 4.8))
    p.drawLine(QPointF(5.2, 8), QPointF(8.6, 7.4))
    p.drawLine(QPointF(12, 8), QPointF(12, 12))
    p.drawLine(QPointF(12, 12), QPointF(15, 14))


def _leaf(p, fill):
    path = QPainterPath(QPointF(5, 19))
    path.cubicTo(QPointF(4, 9), QPointF(11, 4), QPointF(20, 4))
    path.cubicTo(QPointF(20, 13), QPointF(15, 20), QPointF(5, 19))
    p.drawPath(path)
    p.drawLine(QPointF(5, 19), QPointF(13, 11))


def _live(p, fill):
    path = QPainterPath()
    path.addEllipse(QPointF(12, 12), 2.2, 2.2)
    fill(path)
    for r in (5.5, 9):
        rect = QRectF(12 - r, 12 - r, 2 * r, 2 * r)
        p.drawArc(rect, -45 * 16, 90 * 16)
        p.drawArc(rect, 135 * 16, 90 * 16)


def _live_off(p, fill):
    """Muted: the live waves, struck through."""
    _live(p, fill)
    p.drawLine(QPointF(4, 4), QPointF(20, 20))


def _ear(p, fill):
    """Hear what they hear."""
    path = QPainterPath(QPointF(7, 9))
    path.cubicTo(QPointF(7, 4.5), QPointF(17, 4), QPointF(17, 10))
    path.cubicTo(QPointF(17, 14), QPointF(13, 14), QPointF(13, 17.5))
    path.cubicTo(QPointF(13, 21), QPointF(8, 21), QPointF(8, 18))
    p.drawPath(path)
    arc = QPainterPath(QPointF(10, 10))
    arc.cubicTo(QPointF(10, 7.5), QPointF(14, 7.5), QPointF(14, 10))
    arc.cubicTo(QPointF(14, 11.5), QPointF(12, 12), QPointF(12, 13.5))
    p.drawPath(arc)


def _arrow(direction):
    def draw(p, fill):
        s = -1 if direction == "back" else 1
        p.drawLine(QPointF(12 - 7 * s, 12), QPointF(12 + 7 * s, 12))
        p.drawLine(QPointF(12 + 7 * s, 12), QPointF(12 + 2 * s, 7))
        p.drawLine(QPointF(12 + 7 * s, 12), QPointF(12 + 2 * s, 17))
    return draw


def _panel(stripe, way):
    """The tab rail's hide / show: a window with its side bar (`stripe`, the side it's
    on) and a chevron pointing `way`, the way the bar will go."""
    def draw(p, fill):
        p.drawRoundedRect(QRectF(3, 4, 18, 16), 3, 3)
        x = 9 if stripe == "left" else 15
        p.drawLine(QPointF(x, 4), QPointF(x, 20))
        c = 15 if stripe == "left" else 9   # the chevron, centred in the rest
        s = -1 if way == "left" else 1
        p.drawPolyline([QPointF(c - 1.5 * s, 9), QPointF(c + 1.5 * s, 12),
                        QPointF(c - 1.5 * s, 15)])
    return draw


def _nav_arrow(direction):
    """The setup guide's Back / Next: the arrow, heavier and with a wider head, so it
    holds its own beside the buttons' semibold words."""
    def draw(p, fill):
        pen = p.pen()
        pen.setWidthF(2.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        s = -1 if direction == "back" else 1
        p.drawLine(QPointF(12 - 7 * s, 12), QPointF(12 + 7 * s, 12))
        p.drawPolyline([QPointF(12 + 1 * s, 5), QPointF(12 + 7 * s, 12),
                        QPointF(12 + 1 * s, 19)])
    return draw


def _reload(p, fill):
    p.drawArc(QRectF(5, 5, 14, 14), 60 * 16, 290 * 16)
    p.drawLine(QPointF(15.5, 6), QPointF(19, 5))
    p.drawLine(QPointF(15.5, 6), QPointF(16.5, 9.5))


def _speech(p, fill):
    path = QPainterPath()
    path.addRoundedRect(QRectF(3, 4, 18, 12), 3, 3)
    p.drawPath(path)
    p.drawLine(QPointF(8, 16), QPointF(7, 20.5))
    p.drawLine(QPointF(7, 20.5), QPointF(12, 16))
    for x in (8, 12, 16):
        dot = QPainterPath()
        dot.addEllipse(QPointF(x, 10), 1.1, 1.1)
        fill(dot)


def _mask(p, fill):
    """Voice changer."""
    path = QPainterPath(QPointF(4, 6))
    path.cubicTo(QPointF(9, 4), QPointF(15, 4), QPointF(20, 6))
    path.cubicTo(QPointF(20, 15), QPointF(16, 20), QPointF(12, 20))
    path.cubicTo(QPointF(8, 20), QPointF(4, 15), QPointF(4, 6))
    p.drawPath(path)
    p.drawLine(QPointF(7.5, 10), QPointF(10, 10))
    p.drawLine(QPointF(14, 10), QPointF(16.5, 10))
    p.drawArc(QRectF(9, 12, 6, 4), 200 * 16, 140 * 16)


def _puzzle(p, fill):
    """An add-on piece, with a tab above and a socket on the right."""
    path = QPainterPath(QPointF(4, 8))
    path.lineTo(9, 8)
    path.cubicTo(7, 2, 17, 2, 15, 8)
    path.lineTo(20, 8)
    path.lineTo(20, 12)
    path.cubicTo(14, 10, 14, 20, 20, 18)
    path.lineTo(20, 21)
    path.lineTo(4, 21)
    path.closeSubpath()
    p.drawPath(path)


def _cable(p, fill):
    """The virtual cable / plug."""
    p.drawLine(QPointF(9, 3), QPointF(9, 7))
    p.drawLine(QPointF(15, 3), QPointF(15, 7))
    p.drawRoundedRect(QRectF(6, 7, 12, 6), 2, 2)
    p.drawLine(QPointF(12, 13), QPointF(12, 16))
    path = QPainterPath(QPointF(12, 16))
    path.cubicTo(QPointF(12, 22), QPointF(20, 22), QPointF(20, 16))
    p.drawPath(path)


def _link(p, fill):
    """A sound played from its own file elsewhere on the disk: two chain links."""
    p.save()
    p.translate(12, 12)
    p.rotate(-45)
    p.drawRoundedRect(QRectF(-10, -3.5, 11.5, 7), 3.5, 3.5)
    p.drawRoundedRect(QRectF(-1.5, -3.5, 11.5, 7), 3.5, 3.5)
    p.restore()


def _check(p, fill):
    p.drawEllipse(QRectF(3, 3, 18, 18))
    p.drawLine(QPointF(8, 12.5), QPointF(11, 15.5))
    p.drawLine(QPointF(11, 15.5), QPointF(16.5, 9))


def _info(p, fill):
    """Tab help: a clean circular outline and a font-independent information mark."""
    p.drawEllipse(QRectF(3, 3, 18, 18))
    dot = QPainterPath()
    dot.addEllipse(QPointF(12, 7.5), 1.1, 1.1)
    fill(dot)
    p.drawLine(QPointF(12, 11), QPointF(12, 16.5))


def _question(p, fill):
    """A question (yes / no boxes): a circle with a question mark, like _info's."""
    p.drawEllipse(QRectF(3, 3, 18, 18))
    hook = QPainterPath(QPointF(9.4, 9.6))
    hook.cubicTo(9.4, 6.4, 14.8, 6.4, 14.8, 9.6)
    hook.cubicTo(14.8, 11.6, 12, 11.8, 12, 14)
    p.drawPath(hook)
    dot = QPainterPath()
    dot.addEllipse(QPointF(12, 16.8), 1.1, 1.1)
    fill(dot)


def _more(p, fill):
    """More actions (a card's rare ones): three dots in a row."""
    dots = QPainterPath()
    for x in (5, 12, 19):
        dots.addEllipse(QPointF(x, 12), 1.9, 1.9)
    fill(dots)


def _grip(p, fill):
    """A handle to drag a row by: two columns of three dots."""
    dots = QPainterPath()
    for x in (9, 15):
        for y in (6, 12, 18):
            dots.addEllipse(QPointF(x, y), 1.8, 1.8)
    fill(dots)


def _alert(p, fill):
    """An error: a circle with an exclamation mark."""
    p.drawEllipse(QRectF(3, 3, 18, 18))
    p.drawLine(QPointF(12, 7.5), QPointF(12, 13))
    dot = QPainterPath()
    dot.addEllipse(QPointF(12, 16.5), 1.1, 1.1)
    fill(dot)


def _onion(p, fill):
    """Help and community (the rail's foot): a bulb, a layer and a curled leaf."""
    bulb = QPainterPath(QPointF(12, 6.5))
    bulb.cubicTo(QPointF(14, 9), QPointF(20.5, 10), QPointF(20.5, 14.8))
    bulb.cubicTo(QPointF(20.5, 19), QPointF(16.5, 21), QPointF(12, 21))
    bulb.cubicTo(QPointF(7.5, 21), QPointF(3.5, 19), QPointF(3.5, 14.8))
    bulb.cubicTo(QPointF(3.5, 10), QPointF(10, 9), QPointF(12, 6.5))
    p.drawPath(bulb)
    layer = QPainterPath(QPointF(12, 9))
    layer.cubicTo(QPointF(15, 12.5), QPointF(15, 17.5), QPointF(12.5, 21))
    p.drawPath(layer)
    leaf = QPainterPath(QPointF(12, 6.5))
    leaf.cubicTo(QPointF(12, 4.5), QPointF(13, 3), QPointF(15.5, 2.5))
    p.drawPath(leaf)


def _shield(p, fill):
    """Privacy & security: a shield with a tick."""
    path = QPainterPath(QPointF(12, 3))
    path.lineTo(19.5, 6)
    path.lineTo(19.5, 11.5)
    path.cubicTo(QPointF(19.5, 16), QPointF(16.5, 19.3), QPointF(12, 21))
    path.cubicTo(QPointF(7.5, 19.3), QPointF(4.5, 16), QPointF(4.5, 11.5))
    path.lineTo(4.5, 6)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QPointF(8.8, 12), QPointF(11, 14.3))
    p.drawLine(QPointF(11, 14.3), QPointF(15.4, 9.6))


def _warn(p, fill):
    path = QPainterPath(QPointF(12, 3.5))
    path.lineTo(21, 19.5)
    path.lineTo(3, 19.5)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QPointF(12, 9.5), QPointF(12, 13.5))
    dot = QPainterPath()
    dot.addEllipse(QPointF(12, 16.6), 1.1, 1.1)
    fill(dot)


def _folder(p, fill):
    """A folder with a rounded body, its tab, and the front flap's edge."""
    path = QPainterPath(QPointF(3, 17.5))
    path.lineTo(3, 6.5)
    path.quadTo(3, 4.5, 5, 4.5)
    path.lineTo(8.6, 4.5)
    path.quadTo(9.6, 4.5, 10.3, 5.3)
    path.lineTo(11.6, 6.8)
    path.lineTo(19, 6.8)
    path.quadTo(21, 6.8, 21, 8.8)
    path.lineTo(21, 17.5)
    path.quadTo(21, 19.5, 19, 19.5)
    path.lineTo(5, 19.5)
    path.quadTo(3, 19.5, 3, 17.5)
    p.drawPath(path)
    p.drawLine(QPointF(3, 10), QPointF(21, 10))


def _next(p, fill):
    path = QPainterPath(QPointF(5, 5))
    path.lineTo(15, 12)
    path.lineTo(5, 19)
    path.closeSubpath()
    fill(path)
    bar_ = QPainterPath()
    bar_.addRoundedRect(QRectF(16.5, 5, 3, 14), 1, 1)
    fill(bar_)


def _edit(p, fill):
    path = QPainterPath(QPointF(4, 20))
    for pt in ((5, 15.5), (15.5, 5), (19, 8.5), (8.5, 19)):
        path.lineTo(*pt)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QPointF(13, 7.5), QPointF(16.5, 11))


def _trash(p, fill):
    p.drawLine(QPointF(4, 6.5), QPointF(20, 6.5))
    p.drawLine(QPointF(9.5, 6.5), QPointF(10, 3.5))
    p.drawLine(QPointF(10, 3.5), QPointF(14, 3.5))
    p.drawLine(QPointF(14, 3.5), QPointF(14.5, 6.5))
    path = QPainterPath(QPointF(6, 6.5))
    path.lineTo(7, 20.5)
    path.lineTo(17, 20.5)
    path.lineTo(18, 6.5)
    p.drawPath(path)
    p.drawLine(QPointF(10.5, 10), QPointF(10.5, 17))
    p.drawLine(QPointF(13.5, 10), QPointF(13.5, 17))


def _archive(p, fill):
    p.drawRoundedRect(QRectF(3, 4, 18, 4), 1, 1)
    p.drawRoundedRect(QRectF(4.5, 8, 15, 12), 1.5, 1.5)
    p.drawLine(QPointF(9, 12), QPointF(15, 12))


def _keyboard(p, fill):
    p.drawRoundedRect(QRectF(2.5, 6, 19, 12), 2.5, 2.5)
    for y in (9.5, 12.5):
        for x in (6, 9.5, 13, 16.5):   # key dots
            dot = QPainterPath()
            dot.addEllipse(QPointF(x + 0.5, y), 0.9, 0.9)
            fill(dot)
    p.drawLine(QPointF(8, 15.3), QPointF(16, 15.3))


def _palette(p, fill):
    path = QPainterPath(QPointF(12, 3))
    path.cubicTo(QPointF(4, 3), QPointF(2, 10), QPointF(3.5, 14.5))
    path.cubicTo(QPointF(5, 19), QPointF(10, 21), QPointF(13, 20))
    path.cubicTo(QPointF(15, 19.3), QPointF(13.5, 16.5), QPointF(15, 15.5))
    path.cubicTo(QPointF(17, 14.3), QPointF(21, 16), QPointF(21, 11))
    path.cubicTo(QPointF(21, 6), QPointF(17, 3), QPointF(12, 3))
    p.drawPath(path)
    for x, y in ((8, 9), (12.5, 7), (16.5, 9.5), (7.5, 14)):
        dot = QPainterPath()
        dot.addEllipse(QPointF(x, y), 1.3, 1.3)
        fill(dot)


def _radio(p, fill):
    """The Radio tab: a little set with an antenna."""
    p.drawRoundedRect(QRectF(3, 9, 18, 12), 2.5, 2.5)
    p.drawLine(QPointF(7, 9), QPointF(17, 3.5))
    p.drawEllipse(QPointF(9, 15), 3, 3)
    p.drawLine(QPointF(15, 13), QPointF(18, 13))
    p.drawLine(QPointF(15, 17), QPointF(18, 17))


def _gamepad(p, fill):
    path = QPainterPath(QPointF(7, 7))
    path.lineTo(17, 7)
    path.cubicTo(QPointF(21, 7), QPointF(22.5, 17), QPointF(20, 18.5))
    path.cubicTo(QPointF(18, 19.5), QPointF(16.5, 15.5), QPointF(15, 15.5))
    path.lineTo(9, 15.5)
    path.cubicTo(QPointF(7.5, 15.5), QPointF(6, 19.5), QPointF(4, 18.5))
    path.cubicTo(QPointF(1.5, 17), QPointF(3, 7), QPointF(7, 7))
    p.drawPath(path)
    p.drawLine(QPointF(6, 11), QPointF(10, 11))
    p.drawLine(QPointF(8, 9), QPointF(8, 13))
    for x, y in ((15.5, 10), (17.5, 12)):
        dot = QPainterPath()
        dot.addEllipse(QPointF(x, y), 1.1, 1.1)
        fill(dot)


def _image(p, fill):
    """A picture: frame, sun, mountains."""
    p.drawRoundedRect(QRectF(3, 4, 18, 16), 2.5, 2.5)
    sun = QPainterPath()
    sun.addEllipse(QPointF(8.5, 9), 1.8, 1.8)
    fill(sun)
    path = QPainterPath(QPointF(3.5, 17.5))
    for pt in ((9, 12.5), (13, 16), (16, 13), (20.5, 17.5)):
        path.lineTo(*pt)
    p.drawPath(path)


def _video(p, fill):
    """A video camera: the body and its lens cone."""
    p.drawRoundedRect(QRectF(2.5, 6.5, 13, 11), 2.5, 2.5)
    path = QPainterPath(QPointF(15.5, 10.5))
    for pt in ((21.5, 7), (21.5, 17), (15.5, 13.5)):
        path.lineTo(*pt)
    path.closeSubpath()
    p.drawPath(path)


def _apps(p, fill):
    """The Apps tab: a window with a small sound wave leaving it."""
    p.drawRoundedRect(QRectF(3, 4, 14, 12), 2.5, 2.5)
    p.drawLine(QPointF(3, 8), QPointF(17, 8))
    for x, y in ((5.5, 6), (8, 6)):
        dot = QPainterPath()
        dot.addEllipse(QPointF(x, y), 0.9, 0.9)
        fill(dot)
    p.drawLine(QPointF(10, 19.5), QPointF(10, 19.5))
    path = QPainterPath(QPointF(16, 16))
    path.cubicTo(QPointF(17, 15), QPointF(17, 13), QPointF(16, 12))
    p.drawPath(path)
    path = QPainterPath(QPointF(18.5, 18))
    path.cubicTo(QPointF(21, 15.5), QPointF(21, 12.5), QPointF(18.5, 10))
    p.drawPath(path)
    p.drawLine(QPointF(6, 20), QPointF(13, 20))
    p.drawLine(QPointF(9.5, 16), QPointF(9.5, 20))


def _eye(p, fill):
    """The Triggers tab: an eye, watching the screen (a solid iris with a glint)."""
    path = QPainterPath(QPointF(2.5, 12))
    path.cubicTo(QPointF(6, 5.5), QPointF(18, 5.5), QPointF(21.5, 12))
    path.cubicTo(QPointF(18, 18.5), QPointF(6, 18.5), QPointF(2.5, 12))
    p.drawPath(path)
    iris = QPainterPath()
    iris.addEllipse(QPointF(12, 12), 4, 4)
    glint = QPainterPath()
    glint.addEllipse(QPointF(13.4, 10.6), 1.2, 1.2)
    fill(iris.subtracted(glint))


def _chevron(direction):
    """A fold-out's state: > closed, v open (^ to fold it back up)."""
    pts = {"down": ((6, 9), (12, 15), (18, 9)), "up": ((6, 15), (12, 9), (18, 15)),
           "left": ((15, 6), (9, 12), (15, 18))}.get(direction, ((9, 6), (15, 12), (9, 18)))

    def draw(p, fill):
        # each corner on the pixel grid at the size it's drawn: at 12 px the tip fell
        # between two pixel rows and came out a dim smudge, not a point
        scale = p.transform().m11() or 1
        odd = round(p.pen().widthF() * scale) % 2 == 1   # a 1 px line: drawn hard

        def snap(v):
            d = v * scale
            return (math.floor(d) if odd else math.floor(d + 0.5)) / scale

        path = QPainterPath(QPointF(snap(pts[0][0]), snap(pts[0][1])))
        for x, y in pts[1:]:
            path.lineTo(snap(x), snap(y))
        if odd:   # a 1 px line at 45 degrees: solid steps, not two half-lit pixels each
            p.save()
            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            p.drawPath(path)
            p.restore()
        else:
            p.drawPath(path)
    return draw


def _shuffle(p, fill):
    for points in (((3, 6), (7, 6), (17, 18), (21, 18)),
                   ((3, 18), (7, 18), (17, 6), (21, 6))):
        path = QPainterPath(QPointF(*points[0]))
        for pt in points[1:]:
            path.lineTo(*pt)
        p.drawPath(path)
    for y in (6, 18):
        p.drawLine(QPointF(18, y - 3), QPointF(21, y))
        p.drawLine(QPointF(21, y), QPointF(18, y + 3))


def _star(p, fill, solid=False):
    path = QPainterPath()
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        r = 9 if i % 2 == 0 else 4.2
        point = QPointF(12 + r * math.cos(a), 12 + r * math.sin(a))
        path.moveTo(point) if i == 0 else path.lineTo(point)
    path.closeSubpath()
    fill(path) if solid else p.drawPath(path)


def _like(p, fill):
    p.drawRoundedRect(QRectF(3, 10, 4, 11), 1, 1)
    path = QPainterPath(QPointF(7, 11))
    for pt in ((11, 6), (12, 2), (15, 3), (15, 9), (20, 9),
               (21, 11), (19, 20), (17, 21), (7, 21)):
        path.lineTo(*pt)
    path.closeSubpath()
    p.drawPath(path)


def _dislike(p, fill):
    """The thumbs-up turned upside down."""
    p.save()
    p.translate(0, 24)
    p.scale(1, -1)
    _like(p, fill)
    p.restore()


def _upload(p, fill):
    """An arrow up out of an open tray."""
    p.drawLine(QPointF(12, 15), QPointF(12, 4))
    p.drawPolyline([QPointF(7.5, 8.5), QPointF(12, 4), QPointF(16.5, 8.5)])
    p.drawPolyline([QPointF(4, 15), QPointF(4, 20), QPointF(20, 20), QPointF(20, 15)])


def _flag(p, fill):
    """A flag on a pole: report something."""
    p.drawLine(QPointF(5, 21), QPointF(5, 3.5))
    path = QPainterPath(QPointF(5, 4))
    for pt in ((10, 2.5), (14, 5.5), (19, 4), (19, 13), (14, 14.5), (10, 11.5), (5, 13)):
        path.lineTo(*pt)
    p.drawPath(path)


def _store(p, fill):
    """A shop front: an awning over a door."""
    p.drawPolyline([QPointF(4, 11), QPointF(4, 20.5), QPointF(20, 20.5), QPointF(20, 11)])
    path = QPainterPath(QPointF(3, 9))
    path.lineTo(5, 3.5)
    path.lineTo(19, 3.5)
    path.lineTo(21, 9)
    path.closeSubpath()
    p.drawPath(path)
    for x in (8.3, 12, 15.7):
        p.drawLine(QPointF(x, 3.5), QPointF(x - 0.6 if x < 12 else x + 0.6 if x > 12 else x, 9))
    p.drawRect(QRectF(9.5, 14, 5, 6.5))


def _sort(p, fill):
    """Lines getting shorter, an arrow pointing down beside them."""
    for y, w in ((6, 10), (12, 7), (18, 4)):
        p.drawLine(QPointF(3, y), QPointF(3 + w, y))
    p.drawLine(QPointF(18, 4), QPointF(18, 20))
    p.drawPolyline([QPointF(14.5, 16.5), QPointF(18, 20), QPointF(21.5, 16.5)])


def _rename(p, fill):
    """A text box with a typing cursor in it."""
    p.drawRoundedRect(QRectF(2.5, 7, 19, 10), 2, 2)
    p.drawLine(QPointF(12, 4), QPointF(12, 20))
    p.drawLine(QPointF(10, 4), QPointF(14, 4))
    p.drawLine(QPointF(10, 20), QPointF(14, 20))


def _tag(p, fill):
    """A label tag with its hole."""
    path = QPainterPath(QPointF(3.5, 5.5))
    for pt in ((3.5, 11.5), (12.5, 20.5), (20.5, 12.5), (11.5, 3.5), (5.5, 3.5)):
        path.lineTo(*pt)
    path.closeSubpath()
    p.drawPath(path)
    hole = QPainterPath()
    hole.addEllipse(QPointF(8, 8), 1.5, 1.5)
    fill(hole)


def _list(p, fill):
    for y in (6, 12, 18):
        fill(QPainterPath(), lambda pp, y=y: pp.addEllipse(QPointF(4.5, y), 1.6, 1.6))
        p.drawLine(QPointF(9, y), QPointF(21, y))


def _copy(p, fill):
    p.drawRoundedRect(QRectF(8, 8, 12, 13), 2, 2)
    path = QPainterPath(QPointF(5, 16))
    for pt in ((3, 16), (3, 3), (15, 3), (15, 5)):
        path.lineTo(*pt)
    p.drawPath(path)


def _youtube(p, fill):
    body = QPainterPath()
    body.addRoundedRect(QRectF(2, 5, 20, 14), 4, 4)
    play = QPainterPath(QPointF(10, 8))
    play.lineTo(16, 12)
    play.lineTo(10, 16)
    play.closeSubpath()
    fill(body.subtracted(play))


def _ytmusic(p, fill):
    p.drawEllipse(QRectF(2, 2, 20, 20))
    body = QPainterPath()
    body.addEllipse(QRectF(6, 6, 12, 12))
    play = QPainterPath(QPointF(10.5, 8.5))
    play.lineTo(15.5, 12)
    play.lineTo(10.5, 15.5)
    play.closeSubpath()
    fill(body.subtracted(play))


def _soundcloud(p, fill):
    for x, top in ((2, 12), (5, 10), (8, 7)):
        p.drawLine(QPointF(x, top), QPointF(x, 18))
    cloud = QPainterPath(QPointF(11, 18))
    cloud.lineTo(11, 6)
    cloud.cubicTo(15, 4, 19, 7, 19, 11)
    cloud.cubicTo(24, 10, 25, 18, 20, 18)
    cloud.closeSubpath()
    fill(cloud)


def _tiktok(p, fill):
    note = QPainterPath(QPointF(13, 2))
    note.lineTo(17, 2)
    note.cubicTo(17, 5, 19, 7, 22, 7)
    note.lineTo(22, 11)
    note.cubicTo(20, 11, 18, 10, 17, 9)
    note.lineTo(17, 16)
    note.cubicTo(17, 24, 4, 24, 4, 16)
    note.cubicTo(4, 12, 8, 10, 11, 11)
    note.lineTo(11, 15)
    note.cubicTo(7, 13, 6, 19, 10, 19)
    note.cubicTo(12, 19, 13, 18, 13, 16)
    note.closeSubpath()
    fill(note)


def _twitch(p, fill):
    # Twitch's speech box: square, cut corner, a tail at the bottom, two bars in it
    box = QPainterPath(QPointF(5, 2))
    box.lineTo(21, 2)
    box.lineTo(21, 14)
    box.lineTo(16, 19)
    box.lineTo(12, 19)
    box.lineTo(9, 22)
    box.lineTo(9, 19)
    box.lineTo(3, 19)
    box.lineTo(3, 6)
    box.closeSubpath()
    box.addRect(QRectF(10, 6, 2, 6))   # (the default odd-even fill: holes)
    box.addRect(QRectF(15, 6, 2, 6))
    fill(box)


def _myinstants(p, fill):
    p.drawEllipse(QRectF(2, 12, 20, 8))
    button = QPainterPath(QPointF(5, 15))
    button.lineTo(5, 11)
    button.cubicTo(5, 4, 19, 4, 19, 11)
    button.lineTo(19, 15)
    button.cubicTo(16, 18, 8, 18, 5, 15)
    fill(button)


def _bun(p, fill):
    """Bun mode: a bunny's head, one ear up and one flopped over (an outline like the
    rest, not the cartoon Bun himself)."""
    shape = QPainterPath()
    shape.addEllipse(QRectF(5, 10, 14, 11.5))
    ear = QPainterPath()
    ear.addEllipse(QRectF(-2, -5.5, 4, 11))
    shape = shape.united(QTransform().translate(9.4, 7).rotate(-8).map(ear))
    flop = QPainterPath()
    flop.addEllipse(QRectF(-2, -5, 4, 10))
    shape = shape.united(QTransform().translate(17.2, 8.2).rotate(62).map(flop))
    p.drawPath(shape.simplified())
    for x in (9.6, 14.4):
        eye = QPainterPath()
        eye.addEllipse(QPointF(x, 15.4), 1.1, 1.1)
        fill(eye)


def _chat(p, fill):
    """A speech bubble with a tail, and two lines of text in it."""
    path = QPainterPath(QPointF(5, 4.5))
    path.lineTo(19, 4.5)
    path.quadTo(21, 4.5, 21, 6.5)
    path.lineTo(21, 14.5)
    path.quadTo(21, 16.5, 19, 16.5)
    path.lineTo(11, 16.5)
    path.lineTo(6.5, 20.5)
    path.lineTo(6.5, 16.5)
    path.lineTo(5, 16.5)
    path.quadTo(3, 16.5, 3, 14.5)
    path.lineTo(3, 6.5)
    path.quadTo(3, 4.5, 5, 4.5)
    p.drawPath(path)
    p.drawLine(QPointF(7.5, 9), QPointF(16.5, 9))
    p.drawLine(QPointF(7.5, 12.3), QPointF(13, 12.3))


# the Store's categories (its Category dropdown)

def _face(p, fill):
    p.drawEllipse(QPointF(12, 12), 9, 9)


def _dots(fill, *points, r=1.3):
    path = QPainterPath()
    for x, y in points:
        path.addEllipse(QPointF(x, y), r, r)
    fill(path)


def _laugh(p, fill):
    """Memes: a face laughing, eyes shut, mouth wide open."""
    _face(p, fill)
    p.drawPolyline([QPointF(7.5, 10), QPointF(9, 8.5), QPointF(10.5, 10)])
    p.drawPolyline([QPointF(13.5, 10), QPointF(15, 8.5), QPointF(16.5, 10)])
    mouth = QPainterPath(QPointF(7.5, 13))
    mouth.arcTo(QRectF(7.5, 8.5, 9, 9), 180, 180)
    mouth.closeSubpath()
    fill(mouth)


def _wow(p, fill):
    """Reactions: a surprised face, its mouth an O."""
    _face(p, fill)
    _dots(fill, (9, 9.5), (15, 9.5))
    p.drawEllipse(QPointF(12, 15.5), 1.8, 2.2)


def _wink(p, fill):
    """Pranks: a cheeky face, winking with its tongue out."""
    _face(p, fill)
    _dots(fill, (9, 9.5))
    p.drawLine(QPointF(13.5, 9.5), QPointF(16.5, 9.5))
    p.drawArc(QRectF(7.5, 9, 9, 7), 200 * 16, 140 * 16)
    tongue = QPainterPath(QPointF(12, 15.4))
    tongue.arcTo(QRectF(12, 13.6, 3.6, 4.4), 180, 180)
    tongue.closeSubpath()
    fill(tongue)


def _clapper(p, fill):
    """Movies: a clapperboard, its top swung open."""
    p.drawRoundedRect(QRectF(3, 10, 18, 10.5), 1.5, 1.5)
    p.save()
    p.translate(3, 10)
    p.rotate(-12)
    p.drawRect(QRectF(0, -4.5, 18, 4.5))
    p.drawLine(QPointF(5, -4.5), QPointF(7.5, 0))
    p.drawLine(QPointF(10.5, -4.5), QPointF(13, 0))
    p.restore()


def _tv(p, fill):
    """TV: an old set with rabbit ears."""
    p.drawRoundedRect(QRectF(2.5, 8, 19, 12.5), 2.5, 2.5)
    p.drawPolyline([QPointF(8, 3), QPointF(12, 8), QPointF(16, 3)])


def _ball(p, fill):
    """Sports: a basketball and its seams."""
    p.drawEllipse(QPointF(12, 12), 9, 9)
    p.drawLine(QPointF(12, 3), QPointF(12, 21))
    p.drawLine(QPointF(3, 12), QPointF(21, 12))
    p.drawArc(QRectF(-1.5, 4.5, 12, 15), -75 * 16, 150 * 16)
    p.drawArc(QRectF(13.5, 4.5, 12, 15), 105 * 16, 150 * 16)


def _flame(p, fill):
    """Viral: a flame with a small one inside."""
    path = QPainterPath(QPointF(12, 2.5))
    path.cubicTo(QPointF(15, 6), QPointF(19, 9.5), QPointF(19, 14.5))
    path.cubicTo(QPointF(19, 18.5), QPointF(16, 21.5), QPointF(12, 21.5))
    path.cubicTo(QPointF(8, 21.5), QPointF(5, 18.5), QPointF(5, 14.5))
    path.cubicTo(QPointF(5, 11.5), QPointF(6.5, 9.5), QPointF(8, 8))
    path.cubicTo(QPointF(8.5, 10), QPointF(9.5, 11), QPointF(10.5, 11.5))
    path.cubicTo(QPointF(10, 8), QPointF(10.5, 5), QPointF(12, 2.5))
    p.drawPath(path)
    inner = QPainterPath(QPointF(12, 18.5))
    inner.cubicTo(QPointF(10.5, 18.5), QPointF(9.5, 17.3), QPointF(10, 16))
    inner.cubicTo(QPointF(10.4, 15), QPointF(11.5, 14.4), QPointF(12, 13.3))
    inner.cubicTo(QPointF(12.8, 14.4), QPointF(14.3, 15.4), QPointF(14, 16.7))
    inner.cubicTo(QPointF(13.8, 17.8), QPointF(13, 18.5), QPointF(12, 18.5))
    fill(inner)


def _columns(p, fill):
    """Politics: a hall with a pointed roof on three columns."""
    roof = QPainterPath(QPointF(3, 8.5))
    roof.lineTo(12, 3)
    roof.lineTo(21, 8.5)
    roof.closeSubpath()
    p.drawPath(roof)
    for x in (7, 12, 17):
        p.drawLine(QPointF(x, 11.5), QPointF(x, 17.5))
    p.drawLine(QPointF(3, 20.5), QPointF(21, 20.5))


def _trophy(p, fill):
    """Esports: a cup with handles on a stand."""
    cup = QPainterPath(QPointF(7, 3.5))
    cup.lineTo(7, 8)
    cup.cubicTo(QPointF(7, 11.5), QPointF(9.5, 13.5), QPointF(12, 13.5))
    cup.cubicTo(QPointF(14.5, 13.5), QPointF(17, 11.5), QPointF(17, 8))
    cup.lineTo(17, 3.5)
    cup.closeSubpath()
    p.drawPath(cup)
    left = QPainterPath(QPointF(7, 5.5))
    left.cubicTo(QPointF(3, 5.5), QPointF(3, 10.5), QPointF(7.6, 10.5))
    right = QPainterPath(QPointF(17, 5.5))
    right.cubicTo(QPointF(21, 5.5), QPointF(21, 10.5), QPointF(16.4, 10.5))
    p.drawPath(left)
    p.drawPath(right)
    p.drawLine(QPointF(12, 13.5), QPointF(12, 20.5))
    p.drawLine(QPointF(8, 20.5), QPointF(16, 20.5))


def _ghost(p, fill):
    """Spooky: a ghost with a wavy hem."""
    path = QPainterPath(QPointF(5, 20.5))
    path.lineTo(5, 11)
    path.cubicTo(QPointF(5, 6), QPointF(8, 3), QPointF(12, 3))
    path.cubicTo(QPointF(16, 3), QPointF(19, 6), QPointF(19, 11))
    path.lineTo(19, 20.5)
    for pt in ((16.7, 18.5), (14.3, 20.5), (12, 18.5), (9.7, 20.5), (7.3, 18.5)):
        path.lineTo(*pt)
    path.closeSubpath()
    p.drawPath(path)
    _dots(fill, (9.5, 10.5), (14.5, 10.5), r=1.4)


def _robot(p, fill):
    """AI voices: a robot's head with an antenna."""
    p.drawRoundedRect(QRectF(4, 8, 16, 12), 3, 3)
    p.drawLine(QPointF(12, 8), QPointF(12, 5))
    p.drawLine(QPointF(2, 12), QPointF(2, 16))
    p.drawLine(QPointF(22, 12), QPointF(22, 16))
    _dots(fill, (12, 3.6), (9, 13), (15, 13), r=1.4)
    p.drawLine(QPointF(10, 16.8), QPointF(14, 16.8))


SHAPES = {
    "laugh": _laugh, "wow": _wow, "wink": _wink, "clapper": _clapper, "tv": _tv,
    "ball": _ball, "flame": _flame, "columns": _columns, "trophy": _trophy,
    "ghost": _ghost, "robot": _robot,
    "bun": _bun,
    "youtube": _youtube, "ytmusic": _ytmusic, "soundcloud": _soundcloud,
    "tiktok": _tiktok, "myinstants": _myinstants, "twitch": _twitch,
    "shuffle": _shuffle, "star": _star,
    "star_filled": lambda p, fill: _star(p, fill, True), "like": _like, "copy": _copy,
    "dislike": _dislike,
    "upload": _upload, "flag": _flag, "store": _store, "chat": _chat,
    "sort": _sort, "list": _list, "rename": _rename, "tag": _tag, "search": _search,
    "sounds": _grid, "browser": _globe, "offline": _offline, "tor": _tor, "phone": _phone,
    "voice": _mask, "setup": _sliders,
    "sliders": _sliders, "wave": _wave, "scissors": _scissors, "music": _music, "puzzle": _puzzle,
    "mic": _mic, "mic_off": _mic_off, "headphones": _headphones, "volume": _volume,
    "volume_off": _volume_off, "ear": _ear,
    "play": _play, "pause": _pause, "stop": _stop, "stop_all": _stop_all, "record": _record,
    "plus": _plus, "close": _close,
    "download": _download,
    "expand": _expand,
    "settings": _gear, "history": _history, "leaf": _leaf, "live": _live, "archive": _archive,
    "live_off": _live_off,
    "back": _arrow("back"), "forward": _arrow("forward"),
    "panel_close": _panel("left", "left"), "panel_open": _panel("left", "right"),
    "panel_close_rtl": _panel("right", "right"), "panel_open_rtl": _panel("right", "left"),
    "nav_back": _nav_arrow("back"), "nav_next": _nav_arrow("forward"), "reload": _reload,
    "speech": _speech, "cable": _cable, "check": _check, "warn": _warn,
    "folder": _folder,
    "link": _link,
    "shield": _shield, "info": _info, "question": _question, "alert": _alert, "more": _more,
    "grip": _grip,
    "onion": _onion,
    "next": _next, "edit": _edit, "trash": _trash, "keyboard": _keyboard,
    "palette": _palette, "gamepad": _gamepad, "image": _image, "video": _video, "radio": _radio,
    "apps": _apps, "triggers": _eye, "eye": _eye,
    "fold": _chevron("right"), "fold_back": _chevron("left"),
    "fold_open": _chevron("down"), "fold_up": _chevron("up"),
}
