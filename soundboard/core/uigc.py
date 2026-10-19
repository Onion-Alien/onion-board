"""Python's garbage collector, run on the UI thread only.

Left alone, a collection runs on whichever thread happens to allocate past the
threshold: the audio callbacks, the network relay, a decoder. When that collection
frees a Qt object caught in a reference cycle (a closed dialog, a finished player),
the object is destroyed on that thread. A QObject with a running timer can't stop it
from another thread ("QObject::~QObject: Timers cannot be stopped from another
thread"), so the timer stays registered and its next tick lands on freed memory: an
access violation inside QCoreApplication::notify, under load, every few hundred runs.
On the audio threads the collection is a stutter as well.

So automatic collection is switched off and a UI-thread timer runs the same
generational collections the interpreter would have, at the same thresholds.

The same goes for what a thread lets go of when it ends. Its target is often a tab's
bound method or a closure over the tab: switch the tab off while the thread works and
the thread's reference can be the last one, so the tab's Python side (and every Qt
object only it holds) was freed on the worker. That corrupted the heap now and then,
and the crash came later somewhere else (switching tabs, a constructor, a teardown).
So a finished thread hands its target and arguments over, and the same UI-thread timer
lets go of them (hand_threads_to_ui, let_go).

A collection still holds Python's lock from start to end, and the audio callbacks need
it too: on the UI thread a pause isn't free, the sound playing waits it out. A
gen-0 collection of 50,000 new objects took ~8 ms, a full one ~30 ms (a skip). So the
collector keeps every pause short: gen 0 is collected small and often (YOUNG new
objects, checked every INTERVAL_MS), and what's alive once the window is up is set
aside (gc.freeze), so a gen-2 collection only goes through what's been made since.
What's set aside is gone through too (a deep sweep: gc.unfreeze, collect, freeze), but
only when nothing's playing (`quiet`), every DEEP_S; or, never quiet, after DEEP_MAX_S.
"""
from __future__ import annotations

import gc
import threading
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer

from soundboard.core import overridepin

INTERVAL_MS = 100
YOUNG = 5_000         # new objects before a gen-0 collection (~1 ms each)
DEEP_S = 600          # the set-aside objects gone through again, when it's quiet...
DEEP_MAX_S = 3600     # ...or after this long anyway (the radio on all day)

_handed: list[tuple] = []   # (target, args, kwargs) of finished threads, until let_go
_handed_lock = threading.Lock()
_thread_run = threading.Thread.run


def _run(self):
    """threading.Thread.run, but the target and its arguments are kept for let_go
    instead of being let go of here, on the thread."""
    try:
        if self._target is not None:
            self._target(*self._args, **self._kwargs)
    finally:
        # built and handed over under the lock: no reference is left on this thread
        # that let_go (which takes the lock) could leave as the last one
        if threading.current_thread() is not threading.main_thread():
            with _handed_lock:
                _handed.append((self._target, self._args, self._kwargs))
        del self._target, self._args, self._kwargs


def hand_threads_to_ui():
    """From now on, what a finished thread was given is let go of by let_go."""
    threading.Thread.run = _run


def let_go() -> int:
    """Let go of what finished threads handed over (on this thread, the UI one); how
    many threads' worth."""
    with _handed_lock:
        done = _handed[:]
        _handed.clear()
    n = len(done)
    del done
    return n


def collect_due(thresholds=None) -> int:
    """Collect the generations the interpreter would have by now (on this thread);
    the oldest one collected, or -1 for none."""
    thresholds = thresholds or gc.get_threshold()
    counts = gc.get_count()
    gen = -1
    for g in range(3):
        if counts[g] <= thresholds[g]:
            break
        gen = g
    if gen >= 0:
        gc.collect(gen)
    return gen


class UiCollector(QObject):
    """`quiet`: True while nothing is playing (Engine.quiet), when a deep sweep's
    pause can't be heard. `freeze` False: nothing is set aside (the tests' collector:
    a test that checks something is freed by gc.collect() can't have it set aside)."""

    def __init__(self, parent=None, interval_ms: int = INTERVAL_MS,
                 quiet: Callable[[], bool] | None = None, freeze: bool = True):
        super().__init__(parent)
        self.thresholds = (YOUNG, *gc.get_threshold()[1:])
        self._quiet = quiet or (lambda: True)
        self._freeze = freeze
        gc.disable()
        if freeze:
            gc.freeze()   # what start-up made: gone through by the deep sweeps only
        self._deep_at = time.monotonic()
        hand_threads_to_ui()
        overridepin.pin()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check)
        self._timer.start(interval_ms)

    def check(self) -> int:
        let_go()
        overridepin.pin_new()   # classes imported since (a tab, an add-on)
        since = time.monotonic() - self._deep_at
        if self._freeze and (since > DEEP_MAX_S or (since > DEEP_S and self._quiet())):
            return self.deep()
        gen = collect_due(self.thresholds)
        if gen == 2 and self._freeze:
            gc.freeze()   # what lived through it: set aside till the next deep sweep
        return gen

    def deep(self) -> int:
        """Everything, the set-aside objects too, collected; then set aside again."""
        self._deep_at = time.monotonic()
        gc.unfreeze()
        gc.collect()
        gc.freeze()
        return 3

    def stop(self):
        self._timer.stop()
        threading.Thread.run = _thread_run
        let_go()
        if self._freeze:
            gc.unfreeze()
        gc.enable()
