"""Optional add-on modules, dropped into a `modules` folder as their own subfolders.

    <module folder>/
        module.json      {"id", "name", "version", "description", "kind", ...}
        ...

Three kinds:

  "effects"  An `entry` Python file loaded into the app. Its `register(api)` adds
             voice effects with `api.register_effect(EffectSubclass)`. It may only
             import what the app itself ships (numpy, scipy, soxr, the stdlib…),
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
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from soundboard import voicefx
from soundboard import library

log = logging.getLogger(__name__)

KINDS = ("effects", "service", "translation", "triggers")
INSTALL_STEP_TIMEOUT_S = 30 * 60     # one install step (pip) before it's given up on
TRIGGERS_API = (1, 1)   # the oldest and newest "triggers" api_version this app can host
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
                          kind="?", path=folder, error=f"bad module.json: {e}")
    if info.kind not in KINDS:
        info.error = f"unknown kind {info.kind!r}"
    elif info.kind == "effects" and not (folder / info.entry).is_file():
        info.error = f"entry file {info.entry!r} not found"
    elif info.kind == "service" and not info.command:
        info.error = "no command"
    elif info.kind == "translation" and not (
            re.fullmatch(r"[a-z]{2,3}", info.language)
            and str(info.download.get("url", "")).startswith("https://")
            and re.fullmatch(r"[0-9a-f]{64}", str(info.download.get("sha256", "")))):
        info.error = "needs a language code and an https download with its sha256"
    elif info.kind == "triggers":
        info.error = _triggers_error(info)
    return info


def _triggers_error(info: ModuleInfo) -> str:
    """Why a "triggers" module can't be loaded ("" if it can be tried)."""
    pkg, entry = info.package, info.entry
    if not (_NAME.fullmatch(pkg) and (info.path / pkg / "__init__.py").is_file()):
        return f"package {pkg!r} not found"
    if not (entry == pkg or entry.startswith(pkg + ".")) or not all(
            _NAME.fullmatch(p) for p in entry.split(".")):
        return f"entry {entry!r} isn't a module of {pkg!r}"
    low, high = TRIGGERS_API
    if info.api_version > high:
        return "it needs a newer Onion Board: update Onion Board first"
    if info.api_version < low:
        return "it's too old for this Onion Board: get its update"
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
            info.error = f"failed to load: {e}"
            log.exception("module %s failed to load", info.id)


def _importable(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _forget(package: str):
    for name in [n for n in sys.modules if n == package or n.startswith(package + ".")]:
        del sys.modules[name]


def load_package(info: ModuleInfo):
    """Load a "triggers" module's package from its folder and return its `entry`
    module (which has create(host)). Loaded once per run: a copy already loaded
    from the same folder, at the same version, is reused; a different one needs a
    restart (Python can't swap a package it's running). Raises ModuleError."""
    if info.kind != "triggers":
        raise ModuleError(f"{info.name} isn't a Triggers add-on")
    if info.error:
        raise ModuleError(info.error)
    missing = [m for m in info.imports if not _importable(m)]
    if missing:
        raise ModuleError(f"it needs {', '.join(missing)}, which this Onion Board doesn't have: "
                          "update Onion Board")
    pkg_dir = info.path / info.package
    have = sys.modules.get(info.package)
    if have is not None:
        where = Path(getattr(have, "__file__", "") or ".").resolve().parent
        if where != pkg_dir.resolve() or getattr(have, "__version__", None) != info.version:
            raise ModuleError(f"restart Onion Board to use {info.name} {info.version}")
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
            raise ModuleError(f"failed to load: {e}") from e
    try:
        entry = importlib.import_module(info.entry)
    except Exception as e:  # noqa: BLE001
        _forget(info.package)
        log.exception("module %s failed to load", info.id)
        raise ModuleError(f"failed to load: {e}") from e
    if not callable(getattr(entry, "create", None)):
        raise ModuleError(f"{info.entry} has no create()")
    info.loaded = True
    log.info("loaded module %s %s from %s", info.id, info.version, info.path)
    return entry


def _check_zip(z: zipfile.ZipFile, module_id: str) -> None:
    """Refuse a zip that would write anywhere but one `module_id` folder, holds
    links, or is far too big once unpacked."""
    items = z.infolist()
    if not items or len(items) > MAX_ZIP_FILES:
        raise ModuleError("it isn't an add-on (empty, or far too many files)")
    total = 0
    for i in items:
        n = i.filename
        parts = PurePosixPath(n).parts
        if (not parts or parts[0] != module_id or n.startswith("/") or "\\" in n or ":" in n
                or ".." in parts):
            raise ModuleError(f"it holds a file outside its own folder ({n})")
        if stat.S_ISLNK(i.external_attr >> 16):
            raise ModuleError(f"it holds a link ({n})")
        total += i.file_size
    if total > MAX_ZIP_UNPACKED:
        raise ModuleError("it would unpack to far more than an add-on")


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
        raise ModuleError(f"it isn't a zip file that can be opened ({e})") from e
    staging = base.parent / f"modules-new-{uuid.uuid4().hex[:8]}"
    try:
        with z:
            _check_zip(z, module_id)
            try:
                d = json.loads(z.read(f"{module_id}/module.json").decode("utf-8-sig"))
            except KeyError as e:
                raise ModuleError("it has no module.json") from e
            except ValueError as e:
                raise ModuleError(f"its module.json can't be read ({e})") from e
            if not isinstance(d, dict) or d.get("id") != module_id or d.get("kind") != kind:
                raise ModuleError(f"it isn't the {module_id} add-on")
            staging.mkdir(parents=True)
            z.extractall(staging)
        info = _read(staging / module_id)
        if info is None or info.error:
            raise ModuleError(info.error if info is not None else "it has no module.json")
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
        raise ModuleError(f"it couldn't be installed ({e})") from e
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
        raise ModuleError(f"it couldn't be removed ({e})") from e
    shutil.rmtree(gone, ignore_errors=True)
    log.info("removed module %s from %s", module_id, dest)


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


def install(info: ModuleInfo, on_line: Callable[[str], None]) -> bool:
    """Run the module's "install" steps (module.json), streaming their output to
    `on_line`. Blocking: call from a worker thread. Returns True on success."""
    if not info.install_steps:
        on_line("This add-on has no install steps.")
        return False
    py = base_python()
    if py is None:
        on_line("Python isn't installed. Get it from python.org (tick \"Add python.exe to "
                "PATH\"), then press Install again.")
        return False
    for step in info.install_steps:
        argv = [info._fill(a, py) for a in step]
        on_line("> " + " ".join(argv[1:]))
        try:
            p = subprocess.Popen(argv, cwd=info.path, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                 text=True, encoding="utf-8", errors="replace",
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            on_line(f"couldn't run it: {e}")
            return False
        # a step that hangs (a stuck download, a prompt nobody sees) is killed
        timed_out = threading.Event()

        def watchdog(p=p, timed_out=timed_out):
            timed_out.set()
            p.kill()

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
                p.kill()
                p.wait()
        if timed_out.is_set():
            on_line(f"stopped: it took over {INSTALL_STEP_TIMEOUT_S // 60:.0f} minutes. Check "
                    "your internet connection and press it again.")
            log.warning("install of %s timed out at: %s", info.id, argv)
            return False
        if p.returncode != 0:
            on_line(f"failed (exit code {p.returncode})")
            log.warning("install of %s failed at: %s", info.id, argv)
            return False
    log.info("installed module %s", info.id)
    return True
