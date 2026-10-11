"""Type check with pyright, failing only on errors that aren't in the baseline.

The code had thousands of lines before it was type checked, so today's errors are
recorded in scripts/pyright_baseline.json and only new ones fail. An error is matched
by file, rule and message (not line), so an edit that moves code doesn't trip it.

    python scripts/check_types.py                # files changed since origin/main
    python scripts/check_types.py --base X       # ... since branch X
    python scripts/check_types.py FILE ...       # just these files
    python scripts/check_types.py --all          # whole repo (what CI runs)
    python scripts/check_types.py --update       # whole repo: rewrite the baseline

Fixed an old error? Run --update so the baseline shrinks and it can't come back.
"""

import argparse
import collections
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(ROOT, "scripts", "pyright_baseline.json")
CHECKED = ("soundboard/", "main.py")   # as [tool.pyright] include


def pyright(files):
    # --pythonpath: the Python running this script, so a git worktree without its own
    # .venv still finds PySide6 and the other packages
    out = subprocess.run([sys.executable, "-m", "pyright", "--outputjson",
                          "--pythonpath", sys.executable, *files], cwd=ROOT,
                         capture_output=True, text=True, encoding="utf-8")
    try:
        diags = json.loads(out.stdout)["generalDiagnostics"]
    except (ValueError, KeyError):
        sys.exit(f"pyright failed:\n{out.stdout}\n{out.stderr}")
    return [d for d in diags if d["severity"] == "error"]


def key(d):
    path = os.path.relpath(d["file"], ROOT).replace("\\", "/")
    return path, d.get("rule", ""), d["message"].splitlines()[0]


def changed(base):
    def git(*a):
        return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.split()
    names = set(git("diff", "--name-only", base))
    names |= set(git("ls-files", "--others", "--exclude-standard"))
    return sorted(n for n in names if n.endswith(".py") and n.startswith(CHECKED)
                  and os.path.exists(os.path.join(ROOT, n)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--update", action="store_true")
    a = ap.parse_args()

    if a.update:
        counts = collections.Counter(key(d) for d in pyright([]))
        rows = [{"file": f, "rule": r, "message": m, "count": n}
                for (f, r, m), n in sorted(counts.items())]
        with open(BASELINE, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(rows, fh, indent=0, ensure_ascii=False)
            fh.write("\n")
        print(f"baseline: {sum(counts.values())} errors in {len({k[0] for k in counts})} files")
        return 0

    files = [] if a.all else a.files or changed(a.base)
    if not files and not a.all:
        print("no changed Python files to type check")
        return 0
    with open(BASELINE, encoding="utf-8") as fh:
        known = {(r["file"], r["rule"], r["message"]): r["count"] for r in json.load(fh)}
    seen, new = collections.Counter(), []
    for d in pyright(files):   # no files: the whole repo
        k = key(d)
        seen[k] += 1
        if seen[k] > known.get(k, 0):
            new.append(d)
    for d in new:
        f, r, m = key(d)
        print(f"{f}:{d['range']['start']['line'] + 1}: {m} ({r})")
    if new:
        print(f"{len(new)} new type error(s). Fix them, or add `# pyright: ignore[rule]` "
              "with a reason if pyright is wrong.")
        return 1
    print("no new type errors in " + ("the repo" if a.all else f"{len(files)} file(s)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
