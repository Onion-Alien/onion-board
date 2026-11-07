"""The usage count's message: one send as named events with real fields, not one string each.

    {"schema": 2, "app": "board", "version": "2.9.0", "os": "win11",
     "install": "u-0123456789ab", "run": "r-0123456789ab",
     "events": [{"name": "error", "level": "error", "t": 1762500000, "count": 3,
                 "attrs": {"type": "KeyError", "file": "soundboard/audio/engine.py",
                           "line": 1090, "func": "play", "stack": ["..."]}}]}

`install` is the short tag made from this PC's random ID and `run` a random ID for this
start of the app, kept in memory only. `t` is rounded to TIME_STEP_S, so events keep their
order and rough time without a precise record of someone's day. An attribute is a word we
made, a number, a yes or a list of words: never a message, a path outside this app's own
code, or anything typed (except what usagetags.other_tag tidied). Pure functions: nothing
here sends anything."""
from __future__ import annotations

import json
import time
import uuid

from soundboard import __version__
from soundboard.core.usagetags import os_tag

SCHEMA = 2
APP = "board"
TIME_STEP_S = 600
MAX_STACK = 16   # frames of our own code per error, the deepest ones
MAX_COUNT = 1_000_000
RUN = "r-" + uuid.uuid4().hex[:12]   # this start of the app; never saved

# what a count can say; the server takes any name of this shape
DAILY = "daily"
FEATURE_USED = "feature.used"   # `count` is how many times since the last send
FEATURE_ON = "feature.on"       # set up, counted every day it is
TAB = "tab.opened"
LOG_ERROR = "log.error"       # a line the app logged as an error (usagelog.py)
LOG_WARNING = "log.warning"
RUN_START = "run.start"
RUN_END = "run.end"           # a clean quit; `lasted` is how long it ran, roughly

# how bad an event is, like a log's levels; anything not named here is "info"
ERRORS = frozenset(("crash", "error", "freeze", "unclean_exit", "startup_failed", LOG_ERROR))
WARNINGS = frozenset(("warned", "failed", "problems_dropped", LOG_WARNING))


def level_of(name: str) -> str:
    return "error" if name in ERRORS else "warn" if name in WARNINGS else "info"


def rounded(when: float | None = None) -> int:
    """A time as whole TIME_STEP_S (unix seconds, UTC)."""
    now = time.time() if when is None else when
    return int(now // TIME_STEP_S * TIME_STEP_S)


def event(name: str, *, at: float | None = None, count: int = 1, **attrs) -> dict:
    """One event. Empty attributes (no value, no, nothing known) are left out."""
    out: dict = {"name": name, "level": level_of(name), "t": rounded(at)}
    if count > 1:
        out["count"] = min(int(count), MAX_COUNT)
    kept = {k: v for k, v in attrs.items() if v not in ("", None, [], False)}
    if kept:
        out["attrs"] = kept
    return out


def worst_first(events: list[dict], limit: int) -> list[dict]:
    """A list about to be cut at `limit`: errors, then warnings, then the rest, each in the
    order they came, so a lot of warnings never push out a crash. As it is if it all fits."""
    if len(events) <= limit:
        return events
    rank = {"error": 0, "warn": 1}
    return sorted(events, key=lambda e: rank.get(e.get("level", ""), 2))


def older(raw: str) -> dict:
    """A count an older version left waiting in config.json, as the name it would have sent."""
    return {"name": "older", "level": "info", "attrs": {"raw": raw}}


def place(frames: list[str]) -> dict:
    """The attributes for our own frames (`soundboard/x.py:12:play`, outermost first): the
    deepest one's file, line and function, and the chain when there's more than one."""
    if not frames:
        return {}
    file, line, func = (frames[-1].split(":", 2) + ["", ""])[:3]
    out: dict = {"file": file, "line": int(line) if line.isdigit() else 0, "func": func}
    if len(frames) > 1:
        out["stack"] = frames[-MAX_STACK:]
    return out


def merged(events: list[dict]) -> list[dict]:
    """The same event twice as one with a count: a bug in a loop is one line, "3 times"."""
    out: dict[str, dict] = {}
    for e in events:
        key = json.dumps([e.get("name"), e.get("attrs")], sort_keys=True)
        have = out.get(key)
        if have is None:
            out[key] = dict(e)
        else:
            have["count"] = min(have.get("count", 1) + e.get("count", 1), MAX_COUNT)
    return list(out.values())


def message(events: list[dict], install: str = "", run: str = "") -> dict:
    """One request's body. No `install` or `run` when it has none: an opt-out can't be tied
    to anything, and the feedback picks carry a one-off tag and no run."""
    out: dict = {"schema": SCHEMA, "app": APP, "version": __version__, "os": os_tag()}
    if install:
        out["install"] = install
    if run:
        out["run"] = run
    out["events"] = events
    return out
