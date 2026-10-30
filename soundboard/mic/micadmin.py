"""The mic effect's admin part: everything that runs in the admin copy only
(`--direct-mic ...`, Windows' prompt or the mic helper): putting the effect on a mic
and taking it off, Windows' audio restarted around it, and cli, the command runner
(plus, at the end, its SteelSeries Sonar look-ups for the app, which need no admin).
The mic helper (michelper.py) runs a frozen copy of it: change it and
michelper.HELPER_VERSION goes up (tests/test_michelper.py)."""
from __future__ import annotations

import ctypes
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import time
import winreg
from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path

from soundboard.mic import safefs
from soundboard.win import systools
from soundboard.mic.micbase import (CAPTURE_KEY, CLSID, COMPOSITE_EFX, COMPOSITE_SFX,
                                    DISABLE_SYSFX, EFX, ENDPOINTS_KEY, ENDPOINT_SLOTS, FX, GFX,
                                    LEGACY, LFX, MODERN, MODES_KEY, MODE_DEFAULT, OUR_SLOTS, SFX,
                                    SLOTS_FX, STATE_KEY, _CREATE_NO_WINDOW, _GUID,
                                    _old_install_dirs, bundled_dll, data_dir, install_dir, log,
                                    ring_path)
from soundboard.mic.micring import make_ring_ok, new_ring_bytes
from soundboard.mic.micstate import (_digest, _eapo_hand_back, _fx_values, _is_eapo, _is_ours,
                                     anything_installed, capture_endpoints, eapo_runs_us,
                                     installed_on, registered_dll, without_ours)


# ---------------------------------------------------------------------- admin part
# Everything below runs in the admin copy only (`--direct-mic ...`).

def _enable_privileges(*names: str):
    from ctypes import wintypes

    class LUID(ctypes.Structure):
        _fields_ = [("Low", wintypes.DWORD), ("High", wintypes.LONG)]

    class TOKEN_PRIVILEGES(ctypes.Structure):
        _fields_ = [("Count", wintypes.DWORD), ("Luid", LUID), ("Attributes", wintypes.DWORD)]

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                        ctypes.POINTER(wintypes.HANDLE)]
    advapi.LookupPrivilegeValueW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR,
                                             ctypes.POINTER(LUID)]
    advapi.AdjustTokenPrivileges.argtypes = [wintypes.HANDLE, wintypes.BOOL,
                                             ctypes.POINTER(TOKEN_PRIVILEGES), wintypes.DWORD,
                                             ctypes.c_void_p, ctypes.c_void_p]
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0020 | 0x0008,
                                   ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        for name in names:
            tp = TOKEN_PRIVILEGES(Count=1, Attributes=0x2)   # SE_PRIVILEGE_ENABLED
            if not advapi.LookupPrivilegeValueW(None, name, ctypes.byref(tp.Luid)):
                raise ctypes.WinError(ctypes.get_last_error())
            advapi.AdjustTokenPrivileges(token, False, ctypes.byref(tp), 0, None, None)
            if ctypes.get_last_error():   # ERROR_NOT_ALL_ASSIGNED: not admin
                raise PermissionError(f"can't enable {name}")
    finally:
        kernel.CloseHandle(token)


class _BackupKey:
    """A registry key opened with the backup/restore privileges: Windows' audio keys
    belong to its own services, and these let an admin change them without taking
    ownership or touching their permissions."""

    def __init__(self, path: str, create: bool = True):
        from ctypes import wintypes
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        fn = advapi.RegCreateKeyExW
        fn.argtypes = [wintypes.HKEY, wintypes.LPCWSTR, wintypes.DWORD, wintypes.LPWSTR,
                       wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       ctypes.POINTER(wintypes.HKEY), ctypes.POINTER(wintypes.DWORD)]
        if not create:   # FileNotFoundError if it's not there; denied still means it is
            try:
                winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path).Close()
            except PermissionError:
                pass
        h = wintypes.HKEY()
        disp = wintypes.DWORD()
        err = fn(winreg.HKEY_LOCAL_MACHINE, path, 0, None, 0x4,   # REG_OPTION_BACKUP_RESTORE
                 winreg.KEY_ALL_ACCESS, None, ctypes.byref(h), ctypes.byref(disp))
        if err:
            raise ctypes.WinError(err)
        assert h.value is not None   # it opened
        self.h: int | winreg.HKEYType = h.value
        self.created = disp.value == 1   # REG_CREATED_NEW_KEY

    def get(self, name):
        try:
            return winreg.QueryValueEx(self.h, name)
        except OSError:
            return None

    def set(self, name, kind, value):
        winreg.SetValueEx(self.h, name, 0, kind, value)

    def set_raw(self, name, kind, data: bytes):
        """A value of any kind, byte for byte (winreg converts only the kinds it knows)."""
        from ctypes import wintypes
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        fn = advapi.RegSetValueExW
        fn.argtypes = [wintypes.HKEY, wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       ctypes.c_char_p, wintypes.DWORD]
        err = fn(self.h, name, 0, kind, data, len(data))
        if err:
            raise ctypes.WinError(err)

    def delete(self, name):
        try:
            winreg.DeleteValue(self.h, name)
        except FileNotFoundError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        winreg.CloseKey(self.h)


class _StateKey(_BackupKey):
    r"""Our own notes (HKLM\SOFTWARE\OnionBoard\MicPlugin): a plain admin key."""

    def __init__(self, path: str):
        self.h = winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_ALL_ACCESS)
        self.created = False


def _powershell(script: str) -> list[str]:
    """Windows PowerShell running `script` (from System32: systools)."""
    return [systools.tool("powershell"), "-NoProfile", "-NonInteractive", "-Command", script]


def _run(cmd: list[str], timeout: float = 60.0) -> int:
    """Run a command, hidden. Its exit code; -1 if it hung (it's stopped after `timeout`).
    A bare tool name (net, pnputil) is Windows' own, from System32: never one found in
    a PATH folder someone else can write to (systools)."""
    run = [systools.tool(cmd[0]), *cmd[1:]] if os.sep not in cmd[0] else cmd
    try:
        r = subprocess.run(run, capture_output=True, text=True, errors="replace",
                           timeout=timeout, creationflags=_CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        log.warning("%s: no answer in %.0f s, stopped", " ".join(cmd), timeout)
        return -1
    if r.returncode:
        log.warning("%s -> %s %s", " ".join(cmd), r.returncode, (r.stdout + r.stderr).strip())
    return r.returncode


AUDIO_SERVICES = ("AudioEndpointBuilder", "Audiosrv")
_SERVICE_NAME = re.compile(r"[A-Za-z0-9_.-]{1,80}")


def _running_dependents() -> list[str]:
    """The services running now that depend on Windows' audio ("Windows MIDI Service",
    "Agent Activation Runtime", some sound-card vendors' own): stopping the audio stops
    them too, and Windows doesn't start them again with it, so they're started by hand."""
    script = (f"Get-Service -Name {','.join(AUDIO_SERVICES)} -DependentServices "
              "-ErrorAction SilentlyContinue | Where-Object Status -eq Running | "
              "ForEach-Object Name")
    try:
        r = subprocess.run(_powershell(script),
                           capture_output=True, text=True, errors="replace", timeout=30,
                           creationflags=_CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        log.warning("couldn't list the services that depend on the audio")
        return []
    names = [n.strip() for n in r.stdout.splitlines()]
    return [n for n in dict.fromkeys(names) if _SERVICE_NAME.fullmatch(n)
            and n.lower() not in {s.lower() for s in AUDIO_SERVICES}]


def _audio_comes_back(dependents: Sequence[str] = ()):
    """A small helper that starts Windows' audio again once this process ends, however
    it ends: killed half-way or crashed, the PC must never be left without sound.
    (Starting a service that's already running does nothing.)"""
    names = [*AUDIO_SERVICES, *(n for n in dependents if _SERVICE_NAME.fullmatch(n))]
    script = (f"Wait-Process -Id {os.getpid()} -ErrorAction SilentlyContinue; "
              + "; ".join(f"Start-Service '{n}' -ErrorAction SilentlyContinue" for n in names))
    cmd = _powershell(script)
    for flags in (_CREATE_NO_WINDOW | 0x01000000, _CREATE_NO_WINDOW):   # out of our job
        try:
            subprocess.Popen(cmd, creationflags=flags, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            continue
    log.warning("no helper to bring the audio back if this stops half-way")


_SERVICE_STATES = {1: "Stopped", 2: "StartPending", 3: "StopPending", 4: "Running",
                   5: "ContinuePending", 6: "PausePending", 7: "Paused"}


def _service_states() -> dict[str, str] | None:
    """Windows' audio services' states ({"Audiosrv": "Stopped", ...}), asked of Windows'
    service manager itself; None if it can't tell. PowerShell alone, as before, said
    "not stopped" on PCs where it was slow or blocked (as the mic helper, too): exit
    code 6 with neither service named, though the audio had stopped."""
    from ctypes import wintypes

    class STATUS(ctypes.Structure):
        _fields_ = [(n, wintypes.DWORD) for n in ("type", "state", "accepted", "exit",
                                                   "service_exit", "check", "wait")]
    try:
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        advapi.OpenSCManagerW.restype = advapi.OpenServiceW.restype = wintypes.HANDLE
        advapi.OpenSCManagerW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
        advapi.OpenServiceW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD]
        advapi.QueryServiceStatus.argtypes = [wintypes.HANDLE, ctypes.POINTER(STATUS)]
        advapi.CloseServiceHandle.argtypes = [wintypes.HANDLE]
    except (AttributeError, OSError):
        return None
    scm = advapi.OpenSCManagerW(None, None, 0x0001)   # SC_MANAGER_CONNECT
    if not scm:
        return None
    states: dict[str, str] = {}
    try:
        for name in AUDIO_SERVICES:
            h = advapi.OpenServiceW(scm, name, 0x0004)   # SERVICE_QUERY_STATUS
            if not h:
                return None
            try:
                st = STATUS()
                if not advapi.QueryServiceStatus(h, ctypes.byref(st)):
                    return None
                states[name] = _SERVICE_STATES.get(st.state, "Unknown")
            finally:
                advapi.CloseServiceHandle(h)
    finally:
        advapi.CloseServiceHandle(scm)
    return states


def _services_stopped() -> bool:
    """Windows' audio is really stopped. The endpoint builder re-reads a mic's effect
    settings when it starts, so a stop that silently failed leaves the change unread
    until a restart: worth knowing."""
    states = _service_states()
    if states is not None:
        return all(s == "Stopped" for s in states.values())
    script = ("(Get-Service -Name " + ",".join(AUDIO_SERVICES) + " -ErrorAction SilentlyContinue"
              " | Where-Object Status -ne 'Stopped' | Measure-Object).Count")
    try:
        r = subprocess.run(_powershell(script),
                           capture_output=True, text=True, errors="replace", timeout=15,
                           creationflags=_CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.stdout.strip() == "0"


def _services_up() -> str:
    """Windows' audio services not stopped, with their state ("Audiosrv=StopPending"),
    or "" when all are stopped or it can't tell (a check: never fails)."""
    states = _service_states()
    if states is not None:
        return " ".join(f"{n}={s}" for n, s in states.items() if s != "Stopped")
    script = ("Get-Service -Name " + ",".join(AUDIO_SERVICES) + " -ErrorAction SilentlyContinue"
              " | Where-Object Status -ne 'Stopped'"
              " | ForEach-Object { \"$($_.Name)=$($_.Status)\" }")
    try:
        r = subprocess.run(_powershell(script),
                           capture_output=True, text=True, errors="replace", timeout=15,
                           creationflags=_CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return " ".join(r.stdout.split())


def _audio_service(start: bool, dependents: Sequence[str] = ()) -> bool:
    """Stop / start Windows' audio. The endpoint builder reads the mics' effect settings
    when it starts, so it goes too (the audio service depends on it). `dependents`: the
    services that were running on it (_running_dependents), started again after it.
    True when the audio ended up in the state asked for (a stop that didn't take is
    logged: the effect's change may not be read until a restart)."""
    if start:
        _run(["net", "start", "AudioEndpointBuilder"])
        _run(["net", "start", "audiosrv"])
        for name in dependents:
            if _SERVICE_NAME.fullmatch(name):
                _run(["net", "start", name], timeout=30.0)
        return True
    _run(["net", "stop", "audiosrv", "/y"])
    _run(["net", "stop", "AudioEndpointBuilder", "/y"])
    if _stopped_soon():
        return True
    # a dependency held it, or net gave up while it was still stopping: once more, with
    # longer for a slow sound-card driver (exit code 6 came from PCs that only stopped
    # a little after the first wait)
    _run(["net", "stop", "audiosrv", "/y"])
    _run(["net", "stop", "AudioEndpointBuilder", "/y"])
    if _stopped_soon(STOP_WAIT_S * 3):
        return True
    # what was still up, for the app to count (stuck_why) and for the log's reader
    log.warning("Windows' audio wouldn't stop: the mic effect may need a restart to take")
    log.warning("%s %s", AUDIO_STUCK, _services_up() or "unknown")
    return False


STOP_WAIT_S = 10.0   # how long a service still "stopping" gets before it counts as stuck
# the line logged when the audio wouldn't stop (directmic.stuck_why reads it)
AUDIO_STUCK = "audio still up:"


def _stopped_soon(wait_s: float | None = None) -> bool:
    """_services_stopped(), given up to STOP_WAIT_S: a slow sound-card driver keeps the
    audio "stopping" for seconds after net stop has returned (exit code 6 on a PC
    where it would have stopped a moment later)."""
    give_up = time.monotonic() + (STOP_WAIT_S if wait_s is None else wait_s)
    while True:
        if _services_stopped():
            return True
        if time.monotonic() >= give_up:
            return False
        time.sleep(1.0)


# (Restarting only the mic a step changed, pnputil /restart-device on its endpoint, was
# tried in place of all of the audio and dropped: a USB headset's mic came back without
# the effect, twice in a row, and a mic it came off refused every app until all of the
# audio restarted. A full restart worked on every mic.)


def _restart_audio() -> bool:
    """Restart all of Windows' audio (the services that ran on it too), and put SteelSeries
    Sonar's devices back after it (_sonar_back). False if it wouldn't stop (it's started
    again either way)."""
    dependents = _running_dependents()
    _audio_comes_back(dependents)
    try:
        return _audio_service(False)
    finally:
        _audio_service(True, dependents)
        _sonar_back()


def _register_com(dll: Path):
    clsid_key = rf"SOFTWARE\Classes\CLSID\{CLSID}"
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, clsid_key, 0, winreg.KEY_ALL_ACCESS) as k:
        winreg.SetValueEx(k, None, 0, winreg.REG_SZ, "Onion Board mic")
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, clsid_key + r"\InprocServer32", 0,
                            winreg.KEY_ALL_ACCESS) as k:
        winreg.SetValueEx(k, None, 0, winreg.REG_SZ, str(dll))
        winreg.SetValueEx(k, "ThreadingModel", 0, winreg.REG_SZ, "Both")
    apo_key = rf"SOFTWARE\Classes\AudioEngine\AudioProcessingObjects\{CLSID}"
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, apo_key, 0, winreg.KEY_ALL_ACCESS) as k:
        for name, value in (("FriendlyName", "Onion Board mic"),
                            ("Copyright", "Onion Board contributors"),
                            ("APOInterface0", "{FD7F2B29-24D0-4B5C-B177-592C39F9CA10}")):
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
        for name, value in (("MajorVersion", 1), ("MinorVersion", 0), ("Flags", 14),
                            ("MinInputConnections", 1), ("MaxInputConnections", 1),
                            ("MinOutputConnections", 1), ("MaxOutputConnections", 1),
                            ("MaxInstances", 0xFFFFFFFF), ("NumAPOInterfaces", 1)):
            winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, value)


def _unregister_com():
    for path in (rf"SOFTWARE\Classes\CLSID\{CLSID}\InprocServer32",
                 rf"SOFTWARE\Classes\CLSID\{CLSID}",
                 rf"SOFTWARE\Classes\AudioEngine\AudioProcessingObjects\{CLSID}"):
        try:
            winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, path)
        except FileNotFoundError:
            pass


def pick_slot(values: Mapping[int, object]) -> tuple[str, int]:
    """Which effect slot the effect takes on a mic whose FxProperties hold `values`
    ({pid: value}): ('wrap', LFX) on a driver with only the old kind of effects;
    ('composite', 15) joins an endpoint effect list Windows chains by itself; otherwise
    ('wrap', EFX), the endpoint effect raw streams get too. 'wrap' replaces that slot's
    effect, and the effect runs the one it replaced first."""
    if any(values.get(p) for p in LEGACY) and not any(values.get(p) for p in MODERN) \
            and not values.get(COMPOSITE_SFX):
        return "wrap", LFX
    if values.get(COMPOSITE_EFX) and _clsid_list(values[COMPOSITE_EFX]) is not None:
        return "composite", COMPOSITE_EFX
    return "wrap", EFX


def _clsid_list(value) -> list[str] | None:
    """An endpoint effect list's CLSIDs: a list of texts, or one effect held as plain
    text; None for any other kind (raw bytes from a driver), which isn't joined: it
    raised half-way through a set-up (exit code 1), and a text was split into letters."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(c, str) for c in value):
        return value
    return None


def _original(values: Mapping[int, object], pid: int) -> str:
    """The effect the effect runs first in slot `pid`: the slot's own, or (a mic whose
    driver has no endpoint effect) its old-style LFX, which a modern slot switches off."""
    old = values.get(pid)
    if not old and pid in (SFX, EFX) and not values.get(EFX):
        old = values.get(LFX)
    return old if isinstance(old, str) and not _is_ours(old) else ""


def _install_endpoint(guid: str, slot: str | None):
    """Put the effect on one mic. Everything changed is noted under ENDPOINTS_KEY so
    _uninstall_endpoint can put it back exactly."""
    base = rf"{CAPTURE_KEY}\{guid}"
    with _BackupKey(base + r"\FxProperties") as fx, \
            _StateKey(rf"{ENDPOINTS_KEY}\{guid}") as state:
        values = {p: (fx.get(FX % p) or (None,))[0]
                  for p in (*MODERN, *LEGACY, COMPOSITE_SFX, COMPOSITE_EFX)}
        kind, pid = pick_slot(values) if not slot else ("wrap", SLOTS_FX[slot])
        if _is_eapo(values.get(pid)) and eapo_runs_us(guid):
            # Equalizer APO went on after this effect and runs it: wrapping it back
            # would make each run the other. Notes kept (or, lost, made: nothing to
            # put back in the slot, Equalizer APO is handed the effect it ran)
            if not state.get("Slot"):
                state.set("Slot", winreg.REG_DWORD, pid)
                state.set("Before", winreg.REG_MULTI_SZ, [])
                state.set("Original", winreg.REG_SZ, "")
            log.info("mic effect on %s: run by Equalizer APO (slot %s)", guid, pid)
            return
        modes = SFX if pid in (SFX, COMPOSITE_SFX) else EFX if pid in ENDPOINT_SLOTS else None
        state.set("FxCreated", winreg.REG_DWORD, 1 if fx.created else 0)
        state.set("Slot", winreg.REG_DWORD, pid)
        # every value this touches, as it was, to put back later (written before anything
        # changes, so a step cut off half-way can still be undone)
        names = (FX % pid, MODES_KEY % SFX, MODES_KEY % EFX, FX % LFX, FX % GFX, DISABLE_SYSFX)
        state.set("Before", winreg.REG_MULTI_SZ, [_note(n, fx.get(n)) for n in names])
        if kind == "composite":
            cur = _clsid_list(values[pid]) or []
            fx.set(FX % pid, winreg.REG_MULTI_SZ,
                   [CLSID] + [c for c in cur if c.upper() != CLSID])
            state.set("Original", winreg.REG_SZ, "")
        else:
            state.set("Original", winreg.REG_SZ, _original(values, pid))
            fx.set(FX % pid, winreg.REG_SZ, CLSID)
        if modes is not None:
            if not fx.get(MODES_KEY % modes):
                fx.set(MODES_KEY % modes, winreg.REG_MULTI_SZ, [MODE_DEFAULT])
            # a modern effect on the mic switches the old-style ones off anyway
            fx.delete(FX % LFX)
            fx.delete(FX % GFX)
        if fx.get(DISABLE_SYSFX):   # "Audio enhancements: off" would stop every effect
            fx.delete(DISABLE_SYSFX)
    log.info("mic effect on %s (slot %s)", guid, pid)


def _note(name: str, v) -> str:
    """One value as it was, for the "Before" notes: `name=` (wasn't there),
    `name=sz:...`, `name=multi:a|b`, `name=dword:N`, or `name=raw:<type>:<hex>` for any
    other kind, so it goes back exactly as it was. This effect's own CLSID is never
    noted as an original (notes lost while it was on the mic): it's left out."""
    if v is None:
        return f"{name}="
    value, kind = v
    if kind == winreg.REG_MULTI_SZ and all(isinstance(x, str) for x in value or []):
        return f"{name}=multi:" + "|".join(x for x in value or [] if x.upper() != CLSID)
    if kind == winreg.REG_DWORD:
        return f"{name}=dword:{int(value)}"
    if kind == winreg.REG_SZ and isinstance(value, str):
        return f"{name}=" if value.upper() == CLSID else f"{name}=sz:{value}"
    if isinstance(value, bytes):
        raw = value
    elif isinstance(value, int):
        raw = value.to_bytes(8 if kind == winreg.REG_QWORD else 4, "little", signed=value < 0)
    elif value is None:
        raw = b""
    else:
        raw = (str(value) + "\0").encode("utf-16-le")
    return f"{name}=raw:{kind}:{raw.hex()}"


def _note_value(item: str):
    """The value a "Before" note puts back (None: it wasn't there). A raw note (an odd
    kind) can't be compared to what's there: `_MISSING`."""
    _, _, value = item.partition("=")
    if not value:
        return None
    if value.startswith("multi:"):
        return value[6:].split("|") if value[6:] else []
    if value.startswith("dword:"):
        return int(value[6:])
    if value.startswith("raw:"):
        return _MISSING
    return value.removeprefix("sz:")


_MISSING = object()


def _put_back(fx, item: str):
    """Undo one "Before" note (see _note)."""
    name, _, value = item.partition("=")
    if not value:
        fx.delete(name)
    elif value.startswith("multi:"):
        fx.set(name, winreg.REG_MULTI_SZ, value[6:].split("|") if value[6:] else [])
    elif value.startswith("dword:"):
        fx.set(name, winreg.REG_DWORD, int(value[6:]))
    elif value.startswith("raw:"):
        kind, _, data = value[4:].partition(":")
        fx.set_raw(name, int(kind), bytes.fromhex(data))
    else:
        fx.set(name, winreg.REG_SZ, value.removeprefix("sz:"))


def _uninstall_endpoint(guid: str):
    """Put one mic back as it was before _install_endpoint. If Windows already took the
    effect off (a driver update or "Reset sound settings" rewrote the mic's effects),
    what's there now is the driver's own and stays: the notes are only dropped. If the
    uninstall itself was cut off half-way (a crash, a reboot), the slot already matches
    the notes and the rest of the change is finished now."""
    base = rf"{CAPTURE_KEY}\{guid}"
    with _StateKey(rf"{ENDPOINTS_KEY}\{guid}") as state:
        before = (state.get("Before") or ([],))[0] or []
        created = (state.get("FxCreated") or (0,))[0]
        slot = (state.get("Slot") or (None,))[0]
        original = (state.get("Original") or ("",))[0]
        if not before and slot is not None:   # an early test build's notes
            before = [f"{FX % slot}=sz:{original}" if original else f"{FX % slot}="]
            modes_created = (state.get("ModesCreated") or (0,))[0]
            if modes_created:
                before.append(f"{MODES_KEY % modes_created}=")
            if (state.get("AssocCreated") or (0,))[0]:
                before.append(f"{FX % 0}=")
    try:
        with _BackupKey(base + r"\FxProperties", create=False) as fx:
            if slot is None:
                restore = any(_is_ours((fx.get(FX % p) or (None,))[0]) for p in OUR_SLOTS)
            else:
                cur = (fx.get(FX % slot) or (None,))[0]
                want = _note_value(next((b for b in before
                                         if b.partition("=")[0] == FX % slot),
                                        f"{FX % slot}="))
                # our CLSID still in the slot, or the slot already matches the notes (an
                # uninstall cut off half-way): finish it. A slot holding some other value
                # means Windows reset the mic: leave it all.
                restore = _is_ours(cur) or cur == want
                if not restore and _is_eapo(cur):
                    # Equalizer APO took the slot after this effect and runs it: it
                    # runs the mic's own effect again instead. The rest stays as it set
                    # it (the old "Audio enhancements: off" would switch it off too)
                    _eapo_hand_back(guid, original)
            if restore:
                for item in before:
                    _put_back(fx, item)
            else:
                log.info("%s: Windows already took the effect off; left as it is", guid)
        if created and restore:
            _delete_if_empty(base + r"\FxProperties")
    except FileNotFoundError:
        pass   # the mic is gone
    winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, rf"{ENDPOINTS_KEY}\{guid}")
    log.info("mic effect taken off %s", guid)


def _delete_if_empty(path: str):
    with _BackupKey(path, create=False) as k:
        n = winreg.QueryInfoKey(k.h)
    if n[0] == 0 and n[1] == 0:
        from ctypes import wintypes
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        fn = advapi.RegDeleteKeyW
        # without these, ctypes passes HKEY_LOCAL_MACHINE (0x80000002) as a C int:
        # ArgumentError, and the effect's notes were never cleared
        fn.argtypes = [wintypes.HKEY, wintypes.LPCWSTR]
        fn.restype = wintypes.LONG
        err = fn(winreg.HKEY_LOCAL_MACHINE, path)
        if err:   # an empty key left behind is harmless
            log.warning("couldn't delete the empty %s: %s", path, ctypes.FormatError(err))


# Who may do what in the data folders. %ProgramData%\OnionBoard: admins only (its logs
# are the admin step's). MicPlugin: the audio engine (LOCAL SERVICE with a write-
# restricted token, so WRITE RESTRICTED too) and signed-in users make and change files
# in it, but can't delete, rename or swap the folder itself, nor make folders in it.
# Nothing for store apps. Owner: Administrators.
_READ = "0x1200a9"          # read & run
_FOLDER_WRITE = "0x1201bb"  # read, make files, write attributes: no delete, no subfolders
_MODIFY = "0x1301bf"
_BASE_SDDL = f"O:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;{_READ};;;BU)"
_MIC_SDDL = _BASE_SDDL + "".join(f"(A;;{_FOLDER_WRITE};;;{s})(A;OICIIO;{_MODIFY};;;{s})"
                                 for s in ("AU", "LS", "WR"))
_ADMIN_SIDS = ("S-1-5-32-544", "S-1-5-18")   # Administrators, SYSTEM
_REPARSE = 0x400                             # FILE_ATTRIBUTE_REPARSE_POINT


def _is_link(path: Path) -> bool:
    """A symlink, junction or other reparse point (never followed by the admin step)."""
    try:
        return bool(getattr(os.lstat(path), "st_file_attributes", 0) & _REPARSE)
    except OSError:
        return False


def _remove_entry(path: Path):
    """Remove one folder entry itself, never what a link points at, nor what a link
    inside it points at: someone else's folder goes through handles to its checked
    folders (safefs), never by paths they could re-point half-way."""
    left = safefs.remove_tree(path)
    if left:
        raise PermissionError(f"couldn't remove {left[0]} (in use)")


def _make_dir(path: Path, sddl: str):
    """A new folder with `sddl`'s access from the moment it exists: never a moment with
    what it would inherit from %ProgramData%, where anyone may add to it."""
    from ctypes import wintypes
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    kernel.CreateDirectoryW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]

    class Attributes(ctypes.Structure):   # SECURITY_ATTRIBUTES
        _fields_ = [("length", wintypes.DWORD), ("sd", ctypes.c_void_p),
                    ("inherit", wintypes.BOOL)]
    sd = ctypes.c_void_p()
    if advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(sd),
                                                                   None):
        try:
            if kernel.CreateDirectoryW(str(path), ctypes.byref(
                    Attributes(ctypes.sizeof(Attributes), sd, False))):
                return
        finally:
            kernel.LocalFree(sd)
    path.mkdir()   # (an owner this account can't set: _secure_dir then says so)


def _secure_dir(path: Path, sddl: str) -> str | None:
    """Make `path` a real folder owned by Administrators with exactly `sddl`'s access, set
    on an open handle to the folder itself: never through a link, and without touching
    anything inside (no inheritance walk a planted link could steer). Its owner SID
    before (None if it was made just now). One someone else made (only the admin step
    makes these) is replaced, not re-secured: a handle they opened before keeps the
    access it was opened with, enough to change it back or swap it later."""
    from ctypes import wintypes
    if _is_link(path) or (path.exists() and not path.is_dir()):
        log.warning("%s wasn't a plain folder: replaced", path)
        _remove_entry(path)
    owner = _owner(path) if path.exists() else None
    if owner is not None and owner not in _ADMIN_SIDS:
        log.warning("%s was made by %s: replaced", path, owner)
        _remove_entry(path)   # (in use by them: PermissionError, the step stops)
    if not path.exists():
        _make_dir(path, sddl)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.HANDLE]
    kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    advapi.SetKernelObjectSecurity.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p]
    # READ_CONTROL | WRITE_DAC | WRITE_OWNER; FILE_FLAG_BACKUP_SEMANTICS | OPEN_REPARSE_POINT
    h = kernel.CreateFileW(str(path), 0x000E0000, 7, None, 3, 0x02200000, None)
    if h in (None, wintypes.HANDLE(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        info = (ctypes.c_ulong * 13)()   # BY_HANDLE_FILE_INFORMATION
        if not kernel.GetFileInformationByHandle(wintypes.HANDLE(h), info):
            raise ctypes.WinError(ctypes.get_last_error())
        if info[0] & _REPARSE or not info[0] & 0x10:   # swapped for a link since the check
            raise PermissionError(f"{path} isn't a plain folder")
        sd = ctypes.c_void_p()
        if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, 1, ctypes.byref(sd), None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            # (OWNER |) DACL | PROTECTED_DACL: the folder's own security only, no walk
            what = 0x80000004 | (1 if sddl.startswith("O:") else 0)
            if not advapi.SetKernelObjectSecurity(h, what, sd):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            kernel.LocalFree(sd)
    finally:
        kernel.CloseHandle(h)
    return owner


def _owner(path: Path) -> str | None:
    """The owner SID of one entry itself (links are never asked: they're removed first)."""
    from ctypes import wintypes
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi.GetNamedSecurityInfoW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD,
                                             ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
                                             ctypes.c_void_p, ctypes.c_void_p,
                                             ctypes.POINTER(ctypes.c_void_p)]
    advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    sid, sd = ctypes.c_void_p(), ctypes.c_void_p()
    if advapi.GetNamedSecurityInfoW(str(path), 1, 1, ctypes.byref(sid), None, None, None,
                                    ctypes.byref(sd)):
        return None
    try:
        text = ctypes.c_wchar_p()
        if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            return None
        value = text.value
        kernel.LocalFree(text)
        return value
    finally:
        kernel.LocalFree(sd)


def _clean_base(base: Path):
    """Once the base folder is admins-only (nobody else can add to it), drop what someone
    else could have put there before: links, hard links, anything not admin-owned. The
    admin step writes its log there, and must never write through a planted link. A
    folder of theirs goes through handles (_remove_entry): they still own what's in it,
    and could swap a folder deep inside for a link while it's being removed."""
    for entry in list(base.iterdir()):
        if entry.name == "MicPlugin":
            continue
        try:
            st = os.lstat(entry)
            if getattr(st, "st_file_attributes", 0) & _REPARSE or st.st_nlink > 1 \
                    or _owner(entry) not in _ADMIN_SIDS:
                log.warning("removed %s from the data folder (not the admin step's)", entry.name)
                _remove_entry(entry)
        except OSError:
            log.warning("couldn't check %s", entry, exc_info=True)


def secure_data_dirs():
    """Admin step, first thing: %ProgramData%\\OnionBoard and its MicPlugin folder made
    safe before anything is written there (anyone signed in can make folders in
    %ProgramData%, so either could be someone else's, or a link to a system folder)."""
    base = data_dir().parent
    base.parent.mkdir(parents=True, exist_ok=True)
    _secure_dir(base, _BASE_SDDL)
    _clean_base(base)
    _secure_dir(data_dir(), _MIC_SDDL)


def _make_ring():
    """A fresh ring file for the effect to find when the audio starts, made without
    ever writing through a link someone else put in the (user-writable) folder: a new
    file of our own, then swapped in by name."""
    path = ring_path()
    if make_ring_ok(path):
        return
    try:
        folder = safefs.Folder(path.parent)
    except (FileNotFoundError, safefs.NotPlain):
        # a reinstall's uninstall removed the folder (nothing held the ring open, as a
        # running board does), or someone turned it into a link: made again, as safe
        # as the admin step makes it at first
        secure_data_dirs()
        folder = safefs.Folder(path.parent)
    # all of it relative to the folder's handle: signed-in users write in it, and could
    # turn it into a link between one step and the next
    with folder:
        tmp = f"ring2.{os.getpid()}-{int(time.monotonic() * 1000)}.tmp"
        folder.write_new(tmp, new_ring_bytes())
        try:
            folder.replace(tmp, path.name)   # replaces the entry itself, never a link's target
        except BaseException:
            folder.delete(tmp)
            raise
        folder.delete("ring.bin")   # the first test build's (the entry itself)


def _audio_off(work, also: Sequence[str] = ()) -> int:
    """Run `work` (it returns an exit code) with Windows' audio stopped: the endpoint
    builder reads the mics' effect settings when it starts. The audio always starts
    again, however `work` ends; if it won't stop, nothing is touched (6). `work` done,
    the audio back, and then checked (_after_restart): the effect has to start on its mic
    (else EFFECT_NOT_STARTED) and every mic the step changed that apps could open before
    has to open again (else MIC_SHUT), each given one more restart first. A mic still
    sending only silence after every restart (_mics_come_back_live): MIC_SILENT. A mic
    (the effect's, or `also`: the one it goes on) that was already silent before isn't
    the step's doing: a headset that's switched off, or its mic muted, sends only zeros
    too, and restarting the audio for it only cut the sound."""
    _enable_privileges("SeBackupPrivilege", "SeRestorePrivilege")
    touched = [*installed_on(), *also]
    # a mic the last step left silent (MIC_SILENT, just now) is silent before this retry
    # too, but that's the stuck mic the retry is for: it still gets the extra restarts
    quiet = _silent_before(touched) - _left_silent()
    opened = _mics_open(touched)
    apps_quiet = _mic_apps_quiet()
    _sonar_keep()
    dependents = _running_dependents()
    _audio_comes_back(dependents)
    mics: list[str] | None = None
    code: int | None = None
    checked = mark = 0
    try:
        if not _audio_service(False):
            return 6   # don't rewrite a live endpoint if Windows couldn't stop its audio
        mark = _apo_log_size()   # (no effect runs now: what it logs after this is new)
        mics = installed_on()   # the one it comes off is listened to as well
        code = work()
    finally:
        _audio_service(True, dependents)
        _sonar_back()
        if _sonar_fixed is False:   # before its mic is listened to: it's silent until then
            _mic_apps_back(apps_quiet)
        if code == 0:
            checked = _after_restart(opened, mark)
        live = mics is None or _mics_come_back_live(mics, quiet)
        _mic_apps_back(apps_quiet)
    if code is None:   # (work raised: its exception goes on from the finally above)
        return 1
    if code == 0 and checked:
        return checked
    return MIC_SILENT if code == 0 and not live else code


EFFECT_NOT_STARTED = 8   # the step was done, but the effect didn't start on its mic
MIC_SHUT = 9             # the step was done, but a mic apps could open before won't open


def _after_restart(opened: Collection[str], mark: int) -> int:
    """After a step's audio restart: the effect started on each mic it's on now
    (_effect_runs; its log from `mark` on), and each mic in `opened` (apps could open it
    before the step) opens again (_mics_open). Either not: all of Windows' audio restarts
    once more and they're checked again. 0 when both are fine (a check that can't tell
    counts as fine), else EFFECT_NOT_STARTED or MIC_SHUT."""
    for again in (False, True):
        runs = _effect_runs(installed_on(), mark)
        now = _mics_open(opened)
        shut = [g for g in opened if g not in now]
        if runs and not shut:
            return 0
        if not runs:
            log.warning("the effect didn't start on its mic after the audio restart")
        if shut:
            log.warning("%s won't open after the audio restart", ", ".join(shut))
        if again:
            return MIC_SHUT if shut else EFFECT_NOT_STARTED
        log.warning("restarting Windows' audio once more")
        mark = _apo_log_size()
        _restart_audio()
    return 0


def _mics_open(guids: Collection[str]) -> set[str]:
    """The mics among `guids` an app can open now (appaudio.mic_opens), lowercase. One
    that can't be told about (unplugged, the check failing) isn't in it: it isn't
    checked again after the step either. A check: never fails."""
    from soundboard.audio import appaudio
    opens = set()
    for g in dict.fromkeys(g.lower() for g in guids):
        try:
            ok = appaudio.mic_opens(g)
        except Exception:  # noqa: BLE001
            log.info("couldn't open mic %s", g, exc_info=True)
            ok = None
        if ok:
            opens.add(g)
        elif ok is False:
            log.info("mic %s doesn't open", g)
    return opens


APO_LOG = "apo.log"     # in data_dir(): the effect's own log (obmic.cpp logv)
EFFECT_START_S = 5      # how long a mic gets to start the effect once it's opened


def _apo_log_size() -> int:
    """The effect's log's size now (0 without one): what's written after it is new."""
    try:
        return (data_dir() / APO_LOG).stat().st_size
    except OSError:
        return 0


def _effect_started(mark: int) -> str:
    """What the effect logged since `mark` (all of it if the log was started again
    meanwhile: it does at 256 kB), lowercased. A check: never fails."""
    try:
        with open(data_dir() / APO_LOG, "rb") as f:
            if f.seek(0, 2) >= mark:
                f.seek(mark)
            else:
                f.seek(0)
            return f.read().decode("utf-8", "replace").lower()
    except OSError:
        return ""


APO_LOG_BURST = 40   # the effect logs at most this many lines a process per 10 s (obmic.cpp
                     # LOG_BURST): the rest are dropped, and the next line says how many
_APO_PID = re.compile(r"\bpid (\d+): ")


def _apo_log_capped(text: str) -> bool:
    """The effect's log `text` (since a mark) hit its cap: a process wrote APO_LOG_BURST
    lines, or a line says some were skipped. Right after an audio restart Windows starts
    the effect on every mic and asks it about formats many times, so its "initialize"
    line could be among the dropped ones: it may well have started (exit code 8 on PCs
    where it had)."""
    if "lines skipped)" in text:
        return True
    per_pid = Counter(m.group(1) for m in map(_APO_PID.search, text.splitlines()) if m)
    return bool(per_pid) and max(per_pid.values()) >= APO_LOG_BURST


# the line logged when the effect didn't start on a mic (directmic.unstarted_why reads
# it), with what its log showed instead: nothing at all (Windows loaded it nowhere, or it
# couldn't write its log), lines but no start, starts on a mic it couldn't name, or
# starts only on other mics
UNSTARTED = "effect not started:"
UNSTARTED_HOW = ("silent", "no-init", "unnamed", "other-mics")


def _unstarted_how(text: str) -> str:
    """An UNSTARTED_HOW word for the effect's log `text` (since a mark, lowercased) when
    it didn't start on a mic it's on."""
    if not text.strip():
        return "silent"
    starts = re.findall(r"initialize: endpoint ([^,\s]*)", text)
    return ("no-init" if not starts else "unnamed" if not all(starts) else
            "other-mics")


def _effect_runs(guids: Sequence[str], mark: int) -> bool:
    """The effect started on each of the active mics `guids` after the step (it logs
    "initialize: endpoint <guid>" whenever Windows starts it on a mic): each is opened
    once to make it, if no app has it open already. False if one doesn't within
    EFFECT_START_S; True when there's nothing to check or the check itself fails."""
    try:
        active = {e["guid"].lower() for e in capture_endpoints() if e["active"]}
        waiting = [g.lower() for g in guids if g.lower() in active]
        end = time.monotonic() + EFFECT_START_S
        while waiting:
            text = _effect_started(mark)
            waiting = [g for g in waiting if f"initialize: endpoint {g}" not in text]
            if not waiting or time.monotonic() > end:
                break
            _mics_open(waiting)   # opening one starts the effect on it (muted too)
        text = _effect_started(mark) if waiting else ""
        if waiting and _apo_log_capped(text):
            log.info("the effect's log was full: can't tell it started on %s",
                     ", ".join(waiting))
            return True
        if waiting:
            log.warning("the effect didn't start on %s", ", ".join(waiting))
            # what its log showed instead, for the app to count (unstarted_why)
            log.warning("%s %s", UNSTARTED, _unstarted_how(text))
        return not waiting
    except Exception:  # noqa: BLE001
        log.info("couldn't check that the effect started", exc_info=True)
        return True


# Apps that put a mic of their own between the real mic and voice chat (the chat app
# records theirs): (their process, the process that starts it again when it ends, the
# name their mic starts with). A restart of Windows' audio leaves their mic sending only
# silence until they start again, so the voice chat hears nothing; ended, they're
# started again by their own app within seconds, and that's how they're restarted here.
SONAR_EXE = "SteelSeriesSonar.exe"
MIC_APPS = (
    (SONAR_EXE, "SteelSeriesGGEZ.exe", "SteelSeries Sonar - Microphone"),
)
MIC_APP_BACK_S = 30   # how long a restarted mic app gets to be running again


def _mic_app_mics(mic: str) -> list[str]:
    """The active mics whose name starts with `mic` (a mic app's own)."""
    return [e["guid"].lower() for e in capture_endpoints()
            if e["active"] and e["name"].startswith(mic)]


def _mic_apps_quiet() -> set[str]:
    """The running mic apps' (MIC_APPS) mics sending only silence before a step, or
    that can't be listened to (_heard_before): not shown to be the step's doing (the app
    switched off, or set up to send nothing), so they're left alone after it. A check:
    never fails the step."""
    quiet = set()
    try:
        for exe, _parent, mic in MIC_APPS:
            if _processes(exe):
                quiet |= {g for g in _mic_app_mics(mic) if _heard_before(g) is not False}
    except Exception:  # noqa: BLE001
        log.info("couldn't listen to the mic apps before the step", exc_info=True)
    return quiet


def _mic_apps_back(quiet: Collection[str] = ()) -> None:
    """After a restart of Windows' audio: each mic app (MIC_APPS) whose mic now sends
    only silence is restarted (ended, for its own app to start it again), once, and its
    mic listened to again. Only one its own app will start again is ended, and never
    one whose mic was silent before the step already (`quiet`, _mic_apps_quiet): that
    silence isn't the restart's, and ending it lost the app for good when its own app
    didn't start it again. Sonar whose devices were set back (_sonar_back) is left
    running; one whose own server answered but whose devices wouldn't go back is
    restarted, silent before or not: its server says it's off. A check: never fails the
    step."""
    global _sonar_ended
    try:
        for exe, parent, mic in MIC_APPS:
            if exe == SONAR_EXE and (_sonar_fixed or _sonar_ended):
                continue
            running = _processes(exe)
            if not running:
                continue
            if exe == SONAR_EXE and _sonar_fixed is False:
                guids = _mic_app_mics(mic)
            else:
                guids = [g for g in _mic_app_mics(mic) if g not in quiet]
                if not guids or not any(_silent(g) for g in guids):
                    continue
            if not all(p == parent.lower() for _, p in running):
                log.warning("%s's mic sends only silence after the audio restart, but "
                            "nothing would start it again: left as it is", exe)
                continue
            log.info("%s's mic sends only silence after the audio restart: restarting it",
                     exe)
            old = {pid for pid, _ in running}
            _sonar_ended = _sonar_ended or exe == SONAR_EXE
            for pid in old:
                subprocess.run([systools.tool("taskkill"), "/F", "/PID", str(pid)],
                               capture_output=True, timeout=15,
                               creationflags=_CREATE_NO_WINDOW)
            end = time.monotonic() + MIC_APP_BACK_S
            while not {p for p, _ in _processes(exe)} - old:
                if time.monotonic() > end:
                    log.warning("%s didn't start again within %d s", exe, MIC_APP_BACK_S)
                    break
                time.sleep(1)
            else:
                if exe == SONAR_EXE:
                    _sonar_keep_again()
                silent = [g for g in guids if _silent(g)]
                log.info("%s is back; its mic: %s", exe,
                         "still only silence" if silent else "sound")
    except Exception:  # noqa: BLE001 - a check: never fails the step
        log.warning("couldn't check the mic apps after the audio restart", exc_info=True)


# SteelSeries Sonar sends its mic (and plays its Game / Chat / Media / Aux channels) through
# devices it picked: a restart of Windows' audio drops its mic device (its mic then sends
# only exact zeros) and moves its channels onto other devices, and it doesn't pick them
# back. Its own local web server (what SteelSeries GG's window uses) sets a channel's
# device: so the devices it had before a step are noted (_sonar_keep) and set again after
# each audio restart (_sonar_back), with Sonar left running. Ending Sonar for SteelSeries
# GG to start it again did the same, but GG starts it again only 3 times in a session.
GG_PROPS = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "SteelSeries" / "GG" / \
    "coreProps.json"
SONAR_ROUTES = (("classicRedirections", "id"), ("streamRedirections", "streamRedirectionId"))
SONAR_BACK_S = 20    # how long Sonar's devices get to be set again after an audio restart
SONAR_SETTLE_S = 8   # ...watched at least this long: Sonar picks devices of its own meanwhile
SONAR_START_S = 3    # how long a channel set again gets to say it runs before it's moved
SONAR_AWAY_S = 2     # ...how long on no device before it's set back (at once: 1 in 4 start)
_NO_DEVICE = "{00000000-0000-0000-0000-000000000000}"
_DEVICE_ID = re.compile(r"\{0\.0\.[01]\.00000000\}\.\{[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-"
                        r"[0-9a-fA-F]{12}\}")
_ROUTE_ID = re.compile(r"[A-Za-z]{1,40}")
_sonar_saved: dict[tuple[str, str], tuple[str, bool]] | None = None   # (_sonar_keep)
_sonar_fixed: bool | None = None   # the last _sonar_back: True set, False not, None no Sonar
_sonar_ended = False   # Sonar was restarted in this step already (once at most)


def _local_http(method: str, address: str, path: str, tls: bool = False) -> bytes:
    """`method` `path` on a server on this PC at `address` ("127.0.0.1:port", from a file
    any user can write: nothing else is ever connected to). Its answer; OSError if it
    isn't 2xx or doesn't answer."""
    import http.client
    host, _, port = address.removeprefix("http://").rstrip("/").rpartition(":")
    if host != "127.0.0.1" or not port.isdigit() or not 0 < int(port) < 65536:
        raise OSError(f"not a local address: {address!r}")
    if tls:   # SteelSeries GG's own: a certificate it made itself, on this PC only
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        conn = http.client.HTTPSConnection(host, int(port), timeout=5, context=ctx)
    else:
        conn = http.client.HTTPConnection(host, int(port), timeout=5)
    try:
        conn.request(method, path)
        r = conn.getresponse()
        body = r.read(1 << 20)
    except (http.client.HTTPException, ValueError) as e:
        raise OSError(str(e)) from e
    finally:
        conn.close()
    if not 200 <= r.status < 300:
        raise OSError(f"{method} {path}: HTTP {r.status}")
    return body


def _sonar_address() -> str:
    """Sonar's web server ("http://127.0.0.1:port"), as SteelSeries GG lists it. OSError
    when GG or Sonar isn't running."""
    try:
        gg = json.loads(GG_PROPS.read_text(encoding="utf-8"))["ggEncryptedAddress"]
        apps = json.loads(_local_http("GET", str(gg), "/subApps", tls=True))
        sonar = apps["subApps"]["sonar"]
        if not sonar.get("isRunning"):
            raise OSError("Sonar isn't running")
        return str(sonar["metadata"]["webServerAddress"])
    except (KeyError, TypeError, ValueError) as e:
        raise OSError(f"no Sonar address: {e}") from e


def _sonar_routes(address: str) -> dict[tuple[str, str], tuple[str, bool]]:
    """Sonar's channels now: {(list, channel): (its device, running)}, both lists (its
    classic and its streamer mode), channels without a device left out."""
    routes = {}
    for kind, key in SONAR_ROUTES:
        try:
            got = json.loads(_local_http("GET", address, "/" + kind))
        except ValueError as e:
            raise OSError(f"{kind}: {e}") from e
        for r in got if isinstance(got, list) else ():
            rid, dev = r.get(key) if isinstance(r, dict) else None, r.get("deviceId")
            if isinstance(rid, str) and _ROUTE_ID.fullmatch(rid) and isinstance(dev, str) \
                    and _DEVICE_ID.fullmatch(dev):
                routes[(kind, rid)] = (dev.lower(), bool(r.get("isRunning")))
    return routes


def _sonar_mic_runs(address: str, now: Mapping[tuple[str, str], tuple[str, bool]]) -> bool:
    """Sonar's mic channel (its streamer mode's in that mode) has a device and runs."""
    try:
        mode = json.loads(_local_http("GET", address, "/mode"))
    except (OSError, ValueError):
        mode = ""
    return now.get(("streamRedirections" if mode == "stream" else "classicRedirections",
                    "mic"), ("", False))[1]


def _sonar_keep(again: bool = False) -> None:
    """Note Sonar's devices before a step (None when it isn't running or doesn't
    answer); `again`: in it, Sonar restarted. A check: never fails the step."""
    global _sonar_saved, _sonar_fixed, _sonar_ended
    _sonar_saved, _sonar_fixed = None, None
    _sonar_ended = _sonar_ended and again
    try:
        if not _processes(SONAR_EXE):
            return
        _sonar_saved = _sonar_routes(_sonar_address())
        log.info("Sonar's devices before the step: %s", ", ".join(
            f"{rid}={dev}" for (_k, rid), (dev, _r) in sorted(_sonar_saved.items())))
    except Exception:  # noqa: BLE001
        log.info("couldn't read Sonar's devices before the step", exc_info=True)


def _sonar_keep_again() -> None:
    """Sonar started again (_mic_apps_back): the devices it picked, once its mic has one
    (within SONAR_BACK_S), noted for the step's later audio restarts to set back. Seen
    to either way: it isn't restarted again in this step."""
    global _sonar_fixed
    end = time.monotonic() + SONAR_BACK_S
    while True:
        _sonar_keep(again=True)
        has_mic = bool(_sonar_saved) and any(rid == "mic" for _k, rid in _sonar_saved)
        if has_mic or time.monotonic() > end:
            break
        time.sleep(1)
    _sonar_fixed = True


def _sonar_back() -> None:
    """After an audio restart: each of Sonar's channels on another device than before
    the step, or stopped when it ran, set back to its device (setting it again starts a
    stopped one), until all are and SONAR_SETTLE_S have gone by; given up after
    SONAR_BACK_S. Its mic channel then without a device (dropped before the step, by an
    older version's restart: nothing to set back) needs Sonar restarted, which picks the
    device it's set up with again. Only its mic decides that: a Game / Chat / Media / Aux
    channel Sonar won't take back (it refuses its device, or says it's stopped and
    refuses no device too) is left to Sonar, which picks those again by itself; ending
    Sonar for one used up SteelSeries GG's 3 restarts, then Sonar stayed off, mic and
    sound. Its result (_sonar_fixed) tells _mic_apps_back whether Sonar still needs a
    restart. A check: never fails the step."""
    global _sonar_fixed
    if _sonar_saved is None:
        _sonar_fixed = None
        return
    start = time.monotonic()
    answered = False
    put: dict[tuple[str, str], float] = {}   # when each channel was last set
    away: dict[tuple[str, str], float] = {}  # ...or moved to no device (to start it)
    refused: set[tuple[str, str]] = set()    # ...which Sonar wouldn't take: not tried again
    address, now, last_wrong = "", {}, None
    while True:
        wrong = None   # (Sonar not answering this time)
        try:
            address = _sonar_address()
            now = _sonar_routes(address)
            answered = True
            wrong = [k for k, (dev, ran) in _sonar_saved.items()
                     if now.get(k, ("", False))[0] != dev or (ran and not now[k][1])
                     or k not in put]   # each set once at least: a stopped one can say it runs
            last_wrong = wrong
            for kind, rid in wrong:
                dev = _sonar_saved[(kind, rid)][0]
                try:
                    if (kind, rid) in away:   # moved to no device: back after a moment
                        if time.monotonic() - away[(kind, rid)] < SONAR_AWAY_S:
                            continue
                        del away[(kind, rid)]
                    elif (kind, rid) in put and now.get((kind, rid), ("",))[0] == dev:
                        # set again and still stopped: in streamer mode Sonar starts a
                        # channel only when its device changes, so it's moved to no
                        # device (an id no device has) for a moment, then back
                        if (kind, rid) in refused:
                            continue
                        if time.monotonic() - put[(kind, rid)] >= SONAR_START_S:
                            try:
                                _local_http("PUT", address, f"/{kind}/{rid}/deviceId/"
                                            + dev.rpartition(".")[0] + "." + _NO_DEVICE)
                            except OSError:   # (its Game / Chat channels: HTTP 400)
                                refused.add((kind, rid))
                                raise
                            away[(kind, rid)] = time.monotonic()
                        continue
                    _local_http("PUT", address, f"/{kind}/{rid}/deviceId/{dev}")
                    put[(kind, rid)] = time.monotonic()
                except OSError as e:   # its device not back yet: tried again
                    log.info("Sonar's %s: %s", rid, e)
        except Exception:  # noqa: BLE001 - Sonar's server not back yet
            log.debug("Sonar didn't answer", exc_info=True)
        waited = time.monotonic() - start
        if wrong == [] and waited >= SONAR_SETTLE_S:
            _sonar_fixed = _sonar_mic_runs(address, now)
            if _sonar_fixed:
                log.info("Sonar's devices are set as before the step")
            else:
                log.warning("Sonar's mic has no device (dropped before the step?): it "
                            "needs a restart")
            return
        if waited > SONAR_BACK_S:
            if last_wrong and all(rid != "mic" for _k, rid in last_wrong) \
                    and _sonar_mic_runs(address, now):
                log.warning("couldn't set Sonar's %s back after the audio restart; its mic "
                            "is set back: Sonar left running",
                            ", ".join(sorted({rid for _k, rid in last_wrong})))
                _sonar_fixed = True
                return
            log.warning("couldn't set Sonar's devices back after the audio restart")
            _sonar_fixed = False if answered else None
            return
        time.sleep(1)


def _processes(exe: str) -> list[tuple[int, str]]:
    """The running copies of `exe`: (pid, its parent's process name, lowercase)."""
    script = (f"$all = Get-CimInstance Win32_Process; $all | Where-Object Name -eq '{exe}' | "
              "ForEach-Object { $p = $_.ParentProcessId; "
              "$n = ($all | Where-Object ProcessId -eq $p | Select-Object -First 1).Name; "
              "\"$($_.ProcessId) $n\" }")
    try:
        r = subprocess.run(_powershell(script),
                           capture_output=True, text=True, errors="replace", timeout=30,
                           creationflags=_CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return []
    found = []
    for line in r.stdout.splitlines():
        pid, _, parent = line.strip().partition(" ")
        if pid.isdigit():
            found.append((int(pid), parent.strip().lower()))
    return found


def _heard_before(guid: str) -> bool | None:
    """_mic_is_silent before a step, asked once more after a moment when it couldn't
    tell at once: Windows can refuse to open a mic for a moment (a mic app's own, such
    as SteelSeries Sonar's, right after the board using it was ended). A mic that took
    longer to say so (not there, or not back yet) isn't waited for again."""
    start = time.monotonic()
    heard = _mic_is_silent(guid)
    if heard is None and time.monotonic() - start < BEFORE_RETRY_S:
        time.sleep(BEFORE_RETRY_S)
        heard = _mic_is_silent(guid)
    return heard


BEFORE_RETRY_S = 2


def _silent_before(guids: Sequence[str]) -> set[str]:
    """The mics among `guids` sending only exact zeros now (a check: never fails). One
    that can't be listened to counts as silent too: its silence after the step can't be
    shown to be the step's, and blaming the step cost a mic app's mic that only sends
    zeros in a quiet room (Sonar's) three more restarts of all the PC's sound, Sonar
    itself, and a set-up called failed."""
    quiet = set()
    for g in dict.fromkeys(g.lower() for g in guids):
        try:
            heard = _heard_before(g)
        except Exception:  # noqa: BLE001
            log.info("couldn't listen to mic %s before the step", g, exc_info=True)
            heard = None
        if heard is None:
            log.info("can't tell if mic %s sends sound before the step: its silence "
                     "after it isn't counted as the step's", g)
        if heard is not False:
            quiet.add(g)
    if quiet:
        log.info("%s already sends only silence (switched off or muted?): not the "
                 "step's doing", ", ".join(sorted(quiet)))
    return quiet


MIC_SILENT = 7        # the step was done, but a mic still sends only silence
EXTRA_RESTARTS = 3    # ...after this many more restarts of Windows' audio
LEFT_SILENT = "left-silent.json"   # in data_dir().parent: the mics a step's MIC_SILENT named
RETRY_S = 30 * 60     # a step this soon after one counts as its retry
# what a step returns when its work was done (whatever the checks after it found)
DONE_CODES = (0, MIC_SILENT, EFFECT_NOT_STARTED, MIC_SHUT)


def _left_silent() -> set[str]:
    """The mics the last step left sending only silence, if it was under RETRY_S ago
    (a check: never fails)."""
    try:
        got = json.loads((data_dir().parent / LEFT_SILENT).read_text(encoding="utf-8"))
        if 0 <= time.time() - float(got["at"]) < RETRY_S:
            mics = {str(g).lower() for g in got["mics"]}
            if mics:
                log.info("%s left silent by the last step: still restarting for it",
                         ", ".join(sorted(mics)))
            return mics
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return set()


def _remember_silent(mics: Sequence[str]) -> None:
    """Note the mics this step left silent for the next one (none: forget them). In the
    admins-only folder: in MicPlugin, the users' folder, the name could be a link."""
    path = data_dir().parent / LEFT_SILENT
    try:
        if mics:
            path.write_text(json.dumps({"at": time.time(), "mics": sorted(mics)}),
                            encoding="utf-8")
        else:
            path.unlink(missing_ok=True)
    except OSError:
        log.info("couldn't note the silent mics", exc_info=True)


def _mic_is_silent(guid: str) -> bool | None:
    """appaudio.mic_is_silent: True when the mic sends only exact zeros."""
    from soundboard.audio import appaudio
    return appaudio.mic_is_silent(guid)


def _silent(guid: str) -> bool:
    """Only exact zeros, twice 2 s apart (a mic still waking up can be silent a moment)."""
    heard = _mic_is_silent(guid)
    if heard:
        log.info("mic %s silent just after the audio restart: listening again", guid)
        time.sleep(2)
        heard = _mic_is_silent(guid)
    log.info("mic %s after the audio restart: %s", guid,
             {True: "only silence", False: "sound", None: "can't tell"}[heard])
    return bool(heard)


def _mics_come_back_live(before: Sequence[str], quiet: Collection[str] = ()) -> bool:
    """After the audio restart a mic can come back sending only exact zeros (an app
    such as a voice chat grabbed it the moment it was back), to every app and to Windows'
    own mic test, until the audio restarts again. So the mics the effect was on (`before`)
    and is on now are listened to: digital silence gets another restart, up to
    EXTRA_RESTARTS of them. False if a mic still sends only silence after those (the app
    then says so); True otherwise, "can't tell" and a failed check included. Mics in
    `quiet` were silent before the step already (_silent_before): left alone."""
    try:
        silent = [g for g in dict.fromkeys([*before, *installed_on()])
                  if g.lower() not in quiet and _silent(g)]
        for n in range(1, EXTRA_RESTARTS + 1):
            if not silent:
                break
            log.warning("%s sends only silence after the audio restart: restarting the "
                        "audio again (%d of %d)", ", ".join(silent), n, EXTRA_RESTARTS)
            _restart_audio()
            silent = [g for g in silent if _silent(g)]
            if not silent:
                log.info("the mic is back after %d more restart(s)", n)
        _remember_silent(silent)
        if silent:
            log.warning("%s still sends only silence after %d more restarts",
                        ", ".join(silent), EXTRA_RESTARTS)
            return False
    except Exception:  # noqa: BLE001 - a check: never fails the install or uninstall
        log.warning("couldn't check the mic after the audio restart", exc_info=True)
    return True


def admin_install(guid: str, slot: str | None = None, source: Path | None = None) -> int:
    """Put the effect on the mic `guid`: this app's own copy, or `source` (only
    admin_reinstall's saved copy of the part that was there, to put it back)."""
    dll = source or bundled_dll()
    if not dll.is_file():
        log.error("no effect DLL at %s", dll)
        return 3

    def work() -> int:
        # a file Windows' audio hasn't let go of yet, a registry key still being
        # written: such a failure is gone a moment later, so it's tried once more
        result = _try_put_on(guid, dll, slot)
        if result:
            log.warning("the mic effect didn't go on (%s): trying once more", result)
            time.sleep(2)
            result = _try_put_on(guid, dll, slot)
        return result
    return _audio_off(work, also=(guid,))


def _put_on(guid: str, slot: str | None, dll: Path) -> int:
    """admin_install()'s work (with the audio stopped, or before its mics restart)."""
    # a name of its own per version: a copy Windows still holds can't block it
    digest = hashlib.sha256(dll.read_bytes()).hexdigest()[:12]
    target = install_dir() / f"obmic-{digest}.dll"
    target.parent.mkdir(parents=True, exist_ok=True)
    # this version is there already (a set-up again, a repair): kept as it is. Writing
    # over it failed while a program that hadn't let go of Windows' audio yet still
    # had it loaded (exit code 1)
    if _digest(target) != _digest(dll):
        tmp = target.with_suffix(".new")
        shutil.copyfile(dll, tmp)   # whole, then in place: never a half-copied effect
        os.replace(tmp, target)
    _register_com(target)
    for old in [*install_dir().glob("obmic*.dll"), *_old_install_dirs()]:
        if old != target:
            _remove(old)
    _make_ring()
    _unmark([target, ring_path()])
    for other in installed_on():   # one mic at a time; this one is done afresh
        _uninstall_endpoint(other)
    for e in capture_endpoints():
        # an older version's set-up cut off (or its notes lost) left the effect in
        # this mic's slots with nothing to put back: just take it out
        if e["guid"] != guid and any(without_ours(v)[0]
                                     for v in _fx_values(e["guid"]).values()):
            _strip_endpoint(e["guid"])
    try:
        _install_endpoint(guid, slot)
    except BaseException:
        # cut off half-way: the mic goes back as it was rather than half set up
        try:
            _uninstall_endpoint(guid)
        except Exception:  # noqa: BLE001 - the notes stay; a later uninstall finishes
            log.exception("couldn't put %s back after a failed set-up", guid)
        raise
    return 0


def admin_reinstall(guid: str) -> int:
    """The old effect off completely, then this app's on: one admin prompt, one lock
    and one restart of Windows' audio (it was two, ~35 s; now ~18 s). Never leaves the
    mic without a working effect: a failed install is tried once more, and if that
    fails too the part that was there is put back."""
    dll = bundled_dll()
    if not dll.is_file():
        return 3
    # Read the complete source before touching Windows: unreadable or empty builds
    # must leave the existing setup alone. _put_on copies it atomically.
    if not dll.read_bytes():
        return 3
    # a copy of the part that's there now, in the admins-only data folder (the
    # uninstall removes its own folder): what goes back if the new one won't go on
    old, backup = registered_dll(), None
    if guid in installed_on() and old is not None and old.is_file():
        try:
            backup = data_dir().parent / "obmic-previous.dll"
            tmp = backup.with_suffix(".new")
            shutil.copyfile(old, tmp)
            os.replace(tmp, backup)
        except OSError:
            log.warning("couldn't keep a copy of the mic effect there now", exc_info=True)
            backup = None

    def work() -> int:
        result = _take_off(None)
        if result:
            return result   # keep the failed endpoint's recovery notes for another attempt
        result = _try_put_on(guid, dll)
        if result:
            log.warning("the new mic effect didn't go on (%s): trying once more", result)
            time.sleep(2)
            result = _try_put_on(guid, dll)
        if result and backup is not None:
            log.warning("the new mic effect didn't go on (%s): the old one goes back", result)
            if _try_put_on(guid, backup):
                log.error("couldn't put the old mic effect back either")
        return result
    try:
        return _audio_off(work, also=(guid,))
    finally:
        if backup is not None:
            _remove(backup)


def _try_put_on(guid: str, dll: Path, slot: str | None = None) -> int:
    """_put_on(), an exception counted as a failure (1)."""
    try:
        return _put_on(guid, slot, dll)
    except Exception:  # noqa: BLE001 - reported by the caller, which tries again
        log.exception("mic effect install failed")
        return 1


def admin_uninstall(only: str | None = None) -> int:
    """Take the effect off every mic, or only off the mic `only` (a GUID): then the
    rest stays, and the effect itself is removed once it's on no mic at all. On no mic,
    not registered and no files (the app's uninstall after the effect came off): nothing
    holds Windows' audio, so it isn't restarted for nothing (that cut everyone's sound and
    moved SteelSeries Sonar's devices)."""
    if not anything_installed():
        return _take_off(only)
    return _audio_off(lambda: _take_off(only))


def _take_off(only: str | None) -> int:
    """admin_uninstall()'s work, with the audio stopped."""
    failed = False
    for guid in installed_on():
        if only is not None and guid != only:
            continue
        try:
            _uninstall_endpoint(guid)
        except Exception:  # noqa: BLE001 - one mic left behind mustn't strand the rest
            failed = True
            log.exception("couldn't take the mic effect off %s", guid)
    if failed:
        # its notes stay, and the effect is still registered and on a mic: leaving
        # everything in place lets a later uninstall finish the job
        return 1
    if installed_on():
        return 0   # still on another mic: it stays registered for that one
    _unregister_com()
    for d in (install_dir(), *_old_install_dirs(), data_dir()):
        _remove(d)
    try:
        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, ENDPOINTS_KEY)
        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, STATE_KEY)
    except OSError:
        pass
    return 0


def admin_remove_all() -> int:
    """The app is being uninstalled: the effect off every mic, then the mic helper."""
    from soundboard.mic import michelper
    code = admin_uninstall()
    if code == 0 and not michelper.is_helper():
        michelper.remove_helper()   # (the helper removes itself after answering)
    return code


def _strip_endpoint(guid: str):
    """Take this effect out of every effect slot on one mic that has no notes. What it
    replaced isn't known, so the slot is left without it: everything else stays."""
    try:
        with _BackupKey(rf"{CAPTURE_KEY}\{guid}\FxProperties", create=False) as fx:
            for name, value in _fx_values(guid).items():
                changed, rest = without_ours(value)
                if not changed:
                    continue
                if rest is None:
                    fx.delete(name)
                else:
                    fx.set(name, winreg.REG_MULTI_SZ, rest)
                log.info("%s: took a leftover effect out of %s", guid, name)
    except FileNotFoundError:
        pass   # the mic is gone


def admin_cleanup(guid: str) -> int:
    """Clean up after the effect on a mic it isn't (by our notes) on: our CLSID out of
    its effect slots, then, if no mic uses the effect, its registration and files. A
    mic it is on properly is uninstalled the normal way (its notes put it back)."""
    if guid in installed_on():
        return admin_uninstall(guid)
    _enable_privileges("SeBackupPrivilege", "SeRestorePrivilege")
    leftover = any(without_ours(v)[0] for v in _fx_values(guid).values())
    if leftover:
        apps_quiet = _mic_apps_quiet()
        _sonar_keep()
        dependents = _running_dependents()
        _audio_comes_back(dependents)
        try:
            if not _audio_service(False):
                return 6   # never rewrite a live mic
            _strip_endpoint(guid)
        finally:
            _audio_service(True, dependents)
            _sonar_back()
            _mic_apps_back(apps_quiet)
    if not installed_on() and anything_installed():
        return admin_uninstall()   # on no mic: the rest of it goes too
    return 0


def _remove(path: Path):
    """Delete a file or folder of ours. What Windows still holds open (an old copy of
    the effect) goes at the next restart instead of staying behind for good."""
    # through handles to checked folders: a link anywhere in it goes itself, never what
    # it points at (a planted %ProgramData%\OnionBoard junction once had everything
    # behind it marked for removal)
    left = safefs.remove_tree(path)
    # files first, deepest folders next, the folder itself last; never in a folder
    # others may write to, where the name could be a link to anywhere by the restart
    for entry in sorted(left, key=lambda p: (p.is_dir(), -len(p.parts))):
        if not _others_write(entry):
            _gone_at_restart(entry)


def _others_write(path: Path) -> bool:
    """`path` is in a folder signed-in users may write to (MicPlugin, the helper's
    requests)."""
    from soundboard.mic import michelper
    p = _same_path(path)
    return any(p == d or p.startswith(d + os.sep)
               for d in map(_same_path, (data_dir(), michelper.requests_dir())))


SESSION_KEY = r"SYSTEM\CurrentControlSet\Control\Session Manager"
PENDING = "PendingFileRenameOperations"   # Windows' list of what goes at the next restart


def _pending_path(entry: str) -> str:
    """A path as _same_path compares it, from an entry of Windows' list: the path after
    a "*1" and a "\\??\\"."""
    return _same_path(re.sub(r"^\*\d+", "", entry).removeprefix("\\??\\"))


def _same_path(path) -> str:
    return os.path.normcase(os.path.abspath(path)).rstrip(os.sep)


def _unmark(paths: Sequence[Path]):
    """Take `paths` and the folders they're in off Windows' list of what goes at the next
    restart. An earlier step marked them while something still held them (the board its
    ring, Windows' audio an effect copy), and this step uses them again: left marked, the
    effect lost its files at the next restart. (A check: never fails the step.)"""
    want = [_same_path(p) for p in paths]
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, SESSION_KEY, 0,
                            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as k:
            ops, kind = winreg.QueryValueEx(k, PENDING)
            if kind != winreg.REG_MULTI_SZ or len(ops) % 2:
                return
            keep = []
            for src, dst in zip(ops[::2], ops[1::2]):
                p = _pending_path(src)
                if not dst and any(w == p or w.startswith(p + os.sep) for w in want):
                    log.info("%s no longer goes at the next restart: it's in use", p)
                    continue
                keep += [src, dst]
            if len(keep) != len(ops):
                winreg.SetValueEx(k, PENDING, 0, winreg.REG_MULTI_SZ, keep)
    except FileNotFoundError:
        pass   # nothing goes at the next restart
    except OSError:
        log.warning("couldn't read what goes at the next restart", exc_info=True)


def _marked(path: Path) -> bool:
    """`path` is on Windows' list of what goes at the next restart already."""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, SESSION_KEY) as k:
            ops = winreg.QueryValueEx(k, PENDING)[0]
    except OSError:
        return False
    p = _same_path(path)
    return isinstance(ops, list) and any(
        not dst and _pending_path(src) == p for src, dst in zip(ops[::2], ops[1::2]))


def _gone_at_restart(path: Path):
    log.info("can't remove %s yet: it goes at the next restart", path)
    if _marked(path):
        return   # (an old copy Windows' audio still holds: once is enough)
    try:
        # MOVEFILE_DELAY_UNTIL_REBOOT (admin only: the admin step is)
        if not ctypes.windll.kernel32.MoveFileExW(str(path), None, 4):
            log.warning("couldn't mark %s for removal", path)
    except (AttributeError, OSError):
        log.warning("couldn't mark %s for removal", path, exc_info=True)


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def cli(args: list[str]) -> int:
    """`--direct-mic install <endpoint guid> [sfx|lfx|efx]` /`--direct-mic uninstall`: the
    admin copy. `--direct-mic remove`: the uninstaller's, not admin: runs the admin
    `remove-all` (the mic helper, or Windows asks first) if Onion Board is on a mic or
    its helper (or any of it) is there at all. 0 when done. The app adds `--for <SID>`
    (the account that asked) to the steps that may set up the helper."""
    from soundboard.mic import directmic, michelper
    user = None
    if len(args) >= 2 and args[-2] == michelper.FOR:
        user, args = args[-1], args[:-2]   # (install_helper checks it)
    if args == ["remove"]:
        if not anything_installed() and not michelper.leftover():
            return 0
        if not _is_admin():
            code = directmic._elevated(["remove-all"])
            return 1 if code is None or code < 0 else code
        args = ["remove-all"]
    if args[:1] == ["reinstall"] and len(args) == 2 and _GUID.fullmatch(args[1]):
        guid = args[1].lower()
        if guid not in {e["guid"] for e in capture_endpoints()}:
            return 2
        step = lambda: admin_reinstall(guid)  # noqa: E731
    elif args[:1] == ["install"] and len(args) in (2, 3) and _GUID.fullmatch(args[1]) \
            and (len(args) == 2 or args[2] in SLOTS_FX):
        guid = args[1].lower()
        if guid not in {e["guid"] for e in capture_endpoints()}:
            return 2
        step = lambda: admin_install(guid, args[2] if len(args) == 3 else None)  # noqa: E731
    elif args == ["uninstall"]:
        step = admin_uninstall
    elif args == ["remove-all"]:
        step = admin_remove_all
    elif args[:1] == ["cleanup"] and len(args) == 2 and _GUID.fullmatch(args[1]):
        guid = args[1].lower()
        step = lambda: admin_cleanup(guid)  # noqa: E731
    elif args[:1] == ["uninstall"] and len(args) == 2 and _GUID.fullmatch(args[1]):
        guid = args[1].lower()   # an unplugged mic too: its settings are still there
        step = lambda: admin_uninstall(guid)  # noqa: E731
    else:
        return 2
    lock = _admin_lock()
    if lock is None:
        return 4   # another copy is at it (a set-up the board stopped waiting for)
    try:
        try:
            _enable_privileges("SeBackupPrivilege", "SeRestorePrivilege")
            secure_data_dirs()   # before the log or anything else is written there
        except Exception:  # noqa: BLE001 - nowhere safe to log to: just say it failed
            return 5
        log_to(data_dir().parent / "directmic-admin.log")
        try:
            code = step()
        except Exception:  # noqa: BLE001
            log.exception("mic effect %s failed", args[:1])
            return 1
        if code in DONE_CODES and args[0] in ("install", "reinstall", "cleanup") \
                and not michelper.is_helper():
            # the one prompt also sets up (or updates) the helper: no prompt next time
            michelper.install_helper(user)
        return code
    finally:
        _release(lock)


LOG_BYTES = 1 << 20


def log_to(path: Path):
    """The admin logs (directmic-admin.log, michelper.log): about 1 MB each, with one
    older copy, instead of growing for good. Nothing if logging is set up already."""
    from logging.handlers import RotatingFileHandler
    root = logging.getLogger()
    if root.handlers:
        return
    handler = RotatingFileHandler(path, maxBytes=LOG_BYTES, backupCount=1,
                                  encoding="utf-8", delay=True)
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    root.addHandler(handler)
    root.setLevel(logging.INFO)


_LOCK_NAME = "Global\\OnionBoardMicEffect"


def _admin_lock():
    """One admin step at a time, machine-wide: a handle to hold, or None if another copy
    holds it (two at once would each stop the audio and rewrite the same mic)."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    h = kernel.CreateMutexW(None, False, _LOCK_NAME)
    if not h:
        return None
    if kernel.WaitForSingleObject(h, 0) not in (0, 0x80):   # got it / its owner died
        kernel.CloseHandle(h)
        return None
    return h


def _release(h):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.ReleaseMutex(h)
    kernel.CloseHandle(h)


# ---------------------------------------------------------------------- Sonar, for the app

# SteelSeries Sonar's devices for the app's own watch (soundboard.mic.sonarkeep): the
# admin part's look-ups and set-back, without admin (Sonar's local server). They use
# its module-wide note of the devices, which only a step itself (in the mic helper or
# the app's elevated copy, never this process) otherwise uses.
SONAR_MIC = MIC_APPS[0][2]   # "SteelSeries Sonar - Microphone": its mic's name starts so


def sonar_devices() -> dict[tuple[str, str], tuple[str, bool]] | None:
    """Sonar's channels now: None when Sonar isn't running or doesn't answer, or its mic
    channel has no device or is stopped (nothing worth keeping)."""
    try:
        address = _sonar_address()
        routes = _sonar_routes(address)
    except OSError:
        return None
    return routes if _sonar_mic_runs(address, routes) else None


def sonar_set_back(saved: dict[tuple[str, str], tuple[str, bool]]) -> bool | None:
    """Sonar's channels set back to `saved` (sonar_devices) after an audio restart, as a
    step does it (_sonar_back; Sonar is never ended here). True when they are, False
    when Sonar wouldn't take them, None when it didn't answer."""
    global _sonar_saved
    _sonar_saved = dict(saved)
    _sonar_back()
    return _sonar_fixed

