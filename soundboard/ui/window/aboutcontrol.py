"""The main window's About menu (the onion's menu: Join the Discord, Send feedback,
Report a problem) and opening those pages.

MainWindow makes one ``AboutControl`` (``MainWindow.aboutctl``); everything here runs on
the UI thread."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint

from soundboard.i18n import _
from soundboard.ui.kit import busy, icons
from soundboard.ui.window.controller import Controller

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow


class AboutControl(Controller):
    """The About menu of one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)

    def _show_about_menu(self):
        # (a foot button is checkable for Settings' "showing" fill: this one never is)
        mw = self.mw
        mw.btn_about.setChecked(False)
        # up from the rail's foot, its edge over the onion's (down, it ran off the window)
        m = mw.about_menu
        self._fill_about_menu()
        edge = 0 if not mw.isRightToLeft() else mw.btn_about.width() - m.sizeHint().width()
        m.popup(mw.btn_about.mapToGlobal(QPoint(edge, -m.sizeHint().height())))

    def _fill_about_menu(self):
        """The onion at the rail's foot: where to talk to us. Only those three: What's new
        is the version under the app's name."""
        mw = self.mw
        from soundboard import __version__
        from soundboard.core import feedback
        m = mw.about_menu
        m.clear()
        icons.set_icon(m.addAction(_("Join the Discord"), lambda: self._open_page(
            feedback.DISCORD_URL)), "speech")
        icons.set_icon(m.addAction(_("Send feedback"), self.ask_feedback), "edit")
        icons.set_icon(m.addAction(_("Report a problem"), lambda: self._open_page(
            feedback.problem_url(__version__))), "warn")

    def ask_feedback(self):
        """*Send feedback*: "What would you improve?" (ui/kit/feedbackdialog.py)."""
        mw = self.mw
        from soundboard.ui.kit import feedbackdialog
        mw.show_from_tray()
        self.feedback_box = feedbackdialog.ask(mw.cfg, mw)

    def _open_page(self, url: str):
        mw = self.mw
        busy.open_url(url, window=mw, failed=_("Couldn't open your browser. The page is"))
