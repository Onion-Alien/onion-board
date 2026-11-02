"""Drawing Hoot: his shapes, Bun's outfit moved onto him (_fit), draw_owl(),
owl_image() and sparkle(). Split out of owl.py, which re-exports every name here;
part of the style kit (see __init__.py)."""
from __future__ import annotations

import functools

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QRadialGradient

from . import bunnyfit, hooks
from .owllooks import (BEAK_DARK, BELLY_MARK, CHEEK, EYE, EYE_Y, EYES, H, INK, LOOKS,
                       MOUTH, TEAR, VANILLA, W)


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


# his outline, tufts, wings and face mask never change: built once, kept (only ever
# drawn or clipped to, never changed)
@functools.cache
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


@functools.cache
def _tuft(sx: int, style: str = "point") -> QPainterPath:
    """An ear tuft on his `sx` side (TUFTS): "point", a soft curved point with a little
    notch; "round", a soft round nub; "tall", a long point; "swept", a point swept out
    sideways; "tiny", a little bump. All grow from the same base on his head."""
    def m(x, y):
        return QPointF(50 + sx * (x - 50), y)
    path = QPainterPath(m(70, 27))
    if style == "round":
        path.cubicTo(m(70, 17), m(81, 11), m(85, 18))
        path.cubicTo(m(88, 24), m(86, 35), m(80, 41))
    elif style == "tall":
        path.cubicTo(m(73, 20), m(77, 11), m(78, 2))
        path.cubicTo(m(82, 9), m(85, 15), m(84, 23))
        path.quadTo(m(87.5, 21.5), m(89.5, 18.5))
        path.cubicTo(m(89, 29), m(85.5, 37), m(80, 41))
    elif style == "swept":
        path.cubicTo(m(76, 22), m(84, 16), m(94, 13))
        path.cubicTo(m(92, 20), m(90, 25), m(87, 28))
        path.cubicTo(m(87, 33), m(84, 38), m(80, 41))
    elif style == "tiny":
        path.cubicTo(m(73, 23), m(78, 20), m(82, 19))
        path.cubicTo(m(84, 24), m(84, 34), m(80, 41))
    else:
        path.cubicTo(m(74, 22), m(78, 16), m(79, 8))
        path.cubicTo(m(82, 13), m(84, 18), m(83, 24))
        path.quadTo(m(86.5, 23), m(88, 21))
        path.cubicTo(m(88, 30), m(85, 37), m(80, 41))
    path.closeSubpath()
    return path


def _heart(x: float, y: float, r: float) -> QPainterPath:
    """A little filled heart about `r` wide each side of x, its middle at y."""
    path = QPainterPath(QPointF(x, y + r))
    path.cubicTo(QPointF(x - r * 0.4, y + r * 0.6), QPointF(x - r * 1.2, y),
                 QPointF(x - r * 1.0, y - r * 0.55))
    path.cubicTo(QPointF(x - r * 0.8, y - r * 1.15), QPointF(x - r * 0.1, y - r * 1.05),
                 QPointF(x, y - r * 0.45))
    path.cubicTo(QPointF(x + r * 0.1, y - r * 1.05), QPointF(x + r * 0.8, y - r * 1.15),
                 QPointF(x + r * 1.0, y - r * 0.55))
    path.cubicTo(QPointF(x + r * 1.2, y), QPointF(x + r * 0.4, y + r * 0.6), QPointF(x, y + r))
    path.closeSubpath()
    return path


BELLY_SPOTS = ((42, 84), (50, 84), (58, 84), (46, 92.5), (54, 92.5), (50, 101))


def _belly_marks(p: QPainter, kind: str, col: QColor):
    """The marks on his belly (MARKS), in rows like feathers: thin scallops (plain
    Hoot's), round spots, chunky chevrons, little hearts, or none."""
    for x, y in BELLY_SPOTS:
        if kind == "scallops":
            _stroke(p, _arc(x - 3.6, y, x, y + 3.4, x + 3.6, y), col, 1.7)
            continue
        if kind == "spots":
            shape = QPainterPath()
            shape.addEllipse(QPointF(x, y + 1.5), 2.7, 2.7)
        elif kind == "chevrons":
            shape = QPainterPath(QPointF(x - 4, y - 0.6))
            for px, py in ((x, y + 2.6), (x + 4, y - 0.6), (x + 4, y + 2.2), (x, y + 5.4),
                           (x - 4, y + 2.2)):
                shape.lineTo(QPointF(px, py))
            shape.closeSubpath()
        elif kind == "hearts":
            shape = _heart(x, y + 1.6, 3.0)
        else:
            return
        p.fillPath(shape, col)


@functools.cache
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


@functools.cache
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
# pieces that need their own place: the frog's eyes, the mint, the firework burst and
# the sparkler's lit tip would poke out of his picture (moved in, the sparkler smaller).
# Tall hats stay full size on purpose: an oversized hat on him is the look.
OWN_PLACE = {"frog": (0, -10, 1.0), "mint_sprig": (2, -1, 1.0), "burst": (3, 2, 0.8),
             "sparkler": (25, 3, 0.7)}
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
             outfit: tuple[str, ...] | None = None, kit: dict | None = None,
             wave: float | None = None):
    """Draw Hoot fitted (aspect kept, centred) into `rect`. `look` / `look_y` -1..1
    turn his eyes left / right and up / down: watching. The keywords pose him for
    OwlWidget: `blink` 0..1 closes the eyes, `sad` 0..1 worries the brows and wets
    the eyes, `tufts` droops the ear tufts by that many degrees (negative perks them
    up), `clasp` 0..1 brings the wings together in front (begging), `flap` 0..1 lifts
    them (joy), `plead` 0..1 makes the eyes big and shiny, `tear` 0..1 rolls a tear
    down his cheek (0 = none) and `beak` 0..1 opens his beak (a cheer, a hoot); `wave`
    -1..1 (None: not waving) raises the wing on your left up by his head, swung that
    far one way or the other (hello). His
    feathers are his look's unless `feather` / `dark` are given.
    `outfit`: Bun's outfit pieces to wear (None: the current theme's, (): none).
    `kit`: his look (look(): feathers, eyes, belly marks, tufts, beak, toes; None: the
    current theme's; VANILLA: his own teal)."""
    fit = bunnyfit.outfit() if outfit is None else outfit
    # (look() by hand: `look` here is where his eyes turn)
    kit = {**VANILLA, **(LOOKS.get(hooks.theme_name(), {}) if kit is None else kit)}
    if feather is None:
        feather = kit["feather"]
        if dark is None:
            dark = kit["wing"]
    if dark is None:
        dark = QColor(feather).darker(135)
    feather, dark = QColor(feather), QColor(dark)
    face, belly_col = QColor(kit["face"]), QColor(kit["belly"])
    # the soft shade low on his belly and mask: plain Hoot's warm tan, else a shade of
    # the belly's own colour
    shade = BELLY_MARK if kit["belly"] == VANILLA["belly"] else belly_col.darker(118)
    iris, beak_col = QColor(kit["iris"]), QColor(kit["beak"])
    beak_dark = BEAK_DARK if kit["beak"] == VANILLA["beak"] else beak_col.darker(122)
    toes = QColor(kit["feet"] or kit["beak"])
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
        tuft = _tuft(sx, kit["tufts"])
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
    # belly, with rows of marks (little feather scallops on plain Hoot)
    belly = QPainterPath()
    belly.addEllipse(QRectF(29, 70, 42, 42))
    p.fillPath(belly, belly_col)
    _shade(p, belly, 50, 114, 22, shade, 110)
    _belly_marks(p, kind=kit["marks"], col=QColor(kit["mark"]))
    # feet: three round toes each
    for x in (39, 61):
        for dx, dy in ((-3.8, 0.5), (0, 1.2), (3.8, 0.5)):
            _e(p, x + dx, 113 + dy, 4.8, 6.2, toes, QPen(INK, 1.7))
    # the face: a cream mask, soft-edged, the cheeks blushing
    mask = _face_path()
    p.fillPath(mask, face)
    _shade(p, mask, 50, 78, 22, shade, 90)
    p.save()
    p.setClipPath(mask)
    for x in (22.5, 77.5):
        g = QRadialGradient(QPointF(x, 63.5), 6.5)
        g.setColorAt(0, CHEEK)
        g.setColorAt(0.55, CHEEK)
        g.setColorAt(1, QColor(255, 128, 160, 0))
        p.fillRect(QRectF(x - 7, 56.5, 14, 14), g)
    p.restore()
    # what he wears round his neck goes under the wings, which clasp in front of it
    neck = tuple(n for n in fit if n in bunnyfit.NECK)
    _fit(p, neck, "face", ink)
    # wings: at his sides, clasped in front of the belly, or flung up
    for sx in (-1, 1):
        if sx == -1 and wave is not None:   # waving hello, turned about his shoulder
            p.save()
            p.translate(21, 76)
            p.rotate(148 + 18 * wave)
            p.scale(1.15, 1.12)
            p.translate(0, 19)
            wing = _wing(sx)
            p.setPen(ink)
            p.setBrush(dark)
            p.drawPath(wing)
            _shade(p, wing, -sx * 4, -12, 14, feather, 150)
            p.restore()
            continue
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
        g.setColorAt(0, iris)
        g.setColorAt(1, QColor(iris.red(), iris.green(), iris.blue(), 0))
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
            p.setBrush(face)
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
        _e(p, 50, 67 + 5 * o, 6, 4 * o, beak_dark)
        p.restore()
    p.setPen(bp)
    p.setBrush(beak_col)
    p.drawPath(top)
    p.save()
    p.setClipPath(top)
    _e(p, 52, 64.5 - 2 * o, 6, 7, beak_dark)
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
    _fit(p, tuple(n for n in fit if n not in bunnyfit.NECK), "face", ink, shut=shut)
    p.restore()


def owl_image(height: int, look: float = 0.5) -> QImage:
    h = max(1, height)
    w = max(1, round(h * W / H))
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    draw_owl(p, QRectF(0, 0, w, h), look, outfit=(), kit=VANILLA)   # artwork: plain Hoot
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
