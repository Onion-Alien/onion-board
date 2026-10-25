"""Pack the Stream Deck plugin into dist/com.onionalien.onionboard.streamDeckPlugin.

    .venv\\Scripts\\python scripts\\buildtools\\pack_streamdeck.py [--require]

build.ps1 runs it; the file goes on each GitHub release next to the installer
(docs/DEVELOPING.md "Release"). Double-clicking it installs the plugin in Stream Deck.
Elgato's CLI validates the plugin and packs it (through npx, pinned). Without Node it
says so and skips, like a build without Inno Setup; --require (the release workflow)
makes that an error. The manifest's Version must be __version__ + ".0" (release.py
moves both).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "streamdeck" / "com.onionalien.onionboard.sdPlugin"
OUT = ROOT / "dist"
NAME = "com.onionalien.onionboard.streamDeckPlugin"
CLI = "@elgato/cli@1.10.2"


def fixed_times(path: Path) -> None:
    """Rewrites the zip with every entry dated 1980-01-01 and no extra fields: the
    packer stores each file's local time next to its UTC time, which gives away the
    build PC's time zone. The contents and their order stay the same."""
    tmp = path.with_suffix(".tmp")
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w") as zout:
        for i in zin.infolist():
            z = zipfile.ZipInfo(i.filename, date_time=(1980, 1, 1, 0, 0, 0))
            z.compress_type = i.compress_type
            z.create_system = i.create_system
            z.external_attr = i.external_attr
            zout.writestr(z, zin.read(i))
    tmp.replace(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--require", action="store_true", help="fail without Node")
    args = ap.parse_args(argv)
    init = (ROOT / "soundboard" / "__init__.py").read_text(encoding="utf-8")
    app = re.search(r'__version__ = "([^"]+)"', init).group(1)
    plugin = json.loads((PLUGIN / "manifest.json").read_text(encoding="utf-8"))["Version"]
    if plugin != f"{app}.0":
        raise SystemExit(f"the Stream Deck manifest says {plugin}, the app {app}: "
                         f"set it to {app}.0 (scripts/release.py does)")
    npx = shutil.which("npx")
    if not npx:
        if args.require:
            raise SystemExit("npx (Node.js) not found: can't pack the Stream Deck plugin")
        print("Node.js not found, so no Stream Deck plugin this time "
              "(winget install OpenJS.NodeJS.LTS)")
        return 0
    OUT.mkdir(exist_ok=True)
    (OUT / NAME).unlink(missing_ok=True)
    try:
        done = subprocess.run([npx, "--yes", CLI, "pack", str(PLUGIN), "-o", str(OUT),
                               "--force", "--no-update-check", "--no-file-list"],
                              cwd=ROOT, timeout=300)
    except subprocess.TimeoutExpired:
        raise SystemExit("packing the Stream Deck plugin took over 5 minutes") from None
    if done.returncode or not (OUT / NAME).is_file():
        raise SystemExit("packing the Stream Deck plugin failed (see above)")
    fixed_times(OUT / NAME)
    kb = (OUT / NAME).stat().st_size // 1024
    print(f"Built dist\\{NAME} ({kb} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
