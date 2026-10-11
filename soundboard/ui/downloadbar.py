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

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import (QColor, QFontMetricsF, QIcon, QLinearGradient, QPainter,
                           QPainterPath, QPalette, QPen, QPixmap)
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSizePolicy, QSpacerItem, QVBoxLayout, QWidget)

from soundboard import theme, usage
from soundboard.i18n import _, ngettext
from soundboard.ui import icons
from soundboard.ui.scribebun import ScribeBunny
from soundboard.ui.widgets import fmt_time


CORNER = 22   # room line 1 leaves for the corner's minimise / ✕ button
BAR_W = 480   # the progress bar's length in the banner
LINE_GAP = 9  # between line 1 (the title) and line 2 (the bar); the mini player: 2


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
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

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
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        rad = r.height() / 2
        p.setPen(Qt.PenStyle.NoPen)
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
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def sizeHint(self) -> QSize:
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 2,
                     super().sizeHint().height())

    def paintEvent(self, _e):
        p = QPainter(self)
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, self.width())
        self.style().drawItemText(p, self.rect(),
                                  int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                                  self.palette(), self.isEnabled(), text,
                                  QPalette.ColorRole.WindowText)
        p.end()


class Outcome(QWidget):
    """How a download ended, flashed for a moment: a small green tick in front of the
    picture (or Bun) when it worked, a red ✗ there when it didn't (the bar's background
    turns red then too: DownloadBar.paintEvent, under the words). No badge behind the
    mark; it pops in and fades straight away. Clicks go through it."""

    SHOW_MS = 1000
    MARK = 20.0          # the tick's or ✗'s size, px

    def __init__(self, bar: QFrame):
        super().__init__(bar)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.ok = True
        self.spot = QRectF()   # the picture's box, in the bar's pixels (empty: no badge)
        self._k = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(self.SHOW_MS)
        self._anim.valueChanged.connect(self._step)
        self._anim.finished.connect(self.hide)
        self.hide()

    def play(self, ok: bool, spot: QRectF):
        self.ok, self.spot = ok, spot
        bar = self.parentWidget()
        assert bar is not None   # made on the bar
        self.setGeometry(bar.rect())
        self.raise_()
        self.show()
        self._anim.stop()
        self._anim.start()

    def stop(self):
        self._anim.stop()
        self.hide()

    def running(self) -> bool:
        return self._anim.state() == QVariantAnimation.State.Running

    def k(self) -> float:
        return self._k

    def _step(self, k):
        self._k = float(k)
        self.update()
        bar = self.parentWidget()
        if not self.ok and bar is not None:
            bar.update()   # its red background fades with it

    def paintEvent(self, _e):
        k = self._k
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        red = QColor(theme.status("error"))
        if self.spot.isEmpty():
            p.end()
            return
        pop = min(1.0, k / 0.15)                               # pops in, then fades out
        fade = min(1.0, (1.0 - k) / 0.4)
        u = self.MARK / 2 * (0.6 + 0.4 * pop)
        c = self.spot.center()
        path = QPainterPath()
        if self.ok:
            path.moveTo(c.x() - 0.8 * u, c.y() + 0.05 * u)
            path.lineTo(c.x() - 0.25 * u, c.y() + 0.6 * u)
            path.lineTo(c.x() + 0.85 * u, c.y() - 0.6 * u)
        else:
            a = 0.62 * u
            path.moveTo(c.x() - a, c.y() - a)
            path.lineTo(c.x() + a, c.y() + a)
            path.moveTo(c.x() - a, c.y() + a)
            path.lineTo(c.x() + a, c.y() - a)
        p.setBrush(Qt.BrushStyle.NoBrush)
        edge = QColor(theme.T["bg"]).darker(140)   # a thin dark edge: shows on any picture
        edge.setAlphaF(0.7 * fade)
        p.setPen(QPen(edge, 5.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                      Qt.PenJoinStyle.RoundJoin))
        p.drawPath(path)
        mark = QColor(theme.status("ok") if self.ok else red)
        mark.setAlphaF(fade)
        p.setPen(QPen(mark, 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                      Qt.PenJoinStyle.RoundJoin))
        p.drawPath(path)
        p.end()


THUMB_W, THUMB_H = 64, 36     # the picture at the left of the banner
ROW_THUMB = (40, 24)          # and in the queue list
WIDE_AT = 720                 # the banner is this wide or more: the uploader and length show
TIGHT_BELOW = 640             # narrower: the site as just its logo, Stop all in the queue list,
                              # "+2" for "+2 queued" (as in the mini player)
BAR_MIN_W = 48                # the progress bar never shrinks past this
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
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
    p.setClipPath(path)
    src = pm.scaled(round(w * dpr), round(h * dpr), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation)
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
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QLinearGradient(0, 0, w, h)
    grad.setColorAt(0, QColor(theme.mix(T["card"], T["accent"], 0.75)))
    grad.setColorAt(1, QColor(theme.mix(T["card"], T["accent"], 0.25)))
    p.setBrush(grad)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(QRectF(0, 0, w, h), radius, radius)
    side = round(h * 0.6)
    glyph = icons.pixmap("wave", round(side * dpr), T["live_text"])
    glyph.setDevicePixelRatio(dpr)
    p.drawPixmap(round((w - side) / 2), round((h - side) / 2), glyph)
    p.end()
    return out


def _after_hold(method):
    """While the tick or red flash of the download that just ended shows, what comes
    next (the next pick starting, its progress, the queue moving up) waits, then
    plays out in order. The downloads themselves don't wait: only the banner does."""
    def wrapper(self, *args):
        if self._held is not None:
            self._held.append((method, args))
            return
        method(self, *args)
    wrapper.__name__ = method.__name__
    wrapper.__doc__ = method.__doc__
    return wrapper


class _QueueRow(QFrame):
    """A row of the queue list; clicking a waiting one makes it next up."""
    clicked = Signal()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(ev)


class _Summary(QWidget):
    """The banner's slim top line: "Downloads · 2 of 4 · 45% · total 36%". Clicking it
    folds the banner down to just this line, or opens it again."""
    clicked = Signal()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(ev)


class DownloadBar(QFrame):
    """The persistent top bar displaying ongoing downloads and preparation, with the
    queue of picks waiting behind it (open from the "+N queued" button)."""
    cancel_requested = Signal(str)  # (url to cancel, or "" for active)
    stop_all_requested = Signal()   # the running download and every pick waiting
    play_requested = Signal()
    shown_changed = Signal(bool)   # the bar appeared / went away
    retry_requested = Signal(dict)  # a pick that failed: {url, title, kind, seconds}
    front_requested = Signal(str)   # a waiting pick clicked in the list: it's next up

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("downloadbar")
        self.url = ""
        self.title = ""
        self.kind = ""  # "play" or "add"
        self.stage = ""  # "parsing", "downloading", "processing", "done"
        self.progress_frac = 0.0
        self._mini = False
        self._tight = False   # _fit_tight: a narrow banner (or the mini player's)
        self._queue: list[dict] = []
        self._failed: list[dict] = []   # picks that couldn't download, to retry
        self._raw = ("", 0.0)   # the running pick's title as given, and its length
        self._failing = ""      # set_failed: the next set_done(False) for it is an error
        self._cancelling = ""   # our own Cancel / Stop all: its set_done isn't a failure
        self._held: list | None = None   # calls waiting for the tick / red flash (_after_hold)
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.timeout.connect(self._release)
        self._pm: QPixmap | None = None
        self._meta = ""
        self._source = ("browser", "")
        # set by the window: url -> picture (or None), url -> (uploader, seconds)
        self.thumb_lookup = lambda url: None

        self._auto_hide = QTimer(self)
        self._auto_hide.setSingleShot(True)
        self._auto_hide.timeout.connect(self._clear_and_hide)

        self._build_ui()
        self.outcome = Outcome(self)
        self.retheme()
        self.hide()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Minimised, the banner is one slim line: what the whole queue is up to, a thin
        # bar, and a chevron (or a click anywhere on it) to open it again
        sm = self.summary = _Summary()
        sm.setObjectName("downloadhead")
        sm.setCursor(Qt.CursorShape.PointingHandCursor)
        sm.clicked.connect(lambda: self.set_collapsed(False))
        sl = QHBoxLayout(sm)
        sl.setContentsMargins(12, 6, 8, 6)
        sl.setSpacing(8)
        self.s_icon = QLabel()
        self.s_icon.setFixedSize(14, 14)
        sl.addWidget(self.s_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        self.s_name = QLabel(_("Downloads"))
        self.s_name.setObjectName("summaryname")
        sl.addWidget(self.s_name, 0, Qt.AlignmentFlag.AlignVCenter)
        self.s_text = ElideLabel()
        self.s_text.setObjectName("downloadstatus")
        sl.addWidget(self.s_text, 0, Qt.AlignmentFlag.AlignVCenter)
        self.s_failed = QLabel()
        self.s_failed.setObjectName("summaryfailed")
        self.s_failed.hide()
        sl.addWidget(self.s_failed, 0, Qt.AlignmentFlag.AlignVCenter)
        sl.addStretch(1)
        self.s_bar = SmoothProgressBar()
        self.s_bar.setFixedHeight(4)
        self.s_bar.setMaximumWidth(220)
        sl.addWidget(self.s_bar, 1, Qt.AlignmentFlag.AlignVCenter)
        self.btn_expand = QPushButton()
        self.btn_expand.setObjectName("urgenthide")
        self.btn_expand.setToolTip(_("Show more"))
        self.btn_expand.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_expand.setFixedSize(22, 22)
        self.btn_expand.clicked.connect(lambda: self.set_collapsed(False))
        sl.addWidget(self.btn_expand, 0, Qt.AlignmentFlag.AlignVCenter)
        self.s_close = QPushButton("✕")
        self.s_close.setObjectName("urgenthide")
        self.s_close.setToolTip(_("Dismiss"))
        self.s_close.setFixedSize(22, 22)
        self.s_close.clicked.connect(self._clear_and_hide)
        self.s_close.hide()
        sl.addWidget(self.s_close, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addWidget(sm)
        sm.hide()
        self._collapsed = False

        head = self._head = QWidget()
        head.setObjectName("downloadhead")
        outer.addWidget(head)
        h = self._head_lay = QHBoxLayout(head)
        h.setContentsMargins(12, 10, 12, 10)
        h.setSpacing(12)

        # Thumbnail / icon
        self.thumb = QLabel()
        self.thumb.setFixedSize(THUMB_W, THUMB_H)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(self.thumb, 0, Qt.AlignmentFlag.AlignVCenter)
        # no picture of its own (an MP3, a link without art): Bun writes the download down
        self.scribe = ScribeBunny()
        h.addWidget(self.scribe, 0, Qt.AlignmentFlag.AlignVCenter)

        # Center column: pill, title and uploader on line 1, status and progress on line 2
        col = self._col = QVBoxLayout()
        col.setSpacing(LINE_GAP)   # room between the title and the bar
        col.setContentsMargins(0, 0, 0, 0)

        row1 = self._row1 = QHBoxLayout()
        row1.setSpacing(8)
        row1.setContentsMargins(0, 0, 0, 0)
        # every piece of line 1 hangs from the top by its own amount (_line_up), so the
        # words share one baseline and the pill and logo sit centred on the title
        self._drops: dict[QWidget, QSpacerItem] = {}

        def hang(w: QWidget, stretch: int = 0) -> QVBoxLayout:
            v = QVBoxLayout()
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(0)
            drop = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            v.addItem(drop)
            v.addWidget(w)
            self._drops[w] = drop
            row1.addLayout(v, stretch)
            return v

        self.pill = QLabel()
        self.pill.setObjectName("actionpill")
        self.pill.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        hang(self.pill)

        self.lbl_title = ElideLabel()
        self.lbl_title.setObjectName("downloadtitle")
        f = self.lbl_title.font()
        f.setBold(True)
        self.lbl_title.setFont(f)
        hang(self.lbl_title)

        self.src_icon = QLabel()   # where it's from: the site's logo, then its name
        self.src_icon.setFixedSize(14, 14)
        self.src_icon.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        hang(self.src_icon)
        self.lbl_src = QLabel()
        self.lbl_src.setObjectName("downloadmeta")
        hang(self.lbl_src)

        self.lbl_meta = ElideLabel()
        self.lbl_meta.setObjectName("downloadmeta")
        self.lbl_meta.hide()
        hang(self.lbl_meta, 1)
        row1.addStretch(1)   # a short title doesn't stretch the line
        row1.addSpacing(CORNER)   # line 1 stops short of the corner buttons
        # in the bar's top right corner, clear of the buttons on line 2 (resizeEvent):
        # minimise (set_collapsed), and ✕ once it's over
        self.btn_min = QPushButton(self)
        self.btn_min.setObjectName("urgenthide")
        self.btn_min.setToolTip(_("Hide"))
        self.btn_min.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_min.setFixedSize(22, 22)
        self.btn_min.clicked.connect(
            lambda: (usage.used("dl-bar-small"), self.set_collapsed(True)))
        self.btn_close = QPushButton("✕", self)
        self.btn_close.setObjectName("urgenthide")
        self.btn_close.setToolTip(_("Dismiss"))
        self.btn_close.setFixedSize(22, 22)
        self.btn_close.clicked.connect(self._clear_and_hide)
        self.btn_close.hide()
        col.addLayout(row1)

        row2 = self._row2 = QHBoxLayout()
        row2.setSpacing(10)
        row2.setContentsMargins(0, 0, 0, 0)

        # the bar first, one length whatever it says (BAR_W, less in a narrow window),
        # starting under line 1's words; what it's doing comes after it
        self.bar = SmoothProgressBar()
        self.bar.setMaximumWidth(BAR_W)
        self.bar.setMinimumWidth(BAR_MIN_W)
        row2.addWidget(self.bar, 1, Qt.AlignmentFlag.AlignVCenter)

        self.lbl_status = QLabel()
        self.lbl_status.setObjectName("downloadstatus")
        self.lbl_status.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        row2.addWidget(self.lbl_status, 0, Qt.AlignmentFlag.AlignVCenter)
        # what's left past the bar's length goes between the words and the buttons
        row2.addStretch(0)

        col.addLayout(row2)
        h.addLayout(col, 1)
        h.setAlignment(col, Qt.AlignmentFlag.AlignVCenter)   # the two lines together, in the middle

        # after the progress, on its line: the queue's button, Stop all, Cancel
        self.queue_badge = QPushButton()
        self.queue_badge.setObjectName("queuebadge")
        self.queue_badge.setCheckable(True)
        self.queue_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.queue_badge.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.queue_badge.toggled.connect(self._toggle_panel)
        self.queue_badge.hide()
        row2.addWidget(self.queue_badge, 0, Qt.AlignmentFlag.AlignVCenter)

        self.btn_stop_all = QPushButton(_("Stop all"))
        self.btn_stop_all.setObjectName("cancelbutton")
        self.btn_stop_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stop_all.clicked.connect(self._on_stop_all)
        self.btn_stop_all.hide()
        row2.addWidget(self.btn_stop_all, 0, Qt.AlignmentFlag.AlignVCenter)

        self.btn_retry = QPushButton(_("Retry"))   # it failed: try it again
        self.btn_retry.setObjectName("retrybutton")
        self.btn_retry.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_retry.clicked.connect(lambda: self._retry(self.url))
        self.btn_retry.hide()
        row2.addWidget(self.btn_retry, 0, Qt.AlignmentFlag.AlignVCenter)

        self.btn_cancel = QPushButton(_("Cancel"))
        self.btn_cancel.setObjectName("cancelbutton")
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.setToolTip(_("Cancel download"))
        self.btn_cancel.clicked.connect(self._on_cancel)
        row2.addWidget(self.btn_cancel, 0, Qt.AlignmentFlag.AlignVCenter)

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
        self.btn_panel_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_panel_stop.clicked.connect(self._on_stop_all)
        self.btn_panel_stop.hide()
        ph.addWidget(self.btn_panel_stop)
        pv.addLayout(ph)
        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("queuescroll")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        holder.setObjectName("queueholder")
        self.rows = QVBoxLayout(holder)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(4)
        self.scroll_area.setWidget(holder)
        pv.addWidget(self.scroll_area)
        outer.addWidget(self.panel)
        self.panel.hide()

    def retheme(self):
        T = theme.T
        card_bg = theme.mix(T["card"], T["accent"], 0.12)
        border = theme.mix(T["card"], T["accent"], 0.35)
        pill_bg = theme.mix(T["card"], T["accent"], 0.28)
        pill_color = T["live_text"]
        row_bg = theme.mix(card_bg, T["text"], 0.05)
        bad = theme.status("error")
        bad_edge = theme.mix(row_bg, bad, 0.45)

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
            f"QLabel#summaryname {{ color:{T['text_hi']}; font-size:8.5pt; font-weight:700; }}"
            f"QLabel#summaryfailed {{ color:{theme.status('error')}; font-size:8.5pt; "
            f"font-weight:700; }}"
            f"QPushButton#queuebadge {{ background:{T['btn']}; color:{T['text']}; "
            f"border:1px solid {T['border']}; border-radius:8px; padding:4px 10px; "
            f"font-size:8.5pt; font-weight:600; }}"
            f"QPushButton#queuebadge:hover, QPushButton#queuebadge:checked "
            f"{{ background:{T['btn_hover']}; }}"
            f"QPushButton#cancelbutton {{ background:transparent; border:1px solid {T['border']}; "
            f"border-radius:8px; padding:4px 12px; color:{T['muted']}; font-size:8.5pt; "
            f"font-weight:600; }}"
            f"QPushButton#cancelbutton:hover {{ background:{T['btn_hover']}; color:{T['text']}; }}"
            f"QPushButton#retrybutton {{ background:{theme.accent_fill()}; {theme.accent_edge()} "
            f"border-radius:8px; padding:4px 13px; color:{T['on_accent']}; font-size:8.5pt; "
            f"font-weight:700; }}"
            f"QPushButton#retrybutton:hover {{ background:{theme.accent_fill(hover=True)}; }}"
            f"QFrame#queuerow[failed=\"true\"] {{ border-color:{bad_edge}; }}"
            f"QLabel#failedtag {{ color:{bad}; font-size:8.5pt; font-weight:700; }}"
            f"QPushButton#urgenthide {{ background:transparent; border:none; color:{T['muted']}; "
            f"border-radius:6px; padding:0px; min-width:0px; font-size:10pt; }}"
            f"QPushButton#urgenthide:hover {{ background:{T['btn_hover']}; }}"
            f"QFrame#queuerow {{ background:{row_bg}; border:1px solid transparent; "
            f"border-radius:8px; }}"
            # lights up under the mouse like the app's other cards (More tabs)
            f"QFrame#queuerow:hover {{ background:{theme.mix(row_bg, T['text'], 0.06)}; "
            f"border-color:{T['border_hi']}; }}"
            f"QLabel#queueindex {{ color:{T['muted']}; font-size:8.5pt; font-weight:700; }}"
        )
        self.bar.update()
        for b, name in ((self.btn_min, "fold_up"), (self.btn_expand, "fold_open")):
            b.setIcon(QIcon(icons.pixmap(name, 16, T["muted"])))
        self.s_icon.setPixmap(self._icon("download"))
        self._line_up()
        self._update_queue_badge()
        if self.url:
            self._update_thumb()   # the plain icon is drawn in the theme's colour
            self.src_icon.setPixmap(self._icon(self._source[0]))
        if self.panel.isVisible():
            self._fill_rows()

    def _line_up(self):
        """Line 1 on one line: the title, the site's name and the uploader on the same
        baseline, the pill and the site's logo centred on the middle of the title's
        capitals. Worked out from the fonts the style sheet gave."""
        texts = (self.lbl_title, self.lbl_src, self.lbl_meta)
        for w in texts + (self.pill,):
            w.ensurePolished()
        cap_mid = QFontMetricsF(self.lbl_title.font()).capHeight() / 2
        # how far below its own top each piece's line (baseline, or middle) falls
        line_at = {}
        for w in texts:
            fm = QFontMetricsF(w.font())
            w.setFixedHeight(math.ceil(fm.height()))
            line_at[w] = (w.height() - fm.height()) / 2 + fm.ascent()
        line_at[self.pill] = self.pill.sizeHint().height() / 2 + cap_mid
        line_at[self.src_icon] = self.src_icon.height() / 2 + cap_mid
        base = max(line_at.values())
        for w, drop in self._drops.items():
            drop.changeSize(0, round(base - line_at[w]), QSizePolicy.Policy.Minimum,
                            QSizePolicy.Policy.Fixed)
        self._row1.invalidate()

    def paintEvent(self, ev):
        super().paintEvent(ev)
        if self.outcome.running() and not self.outcome.ok:
            # it failed: the background turns red for a moment, under the words, and fades
            red = QColor(theme.status("error"))
            fade = 1.0 - self.outcome.k()
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            fill = QColor(red)
            fill.setAlphaF(0.28 * fade)
            edge = QColor(red)
            edge.setAlphaF(fade)
            p.setPen(QPen(edge, 1.5))
            p.setBrush(fill)
            # the same rounded corners as the bar's own border
            p.drawRoundedRect(QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75), 12, 12)
            p.end()

    def set_collapsed(self, on: bool):
        """Minimised: just the summary line (and a thin bar) so the page below gets the
        room back; its chevron, or a click anywhere on it, opens it again."""
        self._collapsed = on and not self._mini
        if self._collapsed:
            self.queue_badge.setChecked(False)
        self._head.setVisible(not self._collapsed)
        self.summary.setVisible(self._collapsed)
        self._corner()
        self._sync_summary()

    def _corner(self):
        """The top right corner: minimise while it runs, ✕ once it's over; minimised,
        the slim line has its own."""
        done = self.stage == "done"
        self.btn_min.setVisible(not (done or self._mini or self._collapsed))
        self.btn_close.setVisible(done and not self._collapsed)
        self.s_close.setVisible(done)

    def _queued_text(self) -> str:
        n = len(self._queue)
        return ngettext("+{count} queued", "+{count} queued", n, count=n) if n else ""

    def _failed_text(self) -> str:
        n = len(self._failed)
        return ngettext("{n} failed", "{n} failed", n) if n else ""

    def _sync_summary(self):
        """The minimised line: which song, how far it's got, how many wait, how many
        failed (in red)."""
        bits = [x for x in (self.title, self.lbl_status.text(), self._queued_text()) if x]
        self.s_text.setText(" · ".join(bits))
        self.s_text.setToolTip(self.title)
        failed = self._failed_text()
        self.s_failed.setText("· " + failed if failed else "")
        self.s_failed.setVisible(bool(failed))
        if self.bar._mode == "indeterminate":
            self.s_bar.set_indeterminate(True)
        else:
            self.s_bar.set_progress(self.bar._progress)

    def showEvent(self, ev):
        super().showEvent(ev)
        self.shown_changed.emit(True)

    def hideEvent(self, ev):
        super().hideEvent(ev)
        self.shown_changed.emit(False)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.outcome.setGeometry(self.rect())
        for b in (self.btn_min, self.btn_close):
            b.move(self.width() - b.width() - 6, 6)
            b.raise_()
        self._fit_tight()
        self._show_meta()

    def _fit_tight(self):
        """In a narrow window the banner drops what it can do without, like the mini
        player's: the site's name (its logo stays), Stop all (it moves into the queue
        list) and the word "queued"."""
        tight = self._mini or self.width() < TIGHT_BELOW
        if tight == self._tight:
            return
        self._tight = tight
        self.lbl_src.setVisible(not tight)
        self._update_queue_badge()

    def set_mini(self, mini: bool):
        """The mini player's narrow bar: no picture, the site as just its logo, and its
        Stop all in the queue list (no room for it beside Cancel)."""
        self._mini = mini
        self._tight = not mini   # makes _fit_tight apply it
        self._fit_tight()
        self._corner()   # no minimise: the mini player's bar is short already
        self.retheme()   # also lines line 1 up again
        self._apply_art()
        self._head_lay.setContentsMargins(*((8, 6, 8, 6) if mini else (12, 10, 12, 10)))
        self._col.setSpacing(2 if mini else LINE_GAP)
        self._head_lay.setSpacing(8 if mini else 12)
        self._update_queue_badge()
        self._show_meta()

    def _show_meta(self):
        """The uploader and length come after the title once the banner is wide."""
        self.lbl_meta.setVisible(bool(self._meta) and not self._mini
                                 and self.width() >= WIDE_AT)

    @_after_hold
    def set_active(self, url: str, title: str, kind: str, thumb_pm: QPixmap | None = None,
                   channel: str = "", seconds: float = 0.0):
        self._show_card(url, title, kind, thumb_pm, channel, seconds)
        self.scribe.reset()
        self.btn_cancel.show()
        self.btn_retry.hide()
        self._corner()
        self.lbl_status.setText(_("Parsing video…"))
        self.bar.set_indeterminate(True)
        self._update_queue_badge()
        self._sync_summary()
        self.show()

    def _show_card(self, url, title, kind, thumb_pm, channel, seconds):
        self._auto_hide.stop()
        self.outcome.stop()
        self._raw = (title, seconds)
        self.url = url
        self.title = pretty_title(title) or _("Sound")
        self.kind = kind
        self.stage = "parsing"
        self.progress_frac = 0.0
        self._pm = thumb_pm
        self._source = source_of(url)
        self.lbl_src.setText(self._source[1])
        self.src_icon.setPixmap(self._icon(self._source[0]))
        self.src_icon.setToolTip(self._source[1])

        self.lbl_title.setText(self.title)
        self.lbl_title.setToolTip(self.title)
        meta = " · ".join(x for x in (channel, fmt_time(seconds) if seconds else "") if x)
        self._meta = "· " + meta if meta else ""
        self.lbl_meta.setText(self._meta)
        self._show_meta()
        pill_text = _("Play once") if kind == "play" else _("Add as sound")
        self.pill.setText(pill_text)
        self._update_thumb()

    @_after_hold
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
        self._sync_summary()
        self.show()

    @_after_hold
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

    @_after_hold
    def set_queue(self, queue: list[dict]):
        self._queue = list(queue)
        self._update_queue_badge()
        self._sync_summary()
        if self.panel.isVisible():
            self._fill_rows()

    def _others_failed(self) -> list[dict]:
        """The picks that failed, but not the one on the card (it says so itself)."""
        return [f for f in self._failed if f["url"] != self.url]

    def _failed_text_for(self, failed: list[dict]) -> str:
        n = len(failed)
        return ngettext("{n} failed", "{n} failed", n) if n else ""

    def _update_queue_badge(self):
        failed = self._others_failed()
        if not self._queue and not failed:
            self.queue_badge.setChecked(False)
            self.queue_badge.hide()
            self.btn_stop_all.hide()
            self.btn_panel_stop.hide()
            self.panel.hide()
            return
        if self._tight:   # "+2 · ✗ 1": the tooltip and the list say the rest
            short = [f"+{len(self._queue)}" if self._queue else "",
                     f"✗ {len(failed)}" if failed else ""]
            self.queue_badge.setText(" · ".join(x for x in short if x))
        else:
            self.queue_badge.setText(" · ".join(x for x in (self._queued_text(),
                                                            self._failed_text_for(failed)) if x))
        self.queue_badge.setIcon(QIcon(icons.pixmap(
            "fold_open" if self.queue_badge.isChecked() else "fold", 14, theme.T["muted"])))
        names = [pretty_title(item.get("title", "")) or _("Sound") for item in self._queue]
        self.queue_badge.setToolTip("\n".join(([_("Up next")] + [f"• {n_}" for n_ in names])
                                              if names else [self._failed_text_for(failed)]))
        self.queue_badge.show()
        self.btn_stop_all.setVisible(bool(self._queue) and not self._tight)
        self.btn_panel_stop.setVisible(bool(self._queue) and self._tight)
        if self.panel.isVisible():
            self._fill_rows()

    def _toggle_panel(self, on: bool):
        has = bool(self._queue or self._others_failed())
        if on and has:
            self._fill_rows()
        self.panel.setVisible(on and has)
        self.queue_badge.setIcon(QIcon(icons.pixmap(
            "fold_open" if on else "fold", 14, theme.T["muted"])))

    def _fill_rows(self):
        """The queue list, rebuilt: the picks waiting, then the ones that failed (each
        with Retry). A handful of rows (the queue is capped), and only while it's open."""
        while self.rows.count():
            item = self.rows.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.deleteLater()
        failed = self._others_failed()
        for i, q in enumerate(self._queue + failed, 1):
            bad = i > len(self._queue)
            row = _QueueRow()
            row.setObjectName("queuerow")
            if not bad and i > 1:   # the first one is next up already
                row.setCursor(Qt.CursorShape.PointingHandCursor)
                row.setToolTip(_("Download this one next"))
                row.clicked.connect(lambda u=q["url"]: self.front_requested.emit(u))
            row.setProperty("failed", bad)
            row.setAttribute(Qt.WidgetAttribute.WA_Hover)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(8, 4, 6, 4)
            rl.setSpacing(8)
            idx = QLabel("✗" if bad else str(i))
            idx.setObjectName("failedtag" if bad else "queueindex")
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
            if bad:
                why = QLabel(_("Couldn't download"))
                why.setObjectName("failedtag")
                rl.addWidget(why)
                again = QPushButton(_("Retry"))
                again.setObjectName("retrybutton")
                again.setCursor(Qt.CursorShape.PointingHandCursor)
                again.clicked.connect(lambda _c=False, u=q["url"]: self._retry(u))
                rl.addWidget(again)
            else:
                kind = QLabel(_("Play once") if q.get("kind") == "play" else _("Add as sound"))
                kind.setObjectName("actionpill")
                kind.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                rl.addWidget(kind)
            x = QPushButton("✕")
            x.setObjectName("urgenthide")
            x.setToolTip(_("Remove"))
            x.setCursor(Qt.CursorShape.PointingHandCursor)
            x.setFixedSize(24, 24)
            x.clicked.connect(lambda _c=False, u=q["url"], b=bad: self._forget(u) if b
                              else (usage.used("dl-cancel"), self.cancel_requested.emit(u)))
            rl.addWidget(x)
            self.rows.addWidget(row)
        self.rows.addStretch(1)
        # as tall as the first few rows really are (a failed one's Retry is taller)
        rows = []
        for i in range(self.rows.count() - 1):
            item = self.rows.itemAt(i)
            w = item.widget() if item else None
            assert w is not None   # a row each (the stretch is last)
            rows.append(w)
        shown = rows[:QUEUE_ROWS]
        self.scroll_area.setFixedHeight(sum(r.sizeHint().height() for r in shown)
                                   + max(0, len(shown) - 1) * self.rows.spacing())

    def _retry(self, url: str):
        """Retry: the failed pick is picked again (it starts, or waits its turn)."""
        item = next((f for f in self._failed if f["url"] == url), None)
        if item is None:
            return
        self._forget(url)
        usage.used("dl-retry")
        self.retry_requested.emit(dict(item))

    def _forget(self, url: str):
        self._failed = [f for f in self._failed if f["url"] != url]
        self._update_queue_badge()
        self._sync_summary()

    @_after_hold
    def set_failed(self, url: str, kind: str):
        """The download for `url` ended in an error (its set_done(False) follows): unlike
        a Cancel, or a newer Play taking over, this one gets the red flash and Retry."""
        self._failing = url

    @_after_hold
    def set_done(self, url: str, kind: str, ok: bool):
        if url != self.url or self.stage == "done":
            return
        failed = not ok and self._failing == url
        self._failing = ""
        if not ok and not failed:   # stopped (Cancel, a newer pick): no flash, no Retry
            if self._cancelling != url:
                self._ended_quietly()
            return
        self.stage = "done"
        self.scribe.finish(ok)
        self.btn_cancel.hide()
        self._corner()
        # a second of tick (or red ✗ and a red glow) over the picture so it's noticed; the
        # mini player has no picture: just the glow when it failed
        spot = QRectF()
        art = next((w for w in (self.thumb, self.scribe) if w.isVisibleTo(self)), None)
        if art is not None:
            top_left = art.mapTo(self, art.rect().topLeft())
            spot = QRectF(top_left.x(), top_left.y(), art.width(), art.height())
        if spot.isValid() or failed:
            self.outcome.play(ok, spot)
        # what comes next (the next pick, the queue moving up) waits for the flash
        self._held = []
        self._hold.start(Outcome.SHOW_MS)

        if ok:
            self.btn_retry.hide()
            self.bar.set_progress(1.0)
            if kind == "play":
                self.lbl_status.setText(_("▶ Playing"))
            else:
                self.lbl_status.setText(_("✓ Added to your sounds"))
            if not self._others_failed():   # the failed ones wait for Retry or ✕
                self._auto_hide.start(7000 if kind == "play" else 4000)
        else:
            self._failed = [f for f in self._failed if f["url"] != url] + [{
                "url": url, "title": self._raw[0], "kind": kind, "seconds": self._raw[1]}]
            self._show_failed_state()
        self._update_queue_badge()
        self._sync_summary()

    def _show_failed_state(self):
        self.stage = "done"
        self.lbl_status.setText(_("Couldn't download"))
        self.bar.set_progress(0.0)
        self.btn_cancel.hide()
        self.btn_retry.show()
        self._corner()

    def _release(self):
        """The flash is over: play out what waited, in order (one may be another finish,
        which holds the rest again)."""
        held, self._held = self._held or [], None
        while held:
            method, args = held.pop(0)
            method(self, *args)
            if self._held is not None:
                self._held[:0] = held
                return

    def _ended_quietly(self):
        """The running pick stopped without failing: the next pick takes over (it's
        about to start), else a failed one waiting for Retry shows, else the bar goes."""
        if self._queue:
            return
        if self._failed:
            f = self._failed[-1]
            self._show_card(f["url"], f["title"], f["kind"], self.thumb_lookup(f["url"]),
                            "", f["seconds"])
            self.scribe.finish(False)
            self._show_failed_state()
            self._update_queue_badge()
            self._sync_summary()
            return
        self._clear_and_hide()

    def _on_cancel(self):
        usage.used("dl-cancel")
        url = self._cancelling = self.url
        self.cancel_requested.emit(url)
        self._cancelling = ""
        if self.url == url:   # nothing took its place (the next pick would have set_active)
            self._ended_quietly()

    def _on_stop_all(self):
        usage.used("dl-cancel")
        self._cancelling = self.url
        self.stop_all_requested.emit()
        self._cancelling = ""
        self._clear_and_hide()

    def _clear_and_hide(self):
        self._auto_hide.stop()
        self._hold.stop()
        self._held = None
        self.outcome.stop()
        self.url = ""
        self.title = ""
        self.stage = ""
        self._queue = []
        self._failed = []
        self._failing = ""
        self._pm = None
        self._meta = ""
        self.btn_retry.hide()
        self._update_queue_badge()
        self.set_collapsed(False)   # the next download opens full size again
        self.hide()
