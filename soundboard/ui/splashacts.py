"""Bun's start-up acts: the splash (ui/splash.py) picks one at random on every launch
and plays it on a loop until the window is up, then he waves goodbye (`goodbye`).

Each act is a function of the time alone, drawing on Bun's own 100 x 120 canvas (his
feet at 50, 120): `draw(p, show, t, rect)` maps that canvas onto `rect`. The panel
around him has room for props, notes and confetti either side and a little above, so
an act may draw outside the canvas (the splash clips it to the panel). Every act reads
in its first half second: a cold start is often over in one or two.

Now and then a launch is special (`pick`): Golden Bun (1 in 50), the Halloween theme's
witch hat and fangs all October, the Santa hat all December, and the sleepy act most
nights. Animations never draw Bun themselves: they
work out `draw_bunny`'s keywords per frame (docs/MASCOT.md).
"""
from __future__ import annotations

import datetime
import math
import random
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen

from soundboard import theme
from soundboard.bunny import PAW_R, draw_bunny, look_colour, music_note, sparkle
from soundboard.style import bunnyfit

GOLD_ODDS = 50          # one launch in this many gets Golden Bun
NIGHT = (22, 5)         # from 22:00 to 05:00 he's mostly sleepy
NIGHT_WEIGHT = 8        # ... this many times as likely as any other act
GOODBYE_S = 0.5         # his wave as the window comes up
GOLD = {"fur": "#f6cf55", "belly": "#fde9a6", "inner": "#ffb0a8", "nose": "#ff8a73",
        "iris": "#c8781e", "pattern": ()}
# what he wears by month, over the theme's outfit (its hats off); a piece that isn't in
# bunnyfit.PIECES is skipped
SEASONS = {10: ("witch_hat", "fangs"), 12: ("santa",)}
CONFETTI = ("#ff5d8f", "#ffcf40", "#1fb6ff", "#3cc46a", "#a46be8")


@dataclass
class Show:
    """What this launch shows: the act, and anything special about Bun."""
    act: str = "headbang"
    gold: bool = False
    outfit: tuple[str, ...] | None = None   # None: the theme's
    extras: dict = field(default_factory=dict)

    def pose(self, **pose) -> dict:
        """`draw_bunny` keywords with this launch's look and outfit."""
        if self.gold and not pose.get("robot"):
            pose.setdefault("kit", {**bunnyfit.look(), **GOLD})
        if self.outfit is not None:
            pose.setdefault("outfit", self.outfit)
        return pose


def pick(now: datetime.datetime | None = None, rng: random.Random | None = None) -> Show:
    """This launch's act, picked at random (sleepy is the favourite at night), with
    Golden Bun now and then and his season's hat (SEASONS)."""
    now = now or datetime.datetime.now()
    rng = rng or random.Random()
    names = list(ACTS)
    late = now.hour >= NIGHT[0] or now.hour < NIGHT[1]
    weights = [NIGHT_WEIGHT if late and n == "sleepy" else 1 for n in names]
    show = Show(act=rng.choices(names, weights)[0])
    show.gold = show.act != "robo" and rng.randrange(GOLD_ODDS) == 0
    season = tuple(n for n in SEASONS.get(now.month, ()) if n in bunnyfit.PIECES)
    if season:   # his own hat off, the season's on (neck pieces stay)
        show.outfit = tuple(n for n in bunnyfit.outfit()
                            if n not in bunnyfit.HATS and n not in season) + season
    return show


# --- small helpers, all on Bun's canvas ---------------------------------------------

def _ease(k: float) -> float:
    k = min(1.0, max(0.0, k))
    return k * k * (3 - 2 * k)


def _accent() -> QColor:
    return QColor(theme.T["accent"])


def _shadow(p: QPainter, lift: float = 0.0, w: float = 48.0):
    k = max(0.45, 1 - lift / 30)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0, round(55 * k)))
    p.drawEllipse(QPointF(50, 120), w / 2 * k, 4 * k)


def _bun(p: QPainter, show: Show, *, lift: float = 0.0, sx: float = 1.0, sy: float = 1.0,
         angle: float = 0.0, **pose):
    """Bun stood on his feet (50, 120), raised `lift`, squashed `sx` / `sy` and leant
    `angle` about them."""
    p.save()
    p.translate(50, 120 - lift)
    p.rotate(angle)
    p.scale(sx, sy)
    draw_bunny(p, QRectF(-50, -120, 100, 120), **show.pose(**pose))
    p.restore()


def _bun_above(p: QPainter, show: Show, floor: float, *, lift: float = 0.0, **pose):
    """Bun cut off at `floor` (canvas y), as if coming up out of a hole there: drawn on
    a picture first, since draw_bunny sets clips of its own over any clip set here."""
    m = max(0.5, p.deviceTransform().m11())
    box = QRectF(-20, -40, 140, floor + 40)
    img = QImage(max(1, round(box.width() * m)), max(1, round(box.height() * m)),
                 QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    q = QPainter(img)
    try:
        q.scale(m, m)
        q.translate(-box.x(), -box.y())
        _bun(q, show, lift=lift, **pose)
    finally:
        q.end()
    p.drawImage(box, img)


def _note(p: QPainter, x: float, y: float, alpha: float, k: float = 1.2,
          col: QColor | None = None):
    c = QColor(col or _accent())
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    music_note(p, x - 4, y - 8, k, c)


def _rising(t: float, period: float, i: int, n: int) -> float:
    """0..1 through note `i` of `n`'s rise, the notes evenly spaced."""
    return ((t / period) + i / n) % 1.0


def _fade(u: float) -> float:
    return min(1.0, u * 5, (1 - u) * 2.5)


def _sparkles(p: QPainter, t: float, spots, col: QColor | None = None, speed: float = 1.0):
    for i, (x, y, r) in enumerate(spots):
        k = 0.5 + 0.5 * math.sin(2 * math.pi * (t * speed + i * 0.37))
        if k > 0.15:
            sparkle(p, x, y, r * k, col or QColor(("#ffcf40", "#ff8fae", "#1fb6ff")[i % 3]))


def _puff(p: QPainter, x: float, y: float, u: float):
    """A dust puff `u` 0..1 through its life."""
    if not 0 <= u < 1:
        return
    c = QColor(theme.T["muted"])
    c.setAlphaF(0.55 * (1 - u))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    for dx, dy, r in ((-10, 0, 6), (0, -4, 7), (10, 0, 6), (-5, 3, 4.5), (6, 3, 4.5)):
        p.drawEllipse(QPointF(x + dx * (0.5 + u), y + dy * (0.5 + u) - 6 * u), r * (0.6 + u),
                      r * (0.6 + u))


def _zed(p: QPainter, x: float, y: float, size: float, alpha: float):
    c = QColor(_accent())
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    p.setPen(QPen(c, max(1.2, size * 0.22), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    z = QPainterPath(QPointF(x, y))
    z.lineTo(x + size, y)
    z.lineTo(x, y + size)
    z.lineTo(x + size, y + size)
    p.drawPath(z)


def _ink() -> QPen:
    pen = QPen(QColor("#2b2340"), 2.2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


# --- the acts ------------------------------------------------------------------------

def headbang(p: QPainter, show: Show, t: float):
    """Rocking out to his headphones: a big nod on every beat, ears flapping, notes
    flying off both cups."""
    beat = t / 0.48
    down = max(0.0, math.sin(2 * math.pi * beat))
    side = math.sin(math.pi * beat)
    for i in range(4):
        u = _rising(t, 1.3, i, 4)
        s = -1 if i % 2 else 1
        _note(p, 50 + s * (44 + 22 * u) + 4 * math.sin(7 * u + i), 66 - 70 * u, _fade(u))
    _shadow(p, 4 * (1 - down))
    _bun(p, show, lift=4 * (1 - down), nod=11 * side, dip=9 * down, ears=18 * down,
         blink=1.0 if down > 0.6 else 0.0, mouth=0.5 * down)


def karaoke(p: QPainter, show: Show, t: float):
    """Singing into his mic: mouth going, swaying, notes pouring out of the mic."""
    sway = math.sin(2 * math.pi * t / 1.6)
    line = t % 1.6
    belt = line > 1.1   # the long note at the end of each line: eyes shut, mouth wide
    mouth = 0.95 if belt else max(0.0, math.sin(2 * math.pi * t / 0.27)) * 0.8
    for i in range(3):
        u = _rising(t, 1.5, i, 3)
        _note(p, 88 + 30 * u + 5 * math.sin(6 * u + i * 2), 76 - 60 * u, _fade(u))
    _shadow(p)
    _bun(p, show, prop="mic", mouth=mouth, nod=6 * sway - (4 if belt else 0),
         blink=1.0 if belt else 0.0, ears=6 * sway + (8 if belt else 0))


HAMMER_S = 0.7


def build(p: QPainter, show: Show, t: float):
    """Building the board: hammer up, THUNK on the plank, a puff of dust."""
    u = (t % HAMMER_S) / HAMMER_S
    if u < 0.55:                      # lifting it, slow
        swing = 1 - _ease(u / 0.55)
    elif u < 0.7:                     # down hard
        swing = _ease((u - 0.55) / 0.15)
    else:                             # resting on the plank
        swing = 1.0
    hit = (u - 0.7) * HAMMER_S / 0.35 if u >= 0.7 else (u + 0.3) * HAMMER_S / 0.35 + 1
    _shadow(p)
    _puff(p, 104, 112, hit)
    jolt = 1.0 if 0.7 <= u < 0.8 else 0.0
    _bun(p, show, prop="hammer", swing=swing, sy=1 - 0.03 * jolt, sx=1 + 0.02 * jolt,
         blink=jolt, look=0.6, nod=4 * swing)
    if jolt:
        _sparkles(p, 0.25, ((114, 100, 5), (96, 98, 4)), QColor("#ffcf40"))


BAT_S = 1.5


def batting(p: QPainter, show: Show, t: float):
    """Batting practice: a note flies in, he swings and knocks it out of the panel."""
    u = (t % BAT_S) / BAT_S
    hit_at = 0.42
    if u < hit_at - 0.08:       # waiting, bat up, eyes on the note
        swing = 0.0
    elif u < hit_at + 0.04:     # the swing
        swing = _ease((u - hit_at + 0.08) / 0.12)
    else:                       # follow through, then back up
        swing = 1 - _ease((u - hit_at - 0.04) / 0.4)
    if u < hit_at:              # in from the right on a slight arc
        k = u / hit_at
        nx, ny = 172 - 62 * k, 74 + 10 * k - 8 * math.sin(math.pi * k)
        spin = 0.0
    else:                       # knocked up and away
        k = (u - hit_at) / 0.35
        nx, ny = 110 + 90 * k, 84 - 120 * k + 30 * k * k
        spin = 720 * k
    if k <= 1:
        p.save()
        p.translate(nx, ny)
        p.rotate(spin)
        _note(p, 0, 0, 1.0, 1.5)
        p.restore()
    _shadow(p)
    happy = hit_at <= u < hit_at + 0.3
    _bun(p, show, prop="bat", swing=swing, look=0.0 if happy else 1.0,
         blink=1.0 if happy else 0.0, mouth=0.5 if happy else 0.0, nod=-4 * swing)
    if hit_at <= u < hit_at + 0.12:
        _sparkles(p, 0.25, ((108, 80, 7),), QColor("#ffcf40"))


def party(p: QPainter, show: Show, t: float):
    """Party time: party hat, his star held high, bouncing, confetti falling."""
    bounce = abs(math.sin(math.pi * t / 0.42))
    rng = random.Random(7)
    for i in range(22):
        x0, speed, phase = rng.uniform(-80, 180), rng.uniform(55, 95), rng.random()
        y = (phase * 175 + t * speed) % 175 - 30
        p.save()
        p.translate(x0 + 6 * math.sin(t * 3 + i), y)
        p.rotate(t * 200 + i * 40)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(CONFETTI[i % len(CONFETTI)]))
        p.drawRect(QRectF(-2.5, -1.5, 5, 3))
        p.restore()
    hat = show.outfit if show.outfit is not None else bunnyfit.outfit()
    if not any(n in bunnyfit.HATS for n in hat):
        hat = tuple(hat) + ("party",)
    _shadow(p, 6 * bounce)
    _bun(p, show, prop="star", lift=6 * bounce, outfit=hat, blink=1.0, mouth=0.6,
         ears=10 * bounce, nod=5 * math.sin(math.pi * t / 0.84))


SLEEP_S = 3.2


def sleepy(p: QPainter, show: Show, t: float):
    """Nodding off in his nightcap, Z's drifting up, then a start: awake! (and off again)."""
    u = (t % SLEEP_S) / SLEEP_S
    jolt = u > 0.84
    drift = _ease(u / 0.84)
    for i in range(3):
        k = _rising(t, 2.0, i, 3)
        _zed(p, 76 + 18 * k + 4 * math.sin(5 * k + i), 40 - 50 * k, 5 + 6 * k,
             0 if jolt else _fade(k))
    _shadow(p)
    if jolt:
        _bun(p, show, nightcap=True, ears=12, lift=3 * math.sin(math.pi * (u - 0.84) / 0.16))
    else:
        breath = math.sin(2 * math.pi * t / 1.6)
        _bun(p, show, nightcap=True, blink=1.0, dip=1 + 9 * drift, nod=-18 * drift,
             sy=1 + 0.012 * breath, sx=1 - 0.008 * breath)


BOOT_S = 1.1


def robo(p: QPainter, show: Show, t: float):
    """Robo-Bun boots up: LEDs come on one after another, eyes flick on, then he scans
    about, his core pulsing, beeping little signals off his ears."""
    boot = min(1.0, t / BOOT_S)
    led = boot if t < BOOT_S else 0.6 + 0.4 * math.sin(2 * math.pi * t / 0.9)
    eyes = 1.0 if boot < 0.55 else (0.0 if boot >= 0.75 else 1 - (boot - 0.55) / 0.2)
    look = 0.0 if t < BOOT_S else math.sin(2 * math.pi * (t - BOOT_S) / 2.4)
    if t >= BOOT_S:   # signal rings off his ears
        for i in range(2):
            k = _rising(t, 1.2, i, 2)
            c = QColor("#00d4ff")
            c.setAlphaF(0.7 * (1 - k))
            p.setPen(QPen(c, 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            for x in (30, 72):
                p.drawArc(QRectF(x - 6 - 10 * k, 4 - 8 * k - 6, 12 + 20 * k, 12 + 20 * k),
                          30 * 16, 120 * 16)
    _shadow(p)
    _bun(p, show, robot=True, led=led, blink=eyes, look=look,
         mouth=0.4 if t >= BOOT_S and (t % 1.2) < 0.15 else 0.0,
         lift=1.5 * abs(math.sin(math.pi * boot)) if t < BOOT_S else 0.0)


PLUG_S = 2.6


def plug(p: QPainter, show: Show, t: float):
    """Plugging in his headphones: he eyes the plug, clicks it into the cup with a
    spark, and they light up and start playing."""
    u = (t % PLUG_S) / PLUG_S
    clicked = 0.2 <= u < 0.92
    dip = 3.5 * _ease(u / 0.2) if u < 0.2 else (3.5 if clicked else 3.5 * (1 - (u - 0.92) / 0.08))
    if clicked:   # a glow round both cups, pulsing to the music
        g = QColor(_accent())
        g.setAlphaF(0.35 + 0.2 * math.sin(2 * math.pi * t / 0.45))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        for x in (15, 85):
            p.drawEllipse(QPointF(x, 65 + dip), 13, 17)
        for i in range(3):
            k = _rising(t, 1.3, i, 3)
            s = -1 if i % 2 else 1
            _note(p, 50 + s * (46 + 16 * k), 60 - 60 * k, _fade(k))
    _shadow(p)
    groove = math.sin(2 * math.pi * t / 0.45) if clicked and u > 0.28 else 0.0
    _bun(p, show, prop="plug", dip=dip, look=1.0 if u < 0.2 else 0.0, nod=8 * (1 - min(
        1.0, u / 0.2)) + 4 * groove, blink=1.0 if clicked and u > 0.28 else 0.0,
         ears=8 * abs(groove))
    if 0.2 <= u < 0.3:   # the click
        _sparkles(p, 0.25, ((96, 72, 7), (102, 64, 4)), QColor("#ffcf40"))


HOP_S = 0.8


def hop(p: QPainter, show: Show, t: float):
    """Hopping on the spot: crouch, spring up stretched, land with a squish."""
    u = (t % HOP_S) / HOP_S
    if u < 0.15:                     # crouch
        k = math.sin(math.pi * u / 0.15)
        lift, sx, sy, ears = 0.0, 1 + 0.08 * k, 1 - 0.1 * k, -4 * k
    elif u < 0.62:                   # in the air
        k = (u - 0.15) / 0.47
        lift = 16 * math.sin(math.pi * k)
        stretch = 1 - abs(2 * k - 1)
        sx, sy, ears = 1 - 0.05 * (1 - stretch), 1 + 0.06 * (1 - stretch), 10 * (1 - k)
    elif u < 0.78:                   # land
        k = math.sin(math.pi * (u - 0.62) / 0.16)
        lift, sx, sy, ears = 0.0, 1 + 0.1 * k, 1 - 0.12 * k, 12 * k
    else:
        lift, sx, sy, ears = 0.0, 1.0, 1.0, 0.0
    _shadow(p, lift)
    _bun(p, show, lift=lift, sx=sx, sy=sy, ears=ears, blink=1.0 if lift > 6 else 0.0,
         mouth=0.4 if lift > 2 else 0.0)


DRUM_S = 0.44   # one left-right pair of hits


def drums(p: QPainter, show: Show, t: float):
    """On the drums: a little drum in front of him, sticks going, a crash on the cymbal
    every bar."""
    u = (t % DRUM_S) / DRUM_S
    bar = int(t / DRUM_S) % 4 == 3
    _shadow(p, w=58)
    fur = look_colour("fur")
    ink = _ink()
    left = max(0.0, math.sin(2 * math.pi * u))     # 1: the left stick on the drum
    right = max(0.0, -math.sin(2 * math.pi * u))
    _bun(p, show, nod=5 * (left - right), dip=2 * max(left, right),
         blink=1.0 if bar else 0.0, mouth=0.5 if bar else 0.0, ears=6 * max(left, right))
    # the cymbal on its stand, to his right
    wob = 8 * right if bar else 0.0
    p.setPen(QPen(QColor("#8e98ad"), 2))
    p.drawLine(QPointF(104, 92), QPointF(104, 121))
    p.save()
    p.translate(104, 90)
    p.rotate(-12 + wob)
    p.setPen(ink)
    p.setBrush(QColor("#ffcf40"))
    p.drawEllipse(QRectF(-14, -3, 28, 6))
    p.restore()
    if bar and right > 0.4:
        _sparkles(p, 0.25, ((116, 82, 6), (94, 80, 4)), QColor("#ffcf40"))
    # the drum, in front of his feet
    shell = QColor(theme.T["accent"])
    p.setPen(ink)
    p.setBrush(shell)
    p.drawRoundedRect(QRectF(29, 106, 42, 16), 3, 3)
    p.setBrush(QColor("#f4ecf6"))
    p.drawEllipse(QRectF(29, 101, 42, 10))
    # sticks from his paws, then the paws over them
    hits = ((33, 101, left, -1, (42, 105)), (67, 101, right, 1,
                                              (100, 89) if bar else (58, 105)))
    for x, y, k, side, (tx, ty) in hits:
        up = (x + side * 6, y - 22)
        ex, ey = up[0] + (tx - up[0]) * k, up[1] + (ty - up[1]) * k
        p.setPen(QPen(QColor("#2b2340"), 4.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(x, y), QPointF(ex, ey))
        p.setPen(QPen(QColor("#e3b877"), 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(x, y), QPointF(ex, ey))
    p.setPen(ink)
    p.setBrush(fur)
    for x, y, *_ in hits:
        p.drawEllipse(QPointF(x, y), PAW_R, PAW_R - 0.5)


def ears(p: QPainter, show: Show, t: float):
    """Showing off his ears: they dance in and out while his head sways and his eyes
    follow, sparkles at the top of each wiggle."""
    wig = math.sin(2 * math.pi * t / 0.36)
    sway = math.sin(2 * math.pi * t / 1.44)
    _shadow(p)
    _bun(p, show, ears=16 * wig, nod=9 * sway, look=sway, mouth=0.3 * abs(wig),
         blink=1.0 if (t % 2.2) > 2.05 else 0.0)
    if abs(wig) > 0.92:
        _sparkles(p, 0.25, ((18, 4, 5), (84, 6, 5)))


PEEK_S = 3.2


def peekaboo(p: QPainter, show: Show, t: float):
    """Peekaboo: he pops up out of a hole, looks both ways, waves, ducks back in."""
    u = ((t + 0.1) % PEEK_S) / PEEK_S
    if u < 0.1:      # pop up, a little overshoot
        k = u / 0.1
        lift = -125 * (1 - k) + 6 * math.sin(math.pi * k)
    elif u < 0.8:
        lift = 0.0
    elif u < 0.9:    # duck back in
        lift = -125 * _ease((u - 0.8) / 0.1)
    else:
        lift = -125.0
    hole = QColor(theme.T["bg"]).darker(140)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(hole)
    p.drawEllipse(QPointF(50, 120), 36, 6)
    look = -1.0 if 0.1 <= u < 0.2 else 1.0 if 0.2 <= u < 0.3 else 0.0   # this way, that way
    waving = 0.32 <= u < 0.72
    if lift > -124:
        _bun_above(p, show, 120, lift=lift, look=look,
                   wave=math.sin(2 * math.pi * (u - 0.32) * PEEK_S / 0.5) if waving else None,
                   blink=1.0 if waving else 0.0, mouth=0.4 if waving else 0.0,
                   ears=10 if u < 0.15 else 0.0)


SPIN_S = 2.4


def spin(p: QPainter, show: Show, t: float):
    """A happy twirl with a little hop, then a bow, then a grin."""
    u = (t % SPIN_S) / SPIN_S
    if u < 0.3:
        k = _ease(u / 0.3)
        sx = math.cos(2 * math.pi * k)
        _shadow(p, 7 * math.sin(math.pi * k))
        _bun(p, show, lift=7 * math.sin(math.pi * k), sx=sx if abs(sx) > 0.06 else 0.06,
             ears=12 * math.sin(math.pi * k), blink=1.0, mouth=0.5)
        return
    bow = math.sin(math.pi * (u - 0.3) / 0.25) if u < 0.55 else 0.0
    _shadow(p)
    _bun(p, show, dip=9 * bow, nod=-6 * bow, blink=1.0 if bow > 0.2 or u > 0.6 else 0.0,
         mouth=0.3 if u > 0.6 else 0.0, sy=1 - 0.04 * bow)
    if u > 0.6:
        _sparkles(p, t, ((8, 30, 5), (94, 24, 6), (100, 70, 4)))


ACTS = {"headbang": headbang, "karaoke": karaoke, "build": build, "batting": batting,
        "party": party, "sleepy": sleepy, "robo": robo, "plug": plug, "hop": hop,
        "drums": drums, "ears": ears, "peekaboo": peekaboo, "spin": spin}


def _canvas(p: QPainter, rect: QRectF):
    p.translate(rect.x(), rect.y())
    p.scale(rect.width() / 100, rect.height() / 120)


def draw(p: QPainter, show: Show, t: float, rect: QRectF):
    """Frame `t` seconds into `show`'s act, Bun's canvas mapped onto `rect`."""
    p.save()
    try:
        _canvas(p, rect)
        ACTS.get(show.act, headbang)(p, show, t)
        if show.gold:
            _sparkles(p, t * 0.8, ((-8, 30, 6), (104, 20, 7), (112, 78, 5), (-14, 88, 5),
                                   (50, -12, 5)), QColor("#ffcf40"))
    finally:
        p.restore()


def still(p: QPainter, show: Show, rect: QRectF):
    """Bun at rest, for Windows' Animation effects off."""
    p.save()
    try:
        _canvas(p, rect)
        _bun(p, show, robot=show.act == "robo", led=1.0, nightcap=show.act == "sleepy",
             blink=1.0 if show.act == "sleepy" else 0.0)
    finally:
        p.restore()


def goodbye(p: QPainter, show: Show, u: float, rect: QRectF):
    """His goodbye as the window comes up, `u` 0..1 through it: a hop and a wave."""
    p.save()
    try:
        _canvas(p, rect)
        lift = 9 * math.sin(math.pi * min(1.0, u / 0.6))
        _shadow(p, lift)
        _bun(p, show, robot=show.act == "robo", led=1.0, lift=lift,
             wave=math.sin(2 * math.pi * 2.2 * u), blink=1.0, mouth=0.45, ears=8)
    finally:
        p.restore()
