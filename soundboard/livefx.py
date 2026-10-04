"""Live effects on the sounds bus: the Effects knobs in the speed & pitch popup.

Like the live speed and pitch they change every sound while it plays, aren't
saved, and leave the app's own playback (test recording, cues, previews) alone.
Each knob is one amount; the effect behind it is a voicefx building block run
once per channel. At 0 a knob costs nothing: its effect fades out to the dry
sound (FADE samples, like the filter knobs' crossfade) and is then dropped, so
turning it back up starts from silence instead of an old tail.

`Engine.sound_fx` holds the amounts ({key: value}, missing = 0), swapped whole by
the UI and read once per block on the audio thread."""
from __future__ import annotations

import numpy as np

from soundboard.dsp import SmoothSos, butter, matched_biquad
from soundboard.voicefx import Param
from soundboard.voicefx.builtin import Distortion, Echo, Reverb

F32 = np.float32

BASS = Param("bass", "Bass", -12, 18, 0, " dB", 1)
TREBLE = Param("treble", "Treble", -12, 12, 0, " dB", 1)
MUFFLE = Param("muffle", "Muffle", 0, 1, 0)
REVERB = Param("reverb", "Reverb", 0, 1, 0)
ECHO = Param("echo", "Echo", 0, 1, 0)
CRUNCH = Param("crunch", "Distortion", 0, 1, 0)
PARAMS = (BASS, TREBLE, MUFFLE, REVERB, ECHO, CRUNCH)

PRESETS: dict[str, dict[str, float]] = {
    "Bass boosted": {"bass": 12},
    "Blown out": {"bass": 15, "crunch": 0.7},
    "Concert hall": {"reverb": 0.55},
    "Canyon": {"echo": 0.6, "reverb": 0.2},
    "Underwater": {"muffle": 0.8, "reverb": 0.3, "bass": 4},
    "Phone call": {"bass": -12, "treble": -4, "muffle": 0.45, "crunch": 0.15},
}

MUFFLE_TOP, MUFFLE_LOW = 18000.0, 350.0     # lowpass cutoff at 0 and at full muffle
FADE = 1024    # samples an effect takes to fade out once its knob hits 0 (as SmoothSos)


def clean(fx) -> dict[str, float]:
    """Only the knobs that are off 0, each clamped into its range."""
    if not isinstance(fx, dict):
        return {}
    out = {}
    for q in PARAMS:
        v = q.clamp(fx.get(q.key, 0))
        if abs(v) > 1e-6:
            out[q.key] = v
    return out


class _Shelf:
    """Bass / treble / muffle as one filter on both channels; a new design
    crossfades in (dsp.SmoothSos), so dragging a knob doesn't click."""

    def __init__(self, rate: int):
        self.rate = rate
        self.key = None
        self.sos = None
        self.f = SmoothSos()
        self.f.fresh = False       # made mid-stream: fade in from the dry sound

    def design(self, bass: float, treble: float, muffle: float):
        rows = []
        if bass:
            rows.append(matched_biquad("lowshelf", 110, bass, self.rate)[None])
        if treble:
            rows.append(matched_biquad("highshelf", 5000, treble, self.rate)[None])
        if muffle:
            hz = MUFFLE_TOP * (MUFFLE_LOW / MUFFLE_TOP) ** muffle
            rows.append(butter(2, min(hz, self.rate * 0.45), btype="low", fs=self.rate))
        return np.vstack(rows) if rows else None

    @property
    def idle(self) -> bool:
        return self.sos is None and not self.f.fading

    def process(self, x: np.ndarray, key) -> np.ndarray:
        if key != self.key:
            self.key, self.sos = key, self.design(*key)
        if self.idle and self.f.sos is None:
            return x
        return self.f.run(x, self.sos).astype(F32, copy=False)


class LiveFx:
    """The live effects for one output (stereo blocks at its rate)."""

    def __init__(self, rate: int):
        self.rate = rate
        self.shelf = _Shelf(rate)
        self._fx: dict[str, tuple] = {}      # key -> one effect per channel
        self._last: dict[str, float] = {}    # key -> its last amount (for the fade-out)
        self._gone: dict[str, int] = {}      # key -> samples into its fade-out

    @property
    def idle(self) -> bool:
        return not self._fx and self.shelf.idle

    def _pair(self, key: str, cls, values: dict):
        pair = self._fx.get(key)
        if pair is None:
            pair = self._fx[key] = (cls(self.rate, values), cls(self.rate, values))
        for e in pair:
            e.p = e._values(values)        # set directly: one dict swap
        return pair

    def _run(self, pair, x: np.ndarray) -> np.ndarray:
        out = np.empty_like(x)
        for c, e in enumerate(pair):
            out[:, c] = e.run(np.ascontiguousarray(x[:, c]), self.rate)
        return out

    def _knob(self, key: str, a: float, y: np.ndarray, run) -> np.ndarray:
        """One effect knob: `run(a, y)` is its output at amount `a`. Once the knob
        hits 0 it keeps running at its last amount while the output crossfades back
        to the dry `y` (dropping it at once clicked and cut the echo's tail off)."""
        if a:
            self._gone.pop(key, None)
            self._last[key] = a
            return run(a, y)
        if key not in self._fx:
            return y
        pos = self._gone.get(key, 0)
        n = len(y)
        wet = run(self._last[key], y)
        ramp = np.clip(1 - (pos + np.arange(1, n + 1, dtype=F32)) / F32(FADE), 0, 1)
        out = (y + (wet - y) * ramp[:, None]).astype(F32, copy=False)
        if pos + n >= FADE:
            self._fx.pop(key, None)
            self._last.pop(key, None)
            self._gone.pop(key, None)
        else:
            self._gone[key] = pos + n
        return out

    def _crunch(self, a: float, y: np.ndarray) -> np.ndarray:
        d = self._run(self._pair("crunch", Distortion, {
            "drive": 6 + 24 * a, "tone": 9000 - 3000 * a, "level": 0.5}), y)
        return y * F32(1 - a) + d * F32(a)

    def _echo(self, a: float, y: np.ndarray) -> np.ndarray:
        return self._run(self._pair("echo", Echo, {
            "delay": 300, "feedback": 0.25 + 0.4 * a, "mix": 0.75 * a,
            "tone": 7000}), y)

    def _reverb(self, a: float, y: np.ndarray) -> np.ndarray:
        return self._run(self._pair("reverb", Reverb, {
            "size": 0.5 + 0.35 * a, "tone": 6000, "mix": a}), y)

    def process(self, x: np.ndarray, fx: dict) -> np.ndarray:
        g = {q.key: float(fx.get(q.key, 0.0)) for q in PARAMS}
        y = self.shelf.process(x, (g["bass"], g["treble"], g["muffle"]))
        y = self._knob("crunch", g["crunch"], y, self._crunch)
        y = self._knob("echo", g["echo"], y, self._echo)
        return self._knob("reverb", g["reverb"], y, self._reverb)
