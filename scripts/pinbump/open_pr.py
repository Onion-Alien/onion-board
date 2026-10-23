"""Open the PRs the pin-bump check job left (common.open_pr with PINBUMP_OUT): run by
.github/workflows/pin-bumps.yml's `open` job, the only one with a token that can push.
It runs nothing that was downloaded: it copies the edited pin files back into this
checkout, only ones a checker may edit (PINNED), and opens each PR.

    python scripts/pinbump/open_pr.py <folder with one bundle per checker>"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

# the files the checkers rewrite: a bundle naming any other is refused
PINNED = {"soundboard/online/torget.py", "soundboard/online/ffmpegget.py",
          "soundboard/online/pyget.py", "scripts/buildtools/fetch_qjs.py",
          "pins/yt-dlp.json"}
NAME = re.compile(r"[a-z0-9-]{1,30}")
VERSION = re.compile(r"[0-9A-Za-z.+-]{1,60}")


def main(folder: str) -> int:
    bundles = sorted(p.parent for p in Path(folder).glob("*/pr.json"))
    if not bundles:
        print("nothing to open")
        return 0
    failed, start = 0, common.git("rev-parse", "HEAD")
    for b in bundles:
        pr = json.loads((b / "pr.json").read_text(encoding="utf-8"))
        name, version, files = pr["name"], pr["version"], pr["files"]
        if not (NAME.fullmatch(name) and VERSION.fullmatch(version)
                and files and set(files) <= PINNED):
            print(f"::error::{b.name}: a bundle this job won't open: {name} {version} {files}")
            failed = 1
            continue
        if common.already_open(name, version):
            print(f"{name} {version}: its PR is waiting already")
            continue
        common.git("switch", "--detach", start)   # each branch from the commit checked out
        for f in files:
            (common.ROOT / f).write_bytes((b / "files" / f).read_bytes())
        common.open_pr(name, version, [common.ROOT / f for f in files], str(pr["title"]),
                       str(pr["body"]))
    return failed


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
