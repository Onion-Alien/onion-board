"""The usage count's problem events (usage.py): crash / error / freeze reports read
out as their kind, version and our own file:line only, the running.txt mark for an
unclean exit, and a start-up that died before it began. Nothing here sends anything."""
from __future__ import annotations

import re
from pathlib import Path

from soundboard import __version__

RUNNING = "running.txt"     # in the app folder while the app runs (mark_running)
MAX_PROBLEMS = 10           # problem events per send: a bug in a loop isn't 1000 hits
VERSION_RE = r"[0-9][0-9A-Za-z.\-]{0,20}"


# a stack line in a report: `File "...\soundboard\audio\engine.py", line 1090, in ...`; only
# our own files count, named from the package folder down (never the folder above it)
_OUR_FRAME = re.compile(r'^\s*File "(?:[^"]*[\\/])?(soundboard(?:[\\/][a-z0-9_]+){0,2}'
                        r'[\\/][a-z0-9_]+\.py)", line (\d+)', re.M)
_ANY_FRAME = re.compile(r'^\s*File ".*", line \d+', re.M)
_ERROR_TYPE = re.compile(r"([A-Za-z_][\w.]*)(?::|$)")
# the same "our own file" rule as _OUR_FRAME, for a caught exception's traceback object
# (warned): the package folder down, never the folders above it
_OUR_FILE = re.compile(r"soundboard(?:[\\/][a-z0-9_]+){0,2}[\\/][a-z0-9_]+\.py")


def _ours(stack: str) -> list[str]:
    """Our own lines in a stack, outermost first, as `soundboard/audio/engine.py:1090` (the
    same file and line anyone can look up in the public source). threadnames.py only
    wraps Thread.start / run, so its lines are left out: they name their caller."""
    frames = [f"{file.replace(chr(92), '/')}:{line}"
              for file, line in _OUR_FRAME.findall(stack)]
    return [f for f in frames if not f.startswith("soundboard/core/threadnames.py:")] or frames


def _where(stack: str) -> str:
    """The deepest of our own lines in a report's stack, or ""."""
    frames = _ours(stack)
    return frames[-1] if frames else ""


def _tb_where(tb) -> str:
    """The deepest of our own lines in a caught exception's traceback, as
    `soundboard/audio/engine.py:1090` (deeper frames can be another library's: only ours
    count), or ""."""
    where = ""
    while tb is not None:
        name = str(tb.tb_frame.f_code.co_filename).replace(chr(92), "/")
        m = _OUR_FILE.search(name)
        if m and not m.group(0).startswith("soundboard/core/threadnames.py"):
            where = f"{m.group(0)}:{tb.tb_lineno}"
        tb = tb.tb_next
    return where


# the innermost frame of a stuck window, when it's outside our code: only the module's
# file name (never its folder) and the function, e.g. `threading.wait`
_INNER = re.compile(r'^\s*File "(?:[^"]*[\\/])?([A-Za-z0-9_]+)\.py", line \d+, in ([A-Za-z_]\w*)$')
BUSY = 0.3   # a thread using this share of a core or more was working, not waiting
IN_DIALOG_MARK = "inside a window's own event loop"   # hangwatch.IN_DIALOG_NOTE
ALL_HELD_MARK = "every thread was held up"   # hangwatch.ALL_HELD_NOTE
GC_SWEEP_MARK = "a full garbage sweep over the whole app"   # hangwatch.GC_SWEEP_NOTE


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


def _freeze_tag(head: str, window: str, others: str) -> str:
    """`@<deepest line><<its caller>~<stuck in>/<how long>/<who was busy>`, e.g.
    `@soundboard/ui/window/mainwindow.py:5898<soundboard/core/app.py:100~threading.wait/
    lasted-10-30s/idle`: each part only when the report has it."""
    ours = _ours(window)
    tag = f"@{ours[-1]}" if ours else ""
    if len(ours) > 1:
        tag += f"<{ours[-2]}"
    inner = _blocked_in(window)
    if inner:
        tag += f"~{inner}"
    rest = ["in-dialog"] if IN_DIALOG_MARK in window else []
    if ALL_HELD_MARK in window:   # the whole app, not the window alone
        rest.append("all-held")
    if GC_SWEEP_MARK in window:   # uigc's deep sweep held it (reading the app back in)
        rest.append("gc-sweep")
    rest += [p for p in (_lasted(head), _busy(window, others)) if p]
    rest += _memory(window)   # a PC short of memory: the likely cause of an idle freeze
    return tag + "".join(f"/{p}" for p in rest)


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


def _report_event(path: Path) -> str:
    """`crash/1.9.6`, `error/1.9.6` or `freeze/1.9.6` for a saved report (applog.py),
    then where it happened when the stack shows it: `error/1.9.6/KeyError@
    soundboard/audio/engine.py:1090`, `freeze/1.9.6@soundboard/mic/directmic.py:184` (a freeze
    with more: _freeze_tag)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read(64_000)
    except OSError:
        return ""
    head = text[:600]
    if head.startswith("Onion Board ended without closing"):   # exitwatch.py: counted
        return ""                                          # as unclean-exit/ already
    m = re.search(rf"^Version:\s*({VERSION_RE})\s*$", head, re.M)
    ver = m.group(1) if m else __version__
    # the stack only: never the log lines saved below it
    stack = re.split(r"^Last \d+ log lines\s*$", text, maxsplit=1, flags=re.M)[0]
    stack = stack.split("\n\n", 1)[-1]
    # a freeze: the window's own stack; the other threads hangwatch.py adds only say
    # which one was busy
    stack, *others = re.split(r"^Other threads\s*$", stack, maxsplit=1, flags=re.M)
    if "froze for" in head.split("\n", 1)[0]:
        return f"freeze/{ver}" + _freeze_tag(head, stack, "".join(others))
    kind = "crash" if re.search(r"^Fatal:", head, re.M) else "error"
    return f"{kind}/{ver}" + _error_tag(stack)


def _error_tag(stack: str) -> str:
    """`/<type>@<deepest line><<its caller>~<raised in>`, e.g. `/TypeError@soundboard/
    ui/apps/appspanel.py:352<soundboard/ui/apps/appspanel.py:380~enum.__or__`: like a freeze's,
    the caller and the library function it was raised in tell apart errors that end on
    the same line. Each part only when the stack has it."""
    ours = _ours(stack)
    tag = "@".join(p for p in (_error_type(stack), ours[-1] if ours else "") if p)
    if len(ours) > 1:
        tag += f"<{ours[-2]}"
    inner = _blocked_in(stack)
    if inner:
        tag += f"~{inner}"
    return f"/{tag}" if tag else ""


def problems(app_dir: Path, since: float,
             skipped: list[int] | None = None) -> tuple[list[str], float]:
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
        ev = _report_event(f)
        if ev:
            out.append(ev)
    if skipped is not None:
        skipped.append(over)
    return out, newest


def mark_running(app_dir: Path) -> str:
    """At start: note that the app is running. Returns `unclean-exit/<version>` when the
    last run never got to mark_stopped (it crashed hard, was ended in Task Manager, or
    the PC lost power), else ""."""
    path = app_dir / RUNNING
    event = ""
    try:
        old = path.read_text(encoding="utf-8").strip()
        if re.fullmatch(VERSION_RE, old):
            event = f"unclean-exit/{old}"
    except OSError:
        pass
    try:
        path.write_text(__version__, encoding="utf-8")
    except OSError:
        pass
    return event


def mark_stopped(app_dir: Path) -> None:
    """At a real quit (MainWindow.shutdown, also when Windows ends the session)."""
    try:
        (app_dir / RUNNING).unlink(missing_ok=True)
    except OSError:
        pass


def startup_failed(app_dir: Path, version: str, pid: int = 0, native: str = "",
                   started: float = 0.0) -> str:
    """`startup-failed/<version>` for a run that died before it started (bootmark.py's
    breadcrumb was left behind): a crash while Qt or a module loaded, which left no
    report and no running.txt. Adds what ended it when it's known -- the native stacks
    faulthandler caught, or Windows' own error for that process -- as names and our own
    file:line only, never a message. "" (nothing to count) when it left no trace and
    Windows started again since the breadcrumb was left at `started`: the PC was shut
    down or lost power while the app loaded. Runs wevtutil (call it off the UI thread)."""
    from soundboard.core import exitwatch
    event = f"startup-failed/{version}"
    err, where = exitwatch.native_summary(native)
    if err or where:
        return event + "/" + "@".join(p for p in (err, where) if p)
    events = exitwatch.windows_events(pid) if pid else []
    for ev in events:
        if ev["kind"] == "windows-error":
            return event + "/" + "@".join(p for p in (ev["code"], ev["module"]) if p)
    if any(ev["kind"] == "not-responding" for ev in events):
        return event + "/not-responding"
    if started and exitwatch.boot_time() > started:
        return ""   # like an unclean exit's pc-restarted: not the app's problem
    return event
