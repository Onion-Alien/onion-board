"""Bun's still poses for pop-ups (`POSES`): a prop in his paws plus a face, drawn in code like
the rest of him. A pose is a prop name for `draw_bunny` and the face keywords it goes with;
`ModalFrame(mascot="bun:radio")` shows one. Flat fills in the theme's accent, round-capped ink
outline, no texture. Props live on his 100 x 120 canvas, in his lap (y 90..118)."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

from soundboard.ui.kit import theme
from soundboard.ui.bun.bunshapes import _ellipse

PAPER = QColor("#fffdf6")
GOLD = QColor("#ffcf40")
GREEN = QColor("#2fd27a")

# pose name -> (prop, draw_bunny keywords). The props' paws are PROP_PAWS in bunny.py.
POSES = {
    "voices": ("sing", {"mouth": 0.9, "look": 0.0}),
    "game": ("controller", {"angry": 0.4}),
    "server": ("server", {"look": 0.6}),
    "make": ("mixer", {"mouth": 0.35, "nod": 7.0, "look": 0.7}),
    "share_sound": ("card", {"blink": 1.0, "mouth": 0.5}),
    "share_voice": ("bubble", {"mouth": 0.3}),
    "picture": ("frame", {"look": -0.4}),
    "combine": ("puzzle", {"blink": 1.0, "mouth": 0.5}),
    "repair": ("fixmic", {"angry": 0.4}),
    "restore": ("restore", {"look": -0.5}),
    "radio": ("radio", {"blink": 1.0}),
    "running": ("window", {"smug": True}),
}
PROP_NAMES = tuple(v[0] for v in POSES.values())
BOTH = {"controller", "card", "bubble", "frame", "puzzle", "restore", "window"}
# (viewer's left paw, right paw); None: that arm stays on his tummy
PAWS = {"sing": ((26, 99), (87, 95)), "controller": ((36, 109), (64, 109)),
        "server": (None, (61, 103)), "mixer": (None, (80, 103)),
        "card": ((34, 104), (66, 104)), "bubble": ((31, 105), (69, 105)),
        "frame": ((31, 103), (69, 103)), "puzzle": ((22, 104), (78, 104)),
        "fixmic": (None, (64, 104)), "restore": ((36, 99), (64, 99)),
        "radio": (None, (84, 107)), "window": ((30, 98), (70, 98))}


def pose_args(name: str) -> tuple[str | None, dict]:
    """(prop, keywords) of pose `name`; an unknown name is plain Bun."""
    prop, kw = POSES.get(name, (None, {}))
    return prop, dict(kw)


def _cols():
    acc = QColor(theme.T["accent"])
    return acc, acc.lighter(160), acc.darker(125)


def _paw(p, x, y, fur, ink):
    _ellipse(p, x, y, 12, 10, fur, ink)


def _line(p, pts, col, w=2.0):
    p.setPen(QPen(col, w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath(QPointF(*pts[0]))
    for q in pts[1:]:
        path.lineTo(*q)
    p.drawPath(path)


def _burst(p, cx, cy, ink, dirs, r0=4.0, r1=8.0):
    """A few short round-capped dashes round (cx, cy), at the given angles (degrees)."""
    for a in dirs:
        c, s = math.cos(math.radians(a)), math.sin(math.radians(a))
        _line(p, [(cx + c * r0, cy - s * r0), (cx + c * r1, cy - s * r1)],
              QColor(theme.T["accent"]), 2.2)


def _wave(p, x0, x1, cy, col, hs=(2, 5, 3, 7, 3, 5, 2), w=1.8):
    n = len(hs)
    for i, h in enumerate(hs):
        x = x0 + (x1 - x0) * (i + 0.5) / n
        _line(p, [(x, cy - h), (x, cy + h)], col, w)


def _note(p, x, y, col, k=1.0):
    """A white-ish music note, head bottom-left, in a box about 12 x 14 at (x, y)."""
    p.setPen(QPen(col, 2.2 * k, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(col)
    p.drawEllipse(QPointF(x + 2.5 * k, y + 11 * k), 2.6 * k, 2.2 * k)
    p.drawEllipse(QPointF(x + 10.5 * k, y + 9 * k), 2.6 * k, 2.2 * k)
    p.drawLine(QPointF(x + 4.7 * k, y + 10.5 * k), QPointF(x + 4.7 * k, y + 1 * k))
    p.drawLine(QPointF(x + 12.7 * k, y + 8.5 * k), QPointF(x + 12.7 * k, y - 1 * k))
    p.drawLine(QPointF(x + 4.7 * k, y + 1 * k), QPointF(x + 12.7 * k, y - 1 * k))


def draw_pose_prop(p: QPainter, prop: str, ink: QPen, fur: QColor):
    """Draw pose prop `prop` and the paws that hold it (after his face)."""
    acc, lt, dk = _cols()
    p.save()
    p.setPen(ink)
    p.setBrush(acc)
    if prop == "sing":          # a mic up by his mouth, the other paw out
        p.save()
        p.translate(26, 99)
        p.rotate(28)
        p.setBrush(dk)
        p.drawRoundedRect(QRectF(-2.6, -17, 5.2, 21), 2.5, 2.5)
        _ellipse(p, 0, -19, 13, 13, lt, ink)
        p.setPen(QPen(acc, 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for dy in (-2.5, 0, 2.5):
            p.drawLine(QPointF(-4.2, -19 + dy), QPointF(4.2, -19 + dy))
        p.restore()
        _paw(p, 26, 99, fur, ink)
        _paw(p, 87, 95, fur, ink)
        _burst(p, 6, 60, ink, (150, 180, 210), 3, 7)
    elif prop == "controller":  # a game pad in both paws, a headset mic by his mouth
        _line(p, [(85, 66), (88, 80), (72, 84), (62, 80)], dk, 1.8)
        _ellipse(p, 62, 80, 5, 5, acc, ink)
        p.setPen(ink)
        p.setBrush(acc)
        p.drawRoundedRect(QRectF(26, 92, 48, 21), 9, 9)
        p.setBrush(PAPER)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(34.5, 99, 11, 3.4), 1.5, 1.5)      # the d-pad
        p.drawRoundedRect(QRectF(38.3, 95.2, 3.4, 11), 1.5, 1.5)
        p.drawEllipse(QPointF(58, 96.5), 2.1, 2.1)                    # the buttons
        p.drawEllipse(QPointF(63.5, 101), 2.1, 2.1)
        p.drawEllipse(QPointF(58, 105.5), 2.1, 2.1)
        _paw(p, 36, 109, fur, ink)
        _paw(p, 64, 109, fur, ink)
        _burst(p, 90, 46, ink, (40, 70))
    elif prop == "server":      # plugging a cable into a small server box
        cable = [(62, 103), (52, 113), (36, 114), (24, 108)]
        _line(p, cable, ink.color(), 4.6)                                      # a cable, outlined
        _line(p, cable, lt, 2.4)
        p.setPen(ink)
        p.setBrush(acc)
        p.drawRoundedRect(QRectF(68, 84, 28, 34), 4, 4)
        p.setPen(QPen(lt, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for y in (98, 104.5, 111):
            p.drawLine(QPointF(74, y), QPointF(90, y))
        _ellipse(p, 88, 90, 4.4, 4.4, GREEN, ink)                     # the green light
        p.setPen(ink)
        p.setBrush(dk)
        p.drawRoundedRect(QRectF(62.5, 100, 6, 6), 1.5, 1.5)           # the plug
        _paw(p, 59, 103, fur, ink)
        _burst(p, 82, 76, ink, (60, 90, 120), 3.5, 7)
    elif prop == "mixer":       # turning a knob on a little mixer box
        p.drawRoundedRect(QRectF(44, 100, 54, 18), 4, 4)
        p.setPen(QPen(lt, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(50, 112), QPointF(66, 112))
        p.drawLine(QPointF(70, 112), QPointF(92, 112))
        _ellipse(p, 60, 106, 9, 9, lt, ink)
        _ellipse(p, 82, 106, 11, 11, lt, ink)
        p.setPen(QPen(ink.color(), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(82, 106), QPointF(85, 101.5))
        p.drawLine(QPointF(60, 106), QPointF(60, 102.5))
        _paw(p, 80, 103, fur, ink)
        q = QPainterPath(QPointF(84, 24))                             # a "?"
        q.cubicTo(84, 16, 96, 16, 96, 24)
        q.cubicTo(96, 30, 90, 29, 90, 35)
        p.setPen(QPen(acc, 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(q)
        p.drawPoint(QPointF(90, 41))
    elif prop == "card":        # a card with a music note, held to you
        p.drawRoundedRect(QRectF(33, 90, 34, 27), 6, 6)
        _note(p, 43.5, 96.5, PAPER, 1.25)
        _paw(p, 33, 104, fur, ink)
        _paw(p, 67, 104, fur, ink)
        _burst(p, 22, 88, ink, (150, 190))
        _burst(p, 78, 88, ink, (30, -10))
    elif prop == "bubble":      # a speech bubble with a waveform in it
        path = QPainterPath()
        path.addRoundedRect(QRectF(30, 91, 40, 24), 11, 11)
        tail = QPainterPath(QPointF(38, 112))
        tail.lineTo(34, 119)
        tail.lineTo(46, 113.5)
        tail.closeSubpath()
        shape = path.united(tail)
        p.setBrush(lt)
        p.drawPath(shape)
        _wave(p, 38, 62, 103, acc, (2, 5, 8, 5, 3, 6, 2), 2.2)
        _paw(p, 31, 105, fur, ink)
        _paw(p, 69, 105, fur, ink)
        _burst(p, 80, 88, ink, (30, 60), 4, 8)
    elif prop == "frame":       # a picture frame: mountains and a sun
        p.setBrush(PAPER)
        p.drawRoundedRect(QRectF(32, 90, 36, 28), 4, 4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(lt)
        p.drawRoundedRect(QRectF(35.5, 93.5, 29, 21), 2, 2)
        p.setBrush(GOLD)
        p.drawEllipse(QPointF(58, 99), 3, 3)
        m = QPainterPath(QPointF(35.5, 114.5))
        m.lineTo(45, 101)
        m.lineTo(51, 108)
        m.lineTo(55, 104)
        m.lineTo(64.5, 114.5)
        m.closeSubpath()
        p.setBrush(acc)
        p.drawPath(m)
        _paw(p, 31, 103, fur, ink)
        _paw(p, 69, 103, fur, ink)
        _burst(p, 20, 84, ink, (110, 140))
    elif prop == "puzzle":      # two clip pieces clicking together
        p.setBrush(acc)
        left = QPainterPath()
        left.addRoundedRect(QRectF(24, 95, 26, 20), 5, 5)
        left = left.united(_oval(52, 105, 5.5))
        right = QPainterPath()
        right.addRoundedRect(QRectF(50, 95, 26, 20), 5, 5)
        right = right.subtracted(_oval(50, 105, 5.5))
        p.drawPath(right)
        p.drawPath(left)
        _wave(p, 28, 46, 105, PAPER, (2, 4, 7, 4, 2), 1.8)
        _wave(p, 55, 73, 105, PAPER, (2, 5, 7, 4, 2), 1.8)
        _paw(p, 22, 104, fur, ink)
        _paw(p, 78, 104, fur, ink)
        _burst(p, 14, 88, ink, (140, 180))
        _burst(p, 86, 88, ink, (40, 0))
    elif prop == "fixmic":      # a wrench on a standing mic
        p.setBrush(dk)
        p.drawRoundedRect(QRectF(82, 100, 4, 16), 1.5, 1.5)             # the stand
        _ellipse(p, 84, 117, 18, 5, dk, ink)
        p.setBrush(lt)
        p.drawRoundedRect(QRectF(77, 82, 14, 20), 7, 7)                # the mic
        p.setPen(QPen(acc, 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for y in (88, 92, 96):
            p.drawLine(QPointF(79.5, y), QPointF(88.5, y))
        p.save()
        p.translate(64, 104)
        p.rotate(50)
        p.setPen(ink)
        p.setBrush(PAPER)
        p.drawRoundedRect(QRectF(-2.6, -22, 5.2, 24), 2.5, 2.5)
        p.drawEllipse(QPointF(0, -25), 6.4, 6.4)
        p.setBrush(acc)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(QRectF(-2.2, -33, 4.4, 8))                           # the jaw's gap
        p.restore()
        _paw(p, 64, 104, fur, ink)
        _burst(p, 84, 74, ink, (50, 90, 130), 4, 8)
    elif prop == "restore":     # pulling a clock card out of a box
        p.setBrush(PAPER)
        p.drawRoundedRect(QRectF(34, 83, 32, 26), 3, 3)                # the card
        _ellipse(p, 50, 95, 14, 14, PAPER, QPen(acc, 2.0))
        _line(p, [(50, 95), (50, 89.5)], acc, 1.8)
        _line(p, [(50, 95), (54.5, 97)], acc, 1.8)
        p.setPen(ink)
        p.setBrush(acc)
        p.drawRoundedRect(QRectF(26, 104, 48, 14), 3.5, 3.5)           # the box
        p.setBrush(lt)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(44, 109, 12, 4), 2, 2)
        _paw(p, 36, 99, fur, ink)
        _paw(p, 64, 99, fur, ink)
        _burst(p, 80, 82, ink, (40, 70), 4, 8)
    elif prop == "radio":       # turning a radio's dial
        _line(p, [(88, 98), (95, 84)], dk, 2.0)
        p.setPen(ink)
        p.setBrush(acc)
        p.drawRoundedRect(QRectF(42, 98, 54, 20), 5, 5)
        p.setPen(QPen(lt, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for y in (104, 108.5, 113):
            p.drawLine(QPointF(48, y), QPointF(68, y))
        _ellipse(p, 83, 108, 14, 14, lt, ink)
        p.setPen(QPen(ink.color(), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(83, 108), QPointF(86, 103))
        _paw(p, 85, 105, fur, ink)
        _burst(p, 76, 95, ink, (110, 140), 3, 6)
    elif prop == "window":      # peeking over the bottom edge of a small app window
        p.setBrush(acc)
        p.drawRoundedRect(QRectF(2, 99, 96, 19), 5, 5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(lt)
        for x in (10, 16.5, 23):
            p.drawEllipse(QPointF(x, 106), 2.2, 2.2)
        _paw(p, 30, 98, fur, ink)
        _paw(p, 70, 98, fur, ink)
        moon = QPainterPath()
        moon.addEllipse(QPointF(90, 28), 7, 7)
        moon = moon.subtracted(_oval_pt(93.5, 25, 6))
        p.setPen(ink)
        p.setBrush(GOLD)
        p.drawPath(moon)
        for x, y, k in ((94, 52, 1.0), (101, 41, 0.8)):
            _line(p, [(x, y), (x + 5 * k, y), (x, y + 5 * k), (x + 5 * k, y + 5 * k)], acc, 2.0)
    p.restore()


def _oval(cx, cy, r) -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(QPointF(cx, cy), r, r)
    return path


_oval_pt = _oval
