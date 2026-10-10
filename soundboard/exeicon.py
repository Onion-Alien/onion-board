"""A program's icon, read from its .exe off the UI thread.

Qt's QFileIconProvider asks the Windows shell on the UI thread and holds the GIL
while it does: 10-15 ms a program, ~70 ms for the first one. Opening the Apps tab
with a few programs running starved the audio callbacks for that long, and a sound
playing skipped. load() runs on the thread that listed the programs (ctypes lets go
of the GIL while the shell works); the tab only turns the ready image into a pixmap.
"""
from __future__ import annotations

import ctypes
import logging
import sys
import threading
from ctypes import wintypes

from PySide6.QtGui import QImage

log = logging.getLogger(__name__)

_win = sys.platform == "win32"
_cache: dict[str, QImage | None] = {}   # path -> its icon (None: it has none)
_lock = threading.Lock()

SHGFI_ICON = 0x100
SHGFI_LARGEICON = 0x0   # the system's large size (32 px at 100 %, more when scaled)


class _SHFILEINFOW(ctypes.Structure):
    _fields_ = [("hIcon", wintypes.HANDLE), ("iIcon", ctypes.c_int),
                ("dwAttributes", wintypes.DWORD), ("szDisplayName", wintypes.WCHAR * 260),
                ("szTypeName", wintypes.WCHAR * 80)]


if _win:
    _shell32 = ctypes.WinDLL("shell32")
    _user32 = ctypes.WinDLL("user32")
    _shell32.SHGetFileInfoW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD,
                                        ctypes.POINTER(_SHFILEINFOW), wintypes.UINT,
                                        wintypes.UINT)
    _shell32.SHGetFileInfoW.restype = ctypes.c_size_t
    _user32.DestroyIcon.argtypes = (wintypes.HANDLE,)


def _read(path: str) -> QImage | None:
    sfi = _SHFILEINFOW()
    if not _shell32.SHGetFileInfoW(path, 0, ctypes.byref(sfi), ctypes.sizeof(sfi),
                                   SHGFI_ICON | SHGFI_LARGEICON) or not sfi.hIcon:
        return None
    try:
        img = QImage.fromHICON(sfi.hIcon)
    finally:
        _user32.DestroyIcon(sfi.hIcon)
    return None if img.isNull() else img


def load(paths) -> None:
    """Read the icons of `paths` not read yet (any thread but the UI's)."""
    if not _win:
        return
    for path in paths:
        if not path or path in _cache:
            continue
        try:
            img = _read(path)
        except Exception:  # noqa: BLE001 - no icon is fine: the card has a stand-in
            log.debug("no icon for %s", path, exc_info=True)
            img = None
        with _lock:
            _cache[path] = img


def known(path: str) -> bool:
    return path in _cache


def get(path: str) -> QImage | None:
    """The icon load() read for `path`, or None (not read, or it has none)."""
    with _lock:
        return _cache.get(path)
