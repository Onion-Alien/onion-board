"""Removing VB-Cable once straight into the mic works: the cable is only the fallback
then. VB-Audio's own setup program, which its install leaves in Program Files, removes
it with ``-u -h`` (the installer's uninstall step does the same). Windows asks for
permission first, and lists the CABLE devices (not working) until the next restart."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from soundboard import directmic
from soundboard.i18n import _

log = logging.getLogger(__name__)


def setup_exe() -> Path | None:
    """VB-Audio's setup program, or None: no VB-Cable to remove (another kind of
    virtual cable, e.g. Voicemeeter's, is left alone)."""
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    for p in (Path(pf) / "VB" / "CABLE" / "VBCABLE_Setup_x64.exe",
              Path(pf86) / "VB" / "CABLE" / "VBCABLE_Setup.exe"):
        if p.is_file():
            return p
    return None


def remove() -> str | None:
    """Remove VB-Cable (Windows asks first). None when done, else what went wrong, in
    plain words."""
    exe = setup_exe()
    if exe is None:
        return _("VB-Cable's own setup program isn't on this PC, "
                 "so it can't be removed here.")
    code = directmic.run_elevated(str(exe), "-u -h", wait_s=120.0)
    if code is None:
        return _("Windows' admin prompt was turned down (or didn't finish).")
    log.info("VB-Cable removed (setup exit code %s)", code)   # (its codes aren't documented)
    return None
