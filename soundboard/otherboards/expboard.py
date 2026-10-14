"""Bring an EXP Soundboard board over: its sounds and hotkeys.

EXP Soundboard (a Java app) saves a board wherever the user picks, as JSON:

    {"soundboardEntries": [{"file": "C:\\\\Sounds\\\\airhorn.mp3",
                            "activationKeysNumbers": [17, 49]}]}

Paths are absolute; there are no names (it shows the file name), categories or
per-sound volumes. The keys are JNativeHook key codes, Java-style, in the order
they were pressed, modifiers included (16 Shift, 17 Ctrl, 18 Alt, 524 Windows).
The board it last had open is remembered in Java's Preferences, which on Windows
live in the registry (HKCU\\Software\\JavaSoft\\Prefs, with Java's own escaping of
the names and values). Older Javas wrote the file in the ANSI code page, not UTF-8.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from soundboard.otherboards import Entry, Source, vk_hotkey
from soundboard.i18n import _

MAX_BYTES = 20 * 1024 * 1024
_PREFS_KEY = r"Software\JavaSoft\Prefs\/Expenosa's /Soundboard"
_PREFS_VALUE = "last/Soundboard/Used"
_SHIFT, _CTRL, _ALT, _WIN = 16, 17, 18, 524

# JNativeHook 1.1.4 key codes that aren't already the Windows virtual-key code
_VK = {10: 0x0D, 127: 0x2E, 155: 0x2D, 154: 0x2C, 525: 0x5D, 59: 0xBA, 61: 0xBB,
       44: 0xBC, 45: 0xBD, 46: 0xBE, 47: 0xBF, 129: 0xBF, 192: 0xC0, 91: 0xDB,
       92: 0xDC, 93: 0xDD, 222: 0xDE}
_VK.update({61440 + i: 0x7C + i for i in range(12)})   # F13-F24
_SAME = (set(range(65, 91)) | set(range(48, 58)) | set(range(96, 108))
         | set(range(109, 124)) | {8, 9, 19, 20, 27, 32, 33, 34, 35, 36, 37, 38, 39, 40,
                                   144, 145})


def java_pref(s: str) -> str:
    """Undo Java's escaping of a Preferences value in the registry: '/D:///Sounds//x'
    -> 'D:\\Sounds\\x' (a '/' before a capital, '//' for '\\', '\\' for '/', /uXXXX)."""
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "/" and i + 1 < len(s):
            n = s[i + 1]
            if n == "u" and re.fullmatch(r"[0-9a-fA-F]{4}", s[i + 2:i + 6]):
                out.append(chr(int(s[i + 2:i + 6], 16)))
                i += 6
                continue
            out.append("\\" if n == "/" else n)
            i += 2
            continue
        out.append("/" if c == "\\" else c)
        i += 1
    return "".join(out)


def _last_board() -> Path | None:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _PREFS_KEY) as k:
            raw, _ = winreg.QueryValueEx(k, _PREFS_VALUE)
    except (ImportError, OSError):
        return None
    p = Path(java_pref(str(raw)))
    return p if p.is_file() else None


def _is_board(p: Path) -> bool:
    try:
        if p.stat().st_size > MAX_BYTES:
            return False
        with open(p, "rb") as f:
            return b'"soundboardEntries"' in f.read(4096)
    except OSError:
        return False


def default_board() -> Path | None:
    """The board EXP Soundboard last had open; else one saved straight in Documents or
    on the Desktop, where its Save dialog starts (the newest one)."""
    if p := _last_board():
        return p
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    boards = []
    for d in (home / "Documents", home / "Desktop"):
        try:
            boards += [p for p in d.glob("*.json") if _is_board(p)]
        except OSError:
            pass
    return max(boards, key=lambda p: p.stat().st_mtime, default=None)


def hotkey(codes) -> str:
    """EXP's activationKeysNumbers -> 'ctrl+1'; "" when it's none, a key we can't map,
    or more than one key besides the modifiers (Windows hotkeys have one)."""
    if not isinstance(codes, list):
        return ""
    keys = [c for c in codes if isinstance(c, int) and c not in (_SHIFT, _CTRL, _ALT, _WIN)]
    if len(keys) != 1:
        return ""
    k = keys[0]
    vk = _VK.get(k, k if k in _SAME else 0)
    return vk_hotkey(vk, ctrl=_CTRL in codes, alt=_ALT in codes, shift=_SHIFT in codes,
                     win=_WIN in codes)


def read(path: str | Path) -> list[Entry]:
    """The sounds on an EXP Soundboard board, in its order. Raises ValueError with a
    plain message if it isn't one."""
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError(_("that file is too big to be an EXP Soundboard board"))
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("mbcs" if os.name == "nt" else "cp1252", errors="replace")
    try:
        data = json.loads(text)
    except ValueError as e:
        raise ValueError(_("that isn't an EXP Soundboard board (it couldn't be read)")) from e
    rows = data.get("soundboardEntries") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ValueError(_("that isn't an EXP Soundboard board"))
    out = []
    for r in rows:
        f = r.get("file") if isinstance(r, dict) else None
        if not isinstance(f, str) or not f.strip():
            continue
        p = Path(f)
        out.append(Entry(str(p), p.stem.strip()[:40] or "Sound",
                         hotkey(r.get("activationKeysNumbers")), exists=p.is_file()))
    return out


# its boards are plain .json: a dropped one is only taken for one when it says so
SOURCE = Source("expboard", "EXP Soundboard", (".json",), default_board, read,
                claims=lambda f: _is_board(Path(f)))
