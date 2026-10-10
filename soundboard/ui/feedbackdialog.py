"""*Send feedback*: "What would you improve?" with a few picks and Other, then a thank
you with the feedback form for anyone who wants to say more or get a reply.

Some picks open a few follow-up ticks under them (More sounds > Memes, ...); Fewer bugs
opens a "What bugs did you hit?" line. The picks go out with the anonymous usage count
(usage.improve: names from fixed lists, and the typed words with anything personal
taken out), so they're counted only when that's on. They go with a one-off random
session, never this PC's ID, and the box says so. The form only opens in the browser,
like before (feedback.py)."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)
import shiboken6

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


def follow_ups() -> dict[str, list[tuple[str, str]]]:
    """What opens under a pick when it's ticked: (usage.IMPROVE_MORE name, text)."""
    return {
        "sounds": [("memes", _("Memes")), ("music", _("Music")),
                   ("game", _("Game sounds")), ("reactions", _("Reactions")),
                   ("voice-lines", _("Voice lines"))],
        "setup": [("others-hear-me", _("Getting others to hear me")),
                  ("pick-mic", _("Picking my mic and headphones")),
                  ("hotkeys", _("Setting up hotkeys")),
                  ("install", _("Installing it"))],
        "voice-chat": [("discord", _("Discord")), ("in-game", _("In-game voice chat")),
                       ("calls", _("Zoom, Teams or a browser call")),
                       ("streaming", _("Streaming (OBS)"))],
        "voice-changer": [("more-voices", _("More voices")),
                          ("more-real", _("Sounds more real")),
                          ("less-delay", _("Less delay")),
                          ("ai-voices", _("AI voices"))],
        "speed": [("starts-slow", _("Starts slowly")),
                  ("heavy", _("Uses a lot of my PC")),
                  ("lags-games", _("Lags my games")),
                  ("stutters", _("Sounds stutter"))],
        "looks": [("crowded", _("Too crowded")), ("hard-to-find", _("Hard to find things")),
                  ("themes", _("More themes")), ("text-size", _("Text too small"))],
    }


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
        self.more: dict[str, QWidget] = {}        # what opens under a ticked pick
        self.sub_boxes: dict[str, QCheckBox] = {}   # "sounds/memes"
        more = follow_ups()
        self.other = self._text_line(_("What else?"))
        self.bugs_text = self._text_line(_("What bugs did you hit?"), usage.BUGS_MAX)
        for key, text in picks():
            box = self.boxes[key] = QCheckBox(text)
            box.toggled.connect(self._changed)
            v.addWidget(box)
            subs = more.get(key, [])
            line = {"other": self.other, "bugs": self.bugs_text}.get(key)
            if not subs and line is None:
                continue
            panel = self.more[key] = QWidget()
            pv = QVBoxLayout(panel)
            pv.setContentsMargins(26, 0, 0, 6)   # under the pick's text, past its tick
            pv.setSpacing(2)
            for sub, sub_text in subs:
                sb = self.sub_boxes[f"{key}/{sub}"] = QCheckBox(sub_text)
                pv.addWidget(sb)
            if line is not None:
                pv.addWidget(line)
            panel.setVisible(False)
            v.addWidget(panel)
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
        self.anon_note = QLabel(_("Anonymous: not linked to you or this PC."))
        self.anon_note.setObjectName("hint")
        self.anon_note.setWordWrap(True)
        note.addWidget(shield, 0, Qt.AlignmentFlag.AlignTop)
        note.addWidget(self.anon_note, 1)
        v.addSpacing(2)
        v.addLayout(note)
        self._changed()
        return w

    def _text_line(self, placeholder: str, limit: int = 200) -> QLineEdit:
        line = QLineEdit()
        line.setPlaceholderText(placeholder)
        line.setMaxLength(limit)
        return line

    def chosen(self) -> list[str]:
        """The ticked picks, and the ticked follow-ups of those ("sounds/memes")."""
        top = [k for k, b in self.boxes.items() if b.isChecked()]
        subs = [k for k, b in self.sub_boxes.items()
                if b.isChecked() and k.split("/", 1)[0] in top]
        return top + subs

    def _changed(self, *_args):
        moved = False
        for key, panel in self.more.items():
            on = self.boxes[key].isChecked()
            if on != panel.isVisible():
                panel.setVisible(on)
                moved = True
                if on and key in ("other", "bugs"):   # a text box: ready to type
                    (self.other if key == "other" else self.bugs_text).setFocus()
        if moved:
            # grow and shrink with the follow-ups, no gap left behind; once the layout
            # has caught up with what was just shown or hidden
            # (two turns: the hidden rows' sizes settle one turn after they're hidden)
            QTimer.singleShot(0, lambda: QTimer.singleShot(0, self._fit_height))
        self.send_btn.setEnabled(any(b.isChecked() for b in self.boxes.values()))

    def _fit_height(self):
        if not shiboken6.isValid(self):
            return
        self.layout().activate()
        self.resize(self.width(), self.minimumSizeHint().height())

    def send(self):
        if not any(b.isChecked() for b in self.boxes.values()):
            return
        self.sent = usage.improve(self.cfg, self.chosen(), self.other.text(),
                                  self.bugs_text.text())
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
