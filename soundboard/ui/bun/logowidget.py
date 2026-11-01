"""The header logo, alive: the onion mark from theme.paint_logo with a glow around it.

At rest the glow holds still and a sheen sweeps across the tile every few seconds; the
timer only runs for the sweep (a window left open with nothing playing costs next to
nothing). Feed it the level of whatever is playing (`set_level`, 0..1: sounds, the
radio, captured programs; not your mic) and it reacts: the glow breathes, flares and
warms towards flame orange, and embers drift up off the onion while sounds play; when
they stop the breathing eases out.

A click gives it a little wobble.

It always paints in the current theme's accent colours, so theme switches recolour
it on the next frame. The widget is a little bigger than the mark to leave room for
the glow. The timer only runs while it's on screen, always at the same pace (a slower
idle pace made the breathing judder next to the smooth sheen). In lite mode (ui/settings/lite.py)
it's a still glow: no timer, no sheen, no embers (`lite_changed` after a switch).
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

from soundboard.ui.kit import theme
from soundboard.ui.kit import appstate
from soundboard.ui.settings import lite
from soundboard.ui.kit.pixels import snap_to_pixels

FLAME = QColor("#ff8a2b")
EMBER_COLORS = ("#ffcf40", "#ff8a2b", "#ff5a36")
SHEEN_PERIOD = 4.5   # seconds between sheen sweeps
SHEEN_TIME = 0.9     # how long one sweep takes
FAST_MS = 1000 // 24  # frame interval, 24 fps (while it moves and the window is in front)
QUIET = 0.003         # a level below this (-50 dB, the meters' floor) is nothing playing


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
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = sz / 2
        rg = QRadialGradient(QPointF(c, c), c)
        col = _mix(QColor(c2), FLAME, 0.6 + 0.4 * amount)
        col.setAlpha(round(170 + 85 * amount))
        rg.setColorAt(0.5, col)
        col.setAlpha(0)
        rg.setColorAt(1.0, col)
        p.setPen(Qt.PenStyle.NoPen)
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
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.level = 0.0          # smoothed output level, 0..1
        self._target = 0.0
        self.embers: list[list[float]] = []   # [x, y, vx, vy, life, size, colour index]
        self._cache: tuple | None = None      # (key, pixmap)
        self.squish = 0.0         # a click's wobble, 1 just clicked, easing to 0
        self.life = 0.0           # how much the glow breathes: 1 with a sound, 0 at rest
        self._t0 = time.monotonic()
        self._last = self._t0
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._timer.timeout.connect(self._step)
        self._wake = QTimer(self)   # at rest: the next sheen
        self._wake.setSingleShot(True)
        self._wake.timeout.connect(self._resume)
        appstate.pause_in_background(self, self._resume, self._pause)

    def set_mark(self, mark: int):
        """A new size for the onion (the tab rail's, shut or open)."""
        if mark != self.mark:
            self.mark = mark
            self.setFixedSize(QSize(mark + 2 * self.pad, mark + 2 * self.pad))
            self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.poke()
        super().mousePressEvent(e)

    def poke(self):
        """A click's wobble (also a laser hit in the Triggers page's duel)."""
        self.squish = 1.0
        self._resume()

    # ---- feeding
    def set_level(self, v: float):
        v = float(v)   # (a level fades out, never quite to 0: below QUIET it's silence)
        self._target = 0.0 if v < QUIET else min(1.0, v)
        if self._target > 0 and self._wake.isActive():   # resting: a sound wakes it
            self._resume()

    # ---- lifecycle
    def showEvent(self, e):
        if appstate.active():   # behind a game it waits until the app is back in front
            self._resume()
        super().showEvent(e)

    def _resume(self):
        self._wake.stop()
        if lite.on():   # (still: one paint, no timer)
            self._timer.stop()
            self.level, self.embers, self.squish, self.life = 0.0, [], 0.0, 0.0
            self.update()
            return
        self._last = time.monotonic()
        if not self._timer.isActive():
            self._timer.start(FAST_MS)

    def _pause(self):
        self._timer.stop()
        self._wake.stop()

    def lite_changed(self):
        """Lite mode went on or off: still now, or moving again (when it can be seen)."""
        if lite.on() or (self.isVisible() and appstate.active()):
            self._resume()

    def hideEvent(self, e):
        self._pause()
        super().hideEvent(e)

    def resting(self) -> bool:
        """Nothing moves but the sheen: no sound, embers, wobble or breathing left."""
        return (self._target == 0 and self.level < 0.005 and not self.embers
                and self.squish == 0 and self.life < 0.005)

    def _step(self):
        now = time.monotonic()
        dt = min(0.1, now - self._last)
        self._last = now
        self.advance(dt)
        self.update()
        t = now - self._t0
        if self.resting() and (t % SHEEN_PERIOD) / SHEEN_TIME >= 1.0:   # between sweeps
            self._timer.stop()
            self._wake.start(max(1, round((SHEEN_PERIOD - t % SHEEN_PERIOD) * 1000)))

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
        self.squish = max(0.0, self.squish - dt * 4)
        # the breathing comes in with a sound and eases out over a second or two after it
        alive = self._target > 0 or self.level > 0.02
        self.life += (float(alive) - self.life) * min(1.0, dt * (4 if alive else 1.5))
        if not alive and self.life < 0.005:
            self.life = 0.0

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
        still = lite.on()
        t = 0.0 if still else time.monotonic() - self._t0
        lv = self.level
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = self.width() / 2
        s = float(self.mark)
        x0 = y0 = float(self.pad)
        if self.squish > 0:   # a click's wobble, from the bottom of the tile
            k = self.squish * math.cos((1 - self.squish) * 14)
            p.translate(c, y0 + s)
            p.scale(1 + 0.08 * k, 1 - 0.1 * k)
            p.translate(-c, -(y0 + s))

        # glow: still at rest; breathes, flares and flickers warm with the sound
        breathe = 0.5 if still else 0.5 + 0.5 * math.sin(t * 1.6) * self.life
        flicker = 0.85 + 0.15 * math.sin(t * 23) * math.sin(t * 7.3) if lv > 0.05 else 1.0
        glow = _mix(QColor(c2), FLAME, lv * 1.4)
        alpha = min(255, int((70 + 60 * breathe + 170 * lv) * flicker))
        rg = QRadialGradient(QPointF(c, c + s * 0.04), c)
        col = QColor(glow)
        col.setAlpha(alpha)
        rg.setColorAt(0.45, col)
        col.setAlpha(0)
        rg.setColorAt(1.0, col)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(rg)
        p.drawEllipse(QPointF(c, c), c, c)

        # the mark itself
        p.drawPixmap(QPointF(x0, y0), self._mark_pixmap(c1, c2))

        # sheen: a soft diagonal band sweeping across the tile now and then
        ph = (t % SHEEN_PERIOD) / SHEEN_TIME
        if ph < 1.0 and not still:
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
            ec = QColor(EMBER_COLORS[int(ci)])
            ec.setAlpha(int(255 * min(1.0, life * 1.5)))
            p.setBrush(ec)
            r = size * (0.5 + 0.5 * life)
            p.drawEllipse(QPointF(x, y), r, r)
        p.end()
