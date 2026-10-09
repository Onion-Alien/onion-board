"""Recently deleted: removed sounds and forgotten programs, kept for a while so they
can be brought back.

A removed sound's audio and picture move into %APPDATA%\\OnionBoard\\deleted\\, and
its pad (name, volume, hotkey, effects, categories…) is written to deleted.json
beside them. A forgotten program keeps its volume and "Hear it myself". Entries
older than KEEP_DAYS, or past the newest MAX_ITEMS, go for good: a sound's audio
then goes to the Windows Recycle Bin, as a removal used to straight away.

The folder is looked up on every call (library.APP_DIR), so tests that point the
library somewhere else get their own bin.
"""
from __future__ import annotations

import json
import logging
import shutil
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from soundboard import library
from soundboard.i18n import _, ngettext
from soundboard.library import SoundMeta

log = logging.getLogger(__name__)

KEEP_DAYS = 30
MAX_ITEMS = 200
SOUND, APP = "sound", "app"
_lock = threading.RLock()   # startup prunes on the loader thread


def folder() -> Path:
    return library.APP_DIR / "deleted"


def _index() -> Path:
    return folder() / "deleted.json"


@dataclass
class Item:
    id: str
    kind: str                 # SOUND | APP
    name: str                 # what the list shows
    when: float               # time.time() it was deleted
    data: dict = field(default_factory=dict)   # SOUND: the SoundMeta; APP: exe, spec
    index: int = 0            # SOUND: where it was on the board


def load() -> list[Item]:
    """What's in the bin, oldest first. A damaged file reads as an empty bin."""
    return _read()[0]


def _read(tries: int = 1) -> tuple[list[Item], bool]:
    """The bin, and False when its index exists but couldn't be read (locked by an
    antivirus or OneDrive): then it mustn't be saved over, or everything in it is lost.
    A locked file is tried `tries` times. A damaged one is set aside
    (deleted.json.broken-<time>, its files stay in the folder) before the bin starts
    over; if it can't be, it's treated as locked."""
    for n in range(tries):
        try:
            raw = json.loads(_index().read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError(f"the bin's list is a {type(raw).__name__}")
            break
        except FileNotFoundError:
            return [], True
        except ValueError:   # damaged for good: starting over is all that's left
            log.warning("couldn't read %s", _index(), exc_info=True)
            return [], _set_aside()
        except OSError:
            if n == tries - 1:
                log.warning("couldn't read %s", _index(), exc_info=True)
                return [], False
            time.sleep(0.1)
    return _items(raw), True


def _items(raw) -> list[Item]:
    items = []
    for d in raw.get("items", []) if isinstance(raw, dict) else []:
        try:
            it = Item(id=str(d["id"]), kind=str(d["kind"]), name=str(d.get("name", "")),
                      when=float(d.get("when", 0)), data=dict(d.get("data") or {}),
                      index=int(d.get("index", 0)))
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        if it.kind in (SOUND, APP):
            items.append(it)
    return items


def _set_aside() -> bool:
    """Move a damaged index out of the way, so saving the bin doesn't overwrite it."""
    broken = _index().with_name(f"deleted.json.broken-{time.strftime('%Y%m%d-%H%M%S')}")
    try:
        _index().replace(broken)
    except FileNotFoundError:
        return True
    except OSError:
        log.warning("couldn't set the damaged %s aside", _index(), exc_info=True)
        return False
    log.warning("set the damaged bin list aside as %s", broken.name)
    return True


def _save(items: list[Item]) -> None:
    try:
        folder().mkdir(parents=True, exist_ok=True)
        tmp = _index().with_suffix(".tmp")
        tmp.write_text(json.dumps({"items": [asdict(i) for i in items]}, indent=1),
                       encoding="utf-8")
        tmp.replace(_index())
    except OSError:
        log.exception("couldn't save %s", _index())


def items(kind: str | None = None) -> list[Item]:
    """The bin, newest first (only `kind` if given)."""
    return [i for i in reversed(load()) if kind is None or i.kind == kind]


def _move(src: Path, dest_dir: Path) -> Path:
    """Move a file into dest_dir under its own name, or a free one next to it."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    n = 1
    while dest.exists():
        dest = dest_dir / f"{src.stem}-{n}{src.suffix}"
        n += 1
    shutil.move(str(src), dest)
    return dest


def put_sound(meta: SoundMeta, index: int) -> None:
    """A sound came off the board: keep its files and its pad in the bin. Its decoded
    cache is just deleted (it's made again from the audio)."""
    d = library._with_raw(asdict(meta), meta)   # a newer version's fields too
    try:
        p = Path(meta.file)
        if library.owns(p) and p.exists():   # kept in the bin in its library folder
            sub = p.parent.relative_to(library.SOUNDS_DIR)   # ("YouTube/Song.flac")
            d["file"] = _move(p, folder() / sub).relative_to(folder()).as_posix()
    except OSError:
        log.warning("couldn't move %s to the bin; removing it instead", meta.file,
                    exc_info=True)
        library.delete_file(meta)
        return
    try:
        if meta.image and Path(meta.image).parent == library.THUMBS_DIR \
                and Path(meta.image).exists():
            d["image"] = _move(Path(meta.image), folder()).name
    except OSError:   # the audio is in the bin already: the picture stays where it is
        log.warning("couldn't move %s to the bin", meta.image, exc_info=True)
    library.unlink_cache(meta.id)
    item = Item(uuid.uuid4().hex[:12], SOUND, meta.name, time.time(), d, index)
    if not _add(item):   # unlisted, it could never come back: removed instead, the
        _destroy(item)   # audio to the Recycle Bin, as a removal used to


def put_app(exe: str, spec: dict, name: str, hidden: bool = False, path: str = "") -> Item:
    """A program was forgotten: keep what was remembered about it (`spec`, maybe
    empty), and whether it was also taken off the Apps tab's list (`hidden`). `path`:
    it was another program of that name, remembered by its folder (cfg.apps_paths)."""
    data = {"exe": exe, "spec": dict(spec), "hidden": hidden}
    if path:
        data["path"] = path
    item = Item(uuid.uuid4().hex[:12], APP, name or exe, time.time(), data)
    _add(item)
    return item


def _add(item: Item) -> bool:
    """False if the bin's list is locked: the rest of the bin is kept, unchanged."""
    with _lock:
        all_, ok = _read(tries=10)
        if not ok:
            log.warning("the bin's list is locked: %s isn't listed in it", item.name)
            return False
        all_.append(item)
        _save(_prune(all_))
        return True


def _in_bin(name: str) -> Path | None:
    """A file name stored for a binned sound, as a path inside the bin (or an outside
    file the sound pointed at, left where it was)."""
    if not name:
        return None
    p = Path(name)
    if ".." in p.parts:   # never a file outside the bin by way of its list
        return None
    return p if p.is_absolute() else folder() / p


def _ours(p: Path) -> bool:
    """A file the bin keeps itself (in it, or in a library folder's copy in it)."""
    return p != folder() and p.is_relative_to(folder())


def take(item_id: str) -> Item | None:
    """Take an entry out of the bin to bring it back. For a sound, its files move back
    into the library and `data` is ready for SoundMeta(**data). None if it's gone."""
    with _lock:
        all_ = load()
        item = next((i for i in all_ if i.id == item_id), None)
        if item is None:
            return None
        if item.kind == SOUND:
            d = dict(item.data)
            f = _in_bin(d.get("file", ""))
            moved = None
            try:
                if f is not None and _ours(f):
                    if not f.exists():
                        log.warning("the bin lost %s", f)
                        return None   # back into its library folder
                    moved = _move(f, library.SOUNDS_DIR / f.parent.relative_to(folder()))
                    d["file"] = str(moved)
                img = _in_bin(d.get("image", ""))
                if img is not None and img.parent == folder():
                    d["image"] = str(_move(img, library.THUMBS_DIR)) if img.exists() else ""
            except OSError:
                log.warning("couldn't bring %s back", item.name, exc_info=True)
                if moved is not None:   # the audio came back but the picture didn't
                    try:
                        shutil.move(str(moved), f)
                    except OSError:   # then the entry follows the audio where it is now
                        item.data["file"] = str(moved)
                        _save(all_)
                return None
            item.data = d
        all_.remove(item)
        _save(all_)
        return item


def adopt(src: Path) -> bool:
    """Put a bin that was set aside (a restore point's copy of this folder) back into
    the bin, next to what's been deleted since. True once all of it is in (`src` can
    go); False if some of it is still only in `src` (its list couldn't be read, the
    bin's is locked, a file couldn't be moved): then `src` must be kept. Adopting the
    same folder again only adds what isn't in the bin yet."""
    whole = True
    try:
        raw = json.loads((src / "deleted.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raw = {}
    except (OSError, ValueError):
        log.warning("couldn't read %s", src / "deleted.json", exc_info=True)
        raw, whole = {}, False
    with _lock:
        all_, ok = _read(tries=10)
        if not ok:
            log.warning("the bin's list is locked: %s stays where it is", src)
            return False
        have = {i.id for i in all_}
        for it in _items(raw):
            if it.id in have:
                continue
            try:
                for k in ("file", "image"):
                    name = it.data.get(k, "")
                    if name and not Path(name).is_absolute() and (src / name).exists():
                        to = folder() / Path(name).parent
                        it.data[k] = _move(src / name, to).relative_to(folder()).as_posix()
            except OSError:
                log.warning("couldn't bring %s back into the bin", it.name, exc_info=True)
                whole = False
                if k == "image":   # the audio is in: the entry follows it, minus its picture
                    it.data["image"] = ""
                else:
                    continue
            all_.append(it)
        all_.sort(key=lambda i: i.when)
        _save(_prune(all_))
    try:   # anything still in src (a file no entry names) mustn't be deleted with it
        left = [p for p in src.rglob("*") if p.is_file() and p.name != "deleted.json"]
    except OSError:
        return False
    return whole and not left


def meta_of(item: Item) -> SoundMeta | None:
    """A taken sound entry as a pad again (fields a newer version wrote are kept
    aside, and written back when the settings are saved: see library._with_raw)."""
    fields_ = SoundMeta.__dataclass_fields__
    known = {k: v for k, v in item.data.items() if k in fields_}
    try:
        m = SoundMeta(**known)
    except TypeError:
        return None
    m.tags = library.clean_tags(m.tags)
    extra = {k: v for k, v in item.data.items() if k not in fields_}
    if extra:
        m._raw_extra = extra
    if m.mode not in library.MODES:   # a newer version's mode: played as restart
        m._raw_kept = {"mode": ("restart", m.mode)}
        m.mode = "restart"
    return m


def forget(item_id: str) -> None:
    """Delete an entry for good."""
    with _lock:
        all_ = load()
        item = next((i for i in all_ if i.id == item_id), None)
        if item is not None:
            all_.remove(item)
            _destroy(item)
            _save(all_)


def empty(kind: str | None = None) -> None:
    with _lock:
        all_, ok = _read(tries=10)
        if not ok:   # saving [] would drop the entries that couldn't be read
            log.warning("the bin's list is locked: not emptying it")
            return
        keep = [i for i in all_ if kind is not None and i.kind != kind]
        for i in all_:
            if i not in keep:
                _destroy(i)
        _save(keep)


def prune() -> None:
    """Let go of what's been in the bin too long (run at startup)."""
    with _lock:
        all_ = load()
        kept = _prune(all_)
        if len(kept) != len(all_):
            _save(kept)


def _prune(all_: list[Item]) -> list[Item]:
    cutoff = time.time() - KEEP_DAYS * 86400
    kept = [i for i in all_ if i.when >= cutoff][-MAX_ITEMS:]
    for i in all_:
        if i not in kept:
            _destroy(i)
    return kept


def _destroy(item: Item) -> None:
    if item.kind != SOUND:
        return
    f = _in_bin(item.data.get("file", ""))
    img = _in_bin(item.data.get("image", ""))
    try:
        if f is not None and _ours(f) and f.exists() \
                and not (library.USE_RECYCLE_BIN and library.recycle(f)):
            f.unlink(missing_ok=True)
        if img is not None and img.parent == folder():
            img.unlink(missing_ok=True)
    except OSError:
        log.warning("couldn't delete %s", f, exc_info=True)


def ago(when: float, now: float | None = None) -> str:
    """"just now", "5 min ago", "3 hours ago", "2 days ago"."""
    s = max(0, (now or time.time()) - when)
    if s < 60:
        return _("just now")
    if s < 3600:
        return _("{n} min ago", n=int(s // 60))
    if s < 86400:
        return ngettext("{n} hour ago", "{n} hours ago", int(s // 3600))
    return ngettext("{n} day ago", "{n} days ago", int(s // 86400))
