"""The two "are you sure?" steps before every sound on the board is deleted.

Right-clicking the All tab opens this. Yes on the first step only moves on to the second,
and Cancel stays the default on both, so Enter or a stray click never deletes anything."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from soundboard.core import trash
from soundboard.i18n import _, ngettext
from soundboard.ui.kit import fit
from soundboard.ui.kit.quietbox import badge

ARM_S = 0.5   # the second Yes ignores clicks this long, so a double-click can't answer both


class DeleteAllDialog(QDialog):
    """Accepted only after Yes on both steps. Cancel, Esc or a click outside says no."""

    def __init__(self, count: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("deletealldialog")
        self.setWindowTitle(_("Delete all sounds"))
        self.setFixedWidth(440)
        fit.watch(self)
        self.count = count
        self.step = 1
        self._armed_at = 0.0

        top = QHBoxLayout()
        top.setSpacing(14)
        self.pic = QLabel()
        top.addWidget(self.pic, 0, Qt.AlignmentFlag.AlignTop)
        words = QVBoxLayout()
        words.setSpacing(6)
        self.title = QLabel()
        self.title.setObjectName("helptitle")
        self.title.setWordWrap(True)
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.TextFormat.PlainText)
        words.addWidget(self.title)
        words.addWidget(self.body)
        top.addLayout(words, 1)

        self.btn_yes = QPushButton(_("Yes"))
        self.btn_yes.setObjectName("danger")
        self.btn_yes.setAutoDefault(False)
        self.btn_yes.clicked.connect(self._yes)
        self.btn_cancel = QPushButton(_("Cancel"))
        self.btn_cancel.setDefault(True)
        self.btn_cancel.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.btn_yes)
        row.addWidget(self.btn_cancel)

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(16)
        v.addLayout(top)
        v.addLayout(row)
        self._show_step()

    def _show_step(self) -> None:
        if self.step == 1:
            icon = "warn"
            self.title.setText(_("Are you sure you want to delete all sounds?"))
            self.body.setText(ngettext(
                "This takes your {n} sound off the board, in every category.",
                "This takes all {n} sounds off the board, in every category.",
                self.count, n=self.count))
        else:
            icon = "alert"
            self.title.setText(_("Are you really sure?"))
            self.body.setText(_("Your board will be empty. They wait in Recently deleted for "
                                "{keep_days} days, then they're gone for good.",
                                keep_days=trash.KEEP_DAYS))
        self.pic.setPixmap(badge(icon, "danger_text", self.devicePixelRatioF()))
        self.btn_cancel.setFocus()
        self._fit()

    def _fit(self) -> None:
        """As tall as its words at this width (adjustSize measures at a narrower one)."""
        for label in (self.title, self.body):
            label.ensurePolished()   # the style sheet's title size is in the measure
        self.resize(self.width(), fit.needed_height(self, self.width()))

    def showEvent(self, event) -> None:   # noqa: N802 - Qt API
        self._fit()
        super().showEvent(event)

    def _yes(self) -> None:
        if self.step == 1:
            self.step = 2
            self._armed_at = time.monotonic() + ARM_S
            self._show_step()
        elif time.monotonic() >= self._armed_at:
            self.accept()
