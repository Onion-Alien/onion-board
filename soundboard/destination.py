"""Destination modes: shape the sounds bus for whoever is listening.

The codec bench (soundboard.codecsim) measured what voice chat does to what
we send. Every engine captures its mic in mono and high-passes it: Discord at
~94 Hz, Vivox at ~80 Hz with a slow tail to ~150 Hz, WebRTC's cleanup (Epic
Online Services, browsers) around 80 Hz, Opus' own voice mode on top. Steam
voice and Photon are fed 24 kHz so nothing above 12 kHz survives; Unreal's
built-in voice and Vivox's low-CPU codec stop at 8 kHz. 100 Hz to 6 kHz gets
through everywhere.

A mode pre-shapes the sounds bus for that pipeline:

  bass     sub-bass harmonics: the part under 100 Hz the chat will drop is
           saturated and its 2nd..4th harmonics (100-350 Hz, which survive) are
           mixed back in, so a kick still reads as a kick on the other side. The
           saturation runs on the band divided by its own envelope, so the
           harmonics keep the same character at any level
  lowcut   remove the sub-bass ourselves, after the harmonics are made: the chat
           throws it away anyway, but until then it sets the peaks, and the limiter
           turns the whole song down for bass nobody will hear (an 808 track lost
           11 dB that way in a real Valorant party). Each sound is also given back
           the level the cut takes from it (Voice.makeup, from cut_shares when it
           starts): levelling measured it *with* its sub-bass, so a bass-heavy song
           was levelled 8-10 dB quieter than the others and then lost its bass too
  ceiling  low-pass at the codec's ceiling: the encoder stops spending bits on
           content nobody will hear, and what you monitor matches what they get
  comp     gentle RMS compressor, for custom modes. None of the engines wants it:
           it cost 2-5 dB and added distortion in every one, even behind an automatic
           gain, and pushed songs under a voice gate where the make-up kept them over
  mono     one channel, the way the mic capture will send it, with the
           phase-aware downmix (soundboard.sendfx.SmartMono) so stereo effects
           that would cancel in a plain average don't

Built-in modes are one per voice chat engine; custom ones (Settings) let you
describe any other codec by the same knobs. The engine runs one Processor per
output (it keeps filter state), all reading the same Dest.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from functools import lru_cache

import numpy as np
from scipy import fft as sfft
from scipy.signal import butter, lfilter, sosfilt, sosfreqz

F32 = np.float32
CEILINGS = (0, 16000, 12000, 8000, 6000, 4000)   # 0 = none; the rest are codec bandwidths
LOWCUTS = (0, 60, 70, 80, 90)                     # 0 = none; Hz
CUT_ORDER = 8                                     # the low cut's Butterworth order
MAKEUP_MAX_DB = 12.0                              # most a sound is given back for its cut


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
    lowcut: int = 0           # Hz high-pass (one of LOWCUTS); 0 = none

    @property
    def active(self) -> bool:
        return bool(self.ceiling or self.bass > 0 or self.comp > 0 or self.mono or self.lowcut)

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
        cut = num("lowcut", 0, max(LOWCUTS), 0)
        lowcut = min(LOWCUTS, key=lambda c: abs(c - cut))   # a hand-edited value: nearest
        return Dest(key, label, ceiling, num("bass", 0, 1, 0), num("comp", 0, 1, 0),
                    bool(d.get("mono", False)), str(d.get("note", ""))[:200], custom=True,
                    lowcut=lowcut)


OFF = Dest("off", "Off (send as is)", note="No shaping. Your sounds go out exactly as mixed.")

# One mode per voice chat engine. Every engine's own cleanup and voice gate were run on
# 99 songs (docs/GAME-VOICE.md): all of them want the same shaping (sub-bass cut at
# their high-pass with the level given back, harmonics, no compressor), so the modes
# differ in the cut and the codec's ceiling, and in the games they name. A game is
# only ever an example here; the engine is what's matched. Keys are what configs
# store: "game" was the Vivox mode all along, and keeps its key.
BUILTIN: tuple[Dest, ...] = (
    OFF,
    Dest("discord", "Discord", 0, 0.8, 0.0, True, lowcut=90,
         note="Discord calls and servers. Opus 64 kbps mono, keeps 100 Hz-20 kHz "
              "(measured in a real call)."),
    Dest("game", "Vivox", 0, 0.8, 0.0, True, lowcut=80,
         note="Valorant, League of Legends, Rainbow Six Siege, Overwatch 2 and other "
              "games on Vivox. Opus 32 kbps mono, full band, nothing under ~80 Hz "
              "(measured in a real game). Also suits TeamSpeak and Mumble."),
    Dest("eos", "Epic Online Services", 0, 0.8, 0.0, True, lowcut=80,
         note="Fortnite and other games on Epic's voice chat. Opus mono with "
              "WebRTC-style noise suppression: turn that off in the game if it lets you."),
    Dest("steam", "Steam voice", 12000, 0.8, 0.0, True, lowcut=80,
         note="CS2, Dota 2, TF2 and other games on Steam's voice chat. Opus fed "
              "24 kHz mono: nothing above 12 kHz gets through."),
    Dest("unity", "Unity voice (Photon / Dissonance)", 12000, 0.8, 0.0, True, lowcut=80,
         note="Phasmophobia, Lethal Company and other Unity games with Photon Voice or "
              "Dissonance: Opus at 17-30 kbps, 12 kHz at most, voice activation."),
    Dest("game_lo", "Low bandwidth (8 kHz)", 8000, 0.9, 0.0, True, lowcut=80,
         note="Older and console titles: Unreal's built-in voice chat, Vivox's "
              "low-CPU codec. Nothing above 8 kHz."),
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


# --------------------------------------------------------------------------- make-up

def _cut_sos(hz: float, rate: int) -> np.ndarray:
    return butter(CUT_ORDER, hz / (rate / 2), "high", output="sos")


@lru_cache(maxsize=32)
def _cut_power(hz: int, rate: int, n: int) -> np.ndarray:
    """|H|^2 of the low cut at an n-point rfft's bins."""
    _, h = sosfreqz(_cut_sos(hz, rate), worN=np.fft.rfftfreq(n, 1 / rate), fs=rate)
    return (np.abs(h) ** 2).astype(np.float64)


def cut_shares(data: np.ndarray, rate: int) -> dict[int, float]:
    """How much of a sound's power each of LOWCUTS takes away: {cut Hz: 0..1}.

    Measured over the loud part of the sound (up to 128 spread-out frames of ~170 ms,
    so a long song costs the same few milliseconds as a short clip), through the
    cut's real filter response. The engine works this out once when a sound starts
    (Engine.play) and turns it into that sound's make-up gain (makeup)."""
    if data.ndim != 2 or len(data) < 1024:
        return {}
    n = 8192 if rate >= 32000 else 4096
    if len(data) < n:
        n = 1 << int(math.log2(len(data)))
    k = len(data) // n
    starts = np.linspace(0, k - 1, min(k, 128)).astype(np.int64) * n
    # only the frames used are read (a whole song's mono mix would cost 100+ ms)
    frames = np.stack([data[s:s + n] for s in starts]).astype(F32)   # (m, n, 2)
    frames = (frames[:, :, 0] + frames[:, :, 1]) * F32(
        0.5 / 32768.0 if data.dtype == np.int16 else 0.5)
    frames *= np.hanning(n).astype(F32)
    z = sfft.rfft(frames, axis=1)
    spec = z.real * z.real + z.imag * z.imag
    power = spec.sum(axis=1, dtype=np.float64)
    if power.max() <= 1e-18:
        return {}
    spec = spec[power > power.max() * 0.01].sum(axis=0, dtype=np.float64)   # loud frames
    total = float(spec.sum())
    out = {}
    for cut in LOWCUTS:
        if not cut or cut >= rate / 2 * 0.9:
            continue
        kept = float(spec @ _cut_power(cut, rate, n))
        out[cut] = min(max(1.0 - kept / total, 0.0), 1.0)
    return out


def makeup(share: float) -> float:
    """The gain that gives a sound back the power a cut took (share = cut_shares'
    value), capped at MAKEUP_MAX_DB so a sound that is almost all sub-bass (a bare
    808, a rumble) isn't pushed into the limiter."""
    cap = 10 ** (MAKEUP_MAX_DB / 20)
    if share <= 0.0:
        return 1.0
    return float(min(1.0 / math.sqrt(max(1.0 - share, 1.0 / (cap * cap))), cap))


# --------------------------------------------------------------------------- DSP

class _Sos:
    """A stateful second-order-section filter (sosfilt with kept memory)."""

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

    BASS_SPLIT = 100.0          # Hz: below this the chat's high-pass will eat it
    BASS_BAND = (100.0, 350.0)  # where the generated harmonics are placed
    BASS_GAIN = 1.0             # harmonics level at bass = 1
    ENV_S = 0.015               # the sub-bass envelope the saturator is normalised by
    COMP_THRESHOLD_DB = -20.0   # RMS, after the sound's levelling
    ATTACK_S, RELEASE_S = 0.03, 0.30
    GATE_DB = -50.0             # quieter than this the compressor holds its gain

    def __init__(self, rate: int):
        self.rate = int(rate)
        self.dest: Dest | None = None
        self._lp = self._bp = self._cut = self._ceil = None
        self._env_zi = np.zeros(1)
        self._mono = None
        self._pw = None   # compressor's smoothed power
        self.g = 1.0      # compressor gain

    def _design(self, d: Dest):
        r = self.rate
        nyq = r / 2
        if d.bass > 0:
            # steep split so the midrange never reaches the saturator
            self._lp = _Sos(butter(4, self.BASS_SPLIT / nyq, "low", output="sos"))
            self._bp = _Sos(butter(4, [self.BASS_BAND[0] / nyq, min(self.BASS_BAND[1] / nyq,
                                                                    0.95)],
                                   "band", output="sos"))
            self._env_zi = np.zeros(1)
        else:
            self._lp = self._bp = None
        self._cut = _Sos(_cut_sos(d.lowcut, r)) if d.lowcut and d.lowcut < nyq * 0.9 else None
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
            self._pw = None
            return x
        if d != self.dest:
            keep = self.dest is not None and (d.bass > 0) == (self.dest.bass > 0) \
                and d.ceiling == self.dest.ceiling and d.lowcut == self.dest.lowcut
            old = self._lp, self._bp, self._cut, self._ceil, self._env_zi
            self._design(d)
            if keep:                 # only amounts changed: keep filter memory
                self._lp, self._bp, self._cut, self._ceil, self._env_zi = old
        if x.dtype != F32:
            x = x.astype(F32)
        if d.bass > 0:
            x = x + self._harmonics(x, d.bass)
        if self._cut is not None:
            x = self._cut(x)
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

    def _harmonics(self, x: np.ndarray, amount: float) -> np.ndarray:
        """The sub-bass's 2nd..4th harmonics, (n, 1) to add to both channels.
        The band is divided by its own envelope before the saturator, so a quiet bass
        line gets the same harmonics as a loud one (just quieter): |u| makes the even
        ones (mostly the 2nd, an octave up), tanh the odd ones."""
        low = self._lp(x.mean(axis=1, keepdims=True))[:, 0]
        a = math.exp(-1.0 / (self.rate * self.ENV_S))
        env, self._env_zi = lfilter([1.0 - a], [1.0, -a], np.abs(low), zi=self._env_zi)
        env = np.maximum(env, 1e-5)
        u = low / env
        drive = (np.abs(u) + 0.5 * np.tanh(1.5 * u)) * env
        return self._bp(drive.astype(F32)[:, None]) * F32(self.BASS_GAIN * amount)

    def _compress(self, x: np.ndarray, amount: float) -> np.ndarray:
        """Block-wise RMS compressor (one gain per block, ramped; no sample loop).
        amount 0..1 -> ratio 1..4:1 above COMP_THRESHOLD_DB. No make-up: the sound's
        levelling and the limiter set the loudness; this only evens it out."""
        n = len(x)
        pw = float(np.mean(np.square(x, dtype=np.float64)))
        if 10 * math.log10(pw + 1e-20) < self.GATE_DB:   # a pause: hold, don't wind up
            g = self.g
        else:
            if self._pw is None:
                self._pw = pw
            tau = self.ATTACK_S if pw > self._pw else self.RELEASE_S
            k = math.exp(-n / (self.rate * tau))
            self._pw = k * self._pw + (1 - k) * pw
            level = 10 * math.log10(self._pw + 1e-20)
            over = level - self.COMP_THRESHOLD_DB
            ratio = 1.0 + 3.0 * amount
            g = 10 ** (-over * (1 - 1 / ratio) / 20) if over > 0 else 1.0
        ramp = np.linspace(self.g, g, n + 1, dtype=F32)[1:]
        self.g = float(g)
        return x * ramp[:, None]


__all__ = ["BUILTIN", "BUILTIN_BY_KEY", "CEILINGS", "LOWCUTS", "OFF", "Dest", "Processor",
           "all_modes", "apply", "cut_shares", "makeup", "resolve"]
