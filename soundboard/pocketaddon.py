"""Onion Pocket, the "remote" add-on that puts your pads on your phone: its newest
release, downloading it and installing it into %APPDATA%\\OnionBoard\\modules\\onion-pocket.

The same path as Onion Watch (soundboard.watchaddon): nothing runs until the *Get
Onion Pocket* button on Settings → Remote is clicked; the zip comes only from the
project's own github.com/…/releases/download/ link, over HTTPS, and is kept only if it
matches the SHA-256 GitHub lists for it (updates.fetch); then it's checked and unpacked
(modules.install_zip) and loaded (MainWindow.load_remote_addon).

Once it's in, Settings → Remote asks GitHub (at most once an hour, see check_update)
whether a newer one is out, and if so puts *Update Onion Pocket to X* on its card: the
same download, then the running copy is stopped and the new one started in its place,
with its settings (Config.remote_addons["onion-pocket"]) untouched.

Onion Pocket is optional: if any of this fails (offline, no release yet, a bad zip),
Settings just leaves its card out, or its update button. Nothing here raises past
`get()` / `check_update()`.

ONIONBOARD_ONION_POCKET_ZIP=<path to an OnionPocket-module.zip> uses that file instead
of GitHub, to try a build before it's released. "Get and update add-ons" switched off
in Settings > Privacy & security stops all of it (net.FeatureOff).
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

NAME = "Onion Pocket"
REPO = "Onion-Alien/onion-pocket"
PAGE = f"https://github.com/{REPO}"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES = f"{PAGE}/releases/latest"
DOWNLOADS = f"{PAGE}/releases/download/"     # the only place the add-on is fetched from
ASSET = "OnionPocket-module.zip"
MODULE_ID = "onion-pocket"
KIND = "remote"
LOCAL_ENV = "ONIONBOARD_ONION_POCKET_ZIP"
MAX_SIZE = 5 << 20       # the zip is ~40 KB
FEATURE = "addons"       # its switch in Settings > Privacy & security (soundboard.net)


@dataclass
class Offer:
    """An Onion Pocket there is to install."""
    version: str
    url: str = ""          # its zip on GitHub
    sha256: str = ""       # ...and that file's SHA-256, as GitHub lists it
    size: int = 0
    page: str = RELEASES   # its release page
    local: Path | None = None   # a zip on this PC instead (LOCAL_ENV)


def local_zip() -> Path | None:
    v = os.environ.get(LOCAL_ENV, "").strip().strip('"')
    return Path(v) if v else None


def offered() -> bool:
    """Whether Settings should offer *Get Onion Pocket*: add-ons allowed (or a local
    zip to try). Asks nothing over the network."""
    return local_zip() is not None or net.allowed(FEATURE)


def installed(dirs: list[Path] | None = None) -> ModuleInfo | None:
    return next((m for m in modules.discover(dirs) if m.id == MODULE_ID), None)


def _zip_version(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as z:
            d = json.loads(z.read(f"{MODULE_ID}/module.json").decode("utf-8-sig"))
        return str(d.get("version", "?"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, AttributeError):
        return "?"


def latest(cancelled: Callable[[], bool] | None = None) -> Offer | None:
    """The newest Onion Pocket to install, or None when its latest release has no zip
    the app can check. Raises OSError / ValueError when GitHub can't be asked, and
    net.FeatureOff when add-ons may not go online. Call off the UI thread."""
    lz = local_zip()
    if lz is not None:
        return Offer(_zip_version(lz), page=str(lz), local=lz)
    data = updates._get(API, FEATURE, cancelled)
    ver = updates.parse_version(str(data.get("tag_name") or data.get("name") or ""))
    if ver is None:
        return None
    url, sha, size = updates.find_asset(data, ASSET, (DOWNLOADS,))
    if not url:
        return None
    page = str(data.get("html_url") or RELEASES)
    if not page.startswith(PAGE + "/"):
        page = RELEASES     # only ever open the project's own page
    return Offer(".".join(map(str, ver)), url, sha, size, page)


def fetch(offer: Offer, progress: Callable[[int, int], None] | None = None,
          cancelled: Callable[[], bool] | None = None) -> Path:
    """The offer's zip on this PC: downloaded into the updates folder and checked
    against its SHA-256. Raises updates.UpdateError. Call off the UI thread."""
    if offer.local is not None:
        if not offer.local.is_file():
            raise updates.UpdateError(f"{offer.local} isn't there ({LOCAL_ENV})")
        return offer.local
    dest = updates.UPDATES_DIR / f"OnionPocket-module-{offer.version}.zip"
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


def get(base: Path | None = None, progress: Callable[[int, int], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
        offer: Offer | None = None) -> ModuleInfo | None:
    """Download and install the newest Onion Pocket (or `offer`). The installed
    add-on's info, or None when anything went wrong (logged, never raised). Call off
    the UI thread."""
    try:
        offer = offer or latest(cancelled)
        if offer is None:
            raise updates.UpdateError("no Onion Pocket release the app can check")
        return install(fetch(offer, progress, cancelled), base)
    except Exception as e:  # noqa: BLE001 - optional: any failure just means no card
        log.info("getting Onion Pocket failed: %s", e)
        return None


def check_update(info: ModuleInfo | None) -> Offer | None:
    """A newer Onion Pocket than `info` (the running copy), or None: also when there's
    none running, add-ons may not go online, or GitHub can't be asked (logged, not
    raised). Call off the UI thread."""
    if info is None or (local_zip() is None and not net.allowed(FEATURE)):
        return None
    try:
        offer = latest()
    except Exception as e:  # noqa: BLE001 - offline, rate-limited, switched off…
        log.info("Onion Pocket update check failed: %s", e)
        return None
    if offer is not None and updates.newer(offer.version, info.version):
        log.info("a newer Onion Pocket is out: %s", offer.version)
        return offer
    return None
