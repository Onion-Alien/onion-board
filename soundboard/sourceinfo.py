"""Where a downloaded sound came from: the video's link, channel, upload date, length
and views, so the user can find the video again (the pad menu's *Open on YouTube*,
*Copy link* and *Video info…*).

Only for YouTube, YouTube Music, TikTok and SoundCloud. It is picked out of the reply
yt-dlp already got for the download: nothing extra is asked of the site (a second
lookup per download reads as a bot). Likes and comments are left out on purpose.

The info is kept on the sound (SoundMeta.source) and written as a plain text file
next to its audio, "YouTube/Song.txt", for anyone browsing the Sounds folder. The
text file is only a copy: it's made again from SoundMeta.source when needed."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from urllib.parse import urlsplit

from soundboard.i18n import _

log = logging.getLogger(__name__)

# what download_audio leaves in its temp folder for the caller (like the thumbnail)
FILE = "source.json"

# host -> (site key, the name shown). Keys match ui/icons.py's site icons.
_SITES = {"music.youtube.com": ("ytmusic", "YouTube Music"),
          "youtube.com": ("youtube", "YouTube"), "youtu.be": ("youtube", "YouTube"),
          "tiktok.com": ("tiktok", "TikTok"), "soundcloud.com": ("soundcloud", "SoundCloud")}


def site_of(url: str) -> tuple[str, str] | None:
    """(key, name) of a site we keep the info for, or None."""
    try:
        host = (urlsplit(str(url).strip()).hostname or "").lower()
    except ValueError:
        return None
    for site, found in _SITES.items():
        if host == site or host.endswith("." + site):
            return found
    return None


def _text(v, limit: int = 300) -> str:
    return str(v).strip()[:limit] if isinstance(v, (str, int, float)) and v != "" else ""


def _http(v) -> str:
    s = _text(v, 2000)
    return s if s.startswith(("https://", "http://")) else ""


def _number(v) -> int | None:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else None


def pick(info: dict, url: str) -> dict:
    """The fields kept from yt-dlp's `info` for a download of `url`; {} for a site we
    don't keep it for. The link is the video's own page (a short youtu.be link or a
    search hit becomes the watch link)."""
    link = _http(info.get("webpage_url")) or _http(url)
    found = site_of(url) or site_of(link)
    if not link or found is None:
        return {}
    d = info.get("upload_date")
    uploaded = (f"{d[:4]}-{d[4:6]}-{d[6:8]}" if isinstance(d, str) and len(d) == 8
                and d.isdigit() else "")
    out = {"site": found[0], "link": link,
           "title": _text(info.get("title")),
           "channel": _text(info.get("channel") or info.get("uploader")
                            or info.get("creator")),
           "channel_link": _http(info.get("channel_url") or info.get("uploader_url")),
           "uploaded": uploaded,
           "seconds": _number(info.get("duration")),
           "views": _number(info.get("view_count")),
           "added": time.strftime("%Y-%m-%d")}
    return {k: v for k, v in out.items() if v not in ("", None)}


def clean(v) -> dict:
    """A stored SoundMeta.source made safe to use: {} unless it has an http(s) link on
    one of our sites."""
    if not isinstance(v, dict) or not _http(v.get("link")) or site_of(v["link"]) is None:
        return {}
    out = {k: _text(v.get(k)) for k in ("site", "title", "channel", "uploaded", "added")}
    out["link"] = _http(v["link"])
    out["channel_link"] = _http(v.get("channel_link"))
    out["seconds"] = _number(v.get("seconds"))
    out["views"] = _number(v.get("views"))
    if out["site"] not in {k for k, _n in _SITES.values()}:
        out["site"] = site_of(out["link"])[0]
    return {k: x for k, x in out.items() if x not in ("", None)}


def site_name(src: dict) -> str:
    """"YouTube", "YouTube Music", "TikTok" or "SoundCloud" (brand names: never
    translated)."""
    return next((n for k, n in _SITES.values() if k == src.get("site")), "YouTube")


def length(seconds) -> str:
    """3:33 or 1:02:03."""
    s = int(seconds or 0)
    h, m = divmod(s // 60, 60)
    return f"{h}:{m:02d}:{s % 60:02d}" if h else f"{m}:{s % 60:02d}"


def rows(src: dict) -> list[tuple[str, str]]:
    """(label, value) for every field it has, in the order shown (the info box and
    the text file)."""
    out = [(_("Title"), src.get("title", "")), (_("Link"), src.get("link", "")),
           (_("Channel"), src.get("channel", "")),
           (_("Channel link"), src.get("channel_link", "")),
           (_("Uploaded"), src.get("uploaded", "")),
           (_("Length"), length(src["seconds"]) if src.get("seconds") else ""),
           (_("Views"), _("{n} (when added)", n=f"{src['views']:,}")
            if src.get("views") is not None else ""),
           (_("Site"), site_name(src)), (_("Added"), src.get("added", ""))]
    return [(k, v) for k, v in out if v]


def text(src: dict) -> str:
    """The text file's contents."""
    pairs = rows(src)
    wide = max(len(k) for k, _v in pairs) + 2
    return "".join(f"{k + ':':<{wide}}{v}\n" for k, v in pairs)


def sidecar(audio: str | Path) -> Path:
    """The text file next to a sound's audio: "YouTube/Song.txt"."""
    return Path(audio).with_suffix(".txt")


def write(audio: str | Path, src: dict) -> None:
    """Write (or replace) the text file next to `audio`. Best effort: it's only a copy
    of what the sound keeps."""
    if not src:
        return
    p = sidecar(audio)
    try:
        p.write_text(text(src), encoding="utf-8-sig")   # Notepad reads it as UTF-8
    except OSError:
        log.info("couldn't write %s", p, exc_info=True)


def remove(audio: str | Path) -> None:
    """Delete the text file next to `audio`, if there is one."""
    try:
        sidecar(audio).unlink(missing_ok=True)
    except OSError:
        log.info("couldn't remove %s", sidecar(audio), exc_info=True)


def save_for(folder: Path, info: dict, url: str) -> None:
    """download_audio's part: leave the picked info in its temp folder."""
    src = pick(info, url)
    if src:
        try:
            (folder / FILE).write_text(json.dumps(src), encoding="utf-8")
        except OSError:
            log.info("couldn't keep the source info of %s", url, exc_info=True)


def read_from(folder: Path) -> dict:
    """What save_for left in `folder`, or {}."""
    try:
        return clean(json.loads((folder / FILE).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}

