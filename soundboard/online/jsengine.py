"""Which JavaScript engine yt-dlp gets for YouTube's player challenge.

YouTube hides its streams behind a puzzle in its player script. yt-dlp solves it with a
JavaScript engine (yt-dlp-ejs); without one it sees fewer formats and warns that this
way is deprecated. Most PCs have no engine, so the app ships QuickJS
(scripts/buildtools/fetch_qjs.py, bundled by build.ps1). Deno, Node and Bun solve it several times
faster, so one installed at a version yt-dlp supports comes first: Deno, Node, Bun, then
the app's QuickJS. The engine only runs on this PC: nothing it does goes online.

Worked out once per run (each engine is started with --version, hidden), from ytdl's
options, which are only made off the UI thread. No engine is fine: yt-dlp goes without.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# yt-dlp's names, best first, with the oldest version it accepts (MIN_SUPPORTED_VERSION
# in yt_dlp/utils/_jsruntime.py)
INSTALLED = (("deno", (2, 3, 0)), ("node", (22, 0, 0)), ("bun", (1, 2, 11)))
QUICKJS = "quickjs"
QJS_EXE = "qjs.exe"
VERSION_TIMEOUT_S = 5
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# the frozen app's _internal folder (build.ps1 bundles qjs\ there); from source, where
# scripts/buildtools/fetch_qjs.py leaves it (a source run without it simply goes without QuickJS)
QJS_DIR = (Path(sys._MEIPASS) / "qjs" if hasattr(sys, "_MEIPASS")   # pyright: ignore[reportAttributeAccessIssue]
           else Path(__file__).resolve().parents[2] / "build" / "qjs")


@dataclass(frozen=True)
class Engine:
    name: str                  # yt-dlp's name for it: deno, node, bun, quickjs
    path: str
    version: tuple[int, ...]


_lock = threading.Lock()
_picked: list[Engine] | None = None


def bundled_qjs() -> Path | None:
    p = QJS_DIR / QJS_EXE
    return p if p.is_file() else None


def _version(exe: str, quickjs: bool = False) -> tuple[int, ...] | None:
    """The engine's version, or None if it won't start or say. QuickJS has no
    --version: its --help names it (and exits 1)."""
    try:
        p = subprocess.run([exe, "--help" if quickjs else "--version"],
                           capture_output=True, text=True, errors="replace",
                           stdin=subprocess.DEVNULL, timeout=VERSION_TIMEOUT_S,
                           creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    out = p.stdout + p.stderr
    if quickjs and "QuickJS" not in out:
        return None
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", out)
    return tuple(int(g) for g in m.groups(default="0")) if m else None


def detect() -> list[Engine]:
    """Every engine yt-dlp could use here, best first: the installed ones at a version
    it supports, then the app's QuickJS."""
    found = []
    for name, oldest in INSTALLED:
        exe = shutil.which(name)
        v = _version(exe) if exe else None
        if v and v >= oldest:
            found.append(Engine(name, exe, v))   # pyright: ignore[reportArgumentType]
        elif exe:
            log.info("%s %s is too old for yt-dlp (needs %s)", name,
                     ".".join(map(str, v or ())) or "?", ".".join(map(str, oldest)))
    if qjs := bundled():
        found.append(qjs)
    return found


def bundled() -> Engine | None:
    """The app's own QuickJS, if it's there and starts."""
    qjs = bundled_qjs()
    v = _version(str(qjs), quickjs=True) if qjs else None
    return Engine(QUICKJS, str(qjs), v) if qjs and v else None


def picked() -> list[Engine]:
    """detect(), once per run."""
    global _picked
    with _lock:
        if _picked is None:
            _picked = detect()
            if _picked:
                e = _picked[0]
                log.info("JavaScript engine for YouTube: %s %s", e.name,
                         ".".join(map(str, e.version)))
            else:
                log.info("no JavaScript engine for YouTube: yt-dlp goes without "
                         "(fewer formats)")
        return _picked


def forget():
    """Look again next time (tests; after an engine is installed)."""
    global _picked
    with _lock:
        _picked = None


def runtimes() -> dict:
    """yt-dlp's js_runtimes option: the best engine, and the app's QuickJS behind Deno
    or Node in case yt-dlp refuses that one (yt-dlp ranks QuickJS below those two but
    above Bun, so Bun goes alone). Empty: no engine, yt-dlp goes without."""
    found = picked()
    if not found:
        return {}
    best = found[0]
    out = {best.name: {"path": best.path}}
    qjs = next((e for e in found if e.name == QUICKJS), None)
    if qjs and best.name in ("deno", "node"):
        out[QUICKJS] = {"path": qjs.path}
    return out
