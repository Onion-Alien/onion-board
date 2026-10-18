"""Games run as admin: Windows keeps the keys pressed in an admin window from every
program that isn't admin too (User Interface Privilege Isolation), so the board's
hotkeys go quiet while one is in front, whichever way they're read (raw input,
RegisterHotKey). The game still gets its keys: nothing is taken from it.

This notices such a game coming to the front, so the window can say why the keys don't
work there and offer to start the board again as admin (ui/hotkeycontrol.py), the way
Microsoft's PowerToys does. Only full-screen admin windows count: Task Manager and an
admin terminal are admin too, and nobody games in them. Nothing here reads keys."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import os
import subprocess
import sys
import threading

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TOKEN_ELEVATION = 20      # TOKEN_INFORMATION_CLASS.TokenElevation
EVERY_S = 2.0             # how often the window in front is looked at
ERROR_CANCELLED = 1223    # the admin prompt was answered No


def _api():
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    k32.OpenProcess.argtypes = (wt.DWORD, wt.BOOL, wt.DWORD)
    k32.OpenProcess.restype = wt.HANDLE
    k32.CloseHandle.argtypes = (wt.HANDLE,)
    k32.QueryFullProcessImageNameW.argtypes = (wt.HANDLE, wt.DWORD, wt.LPWSTR,
                                               ctypes.POINTER(wt.DWORD))
    adv.OpenProcessToken.argtypes = (wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE))
    adv.GetTokenInformation.argtypes = (wt.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                        wt.DWORD, ctypes.POINTER(wt.DWORD))
    return k32, adv


def elevated(pid: int | None = None) -> bool | None:
    """Whether process `pid` (None: this one) runs as admin. None when Windows won't
    say (a protected process, one that's gone): treated as not admin."""
    if sys.platform != "win32":
        return False
    try:
        k32, adv = _api()
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False,
                            os.getpid() if pid is None else pid)
        if not h:
            return None
        try:
            tok = wt.HANDLE()
            if not adv.OpenProcessToken(h, TOKEN_QUERY, ctypes.byref(tok)):
                return None
            try:
                val, size = wt.DWORD(), wt.DWORD()
                if not adv.GetTokenInformation(tok, TOKEN_ELEVATION, ctypes.byref(val),
                                               ctypes.sizeof(val), ctypes.byref(size)):
                    return None
                return bool(val.value)
            finally:
                k32.CloseHandle(tok)
        finally:
            k32.CloseHandle(h)
    except (OSError, AttributeError):
        log.debug("elevation check failed", exc_info=True)
        return None


def exe_name(pid: int) -> str:
    """The file name of process `pid`'s program ("" if Windows won't say)."""
    try:
        k32, _adv = _api()
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return ""
        try:
            buf, n = ctypes.create_unicode_buffer(1024), wt.DWORD(1024)
            if not k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                return ""
            return os.path.basename(buf.value)
        finally:
            k32.CloseHandle(h)
    except (OSError, AttributeError):
        return ""


def front_pid() -> int:
    """The process of the window in front (0: none)."""
    try:
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.GetForegroundWindow.restype = wt.HWND
        pid = wt.DWORD()
        u.GetWindowThreadProcessId(u.GetForegroundWindow(), ctypes.byref(pid))
        return pid.value
    except (OSError, AttributeError):
        return 0


class Watcher(QObject):
    """Looks at the window in front every EVERY_S on its own thread, and emits
    `found(exe)` (on the UI thread) once per admin program the first time one of its
    windows fills the screen in front. Never started when the board is admin itself."""
    found = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        if sys.platform != "win32" or self._thread is not None or elevated():
            return False
        self._thread = threading.Thread(target=self._loop, daemon=True, name="adminfront")
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()

    def _loop(self):
        from soundboard.core.tips import fullscreen_in_front
        from soundboard.ui import busy
        me = os.getpid()
        admin: dict[int, bool] = {}   # pid -> runs as admin (asked once each)
        told: set[int] = set()
        while not self._stop.wait(EVERY_S):
            try:
                pid = front_pid()
                if not pid or pid == me or pid in told or admin.get(pid) is False:
                    continue
                if not fullscreen_in_front():
                    continue
                if pid not in admin:
                    admin[pid] = bool(elevated(pid))
                if admin[pid]:
                    told.add(pid)
                    exe = exe_name(pid)
                    log.info("admin program in front: %s (the board's keys can't "
                             "reach it)", exe or pid)
                    if not busy.emit(self.found, exe, owner=self):
                        return
            except Exception:  # noqa: BLE001 - never ends the app; just stop looking
                log.exception("admin window check failed")
                return


def start_elevated(args: list[str]) -> bool:
    """Start this program again as admin with `args` (Windows' admin prompt). Blocks
    until the prompt is answered: call it off the UI thread. False if it was answered
    No or couldn't start."""
    try:
        import ctypes.wintypes as w

        class SHELLEXECUTEINFOW(ctypes.Structure):
            _fields_ = [("cbSize", w.DWORD), ("fMask", w.ULONG), ("hwnd", w.HWND),
                        ("lpVerb", w.LPCWSTR), ("lpFile", w.LPCWSTR),
                        ("lpParameters", w.LPCWSTR), ("lpDirectory", w.LPCWSTR),
                        ("nShow", ctypes.c_int), ("hInstApp", w.HINSTANCE),
                        ("lpIDList", ctypes.c_void_p), ("lpClass", w.LPCWSTR),
                        ("hkeyClass", w.HKEY), ("dwHotKey", w.DWORD),
                        ("hIconOrMonitor", w.HANDLE), ("hProcess", w.HANDLE)]
        info = SHELLEXECUTEINFOW(cbSize=ctypes.sizeof(SHELLEXECUTEINFOW),
                                 fMask=0x00000100,   # SEE_MASK_NOASYNC
                                 lpVerb="runas", lpFile=sys.executable,
                                 lpParameters=subprocess.list2cmdline(args),
                                 lpDirectory=os.getcwd(), nShow=1)   # SW_SHOWNORMAL
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        if shell32.ShellExecuteExW(ctypes.byref(info)):
            return True
        err = ctypes.get_last_error()
        if err != ERROR_CANCELLED:
            log.warning("couldn't start the board as admin (error %d)", err)
        return False
    except (OSError, AttributeError):
        log.exception("couldn't start the board as admin")
        return False
