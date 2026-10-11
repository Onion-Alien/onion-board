"""Getting FFmpeg from the app (Settings > Data & quality > Get FFmpeg).

The installer offers FFmpeg on its "Pick what you want" page, but only there: someone
who left that box unticked (or installed before the option existed) had no way to add it
later, and playing an M4A, AAC or video link only said "install ffmpeg" with nowhere to
do it. This runs the installer's own install (the Gyan.FFmpeg.Essentials package through
winget, the package manager Windows 10/11 ships) from the app itself.

winget downloads from Microsoft's package source itself, so, like the installer, this
can't go through the app's proxy or Tor; net's "ffmpeg_download" switch only decides
whether the app runs it at all.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from soundboard import library, net
from soundboard.i18n import _

log = logging.getLogger(__name__)

PACKAGE = "Gyan.FFmpeg.Essentials"   # the package the installer ticks (installer/OnionBoard.iss)
FEATURE = "ffmpeg_download"          # net's switch for this download
TIMEOUT_S = 900.0                    # winget fetches about 100 MB; a stuck one is cut here


class GetError(Exception):
    """winget couldn't install FFmpeg; the message is fit to show the user."""


def winget() -> str | None:
    """winget.exe, where the installer looks for it (installer/OnionBoard.iss)."""
    local = os.environ.get("LOCALAPPDATA")
    if local and (Path(local) / "Microsoft" / "WindowsApps" / "winget.exe").is_file():
        return str(Path(local) / "Microsoft" / "WindowsApps" / "winget.exe")
    return shutil.which("winget")


def installed() -> bool:
    """Is there an ffmpeg the app can use (library._ffmpeg)?"""
    return library._ffmpeg() is not None


def can_offer() -> bool:
    """Offer Get FFmpeg only when it's missing and winget is here to get it."""
    return not installed() and winget() is not None


def _last_line(out: str) -> str:
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def get(progress: Callable[[], None] | None = None) -> str:
    """Install FFmpeg with winget and return ffmpeg.exe's path. Raises GetError with words
    for the user. ``progress`` (called once, just before the wait) is for the UI."""
    if net.offline() or not net.allowed(FEATURE):
        raise GetError(net.off_message(FEATURE))
    exe = winget()
    if exe is None:
        raise GetError(_("winget isn't on this PC, so the app can't install FFmpeg. Get it "
                         "from ffmpeg.org instead."))
    if installed():                      # it arrived meanwhile (another click, the installer)
        return library._ffmpeg()
    if progress is not None:
        progress()
    args = [exe, "install", "--id", PACKAGE, "--exact", "--silent",
            "--disable-interactivity", "--accept-package-agreements",
            "--accept-source-agreements"]
    try:
        p = subprocess.run(args, capture_output=True, timeout=TIMEOUT_S,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise GetError(_("winget took longer than {seconds} seconds.",
                         seconds=int(TIMEOUT_S))) from None
    except OSError as e:
        raise GetError(_("Couldn't run winget ({error}).", error=e)) from e
    found = library._ffmpeg()
    if found:                            # winget's WinGet\Links shim is found without a restart
        return found
    out = ((p.stdout or b"").decode(errors="ignore") + "\n"
           + (p.stderr or b"").decode(errors="ignore"))
    log.info("winget couldn't install %s (rc=%s): %s", PACKAGE, p.returncode, out.strip())
    raise GetError(_("winget couldn't install FFmpeg (it said: {error}).",
                     error=_last_line(out) or _("no reason given")))
