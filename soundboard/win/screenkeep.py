"""Keeps Qt's screens while Windows has none (every monitor off, unplugged, or changing
for a moment; a remote session going away).

Qt drops all its screens then. The next window anything makes (a toast, a tooltip, a
menu) ends the app with "Cannot create window: no screens available", and windows that
are already there have no screen to ask. Qt hears of monitors through one hidden window
of its own: its messages are held back while Windows lists no monitor, so Qt keeps the
screens it had, and they're passed on once there is one again."""
from __future__ import annotations

import atexit
import contextlib
import ctypes
import logging
import sys
from typing import Any

log = logging.getLogger(__name__)

WM_SETTINGCHANGE, WM_DISPLAYCHANGE = 0x001A, 0x007E
GWLP_WNDPROC = -4
CLASS_PART = "ScreenChangeObserver"   # Qt's own hidden window ("Qt6112ScreenChange...")
LOOK_MS = 1000   # how often to look for a monitor while there's none

_kept: dict[str, Any] = {}   # the window, Qt's own procedure, ours (kept alive), the timer


def _user32():
    from ctypes import wintypes as wt
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.SetWindowLongPtrW.argtypes = (wt.HWND, ctypes.c_int, ctypes.c_void_p)
    u.SetWindowLongPtrW.restype = ctypes.c_void_p
    u.CallWindowProcW.argtypes = (ctypes.c_void_p, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
    u.CallWindowProcW.restype = ctypes.c_ssize_t
    u.GetClassNameW.argtypes = (wt.HWND, wt.LPWSTR, ctypes.c_int)
    u.IsWindow.argtypes = (wt.HWND,)
    u.GetMonitorInfoW.argtypes = (wt.HMONITOR, ctypes.c_void_p)
    return u


def _monitors(u) -> int:
    """How many monitors Windows lists and can describe (the ones Qt would take)."""
    from ctypes import wintypes as wt

    class Info(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT),
                    ("dwFlags", wt.DWORD)]
    found = []
    proc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HMONITOR, wt.HDC, ctypes.c_void_p, wt.LPARAM)

    def one(mon, _dc, _rect, _data):
        info = Info(cbSize=ctypes.sizeof(Info))
        if u.GetMonitorInfoW(mon, ctypes.byref(info)):
            found.append(mon)
        return True
    u.EnumDisplayMonitors(None, None, proc(one), 0)
    return len(found)


def _observer(u) -> int:
    """Qt's hidden screen-change window on this thread (0: not found)."""
    from ctypes import wintypes as wt
    found = []
    proc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def one(hwnd, _data):
        name = ctypes.create_unicode_buffer(128)
        u.GetClassNameW(hwnd, name, 128)
        if CLASS_PART in name.value:
            found.append(hwnd)
        return True
    u.EnumThreadWindows(ctypes.windll.kernel32.GetCurrentThreadId(), proc(one), 0)
    return found[0] if found else 0


def install() -> bool:
    """Call once on the UI thread, after the QApplication is made."""
    if sys.platform != "win32" or _kept:
        return False
    try:
        return _install()
    except Exception:  # noqa: BLE001 - without it the app works as Qt does
        log.warning("couldn't look after Qt's screens", exc_info=True)
        return False


def _install() -> bool:
    from ctypes import wintypes as wt

    from PySide6.QtCore import QCoreApplication, QTimer
    u = _user32()
    hwnd = _observer(u)
    if not hwnd:   # offscreen tests, or a Qt that does it another way
        log.info("Qt's screen-change window wasn't found")
        return False
    timer = QTimer()
    timer.setInterval(LOOK_MS)
    proc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
    qts = {"proc": None}   # Qt's own procedure

    def proc(h, msg, wp, lp):
        try:
            if msg in (WM_DISPLAYCHANGE, WM_SETTINGCHANGE) and not _monitors(u):
                if not timer.isActive():
                    log.info("Windows has no monitor right now: keeping the screens as they are")
                    timer.start()
                return 0
        except Exception:  # noqa: BLE001 - the message still reaches Qt
            log.debug("the monitor check failed", exc_info=True)
        return u.CallWindowProcW(qts["proc"], h, msg, wp, lp)

    def look():
        if _monitors(u):
            timer.stop()
            log.info("a monitor is back")
            u.CallWindowProcW(qts["proc"], hwnd, WM_DISPLAYCHANGE, 32, 0)   # Qt asks for the rest

    timer.timeout.connect(look)
    ours = proc_type(proc)
    get = u.GetWindowLongPtrW
    get.argtypes, get.restype = (wt.HWND, ctypes.c_int), ctypes.c_void_p
    qts["proc"] = get(hwnd, GWLP_WNDPROC)   # known before the first message can come
    if not qts["proc"]:
        log.info("Qt's screen-change window couldn't be taken over")
        return False
    _kept.update(user32=u, hwnd=hwnd, old=qts["proc"], proc=ours, timer=timer)
    u.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, ctypes.cast(ours, ctypes.c_void_p))
    app = QCoreApplication.instance()
    if app is not None:
        app.aboutToQuit.connect(uninstall)
    atexit.register(uninstall)   # Qt destroys the window after Python could answer it
    return True


def uninstall() -> None:
    """Qt's window is its own again (the app is quitting)."""
    if not _kept:
        return
    u, hwnd, old, timer = _kept["user32"], _kept["hwnd"], _kept["old"], _kept["timer"]
    if u.IsWindow(hwnd):
        u.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, old)
    with contextlib.suppress(RuntimeError):   # Qt's side is gone already
        timer.stop()
    _kept.clear()
