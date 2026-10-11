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
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from soundboard import library, net
from soundboard.i18n import _

log = logging.getLogger(__name__)

PACKAGE = "Gyan.FFmpeg.Essentials"   # the package the installer ticks (installer/OnionBoard.iss)
FEATURE = "ffmpeg_download"          # net's switch for this download
TIMEOUT_S = 900.0                    # winget fetches about 100 MB; a stuck one is cut here
CHECK_TIMEOUT_S = 8.0                # `ffmpeg -version` answers in well under a second;
                                     # a cold disk and a virus scan get a few more
SITE = "https://ffmpeg.org/download.html"   # where to get it by hand

OK, MISSING, BROKEN = "ok", "missing", "broken"
# sound files only FFmpeg can read (libsndfile reads the rest of library.AUDIO_EXTS)
NEEDS_FFMPEG = {".m4a", ".aac", ".wma", ".webm", ".mp4", ".mkv", ".mov"}


class GetError(Exception):
    """winget couldn't install FFmpeg; the message is fit to show the user."""


@dataclass(frozen=True)
class Health:
    """What check() found: ``state`` is OK, MISSING or BROKEN; ``version`` ("7.1") when
    it runs; ``why`` (for the user) when it's broken."""
    state: str
    version: str = ""
    path: str = ""
    why: str = ""


_last: Health | None = None   # check()'s latest answer, for the UI thread to show
_fixing = threading.Lock()    # one install at a time (the bar's Fix it and Settings')
_has_winget: bool | None = None   # winget() at the last check (None: not looked yet)


def last() -> Health | None:
    """The latest check() (None: not checked yet). Cheap: safe on the UI thread."""
    return _last


def _run_version(exe: str) -> subprocess.CompletedProcess:
    return subprocess.run([exe, "-version"], capture_output=True, timeout=CHECK_TIMEOUT_S,
                          stdin=subprocess.DEVNULL,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _leftovers() -> bool:
    """winget's FFmpeg half there: its link with nothing behind it, or its package folder
    without ffmpeg.exe. winget still counts that as installed, so a plain install skips it."""
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return False
    winget_dir = Path(local) / "Microsoft" / "WinGet"
    link = winget_dir / "Links" / "ffmpeg.exe"
    if os.path.lexists(link) and not link.is_file():
        return True
    try:
        return any(p.is_dir() for p in (winget_dir / "Packages").glob(PACKAGE + "*"))
    except OSError:
        return False


def _version(out: str) -> str:
    """"ffmpeg version 7.1-essentials_build-www.gyan.dev Copyright…" -> "7.1"."""
    words = out.split()
    if len(words) < 3 or words[:2] != ["ffmpeg", "version"]:
        return ""
    v = words[2]
    if v[:1] == "n" and v[1:2].isdigit():   # git builds say "n7.1"
        v = v[1:]
    return (v.split("-")[0] if v[:1].isdigit() else v)[:20]


def check() -> Health:
    """Is FFmpeg there and does it start? Runs ffmpeg, so never on the UI thread."""
    global _last, _has_winget
    _has_winget = winget() is not None
    _last = h = _check()
    log.info("FFmpeg check: %s %s %s %s", h.state, h.version, h.path, h.why)
    return h


def _check() -> Health:
    exe = library._ffmpeg()
    if exe is None:
        if _leftovers():
            return Health(BROKEN, why=_("some of its files are gone"))
        return Health(MISSING)
    try:
        p = _run_version(exe)
    except subprocess.TimeoutExpired:
        return Health(BROKEN, path=exe, why=_("it didn't answer in {seconds} seconds",
                                              seconds=int(CHECK_TIMEOUT_S)))
    except OSError as e:   # not a program, the wrong kind for this PC, a dead link
        log.info("FFmpeg won't start: %s", e)
        return Health(BROKEN, path=exe, why=_("Windows won't start it"))
    out = (p.stdout or b"").decode(errors="ignore")
    if p.returncode != 0:
        log.info("ffmpeg -version gave %s: %s", p.returncode,
                 (p.stderr or b"").decode(errors="ignore").strip())
        return Health(BROKEN, path=exe, why=_("it stops with an error"))
    return Health(OK, _version(out), exe)


def why_cant_fix() -> str:
    """Why the app can't install FFmpeg itself (words for the user), or "" when it can.
    Safe on the UI thread once check() has run (it remembers whether winget is here)."""
    if net.offline() or not net.allowed(FEATURE):
        return net.off_message(FEATURE)
    if not (winget() is not None if _has_winget is None else _has_winget):
        return _("winget isn't on this PC, so the app can't install FFmpeg. Get it "
                 "from ffmpeg.org instead.")
    return ""


def fix(force: bool = False, progress: Callable[[], None] | None = None) -> Health:
    """Get FFmpeg, or install it again over one that won't start (or, with ``force``,
    over a working one), then check it runs. Returns the new Health; raises GetError
    with words for the user. Never on the UI thread."""
    with _fixing:
        before = check()
        if before.state == OK and not force:
            return before            # fixed meanwhile (the other button, the installer)
        # --force: winget may count a deleted or broken one as installed and skip it;
        # with nothing there it's a plain install
        get(progress, force=True)
        after = check()
        if after.state != OK:
            # it still won't start: take it off first, then install it fresh
            _winget(["uninstall", "--id", PACKAGE, "--exact", "--silent",
                     "--disable-interactivity", "--accept-source-agreements"])
            get(force=True)
            after = check()
        if after.state == OK:
            return after
        raise GetError(_("FFmpeg was installed but still won't start ({error}).",
                         error=after.why or _("no reason given")))


def winget() -> str | None:
    """winget.exe, where the installer looks for it (installer/OnionBoard.iss)."""
    local = os.environ.get("LOCALAPPDATA")
    if local and (Path(local) / "Microsoft" / "WindowsApps" / "winget.exe").is_file():
        return str(Path(local) / "Microsoft" / "WindowsApps" / "winget.exe")
    return shutil.which("winget")


def _last_line(out: str) -> str:
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def _winget(args: list[str]) -> subprocess.CompletedProcess:
    """winget with ``args``, hidden; raises GetError with words for the user."""
    exe = winget()
    if exe is None:
        raise GetError(why_cant_fix())
    try:
        return subprocess.run([exe, *args], capture_output=True, timeout=TIMEOUT_S,
                              stdin=subprocess.DEVNULL,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise GetError(_("winget took longer than {seconds} seconds.",
                         seconds=int(TIMEOUT_S))) from None
    except OSError as e:
        raise GetError(_("Couldn't run winget ({error}).", error=e)) from e


def get(progress: Callable[[], None] | None = None, force: bool = False) -> str:
    """Install FFmpeg with winget and return ffmpeg.exe's path. Raises GetError with words
    for the user. ``progress`` (called once, just before the wait) is for the UI.
    ``force`` installs it again over what's there (one that won't start)."""
    if net.offline() or not net.allowed(FEATURE):
        raise GetError(net.off_message(FEATURE))
    if winget() is None:
        raise GetError(why_cant_fix())
    found = library._ffmpeg()
    if found is not None and not force:  # it arrived meanwhile (another click, the installer)
        return found
    if progress is not None:
        progress()
    p = _winget(["install", "--id", PACKAGE, "--exact", "--silent",
                 "--disable-interactivity", "--accept-package-agreements",
                 "--accept-source-agreements", *(["--force"] if force else [])])
    found = library._ffmpeg()
    if found:                            # winget's WinGet\Links shim is found without a restart
        return found
    out = ((p.stdout or b"").decode(errors="ignore") + "\n"
           + (p.stderr or b"").decode(errors="ignore"))
    log.info("winget couldn't install %s (rc=%s): %s", PACKAGE, p.returncode, out.strip())
    raise GetError(_("winget couldn't install FFmpeg (it said: {error}).",
                     error=_last_line(out) or _("no reason given")))
