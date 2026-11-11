"""Make the app's named helper exes (soundboard/core/helperexe.py) beside a built
OnionBoard.exe, so Task Manager tells them apart ("Onion Board download helper" and so on).

Each helper is only PyInstaller's small launcher (the front of OnionBoard.exe, ~170 KB)
with its own name in the version info, marked to load the program from a file beside it,
<name>.pkg, instead of from its own end. That .pkg is a byte-for-byte copy of
OnionBoard.exe (the launcher finds the program at the end of the file it opens), so the
installer stores it once with the exe (scripts/buildtools/installer_dupes.py): three
named helpers cost about half a MB of download, not three 17 MB exes.

Usage: python scripts/buildtools/helper_exes.py dist/OnionBoard
"""
from __future__ import annotations

import shutil
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# PyInstaller's archive cookie at the end of the exe: magic, archive length, TOC offset,
# TOC length, Python version, Python DLL name ('!8sIIii64s')
COOKIE = struct.Struct("!8sIIii64s")
MAGIC = b"MEI\014\013\012\013\016"
# what PyInstaller appends instead of the archive to load it from <name>.pkg
SIDELOAD = b"MEI\015\013\012\013\016"


def launcher(exe_bytes: bytes) -> bytes:
    """The front of a PyInstaller exe: everything before its appended archive."""
    at = exe_bytes.rfind(MAGIC)
    if at < 0 or at + COOKIE.size > len(exe_bytes):
        raise SystemExit("OnionBoard.exe has no PyInstaller archive at its end")
    archive_len = COOKIE.unpack_from(exe_bytes, at)[1]
    start = at + COOKIE.size - archive_len
    if not 0 < start < at:
        raise SystemExit("OnionBoard.exe's archive cookie doesn't add up")
    return exe_bytes[:start]


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
    front = launcher(exe.read_bytes())
    base = version_info.render(soundboard.__version__)
    for stem, description in HELPERS.values():
        out = dist / f"{stem}.exe"
        out.write_bytes(front)
        tmp = dist.parent / f"{stem}-version.txt"
        tmp.write_text(version_text(base, stem, description), encoding="utf-8")
        info = versioninfo.load_version_info_from_text_file(str(tmp))
        tmp.unlink()
        versioninfo.write_version_info_to_executable(str(out), info)
        with open(out, "ab") as f:
            f.write(SIDELOAD)
        winutils.update_exe_pe_checksum(str(out))
        shutil.copyfile(exe, dist / f"{stem}.pkg")
        print(f"made {out.name} ({description}, {out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(make(Path(sys.argv[1] if len(sys.argv) > 1 else "dist/OnionBoard")))
