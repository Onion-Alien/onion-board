"""The starter sounds: 25 short CC0 sounds that ship inside the app (assets/starter, about
0.7 MB) and are added to a new install's board when Bun's first-run tour ends with the
board still empty (ui/firsttour.py). No download, no button, once only.

They go in a tab of their own, "Starter", so they never sit among the sounds someone adds
later. They're ordinary sounds, imported like dropped files: rename, delete or recolour
them like any other. Deleting them all doesn't bring them back (the flag below
stays in Config.tips_seen)."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from soundboard import usage
from soundboard.i18n import _
from soundboard.otherboards import Entry

log = logging.getLogger(__name__)

KEY = "starter-sounds"   # in Config.tips_seen once added (or once the board had sounds)
# in a source checkout assets/starter, in the frozen app starter/ (build.ps1 bundles it)
ASSET_DIR = (Path(sys._MEIPASS) / "starter" if hasattr(sys, "_MEIPASS")   # pyright: ignore[reportAttributeAccessIssue]
             else Path(__file__).resolve().parent.parent / "assets" / "starter")


def files() -> list[str]:
    """The bundled sounds, A to Z (their names are the file names)."""
    try:
        return [str(p) for p in sorted(ASSET_DIR.glob("*.ogg"))]
    except OSError:
        return []


def add_to(win) -> bool:
    """Add them to `win`'s board, once. False when they were added before, the board has
    sounds already, or they aren't in this copy of the app."""
    cfg = win.cfg
    if KEY in cfg.tips_seen or cfg.sounds:
        return False
    found = files()
    if not found:
        return False
    cfg.tips_seen = [*cfg.tips_seen, KEY]
    win._save_later()
    usage.used("starter-sounds")
    tab = _("Starter")
    entries = {f: Entry(f, Path(f).stem, tags=[tab]) for f in found}
    try:
        win.impctl.import_files(found, entries)
    except RuntimeError:   # the window went meanwhile
        log.info("starter sounds: the window was closing")
        return False
    return True
