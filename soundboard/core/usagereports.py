"""The usage count's problem events (usage.py): crash / error / freeze reports read
out as their kind, version, error type and our own file, line and function only, the
running.txt mark for an unclean exit, and a start-up that died before it began. Nothing
here sends anything."""
from __future__ import annotations

import re
from pathlib import Path

from soundboard import __version__
from soundboard.core.usageevents import event, place
from soundboard.core.usagetrace import report_thread, text_attrs, text_trace

RUNNING = "running.txt"     # in the app folder while the app runs (mark_running)
MAX_PROBLEMS = 30           # different problems per send: a bug in a loop is one, with a count
VERSION_RE = r"[0-9][0-9A-Za-z.\-]{0,20}"


# a stack line in a report: `File "...\soundboard\audio\engine.py", line 1090, in ...`; only
# our own files count, named from the package folder down (never the folder above it)
_OUR_FRAME = re.compile(r'^\s*File "(?:[^"]*[\\/])?(soundboard(?:[\\/][a-z0-9_]+){0,2}'
                        r'[\\/][a-z0-9_]+\.py)", line (\d+)(?:, in ([\w<>.]{1,60}))?', re.M)
_ANY_FRAME = re.compile(r'^\s*File ".*", line \d+', re.M)
_ERROR_TYPE = re.compile(r"([A-Za-z_][\w.]*)(?::|$)")
# the same "our own file" rule as _OUR_FRAME, for a caught exception's traceback object
# (warned): the package folder down, never the folders above it
_OUR_FILE = re.compile(r"soundboard(?:[\\/][a-z0-9_]+){0,2}[\\/][a-z0-9_]+\.py")


def _frames(stack: str) -> list[str]:
    """Our own frames in a stack, outermost first, as `soundboard/audio/engine.py:1090:play`
    (the same file, line and function anyone can look up in the public source).
    threadnames.py only wraps Thread.start / run, so its lines are left out: they name
    their caller."""
    frames = [f"{file.replace(chr(92), '/')}:{line}:{func}"
              for file, line, func in _OUR_FRAME.findall(stack)]
    return [f for f in frames if not f.startswith("soundboard/core/threadnames.py:")] or frames


def _ours(stack: str) -> list[str]:
    """_frames as `soundboard/audio/engine.py:1090`, without the functions."""
    return [f.rsplit(":", 1)[0] for f in _frames(stack)]


def _where(stack: str) -> str:
    """The deepest of our own lines in a report's stack, or ""."""
    frames = _ours(stack)
    return frames[-1] if frames else ""


def _tb_frames(tb) -> list[str]:
    """Our own frames in a caught exception's traceback, outermost first, as _frames says
    them (deeper frames can be another library's: only ours count)."""
    out = []
    while tb is not None:
        name = str(tb.tb_frame.f_code.co_filename).replace(chr(92), "/")
        m = _OUR_FILE.search(name)
        if m and not m.group(0).startswith("soundboard/core/threadnames.py"):
            out.append(f"{m.group(0)}:{tb.tb_lineno}:{tb.tb_frame.f_code.co_name}")
        tb = tb.tb_next
    return out


def _tb_where(tb) -> str:
    """The deepest of our own lines in a caught exception's traceback, as
    `soundboard/audio/engine.py:1090`, or ""."""
    frames = _tb_frames(tb)
    return frames[-1].rsplit(":", 1)[0] if frames else ""


# the innermost frame of a stuck window, when it's outside our code: only the module's
# file name (never its folder) and the function, e.g. `threading.wait`
_INNER = re.compile(r'^\s*File "(?:[^"]*[\\/])?([A-Za-z0-9_]+)\.py", line \d+, in ([A-Za-z_]\w*)$')
BUSY = 0.3   # a thread using this share of a core or more was working, not waiting
IN_DIALOG_MARK = "inside a window's own event loop"   # hangwatch.IN_DIALOG_NOTE
ALL_HELD_MARK = "every thread was held up"   # hangwatch.ALL_HELD_NOTE
GC_SWEEP_MARK = "a full garbage sweep over the whole app"   # hangwatch.GC_SWEEP_NOTE
NO_CPU_MARK = "the app used no CPU meanwhile"   # hangwatch.NO_CPU_NOTE


def _blocked_in(stack: str) -> str:
    frames = [ln for ln in stack.splitlines() if _ANY_FRAME.match(ln)]
    if not frames or _OUR_FRAME.match(frames[-1]):
        return ""
    m = _INNER.match(frames[-1])
    return f"{m.group(1)}.{m.group(2)}" if m else ""


def _lasted(head: str) -> str:
    m = re.search(r"^Lasted:\s*(.*)$", head, re.M)
    if not m:
        return ""                  # a report from an older version: not known
    s = re.match(r"(\d+) s", m.group(1).strip())
    if not s:
        return "never-ended"       # the app was ended while frozen (or never came back)
    s = int(s.group(1))
    return ("lasted-under-10s" if s < 10 else "lasted-10-30s" if s < 30
            else "lasted-30s-2m" if s < 120 else "lasted-2m-plus")


def _lasted_s(head: str) -> int | None:
    """A freeze's length in whole seconds, when the report says it."""
    m = re.search(r"^Lasted:\s*(\d+) s", head, re.M)
    return int(m.group(1)) if m else None


def _busy(window: str, others: str) -> str:
    """Who was using the CPU while the window was stuck (hangwatch.py measures it):
    `busy-window` (working itself), `busy-thread@<our line>` (another thread was, and
    the window likely waited on it: the GIL or a lock), `idle` (everyone waited: a
    lock, the disk, the network, Windows). "" in a report without the numbers."""
    m = re.search(r"^Window CPU: (\d+)%", window, re.M)
    if not m:
        return ""
    if int(m.group(1)) >= BUSY * 100:
        return "busy-window"
    best, where = BUSY * 100, None
    for block in re.split(r'^(?=Thread ")', others, flags=re.M):
        m = re.match(r'Thread ".*" \(\d+\), (\d+)% CPU:', block)
        if m and int(m.group(1)) >= best:
            best, where = int(m.group(1)), _where(block)
    if where is None:
        return "idle"
    return "busy-thread" + (f"@{where}" if where else "")


# a PC short of memory (hangwatch._pc_memory): `mem-80` / `mem-90` from 80% in use, and
# `paging` when the app page-faulted at least this fast while stuck (swapped to disk)
MEM_HIGH = 80
PAGING_PER_S = 2000


def _memory(window: str) -> list[str]:
    out = []
    m = re.search(r"^PC memory in use: (\d+)%", window, re.M)
    if m and int(m.group(1)) >= MEM_HIGH:
        out.append(f"mem-{min(int(m.group(1)), 99) // 10 * 10}")
    m = re.search(r"^Page faults: (\d+)/s", window, re.M)
    if m and int(m.group(1)) >= PAGING_PER_S:
        out.append("paging")
    return out


def _freeze_attrs(head: str, window: str, others: str) -> dict:
    """What a freeze report says: where it was stuck (place), the library call it was
    stuck in, how long, who was busy and how full the PC's memory was. Each only when
    the report has it."""
    busy = _busy(window, others)
    who, _, at = busy.removeprefix("busy-").partition("@")
    mem = _memory(window)
    return {**place(_frames(window)), "stuck_in": _blocked_in(window),
            "in_dialog": IN_DIALOG_MARK in window,
            "all_held": ALL_HELD_MARK in window,   # the whole app, not the window alone
            "gc_sweep": GC_SWEEP_MARK in window,   # uigc's deep sweep held it
            "no_cpu": NO_CPU_MARK in window,       # nobody was busy: Windows wasn't running it
            "lasted": _lasted(head).removeprefix("lasted-"), "lasted_s": _lasted_s(head),
            "busy": who, "busy_at": at, "trace": text_trace(window), "thread": "MainThread",
            "memory": next((int(m[4:]) for m in mem if m.startswith("mem-")), None),
            "paging": "paging" in mem}


def _error_type(stack: str) -> str:
    """`KeyError` from the traceback's last line: the type only, never its message
    (a message can hold a path, a device or a user name)."""
    frames = list(_ANY_FRAME.finditer(stack))
    if not frames:
        return ""
    for line in stack[frames[-1].end():].splitlines()[1:]:
        if line.strip() and not line[:1].isspace():   # past the frame's code lines
            m = _ERROR_TYPE.match(line)
            name = m.group(1).rsplit(".", 1)[-1] if m else ""
            return name if len(name) <= 40 else ""
    return ""


def _report_event(path: Path, at: float | None = None) -> dict | None:
    """The event for a saved report (applog.py): `crash`, `error` or `freeze`, with the
    version that saved it and what its stack shows. `at`: when it was saved."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read(64_000)
    except OSError:
        return None
    head = text[:600]
    if head.startswith("Onion Board ended without closing"):   # exitwatch.py: counted
        return None                                        # as unclean_exit already
    m = re.search(rf"^Version:\s*({VERSION_RE})\s*$", head, re.M)
    ver = m.group(1) if m else __version__
    # the stack only: never the log lines saved below it
    stack = re.split(r"^Last \d+ log lines\s*$", text, maxsplit=1, flags=re.M)[0]
    stack = stack.split("\n\n", 1)[-1]
    # a freeze: the window's own stack; the other threads hangwatch.py adds only say
    # which one was busy
    stack, *others = re.split(r"^Other threads\s*$", stack, maxsplit=1, flags=re.M)
    if "froze for" in head.split("\n", 1)[0]:
        return event("freeze", at=at, version=ver, **_freeze_attrs(head, stack, "".join(others)))
    kind = "crash" if re.search(r"^Fatal:", head, re.M) else "error"
    return event(kind, at=at, version=ver, **_error_attrs(stack, report_thread(head)))


def _error_attrs(stack: str, thread: str = "") -> dict:
    """The error's type, where it happened (place) and the library function it was raised
    in, which tell apart errors that end on the same line of ours, then its whole stack,
    thread and the exceptions that led to it (usagetrace.text_attrs)."""
    return {"type": _error_type(stack), **place(_frames(stack)), "raised_in": _blocked_in(stack),
            **text_attrs(stack, thread)}


def problems(app_dir: Path, since: float,
             skipped: list[int] | None = None) -> tuple[list[dict], float]:
    """Events for the crash / freeze reports saved in app_dir after `since` (a file
    time), and the newest such time. Only the kind and version are read out. Past
    MAX_PROBLEMS the rest aren't read: how many is added to `skipped`."""
    from soundboard.core.applog import REPORTS_DIR
    out, newest, over = [], since, 0
    try:
        files = sorted((f.stat().st_mtime, f.name, f)
                       for f in (app_dir / REPORTS_DIR).glob("crash-*.txt"))
    except OSError:
        return [], since
    for mtime, _name, f in files:
        if mtime <= since:
            continue
        newest = max(newest, mtime)
        if len(out) >= MAX_PROBLEMS:
            over += 1
            continue
        ev = _report_event(f, mtime)
        if ev:
            out.append(ev)
    if skipped is not None:
        skipped.append(over)
    return out, newest


def mark_running(app_dir: Path) -> dict | None:
    """At start: note that the app is running. Returns an `unclean_exit` event when the
    last run never got to mark_stopped (it crashed hard, was ended in Task Manager, or
    the PC lost power), else None."""
    path = app_dir / RUNNING
    found = None
    try:
        old = path.read_text(encoding="utf-8").strip()
        if re.fullmatch(VERSION_RE, old):
            found = event("unclean_exit", version=old)
    except OSError:
        pass
    try:
        path.write_text(__version__, encoding="utf-8")
    except OSError:
        pass
    return found


def mark_stopped(app_dir: Path) -> None:
    """At a real quit (MainWindow.shutdown, also when Windows ends the session)."""
    try:
        (app_dir / RUNNING).unlink(missing_ok=True)
    except OSError:
        pass


def startup_failed(app_dir: Path, version: str, pid: int = 0, native: str = "",
                   started: float = 0.0) -> dict | None:
    """A `startup_failed` event for a run that died before it started (bootmark.py's
    breadcrumb was left behind): a crash while Qt or a module loaded, which left no
    report and no running.txt. Adds what ended it when it's known -- the native stacks
    faulthandler caught, or Windows' own error for that process -- as names and our own
    file:line only, never a message. None (nothing to count) when it left no trace and
    Windows started again since the breadcrumb was left at `started`: the PC was shut
    down or lost power while the app loaded. Runs wevtutil (call it off the UI thread)."""
    from soundboard.core import exitwatch
    events = exitwatch.windows_events(pid) if pid else []
    tag = exitwatch.native_tag(native, events)
    if tag:
        return event("startup_failed", version=version, detail=tag)
    for ev in events:
        if ev["kind"] == "windows-error":
            return event("startup_failed", version=version,
                         detail="@".join(p for p in (ev["code"], ev["module"]) if p))
    if any(ev["kind"] == "not-responding" for ev in events):
        return event("startup_failed", version=version, detail="not-responding")
    if started and exitwatch.boot_time() > started:
        return None   # like an unclean exit's pc-restarted: not the app's problem
    return event("startup_failed", version=version)
