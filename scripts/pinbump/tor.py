"""Bump soundboard/torget.py to the newest stable Tor Expert Bundle on
dist.torproject.org, once its signature checks out against the Tor Browser
developers' key named in torget.py's docstring. See common.py.

    python scripts/pinbump/tor.py [--dry-run]
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

SRC = common.ROOT / "soundboard" / "torget.py"
DIST = "https://dist.torproject.org/torbrowser/"
KEY_URL = "https://keys.openpgp.org/vks/v1/by-fingerprint/{fpr}"


def latest() -> str:
    """Newest stable version folder on dist (alphas like 16.0a13 don't match)."""
    listing = common.fetch(DIST, 1_000_000).decode("utf-8", "replace")
    found = set(re.findall(r'href="(\d+(?:\.\d+)+)/"', listing))
    if not found:
        sys.exit(f"no version folders listed at {DIST}")
    return max(found, key=common.version_key)


def signing_key() -> str:
    """The key fingerprint in torget.py's docstring, as 40 hex digits."""
    m = re.search(r"key\s+((?:[0-9A-F]{4}\s*){10})", SRC.read_text(encoding="utf-8"))
    if not m:
        sys.exit(f"no signing key fingerprint in {SRC}'s docstring")
    return re.sub(r"\s", "", m.group(1))


def verify(data: bytes, sig: bytes, fpr: str) -> None:
    """Exit unless sig is a good signature on data by fpr (or one of its subkeys)."""
    key = common.fetch(KEY_URL.format(fpr=fpr), 1_000_000)
    with tempfile.TemporaryDirectory() as home:
        os.chmod(home, 0o700)
        paths = {n: Path(home, n) for n in ("key.asc", "file", "file.asc")}
        for p, b in zip(paths.values(), (key, data, sig)):
            p.write_bytes(b)
        gpg = ["gpg", "--batch", "--homedir", home]
        # its exit code is no use: a missing gpg-agent makes it 2 after a good import
        subprocess.run([*gpg, "--import", str(paths["key.asc"])])
        status = subprocess.run(
            [*gpg, "--status-fd", "1", "--verify", str(paths["file.asc"]), str(paths["file"])],
            text=True, stdout=subprocess.PIPE).stdout
    # VALIDSIG <signing (sub)key> ... <primary key fingerprint>
    ok = any(line.split()[-1] == fpr for line in status.splitlines()
             if line.startswith("[GNUPG:] VALIDSIG "))
    if not ok:
        sys.exit(f"signature not valid for key {fpr}:\n{status}")


def main() -> int:
    a = common.args()
    current = common.get_pin(SRC, "VERSION")
    new = latest()
    print(f"tor: pinned {current}, newest on dist {new}")
    if common.version_key(new) <= common.version_key(current):
        if not a.dry_run:
            return 0
        print("tor: up to date; verifying the newest anyway (--dry-run)")
    elif common.already_open("tor", new):
        print(f"tor: {common.branch_for('tor', new)} already exists, skipping")
        return 0
    tarball = f"tor-expert-bundle-windows-x86_64-{new}.tar.gz"
    data = common.fetch(f"{DIST}{new}/{tarball}")
    sig = common.fetch(f"{DIST}{new}/{tarball}.asc", 100_000)
    fpr = signing_key()
    verify(data, sig, fpr)
    digest = common.sha256(data)
    print(f"tor: {tarball} signed by {fpr}, sha256 {digest}, {len(data)} bytes")
    if a.dry_run:
        return 0
    common.set_pins(SRC, {"VERSION": new, "SHA256": digest})
    common.open_pr(
        "tor", new, [SRC], f"Tor: pin the Expert Bundle to {new}",
        f"Weekly pin bump: Tor Expert Bundle {current} -> {new} (`soundboard/torget.py`).\n\n"
        f"- `{tarball}.asc` is a good signature by the key in torget.py's docstring "
        f"(`{fpr}`).\n- SHA-256 `{digest}`, {len(data):,} bytes.\n\n"
        "Opened by `.github/workflows/pin-bumps.yml`; the checks were started on this "
        "branch by that run (a PR opened with GITHUB_TOKEN starts none by itself). "
        "If they're missing, close and reopen the PR.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
