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
from soundboard.ui.kit import closeask
from soundboard.ui.kit import icons
from soundboard.ui.bun.logowidget import glow_icon
from soundboard.i18n import _

from soundboard.ui.window.windowparts import WindowParts
log = logging.getLogger("soundboard.ui.window.mainwindow")


class _LeftMenu(QMenu):
    """A menu in the tray's menu: the tray sits in the screen's bottom right, so it
    opens to the left of the menu it's in, like steps, instead of back over it. A click
    on a row does it without closing the menus: voices are tried one after another."""

    def mouseReleaseEvent(self, e):
        act = self.actionAt(e.position().toPoint())
        if act is not None and act.isEnabled() and act.menu() is None and not act.isSeparator():
            act.trigger()
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def showEvent(self, e):
        super().showEvent(e)
        up = self.parentWidget()
        if isinstance(up, QMenu) and up.isVisible():
            x = up.geometry().left() - self.width()
            screen = self.screen().availableGeometry()
            if x >= screen.left():
                self.move(x, self.y())


def _sub(menu: QMenu, title: str) -> QMenu:
    sub = _LeftMenu(title, menu)
    menu.addMenu(sub)
    return sub


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
        self._tray_voices = _sub(menu, _("Voice changer"))
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
        """The tray's Voice changer menu: Clean mic; Favorites, with the voices you
        starred on the Voice tab in two menus, Voice changer and AI voices (one of
        each can be on: picking one swaps it, picking the ticked one turns it off);
        what's on now as plain rows; and the switch for the voices. Made each time it
        opens, so it's never out of date."""
        m = self._tray_voices
        m.clear()
        fx = self.hkctl._voice_fx()
        if fx is None:
            m.addAction(_("The Voice tab is switched off")).setEnabled(False)
            return
        ai = self.hkctl._ai_panel()
        ai_on = ai is not None and ai.is_on()
        ai_now = ai.current_voice() if ai is not None and ai_on else None
        clean = self.voice.clean
        a = m.addAction(_("Clean mic"), lambda: (usage.used("tray-clean-mic"),
                                                 clean.set_on(not clean.is_on()),
                                                 self._sync_tray_voices()))
        a.setCheckable(True)
        a.setChecked(clean.is_on())
        a.setEnabled(clean.ok)
        rows = self._tray_rows = {"clean": a, "fx": [], "ai": []}
        voices = fx.voice_names()
        favs = [n for n in fx.favorites if n in voices]
        ids = {vo["id"] for vo in ai.voices} if ai is not None else set()
        stars = [v for v in ai.favorites if v in ids] if ai is not None else []
        fx_on = fx.btn_power.isChecked()
        fav_menu = _sub(m, _("Favorites"))
        if favs:
            sub = _sub(fav_menu, _("Voice changer"))
            for n in favs:
                on = fx_on and fx.preset == n
                # (an "&" in a name shows as itself: Qt reads one as a shortcut marker)
                a = sub.addAction(fx.title_of(n).replace("&", "&&"),
                                  lambda n=n: self._tray_pick_voice(n))
                a.setCheckable(True)
                a.setChecked(on)
                rows["fx"].append((a, n))
        if stars and ai is not None:
            sub = _sub(fav_menu, _("AI voices"))
            for v in stars:
                on = ai_now == v
                a = sub.addAction(self.hkctl._ai_name(v).replace("&", "&&"),
                                  lambda v=v: self._tray_pick_ai_voice(v))
                a.setCheckable(True)
                a.setChecked(on)
                rows["ai"].append((a, v))
        if not favs and not stars:
            fav_menu.addAction(_("Star voices on the Voice tab to list them here")
                               ).setEnabled(False)
        # what's on now: words, not rows to click (hidden when nothing is on)
        rows["fx_now"] = m.addAction("")
        rows["fx_now"].setEnabled(False)
        rows["ai_now"] = m.addAction("")
        rows["ai_now"].setEnabled(False)
        m.addSeparator()
        rows["power"] = m.addAction("", lambda: (
            usage.used("tray-voice-toggle"),
            self._tray_voice_power(not self._tray_voices_on()),
            self._sync_tray_voices()))
        self._sync_tray_voices()

    def _tray_voices_on(self) -> bool:
        fx, ai = self.hkctl._voice_fx(), self.hkctl._ai_panel()
        return bool(fx is not None and fx.btn_power.isChecked()) or bool(
            ai is not None and ai.is_on())

    def _tray_pick_voice(self, name: str):
        usage.used("tray-voice-pick")
        fx = self.hkctl._voice_fx()
        if fx is not None and fx.btn_power.isChecked() and fx.preset == name:
            self.hkctl._set_voice(False)
        else:
            self.hkctl.pick_voice(name)
        self._sync_tray_voices()

    def _tray_pick_ai_voice(self, voice: str):
        usage.used("tray-ai-voice-pick")
        ai = self.hkctl._ai_panel()
        if ai is not None and ai.is_on() and ai.current_voice() == voice:
            ai.stop()
        else:
            self.hkctl.pick_ai_voice(voice)
        self._sync_tray_voices()

    def _sync_tray_voices(self):
        """The Voice changer menus' ticks and words as they are now: the menus stay open
        when a row is clicked, so they're brought up to date in place."""
        rows = getattr(self, "_tray_rows", None)
        fx, ai = self.hkctl._voice_fx(), self.hkctl._ai_panel()
        if not rows or fx is None:
            return
        clean = self.voice.clean
        rows["clean"].setChecked(clean.is_on())
        fx_on = fx.btn_power.isChecked()
        ai_on = ai is not None and ai.is_on()
        ai_now = ai.current_voice() if ai is not None and ai_on else None
        for a, n in rows["fx"]:
            a.setChecked(fx_on and fx.preset == n)
        for a, v in rows["ai"]:
            a.setChecked(ai_now == v)
        now = rows["fx_now"]
        now.setVisible(fx_on)
        if fx_on:
            now.setText(_("Voice changer: {voice}", voice=fx.title_of(fx.preset)).replace(
                "&", "&&"))
        now = rows["ai_now"]
        now.setVisible(bool(ai_now))
        if ai_now:
            now.setText(_("AI voice: {voice}", voice=self.hkctl._ai_name(ai_now)).replace(
                "&", "&&"))
        rows["power"].setText(_("Turn voices off") if fx_on or ai_on
                              else _("Turn on the voice changer"))

    def _tray_voice_power(self, on: bool):
        """The tray's on / off: on is the voice changer (as its hotkey), off is every
        voice that changes your mic (the voice changer and the AI voice). Clean mic has
        its own tick and stays as it is."""
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

    def _ask_how_to_close(self) -> bool:
        """The first ✕ ever: keep running in the tray, or close fully? True while that
        question is up (the window stays until it's answered). Its answer is the Close
        to tray setting, so it's asked once, and never when the window isn't showing
        (a quit from the tray, the installer, Windows signing out)."""
        if self.cfg.close_asked or not self.isVisible():
            return False
        if self._close_ask is None:
            if self.isMinimized():   # a question on a minimised window can't be seen
                self.showMaximized() if self.cfg.window_maximized else self.showNormal()
            self._close_ask = closeask.CloseAskDialog(self)
            self._close_ask.finished.connect(self._close_answered)
            self._close_ask.open()
        else:
            self._close_ask.raise_()
        return True

    def _close_answered(self, answer: int):
        self._close_ask = None
        if answer == closeask.CANCELLED or self._shut_down:
            return   # changed their mind, or the app quit meanwhile
        self.set_option("close_asked", True)
        if answer == closeask.QUIT:
            self.set_option("tray", False)
        self.close()

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
