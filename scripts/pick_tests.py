"""Which test files a branch's changes need (CI runs only those on a pull request).

A test file runs when:
- it changed, or a test file it imports (the `window` fixture in test_mainwindow…)
- it imports a changed module (soundboard/, perf/, scripts/, main.py), straight or
  through a test file it imports. A module no test imports picks the tests of the
  nearest modules that import it.
- it names a changed file that isn't one of those (`build.ps1`, `DESIGN.md`,
  `module.json`, "lang" for assets/lang/…)

A change to what every test runs on (conftest.py, pyproject.toml, the requirements,
the workflow, this script) runs them all. A change no test is about (the README, the
changelog, the website) runs none. main runs the whole suite after every merge, and
so does a manual run of the workflow.

Usage: python scripts/pick_tests.py [BASE]   (BASE defaults to origin/main)
Prints the test files, one per line: `tests` alone for all of them, nothing for none.
Locally: python -m pytest $(python scripts/pick_tests.py)
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
# Python whose imports are followed; scripts/ is on sys.path in the tests that use it
CODE_DIRS = ("soundboard", "perf", "scripts", "tests")
RUN_ALL = {
    "tests/conftest.py", "pyproject.toml", "requirements.txt", "requirements-dev.txt",
    ".github/workflows/checks.yml", "scripts/pick_tests.py",
}
# too common to say which test is about it
VAGUE_NAMES = {"__init__.py", "README.md", "LICENSE", ".gitignore", "requirements.txt"}


def module_name(rel: str) -> str:
    """soundboard/ui/panel.py → soundboard.ui.panel; tests/ and scripts/ files go by
    their bare name, as the tests import them."""
    parts = list(Path(rel).with_suffix("").parts)
    if parts[0] in ("tests", "scripts"):
        parts = parts[1:]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def imported_names(path: Path) -> set[str]:
    """Every module name the file imports anywhere (inside functions too), with each
    package above it: `from soundboard.ui import panel` gives soundboard,
    soundboard.ui and soundboard.ui.panel."""
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    own = module_name(path.relative_to(ROOT).as_posix()).split(".")
    if path.name != "__init__.py":
        own = own[:-1]   # the package a relative import starts from
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                pkg = own[:len(own) - (node.level - 1)]
                base = ".".join(pkg + ([base] if base else []))
            names.add(base)
            names.update(f"{base}.{a.name}" for a in node.names)
    out = set()
    for name in names:
        while name:
            out.add(name)
            name = name.rpartition(".")[0]
    return out


def code_files() -> dict[str, Path]:
    files = {"main": ROOT / "main.py"}
    for d in CODE_DIRS:
        for p in (ROOT / d).rglob("*.py"):
            if "__pycache__" not in p.parts:
                files[module_name(p.relative_to(ROOT).as_posix())] = p
    return files


def changed_files(base: str) -> list[str]:
    out = subprocess.run(["git", "diff", "--name-only", "--no-renames", f"{base}...HEAD"],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line]


def pick(changed: list[str]) -> list[str]:
    if any(f in RUN_ALL for f in changed):
        return ["tests"]
    files = code_files()
    imports = {m: imported_names(p) for m, p in files.items()}
    tests = {m: p for m, p in files.items()
             if p.parent == TESTS and p.name.startswith("test_")}
    # a test file "uses" what it imports and what the test files it imports do
    uses = {}
    for t in tests:
        u = set(imports[t])
        for m in imports[t]:
            if m in files and files[m].parent == TESTS:
                u |= imports[m]
        uses[t] = u
    # test_pick_tests names files of every kind as examples: it's about this script
    texts = {t: p.read_text(encoding="utf-8") for t, p in tests.items()
             if t != "test_pick_tests"}

    def users(mod: str) -> set[str]:
        return {t for t in tests if t == mod or mod in uses[t]}

    picked: set[str] = set()
    for rel in changed:
        top = rel.split("/")[0]
        if rel.endswith(".py") and (top in CODE_DIRS or rel == "main.py"):
            mod = module_name(rel)
            found = users(mod)
            # nothing imports it straight: the tests of the nearest modules that do
            seen, level = {mod}, {mod}
            while not found and level:
                level = {m for m in files if m not in seen and level & imports[m]}
                seen |= level
                found = set().union(*(users(m) for m in level)) if level else set()
            picked |= found
        if top not in ("soundboard", "tests"):
            # a file the tests read or check: by its name, its folder's, or its path
            p = Path(rel)
            words = [] if p.name in VAGUE_NAMES else [p.name]
            if len(p.parts) > 1:
                words += [f'"{p.parent.name}"', p.parent.as_posix()]
            picked |= {t for t, text in texts.items() if any(w in text for w in words)}
    return sorted(tests[t].relative_to(ROOT).as_posix() for t in picked)


def main(argv: list[str]) -> int:
    base = argv[1] if len(argv) > 1 else "origin/main"
    for line in pick(changed_files(base)):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
