"""The Radio map's small parts (flatmap.py): the loading card, filling and mixing colours,
the stations' dot sizes and glow, and moving dots that would cover each other apart."""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QRadialGradient
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from soundboard.i18n import _
from soundboard.ui.settings import lite

LAT_TOP, LAT_BOTTOM = 84.0, -58.0   # the inhabited world: no polar wastes
FILL_PX = 1_000_000                 # device pixels per filled band (_fill)
# The most listened stations (HOT_SHARE of them, at least HOT_MIN plays today) are big
# glowing dots, bigger the more they're played; the rest are small plain ones.
HOT_SHARE = 0.1
HOT_MIN = 10
QUIET_R = 1.6                       # a quiet station's dot (pixels, at every zoom)...
HOT_R = (2.6, 5.0)                  # ...a popular one's, least to most played
# Stations close together (often a whole city's, listed at its centre) are fanned out
# round their spot once, when the list comes (FlatMap.set_points, _spread_out): where
# they are needn't be exact. Full size from SPREAD_S pixels a degree (a few wheel steps
# in), shrinking with the map below that, so on the whole world a city is one spot.
SPREAD_S = 16.0
SPREAD_CELL = 16.0                  # stations in one square this big at SPREAD_S: fanned
SPREAD_ROOM = 0.95                  # how roomy the fan is (1: dots just touching)
ROOM_GAP_PX = 1.5                   # pixels between fanned dots
LOADING_TEXT = _("Tuning in to radio stations around the world…")


def _fill(p: QPainter, rect: QRectF, colour: QColor):
    """p.fillRect in bands of about FILL_PX device pixels: Qt keeps Python's lock while
    it fills, and the whole world picture in one go held up the audio for ~10 ms.
    A step per band (FlatMap._world_steps)."""
    dpr = p.device().devicePixelRatioF()
    band = max(1.0, FILL_PX / max(1.0, rect.width() * dpr * dpr))
    y = rect.top()
    while y < rect.bottom():
        h = min(band, rect.bottom() - y)
        p.fillRect(QRectF(rect.left(), y, rect.width(), h), colour)
        y += h
        yield


def _mix(a: str, b: str, t: float) -> QColor:
    ca, cb = QColor(a), QColor(b)
    return QColor.fromRgbF(ca.redF() + (cb.redF() - ca.redF()) * t,
                           ca.greenF() + (cb.greenF() - ca.greenF()) * t,
                           ca.blueF() + (cb.blueF() - ca.blueF()) * t)


class _Loading(QFrame):
    """Bun with his headphones on, tuning in, music notes floating up: on the map
    (which can be dragged and zoomed meanwhile) until the stations come."""

    def __init__(self, parent: QWidget):
        from soundboard.ui.bun.bunnywidget import BunnyWidget
        super().__init__(parent)
        self.setObjectName("maploader")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        box = QHBoxLayout(self)
        box.setContentsMargins(6, 4, 18, 4)
        box.setSpacing(4)
        self.bun = BunnyWidget("headphones", height=64, pad=14)
        box.addWidget(self.bun)
        text = LOADING_TEXT
        self.label = QLabel(text)
        self.label.setObjectName("maploadertext")
        # two lines in any language: wrap at about half the text's width
        self.label.setWordWrap(True)
        self.label.setFixedWidth(max(150, self.label.fontMetrics().horizontalAdvance(text)
                                     * 55 // 100))
        box.addWidget(self.label)
        self._notes = QTimer(self)
        self._notes.setInterval(700)
        self._notes.timeout.connect(lambda: self.bun.burst(2))

    def showEvent(self, e):
        super().showEvent(e)
        self.bun.burst(3)
        if not lite.on():   # (lite mode: a still Bun, no notes)
            self._notes.start()

    def hideEvent(self, e):
        self._notes.stop()
        super().hideEvent(e)


def _sizes(k: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Plays today -> each dot's radius (before zoom) and whether it glows: the most
    listened HOT_SHARE (HOT_MIN plays or more) big, on a log scale up to the most
    played; the rest all QUIET_R."""
    if not len(k):
        return np.zeros(0), np.zeros(0, bool)
    floor = max(float(HOT_MIN), float(np.quantile(k, 1 - HOT_SHARE)))
    hot = k >= floor
    lo, hi = math.log1p(floor), math.log1p(max(floor, float(k.max())))
    q = np.clip((np.log1p(k) - lo) / max(1e-9, hi - lo), 0.0, 1.0)
    r = np.where(hot, HOT_R[0] + (HOT_R[1] - HOT_R[0]) * np.sqrt(q), QUIET_R)
    return r, hot


def _spread_out(x: np.ndarray, y: np.ndarray, r: np.ndarray) -> np.ndarray:
    """Pixels to move each dot by, (n, 2), so the ones close together don't cover each
    other: the dots in each SPREAD_CELL square (`x`, `y`: pixels at SPREAD_S) go round
    their spot on a sunflower, the most listened (the last) in the middle, each as far
    out as the dots before it need room. One pass of numpy, ~1 ms for 3000."""
    n = len(x)
    out = np.zeros((n, 2))
    if not n:
        return out
    gx = np.floor(x / SPREAD_CELL).astype(np.int64)
    gy = np.floor(y / SPREAD_CELL).astype(np.int64)
    g = (gx - gx.min()) * (int(gy.max() - gy.min()) + 1) + (gy - gy.min())
    order = np.lexsort((-np.arange(n), g))      # by square, the most listened first
    gs = g[order]
    idx = np.arange(n)
    first = np.maximum.accumulate(np.where(np.r_[True, gs[1:] != gs[:-1]], idx, 0))
    rank = idx - first
    area = (2 * r[order] + ROOM_GAP_PX) ** 2
    before = np.cumsum(area) - area             # the room the dots before it take...
    before -= before[first]                     # ...in its own square
    d = SPREAD_ROOM * np.sqrt(before)
    a = rank * math.pi * (3 - math.sqrt(5))
    out[order, 0] = d * np.cos(a)
    out[order, 1] = d * np.sin(a)
    return out


def _glow_image(colour: QColor) -> QImage:
    """A soft round glow in `colour`, fading to nothing at its edge: drawn stretched
    under each popular dot."""
    side = 64
    img = QImage(side, side, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    g = QRadialGradient(side / 2, side / 2, side / 2)
    for at, alpha in ((0.0, 0.95), (0.3, 0.6), (0.6, 0.2), (1.0, 0.0)):
        c = QColor(colour)
        c.setAlphaF(alpha)
        g.setColorAt(at, c)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawEllipse(QRectF(0, 0, side, side))
    p.end()
    return img
