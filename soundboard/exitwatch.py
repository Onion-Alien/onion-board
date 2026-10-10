"""Why the last run ended without closing itself.

usage.py only learns *that* a run never reached a clean quit (`running.txt` left
behind). This keeps a small black box while the app runs, so the next start can say
why, in the usage count (`unclean-exit/<version>/<why>`) and in a report saved beside
the crash reports:

- `last-run.json`: when this run started, a heartbeat every HEARTBEAT_S, whether the
  window was frozen at that moment, and whether a quit had started.
- `native-crash.txt`: Python's faulthandler writes every thread's stack here if the
  process dies in native code (an access violation in Qt, PortAudio, a DLL) -- the
  kind of crash that never reaches applog's Python hooks. Emptied at a clean quit.
- Windows' own Application log: an "Application Error" (the exception code and the
  DLL it happened in) or "Application Hang" (Windows closed it as Not Responding)
  for this run's process ID. Read with wevtutil, on this PC only.

The kinds, most certain first: `native-crash`, `windows-error`, `not-responding`,
`while-closing` (a quit started but never finished), `frozen` (the window was stuck
at the last heartbeat: probably ended in Task Manager), `pc-restarted` (the PC
started again since the last heartbeat: a power cut, a forced restart, a blue
screen), `ended` (none of those: ended in Task Manager, or killed without a trace).
"""
from __future__ import annotations

import ctypes
import faulthandler
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from soundboard import __version__

log = logging.getLogger(__name__)

STATE = "last-run.json"
NATIVE = "native-crash.txt"
HEARTBEAT_S = 30.0
FROZEN_S = 5.0          # the window stuck this long at a heartbeat counts as frozen
EVENTS_MAX_AGE_MS = 14 * 24 * 3600 * 1000
WEVTUTIL_TIMEOUT_S = 10
LOG_LINES = 40          # of the last run's log, in the report

_KINDS = ("native-crash", "windows-error", "not-responding", "while-closing", "frozen",
          "pc-restarted", "ended")
# Windows exception codes worth a name; anything else is sent as its hex code
_CODES = {0xC0000005: "access-violation", 0xC0000409: "fast-fail",
          0xC00000FD: "stack-overflow", 0xC0000374: "heap-corruption",
          0x80000003: "breakpoint", 0xC000001D: "illegal-instruction",
          0xC0000094: "divide-by-zero", 0xE06D7363: "cpp-exception",
          0xC0000420: "assertion", 0x40000015: "abort"}
# Codes COM and RPC raise to tell a caller "not now / not here" and catch themselves.
# faulthandler still writes stacks for them (0x8001010d came from a Qt window message
# while a COM call was in flight), but they never end the app.
_HARMLESS = {0x8001010D,   # RPC_E_CANTCALLOUT_ININPUTSYNCCALL
             0x8001010E,   # RPC_E_WRONG_THREAD
             0x800706BA,   # RPC_S_SERVER_UNAVAILABLE
             0x800706BE}   # RPC_S_CALL_FAILED
_FAULT_CODE = re.compile(r"^Windows fatal exception: code (0x[0-9a-f]+)", re.M | re.I)
_FAULT_OTHER = re.compile(r"^(?:Fatal Python error|Windows fatal exception: (?!code ))", re.M)
_DLL = re.compile(r"^[A-Za-z0-9_.\-]{1,40}\.(?:dll|exe|pyd)$", re.I)


# -- while running ----------------------------------------------------------------

class ExitWatch:
    """The black box for this run. `ui_stuck()` says how many seconds the window has
    been stuck (hangwatch), read on the heartbeat thread."""

    def __init__(self, app_dir: Path, ui_stuck=lambda: 0.0):
        self.dir = Path(app_dir)
        self.ui_stuck = ui_stuck
        self.state = {"version": __version__, "pid": os.getpid(), "started": time.time(),
                      "alive": time.time(), "stuck_s": 0.0, "quitting": False}
        self._stop = threading.Event()
        self._native = None
        self._arm()
        self._write()
        threading.Thread(target=self._beat, daemon=True, name="exitwatch").start()

    def _arm(self):
        """A fresh, empty native-crash.txt for faulthandler to write into."""
        old, self._native = self._native, None
        try:
            self._native = open(self.dir / NATIVE, "w", encoding="utf-8")
            faulthandler.enable(self._native, all_threads=True)
        except (OSError, RuntimeError, ValueError):
            log.debug("faulthandler not on", exc_info=True)
        if old is not None:
            try:
                old.close()
            except OSError:
                pass

    def _survived(self):
        """Windows tells faulthandler about a native error before anyone gets to catch
        it, so a caught one (ctypes turns a bad read into an OSError) writes stacks
        too. Still running at a heartbeat: it was survived. Log it, start afresh."""
        try:
            if self._native is None or os.fstat(self._native.fileno()).st_size == 0:
                return
            text = (self.dir / NATIVE).read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            return
        if only_harmless(text):   # Windows' own, handled by Windows: not worth a warning
            log.debug("a harmless Windows error code was caught: %s",
                      ", ".join(_FAULT_CODE.findall(text)))
        else:
            log.warning("a native error was caught and survived:\n%s", text[:4000].strip())
        self._arm()

    def _write(self):
        try:
            tmp = self.dir / (STATE + ".tmp")
            tmp.write_text(json.dumps(self.state), encoding="utf-8")
            os.replace(tmp, self.dir / STATE)
        except OSError:
            pass

    def _beat(self):
        while not self._stop.wait(HEARTBEAT_S):
            try:
                self.state["stuck_s"] = round(float(self.ui_stuck()), 1)
            except Exception:  # noqa: BLE001 - the black box must never take the app down
                pass
            self._survived()
            self.state["alive"] = time.time()
            self._write()

    def quitting(self):
        """A real quit has started (MainWindow.shutdown)."""
        self.state["quitting"] = True
        self.state["alive"] = time.time()
        self._write()

    def stopped(self):
        """The quit finished: nothing to explain next time."""
        self._stop.set()
        try:
            faulthandler.disable()
        except RuntimeError:
            pass
        if self._native is not None:
            try:
                self._native.close()
            except OSError:
                pass
        for name in (NATIVE, STATE):
            try:
                (self.dir / name).unlink(missing_ok=True)
            except OSError:
                pass


_current: list[ExitWatch] = []


def start(app_dir: Path, ui_stuck=lambda: 0.0) -> ExitWatch:
    """Start this run's black box (after read_last)."""
    w = ExitWatch(app_dir, ui_stuck)
    _current[:] = [w]
    return w


def quitting():
    for w in _current:
        w.quitting()


def stopped():
    for w in _current:
        w.stopped()
    _current.clear()


# -- at the next start --------------------------------------------------------------

def read_last(app_dir: Path) -> tuple[dict, str]:
    """The last run's black box: its state and native-crash stacks ("" for none).
    Call before ExitWatch() starts this run's (it empties both)."""
    state, native = {}, ""
    try:
        state = json.loads((Path(app_dir) / STATE).read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            state = {}
    except (OSError, ValueError):
        pass
    try:
        native = (Path(app_dir) / NATIVE).read_text(encoding="utf-8",
                                                    errors="replace")[:64_000].strip()
    except OSError:
        pass
    return state, native


def boot_time() -> float:
    """When Windows last started (time.time() scale), or 0."""
    try:
        k32 = ctypes.windll.kernel32
        k32.GetTickCount64.restype = ctypes.c_ulonglong
        return time.time() - k32.GetTickCount64() / 1000
    except (AttributeError, OSError):
        return 0.0


def windows_events(pid: int) -> list[dict]:
    """Windows' "Application Error" / "Application Hang" events for process `pid` of
    Onion Board in the last two weeks: [{"kind", "code", "module"}], newest first."""
    if not pid or sys.platform != "win32":
        return []
    query = ("*[System[(Provider[@Name='Application Error'] or "
             "Provider[@Name='Application Hang']) and "
             f"TimeCreated[timediff(@SystemTime) <= {EVENTS_MAX_AGE_MS}]]]")
    try:
        out = subprocess.run(["wevtutil", "qe", "Application", f"/q:{query}", "/c:30",
                              "/rd:true", "/f:xml"], capture_output=True,
                             timeout=WEVTUTIL_TIMEOUT_S,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        text = out.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_events(text, pid)


def parse_events(xml_text: str, pid: int) -> list[dict]:
    """The events in wevtutil's output that are about process `pid` (any of its data
    fields equal to the pid: hex, as an Application Hang's bare "1f40", or decimal) of
    OnionBoard.exe."""
    found = []
    pids = {f"0x{pid:x}", f"{pid:x}", str(pid)}
    for chunk in re.findall(r"<Event[ >].*?</Event>", xml_text, re.S):
        try:
            ev = ET.fromstring(re.sub(r"""\sxmlns=(['"])[^'"]*\1""", "", chunk, count=1))
        except ET.ParseError:
            continue
        data = [(d.text or "").strip() for d in ev.iter("Data")]
        if not data or "onionboard" not in data[0].lower():
            continue
        if not pids & {d.lower() for d in data}:
            continue
        provider = ev.find("System/Provider")
        name = provider.get("Name", "") if provider is not None else ""
        if name == "Application Hang":
            found.append({"kind": "not-responding", "code": "", "module": ""})
            continue
        # Application Error: app, version, stamp, module, module version, stamp, code…
        module = data[3] if len(data) > 3 and _DLL.match(data[3]) else ""
        code = data[6] if len(data) > 6 else ""
        found.append({"kind": "windows-error", "code": code_name(code), "module": module})
    return found


def code_name(code: str) -> str:
    """`access-violation` for "0xc0000005" / "c0000005", else the tidy hex, else ""."""
    try:
        n = int(code, 16) & 0xFFFFFFFF
    except (TypeError, ValueError):
        return ""
    return _CODES.get(n, f"0x{n:08x}")


def only_harmless(native: str) -> bool:
    """faulthandler's output holds only codes Windows raises and handles itself
    (_HARMLESS): no crash, nothing to report."""
    codes = _FAULT_CODE.findall(native)
    return (bool(codes) and not _FAULT_OTHER.search(native)
            and all(int(c, 16) & 0xFFFFFFFF in _HARMLESS for c in codes))


def native_summary(native: str) -> tuple[str, str]:
    """From faulthandler's output: the error (`access-violation`) and the deepest of
    our own lines on the crashing thread (`soundboard/engine.py:1090`)."""
    if not native:
        return "", ""
    err = ""
    m = re.search(r"^(?:Windows )?[Ff]atal (?:exception|Python error): ([^\n]+)", native, re.M)
    if m:
        what = m.group(1).strip().lower()
        code = re.search(r"code (0x[0-9a-f]+)", what)
        err = (code_name(code.group(1)) if code
               else re.sub(r"[^a-z0-9]+", "-", what).strip("-")[:30])
    # the crashing thread's stack, newest first ("Current thread ...")
    cur = re.search(r"^Current thread[^\n]*\n((?:[ \t]+[^\n]*\n?)*)", native, re.M)
    stack = cur.group(1) if cur else native
    where = ""
    for f, line in re.findall(r'File "(?:[^"]*[\\/])?(soundboard(?:[\\/][a-z0-9_]+)?'
                              r'[\\/][a-z0-9_]+\.py)", line (\d+)', stack):
        where = f"{f.replace(chr(92), '/')}:{line}"
        break   # newest first: the first of ours is the deepest
    return err, where


def diagnose(state: dict, native: str, events: list[dict], booted: float) -> tuple[str, str]:
    """(kind, detail tag) for a run that ended without closing itself; the tag is short
    and safe to count (an error name, a DLL name, our own file:line), or ""."""
    err, where = native_summary("" if only_harmless(native) else native)
    if err or where:
        return "native-crash", "@".join(p for p in (err, where) if p)
    for ev in events:
        if ev["kind"] == "windows-error":
            return "windows-error", "@".join(p for p in (ev["code"], ev["module"]) if p)
    if any(ev["kind"] == "not-responding" for ev in events):
        return "not-responding", ""
    if state.get("quitting"):
        return "while-closing", ""
    if float(state.get("stuck_s") or 0) >= FROZEN_S:
        return "frozen", ""
    alive = float(state.get("alive") or 0)
    if alive and booted and booted > alive:
        return "pc-restarted", ""
    return "ended", ""


def _plain(kind: str) -> str:
    return {
        "native-crash": "It crashed inside native code (Qt, audio, a DLL). The stacks "
                        "below show what every thread was doing.",
        "windows-error": "Windows recorded it as crashed (Application Error).",
        "not-responding": "It stopped responding and Windows closed it.",
        "while-closing": "It was closing, but never finished (it hung or crashed while "
                         "closing, or Windows ended it while logging off).",
        "frozen": "The window was frozen at the last check-in: probably ended in Task "
                  "Manager. See the freeze report from the same time.",
        "pc-restarted": "The PC started again since it was last seen running: a power "
                        "cut, a forced restart or a blue screen.",
        "ended": "No crash was recorded: it was most likely ended in Task Manager, or "
                 "killed by another program.",
    }.get(kind, "")


def _prev_log(app_dir: Path) -> str:
    """The last LOG_LINES lines of the previous run in onionboard.log (before this
    run's "starting" line), or ""."""
    from soundboard import applog
    try:
        with open(Path(app_dir) / applog.LOG_NAME, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 200_000))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return ""
    starts = [i for i, ln in enumerate(lines) if re.search(r"Onion Board \S+ starting", ln)]
    if len(starts) >= 1:
        lines = lines[:starts[-1]]
    return "\n".join(lines[-LOG_LINES:])


def report_text(state: dict, native: str, events: list[dict], kind: str, tag: str,
                prev_log: str) -> str:
    def when(t):
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) if t else "?"
    lines = ["Onion Board ended without closing itself",
             f"Version:  {state.get('version') or '?'}",
             f"Time:     {time.strftime('%Y-%m-%d %H:%M:%S')}",
             f"Why:      {kind}" + (f" ({tag})" if tag else ""),
             f"Started:  {when(state.get('started'))}",
             f"Last seen running: {when(state.get('alive'))}",
             f"Window stuck then: {state.get('stuck_s', '?')} s",
             f"Closing:  {'yes' if state.get('quitting') else 'no'}",
             "", _plain(kind)]
    for ev in events:
        lines.append(f"Windows log: {ev['kind']} {ev['code']} {ev['module']}".rstrip())
    if native:
        lines += ["", "Native crash (faulthandler)", "---------------------------", native]
    if prev_log:
        lines += ["", f"Last {LOG_LINES} log lines", "-------------------", prev_log]
    return "\n".join(lines)


def check_last(app_dir: Path, state: dict, native: str, unclean_event: str):
    """After an unclean exit (usage.mark_running's `unclean_event`): work out why, add
    it to the usage event, and save a report beside the crash reports. Runs off the UI
    thread (wevtutil takes a moment). Returns (event, report path)."""
    from soundboard import applog
    events = windows_events(int(state.get("pid") or 0))
    kind, tag = diagnose(state, native, events, boot_time())
    log.warning("the last run ended without closing itself: %s%s", kind,
                f" ({tag})" if tag else "")
    rep = applog.Report(title="ended without closing",
                        text=applog.scrub(report_text(state, native, events, kind, tag,
                                                      _prev_log(app_dir))))
    path = applog._save(rep)
    return f"{unclean_event}/{kind}" + (f"/{tag}" if tag else ""), path
