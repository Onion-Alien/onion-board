"""The uninstaller's tidy-up of what the app put outside its own folder
(installer/OnionBoard.iss, CurUninstallStepChanged): `OnionBoard.exe --uninstall-cleanup
[--data]`, no window, run before the app's files go.

- Always: the Onion Pocket firewall rule (soundboard/online/firewall.py), if this PC has
  one. Only admins can remove it, so Windows asks, but only on a PC that has the rule.
- With `--data` (Yes to the uninstaller's "Also delete your sounds and settings?"): the
  user's `%APPDATA%\\OnionBoard` goes to the Recycle Bin (Windows warns first if it's
  too big for it), and `%ProgramData%\\OnionBoard` (the mic effect's shared file and its
  logs) is deleted in the same admin step, but only once the mic effect and the mic
  helper are gone (the uninstaller takes them off first).

The admin step is this program again with `--admin` added, and does only that. It runs
before main.py's breadcrumb and logging, which would write into the folder being
deleted. The exit code is a set of what stayed, for the uninstaller to say: DATA_LEFT,
RULE_LEFT, MACHINE_LEFT; 0 when everything asked for is gone. ProgramData's folder kept
for a mic effect still on a mic isn't one: the uninstaller says the effect stayed.
"""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from soundboard.win import systools

log = logging.getLogger(__name__)

FLAG = "--uninstall-cleanup"
DATA = "--data"
ADMIN = "--admin"
DATA_LEFT = 1   # some of their sounds and settings stayed
RULE_LEFT = 2   # the firewall rule stayed (Windows' prompt was turned down)
MACHINE_LEFT = 4   # ProgramData's folder stayed (the prompt was turned down, or in use)
RULES = ("OnionPocket",)   # onion_pocket/lan.py FIREWALL_RULE, as cleanup.FIREWALL_RULES
_CREATE_NO_WINDOW = 0x08000000


def _netsh(*args: str) -> int:
    try:
        return subprocess.run([systools.tool("netsh"), "advfirewall", "firewall", *args],
                              capture_output=True, timeout=30,
                              creationflags=_CREATE_NO_WINDOW).returncode
    except (OSError, subprocess.SubprocessError):
        log.warning("netsh failed", exc_info=True)
        return -1


def rules_present() -> list[str]:
    """The firewall rules of ours this PC has (reading them needs no admin)."""
    return [name for name in RULES if _netsh("show", "rule", f"name={name}") == 0]


def user_dir() -> Path:
    from soundboard.sounds import paths
    return paths.APP_DIR


def machine_dir() -> Path:
    from soundboard.core import cleanup
    return cleanup.programdata_dir()


def mic_parts_left() -> bool:
    """The mic effect or its helper is still on this PC: ProgramData's folder stays."""
    from soundboard.mic import directmic as dm, michelper
    return bool(dm.anything_installed() or michelper.leftover())


def admin_part(data: bool) -> int:
    """Elevated: the firewall rules, and with `data` ProgramData's folder."""
    from soundboard.core import cleanup
    left = 0
    for name in RULES:
        _netsh("delete", "rule", f"name={name}")
    if rules_present():
        left |= RULE_LEFT
    if data and machine_dir().exists():
        if mic_parts_left():
            log.info("the mic effect is still here: %s stays", machine_dir())
        elif not cleanup._remove(machine_dir()):
            left |= MACHINE_LEFT
    return left


def elevate(data: bool) -> int:
    """Ask Windows to run admin_part, and wait: its exit code."""
    from soundboard.core import cleanup
    args = [FLAG, ADMIN] + ([DATA] if data else [])
    if not getattr(sys, "frozen", False):   # from source: main.py first
        args = [str(Path(__file__).resolve().parents[2] / "main.py"), *args]
    code = cleanup.run_elevated(args, wait_s=120.0, source=())
    if code is None:   # turned down, or it didn't finish
        return (RULE_LEFT if rules_present() else 0) | \
            (MACHINE_LEFT if data and machine_dir().exists() else 0)
    return code


def recycle_user_dir() -> bool:
    """Their sounds and settings to the Recycle Bin. True if the folder is gone."""
    from soundboard.sounds import files
    d = user_dir()
    if not d.exists():
        return True
    if not files.recycle(d, warn_if_permanent=True):
        log.warning("couldn't put %s in the Recycle Bin", d)
    return not d.exists()


def cli(args: list[str]) -> int:
    """`--uninstall-cleanup [--data] [--admin]`; never raises, the uninstall goes on."""
    data = DATA in args
    try:
        if ADMIN in args:
            return admin_part(data)
        left = 0
        # ProgramData's folder stays with a mic effect still on a mic: no prompt for it
        if rules_present() or (data and machine_dir().exists() and not mic_parts_left()):
            left = elevate(data)
        if data and not recycle_user_dir():
            left |= DATA_LEFT
        return left
    except Exception:  # noqa: BLE001 - never in the uninstaller's way
        log.warning("%s failed", FLAG, exc_info=True)
        return DATA_LEFT if data else RULE_LEFT
