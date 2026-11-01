"""The library's sound files: their names and folders in SOUNDS_DIR, importing,
recording, duplicating and deleting sounds, and tidying files from older versions."""
from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import sys
import threading
import time
import uuid
from pathlib import Path

import numpy as np

from soundboard.sounds import sourceinfo
from soundboard.audio.engine import SR
from soundboard.i18n import _
from soundboard.sounds import decoding, paths
from soundboard.sounds.cachefiles import cache_path, store_cached, unlink_cache
from soundboard.sounds.config import _OUR_SOUND_FILE, AUDIO_EXTS, Config, SoundMeta
from soundboard.sounds.decoding import _Long, stored_ext, write_stored
from soundboard.sounds.levels import level_gain

log = logging.getLogger("soundboard.sounds.library")


def fingerprint(path: str) -> str:
    """Cheap identity for a source file: size + hash of its first and last megabyte
    (a file of up to 1 MB hashes as it always did, whole)."""
    try:
        p = Path(path)
        h = hashlib.blake2b(digest_size=12)
        size = p.stat().st_size
        h.update(str(size).encode())
        with p.open("rb") as f:
            h.update(f.read(1 << 20))
            if size > 1 << 20:
                f.seek(max(size - (1 << 20), 1 << 20))
                h.update(f.read(1 << 20))
        return h.hexdigest()
    except OSError:
        return ""


# Where a new sound's file goes, inside SOUNDS_DIR. Plain folders and the sound's own
# name, so the folder reads like a music library in Explorer (and still does if Onion
# Board is uninstalled and the sounds are kept). Files from before this were all in
# SOUNDS_DIR itself as "<id>_<name>": tidy_files() moves them in. English on purpose:
# a folder on disk mustn't change with the language picked (or the pseudo one).
RECORDINGS = "Recordings"   # recorded clips, Replay, voice lines saved as sounds
MY_SOUNDS = "My sounds"     # files added from the PC, other soundboards, old sounds
DOWNLOADS = "Downloads"     # a link from a site not named in _SITES
_SITES = {"youtube.com": "YouTube", "youtu.be": "YouTube", "tiktok.com": "TikTok",
          "soundcloud.com": "SoundCloud", "instagram.com": "Instagram",
          "twitter.com": "X", "x.com": "X", "reddit.com": "Reddit", "redd.it": "Reddit",
          "twitch.tv": "Twitch", "facebook.com": "Facebook", "fb.watch": "Facebook",
          "vimeo.com": "Vimeo", "bandcamp.com": "Bandcamp", "kick.com": "Kick",
          "dailymotion.com": "Dailymotion", "bilibili.com": "Bilibili",
          "myinstants.com": "Myinstants", "streamable.com": "Streamable"}
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
             *(f"lpt{i}" for i in range(1, 10))}
_claim_lock = threading.Lock()


def site_folder(url: str) -> str:
    """The folder a sound downloaded from `url` goes in: the site's name."""
    from urllib.parse import urlsplit
    try:
        host = (urlsplit(url.strip()).hostname or "").lower()
    except ValueError:
        host = ""
    for site, folder in _SITES.items():
        if host == site or host.endswith("." + site):
            return folder
    return DOWNLOADS


# characters that change how a name reads without showing: right-to-left marks and
# overrides, zero-width spaces and joiners, soft hyphens, byte-order marks
_HIDDEN = re.compile("[\u00ad\u061c\u180e\u200b-\u200f\u2028-\u202e\u2060-\u206f\ufeff]")


def file_stem(name: str) -> str:
    """`name` as a file name Windows takes: no <>:"/|?* (or backslash) or control characters, no
    trailing dot or space, not a device name (CON, NUL...), not too long. Invisible and
    right-to-left characters go too: they can make "a\u202e3pm.exe" read "a.exe.mp3"."""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    s = _HIDDEN.sub("", s)
    s = " ".join(s.split()).strip(" .")[:80].strip(" .")
    if s.split(".")[0].lower() in _RESERVED:
        s = f"_{s}"
    return s or "Sound"


def owns(path: str | Path) -> bool:
    """A file the library keeps itself: anywhere in SOUNDS_DIR (its own folders too)."""
    p = Path(path)
    return p.is_absolute() and p != paths.SOUNDS_DIR and p.is_relative_to(paths.SOUNDS_DIR)


def _folder_of(p: Path) -> str:
    """The library folder a file of ours is in ("YouTube"), "" for SOUNDS_DIR itself
    or a file from elsewhere."""
    if not owns(p) or p.parent == paths.SOUNDS_DIR:
        return ""
    return p.parent.relative_to(paths.SOUNDS_DIR).as_posix()


def new_file(name: str, ext: str, folder: str, note: bool = True) -> Path:
    """A free path for a new sound file named after the sound ("Name (2)" when that's
    taken), made empty at once so two sounds saved together never get the same one.
    `note`: written down as being added (drop_unfinished), for a new sound's file."""
    where = paths.SOUNDS_DIR / folder
    where.mkdir(parents=True, exist_ok=True)
    stem, ext = file_stem(name), ext.lower()
    with _claim_lock:
        for n in range(1, 10000):
            p = where / (f"{stem}{ext}" if n == 1 else f"{stem} ({n}){ext}")
            try:
                with open(p, "xb"):
                    pass
            except FileExistsError:
                continue
            if note:
                _note_adding(p)
            return p
    raise OSError(f"no free file name for {stem}{ext} in {where}")


# A new sound's file is written down in APP_DIR/adding when it's made: an add the app
# was closed or crashed in the middle of (a long download being converted, or before
# the settings with its pad were saved) left a half-written file, or a whole one no pad
# uses, in the sounds folder for good, and adding it again made "Name (2)". The next
# launch takes those out (drop_unfinished); the notes go then too.
_STARTED = time.time()   # notes from before this: an earlier run's


def _adding_dir() -> Path:
    return paths.APP_DIR / "adding"


def _note_adding(p: Path) -> None:
    try:
        d = _adding_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{uuid.uuid4().hex}.txt").write_text(str(p), encoding="utf-8")
    except OSError:   # only a tidy-up later: never a reason for the add to fail
        log.debug("couldn't note %s as being added", p, exc_info=True)


def drop_unfinished(keep: list[str]) -> int:
    """Files an earlier run started adding that no sound uses (`keep`: every file a
    sound, or a removed one that can still be undone, uses): to the Recycle Bin.
    Returns how many. Call off the UI thread, with settings that loaded as they were
    saved (not a backup, which may not know the newest sounds)."""
    try:
        notes = [n for n in _adding_dir().glob("*.txt") if n.stat().st_mtime < _STARTED]
    except OSError:
        return 0
    used = {os.path.normcase(f) for f in keep}
    gone = 0
    for n in notes:
        try:
            p = Path(n.read_text(encoding="utf-8").strip())
            if owns(p) and p.is_file() and os.path.normcase(str(p)) not in used:
                log.warning("taking out %s: its add didn't finish", p)
                if not (USE_RECYCLE_BIN and recycle(p)):
                    p.unlink()
                discard(p)   # its folder too, when that's empty now
                gone += 1
            n.unlink()
        except (OSError, ValueError):
            log.debug("couldn't tidy the unfinished add in %s", n, exc_info=True)
    return gone


def discard(p: Path) -> None:
    """Undo new_file() after a failed save: the file, and its folder if that's empty now."""
    p.unlink(missing_ok=True)
    if p.parent != paths.SOUNDS_DIR:
        try:
            p.parent.rmdir()   # only goes when empty
        except OSError:
            pass


def import_file(src: str, color: str, name: str = "",
                folder: str = MY_SOUNDS, *, copy: bool = True) -> tuple[SoundMeta, np.ndarray]:
    """Decode, optionally bring into the library, and return metadata + int16 audio.
    `copy=False` links a persistent local source without changing its format. Both
    modes populate the same decoded cache; temporary sources must keep `copy=True`.
    The copy is SOUNDS_DIR/`folder`/`name`.ext (`name`: the sound's name, else the
    file's own; a download passes its title, its temp file is named by video id).

    Plain audio files are copied as they are. Anything that needed ffmpeg (a
    download, video, m4a, aac, wma) is stored as an MP3 of its *audio* instead
    (stored_ext()): a 300 MB video used to be copied whole, and the library stays
    playable if ffmpeg goes away. So is a file libsndfile reads under a name outside
    AUDIO_EXTS (.au, .caf, .w64…): only those come back in from a backup
    (soundboard.core.backup)."""
    sid = uuid.uuid4().hex[:10]
    srcp = Path(src)
    name = name.strip() or srcp.stem.replace("_", " ").strip()
    # Never fall back to using `src` in place: a download's temp folder is deleted
    # right after this. A failed copy leaves nothing behind and says what to do.
    dest = None

    def store(via_ffmpeg: bool) -> Path | None:
        """A long sound to convert is saved while it's decoded (_read): here."""
        nonlocal dest
        if copy and (via_ffmpeg or srcp.suffix.lower() not in AUDIO_EXTS):
            dest = dest or new_file(name, stored_ext(), folder)
            return dest
        return None

    try:
        got = decoding._read(src, sid, store)
        if isinstance(got, _Long):
            if copy and dest is None:          # plain audio: copied as it is
                dest = new_file(name, srcp.suffix, folder)
                shutil.copy2(srcp, dest)
            meta = SoundMeta(id=sid, added=time.time(), name=name[:40].strip() or "Sound",
                             file=str(dest) if copy else str(srcp.absolute()), color=color,
                             level_gain=got.gain, duration=got.frames / SR,
                             fingerprint=fingerprint(src))
            return meta, got.audio
    except Exception as e:
        if dest is None and not isinstance(e, OSError):
            raise                              # it couldn't be read: said as it is
        log.warning("couldn't copy %s into the library", src, exc_info=True)
        if dest is not None:
            discard(dest)
        if isinstance(e, OSError):
            raise OSError(_("couldn't save it into your Sounds folder ({error}). Check "
                            "the disk isn't full and try again.", error=e.strerror or e)) from e
        raise
    data, via_ffmpeg = got
    if not len(data):
        raise ValueError(_("this file has no audio in it"))
    convert = via_ffmpeg or srcp.suffix.lower() not in AUDIO_EXTS
    if not copy:
        # The same decoded cache feeds playback and effects in either storage mode.
        # Only persistent local files may use this path; temporary imports must copy.
        meta = SoundMeta(id=sid, added=time.time(), name=name[:40].strip() or "Sound",
                         file=str(srcp.absolute()), color=color, level_gain=level_gain(data),
                         duration=len(data) / SR, fingerprint=fingerprint(src))
        return meta, store_cached(sid, data)
    try:
        dest = new_file(name, stored_ext() if convert else srcp.suffix, folder)
        if convert:
            write_stored(dest, data)
        else:
            shutil.copy2(srcp, dest)
        meta = SoundMeta(id=sid, added=time.time(), name=name[:40].strip() or "Sound",
                         file=str(dest), color=color, level_gain=level_gain(data),
                         duration=len(data) / SR, fingerprint=fingerprint(src))
        return meta, store_cached(sid, data)
    except Exception as e:
        log.warning("couldn't copy %s into the library", src, exc_info=True)
        if dest is not None:
            discard(dest)
        if isinstance(e, OSError):
            raise OSError(_("couldn't save it into your Sounds folder ({error}). Check "
                            "the disk isn't full and try again.", error=e.strerror or e)) from e
        raise


def save_clip(data: np.ndarray, name: str, color: str,
              folder: str = RECORDINGS) -> tuple[SoundMeta, np.ndarray]:
    """Store recorded audio ((n, 2) float32 at SR) as stored_ext() says; return
    metadata + int16 audio."""
    sid = uuid.uuid4().hex[:10]
    dest = new_file(name, stored_ext(), folder)
    try:
        write_stored(dest, data)
    except BaseException:
        discard(dest)
        raise
    meta = SoundMeta(id=sid, name=name[:40], file=str(dest), color=color, added=time.time(),
                     level_gain=level_gain(data), duration=len(data) / SR,
                     fingerprint=fingerprint(str(dest)))
    return meta, store_cached(sid, data)


def duplicate(meta: SoundMeta, name: str) -> SoundMeta:
    """A copy of a sound with its own library file (so removing either one never
    takes the other's audio with it), cache, id and no hotkey."""
    sid = uuid.uuid4().hex[:10]
    src = Path(meta.file)
    dest = src
    if src.is_file():   # next to the original (one from outside: in My sounds)
        dest = new_file(name, src.suffix, _folder_of(src) or MY_SOUNDS)
        try:
            shutil.copy2(src, dest)
        except BaseException:
            discard(dest)
            raise
        sourceinfo.write(dest, meta.source)   # its own "Song (copy).txt"
    try:
        if cache_path(meta.id).exists():
            paths.CACHE_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cache_path(meta.id), cache_path(sid))
    except OSError:
        log.debug("couldn't copy the cache for %s", meta.id, exc_info=True)
    image = meta.image
    if image and Path(image).parent == paths.THUMBS_DIR:   # its own copy, like the audio
        try:
            image = str(paths.THUMBS_DIR / f"{sid}{Path(image).suffix}")
            shutil.copy2(meta.image, image)
        except OSError:
            log.debug("couldn't copy the picture of %s", meta.id, exc_info=True)
            image = ""
    return SoundMeta(id=sid, name=name[:40], file=str(dest), added=time.time(),
                     volume=meta.volume,
                     mode=meta.mode, loop=meta.loop, color=meta.color,
                     level_gain=meta.level_gain, duration=meta.duration,
                     fingerprint="", fx=dict(meta.fx), image=image, tags=list(meta.tags),
                     fade_in=meta.fade_in, fade_out=meta.fade_out, hold=meta.hold,
                     only_them=meta.only_them, delay=meta.delay, cooldown=meta.cooldown,
                     source=dict(meta.source))


def recycle(path: Path, warn_if_permanent: bool = False) -> bool:
    """Send a file or folder to the Windows Recycle Bin (so it can still be restored
    from there). False if that isn't possible: the caller deletes it instead. With
    `warn_if_permanent`, Windows asks first when it's too big for the bin and would be
    deleted for good (the uninstaller's "delete your sounds"); otherwise it's quiet."""
    if sys.platform != "win32" or not path.exists():
        return False
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
                    ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                    ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]
    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 4, 16, 64, 1024
    FOF_WANTNUKEWARNING = 0x4000
    flags = FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI
    if warn_if_permanent:
        flags |= FOF_WANTNUKEWARNING
    op = SHFILEOPSTRUCTW(wFunc=FO_DELETE, pFrom=str(path.resolve()) + chr(0), fFlags=flags)
    try:
        ok = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0
        return ok and not op.fAnyOperationsAborted and not path.exists()
    except Exception:  # noqa: BLE001
        log.debug("recycling %s failed", path, exc_info=True)
        return False


# tests switch this off so they never fill the real Recycle Bin
USE_RECYCLE_BIN = True


def loose_sounds(cfg: Config) -> list[Path]:
    """Audio files put in the sounds folder by hand (dragged there in Explorer): not
    one of the library's own files (in its folders, or "<id>_name" from before), and
    no sound's file."""
    try:
        files = list(paths.SOUNDS_DIR.iterdir())
    except OSError:
        return []
    used = {os.path.normcase(m.file) for m in cfg.sounds}
    return sorted(p for p in files
                  if p.suffix.lower() in AUDIO_EXTS and not _OUR_SOUND_FILE.match(p.name)
                  and os.path.normcase(str(p)) not in used and p.is_file())


def delete_file(meta: SoundMeta):
    """Remove a sound's files: the audio goes to the Recycle Bin (it's the one thing
    that can't be made again), its picture and decoded cache are deleted."""
    p = Path(meta.file)
    try:
        if owns(p) and not (USE_RECYCLE_BIN and recycle(p)):
            p.unlink(missing_ok=True)
        if owns(p) and meta.source:
            sourceinfo.remove(p)
        if meta.image and Path(meta.image).parent == paths.THUMBS_DIR:
            Path(meta.image).unlink(missing_ok=True)
    except OSError:
        log.warning("couldn't delete %s", p, exc_info=True)
    unlink_cache(meta.id)


_VIDEO_ID = re.compile(r"(?=.*[0-9A-Z])[A-Za-z0-9_-]{11}")   # a YouTube video's


def _old_folder(rest: str) -> str:
    """The folder for a file from before library folders, by the "<name>" of its
    "<id>_<name>": downloads were named by their video id."""
    if _VIDEO_ID.fullmatch(rest):
        return "YouTube"
    if rest.isdigit() and len(rest) >= 8:   # TikTok, X...: a long number
        return DOWNLOADS
    return MY_SOUNDS


def _tidy_journal() -> Path:
    """tidy_files' list of moves ("<was>\\t<now>" a line), written before each one and
    deleted once the settings are saved: a crash or power cut in between is undone at
    the next start (_undo_tidy)."""
    return paths.APP_DIR / "tidy-moves.txt"


def _undo_tidy(cfg: Config) -> int:
    """A tidy_files that stopped before its settings were saved: the sounds still name
    the old files, so put back each one that moved (and drop a name claimed but never
    used). Moves the settings already know about stay. The list is kept while a file
    won't move back (open in another program), for the next start. Returns how many
    went back."""
    journal = _tidy_journal()
    try:
        lines = journal.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return 0
    except OSError:
        log.warning("couldn't read %s", journal, exc_info=True)
        return 0
    used = {os.path.normcase(m.file) for m in cfg.sounds}
    back, stuck = 0, False
    for line in lines:
        was, sep, now = line.partition("\t")
        if not sep:   # cut short by the power cut: its move never happened
            continue
        was_p, now_p = Path(was), Path(now)
        if os.path.normcase(now) in used or not now_p.is_file():
            continue
        try:
            if os.path.normcase(was) in used and not was_p.exists():
                os.replace(now_p, was_p)
                back += 1
            elif now_p.stat().st_size == 0:   # claimed by new_file, never filled
                discard(now_p)
        except OSError:
            log.warning("couldn't put %s back after an unfinished tidy", now, exc_info=True)
            stuck = True
    if not stuck:
        journal.unlink(missing_ok=True)
    if back:
        log.warning("put %d sound files back after an unfinished tidy", back)
    return back


def tidy_files(cfg: Config) -> int:
    """Move the sound files from before library folders ("<id>_<name>" in SOUNDS_DIR
    itself) into them, under the sound's own name: "YouTube/Never Gonna Give You
    Up.flac". At the start, before anything reads them. A file that can't move (open
    in another program) stays as it is, for the next start. The settings are saved
    at once: if they can't be, the files go back; if the app stops before then, the
    next start puts them back (_undo_tidy) and tries again. Returns how many moved."""
    if cfg.read_only:
        return 0
    _undo_tidy(cfg)
    if _tidy_journal().exists():   # some couldn't go back yet: don't add to the list
        return 0
    moved: dict[Path, Path] = {}
    journal = None
    changed: list[tuple[SoundMeta, str]] = []
    for m in cfg.sounds:
        p = Path(m.file)
        if p.parent != paths.SOUNDS_DIR or not _OUR_SOUND_FILE.match(p.name):
            continue
        if p not in moved:   # two sounds on one file: both follow it
            if not p.is_file():
                continue
            rest = Path(p.name[11:]).stem
            dest = None
            try:
                dest = new_file(m.name or rest, p.suffix, _old_folder(rest), note=False)
                if journal is None:
                    journal = open(_tidy_journal(), "a", encoding="utf-8")  # noqa: SIM115
                journal.write(f"{p}\t{dest}\n")
                journal.flush()
                os.fsync(journal.fileno())   # on disk before the move it undoes
                os.replace(p, dest)
            except OSError:
                log.warning("couldn't move %s into a library folder", p.name, exc_info=True)
                if dest is not None:
                    dest.unlink(missing_ok=True)
                continue
            moved[p] = dest
        changed.append((m, m.file))
        m.file = str(moved[p])
    if journal is not None:
        journal.close()
    saved = not moved or cfg.save()
    if saved:
        try:
            _tidy_journal().unlink(missing_ok=True)
        except OSError:   # harmless: the sounds name the new files, nothing goes back
            log.warning("couldn't remove the tidy list", exc_info=True)
    if not saved:
        log.warning("couldn't save the settings: the sound files go back where they were")
        all_back = True
        for was, now in moved.items():
            try:
                os.replace(now, was)
            except OSError:   # then the sounds keep the new place: saved next time, or
                log.warning("couldn't move %s back", now, exc_info=True)
                all_back = False   # if never saved, the kept list puts it back next start
                continue
            for m, old in changed:
                if Path(old) == was:
                    m.file = old
        if all_back:
            _tidy_journal().unlink(missing_ok=True)
        return 0
    if moved:
        log.info("moved %d sound files into library folders", len(moved))
    return len(moved)
