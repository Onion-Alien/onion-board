"""Bun's speech bubble, the same everywhere he talks (his widget, the games, Bun mode): a
white bubble with the theme's colour round it and a solid drop under it, and a short fat
tail toward his mouth that never stretches into a line. `beside` puts it close by his
face, `wrap` breaks a longer line, `draw` paints it. `body` is the rect his 100 x 120
drawing canvas is painted into."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen

from soundboard.ui.bun.bunny import H, INK
from soundboard.ui.kit import theme

PAD = 10    # the text's room either side
GAP = 12.0  # between his side and the bubble (the tail bridges it)


def mouth(body: QRectF) -> QPointF:
    s = body.height() / H
    return QPointF(body.left() + 50 * s, body.top() + 77 * s)


def tail_len(bh: float) -> float:
    return max(7.0, min(15.0, bh * 0.5))


def side_room(body: QRectF, width: float) -> float:
    """The most room beside him, on either side, for the text."""
    s = body.height() / H
    return max(width - 2 - (body.left() + 97 * s + GAP), body.left() + 3 * s - GAP - 2) - 2 * PAD


def wrap(fm: QFontMetrics, text: str, fit: float, most: int = 3) -> list[str]:
    """`text` in as few lines (up to `most`) as fit in `fit`, broken at spaces into lines
    of even length; still too wide: the `most` lines anyway."""
    words = text.split(" ")
    for n in range(1, min(most, len(words)) + 1):
        lines = _even(words, n)
        if max(fm.horizontalAdvance(t) for t in lines) <= fit:
            return lines
    return _even(words, min(most, len(words)))


def _even(words: list[str], n: int) -> list[str]:
    """`words` in `n` lines of about the same length (in letters)."""
    goal = len(" ".join(words)) / n
    lines, cur = [], ""
    for i, w in enumerate(words):
        left = len(words) - i   # (each line still to come needs a word)
        if cur and len(lines) < n - 1 and (len(cur) + 1 + len(w) / 2 > goal
                                            or left <= n - 1 - len(lines)):
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}" if cur else w
    return lines + [cur]


def beside(body: QRectF, bw: float, bh: float, width: float, clear: float = 97) -> QRectF:
    """Close by his face, a little above his mouth: on his right (past the headphone cup)
    if it fits, else on his left. No room either side: above his head. `clear`: where his
    right side ends, in canvas units (further out when he holds a bat)."""
    s = body.height() / H
    gap = tail_len(bh) * 0.8
    y = body.top() + 66 * s - bh * 0.62
    right = body.left() + clear * s + gap
    left = body.left() + 3 * s - gap - bw
    if right + bw <= width - 2:
        x = right
    elif left >= 2:
        x = left
    else:
        x = max(2.0, min(body.left() + 58 * s, width - bw - 2))
        y = body.top() + 20 * s - bh - gap
    return QRectF(x, max(2.0, y), bw, bh)


def _shape(box: QRectF, body: QRectF, r: float) -> QPainterPath:
    """The bubble and its tail, one outline: a fat comma on the side nearest his mouth."""
    m = mouth(body)
    bh = box.height()
    half = max(5.0, min(10.0, bh * 0.26))
    if m.x() < box.left() or m.x() > box.right():   # beside him: from its side, low
        sign = -1 if m.x() < box.left() else 1
        edge = box.left() + 3 if sign < 0 else box.right() - 3
        by = min(box.bottom() - r * 0.9, max(box.top() + bh * 0.55, m.y()))
        b1, b2 = QPointF(edge, by - half), QPointF(edge, by + half)
        dx, dy = sign * 1.0, 0.55
    else:                                            # above him: from its bottom
        bx = max(box.left() + r, min(box.right() - r, m.x()))
        b1, b2 = QPointF(bx - half, box.bottom() - 3), QPointF(bx + half, box.bottom() - 3)
        dx, dy = (m.x() - bx) * 0.02, 1.0
    n = math.hypot(dx, dy)
    base = (b1 + b2) / 2
    tip = base + QPointF(dx / n, dy / n) * (tail_len(bh) + 3)
    along = tip - base
    tail = QPainterPath(b1)
    # (the near side bows out, the far side curls in)
    tail.quadTo(base + along * 0.35 + (b1 - base) * 0.9, tip)
    tail.quadTo(base + along * 0.55 + (b2 - base) * 0.1, b2)
    tail.closeSubpath()
    path = QPainterPath()
    path.addRoundedRect(box, r, r)
    return path.united(tail)


def draw(p: QPainter, box: QRectF, text: str, body: QRectF,
         flags: Qt.AlignmentFlag | Qt.TextFlag = Qt.AlignmentFlag.AlignCenter,
         edge: QColor | None = None, radius: float | None = None):
    """The bubble `box` with `text` in it; `edge` instead of the theme's colour round it."""
    r = min(box.height() / 2, 16.0) if radius is None else radius
    shape = _shape(box, body, r)
    k = max(1.0, box.height() / 26)
    col = QColor(edge) if edge is not None else QColor(theme.T["accent"])
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(col.darker(140))   # the solid drop under it
    p.drawPath(shape.translated(0, 3 * k))
    p.setPen(QPen(col, 2.4 * k, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    p.setBrush(QColor("#ffffff"))
    p.drawPath(shape)
    p.setPen(INK)
    p.drawText(box.adjusted(PAD - 2, 0, -PAD + 2, 0), flags, text)
