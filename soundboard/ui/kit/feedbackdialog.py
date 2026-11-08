"""*Send feedback*: "What would you improve?" with a few picks and Other, then a thank
you with the feedback form for anyone who wants to say more or get a reply.

Some picks open a few follow-up ticks under them (More sounds > Memes, ...); Fewer bugs
opens a "What bugs did you hit?" line. The picks go out with the anonymous usage count
(usage.improve: names from fixed lists, and the typed words with anything personal
taken out), so they're counted only when that's on. They go with a one-off random
session, never this PC's ID, and the box says so, beside Send. The form only opens in
the browser, like before (feedback.py).

It's a small modal on the shared frame (kit/modalframe.py). Bun sits in its header by the
heading taking notes (ui/bun/notebun.py): each tick and each letter typed, he writes a bit
more in his notebook; on Send he shuts it, bows and a heart floats up."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QLabel, QLineEdit,
                               QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)
import shiboken6

from soundboard import __version__
from soundboard.core import feedback, usage
from soundboard.i18n import _
from soundboard.ui.bun.notebun import LETTER, LINE, NoteBunny
from soundboard.ui.kit import busy, icons
from soundboard.ui.kit.modalframe import MASCOT, ModalDialog




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


class FeedbackDialog(ModalDialog):
    KEEP_OPEN = True   # a click outside doesn't close it: it would lose work
    def __init__(self, cfg, parent=None):
        super().__init__(parent, _("What would you improve?"), width=480)
        self.setWindowModality(Qt.WindowModality.NonModal)   # (the board keeps playing)
        self.cfg = cfg
        self.sent = False
        self.setWindowTitle(_("Send feedback"))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        f = self.frame
        self.heading = f.heading
        self.hint = f.subtitle
        self.hint.setText(_("Tick all that fit."))
        self.hint.setVisible(True)
        # Bun in the mascot's place (the header's first item), as tall as a card's
        # mascot, taking notes; the body's words start past him, on the title's line
        self.bun = NoteBunny(height=MASCOT)
        f.set_picture(self.bun)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._ask_page())
        self.pages.addWidget(self._thanks_page())
        f.add_widget(self.pages)
        f.close_btn.setAutoDefault(False)   # (Enter is Send, never the ✕)
        self.focus_first(self.send_btn)

    def _thanks_footer(self):
        """The thanks page's buttons in place of the picks' (taken out of the row, not
        hidden in it: a hidden button left the row's room to the others, not its stretch)."""
        for w in (self.send_btn, self.cancel_btn, self.shield, self.anon_note):
            self.frame.footer.removeWidget(w)
            w.hide()
        self.form_btn = self.frame.add_button(_("Open the feedback form"), primary=True)
        self.form_btn.clicked.connect(self.open_form)
        self.done_btn = self.frame.add_button(_("Done"))
        self.done_btn.clicked.connect(self.accept)
        self.focus_first(self.form_btn)

    # ------------------------------------------------------------------ page 1
    def _ask_page(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        self.boxes: dict[str, QCheckBox] = {}
        self.more: dict[str, QWidget] = {}        # what opens under a ticked pick
        self.sub_boxes: dict[str, QCheckBox] = {}   # "sounds/memes"
        more = follow_ups()
        self.other = self._text_line(_("What else?"))
        self.bugs_text = self._text_line(_("What bugs did you hit?"), usage.BUGS_MAX)
        for key, text in picks():
            box = self.boxes[key] = QCheckBox(text)
            box.toggled.connect(self._changed)
            box.clicked.connect(self._noted)
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
                sb.clicked.connect(self._noted)
                pv.addWidget(sb)
            if line is not None:
                pv.addWidget(line)
            panel.setVisible(False)
            v.addWidget(panel)
        # the footer: Send and Cancel bottom-right, the main one first; what Send does
        # with the picks (usage.improve) said beside it, where people decide
        self.send_btn = self.frame.add_button(_("Send"), primary=True)
        self.send_btn.clicked.connect(self.send)
        self.cancel_btn = self.frame.add_button(_("Cancel"))
        self.cancel_btn.clicked.connect(self.reject)
        self.shield = QLabel()
        icons.set_label_icon(self.shield, "shield", size=14)
        self.anon_note = QLabel(_("Anonymous: not linked to you or this PC."))
        self.anon_note.setObjectName("muted")
        foot = self.frame.footer
        foot.insertWidget(0, self.shield, 0, Qt.AlignmentFlag.AlignVCenter)
        foot.insertWidget(1, self.anon_note, 0, Qt.AlignmentFlag.AlignVCenter)
        self._changed()
        return w

    def _text_line(self, placeholder: str, limit: int = 200) -> QLineEdit:
        line = QLineEdit()
        line.setPlaceholderText(placeholder)
        line.setMaxLength(limit)
        line.textEdited.connect(lambda _t: self.bun.write(LETTER))
        return line

    def _noted(self, *_args):
        self.bun.write(LINE)

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
            # Settle the follow-ups and resize during the checkbox change.
            self._fit_height()
        self.send_btn.setEnabled(any(b.isChecked() for b in self.boxes.values()))

    def _fit_height(self):
        if not shiboken6.isValid(self):
            return
        page = self.pages.currentWidget()
        if page is not None:
            page_layout = page.layout()
            assert page_layout is not None   # both pages have a vertical layout
            page_layout.invalidate()
            page.updateGeometry()
        stack_layout = self.pages.layout()
        assert stack_layout is not None   # QStackedWidget owns its layout
        stack_layout.invalidate()
        self.pages.updateGeometry()
        card = self.frame.layout()
        assert card is not None   # the frame's own
        card.invalidate()
        card.activate()
        self.updateGeometry()
        lay = self.layout()
        assert lay is not None   # made in __init__
        lay.activate()
        self.resize(self.width(), self.minimumSizeHint().height())

    def send(self):
        if not any(b.isChecked() for b in self.boxes.values()):
            return
        self.sent = usage.improve(self.cfg, self.chosen(), self.other.text(),
                                  self.bugs_text.text())
        self.not_sent.setVisible(not self.sent)
        self.bun.finish()
        # the stack is as tall as its tallest page: let the short thanks page shrink it
        form = self.pages.widget(0)
        assert form is not None   # the form, then the thanks
        form.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.heading.setText(_("Thanks, that helps!"))
        self.hint.hide()
        self.pages.setCurrentIndex(1)
        self._thanks_footer()
        self._fit_height()
        self.form_btn.setFocus()

    # ------------------------------------------------------------------ page 2
    def _thanks_page(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        more = QLabel(_("Want to tell me more, or get a reply? The feedback form takes a "
                        "minute and needs no account."))
        more.setWordWrap(True)
        v.addWidget(more)
        self.not_sent = QLabel(_("The usage count is off, so your picks weren't sent. The "
                                 "form is the way to tell me."))
        self.not_sent.setObjectName("hint")
        self.not_sent.setWordWrap(True)
        v.addWidget(self.not_sent)
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
