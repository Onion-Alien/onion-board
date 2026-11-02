"""Echo and Reverb, and the Effects pop-up's own copies of Robot, Radio, Echo and Reverb."""
from __future__ import annotations

from dataclasses import replace

import numpy as np
from soundboard.audio.dsp import butter, lfilter
from soundboard.voicefx import Effect, Param, register

from soundboard.voicefx.builtin.parts import F32, _Filter, _Line, _one_pole_lowpass
from soundboard.voicefx.builtin.pitch import PitchShift
from soundboard.voicefx.builtin.retro import BitCrush
from soundboard.voicefx.builtin.synth import Robot
from soundboard.voicefx.builtin.tone import Radio


@register
class Echo(Effect):
    type = "echo"
    name = "Echo"
    description = "Repeating echo, from slapback to canyon."
    params = (Param("delay", "Delay", 40, 1000, 250, " ms", 10),
              Param("feedback", "Repeats", 0, 0.9, 0.35),
              Param("mix", "Mix", 0, 1, 0.4),
              Param("tone", "Tone", 1000, 12000, 12000, " Hz", 100))

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.hist = _Line(self._len())
        self.lp = _Filter()

    def _len(self) -> int:
        return max(1, int(self.rate * self.p["delay"] / 1000))

    def run(self, x, rate):
        d, old = self._len(), None
        if d != len(self.hist):      # delay slider moved: the echoes carry on
            old, self.hist = self.hist, self.hist.resized(d)
        fb, mix, tone = F32(self.p["feedback"]), F32(self.p["mix"]), self.p["tone"]
        out = np.empty_like(x)
        hist, n, i = self.hist, len(x), 0
        # each repeat comes back a little darker; at the top of the range the filter
        # fades out (switching it off at once clicked) and is then skipped
        dark = tone < 12000 or not self.lp.f.idle
        while i < n:
            c = min(d, n - i)
            delayed = hist.take_after(old, c)
            old = None
            if dark:
                delayed = self.lp.run(delayed, tone, lambda: (
                    _one_pole_lowpass(tone, rate) if tone < 12000 else None))
            out[i:i + c] = x[i:i + c] + mix * delayed
            hist.put(x[i:i + c] + fb * delayed)
            i += c
        return out


@register
class Reverb(Effect):
    """A room in three parts, the way real ones reach the ear.

    Pre-delay holds the room back a little, so the voice stays clear in front of
    it. Early reflections: a dozen taps off the dry voice at 4 to 60 ms (the first
    bounces off the nearest walls), spaced unevenly with alternating signs so they
    don't ring at one pitch. Late tail: Freeverb, eight parallel damped combs into
    four allpasses. The damping (a lowpass inside each comb's feedback) is what
    keeps it from ringing like a metal pipe: real rooms swallow highs faster than
    lows. (A feedback delay network was tried in its place and measured less
    smooth: tail flatness 0.28 against these combs' 0.34, worst echo repeat 0.21
    against 0.15.)

    A moved Pre-delay crossfades from the old taps to the new ones across the
    block, so dragging it doesn't click."""

    type = "reverb"
    name = "Reverb"
    description = "Room, hall or cave."
    params = (Param("size", "Size", 0, 1, 0.5),
              Param("tone", "Brightness", 1500, 12000, 5000, " Hz", 100),
              Param("mix", "Mix", 0, 1, 0.3),
              Param("predelay", "Pre-delay", 0, 100, 10, " ms", 1))

    COMBS = (1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617)     # samples at 44.1 kHz
    ALLPASSES = (556, 441, 341, 225)
    EARLY = ((0.0043, 0.84), (0.0215, 0.5), (0.0225, -0.4), (0.0268, 0.38),
             (0.0270, -0.33), (0.0298, 0.32), (0.0458, 0.28), (0.0485, -0.25),
             (0.0572, 0.22), (0.0587, -0.2), (0.0595, 0.18), (0.0612, 0.17))
    EARLY_LEVEL = 0.35
    PRE_MAX_S = 0.1
    LIGHT_COMBS, LIGHT_ALLPASSES = 4, 2   # Use less CPU: half the reverb's delay lines

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        k = rate / 44100
        self.combs = [np.zeros(int(d * k), F32) for d in self.COMBS]
        self.damp = [np.zeros(1, F32) for _ in self.COMBS]        # lowpass memory per comb
        self.aps: list[tuple[np.ndarray, ...]] = [
            (np.zeros(int(d * k), F32),) * 2 for d in self.ALLPASSES]
        self.hp = _Filter()
        self.early_d = np.array([int(d * rate) for d, _ in self.EARLY])
        self.early_g = np.array([g for _, g in self.EARLY], F32)
        keep = int(self.PRE_MAX_S * rate) + int(self.early_d.max()) + 1
        self.hist = np.zeros(keep, F32)                      # the dry voice, newest last
        self.pre = int(self.p["predelay"] / 1000 * rate)

    @staticmethod
    def _tap(full: np.ndarray, d: int, n: int) -> np.ndarray:
        """The last n samples of `full`, d samples ago."""
        end = len(full) - d
        return full[end - n:end]

    def _room(self, x: np.ndarray, rate: int) -> tuple[np.ndarray, np.ndarray]:
        """(the pre-delayed voice, its early reflections) for this block."""
        n = len(x)
        full = np.concatenate([self.hist, x])
        self.hist = full[-len(self.hist):]
        pre, old = int(self.p["predelay"] / 1000 * rate), self.pre
        self.pre = pre
        def taps(d0):
            dry = self._tap(full, d0, n)
            early = np.zeros(n, F32)
            for d, gain in zip(self.early_d, self.early_g):
                early += gain * self._tap(full, d0 + d, n)
            return dry, early
        dry, early = taps(pre)
        if old != pre:      # the knob moved: glide from the old taps to the new
            dry0, early0 = taps(old)
            ramp = np.linspace(0, 1, n, endpoint=False, dtype=F32)
            dry = dry0 + (dry - dry0) * ramp
            early = early0 + (early - early0) * ramp
        return dry, early

    def _comb(self, x, k, g, a):
        """v[n] = x[n] + g·lp(v[n-D]); lp is a one-pole with coefficient a."""
        hist, n = self.combs[k], len(x)
        d = len(hist)
        out = np.empty(n, F32)
        i = 0
        while i < n:
            c = min(d, n - i)
            fed, self.damp[k] = lfilter([1 - a], [1, -a], hist[:c], zi=self.damp[k])
            v = x[i:i + c] + F32(g) * fed.astype(F32)
            out[i:i + c] = v
            hist = np.concatenate([hist[c:], v])
            i += c
        self.combs[k] = hist
        return out

    def set_light(self, on: bool):
        if self.light and not on:   # the lines that sat out start from silence, not
            for k in range(self.LIGHT_COMBS, len(self.combs)):   # from an old tail
                self.combs[k][:] = 0
                self.damp[k][:] = 0
            for k in range(self.LIGHT_ALLPASSES, len(self.aps)):
                xh, yh = self.aps[k]
                self.aps[k] = (np.zeros_like(xh), np.zeros_like(yh))
        super().set_light(on)

    def _in_use(self) -> tuple[int, int]:
        """How many combs and allpasses run (fewer with Use less CPU)."""
        if self.light:
            return self.LIGHT_COMBS, self.LIGHT_ALLPASSES
        return len(self.combs), len(self.aps)

    def _all_combs(self, x, g, a):
        """All the combs at once, for a block no longer than the shortest delay (the
        usual case): each one's feedback is then already in its history, so the
        eight damping filters run as one call over an (8, n) array."""
        n = len(x)
        used = self._in_use()[0]
        fed, zf = lfilter([1 - a], [1, -a], np.stack([h[:n] for h in self.combs[:used]]),
                          zi=np.stack(self.damp[:used]))
        v = x[None] + F32(g) * fed.astype(F32)
        for k in range(used):
            self.combs[k] = np.concatenate([self.combs[k][n:], v[k]])
            self.damp[k] = zf[k]
        return v.sum(axis=0)

    def run(self, x, rate):
        if len(x) == 0:
            return x
        g = 0.7 + 0.28 * self.p["size"]
        a = float(np.exp(-2 * np.pi * self.p["tone"] / rate))
        dry, early = self._room(x, rate)
        combs, aps = self._in_use()
        if len(x) <= min(len(h) for h in self.combs):
            wet = self._all_combs(dry, g, a)
        else:
            wet = np.zeros_like(x)
            for k in range(combs):
                wet += self._comb(dry, k, g, a)
        # same loudness at every size (and with half the combs: their sum is about
        # sqrt(2) quieter, their echoes being unrelated)
        wet *= F32(0.25 * np.sqrt(1 - g * g) * np.sqrt(len(self.combs) / combs))
        for k in range(aps):
            xh, yh = self.aps[k]
            wet, xh, yh = _allpass(wet, xh, yh, 0.5)
            self.aps[k] = (xh, yh)
        wet += early * F32(self.EARLY_LEVEL)
        # the combs pile up below ~150 Hz (they all agree there): keep the mud out
        wet = self.hp.run(wet, "hp", lambda: butter(
            2, 150, btype="high", fs=rate).astype(F32))
        mix = F32(self.p["mix"])
        return x * (1 - F32(0.6) * mix) + wet * (mix * F32(0.8))


def _allpass(x, xh, yh, g):
    """Schroeder allpass: y[n] = -g·x[n] + x[n-D] + g·y[n-D]."""
    d, n = len(xh), len(x)
    out = np.empty(n, F32)
    i = 0
    while i < n:
        c = min(d, n - i)
        xc = x[i:i + c]
        y = F32(-g) * xc + xh[:c] + F32(g) * yh[:c]
        out[i:i + c] = y
        xh = np.concatenate([xh[c:], xc])
        yh = np.concatenate([yh[c:], y])
        i += c
    return out, xh, yh


# ---- the Effects pop-up's own copies (ui/voice/effectspopup.py): on top of whatever voice
# is on, kept when you change voice. A voice's Robot or Echo is its own card in Edit
# voice; these never show there, and run after the voice's effects
@register
class ExtraRobot(Robot):
    type = "extra_robot"
    extra = True


@register
class ExtraRadio(Radio):
    type = "extra_radio"
    extra = True


@register
class ExtraEcho(Echo):
    type = "extra_echo"
    extra = True


@register
class ExtraReverb(Reverb):
    type = "extra_reverb"
    extra = True


@register
class ExtraAutotune(PitchShift):
    """Autotune on top of any voice: the pitch effect with only its snap to notes,
    full on when it's added."""
    type = "extra_autotune"
    name = "Autotune"
    extra = True
    params = tuple(replace(q, default=1.0) if q.key == "tune" else q
                   for q in PitchShift.params)


@register
class ExtraBitCrush(BitCrush):
    type = "extra_bitcrush"
    extra = True
