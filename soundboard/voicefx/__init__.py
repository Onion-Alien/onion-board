"""Voice changer: a chain of real-time effects applied to the mic.

The engine calls `VoiceChain.process()` from the mic callback, before the audio is
resampled and handed to the outputs, so everyone (and you, in mic check) hears the
changed voice. The chain runs on the mono mic signal and returns stereo.

Effects are classes registered by type id. The built-in ones live in
`voicefx.builtin`; downloadable modules add more through the same `register()`
(see `soundboard.addons.modules`). Each effect declares its parameters so the UI can
draw sliders for effects it has never heard of.

Thread safety follows the engine's rule: the audio thread never takes a lock. The
UI builds a new tuple of effects and swaps it in; parameter changes replace an
effect's whole `p` dict (one atomic attribute write).
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from collections.abc import Callable

import numpy as np

from soundboard.core import errors

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Param:
    key: str
    label: str
    lo: float
    hi: float
    default: float
    unit: str = ""
    step: float = 0.0     # 0 = continuous (the UI picks ~200 steps)
    ends: tuple[str, str] = ("", "")   # words under the slider's two ends, if any

    def clamp(self, v) -> float:
        try:
            v = float(v)
        except (TypeError, ValueError):
            return self.default
        if not math.isfinite(v):
            return self.default
        return min(max(v, self.lo), self.hi)


class Effect:
    """Base class. Subclasses set `type`, `name`, `params` and implement `run`.

    `run(x, rate)` gets a 1-D float32 block at the mic's rate and returns a block of
    the same length. It is called on the audio thread: no I/O, no locks, no
    unbounded work. State (filter memory, delay lines) lives on the instance; the
    chain makes a fresh instance whenever the mic's rate changes."""

    type: str = ""
    name: str = ""
    description: str = ""
    params: tuple[Param, ...] = ()
    # one of the Effects pop-up's copies, on top of the voice (no card in Edit voice)
    extra: bool = False

    def __init__(self, rate: int, values: dict | None = None):
        self.rate = rate
        self.p = self._values(values or {})

    def _values(self, values: dict) -> dict:
        return {q.key: q.clamp(values.get(q.key, q.default)) for q in self.params}

    def set_values(self, values: dict):
        self.p = self._values(values)      # one atomic swap, read once per block

    # Use less CPU (the Voice tab, on by itself in lite mode): an effect that has a
    # cheaper way (fewer bands, a smaller reverb, no hiss removal) takes it. Set by the
    # chain on the audio thread after the effect is made, and again when it flips.
    light = False

    def set_light(self, on: bool):
        self.light = bool(on)

    def run(self, x: np.ndarray, rate: int) -> np.ndarray:
        raise NotImplementedError

    def latency(self) -> float:
        """Seconds this effect delays the voice with its current settings (shown in
        the Voice tab). Most effects work sample by sample: 0."""
        return 0.0

    @classmethod
    def clean_extra(cls, cfg: dict) -> dict:
        """Settings of this effect that aren't numbers (lists, names), cleaned from a
        saved one (`clean_spec`). Most effects have none: {}."""
        return {}


REGISTRY: dict[str, type[Effect]] = {}

_light = False   # Use less CPU: read by every chain on its next mic block


def set_light(on: bool):
    """(Any thread.) Use less CPU on or off for every voice chain (one write)."""
    global _light
    _light = bool(on)


def light() -> bool:
    return _light


def register[E: Effect](cls: type[E]) -> type[E]:
    """Make an effect type available (usable as a class decorator)."""
    if not cls.type or not cls.name:
        raise ValueError(f"{cls.__name__} needs a `type` and a `name`")
    for q in cls.params:
        # the UI divides by the range and the step: a slider with no room to move
        # would stop the Voice tab from opening
        if not (isinstance(q, Param) and all(math.isfinite(float(n))
                                             for n in (q.lo, q.hi, q.default, q.step))
                and q.lo < q.hi and 0 <= q.step <= q.hi - q.lo):
            raise ValueError(f"{cls.__name__}: parameter {getattr(q, 'key', q)!r} needs "
                             "lo < hi and a step between 0 and hi - lo")
    if cls.type in REGISTRY and REGISTRY[cls.type] is not cls:
        log.warning("effect type %r registered twice; keeping the newer one", cls.type)
    REGISTRY[cls.type] = cls
    return cls


# built-in voices that were renamed: old saved name -> new name (an older version
# reading the new name shows Custom with the same effects, so nothing is lost)
RENAMED = {"Female voice": "High voice"}
# effects that were taken out, still found in older settings, saved voices and codes:
# dropped quietly ("cleanup", Clean up my mic: Clean mic on the Voice tab does it now)
RETIRED = frozenset({"cleanup"})


def _number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def clean_spec(raw) -> dict:
    """Saved voice changer settings (config or an imported backup) cut down to the
    shape the voice panel and `VoiceChain` expect: {"enabled": bool, "preset": str,
    "effects": {type: {"on": bool, param: number, ...}}, "custom": {like effects}}.
    Anything of the wrong type is dropped, so it falls back to its default instead of
    stopping the app."""
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    if isinstance(raw.get("enabled"), bool):
        out["enabled"] = raw["enabled"]
    if isinstance(raw.get("preset"), str):
        out["preset"] = RENAMED.get(raw["preset"], raw["preset"])
    def effects(v):
        out = {t: {k: x for k, x in cfg.items()
                   if isinstance(k, str) and (isinstance(x, bool) if k == "on" else _number(x))}
               for t, cfg in (v.items() if isinstance(v, dict) else ())
               if isinstance(t, str) and isinstance(cfg, dict) and t not in RETIRED}
        for t, cfg in out.items():
            cls = REGISTRY.get(t)
            if cls is not None:
                try:
                    cfg.update(cls.clean_extra(v[t]))
                except Exception as ex:  # noqa: BLE001 - an add-on's: its extras are dropped
                    log.warning("effect %r: its other settings couldn't be read: %s", t, ex)
        return out
    out["effects"] = effects(raw.get("effects"))
    if isinstance(raw.get("custom"), dict):   # "My own mix", kept while a preset is on
        out["custom"] = effects(raw["custom"])
    favs = raw.get("favorites")   # the starred voices, in the order they were starred
    if isinstance(favs, list):
        out["favorites"] = list(dict.fromkeys(n for n in favs
                                               if isinstance(n, str) and n))[:200]
    size = raw.get("panel_size")   # the Edit voice window's [width, height]
    if isinstance(size, list) and len(size) == 2 and all(
            isinstance(n, int) and not isinstance(n, bool) for n in size):
        out["panel_size"] = [min(max(size[0], 360), 4000), min(max(size[1], 300), 4000)]
    return out


# the Background's sounds: yours, not the voice's (kept when you pick another voice)
KEEP = frozenset({"backdrop"})


def on_top(etype: str) -> bool:
    """On top of the voice, not part of it: the Background and the Effects pop-up's
    extras. They also play on the AI voice with the voice changer off."""
    cls = REGISTRY.get(etype)
    return etype in KEEP or bool(getattr(cls, "extra", False))


def defaults(etype: str) -> dict:
    return {q.key: q.default for q in REGISTRY[etype].params}


class VoiceChain:
    """The effects currently applied to the mic, in order.

    `configure(spec)` (UI thread) takes the saved settings:
        {"enabled": bool, "effects": {type: {"on": bool, param: value, ...}, ...}}
    and effects run in registry order (built-ins first, then modules' in load order).

    `tap` (optional) receives every raw mono block before the effects run; the live
    voice-to-speech feature uses it to listen. With `replace` set the chain outputs
    silence, so only the synthetic voice is heard.

    `source` (optional, the AI voice: soundboard.speech.aivoice.VoiceSource) has
    `process(mono, rate) -> mono` and `latency()`: its output replaces your voice,
    and the effects that are on then run on that. With the voice changer off, the ones
    on top of the voice (`on_top`: rain, an echo) still do.

    Clean mic (`set_clean`, voicefx.cleanmic) runs before all of it, whether or not a
    voice is on: noise out of your mic, the voices and the tap get the cleaned one."""

    def __init__(self):
        self.enabled = False
        self._spec: dict = {}
        self._effects: tuple[Effect, ...] = ()
        self._top: tuple[Effect, ...] = ()   # those of _effects on top of the voice
        self._rate = 0
        # Only the audio thread builds the effects (process). The UI thread posts a new
        # spec and bumps _gen; process() rebuilds when _gen moved past _built. (Built on
        # both threads, the UI could install effects made for the mic's old rate, which
        # process() then never rebuilt, or undo the mic thread's bypass of a broken one.)
        self._gen = 0
        self._built = 0
        self._light = False   # Use less CPU as the effects were last told
        self.tap: Callable[[np.ndarray, int], None] | None = None
        self.replace = False
        self.source = None
        self.errors: dict[str, str] = {}      # effect type -> message (effect bypassed)
        self.beds = None    # voicefx.backdrop.Beds: the Background's loops, made ahead
        # Clean mic: the strength wanted (None: off), posted like the spec; the audio
        # thread makes the Cleaner. Its failure goes in clean_error, not errors (which
        # the voice changer lists as its effects')
        self._clean_want: str | None = None
        self._clean_opts: dict = {}   # cleanmic.options(): volume, sensitivity, AGC
        self._clean_gen = 0
        self._clean_built = 0
        self.cleaner = None   # voicefx.cleanmic.Cleaner, the audio thread's
        self.clean_error = ""

    # ------------------------------------------------------------ UI thread
    def configure(self, spec: dict):
        """Post new settings: the next mic block (process) builds the effects for them."""
        spec = spec or {}
        self._spec = spec   # first the spec, then the bump: process() never misses it
        self.enabled = bool(spec.get("enabled"))
        self._gen += 1

    def set_clean(self, on: bool, strength: str = "normal", opts: dict | None = None):
        """(UI thread.) Clean mic on (at that strength, with cleanmic.options() `opts`)
        or off, from the next mic block."""
        self._clean_opts = dict(opts or {})   # first the options, then the strength
        self._clean_want = strength if on else None
        self.clean_error = ""
        self._clean_gen += 1

    @property
    def clean_on(self) -> bool:
        """Clean mic is switched on (it may still be starting, or have failed)."""
        return self._clean_want is not None

    def clean_level(self) -> float:
        """The cleaned mic's last peak (0 while Clean mic is off), for its meter."""
        c = self.cleaner
        return c.level if c is not None else 0.0

    def _rebuild_clean(self, rate: int):
        """(Audio thread, in process.) The Cleaner for the wanted strength and `rate`."""
        want, opts, old = self._clean_want, self._clean_opts, self.cleaner
        if want is not None and old is not None and old.rate == rate:
            old.set_options(opts)
            old.set_strength(want)
            return
        self.cleaner = None
        if old is not None:
            old.close()
        if want is None or not rate:
            return
        from soundboard.voicefx import cleanmic
        try:
            self.cleaner = cleanmic.Cleaner(rate, want, opts)
        except Exception as ex:  # noqa: BLE001 - the mic goes on uncleaned
            self.clean_error = errors.plain(ex)
            log.error("Clean mic failed to start", exc_info=ex)

    def _rebuild(self, rate: int):
        """(Audio thread, in process.) The effects the spec asks for, made for `rate`."""
        if not rate:
            self._set_effects(())
            return
        wanted = self._spec.get("effects", {})
        old = {e.type: e for e in self._effects}
        new = []
        for etype, cls in REGISTRY.items():
            cfg = wanted.get(etype)
            if not cfg or not cfg.get("on") or etype in self.errors:
                continue
            e = old.get(etype)
            try:
                if e is None or e.rate != rate or type(e) is not cls:
                    e = cls(rate, cfg)
                else:
                    e.set_values(cfg)    # keep its state: no click when a slider moves
            except Exception as ex:  # noqa: BLE001
                # like a failing run(): the effect is left out and the voice panel
                # shows why (runs on the mic thread too, when the mic's rate changes)
                self.errors[etype] = errors.plain(ex)
                log.error("voice effect %r failed to start; bypassed", etype, exc_info=ex)
                continue
            if hasattr(e, "beds"):
                e.beds = self.beds  # pyright: ignore[reportAttributeAccessIssue] - the Background's
            new.append(e)
        self._set_effects(tuple(new))
        self._light = _light
        self._tell_light()

    def _tell_light(self):
        """(Audio thread.) Each effect told whether to use less CPU; one that fails
        is bypassed, like a failing run()."""
        for e in self._effects:
            tell = getattr(e, "set_light", None)   # (an add-on's own class may not have it)
            if tell is None or getattr(e, "light", False) == self._light:
                continue
            try:
                tell(self._light)
            except Exception as ex:  # noqa: BLE001
                self.errors[e.type] = errors.plain(ex)
                self._drop(e)
                log.error("voice effect %r failed to switch Use less CPU; bypassed", e.type,
                          exc_info=ex)

    def _set_effects(self, effects: tuple[Effect, ...]):
        """(Audio thread.) The effects to run, and which of them are on top."""
        self._effects = effects
        self._top = tuple(e for e in effects if on_top(e.type))

    def _drop(self, e: Effect):
        """(Audio thread.) A broken effect left out."""
        self._set_effects(tuple(f for f in self._effects if f is not e))

    def _running(self) -> tuple[Effect, ...]:
        """The effects that run now: all of them while the voice changer is on, only
        the ones on top of the voice for the AI voice alone."""
        return self._effects if self.enabled else self._top if self.source is not None else ()

    def set_beds(self, beds):
        """(Any thread.) The Background's loops, made by voicefx.backdrop.Maker: handed
        to the effect now and to any it's rebuilt as later (one attribute write each)."""
        self.beds = beds
        for e in self._effects:
            if hasattr(e, "beds"):
                e.beds = beds  # pyright: ignore[reportAttributeAccessIssue] - the Background's

    @property
    def active(self) -> bool:
        return ((self.enabled and bool(self._effects)) or self.tap is not None or self.replace
                or self.source is not None or self._clean_want is not None)

    @property
    def changes_voice(self) -> bool:
        """Others hear another voice than yours (an effect, the AI voice, a replacement)."""
        return (self.enabled and bool(self._effects)) or self.replace or self.source is not None

    def latency(self) -> float:
        """Seconds the effects that are on (and the AI voice) add to your voice right now."""
        total = 0.0
        c = self.cleaner
        if c is not None:
            total += c.latency()
        src = self.source
        if src is not None:
            try:
                total += max(0.0, float(src.latency()))
            except Exception:  # noqa: BLE001
                pass
        for e in self._running():
            try:
                total += max(0.0, float(e.latency()))
            except Exception:  # noqa: BLE001 - an add-on's: just not counted
                pass
        return total

    def clear_errors(self):
        self.errors.clear()
        self._gen += 1   # the next mic block gives the bypassed effects another go
        if self.clean_error:
            self.clean_error = ""
            self._clean_gen += 1

    def render(self, mono: np.ndarray, rate: int, block: int = 1024) -> np.ndarray:
        """A whole clip (the computer voice's line) through the voice changer, with its
        own fresh effects so the mic's running ones keep their state. Off, or no
        effect on: the clip as it is. A failing effect is left out, as on the mic."""
        if not self.enabled:
            return mono
        effects = []
        for etype, cls in REGISTRY.items():
            cfg = self._spec.get("effects", {}).get(etype)
            if cfg and cfg.get("on") and etype not in self.errors:
                try:
                    effect = cls(rate, cfg)
                    if hasattr(effect, "beds"):
                        effect.beds = self.beds  # pyright: ignore[reportAttributeAccessIssue] - Background loops
                    effects.append(effect)
                except Exception:  # noqa: BLE001
                    log.warning("voice effect %r couldn't start for the computer voice",
                                etype, exc_info=True)
        if not effects:
            return mono
        # the effects that delay the voice (pitch, formants, hiss removal) still hold
        # the line's last ~60-80 ms when the clip runs out: run that much silence
        # through after it, then drop the same amount from the start, so the whole
        # line comes out, lined up and the same length as it went in
        lag = 0
        for e in effects:
            try:
                lag += max(0, int(round(float(e.latency()) * rate)))
            except Exception:  # noqa: BLE001 - an add-on's: not counted
                pass
        m = np.ascontiguousarray(mono, dtype=np.float32)
        n = len(m)
        if lag:
            m = np.concatenate([m, np.zeros(lag, np.float32)])
        out = np.empty_like(m)
        for i in range(0, len(m), block):
            y = m[i:i + block]
            for e in list(effects):
                try:
                    z = e.run(y, rate)
                    if z.shape != y.shape or not np.all(np.isfinite(z)):
                        raise ValueError("bad output")
                    y = z.astype(np.float32, copy=False)
                except Exception:  # noqa: BLE001
                    effects.remove(e)
                    log.warning("voice effect %r failed on the computer voice", e.type,
                                exc_info=True)
            out[i:i + len(y)] = y
        return out[lag:lag + n] if lag else out

    # ------------------------------------------------------------ audio thread
    def process(self, x: np.ndarray, rate: int) -> np.ndarray:
        """(n, 2) float32 mic block -> (n, 2) float32. Called by the mic callback."""
        if not len(x):
            # an empty block (a device can hand one over): many effects measure the
            # block's level or last sample and would fail on it, which bypasses them
            # for good (a changed voice would turn back into yours mid-call)
            return np.zeros((0, 2), np.float32)
        gen = self._gen
        if rate != self._rate or gen != self._built:   # first block, new rate or settings
            # (the bump is read before the spec: a configure meanwhile rebuilds next block)
            self._rate, self._built = rate, gen
            self._rebuild(rate)
        if self._light != _light:
            self._light = _light
            self._tell_light()
        cgen = self._clean_gen
        if cgen != self._clean_built or (self.cleaner is not None and self.cleaner.rate != rate):
            self._clean_built = cgen
            self._rebuild_clean(rate)
        tap, replace, src, cleaner = self.tap, self.replace, self.source, self.cleaner
        effects = self._effects if self.enabled else self._top if src is not None else ()
        if not effects and tap is None and not replace and src is None and cleaner is None:
            return x
        m = x[:, 0] if x.shape[1] == 1 else (x[:, 0] + x[:, 1]) * np.float32(0.5)
        m = np.ascontiguousarray(m, dtype=np.float32)
        if cleaner is not None:
            try:
                y = cleaner.process(m)
                if y.shape != m.shape or not np.all(np.isfinite(y)):
                    raise ValueError(f"returned {y.shape} / non-finite audio")
                m = y
            except Exception as ex:  # noqa: BLE001 - never kills the mic: it goes on uncleaned
                self.cleaner = None
                self.clean_error = errors.plain(ex)
                log.error("Clean mic failed; off", exc_info=ex)
        if tap is not None:
            try:
                tap(m, rate)
            except Exception as ex:  # noqa: BLE001
                self.tap = None
                log.error("voice tap failed; detached", exc_info=ex)
        if replace:
            return np.zeros_like(x)
        if src is not None:
            try:
                y = src.process(m, rate)
                if y.shape != m.shape:
                    raise ValueError(f"returned {y.shape}")
                m = y.astype(np.float32, copy=False)
            except Exception as ex:  # noqa: BLE001
                # never your real voice by accident: silence for this block, and the
                # source is dropped (the AI voice panel shows it stopped)
                self.source = None
                self.errors["ai-voice"] = errors.plain(ex)
                log.error("AI voice failed; detached", exc_info=ex)
                return np.zeros_like(x)
        for e in effects:
            try:
                y = e.run(m, rate)
                if y.shape != m.shape or not np.all(np.isfinite(y)):
                    raise ValueError(f"returned {y.shape} / non-finite audio")
                m = y.astype(np.float32, copy=False)
            except Exception as ex:  # noqa: BLE001
                # a broken effect is bypassed, never allowed to kill the mic stream
                self.errors[e.type] = errors.plain(ex)
                self._drop(e)
                log.error("voice effect %r failed; bypassed", e.type, exc_info=ex)
        out = np.empty((len(m), 2), np.float32)
        out[:, 0] = m
        out[:, 1] = m
        return out


from soundboard.voicefx import builtin  # noqa: E402,F401  (registers the built-ins)
from soundboard.voicefx.builtin import PRESET_ICONS, PRESETS  # noqa: E402

_shown: tuple[str, dict[str, str]] = ("", {})   # (language, shown_texts()) last built


def shown(text: str) -> str:
    """How an effect's name, description, setting or slider-end word, or a built-in
    voice's name, reads in the app's language. `text` is the English the code and the
    saved settings use (it stays the key); an add-on's own text comes back as it is."""
    global _shown
    from soundboard import i18n
    lang = i18n.current()
    if _shown[0] != lang or not _shown[1]:
        _shown = (lang, builtin.shown_texts())
    return _shown[1].get(text, text)


__all__ = ["Param", "Effect", "REGISTRY", "register", "defaults", "clean_spec", "on_top",
           "VoiceChain", "PRESETS", "PRESET_ICONS", "shown"]
