"""Optional add-on modules, dropped into a `modules` folder as their own subfolders.

    <module folder>/
        module.json      {"id", "name", "version", "description", "kind", ...}
        ...

Two kinds:

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

Modules are searched for in %APPDATA%\\Soundboard\\modules (where users drop
downloads) and in the `modules` folder next to the app (or the repo root when
running from source).
"""
from __future__ import annotations

import importlib.util
import json
import logging
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from soundboard import voicefx
from soundboard import library

log = logging.getLogger(__name__)

KINDS = ("effects", "service")


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
        """For a service: are its dependencies set up (its own venv exists)?"""
        if self.kind != "service" or not any("{python}" in a for a in self.command):
            return True
        return (self.path / ".venv" / "Scripts" / "python.exe").exists()


def _read(folder: Path) -> ModuleInfo | None:
    mf = folder / "module.json"
    if not mf.is_file():
        return None
    try:
        d = json.loads(mf.read_text(encoding="utf-8"))
        info = ModuleInfo(id=str(d["id"]), name=str(d.get("name", d["id"])),
                          version=str(d.get("version", "0")),
                          description=str(d.get("description", "")),
                          kind=str(d.get("kind", "")), path=folder,
                          entry=str(d.get("entry", "")),
                          command=[str(a) for a in d.get("command", [])],
                          provides=[str(a) for a in d.get("provides", [])],
                          install_steps=[[str(a) for a in step]
                                         for step in d.get("install", [])])
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
    return info


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
        for line in p.stdout:
            if line.strip():
                on_line(line.rstrip())
        if p.wait() != 0:
            on_line(f"failed (exit code {p.returncode})")
            log.warning("install of %s failed at: %s", info.id, argv)
            return False
    log.info("installed module %s", info.id)
    return True
