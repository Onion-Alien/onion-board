"""One Microsoft C++ runtime in the PyInstaller output (build.ps1 runs this).

PySide6 6.11's wheels bring their own, recent C++ runtime (`msvcp140.dll`,
`vcruntime140.dll`… in `shiboken6\\`), and Qt is built against it. PyInstaller may also
collect another copy of the same DLLs into `_internal\\`, taken from wherever it found
them on the build PC (System32, Python's folder, a folder on PATH), and that one can
be older. Windows loads one `msvcp140.dll` per process, whichever it finds first: if
that's the older one, Qt asks it for functions it doesn't have and the app can't
start ("DLL load failed while importing QtWidgets: The specified procedure could not
be found").

This finds every copy of each runtime DLL under `_internal\\` and overwrites the older
ones with the newest (shiboken6's own, from the build's Python, counts too), so
whichever Windows picks is new enough. A C++ runtime DLL shiboken6 ships that
PyInstaller left out goes into `_internal\\shiboken6\\`, the folder PySide6 adds to
the DLL search.

Usage: python scripts/vc_runtime.py dist/OnionBoard [--dry-run]
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

# the Visual C++ 2015-2022 runtime (VC14): one version must serve the whole process.
# Wheels that rename their copy (numpy.libs\msvcp140-<hash>.dll) don't clash.
RUNTIME_DLLS = frozenset({
    "concrt140.dll", "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
    "msvcp140_atomic_wait.dll", "msvcp140_codecvt_ids.dll", "vccorlib140.dll",
    "vcruntime140.dll", "vcruntime140_1.dll", "vcomp140.dll", "vcamp140.dll",
})

# what Qt itself links against: added from shiboken6 when PyInstaller left one out
# (the rest, OpenMP, C++ AMP…, only matter if something in the app already ships them)
QT_RUNTIME_PREFIXES = ("msvcp140", "vcruntime140")

Version = tuple[int, int, int, int]


def _version_pefile(path: Path) -> Version:
    """The DLL's file version, (0, 0, 0, 0) if it has none."""
    import pefile
    try:
        pe = pefile.PE(str(path), fast_load=True)
        pe.parse_data_directories(directories=[
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
    except pefile.PEFormatError:
        return (0, 0, 0, 0)
    try:
        info = pe.VS_FIXEDFILEINFO[0]
        ms, ls = info.FileVersionMS, info.FileVersionLS
        return (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)
    except (AttributeError, IndexError):
        return (0, 0, 0, 0)
    finally:
        pe.close()


def shiboken_dir() -> Path | None:
    """The build Python's shiboken6 package folder (not imported: no DLLs load)."""
    spec = importlib.util.find_spec("shiboken6")
    return Path(spec.origin).parent if spec and spec.origin else None


def _runtime_dlls(folder: Path, recurse: bool) -> dict[str, list[Path]]:
    found: dict[str, list[Path]] = {}
    for p in sorted(folder.rglob("*.dll") if recurse else folder.glob("*.dll")):
        if p.name.lower() in RUNTIME_DLLS:
            found.setdefault(p.name.lower(), []).append(p)
    return found


def plan(app_dir: Path, source: Path | None = None,
         version_of: Callable[[Path], Version] = _version_pefile
         ) -> list[tuple[Path, Path]]:
    """(newest copy, file it's copied to): over every older copy in the app, and into
    `_internal\\shiboken6\\` for a DLL `source` (shiboken6's folder) has that the app
    doesn't."""
    internal = app_dir / "_internal"
    shipped = _runtime_dlls(internal, recurse=True)
    extra = _runtime_dlls(source, recurse=False) if source and source.is_dir() else {}
    extra = {n: ps for n, ps in extra.items()
             if n in shipped or n.startswith(QT_RUNTIME_PREFIXES)}
    moves = []
    for name in sorted(shipped.keys() | extra.keys()):
        targets = shipped.get(name, [])
        candidates = targets + extra.get(name, [])
        versions = {p: version_of(p) for p in candidates}
        newest = max(candidates, key=lambda p: versions[p])
        if not targets:
            moves.append((newest, internal / "shiboken6" / newest.name))
        moves += [(newest, p) for p in targets if versions[p] < versions[newest]]
    return moves


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1:
        print(__doc__)
        return 2
    app_dir = Path(args[0])
    if not (app_dir / "_internal").is_dir():
        print(f"ERROR: no _internal folder under {app_dir}")
        return 1
    moves = plan(app_dir, shiboken_dir())
    for src, dst in moves:
        print(("would copy " if dry else "copying ") + f"{src} to {dst.relative_to(app_dir)}")
        if not dry:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    if not moves:
        print("one C++ runtime version already")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
