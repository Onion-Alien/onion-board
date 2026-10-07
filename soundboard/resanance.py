"""Bring a Resanance board over: its sounds, names, tabs and hotkeys.

Resanance (a .NET soundboard) keeps its board in %APPDATA%\\Resanance\\data\\Resanance.db,
a LiteDB 5 database with one collection, "sounds":

    {_id: 6, filepath: "C:\\…\\airhorn.mp3", shortname: "airhorn.mp3", hot: "8",
     mod: "Ctrl", vol: 100.0, index: 5, profile: "Sounds", rand: false, loop: false}

`hot` / `mod` are .NET Keys names ("F1", "A", "8", "NumPad1", "Oemplus"; "Ctrl",
"Alt", "Shift", "None"), `profile` is the tab, `index` the order. Its built-in
controls are rows too, with "Stop Playback" as their filepath: only rows pointing at
a sound file are taken.

Read here without LiteDB: the file is 8 KB pages, and each data page lists its live
blocks in a slot table at its end (deleted rows are left out of it, though their
bytes may still be there). A document is BSON in a chain of blocks. Changes not yet
written back into the file sit in Resanance-log.db, whose committed pages are laid
over the file's. It's read from a copy in memory, so a running Resanance is fine.
"""
from __future__ import annotations

import os
import re
import struct
from pathlib import Path

from soundboard.otherboards import Entry, Source, vk_hotkey
from soundboard.i18n import _

PAGE = 8192
MAGIC = b"** This is a LiteDB file **"
MAX_BYTES = 64 * 1024 * 1024
_DATA = 4   # page type

# .NET Keys names (their values are Windows virtual-key codes) for keys whose name
# isn't the key itself; letters, digits and F1-F24 are worked out
_KEYS = {
    "space": 0x20, "enter": 0x0D, "return": 0x0D, "tab": 0x09, "escape": 0x1B,
    "back": 0x08, "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "prior": 0x21, "pagedown": 0x22, "next": 0x22, "up": 0x26,
    "down": 0x28, "left": 0x25, "right": 0x27, "pause": 0x13, "scroll": 0x91,
    "capslock": 0x14, "capital": 0x14, "numlock": 0x90, "printscreen": 0x2C,
    "snapshot": 0x2C, "apps": 0x5D, "multiply": 0x6A, "add": 0x6B, "subtract": 0x6D,
    "decimal": 0x6E, "divide": 0x6F, "oem1": 0xBA, "oemsemicolon": 0xBA,
    "oemplus": 0xBB, "oemcomma": 0xBC, "oemminus": 0xBD, "oemperiod": 0xBE,
    "oem2": 0xBF, "oemquestion": 0xBF, "oem3": 0xC0, "oemtilde": 0xC0,
    "oem4": 0xDB, "oemopenbrackets": 0xDB, "oem5": 0xDC, "oempipe": 0xDC,
    "oem6": 0xDD, "oemclosebrackets": 0xDD, "oem7": 0xDE, "oemquotes": 0xDE,
    "oem102": 0xE2, "oembackslash": 0xE2, "mediaplaypause": 0xB3,
    "medianexttrack": 0xB0, "mediaprevioustrack": 0xB1, "volumeup": 0xAF,
    "volumedown": 0xAE, "volumemute": 0xAD,
}


def default_db() -> Path | None:
    """Resanance's database, if Resanance has been used on this PC."""
    base = os.environ.get("APPDATA")
    if not base:
        return None
    p = Path(base) / "Resanance" / "data" / "Resanance.db"
    return p if p.is_file() else None


def key_code(name: str) -> int:
    """A .NET Keys name -> virtual-key code (0 if none / unknown)."""
    n = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    if len(n) == 1 and (n.isalpha() or n.isdigit()):
        return ord(n.upper())
    if len(n) == 2 and n[0] == "d" and n[1].isdigit():
        return ord(n[1])                       # .NET's own name for the digit keys
    if m := re.fullmatch(r"f([1-9]|1[0-9]|2[0-4])", n):
        return 0x6F + int(m.group(1))
    if m := re.fullmatch(r"numpad([0-9])", n):
        return 0x60 + int(m.group(1))
    return _KEYS.get(n, 0)


def hotkey(hot: str, mod: str) -> str:
    """Resanance's hot + mod ("8", "Ctrl"; "Ctrl, Shift" too) -> 'ctrl+8'."""
    mods = {m for m in re.split(r"[^a-z]+", (mod or "").lower()) if m}
    return vk_hotkey(key_code(hot), ctrl=bool(mods & {"ctrl", "control"}),
                     alt=bool(mods & {"alt", "menu"}), shift="shift" in mods,
                     win=bool(mods & {"win", "lwin", "rwin", "windows"}))


# ---------------------------------------------------------------- LiteDB 5 pages
def _pages(raw: bytes) -> dict[int, bytes]:
    return {struct.unpack_from("<I", raw, i)[0]: raw[i:i + PAGE]
            for i in range(0, len(raw) - PAGE + 1, PAGE)}


def _with_log(pages: dict[int, bytes], log: bytes) -> dict[int, bytes]:
    """Lay the log file's committed transactions over the data file's pages."""
    txs: dict[int, list[bytes]] = {}
    done = set()
    order = []
    for i in range(0, len(log) - PAGE + 1, PAGE):
        p = log[i:i + PAGE]
        tx = struct.unpack_from("<I", p, 14)[0]
        if tx not in txs:
            txs[tx] = []
            order.append(tx)
        txs[tx].append(p)
        if p[18]:
            done.add(tx)
    for tx in order:
        if tx in done:
            for p in txs[tx]:
                pages[struct.unpack_from("<I", p, 0)[0]] = p
    return pages


def _block(pages: dict[int, bytes], pid: int, slot: int) -> tuple[bool, int, int, bytes]:
    """(continues another block, next page id, next slot, data) of one data block."""
    p = pages[pid]
    length, pos = struct.unpack_from("<HH", p, PAGE - (slot + 1) * 4)
    if not pos or pos + length > PAGE - 4 or length < 6:
        raise ValueError("damaged")
    b = p[pos:pos + length]
    return bool(b[0]), struct.unpack_from("<I", b, 1)[0], b[5], b[6:]


def _documents(pages: dict[int, bytes]):
    for pid, p in sorted(pages.items()):
        if p[4] != _DATA:
            continue
        top = p[30]
        for slot in range(top + 1 if top != 255 else 0):
            length, pos = struct.unpack_from("<HH", p, PAGE - (slot + 1) * 4)
            if not pos:
                continue    # deleted
            try:
                extend, nxt, nslot, data = _block(pages, pid, slot)
                if extend:
                    continue    # the middle of a document read from its first block
                seen = {(pid, slot)}
                while nxt != 0xFFFFFFFF and (nxt, nslot) not in seen and nxt in pages:
                    seen.add((nxt, nslot))
                    _e, nxt2, nslot2, more = _block(pages, nxt, nslot)
                    data += more
                    nxt, nslot = nxt2, nslot2
                yield _bson(data, 0)[0]
            except (ValueError, struct.error, IndexError, KeyError, UnicodeDecodeError):
                continue    # one unreadable row doesn't lose the rest


def _cstr(b: bytes, i: int) -> tuple[str, int]:
    j = b.index(b"\0", i)
    return b[i:j].decode("utf-8"), j + 1


def _bson(b: bytes, i: int) -> tuple[dict, int]:
    """One BSON document at b[i:] -> (dict, the index after it). Only the types a
    LiteDB row holds; anything else stops the document there."""
    size = struct.unpack_from("<i", b, i)[0]
    end = i + size
    if size < 5:   # a damaged length mustn't send the reader backwards (forever)
        raise ValueError("bad BSON document length")
    i += 4
    out: dict = {}
    while i < end - 1:
        t = b[i]
        name, i = _cstr(b, i + 1)
        if t == 0x01:
            out[name] = struct.unpack_from("<d", b, i)[0]
            i += 8
        elif t == 0x02:
            n = struct.unpack_from("<i", b, i)[0]
            if n < 1 or i + 4 + n > end:
                raise ValueError("bad BSON string length")
            out[name] = b[i + 4:i + 3 + n].decode("utf-8")
            i += 4 + n
        elif t in (0x03, 0x04):
            out[name], i = _bson(b, i)
        elif t == 0x05:
            n = struct.unpack_from("<i", b, i)[0]
            if n < 0 or i + 5 + n > end:
                raise ValueError("bad BSON binary length")
            i += 5 + n
        elif t == 0x07:
            i += 12
        elif t == 0x08:
            out[name] = bool(b[i])
            i += 1
        elif t in (0x09, 0x12):
            out[name] = struct.unpack_from("<q", b, i)[0]
            i += 8
        elif t == 0x0A:
            out[name] = None
        elif t == 0x10:
            out[name] = struct.unpack_from("<i", b, i)[0]
            i += 4
        elif t == 0x13:
            i += 16
        else:
            break
    return out, end


# ---------------------------------------------------------------- the board
def read(path: str | Path) -> list[Entry]:
    """The sounds on a Resanance board, tab by tab in its order. Raises ValueError
    with a plain message if it isn't one."""
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError(_("that file is too big to be a Resanance board"))
    raw = path.read_bytes()
    if raw[32:32 + len(MAGIC)] != MAGIC:
        raise ValueError(_("that isn't a Resanance board"))
    pages = _pages(raw)
    log = path.with_name(path.stem + "-log" + path.suffix)
    if log.is_file() and log.stat().st_size <= MAX_BYTES:
        pages = _with_log(pages, log.read_bytes())
    rows = [d for d in _documents(pages)
            if isinstance(d.get("filepath"), str) and ("\\" in d["filepath"]
                                                       or "/" in d["filepath"])]
    tabs: list[str] = []
    for d in rows:
        tab = str(d.get("profile") or "").strip()
        if tab and tab not in tabs:
            tabs.append(tab)

    def order(d):
        tab = str(d.get("profile") or "").strip()
        idx = d.get("index")
        return (tabs.index(tab) if tab in tabs else -1,
                idx if isinstance(idx, int) else 1 << 30, d.get("_id") or 0)

    out = []
    for d in sorted(rows, key=order):
        p = Path(d["filepath"])
        name = str(d.get("shortname") or "").strip() or p.name
        if name.lower().endswith(p.suffix.lower()) and p.suffix:
            name = name[:-len(p.suffix)]   # it's the file name, extension and all
        tab = str(d.get("profile") or "").strip()[:40]
        # one tab is everything there is: no need for it as a category here
        tags = [tab] if tab and len(tabs) > 1 else []
        out.append(Entry(str(p), name.strip()[:40] or p.stem,
                         hotkey(str(d.get("hot") or ""), str(d.get("mod") or "")),
                         tags, exists=p.is_file()))
    return out


SOURCE = Source("resanance", "Resanance", ("resanance.db",), default_db, read)
