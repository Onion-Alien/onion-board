"""Per-program audio capture: tap one running program's sound (Spotify, a browser, a
game, a call in another app) and push it into the engine so it goes out through
the send device like a sound, without touching what any other program plays.

Windows 11 and Windows 10 version 2004+ (build 19041) have this built into WASAPI
("process loopback", what Discord's and OBS's application-audio capture use). It is a
*copy* of the program's audio: the program keeps playing on your speakers as before.

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
import types
import typing
from collections.abc import Callable
from ctypes import (POINTER, addressof, byref, c_float, c_int, c_int64,
                    c_long, c_uint, c_ulong, c_void_p, c_wchar_p, cast, sizeof)
from dataclasses import dataclass, field
from typing import Any

if typing.TYPE_CHECKING:
    import numpy as np
else:
    try:
        import numpy as np
    except ImportError:   # the mic helper (soundboard/mic/michelper.py) ships without numpy:
        np = None         # it only uses mic_is_silent(), which never needs it

from soundboard.core import errors
from soundboard.i18n import _

# its parts, each building on the ones before; all they have is reached through
# this module too (appaudio.Com, appaudio.running, ...): see _Parts
from soundboard.audio import appcom, appmics, appprocs
from soundboard.audio.appcom import *  # noqa: F403
from soundboard.audio.appprocs import *  # noqa: F403
from soundboard.audio.appmics import *  # noqa: F403
from soundboard.audio.appcom import (
    ACTIVATION_PARAMS, AUDCLNT_BUFFERFLAGS_SILENT, AUDCLNT_E_DEVICE_INVALIDATED,
    AUDCLNT_E_UNSUPPORTED_FORMAT, AUDCLNT_SHAREMODE_SHARED,
    AUDCLNT_STREAMFLAGS_EVENTCALLBACK, AUDCLNT_STREAMFLAGS_LOOPBACK,
    AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK, CLSCTX_ALL, _co_init, Com, ComError,
    _device_name, E_CAPTURE, E_CONSOLE, E_NOINTERFACE, E_RENDER, _enumerator, GUID,
    IID_IAgileObject, IID_IAudioCaptureClient, IID_IAudioClient,
    IID_IAudioMeterInformation, IID_IAudioSessionControl2, IID_IAudioSessionManager2,
    IID_ICompletionHandler, IID_IUnknown, PROCESS_LOOPBACK_MODE_EXCLUDE_TREE,
    PROCESS_LOOPBACK_MODE_INCLUDE_TREE, PROPVARIANT, _render_devices, S_OK, to_stereo_f32,
    VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK, VT_BLOB, WAVE_FORMAT_IEEE_FLOAT,
    WAVE_FORMAT_PCM, WAVEFORMATEX, _win,
)
from soundboard.audio.appprocs import (
    file_description, forget_dead_pids, HELPER_EXES, is_running, PidTable, process_path,
    process_started, _process_table, root_pid, SYSTEM_EXES, window_titles,
)
if _win:
    from soundboard.audio.appcom import WINFUNCTYPE, _k32, _ole32, windll

log = logging.getLogger(__name__)

SR = 48000            # what the sink gets (the engine's storage rate)
MIN_BUILD = 19041     # Windows 10 2004: process loopback works there (OBS relies on it),
                      # though Microsoft only documents it from 20348, a Server build
GAP_S = 0.03          # no packets from the program this long: it's quiet, send silence
MAX_GAP_S = 0.2       # most silence handed over at once (about the engine's cushion)


def supported() -> tuple[bool, str]:
    """(can this machine capture a program's audio, why not)."""
    if not _win:
        return False, _("Capturing a program's audio needs Windows.")
    build = sys.getwindowsversion().build
    if build < MIN_BUILD:
        return False, _("Capturing a program's audio needs Windows 11, or Windows 10 "
                        "updated to version 2004 or newer (this is build {build}).",
                        build=build)
    return True, ""


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
    description: str = ""    # the .exe's own name for itself (file_description)

    @property
    def name(self) -> str:
        """Display name: the program's own ('VLC media player', as Windows' volume
        mixer shows it), else from its .exe: 'Spotify' from spotify.exe."""
        if self.description:
            return self.description
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


def list_apps(strict: bool = False, alive: dict[int, str] | None = None,
              meters: dict | None = None) -> list[App]:
    """Every program with a live audio session on any playback device, this
    process excluded and grouped by process tree. Safe from any thread. A failed
    listing is [] (or raises ComError with `strict`: [] would read as "nothing plays").
    `alive` is filled with every running process (pid -> exe name, lower case) from
    the process list the listing was made from, as running() would give, without
    walking every process a second time. `meters`: as in _list_apps."""
    if not _win:
        return []
    own = _co_init()
    try:
        return _list_apps(meters, alive=alive, titles=True)
    except ComError:
        if strict:
            raise
        log.debug("listing audio sessions failed", exc_info=True)
        return []
    finally:
        if own:
            _ole32.CoUninitialize()


def recording_apps(device: str, mine: bool = False) -> list[App]:
    """The programs recording from the recording device named `device` (who listens
    to the virtual cable's far end: Discord, a game, OBS), this process excluded
    unless `mine`. Safe from any thread."""
    if not _win or not device:
        return []
    own = _co_init()
    try:
        # one process at a time (PidTable): only the few recording are looked up
        return _list_apps(flow=E_CAPTURE, only=device, titles=False, table=PidTable(),
                          mine=mine)
    except ComError:
        log.debug("listing recording sessions failed", exc_info=True)
        return []
    finally:
        if own:
            _ole32.CoUninitialize()


def _list_apps(meters: dict | None = None, flow: int = E_RENDER,
               only: str | None = None, alive: dict[int, str] | None = None,
               titles: bool | None = None,
               table: PidTable | dict[int, tuple[int, str]] | None = None,
               mine: bool = False) -> list[App]:
    """With `meters`, also keeps each session's IAudioMeterInformation there
    (root pid -> [Com]) for the caller to read and release; window titles are then
    skipped unless `titles`. `flow` E_CAPTURE lists recording sessions instead,
    `only` on one device. `alive`: see list_apps. `table`: a PidTable instead of a
    snapshot of every process (not with `alive`, which needs them all). `mine`: this
    process's own sessions too."""
    me = 0 if mine else os.getpid()
    if table is None:
        table = _process_table()
        forget_dead_pids(table)
    if alive is not None:
        assert isinstance(table, dict), "alive needs the full snapshot"
        alive.update((pid, exe) for pid, (_, exe) in table.items())
    apps: dict[int, App] = {}
    with _enumerator() as en:
        devices = _render_devices(en, flow)
    try:
        for dev in devices:
            dname = _device_name(dev)
            if only is not None and dname != only:
                continue
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
    if titles is None:
        titles = meters is None
    names = window_titles() if apps and titles else {}
    for app in apps.values():
        pids = (app.pid, *sorted(app.session_pids))
        app.title = next((names[p] for p in pids if p in names), "")
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
        exe = table.get(pid.value, (0, ""))[1]
        path = (process_path(root, table.get(root, (0, ""))[1])   # a helper's host, not it
                or (process_path(pid.value, exe) if exe not in HELPER_EXES else ""))
        exe = os.path.basename(path) or table.get(root, (0, ""))[1] or f"pid {root}"
        app = apps[root] = App(root, exe, path, description=file_description(path))
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


Listed = Callable[[list[App] | None, dict[int, str] | None], None]


class PeakWatcher:
    """Live levels of every program, from Windows' own session meters, read
    ~20 times a second on a worker thread (`list_apps` is too slow to re-run that
    often: it walks processes and windows). The sessions are re-found every
    `rescan` seconds, or sooner when list_for() asks for the whole listing.
    `peak(pid)` takes the root pid, as in `App.pid`."""

    def __init__(self, interval: float = 0.05, rescan: float = 1.5):
        self.interval, self.rescan = interval, rescan
        self._peaks: dict[int, float] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._asks: list[Listed] = []        # list_for() callers waiting for a rescan
        self._asks_lock = threading.Lock()

    def peak(self, pid: int) -> float | None:
        """0..1, or None if the program has no session the watcher knows of yet."""
        return self._peaks.get(pid)

    def list_for(self, done: Listed) -> bool:
        """The Apps tab's list of programs, made by the watcher's next rescan (within
        `interval`): done(apps, alive) is called on the watcher's thread with what
        list_apps(alive=...) gives, apps None if it failed. The tab used to list the
        programs, walk every process again (running()) and have this watcher find the
        same sessions on its own: three walks every 1.5 s, now one.
        False while the watcher isn't running: list them yourself."""
        with self._asks_lock:
            if self._thread is None or self._stop.is_set():
                return False
            self._asks.append(done)
        return True

    def start(self):
        if not _win or (self._thread and self._thread.is_alive()):
            return
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(self._stop,),
                                        name="apppeaks", daemon=True)
        self._thread.start()

    def stop(self):
        with self._asks_lock:
            self._stop.set()
            self._thread = None
        self._peaks = {}

    def _take_asks(self) -> list[Listed]:
        with self._asks_lock:
            return self._take_asks_locked()

    def _take_asks_locked(self) -> list[Listed]:
        asks, self._asks = self._asks, []
        return asks

    def _run(self, stop: threading.Event):
        meters: dict[int, list[Com]] = {}
        own = _co_init()
        try:
            next_scan = 0.0
            peak = c_float()
            while not stop.is_set():
                asks = self._take_asks()
                if asks or time.monotonic() >= next_scan:
                    _release_meters(meters)
                    meters = {}
                    apps = alive = None
                    try:
                        if asks:   # the whole listing, window titles and all
                            alive = {}
                            apps = list_apps(strict=True, alive=alive, meters=meters)
                        else:
                            _list_apps(meters)
                    except ComError:
                        log.debug("finding session meters failed", exc_info=True)
                    finally:
                        _answer(asks, apps, alive)   # (None on any failure)
                    # asked every 1.5 s while the Apps tab shows: no rescans of its own
                    next_scan = time.monotonic() + self.rescan * (2 if asks else 1)
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
            with self._asks_lock:
                stop.set()   # this run takes no more asks: list_for says so from now on
                asks = self._take_asks_locked()
            _answer(asks, None, None)   # never leave the tab waiting for a list
            if own:
                _ole32.CoUninitialize()


def _answer(asks: list[Listed], apps: list[App] | None, alive: dict[int, str] | None):
    for done in asks:
        try:
            done(apps, alive)
        except Exception:  # noqa: BLE001 - one caller's bug mustn't stop the levels
            log.exception("handing over the program list failed")


def _release_meters(meters: dict):
    for ms in meters.values():
        for m in ms:
            m.release()


# --------------------------------------------------------------------------- capture

_QI_T: typing.Any = None
_REF_T: typing.Any = None
_DONE_T: typing.Any = None
if _win:
    _mmdev = None   # mmdevapi.dll, loaded on first capture (it's not on Windows 7)
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
        self._started: int | None = None   # process_started: a reused pid isn't ours
        self._thread = threading.Thread(target=self._run, name=f"appcapture-{pid}", daemon=True)

    # -- lifecycle
    def start(self, timeout: float = 6.0, wait: bool = True) -> bool:
        """With wait=False it returns once the thread is going: `ready` turns True
        when Windows has started the capture, or `error` says why it couldn't (opening
        it can take seconds, which mustn't freeze the window)."""
        if not _win:
            self.error = supported()[1]
            return False
        if not is_running(self.pid):   # Windows would happily "capture" a pid that's gone
            self.error = _("That program isn't running any more.")
            self.ended = True
            return False
        self._started = process_started(self.pid)
        self._thread.start()
        if not wait:
            return True
        if not self._ready.wait(timeout):
            self.error = _("Windows didn't answer in time. Switch Send on to try again.")
            self._stop.set()
            return False
        return self.error is None

    def stop(self, wait: bool = True):
        """With wait=False it only asks the thread to end: it can be inside Windows'
        capture request for seconds, which mustn't freeze the window. The sink gets
        nothing more either way, so a new capture of the same program can start at
        once; `join()` waits for the old thread later (on the way out)."""
        self._stop.set()
        if wait:
            self.join(3)

    def join(self, timeout: float = 3.0):
        if self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout)

    @property
    def running(self) -> bool:
        return self._thread.is_alive() and self.error is None and not self.ended

    @property
    def ready(self) -> bool:
        """Windows has started the capture (start(wait=False) returns before)."""
        return self._ready.is_set() and self.error is None

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
            self.error = errors.plain(e)
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
                raise TimeoutError(_("Windows didn't answer the capture request."))
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
        assert client is not None and fmt is not None   # the last try raises instead
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

    def _hand_over(self, x: np.ndarray) -> bool:
        if self._stop.is_set():   # stopped without waiting: the sink isn't ours any more
            return False
        self.frames += len(x)
        try:
            self.sink(x)
            return True
        except Exception:  # noqa: BLE001
            from soundboard.core import applog
            applog.report(where=f"sending {self.name}'s audio")
            # surfaces on the Apps tab, which stops the capture and shows this
            self.error = _("Sending this program's sound failed. "
                           "Switch Send on to try again.")
            return False

    def _loop(self, cap: Com, fmt: WAVEFORMATEX, is_float: bool, evt):
        align = fmt.nBlockAlign
        n, frames, flags, data = c_uint(), c_uint(), c_ulong(), c_void_p()
        next_alive = time.monotonic() + 1.0
        heard = time.monotonic()   # when the audio handed over so far ends, in real time
        while not self._stop.is_set():
            _k32.WaitForSingleObject(evt, 20)
            got = False
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
                got = True
                if not self._hand_over(x):
                    return
            now = time.monotonic()
            if got:
                heard = now
            elif now - heard > GAP_S:
                # a program with nothing to play sends no packets at all: hand over
                # the silence ourselves, or the engine's cushion for it runs dry, grows
                # (more delay), and stays grown
                if now - heard > MAX_GAP_S:   # stalled (sleep, a hang): don't catch up
                    heard = now - MAX_GAP_S
                x = np.zeros((int((now - heard) * SR), 2), np.float32)
                heard += len(x) / SR
                if len(x) and not self._hand_over(x):
                    return
            if now >= next_alive:
                next_alive = now + 1.0
                if not is_running(self.pid, self._started):
                    self.ended = True
                    return


def _explain(e: ComError) -> str:
    if e.hr == AUDCLNT_E_DEVICE_INVALIDATED & 0xFFFFFFFF:
        return _("The program's audio device went away. Switch Send on to try again.")
    if e.hr == 0x88890008:
        return _("Windows won't hand this program's audio over in a format we can use. "
                 "Try switching the program to another output device.")
    if e.hr == 0x80070057 or e.hr == 0x88890001:   # E_INVALIDARG / NOT_INITIALIZED
        return _("Windows refused to capture this program. Check it's still running, "
                 "then switch Send on again.")
    if e.hr in (0x80070005, 0x88890010):   # E_ACCESSDENIED / AUDCLNT_E_DEVICE_IN_USE
        return _("Windows won't let this app capture that program's audio. If the program "
                 "runs as administrator, run this app as administrator too.")
    ok, why = supported()
    if not ok:
        return why
    return _("Windows couldn't start the capture ({error}). Switch Send on to try again.",
             error=errors.plain(e))


# ---------------------------------------------------------------------- one module

# appaudio was one module, and the app, the tests and the scripts still use it as one:
# what a part has is read here (appaudio.<name>, the private names too), and a name set
# here (a test's monkeypatch) is set in every part that has the same thing, so it
# reaches the code that uses it wherever that code now lives.
_PARTS = (appcom, appprocs, appmics)
_UNSET = object()


def __getattr__(name: str) -> Any:
    for part in _PARTS:
        if name in vars(part):
            return vars(part)[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class _Parts(types.ModuleType):
    def __setattr__(self, name: str, value):
        old = getattr(self, name, _UNSET)
        if old is not _UNSET:
            for part in _PARTS:
                if vars(part).get(name, _UNSET) is old:
                    setattr(part, name, value)
        if name in vars(self) or not any(name in vars(part) for part in _PARTS):
            super().__setattr__(name, value)


sys.modules[__name__].__class__ = _Parts
