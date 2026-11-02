"""Fetch the QuickJS the app ships for YouTube's player challenge (build.ps1 runs this).

yt-dlp needs a JavaScript engine to solve YouTube's player challenge; most PCs have
none, so the app ships QuickJS-ng's Windows build (MIT, licenses/QuickJS-ng-MIT.txt).
The repo has no binaries: this downloads the pinned release file and refuses one
whose SHA-256 doesn't match. A copy already there and matching isn't fetched again.

    python scripts/buildtools/fetch_qjs.py [folder]
        (default: build/qjs; a source run uses it too)
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION = "v0.18.0"
URL = ("https://github.com/quickjs-ng/quickjs/releases/download/"
       f"{VERSION}/qjs-windows-x86_64.exe")
SHA256 = "ff03398d74ea6e6bd3a8e58058f7003225abcac229d7d57775b7aaae812a49c7"
NAME = "qjs.exe"
LICENSE = ROOT / "licenses" / "QuickJS-ng-MIT.txt"
TIMEOUT_S = 60


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / NAME
    if not (exe.is_file() and sha256(exe) == SHA256):
        tmp = exe.with_suffix(".part")
        with urllib.request.urlopen(URL, timeout=TIMEOUT_S) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f)
        got = sha256(tmp)
        if got != SHA256:
            tmp.unlink()
            raise SystemExit(f"{URL}: SHA-256 {got}, expected {SHA256}")
        tmp.replace(exe)
    shutil.copy2(LICENSE, folder / "LICENSE.txt")   # travels with the binary
    return exe


if __name__ == "__main__":
    out = fetch(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "qjs")
    print(f"QuickJS {VERSION}: {out}")
