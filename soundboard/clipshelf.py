"""The Apps tab's saved clips: what the clip editor's Save keeps, as a list under
the cards (soundboard.ui.clipshelf) to play, rename, send, or add to your Sounds.

Each clip is a FLAC in CLIPS_DIR with a row in its index.json (id, name, file,
where it came from, its length, creation and last-use times). Deleting one takes
it out of the index (Undo puts it back); automatic cleanup frees its file after
Undo expires, and other unreferenced files go the next time the list is read.
Audio is (n, 2) float32 at engine.SR, as everywhere."""
from __future__ import annotations

import json
import logging
import math
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import ClassVar

import numpy as np
import soundfile as sf

from soundboard import library
from soundboard.engine import SR

log = logging.getLogger(__name__)

KEEP_DAYS = 7
DAY = 24 * 60 * 60


def clips_dir(folder: str = "clips") -> Path:
    return library.APP_DIR / folder


@dataclass
class Clip:
    id: str
    name: str
    file: str            # the FLAC's name inside its folder
    src: str = ""        # the program it was cut from
    seconds: float = 0.0
    made: float = 0.0    # time.time()
    last_used: float = 0.0
    folder: ClassVar[str] = "clips"   # where its kind lives (not saved in the index)

    @property
    def path(self) -> Path:
        return clips_dir(self.folder) / self.file

    def audio(self) -> np.ndarray:
        data, sr = sf.read(str(self.path), dtype="float32", always_2d=True)
        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        if sr != SR:   # only if someone dropped their own file in: resample roughly
            n = int(len(data) * SR / sr)
            x = np.linspace(0, len(data) - 1, n)
            data = np.stack([np.interp(x, np.arange(len(data)), data[:, c]) for c in (0, 1)],
                            1).astype(np.float32)
        return np.ascontiguousarray(data[:, :2])


class VoiceClip(Clip):
    """The Voice tab's recordings: the same list, a folder of their own."""
    folder: ClassVar[str] = "voice-clips"


class Shelf:
    """The saved clips, newest first. `kind`: Clip (the Apps tab's) or VoiceClip."""

    def __init__(self, kind: type[Clip] = Clip):
        self.kind = kind
        self.clips: list[Clip] = []
        self._lock = threading.RLock()
        self._dirty = False
        self.pruned = False   # prune_missing dropped some since the UI last looked
        self.load()

    def _index(self) -> Path:
        return clips_dir(self.kind.folder) / "index.json"

    def load(self):
        self.clips = []
        try:
            rows = json.loads(self._index().read_text("utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as e:
            log.warning("saved clips list unreadable: %s", e)
            return
        known = {f.name for f in Clip.__dataclass_fields__.values()}
        for r in rows if isinstance(rows, list) else []:
            if isinstance(r, dict) and r.get("id") and r.get("file"):
                c = self.kind(**{k: v for k, v in r.items() if k in known})
                if c.path.is_file():
                    # Earlier versions did not track activity. Give their clips a
                    # full retention period rather than guessing when they were used.
                    now = time.time()
                    for attr in ("made", "last_used"):
                        value = getattr(c, attr)
                        if (not isinstance(value, (int, float))
                                or not math.isfinite(value) or value <= 0):
                            setattr(c, attr, now)
                            self._dirty = True
                    self.clips.append(c)
        self._tidy()

    def _tidy(self):
        """Files no clip points at (deleted ones, from an earlier run) go."""
        keep = {c.file for c in self.clips}
        try:
            for f in clips_dir(self.kind.folder).glob("*.flac"):
                if f.name not in keep:
                    f.unlink(missing_ok=True)
        except OSError:
            pass

    def save(self):
        with self._lock:
            d = clips_dir(self.kind.folder)
            d.mkdir(parents=True, exist_ok=True)
            tmp = d / "index.json.tmp"
            tmp.write_text(json.dumps([asdict(c) for c in self.clips], indent=1), "utf-8")
            tmp.replace(self._index())
            self._dirty = False

    def add(self, data: np.ndarray, name: str, src: str = "") -> Clip:
        d = clips_dir(self.kind.folder)
        d.mkdir(parents=True, exist_ok=True)
        cid = uuid.uuid4().hex[:10]
        now = time.time()
        c = self.kind(id=cid, name=name.strip()[:60] or "Clip", file=f"{cid}.flac", src=src,
                 seconds=len(data) / SR, made=now, last_used=now)
        sf.write(str(c.path), np.asarray(data, np.float32), SR, subtype="PCM_16")
        with self._lock:
            self.clips.insert(0, c)
            self.save()
        return c

    def get(self, cid: str) -> Clip | None:
        with self._lock:
            return next((c for c in self.clips if c.id == cid), None)

    def snapshot(self) -> list[Clip]:
        with self._lock:
            return list(self.clips)

    def touch(self, cid: str):
        """Activity stays in memory; periodic maintenance writes it off the UI thread."""
        with self._lock:
            c = self.get(cid)
            if c is not None:
                c.last_used = time.time()
                self._dirty = True

    def maintain(self, keep_forever: bool = False, active: str | None = None,
                 now: float | None = None) -> list[tuple[int, Clip]]:
        """Expire inactive clips and flush activity. Called on a worker by the UI.

        Files remain until cleanup Undo expires, so they can be brought back.
        A currently playing clip is never interrupted.
        """
        now = time.time() if now is None else now
        with self._lock:
            self.prune_missing()
            gone = [(i, c) for i, c in enumerate(self.clips)
                    if not keep_forever and c.id != active and now - c.last_used >= KEEP_DAYS * DAY]
            if gone:
                ids = {c.id for _i, c in gone}
                before = self.clips
                self.clips = [c for c in self.clips if c.id not in ids]
                try:
                    self.save()
                except OSError:
                    self.clips = before
                    raise
            elif self._dirty:
                self.save()
            return gone

    def prune_missing(self) -> bool:
        """Clips whose file was deleted outside the app leave the list (no Undo:
        there's nothing to bring back). True if any did."""
        with self._lock:
            kept = [c for c in self.clips if c.path.is_file()]
            if len(kept) == len(self.clips):
                return False
            self.clips = kept
            self._dirty = True
            self.pruned = True
            return True

    def rename(self, cid: str, name: str) -> bool:
        with self._lock:
            c, name = self.get(cid), name.strip()[:60]
            if c is None or not name or name == c.name:
                return False
            c.name = name
            self.touch(cid)
            self.save()
            return True

    def remove(self, cid: str) -> tuple[int, Clip] | None:
        """Off the list (its file stays until the next start, for Undo)."""
        gone = self.remove_many({cid})
        return gone[0] if gone else None

    def remove_many(self, ids: set[str]) -> list[tuple[int, Clip]]:
        with self._lock:
            gone = [(i, c) for i, c in enumerate(self.clips) if c.id in ids]
            if not gone:
                return []
            self.clips = [c for c in self.clips if c.id not in ids]
            self.save()
            return gone

    def restore(self, at: int, c: Clip):
        self.restore_many([(at, c)])

    def restore_many(self, gone: list[tuple[int, Clip]]):
        with self._lock:
            ids = {c.id for c in self.clips}
            for at, c in sorted(gone, key=lambda pair: pair[0]):
                if c.id not in ids and c.path.is_file():
                    self.clips.insert(min(at, len(self.clips)), c)
                    c.last_used = time.time()
                    ids.add(c.id)
            self.save()

    def discard_files(self, gone: list[tuple[int, Clip]]):
        """After the cleanup Undo expires, free files that are still unreferenced."""
        with self._lock:
            keep = {c.file for c in self.clips}
            for _at, c in gone:
                if c.file not in keep:
                    try:
                        c.path.unlink(missing_ok=True)
                    except OSError:
                        log.warning("could not remove expired clip file")
