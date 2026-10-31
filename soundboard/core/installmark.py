"""Is Onion Board's installer replacing the app's files right now?

installer/OnionBoard.iss leaves `installing.txt` beside OnionBoard.exe while it replaces
the files, and removes it before it opens the app again. Started meanwhile (a
double-click while an update installs), the app loaded half-copied libraries and Python's
"Unhandled exception in script" box came up, one per click; and a copy stuck on an error
box kept OnionBoard.exe open, so the silent update gave up and rolled back, leaving no
app at all. main.py checks this first, before anything else of the app is imported:
only `os`, `sys` and `time` here, which the installer copies before the rest.
"""
from __future__ import annotations

import os
import sys
import time

INSTALLING = "installing.txt"
# older than this, it was left by a setup that died: ignored
INSTALLING_STALE_S = 15 * 60
# the one-off commands app.main() runs and exits (app.ONE_OFF_COMMANDS, the same names);
# the installer runs some of them itself while the mark is there
ONE_OFF = ("--selftest", "--get-tor", "--install-addon", "--set-offline", "--keep-netlog",
           "--usage-count", "--uninstall-count", "--selftest-addon", "--discord-restore",
           "--quit-running")


def installing(exe_dir: str | os.PathLike | None = None, now: float | None = None) -> bool:
    """The mark is beside the exe and fresh. Only for the installed app (from source:
    never)."""
    if exe_dir is None:
        if not getattr(sys, "frozen", False):
            return False
        exe_dir = os.path.dirname(sys.executable)
    try:
        made = os.stat(os.path.join(exe_dir, INSTALLING)).st_mtime
    except OSError:
        return False
    return (time.time() if now is None else now) - made < INSTALLING_STALE_S


def step_aside(argv: list[str]) -> bool:
    """A normal start (not one of the installer's own commands) while it installs: quit,
    the installer opens the app once it's done."""
    return not (set(argv) & set(ONE_OFF)) and installing()
