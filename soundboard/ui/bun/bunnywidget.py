"""Bun, alive: the mascot from soundboard/ui/bun/bunny.py in a widget that animates.

He bobs gently, blinks every few seconds and flicks an ear now and then. Feed him
the mic level (`set_level`, 0..1) and he talks along: the mouth opens with your
voice, he bounces, and music notes float up out of him. `burst()` throws a handful
of notes (the test sound); `celebrate=True` makes him hop with twinkling sparkles.

`sad` (0..1) is Bun waiting for something: ears drooping, worried brows, wet eyes,
a big sigh now and then. Give him `lines` and every so often he begs for it in a
speech bubble with a hopeful little hop (the widget gets room beside him for it).
`hope(True)` (say, while files are dragged over him) cheers him up and he bounces,
saying one of `hope_lines`; `hope(False)` and he's back to waiting. A click makes
him hop for joy (`joy_lines`) and emits `clicked`.

`build()` is for the cable install: he crouches and dives into a cartoon dust cloud
(all inside his own box), rummages in it (junk flies out, his ears pop up), pops back
out with a hammer and a plank and hammers a little speaker together on it, a part a
blow, until `stop_building(ok)`. ok: the last part pops on, he cheers with a star and
the speaker plays beside him. Not ok: the blow lands, SNAP (the hammer's head flies
off, the plank breaks, smoke), he stares, his ears drop with a sigh and he puts the
bits down in a puff, sad. Robo-Bun does it with a wrench and a gadget whose screen
fills a bar a blow, sparks on every blow and LED ears pulsing while he works.

Now and then (every 20 to 40 s) an idle Bun fidgets: a yawn, a look round, a foot tap
to the beat.

`pong=True` hides an Easter egg: poke him a few times quickly and he gets cross, and
poke him `ANNOY_CLICKS` times and he storms off the same way, comes back with a
baseball bat and challenges you to Pong (ui/bun/bunpong.py) over the page.
Closing the game calls `calm_down()`, and he's back to how he was.

`sulk = True`: he's down and kicks at the ground, over and over, a puff of dust each
time (the Store tab while the store is down).

`naps=True`: in the small hours (NAP_HOURS, by this PC's own clock; nothing is sent
anywhere) he's asleep in a nightcap, breathing slowly, with Zzz floating up. A click
wakes him, grumpy, for WOKEN_S seconds; then he nods off again.

The widget is bigger than Bun himself so there's room around him for the notes,
which also gives him even breathing room in a layout. The timer only runs while
he's on screen, always at the same 60 fps (a slower idle pace made the bob judder
next to the smooth blinks and ear flicks); Bun mode drops to 30 behind a game.
Drawing him is most of a frame, and his idle sway moves him far less than a pixel a
frame, so his picture is kept (`HOLD`): a frame shows it until some part of him has
moved HOLD_PX, and a frame where nothing at all moved isn't painted. Notes, dust and
his bubble still move every frame.

`rest_after_s=N`: with nothing going on he only moves for N seconds after he's shown
(or after the last sound, click or burst), then finishes what he's doing and holds
still: the timer stops and the last pose stays, so an empty page costs nothing. A
sound (`set_groove`), the mic (`set_level`) or a click wakes him; showing him again
gives him another N seconds. In lite mode (ui/settings/lite.py) every Bun rests like that after
lite.REST_S (`_rest_s`), so he's a still picture until something happens.

Over the pose sits a springy layer (`_spring`, `springy`): his ears trail behind his
hops and wobble as they settle, a fast move stretches him and a landing squashes him,
then he jiggles back into shape.
"""
from __future__ import annotations

import logging
import math
import random
import time
import weakref

import shiboken6

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from soundboard.ui.kit import theme
from soundboard.core import usage
from soundboard.ui.bun.bunny import (
    FUR,
    GADGET_SCREEN,
    INK,
    PINK,
    PLANK_SPOT,
    ROOM_TOP,
    ROBOT_CYAN,
    ROBOT_CYAN_HI,
    ROBOT_FUR,
    ROBOT_INK,
    STEEL,
    WOOD,
    WOOD_DARK,
    H,
    W,
    draw_bunny,
    look_colour,
    music_note,
    sparkle,
)
from soundboard.i18n import _
from soundboard.style import bunnyfit, mascotlines
from soundboard.ui.kit import appstate
from soundboard.ui.bun import bunskits
from soundboard.ui.settings import lite
from soundboard.ui.kit.pixels import snap_to_pixels

log = logging.getLogger(__name__)

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
STYLE_BLEND = 0.6  # seconds to change from one style of dance to another
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


def local_hour() -> int:
    """The hour on this PC's clock (read here only, never sent anywhere)."""
    return time.localtime().tm_hour


class _Note:
    __slots__ = ("x", "y", "vx", "vy", "age", "life", "size", "col", "spin", "calm", "k")

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
    col, rim = note_colors(n.col)
    k = getattr(n, "k", 1.0)
    if n.size < 0.6:
        sparkle(p, 0, 0, 5 * k, col)
    else:
        s, o = n.size * k, min(1.6, max(1.0, 0.5 * k))   # (a thin rim at any size)
        for ox, oy in ((-o, 0), (o, 0), (0, -o), (0, o)):   # a soft rim so it reads
            music_note(p, -5 * k + ox, -8 * k + oy, s, rim)
        music_note(p, -5 * k, -8 * k, s, col)
    p.restore()


class BunnyWidget(QWidget):
    clicked = Signal()
    challenge = Signal()   # (pong=True) back with his bat: open the game
    # the ones made with dances=True: the main window's tick hands each one on screen
    # what's playing (set_groove), so he dances to any sound or the radio
    dancers: weakref.WeakSet = weakref.WeakSet()
    alive: weakref.WeakSet = weakref.WeakSet()   # every one (lite mode on / off: lite_changed)

    def __init__(self, prop: str | None = None, height: int = 110, pad: int = 26,
                 celebrate: bool = False, parent=None, *, sad: float = 0.0,
                 lines=(), hope_lines=(), joy_lines=(), pong: bool = False,
                 naps: bool = False, robot: bool = False, in_background: bool = False,
                 dances: bool = False, rest_after_s: float | None = None):
        super().__init__(parent)
        BunnyWidget.alive.add(self)
        if dances:
            BunnyWidget.dancers.add(self)
        self.in_background = in_background   # keeps moving with a game in front (Bun mode)
        self.robot = robot              # Robo-Bun: metal, LEDs, a wrench instead of a hammer
        self.pong = pong
        self.naps = naps
        self._woken_until = 0.0         # a click woke him: awake until then
        self._hour, self._hour_at = -1, -1e9   # the clock's hour, read once a few seconds
        self.zzz: list[list[float]] = []      # [x, y, age]: Zs floating up while he sleeps
        self._zzz_debt = 0.0
        self._pokes: list[float] = []   # recent click times (the Pong Easter egg)
        self._angry = 0.0               # how cross he looks right now (smoothed)
        self._cross_until = 0.0         # ... and stays cross until then
        self._red_at = -1.0             # poked cross: red in the face from then (or -1)
        self._red_pokes = 0             # ... and the pokes since, towards BAT_POKES
        self._act_kind = "build"        # which act is running: "build" or "bat"
        self._dared = False             # the bat act has sent `challenge`
        self.lines, self.hope_lines, self.joy_lines = (tuple(lines), tuple(hope_lines),
                                                       tuple(joy_lines))
        # room either side for the speech bubble (both, so he stays centred)
        self.side = round(height * 1.3) if (lines or hope_lines or joy_lines) else 0
        self.say = ""
        self._say_until = 0.0
        self._beg_at = -1.0
        self._joy_at = -1.0
        if joy_lines:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sad = sad             # his mood at rest
        self.sulk = False          # kicking at the ground (see the module's notes)
        self._kicks = -1           # the last sulky kick that threw up dust
        self._home_sad = sad       # ... which a failed build only dents until the next try
        self._sad = sad            # ... and right now (smoothed)
        self._hopeful = False
        self._sigh_at = -1.0
        self.prop = prop
        self.bun_h = height
        self.pad = pad
        self.celebrate = celebrate
        self.setSizePolicy(QSizePolicy.Policy.Maximum if self.side else QSizePolicy.Policy.Fixed,
                           QSizePolicy.Policy.Fixed)
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
        self._next_sigh = self._t0 + self._rng.uniform(2.5, 5)
        self._next_beg = self._t0 + self._rng.uniform(1.5, 3)
        self._note_debt = 0.0
        self.notes: list[_Note] = []
        self.puffs: list[_Puff] = []
        self._home_prop, self._home_celebrate = prop, celebrate
        self._act_t = -1.0         # seconds into build(), or -1 when not building
        self._blows = 0            # hammer blows landed so far
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)   # (even frames at 60 fps)
        self._timer.setInterval(FAST_MS)
        self._timer.timeout.connect(self._step)
        self.rest_after_s = rest_after_s   # (see the module's notes)
        self._rest_at = self._t0 + (self._rest_s() or 0.0)   # settles down from then
        self.resting = False            # holding still: the timer's off until a stir
        self._still_at = 0.0            # ... and the moment his pose was kept
        if pong:
            self.challenge.connect(self._open_game)
        if in_background:
            appstate.slow_in_background(self, self._timer, FAST_MS, BACK_MS)
        else:
            appstate.pause_in_background(self, self._resume, self._timer.stop)
        self._ears_s = _Spring()        # the springy layer (_spring): ears,
        self._squash_s = _Spring()      # ... squash and stretch,
        self._dy_last, self._vy = 0.0, 0.0   # ... and how fast he's moving up or down
        self._kept_img: QImage | None = None   # his picture (_picture), kept while he's
        self._kept_pose: dict | None = None    # ... this close to the pose it shows (_held)
        self._kept_key: tuple = ()
        self._painted_say = ""          # the bubble the last frame showed
        self.junk: list[_Junk] = []     # tossed out of the dust cloud, the hammer's head
        self.sparks: list[_Spark] = []
        self._junk_debt = 0.0
        self._parts = 0                 # what's built so far (speaker parts / screen bars)
        self._part_at = [-1.0] * SCREEN_BARS   # act time each one went on
        self._flash_at = -1.0           # act time of the last wrench blow (a flash)
        self._fail_t = -1.0             # seconds into the failure beat, or -1
        self._fail_snap = False         # ... which snaps the tools (he was hammering)
        self._fail_swing = 0.0          # where the hammer was when it failed
        self._fin_t = -1.0              # seconds into the finished speaker playing, or -1
        self._pop_t = -1.0              # seconds into popping out of the cloud, or -1
        self._fidget = ""               # the idle fidget going on ("" none)
        self._fidget_at = -1.0
        self._next_fidget = self._t0 + self._rng.uniform(*FIRST_FIDGET)
        self._skit = None               # the theme's skit playing (bunskits), or None
        self._skit_at = -1.0
        self._kit: bunskits.Kit | None = None   # ...this frame of it (pose, paintEvent)
        self.groove = None              # the song playing (set_groove), or None
        self._dance = 0.0               # how much he's dancing (0..1, fades in and out)
        self._style, self._style_was, self._blend = "", "", 1.0
        self._last_beat: float | None = None
        self._g_energy = self._g_voice = 0.0
        self._kick_at = -1.0            # a hop on a hit, before the beat is known
        self._note_hit = -1.0           # the hit the last notes came out on

    def sizeHint(self) -> QSize:
        return QSize(round(self.bun_h * W / H) + 2 * self.pad + 20 + 2 * self.side,
                     self.bun_h + 2 * self.pad + self._head())

    def minimumSizeHint(self) -> QSize:
        """The bubble's room gives way when space is short (it then overlaps him)."""
        return QSize(round(self.bun_h * W / H) + 2 * self.pad + 20,
                     self.bun_h + 2 * self.pad + self._head())

    def _head(self) -> int:
        """Extra room above him where `pad` is too small for an upright ear (or a tall
        hat) at the top of his bob: they reach ROOM_TOP above his canvas."""
        return max(0, math.ceil(self.bun_h * ROOM_TOP / H + BOB_UP) - self.pad)

    # ------------------------------------------------------------------ inputs
    def set_level(self, level: float):
        """The live mic level, 0..1. Call it as often as you like (the wizard: 25/s)."""
        self._level = max(float(level), self._level * 0.8)
        if self._level > TALK:
            self.stir()

    def note_k(self) -> float:
        """How big his notes are, against the usual: they grow and shrink with him."""
        return max(0.3, (self.bun_h / NOTE_H) ** 0.85)

    def set_groove(self, groove):
        """The song playing, as a groove.Groove (its beat and style), or None. He dances
        to it: on the beat, in the song's style (see `_moves`), notes flying on the beats."""
        self.groove = groove
        if groove is not None:
            self.stir()

    def stir(self):
        """Something happened (a sound, a click): with `rest_after_s` he moves again
        and keeps moving for another rest_after_s seconds."""
        rest = self._rest_s()
        if rest is None:
            return
        self._rest_at = time.monotonic() + rest
        if self.resting:
            self.resting = False
            # (no begging for music the moment one starts: the beg held back waits)
            self._next_beg = max(self._next_beg, self._rest_at - rest
                                 + self._rng.uniform(3, 6))
            if self.isVisible() and (self.in_background or appstate.active()):
                self._resume()

    def _rest_s(self) -> float | None:
        """How long he moves after a stir (None: always): rest_after_s, or shorter in
        lite mode."""
        return lite.rest_s(self.rest_after_s)

    @classmethod
    def lite_changed(cls):
        """Lite mode went on (each one settles soon) or off (back to moving)."""
        now = time.monotonic()
        for b in list(cls.alive):
            if not shiboken6.isValid(b):   # (Qt freed it; the wrapper's still about)
                continue
            rest = b._rest_s()
            if rest is not None:
                b._rest_at = min(b._rest_at, now + rest) if lite.on() else now + rest
            if not lite.on() and b.resting:
                b.resting = False
                if b.isVisible() and (b.in_background or appstate.active()):
                    b._resume()

    def burst(self, n: int = 6):
        """Throw a handful of notes out at once."""
        self.stir()
        for _i in range(n):
            self._spawn(1.3)

    def hope(self, on: bool):
        """Cheer him up (True) or let him go back to his mood at rest (False)."""
        if on and not self._hopeful:
            self.burst(5)
            self._say(self.hope_lines, 60.0)
        elif not on and self._hopeful:
            self.say = ""
        self._hopeful = on

    def cheer(self):
        """A happy hop, notes and a joyful line (what a click does)."""
        self._joy_at = time.monotonic()
        self.burst(6)
        # his own lines for where he is, and his theme's character (mascotlines.py)
        self.say = mascotlines.pick(self._rng, self.joy_lines + mascotlines.bun(), self.say)
        usage.used("bun-talk")
        self._say_until = time.monotonic() + mascotlines.read_secs(self.say)

    @property
    def asleep(self) -> bool:
        """Napping right now: naps on, the small hours, not just woken, not mid-act (nor
        while its ending plays out)."""
        if not self.naps or self.building or self._fail_t >= 0 or self._fin_t >= 0:
            return False
        now = time.monotonic()
        if now < self._woken_until or self._dance > 0.05:   # (music wakes him)
            return False
        if now - self._hour_at > 5:
            self._hour, self._hour_at = local_hour(), now
        return self._hour in NAP_HOURS

    def wake(self):
        """A click while he naps: up he gets, grumpy, for WOKEN_S seconds."""
        now = time.monotonic()
        usage.used("egg-bun-woken")   # the name only (usage.py)
        self._woken_until = now + WOKEN_S
        self._cross_until = now + 1.6
        self.zzz.clear()
        self.say = self._rng.choice((_("huh?! wha…"), _("five more minutes…"),
                                     _("it's the middle of the night!"), _("zzz… hm?!")))
        self._say_until = now + 2.2

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.stir()
        if ev.button() == Qt.MouseButton.LeftButton and self.asleep:
            self.wake()
            self.clicked.emit()
            super().mousePressEvent(ev)
            return
        if ev.button() == Qt.MouseButton.LeftButton and self.naps:
            self._woken_until = max(self._woken_until, time.monotonic() + WOKEN_S)
        if ev.button() == Qt.MouseButton.LeftButton and self.joy_lines:
            if not self.poke():
                self.cheer()
            self.clicked.emit()
        super().mousePressEvent(ev)

    def poke(self) -> bool:
        """A click, for the Pong Easter egg: True if it made him cross (rather than
        happy). The BAT_POKES-th one after he's gone red sends him off for his bat."""
        if not self.pong:
            return False
        if self.building:
            return True   # mid-act: more clicks do nothing
        now = time.monotonic()
        if self._red_at < 0 or now >= self._cross_until:   # not cross (any more)
            self._red_at, self._red_pokes = -1.0, 0
            self._pokes = [t for t in self._pokes if now - t < ANNOY_WINDOW] + [now]
            if len(self._pokes) < GRUMPY_AT:
                return False
            self._red_at = now + RED_IN   # he turns red; pokes count from then on
        elif now >= self._red_at:
            self._red_pokes += 1
        self._cross_until = now + ANNOY_WINDOW
        if self._red_pokes >= BAT_POKES:
            self.fetch_bat()
        else:
            grumpy = (_("hey!"), _("quit it!"), _("stop poking!"), _("okay, that's it…"))
            self.say = grumpy[min(self._red_pokes, len(grumpy) - 1)]
            self._say_until = now + 1.2
            self._joy_at = -1.0
        return True

    def fetch_bat(self):
        """He storms off and comes back with a baseball bat, then sends `challenge`."""
        self._pokes.clear()
        self._red_at, self._red_pokes = -1.0, 0
        self._act_kind, self._dared = "bat", False
        self._act_t, self._blows = 0.0, 0
        self.celebrate = False
        self.say = ""

    def calm_down(self):
        """Back to how he was before the game (it closed)."""
        self._pokes.clear()
        self._red_at, self._red_pokes = -1.0, 0
        self._act_t, self._act_kind, self._dared = -1.0, "build", False
        self._cross_until = 0.0
        self.prop, self.celebrate = self._home_prop, self._home_celebrate
        self.say = ""
        self.junk.clear()

    def _open_game(self):
        from soundboard.ui.bun import bunpong  # only ever needed once someone finds it
        self.say = ""   # (his taunt would poke out from under the game)
        bunpong.open_for(self)

    def _say(self, lines, secs: float):
        if lines:
            self.say = self._rng.choice(lines)
            self._say_until = time.monotonic() + secs

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

    # ------------------------------------------------------------------ animation
    def showEvent(self, ev):
        rest = self._rest_s()
        if rest is not None:   # shown again: another rest_after_s to move
            self.resting = False
            self._rest_at = time.monotonic() + rest
        # behind a game it waits until the app is back in front
        if self.in_background or appstate.active():
            self._resume()
        super().showEvent(ev)

    def _resume(self):
        if self.resting:   # (back in front of a game: still until something stirs him)
            return
        self._last = time.monotonic()
        self._timer.start(appstate.interval(FAST_MS, BACK_MS) if self.in_background
                          else FAST_MS)

    def hideEvent(self, ev):
        self._timer.stop()
        self._kept_img = self._kept_pose = None
        if self._act_kind == "bat" and self.building:   # left the page mid-dare
            self.calm_down()
        self._level = 0.0
        super().hideEvent(ev)

    def _step_sulk(self, now: float):
        """A puff of dust each time his sulky kick scuffs the ground."""
        n = int((now - self._t0) / SULK_EVERY)
        if n == self._kicks or (now - self._t0) % SULK_EVERY / SULK_EVERY < SULK_SCUFF:
            return
        self._kicks = n
        body = self._bun_rect()
        at = self._at(body, 80, 112)
        for _i in range(5):
            self._puff(at.x(), at.y(), self.bun_h * 0.35, self.bun_h * 0.05, 0.6)

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
            c = self._at(r, 104, 109)
            self.junk.append(_Junk("head", c.x(), c.y(), -r.height() * 0.4,
                                   -r.height() * 2.0, 820, FAIL_END - FAIL_SNAP))
            b = self._at(r, 84, 112)
            for _i in range(3):
                self._puff(b.x(), b.y(), 22, 4, 0.5)
        for _i in range(7):
            self._puff(c.x(), c.y() - r.height() * 0.04, 30, r.height() * 0.07, 1.1, SMOKE)

    def _step_act(self, dt: float):
        before = self._act_t
        self._act_t += dt
        phase = self.act_phase()
        r = self._bun_rect()
        if phase == "cloud":
            # the scuffle: dust keeps rolling off the cloud, junk flies out of it
            c = self._cloud_spot()
            if self._rng.random() < dt * 30:
                self._puff(c.x() + self._rng.uniform(-0.2, 0.2) * r.width(),
                           c.y() + self._rng.uniform(-0.1, 0.1) * r.height(), 40,
                           r.height() * 0.08, 0.6)
            self._junk_debt += dt
            if self._junk_debt >= 0.22 and self._act_t < CLOUD_END - 0.3:
                self._junk_debt = 0.0
                self._toss()
        elif phase == "back" and before < CLOUD_END:
            c = self._cloud_spot()
            for _i in range(8):   # out he pops, in a burst of dust
                self._puff(c.x(), c.y(), 50, r.height() * 0.08, 0.5)
            if self._act_kind != "build":
                self.prop = "bat"
            else:
                self.prop = "wrench" if self.robot else "hammer"
        elif phase == "bat":
            if before < BACK_END:
                self.say = _("you want some?")
                self._say_until = time.monotonic() + TAUNT + 0.6
            elif not self._dared and self._act_t >= BACK_END + TAUNT:
                self._dared = True
                self.challenge.emit()
        elif phase == "hammer":
            blows = int((self._act_t - BACK_END) / SWING + 0.3)   # strikes at k = 0.7
            if blows > self._blows:   # just hit: something gets built
                self._blows = blows
                if self._parts < (SCREEN_BARS if self.robot else PARTS) - 1:
                    self._add_part()
                if self.robot:        # a spark shower off the bolt
                    self._flash_at = self._act_t
                    c = self._at(r, 104, 108)
                    for _i in range(6):
                        a = self._rng.uniform(math.pi * 1.1, math.pi * 1.9)
                        v = r.height() * self._rng.uniform(0.7, 1.4)
                        self.sparks.append(_Spark(c.x(), c.y(), math.cos(a) * v,
                                                  math.sin(a) * v, self._rng.uniform(0.25, 0.5)))
                    return
                x = r.left() + r.width() * 1.04    # where the hammer lands
                y = r.top() + r.height() * 0.9
                for _i in range(3):
                    self._puff(x, y, 26, 4, 0.5)
                if blows % 2 == 0:
                    n = _Note(x, y - 6, self._rng, 0.6, self.note_k())
                    n.col = QColor(self._rng.choice(SPARKLE_COLORS))
                    self.notes.append(n)

    def _step(self):
        now = time.monotonic()
        dt = min(0.1, now - self._last)
        self._last = now
        if self.building:
            self._step_act(dt)
        self._step_beats(now, dt)
        for f in self.puffs:
            f.age += dt
            f.x += f.vx * dt
            f.y += f.vy * dt
            f.vx *= 1 - dt * 2
            f.vy *= 1 - dt * 2
        self.puffs = [f for f in self.puffs if f.age < f.life]
        if self.sulk:
            self._step_sulk(now)
        talking = self._level > TALK
        # mouth follows the voice with a quick attack and a flappy wobble
        loud = loudness(self._level)
        target = 0.3 + 0.7 * loud if talking else 0.0
        if talking:
            target *= 0.65 + 0.35 * abs(math.sin((now - self._t0) * 17))
        self._mouth += (target - self._mouth) * min(1.0, dt * (22 if target > self._mouth else 12))
        hop = (0.3 + 0.7 * loud) * 6 if talking else 0.0
        self._bounce += (hop - self._bounce) * min(1.0, dt * 10)
        grooving = self._step_groove(now, dt)
        # notes: a stream while talking, scaled by how loud (dancing: on the beat instead)
        if grooving:
            pass
        elif talking:
            self._note_debt += dt * (2 + 10 * loud)
            while self._note_debt >= 1:
                self._note_debt -= 1
                self._spawn(max(0.3, loud))
        elif (self.prop == "headphones" and self.sad < 0.5   # sad: the music's gone
              and not (self._rest_s() is not None and now >= self._rest_at)):
            self._note_debt += dt * 0.7   # something's always playing in his headphones
            if self._note_debt >= 1:
                self._note_debt = 0.0
                self._spawn(0.5, calm=True)   # not "busy": he'd never idle in them
        for n in self.notes:
            n.age += dt
            n.x += n.vx * dt
            n.y += n.vy * dt
            n.vx *= 1 - dt * 0.6
        self.notes = [n for n in self.notes if n.age < n.life]
        self._level *= 0.9 ** (dt * 30)   # (the same fall-off at any frame rate)
        # blink / ear flick schedules
        if now >= self._next_blink:
            self._blink_at = now
            double = self._rng.random() < DOUBLE_BLINK
            self._next_blink = now + (0.27 if double else self._rng.uniform(2.2, 5.5))
        if now >= self._next_flick:
            self._flick_at = now
            self._next_flick = now + self._rng.uniform(4, 9)
        cheering = self._joy_at >= 0 and now - self._joy_at < 1.4
        cross = now < self._cross_until or (self._act_kind == "bat" and self.building)
        self._angry += (float(cross) - self._angry) * min(1.0, dt * (10 if cross else 2))
        shocked = 0 <= self._fail_t < FAIL_DROP   # (staring at what just happened)
        dancing = self._dance > 0.3   # (a sad Bun cheers up when something plays)
        target = 0.0 if self._hopeful or cheering or cross or shocked or dancing else self.sad
        rise = 5 if self._fail_t >= FAIL_DROP else 1.5   # the failure: ears drop at once
        self._sad += (target - self._sad) * min(1.0, dt * (8 if target < self._sad else rise))
        settling = self._rest_s() is not None and now >= self._rest_at
        if settling:   # nothing new starts; what's going on plays out (_calm)
            self._next_sigh = max(self._next_sigh, now + 1.0)
            self._next_beg = max(self._next_beg, now + 1.0)
            self._next_fidget = max(self._next_fidget, now + 1.0)
        if self._sad > 0.3 and now >= self._next_sigh:
            self._sigh_at = now
            self._next_sigh = now + self._rng.uniform(5, 9)
        if self.say and now >= self._say_until:
            self.say = ""
        asleep = self.asleep
        if asleep:   # Zs drift up and off to the side of his head, growing as they go
            self._sad = 0.0
            self._zzz_debt += 0.0 if settling else dt
            if self._zzz_debt >= ZZZ_EVERY:
                self._zzz_debt = 0.0
                r = self._bun_rect()
                self.zzz.append([r.left() + r.width() * 0.74, r.top() + r.height() * 0.24, 0.0])
        for z in self.zzz:   # (mostly sideways: there's more room beside him than above)
            z[2] += dt
            z[0] += dt * (17 + 7 * math.sin(z[2] * 3))
            z[1] -= dt * 9
        self.zzz = [z for z in self.zzz if z[2] < 2.4]
        if (not asleep and self.lines and self._sad > 0.3 and not self.say
                and now >= self._next_beg
                and not (0 <= now - self._sigh_at < 1.6)):
            self._beg_at = now
            self._say(self.lines, BEG)
            self._next_beg = now + BEG + self._rng.uniform(3, 6)
        self._step_fidget(now)
        self._spring(now, dt)
        if not self._still(now):
            self.update()
        if settling and self._calm(now):
            self._timer.stop()   # (this frame is the one he keeps)
            self.resting, self._still_at = True, now

    def _calm(self, now: float) -> bool:
        """Nothing on the go, so stopping here keeps a pose he could hold: no act,
        dance, line, hop, blink, flick, sigh, fidget or skit, nothing in the air, and
        the springy layer settled."""
        def going(at: float, secs: float) -> bool:
            return at >= 0 and now - at < secs
        return not (
            self.building or self._fail_t >= 0 or self._fin_t >= 0 or self._pop_t >= 0
            or self.groove is not None or self._dance > 0.01 or self._level > TALK
            or self._hopeful or self.say or self._angry > 0.05
            or self.notes or self.puffs or self.junk or self.sparks or self.zzz
            or self._fidget or self._skit is not None
            or going(self._blink_at, BLINK_SHUT + BLINK_HOLD + BLINK_OPEN)
            or going(self._flick_at, 0.5) or going(self._sigh_at, 1.6)
            or going(self._beg_at, BEG) or going(self._joy_at, 1.9)   # (+ the wobble)
            or going(self._kick_at, KICK_HOP) or abs(self._squash_s.v) > 0.05
            # sulking: he stops with his foot back down, between two kicks
            or (self.sulk and not self.asleep and sulk_kick(now - self._t0)[1] < 0.75))

    def _step_groove(self, now: float, dt: float) -> bool:
        """Dancing to the song (set_groove): fades the dance in or out, follows the
        song's style and throws notes on the beat. True while a song is playing."""
        g = self.groove
        if g is None or self.building or self._fail_t >= 0:
            self._dance -= self._dance * min(1.0, dt * DANCE_FADE)
            self._last_beat = None
            if self._dance < 0.01:
                self._style = ""
            return False
        on = bool(g.style) and bool(g.bpm)
        self._dance += (float(on) - self._dance) * min(1.0, dt * DANCE_FADE)
        self._g_energy += (g.energy - self._g_energy) * min(1.0, dt * 8)
        # the mouth: the voice as it's heard right now, opening at once and shutting a
        # touch slower
        at = getattr(g, "voice_at", None)
        v = at(now) if at is not None else g.voice
        self._g_voice += (v - self._g_voice) * min(1.0, dt * (90 if v > self._g_voice else 45))
        if not on:   # the first seconds, the style not settled yet: a hop on each bass hit
            age, s = g.last_hit("bass", now)
            if age < 0.1 and s > 0.5 and now - age - self._kick_at > 0.3:
                self._kick_at = now - age
                self._spawn(0.9)
            return True
        if g.style != self._style:
            self._style_was, self._style, self._blend = self._style, g.style, 0.0
        self._blend = min(1.0, self._blend + dt / STYLE_BLEND)
        bands = HIT_BAND.get(g.style)
        if bands:   # notes on the hits he moves to
            age, s = min(g.last_hit(b, now) for b in bands)
            if age < 0.1 and s > 0.45 and now - age - self._note_hit > 0.22:
                self._note_hit = now - age
                self._hit_notes(s)
            return True
        b = g.beat(now)
        if self._last_beat is not None and 0 < int(b) - int(self._last_beat) < 3:
            self._beat_notes(int(b))
        self._last_beat = b
        return True

    def _hit_notes(self, strength: float):
        style = self._style
        count = 1 + (strength > 0.85 and style == "electronic")
        if style == "hiphop" and self._rng.random() < 0.5:
            return   # (every 808 would be a flood)
        for _i in range(count):
            self._spawn({"electronic": 1.4, "rock": 1.2}.get(style, 0.8))

    def _beat_notes(self, n: int):
        """Beat `n` just landed: notes, as many and as lively as the song."""
        style, e = self._style, self._g_energy
        if style == "speech" or n % (2 if style in ("chill", "hiphop") else 1):
            return
        count = 1 + (style == "electronic" and e > 0.5) + (
            n % 4 == 0 and e > 0.55 and style in ("rock", "electronic", "pop"))
        strength = {"electronic": 1.4, "rock": 1.2, "hiphop": 0.8, "chill": 0.45}.get(style, 1.0)
        for _i in range(count):
            self._spawn(strength)
            if style == "chill":   # drifting up slow and long
                self.notes[-1].life *= 1.5
                self.notes[-1].vy *= 0.6

    def _moves(self, style: str, now: float, t: float) -> dict:
        """This moment of his dance to `style`, on the song's beat: how far each part
        moves (sizes are a share of his height, so a big Bun dances big)."""
        g, a = self.groove, self.bun_h
        e = 0.45 + 0.55 * self._g_energy
        b = g.beat(now) if g is not None and g.bpm else t * 2
        if style in ("hiphop", "chill") and g is not None and g.bpm > 115:
            b /= 2   # (heard at double time: a nod every other beat)
        ph = b % 1.0
        up = math.sin(math.pi * ph)                  # in the air between beats, down on them
        spb = 60 / g.bpm if g is not None and g.bpm else 0.5
        hit = hit_curve((ph if ph < 0.75 else ph - 1) * spb, 5 * spb)   # down on the beat
        side = math.sin(math.pi * b)                  # one way a beat, then the other
        slow = math.sin(math.pi * b / 2)              # one sway every two beats
        m = dict(dy=0.0, dx=0.0, angle=0.0, ears=0.0, sy=0.0, nod=0.0, dip=0.0,
                 mouth=0.0, blink=0.0, angry=0.0, smug=0.0)
        # (his mouth stays shut, his little smile, for music: only speech moves it)
        if style in HIT_BAND and g is not None:   # moving to the hits themselves
            hit, s = accent(g, HIT_BAND[style], now, 12.0 if style == "rock" else 5.0)
            hit *= (0.55 + 0.45 * s) / max(s, 1e-3)
        if style == "electronic":   # a hop a kick: up between them, down on the next one
            m.update(dy=-a * 0.07 * e * up, dx=a * 0.035 * slow, angle=5 * slow,
                     ears=-10 * up - 4, sy=0.025 * up, nod=-4 * slow, dip=2 * hit)
        elif style == "rock":       # headbanging: head down hard on each hit, ears flying
            m.update(dip=13 * hit * e, nod=5 * hit * (1 if int(t / 0.9) % 2 else -1),
                     dy=a * 0.03 * hit, sy=-0.05 * hit, ears=26 * hit - 4, angle=2 * side,
                     angry=0.35, blink=0.4 * hit)
        elif style == "hiphop":     # a cool nod on the 808; his face changes now and then
            face = int(t / 4.0) % 4   # every 4 s: cool, eyes shut vibing, cool, plain
            swap = 1.0 if t % 4.0 < 0.12 else 0.0   # (a blink covers the change)
            slow = math.sin(t * 1.7)  # (a lazy sway of its own: hip-hop tempos fool it)
            m.update(dip=6 * hit, nod=3 * hit - 3 - 3 * (face == 3), angle=-3 + 3 * slow,
                     dx=a * 0.03 * slow, dy=a * 0.012 * hit, ears=6 * slow - 6 * hit,
                     smug=float(face in (0, 2)), blink=max(swap, float(face == 1)))
        elif style == "chill":      # a slow sway, eyes shut, lost in it
            awake = 6 <= b % 16 < 8   # (now and then he opens them)
            m.update(angle=6 * slow, dx=a * 0.035 * slow, nod=5 * slow,
                     dy=-a * 0.012 * abs(slow), ears=8 * slow, blink=0.0 if awake else 1.0)
        elif style == "speech":     # talking along: his lips follow the voice
            onset = g.onset if g is not None else 0.0
            m.update(mouth=max(0.0, min(1.0, (self._g_voice - 0.3) * 1.7)),
                     nod=5 * math.sin(t * 1.7) + 3 * math.sin(t * 0.7), dip=2 * onset,
                     ears=-4 * min(1.0, self._g_voice * 2), dy=-a * 0.01 * onset,
                     angle=2 * math.sin(t * 0.9))
        else:                       # anything else: a bounce on the beat
            m.update(dy=-a * 0.06 * e * up, angle=4 * slow, dx=a * 0.025 * slow, dip=4 * hit,
                     ears=-8 * up)
        return m

    def dance(self, now: float, t: float) -> dict:
        """The dance this moment, blended from the last style while it changes and
        faded in and out with the song (all zeros when no song plays)."""
        d = self._dance
        m = self._moves(self._style, now, t)
        if self._blend < 1 and self._style_was:
            k = self._blend * self._blend * (3 - 2 * self._blend)
            was = self._moves(self._style_was, now, t)
            m = {key: was[key] + (m[key] - was[key]) * k for key in m}
        return {key: v * d for key, v in m.items()}

    def _spring(self, now: float, dt: float):
        """Moves the springy layer on a frame: his ears trail behind his hops and
        wobble as they settle, a fast move stretches him and a change of direction (a
        landing, a take-off) squashes him, then he jiggles back into shape."""
        pose = self.pose(now)
        if dt <= 0:
            return
        acted = self.act_phase() in ("dash", "cloud", "back") or self._pop_t >= 0
        vy = 0.0 if acted else (pose["dy"] - self._dy_last) / dt / self.bun_h
        self._dy_last = pose["dy"]
        dv = max(-4.0, min(4.0, vy - self._vy))   # (a jump cut can't fling him)
        self._vy = vy
        if not pose["shown"] or acted:   # the act squashes him by hand
            self._squash_s.x = self._squash_s.v = 0.0
        else:
            self._squash_s.v += SQUASH * dv * 10   # landing (dv < 0): squash
            self._squash_s.step(min(0.08, abs(vy) * STRETCH), dt, *SQUASH_SPRING)
            self._squash_s.x = max(-0.2, min(0.15, self._squash_s.x))
        self._ears_s.step(pose["ears"] - vy * EAR_DRAG, dt, *EAR_SPRING)

    def springy(self, pose: dict) -> dict:
        """`pose` with the springy layer on top (what paintEvent draws)."""
        s = self._squash_s.x
        if s > 0:   # stretched tall: never past the top of his box (his ears got cut)
            room = self._bun_rect().top() + pose["dy"] - 1 - self.bun_h * ROOM_TOP / H
            s = min(s, max(0.0, room / (self.bun_h * pose["sy"])))
        return {**pose, "ears": self._ears_s.x, "sy": pose["sy"] * (1 + s),
                "sx": pose["sx"] * (1 - 0.6 * s)}

    def _step_beats(self, now: float, dt: float):
        """The failure beat, the finished speaker, popping out, and what's flying."""
        r = self._bun_rect()
        if self._fail_t >= 0:
            before = self._fail_t
            self._fail_t += dt
            f = self._fail_t
            if self._fail_snap and before < FAIL_SNAP <= f:
                self._snap()
            if before < FAIL_DROP <= f:   # ears drop, a big sigh
                self._sigh_at = now
                self._next_sigh = now + self._rng.uniform(5, 9)
            if self._fail_snap and before < FAIL_POOF <= f:   # he puts the bits down
                c = self._at(r, 84, 104)
                for _i in range(9):
                    self._puff(c.x(), c.y(), 45, r.height() * 0.08, 0.6)
            if f >= FAIL_END:
                self._fail_t = -1.0
        if self._fin_t >= 0:
            self._fin_t += dt
            if self._fin_t < FINALE - 0.6 and self._rng.random() < dt * 5:   # it plays
                c = self._at(r, PLANK_SPOT.center().x(), 102)
                n = _Note(c.x(), c.y(), self._rng, 1.0, self.note_k())
                n.vx = self._rng.uniform(10, 40)
                self.notes.append(n)
            if self._fin_t >= FINALE:
                self._fin_t = -1.0
        if self._pop_t >= 0:
            self._pop_t += dt
            if self._pop_t >= POP:
                self._pop_t = -1.0
        g, floor = r.height() * 6.5, r.bottom() - 3
        for j in self.junk:
            j.age += dt
            j.vy += g * dt
            j.x += j.vx * dt
            j.y += j.vy * dt
            j.a += j.va * dt
            if j.y > floor:   # bounce on the floor, losing most of it
                j.y, j.vy, j.vx, j.va = floor, -j.vy * 0.3, j.vx * 0.5, j.va * 0.4
        self.junk = [j for j in self.junk if j.age < j.life]
        for k in self.sparks:
            k.age += dt
            k.vy += g * 0.5 * dt
            k.x += k.vx * dt
            k.y += k.vy * dt
        self.sparks = [k for k in self.sparks if k.age < k.life]

    def _idle(self, now: float) -> bool:
        return not (self.building or self._fail_t >= 0 or self._fin_t >= 0 or self.asleep
                    or self._sad > 0.5 or self._angry > 0.05 or self._level > TALK
                    or self._hopeful or self.celebrate or self.say or self._dance > 0.05
                    or (self._joy_at >= 0 and now - self._joy_at < 1.4))

    def _step_fidget(self, now: float):
        """Now and then a bored Bun fidgets or plays his theme's skit (never in the
        middle of anything else; anything else starting cuts a skit short)."""
        if self._fidget and now - self._fidget_at >= FIDGETS[self._fidget]:
            self._fidget = ""
        if self._skit is not None and (now - self._skit_at >= self._skit[0]
                                       or not self._idle(now)):
            self._skit, self._kit = None, None
        if now < self._next_fidget:
            return
        self._next_fidget = now + self._rng.uniform(*FIDGET_EVERY)
        if not self._fidget and self._skit is None and self._idle(now):
            if not self.robot and self._rng.random() < bunskits.NEXT_PROB:
                self.skit()
            else:
                self.fidget(self._rng.choice(tuple(FIDGETS)))

    def skit(self, name: str | None = None):
        """Start the skit of theme `name` (default: the current theme's; bunskits)."""
        self._fidget = ""
        self._skit, self._skit_at = bunskits.for_theme(name), time.monotonic()

    @property
    def skit_playing(self) -> bool:
        return self._skit is not None

    def _skit_frame(self, now: float) -> bunskits.Kit | None:
        """This frame of the skit playing (None: none, or it went wrong: then it stops,
        as nothing in a paint may raise)."""
        if self._skit is None:
            return None
        kit = bunskits.Kit()
        try:
            self._skit[1](kit, now - self._skit_at)
        except Exception:   # noqa: BLE001  (a drawing bug must never take the app down)
            log.exception("Bun's skit failed")
            self._skit = None
            return None
        return kit

    def _with_kit(self, out: dict, kit: bunskits.Kit) -> dict:
        """The pose `out` with the skit's frame on top."""
        k, u = kit.pose, self.bun_h / H
        out["dy"] += k.get("dy", 0.0) * u
        out["dx"] += k.get("dx", 0.0) * u
        for key in ("angle", "ears", "nod", "dip", "sx", "sy"):
            out[key] += k.get(key, 0.0)
        for key in ("mouth", "blink", "sad", "angry"):
            out[key] = max(out[key], k.get(key, 0.0))
        out["smug"] = out["smug"] or k.get("smug", 0.0) > 0.5
        out["alpha"] *= 1 - min(1.0, max(0.0, 1 - k.get("alpha", 1.0)))
        out["shown"] = out["shown"] and out["alpha"] > 0.02
        if kit.prop is not None:
            out["prop"] = kit.prop or None
        if kit.hide:
            out["outfit"] = tuple(n for n in bunnyfit.outfit() if n not in kit.hide)
        return out

    def _paint_kit(self, p: QPainter, rect: QRectF, items):
        """A skit's drawings, on the 100 x 120 canvas fitted to `rect`."""
        if not items:
            return
        p.save()
        p.translate(rect.left(), rect.top())
        s = rect.height() / H
        p.scale(s, s)
        try:
            for fn in items:
                fn(p)
        except Exception:   # noqa: BLE001  (see _skit_frame)
            log.exception("Bun's skit failed to draw")
            self._skit = None
        p.restore()

    def fidget(self, kind: str):
        """Start an idle fidget: "yawn", "look" (round) or "tap" (a foot, to the beat)."""
        self._fidget, self._fidget_at = kind, time.monotonic()

    def pose(self, now: float | None = None) -> dict:
        """Blink / mouth / ears / vertical offset for the current moment."""
        now = time.monotonic() if now is None else now
        t = now - self._t0
        blink = blink_amount(now - self._blink_at) if self._blink_at >= 0 else 0.0
        ears = 3 * math.sin(t * 1.3)
        if self._flick_at >= 0 and (f := now - self._flick_at) < 0.5:
            ears += 14 * math.sin(f / 0.5 * math.pi) * math.cos(f * 30) * (1 - f / 0.5)
        ears += self._mouth * 8 * math.sin(t * 11)
        dy = BOB_UP * math.sin(t * 2.2) * (1 - 0.5 * self._sad)
        ears += 8 * self._sad    # (the droop itself: draw_bunny folds them with `sad`)
        sx = sy = 1.0
        angle, alpha, look_dx = 0.0, 1.0, 0.0
        mouth = self._mouth
        # his head tilts, the way he looks at things: a slow curious lean, further
        # over when he's hoping, a little bob while he talks, and his eyes drift
        tilt = (3.5 * math.sin(t * 0.55) + 1.5 * math.sin(t * 1.3)) * (1 - self._sad)
        tilt -= 7 * self._sad
        tilt += 2.5 * self._mouth * math.sin(t * 4.2)
        if self.prop == "headphones":   # leaning into the cup he's listening with
            tilt += 5
        look = 0.25 * math.sin(t * 0.37)
        if self._sigh_at >= 0 and (s := now - self._sigh_at) < 1.6:
            b = math.sin(math.pi * s / 1.6) * self._sad
            dy += 4 * b
            sy -= 0.05 * b         # sagging with it
            ears += 10 * b
            blink = max(blink, 0.5 * b)
        if self._beg_at >= 0 and (g := now - self._beg_at) < BEG:
            b = math.sin(math.pi * g / BEG)   # perks up and bounces, hoping
            ears -= 10 * b * self._sad
            dy -= 4 * b * abs(math.sin(g * 9))
        if self._joy_at >= 0 and (j := now - self._joy_at) < 1.35:
            # three hops for joy, each lower, a squash on every landing; eyes shut
            # happy, mouth open in a grin
            hops = (0.17, 0.1, 0.05)
            if j < 1.2:
                n = int(j / 0.4)
                u = (j - 0.4 * n) / 0.4
                up = math.sin(u * math.pi)
                dy -= self.bun_h * hops[n] * up
                sy += 0.06 * up * hops[n] / hops[0]
                ears -= 12 * up
                tilt += (6 if n % 2 else -6) * up
            for i, land in enumerate((0.4, 0.8, 1.2)):
                if (d := abs(j - land)) < 0.1:
                    sy -= 0.16 * hops[i] / hops[0] * (1 - d / 0.1)
            sx += (1 - sy) * 0.8
            ears -= 8 * self._sad
            blink = max(blink, 1.0 if j < 1.25 else 0.0)
            mouth = max(mouth, 0.6 * min(1.0, (1.35 - j) / 0.2))
        if self._fidget and (f := now - self._fidget_at) < FIDGETS[self._fidget]:
            d = FIDGETS[self._fidget]
            env = math.sin(math.pi * f / d)
            if self._fidget == "yawn":   # opens wide, eyes screwed shut, a stretch
                o = max(0.0, min(1.0, f / 0.8, (d - 0.2 - f) / 0.6))
                o = o * o * (3 - 2 * o)
                mouth = max(mouth, 0.95 * o)
                blink = max(blink, min(1.0, 1.5 * o))
                sy += 0.05 * o
                dy -= 2 * o
                ears -= 10 * o
            elif self._fidget == "look":   # a look round: leans one way, then the other
                angle += 7 * math.sin(2 * math.pi * f / d) * env
                look_dx = 3 * math.sin(2 * math.pi * f / d) * env
                look += math.sin(2 * math.pi * f / d) * env
                tilt += 7 * math.sin(2 * math.pi * f / d + 0.4) * env
                ears += 6 * math.sin(2 * math.pi * f / d + 0.6) * env
                dy -= 1.5 * env
            else:   # "tap": a foot tap and a sway, to whatever's in his headphones
                beat = abs(math.sin(math.pi * f * 2.2))
                dy -= 2.2 * beat * env
                angle += 4 * math.sin(math.pi * f * 1.1) * env
                ears += 6 * math.sin(math.pi * f * 4.4) * env
        nod = dip = 0.0
        smug = cross = 0.0
        if self._dance > 0.01 and self._style:
            m = self.dance(now, t)
            dy += m["dy"]
            look_dx += m["dx"]
            angle += m["angle"]
            ears += m["ears"]
            sy += m["sy"]
            sx -= m["sy"] * 0.6
            nod, dip, smug, cross = m["nod"], m["dip"], m["smug"], m["angry"]
            tilt *= 1 - self._dance   # (the dance moves his head its own way)
            mouth = max(mouth, m["mouth"])
            blink = max(blink, m["blink"])
        if self.groove is not None and self._kick_at >= 0 and (
                k := now - self._kick_at) < KICK_HOP:   # a hop on a hit (no beat yet)
            dy -= self.bun_h * 0.05 * math.sin(math.pi * k / KICK_HOP)
        if self._hopeful:
            dy -= 6 * abs(math.sin(t * 5))
        if self.celebrate:
            dy -= 7 * abs(math.sin(t * 3.4))
        dy -= self._bounce * abs(math.sin(t * 9))
        dx, swing, shown, prop = look_dx, 0.0, True, self.prop
        phase = self.act_phase()
        led = 0.0
        if phase == "dash":      # crouches, then springs up and dives into the cloud,
            # stretching and shrinking into it (never past the edge of his own box)
            k = self._act_t / DASH_END
            if k < CROUCH:
                c = math.sin(k / CROUCH * math.pi / 2)
                sy, sx, angle = sy - 0.15 * c, sx + 0.1 * c, angle - 5 * c
                ears += 14 * c
            else:
                u = (k - CROUCH) / (1 - CROUCH)
                dy -= self.bun_h * 0.2 * math.sin(u * math.pi)
                sy, sx = sy * (1 + 0.2 * u) * (1 - 0.35 * u), sx * (1 - 0.45 * u)
                ears -= 25 * u
                alpha = max(0.0, 1 - max(0.0, u - 0.5) / 0.45)
            shown = alpha > 0.02
        elif phase == "cloud":
            shown = False
        elif phase == "back":    # pops out of the cloud with his tools, springy
            k = (self._act_t - CLOUD_END) / (BACK_END - CLOUD_END)
            sc = 1 - 0.45 * (1 - k) ** 2 + 0.14 * math.sin(k * math.pi) * (1 - k)
            sx, sy = sx * sc, sy * sc
            dy -= self.bun_h * 0.16 * math.sin(k * math.pi)
            ears -= 14 * math.sin(k * math.pi)
            alpha = 1.0   # (solid at once: small and springy is pop enough)
        elif phase == "hammer":
            swing = self._swing()
            dy += 1.5 * swing    # leans into each blow
            ears += 6 * swing
        elif phase == "bat":     # taps the bat on his paw, glaring
            swing = 0.18 * abs(math.sin((self._act_t - BACK_END) * 5))
            ears -= 8
        if self._pop_t >= 0:     # popped out of the cloud early (the act ended)
            k = self._pop_t / POP
            sc = 1 - 0.4 * (1 - k) ** 2 + 0.1 * math.sin(k * math.pi)
            sx, sy = sx * sc, sy * sc
        if (f := self._fail_t) >= 0:
            if self._fail_snap and f < FAIL_POOF:
                broken = f >= FAIL_SNAP
                prop = ("wrench" if self.robot else "hammer_broken" if broken else "hammer")
                if not broken:   # the blow comes down
                    s0 = self._fail_swing
                    swing = s0 + (1 - s0) * f / FAIL_SNAP
                else:            # ... and he lifts what's left to look at it
                    swing = 1 - 0.35 * min(1.0, (f - FAIL_SNAP) / 0.35)
            if FAIL_SNAP <= f < FAIL_DROP:   # frozen: ears up, mouth an "o", a tremble
                k = (f - FAIL_SNAP) / (FAIL_DROP - FAIL_SNAP)
                ears -= 12
                mouth = max(mouth, 0.35)
                dx += 1.4 * math.sin(t * 45) * (1 - k)
                if (j := f - FAIL_SNAP) < 0.3:   # a start
                    dy -= self.bun_h * 0.05 * math.sin(j / 0.3 * math.pi)
        if self.robot and (self.building or 0 <= self._fail_t < FAIL_SNAP):
            led = 0.5 + 0.5 * math.sin(t * 7)   # his LEDs pulse while he works
        if self._angry > 0.05 and phase in (None, "bat"):   # a cross little shake
            dx += 1.6 * self._angry * math.sin(t * 40)
        if self.asleep:   # eyes shut, slow deep breaths, a little snoring "o"
            blink = 1.0
            breath = math.sin(t * 1.3)
            dy = 1.8 * breath
            ears = 22 + 4 * breath
            mouth = 0.1 + 0.07 * max(0.0, breath)
            tilt, look = 8 + 1.5 * breath, 0.0   # his head lolls over to one side
        kick = 0.0
        if self.sulk and not self.asleep and phase is None:
            kick, u = sulk_kick(now - self._t0)
            angle -= 6 * kick                     # leaning into it
            dx -= 3 * kick
            dy += 2 * max(0.0, kick)
            ears += 10                             # ears down
            dip += 2.5                             # head hung
            blink = max(blink, 0.3)                # eyes on his feet
            look = 0.4 * kick
        out = {"blink": blink, "mouth": mouth, "ears": ears, "dy": dy, "kick": kick,
                "dx": dx, "swing": swing, "shown": shown, "sad": self._sad,
                "angry": self._angry, "sx": sx, "sy": sy, "angle": angle,
                "alpha": alpha, "led": led, "prop": prop, "nod": nod, "dip": dip,
                "tilt": tilt, "look": look,
                "smug": smug > 0.5, "intense": cross, "outfit": None}
        self._kit = self._skit_frame(now)
        return self._with_kit(out, self._kit) if self._kit is not None else out

    # ------------------------------------------------------------------ paint
    def _key(self, pose: dict, dpr: float) -> tuple:
        """What has to be the same for his kept picture to stand in for `pose`."""
        return (pose["shown"], pose["prop"], pose["smug"], pose["outfit"], self.asleep,
                self.robot, _steps(pose), self.bun_h, self.size(), dpr, theme.current_name,
                tuple(theme.T.items()))

    def _moved(self, a: dict, b: dict, dpr: float) -> float:
        """About how far (screen px) the bit of him that moved most moved from pose a
        to pose b (a colour change: always too far)."""
        if abs(a["alpha"] - b["alpha"]) > 0.5 / 255 or abs(a["led"] - b["led"]) > 0.5 / 255:
            return math.inf
        far = self.bun_h * 1.3   # (his ear tips, from his feet: the most a squash or lean moves)
        px = max(abs(a["dx"] - b["dx"]), abs(a["dy"] - b["dy"]),
                 far * abs(a["sx"] - b["sx"]), far * abs(a["sy"] - b["sy"]),
                 far * math.radians(abs(a["angle"] - b["angle"])))
        unit = self.bun_h / H
        for k, n in SWAY.items():
            px = max(px, unit * n * abs(_sway(a, k) - _sway(b, k)))
        return px * dpr

    def _held(self, pose: dict, dpr: float) -> dict:
        """`pose`, or the pose his kept picture shows while he's moved less than
        HOLD_PX from it (no skit on, nothing else about him changed); `dpr`: the
        screen's (or picture's) pixels per px."""
        kept = self._kept_pose
        if (HOLD and kept is not None and self._kit is None
                and self._kept_key == self._key(pose, dpr)
                and self._moved(kept, pose, dpr) < HOLD_PX):
            return kept
        return pose

    def _still(self, now: float) -> bool:
        """The next frame would look just like the last one: his kept picture still
        stands for him and nothing round him moves, so no repaint."""
        if (not HOLD or self._kept_pose is None
                or type(self).paintEvent is not BunnyWidget.paintEvent):   # (SetupShow)
            return False
        if (self.notes or self.puffs or self.zzz or self.junk or self.sparks
                or self.celebrate or self.building or self._fail_t >= 0 or self._fin_t >= 0
                or self._pop_t >= 0 or self.say != self._painted_say):
            return False
        pose = self.springy(self.pose(now))
        return self._held(pose, self.devicePixelRatioF()) is self._kept_pose

    def _picture(self, pose: dict, body: QRectF, dpr: float) -> QImage:
        """Him in `pose` on a see-through picture the size of the widget, at the
        screen's pixels: drawn once, then kept for the frames he hardly moves (_held)."""
        if pose is self._kept_pose and self._kept_img is not None:
            return self._kept_img
        size = QSize(math.ceil(self.width() * dpr), math.ceil(self.height() * dpr))
        img = self._kept_img
        if img is None or img.size() != size:
            img = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
            img.setDevicePixelRatio(dpr)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._draw_bun(p, pose, body)
        p.end()
        self._kept_img, self._kept_pose, self._kept_key = img, pose, self._key(pose, dpr)
        return img

    def _draw_bun(self, p: QPainter, pose: dict, body: QRectF):
        """Him (and what a skit puts in his paws) in `pose`, squashed, leaning and faded."""
        kit = self._kit
        p.save()
        foot = QPointF(body.center().x(), body.bottom())
        p.translate(foot)
        p.rotate(pose["angle"])
        p.scale(pose["sx"], pose["sy"])
        p.translate(-foot)
        p.setOpacity(pose["alpha"])
        draw_bunny(p, body, pose["prop"],
                   blink=pose["blink"], mouth=pose["mouth"], ears=pose["ears"],
                   swing=pose["swing"], sad=pose["sad"],
                   angry=max(pose["angry"], pose["intense"]),
                   nightcap=self.asleep, robot=self.robot, led=pose["led"],
                   nod=pose["nod"] + pose.get("tilt", 0.0), dip=pose["dip"],
                   smug=pose["smug"],
                   outfit=pose["outfit"], look=pose.get("look", 0.0),
                   kick=pose.get("kick", 0.0),
                   hold=None if kit is None else bunskits.held_paws(kit))
        if kit is not None:
            self._paint_kit(p, body, kit.front)
        p.restore()

    def paintEvent(self, ev):
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        now = self._still_at if self.resting else time.monotonic()   # (resting: as kept)
        dpr = p.deviceTransform().m11()   # (the screen's, or a grab's, pixels per px)
        pose = self.springy(self.pose(now))
        r = self._bun_rect()
        # soft shadow on the "floor", shrinking as he rises
        lift = max(0.0, -pose["dy"])
        shade = QColor(0, 0, 0, round(max(20, 70 - int(lift * 6)) * pose["alpha"]))
        sw = max(0.0, r.width() * (0.62 - lift * 0.012) * abs(pose["sx"]))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(shade)
        if pose["shown"]:
            p.drawEllipse(QRectF(r.center().x() + pose["dx"] - sw / 2, r.bottom() - 4, sw, 8))
        self._paint_puffs(p)
        phase = self.act_phase()
        if phase in ("cloud", "back"):   # (the cloud he pops out of is behind him)
            self._paint_scuffle(p)
        if self.celebrate:
            t = now - self._t0
            for i, col in enumerate(SPARKLE_COLORS):
                a = t * 0.8 + i * math.pi / 2
                tw = 0.5 + 0.5 * math.sin(t * 4 + i * 1.7)
                x = r.center().x() + math.cos(a) * (r.width() * 0.78)
                y = r.center().y() - 6 + math.sin(a) * (r.height() * 0.48)
                sparkle(p, x, y, 3 + 4 * tw, QColor(col))
        body = r.translated(pose["dx"], pose["dy"])
        kit = self._kit
        if kit is not None:
            self._paint_kit(p, r, kit.behind)
        self._paint_build(p, body, r, pose)
        if pose["shown"]:
            if HOLD and kit is None:   # (only he is kept: what's round him is this frame's)
                held = self._held(pose, dpr)
                p.drawImage(QPointF(0, 0), self._picture(
                    held, r.translated(held["dx"], held["dy"]), dpr))
            else:
                self._draw_bun(p, pose, body)
        if kit is not None:
            self._paint_kit(p, r, kit.world)
        self._paint_screen(p, body, pose)
        if phase == "dash":   # (the cloud he dives into is in front of him)
            self._paint_scuffle(p)
        self._paint_flying(p, r)
        if self.say and pose["shown"]:
            self._bubble(p, self.say, body)
        if self.zzz:
            f = QFont(self.font())
            f.setBold(True)
            col = QColor(theme.T["text_hi"])
            for x, y, age in self.zzz:
                k = age / 2.4
                f.setPixelSize(max(9, round(self.bun_h * (0.14 + 0.12 * k))))
                p.setFont(f)
                col.setAlphaF(min(1.0, age * 3) * (1 - k) ** 1.1 * 0.95)
                p.setPen(col)
                p.drawText(QPointF(x, y), "z" if k < 0.35 else "Z")
        for n in self.notes:
            paint_note(p, n)
        if kit is not None and kit.flash > 0:   # (Flashbang's skit)
            p.fillRect(self.rect(), QColor(255, 255, 255, round(215 * min(1.0, kit.flash))))
        p.end()
        self._painted_say = self.say

    def _speaker(self, p: QPainter, spot: QRectF, parts: int, at: float, thump: float = 0.0):
        """The little speaker he builds, `parts` of it, on the canvas (each part springs
        on a little bigger, then settles; `at` is the act time now)."""
        def pop(i: int) -> float:
            k = (at - self._part_at[i]) / 0.25
            if k >= 1 or self._part_at[i] < 0:
                return 1.0
            return 0.4 + 0.6 * k + 0.25 * math.sin(k * math.pi)

        def scaled(rect: QRectF, k: float) -> QRectF:
            c = rect.center()
            return QRectF(c.x() - rect.width() * k / 2, c.y() - rect.height() * k / 2,
                          rect.width() * k, rect.height() * k)

        if thump:   # thumping to the beat, from the floor up
            k = 1 + 0.08 * thump
            w, h = spot.width() * k, spot.height() * k
            spot = QRectF(spot.center().x() - w / 2, spot.bottom() - h, w, h)
        ink = QPen(INK, 1.6)
        ink.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(ink)
        p.setBrush(WOOD)
        frame = scaled(spot, pop(0))
        p.drawRoundedRect(frame, 2.5, 2.5)
        if parts >= 2:
            p.setBrush(CABINET)
            p.drawRoundedRect(scaled(spot.adjusted(2.2, 2.2, -2.2, -2.2), pop(1)), 2, 2)
        cx = spot.center().x()
        if parts >= 3:
            rr = spot.width() * 0.3 * pop(2)
            cy = spot.top() + spot.height() * 0.64
            p.setPen(QPen(INK, 1.2))
            p.setBrush(STEEL)
            p.drawEllipse(QPointF(cx, cy), rr, rr)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.T["accent"]))
            p.drawEllipse(QPointF(cx, cy), rr * 0.55, rr * 0.55)
        if parts >= 4:
            rr = spot.width() * 0.14 * pop(3)
            cy = spot.top() + spot.height() * 0.25
            p.setPen(QPen(INK, 1.2))
            p.setBrush(STEEL)
            p.drawEllipse(QPointF(cx, cy), rr, rr)
        elif parts:   # a work in progress: nails waiting
            p.setPen(QPen(WOOD_DARK, 1.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(frame.left() + 2.5, frame.top() + 2.5),
                       QPointF(frame.left() + 4.5, frame.top() + 4.5))

    def _canvas(self, p: QPainter, body: QRectF):
        """Switch the painter to the 100 x 120 canvas `body` is drawn on."""
        s = body.height() / H
        p.translate(body.left(), body.top())
        p.scale(s, s)

    def _paint_build(self, p: QPainter, body: QRectF, rest: QRectF, pose: dict):
        """What he's building, behind him: the speaker on his plank as the blows land,
        toppling off when it fails, and playing on the floor beside him once done."""
        if self.robot or not self._parts:
            return
        f = self._fail_t
        if self.act_phase() == "hammer" or (self._fail_snap and 0 <= f < FAIL_POOF):
            p.save()
            self._canvas(p, body)
            spot = QRectF(PLANK_SPOT)
            if f >= FAIL_SNAP:   # the plank snapped: over it goes
                k = min(1.0, (f - FAIL_SNAP) / 0.35)
                pivot = QPointF(spot.right(), spot.bottom())
                p.translate(pivot)
                p.rotate(80 * k * k)
                p.translate(-pivot)
                p.translate(0, 5 * k)
                p.setOpacity(max(0.0, 1 - (f - FAIL_SNAP) / (FAIL_POOF - FAIL_SNAP)))
            self._speaker(p, spot, self._parts, self._act_t if self.building else 1e9)
            p.restore()
        elif self._fin_t >= 0:
            e = self._fin_t
            p.save()
            self._canvas(p, rest)
            p.setOpacity(max(0.0, min(1.0, (FINALE - e) / 0.7)))
            spot = PLANK_SPOT.translated(2, 119 - PLANK_SPOT.bottom())
            self._speaker(p, spot, PARTS, 1e9, abs(math.sin(e * 9)))
            p.restore()

    def _paint_screen(self, p: QPainter, body: QRectF, pose: dict):
        """Robo-Bun's gadget screen: a bar lights up a blow (the last one when it
        worked), flashing red when it shorts out."""
        if not self.robot or pose["prop"] != "wrench":
            return
        p.save()
        self._canvas(p, body)
        p.setPen(Qt.PenStyle.NoPen)
        scr = GADGET_SCREEN.adjusted(3, 1.4, -1.4, -1.4)
        gap = 0.8
        bw = (scr.width() - gap * (SCREEN_BARS - 1)) / SCREEN_BARS
        if self._fail_t >= FAIL_SNAP:
            on = int(self._fail_t * 8) % 2 == 0
            col = QColor(FAIL_RED)
            col.setAlphaF(0.9 if on else 0.35)
            p.setBrush(col)
            p.drawRect(scr)
        else:
            for i in range(SCREEN_BARS):
                col = QColor(ROBOT_CYAN if i < self._parts else "#2c3446")
                if i == self._parts and self.building:   # the next one: blinking
                    col = QColor(ROBOT_CYAN)
                    col.setAlphaF(0.25 + 0.3 * (0.5 + 0.5 * math.sin(self._act_t * 10)))
                p.setBrush(col)
                p.drawRect(QRectF(scr.left() + i * (bw + gap), scr.top(), bw, scr.height()))
        if self.act_phase() == "hammer" and 0 <= self._act_t - self._flash_at < 0.12:
            sparkle(p, 104, 106, 7, ROBOT_CYAN_HI)   # the wrench hits the bolt
        p.restore()

    def _paint_flying(self, p: QPainter, r: QRectF):
        """Junk out of the cloud, the hammer's head, and sparks."""
        s = r.height() / H
        for j in self.junk:
            p.save()
            p.setOpacity(max(0.0, min(1.0, (j.life - j.age) / 0.35)))
            p.translate(j.x, j.y)
            p.rotate(j.a)
            p.scale(s, s)
            p.setPen(QPen(INK, 1.4))
            if j.kind == "head":
                p.setBrush(STEEL)
                p.drawRoundedRect(QRectF(-10, -5, 20, 10), 2.5, 2.5)
                p.setBrush(WOOD)
                p.drawRect(QRectF(-3, 5, 6, 3))   # the stub of handle still in it
            elif j.kind == "sock":
                path = QPainterPath(QPointF(-3, -9))
                path.lineTo(3, -9)
                path.lineTo(3, 2)
                path.quadTo(QPointF(10, 2), QPointF(10, 6))
                path.quadTo(QPointF(10, 9), QPointF(4, 9))
                path.lineTo(-1, 9)
                path.quadTo(QPointF(-3, 9), QPointF(-3, 6))
                path.closeSubpath()
                p.setBrush(PINK)   # (a light sock: it shows on every theme)
                p.drawPath(path)
                p.setPen(QPen(FUR, 2))
                p.drawLine(QPointF(-2, -6.5), QPointF(2, -6.5))
            elif j.kind == "carrot":
                path = QPainterPath(QPointF(-4, -6))
                path.lineTo(4, -6)
                path.lineTo(0, 10)
                path.closeSubpath()
                p.setBrush(QColor("#ff9a3c"))
                p.drawPath(path)
                p.setPen(QPen(QColor("#2fae5a"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(0, -6), QPointF(-3, -11))
                p.drawLine(QPointF(0, -6), QPointF(3, -11))
            elif j.kind == "spring":
                p.setPen(QPen(STEEL, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                path = QPainterPath(QPointF(-6, -8))
                for i in range(1, 7):
                    path.lineTo(6 if i % 2 else -6, -8 + i * 2.7)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(path)
            elif j.kind == "duck":
                p.setBrush(QColor("#ffd23f"))
                p.drawEllipse(QRectF(-8, -2, 15, 9))
                p.drawEllipse(QRectF(-1, -9, 8, 8))
                p.setBrush(QColor("#ff8a3c"))
                p.drawEllipse(QRectF(5.5, -6.5, 5, 3))
            else:   # a bit of plank
                p.setBrush(WOOD)
                p.drawRoundedRect(QRectF(-9, -2.5, 18, 5), 1.5, 1.5)
            p.restore()
        for k in self.sparks:
            col = QColor(k.col)
            col.setAlphaF(max(0.0, 1 - k.age / k.life))
            p.setPen(QPen(col, max(1.2, 1.8 * s), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(k.x, k.y), QPointF(k.x - k.vx * 0.035, k.y - k.vy * 0.035))

    def _bubble(self, p: QPainter, text: str, body: QRectF):
        """A comic speech bubble up and to the right of his head (Hoot's style)."""
        f = QFont(self.font())
        f.setPixelSize(max(9, round(self.bun_h * 0.13)))
        f.setBold(True)
        p.setFont(f)
        fm = p.fontMetrics()
        room = self.width() - 20
        lines = [text]
        if fm.horizontalAdvance(text) > room and " " in text:
            # a longer line goes on two, broken at the space nearest the middle
            spaces = [i for i, c in enumerate(text) if c == " "]
            cut = min(spaces, key=lambda i: abs(i - len(text) / 2))
            lines = [text[:cut], text[cut + 1:]]
        tw = max(fm.horizontalAdvance(t) for t in lines)
        if tw > room:
            return   # no room for the whole line: say nothing rather than half of it
        pad = 7
        bw, bh = tw + 2 * pad, fm.height() * len(lines) + 2 * pad - 4
        x = max(2.0, min(body.right() - body.width() * 0.05, self.width() - bw - 2))
        y = max(2.0, body.top() + body.height() * 0.05 - bh)
        box = QRectF(x, y, bw, bh)
        tail = QPainterPath(QPointF(box.left() + 10, box.bottom() - 2))
        tail.lineTo(body.center().x() + body.width() * 0.3, body.top() + body.height() * 0.38)
        tail.lineTo(box.left() + 22, box.bottom() - 2)
        shape = QPainterPath()
        shape.addRoundedRect(box, bh / 2, bh / 2)
        shape = shape.united(tail)
        p.setPen(QPen(INK, 1.6))
        p.setBrush(BUBBLE)
        p.drawPath(shape)
        p.setPen(INK)
        p.drawText(box.adjusted(pad, 0, -pad, 0), Qt.AlignmentFlag.AlignCenter,
                   "\n".join(lines))

    def _paint_puffs(self, p: QPainter):
        p.setPen(Qt.PenStyle.NoPen)
        for f in self.puffs:
            k = f.age / f.life
            p.setBrush(f.col)
            p.setOpacity(0.85 * (1 - k))
            rr = f.r * (0.6 + 0.8 * k)
            p.drawEllipse(QRectF(f.x - rr, f.y - rr, 2 * rr, 2 * rr))
        p.setOpacity(1.0)

    def _paint_scuffle(self, p: QPainter):
        """The cartoon dust-up while he rummages for his tools: a jiggling cloud he dives
        into, his ears popping up out of it, stars and bits of plank flying, and he
        pops back out of it with what he went for."""
        r = self._bun_rect()
        c = self._cloud_spot()
        cx, cy = c.x(), c.y()
        t = self._act_t
        u = r.height() / 110   # (sized to him)
        phase = self.act_phase()
        if phase == "dash":    # swells round him as he dives in
            k = (t / DASH_END - CROUCH) / (1 - CROUCH)
            grow = max(0.0, min(1.0, (k - 0.1) / 0.6))
            grow = grow * grow * (3 - 2 * grow)
        elif phase == "back":  # shrinks away as he comes out
            grow = max(0.0, 1 - (t - CLOUD_END) / (BACK_END - CLOUD_END) / 0.6)
        else:
            grow = 1.0
        if grow <= 0:
            return
        if phase == "cloud":   # his ears pop up out of the top now and then
            e = (t * 2.2) % 1.0
            if e < 0.45:
                up = math.sin(e / 0.45 * math.pi)
                for ex, tilt in ((-7, -12), (7, 14)):
                    p.save()
                    p.translate(cx + ex * u + 6 * u * math.sin(t * 5), cy - 18 * u)
                    p.rotate(tilt + 8 * math.sin(t * 13))
                    p.translate(0, -16 * u * up)
                    p.setPen(QPen(ROBOT_INK if self.robot else INK, 1.6))
                    p.setBrush(ROBOT_FUR if self.robot else look_colour("fur"))
                    p.drawEllipse(QRectF(-5 * u, -12 * u, 10 * u, 26 * u))
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(ROBOT_CYAN if self.robot else look_colour("inner"))
                    p.drawEllipse(QRectF(-2.4 * u, -8 * u, 4.8 * u, 18 * u))
                    p.restore()
        p.setPen(QPen(DUST_INK, 1.5))
        p.setBrush(DUST)
        for i in range(8):
            a = i * 2 * math.pi / 8 + t * 3
            rr = (16 + 4 * math.sin(t * 23 + i * 1.9)) * grow * u
            x = cx + math.cos(a) * 25 * grow * u
            y = cy + math.sin(a) * 14 * grow * u
            p.drawEllipse(QRectF(x - rr, y - rr, 2 * rr, 2 * rr))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(cx - 28 * grow * u, cy - 16 * grow * u, 56 * grow * u, 32 * grow * u))
        k = int(t * 9)   # a new spot every few frames
        for j in range(2):
            a = (k * 2.4 + j * math.pi) % (2 * math.pi)
            x, y = cx + math.cos(a) * 38 * grow * u, cy + math.sin(a) * 22 * grow * u
            if (k + j) % 2:
                sparkle(p, x, y, 6 * grow * u, QColor(SPARKLE_COLORS[(k + j) % 4]))
            else:
                p.save()
                p.translate(x, y)
                p.rotate(math.degrees(a))
                p.setPen(QPen(INK, 1.2))
                p.setBrush(WOOD)
                p.drawRoundedRect(QRectF(-9 * grow * u, -2.8 * grow * u, 18 * grow * u,
                                         5.6 * grow * u), 1.5, 1.5)
                p.restore()
