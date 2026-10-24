"""The Radio map's small parts (flatmap.py): the loading card, filling and mixing colours,
the stations' dot sizes and glow, and moving dots that would cover each other apart."""
from __future__ import annotations

import math
from collections.abc import Iterator

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
QUIET_R = 1.0                       # a quiet station's dot (pixels, before zoom)...
HOT_R = (2.0, 5.0)                  # ...a popular one's, least to most played
# Dots that would cover each other move apart (where they are needn't be exact): each
# takes the nearest free place round its spot, up to ROOM_PX away (more zoomed in, as
# the dots grow), ROOM_GAP_PX apart. Past ROOM_ZOOM both grow with the zoom (the gaps
# as its square root, the reach in step with it): a city's stations all listed at its
# centre keep coming apart as you zoom in, instead of staying one fixed clump. Worked
# out once per half zoom step (ROOM_STEPS a doubling) and kept, a slice at a time
# (ROOM_BATCH dots a step, ROOM_SLICE_S a slice) between frames, the dots where they
# were till it's done.
ROOM_PX = 14.0
ROOM_GAP_PX = 0.8
ROOM_ZOOM = 4.0
ROOM_STEPS = 2
ROOM_BATCH = 32
ROOM_SLICE_S = 0.004
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


def _pop(x: np.ndarray) -> np.ndarray:
    """0..1 -> a dot's size while it pops in: grows a little past full, then settles."""
    x = np.clip(x, 0.0, 1.0) - 1
    return 1 + 2.7 * x ** 3 + 1.7 * x ** 2


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


def _make_room(x: np.ndarray, y: np.ndarray, r: np.ndarray, step: float,
               room: float) -> Iterator[None]:
    """The steps that work out how many pixels to move each dot by so none covers
    another (the generator's return value, (n, 2)): from the last (the most listened,
    which keeps its spot) to the first, each takes the first free place on a
    sunflower spiral round its own spot (`step` apart), no further than `room`; with
    none free it stays put. `x`, `y`: where the dots are, in pixels. All ~3000 in one
    go took ~100 ms zoomed out, a stall: a step every ROOM_BATCH dots."""
    n = len(x)
    out = np.zeros((n, 2))
    if not n:
        return out
    gap = ROOM_GAP_PX
    j = np.arange(int((room / step) ** 2) + 1)
    d = step * np.sqrt(j)
    a = j * math.pi * (3 - math.sqrt(5))
    tx, ty = (d * np.cos(a))[:, None], (d * np.sin(a))[:, None]   # (0, 0) first
    chunk = 256   # places tried at a time: zoomed in there can be thousands
    reach = 2 * (room + float(r.max())) + gap   # two moved dots touching, at most
    # the dots placed so far, by square (reach a side, by where each started): a dot
    # looks only at the nine round its own, not at every dot placed
    gx = np.floor(x / reach).astype(int).tolist()
    gy = np.floor(y / reach).astype(int).tolist()
    cells: dict[tuple[int, int], list[int]] = {}
    px, py = x.copy(), y.copy()
    for i in range(n - 1, -1, -1):
        a, b = gx[i], gy[i]
        near = [q for ca in (a - 1, a, a + 1) for cb in (b - 1, b, b + 1)
                for q in cells.get((ca, cb), ())]
        if near:
            q = np.array(near)
            lim = (r[i] + r[q] + gap) ** 2
            for c in range(0, len(tx), chunk):
                cx, cy = tx[c:c + chunk], ty[c:c + chunk]
                free = (((x[i] + cx - px[q]) ** 2 + (y[i] + cy - py[q]) ** 2)
                        >= lim).all(axis=1)
                t = int(np.argmax(free))
                if free[t]:
                    t += c
                    break
            else:   # not free anywhere near enough: it stays on its spot
                t = 0
            if t:
                out[i] = (tx[t, 0], ty[t, 0])
                px[i], py[i] = x[i] + tx[t, 0], y[i] + ty[t, 0]
        cells.setdefault((a, b), []).append(i)
        if i % ROOM_BATCH == 0:
            yield
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
