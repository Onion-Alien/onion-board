"""The setup guide's test sound: a short 8-bit fanfare made in numpy (no audio file)."""
from __future__ import annotations

import numpy as np

from soundboard.audio.engine import SR


TUNE_NOTES = (98.0, 123.47, 146.83, 196.0)   # G2 B2 D3 G3: a G-major arpeggio, down low
TUNE_BASS = 49.0                              # G1 under it
TUNE_PEAK = 0.2


def _pulse(f: float, t: np.ndarray, duty: float = 0.25, top: float = 5000) -> np.ndarray:
    """An 8-bit style pulse wave, built from its harmonics up to `top` Hz so it's
    gritty without the fizzy aliasing a raw square has."""
    out = np.zeros_like(t)
    for k in range(1, int(top / f) + 1):
        out += np.sin(np.pi * k * duty) / k * np.cos(2 * np.pi * k * f * t - np.pi * k * duty)
    return out * (4 / np.pi)


def _steps(env: np.ndarray, levels: int = 15) -> np.ndarray:
    """Old consoles faded in 1/15ths, not smoothly: that stepped decay is half the sound."""
    return np.round(env * levels) / levels


def test_tune() -> np.ndarray:
    """The test sound (stereo float32): a quick G-major arpeggio in an 8-bit pulse
    wave over a deep, stepped triangle-wave bass, like an old console's fanfare."""
    step, note_len, bass_len = 0.1, 0.42, 1.25
    n = int(max(step * (len(TUNE_NOTES) - 1) + note_len, bass_len) * SR)
    out = np.zeros((n, 2))
    # the arpeggio: 25% pulse, stepped decay, low notes a touch left, high a touch right
    t = np.arange(int(note_len * SR)) / SR
    env = _steps(np.minimum(1.0, t / 0.004) * np.exp(-t * 6))
    for i, f in enumerate(TUNE_NOTES):
        tone = _pulse(f, t) * env * (0.55 if i < len(TUNE_NOTES) - 1 else 0.7)
        pan = (i / (len(TUNE_NOTES) - 1) - 0.5) * 0.4
        at = int(i * step * SR)
        out[at:at + len(t), 0] += tone * (1 - pan)
        out[at:at + len(t), 1] += tone * (1 + pan)
    # the bass: a 4-bit triangle (16 levels, like the NES bass channel), held long
    t = np.arange(int(bass_len * SR)) / SR
    tri = np.round((2 * np.abs(2 * ((TUNE_BASS * t) % 1) - 1) - 1) * 7.5) / 7.5
    bass = tri * _steps(np.minimum(1.0, t / 0.01) * np.exp(-t * 1.8))
    out[:len(t)] += bass[:, None]
    fade = int(0.03 * SR)
    out[-fade:] *= np.linspace(1, 0, fade)[:, None]
    out[:int(0.002 * SR)] *= np.linspace(0, 1, int(0.002 * SR))[:, None]
    return (out * (TUNE_PEAK / np.abs(out).max())).astype(np.float32)
