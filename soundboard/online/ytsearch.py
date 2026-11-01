"""Web search for soundboard.online.ytdl: YouTube / SoundCloud through yt-dlp, and
Myinstants' search page."""
from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request

from soundboard.online import net
from soundboard.core import errors
from soundboard.i18n import _
from soundboard.online.ytsites import (BROWSER_HEADERS, FEATURE, FetchError, MYINSTANTS, PLAYLIST,
    Result,
    SOURCES, SwitchedOff, TIKTOK_SUFFIX, _gate, _over_tor)
from soundboard.online.ytfetch import _extract, _opts


def search(query: str, count: int = 20, source: str = "youtube",
           direct: bool = False, start: int = 1, playlists: bool = False) -> list[Result]:
    """Search one of SOURCES (one results page, nothing downloaded): hits `start` to
    `count` (1-based), so Show more asks for the next ones. Live streams and junk
    entries are left out. `playlists`: YouTube's playlists instead of its videos (the
    results' Videos / Playlists switch). Raises DownloadError like probe (TorBlocked
    when the site turned Tor away; `direct` is the user's "without Tor" click)."""
    query = " ".join(query.split())
    if not query:
        return []
    kind = SOURCES[source][1]
    feature = _gate(source)
    if kind == "myinstants":
        if direct:
            return _myinstants(query, count, direct=True)[start - 1:]
        return _over_tor(lambda: _myinstants(query, count), MYINSTANTS)[start - 1:]
    if playlists and source == "youtube":   # YouTube's own "Playlists" search filter
        target = ("https://www.youtube.com/results?search_query="
                  f"{urllib.parse.quote_plus(query)}&sp=EgIQAw%3D%3D")
    elif kind == "ytmusic":
        target = ("https://music.youtube.com/search?q="
                  f"{urllib.parse.quote_plus(query)}#songs")
    else:
        target = f"{kind}{count}:{query}{TIKTOK_SUFFIX if source == 'tiktok' else ''}"
    opts = {k: v for k, v in _opts(feature=feature, direct=direct).items()
            if k not in ("format", "outtmpl")}
    opts.update(extract_flat="in_playlist", noplaylist=False, playliststart=start,
                playlistend=count)

    # YouTube's settings kept between searches: Direct mode only (ytworker.CONFIG_KEEP_S)
    keep = source != "soundcloud" and net.mode() == net.DIRECT

    def look():
        return _extract(target, opts, keep)
    site = "https://soundcloud.com" if source == "soundcloud" else "https://www.youtube.com"
    info = look() if direct else _over_tor(look, site)
    out = []
    for e in (info or {}).get("entries") or ():
        if not e or e.get("live_status") == "is_live":
            continue
        r = (_soundcloud_hit(e) if source == "soundcloud" else
             _playlist_hit(e) if playlists and source == "youtube" else _youtube_hit(e))
        if r:
            out.append(r)
    return out[:count]


def _myinstants(query: str, count: int, direct: bool = False) -> list[Result]:
    """Myinstants' search page, read for its sound buttons (title + MP3 path)."""
    return _myinstants_page(f"{MYINSTANTS}/en/search/?name={urllib.parse.quote_plus(query)}",
                            count, direct)


def _myinstants_page(url: str, count: int, direct: bool = False) -> list[Result]:
    """A Myinstants page of sound buttons (its search), read for each one's
    title and MP3 path."""
    try:
        req = urllib.request.Request(url, headers=BROWSER_HEADERS)
        with net.urlopen(req, timeout=20, feature=f"{FEATURE}.myinstants",
                         direct=direct) as r:
            page = r.read(4 * 1024 * 1024).decode("utf-8", "replace")
    except net.FeatureOff as e:
        raise SwitchedOff(str(e)) from None
    except Exception as e:  # noqa: BLE001 - offline, blocked…: show why
        raise FetchError(_("Myinstants didn't answer ({error})",
                           error=errors.plain(e))) from e
    out = []
    # bounded gaps: on a page of onclicks with no instant-link, an open .*? read on to
    # the page's end from each one
    for m in re.finditer(r"onclick=\"play\('(/media/sounds/[^']{1,300}?\.mp3)'.{0,3000}?"
                         r'class="instant-link[^"]{0,200}">([^<]{1,300})</a>', page, re.S):
        path, title = m.group(1), html.unescape(m.group(2)).strip()
        out.append(Result(path.rsplit("/", 1)[-1], title or _("Sound"), "Myinstants", 0,
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


def _playlist_hit(e: dict) -> Result | None:
    """A YouTube playlist found by a search: opening its card lists its videos."""
    link = str(e.get("url") or "")
    if not re.match(r"https://www\.youtube\.com/playlist\?list=[\w-]+$", link):
        return None   # a channel or a video, not a playlist
    art = next((str(t.get("url")) for t in reversed(e.get("thumbnails") or ())
                if t.get("url")), "")
    return Result(str(e.get("id") or link), str(e.get("title") or _("Playlist")),
                  str(e.get("channel") or e.get("uploader") or ""), 0.0,
                  source=PLAYLIST, link=link, art=art, videos=_count(e.get("playlist_count")))


def _soundcloud_hit(e: dict) -> Result | None:
    link = str(e.get("webpage_url") or e.get("url") or "")
    if not re.match(r"https://(api\.)?soundcloud\.com/", link):
        return None
    # the flat entry only lists tiny cover sizes; "-t300x300" is the same art, bigger
    art = next((str(t.get("url")) for t in reversed(e.get("thumbnails") or ())
                if t.get("url")), str(e.get("thumbnail") or ""))
    art = re.sub(r"-(mini|tiny|small|badge|t\d+x\d+|large)\.(jpg|png)$", r"-t300x300.\2", art)
    return Result(str(e.get("id") or link), str(e.get("title") or _("Track")),
                  str(e.get("uploader") or ""), float(e.get("duration") or 0),
                  "soundcloud", link, art, _count(e.get("view_count")),
                  _count(e.get("like_count")), _count(e.get("comment_count")))


def _count(v) -> int | None:
    try:
        return max(0, int(v)) if v is not None else None
    except (TypeError, ValueError):
        return None
