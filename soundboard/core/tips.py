"""Is a game (or anything else filling a monitor) in front? The bars across the top and the
tours wait until it isn't."""
from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger(__name__)


def fullscreen_in_front() -> bool:
    """A program filling a whole monitor is in front (a game, borderless or not, or a
    video): no bar or tour then. The desktop doesn't count."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.GetForegroundWindow.restype = wintypes.HWND
        u.GetShellWindow.restype = wintypes.HWND
        u.GetDesktopWindow.restype = wintypes.HWND
        u.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        u.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
        u.MonitorFromWindow.restype = wintypes.HMONITOR

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
        u.GetMonitorInfoW.argtypes = (wintypes.HMONITOR, ctypes.POINTER(MONITORINFO))
        hwnd = u.GetForegroundWindow()
        if not hwnd or hwnd in (u.GetShellWindow(), u.GetDesktopWindow()):
            return False
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == os.getpid():   # the board itself, maximised
            return False
        buf = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(hwnd, buf, 64)
        if buf.value in ("WorkerW", "Progman"):   # the desktop
            return False
        r = wintypes.RECT()
        if not u.GetWindowRect(hwnd, ctypes.byref(r)):
            return False
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if not u.GetMonitorInfoW(u.MonitorFromWindow(hwnd, 2), ctypes.byref(mi)):
            return False
        m = mi.rcMonitor
        return r.left <= m.left and r.top <= m.top and r.right >= m.right \
            and r.bottom >= m.bottom
    except Exception:  # noqa: BLE001
        log.debug("fullscreen check failed", exc_info=True)
        return False
