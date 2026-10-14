"""Bump soundboard/ffmpegget.py to the newest FFmpeg essentials build from gyan.dev,
once the builder's published SHA-256, GitHub's digest of the GyanD/codexffmpeg release
file and the bytes from every source in URLS all agree, and its ffmpeg and ffprobe
encode and read back a second of MP3 and M4A. See common.py.

When the pin is already the newest, it checks that every source still serves the
pinned zip with the pinned SHA-256 (the builder's site drops old builds; that's how
9.0.1 broke) and fails with one line per broken source.

    python scripts/pinbump/ffmpeg.py [--dry-run]
"""
from __future__ import annotations

import io
import re
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

SRC = common.ROOT / "soundboard" / "ffmpegget.py"
NEWEST = "https://www.gyan.dev/ffmpeg/builds/release-version"
SHA_URL = "https://www.gyan.dev/ffmpeg/builds/packages/{zip}.sha256"
REPO = "GyanD/codexffmpeg"


def layout(version: str) -> tuple[str, list[str], list[str]]:
    """ffmpegget.py's ZIP, URLS and KEEP members for ``version``, from its text."""
    text = SRC.read_text(encoding="utf-8")
    zip_name = re.search(r'^ZIP = f"([^"]+)"', text, re.M).group(1).format(VERSION=version)
    urls = re.search(r"^URLS = \((.*?)\)", text, re.M | re.S).group(1)
    keep = re.search(r"^KEEP = \{(.*?)\}$", text, re.M | re.S).group(1)
    urls = [u.format(VERSION=version, ZIP=zip_name)
            for u in re.findall(r'f"(https://[^"]+)"', urls)]
    members = [m.format(VERSION=version) for m in re.findall(r'f"([^"]+)":', keep)]
    if not (urls and members):
        sys.exit(f"no URLS or KEEP found in {SRC}")
    return zip_name, urls, members


def latest() -> str:
    v = common.fetch(NEWEST, 1000).decode("ascii", "replace").strip()
    if not re.fullmatch(r"\d+(\.\d+)+", v):
        sys.exit(f"{NEWEST} says {v!r}, not a version")
    return v


def verify(version: str) -> tuple[str, bytes, list[str]]:
    """(SHA-256, zip, problems) for ``version``: the builder's .sha256 file, GitHub's
    digest and every source's bytes must all agree, and the zip must hold KEEP."""
    zip_name, urls, members = layout(version)
    bad: list[str] = []
    try:
        want = common.fetch(SHA_URL.format(zip=zip_name), 1000).decode("ascii").split()[0]
    except Exception as e:  # noqa: BLE001 - every failure is one line in the report
        return "", b"", [f"BROKEN {SHA_URL.format(zip=zip_name)}: {type(e).__name__}: {e}"]
    try:
        gh = common.asset_sha256(common.github_release(REPO, version), zip_name)
        if gh != want:
            bad.append(f"BROKEN GitHub digest {gh}, builder's {want}")
    except (Exception, SystemExit) as e:  # noqa: BLE001
        bad.append(f"BROKEN GitHub release {version}: {type(e).__name__}: {e}")
    good = b""
    for url in urls:
        try:
            data = common.fetch(url)
        except Exception as e:  # noqa: BLE001
            bad.append(f"BROKEN {url}: {type(e).__name__}: {e}")
            continue
        got = common.sha256(data)
        if got != want:
            bad.append(f"BROKEN {url}: SHA-256 {got}, builder's {want}")
            continue
        names = set(zipfile.ZipFile(io.BytesIO(data)).namelist())
        if missing := [m for m in members if m not in names]:
            bad.append(f"BROKEN {url}: zip lacks {', '.join(missing)}")
            continue
        good = data
        print(f"ok     {url}")
    return want, good, bad


def smoke(data: bytes, version: str) -> None:
    """The KEEP members, unpacked as ffmpegget does, run: a second of tone encoded to
    MP3 and to M4A (AAC, which only FFmpeg decodes for the app) and read back."""
    with tempfile.TemporaryDirectory() as d:
        members = layout(version)[2]
        zipfile.ZipFile(io.BytesIO(data)).extractall(d, members)
        exe = {Path(m).name: Path(d, m) for m in members}
        common.run([exe["ffmpeg.exe"], "-version"], expect=f"ffmpeg version {version}")
        for out in ("tone.mp3", "tone.m4a"):
            common.run([exe["ffmpeg.exe"], "-v", "error", "-f", "lavfi",
                        "-i", "sine=frequency=440:duration=1", Path(d, out)])
            got = common.run([exe["ffprobe.exe"], "-v", "error", "-show_entries",
                              "format=duration", "-of", "csv=p=0", Path(d, out)])
            if not 0.9 < float(got.strip() or 0) < 1.2:
                sys.exit(f"smoke FAILED: ffprobe says {out} lasts {got.strip()!r}, not 1 s")


def main() -> int:
    a = common.args()
    current = common.get_pin(SRC, "VERSION")
    pinned = common.get_pin(SRC, "SHA256")
    new = latest()
    print(f"ffmpeg: pinned {current}, newest on gyan.dev {new}")
    if common.version_key(new) > common.version_key(current):
        if common.already_open("ffmpeg", new) and not a.dry_run:
            print(f"ffmpeg: {common.branch_for('ffmpeg', new)} already exists, skipping")
            return 0
        digest, data, bad = verify(new)
        if bad:
            print("\n".join(bad))
            print(f"ffmpeg: {new} isn't on both sources with matching hashes yet; "
                  "checking the pinned one instead")
        else:
            zip_name = layout(new)[0]
            print(f"ffmpeg: {zip_name} sha256 {digest}, {len(data)} bytes, "
                  "same on every source")
            smoke(data, new)
            if a.dry_run:
                return 0
            common.set_pins(SRC, {"VERSION": new, "SHA256": digest})
            common.open_pr(
                "ffmpeg", new, [SRC], f"FFmpeg: pin the essentials build to {new}",
                f"Weekly pin bump: FFmpeg essentials {current} -> {new} "
                "(`soundboard/ffmpegget.py`).\n\n"
                f"- `{zip_name}`: the builder's published SHA-256, GitHub's digest of the "
                f"{REPO} release file and the bytes from both URLS all match.\n"
                f"- SHA-256 `{digest}`, {len(data):,} bytes; the zip holds every KEEP "
                "member.\n"
                "- Smoke test: on a Windows runner its ffmpeg encoded a second of tone to "
                "MP3 and M4A and ffprobe read both back.\n\n"
                "Opened by `.github/workflows/pin-bumps.yml`; the checks were started on "
                "this branch by that run (a PR opened with GITHUB_TOKEN starts none by "
                "itself). If they're missing, close and reopen the PR.")
            return 0
    digest, data, bad = verify(current)
    if digest and digest != pinned:
        bad.append(f"BROKEN builder's SHA-256 for {current} is {digest}, pinned {pinned}")
    if bad:
        print("\n".join(bad))
        return 1
    print(f"ffmpeg: pinned {current} still served by every source")
    if a.dry_run:
        smoke(data, current)
    return 0


if __name__ == "__main__":
    sys.exit(main())
