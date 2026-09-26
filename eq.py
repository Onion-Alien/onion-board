"""7-band equalizer (RBJ biquads run through scipy's sosfilt, which is C-fast).

One EQ instance per audio path (it keeps filter memory between blocks), all
sharing the same band gains.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import sosfilt

# (centre Hz, kind): ends are shelves, the middle are bell/peaking filters
BANDS = [(60, "lowshelf"), (150, "peak"), (400, "peak"), (1000, "peak"),
         (2500, "peak"), (6000, "peak"), (12000, "highshelf")]
BAND_LABELS = ["60", "150", "400", "1k", "2.5k", "6k", "12k"]
MAX_DB = 12

# gains in dB per band, in BANDS order
PRESETS: dict[str, list[float]] = {
    "Flat (off)":              [0, 0, 0, 0, 0, 0, 0],
    "Voice — clear & crisp":   [-4, -2, -1, 1, 3, 3, 1],
    "Voice — deep radio host": [5, 3, 0, -1, 1, 1, 0],
    "Voice — remove boom/mud": [-8, -5, -3, 0, 1, 0, 0],
    "Voice — walkie-talkie":   [-12, -12, -2, 5, 6, -8, -12],
    "Voice — old telephone":   [-12, -12, -4, 4, 3, -12, -12],
    "Music — bass boost":      [7, 5, 0, 0, 0, 1, 2],
    "Music — club / loud":     [8, 5, -2, -1, 1, 4, 5],
    "Music — vocals up":       [-2, -1, 1, 3, 4, 2, 0],
    "Music — treble / bright": [0, 0, 0, 0, 2, 5, 7],
    "Music — lo-fi":           [2, 1, 0, 0, -3, -8, -12],
    "Deep fried 🔥 (max)":     [12, 12, 8, 8, 10, 10, 8],
}


def _biquad(kind: str, f0: float, db: float, rate: int, q: float = 1.0) -> np.ndarray:
    a = 10 ** (db / 40)
    w0 = 2 * np.pi * min(f0, rate * 0.45) / rate
    cw, sw = np.cos(w0), np.sin(w0)
    if kind == "peak":
        alpha = sw / (2 * q)
        b = [1 + alpha * a, -2 * cw, 1 - alpha * a]
        den = [1 + alpha / a, -2 * cw, 1 - alpha / a]
    else:  # shelves, slope S = 1
        alpha = sw / 2 * np.sqrt(2)
        k = 2 * np.sqrt(a) * alpha
        if kind == "lowshelf":
            b = [a * ((a + 1) - (a - 1) * cw + k), 2 * a * ((a - 1) - (a + 1) * cw),
                 a * ((a + 1) - (a - 1) * cw - k)]
            den = [(a + 1) + (a - 1) * cw + k, -2 * ((a - 1) + (a + 1) * cw),
                   (a + 1) + (a - 1) * cw - k]
        else:
            b = [a * ((a + 1) + (a - 1) * cw + k), -2 * a * ((a - 1) + (a + 1) * cw),
                 a * ((a + 1) + (a - 1) * cw - k)]
            den = [(a + 1) - (a - 1) * cw + k, 2 * ((a - 1) - (a + 1) * cw),
                   (a + 1) - (a - 1) * cw - k]
    b = np.array(b) / den[0]
    den = np.array(den) / den[0]
    return np.concatenate([b, den])


def design(gains: list[float], rate: int) -> np.ndarray | None:
    """Second-order sections for these band gains, or None if the EQ is flat."""
    if all(abs(g) < 0.05 for g in gains):
        return None
    return np.array([_biquad(kind, f, g, rate, q=1.1 if kind == "peak" else 1.0)
                     for (f, kind), g in zip(BANDS, gains)])


def response_db(gains: list[float], freqs: np.ndarray, rate: int = 48000) -> np.ndarray:
    """Magnitude response in dB at `freqs` (used to draw the curve)."""
    sos = design(gains, rate)
    if sos is None:
        return np.zeros_like(freqs, dtype=float)
    z = np.exp(-1j * 2 * np.pi * freqs / rate)
    h = np.ones_like(z)
    for s in sos:
        h *= (s[0] + s[1] * z + s[2] * z * z) / (s[3] + s[4] * z + s[5] * z * z)
    return 20 * np.log10(np.abs(h) + 1e-12)


class EQ:
    """Stateful stereo EQ for one audio path at one sample rate."""

    def __init__(self, rate: int):
        self.rate = rate
        self._sos = None
        self._zi = None
        self._gains = None

    def process(self, x: np.ndarray, gains: list[float] | None) -> np.ndarray:
        if gains is None:
            self._zi = None
            return x
        if gains != self._gains:
            self._gains = list(gains)
            sos = design(self._gains, self.rate)
            if sos is None or self._sos is None:
                self._zi = None       # fresh start; otherwise keep memory = no click
            self._sos = sos
        if self._sos is None:
            return x
        if self._zi is None:
            self._zi = np.zeros((len(self._sos), 2, x.shape[1]))
        y, self._zi = sosfilt(self._sos, x, axis=0, zi=self._zi)
        return y.astype(np.float32)
