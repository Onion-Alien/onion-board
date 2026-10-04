"""Windows Firewall rules for add-ons that phones on the home network reach (remote
add-ons such as Onion Pocket), added by Onion Board itself so Windows' admin prompt
names Onion Board rather than "Windows Command Processor".

`allow(name, port)` runs this app again as admin (`OnionBoard.exe --firewall-rule NAME
PORT`, or `pythonw.exe main.py …` from source) and waits for it. That copy does only
`cli()`: it replaces the rules called NAME with two inbound allow rules, TCP on PORT
and this program, both Private networks and local subnet only, then exits. It never
starts the app. The program in the rule is the elevated copy's own sys.executable, never
an argument, and NAME and PORT are checked, so the admin step can't be pointed at
anything else. netsh runs without a shell, so nothing in them is read as a command.
"""
from __future__ import annotations

import logging
import re
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

FLAG = "--firewall-rule"
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9-]{0,39}")
_CREATE_NO_WINDOW = 0x08000000


def valid(name: str, port) -> bool:
    try:
        port = int(port)
    except (TypeError, ValueError):
        return False
    return bool(_NAME.fullmatch(str(name))) and 1024 <= port <= 65535


def commands(name: str, port: int, program: str) -> list[list[str]]:
    """The netsh calls, as argument lists: delete the old rules, add the port's, then
    the program's."""
    if not valid(name, port):
        raise ValueError(f"bad firewall rule {name!r} / {port!r}")
    base = ["netsh", "advfirewall", "firewall"]
    add = base + ["add", "rule", f"name={name}", "dir=in", "action=allow", "protocol=TCP"]
    limits = [f"localport={int(port)}", "profile=private", "remoteip=localsubnet"]
    return [base + ["delete", "rule", f"name={name}"],
            add + limits,
            add + [f"program={program}"] + limits]


def cli(args: list[str]) -> int:
    """The admin copy: `--firewall-rule NAME PORT`. 0 when both rules were added."""
    if len(args) != 2 or not valid(*args):
        return 2
    name, port = args[0], int(args[1])
    calls = commands(name, port, sys.executable)
    # deleting fails harmlessly when there's no old rule
    subprocess.run(calls[0], capture_output=True, creationflags=_CREATE_NO_WINDOW)
    for call in calls[1:]:
        if subprocess.run(call, capture_output=True,
                          creationflags=_CREATE_NO_WINDOW).returncode:
            return 1
    return 0


def relaunch_params(name: str, port: int) -> str:
    """The command line after this program for the admin copy: main.py first when run
    from source."""
    parts = []
    if not getattr(sys, "frozen", False):
        parts.append(f'"{Path(__file__).resolve().parent.parent / "main.py"}"')
    parts += [FLAG, name, str(int(port))]
    return " ".join(parts)


def allow(name: str, port: int, wait_s: float = 60.0) -> bool:
    """Ask Windows (its admin prompt, naming this app) for the rule NAME on PORT, and
    wait for it. True if the prompt was accepted and both rules were added."""
    if sys.platform != "win32" or not valid(name, port):
        return False
    import ctypes
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG),
                    ("hwnd", wintypes.HWND), ("lpVerb", wintypes.LPCWSTR),
                    ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int),
                    ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE),
                    ("hProcess", wintypes.HANDLE)]

    SEE_MASK_NOCLOSEPROCESS, SW_HIDE, WAIT_OBJECT_0 = 0x40, 0, 0
    info = SHELLEXECUTEINFOW(cbSize=ctypes.sizeof(SHELLEXECUTEINFOW),
                             fMask=SEE_MASK_NOCLOSEPROCESS, lpVerb="runas",
                             lpFile=sys.executable,
                             lpParameters=relaunch_params(name, port), nShow=SW_HIDE)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    try:
        if not shell32.ShellExecuteExW(ctypes.byref(info)):   # 1223: prompt turned down
            log.info("firewall rule %s not added (error %s)", name, ctypes.get_last_error())
            return False
    except OSError:
        log.warning("couldn't ask for the firewall rule", exc_info=True)
        return False
    if not info.hProcess:
        return False
    try:
        if kernel32.WaitForSingleObject(info.hProcess, int(wait_s * 1000)) != WAIT_OBJECT_0:
            log.warning("the firewall rule %s didn't finish in %s s", name, wait_s)
            return False
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        if code.value:
            log.warning("the firewall rule %s failed (exit code %s)", name, code.value)
        else:
            log.info("firewall rule %s added for port %s", name, port)
        return code.value == 0
    finally:
        kernel32.CloseHandle(info.hProcess)
