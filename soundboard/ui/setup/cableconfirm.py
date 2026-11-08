"""Are you sure, before the virtual cable: it's the fallback for the few who really don't
want Onion Board's audio driver on their mic. Pressed by accident (it sat right under
the main button), it meant picking CABLE Output in Discord and every game, for nothing.
The box's main button is still the mic."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QDialog

from soundboard.core import usage
from soundboard.i18n import _
from soundboard.ui.kit import icons
from soundboard.ui.kit.modalframe import ModalDialog
from soundboard.ui.setup.wizardkit import SMALL_W, rich, small_ask


def ask(parent, install: Callable[[], None], use_mic: Callable[[], None],
        mic_text: str | None = None) -> QDialog:
    """Open the box (not modal): `install` runs on Install the cable anyway, `use_mic`
    on the main button (`mic_text` its words, when the mic is set up already). Returns
    it, open."""
    usage.used("cable-confirm")
    # kit's small modal, the same box as every short question (confirm)
    d = ModalDialog(parent, _("Install the virtual cable?"), mascot="bun", width=SMALL_W)
    d.setObjectName("cableconfirm")
    f = small_ask(d)
    for text in (
            _("<b>Only get the cable if you know you need it.</b> Most people don't: "
              "<b>Put my sounds into my mic</b> works with the mic Discord and your "
              "games already use."),
            _("With the cable, you have to pick <b>CABLE Output</b> as your microphone in "
              "Discord and in every game, and pick your real mic again if you ever remove "
              "it. It's a separate driver from another company (VB-Audio), and Windows "
              "may need a restart.")):
        rich(f, text)
    mic = f.add_button(mic_text or _("Put my sounds into my mic"), primary=True)
    icons.set_icon(mic, "mic", "on_accent")   # (default: Enter is the mic, never the cable)
    mic.clicked.connect(lambda: (usage.used("cable-confirm-mic"), d.accept(), use_mic()))
    cable = f.add_button(_("Install the cable anyway"))
    icons.set_icon(cable, "cable")
    cable.clicked.connect(lambda: (d.accept(), install()))
    f.add_button(_("Cancel")).clicked.connect(d.reject)
    d.mic_button, d.cable_button = mic, cable   # pyright: ignore[reportAttributeAccessIssue]
    d.finished.connect(d.deleteLater)
    d.open()
    return d
