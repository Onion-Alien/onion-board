"""Remote control in the main window: the local control API (soundboard.remote) started and
stopped to match the settings, and the phone-remote add-ons (soundboard.modules, e.g. Onion
Pocket): starting them, loading a newly installed or updated one in place of the old,
removing one, and stopping them all when the app quits.

MainWindow makes one ``RemoteAccess`` (``MainWindow.remctl``); everything here runs on the
UI thread."""
from __future__ import annotations

import html
import logging
import sys
from typing import TYPE_CHECKING

from soundboard import errors, remote, theme
from soundboard.i18n import _
from soundboard.ui.controller import Controller

if TYPE_CHECKING:
    from soundboard.ui.mainwindow import MainWindow

log = logging.getLogger(__name__)


class RemoteAccess(Controller):
    """The control API and phone-remote add-ons of one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        self.remote_addons: list = []   # [(ModuleInfo, add-on or None)], once loaded

    def apply_remote(self) -> str:
        """Start / stop the local control API to match the settings; "" or an error."""
        mw = self.mw
        err = remote.apply(mw, mw.remote)
        if err:
            mw.say(_("<span style='color:{status}'>Remote control is off: "
                       "{err}.</span>",
                       status=theme.status('warn'), err=html.escape(err)), "warn")
        return err

    def _load_remote_addons(self) -> list:
        """[(ModuleInfo, add-on or None)] for every "remote" add-on (soundboard.modules),
        e.g. Onion Pocket. One that fails is noted on its info (and the log;
        Settings → Remote leaves it out) and never stops the app."""
        from soundboard import modules
        return [(info, self._start_remote_addon(info))
                for info in modules.discover() if info.kind == "remote"]

    def _start_remote_addon(self, info):
        """The add-on's object, or None (the reason noted on `info`)."""
        mw = self.mw
        from soundboard import modules
        from soundboard.ui.remotehost import RemoteHost
        if info.error:
            return None
        try:
            return modules.load_package(info).create(RemoteHost(mw, info.id))
        except Exception as e:  # noqa: BLE001 - a bad add-on can't stop the app
            log.exception("remote add-on %s didn't start", info.id)
            info.error = str(e) if isinstance(e, modules.ModuleError) \
                else _("failed to start: {error}", error=errors.plain(e))
            return None

    def load_remote_addon(self, info):
        """Start a remote add-on installed while the app runs (Settings → Remote's
        *Get Onion Pocket*, or its *Update* button), in place of any copy of it. A
        running copy is stopped first (its server lets go of the port) and its package
        forgotten, so the new version's code loads; its settings in
        Config.remote_addons are the board's and stay as they are. If the new one
        doesn't start, the old one is started again and stays. The add-on's object,
        or None."""
        from soundboard import modules
        old = next(((i, a) for i, a in self.remote_addons if i.id == info.id), None)
        saved = {}
        if old is not None and old[1] is not None:
            try:
                old[1].stop()
            except Exception:  # noqa: BLE001
                log.exception("remote add-on %s didn't stop cleanly", info.id)
            pkg = old[0].package
            saved = {n: m for n, m in sys.modules.items()
                     if pkg and (n == pkg or n.startswith(pkg + "."))}
            modules._forget(pkg)
        addon = self._start_remote_addon(info)
        if addon is None and saved and old is not None:   # (saved: only with an old one)
            log.warning("remote add-on %s %s didn't start (%s): keeping %s",
                        info.id, info.version, info.error, old[0].version)
            if info.package:
                modules._forget(info.package)
            sys.modules.update(saved)
            try:
                restart = getattr(old[1], "apply", None)
                if callable(restart):
                    restart()
            except Exception:  # noqa: BLE001
                log.exception("remote add-on %s didn't start again", info.id)
            return None
        self.remote_addons = [(i, a) for i, a in self.remote_addons if i.id != info.id]
        self.remote_addons.append((info, addon))
        return addon

    def remove_remote_addon(self, info, base=None):
        """Uninstall a remote add-on (Settings' *Remove Onion Pocket*): the running
        copy is stopped (its server lets go of the port), its folder in `base` (the
        modules folder in %APPDATA%) deleted and its package forgotten. Its settings
        in Config.remote_addons stay, for when it's got again. If the folder can't be
        deleted, it's started again. Raises modules.ModuleError."""
        from soundboard import modules
        cur = next(((i, a) for i, a in self.remote_addons if i.id == info.id), None)
        if cur is not None and cur[1] is not None:
            try:
                cur[1].stop()
            except Exception:  # noqa: BLE001 - it's being removed anyway
                log.exception("remote add-on %s didn't stop cleanly", info.id)
        try:
            modules.uninstall(info.id, base)
        except modules.ModuleError:
            if cur is not None and cur[1] is not None:
                restart = getattr(cur[1], "apply", None)
                try:
                    if callable(restart):
                        restart()
                except Exception:  # noqa: BLE001
                    log.exception("remote add-on %s didn't start again", info.id)
            raise
        if info.package:
            modules._forget(info.package)
        self.remote_addons = [(i, a) for i, a in self.remote_addons if i.id != info.id]
        log.info("remote add-on %s %s was removed", info.id, info.version)

    def _stop_remote_addons(self):
        for info, addon in self.remote_addons:
            if addon is not None:
                try:
                    addon.stop()
                except Exception:  # noqa: BLE001
                    log.exception("remote add-on %s didn't stop cleanly", info.id)
