"""Pad pictures: a small JPEG per sound in THUMBS_DIR.

Where they come from: the video thumbnail yt-dlp saves next to a downloaded link
(YouTube, TikTok and the other sites it supports), the cover art / first frame of an
imported file (needs ffmpeg), any image the user picks, drops or pastes on a pad, or
one from a link (fetch()).

Everything here uses QImage, which is safe off the UI thread (the download and
import workers call store()). Only pixmap() and fitted() need the UI thread; they
read the file on a worker thread and answer None until it's in.
"""
from __future__ import annotations

import logging
import html
import queue
import re
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
import weakref
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPixmap
from shiboken6 import isValid as qt_valid

from soundboard import library
from soundboard.i18n import _
from soundboard.library import SoundMeta

log = logging.getLogger(__name__)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".jfif"}
MAX_W, MAX_H = 480, 300          # a pad is at most ~300 px wide; 2x for high-DPI
ART_EXTS = {".mp3", ".m4a", ".flac", ".ogg", ".opus", ".aac", ".wma",
            ".mp4", ".mkv", ".webm", ".mov"}   # may carry cover art or a picture


def is_image(path: str | Path) -> bool:
    return Path(path).suffix.lower() in IMAGE_EXTS


def find_in(folder: Path) -> Path | None:
    """The thumbnail yt-dlp wrote into a download folder, if any. TikTok's comes as
    `<id>.image` (its server names no type): Qt reads the JPEG inside all the same."""
    try:
        return next((p for p in sorted(folder.iterdir()) if p.is_file()
                     and (is_image(p) or p.suffix.lower() == ".image")), None)
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


LINK_FEATURE = "sounds_web.other"   # soundboard.net's switch: "Other pasted links"
MAX_LINK_BYTES = 15 << 20            # a picture (or the page around one) bigger than this isn't
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/140.0 Safari/537.36",
            "Accept": "image/*,text/html;q=0.9,*/*;q=0.8"}
_YOUTUBE = re.compile(r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|embed/|live/)|youtu\.be/)"
                      r"([\w-]{11})")
_PAGE_PIC = re.compile(r"<meta\b[^>]*?(?:property|name)\s*=\s*[\"']"
                       r"(?:og:image(?::secure_url|:url)?|twitter:image(?::src)?)[\"'][^>]*>", re.I)
_CONTENT = re.compile(r"content\s*=\s*[\"']([^\"']+)", re.I)


class LinkError(Exception):
    """fetch() couldn't make a picture of the link; the message says why, for the user."""


def link_picture(page: str, base: str) -> str:
    """The picture a web page shares itself with (og:image / twitter:image), as an
    absolute URL; "" when it names none."""
    for tag in _PAGE_PIC.finditer(page):
        m = _CONTENT.search(tag.group(0))
        if m:
            return urllib.parse.urljoin(base, html.unescape(m.group(1)).strip())
    return ""


def _get(url: str) -> tuple[bytes, str]:
    from soundboard import net
    req = urllib.request.Request(url, headers=_HEADERS)
    with net.urlopen(req, timeout=20, feature=LINK_FEATURE) as r:
        body = r.read(MAX_LINK_BYTES + 1)
        kind = (r.headers.get_content_type() or "").lower()
    if len(body) > MAX_LINK_BYTES:
        raise LinkError(_("That picture is too big (over {mb} MB).", mb=MAX_LINK_BYTES >> 20))
    return body, kind


def fetch(url: str) -> QImage:
    """The picture at a link: an image's own address, or a web page (a YouTube video,
    a post…) whose preview picture is taken. Blocks (call it off the UI thread);
    raises LinkError, or net.FeatureOff when links are switched off."""
    from soundboard import errors, net
    url = url.strip()
    if url and "://" not in url:
        url = "https://" + url
    parts = urllib.parse.urlsplit(url)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname or \
            any(c.isspace() for c in url):
        raise LinkError(_("That isn't a web link. Copy the picture's address (right-click "
                          "it → Copy image address) and paste it here."))
    yt = _YOUTUBE.search(url)
    if yt:   # straight to the video's thumbnail: YouTube's page can ask for cookies first
        url = f"https://i.ytimg.com/vi/{yt.group(1)}/hqdefault.jpg"
    try:
        body, kind = _get(url)
        img = QImage.fromData(body)
        if img.isNull() and ("html" in kind or body[:500].lstrip().lower().startswith(b"<")):
            pic = link_picture(body.decode("utf-8", "replace"), url)
            # the page names it, not the user: a file:// one would open a file on this
            # PC (or a share on another), past the switches and Tor
            if urllib.parse.urlsplit(pic).scheme.lower() in ("http", "https"):
                body, kind = _get(pic)
                img = QImage.fromData(body)
    except (LinkError, net.FeatureOff):
        raise
    except Exception as e:  # noqa: BLE001 - offline, 404, blocked…: say why
        raise LinkError(_("Couldn't get the picture ({error}).", error=errors.plain(e))) from e
    if img.isNull():
        raise LinkError(_("There's no picture at that link. Right-click the picture → Copy "
                          "image address, and paste that."))
    return img


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


# the most recently drawn pictures, as loaded (up to ~0.6 MB each): pads draw fitted()
# copies, so these are only read to make one (a new pad size, the mouse over a pad).
# A couple of screens' worth, so dragging Pad size doesn't read every file again
# (~1 ms each); the oldest give way. 48 MB of them sat there for a session that had
# long since drawn every pad (a 300-sound board, half with pictures).
MAX_CACHED = 128
MAX_BYTES = 12 << 20
_pixmaps: OrderedDict[str, QPixmap | None] = OrderedDict()
_bytes = 0

# pictures already scaled and cropped to a pad's size (in real pixels) with its shade
# drawn on: a pad paints one with a plain copy, where scaling the picture on every paint
# made scrolling a board of pictures stutter (77 ms a step). A few screens' worth even
# of the biggest (a 240 px pad on a 200 % screen is ~0.6 MB, a 150 px one at 100 %
# 50 KB); the oldest give way, and a new size of a picture replaces the old size.
MAX_FITTED_BYTES = 24 << 20
_fitted: OrderedDict[tuple, QPixmap] = OrderedDict()
_fitted_bytes = 0


# A picture's file is read on a worker thread: a restore from the tray (trim()) or a
# scroll reads a screenful of them, and on a slow or waking disk the window froze for
# that long. Until one is in, the pad paints its plain card; the widget that asked
# is repainted when it arrives. Off in tests that check the caches themselves.
LOAD_ASYNC = True
_waiting: dict[str, list[weakref.ref]] = {}   # path -> widgets to repaint when it's in
_jobs: queue.Queue[str] = queue.Queue()
_relay: _Relay | None = None


class _Relay(QObject):
    """Takes a picture the worker read over to the UI thread (lives there)."""
    loaded = Signal(str, QImage)

    def __init__(self):
        super().__init__()
        self.loaded.connect(self._loaded)

    def _loaded(self, path: str, img: QImage):
        if path not in _waiting:      # forgotten (replaced) while it was being read
            return
        _put(path, QPixmap.fromImage(img))
        for ref in _waiting.pop(path):
            if (w := ref()) is not None and qt_valid(w):
                w.update()


def _read_loop(relay: _Relay):
    while True:
        path = _jobs.get()
        try:
            img = QImage(path)
        except Exception:   # noqa: BLE001 - a bad file must not stop the reader
            log.debug("couldn't read picture %s", path, exc_info=True)
            img = QImage()
        try:
            relay.loaded.emit(path, img)
        except RuntimeError:   # the app is closing
            return


def _ask(path: str, waiter):
    """Have the worker read `path`; `waiter` (a widget, or None) is repainted then."""
    global _relay
    refs = _waiting.get(path)
    if refs is None:
        refs = _waiting[path] = []
        if _relay is None:
            _relay = _Relay()
            threading.Thread(target=_read_loop, args=(_relay,), name="pad-pictures",
                             daemon=True).start()
        _jobs.put(path)
    if waiter is not None and not any(r() is waiter for r in refs):
        refs.append(weakref.ref(waiter))


def _size(pm: QPixmap | None) -> int:
    return 0 if pm is None else pm.width() * pm.height() * max(1, pm.depth() // 8)


def _put(path: str, pm: QPixmap | None) -> QPixmap | None:
    global _bytes
    pm = None if pm is None or pm.isNull() else pm
    _bytes -= _size(_pixmaps.pop(path, None))
    _pixmaps[path] = pm
    _bytes += _size(pm)
    while len(_pixmaps) > 1 and (len(_pixmaps) > MAX_CACHED or _bytes > MAX_BYTES):
        _bytes -= _size(_pixmaps.popitem(last=False)[1])
    return pm


def loading(path: str) -> bool:
    """Is `path` being read right now (pixmap() answered None for now)?"""
    return path in _waiting


def pixmap(path: str, waiter=None) -> QPixmap | None:
    """The picture as a QPixmap (cached; UI thread only). None if it's missing, or
    while it's still being read (then `waiter`, a widget, is repainted once it's in)."""
    if not path:
        return None
    if path in _pixmaps:
        _pixmaps.move_to_end(path)
        return _pixmaps[path]
    if LOAD_ASYNC:
        _ask(path, waiter)
        return None
    # by way of a QImage: QPixmap(path) also keeps a copy in Qt's own pixmap cache
    return _put(path, QPixmap.fromImage(QImage(path)))


def fitted(path: str, w: int, h: int, dpr: float,
           shade: tuple[tuple[float, int], ...] = (), radius: float = 0,
           waiter=None) -> QPixmap | None:
    """The picture cropped to fill `w` x `h` real pixels (a pad at device pixel ratio
    `dpr`), darkened top to bottom by `shade`: (position 0..1, black's alpha) stops,
    its corners rounded by `radius` (logical pixels; outside them it's see-through).
    Cached by all of those, so a new size, screen or shade makes a new one, and a new
    picture has a new path (store()). None if it's missing or still being read
    (`waiter` is repainted when it's in: pixmap()). UI thread only."""
    global _fitted_bytes
    if not path or w <= 0 or h <= 0:
        return None
    key = (path, w, h, round(dpr, 3), shade, radius)
    pm = _fitted.get(key)
    if pm is not None:
        _fitted.move_to_end(key)
        return pm
    src = pixmap(path, waiter)
    if src is None:
        return None
    big = src.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    pm = QPixmap(w, h)
    pm.fill(Qt.transparent if radius else Qt.black)
    p = QPainter(pm)
    p.drawPixmap((w - big.width()) // 2, (h - big.height()) // 2, big)
    if shade:
        grad = QLinearGradient(0, 0, 0, h)
        for at, alpha in shade:
            grad.setColorAt(at, QColor(0, 0, 0, alpha))
        p.fillRect(0, 0, w, h, grad)
    if radius:   # cut the corners away, smoothly (a clip path's edge is jagged)
        corners = QPainterPath()
        corners.addRect(0, 0, w, h)
        rounded = QPainterPath()
        rounded.addRoundedRect(0, 0, w, h, radius * dpr, radius * dpr)
        p.setRenderHint(QPainter.Antialiasing)
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.fillPath(corners.subtracted(rounded), Qt.black)
    p.end()
    pm.setDevicePixelRatio(dpr)
    # the pads are all one size: a new size (Pad size dragged, another screen's
    # scale) makes the old one of this picture and shade useless
    for old in [k for k in _fitted if k[0] == path and k[4:] == key[4:] and k != key]:
        _fitted_bytes -= _size(_fitted.pop(old))
    _fitted[key] = pm
    _fitted_bytes += _size(pm)
    while len(_fitted) > 1 and _fitted_bytes > MAX_FITTED_BYTES:
        _fitted_bytes -= _size(_fitted.popitem(last=False)[1])
    return pm


def forget(path: str):
    """Drop a picture from the caches (it was replaced or removed; UI thread only)."""
    global _bytes, _fitted_bytes
    _bytes -= _size(_pixmaps.pop(path, None))
    _waiting.pop(path, None)      # one being read is let go when it arrives
    for key in [k for k in _fitted if k[0] == path]:
        _fitted_bytes -= _size(_fitted.pop(key))


def trim():
    """Let every cached picture go (the window went to the tray: nothing is drawn
    until it's back, and then a screen of them is made again from the small files in
    a few ms). UI thread only."""
    global _bytes, _fitted_bytes
    _pixmaps.clear()
    _fitted.clear()
    _bytes = _fitted_bytes = 0


def prune(keep: set[str]):
    """Delete pictures no sound uses any more (`keep` = the paths in use). Recent
    files are left alone: an import still running has stored one already."""
    try:
        for p in library.THUMBS_DIR.glob("*"):
            if p.is_file() and str(p) not in keep and time.time() - p.stat().st_mtime > 600:
                p.unlink(missing_ok=True)
    except OSError:
        log.debug("picture prune failed", exc_info=True)
