"""The picked mic is one another app makes (Voicemod's, NVIDIA Broadcast's, Steam's...) and
Onion Board almost never works in it: which app, and the ways on."""
from __future__ import annotations

import html
from collections.abc import Callable, Sequence

from PySide6.QtWidgets import QComboBox, QPushButton

from soundboard.i18n import _
from soundboard.ui.kit.modalframe import ModalDialog
from soundboard.ui.setup.wizardkit import SMALL_W, rich, small_ask


class VirtualMicBox(ModalDialog):
    def __init__(self, parent, app: str, mic: str, real: Sequence[str]):
        super().__init__(parent, _("{app}'s mic probably won't work", app=app),
                         mascot="bun", width=SMALL_W)
        self.setObjectName("virtualmicbox")
        f = small_ask(self)
        words = {"app": html.escape(app), "mic": html.escape(mic)}
        rich(f, _("<b>{mic}</b> is made by {app}. Windows usually won't run Onion Board "
                  "inside it.", **words))
        self.mic_box: QComboBox | None = None
        if real:
            rich(f, _("<b>Best fix:</b> use your real mic here, and pick the same one in "
                      "Discord and your games."))
            self.mic_box = QComboBox()
            self.mic_box.setAccessibleName(_("Your mic"))
            for name in real:
                self.mic_box.addItem(name, name)
            f.add_widget(self.mic_box)
        rich(f, _("Quit {app} or turn its mic off in Windows, then try again.",
                  **words))
        rich(f, _("Trying anyway can take 2 minutes, cuts your PC's sound a few times and "
                  "usually fails."), hint=True)
        self.mic_button: QPushButton | None = None
        if real:
            self.mic_button = f.add_button(_("Use my real mic"), primary=True)
        self.again_button = f.add_button(_("Try again"), primary=not real)
        self.anyway_button = f.add_button(_("Try anyway"))
        self.cable_button = f.add_button(_("Use the cable"), left=True)
        self.focus_first(self.mic_button or self.again_button)


def ask(parent, app: str, mic: str, real: Sequence[str], *, use_mic: Callable[[str], None],
        again: Callable[[], None], anyway: Callable[[], None],
        cable: Callable[[], None]) -> VirtualMicBox:
    """Open the box: `mic` is made by `app`, `real` are the real mics there are. Runs
    what was picked (`use_mic` with the real mic's name). Returns it, open."""
    d = VirtualMicBox(parent, app, mic, real)

    def picked():
        name = d.mic_box.currentData() if d.mic_box is not None else ""
        d.accept()
        use_mic(name)
    if d.mic_button is not None:
        d.mic_button.clicked.connect(picked)
    d.again_button.clicked.connect(lambda: (d.accept(), again()))
    d.anyway_button.clicked.connect(lambda: (d.accept(), anyway()))
    d.cable_button.clicked.connect(lambda: (d.accept(), cable()))
    d.finished.connect(d.deleteLater)
    d.open()
    return d
