"""The Sounds tab's YouTube search: press Enter in "Search sounds" (or the YouTube
button next to it) and this list takes the pad grid's place. It's a plain list of
hits (thumbnail, title, channel, length) from yt-dlp's ytsearch, with no web page
and no video. ▶ plays one once and ＋ adds it as a pad; both hand the video to
the link bar (ui/linkbar.py), which downloads just its audio.
"""
from __future__ import annotations

import html
import logging
import threading

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from soundboard import ytdl
from soundboard.browser import rounded
from soundboard.ui import icons
from soundboard.ui.widgets import fmt_time

log = logging.getLogger(__name__)

THUMB_W, THUMB_H = 128, 72


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


class YouTubeResults(QFrame):
    """`play(Result)` / `add(Result)` when a row's button is pressed; `closed()`
    when the × is (the owner shows its pads again)."""
    play = Signal(object)
    add = Signal(object)
    closed = Signal()
    _done = Signal(int, object, str)   # worker -> UI: (search number, results, error)

    def __init__(self):
        super().__init__()
        self.query = ""
        self._gen = 0
        self._rows: list[ResultRow] = []
        self.net = QNetworkAccessManager(self)
        self._done.connect(self._on_done)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        head = QHBoxLayout()
        self.title = QLabel()
        self.title.setTextFormat(Qt.RichText)
        head.addWidget(self.title, 1)
        close = QPushButton("Back to my sounds")
        close.setObjectName("small")
        close.setToolTip("Close the YouTube results")
        close.clicked.connect(self.close_results)
        head.addWidget(close)
        v.addLayout(head)
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

    def search(self, query: str) -> bool:
        query = " ".join(query.split())
        if not query:
            return False
        self.query = query
        self._gen += 1
        self._clear()
        self.title.setText(f"Searching YouTube for <b>{html.escape(query)}</b>…")
        self.show()
        threading.Thread(target=self._work, args=(self._gen, query), daemon=True,
                         name="yt-search").start()
        return True

    def close_results(self):
        self._gen += 1       # a search still running is ignored when it lands
        self._clear()
        self.hide()
        self.closed.emit()

    def _clear(self):
        for r in self._rows:
            r.deleteLater()
        self._rows = []

    def _work(self, gen: int, query: str):
        try:
            self._done.emit(gen, ytdl.search(query), "")
        except Exception as e:  # noqa: BLE001 - shown in the panel
            log.info("YouTube search failed for %r: %s", query, e)
            self._done.emit(gen, [], str(e) or "Search failed")

    def _on_done(self, gen: int, results, err: str):
        if gen != self._gen:
            return
        q = html.escape(self.query)
        if err:
            self.title.setText(f"<span style='color:#ff4d4f'>Couldn't search YouTube: "
                               f"{html.escape(err)}</span>")
            return
        if not results:
            self.title.setText(f"No YouTube results for <b>{q}</b>.")
            return
        self.title.setText(f"YouTube: <b>{q}</b> <span style='color:#8a8f98'>· ▶ plays it "
                           "once, Add keeps it</span>")
        for r in results:
            row = ResultRow(r)
            row.play.connect(self.play)
            row.add.connect(self.add)
            self.rows.insertWidget(self.rows.count() - 1, row)
            self._rows.append(row)
            reply = self.net.get(QNetworkRequest(QUrl(r.thumb)))
            reply.finished.connect(lambda reply=reply, row=row, g=gen: self._on_thumb(
                reply, row, g))

    def _on_thumb(self, reply, row: ResultRow, gen: int):
        data = reply.readAll()
        reply.deleteLater()
        pm = QPixmap()
        if gen == self._gen and row in self._rows and pm.loadFromData(data):
            row.set_thumb(pm)
