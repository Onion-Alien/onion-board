"""A Python for the add-ons that run in their own (live voice, AI voices), got only when
the PC hasn't a good one.

Those add-ons are a helper program in their own environment (``.venv``, made by their
install steps with ``{base_python} -m venv``). The packaged app has no Python of its
own to make it from, and asking people to install one from python.org lost most of
them. So, for an add-on's install (modules.install):

1. The add-on's own private copy, if an earlier install already got one.
2. The PC's own Python, when it's 3.12 or 3.13 (the versions the add-ons' pinned
   requirements have wheels for), 64-bit x86 (live voice's ctranslate2 has no ARM64
   or 32-bit Windows wheels: pip would fail on it every time), has pip to make a venv
   with (ensurepip), and it starts.
3. Otherwise python.org's own build (the "python" package it publishes on nuget.org:
   a plain zip, no installer, pip and venv included), downloaded through net.urlopen
   (so it follows Connection), checked against the SHA-256 PINNED below before anything
   is unpacked, and unpacked into ``<add-on folder>\\.python``. Nothing is installed on
   the PC: no PATH, no registry, no Start menu. It's only that add-on's, and it goes
   when the add-on does (removing it, or uninstalling the app).

It can't be deleted once the add-on is set up: the add-on's ``.venv`` runs on it.

An environment whose Python has gone since (uninstalled, or upgraded to a new folder)
is *broken*: modules.ModuleInfo.broken spots it from the ``home`` line of its
``pyvenv.cfg``, and the Install button repairs it (a new ``.venv``, step 1 to 3 again).

To move to a newer Python: the ``python`` package's .nupkg from
api.nuget.org/v3-flatcontainer/python/<version>/, its SHA-256 here, and check both
add-ons install with it (``scripts`` has no helper: install them from the Voice tab).
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from soundboard.core import errors
from soundboard.online import net
from soundboard.i18n import _

log = logging.getLogger(__name__)

FEATURE = "addons"                   # net's switch: it's part of an add-on's install
VERSION = "3.12.10"
URL = f"https://api.nuget.org/v3-flatcontainer/python/{VERSION}/python.{VERSION}.nupkg"
SHA256 = "0eb85c2dfccccf1b17352de4c397f69194035b7d37149eacc16f1147d93de3b8"
MAX_BYTES = 40_000_000               # the package is 14.5 MB; anything far bigger isn't it
CHUNK = 256 * 1024
DOWNLOAD_TIMEOUT_S = 60.0            # with no bytes arriving for this long
CHECK_TIMEOUT_S = 20.0               # a Python's first start, behind a virus scan
GOOD = ((3, 12), (3, 13))            # a PC's own Python the add-ons can use
PLATFORM = "win-amd64"               # ...built for this (sysconfig.get_platform())
FOLDER = ".python"                   # in the add-on's folder
PREFIX = "tools/"                    # the Python inside the package


class GetError(Exception):
    """Python couldn't be got; the message is fit to show the user."""


def private_python(module_dir: Path) -> Path:
    return module_dir / FOLDER / "python.exe"


def _version(exe: str) -> tuple[int, int] | None:
    """(major, minor) of the Python at ``exe`` if it starts, has venv and pip's
    ensurepip, and (on Windows) is PLATFORM; else None."""
    try:
        p = subprocess.run([exe, "-c", "import sys, sysconfig, venv, ensurepip; "
                                       "print(*sys.version_info[:2], sysconfig.get_platform())"],
                           capture_output=True, text=True, timeout=CHECK_TIMEOUT_S,
                           stdin=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as e:
        log.info("python %s didn't start: %s", exe, e)
        return None
    try:
        major, minor, platform = p.stdout.split()
        version = int(major), int(minor)
    except ValueError:
        log.info("python %s: no version, or no venv / pip (exit %s)", exe, p.returncode)
        return None
    if os.name == "nt" and platform != PLATFORM:
        log.info("python %s is %s, not %s: no wheels for it", exe, platform, PLATFORM)
        return None
    return version


def pc_python() -> str | None:
    """The PC's own Python, when the add-ons can use it (GOOD); None otherwise. Runs it:
    never on the UI thread."""
    for name in ("py", "python"):
        found = shutil.which(name)
        if not found or "WindowsApps" in found:   # the Store stub only opens the Store
            continue
        v = _version(found)
        if v in GOOD:
            return found
        log.info("the PC's %s is Python %s: not one the add-ons can use", name, v)
    return None


def _download(to: Path, progress: Callable[[int, int], None] | None) -> None:
    """The package into the file ``to``, checked against SHA256. Raises GetError."""
    host = urllib.parse.urlsplit(URL).hostname
    req = urllib.request.Request(URL, headers={"User-Agent": "OnionBoard"})
    try:
        with net.urlopen(req, timeout=DOWNLOAD_TIMEOUT_S, feature=FEATURE) as r, \
                open(to, "wb") as f:
            got = net.read_capped(r, f, MAX_BYTES, chunk=CHUNK, progress=progress)
    except net.TooBig:
        raise GetError(_("The download isn't the Python it should be, so it "
                         "wasn't used.")) from None
    except net.ProxyError as e:   # FeatureOff included: switched off, nothing sent
        raise GetError(errors.plain(e)) from None
    except urllib.error.HTTPError as e:
        raise GetError(_("{host} said {error}.", host=host,
                         error=f"{e.code} {e.reason}")) from None
    except (urllib.error.URLError, OSError) as e:
        why = getattr(e, "reason", None) or e
        raise GetError(_("Couldn't reach {host} ({error}).", host=host, error=why)) from None
    if got != SHA256:
        log.warning("python download: SHA-256 %s, expected %s", got, SHA256)
        raise GetError(_("The download isn't the Python it should be, so it wasn't used."))


def unpack(package: Path, dest: Path) -> None:
    """The Python inside a checked package (its ``tools/`` folder) into ``dest``,
    replacing what's there. Each file goes to a path made from its name under
    ``tools/``; a name that would land outside ``dest`` is refused."""
    tmp = dest.with_name(dest.name + ".partial")
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        with zipfile.ZipFile(package) as z:
            for info in z.infolist():
                if not info.filename.startswith(PREFIX) or info.is_dir():
                    continue
                parts = PurePosixPath(info.filename[len(PREFIX):]).parts
                if not parts or any(p in ("", ".", "..") or ":" in p or "\\" in p
                                    for p in parts):
                    raise GetError(_("The download isn't the Python it should be, so it "
                                     "wasn't used."))
                out = tmp.joinpath(*parts)
                out.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, open(out, "wb") as f:
                    shutil.copyfileobj(src, f)
        if not (tmp / "python.exe").is_file():
            raise GetError(_("The download isn't the Python it should be, so it wasn't "
                             "used."))
        shutil.rmtree(dest, ignore_errors=True)
        tmp.rename(dest)
    except GetError:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    except (OSError, zipfile.BadZipFile) as e:
        shutil.rmtree(tmp, ignore_errors=True)
        raise GetError(_("Couldn't unpack Python into {folder} ({error}).", folder=dest,
                         error=getattr(e, "strerror", "") or e)) from None


def get(module_dir: Path, on_line: Callable[[str], object]) -> str:
    """Download and unpack the add-on's private Python; its python.exe. Raises
    GetError. Blocking: never on the UI thread."""
    log.info("getting Python %s for %s (%s)", VERSION, module_dir.name, net.describe(where=False))
    on_line(_("Getting Python for this add-on (about 15 MB)…"))
    last = [-1]

    def progress(done: int, total: int):
        pct = done * 100 // total if total else 0
        if pct // 10 != last[0]:   # a line every 10%, not every chunk
            last[0] = pct // 10
            on_line(_("Getting Python… {percent}%", percent=pct))

    part = module_dir / f"python-{VERSION}.nupkg.partial"
    try:
        _download(part, progress)
        unpack(part, module_dir / FOLDER)
    finally:
        try:
            part.unlink()
        except OSError:
            pass
    exe = private_python(module_dir)
    if _version(str(exe)) is None:
        raise GetError(_("Python was unpacked but won't start. An antivirus may have "
                         "blocked it."))
    log.info("Python %s unpacked into %s", VERSION, exe.parent)
    return str(exe)


def tidy(module_dir: Path) -> None:
    """Remove what a get() cut short (the app ended mid-download or mid-unpack: End
    task, a crash, the power) left in the add-on's folder: the half-downloaded package
    and a half-unpacked .python.partial. A new get() replaces them, but an install that
    takes the PC's own Python instead never would."""
    shutil.rmtree(module_dir / (FOLDER + ".partial"), ignore_errors=True)
    for part in module_dir.glob("python-*.nupkg.partial"):
        try:
            part.unlink()
            log.info("removed %s, left by a download that was cut short", part.name)
        except OSError:
            pass


def for_module(module_dir: Path, on_line: Callable[[str], object]) -> str:
    """The Python to make an add-on's environment from (see the module docstring for the
    order). Raises GetError. Blocking: never on the UI thread."""
    if not getattr(sys, "frozen", False):
        return sys.executable              # from source: the one running the app
    tidy(module_dir)
    own = private_python(module_dir)
    if own.is_file() and _version(str(own)) is not None:
        return str(own)
    found = pc_python()
    if found is not None:
        return found
    from soundboard.core import usage
    try:
        exe = get(module_dir, on_line)
    except GetError:
        usage.used("addon-python-failed")
        raise
    usage.used("addon-got-python")
    return exe
