"""What's new: shown once after an update (or the first start of a newer version over
an older one's settings), with what the release added and a button straight to the
settings it's about. Config.whats_new_seen is the newest version they've seen it
for; a first start has nothing to catch up on (library.Config)."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from soundboard import __version__, updates
from soundboard.ui import fit
from soundboard.ui.panel import hint_label, icon_label


@dataclass(frozen=True)
class Note:
    version: str                       # the release it came in
    headline: str
    items: tuple[tuple[str, str, str], ...]   # (icon, title, one or two sentences)
    page: str = ""                     # the Settings page its button opens ("" = none)
    page_label: str = ""


# newest first; add one per release that has something worth telling
NOTES = (
    Note("1.6.7", "A much better voice changer", (
        ("voice", "Sounds like a person, not a cartoon",
         "Natural sound and Voice size on the Voice tab, mic clean-up on to start with, "
         "and new voices: Female, Male, Talkbox, Autotune, Masked caller and more."),
        ("sliders", "Click anywhere on a slider",
         "Every slider jumps straight to where you click its bar; no need to grab the "
         "circle."),
        ("check", "Fixes",
         "Space pauses the sound you're on instead of restarting it, live tabs glow "
         "green, and getting Onion Watch shows its real progress."),
    )),
    Note("1.6.6", "Coming from another soundboard?", (
        ("sounds", "Bring your sounds over",
         "Backup → Import from another soundboard copies in your Soundpad, Resanance, "
         "Soundux or EXP Soundboard sounds, with their names, categories and hotkeys. "
         "Your old app keeps its own copies."),
        ("check", "Fixes",
         "Quitting with Onion Watch watching no longer ends in a crash report, and the "
         "Triggers tab counts all your triggers past 50."),
    )),
    Note("1.6.5", "Your privacy, your call", (
        ("shield", "A switch for everything that goes online",
         "Settings → Privacy & security lists each thing Onion Board connects to: sound "
         "search per site, radio, update checks, add-ons, voice downloads. Switch off what "
         "you don't use, or turn on Offline mode and it never goes online."),
        ("cable", "Hide your address",
         "Settings → Connection: send the app's connections through your own proxy, or "
         "through Tor (an optional download from the Tor Project), so sites and radio "
         "stations don't see where you are."),
        ("radio", "See every connection",
         "Settings → Connection → Network activity shows each connection the app makes "
         "and why. Saving that history between starts is up to you."),
        ("wave", "Quieter by default",
         "The radio maps ship with the app, secure streams come first, the radio only "
         "counts your plays if you ask it to, and update checks no longer send your "
         "version."),
        ("live", "No virtual cable needed",
         "Setup → Devices → Send to others through: the virtual cable (as before), "
         "another device (Voicemeeter, a mixer, anything OBS captures) or nowhere (only "
         "you hear your sounds). With the last two it never asks you to install the cable."),
    ), "privacy", "Open Privacy && security"),
)


def unseen(seen: str) -> list[Note]:
    """The notes for versions newer than `seen` (none past this one), newest first."""
    return [n for n in NOTES
            if updates.newer(n.version, seen or "0") and not updates.newer(n.version)]


def _heading(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("font-size: 15pt; font-weight: 600;")   # the theme sets fonts in QSS
    lbl.setWordWrap(True)
    return lbl


class WhatsNewDialog(QDialog):
    """The notes in `notes`; its button opens Settings on that page (mw.open_settings)
    after this closes. `updated`: it follows an update the app installed itself."""

    def __init__(self, mw, notes: list[Note], updated: bool = False):
        super().__init__(mw)
        fit.watch(self)
        self.mw = mw
        self.page = ""   # set when they pressed the settings button
        self.setWindowTitle("What's new")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)
        top = notes[0]
        lay.addWidget(_heading(top.headline))
        lay.addWidget(hint_label(
            f"{'Updated to' if updated else 'New in'} Onion Board {__version__}. "
            "Nothing changes until you want it to: everything works as before."))
        for note in notes:
            for icon, title, text in note.items:
                lay.addWidget(self._item(icon, title, text))
        lay.addStretch(1)   # any spare height goes here, not between the rows
        buttons = QHBoxLayout()
        notes_btn = QPushButton("Full release notes")
        notes_btn.setToolTip("This version's page on GitHub, in your browser")
        notes_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(
            f"https://github.com/{updates.REPO}/releases/tag/v{__version__}")))
        buttons.addWidget(notes_btn)
        buttons.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        page = next((n for n in notes if n.page), None)
        if page is not None:
            go = QPushButton(page.page_label)
            go.setObjectName("primary")
            go.setDefault(True)
            go.clicked.connect(lambda: self._open(page.page))
            buttons.addWidget(go)
            self.settings_btn = go
        else:
            close.setDefault(True)
        lay.addLayout(buttons)

    def showEvent(self, ev):
        super().showEvent(ev)
        # Qt's first guess ignores how the hints wrap: as tall as the text, no taller
        self.resize(self.width(), fit.needed_height(self, self.width()))

    def _item(self, icon: str, title: str, text: str) -> QWidget:
        row = QFrame()
        row.setObjectName("setcard")
        h = QHBoxLayout(row)
        h.setContentsMargins(12, 9, 12, 10)
        h.setSpacing(10)
        h.addWidget(icon_label(icon), 0, Qt.AlignTop)
        v = QVBoxLayout()
        v.setSpacing(2)
        t = QLabel(title)
        f = QFont(t.font())
        f.setBold(True)
        t.setFont(f)
        t.setWordWrap(True)
        v.addWidget(t)
        v.addWidget(hint_label(text))
        h.addLayout(v, 1)
        return row

    def _open(self, page: str):
        self.page = page
        self.accept()
