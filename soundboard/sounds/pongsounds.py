"""The sounds of Pong with Bun (ui/bun/bunpong.py), made in code: no sound files.

Every hit is short and crisp, and the hits in a rally climb a major pentatonic scale
one note at a time, so a long rally sounds like it's going somewhere. A hit off the
very tip of your paddle adds a little "ting", a faster ball hits brighter, and each
sound comes from the side of the court the ball is on. Each theme has its own style
of sound (STYLES), like Bun's outfits: 8-bit blips for Retro 98, a wooden knock for
Paper, and so on.

`render(name, style, ...)` returns stereo float32 at engine.SR; ui/bun/bunpong.py plays
it in the headphones only (engine previews), never to the mic.
"""
from __future__ import annotations

import math
import random
from functools import lru_cache

import numpy as np

from soundboard.audio.dsp import (butter, sosfilt)  # not scipy.signal: the built app leaves it out
from soundboard.audio.engine import SR

# each theme's sound style; a theme that isn't listed gets "soft"
STYLES: dict[str, str] = {
    "Arctic": "glass", "Ocean": "glass", "Midnight": "glass", "Mint": "glass",
    "Cherry Blossom": "glass", "Vaporwave": "glass",
    "Paper": "wood", "Mocha": "wood", "Forest": "wood", "Swamp": "wood",
    "Halloween": "wood",
    "Retro 98": "chip", "Hacker": "chip", "Amber Terminal": "chip", "High Contrast": "chip",
    "Synthwave": "neon", "Toxic": "neon", "Sunset": "neon", "Blood Moon": "neon",
    "Lava": "neon", "Brainrot": "neon", "Fireworks": "neon",
    "Barbie": "toy", "Comic Sans": "toy", "Flashbang": "toy", "Deep Fried": "toy",
}
KINDS = ("soft", "glass", "wood", "chip", "neon", "toy")

# the rally's ladder: C major pentatonic up from C5, one step a hit
LADDER = tuple(523.25 * 2 ** (s / 12) for s in (0, 2, 4, 7, 9, 12, 14, 16, 19, 21, 24, 26, 28,
                                                 31, 33))
PEAK = 0.5   # the loudest any one sound gets (the engine's float range is ±1)
_rng = random.Random()   # the little differences between hits: never the game's dice


def style_for(theme_name: str) -> str:
    return STYLES.get(theme_name, "soft")


def note(i: int) -> float:
    return LADDER[max(0, min(i, len(LADDER) - 1))]


class _Mix:
    """A stereo buffer that voices are added into at a time offset and a pan."""

    def __init__(self, secs: float):
        self.buf = np.zeros((int(secs * SR) + 1, 2), np.float32)

    def add(self, mono: np.ndarray, pan: float = 0.0, t0: float = 0.0):
        at = int(t0 * SR)
        need = at + len(mono)
        if need > len(self.buf):
            self.buf = np.concatenate([self.buf, np.zeros((need - len(self.buf), 2), np.float32)])
        a = (max(-1.0, min(1.0, pan)) + 1) * math.pi / 4   # equal-power pan
        self.buf[at:need, 0] += mono * math.cos(a) * math.sqrt(2)
        self.buf[at:need, 1] += mono * math.sin(a) * math.sqrt(2)


@lru_cache(maxsize=64)
def _sos(kind: str, lo: float, hi: float = 0.0):
    """A 2nd-order Butterworth filter's sections (made once each: designing one costs
    more than running it on a sound this short)."""
    edge = (lo, min(hi, SR * 0.45)) if kind == "band" else min(lo, SR * 0.45)
    return butter(2, edge, kind, fs=SR)


def _env(n: int, attack: float, gain: float) -> np.ndarray:
    """A fast rise, then an exponential fall to -80 dB by the end."""
    t = np.arange(n) / SR
    dur = max(n / SR, 1e-3)
    return (gain * np.minimum(1.0, t / max(attack, 1e-4)) * np.exp(-9.2 * t / dur)).astype(
        np.float32)


def tone(f: float, dur: float, gain: float, wave: str = "sine", f2: float = 0.0,
         attack: float = 0.003, lowpass: float = 0.0) -> np.ndarray:
    """One note: `wave` at `f` Hz (gliding to `f2`), with _env's shape."""
    n = max(1, int(dur * SR))
    t = np.arange(n) / SR
    freq = f * (f2 / f) ** (t / dur) if f2 else np.full(n, f)
    ph = np.cumsum(freq) / SR   # in cycles
    if wave == "sine":
        w = np.sin(2 * np.pi * ph)
    elif wave == "triangle":
        w = 2 * np.abs(2 * (ph % 1) - 1) - 1
    elif wave == "square":
        w = np.where(ph % 1 < 0.5, 1.0, -1.0)
    else:   # saw
        w = 2 * (ph % 1) - 1
    if lowpass:
        w = np.asarray(sosfilt(_sos("low", round(lowpass, -2)), w))
    return (w * _env(n, attack, gain)).astype(np.float32)


def noise(dur: float, gain: float, lo: float = 0.0, hi: float = 0.0) -> np.ndarray:
    """A burst of filtered noise: above `lo` Hz, or between `lo` and `hi`."""
    n = max(1, int(dur * SR))
    w = np.random.default_rng(_rng.getrandbits(32)).uniform(-1, 1, n)
    sos = _sos("band", lo, hi) if hi else _sos("high", lo or 2000)
    return (np.asarray(sosfilt(sos, w)) * _env(n, 0.001, gain)).astype(np.float32)


def _jit(v: float, amount: float) -> float:
    return v * (1 + _rng.uniform(-amount, amount))


def _strike(m: _Mix, style: str, f: float, pan: float, heat: float, soft: bool = False,
            t0: float = 0.0):
    """One hit of the ball in `style`, `t0` seconds in; `heat` 0..1 is how fast the ball
    is going."""
    g = (0.22 if soft else 0.32) * _jit(1, 0.08) * (1 + 0.25 * heat)
    f = _jit(f, 0.006)
    if style == "glass":
        m.add(tone(f * 2, 0.35, g * 0.7), pan, t0)
        m.add(tone(f * 2 * 2.76, 0.12, g * 0.25), pan, t0)
        m.add(noise(0.008, 0.04, 6000), pan, t0)
    elif style == "wood":
        m.add(tone(f * 0.5, 0.09, g * 1.1, "triangle", f2=f * 0.45), pan, t0)
        m.add(noise(0.02, 0.12, 1200, 2700), pan, t0)
    elif style == "chip":
        m.add(tone(f, 0.07, g * 0.45, "square", attack=0.001), pan, t0)
        m.add(tone(f * 2, 0.03, g * 0.2, "square", attack=0.001), pan, t0 + 0.035)
    elif style == "neon":
        cut = 1500 + 3500 * heat
        m.add(tone(f, 0.13, g * 0.5, "saw", lowpass=cut), pan, t0)
        m.add(tone(f * 1.007, 0.13, g * 0.4, "saw", lowpass=cut), pan, t0)
        m.add(tone(f / 4, 0.09, g * 0.8, f2=f / 8), pan, t0)
    elif style == "toy":
        m.add(tone(f * 0.7, 0.12, g, "triangle", f2=f * 1.3), pan, t0)
    else:   # soft: a round marimba "pok"
        m.add(tone(f, 0.16, g), pan, t0)
        m.add(tone(f * 4, 0.04, g * 0.35), pan, t0)
        m.add(noise(0.012, 0.05 + 0.08 * heat, 3000), pan, t0)


def render(name: str, style: str = "soft", *, rally: int = 0, pan: float = 0.0,
           heat: float = 0.0, edge: bool = False, level: int = 1) -> np.ndarray:
    """The sound `name` (one of NAMES) in `style`, as stereo float32 at SR.
    rally: the hit's step up the ladder; pan: -1 left .. 1 right; heat: the ball's
    speed, 0..1; edge: a hit off the tip of your paddle; level: the rally milestone."""
    m = _Mix(0.2)
    chip = style == "chip"
    if name == "you":
        _strike(m, style, note(rally), pan, heat)
        if edge:   # the close call: a little sparkle on top
            m.add(tone(note(rally) * 3, 0.25, 0.09), pan, 0.04)
            m.add(tone(note(rally) * 4, 0.2, 0.06), pan, 0.08)
    elif name == "bun":
        _strike(m, style, note(0) * 0.75, pan, heat, soft=True)
        if not chip:
            m.add(noise(0.025, 0.08, 600, 1350), pan)
    elif name == "wall":
        m.add(tone(_jit(1800 if chip else 2600, 0.03), 0.03, 0.05,
                   "square" if chip else "sine"), pan)
    elif name == "serve":
        n = noise(0.18, 0.25, 400, 3000)
        m.add(n * np.linspace(0.3, 1, len(n), dtype=np.float32), pan)
    elif name == "milestone":
        steps = (0, 4, 7, 12, 16, 19, 24)
        for i in range(min(3 + level, len(steps))):
            f = 1046.5 * 2 ** (steps[i] / 12)
            if chip:
                m.add(tone(f, 0.08, 0.08, "square"), 0, i * 0.05)
            else:
                m.add(tone(f, 0.4, 0.1), 0, i * 0.055)
        m.add(noise(0.25, 0.03, 7000), 0, 0.05)
    elif name == "score_you":
        w = "square" if chip else "sine"
        m.add(tone(784, 0.18, 0.18, w))
        m.add(tone(1175, 0.45, 0.18, w), 0, 0.09)
        m.add(tone(2350, 0.3, 0.05), 0, 0.09)
        m.add(noise(0.3, 0.05, 1200, 6000))
    elif name == "score_bun":
        if chip:
            m.add(tone(330, 0.1, 0.12, "square"))
            m.add(tone(247, 0.18, 0.12, "square"), 0, 0.1)
        else:   # a soft, funny boing: missing should make you want another go
            m.add(tone(420, 0.28, 0.22, "triangle", f2=180))
            m.add(tone(260, 0.18, 0.08, f2=300), 0, 0.12)
    elif name == "score_pop":
        m.add(tone(1600, 0.05, 0.06, f2=900))
    elif name == "win":
        w = "square" if chip else "triangle"
        for i, f in enumerate((523, 659, 784, 1047)):
            m.add(tone(f, 0.7 if i == 3 else 0.16, 0.16, w), 0, i * 0.11)
        m.add(tone(1568, 0.8, 0.05), 0, 0.33)
        for _i in range(14):   # the confetti, crackling down
            m.add(noise(0.02, 0.06, 4000), _rng.uniform(-0.8, 0.8), 0.4 + _rng.uniform(0, 0.9))
    elif name == "lose":   # wah, wah, wah, waaah
        w = "square" if chip else "triangle"
        for i, f in enumerate((392, 370, 349, 311)):
            last = i == 3
            m.add(tone(f, 0.5 if last else 0.2, 0.14, w, f2=f * 0.85 if last else 0.0,
                       lowpass=1800), 0, i * 0.2)
    # ---- Bun's other games (ui/bun/bungames.py)
    elif name == "bang":   # a hit: the crack, the boom, a ricochet ring
        m.add(noise(0.05, 0.28, 1500), pan)
        m.add(tone(140, 0.22, 0.3, f2=50), pan)
        m.add(noise(0.18, 0.12, 300, 1500), pan, 0.01)
        m.add(tone(2400, 0.25, 0.04, f2=1700), -pan * 0.6, 0.05)
    elif name == "early":   # a wrong one (whacked a carrot): a short rude buzzer
        m.add(tone(110, 0.28, 0.16, "square", lowpass=1400))
        m.add(tone(116, 0.28, 0.12, "saw", lowpass=1400))
    elif name == "hover":   # something popped up (whack-a-Bun): the faintest tick
        m.add(tone(_jit(3200 if chip else 2200, 0.02), 0.02, 0.06,
                   "square" if chip else "sine"), pan)
    else:
        raise ValueError(name)
    out = m.buf
    peak = float(np.abs(out).max())
    if peak > PEAK:
        out *= PEAK / peak
    fade = min(len(out), int(0.004 * SR))   # never a click at the end
    out[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)[:, None]
    return out


NAMES = ("you", "bun", "wall", "serve", "milestone", "score_you", "score_bun", "score_pop",
         "win", "lose", "bang", "early", "hover")
