"""Which programs are playing sound, found off the UI thread for the Apps tab (`_Lister`), and the
keys its cards are saved under: an exe's path without its version folders (`path_key`) and the
saved volume. `approw` re-exports them."""
from __future__ import annotations

import logging
import math
import re
import threading
import time

from PySide6.QtCore import QObject, Signal

from soundboard.audio import appaudio
from soundboard.win import exeicon

log = logging.getLogger("soundboard.ui.apps.approw")


# while hidden, a 5 s check only walks the process list (~4 ms, not the ~20 ms of a whole
# listing) and lists the programs when one of the tab's started or closed, one not yet
# picked up runs, or this long has gone by
HIDDEN_FULL_S = 30.0
MAX_VOL = 10.0          # 1000 %, the most the volume box takes


# a version folder in a program's path (Discord's app-1.0.9156, 24.1.3): it changes on
# every update, so it doesn't count when telling two programs of the same name apart
_VERSION_DIR = re.compile(r"(app-)?v?\d+(\.\d+)+([-_+][\w.]*)?", re.I)


def path_key(path: str) -> str:
    """How a program's .exe path is remembered: lower case, version folders as *."""
    parts = re.split(r"[\\/]+", path.lower())
    return "\\".join("*" if _VERSION_DIR.fullmatch(p) else p for p in parts)


def is_path_key(key: str) -> bool:
    """A row / remembered key that is a path (cfg.apps_paths), not an .exe name."""
    return "\\" in key


def saved_volume(v) -> float:
    """A remembered program's volume from the config, whatever was written there."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 1.0
    return min(max(v, 0.0), MAX_VOL) if math.isfinite(v) else 1.0


class _Lister(QObject):
    """Reads the audio sessions off the UI thread (COM, ~50 ms) and hands the result
    to it: `peaks`' next rescan makes the list while that watcher runs (it was finding
    the same sessions on its own), else one worker thread of the lister's own does
    (it started a new thread for every listing, 720 an hour in the tray)."""
    ready = Signal(object)

    def __init__(self, parent=None, peaks: appaudio.PeakWatcher | None = None):
        super().__init__(parent)
        self.peaks = peaks
        self._busy = False
        self._stopped = False
        # held while a result is handed over (worker thread); stop() takes it, so none
        # is mid-way once the tab is going and could be freed under it (a crash)
        self._hand_over = threading.Lock()
        self._job: tuple[frozenset, frozenset] | None = None
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        # the worker's own: what refresh(watch=...) saw last time, and when it last listed
        self._seen: frozenset | None = None
        self._listed_at = -math.inf

    def refresh(self, watch: frozenset[str] | None = None,
                waiting: frozenset[str] = frozenset()):
        """List the programs. With `watch` (.exe names, lower case: the tab is hidden),
        only walk the processes first, and list them only if one of those started or
        closed since the last walk, one in `waiting` (not picked up yet) runs, or
        HIDDEN_FULL_S has gone by since the last listing."""
        if self._busy or self._stopped:
            return
        self._busy = True
        if watch is None and self.peaks is not None and self.peaks.list_for(self._listed):
            return
        self._job = None if watch is None else (watch, waiting)
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, name="applist", daemon=True)
            self._thread.start()
        self._wake.set()

    def _run(self):
        while True:
            self._wake.wait()
            self._wake.clear()
            if self._stopped:
                return
            job = self._job
            try:
                due = job is None or self._due(*job)
            except Exception:  # noqa: BLE001
                log.debug("walking the processes failed", exc_info=True)
                due = True
            if due:
                self._work()
            else:
                self._busy = False

    def _due(self, watch: frozenset[str], waiting: frozenset[str]) -> bool:
        alive = appaudio.running()
        seen = frozenset((pid, exe) for pid, exe in alive.items() if exe in watch)
        changed, self._seen = seen != self._seen, seen
        return (changed or any(exe in waiting for _pid, exe in seen)
                or time.monotonic() - self._listed_at >= HIDDEN_FULL_S)

    def _work(self):
        alive: dict[int, str] = {}   # every process, from the listing's own process list
        apps = None
        try:
            apps = appaudio.list_apps(strict=True, alive=alive)
        except appaudio.ComError:
            log.debug("listing programs failed", exc_info=True)
        except Exception:  # noqa: BLE001
            log.exception("listing programs failed")
        self._listed(apps, alive)

    def _listed(self, apps: list | None, alive: dict[int, str] | None):
        """On the worker's or the level watcher's thread. apps None: the listing failed,
        and this round is skipped (an empty list would stop every capture and drop
        the rows)."""
        if apps:
            exeicon.load(app.path for app in apps)   # here, not on the UI thread
        self._listed_at = time.monotonic()
        self._busy = False
        with self._hand_over:
            if apps is not None and not self._stopped:
                self.ready.emit((apps, alive))

    def stop(self):
        with self._hand_over:
            self._stopped = True
        self._wake.set()   # the worker sees it and ends
