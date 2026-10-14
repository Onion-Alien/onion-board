"""Free sound packs: ready-made boards (a GM's tavern and battle sounds…) anyone can add
in one click from the Sounds tab's Backup menu (*Free sound packs*).

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
import shutil
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from soundboard import backup, library, net, netlog, updates

log = logging.getLogger(__name__)

FEATURE = "sound_packs"   # its switch in Settings > Privacy & security (soundboard.net)
CATALOG_URL = (f"https://raw.githubusercontent.com/{updates.REPO}/main/packs/catalog.json")
# where people share a pack: a GitHub form that asks for the link and the licence
SHARE_URL = f"https://github.com/{updates.REPO}/issues/new?template=sound-pack.yml"
RULES_URL = f"https://github.com/{updates.REPO}/blob/main/packs/README.md"
MAX_SIZE = 300 << 20     # the biggest pack the app downloads (the GM pack is ~28 MB)
PREVIEW_MAX = 4 << 20    # a pack's preview: a few short sounds (ours are ~0.4 MB)
SAMPLES = 6              # at most this many of a preview's sounds are shown
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
    # a few of its sounds, cut short, with their pictures (a small zip in the backup
    # format next to the pack): "Listen first" in the window. Optional.
    preview_url: str = ""
    preview_sha256: str = ""
    preview_size: int = 0

    @property
    def path(self) -> Path:
        """Where it's downloaded to. Importing it moves it in as the kept pack
        (backup.keep_pack), so it's never stored twice."""
        return library.APP_DIR / "packs" / f"{self.id}.zip"

    def downloaded(self) -> bool:
        """Fetched (and checked) before: adding it again just skips what's there."""
        return self.path.is_file() or backup.kept_free_pack(self.id) is not None


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
    "emoji": "🎲",
    "preview": {"url": f"{updates.DOWNLOADS}gm-pack-1/gm-starter-preview.zip",
                "sha256": "287c97df2e05a8b0aefb76381ab8bc91f28546caa0b2a1dbd8e5228b71d611db",
                "size": 523245},
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
    "preview": {"url": f"{updates.DOWNLOADS}esports-pack-1/esports-preview.zip",
                "sha256": "81553c247a987ef7dabe7da2b8b4a4555e5fe7e09a9c73f7dd063c491cd8ea4b",
                "size": 407620},
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
    "preview": {"url": f"{updates.DOWNLOADS}podcast-pack-1/podcast-preview.zip",
                "sha256": "1a427fc256d0152b7e5d2250337971e2660595dad21b7afd5b2f8184f7af4db1",
                "size": 392570},
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
        p.preview_url, p.preview_sha256, p.preview_size = _preview(d.get("preview"))
        out.append(p)
    return out


def _preview(d) -> tuple[str, str, int]:
    """A catalog entry's "preview" ({url, sha256, size}), or nothing when it isn't one
    on our releases with a checksum (the pack itself still shows)."""
    try:
        url, sha, size = str(d["url"]), str(d["sha256"]).lower(), int(d.get("size") or 0)
    except (KeyError, TypeError, ValueError):
        return "", "", 0
    if (not url.startswith(updates.DOWNLOADS) or not updates.SHA_RE.fullmatch(sha)
            or not 0 <= size <= PREVIEW_MAX):
        return "", "", 0
    return url, sha, size


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


def download(pack: Pack, progress: Callable[[int, int], object] | None = None,
             cancelled: Callable[[], bool] | None = None) -> Path:
    """Fetch `pack` into the app folder's "packs", checked against its SHA-256; its
    path. Raises updates.UpdateError with a message for the user. Call off the UI
    thread."""
    kept = backup.kept_free_pack(pack.id)
    if kept is not None and updates._sha256(kept) == pack.sha256:
        return kept   # added before and still kept: the same file, not fetched again
    netlog.cause(FEATURE, f"You pressed Add on the {netlog.quoted(pack.name)} pack")
    return updates.fetch(pack.url, pack.sha256, pack.path, (updates.DOWNLOADS,), MAX_SIZE,
                         "pack", pack.size, progress, cancelled, feature=FEATURE)


@dataclass
class Sample:
    """One of a preview's sounds: its name, its tile picture (PNG / JPEG bytes, or
    b"") and its audio file, unpacked."""
    name: str
    picture: bytes
    audio: Path


def previews_dir() -> Path:
    return library.APP_DIR / "packs" / "previews"


def samples(pack: Pack, cancelled: Callable[[], bool] | None = None) -> list[Sample]:
    """A few of `pack`'s sounds to try before adding it: its preview fetched (once,
    checked against its SHA-256) and unpacked. [] when it has none. Raises
    updates.UpdateError (switched off, offline, a bad file). Call off the UI thread."""
    if not pack.preview_url:
        return []
    d = previews_dir()
    zpath = d / f"{pack.id}.zip"
    if not zpath.is_file():   # the first time only: then it's served from here
        netlog.cause(FEATURE, f"You opened Free packs: a few sounds of "
                              f"{netlog.quoted(pack.name)} to try")
    updates.fetch(pack.preview_url, pack.preview_sha256, zpath, (updates.DOWNLOADS,),
                  PREVIEW_MAX, "pack", pack.preview_size, None, cancelled, feature=FEATURE)
    from soundboard import backup   # it imports the library's heavier parts
    try:
        pkg = backup.read(zpath)
    except backup.BackupError as e:
        raise updates.UpdateError(str(e)) from e
    out = d / pack.id
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    found = []
    with zipfile.ZipFile(zpath) as z:
        for i, ps in enumerate(pkg.sounds[:SAMPLES]):
            if sum(z.getinfo(n).file_size for n in (ps.audio, ps.picture) if n) > PREVIEW_MAX:
                continue   # far bigger unpacked than a short sound
            name = str(ps.entry.get("name") or "").strip()[:60]
            audio = out / f"{i}{Path(ps.audio).suffix.lower()}"
            audio.write_bytes(z.read(ps.audio))
            pic = z.read(ps.picture) if ps.picture else b""
            found.append(Sample(name or Path(ps.folder).name, pic, audio))
    return found
