"""The "{name} invited you" greeting on a first start, from the installer's note
(soundboard.core.invite)."""
from __future__ import annotations

from soundboard.core import invite
from soundboard.i18n import _
from soundboard.sounds import library


def welcome(mw) -> bool:
    """Greet them once with the name of the friend who invited them, if the installer
    left one. Run where the queued import runs: after the setup guide."""
    name = invite.take_note(library.APP_DIR)
    if not name or mw._shut_down:
        return False
    mw.set_option("invited_by", name)
    mw.toast(_("{name} invited you to Onion Board. Have fun!", name=name), "ok")
    return True
