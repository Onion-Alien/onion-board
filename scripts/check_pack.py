"""Check a shared sound pack and print its packs/catalog.json entry.

    python scripts/check_pack.py horror.zip --id horror-night --name "Horror night"
        --tag pack-horror-night [--about "..."] [--author "..."] [--emoji 👻]

It reads the zip the way the app does (soundboard.backup), so a pack that passes here
imports. It refuses a pack the app wouldn't take (unreadable, too big, no sounds) and
one that carries settings (a pack must never change someone's theme or hotkeys), and
lists every sound so the licences can be checked against the submission. Then:

    gh release create <tag> <zip> --prerelease --title "<name> (free sound pack)"

and add the printed entry to packs/catalog.json (its URL is that release's file, so
nobody can change the sounds after they were checked: the app holds it to the SHA-256).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from soundboard import backup, packs, updates  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("zip", type=Path)
    ap.add_argument("--id", required=True, help="short-lowercase-name")
    ap.add_argument("--name", required=True)
    ap.add_argument("--tag", required=True, help="the release tag it's uploaded to")
    ap.add_argument("--about", default="")
    ap.add_argument("--author", default="")
    ap.add_argument("--emoji", default="📦")
    ap.add_argument("--license", default="CC0")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")   # names and emoji on a cp1252 console

    problems = []
    if not packs.ID_RE.fullmatch(a.id):
        problems.append(f"--id {a.id!r}: lowercase letters, digits and dashes only")
    size = a.zip.stat().st_size
    if size > packs.MAX_SIZE:
        problems.append(f"{size / 1e6:.0f} MB: over the {packs.MAX_SIZE >> 20} MB limit")
    pkg = backup.read(a.zip)   # raises BackupError for anything the app can't import
    if not pkg.sounds:
        problems.append("no sounds in it")
    if pkg.settings:
        problems.append("it carries settings: export a category, not the whole board")
    for ps in pkg.sounds:
        print(f"  {ps.entry.get('name') or Path(ps.audio).stem}   [{ps.audio}]")
    h = hashlib.sha256(a.zip.read_bytes()).hexdigest()
    entry = {"id": a.id, "name": a.name, "emoji": a.emoji, "description": a.about,
             "url": f"{updates.DOWNLOADS}{a.tag}/{a.zip.name}", "sha256": h, "size": size,
             "sounds": len(pkg.sounds), "license": a.license, "author": a.author,
             "categories": list(pkg.categories)}
    if not packs.parse([entry]):
        problems.append("the entry doesn't pass packs.parse (see its rules)")
    if problems:
        print("\nNot OK:\n  " + "\n  ".join(problems))
        return 1
    print(f"\n{len(pkg.sounds)} sounds, {size / 1e6:.1f} MB. Catalog entry:\n")
    print(json.dumps(entry, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
