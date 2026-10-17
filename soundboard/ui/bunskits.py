"""Bun's idle skits: a little act for each theme, played now and then while he's idle.

Blood Moon's Bun reaches behind him, grabs the moon out of the sky and takes a bite: it's
cheese. Retro 98's pixel shades drop onto his face ("deal with it"), Brainrot's
propeller lifts him off the ground, Swamp's frog hat snaps up a fly, and so on: one per
theme outfit (style/bunnyfit.py), and a juggling act for the themes without one.

A skit is a function of its time alone, `skit(kit, t)`: it adds to his pose (`kit.add`,
`kit.most`), hides outfit pieces it's moving (`kit.hide`) and queues drawings
(`kit.behind` / `kit.front` / `kit.world`), all on Bun's 100 x 120 canvas. Being a
function of time, any frame can be drawn on its own (pictures, tests) and nothing is
left over when it ends. BunnyWidget (`skit()`, `pose`, `paintEvent`) plays them and
draws the queue: `behind` before him, `front` with him (held things move as he does),
`world` after him, standing still.

Everything stays inside his widget's box (a little round him: MASCOT.md), and no skit
shows words: symbols only ("!", "?"), so nothing needs translating.
"""
from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QRadialGradient

from soundboard import theme
from soundboard.bunny import FUR, INK, music_note, sparkle
from soundboard.style import bunnyfit

Draw = Callable[[QPainter], None]
PEN = 2.4                   # his outline's width on the canvas
NEXT_PROB = 0.55            # an idle moment's chance of a skit instead of a fidget
CHEESE, CHEESE_DARK = QColor("#ffd34d"), QColor("#e0a92a")


class Kit:
    """What a skit does to one frame: pose changes, hidden pieces and drawings."""
    __slots__ = ("pose", "hide", "behind", "front", "world", "prop", "flash")

    def __init__(self):
        self.pose: dict[str, float] = {}
        self.hide: set[str] = set()
        self.behind: list[Draw] = []
        self.front: list[Draw] = []
        self.world: list[Draw] = []
        self.prop: str | None = None   # (None: as he is; "": nothing in his paw)
        self.flash = 0.0                # a white flash over everything (Flashbang)

    def add(self, **kw: float):
        """Moves on top of his pose: dy / dx (canvas units), angle, ears, nod, dip, sx, sy."""
        for k, v in kw.items():
            self.pose[k] = self.pose.get(k, 0.0) + v

    def most(self, **kw: float):
        """Faces: mouth, blink, sad, angry, smug (the bigger of his own and this)."""
        for k, v in kw.items():
            self.pose[k] = max(self.pose.get(k, 0.0), v)


# ---------------------------------------------------------------------- timing
def seg(t: float, a: float, b: float) -> float:
    """0 before `a`, 1 after `b`, a straight line between."""
    return 0.0 if t <= a else 1.0 if t >= b else (t - a) / (b - a)


def ease(k: float) -> float:
    return k * k * (3 - 2 * k)


def eseg(t: float, a: float, b: float) -> float:
    return ease(seg(t, a, b))


def bump(t: float, a: float, b: float) -> float:
    """Up and back down between `a` and `b` (0 outside)."""
    return math.sin(math.pi * seg(t, a, b)) if a < t < b else 0.0


def held(t: float, a: float, b: float, fade: float = 0.25) -> float:
    """1 from `a` to `b`, easing in and out over `fade` seconds."""
    return min(eseg(t, a, a + fade), 1 - eseg(t, b - fade, b))


def lerp(a: float, b: float, k: float) -> float:
    return a + (b - a) * k


def _rand(i: int, salt: int = 0) -> float:
    """A steady 'random' number 0..1 for particle `i` (the same on every frame)."""
    x = math.sin(i * 12.9898 + salt * 78.233) * 43758.5453
    return x - math.floor(x)


# ---------------------------------------------------------------------- drawing kit
def _ink(width: float = PEN) -> QPen:
    pen = QPen(INK, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _oval(p: QPainter, x, y, w, h, fill, pen: QPen | None = None, angle: float = 0.0):
    p.save()
    p.translate(x, y)
    p.rotate(angle)
    p.setPen(pen or Qt.PenStyle.NoPen)
    p.setBrush(fill)
    p.drawEllipse(QRectF(-w / 2, -h / 2, w, h))
    p.restore()


def paw(p: QPainter, x: float, y: float, angle: float = 0.0):
    """One of his paws (they're only drawn when they hold something)."""
    _oval(p, x, y, 12, 10.5, FUR, _ink(), angle)


def mark(p: QPainter, x: float, y: float, kind: str = "!", k: float = 1.0):
    """A cartoon "!" (surprise) or "?" above his head, popping in by `k` (0..1)."""
    if k <= 0:
        return
    p.save()
    p.translate(x, y)
    s = 0.6 + 0.4 * k + 0.15 * math.sin(math.pi * k)
    p.scale(s, s)
    p.setOpacity(min(1.0, k * 2))
    col = QColor("#ff4d6d") if kind == "!" else QColor(theme.T["accent"])
    if kind == "!":
        bar = QPainterPath()
        bar.moveTo(-3, -14)
        bar.lineTo(3, -14)
        bar.lineTo(1.5, 1)
        bar.lineTo(-1.5, 1)
        bar.closeSubpath()
        p.setPen(_ink(1.6))
        p.setBrush(col)
        p.drawPath(bar)
        p.drawEllipse(QRectF(-2.4, 3.5, 4.8, 4.8))
    else:
        f = QFont()
        f.setPixelSize(20)
        f.setBold(True)
        path = QPainterPath()
        path.addText(-6, 7, f, "?")
        p.setPen(_ink(1.6))
        p.setBrush(col)
        p.drawPath(path)
    p.restore()


def puff(p: QPainter, x: float, y: float, r: float, alpha: float, col: QColor | None = None):
    c = QColor(col or QColor("#d9d2e6"))
    c.setAlphaF(max(0.0, min(1.0, alpha)) * c.alphaF())
    _oval(p, x, y, 2 * r, 2 * r, c)


def burst(p: QPainter, t: float, x: float, y: float, n: int, speed: float, life: float,
          draw: Callable[[QPainter, float, float, float, int], None], gravity: float = 60.0,
          salt: int = 0, up: float = 0.4):
    """Particles flying out of (x, y) `t` seconds after they started: `draw(p, x, y,
    fade, i)` for each one still alive. Same every frame for the same `t`."""
    if t < 0 or t > life:
        return
    k = t / life
    for i in range(n):
        a = _rand(i, salt) * 2 * math.pi
        v = speed * (0.4 + 0.6 * _rand(i, salt + 1))
        px = x + math.cos(a) * v * t
        py = y + (math.sin(a) - up) * v * t + 0.5 * gravity * t * t
        draw(p, px, py, (1 - k) ** 1.3, i)


def _sparkles(p: QPainter, t, x, y, n=8, life=0.9, salt=0, cols=None):
    cols = cols or ("#ffcf40", "#ff8fae", "#1fb6ff", "#a48bff")

    def one(p, px, py, fade, i):
        c = QColor(cols[i % len(cols)])
        c.setAlphaF(fade)
        sparkle(p, px, py, 2.5 + 2.5 * fade, c)
    burst(p, t, x, y, n, 40, life, one, gravity=10, salt=salt)


def piece(p: QPainter, name: str, dx: float = 0.0, dy: float = 0.0, angle: float = 0.0,
          pivot: tuple[float, float] = (50, 50), scale: float = 1.0, alpha: float = 1.0):
    """One of his outfit pieces, moved: `dx`/`dy` off its place, turned `angle` and
    scaled round `pivot`."""
    fn = bunnyfit.PIECES.get(name, ("", None))[1]
    if fn is None or alpha <= 0:
        return
    p.save()
    p.setOpacity(p.opacity() * alpha)
    p.translate(pivot[0] + dx, pivot[1] + dy)
    p.rotate(angle)
    p.scale(scale, scale)
    p.translate(-pivot[0], -pivot[1])
    fn(p, _ink())
    p.restore()


def heart(p: QPainter, x: float, y: float, r: float, col: QColor):
    path = QPainterPath(QPointF(x, y + r * 0.9))
    path.cubicTo(QPointF(x - r * 1.6, y - r * 0.2), QPointF(x - r * 0.6, y - r * 1.4),
                 QPointF(x, y - r * 0.45))
    path.cubicTo(QPointF(x + r * 0.6, y - r * 1.4), QPointF(x + r * 1.6, y - r * 0.2),
                 QPointF(x, y + r * 0.9))
    p.setPen(_ink(1.4))
    p.setBrush(col)
    p.drawPath(path)


def _surprised(kit: Kit, t: float, a: float, b: float, x: float = 78, y: float = 20):
    """Eyes wide, ears straight up, a jump and a "!" between `a` and `b`."""
    k = held(t, a, b, 0.12)
    if k <= 0:
        return
    kit.add(ears=-14 * k, dy=-7 * bump(t, a, a + 0.35))
    kit.most(mouth=0.4 * k)
    kit.world.append(lambda p: mark(p, x, y, "!", seg(t, a, a + 0.2) * k))


def _sneeze(kit: Kit, t: float, at: float):
    """Winding up (eyes shut, head back) then ACHOO at `at`: head forward, ears fling."""
    wind = held(t, at - 0.55, at, 0.3)
    kit.add(dip=-3 * wind, nod=-4 * wind)
    kit.most(blink=wind, mouth=0.5 * wind)
    hit = bump(t, at, at + 0.35)
    kit.add(dip=9 * hit, ears=18 * hit, dy=2 * hit, sy=-0.05 * hit)


# ---------------------------------------------------------------------- the skits
def blood_moon(kit: Kit, t: float):
    """Looks up, reaches back, pulls the moon down, bites it: cheese! He tosses it back."""
    look = held(t, 0.0, 4.7, 0.5)
    kit.add(dip=-3 * look, nod=-6 * look * (1 - seg(t, 1.3, 1.9)), ears=6 * look)
    pull, toss = eseg(t, 1.3, 2.1), eseg(t, 3.9, 4.6)
    in_paw = 1.3 <= t < 4.6
    if in_paw:
        kit.hide.add("moon")
    # where the moon is: in the sky behind him, then in his paw by his mouth, then back up
    mouth_k = eseg(t, 2.1, 2.35) * (1 - eseg(t, 2.6, 2.9))
    hx, hy = lerp(72, 62, mouth_k), lerp(84, 80, mouth_k)
    if t < 3.9:
        cx, cy, r = lerp(50, hx, pull), lerp(48, hy, pull), lerp(37, 13, pull)
    else:
        cx, cy, r = lerp(hx, 50, toss), lerp(hy, 48, toss) - 30 * bump(t, 3.9, 4.6), \
            lerp(13, 37, toss)
    cheese = eseg(t, 2.4, 2.9) * (1 - eseg(t, 4.1, 4.6))
    bitten = 2.35 <= t
    reach = eseg(t, 0.6, 1.3) * (1 - pull)
    if in_paw:
        front = t >= 1.7 and t < 4.2   # (it comes round in front of him as he pulls it)
        draw = (lambda p: _moon(p, cx, cy, r, cheese, bitten))
        (kit.front if front else kit.behind).append(draw)
        kit.front.append(lambda p: paw(p, cx + r * 0.55, cy + r * 0.45))
    elif t < 1.3:
        kit.front.append(lambda p: paw(p, lerp(78, 82, reach), lerp(100, 34, reach)))
    kit.prop = ""
    if 2.1 <= t < 2.35:
        kit.most(mouth=0.8 * seg(t, 2.1, 2.3))
    chomp = bump(t, 2.33, 2.5)
    kit.add(sy=-0.06 * chomp, dip=2 * chomp)
    if 2.4 <= t < 3.0:
        kit.most(mouth=0.15 + 0.2 * abs(math.sin(t * 22)))
    kit.world.append(lambda p: burst(p, t - 2.35, 62, 76, 7, 30, 0.7, _crumb, salt=3))
    _surprised(kit, t, 3.0, 3.9)


def _crumb(p, x, y, fade, i):
    c = QColor(CHEESE)
    c.setAlphaF(fade)
    _oval(p, x, y, 3.2, 2.6, c, None, i * 40)


def _moon(p: QPainter, cx, cy, r, cheese: float, bitten: bool):
    red_hi, red_lo = QColor("#ff8a4d"), QColor("#c2361f")

    def mix(a: QColor, b: QColor, k: float) -> QColor:
        return QColor.fromRgbF(lerp(a.redF(), b.redF(), k), lerp(a.greenF(), b.greenF(), k),
                               lerp(a.blueF(), b.blueF(), k))
    body = QPainterPath()
    body.addEllipse(QPointF(cx, cy), r, r)
    if bitten:
        bite = QPainterPath()
        for bx, by, br in ((0.62, -0.55, 0.36), (0.85, -0.18, 0.3), (0.3, -0.8, 0.28)):
            bite.addEllipse(QPointF(cx + bx * r, cy + by * r), br * r, br * r)
        body = body.subtracted(bite)
    grad = QRadialGradient(cx - r * 0.3, cy - r * 0.4, r * 1.4)
    grad.setColorAt(0, mix(red_hi, QColor("#fff1a8"), cheese))
    grad.setColorAt(1, mix(red_lo, CHEESE_DARK, cheese))
    p.setPen(QPen(mix(QColor("#6e170e"), QColor("#9a6a12"), cheese), max(1.2, r * 0.05)))
    p.setBrush(grad)
    p.drawPath(body)
    p.save()
    p.setClipPath(body)
    hole = mix(QColor(140, 30, 16), QColor("#d29a22"), cheese)
    hole.setAlpha(round(lerp(120, 255, cheese)))
    for x, y, rr in ((-0.6, -0.37, 0.14), (0.62, -0.54, 0.11), (0.81, 0.11, 0.15),
                     (-0.76, 0.27, 0.1), (0.2, 0.45, 0.13), (-0.15, -0.05, 0.09)):
        _oval(p, cx + x * r, cy + y * r, 2 * rr * r, 2 * rr * r, hole)
    p.restore()


def deal_with_it(kit: Kit, t: float):
    """Retro 98: the pixel shades come off, then drop back down onto his face."""
    kit.hide.add("pixel_shades")
    off = eseg(t, 0.0, 0.5)
    down = seg(t, 1.0, 2.2) ** 2          # (falling: speeding up)
    y = -70 * off if t < 1.0 else -70 * (1 - down)
    alpha = 1 - seg(t, 0.35, 0.55) if t < 1.0 else min(1.0, seg(t, 1.0, 1.2) * 1.5)
    land = bump(t, 2.2, 2.45)
    kit.add(sy=-0.05 * land, dy=1.5 * land)
    kit.front.append(lambda p: piece(p, "pixel_shades", 0, y + 2 * land, 0, (50, 60), 1, alpha))
    if t >= 2.2:
        kit.most(smug=1.0)
        kit.add(nod=3 * bump(t, 2.6, 3.3), dip=2 * bump(t, 2.6, 3.0))
    elif 0.55 < t < 1.0:
        kit.most(blink=bump(t, 0.6, 0.8))   # (his own eyes, for a moment)


def propeller(kit: Kit, t: float):
    """Brainrot: the propeller spins up and lifts him off the ground, then he drops."""
    kit.hide.add("propeller")
    spin = seg(t, 0.0, 1.0) * (1 - seg(t, 2.5, 2.9))
    turns = 6 * t * t if t < 1.0 else 6 + 18 * (t - 1.0)
    lift = eseg(t, 1.0, 1.6) * (1 - seg(t, 2.6, 2.85) ** 2)
    kit.add(dy=-16 * lift, angle=4 * math.sin(t * 7) * lift, ears=10 * lift)
    land = bump(t, 2.85, 3.15)
    kit.add(sy=-0.12 * land, sx=0.08 * land)
    kit.most(mouth=0.35 * lift, blink=0.0)
    kit.front.append(lambda p: _propeller(p, turns, spin))
    if t > 2.9:
        for dx in (-22, 22):
            kit.world.append(lambda p, dx=dx: puff(p, 50 + dx, 117, 5, 1 - seg(t, 2.9, 3.4)))


def _propeller(p: QPainter, turns: float, spin: float):
    piece(p, "propeller")   # the cap
    p.save()
    p.translate(50, 20)
    w = 17 * abs(math.cos(turns * math.pi))   # the blades, turning (seen side on)
    blur = QColor("#2f7bff")
    blur.setAlphaF(0.35 * spin)
    if spin > 0.5:
        _oval(p, 0, 0, 36, 5, blur)
    for sx, col in ((1, "#e8432b"), (-1, "#3cc46a")):
        path = QPainterPath(QPointF(0, 0))
        path.quadTo(QPointF(sx * w * 0.5, -3), QPointF(sx * w, -1))
        path.quadTo(QPointF(sx * w * 0.5, 2.5), QPointF(0, 0))
        p.setPen(_ink(1.2))
        p.setBrush(QColor(col))
        p.drawPath(path)
    _oval(p, 0, 0, 4, 4, QColor("#ffcf40"), _ink(1.2))
    p.restore()


def frog_fly(kit: Kit, t: float):
    """Swamp: a fly buzzes round, the frog hat's tongue snaps it up. Bun: "!"."""
    caught = t >= 1.75
    if not caught:
        fx = lerp(-8, 50, seg(t, 0, 1.6)) + 10 * math.sin(t * 6)
        fy = 14 + 8 * math.sin(t * 9) - 6 * seg(t, 0, 1.6)
        kit.world.append(lambda p: _fly(p, fx, fy, t))
        kit.add(angle=-4 * held(t, 0.3, 1.6), nod=-6 * held(t, 0.3, 1.6))
    tongue = bump(t, 1.55, 1.85)
    if tongue:
        kit.front.append(lambda p: _tongue(p, 50, 28, 46, 6, tongue))
    _surprised(kit, t, 1.9, 2.9)
    if t > 2.9:
        kit.most(smug=held(t, 2.9, 3.4, 0.1))


def _fly(p: QPainter, x, y, t):
    wing = QColor(220, 235, 255, 170)
    flap = 3 * abs(math.sin(t * 60))
    _oval(p, x - 2, y - 2 - flap / 2, 5, 3 + flap, wing)
    _oval(p, x + 2, y - 2 - flap / 2, 5, 3 + flap, wing)
    _oval(p, x, y, 5, 4, QColor("#2b2340"))


def _tongue(p: QPainter, x0, y0, x1, y1, k):
    pen = QPen(QColor("#ff6f91"), 3)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    x, y = lerp(x0, x1, k), lerp(y0, y1, k)
    p.drawLine(QPointF(x0, y0), QPointF(x, y))
    _oval(p, x, y, 5, 5, QColor("#ff6f91"))


def laser(kit: Kit, t: float):
    """Deep Fried: the laser eyes flare and sweep, something goes boom, he blinks sweetly."""
    flare = held(t, 0.3, 1.5, 0.15)
    sweep = lerp(-25, 20, eseg(t, 0.3, 1.5))
    if flare:
        kit.world.append(lambda p: _beams(p, sweep, flare))
        kit.add(dx=0.8 * math.sin(t * 50) * flare)
    boom = t - 1.4
    kit.world.append(lambda p: burst(p, boom, 98, 104, 9, 28, 0.8, _ember, gravity=20, salt=5))
    if 1.4 < t < 2.4:
        kit.world.append(lambda p: puff(p, 98, 102, 4 + 10 * seg(t, 1.4, 1.8),
                                        1 - seg(t, 1.6, 2.4), QColor(120, 110, 130, 200)))
    kit.most(blink=bump(t, 2.2, 2.4) + bump(t, 2.5, 2.7))   # a double blink: innocent
    kit.most(smug=held(t, 2.7, 3.2, 0.1))


def _beams(p: QPainter, angle, k):
    for x in (39, 61):
        p.save()
        p.translate(x, 62)
        p.rotate(angle)
        glow = QColor(255, 60, 60, round(110 * k))
        p.setPen(QPen(glow, 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(0, 0), QPointF(70, 0))
        p.setPen(QPen(QColor(255, 230, 230, round(255 * k)), 2.2, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(0, 0), QPointF(70, 0))
        p.restore()


def _ember(p, x, y, fade, i):
    c = QColor("#ffb84d" if i % 2 else "#ff4d3a")
    c.setAlphaF(fade)
    _oval(p, x, y, 3, 3, c)


def bat(kit: Kit, t: float):
    """Vampire: a swirl of his cape and he's a bat, flapping a loop, then back."""
    gone = held(t, 0.5, 3.4, 0.3)
    kit.pose["alpha"] = 1 - gone
    kit.add(sx=-0.4 * gone, sy=-0.4 * gone)
    for at in (0.5, 3.3):
        kit.world.append(lambda p, at=at: _poof(p, t, at))
    if 0.8 < t < 3.2:
        u = seg(t, 0.8, 3.2) * 2 * math.pi
        x, y = 50 + 34 * math.sin(u), 52 - 18 * math.sin(2 * u)
        kit.world.append(lambda p: _bat(p, x, y, t, math.cos(u)))
    if t > 3.4:
        kit.most(smug=held(t, 3.5, 4.3, 0.1), mouth=0.0)


def _poof(p: QPainter, t, at):
    """A puff of purple smoke at `at` (his cape's swirl)."""
    if t < at:
        return
    for dx, dy in ((-10, 0), (10, -4), (0, 8), (0, -12)):
        puff(p, 50 + dx, 86 + dy, 9 * (0.6 + seg(t, at, at + 0.4)),
             (1 - seg(t, at, at + 0.6)) * 0.9, QColor(90, 70, 110, 200))


def _bat(p: QPainter, x, y, t, facing):
    flap = math.sin(t * 22)
    p.save()
    p.translate(x, y)
    p.scale(1.7 if facing >= 0 else -1.7, 1.7)
    col = QColor("#6b4a8c")
    for sx in (1, -1):
        wing = QPainterPath(QPointF(0, 0))
        tip = QPointF(sx * 15, -8 * flap)
        wing.quadTo(QPointF(sx * 8, -10 * flap - 3), tip)
        wing.quadTo(QPointF(sx * 11, 2), QPointF(sx * 7, 1))
        wing.quadTo(QPointF(sx * 4, 4), QPointF(0, 2))
        p.setPen(_ink(1.2))
        p.setBrush(col)
        p.drawPath(wing)
    _oval(p, 0, 0, 7, 8, col, _ink(1.2))
    _oval(p, -1.5, -1, 1.6, 1.6, QColor("#ff4d6d"))
    _oval(p, 1.5, -1, 1.6, 1.6, QColor("#ff4d6d"))
    p.restore()


def wizard(kit: Kit, t: float):
    """Midnight: a flick of his wand makes a rain cloud, by mistake. Another flick: gone."""
    up = held(t, 0.3, 3.4, 0.3)
    wx, wy = 80, lerp(100, 74, up)
    kit.front.append(lambda p: _wand(p, wx, wy, 20 * bump(t, 0.9, 1.1) + 25 * bump(t, 2.4, 2.6)))
    kit.prop = ""
    kit.world.append(lambda p: _sparkles(p, t - 1.0, 96, 52, salt=1))
    cloud = held(t, 1.1, 2.6, 0.2)
    if cloud:
        kit.world.append(lambda p: _rain_cloud(p, 50, -5, cloud, t))
        kit.most(sad=0.7 * held(t, 1.4, 2.6, 0.2))
        kit.add(dip=2 * held(t, 1.4, 2.6))
    kit.world.append(lambda p: _sparkles(p, t - 2.55, 50, 8, n=10, salt=2))
    kit.add(dy=-6 * bump(t, 2.8, 3.2) - 4 * bump(t, 3.2, 3.5))
    kit.most(blink=held(t, 2.8, 3.5, 0.05))


def _wand(p: QPainter, x, y, angle):
    p.save()
    p.translate(x, y)
    p.rotate(-30 + angle)
    p.setPen(QPen(QColor("#3a3452"), 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(0, 0), QPointF(0, -20))
    sparkle(p, 0, -22, 4.5, QColor("#ffcf40"))
    p.restore()
    paw(p, x, y)


def _rain_cloud(p: QPainter, x, y, k, t):
    p.save()
    p.setOpacity(k)
    col = QColor("#8b8fa3")
    for dx, dy, r in ((-10, 2, 8), (0, -3, 10), (11, 2, 8), (0, 4, 9)):
        _oval(p, x + dx, y + dy, 2 * r, 2 * r, col)
    drop = QColor("#6ec6ff")
    p.setPen(QPen(drop, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for i in range(6):
        fall = (t * 1.6 + _rand(i, 9)) % 1.0
        dx = -14 + i * 5.6
        yy = y + 10 + fall * 34
        p.drawLine(QPointF(x + dx, yy), QPointF(x + dx - 0.6, yy + 3.5))
    p.restore()


def spyglass(kit: Kit, t: float):
    """Ocean: the captain looks out through his spyglass. A fish! It leaps."""
    up = held(t, 0.2, 2.4, 0.3)
    look = math.sin(seg(t, 0.5, 2.2) * 2 * math.pi) * up
    kit.add(angle=5 * look, nod=6 * look)
    if up:
        kit.front.append(lambda p: _spyglass(p, up))
    kit.prop = ""
    _surprised(kit, t, 2.3, 3.2)
    u = seg(t, 2.4, 3.4)
    if 0 < u < 1:
        x, y = lerp(-4, 34, u), 118 - 40 * math.sin(math.pi * u)
        kit.world.append(lambda p: _fish(p, x, y, -60 + 120 * u))
    for at, x in ((2.4, -4), (3.4, 34)):
        kit.world.append(lambda p, at=at, x=x: burst(p, t - at, x, 116, 6, 26, 0.6, _drop,
                                                     gravity=90, salt=7, up=1.0))


def _spyglass(p: QPainter, k):
    p.save()
    p.translate(64, 62)
    p.rotate(-12)
    p.setOpacity(k)
    p.setPen(_ink(1.6))
    p.setBrush(QColor("#9a6532"))
    p.drawRoundedRect(QRectF(0, -5, 18, 10), 2, 2)
    p.setBrush(QColor("#ffcf40"))
    p.drawRoundedRect(QRectF(16, -6.5, 14, 13), 2, 2)
    p.setBrush(QColor("#9fd9ff"))
    p.drawEllipse(QRectF(28, -5.5, 4, 11))
    p.restore()
    paw(p, 70, 74)


def _fish(p: QPainter, x, y, angle):
    p.save()
    p.translate(x, y)
    p.rotate(angle)
    col = QColor("#ff9f43")
    tail = QPainterPath(QPointF(-6, 0))
    tail.lineTo(-12, -5)
    tail.lineTo(-12, 5)
    tail.closeSubpath()
    p.setPen(_ink(1.2))
    p.setBrush(col)
    p.drawPath(tail)
    p.drawEllipse(QRectF(-7, -4.5, 15, 9))
    _oval(p, 4, -1, 2, 2, INK)
    p.restore()


def _drop(p, x, y, fade, i):
    c = QColor("#6ec6ff")
    c.setAlphaF(fade)
    _oval(p, x, y, 2.6, 3.4, c)


def achoo(kit: Kit, t: float):
    """Arctic: snow falls, he shivers, then sneezes."""
    kit.world.append(lambda p: _snow(p, t, held(t, 0, 3.6, 0.4)))
    shiver = held(t, 0.3, 1.8, 0.2)
    kit.add(dx=1.2 * math.sin(t * 55) * shiver, ears=-4 * shiver)
    kit.most(blink=0.4 * shiver)
    _sneeze(kit, t, 2.25)
    kit.world.append(lambda p: _sneeze_cloud(p, t, 2.25))


def _sneeze_cloud(p: QPainter, t, at):
    if t <= at:
        return
    k = seg(t, at, at + 0.65)
    for dx, dy in ((-1, 0.2), (1, 0.3), (0, 0.6)):
        puff(p, 50 + dx * k * 22, 76 + dy * 10 * k, 5 + 4 * k, 1 - seg(t, at + 0.05, at + 0.65),
             QColor(235, 245, 255, 220))


def _snow(p: QPainter, t, k):
    if k <= 0:
        return
    col = QColor(255, 255, 255, round(220 * k))
    for i in range(14):
        fall = (t * 0.3 + _rand(i, 4)) % 1.0
        x = -8 + 116 * _rand(i, 5) + 4 * math.sin(t * 2 + i)
        y = -6 + fall * 128
        _oval(p, x, y, 3, 3, col)


def crown(kit: Kit, t: float):
    """Royal: the crown slips over his eyes; he pushes it back and gives it a polish."""
    kit.hide.add("crown")
    slip = eseg(t, 0.2, 0.6) * (1 - eseg(t, 1.6, 2.1))
    blind = held(t, 0.6, 1.6, 0.1)
    kit.add(dx=1.6 * math.sin(t * 9) * blind, angle=3 * math.sin(t * 5) * blind)
    kit.front.append(lambda p: piece(p, "crown", 0, 20 * slip, 6 * slip, (50, 30)))
    push = held(t, 1.4, 2.2, 0.15)
    rub = held(t, 2.3, 3.2, 0.15)
    if push or rub:
        x = 64 + 4 * math.sin(t * 24) * rub
        y = lerp(48, 32, eseg(t, 1.4, 2.0)) if push else 34
        kit.front.append(lambda p: paw(p, x, y))
        kit.prop = ""
    kit.world.append(lambda p: _sparkles(p, t - 3.1, 56, 18, n=5, salt=8))
    kit.most(smug=held(t, 3.2, 3.6, 0.1))


def onion(kit: Kit, t: float):
    """Onion: he peels a layer off his onion hat and his eyes water."""
    peel = eseg(t, 0.5, 1.5)
    kit.prop = ""
    if t < 1.9:
        kit.front.append(lambda p: _peel(p, peel, 1 - seg(t, 1.5, 1.9)))
        kit.front.append(lambda p: paw(p, lerp(62, 86, peel), lerp(30, 20, peel)))
    cry = held(t, 1.3, 3.0, 0.3)
    kit.most(sad=0.8 * cry)
    kit.add(ears=10 * cry)
    if cry:
        kit.world.append(lambda p: _tears(p, t, cry))
    kit.most(blink=held(t, 3.1, 3.4, 0.05))   # a big sniff, eyes screwed shut
    kit.add(dip=-2 * bump(t, 3.05, 3.4))


def _peel(p: QPainter, k, alpha):
    p.save()
    p.setOpacity(alpha)
    p.translate(60 + 26 * k, 26 - 6 * k)
    p.rotate(80 * k)
    path = QPainterPath(QPointF(-6, -10))
    path.quadTo(QPointF(4, 0), QPointF(-2, 12))
    path.quadTo(QPointF(8, 2), QPointF(-6, -10))
    p.setPen(_ink(1.4))
    p.setBrush(QColor("#c77dde"))
    p.drawPath(path)
    p.restore()


def _tears(p: QPainter, t, k):
    col = QColor("#8fd3ff")
    for i, x in enumerate((36, 64, 38, 62)):
        fall = (t * 1.4 + i * 0.37) % 1.0
        c = QColor(col)
        c.setAlphaF(k * (1 - fall))
        _oval(p, x + (i % 2) * 2, 70 + fall * 26, 3, 4, c)


def geiger(kit: Kit, t: float):
    """Toxic: the Geiger counter in his paw goes wild and he glows green."""
    up = held(t, 0.2, 3.2, 0.3)
    wild = held(t, 0.9, 2.5, 0.2)
    kit.prop = ""
    if up:
        kit.front.append(lambda p: _geiger(p, up, wild, t))
    if wild:
        kit.behind.append(lambda p: _glow(p, wild * (0.6 + 0.4 * math.sin(t * 14))))
        kit.add(ears=-12 * wild, dx=0.8 * math.sin(t * 40) * wild)
        kit.most(mouth=0.35 * wild)
    _surprised(kit, t, 1.0, 1.8)


def _geiger(p: QPainter, k, wild, t):
    p.save()
    p.setOpacity(k)
    p.setPen(_ink(1.6))
    p.setBrush(QColor("#f2c230"))
    p.drawRoundedRect(QRectF(66, 84, 22, 16), 3, 3)
    p.setBrush(QColor("#f4f6e8"))
    p.drawRoundedRect(QRectF(69, 86.5, 16, 8), 2, 2)
    a = math.radians(-150 + 120 * (0.2 + 0.8 * wild * (0.6 + 0.4 * math.sin(t * 30))))
    p.setPen(QPen(QColor("#ff4d3a"), 1.3))
    p.drawLine(QPointF(77, 94), QPointF(77 + 7 * math.cos(a), 94 + 7 * math.sin(a)))
    p.restore()
    paw(p, 70, 100)


def _glow(p: QPainter, k):
    g = QRadialGradient(50, 70, 58)
    g.setColorAt(0, QColor(120, 255, 90, round(120 * k)))
    g.setColorAt(1, QColor(120, 255, 90, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawEllipse(QRectF(-8, 12, 116, 116))


def leaf(kit: Kit, t: float):
    """Forest: a leaf floats down and lands on his nose. He sneezes it off."""
    if t < 1.6:
        u = seg(t, 0, 1.6)
        x, y, a = lerp(80, 50, u) + 12 * math.sin(u * 7), lerp(-6, 70, u), 40 * math.sin(u * 7)
    elif t < 2.3:
        x, y, a = 50, 70, 10
    else:
        u = seg(t, 2.3, 3.4)
        x, y, a = 50 + 60 * u, 70 - 30 * u + 40 * u * u, 400 * u
    alive = t < 3.4
    if alive:
        (kit.front if 1.6 <= t < 2.3 else kit.world).append(lambda p: _leaf(p, x, y, a))
    kit.add(nod=-5 * held(t, 0.4, 1.6), dip=-2 * held(t, 0.4, 1.6))
    kit.most(blink=0.45 * held(t, 1.6, 1.8, 0.05))   # (cross-eyed at it)
    _sneeze(kit, t, 2.3)


def _leaf(p: QPainter, x, y, a):
    p.save()
    p.translate(x, y)
    p.rotate(a)
    path = QPainterPath(QPointF(-8, 0))
    path.quadTo(QPointF(0, -6), QPointF(8, 0))
    path.quadTo(QPointF(0, 6), QPointF(-8, 0))
    p.setPen(QPen(QColor("#2f6b2a"), 1.2))
    p.setBrush(QColor("#5cb85c"))
    p.drawPath(path)
    p.drawLine(QPointF(-8, 0), QPointF(7, 0))
    p.restore()


def coffee(kit: Kit, t: float):
    """Mocha: a sip of coffee... and the caffeine kicks in."""
    cup = held(t, 0.2, 1.8, 0.3)
    kit.prop = ""
    if cup:
        sip = held(t, 0.6, 1.4, 0.2)
        x, y = lerp(76, 60, sip), lerp(98, 84, sip)
        kit.front.append(lambda p: _cup(p, x, y, cup, t))
        kit.most(blink=sip)
        kit.add(dip=-2 * sip)
    jitter = held(t, 1.9, 3.4, 0.15)
    kit.add(dx=1.8 * math.sin(t * 70) * jitter, ears=-14 * jitter,
            dy=-3 * abs(math.sin(t * 16)) * jitter)
    kit.most(mouth=0.25 * jitter)


def _cup(p: QPainter, x, y, k, t):
    p.save()
    p.setOpacity(k)
    p.setPen(_ink(1.6))
    p.setBrush(QColor("#f6efe6"))
    p.drawRoundedRect(QRectF(x - 6, y - 7, 12, 12), 2.5, 2.5)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(x + 4, y - 4, 6, 6), -90 * 16, 180 * 16)
    p.setPen(QPen(QColor(200, 200, 210, 150), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for i in (-2, 2):
        steam = QPainterPath(QPointF(x + i, y - 9))
        steam.quadTo(QPointF(x + i + 3 * math.sin(t * 5 + i), y - 13), QPointF(x + i, y - 17))
        p.drawPath(steam)
    p.restore()
    paw(p, x + 2, y + 5)


def coconut(kit: Kit, t: float):
    """Sunset: a sip from his coconut, then a lazy hula sway, eyes shut."""
    cup = held(t, 0.2, 1.6, 0.3)
    kit.prop = ""
    if cup:
        kit.front.append(lambda p: _coconut(p, lerp(78, 64, held(t, 0.5, 1.3, 0.2)), cup))
    sway = held(t, 1.4, 3.8, 0.4)
    kit.add(angle=7 * math.sin(t * 3.4) * sway, dx=3 * math.sin(t * 3.4) * sway,
            nod=4 * math.sin(t * 3.4 + 0.6) * sway)
    kit.most(blink=sway)


def _coconut(p: QPainter, x, k):
    p.save()
    p.setOpacity(k)
    _oval(p, x, 90, 15, 13, QColor("#8a5a2b"), _ink(1.6))
    p.setPen(QPen(QColor("#ff8fae"), 1.8))
    p.drawLine(QPointF(x + 2, 85), QPointF(x - 4, 76))
    umb = QPainterPath(QPointF(x + 2, 80))
    umb.quadTo(QPointF(x + 8, 74), QPointF(x + 14, 80))
    umb.closeSubpath()
    p.setPen(_ink(1.0))
    p.setBrush(QColor("#ffcf40"))
    p.drawPath(umb)
    p.restore()
    paw(p, x + 5, 96)


def mint(kit: Kit, t: float):
    """Mint: he pops a mint leaf in, chews, and breathes out an icy cloud."""
    kit.prop = ""
    pop = eseg(t, 0.2, 0.8)
    if t < 0.85:
        kit.front.append(lambda p: _leaf(p, lerp(80, 52, pop), lerp(96, 78, pop), 30))
        kit.front.append(lambda p: paw(p, lerp(82, 56, pop), lerp(100, 82, pop)))
    if 0.8 < t < 1.7:
        kit.most(mouth=0.1 + 0.2 * abs(math.sin(t * 20)))
    breath = held(t, 1.8, 2.8, 0.15)
    kit.most(mouth=0.55 * breath, blink=0.6 * breath)
    kit.add(dip=-2 * breath, ears=-6 * breath)

    def frost(p, x, y, fade, i):
        puff(p, x, y, 3 + 5 * (1 - fade), fade, QColor(170, 230, 255, 200))
    kit.world.append(lambda p: burst(p, t - 1.8, 54, 80, 9, 26, 1.0, frost, gravity=-6, salt=11,
                                     up=-0.1))
    shiver = held(t, 2.7, 3.4, 0.1)
    kit.add(dx=1.2 * math.sin(t * 55) * shiver)


def robot_dance(kit: Kit, t: float):
    """Synthwave: his visor scans and he does a stiff little robot dance."""
    step = math.floor(t / 0.4)
    on = held(t, 0.3, 3.5, 0.1)
    pose = ((0, 0), (6, 2), (-6, -2), (0, -3), (6, 2), (-6, 2), (0, 0), (6, -2), (0, 0))
    a, d = pose[step % len(pose)]
    kit.add(angle=a * on, dx=d * on, nod=-a * 0.8 * on, ears=(8 if step % 2 else -6) * on)
    sweep = (t * 1.2) % 1.0
    kit.front.append(lambda p: _scan(p, sweep, on))


def _scan(p: QPainter, k, alpha):
    if alpha <= 0:
        return
    x = 30 + 40 * k
    g = QColor(0, 230, 255, round(220 * alpha))
    p.setPen(QPen(g, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(x, 56), QPointF(x, 68))


def slow_mo(kit: Kit, t: float):
    """Vaporwave: everything goes slow and dreamy; he floats beside a turning cube."""
    on = held(t, 0.0, 4.2, 0.8)
    kit.add(dy=-8 * on, angle=6 * math.sin(t * 1.2) * on, ears=8 * math.sin(t * 1.5) * on)
    kit.most(blink=0.5 * on)
    kit.world.append(lambda p: _cube(p, 92, 40 + 4 * math.sin(t * 1.4), t * 0.8, on))


def _cube(p: QPainter, x, y, a, k):
    if k <= 0:
        return
    p.save()
    p.setOpacity(k)
    pts = []
    for cx, cy, cz in ((-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
                       (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)):
        rx = cx * math.cos(a) - cz * math.sin(a)
        rz = cx * math.sin(a) + cz * math.cos(a)
        ry = cy * math.cos(0.5) - rz * math.sin(0.5)
        pts.append(QPointF(x + rx * 7, y + ry * 7))
    p.setPen(QPen(QColor("#ff71ce"), 1.4))
    for i, j in ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4),
                 (0, 4), (1, 5), (2, 6), (3, 7)):
        p.drawLine(pts[i], pts[j])
    p.restore()


def hot_floor(kit: Kit, t: float):
    """Lava: the floor gets hot and he hops from foot to foot."""
    hot = held(t, 0.0, 3.6, 0.4)
    kit.behind.append(lambda p: _heat(p, hot, t))
    hop = held(t, 0.4, 3.1, 0.2)
    k = abs(math.sin(t * 8))
    kit.add(dy=-7 * k * hop, angle=8 * math.copysign(1, math.sin(t * 8)) * hop * 0.8,
            ears=-8 * hop)
    kit.most(mouth=0.45 * hop)
    if hop:
        kit.world.append(lambda p: _drop(p, 76, 52 + 10 * ((t * 1.3) % 1.0), hop, 0))


def _heat(p: QPainter, k, t):
    if k <= 0:
        return
    g = QRadialGradient(50, 118, 40)
    g.setColorAt(0, QColor(255, 120, 40, round(170 * k)))
    g.setColorAt(1, QColor(255, 60, 20, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawEllipse(QRectF(10, 106, 80, 24))
    p.setPen(QPen(QColor(255, 160, 80, round(150 * k)), 1.4))
    for i, x in enumerate((26, 50, 74)):
        w = QPainterPath(QPointF(x, 112))
        for j in range(3):
            w.quadTo(QPointF(x + (3 if j % 2 else -3) + math.sin(t * 6 + i), 108 - j * 6),
                     QPointF(x, 104 - j * 6))
        p.drawPath(w)


def scribble(kit: Kit, t: float):
    """Amber Terminal: the pencil from behind his ear, a few notes on a pad, back it goes."""
    kit.prop = ""
    out = eseg(t, 0.2, 0.8) * (1 - eseg(t, 3.0, 3.6))
    if out > 0:
        kit.hide.add("pencil")
    write = held(t, 0.9, 2.8, 0.1)
    x = lerp(80, 72, out) + 5 * math.sin(t * 18) * write
    y = lerp(37, 98, out) + 1.5 * math.sin(t * 31) * write
    pad = held(t, 0.6, 3.2, 0.2)
    if pad:
        kit.world.append(lambda p: _notepad(p, pad, seg(t, 0.9, 2.8)))
    if out > 0:
        kit.front.append(lambda p: piece(p, "pencil", x - 80, y - 37, 30 * out, (80, 37)))
        kit.front.append(lambda p: paw(p, x - 3, y + 3))
    kit.add(dip=4 * write, nod=2 * math.sin(t * 5) * write)
    kit.most(smug=held(t, 2.8, 3.4, 0.1))


def _notepad(p: QPainter, k, written):
    p.save()
    p.setOpacity(k)
    p.setPen(_ink(1.4))
    p.setBrush(QColor("#fff7d6"))
    p.drawRoundedRect(QRectF(60, 100, 26, 16), 2, 2)
    p.setPen(QPen(QColor("#2b2340"), 1.0))
    for i in range(3):
        w = max(0.0, min(1.0, written * 3 - i)) * 20
        if w > 0:
            p.drawLine(QPointF(63, 104 + i * 4), QPointF(63 + w, 104 + i * 4 + 0.5))
    p.restore()


def hacker(kit: Kit, t: float):
    """Hacker: a tiny laptop, furious typing, a stream of 0s and 1s, a green tick."""
    up = held(t, 0.2, 3.8, 0.3)
    typing = held(t, 0.6, 2.6, 0.1)
    kit.prop = ""
    kit.world.append(lambda p: _laptop(p, up, t, typing, seg(t, 2.6, 2.8)))
    if up:
        for i, x in enumerate((40, 60)):
            kit.front.append(lambda p, i=i, x=x: paw(
                p, x, 100 - 3 * abs(math.sin(t * 20 + i * 1.7)) * typing))
    kit.add(dip=3 * up, dx=0.5 * math.sin(t * 40) * typing)
    kit.most(smug=held(t, 2.8, 3.8, 0.1))


def _laptop(p: QPainter, k, t, typing, done):
    if k <= 0:
        return
    p.save()
    p.setOpacity(k)
    p.setPen(_ink(1.4))
    p.setBrush(QColor("#3a3f4b"))
    p.drawRoundedRect(QRectF(32, 102, 36, 6), 1.5, 1.5)
    screen = QColor("#0b1a0f")
    p.setBrush(screen)
    p.drawRoundedRect(QRectF(36, 86, 28, 17), 1.5, 1.5)
    green = QColor("#39ff6a")
    if done > 0:
        p.setPen(QPen(green, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(44, 95), QPointF(48, 99))
        p.drawLine(QPointF(48, 99), QPointF(57, 89))
    f = QFont()
    f.setPixelSize(6)
    f.setBold(True)
    p.setFont(f)
    for i in range(6):
        u = (t * 0.8 + _rand(i, 3)) % 1.0
        c = QColor(green)
        c.setAlphaF(typing * (1 - u))
        p.setPen(c)
        p.drawText(QPointF(30 + 40 * _rand(i, 6), 84 - u * 40), "1" if i % 2 else "0")
    p.restore()


def flashbang(kit: Kit, t: float):
    """Flashbang: FLASH. He reels, dizzy, stars spinning round his head."""
    kit.flash = (1 - seg(t, 0.4, 1.1)) if t >= 0.35 else 0.0
    dizzy = held(t, 0.5, 2.8, 0.3)
    kit.add(angle=10 * math.sin(t * 5) * dizzy, dx=3 * math.sin(t * 5) * dizzy,
            nod=-8 * math.sin(t * 5 + 1) * dizzy)
    kit.most(blink=0.5 * dizzy, mouth=0.3 * dizzy)
    if dizzy:
        kit.world.append(lambda p: _orbit(p, t, dizzy))


def _orbit(p: QPainter, t, k):
    for i in range(3):
        a = t * 5 + i * 2.1
        x, y = 50 + 30 * math.cos(a), 26 + 8 * math.sin(a)
        c = QColor("#ffcf40")
        c.setAlphaF(k)
        sparkle(p, x, y, 4.5, c)


def kiss(kit: Kit, t: float):
    """Barbie: she blows a kiss; a heart floats off and pops into sparkles."""
    kit.prop = ""
    hand = held(t, 0.2, 1.3, 0.2)
    out = eseg(t, 0.9, 1.3)
    if hand:
        kit.front.append(lambda p: paw(p, lerp(56, 84, out), lerp(80, 70, out)))
    kit.most(mouth=0.12 * held(t, 0.3, 0.9, 0.1))
    u = seg(t, 1.1, 2.5)
    if 0 < u < 1:
        kit.world.append(lambda p: heart(p, 84 + 12 * u, 66 - 40 * u + 3 * math.sin(u * 12),
                                         4 + 5 * u, QColor("#ff4fa3")))
    kit.world.append(lambda p: _sparkles(p, t - 2.5, 96, 26, salt=12,
                                         cols=("#ff4fa3", "#ffd1e8", "#ffcf40")))
    giggle = held(t, 2.4, 3.3, 0.1)
    kit.most(blink=giggle, mouth=0.3 * giggle)
    kit.add(dy=-3 * abs(math.sin(t * 14)) * giggle)


def party(kit: Kit, t: float):
    """Comic Sans: a toot on a party blower, then confetti everywhere."""
    blow = held(t, 0.4, 1.6, 0.2)
    if blow:
        kit.front.append(lambda p: _blower(p, blow))
        kit.add(dip=-2 * blow)
    kit.world.append(lambda p: burst(p, t - 1.0, 50, 30, 22, 46, 2.2, _confetti, gravity=30,
                                     salt=13, up=0.8))
    kit.most(blink=held(t, 1.6, 2.6, 0.1))
    kit.add(dy=-6 * bump(t, 1.0, 1.4))


def _blower(p: QPainter, k):
    col = QColor(theme.T["accent"])
    p.setPen(QPen(col, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    length = 6 + 26 * k
    path = QPainterPath(QPointF(52, 78))
    path.lineTo(52 + length, 78 - length * 0.2)
    if k < 0.95:   # the curl at its end, unrolling
        path.arcTo(QRectF(52 + length - 4, 78 - length * 0.2 - 8, 8, 8), -90, 300 * (1 - k))
    p.drawPath(path)
    _oval(p, 52, 78, 4, 4, QColor("#ffcf40"), _ink(1.0))


def _confetti(p, x, y, fade, i):
    cols = ("#ff4d6d", "#ffcf40", "#1fb6ff", "#13ce66", "#a48bff")
    c = QColor(cols[i % len(cols)])
    c.setAlphaF(fade)
    p.save()
    p.translate(x, y)
    p.rotate(i * 37 + (1 - fade) * 400)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawRect(QRectF(-1.6, -1, 3.2, 2))
    p.restore()


def bow(kit: Kit, t: float):
    """Light: he straightens his bow tie, then takes a bow."""
    fix = held(t, 0.3, 1.3, 0.15)
    kit.prop = ""
    if fix:
        kit.hide.add("bowtie")
        kit.front.append(lambda p: piece(p, "bowtie", 0, 0, 12 * math.sin(t * 14) * fix, (50, 93)))
        kit.front.append(lambda p: paw(p, 60, 92))
    down = held(t, 1.6, 2.6, 0.3)
    kit.add(dip=12 * down, nod=-3 * down, sy=-0.05 * down, dy=2 * down)
    kit.most(blink=down)
    kit.world.append(lambda p: _sparkles(p, t - 2.6, 50, 30, n=6, salt=14))


def sniff_flower(kit: Kit, t: float):
    """Lilac: he sniffs a flower, sighs happily, then sneezes out petals."""
    kit.prop = ""
    up = held(t, 0.2, 2.3, 0.3)
    if up:
        kit.front.append(lambda p: _flower_in_paw(p, lerp(80, 60, up), lerp(100, 80, up)))
    kit.most(blink=held(t, 0.8, 1.8, 0.2))
    _sneeze(kit, t, 2.3)

    def petal(p, x, y, fade, i):
        c = QColor("#c9a7ff" if i % 2 else "#e6d6ff")
        c.setAlphaF(fade)
        _oval(p, x, y, 4, 2.6, c, None, i * 50)
    kit.world.append(lambda p: burst(p, t - 2.3, 58, 78, 10, 40, 1.2, petal, gravity=20,
                                     salt=15))


def _flower_in_paw(p: QPainter, x, y):
    p.setPen(QPen(QColor("#4caf50"), 1.6))
    p.drawLine(QPointF(x, y), QPointF(x - 4, y - 12))
    bunnyfit._flower(p, x - 4, y - 14, 5, QColor("#c9a7ff"), QColor("#ffe27a"))
    paw(p, x + 1, y + 2)


def petal_catch(kit: Kit, t: float):
    """Cherry Blossom: petals drift down; he catches one and blows it off his paw."""
    kit.world.append(lambda p: _petals(p, t, held(t, 0, 3.8, 0.4)))
    kit.prop = ""
    up = held(t, 1.0, 2.9, 0.2)
    if up:
        kit.front.append(lambda p: paw(p, 74, lerp(100, 82, up)))
    if t < 2.5:
        k = eseg(t, 0.2, 1.5)
        x, y = lerp(90, 74, k), lerp(-4, 77, k)
    else:
        u = seg(t, 2.5, 3.6)
        x, y = 74 + 40 * u, 77 - 50 * u + 10 * math.sin(u * 9)
    if t < 3.6:
        kit.world.append(lambda p: _oval(p, x, y, 5, 3.4, QColor("#ffc1d3"), None, t * 90))
    kit.most(mouth=0.15 * held(t, 2.35, 2.8, 0.1))
    kit.add(nod=5 * held(t, 1.4, 2.8))


def _petals(p: QPainter, t, k):
    if k <= 0:
        return
    for i in range(8):
        fall = (t * 0.22 + _rand(i, 16)) % 1.0
        x = -6 + 112 * _rand(i, 17) + 6 * math.sin(t * 1.5 + i)
        c = QColor("#ffc1d3")
        c.setAlphaF(0.85 * k)
        _oval(p, x, -6 + fall * 128, 4.5, 3, c, None, t * 70 + i * 30)


def spin(kit: Kit, t: float):
    """Carbon: a quick spin on the spot, and a cool pose to finish."""
    turn = eseg(t, 0.4, 1.6)
    kit.add(sx=(math.cos(turn * 4 * math.pi) - 1), dy=-5 * bump(t, 0.4, 1.6))
    posed = held(t, 1.7, 3.0, 0.15)
    kit.add(angle=-6 * posed, nod=-4 * posed, dx=-2 * posed)
    kit.most(smug=posed)
    kit.world.append(lambda p: _sparkles(p, t - 1.6, 50, 60, n=6, salt=18))


def reading(kit: Kit, t: float):
    """Slate: he reads a little book, turns the pages, pushes his readers up."""
    up = held(t, 0.2, 3.8, 0.3)
    kit.prop = ""
    if up:
        kit.front.append(lambda p: _book(p, up, t))
    kit.add(dip=4 * up, nod=2 * math.sin(t * 1.3) * up)
    push = bump(t, 2.9, 3.4)
    if push:
        kit.hide.add("readers")
        kit.front.append(lambda p: piece(p, "readers", 0, -3 * push))
        kit.front.append(lambda p: paw(p, 50, 72 - 2 * push))


def _book(p: QPainter, k, t):
    p.save()
    p.setOpacity(k)
    p.setPen(_ink(1.4))
    p.setBrush(QColor("#8a3b2e"))
    p.drawRoundedRect(QRectF(33, 88, 34, 22), 2, 2)
    p.setBrush(QColor("#fbf3e4"))
    p.drawRect(QRectF(35, 89.5, 15, 19))
    p.drawRect(QRectF(50, 89.5, 15, 19))
    for at in (1.2, 2.3):   # a page turning
        u = seg(t, at, at + 0.4)
        if 0 < u < 1:
            w = 15 * math.cos(u * math.pi)
            p.drawRect(QRectF(50, 89.5, w, 19).normalized())
    p.restore()
    paw(p, 33, 100)
    paw(p, 67, 100)


def paper_plane(kit: Kit, t: float):
    """Paper: he throws a paper plane; it loops round and lands on his head."""
    kit.prop = ""
    throw = held(t, 0.2, 0.9, 0.2)
    if throw:
        kit.front.append(lambda p: paw(p, 78, lerp(98, 80, throw)))
    if 0.2 < t < 0.8:
        kit.front.append(lambda p: _plane(p, 80, lerp(96, 78, throw), -20))
    elif 0.8 <= t < 3.0:
        u = seg(t, 0.8, 3.0)
        a = u * 2 * math.pi
        x, y = 50 + 40 * math.sin(a) * (1 - 0.6 * u), 50 - 30 * math.sin(a * 0.5) - 10 * u
        heading = math.degrees(math.atan2(-30 * math.cos(a * 0.5) * 0.5,
                                          40 * math.cos(a) * (1 - 0.6 * u))) if u < 1 else 0
        kit.world.append(lambda p: _plane(p, x, y, heading))
    elif t < 4.2:
        kit.front.append(lambda p: _plane(p, 52, 34, 15, 1 - seg(t, 3.8, 4.2)))
    land = bump(t, 3.0, 3.25)
    kit.add(sy=-0.05 * land, nod=-4 * held(t, 1.2, 2.8))
    kit.world.append(lambda p: mark(p, 80, 20, "?", held(t, 3.1, 4.0, 0.15)))
    kit.most(blink=bump(t, 3.3, 3.5))


def _plane(p: QPainter, x, y, angle, alpha=1.0):
    p.save()
    p.setOpacity(alpha)
    p.translate(x, y)
    p.rotate(angle)
    path = QPainterPath(QPointF(10, 0))
    path.lineTo(-8, -6)
    path.lineTo(-4, 0)
    path.lineTo(-8, 5)
    path.closeSubpath()
    p.setPen(_ink(1.2))
    p.setBrush(QColor("#ffffff"))
    p.drawPath(path)
    p.drawLine(QPointF(10, 0), QPointF(-4, 0))
    p.restore()


def juggle(kit: Kit, t: float):
    """Any theme without an outfit: he juggles three balls; the last one bonks his head."""
    kit.prop = ""
    on = held(t, 0.2, 3.3, 0.2)
    cols = (QColor(theme.T["accent"]), QColor("#ffcf40"), QColor("#ff8fae"))
    period = 0.9
    for i in range(3):
        u = ((t - 0.2) / period + i / 3) % 1.0
        side = 1 if u < 0.5 else -1
        k = (u % 0.5) / 0.5
        x = 50 + side * lerp(24, -24, k)
        y = 96 - 60 * math.sin(math.pi * k)
        if t > 3.0 and i == 0:   # the bonk: straight down onto his head
            v = seg(t, 3.0, 3.25)
            x, y = 50, lerp(10, 34, v * v) if t < 3.25 else 34 - 30 * seg(t, 3.25, 3.8) + \
                60 * seg(t, 3.25, 3.8) ** 2
        alpha = on if not (t > 3.0 and i == 0) else 1 - seg(t, 3.7, 3.9)
        kit.world.append(lambda p, x=x, y=y, c=cols[i], a=alpha: _ball(p, x, y, c, a))
    if on:
        kit.front.append(lambda p: paw(p, 26, 96 - 4 * abs(math.sin(t * 7))))
        kit.front.append(lambda p: paw(p, 74, 96 - 4 * abs(math.cos(t * 7))))
    kit.add(nod=3 * math.sin(t * 7) * on, dip=-2 * on)
    bonk = bump(t, 3.22, 3.5)
    kit.add(dip=5 * bonk, sy=-0.06 * bonk)
    _surprised(kit, t, 3.25, 3.9)


def _ball(p: QPainter, x, y, col, alpha):
    if alpha <= 0:
        return
    p.save()
    p.setOpacity(alpha)
    _oval(p, x, y, 9, 9, col, _ink(1.4))
    _oval(p, x - 1.8, y - 1.8, 3, 2.4, QColor(255, 255, 255, 170))
    p.restore()


def dj(kit: Kit, t: float):
    """Dark (the default theme, plain Bun in his headphones): a little turntable, a few
    scratches with notes flying off it, then both paws up for the drop."""
    kit.prop = ""
    deck = held(t, 0.2, 3.6, 0.3)
    scratch = held(t, 0.7, 2.6, 0.1)
    wiggle = math.sin(t * 16) * scratch   # the record, back and forth under his paw
    if deck:
        kit.world.append(lambda p: _deck(p, deck, t, wiggle))
        kit.front.append(lambda p: paw(p, 58 + 7 * wiggle, lerp(100, 97, deck)))
        kit.front.append(lambda p: paw(p, 30, lerp(100, 96, deck)))
    kit.add(nod=4 * wiggle, dip=2 * abs(wiggle), ears=-6 * scratch)
    for at in (0.9, 1.3, 1.7, 2.1, 2.5):   # a note off each scratch
        kit.world.append(lambda p, at=at: burst(p, t - at, 60, 92, 1, 30, 0.8, _dj_note,
                                                gravity=-10, salt=int(at * 10), up=1.2))
    drop = held(t, 2.75, 3.7, 0.15)
    if drop:   # paws up, eyes shut, a hop
        kit.front.append(lambda p: paw(p, 20, lerp(96, 70, drop), -30))
        kit.front.append(lambda p: paw(p, 80, lerp(96, 70, drop), 30))
        kit.most(blink=drop)
        kit.add(dy=-7 * bump(t, 2.75, 3.15), ears=-12 * drop)
    kit.world.append(lambda p: _sparkles(p, t - 2.8, 50, 40, n=9, salt=19))


def _deck(p: QPainter, k, t, wiggle):
    p.save()
    p.setOpacity(k)
    p.setPen(_ink(1.6))
    p.setBrush(QColor("#3a3452"))
    p.drawRoundedRect(QRectF(24, 98, 52, 16), 3, 3)
    _oval(p, 58, 104, 22, 9, QColor("#15131f"), _ink(1.2))   # the record (seen from the front)
    _oval(p, 58, 104, 7, 3, QColor(theme.T["accent"]))
    p.setPen(QPen(QColor(255, 255, 255, 90), 1.0))
    a = t * 4 + wiggle * 2   # its grooves catching the light, turning
    p.drawLine(QPointF(58 + 8 * math.cos(a), 104 + 3 * math.sin(a)),
               QPointF(58 + 10 * math.cos(a), 104 + 3.8 * math.sin(a)))
    _oval(p, 32, 104, 5, 5, QColor("#ffcf40"), _ink(1.0))      # a knob
    p.restore()


def _dj_note(p, x, y, fade, i):
    c = QColor(theme.T["accent"])
    c.setAlphaF(fade)
    music_note(p, x - 4, y - 8, 0.8, c)


# theme -> (seconds, skit); a theme that isn't listed juggles
SKITS: dict[str, tuple[float, Callable[[Kit, float], None]]] = {
    "Blood Moon": (5.2, blood_moon),
    "Retro 98": (3.8, deal_with_it),
    "Brainrot": (3.6, propeller),
    "Swamp": (3.4, frog_fly),
    "Deep Fried": (3.3, laser),
    "Vampire": (4.4, bat),
    "Midnight": (3.7, wizard),
    "Ocean": (3.6, spyglass),
    "Arctic": (3.6, achoo),
    "Royal": (3.7, crown),
    "Onion": (3.6, onion),
    "Toxic": (3.4, geiger),
    "Forest": (3.6, leaf),
    "Mocha": (3.6, coffee),
    "Sunset": (3.9, coconut),
    "Mint": (3.5, mint),
    "Synthwave": (3.8, robot_dance),
    "Vaporwave": (4.2, slow_mo),
    "Lava": (3.6, hot_floor),
    "Amber Terminal": (3.8, scribble),
    "Hacker": (4.0, hacker),
    "Flashbang": (3.0, flashbang),
    "Barbie": (3.4, kiss),
    "Comic Sans": (3.4, party),
    "Light": (3.0, bow),
    "Lilac": (3.6, sniff_flower),
    "Cherry Blossom": (3.8, petal_catch),
    "Carbon": (3.1, spin),
    "Slate": (4.0, reading),
    "Paper": (4.3, paper_plane),
    "Dark": (3.9, dj),
}
GENERIC = (4.0, juggle)


def for_theme(name: str | None = None) -> tuple[float, Callable[[Kit, float], None]]:
    """The skit for theme `name` (default: the current one)."""
    return SKITS.get(name or theme.current_name, GENERIC)
