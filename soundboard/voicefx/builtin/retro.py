"""Bit crusher: your voice through an old game console's sound chip."""
from __future__ import annotations

import numpy as np
from soundboard.voicefx import Effect, Param, register

from soundboard.voicefx.builtin.parts import F32, _glide


@register
class BitCrush(Effect):
    """Fewer bits (each sample rounded to one of 2^bits steps) and a lower sample rate
    (each sample held until the next one at the new rate is due): the gritty, buzzy
    sound of 8-bit consoles. Works sample by sample, so it adds no delay.

    The hold's phase is a fraction carried from block to block, on a grid of
    1/2^20 so the sums are exact and the result doesn't depend on the block size.
    Bits, rate and mix glide across a block when a slider moves."""

    type = "bitcrush"
    name = "Bit crusher"
    description = "Fewer bits and a lower sample rate: an old game console."
    params = (Param("bits", "Bits", 2, 16, 8, "", 1),
              Param("rate", "Sample rate", 1000, 24000, 8000, " Hz", 100),
              Param("mix", "Mix", 0, 1, 1))

    GRID = float(1 << 20)    # the hold's phase steps are multiples of 1/GRID

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.phase = 0.0          # how far into the current held sample, 0..1
        self.held = 0.0           # the sample being held
        self.last: tuple[float, float, float] | None = None   # (step, inc, mix) used last

    def _now(self, rate: int) -> tuple[float, float, float]:
        step = 2.0 ** (1 - self.p["bits"])          # -1..1 in 2^bits steps
        inc = min(1.0, self.p["rate"] / (rate or 48000))
        return step, round(inc * self.GRID) / self.GRID, self.p["mix"]

    def run(self, x, rate):
        n = len(x)
        if n == 0:
            return x
        now = self._now(rate)
        step0, inc0, mix0 = self.last or now
        step, inc, mix = now
        self.last = now
        if inc == inc0:
            ph = self.phase + inc * np.arange(1, n + 1)
        else:
            incs = np.round(_glide(inc0, inc, n).astype(np.float64) * self.GRID) / self.GRID
            ph = self.phase + np.cumsum(incs)
        # a new sample is taken wherever the phase passes a whole number
        k = np.floor(ph)
        new = np.diff(k, prepend=np.floor(self.phase)) > 0
        idx = np.maximum.accumulate(np.where(new, np.arange(n), -1))
        y = np.where(idx >= 0, x[np.maximum(idx, 0)], F32(self.held)).astype(F32)
        self.held = float(y[-1])
        self.phase = float(ph[-1] - k[-1])
        q = _glide(step0, step, n)
        y = np.round(y / q) * q
        m = _glide(mix0, mix, n)
        return (x * (1 - m) + y * m).astype(F32)
