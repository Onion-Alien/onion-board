"""Removing VB-Cable once straight into the mic works: the cable is only the fallback
then. VB-Audio's own setup program, which its install leaves in Program Files, removes
it with ``-u -h`` (the installer's uninstall step does the same). Windows asks for
permission first, and lists the CABLE devices (not working) until the next restart.
Installing it again before that restart doesn't work either: VB-Audio's setup says it
went fine, and Windows can't start the driver (device error 10)."""
from __future__ import annotations

import ctypes
import logging
import os
import time
from pathlib import Path

from soundboard.mic import directmic
from soundboard.i18n import _
from soundboard.sounds import library

log = logging.getLogger(__name__)

_UNINSTALL = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
_MARKER = "cable-removed-pending"   # removed, and the PC hasn't restarted since
_GONE_WAIT_S = 5.0   # how long Windows' list of apps gets to catch up


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
        return directmic.declined()
    if code in directmic.UNFINISHED_CODES:
        return directmic.unfinished()
    # its exit codes aren't documented (a removal that works exits with 1): Windows' list
    # of installed apps says whether it went
    end = time.monotonic() + _GONE_WAIT_S
    while _listed() and time.monotonic() < end:
        time.sleep(0.25)
    if _listed():
        log.warning("VB-Cable still installed after its setup (exit code %s)", code)
        return _("VB-Cable's setup finished, but the cable is still installed. Restart your "
                 "PC and try again.")
    log.info("VB-Cable removed (setup exit code %s)", code)
    try:
        (library.APP_DIR / _MARKER).write_text(time.strftime("%Y-%m-%d %H:%M:%S"),
                                               encoding="ascii")
    except OSError:
        log.warning("couldn't note that the cable was removed", exc_info=True)
    return None


def _listed() -> bool:
    """VB-Cable is in Windows' list of installed apps. Not its CABLE devices: those stay
    listed, and "OK", until the next restart."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _UNINSTALL) as k:
            return any(winreg.EnumKey(k, i).startswith("VB:VBCABLE")
                       for i in range(winreg.QueryInfoKey(k)[0]))
    except OSError:
        return False


def written_this_boot(path: Path) -> bool:
    """The file was written since the PC last started (a marker that a restart ends)."""
    try:
        written = path.stat().st_mtime
    except OSError:
        return False
    tick = ctypes.windll.kernel32.GetTickCount64
    tick.restype = ctypes.c_uint64
    return written > time.time() - tick() / 1000


def removed_pending() -> bool:
    """Removed, and the PC hasn't restarted since: the cable can't be used or installed
    yet, even after this app restarts."""
    return written_this_boot(library.APP_DIR / _MARKER)
