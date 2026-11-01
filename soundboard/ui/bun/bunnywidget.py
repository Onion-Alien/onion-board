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
him hop for joy (`joy_lines`) and emits `clicked`. Only Bun himself takes clicks (and
shows the hand): the room round him for notes and the bubble lets them through.

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
gives him another N seconds. In lite mode (ui/settings/lite.py) every Bun rests at once
(lite.REST_S, `_rest_s`) and sounds and the mic don't stir him: a still picture, which only
a click moves.

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
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen  # noqa: F401
from PySide6.QtWidgets import QSizePolicy, QWidget

from soundboard.ui.kit import theme
from soundboard.core import achievements, usage
from soundboard.ui.bun.bunny import (  # noqa: F401
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
from soundboard.ui.bun.bunbits import (  # noqa: F401
    accent, ANNOY_CLICKS, ANNOY_WINDOW, BACK_END, BACK_MS, BAT_POKES, BEG, blink_amount,
    BLINK_HOLD, BLINK_OPEN, BLINK_SHUT, BOB_UP, BUBBLE, CABINET, CLOUD_END, CROUCH, DANCE_FADE,
    DANCE_HOP, DASH_END, DOUBLE_BLINK, DUST, DUST_INK, EAR_DRAG, EAR_SPRING, FAIL_DROP,
    FAIL_END, FAIL_POOF, FAIL_RED, FAIL_SNAP, FAST_MS, FIDGET_EVERY, FIDGETS, FINALE,
    FIRST_FIDGET, FPS, GRUMPY_AT, HIT_BAND, hit_curve, HIT_LEAD, HOLD, HOLD_PX, JOY_HOPS,
    _Junk, KICK_HOP, LOUD, loudness, _luma, NAP_HOURS, _Note, NOTE_COLORS, note_colors,
    _note_cols, NOTE_H, paint_note, PARTS, POP, _Puff, RED_IN, SCREEN_BARS, SMOKE, SPARK,
    _Spark, SPARKLE_COLORS, _Spring, SQUASH, SQUASH_SPRING, _steps, STRETCH, STYLE_BLEND,
    SULK_EVERY, sulk_kick, SULK_SCUFF, SWAY, _sway, SWING, TALK, TAUNT, WOKEN_S, ZZZ_EVERY)
from soundboard.ui.bun.bunbuild import BunnyBuild
from soundboard.ui.bun.bundance import BunnyDance
from soundboard.ui.bun.bunpaint import BunnyPaint

log = logging.getLogger(__name__)


def local_hour() -> int:
    """The hour on this PC's clock (read here only, never sent anywhere)."""
    return time.localtime().tm_hour


class BunnyWidget(BunnyBuild, BunnyDance, BunnyPaint, QWidget):
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
            self.setMouseTracking(True)   # the hand only over him (mouseMoveEvent)
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
        self._face, self._face_until = 0, 0.0   # his dance face (DANCE_FACES), till when
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
        hat) at the top of his bob, or of his highest hop (a click's, a dance's): they
        reach ROOM_TOP above his canvas."""
        hop = max(JOY_HOPS[0] + 0.07 if self.joy_lines else 0.0,   # (+ his stretch: tall hats)
                  DANCE_HOP if self in BunnyWidget.dancers else 0.0)
        return max(0, math.ceil(self.bun_h * (ROOM_TOP / H + hop) + BOB_UP) - self.pad)

    # ------------------------------------------------------------------ inputs
    def set_level(self, level: float):
        """The live mic level, 0..1. Call it as often as you like (the wizard: 25/s)."""
        if lite.on():   # (a still picture: the mic doesn't move him)
            return
        self._level = max(float(level), self._level * 0.8)
        if self._level > TALK:
            self.stir()

    def note_k(self) -> float:
        """How big his notes are, against the usual: they grow and shrink with him."""
        return max(0.3, (self.bun_h / NOTE_H) ** 0.85)

    def set_groove(self, groove):
        """The song playing, as a groove.Groove (its beat and style), or None. He dances
        to it: on the beat, in the song's style (see `_moves`), notes flying on the beats.
        Not in lite mode: he holds still."""
        if lite.on():
            groove = None
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
            if lite.on():
                b.groove, b._level = None, 0.0   # (a still picture: no dancing, no talking)
            rest = b._rest_s()
            if rest is not None:
                b._rest_at = min(b._rest_at, now + rest) if lite.on() else now + rest
            if not lite.on() and b.resting:
                b.resting = False
                if b.isVisible() and (b.in_background or appstate.active()):
                    b._resume()

    def burst(self, n: int = 6):
        """Throw a handful of notes out at once (none in lite mode: a still picture)."""
        if lite.on():
            return
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

    def cheer(self, line: str = ""):
        """A happy hop, notes and a joyful line (what a click does), or `line`."""
        self._joy_at = time.monotonic()
        self.stir()   # (lite mode: the hop alone, no notes)
        self.burst(6)
        # his own lines for where he is, and his theme's character (mascotlines.py)
        self.say = line or mascotlines.pick(self._rng, self.joy_lines + mascotlines.bun(),
                                            self.say)
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

    def on_bun(self, pos) -> bool:
        """Is this widget point on Bun himself (ears and hat included), not the room round
        him?"""
        r = self._bun_rect()
        side, top = r.width() * 0.12, self.bun_h * ROOM_TOP / H + BOB_UP   # (droopy ears)
        return r.adjusted(-side, -top, side, BOB_UP).contains(QPointF(pos))

    def mouseMoveEvent(self, ev):
        if self.joy_lines:
            if self.on_bun(ev.position()):
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.unsetCursor()
        super().mouseMoveEvent(ev)

    def leaveEvent(self, ev):
        if self.joy_lines:
            self.unsetCursor()
        super().leaveEvent(ev)

    def mousePressEvent(self, ev):
        if not self.on_bun(ev.position()):
            ev.ignore()   # a click beside him: not his
            return
        if ev.button() == Qt.MouseButton.LeftButton:
            self.stir()
            achievements.bump("bun_clicks")   # (Petting Zoo)
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
            blows = int((self._act_t - BACK_END) / SWING)   # lands as k wraps to 0 (swing = 1)
            if blows > self._blows:   # just hit: something gets built
                self._blows = blows
                if self._parts < (SCREEN_BARS if self.robot else PARTS) - 1:
                    self._add_part()
                if self.robot:        # a spark shower off the bolt
                    self._flash_at = self._act_t
                    c = self._at(r, 98, 108)
                    for _i in range(6):
                        a = self._rng.uniform(math.pi * 1.1, math.pi * 1.9)
                        v = r.height() * self._rng.uniform(0.7, 1.4)
                        self.sparks.append(_Spark(c.x(), c.y(), math.cos(a) * v,
                                                  math.sin(a) * v, self._rng.uniform(0.25, 0.5)))
                    return
                x = r.left() + r.width() * 0.98    # where the hammer lands
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
        pose = self._spring(now, dt)
        if not self._still(now, pose):
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
            hops = JOY_HOPS
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

    def _still(self, now: float, pose: dict | None = None) -> bool:
        """The next frame would look just like the last one: his kept picture still
        stands for him and nothing round him moves, so no repaint. `pose`: his pose at
        `now` before the springy layer, when the caller already has it (_spring's)."""
        if (not HOLD or self._kept_pose is None
                or type(self).paintEvent is not BunnyWidget.paintEvent):   # (SetupShow)
            return False
        if (self.notes or self.puffs or self.zzz or self.junk or self.sparks
                or self.celebrate or self.building or self._fail_t >= 0 or self._fin_t >= 0
                or self._pop_t >= 0 or self.say != self._painted_say):
            return False
        pose = self.springy(self.pose(now) if pose is None else pose)
        return self._held(pose, self.devicePixelRatioF()) is self._kept_pose

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
        if self.say and pose["shown"]:   # (on top: nothing flies over his words)
            self._bubble(p, self.say, body)
        if kit is not None and kit.flash > 0:   # (Flashbang's skit)
            p.fillRect(self.rect(), QColor(255, 255, 255, round(215 * min(1.0, kit.flash))))
        p.end()
        self._painted_say = self.say

