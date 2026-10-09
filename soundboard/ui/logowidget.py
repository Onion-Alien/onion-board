"""The header logo, alive: the onion mark from theme.paint_logo with a glow around it.

At rest the glow breathes slowly and a sheen sweeps across the tile every few seconds.
Feed it the level of whatever is playing (`set_level`, 0..1: sounds, the radio,
captured programs; not your mic) and it reacts: the glow flares and warms
towards flame orange, and embers drift up off the onion while sounds play.

An Easter egg: click it CRY_CLICKS times quickly and the onion (being an onion) gets
upset: its eyes well up with each click, then it sobs, tears run off it and drip
down the header into a little puddle. Each click while it cries peels a layer off.
It calms down CRY_S seconds after the last click and the puddle dries up.

It always paints in the current theme's accent colours, so theme switches recolour
it on the next frame. The widget is a little bigger than the mark to leave room for
the glow. The timer only runs while it's on screen, always at the same pace (a slower
idle pace made the breathing judder next to the smooth sheen).
"""
from __future__ import annotations

import math
import random
import time
from functools import lru_cache

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPixmap, QRadialGradient)
from PySide6.QtWidgets import QWidget

from soundboard import theme, usage
from soundboard.ui import appstate

FLAME = QColor("#ff8a2b")
EMBER_COLORS = ("#ffcf40", "#ff8a2b", "#ff5a36")
SHEEN_PERIOD = 4.5   # seconds between sheen sweeps
SHEEN_TIME = 0.9     # how long one sweep takes
FAST_MS = 33         # frame interval, ~30 fps
CRY_CLICKS = 10      # quick clicks that make it cry
WELL_UP_AT = 5       # from this many quick clicks its eyes start to show
CRY_WINDOW = 4.0     # seconds the clicks have to come within
CRY_S = 6.0          # it keeps crying this long after the last click
TEAR = QColor("#8fd3ff")
SOB_BLUE = QColor("#5ab8ff")
FACE = QColor("#2b2340")
DROP_FALL = 46       # how far below the logo the tears land (the tab row), px
GRAVITY = 520.0      # px/s² for tears and peels


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


class _TearLayer(QWidget):
    """Where the tears fall: a see-through, click-through strip over the window under
    the logo, painting the logo's tears, peels and puddle (they're kept in window
    coordinates by LogoWidget)."""

    def __init__(self, logo: LogoWidget):
        super().__init__(logo.window())
        self.logo = logo
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.place()
        self.show()
        self.raise_()

    def place(self):
        at = self.logo.mapTo(self.window(), QPoint(0, 0))
        w, h = self.logo.width(), self.logo.height()
        self.setGeometry(QRect(at.x() - 70, at.y() - 30, w + 140, h + DROP_FALL + 46))

    def paintEvent(self, _e):
        lg = self.logo
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.translate(-self.x(), -self.y())
        if lg.puddle > 0.02:   # a little pool where the tears land
            c = QColor(TEAR)
            c.setAlphaF(0.45 * min(1.0, lg.puddle))
            pw = 18 + 52 * lg.puddle
            fx, fy = lg.floor
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawEllipse(QPointF(fx, fy + 2), pw / 2, 2.5 + 1.5 * lg.puddle)
            p.setBrush(QColor(255, 255, 255, round(110 * min(1.0, lg.puddle))))
            p.drawEllipse(QPointF(fx - pw * 0.18, fy + 1.2), pw * 0.12, 0.9)
        for x, y, _vx, _vy, size, splash in lg.tears:
            if splash >= 0:   # a splash: a tiny ring spreading out
                c = QColor(TEAR)
                c.setAlphaF(max(0.0, 1 - splash / 0.35))
                p.setPen(QPen(c, 1.2))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QPointF(x, y), 2 + 10 * splash, 1 + 3 * splash)
                continue
            drop = QPainterPath(QPointF(x, y - size * 1.9))   # a teardrop, point up
            drop.cubicTo(QPointF(x + size * 0.3, y - size), QPointF(x + size, y - size * 0.4),
                         QPointF(x + size, y))
            drop.arcTo(QRectF(x - size, y - size, 2 * size, 2 * size), 0, -180)
            drop.cubicTo(QPointF(x - size, y - size * 0.4), QPointF(x - size * 0.3, y - size),
                         QPointF(x, y - size * 1.9))
            p.setPen(QPen(QColor(40, 110, 170, 160), 0.8))
            p.setBrush(TEAR)
            p.drawPath(drop)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 200))
            p.drawEllipse(QPointF(x - size * 0.35, y - size * 0.2), size * 0.25, size * 0.35)
        c1 = QColor(theme.T["accent"])
        k = max(1.0, lg.mark / 32 * 1.3)
        for x, y, _vx, _vy, ang, life in lg.peels:   # onion layers tumbling off
            p.save()
            p.translate(x, y)
            p.rotate(ang)
            p.scale(k, k)
            p.setOpacity(min(1.0, life))
            peel = QPainterPath(QPointF(-8, 3))
            peel.quadTo(QPointF(0, -8), QPointF(8, 3))
            peel.quadTo(QPointF(0, -3), QPointF(-8, 3))
            p.setPen(QPen(c1, 1.4))
            p.setBrush(QColor("white"))
            p.drawPath(peel)
            p.restore()
        p.end()


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
        # the crying Easter egg
        self._clicks: list[float] = []
        self.squish = 0.0          # a click's wobble, 1 just clicked, easing to 0
        self.welling = 0.0         # eyes showing and watering, 0..1
        self.cry_until = 0.0       # crying until then (time.monotonic)
        self.tears: list[list[float]] = []   # [x, y, vx, vy, size, splash age or -1]
        self.peels: list[list[float]] = []   # [x, y, vx, vy, angle, life]
        self.puddle = 0.0          # the pool under it, 0..~1.2
        self.floor = (0.0, 0.0)    # where tears land, window coordinates
        self._tear_debt = 0.0
        self._layer: _TearLayer | None = None
        self._t0 = time.monotonic()
        self._last = self._t0
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.CoarseTimer)
        self._timer.timeout.connect(self._step)
        appstate.pause_in_background(self, self._resume, self._timer.stop)

    # ---- the crying Easter egg
    @property
    def crying(self) -> bool:
        return time.monotonic() < self.cry_until

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.poke()
        super().mousePressEvent(e)

    def poke(self):
        """One click: a wobble; enough quick ones and it cries; while crying, a peel."""
        now = time.monotonic()
        self.squish = 1.0
        if self.crying:
            self.cry_until = now + CRY_S
            self._peel()
            return
        self._clicks = [t for t in self._clicks if now - t < CRY_WINDOW] + [now]
        n = len(self._clicks)
        if n >= CRY_CLICKS:
            usage.used("egg-onion-cried")   # the name only (usage.py)
            self._clicks.clear()
            self.cry_until = now + CRY_S
            self.welling = 1.0
            self._resume()
        elif n >= WELL_UP_AT:
            self.welling = max(self.welling, (n - WELL_UP_AT + 1) / (CRY_CLICKS - WELL_UP_AT + 1))

    def _eyes(self) -> tuple[QPointF, QPointF]:
        """Its eyes, in this widget's coordinates."""
        s, x0 = float(self.mark), float(self.pad)
        return (QPointF(x0 + s * 0.4, self.pad + s * 0.6),
                QPointF(x0 + s * 0.6, self.pad + s * 0.6))

    def _to_window(self, pt: QPointF) -> QPointF:
        return QPointF(self.mapTo(self.window(), QPoint(0, 0))) + pt

    def _peel(self):
        top = self._to_window(QPointF(self.width() / 2, self.pad + self.mark * 0.42))
        side = random.choice((-1, 1))
        # flung out sideways (there's no room above: the logo sits at the top)
        self.peels.append([top.x(), top.y(), side * random.uniform(70, 130),
                           -random.uniform(40, 80), random.uniform(0, 360), 1.6])
        self._tear_debt += 3   # a burst of tears with it

    def _cry_step(self, dt: float):
        crying = self.crying
        self.squish = max(0.0, self.squish - dt * 4)
        if not crying and self.welling > 0 and not self._clicks:
            self.welling = max(0.0, self.welling - dt * 0.6)
        if self._clicks and time.monotonic() - self._clicks[-1] > CRY_WINDOW:
            self._clicks.clear()
        busy = crying or self.tears or self.peels or self.puddle > 0.01
        if not busy:
            self.puddle = 0.0
            if self._layer is not None:
                self._layer.deleteLater()
                self._layer = None
            return
        if self._layer is None and self.window() is not self:
            self._layer = _TearLayer(self)
        base = self._to_window(QPointF(self.width() / 2, self.height() + DROP_FALL))
        self.floor = (base.x(), base.y())
        if crying:   # two streams of tears, faster with every peel
            self._tear_debt += dt * (7 + 2.5 * len(self.peels))
            self.puddle = min(1.2, self.puddle + dt * 0.12)
        else:
            self.puddle = max(0.0, self.puddle - dt * 0.35)
        while self._tear_debt >= 1:
            self._tear_debt -= 1
            for k, eye in enumerate(self._eyes()):
                e = self._to_window(eye)
                side = -1 if k == 0 else 1
                self.tears.append([e.x() + side * 1.5, e.y() + 1, side * random.uniform(14, 34),
                                   random.uniform(-30, 10), random.uniform(1.6, 2.6), -1.0])
        floor = self.floor[1]
        for tr in self.tears:
            if tr[5] >= 0:
                tr[5] += dt
                continue
            tr[3] += GRAVITY * dt
            tr[0] += tr[2] * dt
            tr[1] += tr[3] * dt
            if tr[1] >= floor:   # landed: splash
                tr[1], tr[5] = floor, 0.0
        self.tears = [tr for tr in self.tears if tr[5] < 0.35][-160:]
        for pl in self.peels:
            pl[3] += GRAVITY * 0.6 * dt
            pl[0] += pl[2] * dt
            pl[1] = min(floor - 2, pl[1] + pl[3] * dt)
            pl[4] += dt * (220 if pl[1] < floor - 2 else 0)
            pl[5] -= dt * (0.25 if pl[1] < floor - 2 else 0.8)
        self.peels = [pl for pl in self.peels if pl[5] > 0]
        if self._layer is not None:
            self._layer.place()
            self._layer.raise_()
            self._layer.update()

    # ---- feeding
    def set_level(self, v: float):
        self._target = max(0.0, min(1.0, float(v)))

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
        if self._layer is not None:   # (it dries up if the window goes)
            self._layer.hide()
        super().hideEvent(e)

    def _step(self):
        now = time.monotonic()
        dt = min(0.1, now - self._last)
        self._last = now
        self.advance(dt)
        self.update()

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
        self._cry_step(dt)

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
        crying = self.crying
        if crying:   # sobbing: a quick shudder
            p.translate(math.sin(t * 31) * 1.1, abs(math.sin(t * 9)) * 0.8)
        if self.squish > 0:   # a click's wobble, from the bottom of the tile
            k = self.squish * math.cos((1 - self.squish) * 14)
            p.translate(c, y0 + s)
            p.scale(1 + 0.08 * k, 1 - 0.1 * k)
            p.translate(-c, -(y0 + s))

        # glow: breathes at rest, flares and flickers warm with the sound
        breathe = 0.5 + 0.5 * math.sin(t * 1.6)
        flicker = 0.85 + 0.15 * math.sin(t * 23) * math.sin(t * 7.3) if lv > 0.05 else 1.0
        glow = _mix(QColor(c2), FLAME, lv * 1.4)
        if crying or self.welling:
            glow = _mix(glow, SOB_BLUE, 1.0 if crying else self.welling * 0.6)
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

        if crying or self.welling > 0.02:
            self._paint_face(p, crying)

        # embers
        for x, y, _vx, _vy, life, size, ci in self.embers:
            ec = QColor(EMBER_COLORS[ci])
            ec.setAlpha(int(255 * min(1.0, life * 1.5)))
            p.setBrush(ec)
            r = size * (0.5 + 0.5 * life)
            p.drawEllipse(QPointF(x, y), r, r)
        p.end()

    def _paint_face(self, p: QPainter, crying: bool):
        """Eyes (and a wobbly mouth) on the onion: watery dots welling up, then
        squeezed shut while it sobs."""
        s = float(self.mark)
        a = 1.0 if crying else min(1.0, self.welling * 1.6)
        ink = QColor(FACE)
        ink.setAlphaF(a)
        lw = max(1.0, s * 0.045)
        for k, e in enumerate(self._eyes()):
            side = -1 if k == 0 else 1
            if crying:   # squeezed shut: > <
                p.setPen(QPen(ink, lw, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.setBrush(Qt.NoBrush)
                d = s * 0.045
                path = QPainterPath(QPointF(e.x() + side * d, e.y() - d))
                path.lineTo(QPointF(e.x() - side * d, e.y()))
                path.lineTo(QPointF(e.x() + side * d, e.y() + d))
                p.drawPath(path)
            else:        # wide, wet eyes
                p.setPen(Qt.NoPen)
                p.setBrush(ink)
                p.drawEllipse(e, s * 0.05, s * 0.06)
                shine = QColor(TEAR)
                shine.setAlphaF(a * self.welling)
                p.setBrush(shine)
                p.drawEllipse(QPointF(e.x(), e.y() + s * 0.05), s * 0.045, s * 0.022)
        mouth = QPainterPath(QPointF(self.pad + s * 0.44, self.pad + s * 0.72))
        mouth.quadTo(QPointF(self.pad + s * 0.5, self.pad + s * (0.66 if crying else 0.69)),
                     QPointF(self.pad + s * 0.56, self.pad + s * 0.72))
        p.setPen(QPen(ink, lw * 0.9, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawPath(mouth)
