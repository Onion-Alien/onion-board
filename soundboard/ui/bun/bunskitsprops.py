"""Bun's theme skits from Blood Moon to Toxic (ui/bun/bunskits.py has the list and how a skit
works): the moon he bites, the shades, the propeller, the frog's fly, the lasers, the bat, the
wand, the spyglass, the sneeze, the crown, the onion and the Geiger counter. `bunskits`
re-exports them."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QRadialGradient

from soundboard.ui.bun.bunny import INK, sparkle
from soundboard.ui.bun.bunskitkit import (
    Kit,
    _ink,
    _oval,
    _rand,
    _sneeze,
    _sparkles,
    _surprised,
    bump,
    burst,
    eseg,
    held,
    lerp,
    paw,
    piece,
    puff,
    seg,
)


CHEESE, CHEESE_DARK = QColor("#ffd34d"), QColor("#e0a92a")


# ---------------------------------------------------------------------- the skits
def blood_moon(kit: Kit, t: float):
    """Looks up, reaches back, pulls the moon down, bites it: cheese! He tosses it back."""
    look = held(t, 0.0, 4.7, 0.5)
    kit.add(dip=-3 * look, nod=-6 * look * (1 - seg(t, 1.3, 1.9)), ears=6 * look)
    pull, toss = eseg(t, 1.3, 2.1), eseg(t, 3.9, 4.6)
    in_paw = 1.3 <= t < 4.6
    if in_paw:
        kit.hide.add("moon")
    # where the moon is: in the sky behind him, then in his paw by his mouth, then back up
    mouth_k = eseg(t, 2.1, 2.35) * (1 - eseg(t, 2.6, 2.9))
    hx, hy = lerp(72, 62, mouth_k), lerp(84, 80, mouth_k)
    if t < 3.9:
        cx, cy, r = lerp(50, hx, pull), lerp(48, hy, pull), lerp(37, 13, pull)
    else:
        cx, cy, r = lerp(hx, 50, toss), lerp(hy, 48, toss) - 30 * bump(t, 3.9, 4.6), \
            lerp(13, 37, toss)
    cheese = eseg(t, 2.4, 2.9) * (1 - eseg(t, 4.1, 4.6))
    bitten = 2.35 <= t
    reach = eseg(t, 0.6, 1.3) * (1 - pull)
    if in_paw:
        front = t >= 1.7 and t < 4.2   # (it comes round in front of him as he pulls it)
        draw = (lambda p: _moon(p, cx, cy, r, cheese, bitten))
        (kit.front if front else kit.behind).append(draw)
        kit.front.append(lambda p: paw(p, cx + r * 0.55, cy + r * 0.45))
    elif t < 1.3:
        kit.front.append(lambda p: paw(p, lerp(78, 82, reach), lerp(100, 34, reach)))
    kit.prop = ""
    if 2.1 <= t < 2.35:
        kit.most(mouth=0.8 * seg(t, 2.1, 2.3))
    chomp = bump(t, 2.33, 2.5)
    kit.add(sy=-0.06 * chomp, dip=2 * chomp)
    if 2.4 <= t < 3.0:
        kit.most(mouth=0.15 + 0.2 * abs(math.sin(t * 22)))
    kit.world.append(lambda p: burst(p, t - 2.35, 62, 76, 7, 30, 0.7, _crumb, salt=3))
    _surprised(kit, t, 3.0, 3.9)


def _crumb(p, x, y, fade, i):
    c = QColor(CHEESE)
    c.setAlphaF(fade)
    _oval(p, x, y, 3.2, 2.6, c, None, i * 40)


def _moon(p: QPainter, cx, cy, r, cheese: float, bitten: bool):
    red_hi, red_lo = QColor("#ff8a4d"), QColor("#c2361f")

    def mix(a: QColor, b: QColor, k: float) -> QColor:
        return QColor.fromRgbF(lerp(a.redF(), b.redF(), k), lerp(a.greenF(), b.greenF(), k),
                               lerp(a.blueF(), b.blueF(), k))
    body = QPainterPath()
    body.addEllipse(QPointF(cx, cy), r, r)
    if bitten:
        bite = QPainterPath()
        for bx, by, br in ((0.62, -0.55, 0.36), (0.85, -0.18, 0.3), (0.3, -0.8, 0.28)):
            bite.addEllipse(QPointF(cx + bx * r, cy + by * r), br * r, br * r)
        body = body.subtracted(bite)
    grad = QRadialGradient(cx - r * 0.3, cy - r * 0.4, r * 1.4)
    grad.setColorAt(0, mix(red_hi, QColor("#fff1a8"), cheese))
    grad.setColorAt(1, mix(red_lo, CHEESE_DARK, cheese))
    p.setPen(QPen(mix(QColor("#6e170e"), QColor("#9a6a12"), cheese), max(1.2, r * 0.05)))
    p.setBrush(grad)
    p.drawPath(body)
    p.save()
    p.setClipPath(body)
    hole = mix(QColor(140, 30, 16), QColor("#d29a22"), cheese)
    hole.setAlpha(round(lerp(120, 255, cheese)))
    for x, y, rr in ((-0.6, -0.37, 0.14), (0.62, -0.54, 0.11), (0.81, 0.11, 0.15),
                     (-0.76, 0.27, 0.1), (0.2, 0.45, 0.13), (-0.15, -0.05, 0.09)):
        _oval(p, cx + x * r, cy + y * r, 2 * rr * r, 2 * rr * r, hole)
    p.restore()


def deal_with_it(kit: Kit, t: float):
    """Retro 98: the pixel shades come off, then drop back down onto his face."""
    kit.hide.add("pixel_shades")
    off = eseg(t, 0.0, 0.5)
    down = seg(t, 1.0, 2.2) ** 2          # (falling: speeding up)
    y = -70 * off if t < 1.0 else -70 * (1 - down)
    alpha = 1 - seg(t, 0.35, 0.55) if t < 1.0 else min(1.0, seg(t, 1.0, 1.2) * 1.5)
    land = bump(t, 2.2, 2.45)
    kit.add(sy=-0.05 * land, dy=1.5 * land)
    kit.front.append(lambda p: piece(p, "pixel_shades", 0, y + 2 * land, 0, (50, 60), 1, alpha))
    if t >= 2.2:
        kit.most(smug=1.0)
        kit.add(nod=3 * bump(t, 2.6, 3.3), dip=2 * bump(t, 2.6, 3.0))
    elif 0.55 < t < 1.0:
        kit.most(blink=bump(t, 0.6, 0.8))   # (his own eyes, for a moment)


def propeller(kit: Kit, t: float):
    """Brainrot: the propeller spins up and lifts him off the ground, then he drops."""
    kit.hide.add("propeller")
    spin = seg(t, 0.0, 1.0) * (1 - seg(t, 2.5, 2.9))
    turns = 6 * t * t if t < 1.0 else 6 + 18 * (t - 1.0)
    lift = eseg(t, 1.0, 1.6) * (1 - seg(t, 2.6, 2.85) ** 2)
    kit.add(dy=-16 * lift, angle=4 * math.sin(t * 7) * lift, ears=10 * lift)
    land = bump(t, 2.85, 3.15)
    kit.add(sy=-0.12 * land, sx=0.08 * land)
    kit.most(mouth=0.35 * lift, blink=0.0)
    kit.front.append(lambda p: _propeller(p, turns, spin))
    if t > 2.9:
        for dx in (-22, 22):
            kit.world.append(lambda p, dx=dx: puff(p, 50 + dx, 117, 5, 1 - seg(t, 2.9, 3.4)))


def _propeller(p: QPainter, turns: float, spin: float):
    piece(p, "propeller")   # the cap
    p.save()
    p.translate(50, 20)
    w = 17 * abs(math.cos(turns * math.pi))   # the blades, turning (seen side on)
    blur = QColor("#2f7bff")
    blur.setAlphaF(0.35 * spin)
    if spin > 0.5:
        _oval(p, 0, 0, 36, 5, blur)
    for sx, col in ((1, "#e8432b"), (-1, "#3cc46a")):
        path = QPainterPath(QPointF(0, 0))
        path.quadTo(QPointF(sx * w * 0.5, -3), QPointF(sx * w, -1))
        path.quadTo(QPointF(sx * w * 0.5, 2.5), QPointF(0, 0))
        p.setPen(_ink(1.2))
        p.setBrush(QColor(col))
        p.drawPath(path)
    _oval(p, 0, 0, 4, 4, QColor("#ffcf40"), _ink(1.2))
    p.restore()


def frog_fly(kit: Kit, t: float):
    """Swamp: a fly buzzes round, the frog hat's tongue snaps it up. Bun: "!"."""
    caught = t >= 1.75
    if not caught:
        fx = lerp(-8, 50, seg(t, 0, 1.6)) + 10 * math.sin(t * 6)
        fy = 14 + 8 * math.sin(t * 9) - 6 * seg(t, 0, 1.6)
        kit.world.append(lambda p: _fly(p, fx, fy, t))
        kit.add(angle=-4 * held(t, 0.3, 1.6), nod=-6 * held(t, 0.3, 1.6))
    tongue = bump(t, 1.55, 1.85)
    if tongue:
        kit.front.append(lambda p: _tongue(p, 50, 28, 46, 6, tongue))
    _surprised(kit, t, 1.9, 2.9)
    if t > 2.9:
        kit.most(smug=held(t, 2.9, 3.4, 0.1))


def _fly(p: QPainter, x, y, t):
    wing = QColor(220, 235, 255, 170)
    flap = 3 * abs(math.sin(t * 60))
    _oval(p, x - 2, y - 2 - flap / 2, 5, 3 + flap, wing)
    _oval(p, x + 2, y - 2 - flap / 2, 5, 3 + flap, wing)
    _oval(p, x, y, 5, 4, QColor("#2b2340"))


def _tongue(p: QPainter, x0, y0, x1, y1, k):
    pen = QPen(QColor("#ff6f91"), 3)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    x, y = lerp(x0, x1, k), lerp(y0, y1, k)
    p.drawLine(QPointF(x0, y0), QPointF(x, y))
    _oval(p, x, y, 5, 5, QColor("#ff6f91"))


def laser(kit: Kit, t: float):
    """Deep Fried: the laser eyes flare and sweep, something goes boom, he blinks sweetly."""
    flare = held(t, 0.3, 1.5, 0.15)
    sweep = lerp(-25, 20, eseg(t, 0.3, 1.5))
    if flare:
        kit.world.append(lambda p: _beams(p, sweep, flare))
        kit.add(dx=0.8 * math.sin(t * 50) * flare)
    boom = t - 1.4
    kit.world.append(lambda p: burst(p, boom, 98, 104, 9, 28, 0.8, _ember, gravity=20, salt=5))
    if 1.4 < t < 2.4:
        kit.world.append(lambda p: puff(p, 98, 102, 4 + 10 * seg(t, 1.4, 1.8),
                                        1 - seg(t, 1.6, 2.4), QColor(120, 110, 130, 200)))
    kit.most(blink=bump(t, 2.2, 2.4) + bump(t, 2.5, 2.7))   # a double blink: innocent
    kit.most(smug=held(t, 2.7, 3.2, 0.1))


def _beams(p: QPainter, angle, k):
    for x in (39, 61):
        p.save()
        p.translate(x, 62)
        p.rotate(angle)
        glow = QColor(255, 60, 60, round(110 * k))
        p.setPen(QPen(glow, 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(0, 0), QPointF(70, 0))
        p.setPen(QPen(QColor(255, 230, 230, round(255 * k)), 2.2, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(0, 0), QPointF(70, 0))
        p.restore()


def _ember(p, x, y, fade, i):
    c = QColor("#ffb84d" if i % 2 else "#ff4d3a")
    c.setAlphaF(fade)
    _oval(p, x, y, 3, 3, c)


def bat(kit: Kit, t: float):
    """Vampire: a swirl of his cape and he's a bat, flapping a loop, then back."""
    gone = held(t, 0.5, 3.4, 0.3)
    kit.pose["alpha"] = 1 - gone
    kit.add(sx=-0.4 * gone, sy=-0.4 * gone)
    for at in (0.5, 3.3):
        kit.world.append(lambda p, at=at: _poof(p, t, at))
    if 0.8 < t < 3.2:
        u = seg(t, 0.8, 3.2) * 2 * math.pi
        x, y = 50 + 34 * math.sin(u), 52 - 18 * math.sin(2 * u)
        kit.world.append(lambda p: _bat(p, x, y, t, math.cos(u)))
    if t > 3.4:
        kit.most(smug=held(t, 3.5, 4.3, 0.1), mouth=0.0)


def _poof(p: QPainter, t, at):
    """A puff of purple smoke at `at` (his cape's swirl)."""
    if t < at:
        return
    for dx, dy in ((-10, 0), (10, -4), (0, 8), (0, -12)):
        puff(p, 50 + dx, 86 + dy, 9 * (0.6 + seg(t, at, at + 0.4)),
             (1 - seg(t, at, at + 0.6)) * 0.9, QColor(90, 70, 110, 200))


def _bat(p: QPainter, x, y, t, facing):
    flap = math.sin(t * 22)
    p.save()
    p.translate(x, y)
    p.scale(1.7 if facing >= 0 else -1.7, 1.7)
    col = QColor("#6b4a8c")
    for sx in (1, -1):
        wing = QPainterPath(QPointF(0, 0))
        tip = QPointF(sx * 15, -8 * flap)
        wing.quadTo(QPointF(sx * 8, -10 * flap - 3), tip)
        wing.quadTo(QPointF(sx * 11, 2), QPointF(sx * 7, 1))
        wing.quadTo(QPointF(sx * 4, 4), QPointF(0, 2))
        p.setPen(_ink(1.2))
        p.setBrush(col)
        p.drawPath(wing)
    _oval(p, 0, 0, 7, 8, col, _ink(1.2))
    _oval(p, -1.5, -1, 1.6, 1.6, QColor("#ff4d6d"))
    _oval(p, 1.5, -1, 1.6, 1.6, QColor("#ff4d6d"))
    p.restore()


def wizard(kit: Kit, t: float):
    """Midnight: a flick of his wand makes a rain cloud, by mistake. Another flick: gone."""
    up = held(t, 0.3, 3.4, 0.3)
    wx, wy = 80, lerp(100, 74, up)
    kit.front.append(lambda p: _wand(p, wx, wy, 20 * bump(t, 0.9, 1.1) + 25 * bump(t, 2.4, 2.6)))
    kit.prop = ""
    kit.world.append(lambda p: _sparkles(p, t - 1.0, 96, 52, salt=1))
    cloud = held(t, 1.1, 2.6, 0.2)
    if cloud:
        kit.world.append(lambda p: _rain_cloud(p, 50, -5, cloud, t))
        kit.most(sad=0.7 * held(t, 1.4, 2.6, 0.2))
        kit.add(dip=2 * held(t, 1.4, 2.6))
    kit.world.append(lambda p: _sparkles(p, t - 2.55, 50, 8, n=10, salt=2))
    kit.add(dy=-6 * bump(t, 2.8, 3.2) - 4 * bump(t, 3.2, 3.5))
    kit.most(blink=held(t, 2.8, 3.5, 0.05))


def _wand(p: QPainter, x, y, angle):
    p.save()
    p.translate(x, y)
    p.rotate(-30 + angle)
    p.setPen(QPen(QColor("#3a3452"), 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(0, 0), QPointF(0, -20))
    sparkle(p, 0, -22, 4.5, QColor("#ffcf40"))
    p.restore()
    paw(p, x, y)


def _rain_cloud(p: QPainter, x, y, k, t):
    p.save()
    p.setOpacity(k)
    col = QColor("#8b8fa3")
    for dx, dy, r in ((-10, 2, 8), (0, -3, 10), (11, 2, 8), (0, 4, 9)):
        _oval(p, x + dx, y + dy, 2 * r, 2 * r, col)
    drop = QColor("#6ec6ff")
    p.setPen(QPen(drop, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for i in range(6):
        fall = (t * 1.6 + _rand(i, 9)) % 1.0
        dx = -14 + i * 5.6
        yy = y + 10 + fall * 34
        p.drawLine(QPointF(x + dx, yy), QPointF(x + dx - 0.6, yy + 3.5))
    p.restore()


def spyglass(kit: Kit, t: float):
    """Ocean: the captain looks out through his spyglass. A fish! It leaps."""
    up = held(t, 0.2, 2.4, 0.3)
    look = math.sin(seg(t, 0.5, 2.2) * 2 * math.pi) * up
    kit.add(angle=5 * look, nod=6 * look)
    if up:
        kit.front.append(lambda p: _spyglass(p, up))
    kit.prop = ""
    _surprised(kit, t, 2.3, 3.2)
    u = seg(t, 2.4, 3.4)
    if 0 < u < 1:
        x, y = lerp(-4, 34, u), 118 - 40 * math.sin(math.pi * u)
        kit.world.append(lambda p: _fish(p, x, y, -60 + 120 * u))
    for at, x in ((2.4, -4), (3.4, 34)):
        kit.world.append(lambda p, at=at, x=x: burst(p, t - at, x, 116, 6, 26, 0.6, _drop,
                                                     gravity=90, salt=7, up=1.0))


def _spyglass(p: QPainter, k):
    p.save()
    p.translate(64, 62)
    p.rotate(-12)
    p.setOpacity(k)
    p.setPen(_ink(1.6))
    p.setBrush(QColor("#9a6532"))
    p.drawRoundedRect(QRectF(0, -5, 18, 10), 2, 2)
    p.setBrush(QColor("#ffcf40"))
    p.drawRoundedRect(QRectF(16, -6.5, 14, 13), 2, 2)
    p.setBrush(QColor("#9fd9ff"))
    p.drawEllipse(QRectF(28, -5.5, 4, 11))
    p.restore()
    paw(p, 70, 74)


def _fish(p: QPainter, x, y, angle):
    p.save()
    p.translate(x, y)
    p.rotate(angle)
    col = QColor("#ff9f43")
    tail = QPainterPath(QPointF(-6, 0))
    tail.lineTo(-12, -5)
    tail.lineTo(-12, 5)
    tail.closeSubpath()
    p.setPen(_ink(1.2))
    p.setBrush(col)
    p.drawPath(tail)
    p.drawEllipse(QRectF(-7, -4.5, 15, 9))
    _oval(p, 4, -1, 2, 2, INK)
    p.restore()


def _drop(p, x, y, fade, i):
    c = QColor("#6ec6ff")
    c.setAlphaF(fade)
    _oval(p, x, y, 2.6, 3.4, c)


def achoo(kit: Kit, t: float):
    """Arctic: snow falls, he shivers, then sneezes."""
    kit.world.append(lambda p: _snow(p, t, held(t, 0, 3.6, 0.4)))
    shiver = held(t, 0.3, 1.8, 0.2)
    kit.add(dx=1.2 * math.sin(t * 55) * shiver, ears=-4 * shiver)
    kit.most(blink=0.4 * shiver)
    _sneeze(kit, t, 2.25)
    kit.world.append(lambda p: _sneeze_cloud(p, t, 2.25))


def _sneeze_cloud(p: QPainter, t, at):
    if t <= at:
        return
    k = seg(t, at, at + 0.65)
    for dx, dy in ((-1, 0.2), (1, 0.3), (0, 0.6)):
        puff(p, 50 + dx * k * 22, 76 + dy * 10 * k, 5 + 4 * k, 1 - seg(t, at + 0.05, at + 0.65),
             QColor(235, 245, 255, 220))


def _snow(p: QPainter, t, k):
    if k <= 0:
        return
    col = QColor(255, 255, 255, round(220 * k))
    for i in range(14):
        fall = (t * 0.3 + _rand(i, 4)) % 1.0
        x = -8 + 116 * _rand(i, 5) + 4 * math.sin(t * 2 + i)
        y = -6 + fall * 128
        _oval(p, x, y, 3, 3, col)


def crown(kit: Kit, t: float):
    """Royal: the crown slips over his eyes; he pushes it back and gives it a polish."""
    kit.hide.add("crown")
    slip = eseg(t, 0.2, 0.6) * (1 - eseg(t, 1.6, 2.1))
    blind = held(t, 0.6, 1.6, 0.1)
    kit.add(dx=1.6 * math.sin(t * 9) * blind, angle=3 * math.sin(t * 5) * blind)
    kit.front.append(lambda p: piece(p, "crown", 0, 20 * slip, 6 * slip, (50, 30)))
    push = held(t, 1.4, 2.2, 0.15)
    rub = held(t, 2.3, 3.2, 0.15)
    if push or rub:
        x = 64 + 4 * math.sin(t * 24) * rub
        y = lerp(48, 32, eseg(t, 1.4, 2.0)) if push else 34
        kit.front.append(lambda p: paw(p, x, y))
        kit.prop = ""
    kit.world.append(lambda p: _sparkles(p, t - 3.1, 56, 18, n=5, salt=8))
    kit.most(smug=held(t, 3.2, 3.6, 0.1))


def onion(kit: Kit, t: float):
    """Onion: he peels a layer off his onion hat and his eyes water."""
    peel = eseg(t, 0.5, 1.5)
    kit.prop = ""
    if t < 1.9:
        kit.front.append(lambda p: _peel(p, peel, 1 - seg(t, 1.5, 1.9)))
        kit.front.append(lambda p: paw(p, lerp(62, 86, peel), lerp(30, 20, peel)))
    cry = held(t, 1.3, 3.0, 0.3)
    kit.most(sad=0.8 * cry)
    kit.add(ears=10 * cry)
    if cry:
        kit.world.append(lambda p: _tears(p, t, cry))
    kit.most(blink=held(t, 3.1, 3.4, 0.05))   # a big sniff, eyes screwed shut
    kit.add(dip=-2 * bump(t, 3.05, 3.4))


def _peel(p: QPainter, k, alpha):
    p.save()
    p.setOpacity(alpha)
    p.translate(60 + 26 * k, 26 - 6 * k)
    p.rotate(80 * k)
    path = QPainterPath(QPointF(-6, -10))
    path.quadTo(QPointF(4, 0), QPointF(-2, 12))
    path.quadTo(QPointF(8, 2), QPointF(-6, -10))
    p.setPen(_ink(1.4))
    p.setBrush(QColor("#c77dde"))
    p.drawPath(path)
    p.restore()


def _tears(p: QPainter, t, k):
    col = QColor("#8fd3ff")
    for i, x in enumerate((36, 64, 38, 62)):
        fall = (t * 1.4 + i * 0.37) % 1.0
        c = QColor(col)
        c.setAlphaF(k * (1 - fall))
        _oval(p, x + (i % 2) * 2, 70 + fall * 26, 3, 4, c)


def geiger(kit: Kit, t: float):
    """Toxic: the Geiger counter in his paw goes wild and he glows green."""
    up = held(t, 0.2, 3.2, 0.3)
    wild = held(t, 0.9, 2.5, 0.2)
    kit.prop = ""
    if up:
        kit.front.append(lambda p: _geiger(p, up, wild, t))
    if wild:
        kit.behind.append(lambda p: _glow(p, wild * (0.6 + 0.4 * math.sin(t * 14))))
        kit.add(ears=-12 * wild, dx=0.8 * math.sin(t * 40) * wild)
        kit.most(mouth=0.35 * wild)
    _surprised(kit, t, 1.0, 1.8)


def _geiger(p: QPainter, k, wild, t):
    p.save()
    p.setOpacity(k)
    p.setPen(_ink(1.6))
    p.setBrush(QColor("#f2c230"))
    p.drawRoundedRect(QRectF(66, 84, 22, 16), 3, 3)
    p.setBrush(QColor("#f4f6e8"))
    p.drawRoundedRect(QRectF(69, 86.5, 16, 8), 2, 2)
    a = math.radians(-150 + 120 * (0.2 + 0.8 * wild * (0.6 + 0.4 * math.sin(t * 30))))
    p.setPen(QPen(QColor("#ff4d3a"), 1.3))
    p.drawLine(QPointF(77, 94), QPointF(77 + 7 * math.cos(a), 94 + 7 * math.sin(a)))
    p.restore()
    paw(p, 70, 100)


def _glow(p: QPainter, k):
    g = QRadialGradient(50, 70, 58)
    g.setColorAt(0, QColor(120, 255, 90, round(120 * k)))
    g.setColorAt(1, QColor(120, 255, 90, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawEllipse(QRectF(-8, 12, 116, 116))
