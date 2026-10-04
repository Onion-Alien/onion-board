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
from pathlib import Path

from soundboard.otherboards import Entry, Source, vk_hotkey

LIST_NAME = "soundlist.spl"
MAX_BYTES = 50 * 1024 * 1024   # a list of tens of thousands of sounds is ~10 MB

# keyModifiers, as Windows' RegisterHotKey takes them (checked against Soundpad 4.0.35's
# own Hotkey column: 1 Alt, 2 Ctrl, 4 Shift, 8 Win)
_ALT, _CTRL, _SHIFT, _WIN = 0x1, 0x2, 0x4, 0x8


def default_list() -> Path | None:
    """Soundpad's working sound list, if Soundpad has been used on this PC."""
    base = os.environ.get("APPDATA")
    if not base:
        return None
    p = Path(base) / "Leppsoft" / LIST_NAME
    return p if p.is_file() else None


def hotkey(key: str | None, mods: str | None) -> str:
    """Soundpad's key (a Windows virtual-key code) + keyModifiers -> 'ctrl+1'."""
    try:
        vk, m = int(key or 0), int(mods or 0)
    except ValueError:
        return ""
    return vk_hotkey(vk, ctrl=bool(m & _CTRL), alt=bool(m & _ALT), shift=bool(m & _SHIFT),
                     win=bool(m & _WIN))


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
    entries = [e for e in entries if e.path]
    # its home category ("My Sounds") has every sound in it: no use as a category here
    every = set.intersection(*(set(e.tags) for e in entries)) if entries else set()
    for e in entries:
        e.tags = [t for t in e.tags if t not in every]
    return entries


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


SOURCE = Source("soundpad", "Soundpad", (".spl",), default_list, read)
