"""Built-in voice effects: plain numpy DSP (filters from soundboard.dsp), cheap enough
for the mic callback.

Every effect works on 1-D float32 blocks and keeps its own memory between blocks.
Recursive delays (echo, reverb) are computed in chunks no longer than their delay,
so each chunk only depends on output that already exists: whole-array numpy maths
instead of a per-sample Python loop.

The effects run in the order they are registered here (pitch first, room last):
a voice is shaped, then squashed, then band-limited and driven, then put in a
space. The presets at the bottom are built from these building blocks.
"""
from __future__ import annotations

import collections
import math
from typing import TYPE_CHECKING

import numpy as np
from soundboard.dsp import (SmoothSos, butter, hermite, lfilter, matched_biquad,
                             running_min, sosfilt, sosfilt_bank)
from soundboard.i18n import _
from soundboard.voicefx import Effect, Param, register

if TYPE_CHECKING:
    from soundboard.voicefx.backdrop import Beds

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
        up = np.convolve(np.concatenate([self._up, z]), self.h, "valid")
        self._up = np.concatenate([self._up, z])[-keep:]
        y = shape(up.astype(F32, copy=False))
        down = np.convolve(np.concatenate([self._down, y]), self.h, "valid")
        self._down = np.concatenate([self._down, y])[-keep:]
        return down[::L].astype(F32, copy=False)

    def latency(self, rate: int) -> float:
        return (self.TAPS - 1) / self.factor / rate



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
        h, n = self.hist, len(x)
        if n >= len(h):
            h[:] = x[n - len(h):]
        else:
            h[:-n] = h[n:]
            h[-n:] = x
        return self.measure(h)

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


def _snap(hz: float) -> float:
    """The nearest note (equal temperament, A = 440 Hz)."""
    return 440.0 * 2.0 ** (round(12 * np.log2(hz / 440.0)) / 12)


def _envelope_shift(spec: np.ndarray, factor: float, lifter: int) -> np.ndarray:
    """Move each frame's spectral envelope (the voice's formants: the size and shape
    of the throat and mouth) by `factor` along the frequency axis while keeping its
    fine structure (the pitch's harmonics). The envelope is the low part of the
    cepstrum; each bin is scaled by envelope(f / factor) / envelope(f)."""
    n = 2 * (spec.shape[1] - 1)
    logm = np.log(np.abs(spec) + 1e-7)
    cep = np.fft.irfft(logm, n, axis=1)
    cep[:, lifter:n - lifter + 1] = 0.0
    env = np.fft.rfft(cep, axis=1).real
    k = np.arange(spec.shape[1]) / factor
    i0 = np.minimum(k.astype(np.int64), spec.shape[1] - 1)
    i1 = np.minimum(i0 + 1, spec.shape[1] - 1)
    f = np.minimum(k - i0, 1.0)
    warped = env[:, i0] * (1 - f) + env[:, i1] * f
    return spec * np.exp(np.clip(warped - env, -3.5, 3.5))


# --------------------------------------------------------------------------- clean-up

@register
class Cleanup(Effect):
    """Your mic, cleaned before any other effect touches it: rumble below 80 Hz
    filtered out, a noise gate that closes between words (it learns your room's
    noise level by itself), and hiss removal (a spectral filter that learns the
    noise's sound while you're quiet). Pitch shifting and distortion turn steady
    noise into warble and fizz, so this is most of what makes a changed voice
    sound clean."""

    type = "cleanup"
    name = "Clean up my mic"
    description = "Removes hum, hiss and room noise before the other effects."
    params = (Param("gate", "Noise gate", 0, 1, 0.6, "", 0, ("off", "strong")),
              Param("hiss", "Hiss removal", 0, 1, 0.5, "", 0, ("off", "strong")))

    SUB_S = 0.0025      # the gate decides every 2.5 ms
    HOLD_S = 0.2        # and stays open this long after you stop
    FLOOR_S = 1.5       # the room's noise: the quietest moment this far back
    FRAME_S = 0.0107    # hiss removal's frame (its added latency): 512 at 48 kHz
    CREEP_DB = 3.0      # how fast (dB/s) the noise estimate rises while you talk

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        rate = rate or 48000
        self.hp = _Filter()
        self.sub = max(16, int(rate * self.SUB_S))
        self.floor_db = -70.0
        self.mins: list[tuple[float, float]] = []   # (seconds, quietest dB) per block
        self.open = False
        self.held = 0.0
        self.g = 1.0
        self.stft: _Stage | None = None
        self.noise: np.ndarray | None = None   # the noise's power per frequency
        self.prev_gain: np.ndarray | None = None
        self.creep = 1.0

    def latency(self) -> float:
        if self.p["hiss"] <= 0:
            return 0.0
        return (self.stft.n if self.stft else _stft_size(self.rate, self.FRAME_S)) / self.rate

    def _gate(self, x, rate):
        """Downward expander, decided per 2.5 ms piece and ramped sample by sample."""
        strength = self.p["gate"]
        n, sub = len(x), self.sub
        pieces = max(1, n // sub)
        edges = np.linspace(0, n, pieces + 1).astype(int)
        lv = np.array([np.sqrt(np.mean(x[a:b] ** 2) + 1e-12)
                       for a, b in zip(edges[:-1], edges[1:])])
        db = 20 * np.log10(lv)
        dt = n / rate
        # the noise floor: the quietest moment of the last FLOOR_S (between words you
        # always drop to the room's noise), so it learns a noisy room straight away
        # and follows it if it gets louder or quieter
        self.mins.append((dt, max(float(db.min()), -90.0)))
        span = sum(t for t, _ in self.mins)
        while len(self.mins) > 1 and span - self.mins[0][0] >= self.FLOOR_S:
            span -= self.mins.pop(0)[0]
        self.floor_db = min(min(m for _, m in self.mins), -38.0)
        open_at, close_at = max(self.floor_db + 9, -60), max(self.floor_db + 5, -64)
        closed_g = 10 ** (-30 * strength / 20)
        gains = np.empty(pieces)
        g = self.g
        for i, d in enumerate(db):
            piece = (edges[i + 1] - edges[i]) / rate
            if d > open_at:
                self.open, self.held = True, 0.0
            elif self.open and d < close_at:
                self.held += piece
                if self.held > self.HOLD_S:
                    self.open = False
            target = 1.0 if self.open else closed_g
            tau = 0.002 if target > g else 0.06
            g = target + (g - target) * np.exp(-piece / tau)
            gains[i] = g
        ramp = np.interp(np.arange(n), np.r_[-1, edges[1:] - 1], np.r_[self.g, gains])
        self.g = float(g)
        return (x * ramp).astype(F32)

    def _dehiss(self, spec):
        strength = self.p["hiss"]
        power = (spec.real ** 2 + spec.imag ** 2).astype(np.float64)
        noise = self.noise
        if noise is None:   # start low: what you say first mustn't count as noise
            noise = power.mean(axis=0) * 1e-3 + 1e-12
        frame_db = 10 * np.log10(power.mean(axis=1) + 1e-20)
        out = np.empty_like(spec)
        over = 1.0 + strength            # subtract a bit more than the estimate
        floor = 10 ** (-18 * strength / 20)
        for f in range(len(spec)):
            noise_db = 10 * np.log10(noise.mean() + 1e-20)
            gated = self.p["gate"] > 0 and not self.open
            if gated or frame_db[f] < noise_db + 3:   # quiet: learn the noise
                noise = 0.9 * noise + 0.1 * power[f]
            else:   # creeps up (~3 dB/s), so a louder room is learned even mid-talk
                noise *= self.creep
            self.noise = noise
            g = np.maximum(1 - over * noise / (power[f] + 1e-20), floor)
            g = np.convolve(g, (0.25, 0.5, 0.25), "same")     # less "musical noise"
            if self.prev_gain is not None:
                g = np.maximum(g, 0.6 * self.prev_gain)      # fades out, never snaps
            self.prev_gain = g
            out[f] = spec[f] * g
        return out

    def run(self, x, rate):
        y = self.hp.run(x, "hp", lambda: butter(2, 80, btype="high", fs=rate).astype(F32))
        if self.p["gate"] > 0:
            y = self._gate(y, rate)
        else:
            self.open = True
        want = self.p["hiss"] > 0
        if want and self.stft is None:
            self.stft = _Stage(_stft_size(rate, self.FRAME_S), int(rate * 0.01))
            # per frame, so the rise is CREEP_DB a second at any rate
            self.creep = 10 ** (self.CREEP_DB / 10 * self.stft.hop / rate)
        if self.stft is not None:   # (at 0 it fades out first: dropping it jumped 10 ms)
            y = self.stft.run(y, self._dehiss, want)
            if not self.stft.on:
                self.stft = None
        return y


# --------------------------------------------------------------------------- pitch

@register
class PitchShift(Effect):
    """Time-domain pitch shifter (WSOLA, the SoundTouch approach).

    The voice is first time-stretched by the pitch ratio: it is cut into short
    overlapping sequences, and each one is spliced onto the previous at the
    offset where the two waveforms line up best (a cross-correlation search), so
    the splices fall on the voice's own period and don't beat against it. Then
    the stretched audio is resampled back to the original length, which moves
    the pitch and the formants together (the chipmunk / giant sound people expect
    from a voice changer). Latency is about SEQ + SEEK + one block, ~50 ms.

    Natural sound and Voice size move the formants on their own (_envelope_shift,
    one more ~20 ms frame): Natural 100% puts them back where your own voice has
    them, so a pitch change sounds like another person rather than a cartoon, and
    Voice size makes the throat behind the voice bigger or smaller (below 100% Mix,
    "Voice size on my voice too" reshapes the blended-in own voice as well, in its own
    frame; off for saves from before it). Both at 0 (the default, and what sounds and
    music use) skip that stage entirely.

    Autotune snaps the voice to the nearest note: a pitch tracker on the input picks
    the correction, which glides in (slow: natural tuning) or jumps (100%: the hard
    T-Pain effect).

    While bypassed (0 st) it keeps the last HIST_S of input, and switching on
    stretches that first, so the output doesn't go silent for the latency.
    Switching on or off crossfades dry <-> wet over XF_MS (no click).
    """

    type = "pitch"
    name = "Pitch"
    description = ("Higher or lower; a cartoon or a real-sounding person; a bigger or "
                   "smaller throat; autotune.")
    params = (Param("semitones", "Pitch", -12, 12, 0, " st", 0.5, ("lower", "higher")),
              Param("natural", "Natural sound", 0, 1, 0, "", 0, ("cartoon", "real person")),
              Param("size", "Voice size", -12, 12, 0, "", 0.5, ("smaller", "bigger")),
              Param("tune", "Autotune", 0, 1, 0, "", 0, ("off", "robotic")),
              Param("mix", "Mix", 0, 1, 1),
              Param("gap", "Gap between voices", 0, 1, 1, "", 0, ("together", "echo")),
              Param("blur", "Blur on the new voice", 0, 1, 0, "", 0, ("clear", "blurry")),
              Param("under", "Voice size on my voice too", 0, 1, 0, "", 0,
                    ("new voice only", "mine too")))

    SEQ_MS = 30.0       # one sequence of voice, copied to the output
    SEEK_MS = 10.0      # how far the splice point may move to line up
    OVL_MS = 7.0        # crossfade between one sequence and the next
    XF_MS = 10.0        # dry <-> wet crossfade when it switches on or off
    HIST_S = 0.35       # input kept while bypassed (enough to prime it at -24 st)
    FORMANT_S = 0.02    # the formant stage's frame (its added latency)
    LIFTER_S = 0.0011   # cepstrum kept as the envelope: shorter than any voice's period
    GAP_MAX_S = 0.15    # longest the blended-in voice can be held back to line up
    GAP_PER_OCTAVE_S = 0.0073   # the shifted voice's extra delay per octave down
    BLUR_SIZE, BLUR_TONE = 0.0, 9000.0   # the room Blur puts round the shifted voice: small
    BLUR_SCOOP_HZ, BLUR_SCOOP_DB = 500.0, 20.0   # ...minus its middle

    def __init__(self, rate, values=None, channels: int = 0):
        """channels: 0 for a mono voice ((n,) blocks); 2 for stereo (n, 2) blocks, cut
        and spliced at the same places in both channels (the engine's live pitch on
        music: channels spliced on their own smear the stereo picture, and flange
        once a call folds them to mono)."""
        super().__init__(rate, values)
        self.shape = (channels,) if channels else ()
        self.seq = int(rate * self.SEQ_MS / 1000)
        self.seek = int(rate * self.SEEK_MS / 1000)
        self.ovl = int(rate * self.OVL_MS / 1000)
        self.fade_in = np.linspace(0, 1, self.ovl, endpoint=False, dtype=F32)
        if channels:
            self.fade_in = self.fade_in[:, None]
        self.fade_out = F32(1) - self.fade_in
        self.aa = _Filter()
        self.aa.f.fresh = False     # first switched on mid-voice: fade in from unfiltered
        self.running = False
        self.hist = np.zeros((int(rate * self.HIST_S),) + self.shape, F32)
        self.xf = max(1, int(rate * self.XF_MS / 1000))
        self.wet_g = 0.0        # 0 = dry, 1 = wet
        self.ratio, self.mix = 1.0, 1.0
        self.formant = 1.0      # formant correction applied after the shift (1 = none)
        self.fstage: _Stage | None = None
        self.dstage: _Stage | None = None   # Voice size on the unshifted voice (Mix < 100%)
        self.dhist = np.zeros((int(rate * self.GAP_MAX_S),) + self.shape, F32)   # blended-in
        self.held = None        # ...and how far back it is read (samples) last block
        self.blend = False      # Mix has been under 100%: keep that path going
        self.mix_g = None       # the Mix applied last block
        self.verb: Reverb | None = None     # Blur: a reverb on the shifted voice only
        self.lifter = max(8, int(rate * self.LIFTER_S))
        self.tracker: _PitchTracker | None = None
        self.tune_st = 0.0      # autotune's correction right now, in semitones
        self._reset(1.0)

    def _need(self, tempo: float) -> int:
        """Input the stretcher needs on hand before it can cut the next sequence."""
        return max(self.seek + self.seq, int((self.seq - self.ovl) * tempo) + 2)

    def _reset(self, ratio: float):
        self.inb = np.zeros((0,) + self.shape, F32)   # mic audio waiting to be stretched
        self.mid = np.zeros((self.ovl,) + self.shape, F32)   # the last sequence's tail
        self.skip = 0.0                         # fractional input position carried over
        # The stretcher can only start once it has a sequence's worth of input, so the
        # resampler starts that far behind (the effect's latency); the head start is
        # exactly what keeps it fed afterwards, whatever the mic's block size.
        # (autotune moves the ratio as you talk: a little more head start for that)
        head = self._need(1 / ratio) * ratio * (1.08 if self.p.get("tune", 0) > 0 else 1.0)
        # (its first sample is the one before the resampler's position: _resample)
        self.stretched = np.zeros((int(head) + 5,) + self.shape, F32)
        self.rs_phase = 0.0
        self.pads = 0                           # times the resampler still had to wait
        self.slows = 0                          # ...or read slower to keep up

    def _stretch(self, tempo: float) -> list[np.ndarray]:
        """Consume `inb`, producing (seq - ovl)-sample chunks at 1/tempo the speed."""
        seq, ovl, seek = self.seq, self.ovl, self.seek
        body = seq - ovl
        need = self._need(tempo)
        out = []
        while len(self.inb) >= need:
            cand = self.inb[:seek + ovl]
            if cand.ndim == 1:
                corr = np.correlate(cand, self.mid, "valid")      # seek + 1 candidates
                cs = np.cumsum(cand.astype(np.float64) ** 2)
            else:   # all channels together: one splice point for all of them
                corr = sum(np.correlate(cand[:, c], self.mid[:, c], "valid")
                           for c in range(cand.shape[1]))
                cs = np.cumsum((cand.astype(np.float64) ** 2).sum(1))
            energy = cs[ovl - 1:] - np.concatenate([[0.0], cs[:seek]])
            k = int(np.argmax(corr / np.sqrt(energy + 1e-9)))
            s = self.inb[k:k + seq]
            out.append(self.mid * self.fade_out + s[:ovl] * self.fade_in)
            out.append(s[ovl:body])
            self.mid = s[body:].copy()
            adv = body * tempo + self.skip
            i = int(adv)
            self.skip = adv - i
            self.inb = self.inb[i:]
        return out

    def _resample(self, ratio: float, n: int) -> np.ndarray:
        """n samples read from `stretched` at `ratio` (cubic: linear dulled the top
        and left images). stretched[0] is the sample before position 0."""
        buf, ph = self.stretched, self.rs_phase
        need = int(1 + ph + (n - 1) * ratio) + 3
        if len(buf) < need and n > 1:
            # the stretcher is a little behind: the pitch went up while you talked
            # (a slider, or autotune snapping up a note) and the head start was sized
            # for the old one. Read this block a touch slower so it fits, instead of
            # leaving a hole of silence (a click); that also rebuilds the head start.
            fit = (len(buf) - 4.01 - ph) / (n - 1)
            if fit >= 0.5 * ratio:
                ratio = fit
                need = int(1 + ph + (n - 1) * ratio) + 3
                self.slows += 1
        if len(buf) < need:                      # the stretcher isn't ahead yet: wait
            buf = np.concatenate([buf, np.zeros((need - len(buf),) + buf.shape[1:], F32)])
            self.pads += 1
        pos = 1 + ph + ratio * np.arange(n, dtype=np.float64)
        i = pos.astype(np.int64)
        f = (pos - i).astype(F32)
        if buf.ndim == 2:
            f = f[:, None]
        y = hermite(buf[i - 1], buf[i], buf[i + 1], buf[i + 2], f)
        nph = ph + n * ratio
        cut = int(nph)
        self.stretched, self.rs_phase = buf[cut:], nph - cut
        return y

    def _add_stretched(self, chunks, ratio: float, rate: int):
        new = np.concatenate(chunks)
        # about to read faster: keep aliasing out. The filter fades in and out
        # (dsp.SmoothSos) instead of switching: started cold, or with the memory it had
        # when it last stopped, it clicked as the pitch was dragged up past +0.3 st
        up = ratio > 1.02
        if up or not self.aa.f.idle:
            cut = 0.45 * rate / ratio
            new = self.aa.run(new, round(cut) if up else None, lambda: butter(
                4, cut, btype="low", fs=rate).astype(F32) if up else None)
        self.stretched = np.concatenate([self.stretched, new])

    def _remember(self, x):
        h, n = self.hist, len(x)
        if n >= len(h):
            h[:] = x[n - len(h):]
        else:
            h[:-n] = h[n:]
            h[-n:] = x

    def _prime(self, ratio: float, rate: int):
        """Start at `ratio` with the recent input already stretched, so the
        resampler's head start is real audio instead of zeros."""
        self._reset(ratio)
        # your own voice's held-back copy (Mix under 100%) starts from the recent
        # input too: from silence, the voice dropped out for the hold-back, then jumped in
        self.dhist[:] = self.hist[len(self.hist) - len(self.dhist):]
        head = len(self.stretched)
        k = self._need(1 / ratio) + int((head + self.seq) / ratio)
        self.inb = self.hist[len(self.hist) - min(k, len(self.hist)):].copy()
        chunks = self._stretch(1.0 / ratio)
        if chunks:
            self._add_stretched(chunks, ratio, rate)
        # keep what a fresh start holds after being fed len(inb) samples
        keep = max(head - int(len(self.inb) * ratio), 0)
        self.stretched = self.stretched[len(self.stretched) - keep:]

    def _target(self, x, rate) -> tuple[float, float]:
        """(pitch ratio, formant correction) for this block."""
        p = self.p
        base = 2.0 ** (p["semitones"] / 12.0)
        tune = p.get("tune", 0.0)
        if tune > 0:
            if self.tracker is None:
                self.tracker = _PitchTracker(rate)
            # the shifter plays what you said ~40 ms ago, so measure the pitch there
            tr = self.tracker
            recent = np.concatenate([self.hist, x])
            if recent.ndim == 2:
                recent = recent.mean(1)
            lag = int(self._need(1.0 / max(base, 1e-3))) - tr.window // 2
            end = min(len(recent), max(tr.window, len(recent) - max(lag, 0)))
            f0 = tr.measure(recent[end - tr.window:end])
            if f0 > 0:
                note = 12 * np.log2(f0 * base / 440.0)
                want = round(note) - note
                tau = 0.005 + 0.15 * (1 - tune)          # 100%: jumps (T-Pain)
                a = 1.0 if tune >= 0.98 else 1 - np.exp(-len(x) / (rate * tau))
                self.tune_st += (want - self.tune_st) * a
        else:
            self.tune_st = 0.0
        ratio = base * 2.0 ** (self.tune_st / 12.0)
        # where the formants should end up, relative to your own voice: following the
        # pitch (a cartoon) or staying put (a real person), then made bigger/smaller
        want = base ** (1.0 - p.get("natural", 0.0)) * 2.0 ** (-p.get("size", 0.0) / 12.0)
        return ratio, want / ratio

    def _wants_formants(self) -> bool:
        p = self.p
        base = 2.0 ** (p["semitones"] / 12.0)
        shift = base ** -p.get("natural", 0.0) * 2.0 ** (-p.get("size", 0.0) / 12)
        return abs(np.log2(shift)) > 1e-3

    def latency(self) -> float:
        p = self.p
        if not (self.running or abs(p["semitones"]) >= 0.01 or p.get("size", 0)
                or p.get("tune", 0) > 0):
            return 0.0
        ratio = 2.0 ** (p["semitones"] / 12.0)
        s = self._need(1 / ratio) / self.rate
        if self.fstage is not None or self._wants_formants():
            n = self.fstage.n if self.fstage else _stft_size(self.rate, self.FORMANT_S)
            s += n / self.rate
        return s

    def _hold_back(self, dry, rate):
        """The shifted voice comes out ~40-80 ms after your own: below 100% Mix that
        is a slapback echo under the voice. Gap between voices at 0 holds your own
        voice back by the difference so the two line up; 1 (old saves) leaves it."""
        h, n = self.dhist, len(dry)
        buf = np.concatenate([h, dry])
        self.dhist = buf[-len(h):]
        # (lower pitches come out a little later than latency(), higher ones earlier:
        # each stretched sequence plays slower or faster than it was said, ~7 ms/octave)
        lag = ((self.latency() + self.GAP_PER_OCTAVE_S * np.log2(1.0 / self.ratio)) * rate
               - (self.dstage.n if self.dstage is not None else 0))
        k = max(min(int(round((1.0 - self.p.get("gap", 1.0)) * max(lag, 0.0))), len(h)), 0)
        k0, self.held = (k if self.held is None else self.held), k
        out = buf[len(buf) - n - k:len(buf) - k]
        if k0 != k:   # Gap or Pitch moved: crossfade to the new spot (a jump clicked)
            r = np.linspace(0, 1, n + 1, dtype=F32)[1:]
            old = buf[len(buf) - n - k0:len(buf) - k0]
            out = old + (out - old) * (r[:, None] if out.ndim == 2 else r)
        return out

    def run(self, x, rate):
        p = self.p
        mix = p["mix"]
        on = (abs(p["semitones"]) >= 0.01 or abs(p.get("size", 0)) >= 0.01
              or p.get("tune", 0) > 0) and mix > 0
        if not on and not self.running:
            self._remember(x)
            return x
        if on:
            ratio, formant = self._target(x, rate)
            if not self.running:
                self.running = True
                self._prime(ratio, rate)
            self.ratio, self.mix, self.formant = ratio, mix, formant
        ratio, mix = self.ratio, self.mix       # switching off: fade out at the old ones
        self._remember(x)
        self.inb = np.concatenate([self.inb, x])
        chunks = self._stretch(1.0 / ratio)
        if chunks:
            self._add_stretched(chunks, ratio, rate)
        wet = self._resample(ratio, len(x))
        if self.fstage is None and abs(np.log2(self.formant)) > 1e-3:
            self.fstage = _Stage(_stft_size(rate, self.FORMANT_S), self.xf)
        if self.fstage is not None:   # once on, it stays on: its delay mustn't jump
            c = self.formant
            wet = self.fstage.run(wet, lambda spec: spec if abs(np.log2(c)) <= 1e-3
                                  else _envelope_shift(spec, c, self.lifter))
        blur = p.get("blur", 0.0)
        if self.verb is None and blur > 0:
            self.verb = Reverb(rate, {"size": self.BLUR_SIZE, "tone": self.BLUR_TONE, "mix": 1})
            self.verb_eq = _Filter()
        if self.verb is not None:     # once on, it stays on: its tail mustn't cut off
            # the room alone (Reverb at full Mix gives 0.4 dry + 0.8 room), with its
            # middle scooped out so the words stay clear and only lows and highs smear
            room = (self.verb.run(wet, rate) - F32(0.4) * wet) * F32(1.25)
            room = self.verb_eq.run(room, "scoop", lambda: _biquad(
                "peak", self.BLUR_SCOOP_HZ, rate, -self.BLUR_SCOOP_DB, 0.7))
            wet = wet + room * F32(blur)
        if mix < 1:
            self.blend = True
        if self.blend:
            # (once your own voice has been blended in, its held-back copy is kept
            # current even at 100% Mix: going back below read a stale one, a click.)
            # "Voice size on my voice too" reshapes the blended-in voice as well, or your
            # own voice stays recognisable under the effect (no key: old saves, as before)
            dry, d = x, 2.0 ** (-p.get("size", 0.0) * p.get("under", 0.0) / 12.0)
            if self.dstage is None and mix < 1 and abs(np.log2(d)) > 1e-3:
                self.dstage = _Stage(_stft_size(rate, self.FORMANT_S), self.xf)
            if self.dstage is not None:
                dry = self.dstage.run(x, lambda spec: spec if abs(np.log2(d)) <= 1e-3
                                      else _envelope_shift(spec, d, self.lifter))
            dry = self._hold_back(dry, rate)
            m0, self.mix_g = (mix if self.mix_g is None else self.mix_g), mix
            if mix < 1 or m0 < 1:     # (glides, like every other level)
                m = _glide(m0, mix, len(x))
                if x.ndim == 2 and np.ndim(m):
                    m = np.asarray(m)[:, None]
                wet = dry * (1 - m) + wet * m
        g0, target = self.wet_g, 1.0 if on else 0.0
        if g0 == target:
            return wet
        step = (1.0 / self.xf) * (1 if target > g0 else -1)
        env = np.clip(g0 + step * np.arange(1, len(x) + 1), 0.0, 1.0).astype(F32)
        self.wet_g = float(env[-1]) if len(x) else g0
        if x.ndim == 2:
            env = env[:, None]
        if not on and self.wet_g <= 0.0:
            self.running = False
            self.fstage = self.dstage = self.verb = None
            self.held = self.mix_g = None
            self.tune_st = 0.0
        return x + (wet - x) * env


# --------------------------------------------------------------------------- growl

@register
class Harmony(Effect):
    """Two more voices at set intervals from yours (a chord of you): two pitch
    shifters on copies of the voice, added back under it. Your own voice waits the
    shifters' delay in a line of its own, so the three land together; the chord
    is a touch wider than that line (a shifter's delay moves a little with its
    interval), which is what a choir does anyway."""

    type = "harmony"
    name = "Harmony"
    description = "Two more voices at intervals from yours: a chord, a choir."
    params = (Param("first", "First voice", -12, 12, 4, " st", 1, ("lower", "higher")),
              Param("second", "Second voice", -12, 12, 7, " st", 1, ("lower", "higher")),
              Param("level", "Volume", 0, 1, 0.7, "", 0, ("behind you", "as loud as you")))

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.a = PitchShift(rate, {"semitones": self.p["first"]})
        self.b = PitchShift(rate, {"semitones": self.p["second"]})
        wait = PitchShift(rate, {"semitones": -12}).latency()
        self.hist = np.zeros(max(1, int(wait * rate)), F32)    # your voice, waiting
        self.level = None

    def latency(self) -> float:
        return len(self.hist) / self.rate

    def set_values(self, values):
        super().set_values(values)
        self.a.set_values({"semitones": self.p["first"]})
        self.b.set_values({"semitones": self.p["second"]})

    def run(self, x, rate):
        n = len(x)
        if n == 0:
            return x
        full = np.concatenate([self.hist, x])
        held, self.hist = full[:n], full[-len(self.hist):]
        chord = self.a.run(x, rate) + self.b.run(x, rate)
        level = 0.5 * self.p["level"]
        g = _glide(level if self.level is None else self.level, level, n)
        self.level = level
        return (held + chord * g).astype(F32, copy=False)


@register
class Growl(Effect):
    """A second voice an octave below yours, the way an octave pedal makes one: a
    square wave that flips at every other cycle of your voice (so it runs at half
    your pitch) multiplied with the voice. No delay, nothing to track: demons and
    monsters."""

    type = "growl"
    name = "Monster growl"
    description = "Adds a rough voice an octave below yours."
    params = (Param("amount", "Growl", 0, 1, 0.5, "", 0, ("subtle", "monster")),
              Param("tone", "Tone", 300, 3000, 1200, " Hz", 50, ("dark", "raspy")))

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.track = _Filter()
        self.tone = _Filter()
        self.sign = 1.0
        self.parity = 0
        self.amount = None

    def run(self, x, rate):
        lo = self.track.run(x, "t", lambda: butter(2, 350, btype="low", fs=rate).astype(F32))
        level = float(np.sqrt(np.mean(lo * lo)) + 1e-9)
        s = np.where(np.abs(lo) > level * 0.3, np.sign(lo), 0.0)
        s[0] = s[0] or self.sign
        idx = np.where(s != 0, np.arange(len(s)), 0)
        s = s[np.maximum.accumulate(idx)]              # hold the last sign (hysteresis)
        rising = np.diff(np.r_[self.sign, s]) > 0
        flips = np.cumsum(rising) + self.parity
        sq = np.where(flips % 2 == 0, 1.0, -1.0).astype(F32)
        self.sign, self.parity = float(s[-1]), int(flips[-1] % 2)
        tone = self.p["tone"]
        sub = self.tone.run(x * sq, round(tone), lambda: butter(
            2, min(tone, rate * 0.45), btype="low", fs=rate).astype(F32))
        amount = 1.6 * self.p["amount"]
        g = _glide(amount if self.amount is None else self.amount, amount, len(x))
        self.amount = amount
        return x + sub * g


# --------------------------------------------------------------------------- robot

@register
class Robot(Effect):
    """Channel vocoder: the voice's spectral envelope, band by band, imposed on a
    buzzing synthesizer note. The words stay clear, the pitch is the buzz's: the
    classic robot / Daft Punk sound (not the ring-modulated 'dalek' garble)."""

    type = "robot"
    name = "Robot"
    description = "Your words spoken by a buzzing synthesizer (vocoder)."
    params = (Param("freq", "Buzz pitch", 40, 400, 100, " Hz", 1),
              Param("follow", "Follow my pitch", 0, 1, 0, "", 1),
              Param("noise", "Breath", 0, 1, 0.2),
              Param("mix", "Mix", 0, 1, 1))

    BANDS = 16
    LO_HZ, HI_HZ = 120.0, 7500.0
    ENV_HZ = 40.0

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        rate = rate or 48000                    # the chain builds effects before the mic opens
        hi = min(self.HI_HZ, rate * 0.42)
        edges = np.geomspace(self.LO_HZ, hi, self.BANDS + 1)
        self.bank = np.stack([butter(2, [edges[i], edges[i + 1]], btype="band", fs=rate)
                              for i in range(self.BANDS)]).astype(F32)
        self.state = None        # the bank's memory, for (voice, carrier)
        self.env_sos = butter(1, self.ENV_HZ, btype="low", fs=rate).astype(F32)
        self.env_zi = np.zeros((1, 2 * self.BANDS, 2), F32)
        self.harmonics = np.arange(1, int(hi / self.params[0].lo) + 1, dtype=np.float64)
        self.phase = 0.0
        self.rng = np.random.default_rng(1)
        self.tracker: _PitchTracker | None = None
        self.f = float(self.p["freq"])

    def _carrier(self, n: int, rate: int) -> np.ndarray:
        f, nz = self.f, self.p["noise"]
        k = self.harmonics[: int(min(self.HI_HZ, rate * 0.42) / f)]
        ph = self.phase + 2 * np.pi * f / rate * np.arange(1, n + 1)
        self.phase = float(ph[-1] % (2 * np.pi))
        saw = (np.sin(np.outer(k, ph)) / k[:, None]).sum(0) * (2 / np.pi)   # band-limited
        noise = self.rng.standard_normal(n) * 0.35
        return (saw * (1 - nz) + noise * nz).astype(F32)

    def run(self, x, rate):
        n = len(x)
        if self.p.get("follow", 0) >= 0.5:
            # talkbox: the buzz sings the note you're speaking, snapped to the scale
            if self.tracker is None:
                self.tracker = _PitchTracker(rate)
            f0 = self.tracker.update(x)
            if f0 > 0:
                self.f = min(max(_snap(f0), self.params[0].lo), self.params[0].hi)
        else:
            self.f = float(self.p["freq"])
        pair = np.stack([x, self._carrier(n, rate)])
        y, self.state = sosfilt_bank(self.bank, pair, self.state)   # (bands, 2, n)
        bands = np.concatenate([y[:, 0], y[:, 1]])                 # voice's, then carrier's
        env, self.env_zi = sosfilt(self.env_sos, np.abs(bands), zi=self.env_zi)
        gain = np.minimum(env[:self.BANDS] / (env[self.BANDS:] + F32(2e-3)), F32(20))
        wet = (gain * bands[self.BANDS:]).sum(0).astype(F32)
        mix = F32(self.p["mix"])
        return wet if mix >= 1 else x * (1 - mix) + wet * mix


# The singing monk's vowels, measured off the Delay Lama plugin's output (a held note
# on every vowel, the same on every pitch: one buzz through a vowel filter). Level in
# dB at each of _MONK_HZ, one row per vowel from "oo" (row 0) through "aa" (3) to
# "ee" (last).
_MONK_HZ = np.geomspace(60, 9000, 72).astype(F32)
_MONK_DB = np.array([
    [-36, -36, -35, -35, -34, -34, -34, -34, -34, -34, -34, -34, -33, -33, -32, -31,
     -31, -31, -30, -29, -29, -29, -28, -27, -26, -25, -24, -23, -22, -21, -18, -15,
     -8, -5, -10, -18, -21, -16, -8, -11, -21, -26, -29, -34, -38, -43, -50, -65,
     -65, -67, -64, -47, -39, -33, -17, -21, -36, -47, -38, -31, -47, -56, -34, -34,
     -56, -73, -80, -83, -83, -88, -87, -86],
    [-44, -43, -43, -42, -42, -41, -40, -40, -40, -39, -39, -39, -38, -38, -37, -36,
     -36, -35, -35, -34, -33, -32, -32, -31, -30, -29, -28, -27, -27, -26, -24, -22,
     -21, -19, -14, -5, -12, -20, -20, -11, -9, -21, -26, -30, -34, -39, -45, -56,
     -66, -64, -64, -49, -40, -34, -18, -21, -36, -47, -39, -32, -47, -56, -34, -34,
     -55, -72, -80, -81, -87, -85, -86, -84],
    [-45, -45, -44, -43, -43, -43, -43, -44, -44, -43, -42, -41, -40, -39, -38, -39,
     -39, -39, -38, -37, -36, -36, -35, -34, -33, -31, -31, -30, -30, -29, -27, -26,
     -25, -23, -19, -13, -3, -10, -19, -21, -15, -9, -18, -26, -30, -35, -40, -47,
     -56, -68, -66, -48, -40, -34, -17, -22, -36, -48, -39, -31, -47, -56, -35, -34,
     -56, -73, -80, -86, -81, -90, -87, -84],
    [-45, -45, -44, -43, -43, -42, -42, -41, -41, -40, -40, -39, -38, -38, -37, -37,
     -36, -36, -36, -35, -34, -33, -33, -32, -31, -30, -29, -29, -28, -28, -25, -24,
     -22, -20, -15, -6, -9, -16, -21, -22, -23, -22, -16, -10, -20, -28, -32, -37,
     -43, -52, -58, -48, -40, -33, -16, -22, -37, -48, -39, -31, -47, -55, -34, -34,
     -55, -73, -80, -82, -84, -87, -84, -89],
    [-36, -36, -35, -35, -34, -34, -34, -34, -34, -34, -34, -34, -33, -32, -32, -32,
     -32, -32, -31, -30, -29, -29, -28, -27, -26, -25, -24, -23, -22, -21, -19, -13,
     -7, -5, -10, -18, -22, -25, -28, -31, -33, -33, -31, -28, -22, -10, -16, -27,
     -33, -38, -51, -49, -37, -31, -14, -26, -39, -51, -38, -31, -48, -56, -34, -35,
     -56, -72, -80, -85, -87, -89, -87, -82],
    [-30, -29, -29, -28, -28, -27, -27, -28, -28, -28, -27, -27, -26, -26, -25, -25,
     -25, -25, -24, -23, -23, -22, -22, -21, -19, -16, -14, -13, -9, -3, -4, -13,
     -18, -22, -24, -27, -29, -31, -35, -39, -46, -56, -45, -39, -34, -30, -26, -12,
     -17, -29, -36, -45, -37, -28, -14, -29, -41, -52, -38, -32, -48, -56, -35, -35,
     -56, -72, -76, -82, -77, -81, -85, -86],
    [-29, -29, -29, -29, -28, -28, -27, -26, -25, -25, -24, -24, -23, -23, -22, -21,
     -20, -19, -19, -18, -17, -14, -13, -10, -5, -1, -2, -8, -14, -17, -20, -22,
     -25, -28, -30, -33, -36, -38, -41, -44, -51, -56, -54, -49, -44, -39, -34, -29,
     -20, -11, -26, -33, -34, -27, -14, -30, -41, -53, -39, -32, -47, -56, -35, -34,
     -56, -73, -80, -85, -88, -78, -89, -88],
    [-30, -30, -29, -28, -27, -26, -25, -24, -24, -23, -23, -22, -21, -20, -19, -18,
     -16, -15, -15, -14, -11, -6, -1, 0, -3, -6, -10, -15, -19, -21, -23, -25,
     -28, -31, -33, -36, -38, -41, -46, -50, -62, -74, -68, -61, -50, -44, -38, -34,
     -29, -15, -13, -29, -31, -27, -13, -29, -41, -53, -38, -31, -48, -55, -33, -33,
     -55, -73, -81, -80, -88, -81, -90, -85],
    [-28, -28, -27, -26, -25, -25, -24, -23, -22, -21, -20, -19, -19, -18, -17, -16,
     -14, -12, -9, -6, -4, -1, 0, -3, -10, -14, -16, -18, -21, -23, -24, -27,
     -29, -32, -34, -37, -40, -43, -47, -53, -64, -68, -64, -69, -54, -47, -41, -36,
     -31, -23, -10, -25, -31, -30, -15, -26, -38, -50, -39, -31, -47, -55, -34, -33,
     -55, -71, -81, -83, -86, -85, -83, -90],
    [-28, -27, -26, -25, -25, -24, -23, -22, -22, -21, -20, -19, -17, -16, -15, -14,
     -14, -12, -9, -5, -2, 0, -1, -6, -12, -15, -17, -18, -21, -24, -25, -27,
     -30, -32, -34, -38, -40, -43, -48, -54, -62, -64, -63, -70, -57, -47, -41, -36,
     -31, -24, -10, -24, -32, -32, -17, -23, -37, -48, -39, -31, -47, -55, -34, -34,
     -55, -73, -82, -83, -87, -83, -90, -90],
    [-27, -26, -26, -25, -24, -23, -23, -22, -21, -21, -20, -19, -17, -15, -14, -14,
     -14, -12, -9, -5, -1, 0, -2, -6, -12, -15, -17, -18, -20, -23, -25, -27,
     -29, -32, -34, -38, -40, -43, -48, -55, -61, -63, -61, -68, -59, -47, -42, -37,
     -31, -24, -10, -23, -32, -34, -20, -18, -35, -45, -39, -31, -47, -55, -34, -34,
     -55, -72, -81, -83, -88, -86, -85, -79],
], F32)
_MONK_LOG_HZ = np.log(_MONK_HZ)
_MONK_SCALE = np.array([0, 3, 5, 7, 10, 12])   # minor pentatonic (and the octave): any two fit


@register
class Monk(Effect):
    """A singing monk sings what you say. Your voice is only listened to: its
    loudness starts and stops his notes, every syllable is one sung "y-a" (and an
    "i" as he lets go, the way his covers sing), its pitch picks his note (snapped to
    a five-note scale around his own low note, so talking comes out as a tune), and
    how open your vowel is opens his "a" a little. His voice is a buzz shaped by
    vowel filters measured off the real monk synth, with his vibrato and glide. A bit
    of your own hiss ("Words") keeps the consonants, so you can still be followed."""

    type = "monk"
    name = "Singing monk"
    description = "A monk sings your words: your talking becomes his chant."
    params = (Param("note", "Pitch", -12, 12, 0, " st", 1, ("lower", "higher")),
              Param("follow", "Follow my tune", 0, 1, 0.55, "", 0, ("one note", "my tune")),
              Param("words", "Words", 0, 1, 0.3, "", 0, ("only singing", "clear words")),
              Param("mix", "Mix", 0, 1, 1))

    BASE_HZ = 130.81            # his note with Pitch at 0 (C3)
    VIB_HZ, VIB_DEPTH = 4.7, 0.015
    GLIDE_S = 0.025             # his slide to a new note (measured: ~60 ms end to end)
    HOLD_S = 0.1                # how long a new note must last before he takes it
    GAP_S = 0.12                # the shortest syllable he sings
    GATE = 0.004                # quieter than this (about -48 dBFS) and he stops
    EE, AA, II = 6.0, 3.0, 5.0  # his vowel rows: a syllable starts "y", sings "a",
    YA_S = 0.05                 # ... slides from "y" to "a" in this long,
                                # and closes to "i" as he lets go
    MOUTH_S = 0.06              # his mouth moves from vowel to vowel this slowly

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        rate = rate or 48000
        self.tracker = _PitchTracker(rate)
        self.spec_n = 1 << int(np.ceil(np.log2(rate * 0.021)))
        self.hist = np.zeros(self.spec_n, F32)
        self.win = np.hanning(self.spec_n).astype(F32)
        fr = np.fft.rfftfreq(self.spec_n, 1 / rate)
        self.band = (fr > 200) & (fr < 3500)
        self.band_hz = fr[self.band]
        self.hiss = _Filter()
        self.phase = self.vib = 0.0
        self.f = 0.0                # the note he's singing now (Hz; 0 = not yet)
        self.target = self.cand = 0.0
        self.cand_n = 0.0           # seconds the next note has lasted
        self.home = 0.0             # your usual pitch (semitones), learnt as you talk
        self.heard = 0              # voiced blocks it's learnt from
        self.filled = 0             # input samples the pitch tracker has seen
        self.amp = 0.0
        self.vowel = self.AA
        self.peak = self.dip = 0.0  # loudness since the last syllable (finds the next)
        self.since = 0.0            # seconds into this syllable
        self.pitched = False        # this syllable's note came from your pitch
        self.amps = None            # last block's harmonic levels (glided across)

    def _note(self, f0: float) -> float:
        """Your pitch -> his note: how far you are above or below your usual pitch,
        on a five-note scale around his own note."""
        st = 12 * np.log2(f0)
        # your middle pitch: a running median (a stray octave jump can't drag it), in
        # big steps at first, then slowly following you
        self.heard += 1
        if self.heard == 1:
            self.home = st
        else:
            self.home += np.sign(st - self.home) * max(0.02, 2.0 / self.heard ** 0.75)
        semis = (st - self.home) * self.p["follow"]
        notes = 12 * np.floor(semis / 12) + _MONK_SCALE
        step = float(notes[np.argmin(np.abs(notes - semis))])
        return self.BASE_HZ * 2 ** ((self.p["note"] + step) / 12)

    def _vowel(self) -> float:
        """Brightness of your voice -> his vowel row (0 = "oo" .. 10 = "ee")."""
        s = np.abs(np.fft.rfft(self.hist * self.win))[self.band]
        c = float((self.band_hz * s).sum() / max(float(s.sum()), 1e-9))
        return float(np.interp(np.log(max(c, 1.0)), np.log([500, 900, 2000]), [1, 3, 9]))

    def run(self, x, rate):
        n = len(x)
        if n == 0:
            return x
        h = self.hist
        if n >= len(h):
            h[:] = x[n - len(h):]
        else:
            h[:-n] = h[n:]
            h[-n:] = x
        f0 = self.tracker.update(x)
        self.filled += n
        if self.filled < self.tracker.window:
            f0 = 0.0                                     # half a window: no pitch yet
        level = float(np.sqrt(np.mean(x * x)))
        loud = level > self.GATE
        # a new syllable: sound after quiet, or loudness rising again out of a dip
        self.peak = max(self.peak, level)
        self.dip = min(self.dip, level)
        self.since += n / rate
        fresh = loud and (self.amp < self.GATE
                          or (self.since > self.GAP_S and self.dip < 0.5 * self.peak
                              and level > 2 * self.dip))
        if fresh or not loud:
            self.peak = self.dip = level
        if fresh:
            self.since = 0.0
            self.pitched = False                         # no note of yours heard in it yet
        if loud and f0 > 0:
            note = self._note(f0)
            if self.f == 0 or fresh or not self.pitched:   # a new syllable: straight there
                self.pitched = True
                self.target = self.cand = note
                if self.f == 0 or self.amp < self.GATE:
                    self.f = note
                self.cand_n = 0.0
            elif note != self.cand:
                self.cand, self.cand_n = note, n / rate
            elif note != self.target:
                self.cand_n += n / rate
                if self.cand_n >= self.HOLD_S:
                    self.target = note
        elif fresh and (self.f == 0 or self.amp < self.GATE):
            # sound with no pitch (a whisper, an "s"): he starts on his own note
            self.f = self.target = self.cand = self.BASE_HZ * 2 ** (self.p["note"] / 12)
            self.cand_n = 0.0
        if self.f == 0:
            return (x * F32(1 - self.p["mix"])).astype(F32, copy=False)
        # loudness: fast up, a little slower down (a sung note, not a gate)
        goal = level * 1.4 if loud else 0.0
        tau = 0.011 if goal > self.amp else 0.015       # measured: ~10 ms in, ~15 ms out
        k = 1 - np.exp(-n / rate / tau)
        amp0, self.amp = self.amp, self.amp + k * (goal - self.amp)
        # his vowel: "y" to "a" in YA_S (a touch less open when yours is closed),
        # "i" as he lets go
        if not loud:
            goal = self.II
        else:
            goal = self.AA + 0.35 * float(np.clip(abs(self._vowel() - 3) / 4, 0, 1))
            if self.since < self.YA_S:                    # "y..." sliding into "a"
                goal += (self.EE - goal) * (1 - self.since / self.YA_S)
        self.vowel += (1 - np.exp(-n / rate / self.MOUTH_S)) * (goal - self.vowel)
        # pitch: glide to the target, plus his vibrato
        t = np.arange(1, n + 1) / rate
        f = self.target + (self.f - self.target) * np.exp(-t / self.GLIDE_S)
        self.f = float(f[-1])
        vib = 1 + self.VIB_DEPTH * np.sin(self.vib + 2 * np.pi * self.VIB_HZ * t)
        self.vib = float((self.vib + 2 * np.pi * self.VIB_HZ * n / rate) % (2 * np.pi))
        ph = self.phase + np.cumsum(2 * np.pi * f * vib / rate)
        self.phase = float(ph[-1] % (2 * np.pi))
        # the buzz through his vowel: every harmonic at the vowel filter's level
        top = min(7000.0, rate * 0.45)       # he has next to nothing above
        k_n = max(1, int(top / (self.f * 1.03)))
        ks = np.arange(1, k_n + 1)
        lo = int(np.clip(np.floor(self.vowel), 0, len(_MONK_DB) - 2))
        a = float(np.clip(self.vowel - lo, 0, 1))
        row = _MONK_DB[lo] * (1 - a) + _MONK_DB[lo + 1] * a
        amps = 10 ** (np.interp(np.log(ks * self.f), _MONK_LOG_HZ, row) / 20)
        amps /= np.sqrt(0.5 * float((amps * amps).sum()))           # rms 1
        old = self.amps
        if old is None or len(old) != k_n:
            old = amps
        self.amps = amps
        ramp = np.linspace(0, 1, n, endpoint=False)
        wave = np.einsum("kn,kn->n", np.sin(np.outer(ks, ph)),
                         old[:, None] + (amps - old)[:, None] * ramp)
        g = np.linspace(amp0, self.amp, n, endpoint=False)
        wet = wave * g
        words = self.p["words"]
        if words > 0:
            hiss = self.hiss.run(x, ("hp", rate),
                                 lambda: butter(2, 2500, btype="high", fs=rate).astype(F32))
            wet = wet + hiss * (2.5 * words)
        mix = F32(self.p["mix"])
        wet = wet.astype(F32)
        return wet if mix >= 1 else (x * (1 - mix) + wet * mix).astype(F32)


@register
class RingMod(Effect):
    """Ring modulator: the voice multiplied by a sine. Every harmonic of the voice
    turns into a pair, one the sine's pitch above it and one below, so the voice
    loses its own pitch and takes on a metallic, bell-like one: the Dalek at about
    30 Hz, a robot bell higher up. The sine's phase runs on from block to block and
    its pitch glides across a block, so neither a block edge nor a dragged slider
    clicks."""

    type = "ringmod"
    name = "Ring modulator"
    description = "Metallic, bell-like voice: the Dalek."
    params = (Param("freq", "Pitch", 5, 2000, 30, " Hz", 1, ("rumble", "bell")),
              Param("mix", "Mix", 0, 1, 1))

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.phase = 0.0
        self.f = float(self.p["freq"])
        self.mix = None

    def run(self, x, rate):
        n = len(x)
        if n == 0:
            return x
        f, f0 = float(self.p["freq"]), self.f
        self.f = f
        hz = np.linspace(f0, f, n + 1)[1:] if f0 != f else f
        ph = self.phase + 2 * np.pi * np.cumsum(np.broadcast_to(hz, (n,)) / rate)
        self.phase = float(ph[-1] % (2 * np.pi))
        wet = x * np.sin(ph).astype(F32)
        mix = self.p["mix"]
        m = _glide(mix if self.mix is None else self.mix, mix, n)
        self.mix = mix
        return (x * (1 - m) + wet * m).astype(F32, copy=False)


# --------------------------------------------------------------------------- dynamics

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
    of the voice and not aliasing fizz, then a tone lowpass."""

    type = "distortion"
    name = "Distortion"
    description = "Overdriven, crunchy voice."
    params = (Param("drive", "Drive", 0, 36, 12, " dB", 1),
              Param("tone", "Tone", 1000, 12000, 6000, " Hz", 100),
              Param("level", "Volume", 0.05, 1, 0.5))

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.lp = _Filter()
        self.os = _Oversampled(rate)
        self.gains = (10 ** (self.p["drive"] / 20), self.p["level"])

    def latency(self) -> float:
        return self.os.latency(self.rate)

    def run(self, x, rate):
        g, level = 10 ** (self.p["drive"] / 20), self.p["level"]
        (g0, level0), n = self.gains, len(x)
        self.gains = (g, level)
        if n == 0:
            return x
        m = n * self.os.factor
        y = self.os.run(x, lambda z: np.tanh(z * _glide(g0, g, m)) * _glide(level0, level, m))
        tone = self.p["tone"]
        return self.lp.run(y, tone, lambda: _one_pole_lowpass(tone, rate))


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


# --------------------------------------------------------------------------- space

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

    def _all_combs(self, x, g, a):
        """All the combs at once, for a block no longer than the shortest delay (the
        usual case): each one's feedback is then already in its history, so the
        eight damping filters run as one call over an (8, n) array."""
        n = len(x)
        fed, zf = lfilter([1 - a], [1, -a], np.stack([h[:n] for h in self.combs]),
                          zi=np.stack(self.damp))
        v = x[None] + F32(g) * fed.astype(F32)
        for k, h in enumerate(self.combs):
            self.combs[k] = np.concatenate([h[n:], v[k]])
            self.damp[k] = zf[k]
        return v.sum(axis=0)

    def run(self, x, rate):
        if len(x) == 0:
            return x
        g = 0.7 + 0.28 * self.p["size"]
        a = float(np.exp(-2 * np.pi * self.p["tone"] / rate))
        dry, early = self._room(x, rate)
        if len(x) <= min(len(h) for h in self.combs):
            wet = self._all_combs(dry, g, a)
        else:
            wet = np.zeros_like(x)
            for k in range(len(self.combs)):
                wet += self._comb(dry, k, g, a)
        wet *= F32(0.25 * np.sqrt(1 - g * g))     # same loudness at every size
        for k, (xh, yh) in enumerate(self.aps):
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


# --------------------------------------------------------------------------- background

class _Drift:
    """A level that wanders to a new random target every `lo`-`hi` seconds, gliding
    there in a straight line: the syllables of a far-off talker, a gust of wind."""

    def __init__(self, rng, lo: float, hi: float, floor: float = 0.0):
        self.rng, self.lo, self.hi, self.floor = rng, lo, hi, floor
        self.v = self.target = floor
        self.step = 0.0
        self.left = 0

    def run(self, n: int, rate: int) -> np.ndarray:
        out = np.empty(n, F32)
        i = 0
        while i < n:
            if self.left <= 0:
                self.left = max(1, int(rate * self.rng.uniform(self.lo, self.hi)))
                self.target = self.floor + (1 - self.floor) * float(self.rng.random()) ** 1.5
                self.step = (self.target - self.v) / self.left
            c = min(n - i, self.left)
            out[i:i + c] = self.v + self.step * np.arange(1, c + 1, dtype=F32)
            self.v += self.step * c
            self.left -= c
            i += c
        return out


class _Hits:
    """Sparse random clicks, about `per_s` a second, of random loudness (raindrops on a
    window, a log cracking): an impulse train for a filter to colour."""

    def __init__(self, rng, per_s: float, spread: float):
        self.rng, self.per_s, self.spread = rng, per_s, spread

    def run(self, n: int, rate: int) -> np.ndarray:
        x = np.zeros(n, F32)
        k = self.rng.poisson(self.per_s * n / rate)
        if k:
            at = self.rng.integers(0, n, k)
            x[at] = (self.rng.random(k) ** self.spread
                     * self.rng.choice((-1.0, 1.0), k)).astype(F32)
        return x


# ---- the Effects pop-up's own copies (ui/effectspopup.py): on top of whatever voice
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
class Background(Effect):
    """Sounds around you, made live (no recordings): rain, wind, an engine, a crowd,
    a spaceship's hum, a fire. Mixed in under your voice after every other effect but
    the studio polish, so the room and radio change you, not the weather.

    Every layer is noise or a few sine waves through filters, scaled so a slider at
    the top is about as loud as a normal headset voice (RMS ~0.08). "Only while I
    talk" lets it in behind your words (a level gate with a 0.4 s hold), so nobody
    hears rain from an idle mic all game."""

    type = "backdrop"
    name = "Background"
    description = "Rain, wind, an engine, a crowd, a spaceship or a fire behind your voice."
    params = (Param("rain", "Rain", 0, 1, 0, "", 0, ("off", "pouring")),
              Param("wind", "Wind", 0, 1, 0, "", 0, ("off", "gale")),
              Param("engine", "Engine hum", 0, 1, 0, "", 0, ("off", "loud")),
              Param("crowd", "Crowd", 0, 1, 0, "", 0, ("off", "packed")),
              Param("space", "Spaceship hum", 0, 1, 0, "", 0, ("off", "loud")),
              Param("fire", "Crackling fire", 0, 1, 0, "", 0, ("off", "roaring")),
              Param("talk", "Only while I talk", 0, 1, 1, "", 1))

    LAYERS = ("rain", "wind", "engine", "crowd", "space", "fire")
    OPEN_DB = -45        # the gate's opening level (a quiet headset word is ~-35)
    HOLD_S = 0.4
    ENGINE_HZ = 46.0     # a big turboprop / truck idle
    SPACE_HZ = (55.0, 82.6, 110.4)    # slightly off harmonics: a slow beat
    LEVEL = 0.08         # a layer at the top of its slider (RMS)
    BED_RATE = 48000     # the rate loops are made at (backdrop.SR)
    # each part's gain, measured so every layer comes out at RMS ~1 before LEVEL
    GAIN = {"hiss": 1.44, "drops": 22.0, "wind": 10.4, "rumble": 6.0, "hum": 0.81,
            "crowd": 5.4, "air": 4.7, "drone": 1.2, "roar": 4.6, "pops": 58.0}

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        rng = self.rng = np.random.default_rng()
        self.f = {k: _Filter() for k in ("rain", "drops", "wind", "rumble", "fire",
                                         "pops", "space", "crowd0", "crowd1",
                                         "crowd2", "crowd3")}
        self.gust = _Drift(rng, 0.8, 3.0, floor=0.25)     # wind strength
        self.sweep = _Drift(rng, 1.5, 4.0)                # wind pitch
        self.talkers = [_Drift(rng, 0.08, 0.3, floor=0.05) for _ in range(4)]
        self.drops = _Hits(rng, 400, 2.0)
        self.pops = _Hits(rng, 40, 3.0)
        self.phase = np.zeros(6)      # engine harmonics' phases
        self.sphase = np.zeros(len(self.SPACE_HZ))
        self.t = 0.0                  # seconds since start (slow wobbles)
        self.g_gate = 0.0
        self.quiet = 0.0
        self.levels: dict = {k: 0.0 for k in self.LAYERS}   # last block's, glided
        self.pos: dict = {}          # where each loop is up to (in its own samples)
        self.beds: Beds | None = None   # loops made ahead (VoiceChain.set_beds)

    # each layer gives n samples at about RMS 1 (scaled by the slider later)
    def _noise(self, n):
        return self.rng.standard_normal(n).astype(F32)

    def _band(self, key, x, lo, hi, rate, order=2):
        hi = min(hi, rate * 0.45)
        return self.f[key].run(x, (lo, hi), lambda: butter(order, [lo, hi], btype="band",
                                                           fs=rate).astype(F32))

    def _low(self, key, x, hz, rate):
        return self.f[key].run(x, hz, lambda: butter(2, min(hz, rate * 0.45),
                                                     btype="low", fs=rate).astype(F32))

    def _rain(self, n, rate):
        hiss = self._band("rain", self._noise(n), 900, 9000, rate) * self.GAIN["hiss"]
        drops = self._band("drops", self.drops.run(n, rate), 2500, 7000, rate) * self.GAIN["drops"]
        return hiss + drops

    def _wind(self, n, rate):
        # the band's middle glides 250-900 Hz; quantised so it isn't redesigned per block
        mid = round((250 + 650 * float(self.sweep.run(n, rate)[-1])) / 25) * 25
        y = self._band("wind", self._noise(n), mid * 0.6, mid * 1.6, rate)
        return y * self.gust.run(n, rate) * self.GAIN["wind"]

    def _engine(self, n, rate):
        t = np.arange(1, n + 1) / rate
        y = np.zeros(n)
        wob = 1 + 0.004 * math.sin(2 * math.pi * 0.3 * self.t)
        for h in range(6):
            w = 2 * math.pi * self.ENGINE_HZ * (h + 1) * wob
            y += math.pow(0.7, h) * np.sin(self.phase[h] + w * t)
            self.phase[h] = (self.phase[h] + w * n / rate) % (2 * math.pi)
        rumble = self._low("rumble", self._noise(n), 220, rate) * self.GAIN["rumble"]
        return (y * self.GAIN["hum"]).astype(F32) + rumble

    def _crowd(self, n, rate):
        y = np.zeros(n, F32)
        for i, (lo, hi) in enumerate(((300, 700), (550, 1200), (900, 1900), (1700, 3200))):
            v = self._band(f"crowd{i}", self._noise(n), lo, hi, rate)
            y += v * self.talkers[i].run(n, rate)
        return y * self.GAIN["crowd"]

    def _space(self, n, rate):
        t = np.arange(1, n + 1) / rate
        y = np.zeros(n)
        for i, hz in enumerate(self.SPACE_HZ):
            w = 2 * math.pi * hz
            y += np.sin(self.sphase[i] + w * t) / (i + 1)
            self.sphase[i] = (self.sphase[i] + w * n / rate) % (2 * math.pi)
        swell = 0.8 + 0.2 * math.sin(2 * math.pi * 0.1 * self.t)
        air = self._band("space", self._noise(n), 150, 400, rate) * self.GAIN["air"]
        return (y * self.GAIN["drone"] * swell).astype(F32) + air

    def _fire(self, n, rate):
        roar = self._low("fire", self._noise(n), 500, rate) * self.GAIN["roar"]
        pops = self._band("pops", self.pops.run(n, rate), 1500, 6000, rate) * self.GAIN["pops"]
        return roar + pops

    def _gate(self, x, rate) -> float:
        """The talk gate's gain for this block (0 closed, 1 open)."""
        level = 20 * np.log10(float(np.sqrt(np.mean(x * x))) + 1e-9)
        if level > self.OPEN_DB:
            self.quiet = 0.0
        else:
            self.quiet += len(x) / rate
        want = 1.0 if self.quiet < self.HOLD_S else 0.0
        # in fast (one block), out over half a second
        if want > self.g_gate:
            self.g_gate = want
        else:
            self.g_gate = max(want, self.g_gate - len(x) / rate / 0.5)
        return self.g_gate

    def layer(self, name: str, n: int, rate: int) -> np.ndarray:
        """n samples of one built-in layer at about RMS 1 (voicefx.backdrop makes its
        loops with this too)."""
        return {"rain": self._rain, "wind": self._wind, "engine": self._engine,
                "crowd": self._crowd, "space": self._space, "fire": self._fire}[name](n, rate)

    def reseed(self, seed: int):
        """The same sound every time (tests, loops made ahead)."""
        self.rng = np.random.default_rng(seed)
        for d in (self.gust, self.sweep, *self.talkers, self.drops, self.pops):
            d.rng = self.rng

    @classmethod
    def clean_extra(cls, cfg: dict) -> dict:
        from soundboard.voicefx import backdrop
        return backdrop.clean_extra(cfg)

    def _bed(self, key, loop: np.ndarray, n: int, rate: int) -> np.ndarray:
        """The next n samples of a loop made at backdrop.SR, stepped to the mic's rate."""
        step = self.BED_RATE / rate
        pos = self.pos.get(key, 0.0)
        idx = pos + step * np.arange(n)
        i0 = idx.astype(np.int64)
        frac = (idx - i0).astype(F32)
        size = len(loop)
        a = loop[i0 % size]
        b = loop[(i0 + 1) % size]
        self.pos[key] = (pos + step * n) % size
        return a + (b - a) * frac

    def run(self, x, rate):
        n = len(x)
        if n == 0:
            return x
        beds = self.beds
        y = np.zeros(n, F32)
        for k in self.LAYERS:
            want = self.p[k]
            was = self.levels[k]
            self.levels[k] = want
            if want <= 0 and was <= 0:
                continue
            # squared: the slider's middle is a background, not half as loud as you
            g = _glide(was * was * self.LEVEL, want * want * self.LEVEL, n)
            loop = beds.layers.get(k) if beds is not None else None
            y += (self._bed(k, loop, n, rate) if loop is not None and len(loop)
                  else self.layer(k, n, rate)) * g
        seen = set()
        for sid, loop, want in (beds.sounds if beds is not None else ()):
            key = ("sound", sid)
            seen.add(key)
            was = self.levels.get(key, 0.0)
            self.levels[key] = want
            if (want <= 0 and was <= 0) or not len(loop):
                continue
            y += self._bed(key, loop, n, rate) * _glide(was * was * self.LEVEL,
                                                        want * want * self.LEVEL, n)
        for key in [k for k in self.levels if isinstance(k, tuple) and k not in seen]:
            del self.levels[key]      # a sound taken off: it starts from silence next time
            self.pos.pop(key, None)
        self.t += n / rate
        if not y.any():
            return x
        if self.p["talk"] >= 0.5:
            was = self.g_gate
            y *= _glide(was, self._gate(x, rate), n)
        return (x + y).astype(F32, copy=False)


# --------------------------------------------------------------------------- polish

@register
class Polish(Effect):
    """The last stage of a broadcast chain, after every other effect: a de-esser, a
    touch of warmth and a lookahead limiter.

    De-ess: the voice is split at 5 kHz (a Linkwitz-Riley pair: two matching
    second-order filters each way, so the two halves add back up flat; a plain
    highpass and "the rest" left most of an S in the rest), and whenever the top
    (the hiss of an S, T or SH) gets louder than the voice's recent level allows,
    only the top is turned down; the rest (the vowels) passes untouched, so it never
    dulls the voice. Read every 2 ms, instant on, 30 ms back off. "Recent level" is
    the rest's level with a slow fall (an S has no low end of its own to compare
    against).

    Warmth: a gentle tanh bend at 4x the rate (_Oversampled): soft odd harmonics on
    the loud parts, the way a tube stage adds body, with no aliasing fizz. Made up
    so a normal talking level stays where it was.

    Limiter: nothing passes the ceiling. The gain is worked out LOOK_S ahead on a
    copy of the signal while the signal itself waits that long, so the gain is
    already down when a peak arrives (no overshoot, no clip). Per sample: a running
    minimum over twice the lookahead, then a moving average over the lookahead,
    which is at or under the gain the peak needs at every sample (the window the
    average takes always contains the peak's minimum) and has no corners. A slow
    50 ms release rides under that, so a held loud note doesn't flutter."""

    type = "polish"
    name = "Studio polish"
    description = ("Tames harsh S sounds, adds warmth and keeps every peak under a "
                   "ceiling. Runs last.")
    params = (Param("deess", "De-ess", 0, 1, 0.5, "", 0, ("off", "strong")),
              Param("warmth", "Warmth", 0, 1, 0.3, "", 0, ("clean", "warm")),
              Param("ceiling", "Ceiling", -12, 0, -1, " dB", 0.5))

    SPLIT_HZ = 5000.0
    DEESS_CHUNK_S, DEESS_RELEASE_S = 0.002, 0.03
    DEESS_FLOOR, DEESS_GATE = 0.25, 10 ** (-45 / 20)   # most it cuts; quietest top it reads
    LEVEL_RISE_S, LEVEL_FALL_S = 0.005, 0.3            # the recent-level tracker
    WARM_REF = 0.3                                     # a normal talking peak, kept level
    LOOK_S, RELEASE_S = 0.0015, 0.05

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        hz = min(self.SPLIT_HZ, 0.45 * rate)
        self.top_f, self.rest_f = _Filter(), _Filter()
        self.top_sos = np.vstack([butter(2, hz, btype="high", fs=rate)] * 2).astype(F32)
        self.rest_sos = np.vstack([butter(2, hz, btype="low", fs=rate)] * 2).astype(F32)
        self.dg = 1.0                      # the de-esser's gain on the top
        self.lvl = 0.0                     # the voice's recent level (its rest band)
        self.os = _Oversampled(rate)
        self.drive = 3 * self.p["warmth"]
        self.look = max(1, int(rate * self.LOOK_S))
        self._held = np.zeros(self.look, F32)            # the signal waiting its turn
        self._need = np.ones(2 * self.look - 1, F32)     # gains needed, for the running min
        self._mins = np.ones(self.look - 1, F32)         # those minima, for the average
        self.lg = 1.0                                    # the limiter's slow release

    def latency(self) -> float:
        return self.look / self.rate + self.os.latency(self.rate)

    def _deess(self, x: np.ndarray, rate: int) -> np.ndarray:
        amount = self.p["deess"]
        n = len(x)
        top = self.top_f.run(x, "top", lambda: self.top_sos)
        rest = self.rest_f.run(x, "rest", lambda: self.rest_sos)
        if not amount and self.dg == 1.0:
            return rest + top
        starts = _chunks(n, max(1, int(rate * self.DEESS_CHUNK_S)))
        ends = np.append(starts[1:], n)
        m = ends - starts
        hi = np.sqrt(_per_chunk(top * top, starts, np.add) / m)
        lo = np.sqrt(_per_chunk(rest * rest, starts, np.add) / m)
        lvl = _envelope(lo, self.lvl, m, rate, self.LEVEL_RISE_S, self.LEVEL_FALL_S)
        self.lvl = float(lvl[-1])
        # the top may be this much of the voice's level before it's an S
        allow = 10 ** ((-3 - 12 * amount) / 20) if amount else 1e9
        need = np.minimum(1.0, allow * lvl / (hi + 1e-9))
        need = np.where(hi < self.DEESS_GATE, 1.0, np.maximum(need, self.DEESS_FLOOR))
        g = _envelope(need, self.dg, m, rate, 1e-4, self.DEESS_RELEASE_S)
        ramp = _spread(self.dg, g, ends, n)
        self.dg = float(g[-1])
        return rest + top * ramp

    @classmethod
    def _bend(cls, z: np.ndarray, d) -> np.ndarray:
        """tanh(d z) / d, made up so WARM_REF stays at WARM_REF; at d -> 0 it's z."""
        d = np.maximum(d, 1e-3)
        r = cls.WARM_REF
        return np.tanh(z * d) * (r / np.tanh(r * d))

    def _warm(self, x: np.ndarray) -> np.ndarray:
        d = 3 * self.p["warmth"]
        d0, self.drive = self.drive, d
        m = len(x) * self.os.factor
        dd = _glide(d0, d, m)
        return self.os.run(x, lambda z: self._bend(z, dd))

    def _limit(self, x: np.ndarray, rate: int) -> np.ndarray:
        n, look = len(x), self.look
        c = 10 ** (self.p["ceiling"] / 20)
        need = np.minimum(1.0, c / (np.abs(x) + 1e-9)).astype(F32)
        seq = np.concatenate([self._need, need])
        mins = running_min(seq, 2 * look) if look > 1 else need
        self._need = seq[-(2 * look - 1):] if look > 1 else self._need
        seq = np.concatenate([self._mins, mins])
        gain = np.convolve(seq, np.full(look, 1 / look, F32), "valid") if look > 1 else mins
        if look > 1:
            self._mins = seq[-(look - 1):]
        # the slow release: per lookahead-chunk minima, chased, never above `gain`
        starts = _chunks(n, look)
        ends = np.append(starts[1:], n)
        slow = _envelope(_per_chunk(gain, starts, np.minimum), self.lg, ends - starts, rate,
                         1e-5, self.RELEASE_S)
        gain = np.minimum(gain, _spread(self.lg, slow, ends, n))
        self.lg = float(slow[-1])
        held = np.concatenate([self._held, x])
        self._held = held[-look:]
        return np.clip(held[:n] * gain, -c, c).astype(F32, copy=False)

    def run(self, x, rate):
        if len(x) == 0:
            return x
        return self._limit(self._warm(self._deess(x, rate)), rate)


# --------------------------------------------------------------------------- presets

# name -> the effects that are on, with their settings (everything else is off).
# Kept short on purpose: every voice here should sound like the thing it's named
# after, straight away, on a normal headset mic. "natural": 1 keeps the voice's
# formants where a real person's would be (a different person, not a cartoon).
# Clean up my mic isn't part of any voice: it stays as you set it.
PRESETS: dict[str, dict[str, dict]] = {
    "Chipmunk":          {"pitch": {"semitones": 8},
                          "compressor": {"threshold": -24, "ratio": 2.5, "boost": 5}},
    "Deep voice":        {"pitch": {"semitones": -4, "natural": 1, "size": 2},
                          "compressor": {"threshold": -22, "ratio": 3, "boost": 6},
                          "tone": {"bass": 3, "presence": 2, "treble": -1}},
    "High voice":        {"pitch": {"semitones": 5, "natural": 1, "size": -2.5},
                          "compressor": {"threshold": -24, "ratio": 2.5, "boost": 5},
                          "tone": {"bass": -3, "presence": 2, "treble": 2}},
    "Male voice":        {"pitch": {"semitones": -5, "natural": 1, "size": 2.5},
                          "compressor": {"threshold": -22, "ratio": 3, "boost": 6},
                          "tone": {"bass": 3, "presence": 1, "treble": -1}},
    "Demon":             {"pitch": {"semitones": -6, "natural": 1, "size": 5},
                          "growl": {"amount": 0.7, "tone": 900},
                          "compressor": {"threshold": -24, "ratio": 4, "boost": 8},
                          "distortion": {"drive": 6, "tone": 3500, "level": 0.8},
                          "reverb": {"size": 0.8, "tone": 2500, "mix": 0.3}},
    "Robot":             {"robot": {"freq": 100, "noise": 0.2, "mix": 1},
                          "compressor": {"threshold": -24, "ratio": 3, "boost": 10},
                          "reverb": {"size": 0.25, "tone": 6000, "mix": 0.12}},
    "Talkbox":           {"robot": {"freq": 110, "follow": 1, "noise": 0.05, "mix": 1},
                          "compressor": {"threshold": -24, "ratio": 3, "boost": 10},
                          "chorus": {"rate": 0.6, "depth": 3, "mix": 0.3}},
    "Autotune":          {"pitch": {"semitones": 0, "tune": 1},
                          # A little tuned carrier makes hard tuning audible in speech,
                          # even when the speaker is already close to a musical note.
                          "robot": {"follow": 1, "noise": 0.05, "mix": 0.35},
                          "compressor": {"threshold": -22, "ratio": 3, "boost": 5},
                          "reverb": {"size": 0.35, "tone": 6000, "mix": 0.18}},
    "Masked caller":     {"pitch": {"semitones": -6, "natural": 0.6, "size": 2},
                          "compressor": {"threshold": -26, "ratio": 5, "boost": 8},
                          "radio": {"low": 200, "high": 5000, "drive": 6, "noise": 0.0},
                          "distortion": {"drive": 4, "tone": 4000, "level": 0.8}},
    "Anonymous":         {"pitch": {"semitones": -4, "natural": 1, "size": -4},
                          "compressor": {"threshold": -24, "ratio": 3, "boost": 11},
                          "chorus": {"rate": 0.2, "depth": 2, "mix": 0.2}},
    # the hidden detective talking through a TV, matched line by line to the show:
    # the voice and a copy 7 st down blended (deep and high at once, no one clear
    # pitch), both with a much smaller throat so it isn't your voice any more, thin
    # on bass and top, strong in the mids, and a metallic ring over it
    "Secret detective":  {"pitch": {"semitones": -7, "size": -6, "mix": 0.45, "gap": 0,
                                    "under": 1},
                          "compressor": {"threshold": -26, "ratio": 5, "boost": 9},
                          "tone": {"bass": -7, "mid": 6, "presence": 3, "treble": -11},
                          "radio": {"low": 150, "high": 6700, "drive": 0, "noise": 0.0},
                          "helmet": {"size": 1.8, "ring": 0.49, "mix": 0.84}},
    "Dark lord":         {"pitch": {"semitones": -3, "natural": 1, "size": 3},
                          "compressor": {"threshold": -26, "ratio": 4, "boost": 8},
                          "tone": {"bass": 4, "presence": 1, "treble": -3},
                          "helmet": {"size": 3, "ring": 0.6, "mix": 0.45},
                          "reverb": {"size": 0.2, "tone": 4000, "mix": 0.1}},
    "Hothead":           {"radio": {"low": 350, "high": 4000, "drive": 12, "noise": 0},
                          "shout": {"threshold": -14, "drive": 16}},
    "Alien":             {"pitch": {"semitones": 5, "mix": 0.6},
                          "compressor": {"threshold": -24, "ratio": 3, "boost": 13},
                          "chorus": {"rate": 4.0, "depth": 3, "mix": 0.6},
                          "reverb": {"size": 0.55, "tone": 8000, "mix": 0.25}},
    "Ghost":             {"pitch": {"semitones": -3},
                          "compressor": {"threshold": -24, "ratio": 3, "boost": 11},
                          "chorus": {"rate": 0.3, "depth": 8, "mix": 0.5},
                          "echo": {"delay": 300, "feedback": 0.45, "mix": 0.3, "tone": 2500},
                          "reverb": {"size": 0.9, "tone": 2500, "mix": 0.4}},
    "Walkie-talkie":     {"compressor": {"threshold": -30, "ratio": 8, "boost": 16},
                          "radio": {"low": 450, "high": 2700, "drive": 10, "noise": 0.01}},
    "Old telephone":     {"compressor": {"threshold": -25, "ratio": 4, "boost": 10},
                          "radio": {"low": 300, "high": 3400, "drive": 4, "noise": 0.002}},
    "Megaphone":         {"compressor": {"threshold": -28, "ratio": 6, "boost": 8},
                          "tone": {"bass": 0, "presence": 6, "treble": 0},
                          "radio": {"low": 500, "high": 4500, "drive": 16, "noise": 0.0},
                          "echo": {"delay": 70, "feedback": 0.15, "mix": 0.25, "tone": 3000}},
    "Stadium announcer": {"compressor": {"threshold": -26, "ratio": 5, "boost": 10},
                          "tone": {"bass": -2, "presence": 5, "treble": 0},
                          "radio": {"low": 250, "high": 6000, "drive": 4, "noise": 0.0},
                          "echo": {"delay": 420, "feedback": 0.3, "mix": 0.3, "tone": 4000},
                          "reverb": {"size": 0.85, "tone": 5000, "mix": 0.3}},
    "Cave":              {"tone": {"bass": 2, "presence": 0, "treble": -3},
                          "echo": {"delay": 350, "feedback": 0.4, "mix": 0.3, "tone": 2500},
                          "reverb": {"size": 0.95, "tone": 3000, "mix": 0.4}},
    # the singing monk (Delay Lama): he sings your words on his own low note, with
    # the chest and room his covers get (bass up, a short echo, a hall)
    "Singing monk":      {"monk": {"note": 0, "follow": 0.55, "words": 0.3, "mix": 1},
                          "tone": {"bass": 5, "mid": 0, "presence": 0, "treble": -2},
                          "echo": {"delay": 330, "feedback": 0.3, "mix": 0.16, "tone": 3000},
                          "reverb": {"size": 0.8, "tone": 5000, "mix": 0.22}},
    "Dalek":             {"ringmod": {"freq": 30, "mix": 1},
                          "compressor": {"threshold": -24, "ratio": 4, "boost": 8},
                          "radio": {"low": 250, "high": 5500, "drive": 4, "noise": 0.0},
                          "distortion": {"drive": 12, "tone": 5000, "level": 0.32}},
    "Haunted radio":     {"robot": {"freq": 100, "follow": 0, "noise": 1, "mix": 1},
                          "compressor": {"threshold": -26, "ratio": 4, "boost": 10},
                          "tone": {"bass": -4, "mid": 0, "presence": 2, "treble": 3}},
    "Underwater":        {"compressor": {"threshold": -24, "ratio": 3, "boost": 11},
                          "tone": {"bass": 3, "mid": 0, "presence": -8, "treble": -12},
                          "flanger": {"rate": 0.3, "depth": 3, "feedback": 0.5, "mix": 0.6},
                          "reverb": {"size": 0.4, "tone": 1500, "mix": 0.3}},
    "Podcast voice":     {"compressor": {"threshold": -22, "ratio": 3, "boost": 5,
                                         "attack": 8, "release": 120},
                          "tone": {"bass": 3, "presence": 3, "treble": 1},
                          "polish": {"deess": 0.5, "warmth": 0.3, "ceiling": -1}},
    # funny: slurred and mumbly, the pitch swaying a semitone or two
    "Drunk": {"pitch": {"semitones": -2, "natural": 1, "blur": 0.6},
              "wobble": {"rate": 0.7, "vibrato": 35, "tremolo": 0.35},
              "compressor": {"threshold": -24, "ratio": 3, "boost": 9},
              "tone": {"bass": 2, "mid": 0, "presence": -4, "treble": -7}},
    # a choir of you: you, a fifth and an octave above, in a hall
    "Choir": {"harmony": {"first": 7, "second": 12, "level": 1},
              "compressor": {"threshold": -24, "ratio": 3, "boost": 13},
              "chorus": {"rate": 0.8, "depth": 6, "mix": 0.5},
              "reverb": {"size": 0.9, "tone": 5000, "mix": 0.4}},
    # high, a tiny throat, nasal and gritty
    "Goblin": {"pitch": {"semitones": 5, "natural": 1, "size": -9},
               "growl": {"amount": 0.25, "tone": 1800},
               "compressor": {"threshold": -24, "ratio": 4, "boost": 0},
               "tone": {"bass": -8, "mid": 9, "presence": 4, "treble": -2},
               "distortion": {"drive": 14, "tone": 4000, "level": 0.4}},
    # an octave higher and tiny, a faint bell sparkle, shimmering, in a bright hall
    "Fairy": {"pitch": {"semitones": 12, "natural": 1, "size": -6},
              "ringmod": {"freq": 1400, "mix": 0.15},
              "compressor": {"threshold": -24, "ratio": 3, "boost": 14},
              "tone": {"bass": -8, "mid": 0, "presence": 2, "treble": 5},
              "chorus": {"rate": 3, "depth": 1.5, "mix": 0.4},
              "reverb": {"size": 0.75, "tone": 10000, "mix": 0.35}},
    # scary: a low raspy groan that sways slowly
    "Zombie": {"pitch": {"semitones": -5, "natural": 1, "size": 4},
               "growl": {"amount": 0.9, "tone": 500},
               "compressor": {"threshold": -26, "ratio": 5, "boost": 4},
               "tone": {"bass": 3, "mid": 2, "presence": -1, "treble": -3},
               "distortion": {"drive": 10, "tone": 3500, "level": 0.7},
               "wobble": {"rate": 0.5, "vibrato": 20, "tremolo": 0.25}},
    # you and a deep copy of you an octave down, just as loud
    "Evil twin": {"pitch": {"semitones": -12, "natural": 1, "size": 5, "mix": 0.5, "gap": 0},
                  "growl": {"amount": 0.35, "tone": 900},
                  "compressor": {"threshold": -24, "ratio": 4, "boost": 9},
                  "reverb": {"size": 0.5, "tone": 4000, "mix": 0.2}},
    # huge and slow-sounding: far lower, a much bigger throat, a rumble, a hall
    "Giant": {"pitch": {"semitones": -10, "natural": 1, "size": 10},
              "growl": {"amount": 0.2, "tone": 600},
              "compressor": {"threshold": -24, "ratio": 4, "boost": 7},
              "tone": {"bass": 6, "mid": 0, "presence": 0, "treble": -4},
              "reverb": {"size": 0.95, "tone": 2500, "mix": 0.35},
              "polish": {"deess": 0, "warmth": 0, "ceiling": -1}},
    # robots & sci-fi: a huge robot suit, one low steady buzz in a metal shell
    "Mecha": {"pitch": {"semitones": -5, "natural": 1, "size": 6},
              "robot": {"freq": 45, "follow": 0, "noise": 0.05, "mix": 1},
              "ringmod": {"freq": 60, "mix": 0.3},
              "compressor": {"threshold": -24, "ratio": 4, "boost": 12},
              "helmet": {"size": 6, "ring": 0.5, "mix": 0.5},
              "reverb": {"size": 0.7, "tone": 4000, "mix": 0.25},
              "polish": {"deess": 0, "warmth": 0, "ceiling": -1}},
    # a calm spaceship computer: one smooth note, a shimmer, a small room
    "Ship computer": {"pitch": {"semitones": 2, "natural": 1, "size": -2},
                      "robot": {"freq": 190, "follow": 0, "noise": 0, "mix": 0.8},
                      "compressor": {"threshold": -24, "ratio": 3, "boost": 15},
                      "tone": {"bass": -4, "mid": 0, "presence": 3, "treble": 3},
                      "chorus": {"rate": 0.5, "depth": 3, "mix": 0.4},
                      "reverb": {"size": 0.4, "tone": 8000, "mix": 0.2}},
    # radio & places: the captain on the cabin speakers, squashed, a short echo
    "Pilot": {"compressor": {"threshold": -30, "ratio": 8, "boost": 13},
              "tone": {"bass": 0, "mid": 3, "presence": 4, "treble": 0},
              "radio": {"low": 400, "high": 3500, "drive": 8, "noise": 0.004, "squelch": 1},
              "echo": {"delay": 60, "feedback": 0.2, "mix": 0.25, "tone": 3000}},
    # a cheap speaker on a pole: a tiny band, blown out, crackling and cutting in and out
    "Drive-thru speaker": {"compressor": {"threshold": -30, "ratio": 8, "boost": 6},
                           "radio": {"low": 900, "high": 2200, "drive": 20, "noise": 0.03,
                                     "squelch": 1},
                           "distortion": {"drive": 20, "tone": 2500, "level": 0.45},
                           "wobble": {"rate": 9, "vibrato": 0.5, "tremolo": 0.5}},
    # a scratchy old reel: thin and hissy, the pitch fluttering
    "Old film": {"compressor": {"threshold": -25, "ratio": 4, "boost": 10},
                 "tone": {"bass": -6, "mid": 4, "presence": 0, "treble": -4},
                 "radio": {"low": 250, "high": 3500, "drive": 4, "noise": 0.015},
                 "wobble": {"rate": 7, "vibrato": 1.5, "tremolo": 0.2},
                 "reverb": {"size": 0.2, "tone": 3000, "mix": 0.12}},
    # a huge stone hall: a long tail and a late echo
    "Cathedral": {"compressor": {"threshold": -24, "ratio": 3, "boost": 10},
                  "tone": {"bass": 1, "mid": 0, "presence": 0, "treble": -1},
                  "echo": {"delay": 380, "feedback": 0.25, "mix": 0.15, "tone": 3000},
                  "reverb": {"size": 1, "tone": 4000, "mix": 0.55, "predelay": 70}},
}

PRESET_ICONS = {"Chipmunk": "🐿️", "Deep voice": "🐻", "High voice": "🎵", "Male voice": "👨",
                "Demon": "👹", "Robot": "🤖", "Talkbox": "🎹", "Autotune": "🎤",
                "Masked caller": "🔪", "Anonymous": "🕶️", "Secret detective": "🕵️",
                "Dark lord": "⛑️",
                "Hothead": "😡", "Alien": "👽", "Ghost": "👻", "Walkie-talkie": "📻",
                "Old telephone": "☎️", "Megaphone": "📢", "Stadium announcer": "🏟️",
                "Cave": "🦇", "Singing monk": "🧘", "Dalek": "🤖", "Haunted radio": "📻",
                "Underwater": "🐠", "Podcast voice": "🎙️"}


# --------------------------------------------------------------------------- shown text

def shown_texts() -> dict[str, str]:
    """The built-in effects' names, descriptions, settings and slider-end words, and
    the built-in voices' names: English (what the code and saved settings use) -> the
    app's language. Built when asked, not at import: this module loads before the
    language is set."""
    return {
        # effects
        "Clean up my mic": _("Clean up my mic"),
        "Removes hum, hiss and room noise before the other effects.":
            _("Removes hum, hiss and room noise before the other effects."),
        "Pitch": _("Pitch"),
        "Higher or lower; a cartoon or a real-sounding person; a bigger or smaller throat; "
        "autotune.": _("Higher or lower; a cartoon or a real-sounding person; a bigger or "
                       "smaller throat; autotune."),
        "Monster growl": _("Monster growl"),
        "Adds a rough voice an octave below yours.":
            _("Adds a rough voice an octave below yours."),
        "Robot": _("Robot"),
        "Your words spoken by a buzzing synthesizer (vocoder).":
            _("Your words spoken by a buzzing synthesizer (vocoder)."),
        "Compressor": _("Compressor"),
        "Evens out your volume: quiet words louder, shouting tamed.":
            _("Evens out your volume: quiet words louder, shouting tamed."),
        "Tone": _("Tone"),
        "Bass, mid, presence and treble, like the EQ on a mixer.":
            _("Bass, mid, presence and treble, like the EQ on a mixer."),
        "Radio": _("Radio"),
        "Walkie-talkie, telephone or megaphone band-limiting.":
            _("Walkie-talkie, telephone or megaphone band-limiting."),
        "Distortion": _("Distortion"),
        "Overdriven, crunchy voice.": _("Overdriven, crunchy voice."),
        "Shout blowout": _("Shout blowout"),
        "Shout and your voice blows out like a megaphone.":
            _("Shout and your voice blows out like a megaphone."),
        "Helmet": _("Helmet"),
        "Talking inside a helmet, mask or metal box.":
            _("Talking inside a helmet, mask or metal box."),
        "Chorus": _("Chorus"),
        "Doubled, wobbling voice: subtle shimmer to full alien warble.":
            _("Doubled, wobbling voice: subtle shimmer to full alien warble."),
        "Echo": _("Echo"),
        "Repeating echo, from slapback to canyon.":
            _("Repeating echo, from slapback to canyon."),
        "Reverb": _("Reverb"),
        "Room, hall or cave.": _("Room, hall or cave."),
        "Studio polish": _("Studio polish"),
        "Background": _("Background"),
        "Rain, wind, an engine, a crowd, a spaceship or a fire behind your voice.":
            _("Rain, wind, an engine, a crowd, a spaceship or a fire behind your voice."),
        "Harmony": _("Harmony"),
        "Two more voices at intervals from yours: a chord, a choir.":
            _("Two more voices at intervals from yours: a chord, a choir."),
        "A monk sings your words: your talking becomes his chant.":
            _("A monk sings your words: your talking becomes his chant."),
        "Follow my tune": _("Follow my tune"),
        "one note": _("one note"),
        "my tune": _("my tune"),
        "Words": _("Words"),
        "only singing": _("only singing"),
        "clear words": _("clear words"),
        "Ring modulator": _("Ring modulator"),
        "Metallic, bell-like voice: the Dalek.": _("Metallic, bell-like voice: the Dalek."),
        "Flanger": _("Flanger"),
        "Sweeping, jet-plane swirl, from gentle to under water.":
            _("Sweeping, jet-plane swirl, from gentle to under water."),
        "Wobble": _("Wobble"),
        "Pitch and volume wobble: drunk, seasick, an old film.":
            _("Pitch and volume wobble: drunk, seasick, an old film."),
        "Tames harsh S sounds, adds warmth and keeps every peak under a ceiling. Runs last.":
            _("Tames harsh S sounds, adds warmth and keeps every peak under a ceiling. "
              "Runs last."),
        # settings
        "Noise gate": _("Noise gate"),
        "Hiss removal": _("Hiss removal"),
        "Natural sound": _("Natural sound"),
        "Voice size": _("Voice size"),
        "Autotune": _("Autotune"),
        "Mix": _("Mix"),
        "Gap between voices": _("Gap between voices"),
        "Blur on the new voice": _("Blur on the new voice"),
        "Voice size on my voice too": _("Voice size on my voice too"),
        "Growl": _("Growl"),
        "Buzz pitch": _("Buzz pitch"),
        "Follow my pitch": _("Follow my pitch"),
        "Breath": _("Breath"),
        "Kicks in at": _("Kicks in at"),
        "Squash": _("Squash"),
        "Boost": _("Boost"),
        "Attack": _("Attack"),
        "Release": _("Release"),
        "De-ess": _("De-ess"),
        "Warmth": _("Warmth"),
        "Ceiling": _("Ceiling"),
        "First voice": _("First voice"),
        "Second voice": _("Second voice"),
        "Feedback": _("Feedback"),
        "Vibrato": _("Vibrato"),
        "Tremolo": _("Tremolo"),
        "Bass": _("Bass"),
        "Mid": _("Mid"),
        "Presence": _("Presence"),
        "Treble": _("Treble"),
        "Low cut": _("Low cut"),
        "High cut": _("High cut"),
        "Crunch": _("Crunch"),
        "Static": _("Static"),
        "Click when I talk": _("Click when I talk"),
        "Rain": _("Rain"),
        "Wind": _("Wind"),
        "Engine hum": _("Engine hum"),
        "Crowd": _("Crowd"),
        "Spaceship hum": _("Spaceship hum"),
        "Crackling fire": _("Crackling fire"),
        "Only while I talk": _("Only while I talk"),
        "Drive": _("Drive"),
        "Volume": _("Volume"),
        "Helmet size": _("Helmet size"),
        "Metal ring": _("Metal ring"),
        "Speed": _("Speed"),
        "Depth": _("Depth"),
        "Delay": _("Delay"),
        "Repeats": _("Repeats"),
        "Size": _("Size"),
        "Brightness": _("Brightness"),
        "Pre-delay": _("Pre-delay"),
        # the words under a slider's two ends
        "off": _("off"),
        "strong": _("strong"),
        "lower": _("lower"),
        "higher": _("higher"),
        "cartoon": _("cartoon"),
        "real person": _("real person"),
        "smaller": _("smaller"),
        "bigger": _("bigger"),
        "robotic": _("robotic"),
        "together": _("together"),
        "echo": _("echo"),
        "clear": _("clear"),
        "clean": _("clean"),
        "blurry": _("blurry"),
        "new voice only": _("new voice only"),
        "mine too": _("mine too"),
        "subtle": _("subtle"),
        "monster": _("monster"),
        "dark": _("dark"),
        "raspy": _("raspy"),
        "whisper": _("whisper"),
        "yell": _("yell"),
        "tin can": _("tin can"),
        "big helmet": _("big helmet"),
        "snappy": _("snappy"),
        "soft": _("soft"),
        "quick": _("quick"),
        "slow": _("slow"),
        "warm": _("warm"),
        "behind you": _("behind you"),
        "as loud as you": _("as loud as you"),
        "rumble": _("rumble"),
        "bell": _("bell"),
        "none": _("none"),
        "resonant": _("resonant"),
        "steady": _("steady"),
        "seasick": _("seasick"),
        "flutter": _("flutter"),
        "pouring": _("pouring"),
        "gale": _("gale"),
        "packed": _("packed"),
        "roaring": _("roaring"),
        "loud": _("loud"),
        # voices (PRESETS: their English names are what settings and share codes keep)
        "Chipmunk": _("Chipmunk"),
        "Deep voice": _("Deep voice"),
        "High voice": _("High voice"),
        "Male voice": _("Male voice"),
        "Demon": _("Demon"),
        "Talkbox": _("Talkbox"),
        "Masked caller": _("Masked caller"),
        "Anonymous": _("Anonymous"),
        "Secret detective": _("Secret detective"),
        "Dark lord": _("Dark lord"),
        "Hothead": _("Hothead"),
        "Alien": _("Alien"),
        "Ghost": _("Ghost"),
        "Singing monk": _("Singing monk"),
        "Dalek": _("Dalek"),
        "Haunted radio": _("Haunted radio"),
        "Underwater": _("Underwater"),
        "Walkie-talkie": _("Walkie-talkie"),
        "Old telephone": _("Old telephone"),
        "Megaphone": _("Megaphone"),
        "Stadium announcer": _("Stadium announcer"),
        "Cave": _("Cave"),
        "Podcast voice": _("Podcast voice"),
        "Drunk": _("Drunk"),
        "Choir": _("Choir"),
        "Goblin": _("Goblin"),
        "Fairy": _("Fairy"),
        "Zombie": _("Zombie"),
        "Evil twin": _("Evil twin"),
        "Giant": _("Giant"),
        "Mecha": _("Mecha"),
        "Ship computer": _("Ship computer"),
        "Pilot": _("Pilot"),
        "Drive-thru speaker": _("Drive-thru speaker"),
        "Old film": _("Old film"),
        "Cathedral": _("Cathedral"),
    }
