"""Quick setup: three steps, one per page, in plain words. Shown on the very first
launch (and from the Setup tab's Step-by-step guide button any time after).

  1. Your mic and headphones              (live level bar: "talk, it should move", and a
                                           test sound)
  2. Where your sounds go                 (straight into the mic, the virtual cable,
                                           another device or nowhere)
  3. Tell Discord / your game / OBS       (the one setting outside the app)

On the very first launch only (Config.use_mode is "" just then), step 3 is "Make it
yours" instead: the tabs to start with (OPTIONAL_TABS), a language and a look, and a
"Set up Discord" switch that opens the Discord guide (and Discord) once they finish.

Every choice is applied to the engine as it's made, so the level bar and the test
sound use the real devices. The window's own device boxes are refreshed at the end.

This file is the guide's frame (the steps, Back / Next, its motion); each step's page
is a mixin of its own: devicestep, cablestep, discordstep and lookstep (the first
launch's), built from wizardkit's sizes and wizardparts' widgets.
"""
from __future__ import annotations

import ctypes
import logging
import subprocess
import sys
import time

from PySide6.QtCore import (QEasingCurve, QEvent, QEventLoop, QSize, Qt, QTimer,
                            QVariantAnimation, Signal)
from PySide6.QtWidgets import (QApplication, QDialog, QGraphicsOpacityEffect, QHBoxLayout,
                               QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from soundboard.core import autostart
from soundboard.mic import directmic, micstate, mictest
from soundboard.core import usage
from soundboard.ui.kit import busy, fit, icons
from soundboard.ui.bun.bunnywidget import TALK
from soundboard.ui.kit.choicetile import ChoiceTile
from soundboard.i18n import _
from soundboard.ui.kit.toast import animations_on
from soundboard.ui.setup import cablestep
from soundboard.ui.setup.cablestep import CableStep, RESTART_NEEDED
from soundboard.ui.setup.devicestep import DeviceStep
from soundboard.ui.setup.discordstep import DiscordStep
from soundboard.ui.setup.lookstep import LookStep
from soundboard.ui.setup.miclater import mic_later
from soundboard.ui.setup.wizardkit import (CONTENT_W, MARGIN, NAV_GAP, SETTLE_MS, _bad,
                                           _nav_words, _ok)
from soundboard.ui.setup.wizardparts import StepBar, _PageStack, _StepScroll

log = logging.getLogger(__name__)

TICK_MS = 40            # the mic page's meter
SLOW_TICK_MS = 250      # the other pages: only the cable installer to keep up with
LOCK_MAX_S = 180        # the mic set-up holds the guide shut at most this long
LOCK_NOTE_MS = 3000     # how long "almost done" shows when they try to close it then
DISCORD_READ_MS = 2000  # the last step re-reads Discord's own settings this often
# the device steps by name, for the count of where the guide was closed (usage.py)
PAGE_NAMES = ("mic", "send", "last")   # (the mic and headphones share step 1: "mic")
MIC_TEST_MIN_S = 3      # on the mic step at least this long before its test is counted
# a click or key that reaches the guide over STALE_MS after it was made was queued while
# the window was stuck (a first launch once froze the PC for a minute): dropped, or the
# Esc / X / Next clicks made meanwhile all land at once and close or skip it. Windows
# stamps each one with when it was made (Qt's event timestamp, GetTickCount's clock).
# (Not a heartbeat timer: waking up, Qt runs the overdue timers before the input.)
STALE_MS = 1000
_INPUT = (QEvent.Type.KeyPress, QEvent.Type.KeyRelease, QEvent.Type.MouseButtonPress,
          QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick)
# the guide's motion (only with Windows' Animation effects on: toast.animations_on)
ENTER_MS, ENTER_DELAY_MS, RISE = 340, 360, 24   # in: fades up from RISE px lower, once
# the backdrop's logo has nearly faded out (setupbackdrop.SETTLE_MS)
LEAVE_MS, SINK = 180, 12                         # out: fades, sinking a little


class SetupWizard(LookStep, DeviceStep, CableStep, DiscordStep, QDialog):
    KEEP_OPEN = True   # a click outside doesn't close it: it would lose work
    PAGES = 3
    _discord_read = Signal(object, object)   # worker -> UI: (files' signature, settings)

    def __init__(self, win, resumed: bool = False):
        """`resumed`: opened by itself after the restart the cable asked for, so it
        starts on the cable step and welcomes them back."""
        super().__init__(win)
        self._resumed = resumed
        fit.watch(self)   # grows to fit its text (ui/kit/fit.py)
        self.win = win
        self.setWindowTitle(_("Onion Board: quick setup"))
        # inside the window, not a window of its own: a card in the middle of the
        # plain backdrop (run_setup), kept there as the window changes size; its own
        # close button, as there's no title bar (a second one under the window's read
        # like two apps)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.setObjectName("setupcard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setProperty(fit.MARGIN, 2 * self.EDGE)
        self.setProperty(fit.SCROLLS, True)   # too tall for the window: the step scrolls
        win.installEventFilter(self)
        # as wide as a row of tiles plus the margins: the tiles' right edge lines up
        # with Next's (DESIGN.md: everything on the same edges)
        self.setMinimumWidth(CONTENT_W + 2 * MARGIN)   # (the height follows each step)
        # the cable installer, while it runs (one a closed guide left running included)
        self._proc: subprocess.Popen | None = \
            cablestep._installer if cablestep._installer is not None \
            and cablestep._installer.poll() is None else None
        self._cable_tries = 0
        self._needs_restart = False   # the installer said Windows must restart first
        self._cable_step = ""         # the installer's current step (CABLE_STEPS)
        self._steps_seen: list[str] = []
        # the devices from before the guide: a page that stands in the first one it
        # finds for a missing (unplugged) device must not overwrite them on Cancel
        self._saved_devices = {"mic_device": win.cfg.mic_device,
                               "mon_device": win.cfg.mon_device}
        self._user_picked: set[str] = set()   # the ones they actually clicked
        self._chose_cable = False   # "Virtual cable instead" clicked here
        self._dev_since: float | None = None   # when the mic step was shown (its test count)
        # the steps: the mic and headphones, then where the sounds go, then the last one:
        # on the first launch "Make it yours" (tabs, language, look and a "Set up
        # Discord" switch), any other time the Discord step (its page stays built on
        # the first launch too, for its words, but isn't a step then)
        self._ask_use = win.cfg.use_mode == ""
        self.dev_index, self.send_index = 0, 1
        self.look_index = 2 if self._ask_use else -1
        self.switch_index = 3 if self._ask_use else -1
        self.discord_index = 4 if self._ask_use else 2
        self.PAGES = 4 if self._ask_use else 3
        self._lang_pending = False   # a language picked there: Finish restarts into it
        # Discord's own settings, read live on the last step (discordcfg)
        self._discord_sig: tuple | None = None
        self._discord_found: list | None = None   # None: not read (or no Discord)
        self._discord_reading = False
        self._discord_read.connect(self._discord_in)

        v = QVBoxLayout(self)
        # (the steps reach into the right margin, for their scroll bar: _StepScroll)
        v.setContentsMargins(MARGIN, 18, MARGIN - _StepScroll.ROOM, 18)
        v.setSpacing(12)
        top = QHBoxLayout()   # the step bar, then "Step 2 of 5"
        top.setContentsMargins(0, 0, _StepScroll.ROOM, 0)
        top.setSpacing(12)
        self.step_bar = StepBar(self.PAGES)
        top.addWidget(self.step_bar, 0, Qt.AlignmentFlag.AlignVCenter)
        self.progress = QLabel()
        self.progress.setObjectName("hint")
        top.addWidget(self.progress)
        top.addStretch(1)
        self.btn_close = QPushButton()
        self.btn_close.setProperty("quiet", True)
        icons.set_icon(self.btn_close, "close", size=16)
        self.btn_close.setToolTip(_("Close"))
        self.btn_close.setAccessibleName(_("Close"))
        self.btn_close.setAutoDefault(False)   # (Enter is Next's)
        self.btn_close.clicked.connect(self.reject)
        top.addWidget(self.btn_close, 0, Qt.AlignmentFlag.AlignVCenter)
        v.addLayout(top)
        self.stack = _PageStack()
        self.steps_scroll = _StepScroll(self.stack)
        v.addWidget(self.steps_scroll, 1)
        self.stack.addWidget(self._page_devices())
        self.stack.addWidget(self._page_cable())
        if self._ask_use:
            self.stack.addWidget(self._page_look())
            self.stack.addWidget(self._page_switches())
        self.stack.addWidget(self._page_discord())
        for i in range(self.stack.count()):   # the pages' edges are the dialog's: their
            page = self.stack.widget(i)          # cards line up with Back / Next
            if page is not None and (lay := page.layout()) is not None:
                lay.setContentsMargins(0, 0, 0, 0)
        # fill the last page's text now (its pill and card show from the start)
        self._fill_discord()

        nav = QHBoxLayout()
        nav.setContentsMargins(0, 0, _StepScroll.ROOM, 0)
        self.btn_back = QPushButton(NAV_GAP + _nav_words(_("←  Back")))
        rtl = QApplication.isRightToLeft()
        icons.set_icon(self.btn_back, "nav_next" if rtl else "nav_back")   # painted: bolder
        self.btn_back.clicked.connect(self.back_clicked)
        nav.addWidget(self.btn_back)
        nav.addStretch(1)
        # the send step, not set up: Next does the setting up, so leaving it without is
        # this quiet button, saying what that means (a bright "Skip for now" in Next's
        # place was the button people pressed, and their sounds then went nowhere)
        self.btn_skip = QPushButton(_("Skip: only I'll hear my sounds"))
        self.btn_skip.setProperty("quiet", True)
        self.btn_skip.clicked.connect(self.skip_clicked)
        self.btn_skip.hide()
        nav.addWidget(self.btn_skip)
        # the send step, not set up some other way (the cable, a device): Next still
        # says Next, and this line beside it says what going on without it means
        # ("Skip for now" in its place gave no reason, and people stopped there)
        self.next_why = QLabel(_("Not set up yet: only you will hear your sounds."))
        self.next_why.setObjectName("hint")
        self.next_why.setWordWrap(True)
        self.next_why.hide()
        nav.addWidget(self.next_why, 1)
        self.btn_next = QPushButton(_nav_words(_("Next  →")))
        self.btn_next.setObjectName("primary")
        # the arrow after the words, on the reading side's end
        self.btn_next.setLayoutDirection(Qt.LayoutDirection.LeftToRight if rtl
                                         else Qt.LayoutDirection.RightToLeft)
        self.btn_next.clicked.connect(self.next_clicked)
        self.btn_next.setDefault(True)   # Enter moves on (not "Play a test sound")
        nav.addWidget(self.btn_next)
        for b in (self.btn_back, self.btn_next):   # a full-page guide's way through
            b.setProperty("guide", True)
            b.setIconSize(QSize(20, 20))
        v.addLayout(nav)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(TICK_MS)
        self.discord_timer = QTimer(self)   # the last step only (go)
        self.discord_timer.timeout.connect(self._read_discord)
        self._stale_noted = False
        if (app := QApplication.instance()) is not None:
            app.installEventFilter(self)
        if self._proc is not None:   # still installing from a guide closed mid-way
            self.bun_cable.build()
        if win._attaching:
            self.setup_show.start()
        self.go(self.send_index if resumed or self._proc is not None or win._attaching else 0)

    # ------------------------------------------------------------------ navigation
    def go(self, i: int):
        i = max(0, min(self.PAGES - 1, i))
        if i != self.dev_index:
            self._count_mic_test()   # leaving the mic step (or never on it)
        elif self.stack.currentIndex() != i or self._dev_since is None:
            self._dev_since = time.monotonic()
        if i != self.send_index and self.setup_show.on:
            self.setup_show._stop()
        # the new step's words and buttons first, while it's still hidden, then show it:
        # shown first, the send step's first showing painted its unfilled state (a
        # "Checking…" card, buttons it doesn't have, the old step's size) and then grew
        # twice as its words came in (only the first time: after that it was filled)
        if i == self.send_index:
            self.recheck_cable(rescan=False)
        elif i == self.discord_index:
            self._fill_discord()
        elif i == self.switch_index:
            self._fill_discord_choice()
        self.stack.setCurrentIndex(i)
        # and its cards measured for those words now: a card's own layout only catches
        # up on its posted LayoutRequest, so the step was sized (and drawn) once with
        # a card's old height, its new words cut to one line, and grew a frame later
        for __ in range(4):   # (each card that changes asks its parent in turn)
            QApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
        self.progress.setText(_("Step {step} of {pages}", step=i + 1, pages=self.PAGES))
        self.step_bar.set_step(i)
        self.btn_back.setVisible(i > 0)
        self.timer.setInterval(TICK_MS if i == self.dev_index else SLOW_TICK_MS)
        # Discord's own settings: read now, then while the step is up
        if i == self.discord_index:
            self._read_discord()
            self.discord_timer.start(DISCORD_READ_MS)
        else:
            self.discord_timer.stop()
        self._update_next()
        # to the new step's size now, before it's drawn: drawn first at the old size,
        # a taller step showed squeezed for a moment. Its width too: the first launch's
        # last step is wider (two columns), and back from it the others are their own
        # width again (fit only grows), their tiles' edges on Back's and Next's
        lay = self.layout()
        if lay is not None and self.isVisible():
            lay.activate()   # (the new step's own least width, straight to it)
            want = max(self.minimumWidth(), lay.totalMinimumSize().width())
            if self.width() != want:
                self.resize(want, self.height())
        fit.fit(self)
        self._settle_size()
        QTimer.singleShot(SETTLE_MS, self, self._settle_size)

    _rise = 0.0   # how far below its place the guide is, coming in or going out

    _left = False

    def showEvent(self, ev):
        super().showEvent(ev)
        self.raise_()   # over the backdrop
        self._centre()
        QTimer.singleShot(SETTLE_MS, self, self._settle_size)   # the first step's height
        if animations_on() and not ev.spontaneous():
            self._set_opacity(0.0)
            QTimer.singleShot(ENTER_DELAY_MS, self, lambda: self._move_in(
                0.0, 1.0, ENTER_MS, RISE, QEasingCurve.Type.OutCubic))

    EDGE = 24   # the least room around the card, inside the window

    def eventFilter(self, obj, ev):
        if obj is self.win and ev.type() == QEvent.Type.Resize:
            self._centre()
        # (the app's too) clicks and keys queued while it was stuck: never close or
        # skip the guide (it's a card inside the window: its own widgets, not window())
        elif ev.type() in _INPUT and isinstance(obj, QWidget) \
                and (obj is self or self.isAncestorOf(obj)) and self._stale(ev):
            return True
        return False

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._centre()

    def _centre(self):
        """In the middle of the window (`_rise` below it, coming in or going out). A
        card taller or wider than the window grows the window, as far as the screen
        lets it."""
        if self.isWindow() or not self.isVisible():
            return
        p = self.parentWidget()
        if p is None:
            return
        need_w, need_h = self.width() + 2 * self.EDGE, self.height() + 2 * self.EDGE
        if (p.isWindow() and p.isVisible() and not (p.isMaximized() or p.isFullScreen())
                and (need_w > p.width() or need_h > p.height())):
            screen = p.screen() or QApplication.primaryScreen()
            avail = screen.availableGeometry()
            frame_h = p.frameGeometry().height() - p.height()
            p.resize(min(max(p.width(), need_w), avail.width()),
                     min(max(p.height(), need_h), avail.height() - frame_h))
        x = max(0, (p.width() - self.width()) // 2)
        y = max(0, (p.height() - self.height()) // 2) + round(self._rise)
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    def _set_opacity(self, v: float):
        """The card's opacity (a window's own, for a guide shown as a window)."""
        if self.isWindow():
            self.setWindowOpacity(v)
            return
        fx = self.graphicsEffect()
        if v >= 1.0:
            if fx is not None:
                # (none at rest: nothing drawn twice; Qt takes None, its stubs say no)
                self.setGraphicsEffect(None)  # pyright: ignore[reportArgumentType]
            return
        if not isinstance(fx, QGraphicsOpacityEffect):
            fx = QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(fx)
        fx.setOpacity(v)

    def _opacity(self) -> float:
        if self.isWindow():
            return self.windowOpacity()
        fx = self.graphicsEffect()
        return fx.opacity() if isinstance(fx, QGraphicsOpacityEffect) else 1.0

    def _move_in(self, a: float, b: float, ms: int, travel: int, curve, wait: bool = False):
        """Fade from opacity `a` to `b`, `travel` px below its place at 0 (the fade in,
        or out). `wait`: return once it's done (the way out, before done carries on)."""
        anim = QVariantAnimation(self)
        anim.setDuration(ms)
        anim.setStartValue(a)
        anim.setEndValue(b)
        anim.setEasingCurve(curve)

        def step(v):
            self._set_opacity(v)
            self._rise = (1 - v) * travel
            self._centre()
        step(a)
        anim.valueChanged.connect(step)
        if wait:
            loop = QEventLoop()
            anim.finished.connect(loop.quit)
            anim.start()
            loop.exec(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        else:
            anim.finished.connect(lambda: (setattr(self, "_rise", 0.0), self._centre()))
            anim.start()

    _settle_due = False

    def event(self, ev):
        # any change to what's shown (a state, a card opening): fit to it again, once
        # things have settled (fit.watch grows the window; this also shrinks it)
        if ev.type() == QEvent.Type.LayoutRequest and not self._settle_due:
            self._settle_due = True
            QTimer.singleShot(SETTLE_MS, self, self._settle_size)
        return super().event(ev)

    def _settle_size(self):
        """To the height this step needs (_PageStack), shrinking too: fit.watch only
        grows the window, so a short step after a tall one kept an empty band, and
        while a step switches Qt can briefly ask for far more room than it needs."""
        self._settle_due = False
        if not self.isVisible():
            return
        need = max(fit.needed_height(self, self.width()), self.minimumHeight())
        if self.height() > need:
            fit.shrink(self, need)

    def _update_next(self):
        i = self.stack.currentIndex()
        # while the cable installs, stay on its page: leaving it (or finishing) would
        # lose track of the installer (a mic set-up is the main window's: it reports
        # back through mic_attached wherever the guide is)
        # (greyed out with set_busy, not setEnabled: that would throw the keyboard focus
        # to another control; the click handlers check too, for Enter on the dialog)
        self._was_locked = self._locked()   # (_tick updates these when that changes)
        installing = self._proc is not None or self._was_locked
        busy.set_busy(self.btn_next, installing)
        busy.set_busy(self.btn_back, installing)
        mic_action = self._mic_action()
        self.btn_skip.setVisible(mic_action)
        self.mic_note.setVisible(self.win.cfg.route == "mic")
        SetupWizard._sync_or(self)   # (by the class: tests drive this with a stand-in)
        if i == self.PAGES - 1:
            text, icon = _("Finish  ✓"), "check"
        elif i == self.send_index and self._was_locked:
            text, icon = _("Setting up…"), "mic"
        elif mic_action:   # the step's one thing to do: Next does it (next_clicked)
            text = (_("Repair my mic  →") if directmic.needs_repair(
                directmic.status(self.win.cfg.mic_device)) else _("Put my sounds in my mic  →"))
            icon = "nav_next"
        else:
            text, icon = _("Next  →"), "nav_next"
        # going on without it is the way out, not the step's main thing: a plain Next
        # with its reason beside it, so the one filled button on the page is the one
        # that sets it up
        skip = (i == self.send_index and not mic_action and not self.route_ok()
                and not self._was_locked)
        self.next_why.setVisible(skip)
        if self.btn_next.objectName() != ("" if skip else "primary"):
            self.btn_next.setObjectName("" if skip else "primary")
            self.btn_next.style().unpolish(self.btn_next)
            self.btn_next.style().polish(self.btn_next)
        if QApplication.isRightToLeft() and icon == "nav_next":
            icon = "nav_back"   # right to left: on is to the left
        self.btn_next.setText(_nav_words(text) + NAV_GAP)
        icons.set_icon(self.btn_next, icon, "text" if skip else "on_accent")

    _lock_since: float | None = None

    _was_locked = False

    _route_was_ok: bool | None = None   # step 3's last answer (_tick)

    def _locked(self) -> bool:
        """Bun is putting the sounds into the mic: the guide stays open on its page
        until it's done (closed or moved on mid-way, they couldn't tell how it went).
        At most LOCK_MAX_S: a set-up that never answers can't trap them."""
        if not self.win._attaching:
            self._lock_since = None
            return False
        if self._lock_since is None:
            self._lock_since = time.monotonic()
        return time.monotonic() - self._lock_since < LOCK_MAX_S

    def _busy(self) -> bool:
        """Back / Next wait: the cable is installing or the mic is being set up."""
        return self._proc is not None or self._locked()

    def _mic_action(self) -> bool:
        """The send step, straight into the mic and not set up (or needing a repair):
        Next puts the sounds into the mic, the step's one thing to do, and Skip is
        the quiet way past it."""
        return (self.stack.currentIndex() == self.send_index and self.win.cfg.route == "mic"
                and self._proc is None and not self.win._attaching
                and not self.setup_show.on and not self.route_ok())

    def back_clicked(self):
        if not self._busy():
            self.go(self.stack.currentIndex() - 1)

    def next_clicked(self):
        if self._busy():
            return   # the cable is installing / the mic is set up: stay on its page
        i = self.stack.currentIndex()
        if self._mic_action():
            self.attach_mic()   # Next is "Put my sounds in my mic" here (_update_next)
        elif i == self.PAGES - 1:
            # the first launch: Discord after, if they ticked it
            self.finish(discord=i == self.switch_index and self.chk_discord.isChecked())
        else:
            self.go(i + 1)

    def skip_clicked(self):
        """Past the send step without setting it up: only they hear their sounds."""
        if self._busy():
            return
        usage.used("setup-skipped-send")
        self.go(self.stack.currentIndex() + 1)

    def finish(self, discord: bool = False):
        """`discord`: then Bun sets Discord up for sounds, over the window (the setup
        guide is gone): chatguide.set_up_discord, as every Discord button does."""
        cfg = self.win.cfg
        # Finish means done, sending set up or not: like closing it, the guide doesn't
        # open by itself again (the Setup tab's Step-by-step guide still opens it, and
        # the status pill says when only they hear the sounds)
        cfg.setup_done = True
        usage.used("setup-finished" if self.route_ok() else "setup-finished-not-sending")
        cfg.mic_enabled = self.chk_send.isChecked()
        self.win.chk_mic.setChecked(cfg.mic_enabled)
        cfg.save()
        self.win.devctl._reopen_devices()   # refresh the window's device boxes from the choices
        if self._ask_use and self.chk_autostart.isChecked() != autostart.is_enabled():
            self.win.set_autostart(self.chk_autostart.isChecked())
        sending = self.route_ok()
        self.accept()
        if self._lang_pending:   # text already on screen can't change language
            QTimer.singleShot(0, self.win.restart_app)
        elif cfg.route == "mic" and not sending:
            # skipped the mic: say where it's done, once their mic is plugged in
            win = self.win
            QTimer.singleShot(0, win, lambda: mic_later(win))
        elif discord:
            from soundboard.ui.setup.chatguide import set_up_discord
            win = self.win
            usage.used("setup-discord")
            QTimer.singleShot(0, win, lambda: set_up_discord(win))

    def _stale(self, ev) -> bool:
        """`ev` was made over STALE_MS ago: queued while the window was stuck (Windows
        only: elsewhere the stamp isn't on GetTickCount's clock). Logged once a guide."""
        made = ev.timestamp()
        if sys.platform != "win32" or not made:   # (0: made by the app itself)
            return False
        age = (ctypes.windll.kernel32.GetTickCount() - made) & 0xFFFFFFFF   # (it wraps)
        if age <= STALE_MS:
            return False
        if not self._stale_noted:
            self._stale_noted = True
            log.info("setup guide: ignored input queued while the window was stuck (%.1f s)",
                     age / 1000)
        return True

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:   # one stray Esc mustn't lose the whole set-up:
            ev.accept()                     # only the guide's own X closes it
            return
        super().keyPressEvent(ev)

    def reject(self):
        """The guide's X. Mid-install, check first: the install carries on
        either way, and reopening the guide picks it back up. While the mic is set up,
        the guide stays open (_locked) and says so, so the X doesn't look broken."""
        if self._locked():
            usage.used("setup-wait-note")
            # the app's toast, spinner and all (one at a time: pressed again, it's renewed)
            busy.toast(self, _("Bun's almost done, one moment."), "busy", LOCK_NOTE_MS,
                       key="setup-almost-done")
            return
        if self._proc is not None and self._proc.poll() is None and QMessageBox.question(
                self, _("Still installing"),
                _("Bun is still installing the virtual cable.\n\nClose the guide anyway? The "
                  "install carries on by itself; open the guide again from the Setup tab "
                  "(Step-by-step guide) to see how it went.")) \
                != QMessageBox.StandardButton.Yes:
            return
        super().reject()

    def done(self, r):
        if animations_on() and self.isVisible() and not self._left:
            self._left = True   # out: a short fade, then the rest (still at once for callers)
            self._move_in(self._opacity(), 0.0, LEAVE_MS, SINK,
                          QEasingCurve.Type.InCubic, wait=True)
        self.timer.stop()
        self.discord_timer.stop()
        if (app := QApplication.instance()) is not None:
            app.removeEventFilter(self)
        self._count_mic_test()
        if self.setup_show.on:
            self.setup_show._stop()
        page = self.stack.currentIndex()
        if r != QDialog.DialogCode.Accepted and 0 <= page < self.PAGES:
            name = "look" if page == self.look_index else PAGE_NAMES[min(page, 2)]
            usage.used(f"setup-closed-{name}")   # where people give up
        tour = self._ask_use   # the very first launch: Bun's tour of the empty board next
        if self._ask_use and page == self.switch_index:
            self._save_tabs()   # finished, or closed on the last step: the tabs as ticked
        if not self.win.cfg.use_mode:   # closed before the last step: asked once is enough
            usage.used("use-skipped")
            self.win.cfg.use_mode = "normal"
            self.win.cfg.save()
        if r != QDialog.DialogCode.Accepted:
            for k, v in self._saved_devices.items():   # keep what they had, unless
                if k not in self._user_picked:         # they picked another one here
                    setattr(self.win.cfg, k, v)
            # closed on purpose: don't open it again every launch (the Setup tab's
            # Step-by-step guide still opens it)
            self.win.cfg.setup_done = True
            self.win.cfg.save()
            self.win.devctl._reopen_devices()
        super().done(r)
        if tour:   # once the guide is gone (and the window has its devices back)
            from soundboard.ui.setup import firsttour
            if firsttour.will_run(self.win):
                # a first start opens on the Setup tab (nothing set up yet): the
                # guide's done, so on to the board it's about
                self.win.tabs.setCurrentWidget(self.win.sounds_page)
            QTimer.singleShot(firsttour.START_MS, self.win, lambda w=self.win: firsttour.start(w))

    def _count_mic_test(self):
        """How the mic test went (usage MIC_TESTS: never the mic's name), when the mic
        step was up long enough for it to mean something. Once per visit."""
        since, self._dev_since = self._dev_since, None
        if since is None or time.monotonic() - since < MIC_TEST_MIN_S:
            return
        if self._mic_peak_seen:
            kind = "heard"
        elif micstate.windows_blocks_mic():
            kind = "blocked"
        elif self._no_mics:
            kind = "no-mic"
        else:
            kind = "silent" if self.win.engine.mic_stream is not None else "no-open"
        usage.used(f"mic-test-{kind}")
        mictest.save(kind == "heard")   # for the uninstaller's feedback form

    def _tick(self):
        if (locked := self._locked()) != self._was_locked:   # the mic set-up began / ended
            self._was_locked = locked
            self._update_next()
        if self.stack.currentIndex() == self.dev_index:   # the mic's meter and Bun
            e = self.win.engine
            lvl = e.level_mic if e.mic_stream is not None else 0.0
            for tile in self.mic_group.buttons():   # the level on the picked mic's tile
                if isinstance(tile, ChoiceTile):
                    tile.set_level(lvl if tile.isChecked() else None)
            self.bun_mic.set_level(lvl)
            if lvl > TALK:
                self._mic_peak_seen = True
            if e.mic_stream is None and self._no_mics:
                self.mic_heard.setText(_("<span style='color:{colour}'>No microphone was "
                                         "found.</span> Plug one in, then open this guide again "
                                         "from the Setup tab, or press Next to carry on without "
                                         "one.", colour=_bad()))
            elif e.mic_stream is None:
                self.mic_heard.setText(_("<span style='color:{colour}'>Couldn't open that "
                                         "mic, try another one.</span>", colour=_bad()))
            elif self._mic_peak_seen:
                # your voice, done; the sounds are a step of their own (said here, or
                # "Not set up" two steps on read as the mic having stopped working)
                self.mic_heard.setText(_("<b style='color:{colour}'>✓ Hearing you! Your mic "
                                         "works.</b> That's your voice done: your sounds go "
                                         "into this mic in a moment.", colour=_ok()))
            else:
                self.mic_heard.setText(_("Waiting to hear you… if the bar doesn't move, pick "
                                         "another mic."))
            self.mic_report.set_failed(bool(self._mic_fail()))
        if (self.stack.currentIndex() == self.send_index and self._proc is None
                and not self._was_locked):
            # the step's card follows the mic effect when it changes from outside the
            # guide (a Windows update takes it off, a repair or Remove elsewhere): it
            # kept saying "Working" after the effect was gone
            if (ok := self.route_ok()) != self._route_was_ok:
                if self._route_was_ok is not None:
                    self.recheck_cable(rescan=False)
                self._route_was_ok = ok
        if self._proc is not None:
            self._read_cable_step()
            if (rc := self._proc.poll()) is not None:
                if cablestep._installer is self._proc:
                    cablestep._installer = None
                self._proc = None
                self._needs_restart = rc == RESTART_NEEDED
                self.recheck_cable()
