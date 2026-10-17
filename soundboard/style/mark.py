"""The Onion Alien mark family: one onion drawn the same way for both apps, in two
finishes. Onion Board's onion is cut into flowing layers that read as sound; Onion
Watch's opens round one big eye. Part of the style kit (see __init__.py), so both
apps draw it from the same lines.

    signal  the onion in white on a tile of the app's two colours
    night   the onion in white on a dark tile, its layers lit in the two colours

Under 24 px the details that would blur are dropped (one layer, no roots, a simpler
sprout), so a 16 px tray icon stays a clear onion.

    paint_mark(p, rect, "#7c5cff", "#ff4d8d", kind="board", finish="signal")
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QLinearGradient, QPainter, QPainterPath,
                           QPainterPathStroker, QPen, QTransform)

FINISHES = ("signal", "night")
NIGHT = ("#1d1b33", "#0f0e1c")   # the dark finish's tile, top to bottom
EYE_Y = 0.60      # Watch's eye: its centre, in mark heights
EYE_R = 0.128     # ... and its iris's radius
GOLD = "#ffc93c"
PUPIL = "#16263a"
RADIUS = 0.26     # the tile's corners, in mark widths
K = 1000.0        # the shapes are built this big: Qt's path maths flattens curves to
                  # lines at a fixed size, so on a unit square they'd come out angular
_BIG = QTransform().scale(K, K)


def _bulb(w: float, top: float = 0.255, bottom: float = 0.865, mid: float = 0.6,
          neck: float = 0.075) -> QPainterPath:
    """An onion's outline on the unit square: a narrow neck at `top`, widest (`w`
    either side of the middle) at `mid`, tapering to a soft point at `bottom`."""
    path = QPainterPath(QPointF(0.5, top))
    path.cubicTo(QPointF(0.5 + neck, top + 0.08), QPointF(0.5 + w, mid - 0.18),
                 QPointF(0.5 + w, mid))
    path.cubicTo(QPointF(0.5 + w, mid + 0.17), QPointF(0.5 + neck * 1.2, bottom - 0.06),
                 QPointF(0.5, bottom))
    path.cubicTo(QPointF(0.5 - neck * 1.2, bottom - 0.06), QPointF(0.5 - w, mid + 0.17),
                 QPointF(0.5 - w, mid))
    path.cubicTo(QPointF(0.5 - w, mid - 0.18), QPointF(0.5 - neck, top + 0.08),
                 QPointF(0.5, top))
    path.closeSubpath()
    return path


def _sprout(small: bool) -> QPainterPath:
    """Two leaves curling up and out of the neck (a single V when tiny)."""
    path = QPainterPath()
    for sx in (-1, 1):
        def m(x, y, sx=sx):
            return QPointF(0.5 + sx * (x - 0.5), y)
        leaf = QPainterPath(m(0.5, 0.3))
        if small:
            leaf.cubicTo(m(0.47, 0.21), m(0.42, 0.15), m(0.35, 0.115))
            leaf.cubicTo(m(0.36, 0.2), m(0.43, 0.26), m(0.5, 0.3))
        else:
            leaf.cubicTo(m(0.49, 0.2), m(0.45, 0.125), m(0.365, 0.095))
            leaf.cubicTo(m(0.345, 0.18), m(0.405, 0.265), m(0.5, 0.3))
        leaf.closeSubpath()
        path = path.united(leaf)
    return path


def _board_layers(small: bool) -> list[QPainterPath]:
    """Board's layer lines, from the neck to the tip: they sway like a sound wave."""
    centre = QPainterPath(QPointF(0.5, 0.36))
    centre.cubicTo(QPointF(0.6, 0.47), QPointF(0.4, 0.61), QPointF(0.5, 0.8))
    if small:
        return [centre]
    left = QPainterPath(QPointF(0.465, 0.355))
    left.cubicTo(QPointF(0.33, 0.45), QPointF(0.3, 0.66), QPointF(0.45, 0.8))
    right = QPainterPath(QPointF(0.535, 0.355))
    right.cubicTo(QPointF(0.69, 0.45), QPointF(0.71, 0.67), QPointF(0.55, 0.8))
    return [left, centre, right]


def _watch_hollow() -> QPainterPath:
    """The almond Watch's eye sits in."""
    return _bulb(0.175, top=0.4, bottom=0.8, mid=EYE_Y, neck=0.05)


def _stroke(path: QPainterPath, width: float) -> QPainterPath:
    st = QPainterPathStroker()
    st.setWidth(width)
    st.setCapStyle(Qt.PenCapStyle.RoundCap)
    st.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return st.createStroke(path)


def shapes(kind: str, px: float) -> dict:
    """The mark's pieces on a K x K square, for a mark `px` pixels wide: `onion`
    (the white), `cuts` (lines through it the tile shows in), `glow` (where the night
    finish lights its colours) and `roots`."""
    small = px < 24
    big = _BIG.map
    onion = big(_bulb(0.315 if kind == "watch" else 0.3)).united(big(_sprout(small)))
    cut_w = K * (0.06 if small else 0.046)
    if kind == "watch":
        hollow = big(_watch_hollow())
        ring = QTransform().translate(0.5, EYE_Y).scale(1.38, 1.24).translate(-0.5, -EYE_Y)
        layer = big(ring.map(_watch_hollow()))
        cuts = [hollow] if small else [hollow, _stroke(layer, cut_w)]
        glow = [] if small else [layer]
    else:
        lines = [big(line) for line in _board_layers(small)]
        cuts = [_stroke(line, cut_w) for line in lines]
        glow = lines
    for cut in cuts:
        onion = onion.subtracted(cut)
    roots = []
    if px >= 40:
        for dx in (-0.045, 0.0, 0.045):
            root = QPainterPath(QPointF(0.5 + dx * 0.5, 0.85))
            root.lineTo(0.5 + dx, 0.905)
            roots.append(big(root))
    return {"onion": onion, "cuts": cuts, "glow": glow, "roots": roots, "small": small}


def _ink(c1: str, c2: str) -> QColor:
    """White, or near-black on very light colours (Toxic's lime) so it stays legible."""
    a, b = QColor(c1), QColor(c2)
    lum = sum((0.299 * q.red() + 0.587 * q.green() + 0.114 * q.blue()) / 2 for q in (a, b))
    return QColor("#0b1a10") if lum > 165 else QColor("white")


def paint_mark(p: QPainter, rect: QRectF, c1: str, c2: str, kind: str = "board",
               finish: str = "signal", inset: float = 0.04, awake: bool = True,
               look: float = 0.0, tile: bool = True):
    """Paint the mark into the square `rect`: `kind` "board" or "watch", `finish`
    "signal" or "night", in the colours `c1` -> `c2`. `inset`: the tile's margin, in
    mark widths. Watch's `awake=False` shuts its eye (a lid and lashes) and `look`
    moves the eye that far sideways (mark widths). `tile=False`: the onion alone."""
    s = rect.width()
    x0, y0 = rect.left(), rect.top()
    night = finish == "night"
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    body = QPainterPath()
    side = s * (1 - 2 * inset)
    body.addRoundedRect(QRectF(x0 + s * inset, y0 + s * inset, side, side),
                        s * RADIUS, s * RADIUS)
    g = QLinearGradient(QPointF(x0, y0), QPointF(x0 + s, y0 + s))
    g.setColorAt(0.0, QColor(c1))
    g.setColorAt(1.0, QColor(c2))
    if tile:
        if night:
            dark = QLinearGradient(QPointF(x0, y0), QPointF(x0, y0 + s))
            dark.setColorAt(0.0, QColor(NIGHT[0]))
            dark.setColorAt(1.0, QColor(NIGHT[1]))
            p.fillPath(body, dark)
            if s >= 20:   # a hairline of the colours round the edge: it holds on dark
                edge = QColor(c1)
                edge.setAlpha(110)
                p.setPen(QPen(edge, max(1.0, s * 0.012)))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(body)
        else:
            p.fillPath(body, g)
        hi = QLinearGradient(QPointF(x0, y0), QPointF(x0, y0 + s * 0.6))
        hi.setColorAt(0.0, QColor(255, 255, 255, 34 if night else 60))
        hi.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillPath(body, hi)
    fg = QColor("white") if night or not tile else _ink(c1, c2)
    parts = shapes(kind, s)
    unit = QTransform().translate(x0, y0).scale(s / K, s / K)
    if night and parts["glow"]:   # the colours lit along the layers, under the white
        p.setPen(QPen(g, s * (0.062 if parts["small"] else 0.036), Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for line in parts["glow"]:
            p.drawPath(unit.map(line))
    p.fillPath(unit.map(parts["onion"]), fg)
    if night and parts["glow"] and not parts["small"]:
        # (drawn again over the white's cut edges, thinner: a lit seam, not a gap)
        p.setPen(QPen(g, s * 0.022, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for line in parts["glow"]:
            p.drawPath(unit.map(line))
    if parts["roots"]:
        rp = QPen(fg, max(1.0, s * 0.028))
        rp.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(rp)
        for root in parts["roots"]:
            p.drawPath(unit.map(root))
    if kind == "watch":
        _eye(p, x0, y0, s, fg, awake, look)
    p.restore()


def _eye(p: QPainter, x0: float, y0: float, s: float, fg: QColor, awake: bool,
         look: float):
    def pt(x, y):
        return QPointF(x0 + x * s, y0 + y * s)

    r = s * EYE_R
    if awake:   # a gold iris, a pupil and a glint
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(GOLD))
        p.drawEllipse(pt(0.5 + look, EYE_Y), r, r)
        p.setBrush(QColor(PUPIL))
        p.drawEllipse(pt(0.5 + look * 1.25, EYE_Y), r * 0.55, r * 0.55)
        if s >= 24:
            p.setBrush(QColor("white"))
            p.drawEllipse(pt(0.5 + 0.04 + look * 1.25, EYE_Y - 0.04), r * 0.22, r * 0.22)
        return
    lp = QPen(fg, max(1.2, s * 0.04))   # asleep: a lid and three lashes
    lp.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(lp)
    p.setBrush(Qt.BrushStyle.NoBrush)
    lid = QPainterPath(pt(0.5 - 0.11, EYE_Y - 0.02))
    lid.quadTo(pt(0.5, EYE_Y + 0.07), pt(0.5 + 0.11, EYE_Y - 0.02))
    p.drawPath(lid)
    if s >= 24:
        for dx, dy in ((-0.06, 0.045), (0.0, 0.06), (0.06, 0.045)):
            p.drawLine(pt(0.5 + dx * 0.9, EYE_Y + dy - 0.025),
                       pt(0.5 + dx * 1.1, EYE_Y + dy + 0.02))
