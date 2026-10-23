"""Windows' own tools (netsh, taskkill, powershell, schtasks…) by their full path in
System32. Started by bare name, Windows looks in the program's own folder, the current
folder and every PATH folder first: an admin step or the SYSTEM mic helper would run
whatever netsh.exe someone left in Downloads, next to the cleanup tool, or in a PATH
folder they can write to."""
from __future__ import annotations

import ctypes
import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def system32() -> Path:
    """GetSystemDirectoryW: not an environment variable, which a user can set."""
    buf = ctypes.create_unicode_buffer(260)
    try:
        if ctypes.windll.kernel32.GetSystemDirectoryW(buf, len(buf)):
            return Path(buf.value)
    except (AttributeError, OSError):
        pass
    return Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"


def tool(name: str) -> str:
    """`name` (netsh, taskkill…) in System32; off Windows, the bare name."""
    if os.name != "nt":
        return name
    if name.lower() in ("powershell", "powershell.exe"):
        return str(system32() / "WindowsPowerShell" / "v1.0" / "powershell.exe")
    return str(system32() / (name if name.lower().endswith(".exe") else f"{name}.exe"))
