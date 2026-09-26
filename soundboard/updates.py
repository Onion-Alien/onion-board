"""Is there a newer Onion Board? An opt-in look at the project's latest GitHub
release (Settings → General), at most once a day, plus a "Check now" button.

Nothing is downloaded or installed: a newer version is only announced, with a
button that opens its release page in the browser. The request carries no data
about the user beyond what any HTTPS request does (see SECURITY.md)."""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.request
from dataclasses import dataclass

from soundboard import __version__

log = logging.getLogger(__name__)

REPO = "Onion-Alien/soundboard"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES = f"https://github.com/{REPO}/releases/latest"
EVERY_S = 24 * 3600
LIMIT = 1 << 20   # the API's answer is a few KB


@dataclass
class Release:
    version: str      # "1.0.1"
    url: str          # its page on GitHub
    notes: str = ""   # the first lines of its description


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
    return Release(".".join(map(str, ver)), url, notes)


def check(cfg, force: bool = False) -> Release | None:
    """A newer release than this one, or None. Without `force` it only asks if the
    user opted in, once a day, and stays quiet about a version they skipped.
    Network errors are logged and read as 'nothing new'. Call off the UI thread."""
    if not force and (not cfg.update_check_optin
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
