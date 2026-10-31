"""The mic helper: the mic effect (soundboard/mic/directmic.py) put on or taken off a mic
without Windows' admin prompt every time.

Putting the effect on a mic needs admin (the mic's settings belong to Windows, and its
audio restarts). Without the helper every set-up, repair, change of mic and removal
asked. Now the first admin step (one prompt, the same as before) also installs:

- obmichelper.exe, a small build of the admin part only (no Qt, no numpy) with its own
  copy of the effect DLL, in Program Files\\Onion Board Mic Helper (admins only: nobody
  else can change what runs);
- a scheduled task, TASK, that runs it as SYSTEM when asked. No trigger: it never runs
  by itself, and nothing stays in the background. Only the accounts that set it up
  (USERS, kept in its folder) and admins may start it.

The app asks by writing a request file (one line: a `--direct-mic` admin command) into
%ProgramData%\\OnionBoard\\MicHelper\\requests and starting the task; the helper does
every request it finds and writes each one's exit code into ...\\results (admins only,
so a planted link can't steer what SYSTEM writes). While it works on one it keeps a
heartbeat (`<id>.ack`) there, so the app can tell a helper at work from one that died
half-way (by whether it changes, never by its age on the wall clock: a clock
correction or a sleep mid-step would make a working helper look dead). Requests are
untrusted: only the commands in `allowed()` run, with a mic
GUID as their only argument. The helper
installs only the DLL it carries, so an update to the effect or the helper (another
STAMP) still goes through Windows' prompt once, which updates the helper too. Without
a working helper everything asks as before (directmic._elevated).
"""
from __future__ import annotations

import ctypes
import hashlib
import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from soundboard.mic import safefs
from soundboard.win import systools

log = logging.getLogger(__name__)

# Bump it when the admin part changes (micadmin.py, or this file); tests/test_michelper.py
# fails until it is. A newer helper is
# put in place by the next admin step that asks anyway: only another effect DLL makes
# the app ask (so the helper never adds a prompt the app wouldn't have had).
HELPER_VERSION = 35
# The oldest helper the app still uses. Raise it (to HELPER_VERSION) only when the
# helpers out there have a bug that matters: the app then asks Windows once more, and
# that prompt puts this version's helper in place.
MIN_HELPER_VERSION = 31   # 31: never steered by a link planted in a folder users write to
TASK = r"\Onion Board\Mic helper"
EXE_NAME = "obmichelper.exe"
STAMP = "stamp.txt"
MANIFEST = "manifest.txt"   # a build's files, "<sha256> <path>" a line (since 10)
MANIFEST_SINCE = 10   # helpers from this version on must match their manifest
USERS = "users.txt"   # the accounts it is set up for, a SID a line (admins only)
SERVE = "--serve"
FOR = "--for"         # admin copy: `... --for <SID>`, the account that asked
_CREATE_NO_WINDOW = 0x08000000
_GUID = re.compile(r"\{[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                   r"[0-9a-fA-F]{12}\}")
# a user account: local or domain (S-1-5-21-...), or a Microsoft Entra ID (work or
# school) one (S-1-12-1-...). Never a well-known one (SYSTEM, Everyone, Users...).
_SID = re.compile(r"S-1-5-21(-\d{1,10}){3,4}|S-1-12-1(-\d{1,10}){4}")
_REQUEST = re.compile(r"[0-9a-f]{32}")
MAX_REQUEST = 256
BUSY_TRIES, BUSY_WAIT_S = 40, 0.05   # a request still being written: waited up to 2 s
RESULT_KEEP_S = 3600.0
START_S = 20.0   # the task didn't pick a request up in this long, and Task Scheduler
#                says it isn't running or queued either: it isn't working
STATUS_EVERY_S = 2.0   # ...asked this often past START_S, while the request waits
# Task Scheduler's "Last Result" while a task runs / waits its turn: the same in every
# language, where the status words aren't
_RUNNING_CODES = ("267009", "267045")   # SCHED_S_TASK_RUNNING, SCHED_S_TASK_QUEUED
BEAT_S = 2.0     # the helper touches a request's .ack this often while on it
STALE_S = 30.0   # ...so an .ack this old means it died half-way (killed, crashed)
HARD_S = 960.0   # the task's own time limit (PT15M) and a minute: gone by then


def helper_dir() -> Path:
    return Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Onion Board Mic Helper"


def helper_exe() -> Path:
    return helper_dir() / EXE_NAME


def queue_dir() -> Path:
    from soundboard.mic import directmic
    return directmic.data_dir().parent / "MicHelper"


def requests_dir() -> Path:
    return queue_dir() / "requests"


def results_dir() -> Path:
    return queue_dir() / "results"


def bundled_helper() -> Path:
    """The helper build this app carries: in the frozen app, or what
    scripts/buildtools/build_michelper.py built when run from source."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "michelper"
    return Path(__file__).resolve().parents[2] / "build" / "michelper" / "obmichelper"


def is_helper() -> bool:
    """This process is the helper itself (it never installs or updates a helper)."""
    return Path(sys.executable).name.lower() == EXE_NAME


def make_stamp(dll: Path) -> str:
    """What a helper build is: "HELPER_VERSION <its effect DLL's sha256>"."""
    return f"{HELPER_VERSION} {hashlib.sha256(dll.read_bytes()).hexdigest()}"


def _read_stamp(folder: Path) -> str | None:
    try:
        return (folder / STAMP).read_text(encoding="ascii").strip() or None
    except (OSError, UnicodeDecodeError):
        return None


def _dll_of(stamp: str | None) -> str | None:
    parts = (stamp or "").split()
    return parts[1] if len(parts) == 2 else None


# ---------------------------------------------------------------------- the app's side

def _on_ui_thread() -> bool:
    """Called on the Qt UI thread (schtasks can take seconds: never there)."""
    qt = sys.modules.get("PySide6.QtCore")
    if qt is None:
        return False
    app = qt.QCoreApplication.instance()
    return app is not None and app.thread() is qt.QThread.currentThread()


def _schtasks(*args: str, timeout: float = 30.0, out: list[str] | None = None) -> int:
    """schtasks' exit code (-1 if it didn't run); what it printed goes into `out`."""
    if _on_ui_thread():
        log.warning("mic helper: schtasks on the UI thread", stack_info=True)
    try:
        r = subprocess.run([systools.tool("schtasks"), *args], capture_output=True, timeout=timeout,
                           creationflags=_CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return -1
    if out is not None:
        out.append(r.stdout.decode("mbcs" if os.name == "nt" else "utf-8", "replace"))
    return r.returncode


def installed() -> bool:
    """A helper is there (maybe an older one): its program and its task."""
    return helper_exe().is_file() and _schtasks("/query", "/tn", TASK) == 0


def _helper_dirs() -> list[Path]:
    d = helper_dir()
    return [d, d.with_name(d.name + ".new"), d.with_name(d.name + ".old")]


def leftover() -> bool:
    """Anything of a helper is there, working or not: a folder (a half-done update's
    too) or its task. Uninstalling the app takes all of it away. A folder on Windows'
    list for the next restart is gone already (the helper removing itself runs from it):
    asking for admin again can't take it away any sooner."""
    from soundboard.mic import directmic
    return any(d.exists() and not directmic._marked(d) for d in _helper_dirs()) \
        or _schtasks("/query", "/tn", TASK) == 0


def wait_gone(timeout: float = 20.0) -> bool:
    """After a remove-all through the helper: it removes itself just after answering, so
    the uninstaller's next steps (ProgramData's folder, its own `--direct-mic remove`)
    would still find it and ask for admin again. True once it's gone."""
    end = time.monotonic() + timeout
    while leftover():
        if time.monotonic() > end:
            log.warning("mic helper: still there %.0f s after removing everything", timeout)
            return False
        time.sleep(0.5)
    return True


def for_user(args: list[str]) -> list[str]:
    """What the app adds to an admin step that may set up the helper: the account
    asking. A standard user who types an admin's password runs the admin copy as that
    admin, so it can't tell who asked otherwise. The admin copy checks it."""
    if args[:1] not in (["install"], ["reinstall"], ["cleanup"]) or is_helper():
        return []
    try:
        sid = _token_sid()
    except (AttributeError, OSError):
        return []
    return [FOR, sid] if sid and _SID.fullmatch(sid) else []


def _version_of(stamp: str | None) -> int:
    try:
        return int((stamp or "").split()[0])
    except (IndexError, ValueError):
        return 0


def _check() -> dict[bool, bool]:
    """Is there a helper this app can use, for setting up (True) and for taking the
    effect off (False)? Both at once, with one look at Task Scheduler."""
    have, mine = _read_stamp(helper_dir()), _read_stamp(bundled_helper())
    ok = _version_of(have) >= MIN_HELPER_VERSION
    if ok and have == mine:
        # this app's own build: a file of it gone (a virus scanner) and the task can't
        # start it. Asking Windows now puts it back, rather than a wait for nothing first
        ok = all((helper_dir() / name).is_file() for name in _build_files(bundled_helper()))
    # a file of it changed or gone since it was built: asking Windows puts it back
    if ok and _version_of(have) >= MANIFEST_SINCE:   # (older ones have none)
        ok = verify_build(helper_dir())
    ok = bool(ok and installed())
    want = _dll_of(mine)
    return {False: ok, True: ok and want is not None and _dll_of(have) == want}


def ready(same_dll: bool = True, via: str = "ready") -> bool:
    """A helper this app can use: at least MIN_HELPER_VERSION and, for setting up
    (`same_dll`), carrying the same effect DLL as this app (an older one would put an
    older effect on the mic). An older helper otherwise is fine: the next admin step
    that asks anyway updates it. Both answers go into `state` (`via`: who asked, for
    the log). Runs a process: not on the UI thread."""
    answers = _check()
    state.set(answers, via)
    return answers[same_dll]


RECHECK_S = 600.0   # the window, back in front after this long, checks the helper again


class HelperState:
    """ready()'s last answers, for the UI thread: both of them (setting up, taking off),
    when they were found (time.monotonic()) and who asked. Another account can remove
    the helper (or set it up) any time: the window checks again when the answers are
    older than RECHECK_S, so they never go stale for good."""

    def __init__(self, answers: dict[bool, bool] | None = None, via: str = ""):
        self.answers: dict[bool, bool] = dict(answers or {})
        self.when: float | None = time.monotonic() if answers else None
        self.via = via

    def set(self, answers: dict[bool, bool], via: str):
        if answers != self.answers:
            log.info("mic helper: %s (%s)", "usable" if answers.get(False) else "not usable",
                     via)
        # (one assignment each: a reader on the UI thread never sees half of it)
        self.answers, self.when, self.via = dict(answers), time.monotonic(), via

    def forget(self):
        self.answers, self.when, self.via = {}, None, ""

    def age(self) -> float | None:
        return None if self.when is None else time.monotonic() - self.when


state = HelperState()


def known(same_dll: bool = True) -> bool | None:
    """ready()'s last answer (None: not asked yet), for the UI thread."""
    return state.answers.get(same_dll)


def checked_ago() -> float | None:
    """Seconds since ready() last answered (None: never), for the UI thread."""
    return state.age()


def will_ask(setting_up: bool = True) -> bool:
    """Will Windows' admin prompt come up for the next mic step (`setting_up`: putting
    the effect on, else taking it off)? From ready()'s last answer, so the UI thread can
    ask: not known yet counts as yes (the texts then say to click Yes)."""
    return known(setting_up) is not True


def ask(args: list[str], wait_s: float = 300.0) -> int | None:
    """Have the helper run the admin command `args`. Its exit code, or None if the
    helper didn't take it (not there, not allowed to start it, or it didn't answer)."""
    if not allowed(args):
        raise ValueError(f"not a mic helper command: {args}")
    rid = secrets.token_hex(16)
    req = requests_dir() / f"{rid}.req"
    res = results_dir() / f"{rid}.res"
    try:
        fd = os.open(req, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0))
        with os.fdopen(fd, "wb") as f:
            f.write(" ".join(args).encode("ascii"))
    except OSError:
        log.info("can't leave the mic helper a request", exc_info=True)
        return None
    if _schtasks("/run", "/tn", TASK) != 0:
        log.info("couldn't start the mic helper")
        _forget(req)
        return None
    ack = results_dir() / f"{rid}.ack"
    clock, beats = _Clock(), _Beats()
    running, next_status = False, START_S
    while True:
        waited = clock.now()
        code = _result(res)
        if code is not None:
            _forget(res)   # (admins only: stays; the helper clears old ones)
            return code
        beat = beats.quiet(ack, waited)
        if beat is not None:
            # at work: wait however long it takes (Windows' prompt now would find it
            # holding the lock and fail), unless its heartbeat stopped
            if beat > STALE_S or waited > HARD_S:
                log.warning("the mic helper stopped half-way (no heartbeat for %.0f s)",
                            beat)
                _forget(req)   # (if it died before taking it: never done later too)
                return None
        elif req.exists():
            # not picked up yet: give up after START_S, unless the helper is at work on
            # another request (another account's, or one left behind): it takes ours
            # next, so wait, within the task's own time limit (others are watched from
            # the start: one only counts once it is seen to change)
            busy = beats.busy(ack, waited)
            if waited > START_S and not busy and waited >= next_status:
                # slow to start (a busy PC, Task Scheduler queueing it): wait on while
                # Task Scheduler says it is running or queued, not a fixed time
                running, next_status = task_running(), waited + STATUS_EVERY_S
            if waited > HARD_S or (waited > START_S and not busy and not running):
                log.info("the mic helper didn't pick the request up")
                _forget(req)
                return None
        elif waited > wait_s:   # taken, no heartbeat: a helper older than 5, or gone
            log.info("the mic helper didn't answer in %.0f s", wait_s)
            return None
        time.sleep(0.1)


def task_running() -> bool:
    """Task Scheduler says the helper's task is running or queued (on a worker)."""
    out: list[str] = []
    return (_schtasks("/query", "/tn", TASK, "/v", "/fo", "LIST", out=out) == 0
            and bool(out) and task_running_in(out[0]))


def task_running_in(text: str) -> bool:
    """`schtasks /query /v /fo LIST`'s output says running or queued: its last result
    code (any language) or the English status. Anything else (a language whose status
    words it can't read and no code) counts as not running: the wait is as before."""
    for line in text.splitlines():
        value = line.partition(":")[2].strip()
        if value in _RUNNING_CODES or value in ("Running", "Queued"):
            return True
    return False


GAP_S = 5.0   # ask() didn't look for this long (it looks 10 times a second): the PC slept


class _Clock:
    """Seconds ask() has waited, on time.monotonic() (never the wall clock: a clock
    correction never moves it), not counting time the PC slept: the helper slept too,
    so a wait that went past a limit meanwhile hasn't really."""

    def __init__(self):
        self.last, self.waited = time.monotonic(), 0.0

    def now(self) -> float:
        t = time.monotonic()
        step, self.last = t - self.last, t
        if 0.0 <= step <= GAP_S:
            self.waited += step
        return self.waited


class _Beats:
    """When each heartbeat (.ack) last changed, by ask()'s clock: what it says (a new
    helper writes a count into it) or its time (one of version 5 to 7 only touches
    it). A change is what counts, never how old a file looks by the wall clock: a clock
    put forward made a working helper look dead, one put back made a dead one look
    alive for that long."""

    def __init__(self):
        self.seen: dict[Path, tuple[tuple, float]] = {}

    def quiet(self, path: Path, now: float, new: bool = True) -> float | None:
        """Seconds since `path` last changed, or None if it isn't there. One seen for
        the first time counts as just changed if `new` (ours: made for this request),
        else only once it changes (another's may be a dead helper's)."""
        mark = _mark(path)
        if mark is None:
            self.seen.pop(path, None)
            return None
        last = self.seen.get(path)
        if last is None:
            self.seen[path] = last = (mark, now if new else float("-inf"))
        elif last[0] != mark:
            self.seen[path] = last = (mark, now)
        return now - last[1]

    def busy(self, ours: Path, now: float) -> bool:
        """The helper is at work on some other request (another's heartbeat beats)."""
        try:
            others = [p for p in results_dir().glob("*.ack") if p != ours]
        except OSError:
            return False
        return any((self.quiet(p, now, new=False) or 0.0) <= STALE_S for p in others)


def _mark(path: Path) -> tuple | None:
    """What a heartbeat says and when it was written, or None if it isn't there."""
    try:
        with open(path, "rb") as f:
            text = f.read(64)
        return text, os.stat(path).st_mtime_ns
    except OSError:
        return None


def _age(path: Path) -> float | None:
    """Seconds since `path` was written, or None if it isn't there."""
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return None


def _result(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def _forget(path: Path):
    try:
        path.unlink()
    except OSError:
        pass


# ---------------------------------------------------------------------- requests

def allowed(args: list[str]) -> bool:
    """The commands the helper runs: the admin steps, each with a mic GUID at most."""
    if args in (["uninstall"], ["remove-all"]):
        return True
    if len(args) == 2 and args[0] in ("install", "reinstall", "cleanup", "uninstall"):
        return bool(_GUID.fullmatch(args[1]))
    return False


def parse(raw: bytes) -> list[str] | None:
    """A request file's command, or None if it isn't one the helper runs."""
    if len(raw) > MAX_REQUEST:
        return None
    try:
        args = raw.decode("ascii").split()
    except UnicodeDecodeError:
        return None
    return args if allowed(args) else None


def _take(path: Path) -> list[str] | None:
    """Read one request and delete it. The folder is the user's: the entry must be a
    plain file of its own (no link, no second name), checked on the handle it is read
    from, so it can't be swapped in between. What it says is only ever matched against
    allowed(), never shown or used as a path. The folder itself could be turned into a
    link too (it's empty most of the time): the request is opened relative to a handle
    to the folder that was checked to be a real one, and deleted through its own
    handle once checked, never by name (safefs). One the app is still writing (it's
    open: ask() writes it in one go) is waited for a moment, never refused."""
    for _try in range(BUSY_TRIES):
        try:
            with safefs.Folder(path.parent) as folder:
                raw = folder.take(path.name, MAX_REQUEST)
        except OSError as e:
            if getattr(e, "winerror", None) == 32 and _try < BUSY_TRIES - 1:   # in use
                time.sleep(BUSY_WAIT_S)
                continue
            raw = None
        return None if raw is None else parse(raw)
    return None


def _requests() -> list[Path]:
    """The request files waiting, listed through a checked handle to the folder. One
    that is a link (someone turned it into one) is removed, never looked into: the
    accounts it's set up for may write there, so it's made again as install_helper
    makes it."""
    folder = requests_dir()
    try:
        with safefs.Folder(folder) as d:
            return [folder / n for n in d.names() if n.endswith(".req")]
    except safefs.NotPlain:
        log.warning("mic helper: the requests folder was a link: removed")
        from soundboard.mic import directmic as dm
        dm._secure_dir(folder, _queue_sddl(helper_users()))
        return []


def _drop(path: Path):
    """Remove a request file that isn't one (a wrong name), through the folder's handle."""
    try:
        with safefs.Folder(path.parent) as folder:
            folder.delete(path.name)
    except OSError:
        pass


def _answer(rid: str, code: int):
    out = results_dir()
    tmp = out / f"{rid}.tmp"
    tmp.write_text(str(code), encoding="ascii")
    os.replace(tmp, out / f"{rid}.res")


class _Heartbeat:
    """`<id>.ack` in results, rewritten every BEAT_S while the helper works on that
    request: the app keeps waiting while it changes, and knows the helper died
    (killed, crashed) when it stops. Gone once the answer is there. Each beat writes a
    new count (what the app watches since version 8) in place, which also moves the
    file's time (what an app of version 7 or older watches)."""

    def __init__(self, rid: str):
        self.path = results_dir() / f"{rid}.ack"
        self.stop = threading.Event()
        self.count = 0
        tmp = self.path.with_suffix(".atmp")
        tmp.write_bytes(self._text())
        os.replace(tmp, self.path)
        self.thread = threading.Thread(target=self._beat, name="mic-helper-beat",
                                       daemon=True)
        self.thread.start()

    def _text(self) -> bytes:
        return f"{self.count} {time.time():.3f}".encode("ascii")

    def _beat(self):
        while not self.stop.wait(BEAT_S):
            self.count += 1
            try:   # (in place: the app may be reading it, which a replace would refuse)
                with open(self.path, "r+b") as f:
                    text = self._text()
                    f.write(text)
                    f.truncate(len(text))
            except OSError:
                try:
                    os.utime(self.path)
                except OSError:
                    pass

    def end(self):
        self.stop.set()
        self.thread.join(5.0)
        _forget(self.path)


SEEN = "prune.seen"   # in results: when this helper first saw each file there


def _read_seen(path: Path) -> dict[str, float]:
    seen = {}
    try:
        for line in path.read_text(encoding="ascii").splitlines():
            name, _, when = line.partition(" ")
            seen[name] = float(when)
    except (OSError, ValueError, UnicodeDecodeError):
        pass
    return seen


def _prune(now: float, mono: float | None = None):
    """Remove results nobody read (the app gave up on them): ones older than
    RESULT_KEEP_S by the wall clock AND seen by an earlier run that long ago by
    time.monotonic() (the whole PC's, not moved by a clock change; lower after a
    restart, when nobody waits on anything from before). A clock put forward an hour
    never takes an answer the app is still about to read."""
    mono = time.monotonic() if mono is None else mono
    folder = results_dir()
    ledger = folder / SEEN
    seen, keep = _read_seen(ledger), {}
    try:
        files = [p for p in folder.iterdir() if p.name != SEEN]
    except OSError:
        return
    for p in files:
        first = seen.get(p.name, mono)
        try:
            if (now - p.stat().st_mtime > RESULT_KEEP_S
                    and (mono - first > RESULT_KEEP_S or first > mono)):
                p.unlink()
                continue
        except OSError:
            continue
        keep[p.name] = first
    try:
        tmp = folder / f"{SEEN}.tmp"
        tmp.write_text("".join(f"{n} {t:.3f}\n" for n, t in keep.items()),
                       encoding="ascii")
        os.replace(tmp, ledger)
    except OSError:
        pass


def serve(run=None) -> int:
    """The helper (as SYSTEM, started by the task): do every request there is, then
    exit. `run`: the admin command runner (directmic.cli)."""
    if run is None:
        from soundboard.mic import directmic
        run = directmic.cli
    _prune(time.time())
    for _round in range(50):   # (requests keep coming: the task's next run takes them)
        try:
            # (_age: one the app gave up on and deleted meanwhile never stops the rest)
            found = sorted(_requests(), key=lambda p: -(_age(p) or 0.0))
        except OSError:
            return 0
        if not found:
            return 0
        for req in found:
            rid = req.stem
            if not _REQUEST.fullmatch(rid):
                _drop(req)
                continue
            beat = _Heartbeat(rid)   # (before the request goes: never neither)
            try:
                args = _take(req)
                if args is None:
                    log.warning("mic helper: refused a request")
                    code = 2
                else:
                    try:
                        code = run(args)
                    except Exception:  # noqa: BLE001 - every request gets an answer
                        log.exception("mic helper: %s failed", args[:1])
                        code = 1
                _answer(rid, code)   # (before the heartbeat goes: never neither)
            finally:
                beat.end()
            if args == ["remove-all"] and code == 0:
                time.sleep(2.0)   # the app reads the answer first: removing takes it too
                remove_helper()
                return 0
    return 0


# ---------------------------------------------------------------------- admin side

def _token_sid() -> str | None:
    """The SID of the account this process runs as."""
    from ctypes import wintypes
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                        ctypes.POINTER(wintypes.HANDLE)]
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                           wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        return None
    try:
        buf = ctypes.create_string_buffer(256)
        size = wintypes.DWORD()
        if not advapi.GetTokenInformation(token, 1, buf, 256, ctypes.byref(size)):   # TokenUser
            return None
        sid = ctypes.c_void_p.from_buffer(buf).value   # TOKEN_USER.User.Sid
        text = ctypes.c_wchar_p()
        if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            return None
        value = text.value
        kernel.LocalFree(text)
        return value
    finally:
        kernel.CloseHandle(token)


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _sids(sids: str | list[str]) -> list[str]:
    sids = [sids] if isinstance(sids, str) else list(sids)
    for sid in sids:
        if not _SID.fullmatch(sid):
            raise ValueError(f"not a user account: {sid}")
    if not sids:
        raise ValueError("no account")
    return sids


def task_sddl(sids: str | list[str]) -> str:
    """Who may see and start the task: admins, and the accounts `sids`."""
    return "D:P(A;;FA;;;SY)(A;;FA;;;BA)" + "".join(f"(A;;GRGX;;;{s})" for s in _sids(sids))


def task_xml(exe: Path, sids: str | list[str], arguments: str = SERVE,
             workdir: Path | None = None) -> str:
    """The task: runs `exe --serve` as SYSTEM when started, never on its own; `sids`
    (the accounts that set it up) may start it, as may admins. (`arguments` and
    `workdir`: the CI test's task runs the helper from source.)"""
    sddl = task_sddl(sids)
    cwd = f"\n      <WorkingDirectory>{_escape(str(workdir))}</WorkingDirectory>" \
        if workdir else ""
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.3" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>Onion Board</Author>
    <Description>Puts Onion Board's mic effect on or off a microphone when the app asks. \
It never runs on its own.</Description>
    <SecurityDescriptor>{sddl}</SecurityDescriptor>
  </RegistrationInfo>
  <Triggers />
  <Principals>
    <Principal id="Author">
      <UserId>S-1-5-18</UserId>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>Queue</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>true</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT15M</ExecutionTimeLimit>
    <Priority>5</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>"{_escape(str(exe))}"</Command>
      <Arguments>{_escape(arguments)}</Arguments>{cwd}
    </Exec>
  </Actions>
</Task>
"""


def _queue_sddl(sids: str | list[str]) -> str:
    """requests: the accounts `sids` make files there, and each changes (and deletes)
    only its own (CREATOR OWNER), nothing else; the rest of the queue is admins'
    (users read)."""
    from soundboard.mic import directmic as dm
    return dm._BASE_SDDL + "".join(f"(A;;{dm._FOLDER_WRITE};;;{s})" for s in _sids(sids)) \
        + f"(A;OICIIO;{dm._MODIFY};;;CO)"


def _has_profile(sid: str) -> bool:
    """`sid` is an account with a profile on this PC (it has signed in here)."""
    import winreg
    try:
        winreg.CloseKey(winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            rf"SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\{sid}"))
        return True
    except OSError:
        return False


def helper_users(new: str | None = None) -> list[str]:
    """The accounts the helper is for: the ones it was set up for before (that are
    still accounts here) and `new`. Each one that set it up keeps it: another account
    setting it up never takes it away from the first."""
    try:
        before = (helper_dir() / USERS).read_text(encoding="ascii").split()
    except (OSError, UnicodeDecodeError):
        before = []
    users: list[str] = []
    for sid in [*before, new]:
        if sid and _SID.fullmatch(sid) and sid not in users and _has_profile(sid):
            users.append(sid)
    return users


def verify_task(exe: Path, sids: list[str], arguments: str = SERVE) -> bool:
    """The task registered really is ours: run as SYSTEM, no trigger, our program,
    and only admins and `sids` may start it (Windows took the XML's security
    descriptor), read back from Task Scheduler."""
    import xml.etree.ElementTree as ET
    out: list[str] = []
    if _schtasks("/query", "/tn", TASK, "/xml", out=out) != 0 or not out:
        return False
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    try:
        text = out[0]
        root = ET.fromstring(text[text.index("<Task"):])
    except (ValueError, ET.ParseError):
        return False

    def one(path: str) -> str | None:
        node = root.find(path, ns)
        return None if node is None else (node.text or "").strip()
    triggers, actions = root.find("t:Triggers", ns), root.find("t:Actions", ns)
    return (one("t:RegistrationInfo/t:SecurityDescriptor") == task_sddl(sids)
            and one("t:Principals/t:Principal/t:UserId") == "S-1-5-18"
            and (triggers is None or not list(triggers))
            and actions is not None and len(list(actions)) == 1
            and one("t:Actions/t:Exec/t:Command") == f'"{exe}"'
            and one("t:Actions/t:Exec/t:Arguments") == arguments)


def _build_files(folder: Path) -> dict[str, Path]:
    """A helper folder's files by relative path, without what install_helper writes."""
    return {p.relative_to(folder).as_posix(): p for p in folder.rglob("*")
            if p.is_file() and p.relative_to(folder).as_posix() not in (USERS, "task.xml")}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(folder: Path):
    """scripts/buildtools/build_michelper.py: every file of the build in `folder` with its sha256,
    so a changed, added or missing file is noticed before it runs as SYSTEM."""
    files = {k: v for k, v in _build_files(folder).items() if k != MANIFEST}
    (folder / MANIFEST).write_text(
        "".join(f"{_sha256(path)} {name}\n" for name, path in sorted(files.items())),
        encoding="utf-8")


def verify_build(folder: Path, required: bool = True) -> bool:
    """`folder`'s files are exactly the ones its manifest lists, byte for byte. Without
    a manifest: `not required` (a helper from before it). It finds damage (a file a
    virus scanner took or changed, a half-done copy) and a build changed after it was
    made; who could also rewrite the manifest could change the app itself anyway."""
    try:
        lines = (folder / MANIFEST).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return not required
    except (OSError, UnicodeDecodeError):
        return False
    want: dict[str, str] = {}
    for line in lines:
        sha, _, name = line.partition(" ")
        if not re.fullmatch(r"[0-9a-f]{64}", sha) or not name or name in want:
            return False
        want[name] = sha
    try:
        have = {k: v for k, v in _build_files(folder).items() if k != MANIFEST}
        return have.keys() == want.keys() and all(
            _sha256(have[name]) == sha for name, sha in want.items())
    except OSError:
        return False


def _same_build(src: Path, dest: Path) -> bool:
    """`dest` holds exactly `src`'s helper build, byte for byte. The stamp alone isn't
    enough: it names the helper version and effect DLL, not how the exe was packed (a
    rebuild can change that) or whether a file of it went missing (a virus scanner)."""
    import filecmp
    try:
        have, want = _build_files(dest), _build_files(src)
        return have.keys() == want.keys() and all(
            filecmp.cmp(want[name], have[name], shallow=False) for name in want)
    except OSError:
        return False


def install_helper(user: str | None = None) -> bool:
    """Admin step (the app's elevated copy): put this app's helper build in Program
    Files and register its task for `user` (the account that asked, from the app's
    `--for`: checked here) or else the account running this, and every account it was
    set up for before. False (logged) when this copy has no helper build or it
    couldn't: the mic effect works anyway, with Windows' prompt each time. Never
    raises: it runs after the effect went on, and an error here made a set-up that
    worked exit with code 1, which the app reported as failed."""
    try:
        return _install_helper(user)
    except Exception:  # noqa: BLE001 - the effect itself is set up already
        log.exception("mic helper: setting it up failed")
        return False


def _install_helper(user: str | None) -> bool:
    from soundboard.mic import directmic as dm
    src = bundled_helper()
    if is_helper() or not (src / EXE_NAME).is_file() or _read_stamp(src) is None:
        return False
    if not verify_build(src):
        log.warning("mic helper: this app's helper build doesn't match its manifest "
                    "(%s): not set up", src)
        return False
    sid = user if user is not None else _token_sid()
    if sid is None or not _SID.fullmatch(sid) or not _has_profile(sid):
        log.info("mic helper: not set up for this account (%s)", sid)
        return False
    try:
        users = helper_users(sid)
        dest = helper_dir()
        if not _same_build(src, dest):
            new, old = dest.with_name(dest.name + ".new"), dest.with_name(dest.name + ".old")
            for d in (new, old):
                if d.exists():
                    shutil.rmtree(d, ignore_errors=True)
            shutil.copytree(src, new)   # whole, then in place
            if not verify_build(new):   # (changed meanwhile, or a bad copy)
                log.warning("mic helper: the copy doesn't match the manifest: not set up")
                shutil.rmtree(new, ignore_errors=True)
                return False
            if dest.exists():
                os.replace(dest, old)
            os.replace(new, dest)
            shutil.rmtree(old, ignore_errors=True)
        # an uninstall's removal left it on Windows' list for the next restart (it ran
        # from it): without this, a reinstall before that restart loses the helper then
        dm._unmark([dest, *dest.rglob("*")])
        q = queue_dir()
        dm._secure_dir(q, dm._BASE_SDDL)
        dm._secure_dir(results_dir(), dm._BASE_SDDL)
        dm._secure_dir(requests_dir(), _queue_sddl(users))
        (dest / USERS).write_text("\n".join(users) + "\n", encoding="ascii")
        xml = dest / "task.xml"
        xml.write_text(task_xml(dest / EXE_NAME, users), encoding="utf-16")
        try:
            code = _schtasks("/create", "/tn", TASK, "/xml", str(xml), "/f")
        finally:
            _forget(xml)
        if code != 0:
            log.warning("mic helper: registering its task failed (%s)", code)
            return False
        if not verify_task(dest / EXE_NAME, users):
            log.warning("mic helper: the task Windows registered isn't the one asked "
                        "for: removed")
            _schtasks("/delete", "/tn", TASK, "/f")
            return False
    except Exception:  # noqa: BLE001 - the effect itself is set up already
        log.exception("mic helper: setting it up failed")
        return False
    log.info("mic helper set up for %s", ", ".join(users))
    return True


def remove_helper():
    """Take the helper away (the app is being uninstalled): its task and files now;
    files in use (the helper removing itself runs from them) at the next restart."""
    from soundboard.mic import directmic
    _schtasks("/delete", "/tn", TASK, "/f")
    for d in (*_helper_dirs(), queue_dir()):
        if d.exists():
            directmic._remove(d)
    log.info("mic helper removed")


def main(argv: list[str]) -> int:
    """obmichelper.exe: `--serve` (the task), or `--selftest`
    (scripts/buildtools/build_michelper.py: the build loads the admin part and carries its
    effect DLL; 0 if so)."""
    if argv == ["--selftest"]:
        from soundboard.mic import directmic
        return 0 if directmic.bundled_dll().is_file() and is_helper() else 3
    if argv != [SERVE]:
        return 2
    from soundboard.mic import directmic
    # SYSTEM never follows a junction a non-admin made (Windows 11; everything this
    # process opens is admins' anyway: Program Files, the secured ProgramData folders)
    safefs.guard()
    directmic.secure_data_dirs()   # before anything is written under ProgramData
    directmic.log_to(directmic.data_dir().parent / "michelper.log")
    try:
        return serve()
    except Exception:  # noqa: BLE001
        log.exception("mic helper failed")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
