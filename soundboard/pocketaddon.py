"""Onion Pocket, the "remote" add-on that puts your pads on your phone: its newest
release, downloading it and installing it into %APPDATA%\\OnionBoard\\modules\\onion-pocket.

The same path as Onion Watch (soundboard.watchaddon): nothing runs until the *Get
Onion Pocket* button on Settings → Remote is clicked; the zip comes only from the
project's own github.com/…/releases/download/ link, over HTTPS, and is kept only if it
matches the SHA-256 GitHub lists for it (updates.fetch); then it's checked and unpacked
(modules.install_zip) and loaded (MainWindow.load_remote_addon).

Onion Pocket is optional: if any of this fails (offline, no release yet, a bad zip),
Settings just leaves its card out. Nothing here raises past `get()`.

ONIONBOARD_ONION_POCKET_ZIP=<path to an OnionPocket-module.zip> uses that file instead
of GitHub, to try a build before it's released. "Get and update add-ons" switched off
in Settings > Privacy & security stops all of it (net.FeatureOff).
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path

from soundboard import modules, net, updates
from soundboard.modules import ModuleInfo

log = logging.getLogger(__name__)

NAME = "Onion Pocket"
REPO = "Onion-Alien/onion-pocket"
PAGE = f"https://github.com/{REPO}"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOADS = f"{PAGE}/releases/download/"     # the only place the add-on is fetched from
ASSET = "OnionPocket-module.zip"
MODULE_ID = "onion-pocket"
KIND = "remote"
LOCAL_ENV = "ONIONBOARD_ONION_POCKET_ZIP"
MAX_SIZE = 5 << 20       # the zip is ~40 KB
FEATURE = "addons"       # its switch in Settings > Privacy & security (soundboard.net)


def local_zip() -> Path | None:
    v = os.environ.get(LOCAL_ENV, "").strip().strip('"')
    return Path(v) if v else None


def offered() -> bool:
    """Whether Settings should offer *Get Onion Pocket*: add-ons allowed (or a local
    zip to try). Asks nothing over the network."""
    return local_zip() is not None or net.allowed(FEATURE)


def installed(dirs: list[Path] | None = None) -> ModuleInfo | None:
    return next((m for m in modules.discover(dirs) if m.id == MODULE_ID), None)


def _download(progress: Callable[[int, int], None] | None,
              cancelled: Callable[[], bool] | None) -> Path:
    lz = local_zip()
    if lz is not None:
        if not lz.is_file():
            raise updates.UpdateError(f"{lz} isn't there ({LOCAL_ENV})")
        return lz
    data = updates._get(API, FEATURE, cancelled)
    ver = updates.parse_version(str(data.get("tag_name") or data.get("name") or ""))
    url, sha, size = updates.find_asset(data, ASSET, (DOWNLOADS,))
    if ver is None or not url:
        raise updates.UpdateError("no Onion Pocket release the app can check")
    dest = updates.UPDATES_DIR / f"OnionPocket-module-{'.'.join(map(str, ver))}.zip"
    return updates.fetch(url, sha, dest, (DOWNLOADS,), MAX_SIZE, "an add-on", size,
                         progress, cancelled, FEATURE)


def get(base: Path | None = None, progress: Callable[[int, int], None] | None = None,
        cancelled: Callable[[], bool] | None = None) -> ModuleInfo | None:
    """Download and install the newest Onion Pocket. The installed add-on's info, or
    None when anything went wrong (logged, never raised). Call off the UI thread."""
    path = None
    try:
        path = _download(progress, cancelled)
        return modules.install_zip(path, MODULE_ID, KIND, base)
    except Exception as e:  # noqa: BLE001 - optional: any failure just means no card
        log.info("getting Onion Pocket failed: %s", e)
        return None
    finally:
        if path is not None and path.parent == updates.UPDATES_DIR:
            path.unlink(missing_ok=True)
