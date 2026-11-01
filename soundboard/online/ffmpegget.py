"""FFmpeg: checking it works, and getting or repairing it from the app.

M4A, AAC and video files only decode through FFmpeg, pad pictures come out of video
files with it, and "Also save the video" needs it to join a video to its sound. The
installer offers it once; someone who left that box unticked, or whose copy broke, had
no way to fix it. So the app checks it at every start (MainWindow.check_ffmpeg), gets
it by itself when it's missing or won't start, and Settings > Data & quality always
shows how it is.

Getting it tries, in turn, until one works (fix):

1. winget, the package manager Windows 10/11 ships: the installer's own install of the
   Gyan.FFmpeg.Essentials package, then with ``--force`` (winget can count a deleted or
   broken copy as installed), then uninstalled and installed fresh. winget downloads
   from Microsoft's package source itself and can't go through the app's proxy or Tor,
   so it's skipped when Connection is set to either.
2. The app's own copy: a pinned essentials build (PINNED below, from the
   GyanD/codexffmpeg releases), downloaded through net.urlopen
   (so it follows Connection), checked against its SHA-256 before anything is unpacked,
   tried a few times on each of two sources, and unpacked into
   %APPDATA%\\OnionBoard\\ffmpeg\\bin, which library._ffmpeg looks in first.

net's "ffmpeg_download" switch and Offline mode decide whether the app goes online for
it at all.

To move to a newer FFmpeg: choose an essentials zip available from both URLS, and
check that the builder's published SHA-256 and GitHub's release asset digest match
(scripts/pinbump/ffmpeg.py does this weekly and opens the PR itself).
Older releases may remain on GitHub after the builder removes its own copy.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from soundboard.core import errors
from soundboard.sounds import library
from soundboard.online import net
from soundboard.i18n import _

log = logging.getLogger(__name__)

PACKAGE = "Gyan.FFmpeg.Essentials"   # the package the installer adds (installer/OnionBoard.iss)
FEATURE = "ffmpeg_download"          # net's switch for this download
TIMEOUT_S = 900.0                    # winget fetches about 100 MB; a stuck one is cut here
CHECK_TIMEOUT_S = 60.0               # `ffmpeg -version` answers in well under a second,
                                     # but the first run of a just-installed copy (a
                                     # 100 MB exe) waits for the virus scan, on a PC
                                     # still busy with the app's own first start

# the app's own copy (step 2): a release available on both GitHub and the builder's site
VERSION = "9.0.2"
ZIP = f"ffmpeg-{VERSION}-essentials_build.zip"
SHA256 = "60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba"
URLS = (f"https://github.com/GyanD/codexffmpeg/releases/download/{VERSION}/{ZIP}",
        f"https://www.gyan.dev/ffmpeg/builds/packages/{ZIP}")   # the builder's own site
MAX_BYTES = 200_000_000             # the zip is 115 MB; anything far bigger isn't it
CHUNK = 256 * 1024
DOWNLOAD_TIMEOUT_S = 60.0           # with no bytes arriving for this long
TRIES = 3                           # per source
RETRY_WAIT_S = (2.0, 6.0)           # before the 2nd and 3rd try
# member in the zip -> where it goes in the bin folder
KEEP = {f"ffmpeg-{VERSION}-essentials_build/bin/ffmpeg.exe": "ffmpeg.exe",
        f"ffmpeg-{VERSION}-essentials_build/bin/ffprobe.exe": "ffprobe.exe",
        f"ffmpeg-{VERSION}-essentials_build/LICENSE": "LICENSE.txt"}

OK, MISSING, BROKEN = "ok", "missing", "broken"
# sound files only FFmpeg can read (libsndfile reads the rest of library.AUDIO_EXTS)
NEEDS_FFMPEG = {".m4a", ".aac", ".wma", ".webm", ".mp4", ".mkv", ".mov"}


class GetError(Exception):
    """FFmpeg couldn't be got or repaired; the message is fit to show the user. `fault`:
    which step failed and how, as short words and numbers for the usage count, one per
    step tried, spaces between (`winget-exit-2316632107 own-http-403`), never the message."""

    def __init__(self, text: str = "", fault: str = ""):
        super().__init__(text)
        self.fault = fault


class Stopped(GetError):
    """Stop was pressed while it downloaded."""


class SwitchedOff(GetError):
    """Its switch is off (or Offline mode is on): nothing was sent, and trying again
    won't change that."""


@dataclass(frozen=True)
class Health:
    """What check() found: ``state`` is OK, MISSING or BROKEN; ``version`` ("7.1") when
    it runs; ``why`` (for the user) when it's broken; ``slow`` when it only didn't
    answer in time (it may yet work: not proof it's broken); ``fault`` why it's broken
    for the usage count (`gone`, `err-193`, `exit-3221225781`), never a path."""
    state: str
    version: str = ""
    path: str = ""
    why: str = ""
    slow: bool = False
    fault: str = ""


_last: Health | None = None   # check()'s latest answer, for the UI thread to show
_fixing = threading.Lock()    # one fix at a time (automatic, the bar's Fix it, Settings')
_has_winget: bool | None = None   # winget() at the last check (None: not looked yet)


def last() -> Health | None:
    """The latest check() (None: not checked yet). Cheap: safe on the UI thread."""
    return _last


def busy() -> bool:
    """A fix is going (any of them)."""
    return _fixing.locked()


def own_dir() -> Path:
    """The app's own FFmpeg: %APPDATA%\\OnionBoard\\ffmpeg\\bin."""
    return library.APP_DIR / "ffmpeg" / "bin"


# --------------------------------------------------------------------------- check

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


_early: threading.Thread | None = None   # start_check's, behind the loading screen


def start_check() -> None:
    """Tidy up after a fix cut short, then check FFmpeg, on a worker while the loading
    screen is up (app.py): its answer is ready when the window is, and nothing waits
    for it."""
    global _early

    def run():
        tidy()
        check()

    _early = threading.Thread(target=run, daemon=True, name="ffmpeg-early-check")
    _early.start()


TIDY_AFTER_S = 600   # a fix unpacks and swaps in seconds: older leftovers are a past one's


def tidy() -> None:
    """Clear what the app's own download left when it was cut short (the app ended
    mid-fix: End task, a crash, the power): the half-downloaded zip, a half-unpacked
    bin.partial, and bin.old, put back first when the swap stopped before the new copy
    was in place. Left alone, they stay for good once FFmpeg is found elsewhere
    (winget, PATH): the zip is up to 115 MB. Skipped while a fix is going; only ones
    older than TIDY_AFTER_S."""
    if not _fixing.acquire(blocking=False):
        return
    try:
        dest = own_dir()
        cutoff = time.time() - TIDY_AFTER_S
        old = dest.with_name(dest.name + ".old")
        if old.is_dir() and old.stat().st_mtime < cutoff:
            if not dest.exists():
                old.rename(dest)
                log.info("put back the FFmpeg a fix had moved aside")
            else:
                shutil.rmtree(old, ignore_errors=True)
        for left in (dest.with_name(dest.name + ".partial"), dest.parent / (ZIP + ".partial")):
            if left.exists() and left.stat().st_mtime < cutoff:
                log.info("removing %s, left by a fix that was cut short", left.name)
                if left.is_dir():
                    shutil.rmtree(left, ignore_errors=True)
                else:
                    left.unlink()
    except OSError:
        log.warning("couldn't tidy the ffmpeg folder", exc_info=True)
    finally:
        _fixing.release()


def answer() -> Health:
    """start_check's answer (waiting for it if it's still going), else a new check.
    Never on the UI thread."""
    t = _early
    if t is not None:
        t.join(CHECK_TIMEOUT_S + 2)
        if _last is not None and not t.is_alive():
            return _last
    return check()


def _check() -> Health:
    exe = library._ffmpeg()
    if exe is None:
        if _leftovers():
            return Health(BROKEN, why=_("some of its files are gone"), fault="gone")
        return Health(MISSING)
    try:
        p = _run_version(exe)
    except subprocess.TimeoutExpired:
        return Health(BROKEN, path=exe, why=_("it didn't answer in {seconds} seconds",
                                              seconds=int(CHECK_TIMEOUT_S)), slow=True,
                      fault="slow")
    except OSError as e:   # not a program, the wrong kind for this PC, a dead link
        log.info("FFmpeg won't start: %s", e)
        return Health(BROKEN, path=exe, why=_("Windows won't start it"),
                      fault=_os_fault("", e))
    out = (p.stdout or b"").decode(errors="ignore")
    if p.returncode != 0:
        log.info("ffmpeg -version gave %s: %s", p.returncode,
                 (p.stderr or b"").decode(errors="ignore").strip())
        return Health(BROKEN, path=exe, why=_("it stops with an error"),
                      fault=f"exit-{p.returncode & 0xFFFFFFFF}")
    return Health(OK, _version(out), exe)


def _os_fault(step: str, e: BaseException) -> str:
    """`step` and an OSError's Windows error (or errno) number: `own-err-5`, `err-193`."""
    num = getattr(e, "winerror", None) or getattr(e, "errno", None)
    reason = getattr(e, "reason", None)   # a URLError's own OSError
    if num is None and isinstance(reason, OSError):
        num = getattr(reason, "winerror", None) or getattr(reason, "errno", None)
    head = f"{step}-" if step else ""
    return f"{head}err-{num}" if isinstance(num, int) else f"{head}{type(e).__name__}"


def why_not() -> str:
    """Why the app may not go online for FFmpeg (words for the user), or ""."""
    if net.offline() or not net.allowed(FEATURE):
        return net.off_message(FEATURE)
    return ""


# --------------------------------------------------------------------------- winget

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
        raise GetError(_("winget isn't on this PC."), "winget-missing")
    try:
        return subprocess.run([exe, *args], capture_output=True, timeout=TIMEOUT_S,
                              stdin=subprocess.DEVNULL,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise GetError(_("winget took longer than {seconds} seconds.",
                         seconds=int(TIMEOUT_S)), "winget-timeout") from None
    except OSError as e:
        raise GetError(_("Couldn't run winget ({error}).", error=e),
                       _os_fault("winget", e)) from e


def get(progress: Callable[[], None] | None = None, force: bool = False) -> str:
    """Install FFmpeg with winget and return ffmpeg.exe's path. Raises GetError with words
    for the user. ``progress`` (called once, just before the wait) is for the UI.
    ``force`` installs it again over what's there (one that won't start)."""
    if why_not():
        raise GetError(why_not())
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
                     error=_last_line(out) or _("no reason given")),
                   f"winget-exit-{p.returncode & 0xFFFFFFFF}")


def _with_winget() -> Health:
    """Steps 1: install, then uninstall + install. The Health after; raises GetError."""
    get(force=True)   # --force: with nothing there it's a plain install
    after = check()
    if after.state != OK:
        log.info("FFmpeg still won't start after winget --force: uninstalling first")
        _winget(["uninstall", "--id", PACKAGE, "--exact", "--silent",
                 "--disable-interactivity", "--accept-source-agreements"])
        get(force=True)
        after = check()
    return after


# --------------------------------------------------------------------------- own copy

def _download_once(url: str, to: Path, progress, stop) -> None:
    """``url`` into the file ``to``, checked against SHA256. Raises GetError."""
    host = urllib.parse.urlsplit(url).hostname
    req = urllib.request.Request(url, headers={"User-Agent": "OnionBoard"})

    def check():
        if stop is not None and stop.is_set():
            raise Stopped(_("Stopped."))

    try:
        with net.urlopen(req, timeout=DOWNLOAD_TIMEOUT_S, feature=FEATURE) as r, \
                open(to, "wb") as f:
            got = net.read_capped(r, f, MAX_BYTES, chunk=CHUNK, progress=progress,
                                  check=check)
    except net.TooBig as e:
        if e.listed:
            raise GetError(_("The download is {mb} MB, far bigger than FFmpeg: not "
                             "taking it.", mb=f"{e.listed / 1e6:.0f}"),
                           "own-too-big") from None
        raise GetError(_("The download kept going far past FFmpeg's size: "
                         "not taking it."), "own-too-big") from None
    except net.FeatureOff as e:   # switched off, nothing sent
        raise SwitchedOff(errors.plain(e)) from None
    except net.ProxyError as e:
        raise GetError(errors.plain(e), "own-proxy") from None
    except urllib.error.HTTPError as e:
        raise GetError(_("{host} said {error}.", host=host,
                         error=f"{e.code} {e.reason}"), f"own-http-{e.code}") from None
    except (urllib.error.URLError, OSError) as e:
        why = getattr(e, "reason", None) or e
        raise GetError(_("Couldn't reach {host} ({error}).", host=host, error=why),
                       _os_fault("own", e)) from None
    if got != SHA256:
        log.warning("ffmpeg download from %s: SHA-256 %s, expected %s", host, got, SHA256)
        raise GetError(_("The download isn't the FFmpeg it should be (its checksum doesn't "
                         "match), so it wasn't used. It was cut short, or something "
                         "between you and the site changed it."), "own-checksum")


def download(to: Path, progress=None, stop: threading.Event | None = None) -> None:
    """The zip into ``to``: each source in turn, a few tries each (a dropped connection,
    a busy server). Raises GetError with each source's last reason (GitHub down and the
    builder's site missing the file are two problems, not one); Stopped and SwitchedOff
    at once."""
    why: dict[str, str] = {}
    fault = ""
    for url in URLS:
        for n in range(TRIES):
            if n:
                wait = RETRY_WAIT_S[min(n - 1, len(RETRY_WAIT_S) - 1)]
                if stop is not None and stop.wait(wait):
                    raise Stopped(_("Stopped."))
                if stop is None:
                    time.sleep(wait)
            try:
                _download_once(url, to, progress, stop)
                return
            except (Stopped, SwitchedOff):
                raise
            except GetError as e:
                log.info("ffmpeg download from %s, try %d: %s", url, n + 1, e)
                why[url] = str(e)
                fault = e.fault or fault
    reasons = list(dict.fromkeys(why.values()))   # the same words from both: say it once
    raise GetError(" ".join(r if r.endswith((".", "!", "?")) else r + "."
                            for r in reasons), fault)


RENAME_TRIES = 20   # x RENAME_WAIT_S: how long a folder that's in use gets to come free
RENAME_WAIT_S = 0.5


def _rename(src: Path, to: Path) -> None:
    """src.rename(to), tried again for a few seconds when Windows denies it: an antivirus
    scanning the new ffmpeg.exe (or a check still running the old one) holds it open."""
    for n in range(RENAME_TRIES):
        try:
            src.rename(to)
            return
        except PermissionError:
            if n == RENAME_TRIES - 1:
                raise
            time.sleep(RENAME_WAIT_S)


def unpack(zip_path: Path, dest: Path | None = None) -> Path:
    """The kept files from a checked zip into ``dest`` (the bin folder by default),
    replacing what's there. Only the named members are read, each written to a fixed
    path, so nothing in the zip picks where a file goes."""
    dest = dest or own_dir()
    tmp = dest.with_name(dest.name + ".partial")
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        tmp.mkdir(parents=True)
        with zipfile.ZipFile(zip_path) as z:
            for name, rel in KEEP.items():
                try:
                    data = z.read(name)
                except KeyError:
                    raise GetError(_("{name} is missing from {file}", name=name,
                                     file=ZIP), "own-unpack-missing") from None
                (tmp / rel).write_bytes(data)
        old = dest.with_name(dest.name + ".old")
        shutil.rmtree(old, ignore_errors=True)
        if dest.exists():
            _rename(dest, old)   # fails while an ffmpeg.exe in it runs
        try:
            _rename(tmp, dest)
        except OSError:
            if old.exists() and not dest.exists():
                _rename(old, dest)   # put the old copy back
            raise
        shutil.rmtree(old, ignore_errors=True)
    except GetError:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    except (OSError, zipfile.BadZipFile) as e:
        shutil.rmtree(tmp, ignore_errors=True)
        raise GetError(_("Couldn't unpack FFmpeg into {folder} ({error}). An antivirus may "
                         "have blocked ffmpeg.exe.", folder=dest,
                         error=getattr(e, "strerror", "") or e),
                       _os_fault("own-unpack", e)) from None
    return dest


def _own_copy(progress, stop) -> Health:
    """Step 2: download, check and unpack the app's own copy. Raises GetError."""
    log.info("downloading FFmpeg %s for the app (%s)", VERSION, net.describe(where=False))
    folder = own_dir().parent
    folder.mkdir(parents=True, exist_ok=True)
    part = folder / (ZIP + ".partial")
    try:
        download(part, progress, stop)
        unpack(part)
    finally:
        try:
            part.unlink()
        except OSError:
            pass
    log.info("FFmpeg %s unpacked into the ffmpeg\\bin folder", VERSION)
    return check()


def is_own(path: str) -> bool:
    """`path` is the app's own copy (own_dir), not winget's or one on PATH."""
    try:
        return Path(path).resolve().parent == own_dir().resolve()
    except OSError:
        return False


def update_own() -> Health | None:
    """The app's own copy follows the app: one older than VERSION (the app was updated)
    is replaced by this release's, checked against SHA256 like any download. A copy
    from winget or elsewhere is left alone. None: nothing to do. Raises GetError.
    Never on the UI thread."""
    if why_not():
        return None
    with _fixing:
        h = check()
        if h.state != OK or not is_own(h.path) or h.version == VERSION:
            return None
        log.info("the app's FFmpeg is %s, this version of the app uses %s: updating",
                 h.version, VERSION)
        return _own_copy(None, None)


# --------------------------------------------------------------------------- fix

def fix(force: bool = False, progress: Callable[[int, int], None] | None = None,
        stop: threading.Event | None = None) -> Health:
    """Get FFmpeg, or repair one that won't start (``force``: reinstall a working one),
    trying winget and then the app's own copy until it works. Returns the new Health;
    raises GetError (Stopped when ``stop`` is set) with words for the user.
    ``progress(done, total)`` follows the app's own download. Never on the UI thread."""
    with _fixing:
        before = check()
        if before.state == OK and not force:
            return before            # fixed meanwhile (the other button, the installer)
        if why_not():
            raise GetError(why_not(), "off")
        reasons: list[str] = []
        faults: list[str] = []   # each step's, for the usage count: "winget-… own-…"
        # winget can't go through a proxy or Tor: then only the app's own download
        if winget() is not None and net.mode() == net.DIRECT:
            try:
                after = _with_winget()
                if after.state == OK:
                    return after
                reasons.append(after.why)
                faults.append(f"winget-still-{after.fault or 'broken'}")
            except GetError as e:
                log.info("winget couldn't fix FFmpeg: %s", e)
                reasons.append(str(e))
                faults.append(e.fault or "winget-other")
        if stop is not None and stop.is_set():   # (winget itself can't be stopped midway)
            raise Stopped(_("Stopped."))
        try:
            after = _own_copy(progress, stop)
        except (Stopped, SwitchedOff):
            raise
        except GetError as e:
            e.fault = " ".join([*faults, e.fault or "own-other"])
            raise
        if after.state == OK:
            return after
        raise GetError(_("FFmpeg was installed but still won't start ({error}).",
                         error=after.why or (reasons[-1] if reasons else "")
                         or _("no reason given")),
                       " ".join([*faults, f"own-still-{after.fault or 'broken'}"]))
