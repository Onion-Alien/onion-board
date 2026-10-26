"""The control API's small helpers for reading a request's values: on= switches, numbers,
volume boxes, and finding a sound or category by name (`remote` re-exports them)."""
from __future__ import annotations

import difflib
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow


def on_value(params: dict, now: bool) -> bool | None:
    """?on=1 / 0 / toggle (or nothing: toggle) -> the new state; None if it's neither."""
    v = (params.get("on") or "toggle").strip().lower()
    if v in ("1", "true", "on", "yes"):
        return True
    if v in ("0", "false", "off", "no"):
        return False
    return not now if v == "toggle" else None


BAD_ON = {"error": "on= takes 1, 0 or toggle"}


def no_sound(cfg, params: dict) -> tuple[int, dict]:
    """The answer when ?id= / ?name= names no sound."""
    if not params:
        return 400, {"error": "say which: ?id=… or ?name=…"}
    body = {"error": "no such sound"}
    if params.get("name"):   # a typo'd button: say what it probably meant
        close = difflib.get_close_matches(params["name"].strip(),
                                          [s.name for s in cfg.sounds], 3, 0.5)
        if close:
            body["did_you_mean"] = close
    return 404, body


def set_volume(spin, params: dict) -> tuple[int, dict] | None:
    """?set=0-<the box's maximum> / ?step=up|down (10 % a step) on a volume box: an error answer, or
    None once it's set."""
    step = (params.get("step") or "").strip().lower()
    if "set" in params:
        try:
            new = round(float(params["set"]))
        except (ValueError, OverflowError):   # "loud", nan / inf, 1e999
            return 400, {"error": f"set= takes a number, 0-{spin.maximum()}"}
    elif step in ("up", "down", "+", "-"):
        new = (round(spin.value() / 10) + (1 if step in ("up", "+") else -1)) * 10
    else:
        return 400, {"error": f"say how: ?set=0-{spin.maximum()} or ?step=up / down"}
    spin.setValue(min(max(new, 0), spin.maximum()))
    return None


def number(params: dict, key: str, lo: float, hi: float) -> float | None:
    """params[key] as a number kept within lo..hi; None if it isn't one."""
    try:
        v = float(params[key])
    except (KeyError, TypeError, ValueError):
        return None
    return None if math.isnan(v) else min(max(v, lo), hi)


def find_category(cfg, name: str) -> str | None:
    """A category by name, any case; None if there's no such one."""
    name = name.strip().lower()
    return next((c for c in cfg.categories if c.lower() == name), None)


def find_sound(mw: MainWindow, params: dict):
    if params.get("id"):
        return mw.meta(params["id"])
    name = (params.get("name") or "").strip().lower()
    if name:
        return next((m for m in mw.cfg.sounds if m.name.lower() == name), None)
    return None
