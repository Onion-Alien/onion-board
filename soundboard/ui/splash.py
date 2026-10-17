"""A small start-up panel in a soft glow of the theme's colours: Bun playing one of
his acts (ui/splashacts.py, a different one picked at random each launch), the app name
and three chasing dots; as the window comes up he waves goodbye. The theme is read
straight from config.json; the rest of the settings load later.

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

import atexit
import json
import logging
import math
import os
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QEventLoop, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QCursor, QFont, QFontMetricsF, QGuiApplication, QImage,
                           QPainter, QPainterPath, QPen, QRadialGradient)
from PySide6.QtWidgets import QApplication, QWidget

from soundboard import __version__, theme
from soundboard.bunny import sparkle
from soundboard.i18n import _
from soundboard.ui import splashacts
from soundboard.ui.pixels import snap_to_pixels

log = logging.getLogger(__name__)

CARD_W, CARD_H = 240, 248   # logical px, including 8 px around the rounded panel
RARE_H = 26   # a rare launch's card is this much taller: its tier and drop rate under the dots
DOTS_Y = CARD_H - 35   # the dots' resting centre (the bar sits there too)
BUN_W, BUN_H = 80, 96
PULSE_S = 1.35   # one complete left-to-right wave
FRAME = 1 / 30   # seconds between repaints while pumping (the Qt fallback)
NATIVE_FPS = 30
# while it's up, Python hands the GIL over every 0.5 ms instead of every 5: each frame
# takes the GIL dozens of times, and a busy UI thread would otherwise hold it 5 ms each
SWITCH_S = 0.0005
# library.CONFIG_PATH, without importing library (numpy, soundfile...) this early
CONFIG = Path(os.environ.get("APPDATA", Path.home())) / "OnionBoard" / "config.json"

_splash: Splash | NativeSplash | None = None
_last = 0.0
_surfaces: dict[tuple, QImage] = {}   # the panel and its text, drawn once
_animate = True
_show = splashacts.Show()   # this launch's act (splashacts.pick, in show())
# what it says under the name ("" = Starting…) and a bar 0..1 instead of the dots
# (None = the dots): set_status, read by every frame (also on the native thread)
_status = ""
_progress: float | None = None


def card_h() -> int:
    """This launch's card height: taller on a rare launch, for its tier line."""
    return CARD_H + RARE_H if _show.odds else CARD_H


def tier_name(rare: str) -> str:
    """A rare launch's tier, as the splash names it (RARES' keys, rarest first)."""
    return {"rainbow": _("Super Rare"), "galaxy": _("Legendary"), "ice": _("Rare"),
            "gold": _("Uncommon")}[rare]


def set_status(text: str = "", progress: float | None = None):
    """Say what start-up is doing (the update as it starts: UpdateControl.update_at_start),
    with a bar when `progress` (0..1) is given; set_status() goes back to Starting…."""
    global _status, _progress
    _status, _progress = text, progress
    pump()


def _surface(w: float, h: float, scale: float) -> QImage:
    """Cache the stationary panel at the monitor's resolution, including its text."""
    status = _status or _("Starting…")
    family = theme.T.get("font", theme.FONT)
    key = (w, h, scale, theme.current_name, tuple(theme.T.items()), family, status,
           _show.rare)
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
            _paint_glow(p, QRectF(8, 8, w - 16, h - 16))
            font = QFont(family)
            font.setPixelSize(18)
            font.setWeight(QFont.Weight.DemiBold)
            p.setFont(font)
            # the name with the version small beside it, the two centred as one
            name, version = "Onion Board", f"v{__version__}"
            vfont = QFont(family)
            vfont.setPixelSize(11)
            vw = QFontMetricsF(vfont).horizontalAdvance(version)
            nw = QFontMetricsF(font).horizontalAdvance(name)
            x = (w - (nw + 6 + vw)) / 2
            p.setPen(QColor(theme.T["text_hi"]))
            p.drawText(QRectF(x, 142, nw + 1, 26), Qt.AlignmentFlag.AlignVCenter, name)
            base = 142 + 13 + QFontMetricsF(font).ascent() / 2 - QFontMetricsF(font).descent() / 2
            p.setFont(vfont)
            p.setPen(QColor(theme.T["muted"]))
            p.drawText(QPointF(x + nw + 6, base), version)
            font.setPixelSize(12)
            font.setWeight(QFont.Weight.Normal)
            p.setFont(font)
            p.setPen(QColor(theme.T["muted"]))
            p.drawText(QRectF(20, 171, w - 40, 22), Qt.AlignmentFlag.AlignCenter, status)
            if _show.odds:   # a rare launch: tier and drop rate under the dots, in sparkles
                glow = QColor(splashacts.RARES[str(_show.rare)][2])
                font.setPixelSize(12)
                font.setWeight(QFont.Weight.Bold)
                p.setFont(font)
                p.setPen(glow)
                line = f"{tier_name(str(_show.rare))} · 1/{_show.odds}"
                y = DOTS_Y + 18   # clear of the dots' hop, as far again from the panel's edge
                p.drawText(QRectF(20, y, w - 40, 18), Qt.AlignmentFlag.AlignCenter, line)
                half = p.fontMetrics().horizontalAdvance(line) / 2
                for side in (-1, 1):
                    sparkle(p, w / 2 + side * (half + 10), y + 9, 4.5, glow)
        finally:
            p.end()
        _surfaces[key] = img
    return img


# the card's soft wash of the theme's colours: (centre x, centre y, radius) as fractions
# of the panel, which colour, how strong on a dark theme (light themes get 60 % of it)
GLOW = (((0.5, 0.05, 0.75), "accent", 0.22), ((1.0, 1.0, 0.7), "accent2", 0.12))


def _paint_glow(p: QPainter, panel: QRectF):
    """A soft glow of the theme's two accent colours over the panel: the accent behind
    Bun, the second one rising from a bottom corner. High Contrast keeps its flat panel."""
    if not theme.polished():
        return
    light = theme.is_light_colour(theme.T["panel"])
    path = QPainterPath()
    path.addRoundedRect(panel, 16, 16)
    for (cx, cy, r), key, strength in GLOW:
        g = QRadialGradient(QPointF(panel.x() + cx * panel.width(),
                                    panel.y() + cy * panel.height()), r * panel.height())
        c = QColor(theme.T.get(key, theme.T["accent"]))
        c.setAlphaF(strength * (0.6 if light else 1.0))
        g.setColorAt(0, c)
        c.setAlphaF(0)
        g.setColorAt(1, c)
        p.fillPath(path, g)


def _bun_rect(w: float) -> QRectF:
    return QRectF((w - BUN_W) / 2, 30, BUN_W, BUN_H)


def fade(leaving: float | None) -> float:
    """How solid the splash is `leaving` 0..1 through his goodbye: the whole window
    fades in its last part (fading Bun's shapes one by one shows them through each
    other)."""
    return 1.0 if leaving is None else min(1.0, max(0.0, (1 - leaving) / 0.45))


def paint_frame(p: QPainter, t: float, w: float, h: float, scale: float = 1.0,
                leaving: float | None = None):
    """The panel, Bun's act `t` seconds in and an accent, growing hop travelling across
    the dots. `leaving` 0..1: his goodbye instead (the window fades it out: `fade`)."""
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.drawImage(QRectF(0, 0, w, h), _surface(w, h, scale))
    _show.t = t
    glow = _show.glow
    if glow is not None:   # a rare launch: a soft glow round the panel, pulsing
        pulse = 0.75 + 0.25 * math.sin(2 * math.pi * t / 1.2)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(8):
            c = QColor(glow)
            c.setAlphaF(pulse * (0.9 if i == 0 else 0.42 * (1 - i / 8) ** 2))
            p.setPen(QPen(c, 2.0 if i == 0 else 1.2))
            p.drawRoundedRect(QRectF(8 - i * 0.9, 8 - i * 0.9, w - 16 + i * 1.8,
                                     h - 16 + i * 1.8), 16 + i * 0.9, 16 + i * 0.9)
        p.setPen(Qt.PenStyle.NoPen)
    p.save()
    room = QPainterPath()   # his act stays on the panel, above the name
    room.addRoundedRect(QRectF(8, 8, w - 16, h - 16), 16, 16)
    above = QPainterPath()
    above.addRect(QRectF(0, 0, w, 140))
    p.setClipPath(room.intersected(above))
    if leaving is not None:
        splashacts.goodbye(p, _show, leaving, _bun_rect(w))
    elif _animate:
        splashacts.draw(p, _show, t, _bun_rect(w))
    else:
        splashacts.still(p, _show, _bun_rect(w))
    p.restore()
    p.setPen(Qt.PenStyle.NoPen)
    accent = QColor(theme.T["accent"])
    resting = QColor(theme.T["muted"])
    progress = _progress
    if progress is not None:   # a bar where the dots were
        bar = QRectF(40, DOTS_Y - 3, w - 80, 6)
        p.setBrush(QColor(theme.T.get("border", theme.T["muted"])))
        p.drawRoundedRect(bar, 3, 3)
        p.setBrush(accent)
        p.drawRoundedRect(QRectF(bar.x(), bar.y(), bar.width() * min(max(progress, 0.0), 1.0),
                                 bar.height()), 3, 3)
        return
    for i in range(3):
        # A raised cosine confined to one step gives a clear 1 -> 2 -> 3 chase,
        # with a smooth handoff and the first dot highlighted from the first frame.
        distance = ((t / PULSE_S * 3 - i + 1.5) % 3) - 1.5
        pulse = (1 + math.cos(math.pi * distance)) / 2 if abs(distance) < 1 else 0.0
        # Windows' Animation effects off: the colour still walks 1 -> 2 -> 3 so the
        # app visibly isn't stuck, but nothing grows or hops
        move = pulse if _animate else 0.0
        c = QColor.fromRgbF(*(resting.redF() + (accent.redF() - resting.redF()) * pulse,
                              resting.greenF() + (accent.greenF() - resting.greenF()) * pulse,
                              resting.blueF() + (accent.blueF() - resting.blueF()) * pulse))
        p.setBrush(c)
        radius = 3 + 2.5 * move
        p.drawEllipse(QPointF(w / 2 + (i - 1) * 16, DOTS_Y - 5 * move), radius, radius)


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
        self.setFixedSize(CARD_W, card_h())
        self._t0 = time.monotonic()

    def paintEvent(self, ev):
        p = QPainter(self)
        snap_to_pixels(p)
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
        self._leave: float | None = None   # when his goodbye started (time.monotonic)
        self._switch = sys.getswitchinterval()
        sys.setswitchinterval(min(SWITCH_S, self._switch))   # never coarser than the app's
        self._thread = threading.Thread(target=self._run, name="splash", daemon=True)
        self._thread.start()
        atexit.register(self._halt)   # never mid-frame while Python shuts down
        self._up.wait(1.0)   # the first frame is on screen (or it gave up)

    def isVisible(self) -> bool:
        return self.ok and self._thread.is_alive() and not self._stop.is_set()

    def close(self, goodbye: bool = False):
        """Take it down; `goodbye`: after his wave (GOODBYE_S), without waiting for it."""
        if goodbye and _animate and self.isVisible():
            self._leave = time.monotonic()
            return
        self._halt()

    def _halt(self):
        self._stop.set()
        if self._thread is not threading.current_thread():
            self._thread.join(1.0)
        sys.setswitchinterval(self._switch)

    def leaving(self) -> bool:
        return self._leave is not None and self._thread.is_alive()

    def deleteLater(self):
        pass

    def _run(self):
        try:
            self._loop()
        except Exception:  # noqa: BLE001 - a splash must never stop the app starting
            log.debug("native splash failed", exc_info=True)
        finally:
            self._up.set()
            if self._leave is not None:   # it said goodbye on its own: tidy up after
                sys.setswitchinterval(self._switch)
                if _splash is None:
                    _surfaces.clear()

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
        w, h = round(CARD_W * k), round(card_h() * k)
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
                leaving = None
                if self._leave is not None:
                    leaving = (start - self._leave) / splashacts.GOODBYE_S
                    if leaving >= 1:
                        break
                img.fill(Qt.GlobalColor.transparent)
                p = QPainter(img)
                try:
                    p.scale(k, k)   # drawn at the monitor's real resolution, never stretched
                    paint_frame(p, start - t0, CARD_W, card_h(), k, leaving)
                finally:
                    p.end()   # never leave img mid-paint: Qt aborts when it's freed
                ctypes.memmove(bits, bytes(img.constBits()), nbytes)
                blend.alpha = round(255 * fade(leaving))
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
    global _splash, _animate, _show
    _animate = _animations_enabled()
    set_status()
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
        theme.set_current(cfg.get("theme", ""))
        _updated(str(cfg.get("update_pending") or ""))
    except Exception:  # noqa: BLE001 - first launch, or unreadable: the default theme
        pass
    _show = splashacts.pick()   # after the theme: his outfit is the theme's
    if QGuiApplication.platformName() == "windows":
        _splash = NativeSplash()   # draws itself on its own thread: nothing to pump
        if _splash.ok:
            return _splash
        _splash.close()   # it couldn't: the Qt one instead
    _splash = Splash()
    screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
    if screen is not None:
        geo = screen.availableGeometry()
        _splash.move(geo.center().x() - CARD_W // 2, geo.center().y() - card_h() // 2)
    _splash.show()
    _splash.repaint()
    QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
    sys.meta_path.insert(0, _PumpOnImport)
    return _splash


def _updated(pending: str):
    """The first start after an update: "Updated to X" instead of Starting…."""
    if pending and pending == __version__:
        set_status(_("Updated to {version}", version=__version__))


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


def close(goodbye: bool = False):
    """Take the splash down (the window is up, or start-up failed). `goodbye`: the
    window is up, so Bun waves first (on Windows, on the splash's own thread: this
    returns at once)."""
    global _splash
    try:
        sys.meta_path.remove(_PumpOnImport)
    except ValueError:
        pass
    leaving = False
    if isinstance(_splash, NativeSplash):
        _splash.close(goodbye)
        leaving = _splash.leaving()
    elif _splash is not None:
        _splash.close()
        _splash.deleteLater()
    _splash = None
    if not leaving:   # (still drawing his wave: its thread clears them when it's done)
        _surfaces.clear()
