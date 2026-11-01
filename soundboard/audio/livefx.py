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

import math

import numpy as np

from soundboard.audio.dsp import SmoothSos, butter, matched_biquad
from soundboard.audio.engineparts import LivePitch, soft_limit
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
# the volume of everything here (100 % = as it is): kept apart from the effect knobs,
# its slider sits under the pitch. Over 100 % the peaks are rounded off (soft_limit) so
# a boost gets louder instead of crackling
VOLUME = Param("volume", "Volume", 0, 400, 100, "%", 5)

# the chips under the knobs. One with a speed, pitch or "keep" (keep pitch, 0 = off:
# record-style, the pitch rises with the speed) also sets those (tuning()); the rest
# only the knobs. Nightcore: 1.3x record-style (+4.5 st), like nightcore uploads.
PRESETS: dict[str, dict[str, float]] = {
    "Nightcore": {"speed": 1.3, "keep": 0, "bass": 3},
    "Slowed + reverb": {"speed": 0.8, "keep": 0, "reverb": 0.45, "bass": 3},
    "Bass boosted": {"bass": 12},
    "Chipmunk": {"pitch": 7},
    "Deep voice": {"pitch": -5, "bass": 4},
    "Underwater": {"muffle": 0.8, "reverb": 0.3, "bass": 4},
}
TUNING = ("speed", "pitch", "keep")


def tuning(preset: dict, has_speed: bool = True) -> tuple[float, float, bool] | None:
    """The (speed, semitones, keep pitch) a preset sets, None if it only sets knobs.
    Without a speed (a live stream: radio, apps) a record-style speed-up becomes the
    pitch it would have given."""
    if not any(k in preset for k in TUNING):
        return None
    speed, pitch = preset.get("speed", 1.0), preset.get("pitch", 0.0)
    keep = bool(preset.get("keep", 1))
    if not has_speed:
        if not keep:
            pitch += round(12 * math.log2(speed))
        speed, keep = 1.0, True
    return speed, pitch, keep


MUFFLE_TOP, MUFFLE_LOW = 18000.0, 350.0     # lowpass cutoff at 0 and at full muffle
FADE = 1024    # samples an effect takes to fade out once its knob hits 0 (as SmoothSos)


def clean(fx) -> dict[str, float]:
    """Only the knobs that are off 0 (the volume: off 100 %), each clamped into its
    range."""
    if not isinstance(fx, dict):
        return {}
    out = {}
    for q in PARAMS:
        v = q.clamp(fx.get(q.key, 0))
        if abs(v) > 1e-6:
            out[q.key] = v
    v = VOLUME.clamp(fx.get(VOLUME.key, VOLUME.default))
    if abs(v - VOLUME.default) > 1e-6:
        out[VOLUME.key] = v
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

    def __init__(self, rate: int, fx: dict | None = None):
        """`fx`: a sound's own knobs it starts with (a sound starting, not a knob
        moved mid-stream): its volume is there from the first sample, not glided to."""
        self.rate = rate
        self.shelf = _Shelf(rate)
        self._fx: dict[str, tuple] = {}      # key -> one effect per channel
        self._last: dict[str, float] = {}    # key -> its last amount (for the fade-out)
        self._gone: dict[str, int] = {}      # key -> samples into its fade-out
        self._flush: int | None = None       # samples into a flush() fade, or None
        self.gen = 0                         # the engine's flush count it last saw
        # the volume the last block ended at
        self._gain = float((fx or {}).get(VOLUME.key, VOLUME.default)) / 100.0

    @property
    def idle(self) -> bool:
        return not self._fx and self.shelf.idle and self._gain == 1.0

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

    def flush(self):
        """Stop all: the echo and reverb tails fade out over FADE samples, then every
        effect starts again from silence. Knobs stay where they are. Audio thread."""
        if self._fx:
            self._flush = 0

    def _volume(self, y: np.ndarray, to: float) -> np.ndarray:
        """`y` at the volume (1 = 100 %), glided from the last block's over this one
        so a drag doesn't click; over 100 % its peaks are rounded off."""
        was, self._gain = self._gain, to
        if was == to == 1.0 or not len(y):
            return y
        if was == to:
            y = y * F32(to)
        else:
            ramp = np.linspace(was, to, len(y) + 1, dtype=F32)[1:]
            y = y * ramp[:, None]
        if max(was, to) > 1.0:
            soft_limit(y)
        return y.astype(F32, copy=False)

    def process(self, x: np.ndarray, fx: dict) -> np.ndarray:
        g = {q.key: float(fx.get(q.key, 0.0)) for q in PARAMS}
        dry = self.shelf.process(x, (g["bass"], g["treble"], g["muffle"]))
        y = self._knob("crunch", g["crunch"], dry, self._crunch)
        y = self._knob("echo", g["echo"], y, self._echo)
        y = self._knob("reverb", g["reverb"], y, self._reverb)
        y = self._wet(dry, y)
        return self._volume(y, float(fx.get(VOLUME.key, VOLUME.default)) / 100.0)

    def _wet(self, dry: np.ndarray, y: np.ndarray) -> np.ndarray:
        """The effects' output, or during a flush() its fade back to `dry`."""
        if self._flush is None:
            return y
        pos, n = self._flush, len(y)
        ramp = np.clip(1 - (pos + np.arange(1, n + 1, dtype=F32)) / F32(FADE), 0, 1)
        y = (dry + (y - dry) * ramp[:, None]).astype(F32, copy=False)
        if pos + n >= FADE:
            self._fx.clear()
            self._last.clear()
            self._gone.clear()
            self._flush = None
        else:
            self._flush = pos + n
        return y



# One sound's own live stage (Engine.set_sound_live): what Edit sound changes, heard
# at once on the playing sound instead of baked in first. (speed, pitch in semitones,
# its Live controls stages, boost as a gain): the speed is how fast the engine reads
# the sound (like Live controls' speed), the rest runs here. A stage {} is knobs at
# 0; NO_STAGE fades a stage that was on back out.
Stage = tuple[float, float, tuple[dict, ...], float]
NO_STAGE: Stage = (1.0, 0.0, (), 1.0)


class SoundStage:
    """A playing sound's live stage on one output: its pitch shift (Live controls'
    shifter), each Live controls stage (a LiveFx, as the bake runs them), then the
    boost and the clip to [-1, 1] the bake ends with. A stage taken off fades out (its
    knobs to 0) before it's dropped. The shifter is there from the start, as on the
    sounds bus: at 0 st it only keeps its history, so turning it on crossfades."""

    def __init__(self, rate: int, fresh: bool = False):
        """`fresh`: the sound is starting with it (else it came on mid-way): its
        volume and boost are there from the first sample, not glided to."""
        self.rate = rate
        self._pitch = LivePitch(rate)
        self._fx: list[LiveFx] = []
        self._gain = 1.0
        self._fresh = fresh

    def process(self, x: np.ndarray, stage: Stage) -> np.ndarray:
        _speed, st, stages, gain = stage
        fresh, self._fresh = self._fresh, False
        if fresh:
            self._gain = gain
        x = self._pitch.process(x, float(st))
        while len(self._fx) < len(stages):
            self._fx.append(LiveFx(self.rate, stages[len(self._fx)] if fresh else None))
        for i, f in enumerate(self._fx):
            x = f.process(x, stages[i] if i < len(stages) else {})
        while len(self._fx) > len(stages) and self._fx[-1].idle:
            self._fx.pop()
        was, self._gain = self._gain, gain
        if was != gain and len(x):   # glided over the block, like the volume
            x = x * np.linspace(was, gain, len(x) + 1, dtype=F32)[1:, None]
        elif gain != 1.0:
            x = x * F32(gain)
        return np.clip(x, -1.0, 1.0).astype(F32, copy=False)
