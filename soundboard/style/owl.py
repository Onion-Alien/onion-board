"""Hoot, Onion Watch's mascot: a cartoon owl (owls keep watch), drawn with QPainter
in the same style as Bun, so it's crisp at any size and needs no image files. He
wears Bun's theme outfit (_fit, bunnyfit.py; docs/MASCOT.md).
His looks are in owllooks.py and his drawing in owldraw.py; this file is him alive
(OwlWidget) and re-exports both, so `owl.<name>` works for every name.

Part of the style kit (see __init__.py): Onion Watch draws him from its copy of
this file, and Onion Board's Triggers tab shows him until the add-on is installed.

    owl_image(160)             # QImage, transparent background
    OwlWidget(96, lines=...)   # Hoot alive: waiting, begging, sulking
"""
from __future__ import annotations

import math
import random
import time
import weakref

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import appstate, hooks, mascotlines
from .appstate import snap_to_pixels
from .hooks import _

# Hoot's looks and drawing live in owllooks.py / owldraw.py, re-exported here so
# `owl.<name>` keeps working for both apps
from .owllooks import (BEAK, BEAK_DARK, BELLY, BELLY_MARK, BUBBLE, CHEEK,  # noqa: F401
                       EYE, EYE_LOW, EYE_RING, EYE_Y, EYES, FACE, FEATHER,
                       FEATHER_DARK, H, INK, look, LOOKS, MARKS, MOUTH,
                       SPARKLE_COLORS, TEAR, TUFTS, VANILLA, W)
from .owldraw import (_arc, _belly_marks, _e, _face_path, _fit, _heart, _K,  # noqa: F401
                      _mix, _shade, _stroke, _tuft, _wing, BELLY_SPOTS,
                      body_path, draw_owl, EYES_AT, HEAD, NECK_AT,
                      NOT_ON_OWL, owl_image, OWN_PLACE, sparkle)

FPS = 30
FAST_MS = 1000 // FPS
NEAR = 2.2           # the mouse this close (owl heights from his face): he perks up
REST_PEEK_MS = 250   # resting: how often he checks for the mouse coming near
# His picture is kept between frames (OwlWidget._held) until some part of him has moved
# HOLD_PX screen pixels: his sway moves far less than a pixel a frame, and redrawing him
# is most of a frame's cost. False: every frame draws him fresh (the tests compare).
HOLD = True
HOLD_PX = 0.25
# how far the furthest bit of him moves for one unit of each pose key, in canvas units
# (100 x 120; tufts: per degree)
SWAY = {"look": 8.0, "look_y": 8.0, "blink": 24.0, "sad": 30.0, "tufts": 0.6,
        "clasp": 40.0, "flap": 40.0, "plead": 20.0, "tear": 40.0, "beak": 15.0}
EXTRAS = ("puff", "ask", "zzz", "startle", "joy", "sleep")   # drawn round him, fresh every frame
# his bed (OwlWidget sleeps=True): headboard, pillow, blanket and its polka dots
BED_WOOD = QColor("#b07a58")
BED_WOOD_DARK = QColor("#8a5a40")
PILLOW = QColor("#fffaf0")
BLANKET = QColor("#8f7cf0")
BLANKET_DOT = QColor("#c9bfff")
SHEET = QColor("#fdf8ee")
SLEEP_Z = QColor("#e6ddff")
WAKE_S = 0.9   # seconds his jolt awake takes



# ---------------------------------------------------------------------- alive
def wait_lines() -> tuple[str, ...]:
    """What he says while he begs, in the language picked (a function: the kit can be
    imported before the language is)."""
    return (_("pleeease?"), _("just one picture?"), _("I'll watch anything…"),
            _("hoo? hoo…?"), _("so… bored…"), _("my turn yet?"))


def joy_lines() -> tuple[str, ...]:
    """What he shouts when he's clicked."""
    return (_("yay!! ↓ down there!"), _("hoo-ray!"), _("let's watch something!"))


# the little acts he does while he waits, and how long each lasts (seconds)
ACTS = {"sigh": 1.8, "plead": 3.0, "tear": 2.6, "peek": 2.2, "doze": 5.0}


def _bell(k: float) -> float:
    """0 → 1 → 0 over k = 0..1, with soft ends."""
    return math.sin(math.pi * max(0.0, min(1.0, k)))


def _soft(k: float) -> float:
    """0 → 1 → 0 over k = 0..1, starting and stopping still (a move eases in and out)."""
    return _bell(k) ** 2


# the springy layer over the pose (OwlWidget._spring): stiffness (1/s²), damping (1/s)
TUFT_SPRING = (420.0, 16.0)    # ear tufts trail his moves and wobble as they settle
WING_SPRING = (600.0, 28.0)    # wings trail too, a little stiffer (they flap)
SQUASH_SPRING = (300.0, 15.0)  # his body jiggles back after a squash or stretch
TUFT_DRAG = 8.0    # how far his tufts trail behind, degrees per owl-height a second
WING_DRAG = 0.3    # how far his wings trail behind (flap), per owl-height a second
STRETCH = 0.03     # how tall and thin a fast move makes him, per owl-height a second
SQUASH = 0.3       # how hard a change of direction (a landing) squashes him
ACT_OUT = 0.35     # seconds an act cut short (the mouse, a click, a song) takes to go


class _Spring:
    """A damped spring chasing a target: the lag, overshoot and wobble that make a
    move look alive instead of on rails (Bun's, in Onion Board's bunnywidget.py)."""
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


# dancing (set_groove): the styles he bobs to the hits themselves, not the beat grid
HIT_BANDS = {"hiphop": ("bass",), "rock": ("bass", "drums")}
HIT_LEAD = 0.1    # seconds a bob starts before its hit, so it lands right on it
# (three frames at his 30 fps: a shorter run-in jumped)
STYLE_BLEND = 0.6  # seconds to change from one style of dance to another


def _hit(age: float, decay: float = 6.0) -> float:
    """A hit `age` seconds ago (less than 0: still coming): down to 1 right on it,
    then easing back."""
    if age < -HIT_LEAD or age > 2:
        return 0.0
    if age < 0:   # speeding down, still moving when it lands (a thud, not a stop)
        k = 1 + age / HIT_LEAD
        return k * k * (2 - k)
    return math.exp(-age * decay)


def _ease(k: float) -> float:
    k = max(0.0, min(1.0, k))
    return k * k * (3 - 2 * k)


class OwlWidget(QWidget):
    """Hoot, alive and waiting: he sways, blinks and glances down at the buttons
    below, sighs, begs with his wings clasped and big shiny eyes, sheds a tear,
    peeks, dozes off and jolts awake. Bring the mouse near and he perks up and
    follows it with his eyes; click him and he hops for joy.

    `lines` are what he says when he begs, `joy` what he shouts when clicked
    (default: wait_lines() / joy_lines()).
    `left` / `right` are the room beside him, px (default: plenty both sides, for
    the speech bubble up to his right and the zzz). The timer only runs while he's
    on screen.

    `rest_after_s=N`: with nothing going on he only moves for N seconds after he's
    shown, then finishes what he's doing and holds still (the timer stops, the last
    pose stays). The mouse coming near (looked at 4 times a second, nothing drawn),
    a click, something playing or showing him again sets him off again.

    `sleeps=True`: he starts asleep in a little bed, breathing, z's floating up. A
    click wakes him (a jolt, the bed goes) and he's his waiting self until he's
    hidden (his tab left), when he goes back to bed."""

    clicked = Signal()
    # the ones made with dances=True: the host hands each one on screen what's playing
    dancers: weakref.WeakSet = weakref.WeakSet()

    def __init__(self, height: int = 96, lines=None, joy=None, parent=None, *,
                 left: int | None = None, right: int | None = None, dances: bool = False,
                 rest_after_s: float | None = None, sleeps: bool = False):
        super().__init__(parent)
        # sleeps: he starts asleep in his bed, z's floating up; a click wakes him and
        # he idles, until he's hidden (the tab left) and goes back to bed
        self.sleeps = sleeps
        self.asleep = sleeps
        self._bed = 1.0 if sleeps else 0.0   # 0..1, how much of his bed shows
        self._wake_t = -1.0        # seconds since he was woken, or -1
        self.rest_after_s = rest_after_s
        self.resting = False       # holding still: the timer's off until a stir
        self._rest_t = self._rest_s() or 0.0   # (his own time, `t`) settles down from then
        if dances:
            OwlWidget.dancers.add(self)
        self.groove = None         # what's playing (set_groove): he dances to it
        self._dance = 0.0          # 0..1, how far into the dance (fades in and out)
        self.owl_h = height
        self.lines = tuple(wait_lines() if lines is None else lines)
        self.joy_lines = tuple(joy_lines() if joy is None else joy)
        side = round(height * 1.45)
        self.left = side if left is None else left
        self.right = side if right is None else right
        self.top = round(height * 0.34)    # room above for "?" and z's
        # the room beside him gives way first when space is short (the bubble then
        # overlaps him a little)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(_("Hoot is waiting for something to watch"))
        self._rng = random.Random()
        self._t0 = self._last = time.monotonic()
        self.t = 0.0
        self.act: str | None = None
        self._act_t = 0.0
        self._next_act = self._rng.uniform(2.0, 3.5)
        self._next_blink = self._rng.uniform(1.0, 3.0)
        self._blink_t = -1.0
        self._near = 0.0           # 0..1, how close the mouse is (smoothed)
        self._joy_t = -1.0         # seconds since he was clicked, or -1
        self.say = ""              # the speech bubble's text
        self._say_until = 0.0      # when a click's line goes (self.t), or 0
        self._look = [0.0, 0.7]    # pupils, smoothed
        self._glance = (0.0, 0.7)  # where he looks when left alone
        self._next_glance = 1.5
        self._was: tuple[str, float] | None = None   # an act cut short, fading out:
        self._was_w = 0.0                            # (act, how far in), 1..0
        self._g_last = None        # the groove he's still fading out of
        self._style = self._style_was = ""
        self._blend = 1.0          # 0..1 from the last style of dance to this one
        self._tufts_s = _Spring()  # the springy layer (_spring): tufts,
        self._wing_s = _Spring()   # ... wings,
        self._squash_s = _Spring()  # ... squash and stretch
        self._sprung = False       # (the springs start where the pose is)
        self._dy_last = 0.0
        self._vy = 0.0
        self._kept_img: QImage | None = None   # his picture (_picture), kept while he's
        self._kept_pose: dict | None = None    # ... this close to the pose it shows (_held)
        self._kept_key: tuple = ()
        self._painted_say = ""     # the bubble the last frame showed
        self._timer = QTimer(self)
        self._timer.setInterval(FAST_MS)
        self._timer.timeout.connect(self._tick)
        # resting: is the mouse coming near? (no repaints)
        self._peek = QTimer(self)
        self._peek.setInterval(REST_PEEK_MS)
        self._peek.timeout.connect(self._peek_mouse)
        appstate.pause_in_background(self, self._resume, self._pause)

    def sizeHint(self) -> QSize:
        return QSize(round(self.owl_h * W / H) + self.left + self.right,
                     self.owl_h + self.top + 8)

    def minimumSizeHint(self) -> QSize:
        return QSize(round(self.owl_h * W / H) + 8, self.owl_h + self.top + 8)

    def showEvent(self, ev):
        rest = self._rest_s()
        if rest is not None:   # shown again: another rest_after_s to move
            self.resting = False
            self._peek.stop()
            self._rest_t = self.t + rest
        if appstate.active():   # behind a game it waits until the app is back in front
            self._resume()
        super().showEvent(ev)

    def _resume(self):
        if self.resting:   # (back in front: still, until the mouse or a sound stirs him)
            self._peek.start()
            return
        self._last = time.monotonic()
        self._timer.start(FAST_MS)

    def _pause(self):
        self._timer.stop()
        self._peek.stop()

    def hideEvent(self, ev):
        if self.sleeps and not ev.spontaneous():   # (his tab left, not the app minimised)
            self.fall_asleep()
        self._pause()
        self._kept_img = self._kept_pose = None
        super().hideEvent(ev)

    def stir(self):
        """Something happened (the mouse came near, a click, a sound): with
        `rest_after_s` he moves again and keeps moving for another rest_after_s."""
        rest = self._rest_s()
        if rest is None:
            return
        self._rest_t = self.t + rest
        if self.resting:
            self.resting = False
            self._peek.stop()
            if self.isVisible() and appstate.active():
                self._resume()

    def _rest_s(self) -> float | None:
        """How long he moves after a stir (None: always): rest_after_s, or none at all
        while the app wants still mascots (hooks.still: lite mode)."""
        return 0.0 if hooks.still() else self.rest_after_s

    def _peek_mouse(self):
        if hooks.still():   # (a still picture: the mouse doesn't stir him)
            return
        m = self._mouse()
        if m and math.hypot(*m) < NEAR:
            self.stir()

    def _calm(self) -> bool:
        """Nothing on the go, so stopping here keeps a pose he could hold: no act,
        line, hop, blink or dance, the mouse away, his eyes and the springy layer
        settled."""
        return not (
            self.act or self._was is not None or self._joy_t >= 0 or self.say
            or self.groove is not None or self._dance > 0.01 or self._near > 0.02
            or (self._blink_t >= 0 and self.t - self._blink_t < 0.2)
            or abs(self._look[0] - self._glance[0]) > 0.01
            or abs(self._look[1] - self._glance[1]) > 0.01
            or abs(self._squash_s.v) > 0.05 or abs(self._tufts_s.v) > 0.5
            or abs(self._wing_s.v) > 0.05
            or 0.01 < self._bed < 0.99 or self._wake_t >= 0)

    def wake(self):
        """Asleep: he jolts awake, his bed goes, and he waits like always."""
        if not self.asleep:
            return
        self.asleep = False
        self._wake_t = 0.0
        self.say = ""
        self._next_act = self.t + self._rng.uniform(3.5, 7.0)
        self._next_blink = self.t + self._rng.uniform(1.5, 3.0)
        self.stir()

    def fall_asleep(self):
        """Back to bed (sleeps=True), as he was at the start."""
        self.asleep = True
        self._bed = 1.0
        self._wake_t = self._joy_t = -1.0
        self.act = self._was = None
        self.say = ""
        self._kept_img = self._kept_pose = None

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            if self.asleep:
                self.wake()
            else:
                self.cheer()
            self.clicked.emit()
        super().mousePressEvent(ev)

    def set_groove(self, groove):
        """What's playing, as a soundboard.audio.groove.Groove (its beat, style and hits), or
        None. He bobs his head to it (not while he's a still picture: hooks.still)."""
        if hooks.still():
            groove = None
        self.groove = groove
        if groove is not None:
            self.stir()

    @staticmethod
    def _accent(g, now: float) -> float:
        """0..1, how far into a bob this moment: on the song's hits (hip-hop, rock) or
        its beat (`g`: the groove)."""
        bands = HIT_BANDS.get(g.style)
        if bands:
            best = 0.0
            for band in bands:
                age, s = g.last_hit(band, now)
                until, s2 = g.next_hit(band, now)
                best = max(best, _hit(age) * s, _hit(-until) * s2)
            return best
        # the beat that went and the one coming, whichever is further in (one curve:
        # never a jump from one to the next), easing back over about a beat
        ph, beat = g.beat(now) % 1.0, 60 / g.bpm
        return max(_hit(ph * beat, 4 / beat), _hit((ph - 1) * beat, 4 / beat))

    def cheer(self):
        """A happy hop with sparkles (what a click does)."""
        self._joy_t = 0.0
        self.stir()
        self._stop_act()
        # his own lines for where he is, and his theme's character (mascotlines.py)
        self.say = (mascotlines.pick(self._rng, self.joy_lines + mascotlines.hoot(), self.say)
                    if self.joy_lines else "")
        self._say_until = self.t + mascotlines.read_secs(self.say)

    # ------------------------------------------------------------------ time
    def _owl_rect(self) -> QRectF:
        w = self.owl_h * W / H
        spare, room = self.width() - w, self.left + self.right   # shared as asked
        x = spare * self.left / room if room else spare / 2
        return QRectF(x, self.height() - self.owl_h - 4, w, self.owl_h)

    def _tick(self):
        now = time.monotonic()
        self.step(min(0.1, now - self._last))
        self._last = now
        if not self._still():   # (30 fps: a slower idle pace made the sway judder)
            self.update()
        if (self._rest_s() is not None and (self.t >= self._rest_t or hooks.still())
                and self._calm()):
            self._timer.stop()   # (this frame is the one he keeps)
            self.resting = True
            self._peek.start()

    def _mouse(self) -> tuple[float, float] | None:
        """The cursor relative to his face, in owl heights, if it's in this window."""
        win = self.window()
        g = QCursor.pos()
        if win is None or not win.frameGeometry().contains(g):
            return None
        pos = self.mapFromGlobal(g)
        r = self._owl_rect()
        return ((pos.x() - r.center().x()) / self.owl_h,
                (pos.y() - (r.top() + r.height() * 0.45)) / self.owl_h)

    def step(self, dt: float, mouse=...):
        """Advance the animation by `dt` seconds (`mouse` overrides the cursor, tests)."""
        self.t += dt
        g = self.groove
        on = g is not None and bool(g.style) and bool(g.bpm)
        if g is not None and on:
            self._g_last = g
            if g.style != self._style:
                self._style_was, self._style, self._blend = self._style, g.style, 0.0
        self._blend = min(1.0, self._blend + dt / STYLE_BLEND)
        self._dance += (float(on) - self._dance) * min(1.0, dt * 3)
        if self._dance < 0.01 and not on:
            self._g_last, self._style = None, ""
        if self._dance > 0.3 and self.act:   # (no sulking while he dances)
            self._stop_act()
        if self._was is not None:
            self._was_w -= dt / ACT_OUT
            if self._was_w <= 0:
                self._was = None
        m = self._mouse() if mouse is ... else mouse
        dist = math.hypot(*m) if m else 99.0
        near = 1.0 if dist < NEAR and not hooks.still() else 0.0
        if near:   # (asleep: only a click wakes him, but the z's keep floating)
            self.stir()
        if self.asleep:
            near = 0.0
        if self._wake_t >= 0:
            self._wake_t += dt
            if self._wake_t > WAKE_S:
                self._wake_t = -1.0
        self._bed += (float(self.asleep) - self._bed) * min(1.0, dt * 5)
        if self._bed < 0.01 and not self.asleep:
            self._bed = 0.0
        settling = self._rest_s() is not None and (self.t >= self._rest_t or hooks.still())
        self._near += (near - self._near) * min(1.0, dt * (5 if near else 1.5))
        if self._joy_t >= 0:
            self._joy_t += dt
            if self._joy_t > 1.6:
                self._joy_t = -1.0
                if self.t >= self._say_until:
                    self.say = ""
        elif self.say and not self.act and 0 < self._say_until <= self.t:
            self._say_until = 0.0   # a longer line from a click stays until it's read
            self.say = ""
        if self.act:
            self._act_t += dt
            if self._act_t >= ACTS[self.act]:
                self.act = None
                self.say = ""
                self._next_act = self.t + self._rng.uniform(3.5, 7.0)
            elif self._near > 0.6:
                self._stop_act()
        elif settling:   # nothing new starts; what's going on plays out (_calm)
            self._next_act = max(self._next_act, self.t + 1.0)
        elif (not self.asleep and self._joy_t < 0 and self._near < 0.3
              and self.t >= self._next_act
              and self._dance < 0.3):
            self.start(self._rng.choice(list(ACTS)))
        if settling:
            self._next_blink = max(self._next_blink, self.t + 1.0)
            self._next_glance = max(self._next_glance, self.t + 1.0)
        if self.t >= self._next_blink:
            self._blink_t = self.t
            self._next_blink = self.t + self._rng.uniform(2.0, 5.0)
        if self.t >= self._next_glance:   # mostly down at the buttons, now and then at you
            self._glance = self._rng.choice(((0.0, 0.8), (0.0, 0.8), (-0.3, 0.6), (0.3, 0.7),
                                             (0.0, -0.2), (-0.7, 0.2), (0.6, 0.1)))
            self._next_glance = self.t + self._rng.uniform(1.2, 3.0)
        if m and self._near > 0.2:
            tx, ty = max(-1.0, min(1.0, m[0] * 1.6)), max(-1.0, min(1.0, m[1] * 1.6))
        else:
            tx, ty = self._glance
        if self.act == "peek":
            tx, ty = 0.5, 1.0
        k = min(1.0, dt * 8)
        self._look[0] += (tx - self._look[0]) * k
        self._look[1] += (ty - self._look[1]) * k
        self._spring(dt)

    def start(self, act: str):
        """Begin one of ACTS now."""
        self.act, self._act_t = act, 0.0
        self.say = self._rng.choice(self.lines) if act == "plead" and self.lines else ""

    def _stop_act(self):
        """Cut the act short: it fades out over ACT_OUT instead of snapping off."""
        if self.act:
            self._was, self._was_w = (self.act, self._act_t / ACTS[self.act]), 1.0
            self._next_act = self.t + self._rng.uniform(3.5, 7.0)
        self.act = None
        self.say = ""

    @staticmethod
    def _act(a: str, k: float, t: float) -> dict:
        """What act `a`, `k` 0..1 of the way through, does to the pose: moves to add
        (dy, rot, tufts), floors to raise (blink, sad, clasp, plead), the tear and the
        extras paintEvent draws. Every move starts and ends still."""
        o: dict = {}
        if a == "sigh":        # sinks, eyes half shut, a puff of breath
            b = _soft(k)
            o.update(dy=5 * b, tufts=14 * b, blink=0.45 * b, puff=k)
        elif a == "plead":     # wings clasped, puppy eyes, hopeful little hops
            e = _ease(k / 0.15) * _ease((1 - k) / 0.15)
            o.update(clasp=e, plead=e, sad=0.9 * e, tufts=-10 * e, beak=0.45 * e,
                     dy=-4 * e * abs(math.sin(k * math.pi * 6)))
        elif a == "tear":
            o.update(tear=k, sad=_ease(k / 0.12) * _ease((1 - k) / 0.12),
                     blink=0.25 * _soft(k))
        elif a == "peek":      # leans over to look down at the buttons
            b = _soft(k)
            o.update(rot=9 * b, ask=b)
        elif a == "doze":      # nods off... and jolts awake
            if k < 0.78:
                d, w, j = _ease(k / 0.3), 1.0, -1.0
            else:              # the doze falls away fast as he jolts
                j = (k - 0.78) / 0.22
                d, w = 1.0, 1 - _ease(j / 0.1)
            o.update(blink=0.9 * d * w, dy=3 * d * w,
                     rot=(-4 * d + 1.5 * math.sin(t * 1.5) * d) * w)
            if k < 0.78:
                o["zzz"] = k
            if j >= 0:
                o["dy"] -= 9 * _soft(min(1.0, j * 1.5))
                o["tufts"] = -25 * _soft(j)
                o["startle"] = j
        return o

    def _dance_style(self, style: str, bob: float) -> tuple[float, float]:
        """(flap, blink) a style of dance adds: wings on a big hit for rock and
        electronic, eyes shut for chill."""
        return (0.7 * bob if style in ("rock", "electronic") else 0.0,
                1.0 if style == "chill" else 0.0)

    def base_pose(self) -> dict:
        """The pose this moment before the springy layer (see pose())."""
        t, near = self.t, self._near
        if self.asleep:   # tucked in: breathing slow, tufts down, head tipped
            br = math.sin(t * 1.7)
            return {"look": 0.0, "look_y": 0.3, "blink": 1.0, "sad": 0.0,
                    "tufts": 18 + 3 * br, "clasp": 0.0, "flap": 0.0, "plead": 0.0,
                    "tear": 0.0, "beak": 0.0, "dy": 1.6 * br,
                    "rot": -4 + 1.2 * math.sin(t * 0.6), "sleep": t}
        sad = 0.85 * (1 - near)
        tufts = 24 * sad - 10 * near + 3 * math.sin(t * 1.1)
        dy = -1.2 * math.sin(t * 2.0) - 4 * near * abs(math.sin(t * 5)) * 0.5
        rot = 2.5 * math.sin(t * 0.8)
        blink = 0.0
        if self._blink_t >= 0 and (b := t - self._blink_t) < 0.18:
            blink = _soft(b / 0.18)
        clasp = flap = plead = tear = beak = 0.0
        extra = {}
        acts = []
        if self.act:
            acts.append((self._act(self.act, self._act_t / ACTS[self.act], t), 1.0))
        if self._was is not None:
            a, k = self._was
            o = self._act(a, k, t)
            if "tear" in o:    # a tear cut short drops off his cheek
                o["tear"] = k + (1 - k) * (1 - self._was_w)
            acts.append((o, _ease(self._was_w)))
        for o, w in acts:
            dy += o.get("dy", 0.0) * w
            rot += o.get("rot", 0.0) * w
            tufts += o.get("tufts", 0.0) * w
            blink = max(blink, o.get("blink", 0.0) * w)
            sad = max(sad, o.get("sad", 0.0) * w)
            clasp = max(clasp, o.get("clasp", 0.0) * w)
            plead = max(plead, o.get("plead", 0.0) * w)
            beak = max(beak, o.get("beak", 0.0) * w)
            if "tear" in o:
                tear = o["tear"]
            for key in ("puff", "zzz", "startle"):
                if key in o:
                    extra[key], extra[key + "_a"] = o[key], w
            if "ask" in o:
                extra["ask"] = o["ask"] * w
        d = self._dance
        g = self.groove if self.groove is not None else self._g_last
        if d > 0.01 and g is not None and g.bpm:
            # dancing: head bobbing down on the hits, swaying a beat each way, tufts
            # bouncing, a flap of the wings on a big hit; cheered right up
            now = time.monotonic()
            bob = self._accent(g, now)
            sway = math.sin(math.pi * g.beat(now))
            sad *= 1 - d
            tufts += d * (-14 + 5 * bob)   # (the springs add the bounce)
            dy += d * 9 * bob
            rot += d * 7 * sway
            f, b = self._dance_style(self._style, bob)
            if self._blend < 1:   # changing style: blended, never a jump
                k = _ease(self._blend)
                f0, b0 = self._dance_style(self._style_was, bob)
                f, b = f0 + (f - f0) * k, b0 + (b - b0) * k
            flap = max(flap, d * f)
            blink = max(blink, d * b)
            beak = max(beak, d * 0.5 * bob)
        if self._joy_t >= 0:
            j = self._joy_t / 1.6
            e = _bell(j)
            sad, tufts = sad * (1 - e), tufts - 30 * e
            flap = abs(math.sin(self._joy_t * 14)) * e
            dy -= 16 * abs(math.sin(j * math.pi * 2)) * (1 - j)
            blink *= 1 - _ease(j / 0.08)
            plead = max(plead, 0.6 * e)
            beak = max(beak, e)
            extra["joy"] = j
        if self._wake_t >= 0:   # woken: a jump, tufts straight up, a "!"
            j = self._wake_t / WAKE_S
            e = _soft(min(1.0, j * 1.4))
            dy -= 12 * e
            tufts -= 28 * e
            sad *= 1 - _bell(j)
            beak = max(beak, 0.5 * e)
            extra["startle"], extra["startle_a"] = j, 1.0
        return {"look": self._look[0], "look_y": self._look[1], "blink": blink, "sad": sad,
                "tufts": tufts, "clasp": clasp, "flap": flap, "plead": plead, "tear": tear,
                "beak": beak,
                "dy": dy, "rot": rot, **extra}

    def _spring(self, dt: float):
        """Moves the springy layer on a frame: his tufts and wings trail behind his
        hops and wobble as they settle, a fast move stretches him and a change of
        direction (a landing, a take-off) squashes him, then he jiggles back."""
        if dt <= 0:
            return
        pose = self.base_pose()
        if not self._sprung:   # first frame: start where he is, no fling
            self._sprung = True
            self._tufts_s.x, self._wing_s.x, self._dy_last = pose["tufts"], pose["flap"], pose["dy"]
        vy = (pose["dy"] - self._dy_last) / dt / max(1, self.owl_h)
        self._dy_last = pose["dy"]
        dv = max(-4.0, min(4.0, vy - self._vy))   # (a jump cut can't fling him)
        self._vy = vy
        # landing (dv < 0): squash; softer on every bob of a dance (not a jelly)
        self._squash_s.v += SQUASH * (1 - 0.7 * self._dance) * dv * 10
        self._squash_s.step(min(0.08, abs(vy) * STRETCH), dt, *SQUASH_SPRING)
        self._squash_s.x = max(-0.2, min(0.15, self._squash_s.x))
        self._tufts_s.step(pose["tufts"] - vy * TUFT_DRAG, dt, *TUFT_SPRING)
        self._wing_s.step(pose["flap"] + vy * WING_DRAG, dt, *WING_SPRING)

    def pose(self) -> dict:
        """Everything draw_owl and the extras need for this moment: base_pose() with
        the springy layer on top (tufts and wings trailing, `sx` / `sy` squash)."""
        pose = self.base_pose()
        if not self._sprung:
            return {**pose, "sx": 1.0, "sy": 1.0}
        s = self._squash_s.x
        return {**pose, "tufts": self._tufts_s.x, "sx": 1 - 0.6 * s, "sy": 1 + s,
                "flap": max(-0.2, min(1.3, self._wing_s.x))}

    # ------------------------------------------------------------------ paint
    def _key(self, pose: dict, dpr: float) -> tuple:
        """What has to be the same for his kept picture to stand in for `pose`: where
        draw_owl switches a part on or off (shut eyes, a lid, the open beak, puppy
        eyes, tears), his size, the theme."""
        return (pose["blink"] > 0.6, pose["blink"] > 0.01,
                pose["flap"] > 0.3 or pose["beak"] > 0.3, pose["plead"] > 0.05,
                pose["sad"] > 0.05, 0 < pose["tear"] < 1, self.owl_h, self.size(), dpr,
                hooks.theme_name(), tuple(hooks.palette().items()))

    def _moved(self, a: dict, b: dict, dpr: float) -> float:
        """About how far (screen px) the bit of him that moved most moved from pose a
        to pose b."""
        far = self.owl_h * 1.2   # (his tufts, from his feet: the most a squash or sway moves)
        px = max(abs(a["dy"] - b["dy"]), far * abs(a["sx"] - b["sx"]),
                 far * abs(a["sy"] - b["sy"]), far * math.radians(abs(a["rot"] - b["rot"])))
        unit = self.owl_h / H
        for k, n in SWAY.items():
            px = max(px, unit * n * abs(a[k] - b[k]))
        return px * dpr

    def _held(self, pose: dict, dpr: float) -> dict:
        """`pose`, or the pose his kept picture shows while he's moved less than
        HOLD_PX from it; `dpr`: the screen's (or picture's) pixels per px."""
        kept = self._kept_pose
        if (HOLD and kept is not None and self._kept_key == self._key(pose, dpr)
                and self._moved(kept, pose, dpr) < HOLD_PX):
            return kept
        return pose

    def _still(self) -> bool:
        """The next frame would look just like the last one: his kept picture still
        stands for him and nothing round him moves, so no repaint."""
        if not HOLD or self._kept_pose is None or self.say != self._painted_say:
            return False
        pose = self.pose()
        return (not any(k in pose for k in EXTRAS)
                and self._held(pose, self.devicePixelRatioF()) is self._kept_pose)

    def _picture(self, pose: dict, r: QRectF, dpr: float) -> QImage:
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
        self._draw_owl(p, pose, r)
        p.end()
        self._kept_img, self._kept_pose, self._kept_key = img, pose, self._key(pose, dpr)
        return img

    def _draw_owl(self, p: QPainter, pose: dict, r: QRectF):
        """Him in `pose`, swaying and squashed about his feet."""
        p.save()
        foot = QPointF(r.center().x(), r.bottom())
        p.translate(foot)
        p.rotate(pose["rot"])
        p.scale(pose["sx"], pose["sy"])   # squash and stretch, about his feet
        p.translate(-foot)
        draw_owl(p, r.translated(0, pose["dy"]), pose["look"], look_y=pose["look_y"],
                 blink=pose["blink"], sad=pose["sad"], tufts=pose["tufts"],
                 clasp=pose["clasp"], flap=pose["flap"], plead=pose["plead"],
                 tear=pose["tear"], beak=pose["beak"])
        p.restore()

    def paintEvent(self, ev):
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pose = self.pose()
        dpr = p.deviceTransform().m11()   # (the screen's, or a grab's, pixels per px)
        r = self._owl_rect()
        u = self.owl_h / H     # one canvas unit, px
        # a soft shadow on the floor, shrinking as he rises
        lift = max(0.0, -pose["dy"])
        sw = r.width() * (0.6 - lift * 0.01)
        bed = self._bed
        if bed > 0:
            self._bed_back(p, r, bed)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, round(max(18, 60 - int(lift * 4)) * (1 - bed))))
        p.drawEllipse(QRectF(r.center().x() - sw / 2, r.bottom() - 3, sw, 7))
        if HOLD:   # (only he is kept: what's round him is this frame's)
            p.drawImage(QPointF(0, 0), self._picture(self._held(pose, dpr), r, dpr))
        else:
            self._draw_owl(p, pose, r)
        if bed > 0:
            self._bed_front(p, r, bed)
        body = r.translated(0, pose["dy"])
        head = QPointF(body.center().x(), body.top() + 18 * u)
        if "sleep" in pose:
            self._sleep_z(p, pose["sleep"], head, u)
        if "puff" in pose:
            k = pose["puff"]
            if 0.25 < k < 0.95:
                q = (k - 0.25) / 0.7
                p.setOpacity(0.7 * (1 - q) * pose.get("puff_a", 1.0))
                p.setBrush(QColor("#d9d2e6"))
                for i in range(3):
                    rr = (3 + 5 * q + i) * u
                    x = body.center().x() + (8 + 30 * q + i * 6) * u
                    y = body.top() + (70 - 8 * q - i * 3) * u
                    p.drawEllipse(QPointF(x, y), rr, rr * 0.8)
                p.setOpacity(1.0)
        if pose.get("ask", 0) > 0.05:
            self._text(p, "?", head.x() + 30 * u, body.top() - 2 * u, 22 * u * pose["ask"],
                       QColor(SPARKLE_COLORS[0]))
        if "zzz" in pose:
            for i in range(3):
                q = (pose["zzz"] * 2.2 - i * 0.35) % 1.3
                if q < 1:
                    p.setOpacity(_bell(q) * pose.get("zzz_a", 1.0))
                    self._text(p, "z", head.x() + (26 + 16 * q + i * 4) * u,
                               head.y() - (8 + 34 * q) * u, (10 + 6 * q) * u,
                               QColor(SPARKLE_COLORS[3]))
            p.setOpacity(1.0)
        if "startle" in pose:
            p.setOpacity(pose.get("startle_a", 1.0))
            self._text(p, "!", head.x() + 28 * u, body.top() + 4 * u,
                       22 * u * _bell(pose["startle"]), QColor(SPARKLE_COLORS[1]))
            p.setOpacity(1.0)
        if "joy" in pose:
            j = pose["joy"]
            for i, col in enumerate(SPARKLE_COLORS * 2):
                a = i * math.pi / 4 + j * 2
                d = (40 + 30 * j) * u
                p.setOpacity(1 - j)
                sparkle(p, head.x() + math.cos(a) * d, head.y() + 10 * u + math.sin(a) * d * 0.8,
                        (4 + 3 * math.sin(j * 9 + i)) * u, QColor(col))
            p.setOpacity(1.0)
        if self.say:
            self._bubble(p, self.say, body)
        p.end()
        self._painted_say = self.say

    def _bed_frame(self, p: QPainter, r: QRectF, bed: float) -> float:
        """Set up for drawing his bed: faded and sunk as it goes; returns one canvas
        unit, px."""
        u = self.owl_h / H
        p.setOpacity(bed)
        p.translate(r.center().x(), r.top() + 14 * u * (1 - bed))
        pen = QPen(INK, 2.4 * u)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        return u

    def _bed_back(self, p: QPainter, r: QRectF, bed: float):
        """The headboard, its two round-topped posts and the pillow, behind him (in
        canvas units from the middle of his top)."""
        p.save()
        u = self._bed_frame(p, r, bed)
        board = QPainterPath()
        board.addRoundedRect(QRectF(-50 * u, 44 * u, 100 * u, (H - 40) * u), 22 * u, 22 * u)
        p.setBrush(BED_WOOD)
        p.drawPath(board)
        for sx in (-1, 1):
            post = QPainterPath()
            post.addRoundedRect(QRectF(sx * 52 * u - 5 * u, 40 * u, 10 * u, (H - 36) * u),
                                5 * u, 5 * u)
            p.setBrush(BED_WOOD_DARK)
            p.drawPath(post)
            p.setBrush(BED_WOOD)
            p.drawEllipse(QPointF(sx * 52 * u, 37 * u), 6.5 * u, 6.5 * u)
        p.setBrush(PILLOW)
        p.drawRoundedRect(QRectF(-42 * u, 56 * u, 84 * u, 26 * u), 13 * u, 13 * u)
        p.restore()

    def _bed_front(self, p: QPainter, r: QRectF, bed: float):
        """The blanket tucked up to his belly, a sheet folded over its top, polka dots."""
        p.save()
        u = self._bed_frame(p, r, bed)
        top, bottom = 90 * u, (H + 2) * u
        blanket = QPainterPath()
        blanket.addRoundedRect(QRectF(-56 * u, top, 112 * u, bottom - top), 10 * u, 10 * u)
        p.setBrush(BLANKET)
        p.drawPath(blanket)
        p.save()
        p.setClipPath(blanket)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(BLANKET_DOT)
        for i, x in enumerate(range(-46, 50, 13)):
            p.drawEllipse(QPointF(x * u, (110 + 5 * (i % 2)) * u), 2.6 * u, 2.6 * u)
        p.restore()
        p.setBrush(SHEET)
        p.drawRoundedRect(QRectF(-58 * u, top - 3 * u, 116 * u, 11 * u), 5.5 * u, 5.5 * u)
        p.restore()

    def _sleep_z(self, p: QPainter, t: float, head: QPointF, u: float):
        """Three fat z's drifting up and away from his head, growing as they go, each
        fading in and out in turn (there's always one or two in the air)."""
        f = QFont(self.font())
        f.setBold(True)
        for i in range(3):
            q = (t * 0.42 + i / 3) % 1.0
            px = (12 + 11 * q) * u
            if px < 1:
                continue
            f.setPixelSize(max(1, round(px)))
            path = QPainterPath()
            path.addText(QPointF(head.x() + (22 + 24 * q + 4 * math.sin(q * 6.3)) * u,
                                 head.y() - (4 + 42 * q) * u), f, "z")
            p.setOpacity(_bell(q) ** 0.5)
            p.setPen(QPen(INK, 1.3 * u))
            p.setBrush(SLEEP_Z)
            p.drawPath(path)
        p.setOpacity(1.0)

    def _text(self, p: QPainter, text: str, x: float, y: float, px: float, col: QColor):
        if px < 1:
            return
        f = QFont(self.font())
        f.setBold(True)
        f.setPixelSize(max(1, round(px)))
        p.setFont(f)
        p.setPen(col)
        p.drawText(QPointF(x, y), text)

    def _bubble(self, p: QPainter, text: str, body: QRectF):
        """A comic speech bubble up and to the right of his head, tail to his beak."""
        f = QFont(self.font())
        f.setPixelSize(max(9, round(self.owl_h * 0.12)))
        f.setBold(True)
        p.setFont(f)
        fm = p.fontMetrics()
        room = self.width() - 20
        lines = [text]
        if fm.horizontalAdvance(text) > room and " " in text:
            # a longer translation goes on two lines, broken at the space nearest the
            # middle
            spaces = [i for i, c in enumerate(text) if c == " "]
            cut = min(spaces, key=lambda i: abs(i - len(text) / 2))
            lines = [text[:cut], text[cut + 1:]]
        tw = max(fm.horizontalAdvance(t) for t in lines)
        if tw > room:
            return   # no room for the whole line: say nothing rather than half of it
        pad = 7
        bw, bh = tw + 2 * pad, fm.height() * len(lines) + 2 * pad - 4
        x = max(2.0, min(body.right() + 2, self.width() - bw - 2))
        y = max(2.0, body.top() - bh * 0.35)
        box = QRectF(x, y, bw, bh)
        tail = QPainterPath(QPointF(box.left() + 10, box.bottom() - 2))
        tail.lineTo(body.center().x() + body.width() * 0.34, body.top() + body.height() * 0.27)
        tail.lineTo(box.left() + 22, box.bottom() - 2)
        shape = QPainterPath()
        radius = (fm.height() + 2 * pad - 4) / 2   # one line's: two lines aren't a pill
        shape.addRoundedRect(box, radius, radius)
        shape = shape.united(tail)
        p.setPen(QPen(INK, 1.6))
        p.setBrush(BUBBLE)
        p.drawPath(shape)
        p.setPen(INK)
        p.drawText(box.adjusted(pad, 0, -pad, 0), Qt.AlignmentFlag.AlignCenter, "\n".join(lines))
