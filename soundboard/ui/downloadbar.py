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
import re
import time
import urllib.parse

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPalette,
                           QPixmap)
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from soundboard import theme
from soundboard.i18n import _, ngettext
from soundboard.ui import icons
from soundboard.ui.scribebun import ScribeBunny
from soundboard.ui.widgets import fmt_time


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


class ElideLabel(QLabel):
    """A one-line label that shrinks with its box and ends in … when the text doesn't fit."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTextFormat(Qt.PlainText)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def sizeHint(self) -> QSize:
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 2,
                     super().sizeHint().height())

    def paintEvent(self, _e):
        p = QPainter(self)
        text = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, self.width())
        self.style().drawItemText(p, self.rect(), int(Qt.AlignLeft | Qt.AlignVCenter),
                                  self.palette(), self.isEnabled(), text, QPalette.WindowText)
        p.end()


THUMB_W, THUMB_H = 64, 36     # the picture at the left of the banner
ROW_THUMB = (40, 24)          # and in the queue list
WIDE_AT = 720                 # the banner is this wide or more: the uploader and length show
QUEUE_ROWS = 5                # queue rows shown before the list scrolls


AUDIO_EXTS = (".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus", ".webm", ".mp4")


def pretty_title(title: str) -> str:
    """A title as a person would write it: a file name loses its extension, and a name
    made of underscores or dashes ("my_cool-song") becomes words ("My Cool Song").
    A real title with spaces keeps its dashes ("Artist - Song")."""
    t = (title or "").strip()
    if t.lower().endswith(AUDIO_EXTS):
        t = t.rsplit(".", 1)[0]
    if " " not in t:   # a slug or file name
        t = t.replace("_", " ").replace("-", " ")
    else:
        t = t.replace("_", " ")
    t = re.sub(r"\s+", " ", t).strip()
    if t and t == t.lower():
        t = t.title()
    return t


def source_of(url: str) -> tuple[str, str]:
    """(icon name, site name) for the page a sound comes from."""
    host = (urllib.parse.urlsplit(url).hostname or "").lower().removeprefix("www.")

    def under(*domains):
        return any(host == d or host.endswith("." + d) for d in domains)
    if host == "music.youtube.com":
        return "ytmusic", "YouTube Music"
    if under("youtube.com", "youtu.be", "youtube-nocookie.com"):
        return "youtube", "YouTube"
    if under("soundcloud.com", "snd.sc"):
        return "soundcloud", "SoundCloud"
    if under("tiktok.com"):
        return "tiktok", "TikTok"
    if under("myinstants.com"):
        return "myinstants", "Myinstants"
    return "browser", host


def _rounded(pm: QPixmap, w: int, h: int, radius: int, dpr: float) -> QPixmap:
    """`pm` filled into a w x h box (cropped, not squashed) with rounded corners."""
    out = QPixmap(round(w * dpr), round(h * dpr))
    out.setDevicePixelRatio(dpr)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
    p.setClipPath(path)
    src = pm.scaled(round(w * dpr), round(h * dpr), Qt.KeepAspectRatioByExpanding,
                    Qt.SmoothTransformation)
    p.drawPixmap(QRectF(0, 0, w, h), src, QRectF(
        (src.width() - w * dpr) / 2, (src.height() - h * dpr) / 2, w * dpr, h * dpr))
    p.end()
    return out


def _placeholder(w: int, h: int, radius: int, dpr: float) -> QPixmap:
    """The picture for a sound with none of its own (an MP3 link, a search card whose
    art hasn't come yet): the theme's accent in a soft gradient with a sound wave on it."""
    T = theme.T
    out = QPixmap(round(w * dpr), round(h * dpr))
    out.setDevicePixelRatio(dpr)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    grad = QLinearGradient(0, 0, w, h)
    grad.setColorAt(0, QColor(theme.mix(T["card"], T["accent"], 0.75)))
    grad.setColorAt(1, QColor(theme.mix(T["card"], T["accent"], 0.25)))
    p.setBrush(grad)
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(0, 0, w, h), radius, radius)
    side = round(h * 0.6)
    glyph = icons.pixmap("wave", round(side * dpr), T["live_text"])
    glyph.setDevicePixelRatio(dpr)
    p.drawPixmap(round((w - side) / 2), round((h - side) / 2), glyph)
    p.end()
    return out


class DownloadBar(QFrame):
    """The persistent top bar displaying ongoing downloads and preparation, with the
    queue of picks waiting behind it (open from the "+N queued" button)."""
    cancel_requested = Signal(str)  # (url to cancel, or "" for active)
    stop_all_requested = Signal()   # the running download and every pick waiting
    play_requested = Signal()
    shown_changed = Signal(bool)   # the bar appeared / went away

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
        self._meta = ""
        self._source = ("browser", "")
        # set by the window: url -> picture (or None), url -> (uploader, seconds)
        self.thumb_lookup = lambda url: None

        self._auto_hide = QTimer(self)
        self._auto_hide.setSingleShot(True)
        self._auto_hide.timeout.connect(self._clear_and_hide)

        self._build_ui()
        self.retheme()
        self.hide()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        head = QWidget()
        head.setObjectName("downloadhead")
        outer.addWidget(head)
        h = self._head_lay = QHBoxLayout(head)
        h.setContentsMargins(12, 10, 12, 10)
        h.setSpacing(12)

        # Thumbnail / icon
        self.thumb = QLabel()
        self.thumb.setFixedSize(THUMB_W, THUMB_H)
        self.thumb.setAlignment(Qt.AlignCenter)
        h.addWidget(self.thumb, 0, Qt.AlignVCenter)
        # no picture of its own (an MP3, a link without art): Bun writes the download down
        self.scribe = ScribeBunny()
        h.addWidget(self.scribe, 0, Qt.AlignVCenter)

        # Center column: pill, title and uploader on line 1, status and progress on line 2
        col = self._col = QVBoxLayout()
        col.setSpacing(6)
        col.setContentsMargins(0, 0, 0, 0)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        row1.setContentsMargins(0, 0, 0, 0)

        self.pill = QLabel()
        self.pill.setObjectName("actionpill")
        self.pill.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        row1.addWidget(self.pill)

        self.lbl_title = ElideLabel()
        self.lbl_title.setObjectName("downloadtitle")
        f = self.lbl_title.font()
        f.setBold(True)
        self.lbl_title.setFont(f)
        row1.addWidget(self.lbl_title, 0)

        self.src_icon = QLabel()   # where it's from: the site's logo, then its name
        self.src_icon.setFixedSize(14, 14)
        self.src_icon.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        row1.addWidget(self.src_icon)
        self.lbl_src = QLabel()
        self.lbl_src.setObjectName("downloadmeta")
        row1.addWidget(self.lbl_src)

        self.lbl_meta = ElideLabel()
        self.lbl_meta.setObjectName("downloadmeta")
        self.lbl_meta.hide()
        row1.addWidget(self.lbl_meta, 1)
        row1.addStretch(1)   # a short title doesn't stretch the line
        col.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(10)
        row2.setContentsMargins(0, 0, 0, 0)

        self.lbl_status = QLabel()
        self.lbl_status.setObjectName("downloadstatus")
        self.lbl_status.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        row2.addWidget(self.lbl_status)

        self.bar = SmoothProgressBar()
        row2.addWidget(self.bar, 1)

        col.addLayout(row2)
        h.addLayout(col, 1)

        # On the right: the queue's button, Stop all, Cancel (or ✕ once it's over)
        self.queue_badge = QPushButton()
        self.queue_badge.setObjectName("queuebadge")
        self.queue_badge.setCheckable(True)
        self.queue_badge.setCursor(Qt.PointingHandCursor)
        self.queue_badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.queue_badge.toggled.connect(self._toggle_panel)
        self.queue_badge.hide()
        h.addWidget(self.queue_badge, 0, Qt.AlignVCenter)

        self.btn_stop_all = QPushButton(_("Stop all"))
        self.btn_stop_all.setObjectName("cancelbutton")
        self.btn_stop_all.setCursor(Qt.PointingHandCursor)
        self.btn_stop_all.clicked.connect(self._on_stop_all)
        self.btn_stop_all.hide()
        h.addWidget(self.btn_stop_all, 0, Qt.AlignVCenter)

        self.btn_cancel = QPushButton(_("Cancel"))
        self.btn_cancel.setObjectName("cancelbutton")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.setToolTip(_("Cancel download"))
        self.btn_cancel.clicked.connect(self._on_cancel)
        h.addWidget(self.btn_cancel, 0, Qt.AlignVCenter)

        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("urgenthide")
        self.btn_close.setToolTip(_("Dismiss"))
        self.btn_close.setFixedSize(26, 26)
        self.btn_close.clicked.connect(self.hide)
        self.btn_close.hide()
        h.addWidget(self.btn_close, 0, Qt.AlignVCenter)

        # The queue: one row per pick waiting, each with its own ✕
        self.panel = QWidget()
        self.panel.setObjectName("queuepanel")
        pv = QVBoxLayout(self.panel)
        pv.setContentsMargins(12, 8, 12, 10)
        pv.setSpacing(6)
        ph = QHBoxLayout()
        ph.setContentsMargins(0, 0, 0, 0)
        self.lbl_up_next = QLabel(_("Up next"))
        self.lbl_up_next.setObjectName("downloadstatus")
        ph.addWidget(self.lbl_up_next)
        ph.addStretch(1)
        self.btn_panel_stop = QPushButton(_("Stop all"))   # the head's is hidden in the mini player
        self.btn_panel_stop.setObjectName("cancelbutton")
        self.btn_panel_stop.setCursor(Qt.PointingHandCursor)
        self.btn_panel_stop.clicked.connect(self._on_stop_all)
        self.btn_panel_stop.hide()
        ph.addWidget(self.btn_panel_stop)
        pv.addLayout(ph)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("queuescroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        holder.setObjectName("queueholder")
        self.rows = QVBoxLayout(holder)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(4)
        self.scroll.setWidget(holder)
        pv.addWidget(self.scroll)
        outer.addWidget(self.panel)
        self.panel.hide()

    def retheme(self):
        T = theme.T
        card_bg = theme.mix(T["card"], T["accent"], 0.12)
        border = theme.mix(T["card"], T["accent"], 0.35)
        pill_bg = theme.mix(T["card"], T["accent"], 0.28)
        pill_color = T["live_text"]
        row_bg = theme.mix(card_bg, T["text"], 0.05)

        self.setStyleSheet(
            f"QFrame#downloadbar {{ background:{card_bg}; border:1px solid {border}; "
            f"border-radius:12px; }}"
            f"QWidget#downloadhead, QWidget#queuepanel, QWidget#queueholder, "
            f"QScrollArea#queuescroll {{ background:transparent; border:none; }}"
            f"QWidget#queuepanel {{ border-top:1px solid {border}; }}"
            f"QLabel#actionpill {{ background:{pill_bg}; color:{pill_color}; "
            f"border-radius:6px; padding:2px 8px; font-size:8pt; font-weight:700; }}"
            f"QLabel#downloadtitle {{ color:{T['text_hi']}; }}"
            f"QLabel#downloadmeta {{ color:{T['muted']}; font-size:9pt; }}"
            f"QLabel#downloadstatus {{ color:{T['muted']}; font-size:8.5pt; font-weight:600; }}"
            f"QPushButton#queuebadge {{ background:{T['btn']}; color:{T['text']}; "
            f"border:1px solid {T['border']}; border-radius:8px; padding:4px 10px; "
            f"font-size:8.5pt; font-weight:600; }}"
            f"QPushButton#queuebadge:hover, QPushButton#queuebadge:checked "
            f"{{ background:{T['btn_hover']}; }}"
            f"QPushButton#cancelbutton {{ background:transparent; border:1px solid {T['border']}; "
            f"border-radius:8px; padding:4px 12px; color:{T['muted']}; font-size:8.5pt; "
            f"font-weight:600; }}"
            f"QPushButton#cancelbutton:hover {{ background:{T['btn_hover']}; color:{T['text']}; }}"
            f"QPushButton#urgenthide {{ background:transparent; border:none; color:{T['muted']}; "
            f"border-radius:6px; padding:0px; min-width:0px; font-size:10pt; }}"
            f"QPushButton#urgenthide:hover {{ background:{T['btn_hover']}; }}"
            f"QFrame#queuerow {{ background:{row_bg}; border-radius:8px; }}"
            f"QLabel#queueindex {{ color:{T['muted']}; font-size:8.5pt; font-weight:700; }}"
        )
        self.bar.update()
        self._update_queue_badge()
        if self.url:
            self._update_thumb()   # the plain icon is drawn in the theme's colour
            self.src_icon.setPixmap(self._icon(self._source[0]))
        if self.panel.isVisible():
            self._fill_rows()

    def showEvent(self, ev):
        super().showEvent(ev)
        self.shown_changed.emit(True)

    def hideEvent(self, ev):
        super().hideEvent(ev)
        self.shown_changed.emit(False)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._show_meta()

    def set_mini(self, mini: bool):
        self._mini = mini
        self._apply_art()
        self._head_lay.setContentsMargins(*((8, 6, 8, 6) if mini else (12, 10, 12, 10)))
        self._head_lay.setSpacing(8 if mini else 12)
        self._update_queue_badge()
        self._show_meta()

    def _show_meta(self):
        """The uploader and length come after the title once the banner is wide."""
        self.lbl_meta.setVisible(bool(self._meta) and not self._mini
                                 and self.width() >= WIDE_AT)

    def set_active(self, url: str, title: str, kind: str, thumb_pm: QPixmap | None = None,
                   channel: str = "", seconds: float = 0.0):
        self._auto_hide.stop()
        self.url = url
        self.title = pretty_title(title) or _("Sound")
        self.kind = kind
        self.stage = "parsing"
        self.progress_frac = 0.0
        self._pm = thumb_pm
        self._source = source_of(url)
        self.lbl_src.setText(self._source[1])
        self.src_icon.setPixmap(self._icon(self._source[0]))

        self.lbl_title.setText(self.title)
        self.lbl_title.setToolTip(self.title)
        meta = " · ".join(x for x in (channel, fmt_time(seconds) if seconds else "") if x)
        self._meta = "· " + meta if meta else ""
        self.lbl_meta.setText(self._meta)
        self._show_meta()
        pill_text = _("Play once") if kind == "play" else _("Add as sound")
        self.pill.setText(pill_text)

        self.scribe.reset()
        self._update_thumb()
        self.btn_cancel.show()
        self.btn_close.hide()

        self.lbl_status.setText(_("Parsing video…"))
        self.bar.set_indeterminate(True)
        self._update_queue_badge()
        self.show()

    def set_progress(self, url: str, payload):
        if url != self.url:   # a cancelled download still finishing: not this one
            return
        self._auto_hide.stop()
        if payload == "parsing":
            self.stage = "parsing"
            self.scribe.set_state("parsing")
            self.lbl_status.setText(_("Parsing video…"))
            self.bar.set_indeterminate(True)
        elif payload == "processing" or (isinstance(payload, (int, float)) and payload < 0):
            self.stage = "processing"
            self.scribe.set_state("processing")
            self.lbl_status.setText(_("Processing audio…"))
            self.bar.set_indeterminate(True)
        elif isinstance(payload, (int, float)):
            self.stage = "downloading"
            self.progress_frac = max(0.0, min(1.0, float(payload)))
            self.scribe.set_progress(self.progress_frac)
            self.lbl_status.setText(f"{self.progress_frac * 100:.0f}%")   # the title says what
            self.bar.set_progress(self.progress_frac)
        self.show()

    def set_thumb(self, url: str, pm: QPixmap):
        if pm.isNull():
            return
        if url == self.url:
            self._pm = pm
            self._update_thumb()
        if self.panel.isVisible() and any(q["url"] == url for q in self._queue):
            self._fill_rows()

    def _icon(self, name: str) -> QPixmap:
        dpr = self.devicePixelRatioF()
        pm = icons.pixmap(name, round(14 * dpr), theme.T["muted"])
        pm.setDevicePixelRatio(dpr)
        return pm

    def _picture(self, pm: QPixmap | None, w: int, h: int, radius: int) -> QPixmap:
        dpr = self.devicePixelRatioF()
        if pm is not None and not pm.isNull():
            return _rounded(pm, w, h, radius, dpr)
        return _placeholder(w, h, radius, dpr)

    def _update_thumb(self):
        # as tall as the two lines beside it, so its top and bottom line up with them
        h = max(THUMB_H, self._col.sizeHint().height())
        self.thumb.setFixedSize(THUMB_W, h)
        if self._pm is not None and not self._pm.isNull():
            self.thumb.setPixmap(self._picture(self._pm, THUMB_W, h, 8))
        self._apply_art()

    def _apply_art(self):
        """The sound's own picture if it has one, else Bun at his scroll."""
        has = self._pm is not None and not self._pm.isNull()
        self.thumb.setVisible(has and not self._mini)
        self.scribe.setVisible(not has and not self._mini)
        if not self._mini:   # Bun's slot is taller than a picture: less space above and below
            self._head_lay.setContentsMargins(12, 10 if has else 6, 12, 10 if has else 6)

    def set_queue(self, queue: list[dict]):
        self._queue = list(queue)
        self._update_queue_badge()
        if self.panel.isVisible():
            self._fill_rows()

    def _update_queue_badge(self):
        if not self._queue:
            self.queue_badge.setChecked(False)
            self.queue_badge.hide()
            self.btn_stop_all.hide()
            self.panel.hide()
            return
        n = len(self._queue)
        self.queue_badge.setText(ngettext("+{count} queued", "+{count} queued", n, count=n))
        self.queue_badge.setIcon(QIcon(icons.pixmap(
            "fold_open" if self.queue_badge.isChecked() else "fold", 14, theme.T["muted"])))
        names = [pretty_title(item.get("title", "")) or _("Sound") for item in self._queue]
        self.queue_badge.setToolTip("\n".join([_("Up next")] + [f"• {n_}" for n_ in names]))
        self.queue_badge.show()
        self.btn_stop_all.setVisible(not self._mini)
        self.btn_panel_stop.setVisible(self._mini)

    def _toggle_panel(self, on: bool):
        if on and self._queue:
            self._fill_rows()
        self.panel.setVisible(on and bool(self._queue))
        self._update_queue_badge()

    def _fill_rows(self):
        """The queue list, rebuilt: it's a handful of rows (the queue is capped) and only
        while it's open."""
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for i, q in enumerate(self._queue, 1):
            row = QFrame()
            row.setObjectName("queuerow")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(8, 4, 6, 4)
            rl.setSpacing(8)
            idx = QLabel(str(i))
            idx.setObjectName("queueindex")
            idx.setFixedWidth(14)
            rl.addWidget(idx)
            pic = QLabel()
            pic.setFixedSize(*ROW_THUMB)
            pic.setPixmap(self._picture(self.thumb_lookup(q["url"]), *ROW_THUMB, 5))
            rl.addWidget(pic)
            title = ElideLabel()
            name = pretty_title(q.get("title", "")) or _("Sound")
            title.setText(name)
            title.setToolTip(name)
            title.setObjectName("downloadtitle")
            rl.addWidget(title, 1)
            kind = QLabel(_("Play once") if q.get("kind") == "play" else _("Add as sound"))
            kind.setObjectName("actionpill")
            kind.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            rl.addWidget(kind)
            x = QPushButton("✕")
            x.setObjectName("urgenthide")
            x.setToolTip(_("Remove"))
            x.setCursor(Qt.PointingHandCursor)
            x.setFixedSize(24, 24)
            x.clicked.connect(lambda _c=False, u=q["url"]: self.cancel_requested.emit(u))
            rl.addWidget(x)
            self.rows.addWidget(row)
        self.rows.addStretch(1)
        shown = min(len(self._queue), QUEUE_ROWS)
        self.scroll.setFixedHeight(shown * (ROW_THUMB[1] + 8) + max(0, shown - 1) * 4)

    def set_done(self, url: str, kind: str, ok: bool):
        if url != self.url:
            return
        self.stage = "done"
        self.scribe.finish(ok)
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
        if self.url == url:   # nothing took its place (the next pick would have set_active)
            self._clear_and_hide()

    def _on_stop_all(self):
        self.stop_all_requested.emit()
        self._clear_and_hide()

    def _clear_and_hide(self):
        self._auto_hide.stop()
        self.url = ""
        self.title = ""
        self.stage = ""
        self._queue = []
        self._pm = None
        self._meta = ""
        self._update_queue_badge()
        self.hide()
