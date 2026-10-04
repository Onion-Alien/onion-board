"""Bring a Soundux board over: its sounds, names, tabs and hotkeys.

Soundux (open source) keeps everything in %APPDATA%\\Soundux\\config.json:

    {"data": {"tabs": [{"id": 1, "name": "Memes", "path": "D:\\\\Memes",
                        "sounds": [{"name": "airhorn", "path": "D:\\\\Memes\\\\airhorn.mp3",
                                    "hotkeys": [162, 49], "localVolume": 50, …}]}]},
     "settings": {…}}

Each tab is a folder it watches; `hotkeys` are the Windows virtual-key codes its
keyboard hook saw, modifiers included (left/right ones: 162 = left Ctrl). Some
versions store each key as {"key": 49, "type": 0} (type 0 = keyboard; others are
mouse buttons and MIDI notes, which aren't keys we can register).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from soundboard.otherboards import Entry, Source, vk_hotkey

MAX_BYTES = 50 * 1024 * 1024
_CTRL = {0x11, 0xA2, 0xA3}
_ALT = {0x12, 0xA4, 0xA5}
_SHIFT = {0x10, 0xA0, 0xA1}
_WIN = {0x5B, 0x5C}


def default_config() -> Path | None:
    """Soundux's config, if Soundux has been used on this PC."""
    base = os.environ.get("APPDATA")
    if not base:
        return None
    p = Path(base) / "Soundux" / "config.json"
    return p if p.is_file() else None


def hotkey(keys) -> str:
    """Soundux's hotkeys list -> 'ctrl+1'; "" for none, a mouse button / MIDI note, or
    more than one key besides the modifiers (Windows hotkeys have one)."""
    if not isinstance(keys, list):
        return ""
    codes = []
    for k in keys:
        if isinstance(k, dict):
            if k.get("type", 0) not in (0, "keyboard"):
                return ""
            k = k.get("key")
        if not isinstance(k, int) or isinstance(k, bool):
            return ""
        codes.append(k)
    main = [c for c in codes if c not in _CTRL | _ALT | _SHIFT | _WIN]
    if len(main) != 1:
        return ""
    c = set(codes)
    return vk_hotkey(main[0], ctrl=bool(c & _CTRL), alt=bool(c & _ALT),
                     shift=bool(c & _SHIFT), win=bool(c & _WIN))


def read(path: str | Path) -> list[Entry]:
    """The sounds on a Soundux board, tab by tab. Raises ValueError with a plain
    message if it isn't one."""
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("that file is too big to be a Soundux config")
    try:
        data = json.loads(path.read_bytes().decode("utf-8-sig", errors="replace"))
    except ValueError as e:
        raise ValueError("that isn't a Soundux config (it couldn't be read)") from e
    inner = data.get("data") if isinstance(data, dict) else None
    tabs = inner.get("tabs") if isinstance(inner, dict) else None
    if not isinstance(tabs, list):
        raise ValueError("that isn't a Soundux config")
    tabs = [t for t in tabs if isinstance(t, dict) and isinstance(t.get("sounds"), list)]
    out = []
    for t in tabs:
        tab = str(t.get("name") or "").strip()[:40]
        for s in t["sounds"]:
            f = s.get("path") if isinstance(s, dict) else None
            if not isinstance(f, str) or not f.strip():
                continue
            p = Path(f)
            name = str(s.get("name") or "").strip()
            if p.suffix and name.lower().endswith(p.suffix.lower()):
                name = name[:-len(p.suffix)]
            out.append(Entry(str(p), name.strip()[:40] or p.stem,
                             hotkey(s.get("hotkeys")),
                             [tab] if tab and len(tabs) > 1 else [], exists=p.is_file()))
    return out


def _is_config(f: str) -> bool:
    try:
        with open(f, "rb") as fh:
            head = fh.read(65536)
    except OSError:
        return False
    return b'"tabs"' in head and b'"soundIdCounter"' in head


# its config is a plain config.json: a dropped one is only taken when it is one
SOURCE = Source("soundux", "Soundux", (".json",), default_config, read, claims=_is_config)
