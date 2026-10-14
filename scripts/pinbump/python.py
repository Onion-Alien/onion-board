"""Bump soundboard/pyget.py to the newest patch release of the pinned Python minor
(3.12.x stays 3.12.x: a minor bump changes what the add-ons run on, so it's a hand
job) from the PSF's "python" package on NuGet, once the package's bytes match the
SHA-512 NuGet's catalog lists for it and the Python in it starts, with ssl, sqlite3
and pip. See common.py.

    python scripts/pinbump/python.py [--dry-run]
"""
from __future__ import annotations

import base64
import hashlib
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

SRC = common.ROOT / "soundboard" / "pyget.py"
VERSIONS = "https://api.nuget.org/v3-flatcontainer/python/index.json"
LEAF = "https://api.nuget.org/v3/registration5-semver1/python/{v}.json"
PACKAGE = "https://api.nuget.org/v3-flatcontainer/python/{v}/python.{v}.nupkg"
AUTHOR = "Python Software Foundation"


def latest(minor: str) -> str:
    """Newest X.Y.Z under ``minor`` ("3.12"); pre-releases like 3.12.0-b1 don't match."""
    found = [v for v in common.fetch_json(VERSIONS)["versions"]
             if re.fullmatch(rf"{re.escape(minor)}\.\d+", v)]
    if not found:
        sys.exit(f"no {minor}.x versions listed at {VERSIONS}")
    return max(found, key=common.version_key)


def catalog(version: str) -> dict:
    leaf = common.fetch_json(LEAF.format(v=version))
    if not leaf.get("listed", False):
        sys.exit(f"python {version} is unlisted on NuGet")
    return common.fetch_json(leaf["catalogEntry"])


def smoke(data: bytes, version: str) -> None:
    """The package's tools/python.exe (what pyget unpacks) starts and has what the
    add-ons' installs need."""
    with tempfile.TemporaryDirectory() as d:
        exe = common.unpack(data, Path(d)) / "tools" / "python.exe"
        common.run([exe, "-I", "-c", "import sys, ssl, sqlite3, ctypes; print(sys.version)"],
                   expect=version)
        common.run([exe, "-I", "-m", "pip", "--version"], expect="pip ")


def main() -> int:
    a = common.args()
    current = common.get_pin(SRC, "VERSION")
    minor = ".".join(current.split(".")[:2])
    new = latest(minor)
    print(f"python: pinned {current}, newest {minor}.x on NuGet {new}")
    if common.version_key(new) <= common.version_key(current):
        if not a.dry_run:
            return 0
        print("python: up to date; verifying the newest anyway (--dry-run)")
    elif common.already_open("python", new):
        print(f"python: {common.branch_for('python', new)} already exists, skipping")
        return 0
    entry = catalog(new)
    if entry.get("authors") != AUTHOR or entry.get("packageHashAlgorithm") != "SHA512":
        sys.exit(f"python {new}: catalog says authors {entry.get('authors')!r}, "
                 f"hash {entry.get('packageHashAlgorithm')!r}")
    data = common.fetch(PACKAGE.format(v=new), 60_000_000)
    got = base64.b64encode(hashlib.sha512(data).digest()).decode()
    if got != entry["packageHash"]:
        sys.exit(f"python {new}: package SHA-512 {got}, NuGet's catalog {entry['packageHash']}")
    digest = common.sha256(data)
    print(f"python: python.{new}.nupkg matches NuGet's SHA-512, sha256 {digest}, "
          f"{len(data)} bytes")
    if new == current and digest != common.get_pin(SRC, "SHA256"):
        sys.exit(f"python: pinned SHA256 isn't {digest}")
    smoke(data, new)
    if a.dry_run:
        return 0
    common.set_pins(SRC, {"VERSION": new, "SHA256": digest})
    common.open_pr(
        "python", new, [SRC], f"Add-ons' Python: pin {new}",
        f"Weekly pin bump: the Python add-ons download, {current} -> {new} "
        "(`soundboard/pyget.py`). Patch releases only; a new minor stays a hand job.\n\n"
        f"- `python.{new}.nupkg` (authors: {AUTHOR}) matches the SHA-512 in NuGet's "
        "catalog.\n"
        f"- SHA-256 `{digest}`, {len(data):,} bytes.\n"
        "- Smoke test: its `tools/python.exe` started on a Windows runner, imported "
        "ssl, sqlite3 and ctypes, and ran `-m pip`.\n\n"
        "Opened by `.github/workflows/pin-bumps.yml`; the checks were started on this "
        "branch by that run (a PR opened with GITHUB_TOKEN starts none by itself). "
        "If they're missing, close and reopen the PR.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
