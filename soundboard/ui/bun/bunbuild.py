"""Bun's building act (see ui/bun/bunnywidget.py's docstring): `build()`,
`stop_building()` and the dust, junk and sparks it throws. Part of `BunnyWidget`."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget

from soundboard.ui.bun import bunsymbols
from soundboard.ui.bun.bunny import GADGET_SCREEN, H, W
from soundboard.ui.bun.bunbits import (
    BACK_END, CLOUD_END, DASH_END, DUST, FAIL_END, FAIL_SNAP, _Junk, _Note, PARTS, _Puff,
    SCREEN_BARS, SMOKE, _Spark, SWING)

if TYPE_CHECKING:
    from typing import Any

    _Base = QWidget
else:
    _Base = object


class BunnyBuild(_Base):
    if TYPE_CHECKING:   # what BunnyWidget has that these use
        _act_kind: Any
        _act_t: Any
        _blows: Any
        _fail_snap: Any
        _fail_swing: Any
        _fail_t: Any
        _fin_t: Any
        _head: Any
        _home_celebrate: Any
        _home_prop: Any
        _home_sad: Any
        _part_at: Any
        _parts: Any
        _pop_t: Any
        _rng: Any
        bun_h: Any
        burst: Any
        celebrate: Any
        junk: Any
        note_k: Any
        notes: Any
        prop: Any
        puffs: Any
        robot: Any
        sad: Any
        sparks: Any
        stir: Any

    @property
    def building(self) -> bool:
        return self._act_t >= 0

    def build(self):
        """Start the building act (see the module docstring). Harmless if running."""
        if self.building:
            return
        self.stir()
        self._act_kind = "build"
        self._act_t, self._blows = 0.0, 0
        self.celebrate = False
        self.sad = self._home_sad
        self.prop = self._home_prop
        self._parts, self._part_at = 0, [-1.0] * SCREEN_BARS
        self._fail_t = self._fin_t = self._pop_t = -1.0
        self.junk.clear()

    def stop_building(self, ok: bool):
        """End the act: celebrate if `ok` (the build finished), otherwise the failure
        beat plays and he's back to his usual pose, looking sad until the next try."""
        phase = self.act_phase()
        hammering = phase == "hammer"
        self._act_t, self._act_kind = -1.0, "build"
        self._fail_t = self._fin_t = self._pop_t = -1.0
        self.junk = [j for j in self.junk if j.kind == "head"]
        if phase in ("dash", "cloud"):   # still in the cloud: he pops back out of it
            self._pop_t = 0.0
            r = self._bun_rect()
            for _i in range(10):
                self._puff(r.center().x(), r.center().y() + r.height() * 0.15, 50, 9, 0.6)
        self.prop = "star" if ok else self._home_prop
        self.celebrate = ok or self._home_celebrate
        self.sad = self._home_sad if ok else max(self._home_sad, 0.8)
        if ok:
            self.burst(8)
            if hammering and self._parts:
                self._add_part()          # the last part pops on: done
                if not self.robot:
                    self._fin_t = 0.0     # and it plays, beside him
        else:
            self._fail_t = 0.0
            self._fail_snap = hammering
            self._fail_swing = self._swing() if hammering else 0.0

    def _add_part(self):
        cap = SCREEN_BARS if self.robot else PARTS
        if self._parts < cap:
            self._part_at[self._parts] = max(0.0, self._act_t)
            self._parts += 1

    def act_phase(self) -> str | None:
        """'dash' (running off), 'cloud' (off screen), 'back', then 'hammer' (building)
        or 'bat' (the Pong dare), or None."""
        t = self._act_t
        if t < 0:
            return None
        return ("dash" if t < DASH_END else "cloud" if t < CLOUD_END else
                "back" if t < BACK_END else "hammer" if self._act_kind == "build" else "bat")

    def _swing(self) -> float:
        """Hammer position, 0 (raised) .. 1 (on the plank): slow lift, fast strike."""
        k = ((self._act_t - BACK_END) / SWING) % 1.0
        return 1 - k / 0.7 if k < 0.7 else ((k - 0.7) / 0.3) ** 2

    def _bun_rect(self) -> QRectF:
        w = self.bun_h * W / H
        return QRectF((self.width() - w) / 2, (self.height() - self.bun_h + self._head()) / 2,
                      w, self.bun_h)

    def _spawn(self, strength: float = 1.0, calm: bool = False):
        r = self._bun_rect()
        # out of one of the headphone cups (or the mic, when he's holding one),
        # drifting outward so they never cross his face
        spots = [(0.10, 0.52, -1), (0.90, 0.52, 1)]
        if self.prop == "mic":
            spots.append((0.84, 0.66, 1))
        fx, fy, side = self._rng.choice(spots)
        n = _Note(r.left() + r.width() * fx, r.top() + r.height() * fy, self._rng, strength,
                  self.note_k())
        n.vx = side * abs(n.vx) + side * 8
        n.calm = calm
        sym = bunsymbols.pick(self._rng)   # (the theme's hearts, stars...)
        if sym is not None:
            n.kind, n.col = sym
        self.notes.append(n)

    def _puff(self, x, y, spread: float, r: float, life: float, col: QColor = DUST):
        a = self._rng.uniform(0, 2 * math.pi)
        v = self._rng.uniform(0.3, 1.0) * spread
        self.puffs.append(_Puff(x, y, math.cos(a) * v, math.sin(a) * v - spread * 0.3,
                                r * self._rng.uniform(0.7, 1.2), life, col))

    def _at(self, body: QRectF, x: float, y: float) -> QPointF:
        """A point on the 100 x 120 drawing canvas, in widget pixels."""
        s = body.height() / H
        return QPointF(body.left() + x * s, body.top() + y * s)

    def _cloud_spot(self) -> QPointF:
        r = self._bun_rect()
        return QPointF(r.center().x(), r.center().y() + r.height() * 0.12)

    def _toss(self):
        """He's rummaging: something he doesn't need flies out of the cloud."""
        c, r = self._cloud_spot(), self._bun_rect()
        reach = max(8.0, min(self.width() / 2 - r.height() * 0.12, r.width() * 0.85))
        side = self._rng.choice((-1, 1))
        kind = self._rng.choice(("sock", "carrot", "spring", "plank", "duck"))
        self.junk.append(_Junk(kind, c.x() + self._rng.uniform(-0.1, 0.1) * r.width(),
                               c.y() - r.height() * 0.12,
                               side * self._rng.uniform(0.35, 1.0) * reach / 0.75,
                               -r.height() * self._rng.uniform(1.6, 2.1),
                               self._rng.uniform(-700, 700), 1.0))

    def _snap(self):
        """The failed blow lands: the hammer's head flies off and the plank snaps (or
        Robo-Bun's gadget shorts out in sparks), in a puff of smoke."""
        r = self._bun_rect()
        if self.robot:
            c = self._at(r, GADGET_SCREEN.center().x(), GADGET_SCREEN.center().y())
            for _i in range(16):
                a = self._rng.uniform(math.pi * 1.05, math.pi * 1.95)
                v = r.height() * self._rng.uniform(0.8, 1.8)
                self.sparks.append(_Spark(c.x(), c.y(), math.cos(a) * v, math.sin(a) * v,
                                          self._rng.uniform(0.35, 0.7)))
        else:
            c = self._at(r, 98, 109)
            self.junk.append(_Junk("head", c.x(), c.y(), -r.height() * 0.4,
                                   -r.height() * 2.0, 820, FAIL_END - FAIL_SNAP))
            b = self._at(r, 84, 112)
            for _i in range(3):
                self._puff(b.x(), b.y(), 22, 4, 0.5)
        for _i in range(7):
            self._puff(c.x(), c.y() - r.height() * 0.04, 30, r.height() * 0.07, 1.1, SMOKE)
