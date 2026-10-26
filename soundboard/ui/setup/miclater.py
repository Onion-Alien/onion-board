"""After a guide finished without the sounds in a mic: the box saying where to put
them in once the mic's plugged in."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from soundboard.ui.kit import icons
from soundboard.ui.bun.bunnywidget import BunnyWidget
from soundboard.i18n import _
from soundboard.ui.setup.wizardkit import BUN_H, BUN_PAD


def mic_later(win) -> QDialog:
    """After a guide finished without the sounds in a mic: where to put them in, once
    the mic's plugged in (Settings → Audio's Install mic effect). Returns the box (open)."""
    d = QDialog(win)
    d.setWindowTitle(_("One more step"))
    d.setMaximumWidth(560)
    v = QVBoxLayout(d)
    v.setContentsMargins(18, 18, 18, 18)
    v.setSpacing(12)
    head = QHBoxLayout()
    head.setSpacing(14)
    head.addWidget(BunnyWidget("plug", height=BUN_H, pad=BUN_PAD), 0, Qt.AlignmentFlag.AlignTop)
    words = QVBoxLayout()
    words.setSpacing(8)
    title = QLabel(_("Your sounds aren't in your mic yet"))
    title.setObjectName("helptitle")
    words.addWidget(title)
    for text in (_("Right now only you hear your sounds."),
                 _("When your mic is plugged in, go to <b>Settings → Audio</b> and press "
                   "<b>Install mic effect</b>. Without it, your sounds won't go through to "
                   "Discord or games."),
                 _("New mic or headset later? Do it again for that one: each mic needs it "
                   "once.")):
        label = QLabel(text)
        label.setWordWrap(True)
        words.addWidget(label)
    head.addLayout(words, 1)
    v.addLayout(head)
    row = QHBoxLayout()
    row.setSpacing(8)
    row.addStretch(1)
    go = QPushButton(_("Open Settings → Audio"))
    icons.set_icon(go, "mic", "on_accent")
    go.setObjectName("primary")
    go.setDefault(True)
    go.clicked.connect(lambda: (d.accept(), win.setctl.open_settings("audio")))
    later = QPushButton(_("Got it, later"))
    later.clicked.connect(d.reject)
    row.addWidget(go)
    row.addWidget(later)
    v.addLayout(row)
    d.open()
    return d
