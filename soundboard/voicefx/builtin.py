"""Built-in voice effects: plain numpy/scipy DSP, cheap enough for the mic callback.

Every effect works on 1-D float32 blocks and keeps its own memory between blocks.
Recursive delays (echo, reverb) are computed in chunks no longer than their delay,
so each chunk only depends on output that already exists: whole-array numpy maths
instead of a per-sample Python loop.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import butter, sosfilt

from soundboard.voicefx import Effect, Param, register

F32 = np.float32


def _one_pole_lowpass(hz: float, rate: int) -> np.ndarray:
    return butter(1, min(hz, rate * 0.45), btype="low", fs=rate, output="sos").astype(F32)


class _Filter:
    """sosfilt with memory, redesigned only when its settings change."""

    def __init__(self):
        self.key = None
        self.sos = None
        self.zi = None

    def run(self, x: np.ndarray, key, design) -> np.ndarray:
        if key != self.key:
            sos = design()
            if self.sos is None or sos.shape != self.sos.shape:
                self.zi = np.zeros((len(sos), 2), F32)
            self.key, self.sos = key, sos
        y, self.zi = sosfilt(self.sos, x, zi=self.zi)
        return y.astype(F32, copy=False)


# --------------------------------------------------------------------------- pitch

@register
class PitchShift(Effect):
    """Delay-line pitch shifter: two read heads sweep through a 50 ms window at the
    new speed, crossfaded so each one is silent at the moment it jumps back. Latency
    is about half the window; formants move with the pitch (the chipmunk / giant
    sound people expect from a voice changer)."""

    type = "pitch"
    name = "Pitch"
    description = "Higher (chipmunk) or lower (giant) voice."
    params = (Param("semitones", "Pitch", -12, 12, 0, " st", 1),
              Param("mix", "Mix", 0, 1, 1))

    WINDOW_S = 0.05

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.w = int(rate * self.WINDOW_S)
        self.h = self.w + 2                      # history kept between blocks
        self.hist = np.zeros(self.h, F32)
        self.phase = 0.0

    def run(self, x, rate):
        buf = np.concatenate([self.hist, x])
        self.hist = buf[-self.h:].copy()
        st, mix = self.p["semitones"], self.p["mix"]
        if abs(st) < 0.01 or mix <= 0:
            return x
        n, w = len(x), self.w
        inc = (1.0 - 2.0 ** (st / 12.0)) / w     # delay change per sample, in windows
        ph = (self.phase + inc * np.arange(1, n + 1)) % 1.0
        self.phase = float(ph[-1])
        base = self.h - 1 + np.arange(n, dtype=np.float64)
        wet = np.zeros(n, np.float64)
        for off in (0.0, 0.5):
            p = (ph + off) % 1.0
            pos = base - p * w
            i = pos.astype(np.int64)
            f = pos - i
            wet += (buf[i] * (1 - f) + buf[i + 1] * f) * np.sin(np.pi * p) ** 2
        wet = wet.astype(F32)
        return wet if mix >= 1 else x * F32(1 - mix) + wet * F32(mix)


# --------------------------------------------------------------------------- tone

@register
class Distortion(Effect):
    type = "distortion"
    name = "Distortion"
    description = "Overdriven, crunchy voice."
    params = (Param("drive", "Drive", 0, 36, 12, " dB", 1),
              Param("tone", "Tone", 1000, 12000, 6000, " Hz", 100),
              Param("level", "Volume", 0.05, 1, 0.5))

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.lp = _Filter()

    def run(self, x, rate):
        g = F32(10 ** (self.p["drive"] / 20))
        y = np.tanh(x * g) * F32(self.p["level"])
        tone = self.p["tone"]
        return self.lp.run(y, tone, lambda: _one_pole_lowpass(tone, rate))


@register
class Robot(Effect):
    """Ring modulator: the voice multiplied by a low sine, the classic robot/dalek."""

    type = "robot"
    name = "Robot"
    description = "Metallic ring-modulated voice."
    params = (Param("freq", "Buzz", 20, 300, 60, " Hz", 1),
              Param("mix", "Mix", 0, 1, 1))

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.phase = 0.0

    def run(self, x, rate):
        n = len(x)
        step = 2 * np.pi * self.p["freq"] / rate
        t = self.phase + step * np.arange(n)
        self.phase = float((self.phase + step * n) % (2 * np.pi))
        wet = x * np.sin(t).astype(F32)
        mix = F32(self.p["mix"])
        return x * (1 - mix) + wet * mix


@register
class Radio(Effect):
    """Band-limited, slightly overdriven voice with a bit of static."""

    type = "radio"
    name = "Radio"
    description = "Walkie-talkie, telephone or megaphone."
    params = (Param("low", "Low cut", 150, 1200, 400, " Hz", 10),
              Param("high", "High cut", 1500, 7000, 3000, " Hz", 50),
              Param("drive", "Crunch", 0, 24, 6, " dB", 1),
              Param("noise", "Static", 0, 0.05, 0.004))

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.bp = _Filter()
        self.rng = np.random.default_rng()

    def run(self, x, rate):
        lo, hi = self.p["low"], self.p["high"]
        hi = min(max(hi, lo * 1.5), rate * 0.45)
        y = self.bp.run(x, (lo, hi),
                        lambda: butter(2, [lo, hi], btype="band", fs=rate,
                                       output="sos").astype(F32))
        g = F32(10 ** (self.p["drive"] / 20))
        y = np.tanh(y * g) / F32(min(float(g), 4.0) ** 0.5)
        if self.p["noise"] > 0:
            y += self.rng.standard_normal(len(y)).astype(F32) * F32(self.p["noise"])
        return y


# --------------------------------------------------------------------------- space

def _comb(x: np.ndarray, hist: np.ndarray, g: float) -> tuple[np.ndarray, np.ndarray]:
    """v[n] = x[n] + g·v[n-D], D = len(hist) (hist = the last D values of v)."""
    d, n = len(hist), len(x)
    out = np.empty(n, F32)
    i = 0
    while i < n:
        c = min(d, n - i)
        v = x[i:i + c] + F32(g) * hist[:c]
        out[i:i + c] = v
        hist = np.concatenate([hist[c:], v])
        i += c
    return out, hist


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


@register
class Echo(Effect):
    type = "echo"
    name = "Echo"
    description = "Repeating echo, from slapback to canyon."
    params = (Param("delay", "Delay", 40, 1000, 250, " ms", 10),
              Param("feedback", "Repeats", 0, 0.9, 0.35),
              Param("mix", "Mix", 0, 1, 0.4))

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.hist = np.zeros(self._len(), F32)

    def _len(self) -> int:
        return max(1, int(self.rate * self.p["delay"] / 1000))

    def run(self, x, rate):
        d = self._len()
        if d != len(self.hist):      # delay slider moved: start a fresh line
            self.hist = np.zeros(d, F32)
        fb, mix = F32(self.p["feedback"]), F32(self.p["mix"])
        out = np.empty_like(x)
        hist, n, i = self.hist, len(x), 0
        while i < n:
            c = min(d, n - i)
            delayed = hist[:c]
            out[i:i + c] = x[i:i + c] + mix * delayed
            hist = np.concatenate([hist[c:], x[i:i + c] + fb * delayed])
            i += c
        self.hist = hist
        return out


@register
class Reverb(Effect):
    """Small Schroeder reverb: four parallel combs into two allpasses."""

    type = "reverb"
    name = "Reverb"
    description = "Room, hall or cave."
    params = (Param("size", "Size", 0, 1, 0.5),
              Param("tone", "Brightness", 1500, 12000, 5000, " Hz", 100),
              Param("mix", "Mix", 0, 1, 0.3))

    COMBS_MS = (29.7, 37.1, 41.1, 43.7)
    ALLPASS_MS = (5.0, 1.7)

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.combs = [np.zeros(int(rate * ms / 1000), F32) for ms in self.COMBS_MS]
        self.aps = [(np.zeros(int(rate * ms / 1000), F32),) * 2 for ms in self.ALLPASS_MS]
        self.lp = _Filter()

    def run(self, x, rate):
        g = 0.7 + 0.27 * self.p["size"]
        wet = np.zeros_like(x)
        for k, hist in enumerate(self.combs):
            y, self.combs[k] = _comb(x, hist, g)
            wet += y
        wet *= F32(0.25 * (1 - g))            # keep the tail from swamping the voice
        for k, (xh, yh) in enumerate(self.aps):
            wet, xh, yh = _allpass(wet, xh, yh, 0.5)
            self.aps[k] = (xh, yh)
        tone = self.p["tone"]
        wet = self.lp.run(wet, tone, lambda: _one_pole_lowpass(tone, rate))
        mix = F32(self.p["mix"])
        return x * (1 - F32(0.5) * mix) + wet * (mix * F32(4))


# --------------------------------------------------------------------------- presets

# name -> the effects that are on, with their settings (everything else is off)
PRESETS: dict[str, dict[str, dict]] = {
    "Chipmunk":          {"pitch": {"semitones": 8}},
    "Deep voice":        {"pitch": {"semitones": -5}},
    "Giant / demon":     {"pitch": {"semitones": -9},
                          "distortion": {"drive": 10, "tone": 4000, "level": 0.6},
                          "reverb": {"size": 0.7, "tone": 3000, "mix": 0.3}},
    "Robot":             {"robot": {"freq": 60, "mix": 1},
                          "reverb": {"size": 0.2, "tone": 6000, "mix": 0.15}},
    "Alien":             {"pitch": {"semitones": 4, "mix": 0.5},
                          "robot": {"freq": 180, "mix": 0.45}},
    "Walkie-talkie":     {"radio": {"low": 500, "high": 2500, "drive": 12, "noise": 0.008}},
    "Old telephone":     {"radio": {"low": 400, "high": 3000, "drive": 3, "noise": 0.0}},
    "Megaphone":         {"radio": {"low": 600, "high": 4500, "drive": 20, "noise": 0.0},
                          "reverb": {"size": 0.3, "tone": 5000, "mix": 0.15}},
    "Cave":              {"reverb": {"size": 0.95, "tone": 4000, "mix": 0.45},
                          "echo": {"delay": 180, "feedback": 0.25, "mix": 0.2}},
    "Stadium announcer": {"echo": {"delay": 320, "feedback": 0.3, "mix": 0.3},
                          "reverb": {"size": 0.8, "tone": 6000, "mix": 0.3}},
}
