"""Proximity chat, simulated: what the listener's game does to our voice *after* the
codec, in games where you're heard as a sound in the world.

Development tool, like soundboard.codecsim. Every model follows the game's or
voice SDK's published / decompiled defaults (the numbers are cited on each); none of
them is measured. Distances are in the game's own units (metres, blocks).

    y = apply(x, "lethal", 8.0)                   # 8 m away, clear line of sight
    y = apply(x, "lethal", 8.0, "occluded")       # 8 m away, behind a wall
    y = apply(x, "lethal", 0.0, "walkie")         # over the walkie-talkie
    y = apply(x, "lethal:walkie")                 # the same ("model:variant")
    gain_db("svc", 24)                            # -6.0: halfway to the 48-block limit

Falloff:  linear   1 - (d - near) / (far - near), silent from far on
          inverse  near / (near + rolloff * (d - near)), silent from far on
          log      Unity's logarithmic rolloff: near / d, silent from far on
The listener's panning and reverb aren't modelled: they move the sound around the
room, they don't take anything out of it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from soundboard.dsp import butter, lfilter, sosfilt

SR = 48000
F32 = np.float32


@dataclass(frozen=True)
class Variant:
    """A listening situation: extra gain and filters, on top of the distance."""
    gain_db: float = 0.0
    band: tuple[float, float] | None = None     # Butterworth band-pass (Hz)
    lowpass_hz: float | None = None
    lowpass_q: float = 0.707                    # >0.707 = a resonant peak at the cutoff
    occlusion: bool = False                     # Lethal Company's distance-driven cutoff
    ignore_distance: bool = False               # radios: same level at any range
    note: str = ""


@dataclass(frozen=True)
class Model:
    key: str
    label: str
    falloff: str            # linear / inverse / log
    near: float
    far: float
    gain_db: float = 0.0
    rolloff: float = 1.0
    distance_lowpass: bool = False   # VRChat: duller with distance
    variants: dict[str, Variant] = field(default_factory=dict)
    note: str = ""


MODELS: dict[str, Model] = {m.key: m for m in (
    Model("unity_3d", "Unity 3D sound (Rust)", "log", 1.0, 40.0,
          note="Unity's default logarithmic rolloff; Rust's voice range ~40 m (estimate)"),
    Model("vivox_3d", "Vivox positional", "inverse", 1.0, 32.0, gain_db=-6.0,
          note="Vivox defaults: conversational 1 m, audible 32 m, InverseByDistance, "
               "positional channels 6 dB down"),
    Model("phasmo", "Phasmophobia local voice", "log", 1.0, 20.0,
          variants={"walkie": Variant(band=(300, 3400), ignore_distance=True,
                                      note="global walkie: telephone band (estimate), "
                                           "static not modelled")},
          note="Photon voice as a Unity 3D sound, heard up to 20 m"),
    Model("lethal", "Lethal Company", "log", 1.0, 50.0,
          variants={
              "occluded": Variant(occlusion=True,
                                  note="behind a wall: cutoff 2500 / (d / 25) Hz, "
                                       "900-4000 Hz (OccludeAudio.cs)"),
              "walkie": Variant(lowpass_hz=4000, lowpass_q=3.0, band=(300, 20000),
                                ignore_distance=True,
                                note="walkie-talkie: 4 kHz low-pass with Q 3 plus a "
                                     "high-pass (its cutoff is an estimate)")},
          note="clear line of sight eases the low-pass to 10 kHz; logarithmic fade"),
    Model("pma_voice", "FiveM pma-voice", "linear", 0.0, 7.0,
          variants={"whisper": Variant(note="whisper range 3"),
                    "shout": Variant(note="shout range 15"),
                    "radio": Variant(band=(389, 3248), ignore_distance=True,
                                     note="radio submix: 389-3248 Hz in, 348-4900 Hz out "
                                          "(its ring modulator runs at 0 Hz: no effect)")},
          note="pma-voice's normal range 7 (whisper 3, shout 15)"),
    Model("svc", "Simple Voice Chat", "linear", 0.0, 48.0,
          variants={"whisper": Variant(note="whisper range 24 blocks")},
          note="volume = 1 - d / 48 blocks (PositionalAudioUtils.java)"),
    Model("vrchat", "VRChat", "inverse", 0.0, 25.0, gain_db=15.0, distance_lowpass=True,
          note="+15 dB voice gain, far 25 m, distance low-pass on (its curve is an estimate)"),
    Model("crewlink", "BetterCrewLink (Among Us)", "linear", 0.1, 5.3,
          variants={"vent": Variant(gain_db=-6.0, lowpass_hz=2000, lowpass_q=20.0,
                                    note="in a vent: 2 kHz low-pass, Q 20, half volume"),
                    "camera": Variant(gain_db=-1.9, lowpass_hz=2300, lowpass_q=0.707,
                                      note="on cameras: 2.3 kHz low-pass, 0.8 volume")},
          note="linear model, ref distance 0.1, rolloff 1; the far edge is an estimate"),
)}

RANGES = {("pma_voice", "whisper"): 3.0, ("pma_voice", "shout"): 15.0,
          ("svc", "whisper"): 24.0}


def gain(model: str, distance: float, variant: str = "") -> float:
    """Linear gain at `distance` (0 = out of range)."""
    m = MODELS[model]
    v = m.variants.get(variant, Variant())
    g = 10 ** ((m.gain_db + v.gain_db) / 20)
    if v.ignore_distance:
        return g
    far = RANGES.get((model, variant), m.far)
    d = max(distance, 0.0)
    if d >= far:
        return 0.0
    if d <= m.near:
        return g
    if m.falloff == "linear":
        return g * (1 - (d - m.near) / (far - m.near))
    if m.falloff == "inverse":
        near = max(m.near, 1.0)       # VRChat's near 0: full gain inside 1 m
        return g * near / (near + m.rolloff * max(d - near, 0.0))
    return g * m.near / d               # log (Unity): near / d


def gain_db(model: str, distance: float, variant: str = "") -> float:
    g = gain(model, distance, variant)
    return float(20 * np.log10(g)) if g > 0 else -np.inf


def cutoff_hz(model: str, distance: float, variant: str = "") -> float | None:
    """The low-pass the listener hears through at this distance (None = none)."""
    m = MODELS[model]
    v = m.variants.get(variant, Variant())
    if v.occlusion:
        half = m.far / 2
        return float(np.clip(2500 / max(distance / half, 1e-6), 900, 4000))
    if v.lowpass_hz:
        return v.lowpass_hz
    if model == "lethal":
        return 10000.0
    if m.distance_lowpass:
        # estimate: from open at 1 m down to 3 kHz at the far edge, even in octaves
        frac = min(max(distance, 1.0), m.far) / m.far
        return float(20000 * (3000 / 20000) ** frac)
    return None


def _resonant_lowpass(x: np.ndarray, hz: float, q: float) -> np.ndarray:
    """RBJ biquad low-pass (Unity's AudioLowPassFilter with resonance)."""
    w = 2 * np.pi * hz / SR
    alpha = np.sin(w) / (2 * q)
    c = np.cos(w)
    b = np.array([(1 - c) / 2, 1 - c, (1 - c) / 2])
    a = np.array([1 + alpha, -2 * c, 1 - alpha])
    return lfilter(b / a[0], a / a[0], x)


def apply(x: np.ndarray, model: str, distance: float = 0.0, variant: str = "") -> np.ndarray:
    """x ((n,) or (n, 2) at 48 kHz, the decoded voice) as the listener hears it.
    Returns (n, 2) float32, both channels the same (panning isn't modelled)."""
    model, _, v2 = model.partition(":")
    variant = variant or v2
    if model not in MODELS:
        raise ValueError(f"unknown proximity model {model!r}")
    m = MODELS[model]
    if variant and variant not in m.variants:
        raise ValueError(f"{model} has no {variant!r} (has: {', '.join(m.variants) or 'none'})")
    v = m.variants.get(variant, Variant())
    y = np.asarray(x, np.float64)
    y = y.mean(axis=1) if y.ndim == 2 else y
    if v.band:
        lo, hi = v.band
        hi = min(hi, SR / 2 - 100)
        y = sosfilt(butter(4, (lo, hi), "bandpass", fs=SR), y)
    hz = cutoff_hz(model, distance, variant)
    if hz and hz < SR / 2 - 100:
        y = (_resonant_lowpass(y, hz, v.lowpass_q) if v.lowpass_q > 0.71
             else sosfilt(butter(2, hz, "lowpass", fs=SR), y))
    y = y * gain(model, distance, variant)
    return np.repeat(y[:, None], 2, axis=1).astype(F32)


__all__ = ["MODELS", "Model", "Variant", "apply", "cutoff_hz", "gain", "gain_db"]
