"""Words on the web search's cards (ytsearch.py): view and like counts, and `ClampLabel`, a
label cut to a few lines with an ellipsis (the Store's cards use it too)."""
from __future__ import annotations

import html

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QTextLayout
from PySide6.QtWidgets import QLabel, QSizePolicy

from soundboard.ui.kit import theme
from soundboard.online import ytdl
from soundboard.ui.kit import icons
from soundboard.i18n import ngettext
from soundboard.ui.kit.pixels import snap_to_pixels


def fmt_count(n: int) -> str:
    """1234 -> "1.2K", 4553746 -> "4.6M" (YouTube's way of rounding)."""
    for size, unit in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if n >= size:
            v = n / size
            return (f"{v:.1f}".rstrip("0").rstrip(".") if v < 10 else f"{v:.0f}") + unit
    return str(n)


def _count(kind: str, n: int, shown: str) -> str:
    """"1.2K views": `n` picks the word's form, `shown` is the number as written."""
    if kind == "views":
        return ngettext("{count} view", "{count} views", n, count=shown)
    if kind == "likes":
        return ngettext("{count} like", "{count} likes", n, count=shown)
    return ngettext("{count} comment", "{count} comments", n, count=shown)


def stats_text(r: ytdl.Result) -> tuple[str, str]:
    """(the card's line, its tooltip) for a hit's views, likes and comments, as its
    search entry gave them: nothing for what it didn't say. No video page is fetched
    for more (a look-up per hit is scraping, and the kind that gets you bot-checked)."""
    parts, tip = [], []
    for n, kind in ((r.views, "views"), (r.likes, "likes"), (r.comments, "comments")):
        if n is not None:
            parts.append(_count(kind, n, fmt_count(n)))
            tip.append(_count(kind, n, f"{n:,}"))
    return " · ".join(parts), ", ".join(tip)


def plain_tip(text: str) -> str:
    """`text` as a tooltip that shows exactly what it says: a tooltip reads anything
    that looks like HTML as HTML, and titles come from the web and the store."""
    return f"<p>{html.escape(text)}</p>" if text else ""


class ClampLabel(QLabel):
    """Text (bold by default) wrapped onto at most `lines` lines, the last ending in "…" when it
    doesn't fit (the full text in the tooltip). Always that tall, so cards in a row
    line up."""

    def __init__(self, text: str, lines: int = 2, bold: bool = True):
        super().__init__()
        self.full, self.lines = text, lines
        self._wrap: tuple = (None, [])   # (key, lines) from _wrapped()
        f = self.font()
        f.setBold(bold)
        self.setFont(f)
        self.setToolTip(plain_tip(text))
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._fit()

    def set_full(self, text: str, tip: str = ""):
        self.full = text
        self.setToolTip(plain_tip(tip or text))
        self.update()

    def _fit(self):
        self.setFixedHeight(self.fontMetrics().lineSpacing() * self.lines + 2)

    def changeEvent(self, e):
        # the theme's font comes with its style sheet, after __init__ (and changes with
        # the theme): sized by the font it had then, the last line lost its descenders
        super().changeEvent(e)
        if e.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._fit()

    def _wrapped(self) -> list[tuple[str, float]]:
        """The lines to draw and their tops. Kept by (text, width, font): a page of
        cards repaints on every hover and scroll, and wrapping is the slow part."""
        key = (self.full, self.width(), self.font().key(), self.lines)
        if self._wrap[0] == key:
            return self._wrap[1]
        fm = self.fontMetrics()
        layout = QTextLayout(self.full, self.font())
        layout.beginLayout()
        y, shown = 0.0, []
        while len(shown) < self.lines:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(self.width())
            shown.append((line.textStart(), line.textLength(), y))
            y += fm.lineSpacing()
        layout.endLayout()
        out = []
        for i, (start, length, ly) in enumerate(shown):
            text = self.full[start:start + length].rstrip()
            if i == len(shown) - 1 and start + length < len(self.full):
                text = fm.elidedText(self.full[start:], Qt.TextElideMode.ElideRight, self.width())
            out.append((text, ly))
        self._wrap = (key, out)
        return out

    def paintEvent(self, e):
        p = QPainter(self)
        snap_to_pixels(p)
        p.setPen(self.palette().color(self.foregroundRole()))
        p.setFont(self.font())
        ascent = self.fontMetrics().ascent()
        for text, ly in self._wrapped():
            p.drawText(QPointF(0, ly + ascent), text)
        p.end()


class StatsLabel(ClampLabel):
    """Compact metadata with the same painted symbols as the app's controls."""

    def __init__(self):
        super().__init__("", lines=1, bold=False)
        self.fields = []

    def set_stats(self, result):
        self.fields = [(icon, fmt_count(n))
                       for n, icon in ((result.views, "triggers"), (result.likes, "like"),
                                       (result.comments, "speech"))
                       if n is not None]
        text, tip = stats_text(result)
        self.set_full(text, tip)
        self.setAccessibleName(text)
        self.setVisible(bool(text))

    def paintEvent(self, e):
        p = QPainter(self)
        snap_to_pixels(p)
        p.setFont(self.font())
        p.setPen(QColor(theme.T["muted"]))
        fm = self.fontMetrics()
        side = max(12, min(16, fm.height()))
        x = 0
        for icon, text in self.fields:
            room = self.width() - x - side - 5
            if room < fm.horizontalAdvance("…"):
                break
            icons.icon(icon, "muted").paint(p, x, (self.height() - side) // 2, side, side)
            x += side + 5
            shown = fm.elidedText(text, Qt.TextElideMode.ElideRight, room)
            p.drawText(QPointF(x, (self.height() - fm.height()) / 2 + fm.ascent()), shown)
            x += fm.horizontalAdvance(shown) + 14
        p.end()
