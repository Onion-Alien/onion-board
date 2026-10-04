"""Download the audio of a web link, with yt-dlp.

Used by the Sounds tab's link bar ("Add as sound" / "Play once"): yt-dlp fetches the
best audio stream the site offers (YouTube, SoundCloud, and the other sites it supports) into
a temporary folder, and the file is then imported like a dropped file (so m4a /
webm audio needs ffmpeg, as it does for a dropped file). Nothing is converted to
MP3 on the way: the library stores it losslessly as a FLAC of what was decoded.

yt-dlp is imported lazily: it's a big package and only needed on click.

Keeping it working: YouTube changes often and yt-dlp follows within days, but the
built app can't pip-install. So a newer yt-dlp is fetched from PyPI (the wheels of
yt-dlp and its pinned yt-dlp-ejs, checked against PyPI's SHA-256) and unpacked into
%APPDATA%\\OnionBoard\\yt-dlp\\current; an import hook (_Finder) makes that copy win
over the bundled one. That only happens when the user asks (Settings → Updates:
Update now / Reset), or, if they opted in (off by default: it's code the app runs),
once a day and when a download fails. "Reset" deletes the copy and its cache and fetches
a fresh one. A copy older than the bundled yt-dlp (the app itself was updated) is
dropped at startup.
"""
from __future__ import annotations

import contextlib
import hashlib
import html
import importlib.abc
import importlib.machinery
import io
import json
import logging
import re
import shutil
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from soundboard import library, net, quality
from soundboard.library import MAX_SECONDS
from soundboard import errors

log = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".image"}   # thumbnails
MAX_BYTES = 200 * 1024 * 1024   # an audio stream bigger than this isn't a sound
VIDEO_MAX_BYTES = 1024 * 1024 * 1024   # ...and with the video kept (Settings > Data)
VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov"}
PACKAGES = ("yt_dlp", "yt_dlp_ejs")
PYPI = "https://pypi.org/pypi/{}/json"
WHEEL_HOST = "https://files.pythonhosted.org/"
CHECK_EVERY = 24 * 3600          # automatic update check
RETRY_CHECK_AFTER = 3600         # a failed download checks again if the last check is older
WHEEL_MAX = 30 * 1024 * 1024

class _SharedLock:
    """Searches, lookups and downloads share yt-dlp (one slow site mustn't hold up
    the rest); swapping in a new copy waits until none of them is using it."""

    def __init__(self):
        self._cond = threading.Condition()
        self._users = 0
        self._swapping = False

    @contextlib.contextmanager
    def shared(self):
        with self._cond:
            self._cond.wait_for(lambda: not self._swapping)
            self._users += 1
        try:
            yield
        finally:
            with self._cond:
                self._users -= 1
                self._cond.notify_all()

    @contextlib.contextmanager
    def exclusive(self):
        with self._cond:
            self._cond.wait_for(lambda: not self._swapping and not self._users)
            self._swapping = True
        try:
            yield
        finally:
            with self._cond:
                self._swapping = False
                self._cond.notify_all()


_lock = _SharedLock()   # a download and swapping in a new copy never overlap


class DownloadError(RuntimeError):
    pass


class FetchError(DownloadError):
    """yt-dlp itself failed (vs. something we refused): a newer yt-dlp may fix it."""


class SwitchedOff(DownloadError):
    """The site (or finding sounds online at all) is switched off in Settings > Privacy
    & security: nothing was looked up or sent. The message says so."""


FEATURE = "sounds_web"           # soundboard.net's switch for all of this
UPDATE_FEATURE = "ytdlp_update"  # ...and for updating yt-dlp from PyPI


def site_of(target: str) -> str:
    """Which of net.SITES a search source (a key of SOURCES) or a link belongs to.
    TikTok's button searches YouTube, so it's YouTube's; a pasted TikTok link is
    "other"."""
    if target in SOURCES:
        return {"soundcloud": "soundcloud", "myinstants": "myinstants"}.get(target, "youtube")
    host = (urllib.parse.urlsplit(target).hostname or "").lower().rstrip(".")

    def under(*domains):
        return any(host == d or host.endswith("." + d) for d in domains)
    if under("youtube.com", "youtu.be", "youtube-nocookie.com"):
        return "youtube"
    if under("soundcloud.com", "snd.sc"):
        return "soundcloud"
    if under("myinstants.com"):
        return "myinstants"
    return "other"


def site_feature(target: str) -> str:
    """The key the requests for `target` carry: "sounds_web.<site>"."""
    return f"{FEATURE}.{site_of(target)}"


def site_allowed(target: str) -> bool:
    return net.allowed(site_feature(target))


def _gate(target: str) -> str:
    """The site's feature key, or SwitchedOff (before anything goes online)."""
    feature = site_feature(target)
    if not net.allowed(feature):
        raise SwitchedOff(net.off_message(feature))
    return feature


class TorBlocked(FetchError):
    """In Tor mode, the site turned Tor away even after TOR_TRIES new identities. The
    UI offers "Try this one without Tor"; only that click (direct=True) goes direct."""


# YouTube (and others) turning a Tor exit away: "Sign in to confirm you're not a bot",
# rate limits and refusals. Retried over a new Tor identity, never directly.
TOR_TRIES = 3
_TOR_BLOCKED = re.compile(r"not a bot|confirm you.?re not|HTTP Error 429|Too Many Requests|"
                          r"HTTP Error 403|unusual traffic|try again later", re.I)


def blocked_by_site(msg: str) -> bool:
    return bool(_TOR_BLOCKED.search(msg or ""))


def _site_name(target: str) -> str:
    host = urllib.parse.urlsplit(target).hostname or ""
    if not host or "youtube" in host or "youtu.be" in host:
        return "YouTube"
    return host.removeprefix("www.")


def _over_tor(fn, target: str):
    """fn(), and in Tor mode, when the site turns the Tor exit away, a new Tor identity
    and another try, up to TOR_TRIES times. Never falls back to a direct connection:
    the last refusal is raised as TorBlocked for the UI to offer that."""
    if net.mode() != net.TOR:
        return fn()
    from soundboard import tor
    for attempt in range(TOR_TRIES + 1):
        try:
            return fn()
        except SwitchedOff:
            raise
        except DownloadError as e:
            if not blocked_by_site(f"{e} {getattr(e, 'raw', '')}"):
                raise
            if not site_allowed(target):   # switched off meanwhile: no more tries
                raise SwitchedOff(net.off_message(site_feature(target))) from None
            if attempt == TOR_TRIES:
                site = _site_name(target)
                raise TorBlocked(
                    f"{site} turned Tor away ({site} often blocks Tor's addresses), and "
                    f"so did {TOR_TRIES} other Tor routes. You can try this one without "
                    f"Tor: {site} would then see your own address.") from e
            log.info("site turned Tor away (%s); new identity, try %d of %d",
                     str(e)[:120], attempt + 1, TOR_TRIES)
            tor.new_identity()


# ---------------------------------------------------------------------- the updated copy

def root() -> Path:
    return library.APP_DIR / "yt-dlp"


def _pkg_dir() -> Path:
    return root() / "current"


def cache_dir() -> Path:
    return root() / "cache"


def _state() -> dict:
    try:
        return json.loads((root() / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(**kw):
    s = _state() | kw
    try:
        root().mkdir(parents=True, exist_ok=True)
        (root() / "state.json").write_text(json.dumps(s), encoding="utf-8")
    except OSError:
        log.warning("couldn't save yt-dlp update state", exc_info=True)


def vtuple(v: str) -> tuple[int, ...]:
    """'2026.08.19' / '2026.8.19.123' -> comparable ints ('' -> ())."""
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def bundled_version() -> str:
    """The yt-dlp that shipped with the app (or is pip-installed, from source)."""
    try:
        from importlib.metadata import version
        return version("yt-dlp")
    except Exception:  # noqa: BLE001 - frozen without metadata, or not installed
        return ""


def override_version() -> str:
    """The downloaded copy's version, if there is one."""
    return _state().get("version", "") if (_pkg_dir() / "yt_dlp").is_dir() else ""


def active_version() -> tuple[str, bool]:
    """(version in use, is it the downloaded copy?)."""
    ov = override_version()
    return (ov, True) if ov else (bundled_version(), False)


class _Finder(importlib.abc.MetaPathFinder):
    """Serves yt_dlp / yt_dlp_ejs from the downloaded copy when there is one. First on
    sys.meta_path, so it also wins over PyInstaller's importer in the built app."""

    def find_spec(self, name, path=None, target=None):
        top = name.partition(".")[0]
        if top not in PACKAGES:
            return None
        base = _pkg_dir()
        if "." in name:
            parent = sys.modules.get(name.rpartition(".")[0])
            search = list(getattr(parent, "__path__", None) or ())
            if not search or not str(search[0]).startswith(str(base)):
                return None   # the parent is the bundled copy: leave it alone
        elif (base / top).is_dir():
            search = [str(base)]
        else:
            return None
        return importlib.machinery.PathFinder.find_spec(name, search)


_finder = _Finder()


def install():
    """Put the import hook in place (idempotent), dropping a stale downloaded copy."""
    if _finder not in sys.meta_path:
        _tidy()
        ov, bv = override_version(), bundled_version()
        if ov and bv and vtuple(ov) < vtuple(bv):
            log.info("dropping downloaded yt-dlp %s: the app ships %s", ov, bv)
            shutil.rmtree(_pkg_dir(), ignore_errors=True)
        sys.meta_path.insert(0, _finder)


def _tidy():
    """Clear what an update cut short left behind: a half-unpacked new-* folder, and
    old-* copies (one is put back first if the swap stopped before `current` was)."""
    try:
        olds = sorted(root().glob("old-*"), key=lambda d: d.stat().st_mtime)
        if olds and not _pkg_dir().exists():
            olds.pop().rename(_pkg_dir())
            log.info("put back the yt-dlp copy an update had moved aside")
        for d in olds + list(root().glob("new-*")):
            shutil.rmtree(d, ignore_errors=True)
    except OSError:
        log.warning("couldn't tidy %s", root(), exc_info=True)


def _purge():
    """Forget imported yt-dlp modules so the next import picks up the new copy."""
    for name in [n for n in sys.modules if n.partition(".")[0] in PACKAGES]:
        del sys.modules[name]
    importlib.invalidate_caches()


def _get(url: str, limit: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "OnionBoard (yt-dlp updater)"})
    with net.urlopen(req, timeout=30, feature=UPDATE_FEATURE) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise DownloadError(f"{url} is unexpectedly large")
    return data


def _wheel(meta: dict) -> bytes:
    """The pure-Python wheel from a PyPI JSON release, verified by its SHA-256."""
    for f in meta.get("urls", ()):
        if f.get("packagetype") == "bdist_wheel" and f["filename"].endswith("-py3-none-any.whl"):
            if not f["url"].startswith(WHEEL_HOST):
                raise DownloadError(f"unexpected download location for {f['filename']}")
            data = _get(f["url"], WHEEL_MAX)
            if hashlib.sha256(data).hexdigest() != f["digests"]["sha256"]:
                raise DownloadError(f"{f['filename']} failed its checksum")
            return data
    raise DownloadError(f"no wheel for {meta.get('info', {}).get('name')}")


def update(force: bool = False) -> str:
    """Fetch the latest yt-dlp if it's newer than what's in use (or always, with
    force). Returns a short message for the user; raises DownloadError on failure
    (SwitchedOff when updating it is switched off in Settings > Privacy & security)."""
    if not net.allowed(UPDATE_FEATURE):
        raise SwitchedOff(net.off_message(UPDATE_FEATURE))
    try:
        meta = json.loads(_get(PYPI.format("yt-dlp"), 5 * 1024 * 1024))
        latest = str(meta["info"]["version"])
    except (ValueError, KeyError, TypeError) as e:
        raise DownloadError("PyPI sent an answer that couldn't be read") from e
    current, _ = active_version()
    _save_state(checked=time.time())
    if not force and current and vtuple(latest) <= vtuple(current):
        return f"yt-dlp {current} is up to date."
    wheels = [_wheel(meta)]
    pin = next((m.group(1) for r in meta["info"].get("requires_dist") or ()
                if (m := re.match(r"yt-dlp-ejs\s*==\s*([\w.]+)", r))), None)
    if pin:
        wheels.append(_wheel(json.loads(_get(f"https://pypi.org/pypi/yt-dlp-ejs/{pin}/json",
                                             5 * 1024 * 1024))))
    root().mkdir(parents=True, exist_ok=True)
    new = Path(tempfile.mkdtemp(prefix="new-", dir=root()))
    try:
        for data in wheels:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                z.extractall(new, [n for n in z.namelist() if n.split("/")[0] in PACKAGES])
        if not (new / "yt_dlp" / "__init__.py").is_file():
            raise DownloadError("the yt-dlp wheel didn't contain yt_dlp")
        with _lock.exclusive():   # not while a download is using the old copy
            old = root() / f"old-{time.time_ns()}"
            if _pkg_dir().exists():
                _pkg_dir().rename(old)
            try:
                new.rename(_pkg_dir())
            except OSError as e:   # put the copy in use back, or downloads break
                if old.exists():
                    old.rename(_pkg_dir())
                raise DownloadError(f"couldn't swap in the new yt-dlp ({errors.plain(e)})") from e
            shutil.rmtree(old, ignore_errors=True)
            _save_state(version=latest)
            _purge()
    finally:
        shutil.rmtree(new, ignore_errors=True)
    log.info("yt-dlp updated to %s", latest)
    return f"Updated yt-dlp to {latest}."


def reset() -> str:
    """For when it's thoroughly broken: delete the downloaded copy and yt-dlp's cache,
    then download the latest again (falling back to the bundled one if that fails).
    Switched off, it does nothing (raises SwitchedOff): a reset that can't fetch a
    fresh copy would only throw the working one away."""
    if not net.allowed(UPDATE_FEATURE):
        raise SwitchedOff(net.off_message(UPDATE_FEATURE))
    with _lock.exclusive():
        shutil.rmtree(root(), ignore_errors=True)
        _purge()
    try:
        update(force=True)
        return f"Reinstalled yt-dlp {override_version()}."
    except Exception as e:  # noqa: BLE001
        log.warning("yt-dlp reinstall failed: %s", e)
        v = bundled_version()
        return (f"Cleared, but couldn't download a fresh copy ({errors.plain(e)}). "
                + (f"Using the built-in yt-dlp {v}." if v else "Try again when you're online."))


def due(every: float = CHECK_EVERY) -> bool:
    return time.time() - float(_state().get("checked", 0)) >= every


def auto_update(enabled: bool):
    """The daily background check (call from a thread); switched off in Settings >
    Privacy & security, it skips itself."""
    if not enabled or not net.allowed(UPDATE_FEATURE) or not due():
        return
    try:
        log.info(update())
    except Exception as e:  # noqa: BLE001 - offline etc.: try again next time
        log.info("yt-dlp update check failed: %s", e)


# ---------------------------------------------------------------------- downloading

def downloadable(url: str) -> bool:
    """Worth offering "Add as sound" for: a video / track page, not a site's home
    page or a search. yt-dlp decides for real; this only greys the button out."""
    m = re.match(r"https?://(?:[\w-]+\.)*([\w-]+\.[a-z]+)(/[^?#]*)?(\?[^#]*)?", url, re.I)
    if not m:
        return False
    host, path, query = m.group(1).lower(), m.group(2) or "", m.group(3) or ""
    if host in ("youtube.com", "youtu.be"):
        return bool(re.search(r"[?&]v=[\w-]{6,}", query)) or \
            bool(re.match(r"/(shorts|live|embed)/[\w-]{6,}", path)) or \
            (host == "youtu.be" and len(path) > 6)
    return path.strip("/") != "" and not path.startswith(("/search", "/results"))


def as_link(text: str) -> str:
    """`text` as a web link if it is one ("www.…" gets https://), else "". Only
    http(s): a typed file:// or data: link is never handed to yt-dlp."""
    t = text.strip()
    if re.match(r"www\.[\w-]+\.", t, re.I):
        t = "https://" + t
    return t if re.fullmatch(r"https?://[\w.-]+\.[a-z]{2,}(:\d+)?([/?#]\S*)?", t, re.I) else ""


def clean_title(title: str) -> str:
    """A pad name from a video title: no "(Official Video)" / "[HD]" noise."""
    t = re.sub(r"\s*[(\[][^)\]]*\b(official|video|audio|lyrics?|hd|4k|visuali[sz]er)\b[^)\]]*[)\]]",
               "", title, flags=re.I)
    return re.sub(r"\s+", " ", t).strip() or title.strip()


def download_audio(url: str, dest: Path | None = None,
                   progress: Callable[[float], None] | None = None,
                   auto_update: bool = True, direct: bool = False,
                   video: bool = False) -> tuple[Path, str]:
    """Download the audio of `url` into `dest` (a new temp folder by default), at
    Settings > Data & quality's download quality; with `video`, the video with its
    sound in one file (save_video() keeps a copy, the pad is still decoded from it).

    Returns (file, title). `progress` gets 0..1 while it downloads. If yt-dlp fails
    and no update check ran in the last hour, it updates yt-dlp and tries once more.
    Raises DownloadError with a message fit to show the user (SwitchedOff when its
    site is switched off in Settings > Privacy & security, TorBlocked when the site
    turned Tor away). `direct` skips the Connection setting (not the switches) for
    this one download: only for the user's own "Try this one without Tor" click."""
    feature = _gate(url)
    if url.startswith(MYINSTANTS + "/media/sounds/"):
        if direct:
            return _download_direct(url, dest, progress, direct=True)
        return _over_tor(lambda: _download_direct(url, dest, progress), url)

    extra = {"video": True} if video else {}

    def fetch():
        if direct:
            return _download(url, dest, progress, feature, direct=True, **extra)
        return _over_tor(lambda: _download(url, dest, progress, feature, **extra), url)
    try:
        return fetch()
    except FetchError as e:
        if (isinstance(e, TorBlocked) or not auto_update or not due(RETRY_CHECK_AFTER)
                or not net.allowed(UPDATE_FEATURE)):
            raise
        try:
            msg = update()
        except Exception as ue:  # noqa: BLE001
            log.info("yt-dlp update after a failed download didn't work: %s", ue)
            raise e from None
        if msg.startswith("Updated"):
            log.info("%s Retrying %s", msg, url)
            return fetch()
        raise


def probe(url: str, direct: bool = False) -> tuple[str, float]:
    """Look `url` up without downloading anything: (clean title, seconds or 0).
    Raises DownloadError like download_audio (but never updates yt-dlp)."""
    feature = _gate(url)
    if url.startswith(MYINSTANTS + "/media/sounds/"):
        return _direct_title(url), 0.0

    def look():
        with _ydl() as yt_dlp:
            try:
                with yt_dlp.YoutubeDL(_opts(feature=feature, direct=direct)) as ydl:
                    return _check(ydl.extract_info(url, download=False))
            except DownloadError:
                raise
            except Exception as e:  # noqa: BLE001 - yt-dlp raises many kinds; show its message
                raise _readable(e) from e
    info = look() if direct else _over_tor(look, url)
    return clean_title(info.get("title") or "") or "Sound", float(info.get("duration") or 0)


# The sites search() can look things up on: key -> (button name, what it searches).
# "ytsearch"/"scsearch" are yt-dlp's own searches; "ytmusic" is YouTube Music's
# search page; "myinstants" is scraped here (meme sound buttons, plain MP3s).
# TikTok has no search without an account, so its button searches YouTube for the
# TikTok sound (most get reposted there); a pasted TikTok link still downloads.
SOURCES = {"youtube": ("YouTube", "ytsearch"),
           "ytmusic": ("YouTube Music", "ytmusic"),
           "soundcloud": ("SoundCloud", "scsearch"),
           "tiktok": ("TikTok", "ytsearch"),
           "myinstants": ("Myinstants", "myinstants")}
TIKTOK_SUFFIX = " tiktok sound"
MYINSTANTS = "https://www.myinstants.com"
BROWSER_HEADERS = {   # Myinstants' Cloudflare turns away urllib's default User-Agent
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/140.0 Safari/537.36",
    "Accept": "text/html,audio/*,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9",
    "Referer": MYINSTANTS + "/"}


@dataclass
class Result:
    """One search hit (see search)."""
    id: str
    title: str
    channel: str
    seconds: float     # 0 when the site didn't say
    source: str = "youtube"
    link: str = ""     # the page to download (YouTube's is built from the id)
    art: str = ""      # thumbnail / cover art (YouTube's is built from the id)
    views: int | None = None      # None: the site didn't say (yet: see stats)
    likes: int | None = None
    comments: int | None = None

    @property
    def url(self) -> str:
        return self.link or f"https://www.youtube.com/watch?v={self.id}"

    @property
    def thumb(self) -> str:
        """"" when there's none (Myinstants' buttons have no picture)."""
        if self.art or self.source != "youtube":
            return self.art
        return f"https://i.ytimg.com/vi/{self.id}/mqdefault.jpg"


def search(query: str, count: int = 20, source: str = "youtube",
           direct: bool = False) -> list[Result]:
    """Search one of SOURCES (one results page, nothing downloaded). Live streams
    and junk entries are left out. Raises DownloadError like probe (TorBlocked when
    the site turned Tor away; `direct` is the user's "without Tor" click)."""
    query = " ".join(query.split())
    if not query:
        return []
    kind = SOURCES[source][1]
    feature = _gate(source)
    if kind == "myinstants":
        if direct:
            return _myinstants(query, count, direct=True)
        return _over_tor(lambda: _myinstants(query, count), MYINSTANTS)
    if kind == "ytmusic":
        target = ("https://music.youtube.com/search?q="
                  f"{urllib.parse.quote_plus(query)}#songs")
    else:
        target = f"{kind}{count}:{query}{TIKTOK_SUFFIX if source == 'tiktok' else ''}"
    opts = {k: v for k, v in _opts(feature=feature, direct=direct).items()
            if k not in ("format", "outtmpl")}
    opts.update(extract_flat="in_playlist", noplaylist=False, playlistend=count)

    def look():
        with _ydl() as yt_dlp:
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    return ydl.extract_info(target, download=False)
            except Exception as e:  # noqa: BLE001 - yt-dlp raises many kinds; show its message
                raise _readable(e) from e
    site = "https://soundcloud.com" if source == "soundcloud" else "https://www.youtube.com"
    info = look() if direct else _over_tor(look, site)
    out = []
    for e in (info or {}).get("entries") or ():
        if not e or e.get("live_status") == "is_live":
            continue
        r = _soundcloud_hit(e) if source == "soundcloud" else _youtube_hit(e)
        if r:
            out.append(r)
    return out[:count]


def _myinstants(query: str, count: int, direct: bool = False) -> list[Result]:
    """Myinstants' search page, read for its sound buttons (title + MP3 path)."""
    url = f"{MYINSTANTS}/en/search/?name={urllib.parse.quote_plus(query)}"
    try:
        req = urllib.request.Request(url, headers=BROWSER_HEADERS)
        with net.urlopen(req, timeout=20, feature=f"{FEATURE}.myinstants",
                         direct=direct) as r:
            page = r.read(4 * 1024 * 1024).decode("utf-8", "replace")
    except net.FeatureOff as e:
        raise SwitchedOff(str(e)) from None
    except Exception as e:  # noqa: BLE001 - offline, blocked…: show why
        raise FetchError(f"Myinstants didn't answer ({errors.plain(e)})") from e
    out = []
    for m in re.finditer(r"onclick=\"play\('(/media/sounds/[^']+?\.mp3)'.*?"
                         r'class="instant-link[^"]*">([^<]+)</a>', page, re.S):
        path, title = m.group(1), html.unescape(m.group(2)).strip()
        out.append(Result(path.rsplit("/", 1)[-1], title or "Sound", "Myinstants", 0,
                          "myinstants", MYINSTANTS + path))
        if len(out) >= count:
            break
    return out


def _youtube_hit(e: dict) -> Result | None:
    vid = str(e.get("id") or "")
    if not re.fullmatch(r"[\w-]{11}", vid):
        return None   # a channel or playlist, not a video
    return Result(vid, str(e.get("title") or vid),
                  str(e.get("channel") or e.get("uploader") or ""),
                  float(e.get("duration") or 0), views=_count(e.get("view_count")))


def _soundcloud_hit(e: dict) -> Result | None:
    link = str(e.get("webpage_url") or e.get("url") or "")
    if not re.match(r"https://(api\.)?soundcloud\.com/", link):
        return None
    # the flat entry only lists tiny cover sizes; "-t300x300" is the same art, bigger
    art = next((str(t.get("url")) for t in reversed(e.get("thumbnails") or ())
                if t.get("url")), "")
    art = re.sub(r"-(mini|tiny|small|badge|t\d+x\d+|large)\.(jpg|png)$", r"-t300x300.\2", art)
    return Result(str(e.get("id") or link), str(e.get("title") or "Track"),
                  str(e.get("uploader") or ""), float(e.get("duration") or 0),
                  "soundcloud", link, art, _count(e.get("view_count")),
                  _count(e.get("like_count")), _count(e.get("comment_count")))


def _count(v) -> int | None:
    try:
        return max(0, int(v)) if v is not None else None
    except (TypeError, ValueError):
        return None


def needs_stats(r: Result) -> bool:
    """A YouTube hit: its search entry has the views but not likes / comments."""
    return r.source in ("youtube", "ytmusic", "tiktok") and not r.link and r.likes is None


# Likes and comments are a nicety, looked up for every YouTube hit of a search. Done
# like a Play (the video page, then each player client's API, its JS player…) that
# was dozens of requests a search, enough for YouTube to take the user for a bot and
# answer "Sign in to confirm you're not a bot" to their next Play. So a look-up is one
# page and nothing else (STATS_ARGS), and the first sign of a site pushing back (a
# bot check or a rate limit, in a look-up or a download) pauses them for STATS_PAUSE.
STATS_ARGS = {"youtube": {"player_client": ["web"],          # the page's own player data
                          "player_skip": ["configs", "js"]}}  # no other client, no JS
STATS_PAUSE = 30 * 60
_stats_paused_until = 0.0


def stats_paused() -> bool:
    return time.monotonic() < _stats_paused_until


def _pause_stats(why: str):
    global _stats_paused_until
    if not stats_paused():
        log.info("site pushed back (%s): no likes / comments look-ups for %d min",
                 why[:120], STATS_PAUSE // 60)
    _stats_paused_until = time.monotonic() + STATS_PAUSE


class _Watch:
    """yt-dlp's logger for a look-up: passes on to ours, and notes a bot check or a
    rate limit it only warns about (a look-up carries on without the player data)."""

    def __init__(self):
        self.pushback = ""

    def debug(self, msg):
        log.debug(msg)

    def info(self, msg):
        log.info(msg)

    def warning(self, msg):
        if blocked_by_site(msg):
            self.pushback = self.pushback or msg
        log.warning(msg)

    def error(self, msg):
        log.error(msg)


def stats(r: Result) -> tuple[int | None, int | None, int | None]:
    """(views, likes, comments) of a hit, from its page (one request, nothing
    downloaded). Tried once: no new Tor identities for a nicety; raises like probe,
    and while stats_paused() without asking the site."""
    feature = _gate(r.source)
    if stats_paused():
        raise DownloadError("likes and comments are paused: the site pushed back")
    watch = _Watch()
    with _ydl() as yt_dlp:
        try:
            opts = {k: v for k, v in _opts(feature=feature).items()
                    if k not in ("format", "outtmpl")}
            opts.update(logger=watch, extractor_args=STATS_ARGS,
                        ignore_no_formats_error=True)   # no player data needed
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(r.url, download=False, process=False) or {}
        except Exception as e:  # noqa: BLE001 - yt-dlp raises many kinds
            raise _readable(e) from e
    if watch.pushback:
        _pause_stats(watch.pushback)
    return (_count(info.get("view_count")), _count(info.get("like_count")),
            _count(info.get("comment_count")))


@contextlib.contextmanager
def _ydl():
    """The yt_dlp module, in shared use (an update never swaps it mid-use)."""
    install()
    with _lock.shared():
        try:
            import yt_dlp
        except ImportError as e:
            raise FetchError("The downloader (yt-dlp) isn't installed — "
                             "Settings → Updates → Reset downloader.") from e
        yield yt_dlp


def _download(url, dest, progress, feature: str = FEATURE,
              direct: bool = False, video: bool = False) -> tuple[Path, str]:
    with _ydl() as yt_dlp:
        if dest:
            return _run(yt_dlp, url, Path(dest), progress, feature, direct, video)
        # Our own temp folder: the caller only learns it on success, so a failed
        # download (up to the size cap) must not be left behind in %TEMP%.
        tmp = Path(tempfile.mkdtemp(prefix="sb-ytdl-"))
        try:
            return _run(yt_dlp, url, tmp, progress, feature, direct, video)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise


def _direct_leaf(url: str) -> str:
    """The file name of a direct link, safe to put in our folder: only the last path
    segment (never the query), decoded, with separators / `..` / odd characters gone."""
    leaf = urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1])
    return re.sub(r"[^\w .()-]", "_", leaf).strip(" .")[:80]


def _direct_title(url: str) -> str:
    stem = _direct_leaf(url).rsplit(".", 1)[0]
    return re.sub(r"[-_]+", " ", stem).strip().capitalize() or "Sound"


def _download_direct(url, dest, progress, direct: bool = False) -> tuple[Path, str]:
    """A plain audio file yt-dlp can't fetch (Myinstants' Cloudflare blocks it)."""
    parts = urllib.parse.urlsplit(url)
    leaf = _direct_leaf(url)
    # the URL comes from a paste: a query / fragment / odd name could steer the file
    # out of our folder (Windows resolves `\..` inside the name)
    if (parts.netloc != urllib.parse.urlsplit(MYINSTANTS).netloc or parts.query
            or parts.fragment or not leaf.lower().endswith(".mp3")):
        raise DownloadError("That isn't a Myinstants sound link.")
    tmp = Path(dest) if dest else Path(tempfile.mkdtemp(prefix="sb-ytdl-"))
    path = tmp / leaf
    if path.resolve().parent != tmp.resolve():
        if not dest:
            shutil.rmtree(tmp, ignore_errors=True)
        raise DownloadError("That isn't a Myinstants sound link.")
    try:
        req = urllib.request.Request(url, headers=BROWSER_HEADERS)
        with (net.urlopen(req, timeout=30, feature=f"{FEATURE}.myinstants",
                          direct=direct) as r,
              open(path, "wb") as f):
            total, got = int(r.headers.get("Content-Length") or 0), 0
            while chunk := r.read(64 * 1024):
                got += len(chunk)
                if got > MAX_BYTES:
                    raise DownloadError(f"It's over {MAX_BYTES // 2**20} MB.")
                f.write(chunk)
                if progress and total:
                    progress(min(got / total, 1.0))
    except DownloadError:
        if not dest:
            shutil.rmtree(tmp, ignore_errors=True)
        raise
    except net.FeatureOff as e:
        if not dest:
            shutil.rmtree(tmp, ignore_errors=True)
        raise SwitchedOff(str(e)) from None
    except Exception as e:  # noqa: BLE001 - network: show why
        if not dest:
            shutil.rmtree(tmp, ignore_errors=True)
        raise DownloadError(f"Download failed ({errors.plain(e)})") from e
    return path, _direct_title(url)


def _check(info: dict) -> dict:
    """Refuse what isn't one sound."""
    if info.get("_type") == "playlist":
        raise DownloadError("That's a playlist — open one video and try again.")
    if info.get("is_live"):
        raise DownloadError("Can't add a live stream — use Record instead.")
    return info


def _readable(e: Exception) -> FetchError:
    """yt-dlp's error in plain words (errors.describe): no "[youtube] id:" prefix,
    command-line tips or "report this on yt-dlp's GitHub"; one we can't explain is
    marked for reporting to us. The original text stays in `.raw`."""
    if blocked_by_site(str(e)):
        _pause_stats(str(e))   # the nicety waits; the user's own clicks don't
    p = errors.describe(e, downloader=True)
    out = FetchError(p.text)
    out.problem, out.raw = p, str(e)
    return out


def _opts(dest: Path | None = None, progress=None, thumbnail: bool = False,
          feature: str = FEATURE, direct: bool = False, video: bool = False) -> dict:
    def hook(d):
        if progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total:
                progress(min(d.get("downloaded_bytes", 0) / total, 1.0))

    opts = {
        "format": quality.current.audio_format(),   # Settings > Data & quality
        "outtmpl": str((dest or Path(tempfile.gettempdir())) / "%(id)s.%(ext)s"),
        "noplaylist": True,            # a video in a playlist: just that video
        "writethumbnail": thumbnail,   # the pad's picture (soundboard.thumbs)
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "max_filesize": MAX_BYTES,
        "cachedir": str(cache_dir()),  # ours, so Reset can clear it
        "js_runtimes": {"deno": {}, "node": {}},   # used when installed; works without
        "progress_hooks": [hook],
        "logger": log,
    }
    # the relay, as this site: Settings > Connection and Privacy & security;
    # `direct` is the user's "Try this one without Tor" (the switches still hold)
    opts["proxy"] = net.ytdlp_proxy(feature, direct=direct)
    if video:
        ff = library._ffmpeg()
        fmt = quality.current.video_format()
        if ff:   # yt-dlp merges the best video and audio streams with it
            opts.update(ffmpeg_location=ff, merge_output_format="mp4")
        else:    # no merging: only files that already hold both
            fmt = fmt.split("/", 2)[2]
        opts.update(format=fmt, max_filesize=VIDEO_MAX_BYTES)
    return opts


def save_video(path: Path, title: str) -> Path | None:
    """Keep a downloaded video in Settings > Data & quality's videos folder, under its
    title. None when `path` isn't a video (a download that fell back to audio)."""
    path = Path(path)
    if path.suffix.lower() not in VIDEO_EXTS:
        return None
    folder = quality.current.videos()
    folder.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip(" .")[:80] or "Video"
    out = folder / f"{stem}{path.suffix.lower()}"
    n = 2
    while out.exists():
        out = folder / f"{stem} ({n}){path.suffix.lower()}"
        n += 1
    shutil.copy2(path, out)
    return out


def _run(yt_dlp, url: str, dest: Path, progress, feature: str = FEATURE,
         direct: bool = False, video: bool = False) -> tuple[Path, str]:
    try:
        with yt_dlp.YoutubeDL(_opts(dest, progress, thumbnail=True, feature=feature,
                                    direct=direct, video=video)) as ydl:
            info = _check(ydl.extract_info(url, download=False))
            dur = info.get("duration") or 0
            if dur > MAX_SECONDS:
                log.info("%s is %ds; only the first %ds will be kept", url, dur, MAX_SECONDS)
            info = ydl.process_ie_result(info, download=True)
            path = Path(ydl.prepare_filename(info))
    except DownloadError:
        raise
    except Exception as e:  # noqa: BLE001 - yt-dlp raises many kinds; show its message
        raise _readable(e) from e
    if not path.is_file():   # skipped (too big) or the extension changed
        found = [p for p in dest.iterdir() if p.is_file() and not p.name.endswith(".part")
                 and p.suffix.lower() not in IMAGE_EXTS]
        if not found:
            raise DownloadError("Nothing was downloaded (the file may be over "
                                f"{MAX_BYTES // 2**20} MB).")
        path = found[0]
    return path, clean_title(info.get("title") or path.stem)
