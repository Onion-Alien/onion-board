"""Import from another soundboard: what the readers for each one share.

Each reader (soundpad.py, resanance.py, soundux.py, expboard.py) finds that app's saved board on
this PC and turns it into Entry rows: the user's own sound files with their names,
hotkeys and categories. Nothing is read until the user asks for an import (the
Backup menu, the setup guide, the installer's box, or a board file dropped on the
window), and nothing of the other app's is changed; the sound files are copied.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from soundboard.library import AUDIO_EXTS

# left in our app folder by the installer's "Bring my sounds over from …" boxes, one
# source key per line, for the app's first start to do (ui.mainwindow import_queued)
QUEUED_NAME = "import-from"


@dataclass
class Entry:
    path: str                 # absolute path of the sound file
    name: str
    hotkey: str = ""          # in our "ctrl+alt+s" form, "" if none or not one we know
    tags: list[str] = field(default_factory=list)   # its categories
    exists: bool = True


@dataclass(frozen=True)
class Source:
    key: str                  # in the installer's note and the tests
    name: str                 # "Soundpad"
    suffixes: tuple[str, ...]   # its saved board files, for the file picker / drops
    find: Callable[[], Path | None]   # its board on this PC, if there is one
    read: Callable[[Path], list[Entry]]   # ValueError with a plain message if it can't
    # for a suffix other files use too (.json): is this file really one of its boards?
    claims: Callable[[str], bool] | None = None


def importable(entries: list[Entry]) -> tuple[list[Entry], list[Entry]]:
    """(the ones whose file is there and plays, the ones that are missing or not audio)."""
    ok, bad = [], []
    for e in entries:
        (ok if e.exists and Path(e.path).suffix.lower() in AUDIO_EXTS else bad).append(e)
    return ok, bad


def sources() -> list[Source]:
    from soundboard import expboard, resanance, soundpad, soundux
    return [soundpad.SOURCE, resanance.SOURCE, soundux.SOURCE, expboard.SOURCE]


def by_key(key: str) -> Source | None:
    return next((s for s in sources() if s.key == key), None)


def for_file(path: str) -> Source | None:
    """The source whose board file this is, by its name (a drop on the window)."""
    p = path.lower()
    return next((s for s in sources() if any(p.endswith(x) for x in s.suffixes)
                 and (s.claims is None or s.claims(path))), None)


def found() -> list[Source]:
    """The soundboards whose saved board is on this PC."""
    out = []
    for s in sources():
        try:
            if s.find():
                out.append(s)
        except OSError:
            pass
    return out


def vk_hotkey(vk: int, ctrl=False, alt=False, shift=False, win=False) -> str:
    """A Windows virtual-key code + modifiers -> our 'ctrl+1' form; "" for none, a bare
    modifier, or a mouse button (not keys we can register)."""
    from soundboard import winkeys   # Win32; only needed once there's a key
    if not 0 < vk < 0xFF or vk in winkeys.MODIFIER_VKS or vk in (1, 2, 4, 5, 6):
        return ""
    flags = ((winkeys.MOD_CONTROL if ctrl else 0) | (winkeys.MOD_ALT if alt else 0)
             | (winkeys.MOD_SHIFT if shift else 0) | (winkeys.MOD_WIN if win else 0))
    return winkeys.combo_name(flags, vk)
