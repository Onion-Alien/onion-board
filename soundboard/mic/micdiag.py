"""The mic effect's start log: what one set-up did, and when it failed, why Windows didn't
start the effect, as far as this PC can show it.

The admin step (`--direct-mic install`, Windows' prompt or the mic helper) writes it as it
goes to REPORT, beside the admin logs, started afresh each step: every log line with its
time, the mic's effect settings at each stage, and on a failure what can only be seen as
admin (Code Integrity, audiodg's loaded files). `snapshot()` is the part anyone can read,
for when no admin step ran. What the app does with it: soundboard/online/micreport.py.

Everything here is a look: it never changes anything, and never fails the step.
Audio callbacks never come near it."""
from __future__ import annotations

import ctypes
import functools
import hashlib
import logging
import os
import re
import struct
import subprocess
import sys
import time
import winreg
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

from soundboard.mic.micbase import (CAPTURE_KEY, CLSID, DISABLE_SYSFX, FX, MODES_KEY,
                                    _CREATE_NO_WINDOW, bundled_dll, data_dir, install_dir,
                                    ring_path)
from soundboard.win import systools

log = logging.getLogger(__name__)

REPORT = "mic-start.log"   # in data_dir().parent: admins write it, users read it
REPORT_BYTES = 48 * 1024   # the step's own lines stop here; a failure's findings still fit
TOOL_S = 15                # one look at Windows (an event log, PowerShell) gets this long
APO_LOG = "apo.log"        # in data_dir(): the effect's own log (obmic.cpp logv)
EVENT_SOURCE = "Onion Board mic"   # obmic.cpp eventLog
ADMIN_START_FAILED = "the admin step couldn't start"   # micadmin.event (exit code 5)
DLL_MARK = "obmic"         # how a file of ours shows up in Windows' event logs
RING_FRESH_MS = 120_000    # the effect's last block this recent: it ran during the step

# what the mic check's Windows error means, for the ones worth naming
HRESULTS = {
    0x88890004: "AUDCLNT_E_DEVICE_INVALIDATED",
    0x8889000A: "AUDCLNT_E_DEVICE_IN_USE (another app has the mic to itself)",
    0x88890008: "AUDCLNT_E_UNSUPPORTED_FORMAT",
    0x88890010: "AUDCLNT_E_CPUUSAGE_EXCEEDED",
    0x88890014: "AUDCLNT_E_ENDPOINT_OFFLOAD_NOT_CAPABLE",
    0x8889000F: "AUDCLNT_E_ENDPOINT_CREATE_FAILED",
    0x88890006: "AUDCLNT_E_BUFFER_SIZE_ERROR",
    0x88890026: "AUDCLNT_E_RESOURCES_INVALIDATED",
    0x80070005: "E_ACCESSDENIED (Windows' microphone privacy setting, or a policy)",
    0x80070490: "E_NOTFOUND",
    0x800401F0: "CO_E_NOTINITIALIZED",
    0x8007007E: "a file Windows' audio has to load isn't there (ERROR_MOD_NOT_FOUND)",
    0x8007007F: "a file Windows' audio loaded lacks what it asks for (ERROR_PROC_NOT_FOUND)",
    0x800700C1: "a file Windows' audio has to load is damaged (ERROR_BAD_EXE_FORMAT)",
    0x800700E1: "a virus scanner blocked a file (ERROR_VIRUS_INFECTED)",
    0x800704EC: "a policy blocked a file (ERROR_ACCESS_DISABLED_BY_POLICY)",
    0x80070241: "Windows refused a file's signature (ERROR_INVALID_IMAGE_HASH)",
    0x80070242: "Windows refused a file's signature (ERROR_DRIVER_BLOCKED)",
    0x800711C7: "App Control blocked a file (ERROR_SYSTEM_INTEGRITY_POLICY_VIOLATION)",
}
# ...the ones that say an effect on the mic couldn't be loaded, not that the mic is at fault
LOAD_FAILED = {0x8007007E, 0x8007007F, 0x800700C1, 0x800700E1, 0x800704EC, 0x80070241,
               0x80070242, 0x800711C7}
_RIGHTS_WRITE = 0x2 | 0x4 | 0x10000000 | 0x40000000   # write, append, generic all, generic write
_EFFECT_SIDS = {"LS", "WR", "AU", "BU", "WD", "S-1-5-19", "S-1-5-33", "S-1-5-11", "S-1-1-0",
                "S-1-5-32-545"}   # audiodg's account and the groups it's in


def _quiet(fallback=None):
    """A look that fails says so in the log, and never stops the step it's in."""
    def wrap(fn):
        @functools.wraps(fn)
        def run(*args, **kw):
            try:
                return fn(*args, **kw)
            except Exception as e:  # noqa: BLE001 - only a log: the step goes on
                log.info("mic start log: %s failed: %s: %s", fn.__name__, type(e).__name__, e)
                return fallback
        return run
    return wrap


class _Lines(logging.Handler):
    """Every line the step logs goes in the report too, with its time; the same few lines
    over and over (a mic that won't open is tried hundreds of times) once, with how many."""

    def __init__(self):
        super().__init__()
        self.recent: deque[str] = deque(maxlen=4)
        self.again = 0

    def emit(self, record):
        try:
            line = self.format(record)
            if line in self.recent:
                self.again += 1
                return
            self.flush()
            self.recent.append(line)
            _write(line)
        except Exception:  # noqa: BLE001 - a log handler never raises
            pass

    def flush(self):
        if self.again:
            _write(f"(the same lines {self.again} more times)")
            self.again = 0


_path: Path | None = None    # the report while a step writes it (begin() to end())
_started = 0.0
_written = 0
_handler: _Lines | None = None
_stages: dict[str, dict] = {}   # stage -> the mic's effect values there
_last_seen: dict[str, dict] = {}   # mic -> its values at the stage before


def report_path() -> Path:
    return data_dir().parent / REPORT


def _write(line: str, *, force: bool = False):
    global _written
    if _path is None or (_written > REPORT_BYTES and not force):
        return
    text = f"+{time.monotonic() - _started:7.2f}s {line}\n"
    with open(_path, "a", encoding="utf-8", errors="replace") as f:
        f.write(text)
    _written += len(text)


@_quiet()
def begin(step: Sequence[str]):
    """An admin step starts: the report is started afresh, with what it is and on what."""
    global _path, _started, _written, _handler
    _path, _started, _written = report_path(), time.monotonic(), 0
    _stages.clear()
    _last_seen.clear()
    _path.write_text("", encoding="utf-8")
    _write(f"step: {' '.join(step)}")
    for line in _about_this_pc():
        _write(line)
    _handler = _Lines()
    logging.getLogger().addHandler(_handler)


@_quiet()
def end(code: int, guids: Iterable[str] = ()):
    """The step ended with exit code `code`: a failure gets everything that can be found
    out about it (slow: Windows' event logs, PowerShell), a success only its code."""
    global _path, _handler
    if _path is None:
        return
    if _handler is not None:
        _handler.flush()
        logging.getLogger().removeHandler(_handler)
    if code:
        for line in findings(list(guids)):
            _write(line, force=True)
    _write(f"exit code: {code}", force=True)
    _path, _handler = None, None


@_quiet()
def stage(name: str, guids: Iterable[str] = ()):
    """One stage of the step: the mics' effect settings as they are now, so what Windows or
    a driver changed between two stages shows ("before the write", "after the restart")."""
    if _path is None:
        return
    _write(f"--- {name}")
    for g in dict.fromkeys(g.lower() for g in guids):
        now = fx_dump(g)
        before = _last_seen.get(g)
        _last_seen[g] = now
        _stages.setdefault(name, {})[g] = now
        for line in fx_lines(now) if before is None else fx_changes(before, now):
            _write(f"  {g} {line}")


def active() -> bool:
    return _path is not None


# ------------------------------------------------------------------------- the PC

def _about_this_pc() -> list[str]:
    from soundboard import __version__
    lines = [f"app: {__version__}, {'frozen' if getattr(sys, 'frozen', False) else 'source'}"]
    v = _key_values(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion")
    build = sys.getwindowsversion().build if sys.platform == "win32" else 0
    lines.append(f"windows: build {build}.{v.get('UBR', '?')}, {v.get('EditionID', '?')}, "
                 f"{v.get('DisplayVersion', v.get('ReleaseId', '?'))}")
    lines.append(f"running as: {_account()}")
    return lines


def _account() -> str:
    """Whose rights this look has (only the kind, never the name)."""
    try:
        admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        admin = False
    system = os.environ.get("USERNAME", "").upper().endswith("$")
    return "SYSTEM (the mic helper)" if system else "admin" if admin else "the signed-in user"


def _key_values(root, path: str) -> dict:
    out: dict = {}
    try:
        with winreg.OpenKey(root, path) as k:
            i = 0
            while True:
                try:
                    name, value, _kind = winreg.EnumValue(k, i)
                except OSError:
                    return out
                out[name] = value
                i += 1
    except OSError:
        return out


# ------------------------------------------------------------------- the mic's settings

def fx_dump(guid: str) -> dict:
    """Every value in the mic's FxProperties: {name: what's in it, readable}."""
    values = _key_values(winreg.HKEY_LOCAL_MACHINE, rf"{CAPTURE_KEY}\{guid}\FxProperties")
    return {name: _shown(v) for name, v in sorted(values.items())}


def _shown(v) -> str:
    if isinstance(v, bytes):
        return "bytes:" + v[:48].hex() + ("..." if len(v) > 48 else "")
    if isinstance(v, list):
        return "|".join(map(str, v))
    return str(v)


def _about_effects(name: str) -> bool:
    """One of the values that decide what runs on a mic (a driver can hold hundreds more:
    its tuning, which says nothing here)."""
    low = name.lower()
    return low.startswith((FX.split(",")[0].lower() + ",", MODES_KEY.split(",")[0].lower() + ",")) \
        or low == DISABLE_SYSFX.lower()


def _with_names(name: str, value: str) -> str:
    said = f"{name} = {value}"
    names = [_effect_name(c) for c in re.findall(r"\{[0-9a-fA-F-]{36}\}", value)]
    return said + "  (" + ", ".join(n or "?" for n in names) + ")" if any(names) else said


def fx_lines(values: dict) -> list[str]:
    """The values that decide which effects run, with the name of what's in each."""
    if not values:
        return ["no FxProperties values"]
    lines = [_with_names(n, v) for n, v in values.items() if _about_effects(n)]
    return [*lines, f"({len(values) - len(lines)} other values, the driver's own)"]


def fx_changes(before: dict, now: dict, shown: int = 20) -> list[str]:
    """What changed from one stage to the next, whichever value it was."""
    lines = []
    for name in sorted(before.keys() | now.keys()):
        if before.get(name) != now.get(name):
            lines.append(f"changed {name}: {before.get(name, '(none)')} -> "
                         + (_with_names(name, now[name]).partition(" = ")[2]
                            if name in now else "(gone)"))
    return lines[:shown] or ["no change"]


def _effect_name(clsid: str) -> str:
    """What an effect CLSID is: ours, or its registered name and file."""
    if clsid.upper() == CLSID:
        return "Onion Board"
    v = _key_values(winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Classes\CLSID\{clsid}")
    dll = _key_values(winreg.HKEY_LOCAL_MACHINE,
                      rf"SOFTWARE\Classes\CLSID\{clsid}\InprocServer32").get("", "")
    bits = [str(v.get("", "")), Path(str(dll)).name if dll else ""]
    return " ".join(b for b in bits if b)


def enhancements_off(values: dict) -> bool:
    """"Audio enhancements: off" on the mic: Windows starts no effect there."""
    v = values.get(DISABLE_SYSFX, "")
    return bool(v) and v != "0" and not set(v.removeprefix("bytes:")) <= {"0"}


def ours_in(values: dict) -> bool:
    return any(CLSID in v.upper() for k, v in values.items()
               if k.lower().startswith(FX.split(",")[0].lower() + ","))


def device_lines(guid: str) -> list[str]:
    """What kind of device the mic is: its name, how it's connected (the enumerator),
    its hardware ids without the serial part, its driver's name and version."""
    props = _key_values(winreg.HKEY_LOCAL_MACHINE, rf"{CAPTURE_KEY}\{guid}\Properties")
    state = _key_values(winreg.HKEY_LOCAL_MACHINE, rf"{CAPTURE_KEY}\{guid}").get("DeviceState")
    name = props.get("{b3f8fa53-0004-438e-9003-51a46e139bfc},6", "")
    desc = props.get("{a45c254e-df1c-4efd-8020-67d146a850e0},2", "")
    lines = [f"mic {guid}: {desc} ({name}), DeviceState {state}"]
    instance = str(props.get("{b3f8fa53-0004-438e-9003-51a46e139bfc},2", ""))
    instance = re.sub(r"^\{[^}]*\}\.", "", instance)
    if not instance:
        lines.append("  no device id among its properties")
        return lines
    enum = instance.split("\\", 1)[0]
    lines.append(f"  connected by: {enum}, hardware: {_no_serial(instance)}")
    dev = _key_values(winreg.HKEY_LOCAL_MACHINE,
                      rf"SYSTEM\CurrentControlSet\Enum\{instance}")
    driver = dev.get("Driver")
    if driver:
        d = _key_values(winreg.HKEY_LOCAL_MACHINE,
                        rf"SYSTEM\CurrentControlSet\Control\Class\{driver}")
        lines.append(f"  driver: {d.get('DriverDesc', '?')} by {d.get('ProviderName', '?')}, "
                     f"version {d.get('DriverVersion', '?')} ({d.get('DriverDate', '?')}), "
                     f"{d.get('InfPath', '?')}, service {dev.get('Service', '?')}")
    return lines


def _no_serial(instance: str) -> str:
    """A device id without its last part, which can be the device's serial number."""
    return "\\".join(instance.split("\\")[:2])


# ------------------------------------------------------------------- the effect's file

def dll_lines() -> tuple[list[str], list[str]]:
    """Whether Windows can load the effect: (lines, causes found)."""
    lines, causes = [], []
    reg = _key_values(winreg.HKEY_LOCAL_MACHINE,
                      rf"SOFTWARE\Classes\CLSID\{CLSID}\InprocServer32")
    dll = str(reg.get("", ""))
    lines.append(f"registered: {dll or 'NOT REGISTERED'}, "
                 f"threading {reg.get('ThreadingModel', '?')}")
    if not dll:
        causes.append("effect-not-registered")
        return lines, causes
    path = Path(dll)
    try:
        st = path.stat()
    except OSError as e:
        lines.append(f"effect file: not there ({type(e).__name__}, error {e.winerror})")
        causes.append("effect-file-missing")
        return lines, causes
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        ours = hashlib.sha256(bundled_dll().read_bytes()).hexdigest()[:16] \
            if bundled_dll().is_file() else "?"
        lines.append(f"effect file: {st.st_size} bytes, sha256 {digest}, this app's copy {ours}, "
                     f"attributes {getattr(st, 'st_file_attributes', 0):#x}")
    except OSError as e:
        lines.append(f"effect file: there, but this look can't read it (error {e.winerror}): "
                     "something is holding or blocking it")
        causes.append("effect-file-unreadable")
    sddl = _sddl(path)
    lines.append(f"effect file's access: {sddl}")
    if sddl and not _lets(sddl, 0x1 | 0x20 | 0x80000000 | 0x10000000):
        causes.append("effect-file-denied")
    lines.append(f"folder {install_dir().name}'s access: {_sddl(install_dir())}")
    return lines, causes


def log_lines() -> tuple[list[str], list[str]]:
    """Whether the effect can write its log: (lines, causes found). Windows' account for it
    is LOCAL SERVICE; the effect's own word on it (the event log) is in event_lines."""
    lines, causes = [], []
    folder = data_dir()
    file = folder / APO_LOG
    sddl = _sddl(folder)
    lines.append(f"log folder's access: {sddl}")
    if sddl and not _lets(sddl, _RIGHTS_WRITE):
        causes.append("log-folder-denied")
    if not file.exists():
        lines.append("effect's log: no file")
        return lines, causes
    st = file.stat()
    readonly = bool(getattr(st, "st_file_attributes", 0) & 1)
    fsddl = _sddl(file)
    lines.append(f"effect's log: {st.st_size} bytes, last written "
                 f"{time.time() - st.st_mtime:.0f} s ago, read-only {readonly}, access {fsddl}")
    if readonly or (fsddl and not _lets(fsddl, _RIGHTS_WRITE)):
        causes.append("log-file-denied")
    return lines, causes


def _sddl(path: Path) -> str:
    """`path`'s access list as text; "" if it can't be read."""
    from ctypes import wintypes
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR),
        ctypes.c_void_p]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    sd = ctypes.c_void_p()
    # SE_FILE_OBJECT, DACL_SECURITY_INFORMATION
    if advapi.GetNamedSecurityInfoW(str(path), 1, 4, None, None, None, None, ctypes.byref(sd)):
        return ""
    text = wintypes.LPWSTR()
    try:
        if not advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                sd, 1, 4, ctypes.byref(text), None):
            return ""
        value = text.value or ""
        kernel.LocalFree(text)
        return value
    finally:
        kernel.LocalFree(sd)


_ACE = re.compile(r"\(([AD]);([^;]*);([^;]*);;;([^)]*)\)")
_LETTERS = {"FA": 0x10000000, "GA": 0x10000000, "FW": 0x40000000, "GW": 0x40000000,
            "FR": 0x80000000, "GR": 0x80000000, "GX": 0x20, "FX": 0x20, "RC": 0, "CC": 0x1,
            "DC": 0x2, "LC": 0x4, "SW": 0x8, "RP": 0x10, "WP": 0x20, "DT": 0x40, "LO": 0x80,
            "CR": 0x100, "SD": 0x10000, "WD": 0x40000, "WO": 0x80000}


def _mask(rights: str) -> int:
    if rights.lower().startswith("0x"):
        return int(rights, 16)
    return sum(_LETTERS.get(rights[i:i + 2], 0) for i in range(0, len(rights), 2))


def _lets(sddl: str, wanted: int) -> bool:
    """Whether `sddl` (a file or folder's access list) gives the effect's account any of the
    `wanted` rights: no Deny entry for it naming them, and an Allow that does. Inherit-only
    entries say nothing about the thing itself. Good enough to name a cause, not a proof:
    the effect's own failed write (the event log) is that."""
    allowed = False
    for kind, flags, rights, sid in _ACE.findall(sddl.partition("D:")[2] or sddl):
        if sid not in _EFFECT_SIDS or "IO" in flags:
            continue
        if _mask(rights) & wanted:
            if kind == "D":
                return False
            allowed = True
    return allowed


# ------------------------------------------------------------------ Windows' event logs

def _events(channel: str, query: str, count: int = 200) -> tuple[list[dict], str]:
    """Events from a Windows event log, newest first: ([{id, time, text}], why not)."""
    try:
        r = subprocess.run([systools.tool("wevtutil"), "qe", channel, f"/q:{query}", "/rd:true",
                            f"/c:{count}", "/f:xml"], capture_output=True, text=True,
                           errors="replace", timeout=TOOL_S, creationflags=_CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired, ValueError) as e:
        return [], type(e).__name__
    if r.returncode:
        return [], f"can't read it (code {r.returncode})"
    out = []
    for xml in re.findall(r"<Event .*?</Event>", r.stdout, re.S):
        m = re.search(r"<EventID[^>]*>(\d+)<", xml)
        t = re.search(r"SystemTime='([^']+)'", xml)
        data = re.findall(r"<Data[^>]*>([^<]*)</Data>", xml)
        out.append({"id": int(m.group(1)) if m else 0, "time": t.group(1)[:19] if t else "?",
                    "text": " | ".join(d for d in data if d)})
    return out, ""


_DAY_MS = 7 * 86400 * 1000
_RECENT = f"TimeCreated[timediff(@SystemTime) <= {_DAY_MS}]"


def event_lines() -> tuple[list[str], list[str]]:
    """What Windows' own logs say about the effect in the last week: (lines, causes)."""
    lines, causes = [], []

    def mentions(events: list[dict], *marks: str) -> list[dict]:
        return [e for e in events if any(m in e["text"].lower() for m in marks)]

    ci, why = _events("Microsoft-Windows-CodeIntegrity/Operational",
                      f"*[System[{_RECENT}]]", 500)
    hits = mentions(ci, DLL_MARK)
    lines.append("Code Integrity log: "
                 + (why or f"{len(ci)} events this week, {len(hits)} about the effect"))
    for e in hits[:8]:
        lines.append(f"  {e['time']} event {e['id']}: {e['text'][:300]}")
    if hits:
        causes.append("blocked-by-code-integrity")
    for channel, name in (("Microsoft-Windows-AppLocker/EXE and DLL", "AppLocker"),
                          ("Microsoft-Windows-Windows Defender/Operational", "Defender")):
        got, why = _events(channel, f"*[System[{_RECENT}]]", 300)
        hits = mentions(got, DLL_MARK, "onion board mic")
        lines.append(f"{name} log: "
                     + (why or f"{len(got)} events this week, {len(hits)} about the effect"))
        for e in hits[:5]:
            lines.append(f"  {e['time']} event {e['id']}: {e['text'][:300]}")
        if hits:
            causes.append(f"blocked-by-{name.lower()}")
    own, why = _events("Application",
                       f"*[System[Provider[@Name='{EVENT_SOURCE}'] and {_RECENT}]]", 30)
    lines.append(f"the effect's own events: {why or len(own)}")
    for e in own[:12]:
        lines.append(f"  {e['time']} event {e['id']}: {e['text'][:300]}")
    fresh, _why = _events("Application", f"*[System[Provider[@Name='{EVENT_SOURCE}'] and "
                                         "TimeCreated[timediff(@SystemTime) <= 900000]]]", 10)
    if any("can't write its log" in e["text"] for e in fresh):   # (now: not last week's)
        causes.append("log-write-failed")
    if any(ADMIN_START_FAILED in e["text"] for e in fresh):   # it says which part, and why
        causes.append("admin-start-failed")
    crashes, why = _events("Application",
                           f"*[System[(EventID=1000 or EventID=1001) and {_RECENT}]]", 100)
    hits = [e for e in mentions(crashes, "audiodg", DLL_MARK) if _is_crash(e)]
    lines.append(f"audio engine crashes this week: {why or len(hits)}")
    for e in hits[:5]:
        lines.append(f"  {e['time']} event {e['id']}: {e['text'][:300]}")
    if hits:
        causes.append("audio-engine-crashed")
    return lines, causes


# Windows Error Reporting's event 1001 is any report it made, not only a crash's: a
# RADAR_PRE_LEAK_64 one (Windows noting a process uses a lot of memory) about audiodg
# was counted as the audio engine crashing, on a PC where it ran fine. A crash's report
# has one of these names (BEX64 too); event 1000 (Application Error) is always a crash
_CRASH_REPORTS = ("appcrash", "bex", "moappcrash")


def _is_crash(event: dict) -> bool:
    """Whether the Application log's event 1000/1001 `event` is a process crashing."""
    if event.get("id") != 1001:
        return True
    # its text: "<bucket> | <type> | <report name> | ..." (_events leaves out empty ones)
    fields = [f.strip().lower() for f in event.get("text", "").split("|")[:4]]
    return any(f.startswith(_CRASH_REPORTS) for f in fields)


def protection_lines() -> list[str]:
    """What on this PC can stop a file loading: Smart App Control, memory integrity,
    App Control policies, virus scanners; and Windows' audio settings that bear on it."""
    lines = []
    ci = _key_values(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\CI\Policy")
    sac = {0: "off", 1: "on", 2: "evaluation"}.get(ci.get("VerifiedAndReputablePolicyState", -1),
                                                   "not set")
    lines.append(f"Smart App Control: {sac}")
    hv = _key_values(winreg.HKEY_LOCAL_MACHINE,
                     r"SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios"
                     r"\HypervisorEnforcedCodeIntegrity")
    lines.append(f"memory integrity (HVCI): {'on' if hv.get('Enabled') else 'off'}")
    audio = _key_values(winreg.HKEY_LOCAL_MACHINE,
                        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Audio")
    lines.append(f"Windows' audio settings: {_shown_all(audio)}")
    script = ("$v=Get-CimInstance -Namespace root\\SecurityCenter2 AntiVirusProduct "
              "-ErrorAction SilentlyContinue; foreach($a in $v){'antivirus: '+$a.displayName+"
              "' state '+$a.productState}; "
              "$d=Get-CimInstance -Namespace root\\Microsoft\\Windows\\DeviceGuard "
              "Win32_DeviceGuard "
              "-ErrorAction SilentlyContinue; if($d){'device guard: user policy '+"
              "$d.UsermodeCodeIntegrityPolicyEnforcementStatus+', running '+"
              "($d.SecurityServicesRunning -join ',')}")
    try:
        r = subprocess.run([systools.tool("powershell"), "-NoProfile", "-NonInteractive",
                            "-Command", script], capture_output=True, text=True,
                           errors="replace", timeout=TOOL_S, creationflags=_CREATE_NO_WINDOW)
        lines += [s.strip() for s in r.stdout.splitlines() if s.strip()][:10]
    except (OSError, subprocess.TimeoutExpired, ValueError) as e:
        lines.append(f"antivirus list: {type(e).__name__}")
    return lines


def _shown_all(values: dict) -> str:
    return ", ".join(f"{k}={_shown(v)}" for k, v in sorted(values.items())) or "none set"


# ----------------------------------------------------------------- did the effect load?

def ring_lines() -> tuple[list[str], bool]:
    """What the running effect left in the ring file, which works with no log at all
    (micring's header: offset 80 its version, 72 its last block, 56 frames of clean mic):
    (lines, whether it ran on a mic in the last RING_FRESH_MS). Unbuffered and only up to
    the version: a running board locks the 4 bytes after it (RingWriter.claim), and a
    buffered read (8 KB) or one past them failed with PermissionError while it ran."""
    try:
        with open(ring_path(), "rb", buffering=0) as f:
            head = f.read(84)
    except OSError as e:
        return [f"ring file: can't read it ({type(e).__name__})"], False
    if len(head) < 84:
        return [f"ring file: only {len(head)} bytes"], False
    frames = struct.unpack_from("<Q", head, 56)[0]
    last = struct.unpack_from("<Q", head, 72)[0]
    version = struct.unpack_from("<I", head, 80)[0]
    ago = _tick() - last if last else -1
    ran = 0 <= ago < RING_FRESH_MS
    # (a tick from before the last restart is ahead of the clock, which starts at 0 at boot)
    when = ("no block yet" if not last else f"last block {ago / 1000:.1f} s ago" if ago >= 0
            else "last block before the last restart")
    return [f"ring file: effect version {version}, {frames} clean-mic frames, {when}"], ran


def _tick() -> int:
    k = ctypes.windll.kernel32
    k.GetTickCount64.restype = ctypes.c_uint64
    return k.GetTickCount64()


def _audiodg_files() -> tuple[list[str] | None, str]:
    """The files loaded in the audio engine now, outside Windows' own folder: (paths, why
    not). Needs admin; audiodg may also not be running with no stream open."""
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)

    class Entry(ctypes.Structure):   # PROCESSENTRY32W
        _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD),
                    ("pid", wintypes.DWORD), ("heap", ctypes.c_size_t),
                    ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                    ("parent", wintypes.DWORD), ("prio", wintypes.LONG),
                    ("flags", wintypes.DWORD), ("exe", ctypes.c_wchar * 260)]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.OpenProcess.restype = wintypes.HANDLE
    snap = kernel.CreateToolhelp32Snapshot(2, 0)   # TH32CS_SNAPPROCESS
    pids = []
    e = Entry()
    e.size = ctypes.sizeof(Entry)
    ok = kernel.Process32FirstW(snap, ctypes.byref(e))
    while ok:
        if e.exe.lower() == "audiodg.exe":
            pids.append(e.pid)
        ok = kernel.Process32NextW(snap, ctypes.byref(e))
    kernel.CloseHandle(snap)
    if not pids:
        return None, "audiodg isn't running"
    psapi.EnumProcessModulesEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                           ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
    psapi.GetModuleFileNameExW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.LPWSTR,
                                           wintypes.DWORD]
    found: list[str] = []
    windows = os.environ.get("SystemRoot", r"C:\Windows").lower()
    for pid in pids:
        h = kernel.OpenProcess(0x0410, False, pid)   # query information, read memory
        if not h:
            return None, f"can't look inside it (error {ctypes.get_last_error()})"
        try:
            mods = (ctypes.c_void_p * 1024)()
            need = wintypes.DWORD()
            if not psapi.EnumProcessModulesEx(h, mods, ctypes.sizeof(mods), ctypes.byref(need), 3):
                return None, f"can't list its files (error {ctypes.get_last_error()})"
            buf = ctypes.create_unicode_buffer(520)
            for i in range(min(need.value // ctypes.sizeof(ctypes.c_void_p), 1024)):
                if psapi.GetModuleFileNameExW(h, mods[i], buf, 520) \
                        and not buf.value.lower().startswith(windows):
                    found.append(buf.value)
        finally:
            kernel.CloseHandle(h)
    return found, ""


def mic_check_lines(guid: str) -> tuple[list[str], list[str]]:
    """Open the mic as an app does and say what Windows answered, with what the audio engine
    has loaded while it's open: (lines, causes)."""
    from soundboard.audio import appaudio
    seen: dict = {}

    def during():
        seen["files"], seen["why"] = _audiodg_files()

    got = appaudio.mic_open_report(guid, during)
    lines, causes = [f"mic check on {guid}: {_said(got)}"], []
    if got.get("hr") == 0x8889000A:
        causes.append("mic-held-exclusively")
    elif got.get("hr") in LOAD_FAILED:
        causes.append("effect-failed-to-load")
    elif got.get("opens") is False:
        causes.append("mic-wont-open")
    elif got.get("opens") is None:
        causes.append("mic-not-active")
    if "files" not in seen:   # (it never got as far as started)
        during()
    files = seen.get("files")
    if files is None:
        lines.append(f"  audio engine's files: {seen.get('why') or 'not looked at'}")
    else:
        loaded = any(DLL_MARK in Path(f).name.lower() for f in files)
        lines.append(f"  audio engine has the effect loaded: {'yes' if loaded else 'NO'}")
        lines.append(f"  its other files: {', '.join(Path(f).name for f in files) or 'none'}")
        if not loaded and got.get("opens"):
            causes.append("engine-did-not-load-effect")
    return lines, causes


def _said(got: dict) -> str:
    if got.get("opens") is None:
        return f"not active ({got.get('why', 'unplugged, off, or the look failed')})"
    fmt = got.get("format", "?")
    if got.get("opens"):
        return f"opens, format {fmt}"
    hr = got.get("hr", 0)
    return (f"REFUSED at {got.get('call', '?')}: 0x{hr:08X} {HRESULTS.get(hr, '')}".rstrip()
            + f", format {fmt}")


@_quiet((["the audio services: can't tell"], []))
def service_lines() -> tuple[list[str], list[str]]:
    from soundboard.mic import micadmin
    states = micadmin._service_states()
    causes = ["audio-service-down"] if states and any(s != "Running" for s in states.values()) \
        else []
    return [f"audio services: {states}"], causes


# ---------------------------------------------------------------------- the whole picture

def _tried(fn: Callable, *args) -> tuple[list[str], list[str]]:
    """(lines, causes) of one look; a look that failed is a line too, and the rest go on."""
    try:
        got = fn(*args)
    except Exception as e:  # noqa: BLE001 - only a log
        return [f"{fn.__name__} failed: {type(e).__name__}: {e}"], []
    return got if isinstance(got, tuple) else (got, [])


def findings(guids: Sequence[str]) -> list[str]:
    """Everything that can be found out about why the effect doesn't start on `guids`, the
    verdict (fixed words for what was found) first."""
    body, causes = [], []
    for fn, args in ((dll_lines, ()), (log_lines, ()), (ring_lines_causes, ()),
                     (service_lines, ()), (event_lines, ()), (protection_lines, ())):
        lines, found = _tried(fn, *args)
        body += lines
        causes += found
    for g in guids:
        body += _tried(device_lines, g)[0]
        values = fx_dump(g)
        body += [f"  {x}" for x in fx_lines(values)]
        if enhancements_off(values):
            causes.append("enhancements-off")
        if not ours_in(values) and not _run_by_eapo(g):
            causes.append("settings-lost")
        if _changed_by_restart(g, values):
            causes.append("settings-rewritten")
        lines, found = _tried(mic_check_lines, g)
        body += lines
        causes += found
    causes = list(dict.fromkeys(causes)) or ["nothing-found"]
    return ["=== why", f"verdict: {' '.join(causes)}", *body]


def _run_by_eapo(guid: str) -> bool:
    from soundboard.mic import micstate
    try:
        return bool(micstate.eapo_runs_us(guid))
    except Exception:  # noqa: BLE001 - a look
        return False


def _changed_by_restart(guid: str, now: dict) -> bool:
    """The mic's settings differ from what the step wrote: a driver or Windows rewrote them
    across the audio restart (only stages this step noted, the last write first)."""
    written = _stages.get("after the write", {}).get(guid)
    if written is None or _moved_slot():
        return False
    return any(written.get(k) != now.get(k) for k in written.keys() | now.keys()
               if _about_effects(k))


def _moved_slot() -> bool:
    """The step itself moved the effect to the stream slot after that stage."""
    return "moved to the stream slot" in _stages


def ring_lines_causes() -> tuple[list[str], list[str]]:
    lines, ran = ring_lines()
    try:
        logged = time.time() - (data_dir() / APO_LOG).stat().st_mtime < RING_FRESH_MS / 1000
    except OSError:
        logged = False
    return lines, ["effect-ran-but-logged-nothing"] if ran and not logged else []


def snapshot(guid: str | None) -> list[str]:
    """What anyone can look at, for a failure with no admin step behind it (or on top of
    one): the file, the log, the mic's settings and Windows' logs a user may read."""
    out = ["=== now, as the signed-in user", *_tried(_about_this_pc)[0]]
    out += findings([guid] if guid else [])
    return out
