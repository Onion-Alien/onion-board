"""Onion Board's own update at the rail's foot (ui/window/sidebar.py): a small card
open, a button with a filling ring shut."""
from __future__ import annotations

import math
import re

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QPushButton

from soundboard.ui.kit import theme
from soundboard.i18n import _
from soundboard.ui.kit import icons
from soundboard.ui.kit.pixels import snap_to_pixels
from soundboard.ui.window.onaircard import OutputBlock
from soundboard.ui.window.railsizes import BUTTON_W, ICON


class UpdateCard(QPushButton):
    """Onion Board's own update, at the rail's foot over the On Air card: open, a small
    card on the same keylines (its icon on the tab icons' centre line, its words on
    the card's text keyline) that says what's going on, with a thin bar while the new
    version downloads; shut (and mid), one rail button, its icon with a ring that
    fills as it downloads. `set_state` says what it shows; the window handles clicks.
    Its "Copy error" link (`copy`) is there after a download failed more than once."""

    TONE = {"available": "accent", "downloading": "accent", "ready": "ok_text",
            "failed": "warn_text"}
    GLYPH = {"available": "download", "downloading": "download", "ready": "reload",
             "failed": "warn"}
    TOP = 12              # the On Air card's padding
    BAR_H = 3             # the progress bar
    BAR_GAP = 6           # title to bar, and bar to the size under it
    RING = 28             # shut: the progress ring round the smaller icon
    RING_ICON = 14

    def __init__(self):
        super().__init__()
        self.setObjectName("railupdate")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.state, self.title, self.hint, self.tip = "available", "", "", ""
        self.pct: int | None = None
        self._card = True
        self._copy_on = False
        self.copy = QPushButton(_("Copy error"), self)
        self.copy.setObjectName("railupdatecopy")
        self.copy.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.copy.hide()
        self.hide()

    # ---- what it says
    def set_state(self, state: str, title: str, hint: str = "", tip: str = "",
                  pct: int | None = None, copy: bool = False):
        self.state, self.title, self.hint, self.tip = state, title, hint, tip
        self.pct = None if pct is None else max(0, min(100, int(pct)))
        self._copy_on = copy
        self.setAccessibleName(title)
        self.setAccessibleDescription(" ".join(filter(None, (hint, tip))))
        self._sync()

    def set_card(self, on: bool):
        """Open, the card; shut and mid, one rail button centred in the column."""
        if on != self._card:
            self._card = on
            self._sync()

    def is_card(self) -> bool:
        return self._card

    def _copy_shown(self) -> bool:
        return self._card and self._copy_on and self.state == "failed"

    def _sync(self):
        self.copy.setVisible(self._copy_shown())
        lines = [self.title, self.hint, self.tip] if not self._card else [self.tip]
        self.setToolTip("\n".join(dict.fromkeys(t for t in lines if t)))
        self._place_copy()
        if self._card and self.width() > 0:
            self.setFixedHeight(self.height_for(self.width()))
        self.updateGeometry()
        self.update()

    # ---- the card's layout: one place for paint, height and the Copy error link
    def _fonts(self) -> tuple[QFont, QFont]:
        title = QFont(self.font())
        title.setBold(True)
        hint = QFont(self.font())
        hint.setPointSizeF(8.5)   # the hint size (DESIGN.md: the type scale)
        return title, hint

    def _rows(self, width: int) -> dict:
        """Where everything goes on a card `width` wide (left to right; mirrored when
        painted): the title's lines, the bar, the hint and the link."""
        title_f, hint_f = self._fonts()
        tm, hm = QFontMetrics(title_f), QFontMetrics(hint_f)
        x = OutputBlock.TEXT_X
        chev = OutputBlock.CHEVRON + 4 if self.state == "available" else 0
        room = max(10, width - x - OutputBlock.PAD - chev)
        lines = _wrap(self.title, tm, room)
        if self.state == "downloading" and len(lines) == 1:
            # wrapped as "100%" would be, so the card doesn't grow at the end
            widest = re.sub(r"\d+", "100", self.title)
            if len(_wrap(widest, tm, room)) > 1:
                lines = _wrap(self.title, tm, tm.horizontalAdvance(self.title) - 1)
        # the card's height from its lines' boxes (TOP round them), but what's in it
        # centred on its ink: the icon's or the capitals' top (not a d's) down to the
        # icon's bottom, the last line's baseline (not a p's tail) or the bar.
        # Centred on the boxes, their room over the capitals and under the baseline
        # left it a pixel or two high
        y = 0
        rows = {"x": x, "dx": 0, "title": (y, lines), "tm": tm, "hm": hm,
                "title_f": title_f, "hint_f": hint_f}
        g = OutputBlock.GLYPH
        glyph = _ink_box(self.GLYPH.get(self.state, "download"), g)
        mid = tm.ascent() - tm.capHeight() / 2
        icon_top = math.floor(mid - g / 2)
        top = min(tm.ascent() - tm.capHeight(), icon_top + glyph[1])
        y += tm.height() * len(lines)
        ink = max(y - tm.height() + tm.ascent() - 1, icon_top + glyph[3])
        if self.state == "downloading":
            y += self.BAR_GAP
            rows["bar"] = y
            y += self.BAR_H + self.BAR_GAP - 2
            ink = rows["bar"] + self.BAR_H
        if self.hint:
            hl = _wrap(self.hint, hm, max(10, width - x - OutputBlock.PAD))
            rows["hint"] = (y, hl)
            y += hm.height() * len(hl)
            ink = y - hm.height() + hm.ascent() - 1
        if self._copy_shown():
            y += 4
            rows["copy"] = y
            ch = self.copy.sizeHint().height()
            cm = self.copy.fontMetrics()
            y += ch
            ink = rows["copy"] + (ch - cm.height()) // 2 + cm.ascent() - 1
        rows["h"] = h = self.TOP + y + self.TOP
        shift = (h - (ink + 1 - top)) // 2 - top
        rows["title"] = (shift, lines)
        for k in ("bar", "copy"):
            if k in rows:
                rows[k] += shift
        if "hint" in rows:
            rows["hint"] = (rows["hint"][0] + shift, rows["hint"][1])
        # left to right, centred across the card by its ink (icon to the widest line,
        # and the chevron), like the On Air card's lines under it. The bar runs the
        # width, its end as far from the edge as the icon's start
        left = OutputBlock.ICON_X - g // 2 + glyph[0]
        rows["edge"] = left
        if "bar" not in rows:
            widths = [tm.horizontalAdvance(t) for t in lines]
            if chev and widths:
                widths[-1] += 4 + _ink_box("fold", OutputBlock.CHEVRON)[2] + 1
            widths += [hm.horizontalAdvance(t) for t in rows.get("hint", (0, []))[1]]
            if "copy" in rows:
                widths.append(self.copy.fontMetrics().horizontalAdvance(self.copy.text()))
            right = x + max(widths, default=0)
            rows["dx"] = max(0, (width - (right - left)) // 2 - left)
        return rows

    def height_for(self, width: int) -> int:
        return self._rows(width)["h"]

    def _place_copy(self):
        if not self._copy_shown():
            return
        r = self._rows(self.width())
        hint = self.copy.sizeHint()
        # its words on the keyline: the link's own padding sits before it
        pad = (hint.width() - self.copy.fontMetrics().horizontalAdvance(self.copy.text())) // 2
        self.copy.setGeometry(round(self._mirror(r["x"] + r["dx"] - pad, hint.width())),
                              r["copy"],
                              hint.width(), hint.height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_copy()

    def sizeHint(self) -> QSize:
        if self._card:
            w = max(self.width(), BUTTON_W)
            return QSize(w, self.height_for(w))
        return QSize(BUTTON_W, BUTTON_W)

    def minimumSizeHint(self) -> QSize:
        return QSize(BUTTON_W, BUTTON_W)

    # ---- painting
    def paintEvent(self, _e):
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        hover, ring = self.underMouse(), self.hasFocus()
        if self._card:
            self._paint_card(p, hover, ring)
        else:
            self._paint_button(p, hover, ring)
        p.end()

    def _mirror(self, x: float, w: float = 0) -> float:
        return self.width() - x - w if self.isRightToLeft() else x

    def _paint_card(self, p: QPainter, hover: bool, ring: bool):
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(theme.T["accent"]), 1) if ring else Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.T["btn_hover" if hover else "panel"]))
        p.drawRoundedRect(r, 12, 12)
        rows = self._rows(self.width())
        tone = QColor(theme.T[self.TONE.get(self.state, "accent")])
        tm, dx = rows["tm"], rows["dx"]
        x = rows["x"] + dx
        y, lines = rows["title"]
        # the icon on the title's cap height (OutputBlock._pin), in the icon column
        mid = y + tm.ascent() - tm.capHeight() / 2
        g = OutputBlock.GLYPH
        p.drawPixmap(round(self._mirror(OutputBlock.ICON_X - g / 2 + dx, g)),
                     math.floor(mid - g / 2),
                     icons.pixmap(self.GLYPH.get(self.state, "download"), g, tone.name()))
        p.setFont(rows["title_f"])
        p.setPen(QColor(theme.T["text_hi"]) if self.state == "downloading" else tone)
        for n, line in enumerate(lines):
            p.drawText(round(self._mirror(x, tm.horizontalAdvance(line))),
                       round(y + n * tm.height() + tm.ascent()), line)
        if self.state == "available" and lines:   # the chevron right after its words
            # on the cap height, as the icon: "Update to 2.1.0" is capitals and digits
            ly = y + (len(lines) - 1) * tm.height()
            cmid = ly + tm.ascent() - tm.capHeight() / 2
            c = OutputBlock.CHEVRON
            cx = x + tm.horizontalAdvance(lines[-1]) + 4
            name = "fold_back" if self.isRightToLeft() else "fold"
            p.drawPixmap(round(self._mirror(cx, c)), math.floor(cmid - c / 2),
                         icons.pixmap(name, c, tone.name()))
        if "bar" in rows:
            w = self.width() - rows["edge"] - x
            _bar(p, QRectF(self._mirror(x, w), rows["bar"], w, self.BAR_H),
                 (self.pct or 0) / 100, self.isRightToLeft())
        if "hint" in rows:
            hm = rows["hm"]
            hy, hl = rows["hint"]
            p.setFont(rows["hint_f"])
            p.setPen(QColor(theme.T["muted"]))
            for n, line in enumerate(hl):
                p.drawText(round(self._mirror(x, hm.horizontalAdvance(line))),
                           round(hy + n * hm.height() + hm.ascent()), line)

    def _paint_button(self, p: QPainter, hover: bool, ring: bool):
        """Shut: the rail button's square (hover fill, the keyboard's ring) round its
        icon; downloading, a ring round a smaller icon fills with the percent."""
        side = min(self.width(), self.height())
        sq = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        if hover or ring:
            p.setPen(QPen(QColor(theme.T["accent"]), 1) if ring else Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.T["btn_hover"]) if hover else Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(sq.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        tone = QColor(theme.T[self.TONE.get(self.state, "accent")])
        c = sq.center()
        size = ICON
        if self.state == "downloading":
            d = min(self.RING, side - 4)
            rr = QRectF(c.x() - d / 2, c.y() - d / 2, d, d)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(theme.T["groove"]), 2.5))
            p.drawEllipse(rr)
            span = round(360 * 16 * (self.pct or 0) / 100)
            if span:   # clockwise from the top (anticlockwise, mirrored)
                pen = QPen(QColor(theme.T["accent"]), 2.5)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.drawArc(rr, 90 * 16, span if self.isRightToLeft() else -span)
            size = self.RING_ICON
        p.drawPixmap(round(c.x() - size / 2), round(c.y() - size / 2),
                     icons.pixmap(self.GLYPH.get(self.state, "download"), size, tone.name()))


def _wrap(text: str, fm: QFontMetrics, room: int) -> list[str]:
    """`text` in lines no wider than `room` (at spaces; a word longer than a line
    gets a line of its own): wrapping grows the card, never clips (DESIGN.md)."""
    lines: list[str] = []
    for word in text.split(" ") if text else []:
        if lines and fm.horizontalAdvance(lines[-1] + " " + word) <= room:
            lines[-1] += " " + word
        else:
            lines.append(word)
    return lines


_INK: dict[tuple[str, int], tuple[int, int, int, int]] = {}


def _ink_box(name: str, size: int) -> tuple[int, int, int, int]:
    """(left, top, right, bottom): an icon's ink in its `size` box (cached)."""
    key = (name, size)
    if key not in _INK:
        img = icons.pixmap(name, size, "#ffffff").toImage()
        dpr = img.devicePixelRatio() or 1
        pts = [(x, y) for y in range(img.height()) for x in range(img.width())
               if img.pixelColor(x, y).alpha() > 40]
        if pts:
            xs, ys = zip(*pts)
            _INK[key] = tuple(round(v / dpr) for v in (min(xs), min(ys), max(xs), max(ys)))
        else:
            _INK[key] = (0, 0, size - 1, size - 1)
    return _INK[key]


def _bar(p: QPainter, r: QRectF, frac: float, rtl: bool = False):
    """A thin progress bar: the groove, and the accent filling it."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(theme.T["groove"]))
    h = r.height()
    p.drawRoundedRect(r, h / 2, h / 2)
    if frac > 0:
        w = max(h, r.width() * min(frac, 1.0))
        x = r.right() - w if rtl else r.left()
        p.setBrush(QColor(theme.T["accent"]))
        p.drawRoundedRect(QRectF(x, r.top(), w, h), h / 2, h / 2)
