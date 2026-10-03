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

from PySide6.QtCore import QPointF, QRectF, QSize, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import (QColor, QLinearGradient, QPainter, QPainterPath, QPixmap,
                           QTextLayout)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from soundboard import net, theme, ytdl
from soundboard.bunny import H as BUN_H
from soundboard.bunny import W as BUN_W
from soundboard.ui import busy, icons
from soundboard.ui.bunnywidget import BunnyWidget
from soundboard.ui.owl import H as OWL_H
from soundboard.ui.owl import W as OWL_W
from soundboard.ui.owl import OwlWidget
from soundboard.ui.panel import CardGrid
from soundboard.ui.responsive import FitWidth
from soundboard.ui.widgets import fmt_time

log = logging.getLogger(__name__)

THUMB_W, THUMB_H = 128, 72   # the pictures' shape (16:9); they fill the card's width
CARD_MIN_W = 210             # results are cards, as many across as fit at this width
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


class Thumb(QWidget):
    """A result's picture: fills the card's width at 16:9 with rounded corners, a
    wave icon until the picture arrives."""

    def __init__(self):
        super().__init__()
        self._pm: QPixmap | None = None
        self._icon = icons.icon("wave", "muted").pixmap(QSize(32, 32))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        return round(w * THUMB_H / THUMB_W)

    def sizeHint(self) -> QSize:
        return QSize(THUMB_W, THUMB_H)

    def minimumSizeHint(self) -> QSize:
        return QSize(THUMB_W, THUMB_H)

    def set_pixmap(self, pm: QPixmap):
        self._pm = pm
        self.update()

    def has_picture(self) -> bool:
        return self._pm is not None

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), 8, 8)
        p.setClipPath(path)
        if self._pm is None:
            p.fillPath(path, QColor(128, 128, 128, 40))   # reads on light and dark
            p.drawPixmap((w - self._icon.width()) // 2, (h - self._icon.height()) // 2,
                         self._icon)
        else:
            pm = self._pm.scaled(w, h, Qt.KeepAspectRatioByExpanding,
                                 Qt.SmoothTransformation)
            p.drawPixmap((w - pm.width()) // 2, (h - pm.height()) // 2, pm)
        p.end()


class ClampLabel(QLabel):
    """Text (bold by default) wrapped onto at most `lines` lines, the last ending in "…" when it
    doesn't fit (the full text in the tooltip). Always that tall, so cards in a row
    line up."""

    def __init__(self, text: str, lines: int = 2, bold: bool = True):
        super().__init__()
        self.full, self.lines = text, lines
        f = self.font()
        f.setBold(bold)
        self.setFont(f)
        self.setToolTip(text)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setFixedHeight(self.fontMetrics().lineSpacing() * lines + 2)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setPen(self.palette().color(self.foregroundRole()))
        p.setFont(self.font())
        fm = self.fontMetrics()
        layout = QTextLayout(self.full, self.font())
        layout.beginLayout()
        y, shown = 0.0, []
        while len(shown) < self.lines:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(self.width())
            shown.append((line.textStart(), line.textLength(), y))
            y += fm.lineSpacing()
        layout.endLayout()
        for i, (start, length, ly) in enumerate(shown):
            text = self.full[start:start + length].rstrip()
            if i == len(shown) - 1 and start + length < len(self.full):
                text = fm.elidedText(self.full[start:], Qt.ElideRight, self.width())
            p.drawText(QPointF(0, ly + fm.ascent()), text)
        p.end()


class ResultRow(QFrame):
    """One hit as a card: picture, title, channel and length, Play and Add."""
    play = Signal(object)
    add = Signal(object)

    def __init__(self, r: ytdl.Result):
        super().__init__()
        self.result = r
        self.setObjectName("card")
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)
        self.thumb = Thumb()
        v.addWidget(self.thumb)
        self.title = ClampLabel(r.title)
        v.addWidget(self.title)
        # channel names come from YouTube: painted as plain text
        self.sub = ClampLabel(" · ".join(x for x in (r.channel, fmt_time(r.seconds)
                                                       if r.seconds else "") if x),
                              lines=1, bold=False)
        self.sub.setObjectName("muted")
        v.addWidget(self.sub)
        v.addStretch(1)
        h = QHBoxLayout()
        h.setSpacing(6)
        self.btn_play = QPushButton("Play")
        self.btn_play.setToolTip("Download its audio and play it once (it isn't kept)")
        icons.set_icon(self.btn_play, "play", size=14)
        self.btn_play.clicked.connect(lambda: self.play.emit(self.result))
        self.btn_add = QPushButton("Add")
        self.btn_add.setObjectName("primary")
        self.btn_add.setToolTip("Download its audio and add it to your Sounds")
        icons.set_icon(self.btn_add, "plus", "on_accent", size=14)
        self.btn_add.clicked.connect(lambda: self.add.emit(self.result))
        for b in (self.btn_play, self.btn_add):
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            h.addWidget(b)
        v.addLayout(h)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Double-click to play")

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        return self.layout().heightForWidth(w)

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
        self.thumb.set_pixmap(pm)


class SearchResults(QFrame):
    """`play(Result)` / `add(Result)` when a row's button is pressed; `closed()`
    when its "My sounds" back button is (the owner shows its pads again). The site
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
        net.apply_qt(self.net, "sounds_web")   # thumbnails: Settings > Privacy
        self._done.connect(self._on_done)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        head = QHBoxLayout()
        back = self.btn_back = QPushButton("My sounds")
        back.setObjectName("small")
        back.setToolTip("Close the search results and go back to your sounds")
        icons.set_icon(back, "back", size=12)
        back.clicked.connect(self.close_results)
        head.addWidget(back)
        head.addSpacing(8)
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
        v.addLayout(head)
        self.title = QLabel()
        self.title.setTextFormat(Qt.RichText)
        self.title.setWordWrap(True)
        v.addWidget(self.title)
        # Tor mode, after the site turned Tor away even over new routes: only this click
        # runs the search without Tor (ytdl.TorBlocked)
        self.direct_btn = QPushButton("Search this without Tor")
        self.direct_btn.setToolTip("Run just this search straight from the site, not through "
                                   "Tor: the site will see your own address")
        self.direct_btn.clicked.connect(lambda: self.search(self.query, direct=True))
        self.direct_btn.hide()
        row = QHBoxLayout()
        row.addWidget(self.direct_btn)
        row.addStretch(1)
        v.addLayout(row)
        self.hint = QLabel(PASTE_HINT)
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        v.addWidget(self.hint)
        self.loading = SearchingView()      # takes the list's place while searching
        self.spinner = self.loading         # start / stop / running()
        v.addWidget(self.loading, 1)
        self.list = FitWidth()   # the cards re-flow to the width they get
        lv = QVBoxLayout(self.list)
        lv.setContentsMargins(0, 0, 6, 0)
        self.rows = CardGrid(min_w=CARD_MIN_W, gap=10)
        lv.addLayout(self.rows)
        lv.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(self.list)
        scroll.setFrameShape(QFrame.NoFrame)
        v.addWidget(scroll, 1)
        self.scroll = scroll
        self.hide()
        self.follow_switches()
        net.on_change(self.follow_switches)

    def follow_switches(self):
        """Settings > Privacy & security: a site switched off has its button greyed
        (saying why), and searching moves to one that's on. With finding sounds online
        switched off altogether, open results close."""
        for key, b in self.site_btns.items():
            ok = ytdl.site_allowed(key)
            b.setEnabled(ok)
            b.setToolTip(TIPS.get(key, f"Search {ytdl.SOURCES[key][0]}") if ok
                         else net.off_message(ytdl.site_feature(key)))
        if not ytdl.site_allowed(self.source):
            on = [k for k in self.site_btns if ytdl.site_allowed(k)]
            if on:
                self.set_source(on[0])
            elif not self.isHidden():
                self.close_results()

    @staticmethod
    def available() -> bool:
        """Can anything be searched online at all (else the bar searches only the
        board)?"""
        return any(ytdl.site_allowed(k) for k in ytdl.SOURCES)

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

    def search(self, query: str, direct: bool = False) -> bool:
        query = " ".join(query.split())
        if not query or not ytdl.site_allowed(self.source):
            return False
        self.query = query
        self._gen += 1
        self._clear()
        where = "TikTok sounds" if self.source == "tiktok" else self.site
        text = f"Searching {where} for <b>{html.escape(query)}</b>…"
        self.title.setText(text)
        self._loading(True, text)
        self.show()
        self.direct_btn.hide()
        threading.Thread(target=self._work, args=(self._gen, query, self.source, direct),
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

    def _work(self, gen: int, query: str, source: str, direct: bool = False):
        try:
            more = {"direct": True} if direct else {}   # the user's "without Tor" click
            self._done.emit(gen, ytdl.search(query, source=source, **more), "")
        except ytdl.TorBlocked as e:   # offered without Tor, never done unasked
            log.info("%s search turned away over Tor", source)
            self._done.emit(gen, "blocked", str(e))
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
            self.direct_btn.setVisible(results == "blocked")
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
            self.rows.addWidget(row)
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
