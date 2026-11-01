"""Bun dancing to what's playing (`set_groove`) and the springy layer over his pose
(`_spring`, `springy`). Part of `BunnyWidget` (ui/bun/bunnywidget.py)."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWidget

from soundboard.ui.bun.bunny import H, PLANK_SPOT, ROOM_TOP
from soundboard.ui.bun.bunbits import (
    accent, DANCE_FACES, DANCE_FADE, EAR_DRAG, EAR_SPRING, FACE_HOLD, FAIL_DROP, FAIL_END,
    FAIL_POOF, FAIL_SNAP, FINALE, HIT_BAND, hit_curve, _Note, POP, SQUASH, SQUASH_SPRING,
    STRETCH, STYLE_BLEND, TALK_FADE)

if TYPE_CHECKING:
    from typing import Any

    _Base = QWidget
else:
    _Base = object


class BunnyDance(_Base):
    if TYPE_CHECKING:   # what BunnyWidget has that these use
        _at: Any
        _blend: Any
        _bun_rect: Any
        _dance: Any
        _dy_last: Any
        _ears_s: Any
        _fail_snap: Any
        _face: Any
        _face_until: Any
        _fail_t: Any
        _fin_t: Any
        _g_energy: Any
        _g_voice: Any
        _kick_at: Any
        _last_beat: Any
        _next_sigh: Any
        _note_hit: Any
        _pop_t: Any
        _puff: Any
        _rng: Any
        _sigh_at: Any
        _snap: Any
        _spawn: Any
        _squash_s: Any
        _style: Any
        _style_was: Any
        _vy: Any
        act_phase: Any
        building: Any
        bun_h: Any
        groove: Any
        junk: Any
        note_k: Any
        notes: Any
        pose: Any
        sparks: Any

    def _step_groove(self, now: float, dt: float) -> bool:
        """Dancing to the song (set_groove): fades the dance in or out, follows the
        song's style and throws notes on the beat. True while a song is playing."""
        g = self.groove
        if g is None or self.building or self._fail_t >= 0:
            fade = TALK_FADE if self._style == "speech" else DANCE_FADE   # (mouth shut)
            self._dance -= self._dance * min(1.0, dt * fade)
            self._last_beat = None
            if self._dance < 0.01:
                self._style = ""
            return False
        # not a song (a soundbite, someone talking): he says it along with it, no notes
        talk = getattr(g, "music", None) is False
        style = "speech" if talk else g.style
        on = talk or (bool(style) and bool(g.bpm))
        if now >= self._face_until:   # time for a new face (maybe the same one again)
            self._face = self._rng.randrange(len(DANCE_FACES))
            self._face_until = now + self._rng.triangular(*FACE_HOLD)
        fade = TALK_FADE if talk else DANCE_FADE   # (a one-second "bruh" is said at once)
        self._dance += (float(on) - self._dance) * min(1.0, dt * fade)
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
        if style != self._style:
            self._style_was, self._style, self._blend = self._style, style, 0.0
        self._blend = min(1.0, self._blend + dt / STYLE_BLEND)
        if talk:
            return True
        bands = HIT_BAND.get(style)
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
        # (his mouth doesn't move to music, only to speech: bouncing, he wears one of his
        # happy faces, DANCE_FACES)
        blink, grin = DANCE_FACES[self._face]
        if style in HIT_BAND and g is not None:   # moving to the hits themselves
            hit, s = accent(g, HIT_BAND[style], now, 12.0 if style == "rock" else 5.0)
            hit *= (0.55 + 0.45 * s) / max(s, 1e-3)
        if style == "electronic":   # a hop a kick: up between them, down on the next one
            m.update(dy=-a * 0.07 * e * up, dx=a * 0.035 * slow, angle=5 * slow,
                     ears=-10 * up - 4, sy=0.025 * up, nod=-4 * slow, dip=2 * hit,
                     blink=blink, mouth=grin)
        elif style == "rock":       # headbanging: head down hard on each hit, ears flying
            m.update(dip=13 * hit * e, nod=5 * hit * (1 if int(t / 0.9) % 2 else -1),
                     dy=a * 0.03 * hit, sy=-0.05 * hit, ears=26 * hit - 4, angle=2 * side,
                     angry=0.35, blink=0.4 * hit)
        elif style == "hiphop":     # a cool nod on the 808; his face changes now and then
            face = int(t / 4.0) % 4   # every 4 s: cool, eyes shut vibing, cool, plain
            swap = 1.0 if t % 4.0 < 0.12 else 0.0   # (a blink covers the change)
            slow = math.sin(t * 1.7)  # (a lazy sway of its own: hip-hop tempos fool it)
            # a nod on each beat too, as far as the beat is sure (an 808 alone, a few
            # a bar, left him all but still). The beat's nod is smooth, down on it and
            # up between, and the 808s only add a little (less the surer the beat):
            # snapping down on the beat and again on every bass note looked like
            # headbanging.
            sure = min(1.0, max(0.0, (getattr(g, "confidence", 0.0) - 0.35) / 0.3))
            hit = max(0.55 * (1 - 0.6 * sure) * hit, 0.75 * sure * math.cos(math.pi * ph) ** 2)
            m.update(dip=9 * hit, nod=4 * hit - 3 - 3 * (face == 3), angle=-3 + 3 * slow,
                     dx=a * 0.03 * slow, dy=a * 0.015 * hit, ears=6 * slow - 5 * hit,
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
                     ears=-8 * up, blink=blink, mouth=grin)
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

    def _spring(self, now: float, dt: float) -> dict:
        """Moves the springy layer on a frame: his ears trail behind his hops and
        wobble as they settle, a fast move stretches him and a change of direction (a
        landing, a take-off) squashes him, then he jiggles back into shape. Returns the
        pose it read (pose(now), without the springs), so _still needn't work it out again."""
        pose = self.pose(now)
        if dt <= 0:
            return pose
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
        return pose

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
