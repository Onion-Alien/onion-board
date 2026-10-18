"""Every module of the app imports, and every module path written as text names one.

A safety net for moving files between folders: an import a move broke (one inside a
function too, which only runs when that feature is used) fails here, not on a user's
PC. Module paths in strings (`monkeypatch.setattr("soundboard.x.y", ...)`,
`sys.modules["soundboard.x"]`, `python -m soundboard.x`) aren't imports, so the second
test checks those by name."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "soundboard"

# run in a fresh Python: importing everything at once mustn't depend on what other
# tests have loaded or faked, and must leave this test process as it was
IMPORT_ALL = r"""
import importlib, pkgutil, sys, traceback
import soundboard
bad = []
for m in pkgutil.walk_packages(soundboard.__path__, "soundboard."):
    if m.name.endswith(".__main__"):   # importing it starts the app
        continue
    try:
        importlib.import_module(m.name)
    except BaseException:
        bad.append(m.name + "\n" + traceback.format_exc(limit=-3))
print("\n\n".join(bad))
sys.exit(1 if bad else 0)
"""


def modules() -> set[str]:
    """Every importable module and package name under soundboard/."""
    out = set()
    for p in SRC.rglob("*.py"):
        parts = p.relative_to(ROOT).with_suffix("").parts
        if "__pycache__" in parts:
            continue
        out.add(".".join(parts[:-1] if parts[-1] == "__init__" else parts))
    return out


def test_every_module_imports(tmp_path):
    # a made-up profile: an import that reads settings or add-ons never sees the real one
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", ONIONBOARD_NO_STATS="1",
               APPDATA=str(tmp_path), LOCALAPPDATA=str(tmp_path), PYTHONPATH=str(ROOT))
    r = subprocess.run([sys.executable, "-c", IMPORT_ALL], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"these modules don't import:\n{r.stdout}\n{r.stderr[-2000:]}"


# a module path in quotes, as code and tests write it
QUOTED = re.compile(r"""["'](soundboard(?:\.[a-z_][a-z0-9_]*)+)["']""")
# names that aren't module paths: logger names, and the made-up modules tests fake
NOT_PATHS = re.compile(r"getLogger\(|types\.ModuleType\(|Half\(")
MADE_UP = {"soundboard.needsnumpy", "soundboard.ui.window"}


def test_module_paths_in_strings_exist():
    known = modules()
    files = [*SRC.rglob("*.py"), *(ROOT / "tests").rglob("*.py"),
             *(ROOT / "scripts").rglob("*.py"), ROOT / "main.py",
             ROOT / "build.ps1", *ROOT.glob("*.spec")]
    stale = []
    for f in files:
        if "__pycache__" in f.parts or not f.is_file() or f == Path(__file__):
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8", errors="replace")
                                 .splitlines(), 1):
            if NOT_PATHS.search(line):
                continue
            for name in QUOTED.findall(line):
                # "soundboard.x.attr" for monkeypatch: the module is a prefix of it
                if name in MADE_UP or any(name == k or name.startswith(k + ".")
                                          and name.count(".") == k.count(".") + 1
                                          for k in known):
                    continue
                stale.append(f"{f.relative_to(ROOT)}:{n}: {name}")
    assert not stale, "module paths that name no module:\n" + "\n".join(stale)
