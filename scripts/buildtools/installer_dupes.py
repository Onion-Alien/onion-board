"""Store byte-identical files once in the installer (installer/OnionBoard.iss).

The app folder holds the same bytes at more than one path: mostly the mic helper's own
Python (_internal\\michelper\\_internal: python313.dll, OpenSSL, the .pyd files), which
it needs beside its own exe because it's copied on to Program Files and run as SYSTEM
from there. Inno Setup's MergeDuplicateFiles only stores a file once when entries name
the same *source* file, so this script writes
dupes.iss for the .iss to #include in [Files]: `#define DupExcludes "..."`, every copy
but one of each set of identical files, for the folder-wide entry to skip, and an entry
for each copy skipped, installing the kept one's bytes under the copy's own path and
name. The kept one is never a copy of something else, and the copies skipped are never
Python itself at the top of _internal (*.dll, *.pyd, base_library.zip), so that still
goes in first and OnionBoard.exe last.

Every file still lands where it was, byte for byte: only the installer's payload
shrinks. Files are compared by contents (size, then SHA-256), never by name. build.ps1
runs this right before Inno Setup, so the lists always match what's in dist\\.

Usage: python scripts/buildtools/installer_dupes.py dist\\OnionBoard build\\installer
"""
from __future__ import annotations

import hashlib
import sys
from collections import defaultdict
from pathlib import Path, PureWindowsPath

EXE = "OnionBoard.exe"
SOURCE = r"..\dist\OnionBoard"   # as the .iss names the app folder


def is_early(rel: PureWindowsPath) -> bool:
    """What the .iss's first three entries install: Python itself, at the top of
    _internal (keep in step with installer/OnionBoard.iss)."""
    return len(rel.parts) == 2 and rel.parts[0].lower() == "_internal" and (
        rel.suffix.lower() in (".dll", ".pyd") or rel.name.lower() == "base_library.zip")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_dupes(root: Path) -> list[tuple[PureWindowsPath, PureWindowsPath]]:
    """(copy, kept) for every file in `root` with the same bytes as another, sorted by
    copy. The kept one of a set is one the .iss installs early when there is one (so the
    early entries still come first), else the first by path. Never the exe (it's
    installed last, on its own), empty files, or names the .iss lists can't hold."""
    by_size: dict[int, list[PureWindowsPath]] = defaultdict(list)
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = PureWindowsPath(p.relative_to(root))
        # a comma would split the Excludes list; { is a constant in DestDir/DestName
        if str(rel).lower() == EXE.lower() or "," in str(rel):
            continue
        size = p.stat().st_size
        if size:
            by_size[size].append(rel)
    pairs = []
    for rels in by_size.values():
        if len(rels) < 2:
            continue
        by_hash: dict[str, list[PureWindowsPath]] = defaultdict(list)
        for rel in rels:
            by_hash[_sha256(root / rel)].append(rel)
        for same in by_hash.values():
            if len(same) < 2:
                continue
            same.sort(key=lambda r: (not is_early(r), str(r).lower()))
            kept = same[0]
            # a copy the first entries install (Python's own folder) stays as it is:
            # those entries are wildcards with no list of their own to skip it from
            pairs += [(rel, kept) for rel in same[1:] if not is_early(rel)]
    return sorted(pairs, key=lambda p: str(p[0]).lower())


def _const(text: str) -> str:
    return text.replace("{", "{{")


def entry(copy: PureWindowsPath, kept: PureWindowsPath) -> str:
    dest = "{app}" + "".join("\\" + _const(p) for p in copy.parts[:-1])
    return (f'Source: "{SOURCE}\\{kept}"; DestDir: "{dest}"; '
            f'DestName: "{_const(copy.name)}"; Flags: ignoreversion\n')


def write(root: Path, out: Path) -> tuple[int, int]:
    """Writes out/dupes.iss; (copies stored once, bytes not stored again)."""
    pairs = find_dupes(root)
    out.mkdir(parents=True, exist_ok=True)
    excludes = "".join(",\\" + str(copy) for copy, _ in pairs)   # each after a comma
    (out / "dupes.iss").write_text(
        "; written by scripts/buildtools/installer_dupes.py for installer/OnionBoard.iss\n"
        f'#define DupExcludes "{excludes}"\n' + "".join(entry(c, k) for c, k in pairs),
        encoding="utf-8")
    return len(pairs), sum((root / c).stat().st_size for c, _ in pairs)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    root, out = Path(argv[0]), Path(argv[1])
    if not (root / EXE).is_file():
        print(f"no {root / EXE}: build the app first", file=sys.stderr)
        return 1
    n, size = write(root, out)
    print(f"installer: {n} identical copies stored once ({size / 1e6:.1f} MB unpacked)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
