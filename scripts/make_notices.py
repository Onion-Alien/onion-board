"""Write THIRD-PARTY-NOTICES.txt for the packaged app (build.ps1 runs this).

The PyInstaller build bundles Python, Qt (PySide6, LGPL-3.0), Qt WebEngine
(Chromium), numpy, scipy, libsndfile, libsoxr, PortAudio and more; their licences
require the notices to travel with the binaries. This walks the runtime
dependencies installed in the current environment and copies every licence file
each one ships, then adds the texts PySide6 doesn't include itself.

    python scripts/make_notices.py [output path]
"""

from __future__ import annotations

import importlib.metadata as md
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROOTS = ["PySide6", "numpy", "scipy", "sounddevice", "soundfile", "soxr", "adblock"]
LICENSE_FILE = re.compile(r"(?i)^(licen[cs]e|copying|notice|authors)|licen[cs]e")
SKIP_FILE = re.compile(r"(?i)commercial")  # Qt's commercial terms don't apply to us
RULE = "=" * 78

EXTRA = f"""\
{RULE}
Python {sys.version.split()[0]}  --  PSF License
{RULE}
The packaged app includes the Python runtime and standard library.
Full text: https://docs.python.org/3/license.html

{RULE}
Qt 6 / PySide6 / Shiboken6  --  LGPL-3.0-only
{RULE}
Qt and PySide6 are used under the GNU Lesser General Public License v3.
The Qt libraries are shipped as separate, replaceable DLLs in the app folder
(`_internal\\PySide6\\`); you may swap them for your own build. Source code:
https://code.qt.io  and  https://code.qt.io/cgit/pyside/pyside-setup.git
The LGPL-3.0 and the GPL-3.0 it builds on are reproduced at the end of this file.

{RULE}
Qt WebEngine (Chromium)
{RULE}
The Browser tab uses Qt WebEngine, which contains Chromium and its third-party
components under BSD-style and other licences. The full list:
https://doc.qt.io/qt-6/qtwebengine-licensing.html

{RULE}
PyInstaller bootloader  --  GPL-2.0-or-later with the PyInstaller exception
{RULE}
The exception allows distributing the bundled program under any licence.
https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt
"""


def closure(roots: list[str]) -> list[md.Distribution]:
    from packaging.requirements import Requirement  # ships with pip / setuptools

    seen: dict[str, md.Distribution] = {}
    todo = list(roots)
    while todo:
        req = Requirement(todo.pop())
        if req.marker and not req.marker.evaluate({"extra": ""}):
            continue
        key = re.sub(r"[-_.]+", "-", req.name).lower()
        if key in seen:
            continue
        try:
            seen[key] = dist = md.distribution(req.name)
        except md.PackageNotFoundError:
            continue
        todo += dist.requires or []
    return sorted(seen.values(), key=lambda d: d.metadata["Name"].lower())


def section(dist: md.Distribution) -> str:
    m = dist.metadata
    lic = m.get("License-Expression") or ((m.get("License") or "").strip().splitlines()
                                          or ["see below"])[0]
    home = m.get("Home-page") or next(
        (u.split(",", 1)[1].strip() for u in m.get_all("Project-URL") or []), "")
    out = [RULE, f"{m['Name']} {dist.version}  --  {lic}", home, RULE]
    for f in dist.files or []:
        if LICENSE_FILE.search(f.name) and not SKIP_FILE.search(f.name) and f.suffix != ".py":
            try:
                text = Path(f.locate()).read_text(encoding="utf-8", errors="replace").strip()
            except (FileNotFoundError, OSError):
                continue
            out += [f"--- {f.as_posix()}", text, ""]
    return "\n".join(out) + "\n"


def main() -> None:
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / "THIRD-PARTY-NOTICES.txt"
    parts = ["Soundboard includes the following third-party software.\n",
             "Soundboard itself is MIT licensed; see LICENSE.txt.\n", EXTRA]
    parts += [section(d) for d in closure(ROOTS)]
    for name in ("LGPL-3.0.txt", "GPL-3.0.txt"):
        parts += [f"{RULE}\n{name}\n{RULE}\n", (ROOT / "licenses" / name).read_text("utf-8")]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {dest} ({dest.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
