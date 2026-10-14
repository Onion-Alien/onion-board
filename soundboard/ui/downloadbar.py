"""The global download progress bar: sits at the top of the main window above all tabs
(and in the mini player), showing real-time download and preparation progress for
web links and search cards clicked by the user.

Shows:
- A summary line: "Adding 3 sounds", how many failed (a red pill), Stop all, minimise
- One list under it, a row per pick:
  - the one downloading now: its picture (or Bun), title, what it'll do ("Adding to
    sounds"), a smooth bar (a gliding shimmer while it's parsed or converted) and how far
  - the ones waiting ("Waiting to add"; a click makes one next up), each with its ✕
  - the ones that failed, each with Retry, and the ones added already
"""
from __future__ import annotations

import math
import re
import time
import urllib.parse
from collections.abc import Callable

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import (QColor, QFontMetricsF, QLinearGradient, QPainter,
                           QPainterPath, QPalette, QPen, QPixmap)
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSizePolicy, QSpacerItem, QVBoxLayout, QWidget)

from soundboard import jobprogress, theme, usage
from soundboard.i18n import _, ngettext
from soundboard.ui import icons
from soundboard.ui.scribebun import ScribeBunny
from soundboard.ui.widgets import fmt_time
from soundboard.ui.pixels import snap_to_pixels


BAR_W = 480   # the progress bar's length in the banner
LINE_GAP = 6  # between line 1 (the title) and line 2 (the bar); the mini player: 4


class SmoothProgressBar(QWidget):
    """A sleek 6px progress bar that only fills forward (soundboard/jobprogress.py). While
    a step has nothing to measure (the link looked up, the audio converted) a faint glint
    runs along the empty part, so it's plainly busy, never a block that looks full."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(6)
        self._busy = True
        self._progress = 0.0          # 0.0 .. 1.0
        self._t0 = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(1000 // 30)
        self._timer.timeout.connect(self.update)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_busy(self, on: bool):
        """The glint over the empty part: on while a step can't say how far it is."""
        if on and not self._busy:
            self._t0 = time.monotonic()
        self._busy = on
        if on and self.isVisible():
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def set_progress(self, frac: float, busy: bool = False):
        self._progress = max(0.0, min(1.0, float(frac)))
        self.set_busy(busy)

    def showEvent(self, ev):
        super().showEvent(ev)
        if self._busy:
            self._timer.start()

    def hideEvent(self, ev):
        self._timer.stop()
        super().hideEvent(ev)

    def sizeHint(self) -> QSize:
        return QSize(180, 6)

    def paintEvent(self, _e):
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        rad = r.height() / 2
        p.setPen(Qt.PenStyle.NoPen)
        groove = QColor(theme.T.get("groove", theme.mix(theme.T["card"], theme.T["text"], 0.12)))
        p.setBrush(groove)
        p.drawRoundedRect(r, rad, rad)

        accent = QColor(theme.T.get("accent", "#7c5cff"))
        w = r.width() * self._progress
        if w > 0:
            p.setBrush(accent)
            p.drawRoundedRect(QRectF(r.left(), r.top(), max(r.height(), w), r.height()),
                              rad, rad)
        if self._busy:
            # a soft glint sweeping the empty part, faded at both ends: busy, not further
            empty = QRectF(r.left() + w, r.top(), r.width() - w, r.height())
            if empty.width() > r.height():
                k = ((time.monotonic() - self._t0) / 1.6) % 1.0
                gw = max(r.height() * 4, empty.width() * 0.3)
                gx = empty.left() - gw + (empty.width() + gw) * k
                g = QLinearGradient(gx, 0, gx + gw, 0)
                clear, lit = QColor(accent), QColor(accent)
                clear.setAlpha(0)
                lit.setAlpha(110)
                g.setColorAt(0.0, clear)
                g.setColorAt(0.5, lit)
                g.setColorAt(1.0, clear)
                p.save()
                clip = QPainterPath()
                clip.addRoundedRect(r, rad, rad)
                p.setClipPath(clip)
                p.setClipRect(empty, Qt.ClipOperation.IntersectClip)
                p.setBrush(g)
                p.drawRect(QRectF(gx, r.top(), gw, r.height()))
                p.restore()
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
        snap_to_pixels(p)
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, self.width())
        self.style().drawItemText(p, self.rect(),
                                  int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                                  self.palette(), self.isEnabled(), text,
                                  QPalette.ColorRole.WindowText)
        p.end()


class KindTag(QWidget):
    """What a pick will do, as a status (an icon and a few words in the accent colour,
    no box): a filled "Add as sound" pill looked like a button to press."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("kindtag")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.icon = QLabel()
        self.icon.setFixedSize(12, 12)
        self.text = QLabel()
        self.text.setObjectName("kindtag")
        lay.addWidget(self.icon)
        lay.addWidget(self.text)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.kind, self.queued = "", False

    def set_kind(self, kind: str, queued: bool = False):
        self.kind, self.queued = kind, queued
        if queued:   # only Add as sound waits in the queue (Play once never does)
            text = _("Waiting to add")
            tip = _("Becomes a new sound on your board after the ones before it. "
                    "Nothing to press.")
        elif kind == "play":
            text = _("Playing once")
            tip = _("Plays once when it's ready. It isn't added to your sounds.")
        else:
            text = _("Adding to sounds")
            tip = _("Becomes a new sound on your board when it's ready. Nothing to press.")
        self.text.setText(text)
        self.setToolTip(tip)
        self.retheme()

    def retheme(self):
        icons.set_label_icon(self.icon, "play" if self.kind == "play" and not self.queued
                             else "plus", "live_text", size=12)


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
        snap_to_pixels(p)
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


THUMB_W, THUMB_H = 64, 36     # the running pick's picture
ROW_THUMB = (48, 27)          # and the other rows' ones
WIDE_AT = 720                 # the banner is this wide or more: the uploader and length show
TIGHT_BELOW = 640             # narrower: the rows drop their pictures (as in the mini player)
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


SOFT = 0.5   # the glow's strength when the theme's cards aren't its accent's colour


def theme_matches_accent() -> bool:
    """The theme's own cards are a shade of its accent: Lava's dark orange cards and
    orange accent, Ocean's navy and cyan. Then the banner's accent glow is the theme's
    look and shows in full; on Dark (near-black cards, a purple accent), Light or Royal
    (gold on violet) the same glow was all anyone saw, so it shows at half."""
    card, accent = QColor(theme.T["card"]), QColor(theme.T["accent"])
    hc, ha = card.hsvHueF(), accent.hsvHueF()
    if hc < 0 or ha < 0:   # a grey: no colour to match
        return False
    colour = card.hsvSaturationF() * card.valueF()   # how far from grey the cards are
    presence = max(0.0, min(1.0, (colour - 0.04) / 0.1))
    same_hue = max(0.0, math.cos(abs(hc - ha) * 2 * math.pi))   # 1 = the same colour
    return presence * same_hue >= 0.6


def glow() -> float:
    """The accent glow's strength: 1 on a theme it matches, else SOFT."""
    return 1.0 if theme_matches_accent() else SOFT


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
    """The banner's summary line ("Adding 3 sounds"). Minimised, it's all that shows, and
    a click on it opens the list again."""
    clicked = Signal()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(ev)


class DownloadBar(QFrame):
    """The persistent top bar: a summary line ("Adding 3 sounds", how many failed) over
    one list with a row per pick: the one downloading now with its bar, then the ones
    waiting, the ones that failed (each with Retry) and the ones added already."""
    cancel_requested = Signal(str)  # (url to cancel, or "" for active)
    stop_all_requested = Signal()   # the running download and every pick waiting
    play_requested = Signal()
    shown_changed = Signal(bool)   # the bar appeared / went away
    room_changed = Signal()        # it needs more or less height: the window fits it again
    retry_requested = Signal(dict)  # a pick that failed: {url, title, kind, seconds}
    front_requested = Signal(str)   # a waiting pick clicked in the list: it's next up

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("downloadbar")
        self.url = ""
        self.title = ""
        self.kind = ""  # "play" or "add"
        self.stage = ""  # "parsing", "downloading", "processing", "done"
        self.progress_frac = 0.0   # the running pick's one bar (jobprogress), 0..1
        self._job = jobprogress.JobProgress()
        self._mini = False
        self._tight = False   # _fit_tight: a narrow banner (or the mini player's)
        self._collapsed = False
        self._room = "open"   # fit_steps: what the window has room for
        self._room_folds: set[str] = set()
        self._shown_rows = 0   # rows under the running one the list is tall for
        self._queue: list[dict] = []
        self._failed: list[dict] = []   # picks that couldn't download, to retry
        self._added: list[dict] = []    # picks added to the sounds since the bar showed
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
        self.thumb_lookup: Callable[[str], QPixmap | None] = lambda url: None

        self._auto_hide = QTimer(self)
        self._auto_hide.setSingleShot(True)
        self._auto_hide.timeout.connect(self._clear_and_hide)

        self._build_ui()
        self.outcome = Outcome(self)
        self.retheme()
        self.hide()

    # ------------------------------------------------------------------ building

    def _icon_button(self, name: str, tip: str, side: int = 28) -> QPushButton:
        b = QPushButton()
        b.setObjectName("dlicon")
        b.setAccessibleName(tip)   # no tooltip: ■, ✕ and the fold arrow say it
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFixedSize(side, side)
        icons.set_icon(b, name, "muted", size=18 if side >= 28 else 16)
        return b

    def _build_ui(self):
        outer = self._outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(4)

        # The summary line: what the whole list is up to, how many failed, and the
        # buttons for all of it. Minimised, it's all that shows (with a thin bar); a
        # click on it opens the list again.
        head = self.summary = _Summary()
        head.setObjectName("downloadhead")
        head.setCursor(Qt.CursorShape.PointingHandCursor)
        head.clicked.connect(lambda: self._collapsed and self.set_collapsed(False))
        hl = self._head_lay = QHBoxLayout(head)
        hl.setContentsMargins(6, 0, 0, 0)
        hl.setSpacing(8)
        self.h_icon = QLabel()
        self.h_icon.setFixedSize(18, 18)
        hl.addWidget(self.h_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        self.h_text = ElideLabel()
        self.h_text.setObjectName("downloadhead")
        hl.addWidget(self.h_text, 0, Qt.AlignmentFlag.AlignVCenter)
        self.h_failed = QLabel()
        self.h_failed.setObjectName("pill")
        theme.set_tone(self.h_failed, "error")
        self.h_failed.hide()
        hl.addWidget(self.h_failed, 0, Qt.AlignmentFlag.AlignVCenter)
        hl.addStretch(1)
        # how far the whole list has got, as a thin bar and a number
        self.s_bar = SmoothProgressBar()
        self.s_bar.setFixedHeight(4)
        self.s_bar.setMaximumWidth(160)
        self.s_bar.hide()
        hl.addWidget(self.s_bar, 1, Qt.AlignmentFlag.AlignVCenter)
        self.s_text = QLabel()
        self.s_text.setObjectName("hint")
        self.s_text.hide()
        hl.addWidget(self.s_text, 0, Qt.AlignmentFlag.AlignVCenter)
        self.btn_stop_all = self._icon_button("stop_all", _("Stop all"))
        self.btn_stop_all.clicked.connect(self._on_stop_all)
        self.btn_stop_all.hide()
        hl.addWidget(self.btn_stop_all, 0, Qt.AlignmentFlag.AlignVCenter)
        self.btn_min = self._icon_button("fold_up", _("Hide"))
        self.btn_min.clicked.connect(lambda: self.set_collapsed(not self._collapsed))
        hl.addWidget(self.btn_min, 0, Qt.AlignmentFlag.AlignVCenter)
        self.btn_close = self._icon_button("close", _("Dismiss"))
        self.btn_close.clicked.connect(self._clear_and_hide)
        self.btn_close.hide()
        hl.addWidget(self.btn_close, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addWidget(head)

        # The list: the running pick's row (built once, it changes in place), then a
        # row each for the rest
        self.panel = QWidget()
        self.panel.setObjectName("queuepanel")
        pv = QVBoxLayout(self.panel)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(4)

        cur = self.cur_row = QFrame()
        cur.setObjectName("queuerow")
        cur.setProperty("running", True)
        h = self._cur_lay = QHBoxLayout(cur)
        h.setContentsMargins(8, 8, 6, 8)
        h.setSpacing(12)
        # Bun first, always: he writes the download down and shows how it went (the
        # picture beside him stays clean); then the sound's picture, or the plain
        # placeholder the rows use, in the column the rows' pictures line up under
        self.scribe = ScribeBunny()
        self._scribe_box = QWidget()
        self._scribe_box.setObjectName("scribebox")
        self._scribe_box.setStyleSheet("background: transparent;")
        self._scribe_box.setFixedWidth(THUMB_W)
        sb = QHBoxLayout(self._scribe_box)
        sb.setContentsMargins(0, 0, 0, 0)
        sb.addWidget(self.scribe, 0, Qt.AlignmentFlag.AlignCenter)
        h.addWidget(self._scribe_box, 0, Qt.AlignmentFlag.AlignVCenter)
        self.thumb = QLabel()
        self.thumb.setFixedSize(THUMB_W, THUMB_H)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(self.thumb, 0, Qt.AlignmentFlag.AlignVCenter)

        col = self._col = QVBoxLayout()
        col.setSpacing(LINE_GAP)
        col.setContentsMargins(0, 0, 0, 0)
        row1 = self._row1 = QHBoxLayout()
        row1.setSpacing(8)
        row1.setContentsMargins(0, 0, 0, 0)
        # every piece of line 1 hangs from the top by its own amount (_line_up), so the
        # words share one baseline and the site's logo sits centred on the title
        self._drops: dict[QWidget, QSpacerItem] = {}

        def hang(w: QWidget, stretch: int = 0):
            v = QVBoxLayout()
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(0)
            drop = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            v.addItem(drop)
            v.addWidget(w)
            self._drops[w] = drop
            row1.addLayout(v, stretch)

        self.lbl_title = ElideLabel()
        self.lbl_title.setObjectName("downloadtitle")
        hang(self.lbl_title)
        self.src_icon = QLabel()   # where it's from: the site's logo (its name: tooltip)
        self.src_icon.setFixedSize(14, 14)
        self.src_icon.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        hang(self.src_icon)
        self.lbl_meta = ElideLabel()   # the uploader and length
        self.lbl_meta.setObjectName("downloadmeta")
        self.lbl_meta.hide()
        hang(self.lbl_meta, 1)
        row1.addStretch(1)
        col.addLayout(row1)

        # line 2: what it'll do, the bar, how far (or how it ended)
        row2 = self._row2 = QHBoxLayout()
        row2.setSpacing(10)
        row2.setContentsMargins(0, 0, 0, 0)
        self.pill = KindTag()
        row2.addWidget(self.pill, 0, Qt.AlignmentFlag.AlignVCenter)
        self.bar = SmoothProgressBar()
        self.bar.setMaximumWidth(BAR_W)
        self.bar.setMinimumWidth(BAR_MIN_W)
        row2.addWidget(self.bar, 1, Qt.AlignmentFlag.AlignVCenter)
        self.lbl_status = QLabel()
        self.lbl_status.setObjectName("downloadstatus")
        self.lbl_status.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        row2.addWidget(self.lbl_status, 0, Qt.AlignmentFlag.AlignVCenter)
        row2.addStretch(1)   # past the bar's length: room, not a gap before the number
        # as tall with the pill as without it (hidden when a pick ends): the title above
        # mustn't hop up when one ends and down when the next starts
        row2.addStrut(self.pill.sizeHint().height())
        col.addLayout(row2)
        h.addLayout(col, 1)
        h.setAlignment(col, Qt.AlignmentFlag.AlignVCenter)

        self.btn_retry = QPushButton(_("Retry"))   # it failed: try it again
        self.btn_retry.setObjectName("retrybutton")
        self.btn_retry.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_retry.clicked.connect(lambda: self._retry(self.url))
        self.btn_retry.hide()
        h.addWidget(self.btn_retry, 0, Qt.AlignmentFlag.AlignVCenter)
        self.btn_cancel = self._icon_button("close", _("Cancel download"), 24)
        self.btn_cancel.clicked.connect(self._on_cancel)
        h.addWidget(self.btn_cancel, 0, Qt.AlignmentFlag.AlignVCenter)
        pv.addWidget(cur)

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
        self.scroll_area.hide()
        pv.addWidget(self.scroll_area)
        outer.addWidget(self.panel)

    # ------------------------------------------------------------------ looks

    def retheme(self):
        T = theme.T
        k = glow()
        card_bg = theme.mix(T["card"], T["accent"], 0.12 * k)
        border = theme.mix(T["card"], T["accent"], 0.38 * k)
        row_bg = theme.mix(card_bg, T["text"], 0.05)
        bad = theme.status("error")

        self.setStyleSheet(
            f"QFrame#downloadbar {{ background:{card_bg}; border:1px solid {border}; "
            f"border-radius:12px; }}"
            + self._gradient_css(row_bg) +
            f"QWidget#downloadhead, QWidget#queuepanel, QWidget#queueholder, "
            f"QScrollArea#queuescroll {{ background:transparent; border:none; }}"
            # words sit on the banner (the flat themes give every widget a background)
            f"QFrame#downloadbar QLabel {{ background:transparent; }}"
            f"QLabel#downloadhead {{ color:{T['text_hi']}; font-weight:600; }}"
            f"QLabel#kindtag {{ color:{T['live_text']}; font-size:8.5pt; font-weight:600; }}"
            f"QLabel#downloadtitle {{ color:{T['text_hi']}; font-weight:600; }}"
            f"QLabel#queuetitle {{ color:{T['text']}; }}"
            f"QLabel#queuetitle[waiting=\"true\"] {{ color:{T['muted']}; }}"
            f"QLabel#downloadmeta {{ color:{T['muted']}; font-size:8.5pt; }}"
            f"QLabel#downloadstatus {{ color:{T['text']}; font-size:8.5pt; font-weight:600; }}"
            f"QLabel#downloadstatus[tone=\"ok\"] {{ color:{theme.status('ok')}; }}"
            f"QLabel#downloadstatus[tone=\"error\"] {{ color:{bad}; }}"
            f"QPushButton#dlicon {{ background:transparent; border:none; border-radius:8px; "
            f"padding:0px; }}"
            f"QPushButton#dlicon:hover {{ background:{T['btn_hover']}; }}"
            f"QPushButton#dlicon:pressed {{ background:{T['btn_press']}; }}"
            f"QPushButton#retrybutton {{ background:{T['btn']}; border:none; border-radius:8px; "
            f"padding:2px 10px; color:{T['text']}; font-size:8pt; font-weight:600; }}"
            f"QPushButton#retrybutton:hover {{ background:{T['btn_hover']}; }}"
            f"QPushButton#retrybutton[main=\"true\"] {{ background:{theme.accent_fill()}; "
            f"{theme.accent_edge()} color:{T['on_accent']}; }}"
            f"QPushButton#retrybutton[main=\"true\"]:hover "
            f"{{ background:{theme.accent_fill(hover=True)}; }}"
            f"QFrame#queuerow {{ background:transparent; border:1px solid transparent; "
            f"border-radius:8px; }}"
            f"QFrame#queuerow[running=\"true\"] {{ background:{row_bg}; }}"
            # lights up under the mouse like the app's other cards (More tabs)
            f"QFrame#queuerow:hover {{ background:{theme.mix(row_bg, T['text'], 0.06)}; "
            f"border-color:{T['border_hi']}; }}"
            + self._row_gradient_css(row_bg)
        )
        self.bar.update()
        self._fold_icon()
        self.pill.retheme()
        self._line_up()
        self._sync_head()
        if self.url:
            self._update_thumb()   # the plain icon is drawn in the theme's colour
            self.src_icon.setPixmap(self._icon(self._source[0]))
        self._fill_rows()

    def _gradient_css(self, row_bg: str) -> str:
        """The banner as one of the theme's designed surfaces: the accent lit at the top
        left fading into the theme's second colour, a light rim on top. How it ended
        tints the lit corner: green when added, red when it failed (state below). The
        outlined theme (High Contrast) stays flat."""
        if not theme.polished():
            return ""
        T, mix = theme.T, theme.mix
        base = T["card"]
        a, a2 = T["accent"], T.get("accent2") or T["accent"]
        ok, bad = theme.status("ok"), theme.status("error")
        k = glow()   # soft unless the theme's cards share the accent's colour
        mid = mix(base, a, 0.12 * k)
        end = mix(base, a2, 0.14 * k)
        rim = mix(mix(base, a, 0.45 * k), "#ffffff", 0.18 * k)

        def grad(top, middle, last):
            return (f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {top}, "
                    f"stop:0.45 {middle}, stop:1 {last})")
        # added / failed: a light green / red at half on every theme (they're never the
        # theme's colours); failed is red the whole way across, so it still reads as red
        # in red themes (Blood Moon), and the red words, pill and Retry say the rest
        return (f"QFrame#downloadbar {{ background:{grad(mix(base, a, 0.26 * k), mid, end)}; "
                f"border-color:{mix(base, a, 0.38 * k)}; border-top-color:{rim}; }}"
                f"QFrame#downloadbar[ended=\"ok\"] {{ "
                f"background:{grad(mix(base, ok, 0.22 * SOFT), mid, end)}; "
                f"border-color:{mix(base, ok, 0.45 * SOFT)}; }}"
                f"QFrame#downloadbar[ended=\"failed\"] {{ background:"
                f"{grad(mix(base, bad, 0.26 * SOFT), mix(base, bad, 0.14 * SOFT),
                        mix(base, bad, 0.08 * SOFT))}; "
                f"border-color:{mix(base, bad, 0.65 * SOFT)}; }}")

    def _row_gradient_css(self, row_bg: str) -> str:
        """The running row lit from the left in the accent; the others plain until the
        mouse is on them."""
        if not theme.polished():
            return ""
        T, mix = theme.T, theme.mix
        k = glow()
        hover = mix(row_bg, T["text"], 0.06)

        def lit(left, rest):
            return (f"qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {left}, "
                    f"stop:0.5 {rest}, stop:1 {rest})")
        return (f"QFrame#queuerow[running=\"true\"] {{ "
                f"background:{lit(mix(row_bg, T['accent'], 0.16 * k), row_bg)}; "
                f"border-color:{mix(row_bg, T['text'], 0.07)}; }}"
                f"QFrame#queuerow:hover {{ background:"
                f"{lit(mix(hover, T['accent'], 0.24 * k), hover)}; "
                f"border-color:{T['border_hi']}; }}")

    def _set_ended(self, how: str):
        """"ok", "failed" or "" (running): the banner's gradient follows it."""
        if self.property("ended") == how:
            return
        self.setProperty("ended", how)
        self.style().unpolish(self)
        self.style().polish(self)

    def _line_up(self):
        """Line 1 on one line: the title and the uploader on the same baseline, the
        site's logo centred on the middle of the title's capitals. Worked out from the
        fonts the style sheet gave."""
        texts = (self.lbl_title, self.lbl_meta)
        for w in texts:
            w.ensurePolished()
        cap_mid = QFontMetricsF(self.lbl_title.font()).capHeight() / 2
        line_at = {}
        for w in texts:
            fm = QFontMetricsF(w.font())
            w.setFixedHeight(math.ceil(fm.height()))
            line_at[w] = (w.height() - fm.height()) / 2 + fm.ascent()
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
            snap_to_pixels(p)
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

    # ------------------------------------------------------------------ the summary line

    def set_collapsed(self, on: bool):
        """Minimised: just the summary line (and a thin bar) so the page below gets the
        room back; its chevron, or a click anywhere on it, opens it again."""
        self._collapsed = on and not self._mini
        self._apply_fold()
        self.room_changed.emit()

    def _folded(self) -> bool:
        """Only the summary line shows: minimised, or the window has no room for more."""
        return self._collapsed or self._room == "line"

    def _apply_fold(self):
        folded = self._folded()
        self.panel.setVisible(not folded)
        self.scroll_area.setVisible(self.rows.count() > 1 and self._room == "open")
        self._outer.setContentsMargins(8, 6 if folded else 8, 8, 6 if folded else 8)
        self._fold_icon()
        self._sync_head()

    # How much shows is one of three states, never a squashed step between them: the
    # whole list ("open"), just the running row ("row") or just the summary line
    # ("line"). The window's fitter picks it (fit_steps): a short window folds the bar
    # before anything else gives way, and long before it turns into the mini player.

    def fit_steps(self) -> list:
        """(priority, "h", apply) steps for the window's responsive.Fitter."""
        return [(20, "h", lambda tight: self._fold_for_room("rows", tight)),
                (25, "h", lambda tight: self._fold_for_room("line", tight))]

    def _fold_for_room(self, what: str, tight: bool):
        self._room_folds = ({*self._room_folds, what} if tight
                            else self._room_folds - {what})
        room = ("line" if "line" in self._room_folds
                else "row" if "rows" in self._room_folds else "open")
        if room != self._room:
            self._room = room
            self._apply_fold()

    def _fold_icon(self):
        self.btn_min.setAccessibleName(_("Show more") if self._folded() else _("Hide"))
        icons.set_icon(self.btn_min, "fold_open" if self._folded() else "fold_up", "muted")

    def _running(self) -> bool:
        return bool(self.url) and self.stage != "done"

    def running(self) -> bool:
        """A download is under way (Bun mode builds while it is)."""
        return self._running()

    def failed_count(self) -> int:
        return len(self._failed)

    def _head_text(self) -> tuple[str, str, str]:
        """(words, icon, icon colour) for the summary line."""
        busy = (1 if self._running() else 0) + len(self._queue)
        if busy:
            if self._running() and self.kind == "play" and not self._queue:
                return _("Playing once"), "play", "live_text"
            return (ngettext("Adding {n} sound", "Adding {n} sounds", busy),
                    "download", "live_text")
        if self.stage == "done" and self.kind == "play" and self.url not in self._failed_urls():
            return _("▶ Playing"), "play", "ok_text"
        if self._added:
            n = len(self._added)
            return ngettext("Added {n} sound", "Added {n} sounds", n), "check", "ok_text"
        if self._failed:
            return _("Couldn't download"), "alert", "error_text"
        return "", "download", "live_text"

    def _failed_urls(self) -> set[str]:
        return {f["url"] for f in self._failed}

    def _sync_head(self):
        """The summary line: what the list is up to, how many failed (a red pill), the
        buttons that fit what's going on, and while one runs how far the whole list has
        got: one bar for all of it, so it doesn't start again with each pick."""
        words, name, colour = self._head_text()
        self.h_text.setText(words)
        icons.set_label_icon(self.h_icon, name, theme.T.get(colour) or theme.T["accent"],
                             size=18)
        n = len(self._failed)
        self.h_failed.setText(ngettext("{n} failed", "{n} failed", n) if n else "")
        self.h_failed.setVisible(bool(n))
        running = self._running()
        over = not running and not self._queue
        # Stop all stays up to the end of a batch (the last pick running, nothing left
        # waiting): it still stops that one, and the bar beside it doesn't jump over
        batch = bool(self._others_added() or self._others_failed())
        self.btn_stop_all.setVisible(bool(self._queue) or (running and batch))
        self.btn_close.setVisible(over)
        # folded for room, it can't open: no button that does nothing
        self.btn_min.setVisible(not over and not self._mini
                                and (self._collapsed or self._room == "open"))
        # also between two picks (the one that ended shows its tick, the next waits): the
        # bar staying up there is what makes the hand-over look like one job
        show_bar = running or bool(self._queue)
        self.s_bar.setVisible(show_bar)
        self.s_text.setVisible(show_bar)
        done = len(self._others_added()) + len(self._others_failed())
        current = (self.progress_frac if running else
                   1.0 if show_bar and self.url and self.stage == "done" else None)
        frac = jobprogress.batch(done, current, len(self._queue))
        self.s_text.setText(f"{frac * 100:.0f}%" if show_bar else "")
        # as wide as "100%" from the start: 9% -> 10% mustn't nudge the bar beside it
        self.s_text.setMinimumWidth(self.s_text.fontMetrics().horizontalAdvance("100%"))
        self.s_text.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.s_bar.set_progress(frac, busy=running and self.stage != "downloading")

    # ------------------------------------------------------------------ sizes

    def showEvent(self, ev):
        super().showEvent(ev)
        self.shown_changed.emit(True)

    def hideEvent(self, ev):
        super().hideEvent(ev)
        self.shown_changed.emit(False)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.outcome.setGeometry(self.rect())
        self._fit_tight()
        self._show_meta()

    def _fit_tight(self):
        """In a narrow window (and the mini player) the rows drop their pictures, and the
        running row its picture (or Bun) and "Adding to sounds" (the summary line says
        what the list is doing)."""
        tight = self._mini or self.width() < TIGHT_BELOW
        if tight == self._tight:
            return
        self._tight = tight
        self._apply_art()
        self._show_pill()
        self._fill_rows()

    def _show_pill(self):
        self.pill.setVisible(self._running() and not self._tight)

    def set_mini(self, mini: bool):
        """The mini player's narrow bar: no pictures, no minimise (it's short already)."""
        self._mini = mini
        self._tight = not mini   # makes _fit_tight apply it
        self._fit_tight()
        if mini:
            self.set_collapsed(False)
        self.retheme()   # also lines line 1 up again
        self._apply_art()
        self._cur_lay.setContentsMargins(*((8, 6, 6, 6) if mini else (8, 8, 6, 8)))
        self._col.setSpacing(4 if mini else LINE_GAP)
        self._cur_lay.setSpacing(8 if mini else 12)
        self._show_meta()

    def _show_meta(self):
        """The uploader and length come after the title once the banner is wide."""
        self.lbl_meta.setVisible(bool(self._meta) and not self._mini
                                 and self.width() >= WIDE_AT)

    # ------------------------------------------------------------------ the running pick

    @_after_hold
    def set_active(self, url: str, title: str, kind: str, thumb_pm: QPixmap | None = None,
                   channel: str = "", seconds: float = 0.0):
        self._show_card(url, title, kind, thumb_pm, channel, seconds)
        self.scribe.reset()
        self.btn_cancel.show()
        self.btn_retry.hide()
        self.lbl_status.setText(_("Parsing video…"))
        self.bar.set_progress(0.0, busy=True)
        self._fill_rows()
        self._sync_head()
        self.show()

    def _show_card(self, url, title, kind, thumb_pm, channel, seconds):
        self._auto_hide.stop()
        self.outcome.stop()
        self._raw = (title, seconds)
        self.url = url
        self.title = pretty_title(title) or _("Sound")
        self.kind = kind
        self.stage = "parsing"
        self._set_ended("")
        self._job.reset()
        self.progress_frac = 0.0
        self._pm = thumb_pm
        self._source = source_of(url)
        self.src_icon.setPixmap(self._icon(self._source[0]))
        self.src_icon.setToolTip(self._source[1])

        self.lbl_title.setText(self.title)
        self.lbl_title.setToolTip(self.title)
        meta = " · ".join(x for x in (channel, fmt_time(seconds) if seconds else "") if x)
        self._meta = meta
        self.lbl_meta.setText(meta)
        self._show_meta()
        self.pill.set_kind(kind)
        self._show_pill()
        self.bar.show()
        theme.set_tone(self.lbl_status, "")
        self._update_thumb()

    @_after_hold
    def set_progress(self, url: str, payload):
        if url != self.url:   # a cancelled download still finishing: not this one
            return
        if self.stage == "done":
            # it ended (✓ or ✗): a late update can't put it back to busy, or the card
            # says "Processing audio…" under the tick and never goes. Only set_active
            # starts it again.
            return
        self._auto_hide.stop()
        # every step on one bar that only goes forward (jobprogress): it used to fill
        # for the download, then again (a gliding block) while converting
        self.progress_frac = self._job.update(payload)
        self.stage = self._job.stage
        if self.stage == "parsing":
            self.scribe.set_state("parsing")
            self.lbl_status.setText(_("Parsing video…"))
        elif self.stage == "processing":
            self.scribe.set_state("processing")
            self.lbl_status.setText(_("Processing audio…"))
        else:
            self.scribe.set_progress(self.progress_frac)
            self.lbl_status.setText(f"{self.progress_frac * 100:.0f}%")   # the title says what
        self.bar.set_progress(self.progress_frac, busy=self.stage != "downloading")
        self._sync_head()
        self.show()

    @_after_hold
    def set_thumb(self, url: str, pm: QPixmap):
        if pm.isNull():
            return
        if url == self.url:
            self._pm = pm
            self._update_thumb()
        if any(q["url"] == url for q in self._queue + self._failed + self._added):
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
        self.thumb.setPixmap(self._picture(self._pm, THUMB_W, THUMB_H, 8))
        self._apply_art()

    def _apply_art(self):
        """Bun at his scroll, then the sound's picture (the placeholder if it has none):
        both always, except in a narrow banner."""
        self.thumb.setVisible(not self._tight)
        self._scribe_box.setVisible(not self._tight)

    # ------------------------------------------------------------------ the rest of the list

    @_after_hold
    def set_queue(self, queue: list[dict]):
        self._queue = list(queue)
        self._fill_rows()
        self._sync_head()

    def _others_failed(self) -> list[dict]:
        """The picks that failed, but not the one on the running row (it says so itself)."""
        return [f for f in self._failed if f["url"] != self.url]

    def _others_added(self) -> list[dict]:
        return [a for a in self._added if a["url"] != self.url]

    def _fill_rows(self):
        """The list under the running row, rebuilt: the picks waiting (a click makes one
        next up), the ones that failed (each with Retry), then the ones added already,
        newest first. A handful of rows (the queue is capped)."""
        while self.rows.count():
            item = self.rows.takeAt(0)
            w = item.widget() if item else None
            if w is not None:   # hidden now: it's only freed later, and mustn't show till then
                w.hide()
                w.deleteLater()
        failed = self._others_failed()
        added = self._others_added()[::-1]
        picks = ([(q, "wait") for q in self._queue] + [(f, "failed") for f in failed]
                 + [(a, "added") for a in added])
        rows = [self._row(q, how, first=(how == "wait" and i == 0))
                for i, (q, how) in enumerate(picks)]
        for row in rows:
            self.rows.addWidget(row)
        self.rows.addStretch(1)
        self.scroll_area.setVisible(bool(picks) and self._room == "open")
        shown = rows[:QUEUE_ROWS]
        full = (sum(r.sizeHint().height() for r in shown)
                + max(0, len(shown) - 1) * self.rows.spacing())
        # as tall as the first few rows (more scroll)
        self.scroll_area.setFixedHeight(full)
        if len(shown) != self._shown_rows:   # taller or shorter: the window fits it again
            self._shown_rows = len(shown)
            self.room_changed.emit()

    def _row(self, q: dict, how: str, first: bool) -> QFrame:
        row = _QueueRow()
        row.setObjectName("queuerow")
        row.setProperty("how", how)
        row.setAttribute(Qt.WidgetAttribute.WA_Hover)
        if how == "wait" and not first:   # the first one is next up already
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            row.setToolTip(_("Download this one next"))
            row.clicked.connect(lambda u=q["url"]: self.front_requested.emit(u))
        rl = QHBoxLayout(row)
        rl.setContentsMargins(8, 6, 6, 6)
        rl.setSpacing(12)
        if not self._tight:   # centred under the running row's picture, titles in line
            rl.addSpacing(THUMB_W)   # under Bun's column
            pic = QLabel()
            pic.setFixedSize(THUMB_W, ROW_THUMB[1])
            pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pic.setPixmap(self._picture(self.thumb_lookup(q["url"]), *ROW_THUMB, 6))
            rl.addWidget(pic, 0, Qt.AlignmentFlag.AlignVCenter)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        title = ElideLabel()
        name = pretty_title(q.get("title", "")) or _("Sound")
        title.setText(name)
        title.setToolTip(name)
        title.setObjectName("queuetitle")
        title.setProperty("waiting", how == "wait")
        col.addWidget(title)
        line = QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        why = QLabel({"wait": _("Waiting to add"), "failed": _("Couldn't download"),
                      "added": _("✓ Added to your sounds")}[how])
        why.setObjectName("downloadmeta" if how == "wait" else "downloadstatus")
        theme.set_tone(why, {"failed": "error", "added": "ok"}.get(how, ""))
        line.addWidget(why)
        secs = q.get("seconds") or 0
        if secs and how != "failed":
            length = QLabel(fmt_time(secs))
            length.setObjectName("downloadmeta")
            line.addWidget(length)
        line.addStretch(1)
        col.addLayout(line)
        rl.addLayout(col, 1)
        if how == "failed":
            again = QPushButton(_("Retry"))
            again.setObjectName("retrybutton")
            again.setCursor(Qt.CursorShape.PointingHandCursor)
            again.clicked.connect(lambda _c=False, u=q["url"]: self._retry(u))
            rl.addWidget(again, 0, Qt.AlignmentFlag.AlignVCenter)
        if how != "added":
            x = self._icon_button("close", _("Remove"), 24)
            x.clicked.connect(lambda _c=False, u=q["url"], b=(how == "failed"):
                              self._forget(u) if b
                              else (usage.used("dl-cancel"), self.cancel_requested.emit(u)))
            rl.addWidget(x, 0, Qt.AlignmentFlag.AlignVCenter)
        return row

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
        self._fill_rows()
        self._sync_head()
        if url == self.url and self.stage == "done":   # the running row's own ✕ / Retry
            self.btn_retry.hide()
            if not self._failed and not self._queue:
                self._auto_hide.start(4000)

    # ------------------------------------------------------------------ how it ends

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
        self._set_ended("ok" if ok else "failed")
        self.scribe.finish(ok)
        self.btn_cancel.hide()
        # a second of tick (or red ✗ and a red glow) over the picture so it's noticed; the
        # mini player has no picture: just the glow when it failed
        spot = QRectF()
        art = self.scribe if self.scribe.isVisibleTo(self) else None   # on Bun, not the picture
        if art is not None:
            top_left = art.mapTo(self, art.rect().topLeft())
            spot = QRectF(top_left.x(), top_left.y(), art.width(), art.height())
        if spot.isValid() or failed:
            self.outcome.play(ok, spot)
        # what comes next (the next pick, the queue moving up) waits for the flash
        self._held = []
        self._hold.start(Outcome.SHOW_MS)

        self.pill.hide()
        self.bar.hide()
        if ok:
            self.btn_retry.hide()
            self.progress_frac = self._job.finish()
            self.bar.set_progress(1.0)
            theme.set_tone(self.lbl_status, "ok")
            if kind == "play":
                self.lbl_status.setText(_("▶ Playing"))
            else:
                self.lbl_status.setText(_("✓ Added to your sounds"))
                self._added = [a for a in self._added if a["url"] != url] + [{
                    "url": url, "title": self._raw[0], "kind": kind, "seconds": self._raw[1]}]
            if not self._others_failed():   # the failed ones wait for Retry or ✕
                self._auto_hide.start(7000 if kind == "play" else 4000)
        else:
            self._failed = [f for f in self._failed if f["url"] != url] + [{
                "url": url, "title": self._raw[0], "kind": kind, "seconds": self._raw[1]}]
            self._show_failed_state()
        self._fill_rows()
        self._sync_head()

    def _show_failed_state(self):
        self.stage = "done"
        self._set_ended("failed")
        self.lbl_status.setText(_("Couldn't download"))
        theme.set_tone(self.lbl_status, "error")
        self.bar.set_progress(0.0)
        self.pill.hide()
        self.bar.hide()
        self.btn_cancel.hide()
        self.btn_retry.setProperty("main", True)   # the one thing to press now
        self.btn_retry.style().unpolish(self.btn_retry)
        self.btn_retry.style().polish(self.btn_retry)
        self.btn_retry.show()

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
            self._fill_rows()
            self._sync_head()
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
        self._set_ended("")
        self._queue = []
        self._failed = []
        self._added = []
        self._failing = ""
        self._pm = None
        self._meta = ""
        self.btn_retry.hide()
        self._fill_rows()
        self.set_collapsed(False)   # the next download opens full size again
        self.hide()
