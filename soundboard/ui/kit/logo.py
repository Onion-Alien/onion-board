"""The app logo: the onion mark (a jack-o'-lantern in Halloween), the app icon and its
pictures."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPixmap, QPolygonF, QRadialGradient)

from soundboard.style.palettes import THEMES


# a theme with logo="lantern" (Halloween) carves the onion into a jack-o'-lantern. Picked
# by its accent pair, so every cache of the mark (keyed by its two colours) stays right.
_LANTERN = {(t["accent"].lower(), t["accent2"].lower()) for t in THEMES.values()
            if t.get("logo") == "lantern"}


def _bulb(pt, w: float) -> QPainterPath:
    """The onion's outline on the caller's `pt` grid, w = half-width at its widest."""
    path = QPainterPath(pt(0, 0.27))
    path.cubicTo(pt(w * 0.25, 0.36), pt(w, 0.42), pt(w, 0.59))
    path.cubicTo(pt(w, 0.74), pt(w * 0.55, 0.81), pt(0, 0.81))
    path.cubicTo(pt(-w * 0.55, 0.81), pt(-w, 0.74), pt(-w, 0.59))
    path.cubicTo(pt(-w, 0.42), pt(-w * 0.25, 0.36), pt(0, 0.27))
    return path


def _sprout(pt) -> QPainterPath:
    """Two leaves curling out of the onion's neck."""
    leaf = QPainterPath(pt(0, 0.29))
    leaf.cubicTo(pt(0, 0.20), pt(-0.04, 0.15), pt(-0.12, 0.12))
    leaf.moveTo(pt(0, 0.27))
    leaf.cubicTo(pt(0.01, 0.19), pt(0.05, 0.14), pt(0.10, 0.10))
    return leaf


def _paint_lantern(p: QPainter, x0: float, y0: float, s: float, inset: float) -> None:
    """The mark as a jack-o'-lantern: the onion's shape on a night-sky tile, pumpkin
    orange with darker ribs where its layers are, a carved face glowing inside."""
    body = QPainterPath()
    body.addRoundedRect(QRectF(x0 + s * inset, y0 + s * inset, s * (1 - 2 * inset),
                               s * (1 - 2 * inset)), s * 0.26, s * 0.26)
    sky = QLinearGradient(QPointF(x0, y0), QPointF(x0 + s, y0 + s))
    sky.setColorAt(0.0, QColor("#3b2152"))
    sky.setColorAt(1.0, QColor("#120a18"))
    p.fillPath(body, sky)
    cx = x0 + s * 0.5

    def pt(dx, dy):
        return QPointF(cx + dx * s, y0 + dy * s)

    halo = QRadialGradient(pt(0, 0.6), s * 0.45)   # the candle's light on the night
    halo.setColorAt(0.0, QColor(255, 140, 40, 110))
    halo.setColorAt(1.0, QColor(255, 140, 40, 0))
    p.fillPath(body, halo)
    stem = QPen(QColor("#6cc04a"), max(1.2, s * 0.055))
    stem.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(stem)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(_sprout(pt))
    skin = QRadialGradient(pt(-0.06, 0.52), s * 0.36)
    skin.setColorAt(0.0, QColor("#ffb347"))
    skin.setColorAt(0.6, QColor("#ff7518"))
    skin.setColorAt(1.0, QColor("#c2440a"))
    p.setPen(Qt.PenStyle.NoPen)
    p.fillPath(_bulb(pt, 0.31), skin)
    if s >= 20:   # ribs: the onion's layers (one at every size, like paint_logo's)
        rib = QPen(QColor(150, 50, 0, 150), max(1.0, s * 0.026))
        p.setPen(rib)
        p.drawPath(_bulb(pt, 0.15))
    glow = QLinearGradient(pt(0, 0.48), pt(0, 0.76))   # candlelight through the face
    glow.setColorAt(0.0, QColor("#fff6a8"))
    glow.setColorAt(1.0, QColor("#ffb020"))
    face = QPainterPath()
    for sx in (-1, 1):   # two triangle eyes
        face.addPolygon(QPolygonF([pt(sx * 0.17, 0.585), pt(sx * 0.05, 0.585),
                                   pt(sx * 0.10, 0.48)]))
        face.closeSubpath()
    mouth = [(-0.20, 0.635), (-0.12, 0.665), (-0.08, 0.635), (-0.04, 0.665), (0.04, 0.665),
             (0.08, 0.635), (0.12, 0.665), (0.20, 0.635), (0.14, 0.725), (0.06, 0.755),
             (0.03, 0.725), (-0.03, 0.725), (-0.06, 0.755), (-0.14, 0.725)]
    face.addPolygon(QPolygonF([pt(dx, dy) for dx, dy in mouth]))
    face.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.fillPath(face, glow)


def paint_logo(p: QPainter, rect: QRectF, c1: str, c2: str, inset: float = 0.04):
    """The Onion Board mark: a gradient squircle holding an onion whose layers
    are drawn as sound-wave arcs — onion + soundboard in one shape. (Halloween's
    colours carve it into a jack-o'-lantern: _LANTERN.)"""
    s = rect.width()
    if (c1.lower(), c2.lower()) in _LANTERN:
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        _paint_lantern(p, rect.left(), rect.top(), s, inset)
        p.restore()
        return
    x0, y0 = rect.left(), rect.top()
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    # body
    g = QLinearGradient(QPointF(x0, y0), QPointF(x0 + s, y0 + s))
    g.setColorAt(0.0, QColor(c1))
    g.setColorAt(1.0, QColor(c2))
    body = QPainterPath()
    body.addRoundedRect(QRectF(x0 + s * inset, y0 + s * inset, s * (1 - 2 * inset),
                               s * (1 - 2 * inset)), s * 0.26, s * 0.26)
    p.fillPath(body, g)
    # soft top highlight
    hi = QLinearGradient(QPointF(x0, y0), QPointF(x0, y0 + s * 0.6))
    hi.setColorAt(0.0, QColor(255, 255, 255, 60))
    hi.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillPath(body, hi)
    # the onion is white, or near-black on light accents (e.g. Toxic's lime) so it stays legible
    a, b = QColor(c1), QColor(c2)
    lum = sum((0.299 * q.red() + 0.587 * q.green() + 0.114 * q.blue()) / 2 for q in (a, b))
    fg = QColor("#0b1a10") if lum > 165 else QColor("white")
    cx = x0 + s * 0.5

    def pt(dx, dy):   # offsets in units of s, from the top-centre of the icon
        return QPointF(cx + dx * s, y0 + dy * s)

    # sprout: two leaves curling out of the neck
    pen = QPen(fg, max(1.2, s * 0.05))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(_sprout(pt))
    # bulb
    p.setPen(Qt.PenStyle.NoPen)
    p.fillPath(_bulb(pt, 0.29), fg)
    # layers: an inner outline in the brand gradient, reading like a sound wave. One at
    # every size, so the taskbar's bigger icon is the same mark as the header's
    if s >= 20:
        lp = QPen(g, max(1.0, s * 0.032))
        lp.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(lp)
        p.drawPath(_bulb(pt, 0.13))
    # roots
    if s >= 32:
        rp = QPen(fg, max(1.0, s * 0.03))
        rp.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(rp)
        for dx in (-0.06, 0.0, 0.06):
            p.drawLine(pt(dx * 0.6, 0.81), pt(dx, 0.87))
    p.restore()


BRAND = ("#7c5cff", "#ff4d8d")   # the app icon keeps its own colours in every theme


# Icons Windows draws (taskbar, exe, shortcuts) fill their square edge to edge, like other apps'
# do; with the in-app 4% margin the tile looked smaller and a touch low beside them.
ICON_INSET = 0.01


def logo_pixmap(size: int, c1: str | None = None, c2: str | None = None,
                inset: float = 0.04) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    paint_logo(p, QRectF(0, 0, size, size), c1 or BRAND[0], c2 or BRAND[1], inset)
    p.end()
    return pm


def app_icon(c1: str | None = None, c2: str | None = None) -> QIcon:
    icon = QIcon()
    for sz in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(logo_pixmap(sz, c1, c2, ICON_INSET))
    return icon


def logo_image(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    paint_logo(p, QRectF(0, 0, size, size), *BRAND, inset=ICON_INSET)
    p.end()
    return img
