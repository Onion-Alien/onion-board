"""Pad pictures: a small JPEG per sound in THUMBS_DIR.

Where they come from: the video thumbnail yt-dlp saves next to a downloaded link
(YouTube, TikTok and the other sites it supports), the cover art / first frame of an
imported file (needs ffmpeg), or any image the user picks, drops or pastes on a pad.

Everything here uses QImage, which is safe off the UI thread (the download and
import workers call store()). Only pixmap() needs the UI thread.
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
import time
import uuid
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap

from soundboard import library
from soundboard.library import SoundMeta

log = logging.getLogger(__name__)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".jfif"}
MAX_W, MAX_H = 480, 300          # a pad is at most ~300 px wide; 2x for high-DPI
ART_EXTS = {".mp3", ".m4a", ".flac", ".ogg", ".opus", ".aac", ".wma",
            ".mp4", ".mkv", ".webm", ".mov"}   # may carry cover art or a picture


def is_image(path: str | Path) -> bool:
    return Path(path).suffix.lower() in IMAGE_EXTS


def find_in(folder: Path) -> Path | None:
    """The thumbnail yt-dlp wrote into a download folder, if any."""
    try:
        return next((p for p in sorted(folder.iterdir()) if p.is_file() and is_image(p)),
                    None)
    except OSError:
        return None


def store(src: str | Path | QImage, sid: str) -> str:
    """Scale an image (a file, or a QImage from the clipboard) down into THUMBS_DIR
    for sound `sid`; returns its path, or "" if it can't be read. A new file name
    every time, so a cached pixmap of the previous picture is never shown for the
    new one."""
    img = src if isinstance(src, QImage) else QImage(str(src))
    if img.isNull():
        log.info("couldn't read %s as a picture", src)
        return ""
    if img.width() > MAX_W or img.height() > MAX_H:
        img = img.scaled(MAX_W, MAX_H, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    try:
        library.THUMBS_DIR.mkdir(parents=True, exist_ok=True)
        dest = library.THUMBS_DIR / f"{sid}_{uuid.uuid4().hex[:6]}.jpg"
        if not img.convertToFormat(QImage.Format_RGB888).save(str(dest), "JPG", 88):
            return ""
        return str(dest)
    except OSError:
        log.warning("couldn't store a picture for %s", sid, exc_info=True)
        return ""


def extract_art(src: str, sid: str) -> str:
    """Cover art (or the first video frame) of an audio/video file, stored like
    store(); "" when there is none or ffmpeg isn't installed."""
    if Path(src).suffix.lower() not in ART_EXTS:
        return ""
    ff = library._ffmpeg()
    if not ff:
        return ""
    with tempfile.TemporaryDirectory(prefix="sb-art-") as tmp:
        out = Path(tmp) / "art.png"
        try:
            subprocess.run([ff, "-v", "error", "-ss", "0", "-i", src, "-an", "-frames:v", "1",
                            "-vf", f"scale='min({MAX_W},iw)':-2", str(out)],
                           capture_output=True, timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired):
            log.debug("ffmpeg art extraction failed for %s", src, exc_info=True)
            return ""
        return store(out, sid) if out.is_file() else ""


def from_clipboard(mime) -> QImage | None:
    """The picture on the clipboard (QMimeData): a copied image ("Copy image" in a
    browser, a screenshot), or a picture file copied in Explorer. None if neither."""
    if mime is None:
        return None
    if mime.hasImage():
        img = QImage(mime.imageData())
        if not img.isNull():
            return img
    if mime.hasUrls():
        for url in mime.urls():
            if url.isLocalFile() and is_image(url.toLocalFile()):
                img = QImage(url.toLocalFile())
                if not img.isNull():
                    return img
    return None


def set_image(meta: SoundMeta, src: str | Path | QImage) -> bool:
    """Give a sound a new picture (the old one's file is removed)."""
    new = store(src, meta.id)
    if not new:
        return False
    clear(meta)
    meta.image = new
    return True


def clear(meta: SoundMeta):
    if meta.image and Path(meta.image).parent == library.THUMBS_DIR:
        Path(meta.image).unlink(missing_ok=True)
        forget(meta.image)
    meta.image = ""


# the most recently drawn pictures (up to ~0.6 MB each). Enough for every pad on
# screen at once; the oldest give way, so a long session doesn't keep every picture
# it ever showed.
MAX_CACHED = 128
_pixmaps: OrderedDict[str, QPixmap | None] = OrderedDict()


def pixmap(path: str) -> QPixmap | None:
    """The picture as a QPixmap (cached; UI thread only). None if it's missing."""
    if not path:
        return None
    if path in _pixmaps:
        _pixmaps.move_to_end(path)
        return _pixmaps[path]
    pm = QPixmap(path)
    _pixmaps[path] = None if pm.isNull() else pm
    while len(_pixmaps) > MAX_CACHED:
        _pixmaps.popitem(last=False)
    return _pixmaps[path]


def forget(path: str):
    """Drop a picture from the cache (it was replaced or removed; UI thread only)."""
    _pixmaps.pop(path, None)


def prune(keep: set[str]):
    """Delete pictures no sound uses any more (`keep` = the paths in use). Recent
    files are left alone: an import still running has stored one already."""
    try:
        for p in library.THUMBS_DIR.glob("*"):
            if p.is_file() and str(p) not in keep and time.time() - p.stat().st_mtime > 600:
                p.unlink(missing_ok=True)
    except OSError:
        log.debug("picture prune failed", exc_info=True)
