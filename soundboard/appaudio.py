"""Per-program audio capture: tap one running program's sound (Spotify, a browser, a
game, a call in another app) and push it into the engine so it goes out through
the virtual cable like a sound, without touching what any other program plays.

Windows 10 build 20348+ and Windows 11 have this built into WASAPI ("process
loopback", what Discord's and OBS's application-audio capture use). It is a *copy*
of the program's audio: the program keeps playing on your speakers as before.

Everything here is ctypes over COM (no extra packages). Nothing in it works
outside Windows; `supported()` says whether this machine can do it, and a failed
`AppCapture.start()` explains why in `error`.

  list_apps()          programs that currently have an audio session, with a level
  AppCapture(pid, sink) a thread that captures that program (and its child
                        processes) and calls `sink((n, 2) float32 at 48 kHz)`
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
import time
from ctypes import (POINTER, Structure, Union, addressof, byref, c_float, c_int, c_int64,
                    c_long, c_ubyte, c_uint, c_ulong, c_ushort, c_void_p, c_wchar_p, cast, sizeof)
from dataclasses import dataclass, field

import numpy as np

log = logging.getLogger(__name__)

SR = 48000            # what the sink gets (the engine's storage rate)
MIN_BUILD = 20348     # first Windows build with process loopback

S_OK = 0
E_NOINTERFACE = -2147467262
CLSCTX_ALL = 23
COINIT_MULTITHREADED = 0
RPC_E_CHANGED_MODE = -2147417850
VT_BLOB = 0x41
VT_LPWSTR = 31
STGM_READ = 0
E_RENDER, DEVICE_STATE_ACTIVE = 0, 1
E_CONSOLE = 0   # ERole: the default device (not the communications one)
AUDCLNT_SHAREMODE_SHARED = 0
AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000
AUDCLNT_BUFFERFLAGS_SILENT = 0x2
AUDCLNT_E_UNSUPPORTED_FORMAT = -2004287480       # 0x88890008
AUDCLNT_E_DEVICE_INVALIDATED = -2004287484       # 0x88890004
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259
WAVE_FORMAT_PCM, WAVE_FORMAT_IEEE_FLOAT, WAVE_FORMAT_EXTENSIBLE = 1, 3, 0xFFFE
PROCESS_LOOPBACK_MODE_INCLUDE_TREE, PROCESS_LOOPBACK_MODE_EXCLUDE_TREE = 0, 1
AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK = 1
VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK = "VAD\\Process_Loopback"
# Windows' own sounds and helpers: never something you'd want to send to a call
SYSTEM_EXES = {"svchost.exe", "audiodg.exe", "explorer.exe", "shellexperiencehost.exe"}

_win = sys.platform == "win32"
if _win:
    from ctypes import WINFUNCTYPE, windll
    _ole32, _k32, _user32 = windll.ole32, windll.kernel32, windll.user32
    _mmdev = None   # mmdevapi.dll, loaded on first capture (it's not on Windows 7)
    # handles and pointers are 64-bit: without these, ctypes would pass them as C ints
    for _f, _res, _args in (
        (_k32.OpenProcess, c_void_p, (c_ulong, c_int, c_ulong)),
        (_k32.CloseHandle, c_int, (c_void_p,)),
        (_k32.GetExitCodeProcess, c_int, (c_void_p, c_void_p)),
        (_k32.QueryFullProcessImageNameW, c_int, (c_void_p, c_ulong, c_void_p, c_void_p)),
        (_k32.CreateToolhelp32Snapshot, c_void_p, (c_ulong, c_ulong)),
        (_k32.Process32FirstW, c_int, (c_void_p, c_void_p)),
        (_k32.Process32NextW, c_int, (c_void_p, c_void_p)),
        (_k32.CreateEventW, c_void_p, (c_void_p, c_int, c_int, c_void_p)),
        (_k32.WaitForSingleObject, c_ulong, (c_void_p, c_ulong)),
        (_user32.IsWindowVisible, c_int, (c_void_p,)),
        (_user32.GetWindow, c_void_p, (c_void_p, c_uint)),
        (_user32.GetWindowThreadProcessId, c_ulong, (c_void_p, c_void_p)),
        (_user32.GetWindowTextLengthW, c_int, (c_void_p,)),
        (_user32.GetWindowTextW, c_int, (c_void_p, c_void_p, c_int)),
        (_user32.EnumWindows, c_int, (c_void_p, c_void_p)),
        (_ole32.CoInitializeEx, c_long, (c_void_p, c_ulong)),
        (_ole32.CoUninitialize, None, ()),
        (_ole32.CoCreateInstance, c_long, (c_void_p, c_void_p, c_ulong, c_void_p, c_void_p)),
        (_ole32.CoTaskMemFree, None, (c_void_p,)),
        (_ole32.PropVariantClear, c_long, (c_void_p,)),
    ):
        _f.restype, _f.argtypes = _res, _args


def supported() -> tuple[bool, str]:
    """(can this machine capture a program's audio, why not)."""
    if not _win:
        return False, "Capturing a program's audio needs Windows."
    build = sys.getwindowsversion().build
    if build < MIN_BUILD:
        return False, (f"Capturing a program's audio needs Windows 11 or Windows 10 build "
                       f"{MIN_BUILD} or newer (this is build {build}).")
    return True, ""


# --------------------------------------------------------------------------- COM plumbing

class GUID(Structure):
    _fields_ = [("d1", c_ulong), ("d2", c_ushort), ("d3", c_ushort), ("d4", c_ubyte * 8)]

    @classmethod
    def of(cls, text: str) -> GUID:
        p = text.strip("{}").split("-")
        g = cls()
        g.d1, g.d2, g.d3 = int(p[0], 16), int(p[1], 16), int(p[2], 16)
        g.d4 = (c_ubyte * 8)(*bytes.fromhex(p[3] + p[4]))   # not c_char: it stops at a 0 byte
        return g

    def __eq__(self, other):
        return isinstance(other, GUID) and bytes(self) == bytes(other)

    __hash__ = None


IID_IUnknown = GUID.of("00000000-0000-0000-C000-000000000046")
IID_IAgileObject = GUID.of("94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90")
IID_IAudioClient = GUID.of("1CB9AD4C-DBFA-4C32-B178-C2F568A703B2")
IID_IAudioCaptureClient = GUID.of("C8ADBD64-E71E-48A0-A4DE-185C395CD317")
IID_ICompletionHandler = GUID.of("41D949AB-9862-444A-80F6-C261334DA5EB")
IID_IMMDeviceEnumerator = GUID.of("A95664D2-9614-4F35-A746-DE8DB63617E6")
CLSID_MMDeviceEnumerator = GUID.of("BCDE0395-E52F-467C-8E3D-C4579291692E")
IID_IAudioSessionManager2 = GUID.of("77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F")
IID_IAudioSessionControl2 = GUID.of("BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D")
IID_IAudioMeterInformation = GUID.of("C02216F6-8C67-4B5B-9D00-D008E73E0064")
KSDATAFORMAT_SUBTYPE_IEEE_FLOAT = GUID.of("00000003-0000-0010-8000-00AA00389B71")
KSDATAFORMAT_SUBTYPE_PCM = GUID.of("00000001-0000-0010-8000-00AA00389B71")


class PROPERTYKEY(Structure):
    _fields_ = [("fmtid", GUID), ("pid", c_ulong)]


PKEY_Device_FriendlyName = PROPERTYKEY(GUID.of("A45C254E-DF1C-4EFD-8020-67D146A850E0"), 14)


class BLOB(Structure):
    _fields_ = [("cbSize", c_ulong), ("pBlobData", c_void_p)]


class _PVU(Union):
    _fields_ = [("blob", BLOB), ("pwszVal", c_void_p)]


class PROPVARIANT(Structure):
    _fields_ = [("vt", c_ushort), ("r1", c_ushort), ("r2", c_ushort), ("r3", c_ushort),
                ("u", _PVU)]


class ACTIVATION_PARAMS(Structure):
    """AUDIOCLIENT_ACTIVATION_PARAMS with its one union member, the process-loopback params."""
    _fields_ = [("ActivationType", c_ulong), ("TargetProcessId", c_ulong),
                ("ProcessLoopbackMode", c_ulong)]


class WAVEFORMATEX(Structure):
    _pack_ = 1
    _fields_ = [("wFormatTag", c_ushort), ("nChannels", c_ushort), ("nSamplesPerSec", c_ulong),
                ("nAvgBytesPerSec", c_ulong), ("nBlockAlign", c_ushort),
                ("wBitsPerSample", c_ushort), ("cbSize", c_ushort)]


class WAVEFORMATEXTENSIBLE(Structure):
    _pack_ = 1
    _fields_ = [("Format", WAVEFORMATEX), ("wValidBitsPerSample", c_ushort),
                ("dwChannelMask", c_ulong), ("SubFormat", GUID)]


class ComError(OSError):
    def __init__(self, hr: int, what: str = ""):
        self.hr = hr & 0xFFFFFFFF
        super().__init__(f"{what or 'COM call'} failed: 0x{self.hr:08X}")


_protos: dict = {}


class Com:
    """A raw COM interface pointer: calls by vtable slot, released once."""

    def __init__(self, ptr: int | None):
        if not ptr:
            raise ComError(-2147467261, "null interface")   # E_POINTER
        self.ptr = ptr

    def _fn(self, slot: int, argtypes: tuple, restype=c_long):
        key = (slot, argtypes, restype)
        proto = _protos.get(key)
        if proto is None:
            proto = _protos[key] = WINFUNCTYPE(restype, c_void_p, *argtypes)
        vtbl = cast(self.ptr, POINTER(c_void_p))[0]
        return proto(cast(vtbl, POINTER(c_void_p))[slot])

    def call(self, slot: int, argtypes: tuple, *args, what: str = "") -> int:
        hr = self._fn(slot, argtypes)(self.ptr, *args)
        if hr < 0:
            raise ComError(hr, what or f"slot {slot}")
        return hr

    def qi(self, iid: GUID) -> Com:
        out = c_void_p()
        self.call(0, (POINTER(GUID), POINTER(c_void_p)), byref(iid), byref(out),
                  what="QueryInterface")
        return Com(out.value)

    def release(self):
        if self.ptr:
            p, self.ptr = self.ptr, None
            try:
                proto = _protos.get((2, (), c_ulong)) or WINFUNCTYPE(c_ulong, c_void_p)
                _protos[(2, (), c_ulong)] = proto
                proto(cast(cast(p, POINTER(c_void_p))[0], POINTER(c_void_p))[2])(p)
            except Exception:  # noqa: BLE001
                log.debug("Release raised", exc_info=True)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.release()


def _co_init() -> bool:
    """CoInitializeEx for this thread. Returns whether we own the uninit."""
    hr = _ole32.CoInitializeEx(None, COINIT_MULTITHREADED)
    if hr == RPC_E_CHANGED_MODE:
        return False   # the thread is already STA (Qt's main thread): calls still work
    if hr < 0:
        raise ComError(hr, "CoInitializeEx")
    return hr == S_OK   # S_FALSE = already initialised on this thread, still ours to balance


def _enumerator() -> Com:
    out = c_void_p()
    hr = _ole32.CoCreateInstance(byref(CLSID_MMDeviceEnumerator), None, CLSCTX_ALL,
                                 byref(IID_IMMDeviceEnumerator), byref(out))
    if hr < 0:
        raise ComError(hr, "CoCreateInstance(MMDeviceEnumerator)")
    return Com(out.value)


def _render_devices(en: Com) -> list[Com]:
    coll = c_void_p()
    en.call(3, (c_int, c_ulong, POINTER(c_void_p)), E_RENDER, DEVICE_STATE_ACTIVE, byref(coll),
            what="EnumAudioEndpoints")
    devs = []
    with Com(coll.value) as c:
        n = c_uint()
        c.call(3, (POINTER(c_uint),), byref(n), what="GetCount")
        for i in range(n.value):
            d = c_void_p()
            c.call(4, (c_uint, POINTER(c_void_p)), i, byref(d), what="Item")
            devs.append(Com(d.value))
    return devs


def _device_name(dev: Com) -> str:
    store = c_void_p()
    try:
        dev.call(4, (c_ulong, POINTER(c_void_p)), STGM_READ, byref(store), what="OpenPropertyStore")
        with Com(store.value) as s:
            pv = PROPVARIANT()
            s.call(5, (POINTER(PROPERTYKEY), POINTER(PROPVARIANT)), byref(PKEY_Device_FriendlyName),
                   byref(pv), what="GetValue")
            try:
                if pv.vt == VT_LPWSTR and pv.u.pwszVal:
                    return cast(pv.u.pwszVal, c_wchar_p).value or ""
            finally:
                _ole32.PropVariantClear(byref(pv))
    except ComError:
        log.debug("device name unavailable", exc_info=True)
    return ""


def _cotaskmem_str(p: c_void_p) -> str:
    if not p.value:
        return ""
    try:
        return cast(p.value, c_wchar_p).value or ""
    finally:
        _ole32.CoTaskMemFree(p.value)


# --------------------------------------------------------------------------- processes

_names: dict[int, str] = {}   # pid -> full image path (a pid can be reused, but rarely mid-list)


def process_path(pid: int) -> str:
    """Full path of the process's .exe ('' if it can't be opened)."""
    if pid in _names:
        return _names[pid]
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
    _names[pid] = path
    return path


def is_running(pid: int) -> bool:
    """False once the process has exited. A process we may not open (a service, a
    game guarded by anti-cheat) counts as running: we can't tell."""
    h = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ctypes.get_last_error() == 5 or _k32.GetLastError() == 5   # ERROR_ACCESS_DENIED
    try:
        code = c_ulong()
        return bool(_k32.GetExitCodeProcess(h, byref(code))) and code.value == STILL_ACTIVE
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


def root_pid(pid: int, table: dict[int, tuple[int, str]] | None = None) -> int:
    """The topmost ancestor with the same .exe name. Browsers and chat apps play
    their audio from a helper child process that comes and goes; capturing the main
    process *and its tree* keeps following them."""
    table = table if table is not None else _process_table()
    if pid not in table:
        return pid
    exe = table[pid][1]
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


# --------------------------------------------------------------------------- sessions

@dataclass
class App:
    """A program with an audio session. `pid` is the process to capture (the root of
    its process tree); `session_pids` the ones actually holding sessions."""
    pid: int
    exe: str                 # 'spotify.exe'
    path: str = ""
    title: str = ""          # main window title, if it has one
    active: bool = False     # playing right now (vs. quiet but still open)
    peak: float = 0.0        # 0..1, from Windows' own session meter
    devices: list[str] = field(default_factory=list)   # where it's playing
    session_pids: set = field(default_factory=set)

    @property
    def name(self) -> str:
        """Short display name: 'Spotify' from spotify.exe."""
        stem = os.path.splitext(self.exe)[0]
        return stem[:1].upper() + stem[1:] if stem else f"pid {self.pid}"


def default_output_name() -> str | None:
    """The name of Windows' default playback device, asked now (PortAudio only knows
    the one from when it started). None if it can't be asked."""
    if not _win:
        return None
    own = _co_init()
    try:
        with _enumerator() as en:
            d = c_void_p()
            en.call(4, (c_int, c_int, POINTER(c_void_p)), E_RENDER, E_CONSOLE, byref(d),
                    what="GetDefaultAudioEndpoint")
            with Com(d.value) as dev:
                return _device_name(dev) or None
    except ComError:
        log.debug("no default playback device", exc_info=True)
        return None
    finally:
        if own:
            _ole32.CoUninitialize()


def list_apps() -> list[App]:
    """Every program with a live audio session on any playback device, this
    process excluded and grouped by process tree. Safe from any thread."""
    if not _win:
        return []
    own = _co_init()
    try:
        return _list_apps()
    except ComError:
        log.debug("listing audio sessions failed", exc_info=True)
        return []
    finally:
        if own:
            _ole32.CoUninitialize()


def _list_apps(meters: dict | None = None) -> list[App]:
    """With `meters`, also keeps each session's IAudioMeterInformation there
    (root pid -> [Com]) for the caller to read and release; window titles are skipped."""
    me = os.getpid()
    table = _process_table()
    apps: dict[int, App] = {}
    with _enumerator() as en:
        devices = _render_devices(en)
    try:
        for dev in devices:
            dname = _device_name(dev)
            mgr = c_void_p()
            try:
                dev.call(3, (POINTER(GUID), c_ulong, c_void_p, POINTER(c_void_p)),
                         byref(IID_IAudioSessionManager2), CLSCTX_ALL, None, byref(mgr),
                         what="Activate(IAudioSessionManager2)")
            except ComError:
                continue
            with Com(mgr.value) as m:
                en_ptr = c_void_p()
                m.call(5, (POINTER(c_void_p),), byref(en_ptr), what="GetSessionEnumerator")
                with Com(en_ptr.value) as se:
                    n = c_int()
                    se.call(3, (POINTER(c_int),), byref(n), what="GetCount")
                    for i in range(n.value):
                        ctl = c_void_p()
                        try:
                            se.call(4, (c_int, POINTER(c_void_p)), i, byref(ctl), what="GetSession")
                        except ComError:
                            continue
                        with Com(ctl.value) as c:
                            _read_session(c, dname, me, table, apps, meters)
    finally:
        for dev in devices:
            dev.release()
    titles = window_titles() if apps and meters is None else {}
    for app in apps.values():
        pids = (app.pid, *sorted(app.session_pids))
        app.title = next((titles[p] for p in pids if p in titles), "")
    return sorted(apps.values(), key=lambda a: (not a.active, a.name.lower(), a.pid))


def _read_session(c: Com, dname: str, me: int, table, apps: dict[int, App],
                  meters: dict | None = None):
    with c.qi(IID_IAudioSessionControl2) as c2:
        state = c_int()
        c2.call(3, (POINTER(c_int),), byref(state), what="GetState")
        if state.value == 2:   # expired
            return
        if c2.call(15, (), what="IsSystemSoundsSession") == S_OK:
            return
        pid = c_ulong()
        c2.call(14, (POINTER(c_ulong),), byref(pid), what="GetProcessId")
        if not pid.value or pid.value == me:
            return
        if (table.get(pid.value, (0, ""))[1] in SYSTEM_EXES):
            return
        peak = c_float()
        try:
            with c2.qi(IID_IAudioMeterInformation) as meter:
                meter.call(3, (POINTER(c_float),), byref(peak), what="GetPeakValue")
        except ComError:
            pass
    root = root_pid(pid.value, table)
    if root == me:   # a child of ours (a test helper): don't fold it into this process
        root = pid.value
    app = apps.get(root)
    if app is None:
        path = process_path(pid.value) or process_path(root)
        exe = os.path.basename(path) or table.get(root, (0, ""))[1] or f"pid {root}"
        app = apps[root] = App(root, exe, path)
    app.session_pids.add(pid.value)
    app.active = app.active or state.value == 1
    app.peak = max(app.peak, float(peak.value))
    if dname and dname not in app.devices:
        app.devices.append(dname)
    if meters is not None:
        try:
            meters.setdefault(root, []).append(c.qi(IID_IAudioMeterInformation))
        except ComError:
            pass


class PeakWatcher:
    """Live levels of every program, from Windows' own session meters, read
    ~20 times a second on a worker thread (`list_apps` is too slow to re-run that
    often: it walks processes and windows). The sessions are re-found every
    `rescan` seconds. `peak(pid)` takes the root pid, as in `App.pid`."""

    def __init__(self, interval: float = 0.05, rescan: float = 1.5):
        self.interval, self.rescan = interval, rescan
        self._peaks: dict[int, float] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def peak(self, pid: int) -> float | None:
        """0..1, or None if the program has no session the watcher knows of yet."""
        return self._peaks.get(pid)

    def start(self):
        if not _win or (self._thread and self._thread.is_alive()):
            return
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(self._stop,),
                                        name="apppeaks", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread = None
        self._peaks = {}

    def _run(self, stop: threading.Event):
        meters: dict[int, list[Com]] = {}
        own = _co_init()
        try:
            next_scan = 0.0
            peak = c_float()
            while not stop.is_set():
                if time.monotonic() >= next_scan:
                    _release_meters(meters)
                    meters = {}
                    try:
                        _list_apps(meters)
                    except ComError:
                        log.debug("finding session meters failed", exc_info=True)
                    next_scan = time.monotonic() + self.rescan
                old, peaks = self._peaks, {}
                for pid, ms in meters.items():
                    v = 0.0
                    for m in ms:
                        try:
                            m.call(3, (POINTER(c_float),), byref(peak), what="GetPeakValue")
                            v = max(v, float(peak.value))
                        except ComError:
                            pass
                    peaks[pid] = max(v, old.get(pid, 0.0) * 0.8)   # fall, don't flicker
                if not stop.is_set():
                    self._peaks = peaks
                stop.wait(self.interval)
        except Exception:  # noqa: BLE001
            log.exception("program level watcher failed")
        finally:
            _release_meters(meters)
            if own:
                _ole32.CoUninitialize()


def _release_meters(meters: dict):
    for ms in meters.values():
        for m in ms:
            m.release()


# --------------------------------------------------------------------------- capture

_QI_T = _REF_T = _DONE_T = None
if _win:
    _QI_T = WINFUNCTYPE(c_long, c_void_p, POINTER(GUID), POINTER(c_void_p))
    _REF_T = WINFUNCTYPE(c_ulong, c_void_p)
    _DONE_T = WINFUNCTYPE(c_long, c_void_p, c_void_p)


class _Handler:
    """A minimal COM object implementing IActivateAudioInterfaceCompletionHandler
    (and IAgileObject, so the callback may come from any thread). ActivateAudioInterfaceAsync
    needs one; we just wait for it to fire.

    Windows holds its own references and may call back after we stopped waiting (a
    timeout), so every handler is parked in `_live` and only dropped once it has fired
    and Windows released it -- freeing the thunks earlier would crash the process."""

    _live: list[_Handler] = []
    _live_lock = threading.Lock()

    def __init__(self):
        self.done = threading.Event()
        self.hr = S_OK
        self.punk: int | None = None
        self._lock = threading.Lock()
        self._refs = 1            # our own; Windows AddRefs/Releases on top
        self._abandoned = False   # we gave up waiting: release whatever arrives late
        self._reaped = False      # seen finished once; dropped on the next pass
        self._funcs = (_QI_T(self._query), _REF_T(self._add_ref), _REF_T(self._release),
                       _DONE_T(self._completed))
        self._vtbl = (c_void_p * 4)(*(cast(f, c_void_p).value for f in self._funcs))
        self._obj = c_void_p(addressof(self._vtbl))   # the object: its one field is the vtable
        self.ptr = addressof(self._obj)
        with _Handler._live_lock:
            # Two passes before freeing, so a Release() thunk that is still returning
            # on another thread when it's first seen finished is long gone by the second.
            keep = []
            for h in _Handler._live:
                if h.done.is_set() and h._refs <= 1:
                    if h._reaped:
                        continue
                    h._reaped = True
                keep.append(h)
            keep.append(self)
            _Handler._live = keep

    def _add_ref(self, _this):
        with self._lock:
            self._refs += 1
            return self._refs

    def _release(self, _this):
        with self._lock:
            self._refs = max(1, self._refs - 1)   # never below our own reference
            return self._refs

    def abandon(self):
        """Stop waiting: a result that still arrives later is released, not leaked."""
        with self._lock:
            self._abandoned = True
            punk, self.punk = self.punk, None
        if punk:
            Com(punk).release()

    def _query(self, this, riid, ppv):
        if riid.contents in (IID_IUnknown, IID_ICompletionHandler, IID_IAgileObject):
            self._add_ref(this)
            ppv[0] = this
            return S_OK
        ppv[0] = None
        return E_NOINTERFACE

    def _completed(self, _this, op):
        try:
            hr, punk = c_long(), c_void_p()
            Com(op).call(3, (POINTER(c_long), POINTER(c_void_p)), byref(hr), byref(punk),
                         what="GetActivateResult")
            with self._lock:
                late = self._abandoned
                if not late:
                    self.hr, self.punk = hr.value, punk.value
            if late and punk.value:
                Com(punk.value).release()
        except ComError as e:
            self.hr = e.hr - (1 << 32) if e.hr & 0x80000000 else e.hr
        except Exception:  # noqa: BLE001
            log.exception("activation callback failed")
            self.hr = -1
        finally:
            self.done.set()
        return S_OK


def _format(kind: str) -> WAVEFORMATEX:
    if kind == "f32":
        return WAVEFORMATEX(WAVE_FORMAT_IEEE_FLOAT, 2, SR, SR * 8, 8, 32, 0)
    return WAVEFORMATEX(WAVE_FORMAT_PCM, 2, SR, SR * 4, 4, 16, 0)


def to_stereo_f32(raw: bytes, fmt: WAVEFORMATEX, is_float: bool) -> np.ndarray:
    """Interleaved capture bytes -> (n, 2) float32 (any channel count / sample width)."""
    ch, bits = fmt.nChannels, fmt.wBitsPerSample
    if is_float and bits == 32:
        x = np.frombuffer(raw, np.float32)
    elif bits == 16:
        x = np.frombuffer(raw, np.int16).astype(np.float32) * np.float32(1 / 32768)
    elif bits == 32:
        x = np.frombuffer(raw, np.int32).astype(np.float32) * np.float32(1 / 2147483648)
    elif bits == 24:
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
        x = ((b[:, 0] << 8) | (b[:, 1] << 16) | (b[:, 2] << 24)).astype(np.float32) / 2147483648
    else:
        x = np.frombuffer(raw, np.uint8).astype(np.float32) * np.float32(1 / 128) - 1
    x = x.reshape(-1, max(ch, 1))
    if ch == 1:
        x = np.repeat(x, 2, axis=1)
    elif ch > 2:
        x = x[:, :2]
    return np.ascontiguousarray(x, dtype=np.float32)


class AppCapture:
    """Captures one program's audio on its own thread and hands it to `sink` as
    (n, 2) float32 chunks at 48 kHz. `start()` blocks until the capture is running
    or has failed (`error`). The thread also ends by itself when the program exits
    (`ended`)."""

    def __init__(self, pid: int, sink, include_tree: bool = True, name: str = ""):
        self.pid, self.sink, self.include_tree = int(pid), sink, include_tree
        self.name = name or str(pid)
        self.error: str | None = None
        self.ended = False           # the program closed (or the device went away)
        self.frames = 0              # captured so far, at 48 kHz
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"appcapture-{pid}", daemon=True)

    # -- lifecycle
    def start(self, timeout: float = 6.0) -> bool:
        if not _win:
            self.error = supported()[1]
            return False
        if not is_running(self.pid):   # Windows would happily "capture" a pid that's gone
            self.error = "That program isn't running any more."
            self.ended = True
            return False
        self._thread.start()
        if not self._ready.wait(timeout):
            self.error = "Windows didn't answer in time. Switch Send on to try again."
            self._stop.set()
            return False
        return self.error is None

    def stop(self):
        self._stop.set()
        if self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(3)

    @property
    def running(self) -> bool:
        return self._thread.is_alive() and self.error is None and not self.ended

    # -- the thread
    def _run(self):
        own = False
        try:
            own = _co_init()
            self._capture()
        except ComError as e:
            if e.hr == AUDCLNT_E_DEVICE_INVALIDATED & 0xFFFFFFFF and self._ready.is_set():
                # the output device changed mid-capture: not an error, just start over
                self.ended = True
                log.info("app capture %s: the audio device went away", self.name)
            else:
                self.error = _explain(e)
                log.warning("app capture %s: %s", self.name, self.error)
        except Exception as e:  # noqa: BLE001
            self.error = str(e) or type(e).__name__
            log.exception("app capture %s failed", self.name)
        finally:
            self._ready.set()
            if own:
                _ole32.CoUninitialize()

    def _activate(self) -> Com:
        global _mmdev
        if _mmdev is None:
            _mmdev = windll.LoadLibrary("Mmdevapi.dll")
            _mmdev.ActivateAudioInterfaceAsync.restype = c_long
            _mmdev.ActivateAudioInterfaceAsync.argtypes = (c_wchar_p, c_void_p, c_void_p,
                                                           c_void_p, c_void_p)
        params = ACTIVATION_PARAMS(AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK, self.pid,
                                   PROCESS_LOOPBACK_MODE_INCLUDE_TREE if self.include_tree
                                   else PROCESS_LOOPBACK_MODE_EXCLUDE_TREE)
        pv = PROPVARIANT()
        pv.vt = VT_BLOB
        pv.u.blob.cbSize = sizeof(params)
        pv.u.blob.pBlobData = addressof(params)
        handler = _Handler()
        op = c_void_p()
        hr = _mmdev.ActivateAudioInterfaceAsync(c_wchar_p(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK),
                                                byref(IID_IAudioClient), byref(pv), handler.ptr,
                                                byref(op))
        if hr < 0:
            raise ComError(hr, "ActivateAudioInterfaceAsync")
        try:
            if not handler.done.wait(5.0):
                handler.abandon()   # it stays alive in _Handler._live for a late callback
                raise TimeoutError("Windows didn't answer the capture request.")
        finally:
            Com(op.value).release()
        if handler.hr < 0:
            raise ComError(handler.hr, "activating the capture")
        with Com(handler.punk) as punk:
            return punk.qi(IID_IAudioClient)

    def _capture(self):
        client = fmt = None
        for kind in ("f32", "i16"):   # the audio engine converts to whatever we ask for
            client = self._activate()
            fmt = _format(kind)
            try:
                client.call(3, (c_ulong, c_ulong, c_int64, c_int64, POINTER(WAVEFORMATEX),
                                c_void_p), AUDCLNT_SHAREMODE_SHARED,
                            AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_EVENTCALLBACK,
                            1_000_000, 0, byref(fmt), None, what="Initialize")
                break
            except ComError as e:
                client.release()
                client = None
                if e.hr != AUDCLNT_E_UNSUPPORTED_FORMAT & 0xFFFFFFFF or kind == "i16":
                    raise
        is_float = fmt.wFormatTag == WAVE_FORMAT_IEEE_FLOAT
        evt = _k32.CreateEventW(None, False, False, None)
        cap = None
        try:
            client.call(13, (c_void_p,), evt, what="SetEventHandle")
            out = c_void_p()
            client.call(14, (POINTER(GUID), POINTER(c_void_p)), byref(IID_IAudioCaptureClient),
                        byref(out), what="GetService(IAudioCaptureClient)")
            cap = Com(out.value)
            client.call(10, (), what="Start")
            self._ready.set()
            self._loop(cap, fmt, is_float, evt)
        finally:
            try:
                client.call(11, (), what="Stop")
            except ComError:
                pass
            if cap is not None:
                cap.release()
            client.release()
            _k32.CloseHandle(evt)

    def _loop(self, cap: Com, fmt: WAVEFORMATEX, is_float: bool, evt):
        align = fmt.nBlockAlign
        n, frames, flags, data = c_uint(), c_uint(), c_ulong(), c_void_p()
        next_alive = time.monotonic() + 1.0
        while not self._stop.is_set():
            _k32.WaitForSingleObject(evt, 20)
            while True:
                cap.call(5, (POINTER(c_uint),), byref(n), what="GetNextPacketSize")
                if not n.value:
                    break
                cap.call(3, (POINTER(c_void_p), POINTER(c_uint), POINTER(c_ulong), c_void_p,
                             c_void_p), byref(data), byref(frames), byref(flags), None, None,
                         what="GetBuffer")
                try:
                    if flags.value & AUDCLNT_BUFFERFLAGS_SILENT or not data.value:
                        x = np.zeros((frames.value, 2), np.float32)
                    else:
                        x = to_stereo_f32(ctypes.string_at(data.value, frames.value * align),
                                          fmt, is_float)
                finally:
                    cap.call(4, (c_uint,), frames.value, what="ReleaseBuffer")
                self.frames += len(x)
                try:
                    self.sink(x)
                except Exception:  # noqa: BLE001
                    from soundboard import applog
                    applog.report(where=f"sending {self.name}'s audio")
                    # surfaces on the Apps tab, which stops the capture and shows this
                    self.error = "Sending this program's sound failed. Switch Send on to try again."
                    return
            now = time.monotonic()
            if now >= next_alive:
                next_alive = now + 1.0
                if not is_running(self.pid):
                    self.ended = True
                    return


def _explain(e: ComError) -> str:
    if e.hr == AUDCLNT_E_DEVICE_INVALIDATED & 0xFFFFFFFF:
        return "The program's audio device went away. Switch Send on to try again."
    if e.hr == 0x88890008:
        return ("Windows won't hand this program's audio over in a format we can use. "
                "Try switching the program to another output device.")
    if e.hr == 0x80070057 or e.hr == 0x88890001:   # E_INVALIDARG / NOT_INITIALIZED
        return ("Windows refused to capture this program. Check it's still running, "
                "then switch Send on again.")
    if e.hr in (0x80070005, 0x88890010):   # E_ACCESSDENIED / AUDCLNT_E_DEVICE_IN_USE
        return ("Windows won't let this app capture that program's audio. If the program "
                "runs as administrator, run this app as administrator too.")
    ok, why = supported()
    if not ok:
        return why
    return f"Windows couldn't start the capture ({e}). Switch Send on to try again."
