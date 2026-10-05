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
"""
from __future__ import annotations

import gc

from PySide6.QtCore import QObject, QTimer

INTERVAL_MS = 500


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
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check)
        self._timer.start(interval_ms)

    def check(self) -> int:
        return collect_due(self.thresholds)

    def stop(self):
        self._timer.stop()
        gc.enable()
