"""After a guide finished without the sounds in a mic: the box saying where to put
them in once the mic's plugged in."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog

from soundboard.ui.kit import icons
from soundboard.ui.kit.modalframe import ModalDialog
from soundboard.i18n import _
from soundboard.ui.setup.wizardkit import SMALL_W, rich, small_ask


def mic_later(win) -> QDialog:
    """After a guide finished without the sounds in a mic: where to put them in, once
    the mic's plugged in (Settings → Audio's Install mic effect). Returns the box (open)."""
    # kit's small modal, the same box as every short question (confirm)
    d = ModalDialog(win, _("Your sounds aren't in your mic yet"), mascot="bun", width=SMALL_W)
    d.setWindowTitle(_("One more step"))
    f = small_ask(d, _("Right now only you hear your sounds."))
    for text in (_("When your mic is plugged in, go to <b>Settings → Audio</b> and press "
                   "<b>Install driver</b>. Without it, your sounds won't go through to "
                   "Discord or games."),
                 _("New mic or headset later? Do it again for that one: the driver works "
                   "on one mic at a time.")):
        rich(f, text)
    go = f.add_button(_("Open Settings → Audio"), primary=True)
    icons.set_icon(go, "mic", "on_accent")
    go.clicked.connect(lambda: (d.accept(), win.setctl.open_audio("driver")))
    f.add_button(_("Got it, later")).clicked.connect(d.reject)
    d.open()
    return d
