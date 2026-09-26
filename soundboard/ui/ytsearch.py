"""The Sounds tab's web search: press Enter in "Search sounds" (or the Search
button next to it) and this list takes the pad grid's place. It's a plain list of
hits (thumbnail, title, channel, length) from the site searches in ytdl.SOURCES
(YouTube, YouTube Music, SoundCloud, TikTok sounds, Myinstants), with no web page
and no video; a spinner turns while one runs. ▶ plays one once and ＋ adds it as a
pad; both hand the page to the link bar (ui/linkbar.py), which downloads just its
audio. Sites without a search (Instagram, X…) work by pasting a link into the
search box instead.
"""
from __future__ import annotations

import html
import logging
import threading

from PySide6.QtCore import QRectF, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from soundboard import theme, ytdl
from soundboard.ui import icons
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


class Spinner(QWidget):
    """A small turning arc in the accent colour, shown while something loads."""

    def __init__(self, size: int = 16):
        super().__init__()
        self.setFixedSize(size, size)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def start(self):
        self.show()
        self._timer.start()

    def stop(self):
        self._timer.stop()
        self.hide()

    def running(self) -> bool:
        return self._timer.isActive()

    def _tick(self):
        self._angle = (self._angle + 30) % 360
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(theme.T.get("accent", "#7c5cff")), 2.2)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        p.drawArc(r, -self._angle * 16, 270 * 16)
        p.end()


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
        self.thumb.setPixmap(icons.icon("wave", "muted").pixmap(32, 32))
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
        self.play.emit(self.result)
        super().mouseDoubleClickEvent(e)

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
        status = QHBoxLayout()
        status.setSpacing(8)
        self.spinner = Spinner()
        status.addWidget(self.spinner)
        self.title = QLabel()
        self.title.setTextFormat(Qt.RichText)
        self.title.setWordWrap(True)
        status.addWidget(self.title, 1)
        v.addLayout(status)
        hint = QLabel(PASTE_HINT)
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        v.addWidget(hint)
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
        self.title.setText(f"Searching {where} for <b>{html.escape(query)}</b>…")
        self.spinner.start()
        self.show()
        threading.Thread(target=self._work, args=(self._gen, query, self.source),
                         daemon=True, name="web-search").start()
        return True

    def close_results(self):
        self._gen += 1       # a search still running is ignored when it lands
        self.spinner.stop()
        self._clear()
        self.hide()
        self.closed.emit()

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
        self.spinner.stop()
        q = html.escape(self.query)
        if err:
            self.title.setText(f"<span style='color:#ff4d4f'>Couldn't search {self.site}: "
                               f"{html.escape(err)}</span>")
            return
        if not results:
            self.title.setText(f"No {self.site} results for <b>{q}</b>.")
            return
        self.title.setText(f"<b>{q}</b> <span style='color:#8a8f98'>· ▶ plays it "
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
