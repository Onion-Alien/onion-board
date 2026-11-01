"""Bun builds your mic: the little show on the Setup tab while Onion Board goes onto
the mic (Windows asking for permission, then loading it).

`start()`: he rolls in from the left, a bit dizzy, pulls a toolbox out from behind
his back, takes a hammer out of it and hammers a speaker together, one part a blow.
He keeps at it until `finish(ok)`:

- ok: the last part pops on, the speaker thumps out music notes, he cheers, then
  scoots off to the right with his toolbox, fading out in a puff before the edge.
- not ok: the speaker shakes, goes BOOM into bits and smoke, and he droops, sighs
  and shuffles off sadly.

Either way `done` fires at the end and the widget hides itself. A result that comes
in early waits until the speaker is mostly built, so the show always makes sense.
Hidden (another tab open) it skips the show and just stops.
"""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy

from soundboard.ui.kit import theme
from soundboard.ui.bun.bunny import H, INK, STEEL, W, WOOD, WOOD_DARK, draw_bunny, sparkle
from soundboard.ui.bun.bunnywidget import (NOTE_COLORS, SPARKLE_COLORS, BunnyWidget, _Note,
                                           paint_note)
from soundboard.ui.kit import reveal
from soundboard.ui.kit.pixels import snap_to_pixels

# when each part of the show ends, in seconds from start()
ROLL_END, DIZZY_END, TOOL_END = 1.1, 1.5, 2.4
SWING = 0.5           # one hammer blow, seconds
PARTS = 4             # frame, front, woofer, tweeter
MIN_BLOWS = PARTS - 1  # a result waits for this much speaker (the last part is the win)
# the endings, seconds from when the result is shown
YAY_SCOOT, YAY_END = 2.6, 4.0
SHAKE, BOOM_SCOOT, BOOM_END = 0.8, 3.0, 4.3
BAR_H = 18            # the pixel progress bar under the show
BAR_PX, BAR_GAP = 7, 3   # one block of it, and the space between blocks
EXPECT_S = 25.0       # a first set-up: the Yes, then ~20 s of Windows reloading its audio
BAR_AT_EXPECT = 0.9   # the bar is this full at EXPECT_S, then keeps creeping (never stuck)
BAR_MAX = 0.97        # how full it gets before the answer is in
SCOOT_S = 0.7         # how long scooting off takes (slower when sad)
BOX = QColor("#e2574c")
BOX_DARK = QColor("#b23a31")
CABINET = QColor("#3a3452")
SMOKE = QColor("#8d8799")


class _Bit:
    """A piece of the broken speaker: flies, spins, bounces on the floor, fades."""
    __slots__ = ("kind", "x", "y", "vx", "vy", "a", "va", "size")

    def __init__(self, kind, x, y, rng: random.Random, size: float):
        self.kind, self.x, self.y, self.size = kind, x, y, size
        self.vx = rng.uniform(-110, 110)
        self.vy = -rng.uniform(90, 170)
        self.a, self.va = rng.uniform(0, 360), rng.uniform(-540, 540)


class SetupShow(BunnyWidget):
    done = Signal()

    def __init__(self, height: int = 58, parent=None, left: bool = False):
        super().__init__(None, height=height, pad=10, parent=parent)
        self._left = left        # the scene starts at the left edge (under left-aligned buttons)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._t = -1.0           # seconds into the show, -1 when not on
        self._expect = EXPECT_S  # about how long the job takes (the bar's pace)
        self._result = None      # what finish() said, until it's shown
        self._end_at = -1.0      # show time the ending began
        self._ok = False
        self._parts = 0
        self._part_at = [-1.0] * PARTS   # show time each part popped on
        self._bits: list[_Bit] = []
        self._booms = 0
        self._poofed = False     # the puff he vanishes in while scooting off
        self.hide()

    def sizeHint(self) -> QSize:
        w = self.bun_h * W / H
        return QSize(round(w * 3.6), self.bun_h + 2 * self.pad + BAR_H)

    def minimumSizeHint(self) -> QSize:
        return QSize(round(self.bun_h * W / H * 2.6), self.bun_h + 2 * self.pad + BAR_H)

    # ------------------------------------------------------------------ inputs
    @property
    def on(self) -> bool:
        return self._t >= 0

    def start(self, expect_s: float = EXPECT_S):
        """Start the show (harmless while it's on). `expect_s`: about how long the job
        takes, for the progress bar's pace."""
        if self.on:
            return
        self._expect = max(1.0, expect_s)
        self._t, self._act_t = 0.0, 0.0   # (_act_t: the base class sees us as mid-act)
        self._result, self._end_at, self._ok = None, -1.0, False
        self._parts, self._part_at = 0, [-1.0] * PARTS
        self._bits, self._booms, self._poofed = [], 0, False
        self.notes, self.puffs = [], []
        self.prop, self.sad, self._sad, self.celebrate = None, 0.0, 0.0, False
        reveal.set_shown(self, True)   # (folds out where the button was)

    def finish(self, ok: bool):
        """How it went: the ending plays once the speaker is far enough along. The first
        answer stands: a failed attempt isn't turned into a cheer by a later status
        redraw that finds an older, still working mic part."""
        if not self.on or self._end_at >= 0 or self._result is not None:
            return
        if not self.isVisible():   # nobody's watching: no show to finish
            self._stop()
            return
        self._result = ok

    def hideEvent(self, ev):
        super().hideEvent(ev)
        # hidden in his ending (a first start plays it on the Setup tab behind the
        # guide, which then opens Sounds): it's over, or the rest played in a flash the
        # next time the tab opened
        if self.on and (self._end_at >= 0 or self._result is not None):
            self._stop()

    def _stop(self):
        self._t = self._act_t = -1.0
        self._result = None
        reveal.set_shown(self, False)   # (he's gone: the empty stage folds away)
        self.done.emit()

    # ------------------------------------------------------------------ the show
    def phase(self) -> str | None:
        """'roll', 'dizzy', 'toolbox', 'build', 'yay', 'shake', 'sad', 'scoot' or None."""
        t = self._t
        if t < 0:
            return None
        if self._end_at >= 0:
            e = t - self._end_at
            if self._ok:
                return "yay" if e < YAY_SCOOT else "scoot"
            return "shake" if e < SHAKE else "sad" if e < BOOM_SCOOT else "scoot"
        return ("roll" if t < ROLL_END else "dizzy" if t < DIZZY_END else
                "toolbox" if t < TOOL_END else "build")

    act_phase = phase

    def _hits(self) -> int:
        return int((self._t - TOOL_END) / SWING) if self._t >= TOOL_END else 0

    def _swing(self) -> float:
        k = ((self._t - TOOL_END) / SWING) % 1.0
        return 1 - k / 0.7 if k < 0.7 else ((k - 0.7) / 0.3) ** 2

    def _step_act(self, dt: float):
        before = self.phase()
        self._t += dt
        self._act_t = self._t
        phase = self.phase()
        r = self._bun_rect()
        if phase == "roll" and self._rng.random() < dt * 25:   # dust kicked up rolling
            x = r.center().x() + self._roll()[0] - r.width() * 0.3
            self._puff(x, r.bottom() - 4, 18, 5, 0.45)
        elif phase == "toolbox" and before != "toolbox":
            self.prop = None
        elif phase == "build":
            if before != "build":   # the hammer out of the box
                self.prop = "hammer"
                self._sparkle_at(r.left() + r.width() * 0.8, r.top() + r.height() * 0.55)
            blows = self._hits()
            if blows > self._parts and self._parts < MIN_BLOWS:
                self._add_part()
            if self._result is not None and blows >= MIN_BLOWS and self._swing() < 0.2:
                self._ending(self._result)   # (at the top of a swing, not mid-blow)
        if self._end_at >= 0:
            self._step_ending(before, phase, dt)
        for b in self._bits:
            b.vy += 520 * dt
            b.x += b.vx * dt
            b.y += b.vy * dt
            b.a += b.va * dt
            if b.y > r.bottom() - 3:          # bounce on the floor, losing most of it
                b.y, b.vy, b.vx, b.va = r.bottom() - 3, -b.vy * 0.35, b.vx * 0.6, b.va * 0.5
        if phase == "scoot" and not self._poofed and self._scoot_k() >= 0.6:
            self._poofed = True   # gone in a puff (well before the edge)
            r = self._bun_rect()
            x = r.center().x() + self._scoot_dx()
            for _ in range(8):
                self._puff(x, r.center().y() + r.height() * 0.2, 40, r.height() * 0.08, 0.6)
        end = YAY_END if self._ok else BOOM_END
        if self._end_at >= 0 and self._t - self._end_at >= end:
            self._stop()

    def _ending(self, ok: bool):
        self._end_at, self._ok, self._result = self._t, ok, None
        if ok:
            while self._parts < PARTS:
                self._add_part()
            self.prop, self.celebrate = "star", True
            self.burst(4)

    def _step_ending(self, before, phase, dt: float):
        e = self._t - self._end_at
        s = self._speaker()
        if self._ok:
            if 0.3 < e < YAY_END - 0.5 and self._rng.random() < dt * 6:   # the music
                n = _Note(s.center().x(), s.top() + s.height() * 0.3, self._rng, 1.2)
                n.vx = self._rng.choice((-1, 1)) * self._rng.uniform(25, 50)
                n.col = QColor(self._rng.choice(NOTE_COLORS))
                self.notes.append(n)
            if phase == "scoot" and before != "scoot":
                self.prop, self.celebrate = None, False
        else:
            if phase == "shake" and self._rng.random() < dt * 14:   # it's not going well
                self._puff(s.center().x() + self._rng.uniform(-8, 8), s.top(), 14, 4, 0.7)
            if phase == "sad" and self._booms == 0:
                self._boom()
            if phase == "sad" and before == "sad" and e > SHAKE + 0.5:
                self.sad = 1.0

    def _boom(self):
        self._booms = 1
        s = self._speaker()
        cx, cy = s.center().x(), s.center().y()
        k = s.width()
        for kind, size in (("woofer", 0.5), ("tweeter", 0.24), ("panel", 0.8),
                           ("panel", 0.8), ("plank", 0.6), ("plank", 0.5)):
            self._bits.append(_Bit(kind, cx, cy, self._rng, k * size))
        for _ in range(14):
            self._puff(cx, cy, 70, 10, 1.4)
        for _ in range(5):
            self._sparkle_at(cx + self._rng.uniform(-k, k), cy + self._rng.uniform(-k, k * 0.4))
        self._parts = 0
        self.prop = None

    def _add_part(self):
        if self._parts < PARTS:
            self._part_at[self._parts] = self._t
            self._parts += 1
            s = self._speaker()
            for _ in range(3):
                self._puff(s.center().x(), s.bottom() - 2, 22, 4, 0.5)

    def _sparkle_at(self, x, y):
        n = _Note(x, y, self._rng, 0.5)
        n.size = 0.5   # (drawn as a sparkle, see paintEvent)
        n.col = QColor(self._rng.choice(SPARKLE_COLORS))
        self.notes.append(n)

    # ------------------------------------------------------------------ layout
    def _bun_rect(self) -> QRectF:
        """Where he stands to build: toolbox on his left, speaker on his right, the
        three of them centred (or from the left edge)."""
        w = self.bun_h * W / H
        left = self._scene_x(w * 2.35) + w * 0.55
        return QRectF(left, (self.height() - BAR_H - self.bun_h) / 2, w, self.bun_h)

    def _scene_x(self, width: float) -> float:
        return 0.0 if self._left else (self.width() - width) / 2

    def _speaker(self) -> QRectF:
        r = self._bun_rect()
        sw, sh = r.width() * 0.62, r.height() * 0.66
        return QRectF(r.right() + r.width() * 0.17, r.bottom() - sh, sw, sh)

    def _toolbox(self) -> QRectF:
        r = self._bun_rect()
        tw, th = r.width() * 0.52, r.height() * 0.28
        return QRectF(r.left() - r.width() * 0.55, r.bottom() - th, tw, th)

    def _roll(self) -> tuple[float, float]:
        """Rolling in: (dx, degrees turned)."""
        r = self._bun_rect()
        if self._t >= ROLL_END:
            return 0.0, 0.0
        k = self._t / ROLL_END
        ease = 1 - (1 - k) ** 3
        return -(r.right() + 4) * (1 - ease), 720 * ease

    def _scoot_k(self) -> float:
        """How far through scooting off, 0..1."""
        if self.phase() != "scoot":
            return 0.0
        start = YAY_SCOOT if self._ok else BOOM_SCOOT
        return min(1.0, (self._t - self._end_at - start) / (SCOOT_S * (1 if self._ok else 1.6)))

    def _scoot_dx(self) -> float:
        """He scoots right, but only as far as there's room: he fades out in a puff of
        dust before the edge, so it never cuts him in half."""
        k = self._scoot_k()
        room = max(0.0, self.width() - self._bun_rect().right() - 4)
        return room * (1 - (1 - k) ** 2)

    def _scoot_alpha(self) -> float:
        k = self._scoot_k()
        return 1.0 if k < 0.45 else max(0.0, 1 - (k - 0.45) / 0.5)

    def pose(self, now=None) -> dict:
        pose = super().pose(now)
        phase = self.phase()
        dx, angle = self._roll()
        swing = 0.0
        if phase == "roll":
            pose["dy"] -= 3 * abs(math.sin(self._t * 9))
        elif phase == "dizzy":   # wobbles to a stop
            k = (self._t - ROLL_END) / (DIZZY_END - ROLL_END)
            angle = 14 * math.sin(k * math.pi * 3) * (1 - k)
            pose["ears"] += 10 * math.sin(k * math.pi * 4)
        elif phase == "toolbox":   # reaches round his back and hauls it out
            k = (self._t - DIZZY_END) / (TOOL_END - DIZZY_END)
            pose["dy"] += 3 * math.sin(min(1.0, k * 2) * math.pi)
            angle = -8 * math.sin(min(1.0, k * 2) * math.pi)
        elif phase == "build":
            swing = self._swing()
            pose["dy"] += 1.5 * swing
            pose["ears"] += 6 * swing
        elif phase == "shake":   # stops mid-swing, ears up: uh oh
            pose["ears"] -= 12
        elif phase == "sad" and (j := self._t - self._end_at - SHAKE) < 0.5:   # BOOM: a jump
            pose["dy"] -= 14 * math.sin(j / 0.5 * math.pi)
            pose["ears"] -= 25 * (1 - j / 0.5)
        elif phase == "scoot":
            dx = self._scoot_dx()
            pose["dy"] -= 5 * abs(math.sin(self._t * (18 if self._ok else 10)))
            pose["ears"] -= 22 if self._ok else -8
        pose.update(dx=dx, angle=angle, swing=swing)
        return pose

    # ------------------------------------------------------------------ paint
    def paintEvent(self, ev):
        if not self.on:
            return
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pose = self.springy(self.pose())
        r = self._bun_rect()
        phase = self.phase()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, round(45 * self._scoot_alpha())))
        sw = r.width() * 0.62
        p.drawEllipse(QRectF(r.center().x() + pose["dx"] - sw / 2, r.bottom() - 4, sw, 8))
        self._paint_progress(p)
        self._paint_toolbox(p, phase)
        self._paint_speaker(p, phase)
        self._paint_puffs(p)
        self._paint_bits(p)
        if self.celebrate:
            t = self._t
            for i, col in enumerate(SPARKLE_COLORS):
                a = t * 0.8 + i * math.pi / 2
                tw = 0.5 + 0.5 * math.sin(t * 4 + i * 1.7)
                sparkle(p, r.center().x() + pose["dx"] + math.cos(a) * r.width() * 0.75,
                        r.center().y() - 6 + math.sin(a) * r.height() * 0.45,
                        3 + 4 * tw, QColor(col))
        body = r.translated(pose["dx"], pose["dy"])
        p.save()
        p.setOpacity(self._scoot_alpha())
        p.translate(body.center())
        p.rotate(pose["angle"])
        p.translate(-body.center())
        draw_bunny(p, body, self.prop, blink=pose["blink"], mouth=pose["mouth"],
                   ears=pose["ears"], swing=pose["swing"], sad=pose["sad"])
        p.restore()
        for n in self.notes:   # (size < 0.6: a sparkle, not a note)
            paint_note(p, n)
        p.end()

    def progress(self) -> float:
        """How far along the bar shows (0-1). Windows says nothing until it's done, so
        it's BAR_AT_EXPECT full at the expected time and keeps creeping after it (a slow
        PC's 35 s never sits still at the end), and fills once the answer is in."""
        if not self.on:
            return 0.0
        if self._result is not None or self._end_at >= 0:
            return 1.0
        k = self._expect * (1 - BAR_AT_EXPECT) / BAR_AT_EXPECT
        return min(BAR_MAX, self._t / (self._t + k))

    def _paint_progress(self, p: QPainter):
        """A row of little square blocks under the show, lit green as it goes (amber
        when it didn't work), the leading one pulsing: something is happening."""
        t = theme.T
        w = self.bun_h * W / H * 2.35   # as wide as toolbox, Bun and speaker together
        n = max(8, int((w + BAR_GAP) // (BAR_PX + BAR_GAP)))
        total = n * (BAR_PX + BAR_GAP) - BAR_GAP
        x0 = self._scene_x(total)
        y = self.height() - BAR_H + (BAR_H - BAR_PX) / 2
        failed = self._end_at >= 0 and not self._ok
        lit = QColor(t["warn_text"] if failed else t["ok_text"])
        off = QColor(t["card_hi"])
        frac = self.progress()
        done = frac * n
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(n):
            col = QColor(lit if i < int(done) else off)
            if i == int(done) and frac < 1:   # the leading block: pulses
                col = QColor(lit)
                col.setAlphaF(0.35 + 0.35 * (0.5 + 0.5 * math.sin(self._t * 6)))
            p.setBrush(col)
            p.drawRoundedRect(QRectF(x0 + i * (BAR_PX + BAR_GAP), y, BAR_PX, BAR_PX), 1.5, 1.5)

    def _paint_toolbox(self, p: QPainter, phase):
        if phase in ("roll", "dizzy"):
            return
        box = self._toolbox()
        r = self._bun_rect()
        lid = 0.0   # how far open, 0..1
        if phase == "toolbox":   # flies out from behind him in an arc, lands, opens
            k = (self._t - DIZZY_END) / (TOOL_END - DIZZY_END)
            fly = min(1.0, k / 0.55)
            start = QPointF(r.center().x(), r.center().y())
            end = box.center()
            x = start.x() + (end.x() - start.x()) * fly
            y = start.y() + (end.y() - start.y()) * fly - math.sin(fly * math.pi) * r.height() * 0.5
            scale = 0.35 + 0.65 * fly
            box = QRectF(x - box.width() * scale / 2, y - box.height() * scale / 2,
                         box.width() * scale, box.height() * scale)
            lid = max(0.0, min(1.0, (k - 0.65) / 0.25))
        else:
            lid = 1.0
        if phase == "scoot":   # he takes it with him
            box.translate(self._scoot_dx(), 0)
            p.save()
            p.setOpacity(self._scoot_alpha())
        ink = QPen(INK, 1.6)
        ink.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        # the handle, then the box, then the lid hinged at the back
        p.setPen(QPen(INK, 2.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        hw = box.width() * 0.34
        if lid < 0.5:
            p.drawArc(QRectF(box.center().x() - hw / 2, box.top() - box.height() * 0.32,
                             hw, box.height() * 0.6), 0, 180 * 16)
        p.setPen(ink)
        p.setBrush(BOX)
        p.drawRoundedRect(box, 2.5, 2.5)
        p.setBrush(BOX_DARK)
        p.drawRect(QRectF(box.center().x() - 2.5, box.top() + 2, 5, 4))   # the latch
        if lid > 0:   # tools poking out
            p.setPen(QPen(INK, 1.2))
            p.setBrush(STEEL)
            p.drawRoundedRect(QRectF(box.left() + box.width() * 0.2, box.top() - 5 * lid, 4,
                                     6 * lid), 1, 1)
            p.setBrush(WOOD)
            p.drawRoundedRect(QRectF(box.left() + box.width() * 0.6, box.top() - 7 * lid, 3.5,
                                     8 * lid), 1, 1)
        p.save()
        p.translate(box.left(), box.top())
        p.rotate(-40 * lid)   # flipped up and back, ajar
        p.setPen(ink)
        p.setBrush(BOX_DARK)
        p.drawRoundedRect(QRectF(0, -box.height() * 0.28, box.width(), box.height() * 0.28),
                          2, 2)
        p.restore()
        if phase == "scoot":
            p.restore()

    def _paint_speaker(self, p: QPainter, phase):
        if self._parts == 0:
            return
        s = self._speaker()
        e = self._t - self._end_at if self._end_at >= 0 else 0.0
        if phase == "shake":
            s.translate(math.sin(self._t * 70) * 2.5 * e / SHAKE, 0)
        if self._ok and 0.3 < e:   # thumping to the beat
            k = 1 + 0.07 * abs(math.sin(e * 9))
            c = s.center()
            s = QRectF(c.x() - s.width() * k / 2, s.bottom() - s.height() * k,
                       s.width() * k, s.height() * k)
        if phase == "scoot" and self._ok:   # fades away once he's gone
            p.setOpacity(max(0.0, 1 - (e - YAY_SCOOT - SCOOT_S) / 0.5))
        accent = QColor(theme.T["accent"])
        ink = QPen(INK, 1.8)
        ink.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        def pop(i: int) -> float:   # each part springs on a little bigger, then settles
            k = (self._t - self._part_at[i]) / 0.25
            return 1.0 if k >= 1 else 0.4 + 0.6 * k + 0.25 * math.sin(k * math.pi)

        def scaled(rect: QRectF, k: float) -> QRectF:
            c = rect.center()
            return QRectF(c.x() - rect.width() * k / 2, c.y() - rect.height() * k / 2,
                          rect.width() * k, rect.height() * k)

        p.setPen(ink)
        p.setBrush(WOOD)
        frame = scaled(s, pop(0))
        p.drawRoundedRect(frame, 4, 4)
        if self._parts >= 2:
            p.setBrush(CABINET)
            p.drawRoundedRect(scaled(s.adjusted(3, 3, -3, -3), pop(1)), 3, 3)
        cx = s.center().x()
        if self._parts >= 3:
            k = pop(2)
            rr = s.width() * 0.32 * k
            cy = s.top() + s.height() * 0.64
            p.setBrush(STEEL)
            p.drawEllipse(QPointF(cx, cy), rr, rr)
            p.setBrush(accent)
            p.drawEllipse(QPointF(cx, cy), rr * 0.55, rr * 0.55)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(INK)
            p.drawEllipse(QPointF(cx, cy), rr * 0.18, rr * 0.18)
        if self._parts >= 4:
            k = pop(3)
            rr = s.width() * 0.13 * k
            cy = s.top() + s.height() * 0.24
            p.setPen(ink)
            p.setBrush(STEEL)
            p.drawEllipse(QPointF(cx, cy), rr, rr)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(accent.lighter(130))
            p.drawEllipse(QPointF(cx, cy), rr * 0.45, rr * 0.45)
        if self._parts < PARTS and self._end_at < 0:   # nails waiting, a work in progress
            p.setPen(QPen(WOOD_DARK, 1.2))
            p.drawLine(QPointF(frame.left() + 3, frame.top() + 3),
                       QPointF(frame.left() + 6, frame.top() + 6))
        p.setOpacity(1.0)

    def _paint_bits(self, p: QPainter):
        if not self._bits:
            return
        e = self._t - self._end_at
        p.setOpacity(max(0.0, min(1.0, (BOOM_END - e) / 0.8)))
        accent = QColor(theme.T["accent"])
        for b in self._bits:
            p.save()
            p.translate(b.x, b.y)
            p.rotate(b.a)
            p.setPen(QPen(INK, 1.4))
            if b.kind in ("woofer", "tweeter"):
                rr = b.size / 2
                p.setBrush(STEEL)
                p.drawEllipse(QPointF(0, 0), rr, rr)
                p.setBrush(accent if b.kind == "woofer" else accent.lighter(130))
                p.drawEllipse(QPointF(0, 0), rr * 0.5, rr * 0.5)
            else:
                p.setBrush(CABINET if b.kind == "panel" else WOOD)
                p.drawRoundedRect(QRectF(-b.size / 2, -2.5, b.size, 5), 1.5, 1.5)
            p.restore()
        p.setOpacity(1.0)

    def _paint_puffs(self, p: QPainter):
        """Dust while building, grey smoke once it's broken."""
        if not self._bits:
            super()._paint_puffs(p)
            return
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(SMOKE)
        for f in self.puffs:
            k = f.age / f.life
            p.setOpacity(0.7 * (1 - k))
            rr = f.r * (0.6 + 0.9 * k)
            p.drawEllipse(QRectF(f.x - rr, f.y - rr, 2 * rr, 2 * rr))
        p.setOpacity(1.0)
