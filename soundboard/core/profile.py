"""The app's own folder under %APPDATA%: settings, sounds and the decoded-audio cache.

The installed app and a source checkout use %APPDATA%\\OnionBoard. A source copy run
from inside the temp folder (a throwaway git worktree made to try a change) uses
%APPDATA%\\OnionBoard-dev instead: a branch under test that prunes the cache or rewrites
the settings its own way can't touch the real profile (one emptied a whole library's
cache, and the next real launch decoded every sound again). ONIONBOARD_PROFILE_DIR,
when set, names the folder outright (any copy, installed or not).

Small on purpose (os, sys, tempfile): main.py's breadcrumb (soundboard.core.bootmark)
and the splash read it before the sound library is imported."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ENV = "ONIONBOARD_PROFILE_DIR"
NAME = "OnionBoard"
DEV_NAME = "OnionBoard-dev"
ROOT = Path(__file__).resolve().parents[2]   # the checkout (or the frozen app's folder)


def _inside(path: Path, folder: str) -> bool:
    try:
        p = os.path.normcase(os.path.realpath(path))
        f = os.path.normcase(os.path.realpath(folder))
    except (OSError, ValueError):
        return False
    return p == f or p.startswith(f.rstrip("\\/") + os.sep)


def scratch_copy(root: Path | None = None) -> bool:
    """A source copy (not the built app) kept in the temp folder."""
    return (not getattr(sys, "frozen", False)
            and _inside(ROOT if root is None else root, tempfile.gettempdir()))


def base() -> Path:
    """The profile folder, not yet spelled out through folder links (callers wrap it in
    winpath.usable_dir)."""
    named = os.environ.get(ENV, "").strip()
    if named:
        return Path(named)
    appdata = Path(os.environ.get("APPDATA", Path.home()))
    return appdata / (DEV_NAME if scratch_copy() else NAME)
