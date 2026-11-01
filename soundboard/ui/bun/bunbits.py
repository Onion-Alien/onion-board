"""Bun's animated widget's (ui/bun/bunnywidget.py) timings, colours and small parts:
the build act's and dances' timings, the springs, blinking, dancing to hits, the
floating notes (`paint_note`, `note_colors`) and the dust, junk and sparks round him.
`bunnywidget` imports them all, so `bunnywidget.X` still works."""
from __future__ import annotations

import math
import random

from PySide6.QtGui import QColor, QPainter

from soundboard.ui.kit import theme
from soundboard.ui.bun import bunsymbols
from soundboard.ui.bun.bunny import INK, music_note, sparkle
from soundboard.ui.bun.bunprops import NOTE_SHAPES

NOTE_COLORS = ("#7c5cff", "#a48bff", "#1fb6ff", "#ff8fae", "#13ce66")
SPARKLE_COLORS = ("#ffcf40", "#ff8fae", "#1fb6ff", "#a48bff")
DUST = QColor("#d9d2e6")
DUST_INK = QColor("#b3a9c7")
SMOKE = QColor("#a9a3b6")   # (light enough to show on dark themes)
CABINET = QColor("#3a3452")
SPARK = QColor("#ffe680")
FAIL_RED = QColor("#ff4d6d")
# build(): when each part of the act ends, in seconds from the start
DASH_END, CLOUD_END, BACK_END = 0.45, 1.6, 2.1
CROUCH = 0.3     # the share of the dash he spends crouching before he dives in
PARTS = 4        # the speaker on his plank: frame, front, woofer, tweeter (the last: ok)
SCREEN_BARS = 6  # Robo-Bun's gadget screen: a bar a blow, the last one when it worked
# a failed build: the blow lands, SNAP, he stares, his ears drop with a sigh, then he
# puts the bits down in a puff (seconds from stop_building(False))
FAIL_SNAP, FAIL_DROP, FAIL_POOF, FAIL_END = 0.15, 0.85, 2.0, 2.5
FINALE = 2.8     # a finished build: the speaker plays beside him this long
POP = 0.35       # popping back out of the dust cloud
FIDGETS = {"yawn": 2.4, "look": 2.6, "tap": 3.2}   # idle fidgets and how long they take
FIDGET_EVERY = (20.0, 40.0)
FIRST_FIDGET = (10.0, 20.0)   # the first one comes a little sooner (an empty tab's Bun)
SWING = 0.55     # one hammer blow, seconds
TALK = 0.008       # mic level that counts as talking (-42 dBFS; also the wizard's "Hearing you")
LOUD = 0.25        # mic level that opens his mouth all the way (-12 dBFS)


def _sway(pose: dict, key: str) -> float:
    """A pose key as draw_bunny gets it (SWAY: how far it moves him)."""
    if key == "nod":
        return pose["nod"] + pose.get("tilt", 0.0)
    if key == "angry":
        return max(pose["angry"], pose["intense"])
    return pose.get(key, 0.0)


def _steps(pose: dict) -> tuple:
    """Where draw_bunny switches a part on or off as a pose key passes a value: shut
    eyes, the open mouth, his ears starting to fold, tears, the frown, cross brows, the
    vein (the kept picture never stands in across one)."""
    sad, angry = pose["sad"], _sway(pose, "angry")
    return (pose["blink"] > 0.6, pose["mouth"] > 0.08, sad * 115 > 0.5, sad > 0.05,
            sad > 0.5, angry > 0.05, angry > 0.4, angry > 0.5)


def loudness(level: float) -> float:
    """A raw mic peak (0..1) as 0..1 on a dB scale, like the level bar: 0 at TALK,
    1 at LOUD. Speech peaks sit far below 1 in linear terms, so a linear scale left
    him still until you yelled."""
    if level <= TALK:
        return 0.0
    return min(1.0, math.log(level / TALK) / math.log(LOUD / TALK))
FPS = 60
FAST_MS = 1000 // FPS
BACK_MS = 33       # Bun mode's pace while a game is in front (he keeps going there)
# a blink shuts fast, stays shut a moment and opens more slowly, like a real one;
# now and then it's a double blink
BLINK_SHUT, BLINK_HOLD, BLINK_OPEN = 0.05, 0.035, 0.13
DOUBLE_BLINK = 0.2
# the springy layer over the pose (paintEvent): stiffness (1/s²) and damping (1/s)
EAR_SPRING = (420.0, 13.0)     # ears trail his moves and wobble as they settle
SQUASH_SPRING = (300.0, 15.0)  # his body jiggles back after a squash or stretch
STRETCH = 0.05     # how tall and thin a fast move makes him, per Bun-height a second
SQUASH = 0.6       # how hard a change of direction (a landing) squashes him
BOB_UP = 2.2      # his idle bob, px each way
JOY_HOPS = (0.17, 0.1, 0.05)   # a click's three hops for joy, in Bun-heights
DANCE_HOP = 0.07   # his highest dance hop (electronic), in Bun-heights
# His picture is kept between frames (`_held`, `_picture`) until some part of him has
# moved HOLD_PX screen pixels: his idle bob and sway move far less than a pixel a frame,
# so most frames show the same Bun, and redrawing him is most of a frame's cost. What's
# round him (notes, dust, his bubble) still moves every frame. False: every frame draws
# him fresh (the tests compare).
HOLD = True
HOLD_PX = 0.25
# how far the furthest bit of him moves for one unit of each pose key, in canvas units
# (100 x 120; ears and nod: per degree, from their pivots to his ear tips)
SWAY = {"blink": 14.0, "mouth": 12.0, "ears": 1.2, "sad": 70.0, "angry": 40.0,
        "swing": 50.0, "nod": 2.0, "dip": 1.0, "look": 1.6, "kick": 15.0}
EAR_DRAG = 9.0     # how far his ears trail behind, degrees per Bun-height a second
BUBBLE = QColor("#fffaf0")
BEG = 2.8          # how long a begging line stays up, seconds
# the Pong Easter egg: GRUMPY_AT clicks inside ANNOY_WINDOW seconds make him cross;
# RED_IN seconds later his face is red, and BAT_POKES more from then fetch his bat
# (each poke keeps him cross for ANNOY_WINDOW; spam before he's red doesn't count)
ANNOY_WINDOW, GRUMPY_AT, RED_IN, BAT_POKES = 3.0, 4, 0.4, 5
ANNOY_CLICKS = GRUMPY_AT + BAT_POKES   # the fewest pokes it can take
TAUNT = 1.5        # how long he taps the bat before the game opens, seconds
NAP_HOURS = (2, 3, 4)   # local hours (2:00 to 4:59) he's asleep, with naps=True
WOKEN_S = 30.0     # how long a click keeps him awake
ZZZ_EVERY = 1.1    # seconds between Zs
NOTE_H = 110       # notes come out their usual size at this Bun height (bigger Bun, bigger)
DANCE_FADE = 3.0   # how fast he gets into a dance or out of it (1/s)
TALK_FADE = 14.0   # ... or into saying a soundbite along with it
STYLE_BLEND = 0.6  # seconds to change from one style of dance to another
# his happy faces while he bounces to a song, (blink, mouth): eyes shut in a ^^ and
# grinning, ^^ with his little smile, eyes open and grinning. He keeps one for a random
# while (FACE_HOLD: low, high, most likely; 15 s on average), then picks again: the
# same one can come up again, more than once in a row
DANCE_FACES = ((1.0, 0.55), (1.0, 0.0), (0.0, 0.5))
FACE_HOLD = (5.0, 30.0, 10.0)
KICK_HOP = 0.26    # a hop on a hit, before the beat is known (seconds)
# the styles he moves to the hits themselves (groove.Groove.hits), not a beat grid: the
# 808 for hip-hop, the kick drums and the snare and riffs for rock (electronic music's
# steady kick is the grid itself, lined up on the kicks)
HIT_BAND = {"hiphop": ("bass",), "rock": ("bass", "drums")}


HIT_LEAD = 0.05   # seconds a move starts before its hit, so it lands right on it


def hit_curve(age: float, decay: float = 5.0) -> float:
    """A hit `age` seconds ago (less than 0: still coming): speeds down to 1 right on
    it, like a head coming down on the beat, then eases back."""
    if age < -HIT_LEAD or age > 2:
        return 0.0
    if age < 0:
        k = 1 + age / HIT_LEAD
        return k * k
    return math.exp(-age * decay)


def accent(groove, bands: tuple, now: float, decay: float = 5.0) -> tuple[float, float]:
    """(0..1 how far into a move, strength) for the hits in `bands` around `now`: the
    last one easing off or the next one, already read, coming down on its time."""
    best = (0.0, 0.0)
    nxt = getattr(groove, "next_hit", None)
    for band in bands:
        age, s = groove.last_hit(band, now)
        best = max(best, (hit_curve(age, decay) * s, s))
        if nxt is not None:
            until, s = nxt(band, now)
            best = max(best, (hit_curve(-until, decay) * s, s))
    return best


SULK_EVERY = 1.7    # seconds a sulky kick takes (sulk)
SULK_SCUFF = 0.4    # ... and where in it his foot scuffs the ground


def sulk_kick(t: float) -> tuple[float, float]:
    """A sulky kick at `t` seconds in (repeating): the foot's swing for draw_bunny's
    `kick` (-1 back .. 1 out in front), and how far through this kick (0..1)."""
    u = t % SULK_EVERY / SULK_EVERY
    if u < 0.3:                      # draws his foot back
        k = -0.7 * math.sin(u / 0.3 * math.pi / 2)
    elif u < 0.45:                   # ... swings it out
        v = (u - 0.3) / 0.15
        k = -0.7 + 1.7 * v * v * (3 - 2 * v)
    elif u < 0.75:                   # ... and lets it drop back
        v = (u - 0.45) / 0.3
        k = 1 - v * v * (3 - 2 * v)
    else:
        k = 0.0
    return k, u


def blink_amount(b: float) -> float:
    """How shut his eyes are (0..1) `b` seconds into a blink."""
    if b < 0:
        return 0.0
    if b < BLINK_SHUT:   # speeding up as the lids come down
        k = b / BLINK_SHUT
        return k * k
    b -= BLINK_SHUT
    if b < BLINK_HOLD:
        return 1.0
    b -= BLINK_HOLD
    if b < BLINK_OPEN:   # easing open
        k = b / BLINK_OPEN
        return 1 - k * k * (3 - 2 * k)
    return 0.0


class _Spring:
    """A damped spring chasing a target: the lag, overshoot and wobble that make a
    move look alive instead of on rails."""
    __slots__ = ("x", "v")

    def __init__(self, x: float = 0.0):
        self.x, self.v = x, 0.0

    def step(self, target: float, dt: float, k: float, d: float) -> float:
        n = max(1, math.ceil(dt / 0.008))   # small steps: steady at any frame rate
        h = dt / n
        for _i in range(n):
            self.v += (k * (target - self.x) - d * self.v) * h
            self.x += self.v * h
        return self.x


class _Note:
    __slots__ = ("x", "y", "vx", "vy", "age", "life", "size", "col", "spin", "calm", "k",
                 "kind", "seed", "shape")

    def __init__(self, x, y, rng: random.Random, strength: float = 1.0, k: float = 1.0):
        self.x, self.y = x, y
        self.k = k   # Bun's size against the usual one: a big Bun's notes are big and fly far
        self.vx = rng.uniform(-18, 18) * k
        self.vy = -rng.uniform(28, 48) * (0.8 + 0.4 * strength) * k
        self.age, self.life = 0.0, rng.uniform(1.2, 1.9)
        self.size = rng.uniform(0.75, 1.15)
        self.col = QColor(rng.choice(NOTE_COLORS))
        self.spin = rng.uniform(-25, 25)
        self.calm = False   # the headphones' slow trickle: fine at the idle frame rate
        self.kind = ""      # or the theme's symbol instead of a note (bunsymbols)
        self.seed = rng.randrange(1 << 16)   # (which 0 or 1, letter, ... a symbol is)
        self.shape = rng.randrange(NOTE_SHAPES)   # ♪ ♩ ♫ or ♬


class _Puff:
    """A ball of dust (or smoke): grows, drifts, fades."""
    __slots__ = ("x", "y", "vx", "vy", "r", "age", "life", "col")

    def __init__(self, x, y, vx, vy, r, life, col: QColor = DUST):
        self.x, self.y, self.vx, self.vy, self.r = x, y, vx, vy, r
        self.age, self.life, self.col = 0.0, life, col


class _Junk:
    """Something flying: junk tossed out of the dust cloud, or the hammer's head. Falls,
    spins, bounces on the floor, fades at the end of its life."""
    __slots__ = ("kind", "x", "y", "vx", "vy", "a", "va", "age", "life")

    def __init__(self, kind, x, y, vx, vy, va, life):
        self.kind, self.x, self.y, self.vx, self.vy = kind, x, y, vx, vy
        self.a, self.va, self.age, self.life = 0.0, va, 0.0, life


class _Spark:
    """A spark off Robo-Bun's wrench: a short bright streak that falls and fades."""
    __slots__ = ("x", "y", "vx", "vy", "age", "life", "col")

    def __init__(self, x, y, vx, vy, life, col: QColor = SPARK):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.age, self.life, self.col = 0.0, life, col


_note_cols: dict[tuple[int, int], tuple[QColor, QColor]] = {}


def _luma(c: QColor) -> float:
    def lin(v: float) -> float:
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(c.redF()) + 0.7152 * lin(c.greenF()) + 0.0722 * lin(c.blueF())


def note_colors(col: QColor) -> tuple[QColor, QColor]:
    """A note colour that stands out on the theme's background (lighter on dark themes,
    darker on light ones, until the contrast is at least 3:1), and its soft rim."""
    bg = QColor(theme.T["bg"])
    key = (col.rgba(), bg.rgba())
    hit = _note_cols.get(key)
    if hit is None:
        lb = _luma(bg)
        dark = lb < 0.35
        c = QColor(col)
        for _i in range(8):
            lc = _luma(c)
            if (max(lc, lb) + 0.05) / (min(lc, lb) + 0.05) >= 3.0:
                break
            c = c.lighter(115) if dark else c.darker(115)
        rim = QColor(255, 255, 255, 70) if dark else QColor(INK.red(), INK.green(), INK.blue(), 60)
        hit = _note_cols[key] = (c, rim)
    return hit


def paint_note(p: QPainter, n) -> None:
    """One floating note (or, `size` < 0.6, a sparkle), faded by its age."""
    k = n.age / n.life
    p.save()
    p.setOpacity(min(1.0, n.age * 6) * (1 - k) ** 1.4)
    p.translate(n.x, n.y)
    p.rotate(n.spin * math.sin(n.age * 4))
    k = getattr(n, "k", 1.0)
    kind = getattr(n, "kind", "")
    if kind:
        col = note_colors(n.col)[0] if kind in bunsymbols.LIKE_NOTES else n.col
        bunsymbols.paint(p, kind, 9 * n.size * k, col, bunsymbols.rim(QColor(theme.T["bg"])),
                         n.seed)
        p.restore()
        return
    col, rim = note_colors(n.col)
    if n.size < 0.6:
        sparkle(p, 0, 0, 5 * k, col)
    else:
        s, o = n.size * k, min(1.6, max(1.0, 0.5 * k))   # (a thin rim at any size)
        shape = getattr(n, "shape", 0)
        x = (-8 if shape >= 2 else -5) * k   # (a beamed pair is wider)
        for ox, oy in ((-o, 0), (o, 0), (0, -o), (0, o)):   # a soft rim so it reads
            music_note(p, x + ox, -8 * k + oy, s, rim, shape)
        music_note(p, x, -8 * k, s, col, shape)
    p.restore()
