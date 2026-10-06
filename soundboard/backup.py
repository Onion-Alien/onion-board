"""Export and import: your board (sounds, their settings, categories and, if you like,
the app's settings) as one plain .zip, to move to a new PC or share.

The format is meant to be easy to read, write and pick apart by hand or by other
tools (docs/BACKUP-FORMAT.md has the full description):

    onionboard.json                 what's inside: format, version, categories, pad order
    settings.json                   optional: the app's settings (no devices, no opt-ins)
    sounds/001 Airhorn/sound.json   one folder per sound: its name, volume, hotkey,
    sounds/001 Airhorn/Airhorn.mp3    effects, categories… plus the audio file as it was
    sounds/001 Airhorn/picture.jpg    imported and its pad picture

Every sound folder stands on its own: a zip (or a plain folder) holding just one
`sound.json` and its audio imports as a single sound, and a zip of several sound
folders with no `onionboard.json` is a sound pack. Nothing in the archive is ever
used as a path: files are found by the names the JSON gives and written under new
names of our own, with a limit on each file and on the whole import (checked against
the free space first), so a crafted archive can't write elsewhere or fill the disk.
"""
from __future__ import annotations

import json
import logging
import math
import re
import shutil
import tempfile
import time
import uuid
import zipfile
import zlib
from dataclasses import dataclass, field, fields
from pathlib import Path, PurePosixPath

import soundfile as sf

from soundboard import __version__, library, savedvoices, voicefx
from soundboard.library import (AUDIO_EXTS, Config, SoundMeta, clean_fade, clean_setting,
                                clean_tags, fits_type)
from soundboard.speech.live import clean_settings as clean_speech_settings
from soundboard import errors

log = logging.getLogger(__name__)

FORMAT = "onionboard-board"
FORMAT_VERSION = 1
MANIFEST = "onionboard.json"
SETTINGS = "settings.json"
SAVED_VOICES = "saved_voices"   # settings.json: the voice changer's saved voices
SOUND_JSON = "sound.json"
PICTURE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".jfif"}
MAX_FILE = 1 << 30          # 1 GiB for any one file in an archive
MAX_JSON = 4 << 20          # 4 MiB for a JSON file
MAX_PICTURE = 64 << 20      # 64 MiB for a pad picture
MAX_TOTAL = 8 << 30         # 8 GiB for everything one import writes
DISK_SPARE = 256 << 20      # free space an import must leave behind
# speech-to-text models the live voice may be told to load (ui.voicepanel.MODELS): any
# other name would make faster-whisper download that repo from Hugging Face
SPEECH_MODELS = ("base.en", "tiny.en", "small.en", "base", "small")
LANGUAGE_RE = re.compile(r"[a-z]{2,3}")
# compressing these again gains nothing
STORED = {".mp3", ".ogg", ".opus", ".m4a", ".aac", ".flac", ".wma", ".webm", ".mp4",
          ".mkv", ".mov", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".jfif"}
# settings that belong to this PC, or that must only ever be switched on by hand
# (they make the app go online / run downloaded code): never exported or imported
LOCAL_SETTINGS = {"version", "sounds", "categories", "category", "main_device", "mon_device",
                  "mic_device", "obs_device", "also_send", "route", "mic_first", "cable_tip_done",
                  "setup_done", "tab", "apps", "apps_paths", "screen",
                  "ytdlp_auto_optin", "update_check", "update_checked", "update_skip",
                  "update_pending", "category_hotkeys", "api_enabled", "api_port",
                  "api_token", "remote_addons", "net_mode", "net_proxy",
                  "net_off", "net_offline", "tor_bridges", "data", "stats_id",
                  "stats_sent", "stats_heard", "stats_tabs", "stats_problems_seen"}
# per-sound fields that are written to sound.json (the paths are replaced by names)
SOUND_FIELDS = ("name", "volume", "hotkey", "mode", "loop", "color", "level_gain",
                "duration", "fingerprint", "fx", "tags", "fade_in", "fade_out", "hold",
                "only_them", "delay", "cooldown")


class BackupError(Exception):
    """An archive that can't be read: the message is shown to the user as is."""


# --------------------------------------------------------------------------- export

def export(dest: str | Path, sounds: list[SoundMeta], cfg: Config | None = None,
           categories: list[str] | None = None) -> int:
    """Write `sounds` (in this order) to the zip `dest`; with `cfg`, the app's settings
    too. Written to a temp file first, so a failure never leaves half an archive.
    Returns how many sounds went in (ones whose audio file is missing are skipped)."""
    dest = Path(dest)
    tmp = dest.with_name(dest.name + ".part")
    used_cats = {t for m in sounds for t in m.tags}
    cats = [c for c in (categories or []) if c in used_cats or cfg is not None]
    folders = []
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for m in sounds:
                audio = Path(m.file)
                if not audio.is_file():
                    log.warning("export: %s has no audio file (%s); skipped", m.name, audio)
                    continue
                folder = f"sounds/{len(folders) + 1:03d} {_safe(m.name)}"
                entry = {k: getattr(m, k) for k in SOUND_FIELDS}
                entry["audio"] = _safe(_original_name(audio), keep_ext=True)
                entry["picture"] = ""
                if audio.suffix.lower() in AUDIO_EXTS:
                    _add_file(z, audio, f"{folder}/{entry['audio']}")
                else:   # only AUDIO_EXTS are read back in: a .caf, .au… goes as a FLAC
                    entry["audio"] = Path(entry["audio"]).stem + ".flac"
                    try:
                        _add_as_flac(z, audio, f"{folder}/{entry['audio']}")
                    except Exception:  # noqa: BLE001 - one odd file mustn't stop the rest
                        log.warning("export: can't convert %s; skipped", audio, exc_info=True)
                        continue
                pic = Path(m.image) if m.image else None
                if pic and pic.is_file() and pic.suffix.lower() in PICTURE_EXTS:
                    entry["picture"] = "picture" + pic.suffix.lower()
                    _add_file(z, pic, f"{folder}/{entry['picture']}")
                z.writestr(f"{folder}/{SOUND_JSON}", json.dumps(entry, indent=2))
                folders.append(folder)
            if cfg is not None:
                z.writestr(SETTINGS, json.dumps(settings_of(cfg), indent=2))
            manifest = {"format": FORMAT, "format_version": FORMAT_VERSION,
                        "app_version": __version__,
                        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "categories": cats, "sounds": folders,
                        "settings": SETTINGS if cfg is not None else None}
            z.writestr(MANIFEST, json.dumps(manifest, indent=2))
        tmp.replace(dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return len(folders)


def settings_of(cfg: Config) -> dict:
    """The app's settings as they're exported: everything except LOCAL_SETTINGS, plus
    the voice changer's saved voices (kept in a file of their own, savedvoices.py)."""
    raw = cfg.to_raw()
    out = {k: v for k, v in raw.items() if k not in LOCAL_SETTINGS}
    if voices := savedvoices.saved():
        out[SAVED_VOICES] = voices
    return out


def _original_name(audio: Path) -> str:
    """The library stores files as '<id>_<original name>': give them back their name."""
    name = audio.name
    head, sep, rest = name.partition("_")
    if sep and len(head) == 10 and all(c in "0123456789abcdef" for c in head) and rest:
        return rest
    return name


def _safe(name: str, keep_ext: bool = False) -> str:
    """A name that's fine as a file / folder name in a zip and on Windows."""
    stem, ext = (Path(name).stem, Path(name).suffix.lower()) if keep_ext else (name, "")
    s = "".join(c if c.isalnum() or c in " -_()." else "_" for c in stem).strip(" .")[:60]
    return (s or "sound") + ext


def _add_file(z: zipfile.ZipFile, src: Path, arcname: str):
    comp = zipfile.ZIP_STORED if src.suffix.lower() in STORED else zipfile.ZIP_DEFLATED
    z.write(src, arcname, compress_type=comp)


def _add_as_flac(z: zipfile.ZipFile, src: Path, arcname: str):
    """Add `src` to the zip re-encoded as FLAC (at its own rate and channels when
    libsndfile reads it, else as the app decodes it)."""
    with tempfile.TemporaryDirectory(prefix="onionboard-export-") as td:
        tmp = Path(td) / "sound.flac"
        try:
            with sf.SoundFile(src) as fin, sf.SoundFile(
                    tmp, "w", fin.samplerate, fin.channels, "PCM_16", format="FLAC") as fout:
                for block in fin.blocks(1 << 16, dtype="float32", always_2d=True):
                    fout.write(block)
        except Exception:  # noqa: BLE001 - too many channels for FLAC, an odd rate…
            log.debug("export: re-encoding %s as it plays", src, exc_info=True)
            sf.write(tmp, library.decode(str(src)), library.SR, subtype="PCM_16")
        _add_file(z, tmp, arcname)


# --------------------------------------------------------------------------- reading

@dataclass
class PackedSound:
    folder: str                 # where it is in the archive ("" = the root)
    entry: dict                 # its sound.json
    audio: str                  # archive path of the audio file
    picture: str = ""           # archive path of the picture, or ""


@dataclass
class Package:
    path: Path
    sounds: list[PackedSound] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    settings: dict | None = None
    app_version: str = ""
    created: str = ""
    is_board: bool = False      # has an onionboard.json (else: a sound or a sound pack)


# What a damaged / unreadable zip can raise while it's opened or read: a bad
# header, a broken deflate stream, a password (RuntimeError), a compression this
# Python can't do (NotImplementedError, e.g. Deflate64), a truncated file.
_ZIP_ERRORS = (OSError, zipfile.BadZipFile, zlib.error, RuntimeError,
               NotImplementedError, EOFError, ValueError)


def _unreadable(name: str) -> str:
    return (f"{name} is damaged or uses a format Onion Board can't read. "
            "Export it again, or re-zip it with Windows (Send to → Compressed folder).")


class _Source:
    """A zip or a folder, seen the same way: names use '/', relative to the root."""

    def __init__(self, path: Path):
        self.path = path
        self.zip = None
        if path.is_dir():
            self._names = {p.relative_to(path).as_posix(): p for p in path.rglob("*")
                           if p.is_file()}
        else:
            try:
                self.zip = zipfile.ZipFile(path)
            except _ZIP_ERRORS as e:
                raise BackupError(_unreadable(path.name)) from e
            self._names = {i.filename: i for i in self.zip.infolist() if not i.is_dir()}

    def close(self):
        if self.zip is not None:
            self.zip.close()

    def names(self) -> list[str]:
        return list(self._names)

    def has(self, name: str) -> bool:
        return name in self._names

    def size(self, name: str) -> int:
        it = self._names[name]
        return it.file_size if self.zip is not None else it.stat().st_size

    def open(self, name: str):
        it = self._names[name]
        return self.zip.open(it) if self.zip is not None else it.open("rb")

    def json(self, name: str) -> dict:
        if self.size(name) > MAX_JSON:
            raise BackupError(f"{name} is too big to be a settings file.")
        try:
            with self.open(name) as f:
                data = json.loads(f.read(MAX_JSON + 1).decode("utf-8-sig"))
        except _ZIP_ERRORS as e:   # ValueError covers bad JSON and UnicodeDecodeError
            raise BackupError(f"{name} in the backup is damaged.") from e
        if not isinstance(data, dict):
            raise BackupError(f"{name} in the backup is damaged.")
        return data


def _join(folder: str, name) -> str:
    """folder + a file name taken from JSON: only a plain name, never a path."""
    if not isinstance(name, str) or not name or PurePosixPath(name).name != name \
            or "\\" in name or name in (".", ".."):
        return ""
    return f"{folder}/{name}" if folder else name


def read(path: str | Path) -> Package:
    """What's in a backup / sound pack / single sound (zip or folder). Raises
    BackupError with a message for the user if it isn't one."""
    path = Path(path)
    src = _Source(path)
    try:
        return _read(src, path)
    except BackupError:
        raise
    except Exception as e:  # noqa: BLE001 - a damaged or odd file: say so, don't crash
        log.warning("import: can't read %s", path, exc_info=True)
        raise BackupError(_unreadable(path.name)) from e
    finally:
        src.close()


def _read(src: _Source, path: Path) -> Package:
    pkg = Package(path)
    if src.has(MANIFEST):
        man = src.json(MANIFEST)
        if man.get("format") != FORMAT:
            raise BackupError(f"{path.name} isn't an Onion Board backup.")
        try:
            version = float(man.get("format_version", 0) or 0)
        except (TypeError, ValueError):
            raise BackupError(_unreadable(path.name)) from None
        if version > FORMAT_VERSION:
            raise BackupError(f"{path.name} was made by a newer Onion Board "
                              f"({man.get('app_version', '?')}). Update the app to import it.")
        pkg.is_board = True
        pkg.app_version = str(man.get("app_version", ""))
        pkg.created = str(man.get("created", ""))
        pkg.categories = clean_tags(man.get("categories"))
        order = man.get("sounds")
        order = [f for f in order if isinstance(f, str)] if isinstance(order, list) else []
        order = list(dict.fromkeys(order))   # a folder listed twice is still one sound
        sname = man.get("settings")
        if isinstance(sname, str) and src.has(sname):
            pkg.settings = src.json(sname)
    else:
        order = []
    # every folder with a sound.json, in the manifest's order, then any others
    found = sorted(n[:-len(SOUND_JSON)].rstrip("/") for n in src.names()
                   if n == SOUND_JSON or n.endswith("/" + SOUND_JSON))
    folders = [f for f in order if f in found] + [f for f in found if f not in order]
    for folder in folders:
        try:
            entry = src.json(_join(folder, SOUND_JSON))
        except BackupError:
            log.warning("import: %s/%s is damaged; skipped", folder, SOUND_JSON)
            continue
        audio = _join(folder, entry.get("audio"))
        if not audio or not src.has(audio) or Path(audio).suffix.lower() not in AUDIO_EXTS:
            log.warning("import: %s has no usable audio file; skipped", folder)
            continue
        pic = _join(folder, entry.get("picture"))
        if not pic or not src.has(pic) or Path(pic).suffix.lower() not in PICTURE_EXTS:
            pic = ""
        pkg.sounds.append(PackedSound(folder, entry, audio, pic))
    if not pkg.sounds and pkg.settings is None:
        if pkg.is_board:
            raise BackupError(f"{path.name} has no sounds or settings in it.")
        raise BackupError(f"{path.name} has no sound files in it, and isn't an Onion Board "
                          "backup or sound pack.")
    return pkg


# ----------------------------------------------------------------- a plain zip of sounds

def _is_junk(name: str) -> bool:
    """macOS resource forks and the like that ride along in zips made on a Mac."""
    p = PurePosixPath(name)
    return p.parts[0] == "__MACOSX" or p.name.startswith("._")


def loose_audio(path: str | Path) -> list[str]:
    """The audio files in a plain zip of sounds (one with no onionboard.json or
    sound.json), in name order. [] for a backup or sound pack, a zip with no audio,
    or one that can't be read: those go to read(), which says what's wrong."""
    path = Path(path)
    if path.is_dir() or path.suffix.lower() != ".zip":
        return []
    try:
        src = _Source(path)
    except BackupError:
        return []
    try:
        names = src.names()
        if any(n == MANIFEST or n == SOUND_JSON or n.endswith("/" + SOUND_JSON)
               for n in names):
            return []
        return sorted((n for n in names if PurePosixPath(n).suffix.lower() in AUDIO_EXTS
                       and not _is_junk(n)), key=str.lower)
    finally:
        src.close()


def extract_loose(path: str | Path, names: list[str], dest_dir: Path
                  ) -> list[tuple[str, Path | None, str]]:
    """Unpack `names` (from loose_audio) into `dest_dir` to be imported like dropped
    files: (name, where it went or None, why not). Each lands in a folder of its own
    under a safe name that keeps its own stem, since that becomes the sound's name.
    Raises BackupError (before anything is written) if the zip is too big or the disk
    too full."""
    path = Path(path)
    src = _Source(path)
    out = []
    try:
        total = sum(min(src.size(n), MAX_FILE + 1) for n in names if src.has(n))
        if total > MAX_TOTAL:
            raise BackupError(f"{path.name} holds {_size(total)} of sounds, more than the "
                              f"{_size(MAX_TOTAL)} one import can take. Import it in parts.")
        dest_dir.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(dest_dir).free
        if 2 * total + DISK_SPARE > free:   # unpacked here, then copied into the library
            raise BackupError(f"There isn't enough free disk space to import {path.name}: "
                              f"it needs {_size(2 * total + DISK_SPARE)} and {_size(free)} "
                              "is free.")
        budget = _Budget(total)
        for i, n in enumerate(names):
            shown = PurePosixPath(n).name
            if not src.has(n):
                out.append((n, None, f"{shown}: not in the zip"))
                continue
            dest = dest_dir / f"{i:04d}" / _safe(shown, keep_ext=True)
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                _extract(src, n, dest, budget=budget)
            except (BackupError, *_ZIP_ERRORS) as e:
                log.warning("import: can't unpack %s from %s", n, path.name, exc_info=True)
                why = str(e) if isinstance(e, BackupError) else "damaged in the zip"
                out.append((n, None, f"{shown}: {why}"))
                continue
            out.append((n, dest, ""))
    finally:
        src.close()
    return out


# --------------------------------------------------------------------------- import

@dataclass
class Imported:
    sounds: list[SoundMeta] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)   # names already in the library
    failed: list[str] = field(default_factory=list)    # "name: why"


def install(pkg: Package, known_fingerprints: set[str], color_for=None) -> Imported:
    """Copy the package's sounds into the library, as new sounds with ids of their own.
    Sounds whose fingerprint is already in the library are skipped (importing the same
    backup twice adds nothing); copies inside the package are all kept, since "Save as
    new sound" makes pads that share their audio. The audio is decoded later, by the
    normal loader."""
    out = Imported()
    known = set(known_fingerprints)
    src = _Source(pkg.path)
    try:
        budget = _Budget(_check_room(src, pkg))
        for i, ps in enumerate(pkg.sounds):
            name = str(ps.entry.get("name") or Path(ps.audio).stem)[:40]
            fp = ps.entry.get("fingerprint")
            if isinstance(fp, str) and fp and fp in known:
                out.skipped.append(name)
                continue
            try:
                meta = _install_one(src, ps, name, color_for(i) if color_for else None,
                                    budget)
            except (OSError, BackupError, zipfile.BadZipFile) as e:
                log.warning("import of %s failed", ps.folder, exc_info=True)
                out.failed.append(f"{name}: {errors.plain(e)}")
                continue
            except Exception:  # noqa: BLE001 - one odd sound mustn't stop the rest
                log.warning("import of %s failed", ps.folder, exc_info=True)
                out.failed.append(f"{name}: it's damaged or in a format Onion Board "
                                  "can't read")
                continue
            out.sounds.append(meta)
    finally:
        src.close()
    return out


def _check_room(src: _Source, pkg: Package) -> int:
    """The bytes this import may write: what the archive says its sounds and pictures
    take, once it's known that is under MAX_TOTAL and fits on the disk with room to
    spare. Raises BackupError (before anything is written) if not."""
    total = 0
    for ps in pkg.sounds:
        for name, limit in ((ps.audio, MAX_FILE), (ps.picture, MAX_PICTURE)):
            if name and src.has(name):
                total += min(src.size(name), limit + 1)
    if total > MAX_TOTAL:
        raise BackupError(f"{pkg.path.name} holds {_size(total)} of sounds, more than the "
                          f"{_size(MAX_TOTAL)} one import can take. Import it in parts.")
    library.SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(library.SOUNDS_DIR).free
    if total + DISK_SPARE > free:
        raise BackupError(f"There isn't enough free disk space to import {pkg.path.name}: "
                          f"it needs {_size(total + DISK_SPARE)} and {_size(free)} is free.")
    return total


def _size(n: int) -> str:
    return f"{n / (1 << 30):.1f} GB" if n >= 1 << 30 else f"{max(n >> 20, 1)} MB"


def _install_one(src: _Source, ps: PackedSound, name: str, color: str | None,
                 budget: _Budget | None = None) -> SoundMeta:
    sid = uuid.uuid4().hex[:10]
    library.SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    audio_name = _safe(PurePosixPath(ps.audio).name, keep_ext=True)
    dest = library.SOUNDS_DIR / f"{sid}_{audio_name}"
    _extract(src, ps.audio, dest, budget=budget)
    try:
        return _fill_meta(src, ps, sid, name, color, dest, budget)
    except BaseException:
        dest.unlink(missing_ok=True)   # don't leave an orphan audio file behind
        raise


def _fill_meta(src: _Source, ps: PackedSound, sid: str, name: str, color: str | None,
               dest: Path, budget: _Budget | None = None) -> SoundMeta:
    from soundboard import thumbs
    meta = SoundMeta(id=sid, name=name, file=str(dest))
    defaults = {f.name: getattr(meta, f.name) for f in fields(SoundMeta)}
    for k in SOUND_FIELDS:
        v = ps.entry.get(k)
        if k == "name" or v is None:
            continue
        if _accept(defaults[k], v):
            setattr(meta, k, float(v) if isinstance(defaults[k], float) else v)
    meta.tags = clean_tags(meta.tags)
    meta.volume = min(max(meta.volume, 0.0), 2.0)
    meta.level_gain = min(max(meta.level_gain, 0.1), 6.0)
    meta.fade_in, meta.fade_out = clean_fade(meta.fade_in), clean_fade(meta.fade_out)
    meta.delay = library.clean_wait(meta.delay, "delay")
    meta.cooldown = library.clean_wait(meta.cooldown, "cooldown")
    if meta.mode not in library.MODES:
        meta.mode = "restart"
    if not (meta.color.startswith("#") and len(meta.color) in (4, 7)):
        meta.color = color or library.PAD_COLORS[0]
    if not meta.fingerprint:
        meta.fingerprint = library.fingerprint(str(dest))
    if ps.picture:
        with tempfile.TemporaryDirectory(prefix="onionboard-import-") as td:
            tmp = Path(td) / ("picture" + Path(ps.picture).suffix.lower())
            try:
                _extract(src, ps.picture, tmp, limit=MAX_PICTURE, budget=budget)
                meta.image = thumbs.store(tmp, sid)   # re-encoded: only a real picture gets in
            except (BackupError, *_ZIP_ERRORS):
                log.debug("import: the picture of %s didn't come across", name, exc_info=True)
    return meta


class _Budget:
    """How many more bytes one import may write, across all its files."""

    def __init__(self, left: int):
        self.left = left


def _extract(src: _Source, name: str, dest: Path, limit: int | None = None,
             budget: _Budget | None = None):
    limit = MAX_FILE if limit is None else limit
    if src.size(name) > limit:
        raise BackupError(f"{PurePosixPath(name).name} is too big")
    tmp = dest.with_name(dest.name + ".part")
    n = 0
    try:
        with src.open(name) as fin, open(tmp, "wb") as fout:
            while chunk := fin.read(1 << 20):
                n += len(chunk)
                if n > limit:   # the zip's header lied about the size
                    raise BackupError(f"{PurePosixPath(name).name} is too big")
                if budget is not None and n > budget.left:   # so did the whole archive
                    raise BackupError(f"{PurePosixPath(name).name} doesn't fit: the backup "
                                      "holds more than it says")
                fout.write(chunk)
        tmp.replace(dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    finally:
        if budget is not None:
            budget.left -= n


def apply_settings(cfg: Config, raw: dict) -> list[str]:
    """Put exported settings onto `cfg`. Only known settings of the right type are
    taken, and never the LOCAL_SETTINGS. Returns the names that changed."""
    defaults = Config()
    changed = []
    for k, v in raw.items():
        if k in LOCAL_SETTINGS or k not in Config.__dataclass_fields__:
            continue
        want = getattr(defaults, k)
        if want is None:
            ok = v is None or isinstance(v, str)
        else:
            ok = _accept(want, v)
        if not ok:
            continue
        if isinstance(want, float):
            v = float(v)
        if v is not None:
            v = clean_setting(k, v)   # into its control's range (None: unusable)
            if v is None:
                continue
        if k == "speech":
            v = _clean_speech(clean_speech_settings(v))
        elif k == "voice_fx":
            v = voicefx.clean_spec(v)
        elif k == "radio":
            v = _clean_radio(v)
        if getattr(cfg, k) != v:
            setattr(cfg, k, v)
            changed.append(k)
    return changed


def _finite(v) -> bool:
    """No NaN or Infinity anywhere in `v` (Python's json reads them; one in a volume or
    an effect setting would poison the audio mix)."""
    if isinstance(v, float):
        return math.isfinite(v)
    if isinstance(v, dict):
        return all(_finite(x) for x in v.values())
    if isinstance(v, list):
        return all(_finite(x) for x in v)
    return True


def _accept(default, v) -> bool:
    """Is `v`, read from an archive, usable for a field whose default is `default`:
    the right type, with no non-finite number in it, however deep."""
    return fits_type(default, v) and _finite(v)


def _clean_speech(raw: dict) -> dict:
    """Imported speech settings, minus a model or language the live voice mustn't be
    handed (an unknown model name makes faster-whisper download it from Hugging Face)."""
    out = dict(raw)
    if out.get("model") not in SPEECH_MODELS:
        out.pop("model", None)
    lang = out.get("language")
    if not (isinstance(lang, str) and (lang == "auto" or LANGUAGE_RE.fullmatch(lang))):
        out.pop("language", None)
    return out


def _clean_radio(raw: dict) -> dict:
    """Imported Radio tab settings: only its known fields, each of the right shape
    (stations are checked again by radio.Station.from_saved when they're used)."""
    out = {}
    vol = raw.get("vol")
    if isinstance(vol, (int, float)) and not isinstance(vol, bool) and math.isfinite(vol):
        out["vol"] = min(max(float(vol), 0.0), 10.0)
    if isinstance(raw.get("monitor"), bool):
        out["monitor"] = raw["monitor"]
    for k in ("favorites", "recent"):
        if isinstance(raw.get(k), list):
            out[k] = [s for s in raw[k] if isinstance(s, dict)]
    if isinstance(raw.get("last"), dict):
        out["last"] = raw["last"]
    return out

