"""Free sound packs: ready-made boards (a GM's tavern and battle sounds…) anyone can add
in one click from the Sounds tab's Backup menu (*Free sound packs*).

The list is packs/catalog.json in the project's repository, read fresh each time the
window opens (a copy of the packs known when this version was built, BUILT_IN, stands
in when it can't be read). Every pack is a zip in Onion Board's own backup format
(docs/BACKUP-FORMAT.md) uploaded to one of the project's GitHub releases: a pack is
only ever fetched from there, over HTTPS, and only kept when its SHA-256 matches the
one the list gives, so nobody can swap a pack's sounds after it was checked.

A pack can also be only links (a "links" list in place of the zip's url and sha256):
Myinstants sounds' MP3s, each fetched from that site when Add is pressed, the way a
pasted Myinstants link is (soundboard.online.ytdl: its own switch, Tor and proxy
settings), then put in a zip of the same format on this PC (download_links). None of
it is stored by the project; a link that has gone is skipped and counted.

Anyone can share a pack: packs/README.md says how (a GitHub form; every sound must be
CC0, so whoever adds it can use it anywhere). The requests carry nothing about the
user beyond what any HTTPS request does, and they have their own switch in Settings >
Privacy & security (FEATURE)."""
from __future__ import annotations

import json
import logging
import re
import shutil
import threading
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from soundboard.core import backup, errors, updates
from soundboard.sounds import library
from soundboard.online import net, netlog
from soundboard.i18n import _

log = logging.getLogger(__name__)

FEATURE = "sound_packs"   # its switch in Settings > Privacy & security (soundboard.online.net)
CATALOG_URL = (f"https://raw.githubusercontent.com/{updates.REPO}/main/packs/catalog.json")
# where people share a pack: a GitHub form that asks for the link and the licence
SHARE_URL = f"https://github.com/{updates.REPO}/issues/new?template=sound-pack.yml"
RULES_URL = f"https://github.com/{updates.REPO}/blob/main/packs/README.md"
MAX_SIZE = 300 << 20     # the biggest pack the app downloads (the GM pack is ~28 MB)
PREVIEW_MAX = 4 << 20    # a pack's preview: a few short sounds (ours are ~0.4 MB)
SAMPLES = 6              # at most this many of a preview's sounds are shown
CATALOG_LIMIT = 1 << 20  # the list is a few KB
ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
MAX_LINKS = 300          # a links pack's sounds
LINK_WORKERS = 4         # links fetched at once


@dataclass(frozen=True)
class Link:
    """One sound of a links pack: its name, its Myinstants MP3 and its category."""
    name: str
    url: str
    category: str = ""


def _link_ok(url: str) -> bool:
    """A Myinstants sound's MP3, nothing else (the list is public: no other site, no
    query, no name that could leave the folder it's saved in)."""
    from soundboard.online.ytsites import MYINSTANTS
    leaf = url.removeprefix(MYINSTANTS + "/media/sounds/")
    return (leaf != url and len(leaf) > 4 and leaf.lower().endswith(".mp3")
            and not any(c in leaf for c in '/\\?#:') and ".." not in leaf)


def _links(raw) -> list[Link]:
    out, seen = [], set()
    for d in raw[:MAX_LINKS] if isinstance(raw, list) else []:
        try:
            link = Link(str(d["name"]).strip()[:60], str(d["url"]).strip(),
                        str(d.get("category") or "").strip()[:40])
        except (KeyError, TypeError, AttributeError):
            continue
        if link.name and _link_ok(link.url) and link.url not in seen:
            seen.add(link.url)
            out.append(link)
    return out


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
    # what kind of pack it is, for the window's filters ("Memes", "Streaming"…)
    tags: list[str] = field(default_factory=list)
    # a links pack (no url / sha256): its sounds' Myinstants links, fetched on Add
    links: list[Link] = field(default_factory=list)
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


# the meme pack: (name, category, its MP3 on Myinstants), from Myinstants' most-played
_MEMES = [
    ("Vine boom", "Reactions", "vine-boom.mp3"),
    ("Bruh", "Reactions", "movie_1.mp3"),
    ("Anime wow", "Reactions", "anime-wow-sound-effect.mp3"),
    ("MLG air horn", "Gaming", "mlg-airhorn.mp3"),
    ("Emotional damage", "Reactions", "emotional-damage-meme.mp3"),
    ("Metal pipe", "Fails", "metal-pipe-clang.mp3"),
    ("Wrong buzzer", "Fails", "wrong-answer-sound-effect.mp3"),
    ("Taco Bell bong", "Reactions", "taco-bell-bong-sfx.mp3"),
    ("Get out (Tuco)", "Reactions", "tuco-get-out.mp3"),
    ("Roblox oof", "Gaming", "roblox-death-sound_1.mp3"),
    ("SpongeBob fail", "Fails", "spongebob-fail.mp3"),
    ("Fahhh", "Reactions", "fahhhhhhhhhhhhhh.mp3"),
    ("Sad violin", "Fails", "tf_nemesis.mp3"),
    ("Rizz", "Vine & TikTok", "rizz-sound-effect.mp3"),
    ("Censor beep", "Reactions", "censor-beep-1.mp3"),
    ("Among Us role reveal", "Gaming", "among-us-role-reveal-sound.mp3"),
    ("Ding", "Reactions", "ding-sound-effect_2.mp3"),
    ("Fortnite death", "Gaming", "tmp_7901-951678082.mp3"),
    ("Bone crack", "Fails", "bone-crack.mp3"),
    ("Metal Gear alert", "Gaming", "tindeck_1.mp3"),
    ("Windows XP error", "Classic memes", "erro.mp3"),
    ("Price is Right losing horn", "Fails", "the-price-is-right-losing-horn.mp3"),
    ("Shut up!", "Reactions", "shutup.swf.mp3"),
    ("Lizard", "Vine & TikTok", "lizard-button.mp3"),
    ("DJ air horn", "Music", "dj-airhorn-sound-effect-kingbeatz_1.mp3"),
    ("What da dog doin", "Vine & TikTok", "yt1s_wU4BGgD.mp3"),
    ("Undertaker bell", "Classic memes", "undertakers-bell_2UwFCIe.mp3"),
    ("Outro song", "Music", "outro-song_oqu8zAg.mp3"),
    ("Oh hell nah", "Reactions", "oh-my-god-bro-oh-hell-nah-man.mp3"),
    ("Dun dun dunnn", "Music", "dun-dun-dun-sound-effect-brass_8nFBccR.mp3"),
    ("Huh? (Ceeday)", "Reactions", "ceeday-huh-sound-effect.mp3"),
    ("Law and Order dun dun", "Music", "dun_dun_1.mp3"),
    ("Baby laughing", "Reactions", "baby-laughing-meme.mp3"),
    ("Chicken jockey", "Gaming", "chicken-jockey.mp3"),
    ("To be continued", "Music", "untitled_1071.mp3"),
    ("Spider-Man meme song", "Music", "spiderman-meme-song.mp3"),
    ("Mario jump", "Gaming", "maro-jump-sound-effect_1.mp3"),
    ("Rehehehe", "Reactions", "rehehehe.mp3"),
    ("Sad trombone", "Fails", "sadtrombone.swf.mp3"),
    ("FBI open up", "Classic memes", "fbi-open-up-sfx.mp3"),
    ("Pluh", "Vine & TikTok", "pluh.mp3"),
    ("Snore mimimimi", "Classic memes", "snore-mimimimimimi.mp3"),
    ("Womp womp womp", "Fails", "downer_noise.mp3"),
    ("Oh no no no laugh", "Reactions", "oh-no-no-no-no-laugh.mp3"),
    ("Run (Vine)", "Vine & TikTok", "run-vine-sound-effect.mp3"),
    ("Minecraft hurt", "Gaming", "classic_hurt.mp3"),
    ("Bad to the bone", "Music", "bad-to-the-bone.mp3"),
    ("Noooo!", "Reactions", "nooo.swf.mp3"),
    ("Oh brother, this guy stinks", "Vine & TikTok", "oh-brother-this-guy-stinks.mp3"),
    ("Hello there", "Classic memes", "obi-wan-hello-there.mp3"),
    ("Yippee", "Reactions", "yippee-tbh.mp3"),
    ("Augh", "Vine & TikTok", "aughhhhh-aughhhhh.mp3"),
    ("Nope", "Reactions", "engineer_no01.mp3"),
    ("Baba Booey", "Classic memes", "bababooey-sound-effect.mp3"),
    ("Yeet", "Vine & TikTok", "yeet-sound-effect.mp3"),
    ("Crickets", "Fails", "crickets.swf.mp3"),
    ("Windows XP shutdown", "Classic memes", "preview_4.mp3"),
    ("Aww", "Reactions", "studio-audience-awwww-sound-fx.mp3"),
    ("Lego Yoda death", "Gaming", "lego-yoda-death-sound-effect.mp3"),
    ("Oh my god", "Reactions", "oh-my-god-meme.mp3"),
    ("Erm what the sigma", "Vine & TikTok", "erm-what-the-sigma_su7GnzC.mp3"),
    ("Mission failed", "Gaming", "dank-meme-compilation-volume-17_cutted.mp3"),
    ("Leeroy Jenkins", "Classic memes", "leroy.swf.mp3"),
    ("Rimshot", "Music", "badumtss.swf.mp3"),
    ("Inception", "Music", "inceptionbutton.mp3"),
    ("My name is Jeff", "Classic memes", "ringtone_20.mp3"),
    ("What are you doing in my swamp", "Classic memes", "what-are-you-doing-in-my-swamp-.mp3"),
    ("Sitcom laugh", "Reactions", "sitcom-laughing-1.mp3"),
    ("We do not care", "Vine & TikTok", "we-do-not-care_phB0mEB.mp3"),
    ("Bonk", "Fails", "bonk_BEtiM8g.mp3"),
    ("A few moments later", "Classic memes", "a-few-moments-later-hd.mp3"),
    ("Extremely loud wrong buzzer", "Fails", "extremely-loud-incorrect-buzzer_0cDaG20.mp3"),
    ("Another one", "Music", "another-one_dPvHt2Z.mp3"),
    ("Tactical nuke incoming", "Gaming", "tactical-nuke.mp3"),
    ("Hitmarker", "Gaming", "hitmarker_2.mp3"),
    ("Wilhelm scream", "Classic memes", "wilhelmscream.mp3"),
    ("Wasted (GTA V)", "Gaming", "gta-v-death-sound-effect-102.mp3"),
    ("Hell naw dog", "Reactions", "hell-naw-dog.mp3"),
    ("Yeah boiii", "Classic memes", "yeah-boiii-i-i-i.mp3"),
    ("Bazinga!", "Classic memes", "bazinga.swf.mp3"),
    ("Deja vu", "Music", "deja-vu.mp3"),
    ("Let's gooo", "Reactions", "vibez-lets-go.mp3"),
    ("Over 9000!", "Classic memes", "over9000.swf.mp3"),
    ("This is Sparta!", "Classic memes", "thisissparta.swf.mp3"),
    ("Nani?!", "Classic memes", "nani_Pmxf5n3.mp3"),
    ("Tuturu", "Gaming", "tuturu_1.mp3"),
    ("Bing chilling", "Vine & TikTok", "bing-chilling_fcdGgUc.mp3"),
    ("Darth Vader noooo", "Classic memes", "nooo.mp3"),
    ("Trololo", "Music", "trollolol.swf.mp3"),
    ("Huh cat", "Vine & TikTok", "huh-cat.mp3"),
    ("Careless whisper", "Music", "careless_whispers.mp3"),
    ("Nelson's ha-ha", "Classic memes", "the-simpsons-nelsons-haha.mp3"),
    ("That was easy", "Reactions", "that_was_easy.mp3"),
    ("Coffin dance", "Music", "y2mate-mp3cut_sRzY6rh.mp3"),
    ("Directed by Robert B. Weide", "Music", "directed-by-robert-b_voI2Z4T.mp3"),
    ("Boom! Headshot!", "Gaming", "boomheadshot.swf.mp3"),
    ("Dramatic chipmunk", "Classic memes", "dramatic.swf.mp3"),
    ("Why are you running?", "Vine & TikTok", "why-are.mp3"),
    ("Super Mario death", "Gaming", "super-mario-death-sound-sound-effect.mp3"),
    ("Zelda item get", "Gaming", "139-item-catch.mp3"),
    ("Illuminati confirmed", "Music", "x-files-theme-song-copy.mp3"),
    ("Za Warudo", "Gaming", "hd-stardust-crusaders-za-warudo_1.mp3"),
    ("Owen Wilson wow", "Reactions", "6_1Njp68r.mp3"),
    ("Sonic ring", "Gaming", "26f8b9_sonic_ring_sound_effect.mp3"),
]

# the packs known when this version was built: shown when the list can't be read
BUILT_IN = [{
    "id": "memes",
    "name": "Meme sounds",
    "description": "The 104 most-played meme sounds of the last 16 years: vine boom, bruh, "
                   "anime wow, MLG air horn, emotional damage, metal pipe, sad violin, Roblox "
                   "oof, Taco Bell bong, Windows XP error, Leeroy Jenkins and many more.",
    "license": "As on Myinstants",
    "author": "Onion Board",
    "emoji": "😂",
    "tags": ["Memes"],
    "categories": ["Reactions", "Gaming", "Fails", "Vine & TikTok", "Classic memes", "Music"],
    "links": [{"name": n, "category": c,
               "url": f"https://www.myinstants.com/media/sounds/{f}"}
              for n, c, f in _MEMES],
}, {
    "id": "streamer",
    "name": "Streamer pack",
    "description": "For live streams: starting soon, just chatting, BRB and ending music; "
                   "follower, sub, donation and raid alerts; air horn, cheers, fails (bonk, "
                   "buzzer, sad trombone), chat reactions, a 3-2-1 Go announcer and transitions. "
                   "Ctrl+Alt+3 air horn, Ctrl+Alt+4 bonk.",
    "url": f"{updates.DOWNLOADS}streamer-pack-1/onion-board-streamer-pack.zip",
    "sha256": "bb6b6895c3ef30f14e5a45a1b0cfc384de4691d960e1fdf1b0eae8967e1b638c",
    "size": 18299334,
    "sounds": 57,
    "license": "CC0",
    "author": "Onion Board",
    "emoji": "📺",
    "tags": ["Streaming"],
    "preview": {"url": f"{updates.DOWNLOADS}streamer-pack-1/streamer-preview.zip",
                "sha256": "4baeb7fe3d9bdbd2a07db071ba89666d9b3a910118cb510325c1adef1478191c",
                "size": 376595},
    "categories": ["Stream music", "Alerts", "Hype", "Fails", "Chat reactions", "Announcer",
                   "Transitions"],
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
    "tags": ["Gaming", "Streaming"],
    "preview": {"url": f"{updates.DOWNLOADS}esports-pack-1/esports-preview.zip",
                "sha256": "81553c247a987ef7dabe7da2b8b4a4555e5fe7e09a9c73f7dd063c491cd8ea4b",
                "size": 407620},
    "categories": ["Hype music", "Crowd", "Announcer", "Callouts", "Plays", "Memes"],
}, {
    "id": "general",
    "name": "General sound pack",
    "description": "483 sounds for everything, in 20 categories: memes (air horn, boom, bruh), "
                   "comedy, game show buzzers, crowds, people, 25 animals, video game blips and "
                   "power-ups, notifications, combat, impacts, whooshes, sci-fi, magic, horror, "
                   "vehicles, household, nature ambiences, sports, music stings and party sounds.",
    "url": f"{updates.DOWNLOADS}general-pack-1/onion-board-general-pack.zip",
    "sha256": "9044bdf70427ef854e7c1ec698901bc9f8a7f59c23ade1af55a046573db57c58",
    "size": 44324802,
    "sounds": 483,
    "license": "CC0",
    "author": "Onion Board",
    "emoji": "🔊",
    "tags": ["Everyday", "Memes"],
    "preview": {"url": f"{updates.DOWNLOADS}general-pack-1/general-preview.zip",
                "sha256": "18a6154703c5a96e868e2b74d0e38ddb4c34cd8deffeddc39f64bbb116312985",
                "size": 356511},
    "categories": ["Memes", "Comedy", "Game show", "Crowd", "People", "Animals", "Video game",
                   "Notifications", "Combat", "Impacts", "Transitions", "Sci-fi", "Magic", "Horror",
                   "Vehicles", "Household", "Nature", "Sports", "Music", "Party"],
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
    "tags": ["Podcast"],
    "preview": {"url": f"{updates.DOWNLOADS}podcast-pack-1/podcast-preview.zip",
                "sha256": "1a427fc256d0152b7e5d2250337971e2660595dad21b7afd5b2f8184f7af4db1",
                "size": 392570},
    "categories": ["Show music", "Stingers", "Reactions", "Comedy", "Game show", "Studio"],
}, {
    "id": "halloween",
    "name": "Halloween pack",
    "description": "For Halloween parties, horror streams and pranks: screams, evil laughs and "
                   "witch cackles, zombies and monster roars, jump scares, creaky doors, a clock "
                   "striking midnight, thunder, wolves and owls. Spooky music loops; Ctrl+Alt+2 a "
                   "scream, Ctrl+Alt+4 a jump scare.",
    "url": f"{updates.DOWNLOADS}halloween-pack-1/onion-board-halloween-pack.zip",
    "sha256": "9ac377385e2979396b132fae75ae874b39559c4b4deb7bfb38a77e3d6a6c0f9d",
    "size": 26947272,
    "sounds": 49,
    "license": "CC0 + CC BY (credits inside)",
    "author": "Onion Board",
    "emoji": "🎃",
    "tags": ["Spooky"],
    "preview": {"url": f"{updates.DOWNLOADS}halloween-pack-1/halloween-preview.zip",
                "sha256": "8014fbf24322b467e09e4a4eaff179aa974f424750d0191393655fe27ae5a090",
                "size": 480541},
    "categories": ["Spooky music", "Screams", "Monsters", "Jump scares", "Haunted house",
                   "Night"],
}, {
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
    "tags": ["Tabletop", "Music"],
    "preview": {"url": f"{updates.DOWNLOADS}gm-pack-1/gm-starter-preview.zip",
                "sha256": "287c97df2e05a8b0aefb76381ab8bc91f28546caa0b2a1dbd8e5228b71d611db",
                "size": 523245},
    "categories": ["Tavern", "Travel", "Weather", "Dungeon", "Combat", "Magic", "Boss",
                   "Endings"],
}]


def parse(raw) -> list[Pack]:
    """The packs in a catalog (its "packs" list, or a bare list): any entry that isn't a
    pack on the project's own releases, with a checksum and a sane size, is left out."""
    items = raw.get("packs") if isinstance(raw, dict) else raw
    out, seen = [], set()
    for d in items if isinstance(items, list) else []:
        try:
            links = _links(d.get("links"))
            p = Pack(id=str(d["id"]), name=str(d["name"]).strip(),
                     description=str(d.get("description") or "").strip(),
                     url="" if links else str(d["url"]),
                     sha256="" if links else str(d["sha256"]).lower(),
                     size=int(d.get("size") or 0), sounds=int(d.get("sounds") or 0),
                     license=str(d.get("license") or "CC0").strip(),
                     author=str(d.get("author") or "").strip(),
                     emoji=str(d.get("emoji") or "📦")[:4],
                     categories=[str(c) for c in d.get("categories") or []
                                 if isinstance(c, str)][:20],
                     tags=[t.strip()[:24] for t in d.get("tags") or []
                           if isinstance(t, str) and t.strip()][:4],
                     links=links)
        except (KeyError, TypeError, ValueError, AttributeError):
            log.debug("skipped a catalog entry: %r", d)
            continue
        if (not ID_RE.fullmatch(p.id) or p.id in seen or not p.name
                or not (p.links or (p.url.startswith(updates.DOWNLOADS)
                                    and updates.SHA_RE.fullmatch(p.sha256)))
                or not 0 <= p.size <= MAX_SIZE):
            log.debug("skipped catalog entry %r", p.id)
            continue
        seen.add(p.id)
        if p.links:
            p.sounds = len(p.links)
            p.categories = p.categories or list(dict.fromkeys(
                k.category for k in p.links if k.category))[:20]
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


_listed: dict[str, Pack] = {}   # every pack the online list has had, by id


def known(pack_id: str) -> Pack | None:
    """A free pack: from the online list once it was read (a pack added since this
    version was built), else this version's own; None when neither has it."""
    return _listed.get(pack_id) or next((p for p in built_in() if p.id == pack_id), None)


def name_of(pack_id: str) -> str:
    """A free pack's name ("Streamer pack"), or ""."""
    p = known(pack_id)
    return p.name if p else ""


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
    _listed.update((p.id, p) for p in packs)
    return packs


def download(pack: Pack, progress: Callable[[int, int], object] | None = None,
             cancelled: Callable[[], bool] | None = None) -> Path:
    """Fetch `pack` into the app folder's "packs", checked against its SHA-256; its
    path. Raises updates.UpdateError with a message for the user. Call off the UI
    thread. A links pack: download_links (this gives just its path)."""
    if pack.links:
        return download_links(pack, progress, cancelled)[0]
    kept = backup.kept_free_pack(pack.id)
    if kept is not None and updates._sha256(kept) == pack.sha256:
        return kept   # added before and still kept: the same file, not fetched again
    netlog.cause(FEATURE, f"You pressed Add on the {netlog.quoted(pack.name)} pack")
    path = updates.fetch(pack.url, pack.sha256, pack.path, (updates.DOWNLOADS,), MAX_SIZE,
                         "pack", pack.size, progress, cancelled, feature=FEATURE)
    try:   # its checksum matched a broken upload: kept, it would read "Add again"
        with zipfile.ZipFile(path) as z:
            bad = z.testzip()
    except (OSError, zipfile.BadZipFile, EOFError) as e:
        bad = str(e) or "unreadable"
    if bad is not None:
        log.warning("pack %s: the downloaded zip is damaged (%s)", pack.id, bad)
        path.unlink(missing_ok=True)
        raise updates.UpdateError(_("the pack's file is damaged, so it wasn't kept"))
    return path


def download_links(pack: Pack, progress: Callable[[int, int], object] | None = None,
                   cancelled: Callable[[], bool] | None = None) -> tuple[Path, int]:
    """A links pack: each link fetched from Myinstants (LINK_WORKERS at once), then put
    in a zip of the backup format at pack.path, so it's added, kept, reset and removed
    like any other pack. (its path, how many links were skipped: gone, or not a sound).
    `progress` gets (links done, links). Raises updates.UpdateError when none came or
    it was cancelled. Call off the UI thread."""
    kept = backup.kept_free_pack(pack.id)
    if kept is not None:
        return kept, 0   # added before and still kept: not fetched again
    from concurrent.futures import ThreadPoolExecutor

    from soundboard.online import ytdl
    from soundboard.online.ytsites import temp_folder
    netlog.cause(FEATURE, f"You pressed Add on the {netlog.quoted(pack.name)} pack: its "
                          f"sounds, from Myinstants")
    tmp = temp_folder("sb-linkpack-")
    got: dict[int, Path] = {}
    errs: list[str] = []
    lock = threading.Lock()
    done = 0

    def one(i: int, link: Link):
        nonlocal done
        if cancelled is not None and cancelled():
            return
        try:
            path, _title = ytdl.download_audio(link.url, tmp / str(i), thumbnail=False)
        except Exception as e:  # noqa: BLE001 - gone, offline, switched off: skipped
            log.info("pack %s: skipped %s (%s)", pack.id, link.url, e)
            with lock:
                errs.append(errors.plain(e))
        else:
            with lock:
                got[i] = Path(path)
        with lock:
            done += 1
            n = done
        if progress is not None:
            progress(n, len(pack.links))

    try:
        for i in range(len(pack.links)):
            (tmp / str(i)).mkdir()
        with ThreadPoolExecutor(LINK_WORKERS, thread_name_prefix="pack-link") as pool:
            list(pool.map(lambda a: one(*a), enumerate(pack.links)))
        if cancelled is not None and cancelled():
            raise updates.UpdateError(_("Stopped."))
        if not got:
            raise updates.UpdateError(errs[0] if errs else _("None of its sounds could be "
                                                              "downloaded."))
        _zip_links(pack, got, pack.path)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return pack.path, len(pack.links) - len(got)


def _zip_links(pack: Pack, got: dict[int, Path], dest: Path):
    """The fetched sounds as a pack zip (docs/BACKUP-FORMAT.md), in the list's order."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    order = sorted(got)
    folders = []
    try:
        with zipfile.ZipFile(part, "w", zipfile.ZIP_STORED) as z:   # MP3s don't shrink
            for n, i in enumerate(order, 1):
                link, audio = pack.links[i], got[i]
                folder = f"sounds/{n:03d}"
                entry: dict = {"name": link.name, "audio": audio.name}
                if link.category:
                    entry["tags"] = [link.category]
                z.write(audio, f"{folder}/{audio.name}")
                z.writestr(f"{folder}/sound.json", json.dumps(entry, ensure_ascii=False))
                folders.append(folder)
            z.writestr("onionboard.json", json.dumps({
                "format": "onionboard-board", "format_version": 1,
                "categories": list(dict.fromkeys(pack.links[i].category for i in order
                                                 if pack.links[i].category)),
                "sounds": folders, "settings": None}, ensure_ascii=False))
        part.replace(dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise


@dataclass
class Sample:
    """One of a preview's sounds: its name, its tile picture (PNG / JPEG bytes, or
    b"") and its audio file, unpacked."""
    name: str
    picture: bytes
    audio: Path


_sample_locks: dict[str, threading.Lock] = {}
_sample_locks_lock = threading.Lock()


def previews_dir() -> Path:
    return library.APP_DIR / "packs" / "previews"


def samples(pack: Pack, cancelled: Callable[[], bool] | None = None) -> list[Sample]:
    """A few of `pack`'s sounds to try before adding it: its preview fetched (once,
    checked against its SHA-256) and unpacked. [] when it has none. Raises
    updates.UpdateError (switched off, offline, a bad file). Call off the UI thread.
    A links pack's are its first SAMPLES links, fetched from Myinstants (_link_samples)."""
    if not pack.preview_url and not pack.links:
        return []
    with _sample_locks_lock:
        lock = _sample_locks.setdefault(pack.id, threading.Lock())
    with lock:   # two at once wrote the same .part file: a bad checksum, no samples
        return _link_samples(pack, cancelled) if pack.links else _samples(pack, cancelled)


def _link_samples(pack: Pack, cancelled: Callable[[], bool] | None) -> list[Sample]:
    """A links pack's first SAMPLES sounds, each fetched once (then kept with the other
    previews, under its own name: the list changing fetches only what's new)."""
    from soundboard.online import ytdl
    from soundboard.online.ytsites import temp_folder
    d = previews_dir() / f"{pack.id}-links"
    d.mkdir(parents=True, exist_ok=True)
    found, errs = [], []
    told = False
    for link in pack.links[:SAMPLES]:
        if cancelled is not None and cancelled():
            raise updates.UpdateError(_("Stopped."))
        kept = d / link.url.rsplit("/", 1)[-1]
        if not kept.is_file():
            if not told:
                netlog.cause(FEATURE, f"You opened Free packs: a few sounds of "
                                      f"{netlog.quoted(pack.name)} to try, from Myinstants")
                told = True
            tmp = temp_folder("sb-linkpreview-")
            try:
                got, _title = ytdl.download_audio(link.url, tmp, thumbnail=False)
                shutil.move(str(got), kept)
            except Exception as e:  # noqa: BLE001 - gone, offline, switched off
                log.info("pack %s: no sample from %s (%s)", pack.id, link.url, e)
                errs.append(errors.plain(e))
                continue
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        found.append(Sample(link.name, b"", kept))
    if not found and errs:
        raise updates.UpdateError(errs[0])
    return found


def _samples(pack: Pack, cancelled: Callable[[], bool] | None) -> list[Sample]:
    d = previews_dir()
    zpath = d / f"{pack.id}.zip"
    if not zpath.is_file():   # the first time only: then it's served from here
        netlog.cause(FEATURE, f"You opened Free packs: a few sounds of "
                              f"{netlog.quoted(pack.name)} to try")
    updates.fetch(pack.preview_url, pack.preview_sha256, zpath, (updates.DOWNLOADS,),
                  PREVIEW_MAX, "pack", pack.preview_size, None, cancelled, feature=FEATURE)
    from soundboard.core import backup  # it imports the library's heavier parts
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
