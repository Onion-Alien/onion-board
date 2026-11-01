"""Bun at work beside a window's title: `ActBunny` plays one act on a loop (and now and
then a one-off, `play`) the way the Live controls' DJ does (speedpitch.DjBunny).

- Edit sound: `snipping`, scissors through a little waveform; the sound's speed plays it
  faster or slower and its pitch stretches him up or squashes him (`ActBunny.tune`).
- Record a sound: the mic in his paw (he talks along with the level, BunnyWidget) and
  `rec_light`, a red light blinking on his ear cup while it records; `mic_check` idle.
- Recently deleted: `in_bin`, peeking out of a bin; `bring_back` throws a sound tile up
  out of it, `bye` waves one off for good.
- Free sound packs: `box_pat` beside a parcel, `box_run` running with it while a pack
  downloads, `box_open` when it lands: notes fly out.
- What's new: `present`, he unwraps a present and a star pops out.

Acts are skits (ui/bun/bunskits.py): a function of their time alone, filling a `Kit`
on Bun's 100 x 120 canvas, so any frame can be drawn on its own. No words, so nothing to
translate. In lite mode he holds still like every other Bun.
"""
from __future__ import annotations

import math
import time
from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

from soundboard.ui.bun.bunny import music_note
from soundboard.ui.bun.bunnywidget import BunnyWidget
from soundboard.ui.bun.bunprops import _star
from soundboard.ui.bun.bunskitkit import (Kit, _ink, _oval, _sparkles, bump, burst, eseg,
                                          held, lerp, mark, paw, puff, seg)
from soundboard.ui.kit import theme
from soundboard.ui.settings import lite

Act = tuple[float, Callable[[Kit, float], None]]   # (seconds, act)
ACT_H = 72   # Bun's height beside a window's title, px (the Live controls DJ's)

STEEL = QColor("#c9ccd8")
CARD = QColor("#c98a4b")        # the parcel
CARD_DARK = QColor("#9a6532")
TAPE = QColor("#e8d3a8")
BIN = QColor("#6a6288")
BIN_HI = QColor("#857ca6")
REC = QColor("#ff3b4f")
GOLD = QColor("#ffcf40")
CONFETTI = ("#ffcf40", "#ff8fae", "#1fb6ff", "#a48bff", "#4fe0a0")


def _accent(alpha: float = 1.0) -> QColor:
    c = QColor(theme.T["accent"])
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def _note(p, x, y, fade, i):
    music_note(p, x - 4, y - 8, 0.8, _accent(fade))


def _confetti(p, x, y, fade, i):
    c = QColor(CONFETTI[i % len(CONFETTI)])
    c.setAlphaF(fade)
    p.save()
    p.translate(x, y)
    p.rotate(i * 47 + fade * 220)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawRoundedRect(QRectF(-2.2, -1.2, 4.4, 2.4), 0.8, 0.8)
    p.restore()


# ---------------------------------------------------------------------- Edit sound
SNIP_LOOP = 3.6
_CUT = 62.0   # where the scissors cut the waveform
_WAVE = (8.0, 106.0, 92.0, 118.0)   # left, top, right, bottom of the waveform strip
_BARS = (0.35, 0.7, 0.5, 0.95, 0.6, 0.8, 0.4, 0.9, 0.55, 0.75, 0.45, 0.85, 0.6, 0.3)


def snipping(kit: Kit, t: float):
    """Edit sound: a strip of waveform at his feet, held in one paw; the scissors in the
    other cut its end off, which drops away, and a fresh end slides back in."""
    t %= SNIP_LOOP
    kit.prop = ""
    reach = eseg(t, 0.1, 0.6) * (1 - eseg(t, 2.6, 3.2))
    snips = (bump(t, 0.7, 1.0), bump(t, 1.05, 1.35))
    shut = max(snips)
    sx = lerp(84, _CUT + 13, reach)
    fall = seg(t, 1.35, 2.2)
    back = eseg(t, 2.8, 3.5)
    kit.world.append(lambda p: _wave(p, fall, back))
    kit.world.append(lambda p: paw(p, 20, 108, -10))
    kit.world.append(lambda p: _scissors(p, sx, lerp(90, 96, reach), 1 - shut, reach))
    kit.add(nod=-6 * reach + 2 * shut, dip=2 * reach)   # leaning in to cut
    kit.most(blink=held(t, 1.55, 2.0, 0.1))   # a happy blink at the clean cut
    kit.world.append(lambda p: _sparkles(p, t - 1.4, _CUT, 104, n=5, life=0.6, salt=3))


def _wave(p: QPainter, fall: float, back: float):
    left, top, right, bottom = _WAVE
    p.save()
    for part, (a, b) in enumerate(((left, _CUT), (_CUT, right))):
        dx = dy = 0.0
        alpha = 1.0
        if part == 1:
            if fall > 0 and back <= 0:   # the cut end dropping away
                dx, dy, alpha = 6 * fall, 10 * fall * fall, 1 - fall
            elif back > 0:               # a fresh end sliding in
                dx, alpha = 14 * (1 - back), back
        if alpha <= 0.01:
            continue
        p.setOpacity(alpha)
        p.setPen(_ink(1.4))
        p.setBrush(QColor("#2b2340"))
        p.drawRoundedRect(QRectF(a + dx, top + dy, b - a, bottom - top), 2.5, 2.5)
        p.setPen(QPen(_accent(), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        mid = (top + bottom) / 2 + dy
        n = len(_BARS)
        for i, h in enumerate(_BARS):
            x = left + 4 + i * (right - left - 8) / (n - 1)
            if a + 1.5 < x < b - 1.5:
                half = h * (bottom - top - 5) / 2
                p.drawLine(QPointF(x + dx, mid - half), QPointF(x + dx, mid + half))
    p.restore()


def _scissors(p: QPainter, x: float, y: float, open_: float, k: float):
    """Chunky cartoon scissors, the pivot at (x, y), pointing down and left at the
    waveform; `open_` 0..1 spreads the blades. His paw holds the handles."""
    if k <= 0.01:
        return
    p.save()
    p.setOpacity(min(1.0, k * 2))
    p.translate(x, y)
    p.rotate(-38)
    for side in (1, -1):   # (the lower blade first: the upper one crosses over it)
        p.save()
        p.rotate(side * 16 * open_)
        blade = QPainterPath(QPointF(1, side * 1.5))
        blade.cubicTo(QPointF(-8, side * 3.6), QPointF(-17, side * 2.4), QPointF(-23, 0))
        blade.cubicTo(QPointF(-15, -side * 0.6), QPointF(-6, -side * 1.2), QPointF(1, -side * 0.8))
        blade.closeSubpath()
        p.setPen(_ink(1.4))
        p.setBrush(STEEL)
        p.drawPath(blade)
        p.setPen(_ink(1.4))   # the handle ring, with its hole
        p.setBrush(REC)
        p.drawEllipse(QRectF(3, side * 5 - 4.5, 11, 9))
        p.setBrush(QColor("#2b2340"))
        p.drawEllipse(QRectF(6.2, side * 5 - 2.2, 4.6, 4.4))
        p.restore()
    _oval(p, 0, 0, 3.2, 3.2, QColor("#ffcf40"), _ink(1.0))   # the screw
    p.restore()
    paw(p, x + 8, y + 7, 15)


# ---------------------------------------------------------------------- Record a sound
MIC_LOOP = 4.5


def mic_check(kit: Kit, t: float):
    """Record a sound, waiting: now and then he leans to the mic and taps it."""
    t %= MIC_LOOP
    lean = held(t, 2.2, 3.4, 0.25)
    kit.add(nod=7 * lean, dip=1.5 * lean)
    for at in (2.6, 2.9):   # two taps: a little jolt and a ring off the mic
        kit.add(dy=-1.2 * bump(t, at, at + 0.12))
        kit.world.append(lambda p, at=at: _ring(p, seg(t, at, at + 0.5)))
    kit.world.append(lambda p: mark(p, 88, 22, "?", held(t, 3.0, 3.9, 0.15)))


def _ring(p: QPainter, k: float):
    if not 0 < k < 1:
        return
    p.save()
    p.setPen(QPen(_accent(1 - k), 1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    r = 9 + 8 * k
    p.drawArc(QRectF(79.5 - r, 84 - r, 2 * r, 2 * r), 30 * 16, 120 * 16)
    p.restore()


REC_LOOP = 1.2


def rec_light(kit: Kit, t: float):
    """Record a sound, recording: a red light blinking on his ear cup, his ears up."""
    t %= REC_LOOP
    on = held(t, 0.0, 0.7, 0.08)
    kit.add(ears=-5)
    kit.front.append(lambda p: _rec(p, on))


def _rec(p: QPainter, on: float):
    glow = QColor(REC)
    glow.setAlphaF(0.4 * on)
    _oval(p, 86.5, 70, 15, 15, glow)
    dark = QColor("#7a1c26")
    c = QColor.fromRgbF(lerp(dark.redF(), REC.redF(), on), lerp(dark.greenF(), REC.greenF(), on),
                        lerp(dark.blueF(), REC.blueF(), on))
    _oval(p, 86.5, 70, 7.5, 7.5, c, _ink(1.2))
    _oval(p, 85.2, 68.8, 2.4, 2.0, QColor(255, 255, 255, round(200 * on)))


# ---------------------------------------------------------------------- Recently deleted
BIN_LOOP = 4.4
_IN = 9.0   # how far down into the bin he sits (canvas units)
RIM = 94.0  # the middle of the bin's rim: he isn't drawn below it (ActBunny)


def in_bin(kit: Kit, t: float):
    """Recently deleted: Bun sitting in a bin, looking one way then the other, and
    ducking down out of sight for a moment."""
    t %= BIN_LOOP
    kit.prop = ""
    look = math.sin(t / BIN_LOOP * 2 * math.pi)
    duck = bump(t, 2.9, 3.7)
    kit.add(dy=_IN + 14 * duck * duck, nod=8 * look, ears=4 * duck)
    kit.most(blink=duck)
    kit.world.append(_bin)


def bring_back(kit: Kit, t: float):
    """Recently deleted, Bring back: he pops up and throws a sound tile up out of the bin."""
    kit.prop = ""
    pop = bump(t, 0.0, 0.7)
    kit.add(dy=_IN - 10 * pop, ears=-10 * pop)
    kit.most(mouth=0.5 * held(t, 0.1, 0.9, 0.1), blink=held(t, 0.9, 1.4, 0.1))
    k = seg(t, 0.3, 1.4)
    if 0 < k < 1:
        x, y = lerp(80, 96, k), 90 - 80 * k + 50 * k * k
        kit.world.append(lambda p: _tile(p, x, y, k * 200, 1 - eseg(k, 0.75, 1)))
    throw = held(t, 0.05, 0.5, 0.1)
    if throw:
        kit.world.append(lambda p: paw(p, lerp(72, 84, throw), lerp(94, 80, throw), 20))
    kit.world.append(_bin)
    kit.world.append(lambda p: _sparkles(p, t - 0.9, 90, 60, n=7, life=0.7, salt=11))


def bye(kit: Kit, t: float):
    """Recently deleted, Delete for good: a puff over the bin and he waves it off."""
    kit.prop = ""
    kit.add(dy=_IN)
    wave = held(t, 0.3, 1.8, 0.2)
    if wave:
        swing = 14 * math.sin(t * 11) * wave
        kit.world.append(lambda p: paw(p, 76 + 0.2 * swing, lerp(96, 66, wave), swing))
    kit.most(blink=held(t, 0.5, 1.6, 0.15))
    kit.add(nod=-4 * wave)
    kit.world.append(_bin)
    for i in range(5):   # the puff it goes up in
        a = i * 1.26
        k = seg(t, 0.0, 0.9)
        if 0 < k < 1:
            kit.world.append(lambda p, a=a, k=k: puff(
                p, 82 + 12 * math.cos(a) * k, 34 + 8 * math.sin(a) * k - 10 * k,
                4 + 5 * k, 1 - k))


def _bin(p: QPainter):
    body = QPainterPath(QPointF(9, 96))
    body.lineTo(91, 96)
    body.lineTo(88, 125)   # (past his canvas, over his feet and tail, to the widget's edge)
    body.lineTo(12, 125)
    body.closeSubpath()
    p.setPen(_ink(1.8))
    p.setBrush(BIN)
    p.drawPath(body)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(BIN_HI)   # its ridges, down the front
    for x in (26, 47.5, 69):
        p.drawRoundedRect(QRectF(x, 101, 5, 19), 2.5, 2.5)
    p.setPen(_ink(1.8))
    p.setBrush(BIN_HI)
    p.drawRoundedRect(QRectF(5, 90, 90, 8), 4, 4)   # the rim


def _tile(p: QPainter, x: float, y: float, turn: float, alpha: float):
    if alpha <= 0:
        return
    p.save()
    p.setOpacity(alpha)
    p.translate(x, y)
    p.rotate(turn)
    p.setPen(_ink(1.3))
    p.setBrush(_accent())
    p.drawRoundedRect(QRectF(-7, -7, 14, 14), 3.5, 3.5)
    music_note(p, -4.5, -6, 0.75, QColor("#ffffff"))
    p.restore()


# ---------------------------------------------------------------------- Free sound packs
PAT_LOOP = 3.0
RUN_LOOP = 0.8


def box_pat(kit: Kit, t: float):
    """Free sound packs, idle: a parcel in front of him, which he pats with each paw."""
    t %= PAT_LOOP
    kit.prop = ""
    left, right = bump(t, 0.3, 0.6), bump(t, 0.8, 1.1)
    kit.world.append(lambda p: _box(p, 50, 109, 0.0))
    kit.world.append(lambda p: paw(p, 36, 98 - 4 * left, -10))
    kit.world.append(lambda p: paw(p, 64, 98 - 4 * right, 10))
    kit.add(nod=3 * (right - left))


def box_run(kit: Kit, t: float):
    """Free sound packs, downloading: he runs on the spot with the parcel in his arms."""
    t %= RUN_LOOP
    kit.prop = ""
    step = abs(math.sin(t / RUN_LOOP * 2 * math.pi))
    y = 98 - 3 * step
    kit.add(dy=-4 * step, ears=10, nod=2 * math.sin(t / RUN_LOOP * 2 * math.pi))
    kit.world.append(lambda p: _box(p, 50, y, 0.0))
    kit.world.append(lambda p: paw(p, 32, y - 2, -20))
    kit.world.append(lambda p: paw(p, 68, y - 2, 20))
    side = 1 if t < RUN_LOOP / 2 else -1   # a puff of dust off each foot
    k = (t % (RUN_LOOP / 2)) / (RUN_LOOP / 2)
    kit.world.append(lambda p: puff(p, 50 + side * (22 + 6 * k), 117 - 3 * k, 2.5 + 3 * k,
                                    0.8 * (1 - k)))


def box_open(kit: Kit, t: float):
    """Free sound packs, a pack added: down goes the parcel, its flaps pop and notes fly
    out; paws up."""
    kit.prop = ""
    drop = eseg(t, 0.0, 0.25)
    flaps = eseg(t, 0.3, 0.55)
    kit.world.append(lambda p: _box(p, 50, lerp(98, 109, drop), flaps))
    kit.add(dy=-6 * bump(t, 0.25, 0.65))
    cheer = held(t, 0.5, 1.9, 0.2)
    if cheer:
        kit.world.append(lambda p: paw(p, 18, lerp(98, 74, cheer), -30))
        kit.world.append(lambda p: paw(p, 82, lerp(98, 74, cheer), 30))
        kit.most(blink=cheer)
        kit.add(ears=-10 * cheer)
    kit.world.append(lambda p: burst(p, t - 0.4, 50, 98, 6, 46, 1.2, _note, gravity=-20,
                                     salt=5, up=1.4))
    kit.world.append(lambda p: _sparkles(p, t - 0.5, 50, 90, n=8, salt=8))


def _box(p: QPainter, x: float, y: float, flaps: float):
    """The parcel, centred on (x, y): 34 wide, 18 high. `flaps` 0..1 pops its top open."""
    w, h = 34.0, 18.0
    left, top = x - w / 2, y - h / 2
    p.save()
    if flaps > 0:   # the flaps swinging up and out
        for side in (-1, 1):
            p.save()
            p.translate(x + side * w / 2, top)
            p.rotate(-side * 130 * flaps)
            p.setPen(_ink(1.4))
            p.setBrush(CARD_DARK)
            p.drawRect(QRectF(-w / 2 if side > 0 else 0, -3, w / 2, 3))
            p.restore()
    p.setPen(_ink(1.6))
    p.setBrush(CARD)
    p.drawRoundedRect(QRectF(left, top, w, h), 2, 2)
    if flaps <= 0:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(TAPE)
        p.drawRect(QRectF(x - 3, top + 1, 6, h - 2))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_accent())   # a little label with a note on it
    p.drawRoundedRect(QRectF(left + 4, top + 5, 9, 8), 1.5, 1.5)
    music_note(p, left + 5.2, top + 4.6, 0.5, QColor("#ffffff"))
    p.restore()


# ---------------------------------------------------------------------- What's new
GIFT_LOOP = 5.2


def present(kit: Kit, t: float):
    """What's new: a present in front of him; he tugs the bow, the lid flies off, a star
    pops out with confetti and he cheers. Then a new present for the next go."""
    t %= GIFT_LOOP
    kit.prop = ""
    show = eseg(t, 0.0, 0.35) * (1 - eseg(t, 4.2, 4.7))
    tug = held(t, 0.6, 1.5, 0.15)
    shake = math.sin(t * 30) * tug
    lid = seg(t, 1.5, 2.4)
    if show:
        kit.world.append(lambda p: _gift(p, show, lid, shake))
    if tug:
        spread = 3 * math.sin(t * 15) * tug
        kit.world.append(lambda p: paw(p, 44 - spread, 94 + shake, -10))
        kit.world.append(lambda p: paw(p, 56 + spread, 94 - shake, 10))
        kit.add(nod=2 * shake, dip=2 * tug)
    star = eseg(t, 1.6, 2.2) * (1 - eseg(t, 3.9, 4.4))
    if star:
        kit.world.append(lambda p: _star(p, 50 + 30 * eseg(t, 1.6, 2.2), lerp(100, 66, star),
                                         8 + 3 * star, _ink(1.4)))
    cheer = held(t, 2.1, 3.7, 0.2)
    if cheer:
        kit.world.append(lambda p: paw(p, 18, lerp(98, 74, cheer), -30))
        kit.world.append(lambda p: paw(p, 82 - 6 * cheer, lerp(98, 70, cheer), 30))
        kit.most(blink=cheer, mouth=0.3 * cheer)
        kit.add(ears=-10 * cheer, dy=-6 * bump(t, 2.1, 2.5))
    kit.world.append(lambda p: burst(p, t - 1.6, 50, 92, 14, 52, 1.4, _confetti, gravity=50,
                                     salt=13, up=1.3))
    kit.world.append(lambda p: _sparkles(p, t - 2.0, 78, 62, n=7, salt=4))


def _gift(p: QPainter, show: float, lid: float, shake: float):
    p.save()
    p.setOpacity(show)
    p.translate(50, 120)   # popping up from the floor
    p.scale(0.6 + 0.4 * show, 0.6 + 0.4 * show)
    p.translate(-50 + shake, -120)
    box = _accent()
    p.setPen(_ink(1.6))
    p.setBrush(box)
    p.drawRoundedRect(QRectF(30, 100, 40, 19), 2, 2)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(GOLD)
    p.drawRect(QRectF(47, 100.5, 6, 18))   # the ribbon down the front
    if lid < 1:   # the lid, flying up and off to the left once he's tugged the bow
        p.save()
        p.setOpacity(show * (1 - eseg(lid, 0.6, 1)))
        p.translate(50 - 34 * lid, 98 - 40 * lid + 46 * lid * lid)
        p.rotate(-160 * lid)
        p.setPen(_ink(1.6))
        p.setBrush(box.lighter(115))
        p.drawRoundedRect(QRectF(-22, -4, 44, 8), 2, 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(GOLD)
        p.drawRect(QRectF(-3, -3.5, 6, 7))
        p.setPen(_ink(1.3))   # the bow
        for side in (-1, 1):
            p.save()
            p.rotate(side * 25)
            p.drawEllipse(QRectF(-3.5 + side * 5.5, -11, 7, 8))
            p.restore()
        _oval(p, 0, -5, 4.4, 4.4, GOLD, _ink(1.1))
        p.restore()
    p.restore()


# ---------------------------------------------------------------------- the widget
class ActBunny(BunnyWidget):
    """Bun beside a window's title, playing `act` on a loop. `play(act)` is a one-off
    (the act's own seconds), then he's back to the loop; `set_act` changes the loop.
    His fidgets and his theme's skit stay off: he's busy. Hidden, his timer stops. In
    lite mode he's a still picture of his act (STILL: the bin, the parcel, the present
    still there), with no one-offs."""

    def __init__(self, act: Act, prop: str | None = None, height: int = ACT_H,
                 parent=None):
        super().__init__(prop, height=height, pad=4, parent=parent)
        self.setFixedSize(self.sizeHint())   # never squeezed: a short window clips his ears
        self.rate = 1.0       # how fast the loop plays (`tune`)
        self.stretch = 0.0    # -1..1: squashed down .. stretched up (`tune`)
        self.act = act
        self._phase = 0.0     # seconds into the loop
        self._once: tuple[Act, float] | None = None   # a one-off and when it started
        self._was = time.monotonic()

    def set_act(self, act: Act):
        if act is not self.act:
            self.act, self._phase = act, 0.0
            self.update()   # (resting in lite mode: the new still picture)

    def play(self, act: Act):
        self._once = (act, time.monotonic())
        self.stir()

    def tune(self, speed: float, semitones: float):
        """The sound's speed plays the loop faster or slower; its pitch stretches him
        up (higher) or squashes him down (lower)."""
        self.rate = max(0.25, min(4.0, speed))
        self.stretch = max(-1.0, min(1.0, semitones / 12))

    def _step_fidget(self, now: float):
        dt = min(0.1, max(0.0, now - self._was))
        self._was = now
        self._phase = (self._phase + dt * self.rate) % self.act[0]
        if self._once is not None and now - self._once[1] >= self._once[0][0]:
            self._once = None
        if lite.on():   # a still picture of the act, no one-offs
            self._once = None
        if self._skit is None:
            self._skit, self._skit_at = (math.inf, self._frame), now

    def _draw_bun(self, p: QPainter, pose: dict, body: QRectF):
        """In the bin, nothing of him below its rim is drawn: his legs, feet and tail
        (a long one in some themes' looks) are inside it, not poking out round it."""
        act = self._once[0] if self._once is not None else self.act
        if self._kit is None or act not in IN_BIN:
            super()._draw_bun(p, pose, body)
            return
        r = self._bun_rect()
        p.save()
        p.setClipRect(QRectF(0, 0, self.width(), r.top() + RIM * r.height() / 120),
                      Qt.ClipOperation.IntersectClip)
        super()._draw_bun(p, pose, body)
        p.restore()

    def _calm(self, now: float) -> bool:
        """In lite mode his act is a still picture, so it doesn't keep him moving."""
        if not lite.on():
            return super()._calm(now)
        skit, self._skit = self._skit, None
        try:
            return super()._calm(now)
        finally:
            self._skit = skit

    def _frame(self, kit: Kit, t: float):
        if lite.on():
            self.act[1](kit, STILL.get(self.act, 0.0))
        elif self._once is not None:
            act, at = self._once
            act[1](kit, time.monotonic() - at)
        else:
            self.act[1](kit, self._phase)
        if self.stretch:
            kit.add(sy=0.06 * self.stretch, sx=-0.03 * self.stretch, ears=-10 * self.stretch)


SNIP: Act = (SNIP_LOOP, snipping)
MIC: Act = (MIC_LOOP, mic_check)
RECORDING: Act = (REC_LOOP, rec_light)
BIN_ACT: Act = (BIN_LOOP, in_bin)
BRING_BACK: Act = (1.6, bring_back)
BYE: Act = (1.9, bye)
PAT: Act = (PAT_LOOP, box_pat)
RUN: Act = (RUN_LOOP, box_run)
OPEN: Act = (2.1, box_open)
GIFT: Act = (GIFT_LOOP, present)
IN_BIN = (BIN_ACT, BRING_BACK, BYE)   # the acts he's in the bin for
# lite mode's still picture of each loop: the moment that shows what he's doing
STILL = {SNIP: 0.9, MIC: 0.0, RECORDING: 0.3, BIN_ACT: 0.0, PAT: 0.0, RUN: 0.0, GIFT: 2.6}
