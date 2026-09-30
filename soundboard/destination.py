"""Destination modes: shape the sounds bus for whoever is listening.

The codec bench (soundboard.codecsim) measured what voice chat does to what
we send. Every service captures its mic in mono and runs Opus in voice mode,
which high-passes everything under ~100 Hz (3 dB lost on real music, more on
bass-heavy clips); Steam voice is fed 24 kHz so nothing above 12 kHz survives;
Vivox's low-CPU codec stops at 8 kHz. 100 Hz to 6 kHz gets through everywhere.

A mode pre-shapes the sounds bus for that pipeline:

  bass     sub-bass harmonics: the part under 120 Hz the codec will drop is
           saturated and its 2nd..5th harmonics (100-350 Hz, which survive) are
           mixed back in, so a kick still reads as a kick on the other side
  ceiling  low-pass at the codec's ceiling: the encoder stops spending bits on
           content nobody will hear, and what you monitor matches what they get
  comp     gentle stereo-linked compressor: a steadier level rides the
           service's gate and automatic gain better than a spiky one
  mono     one channel, the way the mic capture will send it, with the
           phase-aware downmix (soundboard.sendfx.SmartMono) so stereo effects
           that would cancel in a plain average don't

Built-in modes cover the services measured; custom ones (Settings) let you
describe any other codec by the same four knobs. The engine runs one Processor
per output (it keeps filter state), all reading the same Dest.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
from scipy.signal import butter, sosfilt

F32 = np.float32
CEILINGS = (0, 16000, 12000, 8000, 6000, 4000)   # 0 = none; the rest are codec bandwidths


@dataclass(frozen=True)
class Dest:
    key: str
    label: str
    ceiling: int = 0          # Hz low-pass; 0 = none
    bass: float = 0.0         # 0..1 sub-bass harmonics amount
    comp: float = 0.0         # 0..1 compressor amount
    mono: bool = False
    note: str = ""
    custom: bool = False

    @property
    def active(self) -> bool:
        return bool(self.ceiling or self.bass > 0 or self.comp > 0 or self.mono)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("custom", None)
        return d

    @staticmethod
    def from_dict(d: dict) -> Dest:
        """A custom mode from saved JSON; bad values fall back to safe ones."""
        def num(k, lo, hi, default):
            try:
                v = float(d.get(k, default))
            except (TypeError, ValueError, OverflowError):
                return float(default)
            return float(min(max(v, lo), hi)) if math.isfinite(v) else float(default)
        key = str(d.get("key") or "").strip() or "custom"
        label = str(d.get("label") or key)[:40]
        try:
            ceiling = int(d.get("ceiling", 0) or 0)
        except (TypeError, ValueError, OverflowError):   # also NaN / Infinity in the JSON
            ceiling = 0
        ceiling = min(max(ceiling, 0), 20000)
        if 0 < ceiling < 1000:
            ceiling = 1000
        return Dest(key, label, ceiling, num("bass", 0, 1, 0), num("comp", 0, 1, 0),
                    bool(d.get("mono", False)), str(d.get("note", ""))[:200], custom=True)


OFF = Dest("off", "Off (send as is)", note="No shaping. Your sounds go out exactly as mixed.")

BUILTIN: tuple[Dest, ...] = (
    OFF,
    Dest("discord", "Discord", 0, 0.6, 0.4, True,
         note="Opus 64 kbps, mono, voice mode. Keeps 100 Hz-20 kHz; loses sub-bass."),
    Dest("steam", "Steam voice (CS2, Dota, Steam games)", 12000, 0.6, 0.4, True,
         note="Opus fed 24 kHz mono: nothing above 12 kHz gets through. Also suits "
              "Phasmophobia and other Photon Voice games (24 kHz too)."),
    Dest("game", "Game voice (Fortnite, Valorant, Unity / Unreal games)", 0, 0.6, 0.5, True,
         note="Vivox Opus at 32 kbps mono. Keeps the full band, squeezes it harder. "
              "Also suits Valorant, Overwatch, FiveM, TeamSpeak and console party chat."),
    Dest("game_lo", "Game voice, low bandwidth (8 kHz)", 8000, 0.7, 0.5, True,
         note="Games on Unreal's own voice chat or Vivox's Siren 7: nothing above "
              "8 kHz."),
)
BUILTIN_BY_KEY = {d.key: d for d in BUILTIN}


def all_modes(custom: list[dict] | None) -> list[Dest]:
    out = list(BUILTIN)
    seen = set(BUILTIN_BY_KEY)
    # a hand-edited or imported config can hold anything here: only a list is used
    for raw in custom if isinstance(custom, list) else ():
        if not isinstance(raw, dict):
            continue
        d = Dest.from_dict(raw)
        if d.key in seen:
            continue
        seen.add(d.key)
        out.append(d)
    return out


def resolve(cfg_dest: dict | None) -> Dest:
    """The Dest a config's `dest` dict selects (OFF when unset or unknown)."""
    cfg_dest = cfg_dest if isinstance(cfg_dest, dict) else {}
    key = cfg_dest.get("mode", "off")
    for d in all_modes(cfg_dest.get("custom")):
        if d.key == key:
            return d
    return OFF


def apply(cfg, engine) -> Dest:
    """Push the config's destination mode onto the engine; returns it."""
    d = resolve(getattr(cfg, "dest", None))
    engine.dest = d if d.active else None
    return d


# --------------------------------------------------------------------------- DSP

class _Sos:
    """A stateful stereo second-order-section filter (sosfilt with kept memory)."""

    def __init__(self, sos: np.ndarray):
        self.sos = np.asarray(sos, F32)
        self.zi = None

    def __call__(self, x: np.ndarray) -> np.ndarray:
        if self.zi is None:
            self.zi = np.zeros((len(self.sos), 2, x.shape[1]), F32)
        y, self.zi = sosfilt(self.sos, x, axis=0, zi=self.zi)
        return y


class Processor:
    """Runs one Dest on one output's sounds bus. Re-designs its filters when the
    Dest changes; keeps state otherwise so switching a knob doesn't click."""

    BASS_SPLIT = 120.0        # Hz: below this the codec's high-pass will eat it
    BASS_BAND = (90.0, 350.0)  # where the generated harmonics are placed
    ATTACK_S, RELEASE_S = 0.005, 0.20

    def __init__(self, rate: int):
        self.rate = int(rate)
        self.dest: Dest | None = None
        self._lp = self._bp = self._ceil = None
        self._mono = None
        self.g = 1.0   # compressor gain

    def _design(self, d: Dest):
        r = self.rate
        nyq = r / 2
        if d.bass > 0:
            # steep split so the midrange never reaches the saturator
            self._lp = _Sos(butter(4, self.BASS_SPLIT / nyq, "low", output="sos"))
            self._bp = _Sos(butter(4, [self.BASS_BAND[0] / nyq, self.BASS_BAND[1] / nyq],
                                   "band", output="sos"))
        else:
            self._lp = self._bp = None
        if d.ceiling and d.ceiling < nyq * 0.9:
            # 8th order: a codec's band edge is a wall, not a slope
            self._ceil = _Sos(butter(8, d.ceiling / nyq, "low", output="sos"))
        else:
            self._ceil = None
        self.dest = d

    def process(self, x: np.ndarray, d: Dest | None) -> np.ndarray:
        if d is None or not d.active:
            self.dest = None
            self.g = 1.0
            return x
        if d != self.dest:
            keep = self.dest is not None and (d.bass > 0) == (self.dest.bass > 0) \
                and d.ceiling == self.dest.ceiling
            lp, bp, ce = self._lp, self._bp, self._ceil
            self._design(d)
            if keep:                 # only amounts changed: keep filter memory
                self._lp, self._bp, self._ceil = lp, bp, ce
        if x.dtype != F32:
            x = x.astype(F32)
        if d.bass > 0:
            low = self._lp(x)
            # odd harmonics from tanh saturation, even ones from the squared term;
            # the band-pass removes the fundamental (going anyway) and the DC
            drive = np.tanh(low * F32(6.0)) + low * np.abs(low) * F32(8.0)
            x = x + self._bp(drive) * F32(0.45 * d.bass)
        if self._ceil is not None:
            x = self._ceil(x)
        if d.comp > 0:
            x = self._compress(x, d.comp)
        if d.mono:
            if self._mono is None:
                from soundboard.sendfx import SmartMono
                self._mono = SmartMono(self.rate)
            x = self._mono.process(x)
        return np.ascontiguousarray(x, dtype=F32)

    def _compress(self, x: np.ndarray, amount: float) -> np.ndarray:
        """Block-wise peak compressor (one gain per block, ramped; no sample loop).
        amount 0..1 -> ratio 1..4:1 above -18 dBFS, with up to 3 dB of make-up."""
        n = len(x)
        ratio = 1.0 + 3.0 * amount
        thr = -18.0
        level = 20 * np.log10(float(np.max(np.abs(x))) + 1e-9)
        over = level - thr
        target = 10 ** (-over * (1 - 1 / ratio) / 20) if over > 0 else 1.0
        tau = self.ATTACK_S if target < self.g else self.RELEASE_S
        g = target + (self.g - target) * float(np.exp(-n / (self.rate * tau)))
        ramp = np.linspace(self.g, g, n + 1, dtype=F32)[1:]
        self.g = float(g)
        makeup = F32(10 ** (3.0 * amount / 20))
        return x * ramp[:, None] * makeup


__all__ = ["BUILTIN", "BUILTIN_BY_KEY", "CEILINGS", "OFF", "Dest", "Processor", "all_modes",
           "apply", "resolve"]
