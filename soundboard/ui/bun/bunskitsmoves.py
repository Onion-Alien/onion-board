"""Bun's theme skits from Forest to Flashbang (ui/bun/bunskits.py has the list and how a skit
works): the falling leaf, coffee, the coconut, the frost, the robot dance, slow motion, the hot
floor, the notepad, the laptop and the flashbang. `bunskits` re-exports them."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QRadialGradient

from soundboard.ui.bun.bunny import sparkle
from soundboard.ui.bun.bunskitkit import (
    Kit,
    _ink,
    _oval,
    _rand,
    _sneeze,
    burst,
    eseg,
    held,
    lerp,
    paw,
    piece,
    puff,
    seg,
)
from soundboard.ui.bun.bunskitsprops import _drop


def leaf(kit: Kit, t: float):
    """Forest: a leaf floats down and lands on his nose. He sneezes it off."""
    if t < 1.6:
        u = seg(t, 0, 1.6)
        x, y, a = lerp(80, 50, u) + 12 * math.sin(u * 7), lerp(-6, 70, u), 40 * math.sin(u * 7)
    elif t < 2.3:
        x, y, a = 50, 70, 10
    else:
        u = seg(t, 2.3, 3.4)
        x, y, a = 50 + 60 * u, 70 - 30 * u + 40 * u * u, 400 * u
    alive = t < 3.4
    if alive:
        (kit.front if 1.6 <= t < 2.3 else kit.world).append(lambda p: _leaf(p, x, y, a))
    kit.add(nod=-5 * held(t, 0.4, 1.6), dip=-2 * held(t, 0.4, 1.6))
    kit.most(blink=0.45 * held(t, 1.6, 1.8, 0.05))   # (cross-eyed at it)
    _sneeze(kit, t, 2.3)


def _leaf(p: QPainter, x, y, a):
    p.save()
    p.translate(x, y)
    p.rotate(a)
    path = QPainterPath(QPointF(-8, 0))
    path.quadTo(QPointF(0, -6), QPointF(8, 0))
    path.quadTo(QPointF(0, 6), QPointF(-8, 0))
    p.setPen(QPen(QColor("#2f6b2a"), 1.2))
    p.setBrush(QColor("#5cb85c"))
    p.drawPath(path)
    p.drawLine(QPointF(-8, 0), QPointF(7, 0))
    p.restore()


def coffee(kit: Kit, t: float):
    """Mocha: a sip of coffee... and the caffeine kicks in."""
    cup = held(t, 0.2, 1.8, 0.3)
    kit.prop = ""
    if cup:
        sip = held(t, 0.6, 1.4, 0.2)
        x, y = lerp(76, 60, sip), lerp(98, 84, sip)
        kit.front.append(lambda p: _cup(p, x, y, cup, t))
        kit.most(blink=sip)
        kit.add(dip=-2 * sip)
    jitter = held(t, 1.9, 3.4, 0.15)
    kit.add(dx=1.8 * math.sin(t * 70) * jitter, ears=-14 * jitter,
            dy=-3 * abs(math.sin(t * 16)) * jitter)
    kit.most(mouth=0.25 * jitter)


def _cup(p: QPainter, x, y, k, t):
    p.save()
    p.setOpacity(k)
    p.setPen(_ink(1.6))
    p.setBrush(QColor("#f6efe6"))
    p.drawRoundedRect(QRectF(x - 6, y - 7, 12, 12), 2.5, 2.5)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(x + 4, y - 4, 6, 6), -90 * 16, 180 * 16)
    p.setPen(QPen(QColor(200, 200, 210, 150), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for i in (-2, 2):
        steam = QPainterPath(QPointF(x + i, y - 9))
        steam.quadTo(QPointF(x + i + 3 * math.sin(t * 5 + i), y - 13), QPointF(x + i, y - 17))
        p.drawPath(steam)
    p.restore()
    paw(p, x + 2, y + 5)


def coconut(kit: Kit, t: float):
    """Sunset: a sip from his coconut, then a lazy hula sway, eyes shut."""
    cup = held(t, 0.2, 1.6, 0.3)
    kit.prop = ""
    if cup:
        kit.front.append(lambda p: _coconut(p, lerp(78, 64, held(t, 0.5, 1.3, 0.2)), cup))
    sway = held(t, 1.4, 3.8, 0.4)
    kit.add(angle=7 * math.sin(t * 3.4) * sway, dx=3 * math.sin(t * 3.4) * sway,
            nod=4 * math.sin(t * 3.4 + 0.6) * sway)
    kit.most(blink=sway)


def _coconut(p: QPainter, x, k):
    p.save()
    p.setOpacity(k)
    _oval(p, x, 90, 15, 13, QColor("#8a5a2b"), _ink(1.6))
    p.setPen(QPen(QColor("#ff8fae"), 1.8))
    p.drawLine(QPointF(x + 2, 85), QPointF(x - 4, 76))
    umb = QPainterPath(QPointF(x + 2, 80))
    umb.quadTo(QPointF(x + 8, 74), QPointF(x + 14, 80))
    umb.closeSubpath()
    p.setPen(_ink(1.0))
    p.setBrush(QColor("#ffcf40"))
    p.drawPath(umb)
    p.restore()
    paw(p, x + 5, 96)


def mint(kit: Kit, t: float):
    """Mint: he pops a mint leaf in, chews, and breathes out an icy cloud."""
    kit.prop = ""
    pop = eseg(t, 0.2, 0.8)
    if t < 0.85:
        kit.front.append(lambda p: _leaf(p, lerp(80, 52, pop), lerp(96, 78, pop), 30))
        kit.front.append(lambda p: paw(p, lerp(82, 56, pop), lerp(100, 82, pop)))
    if 0.8 < t < 1.7:
        kit.most(mouth=0.1 + 0.2 * abs(math.sin(t * 20)))
    breath = held(t, 1.8, 2.8, 0.15)
    kit.most(mouth=0.55 * breath, blink=0.6 * breath)
    kit.add(dip=-2 * breath, ears=-6 * breath)

    def frost(p, x, y, fade, i):
        puff(p, x, y, 3 + 5 * (1 - fade), fade, QColor(170, 230, 255, 200))
    kit.world.append(lambda p: burst(p, t - 1.8, 54, 80, 9, 26, 1.0, frost, gravity=-6, salt=11,
                                     up=-0.1))
    shiver = held(t, 2.7, 3.4, 0.1)
    kit.add(dx=1.2 * math.sin(t * 55) * shiver)


def robot_dance(kit: Kit, t: float):
    """Synthwave: his visor scans and he does a stiff little robot dance."""
    step = math.floor(t / 0.4)
    on = held(t, 0.3, 3.5, 0.1)
    pose = ((0, 0), (6, 2), (-6, -2), (0, -3), (6, 2), (-6, 2), (0, 0), (6, -2), (0, 0))
    a, d = pose[step % len(pose)]
    kit.add(angle=a * on, dx=d * on, nod=-a * 0.8 * on, ears=(8 if step % 2 else -6) * on)
    sweep = (t * 1.2) % 1.0
    kit.front.append(lambda p: _scan(p, sweep, on))


def _scan(p: QPainter, k, alpha):
    if alpha <= 0:
        return
    x = 30 + 40 * k
    g = QColor(0, 230, 255, round(220 * alpha))
    p.setPen(QPen(g, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(x, 56), QPointF(x, 68))


def slow_mo(kit: Kit, t: float):
    """Vaporwave: everything goes slow and dreamy; he floats beside a turning cube."""
    on = held(t, 0.0, 4.2, 0.8)
    kit.add(dy=-8 * on, angle=6 * math.sin(t * 1.2) * on, ears=8 * math.sin(t * 1.5) * on)
    kit.most(blink=0.5 * on)
    kit.world.append(lambda p: _cube(p, 92, 40 + 4 * math.sin(t * 1.4), t * 0.8, on))


def _cube(p: QPainter, x, y, a, k):
    if k <= 0:
        return
    p.save()
    p.setOpacity(k)
    pts = []
    for cx, cy, cz in ((-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
                       (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)):
        rx = cx * math.cos(a) - cz * math.sin(a)
        rz = cx * math.sin(a) + cz * math.cos(a)
        ry = cy * math.cos(0.5) - rz * math.sin(0.5)
        pts.append(QPointF(x + rx * 7, y + ry * 7))
    p.setPen(QPen(QColor("#ff71ce"), 1.4))
    for i, j in ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4),
                 (0, 4), (1, 5), (2, 6), (3, 7)):
        p.drawLine(pts[i], pts[j])
    p.restore()


def hot_floor(kit: Kit, t: float):
    """Lava: the floor gets hot and he hops from foot to foot."""
    hot = held(t, 0.0, 3.6, 0.4)
    kit.behind.append(lambda p: _heat(p, hot, t))
    hop = held(t, 0.4, 3.1, 0.2)
    k = abs(math.sin(t * 8))
    kit.add(dy=-7 * k * hop, angle=8 * math.copysign(1, math.sin(t * 8)) * hop * 0.8,
            ears=-8 * hop)
    kit.most(mouth=0.45 * hop)
    if hop:
        kit.world.append(lambda p: _drop(p, 76, 52 + 10 * ((t * 1.3) % 1.0), hop, 0))


def _heat(p: QPainter, k, t):
    if k <= 0:
        return
    g = QRadialGradient(50, 118, 40)
    g.setColorAt(0, QColor(255, 120, 40, round(170 * k)))
    g.setColorAt(1, QColor(255, 60, 20, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawEllipse(QRectF(10, 106, 80, 24))
    p.setPen(QPen(QColor(255, 160, 80, round(150 * k)), 1.4))
    for i, x in enumerate((26, 50, 74)):
        w = QPainterPath(QPointF(x, 112))
        for j in range(3):
            w.quadTo(QPointF(x + (3 if j % 2 else -3) + math.sin(t * 6 + i), 108 - j * 6),
                     QPointF(x, 104 - j * 6))
        p.drawPath(w)


def scribble(kit: Kit, t: float):
    """Amber Terminal: the pencil from behind his ear, a few notes on a pad, back it goes."""
    kit.prop = ""
    out = eseg(t, 0.2, 0.8) * (1 - eseg(t, 3.0, 3.6))
    if out > 0:
        kit.hide.add("pencil")
    write = held(t, 0.9, 2.8, 0.1)
    x = lerp(80, 72, out) + 5 * math.sin(t * 18) * write
    y = lerp(37, 98, out) + 1.5 * math.sin(t * 31) * write
    pad = held(t, 0.6, 3.2, 0.2)
    if pad:
        kit.world.append(lambda p: _notepad(p, pad, seg(t, 0.9, 2.8)))
    if out > 0:
        kit.front.append(lambda p: piece(p, "pencil", x - 80, y - 37, 30 * out, (80, 37)))
        kit.front.append(lambda p: paw(p, x - 3, y + 3))
    kit.add(dip=4 * write, nod=2 * math.sin(t * 5) * write)
    kit.most(smug=held(t, 2.8, 3.4, 0.1))


def _notepad(p: QPainter, k, written):
    p.save()
    p.setOpacity(k)
    p.setPen(_ink(1.4))
    p.setBrush(QColor("#fff7d6"))
    p.drawRoundedRect(QRectF(60, 100, 26, 16), 2, 2)
    p.setPen(QPen(QColor("#2b2340"), 1.0))
    for i in range(3):
        w = max(0.0, min(1.0, written * 3 - i)) * 20
        if w > 0:
            p.drawLine(QPointF(63, 104 + i * 4), QPointF(63 + w, 104 + i * 4 + 0.5))
    p.restore()


def hacker(kit: Kit, t: float):
    """Hacker: a tiny laptop, furious typing, a stream of 0s and 1s, a green tick."""
    up = held(t, 0.2, 3.8, 0.3)
    typing = held(t, 0.6, 2.6, 0.1)
    kit.prop = ""
    kit.world.append(lambda p: _laptop(p, up, t, typing, seg(t, 2.6, 2.8)))
    if up:
        for i, x in enumerate((40, 60)):
            kit.front.append(lambda p, i=i, x=x: paw(
                p, x, 100 - 3 * abs(math.sin(t * 20 + i * 1.7)) * typing))
    kit.add(dip=3 * up, dx=0.5 * math.sin(t * 40) * typing)
    kit.most(smug=held(t, 2.8, 3.8, 0.1))


def _laptop(p: QPainter, k, t, typing, done):
    if k <= 0:
        return
    p.save()
    p.setOpacity(k)
    p.setPen(_ink(1.4))
    p.setBrush(QColor("#3a3f4b"))
    p.drawRoundedRect(QRectF(32, 102, 36, 6), 1.5, 1.5)
    screen = QColor("#0b1a0f")
    p.setBrush(screen)
    p.drawRoundedRect(QRectF(36, 86, 28, 17), 1.5, 1.5)
    green = QColor("#39ff6a")
    if done > 0:
        p.setPen(QPen(green, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(44, 95), QPointF(48, 99))
        p.drawLine(QPointF(48, 99), QPointF(57, 89))
    f = QFont()
    f.setPixelSize(6)
    f.setBold(True)
    p.setFont(f)
    for i in range(6):
        u = (t * 0.8 + _rand(i, 3)) % 1.0
        c = QColor(green)
        c.setAlphaF(typing * (1 - u))
        p.setPen(c)
        p.drawText(QPointF(30 + 40 * _rand(i, 6), 84 - u * 40), "1" if i % 2 else "0")
    p.restore()


def flashbang(kit: Kit, t: float):
    """Flashbang: FLASH. He reels, dizzy, stars spinning round his head."""
    kit.flash = (1 - seg(t, 0.4, 1.1)) if t >= 0.35 else 0.0
    dizzy = held(t, 0.5, 2.8, 0.3)
    kit.add(angle=10 * math.sin(t * 5) * dizzy, dx=3 * math.sin(t * 5) * dizzy,
            nod=-8 * math.sin(t * 5 + 1) * dizzy)
    kit.most(blink=0.5 * dizzy, mouth=0.3 * dizzy)
    if dizzy:
        kit.world.append(lambda p: _orbit(p, t, dizzy))


def _orbit(p: QPainter, t, k):
    for i in range(3):
        a = t * 5 + i * 2.1
        x, y = 50 + 30 * math.cos(a), 26 + 8 * math.sin(a)
        c = QColor("#ffcf40")
        c.setAlphaF(k)
        sparkle(p, x, y, 4.5, c)
