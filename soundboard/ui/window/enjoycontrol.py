"""*Enjoying Onion Board?*: a small card in the middle of the window, over a dimmed app,
with Bun holding a survey and a thumb up and down. Asked once ever, at a start, of people
who really used the app on a few days before (soundboard.core.enjoy says when). A thumb
is sent at once (usage.survey); the card then asks "What do you like most?" or "What
should we fix?" over a one-line box, with Skip and Send; after a thumb down, one-tap
reasons above the box too (REASONS: sent as a fixed tag, the same in every language). After a thumb down, Skip or Send
then shows one more card: the button that uninstalls Onion Board (its own uninstaller, the
one Installed apps runs), or Keep it; the answer is sent too. The ✕, Esc or a click on the
dimmed app just closes it.

It's part of the window (child widgets, never a window of its own), so it never takes the
focus from a game, and it waits for a calm moment: the window up and in front, no game
in front, no dialog open. If none comes soon after the start, it waits for the next start.
MainWindow makes one ``EnjoyControl`` (``MainWindow.enjoyctl``); everything here runs on
the UI thread."""
from __future__ import annotations

import logging
import subprocess
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton, QWidget

from soundboard.core import enjoy, tips, usage
from soundboard.i18n import _
from soundboard.ui.kit import busy, icons
from soundboard.ui.kit.modalframe import ModalFrame
from soundboard.ui.window.controller import Controller

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

log = logging.getLogger(__name__)

START_DELAY_MS = 4_000   # once the window has settled after a start
RETRY_MS = 20_000        # not calm yet: looked at again this often...
TRIES = 15               # ...this many times (5 minutes), then it waits for the next start
SAID_MAX = 100           # characters of what they type (usage.other_tag keeps as much)
WIDTH = 500             # the card's width, less in a narrow window
EDGE = 16                # the least room around it
BUN = 64                 # Bun's height in the card
QUIT_AFTER_MS = 1_500    # Uninstall: the answer's send gets this long before the app quits
INSTALLED_APPS = "ms-settings:appsfeatures"   # no uninstaller here (a source run): Windows' list
# a thumb down's one-tap reasons: (the tag sent as `said`, its words)
REASONS = (("reason-setup", lambda: _("Too hard to set up")),
           ("reason-mic", lambda: _("Sounds don't reach my mic")),
           ("reason-feature", lambda: _("Missing a feature")),
           ("reason-slow", lambda: _("Too slow or buggy")))


def uninstaller() -> Path | None:
    """The installed app's uninstaller (Inno Setup's, next to the exe), or None."""
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable).resolve().parent / "unins000.exe"
    return exe if exe.is_file() else None


class _Scrim(QWidget):
    """The app dimmed behind the card. A click on it closes the card."""

    def __init__(self, ctl: EnjoyControl):
        super().__init__(ctl.mw)
        self.ctl = ctl
        self.setObjectName("enjoyscrim")

    def paintEvent(self, ev):   # noqa: N802 - Qt API
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 120))   # the same in every theme, like a shadow

    def mousePressEvent(self, ev):   # noqa: N802 - Qt API
        ev.accept()
        self.ctl.close()


class EnjoyControl(Controller):
    """The *Enjoying Onion Board?* card of one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self.sid = ""          # the random ID this showing's answers go with
        self.thumb = ""        # "positive" / "negative" once one was clicked
        self.due = False       # due at this start (worked out once, at the start)
        self.tries = 0
        self.scrim: _Scrim | None = None
        self.frame: ModalFrame | None = None
        self.said: QLineEdit | None = None
        self.asked_uninstall = False   # the uninstall card is the one showing
        self._timer = QTimer(self, interval=RETRY_MS)
        self._timer.timeout.connect(self.maybe_show)

    @property
    def is_open(self) -> bool:
        return self.frame is not None

    def start(self):
        """At start: due? Then looked at after START_DELAY_MS, then every RETRY_MS."""
        self.due = enjoy.due(self.mw.cfg)
        if self.due:
            QTimer.singleShot(START_DELAY_MS, self, self._start)

    def _start(self):
        if not self.maybe_show():
            self._timer.start()

    def _calm(self) -> bool:
        """Nothing else going on: the window up and in front, no game, no dialog."""
        mw = self.mw
        if not mw.isVisible() or mw.isMinimized() or not mw.isActiveWindow():
            return False
        if mw.overlay.is_open or tips.fullscreen_in_front():
            return False
        return QApplication.activeModalWidget() is None and QApplication.activePopupWidget() is None

    def maybe_show(self) -> bool:
        """Show the card if it's due and calm. True when there's nothing more to try."""
        if self.is_open or not self.due or self.mw.cfg.enjoy_state == "done" or not usage.enabled():
            self._timer.stop()
            return True
        if not self._calm():
            self.tries += 1
            if self.tries >= TRIES:
                self._timer.stop()
                return True
            return False
        self._timer.stop()
        self.show()
        return True

    def show(self):
        """The question: thumbs up or down."""
        self.thumb = ""
        self.asked_uninstall = False
        self.sid = uuid.uuid4().hex   # never this PC's stats_id
        self.scrim = _Scrim(self)
        f = self._frame(_("Enjoying Onion Board?"), _("One click. It's anonymous."))
        self.down = f.add_button(_("Not really"))
        icons.set_icon(self.down, "dislike", "text", size=18)
        self.down.clicked.connect(lambda: self.vote("negative"))
        self.up = f.add_button(_("Yes, I like it"), primary=True)
        icons.set_icon(self.up, "like", "on_accent", size=18)
        self.up.clicked.connect(lambda: self.vote("positive"))
        self.mw.installEventFilter(self)
        self._place()
        self.scrim.show()
        f.show()
        f.raise_()
        self.up.setFocus()
        enjoy.asked(self.mw.cfg)   # once, ever: even if they ignore it or quit
        self.mw._save_later()
        usage.survey(self.sid, "shown")

    def _frame(self, title: str, sub: str) -> ModalFrame:
        """A fresh card (in place of the one showing): Bun with his survey, the words, ✕."""
        if self.frame is not None:
            self.frame.hide()
            self.frame.deleteLater()
        from soundboard.ui.bun.bunny import bunny_pixmap
        f = self.frame = ModalFrame(title, sub, mascot="", parent=self.mw)
        bun = QLabel()
        bun.setPixmap(bunny_pixmap(BUN, "survey", dpr=self.mw.devicePixelRatioF() or 1.0))
        f.set_picture(bun)
        f.close_btn.clicked.connect(self.close)
        esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), f, self.close)
        esc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        f.setAccessibleName(title)
        return f

    def vote(self, thumb: str):
        """A thumb: sent now, then what they'd say about it."""
        self.thumb = thumb
        usage.survey(self.sid, thumb)
        f = self._frame(_("Nice! What do you like most?") if thumb == "positive"
                        else _("Sorry about that. What should we fix?"),
                        _("Optional. Never linked to you."))
        if thumb == "negative":
            from soundboard.ui.kit.panellayouts import Flow
            row = QWidget()
            flow = Flow(row, gap=8)
            for tag, words in REASONS:
                b = QPushButton(words())
                b.setObjectName("filterchip")
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.clicked.connect(lambda _checked=False, t=tag: self.send_reason(t))
                flow.addWidget(b)
            f.add_widget(row)
        self.said = QLineEdit()
        self.said.setPlaceholderText(_("Or type your own") if thumb == "negative" else _("Type here"))
        self.said.setMaxLength(SAID_MAX)
        self.said.returnPressed.connect(self.send_said)
        f.add_widget(self.said)
        f.add_button(_("Skip")).clicked.connect(self.skip)
        f.add_button(_("Send"), primary=True).clicked.connect(self.send_said)
        self._place()
        f.show()
        f.raise_()
        self.said.setFocus()

    def send_reason(self, tag: str):
        """A one-tap reason under a thumb down: sent as its tag, then on as Send goes."""
        usage.survey(self.sid, self.thumb, tag)
        self.ask_uninstall()

    def send_said(self):
        text = self.said.text().strip() if self.said is not None else ""
        if self.thumb and text:
            usage.survey(self.sid, self.thumb, text)
        if self.thumb == "negative":
            self.ask_uninstall()
            return
        self._hide()
        busy.toast(self.mw, _("Thanks for telling us!"), "ok")

    def skip(self):
        """Skip under the words: nothing typed is sent; after a thumb down, the uninstall card."""
        if self.thumb == "negative":
            self.ask_uninstall()
        else:
            self.close()

    def ask_uninstall(self):
        """After a thumb down: the button that takes Onion Board off this PC, or Keep it."""
        self.said = None
        self.asked_uninstall = True
        f = self._frame(_("Sorry it's not for you"),
                        _("Please click this button to uninstall Onion Board and completely "
                          "remove it from your computer."))
        keep = f.add_button(_("Keep it"))
        keep.clicked.connect(self.keep)
        f.add_button(_("Uninstall Onion Board"), danger=True).clicked.connect(self.uninstall)
        self._place()
        f.show()
        f.raise_()
        keep.setFocus()

    def keep(self):
        usage.survey(self.sid, "uninstall-no")
        self._hide()

    def uninstall(self):
        """Its own uninstaller (it asks "are you sure", then whether to delete the sounds),
        and the app quits so its files can go. No uninstaller: Windows' Installed apps."""
        usage.survey(self.sid, "uninstall-yes")
        self._hide()
        exe = uninstaller()
        if exe is not None:
            try:
                subprocess.Popen([str(exe)], cwd=str(exe.parent), close_fds=True,
                                 creationflags=0x00000008 | 0x00000200)   # detached, own group
            except OSError:
                log.exception("couldn't start the uninstaller")
            else:
                QTimer.singleShot(QUIT_AFTER_MS, self.mw.quit_app)
                return
        busy.open_url(INSTALLED_APPS, window=self.mw)

    def close(self):
        """✕, Esc, Skip or a click outside: closed for good (counted as dismissed when no
        thumb was clicked)."""
        if not self.is_open:
            return
        if not self.thumb:
            usage.survey(self.sid, "dismissed")
        elif self.asked_uninstall:
            usage.survey(self.sid, "uninstall-no")   # closed without uninstalling
        self._hide()

    def _hide(self):
        self.mw.removeEventFilter(self)
        # the focus back to the page: left to Qt, it went to the next button (the sidebar's
        # Sounds), drawn with the keyboard focus ring though nobody pressed Tab
        tabs = getattr(self.mw, "tabs", None)
        page = tabs.currentWidget() if tabs is not None else None
        (page or self.mw).setFocus(Qt.FocusReason.OtherFocusReason)
        for w in (self.frame, self.scrim):
            if w is not None:
                w.hide()
                w.deleteLater()
        self.frame = self.scrim = self.said = None
        self.asked_uninstall = False

    def _place(self):
        """The dim over the whole window, the card in its middle (a little above)."""
        mw = self.mw
        if self.scrim is not None:
            self.scrim.setGeometry(mw.rect())
        f = self.frame
        if f is None:
            return
        w = max(1, min(WIDTH, mw.width() - 2 * EDGE))
        f.setFixedWidth(w)
        h = f.heightForWidth(w) if f.hasHeightForWidth() else f.sizeHint().height()
        h = min(max(h, f.minimumSizeHint().height()), mw.height() - 2 * EDGE)
        f.setFixedHeight(h)
        f.move((mw.width() - w) // 2, max(EDGE, (mw.height() - h) // 2 - 40))

    def eventFilter(self, obj, ev):   # noqa: N802 - Qt API
        if obj is self.mw and self.is_open and ev.type() == QEvent.Type.Resize:
            self._place()
        return False
