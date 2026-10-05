"""Notes down a frozen window: when the UI thread hasn't run its timer for
HANG_S seconds ("Not Responding"), log what it's doing (its stack) once per
freeze and save it beside the crash reports (applog.save_freeze), so a freeze
nobody can reproduce can still be fixed. Nothing is shown or sent."""
from __future__ import annotations

import logging
import sys
import threading
import time
import traceback

from PySide6.QtCore import QObject, QTimer

log = logging.getLogger(__name__)

HANG_S = 5.0
BEAT_MS = 500


class HangWatch(QObject):
    def __init__(self, hang_s: float = HANG_S, parent=None):
        super().__init__(parent)
        self.hang_s = hang_s
        self.beat = time.monotonic()
        self.reports = 0
        self.saved = None               # the last freeze report's file
        self._ui = threading.get_ident()
        self._stop = threading.Event()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(int(min(BEAT_MS, hang_s * 250)))
        threading.Thread(target=self._watch, name="hangwatch", daemon=True).start()

    def _tick(self):
        self.beat = time.monotonic()

    def stop(self):
        self._stop.set()
        self._timer.stop()

    def _watch(self):
        reported = False
        while not self._stop.wait(min(1.0, self.hang_s / 4)):
            stuck = time.monotonic() - self.beat
            if stuck < self.hang_s:
                reported = False
                continue
            if reported:
                continue
            reported = True
            frame = sys._current_frames().get(self._ui)
            stack = "".join(traceback.format_stack(frame)) if frame else "(no stack)"
            log.warning("the window hasn't responded for %.0f s; it's doing:\n%s",
                        stuck, stack)
            from soundboard import applog
            self.saved = applog.save_freeze(stuck, stack)
            self.reports += 1           # last: a report counts once it's logged and saved
