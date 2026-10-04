"""The app's icon set: simple line icons painted on a 24-unit grid.

Painted (not image files) so they're crisp at any DPI and take the current theme's
colours. `set_icon(widget, name)` applies an icon and remembers it, so `retheme()`
can repaint every icon after a theme switch. A checkable button gets a second,
on-accent colour for its checked state.
"""
from __future__ import annotations

import math
import weakref

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QTransform

from soundboard import theme

SIZES = (16, 20, 24, 32, 48)


# --------------------------------------------------------------------------- shapes
# Each draws in a 24x24 box with the pen already set (2px round strokes); `fill`
# paints solid shapes in the same colour.

def _grid(p, fill):
    for x, y in ((3, 3), (13, 3), (3, 13), (13, 13)):
        p.drawRoundedRect(QRectF(x, y, 8, 8), 2, 2)


def _globe(p, fill):
    p.drawEllipse(QRectF(3, 3, 18, 18))
    p.drawEllipse(QRectF(8, 3, 8, 18))
    p.drawLine(QPointF(3, 12), QPointF(21, 12))


def _wave(p, fill):
    for x, h in ((4, 4), (8, 10), (12, 16), (16, 10), (20, 4)):
        p.drawLine(QPointF(x, 12 - h / 2), QPointF(x, 12 + h / 2))


def _sliders(p, fill):
    for y, k in ((6, 15), (12, 8), (18, 13)):
        p.drawLine(QPointF(3, y), QPointF(21, y))
        fill(QPainterPath(), lambda pp, k=k, y=y: pp.addEllipse(QPointF(k, y), 2.6, 2.6))


def _mic(p, fill):
    p.drawRoundedRect(QRectF(9, 2.5, 6, 11), 3, 3)
    p.drawArc(QRectF(5, 5, 14, 12), 200 * 16, 140 * 16)
    p.drawLine(QPointF(12, 17), QPointF(12, 21))
    p.drawLine(QPointF(8.5, 21), QPointF(15.5, 21))


def _headphones(p, fill):
    p.drawArc(QRectF(4, 4, 16, 16), 0, 180 * 16)
    p.drawLine(QPointF(4, 12), QPointF(4, 15))
    p.drawLine(QPointF(20, 12), QPointF(20, 15))
    p.drawRoundedRect(QRectF(3, 13, 4, 7), 1.5, 1.5)
    p.drawRoundedRect(QRectF(17, 13, 4, 7), 1.5, 1.5)


def _volume(p, fill):
    path = QPainterPath(QPointF(3, 9.5))
    for pt in ((7, 9.5), (12, 5), (12, 19), (7, 14.5), (3, 14.5)):
        path.lineTo(*pt)
    path.closeSubpath()
    p.drawPath(path)
    p.drawArc(QRectF(11, 8, 6, 8), -60 * 16, 120 * 16)
    p.drawArc(QRectF(11, 4.5, 10, 15), -60 * 16, 120 * 16)


def _play(p, fill):
    path = QPainterPath(QPointF(7, 4.5))
    path.lineTo(19.5, 12)
    path.lineTo(7, 19.5)
    path.closeSubpath()
    fill(path)


def _pause(p, fill):
    for x in (6.5, 13.5):
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, 5, 4, 14), 1, 1)
        fill(path)


def _stop(p, fill):
    path = QPainterPath()
    path.addRoundedRect(QRectF(6, 6, 12, 12), 2, 2)
    fill(path)


def _record(p, fill):
    path = QPainterPath()
    path.addEllipse(QPointF(12, 12), 6, 6)
    fill(path)


def _plus(p, fill):
    p.drawLine(QPointF(12, 5), QPointF(12, 19))
    p.drawLine(QPointF(5, 12), QPointF(19, 12))


def _gear(p, fill):
    """Six chunky rounded teeth on a ring: reads as a gear even at 16 px."""
    body = QPainterPath()
    body.addEllipse(QPointF(12, 12), 6.6, 6.6)
    for i in range(6):
        tooth = QPainterPath()
        tooth.addRoundedRect(QRectF(-2.3, -9.6, 4.6, 5.5), 1.3, 1.3)
        a = math.degrees(math.pi * 2 * i / 6)
        body = body.united(QTransform().translate(12, 12).rotate(a).map(tooth))
    p.drawPath(body.simplified())
    p.drawEllipse(QPointF(12, 12), 2.8, 2.8)


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


def _cable(p, fill):
    """The virtual cable / plug."""
    p.drawLine(QPointF(9, 3), QPointF(9, 7))
    p.drawLine(QPointF(15, 3), QPointF(15, 7))
    p.drawRoundedRect(QRectF(6, 7, 12, 6), 2, 2)
    p.drawLine(QPointF(12, 13), QPointF(12, 16))
    path = QPainterPath(QPointF(12, 16))
    path.cubicTo(QPointF(12, 22), QPointF(20, 22), QPointF(20, 16))
    p.drawPath(path)


def _check(p, fill):
    p.drawEllipse(QRectF(3, 3, 18, 18))
    p.drawLine(QPointF(8, 12.5), QPointF(11, 15.5))
    p.drawLine(QPointF(11, 15.5), QPointF(16.5, 9))


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
    """The Triggers tab: an eye, watching the screen."""
    path = QPainterPath(QPointF(2.5, 12))
    path.cubicTo(QPointF(6, 5.5), QPointF(18, 5.5), QPointF(21.5, 12))
    path.cubicTo(QPointF(18, 18.5), QPointF(6, 18.5), QPointF(2.5, 12))
    p.drawPath(path)
    p.drawEllipse(QPointF(12, 12), 3.2, 3.2)
    dot = QPainterPath()
    dot.addEllipse(QPointF(12, 12), 1.3, 1.3)
    fill(dot)


def _chevron(direction):
    """A fold-out's state: > closed, v open."""
    def draw(p, fill):
        path = QPainterPath()
        if direction == "down":
            path.moveTo(6, 9)
            path.lineTo(12, 15)
            path.lineTo(18, 9)
        else:
            path.moveTo(9, 6)
            path.lineTo(15, 12)
            path.lineTo(9, 18)
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


def _copy(p, fill):
    p.drawRoundedRect(QRectF(8, 8, 12, 13), 2, 2)
    path = QPainterPath(QPointF(5, 16))
    for pt in ((3, 16), (3, 3), (15, 3), (15, 5)):
        path.lineTo(*pt)
    p.drawPath(path)


SHAPES = {
    "shuffle": _shuffle, "star": _star,
    "star_filled": lambda p, fill: _star(p, fill, True), "like": _like, "copy": _copy,
    "sounds": _grid, "browser": _globe, "voice": _mask, "setup": _sliders,
    "sliders": _sliders, "wave": _wave,
    "mic": _mic, "headphones": _headphones, "volume": _volume, "ear": _ear,
    "play": _play, "pause": _pause, "stop": _stop, "record": _record, "plus": _plus,
    "settings": _gear, "history": _history, "leaf": _leaf, "live": _live,
    "back": _arrow("back"), "forward": _arrow("forward"), "reload": _reload,
    "speech": _speech, "cable": _cable, "check": _check, "warn": _warn, "folder": _folder,
    "shield": _shield,
    "next": _next, "edit": _edit, "trash": _trash, "keyboard": _keyboard,
    "palette": _palette, "gamepad": _gamepad, "image": _image, "video": _video, "radio": _radio,
    "apps": _apps, "triggers": _eye, "fold": _chevron("right"), "fold_open": _chevron("down"),
}


# --------------------------------------------------------------------------- painting

def pixmap(name: str, size: int, color: str) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 24, size / 24)
    col = QColor(color)
    pen = QPen(col, 2.0)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)

    def fill(path: QPainterPath, build=None):
        if build is not None:
            build(path)
        p.fillPath(path, col)

    SHAPES[name](p, fill)
    p.end()
    return pm


_cache: dict[tuple, QIcon] = {}


def icon(name: str, color: str | None = None, checked_color: str | None = None) -> QIcon:
    """`color`/`checked_color` are theme token names (e.g. "text", "on_accent") or
    literal colours ("#ff4d4f")."""
    def resolve(c):
        return theme.T.get(c, c)
    normal = resolve(color or "text")
    on = resolve(checked_color or "on_accent")
    key = (name, normal, on)
    if key not in _cache:
        ic = QIcon()
        for s in SIZES:
            ic.addPixmap(pixmap(name, s, normal), QIcon.Normal, QIcon.Off)
            ic.addPixmap(pixmap(name, s, resolve("muted")), QIcon.Disabled, QIcon.Off)
            ic.addPixmap(pixmap(name, s, on), QIcon.Normal, QIcon.On)
            # the current tab / a highlighted item: accent, not Qt's washed-out tint
            ic.addPixmap(pixmap(name, s, resolve("accent")), QIcon.Selected, QIcon.Off)
            ic.addPixmap(pixmap(name, s, normal), QIcon.Active, QIcon.Off)
        _cache[key] = ic
    return _cache[key]


# --------------------------------------------------------------------------- live retheme

_applied: list[tuple[weakref.ref, str, str | None, str | None]] = []
_tabs: list[tuple[weakref.ref, int, str, str | None, bool]] = []


def set_icon(widget, name: str, color: str | None = None, checked_color: str | None = None,
             size: int = 18):
    """Give a button or menu action (anything with setIcon) an icon that follows theme
    changes."""
    widget.setIcon(icon(name, color, checked_color))
    if hasattr(widget, "setIconSize"):   # a QAction takes its menu's size
        widget.setIconSize(QSize(size, size))
    # one entry per widget: buttons re-iconed on every click must not grow the list
    _applied[:] = [e for e in _applied if e[0]() is not None and e[0]() is not widget]
    _applied.append((weakref.ref(widget), name, color, checked_color))


_labels: list[tuple[weakref.ref, str, str, int]] = []


def set_label_icon(label, name: str, color: str = "muted", size: int = 18):
    """Show an icon in a QLabel (as its pixmap) that follows theme changes."""
    dpr = label.devicePixelRatioF() or 1.0
    pm = icon(name, color).pixmap(QSize(size, size), dpr)
    label.setPixmap(pm)
    _labels.append((weakref.ref(label), name, color, size))


_items: list[tuple[weakref.ref, list[str]]] = []


def set_item_icons(combo, names: list[str]):
    """Icons for a combo box's items, in order, that follow theme changes."""
    for i, name in enumerate(names):
        combo.setItemIcon(i, icon(name))
    _items[:] = [e for e in _items if e[0]() is not None and e[0]() is not combo]
    _items.append((weakref.ref(combo), names))


def _tab_icon(name: str, tint: str | None, badge: bool = False) -> QIcon:
    if name.startswith("art:"):   # a picture (ui/art.py): its own colours, whatever the tint
        from soundboard.ui import art
        ic = art.icon(name[4:]) or QIcon()
    elif tint is None:
        ic = icon(name, "muted", "accent")
    else:
        ic = QIcon()   # one colour whatever the tab's state (e.g. the live colour while it's live)
        for s in SIZES:
            pm = pixmap(name, s, theme.T.get(tint, tint))
            for mode in (QIcon.Normal, QIcon.Selected, QIcon.Active):
                ic.addPixmap(pm, mode, QIcon.Off)
    return _with_badge(ic) if badge and not ic.isNull() else ic


def _with_badge(ic: QIcon) -> QIcon:
    """`ic` with a small "live" dot on its top-right corner, cut out of the picture by
    a thin gap so it reads on any background. Drawn into the icon itself, so the
    tab it's on keeps its size."""
    out = QIcon()
    color = QColor(theme.T["live_text"])
    for s in SIZES:
        r = s * 0.2
        gap = max(1.0, s / 12)
        c = QPointF(s - r, r)
        for state in (QIcon.Off, QIcon.On):   # On: the current tab
            for mode in (QIcon.Normal, QIcon.Selected, QIcon.Active, QIcon.Disabled):
                # at a ratio of 1: on a scaled screen the plain pixmap() comes back bigger,
                # with its own ratio, and the badge landed off its edge
                pm = QPixmap(ic.pixmap(QSize(s, s), 1.0, mode, state))
                if pm.size() != QSize(s, s):
                    pm = pm.scaled(s, s, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                pm.setDevicePixelRatio(1.0)
                p = QPainter(pm)
                p.setRenderHint(QPainter.Antialiasing)
                p.setPen(Qt.NoPen)
                p.setCompositionMode(QPainter.CompositionMode_Clear)
                p.setBrush(Qt.black)
                p.drawEllipse(c, r + gap, r + gap)
                p.setCompositionMode(QPainter.CompositionMode_SourceOver)
                p.setBrush(color)
                p.drawEllipse(c, r, r)
                p.end()
                out.addPixmap(pm, mode, state)
    return out


def set_tab_icon(tabs, index: int, name: str, tint: str | None = None, badge: bool = False):
    """`tint` colours the icon in every state; None is the usual muted / accent.
    "art:<key>" shows that picture from ui/art.py instead of a painted icon. `badge`
    adds the small "live" dot."""
    # on the bar itself: QTabWidget.setTabIcon also lays the whole widget out again and
    # repaints every page under it (the live badge did that to the whole board each
    # time a sound started or stopped); the bar asks for a layout only if it changed
    # size, and widgets.SteadyTabs lets that through
    tabs.tabBar().setTabIcon(index, _tab_icon(name, tint, badge))
    _tabs[:] = [e for e in _tabs if not (e[0]() is tabs and e[1] == index)]
    _tabs.append((weakref.ref(tabs), index, name, tint, badge))


def tab_icon_name(tabs, index: int) -> str | None:
    """The icon name a tab was last given with set_tab_icon, or None."""
    for ref, i, name, _tint, _badge in _tabs:
        if ref() is tabs and i == index:
            return name
    return None


def retheme():
    _cache.clear()
    alive = []
    for ref, name, color, checked in _applied:
        w = ref()
        try:
            if w is not None:
                w.setIcon(icon(name, color, checked))
                alive.append((ref, name, color, checked))
        except RuntimeError:   # the C++ widget is gone
            pass
    _applied[:] = alive
    for ref, names in list(_items):
        combo = ref()
        try:
            if combo is not None:
                set_item_icons(combo, names)
        except RuntimeError:   # the C++ widget is gone
            _items[:] = [e for e in _items if e[0] is not ref]
    labels = list(_labels)
    _labels.clear()
    for ref, name, color, size in labels:
        lbl = ref()
        if lbl is not None:
            try:
                set_label_icon(lbl, name, color, size)
            except RuntimeError:
                pass
    for ref, index, name, tint, badge in _tabs:
        t = ref()
        if t is not None:
            try:
                t.setTabIcon(index, _tab_icon(name, tint, badge))
            except RuntimeError:
                pass
