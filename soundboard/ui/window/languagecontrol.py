"""The main window's language: switching it.

MainWindow makes one ``LanguageControl`` (``MainWindow.langctl``); everything here runs on
the UI thread."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from soundboard import i18n
from soundboard.core import achievements
from soundboard.ui.window.controller import Controller

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

log = logging.getLogger(__name__)


class LanguageControl(Controller):
    """The language of one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)

    def switch_language(self, code: str, restart: bool = True):
        """Show the app in language `code` from the next start (now, with `restart`:
        text already on screen can't change language)."""
        mw = self.mw
        if not code:
            return
        if code != mw.cfg.language:
            achievements.bump("lang_switch")   # (Babel)
        mw.cfg.language = code
        mw._save_later()
        log.info("language picked: %s", code)
        if restart and code != i18n.current():
            mw.restart_app()
