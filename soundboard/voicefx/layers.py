"""Layers: other voices mixed in on top of yours, and the order your effects run in.

A voice's effects ({type: settings}) may hold one more entry under `KEY`:

    {"order": [type, ...],           # your effects' order (the rest follow as before)
     "stack": [{"voice": str,        # the voice it came from ("" for added effects)
                "on": bool,
                "amount": 0..1,      # how much of it you hear (1: all of it)
                "effects": {type: settings}}, ...]}

Each layer runs after your own effects (before Voice blend & output), as a chain of its
own, so a layer may have effects your voice already has (Duck's pitch and Robot's
pitch both play). Its amount blends it with what went in, lined up for its delay.

Versions without layers drop the entry as an effect they don't have: the voice loads
with its own effects, and a code's note names "layers" as left out.
"""
from __future__ import annotations

import numpy as np

from soundboard.voicefx import REGISTRY, Effect

KEY = "layers"
MAX_LAYERS = 8
MAX_NAME = 32


def _amount(v) -> float:
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v:
        return min(max(float(v), 0.0), 1.0)
    return 1.0


def clean(raw, clean_effects) -> dict:
    """A saved `KEY` entry cut down to its shape ({} when there's nothing in it).
    `clean_effects` cleans one layer's {type: settings} (voicefx.clean_spec's)."""
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    order = raw.get("order")
    if isinstance(order, list):
        seen = list(dict.fromkeys(t for t in order if isinstance(t, str) and t != KEY))
        if seen:
            out["order"] = seen[:64]
    stack = []
    given = raw.get("stack")
    for d in given if isinstance(given, list) else ():
        fx = d.get("effects") if isinstance(d, dict) else None
        if not isinstance(fx, dict):
            continue
        effects = clean_effects({t: c for t, c in fx.items() if t != KEY})
        voice = d.get("voice")
        stack.append({"voice": " ".join(voice.split())[:MAX_NAME]
                      if isinstance(voice, str) else "",
                      "on": d.get("on") is not False,
                      "amount": _amount(d.get("amount", 1.0)),
                      "effects": effects})
    if stack:
        out["stack"] = stack[:MAX_LAYERS]
    return out


def of(effects: dict) -> dict:
    """The `KEY` entry of a voice's effects ({} when it has none)."""
    mix = (effects or {}).get(KEY)
    return mix if isinstance(mix, dict) else {}


def playing(effects: dict) -> list[dict]:
    """The layers that are on and have an effect on, with their amount above 0."""
    return [d for d in of(effects).get("stack", ())
            if isinstance(d, dict) and d.get("on", True) and _amount(d.get("amount", 1)) > 0
            and any(isinstance(c, dict) and c.get("on")
                    for c in (d.get("effects") or {}).values())]


def all_effects(effects: dict) -> list[tuple[str, dict]]:
    """(type, settings) of a voice's own effects and every playing layer's."""
    own = [(t, c) for t, c in (effects or {}).items() if t != KEY]
    return own + [(t, c) for d in playing(effects) for t, c in d["effects"].items()]


def ordered(types, order) -> list[str]:
    """`types` in the voice's order: those named in `order` first, as it has them, then
    the rest as they were; Voice blend & output always last."""
    types = list(types)
    rank: dict[str, int] = {t: i for i, t in enumerate(order or ())}
    return sorted(types, key=lambda t: (t == "voice_output",
                                        rank.get(t, len(rank)), types.index(t)))


class Layer(Effect):
    """One layer as one step of the chain: its effects, blended by its amount."""

    type = "layer"
    name = "Layer"

    def __init__(self, rate: int, index: int):
        super().__init__(rate)
        self.index = index
        self.type = f"layer{index + 1}"
        self.effects: tuple[Effect, ...] = ()
        self.amount = 1.0
        self._amount = 1.0
        self._line: np.ndarray = np.zeros(0, np.float32)
        self.errors: dict[str, str] = {}

    def update(self, entry: dict, order, failed) -> None:
        """(The thread that builds the chain.) Its effects for this entry, keeping the
        ones it has (no click when a slider moves). `failed(type, ex)` is told about one
        that won't start."""
        wanted = entry.get("effects") or {}
        old = {e.type: e for e in self.effects}
        new = []
        for etype in ordered((t for t in REGISTRY if t != KEY), order):
            cfg = wanted.get(etype)
            if not isinstance(cfg, dict) or not cfg.get("on"):
                continue
            cls = REGISTRY[etype]
            e = old.get(etype)
            try:
                if e is None or e.rate != self.rate or type(e) is not cls:
                    e = cls(self.rate, cfg)
                else:
                    e.set_values(cfg)
            except Exception as ex:  # noqa: BLE001 - left out, as on your own chain
                self.errors[etype] = str(ex)
                failed(etype, ex)
                continue
            new.append(e)
        self.effects = tuple(new)
        self.amount = _amount(entry.get("amount", 1.0))

    def set_light(self, on: bool):
        super().set_light(on)
        for e in self.effects:
            tell = getattr(e, "set_light", None)
            if tell is not None:
                tell(on)

    def latency(self) -> float:
        total = 0.0
        for e in self.effects:
            try:
                total += max(0.0, float(e.latency()))
            except Exception:  # noqa: BLE001 - an add-on's: not counted
                pass
        return total

    def run(self, x: np.ndarray, rate: int) -> np.ndarray:
        y = x
        for e in self.effects:
            try:
                z = e.run(y, rate)
                if z.shape != y.shape or not np.isfinite(z).all():
                    raise ValueError(f"returned {z.shape} / non-finite audio")
                y = z.astype(np.float32, copy=False)
            except Exception as ex:  # noqa: BLE001 - that effect is left out
                self.errors[e.type] = str(ex)
                self.effects = tuple(f for f in self.effects if f is not e)
        a0, a1 = self._amount, self.amount
        self._amount = a1
        if a0 >= 1.0 and a1 >= 1.0:
            self._line = np.zeros(0, np.float32)
            return y
        dry = self._aligned(x, max(0, round(self.latency() * rate)))
        amount = np.linspace(a0, a1, len(y), dtype=np.float32) if a0 != a1 else np.float32(a1)
        return (dry + (y - dry) * amount).astype(np.float32, copy=False)

    def _aligned(self, x: np.ndarray, delay: int) -> np.ndarray:
        """`x` delayed by `delay` samples, so it lines up with the layer's effects."""
        if not delay:
            self._line = np.zeros(0, np.float32)
            return x
        if len(self._line) != delay:
            self._line = np.zeros(delay, np.float32)
        both = np.concatenate([self._line, x])
        self._line = both[len(x):].copy()
        return both[:len(x)]
