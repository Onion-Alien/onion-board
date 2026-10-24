"""Chorus, Flanger and Wobble: effects that sway the voice."""
from __future__ import annotations

import numpy as np
from soundboard.voicefx import Effect, Param, register

from soundboard.voicefx.builtin.parts import F32, _glide


@register
class Chorus(Effect):
    """Two copies of the voice on slowly wandering delays, mixed with the original."""

    type = "chorus"
    name = "Chorus"
    description = "Doubled, wobbling voice: subtle shimmer to full alien warble."
    params = (Param("rate", "Speed", 0.1, 8, 1.0, " Hz", 0.1),
              Param("depth", "Depth", 0.5, 15, 4, " ms", 0.5),
              Param("mix", "Mix", 0, 1, 0.5))

    MAX_MS = 20.0

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.h = int(rate * self.MAX_MS / 1000) + 2
        self.hist = np.zeros(self.h, F32)
        self.phase = 0.0
        self.depth = None

    def run(self, x, rate):
        n = len(x)
        buf = np.concatenate([self.hist, x])
        self.hist = buf[-self.h:].copy()
        ph = self.phase + 2 * np.pi * self.p["rate"] / rate * np.arange(1, n + 1)
        self.phase = float(ph[-1] % (2 * np.pi))
        depth = min(self.p["depth"], self.MAX_MS - 1.5) * rate / 1000
        # a new depth moves the read position: glide there, or it jumps (a click)
        d0, self.depth = (depth if self.depth is None else self.depth), depth
        if d0 != depth:
            depth = np.linspace(d0, depth, n + 1)[1:]
        base = self.h - 1 + np.arange(n, dtype=np.float64) - 1.0 * rate / 1000
        wet = np.zeros(n, np.float64)
        for off in (0.0, np.pi / 2):
            pos = base - depth * (1 + np.sin(ph + off)) * 0.5
            i = pos.astype(np.int64)
            f = pos - i
            wet += buf[i] * (1 - f) + buf[i + 1] * f
        mix = F32(self.p["mix"])
        return x * (1 - mix) + wet.astype(F32) * (mix * F32(0.5))


@register
class Flanger(Effect):
    """The voice mixed with a copy on a short delay (1 to 7 ms) that sweeps up and
    down, with some of the output fed back in: the comb notches sweep through the
    voice (a jet, a pipe, under water). The feedback needs the output's own past, so
    the block runs in pieces no longer than the shortest delay; every piece's
    feedback is then already in the history."""

    type = "flanger"
    name = "Flanger"
    description = "Sweeping, jet-plane swirl, from gentle to under water."
    params = (Param("rate", "Speed", 0.05, 5, 0.3, " Hz", 0.05),
              Param("depth", "Depth", 0.2, 6, 3, " ms", 0.1),
              Param("feedback", "Feedback", 0, 0.9, 0.5, "", 0, ("none", "resonant")),
              Param("mix", "Mix", 0, 1, 0.5))

    MIN_MS, MAX_MS = 1.0, 8.0

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.h = int(rate * self.MAX_MS / 1000) + 2
        self.xh = np.zeros(self.h, F32)
        self.yh = np.zeros(self.h, F32)
        self.phase = 0.0
        self.depth = None
        self.fb = None

    def run(self, x, rate):
        n = len(x)
        if n == 0:
            return x
        xf = np.concatenate([self.xh, x])
        yf = np.concatenate([self.yh, np.zeros(n, F32)])
        ph = self.phase + 2 * np.pi * self.p["rate"] / rate * np.arange(1, n + 1)
        self.phase = float(ph[-1] % (2 * np.pi))
        depth = min(self.p["depth"], self.MAX_MS - self.MIN_MS - 0.1) * rate / 1000
        d0, self.depth = (depth if self.depth is None else self.depth), depth
        dep = np.linspace(d0, depth, n + 1)[1:] if d0 != depth else depth
        base = self.MIN_MS * rate / 1000
        delay = base + dep * (1 + np.sin(ph)) * 0.5          # samples, fractional
        fb = self.p["feedback"]
        fbs = _glide(fb if self.fb is None else self.fb, fb, n)
        self.fb = fb
        step = max(1, int(base))
        i = 0
        while i < n:
            c = min(step, n - i)
            pos = self.h + i + np.arange(c) - delay[i:i + c]
            k = pos.astype(np.int64)
            f = (pos - k).astype(F32)
            xd = xf[k] * (1 - f) + xf[k + 1] * f
            yd = yf[k] * (1 - f) + yf[k + 1] * f
            g = fbs[i:i + c] if isinstance(fbs, np.ndarray) else fbs
            yf[self.h + i:self.h + i + c] = xd + g * yd
            i += c
        self.xh = xf[-self.h:].copy()
        self.yh = yf[-self.h:].copy()
        mix = F32(self.p["mix"])
        return x * (1 - mix) + yf[self.h:] * mix


@register
class Wobble(Effect):
    """Vibrato and tremolo: the pitch wobbles (the voice read off a delay that
    sways back and forth) and the volume wobbles, at one speed. Slow and deep is
    drunk or seasick; fast and shallow is an old film or a nervous voice."""

    type = "wobble"
    name = "Wobble"
    description = "Pitch and volume wobble: drunk, seasick, an old film."
    params = (Param("rate", "Speed", 0.3, 12, 5, " Hz", 0.1),
              Param("vibrato", "Vibrato", 0, 40, 2, " ms", 0.1, ("steady", "seasick")),
              Param("tremolo", "Tremolo", 0, 1, 0.3, "", 0, ("steady", "flutter")))

    MAX_MS = 42.0

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.h = int(rate * self.MAX_MS / 1000) + 2
        self.hist = np.zeros(self.h, F32)
        self.phase = 0.0
        self.depth = None
        self.trem = None

    def run(self, x, rate):
        n = len(x)
        if n == 0:
            return x
        buf = np.concatenate([self.hist, x])
        self.hist = buf[-self.h:].copy()
        ph = self.phase + 2 * np.pi * self.p["rate"] / rate * np.arange(1, n + 1)
        self.phase = float(ph[-1] % (2 * np.pi))
        depth = min(self.p["vibrato"], self.MAX_MS - 1.5) * rate / 1000
        d0, self.depth = (depth if self.depth is None else self.depth), depth
        dep = np.linspace(d0, depth, n + 1)[1:] if d0 != depth else depth
        pos = self.h - 1 + np.arange(n, dtype=np.float64) - dep * (1 + np.sin(ph)) * 0.5
        k = pos.astype(np.int64)
        f = pos - k
        y = buf[k] * (1 - f) + buf[k + 1] * f
        trem = self.p["tremolo"]
        t0, self.trem = (trem if self.trem is None else self.trem), trem
        tr = np.linspace(t0, trem, n + 1)[1:] if t0 != trem else trem
        gain = 1 - tr * (1 + np.sin(ph + np.pi / 2)) * 0.5
        return (y * gain).astype(F32)
