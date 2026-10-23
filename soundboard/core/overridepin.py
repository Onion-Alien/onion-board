"""Keeps every Python override of a Qt method alive for good.

PySide 6.11 remembers, per Qt object, which Python method overrides a virtual (a
widget's `resizeEvent`, a filter's `eventFilter`) as a pointer it holds no reference
to. When another override has just raised, the exception waits to be raised until
control is back in Python, and a first lookup made meanwhile "gives up" by dropping a
reference it never took (Sbk_GetPyOverride's error path). So one exception inside a
Qt callback, while Qt goes on to resize or show a widget it hasn't called before,
frees that class's method while the class still lists it: the next call runs
whatever Python put in that memory (a thread's start wrapper, on 2026-10-14) or
crashes outright. Tests: tests/test_overridepin.py reproduces it.

`pin()` gives each override of a Qt method a reference count no stolen reference can
empty. They belong to classes, which live as long as the app anyway. It's cheap
(~0.2 ms for every class), and only classes it hasn't seen are looked at again. Finding
them still walks every Qt class (~1 ms with ~700 of them), so the UI-thread collector
(uigc) calls `pin_new()` on every tick: a walk only once a module was imported since the
last one, or WALK_S after it (a class made inside a function). Walking on every tick
was about 1% of a core with nothing else going on, more on a slower PC.

The walk reads every Qt class the app has. In the tray, on a PC short of memory, Windows
has moved those out to the page file, and a walk read them all back from disk with
Python's lock held: the whole app stopped for 10-30 s (freeze reports in pin(),
`mem-90`, `paging`). So the timed walk (the one not set off by an import) waits until a
read won't page the app back in (`warm`, uigc.warm).
"""
from __future__ import annotations

import ctypes
import sys
import time
import types
import weakref
from collections.abc import Callable

PIN = 1 << 24   # references added to each override: far more than any burst of steals
WALK_S = 5.0    # pin_new: the classes walked again this often, when warm

_walked = (-1, 0.0)   # (modules imported, monotonic time) at pin_new's last walk

_done: weakref.WeakSet[type] = weakref.WeakSet()   # classes already pinned


def _supported() -> bool:
    # the reference count is the first field of every object in CPython with the GIL;
    # the free-threaded build splits it
    gil = getattr(sys, "_is_gil_enabled", lambda: True)
    return sys.implementation.name == "cpython" and bool(gil())


def _qt_names(cls: type) -> set[str]:
    names: set[str] = set()
    for base in cls.__mro__:
        if base.__module__.startswith(("PySide6.", "shiboken6")):
            names.update(vars(base))
    return names


def _pin(obj):
    ref = ctypes.c_ssize_t.from_address(id(obj))
    ref.value += PIN


def pin() -> int:
    """Pin the Qt overrides of every Python class made from a Qt one not done yet;
    how many functions were pinned."""
    if not _supported():
        return 0
    from shiboken6 import Shiboken
    pinned, stack = 0, [Shiboken.Object]
    seen: set[type] = set()
    while stack:
        for sub in type.__subclasses__(stack.pop()):
            if sub in seen:
                continue
            seen.add(sub)
            stack.append(sub)
            if sub in _done or sub.__module__.startswith(("PySide6.", "shiboken6")):
                continue
            _done.add(sub)
            qt = _qt_names(sub)
            for name, value in vars(sub).items():
                if isinstance(value, types.FunctionType) and name in qt:
                    _pin(value)
                    pinned += 1
    return pinned


def pin_new(now: float | None = None, warm: Callable[[], bool] = lambda: True) -> int:
    """pin(), when a module was imported since the last walk, or WALK_S has passed and
    `warm()` says a walk won't page the app back in; how many functions were pinned (0
    when it skipped)."""
    global _walked
    now = time.monotonic() if now is None else now
    mods, at = _walked
    if len(sys.modules) == mods and (0 <= now - at < WALK_S or not warm()):
        return 0
    _walked = (len(sys.modules), now)
    return pin()
