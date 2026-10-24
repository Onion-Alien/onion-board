"""The download card: floats over the bottom-right corner of the page on every tab
(and sits in the mini player as a bar), showing real-time download and preparation
progress for web links and search cards clicked by the user. Minimised, it's a pill
with the summary line; once everything is added it folds to that pill by itself, then
goes.

Shows:
- A summary line: "Adding 3 sounds", how many failed (a red pill), Stop all, minimise
- One list under it, a row per pick:
  - the one downloading now: its picture (or Bun), title, what it'll do ("Adding to
    sounds"), a smooth bar (a gliding shimmer while it's parsed or converted) and how far
  - the ones waiting ("Waiting to add"; a click makes one next up), each with its ✕
  - the ones that failed, each with Retry, and the ones added already, each with ▶
    (plays it as its pad would) and Show (the pad, on the Sounds tab)

Its parts (the bar, the labels, the end flash, the pictures, the glow): downloadparts.py.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import (QRect, QRectF, Qt, QTimer,
                            QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QCursor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
                               QSpacerItem, QVBoxLayout, QWidget)

from soundboard.core import jobprogress, usage
from soundboard.ui.kit import theme
from soundboard.i18n import _, ngettext
from soundboard.ui.kit import icons
from soundboard.ui.bun.scribebun import ScribeBunny
from soundboard.ui.kit.widgets import fmt_time
from soundboard.ui.kit.pixels import snap_to_pixels
from soundboard.ui.kit.restyled import measured, on_restyle
from soundboard.ui.window.downloadparts import (ElideLabel, KindTag, Outcome, SmoothProgressBar,
                                                _placeholder, _rounded, pretty_title, source_of)
from soundboard.ui.window.downloadbits import (  # noqa: F401
    _QueueRow,
    _Summary,
    BAR_MIN_W,
    BAR_W,
    CARD_GAP,
    CARD_MARGIN,
    CARD_TIGHT,
    CARD_W,
    GLIDE_MS,
    LINE_GAP,
    PILL_BAR_W,
    PILL_R,
    QUEUE_ROWS,
    ROW_THUMB,
    THUMB_H,
    THUMB_W,
    TIGHT_BELOW,
    WIDE_AT,
)
from soundboard.ui.window.downloadparts import SOFT, glow  # noqa: F401  (importable here, as before)
from soundboard.ui.window.downloadlook import DownloadLook
from soundboard.ui.window.downloadplace import DownloadPlace
from soundboard.ui.window.downloadrows import DownloadRows


FOLD_MS = 4000                # everything added: the card folds to its pill after this
FOLDED_MS = 6000              # and the pill goes after this (hovering waits)


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


class DownloadBar(DownloadLook, DownloadPlace, DownloadRows, QFrame):
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
    up_next_drop = Signal(str)      # ✕ on an Up next row: that Play won't play after all
    play_sound = Signal(str)        # ▶ on an added row: the pad's sound id
    show_sound = Signal(str)        # Show on an added row: the pad's sound id
    placed = Signal()               # the corner card moved or changed size (toasts go above)

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
        self._corner = False  # float_in: a card over its host's bottom-right corner
        self._host: QWidget | None = None   # float_in: its parent, and the page
        self._area: QWidget | None = None
        self._under: tuple[QWidget, ...] = ()   # what it stands on (float_in)
        self._collapsed = False
        # minimising / expanding, which view shows as the card slides (None: not sliding):
        # the open list at its full size, cut off by the card's bottom edge (True), or
        # just the summary line (False). Never the list squashed into a smaller card.
        self._tall: bool | None = None
        self._glide_from = self._glide_to = QRect()
        self._room = "open"   # place: what the page has room for
        self._shown_rows = 0   # rows under the running one the list is tall for
        self._queue: list[dict] = []
        self._failed: list[dict] = []   # picks that couldn't download, to retry
        self._added: list[dict] = []    # picks added to the sounds since the bar showed
        # Plays downloaded and waiting for the song playing (linkbar's Up next), as
        # (title, url): the running row's own says "Up next", the rest get a row each
        self._up_next: list[tuple[str, str]] = []
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
        # url -> the sound id it was added as (None: not a pad, or not any more)
        self.sound_for: Callable[[str], str | None] = lambda url: None

        self._auto_hide = QTimer(self)
        self._auto_hide.setSingleShot(True)
        self._auto_hide.timeout.connect(self._clear_and_hide)
        self._auto_fold = QTimer(self)   # the corner card: to its pill first (_wind_down)
        self._auto_fold.setSingleShot(True)
        self._auto_fold.timeout.connect(self._fold_when_done)
        self._paused_ms = 0   # the mouse came onto the card while it was winding down
        self._place_due = QTimer(self)
        self._place_due.setSingleShot(True)
        self._place_due.timeout.connect(self.place)
        # the corner card going from one size to the next (minimise, expand) in two
        # moves: down with the list showing, then sideways as just the summary line
        # (expanding: sideways first, then up)
        self._glide = QVariantAnimation(self)
        self._glide.setDuration(GLIDE_MS)
        self._glide.setStartValue(0.0)
        self._glide.setEndValue(1.0)
        self._glide.valueChanged.connect(self._glide_step)
        self._glide.finished.connect(self._glide_done)

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
        # as wide as "100%" from the start: 9% -> 10% mustn't nudge the bar beside it
        measured(self.s_text, lambda: self.s_text.setMinimumWidth(
            self.s_text.fontMetrics().horizontalAdvance("100%")))
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
        for w in (self.lbl_title, self.lbl_meta):   # (in the theme's fonts: see restyled)
            on_restyle(w, self._line_up)

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
        # mustn't hop up when one ends and down when the next starts (a strut, but one
        # that follows the pill's font: see restyled)
        strut = QSpacerItem(0, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        row2.addItem(strut)

        def pill_high():
            strut.changeSize(0, self.pill.sizeHint().height(), QSizePolicy.Policy.Fixed,
                             QSizePolicy.Policy.Fixed)
            row2.invalidate()

        measured(self.pill, pill_high)
        col.addLayout(row2)
        h.addLayout(col, 1)
        h.setAlignment(col, Qt.AlignmentFlag.AlignVCenter)

        self.btn_retry = QPushButton(_("Retry"))   # it failed: try it again
        self.btn_retry.setObjectName("retrybutton")
        self.btn_retry.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_retry.clicked.connect(lambda: self._retry(self.url))
        self.btn_retry.hide()
        h.addWidget(self.btn_retry, 0, Qt.AlignmentFlag.AlignVCenter)
        # added: play it, or go to its pad
        self.btn_play, self.btn_show = self._sound_buttons(lambda: self.url)
        h.addWidget(self.btn_play, 0, Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(self.btn_show, 0, Qt.AlignmentFlag.AlignVCenter)
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

    def _sound_buttons(self, url: Callable[[], str]) -> tuple[QPushButton, QPushButton]:
        """▶ and Show for an added pick (`url()` says which): hidden until it's a pad."""
        play = self._icon_button("play", _("Play"), 24)
        play.setToolTip(_("Play it, as its pad would"))
        play.clicked.connect(lambda: self._to_sound(url(), self.play_sound))
        show = QPushButton(_("Show"))
        show.setObjectName("retrybutton")
        show.setCursor(Qt.CursorShape.PointingHandCursor)
        show.setToolTip(_("Show its pad on the Sounds tab"))
        show.clicked.connect(lambda: self._to_sound(url(), self.show_sound))
        play.hide()
        show.hide()
        return play, show

    def _to_sound(self, url: str, signal):
        sid = self.sound_for(url)
        if sid:
            signal.emit(sid)

    def _sync_sound_buttons(self):
        """The running row's ▶ and Show: once its pick is added as a pad."""
        on = (self.stage == "done" and self.kind == "add" and not self._mini
              and any(a["url"] == self.url for a in self._added)
              and bool(self.sound_for(self.url)))
        self.btn_play.setVisible(on)
        self.btn_show.setVisible(on)

    # ------------------------------------------------------------------ looks


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
            r = PILL_R if self.property("pill") else 12
            p.drawRoundedRect(QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75), r, r)
            p.end()

    # ------------------------------------------------------------------ the summary line


    # How much shows is one of three states, never a squashed step between them: the
    # whole list ("open"), just the running row ("row") or just the summary line
    # ("line"). In the corner the card picks the most its page has height for (place).


    # ------------------------------------------------------------------ the corner


    def enterEvent(self, ev):
        """The mouse on the card holds it as it is: no folding or going while it's read."""
        super().enterEvent(ev)
        for t in (self._auto_fold, self._auto_hide):
            if t.isActive():
                self._paused_ms = max(self._paused_ms, t.remainingTime(), 2500)
                t.stop()

    def leaveEvent(self, ev):
        super().leaveEvent(ev)
        if self._paused_ms:
            ms, self._paused_ms = self._paused_ms, 0
            self._wind_down(ms)

    def _wind_down(self, ms: int):
        """Everything's over: the bar goes after `ms`; the corner card first folds to its
        pill (FOLDED_MS later it goes), so it's seen how it ended without covering the
        page."""
        if self._corner and self._mouse_on():
            self._paused_ms = ms
            return
        if self._corner and not self._collapsed:
            self._auto_fold.start(ms)
        else:
            self._auto_hide.start(FOLDED_MS if self._corner else ms)

    def _mouse_on(self) -> bool:
        """The pointer is on the card now. Not underMouse(): that flag only clears on
        the next mouse move, so after the card folded to its pill away from a still
        pointer it said "hovered" and the pill never went."""
        return self.isVisible() and self.rect().contains(self.mapFromGlobal(QCursor.pos()))

    def _stop_wind_down(self):
        self._auto_fold.stop()
        self._auto_hide.stop()
        self._paused_ms = 0

    def _fold_when_done(self):
        self.set_collapsed(True)
        self._auto_hide.start(FOLDED_MS)

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
        if self._waits():
            return _("Up next"), "list", "live_text"
        if self.stage == "done" and self.kind == "play" and self.url not in self._failed_urls():
            return _("Playing"), "play", "ok_text"
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
        # (the corner card keeps it to the end: its pill opens again to see what came)
        self.btn_min.setVisible((not over or self._corner) and not self._mini
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
        self.s_text.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.s_bar.set_progress(frac, busy=running and self.stage != "downloading")

    # ------------------------------------------------------------------ sizes

    def showEvent(self, ev):
        super().showEvent(ev)
        if self._corner:
            self.place()
        self.shown_changed.emit(True)

    def hideEvent(self, ev):
        super().hideEvent(ev)
        self._end_glide()
        self.shown_changed.emit(False)
        if self._corner:
            self.placed.emit()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.outcome.setGeometry(self.rect())
        self._fit_tight()
        self._show_meta()

    def _fit_tight(self, width: int | None = None):
        """In a narrow window (and the mini player) the rows drop their pictures, and the
        running row its picture (or Bun) and "Adding to sounds" (the summary line says
        what the list is doing). `width`: the card's, about to be (place's glide)."""
        if width is None and self._glide.state() == QVariantAnimation.State.Running:
            return   # (sliding through the narrow widths: it was set for the widest)
        width = self.width() if width is None else width
        tight = self._mini or width < (CARD_TIGHT if self._corner else TIGHT_BELOW)
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
        self._stop_wind_down()
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
        self._sync_sound_buttons()
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
        self._stop_wind_down()
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
        both always, except in a narrow banner. The corner card has room for Bun only
        (the rows' pictures line up under him)."""
        self.thumb.setVisible(not self._tight and not self._corner)
        self._scribe_box.setVisible(not self._tight)

    # ------------------------------------------------------------------ the rest of the list

    @_after_hold
    def set_queue(self, queue: list[dict]):
        self._queue = list(queue)
        self._fill_rows()
        self._sync_head()


    # ------------------------------------------------------------------ Up next


    def set_up_next(self, items: list[tuple[str, str]]):
        """Up next changed (linkbar.up_next_items): the list shows what waits, in order,
        and the bar stays up while anything does."""
        was = self._waits()
        self._up_next = list(items)
        if self.kind == "play" and self.stage == "done" and self.url not in self._failed_urls():
            self._say_play()
        if self._up_next:
            self._stop_wind_down()
        elif self.stage == "done" and not self._others_failed() and (was or self.url):
            self._wind_down(FOLD_MS)   # (its Play starting says so: set_playing)
        self._fill_rows()
        self._sync_head()


    def _forget(self, url: str):
        self._failed = [f for f in self._failed if f["url"] != url]
        self._fill_rows()
        self._sync_head()
        if url == self.url and self.stage == "done":   # the running row's own ✕ / Retry
            self.btn_retry.hide()
            if not self._failed and not self._queue:
                self._wind_down(FOLD_MS)

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
                if not self._waits() and self._alone():   # it plays, and that was all
                    self._clear_and_hide()
                    return
                self._say_play()
            else:
                self.lbl_status.setText(_("✓ Added to your sounds"))
                self._added = [a for a in self._added if a["url"] != url] + [{
                    "url": url, "title": self._raw[0], "kind": kind, "seconds": self._raw[1]}]
            if not self._others_failed() and not self._up_next:   # those stay up
                self._wind_down(7000 if kind == "play" else FOLD_MS)
        else:
            self._failed = [f for f in self._failed if f["url"] != url] + [{
                "url": url, "title": self._raw[0], "kind": kind, "seconds": self._raw[1]}]
            self._show_failed_state()
        self._sync_sound_buttons()
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
        self._stop_wind_down()
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
        self._sync_sound_buttons()
        self._fill_rows()
        self.set_collapsed(False)   # the next download opens full size again
        self.hide()
