"""The mic helper: the mic effect (soundboard/directmic.py) put on or taken off a mic
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
half-way. Requests are untrusted: only the commands in `allowed()` run, with a mic
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

log = logging.getLogger(__name__)

# Bump it when the admin part changes (directmic.py from "admin part" to "the app's
# side", or this file); tests/test_michelper.py fails until it is. A newer helper is
# put in place by the next admin step that asks anyway: only another effect DLL makes
# the app ask (so the helper never adds a prompt the app wouldn't have had).
HELPER_VERSION = 5
# The oldest helper the app still uses. Raise it (to HELPER_VERSION) only when the
# helpers out there have a bug that matters: the app then asks Windows once more, and
# that prompt puts this version's helper in place.
MIN_HELPER_VERSION = 2
TASK = r"\Onion Board\Mic helper"
EXE_NAME = "obmichelper.exe"
STAMP = "stamp.txt"
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
RESULT_KEEP_S = 3600.0
START_S = 20.0   # the task didn't pick a request up in this long: it isn't working
BEAT_S = 2.0     # the helper touches a request's .ack this often while on it
STALE_S = 30.0   # ...so an .ack this old means it died half-way (killed, crashed)
HARD_S = 960.0   # the task's own time limit (PT15M) and a minute: gone by then


def helper_dir() -> Path:
    return Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Onion Board Mic Helper"


def helper_exe() -> Path:
    return helper_dir() / EXE_NAME


def queue_dir() -> Path:
    from soundboard import directmic
    return directmic.data_dir().parent / "MicHelper"


def requests_dir() -> Path:
    return queue_dir() / "requests"


def results_dir() -> Path:
    return queue_dir() / "results"


def bundled_helper() -> Path:
    """The helper build this app carries: in the frozen app, or what
    scripts/build_michelper.py built when run from source."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "michelper"
    return Path(__file__).resolve().parent.parent / "build" / "michelper" / "obmichelper"


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
        r = subprocess.run(["schtasks", *args], capture_output=True, timeout=timeout,
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
    too) or its task. Uninstalling the app takes all of it away."""
    return any(d.exists() for d in _helper_dirs()) or _schtasks("/query", "/tn", TASK) == 0


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


def ready(same_dll: bool = True) -> bool:
    """A helper this app can use: at least MIN_HELPER_VERSION and, for setting up
    (`same_dll`), carrying the same effect DLL as this app (an older one would put an
    older effect on the mic). An older helper otherwise is fine: the next admin step
    that asks anyway updates it. Runs a process: not on the UI thread."""
    have = _read_stamp(helper_dir())
    ok = _version_of(have) >= MIN_HELPER_VERSION
    if ok and same_dll:
        want = _dll_of(_read_stamp(bundled_helper()))
        ok = want is not None and _dll_of(have) == want
    ok = ok and installed()
    _known[same_dll] = ok
    return ok


_known: dict[bool, bool] = {}   # ready()'s last answers, for the UI thread


def known(same_dll: bool = True) -> bool | None:
    """ready()'s last answer (None: not asked yet), for the UI thread."""
    return _known.get(same_dll)


def will_ask(setting_up: bool = True) -> bool:
    """Will Windows' admin prompt come up for the next mic step (`setting_up`: putting
    the effect on, else taking it off)? From ready()'s last answer, so the UI thread can
    ask: not known yet counts as yes (the texts then say to click Yes)."""
    return _known.get(setting_up, _known.get(True) if not setting_up else None) is not True


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
    start = time.monotonic()
    while True:
        waited = time.monotonic() - start
        code = _result(res)
        if code is not None:
            _forget(res)   # (admins only: stays; the helper clears old ones)
            return code
        beat = _age(ack)
        if beat is not None:
            # at work: wait however long it takes (Windows' prompt now would find it
            # holding the lock and fail), unless its heartbeat stopped
            if beat > STALE_S or waited > HARD_S:
                log.warning("the mic helper stopped half-way (no heartbeat for %.0f s)",
                            beat)
                _forget(req)   # (if it died before taking it: never done later too)
                return None
        elif req.exists():
            if waited > START_S:
                log.info("the mic helper didn't pick the request up")
                _forget(req)
                return None
        elif waited > wait_s:   # taken, no heartbeat: a helper older than 5, or gone
            log.info("the mic helper didn't answer in %.0f s", wait_s)
            return None
        time.sleep(0.1)


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
    allowed(), never shown or used as a path."""
    try:
        raw = _read_plain(path)
    except OSError:
        raw = None
    finally:
        _forget(path)
    return None if raw is None else parse(raw)


def _read_plain(path: Path) -> bytes | None:
    """`path`'s bytes if it is a plain file of its own of up to MAX_REQUEST, else None.
    On Windows it is opened without following a link, nobody else may open it
    meanwhile, and it goes when closed."""
    if os.name != "nt":
        st = os.lstat(path)
        if not os.path.isfile(path) or os.path.islink(path) or st.st_nlink != 1 \
                or st.st_size > MAX_REQUEST:
            return None
        return path.read_bytes()
    from ctypes import wintypes

    class Info(ctypes.Structure):   # BY_HANDLE_FILE_INFORMATION
        _fields_ = [("attributes", wintypes.DWORD), ("times", wintypes.DWORD * 6),
                    ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD),
                    ("size_low", wintypes.DWORD), ("links", wintypes.DWORD),
                    ("index", wintypes.DWORD * 2)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.HANDLE]
    kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(Info)]
    kernel.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    # GENERIC_READ | DELETE, no sharing, OPEN_EXISTING,
    # FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_DELETE_ON_CLOSE
    h = kernel.CreateFileW(str(path), 0x80010000, 0, None, 3, 0x00200000 | 0x04000000,
                           None)
    if h is None or h == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        info = Info()
        if not kernel.GetFileInformationByHandle(h, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        size = (info.size_high << 32) | info.size_low
        # FILE_ATTRIBUTE_REPARSE_POINT | FILE_ATTRIBUTE_DIRECTORY
        if info.attributes & 0x410 or info.links != 1 or size > MAX_REQUEST:
            return None
        buf = ctypes.create_string_buffer(MAX_REQUEST + 1)
        got = wintypes.DWORD()
        if not kernel.ReadFile(h, buf, MAX_REQUEST + 1, ctypes.byref(got), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return buf.raw[:got.value]
    finally:
        kernel.CloseHandle(h)


def _answer(rid: str, code: int):
    out = results_dir()
    tmp = out / f"{rid}.tmp"
    tmp.write_text(str(code), encoding="ascii")
    os.replace(tmp, out / f"{rid}.res")


class _Heartbeat:
    """`<id>.ack` in results, touched every BEAT_S while the helper works on that
    request: the app keeps waiting while it is fresh, and knows the helper died
    (killed, crashed) when it goes stale. Gone once the answer is there."""

    def __init__(self, rid: str):
        self.path = results_dir() / f"{rid}.ack"
        self.stop = threading.Event()
        tmp = self.path.with_suffix(".atmp")
        tmp.write_bytes(b"")
        os.replace(tmp, self.path)
        self.thread = threading.Thread(target=self._beat, name="mic-helper-beat",
                                       daemon=True)
        self.thread.start()

    def _beat(self):
        while not self.stop.wait(BEAT_S):
            try:
                os.utime(self.path)
            except OSError:
                pass

    def end(self):
        self.stop.set()
        self.thread.join(5.0)
        _forget(self.path)


def _prune(now: float):
    try:
        for p in results_dir().iterdir():
            try:
                if now - p.stat().st_mtime > RESULT_KEEP_S:
                    p.unlink()
            except OSError:
                pass
    except OSError:
        pass


def serve(run=None) -> int:
    """The helper (as SYSTEM, started by the task): do every request there is, then
    exit. `run`: the admin command runner (directmic.cli)."""
    if run is None:
        from soundboard import directmic
        run = directmic.cli
    _prune(time.time())
    for _round in range(50):   # (requests keep coming: the task's next run takes them)
        try:
            found = sorted((p for p in requests_dir().glob("*.req")),
                           key=lambda p: p.stat().st_mtime)
        except OSError:
            return 0
        if not found:
            return 0
        for req in found:
            rid = req.stem
            if not _REQUEST.fullmatch(rid):
                _forget(req)
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
    from soundboard import directmic as dm
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


def install_helper(user: str | None = None) -> bool:
    """Admin step (the app's elevated copy): put this app's helper build in Program
    Files and register its task for `user` (the account that asked, from the app's
    `--for`: checked here) or else the account running this, and every account it was
    set up for before. False (logged) when this copy has no helper build or it
    couldn't: the mic effect works anyway, with Windows' prompt each time."""
    from soundboard import directmic as dm
    src = bundled_helper()
    if is_helper() or not (src / EXE_NAME).is_file() or _read_stamp(src) is None:
        return False
    sid = user if user is not None else _token_sid()
    if sid is None or not _SID.fullmatch(sid) or not _has_profile(sid):
        log.info("mic helper: not set up for this account (%s)", sid)
        return False
    try:
        users = helper_users(sid)
        dest = helper_dir()
        if _read_stamp(dest) != _read_stamp(src) or not (dest / EXE_NAME).is_file():
            new, old = dest.with_name(dest.name + ".new"), dest.with_name(dest.name + ".old")
            for d in (new, old):
                if d.exists():
                    shutil.rmtree(d, ignore_errors=True)
            shutil.copytree(src, new)   # whole, then in place
            if dest.exists():
                os.replace(dest, old)
            os.replace(new, dest)
            shutil.rmtree(old, ignore_errors=True)
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
    from soundboard import directmic
    _schtasks("/delete", "/tn", TASK, "/f")
    for d in (*_helper_dirs(), queue_dir()):
        if d.exists():
            directmic._remove(d)
    log.info("mic helper removed")


def main(argv: list[str]) -> int:
    """obmichelper.exe: `--serve` (the task), or `--selftest` (scripts/build_michelper.py:
    the build loads the admin part and carries its effect DLL; 0 if so)."""
    if argv == ["--selftest"]:
        from soundboard import directmic
        return 0 if directmic.bundled_dll().is_file() and is_helper() else 3
    if argv != [SERVE]:
        return 2
    from soundboard import directmic
    directmic.secure_data_dirs()   # before anything is written under ProgramData
    directmic.log_to(directmic.data_dir().parent / "michelper.log")
    try:
        return serve()
    except Exception:  # noqa: BLE001
        log.exception("mic helper failed")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
