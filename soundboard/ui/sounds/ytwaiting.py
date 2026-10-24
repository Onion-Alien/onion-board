"""The web search's loading view (`SearchingView`: Bun or Hoot over a sliding bar) and its
*Back* button (`BackHome`)."""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from soundboard.ui.kit import theme
from soundboard.ui.bun.bunny import H as BUN_H
from soundboard.ui.bun.bunny import W as BUN_W
from soundboard.ui.bun.bunnywidget import BunnyWidget
from soundboard.style.owl import H as OWL_H
from soundboard.style.owl import W as OWL_W
from soundboard.style.owl import OwlWidget
from soundboard.ui.kit.widgets import LoadingBar
from soundboard.ui.settings import lite


class _BusyOwl(OwlWidget):
    """Hoot on the job: bright-eyed and tufts up instead of moping, scanning left and
    right for your sound, no dozing or begging."""

    def __init__(self, height: int, parent=None):
        super().__init__(height, lines=(), joy=(), parent=parent, left=0, right=0)
        self._next_act = math.inf
        self.setToolTip("")

    def busy(self) -> bool:
        return True   # always scanning: never the slow idle frames

    def base_pose(self) -> dict:
        d = super().base_pose()   # (the springy layer goes on top: tufts trail his turns)
        d["sad"] = 0.0
        if lite.on():   # (lite mode: a still picture, eyes on the results)
            d["look_y"] = 0.25
            return d
        scan = math.sin(self.t * 1.6)
        d["tufts"] = -8 + 3 * math.sin(self.t * 1.1)
        d["look"] = 0.8 * scan                       # scanning the results,
        d["rot"] += 2.5 * scan                       # leaning into each look
        d["look_y"] = 0.25
        return d


class SearchingView(QWidget):
    """What the results area shows while a search runs: a mascot (Bun with his
    headphones on, or Hoot keeping watch; a coin toss each time) over a loading bar
    and the "Searching ... for ..." line, all centred. Laid out by hand so it never
    asks the window for room: the mascot shrinks with the space and goes when
    there's too little, then the bar, leaving just the line."""

    MASCOTS = ("bunny", "owl")
    BIG, SMALL = 130, 44       # mascot heights, px
    GAP = 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self.kind = ""
        self.mascot: QWidget | None = None
        self._rng = random.Random()
        self.bar = LoadingBar(self)
        self.label = QLabel(self)
        self.label.setTextFormat(Qt.TextFormat.RichText)
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hide()

    def sizeHint(self) -> QSize:
        return QSize(320, 220)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, self.label.sizeHint().height())

    def start(self, text: str):
        """Show `text` (rich text) under a freshly picked mascot and start the bar."""
        self.label.setText(text)
        kind = self._rng.choice(self.MASCOTS)
        if kind != self.kind or self.mascot is None:
            if self.mascot is not None:
                self.mascot.hide()
                self.mascot.deleteLater()
            self.mascot = self._make(kind)
            self.kind = kind
        self.bar.start()
        self.show()
        self._place()

    def stop(self):
        self.bar.stop()
        self.hide()            # the mascot's own timer stops with it

    def running(self) -> bool:
        return self.bar.running()

    def _make(self, kind: str) -> QWidget:
        if kind == "owl":
            m = _BusyOwl(self.BIG, parent=self)
        else:
            m = BunnyWidget("headphones", height=self.BIG, pad=22, parent=self)
        return m

    def _fit_mascot(self, h: int) -> QSize:
        """Draw the mascot `h` px tall; returns the box it then needs."""
        m = self.mascot
        if isinstance(m, OwlWidget):
            m.owl_h, m.top = h, round(h * 0.34)
            return QSize(round(h * OWL_W / OWL_H) + 8, h + m.top + 8)
        assert isinstance(m, BunnyWidget)   # _make makes an owl or a bunny
        m.bun_h, m.pad = h, round(h * 0.22)
        return QSize(round(h * BUN_W / BUN_H) + 2 * m.pad + 20, h + 2 * m.pad)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._place()

    def _place(self):
        w, h, gap = self.width(), self.height(), self.GAP
        tw = max(40, min(w - 24, 460))
        th = self.label.heightForWidth(tw)
        th = th if th > 0 else self.label.sizeHint().height()
        bw = max(0, min(260, w - 48))
        show_bar = bw >= 60 and h >= th + gap + 6
        need = th + (gap + 6 if show_bar else 0)
        room = h - need - gap               # what's left above for the mascot
        box = QSize()
        if self.mascot is not None:
            # biggest that fits (its box is about 1.5x its height), or none at all
            mh = min(self.BIG, int(room / 1.5))
            if mh >= self.SMALL:
                box = self._fit_mascot(mh)
                if box.width() > w - 8 or box.height() > room:
                    box = QSize()
            self.mascot.setVisible(not box.isEmpty())
        total = need + (box.height() + gap if not box.isEmpty() else 0)
        y = max(0, (h - total) // 2)
        if self.mascot is not None and not box.isEmpty():
            self.mascot.setGeometry((w - box.width()) // 2, y, box.width(), box.height())
            y += box.height() + gap
        self.bar.setVisible(show_bar)
        if show_bar:
            self.bar.setGeometry((w - bw) // 2, y, bw, 6)
            y += 6 + gap
        self.label.setGeometry((w - tw) // 2, y, tw, th)


class BackHome(QPushButton):
    """The results' Back button: red, with a soft red glow around its border, so the
    way out is easy to spot. The glow is painted in the button's own margin (the
    sheet's `margin:` for #backhome is GLOW px), so no parent clips it."""

    GLOW = 5     # px of glow around the box: must match the sheet's margin
    RADIUS = 8   # the box's border-radius in the sheet

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("backhome")

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QColor(theme.tokens().get("danger_text", "red"))
        box = QRectF(self.rect()).adjusted(self.GLOW, self.GLOW, -self.GLOW, -self.GLOW)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(1, self.GLOW + 1):   # rings fading out from the border
            c.setAlphaF(0.85 * (1 - i / (self.GLOW + 1)) ** 1.5)
            p.setPen(c)
            r = box.adjusted(-i + 0.5, -i + 0.5, i - 0.5, i - 0.5)
            p.drawRoundedRect(r, self.RADIUS + i, self.RADIUS + i)
        p.end()
        super().paintEvent(e)
