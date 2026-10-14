"""Bump scripts/fetch_qjs.py to the newest QuickJS-ng release (the JavaScript engine
yt-dlp uses for YouTube's player challenge), once the Windows file's bytes match the
SHA-256 GitHub computed for the release asset. See common.py.

    python scripts/pinbump/qjs.py [--dry-run]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

SRC = common.ROOT / "scripts" / "fetch_qjs.py"
REPO = "quickjs-ng/quickjs"
ASSET = "qjs-windows-x86_64.exe"


def key(tag: str) -> tuple[int, ...]:
    return common.version_key(tag.removeprefix("v"))


def main() -> int:
    a = common.args()
    current = common.get_pin(SRC, "VERSION")
    release = common.github_release(REPO)
    new = release["tag_name"]
    if not re.fullmatch(r"v\d+(\.\d+)+", new):
        sys.exit(f"{REPO}'s latest release is {new!r}, not a vX.Y.Z tag")
    print(f"qjs: pinned {current}, newest release {new}")
    if key(new) <= key(current):
        if not a.dry_run:
            return 0
        print("qjs: up to date; verifying the newest anyway (--dry-run)")
    elif common.already_open("qjs", new):
        print(f"qjs: {common.branch_for('qjs', new)} already exists, skipping")
        return 0
    want = common.asset_sha256(release, ASSET)
    data = common.fetch(f"https://github.com/{REPO}/releases/download/{new}/{ASSET}",
                        50_000_000)
    digest = common.sha256(data)
    if digest != want:
        sys.exit(f"qjs: {ASSET} hashes to {digest}, GitHub's digest is {want}")
    if data[:2] != b"MZ":
        sys.exit(f"qjs: {ASSET} isn't a Windows program")
    print(f"qjs: {ASSET} sha256 {digest} matches GitHub's digest, {len(data)} bytes")
    if new == current and digest != common.get_pin(SRC, "SHA256"):
        sys.exit(f"qjs: pinned SHA256 isn't {digest}")
    if a.dry_run:
        return 0
    common.set_pins(SRC, {"VERSION": new, "SHA256": digest})
    common.open_pr(
        "qjs", new, [SRC], f"QuickJS: pin the Windows build to {new}",
        f"Weekly pin bump: QuickJS-ng {current} -> {new} (`scripts/fetch_qjs.py`).\n\n"
        f"- `{ASSET}` hashes to the SHA-256 GitHub computed for the release file: "
        f"`{digest}`, {len(data):,} bytes.\n"
        f"- Release notes: https://github.com/{REPO}/releases/tag/{new}\n\n"
        "Opened by `.github/workflows/pin-bumps.yml`; the checks were started on this "
        "branch by that run (a PR opened with GITHUB_TOKEN starts none by itself). "
        "If they're missing, close and reopen the PR. A YouTube download in the built "
        "app is the real test of a new engine.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
