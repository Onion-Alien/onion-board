"""Which pads have a video: a pad made from a video file (or a link added with
Settings > Data & quality > "Also save the video") can show it while it plays.

The pad itself is only ever audio (library.import_file stores a video's sound as a
FLAC), so the video stays where it is - the user's own file, or the saved-videos
folder - and videos.json beside the config says which sound it belongs to. It's a
side file rather than a SoundMeta field so a version from before this keeps the
links: it never reads or rewrites the file. A link whose video was moved or
deleted is simply not offered.

The folder is looked up on every call (library.APP_DIR), so tests that point the
library somewhere else get their own file.
"""
from __future__ import annotations

import json
import logging
import tempfile
import threading
from pathlib import Path

from soundboard import library

log = logging.getLogger(__name__)

VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v", ".wmv"}
# our own temp folders (a zip being imported, a download): deleted once it's in
TEMP_PREFIXES = ("onionboard-", "sb-")
_lock = threading.Lock()   # the import and download workers link from their threads


def _path() -> Path:
    return library.APP_DIR / "videos.json"


def is_video(path: str | Path) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXTS


def _load() -> dict[str, str]:
    try:
        raw = json.loads(_path().read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        log.warning("videos.json is unreadable; starting it again", exc_info=True)
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str) and v}


def _save(links: dict[str, str]):
    p = _path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(links, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        log.warning("couldn't save videos.json", exc_info=True)


def link(sid: str, video: str | Path):
    """Remember that sound `sid` came from `video`."""
    with _lock:
        links = _load()
        links[sid] = str(Path(video).resolve())
        _save(links)


def link_import(sid: str, src: str | Path) -> bool:
    """After importing `src` as sound `sid`: link it if it's a video that stays put
    (not one unpacked into a temp folder, or dragged into the Sounds folder, which
    the import replaces with the FLAC)."""
    p = Path(src)
    if not is_video(p) or not p.is_file():
        return False
    try:
        r = p.resolve()
        if r.is_relative_to(library.SOUNDS_DIR.resolve()):
            return False
        tmp = Path(tempfile.gettempdir()).resolve()
        if r.is_relative_to(tmp) and r.relative_to(tmp).parts[0].startswith(TEMP_PREFIXES):
            return False
    except OSError:
        return False
    link(sid, r)
    return True


def copy_link(src_sid: str, new_sid: str):
    """A duplicated pad shows the same video."""
    with _lock:
        links = _load()
        if src_sid in links:
            links[new_sid] = links[src_sid]
            _save(links)


def get(sid: str) -> Path | None:
    """The video of sound `sid`, if it has one that's still there."""
    with _lock:
        v = _load().get(sid)
    if v and Path(v).is_file():
        return Path(v)
    return None
