"""Hand-painted widgets: level meter, EQ curve, seek slider, sound pads and their grid."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QMimeData, QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGridLayout, QLabel, QSlider, QStyle, QWidget

from soundboard import theme
from soundboard.eq import MAX_DB as EQ_MAX_DB
from soundboard.eq import response_db as eq_response
from soundboard.library import AUDIO_EXTS, SoundMeta
from soundboard.settings import pretty_key

PAD_MIME = "application/x-soundboard-pad"


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
        p.setBrush(QColor(theme.T["groove"]))
        p.drawRoundedRect(r, 4, 4)
        db = 20 * np.log10(max(self.level, 1e-5))
        frac = float(np.clip((db + 50) / 50, 0, 1))
        if frac > 0:
            col = "#13ce66" if db < -9 else "#ffb020" if db < -2 else "#ff4d4f"
            if self.hot:
                col = "#ff4d4f"
            p.setBrush(QColor(col))
            p.drawRoundedRect(QRectF(0, 0, r.width() * frac, r.height()), 4, 4)


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
        if not self.on:
            p.setPen(QColor(theme.T["faint"]))
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
        moved = self._press is not None and \
            (e.position().toPoint() - self._press).manhattanLength() > 12
        if moved:
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
        T = theme.T
        base = QColor(T["card_hi"] if self.hover else T["card"])
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        p.fillPath(path, base)
        if self.progress is not None:
            fill = QColor(accent)
            fill.setAlpha(45 if self.paused else 90)
            p.save()
            p.setClipPath(path)
            w = r.width() * max(self.progress, 0.02)
            p.fillRect(QRectF(r.left(), r.top(), w, r.height()), fill)
            p.restore()
            pen = QPen(accent, 2.5)
            if self.paused:
                pen.setStyle(Qt.DashLine)
            p.setPen(pen)
        elif self.selected:
            p.setPen(QPen(QColor(T["border_hi"]), 1.6))
        else:
            p.setPen(QPen(QColor(T["border"]), 1.2))
        p.drawPath(path)
        # accent bar
        p.setPen(Qt.NoPen)
        p.setBrush(accent)
        p.drawRoundedRect(QRectF(r.left() + 10, r.top() + 10, 22, 4), 2, 2)
        # name
        p.setPen(QColor(T["text_hi"] if self.state == "ready" else T["muted"]))
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
        if self.state in ("loading", "rendering"):
            p.setPen(QColor(T["muted"]))
            p.drawText(foot, Qt.AlignLeft | Qt.AlignVCenter,
                       "applying effects…" if self.state == "rendering" else "loading…")
        elif self.state == "error":
            p.setPen(QColor("#ff6b6b"))
            p.drawText(foot, Qt.AlignLeft | Qt.AlignVCenter, "can't load file")
        else:
            flags = ("FX " if self.meta.fx else "") + \
                ("⟳ " if self.meta.loop else "") + \
                {"overlap": "⧉ ", "toggle": "⏯ "}.get(self.meta.mode, "")
            p.setPen(QColor(T["muted"]))
            right = "❚❚ paused" if self.paused else f"{flags}{self.meta.duration:.1f}s"
            p.drawText(foot, Qt.AlignRight | Qt.AlignVCenter, right)
            if self.meta.hotkey:
                hk = pretty_key(self.meta.hotkey)
                fm = p.fontMetrics()
                w = min(fm.horizontalAdvance(hk) + 12, foot.width() * 0.68)
                badge = QRectF(foot.left(), foot.top() + 1, w, foot.height() - 2)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(T["badge"]))
                p.drawRoundedRect(badge, 5, 5)
                p.setPen(QColor(T["badge_text"]))
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
        self.empty.setObjectName("empty")
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
                    expanded += [str(x) for x in sorted(pth.rglob("*"))
                                 if x.suffix.lower() in AUDIO_EXTS]
                else:
                    expanded.append(f)
            self.files_dropped.emit(expanded)
            e.acceptProposedAction()
