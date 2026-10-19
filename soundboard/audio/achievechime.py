"""The achievement pop-up's sound, made in code (no audio files in the repo): the classic
console "achievement unlocked" chime. A soft rising bloop, then a bright bell chord that
shimmers and rings out with a short echo, about 1.6 s in all.

It only ever plays in your own headphones / speakers (engine.play(preview=True)), never
into the mic or the call."""
from __future__ import annotations

from functools import lru_cache

import numpy as np

from soundboard.audio.engineparts import SR

PEAK = 0.32   # loud enough to notice over a game, well under a sound's level


def _env(n: int, attack: float, tau: float) -> np.ndarray:
    """A quick linear rise over `attack` seconds, then an exponential fall (`tau`)."""
    t = np.arange(n) / SR
    rise = np.minimum(1.0, t / max(attack, 1e-4))
    return rise * np.exp(-np.maximum(0.0, t - attack) / tau)


def _bloop(n: int) -> np.ndarray:
    """The opening "bwoop": a sine gliding up an octave and a fifth, round and soft."""
    t = np.arange(n) / SR
    f = 330.0 * (3.0 ** np.minimum(1.0, t / 0.11))   # 330 Hz -> 990 Hz over 110 ms
    phase = 2 * np.pi * np.cumsum(f) / SR
    tone = np.sin(phase) + 0.25 * np.sin(2 * phase)
    return tone * _env(n, 0.012, 0.07)


def _bell(n: int, f0: float, tau: float, detune: float) -> np.ndarray:
    """A bright struck bell: a few partials (a little inharmonic, the high ones dying
    first), as two voices a few cents apart for the shimmer."""
    t = np.arange(n) / SR
    out = np.zeros(n)
    for ratio, gain, decay in ((1.0, 1.0, 1.0), (2.0, 0.42, 0.55), (3.01, 0.18, 0.35),
                               (4.16, 0.10, 0.22), (5.43, 0.05, 0.15)):
        for cents in (-detune, detune):
            f = f0 * ratio * 2 ** (cents / 1200)
            out += gain * np.sin(2 * np.pi * f * t) * np.exp(-t / (tau * decay))
    rise = np.minimum(1.0, t / 0.004)
    return out * rise / 2


@lru_cache(maxsize=1)
def chime() -> np.ndarray:
    """The chime as (frames, 2) float32 at the engine's rate. Made once."""
    total = int(1.6 * SR)
    mono = np.zeros(total)
    b = int(0.16 * SR)
    mono[:b] += 0.55 * _bloop(b)
    at = int(0.095 * SR)   # the bell lands as the bloop tops out
    n = total - at
    # a major sixth up from the bloop's top, with its fifth and octave under it
    mono[at:] += _bell(n, 1318.5, 0.42, 4.0)          # E6
    mono[at:] += 0.55 * _bell(n, 1975.5, 0.30, 5.0)   # B6
    mono[at:] += 0.35 * _bell(n, 659.3, 0.55, 3.0)    # E5, the body under it
    # a short echo each side (a little wider than it is long): the "room" it rings in
    left, right = mono.copy(), mono.copy()
    for delay, gain, ch in ((0.083, 0.30, left), (0.107, 0.30, right),
                            (0.171, 0.14, right), (0.197, 0.14, left)):
        d = int(delay * SR)
        ch[d:] += gain * mono[:-d]
    fade = np.minimum(1.0, (total - np.arange(total)) / (0.08 * SR))   # no click at the end
    out = np.stack([left, right], 1) * fade[:, None]
    out *= PEAK / max(1e-9, float(np.abs(out).max()))
    return out.astype(np.float32)
