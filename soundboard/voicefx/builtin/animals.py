"""Cat and Dog: every syllable you say comes out as a meow or a bark."""
from __future__ import annotations

import numpy as np
from soundboard.audio.dsp import butter
from soundboard.voicefx import Effect, Param, critters, register

from soundboard.voicefx.builtin.parts import F32, _Filter, _PitchTracker


def _formants(f: np.ndarray, peaks: np.ndarray) -> np.ndarray:
    """Levels of the harmonics at `f` (Hz) through a mouth with `peaks` (rows of
    centre Hz, width Hz, gain): resonance curves added up, the highs rolling off."""
    c, w, g = peaks[:, 0, None], peaks[:, 1, None], peaks[:, 2, None]
    res = (g / (1 + ((f[None] - c) / (0.5 * w)) ** 2)).sum(0)
    return (res + 0.02) / np.sqrt(1 + f / 4000)


class _Critter(Effect):
    """An animal that says your syllables. Your voice is only listened to, like the
    Singing monk's: a new syllable (sound after quiet, or loudness rising out of a
    dip) starts a call, its loudness sets the call's, and how far your pitch is
    above or below your usual one moves the call's pitch the same way, so a
    question still goes up.

    The calls are real recordings (voicefx.critters, downloaded the first time the
    voice is used): each one plays to its end unless a new syllable comes after
    HOLD_S, and while you keep talking the next follows straight on. Until they're
    in (or offline) the call is made up: a buzz (harmonics summed, like the monk's)
    shaped by a moving mouth (`MOUTHS`), plus a little breath noise; a subclass says
    what that one does in `_call(since, loud, rel, dt)`: its pitch in semitones from
    the animal's own note, its loudness (0..1 of yours), and where its mouth is (a
    row of `MOUTHS`, blended between rows)."""

    params = (Param("note", "Pitch", -12, 12, 0, " st", 1, ("lower", "higher")),
              Param("follow", "Follow my tune", 0, 1, 0.7, "", 0, ("one note", "my tune")),
              Param("mix", "Mix", 0, 1, 1))

    BASE_HZ = 500.0
    MOUTHS: np.ndarray = np.zeros((1, 1, 3), F32)   # [row][peak] = (Hz, width Hz, gain)
    BREATH = 0.05          # breath noise, of the call's loudness
    BREATH_BAND = (2000, 7000)
    TOP_HZ = 9000.0        # no harmonics above
    VIB_HZ, VIB_DEPTH = 6.0, 0.012
    GATE = 0.004           # quieter than this (about -48 dBFS) is not talking
    MOST = 0.2             # the loudest it follows you (shouting, about -14 dBFS)
    GAP_S = 0.12           # the shortest syllable
    MOUTH_S = 0.015        # the mouth moves from row to row this slowly
    HOLD_S = 0.3           # a recorded call plays at least this long before the next
    SETTLE_S = 0.04        # your pitch isn't read this soon into a syllable
    TUNE_S = 0.15          # a recorded call's pitch follows your tune this long, then holds
    SWAP_S = 0.015         # a call cut short fades out this fast
    FOLLOW_ST = 7.0        # the most your tune moves a recorded call (semitones)

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        rate = rate or 48000
        self.tracker = _PitchTracker(rate)
        self.filled = 0
        self.home = 0.0        # your usual pitch (semitones), learnt as you talk
        self.heard = 0
        self.rel = 0.0         # where your pitch is now against it (semitones)
        self.level = 0.0       # your loudness, smoothed
        self.peak = self.dip = 0.0
        self.since = 1e9       # seconds since this call started (huge: none yet)
        self.talking = False
        self.phase = self.vib = 0.0
        self.f = 0.0           # the call's pitch now (Hz)
        self.amp = 0.0
        self.mouth = 0.0
        self.amps = None       # last block's harmonic levels (glided across)
        self.breath = _Filter()
        self.rng = np.random.default_rng()
        self.playing: list[list] = []   # recorded calls: [samples, position, step, gain, fade]
        self.played = 1e9               # seconds since the last one started
        self.last = -1                  # which one that was (not picked twice in a row)

    @classmethod
    def prepare(cls, cfg):
        critters.fetch(cls.type)

    def _call(self, since: float, loud: bool, rel: float,
              dt: float) -> tuple[float, float, float]:
        """(pitch in semitones from BASE_HZ, loudness 0..1 of yours, mouth row) for
        this block, `dt` seconds long."""
        raise NotImplementedError

    def _listen(self, x: np.ndarray, rate: int) -> bool:
        """Your loudness and pitch this block; True when a new syllable starts."""
        n = len(x)
        f0 = self.tracker.update(x)
        self.filled += n
        if self.filled < self.tracker.window:
            f0 = 0.0
        level = float(np.sqrt(np.mean(x * x)))
        loud = level > self.GATE
        self.peak = max(self.peak, level)
        self.dip = min(self.dip, level)
        self.since += n / rate
        fresh = loud and (not self.talking
                          or (self.since > self.GAP_S and self.dip < 0.5 * self.peak
                              and level > 2 * self.dip))
        if fresh or not loud:
            self.peak = self.dip = level
        self.talking = loud
        if fresh:
            self.since = 0.0
        # (a syllable's first moment: the tracker's window still holds the quiet
        # before it, and its pitch comes out wrong, often an octave off)
        if loud and f0 > 0 and self.since >= self.SETTLE_S:
            st = 12 * np.log2(f0)
            self.heard += 1
            if self.heard == 1:
                self.home = st
            else:   # a running median: a stray octave jump can't drag it
                self.home += np.sign(st - self.home) * max(0.02, 2.0 / self.heard ** 0.75)
            self.rel = float(np.clip(st - self.home, -12, 12))
        # loudness: quick up, a little slower down
        tau = 0.01 if level > self.level else 0.04
        self.level += (1 - np.exp(-n / rate / tau)) * (level - self.level)
        return fresh

    def run(self, x, rate):
        n = len(x)
        if n == 0:
            return x
        fresh = self._listen(x, rate)
        recs = critters.calls(self.type)
        if recs:
            return self._play(x, rate, fresh, recs)
        semis, gain, mouth = self._call(self.since, self.talking, self.rel * self.p["follow"],
                                        n / rate)
        f_goal = self.BASE_HZ * 2 ** ((self.p["note"] + semis) / 12)
        a_goal = gain * min(self.level, self.MOST) * 1.4   # (a held tone or a hum: not 3x)
        mix = F32(self.p["mix"])
        if self.amp < 1e-5 and a_goal < 1e-5:
            self.amp = 0.0
            self.amps = None
            return (x * (1 - mix)).astype(F32)
        f0 = self.f or f_goal
        self.f = f_goal
        amp0, self.amp = self.amp, a_goal
        self.mouth += (1 - np.exp(-n / rate / self.MOUTH_S)) * (mouth - self.mouth)
        # pitch across the block, with a little vibrato
        t = np.arange(1, n + 1) / rate
        f = np.linspace(f0, f_goal, n + 1)[1:]
        f = f * (1 + self.VIB_DEPTH * np.sin(self.vib + 2 * np.pi * self.VIB_HZ * t))
        self.vib = float((self.vib + 2 * np.pi * self.VIB_HZ * n / rate) % (2 * np.pi))
        ph = self.phase + np.cumsum(2 * np.pi * f / rate)
        self.phase = float(ph[-1] % (2 * np.pi))
        # the buzz through the mouth: every harmonic at the mouth's level
        top = min(self.TOP_HZ, rate * 0.45)
        k_n = max(1, int(top / (f_goal * 1.03)))
        ks = np.arange(1, k_n + 1)
        rows = self.MOUTHS
        lo = int(np.clip(np.floor(self.mouth), 0, len(rows) - 2))
        a = float(np.clip(self.mouth - lo, 0, 1))
        peaks = rows[lo] * (1 - a) + rows[lo + 1] * a
        amps = _formants(ks * f_goal, peaks)
        amps = amps / np.sqrt(0.5 * float((amps * amps).sum()))      # rms 1
        old = self.amps
        if old is None or len(old) != k_n:
            old = amps
        self.amps = amps
        ramp = np.linspace(0, 1, n, endpoint=False)
        wave = np.einsum("kn,kn->n", np.sin(np.outer(ks, ph)),
                         old[:, None] + (amps - old)[:, None] * ramp)
        g = np.linspace(amp0, self.amp, n, endpoint=False)
        lo_hz, hi_hz = self.BREATH_BAND
        hi_hz = min(hi_hz, 0.45 * rate)
        noise = self.breath.run(self.rng.standard_normal(n).astype(F32), "breath",
                                lambda: butter(2, [lo_hz, hi_hz], btype="band",
                                               fs=rate).astype(F32))
        wet = (self._voice(wave) + noise * F32(2 * self.BREATH)) * g
        wet = wet.astype(F32)
        return wet if mix >= 1 else (x * (1 - mix) + wet * mix).astype(F32)

    def _voice(self, wave: np.ndarray) -> np.ndarray:
        """The buzz as the animal's throat makes it (a subclass may roughen it)."""
        return wave

    def _step(self, rate: int) -> float:
        """How fast a recorded call is read: its pitch moved by Pitch and your tune.
        (They're made at critters.RATE: a mic at another rate reads them faster or
        slower, so they keep their pitch.)"""
        st = self.p["note"] + float(np.clip(self.rel * self.p["follow"],
                                            -self.FOLLOW_ST, self.FOLLOW_ST))
        return 2 ** (st / 12) * critters.RATE / rate

    def _play(self, x, rate, fresh: bool, recs) -> np.ndarray:
        """The recorded calls: a new one on a new syllable (or straight after the last
        while you keep talking), its pitch following your tune, as loud as you."""
        n = len(x)
        self.played += n / rate
        idle = not self.playing
        if self.talking and (fresh or idle) and self.played >= self.HOLD_S:
            for v in self.playing:                       # cut short: faded out
                v[4] = min(v[4], int(self.SWAP_S * rate))
            k = int(self.rng.integers(len(recs)))
            if len(recs) > 1 and k == self.last:
                k = (k + 1) % len(recs)
            self.last, self.played = k, 0.0
            self.playing.append([recs[k], 0.0, self._step(rate), 0.0, 1 << 30])
        # loudness: yours as the call starts (it keeps rising for a moment), then held
        want = min(max(self.level, self.GATE), self.MOST) / critters.CALL_RMS
        wet = np.zeros(n, F32)
        keep = []
        for v in self.playing:
            rec, pos, step, gain, fade = v
            if pos < self.TUNE_S * critters.RATE:     # still starting: as loud as you get,
                gain = v[3] = max(gain, want)           # at the pitch you settle on
                step = v[2] = self._step(rate)
            idx = pos + step * np.arange(n)
            ok = idx < len(rec) - 1
            i0 = idx[ok].astype(np.int64)
            fr = (idx[ok] - i0).astype(F32)
            seg = rec[i0] * (1 - fr) + rec[i0 + 1] * fr
            g = np.full(len(seg), gain, F32)
            if fade < 1 << 30:                           # fading out: then it's done
                g *= np.clip((fade - np.arange(len(seg))) / (self.SWAP_S * rate), 0, 1)
            wet[:len(seg)] += seg * g
            v[1] = pos + step * n
            v[4] = fade - n if fade < 1 << 30 else fade
            if ok.all() and v[4] > 0:
                keep.append(v)
        self.playing = keep
        mix = F32(self.p["mix"])
        return wet if mix >= 1 else (x * (1 - mix) + wet * mix).astype(F32)


@register
class Cat(_Critter):
    """Meows. Each syllable is "mi-aaa" (the mouth opening from a nasal "i" to a
    wide "a" while the pitch rises a little), held as long as you hold it, and an
    "ow" as you stop (the mouth closing and the pitch falling). A cat's mouth is
    small: its resonances sit well above a person's."""

    type = "cat"
    name = "Cat"
    description = "Every syllable you say comes out as a meow."

    BASE_HZ = 560.0
    HOLD_S = 0.6           # a meow is held: a new syllable within this doesn't cut it
    GAP_S = 0.35
    #                  first          second         third
    MOUTHS = np.array([[[450, 250, 0.6], [2700, 500, 1.0], [4200, 700, 0.5]],    # "m(i)"
                       [[1200, 400, 1.0], [2100, 500, 0.8], [4300, 700, 0.5]],   # "a"
                       [[600, 300, 1.0], [1300, 400, 0.6], [3800, 700, 0.3]]],   # "ow"
                      F32)
    OPEN_S = 0.14          # "mi" to "a"
    CLOSE_S = 0.22         # the "ow" as you stop
    RISE, FALL = 3.0, -6.0  # semitones up while opening, down while closing

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.held = 0.0    # how far the call had got when you stopped (0..2)
        self.quiet = 0.0   # seconds since you stopped

    def _call(self, since, loud, rel, dt):
        if since > 1e8:
            return rel, 0.0, 0.0
        if loud:
            self.quiet = 0.0
            o = min(since / self.OPEN_S, 1.0)
            self.held = o
            return rel + self.RISE * o, 0.35 + 0.65 * min(since / 0.03, 1.0), o
        # stopped: the mouth closes to "ow", the pitch falls and it fades out
        self.quiet += dt
        c = min(self.quiet / self.CLOSE_S, 1.0)
        return (rel + self.RISE * self.held + self.FALL * c, 1.0 - c,
                self.held + (2 - self.held) * min(1.5 * c, 1.0))


@register
class Dog(_Critter):
    """Barks. Each syllable is one short "woof": a hard start, the mouth going from
    a rounded "w" to an open "uh", the pitch dropping, gone in under a fifth of a
    second; a syllable held longer barks again. The buzz is rough (its pitch
    jitters, with a growl an octave down) and pushed hard, with plenty of breath."""

    type = "dog"
    name = "Dog"
    description = "Every syllable you say comes out as a bark."

    BASE_HZ = 330.0
    HOLD_S = 0.18
    MOUTHS = np.array([[[350, 200, 1.0], [800, 300, 0.6], [2400, 600, 0.2]],    # "w"
                       [[750, 300, 1.0], [1350, 400, 0.9], [2700, 600, 0.4]]],  # "uh"
                      F32)
    BREATH = 0.3
    BREATH_BAND = (500, 3500)
    TOP_HZ = 6000.0
    VIB_DEPTH = 0.0
    BARK_S = 0.18          # one bark, start to end
    AGAIN_S = 0.32         # held this long, it barks again
    DROP = -5.0            # semitones its pitch falls across a bark

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.jit = 0.0
        self.sub_phase = 0.0

    def _call(self, since, loud, rel, dt):
        if since > 1e8:
            return rel, 0.0, 0.0
        if loud and since >= self.AGAIN_S:
            self.since = since = since % self.AGAIN_S   # held: the next woof
        b = since / self.BARK_S
        if b >= 1:
            return rel + self.DROP, 0.0, 1.0
        attack = min(since / 0.006, 1.0)
        gain = attack * (1.0 if b < 0.25 else np.exp(-(b - 0.25) * 4.5)) * 1.6
        self.jit = float(np.clip(self.jit + self.rng.normal(0, 0.35), -0.8, 0.8))
        return rel + 2.0 + self.DROP * b + self.jit, gain, min(since / 0.03, 1.0)

    def _voice(self, wave):
        # rough: a growl an octave down under it, then pushed into a soft clip
        n = len(wave)
        ph = self.sub_phase + np.cumsum(np.full(n, np.pi * self.f / self.rate))
        self.sub_phase = float(ph[-1] % (2 * np.pi))
        rough = wave + F32(0.5) * np.sin(ph).astype(F32) * (1 + F32(0.5) * wave)
        return np.tanh(rough * F32(1.6)).astype(F32) * F32(0.9)
