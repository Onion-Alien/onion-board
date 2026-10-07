"""Gives each Python thread its name in Windows too (SetThreadDescription), so a
profiler, a crash dump or Task Manager-style tools tell the app's threads apart.
Python 3.13 doesn't do it itself: every thread shows up as an unnamed ucrtbase thread,
and the only way to find the Who's listening worker among 30 others was its wake rate.

`install()` wraps threading.Thread.start once: a thread started after it gives
itself its Python name ("voicesdk-listeners", "tts-speaker"...) as it begins to
run. It never fails a start: off Windows, on an old Windows without the call, or if
anything goes wrong, the thread just runs unnamed as before."""
from __future__ import annotations

import sys
import threading

THREAD_SET_LIMITED_INFORMATION = 0x0400

_api = None   # (OpenThread, SetThreadDescription, CloseHandle), False if missing


def _calls():
    global _api
    if _api is None:
        _api = False
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import c_int, c_long, c_ulong, c_void_p, c_wchar_p
                k32 = ctypes.WinDLL("kernel32")
                k32.OpenThread.restype, k32.OpenThread.argtypes = c_void_p, (c_ulong, c_int,
                                                                             c_ulong)
                k32.SetThreadDescription.restype = c_long   # HRESULT (Windows 10 1607+)
                k32.SetThreadDescription.argtypes = (c_void_p, c_wchar_p)
                k32.CloseHandle.restype, k32.CloseHandle.argtypes = c_int, (c_void_p,)
                _api = (k32.OpenThread, k32.SetThreadDescription, k32.CloseHandle)
            except (OSError, AttributeError):
                pass
    return _api


def name_native(native_id: int | None, name: str) -> bool:
    """Name the OS thread `native_id` (threading.Thread.native_id). True if it worked."""
    api = _calls()
    if not api or not native_id or not name:
        return False
    open_thread, describe, close = api
    try:
        h = open_thread(THREAD_SET_LIMITED_INFORMATION, False, native_id)
        if not h:
            return False
        try:
            return describe(h, name[:120]) >= 0
        finally:
            close(h)
    except Exception:  # noqa: BLE001 - only a nicety
        return False


def install():
    """Name every thread started from now on (from inside it, as it begins to run),
    and the ones already running."""
    start = threading.Thread.start
    if getattr(start, "_names_native", False):
        return

    def named_start(self, *args, **kwargs):
        run = self.run

        def named_run():
            name_native(threading.get_native_id(), self.name)
            run()
        self.run = named_run   # (the instance's: Thread._bootstrap_inner calls self.run)
        start(self, *args, **kwargs)
    named_start._names_native = True
    named_start.__doc__ = start.__doc__
    threading.Thread.start = named_start
    for t in threading.enumerate():
        name_native(t.native_id, "ui" if t is threading.main_thread() else t.name)
