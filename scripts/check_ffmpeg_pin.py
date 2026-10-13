"""Check that every source in soundboard/ffmpegget.py still serves the pinned FFmpeg zip
with the pinned SHA-256 (the builder's site drops old builds; that's how 9.0.1 broke).
Run weekly by .github/workflows/ffmpeg-pin.yml; exits 1 with one line per broken source.

Reads the pin from the file's text, so it needs no packages and doesn't import the app."""
from __future__ import annotations

import hashlib
import re
import sys
import urllib.request
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "soundboard" / "ffmpegget.py"
TIMEOUT_S = 60
CHUNK = 1 << 20


def pin() -> tuple[str, list[str]]:
    text = SRC.read_text(encoding="utf-8")
    version = re.search(r'^VERSION = "([^"]+)"', text, re.M).group(1)
    sha = re.search(r'^SHA256 = "([0-9a-f]{64})"', text, re.M).group(1)
    zip_name = re.search(r'^ZIP = f"([^"]+)"', text, re.M).group(1).format(VERSION=version)
    block = re.search(r"^URLS = \((.*?)\)", text, re.M | re.S).group(1)
    urls = [u.format(VERSION=version, ZIP=zip_name)
            for u in re.findall(r'f"(https://[^"]+)"', block)]
    if not urls:
        sys.exit(f"no URLS found in {SRC}")
    return sha, urls


def digest(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "OnionBoard"})
    h = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        while chunk := r.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    sha, urls = pin()
    bad = 0
    for url in urls:
        try:
            got = digest(url)
        except Exception as e:  # noqa: BLE001 - every failure is one line in the report
            print(f"BROKEN {url}: {type(e).__name__}: {e}")
            bad += 1
            continue
        if got != sha:
            print(f"BROKEN {url}: SHA-256 {got}, pinned {sha}")
            bad += 1
        else:
            print(f"ok     {url}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
