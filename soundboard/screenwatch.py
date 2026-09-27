"""The Triggers tab's back end: watch the screen for pictures you picked (a game's
"YOU DIED", a victory banner, a kill icon) and say when one appears.

Capture uses Windows' Desktop Duplication (DXGI, over ctypes: `DupGrabber`),
which also sees fullscreen games; where that isn't available it falls back to
plain GDI (`Grabber`), which sees borderless and windowed games but can come out
black for exclusive-fullscreen ones (`Watcher.black` says so). Either way the
monitor is sampled at about twice a working width of a few hundred pixels, then
turned grey and averaged down 2x2. Each picture is shrunk by the same factor and
found with normalised cross-correlation (an FFT for the correlation, running sums
for each window's brightness and contrast), so a match scores the same whatever
the game's brightness and nothing is downloaded or installed. Transparent parts of
a picture are left out of the comparison (`match(..., mask)`), so a cut-out icon
matches whatever is behind it. A 1080p screen at the default size costs a few
milliseconds per check.

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
import uuid
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


def match(screen: np.ndarray | Frame, tmpl: np.ndarray,
          mask: np.ndarray | None = None) -> tuple[float, tuple[int, int]]:
    """Best normalised cross-correlation of `tmpl` anywhere in `screen` (2-D float
    grey, or a Frame of it): (score in -1..1, (x, y) of its top-left corner). 0 when
    it can't match at all (bigger than the screen, or a flat picture). `mask` (the
    picture's shape, true = counts) leaves out its transparent parts."""
    f = screen if isinstance(screen, Frame) else Frame(screen)
    th, tw = tmpl.shape
    sh, sw = f.shape
    if th < 2 or tw < 2 or th > sh or tw > sw:
        return 0.0, (0, 0)
    if mask is not None and not mask.all():
        return _match_masked(f, tmpl, mask)
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


def _match_masked(f: Frame, tmpl: np.ndarray, mask: np.ndarray) -> tuple[float, tuple[int, int]]:
    """match() over the mask's pixels only: each window's brightness and contrast
    are taken under the mask too (two more correlations, as the mask isn't a box)."""
    m = mask.astype(np.float64)
    n = float(m.sum())
    if n < 4:
        return 0.0, (0, 0)
    t = (tmpl.astype(np.float64) - float((tmpl * m).sum()) / n) * m
    tnorm = math.sqrt(float((t * t).sum()))
    if tnorm < 1e-6:
        return 0.0, (0, 0)
    mk = m[::-1, ::-1].astype(np.float32)
    num = fftconvolve(f.s, t[::-1, ::-1].astype(np.float32), mode="valid")
    s1 = fftconvolve(f.s, mk, mode="valid").astype(np.float64)
    s2 = fftconvolve(f.s * f.s, mk, mode="valid").astype(np.float64)
    var = s2 - s1 * s1 / n
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


def _guid(text: str) -> ctypes.Array:
    """A COM interface id as the 16 bytes Windows expects."""
    return (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(text).bytes_le)


IID_IDXGIFactory1 = "770aae78-f26f-4dba-a829-253c83d1b387"
IID_IDXGIOutput1 = "00cddea8-939b-4b83-a340-a685226666cc"
IID_ID3D11Texture2D = "6f15aaf2-d208-4e89-9ab4-489535d34f9c"
DXGI_ERROR_NOT_FOUND = 0x887A0002
DXGI_ERROR_ACCESS_LOST = 0x887A0026
DXGI_ERROR_WAIT_TIMEOUT = 0x887A0027


def _hr(v: int) -> int:
    return v & 0xFFFFFFFF


class _COM:
    """A COM pointer called by vtable slot (the interfaces are only ever used here,
    so no type library is needed)."""

    def __init__(self):
        self.p = ctypes.c_void_p()

    def __bool__(self):
        return bool(self.p.value)

    def call(self, index: int, *args, restype=ctypes.c_long, argtypes=()):
        vtbl = ctypes.cast(self.p, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        fn = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtbl[index])
        return fn(self.p, *args)

    def query(self, iid: str) -> _COM:
        out = _COM()
        hr = self.call(0, ctypes.byref(_guid(iid)), ctypes.byref(out.p),
                       argtypes=(ctypes.c_void_p, ctypes.c_void_p))
        if hr < 0:
            raise OSError(f"QueryInterface failed (0x{_hr(hr):08X})")
        return out

    def release(self):
        if self.p.value:
            self.call(2, restype=ctypes.c_ulong)
            self.p = ctypes.c_void_p()


class _OUTPUT_DESC(ctypes.Structure):
    _fields_ = [("DeviceName", wintypes.WCHAR * 32), ("DesktopCoordinates", wintypes.RECT),
                ("AttachedToDesktop", wintypes.BOOL), ("Rotation", ctypes.c_uint),
                ("Monitor", wintypes.HMONITOR)]


class _TEXTURE2D_DESC(ctypes.Structure):
    _fields_ = [("Width", ctypes.c_uint), ("Height", ctypes.c_uint),
                ("MipLevels", ctypes.c_uint), ("ArraySize", ctypes.c_uint),
                ("Format", ctypes.c_uint), ("SampleCount", ctypes.c_uint),
                ("SampleQuality", ctypes.c_uint), ("Usage", ctypes.c_uint),
                ("BindFlags", ctypes.c_uint), ("CPUAccessFlags", ctypes.c_uint),
                ("MiscFlags", ctypes.c_uint)]


class _MAPPED(ctypes.Structure):
    _fields_ = [("pData", ctypes.c_void_p), ("RowPitch", ctypes.c_uint),
                ("DepthPitch", ctypes.c_uint)]


class DupGrabber:
    """Desktop Duplication (IDXGIOutputDuplication): the frames the graphics card
    shows, so fullscreen games are seen too, where GDI may only see black. Same
    interface as Grabber. Each frame is copied to a CPU-readable texture and sampled
    at twice (w, h), then averaged 2x2. An unchanged screen (no new frame) gives
    the last one again. Everything lives on the thread that made it."""

    # vtable slots (IUnknown 0-2, IDXGIObject 3-6, ID3D11DeviceChild 3-6)
    FACTORY_ENUM_ADAPTERS1 = 12
    ADAPTER_ENUM_OUTPUTS = 7
    OUTPUT_GET_DESC = 7
    OUTPUT1_DUPLICATE = 22
    DUP_ACQUIRE = 8
    DUP_RELEASE_FRAME = 14
    DEVICE_CREATE_TEXTURE2D = 5
    CTX_MAP, CTX_UNMAP, CTX_COPY_RESOURCE = 14, 15, 47
    B8G8R8A8 = 87
    USAGE_STAGING, CPU_ACCESS_READ, MAP_READ = 3, 0x20000, 1
    RETRY_S = 1.0             # how often a lost duplication is tried again

    def __init__(self, src: Monitor, w: int, h: int):
        self.src, self.w, self.h = src, w, h
        self.factor = 2 if 2 * w <= src.width and 2 * h <= src.height else 1
        self.device, self.ctx, self.output1 = _COM(), _COM(), _COM()
        self.dup, self.staging = _COM(), _COM()
        self.last: np.ndarray | None = None
        self._lost_at = 0.0
        try:
            self._open()
        except Exception:
            self.close()
            raise
        n = self.factor
        self.ys = ((np.arange(h * n) + 0.5) * src.height / (h * n)).astype(np.intp)
        self.xs = ((np.arange(w * n) + 0.5) * src.width / (w * n)).astype(np.intp)
        for _ in range(5):          # the first real frame follows soon after opening
            if self.grab(timeout_ms=100) is not None:
                break

    def _open(self):
        dxgi, d3d = ctypes.windll.dxgi, ctypes.windll.d3d11
        factory = _COM()
        hr = dxgi.CreateDXGIFactory1(ctypes.byref(_guid(IID_IDXGIFactory1)),
                                     ctypes.byref(factory.p))
        if hr < 0:
            raise OSError(f"CreateDXGIFactory1 failed (0x{_hr(hr):08X})")
        try:
            adapter, output = self._find_output(factory)
        finally:
            factory.release()
        try:
            d3d.D3D11CreateDevice.argtypes = [
                ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p,
                ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
            hr = d3d.D3D11CreateDevice(adapter.p, 0, None, 0, None, 0, 7,   # 7: SDK version
                                       ctypes.byref(self.device.p), None,
                                       ctypes.byref(self.ctx.p))
            if hr < 0:
                raise OSError(f"D3D11CreateDevice failed (0x{_hr(hr):08X})")
            self.output1 = output.query(IID_IDXGIOutput1)
        finally:
            adapter.release()
            output.release()
        self._duplicate()
        desc = _TEXTURE2D_DESC(self.src.width, self.src.height, 1, 1, self.B8G8R8A8, 1, 0,
                               self.USAGE_STAGING, 0, self.CPU_ACCESS_READ, 0)
        hr = self.device.call(self.DEVICE_CREATE_TEXTURE2D, ctypes.byref(desc), None,
                              ctypes.byref(self.staging.p),
                              argtypes=(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p))
        if hr < 0:
            raise OSError(f"CreateTexture2D failed (0x{_hr(hr):08X})")

    def _find_output(self, factory: _COM) -> tuple[_COM, _COM]:
        """The graphics card and output showing self.src (matched by position)."""
        s = self.src
        for i in range(16):
            adapter = _COM()
            hr = factory.call(self.FACTORY_ENUM_ADAPTERS1, i, ctypes.byref(adapter.p),
                              argtypes=(ctypes.c_uint, ctypes.c_void_p))
            if hr < 0:
                break
            for j in range(16):
                output = _COM()
                hr = adapter.call(self.ADAPTER_ENUM_OUTPUTS, j, ctypes.byref(output.p),
                                  argtypes=(ctypes.c_uint, ctypes.c_void_p))
                if hr < 0:
                    break
                d = _OUTPUT_DESC()
                output.call(self.OUTPUT_GET_DESC, ctypes.byref(d), argtypes=(ctypes.c_void_p,))
                r = d.DesktopCoordinates
                if ((r.left, r.top, r.right - r.left, r.bottom - r.top)
                        == (s.left, s.top, s.width, s.height) and d.Rotation in (0, 1)):
                    return adapter, output
                output.release()
            adapter.release()
        raise OSError("no graphics output shows that monitor unrotated")

    def _duplicate(self):
        self.dup.release()
        hr = self.output1.call(self.OUTPUT1_DUPLICATE, self.device.p, ctypes.byref(self.dup.p),
                               argtypes=(ctypes.c_void_p, ctypes.c_void_p))
        if hr < 0:
            raise OSError(f"DuplicateOutput failed (0x{_hr(hr):08X})")

    def grab(self, timeout_ms: int = 0) -> np.ndarray | None:
        if not self.dup:
            # lost (a display mode switch, the UAC / lock screen): retry now and then
            if time.monotonic() - self._lost_at < self.RETRY_S:
                return self.last
            self._lost_at = time.monotonic()
            try:
                self._duplicate()
            except OSError:
                return self.last
        info = (ctypes.c_ubyte * 64)()              # DXGI_OUTDUPL_FRAME_INFO (48 bytes)
        res = _COM()
        hr = self.dup.call(self.DUP_ACQUIRE, timeout_ms, ctypes.byref(info), ctypes.byref(res.p),
                           argtypes=(ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p))
        code = _hr(hr)
        if code == DXGI_ERROR_WAIT_TIMEOUT:
            return self.last                        # nothing new on screen
        if code == DXGI_ERROR_ACCESS_LOST:
            self.dup.release()
            self._lost_at = time.monotonic()
            return self.last
        if hr < 0:
            raise OSError(f"AcquireNextFrame failed (0x{code:08X})")
        # LastPresentTime 0: only the mouse moved, or the (blank) frame a new
        # duplication starts with. The picture is unchanged, so skip the copy.
        if int.from_bytes(bytes(info[:8]), "little", signed=True) == 0:
            res.release()
            self.dup.call(self.DUP_RELEASE_FRAME)
            return self.last
        try:
            tex = res.query(IID_ID3D11Texture2D)
            try:
                self.ctx.call(self.CTX_COPY_RESOURCE, self.staging.p, tex.p, restype=None,
                              argtypes=(ctypes.c_void_p, ctypes.c_void_p))
            finally:
                tex.release()
        finally:
            res.release()
            self.dup.call(self.DUP_RELEASE_FRAME)
        m = _MAPPED()
        hr = self.ctx.call(self.CTX_MAP, self.staging.p, 0, self.MAP_READ, 0, ctypes.byref(m),
                           argtypes=(ctypes.c_void_p, ctypes.c_uint, ctypes.c_int,
                                     ctypes.c_uint, ctypes.c_void_p))
        if hr < 0:
            raise OSError(f"Map failed (0x{_hr(hr):08X})")
        try:
            rows, pitch = self.src.height, m.RowPitch
            buf = (ctypes.c_uint8 * (rows * pitch)).from_address(m.pData)
            img = np.frombuffer(buf, np.uint8).reshape(rows, pitch)
            px = img[:, :self.src.width * 4].reshape(rows, self.src.width, 4)
            sample = px[self.ys[:, None], self.xs[None, :]]      # a copy, taken while mapped
        finally:
            self.ctx.call(self.CTX_UNMAP, self.staging.p, 0, restype=None,
                          argtypes=(ctypes.c_void_p, ctypes.c_uint))
        self.last = gray_2x(sample) if self.factor == 2 else to_gray(sample)
        return self.last

    def close(self):
        for c in (self.staging, self.dup, self.output1, self.ctx, self.device):
            try:
                c.release()
            except OSError:
                log.debug("releasing a capture object failed", exc_info=True)


def open_grabber(src: Monitor, w: int, h: int):
    """Desktop Duplication where it works, else GDI."""
    try:
        return DupGrabber(src, w, h)
    except (OSError, AttributeError) as e:
        log.info("desktop duplication unavailable (%s): capturing with GDI", e)
        return Grabber(src, w, h)


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
    mask: np.ndarray | None = None      # the picture's opaque part (None: all of it)


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
        scaled: dict[str, tuple] = {}
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
                    grab = (self._grabber or open_grabber)(
                        mon, max(1, round(mon.width * scale)), max(1, round(mon.height * scale)))
                    scaled = {i.id: (shrink(i.gray, scale),
                                     None if i.mask is None else shrink(i.mask, scale) > 0.99)
                              for i in items}
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

    def _check(self, gray: np.ndarray, items: list[Watched], scaled: dict[str, tuple]):
        self.black = float(gray.max()) < BLACK_LEVEL
        frame = None if self.black else Frame(gray)
        now = time.monotonic()
        for it in items:
            t = scaled.get(it.id)
            score = 0.0 if t is None or frame is None else match(frame, *t)[0]
            self.scores[it.id] = score
            if it.gate.update(score, now, it.threshold, it.cooldown):
                try:
                    self._on_fire(it.id)
                except Exception:  # noqa: BLE001
                    log.exception("trigger callback failed")
