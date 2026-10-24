"""Background: rain, wind, an engine, a crowd behind your voice (loops from voicefx.backdrop)."""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from soundboard.voicefx import Effect, Param, register

from soundboard.voicefx.builtin.parts import F32, _glide

if TYPE_CHECKING:
    from soundboard.voicefx.backdrop import Beds


@register
class Background(Effect):
    """Bundled CC0 backgrounds behind your voice, read from worker-prepared loops.

    The audio callback only mixes samples. Missing or still-loading loops stay
    silent until Maker hands them over; there is no synthetic fallback.
    """

    type = "backdrop"
    name = "Background"
    description = "Rain, wind, an engine, a crowd, a spaceship or a fire behind your voice."
    params = (Param("rain", "Rain", 0, 1, 0, "", 0, ("off", "pouring")),
              Param("wind", "Wind", 0, 1, 0, "", 0, ("off", "gale")),
              Param("engine", "Engine hum", 0, 1, 0, "", 0, ("off", "loud")),
              Param("crowd", "Crowd", 0, 1, 0, "", 0, ("off", "packed")),
              Param("space", "Spaceship hum", 0, 1, 0, "", 0, ("off", "loud")),
              Param("fire", "Crackling fire", 0, 1, 0, "", 0, ("off", "roaring")),
              Param("window", "Rain on a window", 0, 1, 0, "", 0, ("off", "pouring")),
              Param("talk", "Only while I talk", 0, 1, 1, "", 1))

    LAYERS = ("rain", "wind", "engine", "crowd", "space", "fire", "window")
    OPEN_DB = -45
    HOLD_S = 0.4
    LEVEL = 0.08
    BED_RATE = 48000

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        self.g_gate = 0.0
        self.quiet = self.HOLD_S
        self.levels: dict = {k: 0.0 for k in self.LAYERS}
        self.pos: dict = {}
        self.beds: Beds | None = None

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
            if loop is not None and len(loop):
                y += self._bed(k, loop, n, rate) * g
            else:
                self.levels[k] = 0.0  # fade in once the worker has finished loading
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
        if not y.any():
            return x
        if self.p["talk"] >= 0.5:
            was = self.g_gate
            y *= _glide(was, self._gate(x, rate), n)
        return (x + y).astype(F32, copy=False)
