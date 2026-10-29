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
import sys
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
    if _previous[0] and still_running(_previous[1]):
        # another copy is starting right now (the installer's Finish page opened it and
        # the desktop icon was double-clicked too): not a start that died. Taken as one,
        # it was counted whenever this copy won the single-instance check and the other
        # quit as the second launch.
        _previous = ("", 0)
    _previous_at = written(path) if _previous[0] else 0.0
    mark(version, path)


def still_running(pid: int) -> bool:
    """`pid` is another process running this same exe (not this one, never off
    Windows): a copy of the app that's still starting, not one that died."""
    if not pid or pid == os.getpid() or os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes as wt
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wt.HANDLE
    k32.OpenProcess.argtypes = (wt.DWORD, wt.BOOL, wt.DWORD)
    k32.GetExitCodeProcess.argtypes = (wt.HANDLE, ctypes.POINTER(wt.DWORD))
    k32.QueryFullProcessImageNameW.argtypes = (wt.HANDLE, wt.DWORD, wt.LPWSTR,
                                               ctypes.POINTER(wt.DWORD))
    k32.CloseHandle.argtypes = (wt.HANDLE,)
    h = k32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False   # gone (or not ours to look at: then it isn't this app either)
    try:
        code = wt.DWORD()
        if not k32.GetExitCodeProcess(h, ctypes.byref(code)) or code.value != 259:
            return False   # STILL_ACTIVE: anything else, it has ended
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(len(buf))
        if not k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return False
        # the same program: a reused pid now belongs to something else
        return os.path.normcase(buf.value) == os.path.normcase(sys.executable)
    finally:
        k32.CloseHandle(h)


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
    """Remove this run's breadcrumb: the app reached its running state, ended on
    purpose, or (applog.py) a saved crash report is the trace of a start that died
    instead. One another copy left since (it started while this one loaded) stays:
    a second launch that quits must not take away the start that goes on."""
    try:
        path = Path(directory) if directory is not None else app_dir()
        if read(path)[1] in (0, os.getpid()):
            (path / NAME).unlink(missing_ok=True)
    except OSError:
        pass


STALL_NAME = "startup-stall.txt"
STALL_S = 10.0   # a start slower than this writes down where it is, every STALL_S
STALL_FRAMES = 40   # innermost frames kept per thread
_stall: tuple | None = None   # (stop event, its thread, the file's path, when watching started)


def watch_stall(directory: Path | None = None, seconds: float = STALL_S) -> None:
    """From the loading screen until the window is up (stop_stall): every `seconds`,
    what each thread is doing goes into startup-stall.txt, so a start that takes a
    minute says where it waited. Only code locations; it stays on this PC.

    Not faulthandler.dump_traceback_later: its watchdog walks the other threads' frames
    without Python's lock while they keep running, and one freed under it (the splash
    and the UI thread both busy, on a slow start) crashed the app in faulthandler's
    dump_frame. sys._current_frames() takes the lock, so the frames hold still."""
    global _stall
    import threading
    import time
    try:
        path = (Path(directory) if directory is not None else app_dir()) / STALL_NAME
        path.unlink(missing_ok=True)   # written only once a start is slow
    except OSError:
        _stall = None
        return
    stop = threading.Event()
    thread = threading.Thread(target=_stall_loop, args=(stop, path, seconds),
                              name="startup-stall", daemon=True)
    _stall = (stop, thread, path, time.monotonic())
    thread.start()


def _stall_loop(stop, path: Path, seconds: float) -> None:
    while not stop.wait(seconds):
        try:
            text = _stacks()
            with open(path, "a", encoding="utf-8") as f:
                f.write(text)
        except Exception:   # noqa: BLE001 - a note about a slow start must never hurt it
            return


def _stacks() -> str:
    """Every other thread's stack, innermost frame last, as faulthandler's dump named them."""
    import sys
    import threading
    import traceback
    names = {t.ident: t.name for t in threading.enumerate()}
    me = threading.get_ident()
    out = []
    for ident, frame in sys._current_frames().items():
        if ident == me:
            continue
        out.append(f"Thread {ident:#x} ({names.get(ident, '?')}):\n")
        out.extend(traceback.format_stack(frame, limit=STALL_FRAMES))
        out.append("\n")
    return "".join(out)


def stop_stall() -> tuple[float, Path | None]:
    """Stop watching: (seconds since watch_stall, startup-stall.txt if the start was
    slow enough to write in it, else None)."""
    global _stall
    import time
    if _stall is None:
        return 0.0, None
    stop, thread, path, t0 = _stall
    _stall = None
    stop.set()
    thread.join(timeout=2.0)   # a dump half-written: let it finish
    took = time.monotonic() - t0
    try:
        if path.stat().st_size:
            return took, path
    except OSError:
        pass
    return took, None
