"""7-band equalizer: matched peak / shelf biquads run by our own filter engine
(soundboard.dsp).

The bands are designed to follow the analog EQ they describe all the way up to
Nyquist (dsp.matched_biquad), so the 6 kHz and 12 kHz bands sound the same at
44.1 kHz as at 96 kHz instead of being squeezed by the bilinear transform. Moving a
slider or switching a preset crossfades from the old curve to the new over ~20 ms
(dsp.SmoothSos): no clicks or thumps, even on the bass shelf.

One EQ instance per audio path (it keeps filter memory between blocks), all
sharing the same band gains.
"""
from __future__ import annotations

import math

import numpy as np

from soundboard import dsp

# (centre Hz, kind): ends are shelves, the middle are bell/peaking filters
BANDS = [(60, "lowshelf"), (150, "peak"), (400, "peak"), (1000, "peak"),
         (2500, "peak"), (6000, "peak"), (12000, "highshelf")]
BAND_LABELS = ["60", "150", "400", "1k", "2.5k", "6k", "12k"]
MAX_DB = 12
PEAK_Q = 1.1                  # bell width (about 1.3 octaves)
SHELF_SLOPE = 1 / math.sqrt(2)   # shelf steepness: the cookbook's slope 1

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


def _is_flat(gains: list[float]) -> bool:
    return all(abs(g) < 0.05 for g in gains)


def _rows(gains: list[float], rate: int) -> np.ndarray:
    """One float64 biquad row per band."""
    return np.array([dsp.matched_biquad(kind, f, g, rate,
                                        PEAK_Q if kind == "peak" else SHELF_SLOPE)
                     for (f, kind), g in zip(BANDS, gains)])


def design(gains: list[float], rate: int) -> np.ndarray | None:
    """Second-order sections for these band gains, or None if the EQ is flat.

    Coefficients are designed in float64 and stored as float32 so the filter runs
    the whole block in float32 (the audio format) instead of upcasting to float64 and
    converting back every block. With a 60 Hz shelf at 48 kHz the poles sit at
    radius ~0.996: comfortably inside float32 precision (see tests/test_eq.py)."""
    if _is_flat(gains):
        return None
    return _rows(gains, rate).astype(np.float32)


def response_db(gains: list[float], freqs: np.ndarray, rate: int = 48000) -> np.ndarray:
    """Magnitude response in dB at `freqs` (used to draw the curve)."""
    if _is_flat(gains):
        return np.zeros_like(freqs, dtype=float)
    h = dsp.sos_response(_rows(gains, rate), freqs, rate)
    return 20 * np.log10(np.abs(h) + 1e-12)


class EQ:
    """Stateful stereo EQ for one audio path at one sample rate."""

    def __init__(self, rate: int):
        self.rate = rate
        self._filter = dsp.SmoothSos()
        self._sos = None
        self._gains = None

    def process(self, x: np.ndarray, gains: list[float] | None) -> np.ndarray:
        if gains is None:
            self._filter.reset()
            self._sos = self._gains = None
            return x
        if gains != self._gains:
            self._gains = list(gains)
            self._sos = design(self._gains, self.rate)
        if self._sos is None and self._filter.sos is None:
            return self._filter.run(x, None)       # flat: straight through
        if x.dtype != np.float32:
            x = x.astype(np.float32)
        # float32 in, float32 sos and state -> float32 out, no conversion
        return self._filter.run(x, self._sos, axis=0)
