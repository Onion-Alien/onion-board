"""Bun, the mascot: a cartoon bunny in gaming headphones, drawn with QPainter so it's
crisp at any size and needs no image files. Used by the quick-setup guide (a
different prop on each page) and by scripts/pictures/make_bunny.py for the installer's artwork.

    bunny_image(160, prop="mic")   # QImage, transparent background
"""
from __future__ import annotations

import functools
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QImage, QPainter, QPainterPath, QPainterPathStroker,
                           QPen, QPixmap, QRadialGradient, QTransform)

from soundboard import theme
from soundboard.style import bunnyfit

# drawn on a 100 x 120 canvas, scaled to the requested height
W, H = 100.0, 120.0

FUR = QColor("#fdf8f1")
FUR_SHADE = QColor("#efe3d6")
FUR_LINE = QColor(200, 176, 160, 150)   # soft fluff lines (the nightcap bobble)
INK = QColor("#2b2340")
EYE = QColor("#251c33")
IRIS = QColor(bunnyfit.VANILLA["iris"])   # the coloured glow low in his eyes (plain Bun's:
                                          # each theme's look can change it, and the pinks)
FACE_LIGHT = QColor("#f4ecf6")          # his face lines and eye rims on dark fur
BROW = QColor(196, 140, 140, 150)       # his little resting brows
PINK = QColor(bunnyfit.VANILLA["inner"])
NOSE = QColor(bunnyfit.VANILLA["nose"])   # (his tongue stays this pink whatever his nose)
NOSE_EDGE = QColor("#e0708f")
MOUTH = QColor("#7a2a45")
CHEEK = QColor(255, 122, 150, 165)
# his headphones are the current theme's accent (theme.T, read at paint time)

PROPS = (None, "mic", "headphones", "plug", "star", "hammer", "bat", "wrench",
         "hammer_broken", "survey")
# the props that take a paw (the one on the right, both): those paws leave his lap
ONE_PAW = {"mic", "headphones", "plug", "bat", "hammer", "hammer_broken", "wrench"}
BOTH_PAWS = {"star", "survey"}
WOOD = QColor("#c98a4b")
WOOD_DARK = QColor("#9a6532")
STEEL = QColor("#9aa0b4")
BAT = QColor("#e3b877")
GRIP = QColor("#3a3452")
CROSS = QColor("#ff4d6d")   # the cartoon anger mark

ROBOT_FUR = QColor("#dbe0ea")
ROBOT_FUR_SHADE = QColor("#bec7d8")
ROBOT_INK = QColor("#242735")
ROBOT_CYAN = QColor("#00d4ff")
ROBOT_CYAN_HI = QColor("#b0f4ff")
ROBOT_CYAN_GLOW = QColor(0, 212, 255, 130)
ROBOT_BOLT = QColor("#8e98ad")
GADGET = QColor("#b9c2d4")
# where things get built, on the 100 x 120 canvas (ui/bunnywidget.py draws the progress):
# the wrench prop's gadget screen, and the spot on the hammer's plank
GADGET_SCREEN = QRectF(70, 109, 24, 6.5)
PLANK_SPOT = QRectF(84, 91, 17, 18)
# outfit pieces on his body, not his head: they stay put when he nods (draw_bunny `nod`)
BODY_PIECES = bunnyfit.NECK | {"sweater", "collar"}
EYES = bunnyfit.EYES
EYE_Y = bunnyfit.EYE_Y

# The shapes that are the same from frame to frame (his ears at a fold, his tail, his
# markings, his arms in a pose) are built once and reused: building them (QPainterPath
# unions) was a good part of each frame. They're only ever drawn or combined into new
# paths, never changed. False: every frame builds them fresh (the tests compare).
CACHE = True


def _kept(fn):
    """fn, its results kept by its (hashable) arguments while CACHE is on."""
    kept = functools.lru_cache(maxsize=512)(fn)

    @functools.wraps(fn)
    def get(*args):
        return kept(*args) if CACHE else fn(*args)
    # (a plain attribute on the function: pyright only knows functools.wraps's type)
    get.cache_clear = kept.cache_clear  # pyright: ignore[reportAttributeAccessIssue]
    return get


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


EAR_HINGE = 4.5    # where an ear folds when he's sad: about its middle (ear frame)
REST_FOLD = 122.0  # a floppy ear (the look's "ears": some themes flop one) folds over and down...
REST_HINGE = 12.0  # ... bending a little below its middle, so a good bit stands up first
DROOP = (11.0, 6.5)  # an upright ear's top curves out and down this far (ear frame)


@_kept
def _ear_shape(w: float, h: float) -> QPainterPath:
    """An ear in its own frame, centred and upright: narrow where it meets the head,
    fullest above the middle, a round tip."""
    path = QPainterPath(QPointF(0, h / 2))
    path.cubicTo(QPointF(w * 0.34, h / 2), QPointF(w / 2, h * 0.2), QPointF(w / 2, -h * 0.04))
    path.cubicTo(QPointF(w / 2, -h * 0.32), QPointF(w * 0.3, -h / 2), QPointF(0, -h / 2))
    path.cubicTo(QPointF(-w * 0.3, -h / 2), QPointF(-w / 2, -h * 0.32), QPointF(-w / 2, -h * 0.04))
    path.cubicTo(QPointF(-w / 2, h * 0.2), QPointF(-w * 0.34, h / 2), QPointF(0, h / 2))
    path.closeSubpath()
    return path


def _droop(side: int, h: float):
    """A soft curve for an upright ear (its own frame): the top half bends out to its
    side and down a little, more towards the tip, so it reads soft and floppy."""
    dx, dy = DROOP

    def bend(path: QPainterPath) -> QPainterPath:
        out = QPainterPath(path)
        for i in range(out.elementCount()):
            e = out.elementAt(i)
            t = max(0.0, min(1.0, -e.y / (h / 2)))
            out.setElementPositionAt(i, e.x + side * dx * t * t, e.y + dy * t * t)
        return out
    return bend


def _ear_bend(fold: float, hinge: float = EAR_HINGE) -> QTransform:
    """The ear frame above `hinge` folded `fold` degrees about it (+ = to his left,
    the viewer's right)."""
    return QTransform().translate(0, hinge).rotate(fold).translate(0, -hinge)


def _ear_pieces(w: float, h: float, bend: QTransform | None, hinge: float = EAR_HINGE,
                bite: QPainterPath | None = None):
    """An ear in two pieces, its own frame: the part that stays up (ending in a round
    knee where it bends) and the flap folded over by `bend` (painted on top: it hides
    the inner ear behind it). Straight (`bend` None): the whole ear and no flap. `bite`:
    a chomp taken out of it."""
    full = _ear_shape(w, h)
    if bite is not None:
        full = full.subtracted(bite)
    if bend is None:
        return full, None
    below, above = QPainterPath(), QPainterPath()
    below.addRect(QRectF(-w, hinge, 2 * w, h))
    above.addRect(QRectF(-w, -h, 2 * w, h + hinge))
    kw = w * 0.92   # (the ear's width there)
    knee = QPainterPath()
    knee.addEllipse(QRectF(-kw / 2, hinge - kw / 2, kw, kw))
    return full.intersected(below), bend.map(full.intersected(above)).united(knee)


@_kept
def _ear(side: int, w: float, h: float, fold: float | None, hinge: float, chomp: bool,
         droop: bool):
    """An ear's two pieces as draw_bunny draws them (_ear_pieces): folded `fold` degrees
    about `hinge` (None: straight), with a bite out of its outer edge (`chomp`) and its
    standing part curved over (`droop`, _droop)."""
    bite = None
    if chomp:
        bite = _oval(side * w * 0.5, -h * 0.17, 9, 8.5).united(
            _oval(side * w * 0.55, -h * 0.02, 6.5, 6.5))
    lower, flap = _ear_pieces(w, h, None if fold is None else _ear_bend(fold, hinge), hinge,
                              bite)
    if droop:
        lower = _droop(side, h)(lower)
    return lower, flap


@_kept
def _inner_ear(iw: float, ih: float, dx: float, dy: float, droop_side: int, h: float):
    """The inner ear (its own frame), curved over with the ear (droop_side, else 0)."""
    shape = QTransform().translate(dx, dy).map(_ear_shape(iw, ih))
    return shape if not droop_side else _droop(droop_side, h)(shape)


@_kept
def _flap_inner(inner: tuple, fold: float, hinge: float) -> QPainterPath:
    """The half of the inner ear (_inner_ear(*inner)) that folds over with the flap."""
    top = QPainterPath()
    top.addRect(QRectF(-30, -60, 60, 60 + hinge))
    return _ear_bend(fold, hinge).map(_inner_ear(*inner).intersected(top))


@_kept
def _floppy_pink(ear: tuple, inner: tuple, w: float, hinge: float):
    """A floppy ear's clip (both pieces, _ear(*ear)) and the pink inside it, up to the
    bend (_inner_ear(*inner))."""
    lower, flap = _ear(*ear)
    assert flap is not None   # (a floppy ear is always folded)
    top = QPainterPath()
    top.addRect(QRectF(-30, hinge, 60, 60))
    top.addEllipse(QRectF(-w * 0.25, hinge - w * 0.25, w * 0.5, w * 0.5))
    return lower.united(flap), _inner_ear(*inner).intersected(top.simplified())


def _stroke(p: QPainter, path: QPainterPath, col: QColor, width: float):
    p.setPen(QPen(col, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)


def _arc(x0, y0, cx, cy, x1, y1) -> QPainterPath:
    path = QPainterPath(QPointF(x0, y0))
    path.quadTo(QPointF(cx, cy), QPointF(x1, y1))
    return path


# His arms: short stubby bunny arms from his shoulders at the sides of his body (tucked
# under his head), each along a gentle curve to a round paw: (bend, paw), the viewer's
# left one first. Resting, they hang at his sides; hoping, the paws come up in front of
# his chest; cross, they fold across it (the viewer's right one on top).
SHOULDERS = ((35.5, 92.5), (64.5, 92.5))
ARMS_REST = (((31.3, 96.7), (32.7, 101.6)), ((68.7, 96.7), (67.3, 101.6)))
ARMS_HOPE = (((32.4, 100.5), (43.1, 96.0)), ((67.7, 100.5), (56.9, 96.0)))
ARMS_CROSS = (((29.6, 102.6), (51.6, 100.2)), ((70.5, 102.6), (48.4, 101.4)))
ARM_R = 4.6   # (the paw, PAW_R, a little rounder)
# where a prop puts each paw (None: that paw stays on his tummy). "headphones" is in the
# head's frame: the paw is on the ear cup
PROP_PAWS = {"mic": (None, (76, 97)), "headphones": (None, (86, 72)),
             "plug": (None, (78, 100)), "star": ((20, 92), (80, 92)),
             "hammer": (None, (80, 92)), "hammer_broken": (None, (80, 92)),
             "bat": (None, (80, 92)), "wrench": (None, (80, 92)),
             "survey": ((33, 105), (67, 105))}
PAW_R = 5.5   # the paw: rounder than the arm


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


@_kept
def _limb(a, c, b, r0: float, r1: float, n: int = 16) -> QPainterPath:
    """A tapered limb along the curve a -> b (bent towards c): r0 thick at a, r1 at b,
    round at both ends."""
    left, right = [], []
    for i in range(n + 1):
        t = i / n
        x = (1 - t) ** 2 * a[0] + 2 * (1 - t) * t * c[0] + t * t * b[0]
        y = (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * c[1] + t * t * b[1]
        dx = 2 * (1 - t) * (c[0] - a[0]) + 2 * t * (b[0] - c[0])
        dy = 2 * (1 - t) * (c[1] - a[1]) + 2 * t * (b[1] - c[1])
        d = math.hypot(dx, dy) or 1.0
        r = r0 + (r1 * 0.88 - r0) * t   # (narrowest at the wrist, the paw bulges past it)
        left.append(QPointF(x - dy / d * r, y + dx / d * r))
        right.append(QPointF(x + dy / d * r, y - dx / d * r))
    path = QPainterPath(left[0])
    for q in left[1:] + right[::-1]:
        path.lineTo(q)
    path.closeSubpath()
    path = path.united(_oval(a[0], a[1], 2 * r0, 2 * r0))
    return path.united(_oval(b[0], b[1], 2 * r1, 2 * r1)).simplified()


def _arm(p: QPainter, arm, fur: QColor, ink: QPen):
    """An arm reaching out to a prop: (shoulder, bend, paw, thickness). It's drawn
    behind his body and head, so only the part out past them shows; the prop draws the
    paw that holds it."""
    a, c, b, r0 = arm
    p.setPen(ink)
    p.setBrush(fur)
    p.drawPath(_limb(a, c, b, r0, PAW_R))


def _prop_bend(i: int, paw):
    """The elbow of arm `i` reaching from its shoulder to a prop at `paw`: out to his
    side and sagging a little. The higher the paw (up by his face), the further out it
    swings, so the arm shows beside his head instead of hiding under it."""
    (sx, sy), out = SHOULDERS[i], 1 if i == 1 else -1
    low = ((sx + paw[0]) / 2 + 3.5 * out, (sy + paw[1]) / 2 + 3.0)
    return _lerp(low, (sx + 16 * out, sy + 4), max(0.0, min(1.0, (sy - paw[1]) / 20)))


def _reach(p: QPainter, prop, fur: QColor, ink: QPen, head_xf: QTransform):
    """The arm up to his ear cup ("headphones"), from behind his body and head. Other
    props' arms come from his shoulders in front of his body, like his free ones
    (_paws)."""
    if prop != "headphones":
        return
    q = head_xf.map(QPointF(*PROP_PAWS["headphones"][1]))   # (it moves with his head)
    _arm(p, ((62, 95), (85, 95), (q.x(), q.y()), 5.4), fur, ink)   # up past his cheek


def _wave_paw(wave: float):
    """Where his waving paw is (x, y, lean), up beside his cheek, as `wave` -1..1 swings
    it from side to side."""
    return 87.5 + 2.6 * wave, 84.5 - 1.0 * abs(wave), 22 * wave


def _paws(p: QPainter, prop, sad: float, angry: float, paw_fur: QColor, ink: QPen,
          sleeve: QColor | None = None, waving: bool = False, hold: tuple | None = None):
    """His arms, from the sides of his body to his paws: they bring the paws together
    under his chin as `sad` grows (hoping) and go on his hips, elbows out, when he's
    cross (`angry`). An arm a prop takes goes from his shoulder out to it, its paw left
    to the prop (the one on his ear cup is _reach's)."""
    clasp = cross = 0.0
    if prop is None:
        cross = _smooth((angry - 0.35) / 0.4)
        clasp = _smooth((sad - 0.3) / 0.45) * (1 - cross)
    reach = PROP_PAWS.get(prop or "", (None, None))
    if hold is not None and prop is None:   # (a skit's paws, holding its things)
        reach = hold
    fur = sleeve or paw_fur
    for i in (0, 1):
        if prop == "headphones" and reach[i] is not None or (waving and i == 1):
            continue
        if reach[i] is not None:   # out to the prop, which draws the paw holding it
            p.setPen(ink)
            p.setBrush(fur)
            p.drawPath(_arm_out(i, tuple(reach[i])))
            continue
        (bx, by), (px, py) = (_lerp(_lerp(ARMS_REST[i][k], ARMS_HOPE[i][k], clasp),
                                    ARMS_CROSS[i][k], cross) for k in (0, 1))
        arm = _arm_free(i, bx, by, px, py)
        p.setPen(ink)
        p.setBrush(fur)
        p.drawPath(arm)
        if sleeve is not None:   # a sweater's sleeve: his paw out of the cuff
            _ellipse(p, px, py, 2 * PAW_R, 2 * PAW_R, paw_fur, ink)


def _arm_stroker() -> QPainterPathStroker:
    st = QPainterPathStroker()
    st.setWidth(2 * ARM_R)
    st.setCapStyle(Qt.PenCapStyle.RoundCap)
    st.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return st


@_kept
def _arm_out(i: int, paw: tuple) -> QPainterPath:
    """Arm `i` from his shoulder out to a prop's paw (the prop draws the paw)."""
    line = QPainterPath(QPointF(*SHOULDERS[i]))
    line.quadTo(QPointF(*_prop_bend(i, paw)), QPointF(*paw))
    return _arm_stroker().createStroke(line).simplified()


@_kept
def _arm_free(i: int, bx: float, by: float, px: float, py: float) -> QPainterPath:
    """Arm `i` from his shoulder, bent at bx, by, to its round paw at px, py."""
    line = QPainterPath(QPointF(*SHOULDERS[i]))
    line.quadTo(QPointF(bx, by), QPointF(px, py))
    return _arm_stroker().createStroke(line).united(
        _oval(px, py, 2 * PAW_R, 2 * PAW_R)).simplified()


@_kept
def _tail_shape(style: str) -> QPainterPath:
    """His tail, peeking out behind his left haunch (bunnyfit.TAILS): a round puff, a
    big fluffy one with soft tufts, a long one swept out, a pointy tuft or a heart."""
    if style == "fluffy":
        tail = _oval(21, 108.5, 15, 14)
        for i in range(8):
            a = math.radians(i * 45 + 10)
            tail = tail.united(_oval(21 + 7.2 * math.cos(a), 108.5 + 6.8 * math.sin(a), 6, 6))
        return tail.simplified()
    if style == "long":
        return _limb((29, 111), (20, 112), (11.5, 103), 5.6, 4.6)
    if style == "tuft":   # a teardrop, its point flicked up and out
        path = QPainterPath(QPointF(10, 98.5))
        path.cubicTo(QPointF(13, 103), QPointF(30, 102), QPointF(28, 111))
        path.cubicTo(QPointF(26.5, 118), QPointF(15, 118), QPointF(14.5, 110))
        path.cubicTo(QPointF(14, 105), QPointF(12.5, 102), QPointF(10, 98.5))
        path.closeSubpath()
        return path
    if style == "heart":
        path = QPainterPath(QPointF(0, 6.5))
        path.cubicTo(QPointF(-4, 3), QPointF(-8, 0), QPointF(-8, -3))
        path.cubicTo(QPointF(-8, -7.5), QPointF(-2, -8.5), QPointF(0, -4))
        path.cubicTo(QPointF(2, -8.5), QPointF(8, -7.5), QPointF(8, -3))
        path.cubicTo(QPointF(8, 0), QPointF(4, 3), QPointF(0, 6.5))
        path.closeSubpath()
        return QTransform().translate(19, 107.5).rotate(-24).map(path)
    return _oval(24, 111, 12.5, 11.5)


@_kept
def _marks(pattern, part: str) -> QPainterPath:
    """His fur markings (bunnyfit.PATTERNS) on `part` ("head" or "body"), before
    they're clipped to it: a patch over his left eye (the viewer's right), round spots,
    a mask round both eyes with a stripe of fur left down the middle."""
    marks = QPainterPath()
    for name in pattern:
        if part == "head" and name == "patch":
            marks = marks.united(_oval(66.5, 61, 25, 23)).united(_oval(73, 51, 17, 15))
        elif part == "head" and name == "spots":
            for x, y, w in ((60, 44.5, 8), (39.5, 44, 5.5), (16.5, 72, 8), (82, 76, 6.5)):
                marks = marks.united(_oval(x, y, w, w * 0.9))
        elif part == "body" and name == "spots":
            for x, y, w in ((71, 106, 7), (30, 111, 5.5), (59, 89.5, 5)):
                marks = marks.united(_oval(x, y, w, w * 0.9))
        elif part == "head" and name == "mask":
            for sx in (-1, 1):
                marks = marks.united(_oval(50 + sx * 19, 61.5, 29, 26)).united(
                    _oval(50 + sx * 26, 52, 19, 17))
    return marks.simplified()


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


def draw_bunny(p: QPainter, rect: QRectF, prop: str | None = None, *,
               blink: float = 0.0, mouth: float = 0.0, ears: float = 0.0,
               swing: float = 0.0, sad: float = 0.0, angry: float = 0.0,
               nightcap: bool = False, robot: bool = False, smug: bool = False,
               outfit: tuple[str, ...] | None = None, led: float = 0.0,
               nod: float = 0.0, dip: float = 0.0, look: float = 0.0,
               kit: dict | None = None, wave: float | None = None, kick: float = 0.0,
               hold: tuple | None = None):
    """Draw Bun fitted (aspect kept, centred) into `rect`. The keywords pose Bun for
    animation (ui/bunnywidget.py): `blink` 0..1 closes the eyes, `mouth` 0..1 opens
    the mouth (talking), `ears` tilts both ears outward by that many degrees,
    `swing` 0..1 brings the hammer down (0 = raised, 1 = striking the plank), and
    `sad` 0..1 worries his brows, wets his eyes, turns his smile down and brings his
    paws up under his chin (hoping), and `angry` 0..1 knits them the other way,
    crosses his arms, reddens his cheeks and pops a cross mark on his head (`swing`
    also swings the "bat"). `nightcap` puts his sleeping cap on. `robot` draws him as
    Robo-Bun, metal with glowing LED ears, eyes and chest.
    `smug`: half-shut eyes, one brow up and a lopsided smirk (he got away with it).
    `outfit`: bunnyfit pieces to dress him in (None: the current theme's, (): none).
    Robo-Bun wears no outfit. `led` 0..1 brightens Robo-Bun's LED ears and core (he
    pulses them while he works). `nod` tilts his head (and ears) on his neck by that many
    degrees and `dip` drops it that far on the canvas, the body staying put: a headbang,
    a nod to the beat, a curious tilt. `look` -1..1 turns his eyes left / right.
    `wave` -1..1 (None: not waving): his right paw (the viewer's) up by his cheek,
    swung that far from side to side: hello! (only with no prop).
    `kick` -1..1 moves his left foot (the viewer's right): back under him (-1), out in
    front, lifted, toes up (1): a sulky kick at the ground.
    `kit`: his look (bunnyfit.look: fur, floppy ears, extras, tail, eye / ear / nose
    colours, markings, belly, pads; None: the current theme's).
    `hold` (left, right): canvas points where the caller draws his paws (a skit's, holding
    something; None: that arm's free). Those arms reach there from his shoulders."""
    fit = () if robot else bunnyfit.outfit() if outfit is None else outfit
    if kit is None:
        kit = bunnyfit.look()
    kit = {**bunnyfit.VANILLA, **kit}
    extras = () if robot else kit["extras"]
    # dark glasses hide his eyes: no lids or tears under them, brows lifted clear
    hidden = not nightcap and any(name in bunnyfit.HIDE_EYES for name in fit)
    phones = QColor(theme.T["accent"])
    phones_hi = phones.lighter(145)
    phones_lo = phones.darker(128)
    s = min(rect.width() / W, rect.height() / H)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(rect.center().x() - W * s / 2, rect.center().y() - H * s / 2)
    p.scale(s, s)

    fur = ROBOT_FUR if robot else QColor(kit["fur"])
    iris, ear_pink, nose_col = QColor(kit["iris"]), QColor(kit["inner"]), QColor(kit["nose"])
    pattern = () if robot else tuple(kit["pattern"])
    marks = QColor(kit["marks"])
    fur_shade = (ROBOT_FUR_SHADE if robot else FUR_SHADE if fur == FUR else fur.darker(107))
    dark = not robot and fur.lightnessF() < 0.45   # dark fur: his face drawn in light lines
    face = FACE_LIGHT if dark else INK
    # which eyes sit on his markings (the patch: his left one): dark markings get the
    # light face lines and rims there too, and his smug lids are the markings' colour
    on_marks = ("mask" in pattern, "mask" in pattern or "patch" in pattern)
    marks_dark = marks.lightnessF() < 0.45
    eye_dark = tuple(dark if not m else marks_dark for m in on_marks)
    eye_face = tuple(FACE_LIGHT if d else INK for d in eye_dark)
    lid_fur = tuple(marks if m else fur for m in on_marks)
    ink_col = ROBOT_INK if robot else INK
    ink = QPen(ink_col, 2.4)
    ink.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    ink.setCapStyle(Qt.PenCapStyle.RoundCap)
    head_shape = bunnyfit.head_path()
    body_shape = bunnyfit.body_path()

    bunnyfit.draw(p, fit, "behind", ink)
    # ears (behind the head): both stand up, unless his look flops one or both over
    # at the middle. Sad, the top half of each folds down and outward (droopy, not
    # stuck out)
    fold = 115 * max(0.0, min(1.0, sad))

    def head():   # the head's own frame: tilted on the neck, dipped
        p.translate(50, 92 + dip)
        p.rotate(nod)
        p.translate(-50, -92)

    p.save()
    head()
    flops = {"up": (), "left": (-1,), "right": (1,), "both": (-1, 1)}[kit["ears"]]
    upright = [sd for sd in (-1, 1) if sd not in flops] or [-1]
    for side, bx, cx, cy, w, h, a, tilt in (
            (-1, 37, 34.5, 23, 22, 58, -7, -ears), (1, 63, 65.5, 17, 20, 66, 13, ears)):
        rest = REST_FOLD if side in flops and not robot else 0.0
        bent = max(fold, rest)
        hinge = REST_HINGE if rest else EAR_HINGE
        droop = None if robot or rest else _droop(side, h)
        p.save()
        p.translate(bx, 48)   # pivot at the base of the ear, where it meets the head
        p.rotate(tilt)
        p.translate(-bx, -48)
        p.translate(cx, cy)   # from here on: the ear's own frame, centred, upright
        p.rotate(a)
        bend = _ear_bend(side * bent, hinge)
        # (with "chomp", a bite out of the outer edge of his last upright ear)
        ear = (side, w, h, side * bent if bent > 0.5 else None, hinge,
               "chomp" in extras and side == upright[-1], droop is not None)
        lower, flap = _ear(*ear)
        # how much of the inner ear the flap shows: a flap folded right over shows its
        # furry back; his floppy ear only bends, so its pink runs on to the tip
        inner_on = (1.0 if rest and bent < rest + 8 else   # his floppy ear: pink to the tip
                    0.0 if bent > 50 else max(0.0, 1 - bent / 50))

        # the inner ear: (_inner_ear's arguments, its colour)
        curl = side if droop is not None and bent < 1 else 0
        if robot:
            parts = [((8, h - 14, 0.0, 3.0, curl, h), ROBOT_CYAN.lighter(100 + round(25 * led))),
                     ((3, h - 22, 0.0, 3.0, curl, h), ROBOT_CYAN_HI)]
        else:
            parts = [((w * 0.5, h - 16, 0.0, 3.0, curl, h), ear_pink)]
        for piece, alpha in ((lower, 1.0), (flap, inner_on)):
            if piece is None:
                continue
            p.setPen(ink)
            p.setBrush(fur)
            p.drawPath(piece)
            p.save()
            p.setClipPath(piece)
            p.setPen(Qt.PenStyle.NoPen)
            if robot and led > 0 and piece is lower:
                halo = QColor(ROBOT_CYAN)
                halo.setAlpha(round(110 * led))
                _ellipse(p, 0, 2, 15, h - 4, halo)
            if alpha > 0:
                p.setOpacity(p.opacity() * alpha)
                for shape, col in parts:   # (the flap: only the half that went over with it)
                    shape = (_flap_inner(shape, side * bent, hinge) if piece is flap else
                             _inner_ear(*shape))
                    p.setBrush(col)
                    p.drawPath(shape)
            p.restore()
        if flap is not None and not robot and bent < rest + 8:
            # his floppy ear bends out and back: the pink inside shows right up to the
            # bend, rounded off there
            clip, pink = _floppy_pink(ear, parts[0][0], w, hinge)
            p.save()
            p.setClipPath(clip)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(ear_pink)
            p.drawPath(pink)
            # and round the bend: a pink disc as wide as the inner ear there, so no
            # wedge of fur opens between the two halves' pink
            r = w * 0.24
            p.drawEllipse(QRectF(-r, hinge - r, 2 * r, 2 * r))
            p.restore()
        if "earring" in extras and side == upright[0]:   # a gold hoop through the edge
            ex_, ey_ = side * w * 0.47, -h * 0.02
            ring = QPainterPath()
            ring.addEllipse(QPointF(ex_ + side * 2.2, ey_ + 3.4), 3.3, 3.6)
            _stroke(p, ring, ink_col, 3.8)
            _stroke(p, ring, bunnyfit.GOLD, 2.0)
            _ellipse(p, ex_, ey_, 2.6, 2.6, bunnyfit.GOLD, QPen(ink_col, 1.1))
        if robot:   # antenna bulb at the ear tip (which folds down with the flap)
            tip = bend.map(QPointF(0, -h / 2 + 2))
            if led > 0:
                halo = QColor(ROBOT_CYAN)
                halo.setAlpha(round(140 * led))
                _ellipse(p, tip.x(), tip.y(), 11 + 4 * led, 11 + 4 * led, halo)
            _ellipse(p, tip.x(), tip.y(), 6.5, 6.5, ROBOT_CYAN_HI if led > 0.6 else ROBOT_CYAN,
                     ink)
            _ellipse(p, tip.x() - 1, tip.y() - 1, 2, 2, QColor("white"))
        p.restore()
        if robot:   # pivot bolt at the ear base
            p.save()
            p.translate(bx, 48)
            p.rotate(tilt)
            _ellipse(p, 0, 0, 6, 6, ROBOT_BOLT, ink)
            _ellipse(p, 0, 0, 2, 2, ROBOT_INK, None)
            p.restore()
    p.restore()

    # tail (peeking out behind him), body, front legs, feet
    if not robot:
        p.setPen(ink)
        p.setBrush(fur)
        p.drawPath(_tail_shape(kit["tail"]))
    head_xf = QTransform().translate(50, 92 + dip).rotate(nod).translate(-50, -92)
    arm_fur = ROBOT_FUR if robot else bunnyfit.sleeve(fit) or fur
    _reach(p, prop, arm_fur, ink, head_xf)
    waving = wave is not None and prop is None
    wave_k = wave or 0.0
    if waving:   # the waving arm, up past his cheek from behind him
        wx, wy, _lean = _wave_paw(wave_k)
        _arm(p, ((63, 95), (80, 96), (wx, wy), 5.0), arm_fur, ink)
    p.setPen(ink)
    p.setBrush(fur)
    p.drawPath(body_shape)
    spots = _marks(pattern, "body")
    if not spots.isEmpty():
        p.save()
        p.setClipPath(body_shape)
        p.fillPath(spots, marks)
        p.restore()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(body_shape)   # (his outline back over the markings' edges)
    belly = (QColor(kit["belly"]) if kit["belly"] and not robot else
             fur.lighter(125) if dark else fur_shade)
    _ellipse(p, 50, 105, 28, 21, belly)   # tummy patch
    if not robot:
        _stroke(p, _arc(48.4, 109.8, 50, 111.8, 51.6, 109.8), _navel(belly), 1.3)
        _poof(p, QColor(kit["belly"]).lighter(112) if kit["belly"] else
              fur.lighter(140) if dark else QColor("#ffffff"))
    pads = QColor(kit["pads"]) if kit["pads"] and not robot else None
    for x, a in ((35.5, 9), (64.5, -9)):   # his feet, poking out front, turned out a bit
        y = 114.2
        if kick and x > 50:
            x, y, a = (x + 14 * kick, y - 11 * kick, a - 45 * kick) if kick > 0 else (
                x + 5 * kick, y + 3 * kick, a + 10 * kick)
        _ellipse(p, x, y, 20, 10.4, fur, ink, a)
        if pads is not None:
            p.save()
            p.translate(x, y)
            p.rotate(a)
            _pads(p, pads)
            p.restore()

    if robot:
        # glowing AI audio core on his tummy, under his paws
        _ellipse(p, 50, 107, 13, 13, QColor("#1c2230"), ink)
        if led > 0:
            halo = QColor(ROBOT_CYAN)
            halo.setAlpha(round(120 * led))
            _ellipse(p, 50, 107, 12 + 4 * led, 12 + 4 * led, halo)
        _ellipse(p, 50, 107, 8, 8, ROBOT_CYAN, None)
        _ellipse(p, 50, 107, 3.2, 3.2, ROBOT_CYAN_HI, None)

    # what's round his neck and on his body stays with the body when his head moves
    body = tuple(n for n in fit if n in BODY_PIECES)
    fit_head = tuple(n for n in fit if n not in BODY_PIECES)
    bunnyfit.draw(p, body, "back", ink)
    # what's on his body (a sweater) under his arms, his arms under his head; what's
    # round his neck goes over his head's chin, after it
    worn = tuple(n for n in body if n not in bunnyfit.NECK)
    bunnyfit.draw(p, worn, "face", ink, hats=not nightcap)
    _paws(p, prop, sad, angry, fur, ink, None if robot else bunnyfit.sleeve(fit), waving,
          hold)
    p.save()
    head()
    bunnyfit.draw(p, fit_head, "back", ink)
    p.setPen(ink)
    p.setBrush(fur)
    p.drawPath(head_shape)
    patches = _marks(pattern, "head")
    if not patches.isEmpty():
        p.save()
        p.setClipPath(head_shape)
        p.fillPath(patches, marks)
        p.restore()
    _shade(p, head_shape, 70, 92, 30, fur_shade, 150)   # rounder: shade low on his far side
    if not patches.isEmpty():
        p.setPen(ink)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(head_shape)
    bunnyfit.draw(p, fit_head, "under", ink, hats=not nightcap)

    # headphones: a thick band over the head, round cups on the sides
    band = QPainterPath(QPointF(17.5, 62))
    band.cubicTo(QPointF(14, 22.5), QPointF(86, 22.5), QPointF(82.5, 62))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(ink_col, 10, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawPath(band)
    p.setPen(QPen(ROBOT_CYAN if robot else phones, 6.2, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))
    p.drawPath(band)
    if not robot:   # the shine along the band
        shine = QPainterPath(QPointF(28, 37))
        shine.cubicTo(QPointF(36, 30), QPointF(46, 29), QPointF(52, 29))
        _stroke(p, shine, phones_hi, 1.8)
    for x, sx in ((6.5, -1), (79.5, 1)):
        p.setPen(ink)
        p.setBrush(QColor("#222838") if robot else phones)
        cup = QRectF(x, 49.5, 14, 28)
        p.drawRoundedRect(cup, 7, 7)
        if not robot:   # the cushion against his head, and a shine on the cup
            cushion = QRectF(x + (10 if sx < 0 else 0), 53, 4, 21)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(phones_lo)
            p.drawRoundedRect(cushion, 2, 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ROBOT_CYAN if robot else phones_hi)
        p.drawRoundedRect(QRectF(x + (3 if sx < 0 else 7), 54, 3.4, 11), 1.7, 1.7)

    if nightcap:
        _nightcap(p, ink)
    bunnyfit.draw(p, fit_head, "over", ink, hats=not nightcap)

    # face
    if "shiner" in extras:   # a black eye: a soft purple bruise round his left eye
        _glow(p, EYES[0], EYE_Y + 0.5, 22, 21, QColor(110, 70, 160, 175))
        _glow(p, EYES[0] - 1.5, EYE_Y + 7.5, 13, 6, QColor(205, 175, 70, 110))
    shut = blink > 0.6
    gx = 1.6 * max(-1.0, min(1.0, look))
    for i, x in enumerate(EYES):
        if robot:
            # tech visor socket
            _ellipse(p, x, EYE_Y, 12, 13, QColor("#181e2b"), ink)
            if shut:
                _ellipse(p, x, EYE_Y, 8, 2.4, ROBOT_CYAN, None)
            elif sad > 0.5:
                _ellipse(p, x + gx, EYE_Y + 0.5, 7.5, 7.5, ROBOT_CYAN, None)
                _ellipse(p, x + gx + 1.2, EYE_Y - 1, 2.5, 2.5, ROBOT_CYAN_HI, None)
            else:
                _ellipse(p, x + gx, EYE_Y, 8, 10 * (1 - blink), ROBOT_CYAN, None)
                _ellipse(p, x + gx + 1.6, EYE_Y - 2.5, 3, 3, ROBOT_CYAN_HI, None)
                _ellipse(p, x + gx - 1.4, EYE_Y + 2.5, 1.5, 1.5, QColor("white"), None)
            continue

        if shut:   # shut: a happy little arc, or a sleepy one under the nightcap
            if nightcap:
                arc = _arc(x - 5, EYE_Y, x, EYE_Y + 3.6, x + 5, EYE_Y)
            else:
                arc = _arc(x - 5, EYE_Y + 1.5, x, EYE_Y - 3, x + 5, EYE_Y + 1.5)
            _stroke(p, arc, eye_face[i], 2.3)
            continue
        ex = x + gx
        ew, eh = 11.6 + sad, (12.6 + sad) * (1 - blink)
        if eye_dark[i] and eh > 1:   # a light rim, so his eyes show on dark fur
            _ellipse(p, ex, EYE_Y, ew + 3.4, eh + 3.4, FACE_LIGHT)
        eye = QPainterPath()
        eye.addEllipse(QRectF(ex - ew / 2, EYE_Y - eh / 2, ew, eh))
        p.fillPath(eye, EYE)
        p.save()   # a warm coloured iris glowing up from the bottom of the eye
        p.setClipPath(eye)
        _glow(p, ex, EYE_Y + eh * 0.22, ew * 0.8, eh * 0.6, iris)
        p.restore()
        if eh > 4:   # the sparkles: a big shine up on his right, two little ones low
            _ellipse(p, ex + 2.2, EYE_Y - 2.8, 4.4, 4.4, QColor("white"))
            _ellipse(p, ex - 2.4, EYE_Y + 3.0, 1.8, 1.8, QColor("white"))
            _ellipse(p, ex + 3.2, EYE_Y + 2.0, 1.1, 1.1, QColor("white"))
        if smug and not hidden:   # heavy lids: fur over the top half, a flat lid line
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(lid_fur[i])
            p.drawRect(QRectF(x - 7.5, EYE_Y - 9, 15, 8.5))
            _stroke(p, _arc(x - 5.6, EYE_Y - 0.5, x, EYE_Y - 1.2, x + 5.6, EYE_Y - 0.5),
                    eye_face[i], 2.4)
        if sad > 0.05 and not hidden:   # welling up
            c = QColor("#8fd3ff")
            c.setAlphaF(0.8 * sad)
            _ellipse(p, x, EYE_Y + 6.5, 8.5, 2.6 * sad, c)
    if robot:                 # LED cheeks and a sensor nose
        for x in (29, 71):
            _ellipse(p, x, 73, 8, 4, ROBOT_CYAN_GLOW, None)
            _ellipse(p, x - 2, 73, 2, 2, ROBOT_CYAN, None)
            _ellipse(p, x + 2, 73, 2, 2, ROBOT_CYAN, None)
        _ellipse(p, 50, 70.5, 7, 5, QColor("#3f485c"), ink)
        _ellipse(p, 50, 70.5, 2.4, 2.4, ROBOT_CYAN, None)
    else:
        up = 3.5 if hidden else 0.0
        worried = min(1.0, sad * 1.4)
        cross = min(1.0, angry * 1.4)
        calm = max(0.0, 1 - worried - cross) * (0.0 if smug else 1.0)
        if calm > 0.02:   # resting brows: two little soft arcs
            c = QColor(BROW)
            c.setAlphaF(BROW.alphaF() * calm)
            for i, x in enumerate(EYES):
                b = c
                if eye_dark[i] and not dark:   # (on dark markings: light brows)
                    b = QColor(FACE_LIGHT)
                    b.setAlphaF(0.75 * calm)
                _stroke(p, _arc(x - 3.2, 54.3 - up, x, 52.3 - up, x + 3.2, 54.3 - up), b, 1.6)
        if worried > 0.02:   # worried brows, inner ends lifted
            for i, (x, sx) in enumerate(((EYES[0], -1), (EYES[1], 1))):
                c = QColor(eye_face[i])
                c.setAlphaF(worried)
                _stroke(p, _arc(x + sx * 5.5, 53.5 + sad - up, x + sx * 1.5, 52 - up,
                                x - sx * 3, 51.5 - 4 * sad - up), c, 2.2)
        if smug:                  # one brow flat, the other cocked up
            lx, rx = EYES
            _stroke(p, _arc(lx - 5.5, 54.5 - up, lx, 54 - up, lx + 5.5, 54.8 - up),
                    eye_face[0], 2.2)
            _stroke(p, _arc(rx - 6, 52 - up, rx - 0.5, 46.5 - up, rx + 5.5, 50.5 - up),
                    eye_face[1], 2.2)
        if cross > 0.02:          # cross brows, inner ends pulled down
            for i, (x, sx) in enumerate(((EYES[0], -1), (EYES[1], 1))):
                c = QColor(eye_face[i])
                c.setAlphaF(cross)
                _stroke(p, _arc(x + sx * 6, 51.5 - 2 * angry - up, x + sx * 1, 51.5 - up,
                                x - sx * 3.5, 53 + 3 * angry - up), c, 2.6)
        blush = QColor(CHEEK)
        if angry > 0.05:
            blush = QColor(255, 70, 100, min(255, 120 + round(110 * angry)))
        for x in (27, 73):
            w, h = 15 + 2 * angry, 9.5 + angry
            _glow(p, x, 74, w, h, blush)
        if "freckles" in extras:
            for x, y in ((24, 71.5), (28, 70.5), (26.5, 74), (76, 71.5), (72, 70.5), (73.5, 74)):
                _ellipse(p, x, y, 1.5, 1.5, QColor(196, 120, 110, 190))
        if "bandaid" in extras:   # a plaster on his right cheek
            p.save()
            p.translate(73, 72)
            p.rotate(-28)
            p.setPen(QPen(ink_col, 1.3))
            p.setBrush(QColor("#f3c79a"))
            p.drawRoundedRect(QRectF(-7, -2.6, 14, 5.2), 2.6, 2.6)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#e2a877"))
            p.drawRoundedRect(QRectF(-2.4, -1.9, 4.8, 3.8), 1, 1)
            p.restore()
        nose = QPainterPath(QPointF(47.2, 69.3))
        nose.quadTo(QPointF(50, 68.4), QPointF(52.8, 69.3))
        nose.quadTo(QPointF(53.6, 69.8), QPointF(52.6, 71))
        nose.lineTo(50.9, 72.6)
        nose.quadTo(QPointF(50, 73.3), QPointF(49.1, 72.6))
        nose.lineTo(47.4, 71)
        nose.quadTo(QPointF(46.4, 69.8), QPointF(47.2, 69.3))
        nose.closeSubpath()
        p.setPen(QPen(NOSE_EDGE if nose_col == NOSE else nose_col.darker(125), 1.0,
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(nose_col)
        p.drawPath(nose)
        _ellipse(p, 49, 69.8, 1.8, 1, QColor(255, 255, 255, 170))
    line = ROBOT_CYAN if robot else face
    if mouth > 0.08:          # open, as if talking: the smile's top, a round bottom
        oh = 2.5 + 6.5 * min(1.0, mouth)
        hw = 4.2 + 1.3 * mouth
        top = QPainterPath(QPointF(50 - hw, 75.2))
        top.quadTo(QPointF(50 - hw / 2, 77), QPointF(50, 75.4))
        top.quadTo(QPointF(50 + hw / 2, 77), QPointF(50 + hw, 75.2))
        shape = QPainterPath(top)
        shape.cubicTo(QPointF(50 + hw, 75.5 + oh * 1.25), QPointF(50 - hw, 75.5 + oh * 1.25),
                      QPointF(50 - hw, 75.2))
        shape.closeSubpath()
        if robot:
            p.setPen(QPen(ROBOT_CYAN, 1.6))
            p.setBrush(QColor("#181e2b"))
            p.drawPath(shape)
            p.setPen(QPen(ROBOT_CYAN_HI, 1.4))
            p.drawLine(QPointF(47, 76 + oh / 2), QPointF(53, 76 + oh / 2))
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(MOUTH)
            p.drawPath(shape)
            p.save()
            p.setClipPath(shape)
            _ellipse(p, 50, 75.5 + oh * 0.95, hw * 1.3, oh * 0.6, NOSE)
            p.restore()
            p.setPen(QPen(face, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                          Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(shape)
    elif smug and not robot:  # a lopsided smirk, up on one side
        _stroke(p, _arc(44, 76.5, 51, 79.5, 57, 74), face, 1.8)
    elif sad > 0.5 or angry > 0.4:   # a little wobbly frown
        _stroke(p, _arc(45.5, 78.5, 50, 74.8, 54.5, 78.5), line, 1.8)
    else:                     # his resting smile: a soft double curve under the nose
        smile = QPainterPath(QPointF(44.8, 75))
        smile.quadTo(QPointF(47.4, 78.4), QPointF(50, 75.6))
        smile.quadTo(QPointF(52.6, 78.4), QPointF(55.2, 75))
        _stroke(p, smile, line, 1.8)
    if not robot:   # the little line from his nose to his mouth
        _stroke(p, _arc(50, 72.8, 50, 74.2, 50, 75.4), face, 1.4)

    bunnyfit.draw(p, fit_head, "face", ink, hats=not nightcap, shut=shut)
    if prop == "headphones":   # (his paw is on the ear cup: it goes with his head)
        _draw_prop(p, prop, ink, swing, fur=fur)
    if angry > 0.5:           # the cartoon cross-vein mark, up on his forehead
        p.setPen(QPen(CROSS, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        cx, cy, k = 72, 41, 0.6 + 0.4 * angry
        for ax, ay in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            arc = QPainterPath(QPointF(cx + ax * 1.5 * k, cy + ay * 6 * k))
            arc.quadTo(cx + ax * 1.5 * k, cy + ay * 1.5 * k, cx + ax * 6 * k, cy + ay * 1.5 * k)
            p.drawPath(arc)
    p.restore()   # (the head's frame)
    if waving:   # the paw itself, in front of his cheek
        wx, wy, lean = _wave_paw(wave_k)
        p.setPen(ink)
        p.setBrush(fur)
        p.drawPath(_bean(wx, wy, 12, 13.5, lean + 180))   # (its round toes up)
        if pads is not None:   # his palm's pad prints show as he waves
            p.save()
            p.translate(wx, wy)
            p.rotate(lean)   # (the paw's turned over; its prints' toes stay up)
            p.translate(0, 0.6)
            p.scale(0.66, 0.66)   # (a hand's prints: smaller, well inside the paw)
            _pads(p, pads)
            p.restore()
    bunnyfit.draw(p, tuple(n for n in body if n in bunnyfit.NECK), "face", ink,
                  hats=not nightcap)
    if prop != "headphones":
        _draw_prop(p, prop, ink, swing, fur=fur)
    p.restore()


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
        p.save()
        p.translate(80, 92)
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
        _ellipse(p, 80, 92, 12, 10, fur, ink)
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
        p.save()
        p.translate(80, 92)
        p.rotate(25 + 98 * max(0.0, min(1.0, swing)))
        p.setPen(ink)
        p.setBrush(QColor("#9aa3b5"))
        p.drawRoundedRect(QRectF(-3, -28, 6, 32), 2, 2)
        p.drawRoundedRect(QRectF(-8, -36, 16, 10), 2, 2)
        p.setBrush(fur)
        p.drawRect(QRectF(-3, -37, 6, 6))
        p.restore()
        _ellipse(p, 80, 92, 12, 10, fur, ink)


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


def _music_note(p: QPainter, x, y, k, col: QColor | None = None):
    col = col or QColor(theme.T["accent"])
    p.setPen(QPen(col, 2.2 * k, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(x + 4 * k, y), QPointF(x + 4 * k, y + 12 * k))
    p.drawLine(QPointF(x + 4 * k, y), QPointF(x + 9 * k, y + 3 * k))
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


def _sparkle(p: QPainter, x, y, r, col: QColor):
    path = QPainterPath(QPointF(x, y - r))
    path.quadTo(QPointF(x, y), QPointF(x + r, y))
    path.quadTo(QPointF(x, y), QPointF(x, y + r))
    path.quadTo(QPointF(x, y), QPointF(x - r, y))
    path.quadTo(QPointF(x, y), QPointF(x, y - r))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(col)
    p.drawPath(path)


sparkle = _sparkle


# room round his canvas in a picture of him, canvas units: an upright ear reaches 8
# above it and a collar (Vampire's) 5 past each side
ROOM_TOP, ROOM_SIDE = 9.0, 7.0


def look_colour(part: str) -> QColor:
    """A colour of the current theme's look (`bunnyfit.LOOKS`: "fur", "inner", ...),
    for bits of him drawn outside draw_bunny (a paw holding a skit's prop, his ears
    popping out of the build cloud), so they match the rest of him."""
    return QColor(bunnyfit.look()[part])


def bunny_image(height: int, prop: str | None = None, dpr: float = 1.0,
                robot: bool = False, smug: bool = False, room: bool = True) -> QImage:
    """Bun `height` px tall in the current theme, with ROOM_TOP above him and ROOM_SIDE
    either side so an upright ear, a tall hat or a wide collar isn't cut off (`room`
    False: just his canvas, for art that crops him itself)."""
    s = height * dpr / H
    top, side = (ROOM_TOP * s, ROOM_SIDE * s) if room else (0.0, 0.0)
    h = max(1, math.ceil(height * dpr + top))
    w = max(1, math.ceil(W * s + 2 * side))
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    draw_bunny(p, QRectF(side, h - height * dpr, W * s, height * dpr), prop,
               robot=robot, smug=smug)
    p.end()
    img.setDevicePixelRatio(dpr)
    return img


def bunny_pixmap(height: int, prop: str | None = None, dpr: float = 1.0,
                 robot: bool = False, smug: bool = False, room: bool = True) -> QPixmap:
    return QPixmap.fromImage(bunny_image(height, prop, dpr, robot=robot, smug=smug,
                                         room=room))
