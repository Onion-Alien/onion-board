"""Soundboard — gaming soundboard with virtual-mic output, mic passthrough and test mode."""
from __future__ import annotations

__version__ = "0.1.0"

import ctypes
import sys
import threading
import subprocess
import time
from pathlib import Path

import keyboard
import numpy as np
import sounddevice as sd
from PySide6.QtCore import QEvent, QMimeData, QObject, QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDrag, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractScrollArea, QAbstractSlider, QAbstractSpinBox,
                               QApplication, QScrollBar, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton,
                               QScrollArea, QSlider, QSpinBox, QStyle, QVBoxLayout,
                               QWidget)

import engine as eng
from engine import SR, Engine
from library import AUDIO_EXTS, PAD_COLORS, Config, SoundMeta, decode, delete_file, import_file
from testcheck import analyze as analyze_output, summary_html
from eq import BAND_LABELS as EQ_LABELS, MAX_DB as EQ_MAX_DB, PRESETS as EQ_PRESETS
from eq import response_db as eq_response

PAD_MIME = "application/x-soundboard-pad"


# =========================================================================== hotkeys

class Hotkeys(QObject):
    fired = Signal(str)          # sound id, or "__stop__"
    captured = Signal(str)

    def __init__(self):
        super().__init__()
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def register(self, mapping: dict[str, str]):
        """mapping: hotkey combo -> action id."""
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:  # noqa: BLE001
            pass
        for combo, action in mapping.items():
            if not combo:
                continue
            try:
                keyboard.add_hotkey(combo, self._trigger, args=(action,), suppress=False)
            except Exception:  # noqa: BLE001
                pass

    def _trigger(self, action):
        # key auto-repeat sends events every ~30ms; only fire on a fresh press
        now = time.monotonic()
        with self._lock:
            last = self._last.get(action, 0.0)
            self._last[action] = now
        if now - last > 0.25:
            self.fired.emit(action)

    def capture(self):
        def run():
            try:
                keyboard.unhook_all_hotkeys()
            except Exception:  # noqa: BLE001
                pass
            try:
                combo = keyboard.read_hotkey(suppress=False)
            except Exception:  # noqa: BLE001
                combo = ""
            self.captured.emit(combo)
        threading.Thread(target=run, daemon=True).start()


def is_virtual_cable(name: str) -> bool:
    return eng.is_virtual(name)


def pretty_key(combo: str) -> str:
    if not combo:
        return ""
    return "+".join(p.strip().title() if len(p.strip()) > 1 else p.strip().upper()
                    for p in combo.split("+"))


class HotkeyDialog(QDialog):
    def __init__(self, hotkeys: Hotkeys, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Set hotkey")
        self.result_combo = None
        lay = QVBoxLayout(self)
        t = QLabel("Press the key or combo you want…")
        t.setStyleSheet("font-size:16px; font-weight:600;")
        lay.addWidget(t)
        lay.addWidget(QLabel("Works globally, even while in-game.  Esc = cancel."))
        self.setMinimumWidth(340)
        hotkeys.captured.connect(self._got)
        self._hk = hotkeys
        hotkeys.capture()

    def _got(self, combo):
        try:
            self._hk.captured.disconnect(self._got)
        except (RuntimeError, TypeError):
            pass
        if combo and combo.lower() not in ("esc", "escape"):
            self.result_combo = combo
            self.accept()
        else:
            self.reject()


# =========================================================================== widgets

class Meter(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.level = 0.0
        self.hot = False
        self.setFixedHeight(8)

    def set_level(self, v):
        self.level = v
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#1b1d26"))
        p.drawRoundedRect(r, 4, 4)
        db = 20 * np.log10(max(self.level, 1e-5))
        frac = float(np.clip((db + 50) / 50, 0, 1))
        if frac > 0:
            col = "#13ce66" if db < -9 else "#ffb020" if db < -2 else "#ff4d4f"
            if self.hot:
                col = "#ff4d4f"
            p.setBrush(QColor(col))
            p.drawRoundedRect(QRectF(0, 0, r.width() * frac, r.height()), 4, 4)


class NoWheelChanges(QObject):
    """Scrolling over a dropdown / slider / number box scrolls the page instead of
    changing the value. Values only change by clicking or dragging."""

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Wheel and isinstance(
                obj, (QComboBox, QAbstractSpinBox, QAbstractSlider)) \
                and not isinstance(obj, QScrollBar):
            w = obj.parentWidget()
            while w is not None and not isinstance(w, QAbstractScrollArea):
                w = w.parentWidget()
            if w is not None:
                QApplication.sendEvent(w.verticalScrollBar(), ev)
            return True
        return False


class EqCurve(QWidget):
    """Draws the EQ's actual frequency response. Double-click resets to flat."""
    reset = Signal()

    def __init__(self):
        super().__init__()
        self.setFixedHeight(70)
        self.gains = [0.0] * 7
        self.on = False
        self.setToolTip("Double-click to reset")
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
        p.setBrush(QColor("#15171f"))
        p.drawRoundedRect(r, 8, 8)
        mid = r.center().y()
        p.setPen(QPen(QColor("#2a2e3d"), 1))
        p.drawLine(int(r.left() + 6), int(mid), int(r.right() - 6), int(mid))
        db = eq_response(self.gains, self._freqs)
        scale = (r.height() / 2 - 6) / EQ_MAX_DB
        path = QPainterPath()
        n = len(db)
        for i, d in enumerate(db):
            x = r.left() + 6 + (r.width() - 12) * i / (n - 1)
            y = mid - float(np.clip(d, -EQ_MAX_DB - 3, EQ_MAX_DB + 3)) * scale
            path.moveTo(x, y) if i == 0 else path.lineTo(x, y)
        col = QColor("#7c5cff" if self.on else "#4a5068")
        p.setPen(QPen(col, 2.2))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        if not self.on:
            p.setPen(QColor("#6b7189"))
            p.drawText(r, Qt.AlignCenter, "EQ off")


class SeekSlider(QSlider):
    """Slider that jumps straight to where you click (then drags from there)."""

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.setValue(QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(), int(e.position().x()), self.width()))
        super().mousePressEvent(e)


def fmt_time(s: float) -> str:
    s = max(0, int(s))
    return f"{s // 60}:{s % 60:02d}"


def fmt_pos(pos: float, total: float) -> str:
    if total < 60:  # short clips: tenths of a second are more useful
        return f"{max(pos, 0):.1f}s / {total:.1f}s"
    return f"{fmt_time(pos)} / {fmt_time(total)}"


class Pad(QWidget):
    clicked = Signal(str)
    menu = Signal(str, QPoint)

    def __init__(self, meta: SoundMeta, width: int):
        super().__init__()
        self.meta = meta
        self.progress = None     # None = not playing
        self.paused = False
        self.selected = False
        self.state = "loading"   # loading | ready | error
        self.error = ""
        self.hover = False
        self._press = None
        self.setFixedSize(width, int(width * 0.62))
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)

    def enterEvent(self, e):
        self.hover = True
        self.update()

    def leaveEvent(self, e):
        self.hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = e.position().toPoint()
        elif e.button() == Qt.RightButton:
            self.menu.emit(self.meta.id, e.globalPosition().toPoint())

    def mouseMoveEvent(self, e):
        if self._press is not None and (e.position().toPoint() - self._press).manhattanLength() > 12:
            self._press = None
            drag = QDrag(self)
            md = QMimeData()
            md.setData(PAD_MIME, self.meta.id.encode())
            drag.setMimeData(md)
            drag.setPixmap(self.grab().scaled(self.width() // 2, self.height() // 2,
                                              Qt.KeepAspectRatio, Qt.SmoothTransformation))
            drag.exec(Qt.MoveAction)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._press is not None:
            self._press = None
            self.clicked.emit(self.meta.id)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        accent = QColor(self.meta.color)
        base = QColor("#232633") if not self.hover else QColor("#2b2f3f")
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        p.fillPath(path, base)
        if self.progress is not None:
            fill = QColor(accent)
            fill.setAlpha(45 if self.paused else 90)
            p.save()
            p.setClipPath(path)
            p.fillRect(QRectF(r.left(), r.top(), r.width() * max(self.progress, 0.02), r.height()), fill)
            p.restore()
            pen = QPen(accent, 2.5)
            if self.paused:
                pen.setStyle(Qt.DashLine)
            p.setPen(pen)
        elif self.selected:
            p.setPen(QPen(QColor("#5a6080"), 1.6))
        else:
            p.setPen(QPen(QColor("#343849"), 1.2))
        p.drawPath(path)
        # accent bar
        p.setPen(Qt.NoPen)
        p.setBrush(accent)
        p.drawRoundedRect(QRectF(r.left() + 10, r.top() + 10, 22, 4), 2, 2)
        # name
        p.setPen(QColor("#f1f3f9") if self.state == "ready" else QColor("#8a90a6"))
        f = QFont(self.font())
        f.setPointSizeF(10.5)
        f.setBold(True)
        p.setFont(f)
        text_r = r.adjusted(10, 20, -10, -24)
        p.drawText(text_r, Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap, self.meta.name)
        # footer: hotkey + duration / state
        f.setBold(False)
        f.setPointSizeF(8.5)
        p.setFont(f)
        foot = r.adjusted(10, r.height() - 24, -10, -6)
        if self.state == "loading":
            p.setPen(QColor("#8a90a6"))
            p.drawText(foot, Qt.AlignLeft | Qt.AlignVCenter, "loading…")
        elif self.state == "error":
            p.setPen(QColor("#ff6b6b"))
            p.drawText(foot, Qt.AlignLeft | Qt.AlignVCenter, "can't load file")
        else:
            flags = ("⟳ " if self.meta.loop else "") + {"overlap": "⧉ ", "toggle": "⏯ "}.get(self.meta.mode, "")
            p.setPen(QColor("#8a90a6"))
            right = "❚❚ paused" if self.paused else f"{flags}{self.meta.duration:.1f}s"
            p.drawText(foot, Qt.AlignRight | Qt.AlignVCenter, right)
            if self.meta.hotkey:
                hk = pretty_key(self.meta.hotkey)
                fm = p.fontMetrics()
                w = min(fm.horizontalAdvance(hk) + 12, foot.width() * 0.68)
                badge = QRectF(foot.left(), foot.top() + 1, w, foot.height() - 2)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor("#343849"))
                p.drawRoundedRect(badge, 5, 5)
                p.setPen(QColor("#d6d9e6"))
                p.drawText(badge, Qt.AlignCenter,
                           fm.elidedText(hk, Qt.ElideRight, int(badge.width()) - 8))


class PadGrid(QWidget):
    reorder = Signal(str, int)   # sound id, new index
    files_dropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.pads: list[Pad] = []
        self.grid = QGridLayout(self)
        self.grid.setSpacing(10)
        self.grid.setContentsMargins(4, 4, 4, 4)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.setAcceptDrops(True)
        self.empty = QLabel("Drop sound files here\nor click  ＋ Add sounds\n\n"
                            "mp3 · wav · ogg · flac · m4a · even video files")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet("color:#6b7189; font-size:15px; padding:60px;")
        self._cols = 0

    def set_pads(self, pads):
        self.pads = pads
        self._cols = 0
        self.relayout(force=True)

    def relayout(self, force=False):
        pw = self.pads[0].width() + self.grid.spacing() if self.pads else 160
        cols = max(1, (self.width() - 8) // pw)
        if cols == self._cols and not force:
            return
        self._cols = cols
        while self.grid.count():
            it = self.grid.takeAt(0)
            if it.widget() and it.widget() is not self.empty:
                it.widget().setParent(self)
        if not self.pads:
            self.grid.addWidget(self.empty, 0, 0)
            self.empty.show()
            return
        self.empty.hide()
        i = 0
        for p in self.pads:
            if p.property("filtered"):
                p.hide()
                continue
            p.show()
            self.grid.addWidget(p, i // cols, i % cols)
            i += 1

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.relayout()

    def dragEnterEvent(self, e):
        md = e.mimeData()
        if md.hasFormat(PAD_MIME) or md.hasUrls():
            e.acceptProposedAction()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, e):
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
            expanded = []
            for f in files:
                pth = Path(f)
                if pth.is_dir():
                    expanded += [str(x) for x in sorted(pth.rglob("*")) if x.suffix.lower() in AUDIO_EXTS]
                else:
                    expanded.append(f)
            self.files_dropped.emit(expanded)
            e.acceptProposedAction()


# =========================================================================== dialogs

class EditDialog(QDialog):
    def __init__(self, meta: SoundMeta, hotkeys: Hotkeys, preview_cb, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit sound")
        self.meta = meta
        self.hotkeys = hotkeys
        self.hotkey = meta.hotkey
        self.color = meta.color
        lay = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self.name = QLineEdit(meta.name)
        form.addRow("Name", self.name)

        vrow = QHBoxLayout()
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 200)
        self.vol.setValue(int(meta.volume * 100))
        self.vol_lbl = QLabel()
        self.vol.valueChanged.connect(lambda v: self.vol_lbl.setText(f"{v}%"))
        self.vol_lbl.setText(f"{self.vol.value()}%")
        self.vol_lbl.setFixedWidth(42)
        vrow.addWidget(self.vol)
        vrow.addWidget(self.vol_lbl)
        form.addRow("Volume", vrow)

        self.mode = QComboBox()
        self.mode.addItem("Restart — press again restarts it", "restart")
        self.mode.addItem("Overlap — every press plays a new copy", "overlap")
        self.mode.addItem("Toggle — press again stops it", "toggle")
        self.mode.setCurrentIndex(max(0, self.mode.findData(meta.mode)))
        form.addRow("On press", self.mode)

        self.loop = QCheckBox("Loop until stopped")
        self.loop.setChecked(meta.loop)
        form.addRow("", self.loop)

        hrow = QHBoxLayout()
        self.hk_btn = QPushButton()
        self.hk_btn.clicked.connect(self._capture)
        clr = QPushButton("Clear")
        clr.clicked.connect(lambda: self._set_hk(""))
        hrow.addWidget(self.hk_btn, 1)
        hrow.addWidget(clr)
        form.addRow("Hotkey", hrow)
        self._set_hk(self.hotkey)

        crow = QHBoxLayout()
        crow.setSpacing(6)
        self.swatches = []
        for c in PAD_COLORS:
            b = QPushButton()
            b.setFixedSize(24, 24)
            b.clicked.connect(lambda _=False, c=c: self._set_color(c))
            self.swatches.append((b, c))
            crow.addWidget(b)
        crow.addStretch()
        form.addRow("Colour", crow)
        self._set_color(self.color)
        lay.addLayout(form)

        prev = QPushButton("▶  Preview (only you hear it)")
        prev.clicked.connect(lambda: preview_cb(self.meta.id, self.vol.value() / 100))
        lay.addWidget(prev)

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.setMinimumWidth(460)

    def _set_color(self, c):
        self.color = c
        for b, col in self.swatches:
            border = "3px solid white" if col == c else "1px solid #444"
            b.setStyleSheet(f"background:{col}; border:{border}; border-radius:12px;")

    def _set_hk(self, combo):
        self.hotkey = combo
        self.hk_btn.setText(pretty_key(combo) or "Click to set…")

    def _capture(self):
        d = HotkeyDialog(self.hotkeys, self)
        if d.exec() and d.result_combo:
            self._set_hk(d.result_combo)
        self.parent().register_hotkeys()

    def apply(self):
        m = self.meta
        m.name = self.name.text().strip() or m.name
        m.volume = self.vol.value() / 100
        m.mode = self.mode.currentData()
        m.loop = self.loop.isChecked()
        m.hotkey = self.hotkey
        m.color = self.color


# =========================================================================== main window

class Bridge(QObject):
    loaded = Signal(str, object, str)          # id, data|None, error
    imported = Signal(object, object, str)     # meta|None, data|None, error/filename


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Soundboard")
        self.setWindowIcon(make_icon())
        self.cfg = Config.load()
        self.engine = Engine()
        self.audio: dict[str, np.ndarray] = {}
        self.pads: dict[str, Pad] = {}
        self.hotkeys = Hotkeys()
        self.hotkeys.fired.connect(self.on_hotkey)
        self.bridge = Bridge()
        self.bridge.loaded.connect(self.on_loaded)
        self.bridge.imported.connect(self.on_imported)
        self._ptt_down = False
        self._pending_imports = 0
        self._import_errors: list[str] = []
        self._rec_playing = False
        self.current: str | None = None   # sound shown in the transport bar
        self.start_frac = 0.0             # where ▶ starts if it isn't playing
        self._seeking = False

        self._build_ui()
        self._init_devices()
        self._rebuild_pads()
        self._load_all()
        self.register_hotkeys()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(33)
        self.resize(1180, 720)
        if self.cfg.always_on_top:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

    # ------------------------------------------------------------------ UI build
    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        h = QHBoxLayout(root)
        h.setContentsMargins(14, 14, 14, 10)
        h.setSpacing(14)

        # ---- left: toolbar + pads
        left = QVBoxLayout()
        bar = QHBoxLayout()
        add = QPushButton("＋  Add sounds")
        add.setObjectName("primary")
        add.clicked.connect(self.add_dialog)
        self.stop_btn = QPushButton("■  Stop all")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.clicked.connect(self.engine.stop_all)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search sounds…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.apply_filter)
        bar.addWidget(add)
        bar.addWidget(self.stop_btn)
        bar.addWidget(self.search, 1)
        size = QSlider(Qt.Horizontal)
        size.setRange(110, 240)
        size.setValue(self.cfg.pad_width)
        size.setFixedWidth(90)
        size.setToolTip("Pad size")
        size.valueChanged.connect(self.set_pad_width)
        bar.addWidget(QLabel("Size"))
        bar.addWidget(size)
        left.addLayout(bar)

        self.mic_banner = QPushButton("🎤  YOU'RE HEARING YOUR MIC OUTPUT  —  mic + sounds, "
                                      "exactly what others hear   ·   click to turn off")
        self.mic_banner.setObjectName("micbanner")
        self.mic_banner.setCursor(Qt.PointingHandCursor)
        self.mic_banner.clicked.connect(lambda: self.btn_check.setChecked(False))
        self.mic_banner.hide()
        left.addWidget(self.mic_banner)

        self.grid = PadGrid()
        self.grid.reorder.connect(self.on_reorder)
        self.grid.files_dropped.connect(self.import_files)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.grid)
        scroll.setFrameShape(QFrame.NoFrame)
        left.addWidget(scroll, 1)

        tb = QFrame()
        tb.setObjectName("transport")
        th = QHBoxLayout(tb)
        th.setContentsMargins(10, 8, 14, 8)
        th.setSpacing(10)
        self.btn_pp = QPushButton("▶")
        self.btn_pp.setObjectName("round")
        self.btn_pp.setToolTip("Play / pause")
        self.btn_pp.clicked.connect(self.toggle_play_pause)
        self.btn_st = QPushButton("■")
        self.btn_st.setObjectName("round")
        self.btn_st.setToolTip("Stop")
        self.btn_st.clicked.connect(self.stop_current)
        for b in (self.btn_pp, self.btn_st):
            b.setFixedSize(40, 36)
        self.np_name = QLabel("Click a sound to control it here")
        self.np_name.setFixedWidth(190)
        self.np_name.setStyleSheet("font-weight:600;")
        self.seek = SeekSlider(Qt.Horizontal)
        self.seek.setRange(0, 1000)
        self.seek.setObjectName("seek")
        self.seek.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.seek.sliderReleased.connect(self.do_seek)
        self.seek.valueChanged.connect(self._seek_preview)
        self.np_time = QLabel("0:00 / 0:00")
        self.np_time.setFixedWidth(84)
        self.np_time.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.np_time.setStyleSheet("color:#8a90a6;")
        th.addWidget(self.btn_pp)
        th.addWidget(self.btn_st)
        th.addWidget(self.np_name)
        th.addWidget(self.seek, 1)
        th.addWidget(self.np_time)
        left.addWidget(tb)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#8a90a6;")
        left.addWidget(self.status)
        h.addLayout(left, 1)

        # ---- right: audio panel
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setFixedWidth(330)
        panel.setMinimumHeight(0)
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(16, 16, 16, 16)
        pv.setSpacing(8)

        def section(t):
            l = QLabel(t)
            l.setObjectName("section")
            pv.addWidget(l)

        def hint(t):
            l = QLabel(t)
            l.setWordWrap(True)
            l.setObjectName("hint")
            pv.addWidget(l)
            return l

        # ---- plain-English picture of where the audio goes
        card = QFrame()
        card.setObjectName("howcard")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(12, 10, 12, 12)
        cv.setSpacing(3)
        t = QLabel("HOW IT WORKS")
        t.setObjectName("section")
        cv.addWidget(t)
        self.flow_mic = QLabel()
        self.flow_snd = QLabel("🔊  Your soundboard sounds")
        arrow = QLabel("⬇   the app mixes them together   ⬇")
        arrow.setStyleSheet("color:#8a90a6;")
        self.flow_out = QLabel()
        for w in (self.flow_mic, self.flow_snd, arrow, self.flow_out):
            w.setTextFormat(Qt.RichText)
            w.setWordWrap(True)
            cv.addWidget(w)
        self.step_lbl = QLabel()
        self.step_lbl.setWordWrap(True)
        self.step_lbl.setTextFormat(Qt.RichText)
        self.step_lbl.setStyleSheet("background:#15171f; border-radius:8px; padding:8px; "
                                    "margin-top:6px;")
        cv.addWidget(self.step_lbl)
        self.btn_install = QPushButton("⬇  Install the free virtual cable")
        self.btn_install.setObjectName("primary")
        self.btn_install.clicked.connect(self.install_cable)
        cv.addWidget(self.btn_install)
        self.btn_rescan = QPushButton("⟳  I've installed it — check again")
        self.btn_rescan.setObjectName("small")
        self.btn_rescan.clicked.connect(self.refresh_devices)
        cv.addWidget(self.btn_rescan)
        self.btn_nomic = QPushButton("Game has no microphone setting? Click here")
        self.btn_nomic.setObjectName("small")
        self.btn_nomic.clicked.connect(self.open_windows_mic)
        cv.addWidget(self.btn_nomic)
        pv.addWidget(card)

        section("YOUR MIC")
        self.chk_mic = QCheckBox("Mix my mic in (so they still hear me)")
        self.chk_mic.setChecked(self.cfg.mic_enabled)
        self.chk_mic.toggled.connect(self.on_mic_toggle)
        pv.addWidget(self.chk_mic)
        mic_row = QHBoxLayout()
        self.mic_lbl = QLabel("Mic")
        mic_row.addWidget(self.mic_lbl)
        self.mic_meter = Meter()
        mic_row.addWidget(self.mic_meter, 1)
        pv.addLayout(mic_row)

        section("VOLUME")
        self.sl_sound = self._slider(
            pv, "🔊  Soundboard → them",
            "How loud your sounds are for Discord / the game. Type up to 1000% in the box.",
            self.cfg.sound_vol, lambda v: self._set("sound_vol", v))
        self.sl_mic = self._slider(
            pv, "🎤  Your voice → them",
            "How loud your mic is for Discord / the game.",
            self.cfg.mic_vol, lambda v: self._set("mic_vol", v))
        self.sl_mon = self._slider(
            pv, "🎧  Your headphones",
            "Only what YOU hear. Doesn't change anything for them.",
            self.cfg.mon_vol, lambda v: self._set("mon_vol", v))
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Going out"))
        self.out_meter = Meter()
        self.out_meter.setToolTip("Level of what Discord / the game receives")
        out_row.addWidget(self.out_meter, 1)
        pv.addLayout(out_row)

        section("TEST MODE")
        self.btn_check = QPushButton("🎤  Listen to my mic output")
        self.btn_check.setObjectName("miccheck")
        self.btn_check.setCheckable(True)
        self.btn_check.toggled.connect(self.on_mic_check)
        pv.addWidget(self.btn_check)
        hint("Plays your mic into your headphones on top of the sounds — exactly "
             "what others hear. A red banner shows while it's on.")
        self.btn_rec = QPushButton("⏺  Record 6s → play back")
        self.btn_rec.clicked.connect(self.start_test)
        pv.addWidget(self.btn_rec)
        hint("Talk while a sound plays. Records what Discord / the game actually "
             "receives, plays it back, and tells you if your voice + sounds are in it.")
        self.test_result = QLabel()
        self.test_result.setWordWrap(True)
        self.test_result.setTextFormat(Qt.RichText)
        self.test_result.setStyleSheet("background:#232633; border-radius:8px; padding:8px;")
        self.test_result.hide()
        pv.addWidget(self.test_result)

        # ---- everything below is advanced, hidden until you open it
        self.btn_adv = QPushButton()
        self.btn_adv.setObjectName("advtoggle")
        self.btn_adv.setCheckable(True)
        pv.addWidget(self.btn_adv)
        adv = QWidget()
        adv_layout = QVBoxLayout(adv)
        adv_layout.setContentsMargins(0, 0, 0, 0)
        adv_layout.setSpacing(8)
        pv.addWidget(adv)
        base_pv, pv = pv, adv_layout   # section()/hint() now add to the advanced area

        section("DEVICES")
        hint("Already set up for you — only change these if something's wrong.")

        def alabel(text):
            l = QLabel(text)
            l.setObjectName("hint")
            pv.addWidget(l)

        alabel("Sounds + my voice get sent into (the cable):")
        self.cb_main = QComboBox()
        pv.addWidget(self.cb_main)
        self.setup_hint = hint("")
        alabel("I listen on (my headphones):")
        self.cb_mon = QComboBox()
        pv.addWidget(self.cb_mon)
        alabel("My real microphone:")
        self.cb_mic = QComboBox()
        pv.addWidget(self.cb_mic)
        ref = QPushButton("⟳ Re-scan devices")
        ref.setObjectName("small")
        ref.clicked.connect(self.refresh_devices)
        pv.addWidget(ref)

        section("SOUND OPTIONS")
        self.chk_monitor = QCheckBox("Hear sounds myself")
        self.chk_monitor.setChecked(self.cfg.monitor_sounds)
        self.chk_monitor.toggled.connect(lambda b: self._set("monitor_sounds", b))
        pv.addWidget(self.chk_monitor)
        self.chk_level = QCheckBox("Level volumes (all sounds equally loud)")
        self.chk_level.setChecked(self.cfg.level_volumes)
        self.chk_level.toggled.connect(self.on_level_toggle)
        pv.addWidget(self.chk_level)
        self._build_eq(pv, section, hint)

        section("HOTKEYS")
        self.btn_stop_hk = QPushButton()
        self.btn_stop_hk.clicked.connect(self.set_stop_hotkey)
        row = QHBoxLayout()
        row.addWidget(QLabel("Stop all"))
        row.addWidget(self.btn_stop_hk, 1)
        pv.addLayout(row)
        self.btn_pause_hk = QPushButton()
        self.btn_pause_hk.clicked.connect(self.set_pause_hotkey)
        row = QHBoxLayout()
        row.addWidget(QLabel("Pause all"))
        row.addWidget(self.btn_pause_hk, 1)
        pv.addLayout(row)
        self.btn_ptt = QPushButton()
        self.btn_ptt.clicked.connect(self.set_ptt)
        self.btn_ptt.setToolTip("Holds this key down while a sound is playing — "
                                "set it to your in-game push-to-talk key.")
        row = QHBoxLayout()
        row.addWidget(QLabel("Hold PTT"))
        row.addWidget(self.btn_ptt, 1)
        pv.addLayout(row)
        self._refresh_hk_buttons()
        self.chk_top = QCheckBox("Keep window on top")
        self.chk_top.setChecked(self.cfg.always_on_top)
        self.chk_top.toggled.connect(self.on_top_toggle)
        pv.addWidget(self.chk_top)
        pv = base_pv

        def set_adv(on):
            adv.setVisible(on)
            self.btn_adv.setText("⚙  Advanced  ▾   (hide)" if on else
                                 "⚙  Advanced  ▸   devices, EQ, hotkeys…")
            self.cfg.show_advanced = on
            self._save_later()
        self.btn_adv.toggled.connect(set_adv)
        self.btn_adv.setChecked(self.cfg.show_advanced)
        set_adv(self.cfg.show_advanced)
        pv.addStretch()
        pscroll = QScrollArea()
        pscroll.setWidget(panel)
        pscroll.setWidgetResizable(True)
        pscroll.setFrameShape(QFrame.NoFrame)
        pscroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        pscroll.setFixedWidth(344)
        h.addWidget(pscroll)

        for cb, kind, attr in ((self.cb_main, "output", "main_device"),
                               (self.cb_mon, "output", "mon_device"),
                               (self.cb_mic, "input", "mic_device")):
            cb.activated.connect(lambda _i, cb=cb, attr=attr: self.on_device(cb, attr))

    # ------------------------------------------------------------------ equalizer
    def _build_eq(self, pv, section, hint):
        section("EQUALIZER")
        c = self.cfg
        row = QHBoxLayout()
        self.chk_eq = QCheckBox("EQ on")
        self.chk_eq.setChecked(c.eq_enabled)
        row.addWidget(self.chk_eq)
        row.addWidget(QLabel("for"))
        self.cb_eq_target = QComboBox()
        for label, key in (("🎤 My voice", "voice"), ("🔊 My sounds", "sounds"),
                           ("Both", "all")):
            self.cb_eq_target.addItem(label, key)
        self.cb_eq_target.setCurrentIndex(max(0, self.cb_eq_target.findData(c.eq_target)))
        row.addWidget(self.cb_eq_target, 1)
        pv.addLayout(row)

        self.cb_eq_preset = QComboBox()
        self.cb_eq_preset.addItems(list(EQ_PRESETS))
        self.cb_eq_preset.addItem("Custom")
        pv.addWidget(self.cb_eq_preset)

        self.eq_curve = EqCurve()
        pv.addWidget(self.eq_curve)

        grid = QGridLayout()
        grid.setHorizontalSpacing(2)
        grid.setVerticalSpacing(2)
        self.eq_sliders, self.eq_vals = [], []
        for i, lab in enumerate(EQ_LABELS):
            val = QLabel("0")
            val.setAlignment(Qt.AlignCenter)
            val.setStyleSheet("font-size:8pt; color:#8a90a6;")
            s = QSlider(Qt.Vertical)
            s.setRange(-EQ_MAX_DB * 2, EQ_MAX_DB * 2)   # half-dB steps
            s.setFixedHeight(96)
            s.setToolTip(f"{lab} Hz")
            f = QLabel(lab)
            f.setAlignment(Qt.AlignCenter)
            f.setStyleSheet("font-size:8pt; color:#8a90a6;")
            grid.addWidget(val, 0, i)
            grid.addWidget(s, 1, i, Qt.AlignHCenter)
            grid.addWidget(f, 2, i)
            s.valueChanged.connect(self._on_eq_slider)
            self.eq_sliders.append(s)
            self.eq_vals.append(val)
        pv.addLayout(grid)
        hint("Low = bass (left) · high = treble (right). Drag up to boost, down to cut. "
             "Double-click the curve to reset.")

        self._set_eq_sliders(c.eq_gains)
        self.cb_eq_preset.setCurrentText(c.eq_preset if c.eq_preset in EQ_PRESETS else "Custom")
        self.chk_eq.toggled.connect(self._on_eq_toggle)
        self.cb_eq_target.currentIndexChanged.connect(self._on_eq_target)
        self.cb_eq_preset.currentTextChanged.connect(self._on_eq_preset)
        self.eq_curve.reset.connect(lambda: self.cb_eq_preset.setCurrentText("Flat (off)"))
        self._apply_eq()

    def _set_eq_sliders(self, gains):
        for s, g in zip(self.eq_sliders, gains):
            s.blockSignals(True)
            s.setValue(int(round(g * 2)))
            s.blockSignals(False)
        self._refresh_eq_labels()

    def _eq_gains(self):
        return [s.value() / 2 for s in self.eq_sliders]

    def _refresh_eq_labels(self):
        for s, lab in zip(self.eq_sliders, self.eq_vals):
            g = s.value() / 2
            lab.setText(f"{g:+g}" if g else "0")

    def _on_eq_slider(self, _v):
        self._refresh_eq_labels()
        self.cb_eq_preset.blockSignals(True)
        self.cb_eq_preset.setCurrentText("Custom")
        self.cb_eq_preset.blockSignals(False)
        if not self.chk_eq.isChecked():
            self.chk_eq.setChecked(True)   # touching the EQ means you want it on
        self._apply_eq()

    def _on_eq_preset(self, name):
        if name in EQ_PRESETS:
            self._set_eq_sliders(EQ_PRESETS[name])
            if name != "Flat (off)" and not self.chk_eq.isChecked():
                self.chk_eq.setChecked(True)
        self._apply_eq()

    def _on_eq_toggle(self, _on):
        self._apply_eq()

    def _on_eq_target(self, _i):
        self._apply_eq()

    def _apply_eq(self):
        c = self.cfg
        gains = self._eq_gains()
        c.eq_enabled = self.chk_eq.isChecked()
        c.eq_target = self.cb_eq_target.currentData()
        c.eq_preset = self.cb_eq_preset.currentText()
        c.eq_gains = gains
        self.engine.eq_target = c.eq_target
        self.engine.eq_gains = gains if c.eq_enabled else None
        self.eq_curve.set_gains(gains, c.eq_enabled)
        for w in self.eq_sliders + [self.cb_eq_target]:
            w.setProperty("dim", not c.eq_enabled)
        self._save_later()

    SLIDER_MAX = 300    # slider travel; the typed box goes further
    TYPED_MAX = 1000

    def _slider(self, lay, title, desc, value, cb):
        box = QFrame()
        box.setObjectName("volbox")
        v = QVBoxLayout(box)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(2)
        top = QHBoxLayout()
        t = QLabel(title)
        t.setStyleSheet("font-weight:600;")
        top.addWidget(t, 1)
        spin = QSpinBox()
        spin.setRange(0, self.TYPED_MAX)
        spin.setSuffix(" %")
        spin.setFixedWidth(82)
        spin.setAlignment(Qt.AlignRight)
        spin.setToolTip("Type an exact volume (0–1000%)")
        top.addWidget(spin)
        v.addLayout(top)
        d = QLabel(desc)
        d.setObjectName("hint")
        d.setWordWrap(True)
        v.addWidget(d)
        s = QSlider(Qt.Horizontal)
        s.setRange(0, self.SLIDER_MAX)
        v.addWidget(s)

        def paint_spin(pct):
            col = "#e6e8f0" if pct <= 100 else "#ffb020" if pct <= 300 else "#ff4d4f"
            spin.setStyleSheet(f"color:{col}; font-weight:600;")

        def from_slider(pct):
            spin.blockSignals(True)
            spin.setValue(pct)
            spin.blockSignals(False)
            paint_spin(pct)
            cb(pct / 100)

        def from_spin(pct):
            s.blockSignals(True)
            s.setValue(min(pct, self.SLIDER_MAX))
            s.blockSignals(False)
            paint_spin(pct)
            cb(pct / 100)

        pct0 = int(round(value * 100))
        s.setValue(min(pct0, self.SLIDER_MAX))
        spin.setValue(pct0)
        paint_spin(pct0)
        s.valueChanged.connect(from_slider)
        spin.valueChanged.connect(from_spin)
        lay.addWidget(box)
        return s

    # ------------------------------------------------------------------ devices
    def refresh_devices(self):
        e = self.engine
        e.shutdown()
        e.main_stream = e.mon_stream = e.mic_stream = None
        eng.rescan()
        self._init_devices()
        self._prepare_all()

    def _init_devices(self):
        outs = [d["name"] for d in eng.list_devices("output")]
        # a virtual cable as the *mic* would record our own output and feed it back
        # into itself (a loud feedback screech), so cables never appear here
        ins = [d["name"] for d in eng.list_devices("input") if not is_virtual_cable(d["name"])]
        c = self.cfg
        if c.mic_device and is_virtual_cable(c.mic_device):
            c.mic_device = None   # was set to the cable: fall back to the real mic
        if not c.main_device or eng.find_device("output", c.main_device) is None:
            c.main_device = next(iter(eng.virtual_outputs()), None) or c.main_device
        if not c.mon_device:
            dflt = eng.default_device_name("output")
            c.mon_device = dflt if dflt and not is_virtual_cable(dflt) else \
                next((n for n in outs if not is_virtual_cable(n)), None)
        if not c.mic_device:
            dflt = eng.default_device_name("input")
            c.mic_device = dflt if dflt and not is_virtual_cable(dflt) else \
                next(iter(ins), None)
        self._fill_combo(self.cb_main, outs, c.main_device)
        self._fill_combo(self.cb_mon, outs, c.mon_device)
        self._fill_combo(self.cb_mic, ins, c.mic_device)

        e = self.engine
        e.sound_vol, e.mic_vol, e.mon_vol = c.sound_vol, c.mic_vol, c.mon_vol
        e.mic_enabled, e.monitor_sounds = c.mic_enabled, c.monitor_sounds
        e.set_mic_device(c.mic_device if c.mic_enabled else None)
        e.set_main_device(c.main_device)
        e.set_mon_device(c.mon_device)
        self._update_status()

    def _fill_combo(self, cb, names, current):
        cb.blockSignals(True)
        cb.clear()
        cb.addItem("— none —", None)
        for n in names:
            cb.addItem(n, n)
        i = cb.findData(current) if current else 0
        cb.setCurrentIndex(i if i >= 0 else 0)
        cb.blockSignals(False)

    def on_device(self, cb, attr):
        name = cb.currentData()
        setattr(self.cfg, attr, name)
        if attr == "main_device":
            self.engine.set_main_device(name)
        elif attr == "mon_device":
            self.engine.set_mon_device(name)
        else:
            self.engine.set_mic_device(name if self.cfg.mic_enabled else None)
        self.cfg.save()
        self._update_status()
        self._prepare_all()

    def _prepare_all(self):
        items = list(self.audio.items())
        threading.Thread(target=lambda: [self.engine.prepare(s, d) for s, d in items],
                         daemon=True).start()

    def on_mic_toggle(self, b):
        self._set("mic_enabled", b)
        self.engine.set_mic_device(self.cfg.mic_device if b else None)
        self._update_status()

    def _update_status(self):
        e = self.engine
        main = self.cfg.main_device or ""
        self.virtual_mic = eng.virtual_mic_for(main)
        if self.virtual_mic:
            self.setup_hint.setText(f"A virtual cable is a pipe: audio goes in at <b>{main}</b> "
                                    f"and comes out at <b>{self.virtual_mic}</b>, which Discord "
                                    "/ the game uses as your mic.")
        elif main:
            self.setup_hint.setText("<span style='color:#ffb020'>That's a normal speaker/headphone "
                                    "device, so only you will hear the sounds. Pick a virtual "
                                    "cable here.</span>")
        else:
            self.setup_hint.setText("<span style='color:#ffb020'>Nothing picked — only you "
                                    "will hear sounds.</span>")
        self._update_flow()
        errs = [f"{k}: {v}" for k, v in e.errors.items()]
        if errs:
            self.status.setText("<span style='color:#ff6b6b'>Audio device problem — "
                                + " · ".join(errs) + "</span>")
        else:
            n = len(self.cfg.sounds)
            self.status.setText(f"{n} sound{'s' if n != 1 else ''} · click to play · right-click to "
                                "edit / set hotkey · drag to reorder · drop files to add")

    def _update_flow(self, talking=False):
        e = self.engine
        ok, bad = "#13ce66", "#ff4d4f"
        if e.mic_stream is None or not self.cfg.mic_enabled:
            mic = f"🎤  Your mic  <b style='color:{bad}'>✗ off</b>"
        elif talking:
            mic = f"🎤  Your mic  <b style='color:{ok}'>✓ hearing you</b>"
        else:
            mic = f"🎤  Your mic  <b style='color:{ok}'>✓</b>"
        vm = getattr(self, "virtual_mic", None)
        any_cable = bool(eng.virtual_outputs())
        if not any_cable:
            state = "missing"
            out = f"🎙  Virtual mic  <b style='color:{bad}'>✗ not installed yet</b>"
            step = ("<b style='color:#ffb020'>One-time setup:</b> install the free virtual "
                    "cable. It's what lets Discord and games hear your sounds — without it, "
                    "only you can hear them.")
        elif vm and e.main_stream is not None:
            state = "ok"
            out = (f"🎙  <b style='color:{ok}'>{vm}</b> — your new mic "
                   f"<b style='color:{ok}'>✓ working</b>")
            step = (f"<b>The only thing you set:</b> in Discord or your game, pick "
                    f"<b style='color:{ok}'>{vm}</b> as your <b>microphone</b>.")
        else:
            state = "unrouted"
            out = f"🎙  Virtual mic  <b style='color:{bad}'>✗ not connected</b>"
            step = ("<b style='color:#ffb020'>Almost:</b> open <b>⚙ Advanced → Devices</b> and "
                    "set “Sounds + my voice get sent into” to your virtual cable.")
        self.flow_mic.setText(mic)
        self.flow_out.setText(out)
        self.step_lbl.setText(step)
        self.btn_install.setVisible(state == "missing")
        self.btn_rescan.setVisible(state == "missing")
        self.btn_nomic.setVisible(state == "ok")

    def install_cable(self):
        script = Path(__file__).resolve().parent / "install-vbcable.ps1"
        if not script.exists():
            QMessageBox.warning(self, "Installer missing", f"Can't find {script.name}.")
            return
        subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                          "-File", str(script)],
                         creationflags=subprocess.CREATE_NEW_CONSOLE)
        QMessageBox.information(
            self, "Installing the virtual cable",
            "A window opened that downloads VB-Cable (free) from the official VB-Audio site.\n\n"
            "Windows will ask for permission — click Yes, then click “Install Driver”.\n\n"
            "When it's done, click “I've installed it — check again”. If it doesn't show up, "
            "restart your PC.")

    def open_windows_mic(self):
        vm = getattr(self, "virtual_mic", None) or "your virtual cable"
        subprocess.Popen(["control", "mmsys.cpl,,1"], creationflags=0x08000000)
        QMessageBox.information(
            self, "Game with no mic setting",
            "Some games just use Windows' main mic. A sound window just opened:\n\n"
            f"1.  Right-click  {vm}  →  Set as Default Device\n"
            "2.  Restart the game.\n\n"
            "Heads-up: voice typing will then also hear your sounds.\n"
            "To undo, do the same on your normal mic.")

    # ------------------------------------------------------------------ settings
    def _set(self, attr, v):
        setattr(self.cfg, attr, v)
        if hasattr(self.engine, attr):
            setattr(self.engine, attr, v)
        self._save_later()

    def _save_later(self):
        if not hasattr(self, "_save_timer"):
            self._save_timer = QTimer(self)
            self._save_timer.setSingleShot(True)
            self._save_timer.timeout.connect(self.cfg.save)
        self._save_timer.start(400)

    def on_level_toggle(self, b):
        self._set("level_volumes", b)
        for m in self.cfg.sounds:
            self.engine.set_gain(m.id, self.gain_for(m))

    def on_top_toggle(self, b):
        self._set("always_on_top", b)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, b)
        self.show()

    def set_pad_width(self, w):
        self.cfg.pad_width = w
        for p in self.pads.values():
            p.setFixedSize(w, int(w * 0.62))
        self.grid.relayout(force=True)
        self._save_later()

    # ------------------------------------------------------------------ hotkeys
    def register_hotkeys(self):
        mapping = {}
        if self.cfg.stop_hotkey:
            mapping[self.cfg.stop_hotkey] = "__stop__"
        if self.cfg.pause_hotkey:
            mapping.setdefault(self.cfg.pause_hotkey, "__pause__")
        for m in self.cfg.sounds:
            if m.hotkey:
                mapping.setdefault(m.hotkey, m.id)
        self.hotkeys.register(mapping)

    def _refresh_hk_buttons(self):
        self.btn_stop_hk.setText(pretty_key(self.cfg.stop_hotkey) or "Click to set…")
        self.btn_pause_hk.setText(pretty_key(self.cfg.pause_hotkey) or "Click to set…")
        self.btn_ptt.setText(pretty_key(self.cfg.ptt_key) or "Off (click to set)")

    def set_stop_hotkey(self):
        d = HotkeyDialog(self.hotkeys, self)
        if d.exec() and d.result_combo:
            self.cfg.stop_hotkey = d.result_combo
            self.cfg.save()
        self._refresh_hk_buttons()
        self.register_hotkeys()

    def set_pause_hotkey(self):
        d = HotkeyDialog(self.hotkeys, self)
        if d.exec() and d.result_combo:
            self.cfg.pause_hotkey = d.result_combo
            self.cfg.save()
        self._refresh_hk_buttons()
        self.register_hotkeys()

    def set_ptt(self):
        if self.cfg.ptt_key:
            if QMessageBox.question(self, "Push-to-talk", "Turn off auto push-to-talk?") \
                    == QMessageBox.Yes:
                self.cfg.ptt_key = ""
                self.cfg.save()
                self._refresh_hk_buttons()
                return
        d = HotkeyDialog(self.hotkeys, self)
        if d.exec() and d.result_combo:
            self.cfg.ptt_key = d.result_combo
            self.cfg.save()
        self._refresh_hk_buttons()
        self.register_hotkeys()

    def on_hotkey(self, action):
        if action == "__stop__":
            self.engine.stop_all()
        elif action == "__pause__":
            self.engine.pause_all()
        else:
            self.play(action)

    # ------------------------------------------------------------------ sounds
    def meta(self, sid) -> SoundMeta | None:
        return next((m for m in self.cfg.sounds if m.id == sid), None)

    def gain_for(self, m: SoundMeta, volume=None) -> float:
        v = m.volume if volume is None else volume
        return v * (m.level_gain if self.cfg.level_volumes else 1.0)

    def play(self, sid):
        m = self.meta(sid)
        data = self.audio.get(sid)
        if m is None or data is None:
            return
        self.select(sid)
        v = self.engine.play(sid, data, self.gain_for(m), loop=m.loop, mode=m.mode)
        if v is None and not self.engine.active_outputs():
            self.status.setText("<span style='color:#ffb020'>No audio device is open — pick one "
                                "on the right.</span>")

    def select(self, sid):
        if self.current != sid:
            if self.current in self.pads:
                self.pads[self.current].selected = False
                self.pads[self.current].update()
            self.current = sid
            self.start_frac = 0.0
            if sid in self.pads:
                self.pads[sid].selected = True
                self.pads[sid].update()
            m = self.meta(sid)
            name = m.name if m else ""
            self.np_name.setText(self.np_name.fontMetrics().elidedText(name, Qt.ElideRight, 186))

    def toggle_play_pause(self):
        sid = self.current
        if not sid:
            return
        st = self.engine.state(sid)
        if st:
            self.engine.set_paused(sid, not st[1])
            return
        m, data = self.meta(sid), self.audio.get(sid)
        if m and data is not None:
            frac = 0.0 if self.start_frac >= 0.995 else self.start_frac
            self.engine.play(sid, data, self.gain_for(m), loop=m.loop, mode="restart", start=frac)

    def stop_current(self):
        if self.current:
            self.engine.stop(self.current)
        self.start_frac = 0.0

    def _seek_preview(self, v):
        if self._seeking:
            m = self.meta(self.current) if self.current else None
            if m:
                self.np_time.setText(fmt_pos(v / 1000 * m.duration, m.duration))

    def do_seek(self):
        self._seeking = False
        if not self.current:
            return
        frac = self.seek.value() / 1000
        if not self.engine.seek(self.current, frac):
            self.start_frac = frac   # not playing: ▶ will start from here

    def preview(self, sid, volume=None):
        m = self.meta(sid)
        data = self.audio.get(sid)
        if m and data is not None:
            self.engine.play(sid + ":preview", data, self.gain_for(m, volume), mode="restart",
                             preview=True)

    def _rebuild_pads(self):
        for p in self.pads.values():
            p.setParent(None)
            p.deleteLater()
        self.pads = {}
        ordered = []
        for m in self.cfg.sounds:
            p = Pad(m, self.cfg.pad_width)
            p.clicked.connect(self.play)
            p.menu.connect(self.pad_menu)
            if m.id in self.audio:
                p.state = "ready"
            p.selected = m.id == self.current
            self.pads[m.id] = p
            ordered.append(p)
        self.grid.set_pads(ordered)
        self.apply_filter(self.search.text())
        self._update_status()

    def apply_filter(self, text):
        t = text.strip().lower()
        for m in self.cfg.sounds:
            p = self.pads.get(m.id)
            if p:
                p.setProperty("filtered", bool(t) and t not in m.name.lower())
        self.grid.relayout(force=True)

    def _load_all(self):
        todo = [(m.id, m.file) for m in self.cfg.sounds if m.id not in self.audio]

        def run():
            for sid, path in todo:
                try:
                    data = decode(path)
                    self.engine.prepare(sid, data)
                    self.bridge.loaded.emit(sid, data, "")
                except Exception as e:  # noqa: BLE001
                    self.bridge.loaded.emit(sid, None, str(e))
        threading.Thread(target=run, daemon=True).start()

    def on_loaded(self, sid, data, err):
        p = self.pads.get(sid)
        if data is not None:
            self.audio[sid] = data
            m = self.meta(sid)
            if m and not m.duration:
                m.duration = len(data) / SR
        if p:
            p.state = "ready" if data is not None else "error"
            p.error = err
            p.update()

    def add_dialog(self):
        exts = " ".join(f"*{e}" for e in sorted(AUDIO_EXTS))
        files, _ = QFileDialog.getOpenFileNames(self, "Add sounds", str(Path.home()),
                                                f"Audio ({exts});;All files (*)")
        if files:
            self.import_files(files)

    def import_files(self, files):
        files = [f for f in files if f]
        if not files:
            return
        self._pending_imports += len(files)
        start = len(self.cfg.sounds)

        def run():
            for i, f in enumerate(files):
                try:
                    meta, data = import_file(f, PAD_COLORS[(start + i) % len(PAD_COLORS)])
                    self.engine.prepare(meta.id, data)
                    self.bridge.imported.emit(meta, data, "")
                except Exception as e:  # noqa: BLE001
                    self.bridge.imported.emit(None, None, f"{Path(f).name}: {e}")
        threading.Thread(target=run, daemon=True).start()
        self.status.setText(f"Importing {len(files)} file(s)…")

    def on_imported(self, meta, data, err):
        self._pending_imports -= 1
        if meta is not None:
            self.cfg.sounds.append(meta)
            self.audio[meta.id] = data
        else:
            self._import_errors.append(err)
        if self._pending_imports <= 0:
            self._pending_imports = 0
            self.cfg.save()
            self._rebuild_pads()
            if self._import_errors:
                QMessageBox.warning(self, "Some files couldn't be added",
                                    "\n".join(self._import_errors[:15]))
                self._import_errors = []

    def on_reorder(self, sid, target):
        m = self.meta(sid)
        if not m:
            return
        self.cfg.sounds.remove(m)
        self.cfg.sounds.insert(min(target, len(self.cfg.sounds)), m)
        self.cfg.save()
        self._rebuild_pads()

    def pad_menu(self, sid, pos):
        m = self.meta(sid)
        if not m:
            return
        menu = QMenu(self)
        a_prev = menu.addAction("▶  Preview (only me)")
        a_edit = menu.addAction("✎  Edit… (name, volume, hotkey, loop)")
        a_hk = menu.addAction("⌨  Set hotkey…")
        menu.addSeparator()
        a_del = menu.addAction("🗑  Remove")
        act = menu.exec(pos)
        if act == a_prev:
            self.preview(sid)
        elif act == a_edit:
            self.edit(sid)
        elif act == a_hk:
            d = HotkeyDialog(self.hotkeys, self)
            if d.exec() and d.result_combo:
                m.hotkey = d.result_combo
                self._clear_dupe_hotkey(m)
                self.cfg.save()
                self.pads[sid].update()
            self.register_hotkeys()
        elif act == a_del:
            if QMessageBox.question(self, "Remove sound", f"Remove “{m.name}”?") == QMessageBox.Yes:
                self.engine.stop(sid)
                self.cfg.sounds.remove(m)
                self.audio.pop(sid, None)
                self.engine.forget(sid)
                delete_file(m)
                if self.current == sid:
                    self.current = None
                    self.np_name.setText("Click a sound to control it here")
                self.cfg.save()
                self._rebuild_pads()
                self.register_hotkeys()

    def _clear_dupe_hotkey(self, m):
        for o in self.cfg.sounds:
            if o is not m and o.hotkey and o.hotkey == m.hotkey:
                o.hotkey = ""
                if o.id in self.pads:
                    self.pads[o.id].update()
        for attr in ("stop_hotkey", "pause_hotkey"):
            if m.hotkey and m.hotkey == getattr(self.cfg, attr):
                setattr(self.cfg, attr, "")
                self._refresh_hk_buttons()

    def edit(self, sid):
        m = self.meta(sid)
        d = EditDialog(m, self.hotkeys, self.preview, self)
        if d.exec():
            d.apply()
            self._clear_dupe_hotkey(m)
            self.engine.set_gain(sid, self.gain_for(m))
            self.cfg.save()
            self.pads[sid].update()
            self.apply_filter(self.search.text())
        self.register_hotkeys()

    # ------------------------------------------------------------------ test mode
    def on_mic_check(self, on):
        self.engine.ring_mon.clear()
        self.engine.mic_check = on
        self.btn_check.setText("🔴  LISTENING TO MY MIC — click to stop" if on
                               else "🎤  Listen to my mic output")
        self.mic_banner.setVisible(on)
        self.setWindowTitle("🔴 MIC LIVE IN HEADPHONES — Soundboard" if on else "Soundboard")
        self.mic_lbl.setStyleSheet("color:#ff4d4f; font-weight:700;" if on else "")
        self.mic_meter.hot = on
        if on and not self.cfg.mic_enabled:
            self.status.setText("<span style='color:#ffb020'>“Mix my mic in” is off — "
                                "nobody (including you) will hear your mic.</span>")

    def start_test(self):
        if self.engine.main_stream is None:
            QMessageBox.information(self, "Test", "Set up the virtual cable first (see How it works).")
            return
        # Capture the far end of the virtual cable too, so the test hears exactly
        # what Discord / the game hears (not just our internal mix).
        self._cap, self._cap_stream, self._cap_rate = [], None, None
        vm = eng.virtual_mic_for(self.cfg.main_device)
        self._cap_name = vm
        if vm:
            idx = eng.find_device("input", vm)
            if idx is not None:
                try:
                    self._cap_rate = int(sd.query_devices(idx)["default_samplerate"])
                    self._cap_stream = sd.InputStream(
                        device=idx, samplerate=self._cap_rate, channels=2, dtype="float32",
                        callback=lambda i, f, t, s: self._cap.append(i.copy()))
                    self._cap_stream.start()
                except Exception:  # noqa: BLE001 - fall back to the internal mix
                    self._cap_stream = None
        self.engine.start_test_record(6.0)
        self.btn_rec.setEnabled(False)
        self.test_result.hide()
        self._rec_started = time.monotonic()

    def _finish_test(self, internal, rate):
        e = self.engine
        cable = False
        if self._cap_stream is not None:
            try:
                self._cap_stream.stop()
                self._cap_stream.close()
            except Exception:  # noqa: BLE001
                pass
            self._cap_stream = None
            if self._cap:
                data, rate, cable = np.concatenate(self._cap), self._cap_rate, True
            else:
                data = internal
        else:
            data = internal
        mic = e.take_mic_recording()
        try:
            r = analyze_output(data, rate, mic[0] if mic else None, mic[1] if mic else SR,
                               self.cfg.sound_vol)
            self.test_result.setText(summary_html(r, self._cap_name if cable else None))
        except Exception as ex:  # noqa: BLE001
            self.test_result.setText(f"<span style='color:#ff4d4f'>Test analysis failed: {ex}</span>")
        self.test_result.show()
        return data, rate

    # ------------------------------------------------------------------ tick
    def tick(self):
        e = self.engine
        playing = e.playing()
        for sid, p in self.pads.items():
            prog, paused = playing.get(sid, (None, False))
            if prog != p.progress or paused != p.paused:
                p.progress, p.paused = prog, paused
                p.update()
        self._update_transport(playing)
        self.out_meter.set_level(e.level_main)
        self.mic_meter.set_level(e.level_mic if e.mic_stream else 0.0)
        talking = e.mic_stream is not None and e.level_mic > 0.05
        if talking:
            self._talk_until = time.monotonic() + 0.8
        talking = time.monotonic() < getattr(self, "_talk_until", 0)
        if talking != getattr(self, "_talk_shown", None):
            self._talk_shown = talking
            self._update_flow(talking)
        if e.mic_check:  # pulse the banner so it's impossible to miss
            a = int(160 + 95 * (0.5 + 0.5 * np.sin(time.monotonic() * 5)))
            self.mic_banner.setStyleSheet(f"background: rgba(229,57,53,{a});")
        e.level_main *= 0.9
        e.level_mic *= 0.9

        # test recording
        if e.recording:
            left = 6.0 - (time.monotonic() - self._rec_started)
            self.btn_rec.setText(f"⏺  Recording… talk / play sounds  ({max(left, 0):.0f}s)")
        elif e.rec_done is not None:
            data, rate = e.rec_done
            e.rec_done = None
            data, rate = self._finish_test(data, rate)
            e.play("__test__", data, 1.0, preview=True, src_rate=rate)
            self._rec_playing = True
            self.btn_rec.setText("🔊  Playing back what they heard…")
        elif self._rec_playing and "__test__" not in playing:
            self._rec_playing = False
            self.btn_rec.setEnabled(True)
            self.btn_rec.setText("⏺  Record 6s → play back")

        # auto push-to-talk
        if self.cfg.ptt_key:
            want = e.any_playing()
            if want != self._ptt_down:
                try:
                    (keyboard.press if want else keyboard.release)(self.cfg.ptt_key)
                    self._ptt_down = want
                except Exception:  # noqa: BLE001
                    self._ptt_down = False
        elif self._ptt_down:
            self._ptt_down = False

    def _update_transport(self, playing):
        sid = self.current
        m = self.meta(sid) if sid else None
        enabled = m is not None
        for w in (self.btn_pp, self.btn_st, self.seek):
            w.setEnabled(enabled)
        if not m:
            return
        prog, paused = playing.get(sid, (None, False))
        live = prog is not None
        self.btn_pp.setText("⏸" if live and not paused else "▶")
        if not self._seeking:
            frac = prog if live else self.start_frac
            self.seek.blockSignals(True)
            self.seek.setValue(int(frac * 1000))
            self.seek.blockSignals(False)
            self.np_time.setText(fmt_pos(frac * m.duration, m.duration))

    def closeEvent(self, ev):
        if self._ptt_down and self.cfg.ptt_key:
            try:
                keyboard.release(self.cfg.ptt_key)
            except Exception:  # noqa: BLE001
                pass
        self.cfg.save()
        try:
            keyboard.unhook_all()
        except Exception:  # noqa: BLE001
            pass
        self.engine.shutdown()
        super().closeEvent(ev)


# =========================================================================== theme

STYLE = """
QWidget { background:#15171f; color:#e6e8f0; font-family:'Segoe UI'; font-size:10pt; }
QFrame#panel { background:#1c1f2a; border-radius:14px; }
QFrame#panel QWidget { background:transparent; }
QLabel#section { color:#8f96b3; font-size:8pt; font-weight:700; letter-spacing:1px; padding-top:8px; }
QLabel#hint { color:#8a90a6; font-size:8.5pt; }
QPushButton { background:#2a2e3d; border:1px solid #363b4e; border-radius:8px; padding:7px 12px; }
QPushButton:hover { background:#333849; }
QPushButton:pressed { background:#3c4257; }
QPushButton:checked { background:#7c5cff; border-color:#7c5cff; color:white; }
QPushButton:disabled { color:#8a90a6; }
QPushButton#primary { background:#7c5cff; border:none; color:white; font-weight:600; }
QPushButton#primary:hover { background:#8d71ff; }
QPushButton#danger { background:#3a2230; border:1px solid #5a2a3e; color:#ff8fa3; font-weight:600; }
QPushButton#danger:hover { background:#4a2a3c; }
QPushButton#small { padding:2px 8px; font-size:8pt; }
QFrame#transport { background:#1c1f2a; border-radius:12px; }
QFrame#panel QPushButton#advtoggle { background:#2a2e3d; padding:10px; font-weight:600;
    text-align:left; margin-top:8px; }
QFrame#panel QPushButton#advtoggle:checked { background:#2a2e3d; color:#e6e8f0; }
QFrame#panel QPushButton#primary { background:#7c5cff; color:white; border:none; padding:9px; }
QFrame#panel QPushButton#primary:hover { background:#8d71ff; }
QFrame#panel QFrame#howcard { background:#232633; border-radius:10px; }
QFrame#panel QFrame#volbox { background:#232633; border-radius:10px; }
QSpinBox { background:#15171f; border:1px solid #363b4e; border-radius:6px; padding:3px 4px; }
QSpinBox::up-button, QSpinBox::down-button { width:0; }
QSlider::groove:vertical { width:4px; background:#343849; border-radius:2px; }
QSlider::add-page:vertical { background:#7c5cff; border-radius:2px; }
QSlider::handle:vertical { background:white; width:14px; height:14px; margin:0 -5px; border-radius:7px; }
QPushButton#micbanner { background:#e53935; color:white; font-weight:700; font-size:11pt;
    border:none; border-radius:10px; padding:10px; }
QFrame#panel QPushButton#miccheck:checked { background:#e53935; border:1px solid #ff6b6b; color:white;
    font-weight:700; }
QFrame#transport QLabel { background:transparent; }
QPushButton#round { padding:0; font-size:14pt; border-radius:10px; }
QSlider#seek::groove:horizontal { height:6px; border-radius:3px; }
QSlider#seek::sub-page:horizontal { border-radius:3px; }
QLineEdit, QComboBox { background:#232633; border:1px solid #363b4e; border-radius:8px; padding:6px 8px; }
QFrame#panel QComboBox, QFrame#panel QPushButton { background:#232633; }
QFrame#panel QPushButton:checked { background:#7c5cff; }
QComboBox QAbstractItemView { background:#232633; selection-background-color:#7c5cff; }
QSlider::groove:horizontal { height:4px; background:#343849; border-radius:2px; }
QSlider::sub-page:horizontal { background:#7c5cff; border-radius:2px; }
QSlider::handle:horizontal { background:white; width:14px; height:14px; margin:-5px 0; border-radius:7px; }
QCheckBox::indicator { width:16px; height:16px; border-radius:4px; border:1px solid #4a5068; background:#232633; }
QCheckBox::indicator:checked { background:#7c5cff; border-color:#7c5cff; }
QScrollArea, QScrollArea > QWidget > QWidget { background:transparent; }
QScrollBar:vertical { background:transparent; width:10px; }
QScrollBar::handle:vertical { background:#343849; border-radius:5px; min-height:30px; }
QScrollBar::add-line, QScrollBar::sub-line { height:0; }
QMenu { background:#232633; border:1px solid #363b4e; padding:4px; }
QMenu::item { padding:6px 18px; border-radius:6px; }
QMenu::item:selected { background:#7c5cff; }
QToolTip { background:#232633; color:#e6e8f0; border:1px solid #363b4e; }
"""


def make_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#7c5cff"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(4, 4, 56, 56, 14, 14)
    p.setBrush(QColor("white"))
    for i, hgt in enumerate((18, 34, 26, 40, 22)):
        p.drawRoundedRect(12 + i * 8.5, 32 - hgt / 2, 5, hgt, 2.5, 2.5)
    p.end()
    return QIcon(pm)


def main():
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Soundboard.App")
    except Exception:  # noqa: BLE001
        pass
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    wheel_guard = NoWheelChanges(app)
    app.installEventFilter(wheel_guard)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
