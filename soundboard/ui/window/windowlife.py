"""The main window's life: the tray icon and its menu, quitting and restarting, Windows
ending the session, starting with Windows, and the usage count."""
from __future__ import annotations

import logging
import os
import subprocess
import sys

from PySide6.QtWidgets import QApplication, QDialog, QMenu, QSystemTrayIcon

from soundboard.ui.kit import theme
from soundboard.core import exitwatch
from soundboard.core import achievements, autostart
from soundboard.sounds import library
from soundboard.online import net
from soundboard.core import usage
from soundboard.ui.kit import icons
from soundboard.ui.bun.logowidget import glow_icon
from soundboard.i18n import _

from soundboard.ui.window.windowparts import WindowParts
log = logging.getLogger("soundboard.ui.window.mainwindow")


class WindowLife(WindowParts):
    """MainWindow's tray, quit, restart, autostart and usage count (a mixin)."""

    # ------------------------------------------------------------------ tray
    def _init_tray(self):
        """The tray icon: closing the window keeps the app (and its hotkeys) running
        there, unless turned off in Settings. No tray (some desktops): close quits."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        t = self.tray = QSystemTrayIcon(glow_icon(theme.T["accent"], theme.T["accent2"], 0.0), self)
        t.setToolTip(self.title)
        menu = QMenu(self)
        icons.set_icon(menu.addAction(_("Open Onion Board"), self.show_from_tray), "sounds")
        icons.set_icon(menu.addAction(_("Stop all sounds"), self.playctl.stop_all), "stop")
        self._tray_bun = menu.addAction(self.builder._bun_icon(), _("Turn into Bun"),
                                        self.bunctl.tray_bun)
        menu.aboutToShow.connect(self._name_tray_bun)
        self._tray_voices = menu.addMenu(_("Voice changer"))
        icons.set_icon(self._tray_voices.menuAction(), "wave")
        self._tray_voices.aboutToShow.connect(self._fill_tray_voices)
        menu.addSeparator()
        # the Discord opens in the browser (feedback.py); Send feedback asks first
        from soundboard.core import feedback
        icons.set_icon(menu.addAction(_("Join the Discord"), lambda: self.aboutctl._open_page(
            feedback.DISCORD_URL)), "speech")
        icons.set_icon(menu.addAction(_("Send feedback"), self.aboutctl.ask_feedback), "edit")
        menu.addSeparator()
        icons.set_icon(menu.addAction(_("Quit"), self.quit_app), "stop")
        t.setContextMenu(menu)
        t.activated.connect(self._on_tray)
        t.messageClicked.connect(self.show_from_tray)
        t.show()
        QApplication.setQuitOnLastWindowClosed(False)

    def _fill_tray_voices(self):
        """The tray's Voice changer menu: on / off, Clean mic, then your favorite and
        saved voices and your starred AI voices (the ones in use ticked). Made each time
        it opens, so it's never out of date."""
        m = self._tray_voices
        m.clear()
        fx = self.hkctl._voice_fx()
        if fx is None:
            m.addAction(_("The Voice tab is switched off")).setEnabled(False)
            return
        ai = self.hkctl._ai_panel()
        ai_on = ai is not None and ai.is_on()
        on = fx.btn_power.isChecked() or ai_on
        m.addAction(_("Turn off") if on else _("Turn on"),
                    lambda: (usage.used("tray-voice-toggle"), self._tray_voice_power(not on)))
        clean = self.voice.clean
        a = m.addAction(_("Clean mic"), lambda: (usage.used("tray-clean-mic"),
                                                 clean.set_on(not clean.is_on())))
        a.setCheckable(True)
        a.setChecked(clean.is_on())
        a.setEnabled(clean.ok)
        names = [n for n in fx.favorites if n in fx.voice_names()]
        names += [n for n in fx.saved_names() if n not in names]
        ids = {vo["id"] for vo in ai.voices} if ai is not None else set()
        stars = [v for v in ai.favorites if v in ids] if ai is not None else []
        if not names and not stars:
            m.addSeparator()
            m.addAction(_("Star voices on the Voice tab to list them here")).setEnabled(False)
            return
        if names:
            m.addSeparator()
        for n in names:
            a = m.addAction(fx.title_of(n), lambda n=n: (usage.used("tray-voice-pick"),
                                                         self.hkctl.pick_voice(n)))
            a.setCheckable(True)
            a.setChecked(fx.btn_power.isChecked() and fx.preset == n)
        if stars:
            m.addSeparator()
        for v in stars:
            a = m.addAction(self.hkctl._ai_name(v), lambda v=v: (
                usage.used("tray-ai-voice-pick"), self.hkctl.pick_ai_voice(v)))
            a.setCheckable(True)
            a.setChecked(ai is not None and ai_on and ai.current_voice() == v)

    def _tray_voice_power(self, on: bool):
        """The tray's Turn on / Turn off: on is the voice changer (as its hotkey), off is
        every voice that changes your mic (the voice changer and the AI voice)."""
        self.hkctl._set_voice(on)
        ai = self.hkctl._ai_panel()
        if not on and ai is not None:
            ai.stop()

    def _name_tray_bun(self):
        """The tray's Bun item says what it does now: Bun up, it brings the window back."""
        self._tray_bun.setText(_("Back to the board") if self.bunctl.bun_up()
                               else _("Turn into Bun"))

    def _on_tray(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_from_tray()

    # ------------------------------------------------------------------ Bun mode
    def show_from_tray(self):
        self.bunctl._bun_away()
        if self.isMinimized():   # back the way it was: showNormal() un-maximised it
            self.showMaximized() if self.cfg.window_maximized else self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def can_hide(self) -> bool:
        """Whether the window may start hidden (--tray): only with a tray icon to get
        it back, and once the setup guide is done."""
        return self.tray is not None and self.tray.isVisible() and self.cfg.setup_done

    def quit_app(self):
        self._quitting = True
        self.close()

    @staticmethod
    def restart_args() -> list[str]:
        """The arguments the app starts again with (after sys.executable): this run's,
        minus the one-off ones, plus this copy's pid for the new one to wait on."""
        skip = {autostart.TRAY_ARG, "--resume-setup"}
        args = [a for a in sys.argv[1 if getattr(sys, "frozen", False) else 0:]
                if a not in skip]
        if "--restart-after" in args:   # restarted before: drop the old pid
            i = args.index("--restart-after")
            del args[i:i + 2]
        return [*args, "--restart-after", str(os.getpid())]

    def restart_app(self):
        """Quit and start again (a reset or restore point runs at start-up: see
        soundboard.core.reset). The new copy waits for this one to be gone first."""
        for w in QApplication.topLevelWidgets():   # Settings, the guide
            if isinstance(w, QDialog) and w.isVisible():
                w.reject()
        try:
            subprocess.Popen([sys.executable, *self.restart_args()],
                             creationflags=0x00000008 | 0x00000200,   # detached, own group
                             close_fds=True, env=net.own_env())   # not this copy's relay
        except OSError:
            log.exception("couldn't start the app again")
            self.toast(_("Close Onion Board and open it again to finish."), "warn")
            return
        self.quit_app()

    def _on_session_end(self, _manager=None):
        """Windows is logging off, shutting down, or an installer / updater asked the
        app to close (the Restart Manager sends the same message). Closing then really
        quits: hiding to the tray would veto it, and an upgrade run while the app is
        open would fail with "Setup was unable to close all applications"."""
        self._quitting = True
        exitwatch.closed_by_windows()   # ended before the quit finishes: not a crash

    def set_autostart(self, on: bool) -> bool:
        return autostart.set_enabled(on, self.cfg.autostart_hidden)

    def set_autostart_hidden(self, hidden: bool):
        self.set_option("autostart_hidden", hidden)
        autostart.refresh(hidden)

    # ------------------------------------------------------------------ usage count
    def send_usage(self):
        """The anonymous daily usage count, if it's due and switched on (usage.py)."""
        usage.maybe_send(self.cfg, self.bridge.counted.emit, app_dir=library.APP_DIR)

    def _usage_counted(self, apply):
        """A usage count went: here, on the UI thread that also adds to them, its
        stats_* are cleared (only what it sent) and saved."""
        apply()
        self._save_later()

    def _remember_usage(self):   # features used and time open, for the next daily count
        usage.open_tick(self.cfg)
        usage.remember(self.cfg)

    def _count_at_quit(self):   # what waits for the next count goes now (usage.at_quit)
        self._quit_count = usage.at_quit(self.cfg, app_dir=library.APP_DIR)

    def _finish_count_at_quit(self):   # waits at most usage.QUIT_WAIT_S, all told
        finish, self._quit_count = getattr(self, "_quit_count", None), None
        if finish is not None and finish():
            self.cfg.save()

    def tick_usage(self):   # every usage.OPEN_TICK_S: how long the app has been open
        usage.open_tick(self.cfg)
        cfg = self.cfg
        if achievements.tick(tor=net.mode() == net.TOR, offline=net.offline(),
                             hotkeys=sum(1 for m in cfg.sounds if m.hotkey),
                             sounds=len(cfg.sounds),
                             longest=max((m.duration for m in cfg.sounds), default=0),
                             shortest=min((m.duration for m in cfg.sounds if m.duration > 0),
                                          default=0),
                             tabs=len(cfg.categories),
                             looping=[s for s in self.engine.playing()
                                      if s in {m.id for m in cfg.sounds if m.loop}]):
            self._save_later()

    def _mark_stopped(self):
        usage.mark_stopped(library.APP_DIR)
        exitwatch.stopped()
