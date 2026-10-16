"""The Chat tab: one anonymous, text-only room for everyone using the app (soundboard.chat).

It starts switched off (Settings > Tabs, or + More tabs). The first time it is opened it
shows the rules, and nothing goes online until they're accepted. Then a worker thread asks
the server for new messages (a long poll: the server answers when someone speaks) while the
tab is on screen, and stops when it isn't. Everything the server sends is shown as plain
text, never as HTML. Every call comes back through busy.emit, so a closed tab or window
never gets a late answer."""
from __future__ import annotations

import colorsys
import html
import logging
import threading
import time
import zlib
from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
                               QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from soundboard import chat, errors, net
from soundboard.i18n import _
from soundboard.ui import busy, icons
from soundboard.ui.panel import card, hint_label, icon_button, info_button, section_label

log = logging.getLogger(__name__)

COLUMN_W = 760          # the room stays a readable column on a wide window
RETRY_S = (3, 6, 12, 30)   # waits after a failed poll, then 30 s
MAX_SEEN = 400          # message numbers kept to ignore a repeat


def name_color(user: str, light_theme: bool = False) -> str:
    """A steady colour for a person's name today (from their tag), readable on the
    theme's background: darker on a light one, lighter on a dark one."""
    h = (zlib.crc32(user.encode()) % 360) / 360
    r, g, b = colorsys.hls_to_rgb(h, 0.36 if light_theme else 0.64, 0.6)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


class MessageRow(QFrame):
    """One message: who said it (a name that changes daily), what, and Mute / Report."""

    def __init__(self, m: chat.Message, mine: bool, tab: ChatTab):
        super().__init__()
        self.message = m
        self.setObjectName("card")
        self.setMaximumWidth(COLUMN_W)
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 6, 8, 6)
        h.setSpacing(8)
        words = QVBoxLayout()
        words.setSpacing(0)
        who = _("You") if mine else m.name
        light = tab.palette().window().color().lightness() > 128
        self.who = QLabel(f'<b style="color:{name_color(m.user, light)}">{html.escape(who)}</b>')
        self.who.setTextFormat(Qt.TextFormat.RichText)
        self.who.setAccessibleName(who)
        self.text = QLabel(m.text)
        self.text.setTextFormat(Qt.TextFormat.PlainText)   # never HTML, whatever it says
        self.text.setWordWrap(True)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.text.setMinimumWidth(40)
        words.addWidget(self.who)
        words.addWidget(self.text)
        h.addLayout(words, 1)
        if not mine:
            self.btn_mute = QPushButton(_("Mute"))
            self.btn_mute.setProperty("quiet", True)
            self.btn_mute.setToolTip(_("Hide everything this name says today"))
            self.btn_mute.clicked.connect(lambda: tab.mute(m))
            h.addWidget(self.btn_mute, 0, Qt.AlignmentFlag.AlignTop)
            self.btn_report = icon_button("flag", _("Report this message"))
            self.btn_report.clicked.connect(lambda: tab.report(self))
            h.addWidget(self.btn_report, 0, Qt.AlignmentFlag.AlignTop)


class ChatTab(QWidget):
    """The Chat tab. `open_privacy()` opens Settings > Privacy & security; `save()` saves
    the settings; `count(step)` records a first-time step in the usage count."""
    clip_ready = Signal(object, str)   # (the window wires every tab's; never sent here)
    active_changed = Signal(bool)
    _polled = Signal(int, object, int, bool, str)   # (generation, messages, last, off, error)
    _sent = Signal(object, str)                     # (the message as the room has it, error)
    _reported = Signal(object, str)                 # (row, error)

    def __init__(self, cfg, open_privacy: Callable[[], object],
                 save: Callable[[], None] = lambda: None,
                 count: Callable[[str], object] = lambda step: None):
        super().__init__()
        self.cfg = cfg
        self._open_privacy = open_privacy
        self._save = save
        self._count = count
        self._closed = False
        self._gen = 0             # the polling loop wanted now (older ones stop themselves)
        self._after = 0           # the newest message number seen
        self._mine = ""           # today's tag for this install, learned from its first message
        self._muted: set[str] = set()
        self._rows: list[MessageRow] = []
        self._seen: list[int] = []
        self._polling = False     # a loop is running for the current generation
        self._polled.connect(self._on_polled)
        self._sent.connect(self._on_sent)
        self._reported.connect(self._on_reported)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)
        info = info_button(_("One room for everyone using Onion Board. Text only: no links or "
                             "pictures. Your name is made up and changes every day, and only "
                             "the last few messages are kept, in memory."))
        head, hv = card(_("Chat"), icon="chat", beside=info)
        head.setMaximumWidth(COLUMN_W)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.entry = QLineEdit()
        self.entry.setMaxLength(chat.MAX_LEN)
        self.entry.setPlaceholderText(_("Say something"))
        self.entry.setAccessibleName(_("Message"))
        self.entry.returnPressed.connect(self.send)
        row.addWidget(self.entry, 1)
        self.btn_send = QPushButton(_("Send"))
        self.btn_send.setObjectName("primary")
        self.btn_send.clicked.connect(self.send)
        row.addWidget(self.btn_send)
        hv.addLayout(row)
        outer.addWidget(head)

        self.stack = QStackedWidget()
        scroll = self.list_area = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        self._list = QVBoxLayout(body)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(6)
        self._list.addStretch(1)
        scroll.setWidget(body)
        self.stack.addWidget(scroll)
        self.message = QWidget()
        mv = QVBoxLayout(self.message)
        mv.setContentsMargins(12, 8, 12, 8)
        mv.setSpacing(6)
        mv.addStretch(1)
        self.msg_icon = QLabel()
        self.msg_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mv.addWidget(self.msg_icon)
        self.msg_title = section_label("")
        self.msg_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mv.addWidget(self.msg_title)
        self.msg_text = hint_label("")
        self.msg_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mv.addWidget(self.msg_text)
        br = QHBoxLayout()
        br.addStretch(1)
        self.msg_btn = QPushButton()
        self.msg_btn.clicked.connect(self._message_action)
        br.addWidget(self.msg_btn)
        br.addStretch(1)
        mv.addLayout(br)
        mv.addStretch(2)
        self._msg_do: Callable[[], object] | None = None
        # in a scroll area, so the long rules never raise the window's smallest size
        self.message_area = QScrollArea()
        self.message_area.setWidgetResizable(True)
        self.message_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self.message_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.message_area.setWidget(self.message)
        self.stack.addWidget(self.message_area)
        self.stack.setMaximumWidth(COLUMN_W)
        outer.addWidget(self.stack, 1)
        self.note = QLabel()   # the last action's result, for screen readers and tests
        self.note.hide()
        self._sync()

    # ------------------------------------------------------------------ the main window
    def start(self):
        pass

    def stop(self):
        pass

    def stop_all(self):
        pass

    def is_active(self) -> bool:
        return False

    def retheme(self):
        pass

    def shutdown(self):
        self._closed = True
        self._gen += 1

    def showEvent(self, e):
        super().showEvent(e)
        self._sync()

    def hideEvent(self, e):
        self._gen += 1   # the loop stops after its current call: nobody is looking
        self._polling = False
        super().hideEvent(e)

    # ------------------------------------------------------------------ what's shown
    def accepted(self) -> bool:
        return self.cfg.chat_rules >= chat.RULES_VERSION

    def _say(self, icon: str, title: str, text: str, button: str = "",
             do: Callable[[], object] | None = None):
        self.msg_icon.setPixmap(icons.pixmap(icon, 32, icons.resolve("muted")))
        self.msg_title.setText(title)
        self.msg_text.setText(text)
        self.msg_text.setVisible(bool(text))
        self.msg_btn.setText(button)
        self.msg_btn.setVisible(bool(button))
        self._msg_do = do
        self.stack.setCurrentWidget(self.message_area)

    def _message_action(self):
        if self._msg_do is not None:
            self._msg_do()

    def _sync(self):
        """Show the right page for now: the rules, "off", or the room (and ask for it)."""
        typing = self.accepted() and net.allowed(chat.FEATURE)
        self.entry.setEnabled(typing)
        self.btn_send.setEnabled(typing)
        self.entry.setVisible(typing)   # nothing to type into until the rules are accepted
        self.btn_send.setVisible(typing)
        if not self.accepted():
            self._say("chat", _("Before you join"),
                      _("Chat is one room for everyone using Onion Board. It's anonymous: you "
                        "get a made-up name that changes every day. Be decent: no hate, no "
                        "threats, nothing about kids, no spam. Text only; links are blocked. "
                        "Anyone can mute or report a message, and enough reports mute a "
                        "person for an hour."),
                      _("I agree, join the chat"), self.accept)
            return
        if not net.allowed(chat.FEATURE):
            self._say("offline", _("Chat is off"),
                      net.off_message(chat.FEATURE),
                      _("Open Settings"), self._open_privacy)
            return
        if self.isVisible() and not self._closed:
            self._ensure_polling()
        if self._rows:
            self.stack.setCurrentWidget(self.list_area)
        else:
            self._say("chat", _("Nobody has said anything yet"), _("Say hi."))

    def accept(self):
        self.cfg.chat_rules = chat.RULES_VERSION
        self._save()
        self._count("chat-joined")
        self._sync()
        self.entry.setFocus()

    # ------------------------------------------------------------------ the room
    def install(self) -> str:
        new = not getattr(self.cfg, "store_id", "")
        sid = chat.install_id(self.cfg)
        if new:
            self._save()
        return sid

    def _ensure_polling(self):
        if self._polling:
            return
        self._polling = True
        gen, install = self._gen, self.install()

        def run():
            after, fails = self._after, 0
            while not self._closed and gen == self._gen:
                try:
                    got, last, off = chat.poll(install, after, wait=after != 0)
                    fails = 0
                    after = last if last < after else max([after, *(m.id for m in got)])
                    busy.emit(self._polled, gen, got, last, off, "")
                except Exception as e:  # noqa: BLE001 - offline, switched off, the server…
                    log.info("couldn't read the chat: %s", e)
                    busy.emit(self._polled, gen, [], after, False,
                              str(e) if isinstance(e, chat.ChatError) else errors.plain(e))
                    wait = RETRY_S[min(fails, len(RETRY_S) - 1)]
                    fails += 1
                    end = time.monotonic() + wait
                    while time.monotonic() < end and not self._closed and gen == self._gen:
                        time.sleep(0.25)
        threading.Thread(target=run, daemon=True, name="chat-poll").start()

    def _on_polled(self, gen: int, got, last: int, off: bool, err: str):
        if self._closed or gen != self._gen:
            return
        if off:
            self._clear()
            self._say("offline", _("Chat is switched off for now"), _("Try again later."))
            return
        if err:
            if not self._rows:
                self._say("warn", _("Couldn't open the chat"), err, _("Try again"), self._retry)
            return
        if last < self._after:   # the room started over
            self._clear()
        self._after = last
        bar = self.list_area.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 4
        for m in got:
            if m.id in self._seen:
                continue
            self._seen.append(m.id)
            self._add(m)
        del self._seen[:-MAX_SEEN]
        if self._rows:
            self.stack.setCurrentWidget(self.list_area)
            if at_end:
                QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))
        else:
            self._say("chat", _("Nobody has said anything yet"), _("Say hi."))

    def _retry(self):
        self._gen += 1   # the old loop is waiting out its back-off: let it end
        self._polling = False
        self._sync()

    def _add(self, m: chat.Message):
        if m.user in self._muted:
            return
        r = MessageRow(m, bool(self._mine) and m.user == self._mine, self)
        self._list.insertWidget(self._list.count() - 1, r)
        self._rows.append(r)
        while len(self._rows) > chat.KEEP:
            old = self._rows.pop(0)
            self._list.removeWidget(old)
            old.deleteLater()

    def _clear(self):
        for r in self._rows:
            self._list.removeWidget(r)
            r.deleteLater()
        self._rows.clear()
        self._seen.clear()
        self._after = 0

    # ------------------------------------------------------------------ saying, muting, reporting
    def send(self):
        text = " ".join(self.entry.text().split())
        if not text or not self.accepted() or not self.btn_send.isEnabled():
            return
        install = self.install()
        busy.set_busy(self.btn_send, True)

        def run():
            try:
                busy.emit(self._sent, chat.say(install, text), "")
            except Exception as e:  # noqa: BLE001
                busy.emit(self._sent, None,
                          str(e) if isinstance(e, chat.ChatError) else errors.plain(e))
        threading.Thread(target=run, daemon=True, name="chat-say").start()

    def _on_sent(self, m, err: str):
        if self._closed:
            return
        busy.set_busy(self.btn_send, False)
        if m is None:
            busy.toast(self.window(), html.escape(err), "error")
            self.note.setText(err)
            return
        self.entry.clear()
        self._mine = m.user
        self.note.setText(_("Sent"))
        if m.id not in self._seen:
            self._seen.append(m.id)
            self._add(m)
            self._after = max(self._after, m.id)
        if self._rows:
            self.stack.setCurrentWidget(self.list_area)
            bar = self.list_area.verticalScrollBar()
            QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))
        self._count("chat-said")

    def mute(self, m: chat.Message):
        """Hide everything this name says today (the tag changes with the day)."""
        self._muted.add(m.user)
        for r in [r for r in self._rows if r.message.user == m.user]:
            self._rows.remove(r)
            self._list.removeWidget(r)
            r.deleteLater()
        self.note.setText(_("Muted {name}", name=m.name))
        busy.toast(self.window(), html.escape(_("Muted {name}", name=m.name)), "")
        if not self._rows:
            self._say("chat", _("Nobody has said anything yet"), _("Say hi."))

    def report(self, row: MessageRow):
        row.btn_report.setEnabled(False)
        install, mid = self.install(), row.message.id

        def run():
            try:
                chat.report(install, mid)
                busy.emit(self._reported, row, "")
            except Exception as e:  # noqa: BLE001
                busy.emit(self._reported, row,
                          str(e) if isinstance(e, chat.ChatError) else errors.plain(e))
        threading.Thread(target=run, daemon=True, name="chat-report").start()

    def _on_reported(self, row: MessageRow, err: str):
        if self._closed:
            return
        try:
            row.btn_report.setEnabled(bool(err))
        except RuntimeError:   # the row went away meanwhile
            return
        text = err or _("Reported. Enough reports mute that person for a while.")
        self.note.setText(text)
        busy.toast(self.window(), html.escape(text), "error" if err else "")
