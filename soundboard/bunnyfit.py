"""Bun's outfits: each theme dresses him up a little (a crown for Royal, a cape and
fangs for Vampire, laser eyes for Deep Fried...). Drawn with QPainter on bunny.py's
100 x 120 canvas, in four layers so each piece sits right:

    back   behind his head (a hood, a cape collar)
    under  on his head, under the headphones (a beanie, a headband)
    over   on top of everything on his head (a crown, a hat)
    face   over his face and neck (glasses, a bow tie, a scarf)

`outfit()` picks the current theme's pieces; `draw()` paints one layer of them.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF

from soundboard import theme

# each theme's pieces; a theme that isn't listed is plain Bun (headphones only)
OUTFITS: dict[str, tuple[str, ...]] = {
    "Light": ("bowtie",),
    "Toxic": ("goggles",),
    "Ocean": ("sailor",),
    "Cherry Blossom": ("blossom",),
    "Carbon": ("beanie",),
    "Midnight": ("wizard",),
    "Slate": ("scarf",),
    "Arctic": ("pom_beanie", "scarf"),
    "Paper": ("round_glasses", "bowtie"),
    "Vampire": ("collar", "fangs"),
    "Forest": ("leaves",),
    "Mocha": ("beret",),
    "Sunset": ("shades", "lei"),
    "Royal": ("crown",),
    "Onion": ("onion",),
    "Mint": ("headband",),
    "Synthwave": ("visor",),
    "Vaporwave": ("glasses_3d",),
    "Blood Moon": ("horns",),
    "Lava": ("bandana",),
    "Amber Terminal": ("eyeshade",),
    "Hacker": ("hood", "strings", "shades"),
    "Flashbang": ("aviators",),
    "Barbie": ("bow", "heart_glasses"),
    "Swamp": ("bucket",),
    "Deep Fried": ("laser",),
    "Retro 98": ("pixel_shades",),
    "Comic Sans": ("party", "clown_nose"),
    "Brainrot": ("propeller",),
}

HATS = {"beanie", "pom_beanie", "wizard", "sailor", "beret", "crown", "onion", "horns",
        "bandana", "eyeshade", "bucket", "party", "propeller", "blossom", "leaves",
        "headband", "bow"}

NECK = {"bowtie", "scarf", "lei", "strings"}   # face-layer pieces that sit round his neck

GOLD, GOLD_DARK =QColor("#ffcf40"), QColor("#d99a1e")
WHITE = QColor("#ffffff")
DARK = QColor("#1c1a26")


def outfit(name: str | None = None) -> tuple[str, ...]:
    """Theme `name`'s pieces (default: the current theme)."""
    return OUTFITS.get(name or theme.current_name, ())


def _col(key: str) -> QColor:
    return QColor(theme.T[key])


def _head() -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(QRectF(16, 36, 68, 56))
    return path


def _fill(p: QPainter, path: QPainterPath, fill, ink: QPen | None):
    p.setPen(ink or Qt.PenStyle.NoPen)
    p.setBrush(fill)
    p.drawPath(path)


def _poly(*pts) -> QPainterPath:
    path = QPainterPath()
    path.addPolygon(QPolygonF([QPointF(x, y) for x, y in pts]))
    path.closeSubpath()
    return path


def _star(p: QPainter, x, y, r, col: QColor):
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        k = r if i % 2 == 0 else r * 0.45
        pts.append((x + k * math.cos(a), y + k * math.sin(a)))
    _fill(p, _poly(*pts), col, None)


def _flower(p: QPainter, x, y, r, petal: QColor, middle: QColor, ink: QPen | None = None):
    for i in range(5):
        a = i * 2 * math.pi / 5 - math.pi / 2
        p.setPen(ink or Qt.PenStyle.NoPen)
        p.setBrush(petal)
        p.drawEllipse(QPointF(x + r * 0.62 * math.cos(a), y + r * 0.62 * math.sin(a)),
                      r * 0.5, r * 0.5)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(middle)
    p.drawEllipse(QPointF(x, y), r * 0.32, r * 0.32)


# ---------------------------------------------------------------- back
def _hood(p, ink):
    col = QColor("#23262e")
    hood = QPainterPath()
    hood.addEllipse(QRectF(9, 28, 82, 74))
    _fill(p, hood, col, ink)
    inner = QPainterPath()
    inner.addEllipse(QRectF(14, 33, 72, 64))
    _fill(p, inner, col.darker(140), None)


def _collar(p, ink):
    out, lining = QColor("#1b1324"), QColor("#b3123a")
    for sx in (1, -1):
        def m(x, y, sx=sx):
            return (50 + sx * (x - 50), y)
        wing = _poly(m(42, 94), m(0, 34), m(8, 58), m(-4, 60), m(10, 78), m(22, 100))
        _fill(p, wing, out, ink)
        lin = _poly(m(40, 91), m(4, 41), m(11, 60), m(2, 62), m(13, 77), m(24, 96))
        _fill(p, lin, lining, None)


# ---------------------------------------------------------------- under (on the head)
def _beanie(p, ink, pom=False):
    col = _col("accent2")
    dome = QPainterPath(QPointF(20, 52))       # tall enough to show over the band
    dome.cubicTo(QPointF(18, 6), QPointF(82, 6), QPointF(80, 52))
    dome.closeSubpath()
    _fill(p, dome, col, ink)
    p.save()
    p.setClipPath(dome)
    p.setPen(QPen(col.darker(118), 2.2))
    for x in range(24, 80, 7):
        p.drawLine(QPointF(x, 14), QPointF(x, 50))
    p.restore()
    p.setPen(ink)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(dome)
    cuff = QPainterPath()
    cuff.addRoundedRect(QRectF(17, 44, 66, 11), 5.5, 5.5)
    _fill(p, cuff, col.darker(112), ink)
    if pom:
        _fill(p, _circle(50, 14, 7), WHITE, ink)


def _circle(x, y, r) -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(QPointF(x, y), r, r)
    return path


def _headband(p, ink):
    col = _col("accent2")
    p.save()
    p.setClipPath(_head())
    band = QPainterPath()
    band.addRect(QRectF(10, 43, 80, 8))
    _fill(p, band, col, None)
    p.setPen(QPen(WHITE, 1.6))
    p.drawLine(QPointF(10, 47), QPointF(90, 47))
    p.restore()
    p.setPen(ink)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QRectF(16, 36, 68, 56))


def _bandana(p, ink):
    col = QColor("#e8432b")
    p.save()
    p.setClipPath(_head())
    top = QPainterPath()
    top.addRect(QRectF(10, 30, 80, 20))
    _fill(p, top, col, None)
    p.setBrush(WHITE)
    for x, y in ((28, 44), (40, 40), (52, 44), (64, 40), (74, 46), (34, 48), (58, 48)):
        p.drawEllipse(QPointF(x, y), 1.4, 1.4)
    p.restore()
    edge = QPainterPath(QPointF(18, 52))
    edge.quadTo(QPointF(50, 46), QPointF(82, 52))
    p.setPen(QPen(col.darker(130), 2.2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(edge)
    p.setPen(ink)
    p.drawEllipse(QRectF(16, 36, 68, 56))
    # the knot and its two tails, out on his left
    _fill(p, _circle(84, 50, 3.5), col, ink)
    _fill(p, _poly((86, 49), (96, 42), (95, 50)), col, ink)
    _fill(p, _poly((86, 52), (97, 55), (92, 60)), col, ink)


def _eyeshade(p, ink):
    band = QColor("#2e2a22")
    p.save()
    p.setClipPath(_head())
    strap = QPainterPath()
    strap.addRect(QRectF(10, 44, 80, 5))
    _fill(p, strap, band, None)
    p.restore()
    brim = QPainterPath(QPointF(19, 47))
    brim.cubicTo(QPointF(24, 64), QPointF(76, 64), QPointF(81, 47))
    brim.quadTo(QPointF(50, 41), QPointF(19, 47))
    glass = QColor("#3cc46a")
    glass.setAlpha(170)
    _fill(p, brim, glass, QPen(band, 2))
    p.setPen(QPen(QColor(255, 255, 255, 140), 1.4))
    p.drawLine(QPointF(30, 50), QPointF(44, 52))


# ---------------------------------------------------------------- over (hats)
def _wizard(p, ink):
    col = _col("accent2")
    cone = QPainterPath(QPointF(28, 42))
    cone.cubicTo(QPointF(38, 30), QPointF(52, 6), QPointF(70, -4))
    cone.cubicTo(QPointF(64, 10), QPointF(66, 28), QPointF(72, 42))
    cone.closeSubpath()
    _fill(p, cone, col, ink)
    brim = QPainterPath()
    brim.addEllipse(QRectF(16, 37, 68, 11))
    _fill(p, brim, col.darker(115), ink)
    for x, y, r in ((50, 26, 4), (60, 12, 3), (44, 36, 2.5)):
        _star(p, x, y, r, GOLD)


def _sailor(p, ink):
    top = QPainterPath(QPointF(30, 40))
    top.cubicTo(QPointF(30, 22), QPointF(70, 22), QPointF(70, 40))
    top.closeSubpath()
    _fill(p, top, WHITE, ink)
    band = QPainterPath()
    band.addRoundedRect(QRectF(29, 34, 42, 6), 2, 2)
    _fill(p, band, QColor("#1f4fb8"), None)
    brim = QPainterPath()
    brim.addEllipse(QRectF(24, 38, 52, 8))
    _fill(p, brim, WHITE, ink)
    _fill(p, _circle(50, 25, 3), QColor("#e8432b"), None)


def _beret(p, ink):
    col = QColor("#7a3b2e")
    p.save()
    p.translate(44, 37)
    p.rotate(-12)
    body = QPainterPath()
    body.addEllipse(QRectF(-27, -10, 54, 18))
    _fill(p, body, col, ink)
    p.setPen(QPen(col.darker(130), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(0, -10), QPointF(1, -15))
    p.restore()


def _crown(p, ink):
    crown = _poly((30, 42), (27, 18), (38, 30), (44, 12), (50, 28), (56, 12), (62, 30),
                  (73, 18), (70, 42))
    grad = QLinearGradient(0, 12, 0, 42)
    grad.setColorAt(0, GOLD)
    grad.setColorAt(1, GOLD_DARK)
    _fill(p, crown, grad, ink)
    _fill(p, _circle(50, 36, 3.2), QColor("#e8274b"), None)
    _fill(p, _circle(39, 37, 2.4), QColor("#2f7bff"), None)
    _fill(p, _circle(61, 37, 2.4), QColor("#2f7bff"), None)
    for x, y in ((27, 18), (44, 12), (56, 12), (73, 18)):
        _fill(p, _circle(x, y, 2.4), WHITE, None)


def _horns(p, ink):
    col = QColor("#c4162e")
    for sx in (1, -1):
        def m(x, y, sx=sx):
            return QPointF(50 + sx * (x - 50), y)
        horn = QPainterPath(m(30, 44))
        horn.cubicTo(m(24, 32), m(20, 24), m(14, 14))
        horn.cubicTo(m(28, 20), m(38, 30), m(40, 41))
        horn.closeSubpath()
        _fill(p, horn, col, ink)


def _blossom(p, ink):
    petal, middle = QColor("#ffc1d3"), QColor("#ffe27a")
    edge = QPen(QColor("#e88aa6"), 0.8)
    _flower(p, 70, 40, 10, petal, middle, edge)
    _flower(p, 80, 50, 7, petal, middle, edge)
    _flower(p, 61, 36, 6, QColor("#ffd9e4"), middle, edge)


def _leaves(p, ink):
    green, dark = QColor("#4caf50"), QColor("#2f7d32")
    band = QPainterPath(QPointF(20, 52))
    band.cubicTo(QPointF(20, 30), QPointF(80, 30), QPointF(80, 52))
    p.setPen(QPen(QColor("#6d4c2f"), 2.2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(band)
    for i in range(9):
        t = i / 8
        pt = band.pointAtPercent(t)
        a = band.angleAtPercent(t)
        p.save()
        p.translate(pt)
        p.rotate(-a + (35 if i % 2 else -35))
        leaf = QPainterPath(QPointF(0, 0))
        leaf.quadTo(QPointF(5, -5), QPointF(11, 0))
        leaf.quadTo(QPointF(5, 5), QPointF(0, 0))
        _fill(p, leaf, green if i % 2 else dark, None)
        p.restore()


def _onion(p, ink):
    col = QColor("#b05cc8")
    bulb = QPainterPath(QPointF(50, 10))
    bulb.cubicTo(QPointF(56, 18), QPointF(70, 24), QPointF(68, 34))
    bulb.cubicTo(QPointF(66, 42), QPointF(34, 42), QPointF(32, 34))
    bulb.cubicTo(QPointF(30, 24), QPointF(44, 18), QPointF(50, 10))
    _fill(p, bulb, col, ink)
    p.setPen(QPen(col.lighter(135), 1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    for dx in (-8, 0, 8):
        line = QPainterPath(QPointF(50 + dx * 0.3, 15))
        line.quadTo(QPointF(50 + dx * 1.6, 28), QPointF(50 + dx, 40))
        p.drawPath(line)
    p.setPen(QPen(QColor("#4caf50"), 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(50, 11), QPointF(46, 1))
    p.drawLine(QPointF(50, 11), QPointF(55, 2))


def _bucket(p, ink):
    col = QColor("#6b7a3a")
    crown = QPainterPath(QPointF(32, 42))
    crown.lineTo(35, 24)
    crown.quadTo(QPointF(50, 18), QPointF(65, 24))
    crown.lineTo(68, 42)
    crown.closeSubpath()
    _fill(p, crown, col, ink)
    brim = QPainterPath(QPointF(20, 46))
    brim.quadTo(QPointF(50, 34), QPointF(80, 46))
    brim.quadTo(QPointF(50, 42), QPointF(20, 46))
    p.setPen(QPen(INK_COL, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    p.setBrush(col.darker(115))
    p.drawPath(brim)
    p.setPen(QPen(col.darker(140), 1.2, Qt.PenStyle.DashLine))
    p.drawLine(QPointF(34, 37), QPointF(66, 37))


def _party(p, ink):
    col = _col("accent2")
    cone = _poly((36, 40), (60, 2), (66, 38))
    _fill(p, cone, col, ink)
    p.save()
    p.setClipPath(cone)
    p.setPen(QPen(WHITE, 3))
    for y in (12, 22, 32):
        p.drawLine(QPointF(30, y + 6), QPointF(70, y - 6))
    p.restore()
    p.setPen(ink)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(cone)
    _flower(p, 60, 2, 6, GOLD, QColor("#ff5d8f"))


def _propeller(p, ink):
    dome = QPainterPath(QPointF(30, 44))
    dome.cubicTo(QPointF(30, 24), QPointF(70, 24), QPointF(70, 44))
    dome.closeSubpath()
    p.save()
    p.setClipPath(dome)
    for i, c in enumerate(("#e8432b", "#ffcf40", "#2f7bff", "#3cc46a")):
        _fill(p, _poly((50, 20), (20 + i * 15, 46), (35 + i * 15, 46)), QColor(c), None)
    p.restore()
    p.setPen(ink)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(dome)
    p.setPen(QPen(INK_COL, 2))
    p.drawLine(QPointF(50, 29), QPointF(50, 20))
    for sx in (1, -1):
        blade = QPainterPath()
        blade.addEllipse(QRectF(50 + (2 if sx > 0 else -16), 16, 14, 5))
        _fill(p, blade, QColor("#ff5d8f" if sx > 0 else "#2fd3ff"), ink)
    _fill(p, _circle(50, 19, 2.4), GOLD, None)


def _bow(p, ink):
    col = QColor("#ff4fa3")
    _fill(p, _poly((66, 40), (54, 30), (56, 46)), col, ink)
    _fill(p, _poly((66, 40), (78, 30), (77, 47)), col, ink)
    _fill(p, _circle(66, 40, 3.6), col.darker(115), ink)


# ---------------------------------------------------------------- face
def _lenses(p, ink, fill, shape="rect", frame: QColor | None = None):
    frame = frame or DARK
    pen = QPen(frame, 2)
    p.setPen(pen)
    p.drawLine(QPointF(46, 60), QPointF(54, 60))          # bridge
    p.drawLine(QPointF(31, 59), QPointF(20, 60))          # arms to the headphones
    p.drawLine(QPointF(69, 59), QPointF(80, 60))
    for i, x in enumerate((39, 61)):
        if shape == "round":
            path = _circle(x, 62, 7.5)
        elif shape == "aviator":
            path = QPainterPath(QPointF(x - 8, 56))
            path.lineTo(x + 8, 56)
            path.cubicTo(QPointF(x + 9, 66), QPointF(x + 3, 70), QPointF(x, 70))
            path.cubicTo(QPointF(x - 5, 70), QPointF(x - 9, 64), QPointF(x - 8, 56))
        elif shape == "heart":
            path = QPainterPath(QPointF(x, 70))
            path.cubicTo(QPointF(x - 13, 61), QPointF(x - 7, 50), QPointF(x, 57))
            path.cubicTo(QPointF(x + 7, 50), QPointF(x + 13, 61), QPointF(x, 70))
        else:
            path = QPainterPath()
            path.addRoundedRect(QRectF(x - 8.5, 55.5, 17, 12), 4, 4)
        lens = fill[i] if isinstance(fill, tuple) else fill
        _fill(p, path, lens, pen)
        if shape != "round":                               # a glint
            p.setPen(QPen(QColor(255, 255, 255, 150), 1.6, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(x - 5, 63), QPointF(x - 1, 58))


def _laser(p, ink):
    for x, sx in ((39, -1), (61, 1)):
        grad = QLinearGradient(x, 62, x + sx * 60, 54)
        grad.setColorAt(0, QColor(255, 40, 40, 230))
        grad.setColorAt(1, QColor(255, 40, 40, 0))
        beam = _poly((x, 59), (x + sx * 70, 44), (x + sx * 70, 64), (x, 65))
        _fill(p, beam, grad, None)
        glow = QColor(255, 60, 60, 120)
        _fill(p, _circle(x, 62, 9), glow, None)
        _fill(p, _circle(x, 62, 4.5), QColor("#ff2b2b"), None)
        _fill(p, _circle(x, 62, 2), WHITE, None)


def _pixel_shades(p, ink):
    k = 2.6
    rows = ("XXXXXXXXXXXXXXXXXX",
            " XWXXXXX  XWXXXXX ",
            " XXWXXXX  XXWXXXX ",
            "  XXXXX    XXXXX  ")
    x0, y0 = 50 - 9 * k, 56
    for r, row in enumerate(rows):
        for c, ch in enumerate(row):
            if ch != " ":
                _fill(p, _rect(x0 + c * k, y0 + r * k, k + 0.2, k + 0.2),
                      WHITE if ch == "W" else DARK, None)


def _rect(x, y, w, h) -> QPainterPath:
    path = QPainterPath()
    path.addRect(QRectF(x, y, w, h))
    return path


def _visor(p, ink):
    grad = QLinearGradient(26, 0, 74, 0)
    grad.setColorAt(0, QColor("#ff2fb4"))
    grad.setColorAt(1, QColor("#2fe6ff"))
    band = QPainterPath()
    band.addRoundedRect(QRectF(24, 55, 52, 13), 6.5, 6.5)
    _fill(p, band, grad, QPen(DARK, 2))
    p.setPen(QPen(QColor(255, 255, 255, 170), 1.5))
    p.drawLine(QPointF(30, 59), QPointF(70, 59))
    p.setPen(QPen(DARK, 2))
    p.drawLine(QPointF(24, 61), QPointF(20, 61))
    p.drawLine(QPointF(76, 61), QPointF(80, 61))


def _goggles(p, ink):
    strap = QColor("#2e3a2e")
    p.setPen(QPen(strap, 4))
    p.drawLine(QPointF(20, 60), QPointF(80, 60))
    glass = QColor(theme.T["accent"])
    glass.setAlpha(120)
    for x in (39, 61):
        _fill(p, _circle(x, 62, 9.5), QColor("#3c4a3c"), ink)
        _fill(p, _circle(x, 62, 7), glass, None)
        p.setPen(QPen(QColor(255, 255, 255, 170), 1.6, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(x - 4, 61), QPointF(x - 1, 57.5))


def _strings(p, ink):
    """The hood's drawstrings, hanging over his chest."""
    p.setPen(QPen(QColor("#d8dce4"), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for x, dx in ((42, -1), (58, 1)):
        p.drawLine(QPointF(x, 90), QPointF(x + dx, 104))
        _fill(p, _rect(x + dx - 1.2, 104, 2.4, 4), QColor("#9aa0b4"), None)
        p.setPen(QPen(QColor("#d8dce4"), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))


def _fangs(p, ink):
    for x in (47, 53):
        _fill(p, _poly((x - 2, 77), (x + 2, 77), (x, 82)), WHITE, QPen(INK_COL, 1))


def _clown_nose(p, ink):
    _fill(p, _circle(50, 70.5, 5.5), QColor("#ff2b3a"), QPen(QColor("#a3101d"), 1.2))
    _fill(p, _circle(48.3, 68.8, 1.6), QColor(255, 255, 255, 200), None)


def _bowtie(p, ink):
    col = _col("accent2")
    _fill(p, _poly((50, 93), (39, 87), (39, 99)), col, ink)
    _fill(p, _poly((50, 93), (61, 87), (61, 99)), col, ink)
    knot = QPainterPath()
    knot.addRoundedRect(QRectF(46.5, 89.5, 7, 7), 2, 2)
    _fill(p, knot, col.darker(120), ink)


def _scarf(p, ink):
    col = _col("accent")
    wrap = QPainterPath()
    wrap.addRoundedRect(QRectF(27, 86, 46, 10), 5, 5)
    _fill(p, wrap, col, ink)
    tail = _poly((58, 92), (68, 92), (70, 111), (60, 112))
    _fill(p, tail, col.darker(110), ink)
    p.setPen(QPen(col.lighter(140), 2))
    for y in (103, 108):
        p.drawLine(QPointF(60.5, y), QPointF(69, y))


def _lei(p, ink):
    for i in range(9):
        t = i / 8
        x = 28 + 44 * t
        y = 89 + 6 * math.sin(math.pi * t)
        cols = ("#ff5d8f", "#ffcf40", "#ff8a3d")
        _flower(p, x, y, 6.5, QColor(cols[i % 3]), WHITE)


INK_COL = QColor("#2b2340")

PIECES = {
    "hood": ("back", _hood),
    "collar": ("back", _collar),
    "beanie": ("under", _beanie),
    "pom_beanie": ("under", lambda p, ink: _beanie(p, ink, pom=True)),
    "headband": ("under", _headband),
    "bandana": ("under", _bandana),
    "eyeshade": ("under", _eyeshade),
    "wizard": ("over", _wizard),
    "sailor": ("over", _sailor),
    "beret": ("over", _beret),
    "crown": ("over", _crown),
    "horns": ("over", _horns),
    "blossom": ("over", _blossom),
    "leaves": ("over", _leaves),
    "onion": ("over", _onion),
    "bucket": ("over", _bucket),
    "party": ("over", _party),
    "propeller": ("over", _propeller),
    "bow": ("over", _bow),
    "shades": ("face", lambda p, ink: _lenses(p, ink, DARK)),
    "aviators": ("face", lambda p, ink: _lenses(p, ink, QColor("#2a2d3a"), "aviator",
                                                 GOLD_DARK)),
    "round_glasses": ("face", lambda p, ink: _lenses(p, ink, QColor(200, 230, 255, 60),
                                                      "round", QColor("#5a3a24"))),
    "heart_glasses": ("face", lambda p, ink: _lenses(p, ink, QColor(255, 79, 163, 200),
                                                      "heart", QColor("#c2186b"))),
    "glasses_3d": ("face", lambda p, ink: _lenses(
        p, ink, (QColor(255, 40, 60, 170), QColor(40, 220, 255, 170)), "rect", WHITE)),
    "pixel_shades": ("face", _pixel_shades),
    "visor": ("face", _visor),
    "goggles": ("face", _goggles),
    "laser": ("face", _laser),
    "strings": ("face", _strings),
    "fangs": ("face", _fangs),
    "clown_nose": ("face", _clown_nose),
    "bowtie": ("face", _bowtie),
    "scarf": ("face", _scarf),
    "lei": ("face", _lei),
}


def draw(p: QPainter, pieces: tuple[str, ...], layer: str, ink: QPen,
         hats: bool = True, shut: bool = False, neck: bool | None = None) -> None:
    """Paint the `layer` part of `pieces` (bunny.py calls this between its own layers).
    `hats=False` leaves out anything on his head (his nightcap is on); `shut`: his eyes
    are closed, so no laser eyes. `neck` True / False paints only the pieces round his
    neck / only the rest (ui/owl.py places the two apart on Hoot)."""
    for name in pieces:
        where, fn = PIECES.get(name, ("", None))
        if (where == layer and fn and (hats or name not in HATS)
                and not (shut and name == "laser")
                and (neck is None or neck == (name in NECK))):
            p.save()
            fn(p, ink)
            p.restore()
