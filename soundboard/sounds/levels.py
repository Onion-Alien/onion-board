"""Audio as numbers: int16 <-> float32, loudness levelling, waveform peaks and
trimming the dead air off a recording."""
from __future__ import annotations

import numpy as np

from soundboard.audio.engine import SR


TARGET_RMS_DB = -17.0  # loudness everything is levelled to when "Level volumes" is on
I16 = 32767.0
LEVEL_WIN = 2400   # level_gain's blocks (50 ms); a second (SR) is a whole number of them


def _i16(x: np.ndarray) -> np.ndarray:
    """to_int16's rounding of float audio already under full scale (or limited)."""
    y = x * I16
    np.rint(y, out=y)
    np.clip(y, -I16 - 1, I16, out=y)
    return y.astype("<i2")


def to_int16(data: np.ndarray) -> np.ndarray:
    """float32 [-1, 1] -> int16 (the in-memory / cached format). int16 passes through.
    Peaks over full scale (loud MP3 / AAC masters decode up to ~+1.5 dB, and resampling
    adds a little) are turned down by a limiter first: clipped here, the flat tops
    would be in the cache for good, crackling on every kick and snare."""
    if data.dtype == np.int16:
        return data
    if len(data) and float(np.max(np.abs(data))) > 1.0:
        data = _under_full_scale(data)
    # one float copy, rounded and clipped in place: a 15-minute song is ~350 MB of
    # float32, and each temporary would be another
    y = data * I16
    np.rint(y, out=y)
    np.clip(y, -I16 - 1, I16, out=y)
    return np.ascontiguousarray(y.astype(np.int16))


def _under_full_scale(data: np.ndarray, chunk: int = SR) -> np.ndarray:
    """(n, 2) audio through a lookahead limiter just under 0 dBFS (sendfx.Limiter: no
    distortion, the level elsewhere untouched), a second at a time."""
    from soundboard.audio.sendfx import Limiter
    if data.ndim != 2 or data.shape[1] != 2:
        return data              # (only stereo is stored; anything else just clips)
    lim = Limiter(SR, ceiling_db=-0.05)
    n = len(data)
    out = np.empty((n, 2), np.float32)
    at, skip = 0, lim.la         # the limiter's first `la` samples are its delay line

    def put(y):
        nonlocal at, skip
        d = min(skip, len(y))
        y, skip = y[d:], skip - d
        k = min(len(y), n - at)
        out[at:at + k] = y[:k]
        at += k

    for i in range(0, n, chunk):
        put(lim.process(np.asarray(data[i:i + chunk], np.float32)))
    put(lim.process(np.zeros((lim.la, 2), np.float32)))   # push the delay out
    return out


def to_float32(data: np.ndarray) -> np.ndarray:
    if data.dtype == np.float32:
        return data
    return data.astype(np.float32) * np.float32(1 / I16)


def peaks(data: np.ndarray, n: int) -> np.ndarray:
    """(n,) loudest absolute sample in each of n equal slices of (m, 2) audio,
    0..1: enough to draw a waveform."""
    if not len(data) or n <= 0:
        return np.zeros(max(n, 0), np.float32)
    scale = 1 / I16 if data.dtype == np.int16 else 1.0
    starts = np.linspace(0, len(data), n + 1).astype(np.int64)[:-1]
    at = np.minimum(starts, len(data) - 1)   # more slices than frames: the last ones are empty
    # max and min, not abs: abs of an int16 -32768 is still -32768. Per channel, then
    # both: numpy's max(axis=1) over two columns is many times slower
    hi = np.maximum(np.maximum.reduceat(data[:, 0], at), np.maximum.reduceat(data[:, -1], at))
    lo = np.minimum(np.minimum.reduceat(data[:, 0], at), np.minimum.reduceat(data[:, -1], at))
    hi, lo = hi.astype(np.float32), lo.astype(np.float32)
    out = np.maximum(hi, -lo) * np.float32(scale)
    out[starts >= len(data)] = 0.0
    return np.clip(out, 0.0, 1.0)


def _block_rms(data: np.ndarray) -> np.ndarray:
    """RMS of the mono mix in each whole LEVEL_WIN block (a part-block at the end is left
    out). Block by block, so any run of whole seconds can be done on its own."""
    mono = data.mean(axis=1)
    n = len(mono) // LEVEL_WIN
    return np.sqrt((mono[: n * LEVEL_WIN].reshape(n, LEVEL_WIN) ** 2).mean(axis=1))


def _gain(pk: float, rms: np.ndarray, r: float = 0.0) -> float:
    """level_gain from the loudest sample and the block RMS (`r` when there's no block)."""
    if len(rms):
        # RMS over the loud part only, so silence padding doesn't skew it
        rms = rms[rms > rms.max() * 0.1] if rms.max() > 0 else rms
        r = float(np.sqrt((rms ** 2).mean())) if len(rms) else 0.0
    if r <= 1e-6:
        return 1.0
    g = 10 ** ((TARGET_RMS_DB - 20 * np.log10(r)) / 20)
    if pk > 0:
        g = min(g, 0.95 / pk * 1.4)  # allow a little limiter work, not a lot
    return float(np.clip(g, 0.1, 6.0))


def level_gain(data: np.ndarray) -> float:
    """Gain that brings the sound to TARGET_RMS_DB without letting peaks exceed ~-0.5 dBFS."""
    if not len(data):
        return 1.0
    pk = float(np.max(np.abs(data)))
    if len(data) >= LEVEL_WIN:
        return _gain(pk, _block_rms(data))
    return _gain(pk, np.zeros(0), float(np.sqrt((data.mean(axis=1) ** 2).mean())))


def silence_bounds(data: np.ndarray, threshold: float = 0.002,
                   pad_s: float = 0.05) -> tuple[int, int]:
    """(start, end) frames of a recording with the dead air at both ends cut off (a
    tiny pad kept so it doesn't start abruptly); (0, 0) if it's all quiet."""
    loud = np.flatnonzero(np.max(np.abs(data), axis=1) > threshold)
    if not len(loud):
        return 0, 0
    pad = int(pad_s * SR)
    return max(int(loud[0]) - pad, 0), min(int(loud[-1]) + pad, len(data))


def trim_silence(data: np.ndarray, threshold: float = 0.002, pad_s: float = 0.05) -> np.ndarray:
    """Cut dead air off both ends of a recording (keeps a tiny pad so it doesn't start abruptly)."""
    a, b = silence_bounds(data, threshold, pad_s)
    return data[a:b]
