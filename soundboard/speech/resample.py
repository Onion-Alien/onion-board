"""A streaming resampler with a steady output and almost no delay, for the AI voice.

soxr's good-quality streams hand their output out in ~30 ms lumps (and hold that
much back), which a live voice can't afford: every lump is a gap or a pile-up at
the other end. This is a plain polyphase windowed-sinc filter (Kaiser window,
32+ taps per phase, about 1 ms of delay): each block in gives its share of
samples out at once. Rates must reduce to a small ratio (48k/16k, 24k/48k,
44.1k/24k…); `make()` falls back to soxr's quick (steady) mode otherwise.
"""
from __future__ import annotations

import math

import numpy as np

TAPS = 32                    # per phase
MAX_PHASES = 640             # 44.1 kHz <-> 16/24/48 kHz all fit (147:160 at most)


class Polyphase:
    def __init__(self, src: int, dst: int):
        g = math.gcd(src, dst)
        self.up, self.down = dst // g, src // g
        cutoff = 0.45 * min(src, dst) / (src * self.up)       # cycles per upsampled sample
        # long enough for the narrower of the two bands (shrinking 3:1 needs 3x the taps)
        self.taps = taps = TAPS * max(1, -(-self.down // self.up))
        n = taps * self.up
        t = np.arange(n) - (n - 1) / 2
        h = 2 * cutoff * np.sinc(2 * cutoff * t) * np.kaiser(n, 8.0) * self.up
        # phase p holds taps p, p+up, p+2up...: y[j] = sum_i h[p + i up] x[newest - i]
        self.h = h.reshape(taps, self.up).T[:, ::-1].astype(np.float64)   # [up, taps], oldest first
        self.hist = np.zeros(taps - 1, np.float64)
        self.t = 0                   # next output's position, in upsampled samples, from hist[0]

    def resample_chunk(self, x: np.ndarray) -> np.ndarray:
        buf = np.concatenate([self.hist, np.asarray(x, np.float64)])
        # output j sits at upsampled position self.t + j*down; it needs inputs up to
        # base = pos // up (relative to buf, after the TAPS-1 history)
        taps = self.taps
        end = (len(buf) - taps + 1) * self.up             # positions we can finish
        n_out = max(0, -(-(end - self.t) // self.down))
        pos = self.t + np.arange(n_out) * self.down
        base, phase = pos // self.up, pos % self.up
        idx = base[:, None] + np.arange(taps)[None, :]
        y = np.einsum("ij,ij->i", buf[idx], self.h[phase]) if n_out else np.zeros(0)
        used = len(buf) - (taps - 1)
        self.t = self.t + n_out * self.down - used * self.up
        self.hist = buf[used:]
        return y.astype(np.float32)


def make(src: int, dst: int):
    """A streaming resampler for src -> dst with resample_chunk(x)."""
    g = math.gcd(src, dst)
    if dst // g <= MAX_PHASES and src // g <= MAX_PHASES:
        return Polyphase(src, dst)
    import soxr
    return soxr.ResampleStream(src, dst, 1, dtype="float32", quality="QQ")
