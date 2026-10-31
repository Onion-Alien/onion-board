"""What soundboard.online.ytdl's searches and downloads share: the sites and their
switches in Settings > Privacy & security, the errors, the lock that keeps a new
yt-dlp from being swapped in mid-download, a search result (`Result`), and trying
again when Tor gets turned away."""
from __future__ import annotations

import contextlib
import logging
import re
import threading
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass

from soundboard.online import net
from soundboard.core import errors
from soundboard.i18n import _

log = logging.getLogger("soundboard.online.ytdl")


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".image"}   # thumbnails
MAX_BYTES = 200 * 1024 * 1024   # an audio stream bigger than this isn't a sound
PROGRESS_EVERY_S = 0.1          # download progress to the UI: at most 10 a second
VIDEO_MAX_BYTES = 1024 * 1024 * 1024   # ...and with the video kept (Settings > Data)
VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov"}
RETRY_CHECK_AFTER = 3600         # a failed download checks again if the last check is older
RETRY_PAUSE_S = 2.0              # before a failed download's one automatic second try
# YouTube's players for that second try: a refusal (403, "not a bot", no formats) is
# often for the ones yt-dlp asks first (visionos, web) only. These need no PO token
# (yt-dlp's INNERTUBE_CLIENTS); web_safari last, as its HLS has the sound too
RETRY_CLIENTS = ("tv", "tv_downgraded", "web_embedded", "web_safari")
# failures a second try can get past: refused, cut off, stuck or slow. Not a private,
# removed, age- or country-locked video, which no second try changes
_TRY_AGAIN = re.compile(
    r"http error (?:403|5\d\d)|forbidden|not a bot|confirm you.?re not|"
    r"requested format is not available|no (?:video )?formats|timed? ?out|stopped moving|"
    r"no new data|incomplete ?read|bytes, expected|cut off|connection (?:reset|aborted)|"
    r"having trouble", re.I)

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

    problem: errors.Problem | None = None   # set by _readable
    raw: str = ""
    # for the usage count: yt-dlp's own error class (`ExtractorError`, set by _readable),
    # or `helper-timeout` when the download helper didn't answer in time
    kind = ""
    proxy = False   # the proxy / Tor failed, not yt-dlp (set by _readable)


class SwitchedOff(DownloadError):
    """The site (or finding sounds online at all) is switched off in Settings > Privacy
    & security: nothing was looked up or sent. The message says so."""


FEATURE = "sounds_web"           # soundboard.online.net's switch for all of this
UPDATE_FEATURE = "ytdlp_update"  # ...and for updating yt-dlp (the list + PyPI)


def site_of(target: str) -> str:
    """Which of net.SITES a search source (a key of SOURCES) or a link belongs to.
    TikTok's button searches YouTube, so it's YouTube's; a pasted TikTok link is
    "other". A site's own picture servers count as the site (a YouTube thumbnail
    from i.ytimg.com is YouTube's, so its switch stops it too)."""
    if target in SOURCES:
        return {"soundcloud": "soundcloud", "myinstants": "myinstants"}.get(target, "youtube")
    host = (urllib.parse.urlsplit(target).hostname or "").lower().rstrip(".")

    def under(*domains):
        return any(host == d or host.endswith("." + d) for d in domains)
    if under("youtube.com", "youtu.be", "youtube-nocookie.com", "ytimg.com", "ggpht.com"):
        return "youtube"
    if under("soundcloud.com", "snd.sc", "sndcdn.com"):
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


# A site that never answers a Tor exit (SoundCloud ignores some): the socket times out.
# Waiting longer doesn't help, another exit does.
_TOR_SILENT = re.compile(r"timed? ?out", re.I)


def blocked_by_site(msg: str) -> bool:
    return bool(_TOR_BLOCKED.search(msg or ""))


def silent_over_tor(msg: str) -> bool:
    return bool(_TOR_SILENT.search(msg or ""))


def _site_name(target: str) -> str:
    host = urllib.parse.urlsplit(target).hostname or ""
    if not host or "youtube" in host or "youtu.be" in host:
        return "YouTube"
    return host.removeprefix("www.")


def _over_tor[T](fn: Callable[[], T], target: str) -> T:
    """fn(), and in Tor mode, when the site turns the Tor exit away or doesn't answer
    it, a new Tor identity and another try, up to TOR_TRIES times. Never falls back to
    a direct connection: the last refusal is raised as TorBlocked for the UI to offer
    that."""
    if net.mode() != net.TOR:
        return fn()
    from soundboard.online import tor
    for attempt in range(TOR_TRIES + 1):
        try:
            return fn()
        except SwitchedOff:
            raise
        except DownloadError as e:
            msg = f"{e} {getattr(e, 'raw', '')}"
            silent = not blocked_by_site(msg) and silent_over_tor(msg)
            if not (silent or blocked_by_site(msg)):
                raise
            if not site_allowed(target):   # switched off meanwhile: no more tries
                raise SwitchedOff(net.off_message(site_feature(target))) from None
            if attempt == TOR_TRIES:
                site = _site_name(target)
                if silent:
                    raise TorBlocked(_(
                        "{site} didn't answer over Tor (it ignores some of Tor's "
                        "addresses), and nor did {tries} other Tor routes. You can try "
                        "this one without Tor: {site} would then see your own address.",
                        site=site, tries=TOR_TRIES)) from e
                raise TorBlocked(_(
                    "{site} turned Tor away ({site} often blocks Tor's addresses), and "
                    "so did {tries} other Tor routes. You can try this one without "
                    "Tor: {site} would then see your own address.",
                    site=site, tries=TOR_TRIES)) from e
            log.info("site %s Tor (%s); new identity, try %d of %d",
                     "didn't answer" if silent else "turned away", str(e)[:120],
                     attempt + 1, TOR_TRIES)
            tor.new_identity()
    raise AssertionError("unreachable: the last try returns or raises")


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
# redirects to the trending page of the visitor's country (/en/trending/us/…)
TRENDING = MYINSTANTS + "/en/trending/"
BROWSER_HEADERS = {   # Myinstants' Cloudflare turns away urllib's default User-Agent
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/140.0 Safari/537.36",
    "Accept": "text/html,audio/*,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9",
    "Referer": MYINSTANTS + "/"}


PLAYLIST = "ytplaylist"   # a Result's source when it's a YouTube playlist, not a video


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
    views: int | None = None      # None: the search entry didn't say
    likes: int | None = None
    comments: int | None = None
    videos: int | None = None     # a playlist's: how many it has (None: not said)

    @property
    def url(self) -> str:
        return self.link or f"https://www.youtube.com/watch?v={self.id}"

    @property
    def thumb(self) -> str:
        """"" when there's none (Myinstants' buttons have no picture) or it isn't a
        web link (the site's page names it: net.web_url)."""
        if self.art or self.source != "youtube":
            return net.web_url(self.art)
        return f"https://i.ytimg.com/vi/{self.id}/mqdefault.jpg"
