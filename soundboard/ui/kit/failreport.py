""""Didn't work? Send us a report": the button under a mic failure (the setup guide's mic
test, the mic effect's set-up), so people tell us before they give up.

A click shows, in the button's place, what the feedback form will be filled with
(Windows' version, the mic's name, direct or cable, a short error code: feedback.py
micfail_url); "Open the form" opens it in their browser. Nothing is sent unless they
submit the form there."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from soundboard import __version__
from soundboard.core import feedback
from soundboard.i18n import _
from soundboard.ui.kit import busy, icons
from soundboard.ui.kit.panellabels import hint_label


def mode_of(route: str) -> str:
    """The form's `mode`: "cable" on the virtual cable, else "direct" (straight into the
    mic, the default, also before it's picked)."""
    return "cable" if route == "cable" else "direct"


class FailReport(QWidget):
    """The report button, and in its place after a click: what goes in the form, then
    Open the form / Cancel. `details()` gives {"mic", "mode", "err"} at click time.
    Hidden until `set_failed(True)`; `set_failed(False)` hides it and folds it back."""

    def __init__(self, details: Callable[[], dict], parent: QWidget | None = None):
        super().__init__(parent)
        self._details = details
        self._sent: dict = {}
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        self.what = hint_label("")
        self.what.setTextFormat(Qt.TextFormat.PlainText)   # (a mic's name is never markup)
        self.what.hide()
        v.addWidget(self.what)
        # one row: the report button, or (after its click) Open the form + Cancel. Quiet,
        # as the Setup tab's mic box's other buttons: a plain one there is the box's colour
        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_report = QPushButton(_("Didn't work? Send us a report"))
        icons.set_icon(self.btn_report, "speech")
        self.btn_report.clicked.connect(self.preview)
        self.btn_open = QPushButton(_("Open the form"))
        icons.set_icon(self.btn_open, "browser")
        self.btn_open.clicked.connect(self.open_form)
        self.btn_cancel = QPushButton(_("Cancel"))
        self.btn_cancel.clicked.connect(self.fold)
        for b in (self.btn_report, self.btn_open, self.btn_cancel):
            b.setProperty("quiet", True)
            b.setAutoDefault(False)   # (Enter stays the guide's Next)
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        self.btn_open.hide()
        self.btn_cancel.hide()
        self.hide()

    def set_failed(self, failed: bool):
        if not failed:
            self.fold()
        self.setVisible(failed)

    def preview(self):
        """What the form gets, said where the button was."""
        d = self._sent = dict(self._details())
        win = feedback.windows_version()
        major, _sep, build = win.partition("-")
        parts = [_("Windows {major} (build {build})", major=major, build=build) if win
                 else "",
                 _("mic: {name}", name=d.get("mic")) if d.get("mic") else _("no mic"),
                 _("straight into my mic") if d.get("mode") == "direct"
                 else _("virtual cable"),
                 _("error: {code}", code=d.get("err", ""))]
        self.what.setText(_("The form opens with: {details}. Nothing is sent unless you "
                            "submit it.", details=" · ".join(p for p in parts if p)))
        self.what.show()
        self.btn_open.show()
        self.btn_cancel.show()
        self.btn_open.setFocus()   # (before the clicked button hides: focus stays here)
        self.btn_report.hide()

    def fold(self):
        self.what.hide()
        self.btn_report.show()
        if self.btn_open.hasFocus() or self.btn_cancel.hasFocus():
            self.btn_report.setFocus()
        self.btn_open.hide()
        self.btn_cancel.hide()

    def url(self) -> str:
        d = self._sent or self._details()
        return feedback.micfail_url(__version__, mic=d.get("mic") or "",
                                    mode=d.get("mode") or "direct", err=d.get("err") or "")

    def open_form(self):
        if busy.open_url(self.url(), window=self.window(),
                         failed=_("Couldn't open your browser. The page is")):
            self.fold()
