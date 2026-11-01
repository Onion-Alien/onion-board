"""Optional add-on modules, dropped into a `modules` folder as their own subfolders.

    <module folder>/
        module.json      {"id", "name", "version", "description", "kind", ...}
        ...

The kinds:

  "effects"  An `entry` Python file loaded into the app. Its `register(api)` adds
             voice effects with `api.register_effect(EffectSubclass)`. It may only
             import what the app itself ships (numpy, soxr, scipy.fft, the stdlib…),
             because the packaged app has no pip.

  "service"  A separate program the app launches and talks to over a loopback
             socket (see `soundboard.speech.service`). This is for heavy add-ons
             such as live speech recognition: their dependencies stay in their own
             environment, and if they crash or stall the audio never notices.
             `command` is the argv; "{python}" means the module's own
             .venv\\Scripts\\python.exe (made by its install script) and "{dir}" its
             folder.

  "translation"  A language the live computer voice can speak in. Nothing to run:
             `download` names a translation model ({"url", "sha256", "bytes"}) that
             is fetched only when the user asks for it (see
             `soundboard.speech.translation`), and the live-voice helper loads it.
             `language` is its code (de, es…), `language_name` its name.

  "triggers" The Triggers tab (Onion Watch, soundboard.addons.watchaddon). A Python
             package (`package`, a folder inside the module's) loaded into the app
             from the module's folder, and `entry`, a module in it whose
             `create(host)` makes the tab (or `create(host, parent)`, made on the
             page it goes on; see soundboard.ui.triggers.triggershost for the
             host). `api_version` is the version of that host interface it was
             written for: TRIGGERS_API is what this app can host, and anything else
             is refused with a message. `imports` lists what it needs from outside
             the standard library, checked before it's loaded. Like "effects", it
             may only import what the app ships.

  "remote"   Another way to control the board, such as the phone remote. Packaged
             like "triggers" (`package`, `entry`, `api_version`, `imports`), but
             `create(host)` gets soundboard.ui.settings.remotehost.RemoteHost (version
             REMOTE_API) and returns an object with `card(parent)` (its card on
             Settings → Remote) and `stop()`. Loaded at start-up.

Modules are searched for in %APPDATA%\\OnionBoard\\modules (where users drop
downloads) and in the `modules` folder next to the app (or the repo root when
running from source).
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from soundboard import voicefx
from soundboard.sounds import library
from soundboard.online import net
from soundboard.core import errors
from soundboard.i18n import _, ngettext

log = logging.getLogger(__name__)

KINDS = ("effects", "service", "translation", "triggers", "remote")
INSTALL_STEP_TIMEOUT_S = 30 * 60     # one install step (pip) before it's given up on
# In a service's folder while its install steps run: still there on the next start means
# the app was closed or crashed mid-install, so its .venv is half made (not installed)
INSTALLING = ".installing"
TRIGGERS_API = (1, 1)   # the oldest and newest "triggers" api_version this app can host
REMOTE_API = (1, 1)     # ...and "remote" api_version
PACKAGE_KINDS = {"triggers": TRIGGERS_API, "remote": REMOTE_API}   # loaded as packages
MAX_ZIP_FILES = 2000                  # a module zip with more is refused
MAX_ZIP_UNPACKED = 200 << 20          # ...or that would unpack to more than this
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class ModuleError(Exception):
    """A module that can't be installed or loaded: the message is for the user."""


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def search_dirs() -> list[Path]:
    return [library.APP_DIR / "modules", app_root() / "modules"]


@dataclass
class ModuleInfo:
    id: str
    name: str
    version: str
    description: str
    kind: str
    path: Path
    entry: str = ""
    command: list[str] = field(default_factory=list)
    provides: list[str] = field(default_factory=list)
    install_steps: list[list[str]] = field(default_factory=list)
    language: str = ""
    language_name: str = ""
    download: dict = field(default_factory=dict)
    credits: str = ""
    api_version: int = 0
    package: str = ""
    imports: list[str] = field(default_factory=list)
    error: str = ""
    loaded: bool = False

    def resolved_command(self, extra: Sequence[str] = ()) -> list[str]:
        """argv for a service module, with {python} and {dir} filled in."""
        return [self._fill(a) for a in self.command] + list(extra)

    def _fill(self, arg: str, base_python: str = "python") -> str:
        venv_py = self.path / ".venv" / "Scripts" / "python.exe"
        py = str(venv_py) if venv_py.exists() else "python"
        return (arg.replace("{base_python}", base_python).replace("{python}", py)
                .replace("{dir}", str(self.path)))

    @property
    def installed(self) -> bool:
        """For a service: are its dependencies set up (its own venv exists)? For a
        translation: has its model been downloaded?"""
        if self.kind == "translation":
            from soundboard.speech import translation
            return translation.is_downloaded(self)
        if self.kind != "service" or not any("{python}" in a for a in self.command):
            return True
        return ((self.path / ".venv" / "Scripts" / "python.exe").exists()
                and not (self.path / INSTALLING).exists() and not self.broken)

    @property
    def broken(self) -> bool:
        """A service set up once whose environment can't start any more: the Python it
        was made from is gone (uninstalled, or upgraded into another folder). Its
        install, run again, repairs it (soundboard.online.pyget)."""
        venv = self.path / ".venv"
        if self.kind != "service" or not (venv / "Scripts" / "python.exe").exists():
            return False
        try:
            cfg = (venv / "pyvenv.cfg").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False   # can't tell: only a Python seen to be gone counts
        for line in cfg.splitlines():
            key, _eq, value = line.partition("=")
            if key.strip().lower() == "home":
                return not (Path(value.strip()) / "python.exe").is_file()
        return False


def _strings(v, what: str) -> list[str]:
    """A manifest list of strings (a lone string would otherwise run as one argument
    per character)."""
    if not (isinstance(v, list) and all(isinstance(a, str) for a in v)):
        raise ValueError(f"{what} must be a list of strings")
    return list(v)


def _read(folder: Path) -> ModuleInfo | None:
    mf = folder / "module.json"
    if not mf.is_file():
        return None
    try:
        # utf-8-sig: Notepad and PowerShell save JSON with a byte-order mark
        d = json.loads(mf.read_text(encoding="utf-8-sig"))
        if not isinstance(d, dict):
            raise ValueError("not a JSON object")
        install = d.get("install", [])
        if not isinstance(install, list):
            raise ValueError("install must be a list of commands")
        info = ModuleInfo(id=str(d["id"]), name=str(d.get("name", d["id"])),
                          version=str(d.get("version", "0")),
                          description=str(d.get("description", "")),
                          kind=str(d.get("kind", "")), path=folder,
                          entry=str(d.get("entry", "")),
                          command=_strings(d.get("command", []), "command"),
                          provides=[str(a) for a in d.get("provides", [])],
                          install_steps=[_strings(step, "each install step")
                                         for step in install],
                          language=str(d.get("language", "")),
                          language_name=str(d.get("language_name", "")),
                          download=dict(d.get("download") or {}),
                          credits=str(d.get("credits", "")),
                          package=str(d.get("package", "")),
                          imports=_strings(d.get("imports", []), "imports"))
        api = d.get("api_version", 0)
        info.api_version = api if isinstance(api, int) and not isinstance(api, bool) else 0
    except (OSError, ValueError, KeyError, TypeError) as e:
        log.warning("bad module.json in %s: %s", folder, e)
        return ModuleInfo(id=folder.name, name=folder.name, version="?", description="",
                          kind="?", path=folder, error=f"bad module.json: {errors.plain(e)}")
    if info.kind not in KINDS:
        info.error = f"unknown kind {info.kind!r}"
    elif info.kind == "effects" and not (folder / info.entry).is_file():
        info.error = f"entry file {info.entry!r} not found"
    elif info.kind == "service" and not info.command:
        info.error = "no command"
    elif info.kind == "translation" and not (
            re.fullmatch(r"[a-z]{2,3}(-[A-Z]{2})?", info.language)
            and str(info.download.get("url", "")).startswith("https://")
            and re.fullmatch(r"[0-9a-f]{64}", str(info.download.get("sha256", "")))):
        info.error = "needs a language code and an https download with its sha256"
    elif info.kind in PACKAGE_KINDS:
        info.error = _package_error(info)
    return info


def _package_error(info: ModuleInfo) -> str:
    """Why a "triggers" / "remote" module can't be loaded ("" if it can be tried)."""
    pkg, entry = info.package, info.entry
    if not (_NAME.fullmatch(pkg) and (info.path / pkg / "__init__.py").is_file()):
        return f"package {pkg!r} not found"
    if not (entry == pkg or entry.startswith(pkg + ".")) or not all(
            _NAME.fullmatch(p) for p in entry.split(".")):
        return f"entry {entry!r} isn't a module of {pkg!r}"
    low, high = PACKAGE_KINDS[info.kind]
    if info.api_version > high:
        return _("it needs a newer Onion Board: update Onion Board first")
    if info.api_version < low:
        return _("it's too old for this Onion Board: get its update")
    return ""


def dirs_stamp(dirs: list[Path] | None = None) -> tuple:
    """When each add-on folder last changed (an add-on put in or taken out changes
    it): what discover() found still holds while this is the same."""
    out = []
    for base in dirs if dirs is not None else search_dirs():
        try:
            out.append((str(base), base.stat().st_mtime_ns))
        except OSError:
            out.append((str(base), None))
    return tuple(out)


def discover(dirs: list[Path] | None = None) -> list[ModuleInfo]:
    """Every module found; the first folder wins when two have the same id."""
    found: dict[str, ModuleInfo] = {}
    for base in dirs if dirs is not None else search_dirs():
        try:
            subs = sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []
        except OSError as e:
            log.warning("can't list the add-ons in %s: %s", base, e)
            continue
        for sub in subs:
            # a folder Windows won't let us read (locked by an antivirus, no permission, a
            # link it refuses to follow: WinError 448) is one broken add-on, never a crash
            # at start-up
            try:
                info = _read(sub)
            except OSError as e:
                log.warning("can't read the add-on in %s: %s", sub, e)
                info = ModuleInfo(id=sub.name, name=sub.name, version="?", description="",
                                  kind="?", path=sub,
                                  error=f"can't read its folder: {errors.plain(e)}")
            if info is not None and info.id not in found:
                found[info.id] = info
    return list(found.values())


def find(module_id: str, dirs: list[Path] | None = None) -> ModuleInfo | None:
    """The module with this id as discover() finds it, or None."""
    return next((m for m in discover(dirs) if m.id == module_id), None)


def env_zip(var: str) -> Path | None:
    """The zip the environment variable `var` names (a build to try before it's
    released), or None."""
    v = os.environ.get(var, "").strip().strip('"')
    return Path(v) if v else None


def zip_version(path: Path, module_id: str) -> str:
    """The version in a module zip's <module_id>/module.json, or "?"."""
    try:
        with zipfile.ZipFile(path) as z:
            d = json.loads(z.read(f"{module_id}/module.json").decode("utf-8-sig"))
        return str(d.get("version", "?"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, AttributeError):
        return "?"


class ModuleAPI:
    """What an effects module's `register(api)` is handed."""

    Effect = voicefx.Effect
    Param = voicefx.Param

    def __init__(self, info: ModuleInfo):
        self.info = info
        self.effects: list[str] = []

    def register_effect(self, cls):
        voicefx.register(cls)
        self.effects.append(cls.type)


_LOADED: dict[Path, list[str]] = {}    # module folder -> effect types (loaded once per run)


def load_effects(infos: list[ModuleInfo]) -> None:
    """Import every effects module and let it register. Failures are recorded on the
    module (and shown in the UI), never raised: a bad add-on can't stop the app.
    A module already loaded this run isn't imported again (restart to update one)."""
    for info in infos:
        if info.kind != "effects" or info.error or info.loaded:
            continue
        if info.path in _LOADED:
            info.provides, info.loaded = _LOADED[info.path], True
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                f"soundboard_module_{info.id.replace('-', '_')}", info.path / info.entry)
            assert spec is not None and spec.loader is not None   # a .py path
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            api = ModuleAPI(info)
            mod.register(api)
            info.provides = api.effects
            info.loaded = True
            _LOADED[info.path] = api.effects
            log.info("loaded module %s %s: %s", info.id, info.version, ", ".join(api.effects))
        except Exception as e:  # noqa: BLE001
            info.error = _("failed to load: {error}", error=errors.plain(e))
            log.exception("module %s failed to load", info.id)


def _importable(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _forget(package: str):
    for name in [n for n in sys.modules if n == package or n.startswith(package + ".")]:
        del sys.modules[name]


def _load_all(package: str, pkg_dir: Path):
    """Import every file of a loaded add-on now, not when a button first needs one.
    The running copy then never reads its folder again, so an update installed
    while the app runs (it's used after a restart) can't hand the old code a new
    file, or none: a missing one crashed *Recently deleted*. A file that fails is
    logged and left to fail where it's used, as it would have. A `__main__.py` is
    skipped: it's the add-on's own `python -m` start, and importing it runs the
    add-on as an app of its own (a second QApplication)."""
    for path in sorted(pkg_dir.rglob("*.py")):
        rel = path.relative_to(pkg_dir).with_suffix("")
        parts = [p for p in rel.parts if p != "__init__"]
        if any(not p.isidentifier() for p in parts) or "__main__" in parts:
            continue
        name = ".".join([package, *parts])
        if name in sys.modules:
            continue
        try:
            importlib.import_module(name)
        except Exception:  # noqa: BLE001 - one bad file can't stop the add-on loading
            log.warning("module file %s didn't load", name, exc_info=True)


def precompile(infos: list[ModuleInfo], wait: Callable[[], bool] = lambda: False) -> int:
    """Write the compiled copy (__pycache__) of each loaded-into-the-app add-on's files
    that hasn't one yet, or an old one. The packaged app never writes them by itself
    (PyInstaller turns that off), so the first open of the Triggers tab compiled all
    of Onion Watch on the UI thread, every run: ~0.6 s holding Python's lock, and a
    sound playing skipped. With them it loads in ~0.4 s and nothing skips. Runs off
    the UI thread; a file is only compiled while `wait()` is False (nothing plays),
    as compiling one still holds the lock for a few tens of ms. Returns how many."""
    import py_compile
    done = 0
    for info in infos:
        if info.kind not in PACKAGE_KINDS or not info.package:
            continue
        for src in sorted((info.path / info.package).rglob("*.py")):
            try:
                pyc = Path(importlib.util.cache_from_source(str(src)))
                if pyc.exists() and pyc.stat().st_mtime >= src.stat().st_mtime:
                    continue
                for _try in range(600):   # up to ~10 min of sounds playing, then anyway
                    if not wait():
                        break
                    time.sleep(1)
                py_compile.compile(str(src), cfile=str(pyc), doraise=True)
                done += 1
            except Exception:  # noqa: BLE001 - it loads from source as before
                log.debug("couldn't precompile %s", src, exc_info=True)
    if done:
        log.info("precompiled %d add-on files", done)
    return done


def load_package(info: ModuleInfo):
    """Load a "triggers" or "remote" module's package from its folder and return its
    `entry` module (which has create(host)). Loaded once per run: a copy already loaded
    from the same folder, at the same version, is reused; a different one needs a
    restart (Python can't swap a package it's running). Raises ModuleError."""
    if info.kind not in PACKAGE_KINDS:
        raise ModuleError(_("{name} isn't an add-on that loads into the app", name=info.name))
    if info.error:
        raise ModuleError(info.error)
    missing = [m for m in info.imports if not _importable(m)]
    if missing:
        raise ModuleError(_("it needs {modules}, which this Onion Board doesn't have: "
                            "update {name} or Onion Board",
                            modules=", ".join(missing), name=info.name))
    pkg_dir = info.path / info.package
    have = sys.modules.get(info.package)
    if have is not None:
        where = Path(getattr(have, "__file__", "") or ".").resolve().parent
        if where != pkg_dir.resolve() or getattr(have, "__version__", None) != info.version:
            raise ModuleError(_("restart Onion Board to use {name} {version}",
                                name=info.name, version=info.version))
    else:
        spec = importlib.util.spec_from_file_location(
            info.package, pkg_dir / "__init__.py", submodule_search_locations=[str(pkg_dir)])
        assert spec is not None and spec.loader is not None   # a .py path
        pkg = importlib.util.module_from_spec(spec)
        sys.modules[info.package] = pkg
        try:
            spec.loader.exec_module(pkg)
        except Exception as e:  # noqa: BLE001 - a bad add-on can't stop the app
            _forget(info.package)
            log.exception("module %s failed to load", info.id)
            raise ModuleError(_("failed to load: {error}", error=errors.plain(e))) from e
    try:
        entry = importlib.import_module(info.entry)
    except Exception as e:  # noqa: BLE001
        _forget(info.package)
        log.exception("module %s failed to load", info.id)
        raise ModuleError(_("failed to load: {error}", error=errors.plain(e))) from e
    if not callable(getattr(entry, "create", None)):
        raise ModuleError(f"{info.entry} has no create()")
    _load_all(info.package, pkg_dir)
    info.loaded = True
    log.info("loaded module %s %s from %s", info.id, info.version, info.path)
    return entry


def _check_zip(z: zipfile.ZipFile, module_id: str) -> None:
    """Refuse a zip that would write anywhere but one `module_id` folder, holds
    links, or is far too big once unpacked."""
    items = z.infolist()
    if not items or len(items) > MAX_ZIP_FILES:
        raise ModuleError(_("it isn't an add-on (empty, or far too many files)"))
    total = 0
    for i in items:
        n = i.filename
        parts = PurePosixPath(n).parts
        if (not parts or parts[0] != module_id or n.startswith("/") or "\\" in n or ":" in n
                or ".." in parts):
            raise ModuleError(_("it holds a file outside its own folder ({file})", file=n))
        if stat.S_ISLNK(i.external_attr >> 16):
            raise ModuleError(_("it holds a link ({file})", file=n))
        total += i.file_size
    if total > MAX_ZIP_UNPACKED:
        raise ModuleError(_("it would unpack to far more than an add-on"))


def install_zip(path: Path, module_id: str, kind: str,
                base: Path | None = None) -> ModuleInfo:
    """Install a module from a zip holding one `<module_id>/` folder (module.json
    in it) into `base` (%APPDATA%\\OnionBoard\\modules): unpacked beside it first,
    checked, then swapped for any copy already there, so a failed install leaves the
    old one working. Returns the installed module. Raises ModuleError."""
    base = base if base is not None else library.APP_DIR / "modules"
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as e:
        raise ModuleError(_("it isn't a zip file that can be opened ({error})",
                            error=errors.plain(e))) from e
    staging = base.parent / f"modules-new-{uuid.uuid4().hex[:8]}"
    try:
        with z:
            _check_zip(z, module_id)
            try:
                d = json.loads(z.read(f"{module_id}/module.json").decode("utf-8-sig"))
            except KeyError as e:
                raise ModuleError(_("it has no module.json")) from e
            except ValueError as e:
                raise ModuleError(_("its module.json can't be read ({error})",
                                    error=errors.plain(e))) from e
            if not isinstance(d, dict) or d.get("id") != module_id or d.get("kind") != kind:
                raise ModuleError(_("it isn't the {module} add-on", module=module_id))
            staging.mkdir(parents=True)
            z.extractall(staging)
        info = _read(staging / module_id)
        if info is None or info.error:
            raise ModuleError(info.error if info is not None else _("it has no module.json"))
        base.mkdir(parents=True, exist_ok=True)
        dest, old = base / module_id, staging / f"{module_id}.old"
        if dest.exists():
            os.rename(dest, old)
        try:
            os.rename(staging / module_id, dest)
        except OSError:
            if old.exists() and not dest.exists():
                os.rename(old, dest)           # put the working copy back
            raise
    except OSError as e:
        raise ModuleError(_("it couldn't be installed ({error})", error=errors.plain(e))) from e
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    info = _read(dest)
    if info is None:   # read fine in staging a moment ago
        raise ModuleError(_("it has no module.json"))
    log.info("installed module %s %s into %s", module_id, info.version, dest)
    precompile([info])   # (on the download's thread) it's loaded straight after
    return info


def uninstall(module_id: str, base: Path | None = None) -> None:
    """Remove a module installed into `base` (%APPDATA%\\OnionBoard\\modules): moved
    aside in one step, so it's either there or gone, then deleted. Nothing there is
    fine. Raises ModuleError."""
    base = base if base is not None else library.APP_DIR / "modules"
    dest = base / module_id
    if dest.exists():
        gone = base.parent / f"modules-old-{uuid.uuid4().hex[:8]}"
        try:
            os.rename(dest, gone)
        except OSError as e:
            raise ModuleError(_("it couldn't be removed ({error})",
                                error=errors.plain(e))) from e
        shutil.rmtree(gone, ignore_errors=True)
        log.info("removed module %s from %s", module_id, dest)
    _remove_old_copies(module_id, base)


def _remove_old_copies(module_id: str, base: Path) -> None:
    """An update's old copies of `module_id` left in `base`: found by discover() once
    the add-on itself was gone, one quietly became the live add-on after Remove."""
    try:
        subs = [d for d in base.iterdir() if d.is_dir()]
    except OSError:
        return
    for d in subs:
        m = _OLD_COPY.fullmatch(d.name)
        if m is None or m["id"] != module_id or d.is_symlink():
            continue
        try:
            info = _read(d)
        except OSError:
            continue
        if info is not None and info.id == module_id:
            shutil.rmtree(d, ignore_errors=True)
            log.info("removed the old copy %s of module %s", d.name, module_id)


def install_fetched(path: Path, module_id: str, kind: str, base: Path | None,
                    downloads: Path) -> ModuleInfo:
    """install_zip, then delete the zip if it was downloaded into `downloads` (a
    local one stays). Raises ModuleError."""
    try:
        return install_zip(path, module_id, kind, base)
    finally:
        if path.parent == downloads:
            path.unlink(missing_ok=True)


def is_base_copy(info: ModuleInfo, module_id: str, base: Path | None = None) -> bool:
    """Whether `info` is the copy installed into `base` (default search_dirs()[0]),
    not one shipped with the app."""
    base = base if base is not None else search_dirs()[0]
    try:
        return info.path.resolve() == (base / module_id).resolve()
    except OSError:
        return False


def remove_env(info: ModuleInfo) -> None:
    """Delete what a service's install made in its folder (its .venv), keeping the
    add-on itself: moved aside in one step, so it's either set up or not, then deleted.
    Nothing there is fine. Raises ModuleError (a file in it still in use)."""
    venv = info.path / ".venv"
    if not venv.exists():
        return
    gone = info.path / f".venv-old-{uuid.uuid4().hex[:8]}"
    try:
        os.rename(venv, gone)
    except OSError as e:
        raise ModuleError(_("it couldn't be removed ({error})", error=errors.plain(e))) from e
    shutil.rmtree(gone, ignore_errors=True)
    log.info("removed the environment of module %s", info.id)


# Add-on copies left in %APPDATA%\OnionBoard (and its modules\): install_zip's and
# uninstall's own temp folders when deleting them failed (a file still open), and old
# or half-swapped copies of an add-on beside the real one ("onion-watch-old3",
# "onion-pocket-old-20261005111322", "onion-watch-staged-069"). Only names like these,
# and only folders holding that add-on's module.json, are ever touched.
_TEMP_COPY = re.compile(r"modules-(?:new|old)-[0-9a-f]{8}")
_OLD_COPY = re.compile(r"(?P<id>[a-z0-9][a-z0-9-]*?)-(?:old|staged)(?:-?\d+)?")
LEFTOVER_MIN_AGE_S = 3600   # newer ones may be an install going on right now


def prune_leftovers(app_dir: Path | None = None, loaded=None,
                    now: float | None = None) -> int:
    """Delete leftover add-on copies (see _TEMP_COPY / _OLD_COPY) from `app_dir`
    (%APPDATA%\\OnionBoard) and its modules\\, keeping the newest old copy of each
    add-on (outside modules\\ if there is one). Never a folder an add-on is found in
    (`discover`) or one holding a file in `loaded` (default: every module imported in
    this process), nor one touched in the last hour. Returns how many went. Run off the
    UI thread."""
    app_dir = app_dir if app_dir is not None else library.APP_DIR
    now = time.time() if now is None else now
    if loaded is None:
        loaded = [f for m in list(sys.modules.values())
                  if isinstance(f := getattr(m, "__file__", None), str)]
    in_use = {info.path.resolve() for info in discover([app_dir / "modules",
                                                        app_root() / "modules"])}
    loaded = [Path(f).resolve() for f in loaded]

    def protected(d: Path) -> bool:
        r = d.resolve()
        return (r in in_use or any(r in p.parents for p in in_use)
                or any(r in f.parents for f in loaded))

    temps, copies = [], {}
    for base in (app_dir, app_dir / "modules"):
        try:
            subs = [p for p in base.iterdir() if p.is_dir()]
        except OSError:
            continue
        for d in subs:
            try:
                if (d.is_symlink() or getattr(d, "is_junction", lambda: False)()
                        or now - d.stat().st_mtime < LEFTOVER_MIN_AGE_S or protected(d)):
                    continue
                if base == app_dir and _TEMP_COPY.fullmatch(d.name):
                    temps.append(d)
                elif (m := _OLD_COPY.fullmatch(d.name)):
                    info = _read(d)
                    if info is not None and info.id == m["id"]:
                        # one outside modules\ is kept first: no start-up ever scans it
                        copies.setdefault(info.id, []).append(
                            (base == app_dir, d.stat().st_mtime, d))
            except OSError:
                continue
    doomed = list(temps)
    for found in copies.values():
        found.sort()
        doomed += [d for *_, d in found[:-1]]   # the newest one stays, for going back
    gone = 0
    for d in doomed:
        shutil.rmtree(d, ignore_errors=True)
        if d.exists():
            log.info("couldn't remove the old add-on copy %s yet", d.name)
        else:
            gone += 1
    if gone:
        log.info("removed %d old add-on cop%s", gone, "y" if gone == 1 else "ies")
    return gone


def _job_for(p: subprocess.Popen):
    """A job object holding `p` and whatever it starts (Windows), or None."""
    if os.name != "nt":
        return None
    from soundboard.online.tor import JobObject
    job = None
    try:
        job = JobObject()
        job.assign(p)
        return job
    except Exception as e:  # noqa: BLE001 - falls back to killing by process tree
        log.warning("install step: no job object (%s); killing by process tree", e)
        if job is not None:
            job.close()
        return None


def _kill_tree(p: subprocess.Popen, job) -> None:
    """Kill an install step and everything it started (by its job, or its process
    tree by PID), so nothing is left holding its output pipe open."""
    if job is not None:
        job.close()             # kill-on-close: the step and all its children
    elif os.name == "nt" and p.poll() is None:
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           stdin=subprocess.DEVNULL, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        p.kill()
    except OSError:
        pass


def install(info: ModuleInfo, on_line: Callable[[str], object],
            on_note: Callable[[str], object] | None = None) -> bool:
    """Run the module's "install" steps (see _install), counting how it went for the
    daily usage count (usage.py: the add-on's name from a fixed list and, when it
    failed, why from usage.ADDON_FAILS; nothing else). A first install that failed
    before its packages were all in takes its half-made environment away again, so the
    add-on isn't taken for installed (no Install button, the installer skipping it)."""
    from soundboard.core import usage
    repair = info.broken
    fresh = not info.installed      # (a repair too: its old environment goes first)
    tag = usage.addon_tag(info.id)
    mark = info.path / INSTALLING
    if mark.exists():   # the app closed mid-install last time: start that one again clean
        log.info("module %s: its last install didn't finish; making it again", info.id)
        shutil.rmtree(info.path / ".venv", ignore_errors=True)
    try:
        mark.touch()
    except OSError as e:
        log.warning("module %s: can't mark its install as running: %s", info.id, e)
    try:
        why = _install(info, on_line, on_note)
    except Exception as e:
        usage.used(f"addon-failed-{tag}")
        usage.used(f"addon-failed-{tag}-other")
        usage.failed("addon-other", tag, *usage.error_detail(e))   # its type and place
        raise
    finally:   # it ended (either way) with the app still running: no longer half made
        mark.unlink(missing_ok=True)
    if why:
        usage.used(f"addon-failed-{tag}")
        usage.used(f"addon-failed-{tag}-{why}")
        # only the model download failing: its packages are in, and it gets the
        # model itself when it starts
        if fresh and not why.startswith("download") and (info.path / ".venv").exists():
            log.info("module %s: removing its half-made environment", info.id)
            shutil.rmtree(info.path / ".venv", ignore_errors=True)
        return False
    usage.used(f"addon-installed-{tag}")
    if repair:
        usage.used("addon-repaired")
    return True


def _step_word(step: Sequence[str]) -> str:
    """Which install step this is, as a fixed word for the count: "venv", "pip", the
    model "download", else "step"."""
    for i, a in enumerate(step):
        if a == "-m" and i + 1 < len(step) and step[i + 1] in ("venv", "pip"):
            return step[i + 1]
    return "download" if "--download" in step else "step"


# why a failed install step failed, read from the end of what it printed (_output_why):
# the first of these whose pattern matches, else "other". Counted as these words only
# (usage.failed "addon-step"), never the output itself.
OUTPUT_WHY = (
    ("ssl", r"SSLError|CERTIFICATE_VERIFY_FAILED|SSL: "),
    ("proxy", r"ProxyError|Cannot connect to proxy"),
    ("network", r"ConnectionError|ConnectTimeout|ReadTimeout|Max retries exceeded|"
                r"Could not fetch URL|getaddrinfo failed|Temporary failure in name resolution|"
                r"No connection could be made|Read timed out|IncompleteRead|"
                r"Connection (?:reset|aborted|broken)"),
    ("no-match", r"No matching distribution|Could not find a version that satisfies|"
                 r"ResolutionImpossible|requires a different Python"),
    ("hash", r"DO NOT MATCH THE HASHES|hash mismatch"),
    ("disk", r"No space left on device|\[Errno 28\]|WinError 112\b|not enough space"),
    ("long-path", r"WinError 206\b|filename or extension is too long|Long Path"),
    ("in-use", r"WinError 32\b|being used by another process"),
    ("denied", r"WinError 5\b|Access is denied|PermissionError|\[Errno 13\]"),
    ("build", r"Failed building wheel|Failed to build|subprocess-exited-with-error|"
              r"Microsoft Visual C\+\+|metadata-generation-failed"),
    ("memory", r"MemoryError|out of memory"),
    ("python", r"No module named|DLL load failed|ImportError"),
)
OUTPUT_WORDS = (*(w for w, _ in OUTPUT_WHY), "silent", "other")


def _output_why(lines: Sequence[str]) -> str:
    """Why a step failed, as one of OUTPUT_WORDS, from the last lines it printed:
    "silent" when it printed nothing."""
    text = "\n".join(lines)
    if not text.strip():
        return "silent"
    for word, pattern in OUTPUT_WHY:
        if re.search(pattern, text, re.IGNORECASE):
            return word
    return "other"


def _step_failed(info: ModuleInfo, argv: Sequence[str], word: str,
                 lines: Sequence[str], how: str):
    """Log a failed install step with the end of what it printed (the user's log is what
    a report carries), and count which step and why (_output_why)."""
    why = _output_why(lines)
    log.warning("install of %s %s at: %s (%s); it printed last:\n%s", info.id, how,
                argv, why, "\n".join(lines[-15:]) or "(nothing)")
    from soundboard.core import usage
    usage.failed("addon-step", usage.addon_tag(info.id), word, why)


def _install(info: ModuleInfo, on_line: Callable[[str], object],
             on_note: Callable[[str], object] | None = None) -> str:
    """Run the module's "install" steps (module.json), streaming their output to
    `on_line`; getting a Python for it first when the PC has no good one (pyget), whose
    progress goes to `on_note` (our own words, not a step's output) or else `on_line`.
    Blocking: call from a worker thread. Returns "" on success, else why it didn't
    work, as one of usage.ADDON_FAILS."""
    if not info.install_steps:
        on_line(_("This add-on has no install steps."))
        return "step"
    if not net.allowed("addons"):
        on_line(net.off_message("addons"))
        return "off"
    from soundboard.online import netlog
    netlog.cause("addons", f"You installed or updated the {netlog.quoted(info.name)} "
                           "add-on")
    from soundboard.online import pyget
    if info.broken:   # its Python is gone: a new environment, made from one that's there
        log.info("module %s: its environment's Python is gone; making it again", info.id)
        shutil.rmtree(info.path / ".venv", ignore_errors=True)
    try:
        py = pyget.for_module(info.path, on_note or on_line)
    except pyget.GetError as e:
        on_line(str(e))
        return "python"
    for step in info.install_steps:
        argv = [info._fill(a, py) for a in step]
        on_line("> " + " ".join(argv[1:]))
        try:
            # pip & co. go online through the app's relay as "addons", so the
            # Connection setting holds and switching add-ons off stops them
            p = subprocess.Popen(argv, cwd=info.path, stdout=subprocess.PIPE,
                                 env=net.child_env("addons"),
                                 stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                 text=True, encoding="utf-8", errors="replace",
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            on_line(_("couldn't run it: {error}", error=errors.plain(e)))
            return "run"
        # a step that hangs (a stuck download, a prompt nobody sees) is killed, with
        # everything it started: a grandchild still holding the output pipe would
        # keep the read below waiting for ever
        job = _job_for(p)
        timed_out = threading.Event()

        def watchdog(p=p, timed_out=timed_out, job=job):
            timed_out.set()
            _kill_tree(p, job)

        last: deque[str] = deque(maxlen=40)   # the end of what it printed, for _step_failed
        timer = threading.Timer(INSTALL_STEP_TIMEOUT_S, watchdog)
        timer.daemon = True
        timer.start()
        try:
            assert p.stdout is not None   # stdout=PIPE
            for line in p.stdout:
                if line.strip():
                    on_line(line.rstrip())
                    last.append(line.rstrip())
            p.wait()
        finally:
            timer.cancel()
            if p.poll() is None:
                _kill_tree(p, job)
                p.wait()
            if job is not None:
                job.close()
        if timed_out.is_set():
            on_line(ngettext("stopped: it took over {n} minute. Check "
                             "your internet connection and press it again.",
                             "stopped: it took over {n} minutes. Check "
                             "your internet connection and press it again.",
                             INSTALL_STEP_TIMEOUT_S // 60))
            _step_failed(info, argv, _step_word(step), list(last), "timed out")
            return "download-timeout" if _step_word(step) == "download" else "timeout"
        if p.returncode != 0:
            on_line(_("failed (exit code {code})", code=p.returncode))
            _step_failed(info, argv, _step_word(step), list(last),
                         f"failed (exit code {p.returncode})")
            return _step_word(step)
    log.info("installed module %s", info.id)
    return ""
