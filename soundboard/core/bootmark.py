"""A breadcrumb left while the app starts, so a start that never made it is counted.

Written at the very top of main.py, before the heavy imports (Qt, the sound library),
and removed once the app is up (app.py, right after `running.txt` is written). If it's
still there at the next start, the last run died during start-up: a crash while a
module or Qt loaded. No other check can see that window -- `running.txt` is only
written seconds later, and applog's hooks aren't in yet -- so usage.py counts it as
`startup-failed/<version>` on that next start (with the native stacks faulthandler
caught, or Windows' own error for that process, when either is there).

Only ever the version and this run's process id: nothing about the user or the PC.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from soundboard.core import profile
from soundboard.win import winpath

NAME = "starting.txt"

# the installer's mark and the one-off commands: soundboard/core/installmark.py (main.py
# reads them before anything else of the app is imported)
from soundboard.core.installmark import (  # noqa: E402,F401
    INSTALLING, INSTALLING_STALE_S, ONE_OFF, installing)

_VERSION_RE = re.compile(r"[0-9][0-9A-Za-z.\-]{0,20}")


def app_dir() -> Path:
    """%APPDATA%\\OnionBoard, the same folder as `library.APP_DIR` (spelled out
    through a folder link Windows won't follow). Kept here, small: main.py writes the
    breadcrumb before the sound library is imported."""
    return winpath.usable_dir(profile.base())


_previous: tuple[str, int] = ("", 0)
_previous_at = 0.0


def start(version: str, directory: Path | None = None) -> None:
    """Read the last run's breadcrumb, then leave this run's: call once, at the top of
    main.py, for a normal launch (not the one-off helper commands). `previous()` then
    says what the last run left behind, and `previous_at()` when."""
    global _previous, _previous_at
    path = Path(directory) if directory is not None else app_dir()
    _previous = read(path)
    _previous_at = written(path) if _previous[0] else 0.0
    mark(version, path)


def previous() -> tuple[str, int]:
    """(version, pid) the last run left, or ("", 0) after a run that got past start-up
    (or on the very first launch)."""
    return _previous


def previous_at() -> float:
    """When the last run left its breadcrumb (time.time() scale), or 0 with none."""
    return _previous_at


def written(directory: Path) -> float:
    """When `directory`'s breadcrumb was written, or 0."""
    try:
        return (Path(directory) / NAME).stat().st_mtime
    except OSError:
        return 0.0


def mark(version: str, directory: Path | None = None) -> Path | None:
    """Leave this run's breadcrumb (best effort: it never stops or slows a start)."""
    try:
        path = Path(directory) if directory is not None else app_dir()
        path.mkdir(parents=True, exist_ok=True)
        file = path / NAME
        file.write_text(json.dumps({"version": version, "pid": os.getpid()}),
                        encoding="utf-8")
        return file
    except OSError:
        return None


def read(directory: Path) -> tuple[str, int]:
    """(version, pid) in `directory`'s breadcrumb, or ("", 0) when there is none (or
    it's unreadable: a half-written file from a crash mid-write, say)."""
    try:
        data = json.loads((Path(directory) / NAME).read_text(encoding="utf-8"))
        version = data.get("version")
        if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
            return ("", 0)
        return version, int(data.get("pid") or 0)
    except (OSError, ValueError, AttributeError, TypeError):
        return ("", 0)


def clear(directory: Path | None = None) -> None:
    """Remove the breadcrumb: the app reached its running state, ended on purpose, or
    (applog.py) a saved crash report is the trace of a start that died instead."""
    try:
        path = Path(directory) if directory is not None else app_dir()
        (path / NAME).unlink(missing_ok=True)
    except OSError:
        pass


STALL_NAME = "startup-stall.txt"
STALL_S = 10.0   # a start slower than this writes down where it is, every STALL_S
_stall: tuple | None = None   # (open file, its path, when watching started)


def watch_stall(directory: Path | None = None, seconds: float = STALL_S) -> None:
    """From the loading screen until the window is up (stop_stall): every `seconds`,
    what each thread is doing goes into startup-stall.txt, so a start that takes a
    minute says where it waited. faulthandler writes from a thread of its own, so this
    works however stuck the UI thread is. Only code locations; it stays on this PC."""
    global _stall
    import faulthandler
    import time
    try:
        path = (Path(directory) if directory is not None else app_dir()) / STALL_NAME
        f = open(path, "w", encoding="utf-8")   # noqa: SIM115 - open until stop_stall
        faulthandler.dump_traceback_later(seconds, repeat=True, file=f)
        _stall = (f, path, time.monotonic())
    except (OSError, RuntimeError, ValueError):
        _stall = None


def stop_stall() -> tuple[float, Path | None]:
    """Stop watching: (seconds since watch_stall, startup-stall.txt if the start was
    slow enough to write in it, else None and the empty file is removed)."""
    global _stall
    import faulthandler
    import time
    if _stall is None:
        return 0.0, None
    f, path, t0 = _stall
    _stall = None
    faulthandler.cancel_dump_traceback_later()
    took = time.monotonic() - t0
    try:
        f.close()
        if path.stat().st_size:
            return took, path
        path.unlink(missing_ok=True)
    except OSError:
        pass
    return took, None
