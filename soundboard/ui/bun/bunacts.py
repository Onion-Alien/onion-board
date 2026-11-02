"""Bun at work beside a window's title: `ActBunny` plays one act on a loop (and now and
then a one-off, `play`) the way the Live controls' DJ does (speedpitch.DjBunny).

- Edit sound: `snipping`, scissors through a little waveform; the sound's speed plays it
  faster or slower and its pitch stretches him up or squashes him (`ActBunny.tune`).
- Record a sound: the mic in his paw (he talks along with the level, BunnyWidget) and
  `rec_light`, a red light blinking on his ear cup while it records; `mic_check` idle.
- Recently deleted: `in_bin`, peeking out of a bin; `bring_back` digs the sound out and
  holds it up with a green tick, `bye` catches it and drops it in the bin with him.
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

import numpy as np

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QRegion
from PySide6.QtWidgets import QWidget

from soundboard.ui.bun import bunskits
from soundboard.ui.bun.bunny import music_note
from soundboard.ui.bun.bunnywidget import BunnyWidget
from soundboard.ui.bun.bunprops import _star
from soundboard.ui.bun.bunskitkit import (Kit, _ink, _oval, _sparkles, bump, burst, eseg,
                                          held, lerp, paw, puff, seg)
from soundboard.ui.kit import theme
from soundboard.ui.settings import lite

Act = tuple[float, Callable[[Kit, float], None]]   # (seconds, act)
ACT_H = 72   # Bun's height beside a window's title, px (the Live controls DJ's)
ADV_H = 64   # ... in the button row of Edit sound's Advanced view
SEEN_FRAMES = 8   # pictures of him seen() averages over

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


def desk(kit: Kit, t: float, away: float = 0.0):
    """Edit sound with nothing playing: Bun sits still behind the Live controls' DJ desk
    (bunskits.mixing's), paws on it. `away` 0..1: the desk going down out of the way."""
    kit.prop = ""
    kit.world.append(lambda p: _desk_at(p, away))
    if away < 0.5:
        kit.world.append(lambda p: paw(p, 27, 100 + 10 * away, -10))
        kit.world.append(lambda p: paw(p, 66, 101 + 10 * away, 10))


def _desk_at(p: QPainter, away: float):
    if away >= 1:
        return
    p.save()
    p.translate(0, 24 * away)
    p.setOpacity(1 - away)
    bunskits._desk(p, 0.0, -1, 0.0, 0.0)
    p.restore()


KNOB_LOOP = 1.6


def tweak(kit: Kit, t: float):
    """Edit sound, a speed / pitch / effect change: he twists a big knob with both paws."""
    t %= KNOB_LOOP
    kit.prop = ""
    turn = 50 * math.sin(t / KNOB_LOOP * 2 * math.pi)
    kit.world.append(lambda p: _knob(p, turn))
    a = math.radians(turn)
    kit.world.append(lambda p: paw(p, 50 - 13 * math.cos(a), 103 - 13 * math.sin(a), -20))
    kit.world.append(lambda p: paw(p, 50 + 13 * math.cos(a), 103 + 13 * math.sin(a), 20))
    kit.add(nod=turn / 12, dip=1.5)
    kit.world.append(lambda p: _sparkles(p, t - 0.7, 70, 92, n=4, life=0.6, salt=21))


def _knob(p: QPainter, turn: float):
    p.save()
    p.setPen(_ink(1.6))
    p.setBrush(QColor("#3a3452"))
    p.drawRoundedRect(QRectF(30, 110, 40, 9), 3, 3)   # its little stand
    _oval(p, 50, 103, 26, 26, _accent(), _ink(1.6))
    _oval(p, 50, 103, 18, 18, QColor("#2b2340"))
    p.translate(50, 103)
    p.rotate(turn)
    p.setPen(QPen(QColor("#ffcf40"), 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(0, -2), QPointF(0, -8))   # the pointer
    p.restore()


# ---------------------------------------------------------------------- Record a sound
MIC_LOOP = 4.5


def mic_check(kit: Kit, t: float):
    """Record a sound, waiting: a mic check. He leans in and mouths "one, two... one,
    two" into the mic (his mouth is the main thing moving), a ring off the mic on each
    word, then sits back and listens."""
    t %= MIC_LOOP
    lean = held(t, 0.3, 3.3, 0.3)
    kit.add(nod=6 * lean, dip=1.5 * lean)
    for at in _WORDS:   # each word: the mouth opens and shuts, a little nod with it
        say = bump(t, at, at + 0.32)
        kit.most(mouth=0.9 * say)
        kit.add(dy=-1.0 * say, nod=2 * say)
        kit.world.append(lambda p, at=at: _ring(p, seg(t, at + 0.05, at + 0.6)))
    kit.most(blink=held(t, 3.6, 4.1, 0.1))   # listening back, eyes shut


_WORDS = (0.6, 1.05, 1.9, 2.35)   # "one, two ... one, two"


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
    kit.front.append(lambda p: _rec(p, on))   # (his mouth: the mic level, BunnyWidget)


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
    """Recently deleted, Bring back: he ducks into the bin, digs and pops up holding the
    sound high; a green tick pops on it, then he tosses it back to the board."""
    kit.prop = ""
    duck = held(t, 0.0, 0.55, 0.15)
    dig = math.sin(t * 30) * held(t, 0.15, 0.5, 0.05)
    up = eseg(t, 0.55, 0.85)
    kit.add(dy=_IN + 16 * duck - 8 * bump(t, 0.55, 0.95), nod=4 * dig, ears=6 * duck)
    kit.most(blink=duck, mouth=0.6 * held(t, 0.85, 1.6, 0.1))
    toss = seg(t, 1.6, 2.1)
    if t < 0.55:   # dust out of the bin while he digs
        kit.world.append(lambda p: _dig_puffs(p, t))
    if 0.55 <= t < 1.6:   # held up high: out of the bin, over his head
        y = lerp(104, 22, up)
        kit.world.append(lambda p: _tile(p, 76, y, 0.0, 1.0, tick=seg(t, 0.95, 1.15)))
        kit.world.append(lambda p: paw(p, 76, y + 10, 15))
    elif toss > 0:   # tossed off to the right, back to the board
        x, y = lerp(76, 104, toss), 22 - 18 * math.sin(math.pi * toss) + 30 * toss * toss
        kit.world.append(lambda p: _tile(p, x, y, 300 * toss, 1 - toss, tick=1.0))
    kit.world.append(_bin)
    kit.world.append(lambda p: _sparkles(p, t - 1.0, 76, 18, n=8, life=0.8, salt=11))


def bye(kit: Kit, t: float):
    """Recently deleted, Delete for good: the sound flies in from the list into his paw,
    he holds it over the bin and drops it in with him; a puff, and a smug look."""
    kit.prop = ""
    fly = seg(t, 0.0, 0.45)
    drop = seg(t, 0.95, 1.25)
    land = bump(t, 1.2, 1.45)
    kit.add(dy=_IN + 3 * land, nod=-5 * held(t, 0.3, 0.95, 0.15), ears=-6 * bump(t, 0.4, 0.7))
    kit.most(mouth=0.4 * bump(t, 0.4, 0.7), smug=held(t, 1.35, 1.9, 0.15))
    if t < 0.45:   # in from the list, on his right, in an arc
        x, y = lerp(104, 78, fly), 70 - 28 * math.sin(math.pi * fly)
        kit.world.append(lambda p: _tile(p, x, y, -200 * (1 - fly), 1.0))
    elif t < 0.95:   # caught: held over the bin
        kit.world.append(lambda p: _tile(p, 78, 72, 0.0, 1.0))
        kit.world.append(lambda p: paw(p, 78, 80, 15))
    elif drop < 1:   # let go: down into the bin (behind its front)
        kit.world.append(lambda p: _tile(p, 70, lerp(74, 112, drop * drop), 40 * drop, 1.0))
    kit.world.append(_bin)
    kit.world.append(lambda p: _land_puff(p, seg(t, 1.2, 1.7)))


def _dig_puffs(p: QPainter, t: float):
    for i in range(3):
        k = (t * 2.5 + i / 3) % 1.0
        puff(p, 30 + 20 * i + 6 * k, 90 - 12 * k, 3 + 3 * k, 0.7 * (1 - k))


def _land_puff(p: QPainter, k: float):
    if not 0 < k < 1:
        return
    for i in range(5):
        a = math.pi + i * math.pi / 4
        puff(p, 50 + 30 * math.cos(a) * (0.5 + k), 90 + 6 * math.sin(a) * k - 8 * k,
             3 + 4 * k, 0.8 * (1 - k))


def _tile(p: QPainter, x: float, y: float, turn: float, alpha: float, tick: float = 0.0):
    """A sound, as a little pad tile with a note on it; `tick` 0..1 pops a green tick on."""
    if alpha <= 0:
        return
    p.save()
    p.setOpacity(alpha)
    p.translate(x, y)
    p.rotate(turn)
    p.setPen(_ink(1.5))
    p.setBrush(_accent())
    p.drawRoundedRect(QRectF(-9, -9, 18, 18), 4.5, 4.5)
    music_note(p, -5.5, -7.5, 0.9, QColor("#ffffff"))
    if tick > 0:
        s = 0.4 + 0.6 * tick + 0.25 * math.sin(math.pi * tick)
        p.translate(8, -8)
        p.scale(s, s)
        _oval(p, 0, 0, 13, 13, QColor("#2fc46b"), _ink(1.3))
        p.setPen(QPen(QColor("#ffffff"), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPolyline([QPointF(-3, 0.2), QPointF(-0.8, 2.6), QPointF(3.4, -2.6)])
    p.restore()


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
    still there), with no one-offs. With `rest_after_s` he plays the loop that long
    after he's shown or stirred, finishes the round he's on and holds its first pose:
    a window left open costs nothing."""

    def __init__(self, act: Act, prop: str | None = None, height: int = ACT_H,
                 parent=None, rest_after_s: float | None = None):
        self._wrapped = False   # the loop just came back round to its start
        super().__init__(prop, height=height, pad=4, parent=parent, rest_after_s=rest_after_s)
        self.setFixedSize(self.sizeHint())   # never squeezed: a short window clips his ears
        self.rate = 1.0       # how fast the loop plays (`tune`)
        self.stretch = 0.0    # -1..1: squashed down .. stretched up (`tune`)
        self.act = act
        self._phase = 0.0     # seconds into the loop
        self._once: tuple[Act, float] | None = None   # a one-off and when it started
        self._was = time.monotonic()
        # his act from the very first paint (not from his first tick: a bare Bun, then
        # the bin popping in round him)
        self._skit, self._skit_at = (math.inf, self._frame), self._was
        self._dy_last = self.pose(self._was)["dy"]   # (already in place: no jolt to settle)

    def set_height(self, height: int):
        """Bun this many px tall (his widget's size follows)."""
        if height != self.bun_h:
            self.bun_h = height
            self._kept_img = self._kept_pose = None
            self.setFixedSize(self.sizeHint())
            self.update()

    def seen(self) -> QRectF:
        """The part of his widget he's drawn in (each theme's look has its own ears),
        found by drawing him: edges averaged over his bob, in his widget's px."""
        boxes = []
        t0 = self._t0
        try:
            for k in range(SEEN_FRAMES):   # (round one bob: about 2.9 s)
                self._t0 = t0 - k * 2.9 / SEEN_FRAMES
                img = QImage(self.size(), QImage.Format.Format_ARGB32)
                img.fill(0)
                self.render(img, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
                a = np.frombuffer(img.constBits(), np.uint8).reshape(
                    img.height(), img.bytesPerLine() // 4, 4)[:, :img.width(), 3]
                ys, xs = np.nonzero(a > 120)
                if len(xs):
                    boxes.append((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
        finally:
            self._t0 = t0
        if not boxes:
            return QRectF(self.rect())
        x0, y0, x1, y1 = (sum(b[i] for b in boxes) / len(boxes) for i in range(4))
        return QRectF(x0, y0, x1 - x0, y1 - y0)

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
        phase = (self._phase + dt * self.rate) % self.act[0]
        self._wrapped = phase < self._phase
        self._phase = phase
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
        """In lite mode his act is a still picture, so it doesn't keep him moving; after
        his rest it only does until the round he's on is done."""
        if not lite.on():
            if not self._wrapped or self._once is not None:
                return super()._calm(now)
            self._phase = 0.0   # (the round's end is its start: the pose he holds)
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
BRING_BACK: Act = (2.1, bring_back)
BYE: Act = (1.9, bye)
PAT: Act = (PAT_LOOP, box_pat)
RUN: Act = (RUN_LOOP, box_run)
OPEN: Act = (2.1, box_open)
GIFT: Act = (GIFT_LOOP, present)
DESK: Act = (bunskits.MIX_LOOP, desk)
KNOB: Act = (KNOB_LOOP, tweak)
IN_BIN = (BIN_ACT, BRING_BACK, BYE)   # the acts he's in the bin for
# lite mode's still picture of each loop: the moment that shows what he's doing
STILL: dict[Act, float] = {DESK: 0.0, SNIP: 0.9, MIC: 0.0, RECORDING: 0.3, BIN_ACT: 0.0, PAT: 0.0,
                           RUN: 0.0, GIFT: 2.6}


ACT_REST_S = 10.0   # a window's Bun plays this long after it opens or a change, then holds still
AWAY = 0.35   # seconds: the desk going down out of his way, or coming back up
LONGEST = {SNIP: 2.4, KNOB: 1.6}   # an action plays at least this long (one cut, a twist)
LINGER = 0.7  # ... and this long after the last change (a drag keeps him at it)


class EditBunny(ActBunny):
    """Edit sound's Bun, behind the Live controls' DJ desk: mixing to the beat while the
    sound plays (`set_playing`), sitting still behind it while it doesn't. A change
    (`busy`): he puts the desk away, snips (the trim) or twists a knob (anything else)
    for as long as the changes keep coming, then the desk comes back."""

    def __init__(self, parent=None):
        self.playing = False
        self._task: list | None = None   # [act, started, last change]
        # (draws his first frame: set up first)
        super().__init__(DESK, parent=parent, rest_after_s=ACT_REST_S)

    def set_playing(self, on: bool):
        if on != self.playing:
            self.playing = on
            self.stir()

    def busy(self, act: Act):
        now = time.monotonic()
        task = self._task
        if task is not None and now - task[1] >= AWAY and now < self._task_end(task):
            task[0], task[2] = act, now   # still at it: keep going (the newest change's act)
        elif task is not None and now - task[1] < AWAY:
            task[0], task[2] = act, now   # the desk is still going down
        else:
            self._task = [act, now, now]
        self.stir()

    @staticmethod
    def _task_end(task: list) -> float:
        """When the action itself stops (then the desk takes AWAY to come back)."""
        act, start, last = task
        return max(start + AWAY + LONGEST.get(act, 1.6), last + LINGER)

    def _step_fidget(self, now: float):
        super()._step_fidget(now)
        if self._task is not None and now >= self._task_end(self._task) + AWAY:
            self._task = None

    def _calm(self, now: float) -> bool:
        """Not while he's at a change (the desk is away)."""
        return self._task is None and super()._calm(now)

    def _frame(self, kit: Kit, t: float):
        task = None if lite.on() else self._task
        if task is not None:
            now = time.monotonic()
            act, start, _last = task
            end = self._task_end(task)
            if now - start < AWAY:   # the desk going down
                desk(kit, 0, eseg(now - start, 0, AWAY))
            elif now < end:          # at it
                act[1](kit, now - start - AWAY)
            else:                    # the desk coming back up
                desk(kit, 0, 1 - eseg(now - end, 0, AWAY))
        elif self.playing and not lite.on():
            bunskits.mixing(kit, self._phase)   # the sound plays: he mixes along
        else:
            desk(kit, 0)
        if self.stretch:
            kit.add(sy=0.06 * self.stretch, sx=-0.03 * self.stretch, ears=-10 * self.stretch)
