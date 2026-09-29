"""Is there a newer Onion Board, and installing it. The app asks the project's latest
GitHub release once a day (Settings → General; on unless unticked), plus a "Check now"
button.

A newer version is only announced. Nothing is downloaded until the user presses
*Update now*: then the release's OnionBoardSetup.exe is fetched from the project's own
GitHub release, checked against the SHA-256 GitHub lists for it, and run silently over
the installed copy once they press *Restart to update* (the app closes, the installer
opens it again). A copy running from source is never updated: it only says what's new.
The requests carry no data about the user beyond what any HTTPS request does (see
SECURITY.md)."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from soundboard import __version__
from soundboard.library import APP_DIR

log = logging.getLogger(__name__)

REPO = "Onion-Alien/onionboard"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES = f"https://github.com/{REPO}/releases/latest"
ASSET = "OnionBoardSetup.exe"
# the only place an installer is ever fetched from (GitHub then redirects to its CDN)
DOWNLOADS = f"https://github.com/{REPO}/releases/download/"
UPDATES_DIR = APP_DIR / "updates"
INSTALL_LOG = UPDATES_DIR / "install.log"
EVERY_S = 24 * 3600
LIMIT = 1 << 20          # the API's answer is a few KB
MAX_SIZE = 400 << 20     # the installer is ~140 MB
CHUNK = 1 << 20
SHA_RE = re.compile(r"[0-9a-f]{64}")


class UpdateError(Exception):
    """An update that couldn't be downloaded: the message is shown to the user as is."""


@dataclass
class Release:
    version: str      # "1.0.1"
    url: str          # its page on GitHub
    notes: str = ""   # the first lines of its description
    asset_url: str = ""   # its OnionBoardSetup.exe; "" = nothing to install
    sha256: str = ""      # that file's SHA-256 (lowercase hex), as GitHub lists it
    size: int = 0


def parse_version(text: str) -> tuple[int, ...] | None:
    """'v1.0.1' / '1.0.1' / 'Onion Board 1.2' -> (1, 0, 1); None if there's no version."""
    m = re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", text or "")
    if not m:
        return None
    return tuple(int(g or 0) for g in m.groups())


def newer(latest: str, current: str = __version__) -> bool:
    a, b = parse_version(latest), parse_version(current)
    return a is not None and b is not None and a > b


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={
        "User-Agent": f"OnionBoard/{__version__} (update check)",
        "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read(LIMIT).decode("utf-8"))


def _installer(data: dict) -> tuple[str, str, int]:
    """The release's OnionBoardSetup.exe: (download link, SHA-256, size), or blanks
    when it has none from this project, or no checksum to hold it to. The checksum is
    GitHub's own `digest` for the file; releases made before GitHub listed one carry it
    in their notes ("SHA-256: `…`")."""
    for a in data.get("assets") or []:
        if not isinstance(a, dict) or a.get("name") != ASSET:
            continue
        url = str(a.get("browser_download_url") or "")
        if not url.startswith(DOWNLOADS):
            return "", "", 0
        digest = str(a.get("digest") or "").lower()
        sha = digest.removeprefix("sha256:") if digest.startswith("sha256:") else ""
        if not SHA_RE.fullmatch(sha):
            m = re.search(r"SHA-256:\W*([0-9a-fA-F]{64})\b", str(data.get("body") or ""))
            sha = m.group(1).lower() if m else ""
        if not sha:
            return "", "", 0
        size = a.get("size")
        return url, sha, size if isinstance(size, int) and size > 0 else 0
    return "", "", 0


def latest() -> Release | None:
    """The newest published release (drafts and pre-releases aren't 'latest')."""
    data = _get(API)
    tag = str(data.get("tag_name") or data.get("name") or "")
    ver = parse_version(tag)
    if ver is None:
        return None
    url = str(data.get("html_url") or RELEASES)
    if not url.startswith("https://github.com/"):
        url = RELEASES   # only ever open the project's own page
    notes = "\n".join(str(data.get("body") or "").strip().splitlines()[:8])
    return Release(".".join(map(str, ver)), url, notes, *_installer(data))


def check(cfg, force: bool = False) -> Release | None:
    """A newer release than this one, or None. Without `force` it only asks if the
    box is ticked, once a day, and stays quiet about a version they skipped.
    Network errors are logged and read as 'nothing new'. Call off the UI thread."""
    if not force and (not cfg.update_check
                      or time.time() - cfg.update_checked < EVERY_S):
        return None
    try:
        rel = latest()
    except Exception as e:  # noqa: BLE001 - offline, rate-limited, GitHub down…
        log.info("update check failed: %s", e)
        if force:
            raise
        return None
    cfg.update_checked = time.time()
    if rel is None or not newer(rel.version):
        return None
    if not force and rel.version == cfg.update_skip:
        return None
    log.info("a newer version is out: %s", rel.version)
    return rel


# --------------------------------------------------------------------------- installing

def can_install() -> bool:
    """Only the installed (frozen) app updates itself; from source it's `git pull`."""
    return bool(getattr(sys, "frozen", False)) and sys.platform == "win32"


def installer_path(rel: Release) -> Path:
    return UPDATES_DIR / f"OnionBoardSetup-{rel.version}.exe"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _open(url: str):
    req = urllib.request.Request(url, headers={
        "User-Agent": f"OnionBoard/{__version__} (update download)"})
    return urllib.request.urlopen(req, timeout=30)


def download(rel: Release, progress: Callable[[int, int], None] | None = None,
             cancelled: Callable[[], bool] | None = None) -> Path:
    """Fetch the release's installer into UPDATES_DIR and prove it's the file GitHub
    lists (SHA-256); its path. `progress(done, total)` is called as it arrives. Raises
    UpdateError with a message for the user. Call off the UI thread."""
    if not rel.asset_url.startswith(DOWNLOADS) or not SHA_RE.fullmatch(rel.sha256):
        raise UpdateError("this release has no installer the app can check, "
                          "so it can only be downloaded from its page")
    dest = installer_path(rel)
    if dest.is_file() and _sha256(dest) == rel.sha256:
        return dest   # downloaded earlier, never installed
    UPDATES_DIR.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    h = hashlib.sha256()
    done = 0
    try:
        with _open(rel.asset_url) as r, open(part, "wb") as f:
            if not r.geturl().startswith("https://"):
                raise UpdateError("the download was redirected off HTTPS")
            total = int(r.headers.get("Content-Length") or rel.size or 0)
            if total > MAX_SIZE:
                raise UpdateError("the download is far bigger than an installer")
            while chunk := r.read(CHUNK):
                if cancelled is not None and cancelled():
                    raise UpdateError("cancelled")
                done += len(chunk)
                if done > MAX_SIZE:
                    raise UpdateError("the download is far bigger than an installer")
                h.update(chunk)
                f.write(chunk)
                if progress is not None:
                    progress(done, total)
        if h.hexdigest() != rel.sha256:
            log.warning("update %s: SHA-256 %s, expected %s", rel.version,
                        h.hexdigest(), rel.sha256)
            raise UpdateError("the downloaded file isn't the one GitHub lists "
                              "(its checksum doesn't match), so it wasn't kept")
        os.replace(part, dest)
    except UpdateError:
        part.unlink(missing_ok=True)
        raise
    except OSError as e:   # offline, disk full, connection dropped…
        part.unlink(missing_ok=True)
        raise UpdateError(f"the download failed ({e})") from e
    log.info("downloaded update %s (%d bytes, SHA-256 checked)", rel.version, done)
    return dest


def installer_args(path: Path) -> list[str]:
    """Run the installer over this copy with no questions, keeping the user's
    shortcut choice but never the one-off extras (the virtual cable would ask Windows
    for permission, live voice downloads ~300 MB), then open the app again
    (/RELAUNCH, see installer/OnionBoard.iss)."""
    return [str(path), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS",
            "/MERGETASKS=!vbcable,!ffmpeg,!livevoice", "/RELAUNCH=1",
            f"/LOG={INSTALL_LOG}"]


def start_install(path: Path) -> None:
    """Start the installer on its own; the caller then quits the app so it can
    replace the files. Raises OSError if it couldn't be started."""
    flags = (getattr(subprocess, "DETACHED_PROCESS", 0)
             | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    subprocess.Popen(installer_args(path), creationflags=flags, close_fds=True,
                     cwd=str(UPDATES_DIR))
    log.info("started the installer for the update: %s", path.name)


def finished(pending: str, current: str = __version__) -> bool:
    """After an update was started for version `pending`: did it land?"""
    a, b = parse_version(pending), parse_version(current)
    return a is not None and b is not None and b >= a


def cleanup() -> None:
    """Remove downloaded installers (and half-downloads). One still running, just
    after it reopened the app, is locked: it goes next time."""
    for p in UPDATES_DIR.glob("OnionBoardSetup-*"):
        try:
            p.unlink()
        except OSError:
            pass
