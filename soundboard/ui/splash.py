"""The start-up splash: Bun hopping about in the middle of the screen, from the
moment the QApplication exists until the main window is up. Just Bun on the
desktop (no card, spinner or caption), his headphones in the saved theme's accent
(read straight from config.json; the rest of the settings load later).

A cold start (first launch after a reboot, files not yet cached) can spend several
seconds importing and building the window, all on the UI thread. On Windows the
splash therefore isn't a Qt window: a thread of its own draws each frame into a
QImage at the monitor's real resolution (QPainter on a QImage is fine off the UI
thread) and hands it to a native layered window, so Bun hops smoothly at 60 fps
however busy the UI thread is. Elsewhere (the offscreen platform the tests use)
it's a Qt widget that `pump()` repaints: `show()` hooks the import system so every
module loaded meanwhile pumps it, and MainWindow calls `pump()` between its slower
steps. Without a Qt splash on screen `pump()` does nothing, so it's safe to call
anywhere.
"""
from __future__ import annotations

import json
import logging
import math
import os
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QEventLoop, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QImage, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from soundboard import theme
from soundboard.bunny import draw_bunny

log = logging.getLogger(__name__)

CARD_W, CARD_H = 420, 330   # logical px; the native window is this times the screen's scale
BUN_W, BUN_H = 160, 192
HOP = 0.62       # seconds per hop
HOP_PX = 46      # how high he gets
ROAM_PX = 95     # how far he wanders either side of the middle
FRAME = 1 / 30   # seconds between repaints while pumping (the Qt fallback)
NATIVE_FPS = 60
# while it's up, Python hands the GIL over every 0.5 ms instead of every 5: each frame
# takes the GIL dozens of times, and a busy UI thread would otherwise hold it 5 ms each
SWITCH_S = 0.0005
# library.CONFIG_PATH, without importing library (numpy, soundfile...) this early
CONFIG = Path(os.environ.get("APPDATA", Path.home())) / "OnionBoard" / "config.json"

_splash: Splash | NativeSplash | None = None
_last = 0.0
_sprites: dict[tuple, QImage] = {}   # Bun drawn once per (ears, blink, scale)


def _sprite(ears: float, blink: float, scale: float) -> QImage:
    """Bun in this pose, drawn once at `scale` (device px per logical px) with room to
    spare for the stretch, so a frame is one image draw instead of hundreds of
    painter calls (the native splash shares the GIL with a busy UI thread)."""
    key = (round(ears), blink, scale)
    img = _sprites.get(key)
    if img is None:
        over = scale * 1.25
        img = QImage(round(BUN_W * over), round(BUN_H * over), QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        draw_bunny(p, QRectF(0, 0, img.width(), img.height()), blink=blink, ears=key[0])
        p.end()
        _sprites[key] = img
    return img


def paint_frame(p: QPainter, t: float, w: float, h: float, scale: float = 1.0):
    """One frame of Bun hopping, `t` seconds in, on a `w` x `h` (logical px) canvas
    that `p` maps onto `scale` device px per logical px."""
    u = (t % HOP) / HOP                     # 0..1 through this hop
    air = 4 * u * (1 - u)                   # 0 on the ground, 1 at the top
    land = max(0.0, 1 - u / 0.18)           # just landed: squash, ears flop
    wander = math.sin(t * 0.9)
    facing = 1 if math.cos(t * 0.9) >= 0 else -1   # the way he's heading
    stretch = 1 + 0.08 * air - 0.14 * land   # taller in the air, squat on landing
    foot_x = w / 2 + wander * ROAM_PX
    foot_y = h - 18
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    # a soft shadow on the ground, smaller while he's up
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(0, 0, 0, round(70 - 40 * air)))
    sw = BUN_W * 0.62 * (1 - 0.35 * air)
    p.drawEllipse(QRectF(foot_x - sw / 2, foot_y - 7, sw, 14))
    # Bun, squashed about his feet and mirrored to face where he's going
    p.save()
    p.translate(foot_x, foot_y - HOP_PX * air)
    p.scale(facing / stretch ** 0.5, stretch)
    blink = 1.0 if (t % 2.7) > 2.55 else 0.0
    p.drawImage(QRectF(-BUN_W / 2, -BUN_H, BUN_W, BUN_H),
                _sprite(14 * land - 6 * air, blink, scale))
    p.restore()


class Splash(QWidget):
    """The Qt splash, for platforms without the native one (the tests' offscreen)."""

    def __init__(self):
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)   # don't take focus from a game
        self.setWindowTitle("Onion Board")
        self.setFixedSize(CARD_W, CARD_H)
        self._t0 = time.monotonic()

    def paintEvent(self, ev):
        p = QPainter(self)
        paint_frame(p, time.monotonic() - self._t0, self.width(), self.height(),
                    self.devicePixelRatioF())
        p.end()


class NativeSplash:
    """The Windows splash: a click-through, never-activated layered window owned by
    a thread that draws and shows every frame itself (see the module docstring)."""

    def __init__(self):
        self._stop = threading.Event()
        self._up = threading.Event()
        self.ok = False   # the window came up and showed its first frame
        self._switch = sys.getswitchinterval()
        sys.setswitchinterval(min(SWITCH_S, self._switch))   # never coarser than the app's
        self._thread = threading.Thread(target=self._run, name="splash", daemon=True)
        self._thread.start()
        self._up.wait(1.0)   # the first frame is on screen (or it gave up)

    def isVisible(self) -> bool:
        return self.ok and self._thread.is_alive() and not self._stop.is_set()

    def close(self):
        self._stop.set()
        self._thread.join(1.0)
        sys.setswitchinterval(self._switch)

    def deleteLater(self):
        pass

    def _run(self):
        try:
            self._loop()
        except Exception:  # noqa: BLE001 - a splash must never stop the app starting
            log.debug("native splash failed", exc_info=True)
        finally:
            self._up.set()

    def _loop(self):
        import ctypes
        from ctypes import wintypes as wt

        user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
        H = ctypes.c_void_p
        user.CreateWindowExW.restype = H
        user.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
                                         ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                         ctypes.c_int, H, H, H, H]
        user.MonitorFromPoint.restype = H
        user.MonitorFromPoint.argtypes = [wt.POINT, wt.DWORD]
        user.GetMonitorInfoW.argtypes = [H, H]
        user.ShowWindow.argtypes = [H, ctypes.c_int]
        user.DestroyWindow.argtypes = [H]
        user.PeekMessageW.argtypes = [H, H, wt.UINT, wt.UINT, wt.UINT]
        user.TranslateMessage.argtypes = [H]
        user.DispatchMessageW.argtypes = [H]
        user.UpdateLayeredWindow.argtypes = [H, H, H, H, H, H, wt.DWORD, H, wt.DWORD]
        gdi.CreateCompatibleDC.restype = H
        gdi.CreateCompatibleDC.argtypes = [H]
        gdi.CreateDIBSection.restype = H
        gdi.CreateDIBSection.argtypes = [H, H, wt.UINT, ctypes.POINTER(H), H, wt.DWORD]
        gdi.SelectObject.restype = H
        gdi.SelectObject.argtypes = [H, H]
        gdi.DeleteObject.argtypes = [H]
        gdi.DeleteDC.argtypes = [H]

        # centred on the work area of the monitor the mouse is on, at that monitor's
        # scale (the process is per-monitor DPI aware by now: Qt set that up)
        pt = wt.POINT()
        user.GetCursorPos(ctypes.byref(pt))
        mon = user.MonitorFromPoint(pt, 2)   # MONITOR_DEFAULTTONEAREST

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT),
                        ("dwFlags", wt.DWORD)]

        mi = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
        user.GetMonitorInfoW(mon, ctypes.byref(mi))
        dpi_x, dpi_y = wt.UINT(96), wt.UINT(96)
        try:
            ctypes.windll.shcore.GetDpiForMonitor(H(mon), 0, ctypes.byref(dpi_x),
                                                  ctypes.byref(dpi_y))
        except Exception:  # noqa: BLE001 - no per-monitor DPI: 100 %
            pass
        k = dpi_x.value / 96
        w, h = round(CARD_W * k), round(CARD_H * k)
        wa = mi.rcWork
        x = (wa.left + wa.right) // 2 - w // 2
        y = (wa.top + wa.bottom) // 2 - h // 2

        # WS_EX_LAYERED | TOPMOST | TOOLWINDOW | NOACTIVATE | TRANSPARENT (click-through)
        ex = 0x80000 | 0x8 | 0x80 | 0x08000000 | 0x20
        hwnd = user.CreateWindowExW(ex, "Static", "Onion Board", 0x80000000,   # WS_POPUP
                                    x, y, w, h, None, None, None, None)
        if not hwnd:
            return

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                        ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                        ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                        ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]

        class BLENDFUNCTION(ctypes.Structure):
            _fields_ = [("op", ctypes.c_ubyte), ("flags", ctypes.c_ubyte),
                        ("alpha", ctypes.c_ubyte), ("fmt", ctypes.c_ubyte)]

        bih = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=w,
                               biHeight=-h, biPlanes=1, biBitCount=32)   # top-down BGRA
        dc = gdi.CreateCompatibleDC(None)
        bits = H()
        dib = gdi.CreateDIBSection(dc, ctypes.byref(bih), 0, ctypes.byref(bits), None, 0)
        old = gdi.SelectObject(dc, dib)
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)   # premultiplied BGRA, as GDI wants
        nbytes = w * h * 4
        size, src, dst = wt.SIZE(w, h), wt.POINT(0, 0), wt.POINT(x, y)
        blend = BLENDFUNCTION(0, 0, 255, 1)   # AC_SRC_OVER, per-pixel alpha
        msg = wt.MSG()
        t0 = time.monotonic()
        try:
            while not self._stop.is_set():
                start = time.monotonic()
                img.fill(Qt.transparent)
                p = QPainter(img)
                try:
                    p.scale(k, k)   # drawn at the monitor's real resolution, never stretched
                    paint_frame(p, start - t0, CARD_W, CARD_H, k)
                finally:
                    p.end()   # never leave img mid-paint: Qt aborts when it's freed
                ctypes.memmove(bits, bytes(img.constBits()), nbytes)
                user.UpdateLayeredWindow(hwnd, None, ctypes.byref(dst), ctypes.byref(size),
                                         dc, ctypes.byref(src), 0, ctypes.byref(blend), 2)
                if not self._up.is_set():
                    user.ShowWindow(hwnd, 4)   # SW_SHOWNOACTIVATE
                    self.ok = True
                    self._up.set()
                while user.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):   # PM_REMOVE
                    user.TranslateMessage(ctypes.byref(msg))
                    user.DispatchMessageW(ctypes.byref(msg))
                self._stop.wait(max(0.0, 1 / NATIVE_FPS - (time.monotonic() - start)))
        finally:
            user.DestroyWindow(hwnd)
            gdi.SelectObject(dc, old)
            gdi.DeleteObject(dib)
            gdi.DeleteDC(dc)


class _PumpOnImport:
    """A meta-path finder that finds nothing: it only pumps the splash each time a
    module is imported, which is most of what a cold start spends its time on."""

    @staticmethod
    def find_spec(name, path=None, target=None):
        pump()
        return None


def show() -> Splash | NativeSplash:
    """Put the splash up, centred on the screen the mouse is on."""
    global _splash
    try:
        theme.set_current(json.loads(CONFIG.read_text(encoding="utf-8-sig")).get("theme", ""))
    except Exception:  # noqa: BLE001 - first launch, or unreadable: the default theme
        pass
    if QGuiApplication.platformName() == "windows":
        _splash = NativeSplash()   # draws itself on its own thread: nothing to pump
        if _splash.ok:
            return _splash
        _splash.close()   # it couldn't: the Qt one instead
    _splash = Splash()
    screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
    if screen is not None:
        geo = screen.availableGeometry()
        _splash.move(geo.center().x() - CARD_W // 2, geo.center().y() - CARD_H // 2)
    _splash.show()
    _splash.repaint()
    QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
    sys.meta_path.insert(0, _PumpOnImport)
    return _splash


def pump():
    """Repaint the Qt splash if a frame's time has passed (UI thread only)."""
    global _last
    if not isinstance(_splash, Splash) or threading.current_thread() is not threading.main_thread():
        return
    now = time.monotonic()
    if now - _last < FRAME:
        return
    _last = now
    _splash.update()
    QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)


def close():
    """Take the splash down (the window is up, or start-up failed)."""
    global _splash
    try:
        sys.meta_path.remove(_PumpOnImport)
    except ValueError:
        pass
    if _splash is not None:
        _splash.close()
        _splash.deleteLater()
        _splash = None
    _sprites.clear()
