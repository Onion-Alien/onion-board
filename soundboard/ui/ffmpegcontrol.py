"""FFmpeg in the main window: the check at start-up, getting it by itself when it's
missing or won't start, Fix it / Get FFmpeg / Reinstall (the bar or Settings → Data &
quality), and the slim bar across the top that shows how far a download is, with Stop.

MainWindow makes one ``FfmpegControl`` (``MainWindow.ffctl``), puts its ``bar`` among
the top bars and sends it the bridge's ``ffmpeg`` / ``ffmpeg_progress`` signals. The
work runs on workers (ffmpegget); everything here runs on the UI thread."""
from __future__ import annotations

import html
import threading
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton
from shiboken6 import isValid as qt_valid

from soundboard.core import errors, usage
from soundboard.online import quality
from soundboard.online import ffmpegget, net, netlog
from soundboard.i18n import _
from soundboard.ui import busy, icons, worker
from soundboard.ui.controller import Controller

if TYPE_CHECKING:
    from soundboard.ui.mainwindow import MainWindow

ASK_OFF = "ffmpeg-offer"   # in Config.tips_seen: the FFmpeg bar's Don't ask again


class FfmpegControl(Controller):
    """The FFmpeg check, fix and bar for one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self.health: ffmpegget.Health | None = None   # the last check's answer
        self.checking = False
        self.not_now = False   # hidden until the next start
        self.error = ""        # the last fix's error, shown on the bar
        self.waiting: list = []   # (button, release) of fixes still going
        self.getting = False   # a fix is going (by itself or clicked)
        self.percent = -1      # ...how far its download is (-1: not known)
        self.stop_flag: threading.Event | None = None   # Stop sets it
        self.auto_tried = False   # got by itself once this start (not again)
        self.auto_now = False     # the get running now is that one (for the count)
        self.done = False         # the last fix worked (Settings says so)

    def build_bar(self) -> QFrame:
        """Its download's progress with Stop, or, when the app couldn't get it by itself,
        what stops working and Fix it. The same slim bar as the Discord offer, never a
        window"""
        self.bar = QFrame()
        self.bar.setObjectName("tipbar")
        fh = QHBoxLayout(self.bar)
        fh.setContentsMargins(12, 6, 6, 6)
        fh.setSpacing(8)
        self.lbl = QLabel()
        self.lbl.setTextFormat(Qt.TextFormat.PlainText)   # winget's own words may be in it
        self.lbl.setWordWrap(True)
        fh.addWidget(self.lbl, 1)
        self.fix_btn = QPushButton(_("Fix it"))
        self.fix_btn.setObjectName("primary")
        self.fix_btn.clicked.connect(self._fix_clicked)
        fh.addWidget(self.fix_btn)
        self.stop_btn = QPushButton(_("Stop"))
        self.stop_btn.setObjectName("small")
        self.stop_btn.clicked.connect(self._stop)
        fh.addWidget(self.stop_btn)
        self.never_btn = QPushButton(_("Don't ask again"))
        self.never_btn.setObjectName("small")
        self.never_btn.setToolTip(_("Settings → Data & quality still has it"))
        self.never_btn.clicked.connect(self._never)
        fh.addWidget(self.never_btn)
        hide = QPushButton()
        hide.setObjectName("urgenthide")
        hide.setAccessibleName(_("Hide"))
        hide.setToolTip(_("Hide until Onion Board starts again"))
        icons.close_button(hide, 28)
        hide.clicked.connect(self._not_now)
        fh.addWidget(hide)
        self.hide_btn = hide
        self.bar.hide()
        return self.bar

    def check(self):
        """Is FFmpeg there and does it start? The answer of the check started behind the
        loading screen (ffmpegget.start_check), or a new one, taken on a worker (it runs
        ffmpeg); it comes back to on_answer, which gets FFmpeg by itself when needed."""
        if self.checking:
            return
        self.checking = True

        # no answer is never a crash: the check failed
        worker.run(lambda: (ffmpegget.answer(), None), self.mw.bridge.ffmpeg, "ffmpeg-check",
                   error=(None, None), owner=self.mw)

    def may_get(self) -> bool:
        """Get FFmpeg without asking: unless the user said not to go online for it
        (Offline mode, its switch, Low data mode) or not to ask about it again."""
        return (not self.auto_tried and ASK_OFF not in self.mw.cfg.tips_seen
                and not ffmpegget.why_not() and not quality.current.low_data)

    def fix_clicked(self, btn: QPushButton, force: bool = False):
        """Fix it / Get FFmpeg / Reinstall (the bar or Settings): pressing it is a yes,
        so a switched-off FFmpeg download is switched back on. Offline mode stays: it
        says so instead."""
        mw = self.mw
        if self.getting or busy.is_busy(btn):
            return
        if net.offline():
            mw.toast(html.escape(net.off_message(ffmpegget.FEATURE)), "warn", 8000)
            return
        if not net.allowed(ffmpegget.FEATURE):
            off = [k for k in mw.cfg.net_off if k != ffmpegget.FEATURE]
            mw.set_option("net_off", off)
            net.configure_features(mw.cfg.net_off, mw.cfg.net_offline)
            mw.toast(_("FFmpeg downloads are switched on again (Settings → Privacy & "
                       "security)."))
        self.fix(btn, force)

    def fix(self, btn: QPushButton | None = None, force: bool = False, auto: bool = False):
        """Get FFmpeg, or repair one that won't start (``force``: reinstall a working
        one), on a worker: winget, then the app's own download (ffmpegget.fix). The bar
        shows how far it is, with Stop; ``btn`` shows it's busy and then whether it
        worked; the bar and Settings show the new state."""
        if self.getting:
            return
        usage.used("get-ffmpeg-auto" if auto else "get-ffmpeg")
        self.getting, self.percent, self.error = True, -1, ""
        self.auto_now = auto
        self.auto_tried = self.auto_tried or auto
        stop = self.stop_flag = threading.Event()
        if btn is not None:
            self.waiting.append((btn, busy.hold(btn, _("Getting FFmpeg…"))))
        seen = [-1]
        bridge = self.mw.bridge

        def progress(done: int, total: int):
            pct = min(99, done * 100 // total) if total else -1
            if pct != seen[0]:
                seen[0] = pct
                busy.emit(bridge.ffmpeg_progress, pct)

        def work():
            netlog.cause(ffmpegget.FEATURE,
                         "FFmpeg was missing or wouldn't start when the app started" if auto
                         else "You clicked Fix it, Get FFmpeg or Reinstall (the FFmpeg bar, "
                              "or Settings > Data & quality)")
            err: object = ""
            try:
                ffmpegget.fix(force, progress, stop)
            except ffmpegget.GetError as e:
                err = e
            return ffmpegget.last(), err

        def failed(e):   # shown, never a stuck button
            return None, ffmpegget.GetError(_("Couldn't get FFmpeg ({error}).",
                                              error=errors.plain(e)))
        worker.run(work, bridge.ffmpeg, "ffmpeg-get", error=failed, owner=self.mw)
        self.news()

    def on_progress(self, pct: int):
        if self.getting:
            self.percent = pct
            self.news()

    def on_answer(self, h, err):
        """A check's answer (``err`` None) or a fix's (``err`` "" when it worked, else
        the GetError)."""
        mw = self.mw
        if h is not None:
            self.health = h
            if not err:   # a check or successful fix, never a failed/cancelled fix's stale health
                usage.ffmpeg_state(mw.cfg, "slow" if h.slow else h.state)
                usage.remember(mw.cfg)
                mw._save_later()
        if err is None:
            self.checking = False
            if h is not None and h.state != ffmpegget.OK and self.may_get():
                self.fix(auto=True)
                return
        else:
            self.getting, self.stop_flag = False, None
            stopped = isinstance(err, ffmpegget.Stopped)
            if err and not stopped:
                usage.used("get-ffmpeg-auto-failed" if self.auto_now
                           else "get-ffmpeg-failed")
                usage.ffmpeg_state(mw.cfg, "get-failed")
                usage.remember(mw.cfg)
                mw._save_later()
            for btn, release in self.waiting:
                if qt_valid(btn):
                    release(None if stopped else _("✗ Failed") if err else _("✓ Got FFmpeg"))
            self.waiting.clear()
            self.error = "" if stopped else errors.plain(err) if err else ""
            self.done = not err
            if stopped:
                pass
            elif err:
                mw.toast(html.escape(self.error), "error", 8000)
            elif h is not None and h.version:
                mw.toast(_("FFmpeg works now (version {version}).",
                           version=html.escape(h.version)), "ok")
            else:
                mw.toast(_("FFmpeg works now."), "ok")
        self.news()

    def news(self):
        """The bar, and Settings' FFmpeg row if it's built, show the current state."""
        self.show_bar()
        dlg = self.mw.setctl._settings_dlg
        if dlg is not None and qt_valid(dlg):
            dlg.privacy._ffmpeg_sync()

    def show_bar(self):
        """While FFmpeg downloads: how far, with Stop. When it's missing or won't start
        and the app couldn't get it by itself: what stops working, and Fix it. Hidden by
        ✕ until the next start, and for good by Don't ask again."""
        h = self.health
        if self.not_now or (not self.getting and (
                h is None or h.state == ffmpegget.OK or ASK_OFF in self.mw.cfg.tips_seen)):
            self.bar.hide()
            return
        if self.getting:
            text = (_("Getting FFmpeg, so M4A, AAC and video files play and videos can be "
                      "saved… {percent}%", percent=self.percent)
                    if self.percent >= 0 else
                    _("Getting FFmpeg, so M4A, AAC and video files play and videos can be "
                      "saved…"))
            why = ""
        else:
            assert h is not None
            if h.state == ffmpegget.MISSING:
                text = _("FFmpeg is missing, so M4A, AAC and video files won't play and "
                         "videos can't be saved.")
            else:
                text = _("FFmpeg won't start ({error}), so M4A, AAC and video files won't "
                         "play and videos can't be saved.", error=h.why or _("no reason given"))
            why = (self.error or ffmpegget.why_not()
                   or (_("Low data mode is on, so it wasn't downloaded by itself (about "
                         "110 MB).") if quality.current.low_data else ""))
        self.lbl.setText("\n".join(t for t in (text, why) if t))
        for b, on in ((self.fix_btn, not self.getting), (self.never_btn, not self.getting),
                      (self.stop_btn, self.getting)):
            if not on and b.hasFocus():
                self.hide_btn.setFocus()   # hiding a focused button jumps focus elsewhere
            b.setVisible(on)
        self.bar.show()

    def _fix_clicked(self):
        self.fix_clicked(self.fix_btn)

    def _stop(self):
        if self.stop_flag is not None:
            self.stop_flag.set()
            busy.flash(self.stop_btn, _("Stopping…"))

    def _not_now(self):
        self.not_now = True
        self.bar.hide()

    def _never(self):
        mw = self.mw
        self.bar.hide()
        if ASK_OFF not in mw.cfg.tips_seen:
            mw.cfg.tips_seen.append(ASK_OFF)
        mw._save_later()
        mw.toast(_("Won't ask about FFmpeg again. Settings → Data & quality still has it."))
