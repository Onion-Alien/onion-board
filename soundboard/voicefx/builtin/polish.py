"""Studio polish: de-ess, warmth and a ceiling. Runs last."""
from __future__ import annotations

import numpy as np
from soundboard.audio.dsp import butter, running_min
from soundboard.voicefx import Effect, Param, register

from soundboard.voicefx.builtin.parts import (F32, _Filter, _Oversampled, _chunks, _envelope,
                                              _glide, _per_chunk, _spread)


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
