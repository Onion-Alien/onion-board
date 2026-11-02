"""The sound store (the Store tab): free sounds anyone can add to their board, voted up
or down, and shared by the people who made them.

Everything lives on the project's own small server (a Cloudflare Worker). Every sound
is CC0: whoever uploads one agrees it's theirs and gives it away, and nothing shows in
the store until it has been checked. The app sends a random id it made itself
(Config.store_id), so one install gets one vote per sound a day; the server only keeps a
salted hash of it. Nothing else about the user is sent, and the store has its own
switch in Settings > Privacy & security (FEATURE)."""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import threading
import time
import zlib
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from soundboard.sounds import library
from soundboard.online import net, netlog
from soundboard.i18n import _, ngettext

log = logging.getLogger(__name__)

FEATURE = "sound_store"   # its switch in Settings > Privacy & security (soundboard.online.net)
BASE = "https://onion-board-store.onion-alien.workers.dev"
AGREEMENT = "own-cc0-v1"    # the upload agreement's version (the server checks it)
LINK_AGREEMENT = "link-v1"  # sharing a link: only the link is kept
CONTACT = "onionboard.contact@proton.me"   # copyright and takedown requests
MAX_BYTES = 4 << 20         # the biggest sound the store takes
EXTS = (".mp3", ".ogg", ".wav", ".flac")   # what it takes (checked from the bytes there)
LIST_LIMIT = 1 << 20        # a page of the list is a few KB
CATALOG_LIMIT = 8 << 20     # every list's first page at once (/v1/catalog): a few hundred KB
ORDERS = ("trending", "top", "new")
REASONS = ("copyright", "offensive", "broken", "other")
# the store's categories (the server's CATS), then OURS; the dropdown shows them in the
# server's order (OURS first, then the biggest)
OURS = "onionboard"   # "Onion Board": the store's own sounds, shared by players or ours
SITE_CATS = ("memes", "reactions", "games", "movies", "tv", "music", "sports", "viral",
             "pranks", "politics", "streamer", "esports", "podcast", "spooky")   # a sound's
CATS = (*SITE_CATS, OURS)


def cat_name(key: str) -> str:
    """A category's name, in the app's language ("" for none or one this version doesn't
    know)."""
    return {"memes": _("Memes"), "reactions": _("Reactions"), "games": _("Games"),
            "movies": _("Movies"), "tv": _("TV"), "music": _("Music"), "sports": _("Sports"),
            "viral": _("Viral"), "pranks": _("Pranks"), "politics": _("Politics"),
            "streamer": _("Streaming"), "esports": _("Esports"), "podcast": _("Podcast"),
            "spooky": _("Spooky"), OURS: "Onion Board"}.get(key, "")
ID_LEN = 12


class StoreError(Exception):
    """What went wrong, in words for the user."""


class StoreDown(StoreError):
    """The store's server isn't working (it answered with an error of its own): nothing
    the user did, and nothing they can fix. `back`: when it said it's back (time.time()),
    0 when it didn't say."""

    def __init__(self, back: float = 0):
        self.back = back
        title, line = down_words(back)
        super().__init__(f"{title}. {line}")


def down_words(back: float = 0) -> tuple[str, str]:
    """The store's down: a title and a line for the card. `back` (time.time(), 0 for
    not known): the server's free daily allowance ran out and it said when it's back
    (midnight UTC), so it's down for maintenance for about that long."""
    if back:
        hours = round((back - time.time()) / 3600)
        if hours < 1:
            return (_("The store's down for maintenance"),
                    _("It'll be back in under an hour."))
        return (_("The store's down for maintenance"),
                ngettext("It'll be back in about {n} hour.",
                         "It'll be back in about {n} hours.", hours, n=hours))
    return (_("Sorry, the store's down"),
            _("We're working on getting it back up. Try again in a bit."))


_failing: set[str] = set()   # the calls (their paths, no query) the server last failed


def is_down() -> bool:
    """Whether the server failed one of its calls with an error of its own (a 500) and
    hasn't answered that call since: sharing is off until it does."""
    return bool(_failing)


def down_share() -> str:
    """Why sharing is greyed out."""
    return _("The store's down right now, so sharing is off. Try again later.")


@dataclass
class Sound:
    id: str
    name: str
    ext: str
    size: int = 0
    up: int = 0
    down: int = 0
    author: str = ""   # "" = shared by someone using the app
    created: int = 0
    mine: int = 0      # this install's vote: 1, -1 or 0
    tags: list[str] = field(default_factory=list)
    link: str = ""     # a shared link (ext "link"): no file, the site's own download
    cat: str = ""      # one of SITE_CATS, or none
    source: str = ""   # "myinstants": brought in from that site by the server; "" shared here

    @property
    def is_link(self) -> bool:
        return self.ext == "link"

    @property
    def score(self) -> int:
        return self.up - self.down

    @property
    def path(self) -> Path:
        """Where it's kept once fetched: the app folder's "store", in a folder of its
        own under its name (added to the board, the name comes from the file's)."""
        return library.APP_DIR / "store" / self.id / f"{library.file_stem(self.name)}.{self.ext}"


def install_id(cfg) -> str:
    """This install's random store id, made the first time it's needed."""
    if not getattr(cfg, "store_id", ""):
        cfg.store_id = str(uuid.UUID(bytes=secrets.token_bytes(16), version=4))
    return cfg.store_id


def parse(raw) -> tuple[list[Sound], bool]:
    """The sounds in a page of the list (anything odd is left out) and whether there
    are more."""
    out = []
    items = raw.get("sounds") if isinstance(raw, dict) else None
    for d in items if isinstance(items, list) else []:
        try:
            s = Sound(id=str(d["id"]), name=str(d["name"]).strip()[:60], ext=str(d["ext"]),
                      size=int(d.get("size") or 0), up=max(0, int(d.get("up") or 0)),
                      down=max(0, int(d.get("down") or 0)),
                      author=str(d.get("author") or "").strip()[:60],
                      created=int(d.get("created") or 0), mine=int(d.get("mine") or 0),
                      tags=[str(t)[:24] for t in d.get("tags") or [] if isinstance(t, str)][:8],
                      link=str(d.get("link") or "")[:500],
                      cat=str(d.get("cat") or "") if d.get("cat") in SITE_CATS else "",
                      source=str(d.get("source") or "")[:20])
        except (KeyError, TypeError, ValueError):
            continue
        if (len(s.id) != ID_LEN or not all(c in "0123456789abcdef" for c in s.id)
                or not (f".{s.ext}" in EXTS or (s.is_link and link_ok(s.link)))
                or not s.name or s.mine not in (-1, 0, 1)):
            continue
        out.append(s)
    return out, bool(isinstance(raw, dict) and raw.get("more"))


# a link in a name or tags (schemes, www., name.tld): the store refuses those, so the
# share window says so before sending (blocked words only the store knows)
_WORD_LINK = re.compile(
    r"(https?:|ftp:|file:|data:|javascript:|www\.|\b[a-z0-9-]{2,}\.(com|net|org|io|gg|ly|me|"
    r"co|tv|xyz|app|dev|ru|to|cc|info|biz|site|online|shop|top|link|click|su|pw|cn|uk)\b|"
    r"discord\.gg|[a-z0-9-]+\.[a-z]{2,}/)", re.I)


def check_words(name: str, tags: str = "") -> str:
    """Why the store won't take this name or these tags, or "" (as far as the app can
    tell: only the store knows its blocked words)."""
    if _WORD_LINK.search(name[:60]) or _WORD_LINK.search(tags[:200]):
        return _("Names and tags can't have links in them.")
    return ""


def link_ok(url: str) -> bool:
    """A link the store keeps: https, on one of the video and sound sites the app knows
    (sourceinfo), never any other web address."""
    from soundboard.sounds import sourceinfo
    found = sourceinfo.site_of(url)
    return url.startswith("https://") and found is not None and found[0] != "web"


def _request(method: str, path: str, install: str = "", body: bytes | None = None,
             ctype: str = "", limit: int = LIST_LIMIT, timeout: float = 15,
             why: Callable[[int, str], str] | None = None, packed: bool = False) -> bytes:
    """One call to the store; its answer. Raises StoreError (or net.ProxyError when the
    store is switched off or Offline), saying why in `why(status, error)`'s words (the
    sounds' by default). Call off the UI thread."""
    headers = {"User-Agent": "OnionBoard (sound store)"}
    if packed:   # (gzipped on the way: a fifth of the size)
        headers["Accept-Encoding"] = "gzip"
    if install:
        headers["X-Onion-Install"] = install
    if ctype:
        headers["Content-Type"] = ctype
    req = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    key = path.split("?", 1)[0]
    try:
        with net.urlopen(req, timeout=timeout, feature=FEATURE) as r:
            data = r.read(limit + 1)
            gzipped = packed and r.headers.get("Content-Encoding", "").lower() == "gzip"
    except urllib.error.HTTPError as e:
        try:
            said = json.loads(e.read(4096) or b"{}")
            err = str(said.get("error", ""))
        except (ValueError, AttributeError):
            said, err = {}, ""
        if e.code >= 500 and err not in ("queue full", "store full"):
            _failing.add(key)
            # the free plan's daily allowance ran out: it says how long until it's back
            wait = said.get("in") if err == "maintenance" else None
            ok = isinstance(wait, int) and 0 < wait <= 2 * 86400
            raise StoreDown(time.time() + wait if isinstance(wait, int) and ok else 0) from None
        raise StoreError((why or _why)(e.code, err)) from None
    except net.ProxyError:
        raise
    except OSError as e:
        log.info("store %s %s failed: %s", method, path, e)
        raise StoreError(_("Couldn't reach the sound store. Check your internet and try "
                           "again.")) from None
    _failing.discard(key)
    if packed and gzipped:
        try:
            data = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(data, limit + 1)
        except zlib.error:
            raise StoreError(_("The sound store had a problem. Try again in a bit.")) from None
    if len(data) > limit:
        raise StoreError(_("The sound store sent more than it should, so it was left."))
    return data


def _why(code: int, err: str) -> str:
    if err == "duplicate":
        return _("That sound is already in the store.")
    if err == "slow down" or code == 429:
        return _("That's a lot for one day. Try again tomorrow.")
    if err == "too big" or code == 413:
        return _("That file is too big: the store takes sounds up to 4 MB.")
    if err == "not audio" or code == 415:
        return _("That file isn't a sound the store takes (MP3, OGG, WAV or FLAC).")
    if err == "not allowed":
        return _("The store doesn't take that name or those tags. Try other words "
                 "(and no links).")
    if err == "bad link":
        return _("The store takes links to YouTube, TikTok, SoundCloud and other video "
                 "and sound sites.")
    if err == "queue full" or code == 503:
        return _("Lots of sounds are waiting to be checked. Try again in a day or two.")
    if code == 404:
        return _("That sound isn't in the store any more.")
    return _("The sound store had a problem. Try again in a bit.")


def browse(install: str, sort: str = "top", query: str = "", offset: int = 0,
           cat: str = "") -> tuple[list[Sound], bool]:
    """A page of the store: the best first ("top"), the newest ("new") or what's hot now
    ("trending"), only those in category `cat` and matching `query` when they're given.
    Call off the UI thread."""
    netlog.cause(FEATURE, "You opened the Store tab: reading the list of sounds")
    q = urllib.parse.urlencode({"sort": sort if sort in ("new", "trending") else "top",
                                **({"cat": cat} if cat in CATS else {}),
                                **({"q": query[:60]} if query.strip() else {}),
                                **({"offset": offset} if offset else {})})
    data = _request("GET", f"/v1/sounds?{q}", install)
    try:
        return parse(json.loads(data.decode("utf-8")))
    except ValueError:
        raise StoreError(_("The sound store had a problem. Try again in a bit.")) from None


def categories(install: str) -> tuple[list[tuple[str, int]], int]:
    """The categories with sounds in them, the biggest first, as (key, how many), and how
    many sounds there are in all. Call off the UI thread."""
    netlog.cause(FEATURE, "You opened the Store tab: reading its categories")
    data = _request("GET", "/v1/categories", install)
    try:
        return _cats(json.loads(data.decode("utf-8")))
    except (ValueError, TypeError, KeyError, AttributeError):
        raise StoreError(_("The sound store had a problem. Try again in a bit.")) from None


def _cats(raw) -> tuple[list[tuple[str, int]], int]:
    cats = [(str(c["cat"]), max(0, int(c["n"]))) for c in raw.get("categories") or ()
            if isinstance(c, dict) and c.get("cat") in CATS]
    return cats, max(0, int(raw.get("total") or 0))


# ------------------------------------------------------------------ every list at once
@dataclass
class Catalog:
    """Every list the tab opens on, as the store last built it (every 30 minutes): the
    first page of each order of every sound, of the store's own and of each category,
    and the categories with how many. Got once a launch and kept on disk, so the tab and
    every category show at once; Show more, a search and Refresh still ask the store.
    It's the same for everyone, so it has no one's own votes: `with_my_votes` puts them on."""
    built: int                                              # when (the server's time.time())
    lists: dict[tuple[str, str], tuple[list[Sound], bool]]   # (order, category): (sounds, more)
    cats: list[tuple[str, int]]
    total: int

    def get(self, sort: str, cat: str) -> tuple[list[Sound], bool] | None:
        """A list's first page (copies: votes change them), None when it isn't in it."""
        got = self.lists.get((sort, cat))
        if got is None:
            return None
        return with_my_votes([replace(s, tags=list(s.tags)) for s in got[0]], self.built), got[1]


def parse_catalog(data: bytes) -> Catalog | None:
    """/v1/catalog's answer (or the copy kept on disk); None when it isn't one."""
    try:
        raw = json.loads(data.decode("utf-8"))
        sounds, lists = raw["sounds"], raw["lists"]
        built = int(raw.get("built") or 0)
        cats, total = _cats(raw.get("categories") or {})
    except (ValueError, TypeError, KeyError, AttributeError):
        return None
    if not isinstance(sounds, dict) or not isinstance(lists, dict):
        return None
    known = {s.id: s for s in parse({"sounds": list(sounds.values())})[0]}
    got: dict[tuple[str, str], tuple[list[Sound], bool]] = {}
    for key, v in lists.items():
        sort, _sep, cat = str(key).partition(":")
        ids = v.get("ids") if isinstance(v, dict) else None
        if sort in ORDERS and (not cat or cat in CATS) and isinstance(ids, list):
            got[(sort, cat)] = ([known[i] for i in ids if isinstance(i, str) and i in known],
                                bool(v.get("more")))
    return Catalog(built, got, cats, total)


def _catalog_file() -> Path:
    return library.APP_DIR / "store" / "catalog.json"


def saved_catalog() -> Catalog | None:
    """The catalog got last time (None: none yet). Call off the UI thread."""
    try:
        return parse_catalog(_catalog_file().read_bytes())
    except OSError:
        return None


def fetch_catalog() -> Catalog:
    """Every list's first page from the store, kept on disk for the next launch. No
    install id: it's the same for everyone. Call off the UI thread."""
    netlog.cause(FEATURE, "Onion Board started: reading the sound store's lists")
    data = _request("GET", "/v1/catalog", limit=CATALOG_LIMIT, timeout=30, packed=True)
    got = parse_catalog(data)
    if got is None:
        raise StoreError(_("The sound store had a problem. Try again in a bit."))
    _write(_catalog_file(), data)
    return got


def _write(path: Path, data: bytes):
    """(Whole or not at all: a crash halfway never leaves half a file.)"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except OSError as e:
        log.info("couldn't keep %s: %s", path.name, e)


# this install's own votes, kept on disk: (value, day, up, down, when) by sound id. The
# catalog is the same for everyone, so these show which thumb is yours (one vote a day,
# as the server counts them) and the counts your vote made until it's built again.
_votes: tuple[Path, dict[str, tuple[int, int, int, int, float]]] | None = None   # (its file, them)
_votes_lock = threading.Lock()
VOTES_KEEP_S = 2 * 86400


def _votes_file() -> Path:
    return library.APP_DIR / "store" / "votes.json"


def _my_votes() -> dict[str, tuple[int, int, int, int, float]]:
    global _votes
    path = _votes_file()
    with _votes_lock:
        if _votes is None or _votes[0] != path:
            got: dict[str, tuple[int, int, int, int, float]] = {}
            try:
                raw = json.loads(path.read_text("utf-8"))
                for sid, v in raw.items() if isinstance(raw, dict) else ():
                    value, day, up, down, at = v
                    got[str(sid)] = (int(value), int(day), int(up), int(down), float(at))
            except (OSError, ValueError, TypeError):
                pass
            _votes = (path, got)
        return _votes[1]


def keep_vote(sound_id: str, up: int, down: int, mine: int):
    """A vote the store took (its new counts and this install's vote). Call off the UI
    thread."""
    votes = _my_votes()
    now = time.time()
    with _votes_lock:
        votes[sound_id] = (mine, int(now // 86400), up, down, now)
        for sid in [k for k, v in votes.items() if now - v[4] > VOTES_KEEP_S]:
            del votes[sid]
        data = json.dumps(votes).encode("utf-8")
    _write(_votes_file(), data)


def with_my_votes(sounds: list[Sound], built: float) -> list[Sound]:
    """`sounds` from a list built at `built` with this install's votes on them."""
    votes = _my_votes()
    today = int(time.time() // 86400)
    for s in sounds:
        v = votes.get(s.id)
        if v is None:
            continue
        if v[1] == today:
            s.mine = v[0]
        if v[4] > built:   # (voted after it was built: the counts it got then)
            s.up, s.down = v[2], v[3]
    return sounds


def looks_like(data: bytes, ext: str) -> bool:
    """Whether `data` starts the way an `ext` sound does (mp3, ogg, wav, flac). The server
    walks each whole file before it takes it; this only stops anything else being kept."""
    if len(data) < 12:
        return False
    if ext == "mp3":
        return data[:3] == b"ID3" or (data[0] == 0xFF and data[1] & 0xE0 == 0xE0)
    return {"ogg": data[:4] == b"OggS", "flac": data[:4] == b"fLaC",
            "wav": data[:4] == b"RIFF" and data[8:12] == b"WAVE"}.get(ext, False)


def fetch(sound: Sound) -> Path:
    """The sound's file, fetched once into the app folder's "store". Call off the UI
    thread."""
    p = sound.path
    if p.is_file() and p.stat().st_size:
        return p
    root = (library.APP_DIR / "store").resolve()
    if sound.is_link or not p.resolve().is_relative_to(root):
        raise StoreError(_("The sound store had a problem. Try again in a bit."))
    netlog.cause(FEATURE, f"You played or added {netlog.quoted(sound.name)} from the store")
    data = _request("GET", f"/v1/sounds/{sound.id}/file", limit=MAX_BYTES, timeout=30)
    if not data or not looks_like(data, sound.ext):
        # the server checks every file it takes; this is in case it ever sends something else
        log.warning("store sound %s isn't the %s it should be: not kept", sound.id, sound.ext)
        raise StoreError(_("The sound store had a problem. Try again in a bit."))
    p.parent.mkdir(parents=True, exist_ok=True)
    part = p.with_name(p.name + ".part")
    part.write_bytes(data)
    part.replace(p)
    return p


def vote(install: str, sound_id: str, value: int) -> tuple[int, int, int]:
    """Thumbs up (1), down (-1) or neither (0); the sound's new (up, down, mine)."""
    netlog.cause(FEATURE, "You voted on a sound in the store")
    data = _request("POST", f"/v1/sounds/{sound_id}/vote", install,
                    json.dumps({"value": value}).encode(), "application/json")
    try:
        d = json.loads(data.decode("utf-8"))
        got = int(d["up"]), int(d["down"]), int(d["mine"])
    except (ValueError, KeyError, TypeError):
        raise StoreError(_("The sound store had a problem. Try again in a bit.")) from None
    keep_vote(sound_id, *got)
    return got


def report(install: str, sound_id: str, reason: str) -> None:
    """Tell the store a sound breaks the rules (REASONS)."""
    netlog.cause(FEATURE, "You reported a sound in the store")
    _request("POST", f"/v1/sounds/{sound_id}/report", install,
             json.dumps({"reason": reason if reason in REASONS else "other"}).encode(),
             "application/json")


def check_file(path: str) -> str:
    """Why `path` can't be uploaded, or "" when it can."""
    p = Path(path)
    if p.suffix.lower() not in EXTS:
        return _("The store takes MP3, OGG, WAV or FLAC files.")
    try:
        size = p.stat().st_size
    except OSError:
        return _("That file can't be opened.")
    if not size:
        return _("That file is empty.")
    if size > MAX_BYTES:
        return _("That file is too big: the store takes sounds up to 4 MB.")
    return ""


def _form(fields: dict[str, str], file_name: str, data: bytes) -> tuple[bytes, str]:
    """A multipart form with `fields` and the file; (body, content type). `file_name` is
    never the file's own ("sound.mp3"): a name on this PC says nothing to the store."""
    b = secrets.token_hex(16)
    out = []
    for k, v in fields.items():
        out.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n'
                   .encode() + v.encode("utf-8") + b"\r\n")
    safe = "".join(c for c in file_name if c.isalnum() or c in "._-")[:60] or "sound"
    out.append(f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{safe}"\r\n'
               "Content-Type: application/octet-stream\r\n\r\n".encode() + data + b"\r\n")
    out.append(f"--{b}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={b}"


def upload(install: str, path: str, name: str, tags: str = "") -> str:
    """Share a sound: it waits to be checked before it shows. Its id. Raises
    StoreError. Call off the UI thread."""
    if why := check_file(path) or check_words(name, tags):
        raise StoreError(why)
    netlog.cause(FEATURE, f"You shared {netlog.quoted(name)} with the store")
    try:
        data = Path(path).read_bytes()
    except OSError:
        raise StoreError(_("That file can't be opened.")) from None
    body, ctype = _form({"name": name.strip()[:60], "tags": tags.strip()[:200],
                         "agree": AGREEMENT}, "sound" + Path(path).suffix.lower(), data)
    out = _request("POST", "/v1/sounds", install, body, ctype, timeout=60)
    try:
        return str(json.loads(out.decode("utf-8"))["id"])
    except (ValueError, KeyError, TypeError):
        raise StoreError(_("The sound store had a problem. Try again in a bit.")) from None


def share_link(install: str, link: str, name: str, tags: str = "") -> str:
    """Share a link (a YouTube video…): only the link is kept, and it waits to be
    checked. Whoever adds it downloads it from the site. Its id. Raises StoreError."""
    link = link.strip()
    if not link_ok(link):
        raise StoreError(_("The store takes links to YouTube, TikTok, SoundCloud and other "
                           "video and sound sites."))
    if why := check_words(name, tags):
        raise StoreError(why)
    netlog.cause(FEATURE, f"You shared a link to {netlog.quoted(name)} with the store")
    body = json.dumps({"link": link[:500], "name": name.strip()[:60], "tags": tags.strip()[:200],
                       "agree": LINK_AGREEMENT}).encode()
    out = _request("POST", "/v1/links", install, body, "application/json")
    try:
        return str(json.loads(out.decode("utf-8"))["id"])
    except (ValueError, KeyError, TypeError):
        raise StoreError(_("The sound store had a problem. Try again in a bit.")) from None
