"""Hand-painted widgets: level meter, EQ curve, seek slider, sound pads and their grid."""
from __future__ import annotations

import math
import time
from functools import lru_cache
from pathlib import Path

import numpy as np
from PySide6.QtCore import (QEasingCurve, QEvent, QMimeData, QObject, QPoint, QPointF, QRectF,
                            QSize, Qt, QTimer, QVariantAnimation, Signal)
from PySide6.QtGui import (QColor, QDrag, QFont, QFontMetrics, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import (QAbstractButton, QApplication, QGridLayout, QLabel, QMainWindow,
                               QMenu,
                               QScrollArea,
                               QSlider, QStackedWidget, QStyle, QStyleOptionSlider,
                               QTabWidget, QToolTip,
                               QVBoxLayout, QWidget)
from shiboken6 import delete as qt_delete
from shiboken6 import invalidate as qt_invalidate
from shiboken6 import isValid as qt_valid

from soundboard import library, midi, theme, thumbs
from soundboard.eq import MAX_DB as EQ_MAX_DB
from soundboard.eq import response_db as eq_response
from soundboard.engine import SR
from soundboard.library import AUDIO_EXTS, SoundMeta
from soundboard.settings import pretty_key
from soundboard.ui import icons
from soundboard.ui.bunnywidget import BunnyWidget
from soundboard.i18n import _
from soundboard.ui.pixels import snap_to_pixels

PAD_MIME = "application/x-soundboard-pad"


def take_out(layout, i: int = 0) -> None:
    """Take item `i` out of `layout` and free it; its widget stays alive.

    Qt's takeAt() hands the item to the caller, and from Python nobody ever frees it.
    A widget remembers the first item made for it, so after it's added back to a
    layout (columns re-stacked, a grid reflowed) its size changes kept going to the
    old, orphaned item: the new one kept a stale height for that width, and a card
    whose text grew was squeezed (its buttons drawn over the text) until the
    width changed."""
    item = layout.takeAt(i)
    if item is not None:
        qt_delete(item)


def widget_at(layout, i: int):
    """The widget of `layout`'s item `i` (None for a spacer, a nested layout or past
    the end). Use it, never ``layout.itemAt(i).widget()``.

    itemAt() makes a Python wrapper for the item that the layout keeps. When Qt
    deletes the item itself (its widget deleted or moved), the wrapper stays listed at
    that address, and the next Qt object made there reaches Python as that dead
    item: a new menu was handed to the style's polish() as a QWidgetItem. So the
    wrapper is dropped from the list right away; the item itself is untouched.
    (Not for our own layouts, e.g. panel.py's: they keep their items' wrappers in
    a list of their own, and that wrapper is the item.)"""
    item = layout.itemAt(i)
    if item is None:
        return None
    w = item.widget()
    if type(layout).__module__.startswith("PySide6."):
        qt_invalidate(item)
    return w


class DropdownMenu(QMenu):
    """A dropdown menu opened with a short gap from its button, not stuck to it."""
    GAP = 8

    def showEvent(self, ev):
        super().showEvent(ev)
        btn = self.parentWidget()
        if isinstance(btn, QAbstractButton):
            below = self.y() >= btn.mapToGlobal(btn.rect().center()).y()
            gap = self.GAP if below else -self.GAP
            room = btn.screen().availableGeometry() if btn.screen() else None
            new_y = self.y() + gap
            if room:
                new_y = max(room.top(), min(new_y, room.bottom() + 1 - self.height()))
            self.move(self.x(), new_y)


class WindowRoot(QWidget):
    """The main window's page: it paints the theme's window background itself (flat, or
    the Textured accent glow), the same picture opaque widgets copy (PadGrid)."""

    def paintEvent(self, e):
        p = QPainter(self)
        theme.paint_window_bg(p, e.rect(), QPointF(0, 0), self.width(), self.height())
        p.end()


class Meter(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.level = 0.0
        self._hot = False
        self._drawn = None        # (bar width in px, colour) as last painted
        self._col = "#13ce66"
        # the loudest the level can get: full bar and the red zone sit under it (the
        # send limiter holds what others hear at sendfx.CEILING_DB, under 0 dB)
        self.top_db = 0.0
        self.setFixedHeight(8)
        self.setAccessibleName(_("Level meter"))

    @property
    def hot(self) -> bool:
        return self._hot

    @hot.setter
    def hot(self, on: bool):
        self._hot = bool(on)
        self.update()

    def _bar(self) -> tuple[float, str]:
        db = 20 * np.log10(max(self.level, 1e-5)) - self.top_db
        frac = float(np.clip((db + 50) / 50, 0, 1))
        # Hysteresis keeps levels near the thresholds from flashing between colours.
        if self._col == "#ff4d4f":
            if db < -3.5:
                self._col = "#ffb020" if db >= -11.0 else "#13ce66"
        elif self._col == "#ffb020":
            if db >= -2.0:
                self._col = "#ff4d4f"
            elif db < -11.0:
                self._col = "#13ce66"
        else:
            if db >= -2.0:
                self._col = "#ff4d4f"
            elif db >= -9.0:
                self._col = "#ffb020"
        return frac, "#ff4d4f" if self._hot else self._col

    def set_level(self, v):
        self.level = v
        frac, col = self._bar()
        # fed 20-30 times a second: repaint only when the bar would look different
        drawn = (round(self.width() * frac), col if frac > 0 else "")
        if drawn != self._drawn:
            self._drawn = drawn
            self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._drawn = None

    def paintEvent(self, e):
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.T["groove"]))
        rad = min(4.0, r.height() / 2)
        p.drawRoundedRect(r, rad, rad)
        frac, col = self._bar()
        if frac > 0:
            p.setBrush(QColor(col))
            p.drawRoundedRect(QRectF(0, 0, r.width() * frac, r.height()), rad, rad)


class EqCurve(QWidget):
    """Draws the EQ's actual frequency response. Double-click resets to flat."""
    reset = Signal()

    def __init__(self):
        super().__init__()
        self.setFixedHeight(70)
        self.gains = [0.0] * 7
        self.on = False
        self.setToolTip(_("Double-click to reset"))
        self.setAccessibleName(_("EQ curve"))
        self._freqs = np.geomspace(30, 18000, 160)

    def set_gains(self, gains, on):
        self.gains, self.on = list(gains), on
        self.update()

    def mouseDoubleClickEvent(self, e):
        self.reset.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.T["bg"]))
        p.drawRoundedRect(r, 8, 8)
        mid = r.center().y()
        p.setPen(QPen(QColor(theme.T["groove"]), 1))
        p.drawLine(int(r.left() + 6), int(mid), int(r.right() - 6), int(mid))
        db = eq_response(self.gains, self._freqs)
        scale = (r.height() / 2 - 6) / EQ_MAX_DB
        path = QPainterPath()
        n = len(db)
        for i, d in enumerate(db):
            x = r.left() + 6 + (r.width() - 12) * i / (n - 1)
            y = mid - float(np.clip(d, -EQ_MAX_DB - 3, EQ_MAX_DB + 3)) * scale
            path.moveTo(x, y) if i == 0 else path.lineTo(x, y)
        col = QColor(theme.T["accent"] if self.on else theme.T["off"])
        p.setPen(QPen(col, 2.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        if not self.on:   # on a little plate, so the flat line doesn't strike it through
            fm = p.fontMetrics()
            off = _("EQ off")
            plate = QRectF(0, 0, fm.horizontalAdvance(off) + 14, fm.height() + 4)
            plate.moveCenter(r.center())
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.T["bg"]))
            p.drawRoundedRect(plate, plate.height() / 2, plate.height() / 2)
            p.setPen(QColor(theme.T["muted"]))
            p.drawText(plate, Qt.AlignmentFlag.AlignCenter, off)


class CrispSlider(QSlider):
    """Themed horizontal slider with a circle aligned to physical pixels."""

    def paintEvent(self, e):
        if self.orientation() != Qt.Orientation.Horizontal:
            return super().paintEvent(e)
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        style = self.style()
        handle = style.subControlRect(QStyle.ComplexControl.CC_Slider, opt,
                                      QStyle.SubControl.SC_SliderHandle, self)
        groove = QRectF(style.subControlRect(QStyle.ComplexControl.CC_Slider, opt,
                                            QStyle.SubControl.SC_SliderGroove, self))
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.T["groove"]))
        radius = groove.height() / 2
        p.drawRoundedRect(groove, radius, radius)
        if self.isEnabled() and self.sliderPosition() > self.minimum():
            fill = QRectF(groove)
            if opt.upsideDown:
                fill.setLeft(handle.center().x())
            else:
                fill.setRight(handle.center().x())
            p.setBrush(QColor(theme.T["accent" if self.objectName() == "seek" else "muted"]))
            p.drawRoundedRect(fill, radius, radius)
        # A stylesheet's rounded box with a transparent border leaves a soft rim.
        # Paint one circle instead, with its bounds on physical pixel boundaries.
        transform = p.deviceTransform()
        scale = transform.m11()
        bounds = transform.mapRect(QRectF(handle))
        diameter = math.floor(min(bounds.width(), bounds.height()) + 0.5)
        x = math.floor(bounds.center().x() - diameter / 2 + 0.5)
        y = math.floor(bounds.center().y() - diameter / 2 + 0.5)
        circle = QRectF((x - transform.dx()) / scale, (y - transform.dy()) / scale,
                        diameter / scale, diameter / scale)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.T["text_hi" if self.isEnabled() else
                                 ("off" if self.objectName() == "seek" else "inset")]))
        p.drawEllipse(circle)
        hovered = opt.activeSubControls == QStyle.SubControl.SC_SliderHandle
        if self.isEnabled() and (self.hasFocus() or hovered or self.isSliderDown()):
            width = 2 if self.hasFocus() else 1
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(theme.T["accent" if self.hasFocus() else "border_hi"]), width))
            p.drawEllipse(circle.adjusted(width / 2, width / 2, -width / 2, -width / 2))


class SeekSlider(CrispSlider):
    """Slider that jumps straight to where you click (then drags from there)."""

    def __init__(self, *args):
        super().__init__(*args)
        self.setAccessibleName(_("Playback position"))   # a screen reader said nothing on it
        # at 0:00 Qt still paints a sliver of fill beside the handle (it looked a few
        # seconds in): the theme hides the fill while "atstart" is set
        self.setProperty("atstart", True)

    def sliderChange(self, change):
        super().sliderChange(change)
        if change not in (QSlider.SliderChange.SliderValueChange,
                          QSlider.SliderChange.SliderRangeChange):
            return
        # Playback blocks signals to avoid seeking on each tick. This virtual
        # callback still runs, so the fill follows both playback and user input.
        at = self.value() <= self.minimum()
        if self.property("atstart") != at:   # restyle only when it flips, not every tick
            self.setProperty("atstart", at)
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.setValue(QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(), int(e.position().x()), self.width()))
        super().mousePressEvent(e)


class EdgeMatch(QObject):
    """Lines up the right ends of two bars in different rows (the player's seek
    slider and the "What others hear" meter): the one that reaches further gives up
    the difference through its ``set_pad`` callable, so the two end in one line. Only
    while both show, left to right, and the difference is small (a narrow window
    lays the rows out differently: a big gap there looked worse)."""

    MAX = 24

    def __init__(self, a: QWidget, pad_a, b: QWidget, pad_b):
        super().__init__(a)
        self._bars = ((a, pad_a), (b, pad_b))
        self._pads = [0, 0]
        self._queued = False
        for w in (a, b):
            w.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.Show,
                            QEvent.Type.Hide) and not self._queued:
            self._queued = True   # after the layouts have placed both
            QTimer.singleShot(0, self, self.match)
        return False

    def match(self):
        self._queued = False
        bars = [w for w, _ in self._bars]
        if not all(qt_valid(w) for w in bars):
            return
        pads = [0, 0]
        win = bars[0].window()
        if (all(w.isVisible() and w.isLeftToRight() and w.window() is win for w in bars)):
            # where each would end with no pad
            ends = [w.mapTo(win, QPoint(w.width(), 0)).x() + p
                    for w, p in zip(bars, self._pads)]
            give = [e - min(ends) for e in ends]
            if max(give) <= self.MAX:
                pads = give
        for i, (_w, set_pad) in enumerate(self._bars):
            if pads[i] != self._pads[i]:
                self._pads[i] = pads[i]
                set_pad(pads[i])


class NameAndSeek(QWidget):
    """The player's sound name with its seek slider right after it: the name is only
    as wide as its text (up to ``max_name``) and the slider takes the rest. Placed by
    hand, so a new name never changes this widget's size hint: the name changes with
    every pad press, and a hint change would lay out the whole page again."""

    GAP = 10
    SEEK_MIN = 120   # the slider, at the least

    def __init__(self, name: QLabel, seek: QWidget, max_name: int, parent=None):
        super().__init__(parent)
        self.name, self.seek, self.max_name = name, seek, max_name
        self.pad_right = 0   # room left after the slider (EdgeMatch)
        name.setParent(self)
        seek.setParent(self)
        name.installEventFilter(self)

    def sizeHint(self):
        return QSize(self.max_name + 120, max(self.name.height(), self.seek.sizeHint().height()))

    def minimumSizeHint(self):
        # honest, so the window's fitter hides other things (or the name) before the
        # slider gets too short to aim at or the name is cut: the name as it is now (up
        # to max_name). Not announced on a new name (no relayout per pad press): the
        # fitter measures it fresh on the next resize
        # (asked while the window closes too: nothing here may raise, overridepin.py)
        if not (qt_valid(self.name) and qt_valid(self.seek)):
            return QSize(self.SEEK_MIN, 0)
        name = 0 if self.name.isHidden() else self.GAP + min(
            self.max_name, self.name.fontMetrics().horizontalAdvance(self.name.text()) + 4)
        return QSize(self.SEEK_MIN + name, self.sizeHint().height())

    def relayout(self):
        h = self.height()
        fm = self.name.fontMetrics()
        w = 0 if self.name.isHidden() else min(
            self.max_name, fm.horizontalAdvance(self.name.text()) + 4,
            max(0, self.width() - self.SEEK_MIN - self.GAP))
        self.name.setGeometry(0, 0, w, h)
        sh = self.seek.sizeHint().height()
        x = w + self.GAP if not self.name.isHidden() else 0
        self.seek.setGeometry(x, (h - sh) // 2,
                              max(0, self.width() - self.pad_right - x), sh)

    def set_pad_right(self, px: int):
        self.pad_right = px
        self.relayout()

    def eventFilter(self, obj, event):
        if obj is self.name and event.type() in (QEvent.Type.Show, QEvent.Type.Hide):
            self.updateGeometry()   # the minimum has room for the name or not
            self.relayout()
        return super().eventFilter(obj, event)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.relayout()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self.relayout()


class LoadingBar(QWidget):
    """An indeterminate progress bar: an accent pill gliding back and forth along a
    rounded groove. Theme colours are read on every paint, and the timer only runs
    while it's started and on screen."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(6)
        self._t0 = time.monotonic()
        self._on = False
        self._timer = QTimer(self)
        self._timer.setInterval(1000 // 30)
        self._timer.timeout.connect(self.update)

    def start(self):
        self._on = True
        self._t0 = time.monotonic()
        if self.isVisible():
            self._timer.start()

    def stop(self):
        self._on = False
        self._timer.stop()

    def running(self) -> bool:
        return self._on

    def ticking(self) -> bool:
        return self._timer.isActive()

    def showEvent(self, ev):
        if self._on:
            self._timer.start()
        super().showEvent(ev)

    def hideEvent(self, ev):
        self._timer.stop()
        super().hideEvent(ev)

    def sizeHint(self) -> QSize:
        return QSize(240, 6)

    def paintEvent(self, _e):
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        rad = r.height() / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.T.get("groove", "#343849")))
        p.drawRoundedRect(r, rad, rad)
        # the pill eases from one end to the other and back, stretching mid-glide
        k = 0.5 - 0.5 * math.cos((time.monotonic() - self._t0) * math.pi / 0.9)
        w = r.width() * (0.28 + 0.14 * math.sin(k * math.pi))
        x = r.left() + (r.width() - w) * k
        g = QLinearGradient(x, 0, x + w, 0)
        g.setColorAt(0, QColor(theme.T.get("accent", "#7c5cff")))
        g.setColorAt(1, QColor(theme.T.get("accent2", theme.T.get("accent_hi", "#8d71ff"))))
        p.setBrush(g)
        p.drawRoundedRect(QRectF(x, r.top(), w, r.height()), rad, rad)
        p.end()


def paint_now_playing(p: QPainter, rect: QRectF, color: QColor, paused: bool = False,
                      n: int = 4, t: float | None = None):
    """A small "now playing" equalizer in `rect`: `n` bars bouncing with the clock (`t`,
    seconds; now if None), or low and still while paused. Used wherever something
    playing has to stand out at a glance: a web result's picture, the playing radio
    station."""
    t = time.monotonic() if t is None else t
    gap = rect.width() / (n * 3 - 1)   # a bar is two gaps wide
    bw = gap * 2
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    for i in range(n):
        f = 0.3 if paused else 0.25 + 0.75 * abs(math.sin(t * (2.3 + i * 0.9) + i * 1.7))
        h = max(bw, rect.height() * f)
        p.drawRoundedRect(QRectF(rect.left() + i * (bw + gap), rect.bottom() - h, bw, h),
                          bw / 2, bw / 2)
    p.restore()


def fmt_time(s: float) -> str:
    s = max(0, int(s))
    return f"{s // 60}:{s % 60:02d}"


def fmt_pos(pos: float, total: float) -> str:
    if total < 60:  # short clips: tenths of a second are more useful
        return f"{max(pos, 0):.1f}s / {total:.1f}s"
    return f"{fmt_time(pos)} / {fmt_time(total)}"


FFT_N = 2048
_HANN = np.hanning(FFT_N).astype(np.float32)
_FREQS = np.fft.rfftfreq(FFT_N, 1 / SR)


class SteadyTabs(QObject):
    """Keeps a QTabWidget from repainting all of itself when nothing it lays out
    changed. It answers every layout request from inside (a label's new text, a
    chip in the now-playing row, a tab's new icon) by laying out its tab bar and page
    area again and repainting everything under it: every pad on the board, 2-3
    times a pad press. Only its own size, the tab bar's and corner's size hints and
    the pages' minimum size matter to that layout; while those stay the same the
    request is dropped (the page inside still lays itself out)."""

    def __init__(self, tabs: QTabWidget):
        super().__init__(tabs)
        self._tabs = tabs
        self._stack = tabs.findChild(QStackedWidget, "qt_tabwidget_stackedwidget",
                                     Qt.FindChildOption.FindDirectChildrenOnly)
        self._last = None
        tabs.installEventFilter(self)

    def _state(self):
        t, bar = self._tabs, self._tabs.tabBar()
        if self._stack is not None and not qt_valid(self._stack):   # (seen once: find it again)
            self._stack = t.findChild(QStackedWidget, "qt_tabwidget_stackedwidget",
                                      Qt.FindChildOption.FindDirectChildrenOnly)
        corners = tuple(w.sizeHint() if w is not None and w.isVisible() else None
                        for w in (t.cornerWidget(Qt.Corner.TopLeftCorner),
                                  t.cornerWidget(Qt.Corner.TopRightCorner)))
        return (t.size(), t.isVisible(), t.count(), t.currentIndex(), bar.sizeHint(),
                bar.minimumSizeHint(), corners,
                self._stack.minimumSizeHint() if self._stack is not None else None)

    def eventFilter(self, obj, ev):
        if obj is self._tabs and ev.type() == QEvent.Type.LayoutRequest:
            state = self._state()
            if state == self._last:
                return True
            self._last = state
        return False


def spectrum(data: np.ndarray | None, frac: float, n: int) -> np.ndarray:
    """`n` log-spaced band levels (0..1) of int16/float (m, 2) audio around position
    `frac` (0..1): what a pad's visualizer shows. Cheap: one 2048-point FFT."""
    if data is None or not len(data) or n <= 0:
        return np.zeros(max(n, 0), np.float32)
    # the stretch just played, not the one coming: a long sound is read from disk
    # (mapped.py) and what's ahead may not be in yet, while the rest of the file is
    # being read in behind it. On a slow drive each frame waited its turn: the pad's
    # equalizer ran at 2 a second until that finished. What was just played is in.
    pos = max(0, int(min(max(frac, 0.0), 1.0) * len(data)) - FFT_N)
    seg = data[pos:pos + FFT_N]
    if len(seg) < FFT_N:
        seg = np.concatenate([seg, np.zeros((FFT_N - len(seg), 2), seg.dtype)])
    mono = seg.mean(axis=1, dtype=np.float32)
    if data.dtype == np.int16:
        mono /= 32768.0
    mag = np.abs(np.fft.rfft(mono * _HANN)) * (4.0 / FFT_N)   # full-scale sine ~ 1
    start, count, tilt = _band_plan(n)
    # each band's RMS from a running sum of the power: no Python loop over bands
    power = np.concatenate(([0.0], np.cumsum(mag.astype(np.float64) ** 2)))
    out = np.sqrt((power[start + count] - power[start]) / count)
    db = 20 * np.log10(out + 1e-9) + tilt
    return np.clip((db + 62) / 52, 0.0, 1.0).astype(np.float32)


def loudness(data: np.ndarray | None, frac: float, gain: float = 1.0) -> float:
    """How loud (0..1) the stretch just played around `frac` is: its RMS times `gain`,
    -48 dBFS..0 dBFS. What a playing pad's level meter shows; the same window as
    spectrum() (what's ahead of a long sound may not be read in yet)."""
    if data is None or not len(data):
        return 0.0
    pos = max(0, int(min(max(frac, 0.0), 1.0) * len(data)) - FFT_N)
    seg = data[pos:pos + FFT_N]
    if not len(seg):
        return 0.0
    mono = seg.mean(axis=1, dtype=np.float32)
    if data.dtype == np.int16:
        mono /= 32768.0
    rms = float(np.sqrt(np.mean(mono * mono))) * max(gain, 0.0)
    return min(max((20 * math.log10(rms + 1e-9) + 48) / 48, 0.0), 1.0)


@lru_cache(maxsize=16)
def _band_plan(n: int):
    """Where spectrum()'s `n` log-spaced bands start in the FFT, how many bins each
    covers (at least one), and the lift each gets because music falls off up high."""
    edges = np.geomspace(50, 14000, n + 1)
    idx = np.clip(np.searchsorted(_FREQS, edges), 1, len(_FREQS) - 1)
    start = idx[:-1]
    count = np.maximum(idx[1:], start + 1) - start
    return start, count, np.linspace(0, 14, n)


MINI_PAD_MIN_W = 96   # the mini player's two-a-row pads get no smaller than this


SLIM_PAD_H = 30      # a pad as a one-line row: the mini player when it's too small for cards
# the Sounds tab's list view, by its row size (Config.list_rows): how tall a row is,
# and how wide at least (as many a line as fit)
LIST_ROW_H = {"small": 26, "medium": 30, "large": 38}
LIST_ROW_W = {"small": 220, "medium": 260, "large": 300}
ROW_MAX_H = max(LIST_ROW_H.values())   # a pad this short or shorter is drawn as a row


def pad_height(width: int) -> int:
    return int(width * 0.62)


# a picture on a pad is darkened towards the bottom so the text reads on it:
# (where 0..1, black's alpha), lighter while the mouse is over it
PAD_RADIUS = 12      # a pad card's rounded corners
HOVER_LIFT = 2.0     # how far a card rises under the mouse (it has 2 px spare above)
HOVER_MS = 120       # ...and how quickly: short, so moving across the board feels light
PAD_SHRINK = 0.8     # a row takes one more pad when that shrinks them by a fifth at most
PIC_SHADE = ((0.0, 100), (0.55, 150), (1.0, 205))
PIC_SHADE_HOVER = ((0.0, 70), (0.55, 120), (1.0, 205))

_PAD_COLOURS = ("card", "card_hi", "border", "border_hi", "accent", "on_accent", "text_hi",
                "muted", "error_text", "badge", "badge_text")
_pad_palette: list = [None, {}]   # (the theme's values, QColor for each) - see pad_colours
_SHADOW, _WHITE = QColor(0, 0, 0, 200), QColor("#ffffff")   # text on a picture
_METER_WARM, _METER_HOT = QColor("#ffb84d"), QColor("#ff5a4f")   # a level meter near full scale
_WHITE_DIM, _WHITE_MUTED = QColor(255, 255, 255, 170), QColor(255, 255, 255, 200)
_ERROR_ON_PIC = QColor("#ff6b6b")
LINK_PX = 12         # the linked-file mark: the footer text's height
_link_pm: dict = {}  # (colour, real pixels) -> its pixmap


def _link_pixmap(colour: QColor, dpr: float) -> QPixmap:
    px = round(LINK_PX * dpr)
    key = (colour.rgba(), px)
    pm = _link_pm.get(key)
    if pm is None:
        pm = _link_pm[key] = icons.pixmap("link", px, colour.name(QColor.NameFormat.HexArgb))
        pm.setDevicePixelRatio(dpr)
    return pm


def pad_colours() -> dict[str, QColor]:
    """The theme colours a pad paints with, as QColors made once per theme (a few
    hundred pads each made a dozen every paint)."""
    key = tuple(theme.T[k] for k in _PAD_COLOURS)
    if key != _pad_palette[0]:
        _pad_palette[0] = key
        _pad_palette[1] = {k: QColor(v) for k, v in zip(_PAD_COLOURS, key)}
    return _pad_palette[1]


class Pad(QAbstractButton):
    """One sound's button, painted by hand. It's a QAbstractButton so screen readers
    see a button with the sound's name, and it works from the keyboard: Tab / arrows
    to move, Enter or Space to play, Ctrl+Space to pick, the Menu key for its menu,
    F2 to rename it, Alt+Enter to edit it (Delete removes it: ui/padbatch.py)."""
    activated = Signal(str)     # play it (a double-click, Enter, a screen reader's press)
    rename = Signal(str)        # F2: ask for a new name
    edit = Signal(str)          # Alt+Enter: the Edit window
    chosen = Signal(str)        # a single click: select it (transport bar) without playing
    pick = Signal(str, bool)    # Ctrl+click / Ctrl+Space (False) or Shift+click (True)
    space = Signal(str)         # Space: pause / resume it if it's playing, else play it
    menu = Signal(str, QPoint)
    step = Signal(object, int, int)   # arrow key: this pad, columns, rows to move focus
    nudge = Signal(str, int)    # Ctrl+wheel: its volume this many steps up (+) or down (-)
    single_click = False        # Settings: a click plays it (activated) instead of selecting

    def __init__(self, meta: SoundMeta, width: int):
        super().__init__()
        self.setProperty("own_space", True)   # Space pauses / plays this pad (ui/spacekey.py)
        self.meta = meta
        self.progress: float | None = None     # None = not playing
        self.paused = False
        self.bands: np.ndarray | None = None   # visualizer levels (0..1) while playing
        self.peaks: np.ndarray | None = None   # the little caps that fall slowly
        self.meter = None        # how loud it is right now (0..1) while playing
        self.meter_peak = 0.0    # the meter's peak mark, falling slowly
        self.selected = False    # the sound in the transport bar
        self.picked = False      # one of several picked for a batch change (ui.padbatch)
        self.state = "loading"   # loading | ready | error
        self.error = ""
        self.hover = False
        self._hover_k = 0.0      # 0..1, eased in and out (the card lights up smoothly)
        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(HOVER_MS)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)   # quick up, soft landing
        self._hover_anim.valueChanged.connect(self._on_hover_k)
        self._down = False       # pressed: the card sinks a little
        self.name_cut = False    # the name is cut short with "…" (_fit_name)
        self._play_t: float | None = None   # when it started playing (the flash on start)
        self._press = None
        self._last_click = -1e9   # when a plain left click was let go (ms): see _second_click
        self._kbd_focus = False  # focus came from the keyboard: draw the focus ring
        self._described = None
        self._name_fit = None    # (what it was fitted to, how) - see _fit_name
        self._font_key = self.font().key()
        self._accent: tuple[str | None, QColor] = (None, QColor())   # (meta.color, its QColor)
        # (what the footer shows, its font, text and badge)
        self._foot: tuple[tuple | None, tuple[QFont, str, tuple[str, int] | None] | None] = \
            (None, None)
        self._linked = (None, "")     # (meta.file, its path when outside the library)
        self._link_rect: QRectF | None = None   # where the linked-file mark was painted
        self._wheel = 0               # Ctrl+wheel turned less than a notch (touchpads)
        self.setFixedSize(width, pad_height(width))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.clicked.connect(lambda: self.activated.emit(self.meta.id))   # keyboard / a11y
        self.describe()

    def set_picked(self, on: bool):
        self.picked = on
        self.describe()
        self.update()

    def describe(self):
        """Keep what a screen reader says in step with the pad (only when it changes)."""
        m = self.meta
        bits = []
        if self.progress is not None:
            bits.append(_("paused") if self.paused else _("playing"))
        if self.picked:
            bits.append(_("selected"))
        if self.state in ("loading", "rendering"):
            bits.append(_("loading"))
        elif self.state == "error":
            bits.append(_("can't load the file"))
        else:
            bits.append(_("{s} seconds", s=f"{m.duration:.1f}"))
        if m.hotkey:
            bits.append(_("hotkey {key}", key=pretty_key(m.hotkey)))
        if m.loop:
            bits.append(_("loops"))
        if m.mode in ("overlap", "toggle"):
            bits.append({"overlap": _("presses overlap"),
                         "toggle": _("press again stops")}[m.mode])
        if m.hold:
            bits.append(_("plays while its hotkey is held"))
        if m.fx:
            bits.append(_("effects"))
        if m.tags:
            bits.append(_("in {categories}", categories=", ".join(
                t if "/" not in t else t.replace(" / ", " › ") for t in m.tags
                if not any(o.startswith(t + " / ") for o in m.tags))))
        if self.linked_file():
            bits.append(_("Plays from: {path}", path=self.linked_file()))
        desc = ", ".join(bits)
        if (m.name, desc) != self._described:
            self._described = (m.name, desc)
            self.setText(m.name.replace("&", "&&"))   # else "R&B" claims Alt+B
            self.setAccessibleName(m.name)
            self.setAccessibleDescription(desc)

    def linked_file(self) -> str:
        """The sound's file on the disk when the library didn't copy it in ("Copy into
        library" is off: the pad plays the original), else ""."""
        f = self.meta.file
        if self._linked[0] != f:
            self._linked = (f, str(Path(f)) if f and not library.owns(f) else "")
        return self._linked[1]

    def event(self, e):
        """The linked-file mark's tooltip shows over the mark only; elsewhere on the pad,
        the whole name when it's cut short."""
        if e.type() == QEvent.Type.ToolTip:
            box = self._link_rect
            hit = box.adjusted(-4, -4, 4, 4) if box is not None else None
            if hit is not None and hit.contains(QPointF(e.pos())) and self.linked_file():
                QToolTip.showText(e.globalPos(), _("Plays from: {path}",
                                                   path=self.linked_file()),
                                  self, hit.toAlignedRect())
            elif self.name_cut:
                QToolTip.showText(e.globalPos(), self.meta.name, self)
            else:
                QToolTip.hideText()
                e.ignore()
            return True
        return super().event(e)

    def focusInEvent(self, e):
        self._kbd_focus = e.reason() in (Qt.FocusReason.TabFocusReason,
                                         Qt.FocusReason.BacktabFocusReason,
                                         Qt.FocusReason.ShortcutFocusReason,
                                         Qt.FocusReason.OtherFocusReason)
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self._kbd_focus = False
        super().focusOutEvent(e)

    def keyPressEvent(self, e):
        k, mods = e.key(), e.modifiers()
        arrows = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0), Qt.Key.Key_Up: (0, -1),
                  Qt.Key.Key_Down: (0, 1)}
        if k == Qt.Key.Key_Space and mods & Qt.KeyboardModifier.ControlModifier:
            self.pick.emit(self.meta.id, False)
        elif k == Qt.Key.Key_Space and not mods:
            if not e.isAutoRepeat():
                self.space.emit(self.meta.id)
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and mods & Qt.KeyboardModifier.AltModifier:
            self.edit.emit(self.meta.id)
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.activated.emit(self.meta.id)
        elif k == Qt.Key.Key_F2 and not mods:
            self.rename.emit(self.meta.id)
        elif k == Qt.Key.Key_Menu or (k == Qt.Key.Key_F10
                                      and mods & Qt.KeyboardModifier.ShiftModifier):
            self.menu.emit(self.meta.id, self.mapToGlobal(self.rect().center()))
        elif k in arrows and not mods & (Qt.KeyboardModifier.ControlModifier
                                         | Qt.KeyboardModifier.AltModifier):
            self.step.emit(self, *arrows[k])
        else:
            super().keyPressEvent(e)

    def changeEvent(self, e):
        if e.type() == QEvent.Type.FontChange:
            self._font_key = self.font().key()
        super().changeEvent(e)

    def _fit_name(self, room: QRectF) -> tuple[QFont, Qt.AlignmentFlag, str]:
        """The name's font, flags and text: one line from the top, cut short with "…"
        when it doesn't fit (hovering the pad shows all of it). Wrapping it, or a size
        smaller, changed with the pad's width: a resize made names jump between one
        line and two."""
        key = (self.meta.name, room.width(), self._font_key)
        if self._name_fit is None or self._name_fit[0] != key:
            name = self.meta.name
            f = QFont(self.font())
            f.setBold(True)
            f.setPointSizeF(10.5)
            text = QFontMetrics(f).elidedText(name, Qt.TextElideMode.ElideRight,
                                              room.toRect().width())
            self._name_fit = (key, (f, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                                    text))
            self.name_cut = text != name
        return self._name_fit[1]

    def _accent_colour(self) -> QColor:
        if self._accent[0] != self.meta.color:
            self._accent = (self.meta.color, QColor(self.meta.color))
        return self._accent[1]

    def _footer(self, foot: QRectF, name_font: QFont) -> tuple[QFont, str, tuple[str, int] | None]:
        """(font, the right-hand text, the hotkey badge's (text, width) or None): only
        worked out again when something it shows changes."""
        m = self.meta
        key = (m.fx, m.loop, m.mode, m.hold, m.duration, m.hotkey, self.paused,
               foot.width(), self._font_key)
        if self._foot[0] != key:
            f = QFont(name_font)
            f.setBold(False)
            f.setPointSizeF(8.5)
            flags = ("FX " if m.fx else "") + ("⟳ " if m.loop else "") + \
                {"overlap": "⧉ ", "toggle": "⏯ "}.get(m.mode, "") + \
                (_("hold") + " " if m.hold else "")
            right = _("❚❚ paused") if self.paused else f"{flags}{m.duration:.1f}s"
            hk = m.hotkey and (midi.short(m.hotkey) if midi.is_midi(m.hotkey)
                               else pretty_key(m.hotkey))
            badge = None
            fm = QFontMetrics(f)
            # a cut-off key ("Ctrl+Al…") says nothing: no badge on a pad too narrow
            if hk and fm.horizontalAdvance(hk) + 12 <= foot.width() * 0.68:
                badge = (hk, fm.horizontalAdvance(hk) + 12)
            self._foot = (key, (f, right, badge))
        out = self._foot[1]
        assert out is not None   # made above
        return out

    @property
    def n_bands(self) -> int:
        return max(8, min(28, (self.width() - 20) // 9))

    def set_levels(self, levels):
        """New visualizer levels (None clears): bars jump up and fall back smoothly."""
        if levels is None:
            self.bands = self.peaks = None
            return
        levels = np.asarray(levels, np.float32)
        if self.bands is None or len(self.bands) != len(levels):
            self.bands, self.peaks = levels.copy(), levels.copy()
            return
        assert self.peaks is not None   # set with the bands
        self.bands = np.maximum(levels, self.bands * 0.78)
        self.peaks = np.maximum(self.bands, self.peaks - 0.025)

    def set_meter(self, v):
        """The level meter's new reading (None clears): up at once, down smoothly, so
        it reads as loudness rather than flicker; the peak mark falls slower still."""
        if v is None:
            self.meter, self.meter_peak = None, 0.0
            return
        v = min(max(float(v), 0.0), 1.0)
        self.meter = v if self.meter is None else max(v, self.meter * 0.86)
        self.meter_peak = max(self.meter, self.meter_peak - 0.012)

    def _on_hover_k(self, v):
        self._hover_k = float(v)
        self.update()

    def _fade_hover(self, on: bool):
        self.hover = on
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_k)
        self._hover_anim.setEndValue(1.0 if on else 0.0)
        self._hover_anim.start()

    def enterEvent(self, e):
        self._fade_hover(True)

    def leaveEvent(self, e):
        self._down = False
        self._fade_hover(False)

    def _second_click(self, e) -> bool:
        """A second plain left click soon after the first, anywhere on the pad. Qt only
        counts a double-click when both land a few pixels apart, so top-left then
        bottom-right was two single clicks (and a drag if the mouse was still moving)."""
        return (not Pad.single_click and e.button() == Qt.MouseButton.LeftButton
                and not e.modifiers() & (Qt.KeyboardModifier.ShiftModifier
                                         | Qt.KeyboardModifier.ControlModifier)
                and time.monotonic() * 1000 - self._last_click
                <= QApplication.doubleClickInterval())

    def mousePressEvent(self, e):
        if self._second_click(e):
            self._last_click = -1e9   # a third click starts over
            self._press = None        # no drag, no select on release
            self._down = True
            self.update()
            self.activated.emit(self.meta.id)
        elif e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position().toPoint()
            self._down = True
            self.update()
        elif e.button() == Qt.MouseButton.RightButton:
            self.menu.emit(self.meta.id, e.globalPosition().toPoint())

    def mouseMoveEvent(self, e):
        moved = self._press is not None and \
            (e.position().toPoint() - self._press).manhattanLength() > 12
        if moved:
            self._press = None
            self._down = False
            self.update()
            drag = QDrag(self)
            md = QMimeData()
            md.setData(PAD_MIME, self.meta.id.encode())
            drag.setMimeData(md)
            # half the pad's size on screen: grab() is in real pixels, so scaling it to
            # half the logical size made a 40 % preview on a 125 % screen
            shot = self.grab()
            dpr = shot.devicePixelRatio()
            half = shot.scaled(round(self.width() / 2 * dpr), round(self.height() / 2 * dpr),
                               Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            half.setDevicePixelRatio(dpr)
            drag.setPixmap(half)
            drag.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, e):
        if self._down:
            self._down = False
            self.update()
        if e.button() == Qt.MouseButton.LeftButton and self._press is not None:
            self._press = None
            mods = e.modifiers()
            if not mods & (Qt.KeyboardModifier.ShiftModifier
                           | Qt.KeyboardModifier.ControlModifier):
                self._last_click = time.monotonic() * 1000
            if mods & Qt.KeyboardModifier.ShiftModifier:
                self.pick.emit(self.meta.id, True)
            elif mods & Qt.KeyboardModifier.ControlModifier:
                self.pick.emit(self.meta.id, False)
            elif Pad.single_click:
                self.activated.emit(self.meta.id)
            else:
                self.chosen.emit(self.meta.id)

    def wheelEvent(self, e):
        """Ctrl+wheel: the sound's volume. A plain wheel still scrolls the pads."""
        if not e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            e.ignore()
            return
        self._wheel += e.angleDelta().y()
        steps = int(self._wheel / 120)
        if steps:
            self._wheel -= steps * 120
            self.nudge.emit(self.meta.id, steps)
        e.accept()

    def mouseDoubleClickEvent(self, e):
        # Qt sends this in place of the second press: the same as a press (it plays when
        # it's a second click: _second_click; a quick second click is just another click
        # when one click plays)
        self.mousePressEvent(e)

    def paintEvent(self, e):
        self.describe()
        if self.height() <= ROW_MAX_H:
            self._paint_slim()
            return
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        accent = self._accent_colour()
        C = pad_colours()
        lo, hi, k = C["card"], C["card_hi"], self._hover_k
        if self._down:
            r.adjust(1.5, 1.5, -1.5, -1.5)
        elif k > 0.0:   # the mouse over it: it lifts off a soft shadow
            p.setPen(Qt.PenStyle.NoPen)
            for grow, alpha in ((0.0, 60), (1.0, 30), (2.0, 14)):   # a blur, cheaply
                p.setBrush(QColor(0, 0, 0, int(alpha * k)))
                p.drawRoundedRect(r.adjusted(-grow, HOVER_LIFT - grow + 0.5,
                                             grow, HOVER_LIFT + grow),
                                  PAD_RADIUS + grow, PAD_RADIUS + grow)
            r.translate(0, -HOVER_LIFT * k)
        if k <= 0.0:
            base = lo
        elif k >= 1.0:
            base = hi
        else:
            base = QColor.fromRgbF(lo.redF() + (hi.redF() - lo.redF()) * k,
                                   lo.greenF() + (hi.greenF() - lo.greenF()) * k,
                                   lo.blueF() + (hi.blueF() - lo.blueF()) * k)
        if self._down:
            base = base.darker(108)
        path = QPainterPath()
        path.addRoundedRect(r, PAD_RADIUS, PAD_RADIUS)
        p.fillPath(path, base)
        pic = self._picture(r)
        playing = self.progress is not None
        now = time.monotonic()
        if not playing:
            self._play_t = None
        elif self._play_t is None:
            self._play_t = now
        if pic is not None:   # already the pad's size, shade and corners: a plain copy
            p.drawPixmap(r.topLeft(), pic)
        else:   # its colour as a soft wash from the top, not a stripe
            tint = QLinearGradient(0, r.top(), 0, r.bottom())
            top, clear = QColor(accent), QColor(accent)
            top.setAlpha(32)
            clear.setAlpha(0)
            tint.setColorAt(0.0, top)
            tint.setColorAt(0.75, clear)
            p.fillPath(path, tint)
        if playing:
            p.save()
            p.setClipPath(path)
            done = QColor(accent)   # how far it's got: the card fills from the left
            done.setAlpha(34)
            progress = self.progress or 0.0   # (playing: set)
            p.fillRect(QRectF(r.left(), r.top(), r.width() * progress, r.height()), done)
            flash = 1 - (now - (self._play_t if self._play_t is not None else now)) / 0.35
            if flash > 0:   # a quick wash of its colour as it starts
                wash = QColor(accent)
                wash.setAlpha(int(90 * flash))
                p.fillPath(path, wash)
            self._paint_visualizer(p, r, accent)
            self._paint_meter(p, r, accent)
            # progress: a thin accent line along the bottom edge
            p.fillRect(QRectF(r.left(), r.bottom() - 3, r.width() * progress, 3), accent)
            p.restore()
        p.setBrush(Qt.BrushStyle.NoBrush)
        if playing:
            glow = QColor(accent)   # breathes while it plays
            glow.setAlpha(60 if self.paused else int(105 + 35 * math.sin(now * 5)))
            p.setPen(QPen(glow, 6))
            p.drawPath(path)
            ink = QColor(accent)
            if self.paused:   # paused: the same line, faded
                ink.setAlpha(110)
            pen = QPen(ink, 2.2)
            p.setPen(pen)
        elif self.picked:
            p.setPen(QPen(C["accent"], 2.4))
        elif self.selected:
            p.setPen(QPen(C["border_hi"], 1.6))
        else:   # at rest: no outline, the card's own shade is enough
            p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(path)
        if self.picked:   # a tick in the corner, so it reads as picked while playing too
            c = QRectF(r.right() - 24, r.top() + 6, 18, 18)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C["accent"])
            p.drawEllipse(c)
            tick = QPen(C["on_accent"], 2.2)   # white vanished on yellow accents
            tick.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(tick)
            p.drawPolyline([QPointF(c.left() + 5, c.center().y()),
                            QPointF(c.left() + 8, c.bottom() - 5),
                            QPointF(c.right() - 4, c.top() + 5)])
            p.setBrush(Qt.BrushStyle.NoBrush)
        if self.hasFocus() and self._kbd_focus:
            p.setPen(QPen(C["text_hi"], 1.4))
            p.drawRoundedRect(r.adjusted(3, 3, -3, -3), 10, 10)
        on_pic = pic is not None
        # name
        text_r = r.adjusted(10, 12, -10, -24)
        f, flags, name = self._fit_name(text_r)
        p.setFont(f)
        if on_pic:   # a soft shadow keeps it readable on any picture
            p.setPen(_SHADOW)
            p.drawText(text_r.translated(1, 1), flags, name)
            p.setPen(_WHITE if self.state == "ready" else _WHITE_DIM)
        else:
            p.setPen(C["text_hi"] if self.state == "ready" else C["muted"])
        p.drawText(text_r, flags, name)
        muted = _WHITE_MUTED if on_pic else C["muted"]
        # footer: hotkey + duration / state
        foot = r.adjusted(10, r.height() - 24, -10, -6)
        f, right, badge = self._footer(foot, f)
        p.setFont(f)
        self._link_rect = None
        if self.state in ("loading", "rendering"):
            p.setPen(muted)
            p.drawText(foot, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       _("applying effects…") if self.state == "rendering" else _("loading…"))
        elif self.state == "error":
            p.setPen(_ERROR_ON_PIC if on_pic else C["error_text"])   # readable on light
            p.drawText(foot, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       _("can't load file"))
        else:
            p.setPen(muted)
            p.drawText(foot, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, right)
            if self.linked_file():   # a small chain link just before the length
                x = foot.right() - QFontMetrics(f).horizontalAdvance(right) - 5 - LINK_PX
                if x >= foot.left() + (badge[1] + 6 if badge is not None else 0):
                    box = QRectF(x, foot.center().y() - LINK_PX / 2, LINK_PX, LINK_PX)
                    p.drawPixmap(box.topLeft(), _link_pixmap(muted, self.devicePixelRatioF()))
                    self._link_rect = box
            if badge is not None:
                hk, w = badge
                box = QRectF(foot.left(), foot.top() + 1, w, foot.height() - 2)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(C["badge"])
                p.drawRoundedRect(box, 5, 5)
                p.setPen(C["badge_text"])
                p.drawText(box, Qt.AlignmentFlag.AlignCenter, hk)

    def _picture(self, r: QRectF):
        """The pad's picture fitted to `r` in real pixels with its shade drawn on, or
        None. thumbs.fitted caches it by picture, size, screen and shade, so a resize,
        a press, a new picture, another screen or the mouse over it each get their own
        and nothing is scaled on an ordinary paint. None (the plain card) while the
        file is still being read."""
        if not self.meta.image:
            return None
        dpr = self.devicePixelRatioF()
        return thumbs.fitted(self.meta.image, math.ceil(r.width() * dpr),
                             math.ceil(r.height() * dpr), dpr,
                             PIC_SHADE_HOVER if self.hover else PIC_SHADE, PAD_RADIUS,
                             waiter=self)   # read off the UI thread: repainted when in

    def _paint_slim(self):
        """A one-line row: accent dot, name, duration; progress along the bottom."""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        T = theme.T
        accent = QColor(self.meta.color)
        lo, hi, k = QColor(T["card"]), QColor(T["card_hi"]), self._hover_k
        base = QColor.fromRgbF(lo.redF() + (hi.redF() - lo.redF()) * k,
                               lo.greenF() + (hi.greenF() - lo.greenF()) * k,
                               lo.blueF() + (hi.blueF() - lo.blueF()) * k)
        if self._down:
            base = base.darker(108)
        path = QPainterPath()
        path.addRoundedRect(r, 7, 7)
        p.fillPath(path, base)
        playing = self.progress is not None
        if playing:
            p.save()
            p.setClipPath(path)
            wash = QColor(accent)
            wash.setAlpha(40)
            p.fillPath(path, wash)
            p.fillRect(QRectF(r.left(), r.bottom() - 2, r.width() * (self.progress or 0.0), 2),
                       accent)
            p.restore()
        if playing:
            ink = QColor(accent)
            if self.paused:   # paused: the same line, faded
                ink.setAlpha(110)
            pen = QPen(ink, 1.8)
        elif self.picked:
            pen = QPen(QColor(T["accent"]), 2)
        elif self.selected:
            pen = QPen(QColor(T["border_hi"]), 1.4)
        else:
            pen = Qt.PenStyle.NoPen
        p.setPen(pen)
        p.drawPath(path)
        if self.hasFocus() and self._kbd_focus:
            p.setPen(QPen(QColor(T["text_hi"]), 1.2))
            p.drawRoundedRect(r.adjusted(2, 2, -2, -2), 5, 5)
        p.setPen(Qt.PenStyle.NoPen)
        dot = QRectF(r.left() + 9, r.center().y() - 4, 8, 8)
        if self.meter:   # the row's level meter: a halo round the dot, as loud as it is
            halo = QColor(accent)
            halo.setAlpha(60 if self.paused else 140)
            p.setBrush(halo)
            grow = 1 + 5 * self.meter
            p.drawEllipse(dot.adjusted(-grow, -grow, grow, grow))
        p.setBrush(QColor(T["accent"]) if self.picked else accent)
        p.drawEllipse(dot)
        f = QFont(self.font())
        h = self.height()   # bigger rows (the list's row size), bigger text
        f.setPointSizeF(8.0 if h < SLIM_PAD_H else 8.5 if h < ROW_MAX_H else 9.5)
        p.setFont(f)
        fm = p.fontMetrics()
        if self.state in ("loading", "rendering"):
            right = _("applying…") if self.state == "rendering" else _("loading…")
            rc = T["muted"]
        elif self.state == "error":
            right, rc = _("can't load"), "#ff6b6b"
        else:
            m = self.meta
            flags = ("⟳ " if m.loop else "") + \
                {"overlap": "⧉ ", "toggle": "⏯ "}.get(m.mode, "")
            right = "❚❚" if self.paused else f"{flags}{m.duration:.1f}s"
            rc = T["muted"]
        rw = fm.horizontalAdvance(right) + 4
        self._link_rect = None
        if self.state == "ready" and self.linked_file() and r.width() >= 160:
            box = QRectF(r.right() - 9 - rw - 2 - LINK_PX, r.center().y() - LINK_PX / 2,
                         LINK_PX, LINK_PX)
            p.drawPixmap(box.topLeft(), _link_pixmap(QColor(T["muted"]),
                                                     self.devicePixelRatioF()))
            self._link_rect = box
            rw += LINK_PX + 6
        p.setPen(QColor(rc))
        p.drawText(r.adjusted(0, 0, -9, 0), Qt.AlignmentFlag.AlignRight
                   | Qt.AlignmentFlag.AlignVCenter, right)
        hk = self.meta.hotkey and (midi.short(self.meta.hotkey) if midi.is_midi(self.meta.hotkey)
                                   else pretty_key(self.meta.hotkey))
        if hk and r.width() >= 200:   # the key as a badge left of the length, room allowing
            bw = fm.horizontalAdvance(hk) + 10
            if bw <= r.width() * 0.4:
                box = QRectF(r.right() - 9 - rw - 4 - bw, r.center().y() - 9, bw, 18)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(pad_colours()["badge"])
                p.drawRoundedRect(box, 5, 5)
                p.setPen(pad_colours()["badge_text"])
                p.drawText(box, Qt.AlignmentFlag.AlignCenter, hk)
                rw += bw + 8
        f.setBold(True)
        p.setFont(f)
        text_r = r.adjusted(24, 0, -14 - rw, 0)
        p.setPen(QColor(T["text_hi"] if self.state == "ready" else T["muted"]))
        p.drawText(text_r, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(self.meta.name, Qt.TextElideMode.ElideRight,
                                              int(text_r.width())))

    def _paint_meter(self, p: QPainter, r: QRectF, accent: QColor):
        """A slim level meter up the card's left edge: how loud it is right now, with a
        peak mark. Its own colour, warming to amber then red near full scale."""
        if self.meter is None:
            return
        # from under the top corner to just above the footer (the hotkey badge)
        track = QRectF(r.left() + 4, r.top() + PAD_RADIUS, 3, r.height() - PAD_RADIUS - 28)
        p.setPen(Qt.PenStyle.NoPen)
        dim = QColor(accent)
        dim.setAlpha(40)
        p.setBrush(dim)
        p.drawRoundedRect(track, 1.5, 1.5)
        h = track.height() * self.meter
        if h >= 1.0:
            grad = QLinearGradient(0, track.bottom(), 0, track.top())
            grad.setColorAt(0.0, QColor(accent).lighter(115))
            grad.setColorAt(0.72, QColor(accent).lighter(130))
            grad.setColorAt(0.86, _METER_WARM)
            grad.setColorAt(1.0, _METER_HOT)
            if self.paused:
                p.setOpacity(0.45)
            p.setBrush(grad)
            p.drawRoundedRect(QRectF(track.left(), track.bottom() - h, track.width(), h),
                              1.5, 1.5)
            if self.meter_peak > self.meter + 0.02:
                y = track.bottom() - track.height() * self.meter_peak
                p.drawRect(QRectF(track.left(), y, track.width(), 1.5))
            p.setOpacity(1.0)

    def _paint_visualizer(self, p: QPainter, r: QRectF, accent: QColor):
        """Spectrum bars rising from the bottom, behind the text."""
        bands = self.bands
        if bands is None or not len(bands):
            return
        n = len(bands)
        area = r.adjusted(8, r.height() * 0.58, -8, -5)   # under the name, not through it
        gap = 2.0 if area.width() / n > 6 else 1.0
        bw = (area.width() - gap * (n - 1)) / n
        top, bottom = QColor(accent).lighter(135), QColor(accent)
        top.setAlpha(70 if self.paused else 150)
        bottom.setAlpha(15 if self.paused else 40)
        grad = QLinearGradient(0, area.top(), 0, area.bottom())
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, bottom)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        rad = min(bw / 2, 2.5)
        for i, lv in enumerate(bands):
            x = area.left() + i * (bw + gap)
            h = max(2.0, float(lv) * area.height())
            p.drawRoundedRect(QRectF(x, area.bottom() - h, bw, h), rad, rad)
        if self.peaks is not None:
            cap = QColor(accent).lighter(160)
            cap.setAlpha(70 if self.paused else 160)
            p.setBrush(cap)
            for i, pk in enumerate(self.peaks):
                x = area.left() + i * (bw + gap)
                y = area.bottom() - max(2.0, float(pk) * area.height()) - 4
                p.drawRoundedRect(QRectF(x, y, bw, 2), 1, 1)


class PadGrid(QWidget):
    reorder = Signal(str, int)   # sound id, new index
    files_dropped = Signal(list)
    image_dropped = Signal(str, str)   # sound id, picture file dropped on its pad
    laid_out = Signal()   # after each relayout: slack() may have changed
    HOW_TO = DROP_HINT = _("Drop sound files here")
    NO_MATCH = _("No sounds match the search\nor this category")
    DROP_HINT_HEIGHT = 110

    def __init__(self):
        super().__init__()
        self.pads: list[Pad] = []
        self.background_image = ""
        self.background_opacity = 0
        self.background_pad_height = 0
        self.pad_w = 150         # the size picked (Pad size); narrower only when it won't fit
        self.two_up = False      # the mini player: two smaller pads a row rather than one
        self.slim = False        # a tiny mini player: one-line rows instead of cards
        self.listed = False      # the list view (Sounds tab): one-line rows in columns
        self.row_size = "medium"   # ...and how big those rows are (LIST_ROW_H)
        self.grid = QGridLayout(self)
        self.grid.setSpacing(10)
        self.grid.setContentsMargins(4, 4, 4, 4)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.setAcceptDrops(True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)   # see event()
        # no sounds yet: Bun waits (sadly) above the how-to, and cheers up when
        # files are dragged over
        self.empty = QWidget()
        self.empty.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        ev = QVBoxLayout(self.empty)
        ev.setContentsMargins(0, 24, 0, 4)
        ev.setSpacing(12)
        self.bun = BunnyWidget(
            height=130, pad=16, sad=0.9,
            lines=(_("add a sound?"), _("pleeease?"), _("it's so quiet…"),
                   _("drop one on me!"), _("just one sound?"), _("I'm bored…")),
            hope_lines=(_("yes! drop it!"), _("ooh, for me?!")),
            joy_lines=(_("yay!!"), _("↑ Add sounds!"), _("hehe!")), pong=True, naps=True)
        ev.addWidget(self.bun, 0, Qt.AlignmentFlag.AlignHCenter)
        self.empty_text = QLabel(self.HOW_TO)
        # short lines: fits the mini player
        self.empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_text.setWordWrap(True)   # and wraps rather than losing both ends
        self.empty_text.setObjectName("empty")
        self.empty_text.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.empty_text.setStyleSheet("padding:8px 12px; background:transparent;")
        self.empty_text.setFixedHeight(self.DROP_HINT_HEIGHT)
        ev.addWidget(self.empty_text)
        self._cols = 0
        self._n_shown = 0        # pads in the grid now (drop_area)
        self._shape = None       # (columns, pad width) last laid out
        self._slack = 0          # pixels right of a full row (slack())
        self._placed = None      # (columns, the pads shown) in the grid now
        self._slots: dict[Pad, tuple[int, int]] = {}   # the pads in the grid: row, column

    def set_background(self, image: str, opacity: int):
        opacity = min(100, max(0, opacity))
        if (image, opacity) != (self.background_image, self.background_opacity):
            self.background_image, self.background_opacity = image, opacity
            self.update()

    def background_rect(self, size: QSize) -> QRectF:
        view = self.parentWidget()
        area = QRectF(0, -self.y(), self.width(),
                      view.height() if view else self.height())
        if size.isEmpty() or area.width() <= 0 or area.height() <= 0:
            return QRectF()
        return area

    def minimumSizeHint(self):
        # never wider than the scroll area around it: the pads fit themselves to its
        # width (relayout), so a narrower window can't leave them stuck wider than it
        # is, with a sideways scroll bar and the rest out of sight
        return QSize(0, super().minimumSizeHint().height())

    def sizeHint(self):
        return QSize(0, super().sizeHint().height())

    def set_pads(self, pads, layout: bool = True):
        """The pads, in order. `layout`: lay them out now (False: the caller filters
        them next, and that lays them out)."""
        keep = set(pads)   # (one gone from the list is taken out of the grid by _place)
        self._slots = {p: at for p, at in self._slots.items() if p in keep}
        self.pads = pads
        self._shape = self._placed = None
        if layout:
            self.relayout(force=True)

    def set_pad_width(self, w: int):
        self.pad_w = w
        self.relayout(force=True)

    def set_two_up(self, on: bool):
        if on != self.two_up:
            self.two_up = on
            self.relayout(force=True)

    def set_slim(self, on: bool):
        if on != self.slim:
            self.slim = on
            self._spacing()
            self.relayout(force=True)

    def set_listed(self, on: bool):
        if on != self.listed:
            self.listed = on
            self._spacing()
            self.relayout(force=True)

    def set_row_size(self, size: str):
        if size in LIST_ROW_H and size != self.row_size:
            self.row_size = size
            if self.listed:
                self.relayout(force=True)

    def _spacing(self):
        self.grid.setSpacing(4 if self.slim else 6 if self.listed else 10)

    def rows(self) -> bool:
        """Pads drawn as one-line rows: the list view, or a tiny mini player."""
        return self.slim or self.listed

    def pad_h(self, w: int) -> int:
        return self.background_pad_height or self.natural_pad_h(w)

    def natural_pad_h(self, w: int) -> int:
        # as tall as the picked size while a row only stretches or squeezes them (the
        # height followed the width: each row losing a pad as the window narrowed
        # jolted every row below); only pads squeezed past that (a narrow window, the
        # mini player) get shorter
        if self.slim:
            return SLIM_PAD_H
        if self.listed:
            return LIST_ROW_H[self.row_size]
        return pad_height(min(self.pad_w, round(w / PAD_SHRINK)))

    def fit_width(self, room: int, slim: bool | None = None) -> tuple[int, int]:
        """(columns, pad width) for `room` pixels: the picked size, but never wider than
        the room, and two a row in the mini player while they'd still be a usable size.
        Slim rows take the whole width, one a row."""
        if self.slim if slim is None else slim:
            return 1, max(1, room)
        if self.listed and slim is None:   # the mini player's rows take the whole width
            if self.two_up:
                return 1, max(1, room)
            sp = 6
            cols = max(1, (room + sp) // (LIST_ROW_W[self.row_size] + sp))
            return cols, max(1, (room - sp * (cols - 1)) // cols)
        sp = 10
        w = max(1, min(self.pad_w, room))
        if self.two_up and (room + sp) // (w + sp) < 2 and room - sp >= 2 * MINI_PAD_MIN_W:
            w = (room - sp) // 2
        # the picked size is roughly what they get: the pads stretch so the row ends at
        # the edge (a fixed size left a strip as wide as most of a pad on the right),
        # or take one more a row when that shrinks them by a fifth at most
        cols = max(1, (room + sp) // (w + sp))
        if (room - sp * cols) // (cols + 1) >= w * PAD_SHRINK:
            cols += 1
        return cols, max(1, (room - sp * (cols - 1)) // cols)

    def slack(self) -> int:
        """Pixels left over right of a full row (the width rarely splits evenly)."""
        return self._slack if self.pads else 0

    def row_height(self) -> int:
        """One row of pads as they're laid out now, margins included (0 with none)."""
        m = self.grid.contentsMargins()
        if not self.pads or self._shape is None:
            return 0
        return self.pad_h(self._shape[1]) + m.top() + m.bottom()

    def relayout(self, force=False):
        m = self.grid.contentsMargins()
        room = self.width() - m.left() - m.right()
        cols, w = self.fit_width(room)
        self._slack = max(0, room - cols * w - self.grid.horizontalSpacing() * (cols - 1))
        self.laid_out.emit()
        if (cols, w) == self._shape and not force:
            return
        self._shape = (cols, w)
        self._cols = cols
        # the grid switched off while the pads move: each show() / addWidget() into a
        # live layout laid the whole grid out again (85-145 ms clearing a search with
        # 600 pads); once at the end instead
        self.grid.setEnabled(False)
        try:
            self._place(cols, w)
        finally:
            self.grid.setEnabled(True)
            self.grid.activate()
            # Moving children only repaints the strips they expose. The drop hint
            # also moves (or disappears), including background below every pad:
            # repaint it with the completed layout so its old border/text is erased.
            self.update()

    def _place(self, cols: int, w: int):
        h = self.pad_h(w)
        for p in self.pads:
            if p.width() != w or p.height() != h:
                p.setFixedSize(w, h)
        shown = [p for p in self.pads if not p.property("filtered")]
        self._n_shown = len(shown)
        placed = (cols, tuple(map(id, shown)))
        if shown and placed == self._placed:
            return   # the same pads in the same columns: only their size changed
        self._placed = placed if shown else None
        want = {p: (i // cols, i % cols) for i, p in enumerate(shown)}
        # only the pads that move are taken out and put back, and only the ones whose
        # filter changed are shown or hidden: a category click redid all of them, even
        # the hundreds out of sight
        slots, grid = self._slots, self.grid
        for i in reversed(range(grid.count())):   # from the end: each take is cheap
            it = widget_at(grid, i)
            pad = it if isinstance(it, Pad) else None
            # (Bun's never wanted)
            if pad is None or pad not in want or slots.get(pad) != want[pad]:
                take_out(grid, i)
                if pad is not None:
                    slots.pop(pad, None)
        if not shown:
            # every pad filtered out showed nothing at all: Bun says why instead
            for p in self.pads:
                p.hide()
            self.empty_text.setText(self.NO_MATCH if self.pads else self.HOW_TO)
            # across the whole width, however wide that is now (a fixed width here kept
            # the grid as wide as the window once was: a shrunk window showed nothing),
            # halfway down the page rather than stuck to its top
            grid.setAlignment(Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(self.empty, 0, 0)
            self.empty.show()
            return
        grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.empty.hide()
        self.empty_text.setText(self.HOW_TO)
        for p, at in want.items():
            if p not in slots:
                # into the grid first: a new pad has no parent yet, and showing it then
                # flashed it up on the desktop as a little window of its own
                grid.addWidget(p, *at)
                slots[p] = at
        for p in self.pads:
            if p in want:
                if p.isHidden():
                    p.show()
            elif not p.isHidden():
                p.hide()

    def event(self, e):
        done = super().event(e)
        if e.type() in (QEvent.Type.Polish, QEvent.Type.StyleChange, QEvent.Type.ParentChange):
            # opaque: it paints the page colour behind itself (paintEvent), so a scroll
            # copies what's on screen and only the strip that came into view is drawn.
            # See-through, every pad in view was painted again on each wheel step. Qt
            # clears the flag when the scroll area adopts it and on each restyle (a
            # theme change), so it's set again after those
            self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        return done

    def paintEvent(self, e):
        # the same colour the page behind it shows; read on each paint, so a theme
        # change (theme.apply repaints every widget) follows
        p = QPainter(self)
        # no snap_to_pixels until the background is down: it's opaque (nothing is
        # cleared first), and the half-pixel nudge left a one-pixel strip of the old
        # picture at the edge of each repaint, lines behind the cards at 125 %
        # the window's faint glow, fixed to the pads (so a scroll can still copy
        # what's on screen): it lines up with the window at the top of the board
        win, view = self.window(), self.parentWidget()
        root = win.centralWidget() if isinstance(win, QMainWindow) else None
        if root is not None and view is not None:
            at = view.mapTo(root, QPoint(0, 0))
            theme.paint_window_bg(p, e.rect(), QPointF(-at.x(), -at.y()),
                                  root.width(), root.height())
        else:
            p.fillRect(e.rect(), QColor(theme.T["bg"]))
        if self.background_image and self.background_opacity:
            pm = thumbs.pixmap(self.background_image, waiter=self)
            if pm is not None and not pm.isNull():
                # Stretch the whole thumbnail across the visible board, with breathing
                # room beside the scrollbar. Keep it fixed while the cards scroll.
                target = self.background_rect(pm.size())
                clip = QPainterPath()
                clip.addRoundedRect(target, PAD_RADIUS, PAD_RADIUS)
                p.save()
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.setClipPath(clip)
                p.setOpacity(self.background_opacity / 100)
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                p.drawPixmap(target, pm, QRectF(pm.rect()))
                p.restore()
        snap_to_pixels(p)
        drop = self.drop_area()
        if drop is not None and drop.intersects(QRectF(e.rect())):
            # the empty room under the pads says what it's for, faintly
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(theme.T["border"]), 1.4)
            p.setPen(pen)
            p.drawRoundedRect(drop, PAD_RADIUS, PAD_RADIUS)
            if self._n_shown:
                p.setPen(QColor(theme.T["faint"]))
                p.drawText(drop, Qt.AlignmentFlag.AlignCenter, self.DROP_HINT)

    def drop_area(self) -> QRectF | None:
        """The same drop box below Bun on an empty board or below the last card row."""
        if not self.pads and not self.empty.isHidden():
            m = self.grid.contentsMargins()
            top = self.empty.y() + self.empty_text.y()
            return QRectF(m.left() + 2, top, self.width() - m.left() - m.right() - 4,
                          self.DROP_HINT_HEIGHT)
        if not self._n_shown or self._shape is None or self.rows():
            return None
        cols, w = self._shape
        m, sp = self.grid.contentsMargins(), self.grid.spacing()
        rows = -(-self._n_shown // cols)
        top = m.top() + rows * (self.pad_h(w) + sp) + 2
        room = self.height() - top - m.bottom() - 4
        if room < 90:
            return None
        # the full width, whatever the pad size: as wide as the pads' columns, it
        # jumped about as Pad size moved
        return QRectF(m.left() + 2, top, self.width() - m.left() - m.right() - 4,
                      min(room, self.DROP_HINT_HEIGHT))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.relayout()

    def pad_at(self, pos) -> Pad | None:
        return next((p for p in self.pads if p.isVisible() and p.geometry().contains(pos)),
                    None)

    def focus_step(self, pad: Pad, dx: int, dy: int):
        """Arrow keys on a pad: move the keyboard focus through the grid."""
        shown = [p for p in self.pads if not p.property("filtered")]
        if pad not in shown:
            return
        i = shown.index(pad) + dx + dy * max(1, self._cols)
        if 0 <= i < len(shown):
            shown[i].setFocus(Qt.FocusReason.TabFocusReason)
            view = self.parentWidget()
            area = view.parentWidget() if view is not None else None
            if isinstance(area, QScrollArea):
                area.ensureWidgetVisible(shown[i])

    def _drop_target(self, pos) -> int:
        """Where a dragged pad dropped at ``pos`` goes: the pad under it, else (a gap
        between pads, the margin) the nearest one; below the last row, the end."""
        shown = [(i, p.geometry()) for i, p in enumerate(self.pads) if p.isVisible()]
        if not shown or pos.y() > max(r.bottom() for _i, r in shown):
            return len(self.pads) - 1

        def dist(r) -> int:
            dx = max(r.left() - pos.x(), 0, pos.x() - r.right())
            dy = max(r.top() - pos.y(), 0, pos.y() - r.bottom())
            return dx * dx + dy * dy
        return min(shown, key=lambda ir: dist(ir[1]))[0]

    def dragEnterEvent(self, e):
        md = e.mimeData()
        if md.hasFormat(PAD_MIME) or md.hasUrls():
            e.acceptProposedAction()
            if md.hasUrls() and not self.pads:
                self.bun.hope(True)

    def dragMoveEvent(self, e):
        md = e.mimeData()
        if md.hasFormat(PAD_MIME) or md.hasUrls():
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.bun.hope(False)
        super().dragLeaveEvent(e)

    def dropEvent(self, e):
        self.bun.hope(False)
        md = e.mimeData()
        if md.hasFormat(PAD_MIME):
            sid = bytes(md.data(PAD_MIME)).decode()
            pos = e.position().toPoint()
            over = self.pad_at(pos)
            if over is None or over.meta.id != sid:   # back on itself: nothing moved
                self.reorder.emit(sid, self._drop_target(pos))
            e.acceptProposedAction()
        elif md.hasUrls():
            files = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
            pad = self.pad_at(e.position().toPoint())
            if pad is not None and len(files) == 1 and thumbs.is_image(files[0]):
                self.image_dropped.emit(pad.meta.id, files[0])
                e.acceptProposedAction()
                return
            self.files_dropped.emit(expand_dropped(files))
            e.acceptProposedAction()


def expand_dropped(files: list[str]) -> list[str]:
    """Files dropped from Explorer, with folders opened up into the sound files (and zips)
    in them. An unzipped backup / sound pack folder is kept whole (see backup.py)."""
    expanded = []
    for f in files:
        pth = Path(f)
        if pth.is_dir() and any((pth / n).is_file() for n in ("onionboard.json", "sound.json")):
            expanded.append(f)
        elif pth.is_dir():
            expanded += [str(x) for x in sorted(pth.rglob("*"))
                         if x.is_file() and x.suffix.lower() in AUDIO_EXTS | {".zip"}]
        else:
            expanded.append(f)
    return expanded
