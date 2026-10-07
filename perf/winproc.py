"""Reading another process's costs on Windows with ctypes only (no psutil): memory,
CPU time and cycles, disk and other I/O, handles, GDI / USER objects, its threads
and the module each one started in, and its child processes.

Everything here only reads. Nothing is injected into or written to the process
being measured. On other systems `supported()` is False and nothing else is used.
"""
from __future__ import annotations

import ctypes
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"


def supported() -> bool:
    return IS_WINDOWS


MB = 1024 * 1024

if IS_WINDOWS:
    from ctypes import wintypes as wt

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")

    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    PROCESS_VM_READ = 0x0010
    SYNCHRONIZE = 0x00100000
    THREAD_QUERY_INFORMATION = 0x0040
    THREAD_QUERY_LIMITED_INFORMATION = 0x0800
    TH32CS_SNAPPROCESS = 0x2
    TH32CS_SNAPTHREAD = 0x4
    INVALID_HANDLE = ctypes.c_void_p(-1).value
    STILL_ACTIVE = 259

    class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
        _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                    ("PrivateUsage", ctypes.c_size_t)]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                    ("WriteOperationCount", ctypes.c_ulonglong),
                    ("OtherOperationCount", ctypes.c_ulonglong),
                    ("ReadTransferCount", ctypes.c_ulonglong),
                    ("WriteTransferCount", ctypes.c_ulonglong),
                    ("OtherTransferCount", ctypes.c_ulonglong)]

    class THREADENTRY32(ctypes.Structure):
        _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ThreadID", wt.DWORD),
                    ("th32OwnerProcessID", wt.DWORD), ("tpBasePri", wt.LONG),
                    ("tpDeltaPri", wt.LONG), ("dwFlags", wt.DWORD)]

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wt.DWORD),
                    ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
                    ("pcPriClassBase", wt.LONG), ("dwFlags", wt.DWORD),
                    ("szExeFile", wt.WCHAR * 260)]

    class MODULEINFO(ctypes.Structure):
        _fields_ = [("lpBaseOfDll", ctypes.c_void_p), ("SizeOfImage", wt.DWORD),
                    ("EntryPoint", ctypes.c_void_p)]

    H = wt.HANDLE
    k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    k32.OpenProcess.restype = H
    k32.OpenThread.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    k32.OpenThread.restype = H
    k32.CloseHandle.argtypes = [H]
    k32.GetProcessTimes.argtypes = [H] + [ctypes.POINTER(wt.FILETIME)] * 4
    k32.GetThreadTimes.argtypes = [H] + [ctypes.POINTER(wt.FILETIME)] * 4
    k32.GetProcessIoCounters.argtypes = [H, ctypes.POINTER(IO_COUNTERS)]
    k32.GetProcessHandleCount.argtypes = [H, ctypes.POINTER(wt.DWORD)]
    k32.GetExitCodeProcess.argtypes = [H, ctypes.POINTER(wt.DWORD)]
    k32.QueryProcessCycleTime.argtypes = [H, ctypes.POINTER(ctypes.c_ulonglong)]
    k32.QueryThreadCycleTime.argtypes = [H, ctypes.POINTER(ctypes.c_ulonglong)]
    k32.GetCurrentThread.restype = H
    k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
    k32.CreateToolhelp32Snapshot.restype = H
    k32.Thread32First.argtypes = [H, ctypes.POINTER(THREADENTRY32)]
    k32.Thread32Next.argtypes = [H, ctypes.POINTER(THREADENTRY32)]
    k32.Process32FirstW.argtypes = [H, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32NextW.argtypes = [H, ctypes.POINTER(PROCESSENTRY32W)]
    psapi.GetProcessMemoryInfo.argtypes = [H, ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),
                                           wt.DWORD]
    psapi.EnumProcessModulesEx.argtypes = [H, ctypes.POINTER(ctypes.c_void_p), wt.DWORD,
                                           ctypes.POINTER(wt.DWORD), wt.DWORD]
    psapi.GetModuleFileNameExW.argtypes = [H, ctypes.c_void_p, wt.LPWSTR, wt.DWORD]
    psapi.GetModuleInformation.argtypes = [H, ctypes.c_void_p, ctypes.POINTER(MODULEINFO),
                                           wt.DWORD]
    user32.GetGuiResources.argtypes = [H, wt.DWORD]
    user32.GetGuiResources.restype = wt.DWORD
    ntdll.NtQueryInformationThread.argtypes = [H, ctypes.c_int, ctypes.c_void_p, wt.ULONG,
                                               ctypes.POINTER(wt.ULONG)]


def filetime_s(ft) -> float:
    """A FILETIME (100 ns ticks) as seconds."""
    return ((ft.dwHighDateTime << 32) | ft.dwLowDateTime) / 1e7


# ------------------------------------------------------------------ one process

@dataclass
class Sample:
    """What a process costs at one moment (counters are totals since it started)."""
    t: float                 # time.perf_counter() in the measuring process
    private: int = 0         # bytes committed for this process alone (commit charge)
    wset: int = 0            # bytes in RAM now
    peak_wset: int = 0
    page_faults: int = 0
    cpu_user: float = 0.0    # seconds
    cpu_kernel: float = 0.0
    cycles: int = 0          # CPU cycles (QueryProcessCycleTime): finer than the times
    read_bytes: int = 0
    write_bytes: int = 0
    other_bytes: int = 0
    read_ops: int = 0
    write_ops: int = 0
    handles: int = 0
    gdi: int = 0
    user: int = 0
    gdi_peak: int = 0
    user_peak: int = 0
    threads: int = 0
    children: int = 0        # processes it started (any depth), e.g. the web engine's
    children_private: int = 0
    children_wset: int = 0

    def as_dict(self) -> dict:
        return dict(self.__dict__)


class Proc:
    """A handle on one process, for reading its counters."""

    def __init__(self, pid: int):
        self.pid = pid
        self.h = None
        if not IS_WINDOWS:
            return
        for access in (PROCESS_QUERY_INFORMATION | PROCESS_VM_READ | SYNCHRONIZE,
                       PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE):
            h = k32.OpenProcess(access, False, pid)
            if h:
                self.h = h
                break
        if not self.h:
            raise OSError(ctypes.get_last_error(), f"can't open process {pid}")
        self.created = self.times()[2]

    def close(self):
        if self.h:
            k32.CloseHandle(self.h)
            self.h = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def alive(self) -> bool:
        code = wt.DWORD()
        return bool(k32.GetExitCodeProcess(self.h, ctypes.byref(code))) \
            and code.value == STILL_ACTIVE

    def exit_code(self) -> int | None:
        code = wt.DWORD()
        if not k32.GetExitCodeProcess(self.h, ctypes.byref(code)) or code.value == STILL_ACTIVE:
            return None
        return code.value

    def memory(self) -> dict:
        m = PROCESS_MEMORY_COUNTERS_EX()
        m.cb = ctypes.sizeof(m)
        if not psapi.GetProcessMemoryInfo(self.h, ctypes.byref(m), m.cb):
            return {}
        return {"private": m.PrivateUsage, "wset": m.WorkingSetSize,
                "peak_wset": m.PeakWorkingSetSize, "page_faults": m.PageFaultCount}

    def times(self) -> tuple[float, float, float]:
        """(user s, kernel s, creation time as seconds since 1601)."""
        ft = [wt.FILETIME() for _ in range(4)]
        if not k32.GetProcessTimes(self.h, *[ctypes.byref(f) for f in ft]):
            return 0.0, 0.0, 0.0
        return filetime_s(ft[3]), filetime_s(ft[2]), filetime_s(ft[0])

    def cycles(self) -> int:
        c = ctypes.c_ulonglong()
        return c.value if k32.QueryProcessCycleTime(self.h, ctypes.byref(c)) else 0

    def io(self) -> dict:
        c = IO_COUNTERS()
        if not k32.GetProcessIoCounters(self.h, ctypes.byref(c)):
            return {}
        return {"read_bytes": c.ReadTransferCount, "write_bytes": c.WriteTransferCount,
                "other_bytes": c.OtherTransferCount, "read_ops": c.ReadOperationCount,
                "write_ops": c.WriteOperationCount}

    def handles(self) -> int:
        n = wt.DWORD()
        return n.value if k32.GetProcessHandleCount(self.h, ctypes.byref(n)) else 0

    def gui(self) -> dict:
        """GDI and USER objects: now and the most it ever had."""
        g = user32.GetGuiResources
        return {"gdi": g(self.h, 0), "user": g(self.h, 1), "gdi_peak": g(self.h, 2),
                "user_peak": g(self.h, 4)}

    def modules(self) -> list[tuple[int, int, str]]:
        """(base address, size, file name) of every DLL / exe loaded, sorted."""
        arr = (ctypes.c_void_p * 4096)()
        need = wt.DWORD()
        if not psapi.EnumProcessModulesEx(self.h, arr, ctypes.sizeof(arr), ctypes.byref(need), 3):
            return []
        out = []
        buf = ctypes.create_unicode_buffer(1024)
        for i in range(min(need.value // ctypes.sizeof(ctypes.c_void_p), 4096)):
            mi = MODULEINFO()
            if psapi.GetModuleInformation(self.h, arr[i], ctypes.byref(mi), ctypes.sizeof(mi)):
                psapi.GetModuleFileNameExW(self.h, arr[i], buf, 1024)
                out.append((mi.lpBaseOfDll or 0, mi.SizeOfImage, os.path.basename(buf.value)))
        return sorted(out)

    def sample(self, kids: list[int] | None = None) -> Sample:
        s = Sample(t=time.perf_counter())
        for k, v in {**self.memory(), **self.io(), **self.gui()}.items():
            setattr(s, k, v)
        s.cpu_user, s.cpu_kernel, _ = self.times()
        s.cycles = self.cycles()
        s.handles = self.handles()
        s.threads = len(threads_of(self.pid))
        if kids:
            s.children = len(kids)
            for pid in kids:
                try:
                    with Proc(pid) as c:
                        m = c.memory()
                except OSError:
                    continue
                s.children_private += m.get("private", 0)
                s.children_wset += m.get("wset", 0)
        return s


def kill(pid: int) -> bool:
    """End one process by its id (never by name)."""
    h = k32.OpenProcess(0x0001, False, pid)   # PROCESS_TERMINATE
    if not h:
        return False
    try:
        k32.TerminateProcess.argtypes = [H, wt.UINT]
        return bool(k32.TerminateProcess(h, 1))
    finally:
        k32.CloseHandle(h)


# ------------------------------------------------------------------ processes, threads

def processes() -> list[tuple[int, int, str]]:
    """Every process: (pid, parent pid, exe name)."""
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == INVALID_HANDLE:
        return []
    out = []
    try:
        e = PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(e)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            out.append((e.th32ProcessID, e.th32ParentProcessID, e.szExeFile))
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return out


def descendants(pid: int, table: list[tuple[int, int, str]] | None = None) -> list[int]:
    """Processes started by `pid`, and by those, and so on."""
    table = processes() if table is None else table
    kids: dict[int, list[int]] = {}
    for p, parent, _name in table:
        if p != parent:
            kids.setdefault(parent, []).append(p)
    out, todo = [], list(kids.get(pid, []))
    while todo:
        p = todo.pop()
        if p in out:
            continue
        out.append(p)
        todo.extend(kids.get(p, []))
    return out


def threads_of(pid: int) -> list[int]:
    """The thread ids of one process."""
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if not snap or snap == INVALID_HANDLE:
        return []
    out = []
    try:
        e = THREADENTRY32()
        e.dwSize = ctypes.sizeof(e)
        ok = k32.Thread32First(snap, ctypes.byref(e))
        while ok:
            if e.th32OwnerProcessID == pid:
                out.append(e.th32ThreadID)
            ok = k32.Thread32Next(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return out


def owner_of(addr: int | None, mods: list[tuple[int, int, str]]) -> str:
    """The module (file name) an address lies in, '?' if none."""
    if not addr:
        return "?"
    for base, size, name in mods:
        if base <= addr < base + size:
            return name
    return "?"


# thread start module -> group, first match wins (lower-case prefixes)
GROUPS = (
    (("amdxx64", "amdxc64", "atidxx64", "nvwgf2um", "nvd3dum", "igd10", "igd11", "igd12",
      "igc64", "nvldumd", "amdihk64"), "gpu driver"),
    (("libopenblas", "libscipy_openblas", "openblas", "mkl_"), "openblas"),
    (("libportaudio",), "portaudio"),
    (("qt6webengine",), "qt webengine"),
    (("qt6", "pyside6", "shiboken6"), "qt"),
    (("d3d11", "d3d12", "dxgi", "d3d9", "dxcore"), "direct3d"),
    (("dsound", "winmm", "audioses", "mmdevapi", "wdmaud", "avrt"), "windows audio"),
    (("combase", "rpcrt4", "ole32"), "windows com"),
    (("ntdll", "kernelbase", "kernel32"), "windows pool"),
    (("ucrtbase", "python3", "python.exe", "pythonw.exe", "msvcrt", "vcruntime"), "python"),
)


def group_of(module: str, main_exe: str = "") -> str:
    m = module.lower()
    if main_exe and m == main_exe.lower():
        return "main"
    for prefixes, group in GROUPS:
        if m.startswith(prefixes):
            return group
    return "other: " + (Path(m).stem or "?")


@dataclass
class ThreadRec:
    tid: int
    handle: int
    start: int | None
    module: str = "?"
    created: float = 0.0
    last_cycles: int = 0
    gone: bool = False


@dataclass
class ThreadTracker:
    """Keeps a handle on every thread of a process it has seen, so the cycles of a
    thread that ends between two looks still count, and names each one by the module
    it started in (Python's own threads all start in the C runtime: the measured
    process can name those by their native id, see `names`)."""
    proc: Proc
    main_exe: str = ""
    names: dict[int, str] = field(default_factory=dict)   # native id -> python name
    recs: dict[int, ThreadRec] = field(default_factory=dict)
    _mods: list = field(default_factory=list)
    _mods_n: int = 0

    def _refresh_modules(self):
        self._mods = self.proc.modules()
        self._mods_n = len(self._mods)

    def _open(self, tid: int) -> ThreadRec | None:
        for access in (THREAD_QUERY_INFORMATION, THREAD_QUERY_LIMITED_INFORMATION):
            h = k32.OpenThread(access, False, tid)
            if h:
                break
        else:
            return None
        addr = ctypes.c_void_p()
        start = None
        if ntdll.NtQueryInformationThread(h, 9, ctypes.byref(addr), ctypes.sizeof(addr),
                                          None) == 0:
            start = addr.value or 0
        ft = [wt.FILETIME() for _ in range(4)]
        created = filetime_s(ft[0]) if k32.GetThreadTimes(h, *[ctypes.byref(f) for f in ft]) \
            else 0.0
        return ThreadRec(tid, h, start, created=created)

    def _cycles(self, rec: ThreadRec) -> int:
        c = ctypes.c_ulonglong()
        if k32.QueryThreadCycleTime(rec.handle, ctypes.byref(c)):
            rec.last_cycles = c.value
        return rec.last_cycles

    def look(self) -> dict[int, int]:
        """{tid: cycles so far} for every thread seen, live or ended since."""
        live = set(threads_of(self.proc.pid))
        new = [t for t in live if t not in self.recs or self.recs[t].gone]
        if new:
            self._refresh_modules()
        for tid in new:
            old = self.recs.pop(tid, None)
            if old is not None:   # an id used again: keep the old one's cycles apart
                self.recs[-tid - len(self.recs) * 1_000_000] = old
            rec = self._open(tid)
            if rec is not None:
                rec.module = owner_of(rec.start, self._mods)
                self.recs[tid] = rec
        for tid, rec in self.recs.items():
            if not rec.gone:
                self._cycles(rec)
                if tid not in live:
                    rec.gone = True
                    k32.CloseHandle(rec.handle)
        return {tid: r.last_cycles for tid, r in self.recs.items()}

    def group(self, tid: int) -> str:
        rec = self.recs.get(tid)
        if rec is None:
            return "?"
        name = self.names.get(tid)
        g = group_of(rec.module, self.main_exe)
        if name is not None and g in ("python", "main", "?"):
            return name
        return g

    def census(self) -> dict[str, int]:
        """Live threads per group."""
        out: dict[str, int] = {}
        for tid, rec in self.recs.items():
            if not rec.gone:
                g = self.group(tid)
                out[g] = out.get(g, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    def close(self):
        for rec in self.recs.values():
            if not rec.gone:
                k32.CloseHandle(rec.handle)
                rec.gone = True


def cycles_by_group(tracker: ThreadTracker, before: dict[int, int],
                    after: dict[int, int]) -> dict[str, int]:
    out: dict[str, int] = {}
    for tid, c in after.items():
        d = c - before.get(tid, 0)
        if d > 0:
            g = tracker.group(tid)
            out[g] = out.get(g, 0) + d
    return out


# ------------------------------------------------------------------ calibration, disk

def cycles_per_second(secs: float = 0.2) -> float:
    """How many cycles QueryThreadCycleTime counts per second on this PC, measured on
    the calling thread kept busy. The counter runs at a fixed rate on current CPUs,
    so this turns any thread's or process's cycles into CPU seconds."""
    if not IS_WINDOWS:
        return 0.0
    h = k32.GetCurrentThread()
    c0, c1 = ctypes.c_ulonglong(), ctypes.c_ulonglong()
    best = 0.0
    for _ in range(3):
        k32.QueryThreadCycleTime(h, ctypes.byref(c0))
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < secs / 3:
            pass
        k32.QueryThreadCycleTime(h, ctypes.byref(c1))
        rate = (c1.value - c0.value) / (time.perf_counter() - t0)
        best = max(best, rate)   # the run least interrupted
    return best


def folder_size(path: Path) -> tuple[int, int]:
    """(bytes, files) under a folder."""
    total = files = 0
    for root, _dirs, names in os.walk(path):
        for n in names:
            try:
                total += os.path.getsize(os.path.join(root, n))
                files += 1
            except OSError:
                pass
    return total, files


def biggest_files(path: Path, n: int = 20) -> list[tuple[str, int]]:
    out = []
    for root, _dirs, names in os.walk(path):
        for name in names:
            p = os.path.join(root, name)
            try:
                out.append((os.path.relpath(p, path), os.path.getsize(p)))
            except OSError:
                pass
    return sorted(out, key=lambda kv: -kv[1])[:n]
