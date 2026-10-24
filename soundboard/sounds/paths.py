"""Where the library keeps its files: the app folder in %APPDATA% and the sounds,
cache, pad pictures and config.json in it.

Code reads these as `paths.X` when it runs, not `from paths import X`: tests (and the
library's own moves) point them at another folder.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from soundboard.core import profile
from soundboard.win import winpath


# usable_dir: spelled out through any folder link Windows won't follow (soundboard.win.winpath)
# %APPDATA%\OnionBoard, or OnionBoard-dev for a source copy in the temp folder (core/profile.py)
APP_DIR = winpath.usable_dir(profile.base())
# from when this app was called Soundboard; see config.migrate_from_soundboard()
OLD_APP_DIR = winpath.usable_dir(Path(os.environ.get("APPDATA", Path.home())) / "Soundboard")
SOUNDS_DIR = winpath.usable_dir(APP_DIR / "sounds")
CACHE_DIR = winpath.usable_dir(APP_DIR / "cache")
THUMBS_DIR = winpath.usable_dir(APP_DIR / "thumbs")   # pad pictures (soundboard.sounds.thumbs)
CONFIG_PATH = APP_DIR / "config.json"
# where install-vbcable.ps1 lives: installer/ in a source checkout, or the frozen
# app's _internal folder (PyInstaller's _MEIPASS; build.ps1 bundles it at its root)
RESOURCE_DIR = (Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS")   # pyright: ignore[reportAttributeAccessIssue]
                else Path(__file__).resolve().parents[2] / "installer")
