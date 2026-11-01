"""OnionBoardCleanup.exe: takes everything of Onion Board off a PC, for people whose
uninstall didn't finish (Windows' prompt said No, the app folder was deleted by hand,
an old version's uninstaller failed) or who just want it all gone.

It finds and removes, after asking once:
- the mic effect (1.9.0 and later): off every mic it is on, each mic's own settings put
  back from the notes the app kept, then its DLL, registration and files. This is the
  app's own `directmic.admin_remove_all()`, the same code the uninstaller runs, plus
  `admin_cleanup()` for any mic that still has the effect in a slot without notes;
- the mic helper (1.9.28 and later): its SYSTEM task and folder;
- the installed app: its folder, its entry in Installed apps, shortcuts, start-up entry;
- `C:\\ProgramData\\OnionBoard` (logs) and the Onion Pocket firewall rule;
- only if the user says so: their sounds and settings in `%APPDATA%\\OnionBoard`.

VB-CABLE is left alone (it's VB-Audio's: Installed apps removes it, and other programs
may use it). The machine-wide part needs admin: the program asks Windows once and runs
itself again elevated with ADMIN_PART. Built by scripts/buildtools/build_cleanup.py.

Usage: OnionBoardCleanup.exe [--yes] [--remove-sounds] [--dry-run]
"""
from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
import tempfile
import time
import winreg
from pathlib import Path

from soundboard.win import systools

log = logging.getLogger("cleanup")

ADMIN_PART = "--admin-part"
APP_ID = "{6B0B6E2F-6D63-4C1B-9E0B-5B8E3C2A71D4}_is1"   # installer/OnionBoard.iss AppId
UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
RUN_KEYS = (r"Software\Microsoft\Windows\CurrentVersion\Run",
            r"Software\Microsoft\Windows\CurrentVersion\RunOnce",
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run")
RUN_NAMES = ("OnionBoard", "OnionBoardResumeSetup")   # autostart.py, ui/setup/cablestep.py
APP_EXES = ("onionboard.exe", "soundboard.exe", "obmichelper.exe")
FIREWALL_RULES = ("OnionPocket",)                     # onion_pocket/lan.py FIREWALL_RULE
STATE_ROOT = r"SOFTWARE\OnionBoard"
_CREATE_NO_WINDOW = 0x08000000
RESTART = 10       # ADMIN_PART's exit code: done, but something goes at the next restart


def _env(name: str, default: str) -> Path:
    return Path(os.environ.get(name) or default)


def appdata_dir() -> Path:
    return _env("APPDATA", str(Path.home() / "AppData" / "Roaming")) / "OnionBoard"


def programdata_dir() -> Path:
    return _env("ProgramData", r"C:\ProgramData") / "OnionBoard"


def default_install_dir() -> Path:
    return _env("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")) / "Programs" / "OnionBoard"


# ---------------------------------------------------------------------- finding it

def _uninstall_entries(hive) -> list[tuple[int, str]]:
    """(registry view, key path) of the installer's entries in this hive."""
    found = []
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        path = rf"{UNINSTALL}\{APP_ID}"
        try:
            winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view).Close()
        except OSError:
            continue
        if (view, path) not in found:
            found.append((view, path))
    return found


def _install_location(hive, view: int, path: str) -> Path | None:
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view) as k:
            where = winreg.QueryValueEx(k, "InstallLocation")[0]
    except OSError:
        return None
    return Path(where.rstrip("\\/")) if isinstance(where, str) and where.strip() else None


def is_app_dir(d: Path) -> bool:
    """A folder that holds the installed app (never a drive or a user folder by mistake:
    it must have the app's .exe or its uninstaller in it, and sit a few levels deep)."""
    if len(d.parts) < 3 or not d.is_dir():
        return False
    return any((d / n).is_file() for n in ("OnionBoard.exe", "Soundboard.exe")) \
        or ((d / "unins000.exe").is_file() and (d / "_internal").is_dir())


def install_dirs(hives=(winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)) -> list[Path]:
    dirs = []
    for hive in hives:
        for view, path in _uninstall_entries(hive):
            d = _install_location(hive, view, path)
            if d and is_app_dir(d) and d not in dirs:
                dirs.append(d)
    d = default_install_dir()
    if hives and winreg.HKEY_CURRENT_USER in hives and is_app_dir(d) and d not in dirs:
        dirs.append(d)
    return dirs


def link_targets(hives=(winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)) -> list[Path]:
    """Where shortcuts of ours point: the install folders, gone ones too (a folder
    deleted by hand leaves its shortcuts behind)."""
    out = [default_install_dir()]
    for hive in hives:
        for view, path in _uninstall_entries(hive):
            d = _install_location(hive, view, path)
            if d and len(d.parts) >= 3:
                out.append(d)
    return list(dict.fromkeys(out))


def shortcut_dirs() -> list[Path]:
    """Desktop and Start menu, this user's and everyone's."""
    out = [Path.home() / "Desktop",
           _env("APPDATA", "") / "Microsoft" / "Windows" / "Start Menu" / "Programs",
           _env("PUBLIC", r"C:\Users\Public") / "Desktop",
           _env("ProgramData", r"C:\ProgramData") / "Microsoft" / "Windows" / "Start Menu"
           / "Programs"]
    try:   # a Desktop moved to OneDrive or another drive
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows"
                            r"\CurrentVersion\Explorer\User Shell Folders") as k:
            out.append(Path(os.path.expandvars(winreg.QueryValueEx(k, "Desktop")[0])))
    except OSError:
        pass
    return list(dict.fromkeys(p for p in out if str(p) not in ("", ".")))


def points_into(lnk: Path, dirs: list[Path]) -> bool:
    """A shortcut whose target is inside one of `dirs` (the path is in the .lnk as
    plain or UTF-16 text; nothing else of it is read)."""
    try:
        data = lnk.read_bytes()[:65536].lower()
    except OSError:
        return False
    for d in dirs:
        s = str(d).lower().rstrip("\\") + "\\"
        if s.encode("utf-8", "ignore") in data or s.encode("utf-16-le") in data:
            return True
    return False


def shortcuts(dirs: list[Path]) -> list[Path]:
    found = []
    for base in shortcut_dirs():
        if not base.is_dir():
            continue
        try:
            links = [*base.glob("*.lnk"), *base.glob("*/*.lnk")]
        except OSError:
            continue
        for lnk in links:
            if lnk not in found and points_into(lnk, dirs):
                found.append(lnk)
    return found


def run_values() -> list[tuple[str, str]]:
    found = []
    for key in RUN_KEYS:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                for name in RUN_NAMES:
                    try:
                        winreg.QueryValueEx(k, name)
                        found.append((key, name))
                    except OSError:
                        pass
        except OSError:
            pass
    return found


def _key_exists(hive, path: str) -> bool:
    try:
        winreg.OpenKey(hive, path).Close()
        return True
    except OSError:
        return False


def mics_with_effect() -> list[str]:
    """Every mic (unplugged ones too) the effect is on, by the notes or in a slot."""
    from soundboard.mic import directmic as dm
    guids = list(dm.installed_on())
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, dm.CAPTURE_KEY) as root:
            i = 0
            while True:
                try:
                    guid = winreg.EnumKey(root, i).lower()
                except OSError:
                    break
                i += 1
                if guid not in guids and any(dm.without_ours(v)[0]
                                             for v in dm._fx_values(guid).values()):
                    guids.append(guid)
    except OSError:
        pass
    return guids


def _mic_name(guid: str) -> str:
    from soundboard.mic import directmic as dm
    for e in dm.capture_endpoints():
        if e["guid"] == guid:
            return e["name"] + ("" if e["active"] else " (unplugged)")
    return guid


def machine_items() -> list[str]:
    """What the admin part would remove, in words; [] if nothing."""
    from soundboard.mic import directmic as dm, michelper
    items = [f"The mic effect on: {_mic_name(g)}" for g in mics_with_effect()]
    if not items and dm.anything_installed():
        items.append("The mic effect's files and registration (on no mic)")
    if michelper.leftover():
        items.append("The mic helper (its scheduled task and folder)")
    for d in install_dirs((winreg.HKEY_LOCAL_MACHINE,)):
        items.append(f"Onion Board for all users: {d}")
    if programdata_dir().exists():
        items.append(f"Logs: {programdata_dir()}")
    if _key_exists(winreg.HKEY_LOCAL_MACHINE, STATE_ROOT):
        items.append(rf"Notes in the registry: HKLM\{STATE_ROOT}")
    return items


def user_items(remove_sounds: bool) -> list[str]:
    dirs = install_dirs((winreg.HKEY_CURRENT_USER,))
    items = [f"Onion Board: {d}" for d in dirs]
    if _uninstall_entries(winreg.HKEY_CURRENT_USER):
        items.append("Its entry in Installed apps")
    items += [f"Shortcut: {s}" for s in shortcuts(link_targets())]
    if run_values():
        items.append("Starting with Windows")
    if remove_sounds and appdata_dir().exists():
        items.append(f"Your sounds and settings: {appdata_dir()}")
    return items


# ---------------------------------------------------------------------- removing it

def _remove(path: Path) -> bool:
    """Delete a file or folder; True if it's gone now (else it goes at the next restart
    when we're admin). A link (%ProgramData%\\OnionBoard made a junction by another
    account) goes itself: what it points at is never walked or marked (dm._remove)."""
    from soundboard.mic import directmic as dm
    if not os.path.lexists(path):
        return True
    try:
        dm._remove(path)
    except OSError:
        log.warning("couldn't remove %s", path, exc_info=True)
    gone = not os.path.lexists(path)
    log.info("%s %s", "removed" if gone else "couldn't remove yet:", path)
    return gone


def _delete_tree(hive, path: str, view: int = 0):
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_ALL_ACCESS | view) as k:
            while True:
                try:
                    sub = winreg.EnumKey(k, 0)
                except OSError:
                    break
                _delete_tree(hive, rf"{path}\{sub}", view)
        winreg.DeleteKeyEx(hive, path, view)
        log.info("deleted registry key %s", path)
    except FileNotFoundError:
        pass


def _process_paths() -> list[tuple[int, str]]:
    """(pid, exe path) of every process we may read, by Toolhelp (no console, no WMI)."""
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.OpenProcess.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(2, 0)   # TH32CS_SNAPPROCESS
    out = []
    if not snap or snap == wintypes.HANDLE(-1).value:
        return out
    try:
        e = Entry()
        e.dwSize = ctypes.sizeof(Entry)
        ok = k32.Process32FirstW(wintypes.HANDLE(snap), ctypes.byref(e))
        while ok:
            if e.szExeFile.lower() in APP_EXES:
                h = k32.OpenProcess(0x1000, False, e.th32ProcessID)   # QUERY_LIMITED
                if h:
                    buf = ctypes.create_unicode_buffer(1024)
                    size = wintypes.DWORD(1024)
                    if k32.QueryFullProcessImageNameW(wintypes.HANDLE(h), 0, buf,
                                                      ctypes.byref(size)):
                        out.append((e.th32ProcessID, buf.value))
                    k32.CloseHandle(wintypes.HANDLE(h))
            ok = k32.Process32NextW(wintypes.HANDLE(snap), ctypes.byref(e))
    finally:
        k32.CloseHandle(wintypes.HANDLE(snap))
    return out


def close_apps(dirs: list[Path]):
    """Stop Onion Board if it's running from one of `dirs` (only those: another
    program called Soundboard.exe is left alone), so its files can go."""
    from soundboard.mic import michelper
    dirs = [*dirs, michelper.helper_dir()]
    for pid, exe in _process_paths():
        p = Path(exe)
        if any(p.is_relative_to(d) for d in dirs) and pid != os.getpid():
            log.info("closing %s (%d)", exe, pid)
            subprocess.run([systools.tool("taskkill"), "/F", "/T", "/PID", str(pid)],
                           capture_output=True, creationflags=_CREATE_NO_WINDOW)
    time.sleep(1)


def admin_part() -> int:
    """Elevated: the mic effect, the mic helper, and everything machine-wide. 0 when
    done, RESTART when a file in use goes at the next restart, 1 if the mic effect
    couldn't come off (its notes are kept, so running this again can finish)."""
    from soundboard.mic import directmic as dm, michelper
    dm._enable_privileges("SeBackupPrivilege", "SeRestorePrivilege")
    machine_dirs = install_dirs((winreg.HKEY_LOCAL_MACHINE,))
    close_apps(machine_dirs)
    failed = False
    lock = dm._admin_lock()   # never at the same time as an app's own admin step
    if lock is None:
        log.error("Onion Board's mic setup is running right now: try again in a minute")
        return 1
    try:
        if dm.installed_on() or dm.anything_installed():
            code = dm.admin_uninstall()
            log.info("taking the mic effect off: %s", code)
            failed = code not in dm.DONE_CODES
        for guid in mics_with_effect():   # in a slot, but no notes: just take it out
            code = dm.admin_cleanup(guid)
            log.info("cleaning %s: %s", guid, code)
            failed = failed or code not in dm.DONE_CODES
        if not failed and dm.anything_installed():
            failed = dm.admin_uninstall() not in dm.DONE_CODES
    finally:
        dm._release(lock)
    if michelper.leftover():
        michelper.remove_helper()
    for name in FIREWALL_RULES:
        subprocess.run([systools.tool("netsh"), "advfirewall", "firewall", "delete", "rule",
                        f"name={name}"], capture_output=True, creationflags=_CREATE_NO_WINDOW)
    later = False
    for d in machine_dirs:
        later |= not _remove(d)
    for view, path in _uninstall_entries(winreg.HKEY_LOCAL_MACHINE):
        _delete_tree(winreg.HKEY_LOCAL_MACHINE, path, view)
    if failed:
        log.error("the mic effect is still on a mic: its notes are kept so this can be run again")
        return 1
    _delete_tree(winreg.HKEY_LOCAL_MACHINE, STATE_ROOT)
    later |= not _remove(programdata_dir())
    later |= any(d.exists() for d in (dm.install_dir(), *michelper._helper_dirs()))
    return RESTART if later else 0


def user_part(remove_sounds: bool) -> bool:
    """This user's part (no admin): True if all of it is gone now."""
    dirs = install_dirs((winreg.HKEY_CURRENT_USER,))
    links = shortcuts(link_targets())
    close_apps(dirs)
    ok = True
    for d in dirs:
        ok &= _remove(d)
    for view, path in _uninstall_entries(winreg.HKEY_CURRENT_USER):
        _delete_tree(winreg.HKEY_CURRENT_USER, path, view)
    for lnk in links:
        ok &= _remove(lnk)
    for key, name in run_values():
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, name)
            log.info("removed start-up entry %s", name)
        except OSError:
            ok = False
    if remove_sounds:
        ok &= _remove(appdata_dir())
    return ok


# ---------------------------------------------------------------------- running it

def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def run_elevated(args: list[str], wait_s: float = 600.0,
                 source: tuple[str, ...] = ("-m", "soundboard.core.cleanup")) -> int | None:
    """Run this program again as admin and wait: its exit code, None if Windows' prompt
    was answered No (or it didn't finish in time). From source, Python gets `source`
    first (the uninstaller's tidy-up passes main.py in `args` instead)."""
    from ctypes import wintypes

    class Info(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong),
                    ("hwnd", wintypes.HWND), ("lpVerb", wintypes.LPCWSTR),
                    ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int),
                    ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE),
                    ("hProcess", wintypes.HANDLE)]

    if getattr(sys, "frozen", False):
        exe, params = sys.executable, args
    else:   # from source: python -m soundboard.core.cleanup
        exe, params = sys.executable, [*source, *args]
    info = Info(cbSize=ctypes.sizeof(Info), fMask=0x40,   # SEE_MASK_NOCLOSEPROCESS
                lpVerb="runas", lpFile=exe, lpParameters=subprocess.list2cmdline(params),
                lpDirectory=str(Path(exe).parent), nShow=0)
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)) or not info.hProcess:
        return None
    k32 = ctypes.windll.kernel32
    try:
        if k32.WaitForSingleObject(info.hProcess, int(wait_s * 1000)) != 0:
            return None
        code = wintypes.DWORD()
        k32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        return code.value
    finally:
        k32.CloseHandle(info.hProcess)


def ask(question: str, default: bool) -> bool:
    hint = "[Y/n]" if default else "[y/N]"
    try:
        answer = input(f"{question} {hint} ").strip().lower()
    except EOFError:
        return default
    return default if not answer else answer.startswith("y")


def log_file() -> Path:
    return Path(tempfile.gettempdir()) / "OnionBoardCleanup.log"


def setup_logging(console: bool):
    handlers: list[logging.Handler] = [logging.FileHandler(log_file(), encoding="utf-8")]
    if console:
        h = logging.StreamHandler(sys.stdout)
        h.setLevel(logging.WARNING)
        handlers.append(h)
    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")


def main(argv: list[str]) -> int:
    if argv == [ADMIN_PART]:
        setup_logging(console=False)
        try:
            return admin_part()
        except Exception:  # noqa: BLE001
            log.exception("the admin part failed")
            return 1
    unknown = set(argv) - {"--yes", "--remove-sounds", "--dry-run"}
    if unknown:
        print("Usage: OnionBoardCleanup.exe [--yes] [--remove-sounds] [--dry-run]")
        return 2
    yes, dry = "--yes" in argv, "--dry-run" in argv
    remove_sounds = "--remove-sounds" in argv
    setup_logging(console=True)
    print("Onion Board cleanup\n")
    machine = machine_items()
    user = user_items(remove_sounds=False)
    has_sounds = appdata_dir().exists()
    if not machine and not user and not (has_sounds and remove_sounds):
        print("Nothing of Onion Board was found on this PC (apart from your sounds"
              f" in {appdata_dir()})." if has_sounds else
              "Nothing of Onion Board was found on this PC. You're all clean.")
        return _done(0, yes)
    print("Found:")
    for line in [*machine, *user]:
        print(f"  - {line}")
    if has_sounds:
        print(f"\nYour sounds and settings ({appdata_dir()}) are kept unless you say"
              " otherwise.")
    if dry:
        return 0
    print()
    if not yes and not ask("Remove all of this?", True):
        print("Nothing was changed.")
        return _done(0, yes)
    if has_sounds and not yes and not remove_sounds:
        remove_sounds = ask("Also delete your sounds and settings?", False)
    code = 0
    if machine:
        print("\nWorking (Windows' sound stops for a few seconds while the mic effect"
              " comes off)...")
        if is_admin():
            code = admin_part()
        else:
            print("Windows will ask for permission: that part changes your mic's settings.")
            got = run_elevated([ADMIN_PART])
            code = 1 if got is None else got
            if got is None:
                print("\nWindows' prompt was answered No, so the mic effect is still there."
                      " Run this again and answer Yes.")
    user_ok = user_part(remove_sounds)
    print()
    if code == 1:
        print(f"Not everything could be removed. The details are in {log_file()}."
              " Running this again usually finishes it.")
    elif code == RESTART or not user_ok:
        print("Done. A few files were in use: restart your PC to finish removing them.")
    else:
        print("Done: Onion Board is gone from this PC." + ("" if remove_sounds or not has_sounds
              else f" Your sounds are still in {appdata_dir()}."))
    return _done(1 if code == 1 else 0, yes)


def _done(code: int, yes: bool) -> int:
    if not yes and sys.stdin and sys.stdin.isatty():
        try:
            input("\nPress Enter to close.")
        except EOFError:
            pass
    return code


if __name__ == "__main__":
    if getattr(sys, "frozen", False):
        sys.path.insert(0, str(Path(sys.executable).parent))
    sys.exit(main(sys.argv[1:]))
