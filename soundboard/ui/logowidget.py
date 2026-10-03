"""The header logo, alive: the onion mark from theme.paint_logo with a glow around it.

At rest the glow breathes slowly and a sheen sweeps across the tile every few seconds.
Feed it the level of whatever is playing (`set_level`, 0..1: sounds, the radio,
captured programs; not your mic) and it reacts: the glow flares and warms
towards flame orange, and embers drift up off the onion while sounds play.

It always paints in the current theme's accent colours, so theme switches recolour
it on the next frame. The widget is a little bigger than the mark to leave room for
the glow. The timer only runs while it's on screen, and slows to a few frames a
second at rest (only the breathing moves then).
"""
from __future__ import annotations

import math
import random
import time
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPixmap,
                           QRadialGradient)
from PySide6.QtWidgets import QWidget

from soundboard import theme
from soundboard.ui import appstate

FLAME = QColor("#ff8a2b")
EMBER_COLORS = ("#ffcf40", "#ff8a2b", "#ff5a36")
SHEEN_PERIOD = 4.5   # seconds between sheen sweeps
SHEEN_TIME = 0.9     # how long one sweep takes
FAST_MS = 33         # frame interval with sound, embers or the sheen sweeping
IDLE_MS = 125        # at rest only the slow breathing moves: a few frames a second do


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(round(a.red() + (b.red() - a.red()) * t),
                  round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t))


@lru_cache(maxsize=64)
def glow_icon(c1: str, c2: str, amount: float) -> QIcon:
    """The app icon for the title bar, taskbar and tray, glowing warm by `amount`
    (0..1) the way the header logo does while something plays. At 0 it's the plain
    theme.app_icon; above, the mark shrinks a little inside a flame-coloured halo."""
    if amount <= 0:
        return theme.app_icon(c1, c2)
    icon = QIcon()
    for sz in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(sz, sz)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        c = sz / 2
        rg = QRadialGradient(QPointF(c, c), c)
        col = _mix(QColor(c2), FLAME, 0.6 + 0.4 * amount)
        col.setAlpha(round(170 + 85 * amount))
        rg.setColorAt(0.5, col)
        col.setAlpha(0)
        rg.setColorAt(1.0, col)
        p.setPen(Qt.NoPen)
        p.setBrush(rg)
        p.drawEllipse(QPointF(c, c), c, c)
        m = sz * (0.86 - 0.08 * amount)   # the halo needs room at the edge
        theme.paint_logo(p, QRectF(c - m / 2, c - m / 2, m, m), c1, c2)
        p.end()
        icon.addPixmap(pm)
    return icon


class LogoWidget(QWidget):
    def __init__(self, mark: int = 32, pad: int = 5, parent=None):
        super().__init__(parent)
        self.mark = mark
        self.pad = pad
        self.setFixedSize(QSize(mark + 2 * pad, mark + 2 * pad))
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.level = 0.0          # smoothed output level, 0..1
        self._target = 0.0
        self.embers: list[list[float]] = []   # [x, y, vx, vy, life, size, colour index]
        self._cache: tuple | None = None      # (key, pixmap)
        self._t0 = time.monotonic()
        self._last = self._t0
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.CoarseTimer)
        self._timer.timeout.connect(self._step)
        appstate.pause_in_background(self, self._resume, self._timer.stop)

    # ---- feeding
    def set_level(self, v: float):
        self._target = max(0.0, min(1.0, float(v)))
        if self._target >= 0.01 and self._timer.isActive() \
                and self._timer.interval() != FAST_MS:
            self._timer.start(FAST_MS)   # a sound started: back to full speed at once

    # ---- lifecycle
    def showEvent(self, e):
        if appstate.active():   # behind a game it waits until the app is back in front
            self._resume()
        super().showEvent(e)

    def _resume(self):
        self._last = time.monotonic()
        self._timer.start(FAST_MS)

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)

    def _step(self):
        now = time.monotonic()
        dt = min(0.1, now - self._last)
        self._last = now
        self.advance(dt)
        self.update()
        want = FAST_MS if self.busy() else IDLE_MS
        if self._timer.interval() != want:
            self._timer.setInterval(want)

    def busy(self) -> bool:
        """Anything moving faster than the slow idle breathing: sound, embers, or
        the sheen mid-sweep (or about to start one)."""
        if self.level >= 0.01 or self._target >= 0.01 or self.embers:
            return True
        ph = ((time.monotonic() - self._t0) % SHEEN_PERIOD) / SHEEN_TIME
        return ph < 1.0 or ph > (SHEEN_PERIOD - IDLE_MS / 1000) / SHEEN_TIME

    def advance(self, dt: float):
        """Move the animation on by dt seconds (separate from the timer for tests)."""
        # fast attack, slow release, so a hit flares and then settles
        k = 0.5 if self._target > self.level else 0.08
        self.level += (self._target - self.level) * k
        c = self.width() / 2
        if self.level > 0.06 and random.random() < self.level * 0.7:
            self.embers.append([c + random.uniform(-0.25, 0.25) * self.mark,
                                c + random.uniform(-0.05, 0.25) * self.mark,
                                random.uniform(-6, 6), -random.uniform(14, 30),
                                1.0, random.uniform(0.7, 1.4), random.randrange(len(EMBER_COLORS))])
        for em in self.embers:
            em[0] += em[2] * dt + math.sin((time.monotonic() - self._t0) * 9 + em[5] * 5) * 0.25
            em[1] += em[3] * dt
            em[4] -= dt * 1.1
        self.embers = [em for em in self.embers if em[4] > 0][-16:]

    # ---- painting
    def _mark_pixmap(self, c1: str, c2: str) -> QPixmap:
        dpr = self.devicePixelRatioF() or 1.0
        key = (c1, c2, self.mark, dpr)
        if self._cache is None or self._cache[0] != key:
            pm = theme.logo_pixmap(round(self.mark * dpr), c1, c2)
            pm.setDevicePixelRatio(dpr)
            self._cache = (key, pm)
        return self._cache[1]

    def paintEvent(self, _e):
        c1, c2 = theme.T["accent"], theme.T["accent2"]
        t = time.monotonic() - self._t0
        lv = self.level
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = self.width() / 2
        s = float(self.mark)
        x0 = y0 = float(self.pad)

        # glow: breathes at rest, flares and flickers warm with the sound
        breathe = 0.5 + 0.5 * math.sin(t * 1.6)
        flicker = 0.85 + 0.15 * math.sin(t * 23) * math.sin(t * 7.3) if lv > 0.05 else 1.0
        glow = _mix(QColor(c2), FLAME, lv * 1.4)
        alpha = min(255, int((70 + 60 * breathe + 170 * lv) * flicker))
        rg = QRadialGradient(QPointF(c, c + s * 0.04), c)
        col = QColor(glow)
        col.setAlpha(alpha)
        rg.setColorAt(0.45, col)
        col.setAlpha(0)
        rg.setColorAt(1.0, col)
        p.setPen(Qt.NoPen)
        p.setBrush(rg)
        p.drawEllipse(QPointF(c, c), c, c)

        # the mark itself
        p.drawPixmap(QPointF(x0, y0), self._mark_pixmap(c1, c2))

        # sheen: a soft diagonal band sweeping across the tile now and then
        ph = (t % SHEEN_PERIOD) / SHEEN_TIME
        if ph < 1.0:
            tile = QPainterPath()
            tile.addRoundedRect(QRectF(x0 + s * 0.04, y0 + s * 0.04, s * 0.92, s * 0.92),
                                s * 0.26, s * 0.26)
            p.save()
            p.setClipPath(tile)
            pos = -0.6 + 2.2 * ph
            g = QLinearGradient(QPointF(x0 + s * (pos - 0.3), y0),
                                QPointF(x0 + s * (pos + 0.3), y0 + s))
            g.setColorAt(0.0, QColor(255, 255, 255, 0))
            g.setColorAt(0.5, QColor(255, 255, 255, 85))
            g.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.fillRect(QRectF(x0, y0, s, s), g)
            p.restore()

        # embers
        for x, y, _vx, _vy, life, size, ci in self.embers:
            ec = QColor(EMBER_COLORS[ci])
            ec.setAlpha(int(255 * min(1.0, life * 1.5)))
            p.setBrush(ec)
            r = size * (0.5 + 0.5 * life)
            p.drawEllipse(QPointF(x, y), r, r)
        p.end()
