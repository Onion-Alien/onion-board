"""*Enjoying Onion Board?*: a small card in the middle of the window, over a dimmed app,
with Bun holding a survey and a thumb up and down. Asked once ever, at a start, of people
who really used the app on a few days before (soundboard.core.enjoy says when). A thumb
is sent at once (usage.survey); the card then asks "What do you like most?" or "What
should we fix?" over a one-line box, with Skip and Send. After a thumb down, Send shows one
more card: the button that uninstalls Onion Board (its own uninstaller, the one Installed
apps runs), or Keep it; the answer is sent too. Skip there instead locks the installed app:
the uninstall card can't be closed, and if they quit without pressing it, the next start
says thanks and runs the uninstaller (a reinstall isn't locked: the lock names this
install). The ✕, Esc or a click on the dimmed app otherwise just closes it.

It's part of the window (child widgets, never a window of its own), so it never takes the
focus from a game, and it waits for a calm moment: the window up and in front, no game
in front, no dialog open. If none comes soon after the start, it waits for the next start.
MainWindow makes one ``EnjoyControl`` (``MainWindow.enjoyctl``); everything here runs on
the UI thread."""
from __future__ import annotations

import logging
import math
import subprocess
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QWidget

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
GOODBYE_MS = 4_000       # locked: the thanks card shows this long before the uninstaller
WAVE_MS = 40             # the goodbye card's Bun: a frame this often (25 fps)
INSTALLED_APPS = "ms-settings:appsfeatures"   # no uninstaller here (a source run): Windows' list


def uninstaller() -> Path | None:
    """The installed app's uninstaller (Inno Setup's, next to the exe), or None."""
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable).resolve().parent / "unins000.exe"
    return exe if exe.is_file() else None


def install_stamp(exe: Path | None) -> str:
    """Which install this is: its uninstaller's size and time (every install rewrites it)."""
    try:
        st = exe.stat() if exe is not None else None
    except OSError:
        st = None
    return f"{st.st_size}:{st.st_mtime_ns}" if st else ""


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
        self.locked = False            # ...and it can't be closed (thumb down, then Skip)
        self.bun: QLabel | None = None
        self._wave_t = 0.0
        self._waver = QTimer(self, interval=WAVE_MS)
        self._waver.timeout.connect(self._wave)
        self._timer = QTimer(self, interval=RETRY_MS)
        self._timer.timeout.connect(self.maybe_show)

    @property
    def is_open(self) -> bool:
        return self.frame is not None

    def start(self):
        """At start: locked to uninstall? Then thanks and the uninstaller. Otherwise due?
        Then looked at after START_DELAY_MS, then every RETRY_MS."""
        cfg = self.mw.cfg
        if cfg.enjoy_lock:
            exe = uninstaller()
            if exe is not None and cfg.enjoy_lock == install_stamp(exe):
                QTimer.singleShot(START_DELAY_MS, self, self.goodbye)
                return
            cfg.enjoy_lock = ""   # a fresh install (or a source run): not locked
            self.mw._save_later()
        self.due = enjoy.due(cfg)
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
        bun = self.bun = QLabel()
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
        self.said = QLineEdit()
        self.said.setPlaceholderText(_("Type here"))
        self.said.setMaxLength(SAID_MAX)
        self.said.returnPressed.connect(self.send_said)
        f.add_widget(self.said)
        f.add_button(_("Skip")).clicked.connect(self.skip)
        f.add_button(_("Send"), primary=True).clicked.connect(self.send_said)
        self._place()
        f.show()
        f.raise_()
        self.said.setFocus()

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
        """Skip under the words: nothing typed is sent; after a thumb down, the installed
        app is locked to the uninstall card (a source run, with no uninstaller: Keep it too)."""
        if self.thumb != "negative":
            self.close()
            return
        exe = uninstaller()
        if exe is not None:
            self.mw.cfg.enjoy_lock = install_stamp(exe)
            self.mw._save_now()   # now: quitting before pressing it still uninstalls
        self.ask_uninstall(locked=exe is not None)

    def ask_uninstall(self, locked: bool = False):
        """After a thumb down: the button that takes Onion Board off this PC, and Keep it
        unless `locked` (then nothing else closes it either)."""
        self.said = None
        self.asked_uninstall = True
        self.locked = locked
        f = self._frame(_("Sorry it's not for you"),
                        _("Please click this button to uninstall Onion Board and completely "
                          "remove it from your computer."))
        if locked:
            f.close_btn.hide()
            f.add_text(_("If you close Onion Board instead, it uninstalls itself the next "
                         "time it opens."))
        else:
            keep = f.add_button(_("Keep it"))
            keep.clicked.connect(self.keep)
        go = f.add_button(_("Uninstall Onion Board"), danger=True)
        go.clicked.connect(self.uninstall)
        self._place()
        f.show()
        f.raise_()
        (go if locked else keep).setFocus()

    def goodbye(self):
        """The locked install's next start: thanks, then its uninstaller and quit."""
        self.sid = uuid.uuid4().hex
        self.thumb = "negative"
        self.locked = self.asked_uninstall = True
        self.scrim = _Scrim(self)
        f = self._frame(_("Thanks for using Onion Board!"),
                        _("I'm sorry it wasn't good for you. Uninstalling now..."))
        f.close_btn.hide()
        self._wave_t = 0.0
        self._wave()
        self._waver.start()
        self.mw.installEventFilter(self)
        self._place()
        self.scrim.show()
        f.show()
        f.raise_()
        QTimer.singleShot(GOODBYE_MS, self, self.uninstall)

    def _wave(self):
        """The goodbye card's Bun: smug, waving bye, ears and head swaying a little."""
        if self.bun is None:
            self._waver.stop()
            return
        from soundboard.ui.bun.bunny import bunny_pixmap
        t = self._wave_t
        self._wave_t += WAVE_MS / 1000
        self.bun.setPixmap(bunny_pixmap(
            BUN, dpr=self.mw.devicePixelRatioF() or 1.0, smug=True,
            wave=math.sin(t * 9), ears=4 * math.sin(t * 4.5), nod=5 * math.sin(t * 4.5),
            blink=float(t % 2.6 > 2.45)))

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
        if not self.is_open or self.locked:
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
        self._waver.stop()
        self.frame = self.scrim = self.said = self.bun = None
        self.asked_uninstall = self.locked = False

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
