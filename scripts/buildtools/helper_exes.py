"""Make the app's named helper exes (soundboard/core/helperexe.py) beside a built
OnionBoard.exe: a copy of it each, with its own name in the version info, so Task Manager
tells them apart ("Onion Board download helper" and so on).

Usage: python scripts/buildtools/helper_exes.py dist/OnionBoard
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def version_text(base: str, stem: str, description: str) -> str:
    """The app's version info (scripts/buildtools/version_info.py) with this helper's names."""
    text = base
    for old, new in (("StringStruct('FileDescription', 'Onion Board')",
                      f"StringStruct('FileDescription', '{description}')"),
                     ("StringStruct('InternalName', 'OnionBoard')",
                      f"StringStruct('InternalName', '{stem}')"),
                     ("'OnionBoard.exe'", f"'{stem}.exe'")):
        if old not in text:
            raise SystemExit(f"version info has no {old!r}: change helper_exes.py to match")
        text = text.replace(old, new)
    return text


def make(dist: Path) -> int:
    sys.path.insert(0, str(ROOT))
    import soundboard
    from PyInstaller.utils.win32 import versioninfo, winutils

    from scripts.buildtools import version_info
    from soundboard.core.helperexe import HELPERS
    exe = dist / "OnionBoard.exe"
    if not exe.is_file():
        print(f"no {exe}", file=sys.stderr)
        return 1
    base = version_info.render(soundboard.__version__)
    for stem, description in HELPERS.values():
        out = dist / f"{stem}.exe"
        shutil.copyfile(exe, out)
        tmp = dist.parent / f"{stem}-version.txt"
        tmp.write_text(version_text(base, stem, description), encoding="utf-8")
        info = versioninfo.load_version_info_from_text_file(str(tmp))
        tmp.unlink()
        # keeps the program's appended archive (re-adds it if Windows' update drops it)
        versioninfo.write_version_info_to_executable(str(out), info)
        winutils.update_exe_pe_checksum(str(out))
        print(f"made {out.name} ({description})")
    return 0


if __name__ == "__main__":
    sys.exit(make(Path(sys.argv[1] if len(sys.argv) > 1 else "dist/OnionBoard")))
