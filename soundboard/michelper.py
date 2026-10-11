"""The mic helper: the mic effect (soundboard/directmic.py) put on or taken off a mic
without Windows' admin prompt every time.

Putting the effect on a mic needs admin (the mic's settings belong to Windows, and its
audio restarts). Without the helper every set-up, repair, change of mic and removal
asked. Now the first admin step (one prompt, the same as before) also installs:

- obmichelper.exe, a small build of the admin part only (no Qt, no numpy) with its own
  copy of the effect DLL, in Program Files\\Onion Board Mic Helper (admins only: nobody
  else can change what runs);
- a scheduled task, TASK, that runs it as SYSTEM when asked. No trigger: it never runs
  by itself, and nothing stays in the background. Only the account that set it up
  (and admins) may start it.

The app asks by writing a request file (one line: a `--direct-mic` admin command) into
%ProgramData%\\OnionBoard\\MicHelper\\requests and starting the task; the helper does
every request it finds and writes each one's exit code into ...\\results (admins only,
so a planted link can't steer what SYSTEM writes). Requests are untrusted: only the
commands in `allowed()` run, with a mic GUID as their only argument. The helper
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
import time
from pathlib import Path

log = logging.getLogger(__name__)

# Bump it when the admin part changes (directmic.py from "admin part" to "the app's
# side", or this file); tests/test_michelper.py fails until it is. A newer helper is
# put in place by the next admin step that asks anyway: only another effect DLL makes
# the app ask (so the helper never adds a prompt the app wouldn't have had).
HELPER_VERSION = 3
# The oldest helper the app still uses. Raise it (to HELPER_VERSION) only when the
# helpers out there have a bug that matters: the app then asks Windows once more, and
# that prompt puts this version's helper in place.
MIN_HELPER_VERSION = 2
TASK = r"\Onion Board\Mic helper"
EXE_NAME = "obmichelper.exe"
STAMP = "stamp.txt"
SERVE = "--serve"
_CREATE_NO_WINDOW = 0x08000000
_GUID = re.compile(r"\{[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                   r"[0-9a-fA-F]{12}\}")
_SID = re.compile(r"S-1-5-21(-\d{1,10}){3,4}")   # a user account (domain or local)
_REQUEST = re.compile(r"[0-9a-f]{32}")
MAX_REQUEST = 256
RESULT_KEEP_S = 3600.0
START_S = 20.0   # the task didn't pick a request up in this long: it isn't working


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

def _schtasks(*args: str, timeout: float = 30.0) -> int:
    try:
        return subprocess.run(["schtasks", *args], capture_output=True, timeout=timeout,
                              creationflags=_CREATE_NO_WINDOW).returncode
    except (OSError, subprocess.SubprocessError):
        return -1


def installed() -> bool:
    """A helper is there (maybe an older one): its program and its task."""
    return helper_exe().is_file() and _schtasks("/query", "/tn", TASK) == 0


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
    if _version_of(have) < MIN_HELPER_VERSION:
        return False
    if same_dll:
        want = _dll_of(_read_stamp(bundled_helper()))
        if want is None or _dll_of(have) != want:
            return False
    return installed()


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
    start = time.monotonic()
    while time.monotonic() - start < wait_s:
        code = _result(res)
        if code is not None:
            _forget(res)   # (admins only: stays; the helper clears old ones)
            return code
        if req.exists() and time.monotonic() - start > START_S:
            log.info("the mic helper didn't pick the request up")
            _forget(req)
            return None
        time.sleep(0.1)
    log.info("the mic helper didn't answer in %.0f s", wait_s)
    _forget(req)
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
    plain file of its own (no link, no second name). What it says is only ever matched
    against allowed(), never shown or used as a path."""
    try:
        st = os.lstat(path)
        plain = not getattr(st, "st_file_attributes", 0) & 0x400 and st.st_nlink == 1 \
            and st.st_size <= MAX_REQUEST and not path.is_dir()
        raw = path.read_bytes()[:MAX_REQUEST + 1] if plain else b""
    except OSError:
        return None
    finally:
        _forget(path)
    return parse(raw) if plain else None


def _answer(rid: str, code: int):
    out = results_dir()
    tmp = out / f"{rid}.tmp"
    tmp.write_text(str(code), encoding="ascii")
    os.replace(tmp, out / f"{rid}.res")


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
            args = _take(req)
            if args is None:
                log.warning("mic helper: refused a request")
                _answer(rid, 2)
                continue
            try:
                code = run(args)
            except Exception:  # noqa: BLE001 - every request gets an answer
                log.exception("mic helper: %s failed", args[:1])
                code = 1
            _answer(rid, code)
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


def task_xml(exe: Path, sid: str) -> str:
    """The task: runs `exe --serve` as SYSTEM when started, never on its own; `sid` (the
    account that set it up) may start it, as may admins."""
    if not _SID.fullmatch(sid):
        raise ValueError(f"not a user account: {sid}")
    sddl = f"D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;GRGX;;;{sid})"
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
      <Arguments>{SERVE}</Arguments>
    </Exec>
  </Actions>
</Task>
"""


def _queue_sddl(sid: str) -> str:
    """requests: `sid` makes files there (and changes its own), nothing else; the
    rest of the queue is admins' (users read)."""
    from soundboard import directmic as dm
    return dm._BASE_SDDL + f"(A;;{dm._FOLDER_WRITE};;;{sid})(A;OICIIO;{dm._MODIFY};;;{sid})"


def install_helper() -> bool:
    """Admin step (the app's elevated copy): put this app's helper build in Program
    Files and register its task for the account running this. False (logged) when this
    copy has no helper build or it couldn't: the mic effect works anyway, with
    Windows' prompt each time."""
    from soundboard import directmic as dm
    src = bundled_helper()
    if is_helper() or not (src / EXE_NAME).is_file() or _read_stamp(src) is None:
        return False
    sid = _token_sid()
    if sid is None or not _SID.fullmatch(sid):
        log.info("mic helper: not set up for this account (%s)", sid)
        return False
    try:
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
        dm._secure_dir(requests_dir(), _queue_sddl(sid))
        xml = dest / "task.xml"
        xml.write_text(task_xml(dest / EXE_NAME, sid), encoding="utf-16")
        try:
            code = _schtasks("/create", "/tn", TASK, "/xml", str(xml), "/f")
        finally:
            _forget(xml)
        if code != 0:
            log.warning("mic helper: registering its task failed (%s)", code)
            return False
    except Exception:  # noqa: BLE001 - the effect itself is set up already
        log.exception("mic helper: setting it up failed")
        return False
    log.info("mic helper set up for %s", sid)
    return True


def remove_helper():
    """Take the helper away (the app is being uninstalled): its task and files now;
    files in use (the helper removing itself runs from them) at the next restart."""
    from soundboard import directmic
    _schtasks("/delete", "/tn", TASK, "/f")
    for d in (helper_dir(), queue_dir()):
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
    logging.basicConfig(filename=str(directmic.data_dir().parent / "michelper.log"),
                        level=logging.INFO, format="%(asctime)s %(message)s")
    try:
        return serve()
    except Exception:  # noqa: BLE001
        log.exception("mic helper failed")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
