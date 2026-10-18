"""*Enjoying Onion Board?*: a slim bar over the tabs (never a window, so it's safe while a
game is up) with Bun holding up a survey clipboard and a thumb up and down, shown once
ever (enjoy.asked), after a few days of heavy use (soundboard.core.enjoy says when). A thumb
is sent at once (usage.survey); the bar then asks "What do you like most?" or "What
should we fix?" over a box that wraps and grows, and Send. The ✕ just closes it.

It waits for a calm moment like the tips do: the window shown and not minimised, no
game in front, no tutorial, no other bar. MainWindow makes one ``EnjoyControl``
(``MainWindow.enjoyctl``); everything here runs on the UI thread."""
from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                               QVBoxLayout, QWidget)

from soundboard.core import enjoy, tips, usage
from soundboard.i18n import _
from soundboard.ui.kit import busy, icons
from soundboard.ui.bun.bunnywidget import BunnyWidget
from soundboard.ui.controller import Controller

if TYPE_CHECKING:
    from soundboard.ui.mainwindow import MainWindow

START_DELAY_MS = 30_000   # never in the first moments after a start
RETRY_MS = 60_000         # ...then looked at this often until it's been shown this start
BUN_H = 70                # Bun's height in the bar
SAID_MAX = 100            # characters of what they type (usage.other_tag keeps as much)
SAID_LINES = 6            # the box grows to this many lines: SAID_MAX always fits
SAID_W = 420              # ...at most this wide
WORDS_W = 200             # the question wraps only past this width (a narrow window)


class EnjoyControl(Controller):
    """The *Enjoying Onion Board?* bar of one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self.sid = ""          # the random session this showing's answers go with
        self.thumb = ""        # "positive" / "negative" once one was clicked
        self.shown = False     # shown this start: not again until the next
        self._timer = QTimer(mw, interval=RETRY_MS)
        self._timer.timeout.connect(self.maybe_show)

    def build_bar(self) -> QFrame:
        """[Bun] the question and its thumbs, or (after a thumb) the next question with a
        box under it that wraps and grows with the text, so every word typed stays
        in view (SAID_MAX characters fit even in the narrowest window), and Send. ✕ on the right."""
        self.bar = QFrame()
        self.bar.setObjectName("tipbar")
        h = QHBoxLayout(self.bar)
        h.setContentsMargins(4, 4, 6, 4)
        h.setSpacing(8)
        self.bun = BunnyWidget("survey", height=BUN_H, pad=2)
        h.addWidget(self.bun, 0, Qt.AlignmentFlag.AlignVCenter)
        col = QVBoxLayout()
        col.setSpacing(6)
        col.addStretch(1)
        top = self._top = QHBoxLayout()
        top.setSpacing(8)
        words = QVBoxLayout()
        words.setSpacing(2)
        self.lbl = QLabel()
        self.lbl.setObjectName("enjoytitle")
        self.lbl.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl.setWordWrap(True)   # (only in a narrow window: it gets its width first)
        f = self.lbl.font()
        f.setBold(True)
        self.lbl.setFont(f)
        words.addWidget(self.lbl)
        self.sub = QLabel()
        self.sub.setObjectName("hint")
        self.sub.setTextFormat(Qt.TextFormat.PlainText)
        self.sub.setWordWrap(True)
        words.addWidget(self.sub)
        top.addLayout(words)
        self.up = self._thumb_button("like", _("Yes, I like it"))
        self.up.clicked.connect(lambda: self.vote("positive"))
        top.addWidget(self.up, 0, Qt.AlignmentFlag.AlignVCenter)
        self.down = self._thumb_button("dislike", _("Not really"))
        self.down.clicked.connect(lambda: self.vote("negative"))
        top.addWidget(self.down, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addStretch(1)
        col.addLayout(top)
        self.answer = QWidget()
        row = QHBoxLayout(self.answer)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.said = QPlainTextEdit()
        self.said.setObjectName("enjoysaid")
        self.said.setTabChangesFocus(True)
        self.said.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.said.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.said.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.said.setMinimumWidth(160)
        self.said.setMaximumWidth(SAID_W)
        self.said.textChanged.connect(self._said_changed)
        self.said.installEventFilter(self)   # its lines change with its width too
        row.addWidget(self.said, 1)   # (the stretch below only gets what's left)
        self.send_btn = QPushButton(_("Send"))
        self.send_btn.setObjectName("primary")
        self.send_btn.setProperty("roomy", True)
        self.send_btn.clicked.connect(self.send_said)
        row.addWidget(self.send_btn, 0, Qt.AlignmentFlag.AlignTop)
        row.addStretch(0)
        col.addWidget(self.answer)
        col.addStretch(1)
        h.addLayout(col, 1)
        self.x = QPushButton()
        self.x.setObjectName("urgenthide")
        self.x.setAccessibleName(_("Close"))
        self.x.setToolTip(_("Close"))
        icons.close_button(self.x, 28)
        self.x.clicked.connect(self.close)
        h.addWidget(self.x, 0, Qt.AlignmentFlag.AlignTop)
        self._said_changed()
        self.bar.hide()
        return self.bar

    def _said_changed(self):
        """Keep it to SAID_MAX characters on one paragraph (Enter sends), and as tall as
        its lines."""
        text = self.said.toPlainText()
        enter = "\n" in text
        clean = text.replace("\n", " ")[:SAID_MAX]
        if clean != text:
            self.said.blockSignals(True)
            self.said.setPlainText(clean)
            self.said.moveCursor(QTextCursor.MoveOperation.End)
            self.said.blockSignals(False)
        self._fit_said()
        if enter:
            self.send_said()

    def eventFilter(self, obj, ev):   # noqa: N802 - Qt
        """The box got wider or narrower: fit its height once it has re-wrapped."""
        if obj is self.said and ev.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self, self._fit_said)
        return False

    def _set_words(self, title: str, sub: str):
        """The question and the line under it. Each keeps its own width up to WORDS_W
        before it wraps: a wrapped label is otherwise squeezed to a narrow block."""
        for label, text in ((self.lbl, title), (self.sub, sub)):
            label.setText(text)
            label.setMinimumWidth(min(WORDS_W, label.fontMetrics().horizontalAdvance(text) + 2))

    def _fit_said(self):
        """As tall as its lines, up to SAID_LINES."""
        lines = max(1, min(SAID_LINES, round(self.said.document().size().height())))
        # around the text: the document's margin, and the border and padding (the box's
        # height less its viewport's), so the words sit in the middle
        frame = self.said.height() - self.said.viewport().height()
        pad = round(self.said.document().documentMargin() * 2) + frame
        line = self.said.fontMetrics().lineSpacing()
        self.said.setFixedHeight(lines * line + pad)
        self.send_btn.setFixedHeight(line + pad)   # level with the box's first line

    @staticmethod
    def _thumb_button(icon: str, tip: str) -> QPushButton:
        b = QPushButton()
        icons.set_icon(b, icon, "muted", size=20, gap=False)
        b.setFixedSize(44, 34)
        b.setToolTip(tip)
        b.setAccessibleName(tip)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        return b

    def start(self):
        """At start: looked at after START_DELAY_MS, then every RETRY_MS."""
        QTimer.singleShot(START_DELAY_MS, self, self._start)

    def _start(self):
        if not self.maybe_show():
            self._timer.start()

    def _calm(self) -> bool:
        """Nothing else going on: the window up, no game, no tutorial, no other bar."""
        mw = self.mw
        if not mw.isVisible() or mw.isMinimized():
            return False
        if mw.overlay.is_open or tips.fullscreen_in_front():
            return False
        from soundboard.ui.setup import firsttour, tabtours
        if firsttour._current is not None or tabtours._current is not None:
            return False
        return not any(getattr(mw, n) is not self.bar and not getattr(mw, n).isHidden()
                       for n in mw.TOP_BARS)

    def maybe_show(self) -> bool:
        """Show the bar if it's due and it's a calm moment. True when there's nothing
        more to try (shown already: it never shows again)."""
        if self.shown or self.mw.cfg.enjoy_state == "done":
            self._timer.stop()
            return True
        if not enjoy.due(self.mw.cfg) or not usage.enabled() or not self._calm():
            return False
        self.show()
        self._timer.stop()
        return True

    def show(self):
        """The question: thumbs up or down."""
        self.shown, self.thumb = True, ""
        self.sid = uuid.uuid4().hex   # never this PC's stats_id
        self._set_words(_("Enjoying Onion Board?"), _("One click. It's anonymous."))
        self.bun.sad, self.bun._joy_at = 0.0, -1.0
        self.up.show()
        self.down.show()
        self.answer.hide()
        self._top.setStretch(0, 0)   # the thumbs right after the words
        self._top.setStretch(3, 1)
        self.bar.show()
        enjoy.asked(self.mw.cfg)   # once, ever: even if they ignore it or quit
        self.mw._save_later()
        usage.survey(self.sid, "shown")

    def vote(self, thumb: str):
        """A thumb: sent now, then what they'd say about it."""
        self.thumb = thumb
        usage.survey(self.sid, thumb)
        if thumb == "positive":   # a happy hop and some notes
            self.bun._joy_at = time.monotonic()
            self.bun.burst(6)
        else:
            self.bun.sad = 0.6
        self._set_words(_("Nice! What do you like most?") if thumb == "positive"
                        else _("Sorry about that. What should we fix?"),
                        _("Optional. Never linked to you."))
        self.said.clear()
        self.said.setPlaceholderText(_("Type here"))
        self.up.hide()
        self.down.hide()
        self.answer.show()
        self._top.setStretch(0, 1)   # no thumbs: the words take the room
        self._top.setStretch(3, 0)
        self.said.setFocus()

    def send_said(self):
        text = self.said.toPlainText().strip()
        if not self.thumb:
            return
        if text:
            usage.survey(self.sid, self.thumb, text)
        self.bar.hide()
        busy.toast(self.mw, _("Thanks for telling us!"), "ok")

    def close(self):
        """The ✕: closed for good (counted as dismissed when no thumb was clicked)."""
        self.bar.hide()
        if not self.thumb:
            usage.survey(self.sid, "dismissed")
