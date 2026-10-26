"""Building blocks the built-in effects share: filters, delay lines, the STFT, the
pitch tracker and the chunked envelope helpers."""
from __future__ import annotations

import numpy as np
from soundboard.audio.dsp import SmoothSos, butter, matched_biquad


F32 = np.float32


def _one_pole_lowpass(hz: float, rate: int) -> np.ndarray:
    return butter(1, min(hz, rate * 0.45), btype="low", fs=rate).astype(F32)


def _glide(old: float, new: float, n: int):
    """A gain moving from `old` to `new` across an n-sample block (a scalar when it
    stays put). Applied at once, a slider dragged while you talk steps the gain at
    every block's edge: a crackle."""
    if old == new:
        return F32(new)
    return np.linspace(old, new, n + 1, dtype=F32)[1:]


def _biquad(kind: str, f0: float, rate: int, gain_db: float, q: float = 0.707) -> np.ndarray:
    """One EQ band as a (1, 6) sos row: 'peak', 'lowshelf' or 'highshelf', matched to
    its analog shape up to Nyquist (dsp.matched_biquad)."""
    return matched_biquad(kind, f0, gain_db, rate, q)[None].astype(F32)


class _Filter:
    """A filter with memory, redesigned only when its settings change. A new design
    (or None: straight through) is crossfaded in over the block, so turning a knob
    doesn't click (dsp.SmoothSos)."""

    def __init__(self):
        self.key = None
        self.sos = None
        self.f = SmoothSos()

    def run(self, x: np.ndarray, key, design) -> np.ndarray:
        if key != self.key:
            self.key, self.sos = key, design()
        return self.f.run(x, self.sos).astype(F32, copy=False)


class _Oversampled:
    """Runs a waveshaper (tanh and friends) at `factor` times the rate. A curve bent
    at the mic's own rate makes harmonics past Nyquist that fold back down as a fizz
    that isn't in tune with the voice (aliasing; measured -25 dB on a 1 kHz tone at
    36 dB drive). Up here the harmonics have room, and the way back down cuts them
    off. Both ways are one windowed-sinc lowpass with memory, so blocks join without
    a seam whatever their size. Delay: (TAPS - 1) / factor samples (about 0.25 ms)."""

    TAPS = 48

    def __init__(self, rate: int, factor: int = 4):
        self.factor = factor
        n = np.arange(self.TAPS) - (self.TAPS - 1) / 2
        cut = 0.45 / factor            # of the oversampled rate: the voice's own band
        h = 2 * cut * np.sinc(2 * cut * n) * np.kaiser(self.TAPS, 8.0)
        self.h = (h / h.sum()).astype(F32)
        self._up = np.zeros(self.TAPS - 1, F32)       # the lowpasses' memory
        self._down = np.zeros(self.TAPS - 1, F32)

    def run(self, x: np.ndarray, shape) -> np.ndarray:
        """`shape(z)` bends the upsampled block z (len(x) * factor samples)."""
        n, L, keep = len(x), self.factor, self.TAPS - 1
        if n == 0:
            return x
        z = np.zeros(n * L, F32)
        z[::L] = x * F32(L)
        buf = np.concatenate([self._up, z])
        up = np.convolve(buf, self.h, "valid")
        self._up = buf[-keep:]
        y = shape(up.astype(F32, copy=False))
        buf = np.concatenate([self._down, y])
        down = np.convolve(buf, self.h, "valid")
        self._down = buf[-keep:]
        return down[::L].astype(F32, copy=False)

    def latency(self, rate: int) -> float:
        return (self.TAPS - 1) / self.factor / rate


def _shift_in(h: np.ndarray, x: np.ndarray) -> None:
    """History `h` (newest last) moves on by len(x) samples, `x` landing at its end,
    in place. Shifted as one flat run: numpy copies an overlapping 2-D slice through
    a temporary (an allocation every block), a 1-D one in place. `h` is C-contiguous
    (np.zeros, only ever written in place), so reshape(-1) is a view of it."""
    n = len(x)
    if n >= len(h):
        h[:] = x[n - len(h):]
        return
    f = h.reshape(-1)
    k = f.size // len(h) * n
    f[:-k] = f[k:]
    h[-n:] = x


class _Line:
    """A delay line of `d` samples, as a ring: take() the oldest c (c <= d), then
    put() c new ones in their place. Was a np.concatenate of the whole line per
    block (a 1 s echo copied 190 KB every few ms)."""

    def __init__(self, d: int):
        self.buf = np.zeros(d, F32)
        self.at = 0     # the oldest sample

    def __len__(self) -> int:
        return len(self.buf)

    def take(self, c: int) -> np.ndarray:
        """The oldest c samples (a view when they don't wrap: use before put)."""
        a, d = self.at, len(self.buf)
        if a + c <= d:
            return self.buf[a:a + c]
        return np.concatenate([self.buf[a:], self.buf[:a + c - d]])

    def put(self, v: np.ndarray) -> None:
        """Replace the oldest len(v) samples with v (the newest)."""
        a, d, c = self.at, len(self.buf), len(v)
        k = min(c, d - a)
        self.buf[a:a + k] = v[:k]
        if c > k:
            self.buf[:c - k] = v[k:]
        self.at = (a + c) % d

    def resized(self, d: int) -> _Line:
        """A line of d samples holding this one's newest ones (silence before them if
        it's longer). A fresh empty line cut the echo off mid-tail (a click) and left
        it silent for as long as a slider was being dragged."""
        new = _Line(d)
        old = np.roll(self.buf, -self.at)          # oldest first
        k = min(d, len(old))
        new.buf[d - k:] = old[len(old) - k:]
        return new

    def take_after(self, old: _Line | None, c: int) -> np.ndarray:
        """take(c) just after a resize: crossfaded from what `old` (the line before it)
        would have given, so the echo glides from one point in the past to the other
        instead of jumping (a click at every step of a dragged slider)."""
        y = self.take(c)
        if old is None:
            return y
        k = min(c, len(old))
        y = y.copy()
        y[:k] += (old.take(k) - y[:k]) * np.linspace(1, 0, k, endpoint=False, dtype=F32)
        return y


class _Stft:
    """Streaming short-time Fourier processing for one mono stream: `run(x, fn)`
    cuts the input into Hann-windowed frames (hop = n/4), hands all the frames that
    are ready to fn((frames, bins) complex) -> same shape, and overlap-adds the
    result. Always returns len(x) samples; the delay is exactly n samples (one frame,
    because a frame can only be processed once all of it has arrived)."""

    def __init__(self, n: int):
        self.n = n = max(64, n - n % 4)
        self.hop = n // 4
        self.win = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n) / n)).astype(F32)
        self.norm = F32(self.hop / float(np.sum(self.win ** 2)))
        self.buf = np.zeros(n - self.hop, F32)     # the last frame's overlap
        self.acc = np.zeros(n, F32)                 # overlap-add still being summed
        self.out = np.zeros(self.hop, F32)          # finished output, not yet handed back

    def run(self, x: np.ndarray, fn) -> np.ndarray:
        n, hop = self.n, self.hop
        buf = np.concatenate([self.buf, x])
        frames = (len(buf) - n) // hop + 1 if len(buf) >= n else 0
        done = [self.out]
        if frames > 0:
            idx = np.arange(n)[None, :] + hop * np.arange(frames)[:, None]
            spec = np.fft.rfft(buf[idx] * self.win, axis=1)
            y = np.fft.irfft(fn(spec), n, axis=1).astype(F32) * (self.win * self.norm)
            acc = np.concatenate([self.acc, np.zeros(hop * frames, F32)])
            for f in range(frames):
                acc[f * hop:f * hop + n] += y[f]
            done.append(acc[:hop * frames])
            self.acc = acc[hop * frames:].copy()
            buf = buf[hop * frames:]
        self.buf = buf.copy()
        out = np.concatenate(done)
        self.out = out[len(x):].copy()
        return out[:len(x)]


def _stft_size(rate: int, seconds: float) -> int:
    return max(64, int(rate * seconds) // 4 * 4)


class _Stage:
    """An _Stft stage that can start and stop mid-stream. A new _Stft puts out
    silence for its first frame, so one switched on while you talk left a 10-20 ms
    hole, then the voice jumped back in. Here the voice goes past it untouched until
    its output is real, then crossfades over (XF samples); switched off, it fades
    back to the untouched voice before it is dropped (`on` turns False)."""

    def __init__(self, n: int, xf: int):
        self.stft = _Stft(n)
        self.n, self.hop = self.stft.n, self.stft.hop
        self.xf = max(1, xf)
        self.wait = self.n       # samples until its output is the voice, not silence
        self.g = 0.0             # 0 = untouched voice, 1 = the stage's output
        self.on = True

    def run(self, x: np.ndarray, fn, want: bool = True) -> np.ndarray:
        n = len(x)
        z = self.stft.run(x, fn)
        target = 1.0 if want else 0.0
        if self.g == target and (self.wait <= 0 or not want):
            if not want:
                self.on = False
                return x
            return z
        k = np.maximum(np.arange(1, n + 1) - self.wait, 0)
        self.wait = max(0, self.wait - n)
        step = (1.0 / self.xf) * (1 if target > self.g else -1)
        env = np.clip(self.g + step * k, 0.0, 1.0).astype(F32)
        self.g = float(env[-1]) if n else self.g
        if not want and self.g <= 0.0:
            self.on = False
        return x + (z - x) * env


class _PitchTracker:
    """The voice's pitch, block by block (YIN on the last ~32 ms, decimated to about
    12 kHz so it costs next to nothing). `update(x)` returns Hz, or 0 while there's
    no clear pitch (silence, breath, s and f sounds)."""

    LO_HZ, HI_HZ = 65.0, 1000.0

    def __init__(self, rate: int):
        self.dec = max(1, int(rate // 12000))
        self.sr = rate / self.dec
        self.tmin = max(2, int(self.sr / self.HI_HZ))
        self.tmax = int(self.sr / self.LO_HZ) + 1
        self.hist = np.zeros(2 * self.tmax * self.dec, F32)
        self.f0 = 0.0

    @property
    def window(self) -> int:
        """Input samples one measurement looks at."""
        return len(self.hist)

    def update(self, x: np.ndarray) -> float:
        _shift_in(self.hist, x)
        return self.measure(self.hist)

    def measure(self, h: np.ndarray) -> float:
        """Pitch of exactly `window` samples."""
        w = h.reshape(-1, self.dec).mean(axis=1).astype(np.float64)
        w -= w.mean()
        if float(np.sqrt(np.mean(w * w))) < 3e-4:      # quiet headset speech still has pitch
            self.f0 = 0.0
            return 0.0
        tmax, size = self.tmax, len(w) - self.tmax
        cs = np.concatenate([[0.0], np.cumsum(w * w)])
        e0 = cs[size]
        et = cs[size:size + tmax] - cs[:tmax]          # energy of w[t : t + size]
        m = 1 << int(np.ceil(np.log2(len(w) + size)))
        r = np.fft.irfft(np.fft.rfft(w, m) * np.conj(np.fft.rfft(w[:size], m)), m)[:tmax]
        d = np.maximum(e0 + et - 2 * r, 0.0)
        d[0] = 0.0
        cm = d[1:] * np.arange(1, tmax) / np.maximum(np.cumsum(d[1:]), 1e-12)
        cm = np.concatenate([[1.0], cm])
        cand = np.flatnonzero(cm[self.tmin:] < 0.2)
        if len(cand):
            t = int(cand[0]) + self.tmin
            while t + 1 < tmax and cm[t + 1] < cm[t]:
                t += 1
        else:
            t = int(np.argmin(cm[self.tmin:])) + self.tmin
            if cm[t] > 0.35:
                self.f0 = 0.0
                return 0.0
        if 0 < t < tmax - 1:                            # parabolic: between two lags
            a, b, c = cm[t - 1], cm[t], cm[t + 1]
            den = a - 2 * b + c
            tt = t + (0.5 * (a - c) / den if abs(den) > 1e-12 else 0.0)
        else:
            tt = float(t)
        self.f0 = self.sr / tt
        return self.f0


def _chunks(n: int, size: int) -> np.ndarray:
    """Where each `size`-sample chunk of an n-sample block starts (the last may be
    short)."""
    return np.arange(0, n, size)


def _per_chunk(x: np.ndarray, starts: np.ndarray, how) -> np.ndarray:
    """`how` (np.maximum / np.add ...) reduced over each chunk of x."""
    return how.reduceat(x, starts)


def _envelope(target: np.ndarray, g: float, lengths: np.ndarray, rate: int,
              attack_s: float, release_s: float) -> np.ndarray:
    """A gain chasing `target` chunk by chunk from `g`: down at the attack speed,
    up at the release speed. A few chunks per block: a short loop."""
    out = np.empty(len(target), np.float64)
    for k, (t, m) in enumerate(zip(target, lengths)):
        tau = attack_s if t < g else release_s
        g = t + (g - t) * np.exp(-m / (rate * tau))
        out[k] = g
    return out


def _spread(g0: float, g: np.ndarray, ends: np.ndarray, n: int) -> np.ndarray:
    """A per-sample gain: `g0` at the block's start, `g[k]` at the end of chunk k
    (`ends`), straight lines between."""
    return np.interp(np.arange(1, n + 1), np.concatenate([[0], ends]),
                     np.concatenate([[g0], g])).astype(F32)
