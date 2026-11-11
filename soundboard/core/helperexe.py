"""The app's own helper processes (YouTube downloads, slow sound renders, the computer
voice's lines) each run as their own named program, so Task Manager shows
"Onion Board download helper" and so on, not three more "Onion Board"s.

build.ps1 makes them (scripts/buildtools/helper_exes.py): a small launcher with its own
name and description (<name>.exe) that runs the app's program from a copy of
OnionBoard.exe beside it (<name>.pkg). A build without both files (or a run from source)
starts the app's own exe / Python, as before."""
from __future__ import annotations

import sys
from pathlib import Path

# the helper's command-line switch (main.py) -> (its exe's name, Task Manager's name)
HELPERS: dict[str, tuple[str, str]] = {
    "--ytdl-worker": ("OnionBoardDownloads", "Onion Board download helper"),
    "--render-worker": ("OnionBoardSounds", "Onion Board sound helper"),
    "--line-helper": ("OnionBoardVoice", "Onion Board voice helper"),
}


def command(arg: str) -> list[str]:
    """How to start the helper that `arg` (one of HELPERS) runs."""
    if getattr(sys, "frozen", False):
        own = Path(sys.executable)
        named = own.with_name(HELPERS[arg][0] + own.suffix)
        ok = named.is_file() and named.with_suffix(".pkg").is_file()
        return [str(named) if ok else sys.executable, arg]
    main = Path(__file__).resolve().parents[2] / "main.py"
    return [sys.executable, str(main), arg]
