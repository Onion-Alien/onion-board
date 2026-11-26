"""Chorus, Flanger and Wobble: effects that sway the voice."""
from __future__ import annotations

import math

import numpy as np
from soundboard.audio import nativedsp
from soundboard.voicefx import Effect, Param, register

from soundboard.voicefx.builtin.parts import F32, _glide


@register
class Chorus(Effect):
    """Two to eight copies on slowly wandering delays, mixed with the original."""

    type = "chorus"
    name = "Chorus"
    description = "Doubled, wobbling voice: subtle shimmer to full alien warble."
    params = (Param("rate", "Speed", 0.1, 8, 1.0, " Hz", 0.1),
              Param("depth", "Depth", 0.5, 15, 4, " ms", 0.5),
              Param("mix", "Mix", 0, 1, 0.5),
              Param("voices", "Voices", 2, 8, 2, "", 1))

    MAX_MS = 20.0

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.h = int(rate * self.MAX_MS / 1000) + 2
        self.hist = np.zeros(self.h, F32)
        self.phase = 0.0
        self.depth = None

    def run(self, x, rate):
        n = len(x)
        if not n:
            return x
        voices = int(round(self.p["voices"]))
        depth = min(self.p["depth"], self.MAX_MS - 1.5) * rate / 1000
        # a new depth moves the read position: glide there, or it jumps (a click)
        d0, self.depth = (depth if self.depth is None else self.depth), depth
        if d0 != depth:
            depth = np.linspace(d0, depth, n + 1)[1:]
        if nativedsp.HOLD is not None and voices == 2:   # preserve the two-voice fast path
            y, self.phase = nativedsp.chorus(self.hist, x, self.phase,
                                             2 * np.pi * self.p["rate"] / rate, depth,
                                             1.0 * rate / 1000, float(F32(self.p["mix"])))
            return y
        buf = np.concatenate([self.hist, x])
        self.hist = buf[-self.h:].copy()
        ph = self.phase + 2 * np.pi * self.p["rate"] / rate * np.arange(1, n + 1)
        self.phase = float(ph[-1] % (2 * np.pi))
        base = self.h - 1 + np.arange(n, dtype=np.float64) - 1.0 * rate / 1000
        wet = np.zeros(n, np.float64)
        # Keep the original pair exactly; spread additional copies around the cycle.
        offsets = (0.0, np.pi / 2) if voices == 2 else np.arange(voices) * (2 * np.pi / voices)
        for off in offsets:
            pos = base - depth * (1 + np.sin(ph + off)) * 0.5
            i = pos.astype(np.int64)
            f = pos - i
            wet += buf[i] * (1 - f) + buf[i + 1] * f
        mix = F32(self.p["mix"])
        return x * (1 - mix) + wet.astype(F32) * (mix * F32(1 / voices))


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
        if nativedsp.LIB is not None:
            delay = np.ascontiguousarray(delay, np.float64)
            fb_all = fbs if isinstance(fbs, np.ndarray) else np.full(n, fbs, F32)
            nativedsp.flanger(xf, yf, self.h, n, delay, fb_all)
            i = n
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
        depth = min(self.p["vibrato"], self.MAX_MS - 1.5) * rate / 1000
        d0, self.depth = (depth if self.depth is None else self.depth), depth
        dep = np.linspace(d0, depth, n + 1)[1:] if d0 != depth else depth
        trem = self.p["tremolo"]
        t0, self.trem = (trem if self.trem is None else self.trem), trem
        tr = np.linspace(t0, trem, n + 1)[1:] if t0 != trem else trem
        if nativedsp.HOLD is not None:   # the same, in C++
            y, self.phase = nativedsp.wobble(self.hist, x, self.phase,
                                             2 * np.pi * self.p["rate"] / rate, dep, tr)
            return y
        buf = np.concatenate([self.hist, x])
        self.hist = buf[-self.h:].copy()
        ph = self.phase + 2 * np.pi * self.p["rate"] / rate * np.arange(1, n + 1)
        self.phase = float(ph[-1] % (2 * np.pi))
        pos = self.h - 1 + np.arange(n, dtype=np.float64) - dep * (1 + np.sin(ph)) * 0.5
        k = pos.astype(np.int64)
        f = pos - k
        y = buf[k] * (1 - f) + buf[k + 1] * f
        gain = 1 - tr * (1 + np.sin(ph + np.pi / 2)) * 0.5
        return (y * gain).astype(F32)


@register
class Wah(Effect):
    """Sweeping resonant bandpass filter (Cytomic linear trapezoidal SVF) stepped on a
    fixed sample grid so the sweep stays smooth, unconditionally stable and identical
    regardless of the audio block size."""

    type = "wah"
    name = "Wah-wah"
    description = "Sweep a resonant filter across your voice."
    params = (Param("rate", "Speed", 0.3, 8, 2.2, " Hz", 0.1),
              Param("depth", "Depth", 0, 1, 0.85),
              Param("resonance", "Resonance", 1.5, 8, 4.0, "", 0.5, ("smooth", "sharp")),
              Param("mix", "Mix", 0, 1, 0.85))

    LO_HZ, HI_HZ = 350.0, 2400.0
    STEP = 32   # fixed sample grid between LFO filter updates (~0.67 ms at 48 kHz)

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.phase = 0.0
        self.rem = 0
        self.ic1 = 0.0
        self.ic2 = 0.0
        self.mix: float | None = None
        self._cell: tuple | None = None

    def _design(self, rate: int) -> tuple:
        """TPT SVF state-space constants for one STEP-sample cell at the current LFO phase."""
        hi = min(self.HI_HZ, rate * 0.42)
        lo = min(self.LO_HZ, hi * 0.5)
        lfo = 0.5 + 0.5 * self.p["depth"] * math.sin(self.phase)
        fc = lo * (hi / lo) ** lfo
        q = max(self.p["resonance"], 1.0)
        k = 1.0 / q
        g = math.tan(math.pi * min(fc, rate * 0.45) / rate)
        a1 = 1.0 / (1.0 + g * (g + k))
        a2 = g * a1
        a3 = g * a2
        # 2x2 state transition A = tr * I + a2 * M, where M = [[-k, -2], [2, k]] and M^2 = -w^2 * I
        tr = a1 - a3
        w = math.sqrt(max(4.0 - k * k, 1e-12))
        lam = complex(tr, a2 * w)
        # output v1 = C @ s + D * x, C = [a1, -a2], D = a2, B = [2*a2, 2*a3]
        cm0 = -k * a1 - 2.0 * a2
        cm1 = -2.0 * a1 - k * a2
        b0, b1 = 2.0 * a2, 2.0 * a3
        mb0, mb1 = -k * b0 - 2.0 * b1, 2.0 * b0 + k * b1
        cb = a1 * b0 - a2 * b1
        cmb = cm0 * b0 + cm1 * b1
        # constant-peak bandpass (k * v1 has 0 dB peak at fc) with gentle resonant makeup
        scale = k * (1.0 + 0.12 * q)
        return (a1, a2, k, w, lam, cm0, cm1, b0, b1, mb0, mb1, cb, cmb, scale)

    def _svf_chunk(self, xc: np.ndarray, cell: tuple) -> np.ndarray:
        """Run `len(xc)` samples of the constant-coefficient TPT SVF cell, updating ic1/ic2."""
        a1, a2, k, w, lam, cm0, cm1, b0, b1, mb0, mb1, cb, cmb, scale = cell
        m = len(xc)
        x64 = xc.astype(np.float64, copy=False)
        pw = lam ** np.arange(m + 1)
        u = pw[:m].real
        v = pw[:m].imag / w
        # free response from current integrator states
        v1 = (a1 * u + cm0 * v) * self.ic1 + (-a2 * u + cm1 * v) * self.ic2
        # forced response: impulse response h[0]=a2, h[t]=cb*u[t-1]+cmb*v[t-1]
        h = np.empty(m, np.float64)
        h[0] = a2
        if m > 1:
            h[1:] = cb * u[:-1] + cmb * v[:-1]
        v1 = v1 + np.convolve(x64, h)[:m]
        # advance state by m samples: A^m @ s + sum_{t=0}^{m-1} A^{m-1-t} @ B * x[t]
        ue, ve = pw[m].real, pw[m].imag / w
        ic1, ic2 = self.ic1, self.ic2
        xr = x64[::-1]
        su = float(np.dot(u, xr))
        sv = float(np.dot(v, xr))
        self.ic1 = (ue - k * ve) * ic1 + (-2.0 * ve) * ic2 + b0 * su + mb0 * sv
        self.ic2 = (2.0 * ve) * ic1 + (ue + k * ve) * ic2 + b1 * su + mb1 * sv
        return (v1 * scale).astype(F32)

    def run(self, x, rate):
        n = len(x)
        if n == 0:
            return x
        wet = np.empty(n, F32)
        i = 0
        while i < n:
            if self.rem == 0:
                self._cell = self._design(rate)
                self.phase = float((self.phase + 2 * np.pi * self.p["rate"] * self.STEP / rate)
                                   % (2 * np.pi))
                self.rem = self.STEP
            c = min(self.rem, n - i)
            assert self._cell is not None
            wet[i:i + c] = self._svf_chunk(x[i:i + c], self._cell)
            self.rem -= c
            i += c
        mix = self.p["mix"]
        m = _glide(mix if self.mix is None else self.mix, mix, n)
        self.mix = mix
        return (x * (F32(1) - m) + wet * m).astype(F32)
