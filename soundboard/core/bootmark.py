"""A breadcrumb left while the app starts, so a start that never made it is counted.

Written at the very top of main.py, before the heavy imports (Qt, the sound library),
and removed once the app is up (app.py, right after `running.txt` is written). If it's
still there at the next start, the last run died during start-up: a crash while a
module or Qt loaded. No other check can see that window -- `running.txt` is only
written seconds later, and applog's hooks aren't in yet -- so usage.py counts it as
`startup-failed/<version>` on that next start (with the native stacks faulthandler
caught, or Windows' own error for that process, when either is there).

How far the start got goes in too (`stage()`: `boot`, `setup`, `qt`, `window`...), and
a Python error that ends the start before the crash reporter is in (`failed()`, from
main.py) as its type and our own file:line, so a start that died always says where.

Only ever the version, this run's process id, the stage and that error's type and our
own file:line: nothing about the user or the PC, never an error's message.
"""
from __future__ import annotations

import gc
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
_STAGE_RE = re.compile(r"[a-z][a-z-]{0,20}")
_ERROR_RE = re.compile(r"[A-Za-z_]\w{0,40}(?:@soundboard(?:/[a-z0-9_]+){1,5}\.py:[0-9]{1,6})?")
_STALL_FRAME_RE = re.compile(
    r'File "(?:[^"]*[\\/])?(soundboard(?:[\\/][a-z0-9_]+){1,5}\.py)", line (\d+)')
STAGE_PREFIX = "stage-"   # previous_why() for a start that died with no Python error
LOG_NAME = "onionboard.log"


def app_dir() -> Path:
    """%APPDATA%\\OnionBoard, the same folder as `library.APP_DIR` (spelled out
    through a folder link Windows won't follow). Kept here, small: main.py writes the
    breadcrumb before the sound library is imported."""
    return winpath.usable_dir(profile.base())


_previous: tuple[str, int] = ("", 0)
_previous_at = 0.0
_previous_why = ""
_previous_stall = ""


def start(version: str, directory: Path | None = None) -> None:
    """Read the last run's breadcrumb, then leave this run's: call once, at the top of
    main.py, for a normal launch (not the one-off helper commands). `previous()` then
    says what the last run left behind, and `previous_at()` when."""
    global _previous, _previous_at, _previous_why, _previous_stall
    # No automatic garbage collection from here on: uigc.UiCollector runs it on the UI
    # thread once the window is up, and until then a collection could run on whichever
    # thread allocated past the threshold (the stall watch below, a loader, the audio)
    # and free Qt objects caught in a cycle there (the loading screen's): an access
    # violation on 2.9.2, with the stall watch's thread the one that crashed.
    gc.disable()
    path = Path(directory) if directory is not None else app_dir()
    _previous = read(path)
    _previous_why = why(path) if _previous[0] else ""
    if _previous[0] and still_running(_previous[1]):
        # another copy is starting right now (the installer's Finish page opened it and
        # the desktop icon was double-clicked too): not a start that died. Taken as one,
        # it was counted whenever this copy won the single-instance check and the other
        # quit as the second launch.
        _previous, _previous_why = ("", 0), ""
    _previous_at = written(path) if _previous[0] else 0.0
    _previous_stall = _read_stall(path) if _previous[0] else ""
    mark(version, path)


def _read_stall(directory: Path) -> str:
    """Read any startup-stall.txt left by a previous failed start before watch_stall
    unlinks it."""
    try:
        return (directory / STALL_NAME).read_text(encoding="utf-8", errors="replace")[:64_000]
    except OSError:
        return ""


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


def previous_why() -> str:
    """What the last run's breadcrumb says ended it: the Python error
    (`AttributeError@soundboard/core/app.py:650`), else how far it got (`stage-window`),
    or "" (none left, or one from a version that didn't write these down)."""
    return _previous_why


def previous_at() -> float:
    """When the last run left its breadcrumb (time.time() scale), or 0 with none."""
    return _previous_at


def previous_stall() -> str:
    """startup-stall.txt captured from a previous failed start, or ""."""
    return _previous_stall


def stall_frame(stall: str) -> str:
    """Our own deepest `soundboard/...py:N` frame from the last MainThread dump in
    startup-stall.txt (or the last thread dump if MainThread isn't named), or ""."""
    if not stall:
        return ""
    blocks = re.split(r"(?m)^(?=Thread )", stall)
    main_blocks = [b for b in blocks if "(MainThread):" in b]
    for block in reversed(main_blocks or blocks):
        hits = _STALL_FRAME_RE.findall(block)
        if hits:
            file, line = hits[-1]
            return f"{file.replace(chr(92), '/')}:{line}"
    return ""


def written(directory: Path) -> float:
    """When `directory`'s breadcrumb was written, or 0."""
    try:
        return (Path(directory) / NAME).stat().st_mtime
    except OSError:
        return 0.0


_mine: dict = {}   # this run's breadcrumb as last written (stage() and failed() add to it)


def mark(version: str, directory: Path | None = None) -> Path | None:
    """Leave this run's breadcrumb (best effort: it never stops or slows a start)."""
    _mine.clear()
    _mine.update(version=version, pid=os.getpid(), stage="boot")
    return _write(directory)


def _write(directory: Path | None) -> Path | None:
    try:
        path = Path(directory) if directory is not None else app_dir()
        path.mkdir(parents=True, exist_ok=True)
        file = path / NAME
        file.write_text(json.dumps(_mine), encoding="utf-8")
        return file
    except OSError:
        return None


def _still_mine(directory: Path | None) -> bool:
    """This run left a breadcrumb and it's still there as this run's: not cleared (the
    app is up), and not another copy's that started meanwhile."""
    if not _mine:
        return False
    path = Path(directory) if directory is not None else app_dir()
    return read(path)[1] == os.getpid()


def stage(name: str, directory: Path | None = None) -> None:
    """How far this start got, for the next start to say if this one dies here. A
    no-op once the breadcrumb is gone (the app is up) or after a one-off command."""
    if _STAGE_RE.fullmatch(name) and _still_mine(directory):
        _mine["stage"] = name
        _write(directory)


def failed(exc: BaseException, directory: Path | None = None) -> None:
    """main.py: a Python error ended this start. Written down as its type and our own
    deepest file:line (never its message), for the next start to count: an error before
    applog's hooks are in leaves no report. One the hooks do report clears the breadcrumb
    with it (applog._clear_bootmark), so it's counted once. Never raises."""
    if isinstance(exc, SystemExit):
        return   # an exit on purpose: the paths that take one clear the breadcrumb
    try:
        if not _still_mine(directory):
            return
        name = type(exc).__name__
        frames = []
        tb = exc.__traceback__
        while tb is not None:   # our own deepest line, as the usage count spells it
            file = str(tb.tb_frame.f_code.co_filename).replace("\\", "/")
            at = file.rfind("soundboard/")
            if at >= 0 and file.endswith(".py"):
                frames.append(f"{file[at:]}:{tb.tb_lineno}")
            tb = tb.tb_next
        text = f"{name}@{frames[-1]}" if frames else name
        err = text if _ERROR_RE.fullmatch(text) else (
            name if _ERROR_RE.fullmatch(name) else "Unnamed")
        _mine["error"] = err
        _write(directory)
        _log_failure(directory, err)
    except Exception:  # noqa: BLE001 - never hide the error being raised
        pass


def _log_failure(directory: Path | None, err: str) -> None:
    """Append a single safe line (type + our own file:line + stage, never the message)
    to onionboard.log so a failure before applog.setup still leaves a local trace."""
    try:
        import time
        path = Path(directory) if directory is not None else app_dir()
        path.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        stage_name = _mine.get("stage") or "boot"
        with open(path / LOG_NAME, "a", encoding="utf-8") as f:
            f.write(f"{stamp} ERROR Startup failed (stage={stage_name}): {err}\n")
    except OSError:
        pass


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


def why(directory: Path) -> str:
    """previous_why's text for `directory`'s breadcrumb: its error, else
    `stage-<how far it got>`, or "" when it has neither (or they look wrong)."""
    try:
        data = json.loads((Path(directory) / NAME).read_text(encoding="utf-8"))
        error, at = data.get("error"), data.get("stage")
    except (OSError, ValueError, AttributeError, TypeError):
        return ""
    if isinstance(error, str) and _ERROR_RE.fullmatch(error):
        return error
    if isinstance(at, str) and _STAGE_RE.fullmatch(at):
        return STAGE_PREFIX + at
    return ""


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


def _stacks(frames: int = STALL_FRAMES) -> str:
    """Every other thread's stack (its `frames` innermost), innermost frame last, as
    faulthandler's dump named them. Also the audio watchdog's dump at a stall."""
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
        out.extend(traceback.format_stack(frame, limit=frames))
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
