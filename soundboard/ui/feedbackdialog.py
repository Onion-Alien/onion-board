"""*Send feedback*: "What would you improve?" with a few picks and Other, then a thank
you with the feedback form for anyone who wants to say more or get a reply.

The picks go out with the anonymous usage count (usage.improve: names from a fixed
list, and Other's words with anything personal taken out), so they're counted only
when that's on. They go with a one-off random session, never this PC's ID, and the box
says so. The form only opens in the browser, like before (feedback.py)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from soundboard import __version__, feedback, usage
from soundboard.i18n import _
from soundboard.ui import busy, fit, icons


def picks() -> list[tuple[str, str]]:
    """(usage.IMPROVE name, what the box says), in the box's order."""
    return [("sounds", _("More sounds and packs")),
            ("setup", _("Easier to set up")),
            ("voice-chat", _("Others hearing my sounds in games and calls")),
            ("voice-changer", _("The voice changer")),
            ("speed", _("Faster, lighter on my PC")),
            ("looks", _("How it looks")),
            ("bugs", _("Fewer bugs")),
            ("other", _("Something else"))]


def _title(text: str) -> QLabel:
    lab = QLabel(text)
    f = lab.font()
    f.setPointSizeF(f.pointSizeF() * 1.3)
    f.setBold(True)
    lab.setFont(f)
    return lab


class FeedbackDialog(QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        fit.watch(self)   # grows to fit its text (ui/fit.py)
        self.cfg = cfg
        self.sent = False
        self.setWindowTitle(_("Send feedback"))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 14)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._ask_page())
        self.pages.addWidget(self._thanks_page())
        v.addWidget(self.pages)

    # ------------------------------------------------------------------ page 1
    def _ask_page(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(_title(_("What would you improve?")))
        hint = QLabel(_("Tick all that fit."))
        hint.setObjectName("hint")
        v.addWidget(hint)
        self.boxes: dict[str, QCheckBox] = {}
        for key, text in picks():
            box = self.boxes[key] = QCheckBox(text)
            box.toggled.connect(self._changed)
            v.addWidget(box)
        self.other = QLineEdit()
        self.other.setPlaceholderText(_("What else?"))
        self.other.setMaxLength(200)
        self.other.setVisible(False)
        self.other.textChanged.connect(self._changed)
        v.addWidget(self.other)
        row = QHBoxLayout()
        cancel = QPushButton(_("Cancel"))
        cancel.clicked.connect(self.reject)
        self.send_btn = QPushButton(_("Send"))
        self.send_btn.setObjectName("primary")
        self.send_btn.setDefault(True)
        self.send_btn.clicked.connect(self.send)
        # on the left, the main one first: where the eye starts reading
        row.addWidget(self.send_btn)
        row.addWidget(cancel)
        row.addStretch(1)
        v.addSpacing(6)
        v.addLayout(row)
        # what Send does with the picks (usage.improve): said where people decide
        note = QHBoxLayout()
        note.setSpacing(6)
        shield = QLabel()
        icons.set_label_icon(shield, "shield", size=14)
        self.anon_note = QLabel(_("Anonymous: not linked to you, your account or this PC."))
        self.anon_note.setObjectName("hint")
        self.anon_note.setWordWrap(True)
        note.addWidget(shield, 0, Qt.AlignmentFlag.AlignTop)
        note.addWidget(self.anon_note, 1)
        v.addSpacing(2)
        v.addLayout(note)
        self._changed()
        return w

    def chosen(self) -> list[str]:
        return [k for k, b in self.boxes.items() if b.isChecked()]

    def _changed(self, *_args):
        other = self.boxes["other"].isChecked()
        if other != self.other.isVisible():
            self.other.setVisible(other)
            if other:
                self.other.setFocus()
        self.send_btn.setEnabled(bool(self.chosen()))

    def send(self):
        if not self.chosen():
            return
        self.sent = usage.improve(self.cfg, self.chosen(), self.other.text())
        self.not_sent.setVisible(not self.sent)
        # the stack is as tall as its tallest page: let the short thanks page shrink it
        self.pages.widget(0).setSizePolicy(QSizePolicy.Policy.Ignored,
                                           QSizePolicy.Policy.Ignored)
        self.pages.setCurrentIndex(1)
        self.resize(self.width(), self.minimumSizeHint().height())
        self.form_btn.setFocus()

    # ------------------------------------------------------------------ page 2
    def _thanks_page(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(_title(_("Thanks, that helps!")))
        more = QLabel(_("Want to tell me more, or get a reply? The feedback form takes a "
                        "minute and needs no account."))
        more.setWordWrap(True)
        v.addWidget(more)
        self.not_sent = QLabel(_("The usage count is off, so your picks weren't sent. The "
                                 "form is the way to tell me."))
        self.not_sent.setObjectName("hint")
        self.not_sent.setWordWrap(True)
        v.addWidget(self.not_sent)
        row = QHBoxLayout()
        done = QPushButton(_("Done"))
        done.clicked.connect(self.accept)
        self.form_btn = QPushButton(_("Open the feedback form"))
        self.form_btn.setObjectName("primary")
        self.form_btn.clicked.connect(self.open_form)
        row.addWidget(self.form_btn)
        row.addWidget(done)
        row.addStretch(1)
        v.addSpacing(6)
        v.addLayout(row)
        return w

    def form_url(self) -> str:
        return feedback.feedback_url(__version__, improve=self.chosen())

    def open_form(self):
        if busy.open_url(self.form_url(), window=self.parentWidget(),
                         failed=_("Couldn't open your browser. The page is")):
            self.accept()


def ask(cfg, parent=None) -> FeedbackDialog:
    """Show the box (not modal: the board keeps playing). Returns it, for tests."""
    dlg = FeedbackDialog(cfg, parent)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    return dlg
