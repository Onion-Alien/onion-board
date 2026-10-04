"""Onion Board as the host of a "remote" add-on (soundboard.modules), such as Onion
Pocket (modules/onion-pocket, the pads on your phone): the one interface it talks to,
version REMOTE_API. The add-on's `create(host)` returns an object with `card(parent)`,
its card on Settings → Remote, and `stop()`, called when the app closes.

What the host gives it:

  settings / save()   its own settings, kept in Config.remote_addons[<its id>]: on
                      this PC only, never in a backup (they hold keys)
  actions             every control API action (soundboard.remote.ACTIONS)
  server(actions, page, name)
                      a control API server for other devices on the home network
                      (RemoteControl with lan=True: local peers only, wrong keys
                      locked out) offering `actions`, serving `page` at /
  new_token()         a fresh random key
  warn(text)          a warning on the main window's status line
  card(), button_row(), flash(), icon(), no_wheel()
                      Settings' own look, so the add-on's card matches the rest
"""
from __future__ import annotations

import html
import logging

from soundboard import remote, theme
from soundboard.modules import REMOTE_API

log = logging.getLogger(__name__)


class RemoteHost:
    api_version = REMOTE_API[1]
    name = "Onion Board"
    actions = remote.ACTIONS

    def __init__(self, win, module_id: str):
        """`win` is the MainWindow: cfg, status, and remote.dispatch on it."""
        self.win = win
        self.module_id = module_id
        if not isinstance(win.cfg.remote_addons, dict):
            win.cfg.remote_addons = {}

    @property
    def app_version(self) -> str:
        from soundboard import __version__
        return __version__

    # ------------------------------------------------------------------ settings
    @property
    def settings(self) -> dict:
        d = self.win.cfg.remote_addons.get(self.module_id)
        if not isinstance(d, dict):
            d = self.win.cfg.remote_addons[self.module_id] = {}
        return d

    def save(self):
        self.win.cfg.save()   # now, not later: a new key must outlive a crash

    # ------------------------------------------------------------------ the board
    def dispatch(self, action: str, params: dict):
        return remote.dispatch(self.win, action, params)

    def server(self, actions, page=None, name: str = "remote add-on") -> remote.RemoteControl:
        unknown = set(actions) - set(remote.ACTIONS)
        if unknown:
            raise ValueError(f"no such actions: {', '.join(sorted(unknown))}")
        return remote.RemoteControl(self.dispatch, self.win, actions=actions, page=page,
                                    lan=True, name=name)

    @staticmethod
    def new_token() -> str:
        return remote.new_token()

    def warn(self, text: str):
        self.win.status.setText(f"<span style='color:{theme.status('warn')}'>"
                                f"{html.escape(text)}</span>")

    # ------------------------------------------------------------------ Settings' look
    @staticmethod
    def card(title: str, hint: str = ""):
        from soundboard.settings import SettingsDialog
        return SettingsDialog._card(title, hint)

    @staticmethod
    def button_row():
        from soundboard.settings import _button_row
        return _button_row()

    @staticmethod
    def flash(button, text: str):
        from soundboard.ui import busy
        busy.flash(button, text)

    @staticmethod
    def icon(button, name: str):
        from soundboard.ui import icons
        icons.set_icon(button, name)

    @staticmethod
    def no_wheel(widget):
        from soundboard.wheelguard import no_wheel
        no_wheel(widget)
