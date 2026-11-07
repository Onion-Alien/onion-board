"""The question on the first press of the window's ✕: stay in the tray or really close.

Asked once, so nobody finds the app still running a day later without having been told
it would (MainWindow's closeEvent). The answer is the Close to tray setting in Settings."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from soundboard.i18n import _
from soundboard.ui.kit import fit, panel

CANCELLED, KEEP, QUIT = 0, 1, 2   # the `finished` signal's answer; Esc and the ✕ cancel


class CloseAskDialog(QDialog):
    KEEP_OPEN = True   # a click outside doesn't answer it (modals.closes_on_click_outside)

    def __init__(self, parent=None):
        super().__init__(parent)
        heading = _("Keep Onion Board running?")
        self.setWindowTitle(heading)
        self.setMinimumWidth(420)
        self.setMaximumWidth(620)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(12)
        title = QLabel(heading)
        title.setObjectName("helptitle")
        title.setWordWrap(True)
        v.addWidget(title)
        v.addWidget(panel.hint_label(
            _("It can stay in the tray, by the clock, so your hotkeys and sounds keep working. "
              "To quit from there, right-click its icon.")))
        v.addWidget(panel.hint_label(
            _("We won't ask again. You can change this in Settings.")))
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        self.keep_btn = QPushButton(_("Keep running"))
        self.keep_btn.setObjectName("primary")
        self.keep_btn.setDefault(True)
        self.keep_btn.clicked.connect(lambda: self.done(KEEP))
        self.quit_btn = QPushButton(_("Close fully"))
        self.quit_btn.clicked.connect(lambda: self.done(QUIT))
        row.addWidget(self.keep_btn)
        row.addWidget(self.quit_btn)
        v.addLayout(row)
        fit.watch(self)   # grows to fit long translations (ui/kit/fit.py)
