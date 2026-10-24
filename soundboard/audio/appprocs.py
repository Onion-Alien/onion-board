"""The running programs, for per-program capture: each process's path, start time
and .exe description, whether it still runs, its tree's root (shared helpers
folded into the program that started them) and window titles.
Part of soundboard.audio.appaudio, which re-exports all of it.
"""
from __future__ import annotations

import ctypes
import logging
import os
import threading
import typing
from ctypes import (Structure, byref, c_int, c_long, c_uint, c_ulong, c_ushort, c_void_p,
                    c_wchar_p, sizeof)

from soundboard.audio.appcom import PROCESS_QUERY_LIMITED_INFORMATION, STILL_ACTIVE, _win
if _win:
    from soundboard.audio.appcom import WINFUNCTYPE, _k32, _k32le, _ntdll, _user32

log = logging.getLogger("soundboard.audio.appaudio")


SYSTEM_EXES = {"svchost.exe", "audiodg.exe", "explorer.exe", "shellexperiencehost.exe"}
# shared helpers that play audio for whichever program started them (the new Teams,
# Steam's store and overlay, launchers built on CEF / Qt WebEngine): their sound is
# that program's, so they're folded into it instead of showing up on their own
HELPER_EXES = {"msedgewebview2.exe", "steamwebhelper.exe", "cefsharp.browsersubprocess.exe",
               "qtwebengineprocess.exe", "epicwebhelper.exe", "upc_webhelper.exe"}

# --------------------------------------------------------------------------- processes

_names: dict[int, str] = {}   # pid -> full image path; see forget_dead_pids
_names_lock = threading.Lock()


def process_path(pid: int, exe: str = "") -> str:
    """Full path of the process's .exe ('' if it can't be opened). `exe`, the name a
    fresh process list gives this pid, catches a pid Windows has handed to another
    program since it was cached."""
    with _names_lock:
        path = _names.get(pid)
    if path is not None and (not exe or not path
                             or os.path.basename(path).lower() == exe.lower()):
        return path
    path = ""
    h = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if h:
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = c_ulong(len(buf))
            if _k32.QueryFullProcessImageNameW(h, 0, buf, byref(size)):
                path = buf.value
        finally:
            _k32.CloseHandle(h)
    with _names_lock:
        _names[pid] = path
    return path


_descriptions: dict[str, str] = {}   # .exe path -> its file description; see file_description
_version = None   # version.dll, its own copy (argtypes set here don't leak elsewhere)


def file_description(path: str) -> str:
    """The program's own name for itself: its .exe's FileDescription version info, what
    Windows' volume mixer shows ('VLC media player' for vlc.exe, 'OBS Studio' for
    obs64.exe); '' if it has none. Reads the file, so never on the UI thread; cached
    per path (a program's name doesn't change while it runs)."""
    global _version
    if not _win or not path:
        return ""
    with _names_lock:
        if path in _descriptions:
            return _descriptions[path]
    desc = ""
    try:
        if _version is None:
            v = ctypes.WinDLL("version")
            v.GetFileVersionInfoSizeW.restype = c_ulong
            v.GetFileVersionInfoSizeW.argtypes = (c_wchar_p, c_void_p)
            v.GetFileVersionInfoW.restype = c_int
            v.GetFileVersionInfoW.argtypes = (c_wchar_p, c_ulong, c_ulong, c_void_p)
            v.VerQueryValueW.restype = c_int
            v.VerQueryValueW.argtypes = (c_void_p, c_wchar_p, c_void_p, c_void_p)
            _version = v
        size = _version.GetFileVersionInfoSizeW(path, None)
        buf = ctypes.create_string_buffer(size) if size else None
        if buf is not None and _version.GetFileVersionInfoW(path, 0, size, buf):
            ptr, n = c_void_p(), c_uint()
            langs = []   # the file's own language + code page pairs first, then the usual
            if (_version.VerQueryValueW(buf, "\\VarFileInfo\\Translation", byref(ptr),
                                        byref(n)) and ptr.value and n.value >= 4):
                w = (c_ushort * (n.value // 2)).from_address(ptr.value)
                langs = [f"{w[i]:04x}{w[i + 1]:04x}" for i in range(0, len(w) - 1, 2)]
            for lang in (*langs, "040904b0", "040904e4", "04090000"):
                if (_version.VerQueryValueW(buf, f"\\StringFileInfo\\{lang}\\FileDescription",
                                            byref(ptr), byref(n)) and ptr.value and n.value):
                    desc = ctypes.wstring_at(ptr.value, n.value).split("\0", 1)[0].strip()
                    if desc:
                        break
    except (OSError, ValueError):
        log.debug("version info of %s unavailable", path, exc_info=True)
    if desc.lower().endswith(".exe"):   # Notepad and Snipping Tool say 'Notepad.exe'
        desc = desc[:-4].rstrip()
    desc = desc[:60]
    with _names_lock:
        _descriptions[path] = desc
    return desc


def forget_dead_pids(table: dict[int, tuple[int, str]]):
    """Drops cached paths of pids missing from a fresh process list: Windows reuses
    pids, and a stale entry would put a remembered program's name (and its auto-send)
    on whatever new process gets the number."""
    with _names_lock:
        for pid in [p for p in _names if p not in table]:
            del _names[pid]


def process_started(pid: int) -> int | None:
    """When the process started (FILETIME ticks), None if it can't be opened. With
    the pid it names one process for good: a reused pid starts at another time."""
    h = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        t = [ctypes.c_ulonglong() for _ in range(4)]
        if not _k32.GetProcessTimes(h, *(byref(x) for x in t)):
            return None
        return t[0].value
    finally:
        _k32.CloseHandle(h)


def is_running(pid: int, started: int | None = None) -> bool:
    """False once the process has exited, or (with `started`, from process_started)
    once its pid belongs to a newer process. A process we may not open (a service, a
    game guarded by anti-cheat) counts as running: we can't tell."""
    h = _k32le.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ctypes.get_last_error() == 5   # ERROR_ACCESS_DENIED
    try:
        code = c_ulong()
        if not (_k32.GetExitCodeProcess(h, byref(code)) and code.value == STILL_ACTIVE):
            return False
        if started is not None:
            t = [ctypes.c_ulonglong() for _ in range(4)]
            if _k32.GetProcessTimes(h, *(byref(x) for x in t)) and t[0].value != started:
                return False
        return True
    finally:
        _k32.CloseHandle(h)

class _PROCESSENTRY32W(Structure):
    _fields_ = [("dwSize", c_ulong), ("cntUsage", c_ulong), ("th32ProcessID", c_ulong),
                ("th32DefaultHeapID", c_void_p), ("th32ModuleID", c_ulong), ("cntThreads", c_ulong),
                ("th32ParentProcessID", c_ulong), ("pcPriClassBase", c_long), ("dwFlags", c_ulong),
                ("szExeFile", ctypes.c_wchar * 260)]


def _process_table() -> dict[int, tuple[int, str]]:
    """pid -> (parent pid, exe name) for every process (Toolhelp snapshot)."""
    table: dict[int, tuple[int, str]] = {}
    snap = _k32.CreateToolhelp32Snapshot(0x2, 0)   # TH32CS_SNAPPROCESS
    if snap == -1 or not snap:
        return table
    try:
        e = _PROCESSENTRY32W()
        e.dwSize = sizeof(e)
        ok = _k32.Process32FirstW(snap, byref(e))
        while ok:
            table[e.th32ProcessID] = (e.th32ParentProcessID, e.szExeFile.lower())
            ok = _k32.Process32NextW(snap, byref(e))
    finally:
        _k32.CloseHandle(snap)
    return table


class _PBI(Structure):   # PROCESS_BASIC_INFORMATION
    _fields_ = [("ExitStatus", c_long), ("PebBaseAddress", c_void_p),
                ("AffinityMask", ctypes.c_size_t), ("BasePriority", c_long),
                ("UniqueProcessId", ctypes.c_size_t), ("ParentPid", ctypes.c_size_t)]


class PidTable:
    """The _process_table rows a session list needs, (parent pid, exe name), looked up
    one process at a time as they're asked for. A recording-session list touches a
    handful of pids (each session's and a few parents), and a full snapshot of every
    process (~500 on a gaming PC) cost ~20 ms of the ~28 ms the Who's listening poll
    took every 3 s. A pid that's gone isn't in it, as in a snapshot; one Windows won't
    let us open (a protected process) makes it take the full snapshot after all, so
    nothing is ever named differently from before."""

    def __init__(self):
        self._rows: dict[int, tuple[int, str] | None] = {}
        self._full: dict[int, tuple[int, str]] | None = None
        self.snapshots = 0   # full snapshots it had to take (for the tests and benches)

    def _row(self, pid: int) -> tuple[int, str] | None:
        if self._full is not None:
            return self._full.get(pid)
        if pid in self._rows:
            return self._rows[pid]
        found = _open_row(pid)
        if found is _DENIED:
            self._full = _process_table()
            self.snapshots += 1
            return self._full.get(pid)
        row = typing.cast("tuple[int, str] | None", found)
        self._rows[pid] = row
        return row

    def get(self, pid: int, default=None):
        row = self._row(pid)
        return default if row is None else row

    def __contains__(self, pid) -> bool:
        return self._row(pid) is not None

    def __getitem__(self, pid: int) -> tuple[int, str]:
        row = self._row(pid)
        if row is None:
            raise KeyError(pid)
        return row


_DENIED = object()


def _open_row(pid: int):
    """(parent pid, exe name) of one running process, None if there's no such process,
    _DENIED if Windows won't say."""
    if pid == 0:
        return None
    h = _k32le.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None if ctypes.get_last_error() == 87 else _DENIED   # INVALID_PARAMETER: gone
    try:
        code = c_ulong()
        if _k32.GetExitCodeProcess(h, byref(code)) and code.value != STILL_ACTIVE:
            return None   # exited, only a handle keeps it (a snapshot wouldn't list it)
        buf = ctypes.create_unicode_buffer(1024)
        size = c_ulong(len(buf))
        pbi, got = _PBI(), c_ulong()
        if (not _k32.QueryFullProcessImageNameW(h, 0, buf, byref(size))
                or _ntdll.NtQueryInformationProcess(h, 0, byref(pbi), sizeof(pbi),
                                                    byref(got)) != 0):
            return _DENIED
        return int(pbi.ParentPid), os.path.basename(buf.value).lower()
    finally:
        _k32.CloseHandle(h)


def running() -> dict[int, str]:
    """pid -> exe name (lower case) of every running process; {} off Windows."""
    return {pid: exe for pid, (_, exe) in _process_table().items()} if _win else {}


def root_pid(pid: int, table: dict[int, tuple[int, str]] | None = None) -> int:
    """The topmost ancestor with the same .exe name. Browsers and chat apps play
    their audio from a helper child process that comes and goes; capturing the main
    process *and its tree* keeps following them. A shared helper (HELPER_EXES) goes
    to the program that started it, unless that's Windows itself."""
    table = table if table is not None else _process_table()
    if pid not in table:
        return pid
    exe = table[pid][1]
    if exe in HELPER_EXES:
        seen, host = {pid}, pid
        while table[host][1] in HELPER_EXES:
            parent = table[host][0]
            if parent in seen or parent not in table or table[parent][1] in SYSTEM_EXES:
                break
            seen.add(parent)
            host = parent
        if table[host][1] not in HELPER_EXES:
            pid, exe = host, table[host][1]
    seen = {pid}
    while True:
        parent = table[pid][0]
        if parent in seen or parent not in table or table[parent][1] != exe:
            return pid
        seen.add(parent)
        pid = parent


def window_titles() -> dict[int, str]:
    """pid -> title of its main visible window (the first one found), for nicer names."""
    titles: dict[int, str] = {}
    proto = WINFUNCTYPE(c_int, c_void_p, c_void_p)

    def visit(hwnd, _):
        try:
            if not _user32.IsWindowVisible(hwnd) or _user32.GetWindow(hwnd, 4):   # 4 = GW_OWNER
                return True
            pid = c_ulong()
            _user32.GetWindowThreadProcessId(hwnd, byref(pid))
            if pid.value in titles:
                return True
            n = _user32.GetWindowTextLengthW(hwnd)
            if n > 0:
                buf = ctypes.create_unicode_buffer(n + 1)
                _user32.GetWindowTextW(hwnd, buf, n + 1)
                if buf.value.strip():
                    titles[pid.value] = buf.value.strip()
        except Exception:  # noqa: BLE001
            pass
        return True

    cb = proto(visit)
    _user32.EnumWindows(cb, 0)
    return titles

