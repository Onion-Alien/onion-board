"""The two "are you sure?" steps before every sound on the board is deleted.

Right-clicking the All tab opens this. The first step's button only moves on to the second,
and Cancel stays the default on both, so Enter or a stray click never deletes anything."""
from __future__ import annotations

import time

from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget

from soundboard.core import trash
from soundboard.i18n import _, ngettext
from soundboard.ui.kit import fit
from soundboard.ui.kit.modalframe import ModalFrame
from soundboard.ui.kit.quietbox import badge

ARM_S = 0.5   # the second button ignores clicks this long, so a double-click can't answer both


class DeleteAllDialog(QDialog):
    """Accepted only after the danger button on both steps. Cancel, Esc or a click outside
    says no."""

    def __init__(self, count: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("deleteall")
        self.setWindowTitle(_("Delete all sounds"))
        self.setFixedWidth(460)
        fit.watch(self)
        self.count = count
        self.step = 1
        self._armed_at = 0.0

        self.frame = ModalFrame("", "", mascot="bun", close=False)
        self.title = self.frame.heading
        self.body = self.frame.subtitle
        self.pic = self.frame.mascot
        self.btn_yes = self.frame.add_button(_("Delete all sounds"))
        self.btn_yes.setObjectName("danger")
        self.btn_yes.setAutoDefault(False)
        self.btn_yes.clicked.connect(self._yes)
        self.btn_cancel = self.frame.add_button(_("Cancel"))
        self.btn_cancel.setDefault(True)
        self.btn_cancel.clicked.connect(self.reject)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.frame)
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
        self.body.show()
        assert self.pic is not None
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
