"""The question on the first press of the window's ✕: stay in the tray or really close.

Asked once, so nobody finds the app still running a day later without having been told
it would (MainWindow's closeEvent). The answer is the Close to tray setting in Settings.
A small modal on the shared frame (kit/modalframe.py), Bun in its header."""
from __future__ import annotations

from soundboard.i18n import _
from soundboard.ui.kit.modalframe import ModalDialog

CANCELLED, KEEP, QUIT = 0, 1, 2   # the `finished` signal's answer; Esc and the ✕ cancel


class CloseAskDialog(ModalDialog):
    KEEP_OPEN = True   # a click outside doesn't answer it (modals.closes_on_click_outside)

    def __init__(self, parent=None):
        super().__init__(parent, _("Keep Onion Board running?"), mascot="bun")
        f = self.frame
        f.add_text(_("It can stay in the tray, by the clock, so your hotkeys and sounds keep "
                     "working. To quit from there, right-click its icon."))
        f.add_text(_("We won't ask again. You can change this in Settings.")).setObjectName(
            "muted")
        self.keep_btn = f.add_button(_("Keep running"), primary=True)
        self.keep_btn.clicked.connect(lambda: self.done(KEEP))
        self.quit_btn = f.add_button(_("Close fully"))
        self.quit_btn.clicked.connect(lambda: self.done(QUIT))
        self.focus_first(self.keep_btn)
