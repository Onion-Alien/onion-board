"""Writing config.json: atomically, with rotated backups and the privacy.json side
copy, on a background thread (`Saver`) so a slow disk never freezes the window."""
from __future__ import annotations

import collections
import json
import logging
import os
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from soundboard.sounds import paths

if TYPE_CHECKING:
    from soundboard.sounds.config import Config

log = logging.getLogger("soundboard.sounds.library")


CONFIG_BACKUPS = 3   # config.json.1 … .3, rotated on a save that changes something...
ROTATE_EVERY_S = 3600   # ...at most once an hour (the first change of a session always)


_write_lock = threading.Lock()   # one writer at a time: Saver's thread or a direct save()
_written_seq = 0    # the newest snapshot written (config.Config.snapshot numbers them)


def _write_privacy(text: str):
    path = _privacy_path()
    try:
        if path.read_text(encoding="utf-8") == text:
            return
    except OSError:
        pass
    try:
        atomic_write_text(path, text)
    except OSError:
        log.warning("couldn't save %s", path, exc_info=True)


def _durable_tmp(path: Path, text: str) -> Path:
    """`text` in a new temp file next to `path`, flushed to the disk (fsync) before it
    returns: renamed over `path` without that, a power cut could leave `path` empty or
    full of NULs. The temp file is removed if writing it fails."""
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return tmp


def atomic_write_text(path: Path, text: str):
    """Replace `path` with `text` so a crash or power cut leaves the old file or the new
    one, never a broken one. Raises OSError."""
    tmp = _durable_tmp(Path(path), text)
    try:
        _replace(tmp, Path(path))
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _replace(tmp: Path, path: Path, tries: int = 6):
    """tmp.replace(path), tried again for a moment while something (an antivirus scan,
    the search indexer, a backup tool) has `path` open: one such lock made a whole
    save fail and showed "Couldn't save your settings" though the next save was fine."""
    for i in range(tries):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.05 * (i + 1))


def _write(snap: tuple[int, dict, str]) -> bool:
    """Write a Config.snapshot() to config.json (+ privacy.json), unless a newer one
    is already there."""
    global _written_seq
    seq, raw, privacy = snap
    with _write_lock:
        if seq < _written_seq:
            return True   # a newer snapshot got there first
        try:
            paths.APP_DIR.mkdir(parents=True, exist_ok=True)
            text = json.dumps(raw, indent=2)
            _write_privacy(privacy)
            damaged = False
            try:
                old = paths.CONFIG_PATH.read_text(encoding="utf-8-sig")
                if old == text:
                    _written_seq = seq
                    return True   # nothing changed: don't churn the backups
                # a damaged file that couldn't be set aside isn't a backup: rotating it
                # in would push out a good one
                damaged = not isinstance(json.loads(old), dict)
            except ValueError:   # includes UnicodeDecodeError
                damaged = True
            except OSError:
                pass
            tmp = _durable_tmp(paths.CONFIG_PATH, text)
            try:
                if paths.CONFIG_PATH.exists() and not damaged and _rotate_due():
                    try:
                        _rotate_backups()
                        _rotated[paths.CONFIG_PATH] = time.monotonic()
                    except OSError:   # a backup locked for a moment mustn't block the save
                        log.warning("couldn't rotate the config backups", exc_info=True)
                _replace(tmp, paths.CONFIG_PATH)
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise
            _written_seq = seq
            return True
        except OSError:
            log.exception("couldn't save settings to %s", paths.CONFIG_PATH)
            return False


class Saver:
    """Saves a Config on a background thread, so a slow disk (an antivirus scan of
    the new file took 2-7 s) doesn't freeze the window. save() copies the settings
    right away; the newest copy is the one written, and `done(ok)` is called on the
    saver's thread after each write. save(then) keeps `then` until a write covers that
    copy; finished() hands it back with how that write went."""

    def __init__(self, cfg: Config, done=None):
        self.cfg = cfg
        self._done = done
        self._cond = threading.Condition()
        self._pending: tuple | None = None
        self._pending_n = 0                  # the save() that copy is from
        self._count = 0                      # save() calls so far
        self._then: list[tuple[int, Callable[[bool], None]]] = []
        self._written: collections.deque[tuple[int, bool]] = collections.deque(maxlen=64)
        self._busy = False
        self._thread: threading.Thread | None = None

    def save(self, then: Callable[[bool], None] | None = None):
        with self._cond:
            self._count += 1
            n = self._count
            if then is not None:
                self._then.append((n, then))
        if self.cfg.read_only:   # logs it; nothing to write
            ok = self.cfg.save()
            with self._cond:
                self._written.append((n, ok))
            if self._done:
                self._done(ok)
            return
        snap = self.cfg.snapshot()
        with self._cond:
            self._pending, self._pending_n = snap, n
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="config-save",
                                                daemon=True)
                self._thread.start()
            self._cond.notify_all()

    def _run(self):
        while True:
            with self._cond:
                while self._pending is None:
                    # idle for good, never ended: starting a thread waits for it to
                    # run, and a new one per save (after 30 s idle) held the window on
                    # a PC short of memory (freeze reports at save()'s start())
                    self._cond.wait()
                snap, n, self._pending, self._busy = self._pending, self._pending_n, None, True
            try:
                ok = _write(snap)
            except Exception:  # noqa: BLE001 - a save must never kill the saver
                log.exception("saving settings failed")
                ok = False
            with self._cond:
                self._busy = False
                self._written.append((n, ok))   # every save() up to n is in this one
                self._cond.notify_all()
            if self._done:
                try:
                    self._done(ok)
                except Exception:  # noqa: BLE001
                    log.exception("after saving settings")

    def finished(self) -> list[tuple[Callable[[bool], None], bool]]:
        """The save(then)s whose copy (or a newer one) has been written since, each with
        how that write went (ok). Call it from the thread `then` belongs to."""
        with self._cond:
            out, keep = [], []
            for n, then in self._then:
                ok = next((w_ok for w_n, w_ok in self._written if w_n >= n), None)
                if ok is None:
                    keep.append((n, then))
                else:
                    out.append((then, ok))
            self._then = keep
            return out

    def flush(self, timeout: float = 10.0) -> bool:
        """Wait until everything handed to save() is written. True when it is."""
        end = time.monotonic() + timeout
        with self._cond:
            while self._pending is not None or self._busy:
                left = end - time.monotonic()
                if left <= 0:
                    return False
                self._cond.wait(left)
        return True


def _privacy_path() -> Path:
    return paths.CONFIG_PATH.with_name("privacy.json")


_rotated: dict[Path, float] = {}   # config path -> when its backups last rotated


def _rotate_due() -> bool:
    """Rotate the backups now? A volume slider dragged about saves many times a
    minute: rotating on each one copied the file every time and soon pushed out
    every copy older than a few seconds. Once an hour keeps .1 the settings as
    they were when this session (or hour) began."""
    last = _rotated.get(paths.CONFIG_PATH)
    return last is None or time.monotonic() - last >= ROTATE_EVERY_S


def _rotate_backups():
    """config.json -> .1, .1 -> .2, … (the oldest falls off)."""
    for i in range(CONFIG_BACKUPS, 0, -1):
        src = paths.CONFIG_PATH if i == 1 else paths.CONFIG_PATH.with_name(f"config.json.{i - 1}")
        dst = paths.CONFIG_PATH.with_name(f"config.json.{i}")
        if src.exists():
            if i == 1:
                shutil.copy2(src, dst)   # keep config.json in place for the atomic replace
            else:
                src.replace(dst)
