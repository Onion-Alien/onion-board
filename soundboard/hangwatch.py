"""Notes down a frozen window: when the UI thread hasn't run its timer for
HANG_S seconds ("Not Responding"), log what it's doing (its stack) once per
freeze and save it, with every other thread's stack, beside the crash reports
(applog.save_freeze, which scrubs personal paths), so a freeze
nobody can reproduce can still be fixed. Nothing is shown or sent."""
from __future__ import annotations

import logging
import re
import sys
import threading
import time
import traceback

from PySide6.QtCore import QObject, QTimer

log = logging.getLogger(__name__)

HANG_S = 5.0
BEAT_MS = 500
MAX_FRAMES = 40                 # innermost frames kept per thread
# A modal dialog's exec() runs its own event loop, which still beats our timer: a
# freeze with exec() as the last Python frame was in native Qt or another thread.
IN_EXEC = re.compile(r"\.exec_?\(")
IN_DIALOG_NOTE = ("(it was inside a window's own event loop; the stall was in Qt "
                  "or another thread)")


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
            frames = sys._current_frames()
            frame = frames.get(self._ui)
            ui = traceback.extract_stack(frame, limit=MAX_FRAMES) if frame else None
            stack = "".join(ui.format()) if ui else "(no stack)"
            if ui and IN_EXEC.search(ui[-1].line or ""):
                stack += f"\n{IN_DIALOG_NOTE}\n"
            log.warning("the window hasn't responded for %.0f s; it's doing:\n%s",
                        stuck, stack)
            from soundboard import applog
            self.saved = applog.save_freeze(stuck, stack + self._others(frames))
            self.reports += 1           # last: a report counts once it's logged and saved

    def _others(self, frames) -> str:
        """Every other thread's stack: a UI thread stuck in native code is often
        waiting on one of these (the GIL, a lock)."""
        names = {t.ident: t.name for t in threading.enumerate()}
        me = threading.get_ident()
        parts = ["", "Other threads", "-------------"]
        for ident, frame in frames.items():
            if ident in (self._ui, me):
                continue
            parts.append(f'Thread "{names.get(ident, "?")}" ({ident}):')
            parts.append("".join(traceback.format_stack(frame, limit=MAX_FRAMES)))
        return "\n".join(parts)
