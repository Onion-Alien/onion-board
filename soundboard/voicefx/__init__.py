"""Voice changer: a chain of real-time effects applied to the mic.

The engine calls `VoiceChain.process()` from the mic callback, before the audio is
resampled and handed to the outputs, so everyone (and you, in mic check) hears the
changed voice. The chain runs on the mono mic signal and returns stereo.

Effects are classes registered by type id. The built-in ones live in
`voicefx.builtin`; downloadable modules add more through the same `register()`
(see `soundboard.modules`). Each effect declares its parameters so the UI can
draw sliders for effects it has never heard of.

Thread safety follows the engine's rule: the audio thread never takes a lock. The
UI builds a new tuple of effects and swaps it in; parameter changes replace an
effect's whole `p` dict (one atomic attribute write).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from collections.abc import Callable

import numpy as np

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

    def clamp(self, v) -> float:
        try:
            v = float(v)
        except (TypeError, ValueError):
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

    def __init__(self, rate: int, values: dict | None = None):
        self.rate = rate
        self.p = self._values(values or {})

    def _values(self, values: dict) -> dict:
        return {q.key: q.clamp(values.get(q.key, q.default)) for q in self.params}

    def set_values(self, values: dict):
        self.p = self._values(values)      # one atomic swap, read once per block

    def run(self, x: np.ndarray, rate: int) -> np.ndarray:
        raise NotImplementedError


REGISTRY: dict[str, type[Effect]] = {}


def register(cls: type[Effect]) -> type[Effect]:
    """Make an effect type available (usable as a class decorator)."""
    if not cls.type or not cls.name:
        raise ValueError(f"{cls.__name__} needs a `type` and a `name`")
    if cls.type in REGISTRY and REGISTRY[cls.type] is not cls:
        log.warning("effect type %r registered twice; keeping the newer one", cls.type)
    REGISTRY[cls.type] = cls
    return cls


def defaults(etype: str) -> dict:
    return {q.key: q.default for q in REGISTRY[etype].params}


class VoiceChain:
    """The effects currently applied to the mic, in order.

    `configure(spec)` (UI thread) takes the saved settings:
        {"enabled": bool, "effects": {type: {"on": bool, param: value, ...}, ...}}
    and effects run in registry order (built-ins first, then modules' in load order).

    `tap` (optional) receives every raw mono block before the effects run; the live
    voice-to-speech feature uses it to listen. With `replace` set the chain outputs
    silence, so only the synthetic voice is heard."""

    def __init__(self):
        self.enabled = False
        self._spec: dict = {}
        self._effects: tuple[Effect, ...] = ()
        self._rate = 0
        self.tap: Callable[[np.ndarray, int], None] | None = None
        self.replace = False
        self.errors: dict[str, str] = {}      # effect type -> message (effect bypassed)

    # ------------------------------------------------------------ UI thread
    def configure(self, spec: dict):
        self._spec = spec or {}
        self.enabled = bool(self._spec.get("enabled"))
        self._rebuild(self._rate)

    def _rebuild(self, rate: int):
        wanted = self._spec.get("effects", {})
        old = {e.type: e for e in self._effects}
        new = []
        for etype, cls in REGISTRY.items():
            cfg = wanted.get(etype)
            if not cfg or not cfg.get("on") or etype in self.errors:
                continue
            e = old.get(etype)
            if e is None or e.rate != rate or type(e) is not cls:
                e = cls(rate, cfg)
            else:
                e.set_values(cfg)        # keep its state: no click when a slider moves
            new.append(e)
        self._effects = tuple(new)

    @property
    def active(self) -> bool:
        return (self.enabled and bool(self._effects)) or self.tap is not None or self.replace

    def clear_errors(self):
        self.errors.clear()
        self._rebuild(self._rate)

    # ------------------------------------------------------------ audio thread
    def process(self, x: np.ndarray, rate: int) -> np.ndarray:
        """(n, 2) float32 mic block -> (n, 2) float32. Called by the mic callback."""
        if rate != self._rate:          # first block, or the mic changed rate
            self._rate = rate
            self._rebuild(rate)
        tap, replace = self.tap, self.replace
        effects = self._effects if self.enabled else ()
        if not effects and tap is None and not replace:
            return x
        m = x[:, 0] if x.shape[1] == 1 else (x[:, 0] + x[:, 1]) * np.float32(0.5)
        m = np.ascontiguousarray(m, dtype=np.float32)
        if tap is not None:
            try:
                tap(m, rate)
            except Exception as ex:  # noqa: BLE001
                self.tap = None
                log.error("voice tap failed; detached", exc_info=ex)
        if replace:
            return np.zeros_like(x)
        for e in effects:
            try:
                y = e.run(m, rate)
                if y.shape != m.shape or not np.all(np.isfinite(y)):
                    raise ValueError(f"returned {y.shape} / non-finite audio")
                m = y.astype(np.float32, copy=False)
            except Exception as ex:  # noqa: BLE001
                # a broken effect is bypassed, never allowed to kill the mic stream
                self.errors[e.type] = str(ex)
                self._effects = tuple(f for f in self._effects if f is not e)
                log.error("voice effect %r failed; bypassed", e.type, exc_info=ex)
        out = np.empty((len(m), 2), np.float32)
        out[:, 0] = m
        out[:, 1] = m
        return out


from soundboard.voicefx import builtin  # noqa: E402,F401  (registers the built-ins)
from soundboard.voicefx.builtin import PRESET_ICONS, PRESETS  # noqa: E402

__all__ = ["Param", "Effect", "REGISTRY", "register", "defaults", "VoiceChain", "PRESETS",
           "PRESET_ICONS"]
