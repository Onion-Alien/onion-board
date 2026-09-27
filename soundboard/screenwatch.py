"""The Triggers tab's back end: watch the screen for pictures you picked (a game's
"YOU DIED", a victory banner, a kill icon) and say when one appears.

Capture is plain GDI over ctypes: the monitor is copied and shrunk to about
twice a working width of a few hundred pixels, then turned grey and averaged
down 2x2 (see Grabber). Each picture is shrunk by
the same factor and found with normalised cross-correlation (an FFT for the
correlation, running sums for each window's brightness and contrast), so a match
scores the same whatever the game's brightness and nothing is downloaded or
installed. A 1080p screen at the default size costs a few milliseconds per check.

GDI sees what the desktop compositor shows: borderless and windowed games, not
some exclusive-fullscreen ones, which come out black (`Watcher.black` says so).

`Gate` decides when a score is a new appearance: it fires once when a picture shows
up, then waits for it to go away before it can fire again (and never sooner than
the trigger's cooldown), so a death screen that stays up for five seconds plays
its sound once.
"""
from __future__ import annotations

import ctypes
import logging
import math
import sys
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass, field

import numpy as np
from scipy.signal import fftconvolve

log = logging.getLogger(__name__)

WORK_WIDTH = 480        # the screen is shrunk to about this wide before matching
MIN_SIDE = 12           # ...but never so far that a picture's short side drops below this
REARM_MARGIN = 0.08     # a match must fall this far below the threshold to count as gone
FLAT_STD = 2 / 255      # screen windows flatter than this never match (blank areas)
BLACK_LEVEL = 3 / 255   # a whole frame darker than this is a capture that can't see the game
INTERVALS_MS = (16, 33, 50, 100, 250, 500)
DEFAULT_INTERVAL_MS = 100


@dataclass
class Trigger:
    """One picture to watch for and what to play when it shows up (stored in
    Config.screen["triggers"])."""
    id: str
    name: str = "Trigger"
    image: str = ""           # the picture, a PNG inside library.APP_DIR / "triggers"
    sound: str = ""           # a sound id from the board
    delay: float = 0.0        # seconds between the match and the sound
    cooldown: float = 3.0     # seconds before this trigger can play again
    threshold: float = 0.80   # how alike (0..1) the screen must be to count as a match
    enabled: bool = True
    # a sound file picked here that's still being added to the board: its fingerprint,
    # so the trigger takes the new sound's id once the import finishes
    pending: str = ""

    @classmethod
    def from_raw(cls, d: dict) -> Trigger | None:
        if not isinstance(d, dict) or not isinstance(d.get("id"), str) or not d["id"]:
            return None
        t = cls(id=d["id"])
        for k, default in list(vars(t).items()):
            v = d.get(k, default)
            if isinstance(default, bool):
                ok = isinstance(v, bool)
            elif isinstance(default, float):
                ok = isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
            else:
                ok = isinstance(v, type(default))
            if ok:
                setattr(t, k, float(v) if isinstance(default, float) else v)
        t.delay = min(max(t.delay, 0.0), 60.0)
        t.cooldown = min(max(t.cooldown, 0.0), 600.0)
        t.threshold = min(max(t.threshold, 0.3), 0.99)
        return t


# --------------------------------------------------------------------------- matching

def to_gray(bgra: np.ndarray) -> np.ndarray:
    """(h, w, 4) BGRA / (h, w, 3) BGR uint8 -> (h, w) float32 luma in 0..1."""
    b, g, r = (bgra[..., i].astype(np.float32) for i in range(3))
    return (0.114 / 255) * b + (0.587 / 255) * g + (0.299 / 255) * r


class Frame:
    """A grey screen prepared for matching: its running sums (of brightness and of
    its square) are worked out once and shared by every picture checked against it."""

    def __init__(self, gray: np.ndarray):
        self.s = gray.astype(np.float32)
        h, w = gray.shape
        g = gray.astype(np.float64)
        self.ii = np.zeros((h + 1, w + 1))
        self.ii[1:, 1:] = g.cumsum(0).cumsum(1)
        self.ii2 = np.zeros((h + 1, w + 1))
        self.ii2[1:, 1:] = (g * g).cumsum(0).cumsum(1)

    @property
    def shape(self) -> tuple[int, int]:
        return self.s.shape

    def window_sums(self, ii: np.ndarray, th: int, tw: int) -> np.ndarray:
        return ii[th:, tw:] - ii[:-th, tw:] - ii[th:, :-tw] + ii[:-th, :-tw]


def match(screen: np.ndarray | Frame, tmpl: np.ndarray) -> tuple[float, tuple[int, int]]:
    """Best normalised cross-correlation of `tmpl` anywhere in `screen` (2-D float
    grey, or a Frame of it): (score in -1..1, (x, y) of its top-left corner). 0 when
    it can't match at all (bigger than the screen, or a flat picture)."""
    f = screen if isinstance(screen, Frame) else Frame(screen)
    th, tw = tmpl.shape
    sh, sw = f.shape
    if th < 2 or tw < 2 or th > sh or tw > sw:
        return 0.0, (0, 0)
    t = tmpl.astype(np.float64) - float(tmpl.mean())
    tnorm = math.sqrt(float((t * t).sum()))
    if tnorm < 1e-6:
        return 0.0, (0, 0)
    num = fftconvolve(f.s, t[::-1, ::-1].astype(np.float32), mode="valid")
    n = th * tw
    s1 = f.window_sums(f.ii, th, tw)
    var = f.window_sums(f.ii2, th, tw) - s1 * s1 / n     # n * the window's variance
    ok = var > n * FLAT_STD * FLAT_STD
    score = np.zeros(num.shape)
    np.divide(num, np.sqrt(np.where(ok, var, 1.0)) * tnorm, out=score, where=ok)
    i = int(np.argmax(score))
    y, x = divmod(i, score.shape[1])
    return float(min(score.flat[i], 1.0)), (x, y)


def work_scale(screen_w: int, tmpl_sides: list[int]) -> float:
    """How much to shrink the screen (and every picture) before matching: down to
    about WORK_WIDTH, but keeping the smallest picture at least MIN_SIDE px."""
    if screen_w <= 0:
        return 1.0
    scale = WORK_WIDTH / screen_w
    if tmpl_sides:
        scale = max(scale, MIN_SIDE / max(min(tmpl_sides), 1))
    return min(1.0, scale)


def shrink(gray: np.ndarray, scale: float) -> np.ndarray:
    """Area-average `gray` by `scale` (<= 1), the way the HALFTONE screen shrink does,
    so a picture and the screen it was cut from end up alike
    (the screen's shrink is close to an area average too: see Grabber)."""
    if scale >= 0.999:
        return gray.astype(np.float32)
    h, w = gray.shape
    nh, nw = max(1, round(h * scale)), max(1, round(w * scale))
    ys = np.linspace(0, h, nh + 1).astype(int)
    xs = np.linspace(0, w, nw + 1).astype(int)
    ii = np.zeros((h + 1, w + 1))
    ii[1:, 1:] = gray.astype(np.float64).cumsum(0).cumsum(1)
    tot = ii[ys[1:]][:, xs[1:]] - ii[ys[:-1]][:, xs[1:]] - ii[ys[1:]][:, xs[:-1]] + \
        ii[ys[:-1]][:, xs[:-1]]
    area = np.outer(np.diff(ys), np.diff(xs)).clip(min=1)
    return (tot / area).astype(np.float32)


@dataclass
class Gate:
    """Turns a stream of match scores into "it just appeared" moments."""
    armed: bool = True
    last: float = -math.inf

    def update(self, score: float, now: float, threshold: float, cooldown: float) -> bool:
        if score >= threshold:
            fire = self.armed and now - self.last >= cooldown
            self.armed = False      # showing: wait for it to go away first
            if fire:
                self.last = now
            return fire
        if score < threshold - REARM_MARGIN:
            self.armed = True
        return False


# --------------------------------------------------------------------------- capture

def supported() -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "Screen triggers only work on Windows."
    return True, ""


@dataclass
class Monitor:
    left: int
    top: int
    width: int
    height: int
    primary: bool = False

    @property
    def label(self) -> str:
        return f"{self.width}×{self.height}" + ("  (main)" if self.primary else "")


def monitors() -> list[Monitor]:
    """The monitors in physical pixels, the main one first."""
    if sys.platform != "win32":
        return []
    user32 = ctypes.windll.user32
    found: list[Monitor] = []

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                              ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def cb(hmon, _hdc, _rect, _lp):
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            r = mi.rcMonitor
            found.append(Monitor(r.left, r.top, r.right - r.left, r.bottom - r.top,
                                 bool(mi.dwFlags & 1)))
        return True

    try:
        user32.EnumDisplayMonitors(None, None, proc(cb), 0)
    except OSError:
        log.warning("listing monitors failed", exc_info=True)
    found.sort(key=lambda m: (not m.primary, m.left, m.top))
    return found


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


def gray_2x(bgra: np.ndarray) -> np.ndarray:
    """(2h, 2w, 4) BGRA uint8 -> (h, w) float32 luma in 0..1, each output pixel the
    average of a 2x2 block. Integer maths: a quarter the cost of float colour."""
    h, w = bgra.shape[0] // 2, bgra.shape[1] // 2
    x = bgra[:2 * h, :2 * w]
    y = (x[..., 0].astype(np.uint16) * 29 + x[..., 1].astype(np.uint16) * 150
         + x[..., 2].astype(np.uint16) * 77)                   # luma * 256
    y = y.reshape(h, 2, w, 2).sum((1, 3), dtype=np.uint32)
    return y.astype(np.float32) * (1 / (256 * 4 * 255))


class Grabber:
    """Copies one monitor, shrunk to (w, h), as grey (float32 0..1). The copy is
    taken at twice that size with GDI's plain pixel-dropping shrink (COLORONCOLOR:
    ~1 ms of CPU, where the smoother HALFTONE costs over 10) and each 2x2 block is
    then averaged, so thin text still shows. GDI handles belong to the thread that
    made them: create, use and close it on the watcher thread."""

    SRCCOPY = 0x00CC0020
    COLORONCOLOR = 3

    def __init__(self, src: Monitor, w: int, h: int):
        self.src, self.w, self.h = src, w, h
        self.factor = 2 if 2 * w <= src.width and 2 * h <= src.height else 1
        cw, ch = w * self.factor, h * self.factor
        self.cw, self.ch = cw, ch
        self.screen_dc = self.dc = self.bmp = self._old = None
        u, g = ctypes.windll.user32, ctypes.windll.gdi32
        self._u, self._g = u, g
        u.GetDC.restype = wintypes.HDC
        u.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        g.CreateCompatibleDC.restype = wintypes.HDC
        g.CreateCompatibleDC.argtypes = [wintypes.HDC]
        g.CreateDIBSection.restype = wintypes.HBITMAP
        g.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                       ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE,
                                       wintypes.DWORD]
        g.SelectObject.restype = wintypes.HGDIOBJ
        g.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        g.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        g.DeleteDC.argtypes = [wintypes.HDC]
        g.SetStretchBltMode.argtypes = [wintypes.HDC, ctypes.c_int]
        g.StretchBlt.argtypes = [wintypes.HDC] + [ctypes.c_int] * 4 + [wintypes.HDC] + \
            [ctypes.c_int] * 4 + [wintypes.DWORD]
        self.screen_dc = u.GetDC(None)
        self.dc = g.CreateCompatibleDC(self.screen_dc)
        bmi = _BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.biWidth, bmi.biHeight = cw, -ch        # top-down rows
        bmi.biPlanes, bmi.biBitCount = 1, 32
        bits = ctypes.c_void_p()
        if self.dc:
            self.bmp = g.CreateDIBSection(self.dc, ctypes.byref(bmi), 0, ctypes.byref(bits),
                                          None, 0)
        if not self.dc or not self.bmp or not bits.value:
            self.close()
            raise OSError("couldn't set up screen capture")
        self._old = g.SelectObject(self.dc, self.bmp)
        g.SetStretchBltMode(self.dc, self.COLORONCOLOR)
        buf = (ctypes.c_uint8 * (cw * ch * 4)).from_address(bits.value)
        self.pixels = np.frombuffer(buf, np.uint8).reshape(ch, cw, 4)

    def grab(self) -> np.ndarray | None:
        s = self.src
        if not self._g.StretchBlt(self.dc, 0, 0, self.cw, self.ch, self.screen_dc,
                                  s.left, s.top, s.width, s.height, self.SRCCOPY):
            return None
        return gray_2x(self.pixels) if self.factor == 2 else to_gray(self.pixels)

    def close(self):
        g, u = self._g, self._u
        if self._old:
            g.SelectObject(self.dc, self._old)
            self._old = None
        if self.bmp:
            g.DeleteObject(self.bmp)
            self.bmp = None
        if self.dc:
            g.DeleteDC(self.dc)
            self.dc = None
        if self.screen_dc:
            u.ReleaseDC(None, self.screen_dc)
            self.screen_dc = None


# --------------------------------------------------------------------------- watcher

@dataclass
class Watched:
    """A trigger as the watcher thread sees it: its picture (full size, grey) and
    the numbers it's judged by."""
    id: str
    gray: np.ndarray
    threshold: float
    cooldown: float
    gate: Gate = field(default_factory=Gate)


class Watcher:
    """The watching thread. `on_fire(trigger_id)` is called from that thread when a
    picture appears; `scores` holds each trigger's latest match for the UI to show."""

    def __init__(self, on_fire, grabber=None):
        self._on_fire = on_fire
        self._grabber = grabber
        self._lock = threading.Lock()
        self._items: dict[str, Watched] = {}
        self._changed = True              # pictures / monitor changed: rescale
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.interval = DEFAULT_INTERVAL_MS / 1000
        self.monitor = 0
        self.scores: dict[str, float] = {}
        self.black = False                # the capture only sees black
        self.error = ""
        self.check_ms = 0.0               # how long the last check took

    # set from the UI thread
    def set_items(self, items: list[Watched]):
        with self._lock:
            old = self._items
            for it in items:              # keep a trigger's gate across edits
                if it.id in old:
                    it.gate = old[it.id].gate
            self._items = {it.id: it for it in items}
            self._changed = True
        self.scores = {k: v for k, v in self.scores.items() if k in self._items}

    def set_monitor(self, index: int):
        with self._lock:
            self.monitor = index
            self._changed = True

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.running:
            return
        self._stop.clear()
        self.error = ""
        self._thread = threading.Thread(target=self._run, name="screenwatch", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        t, self._thread = self._thread, None
        if t is not None and t is not threading.current_thread():
            t.join(2.0)
        self.scores = {}
        self.black = False

    # the thread
    def _run(self):
        grab: Grabber | None = None
        scaled: dict[str, np.ndarray] = {}
        try:
            while not self._stop.is_set():
                t0 = time.perf_counter()
                with self._lock:
                    items = list(self._items.values())
                    changed, self._changed = self._changed, False
                    mon_index = self.monitor
                if changed:
                    if grab is not None:
                        grab.close()
                        grab = None
                    mons = monitors()
                    if not mons:
                        raise OSError("no monitor found")
                    mon = mons[mon_index] if 0 <= mon_index < len(mons) else mons[0]
                    scale = work_scale(mon.width, [min(i.gray.shape) for i in items])
                    grab = (self._grabber or Grabber)(
                        mon, max(1, round(mon.width * scale)), max(1, round(mon.height * scale)))
                    scaled = {i.id: shrink(i.gray, scale) for i in items}
                if items:
                    gray = grab.grab()
                    if gray is not None:
                        self._check(gray, items, scaled)
                self.check_ms = (time.perf_counter() - t0) * 1000
                self._stop.wait(max(0.001, self.interval - (time.perf_counter() - t0)))
        except Exception as e:  # noqa: BLE001 - say so in the tab instead of dying quietly
            log.exception("screen watching stopped")
            self.error = str(e) or type(e).__name__
        finally:
            if grab is not None:
                grab.close()

    def _check(self, gray: np.ndarray, items: list[Watched], scaled: dict[str, np.ndarray]):
        self.black = float(gray.max()) < BLACK_LEVEL
        frame = None if self.black else Frame(gray)
        now = time.monotonic()
        for it in items:
            t = scaled.get(it.id)
            score = 0.0 if t is None or frame is None else match(frame, t)[0]
            self.scores[it.id] = score
            if it.gate.update(score, now, it.threshold, it.cooldown):
                try:
                    self._on_fire(it.id)
                except Exception:  # noqa: BLE001
                    log.exception("trigger callback failed")
