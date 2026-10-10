"""Every module in soundboard/ is in docs/CODE.md's *Code layout* table (CLAUDE.md:
"keep it current when adding modules"), and the table names no module that's gone.

    python scripts/check_code_doc.py      exit 1 and list them if not (CI's pick job)

A row covers a module by its path (`soundboard/ui/busy.py`), by its folder
(`soundboard/voicefx/`), or by its bare name after another path of the same folder in
the row (`soundboard/soundpad.py`, `resanance.py`). `__init__.py` files aren't listed.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "CODE.md"
SRC = ROOT / "soundboard"


def table_rows(text: str) -> list[list[str]]:
    """The backticked names in each row of the Code layout table."""
    section = text.split("## Code layout", 1)[1].split("\n## ", 1)[0]
    rows = []
    for line in section.splitlines():
        if line.startswith("|") and "`" in line:
            first = line.split("|")[1]   # the file column
            rows.append(re.findall(r"`([^`]+)`", first))
    return rows


def covered(rows: list[list[str]]) -> tuple[set[str], set[str], list[str]]:
    """(files named, folders named, names that are neither a file nor a folder)."""
    files, folders, stale = set(), set(), []
    for names in rows:
        folder = None
        for name in names:
            if not name.startswith("soundboard/") and folder is not None:
                name = folder + name   # a bare name after a path of the same row
            if not name.startswith("soundboard/"):
                continue
            path = ROOT / name
            if name.endswith("/"):
                folders.add(name)
                folder = name
            else:
                files.add(name)
                folder = name.rsplit("/", 1)[0] + "/"
            if not path.exists():
                stale.append(name)
    return files, folders, stale


def missing(files: set[str], folders: set[str]) -> list[str]:
    out = []
    for p in sorted(SRC.rglob("*.py")):
        rel = p.relative_to(ROOT).as_posix()
        if p.name == "__init__.py" or "__pycache__" in rel or rel in files:
            continue
        if any(rel.startswith(f) for f in folders):
            continue
        out.append(rel)
    return out


def main() -> int:
    files, folders, stale = covered(table_rows(DOC.read_text(encoding="utf-8")))
    gone = missing(files, folders)
    for rel in gone:
        print(f"docs/CODE.md: add {rel} to the Code layout table")
    for name in stale:
        print(f"docs/CODE.md: {name} is in the Code layout table but doesn't exist")
    return 1 if gone or stale else 0


if __name__ == "__main__":
    sys.exit(main())
