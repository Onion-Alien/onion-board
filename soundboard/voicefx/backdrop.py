"""The voice changer's Background: loops made off the audio thread.

Built-in CC0 recordings are decoded and prepared here on a worker, including
neutral loops. Speed, pitch, bass, muffle and reverb are baked in before playback.
The effect only reads finished loops; it never decodes a file on the audio thread.

What the voice changer keeps (the effect's settings, so saved voices carry it):

    {"on": True, "rain": 0.5, ..., "talk": 0,          the levels (numbers)
     "tweaks": {"rain": {"speed": 1, "pitch": 0, "bass": 0, "muffle": 0, "reverb": 0}},
     "sounds": [{"id": "<a board sound's id>", "level": 0.4, "tweaks": {...}}]}

`Maker` runs the renders on one worker thread and hands the finished loops (`Beds`)
to a callback; a newer request replaces one that hasn't started.
"""
from __future__ import annotations

import logging
import math
import sys
from functools import lru_cache
from pathlib import Path
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from soundboard.voicefx import Param

log = logging.getLogger(__name__)

F32 = np.float32
SR = 48000            # the loops' rate (the engine's); the effect steps through them
LOOP_S = 20.0         # a loop's length (a board sound shorter than this loops as it is)
SEAM_S = 1.0          # the crossfade where a loop's end runs into its start
SHORT_SEAM_S = 0.05   # ...for a board sound: a beat's own gap isn't smeared
MAX_SOUNDS = 4        # board sounds in one background
LAYERS = ("rain", "wind", "engine", "crowd", "space", "fire", "window")
AUDIO_DIR = (Path(sys._MEIPASS) / "backgrounds" if hasattr(sys, "_MEIPASS")  # pyright: ignore[reportAttributeAccessIssue]
             else Path(__file__).resolve().parents[2] / "assets" / "backgrounds")

# the Speed and pitch pop-up's settings: like Live controls', for one sound
TWEAKS = (Param("speed", "Speed", 0.5, 2.0, 1.0, "x", 0.05),
          Param("pitch", "Pitch", -12, 12, 0, " st", 1),
          Param("bass", "Bass", -12, 12, 0, " dB", 1),
          Param("muffle", "Muffle", 0, 1, 0),
          Param("reverb", "Reverb", 0, 1, 0))

# the pop-up's quick picks: where the sound seems to be
PLACES = {"Far away": {"bass": -6, "muffle": 0.55, "reverb": 0.6},
          "Next room": {"bass": 2, "muffle": 0.75, "reverb": 0.25},
          "Through a wall": {"bass": 4, "muffle": 0.95, "reverb": 0.0},
          "Outside": {"bass": -2, "muffle": 0.2, "reverb": 0.15},
          "Bass boosted": {"bass": 10, "muffle": 0.0, "reverb": 0.0}}


def neutral_tweaks() -> dict:
    return {q.key: q.default for q in TWEAKS}


def clean_tweaks(raw) -> dict:
    """Saved pop-up settings with every number in its range (a damaged one: as it starts)."""
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for q in TWEAKS:
        v = raw.get(q.key, q.default)
        out[q.key] = q.clamp(v) if not isinstance(v, bool) else q.default
    return out


def is_neutral(tweaks: dict | None) -> bool:
    t = clean_tweaks(tweaks)
    return all(t[q.key] == q.default for q in TWEAKS)


def clean_extra(cfg: dict) -> dict:
    """The Background's non-number settings ("tweaks", "sounds"), cleaned; {} if none."""
    out = {}
    tw = cfg.get("tweaks")
    if isinstance(tw, dict):
        kept = {k: clean_tweaks(v) for k, v in tw.items() if k in LAYERS and isinstance(v, dict)}
        kept = {k: v for k, v in kept.items() if not is_neutral(v)}
        if kept:
            out["tweaks"] = kept
    snd = cfg.get("sounds")
    if isinstance(snd, list):
        seen, kept_s = set(), []
        for d in snd:
            if not isinstance(d, dict) or not isinstance(d.get("id"), str) or not d["id"]:
                continue
            if d["id"] in seen or len(kept_s) >= MAX_SOUNDS:
                continue
            seen.add(d["id"])
            lvl = d.get("level", 0.5)
            lvl = (min(max(float(lvl), 0.0), 1.0)
                   if isinstance(lvl, (int, float)) and not isinstance(lvl, bool)
                   and math.isfinite(lvl) else 0.5)
            item = {"id": d["id"][:64], "level": lvl}
            if isinstance(d.get("tweaks"), dict) and not is_neutral(d["tweaks"]):
                item["tweaks"] = clean_tweaks(d["tweaks"])
            kept_s.append(item)
        if kept_s:
            out["sounds"] = kept_s
    return out


def fx_for(tweaks: dict) -> dict:
    """The pop-up's settings as a pad's effects (soundfx): speed keeps the pitch, bass
    is the bottom two EQ bands, muffle pulls the top three down, reverb is a hall."""
    from soundboard.audio import eq, soundfx
    t = clean_tweaks(tweaks)
    f = soundfx.neutral()
    f["speed"], f["pitch"] = t["speed"], t["pitch"]
    bands = [0.0] * len(eq.BANDS)
    bands[0], bands[1] = t["bass"], t["bass"] * 0.6
    m = t["muffle"] * eq.MAX_DB
    bands[-3], bands[-2], bands[-1] = -m * 0.5, -m, -m
    f["eq"] = bands
    if t["reverb"] > 0:
        f["effects"] = {"reverb": {"on": True, "size": 0.3 + 0.6 * t["reverb"],
                                   "tone": 4000, "mix": 0.55 * t["reverb"]}}
    return f


@lru_cache(maxsize=len(LAYERS))
def recording(layer: str) -> np.ndarray:
    """Decode one bundled CC0 loop off the audio thread; shared read-only samples."""
    import soundfile as sf
    if layer not in LAYERS:
        raise ValueError("unknown background layer")
    audio, rate = sf.read(AUDIO_DIR / (layer + ".ogg"), dtype="float32")
    if rate != SR or audio.ndim != 1 or not len(audio) or not np.isfinite(audio).all():
        raise ValueError("invalid background recording")
    # Sparse drops can have high crest factors. Keep their natural dynamics
    # without a single drop clipping at the full layer level (0.08).
    audio = _norm(audio, peak=8.0)
    audio.flags.writeable = False
    return audio


def generate(layer: str, seconds: float, rate: int = SR, seed: int | None = None) -> np.ndarray:
    """An excerpt of the same CC0 loop used live, RMS ~1, made off the audio thread."""
    import soxr
    raw = recording(layer)
    n = int(seconds * SR)
    out = np.tile(raw, max(1, math.ceil(n / len(raw))))[:n].copy()
    if rate != SR:
        out = soxr.resample(out, SR, rate).astype(F32)
    return out


def loopable(x: np.ndarray, seam_s: float, rate: int = SR) -> np.ndarray:
    """x with its last `seam_s` crossfaded (equal power) into its start and cut off, so
    playing it round and round has no click or gap."""
    k = min(int(seam_s * rate), len(x) // 3)
    if k < 2:
        return np.ascontiguousarray(x, dtype=F32)
    t = np.linspace(0.0, math.pi / 2, k, dtype=F32)
    y = x[:len(x) - k].astype(F32, copy=True)
    y[:k] = y[:k] * np.sin(t) + x[len(x) - k:] * np.cos(t)
    return y


def _mono(x: np.ndarray) -> np.ndarray:
    if x.ndim == 1:
        return x.astype(F32, copy=False)
    if x.dtype == np.int16:
        x = x.astype(F32) * F32(1 / 32767.0)
    return x.astype(F32, copy=False).mean(axis=1).astype(F32)


def _norm(x: np.ndarray, peak: float | None = None) -> np.ndarray:
    """A board sound at about the built-in layers' loudness (RMS 1 before its level),
    so a slider means the same on every row. Silence stays silence."""
    rms = float(np.sqrt(np.mean(x * x))) if len(x) else 0.0
    out = (x / F32(rms)).astype(F32) if rms > 1e-5 else x
    if peak is not None and len(out):
        out = out * F32(min(1.0, peak / max(float(np.max(np.abs(out))), 1e-9)))
    return out


def render_layer(layer: str, tweaks: dict) -> np.ndarray:
    """A built-in layer with its pop-up settings, as a loop (mono, SR, RMS ~1)."""
    import soxr

    from soundboard.audio import soundfx
    t = clean_tweaks(tweaks)
    if is_neutral(t):
        return recording(layer)
    # rain or wind has no tune to keep: speed and pitch are one resample (a tape sped
    # up), not soundfx's stretch, which took seconds of the app's time for 30 s
    factor = t["speed"] * 2 ** (t["pitch"] / 12)
    raw = generate(layer, (LOOP_S + SEAM_S) * factor + 1)
    if factor != 1:
        raw = soxr.resample(raw, SR * factor, SR).astype(F32)
    st = np.stack([raw, raw], 1)
    out = _mono(soundfx.render(st, fx_for({**t, "speed": 1.0, "pitch": 0.0})))
    return _norm(loopable(out[:int((LOOP_S + SEAM_S) * SR)], SEAM_S), peak=8.0)


def render_sound(audio: np.ndarray, tweaks: dict | None) -> np.ndarray:
    """A board sound ((n, 2) int16 or float32 at SR, its own effects in) with the
    pop-up's settings, as a loop (mono, SR, RMS ~1). Only its first LOOP_S seconds."""
    from soundboard.audio import soundfx
    t = clean_tweaks(tweaks)
    cut = audio[:int((LOOP_S * t["speed"] + SHORT_SEAM_S) * SR)]
    out = soundfx.render(cut, fx_for(t)) if not is_neutral(t) else cut
    return loopable(_norm(_mono(out)), SHORT_SEAM_S)


def _board_loop(load: Callable[[str], np.ndarray | None], sid: str, tweaks: dict):
    audio = load(sid)
    if audio is None or not len(audio):
        raise LookupError("no such sound")
    return render_sound(audio, tweaks)


@dataclass(frozen=True)
class Beds:
    """Finished loops for the Background effect. `layers`: built-in layer -> its loop
    (including neutral recordings). `sounds`: (loop, level) per board
    sound. Swapped in whole: the audio thread reads one attribute."""
    layers: dict = field(default_factory=dict)
    sounds: tuple = ()
    key: tuple = ()      # what was asked for (Maker skips an identical request)


def wanted(cfg: dict | None) -> tuple:
    """What a Background's settings need made: ((layer, tweaks...), (id, tweaks...)),
    hashable, so a change of level alone (no new loop) is seen as the same."""
    cfg = cfg or {}
    extra = clean_extra(cfg)
    tweaks = extra.get("tweaks", {})
    layers = tuple((k, tuple(sorted(clean_tweaks(tweaks.get(k)).items())))
                   for k in LAYERS if Param(k, k, 0, 1, 0).clamp(cfg.get(k, 0)) > 0)
    sounds = tuple((d["id"], tuple(sorted(clean_tweaks(d.get("tweaks")).items())))
                   for d in extra.get("sounds", []))
    return layers, sounds


class Maker:
    """Makes the loops a Background needs on one worker thread.

    `update(cfg, load)` (UI thread): cfg is the Background's settings (None: off),
    load(sound_id) -> (n, 2) audio or None (a sound that's gone is left out; it runs
    on the worker, so it may read the disk). `ready(beds)` is called on the worker
    with the result; levels changing alone call it at once (no render). Loops made
    before are kept (by what made them), so moving a slider back is instant."""

    MAX_KEPT = 16

    def __init__(self, ready: Callable[[Beds], None]):
        self.ready = ready
        self._lock = threading.Lock()
        self._job: tuple | None = None
        self._busy = False
        self._made: dict[tuple, np.ndarray] = {}
        self._gen = 0
        self.closed = False

    def update(self, cfg: dict | None, load: Callable[[str], np.ndarray | None]):
        if self.closed:
            return
        key = wanted(cfg) if cfg and cfg.get("on") else ((), ())
        levels = tuple(d["level"] for d in clean_extra(cfg or {}).get("sounds", []))
        with self._lock:
            self._gen += 1
            self._job = (self._gen, key, levels, load)
            if self._busy:
                return
            self._busy = True
        threading.Thread(target=self._run, name="voice-backdrop", daemon=True).start()

    def close(self):
        self.closed = True

    def _loop_for(self, what: tuple, make: Callable[[], np.ndarray]) -> np.ndarray | None:
        got = self._made.get(what)
        if got is None:
            try:
                got = make()
            except Exception as ex:  # noqa: BLE001 - one bad sound leaves only itself out
                log.warning("background sound %r couldn't be made: %s", what[:2], ex)
                return None
            if len(self._made) >= self.MAX_KEPT:
                self._made.pop(next(iter(self._made)))
            self._made[what] = got
        return got

    def _run(self):
        while True:
            with self._lock:
                job, self._job = self._job, None
                if job is None or self.closed:
                    self._busy = False
                    return
            gen, (layers, sounds), levels, load = job
            beds_layers = {}
            for layer, tw in layers:
                loop = self._loop_for(("layer", layer, tw),
                                      lambda la=layer, t=dict(tw): render_layer(la, t))
                if loop is not None:
                    beds_layers[layer] = loop
            beds_sounds = []
            for (sid, tw), lvl in zip(sounds, levels):
                loop = self._loop_for(("sound", sid, tw),
                                      lambda s=sid, t=dict(tw), ld=load: _board_loop(ld, s, t))
                if loop is not None:
                    beds_sounds.append((sid, loop, float(lvl)))
            with self._lock:
                stale = gen != self._gen
            if not stale and not self.closed:
                try:
                    self.ready(Beds(beds_layers, tuple(beds_sounds), (layers, sounds)))
                except Exception as ex:  # noqa: BLE001
                    log.error("background sounds couldn't be handed over", exc_info=ex)
