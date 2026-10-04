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
import logging
import threading

from PySide6.QtCore import QObject, Signal

from soundboard import midi

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY, WM_APP, WM_TIMER = 0x0312, 0x8000, 0x0113
HELD_POLL_MS = 25     # while a hotkey is held: how often we look for it being let go
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
           "divide": "num /", "plus": "=", "+": "=", "minus": "-"}
NAME = {v: k for k, v in reversed(list(VK.items()))}
NAME[0x6B] = "add"   # "num +" would clash with the "+" between keys in a combo
MODIFIER_VKS = {0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5}


def parse(combo: str) -> tuple[int, int] | None:
    """'ctrl+alt+s' -> (modifier flags, vk). None if it can't be parsed."""
    mods, vk = 0, None
    combo = combo.lower().replace("num +", "add")   # saved by older versions
    parts = combo.split("+")
    if len(parts) >= 2 and parts[-1] == "" and parts[-2] == "":
        parts = parts[:-2] + ["+"]   # "ctrl++" = ctrl and the + key
    for raw in parts:
        p = raw.strip()
        if not p:
            return None
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


user32.SetTimer.argtypes = (wt.HWND, ctypes.c_size_t, wt.UINT, ctypes.c_void_p)
user32.SetTimer.restype = ctypes.c_size_t
user32.KillTimer.argtypes = (wt.HWND, ctypes.c_size_t)


class _MSG(ctypes.Structure):
    _fields_ = [("hwnd", wt.HWND), ("message", wt.UINT), ("wParam", wt.WPARAM),
                ("lParam", wt.LPARAM), ("time", wt.DWORD), ("pt", wt.POINT)]


class Hotkeys(QObject):
    """RegisterHotKey on a private thread; emits `fired(action)` on the Qt thread, and
    `released(action)` when that key (or MIDI pad) is let go again, for hold-to-play.

    Combos starting `midi:` are MIDI pads (soundboard.midi), handled by `self.midi`.

    `failed_changed(list)` is emitted (on the Qt thread) after every `register`
    with the combos another program already owns."""
    fired = Signal(str)
    released = Signal(str)
    failed_changed = Signal(list)

    def __init__(self, midi_in: midi.MidiIn | None = None):
        super().__init__()
        self.failed: list[str] = []      # combos another app already owns (last register)
        self.midi = midi_in or midi.MidiIn()
        self._midi_map: dict[str, str] = {}
        self.midi.pressed.connect(self._midi_pressed)
        self.midi.released.connect(self._midi_released)
        self._pending: dict[str, str] | None = None
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._tid = 0
        threading.Thread(target=self._loop, daemon=True, name="hotkeys").start()
        if not self._ready.wait(2):
            log.error("hotkey thread didn't start; global hotkeys won't work this session")

    @property
    def alive(self) -> bool:
        return self._tid != 0

    def register(self, mapping: dict[str, str]):
        """mapping: combo -> action. Replaces all current hotkeys."""
        self._midi_map = {c: a for c, a in mapping.items() if midi.is_midi(c)}
        self.midi.want({p[2] for p in map(midi.parse, self._midi_map) if p})
        with self._lock:
            self._pending = {c: a for c, a in mapping.items() if not midi.is_midi(c)}
        if not self._tid or not user32.PostThreadMessageW(self._tid, WM_APP, 0, 0):
            log.error("can't reach the hotkey thread (error %d)", ctypes.get_last_error())

    def pause(self):
        """Release every hotkey (while capturing a new one)."""
        self.register({})

    def stop(self):
        self.midi.close_all()
        user32.PostThreadMessageW(self._tid, 0x0012, 0, 0)   # WM_QUIT

    def _midi_pressed(self, combo: str):
        act = self._midi_map.get(combo)
        if act:
            self.fired.emit(act)

    def _midi_released(self, combo: str):
        act = self._midi_map.get(combo)
        if act:
            self.released.emit(act)

    def _loop(self):
        actions: dict[int, tuple[str, int]] = {}   # hotkey id -> (action, vk)
        self._held: dict[int, str] = {}            # vk -> action, until let go
        self._timer = 0
        try:
            self._tid = kernel32.GetCurrentThreadId()
            msg = _MSG()
            user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)   # create the queue
            self._ready.set()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                try:
                    self._handle(msg, actions)
                except Exception:  # noqa: BLE001 - one bad message mustn't end hotkeys
                    log.exception("hotkey thread: handling message 0x%x failed", msg.message)
        except Exception:  # noqa: BLE001
            from soundboard import applog
            applog.report(where="hotkey thread")
        finally:
            self._tid = 0            # `alive` now tells the truth
            self._ready.set()        # never leave __init__ waiting on a thread that died
            for hid in actions:
                user32.UnregisterHotKey(None, hid)

    def _handle(self, msg, actions: dict[int, tuple[str, int]]):
        if msg.message == WM_HOTKEY:
            hit = actions.get(msg.wParam)
            if hit:
                act, vk = hit
                self.fired.emit(act)
                # WM_HOTKEY has no key-up: watch the key until it's let go
                self._held[vk] = act
                if not self._timer:
                    self._timer = user32.SetTimer(None, 0, HELD_POLL_MS, None)
        elif msg.message == WM_TIMER:
            for vk, act in list(self._held.items()):
                if not is_down(vk):
                    del self._held[vk]
                    self.released.emit(act)
            if not self._held and self._timer:
                user32.KillTimer(None, self._timer)
                self._timer = 0
        elif msg.message == WM_APP:
            with self._lock:
                mapping, self._pending = self._pending, None
            if mapping is None:
                return
            for hid in actions:
                user32.UnregisterHotKey(None, hid)
            actions.clear()
            failed = []
            for i, (combo, act) in enumerate(mapping.items(), start=1):
                if not combo:
                    continue
                parsed = parse(combo)
                if not parsed:
                    failed.append(combo)   # shown as not working, not silently dropped
                    continue
                mods, vk = parsed
                if user32.RegisterHotKey(None, i, mods | MOD_NOREPEAT, vk):
                    actions[i] = (act, vk)
                else:
                    failed.append(combo)
            self.failed = failed
            self.failed_changed.emit(list(failed))


# ---------------------------------------------------------------- key presses (PTT)
# SendInput (the supported API; keybd_event has been a compatibility shim since XP).
# Modifiers and the key go in one call, so a game can't observe them half-pressed.

KEYEVENTF_KEYUP, KEYEVENTF_EXTENDEDKEY = 0x2, 0x1
INPUT_KEYBOARD = 1
# the E0-prefixed keys: Page Up/Down, End, Home, arrows, Insert, Delete, Print Screen,
# Win, Menu, numpad /, Num Lock, right Ctrl / Alt
_EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2C, 0x2D, 0x2E,
             0x5B, 0x5C, 0x5D, 0x6F, 0x90, 0xA3, 0xA5}


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _U)]


user32.SendInput.argtypes = (wt.UINT, ctypes.POINTER(_INPUT), ctypes.c_int)
user32.SendInput.restype = wt.UINT


def key_char(vk: int) -> str:
    """What the key with virtual-key code `vk` types on the current keyboard layout
    ("" if nothing): VK_OEM_3 is ` on a US keyboard but ' on a UK one and ö on a
    German one."""
    code = user32.MapVirtualKeyW(vk, 2) & 0x7FFF   # MAPVK_VK_TO_CHAR; top bit = dead key
    return chr(code) if 32 < code < 0xD800 else ""


def key_input(vk: int, up: bool) -> _INPUT:
    """One keyboard INPUT record (exposed for tests; nothing is sent)."""
    inp = _INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki.wVk = vk
    inp.ki.wScan = user32.MapVirtualKeyW(vk, 0)
    ext = KEYEVENTF_EXTENDEDKEY if vk in _EXTENDED else 0
    inp.ki.dwFlags = (KEYEVENTF_KEYUP if up else 0) | ext
    return inp


def key_sequence(combo: str, up: bool) -> list[tuple[int, bool]] | None:
    """The (vk, up) events that press (or release) a combo, in order: modifiers
    down before the key, and released after it. None if the combo can't be parsed."""
    parsed = parse(combo)
    if not parsed:
        return None
    mods, vk = parsed
    mod_vks = [mvk for flag, mvk in ((MOD_CONTROL, 0x11), (MOD_ALT, 0x12),
                                     (MOD_SHIFT, 0x10), (MOD_WIN, 0x5B)) if mods & flag]
    if up:
        return [(vk, True)] + [(m, True) for m in reversed(mod_vks)]
    return [(m, False) for m in mod_vks] + [(vk, False)]


def _send_all(events: list[tuple[int, bool]]) -> bool:
    arr = (_INPUT * len(events))(*[key_input(vk, up) for vk, up in events])
    sent = user32.SendInput(len(events), arr, ctypes.sizeof(_INPUT))
    if sent != len(events):
        log.warning("SendInput sent %d of %d events (error %d)", sent, len(events),
                    ctypes.get_last_error())
        return False
    return True


def press(combo: str) -> bool:
    """Hold a key (with its modifiers) down, e.g. a game's push-to-talk key."""
    events = key_sequence(combo, up=False)
    return events is not None and _send_all(events)


def release(combo: str) -> bool:
    events = key_sequence(combo, up=True)
    return events is not None and _send_all(events)


# ---------------------------------------------------------------- overlay helpers

user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
user32.GetAsyncKeyState.restype = ctypes.c_short


def is_down(vk: int) -> bool:
    """Is this key physically held right now? (A plain state query: no hook.)"""
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


QUNS_RUNNING_D3D_FULL_SCREEN = 3


def exclusive_fullscreen() -> bool:
    """True while a game owns the screen in exclusive (D3D) fullscreen, where no
    other window can be drawn on top of it. Borderless 'fullscreen' reports False."""
    state = ctypes.c_int(0)
    try:
        hr = ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state))
    except (AttributeError, OSError):
        return False
    return hr == 0 and state.value == QUNS_RUNNING_D3D_FULL_SCREEN


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT),
                ("dwFlags", wt.DWORD), ("szDevice", wt.WCHAR * 32)]


user32.GetForegroundWindow.restype = wt.HWND
user32.MonitorFromWindow.argtypes = (wt.HWND, wt.DWORD)
user32.MonitorFromWindow.restype = wt.HANDLE
user32.GetMonitorInfoW.argtypes = (wt.HANDLE, ctypes.POINTER(_MONITORINFOEXW))


def foreground_monitor_info() -> tuple[str, tuple[int, int, int, int] | None]:
    r"""The monitor the active window (the game) is on: its GDI device name
    ('\\.\DISPLAY2') and its rectangle in native pixels (left, top, width, height),
    or ('', None) if it can't be told.

    Qt 5's QScreen.name() was this device name; Qt 6 reports the monitor's friendly
    name instead, so callers match on the rectangle (overlay.pick_screen)."""
    mon = user32.MonitorFromWindow(user32.GetForegroundWindow(), 2)   # NEAREST
    info = _MONITORINFOEXW()
    info.cbSize = ctypes.sizeof(info)
    if not mon or not user32.GetMonitorInfoW(mon, ctypes.byref(info)):
        return "", None
    r = info.rcMonitor
    return info.szDevice, (r.left, r.top, r.right - r.left, r.bottom - r.top)


def foreground_monitor() -> str:
    r"""Device name ('\\.\DISPLAY2') of the monitor the active window is on, or ''.
    Not QScreen.name() under Qt 6; see foreground_monitor_info()."""
    return foreground_monitor_info()[0]


GWL_EXSTYLE = -20
WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_TOPMOST = 0x20, 0x80, 0x8
WS_EX_LAYERED, WS_EX_NOACTIVATE = 0x80000, 0x8000000
_GetLong = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
_SetLong = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
_GetLong.argtypes = (wt.HWND, ctypes.c_int)
_GetLong.restype = ctypes.c_ssize_t
_SetLong.argtypes = (wt.HWND, ctypes.c_int, ctypes.c_ssize_t)
_SetLong.restype = ctypes.c_ssize_t
user32.SetWindowPos.argtypes = (wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, wt.UINT)
HWND_TOPMOST = wt.HWND(-1)
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x1, 0x2, 0x10, 0x40


def make_overlay(hwnd: int):
    """Turn a window into a HUD: never takes focus, even when clicked (the game keeps
    the keyboard), not in the taskbar or alt-tab."""
    h = wt.HWND(hwnd)
    ex = _GetLong(h, GWL_EXSTYLE)
    _SetLong(h, GWL_EXSTYLE, (ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_LAYERED
                              | WS_EX_TOPMOST) & ~WS_EX_TRANSPARENT)


def set_click_through(hwnd: int, on: bool):
    """Let clicks pass through the window to whatever is under it (the preview: it's
    only to look at, and under the modal Settings window a click on it just dinged)."""
    h = wt.HWND(hwnd)
    ex = _GetLong(h, GWL_EXSTYLE)
    _SetLong(h, GWL_EXSTYLE, ex | WS_EX_TRANSPARENT if on else ex & ~WS_EX_TRANSPARENT)


def raise_topmost(hwnd: int):
    """Put the window back on top without activating it (games that make themselves
    topmost can otherwise end up above it)."""
    user32.SetWindowPos(wt.HWND(hwnd), HWND_TOPMOST, 0, 0, 0, 0,
                        SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_SHOWWINDOW)
