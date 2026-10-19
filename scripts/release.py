"""Cut a release's version bump in one step, instead of editing three files by hand.

    .venv\\Scripts\\python scripts\\release.py 1.9.28          # bump, date the changelog
    .venv\\Scripts\\python scripts\\release.py 1.9.28 --dry-run

Changes not released yet are one file each in changelog.d/ (so two pull requests
never edit the same lines of CHANGELOG.md and conflict). It:
1. checks the new version is newer than soundboard/__init__.py's;
2. checks changelog.d/ has entries, writes them into CHANGELOG.md under
   "## <version> <long dash> <today, UTC>" (newest first) and deletes the files;
3. sets __version__ in soundboard/__init__.py, and the Stream Deck plugin's manifest
   Version to the same (X.Y.Z.0: build.ps1 packs it for the release);
4. runs `scripts/checks/i18n_extract.py --check` (missing translations fail it) and
   `scripts/docs.py --no-shots` (the README and website release line).

Before any of that it refuses unless the checkout is origin/main exactly and main's
full "checks" run (CI on a PR only runs the tests its change imports; main runs them
all after the merge) passed on that commit. `--skip-ci-check` skips the CI half, with
a loud warning: only for an urgent fix when CI itself is broken.

It never builds, tags, pushes or commits. After it: build, scan the installer on
VirusTotal, then `scripts/docs.py --vt <sha256> N/N`. Scan the mic helper too
(build\\michelper\\obmichelper\\obmichelper.exe): it is unsigned and runs as SYSTEM, and
a scan of the installer doesn't always look inside it. A "What's new" note
(soundboard/ui/setup/whatsnew.py) is only for releases with something worth telling, and
its text is translated like any other, so it stays a hand-written step.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT = ROOT / "soundboard" / "__init__.py"
CHANGELOG = ROOT / "CHANGELOG.md"
FRAGMENTS = ROOT / "changelog.d"
MANIFEST = ROOT / "streamdeck" / "com.onionalien.onionboard.sdPlugin" / "manifest.json"
FRAGMENT_README = "README.md"   # keeps the folder in git; not an entry
DASH = "\u2014"   # the changelog's headings are "## 1.9.27 <long dash> 2026-10-09"
VERSION_RE = re.compile(r'__version__ = "([^"]+)"')


def parse(v: str) -> tuple[int, ...]:
    if not re.fullmatch(r"\d+(\.\d+){1,3}", v):
        raise SystemExit(f"not a version: {v!r} (want e.g. 1.9.28)")
    return tuple(int(p) for p in v.split("."))


def current_version(text: str) -> str:
    return VERSION_RE.search(text).group(1)


def bump_init(text: str, new: str) -> str:
    return VERSION_RE.sub(f'__version__ = "{new}"', text, count=1)


MANIFEST_VERSION_RE = re.compile(r'^(  "Version": ")[^"]+(")', flags=re.M)


def bump_manifest(text: str, new: str) -> str:
    """The plugin's top-level Version (Stream Deck wants four numbers)."""
    out, n = MANIFEST_VERSION_RE.subn(rf"\g<1>{new}.0\g<2>", text, count=1)
    if not n:
        raise SystemExit(f"no top-level \"Version\" in {MANIFEST.name}")
    return out


def fragment_files(folder: Path | None = None) -> list[Path]:
    """changelog.d/*.md, newest first: by the time git added each one (not committed
    yet counts as newest), then by name."""
    folder = folder or FRAGMENTS
    files = [p for p in folder.glob("*.md") if p.name != FRAGMENT_README]

    def added(p: Path) -> int:
        try:
            out = subprocess.run(
                ["git", "log", "--diff-filter=A", "--format=%ct", "-1", "--", p.name],
                cwd=folder, capture_output=True, text=True, timeout=20).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            out = ""
        return int(out) if out.isdigit() else 1 << 62

    return sorted(sorted(files, key=lambda p: p.name), key=added, reverse=True)


def read_fragment(p: Path) -> str:
    return p.read_text(encoding="utf-8").strip()


def date_changelog(text: str, new: str, today: str, entries: list[str]) -> str:
    """Put the entries under a new "## <version>" heading above the newest release."""
    entries = [e for e in entries if e]
    if not entries:
        raise SystemExit("changelog.d/ has no entries: nothing to release")
    if re.search(r"^## Unreleased\b", text, flags=re.M):
        raise SystemExit("CHANGELOG.md has an '## Unreleased' section: move its lines "
                         "into a file in changelog.d/")
    if re.search(rf"^## {re.escape(new)}\b", text, flags=re.M):
        raise SystemExit(f"CHANGELOG.md already has a {new} section")
    section = f"## {new} {DASH} {today}\n\n" + "\n".join(entries) + "\n\n"
    m = re.search(r"^## ", text, flags=re.M)
    at = m.start() if m else len(text)
    return text[:at] + section + text[at:]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                          timeout=60).stdout.strip()


def head_is_origin_main() -> str:
    """HEAD's sha, after checking it is origin/main's (fetched just now)."""
    try:
        git("fetch", "-q", "origin", "main")
    except subprocess.SubprocessError:
        print("warning: couldn't fetch origin; comparing with the last fetched main")
    head, main = git("rev-parse", "HEAD"), git("rev-parse", "origin/main")
    if not head or head != main:
        raise SystemExit(f"HEAD ({head[:8] or '?'}) isn't origin/main ({main[:8] or '?'}): "
                         "release from an up-to-date main checkout")
    return head


def ci_verdict(runs: list[dict]) -> str | None:
    """None when a 'checks' run on main passed for the commit, else why not.
    `runs` is `gh run list --json conclusion,status` for that commit."""
    if any(r.get("conclusion") == "success" for r in runs):
        return None
    if not runs:
        return "no 'checks' run on main for this commit yet"
    if any(r.get("status") != "completed" for r in runs):
        return "main's 'checks' run for this commit is still going: wait for it"
    got = ", ".join(sorted({r.get("conclusion") or "?" for r in runs}))
    return f"main's 'checks' run for this commit didn't pass ({got}): fix main first"


def ci_runs(sha: str) -> list[dict]:
    try:
        out = subprocess.run(
            ["gh", "run", "list", "--workflow", "checks.yml", "--branch", "main",
             "--commit", sha, "--json", "conclusion,status"],
            cwd=ROOT, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        raise SystemExit(f"couldn't ask GitHub about CI ({e}): is gh installed?") from None
    if out.returncode:
        raise SystemExit(f"gh run list failed: {out.stderr.strip()}")
    return json.loads(out.stdout or "[]")


def check_ci(sha: str, skip: bool) -> None:
    if skip:
        bar = "!" * 70
        print(f"{bar}\nWARNING: --skip-ci-check: releasing WITHOUT main's full test run "
              f"passing on {sha[:8]}.\nEveryone who clicks Update now gets this "
              f"build.\n{bar}")
        return
    why = ci_verdict(ci_runs(sha))
    if why:
        raise SystemExit(f"{why} (--skip-ci-check overrides, for an urgent fix only)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("version")
    ap.add_argument("--dry-run", action="store_true", help="check only, change nothing")
    ap.add_argument("--skip-ci-check", action="store_true",
                    help="release even if main's CI didn't pass (loud warning)")
    args = ap.parse_args(argv)
    check_ci(head_is_origin_main(), args.skip_ci_check)

    init, log = INIT.read_text(encoding="utf-8"), CHANGELOG.read_text(encoding="utf-8")
    old = current_version(init)
    if parse(args.version) <= parse(old):
        raise SystemExit(f"{args.version} isn't newer than the current {old}")
    today = datetime.datetime.now(datetime.UTC).date().isoformat()   # UTC, like commits
    frags = fragment_files()
    new_log = date_changelog(log, args.version, today, [read_fragment(p) for p in frags])
    if args.dry_run:
        print(f"ok: {old} -> {args.version} ({today}), {len(frags)} entries; "
              "nothing written")
        return 0
    CHANGELOG.write_text(new_log, encoding="utf-8")
    INIT.write_text(bump_init(init, args.version), encoding="utf-8")
    manifest = MANIFEST.read_text(encoding="utf-8")
    MANIFEST.write_text(bump_manifest(manifest, args.version), encoding="utf-8")
    for p in frags:
        p.unlink()
    print(f"{old} -> {args.version}: CHANGELOG.md ({len(frags)} entries from "
          "changelog.d/), soundboard/__init__.py, the Stream Deck manifest")
    for cmd in (["scripts/checks/i18n_extract.py", "--check"], ["scripts/docs.py", "--no-shots"]):
        if subprocess.run([sys.executable, *cmd], cwd=ROOT).returncode:
            raise SystemExit(f"{' '.join(cmd)} failed: fix it, then run it again")
    print("next: build, VirusTotal scan (the installer and "
          r"build\michelper\obmichelper\obmichelper.exe), then "
          "scripts/docs.py --vt <sha256> N/N")
    return 0


if __name__ == "__main__":
    sys.exit(main())
