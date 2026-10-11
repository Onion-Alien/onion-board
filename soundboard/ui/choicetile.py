"""ChoiceTile and FoldPill. ChoiceTile: one choice of a few, as a fixed-size tile
(DESIGN.md: choices as tiles). A big icon and the name, the picked one filled with
the accent tint, ringed and ticked; optionally a live level bar along its foot (the
setup guide's mic). FoldPill: a small pill that opens and shuts something under it.

A QRadioButton underneath, painted by hand: tiles sharing a parent stay exclusive,
arrow keys move between them, and text() / isChecked() / click() work as usual."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QRadioButton, QSizePolicy

from soundboard import theme
from soundboard.ui import icons

RADIUS = 12   # a card's corners
HINT_PT = 8.5  # DESIGN.md Standard kit: Hint
FOOT_PAD = 10  # under the words / level bar of a stacked tile
PAD = 14      # inside the tile (DESIGN.md: card padding)


def wrap(text: str, fm: QFontMetrics, width: int, max_lines: int) -> list[str]:
    """`text` in lines that fit `width`, at most `max_lines`; the last one ends in an
    ellipsis when the rest doesn't fit (a long device name never spills over)."""
    lines: list[str] = []
    words = text.split()
    while words and len(lines) < max_lines:
        line = words.pop(0)
        while words and fm.horizontalAdvance(f"{line} {words[0]}") <= width:
            line = f"{line} {words.pop(0)}"
        if len(lines) == max_lines - 1 and words:   # the last line: the rest, cut short
            line = " ".join([line, *words])
            words = []
        lines.append(fm.elidedText(line, Qt.ElideRight, width))
    return lines


class ChoiceTile(QRadioButton):
    def __init__(self, text: str, icon: str, width: int, height: int,
                 stacked: bool = True, parent=None, *, title: str = "", sub: str = ""):
        """`stacked`: the icon over the name (devices); else beside it (short answers).
        `title` / `sub`: what to show instead of `text` (a device's product name, then
        its kind in small muted words); text() stays the full name."""
        super().__init__(text.replace("&", "&&"), parent)   # a lone & is a shortcut marker
        self.icon_name = icon
        self.title, self.sub = title, sub
        self.stacked = stacked
        self.level: float | None = None   # None: no level bar
        self._drawn_level = -1
        self.setFixedSize(width, height)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)
        self.setAccessibleName(text)
        self._keyboard = False   # focus came from the keyboard: show the focus ring

    def focusInEvent(self, ev):
        if ev.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason):
            self._keyboard = True
        super().focusInEvent(ev)

    def keyPressEvent(self, ev):   # arrows move between tiles: the ring goes with them
        self._keyboard = True
        super().keyPressEvent(ev)

    def mousePressEvent(self, ev):
        self._keyboard = False
        super().mousePressEvent(ev)

    def _ring(self) -> bool:
        return self._keyboard and self.hasFocus()

    def sizeHint(self) -> QSize:
        return self.size()

    def hitButton(self, pos) -> bool:   # the whole tile, not just a radio's dot and text
        return self.rect().contains(pos)

    def set_level(self, level: float | None):
        """The live level (linear peak, 0-1) to show along the foot, or None for none.
        Fed many times a second: repaints only when the bar would change."""
        self.level = level
        px = -1 if level is None else round(self._level_frac() * (self.width() - 2 * PAD))
        if px != self._drawn_level:
            self._drawn_level = px
            self.update()

    def _level_frac(self) -> float:
        db = 20 * math.log10(max(self.level or 0.0, 1e-5))
        return min(1.0, max(0.0, (db + 50) / 50))   # as widgets.Meter: -50 dB to 0

    def paintEvent(self, ev):
        t = theme.T
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on, hover = self.isChecked(), self.underMouse()
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(t["card_hi"] if hover and not on else t["panel"]))
        p.drawRoundedRect(r, RADIUS, RADIUS)
        if on:   # the accent tint and ring
            tint = QColor(t["accent"])
            tint.setAlpha(40)
            p.setBrush(tint)
            p.drawRoundedRect(r, RADIUS, RADIUS)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(t["accent"]), 2))
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), RADIUS - 1, RADIUS - 1)
        elif self._ring():   # the keyboard's ring
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(t["text"]), 1.5, Qt.DotLine))
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), RADIUS - 1, RADIUS - 1)
        if on and self._ring():
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(t["text_hi"]), 1, Qt.DotLine))
            p.drawRoundedRect(r.adjusted(4, 4, -4, -4), RADIUS - 4, RADIUS - 4)

        text = self.title or self.text().replace("&&", "&")
        f = self.font()
        f.setWeight(f.Weight.DemiBold if on else f.Weight.Normal)
        p.setFont(f)
        p.setPen(QColor(t["text_hi"] if on else t["text"]))
        colour = "accent" if on else "muted"
        foot = 8 if self.level is not None else 0   # room for the level bar
        if self.stacked:
            size = 24
            pm = icons.icon(self.icon_name, colour).pixmap(QSize(size, size),
                                                            self.devicePixelRatioF())
            small = QFont(self.font())
            small.setPointSizeF(HINT_PT)
            sub_h = QFontMetrics(small).height() if self.sub else 0
            fm = QFontMetrics(p.font())
            bottom = self.height() - FOOT_PAD - foot
            room = max(1, int((bottom - 12 - size - 6 - sub_h) // fm.lineSpacing()))
            lines = wrap(text, fm, self.width() - 20, room)
            # icon, words and kind centred as one block: no band under a short name
            block = size + 6 + len(lines) * fm.lineSpacing() + sub_h
            y0 = max(10.0, (bottom - block) / 2 + 2)
            p.drawPixmap(round((self.width() - size) / 2), round(y0), pm)
            words = QRectF(10, y0 + size + 6, self.width() - 20, len(lines) * fm.lineSpacing())
            y = words.top()
            for line in lines:
                p.drawText(QRectF(words.left(), y, words.width(), fm.lineSpacing()),
                           Qt.AlignHCenter | Qt.AlignTop, line)
                y += fm.lineSpacing()
            if self.sub:
                p.setFont(small)
                p.setPen(QColor(t["muted"]))
                line = QRectF(words.left(), y, words.width(), sub_h)
                p.drawText(line, Qt.AlignHCenter | Qt.AlignTop,
                           QFontMetrics(small).elidedText(self.sub, Qt.ElideRight,
                                                          int(line.width())))
        else:
            size = 22
            pm = icons.icon(self.icon_name, colour).pixmap(QSize(size, size),
                                                            self.devicePixelRatioF())
            rtl = self.isRightToLeft()
            x = self.width() - PAD - size if rtl else PAD
            p.drawPixmap(round(x), round((self.height() - size) / 2), pm)
            left = PAD if rtl else PAD + size + 12
            words = QRectF(left, 0, self.width() - PAD - size - 12 - PAD - 22, self.height())
            align = (Qt.AlignRight if rtl else Qt.AlignLeft) | Qt.AlignVCenter | Qt.TextWordWrap
            p.drawText(words, align, text)

        if on:   # the tick badge in the top corner (the reading side's end)
            d = 18
            x = PAD - 6 if self.isRightToLeft() else self.width() - PAD + 6 - d
            badge = QRectF(x, PAD - 6, d, d)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t["accent"]))
            p.drawEllipse(badge)
            tick = QPainterPath(QPointF(badge.left() + 5, badge.center().y()))
            tick.lineTo(badge.left() + 8, badge.center().y() + 3)
            tick.lineTo(badge.right() - 4.5, badge.center().y() - 3.5)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(t["on_accent"]), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(tick)

        if self.level is not None:   # the live level along the foot
            track = QRectF(PAD, self.height() - FOOT_PAD - 4, self.width() - 2 * PAD, 4)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t["card_hi"]))
            p.drawRoundedRect(track, 2, 2)
            frac = self._level_frac()
            if frac > 0:
                p.setBrush(QColor(t["accent"]))
                p.drawRoundedRect(QRectF(track.left(), track.top(), track.width() * frac, 4),
                                  2, 2)


class FoldPill(QAbstractButton):
    """A small rounded pill that opens and shuts something under it: an icon, a few
    words and a chevron right after them, only as wide as that (DESIGN.md: rare
    things a click away). Open, it takes the accent tint and the chevron points up."""
    H = 32
    PADX = 12

    def __init__(self, text: str, icon: str, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.icon_name = icon
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(text)
        self.toggled.connect(lambda __: self.update())
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def _font(self) -> QFont:
        f = QFont(self.font())
        f.setWeight(QFont.Weight.DemiBold)
        return f

    def sizeHint(self) -> QSize:
        w = QFontMetrics(self._font()).horizontalAdvance(self.text())
        return QSize(self.PADX + 18 + 8 + w + 6 + 16 + self.PADX, self.H)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, ev):
        t = theme.T
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        on = self.isChecked()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(t["btn_hover"] if self.underMouse() else t["btn"]))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        if on:
            tint = QColor(t["accent"])
            tint.setAlpha(45)
            p.setBrush(tint)
            p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        if self.hasFocus():
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(t["accent"]), 1.5))
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), r.height() / 2 - 1, r.height() / 2 - 1)
        rtl = self.isRightToLeft()
        dpr = self.devicePixelRatioF()
        lead = icons.icon(self.icon_name, "accent").pixmap(QSize(18, 18), dpr)
        chev = icons.icon("fold_up" if on else "fold_open", "text").pixmap(QSize(16, 16), dpr)
        f = self._font()
        p.setFont(f)
        tw = QFontMetrics(f).horizontalAdvance(self.text())
        x = self.PADX
        parts = [(lead, 18), ("text", tw), (chev, 16)]   # 8 px after the icon, 6 before ⌄
        gaps = [8, 6]
        if rtl:
            parts.reverse()
            gaps.reverse()
        for i, (part, w) in enumerate(parts):
            if part == "text":
                p.setPen(QColor(t["text_hi"]))
                p.drawText(QRectF(x, 0, w + 2, self.height()), Qt.AlignVCenter, self.text())
            else:
                p.drawPixmap(round(x), round((self.height() - w) / 2), part)
            x += w + (gaps[i] if i < len(gaps) else 0)
