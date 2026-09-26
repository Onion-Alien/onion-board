"""Global hotkeys and key presses using plain Win32 APIs — no keyboard hook.

Why: the `keyboard` package installs a low-level keyboard hook, which puts this
Python process in the path of *every* keypress on the PC. When Python is busy
(e.g. starting up and decoding sounds) Windows waits on the hook, input stalls,
and keys can appear stuck (a held W in a game kept "moving" for ~10 s).

RegisterHotKey is different: Windows only notifies us when one of *our* combos
is pressed, and never waits on us, so we can't lag or block anyone's input.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import threading

from PySide6.QtCore import QObject, Signal

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY, WM_APP = 0x0312, 0x8000
MODS = {"ctrl": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT, "windows": MOD_WIN}
MOD_ALIASES = {"control": "ctrl", "win": "windows", "left windows": "windows",
               "right windows": "windows", "left ctrl": "ctrl", "right ctrl": "ctrl",
               "left alt": "alt", "right alt": "alt", "alt gr": "alt",
               "left shift": "shift", "right shift": "shift"}

# key name (as stored in config) -> virtual-key code
VK: dict[str, int] = {}
VK.update({chr(c): c for c in range(ord("A"), ord("Z") + 1)})
VK = {k.lower(): v for k, v in VK.items()}
VK.update({str(d): 0x30 + d for d in range(10)})
VK.update({f"f{i}": 0x6F + i for i in range(1, 25)})
VK.update({f"num {d}": 0x60 + d for d in range(10)})
VK.update({
    "num *": 0x6A, "num +": 0x6B, "num -": 0x6D, "num .": 0x6E, "num /": 0x6F,
    "space": 0x20, "enter": 0x0D, "tab": 0x09, "esc": 0x1B, "backspace": 0x08,
    "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23,
    "page up": 0x21, "page down": 0x22, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "pause": 0x13, "print screen": 0x2C, "scroll lock": 0x91, "caps lock": 0x14,
    "num lock": 0x90, "menu": 0x5D,
    ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF, "`": 0xC0,
    "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE,
    "play/pause media": 0xB3, "next track": 0xB0, "previous track": 0xB1,
    "volume up": 0xAF, "volume down": 0xAE, "volume mute": 0xAD,
})
ALIASES = {"escape": "esc", "return": "enter", "spacebar": "space", "del": "delete",
           "pgup": "page up", "pgdn": "page down", "prtsc": "print screen",
           "decimal": "num .", "multiply": "num *", "add": "num +", "subtract": "num -",
           "divide": "num /", "plus": "=", "minus": "-"}
NAME = {v: k for k, v in reversed(list(VK.items()))}
MODIFIER_VKS = {0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5}


def parse(combo: str) -> tuple[int, int] | None:
    """'ctrl+alt+s' -> (modifier flags, vk). None if it can't be parsed."""
    mods, vk = 0, None
    for raw in combo.lower().split("+"):
        p = raw.strip()
        if not p:
            p = "+"   # "ctrl++" style
        p = MOD_ALIASES.get(p, p)
        if p in MODS:
            mods |= MODS[p]
            continue
        p = ALIASES.get(p, p)
        if p in VK:
            vk = VK[p]
        elif p.startswith("vk") and p[2:]:
            try:
                vk = int(p[2:], 16)
            except ValueError:
                return None
        else:
            return None
    return (mods, vk) if vk is not None else None


def combo_name(mods: int, vk: int) -> str:
    parts = [n for n, f in (("ctrl", MOD_CONTROL), ("alt", MOD_ALT), ("shift", MOD_SHIFT),
                            ("windows", MOD_WIN)) if mods & f]
    parts.append(NAME.get(vk, f"vk{vk:02x}"))
    return "+".join(parts)


class _MSG(ctypes.Structure):
    _fields_ = [("hwnd", wt.HWND), ("message", wt.UINT), ("wParam", wt.WPARAM),
                ("lParam", wt.LPARAM), ("time", wt.DWORD), ("pt", wt.POINT)]


class Hotkeys(QObject):
    """RegisterHotKey on a private thread; emits `fired(action)` on the Qt thread."""
    fired = Signal(str)

    def __init__(self):
        super().__init__()
        self.failed: list[str] = []      # combos another app already owns
        self._pending: dict[str, str] | None = None
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._tid = 0
        threading.Thread(target=self._loop, daemon=True, name="hotkeys").start()
        self._ready.wait(2)

    def register(self, mapping: dict[str, str]):
        """mapping: combo -> action. Replaces all current hotkeys."""
        with self._lock:
            self._pending = dict(mapping)
        user32.PostThreadMessageW(self._tid, WM_APP, 0, 0)

    def pause(self):
        """Release every hotkey (while capturing a new one)."""
        self.register({})

    def stop(self):
        user32.PostThreadMessageW(self._tid, 0x0012, 0, 0)   # WM_QUIT

    def _loop(self):
        self._tid = kernel32.GetCurrentThreadId()
        msg = _MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)   # create the queue
        self._ready.set()
        actions: dict[int, str] = {}
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                act = actions.get(msg.wParam)
                if act:
                    self.fired.emit(act)
            elif msg.message == WM_APP:
                with self._lock:
                    mapping, self._pending = self._pending, None
                if mapping is None:
                    continue
                for hid in actions:
                    user32.UnregisterHotKey(None, hid)
                actions.clear()
                failed = []
                for i, (combo, act) in enumerate(mapping.items(), start=1):
                    parsed = parse(combo) if combo else None
                    if not parsed:
                        continue
                    mods, vk = parsed
                    if user32.RegisterHotKey(None, i, mods | MOD_NOREPEAT, vk):
                        actions[i] = act
                    else:
                        failed.append(combo)
                self.failed = failed
        for hid in actions:
            user32.UnregisterHotKey(None, hid)


# ---------------------------------------------------------------- key presses (PTT)

KEYEVENTF_KEYUP, KEYEVENTF_EXTENDEDKEY = 0x2, 0x1
_EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x6F, 0xA3, 0xA5}


def _send(vk: int, up: bool):
    scan = user32.MapVirtualKeyW(vk, 0)
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if vk in _EXTENDED else 0)
    user32.keybd_event(vk, scan, flags, 0)


def press(combo: str) -> bool:
    """Hold a key (with its modifiers) down, e.g. a game's push-to-talk key."""
    parsed = parse(combo)
    if not parsed:
        return False
    mods, vk = parsed
    for flag, mvk in ((MOD_CONTROL, 0x11), (MOD_ALT, 0x12), (MOD_SHIFT, 0x10), (MOD_WIN, 0x5B)):
        if mods & flag:
            _send(mvk, False)
    _send(vk, False)
    return True


def release(combo: str) -> bool:
    parsed = parse(combo)
    if not parsed:
        return False
    mods, vk = parsed
    _send(vk, True)
    for flag, mvk in ((MOD_WIN, 0x5B), (MOD_SHIFT, 0x10), (MOD_ALT, 0x12), (MOD_CONTROL, 0x11)):
        if mods & flag:
            _send(mvk, True)
    return True
