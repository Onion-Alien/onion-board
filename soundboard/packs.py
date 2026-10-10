"""Free sound packs: ready-made boards (a GM's tavern and battle sounds…) anyone can add
in one click from the Sounds tab's Backup menu (*Free sound packs…*).

The list is packs/catalog.json in the project's repository, read fresh each time the
window opens (a copy of the packs known when this version was built, BUILT_IN, stands
in when it can't be read). Every pack is a zip in Onion Board's own backup format
(docs/BACKUP-FORMAT.md) uploaded to one of the project's GitHub releases: a pack is
only ever fetched from there, over HTTPS, and only kept when its SHA-256 matches the
one the list gives, so nobody can swap a pack's sounds after it was checked.

Anyone can share a pack: packs/README.md says how (a GitHub form; every sound must be
CC0, so whoever adds it can use it anywhere). The requests carry nothing about the
user beyond what any HTTPS request does, and they have their own switch in Settings >
Privacy & security (FEATURE)."""
from __future__ import annotations

import json
import logging
import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from soundboard import library, net, netlog, updates

log = logging.getLogger(__name__)

FEATURE = "sound_packs"   # its switch in Settings > Privacy & security (soundboard.net)
CATALOG_URL = (f"https://raw.githubusercontent.com/{updates.REPO}/main/packs/catalog.json")
# where people share a pack: a GitHub form that asks for the link and the licence
SHARE_URL = f"https://github.com/{updates.REPO}/issues/new?template=sound-pack.yml"
RULES_URL = f"https://github.com/{updates.REPO}/blob/main/packs/README.md"
MAX_SIZE = 300 << 20     # the biggest pack the app downloads (the GM pack is ~28 MB)
CATALOG_LIMIT = 1 << 20  # the list is a few KB
ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")


@dataclass
class Pack:
    id: str            # "gm-starter": its zip's name in the app folder's "packs"
    name: str
    description: str
    url: str           # a file on one of the project's GitHub releases
    sha256: str
    size: int = 0      # bytes
    sounds: int = 0
    license: str = "CC0"
    author: str = ""
    emoji: str = "📦"   # the pack's picture in the window
    categories: list[str] = field(default_factory=list)

    @property
    def path(self) -> Path:
        return library.APP_DIR / "packs" / f"{self.id}.zip"

    def downloaded(self) -> bool:
        """Fetched (and checked) before: adding it again just skips what's there."""
        return self.path.is_file()


# the packs known when this version was built: shown when the list can't be read
BUILT_IN = [{
    "id": "gm-starter",
    "name": "GM starter pack",
    "description": "For tabletop games (D&D and friends): tavern, travel, weather, "
                   "dungeon, combat, magic, boss and ending sounds. Music loops, and "
                   "Ctrl+Alt+1/2/3 switch tavern, battle and boss music.",
    "url": f"{updates.DOWNLOADS}gm-pack-1/onion-board-gm-starter-pack.zip",
    "sha256": "bfb53856bb8f225f336e5391b9ceb0773da2bca61923de0102abf888d499f09d",
    "size": 28480681,
    "sounds": 67,
    "license": "CC0 + CC BY (credits inside)",
    "author": "Onion Board",
    "emoji": "🐉",
    "categories": ["Tavern", "Travel", "Weather", "Dungeon", "Combat", "Magic", "Boss",
                   "Endings"],
}, {
    "id": "esports",
    "name": "Esports pack",
    "description": "For streams, casting, LAN parties and voice chat: arena crowd cheers and "
                   "boos, air horn, a fighting-game announcer (3, 2, 1, Fight!, Multi kill, "
                   "Flawless victory), shooter callouts, plays and memes. Hype music loops; "
                   "Ctrl+Alt+1 hype music, Ctrl+Alt+3 the countdown.",
    "url": f"{updates.DOWNLOADS}esports-pack-1/onion-board-esports-pack.zip",
    "sha256": "661dee49cef5796519fb95bd16ce21283bdfae955ca6fbe973c7b35943791ba5",
    "size": 18546197,
    "sounds": 51,
    "license": "CC0",
    "author": "Onion Board",
    "emoji": "🏆",
    "categories": ["Hype music", "Crowd", "Announcer", "Callouts", "Plays", "Memes"],
}, {
    "id": "podcast",
    "name": "Podcast pack",
    "description": "For podcasts, talk streams and live shows: intro, outro and background "
                   "music, stingers, ba-dum-tss, bleep, audience laughs and applause, comedy "
                   "sounds, game-show buzzers and studio sounds (phone, doorbell, "
                   "typewriter).",
    "url": f"{updates.DOWNLOADS}podcast-pack-1/onion-board-podcast-pack.zip",
    "sha256": "c560b16bb4f87120394ff43986645119bb7a7071c54d6ceb256a4def3bae69d9",
    "size": 15628205,
    "sounds": 51,
    "license": "CC0 (applause public domain)",
    "author": "Onion Board",
    "emoji": "🎙️",
    "categories": ["Show music", "Stingers", "Reactions", "Comedy", "Game show", "Studio"],
}]


def parse(raw) -> list[Pack]:
    """The packs in a catalog (its "packs" list, or a bare list): any entry that isn't a
    pack on the project's own releases, with a checksum and a sane size, is left out."""
    items = raw.get("packs") if isinstance(raw, dict) else raw
    out, seen = [], set()
    for d in items if isinstance(items, list) else []:
        try:
            p = Pack(id=str(d["id"]), name=str(d["name"]).strip(),
                     description=str(d.get("description") or "").strip(),
                     url=str(d["url"]), sha256=str(d["sha256"]).lower(),
                     size=int(d.get("size") or 0), sounds=int(d.get("sounds") or 0),
                     license=str(d.get("license") or "CC0").strip(),
                     author=str(d.get("author") or "").strip(),
                     emoji=str(d.get("emoji") or "📦")[:4],
                     categories=[str(c) for c in d.get("categories") or []
                                 if isinstance(c, str)][:20])
        except (KeyError, TypeError, ValueError):
            log.debug("skipped a catalog entry: %r", d)
            continue
        if (not ID_RE.fullmatch(p.id) or p.id in seen or not p.name
                or not p.url.startswith(updates.DOWNLOADS)
                or not updates.SHA_RE.fullmatch(p.sha256)
                or not 0 <= p.size <= MAX_SIZE):
            log.debug("skipped catalog entry %r", p.id)
            continue
        seen.add(p.id)
        out.append(p)
    return out


def built_in() -> list[Pack]:
    return parse(BUILT_IN)


def catalog() -> list[Pack]:
    """The packs on offer now, from the project's list. Raises (net.ProxyError when
    switched off or Offline, OSError / ValueError when it can't be read): the caller
    shows built_in() and says why. Call off the UI thread."""
    netlog.cause(FEATURE, "You opened Free packs: reading the list of packs")
    req = urllib.request.Request(CATALOG_URL, headers={"User-Agent": "OnionBoard (sound packs)"})
    with net.urlopen(req, timeout=15, feature=FEATURE) as r:
        packs = parse(json.loads(r.read(CATALOG_LIMIT).decode("utf-8")))
    if not packs:
        raise ValueError("the pack list is empty")
    return packs


def download(pack: Pack, progress: Callable[[int, int], None] | None = None,
             cancelled: Callable[[], bool] | None = None) -> Path:
    """Fetch `pack` into the app folder's "packs", checked against its SHA-256; its
    path. Raises updates.UpdateError with a message for the user. Call off the UI
    thread."""
    netlog.cause(FEATURE, f"You pressed Add on the {netlog.quoted(pack.name)} pack")
    return updates.fetch(pack.url, pack.sha256, pack.path, (updates.DOWNLOADS,), MAX_SIZE,
                         "pack", pack.size, progress, cancelled, feature=FEATURE)
