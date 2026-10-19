"""The main window's language: offering Windows' language once (when the app isn't in it
yet), turning that down, and switching language.

MainWindow makes one ``LanguageControl`` (``MainWindow.langctl``); everything here runs on
the UI thread."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt

from soundboard import i18n
from soundboard.i18n import _
from soundboard.ui.window.controller import Controller

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

log = logging.getLogger(__name__)

LANG_OFFER_SEEN = "language-offer"   # in Config.tips_seen: the language bar was turned down


class LanguageControl(Controller):
    """The language of one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)

    def _offer_language(self):
        """Windows speaks a language the board has, and no language was ever picked:
        a bar, in that language, offering to switch (until switched or dismissed)."""
        mw = self.mw
        code = i18n.offer()
        if not code or mw.cfg.language or LANG_OFFER_SEEN in mw.cfg.tips_seen:
            return
        name = i18n.name_of(code)
        mw._lang_offered = code
        text, button, hide = i18n.in_language(code, lambda: (
            # the way there in the catalog's own words for the gear, the page and the box
            _("Onion Board is also in {name}. You can change it any time in {where}.",
              name=name, where=" → ".join((_("Settings"), _("Appearance"), _("Language")))),
            _("Switch to {name}", name=name), _("No thanks")))
        # a right-to-left line that starts with "Onion Board" still reads right to left
        mw.lang_bar.set_message("‏" + text if i18n.is_rtl(code) else text)
        mw.lang_btn.setText(button)
        mw.lang_hide.setAccessibleName(hide)
        mw.lang_hide.setToolTip(hide)
        for w in (mw.lang_lbl, mw.lang_btn):   # its own direction (Arabic offered
            w.setLayoutDirection(Qt.LayoutDirection.RightToLeft if i18n.is_rtl(code)
                                 else Qt.LayoutDirection.LeftToRight)
        mw.lang_bar.show()

    def _no_language(self):
        mw = self.mw
        mw.lang_bar.hide()
        if LANG_OFFER_SEEN not in mw.cfg.tips_seen:
            mw.cfg.tips_seen.append(LANG_OFFER_SEEN)
        mw._save_later()

    def switch_language(self, code: str, restart: bool = True):
        """Show the app in language `code` from the next start (now, with `restart`:
        text already on screen can't change language)."""
        mw = self.mw
        if not code:
            return
        mw.cfg.language = code
        mw.lang_bar.hide()
        mw._save_later()
        log.info("language picked: %s", code)
        if restart and code != i18n.current():
            mw.restart_app()
