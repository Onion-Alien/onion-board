"""What flies out of Bun's headphones besides notes, by theme: hearts for Bubblegum, petals
for Cherry Blossom, gold stars for Royal, bats and drops of blood for Vampire... (`pick`,
`paint`). Every theme has its own; one that isn't in MIXES throws notes only. Used by
`paint_note` (ui/bun/bunbits.py)."""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QConicalGradient, QFont, QFontMetricsF, QPainter,
                           QPainterPath, QPen, QPolygonF, QRadialGradient)

from soundboard.style import hooks
from soundboard.ui.kit import theme
from soundboard.ui.bun.bunny import INK

# theme -> what he throws, (kind, colour) each as likely; "note" keeps a note in the mix
MIXES: dict[str, tuple[tuple[str, str], ...]] = {
    "Bubblegum": (("heart", "#e8006e"), ("heart", "#ffffff"), ("note", "#c4005c"),
               ("heart", "#ff3d8b")),
    "Cherry Blossom": (("petal", "#ff8fb8"), ("petal", "#ffb3cf"), ("heart", "#e8457f"),
                       ("note", "#d9467c")),
    "Royal": (("star", "#f4c430"), ("sparkle", "#ffe27a"), ("note", "#f4c430"),
              ("star", "#ffd75e")),
    "Arctic": (("snowflake", "#d6f1ff"), ("snowflake", "#9fdcff"), ("note", "#7fc8ff"),
               ("sparkle", "#ffffff")),
    "Ocean": (("bubble", "#8fe3ff"), ("bubble", "#5cc8ff"), ("note", "#3fb0ff"),
              ("bubble", "#c8f3ff")),
    "Forest": (("leaf", "#6cc04a"), ("leaf", "#a8d65a"), ("note", "#5fbf6a"),
               ("leaf", "#d9a441")),
    "Halloween": (("ghost", "#f5f2ff"), ("bat", "#a77ce6"), ("note", "#ff9a2e"),
                  ("bat", "#8b5cd0")),
    "Fireworks": (("sparkle", "#ffc94d"), ("star", "#ff5fae"), ("note", "#ffb627"),
                  ("sparkle", "#ff8cc6"), ("burst", "#ffc94d"), ("burst", "#6fd3ff")),
    "Hacker": (("digit", "#3cff6e"), ("digit", "#28c850"), ("note", "#3cff6e"),
               ("digit", "#9bffb5")),
    "Dark": (("wave", "#7859f7"), ("wave", "#ff4d8d"), ("note", "#7859f7"),
             ("sparkle", "#c9b8ff")),
    "Light": (("cup", "#ffffff"), ("cup", "#f3edff"), ("note", "#6a4cff"),
              ("sparkle", "#e6b93d")),
    "Lilac": (("flower", "#c9a7ff"), ("flower", "#ff8fc4"), ("note", "#ff5fa2"),
              ("peace", "#b58cff")),
    "Toxic": (("trefoil", "#ffe23d"), ("drop", "#1ee07f"), ("note", "#1ee07f"),
              ("drop", "#c6ff3d")),
    "Carbon": (("coin", "#f4c430"), ("diamond", "#9fe6ff"), ("note", "#aeb3bf"),
               ("coin", "#ffd75e")),
    "Midnight": (("moon", "#ffe27a"), ("star", "#b36bff"), ("note", "#336bed"),
                 ("sparkle", "#9fbfff")),
    "Slate": (("text", "#e0a458"), ("thought", "#e2e8ef"), ("note", "#4fa3a5"),
              ("text", "#4fa3a5")),
    "Paper": (("text", "#2f6f73"), ("book", "#b5562c"), ("note", "#3b3226"),
              ("text", "#b5562c")),
    "High Contrast": (("text", "#ffff00"), ("text", "#00ffff"), ("note", "#ffffff"),
                      ("note", "#ffff00")),
    "Vampire": (("bat", "#bd93f9"), ("drop", "#d4213d"), ("note", "#bd93f9"),
                ("bat", "#ff79c6")),
    "Mocha": (("bean", "#8a5a3c"), ("splat", "#d4915a"), ("note", "#d4915a"),
              ("splat", "#efe4da")),
    "Sunset": (("sun", "#ffb347"), ("flower", "#ff3d7f"), ("note", "#ff7849"),
               ("flower", "#ff7849")),
    "Onion": (("drop", "#8fd0ff"), ("ring", "#e3c6f0"), ("note", "#8fd14f"),
              ("ring", "#ae45d7")),
    "Mint": (("leaf", "#3ddc97"), ("leaf", "#0e8669"), ("note", "#0e8669"),
             ("sparkle", "#3f8cff")),
    "Synthwave": (("triangle", "#36f9f6"), ("triangle", "#ff2e88"), ("note", "#ff4fd8"),
                  ("bolt", "#f9e936")),
    "Vaporwave": (("text", "#9f3dff"), ("cd", "#c8b5ff"), ("note", "#ff71ce"),
                  ("text", "#05b083")),
    "Blood Moon": (("moon", "#d91f35"), ("pitchfork", "#ff8a3d"), ("note", "#d91f35"),
                   ("moon", "#ff5a4a")),
    "Lava": (("flame", "#ff5a1f"), ("flame", "#ffb020"), ("note", "#ff5a1f"),
             ("sparkle", "#ffd23d")),
    "Amber Terminal": (("text", "#ffb000"), ("check", "#ffb000"), ("note", "#ff7a00"),
                       ("text", "#ffc766")),
    "Flashbang": (("spiral", "#ffd600"), ("star", "#ff9100"), ("note", "#ffd600"),
                  ("spiral", "#ff9100")),
    "Swamp": (("fly", "#1c1f12"), ("bubble", "#a4c639"), ("note", "#a4c639"),
              ("fly", "#1c1f12")),
    "Deep Fried": (("text", "#ff2020"), ("flare", "#ffff00"), ("note", "#00ff00"),
                   ("text", "#ffff00")),
    "Retro 98": (("floppy", "#000080"), ("cursor", "#ffffff"), ("note", "#000080"),
                 ("floppy", "#008080")),
    "Comic Sans": (("confetti", "#e01686"), ("balloon", "#1aa7ec"), ("note", "#e01686"),
                   ("confetti", "#1aa7ec"), ("balloon", "#e01686"), ("confetti", "#ffb800")),
    "Brainrot": (("skull", "#f2f2f2"), ("text", "#c6ff00"), ("note", "#ff00d4"),
                 ("text", "#ff00d4")),
}
# the "text" kind: the font and the bits of text a theme throws (one picked by its seed)
TEXT: dict[str, tuple[str, tuple[str, ...]]] = {
    "Slate": ("Georgia", ("?", "?", "…")),
    "Paper": ("Georgia", ("A", "b", "C", "&", "Q", "e")),
    "High Contrast": ("Arial Black", ("!",)),
    "Vaporwave": ("Yu Gothic", ("Ａ", "Ｅ", "Ｓ", "Ｔ", "Ｈ", "Ｉ", "Ｃ")),
    "Amber Terminal": ("Consolas", ("$", "%", "#", "7", "4", "+", "=")),
    "Deep Fried": ("Impact", ("100", "!!", "B")),
    "Brainrot": ("Arial Black", ("W", "67", "?!")),
}
# (these get their colour pushed to stand out like a note's; the rest keep theirs and an
# outline does that)
LIKE_NOTES = {"note", "digit", "snowflake", "bubble", "sparkle", "wave", "peace", "text",
              "triangle", "check", "burst"}


def pick(rng: random.Random) -> tuple[str, QColor] | None:
    """What the next one is in the current theme, or None: a plain note."""
    mix = MIXES.get(hooks.theme_name())
    if not mix:
        return None
    kind, col = rng.choice(mix)
    return None if kind == "note" else (kind, QColor(col))


def rim(bg: QColor) -> QColor:
    """The outline that keeps a symbol readable on the theme's background."""
    if bg.lightnessF() < 0.45:
        return QColor(255, 255, 255, 90)
    return QColor(INK.red(), INK.green(), INK.blue(), 170)


def paint(p: QPainter, kind: str, r: float, col: QColor, edge: QColor, seed: int = 0):
    """A `kind` about 2r across, centred on (0, 0)."""
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    _KINDS[kind](p, r, col, QPen(edge, max(1.0, r * 0.12)), seed)


def _heart(p, r, col, pen, _seed):
    path = QPainterPath(QPointF(0, r * 0.9))
    path.cubicTo(-r * 1.4, -r * 0.1, -r * 0.7, -r * 1.2, 0, -r * 0.45)
    path.cubicTo(r * 0.7, -r * 1.2, r * 1.4, -r * 0.1, 0, r * 0.9)
    p.setPen(pen)
    p.setBrush(col)
    p.drawPath(path)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 150))   # a shine
    p.drawEllipse(QRectF(-r * 0.62, -r * 0.62, r * 0.32, r * 0.24))


def _star(p, r, col, pen, _seed):
    pts = []
    for i in range(10):   # five points, five dips
        a, rr = -math.pi / 2 + i * math.pi / 5, r if i % 2 == 0 else r * 0.45
        pts.append(QPointF(math.cos(a) * rr, math.sin(a) * rr))
    p.setPen(pen)
    p.setBrush(col)
    p.drawPolygon(QPolygonF(pts))


def _sparkle(p, r, col, _pen, _seed):
    from soundboard.ui.bun.bunny import sparkle
    sparkle(p, 0, 0, r, col)


def _petal(p, r, col, pen, _seed):
    path = QPainterPath(QPointF(0, r))
    path.cubicTo(-r * 1.1, r * 0.2, -r * 0.6, -r * 0.9, -r * 0.15, -r * 0.8)
    path.lineTo(0, -r * 0.55)   # the little notch at its tip
    path.lineTo(r * 0.15, -r * 0.8)
    path.cubicTo(r * 0.6, -r * 0.9, r * 1.1, r * 0.2, 0, r)
    p.setPen(pen)
    p.setBrush(col)
    p.drawPath(path)


def _snowflake(p, r, col, _pen, _seed):
    p.setPen(QPen(col, max(1.4, r * 0.18), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for i in range(3):
        a = i * math.pi / 3
        c, s = math.cos(a), math.sin(a)
        p.drawLine(QPointF(-c * r, -s * r), QPointF(c * r, s * r))
        for sgn in (-1, 1):   # a little V on each arm
            bx, by = c * r * 0.55 * sgn, s * r * 0.55 * sgn
            for t in (-1, 1):
                a2 = a + t * 0.7
                p.drawLine(QPointF(bx, by), QPointF(bx + sgn * math.cos(a2) * r * 0.3,
                                                    by + sgn * math.sin(a2) * r * 0.3))


def _bubble(p, r, col, _pen, _seed):
    p.setPen(QPen(col, max(1.3, r * 0.14)))
    fill = QColor(col)
    fill.setAlpha(55)
    p.setBrush(fill)
    p.drawEllipse(QRectF(-r, -r, 2 * r, 2 * r))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 200))
    p.drawEllipse(QRectF(-r * 0.55, -r * 0.6, r * 0.38, r * 0.3))


def _leaf(p, r, col, pen, _seed):
    path = QPainterPath(QPointF(0, -r))
    path.quadTo(r * 0.9, 0, 0, r)
    path.quadTo(-r * 0.9, 0, 0, -r)
    p.setPen(pen)
    p.setBrush(col)
    p.drawPath(path)
    p.setPen(QPen(col.darker(150), max(1.0, r * 0.1)))   # its middle vein and stalk
    p.drawLine(QPointF(0, -r * 0.8), QPointF(0, r * 1.25))


def _bat(p, r, col, pen, _seed):
    path = QPainterPath(QPointF(0, -r * 0.25))
    for x, y in ((-0.25, -0.55), (-0.2, -0.2)):   # an ear
        path.lineTo(r * x, r * y)
    for (cx, cy), (x, y) in (((-0.7, -0.65), (-1.3, -0.35)), ((-1.0, -0.15), (-1.05, 0.2)),
                             ((-0.75, 0), (-0.55, 0.25)), ((-0.35, 0.05), (0, 0.45)),
                             ((0.35, 0.05), (0.55, 0.25)), ((0.75, 0), (1.05, 0.2)),
                             ((1.0, -0.15), (1.3, -0.35)), ((0.7, -0.65), (0.2, -0.2))):
        path.quadTo(r * cx, r * cy, r * x, r * y)   # the wings' scalloped edges
    path.lineTo(r * 0.25, -r * 0.55)
    path.closeSubpath()
    p.setPen(pen)
    p.setBrush(col)
    p.drawPath(path)


def _ghost(p, r, col, _pen, _seed):
    path = QPainterPath(QPointF(-r * 0.8, r * 0.9))
    path.lineTo(-r * 0.8, 0)
    path.cubicTo(-r * 0.8, -r * 1.25, r * 0.8, -r * 1.25, r * 0.8, 0)
    path.lineTo(r * 0.8, r * 0.9)
    for i in range(3):   # the wavy hem
        x0 = r * 0.8 - i * r * 0.533
        path.quadTo(x0 - r * 0.13, r * 0.55, x0 - r * 0.27, r * 0.9)
        path.quadTo(x0 - r * 0.4, r * 1.2, x0 - r * 0.533, r * 0.9)
    p.setPen(QPen(INK, max(1.0, r * 0.1)))
    p.setBrush(col)
    p.drawPath(path)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(INK)
    for ex in (-0.3, 0.3):
        p.drawEllipse(QRectF(r * ex - r * 0.12, -r * 0.3, r * 0.24, r * 0.32))


def _digit(p, r, col, _pen, seed):
    f = QFont("Consolas")
    f.setPixelSize(max(6, round(r * 2.2)))
    f.setBold(True)
    p.setFont(f)
    p.setPen(col)
    p.drawText(QRectF(-r * 1.5, -r * 1.5, r * 3, r * 3), Qt.AlignmentFlag.AlignCenter,
               "01"[seed % 2])


def _fill(p, col, pen):
    p.setPen(pen)
    p.setBrush(col)


def _wave(p, r, col, _pen, _seed):
    """A speaker's sound: three arcs."""
    p.setPen(QPen(col, max(1.4, r * 0.2), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    for rr in (0.4, 0.8, 1.2):
        p.drawArc(QRectF(-r * 0.7 - r * rr, -r * rr, 2 * r * rr, 2 * r * rr), -50 * 16, 100 * 16)


def _cup(p, r, col, pen, _seed):
    """A teacup on its saucer."""
    _fill(p, col, pen)
    p.drawEllipse(QRectF(-r * 1.05, r * 0.45, r * 2.1, r * 0.45))   # the saucer
    body = QPainterPath(QPointF(-r * 0.8, -r * 0.45))
    body.lineTo(r * 0.6, -r * 0.45)
    body.cubicTo(r * 0.6, r * 0.35, r * 0.3, r * 0.6, -r * 0.1, r * 0.6)
    body.cubicTo(-r * 0.5, r * 0.6, -r * 0.8, r * 0.35, -r * 0.8, -r * 0.45)
    body.closeSubpath()
    p.drawPath(body)
    p.setBrush(Qt.BrushStyle.NoBrush)   # the handle
    p.drawArc(QRectF(r * 0.4, -r * 0.3, r * 0.6, r * 0.55), -90 * 16, 180 * 16)
    gold = QColor("#e6b93d")
    p.setPen(QPen(gold, max(1.0, r * 0.12)))
    p.drawLine(QPointF(-r * 0.72, -r * 0.2), QPointF(r * 0.55, -r * 0.2))   # a gold band
    p.setPen(QPen(QColor(255, 255, 255, 160), max(1.0, r * 0.1), Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))   # steam
    steam = QPainterPath(QPointF(-r * 0.1, -r * 0.65))
    steam.cubicTo(-r * 0.35, -r * 0.85, r * 0.15, -r * 1.0, -r * 0.1, -r * 1.25)
    p.drawPath(steam)


def _flower(p, r, col, pen, _seed):
    """Five round petals and a yellow middle."""
    p.setPen(pen)
    p.setBrush(col)
    for i in range(5):
        a = -math.pi / 2 + i * 2 * math.pi / 5
        p.drawEllipse(QPointF(math.cos(a) * r * 0.55, math.sin(a) * r * 0.55), r * 0.45, r * 0.45)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#ffd23d"))
    p.drawEllipse(QPointF(0, 0), r * 0.32, r * 0.32)


def _peace(p, r, col, _pen, _seed):
    """☮"""
    p.setPen(QPen(col, max(1.4, r * 0.2), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(0, 0), r * 0.9, r * 0.9)
    p.drawLine(QPointF(0, -r * 0.9), QPointF(0, r * 0.9))
    for sgn in (-1, 1):
        p.drawLine(QPointF(0, 0), QPointF(sgn * r * 0.64, r * 0.64))


def _trefoil(p, r, col, pen, _seed):
    """The radiation sign: three black blades on yellow."""
    _fill(p, col, pen)
    p.drawEllipse(QPointF(0, 0), r, r)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(INK)
    box = QRectF(-r * 0.82, -r * 0.82, r * 1.64, r * 1.64)
    for i in range(3):
        p.drawPie(box, (60 + i * 120) * 16, 60 * 16)
    p.setBrush(col)
    p.drawEllipse(QPointF(0, 0), r * 0.3, r * 0.3)
    p.setBrush(INK)
    p.drawEllipse(QPointF(0, 0), r * 0.18, r * 0.18)


def _drop(p, r, col, pen, _seed):
    """A drop: goo, a tear, blood."""
    path = QPainterPath(QPointF(0, -r))
    path.cubicTo(r * 0.25, -r * 0.45, r * 0.8, -r * 0.05, r * 0.8, r * 0.35)
    path.cubicTo(r * 0.8, r * 0.8, r * 0.4, r * 1.0, 0, r * 1.0)
    path.cubicTo(-r * 0.4, r * 1.0, -r * 0.8, r * 0.8, -r * 0.8, r * 0.35)
    path.cubicTo(-r * 0.8, -r * 0.05, -r * 0.25, -r * 0.45, 0, -r)
    _fill(p, col, pen)
    p.drawPath(path)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 170))
    p.drawEllipse(QRectF(-r * 0.5, r * 0.1, r * 0.25, r * 0.4))


def _coin(p, r, col, pen, _seed):
    """A gold coin with a $ on it."""
    _fill(p, col, pen)
    p.drawEllipse(QPointF(0, 0), r, r)
    p.setPen(QPen(col.darker(135), max(1.0, r * 0.12)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(0, 0), r * 0.75, r * 0.75)
    _text(p, r * 0.75, col.darker(150), "$", "Arial Black")


def _diamond(p, r, col, pen, _seed):
    """A cut gem."""
    pts = [QPointF(-r * 0.55, -r * 0.6), QPointF(r * 0.55, -r * 0.6), QPointF(r, -r * 0.15),
           QPointF(0, r), QPointF(-r, -r * 0.15)]
    _fill(p, col, pen)
    p.drawPolygon(QPolygonF(pts))
    p.setPen(QPen(col.darker(140), max(0.8, r * 0.08)))
    p.drawLine(QPointF(-r, -r * 0.15), QPointF(r, -r * 0.15))
    for x in (-0.3, 0.3):   # the facets
        p.drawLine(QPointF(r * x * 1.8, -r * 0.6), QPointF(r * x, -r * 0.15))
        p.drawLine(QPointF(r * x, -r * 0.15), QPointF(0, r))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 190))
    p.drawPolygon(QPolygonF([QPointF(-r * 0.45, -r * 0.5), QPointF(-r * 0.15, -r * 0.5),
                             QPointF(-r * 0.35, -r * 0.2)]))


def _moon(p, r, col, pen, _seed):
    """A crescent moon."""
    whole = QPainterPath()
    whole.addEllipse(QPointF(0, 0), r, r)
    bite = QPainterPath()
    bite.addEllipse(QPointF(r * 0.55, -r * 0.3), r * 0.85, r * 0.85)
    _fill(p, col, pen)
    p.drawPath(whole.subtracted(bite))


def _thought(p, r, col, pen, _seed):
    """A thought: a little cloud and two dots trailing off it."""
    cloud = QPainterPath()
    for x, y, rr in ((-0.45, -0.1, 0.45), (0.1, -0.35, 0.5), (0.55, -0.05, 0.42),
                     (0.05, 0.15, 0.45)):
        puff = QPainterPath()
        puff.addEllipse(QPointF(r * x, r * y), r * rr, r * rr)
        cloud = cloud.united(puff)
    _fill(p, col, pen)
    p.drawPath(cloud)
    p.drawEllipse(QPointF(-r * 0.75, r * 0.6), r * 0.17, r * 0.17)
    p.drawEllipse(QPointF(-r * 1.0, r * 0.95), r * 0.1, r * 0.1)


def _book(p, r, col, pen, _seed):
    """A closed book: cover, pages, a band on its spine."""
    _fill(p, QColor("#fff8e6"), pen)   # the pages, showing past the cover
    p.drawRoundedRect(QRectF(-r * 0.6, -r * 0.8, r * 1.35, r * 1.6), r * 0.1, r * 0.1)
    p.setBrush(col)
    p.drawRoundedRect(QRectF(-r * 0.75, -r * 0.9, r * 1.35, r * 1.65), r * 0.12, r * 0.12)
    p.setPen(QPen(QColor("#ffd23d"), max(1.0, r * 0.14)))
    for y in (-0.55, 0.45):
        p.drawLine(QPointF(-r * 0.75, r * y), QPointF(r * 0.6, r * y))


def _bean(p, r, col, pen, _seed):
    """A coffee bean."""
    p.save()
    p.rotate(-30)
    _fill(p, col, pen)
    p.drawEllipse(QPointF(0, 0), r * 0.7, r)
    p.setPen(QPen(col.darker(170), max(1.0, r * 0.16), Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))
    crease = QPainterPath(QPointF(0, -r * 0.8))
    crease.cubicTo(r * 0.35, -r * 0.3, -r * 0.35, r * 0.3, 0, r * 0.8)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(crease)
    p.restore()


def _splat(p, r, col, pen, seed):
    """A splash of paint: a round middle with blobs of all sizes round it, and a drop or
    two flying off it."""
    rng = random.Random(seed)
    path = QPainterPath()
    path.addEllipse(QPointF(0, 0), r * 0.6, r * 0.6)
    a0 = rng.uniform(0, 2 * math.pi)
    for i in range(7):
        a = a0 + i * 2 * math.pi / 7 + rng.uniform(-0.25, 0.25)
        d, rr = rng.uniform(0.5, 0.7), rng.uniform(0.18, 0.34)
        blob = QPainterPath()
        blob.addEllipse(QPointF(math.cos(a) * r * d, math.sin(a) * r * d), r * rr, r * rr)
        path = path.united(blob)
    _fill(p, col, pen)
    p.drawPath(path)
    for _i in range(2):
        a = rng.uniform(0, 2 * math.pi)
        p.drawEllipse(QPointF(math.cos(a) * r * 1.15, math.sin(a) * r * 1.15), r * 0.13,
                      r * 0.13)


def _sun(p, r, col, pen, _seed):
    p.setPen(QPen(col, max(1.3, r * 0.17), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for i in range(8):
        a = i * math.pi / 4
        p.drawLine(QPointF(math.cos(a) * r * 0.7, math.sin(a) * r * 0.7),
                   QPointF(math.cos(a) * r, math.sin(a) * r))
    _fill(p, col, pen)
    p.drawEllipse(QPointF(0, 0), r * 0.5, r * 0.5)


def _ring(p, r, col, pen, _seed):
    """An onion ring: a fat ring of onion, its layers showing."""
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(pen.color(), r * 0.42 + 2 * pen.widthF()))
    p.drawEllipse(QPointF(0, 0), r * 0.75, r * 0.65)
    p.setPen(QPen(col, r * 0.42))
    p.drawEllipse(QPointF(0, 0), r * 0.75, r * 0.65)
    p.setPen(QPen(col.lighter(130), max(0.8, r * 0.07)))
    p.drawEllipse(QPointF(0, 0), r * 0.75, r * 0.65)


def _triangle(p, r, col, _pen, _seed):
    """A neon triangle, outline only."""
    pts = [QPointF(math.cos(a) * r, math.sin(a) * r + r * 0.15)
           for a in (-math.pi / 2, math.pi / 6, 5 * math.pi / 6)]
    p.setPen(QPen(col, max(1.4, r * 0.2), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolygon(QPolygonF(pts))


def _bolt(p, r, col, pen, _seed):
    pts = [(0.25, -1.0), (-0.55, 0.12), (-0.05, 0.12), (-0.3, 1.0), (0.6, -0.2), (0.08, -0.2),
           (0.45, -1.0)]
    _fill(p, col, pen)
    p.drawPolygon(QPolygonF([QPointF(r * x, r * y) for x, y in pts]))


def _cd(p, r, col, pen, _seed):
    """A shiny disc, every colour of the rainbow across it."""
    g = QConicalGradient(0, 0, 30)
    for i, c in enumerate((col, QColor("#9ff3ff"), QColor("#fff3a8"), QColor("#ffb3e6"), col)):
        g.setColorAt(i / 4, c)
    p.setPen(pen)
    p.setBrush(g)
    p.drawEllipse(QPointF(0, 0), r, r)
    p.setBrush(QColor(theme.T["bg"]))
    p.drawEllipse(QPointF(0, 0), r * 0.22, r * 0.22)


def _pitchfork(p, r, col, pen, _seed):
    """A little devil's fork."""
    p.save()
    p.rotate(20)
    w = max(1.3, r * 0.2)
    path = QPainterPath(QPointF(0, r))
    path.lineTo(0, -r * 0.35)
    path.moveTo(-r * 0.5, -r)
    path.lineTo(-r * 0.5, -r * 0.55)
    path.quadTo(-r * 0.5, -r * 0.35, 0, -r * 0.35)
    path.quadTo(r * 0.5, -r * 0.35, r * 0.5, -r * 0.55)
    path.lineTo(r * 0.5, -r)
    path.moveTo(0, -r * 0.35)
    path.lineTo(0, -r)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(pen.color(), w + 2 * pen.widthF(), Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawPath(path)
    p.setPen(QPen(col, w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    p.drawPath(path)
    p.restore()


def _flame(p, r, col, pen, _seed):
    def tongue(k):
        path = QPainterPath(QPointF(0, -r * k))
        path.cubicTo(r * 0.3 * k, -r * 0.45 * k, r * 0.85 * k, -r * 0.1 * k, r * 0.7 * k,
                     r * 0.45 * k)
        path.cubicTo(r * 0.55 * k, r * 0.95 * k, -r * 0.55 * k, r * 0.95 * k, -r * 0.7 * k,
                     r * 0.45 * k)
        path.cubicTo(-r * 0.85 * k, 0, -r * 0.35 * k, -r * 0.2 * k, -r * 0.25 * k,
                     -r * 0.55 * k)
        path.cubicTo(-r * 0.05 * k, -r * 0.4 * k, -r * 0.05 * k, -r * 0.7 * k, 0, -r * k)
        return path
    _fill(p, col, pen)
    p.drawPath(tongue(1.0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#ffe680"))
    p.translate(0, r * 0.25)
    p.drawPath(tongue(0.55))


def _check(p, r, col, _pen, _seed):
    p.setPen(QPen(col, max(1.6, r * 0.28), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolyline(QPolygonF([QPointF(-r * 0.8, 0), QPointF(-r * 0.25, r * 0.6),
                              QPointF(r * 0.85, -r * 0.65)]))


def _spiral(p, r, col, pen, _seed):
    """Seeing stars: a dizzy spiral, outlined (it's yellow on white)."""
    pts = []
    for i in range(60):
        a = i * 0.21
        rr = r * i / 59
        pts.append(QPointF(math.cos(a) * rr, math.sin(a) * rr))
    w = max(1.3, r * 0.2)
    p.setBrush(Qt.BrushStyle.NoBrush)
    for c, width in ((pen.color(), w + 2 * pen.widthF()), (col, w)):
        p.setPen(QPen(c, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPolyline(QPolygonF(pts))


def _fly(p, r, col, _pen, _seed):
    """A swamp fly: two see-through wings and a fat dark body."""
    wing = QColor(235, 245, 255, 190)
    p.setPen(QPen(QColor(255, 255, 255, 110), max(0.8, r * 0.08)))
    p.setBrush(wing)
    for sgn in (-1, 1):
        p.save()
        p.rotate(sgn * 35)
        p.drawEllipse(QPointF(sgn * r * 0.45, -r * 0.45), r * 0.42, r * 0.6)
        p.restore()
    p.setPen(QPen(QColor(255, 255, 255, 90), max(0.8, r * 0.08)))
    p.setBrush(col)
    p.drawEllipse(QPointF(0, r * 0.2), r * 0.38, r * 0.55)
    p.drawEllipse(QPointF(0, -r * 0.35), r * 0.28, r * 0.25)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#e8473c"))   # its big red eyes
    for sgn in (-1, 1):
        p.drawEllipse(QPointF(sgn * r * 0.17, -r * 0.4), r * 0.13, r * 0.13)


def _flare(p, r, col, _pen, _seed):
    """A blown-out lens flare."""
    g = QRadialGradient(0, 0, r * 1.2)
    glow = QColor(col)
    glow.setAlpha(200)
    g.setColorAt(0, QColor(255, 255, 255, 255))
    g.setColorAt(0.25, glow)
    glow.setAlpha(0)
    g.setColorAt(1, glow)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawEllipse(QPointF(0, 0), r * 1.2, r * 1.2)
    from soundboard.ui.bun.bunny import sparkle
    sparkle(p, 0, 0, r * 1.3, QColor(255, 255, 255, 230))


def _confetti(p, r, col, pen, seed):
    p.rotate(seed % 180)
    _fill(p, col, pen)
    if seed % 3:
        p.drawRect(QRectF(-r * 0.7, -r * 0.28, r * 1.4, r * 0.56))
    else:   # a curl of streamer
        p.setPen(QPen(col, max(1.3, r * 0.25), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        curl = QPainterPath(QPointF(-r * 0.9, 0))
        curl.cubicTo(-r * 0.45, -r * 0.8, -r * 0.1, r * 0.8, r * 0.3, 0)
        curl.cubicTo(r * 0.5, -r * 0.4, r * 0.75, -r * 0.3, r * 0.9, 0)
        p.drawPath(curl)


def _balloon(p, r, col, pen, _seed):
    p.setPen(QPen(pen.color(), max(0.8, r * 0.07)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    string = QPainterPath(QPointF(0, r * 0.75))
    string.cubicTo(r * 0.3, r * 1.0, -r * 0.3, r * 1.2, r * 0.05, r * 1.5)
    p.drawPath(string)
    _fill(p, col, pen)
    p.drawEllipse(QPointF(0, -r * 0.1), r * 0.7, r * 0.85)
    p.drawPolygon(QPolygonF([QPointF(0, r * 0.7), QPointF(-r * 0.15, r * 0.88),
                             QPointF(r * 0.15, r * 0.88)]))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 170))
    p.drawEllipse(QRectF(-r * 0.45, -r * 0.6, r * 0.25, r * 0.4))


def _skull(p, r, col, pen, _seed):
    _fill(p, col, pen)
    head = QPainterPath()
    head.addEllipse(QPointF(0, -r * 0.15), r * 0.85, r * 0.75)
    jaw = QPainterPath()
    jaw.addRoundedRect(QRectF(-r * 0.45, r * 0.2, r * 0.9, r * 0.7), r * 0.18, r * 0.18)
    p.drawPath(head.united(jaw))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(INK)
    for sgn in (-1, 1):
        p.drawEllipse(QPointF(sgn * r * 0.33, -r * 0.1), r * 0.22, r * 0.25)
    p.drawPolygon(QPolygonF([QPointF(0, r * 0.15), QPointF(-r * 0.1, r * 0.35),
                             QPointF(r * 0.1, r * 0.35)]))
    p.setPen(QPen(INK, max(0.8, r * 0.08)))
    for x in (-0.15, 0.15):   # its teeth
        p.drawLine(QPointF(r * x, r * 0.6), QPointF(r * x, r * 0.88))


def _burst(p, r, col, _pen, seed):
    """A firework going off: streaks out from the middle, a bright dot on each end."""
    rng = random.Random(seed)
    a0 = rng.uniform(0, math.pi)
    w = max(1.2, r * 0.14)
    for i in range(10):
        a = a0 + i * math.pi / 5
        c, s = math.cos(a), math.sin(a)
        p.setPen(QPen(col, w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(c * r * 0.3, s * r * 0.3), QPointF(c * r * 0.8, s * r * 0.8))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 230) if i % 2 else col)
        p.drawEllipse(QPointF(c * r, s * r), w * 0.9, w * 0.9)


def _floppy(p, r, col, pen, _seed):
    """A floppy disk: its label and metal shutter."""
    path = QPainterPath(QPointF(-r * 0.85, -r * 0.85))
    path.lineTo(r * 0.6, -r * 0.85)
    path.lineTo(r * 0.85, -r * 0.6)
    path.lineTo(r * 0.85, r * 0.85)
    path.lineTo(-r * 0.85, r * 0.85)
    path.closeSubpath()
    _fill(p, col, pen)
    p.drawPath(path)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#d4d4d4"))
    p.drawRect(QRectF(-r * 0.45, -r * 0.85, r * 0.85, r * 0.55))
    p.setBrush(col)
    p.drawRect(QRectF(r * 0.12, -r * 0.78, r * 0.17, r * 0.38))
    p.setBrush(QColor("#ffffff"))
    p.drawRect(QRectF(-r * 0.6, r * 0.05, r * 1.2, r * 0.7))


def _cursor(p, r, col, _pen, _seed):
    """The old arrow pointer, white with a black edge."""
    pts = [(-0.6, -1.0), (-0.6, 0.6), (-0.22, 0.25), (0.05, 0.9), (0.3, 0.8), (0.03, 0.15),
           (0.55, 0.15)]
    p.setPen(QPen(INK, max(1.0, r * 0.12), Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap,
                  Qt.PenJoinStyle.MiterJoin))
    p.setBrush(col)
    p.drawPolygon(QPolygonF([QPointF(r * x, r * y) for x, y in pts]))


def _text(p, r, col, text, family):
    f = QFont(family)
    f.setPixelSize(max(6, round(r * 2.2)))
    f.setBold(True)
    w = QFontMetricsF(f).horizontalAdvance(text)
    if w > r * 2.6:   # ("100": shrunk to fit)
        f.setPixelSize(max(6, round(r * 2.2 * r * 2.6 / w)))
    p.setFont(f)
    p.setPen(col)
    p.drawText(QRectF(-r * 2, -r * 1.5, r * 4, r * 3), Qt.AlignmentFlag.AlignCenter, text)


def _textbit(p, r, col, _pen, seed):
    family, bits = TEXT.get(hooks.theme_name(), ("Arial Black", ("!",)))
    _text(p, r, col, bits[seed % len(bits)], family)


_KINDS = {"heart": _heart, "star": _star, "sparkle": _sparkle, "petal": _petal,
          "snowflake": _snowflake, "bubble": _bubble, "leaf": _leaf, "bat": _bat,
          "ghost": _ghost, "digit": _digit, "wave": _wave, "cup": _cup, "flower": _flower,
          "peace": _peace, "trefoil": _trefoil, "drop": _drop, "coin": _coin,
          "diamond": _diamond, "moon": _moon, "thought": _thought, "text": _textbit,
          "book": _book, "bean": _bean, "splat": _splat, "sun": _sun, "ring": _ring,
          "triangle": _triangle, "bolt": _bolt, "cd": _cd, "pitchfork": _pitchfork,
          "flame": _flame, "check": _check, "spiral": _spiral, "fly": _fly,
          "flare": _flare, "confetti": _confetti, "balloon": _balloon, "skull": _skull,
          "floppy": _floppy, "cursor": _cursor, "burst": _burst}
