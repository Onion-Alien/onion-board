"""Check a shared sound pack and print its packs/catalog.json entry.

    python scripts/checks/check_pack.py horror.zip --id horror-night --name "Horror night"
        --tag pack-horror-night [--about "..."] [--author "..."] [--emoji 👻]
        [--preview "Door creak" --preview Scream ...]

It reads the zip the way the app does (soundboard.core.backup), so a pack that passes here
imports. It refuses a pack the app wouldn't take (unreadable, too big, no sounds) and
one that carries settings (a pack must never change someone's theme or hotkeys), and
lists every sound so the licences can be checked against the submission. Then:

    gh release create <tag> <zip> --prerelease --title "<name> (free sound pack)"

(with --preview, upload the <id>-preview.zip it writes next to the pack to the same
release: a few of its sounds, cut short, that people can hear before adding it)
and add the printed entry to packs/catalog.json (its URL is that release's file, so
nobody can change the sounds after they were checked: the app holds it to the SHA-256).
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from soundboard.core import backup, updates  # noqa: E402
from soundboard.sounds import library, packs  # noqa: E402

SAMPLE_S = 7.0   # a preview's sounds: at most this long,
FADE_S = 1.0     # fading out over the last second


def make_preview(src: Path, pkg: backup.Package, names: list[str], dest: Path) -> list[str]:
    """Write `dest`: the named sounds of the pack at `src` with their pictures, cut to
    SAMPLE_S with a fade, in the backup format (packs.samples reads it). The names not
    found."""
    import numpy as np
    import soundfile as sf
    by_name = {str(ps.entry.get("name") or ""): ps for ps in pkg.sounds}
    missing, order = [n for n in names if n not in by_name], []
    with zipfile.ZipFile(src) as z, zipfile.ZipFile(dest, "w", zipfile.ZIP_STORED) as out:
        for i, name in enumerate(n for n in names if n in by_name):
            ps = by_name[name]
            tmp = dest.with_name(f"_sample{Path(ps.audio).suffix}")
            tmp.write_bytes(z.read(ps.audio))
            try:
                x = library.decode(str(tmp))
            finally:
                tmp.unlink()
            if len(x) > SAMPLE_S * library.SR:   # cut short: fade out, not a click
                x = x[:int(SAMPLE_S * library.SR)]
                fade = int(FADE_S * library.SR)
                x[-fade:] *= np.linspace(1, 0, fade, dtype=x.dtype)[:, None]
            buf = io.BytesIO()
            sf.write(buf, x, library.SR, format="OGG", subtype="VORBIS")
            folder = f"sounds/{i + 1:03d} {backup._safe(name)}"
            entry = {k: v for k, v in ps.entry.items() if k in ("name", "color", "tags")}
            entry["audio"] = "sound.ogg"
            out.writestr(f"{folder}/sound.ogg", buf.getvalue())
            if ps.picture:
                entry["picture"] = "picture" + Path(ps.picture).suffix.lower()
                out.writestr(f"{folder}/{entry['picture']}", z.read(ps.picture))
            out.writestr(f"{folder}/sound.json", json.dumps(entry, indent=1, ensure_ascii=False))
            order.append(folder)
        out.writestr(backup.MANIFEST, json.dumps(
            {"format": backup.FORMAT, "format_version": 1, "categories": [],
             "sounds": order}, indent=1))
    return missing


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
    ap.add_argument("--preview", action="append", default=[], metavar="SOUND",
                    help=f"one of its sounds people can hear before adding it (up to "
                         f"{packs.SAMPLES}: repeat it)")
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
    if a.preview:
        names = [n.strip() for n in a.preview if n.strip()][:packs.SAMPLES]
        pdest = a.zip.with_name(f"{a.id}-preview.zip")
        missing = make_preview(a.zip, pkg, names, pdest)
        if missing:
            problems.append(f"--preview: no sound called {', '.join(map(repr, missing))}")
        pdata = pdest.read_bytes()
        entry["preview"] = {"url": f"{updates.DOWNLOADS}{a.tag}/{pdest.name}",
                            "sha256": hashlib.sha256(pdata).hexdigest(), "size": len(pdata)}
        print(f"\npreview: {pdest} ({len(pdata) / 1e3:.0f} KB)")
    if not packs.parse([entry]) or (a.preview and not packs.parse([entry])[0].preview_url):
        problems.append("the entry doesn't pass packs.parse (see its rules)")
    if problems:
        print("\nNot OK:\n  " + "\n  ".join(problems))
        return 1
    print(f"\n{len(pkg.sounds)} sounds, {size / 1e6:.1f} MB. Catalog entry:\n")
    print(json.dumps(entry, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
