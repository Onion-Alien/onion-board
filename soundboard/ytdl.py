"""Download the audio of the page open in the browser tab, with yt-dlp.

Used by the browser tab's "Add as sound" button: yt-dlp fetches the best audio
stream the site offers (YouTube, SoundCloud, and the other sites it supports) into
a temporary folder, and the file is then imported like a dropped file (so m4a /
webm audio needs ffmpeg, as it does for a dropped file). Nothing is converted to
MP3 on the way: the library stores it losslessly as a FLAC of what was decoded.

yt-dlp is imported lazily: it's a big package and only needed on click.
"""
from __future__ import annotations

import logging
import re
import tempfile
from collections.abc import Callable
from pathlib import Path

from soundboard.library import MAX_SECONDS

log = logging.getLogger(__name__)

MAX_BYTES = 200 * 1024 * 1024   # an audio stream bigger than this isn't a sound


class DownloadError(RuntimeError):
    pass


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


def clean_title(title: str) -> str:
    """A pad name from a video title: no "(Official Video)" / "[HD]" noise."""
    t = re.sub(r"\s*[(\[][^)\]]*\b(official|video|audio|lyrics?|hd|4k|visuali[sz]er)\b[^)\]]*[)\]]",
               "", title, flags=re.I)
    return re.sub(r"\s+", " ", t).strip() or title.strip()


def download_audio(url: str, dest: Path | None = None,
                   progress: Callable[[float], None] | None = None) -> tuple[Path, str]:
    """Download the best audio of `url` into `dest` (a new temp folder by default).

    Returns (file, title). `progress` gets 0..1 while it downloads. Raises
    DownloadError with a message fit to show the user."""
    try:
        import yt_dlp
    except ImportError as e:
        raise DownloadError("The YouTube downloader (yt-dlp) isn't installed.") from e
    dest = Path(dest or tempfile.mkdtemp(prefix="sb-ytdl-"))

    def hook(d):
        if progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total:
                progress(min(d.get("downloaded_bytes", 0) / total, 1.0))

    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(dest / "%(id)s.%(ext)s"),
        "noplaylist": True,            # a video in a playlist: just that video
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "max_filesize": MAX_BYTES,
        "js_runtimes": {"deno": {}, "node": {}},   # used when installed; works without
        "progress_hooks": [hook],
        "logger": log,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info.get("_type") == "playlist":
                raise DownloadError("That's a playlist — open one video and try again.")
            if info.get("is_live"):
                raise DownloadError("Can't add a live stream — use Record instead.")
            dur = info.get("duration") or 0
            if dur > MAX_SECONDS:
                log.info("%s is %ds; only the first %ds will be kept", url, dur, MAX_SECONDS)
            info = ydl.process_ie_result(info, download=True)
            path = Path(ydl.prepare_filename(info))
    except DownloadError:
        raise
    except Exception as e:  # noqa: BLE001 - yt-dlp raises many kinds; show its message
        msg = re.sub(r"^ERROR:\s*", "", str(e)).strip()
        msg = re.sub(r"\x1b\[[0-9;]*m", "", msg)   # colour codes
        raise DownloadError(msg or "Download failed") from e
    if not path.is_file():   # skipped (too big) or the extension changed
        found = [p for p in dest.iterdir() if p.is_file() and not p.name.endswith(".part")]
        if not found:
            raise DownloadError("Nothing was downloaded (the file may be over "
                                f"{MAX_BYTES // 2**20} MB).")
        path = found[0]
    return path, clean_title(info.get("title") or path.stem)
