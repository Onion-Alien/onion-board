"""The global download progress bar: sits at the top of the main window above all tabs
(and in the mini player), showing real-time download and preparation progress for
web links and search cards clicked by the user.

Shows:
- Preview thumbnail or download icon
- Action badge ("Play once" / "Add as sound")
- Sound title (elided)
- Status text ("Parsing video…", "Downloading · 42%", "Processing audio…", "✓ Added")
- A smooth progress bar (determinate fill or indeterminate gliding shimmer)
- Queue indicator ("+N queued") when multiple cards were clicked
- Cancel button to stop downloading or dequeue
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from soundboard import theme
from soundboard.i18n import _, ngettext
from soundboard.ui import icons


class SmoothProgressBar(QWidget):
    """A sleek 6px progress bar that supports both indeterminate gliding shimmer
    (during video parsing / audio decoding) and determinate progress (during byte download)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(6)
        self._mode = "indeterminate"  # "indeterminate" or "determinate"
        self._progress = 0.0          # 0.0 .. 1.0
        self._t0 = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(1000 // 30)
        self._timer.timeout.connect(self.update)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_indeterminate(self, on: bool):
        if on:
            self._mode = "indeterminate"
            self._t0 = time.monotonic()
            if self.isVisible() and not self._timer.isActive():
                self._timer.start()
        else:
            self._mode = "determinate"
            self._timer.stop()
        self.update()

    def set_progress(self, frac: float):
        self._mode = "determinate"
        self._progress = max(0.0, min(1.0, float(frac)))
        self._timer.stop()
        self.update()

    def showEvent(self, ev):
        super().showEvent(ev)
        if self._mode == "indeterminate":
            self._timer.start()

    def hideEvent(self, ev):
        self._timer.stop()
        super().hideEvent(ev)

    def sizeHint(self) -> QSize:
        return QSize(180, 6)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        rad = r.height() / 2
        p.setPen(Qt.NoPen)
        groove = QColor(theme.T.get("groove", theme.mix(theme.T["card"], theme.T["text"], 0.12)))
        p.setBrush(groove)
        p.drawRoundedRect(r, rad, rad)

        accent = QColor(theme.T.get("accent", "#7c5cff"))
        p.setBrush(accent)
        if self._mode == "indeterminate":
            k = 0.5 - 0.5 * math.cos((time.monotonic() - self._t0) * math.pi / 0.9)
            pw = max(r.height() * 2, r.width() * 0.28)
            px = r.left() + (r.width() - pw) * k
            p.drawRoundedRect(QRectF(px, r.top(), pw, r.height()), rad, rad)
        else:
            w = r.width() * self._progress
            if w > 0:
                p.drawRoundedRect(QRectF(r.left(), r.top(), max(r.height(), w), r.height()),
                                  rad, rad)
        p.end()


class DownloadBar(QFrame):
    """The persistent top bar displaying ongoing downloads and preparation."""
    cancel_requested = Signal(str)  # (url to cancel, or "" for active)
    play_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("downloadbar")
        self.url = ""
        self.title = ""
        self.kind = ""  # "play" or "add"
        self.stage = ""  # "parsing", "downloading", "processing", "done"
        self.progress_frac = 0.0
        self._mini = False
        self._queue: list[dict] = []
        self._pm: QPixmap | None = None

        self._auto_hide = QTimer(self)
        self._auto_hide.setSingleShot(True)
        self._auto_hide.timeout.connect(self._clear_and_hide)

        self._build_ui()
        self._style()
        self.hide()

    def _build_ui(self):
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 6, 10, 6)
        h.setSpacing(10)

        # Thumbnail / icon
        self.thumb = QLabel()
        self.thumb.setFixedSize(44, 26)
        self.thumb.setAlignment(Qt.AlignCenter)
        h.addWidget(self.thumb)

        # Center column: Title + Action Pill on line 1, Status text + Progress bar on line 2
        col = QVBoxLayout()
        col.setSpacing(3)
        col.setContentsMargins(0, 0, 0, 0)

        row1 = QHBoxLayout()
        row1.setSpacing(6)
        row1.setContentsMargins(0, 0, 0, 0)

        self.pill = QLabel()
        self.pill.setObjectName("actionpill")
        self.pill.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        row1.addWidget(self.pill)

        self.lbl_title = QLabel()
        self.lbl_title.setObjectName("downloadtitle")
        self.lbl_title.setTextFormat(Qt.PlainText)
        self.lbl_title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        f = self.lbl_title.font()
        f.setBold(True)
        self.lbl_title.setFont(f)
        row1.addWidget(self.lbl_title, 1)

        self.queue_badge = QLabel()
        self.queue_badge.setObjectName("queuebadge")
        self.queue_badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.queue_badge.hide()
        row1.addWidget(self.queue_badge)

        col.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        row2.setContentsMargins(0, 0, 0, 0)

        self.lbl_status = QLabel()
        self.lbl_status.setObjectName("downloadstatus")
        self.lbl_status.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        row2.addWidget(self.lbl_status)

        self.bar = SmoothProgressBar()
        row2.addWidget(self.bar, 1)

        col.addLayout(row2)
        h.addLayout(col, 1)

        # Actions on the right: Play/Resume (when done) or Cancel
        self.btn_cancel = QPushButton(_("Cancel"))
        self.btn_cancel.setObjectName("cancelbutton")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.setToolTip(_("Cancel download"))
        self.btn_cancel.clicked.connect(self._on_cancel)
        h.addWidget(self.btn_cancel)

        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("urgenthide")
        self.btn_close.setToolTip(_("Dismiss"))
        self.btn_close.setFixedSize(26, 26)
        self.btn_close.clicked.connect(self.hide)
        self.btn_close.hide()
        h.addWidget(self.btn_close)

    def _style(self):
        T = theme.T
        card_bg = theme.mix(T["card"], T["accent"], 0.12)
        border = theme.mix(T["card"], T["accent"], 0.35)
        pill_bg = theme.mix(T["card"], T["accent"], 0.28)
        pill_color = T["live_text"]

        self.setStyleSheet(
            f"QFrame#downloadbar {{ background:{card_bg}; border:1px solid {border}; "
            f"border-radius:12px; }}"
            f"QLabel#actionpill {{ background:{pill_bg}; color:{pill_color}; "
            f"border-radius:6px; padding:2px 8px; font-size:8pt; font-weight:700; }}"
            f"QLabel#downloadtitle {{ color:{T['text_hi']}; }}"
            f"QLabel#downloadstatus {{ color:{T['muted']}; font-size:8.5pt; font-weight:600; }}"
            f"QLabel#queuebadge {{ background:{T['btn']}; color:{T['muted']}; "
            f"border:1px solid {T['border']}; border-radius:6px; padding:1px 6px; font-size:8pt; }}"
            f"QPushButton#cancelbutton {{ background:transparent; border:1px solid {T['border']}; "
            f"border-radius:6px; padding:3px 10px; color:{T['muted']}; font-size:8.5pt; "
            f"font-weight:600; }}"
            f"QPushButton#cancelbutton:hover {{ background:{T['btn_hover']}; color:{T['text']}; }}"
            f"QPushButton#urgenthide {{ background:transparent; border:none; color:{T['muted']}; "
            f"border-radius:6px; }}"
            f"QPushButton#urgenthide:hover {{ background:{T['btn_hover']}; }}"
        )

    def set_mini(self, mini: bool):
        self._mini = mini
        self.thumb.setVisible(not mini)
        margins = (8, 4, 8, 4) if mini else (12, 6, 10, 6)
        self.layout().setContentsMargins(*margins)


    def set_active(self, url: str, title: str, kind: str, thumb_pm: QPixmap | None = None):
        self._auto_hide.stop()
        self.url = url
        self.title = title or _("Sound")
        self.kind = kind
        self.stage = "parsing"
        self.progress_frac = 0.0
        self._pm = thumb_pm

        self.lbl_title.setText(self.title)
        self.lbl_title.setToolTip(self.title)
        pill_text = _("Play once") if kind == "play" else _("Add as sound")
        self.pill.setText(pill_text)

        self._update_thumb()
        self.btn_cancel.show()
        self.btn_close.hide()

        self.lbl_status.setText(_("Parsing video…"))
        self.bar.set_indeterminate(True)
        self._update_queue_badge()
        self.show()

    def set_progress(self, url: str, payload):
        if url != self.url and not self.url:
            return
        self._auto_hide.stop()
        if payload == "parsing":
            self.stage = "parsing"
            self.lbl_status.setText(_("Parsing video…"))
            self.bar.set_indeterminate(True)
        elif payload == "processing" or (isinstance(payload, (int, float)) and payload < 0):
            self.stage = "processing"
            self.lbl_status.setText(_("Processing audio…"))
            self.bar.set_indeterminate(True)
        elif isinstance(payload, (int, float)):
            self.stage = "downloading"
            self.progress_frac = max(0.0, min(1.0, float(payload)))
            pct = self.progress_frac * 100
            self.lbl_status.setText(_("Downloading audio · {value:.0f}%", value=pct))
            self.bar.set_progress(self.progress_frac)
        self.show()

    def set_thumb(self, url: str, pm: QPixmap):
        if url == self.url and not pm.isNull():
            self._pm = pm
            self._update_thumb()

    def _update_thumb(self):
        if self._pm and not self._pm.isNull():
            dpr = self.devicePixelRatioF()
            tw, th = round(44 * dpr), round(26 * dpr)
            scaled = self._pm.scaled(tw, th, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            scaled.setDevicePixelRatio(dpr)
            self.thumb.setPixmap(scaled)
        else:
            self.thumb.setPixmap(icons.pixmap("wave", 20, "muted"))

    def set_queue(self, queue: list[dict]):
        self._queue = list(queue)
        self._update_queue_badge()

    def _update_queue_badge(self):
        if not self._queue:
            self.queue_badge.hide()
            return
        n = len(self._queue)
        text = ngettext("+{count} queued", "+{count} queued", n, count=n)
        tip_lines = [_("Next in line:")] + [
            f"• {item.get('title', _('Sound'))}" for item in self._queue
        ]
        self.queue_badge.setText(text)
        self.queue_badge.setToolTip("\n".join(tip_lines))
        self.queue_badge.show()

    def set_done(self, url: str, kind: str, ok: bool):
        if url != self.url and self.url:
            return
        self.stage = "done"
        self.btn_cancel.hide()
        self.btn_close.show()

        if ok:
            if kind == "play":
                self.lbl_status.setText(_("▶ Playing"))
                self.bar.set_progress(1.0)
                self._auto_hide.start(7000)
            else:
                self.lbl_status.setText(_("✓ Added to your sounds"))
                self.bar.set_progress(1.0)
                self._auto_hide.start(4000)
        else:
            self.lbl_status.setText(_("Couldn't download"))
            self.bar.set_progress(0.0)
            self._auto_hide.start(6000)

    def _on_cancel(self):
        url = self.url
        self.cancel_requested.emit(url)
        self._clear_and_hide()

    def _clear_and_hide(self):
        self._auto_hide.stop()
        self.url = ""
        self.title = ""
        self.stage = ""
        self._queue = []
        self._pm = None
        self.hide()
