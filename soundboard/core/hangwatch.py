"""Notes down a frozen window: when the UI thread hasn't run its timer for
HANG_S seconds ("Not Responding"), log what it's doing (its stack) once per
freeze and save it, with every other thread's stack, beside the crash reports
(applog.save_freeze, which scrubs personal paths), so a freeze
nobody can reproduce can still be fixed. With it, how busy each thread was (CPU, over
half a second: the window working itself, waiting on a busy thread, or everyone
waiting), and once the window answers again, how long it was stuck in all. Nothing is
shown or sent (usage.py counts it, with only where in our code it was).

Time is counted only while the PC is awake (awake_clock): with the app open over a
sleep, every thread stops, and on waking it looked like the window had frozen for the
whole sleep, stuck wherever it happened to be (2.0.4's "freezes" in the event loop, idle,
lasting minutes)."""
from __future__ import annotations

import dis
import logging
import sys
import threading
import time
import traceback
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer

log = logging.getLogger(__name__)

HANG_S = 5.0
BEAT_MS = 500
MAX_FRAMES = 40                 # innermost frames kept per thread
CPU_SAMPLE_S = 0.5              # how long each thread's CPU use is measured, once stuck
THREAD_QUERY_LIMITED_INFORMATION = 0x0800
# A modal dialog's exec() runs its own event loop, which still beats our timer: a
# freeze with exec() as the last Python frame was in native Qt or another thread.
EXECS = {"exec", "exec_"}
# Windows' own file window, on our thread: the same, but all of it is Windows' (the shell,
# its add-ons, the folder it opens). Written to the log, not reported: nothing here to fix.
FILE_DIALOGS = {"getOpenFileName", "getOpenFileNames", "getOpenFileUrl", "getOpenFileUrls",
                "getSaveFileName", "getSaveFileUrl", "getExistingDirectory",
                "getExistingDirectoryUrl"}
IN_DIALOG_NOTE = ("(it was inside a window's own event loop; the stall was in Qt "
                  "or another thread)")
# The watch's own thread was held up as long: not the window alone but the whole app
# (one thread kept Python's lock while it waited, or Windows paused the app).
ALL_HELD_NOTE = "(every thread was held up, this watch too)"
# A deep garbage sweep (uigc) ended while the window was stuck: by the time the watch
# could look, the window was often back in the event loop, so its stack named only
# app.exec(). This says what held it.
GC_SWEEP_NOTE = "(a full garbage sweep over the whole app ran meanwhile: {took:.1f} s)"
# All held up and no thread used the CPU in that time either: no Python thread was busy
# holding the rest up. Windows wasn't running the app, or was reading it back from disk.
NO_CPU_NOTE = "(the app used no CPU meanwhile)"
NO_CPU_SHARE = 0.02   # of one core, over the time it was held up


class HangWatch(QObject):
    def __init__(self, hang_s: float = HANG_S, parent=None,
                 clock: Callable[[], float] | None = None):
        super().__init__(parent)
        self.hang_s = hang_s
        self._clock = clock or awake_clock()
        self.beat = self._clock()
        self.reports = 0
        self.saved = None               # the last freeze report's file
        self._ui = threading.get_ident()
        self._stop = threading.Event()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(int(min(BEAT_MS, hang_s * 250)))
        threading.Thread(target=self._watch, name="hangwatch", daemon=True).start()

    def _tick(self):
        self.beat = self._clock()

    def stuck(self) -> float:
        """Seconds since the window last beat, on this watch's own (awake) clock. Read
        `beat` only through this: time.monotonic() - beat was the PC's whole sleep time
        since it booted, and every unclean exit after a sleep looked frozen."""
        return max(0.0, self._clock() - self.beat)

    def stop(self):
        self._stop.set()
        self._timer.stop()

    def _watch(self):
        reported = False
        woke = self._clock()
        cpu = time.process_time()
        while not self._stop.wait(min(1.0, self.hang_s / 4)):
            now = self._clock()
            cpu_now = time.process_time()
            gap, used = now - woke, cpu_now - cpu
            woke, cpu = now, cpu_now
            held = gap >= self.hang_s   # this thread was stuck as long
            stuck = now - self.beat
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
            calling = called_name(frame) if frame else ""
            if calling in FILE_DIALOGS:
                log.info("the window waited %.0f s on Windows' file window", stuck)
                continue
            if frame and calling in EXECS and frame.f_code.co_name != "main":   # (not app.exec)
                stack += f"\n{IN_DIALOG_NOTE}\n"
            if held:
                stack += f"\n{ALL_HELD_NOTE}\n"
                if used < NO_CPU_SHARE * gap:
                    stack += f"\n{NO_CPU_NOTE}\n"
            took = deep_sweep_within(stuck)
            if took is not None:
                stack += "\n" + GC_SWEEP_NOTE.format(took=took) + "\n"
            from soundboard.core import applog
            log.warning("the window hasn't responded for %.0f s; it's doing:\n%s",
                        stuck, stack, extra=applog.COUNTED)   # as save_freeze's report
            faults = page_faults()
            cpu = self._cpu_use()
            if self._ui in cpu:
                stack += f"\nWindow CPU: {cpu[self._ui]:.0%}\n"
            stack += self._pc_memory(faults)
            self.saved = applog.save_freeze(stuck, stack + self._others(frames, cpu))
            self.reports += 1           # last: a report counts once it's logged and saved
            self._wait_end(since)
            woke, cpu = self._clock(), time.process_time()

    def _wait_end(self, since: float):
        """Once the window beats again, note in the report how long it was stuck."""
        while not self._stop.wait(min(1.0, self.hang_s / 4)):
            if self.beat != since:
                from soundboard.core import applog
                applog.note_freeze_end(self.saved, self.beat - since)
                return

    def _cpu_use(self) -> dict[int, float]:
        """How busy each thread is (share of one core, over CPU_SAMPLE_S), by ident.
        A stuck window using no CPU waits on something (a lock, the disk, the GIL that
        a busy thread holds); one at 100% is working itself. {} where unknown."""
        ids = {t.ident: t.native_id for t in threading.enumerate()
               if t.native_id and t.ident is not None}
        before, t0 = cpu_times(ids), time.monotonic()
        if not before or self._stop.wait(CPU_SAMPLE_S):
            return {}
        after, dt = cpu_times(ids), time.monotonic() - t0
        return {i: max(0.0, after[i] - before[i]) / dt for i in before if i in after}

    def _pc_memory(self, faults_before: int | None) -> str:
        """How full the PC's memory is, and how fast this app page-faulted over the CPU
        sample: an idle window stuck at random lines for 10-30 s, over and over on one
        PC (2.6.1), looked like Windows swapping the app out to disk. "" when unknown."""
        out = ""
        load = memory_load()
        if load is not None:
            out += f"PC memory in use: {load}%\n"
        after = page_faults()
        if faults_before is not None and after is not None:
            out += f"Page faults: {round(max(0, after - faults_before) / CPU_SAMPLE_S)}/s\n"
        return out

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


def called_name(frame) -> str:
    """The attribute `frame` is calling now (`exec` for `dlg.exec()`), "" when unknown. Read
    from its bytecode: an installed copy has no source, so a stack's line text is empty
    there (`in-dialog` never once reached a report)."""
    try:
        code = list(dis.get_instructions(frame.f_code))
        at = max(i for i, ins in enumerate(code) if ins.offset <= frame.f_lasti)
        call = code[at].positions
        for ins in reversed(code[:at]):
            # (the callee starts where the call does: its arguments come after)
            if ins.opname == "LOAD_ATTR" and (
                    not call or not ins.positions
                    or (ins.positions.lineno, ins.positions.col_offset)
                    == (call.lineno, call.col_offset)):
                return ins.argval
    except (ValueError, AttributeError, TypeError):
        pass
    return ""


def deep_sweep_within(seconds: float) -> float | None:
    """How long uigc's last deep sweep took, when it ended in the last `seconds` (the
    time the window has been stuck); else None."""
    from soundboard.core import uigc
    end, took = uigc.last_deep
    if end and time.monotonic() - end <= seconds + 1.0:
        return took
    return None


def awake_clock() -> Callable[[], float]:
    """Seconds the PC has been awake (Windows' unbiased interrupt time: sleep and
    hibernation left out), else time.monotonic."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import POINTER, c_ulonglong
            for dll, name in (("kernelbase", "QueryUnbiasedInterruptTimePrecise"),
                              ("kernel32", "QueryUnbiasedInterruptTime")):
                try:
                    f = getattr(ctypes.WinDLL(dll), name)
                except (OSError, AttributeError):
                    continue
                f.argtypes = (POINTER(c_ulonglong),)

                def awake(f=f) -> float:   # (both threads call it: a value each)
                    t = c_ulonglong()
                    f(ctypes.byref(t))
                    return t.value / 1e7   # 100 ns units
                awake()
                return awake
        except (OSError, AttributeError, ImportError):
            pass
    return time.monotonic


_memory_status = None   # (GlobalMemoryStatusEx, its struct), looked up once


def memory_load() -> int | None:
    """Percent of the PC's memory in use (Windows' own figure); None where unknown.
    The UI thread asks (uigc.warm), so the DLL is looked up once: the frozen app's
    ctypes.WinDLL checks the disk for the file, and with the drive stalled that held
    the window for 30 s."""
    global _memory_status
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        if _memory_status is None:
            from ctypes import wintypes

            class Status(ctypes.Structure):
                _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                            *((n, ctypes.c_ulonglong) for n in (
                                "total", "avail", "total_pf", "avail_pf", "total_v",
                                "avail_v", "avail_ext"))]
            _memory_status = (ctypes.WinDLL("kernel32").GlobalMemoryStatusEx, Status)
        status, Status = _memory_status
        s = Status()
        s.dwLength = ctypes.sizeof(Status)
        if not status(ctypes.byref(s)):
            return None
        return int(s.dwMemoryLoad)
    except (OSError, AttributeError, ValueError):
        return None


_process_memory = None   # (GetProcessMemoryInfo, the process, its struct), or False


def resident_share() -> float | None:
    """How much of this app's own memory is in RAM (0-1), not moved out to the page
    file: its private working set over its private bytes (Windows 10 21H2 and later);
    None where unknown. The UI thread asks (uigc.warm), so the DLLs are looked up once
    (see memory_load)."""
    global _process_memory
    if sys.platform != "win32" or _process_memory is False:
        return None
    try:
        import ctypes
        if _process_memory is None:
            from ctypes import wintypes

            class Counters(ctypes.Structure):   # PROCESS_MEMORY_COUNTERS_EX2
                _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD),
                            *((n, ctypes.c_size_t) for n in (
                                "peak_ws", "ws", "peak_paged", "paged", "peak_nonpaged",
                                "nonpaged", "pagefile", "peak_pagefile", "private",
                                "private_ws")),
                            ("shared_commit", ctypes.c_ulonglong)]
            k32 = ctypes.WinDLL("kernel32")
            k32.GetCurrentProcess.restype = wintypes.HANDLE
            get = ctypes.WinDLL("psapi").GetProcessMemoryInfo
            get.argtypes = (wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD)
            _process_memory = (get, k32.GetCurrentProcess(), Counters)
        get, me, Counters = _process_memory
        c = Counters()
        c.cb = ctypes.sizeof(Counters)
        if not get(me, ctypes.byref(c), c.cb):
            _process_memory = False   # an older Windows: no private working set
            return None
        if not c.private:
            return None
        return min(1.0, c.private_ws / c.private)
    except (OSError, AttributeError, ValueError):
        _process_memory = False
        return None


def page_faults() -> int | None:
    """This app's page faults so far (soft and hard); None where unknown."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        *((n, ctypes.c_size_t) for n in (
                            "peak_ws", "ws", "peak_paged", "paged", "peak_nonpaged",
                            "nonpaged", "pagefile", "peak_pagefile"))]
        c = Counters()
        c.cb = ctypes.sizeof(Counters)
        k32 = ctypes.WinDLL("kernel32")
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        get = ctypes.WinDLL("psapi").GetProcessMemoryInfo
        get.argtypes = (wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD)
        if not get(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
            return None
        return int(c.PageFaultCount)
    except (OSError, AttributeError, ValueError):
        return None


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
    if not isinstance(_api, tuple):   # None / False: not there
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
