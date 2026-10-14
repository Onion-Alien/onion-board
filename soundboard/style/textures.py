"""The themes' see-through textures (Settings: Textured), shared by Onion Board and
Onion Watch. Each theme names one with its `texture` token; texture_image() draws a
tile in a theme's colours.

Part of the style kit (see __init__.py): imports nothing from either app.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen

from . import hooks
from .palettes import is_light_colour


def _ink(colour: str, alpha: float) -> QColor:
    c = QColor(colour)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def _carbon_tile(p: QPainter, size: int, light: QColor, dark: QColor) -> None:
    """2x2 twill weave: each cell a tow of fibres shaded across its width, the
    neighbouring cells turned 90 degrees, so it tiles into carbon fibre."""
    c = size / 2
    for i in range(2):
        for j in range(2):
            x, y = i * c, j * c
            if (i + j) % 2:
                g = QLinearGradient(QPointF(x, y), QPointF(x + c, y))
            else:
                g = QLinearGradient(QPointF(x, y), QPointF(x, y + c))
            g.setColorAt(0.0, dark)
            g.setColorAt(0.5, light)
            g.setColorAt(1.0, dark)
            p.fillRect(QRectF(x, y, c, c), g)


# Each texture: its tile size and which colour it draws with by default ("lift" = the
# theme's brightest text colour, "shade" = black, or a theme token like "accent2").
TEXTURES = {
    "carbon": (14, "lift"), "scanlines": (3, "shade"), "grid": (24, "accent2"),
    "dots": (12, "lift"), "diagonal": (12, "lift"),
    "ruled": (24, "accent2"), "waves": (32, "accent"),
    "crosshatch": (8, "lift"), "diamond": (20, "accent"), "scales": (24, "accent"),
    "embers": (96, "accent2"), "petals": (64, "accent2"), "dither": (2, "shade"),
    "halftone": (10, "shade"), "frost": (64, "lift"),
}
TEXTURE_TILE = {k: v[0] for k, v in TEXTURES.items()}


def texture_image(kind: str, tk: dict[str, str] | None = None, size: int | None = None) -> QImage:
    """One see-through tile of theme texture `kind`, in theme `tk`'s colours. It lies
    over a card's own colour, so hover and the theme's shades still show through, and
    every mark stays faint enough for text on top to read."""
    tk = tk or hooks.palette()
    size = size or TEXTURES.get(kind, (14, ""))[0]
    ink_key = tk.get("texture_ink") or TEXTURES.get(kind, (0, "lift"))[1]
    light = is_light_colour(tk["panel"])
    ink = ("#000000" if ink_key == "shade" or (ink_key == "lift" and light)
           else tk["text_hi"] if ink_key == "lift" else tk.get(ink_key, tk["accent"]))
    k = float(tk.get("texture_strength", 1.0))   # a theme can turn its texture up or down
    a = (lambda x: _ink(ink, x * k))
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    import random
    rng = random.Random(7)   # the same specks every time, so tiles meet without a seam
    if kind == "carbon":
        _carbon_tile(p, size, _ink("#ffffff", 0.07 * k), _ink("#000000", 0.30 * k))
    elif kind == "scanlines":   # a darker row every third pixel, like an old CRT
        p.fillRect(QRectF(0, 0, size, 1), a(0.28))
    elif kind == "grid":        # one lit line along the top and left of each tile
        p.fillRect(QRectF(0, 0, size, 1), a(0.13))
        p.fillRect(QRectF(0, 0, 1, size), a(0.13))
    elif kind == "dots":
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(a(0.10))
        r = size * 0.14
        for c in (0.25, 0.75):
            p.drawEllipse(QPointF(size * c, size * c), r, r)
    elif kind == "halftone":    # comic-book print dots
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(a(0.09))
        for cx, cy in ((0, 0), (size, 0), (0, size), (size, size), (size / 2, size / 2)):
            p.drawEllipse(QPointF(cx, cy), size * 0.2, size * 0.2)
    elif kind in ("frost", "embers"):   # fixed-seed specks
        n, alpha = {"frost": (220, 0.10), "embers": (40, 0.30)}[kind]
        for _ in range(n):
            x, y = rng.randrange(size), rng.randrange(size)
            img.setPixelColor(x, y, a(alpha * rng.uniform(0.4, 1.0)))
    elif kind == "diagonal":    # thin pinstripes, bottom-left to top-right
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(a(0.07), 1.5))
        for off in (-size, 0, size):
            p.drawLine(QPointF(off, size), QPointF(off + size, 0))
    elif kind == "crosshatch":
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(a(0.045), 1))
        for off in (-size, 0, size):
            p.drawLine(QPointF(off, size), QPointF(off + size, 0))
            p.drawLine(QPointF(off, 0), QPointF(off + size, size))
    elif kind == "ruled":       # notebook paper: one faint line per text row
        p.fillRect(QRectF(0, size - 1, size, 1), a(0.16))
    elif kind == "waves":
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(a(0.08), 1.2))
        import math
        path = QPainterPath(QPointF(0, size / 2))
        for x in range(1, size + 1):
            path.lineTo(QPointF(x, size / 2 + math.sin(x / size * 2 * math.pi) * size / 6))
        p.drawPath(path)
    elif kind == "diamond":     # a thin lattice, like damask wallpaper
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(a(0.08), 1))
        h = size / 2
        diamond = QPainterPath(QPointF(h, 0))
        for pt in ((size, h), (h, size), (0, h), (h, 0)):
            diamond.lineTo(QPointF(*pt))
        p.drawPath(diamond)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(a(0.12))
        p.drawEllipse(QPointF(h, h), 1.2, 1.2)
    elif kind == "scales":      # overlapping rings, like the layers of an onion
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(a(0.08), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        h = size / 2
        for cx, cy in ((0, h), (size, h), (h, size), (h, 0), (0, -h + size * 2), (size, h * 3)):
            for r in (h * 0.95, h * 0.6):
                p.drawEllipse(QPointF(cx, cy), r, r)
    elif kind == "petals":      # a few soft blossoms scattered across the tile
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        for _ in range(5):
            x, y, r = rng.uniform(4, size - 4), rng.uniform(4, size - 4), rng.uniform(1.5, 3)
            p.setBrush(a(0.20))
            p.drawEllipse(QPointF(x, y), r * 1.3, r)
    elif kind == "dither":      # a 1-pixel checkerboard, like 256-colour dithering
        img.setPixelColor(0, 0, a(0.10))
        img.setPixelColor(1, 1, a(0.10))
    p.end()
    return img
