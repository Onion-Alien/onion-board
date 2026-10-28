"""Clean mic's Strong: DeepFilterNet, an optional download.

DeepFilterNet (MIT or Apache-2.0, licenses/DeepFilterNet-MIT.txt) takes out nearly
everything but a voice, 48 kHz, 10 ms at a time. Its Windows build is upstream's LADSPA
plugin DLL (~50 MB, the model inside it), so it isn't in the app or its installer:
`download()` fetches that one pinned file from DeepFilterNet's own GitHub release and
keeps it only if its SHA-256 matches, into %APPDATA%\\OnionBoard\\models\\deepfilter.

The plugin runs the model on a worker thread of its own, and its `run()` waits (sleeps)
until that thread has the block ready. It also ends the whole process when it falls
too far behind (it panics). So the audio thread never calls it: `Stream` hands the mic
to a thread of ours that does, and takes back what's ready, and that thread stops
calling it long before the plugin would give up (`_Plugin.run`). One plugin is made
per use ("live", "clip") and kept for the run: closing one leaves its worker behind.
Windows' 1 ms timer is asked for while one runs (the plugin's waits are 2 ms; at the
default 15.6 ms it fell behind).
"""
from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from pathlib import Path

import numpy as np

from soundboard.core import updates
from soundboard.i18n import _
from soundboard.sounds import library

log = logging.getLogger(__name__)

VERSION = "0.5.6"
TRUSTED = ("https://github.com/Rikorose/DeepFilterNet/releases/download/",)
URL = (f"{TRUSTED[0]}v{VERSION}/"
       f"deep_filter_ladspa-{VERSION}-x86_64-pc-windows-msvc.dll")
SHA256 = "f97e34275eb884b6076a96d261683d2a43c6b2d97ddf9e346bc06f7c8057eb04"
SIZE = 50671104
MAX_SIZE = 64 << 20
NAME = "deep_filter.dll"
FEATURE = "addons"   # its switch in Settings > Privacy & security, as other add-ons'

RATE = 48000
FRAME = 480          # its frame: 10 ms at 48 kHz
DELAY = 960          # its output trails its input by two frames (measured: 20 ms)
PRIME = 2 * FRAME    # Stream: silence the output starts with, for our thread's slack
# the plugin's ports after Audio In / Out: attenuation limit (100 dB: no limit), min
# processing threshold, max ERB / DF thresholds, min buffer frames, post-filter beta.
# Its thresholds skip the work on frames that are only noise or already clean voice:
# a third less CPU than its defaults (-15, 35, 35), the same cleaning (measured)
CONTROLS = (100.0, -10.0, 30.0, 20.0, 0.0, 0.0)
GIVE_UP = 40         # late runs before we stop (the plugin panics at ~100)
STALL_S = 0.5        # Stream: this long with nothing back and it has stopped
START_S = 10.0       # ...or this long to start


def folder() -> Path:
    return library.APP_DIR / "models" / "deepfilter"


def path() -> Path:
    return folder() / NAME


def downloaded() -> bool:
    """Strong's download is on this PC (and wasn't removed this run)."""
    return path().is_file()


def download(progress: Callable[[int, int], object] | None = None,
             cancelled: Callable[[], bool] | None = None) -> Path:
    """Fetch the DLL (updates.fetch: HTTPS from DeepFilterNet's release only, size
    capped, SHA-256 checked; progress / cancel / Offline as other downloads). Raises
    updates.UpdateError with a message for the user. Call off the UI thread."""
    _sweep()
    return updates.fetch(URL, SHA256, path(), TRUSTED, MAX_SIZE, "model", SIZE,
                         progress, cancelled, FEATURE)


def remove() -> None:
    """Delete the download. Loaded this run, Windows keeps the file open: it's moved
    aside and deleted on the next download. Raises OSError."""
    p = path()
    if not p.exists():
        return
    try:
        p.unlink()
    except PermissionError:
        p.rename(p.with_name(f"{NAME}.old-{uuid.uuid4().hex[:8]}"))


def _sweep():
    """Delete what remove() had to leave behind."""
    for old in folder().glob(f"{NAME}.old-*") if folder().is_dir() else ():
        try:
            old.unlink()
        except OSError:
            pass


def friendly(e: Exception) -> str:
    """A failed download, as a sentence for the card."""
    if isinstance(e, updates.UpdateError):
        text = str(e)
    elif isinstance(e, OSError):
        text = _("couldn't reach GitHub. Check your internet connection")
    else:
        text = str(e) or type(e).__name__
    return text[:1].upper() + text[1:]


# ---------------------------------------------------------------- the plugin
_ul = ctypes.c_ulong
_fp = ctypes.POINTER(ctypes.c_float)


class _Descriptor(ctypes.Structure):
    _fields_ = [("UniqueID", _ul), ("Label", ctypes.c_char_p), ("Properties", ctypes.c_int),
                ("Name", ctypes.c_char_p), ("Maker", ctypes.c_char_p),
                ("Copyright", ctypes.c_char_p), ("PortCount", _ul),
                ("PortDescriptors", ctypes.c_void_p), ("PortNames", ctypes.c_void_p),
                ("PortRangeHints", ctypes.c_void_p), ("ImplementationData", ctypes.c_void_p),
                ("instantiate", ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, _ul)),
                ("connect_port", ctypes.CFUNCTYPE(None, ctypes.c_void_p, _ul, _fp)),
                ("activate", ctypes.CFUNCTYPE(None, ctypes.c_void_p)),
                ("run", ctypes.CFUNCTYPE(None, ctypes.c_void_p, _ul)),
                ("run_adding", ctypes.c_void_p), ("set_run_adding_gain", ctypes.c_void_p),
                ("deactivate", ctypes.CFUNCTYPE(None, ctypes.c_void_p)),
                ("cleanup", ctypes.CFUNCTYPE(None, ctypes.c_void_p))]


_lock = threading.Lock()
_plugins: dict[str, _Plugin] = {}
_lib: ctypes.CDLL | None = None
_timer_users = 0


def _fine_timer(on: bool):
    """Windows' 1 ms timer while a plugin runs (counted)."""
    global _timer_users
    if sys.platform != "win32":
        return
    with _lock:
        _timer_users += 1 if on else -1
        first, last = on and _timer_users == 1, not on and _timer_users == 0
    try:
        if first:
            ctypes.windll.winmm.timeBeginPeriod(1)
        elif last:
            ctypes.windll.winmm.timeEndPeriod(1)
    except (OSError, AttributeError):
        pass


class _Plugin:
    """One DeepFilterNet (mono) at 48 kHz. `run` is called by one thread at a time
    (`lock`). `broken` says why it can't be used any more, for good."""

    def __init__(self):
        global _lib
        p = path()
        if not p.is_file():
            raise RuntimeError(_("Strong isn't downloaded"))
        if _lib is None:
            _lib = ctypes.CDLL(str(p))
            _lib.ladspa_descriptor.restype = ctypes.POINTER(_Descriptor)
            _lib.ladspa_descriptor.argtypes = [_ul]
        ptr = _lib.ladspa_descriptor(0)
        if not ptr or ptr.contents.Label != b"deep_filter_mono":
            raise RuntimeError("not DeepFilterNet's plugin")
        d = self._d = ptr.contents
        self._h = d.instantiate(ctypes.byref(d), RATE)
        if not self._h:
            raise RuntimeError("DeepFilterNet didn't start")
        self._in = np.zeros(FRAME, np.float32)
        self._out = np.zeros(FRAME, np.float32)
        self._ctl = [np.array([v], np.float32) for v in CONTROLS]
        for i, a in enumerate([self._in, self._out, *self._ctl]):
            d.connect_port(self._h, i, a.ctypes.data_as(_fp))
        d.activate(self._h)
        self.lock = threading.Lock()
        self.broken = ""
        self._late = 0    # as the plugin counts its late runs (each adds a frame of delay)
        self._calm = 0

    def delay(self) -> int:
        """Samples its output trails its input by, now."""
        return DELAY + self._late * FRAME

    def run(self, frame: np.ndarray) -> np.ndarray | None:
        """One frame cleaned (a frame behind: the first answers are silence), or None
        once it's too slow to go on (`broken`)."""
        if self.broken:
            return None
        self._in[:] = frame
        t = time.perf_counter()
        self._d.run(self._h, FRAME)
        took = (time.perf_counter() - t) * RATE / FRAME   # of the frame's own length
        # the plugin's own bookkeeping, mirrored: a run as long as its frame adds a
        # frame of delay, 1000 quick ones in a row take one back, and at a second of
        # delay it ends the process. We stop well before. (It can also drop below its
        # first frame of delay; not counted here, so ours is never under its count.)
        if took >= 1.0:
            self._late += 1
            self._calm = 0
            if self._late >= GIVE_UP:
                self.broken = _("it's too slow on this PC")
                log.warning("DeepFilterNet: %d late frames, stopped", self._late)
                return None
        else:
            self._calm += 1
            if self._calm > 1000 and took < 0.5 and self._late > 0:
                self._late -= 1
                self._calm = 0
        return self._out.copy()


def plugin(use: str) -> _Plugin:
    """The plugin for `use` ("live", "clip"), made the first time (~0.4 s). Raises
    RuntimeError (or OSError when the DLL won't load)."""
    with _lock:
        p = _plugins.get(use)
    if p is None:
        p = _Plugin()
        with _lock:
            p = _plugins.setdefault(use, p)
    if p.broken:
        raise RuntimeError(p.broken)
    return p


class Stream:
    """Strong cleaning of a 48 kHz mic. `feed(x)` (the audio thread, never waits)
    gives back as many samples, cleaned, `latency()` late; None while it starts (the
    caller cleans with RNNoise meanwhile). `error` is set once it has stopped for
    good (it didn't load, it's too slow, it stalled): the caller falls back."""

    def __init__(self):
        self.ready = False
        self.error = ""
        self._todo: deque[np.ndarray] = deque()   # mic in, for our thread
        self._done: deque[np.ndarray] = deque()   # cleaned frames back
        self._have = np.zeros(PRIME, np.float32)  # cleaned, not given out yet
        self._late = 0      # silence given out when it fell short, for latency()
        self._short_s = 0.0
        self._wake = threading.Event()
        self._plugin: _Plugin | None = None
        self._stop = False
        self._started = time.monotonic()
        threading.Thread(target=self._work, daemon=True, name="clean-mic-strong").start()

    def latency(self) -> float:
        p = self._plugin
        return ((p.delay() if p is not None else DELAY) + PRIME + self._late) / RATE

    def feed(self, x: np.ndarray) -> np.ndarray | None:
        if self.error:
            return None
        if not self.ready:
            if time.monotonic() - self._started > START_S:
                self.error = _("it didn't start")
            return None
        self._todo.append(x)
        self._wake.set()
        n = len(x)
        done = self._done
        got = [self._have] if len(self._have) else []
        size = len(self._have)
        while size < n and done:
            f = done.popleft()
            got.append(f)
            size += len(f)
        have = np.concatenate(got) if len(got) > 1 else (got[0] if got else np.zeros(0, np.float32))
        if size >= n:
            self._have = have[n:]
            self._short_s = 0.0
            return have[:n]
        # short: what there is, after silence (that much later from now on)
        self._short_s += (n - size) / RATE
        if self._short_s > STALL_S:
            self.error = _("it stopped answering")
        self._late += n - size
        self._have = np.zeros(0, np.float32)
        return np.concatenate([np.zeros(n - size, np.float32), have])

    def _work(self):
        _fine_timer(True)
        try:
            try:
                p = plugin("live")
            except Exception as ex:  # noqa: BLE001 - said on the card, Normal cleans
                self.error = str(ex)
                log.warning("Clean mic Strong didn't start: %s", ex)
                return
            with p.lock:
                p.run(np.zeros(FRAME, np.float32))   # what's left from an earlier use
                self._plugin = p
                self.ready = True
                pending = np.zeros(0, np.float32)
                while not self._stop:
                    self._wake.wait(0.05)
                    self._wake.clear()
                    got = [pending]
                    while self._todo:
                        got.append(self._todo.popleft())
                    pending = np.concatenate(got) if len(got) > 1 else pending
                    i = 0
                    while len(pending) - i >= FRAME and not self._stop:
                        y = p.run(pending[i:i + FRAME])
                        if y is None:
                            self.error = p.broken
                            return
                        self._done.append(y)
                        i += FRAME
                    pending = pending[i:]
        finally:
            _fine_timer(False)

    def close(self):
        self._stop = True
        self._wake.set()


def clean_clip(m: np.ndarray) -> np.ndarray:
    """A whole 48 kHz recording cleaned, lined up with it and the same length (Hear
    the difference's After). Off the UI thread; about a third of the clip's length
    (each frame is given a few ms, so the plugin never runs late). Raises
    RuntimeError."""
    p = plugin("clip")
    n = len(m)
    x = np.concatenate([np.asarray(m, np.float32), np.zeros(DELAY + 4 * FRAME, np.float32)])
    x = np.concatenate([x, np.zeros(-len(x) % FRAME, np.float32)])
    out = np.empty(len(x), np.float32)
    _fine_timer(True)
    try:
        with p.lock:
            p.run(np.zeros(FRAME, np.float32))
            lag = p.delay()
            for i in range(0, len(x), FRAME):
                y = p.run(x[i:i + FRAME])
                if y is None:
                    raise RuntimeError(p.broken)
                out[i:i + FRAME] = y
                time.sleep(0.003)
    finally:
        _fine_timer(False)
    return out[lag:lag + n]

