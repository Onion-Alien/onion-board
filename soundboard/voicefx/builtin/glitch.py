"""Glitch: your voice stutters, skips and cuts out like a broken stream."""
from __future__ import annotations

import numpy as np
from soundboard.voicefx import Effect, Param, register

from soundboard.voicefx.builtin.parts import F32


@register
class Glitch(Effect):
    """Now and then, while you talk, the last moment of your voice is caught and
    played instead of you: repeated a few times (a stutter: "I-I-I-I"), backwards,
    sped up into a chirp, or not at all (a drop-out). Then your live voice comes
    back. Nothing waits for what's next, so it adds no delay.

    Each glitch fades in and out over EDGE_S, and so does every repeat of its
    slice, so it skips without clicking."""

    type = "glitch"
    name = "Glitch"
    description = "Your voice stutters, skips and cuts out like a broken stream."
    params = (Param("amount", "How often", 0, 1, 0.5, "", 0, ("rarely", "all the time")),
              Param("length", "Repeat length", 20, 250, 80, " ms", 5, ("short", "long")))

    MOST_PER_S = 4.0       # glitches a second at How often 100%, while you talk
    GATE = 0.004           # quieter than this is not talking
    EDGE_S = 0.002
    KEEP_S = 0.5           # the slice comes from the last this-long of your voice
    # what a glitch does: stutter, backwards, chirp, drop-out
    KINDS = ("stutter", "reverse", "chirp", "drop")
    ODDS = (0.55, 0.15, 0.15, 0.15)

    def __init__(self, rate, values=None):
        super().__init__(rate, values)
        rate = rate or 48000
        self.hist = np.zeros(int(rate * self.KEEP_S), F32)
        self.edge = max(1, int(rate * self.EDGE_S))
        self.rng = np.random.default_rng()
        self.slice: np.ndarray | None = None   # the glitch playing now (one repeat)
        self.pos = 0                           # samples of it played
        self.total = 0                         # samples it lasts

    def _start(self, rate: int):
        """A new glitch from the voice just heard."""
        amount = self.p["amount"]
        n = int(np.clip(self.p["length"] / 1000 * self.rng.uniform(0.6, 1.4) * rate,
                        4 * self.edge, len(self.hist)))
        kind = self.KINDS[int(self.rng.choice(len(self.KINDS), p=self.ODDS))]
        s = self.hist[-n:].copy()
        repeats = int(self.rng.integers(2, 4 + int(4 * amount)))
        if kind == "reverse":
            s, repeats = s[::-1].copy(), max(1, repeats // 2)
        elif kind == "chirp":
            s = s[::2].copy()
            repeats *= 2
        elif kind == "drop":
            s[:] = 0
            repeats = 1
        self.slice, self.pos, self.total = s, 0, len(s) * repeats

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
        amount = self.p["amount"]
        if self.slice is None and amount > 0:
            talking = float(np.sqrt(np.mean(x * x))) > self.GATE
            if talking and self.rng.random() < amount * self.MOST_PER_S * n / rate:
                self._start(rate)
        s = self.slice
        if s is None:
            return x
        i = self.pos + np.arange(n)
        on = i < self.total
        j = i % len(s)
        e = F32(self.edge)
        rep = np.clip(np.minimum(j, len(s) - 1 - j) / e, 0, 1)     # each repeat's edges
        w = np.clip(np.minimum(i, self.total - 1 - i) / e, 0, 1) * on
        y = (x * (1 - w) + s[j] * rep * w).astype(F32)
        self.pos += n
        if self.pos >= self.total:
            self.slice = None
        return y
