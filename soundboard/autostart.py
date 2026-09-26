"""Start with Windows: one value under the per-user Run key (no admin, and the
uninstaller / the Settings checkbox takes it away again).

The value is the command that starts this app: the installed .exe, or pythonw.exe
with main.py when running from source. `--tray` makes it start hidden in the tray."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

try:
    import winreg
except ImportError:   # not Windows: start with Windows isn't offered
    winreg = None

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "OnionBoard"
TRAY_ARG = "--tray"


def available() -> bool:
    return winreg is not None


def command(hidden: bool) -> str:
    """The command line Windows runs at sign-in."""
    if getattr(sys, "frozen", False):
        parts = [sys.executable]
    else:
        exe = Path(sys.executable)
        gui = exe.with_name("pythonw.exe")   # no console window
        main = Path(__file__).resolve().parent.parent / "main.py"
        parts = [str(gui if gui.exists() else exe), str(main)]
    if hidden:
        parts.append(TRAY_ARG)
    return " ".join(p if p.startswith("--") else f'"{p}"' for p in parts)


def current() -> str | None:
    """The command registered now, or None."""
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            v, _t = winreg.QueryValueEx(k, VALUE)
            return str(v)
    except OSError:
        return None


def is_enabled() -> bool:
    return current() is not None


def set_enabled(on: bool, hidden: bool = True) -> bool:
    """Add (or update) or remove the Run value. False if the registry said no."""
    if winreg is None:
        return False
    try:
        if on:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                winreg.SetValueEx(k, VALUE, 0, winreg.REG_SZ, command(hidden))
        else:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, VALUE)
        return True
    except FileNotFoundError:
        return not on   # removing a value that isn't there: done
    except OSError:
        log.warning("couldn't change start with Windows", exc_info=True)
        return False


def refresh(hidden: bool):
    """Point an existing entry at this copy of the app (it may have moved, or the
    'start in the tray' choice changed). Does nothing if start with Windows is off."""
    cur = current()
    if cur is not None and cur != command(hidden):
        set_enabled(True, hidden)
