"""Bun's idle skits: a little act for each theme, played now and then while he's idle.

Blood Moon's Bun reaches behind him, grabs the moon out of the sky and takes a bite: it's
cheese. Retro 98's pixel shades drop onto his face ("deal with it"), Brainrot's
propeller lifts him off the ground, Swamp's frog hat snaps up a fly, and so on: one per
theme outfit (style/bunnyfit.py), and a juggling act for the themes without one.

A skit is a function of its time alone, `skit(kit, t)`: it adds to his pose (`kit.add`,
`kit.most`), hides outfit pieces it's moving (`kit.hide`) and queues drawings
(`kit.behind` / `kit.front` / `kit.world`), all on Bun's 100 x 120 canvas. Being a
function of time, any frame can be drawn on its own (pictures, tests) and nothing is
left over when it ends. BunnyWidget (`skit()`, `pose`, `paintEvent`) plays them and
draws the queue: `behind` before him, `front` with him (held things move as he does),
`world` after him, standing still.

Everything stays inside his widget's box (a little round him: MASCOT.md), and no skit
shows words: symbols only ("!", "?"), so nothing needs translating.
"""
from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

from soundboard.ui.kit import theme
from soundboard.ui.bun.bunny import music_note
from soundboard.style import bunnyfit
from soundboard.ui.bun.bunskitkit import (  # noqa: F401
    _found,
    _ink,
    _oval,
    _rand,
    _sneeze,
    _sparkles,
    _surprised,
    bump,
    burst,
    Draw,
    ease,
    eseg,
    heart,
    held,
    held_paws,
    Kit,
    lerp,
    mark,
    paw,
    PEN,
    piece,
    puff,
    seg,
)
from soundboard.ui.bun.bunskitsprops import (  # noqa: F401
    _bat,
    _beams,
    _crumb,
    _drop,
    _ember,
    _fish,
    _fly,
    _geiger,
    _glow,
    _moon,
    _peel,
    _poof,
    _propeller,
    _rain_cloud,
    _sneeze_cloud,
    _snow,
    _spyglass,
    _tears,
    _tongue,
    _wand,
    achoo,
    bat,
    blood_moon,
    CHEESE,
    CHEESE_DARK,
    crown,
    deal_with_it,
    frog_fly,
    geiger,
    laser,
    onion,
    propeller,
    spyglass,
    wizard,
)
from soundboard.ui.bun.bunskitsmoves import (  # noqa: F401
    _coconut,
    _cube,
    _cup,
    _heat,
    _laptop,
    _leaf,
    _notepad,
    _orbit,
    _scan,
    coconut,
    coffee,
    flashbang,
    hacker,
    hot_floor,
    leaf,
    mint,
    robot_dance,
    scribble,
    slow_mo,
)

NEXT_PROB = 0.55            # an idle moment's chance of a skit instead of a fidget


def kiss(kit: Kit, t: float):
    """Barbie: she blows a kiss; a heart floats off and pops into sparkles."""
    kit.prop = ""
    hand = held(t, 0.2, 1.3, 0.2)
    out = eseg(t, 0.9, 1.3)
    if hand:
        kit.front.append(lambda p: paw(p, lerp(56, 84, out), lerp(80, 70, out)))
    kit.most(mouth=0.12 * held(t, 0.3, 0.9, 0.1))
    u = seg(t, 1.1, 2.5)
    if 0 < u < 1:
        kit.world.append(lambda p: heart(p, 84 + 12 * u, 66 - 40 * u + 3 * math.sin(u * 12),
                                         4 + 5 * u, QColor("#ff4fa3")))
    kit.world.append(lambda p: _sparkles(p, t - 2.5, 96, 26, salt=12,
                                         cols=("#ff4fa3", "#ffd1e8", "#ffcf40")))
    giggle = held(t, 2.4, 3.3, 0.1)
    kit.most(blink=giggle, mouth=0.3 * giggle)
    kit.add(dy=-3 * abs(math.sin(t * 14)) * giggle)


def party(kit: Kit, t: float):
    """Comic Sans: a toot on a party blower, then confetti everywhere."""
    blow = held(t, 0.4, 1.6, 0.2)
    if blow:
        kit.front.append(lambda p: _blower(p, blow))
        kit.add(dip=-2 * blow)
    kit.world.append(lambda p: burst(p, t - 1.0, 50, 30, 22, 46, 2.2, _confetti, gravity=30,
                                     salt=13, up=0.8))
    kit.most(blink=held(t, 1.6, 2.6, 0.1))
    kit.add(dy=-6 * bump(t, 1.0, 1.4))


def _blower(p: QPainter, k):
    col = QColor(theme.T["accent"])
    p.setPen(QPen(col, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    length = 6 + 26 * k
    path = QPainterPath(QPointF(52, 78))
    path.lineTo(52 + length, 78 - length * 0.2)
    if k < 0.95:   # the curl at its end, unrolling
        path.arcTo(QRectF(52 + length - 4, 78 - length * 0.2 - 8, 8, 8), -90, 300 * (1 - k))
    p.drawPath(path)
    _oval(p, 52, 78, 4, 4, QColor("#ffcf40"), _ink(1.0))


def _confetti(p, x, y, fade, i):
    cols = ("#ff4d6d", "#ffcf40", "#1fb6ff", "#13ce66", "#a48bff")
    c = QColor(cols[i % len(cols)])
    c.setAlphaF(fade)
    p.save()
    p.translate(x, y)
    p.rotate(i * 37 + (1 - fade) * 400)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawRect(QRectF(-1.6, -1, 3.2, 2))
    p.restore()


def fireworks(kit: Kit, t: float):
    """Fireworks: two rockets go up beside him and burst, gold then pink; he goes "ooh",
    then hops."""
    kit.hide.add("burst")   # (his own burst steps aside for the show)
    for at, x, y, col in ((0.3, 10, 26, "#ffc94d"), (1.3, 14, 8, "#ff5fae")):
        kit.behind.append(lambda p, at=at, x=x, y=y, col=col: _rocket(p, t - at, x, y, col))
    kit.most(mouth=0.7 * (held(t, 0.95, 1.5, 0.15) + held(t, 1.95, 2.5, 0.15)),
             blink=held(t, 2.7, 3.2, 0.05))
    kit.add(dy=-7 * bump(t, 2.65, 3.05), ears=6 * bump(t, 2.65, 3.05))


def _rocket(p: QPainter, t, x, top, col):
    """One rocket: a streak up from behind him to (x, top), then a burst of sparks in
    `col` with a few white ones."""
    rise = 0.6
    if 0 < t < rise:
        y = lerp(100, top, ease(t / rise))
        for i in range(5):   # its trail, fading behind it
            c = QColor("#ffe27a")
            c.setAlphaF(0.9 - i * 0.17)
            _oval(p, x, y + i * 5, 4 - i * 0.5, 4 - i * 0.5, c, None)

    def spark(p, px, py, fade, i):   # a streak pointing out from the middle
        c = QColor(col if i % 4 else "#fff6d0")
        c.setAlphaF(min(1.0, 1.6 * fade))
        dx, dy = px - x, py - top
        d = math.hypot(dx, dy) or 1.0
        tail = min(d, 6.0)
        p.setPen(QPen(c, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(px, py), QPointF(px - dx / d * tail, py - dy / d * tail))
    burst(p, t - rise, x, top, 22, 26, 0.95, spark, gravity=14, salt=int(x) + 7, up=0.0)


def bow(kit: Kit, t: float):
    """Light: he straightens his bow tie, then takes a bow."""
    fix = held(t, 0.3, 1.3, 0.15)
    kit.prop = ""
    if fix:
        kit.hide.add("bowtie")
        kit.front.append(lambda p: piece(p, "bowtie", 0, 0, 12 * math.sin(t * 14) * fix, (50, 93)))
        kit.front.append(lambda p: paw(p, 60, 92))
    down = held(t, 1.6, 2.6, 0.3)
    kit.add(dip=12 * down, nod=-3 * down, sy=-0.05 * down, dy=2 * down)
    kit.most(blink=down)
    kit.world.append(lambda p: _sparkles(p, t - 2.6, 50, 30, n=6, salt=14))


def sniff_flower(kit: Kit, t: float):
    """Lilac: he sniffs a flower, sighs happily, then sneezes out petals."""
    kit.prop = ""
    up = held(t, 0.2, 2.3, 0.3)
    if up:
        kit.front.append(lambda p: _flower_in_paw(p, lerp(80, 60, up), lerp(100, 80, up)))
    kit.most(blink=held(t, 0.8, 1.8, 0.2))
    _sneeze(kit, t, 2.3)

    def petal(p, x, y, fade, i):
        c = QColor("#c9a7ff" if i % 2 else "#e6d6ff")
        c.setAlphaF(fade)
        _oval(p, x, y, 4, 2.6, c, None, i * 50)
    kit.world.append(lambda p: burst(p, t - 2.3, 58, 78, 10, 40, 1.2, petal, gravity=20,
                                     salt=15))


def _flower_in_paw(p: QPainter, x, y):
    p.setPen(QPen(QColor("#4caf50"), 1.6))
    p.drawLine(QPointF(x, y), QPointF(x - 4, y - 12))
    bunnyfit._flower(p, x - 4, y - 14, 5, QColor("#c9a7ff"), QColor("#ffe27a"))
    paw(p, x + 1, y + 2)


def petal_catch(kit: Kit, t: float):
    """Cherry Blossom: petals drift down; he catches one and blows it off his paw."""
    kit.world.append(lambda p: _petals(p, t, held(t, 0, 3.8, 0.4)))
    kit.prop = ""
    up = held(t, 1.0, 2.9, 0.2)
    if up:
        kit.front.append(lambda p: paw(p, 74, lerp(100, 82, up)))
    if t < 2.5:
        k = eseg(t, 0.2, 1.5)
        x, y = lerp(90, 74, k), lerp(-4, 77, k)
    else:
        u = seg(t, 2.5, 3.6)
        x, y = 74 + 40 * u, 77 - 50 * u + 10 * math.sin(u * 9)
    if t < 3.6:
        kit.world.append(lambda p: _oval(p, x, y, 5, 3.4, QColor("#ffc1d3"), None, t * 90))
    kit.most(mouth=0.15 * held(t, 2.35, 2.8, 0.1))
    kit.add(nod=5 * held(t, 1.4, 2.8))


def _petals(p: QPainter, t, k):
    if k <= 0:
        return
    for i in range(8):
        fall = (t * 0.22 + _rand(i, 16)) % 1.0
        x = -6 + 112 * _rand(i, 17) + 6 * math.sin(t * 1.5 + i)
        c = QColor("#ffc1d3")
        c.setAlphaF(0.85 * k)
        _oval(p, x, -6 + fall * 128, 4.5, 3, c, None, t * 70 + i * 30)


def spin(kit: Kit, t: float):
    """Carbon: a quick spin on the spot, and a cool pose to finish."""
    turn = eseg(t, 0.4, 1.6)
    kit.add(sx=(math.cos(turn * 4 * math.pi) - 1), dy=-5 * bump(t, 0.4, 1.6))
    posed = held(t, 1.7, 3.0, 0.15)
    kit.add(angle=-6 * posed, nod=-4 * posed, dx=-2 * posed)
    kit.most(smug=posed)
    kit.world.append(lambda p: _sparkles(p, t - 1.6, 50, 60, n=6, salt=18))


def reading(kit: Kit, t: float):
    """Slate: he reads a little book, turns the pages, pushes his readers up."""
    up = held(t, 0.2, 3.8, 0.3)
    kit.prop = ""
    if up:
        kit.front.append(lambda p: _book(p, up, t))
    kit.add(dip=4 * up, nod=2 * math.sin(t * 1.3) * up)
    push = bump(t, 2.9, 3.4)
    if push:
        kit.hide.add("readers")
        kit.front.append(lambda p: piece(p, "readers", 0, -3 * push))
        kit.front.append(lambda p: paw(p, 50, 72 - 2 * push))


def _book(p: QPainter, k, t):
    p.save()
    p.setOpacity(k)
    p.setPen(_ink(1.4))
    p.setBrush(QColor("#8a3b2e"))
    p.drawRoundedRect(QRectF(33, 88, 34, 22), 2, 2)
    p.setBrush(QColor("#fbf3e4"))
    p.drawRect(QRectF(35, 89.5, 15, 19))
    p.drawRect(QRectF(50, 89.5, 15, 19))
    for at in (1.2, 2.3):   # a page turning
        u = seg(t, at, at + 0.4)
        if 0 < u < 1:
            w = 15 * math.cos(u * math.pi)
            p.drawRect(QRectF(50, 89.5, w, 19).normalized())
    p.restore()
    paw(p, 33, 100)
    paw(p, 67, 100)


def paper_plane(kit: Kit, t: float):
    """Paper: he throws a paper plane; it loops round and lands on his head."""
    kit.prop = ""
    throw = held(t, 0.2, 0.9, 0.2)
    if throw:
        kit.front.append(lambda p: paw(p, 78, lerp(98, 80, throw)))
    if 0.2 < t < 0.8:
        kit.front.append(lambda p: _plane(p, 80, lerp(96, 78, throw), -20))
    elif 0.8 <= t < 3.0:
        u = seg(t, 0.8, 3.0)
        a = u * 2 * math.pi
        x, y = 50 + 40 * math.sin(a) * (1 - 0.6 * u), 50 - 30 * math.sin(a * 0.5) - 10 * u
        heading = math.degrees(math.atan2(-30 * math.cos(a * 0.5) * 0.5,
                                          40 * math.cos(a) * (1 - 0.6 * u))) if u < 1 else 0
        kit.world.append(lambda p: _plane(p, x, y, heading))
    elif t < 4.2:
        kit.front.append(lambda p: _plane(p, 52, 34, 15, 1 - seg(t, 3.8, 4.2)))
    land = bump(t, 3.0, 3.25)
    kit.add(sy=-0.05 * land, nod=-4 * held(t, 1.2, 2.8))
    kit.world.append(lambda p: mark(p, 80, 20, "?", held(t, 3.1, 4.0, 0.15)))
    kit.most(blink=bump(t, 3.3, 3.5))


def _plane(p: QPainter, x, y, angle, alpha=1.0):
    p.save()
    p.setOpacity(alpha)
    p.translate(x, y)
    p.rotate(angle)
    path = QPainterPath(QPointF(10, 0))
    path.lineTo(-8, -6)
    path.lineTo(-4, 0)
    path.lineTo(-8, 5)
    path.closeSubpath()
    p.setPen(_ink(1.2))
    p.setBrush(QColor("#ffffff"))
    p.drawPath(path)
    p.drawLine(QPointF(10, 0), QPointF(-4, 0))
    p.restore()


def juggle(kit: Kit, t: float):
    """Any theme without an outfit: he juggles three balls; the last one bonks his head."""
    kit.prop = ""
    on = held(t, 0.2, 3.3, 0.2)
    cols = (QColor(theme.T["accent"]), QColor("#ffcf40"), QColor("#ff8fae"))
    period = 0.9
    for i in range(3):
        u = ((t - 0.2) / period + i / 3) % 1.0
        side = 1 if u < 0.5 else -1
        k = (u % 0.5) / 0.5
        x = 50 + side * lerp(24, -24, k)
        y = 96 - 60 * math.sin(math.pi * k)
        if t > 3.0 and i == 0:   # the bonk: straight down onto his head
            v = seg(t, 3.0, 3.25)
            x, y = 50, lerp(10, 34, v * v) if t < 3.25 else 34 - 30 * seg(t, 3.25, 3.8) + \
                60 * seg(t, 3.25, 3.8) ** 2
        alpha = on if not (t > 3.0 and i == 0) else 1 - seg(t, 3.7, 3.9)
        kit.world.append(lambda p, x=x, y=y, c=cols[i], a=alpha: _ball(p, x, y, c, a))
    if on:
        kit.front.append(lambda p: paw(p, 26, 96 - 4 * abs(math.sin(t * 7))))
        kit.front.append(lambda p: paw(p, 74, 96 - 4 * abs(math.cos(t * 7))))
    kit.add(nod=3 * math.sin(t * 7) * on, dip=-2 * on)
    bonk = bump(t, 3.22, 3.5)
    kit.add(dip=5 * bonk, sy=-0.06 * bonk)
    _surprised(kit, t, 3.25, 3.9)


def _ball(p: QPainter, x, y, col, alpha):
    if alpha <= 0:
        return
    p.save()
    p.setOpacity(alpha)
    _oval(p, x, y, 9, 9, col, _ink(1.4))
    _oval(p, x - 1.8, y - 1.8, 3, 2.4, QColor(255, 255, 255, 170))
    p.restore()


def dj(kit: Kit, t: float):
    """Dark (the default theme, plain Bun in his headphones): a little turntable, a few
    scratches with notes flying off it, then both paws up for the drop."""
    kit.prop = ""
    deck = held(t, 0.2, 3.6, 0.3)
    scratch = held(t, 0.7, 2.6, 0.1)
    wiggle = math.sin(t * 16) * scratch   # the record, back and forth under his paw
    if deck:
        kit.world.append(lambda p: _deck(p, deck, t, wiggle))
        kit.front.append(lambda p: paw(p, 58 + 7 * wiggle, lerp(100, 97, deck)))
        kit.front.append(lambda p: paw(p, 30, lerp(100, 96, deck)))
    kit.add(nod=4 * wiggle, dip=2 * abs(wiggle), ears=-6 * scratch)
    for at in (0.9, 1.3, 1.7, 2.1, 2.5):   # a note off each scratch
        kit.world.append(lambda p, at=at: burst(p, t - at, 60, 92, 1, 30, 0.8, _dj_note,
                                                gravity=-10, salt=int(at * 10), up=1.2))
    drop = held(t, 2.75, 3.7, 0.15)
    if drop:   # paws up, eyes shut, a hop
        kit.front.append(lambda p: paw(p, 20, lerp(96, 70, drop), -30))
        kit.front.append(lambda p: paw(p, 80, lerp(96, 70, drop), 30))
        kit.most(blink=drop)
        kit.add(dy=-7 * bump(t, 2.75, 3.15), ears=-12 * drop)
    kit.world.append(lambda p: _sparkles(p, t - 2.8, 50, 40, n=9, salt=19))


def _deck(p: QPainter, k, t, wiggle):
    p.save()
    p.setOpacity(k)
    p.setPen(_ink(1.6))
    p.setBrush(QColor("#3a3452"))
    p.drawRoundedRect(QRectF(24, 98, 52, 16), 3, 3)
    _oval(p, 58, 104, 22, 9, QColor("#15131f"), _ink(1.2))   # the record (seen from the front)
    _oval(p, 58, 104, 7, 3, QColor(theme.T["accent"]))
    p.setPen(QPen(QColor(255, 255, 255, 90), 1.0))
    a = t * 4 + wiggle * 2   # its grooves catching the light, turning
    p.drawLine(QPointF(58 + 8 * math.cos(a), 104 + 3 * math.sin(a)),
               QPointF(58 + 10 * math.cos(a), 104 + 3.8 * math.sin(a)))
    _oval(p, 32, 104, 5, 5, QColor("#ffcf40"), _ink(1.0))      # a knob
    p.restore()


MIX_LOOP = 4.0   # seconds: `mixing` comes back round to where it started
_BEAT = 0.5      # a pad hit every half second
_PADS = ((21, 101.5), (33, 101.5), (21, 108.5), (33, 108.5))   # the 2 x 2 pads on the desk
_HITS = (0, 3, 1, 2, 0, 2, 3, 1)   # which pad each beat of the loop hits
_RECORD = (66.0, 105.0)


def mixing(kit: Kit, t: float):
    """Not a theme's skit: the Live controls' DJ (speedpitch.DjBunny). Bun at a little
    desk, one paw tapping sound pads on the beat, the other scratching a record, his head
    bopping. Loops every MIX_LOOP seconds with no seam."""
    t %= MIX_LOOP
    kit.prop = ""
    beat = t / _BEAT
    n, k = int(beat) % len(_HITS), beat % 1.0
    tap = max(0.0, 1 - k / 0.3)          # the paw on the pad, lifting off
    lit = max(0.0, 1 - k * _BEAT / 0.4)   # the pad just hit, fading
    x0, y0 = _PADS[_HITS[n]]
    x1, y1 = _PADS[_HITS[(n + 1) % len(_HITS)]]
    move = eseg(k, 0.4, 0.95)
    px = lerp(x0, x1, move)
    py = lerp(y0, y1, move) - 3 - 6 * math.sin(math.pi * seg(k, 0.1, 1.0))
    wiggle = math.sin(t * 2 * math.pi / _BEAT)   # the record, back and forth
    kit.world.append(lambda p: _desk(p, t, _HITS[n], lit, wiggle))
    kit.world.append(lambda p: paw(p, px, py, -10))   # (over the desk, so after it)
    kit.world.append(lambda p: paw(p, _RECORD[0] + 6 * wiggle, 101, 10))
    kit.add(nod=5 * math.sin(math.pi * beat), dip=2.5 * tap, ears=-5 * tap)
    for at in (0.25, 1.25, 2.25, 3.25):   # a note off the record every second
        kit.world.append(lambda p, at=at: burst(p, t - at, _RECORD[0], 96, 1, 30, 0.7,
                                                _dj_note, gravity=-10, salt=int(at * 10),
                                                up=1.2))


def _desk(p: QPainter, t, hit: int, lit: float, wiggle):
    p.save()
    p.setPen(_ink(1.6))
    p.setBrush(QColor("#3a3452"))
    p.drawRoundedRect(QRectF(12, 97, 76, 18), 3.5, 3.5)
    accent = QColor(theme.T["accent"])
    for i, (x, y) in enumerate(_PADS):
        glow = lit if i == hit else 0.0
        if glow > 0:   # a soft halo round the pad just hit
            halo = QColor(accent)
            halo.setAlphaF(0.45 * glow)
            _oval(p, x, y, 16, 10, halo)
        base = QColor("#6a6288")
        c = QColor.fromRgbF(lerp(base.redF(), accent.redF(), glow),
                            lerp(base.greenF(), accent.greenF(), glow),
                            lerp(base.blueF(), accent.blueF(), glow))
        p.setPen(_ink(1.0))
        p.setBrush(c)
        p.drawRoundedRect(QRectF(x - 5, y - 2.6, 10, 5.2), 1.4, 1.4)
    p.setPen(QPen(QColor("#15131f"), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(45, 100), QPointF(45, 111))   # a fader, riding the beat
    _oval(p, 45, 105.5 + 3 * math.sin(t * math.pi * 2 / MIX_LOOP * 2), 5, 2.6,
          QColor("#ffcf40"), _ink(0.9))
    _oval(p, *_RECORD, 24, 10, QColor("#15131f"), _ink(1.2))   # the record
    _oval(p, *_RECORD, 7, 3, accent)
    p.setPen(QPen(QColor(255, 255, 255, 90), 1.0))
    a = t * 2 * math.pi / MIX_LOOP * 4 + wiggle * 2   # its grooves catching the light
    cx, cy = _RECORD
    p.drawLine(QPointF(cx + 8 * math.cos(a), cy + 3 * math.sin(a)),
               QPointF(cx + 10.5 * math.cos(a), cy + 4 * math.sin(a)))
    p.restore()


def _dj_note(p, x, y, fade, i):
    c = QColor(theme.T["accent"])
    c.setAlphaF(fade)
    music_note(p, x - 4, y - 8, 0.8, c)


# theme -> (seconds, skit); a theme that isn't listed juggles
SKITS: dict[str, tuple[float, Callable[[Kit, float], None]]] = {
    "Blood Moon": (5.2, blood_moon),
    "Retro 98": (3.8, deal_with_it),
    "Brainrot": (3.6, propeller),
    "Swamp": (3.4, frog_fly),
    "Deep Fried": (3.3, laser),
    "Vampire": (4.4, bat),
    "Midnight": (3.7, wizard),
    "Ocean": (3.6, spyglass),
    "Arctic": (3.6, achoo),
    "Royal": (3.7, crown),
    "Onion": (3.6, onion),
    "Toxic": (3.4, geiger),
    "Forest": (3.6, leaf),
    "Mocha": (3.6, coffee),
    "Sunset": (3.9, coconut),
    "Mint": (3.5, mint),
    "Synthwave": (3.8, robot_dance),
    "Vaporwave": (4.2, slow_mo),
    "Lava": (3.6, hot_floor),
    "Amber Terminal": (3.8, scribble),
    "Hacker": (4.0, hacker),
    "Flashbang": (3.0, flashbang),
    "Barbie": (3.4, kiss),
    "Comic Sans": (3.4, party),
    "Light": (3.0, bow),
    "Lilac": (3.6, sniff_flower),
    "Cherry Blossom": (3.8, petal_catch),
    "Carbon": (3.1, spin),
    "Slate": (4.0, reading),
    "Paper": (4.3, paper_plane),
    "Dark": (3.9, dj),
    "Fireworks": (3.4, fireworks),
}
GENERIC = (4.0, juggle)


def for_theme(name: str | None = None) -> tuple[float, Callable[[Kit, float], None]]:
    """The skit for theme `name` (default: the current one)."""
    return SKITS.get(name or theme.current_name, GENERIC)
