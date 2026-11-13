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
them walks every Qt class (~1 ms with ~700 of them), so the UI-thread collector (uigc)
calls `pin_new()` on every tick instead: it looks only through the modules imported
since the last tick (their classes are new and in RAM), and walks every class only
WALK_S after the last walk (for a class made inside a function). Walking on every tick
was about 1% of a core with nothing else going on, more on a slower PC.

The full walk reads every Qt class the app has. In the tray, on a PC short of memory,
Windows has moved those out to the page file, and a walk read them all back from disk
with Python's lock held: the whole app stopped for 10 s to over a minute (freeze
reports in pin(), `paging`). A module imported in the tray (a first search, an update
check) set one off too. So only a new module's own classes are looked at then, and the
full walk waits until a read won't page the app back in (`warm`, uigc.warm). Classes
already done are found by address, so the walk doesn't make a weak reference to each
class it passes (a WeakSet look-up does, and that was where the frozen walks stood).
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

_walked = 0.0     # monotonic time of pin_new's last full walk
_modules = -1     # len(sys.modules) at pin_new's last look; -1: never looked
_pending: list[str] = []   # modules imported but still running their code

_done: dict[int, weakref.ref] = {}   # id(class): a weak reference, for classes pinned
_QT = ("PySide6.", "shiboken6")


def _supported() -> bool:
    # the reference count is the first field of every object in CPython with the GIL;
    # the free-threaded build splits it
    gil = getattr(sys, "_is_gil_enabled", lambda: True)
    return sys.implementation.name == "cpython" and bool(gil())


def _qt_names(cls: type) -> set[str]:
    names: set[str] = set()
    for base in cls.__mro__:
        if base.__module__.startswith(_QT):
            names.update(vars(base))
    return names


def _pin(obj):
    ref = ctypes.c_ssize_t.from_address(id(obj))
    ref.value += PIN


def _is_done(cls: type) -> bool:
    ref = _done.get(id(cls))
    return ref is not None and ref() is cls


def _forget(ref, key):
    if _done.get(key) is ref:
        del _done[key]


def _pin_class(cls: type) -> int:
    """Pin cls's own Qt overrides, if it's new; how many."""
    if _is_done(cls) or cls.__module__.startswith(_QT):
        return 0
    key = id(cls)
    _done[key] = weakref.ref(cls, lambda r, key=key: _forget(r, key))
    qt = _qt_names(cls)
    pinned = 0
    for name, value in vars(cls).items():
        if isinstance(value, types.FunctionType) and name in qt:
            _pin(value)
            pinned += 1
    return pinned


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
            pinned += _pin_class(sub)
    return pinned


def _classes(space: dict, base: type, depth: int = 0):
    """The classes made from `base` in a module's or a class's namespace, and the ones
    inside those."""
    for value in list(space.values()):
        if isinstance(value, type) and issubclass(value, base):
            yield value
            if depth < 4:
                yield from _classes(dict(vars(value)), base, depth + 1)


def pin_modules(names) -> int:
    """pin() for just these modules' classes (and the classes inside them)."""
    if not _supported():
        return 0
    from shiboken6 import Shiboken
    pinned = 0
    for name in names:
        mod = sys.modules.get(name)
        space = getattr(mod, "__dict__", None)
        if isinstance(space, dict):
            for cls in _classes(space, Shiboken.Object):
                pinned += _pin_class(cls)
    return pinned


def _running(name: str) -> bool:
    spec = getattr(sys.modules.get(name), "__spec__", None)
    return bool(getattr(spec, "_initializing", False))


def pin_new(now: float | None = None, warm: Callable[[], bool] = lambda: True) -> int:
    """Pin the classes of the modules imported since the last call, and walk every class
    when WALK_S has passed and `warm()` says a walk won't page the app back in; how many
    functions were pinned."""
    global _walked, _modules
    now = time.monotonic() if now is None else now
    pinned, count = 0, len(sys.modules)
    if _modules < 0:   # the first call: everything is new
        _modules, _walked = count, now
        return pin()
    if count > _modules:
        # sys.modules keeps the order modules came in: the new ones are at its end
        new = []
        try:
            for name in reversed(sys.modules):
                if len(new) >= count - _modules:
                    break
                new.append(name)
        except RuntimeError:   # another thread imported meanwhile: next tick
            return 0
        _pending.extend(new)
    _modules = count
    if _pending:
        done = [n for n in _pending if not _running(n)]
        _pending[:] = [n for n in _pending if n not in done]
        pinned += pin_modules(done)
    if not 0 <= now - _walked < WALK_S and warm():
        _walked = now
        pinned += pin()
    return pinned
