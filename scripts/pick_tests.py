"""Which test files a branch's changes need (CI runs only those on a pull request).

A test file runs when:
- it changed, or a test file it imports (the `window` fixture in test_mainwindow…)
- it imports a changed module (soundboard/, perf/, scripts/, main.py), straight,
  through a test file it imports, or through a package that imports its own modules
  (`from soundboard import voicefx` gets `voicefx.builtin`'s presets). A module no
  test imports picks the tests of the nearest modules that import it.
- it names a changed file that isn't one of those (`build.ps1`, `DESIGN.md`,
  `module.json`, "lang" for assets/lang/…)

A change to what every test runs on (conftest.py, pyproject.toml, the requirements,
the workflow, this script) runs them all, and so does one to a hub (HUBS: the main
window, the engine, the library, the settings): so much reaches those through signals
and lazy imports no import line names that the picked tests can miss a break. A
change no test is about (the README, the changelog, the website) runs none. main runs
the whole suite after every merge and every night, and so does a manual run of the
workflow.

Usage: python scripts/pick_tests.py [BASE] [--local] [--matrix] [--shards=N]
(BASE: origin/main)
Prints the test files, one per line: `tests` alone for all of them, nothing for none.
--local also counts uncommitted and new files. Locally, scripts/precommit.ps1 runs
ruff and the other quick checks; with -Tests these tests too.

--matrix prints CI's test jobs as JSON instead (BASE "all": the whole suite): the
picked files split into jobs of about the same length by test_times.json (each
file's seconds in a full run): one per JOB_S of tests, SHARDS at most (--shards=N: N),
or none. main's run after a merge takes fewer: nobody waits on it, and every job it
holds is a Windows machine a pull request's run queues for.

--refresh-times DIR [DIR...] rewrites test_times.json from the JUnit reports in each DIR
(every test job keeps one: `gh run download <run> -p "times-*" -D DIR`, one DIR a run of
the whole suite). With a few runs each file gets its average: one file took 418 s in one
run and 164 s in the next, so one run's times split the jobs unevenly.
"""
from __future__ import annotations

import ast
import json
import math
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
# what most of the app reaches through signals, callbacks and lazy imports: a change
# to one runs the whole suite rather than trust the imports to find every test
HUBS = {
    "soundboard/ui/mainwindow.py", "soundboard/audio/engine.py", "soundboard/sounds/library.py",
    "soundboard/settings.py",
}
# too common to say which test is about it
VAGUE_NAMES = {"__init__.py", "README.md", "LICENSE", ".gitignore", "requirements.txt"}


def module_name(rel: str) -> str:
    """soundboard/ui/panel.py → soundboard.ui.panel; tests/ and scripts/ files go by
    their bare name, as the tests import them (scripts/voicetests/game_roundtrip.py →
    game_roundtrip: its folder is put on sys.path)."""
    parts = list(Path(rel).with_suffix("").parts)
    if parts[0] == "tests":
        parts = parts[1:]
    elif parts[0] == "scripts":
        parts = parts[-1:]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def imported_names(path: Path) -> set[str]:
    """Every module name the file imports anywhere (inside functions too, and by a
    plain string to importlib.import_module or __import__), with each package above
    it: `from soundboard.ui import panel` gives soundboard, soundboard.ui and
    soundboard.ui.panel."""
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
        elif (isinstance(node, ast.Call) and node.args
              and isinstance(node.args[0], ast.Constant)
              and isinstance(node.args[0].value, str)
              and not node.args[0].value.startswith(".")
              and (isinstance(node.func, ast.Name) and node.func.id == "__import__"
                   or isinstance(node.func, ast.Attribute)
                   and node.func.attr == "import_module")):
            names.add(node.args[0].value)
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


def _git(*args: str) -> list[str]:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                         check=True).stdout
    return [line for line in out.splitlines() if line]


def changed_files(base: str, local: bool = False) -> list[str]:
    """What the branch changed since it left `base`. `local` adds what isn't committed
    yet (edited, staged and new files), for running the right tests before a commit."""
    if not local:
        return _git("diff", "--name-only", "--no-renames", f"{base}...HEAD")
    since = _git("merge-base", base, "HEAD")[0]
    files = _git("diff", "--name-only", "--no-renames", since)   # to the working tree
    files += _git("ls-files", "--others", "--exclude-standard")
    return sorted(set(files))


def pick(changed: list[str]) -> list[str]:
    if any(f in RUN_ALL or f in HUBS for f in changed):
        return ["tests"]
    files = code_files()
    imports = {m: imported_names(p) for m, p in files.items()}
    tests = {m: p for m, p in files.items()
             if p.parent == TESTS and p.name.startswith("test_")}
    # a package that imports its own modules hands them on: a test of the package
    # tests them too (voicefx/__init__.py re-exports voicefx.builtin's PRESETS)
    hands_on = {m: {n for n in imports[m] if n.startswith(m + ".") and n in files}
                for m, p in files.items() if p.name == "__init__.py"}

    def with_parts(names: set[str]) -> set[str]:
        todo = [n for n in names if n in hands_on]
        while todo:
            for n in hands_on[todo.pop()] - names:
                names.add(n)
                todo += [n] if n in hands_on else []
        return names

    # a test file "uses" what it imports and what the test files it imports do; not
    # conftest's: a test taking process_events from it doesn't use the dozens of
    # modules its fixtures patch (a conftest change runs everything anyway)
    uses = {}
    for t in tests:
        u = set(imports[t])
        for m in imports[t]:
            if m in files and files[m].parent == TESTS and m != "conftest":
                u |= imports[m]
        uses[t] = with_parts(u)
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


TIMES = Path(__file__).with_name("test_times.json")
SHARDS = 6             # the most jobs a run is split into (on Windows and on Linux):
                       # the whole suite, ~5600 s over 4 workers, ~4 min each
JOB_S = 600            # seconds of tests (summed over workers) worth another job, about
                       # 2.5 min on its 4 workers: each job spends ~35 s starting
                       # (checkout, venv cache, Python), so a small run gets few


def all_tests() -> list[str]:
    return sorted(p.relative_to(ROOT).as_posix() for p in TESTS.glob("test_*.py"))


def shards(files: list[str], most: int = SHARDS) -> list[list[str]]:
    """`files` in jobs of about the same length (longest first, each into the job with
    the least so far): one job per JOB_S of tests, `most` at most. A file not timed yet
    counts as an average one."""
    times = json.loads(TIMES.read_text(encoding="utf-8"))
    avg = sum(times.values()) / max(len(times), 1)
    cost = {f: max(times.get(f, avg), 0.5) for f in files}
    if not files:
        return []
    n = max(1, min(most, math.ceil(sum(cost.values()) / JOB_S)))
    jobs: list[tuple[float, list[str]]] = [(0.0, []) for _ in range(n)]
    for f in sorted(files, key=lambda f: -cost[f]):
        i = min(range(n), key=lambda i: jobs[i][0])
        jobs[i] = (jobs[i][0] + cost[f], jobs[i][1] + [f])
    return [sorted(fs) for _t, fs in jobs if fs]


def matrix(picked: list[str], most: int = SHARDS) -> list[dict]:
    files = all_tests() if picked == ["tests"] else picked
    jobs = shards(files, most)
    return [{"shard": f"{i}/{len(jobs)}", "tests": " ".join(fs)}
            for i, fs in enumerate(jobs, 1)]


def refresh_times(reports: list[Path]) -> dict[str, float]:
    """Each test file's seconds (setup + call + teardown, all its tests) from the
    JUnit reports of a full run (pytest --junitxml, one per test job)."""
    import xml.etree.ElementTree as ET
    out: dict[str, float] = {}
    for report in reports:
        for case in ET.parse(report).iter("testcase"):
            # classname "tests.test_x" or "tests.test_x.TestClass"
            parts = case.get("classname", "").split(".")
            if len(parts) < 2 or not parts[1].startswith("test_"):
                continue
            f = f"{parts[0]}/{parts[1]}.py"
            out[f] = out.get(f, 0.0) + float(case.get("time") or 0)
    return {f: round(t, 1) for f, t in sorted(out.items())}


def main(argv: list[str]) -> int:
    most = SHARDS
    for a in argv[1:]:
        if a.startswith("--shards="):
            most = max(1, int(a.split("=", 1)[1]))
    flags = {a.split("=", 1)[0] for a in argv[1:] if a.startswith("--")}
    args = [a for a in argv[1:] if not a.startswith("--")]
    if "--refresh-times" in flags:
        runs = [refresh_times(r) for a in args if (r := sorted(Path(a).rglob("*.xml")))]
        if not runs:
            print("usage: pick_tests.py --refresh-times DIR [DIR...] (DIR: a run's JUnit "
                  "reports)")
            return 2
        files = sorted(set().union(*runs))
        times = {f: round(sum(run[f] for run in runs if f in run)
                          / sum(f in run for run in runs), 1) for f in files}
        TIMES.write_text(json.dumps(times, indent=0) + "\n", encoding="utf-8")
        print(f"{len(times)} files, {sum(times.values()):.0f} s in all, the average of "
              f"{len(runs)} run(s)")
        return 0
    base = args[0] if args else "origin/main"
    picked = ["tests"] if base == "all" else pick(changed_files(base, "--local" in flags))
    if "--matrix" in flags:
        print(json.dumps(matrix(picked, most)))
        return 0
    for line in picked:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
