"""Your own voices for the voice changer: mixes saved under a name (Fine-tune ->
"Save as a voice"), and the ones deleted lately so they can be brought back.

They live in %APPDATA%\\OnionBoard\\voices.json, not in config.json: an older version
rewrites the voice changer's settings without the fields it doesn't know, and this is
a file it never opens, so going back a version loses none of them.

    {"version": 1,
     "voices": [{"name": "Squeaky robot", "effects": {type: {"on": bool, ...}}}],
     "deleted": [{"id": "...", "name": "...", "when": time.time(), "effects": {...}}]}

The folder is looked up on every call (library.APP_DIR), so tests that point the
library somewhere else get their own file.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path

from soundboard import library, trash, voicefx

log = logging.getLogger(__name__)

FILE_NAME = "voices.json"
VERSION = 1
MAX_NAME = 32
MAX_VOICES = 100
KEEP_DAYS = trash.KEEP_DAYS
VOICE = "voice"     # the bin's kind (ui.deleted.DeletedDialog lists one kind)


def path() -> Path:
    return library.APP_DIR / FILE_NAME


def clean_name(name) -> str:
    """One line, no runs of spaces, at most MAX_NAME characters ("" if nothing's left)."""
    return " ".join(str(name or "").split())[:MAX_NAME].strip()


def clean_effects(raw) -> dict:
    return voicefx.clean_spec({"effects": raw})["effects"]


def clean_list(raw) -> list[tuple[str, dict]]:
    """[{"name", "effects"}, ...] from a file or a backup, as (name, effects) pairs:
    damaged entries are dropped, and a name used twice keeps its first."""
    out, seen = [], set()
    for d in raw if isinstance(raw, list) else ():
        if not isinstance(d, dict):
            continue
        name = clean_name(d.get("name"))
        if name and name.casefold() not in seen and isinstance(d.get("effects"), dict):
            seen.add(name.casefold())
            out.append((name, clean_effects(d["effects"])))
    return out[:MAX_VOICES]


def saved() -> list[dict]:
    """The saved voices as written, read without changing anything (for a backup)."""
    try:
        raw = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    voices = raw.get("voices") if isinstance(raw, dict) else None
    return [{"name": n, "effects": e} for n, e in clean_list(voices)]


class Store:
    """The saved voices (name -> effects, in the order they were saved) and the bin.
    Every change is written straight away. If the file couldn't be read (locked by an
    antivirus or OneDrive) nothing is written over it this run."""

    KEEP_DAYS = KEEP_DAYS   # for ui.deleted.DeletedDialog, like trash's

    def __init__(self):
        self.voices: dict[str, dict] = {}
        self.deleted: list[trash.Item] = []
        self.writable = True
        self.reload()

    # ------------------------------------------------------------ the file
    def reload(self):
        self.voices, self.deleted, self.writable = {}, [], True
        try:
            raw = json.loads(path().read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except ValueError:
            log.warning("couldn't read %s; setting it aside", path(), exc_info=True)
            try:
                path().replace(path().with_name(
                    f"{FILE_NAME}.broken-{time.strftime('%Y%m%d-%H%M%S')}"))
            except OSError:
                self.writable = False
            return
        except OSError:
            log.warning("couldn't read %s", path(), exc_info=True)
            self.writable = False
            return
        raw = raw if isinstance(raw, dict) else {}
        self.voices = dict(clean_list(raw.get("voices")))
        for d in raw.get("deleted", []) if isinstance(raw.get("deleted"), list) else ():
            try:
                name = clean_name(d["name"]) or "Voice"
                self.deleted.append(trash.Item(str(d["id"]), VOICE, name,
                                               float(d.get("when", 0)),
                                               {"effects": clean_effects(d.get("effects"))}))
            except (KeyError, TypeError, ValueError):
                continue
        self._prune()

    def save(self) -> bool:
        if not self.writable:
            log.warning("not saving %s: it couldn't be read at startup", path())
            return False
        self._prune()
        data = {"version": VERSION,
                "voices": self.export(),
                "deleted": [{"id": i.id, "name": i.name, "when": i.when,
                             "effects": i.data.get("effects", {})} for i in self.deleted]}
        try:
            path().parent.mkdir(parents=True, exist_ok=True)
            tmp = path().with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
            tmp.replace(path())
            return True
        except OSError:
            log.exception("couldn't save %s", path())
            return False

    def export(self) -> list[dict]:
        """The voices as they're written (and exported with a backup's settings)."""
        return [{"name": n, "effects": e} for n, e in self.voices.items()]

    def _prune(self):
        cutoff = time.time() - KEEP_DAYS * 86400
        self.deleted = [i for i in self.deleted if i.when >= cutoff][-trash.MAX_ITEMS:]

    # ------------------------------------------------------------ voices
    def find(self, name: str) -> str | None:
        """The saved voice called `name`, whatever its capitals (None if there's none)."""
        key = clean_name(name).casefold()
        return next((n for n in self.voices if n.casefold() == key), None)

    def free_name(self, name: str) -> str:
        """`name`, or "name (2)", "name (3)"... if that's taken."""
        name = clean_name(name) or "My voice"
        if self.find(name) is None:
            return name
        n = 2
        while self.find(f"{name[:MAX_NAME - 5]} ({n})") is not None:
            n += 1
        return f"{name[:MAX_NAME - 5]} ({n})"

    def full(self) -> bool:
        return len(self.voices) >= MAX_VOICES

    def put(self, name: str, effects: dict) -> str:
        """Save (or replace, keeping its place) a voice. Returns the name it got."""
        name = self.find(name) or clean_name(name)
        self.voices[name] = clean_effects(effects)
        self.save()
        return name

    def rename(self, old: str, new: str) -> str:
        """Rename keeping its place. Returns the new name ("" if `old` is gone)."""
        new = clean_name(new)
        if old not in self.voices or not new:
            return ""
        self.voices = {(new if n == old else n): e for n, e in self.voices.items()}
        self.save()
        return new

    def remove(self, name: str) -> trash.Item | None:
        """Into the bin. Returns its bin entry, for Undo."""
        if name not in self.voices:
            return None
        index = list(self.voices).index(name)
        item = trash.Item(uuid.uuid4().hex[:12], VOICE, name, time.time(),
                          {"effects": self.voices.pop(name)}, index)
        self.deleted.append(item)
        self.save()
        return item

    def restore(self, item: trash.Item, index: int | None = None) -> str:
        """Put a taken-out bin entry back (as "name (2)" if the name's been reused).
        Returns the name it came back as."""
        name = self.free_name(item.name)
        pairs = list(self.voices.items())
        at = len(pairs) if index is None else min(max(index, 0), len(pairs))
        pairs.insert(at, (name, clean_effects(item.data.get("effects"))))
        self.voices = dict(pairs)
        self.save()
        return name

    def merge(self, raw) -> int:
        """Add the voices from a backup that aren't here by name. Returns how many."""
        added = 0
        for name, effects in clean_list(raw):
            if self.find(name) is None and not self.full():
                self.voices[name] = effects
                added += 1
        if added:
            self.save()
        return added

    # ------------------------------------------------------------ the bin
    # (shaped like soundboard.trash, for ui.deleted.DeletedDialog)
    def items(self, kind: str | None = None) -> list[trash.Item]:
        return [i for i in reversed(self.deleted) if kind in (None, VOICE)]

    def take(self, item_id: str) -> trash.Item | None:
        item = next((i for i in self.deleted if i.id == item_id), None)
        if item is not None:
            self.deleted.remove(item)
            self.save()
        return item

    def forget(self, item_id: str) -> None:
        self.take(item_id)
