"""Shared parts of the pin bumpers in this folder (run weekly by
.github/workflows/pin-bumps.yml, one job per checker).

A checker finds the newest release of one pinned download, verifies it, smoke-tests
it (unpacks it and runs it with run(), on a Windows runner like the app's), rewrites
the pin with set_pins() and calls open_pr(). A failed smoke test opens no PR.
Everything here uses the standard library plus git and gh, so the checkers run on a
bare runner without the app's packages. Pins are
read and written as text (`NAME = "value"` at the start of a line), never imported.

Run a checker with --dry-run to see what it would change without writing or pushing."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TIMEOUT_S = 60
CHUNK = 1 << 20
SMOKE_TIMEOUT_S = 60       # per smoke-test step
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
    a workflow_dispatch run does, and its checks land on the PR's commit).

    With PINBUMP_OUT set (the workflow's check job, which runs the downloads and so has
    no token that can write), the edited files and the PR's text are left in that
    folder instead, for open_pr.py in a job that runs nothing downloaded."""
    if out := os.environ.get("PINBUMP_OUT"):
        bundle = Path(out) / name
        rel = [str(Path(f).resolve().relative_to(ROOT)).replace("\\", "/") for f in files]
        for r in rel:
            (bundle / "files" / r).parent.mkdir(parents=True, exist_ok=True)
            (bundle / "files" / r).write_bytes((ROOT / r).read_bytes())
        (bundle / "pr.json").write_text(json.dumps(
            {"name": name, "version": version, "files": rel, "title": title, "body": body}),
            encoding="utf-8")
        print(f"left for the PR job: {bundle}")
        return
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


def fetch_json(url: str, headers: dict[str, str] | None = None):
    req = urllib.request.Request(url, headers={"User-Agent": "OnionBoard pin bump",
                                               **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        return json.loads(r.read(10_000_000))


def github_release(repo: str, tag: str = "latest") -> dict:
    """A release's JSON from the GitHub API ("latest" skips drafts and pre-releases).
    Uses GH_TOKEN when it's set, for the higher rate limit."""
    path = "latest" if tag == "latest" else f"tags/{tag}"
    token = os.environ.get("GH_TOKEN")
    return fetch_json(f"https://api.github.com/repos/{repo}/releases/{path}",
                      {"Authorization": f"Bearer {token}"} if token else None)


def asset_sha256(release: dict, name: str) -> str:
    """The SHA-256 GitHub computed for one of a release's files ("sha256:<hex>")."""
    for a in release.get("assets", []):
        if a["name"] == name:
            digest = a.get("digest") or ""
            if not digest.startswith("sha256:"):
                sys.exit(f"{name} in {release['tag_name']} has no SHA-256 digest")
            return digest.removeprefix("sha256:")
    sys.exit(f"no {name} in release {release['tag_name']}")


def unpack(data: bytes, dest: Path) -> Path:
    """A verified .zip/.nupkg or .tar.gz into ``dest``, for a smoke test."""
    if data[:2] == b"PK":
        zipfile.ZipFile(io.BytesIO(data)).extractall(dest)
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            tar.extractall(dest, filter="data")
    return dest


def run(cmd: list, expect: str = "", timeout: float = SMOKE_TIMEOUT_S, **kw) -> str:
    """One smoke-test step: run ``cmd`` and return its output. Exits (so no PR opens)
    when it fails, times out or doesn't print ``expect``."""
    shown = " ".join(map(str, [Path(cmd[0]).name, *cmd[1:]]))
    start = time.monotonic()
    # what was just downloaded gets no token (nor Actions' own runtime ones)
    kw.setdefault("env", {k: v for k, v in os.environ.items()
                          if not k.endswith("_TOKEN") and not k.startswith("ACTIONS_")})
    try:
        p = subprocess.run(list(map(str, cmd)), capture_output=True, text=True,
                           errors="replace", timeout=timeout, **kw)
    except subprocess.TimeoutExpired:
        sys.exit(f"smoke FAILED: {shown} took over {timeout} s")
    except OSError as e:
        sys.exit(f"smoke FAILED: {shown}: {e}")
    out = p.stdout + p.stderr
    if p.returncode or expect not in out:
        missing = f", no {expect!r} in its output" if expect not in out else ""
        sys.exit(f"smoke FAILED: {shown} exited {p.returncode}{missing}:\n{out[-3000:]}")
    print(f"smoke ok ({time.monotonic() - start:.1f} s): {shown}")
    return out
