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

from soundboard import winpath

NAME = "starting.txt"

# the one-off commands app.main() runs and exits (app.ONE_OFF_COMMANDS, the same names):
# main.py leaves no breadcrumb for them, since one would look like a start that failed.
# Kept here, not in app.py, because main.py reads it before the heavy imports.
ONE_OFF = ("--selftest", "--get-tor", "--install-addon", "--set-offline", "--keep-netlog",
           "--usage-count", "--uninstall-count", "--selftest-addon")
_VERSION_RE = re.compile(r"[0-9][0-9A-Za-z.\-]{0,20}")


def app_dir() -> Path:
    """%APPDATA%\\OnionBoard, the same folder as `library.APP_DIR` (spelled out
    through a folder link Windows won't follow). Kept here, small: main.py writes the
    breadcrumb before the sound library is imported."""
    return winpath.usable_dir(Path(os.environ.get("APPDATA", Path.home())) / "OnionBoard")


_previous: tuple[str, int] = ("", 0)


def start(version: str, directory: Path | None = None) -> None:
    """Read the last run's breadcrumb, then leave this run's: call once, at the top of
    main.py, for a normal launch (not the one-off helper commands). `previous()` then
    says what the last run left behind."""
    global _previous
    path = Path(directory) if directory is not None else app_dir()
    _previous = read(path)
    mark(version, path)


def previous() -> tuple[str, int]:
    """(version, pid) the last run left, or ("", 0) after a run that got past start-up
    (or on the very first launch)."""
    return _previous


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
