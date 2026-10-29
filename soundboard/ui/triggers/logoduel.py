"""A brief, silent laser duel between the two logos on the Triggers page.

Click either logo and they trade shots: each one glows at the eye as it charges, fires
a bolt with a white-hot core, and the bolt hits the other logo in a flash of sparks
that knocks it into a wobble. In the last round both fire at once and the bolts clash
in the middle. ROUNDS shots of SHOT_S seconds each, then it's gone."""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from soundboard.ui.kit import theme
from soundboard.ui.kit import appstate
from soundboard.ui.settings import lite

FRAME_MS = 1000 // 24
SHOT_S = 0.5
ROUNDS = 4
CHARGE = 0.2     # each shot, as parts of SHOT_S: the eye glows until this...
HIT = 0.42       # ...the bolt flies until this and hits...
FADE = 0.7       # ...and the beam it leaves is gone by this
SPARKS = 9       # sparks off each hit
GRAVITY = 260.0  # px/s² on the sparks
WHITE = QColor(255, 255, 255)


def _alpha(c: QColor, a: float) -> QColor:
    c = QColor(c)
    c.setAlphaF(max(0.0, min(1.0, a)))
    return c


class LogoDuel(QObject):
    def __init__(self, tab):
        super().__init__(tab)
        self.tab = tab
        self.logos: tuple[QWidget, ...] = ()
        self.overlay: _Lasers | None = None
        tab.installEventFilter(self)

    def bind(self):
        """Optional add-on UI: older versions without a logo keep their own clicks."""
        self.stop()
        for logo in self.logos:
            logo.removeEventFilter(self)
        self.logos = ()
        board = getattr(self.tab.window(), "logo", None)
        pages = getattr(self.tab.panel, "pages", None)
        watch = getattr(pages, "logo", None)
        if isinstance(board, QWidget) and isinstance(watch, QWidget):
            self.logos = (board, watch)
            for logo in self.logos:
                logo.installEventFilter(self)

    def stop(self):
        if self.overlay is not None:
            self.overlay.stop()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Hide:
            self.stop()
        elif (obj in self.logos and event.type() == QEvent.Type.MouseButtonPress
              and event.button() == Qt.MouseButton.LeftButton
              and self.tab.isVisible() and all(w.isVisible() for w in self.logos)
              and not lite.on()):   # (not Windows' Animation effects: off on many PCs)
            if self.overlay is None:
                self.overlay = _Lasers(self, self.tab.window())
            self.overlay.start(self.logos.index(obj))
            event.accept()
            return True
        return False


class _Lasers(QWidget):
    def __init__(self, duel: LogoDuel, host: QWidget):
        super().__init__(host)
        self.duel = duel
        self.host = host
        self.elapsed = 0.0
        self.first = 0
        self._last = 0.0
        self._hits = 0   # shots that have landed (each knocks its target once)
        self.sparks: list[list[float]] = []   # [x, y, vx, vy, life, which logo's colour]
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.timer = QTimer(self)
        self.timer.setInterval(FRAME_MS)
        self.timer.timeout.connect(self._tick)
        appstate.pause_in_background(self, self.stop, self.stop)
        self.hide()

    def start(self, first: int):
        # Repeat clicks restart the same bounded exchange; no queued timers or layers.
        self.first, self.elapsed, self._hits = first, 0.0, 0
        self.sparks = []
        self._last = time.monotonic()
        self.setGeometry(self.host.rect())
        self.show()
        self.raise_()
        self.timer.start()
        self.update()

    def stop(self):
        self.timer.stop()
        self.sparks = []
        self.hide()

    def _tick(self):
        now = time.monotonic()
        self.advance(min(0.1, now - self._last))
        self._last = now

    def advance(self, dt: float):
        self.elapsed += dt
        if (self.elapsed >= SHOT_S * ROUNDS or not self.duel.tab.isVisible()
                or not all(w.isVisible() for w in self.duel.logos)):
            self.stop()
            return
        while self._hits < ROUNDS and self.elapsed >= (self._hits + HIT) * SHOT_S:
            self._land(self._hits)
            self._hits += 1
        for s in self.sparks:
            s[3] += GRAVITY * dt
            s[0] += s[2] * dt
            s[1] += s[3] * dt
            s[4] -= dt * 1.8
        self.sparks = [s for s in self.sparks if s[4] > 0]
        self.setGeometry(self.host.rect())
        self.update()

    def _land(self, shot: int):
        """Shot `shot` hits: sparks fly and the target wobbles (both, in the clash)."""
        source = (self.first + shot) % 2
        a, b = self._eyes(source)
        if shot == ROUNDS - 1:   # the clash in the middle
            at, targets, colours = (a + b) / 2, self.duel.logos, (0, 1, 0, 1)
        else:
            at, targets, colours = b, (self.duel.logos[1 - source],), (source,)
        for i in range(SPARKS * (2 if len(targets) == 2 else 1)):
            ang = random.uniform(0, math.tau)
            speed = random.uniform(60, 150)
            self.sparks.append([at.x(), at.y(), math.cos(ang) * speed,
                                math.sin(ang) * speed - 40, random.uniform(0.7, 1.0),
                                colours[i % len(colours)]])
        for logo in targets:
            poke = getattr(logo, "poke", None)
            if callable(poke):
                poke()

    def _eye(self, widget: QWidget) -> QPointF:
        # through the screen: the overlay isn't a parent of the logos, and mapTo()
        # only maps to a parent
        local = QPointF(widget.width() * 0.5, widget.height() * 0.60)
        eye = getattr(widget, "eye_center", None)
        if callable(eye):
            center = eye()
            if isinstance(center, QPointF):
                local = center
        at = self.mapFromGlobal(widget.mapToGlobal(QPoint(0, 0)))
        return QPointF(at) + local

    def _eyes(self, source: int) -> tuple[QPointF, QPointF]:
        logos = self.duel.logos
        return self._eye(logos[source]), self._eye(logos[1 - source])

    def _colour(self, which: int) -> QColor:
        return QColor(theme.T["accent" if which == 0 else "accent2"])

    def paintEvent(self, _event):
        if len(self.duel.logos) != 2:
            return
        shot = min(ROUNDS - 1, int(self.elapsed / SHOT_S))
        phase = (self.elapsed - shot * SHOT_S) / SHOT_S
        source = (self.first + shot) % 2
        a, b = self._eyes(source)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if shot == ROUNDS - 1:   # both at once, meeting in the middle
            mid = (a + b) / 2
            self._shot(p, a, mid, phase, self._colour(source), hit=False)
            self._shot(p, b, mid, phase, self._colour(1 - source), hit=False)
            self._impact(p, mid, phase, self._colour(source), big=True)
            self._impact(p, mid, phase, self._colour(1 - source), big=True)
        else:
            colour = self._colour(source)
            self._shot(p, a, b, phase, colour, hit=True)
            self._impact(p, b, phase, colour, big=False)
        for x, y, vx, vy, life, which in self.sparks:   # streaks, white-hot at the front
            c = self._colour(int(which))
            at, tail = QPointF(x, y), QPointF(x - vx * 0.05, y - vy * 0.05)
            p.setPen(QPen(_alpha(c, life * 0.45), 5, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap))
            p.drawLine(tail, at)
            p.setPen(QPen(_alpha(c, life), 2.4, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap))
            p.drawLine(tail, at)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_alpha(WHITE, life))
            p.drawEllipse(at, 1.3, 1.3)
        p.end()

    def _glow(self, p: QPainter, at: QPointF, r: float, colour: QColor, a: float,
              core: float = 0.3):
        """A soft round glow, white in the middle (out to `core` of its radius: a
        wide see-through white turns grey on a dark page)."""
        if r <= 0.5 or a <= 0:
            return
        g = QRadialGradient(at, r)
        g.setColorAt(0.0, _alpha(WHITE, a))
        g.setColorAt(core, _alpha(colour, a * 0.9))
        g.setColorAt(1.0, _alpha(colour, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(at, r, r)

    def _shot(self, p: QPainter, a: QPointF, b: QPointF, phase: float, colour: QColor,
              hit: bool):
        """One logo's shot from `a` to `b` at `phase` (0..1 through the shot): it charges
        at the eye, the bolt flies, and the beam it leaves fades and thins."""
        if phase < CHARGE:   # charging: a glow growing at the eye, flickering
            k = phase / CHARGE
            self._glow(p, a, 3 + 7 * k + math.sin(phase * 90) * 0.8, colour, 0.35 + 0.6 * k)
            return
        fly = min(1.0, (phase - CHARGE) / (HIT - CHARGE))
        fly = 1 - (1 - fly) ** 2   # fast out of the eye, easing in
        if phase < HIT:   # in flight: a bolt with a bright head and a trail behind it
            head = a + (b - a) * fly
            tail = a + (b - a) * max(0.0, fly - 0.45)
            fade, thin = 1.0, 1.0
        else:             # it's hit: the beam stays a moment, fading and thinning
            head, tail = b, a
            u = (phase - HIT) / (FADE - HIT)
            if u >= 1:
                return
            fade, thin = 1 - u, 1 - 0.6 * u
        for width, alpha in ((12, 0.16), (7, 0.4), (3.5, 0.85)):
            p.setPen(QPen(_alpha(colour, alpha * fade), width * thin, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap))
            p.drawLine(tail, head)
        p.setPen(QPen(_alpha(WHITE, fade), 1.6 * thin, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        p.drawLine(tail, head)
        # the flash at the eye as it fires, and the bolt's hot head
        self._glow(p, a, 9 * fade, colour, 0.8 * fade if phase < HIT else 0.5 * fade)
        if phase < HIT:
            self._glow(p, head, 7, colour, 1.0)

    def _impact(self, p: QPainter, at: QPointF, phase: float, colour: QColor, big: bool):
        """The hit: a flash and a ring spreading out (the sparks are separate)."""
        if not HIT <= phase < 0.95:
            return
        u = (phase - HIT) / (0.95 - HIT)
        size = 1.4 if big else 1.0
        self._glow(p, at, (10 + 12 * u) * size, colour, (1 - u) ** (2.5 if big else 1.5),
                   core=0.15 if big else 0.3)
        p.setPen(QPen(_alpha(colour, (1 - u) * 0.9), 2.4 * (1 - u) + 0.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        r = (6 + 20 * u) * size
        p.drawEllipse(at, r, r)
