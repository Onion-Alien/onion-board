"""Settings → Add-ons and About: the add-ons, the version, getting in touch, support and the
disclaimer."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from soundboard.i18n import _
from soundboard.ui import busy, icons
from soundboard.ui.settingspages import Page, _button_row


# Plain words, not a contract: the LICENSE file is the real terms.
DISCLAIMER = _(
    "Onion Board is provided as is, with no warranty: use it at your own risk (the "
    "LICENSE file has the full terms). In plain words:"
    "<ul style='margin-left:-24px'>"
    "<li><b>Your sounds are on you.</b> It comes with none of its own. Only download, "
    "play or stream things you have the right to use, and follow the rules of the sites "
    "you get them from.</li>"
    "<li><b>Recording people.</b> Instant replay and radio clips record what your PC "
    "plays. Some places need everyone's OK to record a call, so ask first.</li>"
    "<li><b>Voices.</b> Don't use the voice changer or text-to-speech to pretend to be "
    "a real person, to scam or to harass anyone.</li>"
    "<li><b>Games and servers.</b> Some servers and games don't allow soundboards or "
    "voice changers. Onion Board never changes a game's files or reads its memory, but whether a "
    "server is OK with it is their call, and your account.</li>"
    "<li><b>Your ears.</b> Keep an eye on the volume, yours and your friends'.</li>"
    "<li><b>Names.</b> Discord, YouTube, VB-Audio and every other product named here "
    "belong to their owners. Onion Board isn't affiliated with or endorsed by any of "
    "them.</li>"
    "<li><b>Other people's code.</b> Parts of Onion Board (Qt, yt-dlp and more) "
    "come under their own licenses; THIRD-PARTY-NOTICES.txt next to the app lists "
    "them.</li></ul>")


class HelpPage(Page):
    """Settings → Add-ons and About."""

    def _help(self):
        w, v = self._page()
        col = QWidget()
        col.setMaximumWidth(self.dlg.ADDONS_W)
        cl = QVBoxLayout(col)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(12)
        cl.addWidget(self.dlg._addons_card())
        row = QHBoxLayout()
        row.addWidget(col, 1)
        row.addStretch(0)
        v.addLayout(row)
        v.addStretch(1)
        return w

    # ------------------------------------------------------------------ about
    def _about(self):
        w, v = self._page()
        v.addWidget(self._about_card())
        v.addWidget(self._contact_card())
        v.addWidget(self._support_card())
        v.addWidget(self._note_card())
        v.addWidget(self._disclaimer_card())
        v.addStretch(1)
        return w

    def _about_card(self):
        """The version (as the title bar shows it), and where the app and its licences
        live."""
        from soundboard.ui.mainwindow import version_text
        from soundboard.updates import REPO
        card, cv = self._card("Onion Board")
        ver = self.dlg.about_version = QLabel(_("Version {version}", version=version_text()))
        ver.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cv.addWidget(ver)
        hint = QLabel(_("Free, with no ads and no account. Made by OnionAlien. MIT license with "
                        "the Commons Clause: use it for anything, share it for free, never sell "
                        "it."))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        cv.addWidget(hint)
        row = _button_row()
        row.addWidget(self._link_button(_("Website"), "https://onion-alien.github.io/onion-board/",
                                        "browser"))
        row.addWidget(self._link_button(_("Source code"), f"https://github.com/{REPO}"))
        row.addWidget(self._link_button(_("Licenses"), f"https://github.com/{REPO}#license"))
        cv.addLayout(row)
        return card

    def _contact_card(self):
        """Ways to reach the author. All of them only open a page in the browser:
        nothing is sent from the app (feedback.py)."""
        from soundboard import __version__, feedback
        from soundboard.updates import REPO
        card, cv = self._card(_("Get in touch"),
                              _("The Discord is where to chat, ask for help and hear about new "
                                "versions. The feedback form needs no account. Found a security "
                                "problem? Report it privately on GitHub, not in a public issue."))
        row = _button_row()
        discord = self._link_button(_("Join the Discord"), feedback.DISCORD_URL, "speech")
        discord.setObjectName("primary")
        row.addWidget(discord)
        send = QPushButton(_("Send feedback"))
        icons.set_icon(send, "edit")
        send.clicked.connect(self._ask_feedback)
        row.addWidget(send)
        bug = self._link_button(_("Report a problem"), feedback.problem_url(__version__))
        bug.setToolTip(_("For people with a GitHub account: opens a new bug report"))
        row.addWidget(bug)
        self.dlg.discord_btn, self.dlg.feedback_btn, self.dlg.problem_btn = discord, send, bug
        row.addWidget(self._link_button(
            _("Report a security issue"), f"https://github.com/{REPO}/security/advisories/new",
            "shield"))
        cv.addLayout(row)
        return card

    def _disclaimer_card(self):
        card, cv = self._card(_("The boring bit"))
        text = QLabel(DISCLAIMER)
        text.setObjectName("hint")
        text.setWordWrap(True)
        text.setTextFormat(Qt.TextFormat.RichText)
        cv.addWidget(text)
        return card

    # ------------------------------------------------------------------ support
    def _support_card(self):
        """A link to the GitHub page's Support section: the ways to donate live there,
        not in the app, so they can change without a release and a copy of the app
        with someone else's details swapped in is easy to spot."""
        from soundboard.updates import REPO
        card, cv = self._card(_("Support Onion Board"),
                              _("Onion Board is free, with no ads and no account. If it made "
                                "your games or calls more fun, you can chip in. Entirely "
                                "optional. The button opens the project's GitHub page."))
        btn = QPushButton(_("♥  Support Onion Board"))
        btn.clicked.connect(lambda: busy.open_url(
            f"https://github.com/{REPO}#support-onion-board", btn,
            opened=_("✓ Opened in your browser, thank you!"),
            failed=_("Couldn't open your browser. The page is")))
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addStretch(1)
        cv.addLayout(row)
        return card

    def _ask_feedback(self):
        """*Send feedback*: "What would you improve?" (ui/feedbackdialog.py)."""
        from soundboard.ui import feedbackdialog
        self.dlg.feedback_box = feedbackdialog.ask(self.mw.cfg, self.dlg)
