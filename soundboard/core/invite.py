"""Invite a friend: a link to the download page with the inviter's name on it, and the
"{name} invited you" greeting on the friend's first start. Nothing is counted or sent.

The link opens onionalien.com/invite/?from=<name>, whose download button hands out the
installer as `OnionBoardSetup-from-<name>.exe`. The installer reads the name back out of
its own file name and, on a new install, leaves it in `invited-by` beside the settings
for the first start to greet them with (installer/OnionBoard.iss, InviteName).
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

INVITE_URL = "https://onionalien.com/invite/"
NOTE_NAME = "invited-by"
MAX_NAME = 24
# letters and digits of any script, spaces, _ - . : what a gamertag needs and a file name
# can hold (the site's download and the installer keep the same set)
_NOT_ALLOWED = re.compile(r"[^\w .-]")


def clean(name: str) -> str:
    """The name as the link, the file name and the greeting show it: the allowed
    characters only, single spaces, at most MAX_NAME long."""
    name = _NOT_ALLOWED.sub("", str(name or ""))
    name = " ".join(name.split())
    return name[:MAX_NAME].strip(" .-")


def link(name: str = "") -> str:
    """The invite link, with the name on it when there is one."""
    name = clean(name)
    return INVITE_URL + (f"?from={quote(name)}" if name else "")


def take_note(app_dir: Path) -> str:
    """The name the installer left for this first start, and the note gone: "" when there
    is none (or it can't be read)."""
    note = Path(app_dir) / NOTE_NAME
    try:
        if not note.is_file():
            return ""
        text = note.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""
    try:
        note.unlink()
    except OSError:
        pass
    return clean(text.strip())
