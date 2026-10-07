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

  "triggers" The Triggers tab (Onion Watch, soundboard.watchaddon). A Python
             package (`package`, a folder inside the module's) loaded into the app
             from the module's folder, and `entry`, a module in it whose
             `create(host)` makes the tab (see soundboard.ui.triggershost for the
             host). `api_version` is the version of that host interface it was
             written for: TRIGGERS_API is what this app can host, and anything else
             is refused with a message. `imports` lists what it needs from outside
             the standard library, checked before it's loaded. Like "effects", it
             may only import what the app ships.

  "remote"   Another way to control the board, such as the phone remote. Packaged
             like "triggers" (`package`, `entry`, `api_version`, `imports`), but
             `create(host)` gets soundboard.ui.remotehost.RemoteHost (version
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
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from soundboard import voicefx
from soundboard import library, net
from soundboard import errors
from soundboard.i18n import _, ngettext

log = logging.getLogger(__name__)

KINDS = ("effects", "service", "translation", "triggers", "remote")
INSTALL_STEP_TIMEOUT_S = 30 * 60     # one install step (pip) before it's given up on
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
    return Path(__file__).resolve().parent.parent


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

    def resolved_command(self, extra: list[str] = ()) -> list[str]:
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
        return (self.path / ".venv" / "Scripts" / "python.exe").exists()


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


def discover(dirs: list[Path] | None = None) -> list[ModuleInfo]:
    """Every module found; the first folder wins when two have the same id."""
    found: dict[str, ModuleInfo] = {}
    for base in dirs if dirs is not None else search_dirs():
        if not base.is_dir():
            continue
        for sub in sorted(p for p in base.iterdir() if p.is_dir()):
            info = _read(sub)
            if info is not None and info.id not in found:
                found[info.id] = info
    return list(found.values())


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
    logged and left to fail where it's used, as it would have."""
    for path in sorted(pkg_dir.rglob("*.py")):
        rel = path.relative_to(pkg_dir).with_suffix("")
        parts = [p for p in rel.parts if p != "__init__"]
        if any(not p.isidentifier() for p in parts):
            continue
        name = ".".join([package, *parts])
        if name in sys.modules:
            continue
        try:
            importlib.import_module(name)
        except Exception:  # noqa: BLE001 - one bad file can't stop the add-on loading
            log.warning("module file %s didn't load", name, exc_info=True)


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
    log.info("installed module %s %s into %s", module_id, info.version, dest)
    return info


def uninstall(module_id: str, base: Path | None = None) -> None:
    """Remove a module installed into `base` (%APPDATA%\\OnionBoard\\modules): moved
    aside in one step, so it's either there or gone, then deleted. Nothing there is
    fine. Raises ModuleError."""
    base = base if base is not None else library.APP_DIR / "modules"
    dest = base / module_id
    if not dest.exists():
        return
    gone = base.parent / f"modules-old-{uuid.uuid4().hex[:8]}"
    try:
        os.rename(dest, gone)
    except OSError as e:
        raise ModuleError(_("it couldn't be removed ({error})", error=errors.plain(e))) from e
    shutil.rmtree(gone, ignore_errors=True)
    log.info("removed module %s from %s", module_id, dest)


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


def base_python() -> str | None:
    """A Python to build a module's own environment from. From source that's the one
    running the app; the packaged exe has none of its own, so look on PATH."""
    if not getattr(sys, "frozen", False):
        return sys.executable
    for name in ("py", "python"):
        found = shutil.which(name)
        if found and "WindowsApps" not in found:   # the Store stub only opens the Store
            return found
    return None


def _job_for(p: subprocess.Popen):
    """A job object holding `p` and whatever it starts (Windows), or None."""
    if os.name != "nt":
        return None
    from soundboard.tor import JobObject
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


def install(info: ModuleInfo, on_line: Callable[[str], None]) -> bool:
    """Run the module's "install" steps (module.json), streaming their output to
    `on_line`. Blocking: call from a worker thread. Returns True on success."""
    if not info.install_steps:
        on_line(_("This add-on has no install steps."))
        return False
    if not net.allowed("addons"):
        on_line(net.off_message("addons"))
        return False
    from soundboard import netlog
    netlog.cause("addons", f"You installed or updated the {netlog.quoted(info.name)} "
                           "add-on")
    py = base_python()
    if py is None:
        on_line(_("Python isn't installed. Get it from python.org (tick \"Add python.exe to "
                  "PATH\"), then press Install again."))
        return False
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
            return False
        # a step that hangs (a stuck download, a prompt nobody sees) is killed, with
        # everything it started: a grandchild still holding the output pipe would
        # keep the read below waiting for ever
        job = _job_for(p)
        timed_out = threading.Event()

        def watchdog(p=p, timed_out=timed_out, job=job):
            timed_out.set()
            _kill_tree(p, job)

        timer = threading.Timer(INSTALL_STEP_TIMEOUT_S, watchdog)
        timer.daemon = True
        timer.start()
        try:
            for line in p.stdout:
                if line.strip():
                    on_line(line.rstrip())
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
            log.warning("install of %s timed out at: %s", info.id, argv)
            return False
        if p.returncode != 0:
            on_line(_("failed (exit code {code})", code=p.returncode))
            log.warning("install of %s failed at: %s", info.id, argv)
            return False
    log.info("installed module %s", info.id)
    return True
