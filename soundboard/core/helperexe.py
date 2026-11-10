"""The app's own helper processes (YouTube downloads, slow sound renders, the computer
voice's lines) each run as their own named copy of OnionBoard.exe, so Task Manager's
Details tab shows OnionBoardDownloads.exe and so on, not four OnionBoard.exe.

build.ps1 makes the copies (scripts/buildtools/helper_exes.py): byte-for-byte the same
program, so the installer stores it once. A build without them (or a run from source)
starts the app's own exe / Python, as before."""
from __future__ import annotations

import sys
from pathlib import Path

# the helper's command-line switch (main.py) -> its exe's name
HELPERS: dict[str, str] = {
    "--ytdl-worker": "OnionBoardDownloads",
    "--render-worker": "OnionBoardSounds",
    "--line-helper": "OnionBoardVoice",
}


def command(arg: str) -> list[str]:
    """How to start the helper that `arg` (one of HELPERS) runs."""
    if getattr(sys, "frozen", False):
        own = Path(sys.executable)
        named = own.with_name(HELPERS[arg] + own.suffix)
        return [str(named) if named.is_file() else sys.executable, arg]
    main = Path(__file__).resolve().parents[2] / "main.py"
    return [sys.executable, str(main), arg]
