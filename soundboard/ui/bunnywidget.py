"""Bun, alive: the mascot from soundboard/bunny.py in a widget that animates.

He bobs gently, blinks every few seconds and flicks an ear now and then. Feed him
the mic level (`set_level`, 0..1) and he talks along: the mouth opens with your
voice, he bounces, and music notes float up out of him. `burst()` throws a handful
of notes (the test sound); `celebrate=True` makes him hop with twinkling sparkles.

`build()` is for the cable install: he dashes off, a cartoon dust cloud rattles where
he went, and he comes back with a hammer and a plank and hammers away until
`stop_building(ok)`, which ends in a celebration (ok) or back to how he was.

The widget is bigger than Bun himself so there's room around him for the notes,
which also gives him even breathing room in a layout. The timer only runs while
he's on screen.
"""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from soundboard.bunny import H, INK, W, WOOD, draw_bunny, music_note, sparkle

NOTE_COLORS = ("#7c5cff", "#a48bff", "#1fb6ff", "#ff8fae", "#13ce66")
SPARKLE_COLORS = ("#ffcf40", "#ff8fae", "#1fb6ff", "#a48bff")
DUST = QColor("#d9d2e6")
DUST_INK = QColor("#b3a9c7")
# build(): when each part of the act ends, in seconds from the start
DASH_END, CLOUD_END, BACK_END = 0.45, 1.6, 2.1
SWING = 0.55     # one hammer blow, seconds
TALK = 0.05        # mic level that counts as talking (same as the wizard's "Hearing you")
FPS = 30


class _Note:
    __slots__ = ("x", "y", "vx", "vy", "age", "life", "size", "col", "spin")

    def __init__(self, x, y, rng: random.Random, strength: float = 1.0):
        self.x, self.y = x, y
        self.vx = rng.uniform(-18, 18)
        self.vy = -rng.uniform(28, 48) * (0.8 + 0.4 * strength)
        self.age, self.life = 0.0, rng.uniform(1.2, 1.9)
        self.size = rng.uniform(0.75, 1.15)
        self.col = QColor(rng.choice(NOTE_COLORS))
        self.spin = rng.uniform(-25, 25)


class _Puff:
    """A ball of dust: grows, drifts, fades."""
    __slots__ = ("x", "y", "vx", "vy", "r", "age", "life")

    def __init__(self, x, y, vx, vy, r, life):
        self.x, self.y, self.vx, self.vy, self.r = x, y, vx, vy, r
        self.age, self.life = 0.0, life


class BunnyWidget(QWidget):
    def __init__(self, prop: str | None = None, height: int = 110, pad: int = 26,
                 celebrate: bool = False, parent=None):
        super().__init__(parent)
        self.prop = prop
        self.bun_h = height
        self.pad = pad
        self.celebrate = celebrate
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._rng = random.Random()
        self._t0 = time.monotonic()
        self._last = self._t0
        self._level = 0.0          # smoothed mic level
        self._mouth = 0.0
        self._bounce = 0.0         # extra hop height from talking, px
        self._next_blink = self._t0 + self._rng.uniform(1.5, 4)
        self._blink_at = -1.0
        self._next_flick = self._t0 + self._rng.uniform(3, 7)
        self._flick_at = -1.0
        self._note_debt = 0.0
        self.notes: list[_Note] = []
        self.puffs: list[_Puff] = []
        self._home_prop, self._home_celebrate = prop, celebrate
        self._act_t = -1.0         # seconds into build(), or -1 when not building
        self._blows = 0            # hammer blows landed so far
        self._timer = QTimer(self)
        self._timer.setInterval(1000 // FPS)
        self._timer.timeout.connect(self._step)

    def sizeHint(self) -> QSize:
        return QSize(round(self.bun_h * W / H) + 2 * self.pad + 20, self.bun_h + 2 * self.pad)

    minimumSizeHint = sizeHint

    # ------------------------------------------------------------------ inputs
    def set_level(self, level: float):
        """The live mic level, 0..1. Call it as often as you like (the wizard: 25/s)."""
        self._level = max(float(level), self._level * 0.8)

    def burst(self, n: int = 6):
        """Throw a handful of notes out at once."""
        for _ in range(n):
            self._spawn(1.3)

    @property
    def building(self) -> bool:
        return self._act_t >= 0

    def build(self):
        """Start the building act (see the module docstring). Harmless if running."""
        if self.building:
            return
        self._act_t, self._blows = 0.0, 0
        self.celebrate = False

    def stop_building(self, ok: bool):
        """End the act: celebrate if `ok`, otherwise go back to the usual pose."""
        self._act_t = -1.0
        self.prop = "star" if ok else self._home_prop
        self.celebrate = ok or self._home_celebrate
        if ok:
            self.burst(8)

    def act_phase(self) -> str | None:
        """'dash' (running off), 'cloud' (off screen), 'back', 'hammer', or None."""
        t = self._act_t
        if t < 0:
            return None
        return ("dash" if t < DASH_END else "cloud" if t < CLOUD_END else
                "back" if t < BACK_END else "hammer")

    def _swing(self) -> float:
        """Hammer position, 0 (raised) .. 1 (on the plank): slow lift, fast strike."""
        k = ((self._act_t - BACK_END) / SWING) % 1.0
        return 1 - k / 0.7 if k < 0.7 else ((k - 0.7) / 0.3) ** 2

    # ------------------------------------------------------------------ animation
    def showEvent(self, ev):
        self._last = time.monotonic()
        self._timer.start()
        super().showEvent(ev)

    def hideEvent(self, ev):
        self._timer.stop()
        self._level = 0.0
        super().hideEvent(ev)

    def _bun_rect(self) -> QRectF:
        w = self.bun_h * W / H
        return QRectF((self.width() - w) / 2, (self.height() - self.bun_h) / 2, w, self.bun_h)

    def _spawn(self, strength: float = 1.0):
        r = self._bun_rect()
        # out of one of the headphone cups (or the mic, when he's holding one),
        # drifting outward so they never cross his face
        spots = [(0.10, 0.52, -1), (0.90, 0.52, 1)]
        if self.prop == "mic":
            spots.append((0.84, 0.66, 1))
        fx, fy, side = self._rng.choice(spots)
        n = _Note(r.left() + r.width() * fx, r.top() + r.height() * fy, self._rng, strength)
        n.vx = side * abs(n.vx) + side * 8
        self.notes.append(n)

    def _puff(self, x, y, spread: float, r: float, life: float):
        a = self._rng.uniform(0, 2 * math.pi)
        v = self._rng.uniform(0.3, 1.0) * spread
        self.puffs.append(_Puff(x, y, math.cos(a) * v, math.sin(a) * v - spread * 0.3,
                                r * self._rng.uniform(0.7, 1.2), life))

    def _step_act(self, dt: float):
        before = self._act_t
        self._act_t += dt
        phase = self.act_phase()
        r = self._bun_rect()
        if phase == "cloud":
            # the scuffle: dust keeps rolling off the cloud where he ran
            if self._rng.random() < dt * 30:
                self._puff(r.center().x() + self._rng.uniform(-18, 18),
                           r.center().y() + self._rng.uniform(-10, 18), 40, 9, 0.6)
        elif phase == "back" and before < CLOUD_END:
            self.prop = "hammer"
        elif phase == "hammer":
            blows = int((self._act_t - BACK_END) / SWING + 0.3)   # strikes at k = 0.7
            if blows > self._blows:   # just hit the plank: a puff of sawdust, a tink
                self._blows = blows
                x = r.left() + r.width() * 1.04    # where the hammer lands
                y = r.top() + r.height() * 0.9
                for _ in range(3):
                    self._puff(x, y, 26, 4, 0.5)
                if blows % 2 == 0:
                    n = _Note(x, y - 6, self._rng, 0.6)
                    n.col = QColor(self._rng.choice(SPARKLE_COLORS))
                    self.notes.append(n)

    def _step(self):
        now = time.monotonic()
        dt = min(0.1, now - self._last)
        self._last = now
        if self.building:
            self._step_act(dt)
        for f in self.puffs:
            f.age += dt
            f.x += f.vx * dt
            f.y += f.vy * dt
            f.vx *= 1 - dt * 2
            f.vy *= 1 - dt * 2
        self.puffs = [f for f in self.puffs if f.age < f.life]
        talking = self._level > TALK
        # mouth follows the voice with a quick attack and a flappy wobble
        target = min(1.0, self._level * 4) if talking else 0.0
        if talking:
            target *= 0.65 + 0.35 * abs(math.sin((now - self._t0) * 17))
        self._mouth += (target - self._mouth) * min(1.0, dt * (22 if target > self._mouth else 12))
        hop = min(1.0, self._level * 5) * 6 if talking else 0.0
        self._bounce += (hop - self._bounce) * min(1.0, dt * 10)
        # notes: a stream while talking, scaled by how loud
        if talking:
            self._note_debt += dt * (2 + 10 * min(1.0, self._level * 3))
            while self._note_debt >= 1:
                self._note_debt -= 1
                self._spawn(min(1.0, self._level * 3))
        elif self.prop == "headphones":
            self._note_debt += dt * 0.7   # something's always playing in his headphones
            if self._note_debt >= 1:
                self._note_debt = 0.0
                self._spawn(0.5)
        for n in self.notes:
            n.age += dt
            n.x += n.vx * dt
            n.y += n.vy * dt
            n.vx *= 1 - dt * 0.6
        self.notes = [n for n in self.notes if n.age < n.life]
        self._level *= 0.9
        # blink / ear flick schedules
        if now >= self._next_blink:
            self._blink_at = now
            self._next_blink = now + self._rng.uniform(2.2, 5.5)
        if now >= self._next_flick:
            self._flick_at = now
            self._next_flick = now + self._rng.uniform(4, 9)
        self.update()

    def pose(self, now: float | None = None) -> dict:
        """Blink / mouth / ears / vertical offset for the current moment."""
        now = time.monotonic() if now is None else now
        t = now - self._t0
        blink = 0.0
        if self._blink_at >= 0 and (b := now - self._blink_at) < 0.16:
            blink = 1 - abs(b - 0.08) / 0.08
        ears = 3 * math.sin(t * 1.3)
        if self._flick_at >= 0 and (f := now - self._flick_at) < 0.5:
            ears += 14 * math.sin(f / 0.5 * math.pi) * math.cos(f * 30) * (1 - f / 0.5)
        ears += self._mouth * 8 * math.sin(t * 11)
        dy = 2.2 * math.sin(t * 2.2)
        if self.celebrate:
            dy -= 7 * abs(math.sin(t * 3.4))
        dy -= self._bounce * abs(math.sin(t * 9))
        dx, swing, shown = 0.0, 0.0, True
        phase = self.act_phase()
        away = self.width() * 0.5 + self.bun_h * W / H   # far enough to be out of view
        if phase == "dash":      # zooms off to the right in quick hops, ears flat back
            k = self._act_t / DASH_END
            dx, ears = away * k * k, ears - 25
            dy -= 8 * abs(math.sin(self._act_t * 20))
        elif phase == "cloud":
            shown = False
        elif phase == "back":    # hops back in from the right with his tools
            k = (self._act_t - CLOUD_END) / (BACK_END - CLOUD_END)
            dx = away * (1 - k) ** 2
            dy -= 6 * abs(math.sin(self._act_t * 16))
        elif phase == "hammer":
            swing = self._swing()
            dy += 1.5 * swing    # leans into each blow
            ears += 6 * swing
        return {"blink": blink, "mouth": self._mouth, "ears": ears, "dy": dy,
                "dx": dx, "swing": swing, "shown": shown}

    # ------------------------------------------------------------------ paint
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        now = time.monotonic()
        pose = self.pose(now)
        r = self._bun_rect()
        # soft shadow on the "floor", shrinking as he rises
        lift = max(0.0, -pose["dy"])
        shade = QColor(0, 0, 0, max(20, 70 - int(lift * 6)))
        sw = r.width() * (0.62 - lift * 0.012)
        p.setPen(Qt.NoPen)
        p.setBrush(shade)
        if pose["shown"]:
            p.drawEllipse(QRectF(r.center().x() + pose["dx"] - sw / 2, r.bottom() - 4, sw, 8))
        self._paint_puffs(p)
        if self.celebrate:
            t = now - self._t0
            for i, col in enumerate(SPARKLE_COLORS):
                a = t * 0.8 + i * math.pi / 2
                tw = 0.5 + 0.5 * math.sin(t * 4 + i * 1.7)
                x = r.center().x() + math.cos(a) * (r.width() * 0.78)
                y = r.center().y() - 6 + math.sin(a) * (r.height() * 0.48)
                sparkle(p, x, y, 3 + 4 * tw, QColor(col))
        if pose["shown"]:
            draw_bunny(p, r.translated(pose["dx"], pose["dy"]), self.prop,
                       blink=pose["blink"], mouth=pose["mouth"], ears=pose["ears"],
                       swing=pose["swing"])
        else:
            self._paint_scuffle(p)
        for n in self.notes:
            k = n.age / n.life
            alpha = min(1.0, n.age * 6) * (1 - k) ** 1.4
            p.save()
            p.setOpacity(alpha)
            p.translate(n.x, n.y)
            p.rotate(n.spin * math.sin(n.age * 4))
            music_note(p, -5, -8, n.size, n.col)
            p.restore()
        p.end()

    def _paint_puffs(self, p: QPainter):
        p.setPen(Qt.NoPen)
        p.setBrush(DUST)
        for f in self.puffs:
            k = f.age / f.life
            p.setOpacity(0.85 * (1 - k))
            rr = f.r * (0.6 + 0.8 * k)
            p.drawEllipse(QRectF(f.x - rr, f.y - rr, 2 * rr, 2 * rr))
        p.setOpacity(1.0)

    def _paint_scuffle(self, p: QPainter):
        """The cartoon dust-up while he's off fetching his tools: a jiggling cloud with
        bits of plank and stars poking out of it."""
        r = self._bun_rect()
        cx, cy = r.center().x(), r.center().y() + 8
        t = self._act_t
        grow = max(0.0, min(1.0, (t - DASH_END) / 0.2, (CLOUD_END - t) / 0.2))
        p.setPen(QPen(DUST_INK, 1.5))
        p.setBrush(DUST)
        for i in range(7):
            a = i * 2 * math.pi / 7 + t * 3
            rr = (15 + 4 * math.sin(t * 23 + i * 1.9)) * grow
            x = cx + math.cos(a) * 20 * grow
            y = cy + math.sin(a) * 12 * grow
            p.drawEllipse(QRectF(x - rr, y - rr, 2 * rr, 2 * rr))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(cx - 22 * grow, cy - 14 * grow, 44 * grow, 28 * grow))
        k = int(t * 9)   # a new spot every few frames
        for j in range(2):
            a = (k * 2.4 + j * math.pi) % (2 * math.pi)
            x, y = cx + math.cos(a) * 34 * grow, cy + math.sin(a) * 22 * grow
            if (k + j) % 2:
                sparkle(p, x, y, 5 * grow, QColor(SPARKLE_COLORS[(k + j) % 4]))
            else:
                p.save()
                p.translate(x, y)
                p.rotate(math.degrees(a))
                p.setPen(QPen(INK, 1.2))
                p.setBrush(WOOD)
                p.drawRoundedRect(QRectF(-8 * grow, -2.5 * grow, 16 * grow, 5 * grow), 1.5, 1.5)
                p.restore()
