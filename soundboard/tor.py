"""The app's own Tor (Settings > Connection > Tor).

tor.exe (the Tor Expert Bundle, which the app doesn't ship: soundboard.torget downloads
it into %APPDATA%\\OnionBoard\\tor\\bin when the user presses Get Tor or ticks the
installer's box; from source, scripts/fetch_tor.py's vendor/tor works too) runs only
while the Connection setting is Tor and something has needed the network. It's a
SOCKS proxy on 127.0.0.1 that soundboard.net hands every connection to
(net.set_tor_gate); until Tor has finished connecting ("bootstrapping") a connection
waits, then fails. Nothing ever goes direct instead.

  * torrc and Tor's data live in %APPDATA%\\OnionBoard\\tor. Both ports are "auto" and
    read back (the control port from ControlPortWriteToFile, the SOCKS port over the
    control connection), so nothing clashes with another Tor on this PC.
  * Tor is held three ways so it never outlives the app: a Windows job object that
    kills it when the app's handle closes (a crash included), TAKEOWNERSHIP on the
    control connection, and __OwningControllerProcess.
  * The control port is spoken here directly (AUTHENTICATE with the cookie, GETINFO,
    SIGNAL): a few lines, so no stem.
  * "Hide that I'm using Tor": bridges through lyrebird. Snowflake (looks like a video
    call) by default, or obfs4 (looks like random bytes) with the bridge lines that
    ship in pt_config.json. Slower; for networks where Tor is blocked or noticed.
  * Tor logs at notice level with SafeLogging: no site names or addresses.
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

from soundboard import library, net, torget
from soundboard import errors

log = logging.getLogger(__name__)

OFF, STARTING, READY, FAILED = "off", "starting", "ready", "failed"
BRIDGES = ("", "snowflake", "obfs4")   # cfg.tor_bridges: "" = no bridges
DEFAULT_BRIDGE = "snowflake"
CONTROL_FILE_WAIT_S = 30.0    # tor.exe writing its control port after starting
BOOTSTRAP_TIMEOUT_S = 180.0   # straight to the Tor network
BRIDGE_BOOTSTRAP_TIMEOUT_S = 360.0   # Snowflake can take minutes
POLL_S = 0.5
RETRY_AFTER_FAIL_S = 10.0     # a request right after a failure gets that failure
NEWNYM_EVERY_S = 10.0         # tor ignores (delays) NEWNYM more often than this
STOP_WAIT_S = 3.0
STILL_MOVING_S = 60.0         # a request keeps waiting past its time while Tor progresses
LOG_LINES = 40


def bundle_dirs() -> list[Path]:
    """Where tor.exe may be, in order: the downloaded copy, then (from source only)
    vendor/tor from scripts/fetch_tor.py."""
    dirs = [torget.bin_dir()]
    if not hasattr(sys, "_MEIPASS"):
        dirs.append(Path(__file__).resolve().parent.parent / "vendor" / "tor")
    return dirs


def bundle_dir() -> Path:
    """tor.exe's folder: the first of bundle_dirs() that has it, else the download's."""
    for d in bundle_dirs():
        if (d / "tor.exe").is_file():
            return d
    return torget.bin_dir()


def tor_exe() -> Path | None:
    p = bundle_dir() / "tor.exe"
    return p if p.is_file() else None


def available() -> bool:
    return tor_exe() is not None


NOT_INSTALLED = ("Tor isn't on this PC yet: press Get Tor (Settings > Connection) "
                 "to download it." + (
                     "" if hasattr(sys, "_MEIPASS") else
                     " From source, scripts/fetch_tor.py also works."))


def data_root() -> Path:
    return library.APP_DIR / "tor"


# --------------------------------------------------------------------------- torrc

def _q(value) -> str:
    """A torrc value in quotes (paths may hold spaces, # or backslashes)."""
    s = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def load_pt_config(path: Path | None = None) -> dict:
    """pt_config.json from the bundle: the pluggable transports and the built-in
    bridge lines. {} when it's missing or unreadable."""
    path = path or bundle_dir() / "pluggable_transports" / "pt_config.json"
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def bridge_config(kind: str, pt: dict) -> list[str]:
    """The torrc lines for one kind of bridge ("snowflake" / "obfs4"). The transport's
    path is relative: tor.exe runs in its own folder, so a space in the install path
    (which torrc can't take there) doesn't matter. Raises ValueError if the bundle
    doesn't have that kind."""
    plugin_key = {"snowflake": "snowflake", "obfs4": "lyrebird"}.get(kind)
    plugin = (pt.get("pluggableTransports") or {}).get(plugin_key or "")
    lines = (pt.get("bridges") or {}).get(kind) or []
    if not plugin or not lines:
        raise ValueError(f"this copy of Tor has no {kind} bridges")
    plugin = plugin.replace("${pt_path}", "pluggable_transports\\")
    return ["UseBridges 1", plugin, *(f"Bridge {b}" for b in lines)]


def make_torrc(root: Path, bridges: str = "", pt: dict | None = None,
               owner_pid: int | None = None) -> str:
    """The torrc for Tor's data folder `root`. Client only, both ports on 127.0.0.1
    and picked by tor, cookie login, nothing that would log where connections go."""
    lines = [
        "# Written by Onion Board each time Tor starts: changes here are overwritten.",
        f"DataDirectory {_q(root / 'data')}",
        "SocksPort 127.0.0.1:auto",
        "ControlPort 127.0.0.1:auto",
        f"ControlPortWriteToFile {_q(root / 'control-port')}",
        "CookieAuthentication 1",
        f"CookieAuthFile {_q(root / 'data' / 'control_auth_cookie')}",
        "ClientOnly 1",
        "AvoidDiskWrites 1",
        "SafeLogging 1",
        "Log notice stdout",
        'GeoIPFile ""',
        'GeoIPv6File ""',
        "DormantCanceledByStartup 1",
    ]
    if owner_pid:
        lines.append(f"__OwningControllerProcess {int(owner_pid)}")
    if bridges:
        lines += bridge_config(bridges, pt if pt is not None else load_pt_config())
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- control port

class ControlError(OSError):
    """The control port said no, or stopped answering."""


_KV = re.compile(r'([A-Za-z_]+)=("(?:[^"\\]|\\.)*"|\S*)')


def parse_kv(text: str) -> dict[str, str]:
    """KEY=value KEY="quoted value" pairs, as in a bootstrap status line."""
    out = {}
    for k, v in _KV.findall(text):
        if v.startswith('"'):
            v = re.sub(r"\\(.)", r"\1", v[1:-1])
        out[k] = v
    return out


def parse_bootstrap(value: str) -> dict:
    """GETINFO status/bootstrap-phase, e.g.
    'NOTICE BOOTSTRAP PROGRESS=45 TAG=loading_descriptors SUMMARY="Loading relay
    descriptors"' -> {"progress": 45, "tag": ..., "summary": ..., "warning": ""}."""
    kv = parse_kv(value)
    try:
        progress = max(0, min(100, int(kv.get("PROGRESS", "0"))))
    except ValueError:
        progress = 0
    severity = value.split(" ", 1)[0] if value else ""
    return {"progress": progress, "tag": kv.get("TAG", ""), "summary": kv.get("SUMMARY", ""),
            "warning": kv.get("WARNING", "") if severity == "WARN" else ""}


def parse_getinfo(reply: list[tuple[str, str, str]]) -> dict[str, str]:
    """A GETINFO reply ((code, separator, text) lines, data blocks already joined)
    as {key: value}."""
    out = {}
    for _code, _sep, text in reply:
        if "=" in text:
            k, _, v = text.partition("=")
            out[k] = v
    return out


class ControlClient:
    """Just enough of Tor's control protocol: one command at a time, replies read
    whole (multi-line and data blocks), asynchronous 6xx events skipped."""

    def __init__(self, port: int, host: str = "127.0.0.1", timeout: float = 10.0):
        self.sock = socket.create_connection((host, port), timeout)
        self._buf = b""
        self._lock = threading.Lock()

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def _line(self) -> str:
        while b"\r\n" not in self._buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ControlError("Tor closed its control connection")
            self._buf += chunk
            if len(self._buf) > 1 << 20:
                raise ControlError("Tor's control port sent too much")
        line, _, self._buf = self._buf.partition(b"\r\n")
        return line.decode("utf-8", "replace")

    def _reply(self) -> list[tuple[str, str, str]]:
        lines = []
        while True:
            line = self._line()
            if len(line) < 4:
                raise ControlError(f"Tor's control port sent {line!r}")
            code, sep, text = line[:3], line[3], line[4:]
            if sep == "+":   # a data block, ended by a line holding "."
                data = []
                while (d := self._line()) != ".":
                    data.append(d[1:] if d.startswith(".") else d)
                text = text + "\n".join(data)
            if code.startswith("6"):   # an event we didn't ask for: not our reply
                if sep == " ":
                    lines = []
                continue
            lines.append((code, sep, text))
            if sep == " ":
                return lines

    def command(self, line: str) -> list[tuple[str, str, str]]:
        with self._lock:
            self.sock.sendall(line.encode() + b"\r\n")
            reply = self._reply()
        code = reply[-1][0]
        if not code.startswith("2"):
            raise ControlError(f"Tor said {code} {reply[-1][2]}")
        return reply

    def authenticate(self, cookie: bytes):
        self.command(f"AUTHENTICATE {cookie.hex()}")

    def getinfo(self, *keys: str) -> dict[str, str]:
        return parse_getinfo(self.command("GETINFO " + " ".join(keys)))

    def signal(self, name: str):
        self.command(f"SIGNAL {name}")

    def take_ownership(self):
        self.command("TAKEOWNERSHIP")


def read_control_port(path: Path) -> int | None:
    """ControlPortWriteToFile's 'PORT=127.0.0.1:9151'."""
    try:
        text = path.read_text("ascii", "replace")
    except OSError:
        return None
    m = re.search(r"PORT=127\.0\.0\.1:(\d+)", text)
    return int(m.group(1)) if m else None


def parse_listener(value: str) -> int | None:
    """GETINFO net/listeners/socks: '"127.0.0.1:9150"' (maybe several)."""
    m = re.search(r"127\.0\.0\.1:(\d+)", value or "")
    return int(m.group(1)) if m else None


# --------------------------------------------------------------------------- job object

class JobObject:
    """A Windows job object that kills everything in it when its last handle closes:
    when this process exits, however it exits. tor.exe's own children (lyrebird) join
    it automatically. Does nothing on other systems."""

    def __init__(self):
        self.handle = None
        if os.name != "nt":
            return
        from ctypes import wintypes

        class _Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class _Io(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in
                        ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                         "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class _Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", _Io),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k32 = self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        k32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int,
                                                ctypes.c_void_p, wintypes.DWORD)
        k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = k32.CreateJobObjectW(None, None)
        if not handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObject failed")
        info = _Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000   # KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(handle, 9, ctypes.byref(info),   # Extended…
                                           ctypes.sizeof(info)):
            err = ctypes.get_last_error()
            k32.CloseHandle(handle)
            raise OSError(err, "SetInformationJobObject failed")
        self.handle = handle

    def assign(self, proc: subprocess.Popen):
        if self.handle is None:
            return
        if not self._k32.AssignProcessToJobObject(self.handle, int(proc._handle)):
            raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")

    def close(self):
        """Kills whatever is still in it."""
        if self.handle is not None:
            self._k32.CloseHandle(self.handle)
            self.handle = None


# --------------------------------------------------------------------------- the manager

class Tor:
    """One tor.exe, started on demand. Thread-safe: gate() is called from whichever
    thread is about to connect; listeners are called from the worker thread (the Qt
    side, TorStatus, re-emits them as a signal)."""

    def __init__(self, exe: Path | None = None, root: Path | None = None,
                 cwd: Path | None = None):
        self._exe = exe
        self._root = root
        self._cwd = cwd
        self.bridges = ""
        self.enabled = False          # Connection = Tor
        self.state = OFF
        self.progress = 0
        self.message = ""             # the bootstrap summary, or why it failed
        self.socks_port: int | None = None
        self.waiting = 0              # requests held until Tor is ready
        self._cond = threading.Condition()
        self._proc: subprocess.Popen | None = None
        self._job: JobObject | None = None
        self._ctrl: ControlClient | None = None
        self._run_id = 0
        self._failed_at = 0.0
        self._moved_at = 0.0          # when the bootstrap progress last went up
        self._last_newnym = 0.0
        self._log: deque[str] = deque(maxlen=LOG_LINES)
        self._listeners: list[Callable[[], None]] = []

    # ---- paths
    @property
    def exe(self) -> Path | None:
        return self._exe if self._exe is not None else tor_exe()

    @property
    def root(self) -> Path:
        return self._root if self._root is not None else data_root()

    # ---- listeners
    def on_change(self, fn: Callable[[], None]):
        self._listeners.append(fn)

    def _changed(self):
        for fn in list(self._listeners):
            try:
                fn()
            except Exception:  # noqa: BLE001 - one listener mustn't stop the others
                log.exception("tor listener failed")

    def _set(self, run_id: int, state: str | None = None, progress: int | None = None,
             message: str | None = None) -> bool:
        """Update the status if `run_id` is still the current run."""
        with self._cond:
            if run_id != self._run_id:
                return False
            if state is not None:
                self.state = state
                if state == FAILED:
                    self._failed_at = time.monotonic()
            if progress is not None:
                if progress != self.progress:
                    self._moved_at = time.monotonic()
                self.progress = progress
            if message is not None:
                self.message = message
            self._cond.notify_all()
        self._changed()
        return True

    def status_text(self) -> str:
        """The status line for Settings, in plain words."""
        if not self.exe:
            return NOT_INSTALLED
        if self.state == READY:
            return "Connected to Tor."
        if self.state == STARTING:
            return f"Connecting to Tor… {self.progress}%" + (
                f" ({self.message})" if self.message else "")
        if self.state == FAILED:
            return f"Couldn't connect to Tor: {self.message}"
        if self.enabled and not net.any_allowed():
            return "Tor doesn't start: nothing is allowed to go online (Offline mode)."
        return ("Tor starts the next time the app goes online." if self.enabled
                else "Tor is off.")

    # ---- control
    def configure(self, enabled: bool, bridges: str = ""):
        """Connection is (or isn't) Tor, with these bridges. Turning it off stops Tor;
        changing the bridges restarts a running Tor."""
        bridges = bridges if bridges in BRIDGES else DEFAULT_BRIDGE
        restart = enabled and bridges != self.bridges and self.state in (STARTING, READY)
        self.enabled, self.bridges = enabled, bridges
        if not enabled:
            self.stop()
        elif restart:
            self.stop()
            self.start()
        else:
            self._changed()

    def start(self) -> None:
        """Start tor.exe in the background if it isn't running (or starting). Never
        while nothing may go online (Offline mode, or every switch off): Tor itself
        would."""
        if not net.any_allowed():
            return
        with self._cond:
            if not self.enabled or self.state in (STARTING, READY):
                return
            self._run_id += 1
            run_id = self._run_id
            self.state, self.progress, self.message = STARTING, 0, "starting Tor"
            self.socks_port = None
            self._cond.notify_all()
        self._changed()
        threading.Thread(target=self._run, args=(run_id,), daemon=True,
                         name="tor-start").start()

    def stop(self) -> None:
        """Stop tor.exe (and lyrebird) and wait briefly for it to go."""
        with self._cond:
            self._run_id += 1
            proc, job, ctrl = self._proc, self._job, self._ctrl
            self._proc = self._job = self._ctrl = None
            was = self.state
            self.state, self.progress, self.socks_port = OFF, 0, None
            self.message = ""
            self._cond.notify_all()
        if ctrl is not None:
            try:
                ctrl.signal("SHUTDOWN")   # a client exits straight away
            except OSError:
                pass
            ctrl.close()                  # TAKEOWNERSHIP: closing it stops tor too
        if proc is not None:
            try:
                proc.wait(STOP_WAIT_S)
            except subprocess.TimeoutExpired:
                pass
        if job is not None:
            job.close()                   # kills whatever is left in it
        if proc is not None and proc.poll() is None:
            proc.kill()
        if was != OFF:
            log.info("tor stopped")
            self._changed()

    def gate(self, timeout: float) -> net.Proxy:
        """net's way in: Tor's SOCKS port once it's connected. Starts Tor if needed and
        waits up to `timeout`; raises net.ProxyError (nothing is sent) otherwise."""
        if not self.exe:
            raise net.ProxyError(f"Not connecting: {NOT_INSTALLED} Or pick another "
                                 f"Connection in {net.WHERE}.")
        with self._cond:
            if not self.enabled:
                raise net.ProxyError("Not connecting: Tor is switched off")
            if (self.state == FAILED
                    and time.monotonic() - self._failed_at < RETRY_AFTER_FAIL_S):
                raise net.ProxyError(f"Couldn't connect to Tor ({self.message}). Nothing "
                                     "was sent without it.")
        self.start()
        deadline = time.monotonic() + timeout
        with self._cond:
            self.waiting += 1
        self._changed()
        try:
            with self._cond:
                while self.state != READY:
                    now = time.monotonic()
                    left = deadline - now
                    if self.state in (FAILED, OFF):
                        break
                    if left <= 0:
                        # a first start (no saved directory) can take minutes on a slow
                        # line: keep waiting while it's getting somewhere; the bootstrap
                        # gives up by itself at its own time limit
                        if now - self._moved_at > STILL_MOVING_S:
                            break
                        left = STILL_MOVING_S
                    self._cond.wait(min(left, 1.0))
                if self.state == READY and self.socks_port:
                    return net.Proxy("socks5", "127.0.0.1", self.socks_port)
                if self.state == FAILED:
                    raise net.ProxyError(f"Couldn't connect to Tor ({self.message}). "
                                         "Nothing was sent without it.")
                if self.state == OFF:
                    raise net.ProxyError("Not connecting: Tor was switched off")
                raise net.ProxyError(f"Tor is still connecting ({self.progress}%). Nothing "
                                     "was sent without it: try again in a moment.")
        finally:
            with self._cond:
                self.waiting -= 1
            self._changed()

    def new_identity(self) -> str:
        """SIGNAL NEWNYM: new connections use new circuits (most likely another exit,
        so sites see another address). Waits out tor's rate limit so the next
        connection really is new. Returns a message for the user."""
        with self._cond:
            ctrl = self._ctrl if self.state == READY else None
        if ctrl is None:
            return "Tor isn't connected, so there's no identity to change."
        wait = self._last_newnym + NEWNYM_EVERY_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            ctrl.signal("NEWNYM")
        except OSError as e:
            return f"Tor didn't take it ({errors.plain(e)})"
        self._last_newnym = time.monotonic()
        log.info("tor: new identity")
        return "New identity: new connections go out through a different route."

    # ---- the worker
    def _fail(self, run_id: int, why: str):
        log.warning("tor failed: %s", why)
        if self._set(run_id, FAILED, message=why):
            self._kill_run(run_id)

    def _kill_run(self, run_id: int):
        with self._cond:
            if run_id != self._run_id:
                return
            proc, job, ctrl = self._proc, self._job, self._ctrl
            self._proc = self._job = self._ctrl = None
        if ctrl is not None:
            ctrl.close()
        if job is not None:
            job.close()
        if proc is not None and proc.poll() is None:
            proc.kill()

    def _command(self, exe: Path) -> list[str]:
        return [str(exe)]   # tests run a Python stand-in instead

    def _launch(self, run_id: int) -> tuple[subprocess.Popen, Path] | None:
        exe = self.exe
        if exe is None:
            self._fail(run_id, NOT_INSTALLED)
            return None
        root = self.root
        try:
            (root / "data").mkdir(parents=True, exist_ok=True)
            torrc = make_torrc(root, self.bridges, owner_pid=os.getpid())
            (root / "torrc").write_text(torrc, "utf-8")
            (root / "torrc-defaults").write_text("", "utf-8")
            port_file = root / "control-port"
            port_file.unlink(missing_ok=True)
        except ValueError as e:
            self._fail(run_id, errors.plain(e))
            return None
        except OSError as e:
            self._fail(run_id, f"couldn't write its settings ({errors.plain(e)})")
            return None
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            job = JobObject()
            proc = subprocess.Popen(
                self._command(exe) + ["-f", str(root / "torrc"),
                                      "--defaults-torrc", str(root / "torrc-defaults")],
                cwd=str(self._cwd or exe.parent), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=flags)
        except OSError as e:
            self._fail(run_id, f"tor.exe wouldn't start ({errors.plain(e)}); an antivirus "
                               "may have blocked it")
            return None
        try:
            job.assign(proc)
        except OSError:
            log.exception("tor: couldn't put tor.exe in a job object")
        with self._cond:
            if run_id != self._run_id:   # stopped meanwhile
                job.close()
                if proc.poll() is None:
                    proc.kill()
                return None
            self._proc, self._job = proc, job
        threading.Thread(target=self._read_log, args=(proc,), daemon=True,
                         name="tor-log").start()
        return proc, port_file

    def _read_log(self, proc: subprocess.Popen):
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip()
            self._log.append(line)
            if "[warn]" in line or "[err]" in line:
                log.info("tor: %s", line.split("] ", 1)[-1])

    def _why_exited(self, proc: subprocess.Popen) -> str:
        time.sleep(0.2)   # let the log reader catch up
        for line in reversed(self._log):
            if "[err]" in line or "[warn]" in line:
                return f"tor.exe stopped: {line.split('] ', 1)[-1]}"
        return f"tor.exe stopped (exit code {proc.returncode})"

    def _run(self, run_id: int):
        launched = self._launch(run_id)
        if launched is None:
            return
        proc, port_file = launched
        log.info("tor starting%s", f" with {self.bridges} bridges" if self.bridges else "")
        deadline = time.monotonic() + CONTROL_FILE_WAIT_S
        port = None
        while port is None:
            if proc.poll() is not None:
                return self._fail(run_id, self._why_exited(proc))
            if time.monotonic() > deadline:
                return self._fail(run_id, "tor.exe didn't open its control port")
            if run_id != self._run_id:
                return
            port = read_control_port(port_file)
            if port is None:
                time.sleep(0.1)
        try:
            ctrl = ControlClient(port)
            cookie = (self.root / "data" / "control_auth_cookie").read_bytes()
            ctrl.authenticate(cookie)
            ctrl.take_ownership()
            socks = parse_listener(ctrl.getinfo("net/listeners/socks").get(
                "net/listeners/socks", ""))
        except OSError as e:
            return self._fail(run_id, f"couldn't talk to tor.exe ({errors.plain(e)})")
        if socks is None:
            ctrl.close()
            return self._fail(run_id, "tor.exe didn't open its SOCKS port")
        with self._cond:
            if run_id != self._run_id:
                ctrl.close()
                return
            self._ctrl, self.socks_port = ctrl, socks
        limit = BRIDGE_BOOTSTRAP_TIMEOUT_S if self.bridges else BOOTSTRAP_TIMEOUT_S
        deadline = time.monotonic() + limit
        last = None
        while run_id == self._run_id:
            if proc.poll() is not None:
                return self._fail(run_id, self._why_exited(proc))
            try:
                phase = parse_bootstrap(ctrl.getinfo("status/bootstrap-phase").get(
                    "status/bootstrap-phase", ""))
            except OSError as e:
                if run_id != self._run_id:
                    return
                return self._fail(run_id, f"tor.exe stopped answering ({errors.plain(e)})")
            now = (phase["progress"], phase["summary"])
            if now != last:
                last = now
                log.info("tor: %d%% %s", phase["progress"], phase["summary"])
            if phase["progress"] >= 100:
                self._set(run_id, READY, 100, "connected")
                log.info("tor connected (SOCKS on 127.0.0.1:%d)", socks)
                return
            self._set(run_id, progress=phase["progress"],
                      message=phase["summary"] or "connecting")
            if time.monotonic() > deadline:
                why = phase["warning"] or phase["summary"] or "no reason given"
                hint = ("" if self.bridges else
                        ". If Tor is blocked where you are, try “Hide that I'm using Tor”")
                return self._fail(run_id, f"it took too long ({why}){hint}")
            time.sleep(POLL_S)


# --------------------------------------------------------------------------- the app's one Tor

_tor: Tor | None = None


def manager() -> Tor:
    """The app's Tor, created on first use and plugged into soundboard.net."""
    global _tor
    if _tor is None:
        _tor = Tor()
        net.set_tor_gate(_tor.gate)
    return _tor


def _follow_switches() -> None:
    """Offline mode (or every switch off): a running Tor stops (off the UI thread: it
    waits for tor.exe to go), and isn't started again until something may go online."""
    t = _tor
    if t is None:
        return
    if net.any_allowed():
        t._changed()   # clear the Offline status; connections still start it on demand
        return
    if t.state in (STARTING, READY):
        threading.Thread(target=t.stop, daemon=True, name="tor-offline").start()
    else:
        t._changed()   # the status line says why it doesn't start


net.on_change(_follow_switches)


def configure_from(cfg) -> None:
    """Follow the Connection setting (called after net.configure)."""
    t = manager()
    t.configure(getattr(cfg, "net_mode", "") == net.TOR,
                getattr(cfg, "tor_bridges", "") or "")


def new_identity() -> str:
    return manager().new_identity() if _tor is not None else "Tor isn't running."


def shutdown() -> None:
    if _tor is not None:
        _tor.stop()


_status = None


def qt_status():
    """The app's one QObject whose `changed` signal fires (on the UI thread) whenever
    Tor's state, progress or waiting count changes. Create it on the UI thread."""
    global _status
    if _status is None:
        from PySide6.QtCore import QObject, Signal

        class TorStatus(QObject):
            changed = Signal()

        _status = TorStatus()
        manager().on_change(_status.changed.emit)   # queued over from the worker thread
    return _status
