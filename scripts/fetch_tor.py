"""Download the Tor Expert Bundle and unpack the parts Onion Board runs into
vendor/tor/ (gitignored), for trying Tor mode from source without pressing Get Tor.
The app itself doesn't ship Tor: it downloads it on request (soundboard/torget.py,
which holds the pinned version and SHA-256 this uses, and says how to move to a
newer Tor).

    python scripts/fetch_tor.py [--force]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from soundboard import torget  # noqa: E402

DEST = ROOT / "vendor" / "tor"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--force", action="store_true", help="download again even if present")
    args = ap.parse_args()
    if torget.installed(DEST) and not args.force:
        print(f"Tor {torget.VERSION} is already in {DEST.relative_to(ROOT)}")
        return 0
    print(f"downloading {torget.URL}")
    try:
        torget.unpack(torget.download(), DEST)
    except torget.GetError as e:
        print(f"fetch_tor: {e}", file=sys.stderr)
        return 1
    size = sum(f.stat().st_size for f in DEST.rglob("*") if f.is_file())
    print(f"Tor {torget.VERSION} unpacked into {DEST.relative_to(ROOT)} ({size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
