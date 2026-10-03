"""The Sounds tab's web search: press Enter in "Search sounds" (or the Search
button next to it) and this list takes the pad grid's place. It's a plain list of
hits (thumbnail, title, channel, length) from the site searches in ytdl.SOURCES
(YouTube, YouTube Music, SoundCloud, TikTok sounds, Myinstants), with no web page
and no video. While one runs the list makes way for a loading view: Bun or Hoot
(picked at random each time) over a sliding bar and "Searching YouTube for ...".
▶ plays one once and ＋ adds it as a
pad; both hand the page to the link bar (ui/linkbar.py), which downloads just its
audio. Sites without a search (Instagram, X…) work by pasting a link into the
search box instead.
"""
from __future__ import annotations

import html
import logging
import math
import random
import threading
import time

from PySide6.QtCore import QRectF, QSize, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from soundboard import net, theme, ytdl
from soundboard.bunny import H as BUN_H
from soundboard.bunny import W as BUN_W
from soundboard.ui import busy, icons
from soundboard.ui.bunnywidget import BunnyWidget
from soundboard.ui.owl import H as OWL_H
from soundboard.ui.owl import W as OWL_W
from soundboard.ui.owl import OwlWidget
from soundboard.ui.widgets import fmt_time

log = logging.getLogger(__name__)

THUMB_W, THUMB_H = 128, 72
PASTE_HINT = ("Instagram, X, Reddit, a TikTok you already have…? Copy the video's link "
              "and paste it in the search box.")
TIPS = {"youtube": "Search YouTube",
        "ytmusic": "Search YouTube Music: songs, the official versions",
        "soundcloud": "Search SoundCloud",
        "tiktok": "Find TikTok sounds (TikTok's own search needs an account, so this "
                  "looks for them on YouTube, where they get reposted)",
        "myinstants": "Search Myinstants: short meme sound buttons"}


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


class _BusyOwl(OwlWidget):
    """Hoot on the job: bright-eyed and tufts up instead of moping, scanning left and
    right for your sound, no dozing or begging."""

    def __init__(self, height: int, parent=None):
        super().__init__(height, lines=(), joy=(), parent=parent, left=0, right=0)
        self._next_act = math.inf
        self.setToolTip("")

    def pose(self) -> dict:
        d = super().pose()
        d["sad"] = 0.0
        d["tufts"] = -8 + 3 * math.sin(self.t * 1.1)
        d["look"] = 0.8 * math.sin(self.t * 1.6)     # scanning the results
        d["look_y"] = 0.25
        return d


class SearchingView(QWidget):
    """What the results area shows while a search runs: a mascot (Bun with his
    headphones on, or Hoot keeping watch; a coin toss each time) over a loading bar
    and the "Searching ... for ..." line, all centred. Laid out by hand so it never
    asks the window for room: the mascot shrinks with the space and goes when
    there's too little, then the bar, leaving just the line."""

    MASCOTS = ("bunny", "owl")
    BIG, SMALL = 104, 44       # mascot heights, px
    GAP = 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self.kind = ""
        self.mascot: QWidget | None = None
        self._rng = random.Random()
        self.bar = LoadingBar(self)
        self.label = QLabel(self)
        self.label.setTextFormat(Qt.RichText)
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignCenter)
        self.hide()

    def sizeHint(self) -> QSize:
        return QSize(320, 220)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, self.label.sizeHint().height())

    def start(self, text: str):
        """Show `text` (rich text) under a freshly picked mascot and start the bar."""
        self.label.setText(text)
        kind = self._rng.choice(self.MASCOTS)
        if kind != self.kind or self.mascot is None:
            if self.mascot is not None:
                self.mascot.hide()
                self.mascot.deleteLater()
            self.mascot = self._make(kind)
            self.kind = kind
        self.bar.start()
        self.show()
        self._place()

    def stop(self):
        self.bar.stop()
        self.hide()            # the mascot's own timer stops with it

    def running(self) -> bool:
        return self.bar.running()

    def _make(self, kind: str) -> QWidget:
        if kind == "owl":
            m = _BusyOwl(self.BIG, parent=self)
        else:
            m = BunnyWidget("headphones", height=self.BIG, pad=22, parent=self)
        return m

    def _fit_mascot(self, h: int) -> QSize:
        """Draw the mascot `h` px tall; returns the box it then needs."""
        m = self.mascot
        if isinstance(m, OwlWidget):
            m.owl_h, m.top = h, round(h * 0.34)
            return QSize(round(h * OWL_W / OWL_H) + 8, h + m.top + 8)
        m.bun_h, m.pad = h, round(h * 0.22)
        return QSize(round(h * BUN_W / BUN_H) + 2 * m.pad + 20, h + 2 * m.pad)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._place()

    def _place(self):
        w, h, gap = self.width(), self.height(), self.GAP
        tw = max(40, min(w - 24, 460))
        th = self.label.heightForWidth(tw)
        th = th if th > 0 else self.label.sizeHint().height()
        bw = max(0, min(260, w - 48))
        show_bar = bw >= 60 and h >= th + gap + 6
        need = th + (gap + 6 if show_bar else 0)
        room = h - need - gap               # what's left above for the mascot
        box = QSize()
        if self.mascot is not None:
            # biggest that fits (its box is about 1.5x its height), or none at all
            mh = min(self.BIG, int(room / 1.5))
            if mh >= self.SMALL:
                box = self._fit_mascot(mh)
                if box.width() > w - 8 or box.height() > room:
                    box = QSize()
            self.mascot.setVisible(not box.isEmpty())
        total = need + (box.height() + gap if not box.isEmpty() else 0)
        y = max(0, (h - total) // 2)
        if not box.isEmpty():
            self.mascot.setGeometry((w - box.width()) // 2, y, box.width(), box.height())
            y += box.height() + gap
        self.bar.setVisible(show_bar)
        if show_bar:
            self.bar.setGeometry((w - bw) // 2, y, bw, 6)
            y += 6 + gap
        self.label.setGeometry((w - tw) // 2, y, tw, th)


def rounded(pm: QPixmap, w: int, h: int, r: int = 10) -> QPixmap:
    """`pm` cropped to fill w x h, with rounded corners."""
    pm = pm.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    out = QPixmap(w, h)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, w, h, r, r)
    p.setClipPath(path)
    p.drawPixmap((w - pm.width()) // 2, (h - pm.height()) // 2, pm)
    p.end()
    return out


class ResultRow(QFrame):
    play = Signal(object)
    add = Signal(object)

    def __init__(self, r: ytdl.Result):
        super().__init__()
        self.result = r
        self.setObjectName("card")
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 6, 8, 6)
        h.setSpacing(10)
        self.thumb = QLabel()
        self.thumb.setFixedSize(THUMB_W, THUMB_H)
        self.thumb.setAlignment(Qt.AlignCenter)
        icons.set_label_icon(self.thumb, "wave", "muted", 32)
        h.addWidget(self.thumb)
        text = QVBoxLayout()
        text.setSpacing(2)
        title = QLabel(f"<b>{html.escape(r.title)}</b>")
        title.setWordWrap(True)
        title.setTextFormat(Qt.RichText)
        sub = QLabel(" · ".join(x for x in (r.channel, fmt_time(r.seconds) if r.seconds
                                            else "") if x))
        sub.setTextFormat(Qt.PlainText)   # channel names come from YouTube
        sub.setObjectName("muted")
        text.addStretch(1)
        text.addWidget(title)
        text.addWidget(sub)
        text.addStretch(1)
        h.addLayout(text, 1)
        self.btn_play = QPushButton("Play")
        self.btn_play.setToolTip("Download its audio and play it once (it isn't kept)")
        icons.set_icon(self.btn_play, "play", size=14)
        self.btn_play.clicked.connect(lambda: self.play.emit(self.result))
        self.btn_add = QPushButton("Add")
        self.btn_add.setObjectName("primary")
        self.btn_add.setToolTip("Download its audio and add it to your Sounds")
        icons.set_icon(self.btn_add, "plus", "on_accent", size=14)
        self.btn_add.clicked.connect(lambda: self.add.emit(self.result))
        h.addWidget(self.btn_play)
        h.addWidget(self.btn_add)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Double-click to play")

    def mouseDoubleClickEvent(self, e):
        if not busy.is_busy(self.btn_play):
            self.play.emit(self.result)
        super().mouseDoubleClickEvent(e)

    def set_busy(self, kind: str):
        """Its audio is being fetched: that button greys out until set_done."""
        btn = self.btn_add if kind == "add" else self.btn_play
        self._release = getattr(self, "_release", {})
        if kind not in self._release and btn.isEnabled():
            self._release[kind] = busy.hold(btn, "Adding…" if kind == "add" else "Loading…")

    def set_done(self, kind: str, ok: bool):
        release = getattr(self, "_release", {}).pop(kind, None)
        if release is None:
            return
        if kind == "add" and ok:
            release()
            self.btn_add.setText("✓ Added")   # added once is enough
            busy.set_busy(self.btn_add, True)
        else:
            release(None if ok else ("Didn't add" if kind == "add" else "Didn't play"))

    def set_thumb(self, pm: QPixmap):
        self.thumb.setPixmap(rounded(pm, THUMB_W, THUMB_H, 8))


class SearchResults(QFrame):
    """`play(Result)` / `add(Result)` when a row's button is pressed; `closed()`
    when "Back to my sounds" is (the owner shows its pads again). The site
    buttons in the header pick where the search goes and re-run it there."""
    play = Signal(object)
    add = Signal(object)
    closed = Signal()
    _done = Signal(int, object, str)   # worker -> UI: (search number, results, error)

    def __init__(self):
        super().__init__()
        self.query = ""
        self.source = "youtube"
        self._gen = 0
        self._rows: list[ResultRow] = []
        self.net = QNetworkAccessManager(self)
        net.apply_qt(self.net)        # Settings > Privacy > Connection
        self._done.connect(self._on_done)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        head = QHBoxLayout()
        self.site_btns: dict[str, QPushButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for key, (name, _prefix) in ytdl.SOURCES.items():
            b = QPushButton(name)
            b.setObjectName("small")
            b.setCheckable(True)
            b.setChecked(key == self.source)
            b.setToolTip(TIPS.get(key, f"Search {name}"))
            b.clicked.connect(lambda _c=False, k=key: self.set_source(k))
            group.addButton(b)
            head.addWidget(b)
            self.site_btns[key] = b
        head.addStretch(1)
        close = QPushButton("Back to my sounds")
        close.setObjectName("small")
        close.setToolTip("Close the search results")
        close.clicked.connect(self.close_results)
        head.addWidget(close)
        v.addLayout(head)
        self.title = QLabel()
        self.title.setTextFormat(Qt.RichText)
        self.title.setWordWrap(True)
        v.addWidget(self.title)
        self.hint = QLabel(PASTE_HINT)
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        v.addWidget(self.hint)
        self.loading = SearchingView()      # takes the list's place while searching
        self.spinner = self.loading         # start / stop / running()
        v.addWidget(self.loading, 1)
        self.list = QWidget()
        self.rows = QVBoxLayout(self.list)
        self.rows.setContentsMargins(0, 0, 6, 0)
        self.rows.setSpacing(6)
        self.rows.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.list)
        scroll.setFrameShape(QFrame.NoFrame)
        v.addWidget(scroll, 1)
        self.scroll = scroll
        self.hide()

    @property
    def site(self) -> str:
        return ytdl.SOURCES[self.source][0]

    def set_source(self, key: str):
        """Search `key` (a ytdl.SOURCES key) from now on, re-running the current search."""
        if key not in ytdl.SOURCES:
            return
        self.site_btns[key].setChecked(True)
        if key != self.source:
            self.source = key
            if self.query and not self.isHidden():
                self.search(self.query)

    def search(self, query: str) -> bool:
        query = " ".join(query.split())
        if not query:
            return False
        self.query = query
        self._gen += 1
        self._clear()
        where = "TikTok sounds" if self.source == "tiktok" else self.site
        text = f"Searching {where} for <b>{html.escape(query)}</b>…"
        self.title.setText(text)
        self._loading(True, text)
        self.show()
        threading.Thread(target=self._work, args=(self._gen, query, self.source),
                         daemon=True, name="web-search").start()
        return True

    def close_results(self):
        self._gen += 1       # a search still running is ignored when it lands
        self._loading(False)
        self._clear()
        self.hide()
        self.closed.emit()

    def _loading(self, on: bool, text: str = ""):
        """The loading view in place of the title, hint and list (on), or those back."""
        for w in (self.title, self.hint, self.scroll):
            w.setVisible(not on)
        if on:
            self.loading.start(text)
        else:
            self.loading.stop()

    def mark(self, url: str, kind: str, ok: bool | None = None):
        """A row's Play / Add: busy (ok None) while its audio is fetched, then done."""
        for r in self._rows:
            if r.result.url == url:
                if ok is None:
                    r.set_busy(kind)
                else:
                    r.set_done(kind, ok)

    def _clear(self):
        for r in self._rows:
            r.deleteLater()
        self._rows = []

    def _work(self, gen: int, query: str, source: str):
        try:
            self._done.emit(gen, ytdl.search(query, source=source), "")
        except Exception as e:  # noqa: BLE001 - shown in the panel
            log.info("%s search failed for %r: %s", source, query, e)
            self._done.emit(gen, [], str(e) or "Search failed")

    def _on_done(self, gen: int, results, err: str):
        if gen != self._gen:
            return
        self._loading(False)
        q = html.escape(self.query)
        if err:
            red = theme.status("error")
            self.title.setText(f"<span style='color:{red}'>Couldn't search {self.site}: "
                               f"{html.escape(err)}</span>")
            return
        if not results:
            self.title.setText(f"No {self.site} results for <b>{q}</b>.")
            return
        self.title.setText(f"<b>{q}</b> <span style='color:{theme.T['muted']}'>· ▶ plays it "
                           "once, Add keeps it</span>")
        for r in results:
            row = ResultRow(r)
            row.play.connect(self.play)
            row.add.connect(self.add)
            self.rows.insertWidget(self.rows.count() - 1, row)
            self._rows.append(row)
            if not r.thumb:
                continue
            reply = self.net.get(QNetworkRequest(QUrl(r.thumb)))
            reply.finished.connect(lambda reply=reply, row=row, g=gen: self._on_thumb(
                reply, row, g))

    def _on_thumb(self, reply, row: ResultRow, gen: int):
        data = reply.readAll()
        reply.deleteLater()
        pm = QPixmap()
        if gen == self._gen and row in self._rows and pm.loadFromData(data):
            row.set_thumb(pm)
