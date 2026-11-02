"""Compressor, Tone, Radio, Distortion, Shout blowout and Helmet: volume and colour."""
from __future__ import annotations

import collections

import numpy as np
from soundboard.audio.dsp import butter
from soundboard.voicefx import Effect, Param, register

from soundboard.voicefx.builtin.parts import (F32, _Filter, _Line, _Oversampled, _biquad, _chunks,
                                              _envelope, _glide, _one_pole_lowpass, _per_chunk,
                                              _spread)


@register
class Compressor(Effect):
    """Peak compressor: the level is read every millisecond (not once per block, which
    reacted late at big blocks and pumped at their edges), a 6 dB soft knee eases it
    in, and the gain chases the target at the attack and release speeds, then runs
    as straight lines between those points: no per-sample loop."""

    type = "compressor"
    name = "Compressor"
    description = "Evens out your volume: quiet words louder, shouting tamed."
    params = (Param("threshold", "Kicks in at", -40, 0, -20, " dB", 1),
              Param("ratio", "Squash", 1, 20, 4, ":1", 0.5),
              Param("boost", "Boost", 0, 24, 6, " dB", 1),
              Param("attack", "Attack", 0.5, 50, 4, " ms", 0.5, ("snappy", "soft")),
              Param("release", "Release", 20, 1000, 150, " ms", 10, ("quick", "slow")))

    KNEE_DB = 6.0
    CHUNK_S = 0.001

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.g = 1.0
        self.boost = 10 ** (self.p["boost"] / 20)

    def _target(self, peak: np.ndarray) -> np.ndarray:
        level = 20 * np.log10(peak + 1e-9)
        over = level - self.p["threshold"]
        slope = 1 - 1 / self.p["ratio"]
        w = self.KNEE_DB
        cut = np.where(over >= w / 2, over * slope,
                       np.where(over > -w / 2, slope * (over + w / 2) ** 2 / (2 * w), 0.0))
        return 10 ** (-cut / 20)

    def run(self, x, rate):
        n = len(x)
        boost = 10 ** (self.p["boost"] / 20)
        if n == 0:
            self.boost = boost
            return x
        starts = _chunks(n, max(1, int(rate * self.CHUNK_S)))
        ends = np.append(starts[1:], n)
        peak = _per_chunk(np.abs(x), starts, np.maximum)
        g = _envelope(self._target(peak), self.g, ends - starts, rate,
                      self.p["attack"] / 1000, self.p["release"] / 1000)
        ramp = _spread(self.g, g, ends, n)
        self.g = float(g[-1])
        ramp *= _glide(self.boost, boost, n)
        self.boost = boost
        return x * ramp


@register
class Tone(Effect):
    type = "tone"
    name = "Tone"
    description = "Bass, mid, presence and treble, like the EQ on a mixer."
    params = (Param("bass", "Bass", -12, 12, 0, " dB", 1),
              Param("mid", "Mid", -12, 12, 0, " dB", 1),
              Param("presence", "Presence", -12, 12, 0, " dB", 1),
              Param("treble", "Treble", -12, 12, 0, " dB", 1))

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.f = _Filter()

    def run(self, x, rate):
        b, m, p, t = self.p["bass"], self.p["mid"], self.p["presence"], self.p["treble"]
        if not (b or m or p or t) and self.f.f.idle:
            return x
        # all at 0: fade out to straight through (then, once the fade has run its
        # course, the line above skips it; cutting it short would strand the fade)
        return self.f.run(x, (b, m, p, t), lambda: None if not (b or m or p or t) else np.vstack([
            _biquad("lowshelf", 160, rate, b), _biquad("peak", 1000, rate, m, 1.0),
            _biquad("peak", 2500, rate, p, 1.0), _biquad("highshelf", 6000, rate, t)]))


# --------------------------------------------------------------------------- tone

@register
class Radio(Effect):
    """Band-limited, overdriven voice with a bed of static in the same band."""

    type = "radio"
    name = "Radio"
    description = "Walkie-talkie, telephone or megaphone band-limiting."
    params = (Param("low", "Low cut", 150, 1200, 400, " Hz", 10),
              Param("high", "High cut", 1500, 7000, 3000, " Hz", 50),
              Param("drive", "Crunch", 0, 24, 6, " dB", 1),
              Param("noise", "Static", 0, 0.05, 0.004),
              Param("squelch", "Click when I talk", 0, 1, 0, "", 1))

    HOLD_S = 0.3         # quiet this long = you let go of the talk button

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.bp = _Filter()
        self.bp_noise = _Filter()
        self.bp_click = _Filter()
        self.rng = np.random.default_rng()
        self.talking = False
        self.quiet = 0.0
        self.pending = np.zeros(0, F32)    # a click or a burst still playing out
        self.g = None                      # the crunch's gain last block

    def _burst(self, rate, secs, level, click=False) -> np.ndarray:
        n = int(rate * secs)
        t = np.arange(n) / rate
        env = np.exp(-t / (secs * (0.15 if click else 0.35)))
        env *= np.minimum(t / 0.003, 1.0)   # a 3 ms fade-in: no full-band snap
        z = self.rng.standard_normal(n) * env * level
        if click:   # the key: a short tick with a little tone in it
            z += np.sin(2 * np.pi * 1200 * t) * env * level * 1.5
        return z.astype(F32)

    def _squelch(self, x, rate) -> np.ndarray:
        """Walkie-talkie clicks: a key click when you start talking and the "kshh"
        of letting go of the button when you stop."""
        n = len(x)
        level = 20 * np.log10(float(np.sqrt(np.mean(x * x))) + 1e-9)
        if level > -42:
            if not self.talking:
                self.talking = True
                self.pending = self._burst(rate, 0.03, 0.3, click=True)
            self.quiet = 0.0
        elif self.talking:
            self.quiet += n / rate
            if self.quiet > self.HOLD_S:
                self.talking = False
                self.pending = self._burst(rate, 0.18, 0.3)
        add = np.zeros(n, F32)
        k = min(n, len(self.pending))
        add[:k] = self.pending[:k]
        self.pending = self.pending[k:]
        return add

    def run(self, x, rate):
        lo, hi = self.p["low"], self.p["high"]
        hi = min(max(hi, lo * 1.5), rate * 0.45)

        def design():
            return butter(2, [lo, hi], btype="band", fs=rate).astype(F32)

        y = self.bp.run(x, (lo, hi), design)
        g = 10 ** (self.p["drive"] / 20)
        g, self.g = _glide(g if self.g is None else self.g, g, len(x)), g
        y = np.tanh(y * g) / np.sqrt(np.minimum(g, F32(4)))
        if self.p["noise"] > 0:
            hiss = self.rng.standard_normal(len(y)).astype(F32) * F32(self.p["noise"] * 3)
            y += self.bp_noise.run(hiss, (lo, hi), design)
        if self.p.get("squelch", 0) >= 0.5:
            # the clicks go through the radio's band too: raw white noise on top of
            # a band-limited voice sounded like a hi-hat
            y = y + np.tanh(self.bp_click.run(self._squelch(x, rate), (lo, hi), design))
        return y


@register
class Distortion(Effect):
    """tanh overdrive, bent at 4x the rate (_Oversampled) so the crunch is harmonics
    of the voice and not aliasing fizz, then a tone lowpass.

    Driven hard, the mic's own hiss between words comes out as loud as the words.
    "Only while I talk" mutes it: it learns the mic's quietest level (a floor that
    drops at once and creeps back up FLOOR_RISE dB a second) and lets the crunch
    through only while the voice is OPEN_DB over it, holding on HOLD_S so the ends
    of words aren't cut."""

    type = "distortion"
    name = "Distortion"
    description = "Overdriven, crunchy voice."
    params = (Param("drive", "Drive", 0, 36, 12, " dB", 1),
              Param("tone", "Tone", 1000, 12000, 6000, " Hz", 100),
              Param("level", "Volume", 0.05, 1, 0.5),
              Param("talk", "Only while I talk", 0, 1, 0, "", 1))

    OPEN_DB, FLOOR_RISE, HOLD_S, CLOSE_S = 12.0, 3.0, 0.12, 0.06

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.lp = _Filter()
        self.os = _Oversampled(rate)
        self.gains = (10 ** (self.p["drive"] / 20), self.p["level"])
        self.floor = 0.0      # the mic's quietest level lately (dB)
        self.held = 0.0       # seconds the gate stays open with no voice
        self.gate = 1.0

    def latency(self) -> float:
        return self.os.latency(self.rate)

    def _gate(self, x: np.ndarray, rate: int):
        """The talk gate's gain across this block (1 while it's off)."""
        n = len(x)
        want = 1.0
        if self.p["talk"]:
            level = 10 * np.log10(float(np.mean(x * x)) + 1e-12)
            self.floor = min(level, self.floor + self.FLOOR_RISE * n / rate)
            if level > max(self.floor + self.OPEN_DB, -70.0):
                self.held = self.HOLD_S
            else:
                self.held -= n / rate
            want = 1.0 if self.held > 0 else 0.0
        g0 = self.gate
        if want >= g0:
            self.gate = want                   # opens at once: no word starts late
        else:
            self.gate = max(want, g0 - n / rate / self.CLOSE_S)
        return _glide(g0, self.gate, n)

    def run(self, x, rate):
        g, level = 10 ** (self.p["drive"] / 20), self.p["level"]
        (g0, level0), n = self.gains, len(x)
        self.gains = (g, level)
        if n == 0:
            return x
        gate = self._gate(x, rate)
        m = n * self.os.factor
        y = self.os.run(x, lambda z: np.tanh(z * _glide(g0, g, m)) * _glide(level0, level, m))
        tone = self.p["tone"]
        return self.lp.run(y, tone, lambda: _one_pole_lowpass(tone, rate)) * gate


@register
class Shout(Effect):
    """Reacts to how loud you are: talk normally and nothing happens, shout and the
    voice blows out like a megaphone (band-limited and overdriven), fading back as
    you calm down. It learns how loud you normally talk, so it works on a quiet mic
    too: a fixed level alone never went off on most mics."""

    type = "shout"
    name = "Shout blowout"
    description = "Shout and your voice blows out like a megaphone."
    params = (Param("threshold", "Kicks in at", -40, -3, -16, " dB", 1, ("whisper", "yell")),
              Param("drive", "Crunch", 0, 30, 14, " dB", 1))

    SPEECH_DB = -55     # louder than this counts as talking
    OVER_DB = 5         # this far over your normal talking level = shouting

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.bp = _Filter()
        self.env = -90.0
        self.amt = 0.0
        self.g = None       # the crunch's gain last block
        self.heard = collections.deque(maxlen=2000)   # your level while talking
        self.normal = None  # how loud you normally talk (their median)

    def run(self, x, rate):
        n = len(x)
        level = 20 * np.log10(float(np.max(np.abs(x))) + 1e-9)
        tau = 0.01 if level > self.env else 0.25
        self.env = level + (self.env - level) * float(np.exp(-n / (rate * tau)))
        if self.env > self.SPEECH_DB and self.amt < 0.5:   # shouting isn't "normal"
            self.heard.append(self.env)
            if len(self.heard) % 25 == 0:
                self.normal = float(np.median(self.heard))
        kick = self.p["threshold"]
        if self.normal is not None and len(self.heard) >= 100:
            # this much over your normal also counts; the slider moves it as well
            kick = min(kick, self.normal + self.OVER_DB + (kick + 16) / 3)
        target = min(max((self.env - kick) / 4.0, 0.0), 1.0)
        a = np.linspace(self.amt, target, n + 1, dtype=F32)[1:]
        self.amt = target
        # the top edge stays under Nyquist (an 8 kHz mic can't take a 4 kHz edge)
        y = self.bp.run(x, "bp", lambda: butter(2, [500, min(4000, 0.45 * rate)],
                                                btype="band", fs=rate).astype(F32))
        g = 10 ** (self.p["drive"] / 20)
        g, self.g = _glide(g if self.g is None else self.g, g, n), g
        wet = np.tanh(y * g) * F32(0.5)
        return x * (1 - a) + wet * a


@register
class Helmet(Effect):
    """A very short echo fed back on itself (a comb filter): the boxy, metallic ring
    of talking inside a helmet, a mask or a tin can."""

    type = "helmet"
    name = "Helmet"
    description = "Talking inside a helmet, mask or metal box."
    params = (Param("size", "Helmet size", 0.5, 8, 2.5, " ms", 0.1, ("tin can", "big helmet")),
              Param("ring", "Metal ring", 0, 0.9, 0.55),
              Param("mix", "Mix", 0, 1, 0.5))

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.hist = _Line(self._len())

    def _len(self) -> int:
        return max(2, int(self.rate * self.p["size"] / 1000))

    def run(self, x, rate):
        d, old = self._len(), None
        if d != len(self.hist):
            old, self.hist = self.hist, self.hist.resized(d)
        fb, mix = F32(self.p["ring"]), F32(self.p["mix"])
        out = np.empty_like(x)
        hist, n, i = self.hist, len(x), 0
        while i < n:
            c = min(d, n - i)
            v = x[i:i + c] + fb * hist.take_after(old, c)
            old = None
            out[i:i + c] = v
            hist.put(v)
            i += c
        wet = out * F32(1 - float(fb) * 0.7)      # about as loud as the dry voice
        return x * (1 - mix) + wet * mix
