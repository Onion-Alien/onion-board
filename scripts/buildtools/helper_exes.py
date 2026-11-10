"""Make the app's named helper exes (soundboard/core/helperexe.py) beside a built
OnionBoard.exe: a byte-for-byte copy each, so Task Manager's Details tab tells them apart by
name (OnionBoardDownloads.exe and so on).

They stay identical to OnionBoard.exe on purpose: the installer then stores the exe once for
all of them (scripts/buildtools/installer_dupes.py). A copy with its own version info is a
different file, and three of those added about 40 MB to the download.

Usage: python scripts/buildtools/helper_exes.py dist/OnionBoard
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def make(dist: Path) -> int:
    sys.path.insert(0, str(ROOT))
    from soundboard.core.helperexe import HELPERS
    exe = dist / "OnionBoard.exe"
    if not exe.is_file():
        print(f"no {exe}", file=sys.stderr)
        return 1
    for stem in HELPERS.values():
        out = dist / f"{stem}.exe"
        shutil.copyfile(exe, out)
        print(f"made {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(make(Path(sys.argv[1] if len(sys.argv) > 1 else "dist/OnionBoard")))
