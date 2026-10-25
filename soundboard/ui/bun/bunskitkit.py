"""What Bun's skits (ui/bun/bunskits.py) are made of: the `Kit` a skit fills in for a frame, the
timing curves (`seg`, `ease`, `bump`, `held`) and the small drawings they share (paws, marks,
puffs, bursts, sparkles, outfit pieces, hearts). `bunskits` re-exports them."""
from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPicture

from soundboard.style import bunnyfit
from soundboard.ui.bun.bunny import INK, look_colour, sparkle
from soundboard.ui.kit import theme


Draw = Callable[[QPainter], None]
PEN = 2.4                   # his outline's width on the canvas


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


_found: list[tuple[float, float]] | None = None   # (held_paws collecting, not drawing)


def paw(p: QPainter, x: float, y: float, angle: float = 0.0):
    """One of his paws (they're only drawn when they hold something), in his theme's fur.
    His arm out to it is draw_bunny's (`hold`, from held_paws)."""
    if _found is not None:
        q = p.transform().map(QPointF(x, y))
        _found.append((q.x(), q.y()))
        return
    _oval(p, x, y, 12, 10.5, look_colour("fur"), _ink(), angle)


def held_paws(kit: Kit) -> tuple | None:
    """Where this frame's drawings put his paws, on his canvas, as draw_bunny's `hold`
    (left, right): those arms leave his sides and reach out to them. None: no paw out.
    (`world` paws count too: the DJ's, over his desk, with no dx / dy.)"""
    global _found
    _found = []
    pic = QPicture()
    p = QPainter(pic)
    try:
        for fn in kit.front + kit.world:
            fn(p)
    finally:
        p.end()
        found, _found = _found, None
    if not found:
        return None
    found = sorted(found[:2])
    if len(found) == 1:   # the arm on its side of him
        return (found[0], None) if found[0][0] < 50 else (None, found[0])
    return found[0], found[1]


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
