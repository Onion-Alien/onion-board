"""Cut a release's version bump in one step, instead of editing three files by hand.

    .venv\\Scripts\\python scripts\\release.py 1.9.28          # bump, date the changelog
    .venv\\Scripts\\python scripts\\release.py 1.9.28 --dry-run

It:
1. checks the new version is newer than soundboard/__init__.py's;
2. checks CHANGELOG.md's "## Unreleased" has entries, renames it to
   "## <version> <long dash> <today, UTC>" and opens a fresh empty "## Unreleased" above it;
3. sets __version__ in soundboard/__init__.py;
4. runs `scripts/i18n_extract.py --check` (missing translations fail it) and
   `scripts/docs.py --no-shots` (the README and website release line).

It never builds, tags, pushes or commits. After it: build, scan the installer on
VirusTotal, then `scripts/docs.py --vt <sha256> N/N`. A "What's new" note
(soundboard/ui/whatsnew.py) is only for releases with something worth telling, and
its text is translated like any other, so it stays a hand-written step.
"""
from __future__ import annotations

import argparse
import datetime
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT = ROOT / "soundboard" / "__init__.py"
CHANGELOG = ROOT / "CHANGELOG.md"
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


def date_changelog(text: str, new: str, today: str) -> str:
    """Rename "## Unreleased" to the release, with a fresh empty one above it."""
    m = re.search(r"^## Unreleased[ \t]*\n(.*?)(?=^## |\Z)", text, flags=re.M | re.S)
    if not m:
        raise SystemExit("CHANGELOG.md has no '## Unreleased' section")
    if not m.group(1).strip():
        raise SystemExit("CHANGELOG.md's Unreleased section is empty: nothing to release")
    if re.search(rf"^## {re.escape(new)}\b", text, flags=re.M):
        raise SystemExit(f"CHANGELOG.md already has a {new} section")
    head = f"## Unreleased\n\n## {new} {DASH} {today}\n"
    return text[:m.start()] + head + text[m.start() + len("## Unreleased\n"):]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("version")
    ap.add_argument("--dry-run", action="store_true", help="check only, change nothing")
    args = ap.parse_args(argv)

    init, log = INIT.read_text(encoding="utf-8"), CHANGELOG.read_text(encoding="utf-8")
    old = current_version(init)
    if parse(args.version) <= parse(old):
        raise SystemExit(f"{args.version} isn't newer than the current {old}")
    today = datetime.datetime.now(datetime.UTC).date().isoformat()   # UTC, like commits
    new_log = date_changelog(log, args.version, today)
    if args.dry_run:
        print(f"ok: {old} -> {args.version} ({today}); nothing written")
        return 0
    CHANGELOG.write_text(new_log, encoding="utf-8")
    INIT.write_text(bump_init(init, args.version), encoding="utf-8")
    print(f"{old} -> {args.version}: CHANGELOG.md, soundboard/__init__.py")
    for cmd in (["scripts/i18n_extract.py", "--check"], ["scripts/docs.py", "--no-shots"]):
        if subprocess.run([sys.executable, *cmd], cwd=ROOT).returncode:
            raise SystemExit(f"{' '.join(cmd)} failed: fix it, then run it again")
    print("next: build, VirusTotal scan, then scripts/docs.py --vt <sha256> N/N")
    return 0


if __name__ == "__main__":
    sys.exit(main())
