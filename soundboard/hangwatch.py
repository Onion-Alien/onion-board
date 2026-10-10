"""Notes down a frozen window: when the UI thread hasn't run its timer for
HANG_S seconds ("Not Responding"), log what it's doing (its stack) once per
freeze and save it, with every other thread's stack, beside the crash reports
(applog.save_freeze, which scrubs personal paths), so a freeze
nobody can reproduce can still be fixed. With it, how busy each thread was (CPU, over
half a second: the window working itself, waiting on a busy thread, or everyone
waiting), and once the window answers again, how long it was stuck in all. Nothing is
shown or sent (usage.py counts it, with only where in our code it was)."""
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
CPU_SAMPLE_S = 0.5              # how long each thread's CPU use is measured, once stuck
THREAD_QUERY_LIMITED_INFORMATION = 0x0800
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
            since = self.beat
            frames = sys._current_frames()
            frame = frames.get(self._ui)
            ui = traceback.extract_stack(frame, limit=MAX_FRAMES) if frame else None
            stack = "".join(ui.format()) if ui else "(no stack)"
            if ui and IN_EXEC.search(ui[-1].line or ""):
                stack += f"\n{IN_DIALOG_NOTE}\n"
            log.warning("the window hasn't responded for %.0f s; it's doing:\n%s",
                        stuck, stack)
            cpu = self._cpu_use()
            if self._ui in cpu:
                stack += f"\nWindow CPU: {cpu[self._ui]:.0%}\n"
            from soundboard import applog
            self.saved = applog.save_freeze(stuck, stack + self._others(frames, cpu))
            self.reports += 1           # last: a report counts once it's logged and saved
            self._wait_end(since)

    def _wait_end(self, since: float):
        """Once the window beats again, note in the report how long it was stuck."""
        while not self._stop.wait(min(1.0, self.hang_s / 4)):
            if self.beat != since:
                from soundboard import applog
                applog.note_freeze_end(self.saved, self.beat - since)
                return

    def _cpu_use(self) -> dict[int, float]:
        """How busy each thread is (share of one core, over CPU_SAMPLE_S), by ident.
        A stuck window using no CPU waits on something (a lock, the disk, the GIL that
        a busy thread holds); one at 100% is working itself. {} where unknown."""
        ids = {t.ident: t.native_id for t in threading.enumerate() if t.native_id}
        before, t0 = cpu_times(ids), time.monotonic()
        if not before or self._stop.wait(CPU_SAMPLE_S):
            return {}
        after, dt = cpu_times(ids), time.monotonic() - t0
        return {i: max(0.0, after[i] - before[i]) / dt for i in before if i in after}

    def _others(self, frames, cpu=None) -> str:
        """Every other thread's stack: a UI thread stuck in native code is often
        waiting on one of these (the GIL, a lock)."""
        names = {t.ident: t.name for t in threading.enumerate()}
        me = threading.get_ident()
        parts = ["", "Other threads", "-------------"]
        for ident, frame in frames.items():
            if ident in (self._ui, me):
                continue
            use = f", {cpu[ident]:.0%} CPU" if cpu and ident in cpu else ""
            parts.append(f'Thread "{names.get(ident, "?")}" ({ident}){use}:')
            parts.append("".join(traceback.format_stack(frame, limit=MAX_FRAMES)))
        return "\n".join(parts)


_api = None   # (OpenThread, GetThreadTimes, CloseHandle), False if missing


def cpu_times(native_ids: dict[int, int]) -> dict[int, float]:
    """CPU seconds (user + kernel) each thread has used so far, by the dict's key;
    Windows only ({} elsewhere or if the calls are missing)."""
    global _api
    if _api is None:
        _api = False
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import POINTER, c_int, c_ulong, c_ulonglong, c_void_p
                k32 = ctypes.WinDLL("kernel32")
                k32.OpenThread.restype = c_void_p
                k32.OpenThread.argtypes = (c_ulong, c_int, c_ulong)
                k32.GetThreadTimes.restype = c_int
                k32.GetThreadTimes.argtypes = (c_void_p, *[POINTER(c_ulonglong)] * 4)
                k32.CloseHandle.restype, k32.CloseHandle.argtypes = c_int, (c_void_p,)
                _api = (k32.OpenThread, k32.GetThreadTimes, k32.CloseHandle, c_ulonglong,
                        ctypes.byref)
            except (OSError, AttributeError):
                pass
    if not _api:
        return {}
    open_thread, times, close, u64, byref = _api
    out = {}
    for key, nid in native_ids.items():
        try:
            h = open_thread(THREAD_QUERY_LIMITED_INFORMATION, False, nid)
            if not h:
                continue
            try:
                c, e, k, u = u64(), u64(), u64(), u64()
                if times(h, byref(c), byref(e), byref(k), byref(u)):
                    out[key] = (k.value + u.value) / 1e7   # 100 ns units
            finally:
                close(h)
        except Exception:  # noqa: BLE001 - only extra detail for a report
            continue
    return out
