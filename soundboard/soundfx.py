"""Per-sound effects: speed, pitch, EQ, boost, reverse and any voice effect, baked
into the sound's audio once (off the audio thread) and kept in the decoded cache.

A sound's settings are a plain dict stored on its SoundMeta (`fx`), so the config
stays readable and new keys can be added without a migration:

    {"speed": 1.0,        0.25..4   playback speed (length changes, pitch doesn't)
     "pitch": 0.0,        -24..24   semitones (pitch changes, length doesn't)
     "tape": False,       speed also moves the pitch, like a record player
     "eq": [0.0] * 7,     dB per eq.BANDS band
     "gain_db": 0.0,      -24..36   boost; above 0 dBFS the sound clips (that's the point)
     "reverse": False,
     "effects": {type: {"on": bool, param: value, ...}}}   any voicefx effect,
                                                            modules' included

Speed and pitch are independent: pitch is a high-quality resample (which also
changes length), then a phase vocoder stretches the result to the length the
speed asks for. With `tape` on and no extra pitch the stretch is skipped
entirely, so nightcore / slowed versions are a pure resample.
"""
from __future__ import annotations

import hashlib
import json
import logging

import numpy as np

from soundboard import eq, voicefx
from soundboard.engine import SR, resample

log = logging.getLogger(__name__)

F32 = np.float32
SPEED_RANGE = (0.25, 4.0)
PITCH_RANGE = (-24.0, 24.0)
GAIN_RANGE = (-24.0, 36.0)
TAIL_S = 3.0          # room left for echo / reverb tails (trimmed back to the sound)
BLOCK = 2048          # effects run in blocks like they do on the mic


def neutral() -> dict:
    return {"speed": 1.0, "pitch": 0.0, "tape": False, "eq": [0.0] * len(eq.BANDS),
            "gain_db": 0.0, "reverse": False, "effects": {}}


def clean(fx: dict | None) -> dict:
    """Settings with every key present, in range, and unknown keys dropped."""
    out = neutral()
    fx = fx if isinstance(fx, dict) else {}

    def num(key, lo, hi):
        try:
            return float(min(max(float(fx.get(key, out[key])), lo), hi))
        except (TypeError, ValueError):
            return out[key]

    out["speed"] = num("speed", *SPEED_RANGE)
    out["pitch"] = num("pitch", *PITCH_RANGE)
    out["gain_db"] = num("gain_db", *GAIN_RANGE)
    out["tape"] = bool(fx.get("tape", False))
    out["reverse"] = bool(fx.get("reverse", False))
    g = fx.get("eq")
    if isinstance(g, list) and len(g) == len(eq.BANDS):
        try:
            out["eq"] = [float(min(max(float(v), -eq.MAX_DB), eq.MAX_DB)) for v in g]
        except (TypeError, ValueError):
            pass
    effs = fx.get("effects")
    if isinstance(effs, dict):
        out["effects"] = {str(k): dict(v) for k, v in effs.items() if isinstance(v, dict)}
    return out


def _active_effects(fx: dict) -> list[str]:
    return [t for t, cfg in fx["effects"].items() if cfg.get("on") and t in voicefx.REGISTRY]


def is_neutral(fx: dict | None) -> bool:
    """True if these settings leave the sound exactly as it is."""
    f = clean(fx)
    return (abs(f["speed"] - 1) < 1e-3 and abs(f["pitch"]) < 1e-3 and abs(f["gain_db"]) < 1e-3
            and not f["reverse"] and eq.design(f["eq"], SR) is None and not _active_effects(f))


def key(fx: dict | None) -> str:
    """Short stable id of the settings ('' for none): the cache file suffix."""
    if is_neutral(fx):
        return ""
    text = json.dumps(clean(fx), sort_keys=True)
    return hashlib.blake2b(text.encode(), digest_size=6).hexdigest()


def summary(fx: dict | None) -> str:
    """A few words for a tooltip: '0.8x, -3 st, EQ, +12 dB'."""
    if is_neutral(fx):
        return ""
    f = clean(fx)
    bits = []
    if abs(f["speed"] - 1) >= 1e-3:
        bits.append(f"{f['speed']:.2g}x" + (" tape" if f["tape"] else ""))
    if abs(f["pitch"]) >= 1e-3:
        bits.append(f"{f['pitch']:+g} st")
    if eq.design(f["eq"], SR) is not None:
        bits.append("EQ")
    if abs(f["gain_db"]) >= 1e-3:
        bits.append(f"{f['gain_db']:+g} dB")
    bits += [voicefx.REGISTRY[t].name for t in _active_effects(f)]
    if f["reverse"]:
        bits.append("reversed")
    return ", ".join(bits)


# --------------------------------------------------------------------------- stretch

def stretch(x: np.ndarray, factor: float, n_fft: int = 2048, hop: int = 512,
            chunk: int = 256) -> np.ndarray:
    """Make (n, 2) float32 audio `factor` times longer without changing its pitch.

    Phase vocoder with identity phase locking (each bin keeps its phase relation
    to the nearest spectral peak), which keeps it from sounding washed out. The
    phase is taken from the mid (L+R) signal and shared by both channels, so the
    stereo image doesn't smear. Frames are processed `chunk` at a time to keep
    memory bounded on long sounds."""
    n = len(x)
    if n == 0 or abs(factor - 1.0) < 1e-3:
        return np.ascontiguousarray(x, dtype=F32)
    out_len = int(round(n * factor))
    ha = hop / factor                        # analysis hop (fractional)
    win = np.hanning(n_fft + 1)[:-1].astype(F32)
    pad = np.zeros((n_fft, 2), F32)
    xp = np.concatenate([pad, x.astype(F32, copy=False), pad])
    n_frames = int(np.ceil((n + n_fft) / ha)) + 1
    starts = np.minimum(np.round(np.arange(n_frames) * ha).astype(np.int64), len(xp) - n_fft)
    y = np.zeros((n_frames * hop + n_fft, 2), np.float64)
    wsum = np.zeros(n_frames * hop + n_fft, np.float64)
    bins = np.arange(n_fft // 2 + 1)
    omega = 2 * np.pi * bins / n_fft         # expected phase advance per sample
    idx = np.arange(n_fft)
    win2 = win.astype(np.float64) ** 2
    prev_ang = None
    prev_phase = None
    prev_start = 0
    for c0 in range(0, n_frames, chunk):
        st = starts[c0:c0 + chunk]
        k = len(st)
        frames = xp[st[:, None] + idx]                     # (k, n_fft, 2)
        spec = np.fft.rfft(frames * win[None, :, None], axis=1)
        mid = spec[..., 0] + spec[..., 1]
        ang = np.angle(mid)
        mag = np.abs(spec)
        # true hop between consecutive frames (the rounding makes it vary by a sample)
        d = np.diff(np.concatenate([[prev_start], st])).astype(np.float64)
        pa = np.vstack([ang[:1] if prev_ang is None else prev_ang[None], ang[:-1]])
        dphi = ang - pa - omega[None] * d[:, None]
        dphi = (dphi + np.pi) % (2 * np.pi) - np.pi
        inst = omega[None] + dphi / np.maximum(d, 1)[:, None]
        adv = inst * hop
        if prev_phase is None:
            adv[0] = ang[0]                                # first frame keeps its phase
            base = 0.0
        else:
            base = prev_phase
        phase = base + np.cumsum(adv, axis=0)
        # identity phase locking: bins follow their nearest peak's rotation
        mm = np.abs(mid)
        peak = np.zeros_like(mm, dtype=bool)
        peak[:, 1:-1] = (mm[:, 1:-1] >= mm[:, :-2]) & (mm[:, 1:-1] > mm[:, 2:])
        peak[:, 0] = peak[:, -1] = True
        ar = np.broadcast_to(bins, mm.shape)
        left = np.maximum.accumulate(np.where(peak, ar, 0), axis=1)
        right = np.where(peak, ar, bins[-1] + n_fft)[:, ::-1]
        right = np.minimum.accumulate(right, axis=1)[:, ::-1]
        right = np.minimum(right, bins[-1])
        near = np.where((ar - left) <= (right - ar), left, right)
        rows = np.arange(k)[:, None]
        locked = phase[rows, near] + ang - ang[rows, near]
        rot = np.exp(1j * locked)[..., None]
        out = np.fft.irfft(mag * rot, n=n_fft, axis=1) * win[None, :, None]
        for j in range(k):
            o = (c0 + j) * hop
            y[o:o + n_fft] += out[j]
            wsum[o:o + n_fft] += win2
        prev_ang, prev_phase, prev_start = ang[-1], phase[-1], st[-1]
    wsum[wsum < 1e-3] = 1.0
    y /= wsum[:, None]
    lead = int(round(n_fft * factor))         # the zero padding, stretched
    return np.ascontiguousarray(y[lead:lead + out_len], dtype=F32)


def change_speed_pitch(x: np.ndarray, speed: float, semitones: float,
                       tape: bool = False) -> np.ndarray:
    """Speed and pitch at SR. With `tape`, speed also shifts the pitch (and
    `semitones` adds to that)."""
    ratio = 2.0 ** (semitones / 12.0) * (speed if tape else 1.0)   # pitch ratio
    y = x
    if abs(ratio - 1) >= 1e-4:
        y = resample(np.ascontiguousarray(x, dtype=F32), SR, int(round(SR / ratio)))
    # after the resample the sound is len/ratio long; it must end up len/speed long
    factor = ratio / speed
    if abs(factor - 1) >= 1e-3:
        y = stretch(y, factor)
    return y


# --------------------------------------------------------------------------- render

def _run_effects(x: np.ndarray, fx: dict) -> np.ndarray:
    types = _active_effects(fx)
    if not types:
        return x
    x = np.concatenate([x, np.zeros((int(TAIL_S * SR), 2), F32)])
    for t in types:
        cls = voicefx.REGISTRY[t]
        cfg = fx["effects"][t]
        chans = []
        for c in range(2):          # voice effects are mono: one instance per channel
            e = cls(SR, cfg)
            src = np.ascontiguousarray(x[:, c])
            parts = []
            for i in range(0, len(src), BLOCK):
                blk = src[i:i + BLOCK]
                try:
                    yb = np.asarray(e.run(blk, SR), dtype=F32)
                    if yb.shape != blk.shape or not np.all(np.isfinite(yb)):
                        raise ValueError(f"returned {yb.shape} / non-finite audio")
                except Exception:  # noqa: BLE001 - a broken module effect is skipped
                    log.exception("sound effect %r failed; skipped", t)
                    parts = None
                    break
                parts.append(yb)
            chans.append(np.concatenate(parts) if parts is not None else src)
        x = np.stack(chans, 1)
    # trim the tail back to where it falls silent
    loud = np.flatnonzero(np.max(np.abs(x), axis=1) > 1e-3)
    end = max(int(loud[-1]) + 1 if len(loud) else 0, len(x) - int(TAIL_S * SR))
    return np.ascontiguousarray(x[:end])


def render(data: np.ndarray, fx: dict | None) -> np.ndarray:
    """The sound with its effects applied: (n, 2) int16 or float32 at SR in,
    (m, 2) float32 at SR out, clipped to [-1, 1]. Slow for long sounds (the
    stretch): call it off the UI thread."""
    f = clean(fx)
    x = data.astype(F32) * F32(1 / 32767.0) if data.dtype == np.int16 else data.astype(F32)
    if is_neutral(f):
        return x
    x = change_speed_pitch(x, f["speed"], f["pitch"], f["tape"])
    if eq.design(f["eq"], SR) is not None:
        x = eq.EQ(SR).process(np.ascontiguousarray(x), f["eq"])
    x = _run_effects(x, f)
    if abs(f["gain_db"]) >= 1e-3:
        x = x * F32(10 ** (f["gain_db"] / 20))
    if f["reverse"]:
        x = x[::-1]
    return np.ascontiguousarray(np.clip(x, -1.0, 1.0), dtype=F32)


# --------------------------------------------------------------------------- presets

def _preset(**kw) -> dict:
    f = neutral()
    f.update(kw)
    return f


# name -> full settings (applied over everything in the Edit dialog)
PRESETS: dict[str, dict] = {
    "None (original)": neutral(),
    "Ear rape 🔊":       _preset(gain_db=24, eq=[12, 12, 8, 6, 10, 10, 6],
                                effects={"distortion": {"on": True, "drive": 30,
                                                        "tone": 9000, "level": 1}}),
    "Bass boosted":      _preset(gain_db=6, eq=[12, 10, 3, 0, 0, 0, 0]),
    "Slowed + reverb":   _preset(speed=0.8, tape=True,
                                effects={"reverb": {"on": True, "size": 0.85,
                                                    "tone": 5000, "mix": 0.35}}),
    "Nightcore":         _preset(speed=1.25, tape=True),
    "Chipmunk":          _preset(pitch=8),
    "Demon":             _preset(pitch=-8, effects={"reverb": {"on": True, "size": 0.6,
                                                               "tone": 3000, "mix": 0.25}}),
    "Fast (same pitch)": _preset(speed=1.5),
    "Slow-mo (same pitch)": _preset(speed=0.5),
    "Old radio":         _preset(effects={"radio": {"on": True, "low": 400, "high": 3000,
                                                    "drive": 8, "noise": 0.004}}),
    "Reversed":          _preset(reverse=True),
}
