"""The last stage before the virtual cable: what makes a mix survive voice chat.

Measured with the codec bench (soundboard.codecsim) and the voice chat check:

  Limiter    Opus puts peaks back up to ~2.5 dB above what went in (more on a
             brick-walled master), and the listener's decoder clips them. A
             lookahead peak limiter holds the send to CEILING_DB, turning the
             level down around a peak instead of bending the waveform (the old
             waveshaper made -30 dB of distortion whenever voice + song summed
             over full scale).
  SmartMono  Every voice chat sends one channel: Discord averages left and right,
             some games take only the left. Averaging cancels whatever is out of
             phase between the channels (a wide synth, phasey bass: measured
             -25 dB) and drops ~3 dB of wide stereo. This downmix does it first,
             per band: a band that is mostly out of phase has its right channel
             flipped before summing, and decorrelated bands get their power back
             (up to +3 dB). Identical channels come out unchanged.
  Ducker     Turns the sounds down while you talk, so your voice isn't buried under
             a song (and the sum doesn't slam the limiter).

All three are block-based numpy with no per-sample Python loops, keep their own
state, and are built for one output rate (the engine keeps one set per output).
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import minimum_filter1d
from scipy.signal import butter, sosfilt

F32 = np.float32
CEILING_DB = -3.0          # peak level sent into the cable (room for the codec's overshoot)
LOOKAHEAD_S = 0.003        # the limiter's delay: how early it sees a peak coming
RELEASE_DB_S = 40.0        # how fast its gain comes back up, dB per second
DUCK_CHOICES = (0.0, -6.0, -12.0, -20.0)   # "lower sounds while I talk": off .. a lot


class Limiter:
    """Lookahead peak limiter: never lets a sample past `ceiling`. Adds LOOKAHEAD_S
    of delay. Gain = sliding minimum of what each sample needs (over the lookahead)
    smoothed by a box filter as long as the lookahead, which provably reaches a peak's
    gain by the time the peak leaves the delay line; then a linear-in-dB release,
    done with a running minimum instead of a sample loop."""

    def __init__(self, rate: int, ceiling_db: float = CEILING_DB):
        self.rate = int(rate)
        self.ceiling = F32(10 ** (ceiling_db / 20))
        self.la = max(1, int(LOOKAHEAD_S * rate))
        self.delay = np.zeros((self.la, 2), F32)       # audio waiting to go out
        self.need = np.ones(2 * self.la, F32)          # recent per-sample needed gains
        self.box = np.ones(self.la, F32)               # the box filter's history
        self.env_db = 0.0                              # released gain at the last sample
        self.rel = RELEASE_DB_S / rate                 # dB per sample
        self.reduction_db = 0.0                        # deepest gain cut in the last block

    def process(self, x: np.ndarray) -> np.ndarray:
        n = len(x)
        if n == 0:
            return x
        la = self.la
        pk = np.max(np.abs(x), axis=1)
        need = np.minimum(F32(1), self.ceiling / np.maximum(pk, F32(1e-9))).astype(F32)
        # all needed gains so far: [older history | this block]
        hist = np.concatenate([self.need, need])
        self.need = hist[-2 * la:]
        # hold: each sample takes the smallest gain needed over the next `la` samples
        held = _forward_min(hist, la)
        # the samples whose gains are final now: the block, delayed by `la`
        held = held[len(hist) - n - la: len(hist) - la]
        # box filter of length `la` (continuous across blocks)
        seq = np.concatenate([self.box, held])
        c = np.concatenate([[0.0], np.cumsum(seq, dtype=np.float64)])
        fast = ((c[la:] - c[:-la]) / la)[1:].astype(F32)   # n values
        self.box = seq[-la:]
        # release: env_db[i] = min(fast_db[i], env_db[i-1] + rel)
        fast_db = 20 * np.log10(np.maximum(fast, F32(1e-6)))
        idx = np.arange(1, n + 1, dtype=np.float64)
        start = self.env_db
        cand = np.minimum.accumulate(np.concatenate([[start], fast_db - self.rel * idx]))
        env_db = np.minimum(cand[1:] + self.rel * idx, 0.0)
        self.env_db = float(env_db[-1])
        self.reduction_db = float(env_db.min())
        g = (10 ** (env_db / 20)).astype(F32)
        # delay the audio by `la` so the gain lands on the samples it was computed for
        buf = np.concatenate([self.delay, x.astype(F32, copy=False)])
        out = buf[:n] * g[:, None]
        self.delay = buf[n:]
        return np.minimum(np.maximum(out, -self.ceiling), self.ceiling)


def _forward_min(x: np.ndarray, la: int) -> np.ndarray:
    """out[i] = min(x[i : i + la + 1]) (the window runs past the end as 1s)."""
    s = la + 1
    centred = minimum_filter1d(np.concatenate([x, np.ones(s, x.dtype)]), size=s,
                               mode="nearest")   # covers [j - s//2, j + (s-1)//2]
    return centred[s // 2: s // 2 + len(x)]


class _Band:
    """One band of SmartMono: smoothed channel powers and cross power, the polarity
    it sums with, and its make-up gain."""

    def __init__(self):
        self.ll = self.rr = self.lr = 0.0
        self.sign = 1.0
        self.gain = 1.0


class SmartMono:
    """Phase-aware mono downmix (see the module docstring). Crossovers at 200 Hz and
    2 kHz (4th-order Linkwitz-Riley: the bands sum back flat)."""

    SPLITS = (200.0, 2000.0)
    TAU_S = 1.0            # how fast the per-band statistics follow the music (slow:
                           # stereo width changes slowly, and a moving make-up gain
                           # would be heard as pumping)
    FLIP_BELOW = -0.35     # correlation under which a band is summed with R flipped
    UNFLIP_ABOVE = -0.10   # ...and back above this (hysteresis: no flapping)
    MAX_GAIN = 1.4125      # +3 dB at most for power lost to decorrelation

    def __init__(self, rate: int):
        self.rate = int(rate)
        nyq = rate / 2
        lo = butter(2, self.SPLITS[0] / nyq, "low", output="sos")
        hi = butter(2, self.SPLITS[0] / nyq, "high", output="sos")
        lo2 = butter(2, self.SPLITS[1] / nyq, "low", output="sos")
        hi2 = butter(2, self.SPLITS[1] / nyq, "high", output="sos")
        # LR4 = the Butterworth pair run twice; the low band also runs through the
        # upper split's all-pass (its LP + HP) so all three bands stay in phase
        self._sos = {
            "low": np.vstack([lo, lo]),
            "mid": np.vstack([hi, hi, lo2, lo2]),
            "high": np.vstack([hi, hi, hi2, hi2]),
        }
        self._ap = (np.vstack([lo2, lo2]), np.vstack([hi2, hi2]))
        self._zi = {k: np.zeros((len(s), 2, 2)) for k, s in self._sos.items()}
        self._zap = [np.zeros((len(s), 2, 2)) for s in self._ap]
        self.bands = {k: _Band() for k in self._sos}

    def _split(self, x: np.ndarray) -> dict:
        out = {}
        for k, sos in self._sos.items():
            out[k], self._zi[k] = sosfilt(sos, x, axis=0, zi=self._zi[k])
        a, self._zap[0] = sosfilt(self._ap[0], out["low"], axis=0, zi=self._zap[0])
        b, self._zap[1] = sosfilt(self._ap[1], out["low"], axis=0, zi=self._zap[1])
        out["low"] = a + b
        return out

    def process(self, x: np.ndarray) -> np.ndarray:
        n = len(x)
        if n == 0:
            return x
        x64 = np.asarray(x, np.float64)
        k = 1.0 - float(np.exp(-n / (self.rate * self.TAU_S)))
        mono = np.zeros(n)
        ramp = np.linspace(0.0, 1.0, n, endpoint=False) + 1.0 / n
        for name, b in self._split(x64).items():
            left, right = b[:, 0], b[:, 1]
            b_ = self.bands[name]
            b_.ll += (float(left @ left) / n - b_.ll) * k
            b_.rr += (float(right @ right) / n - b_.rr) * k
            b_.lr += (float(left @ right) / n - b_.lr) * k
            tot = b_.ll + b_.rr
            corr = b_.lr / np.sqrt(b_.ll * b_.rr) if b_.ll * b_.rr > 1e-18 else 1.0
            sign = b_.sign
            if sign > 0 and corr < self.FLIP_BELOW:
                sign = -1.0
            elif sign < 0 and corr > self.UNFLIP_ABOVE:
                sign = 1.0
            # power of the mono sum vs the channels' average power
            m_pow = (tot + 2 * sign * b_.lr) / 4
            want = float(np.sqrt((tot / 2) / m_pow)) if m_pow > 1e-18 and tot > 1e-18 else 1.0
            gain = min(max(want, 1.0), self.MAX_GAIN)
            s0, g0 = b_.sign, b_.gain
            sg = s0 + (sign - s0) * ramp        # crossfade a polarity change over the block
            gg = g0 + (gain - g0) * ramp
            mono += (left + right * sg) * 0.5 * gg
            b_.sign, b_.gain = sign, gain
        out = np.empty((n, 2), F32)
        out[:, 0] = mono
        out[:, 1] = mono
        return out


class Ducker:
    """Lowers the sounds while the mic hears you talk. Speech is detected against a
    noise floor it tracks itself (fans, hiss), so it works with any mic without a
    threshold to set. Gain moves per block: down fast, up slowly after a hold."""

    ATTACK_S, RELEASE_S, HOLD_S = 0.03, 0.4, 0.35
    ABOVE_FLOOR_DB = 12.0     # this much over the noise floor counts as talking
    MIN_TALK_DB = -50.0       # and never quieter than this

    def __init__(self, rate: int):
        self.rate = int(rate)
        self.floor_db = -60.0
        self.gain_db = 0.0
        self.held = 0.0          # seconds of hold left
        self.talking = False

    def process(self, mic: np.ndarray | None, n: int, depth_db: float) -> np.ndarray | float:
        """The gain for the sounds bus this block: a float 1.0 when there's nothing to
        do, else an (n, 1) ramp. `mic` is this block of the mic as sent, or None."""
        dt = n / self.rate
        if mic is not None and len(mic):
            lvl = 10 * np.log10(float(np.mean(np.square(mic, dtype=np.float64))) + 1e-12)
            # the floor follows quiet stretches down fast and creeps up slowly
            if lvl < self.floor_db:
                self.floor_db += (lvl - self.floor_db) * min(1.0, dt / 0.2)
            else:
                self.floor_db += min(lvl - self.floor_db, 3.0 * dt)   # 3 dB/s
            self.talking = lvl > max(self.floor_db + self.ABOVE_FLOOR_DB, self.MIN_TALK_DB)
        else:
            self.talking = False
        if self.talking:
            self.held = self.HOLD_S
        else:
            self.held = max(0.0, self.held - dt)
        target = depth_db if (depth_db < 0 and self.held > 0) else 0.0
        g0 = self.gain_db
        if target == g0 == 0.0:
            return 1.0
        tau = self.ATTACK_S if target < g0 else self.RELEASE_S
        g1 = target + (g0 - target) * float(np.exp(-dt / tau))
        if abs(g1 - target) < 0.05:
            g1 = target
        self.gain_db = g1
        ramp = np.linspace(g0, g1, n + 1, dtype=np.float64)[1:]
        return (10 ** (ramp / 20)).astype(F32)[:, None]


__all__ = ["CEILING_DB", "DUCK_CHOICES", "Ducker", "Limiter", "SmartMono"]
