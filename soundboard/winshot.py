"""A small picture of a program's window, for the Apps tab's eye button
(soundboard.ui.appspanel).

`find_window` picks the program's main window (visible, not owned by another, with
a title; the biggest if it has several). `grab` copies it with PrintWindow and
PW_RENDERFULLCONTENT, so the window shows even while others cover it, then
shrinks it with GDI's halftone StretchBlt to at most `max_w` x `max_h`. Both talk
to other programs' windows, so they run on a worker thread, never the UI one.

What it can't show: a minimised window isn't drawn at all, and a few games
(exclusive fullscreen, some anti-cheat) come out black. `grab` says which.
"""
from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from dataclasses import dataclass

log = logging.getLogger(__name__)

PW_CLIENTONLY = 0x1
PW_RENDERFULLCONTENT = 0x2
GW_OWNER = 4
HALFTONE = 4
SRCCOPY = 0x00CC0020
DWMWA_CLOAKED = 14

# what a grab came back with
OK = "ok"
MINIMISED = "minimised"
GONE = "gone"         # the window closed, or the program has none
BLACK = "black"       # drawn, but all black: the program doesn't share its picture


@dataclass
class Shot:
    status: str
    width: int = 0
    height: int = 0
    data: bytes = b""     # BGRA rows, top down, width * 4 bytes each (status OK only)


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


_api = None


def supported() -> bool:
    return sys.platform == "win32"


def _win():
    """user32 / gdi32 / dwmapi with argument types set once (handles are pointers:
    without argtypes a 64-bit one can be cut down to 32 bits)."""
    global _api
    if _api is not None:
        return _api
    u = ctypes.WinDLL("user32")
    g = ctypes.WinDLL("gdi32")
    try:
        d = ctypes.WinDLL("dwmapi")
        d.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p,
                                            wintypes.DWORD]
    except OSError:
        d = None
    H = wintypes.HWND
    for f in (u.IsWindow, u.IsWindowVisible, u.IsIconic, u.GetWindowTextLengthW):
        f.argtypes = [H]
    u.GetWindow.argtypes = [H, wintypes.UINT]
    u.GetWindow.restype = H
    u.GetWindowThreadProcessId.argtypes = [H, ctypes.POINTER(wintypes.DWORD)]
    u.GetClientRect.argtypes = [H, ctypes.POINTER(wintypes.RECT)]
    u.PrintWindow.argtypes = [H, wintypes.HDC, wintypes.UINT]
    u.GetDC.argtypes = [H]
    u.GetDC.restype = wintypes.HDC
    u.ReleaseDC.argtypes = [H, wintypes.HDC]
    u.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
    g.CreateCompatibleDC.argtypes = [wintypes.HDC]
    g.CreateCompatibleDC.restype = wintypes.HDC
    g.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                   ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE,
                                   wintypes.DWORD]
    g.CreateDIBSection.restype = wintypes.HBITMAP
    g.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    g.SelectObject.restype = wintypes.HGDIOBJ
    g.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    g.DeleteDC.argtypes = [wintypes.HDC]
    g.SetStretchBltMode.argtypes = [wintypes.HDC, ctypes.c_int]
    g.SetBrushOrgEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
    g.StretchBlt.argtypes = ([wintypes.HDC] + [ctypes.c_int] * 4 + [wintypes.HDC]
                             + [ctypes.c_int] * 4 + [wintypes.DWORD])
    _api = (u, g, d)
    return _api


def _client_size(u, hwnd: int) -> tuple[int, int]:
    r = wintypes.RECT()
    if not u.GetClientRect(hwnd, ctypes.byref(r)):
        return 0, 0
    return r.right - r.left, r.bottom - r.top


def _cloaked(d, hwnd: int) -> bool:
    """A window Windows hides without un-showing it (another desktop, a suspended
    store app): visible by its flags, never on screen."""
    if d is None:
        return False
    v = wintypes.DWORD()
    return d.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(v),
                                   ctypes.sizeof(v)) == 0 and bool(v.value)


def find_window(pids) -> int:
    """The main window of any of `pids`: visible, not owned, titled, the biggest
    one (a minimised one counts as size 0, so a shown window wins). 0 if none."""
    if not supported() or not pids:
        return 0
    u, _g, d = _win()
    want = set(pids)
    best: list[tuple[int, int]] = []   # (area, hwnd)

    def visit(hwnd, _lp):
        try:
            if not u.IsWindowVisible(hwnd) or u.GetWindow(hwnd, GW_OWNER):
                return True
            pid = wintypes.DWORD()
            u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value not in want or u.GetWindowTextLengthW(hwnd) <= 0 or _cloaked(d, hwnd):
                return True
            w, h = (0, 0) if u.IsIconic(hwnd) else _client_size(u, hwnd)
            best.append((w * h, hwnd))
        except Exception:  # noqa: BLE001
            pass
        return True

    cb = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(visit)
    u.EnumWindows(cb, 0)
    return max(best)[1] if best else 0


class _Bitmap:
    """A top-down 32-bit DIB of (w, h) selected into a memory DC. GDI handles belong
    to the thread that made them: made, used and closed in one grab."""

    def __init__(self, g, screen, w: int, h: int):
        self._g = g
        self.w, self.h = w, h
        self.bmp = self._old = None
        self.dc = g.CreateCompatibleDC(screen)
        bmi = _BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.biWidth, bmi.biHeight = w, -h
        bmi.biPlanes, bmi.biBitCount = 1, 32
        self.bits = ctypes.c_void_p()
        if self.dc:
            self.bmp = g.CreateDIBSection(self.dc, ctypes.byref(bmi), 0,
                                          ctypes.byref(self.bits), None, 0)
        if not self.dc or not self.bmp or not self.bits.value:
            self.close()
            raise OSError("couldn't make a bitmap")
        self._old = g.SelectObject(self.dc, self.bmp)

    def read(self) -> bytes:
        assert self.bits.value is not None
        return ctypes.string_at(self.bits.value, self.w * self.h * 4)

    def close(self):
        g = self._g
        if self._old:
            g.SelectObject(self.dc, self._old)
            self._old = None
        if self.bmp:
            g.DeleteObject(self.bmp)
            self.bmp = None
        if self.dc:
            g.DeleteDC(self.dc)
            self.dc = None


def fit(w: int, h: int, max_w: int, max_h: int) -> tuple[int, int]:
    """(w, h) shrunk to fit in max_w x max_h, keeping its shape (never grown)."""
    s = min(max_w / w, max_h / h, 1.0)
    return max(1, round(w * s)), max(1, round(h * s))


def is_black(data: bytes, step: int = 97) -> bool:
    """Every sampled pixel (about one in `step`) all but black."""
    px = memoryview(data)
    for i in range(0, len(px) - 3, step * 4):
        if px[i] > 8 or px[i + 1] > 8 or px[i + 2] > 8:
            return False
    return True


def grab(hwnd: int, max_w: int, max_h: int) -> Shot:
    """`hwnd`'s inside (no title bar), shrunk to fit max_w x max_h."""
    if not supported() or not hwnd:
        return Shot(GONE)
    u, g, _d = _win()
    if not u.IsWindow(hwnd):
        return Shot(GONE)
    if u.IsIconic(hwnd):
        return Shot(MINIMISED)
    w, h = _client_size(u, hwnd)
    if w < 2 or h < 2:
        return Shot(MINIMISED)
    tw, th = fit(w, h, max_w, max_h)
    screen = u.GetDC(None)
    full = small = None
    try:
        full = _Bitmap(g, screen, w, h)
        small = _Bitmap(g, screen, tw, th)
        if not u.PrintWindow(hwnd, full.dc, PW_CLIENTONLY | PW_RENDERFULLCONTENT):
            return Shot(GONE if not u.IsWindow(hwnd) else BLACK)
        g.SetStretchBltMode(small.dc, HALFTONE)
        g.SetBrushOrgEx(small.dc, 0, 0, None)
        g.StretchBlt(small.dc, 0, 0, tw, th, full.dc, 0, 0, w, h, SRCCOPY)
        data = small.read()
    except OSError:
        log.debug("window picture failed", exc_info=True)
        return Shot(GONE)
    finally:
        for b in (small, full):
            if b is not None:
                b.close()
        u.ReleaseDC(None, screen)
    if is_black(data):
        return Shot(BLACK)
    return Shot(OK, tw, th, data)
