"""Shared parts of the pin bumpers in this folder (run weekly by
.github/workflows/pin-bumps.yml, one job per checker).

A checker finds the newest release of one pinned download, verifies it, rewrites the
pin with set_pins() and calls open_pr(). Everything here uses the standard library plus
git and gh, so the checkers run on a bare runner without the app's packages. Pins are
read and written as text (`NAME = "value"` at the start of a line), never imported.

Run a checker with --dry-run to see what it would change without writing or pushing."""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TIMEOUT_S = 60
CHUNK = 1 << 20
MAX_BYTES = 300_000_000


def args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="check and verify, but don't edit files, push or open a PR")
    return ap.parse_args()


def fetch(url: str, max_bytes: int = MAX_BYTES) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "OnionBoard pin bump"})
    out = bytearray()
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        while chunk := r.read(CHUNK):
            out += chunk
            if len(out) > max_bytes:
                sys.exit(f"{url} is over {max_bytes} bytes")
    return bytes(out)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def version_key(v: str) -> tuple[int, ...]:
    """"15.0.25" -> (15, 0, 25), for picking the newest."""
    return tuple(int(p) for p in v.split("."))


def get_pin(path: Path, name: str) -> str:
    m = re.search(rf'^{name} = "([^"]*)"', path.read_text(encoding="utf-8"), re.M)
    if not m:
        sys.exit(f"no {name} = \"...\" line in {path}")
    return m.group(1)


def set_pins(path: Path, pins: dict[str, str]) -> None:
    """Rewrite each `NAME = "..."` line, keeping the file's line endings."""
    text = path.read_bytes().decode("utf-8")
    for name, value in pins.items():
        text, n = re.subn(rf'^{name} = "[^"]*"', f'{name} = "{value}"', text, flags=re.M)
        if n != 1:
            sys.exit(f"expected one {name} line in {path}, found {n}")
    path.write_bytes(text.encode("utf-8"))


def git(*a: str, check: bool = True) -> str:
    return subprocess.run(["git", *a], cwd=ROOT, check=check, text=True,
                          stdout=subprocess.PIPE).stdout.strip()


def gh(*a: str) -> str:
    return subprocess.run(["gh", *a], cwd=ROOT, check=True, text=True,
                          stdout=subprocess.PIPE).stdout.strip()


def branch_for(name: str, version: str) -> str:
    return f"pin-bump/{name}-{version}"


def already_open(name: str, version: str) -> bool:
    """A bump for this version is waiting: its branch exists (open PR, or a run whose PR
    step failed). Deleting the branch lets the next run try again."""
    return bool(git("ls-remote", "--heads", "origin", branch_for(name, version)))


def open_pr(name: str, version: str, files: list[Path], title: str, body: str) -> None:
    """Commit the edited files on pin-bump/<name>-<version>, push it, open its PR and
    start the checks on it (a PR opened with GITHUB_TOKEN starts no workflows itself;
    a workflow_dispatch run does, and its checks land on the PR's commit)."""
    branch = branch_for(name, version)
    git("switch", "-c", branch)
    git("add", "--", *map(str, files))
    git("-c", "user.name=github-actions[bot]",
        "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
        "commit", "-m", title, "--", *map(str, files))
    git("push", "origin", branch)
    try:
        url = gh("pr", "create", "--head", branch, "--title", title, "--body", body)
    except subprocess.CalledProcessError:
        # GITHUB_TOKEN may only open PRs when Settings > Actions > General allows it
        repo = gh("repo", "view", "--json", "url", "-q", ".url")
        sys.exit(f"::error::pushed {branch} but couldn't open its PR (does Settings > "
                 f"Actions > General let Actions create pull requests?): "
                 f"{repo}/compare/{branch}?expand=1")
    print(url)
    gh("workflow", "run", "checks.yml", "--ref", branch)
