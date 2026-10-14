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
"""
from __future__ import annotations

import gc
import threading

from PySide6.QtCore import QObject, QTimer

from soundboard import overridepin

INTERVAL_MS = 500

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
    def __init__(self, parent=None, interval_ms: int = INTERVAL_MS):
        super().__init__(parent)
        self.thresholds = gc.get_threshold()
        gc.disable()
        hand_threads_to_ui()
        overridepin.pin()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check)
        self._timer.start(interval_ms)

    def check(self) -> int:
        let_go()
        overridepin.pin()   # classes imported since the last tick (a tab, an add-on)
        return collect_due(self.thresholds)

    def stop(self):
        self._timer.stop()
        threading.Thread.run = _thread_run
        let_go()
        gc.enable()
