"""Onion Watch, the add-on behind the Triggers tab: its newest release, downloading
it and installing it into %APPDATA%\\OnionBoard\\modules\\onion-watch.

Nothing here runs until the user asks for it: the tab's *Get Onion Watch* button,
or its *Update* button once it's installed and the app's own daily update check
(only while "Tell me when a new version is out" is ticked) found a newer one. The
file is taken only from the project's own github.com/…/releases/download/ link,
over HTTPS, and kept only if it matches the SHA-256 GitHub lists for it
(updates.fetch). Then it's checked and unpacked (modules.install_zip) and the
Triggers tab loads it.

ONIONBOARD_ONION_WATCH_ZIP=<path to an OnionWatch-module.zip> makes both use that
file instead of GitHub, to try a build before it's released.

"Get and update add-ons" switched off in Settings > Privacy & security stops all of
it (net.FeatureOff); the daily check then skips itself without a word.
"""
from __future__ import annotations

import json
import logging
import os
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from soundboard import modules, net, updates
from soundboard.modules import ModuleInfo

log = logging.getLogger(__name__)

REPO = "Onion-Alien/onion-watch"
PAGE = f"https://github.com/{REPO}"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES = f"{PAGE}/releases/latest"
DOWNLOADS = f"{PAGE}/releases/download/"     # the only place the add-on is fetched from
ASSET = "OnionWatch-module.zip"
MODULE_ID = "onion-watch"
KIND = "triggers"
LOCAL_ENV = "ONIONBOARD_ONION_WATCH_ZIP"
MAX_SIZE = 20 << 20      # the zip is ~70 KB
FEATURE = "addons"       # its switch in Settings > Privacy & security (soundboard.net)


@dataclass
class Offer:
    """An Onion Watch there is to install."""
    version: str
    url: str = ""          # its zip on GitHub
    sha256: str = ""       # ...and that file's SHA-256, as GitHub lists it
    size: int = 0
    page: str = RELEASES   # its release page
    notes: str = ""
    local: Path | None = None   # a zip on this PC instead (LOCAL_ENV)


def local_zip() -> Path | None:
    v = os.environ.get(LOCAL_ENV, "").strip().strip('"')
    return Path(v) if v else None


def installed(dirs: list[Path] | None = None) -> ModuleInfo | None:
    """The Onion Watch add-on as installed, or None."""
    return next((m for m in modules.discover(dirs) if m.id == MODULE_ID), None)


def _zip_version(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as z:
            d = json.loads(z.read(f"{MODULE_ID}/module.json").decode("utf-8-sig"))
        return str(d.get("version", "?"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, AttributeError):
        return "?"


def latest() -> Offer | None:
    """The newest Onion Watch to install, or None when its latest release has no
    zip the app can check. Raises OSError / ValueError when GitHub can't be asked
    (offline, rate-limited). Call off the UI thread."""
    lz = local_zip()
    if lz is not None:
        return Offer(_zip_version(lz), page=str(lz), local=lz)
    data = updates._get(API, FEATURE)
    ver = updates.parse_version(str(data.get("tag_name") or data.get("name") or ""))
    if ver is None:
        return None
    url, sha, size = updates.find_asset(data, ASSET, (DOWNLOADS,))
    if not url:
        return None
    page = str(data.get("html_url") or RELEASES)
    if not page.startswith(PAGE + "/"):
        page = RELEASES     # only ever open the project's own page
    return Offer(".".join(map(str, ver)), url, sha, size, page,
                 updates.summary(str(data.get("body") or "")))


def fetch(offer: Offer, progress: Callable[[int, int], None] | None = None,
          cancelled: Callable[[], bool] | None = None) -> Path:
    """The offer's zip on this PC: downloaded into the updates folder and checked
    against its SHA-256. Raises updates.UpdateError. Call off the UI thread."""
    if offer.local is not None:
        if not offer.local.is_file():
            raise updates.UpdateError(f"{offer.local} isn't there ({LOCAL_ENV})")
        return offer.local
    dest = updates.UPDATES_DIR / f"OnionWatch-module-{offer.version}.zip"
    return updates.fetch(offer.url, offer.sha256, dest, (DOWNLOADS,), MAX_SIZE, "an add-on",
                         offer.size, progress, cancelled, FEATURE)


def install(path: Path, base: Path | None = None) -> ModuleInfo:
    """Install a fetched zip (modules.install_zip); a downloaded one is deleted
    afterwards, a local one is left where it is. Raises modules.ModuleError."""
    try:
        return modules.install_zip(path, MODULE_ID, KIND, base)
    finally:
        if path.parent == updates.UPDATES_DIR:
            path.unlink(missing_ok=True)


def removable(info: ModuleInfo, base: Path | None = None) -> bool:
    """Whether this copy is the one installed into `base` (the modules folder in
    %APPDATA%), which remove() can take out, rather than one shipped with the app."""
    base = base if base is not None else modules.search_dirs()[0]
    try:
        return info.path.resolve() == (base / MODULE_ID).resolve()
    except OSError:
        return False


def remove(info: ModuleInfo, base: Path | None = None) -> None:
    """Uninstall it (modules.uninstall) and forget its loaded package, so getting it
    again in this run loads the new copy afresh. The triggers and their pictures are
    the board's (Config.screen, the triggers folder) and are kept. Raises
    modules.ModuleError."""
    modules.uninstall(MODULE_ID, base)
    if info.package:
        modules._forget(info.package)


def check_update(dirs: list[Path] | None = None) -> Offer | None:
    """A newer Onion Watch than the one installed, or None (also when it isn't
    installed: then nothing is asked). Errors are logged, not raised. Call off the
    UI thread; the app calls it with its own daily update check."""
    info = installed(dirs)
    if info is None or not net.allowed(FEATURE):   # switched off: skip, silently
        return None
    try:
        offer = latest()
    except Exception as e:  # noqa: BLE001 - offline, rate-limited, still private…
        log.info("Onion Watch update check failed: %s", e)
        return None
    if offer is not None and updates.newer(offer.version, info.version):
        log.info("a newer Onion Watch is out: %s", offer.version)
        return offer
    return None


def friendly(e: Exception) -> str:
    """An error from getting the add-on, as a sentence for the tab."""
    text = str(e) or type(e).__name__
    if isinstance(e, net.FeatureOff):
        return text
    if getattr(e, "code", None) in (502, 503, 504):
        return ("GitHub's download check is temporarily unavailable (gateway error). "
                "Try Get Onion Watch again in a moment.")
    if "404" in text:
        return ("Onion Watch isn't available to download yet (GitHub says it can't find "
                "it). Try again later.")
    if isinstance(e, OSError):          # urllib's errors: offline, DNS, timeouts
        return f"Couldn't reach GitHub ({text}). Check your internet connection."
    return text[:1].upper() + text[1:]
