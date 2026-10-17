"""Hoot, Onion Watch's mascot: a cartoon owl (owls keep watch), drawn with QPainter
in the same style as Bun, so it's crisp at any size and needs no image files. He
wears Bun's theme outfit (_fit, bunnyfit.py; docs/MASCOT.md).

Part of the style kit (see __init__.py): Onion Watch draws him from its copy of
this file, and Onion Board's Triggers tab shows him until the add-on is installed.

    owl_image(160)             # QImage, transparent background
    OwlWidget(96, lines=...)   # Hoot alive: waiting, begging, sulking
"""
from __future__ import annotations

import math
import random
import time
import weakref

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QCursor, QFont, QImage, QPainter, QPainterPath, QPen,
                           QRadialGradient)
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import appstate, bunnyfit, hooks
from .appstate import snap_to_pixels
from .hooks import _

# drawn on a 100 x 120 canvas, scaled to the requested height
W, H = 100.0, 120.0
INK = QColor("#2b2340")
FEATHER = QColor("#2fbfae")
FEATHER_DARK = QColor("#1f9a8c")
BELLY = QColor("#fbf3e3")
BELLY_MARK = QColor("#e2cfae")
FACE = QColor("#fdf8ee")
EYE = QColor("#251c33")
EYE_LOW = QColor("#5d4560")
BEAK = QColor("#ffb43c")
BEAK_DARK = QColor("#e8892a")
MOUTH = QColor("#c2413b")
EYE_RING = FACE   # (older name for the colour round his eyes)
CHEEK = QColor(255, 128, 160, 120)
TEAR = QColor("#8fd3ff")
BUBBLE = QColor("#fffaf0")
SPARKLE_COLORS = ("#ffcf40", "#ff8fae", "#1fb6ff", "#a48bff")
EYES = (34, 66)
EYE_Y = 53.0
FPS = 30
FAST_MS = 1000 // FPS


def _e(p, cx, cy, w, h, fill, pen=None, angle=0.0):
    p.save()
    p.translate(cx, cy)
    p.rotate(angle)
    p.setPen(pen or Qt.PenStyle.NoPen)
    p.setBrush(fill)
    p.drawEllipse(QRectF(-w / 2, -h / 2, w, h))
    p.restore()


def _mix(a: float, b: float, k: float) -> float:
    return a + (b - a) * k


def _arc(x0, y0, cx, cy, x1, y1) -> QPainterPath:
    path = QPainterPath(QPointF(x0, y0))
    path.quadTo(QPointF(cx, cy), QPointF(x1, y1))
    return path


def _stroke(p: QPainter, path: QPainterPath, col: QColor, width: float):
    p.setPen(QPen(col, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)


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


def body_path() -> QPainterPath:
    """His round, egg-shaped body (owls are all head), with two soft feather points
    on each cheek."""
    path = QPainterPath(QPointF(50, 21))
    path.cubicTo(QPointF(74, 21), QPointF(86, 38), QPointF(86, 60))
    path.cubicTo(QPointF(86, 92), QPointF(74, 114), QPointF(50, 114))
    path.cubicTo(QPointF(26, 114), QPointF(14, 92), QPointF(14, 60))
    path.cubicTo(QPointF(14, 38), QPointF(26, 21), QPointF(50, 21))
    path.closeSubpath()
    for sx in (-1, 1):
        for y, d in ((55, 5.5), (63.5, 4.5)):
            tip = QPainterPath(QPointF(50 + sx * 33.5, y - 5))
            tip.quadTo(QPointF(50 + sx * (36 + d * 0.4), y - 1), QPointF(50 + sx * (36 + d), y + 2))
            tip.quadTo(QPointF(50 + sx * 36, y + 3), QPointF(50 + sx * 34.5, y + 5))
            tip.closeSubpath()
            path = path.united(tip)
    return path


def _tuft(sx: int) -> QPainterPath:
    """An ear tuft on his `sx` side: a soft curved point with a little notch."""
    def m(x, y):
        return QPointF(50 + sx * (x - 50), y)
    path = QPainterPath(m(70, 27))
    path.cubicTo(m(74, 22), m(78, 16), m(79, 8))
    path.cubicTo(m(82, 13), m(84, 18), m(83, 24))
    path.quadTo(m(86.5, 23), m(88, 21))
    path.cubicTo(m(88, 30), m(85, 37), m(80, 41))
    path.closeSubpath()
    return path


def _wing(sx: int) -> QPainterPath:
    """A wing in its own frame (upright, its top at 0, 0): round at the shoulder,
    ending in three soft feather points."""
    def m(x, y):
        return QPointF(sx * x, y)
    path = QPainterPath(m(0, -19))
    path.cubicTo(m(7.5, -19), m(9.5, -6), m(9, 6))
    path.cubicTo(m(8.6, 12), m(6, 17), m(4, 20))
    path.quadTo(m(2.6, 18.5), m(1.2, 18.6))
    path.quadTo(m(0, 21.5), m(-1.4, 20.5))
    path.quadTo(m(-2.6, 18.5), m(-4, 18))
    path.cubicTo(m(-8, 12), m(-9, 2), m(-8, -6))
    path.cubicTo(m(-7, -14), m(-4.5, -19), m(0, -19))
    path.closeSubpath()
    return path


def _face_path() -> QPainterPath:
    """The cream mask round his eyes: two joined discs, the feathers dipping in
    between them on top, meeting in a soft point under his beak."""
    path = QPainterPath()
    for x in EYES:
        path.addEllipse(QPointF(x, EYE_Y), 17.5, 16.5)
    chin = QPainterPath(QPointF(36, 62))
    chin.cubicTo(QPointF(42, 70), QPointF(46, 73), QPointF(50, 74))
    chin.cubicTo(QPointF(54, 73), QPointF(58, 70), QPointF(64, 62))
    chin.closeSubpath()
    return path.united(chin).simplified()


# where Bun's pieces go on Hoot, as (dx, dy, scale) from Bun's canvas: his head sits 12
# higher than Bun's; his eyes are 32 apart (Bun's 25) and 10 higher; he has no neck,
# so a bow tie or scarf goes just under his beak
_K = (EYES[1] - EYES[0]) / (bunnyfit.EYES[1] - bunnyfit.EYES[0])
HEAD = (0, -12, 1.0)
EYES_AT = (50 - 50 * _K, EYE_Y - bunnyfit.EYE_Y * _K, _K)
NECK_AT = (0, -14, 1.0)
# pieces that need their own place: the frog's eyes and the mint would poke out of the
# top of his picture (moved a little lower). Tall hats stay full size on purpose: an
# oversized hat on him is the look.
OWN_PLACE = {"frog": (0, -10, 1.0), "mint_sprig": (2, -1, 1.0)}
# pieces that don't fit an owl: a hoodie's drawstrings read as a second face on his
# belly, and a turtleneck's ribbed roll as teeth under his beak
NOT_ON_OWL = {"strings", "sweater", "turtleneck"}


def _fit(p: QPainter, fit, layer: str, ink: QPen, shut: bool = False):
    """Hoot wears Bun's theme outfit (bunnyfit.py, drawn for Bun's canvas):
    each piece is moved onto Hoot's shape (HEAD, EYES_AT, NECK_AT, OWN_PLACE)."""
    for name in fit:
        if name in NOT_ON_OWL:
            continue
        if name in OWN_PLACE:
            dx, dy, k = OWN_PLACE[name]
        elif layer == "face":
            dx, dy, k = NECK_AT if name in bunnyfit.NECK else EYES_AT
        else:
            dx, dy, k = HEAD
        p.save()
        p.translate(dx, dy)
        p.scale(k, k)
        bunnyfit.draw(p, (name,), layer, ink, shut=shut)
        p.restore()


def draw_owl(p: QPainter, rect: QRectF, look: float = 0.0, feather=None, dark=None,
             *, look_y: float = 0.0, blink: float = 0.0, sad: float = 0.0,
             tufts: float = 0.0, clasp: float = 0.0, flap: float = 0.0,
             plead: float = 0.0, tear: float = 0.0, beak: float = 0.0,
             outfit: tuple[str, ...] | None = None):
    """Draw Hoot fitted (aspect kept, centred) into `rect`. `look` / `look_y` -1..1
    turn his eyes left / right and up / down: watching. The keywords pose him for
    OwlWidget: `blink` 0..1 closes the eyes, `sad` 0..1 worries the brows and wets
    the eyes, `tufts` droops the ear tufts by that many degrees (negative perks them
    up), `clasp` 0..1 brings the wings together in front (begging), `flap` 0..1 lifts
    them (joy), `plead` 0..1 makes the eyes big and shiny, `tear` 0..1 rolls a tear
    down his cheek (0 = none) and `beak` 0..1 opens his beak (a cheer, a hoot). His
    feathers are the current theme's accent unless `feather` / `dark` are given
    (FEATHER / FEATHER_DARK are his own teal).
    `outfit`: Bun's outfit pieces to wear (None: the current theme's, (): none)."""
    fit = bunnyfit.outfit() if outfit is None else outfit
    if feather is None:
        feather = QColor(hooks.palette()["accent"])
    if dark is None:
        dark = QColor(feather).darker(135)
    feather, dark = QColor(feather), QColor(dark)
    s = min(rect.width() / W, rect.height() / H)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(rect.center().x() - W * s / 2, rect.center().y() - H * s / 2)
    p.scale(s, s)
    ink = QPen(INK, 2.4)
    ink.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    ink.setCapStyle(Qt.PenCapStyle.RoundCap)

    _fit(p, fit, "behind", ink)
    _fit(p, fit, "back", ink)
    # ear tufts, turned about their base
    for sx in (-1, 1):
        p.save()
        p.translate(50 + sx * 25, 38)
        p.rotate(sx * tufts)
        p.translate(-(50 + sx * 25), -38)
        tuft = _tuft(sx)
        p.setPen(ink)
        p.setBrush(feather)
        p.drawPath(tuft)
        _shade(p, tuft, 50 + sx * 82, 34, 12, dark, 150)
        p.restore()
    # body: feathers, lit from up on his right, deeper underneath
    body = body_path()
    p.setPen(ink)
    p.setBrush(feather)
    p.drawPath(body)
    _shade(p, body, 50, 122, 46, dark, 190)
    _shade(p, body, 40, 30, 26, feather.lighter(125), 150)
    # belly, with rows of little feather scallops
    belly = QPainterPath()
    belly.addEllipse(QRectF(29, 70, 42, 42))
    p.fillPath(belly, BELLY)
    _shade(p, belly, 50, 114, 22, BELLY_MARK, 110)
    for x, y in ((42, 84), (50, 84), (58, 84), (46, 92.5), (54, 92.5), (50, 101)):
        _stroke(p, _arc(x - 3.6, y, x, y + 3.4, x + 3.6, y), BELLY_MARK, 1.7)
    # feet: three round toes each
    for x in (39, 61):
        for dx, dy in ((-3.8, 0.5), (0, 1.2), (3.8, 0.5)):
            _e(p, x + dx, 113 + dy, 4.8, 6.2, BEAK, QPen(INK, 1.7))
    # the face: a cream mask, soft-edged, the cheeks blushing
    face = _face_path()
    p.fillPath(face, FACE)
    _shade(p, face, 50, 78, 22, BELLY_MARK, 90)
    p.save()
    p.setClipPath(face)
    for x in (22.5, 77.5):
        g = QRadialGradient(QPointF(x, 63.5), 6.5)
        g.setColorAt(0, CHEEK)
        g.setColorAt(0.55, CHEEK)
        g.setColorAt(1, QColor(255, 128, 160, 0))
        p.fillRect(QRectF(x - 7, 56.5, 14, 14), g)
    p.restore()
    # wings: at his sides, clasped in front of the belly, or flung up
    for sx in (-1, 1):
        x = 50 + sx * (_mix(34, 15, clasp) + 5 * flap)
        y = 84 + 3 * clasp - 12 * flap
        ang = -sx * (_mix(12, 30, clasp) - 70 * flap)
        p.save()
        p.translate(x, y)
        p.rotate(ang)
        p.scale(1.15, 1.12)   # (big, soft wings, like the Storybook model)
        wing = _wing(sx)
        p.setPen(ink)
        p.setBrush(dark)
        p.drawPath(wing)
        _shade(p, wing, -sx * 4, -12, 14, feather, 150)   # a lighter shoulder
        p.restore()
    _fit(p, fit, "under", ink)
    # the big eyes
    shut = blink > 0.6
    ew, eh = _mix(19, 21, plead), _mix(20.5, 22.5, plead)
    for x in EYES:
        px, py = x + 2.8 * look, EYE_Y + 2.0 * look_y
        if shut:   # closed: a soft sleepy curve, or happy arcs while he cheers
            if flap > 0.3 or beak > 0.3:
                _stroke(p, _arc(x - 6.5, EYE_Y + 2.5, x, EYE_Y - 3.5, x + 6.5, EYE_Y + 2.5),
                        INK, 2.4)
            else:
                _stroke(p, _arc(x - 6.5, EYE_Y + 1, x, EYE_Y + 5, x + 6.5, EYE_Y + 1), INK, 2.4)
            continue
        eye = QPainterPath()
        eye.addEllipse(QRectF(px - ew / 2, py - eh / 2, ew, eh))
        p.fillPath(eye, EYE)
        p.save()
        p.setClipPath(eye)
        g = QRadialGradient(QPointF(px, py + eh * 0.42), ew * 0.45)
        g.setColorAt(0, EYE_LOW)
        g.setColorAt(1, QColor(EYE_LOW.red(), EYE_LOW.green(), EYE_LOW.blue(), 0))
        p.fillRect(QRectF(px - ew, py, 2 * ew, eh), g)
        _e(p, px + 3.2, py - 3.6, _mix(6, 7.4, plead), _mix(6.4, 7.8, plead), QColor("white"))
        _e(p, px - 3.3, py + 4.0, 2.4, 2.4, QColor("white"))
        if plead > 0.05:   # the extra glint that makes puppy eyes
            c = QColor("white")
            c.setAlphaF(plead)
            _e(p, px + 4.3, py + 3, 2.8, 2.8, c)
        if sad > 0.05:     # welling up: water along the bottom of each eye
            c = QColor(TEAR)
            c.setAlphaF(0.6 * sad)
            _e(p, px, py + eh / 2 - 1, ew, 7 * sad, c)
        if blink > 0.01:   # the lid comes down from the top
            lid = (eh + 2) * blink
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(FACE)
            p.drawRect(QRectF(px - ew, py - eh / 2 - 1, 2 * ew, lid))
            _stroke(p, _arc(px - ew / 2, py - eh / 2 - 1 + lid, px, py - eh / 2 + lid + 1,
                            px + ew / 2, py - eh / 2 - 1 + lid), INK, 2.2)
        p.restore()
    # brows: resting soft ticks above the eyes, or worried (inner ends lifted)
    worried = min(1.0, sad * 1.4)
    for x, sx in ((EYES[0], -1), (EYES[1], 1)):
        if worried > 0.05:
            c = QColor(INK)
            c.setAlphaF(worried)
            _stroke(p, _arc(x + sx * 8, 41.5 + 1.5 * sad, x + sx * 2, 40,
                            x - sx * 4.5, 40.5 - 5 * sad), c, 2.5)
    # beak: a soft amber point, open when he cheers
    o = max(0.0, min(1.0, beak))
    top = QPainterPath(QPointF(45, 59.5))
    top.quadTo(QPointF(50, 57.6), QPointF(55, 59.5))
    top.quadTo(QPointF(55.6, 60.3), QPointF(54.8, 61.6))
    top.quadTo(QPointF(52.4, 66 - 2 * o), QPointF(50.8, 68.5 - 3 * o))
    top.quadTo(QPointF(50, 69.5 - 3 * o), QPointF(49.2, 68.5 - 3 * o))
    top.quadTo(QPointF(47.6, 66 - 2 * o), QPointF(45.2, 61.6))
    top.quadTo(QPointF(44.4, 60.3), QPointF(45, 59.5))
    top.closeSubpath()
    bp = QPen(INK, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
              Qt.PenJoinStyle.RoundJoin)
    if o > 0.05:   # the open mouth and lower beak below the top one
        low = QPainterPath(QPointF(46.5, 63))
        low.quadTo(QPointF(50, 63 + 2 * o), QPointF(53.5, 63))
        low.quadTo(QPointF(52.5, 66 + 4 * o), QPointF(50, 67.5 + 5 * o))
        low.quadTo(QPointF(47.5, 66 + 4 * o), QPointF(46.5, 63))
        low.closeSubpath()
        p.setPen(bp)
        p.setBrush(MOUTH)
        p.drawPath(low)
        p.save()
        p.setClipPath(low)
        _e(p, 50, 67 + 5 * o, 6, 4 * o, BEAK_DARK)
        p.restore()
    p.setPen(bp)
    p.setBrush(BEAK)
    p.drawPath(top)
    p.save()
    p.setClipPath(top)
    _e(p, 52, 64.5 - 2 * o, 6, 7, BEAK_DARK)
    _e(p, 48.2, 60.6, 3.4, 1.6, QColor(255, 255, 255, 170))
    p.restore()
    # a tear rolling down from the outer corner of his left eye
    if 0 < tear < 1:
        c = QColor(TEAR)
        c.setAlphaF(min(1.0, tear * 5, (1 - tear) * 3))
        tx, ty = 23, 63 + 24 * tear * tear
        drop = QPainterPath(QPointF(tx, ty - 7))
        drop.cubicTo(QPointF(tx + 4.5, ty - 1), QPointF(tx + 5, ty + 4.5), QPointF(tx, ty + 4.5))
        drop.cubicTo(QPointF(tx - 5, ty + 4.5), QPointF(tx - 4.5, ty - 1), QPointF(tx, ty - 7))
        p.setPen(QPen(QColor(INK.red(), INK.green(), INK.blue(), round(160 * c.alphaF())), 1))
        p.setBrush(c)
        p.drawPath(drop)
    _fit(p, fit, "over", ink)
    _fit(p, fit, "face", ink, shut=shut)
    p.restore()


def owl_image(height: int, look: float = 0.5) -> QImage:
    h = max(1, height)
    w = max(1, round(h * W / H))
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    draw_owl(p, QRectF(0, 0, w, h), look, FEATHER, FEATHER_DARK,   # artwork: his own teal,
             outfit=())                                           # no outfit
    p.end()
    return img


def sparkle(p: QPainter, x: float, y: float, r: float, col: QColor):
    """A four-pointed twinkle."""
    path = QPainterPath(QPointF(x, y - r))
    path.quadTo(QPointF(x, y), QPointF(x + r, y))
    path.quadTo(QPointF(x, y), QPointF(x, y + r))
    path.quadTo(QPointF(x, y), QPointF(x - r, y))
    path.quadTo(QPointF(x, y), QPointF(x, y - r))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(col)
    p.drawPath(path)


# ---------------------------------------------------------------------- alive
def wait_lines() -> tuple[str, ...]:
    """What he says while he begs, in the language picked (a function: the kit can be
    imported before the language is)."""
    return (_("pleeease?"), _("just one picture?"), _("I'll watch anything…"),
            _("hoo? hoo…?"), _("so… bored…"), _("my turn yet?"))


def joy_lines() -> tuple[str, ...]:
    """What he shouts when he's clicked."""
    return (_("yay!! ↓ down there!"), _("hoo-ray!"), _("let's watch something!"))


# the little acts he does while he waits, and how long each lasts (seconds)
ACTS = {"sigh": 1.8, "plead": 3.0, "tear": 2.6, "peek": 2.2, "doze": 5.0}


def _bell(k: float) -> float:
    """0 → 1 → 0 over k = 0..1, with soft ends."""
    return math.sin(math.pi * max(0.0, min(1.0, k)))


def _soft(k: float) -> float:
    """0 → 1 → 0 over k = 0..1, starting and stopping still (a move eases in and out)."""
    return _bell(k) ** 2


# the springy layer over the pose (OwlWidget._spring): stiffness (1/s²), damping (1/s)
TUFT_SPRING = (420.0, 16.0)    # ear tufts trail his moves and wobble as they settle
WING_SPRING = (600.0, 28.0)    # wings trail too, a little stiffer (they flap)
SQUASH_SPRING = (300.0, 15.0)  # his body jiggles back after a squash or stretch
TUFT_DRAG = 8.0    # how far his tufts trail behind, degrees per owl-height a second
WING_DRAG = 0.3    # how far his wings trail behind (flap), per owl-height a second
STRETCH = 0.03     # how tall and thin a fast move makes him, per owl-height a second
SQUASH = 0.3       # how hard a change of direction (a landing) squashes him
ACT_OUT = 0.35     # seconds an act cut short (the mouse, a click, a song) takes to go


class _Spring:
    """A damped spring chasing a target: the lag, overshoot and wobble that make a
    move look alive instead of on rails (Bun's, in Onion Board's bunnywidget.py)."""
    __slots__ = ("x", "v")

    def __init__(self, x: float = 0.0):
        self.x, self.v = x, 0.0

    def step(self, target: float, dt: float, k: float, d: float) -> float:
        n = max(1, math.ceil(dt / 0.008))   # small steps: steady at any frame rate
        h = dt / n
        for _i in range(n):
            self.v += (k * (target - self.x) - d * self.v) * h
            self.x += self.v * h
        return self.x


# dancing (set_groove): the styles he bobs to the hits themselves, not the beat grid
HIT_BANDS = {"hiphop": ("bass",), "rock": ("bass", "drums")}
HIT_LEAD = 0.1    # seconds a bob starts before its hit, so it lands right on it
# (three frames at his 30 fps: a shorter run-in jumped)
STYLE_BLEND = 0.6  # seconds to change from one style of dance to another


def _hit(age: float, decay: float = 6.0) -> float:
    """A hit `age` seconds ago (less than 0: still coming): down to 1 right on it,
    then easing back."""
    if age < -HIT_LEAD or age > 2:
        return 0.0
    if age < 0:   # speeding down, still moving when it lands (a thud, not a stop)
        k = 1 + age / HIT_LEAD
        return k * k * (2 - k)
    return math.exp(-age * decay)


def _ease(k: float) -> float:
    k = max(0.0, min(1.0, k))
    return k * k * (3 - 2 * k)


class OwlWidget(QWidget):
    """Hoot, alive and waiting: he sways, blinks and glances down at the buttons
    below, sighs, begs with his wings clasped and big shiny eyes, sheds a tear,
    peeks, dozes off and jolts awake. Bring the mouse near and he perks up and
    follows it with his eyes; click him and he hops for joy.

    `lines` are what he says when he begs, `joy` what he shouts when clicked
    (default: wait_lines() / joy_lines()).
    `left` / `right` are the room beside him, px (default: plenty both sides, for
    the speech bubble up to his right and the zzz). The timer only runs while he's
    on screen."""

    clicked = Signal()
    # the ones made with dances=True: the host hands each one on screen what's playing
    dancers: weakref.WeakSet = weakref.WeakSet()

    def __init__(self, height: int = 96, lines=None, joy=None, parent=None, *,
                 left: int | None = None, right: int | None = None, dances: bool = False):
        super().__init__(parent)
        if dances:
            OwlWidget.dancers.add(self)
        self.groove = None         # what's playing (set_groove): he dances to it
        self._dance = 0.0          # 0..1, how far into the dance (fades in and out)
        self.owl_h = height
        self.lines = tuple(wait_lines() if lines is None else lines)
        self.joy_lines = tuple(joy_lines() if joy is None else joy)
        side = round(height * 1.45)
        self.left = side if left is None else left
        self.right = side if right is None else right
        self.top = round(height * 0.34)    # room above for "?" and z's
        # the room beside him gives way first when space is short (the bubble then
        # overlaps him a little)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(_("Hoot is waiting for something to watch"))
        self._rng = random.Random()
        self._t0 = self._last = time.monotonic()
        self.t = 0.0
        self.act: str | None = None
        self._act_t = 0.0
        self._next_act = self._rng.uniform(2.0, 3.5)
        self._next_blink = self._rng.uniform(1.0, 3.0)
        self._blink_t = -1.0
        self._near = 0.0           # 0..1, how close the mouse is (smoothed)
        self._joy_t = -1.0         # seconds since he was clicked, or -1
        self.say = ""              # the speech bubble's text
        self._look = [0.0, 0.7]    # pupils, smoothed
        self._glance = (0.0, 0.7)  # where he looks when left alone
        self._next_glance = 1.5
        self._was: tuple[str, float] | None = None   # an act cut short, fading out:
        self._was_w = 0.0                            # (act, how far in), 1..0
        self._g_last = None        # the groove he's still fading out of
        self._style = self._style_was = ""
        self._blend = 1.0          # 0..1 from the last style of dance to this one
        self._tufts_s = _Spring()  # the springy layer (_spring): tufts,
        self._wing_s = _Spring()   # ... wings,
        self._squash_s = _Spring()  # ... squash and stretch
        self._sprung = False       # (the springs start where the pose is)
        self._dy_last = 0.0
        self._vy = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(FAST_MS)
        self._timer.timeout.connect(self._tick)
        appstate.pause_in_background(self, self._resume, self._timer.stop)

    def sizeHint(self) -> QSize:
        return QSize(round(self.owl_h * W / H) + self.left + self.right,
                     self.owl_h + self.top + 8)

    def minimumSizeHint(self) -> QSize:
        return QSize(round(self.owl_h * W / H) + 8, self.owl_h + self.top + 8)

    def showEvent(self, ev):
        if appstate.active():   # behind a game it waits until the app is back in front
            self._resume()
        super().showEvent(ev)

    def _resume(self):
        self._last = time.monotonic()
        self._timer.start(FAST_MS)

    def hideEvent(self, ev):
        self._timer.stop()
        super().hideEvent(ev)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.cheer()
            self.clicked.emit()
        super().mousePressEvent(ev)

    def set_groove(self, groove):
        """What's playing, as a soundboard.groove.Groove (its beat, style and hits), or
        None. He bobs his head to it."""
        self.groove = groove

    @staticmethod
    def _accent(g, now: float) -> float:
        """0..1, how far into a bob this moment: on the song's hits (hip-hop, rock) or
        its beat (`g`: the groove)."""
        bands = HIT_BANDS.get(g.style)
        if bands:
            best = 0.0
            for band in bands:
                age, s = g.last_hit(band, now)
                until, s2 = g.next_hit(band, now)
                best = max(best, _hit(age) * s, _hit(-until) * s2)
            return best
        # the beat that went and the one coming, whichever is further in (one curve:
        # never a jump from one to the next), easing back over about a beat
        ph, beat = g.beat(now) % 1.0, 60 / g.bpm
        return max(_hit(ph * beat, 4 / beat), _hit((ph - 1) * beat, 4 / beat))

    def cheer(self):
        """A happy hop with sparkles (what a click does)."""
        self._joy_t = 0.0
        self._stop_act()
        self.say = self._rng.choice(self.joy_lines) if self.joy_lines else ""

    # ------------------------------------------------------------------ time
    def _owl_rect(self) -> QRectF:
        w = self.owl_h * W / H
        spare, room = self.width() - w, self.left + self.right   # shared as asked
        x = spare * self.left / room if room else spare / 2
        return QRectF(x, self.height() - self.owl_h - 4, w, self.owl_h)

    def _tick(self):
        now = time.monotonic()
        self.step(min(0.1, now - self._last))
        self._last = now
        self.update()   # always 30 fps: a slower idle pace made the sway judder

    def _mouse(self) -> tuple[float, float] | None:
        """The cursor relative to his face, in owl heights, if it's in this window."""
        win = self.window()
        g = QCursor.pos()
        if win is None or not win.frameGeometry().contains(g):
            return None
        pos = self.mapFromGlobal(g)
        r = self._owl_rect()
        return ((pos.x() - r.center().x()) / self.owl_h,
                (pos.y() - (r.top() + r.height() * 0.45)) / self.owl_h)

    def step(self, dt: float, mouse=...):
        """Advance the animation by `dt` seconds (`mouse` overrides the cursor, tests)."""
        self.t += dt
        g = self.groove
        on = g is not None and bool(g.style) and bool(g.bpm)
        if g is not None and on:
            self._g_last = g
            if g.style != self._style:
                self._style_was, self._style, self._blend = self._style, g.style, 0.0
        self._blend = min(1.0, self._blend + dt / STYLE_BLEND)
        self._dance += (float(on) - self._dance) * min(1.0, dt * 3)
        if self._dance < 0.01 and not on:
            self._g_last, self._style = None, ""
        if self._dance > 0.3 and self.act:   # (no sulking while he dances)
            self._stop_act()
        if self._was is not None:
            self._was_w -= dt / ACT_OUT
            if self._was_w <= 0:
                self._was = None
        m = self._mouse() if mouse is ... else mouse
        dist = math.hypot(*m) if m else 99.0
        near = 1.0 if dist < 2.2 else 0.0
        self._near += (near - self._near) * min(1.0, dt * (5 if near else 1.5))
        if self._joy_t >= 0:
            self._joy_t += dt
            if self._joy_t > 1.6:
                self._joy_t = -1.0
                self.say = ""
        if self.act:
            self._act_t += dt
            if self._act_t >= ACTS[self.act]:
                self.act = None
                self.say = ""
                self._next_act = self.t + self._rng.uniform(3.5, 7.0)
            elif self._near > 0.6:
                self._stop_act()
        elif (self._joy_t < 0 and self._near < 0.3 and self.t >= self._next_act
              and self._dance < 0.3):
            self.start(self._rng.choice(list(ACTS)))
        if self.t >= self._next_blink:
            self._blink_t = self.t
            self._next_blink = self.t + self._rng.uniform(2.0, 5.0)
        if self.t >= self._next_glance:   # mostly down at the buttons, now and then at you
            self._glance = self._rng.choice(((0.0, 0.8), (0.0, 0.8), (-0.3, 0.6), (0.3, 0.7),
                                             (0.0, -0.2), (-0.7, 0.2), (0.6, 0.1)))
            self._next_glance = self.t + self._rng.uniform(1.2, 3.0)
        if m and self._near > 0.2:
            tx, ty = max(-1.0, min(1.0, m[0] * 1.6)), max(-1.0, min(1.0, m[1] * 1.6))
        else:
            tx, ty = self._glance
        if self.act == "peek":
            tx, ty = 0.5, 1.0
        k = min(1.0, dt * 8)
        self._look[0] += (tx - self._look[0]) * k
        self._look[1] += (ty - self._look[1]) * k
        self._spring(dt)

    def start(self, act: str):
        """Begin one of ACTS now."""
        self.act, self._act_t = act, 0.0
        self.say = self._rng.choice(self.lines) if act == "plead" and self.lines else ""

    def _stop_act(self):
        """Cut the act short: it fades out over ACT_OUT instead of snapping off."""
        if self.act:
            self._was, self._was_w = (self.act, self._act_t / ACTS[self.act]), 1.0
            self._next_act = self.t + self._rng.uniform(3.5, 7.0)
        self.act = None
        self.say = ""

    @staticmethod
    def _act(a: str, k: float, t: float) -> dict:
        """What act `a`, `k` 0..1 of the way through, does to the pose: moves to add
        (dy, rot, tufts), floors to raise (blink, sad, clasp, plead), the tear and the
        extras paintEvent draws. Every move starts and ends still."""
        o: dict = {}
        if a == "sigh":        # sinks, eyes half shut, a puff of breath
            b = _soft(k)
            o.update(dy=5 * b, tufts=14 * b, blink=0.45 * b, puff=k)
        elif a == "plead":     # wings clasped, puppy eyes, hopeful little hops
            e = _ease(k / 0.15) * _ease((1 - k) / 0.15)
            o.update(clasp=e, plead=e, sad=0.9 * e, tufts=-10 * e, beak=0.45 * e,
                     dy=-4 * e * abs(math.sin(k * math.pi * 6)))
        elif a == "tear":
            o.update(tear=k, sad=_ease(k / 0.12) * _ease((1 - k) / 0.12),
                     blink=0.25 * _soft(k))
        elif a == "peek":      # leans over to look down at the buttons
            b = _soft(k)
            o.update(rot=9 * b, ask=b)
        elif a == "doze":      # nods off... and jolts awake
            if k < 0.78:
                d, w, j = _ease(k / 0.3), 1.0, -1.0
            else:              # the doze falls away fast as he jolts
                j = (k - 0.78) / 0.22
                d, w = 1.0, 1 - _ease(j / 0.1)
            o.update(blink=0.9 * d * w, dy=3 * d * w,
                     rot=(-4 * d + 1.5 * math.sin(t * 1.5) * d) * w)
            if k < 0.78:
                o["zzz"] = k
            if j >= 0:
                o["dy"] -= 9 * _soft(min(1.0, j * 1.5))
                o["tufts"] = -25 * _soft(j)
                o["startle"] = j
        return o

    def _dance_style(self, style: str, bob: float) -> tuple[float, float]:
        """(flap, blink) a style of dance adds: wings on a big hit for rock and
        electronic, eyes shut for chill."""
        return (0.7 * bob if style in ("rock", "electronic") else 0.0,
                1.0 if style == "chill" else 0.0)

    def base_pose(self) -> dict:
        """The pose this moment before the springy layer (see pose())."""
        t, near = self.t, self._near
        sad = 0.85 * (1 - near)
        tufts = 24 * sad - 10 * near + 3 * math.sin(t * 1.1)
        dy = -1.2 * math.sin(t * 2.0) - 4 * near * abs(math.sin(t * 5)) * 0.5
        rot = 2.5 * math.sin(t * 0.8)
        blink = 0.0
        if self._blink_t >= 0 and (b := t - self._blink_t) < 0.18:
            blink = _soft(b / 0.18)
        clasp = flap = plead = tear = beak = 0.0
        extra = {}
        acts = []
        if self.act:
            acts.append((self._act(self.act, self._act_t / ACTS[self.act], t), 1.0))
        if self._was is not None:
            a, k = self._was
            o = self._act(a, k, t)
            if "tear" in o:    # a tear cut short drops off his cheek
                o["tear"] = k + (1 - k) * (1 - self._was_w)
            acts.append((o, _ease(self._was_w)))
        for o, w in acts:
            dy += o.get("dy", 0.0) * w
            rot += o.get("rot", 0.0) * w
            tufts += o.get("tufts", 0.0) * w
            blink = max(blink, o.get("blink", 0.0) * w)
            sad = max(sad, o.get("sad", 0.0) * w)
            clasp = max(clasp, o.get("clasp", 0.0) * w)
            plead = max(plead, o.get("plead", 0.0) * w)
            beak = max(beak, o.get("beak", 0.0) * w)
            if "tear" in o:
                tear = o["tear"]
            for key in ("puff", "zzz", "startle"):
                if key in o:
                    extra[key], extra[key + "_a"] = o[key], w
            if "ask" in o:
                extra["ask"] = o["ask"] * w
        d = self._dance
        g = self.groove if self.groove is not None else self._g_last
        if d > 0.01 and g is not None and g.bpm:
            # dancing: head bobbing down on the hits, swaying a beat each way, tufts
            # bouncing, a flap of the wings on a big hit; cheered right up
            now = time.monotonic()
            bob = self._accent(g, now)
            sway = math.sin(math.pi * g.beat(now))
            sad *= 1 - d
            tufts += d * (-14 + 5 * bob)   # (the springs add the bounce)
            dy += d * 9 * bob
            rot += d * 7 * sway
            f, b = self._dance_style(self._style, bob)
            if self._blend < 1:   # changing style: blended, never a jump
                k = _ease(self._blend)
                f0, b0 = self._dance_style(self._style_was, bob)
                f, b = f0 + (f - f0) * k, b0 + (b - b0) * k
            flap = max(flap, d * f)
            blink = max(blink, d * b)
            beak = max(beak, d * 0.5 * bob)
        if self._joy_t >= 0:
            j = self._joy_t / 1.6
            e = _bell(j)
            sad, tufts = sad * (1 - e), tufts - 30 * e
            flap = abs(math.sin(self._joy_t * 14)) * e
            dy -= 16 * abs(math.sin(j * math.pi * 2)) * (1 - j)
            blink *= 1 - _ease(j / 0.08)
            plead = max(plead, 0.6 * e)
            beak = max(beak, e)
            extra["joy"] = j
        return {"look": self._look[0], "look_y": self._look[1], "blink": blink, "sad": sad,
                "tufts": tufts, "clasp": clasp, "flap": flap, "plead": plead, "tear": tear,
                "beak": beak,
                "dy": dy, "rot": rot, **extra}

    def _spring(self, dt: float):
        """Moves the springy layer on a frame: his tufts and wings trail behind his
        hops and wobble as they settle, a fast move stretches him and a change of
        direction (a landing, a take-off) squashes him, then he jiggles back."""
        if dt <= 0:
            return
        pose = self.base_pose()
        if not self._sprung:   # first frame: start where he is, no fling
            self._sprung = True
            self._tufts_s.x, self._wing_s.x, self._dy_last = pose["tufts"], pose["flap"], pose["dy"]
        vy = (pose["dy"] - self._dy_last) / dt / max(1, self.owl_h)
        self._dy_last = pose["dy"]
        dv = max(-4.0, min(4.0, vy - self._vy))   # (a jump cut can't fling him)
        self._vy = vy
        # landing (dv < 0): squash; softer on every bob of a dance (not a jelly)
        self._squash_s.v += SQUASH * (1 - 0.7 * self._dance) * dv * 10
        self._squash_s.step(min(0.08, abs(vy) * STRETCH), dt, *SQUASH_SPRING)
        self._squash_s.x = max(-0.2, min(0.15, self._squash_s.x))
        self._tufts_s.step(pose["tufts"] - vy * TUFT_DRAG, dt, *TUFT_SPRING)
        self._wing_s.step(pose["flap"] + vy * WING_DRAG, dt, *WING_SPRING)

    def pose(self) -> dict:
        """Everything draw_owl and the extras need for this moment: base_pose() with
        the springy layer on top (tufts and wings trailing, `sx` / `sy` squash)."""
        pose = self.base_pose()
        if not self._sprung:
            return {**pose, "sx": 1.0, "sy": 1.0}
        s = self._squash_s.x
        return {**pose, "tufts": self._tufts_s.x, "sx": 1 - 0.6 * s, "sy": 1 + s,
                "flap": max(-0.2, min(1.3, self._wing_s.x))}

    # ------------------------------------------------------------------ paint
    def paintEvent(self, ev):
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pose = self.pose()
        r = self._owl_rect()
        u = self.owl_h / H     # one canvas unit, px
        # a soft shadow on the floor, shrinking as he rises
        lift = max(0.0, -pose["dy"])
        sw = r.width() * (0.6 - lift * 0.01)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, max(18, 60 - int(lift * 4))))
        p.drawEllipse(QRectF(r.center().x() - sw / 2, r.bottom() - 3, sw, 7))
        # sway about his feet
        p.save()
        foot = QPointF(r.center().x(), r.bottom())
        p.translate(foot)
        p.rotate(pose["rot"])
        p.scale(pose["sx"], pose["sy"])   # squash and stretch, about his feet
        p.translate(-foot)
        body = r.translated(0, pose["dy"])
        draw_owl(p, body, pose["look"], look_y=pose["look_y"], blink=pose["blink"],
                 sad=pose["sad"], tufts=pose["tufts"], clasp=pose["clasp"],
                 flap=pose["flap"], plead=pose["plead"], tear=pose["tear"], beak=pose["beak"])
        p.restore()
        head = QPointF(body.center().x(), body.top() + 18 * u)
        if "puff" in pose:
            k = pose["puff"]
            if 0.25 < k < 0.95:
                q = (k - 0.25) / 0.7
                p.setOpacity(0.7 * (1 - q) * pose.get("puff_a", 1.0))
                p.setBrush(QColor("#d9d2e6"))
                for i in range(3):
                    rr = (3 + 5 * q + i) * u
                    x = body.center().x() + (8 + 30 * q + i * 6) * u
                    y = body.top() + (70 - 8 * q - i * 3) * u
                    p.drawEllipse(QPointF(x, y), rr, rr * 0.8)
                p.setOpacity(1.0)
        if pose.get("ask", 0) > 0.05:
            self._text(p, "?", head.x() + 30 * u, body.top() - 2 * u, 22 * u * pose["ask"],
                       QColor(SPARKLE_COLORS[0]))
        if "zzz" in pose:
            for i in range(3):
                q = (pose["zzz"] * 2.2 - i * 0.35) % 1.3
                if q < 1:
                    p.setOpacity(_bell(q) * pose.get("zzz_a", 1.0))
                    self._text(p, "z", head.x() + (26 + 16 * q + i * 4) * u,
                               head.y() - (8 + 34 * q) * u, (10 + 6 * q) * u,
                               QColor(SPARKLE_COLORS[3]))
            p.setOpacity(1.0)
        if "startle" in pose:
            p.setOpacity(pose.get("startle_a", 1.0))
            self._text(p, "!", head.x() + 28 * u, body.top() + 4 * u,
                       22 * u * _bell(pose["startle"]), QColor(SPARKLE_COLORS[1]))
            p.setOpacity(1.0)
        if "joy" in pose:
            j = pose["joy"]
            for i, col in enumerate(SPARKLE_COLORS * 2):
                a = i * math.pi / 4 + j * 2
                d = (40 + 30 * j) * u
                p.setOpacity(1 - j)
                sparkle(p, head.x() + math.cos(a) * d, head.y() + 10 * u + math.sin(a) * d * 0.8,
                        (4 + 3 * math.sin(j * 9 + i)) * u, QColor(col))
            p.setOpacity(1.0)
        if self.say:
            self._bubble(p, self.say, body)
        p.end()

    def _text(self, p: QPainter, text: str, x: float, y: float, px: float, col: QColor):
        if px < 1:
            return
        f = QFont(self.font())
        f.setBold(True)
        f.setPixelSize(max(1, round(px)))
        p.setFont(f)
        p.setPen(col)
        p.drawText(QPointF(x, y), text)

    def _bubble(self, p: QPainter, text: str, body: QRectF):
        """A comic speech bubble up and to the right of his head, tail to his beak."""
        f = QFont(self.font())
        f.setPixelSize(max(9, round(self.owl_h * 0.12)))
        f.setBold(True)
        p.setFont(f)
        fm = p.fontMetrics()
        room = self.width() - 20
        lines = [text]
        if fm.horizontalAdvance(text) > room and " " in text:
            # a longer translation goes on two lines, broken at the space nearest the
            # middle
            spaces = [i for i, c in enumerate(text) if c == " "]
            cut = min(spaces, key=lambda i: abs(i - len(text) / 2))
            lines = [text[:cut], text[cut + 1:]]
        tw = max(fm.horizontalAdvance(t) for t in lines)
        if tw > room:
            return   # no room for the whole line: say nothing rather than half of it
        pad = 7
        bw, bh = tw + 2 * pad, fm.height() * len(lines) + 2 * pad - 4
        x = max(2.0, min(body.right() + 2, self.width() - bw - 2))
        y = max(2.0, body.top() - bh * 0.35)
        box = QRectF(x, y, bw, bh)
        tail = QPainterPath(QPointF(box.left() + 10, box.bottom() - 2))
        tail.lineTo(body.center().x() + body.width() * 0.34, body.top() + body.height() * 0.27)
        tail.lineTo(box.left() + 22, box.bottom() - 2)
        shape = QPainterPath()
        radius = (fm.height() + 2 * pad - 4) / 2   # one line's: two lines aren't a pill
        shape.addRoundedRect(box, radius, radius)
        shape = shape.united(tail)
        p.setPen(QPen(INK, 1.6))
        p.setBrush(BUBBLE)
        p.drawPath(shape)
        p.setPen(INK)
        p.drawText(box.adjusted(pad, 0, -pad, 0), Qt.AlignmentFlag.AlignCenter, "\n".join(lines))
