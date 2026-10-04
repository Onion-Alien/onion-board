"""Hand-painted widgets: level meter, EQ curve, seek slider, sound pads and their grid."""
from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import (QEvent, QMimeData, QObject, QPoint, QPointF, QRectF, QSize, Qt,
                            QTimer, QVariantAnimation, Signal)
from PySide6.QtGui import (QColor, QDrag, QFont, QFontMetrics, QLinearGradient, QPainter,
                           QPainterPath, QPen)
from PySide6.QtWidgets import (QAbstractButton, QGridLayout, QLabel, QScrollArea, QSlider,
                               QStackedWidget, QStyle, QTabWidget, QVBoxLayout, QWidget)

from soundboard import midi, theme, thumbs
from soundboard.eq import MAX_DB as EQ_MAX_DB
from soundboard.eq import response_db as eq_response
from soundboard.engine import SR
from soundboard.library import AUDIO_EXTS, SoundMeta
from soundboard.settings import pretty_key
from soundboard.ui.bunnywidget import BunnyWidget

PAD_MIME = "application/x-soundboard-pad"


class Meter(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.level = 0.0
        self._hot = False
        self._drawn = None        # (bar width in px, colour) as last painted
        self.setFixedHeight(8)
        self.setAccessibleName("Level meter")

    @property
    def hot(self) -> bool:
        return self._hot

    @hot.setter
    def hot(self, on: bool):
        self._hot = bool(on)
        self.update()

    def _bar(self) -> tuple[float, str]:
        db = 20 * np.log10(max(self.level, 1e-5))
        frac = float(np.clip((db + 50) / 50, 0, 1))
        col = "#13ce66" if db < -9 else "#ffb020" if db < -2 else "#ff4d4f"
        return frac, "#ff4d4f" if self._hot else col

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
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        p.setPen(Qt.NoPen)
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
        self.setToolTip("Double-click to reset")
        self.setAccessibleName("EQ curve")
        self._freqs = np.geomspace(30, 18000, 160)

    def set_gains(self, gains, on):
        self.gains, self.on = list(gains), on
        self.update()

    def mouseDoubleClickEvent(self, e):
        self.reset.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(Qt.NoPen)
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
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        if not self.on:   # on a little plate, so the flat line doesn't strike it through
            fm = p.fontMetrics()
            plate = QRectF(0, 0, fm.horizontalAdvance("EQ off") + 14, fm.height() + 4)
            plate.moveCenter(r.center())
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.T["bg"]))
            p.drawRoundedRect(plate, plate.height() / 2, plate.height() / 2)
            p.setPen(QColor(theme.T["muted"]))
            p.drawText(plate, Qt.AlignCenter, "EQ off")


class SeekSlider(QSlider):
    """Slider that jumps straight to where you click (then drags from there)."""

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.setValue(QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(), int(e.position().x()), self.width()))
        super().mousePressEvent(e)


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
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        rad = r.height() / 2
        p.setPen(Qt.NoPen)
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
                                     Qt.FindDirectChildrenOnly)
        self._last = None
        tabs.installEventFilter(self)

    def _state(self):
        t, bar = self._tabs, self._tabs.tabBar()
        corners = tuple(w.sizeHint() if w is not None and w.isVisible() else None
                        for w in (t.cornerWidget(Qt.TopLeftCorner),
                                  t.cornerWidget(Qt.TopRightCorner)))
        return (t.size(), t.isVisible(), t.count(), t.currentIndex(), bar.sizeHint(),
                bar.minimumSizeHint(), corners,
                self._stack.minimumSizeHint() if self._stack is not None else None)

    def eventFilter(self, obj, ev):
        if obj is self._tabs and ev.type() == QEvent.LayoutRequest:
            state = self._state()
            if state == self._last:
                return True
            self._last = state
        return False


def spectrum(data: np.ndarray, frac: float, n: int) -> np.ndarray:
    """`n` log-spaced band levels (0..1) of int16/float (m, 2) audio around position
    `frac` (0..1): what a pad's visualizer shows. Cheap: one 2048-point FFT."""
    if data is None or not len(data) or n <= 0:
        return np.zeros(max(n, 0), np.float32)
    pos = int(min(max(frac, 0.0), 1.0) * len(data))
    seg = data[pos:pos + FFT_N]
    if len(seg) < FFT_N:
        seg = np.concatenate([seg, np.zeros((FFT_N - len(seg), 2), seg.dtype)])
    mono = seg.mean(axis=1, dtype=np.float32)
    if data.dtype == np.int16:
        mono /= 32768.0
    mag = np.abs(np.fft.rfft(mono * _HANN)) * (4.0 / FFT_N)   # full-scale sine ~ 1
    edges = np.geomspace(50, 14000, n + 1)
    idx = np.clip(np.searchsorted(_FREQS, edges), 1, len(mag) - 1)
    out = np.empty(n, np.float32)
    for i in range(n):
        a, b = idx[i], max(idx[i + 1], idx[i] + 1)
        out[i] = np.sqrt(np.mean(mag[a:b] ** 2))
    db = 20 * np.log10(out + 1e-9) + np.linspace(0, 14, n)   # music falls off up high
    return np.clip((db + 62) / 52, 0.0, 1.0).astype(np.float32)


MINI_PAD_MIN_W = 96   # the mini player's two-a-row pads get no smaller than this


SLIM_PAD_H = 30      # a pad as a one-line row: the mini player when it's too small for cards


def pad_height(width: int) -> int:
    return int(width * 0.62)


class Pad(QAbstractButton):
    """One sound's button, painted by hand. It's a QAbstractButton so screen readers
    see a button with the sound's name, and it works from the keyboard: Tab / arrows
    to move, Enter or Space to play, Ctrl+Space to pick, the Menu key for its menu."""
    activated = Signal(str)     # play it (a double-click, Enter, a screen reader's press)
    chosen = Signal(str)        # a single click: select it (transport bar) without playing
    pick = Signal(str, bool)    # Ctrl+click / Ctrl+Space (False) or Shift+click (True)
    space = Signal(str)         # Space: pause / resume it if it's playing, else play it
    menu = Signal(str, QPoint)
    step = Signal(object, int, int)   # arrow key: this pad, columns, rows to move focus
    single_click = False        # Settings: a click plays it (activated) instead of selecting

    def __init__(self, meta: SoundMeta, width: int):
        super().__init__()
        self.meta = meta
        self.progress = None     # None = not playing
        self.paused = False
        self.bands = None        # visualizer levels (0..1) while playing
        self.peaks = None        # the little caps that fall slowly
        self.selected = False    # the sound in the transport bar
        self.picked = False      # one of several picked for a batch change (ui.padbatch)
        self.state = "loading"   # loading | ready | error
        self.error = ""
        self.hover = False
        self._hover_k = 0.0      # 0..1, eased in and out (the card lights up smoothly)
        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(140)
        self._hover_anim.valueChanged.connect(self._on_hover_k)
        self._down = False       # pressed: the card sinks a little
        self._play_t = None      # when it started playing (the flash on start)
        self._press = None
        self._kbd_focus = False  # focus came from the keyboard: draw the focus ring
        self._described = None
        self._name_fit = None    # (what it was fitted to, how) - see _fit_name
        self.setFixedSize(width, pad_height(width))
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)
        self.setFocusPolicy(Qt.StrongFocus)
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
            bits.append("paused" if self.paused else "playing")
        if self.picked:
            bits.append("selected")
        if self.state in ("loading", "rendering"):
            bits.append("loading")
        elif self.state == "error":
            bits.append("can't load the file")
        else:
            bits.append(f"{m.duration:.1f} seconds")
        if m.hotkey:
            bits.append(f"hotkey {pretty_key(m.hotkey)}")
        if m.loop:
            bits.append("loops")
        if m.mode in ("overlap", "toggle", "solo"):
            bits.append({"overlap": "presses overlap", "toggle": "press again stops",
                         "solo": "stops the other sounds"}[m.mode])
        if m.hold:
            bits.append("plays while its hotkey is held")
        if m.fx:
            bits.append("effects")
        if m.tags:
            bits.append("in " + ", ".join(m.tags))
        desc = ", ".join(bits)
        if (m.name, desc) != self._described:
            self._described = (m.name, desc)
            self.setText(m.name.replace("&", "&&"))   # else "R&B" claims Alt+B
            self.setAccessibleName(m.name)
            self.setAccessibleDescription(desc)

    def focusInEvent(self, e):
        self._kbd_focus = e.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason,
                                         Qt.ShortcutFocusReason, Qt.OtherFocusReason)
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self._kbd_focus = False
        super().focusOutEvent(e)

    def keyPressEvent(self, e):
        k, mods = e.key(), e.modifiers()
        arrows = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, -1),
                  Qt.Key_Down: (0, 1)}
        if k == Qt.Key_Space and mods & Qt.ControlModifier:
            self.pick.emit(self.meta.id, False)
        elif k == Qt.Key_Space and not mods:
            if not e.isAutoRepeat():
                self.space.emit(self.meta.id)
        elif k in (Qt.Key_Return, Qt.Key_Enter):
            self.activated.emit(self.meta.id)
        elif k == Qt.Key_Menu or (k == Qt.Key_F10 and mods & Qt.ShiftModifier):
            self.menu.emit(self.meta.id, self.mapToGlobal(self.rect().center()))
        elif k in arrows and not mods & (Qt.ControlModifier | Qt.AltModifier):
            self.step.emit(self, *arrows[k])
        else:
            super().keyPressEvent(e)

    def _fit_name(self, room: QRectF) -> tuple[QFont, Qt.AlignmentFlag, str]:
        """The name's font, flags and text so it fits the pad: wrapped over two lines,
        then a size smaller, then on one line cut short with "…" (small pads cut
        words in half and lost the line below)."""
        key = (self.meta.name, room.width(), room.height(), self.font().key())
        if self._name_fit is None or self._name_fit[0] != key:
            name = self.meta.name
            wrap = Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap
            box = room.toRect()
            f = QFont(self.font())
            f.setBold(True)
            for pt in (10.5, 9.0):
                f.setPointSizeF(pt)
                fm = QFontMetrics(f)
                longest = max(name.split(), key=len, default="")   # no word cut in half
                if (fm.boundingRect(box, wrap, name).height() <= box.height()
                        and fm.horizontalAdvance(longest) <= box.width()):
                    self._name_fit = (key, (f, wrap, name))
                    break
            else:
                one = Qt.AlignLeft | Qt.AlignVCenter
                self._name_fit = (key, (f, one, fm.elidedText(name, Qt.ElideRight,
                                                              box.width())))
        f, flags, name = self._name_fit[1]
        return QFont(f), flags, name   # a copy: the footer changes the one it's given

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
        self.bands = np.maximum(levels, self.bands * 0.78)
        self.peaks = np.maximum(self.bands, self.peaks - 0.025)

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

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = e.position().toPoint()
            self._down = True
            self.update()
        elif e.button() == Qt.RightButton:
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
            drag.setPixmap(self.grab().scaled(self.width() // 2, self.height() // 2,
                                              Qt.KeepAspectRatio, Qt.SmoothTransformation))
            drag.exec(Qt.MoveAction)

    def mouseReleaseEvent(self, e):
        if self._down:
            self._down = False
            self.update()
        if e.button() == Qt.LeftButton and self._press is not None:
            self._press = None
            mods = e.modifiers()
            if mods & Qt.ShiftModifier:
                self.pick.emit(self.meta.id, True)
            elif mods & Qt.ControlModifier:
                self.pick.emit(self.meta.id, False)
            elif Pad.single_click:
                self.activated.emit(self.meta.id)
            else:
                self.chosen.emit(self.meta.id)

    def mouseDoubleClickEvent(self, e):
        if Pad.single_click:   # a quick second click is just another click
            self.mousePressEvent(e)
            return
        if e.button() == Qt.LeftButton and not e.modifiers() & (Qt.ShiftModifier |
                                                                  Qt.ControlModifier):
            self._press = None
            self.activated.emit(self.meta.id)

    def paintEvent(self, e):
        self.describe()
        if self.height() <= SLIM_PAD_H:
            self._paint_slim()
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        if self._down:
            r.adjust(1.5, 1.5, -1.5, -1.5)
        accent = QColor(self.meta.color)
        T = theme.T
        lo, hi, k = QColor(T["card"]), QColor(T["card_hi"]), self._hover_k
        base = QColor.fromRgbF(lo.redF() + (hi.redF() - lo.redF()) * k,
                               lo.greenF() + (hi.greenF() - lo.greenF()) * k,
                               lo.blueF() + (hi.blueF() - lo.blueF()) * k)
        if self._down:
            base = base.darker(108)
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        p.fillPath(path, base)
        pic = thumbs.pixmap(self.meta.image)
        playing = self.progress is not None
        now = time.monotonic()
        if not playing:
            self._play_t = None
        elif self._play_t is None:
            self._play_t = now
        p.save()
        p.setClipPath(path)
        if pic is not None:
            self._paint_picture(p, r, pic)
        if playing:
            flash = 1 - (now - self._play_t) / 0.35
            if flash > 0:   # a quick wash of its colour as it starts
                wash = QColor(accent)
                wash.setAlpha(int(90 * flash))
                p.fillPath(path, wash)
            self._paint_visualizer(p, r, accent)
            # progress: a thin accent line along the bottom edge
            p.fillRect(QRectF(r.left(), r.bottom() - 3, r.width() * self.progress, 3), accent)
        p.restore()
        p.setBrush(Qt.NoBrush)
        if playing:
            glow = QColor(accent)   # breathes while it plays
            glow.setAlpha(60 if self.paused else int(105 + 35 * math.sin(now * 5)))
            p.setPen(QPen(glow, 6))
            p.drawPath(path)
            pen = QPen(accent, 2.2)
            if self.paused:
                pen.setStyle(Qt.DashLine)
            p.setPen(pen)
        elif self.picked:
            p.setPen(QPen(QColor(T["accent"]), 2.4))
        elif self.selected:
            p.setPen(QPen(QColor(T["border_hi"]), 1.6))
        else:
            p.setPen(QPen(QColor(T["border"]), 1.2))
        p.drawPath(path)
        if self.picked:   # a tick in the corner, so it reads as picked while playing too
            c = QRectF(r.right() - 24, r.top() + 6, 18, 18)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(T["accent"]))
            p.drawEllipse(c)
            tick = QPen(QColor("#ffffff"), 2.2)
            tick.setCapStyle(Qt.RoundCap)
            p.setPen(tick)
            p.drawPolyline([QPointF(c.left() + 5, c.center().y()),
                            QPointF(c.left() + 8, c.bottom() - 5),
                            QPointF(c.right() - 4, c.top() + 5)])
            p.setBrush(Qt.NoBrush)
        if self.hasFocus() and self._kbd_focus:
            p.setPen(QPen(QColor(T["text_hi"]), 1.4, Qt.DashLine))
            p.drawRoundedRect(r.adjusted(3, 3, -3, -3), 10, 10)
        # accent bar
        p.setPen(Qt.NoPen)
        p.setBrush(accent)
        p.drawRoundedRect(QRectF(r.left() + 10, r.top() + 10, 22, 4), 2, 2)
        on_pic = pic is not None
        # name
        text_r = r.adjusted(10, 20, -10, -24)
        f, flags, name = self._fit_name(text_r)
        p.setFont(f)
        if on_pic:   # a soft shadow keeps it readable on any picture
            p.setPen(QColor(0, 0, 0, 200))
            p.drawText(text_r.translated(1, 1), flags, name)
            p.setPen(QColor("#ffffff") if self.state == "ready" else QColor(255, 255, 255, 170))
        else:
            p.setPen(QColor(T["text_hi"] if self.state == "ready" else T["muted"]))
        p.drawText(text_r, flags, name)
        muted = QColor(255, 255, 255, 200) if on_pic else QColor(T["muted"])
        # footer: hotkey + duration / state
        f.setBold(False)
        f.setPointSizeF(8.5)
        p.setFont(f)
        foot = r.adjusted(10, r.height() - 24, -10, -6)
        if self.state in ("loading", "rendering"):
            p.setPen(muted)
            p.drawText(foot, Qt.AlignLeft | Qt.AlignVCenter,
                       "applying effects…" if self.state == "rendering" else "loading…")
        elif self.state == "error":
            p.setPen(QColor("#ff6b6b"))
            p.drawText(foot, Qt.AlignLeft | Qt.AlignVCenter, "can't load file")
        else:
            flags = ("FX " if self.meta.fx else "") + \
                ("⟳ " if self.meta.loop else "") + \
                {"overlap": "⧉ ", "toggle": "⏯ ", "solo": "◉ "}.get(self.meta.mode, "") + \
                ("hold " if self.meta.hold else "")
            p.setPen(muted)
            right = "❚❚ paused" if self.paused else f"{flags}{self.meta.duration:.1f}s"
            p.drawText(foot, Qt.AlignRight | Qt.AlignVCenter, right)
            hk = self.meta.hotkey and (midi.short(self.meta.hotkey)
                                       if midi.is_midi(self.meta.hotkey)
                                       else pretty_key(self.meta.hotkey))
            fm = p.fontMetrics()
            # a cut-off key ("Ctrl+Al…") says nothing: no badge on a pad too narrow
            if hk and fm.horizontalAdvance(hk) + 12 <= foot.width() * 0.68:
                w = fm.horizontalAdvance(hk) + 12
                badge = QRectF(foot.left(), foot.top() + 1, w, foot.height() - 2)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(T["badge"]))
                p.drawRoundedRect(badge, 5, 5)
                p.setPen(QColor(T["badge_text"]))
                p.drawText(badge, Qt.AlignCenter, hk)


    def _paint_slim(self):
        """A one-line row: accent dot, name, duration; progress along the bottom."""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
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
            p.fillRect(QRectF(r.left(), r.bottom() - 2, r.width() * self.progress, 2), accent)
            p.restore()
        if playing:
            pen = QPen(accent, 1.8)
            if self.paused:
                pen.setStyle(Qt.DashLine)
        elif self.picked:
            pen = QPen(QColor(T["accent"]), 2)
        elif self.selected:
            pen = QPen(QColor(T["border_hi"]), 1.4)
        else:
            pen = QPen(QColor(T["border"]), 1)
        p.setPen(pen)
        p.drawPath(path)
        if self.hasFocus() and self._kbd_focus:
            p.setPen(QPen(QColor(T["text_hi"]), 1.2, Qt.DashLine))
            p.drawRoundedRect(r.adjusted(2, 2, -2, -2), 5, 5)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(T["accent"]) if self.picked else accent)
        p.drawEllipse(QRectF(r.left() + 9, r.center().y() - 4, 8, 8))
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        p.setFont(f)
        fm = p.fontMetrics()
        if self.state in ("loading", "rendering"):
            right, rc = ("applying…" if self.state == "rendering" else "loading…"), T["muted"]
        elif self.state == "error":
            right, rc = "can't load", "#ff6b6b"
        else:
            right = "❚❚" if self.paused else f"{self.meta.duration:.1f}s"
            rc = T["muted"]
        rw = fm.horizontalAdvance(right) + 4
        p.setPen(QColor(rc))
        p.drawText(r.adjusted(0, 0, -9, 0), Qt.AlignRight | Qt.AlignVCenter, right)
        f.setBold(True)
        p.setFont(f)
        text_r = r.adjusted(24, 0, -14 - rw, 0)
        p.setPen(QColor(T["text_hi"] if self.state == "ready" else T["muted"]))
        p.drawText(text_r, Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(self.meta.name, Qt.ElideRight,
                                              int(text_r.width())))

    def _paint_picture(self, p: QPainter, r: QRectF, pic):
        """The picture, cropped to fill the pad, darkened towards the bottom for the text."""
        dpr = pic.devicePixelRatio() or 1.0
        pw, ph = pic.width() / dpr, pic.height() / dpr
        scale = max(r.width() / pw, r.height() / ph)
        w, h = pw * scale, ph * scale
        p.drawPixmap(QRectF(r.center().x() - w / 2, r.center().y() - h / 2, w, h), pic,
                     QRectF(pic.rect()))
        shade = QLinearGradient(r.topLeft(), r.bottomLeft())
        shade.setColorAt(0.0, QColor(0, 0, 0, 70 if self.hover else 100))
        shade.setColorAt(0.55, QColor(0, 0, 0, 120 if self.hover else 150))
        shade.setColorAt(1.0, QColor(0, 0, 0, 205))
        p.fillRect(r, shade)

    def _paint_visualizer(self, p: QPainter, r: QRectF, accent: QColor):
        """Spectrum bars rising from the bottom, behind the text."""
        bands = self.bands
        if bands is None or not len(bands):
            return
        n = len(bands)
        area = r.adjusted(8, r.height() * 0.28, -8, -5)
        gap = 2.0 if area.width() / n > 6 else 1.0
        bw = (area.width() - gap * (n - 1)) / n
        top, bottom = QColor(accent).lighter(135), QColor(accent)
        top.setAlpha(120 if self.paused else 235)
        bottom.setAlpha(25 if self.paused else 60)
        grad = QLinearGradient(0, area.top(), 0, area.bottom())
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, bottom)
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        rad = min(bw / 2, 2.5)
        for i, lv in enumerate(bands):
            x = area.left() + i * (bw + gap)
            h = max(2.0, float(lv) * area.height())
            p.drawRoundedRect(QRectF(x, area.bottom() - h, bw, h), rad, rad)
        if self.peaks is not None:
            cap = QColor(accent).lighter(160)
            cap.setAlpha(110 if self.paused else 230)
            p.setBrush(cap)
            for i, pk in enumerate(self.peaks):
                x = area.left() + i * (bw + gap)
                y = area.bottom() - max(2.0, float(pk) * area.height()) - 4
                p.drawRoundedRect(QRectF(x, y, bw, 2), 1, 1)


class PadGrid(QWidget):
    reorder = Signal(str, int)   # sound id, new index
    files_dropped = Signal(list)
    image_dropped = Signal(str, str)   # sound id, picture file dropped on its pad
    HOW_TO = ("Drop sound files here\nor click  ＋ Add sounds\n\n"
              "mp3 · wav · ogg · flac\nm4a · even video files")
    NO_MATCH = "No sounds match the search\nor this category"

    def __init__(self):
        super().__init__()
        self.pads: list[Pad] = []
        self.pad_w = 150         # the size picked (Pad size); narrower only when it won't fit
        self.two_up = False      # the mini player: two smaller pads a row rather than one
        self.slim = False        # a tiny mini player: one-line rows instead of cards
        self.grid = QGridLayout(self)
        self.grid.setSpacing(10)
        self.grid.setContentsMargins(4, 4, 4, 4)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.setAcceptDrops(True)
        # no sounds yet: Bun waits (sadly) above the how-to, and cheers up when
        # files are dragged over
        self.empty = QWidget()
        ev = QVBoxLayout(self.empty)
        ev.setContentsMargins(0, 24, 0, 0)
        ev.setSpacing(0)
        self.bun = BunnyWidget(
            height=96, pad=16, sad=0.9,
            lines=("add a sound?", "pleeease?", "it's so quiet…", "drop one on me!",
                   "just one sound?", "I'm bored…"),
            hope_lines=("yes! drop it!", "ooh, for me?!"),
            joy_lines=("yay!!", "↑ Add sounds!", "hehe!"))
        self.bun.setToolTip("Bun is waiting for some sounds")
        ev.addWidget(self.bun, 0, Qt.AlignHCenter)
        self.empty_text = QLabel(self.HOW_TO)
        self.empty_text.setAlignment(Qt.AlignCenter)   # short lines: fits the mini player
        self.empty_text.setWordWrap(True)   # and wraps rather than losing both ends
        self.empty_text.setObjectName("empty")
        ev.addWidget(self.empty_text)
        self._cols = 0
        self._shape = None       # (columns, pad width) last laid out

    def minimumSizeHint(self):
        # never wider than the scroll area around it: the pads fit themselves to its
        # width (relayout), so a narrower window can't leave them stuck wider than it
        # is, with a sideways scroll bar and the rest out of sight
        return QSize(0, super().minimumSizeHint().height())

    def sizeHint(self):
        return QSize(0, super().sizeHint().height())

    def set_pads(self, pads):
        self.pads = pads
        self._shape = None
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
            self.grid.setSpacing(4 if on else 10)
            self.relayout(force=True)

    def pad_h(self, w: int) -> int:
        return SLIM_PAD_H if self.slim else pad_height(w)

    def fit_width(self, room: int, slim: bool | None = None) -> tuple[int, int]:
        """(columns, pad width) for `room` pixels: the picked size, but never wider than
        the room, and two a row in the mini player while they'd still be a usable size.
        Slim rows take the whole width, one a row."""
        if self.slim if slim is None else slim:
            return 1, max(1, room)
        sp = 10
        w = max(1, min(self.pad_w, room))
        if self.two_up and (room + sp) // (w + sp) < 2 and room - sp >= 2 * MINI_PAD_MIN_W:
            w = (room - sp) // 2
        return max(1, (room + sp) // (w + sp)), w

    def row_height(self) -> int:
        """One row of pads as they're laid out now, margins included (0 with none)."""
        m = self.grid.contentsMargins()
        if not self.pads or self._shape is None:
            return 0
        return self.pad_h(self._shape[1]) + m.top() + m.bottom()

    def relayout(self, force=False):
        m = self.grid.contentsMargins()
        cols, w = self.fit_width(self.width() - m.left() - m.right())
        if (cols, w) == self._shape and not force:
            return
        self._shape = (cols, w)
        self._cols = cols
        for p in self.pads:
            if p.width() != w or p.height() != self.pad_h(w):
                p.setFixedSize(w, self.pad_h(w))
        while self.grid.count():
            it = self.grid.takeAt(0)
            if it.widget() and it.widget() is not self.empty:
                it.widget().setParent(self)
        shown = [p for p in self.pads if not p.property("filtered")]
        if not shown:
            # every pad filtered out showed nothing at all: Bun says why instead
            for p in self.pads:
                p.hide()
            self.empty_text.setText(self.NO_MATCH if self.pads else self.HOW_TO)
            # across the whole width, however wide that is now (a fixed width here kept
            # the grid as wide as the window once was: a shrunk window showed nothing)
            self.grid.setAlignment(Qt.AlignTop)
            self.grid.addWidget(self.empty, 0, 0)
            self.empty.show()
            return
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.empty.hide()
        self.empty_text.setText(self.HOW_TO)
        i = 0
        for p in self.pads:
            if p.property("filtered"):
                p.hide()
                continue
            # into the grid first: a new pad has no parent yet, and showing it then
            # flashed it up on the desktop as a little window of its own
            self.grid.addWidget(p, i // cols, i % cols)
            p.show()
            i += 1

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
            shown[i].setFocus(Qt.TabFocusReason)
            area = self.parentWidget() and self.parentWidget().parentWidget()
            if isinstance(area, QScrollArea):
                area.ensureWidgetVisible(shown[i])

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
            target = len(self.pads) - 1
            for i, p in enumerate(self.pads):
                if p.isVisible() and p.geometry().contains(pos):
                    target = i
                    break
            self.reorder.emit(sid, target)
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
