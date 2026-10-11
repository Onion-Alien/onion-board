"""A small start-up panel: a steady Bun, the app name and three gently pulsing dots.
The theme is read straight from config.json; the rest of the settings load later.

A cold start (first launch after a reboot, files not yet cached) can spend several
seconds importing and building the window, all on the UI thread. On Windows the
splash therefore isn't a Qt window: a thread of its own draws each frame into a
QImage at the monitor's real resolution (QPainter on a QImage is fine off the UI
thread) and hands it to a native layered window, so the dots keep moving
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

from PySide6.QtCore import QEventLoop, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QImage, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from soundboard import theme
from soundboard.bunny import draw_bunny
from soundboard.i18n import _

log = logging.getLogger(__name__)

CARD_W, CARD_H = 240, 248   # logical px, including 8 px around the rounded panel
BUN_W, BUN_H = 80, 96
PULSE_S = 1.8
FRAME = 1 / 30   # seconds between repaints while pumping (the Qt fallback)
NATIVE_FPS = 30
# while it's up, Python hands the GIL over every 0.5 ms instead of every 5: each frame
# takes the GIL dozens of times, and a busy UI thread would otherwise hold it 5 ms each
SWITCH_S = 0.0005
# library.CONFIG_PATH, without importing library (numpy, soundfile...) this early
CONFIG = Path(os.environ.get("APPDATA", Path.home())) / "OnionBoard" / "config.json"

_splash: Splash | NativeSplash | None = None
_last = 0.0
_surfaces: dict[tuple, QImage] = {}   # only the dots need drawing on each frame
_animate = True


def _surface(w: float, h: float, scale: float) -> QImage:
    """Cache the stationary panel at the monitor's resolution, including its text."""
    status = _("Starting…")
    family = theme.T.get("font", theme.FONT)
    key = (w, h, scale, tuple(theme.T.items()), family, status)
    img = _surfaces.get(key)
    if img is None:
        img = QImage(round(w * scale), round(h * scale), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        try:
            p.scale(scale, scale)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.T["panel"]))
            p.drawRoundedRect(QRectF(8, 8, w - 16, h - 16), 16, 16)
            draw_bunny(p, QRectF((w - BUN_W) / 2, 30, BUN_W, BUN_H))
            font = QFont(family)
            font.setPixelSize(18)
            font.setWeight(QFont.Weight.DemiBold)
            p.setFont(font)
            p.setPen(QColor(theme.T["text_hi"]))
            p.drawText(QRectF(20, 142, w - 40, 26), Qt.AlignmentFlag.AlignCenter, "Onion Board")
            font.setPixelSize(12)
            font.setWeight(QFont.Weight.Normal)
            p.setFont(font)
            p.setPen(QColor(theme.T["muted"]))
            p.drawText(QRectF(20, 171, w - 40, 22), Qt.AlignmentFlag.AlignCenter, status)
        finally:
            p.end()
        _surfaces[key] = img
    return img


def paint_frame(p: QPainter, t: float, w: float, h: float, scale: float = 1.0):
    """A stationary panel; only the three dots change opacity, never size or position."""
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.drawImage(QRectF(0, 0, w, h), _surface(w, h, scale))
    p.setPen(Qt.PenStyle.NoPen)
    accent = QColor(theme.T["accent"])
    for i in range(3):
        pulse = (1 - math.cos(2 * math.pi * (t - i * 0.2) / PULSE_S)) / 2
        c = QColor(accent)
        c.setAlphaF(0.3 + 0.7 * pulse if _animate else 1.0)
        p.setBrush(c)
        p.drawEllipse(QPointF(w / 2 + (i - 1) * 11, h - 35), 2.5, 2.5)


def _animations_enabled() -> bool:
    """Read Windows' Animation effects preference without changing any settings."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        try:
            enabled = wintypes.BOOL(1)
            if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0):
                return bool(enabled.value)
        except (AttributeError, OSError):
            pass
    return True


class Splash(QWidget):
    """The Qt splash, for platforms without the native one (the tests' offscreen)."""

    def __init__(self):
        super().__init__(None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # don't take focus from a game
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
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
        # premultiplied BGRA, as GDI wants
        img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        nbytes = w * h * 4
        size, src, dst = wt.SIZE(w, h), wt.POINT(0, 0), wt.POINT(x, y)
        blend = BLENDFUNCTION(0, 0, 255, 1)   # AC_SRC_OVER, per-pixel alpha
        msg = wt.MSG()
        t0 = time.monotonic()
        try:
            while not self._stop.is_set():
                start = time.monotonic()
                img.fill(Qt.GlobalColor.transparent)
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
                interval = 1 / NATIVE_FPS if _animate else 0.25
                self._stop.wait(max(0.0, interval - (time.monotonic() - start)))
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
    global _splash, _animate
    _animate = _animations_enabled()
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
    QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
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
    QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)


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
    _surfaces.clear()
