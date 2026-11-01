"""What flies out of Bun's headphones besides notes, by theme: hearts for Barbie, petals
for Cherry Blossom, gold stars for Royal... (`pick`, `paint`). A theme that isn't in
MIXES throws notes only. Used by `paint_note` (ui/bun/bunbits.py)."""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF

from soundboard.style import hooks
from soundboard.ui.bun.bunny import INK

# theme -> what he throws, (kind, colour) each as likely; "note" keeps a note in the mix
MIXES: dict[str, tuple[tuple[str, str], ...]] = {
    "Barbie": (("heart", "#e8006e"), ("heart", "#ffffff"), ("note", "#c4005c"),
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
                  ("sparkle", "#ff8cc6")),
    "Hacker": (("digit", "#3cff6e"), ("digit", "#28c850"), ("note", "#3cff6e"),
               ("digit", "#9bffb5")),
}
# (these get their colour pushed to stand out like a note's; the rest keep theirs and an
# outline does that)
LIKE_NOTES = {"note", "digit", "snowflake", "bubble", "sparkle"}


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


_KINDS = {"heart": _heart, "star": _star, "sparkle": _sparkle, "petal": _petal,
          "snowflake": _snowflake, "bubble": _bubble, "leaf": _leaf, "bat": _bat,
          "ghost": _ghost, "digit": _digit}
