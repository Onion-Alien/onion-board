"""The usage count's message: one send as named events with real fields, not one string each.

    {"schema": 2, "app": "board", "version": "2.9.0", "os": "win11",
     "install": "u-0123456789ab", "run": "r-0123456789ab",
     "events": [{"name": "error", "level": "error", "t": 1762500000, "count": 3,
                 "seq": 7, "since_start_s": 84.2,
                 "ctx": {"screen": "sounds", "lite": true, "route": "mic", "mem": 60},
                 "attrs": {"type": "KeyError", "file": "soundboard/audio/engine.py",
                           "line": 1090, "func": "play", "stack": ["..."],
                           "trace": ["..."], "thread": "MainThread"}}]}

`install` is the short tag made from this PC's random ID and `run` a random ID for this
start of the app, kept in memory only. `t` is rounded to TIME_STEP_S, so events keep their
order and rough time without a precise record of someone's day. For timing instead, an
event made during this run says how far into the run it was (`since_start_s`, seconds
since the app's process started) and its place in the run (`seq`, 1 for the first), so
one run's events read in order; a problem also says what the app was doing (`ctx`: the
tab on screen, Lite mode, where sounds go, how full the PC's memory was, the add-ons
loaded). An event kept for a later run says which run it came from (`from_run`).
An attribute is a word we made, a number, a yes or a list of words: never a message, a
path outside this app's own code, or anything typed (except what usagetags.other_tag
tidied). Whole stacks: usagetrace.py. Pure functions: nothing here sends anything."""
from __future__ import annotations

import itertools
import json
import sys
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
RUN_READY = "run.ready"       # the window is up (or the tray icon): `startup_s` it took
RUN_END = "run.end"           # a clean quit; `lasted` is how long it ran, roughly
TIMING = "timing"             # how long something took, `n` times since the last send

# how bad an event is, like a log's levels; anything not named here is "info"
ERRORS = frozenset(("crash", "error", "freeze", "unclean_exit", "startup_failed", LOG_ERROR))
WARNINGS = frozenset(("warned", "failed", "problems_dropped", LOG_WARNING))

# made in this run only: never on an event about an earlier run (a saved report), and left
# out of a message with no run (an opt-out, the feedback picks)
RUN_FIELDS = ("seq", "since_start_s", "ctx", "from_run")
WITH_CTX = frozenset((RUN_END, RUN_READY))   # besides every error and warning


def _process_age() -> float:
    """How long ago this process started, in seconds (Windows' own record of it), or 0
    where unknown: then times count from this module's import, early in the start."""
    if sys.platform != "win32":
        return 0.0
    try:
        import ctypes
        from ctypes import wintypes
        # its own copy: argtypes set on the shared windll.kernel32 change every other
        # module's calls too (the app audio code passes its own pointer types)
        k32 = ctypes.WinDLL("kernel32")
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.GetProcessTimes.argtypes = (wintypes.HANDLE, *[ctypes.POINTER(wintypes.FILETIME)] * 4)
        k32.GetProcessTimes.restype = wintypes.BOOL
        times = [wintypes.FILETIME() for _ in range(4)]   # created, exited, kernel, user
        now = wintypes.FILETIME()
        if not k32.GetProcessTimes(k32.GetCurrentProcess(), *map(ctypes.byref, times)):
            return 0.0
        k32.GetSystemTimeAsFileTime(ctypes.byref(now))

        def secs(ft):
            return ((ft.dwHighDateTime << 32) | ft.dwLowDateTime) / 1e7
        age = secs(now) - secs(times[0])
        return age if 0 <= age < 3600 else 0.0
    except Exception:  # noqa: BLE001 - only a nicety
        return 0.0


_AGE = _process_age()
BORN_MONO = time.monotonic() - _AGE   # when this process started, on both clocks
BORN_WALL = time.time() - _AGE
_seq = itertools.count(1)   # next() is atomic under the GIL: any thread may make an event
_context: dict = {}         # set_context
_memory: list = [None, None]   # (when, bucket): memory_bucket asks Windows every 30 s at most
MEMORY_EVERY_S = 30


def since_start(at: float | None = None) -> float:
    """Seconds from this process's start to `at` (a time.time()), or to now."""
    return (time.monotonic() - BORN_MONO) if at is None else (at - BORN_WALL)


def set_context(**words) -> None:
    """What the app is doing, for the `ctx` of the problems from now on: `screen` (a tab's
    key), `lite`, `route`, `addons` (a list). Only fixed words, yes and numbers; an empty
    one (no, nothing) is taken away."""
    for k, v in words.items():
        if v in (None, "", False, [], ()):
            _context.pop(k, None)
        else:
            _context[k] = list(v) if isinstance(v, (list, tuple)) else v


def memory_bucket() -> int | None:
    """How full the PC's memory is, in tens of percent (`60` for 60-69%), or None."""
    now = time.monotonic()
    if _memory[0] is None or now - _memory[0] > MEMORY_EVERY_S:
        try:
            from soundboard.core.hangwatch import memory_load
            load = memory_load()
        except Exception:  # noqa: BLE001 - only a nicety
            load = None
        _memory[:] = [now, None if load is None else min(int(load), 99) // 10 * 10]
    return _memory[1]


def context() -> dict:
    """`ctx` for a problem made now."""
    out = dict(_context)
    mem = memory_bucket()
    if mem is not None:
        out["mem"] = mem
    return out


def level_of(name: str) -> str:
    return "error" if name in ERRORS else "warn" if name in WARNINGS else "info"


def rounded(when: float | None = None) -> int:
    """A time as whole TIME_STEP_S (unix seconds, UTC)."""
    now = time.time() if when is None else when
    return int(now // TIME_STEP_S * TIME_STEP_S)


def event(name: str, *, at: float | None = None, count: int = 1, **attrs) -> dict:
    """One event. Empty attributes (no value, no, nothing known) are left out. One about
    this run (made now, or `at` a time since it started) gets its `seq` and
    `since_start_s`, and an error or warning (or one of WITH_CTX) the app's `ctx`."""
    out: dict = {"name": name, "level": level_of(name), "t": rounded(at)}
    if count > 1:
        out["count"] = min(int(count), MAX_COUNT)
    since = since_start(at)
    if since >= -1:   # a second's leeway: the two clocks were read a moment apart
        out["seq"] = next(_seq)
        out["since_start_s"] = round(max(since, 0.0), 1)
        if out["level"] != "info" or name in WITH_CTX:
            ctx = context()
            if ctx:
                out["ctx"] = ctx
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
    """The same event twice as one with a count: a bug in a loop is one line, "3 times".
    The first one's time, place in the run and context stay."""
    out: dict[str, dict] = {}
    for e in events:
        key = json.dumps([e.get("name"), e.get("attrs")], sort_keys=True)
        have = out.get(key)
        if have is None:
            out[key] = dict(e)
        else:
            have["count"] = min(have.get("count", 1) + e.get("count", 1), MAX_COUNT)
    return list(out.values())


def kept(e: dict) -> dict:
    """Event `e` about to wait in config.json, maybe for a later run: it says which run it
    came from, so its `seq` still reads in order with that run's."""
    if "seq" in e and "from_run" not in e:
        return {**e, "from_run": RUN}
    return e


def _for(e: dict, run: str) -> dict:
    """`e` as the message for `run` sends it: none of RUN_FIELDS with no run (they'd tie an
    opt-out to a time in a run), and no `from_run` when it's this one."""
    if not run:
        return {k: v for k, v in e.items() if k not in RUN_FIELDS}
    if e.get("from_run") == run:
        return {k: v for k, v in e.items() if k != "from_run"}
    return e


def message(events: list[dict], install: str = "", run: str = "") -> dict:
    """One request's body. No `install` or `run` when it has none: an opt-out can't be tied
    to anything, and the feedback picks carry a one-off tag and no run."""
    out: dict = {"schema": SCHEMA, "app": APP, "version": __version__, "os": os_tag()}
    if install:
        out["install"] = install
    if run:
        out["run"] = run
    out["events"] = [_for(e, run) for e in events]
    return out
