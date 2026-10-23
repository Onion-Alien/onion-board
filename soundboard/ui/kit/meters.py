"""Painted gauges: the level meter, the EQ curve, the loading bar, the "now playing"
equalizer, and the spectrum / loudness a playing pad shows."""
from __future__ import annotations

import math
import time
from functools import lru_cache

import numpy as np
from PySide6.QtCore import (QRectF, QSize, Qt, QTimer, Signal)
from PySide6.QtGui import (QColor, QLinearGradient, QPainter, QPainterPath, QPen)
from PySide6.QtWidgets import QWidget

from soundboard.ui.kit import theme
from soundboard.audio.eq import MAX_DB as EQ_MAX_DB
from soundboard.audio.eq import response_db as eq_response
from soundboard.audio.engine import SR
from soundboard.ui.settings import lite
from soundboard.i18n import _
from soundboard.ui.kit.pixels import snap_to_pixels


class Meter(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.level = 0.0
        self._hot = False
        self._drawn = None        # (bar width in px, colour) as last painted
        self._col = "#13ce66"
        # the loudest the level can get: full bar and the red zone sit under it (the
        # send limiter holds what others hear at sendfx.CEILING_DB, under 0 dB)
        self.top_db = 0.0
        self.setFixedHeight(8)
        self.setAccessibleName(_("Level meter"))

    @property
    def hot(self) -> bool:
        return self._hot

    @hot.setter
    def hot(self, on: bool):
        self._hot = bool(on)
        self.update()

    def _bar(self) -> tuple[float, str]:
        db = 20 * np.log10(max(self.level, 1e-5)) - self.top_db
        frac = float(np.clip((db + 50) / 50, 0, 1))
        # Hysteresis keeps levels near the thresholds from flashing between colours.
        if self._col == "#ff4d4f":
            if db < -3.5:
                self._col = "#ffb020" if db >= -11.0 else "#13ce66"
        elif self._col == "#ffb020":
            if db >= -2.0:
                self._col = "#ff4d4f"
            elif db < -11.0:
                self._col = "#13ce66"
        else:
            if db >= -2.0:
                self._col = "#ff4d4f"
            elif db >= -9.0:
                self._col = "#ffb020"
        return frac, "#ff4d4f" if self._hot else self._col

    def set_level(self, v):
        self.level = v
        frac, col = self._bar()
        # fed 20-30 times a second: repaint only when the bar would look different
        drawn = (round(self.width() * frac), col if frac > 0 else "")
        if drawn != self._drawn:
            self._drawn = drawn
            self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._drawn = None

    def paintEvent(self, e):
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.T["groove"]))
        rad = min(4.0, r.height() / 2)
        p.drawRoundedRect(r, rad, rad)
        frac, col = self._bar()
        if frac > 0:
            p.setBrush(QColor(col))
            p.drawRoundedRect(QRectF(0, 0, r.width() * frac, r.height()), rad, rad)


class EqCurve(QWidget):
    """Draws the EQ's actual frequency response. Double-click resets to flat."""
    reset = Signal()

    def __init__(self):
        super().__init__()
        self.setFixedHeight(70)
        self.gains = [0.0] * 7
        self.on = False
        self.setToolTip(_("Double-click to reset"))
        self.setAccessibleName(_("EQ curve"))
        self._freqs = np.geomspace(30, 18000, 160)

    def set_gains(self, gains, on):
        self.gains, self.on = list(gains), on
        self.update()

    def mouseDoubleClickEvent(self, e):
        self.reset.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.T["bg"]))
        p.drawRoundedRect(r, 8, 8)
        mid = r.center().y()
        p.setPen(QPen(QColor(theme.T["groove"]), 1))
        p.drawLine(int(r.left() + 6), int(mid), int(r.right() - 6), int(mid))
        db = eq_response(self.gains, self._freqs)
        scale = (r.height() / 2 - 6) / EQ_MAX_DB
        path = QPainterPath()
        n = len(db)
        for i, d in enumerate(db):
            x = r.left() + 6 + (r.width() - 12) * i / (n - 1)
            y = mid - float(np.clip(d, -EQ_MAX_DB - 3, EQ_MAX_DB + 3)) * scale
            path.moveTo(x, y) if i == 0 else path.lineTo(x, y)
        col = QColor(theme.T["accent"] if self.on else theme.T["off"])
        p.setPen(QPen(col, 2.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        if not self.on:   # on a little plate, so the flat line doesn't strike it through
            fm = p.fontMetrics()
            off = _("EQ off")
            plate = QRectF(0, 0, fm.horizontalAdvance(off) + 14, fm.height() + 4)
            plate.moveCenter(r.center())
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.T["bg"]))
            p.drawRoundedRect(plate, plate.height() / 2, plate.height() / 2)
            p.setPen(QColor(theme.T["muted"]))
            p.drawText(plate, Qt.AlignmentFlag.AlignCenter, off)


class LoadingBar(QWidget):
    """An indeterminate progress bar: an accent pill gliding back and forth along a
    rounded groove. Theme colours are read on every paint, and the timer only runs
    while it's started and on screen."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(6)
        self._t0 = time.monotonic()
        self._on = False
        self._timer = QTimer(self)
        self._timer.setInterval(1000 // 24)
        self._timer.timeout.connect(self.update)

    def start(self):
        self._on = True
        self._t0 = time.monotonic()
        if self.isVisible():
            self._timer.start()

    def stop(self):
        self._on = False
        self._timer.stop()

    def running(self) -> bool:
        return self._on

    def ticking(self) -> bool:
        return self._timer.isActive()

    def showEvent(self, ev):
        if self._on:
            self._timer.start()
        super().showEvent(ev)

    def hideEvent(self, ev):
        self._timer.stop()
        super().hideEvent(ev)

    def sizeHint(self) -> QSize:
        return QSize(240, 6)

    def paintEvent(self, _e):
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        rad = r.height() / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.T.get("groove", "#343849")))
        p.drawRoundedRect(r, rad, rad)
        # the pill eases from one end to the other and back, stretching mid-glide
        k = 0.5 - 0.5 * math.cos((time.monotonic() - self._t0) * math.pi / 0.9)
        w = r.width() * (0.28 + 0.14 * math.sin(k * math.pi))
        x = r.left() + (r.width() - w) * k
        g = QLinearGradient(x, 0, x + w, 0)
        g.setColorAt(0, QColor(theme.T.get("accent", "#7c5cff")))
        g.setColorAt(1, QColor(theme.T.get("accent2", theme.T.get("accent_hi", "#8d71ff"))))
        p.setBrush(g)
        p.drawRoundedRect(QRectF(x, r.top(), w, r.height()), rad, rad)
        p.end()


def paint_now_playing(p: QPainter, rect: QRectF, color: QColor, paused: bool = False,
                      n: int = 4, t: float | None = None):
    """A small "now playing" equalizer in `rect`: `n` bars bouncing with the clock (`t`,
    seconds; now if None), or low and still while paused. Used wherever something
    playing has to stand out at a glance: a web result's picture, the playing radio
    station."""
    t = time.monotonic() if t is None else t
    paused = paused or lite.on()   # (lite mode: low and still)
    gap = rect.width() / (n * 3 - 1)   # a bar is two gaps wide
    bw = gap * 2
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    for i in range(n):
        f = 0.3 if paused else 0.25 + 0.75 * abs(math.sin(t * (2.3 + i * 0.9) + i * 1.7))
        h = max(bw, rect.height() * f)
        p.drawRoundedRect(QRectF(rect.left() + i * (bw + gap), rect.bottom() - h, bw, h),
                          bw / 2, bw / 2)
    p.restore()


FFT_N = 2048


_HANN = np.hanning(FFT_N).astype(np.float32)


_FREQS = np.fft.rfftfreq(FFT_N, 1 / SR)


def spectrum(data: np.ndarray | None, frac: float, n: int) -> np.ndarray:
    """`n` log-spaced band levels (0..1) of int16/float (m, 2) audio around position
    `frac` (0..1): what a pad's visualizer shows. Cheap: one 2048-point FFT."""
    if data is None or not len(data) or n <= 0:
        return np.zeros(max(n, 0), np.float32)
    # the stretch just played, not the one coming: a long sound is read from disk
    # (mapped.py) and what's ahead may not be in yet, while the rest of the file is
    # being read in behind it. On a slow drive each frame waited its turn: the pad's
    # equalizer ran at 2 a second until that finished. What was just played is in.
    pos = max(0, int(min(max(frac, 0.0), 1.0) * len(data)) - FFT_N)
    seg = data[pos:pos + FFT_N]
    if len(seg) < FFT_N:
        seg = np.concatenate([seg, np.zeros((FFT_N - len(seg), 2), seg.dtype)])
    mono = seg.mean(axis=1, dtype=np.float32)
    if data.dtype == np.int16:
        mono /= 32768.0
    mag = np.abs(np.fft.rfft(mono * _HANN)) * (4.0 / FFT_N)   # full-scale sine ~ 1
    start, count, tilt = _band_plan(n)
    # each band's RMS from a running sum of the power: no Python loop over bands
    power = np.concatenate(([0.0], np.cumsum(mag.astype(np.float64) ** 2)))
    out = np.sqrt((power[start + count] - power[start]) / count)
    db = 20 * np.log10(out + 1e-9) + tilt
    return np.clip((db + 62) / 52, 0.0, 1.0).astype(np.float32)


def loudness(data: np.ndarray | None, frac: float, gain: float = 1.0) -> float:
    """How loud (0..1) the stretch just played around `frac` is: its RMS times `gain`,
    -48 dBFS..0 dBFS. What a playing pad's level meter shows; the same window as
    spectrum() (what's ahead of a long sound may not be read in yet)."""
    if data is None or not len(data):
        return 0.0
    pos = max(0, int(min(max(frac, 0.0), 1.0) * len(data)) - FFT_N)
    seg = data[pos:pos + FFT_N]
    if not len(seg):
        return 0.0
    mono = seg.mean(axis=1, dtype=np.float32)
    if data.dtype == np.int16:
        mono /= 32768.0
    rms = float(np.sqrt(np.mean(mono * mono))) * max(gain, 0.0)
    return min(max((20 * math.log10(rms + 1e-9) + 48) / 48, 0.0), 1.0)


@lru_cache(maxsize=16)
def _band_plan(n: int):
    """Where spectrum()'s `n` log-spaced bands start in the FFT, how many bins each
    covers (at least one), and the lift each gets because music falls off up high."""
    edges = np.geomspace(50, 14000, n + 1)
    idx = np.clip(np.searchsorted(_FREQS, edges), 1, len(_FREQS) - 1)
    start = idx[:-1]
    count = np.maximum(idx[1:], start + 1) - start
    return start, count, np.linspace(0, 14, n)
