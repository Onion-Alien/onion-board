"""Bring a Soundpad board over: its sound list, names, categories and hotkeys.

Soundpad keeps the list it has open in %APPDATA%\\Leppsoft\\soundlist.spl (saved
every so often and when it closes), and "File > Save sound list as…" writes the
same XML anywhere. It only points at the sound files, which are the user's own;
importing copies them into our library like any other file. Nothing is read
unless the user asks for an import, and nothing of Soundpad's is changed.

    <Soundlist rel="C:\\Sounds">            rel: what relative urls are relative to
      <Sound url="a.mp3" title="A" key="49" keyModifiers="2"/>
      <Categories>
        <Category type="1" hidden="true"/>   the built-in "all sounds" list
        <Category name="Memes">
          <Sound id="0"/>                    0-based index into the Sounds above
          <Category name="Loud">…</Category> categories nest
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from soundboard.library import AUDIO_EXTS

LIST_NAME = "soundlist.spl"
MAX_BYTES = 50 * 1024 * 1024   # a list of tens of thousands of sounds is ~10 MB

# keyModifiers, as Windows' RegisterHotKey takes them (what Soundpad passes it)
_ALT, _CTRL, _SHIFT, _WIN = 0x1, 0x2, 0x4, 0x8


@dataclass
class Entry:
    path: str                 # absolute path of the sound file
    name: str
    hotkey: str = ""          # in our "ctrl+alt+s" form, "" if none or not one we know
    tags: list[str] = field(default_factory=list)   # its categories, leaf names
    exists: bool = True


def default_list() -> Path | None:
    """Soundpad's working sound list, if Soundpad has been used on this PC."""
    base = os.environ.get("APPDATA")
    if not base:
        return None
    p = Path(base) / "Leppsoft" / LIST_NAME
    return p if p.is_file() else None


def hotkey(key: str | None, mods: str | None) -> str:
    """Soundpad's key (a Windows virtual-key code) + keyModifiers -> 'ctrl+1'."""
    from soundboard import winkeys   # Win32; only needed once there's a key
    try:
        vk, m = int(key or 0), int(mods or 0)
    except ValueError:
        return ""
    if not 0 < vk < 0xFF or vk in winkeys.MODIFIER_VKS or vk in (1, 2, 4, 5, 6):
        return ""   # nothing, a bare modifier, or a mouse button (not a key we register)
    flags = ((winkeys.MOD_ALT if m & _ALT else 0) | (winkeys.MOD_CONTROL if m & _CTRL else 0)
             | (winkeys.MOD_SHIFT if m & _SHIFT else 0) | (winkeys.MOD_WIN if m & _WIN else 0))
    return winkeys.combo_name(flags, vk)


def read(path: str | Path) -> list[Entry]:
    """The sounds in a Soundpad list, in its order. Raises ValueError with a plain
    message if it isn't one."""
    path = Path(path)
    try:
        if path.stat().st_size > MAX_BYTES:
            raise ValueError("that file is too big to be a Soundpad sound list")
        root = ET.fromstring(path.read_bytes())
    except ET.ParseError as e:
        raise ValueError("that isn't a Soundpad sound list (it couldn't be read)") from e
    if root.tag != "Soundlist":
        raise ValueError("that isn't a Soundpad sound list")
    base = Path(root.get("rel") or path.parent)
    entries: list[Entry] = []
    for s in root.findall("Sound"):
        url = (s.get("url") or "").strip()
        if not url:
            entries.append(Entry("", "", exists=False))   # keeps the ids lined up
            continue
        p = Path(url)
        if not p.is_absolute():
            p = base / p
        name = (s.get("title") or "").strip() or p.stem
        artist = (s.get("artist") or "").strip()
        if artist and artist.lower() not in name.lower():
            name = f"{artist} - {name}"
        entries.append(Entry(str(p), name[:40], hotkey(s.get("key"), s.get("keyModifiers")),
                             exists=p.is_file()))
    cats = root.find("Categories")
    if cats is not None:
        _tag(cats, entries)
    return [e for e in entries if e.path]


def _tag(node, entries: list[Entry]):
    for cat in node.findall("Category"):
        name = (cat.get("name") or "").strip()[:40]
        if name and cat.get("type") is None:   # typed ones are Soundpad's own lists
            for s in cat.findall("Sound"):
                try:
                    e = entries[int(s.get("id", ""))]
                except (ValueError, IndexError):
                    continue
                if name not in e.tags:
                    e.tags.append(name)
        _tag(cat, entries)


def importable(entries: list[Entry]) -> tuple[list[Entry], list[Entry]]:
    """(the ones whose file is there and plays, the ones that are missing or not audio)."""
    ok, bad = [], []
    for e in entries:
        (ok if e.exists and Path(e.path).suffix.lower() in AUDIO_EXTS else bad).append(e)
    return ok, bad
