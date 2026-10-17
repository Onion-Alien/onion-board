"""Bun's outfits: each theme dresses him up a little (a crown for Royal, a cape and
fangs for Vampire, laser eyes for Deep Fried...). Drawn with QPainter on bunny.py's
100 x 120 canvas, in four layers so each piece sits right:

    behind behind everything, even his ears (a moon)
    back   behind his head (a hood, a cape collar)
    under  on his head, under the headphones (a beanie, a frog hat)
    over   on top of everything on his head (a crown, a hat)
    face   over his face and neck (glasses, a bow tie, a scarf)

`outfit()` picks the current theme's pieces; `draw()` paints one layer of them. Hoot
wears them too (owl.py). Part of the style kit (see __init__.py).
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QRadialGradient,
)

from . import hooks

# each theme's pieces; a theme that isn't listed is plain Bun (headphones only)
OUTFITS: dict[str, tuple[str, ...]] = {
    "Light": ("bowtie",),
    "Lilac": ("flower_crown",),
    "Toxic": ("hazmat", "badge"),
    "Ocean": ("captain",),
    "Cherry Blossom": ("blossom",),
    "Carbon": ("snapback",),
    "Midnight": ("wizard",),
    "Slate": ("sweater", "turtleneck", "readers"),
    "Arctic": ("pom_beanie", "scarf"),
    "Paper": ("round_glasses", "bowtie"),
    "Vampire": ("collar", "fangs"),
    "Forest": ("leaves",),
    "Mocha": ("beret",),
    "Sunset": ("shades", "lei"),
    "Royal": ("crown",),
    "Onion": ("onion",),
    "Mint": ("mint_sprig",),
    "Synthwave": ("visor",),
    "Vaporwave": ("glasses_3d",),
    "Blood Moon": ("moon", "horns"),
    "Lava": ("bandana",),
    "Amber Terminal": ("eyeshade", "pencil"),
    "Hacker": ("hood", "strings", "shades"),
    "Flashbang": ("spirals", "dizzy"),
    "Barbie": ("bow", "heart_glasses"),
    "Swamp": ("frog",),
    "Deep Fried": ("laser",),
    "Retro 98": ("pixel_shades",),
    "Comic Sans": ("party", "clown_nose"),
    "Brainrot": ("propeller",),
}

HATS = {"pom_beanie", "wizard", "captain", "beret", "crown", "onion", "horns", "bandana",
        "eyeshade", "pencil", "frog", "snapback", "party", "propeller", "blossom", "leaves",
        "flower_crown", "mint_sprig", "bow", "dizzy"}

# glasses and visors: off while he sleeps under the nightcap
EYEWEAR = {"shades", "round_glasses", "heart_glasses", "glasses_3d",
           "pixel_shades", "visor", "readers", "spirals"}
# the ones you can't see his eyes through: bunny.py leaves out the lids and tears they'd
# hide and lifts his brows clear of them
HIDE_EYES = {"shades", "pixel_shades", "visor", "spirals"}

NECK = {"bowtie", "scarf", "lei", "strings", "turtleneck", "badge"}   # face-layer pieces
                                                                     # round his neck

GOLD, GOLD_DARK =QColor("#ffcf40"), QColor("#d99a1e")
WHITE = QColor("#ffffff")
DARK = QColor("#1c1a26")


def outfit(name: str | None = None) -> tuple[str, ...]:
    """Theme `name`'s pieces (default: the current theme)."""
    return OUTFITS.get(name or hooks.theme_name(), ())


def _col(key: str) -> QColor:
    return QColor(hooks.palette()[key])


# each theme's own Bun: his fur, which ear flops ("up": neither, "left" / "right": the
# viewer's, "both") and little extras ("chomp": a bite out of an ear, "earring", "shiner",
# "bandaid", "freckles"); his tail (TAILS), the colour low in his eyes ("iris"), inside his
# ears ("inner") and his nose; fur markings ("pattern": "patch" over one eye, "spots",
# a "mask" round both eyes, all in the "marks" colour), his tummy patch ("belly", None: a
# shade of his fur) and the pad prints under his feet ("pads", None: none). A theme that
# isn't listed is plain Bun: VANILLA.
TAILS = ("round", "fluffy", "long", "tuft", "heart")
PATTERNS = ("patch", "spots", "mask")
VANILLA = {"fur": "#fdf8f1", "ears": "right", "extras": (), "tail": "round",
           "iris": "#8a5cc7", "inner": "#ffb3c7", "nose": "#ff8fae", "pattern": (),
           "marks": "#a57a52", "belly": None, "pads": None}
LOOKS: dict[str, dict] = {
    "Light": {"ears": "up", "tail": "fluffy", "iris": "#3d8fe0", "pads": "#ffb3c7"},
    "Lilac": {"fur": "#e9e0f7", "ears": "left", "tail": "fluffy", "iris": "#a46be8",
              "inner": "#d6b4f2", "nose": "#c58ad9", "belly": "#f8f3fe", "pads": "#d6b4f2"},
    "Toxic": {"fur": "#e2f2d3", "extras": ("chomp", "shiner"), "tail": "tuft",
              "iris": "#6cc622", "inner": "#c2ea86", "nose": "#86c84a", "pattern": ("spots",),
              "marks": "#9fd46a", "pads": "#c2ea86"},
    "Ocean": {"ears": "up", "extras": ("earring",), "iris": "#1aa0c8", "inner": "#ffc0ae",
              "nose": "#ff8a73", "pattern": ("patch",), "marks": "#8fbcd6", "pads": "#ffc0ae"},
    "Cherry Blossom": {"fur": "#fde3ec", "ears": "both", "tail": "heart", "iris": "#e0608f",
                       "inner": "#ff9fbf", "nose": "#ff7aa5", "belly": "#fff4f8",
                       "pads": "#ff9fbf"},
    "Carbon": {"fur": "#5c5964", "extras": ("earring", "bandaid"), "tail": "long",
               "iris": "#ff9a3c", "inner": "#c9a3ad", "nose": "#2b2730", "pattern": ("patch",),
               "marks": "#e6e2ea", "pads": "#c9a3ad"},
    "Midnight": {"fur": "#3e4366", "ears": "up", "tail": "fluffy", "iris": "#ffd66b",
                 "inner": "#9ea6e2", "nose": "#b9a4f0", "pattern": ("spots",),
                 "marks": "#6c74aa", "belly": "#5b6290", "pads": "#9ea6e2"},
    "Slate": {"fur": "#e0e1e6", "iris": "#5f7da3", "inner": "#e3b7bf", "nose": "#c98a96",
              "pattern": ("mask",), "marks": "#8d919e", "pads": "#e3b7bf"},
    "Arctic": {"ears": "up", "extras": ("freckles",), "tail": "fluffy", "iris": "#4cc2ee",
               "inner": "#ffd0dc", "pads": "#ffd0dc"},
    "Paper": {"fur": "#f6edda", "extras": ("freckles",), "iris": "#7a5a34", "inner": "#f2c6b2",
              "nose": "#d98f7a", "pattern": ("spots",), "marks": "#3a3550", "pads": "#f2c6b2"},
    "Vampire": {"fur": "#ece7f1", "ears": "left", "extras": ("chomp",), "tail": "tuft",
                "iris": "#d4213d", "inner": "#c25a7a", "nose": "#8f2a4a", "pattern": ("mask",),
                "marks": "#3a2d47", "belly": "#d9cfe3", "pads": "#c25a7a"},
    "Forest": {"fur": "#a57a52", "ears": "up", "tail": "long", "iris": "#5fae3c",
               "inner": "#f0bea6", "nose": "#5a3a28", "pattern": ("spots",), "marks": "#e9d6ba",
               "belly": "#e9d6ba", "pads": "#f0bea6"},
    "Mocha": {"fur": "#6f4630", "ears": "both", "iris": "#e3a24e", "inner": "#e8b0a0",
              "nose": "#3a2218", "pattern": ("patch",), "marks": "#f3e3cc", "belly": "#f3e3cc",
              "pads": "#e8b0a0"},
    "Sunset": {"fur": "#fcdcc4", "ears": "up", "extras": ("earring",), "tail": "fluffy",
               "iris": "#ff7a3c", "inner": "#ffb38a", "nose": "#ff6e6e", "belly": "#fff1e4",
               "pads": "#ffb38a"},
    "Royal": {"ears": "up", "extras": ("earring",), "iris": "#d9a521", "inner": "#c9a3f0",
              "nose": "#b583e8", "pads": "#c9a3f0"},
    "Onion": {"iris": "#9b5de5", "inner": "#e2b6f0", "nose": "#c47ad9", "pads": "#e2b6f0"},
    "Mint": {"fur": "#dbf3e7", "ears": "left", "tail": "fluffy", "iris": "#22b585",
             "inner": "#a8e6c8", "nose": "#ff9fb3", "pattern": ("spots",), "marks": "#5a3a28",
             "pads": "#a8e6c8"},
    "Synthwave": {"fur": "#f6d9ef", "ears": "up", "extras": ("earring",), "tail": "tuft",
                  "iris": "#ff3fb4", "inner": "#ff7ad9", "nose": "#ff4fa0", "pattern": ("mask",),
                  "marks": "#9b5de5", "pads": "#6ee7ff"},
    "Vaporwave": {"fur": "#f2dcf5", "tail": "heart", "iris": "#3fcbdc", "inner": "#b8a4ff",
                  "nose": "#ff9fe0", "belly": "#c9f2f7", "pads": "#b8a4ff"},
    "Blood Moon": {"fur": "#433b4c", "ears": "left", "extras": ("chomp", "shiner"),
                   "tail": "tuft", "iris": "#ff3b2f", "inner": "#c4505a", "nose": "#241d29",
                   "pattern": ("spots",), "marks": "#7a4652", "pads": "#c4505a"},
    "Lava": {"fur": "#f3cdae", "extras": ("bandaid", "chomp"), "tail": "tuft", "iris": "#ff5a1f",
             "inner": "#ff9a6b", "nose": "#e0482a", "pattern": ("patch",), "marks": "#3d2c2c",
             "pads": "#ff9a6b"},
    "Amber Terminal": {"fur": "#f3e7c8", "iris": "#f0a000", "inner": "#f0c890",
                       "nose": "#d98a3a", "pattern": ("mask",), "marks": "#c99a52",
                       "pads": "#f0c890"},
    "Hacker": {"fur": "#45424d", "ears": "up", "extras": ("earring", "chomp"), "tail": "long",
               "iris": "#39ff7a", "inner": "#7fbf8f", "nose": "#1e1c22", "pads": "#7fbf8f"},
    "Flashbang": {"ears": "both", "extras": ("shiner", "bandaid"), "tail": "fluffy",
                  "iris": "#f5c400", "pads": "#ffb3c7"},
    "Barbie": {"fur": "#fcd8e8", "ears": "up", "extras": ("earring",), "tail": "heart",
               "iris": "#ff4fa3", "inner": "#ff8cc6", "nose": "#ff4fa3", "belly": "#fff0f7",
               "pads": "#ff8cc6"},
    "Swamp": {"fur": "#68703f", "ears": "both", "tail": "long", "iris": "#e8d84a",
              "inner": "#c8b878", "nose": "#3e4424", "pattern": ("spots",), "marks": "#97a35a",
              "belly": "#c9cf8f", "pads": "#c8b878"},
    "Deep Fried": {"fur": "#f1d394", "extras": ("shiner", "bandaid", "chomp"), "tail": "tuft",
                   "iris": "#ff2a00", "inner": "#ff9a3a", "nose": "#c83a14",
                   "pattern": ("spots",), "marks": "#c8862a", "pads": "#ff9a3a"},
    "Retro 98": {"fur": "#d8d4cc", "iris": "#1a2ab0", "inner": "#e0b0c0", "nose": "#c08090",
                 "pattern": ("patch",), "marks": "#8a8a8a", "pads": "#e0b0c0"},
    "Comic Sans": {"ears": "both", "extras": ("freckles",), "tail": "fluffy",
                   "iris": "#2f80ff", "pattern": ("spots",), "marks": "#86b8ff",
                   "pads": "#ffb3c7"},
    "Brainrot": {"ears": "left", "extras": ("freckles", "bandaid"), "tail": "long",
                 "iris": "#8fe000", "inner": "#ff9fe0", "nose": "#7a5cff", "pattern": ("patch",),
                 "marks": "#9fd8ff", "pads": "#ff9fe0"},
}


def look(name: str | None = None) -> dict:
    """Theme `name`'s Bun (default: the current theme's): VANILLA with its changes."""
    return {**VANILLA, **LOOKS.get(name or hooks.theme_name(), {})}


def sleeve(pieces: tuple[str, ...]) -> QColor | None:
    """The colour of his little arms when `pieces` dress them (a sweater has sleeves),
    else None: bare fur."""
    return _col("accent2") if "sweater" in pieces else None


# Bun's shape on the 100 x 120 canvas: bunny.py draws him from these, and the pieces
# that sit on him clip to them, so his outline and theirs stay one
EYES = (35.5, 64.5)   # his eyes' centres (x), on EYE_Y
EYE_Y = 64.0


def head_path() -> QPainterPath:
    """His head: round on top, a little wider and softer at the cheeks (about the
    68 x 56 oval centred at 50, 64 the pieces are placed on)."""
    path = QPainterPath(QPointF(50, 36.5))
    path.cubicTo(QPointF(71.5, 36.5), QPointF(85.5, 47), QPointF(85.5, 66))
    path.cubicTo(QPointF(85.5, 84), QPointF(69, 92), QPointF(50, 92))
    path.cubicTo(QPointF(31, 92), QPointF(14.5, 84), QPointF(14.5, 66))
    path.cubicTo(QPointF(14.5, 47), QPointF(28.5, 36.5), QPointF(50, 36.5))
    path.closeSubpath()
    return path


def body_path() -> QPainterPath:
    """His small sitting body under the big head, round at the haunches."""
    path = QPainterPath(QPointF(50, 84))
    path.cubicTo(QPointF(60, 84), QPointF(65, 89), QPointF(67, 96))
    path.cubicTo(QPointF(75, 99), QPointF(77.5, 110), QPointF(71, 117.5))
    path.lineTo(29, 117.5)
    path.cubicTo(QPointF(22.5, 110), QPointF(25, 99), QPointF(33, 96))
    path.cubicTo(QPointF(35, 89), QPointF(40, 84), QPointF(50, 84))
    path.closeSubpath()
    return path


def _head() -> QPainterPath:
    return head_path()


def _fill(p: QPainter, path: QPainterPath, fill, ink: QPen | None):
    p.setPen(ink or Qt.PenStyle.NoPen)
    p.setBrush(fill)
    p.drawPath(path)


def _poly(*pts) -> QPainterPath:
    path = QPainterPath()
    path.addPolygon(QPolygonF([QPointF(x, y) for x, y in pts]))
    path.closeSubpath()
    return path


def _star(p: QPainter, x, y, r, col: QColor, ink: QPen | None = None):
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        k = r if i % 2 == 0 else r * 0.45
        pts.append((x + k * math.cos(a), y + k * math.sin(a)))
    _fill(p, _poly(*pts), col, ink)


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
def _hood(p, ink, col: QColor, rim: QColor | None = None):
    hood = QPainterPath()
    hood.addEllipse(QRectF(9, 28, 82, 74))
    _fill(p, hood, col, ink)
    if rim is not None:                     # so a dark hood doesn't vanish on a dark theme
        p.setPen(QPen(rim, 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(11, 30, 78, 70))
    inner = QPainterPath()
    inner.addEllipse(QRectF(14, 33, 72, 64))
    _fill(p, inner, col.darker(140), None)


def _moon(p, ink):
    """A big blood-red moon behind him, like a halo."""
    grad = QRadialGradient(40, 30, 50)
    grad.setColorAt(0, QColor("#ff8a4d"))
    grad.setColorAt(1, QColor("#c2361f"))
    _fill(p, _circle(50, 48, 41), QColor(255, 110, 60, 60), None)     # its glow
    _fill(p, _circle(50, 48, 37), grad, QPen(QColor("#6e170e"), 2))
    for x, y, r in ((27, 34, 5), (73, 28, 4), (80, 52, 5.5), (22, 58, 3.5), (58, 14, 3)):
        _fill(p, _circle(x, y, r), QColor(140, 30, 16, 120), None)


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
def _pom_beanie(p, ink):
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
    _fill(p, _circle(50, 14, 7), WHITE, ink)


def _circle(x, y, r) -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(QPointF(x, y), r, r)
    return path


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
    p.save()
    p.setClipRect(QRectF(0, 0, 100, 53))     # his outline, only where the band covered it
    p.setPen(ink)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(_head())
    p.restore()
    # the knot and its two tails, out on his left
    _fill(p, _circle(84, 50, 3.5), col, ink)
    _fill(p, _poly((86, 49), (96, 42), (95, 50)), col, ink)
    _fill(p, _poly((86, 52), (97, 55), (92, 60)), col, ink)


def _eyeshade(p, ink):
    """An old terminal operator's amber eye shade, pushed up on his forehead."""
    p.save()
    p.setClipPath(_head())
    strap = QPainterPath()
    strap.addRect(QRectF(10, 45, 80, 5))
    _fill(p, strap, QColor("#3a2a12"), None)
    p.restore()
    shade = QPainterPath(QPointF(25, 48))
    shade.quadTo(QPointF(50, 44), QPointF(75, 48))
    shade.lineTo(83, 31)
    shade.quadTo(QPointF(50, 23), QPointF(17, 31))
    shade.closeSubpath()
    grad = QLinearGradient(0, 24, 0, 48)
    grad.setColorAt(0, QColor(255, 150, 20, 220))   # deeper than his amber headphones
    grad.setColorAt(1, QColor(190, 85, 0, 225))
    _fill(p, shade, grad, QPen(QColor("#3d2200"), 2.2))
    p.setPen(QPen(QColor(255, 255, 255, 160), 1.6, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(24, 32), QPointF(30, 43))


def _frog(p, ink):
    """A frog hat: a green beanie with two frog eyes on top and a wide grin."""
    col = QColor("#43a83f")
    dome = QPainterPath(QPointF(19, 53))
    dome.cubicTo(QPointF(17, 8), QPointF(83, 8), QPointF(81, 53))
    dome.quadTo(QPointF(50, 43), QPointF(19, 53))
    _fill(p, dome, col, ink)
    p.setPen(QPen(col.darker(160), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    grin = QPainterPath(QPointF(36, 27))
    grin.quadTo(QPointF(50, 35), QPointF(64, 27))
    p.drawPath(grin)
    for x in (36, 64):
        _fill(p, _circle(x, 19, 8.5), col, ink)
        _fill(p, _circle(x, 18.5, 5.6), WHITE, None)
        _fill(p, _circle(x + (1 if x < 50 else -1), 19, 3), DARK, None)
        _fill(p, _circle(x + (1.8 if x < 50 else -0.2), 17.6, 1), WHITE, None)


def _snapback(p, ink):
    """A red racing cap worn backwards: the brim pokes out behind, the strap's at
    the front, all clear of his brows."""
    col = QColor("#e8352f")
    p.save()
    p.translate(13, 43)
    p.rotate(14)
    brim = QPainterPath()
    brim.addEllipse(QRectF(-12, -4, 24, 8))
    _fill(p, brim, col.darker(125), ink)
    p.restore()
    dome = QPainterPath(QPointF(20, 51))
    dome.cubicTo(QPointF(18, 10), QPointF(82, 10), QPointF(80, 51))
    dome.quadTo(QPointF(50, 41), QPointF(20, 51))
    _fill(p, dome, col, ink)
    p.save()
    p.setClipPath(dome)
    for x in (43, 53):                                   # racing stripes
        _fill(p, _rect(x, 0, 4, 60), WHITE, None)
    p.restore()
    p.setPen(ink)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(dome)
    gap = QPainterPath(QPointF(41, 47.5))                # the strap's opening
    gap.cubicTo(QPointF(41, 38), QPointF(59, 38), QPointF(59, 47.5))
    gap.closeSubpath()
    _fill(p, gap, QColor("#fbf7f2"), QPen(INK_COL, 1.6))
    strap = QPainterPath()
    strap.addRoundedRect(QRectF(42.5, 42, 15, 3.6), 1.5, 1.5)
    _fill(p, strap, DARK, None)
    _fill(p, _circle(50, 20, 2.6), col.darker(130), None)


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
    """Two little devil horns on top of his head, between his ears."""
    col = QColor("#3a0b12")
    for sx in (1, -1):
        def m(x, y, sx=sx):
            return QPointF(50 + sx * (x - 50), y)
        horn = QPainterPath(m(41, 39))
        horn.cubicTo(m(40, 32), m(40, 27), m(43, 21))
        horn.cubicTo(m(45, 27), m(47, 32), m(48.5, 38))
        horn.closeSubpath()
        _fill(p, horn, col, ink)


def _captain(p, ink):
    """A ship captain's hat: white top, navy band, black peak, gold anchor."""
    navy = QColor("#1d2f5e")
    body = _poly((30, 42), (21, 24), (79, 24), (70, 42))
    _fill(p, body, WHITE, ink)
    top = QPainterPath()
    top.addEllipse(QRectF(19, 15, 62, 17))
    _fill(p, top, WHITE, ink)
    _fill(p, _poly((26, 34), (74, 34), (70.5, 42), (29.5, 42)), navy, ink)
    peak = QPainterPath(QPointF(27, 41))
    peak.quadTo(QPointF(50, 54), QPointF(73, 41))
    peak.quadTo(QPointF(50, 45), QPointF(27, 41))
    _fill(p, peak, DARK, ink)
    p.setPen(QPen(GOLD, 1.4))
    p.drawLine(QPointF(31, 40), QPointF(69, 40))
    _fill(p, _circle(50, 29, 5), GOLD, QPen(GOLD_DARK, 1))       # the badge, an anchor
    p.setPen(QPen(navy, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(50, 26), QPointF(50, 32))
    p.drawLine(QPointF(47.6, 27.4), QPointF(52.4, 27.4))
    hook = QPainterPath(QPointF(47, 30))
    hook.quadTo(QPointF(50, 33.5), QPointF(53, 30))
    p.drawPath(hook)


def _flower_crown(p, ink):
    """A crown of lavender, pink and white flowers on a green vine."""
    vine = QPainterPath(QPointF(21, 50))
    vine.cubicTo(QPointF(22, 27), QPointF(78, 27), QPointF(79, 50))
    p.setPen(QPen(QColor("#4e8f3e"), 2.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(vine)
    edge = QPen(QColor("#5b2fa3"), 0.9)
    cols = (QColor("#c9a2ff"), QColor("#ff9ccf"), QColor("#f4ecff"))
    for i in range(7):
        pt = vine.pointAtPercent(i / 6)
        _flower(p, pt.x(), pt.y(), 7 if i % 2 == 0 else 5.6, cols[i % 3], GOLD, edge)


def _mint_sprig(p, ink):
    """A sprig of mint tucked behind his right ear."""
    stem, leaf, vein = QColor("#2e7d4f"), QColor("#4fd88a"), QColor("#1f8a55")
    p.setPen(QPen(stem, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(29, 47), QPointF(14, 22))
    for x, y, a, k in ((14, 22, -115, 1.4), (19, 31, -170, 1.25), (23, 38, -45, 1.2)):
        p.save()
        p.translate(x, y)
        p.rotate(a)
        shape = QPainterPath(QPointF(0, 0))
        shape.cubicTo(QPointF(4 * k, -6 * k), QPointF(12 * k, -5 * k), QPointF(15 * k, 0))
        shape.cubicTo(QPointF(12 * k, 5 * k), QPointF(4 * k, 6 * k), QPointF(0, 0))
        _fill(p, shape, leaf, QPen(QColor("#145c3c"), 1.3))
        p.setPen(QPen(vein, 1))
        p.drawLine(QPointF(1, 0), QPointF(13 * k, 0))
        p.restore()


def _pencil(p, ink):
    """A pencil tucked behind his left ear."""
    p.save()
    p.translate(80, 37)
    p.rotate(-62)
    _fill(p, _rect(-11, -2.7, 19, 5.4), QColor("#ffcc33"), QPen(INK_COL, 1.3))
    _fill(p, _rect(8, -2.7, 2.5, 5.4), QColor("#b9bdc9"), QPen(INK_COL, 1.3))
    eraser = QPainterPath()
    eraser.addRoundedRect(QRectF(10.5, -2.7, 4, 5.4), 1.4, 1.4)
    _fill(p, eraser, QColor("#ff8fae"), QPen(INK_COL, 1.3))
    _fill(p, _poly((-11, -2.7), (-17, 0), (-11, 2.7)), QColor("#f3d3a0"),
          QPen(INK_COL, 1.3))
    _fill(p, _poly((-15, -0.9), (-17.3, 0), (-15, 0.9)), DARK, None)
    p.restore()


def _dizzy(p, ink):
    """Stars round his head: the flashbang got him."""
    edge = QPen(INK_COL, 1.2)
    for x, y, r in ((50, 21, 6), (18, 33, 5), (83, 31, 5)):
        _star(p, x, y, r, _col("accent2"), edge)


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
    y = EYE_Y
    left, right = EYES
    p.drawLine(QPointF(left + 8, y - 2.5), QPointF(right - 8, y - 2.5))   # bridge
    p.drawLine(QPointF(left - 8.5, y - 3), QPointF(18, y - 2))   # arms to the headphones
    p.drawLine(QPointF(right + 8.5, y - 3), QPointF(82, y - 2))
    for i, x in enumerate(EYES):
        if shape == "round":
            path = _circle(x, y, 9.3)
        elif shape == "heart":
            path = QPainterPath(QPointF(x, y + 9))
            path.cubicTo(QPointF(x - 14, y - 1), QPointF(x - 7.5, y - 13), QPointF(x, y - 5.5))
            path.cubicTo(QPointF(x + 7.5, y - 13), QPointF(x + 14, y - 1), QPointF(x, y + 9))
        else:
            path = QPainterPath()
            path.addRoundedRect(QRectF(x - 9.6, y - 8.6, 19.2, 17.2), 5.2, 5.2)
        lens = fill[i] if isinstance(fill, tuple) else fill
        _fill(p, path, lens, pen)
        if shape != "round":                               # a glint
            p.setPen(QPen(QColor(255, 255, 255, 150), 1.6, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(x - 5, y + 1.5), QPointF(x - 1, y - 3.5))


def _laser(p, ink):
    y = EYE_Y
    for x, sx in ((EYES[0], -1), (EYES[1], 1)):
        grad = QLinearGradient(x, y, x + sx * 60, y - 8)
        grad.setColorAt(0, QColor(255, 40, 40, 230))
        grad.setColorAt(1, QColor(255, 40, 40, 0))
        beam = _poly((x, y - 3), (x + sx * 70, y - 18), (x + sx * 70, y + 2), (x, y + 3))
        _fill(p, beam, grad, None)
        glow = QColor(255, 60, 60, 120)
        _fill(p, _circle(x, y, 9.5), glow, None)
        _fill(p, _circle(x, y, 5), QColor("#ff2b2b"), None)
        _fill(p, _circle(x, y, 2.2), WHITE, None)


def _pixel_shades(p, ink):
    k = 2.6
    rows = ("XXXXXXXXXXXXXXXXXX",
            " XWXXXXX  XWXXXXX ",
            " XXWXXXX  XXWXXXX ",
            "  XXXXX    XXXXX  ")
    x0, y0 = 50 - 9 * k, EYE_Y - 6
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
    band.addRoundedRect(QRectF(22.5, EYE_Y - 8.5, 55, 17), 8.5, 8.5)
    _fill(p, band, grad, QPen(DARK, 2))
    p.setPen(QPen(QColor(255, 255, 255, 170), 1.5))
    p.drawLine(QPointF(30, EYE_Y - 3.5), QPointF(70, EYE_Y - 3.5))
    p.setPen(QPen(DARK, 2))
    p.drawLine(QPointF(23, EYE_Y - 1), QPointF(18, EYE_Y - 1))
    p.drawLine(QPointF(77, EYE_Y - 1), QPointF(82, EYE_Y - 1))


def _strings(p, ink):
    """The hood's drawstrings, hanging over his chest."""
    p.setPen(QPen(QColor("#d8dce4"), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for x, dx in ((42, -1), (58, 1)):
        p.drawLine(QPointF(x, 90), QPointF(x + dx, 104))
        _fill(p, _rect(x + dx - 1.2, 104, 2.4, 4), QColor("#9aa0b4"), None)
        p.setPen(QPen(QColor("#d8dce4"), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))


def _spirals(p, ink):
    """Blinded: spirals for eyes."""
    y = EYE_Y
    for x in EYES:
        _fill(p, _circle(x, y, 7.8), WHITE, QPen(INK_COL, 1.6))
        spin = QPainterPath(QPointF(x, y))
        for i in range(1, 41):
            a = i * 0.42 * (1 if x < 50 else -1)
            r = 6.2 * i / 40
            spin.lineTo(x + r * math.cos(a), y + r * math.sin(a))
        p.setPen(QPen(INK_COL, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(spin)


def _readers(p, ink):
    """Half-moon reading glasses, low on his nose."""
    frame = QPen(QColor("#4a3326"), 1.8)
    p.setPen(frame)
    y = EYE_Y + 2.5
    p.drawLine(QPointF(EYES[0] + 7.5, y), QPointF(EYES[1] - 7.5, y))
    p.drawLine(QPointF(EYES[0] - 7.5, y), QPointF(18, y - 4))
    p.drawLine(QPointF(EYES[1] + 7.5, y), QPointF(82, y - 4))
    for x in EYES:
        lens = QPainterPath(QPointF(x - 7.5, y))
        lens.lineTo(x + 7.5, y)
        lens.cubicTo(QPointF(x + 7.5, y + 8), QPointF(x - 7.5, y + 8), QPointF(x - 7.5, y))
        _fill(p, lens, QColor(200, 230, 255, 80), frame)


def _sweater(p, ink):
    """The body of a turtleneck sweater (the collar is its own piece)."""
    col = _col("accent2")
    body = body_path()
    hem = QPainterPath()
    hem.addRect(QRectF(0, 0, 100, 111))
    body = body.intersected(hem).subtracted(_head())
    _fill(p, body, col, ink)
    p.save()
    p.setClipPath(body)
    p.setPen(QPen(col.darker(115), 1.4))
    for x in range(30, 72, 5):
        p.drawLine(QPointF(x, 106), QPointF(x, 111))
    p.restore()


def _turtleneck(p, ink):
    col = _col("accent2")
    roll = QPainterPath()
    roll.addRoundedRect(QRectF(30, 85, 40, 11), 5.5, 5.5)
    _fill(p, roll, col, ink)
    p.save()
    p.setClipPath(roll)
    p.setPen(QPen(col.darker(118), 1.4))
    for x in range(34, 68, 4):
        p.drawLine(QPointF(x, 85), QPointF(x, 96))
    p.restore()
    p.setPen(ink)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(roll)


def _badge(p, ink):
    """A glowing radiation badge on his chest."""
    _fill(p, _circle(50, 101, 10.5), QColor(198, 255, 61, 90), None)
    _fill(p, _circle(50, 101, 7.5), QColor("#ffd23f"), QPen(INK_COL, 1.4))
    for start in (0, 120, 240):
        blade = QPainterPath(QPointF(50, 101))
        blade.arcTo(QRectF(44, 95, 12, 12), start, 60)
        blade.closeSubpath()
        _fill(p, blade, DARK, None)
    _fill(p, _circle(50, 101, 2.2), QColor("#ffd23f"), None)
    _fill(p, _circle(50, 101, 1.3), DARK, None)


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
    "moon": ("behind", _moon),
    "hood": ("back", lambda p, ink: _hood(p, ink, QColor("#2c323e"), _col("accent"))),
    "hazmat": ("back", lambda p, ink: _hood(p, ink, QColor("#f2c230"))),
    "collar": ("back", _collar),
    "pom_beanie": ("under", _pom_beanie),
    "bandana": ("under", _bandana),
    "eyeshade": ("under", _eyeshade),
    "frog": ("under", _frog),
    "snapback": ("under", _snapback),
    "wizard": ("over", _wizard),
    "captain": ("over", _captain),
    "beret": ("over", _beret),
    "crown": ("over", _crown),
    "horns": ("over", _horns),
    "blossom": ("over", _blossom),
    "leaves": ("over", _leaves),
    "flower_crown": ("over", _flower_crown),
    "mint_sprig": ("over", _mint_sprig),
    "pencil": ("over", _pencil),
    "onion": ("over", _onion),
    "party": ("over", _party),
    "propeller": ("over", _propeller),
    "bow": ("over", _bow),
    "dizzy": ("over", _dizzy),
    "sweater": ("face", _sweater),
    "shades": ("face", lambda p, ink: _lenses(p, ink, DARK)),
    "round_glasses": ("face", lambda p, ink: _lenses(p, ink, QColor(200, 230, 255, 60),
                                                      "round", QColor("#5a3a24"))),
    "heart_glasses": ("face", lambda p, ink: _lenses(p, ink, QColor(255, 79, 163, 200),
                                                      "heart", QColor("#c2186b"))),
    "glasses_3d": ("face", lambda p, ink: _lenses(
        p, ink, (QColor(255, 40, 60, 170), QColor(40, 220, 255, 170)), "rect", WHITE)),
    "pixel_shades": ("face", _pixel_shades),
    "visor": ("face", _visor),
    "spirals": ("face", _spirals),
    "readers": ("face", _readers),
    "laser": ("face", _laser),
    "strings": ("face", _strings),
    "fangs": ("face", _fangs),
    "clown_nose": ("face", _clown_nose),
    "turtleneck": ("face", _turtleneck),
    "badge": ("face", _badge),
    "bowtie": ("face", _bowtie),
    "scarf": ("face", _scarf),
    "lei": ("face", _lei),
}


def draw(p: QPainter, pieces: tuple[str, ...], layer: str, ink: QPen,
         hats: bool = True, shut: bool = False) -> None:
    """Paint the `layer` part of `pieces` (bunny.py calls this between its own layers).
    `hats=False`: his nightcap is on, so nothing on his head and no glasses (he took
    them off to sleep); `shut`: his eyes are closed, so no laser eyes."""
    for name in pieces:
        where, fn = PIECES.get(name, ("", None))
        if (where == layer and fn and (hats or name not in HATS | EYEWEAR)
                and not (shut and name == "laser")):
            p.save()
            fn(p, ink)
            p.restore()
