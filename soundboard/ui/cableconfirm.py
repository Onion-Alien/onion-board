"""Are you sure, before the virtual cable: it's the fallback for the few who really don't
want Onion Board's audio driver on their mic. Pressed by accident (it sat right under
the main button), it meant picking CABLE Output in Discord and every game, for nothing.
The box's main button is still the mic."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from soundboard import usage
from soundboard.i18n import _
from soundboard.ui import fit, icons


def ask(parent, install: Callable[[], None], use_mic: Callable[[], None],
        mic_text: str | None = None) -> QDialog:
    """Open the box (not modal): `install` runs on Install the cable anyway, `use_mic`
    on the main button (`mic_text` its words, when the mic is set up already). Returns
    it, open."""
    usage.used("cable-confirm")
    d = QDialog(parent)
    d.setObjectName("cableconfirm")
    d.setWindowTitle(_("Install the virtual cable?"))
    d.setMaximumWidth(620)
    v = QVBoxLayout(d)
    v.setContentsMargins(18, 18, 18, 18)
    v.setSpacing(12)
    title = QLabel(_("Install the virtual cable?"))
    title.setObjectName("helptitle")
    v.addWidget(title)
    for text in (
            _("<b>Only get the cable if you know you need it.</b> Most people don't: "
              "<b>Put my sounds into my mic</b> works with the mic Discord and your "
              "games already use."),
            _("With the cable, you have to pick <b>CABLE Output</b> as your microphone in "
              "Discord and in every game, and pick your real mic again if you ever remove "
              "it. It's a separate driver from another company (VB-Audio), and Windows "
              "may need a restart.")):
        label = QLabel(text)
        label.setWordWrap(True)
        v.addWidget(label)
    row = QHBoxLayout()
    row.setSpacing(8)
    row.addStretch(1)
    mic = QPushButton(mic_text or _("Put my sounds into my mic"))
    mic.setObjectName("primary")
    mic.setDefault(True)   # Enter: the mic, never the cable
    icons.set_icon(mic, "mic", "on_accent")
    mic.clicked.connect(lambda: (usage.used("cable-confirm-mic"), d.accept(), use_mic()))
    cable = QPushButton(_("Install the cable anyway"))
    icons.set_icon(cable, "cable")
    cable.clicked.connect(lambda: (d.accept(), install()))
    cancel = QPushButton(_("Cancel"))
    cancel.clicked.connect(d.reject)
    for b in (mic, cable, cancel):
        row.addWidget(b)
    v.addLayout(row)
    d.mic_button, d.cable_button = mic, cable   # pyright: ignore[reportAttributeAccessIssue]
    fit.watch(d)
    d.finished.connect(d.deleteLater)
    d.open()
    return d
