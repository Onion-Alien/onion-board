"""Cut a release's version bump in one step, instead of editing three files by hand.

    .venv\\Scripts\\python scripts\\release.py 1.9.28          # bump, date the changelog
    .venv\\Scripts\\python scripts\\release.py 1.9.28 --dry-run

Changes not released yet are one file each in changelog.d/ (so two pull requests
never edit the same lines of CHANGELOG.md and conflict). It:
1. checks the new version is newer than soundboard/__init__.py's;
2. checks changelog.d/ has entries, writes them into CHANGELOG.md under
   "## <version> <long dash> <today, UTC>" (newest first) and deletes the files;
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
FRAGMENTS = ROOT / "changelog.d"
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
    frags = fragment_files()
    new_log = date_changelog(log, args.version, today, [read_fragment(p) for p in frags])
    if args.dry_run:
        print(f"ok: {old} -> {args.version} ({today}), {len(frags)} entries; "
              "nothing written")
        return 0
    CHANGELOG.write_text(new_log, encoding="utf-8")
    INIT.write_text(bump_init(init, args.version), encoding="utf-8")
    for p in frags:
        p.unlink()
    print(f"{old} -> {args.version}: CHANGELOG.md ({len(frags)} entries from "
          "changelog.d/), soundboard/__init__.py")
    for cmd in (["scripts/i18n_extract.py", "--check"], ["scripts/docs.py", "--no-shots"]):
        if subprocess.run([sys.executable, *cmd], cwd=ROOT).returncode:
            raise SystemExit(f"{' '.join(cmd)} failed: fix it, then run it again")
    print("next: build, VirusTotal scan, then scripts/docs.py --vt <sha256> N/N")
    return 0


if __name__ == "__main__":
    sys.exit(main())
