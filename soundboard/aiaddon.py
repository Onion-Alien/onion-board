"""AI voices, the optional add-on behind the Voice tab's AI voices card: its newest
release, downloading it and installing it into %APPDATA%\\OnionBoard\\modules\\ai-voices.

It isn't part of the app or its installer (it's ~40 MB of voice model plus a ~15 MB
runtime that most people never need). Nothing here runs until the user presses
*Get AI voices*. The zip is taken only from the project's own
github.com/…/releases/download/ link, over HTTPS, and kept only if it matches the
SHA-256 GitHub lists for it (updates.fetch). It holds the add-on's code and the voice
model; modules.install then makes its own Python environment (onnxruntime).

ONIONBOARD_AI_VOICES_ZIP=<path to an AiVoices-module.zip> uses that file instead of
GitHub, to try a build before it's released (scripts/make_ai_voices_zip.py makes one).

"Get and update add-ons" switched off in Settings > Privacy & security stops it
(net.FeatureOff).
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
from soundboard import errors
from soundboard.i18n import _

log = logging.getLogger(__name__)

REPO = "Onion-Alien/onion-board"
PAGE = f"https://github.com/{REPO}"
TAG = "ai-voices"            # its own release, apart from the app's
API = f"https://api.github.com/repos/{REPO}/releases/tags/{TAG}"
RELEASES = f"{PAGE}/releases/tag/{TAG}"
DOWNLOADS = f"{PAGE}/releases/download/"     # the only place the add-on is fetched from
ASSET = "AiVoices-module.zip"
MODULE_ID = "ai-voices"
KIND = "service"
LOCAL_ENV = "ONIONBOARD_AI_VOICES_ZIP"
MAX_SIZE = 150 << 20     # the zip is ~40 MB, almost all voice model
FEATURE = "addons"       # its switch in Settings > Privacy & security (soundboard.net)


@dataclass
class Offer:
    """An AI voices add-on there is to install."""
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
    """The AI voices add-on as installed (anywhere modules are looked for), or None."""
    return next((m for m in modules.discover(dirs) if m.id == MODULE_ID), None)


def _zip_version(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as z:
            d = json.loads(z.read(f"{MODULE_ID}/module.json").decode("utf-8-sig"))
        return str(d.get("version", "?"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, AttributeError):
        return "?"


def latest(cancelled: Callable[[], bool] | None = None) -> Offer | None:
    """The newest AI voices add-on to install, or None when its latest release has no
    zip the app can check. Raises OSError / ValueError when GitHub can't be asked
    (offline, rate-limited), UpdateError("cancelled") when `cancelled` turns true
    before a retry. Call off the UI thread."""
    lz = local_zip()
    if lz is not None:
        return Offer(_zip_version(lz), page=str(lz), local=lz)
    data = updates._get(API, FEATURE, cancelled)
    # the tag is just "ai-voices" (one release, its zip replaced on update): the
    # version is in its title, "AI voices 0.1.0"
    ver = updates.parse_version(str(data.get("name") or ""))
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
    dest = updates.UPDATES_DIR / f"AiVoices-module-{offer.version}.zip"
    return updates.fetch(offer.url, offer.sha256, dest, (DOWNLOADS,), MAX_SIZE, "add-on",
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
    """Uninstall it (modules.uninstall): its code, voice model and Python environment.
    The user's AI voice settings stay in the config. Raises modules.ModuleError."""
    modules.uninstall(MODULE_ID, base)


def friendly(e: Exception) -> str:
    """An error from getting the add-on, as a sentence for the tab."""
    text = errors.plain(e)
    if isinstance(e, net.FeatureOff):
        return text
    if getattr(e, "code", None) in (502, 503, 504):
        return _("GitHub's download check is temporarily unavailable (gateway error). "
                 "Try Get AI voices again in a moment.")
    if "404" in text:
        return _("AI voices aren't available to download yet (GitHub says it can't find "
                 "it). Try again later.")
    if isinstance(e, OSError):          # urllib's errors: offline, DNS, timeouts
        return _("Couldn't reach GitHub ({error}). Check your internet connection.",
                 error=text)
    return text[:1].upper() + text[1:]
