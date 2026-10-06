"""Switch category when a program is in front: the user ties programs (by their
.exe name, `Config.category_programs`) to a category, and the board shows that
category whenever one of them comes to the front; when it closes, the board goes back
to the category it was on before. Nothing is built in: every rule is the user's.

`Switcher.poll()` runs on the main window's timer (about once a second, only while a
rule exists): one foreground-window lookup and, while a program it switched for is
running, one "is it still running?" check. Nothing is scanned."""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass

from soundboard import voicesdk

log = logging.getLogger(__name__)

POLL_MS = 1000


def exe_name(path: str) -> str:
    """'game.exe' from a full path: what rules match on, so they survive a reinstall
    to another folder and go into backups."""
    return os.path.basename(path or "").strip().lower()


def programs_for(rules: dict[str, str], category: str) -> list[str]:
    return sorted(exe for exe, cat in rules.items() if cat == category)


@dataclass
class Switch:
    """What poll() wants shown: `category`, because `exe` came to the front (`back`
    False) or closed (`back` True)."""
    category: str
    exe: str
    back: bool = False


class Switcher:
    """Follows the program in front. `foreground()` -> (pid, exe path), as
    voicesdk.foreground_process (this app's own windows are (0, '')); `alive(pid)` as
    appaudio.is_running."""

    def __init__(self, foreground=None, alive=None):
        self._fg = foreground or (lambda: voicesdk.foreground_process())
        if alive is None:
            from soundboard.appaudio import is_running
            alive = is_running
        self._alive = alive
        self.front_pid = 0          # the last real program in front (not us, not Windows')
        self.pid = 0                # the program a switch was made for, while it runs
        self.exe = ""
        self.shown = ""             # the category that switch showed
        self.before: str | None = None   # what was showing before the first switch

    def reset(self):
        """Rules changed or the feature went off: forget the program followed (the
        category showing stays as it is)."""
        self.pid, self.exe, self.shown, self.before = 0, "", "", None

    def poll(self, rules: dict[str, str], current: str, categories) -> Switch | None:
        cats = set(categories)
        pid, path = self._fg()
        if pid and path and not voicesdk._is_system(path) and pid != self.front_pid:
            # a program came to the front. Alt-tabbing out to another one changes
            # nothing; back in front (or a new one with a rule) shows its category
            self.front_pid = pid
            exe = exe_name(path)
            cat = rules.get(exe)
            if cat in cats:
                if self.before is None:
                    self.before = current
                self.pid, self.exe, self.shown = pid, exe, cat
                if current != cat:
                    return Switch(cat, exe)
                return None
        if self.pid and not self._alive(self.pid):
            # it closed: back to what was showing, unless the user has picked another
            # category by hand meanwhile (theirs to keep)
            exe, shown, before = self.exe, self.shown, self.before
            self.reset()
            if current == shown and before is not None and before != current and \
                    (before == "" or before in cats):
                return Switch(before, exe, back=True)
        return None


def windowed_programs() -> list[tuple[str, str, str]]:
    """The programs with a window open now, as (exe name, exe path, window title),
    one per exe, this app and Windows' own left out. For picking a program."""
    if sys.platform != "win32":
        return []
    try:
        return _windowed()
    except Exception:  # noqa: BLE001
        log.debug("listing windows failed", exc_info=True)
        return []


def _windowed() -> list[tuple[str, str, str]]:
    import ctypes
    from ctypes import POINTER, WINFUNCTYPE, byref, c_bool, c_int, c_ulong, c_void_p, wintypes
    u = ctypes.WinDLL("user32", use_last_error=True)
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    proc = WINFUNCTYPE(c_bool, c_void_p, c_void_p)
    u.EnumWindows.argtypes = (proc, c_void_p)
    u.EnumWindows.restype = c_bool
    u.IsWindowVisible.argtypes = (c_void_p,)
    u.IsWindowVisible.restype = c_bool
    u.GetWindowTextLengthW.argtypes = (c_void_p,)
    u.GetWindowTextLengthW.restype = c_int
    u.GetWindowTextW.argtypes = (c_void_p, wintypes.LPWSTR, c_int)
    u.GetWindowTextW.restype = c_int
    u.GetWindow.argtypes = (c_void_p, wintypes.UINT)
    u.GetWindow.restype = c_void_p
    u.GetWindowLongW.argtypes = (c_void_p, c_int)
    u.GetWindowLongW.restype = wintypes.LONG
    u.GetWindowThreadProcessId.argtypes = (c_void_p, POINTER(c_ulong))
    u.GetWindowThreadProcessId.restype = c_ulong
    k.OpenProcess.argtypes = (c_ulong, c_int, c_ulong)
    k.OpenProcess.restype = c_void_p
    k.QueryFullProcessImageNameW.argtypes = (c_void_p, c_ulong, wintypes.LPWSTR,
                                             POINTER(c_ulong))
    k.QueryFullProcessImageNameW.restype = c_int
    k.CloseHandle.argtypes = (c_void_p,)
    k.CloseHandle.restype = c_int
    GW_OWNER, GWL_EXSTYLE, WS_EX_TOOLWINDOW = 4, -20, 0x80
    me = os.getpid()
    found: dict[str, tuple[str, str, str]] = {}
    paths: dict[int, str] = {}

    def path_of(pid: int) -> str:
        if pid not in paths:
            paths[pid] = ""
            h = k.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
            if h:
                try:
                    buf = ctypes.create_unicode_buffer(1024)
                    size = c_ulong(len(buf))
                    if k.QueryFullProcessImageNameW(h, 0, buf, byref(size)):
                        paths[pid] = buf.value
                finally:
                    k.CloseHandle(h)
        return paths[pid]

    def each(hwnd, _lp):
        try:
            if not u.IsWindowVisible(hwnd) or u.GetWindow(hwnd, GW_OWNER):
                return True
            if u.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
                return True
            n = u.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(hwnd, buf, n + 1)
            pid = c_ulong()
            u.GetWindowThreadProcessId(hwnd, byref(pid))
            if not pid.value or pid.value == me:
                return True
            path = path_of(pid.value)
            exe = exe_name(path)
            if exe and not voicesdk._is_system(path) and exe not in found:
                found[exe] = (exe, path, buf.value)
        except Exception:  # noqa: BLE001 - one odd window mustn't end the listing
            pass
        return True

    u.EnumWindows(proc(each), None)
    return sorted(found.values(), key=lambda t: t[0])
