"""Whole stacks for the usage count's problem events (usage.py), the way a tracing tool
shows them: every frame, ours and the libraries', outermost first, the thread it ran on,
and the exceptions that led to it (`raise ... from`, or one raised while handling another).

    "trace": ["soundboard/core/app.py:820:main", "PySide6.QtCore:0:exec",
              "soundboard/audio/engine.py:1090:play", "numpy.core.fromnumeric:42:sum"],
    "thread": "MainThread",
    "cause1_type": "OSError", "cause1_how": "cause", "cause1_trace": ["..."]

Our own frames are named as before (`soundboard/audio/engine.py:1090:play`, the file
from the package folder down). A library's frame is its module, line and function
(`numpy.core.fromnumeric:42:sum`), never its file: an installed copy's paths hold the
Windows user name. A frame from a file outside the app's own install (a script someone
ran, a file they made) is only `<outside>`. Never a message, a variable or a path. Pure
functions: nothing here sends anything."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

MAX_TRACE = 32    # frames per stack: the count server's longest list
HEAD = 4          # outermost frames kept when a stack is longer (the rest are the deepest)
MAX_CHAIN = 3     # exceptions that led to the error, after the error itself
OUTSIDE = "<outside>"
SKIP = "soundboard/core/threadnames.py"   # only wraps Thread.run: names its caller

_OUR_FILE = re.compile(r"soundboard(?:[\\/][a-z0-9_]+){0,2}[\\/][a-z0-9_]+\.py")
_MODULE = re.compile(r"[A-Za-z_][\w.]{0,80}", re.ASCII)
_FUNC = re.compile(r"[A-Za-z_<][\w<>.]{0,80}", re.ASCII)
_TYPE = re.compile(r"[A-Za-z_][\w.]{0,60}", re.ASCII)
# a library file in a report's text: the part after the last folder Python loads from
_LIB_PATH = re.compile(r"^.*[\\/](?:site-packages|dist-packages|_internal|Lib|lib[\\/]python3\.\d+"
                       r"|OnionBoard[\\/]modules[\\/][\w-]+)[\\/](.+?)\.pyc?$", re.I)
_TEXT_FRAME = re.compile(r'^\s*File "([^"\n]*)", line (\d+), in (.+?)\s*$', re.M)
_CHAIN = re.compile(r"^(The above exception was the direct cause of the following exception:"
                    r"|During handling of the above exception, another exception occurred:)"
                    r"\s*$", re.M)
_ERROR_LINE = re.compile(r"([A-Za-z_][\w.]*)(?::|$)")


def thread_tag(name) -> str:
    """A thread's name as a count's word: numbers as N (`Thread-12 (run)` is
    `Thread-N_run`), anything but letters, digits and `_.-` as `_`; "" when nothing's left.
    The app names its own threads in code ("voicesdk-listeners"), never from what someone
    typed."""
    text = re.sub(r"\d+", "N", str(name or ""))
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_")[:40]
    return text if re.match(r"[A-Za-z]", text) else ""


def _word(text, pattern=_FUNC) -> str:
    text = str(text or "")
    return text if pattern.fullmatch(text) else "?"


_roots: list = [None, None]   # (Python's and the app's folders, the add-on folder)


def _norm(path) -> str:
    return os.path.normcase(os.path.abspath(str(path))).rstrip("\\/") + os.sep


def _install_roots() -> tuple[str, ...]:
    """The folders the app's own code comes from: Python and its libraries, the installed
    copy (or the source folder), and the add-on folder. Each worked out once, without
    importing anything or reading the disk again (it can run on any thread)."""
    if _roots[0] is None:
        _roots[0] = tuple({_norm(p) for p in (
            sys.prefix, sys.base_prefix, sys.exec_prefix, getattr(sys, "_MEIPASS", ""),
            Path(__file__).resolve().parents[2]) if p})
    if _roots[1] is None:
        app_dir = getattr(sys.modules.get("soundboard.sounds.library"), "APP_DIR", None)
        if app_dir is not None:   # known once the library has loaded: ask until then
            _roots[1] = (_norm(Path(app_dir) / "modules"),)
    return _roots[0] + (_roots[1] or ())


def _inside(filename: str) -> bool:
    """`filename` (a code object's) is part of the app or its libraries. A frozen copy's
    files have relative names (they're in its archive), and `<frozen ...>` is Python's own."""
    if filename.startswith("<frozen "):
        return True
    if filename.startswith("<") or not filename:
        return False
    if not os.path.isabs(filename):
        return True
    name = os.path.normcase(os.path.abspath(filename))
    return any(name.startswith(root) for root in _install_roots())


def code_frame(code, line: int, module) -> str:
    """One frame of a live traceback, as the module docstring says."""
    file = str(code.co_filename).replace("\\", "/")
    ours = _OUR_FILE.search(file)
    if ours:
        return f"{ours.group(0)}:{line}:{_word(code.co_name)}"
    if not _inside(str(code.co_filename)):
        return OUTSIDE
    func = getattr(code, "co_qualname", code.co_name)
    return f"{_word(module, _MODULE)}:{line}:{_word(func)}"


def text_frame(path: str, line: str, func: str) -> str:
    """One frame of a saved report's stack (`File "...", line 12, in play`)."""
    ours = _OUR_FILE.search(path.replace("\\", "/"))
    if ours:
        return f"{ours.group(0).replace(chr(92), '/')}:{line}:{_word(func)}"
    if path.startswith("<frozen ") and path.endswith(">"):
        module = path[8:-1]
    elif (m := _LIB_PATH.match(path)) is not None:
        module = m.group(1)
    elif path and not path.startswith("<") and not re.match(r"^(?:[A-Za-z]:|[\\/%~])", path):
        module = path.rsplit(".", 1)[0]   # a frozen copy's archive: relative to its root
    else:
        return OUTSIDE
    module = re.sub(r"[\\/]", ".", module).removesuffix(".__init__")
    if not _MODULE.fullmatch(module):
        return OUTSIDE
    return f"{module}:{line}:{_word(func)}"


def cut(frames: list[str]) -> list[str]:
    """A stack that fits a count: our wrapper's frames left out, runs of `<outside>` as one,
    and past MAX_TRACE the HEAD outermost, `~N` for the N left out, then the deepest."""
    out: list[str] = []
    for f in frames:
        if f.startswith(SKIP + ":") or (f == OUTSIDE and out and out[-1] == OUTSIDE):
            continue
        out.append(f)
    if len(out) > MAX_TRACE:
        tail = MAX_TRACE - HEAD - 1
        out = [*out[:HEAD], f"~{len(out) - HEAD - tail}", *out[-tail:]]
    return out


def tb_trace(tb) -> list[str]:
    """Every frame of traceback `tb`, outermost first (cut)."""
    frames = []
    while tb is not None:
        frame = tb.tb_frame
        frames.append(code_frame(frame.f_code, tb.tb_lineno, frame.f_globals.get("__name__")))
        tb = tb.tb_next
    return cut(frames)


def text_trace(stack: str) -> list[str]:
    """Every frame of one exception's printed stack, outermost first (cut)."""
    return cut([text_frame(*m.groups()) for m in _TEXT_FRAME.finditer(stack)])


def exc_trace(e: BaseException | None, thread: str = "") -> dict:
    """The attributes for exception `e`: its whole stack, the thread, and up to MAX_CHAIN
    exceptions that led to it (`causeN_type`, `causeN_how` "cause" for `raise ... from`
    or "context" for one raised while handling it, `causeN_trace`), nearest first."""
    if not isinstance(e, BaseException):
        return {}
    out: dict = {"trace": tb_trace(e.__traceback__), "thread": thread}
    seen, now = {id(e)}, e
    for i in range(1, MAX_CHAIN + 1):
        if now.__cause__ is not None:
            nxt, how = now.__cause__, "cause"
        elif not now.__suppress_context__ and now.__context__ is not None:
            nxt, how = now.__context__, "context"
        else:
            break
        if id(nxt) in seen:
            break
        seen.add(id(nxt))
        out[f"cause{i}_type"] = _word(type(nxt).__name__, _TYPE)
        out[f"cause{i}_how"] = how
        out[f"cause{i}_trace"] = tb_trace(nxt.__traceback__)
        now = nxt
    return out


def _last_type(block: str) -> str:
    """The exception type a printed stack ends with (`KeyError`), never its message."""
    frames = list(_TEXT_FRAME.finditer(block))
    rest = block[frames[-1].end():] if frames else block
    for line in rest.splitlines():
        if line.strip() and not line[:1].isspace() and not line.startswith("Traceback"):
            m = _ERROR_LINE.match(line)
            name = m.group(1).rsplit(".", 1)[-1] if m else ""
            return name if _TYPE.fullmatch(name) and len(name) <= 40 else ""
    return ""


def text_attrs(stack: str, thread: str = "") -> dict:
    """exc_trace for a saved report's printed error: Python prints the first cause first
    and the error itself last, with a line between each."""
    parts = _CHAIN.split(stack)
    blocks, links = parts[0::2], parts[1::2]
    out: dict = {"trace": text_trace(blocks[-1]), "thread": thread}
    for i in range(1, MAX_CHAIN + 1):
        j = len(blocks) - 1 - i
        if j < 0:
            break
        out[f"cause{i}_type"] = _last_type(blocks[j])
        out[f"cause{i}_how"] = "cause" if links[j].startswith("The above") else "context"
        out[f"cause{i}_trace"] = text_trace(blocks[j])
    return out


_WHERE = re.compile(r"^Where:\s*background task '([^'\n]{1,120})'\s*$", re.M)


def report_thread(head: str) -> str:
    """The thread a saved crash report's error happened on: the background task its
    `Where:` line names, else the window's own (`MainThread`)."""
    m = _WHERE.search(head)
    return thread_tag(m.group(1)) if m else "MainThread"
