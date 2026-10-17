"""Bun, the mascot: a cartoon bunny in gaming headphones, drawn with QPainter so it's
crisp at any size and needs no image files. Used by the quick-setup guide (a
different prop on each page) and by scripts/pictures/make_bunny.py for the installer's artwork.

    bunny_image(160, prop="mic")   # QImage, transparent background
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QImage, QPainter, QPainterPath,
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
IRIS = QColor("#8a5cc7")                # the coloured glow low in his eyes
BROW = QColor(196, 140, 140, 150)       # his little resting brows
PINK = QColor("#ffb3c7")
NOSE = QColor("#ff8fae")
NOSE_EDGE = QColor("#e0708f")
MOUTH = QColor("#7a2a45")
CHEEK = QColor(255, 122, 150, 165)
# his headphones are the current theme's accent (theme.T, read at paint time)

PROPS = (None, "mic", "headphones", "plug", "star", "hammer", "bat", "wrench",
         "hammer_broken")
# the props that take a paw (the one on the right, both): those paws leave his lap
ONE_PAW = {"mic", "headphones", "plug", "bat", "hammer", "hammer_broken", "wrench"}
BOTH_PAWS = {"star"}
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


EAR_HINGE = 0.5    # where an ear folds when he's sad: about its middle (ear frame)
REST_FOLD = 100.0  # his right ear (the viewer's right) always flops over and down...
REST_HINGE = 7.0   # ... bending a little below its middle, so a good bit stands up first


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


def _ear_bend(fold: float, hinge: float = EAR_HINGE) -> QTransform:
    """The ear frame above `hinge` folded `fold` degrees about it (+ = to his left,
    the viewer's right)."""
    return QTransform().translate(0, hinge).rotate(fold).translate(0, -hinge)


def _ear_pieces(w: float, h: float, bend: QTransform | None, hinge: float = EAR_HINGE):
    """An ear in two pieces, its own frame: the part that stays up (ending in a round
    knee where it bends) and the flap folded over by `bend` (painted on top: it hides
    the inner ear behind it). Straight (`bend` None): the whole ear and no flap."""
    full = _ear_shape(w, h)
    if bend is None:
        return full, None
    below, above = QPainterPath(), QPainterPath()
    below.addRect(QRectF(-w, hinge, 2 * w, h))
    above.addRect(QRectF(-w, -h, 2 * w, h + hinge))
    kw = w * 0.92   # (the ear's width there)
    knee = QPainterPath()
    knee.addEllipse(QRectF(-kw / 2, hinge - kw / 2, kw, kw))
    return full.intersected(below), bend.map(full.intersected(above)).united(knee)


def _stroke(p: QPainter, path: QPainterPath, col: QColor, width: float):
    p.setPen(QPen(col, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)


def _arc(x0, y0, cx, cy, x1, y1) -> QPainterPath:
    path = QPainterPath(QPointF(x0, y0))
    path.quadTo(QPointF(cx, cy), QPointF(x1, y1))
    return path


# His little front paws: a bunny has no arms to speak of, just two bean-shaped paws
# tucked up under his chin: (x, y, width, height, lean), the viewer's left one first.
# Resting, a little apart; hoping, pressed together, tips touching; cross, folded one
# over the other across his chest (the viewer's right one on top).
PAWS_REST = ((42, 97.5, 10.5, 17, 9), (58, 97.5, 10.5, 17, -9))
PAWS_HOPE = ((46.3, 96.2, 10, 16.5, 22), (53.7, 96.2, 10, 16.5, -22))
PAWS_CROSS = ((54, 98.8, 10.5, 19, -74), (46, 100.4, 10.5, 19, 74))
# where a prop puts each paw (None: that paw stays on his tummy). "headphones" is in the
# head's frame: the paw is on the ear cup
PROP_PAWS = {"mic": (None, (76, 97)), "headphones": (None, (86, 72)),
             "plug": (None, (78, 100)), "star": ((20, 92), (80, 92)),
             "hammer": (None, (80, 92)), "hammer_broken": (None, (80, 92)),
             "bat": (None, (80, 92)), "wrench": (None, (80, 92))}
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


def _prop_arm(shoulder, paw):
    """An arm reaching from `shoulder` to a prop at `paw`, the elbow sagging a little."""
    mx, my = (shoulder[0] + paw[0]) / 2, (shoulder[1] + paw[1]) / 2
    dx, dy = paw[0] - shoulder[0], paw[1] - shoulder[1]
    d = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / d, dx / d
    if ny < 0:
        nx, ny = -nx, -ny
    return (shoulder, (mx + nx * 3, my + ny * 3), paw, 4.4)


def _reach(p: QPainter, prop, fur: QColor, ink: QPen, head_xf: QTransform):
    """The arms a prop takes (one or both), reaching out to it from behind his body."""
    reach = PROP_PAWS.get(prop or "", (None, None))
    for i in (0, 1):
        if reach[i] is not None:
            to = reach[i]
            if prop == "headphones":   # (on the ear cup: it moves with his head)
                q = head_xf.map(QPointF(*to))
                to = (q.x(), q.y())
            if prop == "headphones":   # up past his cheek, elbow out
                _arm(p, ((62, 95), (85, 95), to, 5.4), fur, ink)
            else:
                _arm(p, _prop_arm((41, 97) if i == 0 else (59, 97), to), fur, ink)


def _paws(p: QPainter, prop, sad: float, angry: float, fur: QColor, ink: QPen,
          head: QPainterPath):
    """His front paws, tucked up under his chin (`head`): they come together as `sad`
    grows (hoping) and fold over each other when he's cross (`angry`). A paw a prop
    takes isn't here: it's out holding it (_reach)."""
    clasp = cross = 0.0
    if prop is None:
        cross = _smooth((angry - 0.35) / 0.4)
        clasp = _smooth((sad - 0.3) / 0.45) * (1 - cross)
    reach = PROP_PAWS.get(prop or "", (None, None))
    for i in (0, 1):
        if reach[i] is not None:
            continue
        x, y, w, h, lean = _lerp(_lerp(PAWS_REST[i], PAWS_HOPE[i], clasp), PAWS_CROSS[i], cross)
        p.setPen(ink)
        p.setBrush(fur)
        p.drawPath(_bean(x, y, w, h, lean).subtracted(head))


def draw_bunny(p: QPainter, rect: QRectF, prop: str | None = None, *,
               blink: float = 0.0, mouth: float = 0.0, ears: float = 0.0,
               swing: float = 0.0, sad: float = 0.0, angry: float = 0.0,
               nightcap: bool = False, robot: bool = False, smug: bool = False,
               outfit: tuple[str, ...] | None = None, led: float = 0.0,
               nod: float = 0.0, dip: float = 0.0, look: float = 0.0):
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
    a nod to the beat, a curious tilt. `look` -1..1 turns his eyes left / right."""
    fit = () if robot else bunnyfit.outfit() if outfit is None else outfit
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

    fur = ROBOT_FUR if robot else FUR
    fur_shade = ROBOT_FUR_SHADE if robot else FUR_SHADE
    ink_col = ROBOT_INK if robot else INK
    ink = QPen(ink_col, 2.4)
    ink.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    ink.setCapStyle(Qt.PenCapStyle.RoundCap)
    head_shape = bunnyfit.head_path()
    body_shape = bunnyfit.body_path()

    bunnyfit.draw(p, fit, "behind", ink)
    # ears (behind the head): the left one stands up, the right one always flops over
    # at the middle. Sad, the top half of each folds down and outward (droopy, not
    # stuck out)
    fold = 115 * max(0.0, min(1.0, sad))

    def head():   # the head's own frame: tilted on the neck, dipped
        p.translate(50, 92 + dip)
        p.rotate(nod)
        p.translate(-50, -92)

    p.save()
    head()
    for side, bx, cx, cy, w, h, a, tilt, rest in (
            (-1, 37, 34.5, 27, 22, 50, -7, -ears, 0.0),
            (1, 63, 65.5, 22, 19.5, 56, 13, ears, 0.0 if robot else REST_FOLD)):
        bent = max(fold, rest)
        hinge = REST_HINGE if rest else EAR_HINGE
        p.save()
        p.translate(bx, 48)   # pivot at the base of the ear, where it meets the head
        p.rotate(tilt)
        p.translate(-bx, -48)
        p.translate(cx, cy)   # from here on: the ear's own frame, centred, upright
        p.rotate(a)
        bend = _ear_bend(side * bent, hinge)
        lower, flap = _ear_pieces(w, h, bend if bent > 0.5 else None, hinge)
        # how much of the inner ear the flap shows: a flap folded right over shows its
        # furry back; his floppy ear only bends, so its pink runs on to the tip
        inner_on = (1.0 if rest and bent < rest + 8 else   # his floppy ear: pink to the tip
                    0.0 if bent > 50 else max(0.0, 1 - bent / 50))
        edge = QColor(fur_shade)
        edge.setAlpha(150)

        def inner(col, iw, ih, dx=0.0, dy=3.0):
            shape = QTransform().translate(dx, dy).map(_ear_shape(iw, ih))
            return shape, col

        if robot:
            parts = [inner(ROBOT_CYAN.lighter(100 + round(25 * led)), 8, h - 14),
                     inner(ROBOT_CYAN_HI, 3, h - 22)]
        else:
            parts = [inner(PINK, w * 0.5, h - 16)]
        for piece, mapped, alpha in ((lower, QTransform(), 1.0), (flap, bend, inner_on)):
            if piece is None:
                continue
            p.setPen(ink)
            p.setBrush(fur)
            p.drawPath(piece)
            p.save()
            p.setClipPath(piece)
            p.setPen(Qt.PenStyle.NoPen)
            if not robot:   # a soft shade down the outer edge
                p.setBrush(edge)
                p.drawPath(mapped.map(QTransform().translate(side * w * 0.38, 1).map(
                    _ear_shape(w * 0.45, h - 4))))
            if robot and led > 0 and piece is lower:
                halo = QColor(ROBOT_CYAN)
                halo.setAlpha(round(110 * led))
                _ellipse(p, 0, 2, 15, h - 4, halo)
            if alpha > 0:
                p.setOpacity(p.opacity() * alpha)
                for shape, col in parts:
                    if piece is flap:   # (only the half that went over with it)
                        top = QPainterPath()
                        top.addRect(QRectF(-30, -60, 60, 60 + hinge))
                        shape = bend.map(shape.intersected(top))
                    p.setBrush(col)
                    p.drawPath(shape)
            p.restore()
        if flap is not None and not robot and bent < rest + 8:
            # his floppy ear bends out and back: the pink inside shows right up to the
            # bend, rounded off there
            top = QPainterPath()
            top.addRect(QRectF(-30, hinge, 60, 60))
            top.addEllipse(QRectF(-w * 0.25, hinge - w * 0.25, w * 0.5, w * 0.5))
            p.save()
            p.setClipPath(lower.united(flap))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(PINK)
            p.drawPath(parts[0][0].intersected(top.simplified()))
            p.restore()
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
        _ellipse(p, 24, 111, 12.5, 11.5, fur, ink)
    head_xf = QTransform().translate(50, 92 + dip).rotate(nod).translate(-50, -92)
    _reach(p, prop, ROBOT_FUR if robot else bunnyfit.sleeve(fit) or fur, ink, head_xf)
    p.setPen(ink)
    p.setBrush(fur)
    p.drawPath(body_shape)
    _ellipse(p, 50, 105, 28, 21, fur_shade)   # his tummy patch
    for x, a in ((36.5, 9), (63.5, -9)):   # his feet, poking out front, turned out a bit
        _ellipse(p, x, 114.6, 16, 8.6, fur, ink, a)

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
    p.save()
    head()
    bunnyfit.draw(p, fit_head, "back", ink)
    p.setPen(ink)
    p.setBrush(fur)
    p.drawPath(head_shape)
    _shade(p, head_shape, 70, 92, 30, fur_shade, 150)   # rounder: shade low on his far side
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
    shut = blink > 0.6
    gx = 1.6 * max(-1.0, min(1.0, look))
    for x in EYES:
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
            _stroke(p, arc, INK, 2.3)
            continue
        ex = x + gx
        ew, eh = 11.6 + sad, (12.6 + sad) * (1 - blink)
        eye = QPainterPath()
        eye.addEllipse(QRectF(ex - ew / 2, EYE_Y - eh / 2, ew, eh))
        p.fillPath(eye, EYE)
        p.save()   # a warm coloured iris glowing up from the bottom of the eye
        p.setClipPath(eye)
        _glow(p, ex, EYE_Y + eh * 0.22, ew * 0.8, eh * 0.6, IRIS)
        p.restore()
        if eh > 4:   # the sparkles: a big shine up on his right, two little ones low
            _ellipse(p, ex + 2.2, EYE_Y - 2.8, 4.4, 4.4, QColor("white"))
            _ellipse(p, ex - 2.4, EYE_Y + 3.0, 1.8, 1.8, QColor("white"))
            _ellipse(p, ex + 3.2, EYE_Y + 2.0, 1.1, 1.1, QColor("white"))
        if smug and not hidden:   # heavy lids: fur over the top half, a flat lid line
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fur)
            p.drawRect(QRectF(x - 7.5, EYE_Y - 9, 15, 8.5))
            _stroke(p, _arc(x - 5.6, EYE_Y - 0.5, x, EYE_Y - 1.2, x + 5.6, EYE_Y - 0.5),
                    INK, 2.4)
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
            for x in EYES:
                _stroke(p, _arc(x - 3.2, 54.3 - up, x, 52.3 - up, x + 3.2, 54.3 - up), c, 1.6)
        if worried > 0.02:   # worried brows, inner ends lifted
            c = QColor(INK)
            c.setAlphaF(worried)
            for x, sx in ((EYES[0], -1), (EYES[1], 1)):
                _stroke(p, _arc(x + sx * 5.5, 53.5 + sad - up, x + sx * 1.5, 52 - up,
                                x - sx * 3, 51.5 - 4 * sad - up), c, 2.2)
        if smug:                  # one brow flat, the other cocked up
            lx, rx = EYES
            _stroke(p, _arc(lx - 5.5, 54.5 - up, lx, 54 - up, lx + 5.5, 54.8 - up), INK, 2.2)
            _stroke(p, _arc(rx - 6, 52 - up, rx - 0.5, 46.5 - up, rx + 5.5, 50.5 - up), INK, 2.2)
        if cross > 0.02:          # cross brows, inner ends pulled down
            c = QColor(INK)
            c.setAlphaF(cross)
            for x, sx in ((EYES[0], -1), (EYES[1], 1)):
                _stroke(p, _arc(x + sx * 6, 51.5 - 2 * angry - up, x + sx * 1, 51.5 - up,
                                x - sx * 3.5, 53 + 3 * angry - up), c, 2.6)
        blush = QColor(CHEEK)
        if angry > 0.05:
            blush = QColor(255, 70, 100, min(255, 120 + round(110 * angry)))
        for x in (27, 73):
            w, h = 15 + 2 * angry, 9.5 + angry
            _glow(p, x, 74, w, h, blush)
        nose = QPainterPath(QPointF(47.2, 69.3))
        nose.quadTo(QPointF(50, 68.4), QPointF(52.8, 69.3))
        nose.quadTo(QPointF(53.6, 69.8), QPointF(52.6, 71))
        nose.lineTo(50.9, 72.6)
        nose.quadTo(QPointF(50, 73.3), QPointF(49.1, 72.6))
        nose.lineTo(47.4, 71)
        nose.quadTo(QPointF(46.4, 69.8), QPointF(47.2, 69.3))
        nose.closeSubpath()
        p.setPen(QPen(NOSE_EDGE, 1.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                      Qt.PenJoinStyle.RoundJoin))
        p.setBrush(NOSE)
        p.drawPath(nose)
        _ellipse(p, 49, 69.8, 1.8, 1, QColor(255, 255, 255, 170))
    line = ROBOT_CYAN if robot else INK
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
            p.setPen(QPen(INK, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                          Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(shape)
    elif smug and not robot:  # a lopsided smirk, up on one side
        _stroke(p, _arc(44, 76.5, 51, 79.5, 57, 74), INK, 1.8)
    elif sad > 0.5 or angry > 0.4:   # a little wobbly frown
        _stroke(p, _arc(45.5, 78.5, 50, 74.8, 54.5, 78.5), line, 1.8)
    else:                     # his resting smile: a soft double curve under the nose
        smile = QPainterPath(QPointF(44.8, 75))
        smile.quadTo(QPointF(47.4, 78.4), QPointF(50, 75.6))
        smile.quadTo(QPointF(52.6, 78.4), QPointF(55.2, 75))
        _stroke(p, smile, line, 1.8)
    if not robot:   # the little line from his nose to his mouth
        _stroke(p, _arc(50, 72.8, 50, 74.2, 50, 75.4), INK, 1.4)

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
    bunnyfit.draw(p, body, "face", ink, hats=not nightcap)
    _paws(p, prop, sad, angry, fur, ink, head_xf.map(head_shape))
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


def bunny_image(height: int, prop: str | None = None, dpr: float = 1.0,
                robot: bool = False, smug: bool = False) -> QImage:
    h = max(1, round(height * dpr))
    w = max(1, round(h * W / H))
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    draw_bunny(p, QRectF(0, 0, w, h), prop, robot=robot, smug=smug)
    p.end()
    img.setDevicePixelRatio(dpr)
    return img


def bunny_pixmap(height: int, prop: str | None = None, dpr: float = 1.0,
                 robot: bool = False, smug: bool = False) -> QPixmap:
    return QPixmap.fromImage(bunny_image(height, prop, dpr, robot=robot, smug=smug))
