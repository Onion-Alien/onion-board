"""Fetch the RNNoise library Clean mic uses (build.ps1 runs this).

Clean mic takes background noise out of your mic with RNNoise (BSD-3,
licenses/RNNoise-BSD-3.txt). Its Windows build comes from the pyrnnoise wheel on PyPI;
only rnnoise.dll is taken from it (the wheel's Python side pulls in matplotlib and more,
which the app doesn't need). The repo has no binaries: this downloads the pinned wheel
and refuses one, or a DLL in it, whose SHA-256 doesn't match. A copy already there and
matching isn't fetched again.

    python scripts/buildtools/fetch_rnnoise.py [folder]
        (default: build/rnnoise; a source run uses it too)
"""

from __future__ import annotations

import hashlib
import io
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION = "0.4.5"
URL = ("https://files.pythonhosted.org/packages/20/8d/"
       "0e19fbae841a4933c4ba783cf4466dfd24c70305fab9bc0c8674aa19ebc6/"
       f"pyrnnoise-{VERSION}-py3-none-win_amd64.whl")
SHA256 = "f46015e5a58212d2883bf8e5a2cafb3c6b115176d8039f8340132cb24866b7da"
MEMBER = f"pyrnnoise-{VERSION}.data/purelib/pyrnnoise/rnnoise.dll"
DLL_SHA256 = "06770aeb8855ef942b5dcdb436f84dfdd5867b716ba4b4c8a2c66ade03197f31"
NAME = "rnnoise.dll"
LICENSE = ROOT / "licenses" / "RNNoise-BSD-3.txt"
TIMEOUT_S = 60
MAX_BYTES = 40 * 1024 * 1024   # the wheel is ~13 MB: anything far bigger isn't it


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    dll = folder / NAME
    if not (dll.is_file() and sha256(dll.read_bytes()) == DLL_SHA256):
        with urllib.request.urlopen(URL, timeout=TIMEOUT_S) as r:
            wheel = r.read(MAX_BYTES + 1)
        if len(wheel) > MAX_BYTES:
            raise SystemExit(f"{URL}: over {MAX_BYTES // (1024 * 1024)} MB")
        got = sha256(wheel)
        if got != SHA256:
            raise SystemExit(f"{URL}: SHA-256 {got}, expected {SHA256}")
        data = zipfile.ZipFile(io.BytesIO(wheel)).read(MEMBER)
        got = sha256(data)
        if got != DLL_SHA256:
            raise SystemExit(f"{MEMBER}: SHA-256 {got}, expected {DLL_SHA256}")
        tmp = dll.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(dll)
    shutil.copy2(LICENSE, folder / "LICENSE.txt")   # travels with the binary
    return dll


if __name__ == "__main__":
    out = fetch(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "rnnoise")
    print(f"RNNoise (pyrnnoise {VERSION}): {out}")
