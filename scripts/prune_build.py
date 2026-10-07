"""Trim the PyInstaller output before it's packaged (build.ps1 runs this).

PyInstaller's PySide6 hooks ship the whole Qt: QML and Quick 3D, Charts, the
web engine (Chromium), 186 translation files, a software OpenGL rasteriser…
none of which this app touches. This removes what the app never loads:

- Qt Python modules (`Qt*.pyd`) other than the ones the app imports (KEEP_MODULES)
- `Qt6*.dll` (and the FFmpeg DLLs) that nothing left behind imports, found by walking
  each kept file's import table with pefile
- the QML folder, the QML/positioning/touch plugins, spare platform plugins
- the web engine: its helper exe, resources and locales (the Radio tab's 3D globe
  used it up to 1.9.7; with them gone Qt6WebEngineCore, Quick and QML go too)
- image formats the app never opens (PDF, which drags Qt6Pdf in, TIFF, ICNS, TGA,
  WBMP: every format plugin is loaded at start-up), the virtual keyboard, and the
  TLS backends besides Windows' own (no OpenSSL ships, so that one can't load anyway)
- Qt's translations (the app has its own)
- `opengl32sw.dll`: the software OpenGL fallback. Widgets draw with the CPU, so it
  never loads.

Usage: python scripts/prune_build.py dist/OnionBoard [--dry-run]
Exit 1 if a kept file imports a DLL that would be missing afterwards, so a change in
Qt's layout fails the build instead of shipping an app that can't start.
"""
from __future__ import annotations

import shutil
import sys
from collections.abc import Callable, Iterable
from pathlib import Path

# PySide6 modules the app imports (soundboard/ and their PySide6-side dependencies).
# Everything else's .pyd goes.
KEEP_MODULES = frozenset({
    "QtCore", "QtGui", "QtWidgets", "QtNetwork", "QtMultimedia", "QtMultimediaWidgets",
})
# platform plugins: the real one, and offscreen for `OnionBoard.exe --selftest`
KEEP_PLATFORMS = frozenset({"qwindows.dll", "qoffscreen.dll"})
DROP_PLUGIN_DIRS = ("qmltooling", "position", "generic", "platforminputcontexts")
# picture formats: pads and thumbnails are PNG / JPEG / WebP / GIF / BMP (thumbs.py),
# the icons SVG and ICO; Qt loads every format plugin it finds when it first reads one
DROP_PLUGINS = ("imageformats/qpdf.dll", "imageformats/qtiff.dll", "imageformats/qicns.dll",
                "imageformats/qtga.dll", "imageformats/qwbmp.dll",
                "tls/qopensslbackend.dll", "tls/qcertonlybackend.dll")
# pyside6qml: the Python side of QML (only QtQml.pyd uses it), which keeps Qt6Qml in
DROP_FILES = ("opengl32sw.dll", "QtWebEngineProcess.exe", "pyside6qml.abi3.dll")
# the web engine's data: resources/ holds nothing else
DROP_DIRS = ("resources", "translations/qtwebengine_locales")
# the FFmpeg libraries are kept only if the multimedia plugin still imports them
DLL_CANDIDATES = ("qt6", "av", "sw")


def _imports_pefile(path: Path) -> list[str]:
    """Names of the DLLs `path` links against (lower-case)."""
    import pefile
    try:
        pe = pefile.PE(str(path), fast_load=True)
        pe.parse_data_directories(directories=[
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
    except pefile.PEFormatError:
        return []
    names = []
    for attr in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT"):
        for entry in getattr(pe, attr, None) or ():
            names.append(entry.dll.decode("ascii", "replace").lower())
    pe.close()
    return names


def closure(roots: Iterable[Path], pool: dict[str, Path],
            imports_of: Callable[[Path], list[str]]) -> set[str]:
    """Lower-case names of every file in `pool` reachable from `roots` by imports."""
    seen: set[str] = set()
    todo = list(roots)
    while todo:
        f = todo.pop()
        for name in imports_of(f):
            if name in pool and name not in seen:
                seen.add(name)
                todo.append(pool[name])
    return seen


def plan(app_dir: Path, imports_of: Callable[[Path], list[str]] = _imports_pefile
         ) -> tuple[list[Path], list[str]]:
    """(paths to delete, problems). A problem is a kept file importing a DLL that
    would be gone."""
    qt = app_dir / "_internal" / "PySide6"
    if not qt.is_dir():
        return [], [f"no PySide6 folder under {app_dir}"]
    drop: list[Path] = []

    # 1. Python modules
    for pyd in qt.glob("Qt*.pyd"):
        if pyd.stem not in KEEP_MODULES:
            drop.append(pyd)

    # 2. folders and files the app never opens
    for d in (qt / "qml", *(qt / "plugins" / n for n in DROP_PLUGIN_DIRS),
              *(qt / n for n in DROP_DIRS)):
        if d.is_dir():
            drop.append(d)
    drop += [qt / n for n in DROP_FILES if (qt / n).exists()]
    drop += [qt / "plugins" / n for n in DROP_PLUGINS if (qt / "plugins" / n).exists()]
    for p in (qt / "plugins" / "platforms").glob("*.dll"):
        if p.name not in KEEP_PLATFORMS:
            drop.append(p)
    drop += list((qt / "translations").glob("*.qm"))

    # 3. DLLs nothing left behind imports
    dropped = {p.resolve() for p in drop}

    def kept(p: Path) -> bool:
        r = p.resolve()
        return not any(r == d or d in r.parents for d in dropped)

    pool = {p.name.lower(): p for p in qt.glob("*.dll")}
    candidates = {n for n in pool if n.startswith(DLL_CANDIDATES)}
    roots = [p for p in qt.rglob("*") if p.is_file() and kept(p)
             and p.suffix.lower() in (".pyd", ".exe", ".dll") and p.name.lower() not in candidates]
    roots += [p for p in (app_dir / "_internal" / "shiboken6").glob("*.pyd")]
    needed = closure(roots, pool, imports_of)
    for name in sorted(candidates - needed):
        drop.append(pool[name])

    # 4. sanity: everything kept can still find what it imports
    dropped = {p.resolve() for p in drop}
    remaining = {n: p for n, p in pool.items() if kept(p)}
    problems = []
    for f in roots + [pool[n] for n in needed]:
        if not kept(f):
            continue
        for name in imports_of(f):
            if name in pool and name not in remaining:
                problems.append(f"{f.relative_to(app_dir)} needs {name}, which would be removed")
    return drop, problems


def folder_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1:
        print(__doc__)
        return 2
    app_dir = Path(args[0])
    drop, problems = plan(app_dir, _imports_pefile)
    for msg in problems:
        print("ERROR:", msg)
    if problems:
        return 1
    before = folder_size(app_dir)
    freed = sum(folder_size(p) if p.is_dir() else p.stat().st_size for p in drop)
    for p in sorted(drop):
        print(("would remove " if dry else "removing ") + str(p.relative_to(app_dir)))
        if not dry:
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    print(f"{'would free' if dry else 'freed'} {freed / 2**20:.0f} MB of {before / 2**20:.0f} MB "
          f"({len(drop)} items)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
