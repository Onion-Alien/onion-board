"""Onion Board's own updates in the main window: the check (and Onion Watch's), the
update card's states, the download with its progress and Cancel, installing it, and
What's new after an update.

MainWindow makes one ``UpdateControl`` (``MainWindow.updctl``) and sends it the
bridge's ``update`` / ``watch_update`` / ``update_progress`` / ``update_ready``
signals. Downloads run on workers (updates.py); everything here runs on the UI thread."""
from __future__ import annotations

import html
import logging
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon
from shiboken6 import isValid as qt_valid

from soundboard.core import errors, exitwatch, updates, usage
from soundboard.online import net, netlog
from soundboard.control import remote
from soundboard.addons import watchaddon
from soundboard.i18n import _
from soundboard.ui.kit import busy, worker
from soundboard.ui.controller import Controller
from soundboard.ui.kit.crashdialog import free_dialog

if TYPE_CHECKING:
    from soundboard.ui.mainwindow import MainWindow

log = logging.getLogger(__name__)

START_CHECK_S = 4.0   # how long the loading screen waits for GitHub's answer
STALL_S = 30.0        # ...and for a download that stopped moving


class UpdateControl(Controller):
    """The update check, card, download and install for one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self.release: updates.Release | None = None   # a newer version, once found
        self._update_file: Path | None = None   # its downloaded, checked installer
        self._downloading = False
        self._update_got = (0, 0)     # bytes downloaded, of how many (0: not known)
        self._update_cancel = False   # Cancel was clicked: the download stops at its next chunk
        self._update_err = ""         # why the last try failed ("" = it didn't)
        self._update_detail = ""      # what went wrong, for Copy error
        self._update_fails = 0        # failed tries in a row: from 2, Copy error
        self._update_box: QMessageBox | None = None   # "Downloading…" open over it
        self._whats_new_later: bool | None = None   # What's new waits for the window
        # the check as the app starts is on: a newer version it finds installs itself
        # (until that check is answered, or the settling one it asks for afterwards)
        self._auto = False
        self.start_checked = False   # update_at_start had GitHub's answer
        self._auto_install = False   # this download was started by itself: install it too
        self._installing = False     # the installer is being started (start_install's thread)

    def check_updates(self, force: bool = False, why: str = "", launch: bool = False):
        """Look for a newer release on a thread (see updates.py). Without `force` only
        if the box is ticked, and at most every hour. `why`: the click that asked,
        for Network activity (none: the app's own timer). `launch`: the check as the
        app starts, whatever the hour; what it finds installs itself (_can_auto)."""
        mw = self.mw
        if not force and not mw.cfg.update_check:
            return

        due = force or launch or time.time() - mw.cfg.update_checked >= updates.EVERY_S
        if launch:
            self._auto = True
            why = why or "Update check as the app starts"
        why = why or "Automatic update check (at most every hour)"
        netlog.cause(updates.FEATURE, why)
        netlog.cause(watchaddon.FEATURE, f"{why}: Onion Watch add-on")

        def run():
            try:
                rel, err = updates.check(mw.cfg, force=force, launch=launch), ""
            except Exception as e:  # noqa: BLE001 - offline etc.
                rel, err = None, errors.plain(e)
            busy.emit(mw.bridge.update, rel, err, force, owner=mw)
            if not due:   # the Onion Watch add-on next, once it's installed (else nothing asked)
                return worker.SKIP
            offer = watchaddon.check_update()
            return worker.SKIP if offer is None else offer
        # (nothing waits on the add-on's answer)
        worker.run(run, mw.bridge.watch_update, "update-check", error=worker.SKIP,
                   owner=mw)

    def _on_update(self, rel, err: str, asked: bool):
        mw = self.mw
        mw._save_later()   # update_checked
        auto = self._auto and not asked
        if updates.recheck_s > 0:   # the newest is still settling: offer it once it has
            QTimer.singleShot(round(updates.recheck_s * 1000), mw, self.check_updates)
        else:   # (the start's check isn't over until then)
            self._auto = False
        busy = self._downloading or self._update_file is not None
        if rel is not None and not busy:
            if self.release is None or self.release.version != rel.version:
                self._update_err, self._update_fails = "", 0   # a new version: a fresh start
            self.release = rel
            self._show_update_state()
            if mw.tray is not None and not mw.isVisible():
                mw.tray.showMessage(
                    "Onion Board", _("Important fix: {fix}", fix=rel.urgent) if rel.urgent
                    else _("Version {version} is out.", version=rel.version),
                    QSystemTrayIcon.MessageIcon.Warning if rel.urgent
                    else QSystemTrayIcon.MessageIcon.Information,
                    8000)
            mw.alertctl._show_urgent()
            if auto and self._can_auto(rel):
                self._auto = False
                self.download_update(auto=True)
        mw.update_done.emit(rel, err)   # for the Settings window's "Check now"
        if asked and rel is not None:
            self.show_update()

    def update_at_start(self) -> bool:
        """As the app starts, behind the loading screen (splash): is a newer version
        out? Then download it there, the percentage under Bun, and start its installer.
        True when the installer was started: the app closes instead of opening, and the
        installer opens the new version ("Updated to X" on its loading screen). Waits
        START_CHECK_S at most for GitHub's answer, and gives up on a download that
        stops moving for STALL_S; anything else (nothing new, offline, unticked, from
        source) opens the app as usual, and the check's answer goes to _on_update."""
        mw = self.mw
        cfg = mw.cfg
        if not (cfg.update_check and cfg.update_auto and updates.can_install()
                and net.allowed(updates.FEATURE)):
            return False
        from soundboard.ui import splash
        netlog.cause(updates.FEATURE, "Update check as the app starts")
        splash.set_status(_("Checking for updates…"))
        got: dict = {}

        def check():
            try:
                got["rel"] = updates.check(cfg, launch=True)
            except Exception as e:  # noqa: BLE001 - offline etc.: open as usual
                got["err"] = errors.plain(e)
        end = time.monotonic() + START_CHECK_S
        if not self._wait(check, lambda: time.monotonic() > end, "update-start-check"):
            splash.set_status()
            return False   # GitHub is slow: the check after the window is up asks again
        self.start_checked = True
        rel = got.get("rel")
        if rel is None or not self._can_auto(rel):
            splash.set_status()
            # nothing new, or one to offer on the card; one still settling is asked
            # for again (_on_update) and installs itself in the window then
            self._auto = rel is None
            QTimer.singleShot(0, mw, lambda: self._on_update(rel, "", False))
            return False
        usage.maybe_send(cfg, event=usage.update_event(rel.version))
        netlog.cause(updates.FEATURE,
                     f"Installing Onion Board {rel.version} by itself (found as the app started)")
        text = _("Updating to {version}…", version=rel.version)
        splash.set_status(text, 0.0)
        moved = [time.monotonic()]

        def progress(done, total):
            moved[0] = time.monotonic()
            if total:
                splash.set_status(_("Updating to {version}… {pct}%", version=rel.version,
                                    pct=min(done * 100 // total, 100)), done / total)

        def fetch():
            try:
                got["path"] = updates.download(
                    rel, progress, lambda: time.monotonic() - moved[0] > STALL_S)
            except Exception as e:  # noqa: BLE001 - open as usual, offered on the card
                log.info("the update at start didn't download: %s", e)
        self._wait(fetch, lambda: False, "update-start-download")
        path = got.get("path")
        if path is None:
            splash.set_status()
            QTimer.singleShot(0, mw, lambda: self._on_update(rel, "", False))
            return False
        splash.set_status(_("Installing Onion Board {version}…", version=rel.version), 1.0)
        self.release, self._update_file = rel, path
        cfg.update_auto_tried = rel.version   # once: a failed one waits for a click
        usage.used("update-auto")
        cfg.update_pending = rel.version
        cfg.save()
        # before it starts: the installer can close the app before start_install is back
        exitwatch.closed_by_windows()
        failed = []

        def start():
            try:
                updates.start_install(path)
            except Exception as e:  # noqa: BLE001 - the app opens with the card instead
                failed.append(e)
        # on a thread, the loading screen moving: Windows checks a freshly downloaded
        # installer before it runs it, which can take a while
        self._wait(start, lambda: False, "update-start-install")
        if failed:
            log.warning("couldn't start the update installer: %s", failed[0])
            exitwatch.staying()
            cfg.update_pending = ""
            cfg.save()
            splash.set_status()
            QTimer.singleShot(0, mw, lambda: self._on_update(rel, "", False))
            return False
        log.info("installing %s as the app starts", rel.version)
        return True

    @staticmethod
    def _wait(fn, give_up, name: str) -> bool:
        """Run `fn` on a thread, keeping the loading screen moving and the control API
        answering (Windows' own loading screen handles no events: remote.answer_waiting),
        until it's done (True) or `give_up()` (False; the thread is left to finish on
        its own)."""
        import threading

        from soundboard.ui import splash
        t = threading.Thread(target=fn, daemon=True, name=name)
        t.start()
        while t.is_alive():
            if give_up():
                return False
            splash.pump()
            remote.answer_waiting()
            t.join(0.03)
        return True

    def _can_auto(self, rel) -> bool:
        """Install `rel` by itself: ticked in Settings > Updates, an installed copy (not
        from source), and not a version that already tried (and so didn't work)."""
        cfg = self.mw.cfg
        return (cfg.update_auto and cfg.update_check and updates.can_install()
                and bool(rel.asset_url) and rel.version != cfg.update_auto_tried
                and net.allowed(updates.FEATURE))

    def _on_watch_update(self, offer):
        """A newer Onion Watch (check_updates): its Triggers tab offers it, and an
        urgent one gets the banner too, on that tab only (_urgent_now)."""
        mw = self.mw
        mw.triggers.offer_update(offer)
        if offer.urgent:
            mw.watch_offer = offer
            mw.alertctl._show_urgent()

    def show_update(self):
        """The update pill was clicked: what's new, and what can be done about it."""
        mw = self.mw
        if self._update_file is not None:
            self.install_update()
            return
        rel = self.release
        if rel is None or self._downloading:
            return
        from soundboard import __version__
        box = QMessageBox(QMessageBox.Icon.Warning if rel.urgent else QMessageBox.Icon.Information,
                          _("Important fix available") if rel.urgent else _("Update available"),
                          _("Onion Board {version} is out (you have {current}).",
                            version=rel.version, current=__version__),
                          QMessageBox.StandardButton.NoButton, mw)
        info = (_("<p><b>Important fix:</b> {fix}</p>", fix=html.escape(rel.urgent))
                if rel.urgent else "")
        info += html.escape(rel.notes).replace("\n", "<br>") if rel.notes else ""
        installable = updates.can_install() and bool(rel.asset_url)
        if installable:
            info += _("<p>Update now downloads it in the background (about 180 MB); you "
                      "choose when the app restarts to install it. Your sounds and "
                      "settings stay as they are.</p>")
        elif not updates.can_install():
            info += _("<p>This copy runs from source: update it with <code>git pull</code>.</p>")
        if info:
            box.setInformativeText(f"<p>{info}</p>")
        get = box.addButton(_("Update now") if installable else _("Open the download page"),
                            QMessageBox.ButtonRole.AcceptRole)
        page = (box.addButton(_("Release page"), QMessageBox.ButtonRole.HelpRole)
                if installable else None)
        # an urgent fix can't be skipped for good, only put off
        skip = (None if rel.urgent
                else box.addButton(_("Skip this version"), QMessageBox.ButtonRole.DestructiveRole))
        box.addButton(_("Later"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        free_dialog(box)
        if clicked is get and installable:
            self.download_update()
        elif clicked is get or (page is not None and clicked is page):
            QDesktopServices.openUrl(QUrl(rel.url))
        elif skip is not None and clicked is skip:
            mw.set_option("update_skip", rel.version)
            self.release = None
            self._show_update_state()

    # ---- Onion Board's own update: one state, shown on the card, the urgent bar and
    # in Settings > Updates in the same words
    def _update_pct(self) -> int:
        done, total = self._update_got
        return min(done * 100 // total, 100) if total else 0

    def _update_words(self) -> tuple[str, str, str, str]:
        """(state, title, hint, tip) for the update as it is now; state "" when
        there's none."""
        rel = self.release
        if rel is None:
            return "", "", "", ""
        if self._downloading:
            done, total = self._update_got
            mb = 1024 * 1024
            hint = (_("{done} of {total} MB", done=done // mb, total=max(1, round(total / mb)))
                    if total else _("{done} MB", done=done // mb))
            return ("downloading", _("Downloading {pct}%", pct=self._update_pct()), hint,
                    _("Downloading Onion Board {version}: click to see how far it is, "
                      "or to cancel.", version=rel.version))
        if self._update_err:
            return ("failed", _("Couldn't update"), _("Click to try again"),
                    _("Updating to Onion Board {version} didn't work: {rstrip}.",
                      version=rel.version, rstrip=self._update_err.rstrip(".")))
        if self._update_file is not None:
            return ("ready", _("Restart to update"), "",
                    _("Onion Board {version} is downloaded, click to install it",
                      version=rel.version))
        return ("available", _("Update to {version}", version=rel.version), "",
                _("Onion Board {version} is out, click for details", version=rel.version))

    def update_status(self) -> str:
        """The update's state in one line (Settings > Updates): the card's words."""
        state, title, hint, tip = self._update_words()
        if state == "failed":
            return tip   # (with the reason)
        return " · ".join(filter(None, (title, hint)))

    def _show_update_state(self):
        """The card (and the urgent bar, Settings, a Downloading box) say where the
        update is."""
        mw = self.mw
        state, title, hint, tip = self._update_words()
        if not state:
            mw.btn_update.hide()
        else:
            mw.btn_update.set_state(state, title, hint, tip,
                                      pct=self._update_pct() if state == "downloading" else None,
                                      copy=state == "failed" and self._update_fails >= 2)
            mw.btn_update.show()
        box = self._update_box
        if box is not None and qt_valid(box):
            box.setText(self._update_box_text())
        mw.alertctl._show_urgent()
        mw.update_state.emit()

    def _update_clicked(self):
        """The update card: the next step from where it is."""
        if self._downloading:
            self._update_info()
        elif self._update_err:
            self.download_update()   # "Couldn't update, try again"
        else:
            self.show_update()

    def _update_box_text(self) -> str:
        rel = self.release
        done, total = self._update_got
        mb = 1024 * 1024
        if total:
            return _("Downloading Onion Board {version}: {done} of {total} MB ({pct}%).",
                     version=rel.version if rel else "", done=done // mb,
                     total=max(1, round(total / mb)), pct=self._update_pct())
        return _("Downloading Onion Board {version}: {done} MB so far.",
                 version=rel.version if rel else "", done=done // mb)

    def _update_info(self):
        """Clicked while it downloads: how far it is, and a way to stop it."""
        mw = self.mw
        if self._update_box is not None or self.release is None:
            return   # (never a second one)
        box = QMessageBox(QMessageBox.Icon.Information, _("Downloading the update"),
                          self._update_box_text(), QMessageBox.StandardButton.NoButton, mw)
        box.setInformativeText(_("You can keep using Onion Board meanwhile. When it's done, "
                                 "the button says Restart to update."))
        stop = box.addButton(_("Cancel download"), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(_("Keep going"), QMessageBox.ButtonRole.RejectRole)
        self._update_box = box
        box.exec()
        clicked = box.clickedButton()
        self._update_box = None
        free_dialog(box)
        if clicked is stop and self._downloading:
            self.cancel_update()

    def cancel_update(self):
        """Stop the download (updates.download checks between chunks)."""
        if self._downloading:
            self._update_cancel = True

    def _copy_update_error(self):
        """Copy error: what went wrong, where, for the user to send to the developer."""
        mw = self.mw
        usage.used("update-copy-error")
        QApplication.clipboard().setText(self._update_detail or self._update_err)
        mw.toast(_("Error details copied: paste them into a message to the developer."),
                   "ok")

    def _update_report(self, rel, err: str, trace: str = "", step: str = "download") -> str:
        """Copy error's text: everything needed to find the cause, nothing private
        beyond what the error itself says."""
        import platform
        from datetime import UTC, datetime

        from soundboard import __version__
        done, total = self._update_got
        lines = [
            f"Onion Board update failed ({step}), try {self._update_fails + 1}",
            f"From {__version__} to {rel.version}",
            f"Windows: {platform.platform()}  frozen: {bool(getattr(sys, 'frozen', False))}",
            f"Time (UTC): {datetime.now(UTC):%Y-%m-%d %H:%M:%S}",
            f"URL: {rel.asset_url}",
            f"File: {updates.installer_path(rel)}",
            f"Got: {done} of {total or rel.size or '?'} bytes",
            f"Error: {err}",
        ]
        if trace:
            lines += ["", trace.strip()]
        return "\n".join(lines)

    def download_update(self, auto: bool = False):
        """Fetch the new version's installer on a thread (updates.download). `auto`:
        found as the app started, it installs itself once it's here (_on_update_ready)."""
        mw = self.mw
        rel = self.release
        if rel is None or self._downloading:
            return
        if not net.allowed(updates.FEATURE):   # switched off since it was found
            mw.toast(html.escape(net.off_message(updates.FEATURE)), "warn")
            return
        self._auto_install = auto
        if auto:
            mw.toast(_("Onion Board {version} is out: downloading it now. The app restarts "
                       "by itself to install it when it's done.", version=rel.version),
                     "ok", 8000)
        self._downloading = True
        self._update_cancel = False
        self._update_err = ""
        self._update_got = (0, rel.size or 0)
        netlog.cause(updates.FEATURE,
                     f"Installing Onion Board {rel.version} by itself (found as the app started)"
                     if auto else f"You clicked to download Onion Board {rel.version}")
        usage.maybe_send(mw.cfg, event=usage.update_event(rel.version))
        self._show_update_state()
        last = [-1]

        def progress(done, total):
            pct = min(done * 100 // total, 100) if total else done // (1024 * 1024)
            if pct != last[0]:
                last[0] = pct
                mw.bridge.update_progress.emit(done, total)

        def failed(e):   # never leave the card stuck
            import traceback
            self._update_detail_next = "".join(traceback.format_exception(e, limit=8))
            return None, errors.plain(e)
        self._update_detail_next = ""
        worker.run(lambda: (updates.download(rel, progress,
                                             lambda: mw._shut_down or self._update_cancel),
                            ""),
                   mw.bridge.update_ready, "update-download", error=failed, owner=mw)

    def _on_update_progress(self, done, total):
        mw = self.mw
        if self._downloading and qt_valid(mw):
            self._update_got = (int(done), int(total or 0))
            self._show_update_state()

    def _on_update_ready(self, path, err: str):
        mw = self.mw
        if not qt_valid(mw) or mw._shut_down:
            return
        self._downloading = False
        auto, self._auto_install = self._auto_install, False
        box, self._update_box = self._update_box, None
        if box is not None and qt_valid(box):
            box.reject()   # the Downloading box: done, one way or the other
        rel = self.release
        if rel is None:
            return
        if path is None and self._update_cancel:   # Cancel: back to "Update to …"
            self._update_cancel = False
            usage.used("update-cancelled")
            self._update_got = (0, 0)
            self._show_update_state()
            return
        if path is None:
            self._update_detail = self._update_report(rel, err,
                                                      getattr(self, "_update_detail_next", ""))
            self._update_fails += 1
            self._update_err = errors.plain(err) or _("the download failed")
            usage.used("update-download-failed")
            self._show_update_state()
            url = rel.url
            mw.tell(_("Couldn't update"),
                      _("Onion Board {version} couldn't be downloaded: {rstrip}.",
                        version=rel.version, rstrip=errors.plain(err).rstrip('.')), "error",
                      action=(_("Open the download page"),
                              lambda: QDesktopServices.openUrl(QUrl(url))))
            return
        self._update_file = path
        self._update_err, self._update_fails = "", 0
        self._show_update_state()
        if mw.tray is not None and not mw.isVisible():
            # hidden in the tray, maybe mid-game: don't pop a question, just say so
            mw.tray.showMessage("Onion Board", _("Version {version} is ready to install: "
                                                   "open Onion Board and click Restart to "
                                                   "update.", version=rel.version),
                                  QSystemTrayIcon.MessageIcon.Information, 8000)
            return
        if QApplication.activeModalWidget() is not None:
            return   # something else is open: the card says Restart to update
        # installing itself: not over a sound that's playing (then it asks, as always)
        self.install_update(ask=not (auto and not mw.engine.playing()))

    def install_update(self, ask: bool = True):
        """Ask (unless not `ask`: installing by itself, _on_update_ready), then close
        the app and let the downloaded installer replace it (it opens the app again
        when it's done)."""
        mw = self.mw
        rel, path = self.release, self._update_file
        if rel is None or path is None:
            return
        if not ask:
            log.info("installing %s by itself", rel.version)
            mw.cfg.update_auto_tried = rel.version   # once: a failed one waits for a click
            usage.used("update-auto")
            self._start_install(rel, path)
            return
        box = QMessageBox(QMessageBox.Icon.Question, _("Install the update"),
                          _("Onion Board {version} is ready. Restart now to install it?",
                            version=rel.version),
                          QMessageBox.StandardButton.NoButton, mw)
        box.setInformativeText(_("Onion Board closes, installs the new version and opens again "
                                 "by itself, usually within a minute. Sounds that are playing "
                                 "stop."))
        now = box.addButton(_("Restart now"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(_("Later"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        free_dialog(box)
        if clicked is not now:
            usage.used("update-later")
            return
        self._start_install(rel, path)

    def _start_install(self, rel, path: Path):
        mw = self.mw
        if self._installing:
            return
        if not path.is_file():   # removed meanwhile: fetch it again
            self._update_file = None
            self.download_update()
            return
        mw.cfg.update_pending = rel.version
        mw.cfg.save()
        # before it starts: the installer closes the app as soon as it runs, which can be
        # before start_install is back. Ended that way, it's no crash or freeze to count
        exitwatch.closed_by_windows()
        self._installing = True

        def failed(e):
            import traceback
            return rel, e, traceback.format_exc(limit=8)
        # on a thread: Windows checks a freshly downloaded installer before it runs it,
        # and the window stayed frozen meanwhile (for good, when that check hung)
        worker.run(lambda: (rel, updates.start_install(path), ""), mw.bridge.update_started,
                   "update-start-install", error=failed, owner=mw)

    def _on_update_started(self, rel, e, trace: str):
        """start_install's answer: started (None), so the app quits; else what it raised."""
        mw = self.mw
        self._installing = False
        if e is None:
            mw.quit_app()
            return
        log.warning("couldn't start the update installer: %s", e)
        exitwatch.staying()
        mw.cfg.update_pending = ""
        mw._save_later()
        self._update_detail = self._update_report(rel, errors.plain(e), trace, "install")
        self._update_fails += 1
        self._update_err = errors.plain(e)
        usage.used("update-install-failed")
        self._show_update_state()   # "Couldn't update", click to try again
        mw.tell(_("Couldn't update"),
                  _("The installer couldn't be started ({e}). You can download it "
                    "from the release page instead.", e=errors.plain(e)), "error",
                  action=(_("Open the download page"),
                          lambda: QDesktopServices.openUrl(QUrl(updates.RELEASES))))

    def after_update(self):
        """At start: remove downloaded installers and, the first time after an update
        was started, say whether it worked; then What's new, once per version."""
        mw = self.mw
        pending, mw.cfg.update_pending = mw.cfg.update_pending, ""
        updates.cleanup()
        from soundboard import __version__
        if pending:
            mw._save_later()
            if not updates.finished(pending):
                self._update_failed(pending)
                return
            log.info("updated to %s", __version__)
        self.whats_new(updated=bool(pending))

    def show_whats_new(self):
        """The header's version, clicked: the newest release's notes, any time."""
        mw = self.mw
        from soundboard.ui import whatsnew
        dlg = whatsnew.WhatsNewDialog(mw, [whatsnew.notes()[0]])
        dlg.exec()
        page = dlg.page
        free_dialog(dlg)
        if page:
            mw.setctl.open_settings(page)

    def whats_new(self, updated: bool = False):
        """What's new in this version (ui/whatsnew.py), if they haven't seen it: once,
        with a button to the settings it's about. Waits while the window is in the tray
        or the setup guide is about to run. `updated`: the app updated itself."""
        mw = self.mw
        from soundboard import __version__
        from soundboard.ui import whatsnew
        if not mw.cfg.setup_done:   # the guide comes first; this waits for next time
            return
        if not mw.isVisible():   # started with Windows, in the tray: when it's opened
            self._whats_new_later = updated
            return
        notes = whatsnew.unseen(mw.cfg.whats_new_seen)
        if updates.newer(__version__, mw.cfg.whats_new_seen or "0"):
            mw.cfg.whats_new_seen = __version__
            mw._save_later()
        if notes:
            dlg = whatsnew.WhatsNewDialog(mw, notes, updated)
            usage.used("whats-new-shown")
            dlg.exec()
            page = dlg.page
            free_dialog(dlg)
            if page:
                usage.used("whats-new-page")
                mw.setctl.open_settings(page)
            return
        if not updated:
            return
        url = f"https://github.com/{updates.REPO}/releases/tag/v{__version__}"
        mw.toast(_("Onion Board is up to date: version {version}.", version=__version__),
                   "ok", 10000,
                   action=(_("What's new"), lambda: QDesktopServices.openUrl(QUrl(url))))

    def _update_failed(self, pending: str):
        mw = self.mw
        from soundboard import __version__
        log.warning("the update to %s didn't finish (still %s)", pending, __version__)
        usage.used("update-didnt-finish")
        box = QMessageBox(QMessageBox.Icon.Warning, _("The update didn't finish"),
                          _("Onion Board {pending} wasn't installed; this is still {version}. "
                            "You can download it from its page and run it yourself.",
                            pending=pending, version=__version__),
                          QMessageBox.StandardButton.NoButton, mw)
        page = box.addButton(_("Open the download page"), QMessageBox.ButtonRole.AcceptRole)
        logb = (box.addButton(_("Show the install log"), QMessageBox.ButtonRole.HelpRole)
                if updates.INSTALL_LOG.is_file() else None)
        box.addButton(_("Close"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        free_dialog(box)
        if clicked is page:
            QDesktopServices.openUrl(QUrl(updates.RELEASES))
        elif logb is not None and clicked is logb:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(updates.INSTALL_LOG)))
