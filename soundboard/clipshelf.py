"""The Apps tab's saved clips: what the clip editor's Save keeps, as a list under
the cards (soundboard.ui.clipshelf) to play, rename, send, or add to your Sounds.

Each clip is a FLAC in CLIPS_DIR with a row in its index.json (id, name, file,
where it came from, its length). Deleting one only takes it out of the index (the
Undo bar puts it back); files no row points at are tidied up the next time the
list is read. Audio is (n, 2) float32 at engine.SR, as everywhere."""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from soundboard import library
from soundboard.engine import SR

log = logging.getLogger(__name__)

MAX_CLIPS = 200          # the oldest go past this


def clips_dir() -> Path:
    return library.APP_DIR / "clips"


@dataclass
class Clip:
    id: str
    name: str
    file: str            # the FLAC's name inside clips_dir()
    src: str = ""        # the program it was cut from
    seconds: float = 0.0
    made: float = 0.0    # time.time()

    @property
    def path(self) -> Path:
        return clips_dir() / self.file

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


class Shelf:
    """The saved clips, newest first."""

    def __init__(self):
        self.clips: list[Clip] = []
        self.load()

    def _index(self) -> Path:
        return clips_dir() / "index.json"

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
                c = Clip(**{k: v for k, v in r.items() if k in known})
                if c.path.is_file():
                    self.clips.append(c)
        self._tidy()

    def _tidy(self):
        """Files no clip points at (deleted ones, from an earlier run) go."""
        keep = {c.file for c in self.clips}
        try:
            for f in clips_dir().glob("*.flac"):
                if f.name not in keep:
                    f.unlink(missing_ok=True)
        except OSError:
            pass

    def save(self):
        d = clips_dir()
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "index.json.tmp"
        tmp.write_text(json.dumps([asdict(c) for c in self.clips], indent=1), "utf-8")
        tmp.replace(self._index())

    def add(self, data: np.ndarray, name: str, src: str = "") -> Clip:
        d = clips_dir()
        d.mkdir(parents=True, exist_ok=True)
        cid = uuid.uuid4().hex[:10]
        c = Clip(id=cid, name=name.strip()[:60] or "Clip", file=f"{cid}.flac", src=src,
                 seconds=len(data) / SR, made=time.time())
        sf.write(str(c.path), np.asarray(data, np.float32), SR, subtype="PCM_16")
        self.clips.insert(0, c)
        for old in self.clips[MAX_CLIPS:]:
            old.path.unlink(missing_ok=True)
        del self.clips[MAX_CLIPS:]
        self.save()
        return c

    def get(self, cid: str) -> Clip | None:
        return next((c for c in self.clips if c.id == cid), None)

    def rename(self, cid: str, name: str) -> bool:
        c, name = self.get(cid), name.strip()[:60]
        if c is None or not name or name == c.name:
            return False
        c.name = name
        self.save()
        return True

    def remove(self, cid: str) -> tuple[int, Clip] | None:
        """Off the list (its file stays until the next start, for Undo)."""
        c = self.get(cid)
        if c is None:
            return None
        i = self.clips.index(c)
        self.clips.pop(i)
        self.save()
        return i, c

    def restore(self, at: int, c: Clip):
        if self.get(c.id) is None and c.path.is_file():
            self.clips.insert(min(at, len(self.clips)), c)
            self.save()
