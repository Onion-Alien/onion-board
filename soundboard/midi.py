"""MIDI pad controllers as hotkeys: an Akai LPD8 / MPD, a Launchpad, any USB MIDI
keyboard. Hitting a pad works like pressing a hotkey, so everything a hotkey can do
(play a sound, stop all, a random sound, the overlay) a pad can do too.

A pad is stored where a key combo would be, as `midi:<event>:<device>`:

    midi:note 36:LPD8        a note (the usual pad message)
    midi:cc 20:LPD8          a control change (pads in "CC" mode, buttons)
    midi:pc 3:LPD8           a program change

Windows' own MIDI API (winmm, over ctypes: no extra packages). A MIDI input can only
be open in one program at a time on most Windows drivers, so a device is opened only
while something needs it: a hotkey that uses it, or the hotkey dialog listening for a
pad. One that another program (a DAW) already has shows up in `busy`.

winmm calls back on its own thread; the Qt signals queue the events to the UI thread.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import threading

from PySide6.QtCore import QObject, QTimer, Signal

log = logging.getLogger(__name__)

PREFIX = "midi:"
KINDS = {"note": "note", "cc": "CC", "pc": "program"}
POLL_MS = 2000            # how often a missing / busy device is looked for again


def is_midi(combo: str) -> bool:
    return combo.startswith(PREFIX)


def make(kind: str, number: int, device: str) -> str:
    return f"{PREFIX}{kind} {number}:{device}"


def parse(combo: str) -> tuple[str, int, str] | None:
    """'midi:note 36:LPD8' -> ('note', 36, 'LPD8'). None if it isn't one."""
    if not is_midi(combo):
        return None
    event, _, device = combo[len(PREFIX):].partition(":")
    kind, _, num = event.partition(" ")
    if kind not in KINDS or not num.isdigit() or not device:
        return None
    return kind, int(num), device


def pretty(combo: str) -> str:
    """'midi:note 36:LPD8' -> 'LPD8 note 36'."""
    p = parse(combo)
    if p is None:
        return combo
    kind, num, device = p
    return f"{device} {KINDS[kind]} {num}"


def short(combo: str) -> str:
    """For a pad's small hotkey badge: 'midi:note 36:LPD8' -> '♪36'."""
    p = parse(combo)
    if p is None:
        return combo
    kind, num, _ = p
    return {"note": "♪", "cc": "CC", "pc": "PC"}[kind] + str(num)


def decode(msg: int) -> tuple[str, str, int] | None:
    """A packed short MIDI message (status | data1 << 8 | data2 << 16) ->
    ('press' | 'release', kind, number), or None for anything else (clock, aftertouch…).
    A control change is 'press' at 64 or more and 'release' below it."""
    status, d1, d2 = msg & 0xFF, (msg >> 8) & 0x7F, (msg >> 16) & 0x7F
    kind = status & 0xF0
    if kind == 0x90:
        return ("press" if d2 else "release"), "note", d1   # velocity 0 = note off
    if kind == 0x80:
        return "release", "note", d1
    if kind == 0xB0:
        return ("press" if d2 >= 64 else "release"), "cc", d1
    if kind == 0xC0:
        return "press", "pc", d1
    return None


class Busy(OSError):
    """The device is open in another program."""


# ---------------------------------------------------------------------- winmm
MIM_OPEN, MIM_CLOSE, MIM_DATA = 0x3C1, 0x3C2, 0x3C3
CALLBACK_FUNCTION = 0x30000
MMSYSERR_ALLOCATED = 4

_Proc = ctypes.WINFUNCTYPE(None, wt.HANDLE, wt.UINT, ctypes.c_size_t, ctypes.c_size_t,
                           ctypes.c_size_t)


class _MIDIINCAPSW(ctypes.Structure):
    _fields_ = [("wMid", wt.WORD), ("wPid", wt.WORD), ("vDriverVersion", wt.UINT),
                ("szPname", wt.WCHAR * 32), ("dwSupport", wt.DWORD)]


class WinMM:
    """The real devices. `open(index, key)` starts one; its messages go to
    `on_message(key, msg)` and `on_closed(key)` on winmm's thread."""
    slow = True   # MidiIn lists its devices on a thread

    def __init__(self):
        self.on_message = lambda key, msg: None
        self.on_closed = lambda key: None
        self._dll = None
        self._proc = _Proc(self._callback)   # kept alive as long as we are

    @property
    def dll(self):
        if self._dll is None:
            d = ctypes.WinDLL("winmm")
            d.midiInGetNumDevs.restype = wt.UINT
            d.midiInGetDevCapsW.argtypes = (ctypes.c_size_t, ctypes.POINTER(_MIDIINCAPSW),
                                            wt.UINT)
            d.midiInOpen.argtypes = (ctypes.POINTER(wt.HANDLE), wt.UINT, ctypes.c_size_t,
                                     ctypes.c_size_t, wt.DWORD)
            for fn in ("midiInStart", "midiInStop", "midiInReset", "midiInClose"):
                getattr(d, fn).argtypes = (wt.HANDLE,)
            self._dll = d
        return self._dll

    def devices(self) -> list[str]:
        """Input device names, in winmm's order (the index is what open() takes)."""
        try:
            n = self.dll.midiInGetNumDevs()
        except OSError:
            return []
        names = []
        for i in range(n):
            caps = _MIDIINCAPSW()
            ok = self.dll.midiInGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps)) == 0
            names.append(caps.szPname.strip() if ok else "")
        return names

    def open(self, index: int, key: int):
        h = wt.HANDLE()
        err = self.dll.midiInOpen(ctypes.byref(h), index,
                                  ctypes.cast(self._proc, ctypes.c_void_p).value, key,
                                  CALLBACK_FUNCTION)
        if err == MMSYSERR_ALLOCATED:
            raise Busy(err, "in use by another program")
        if err:
            raise OSError(err, f"midiInOpen failed ({err})")
        self.dll.midiInStart(h)
        return h

    def close(self, handle):
        self.dll.midiInStop(handle)
        self.dll.midiInReset(handle)
        self.dll.midiInClose(handle)

    def _callback(self, _h, msg, key, p1, _p2):
        try:
            if msg == MIM_DATA:
                self.on_message(key, p1)
            elif msg == MIM_CLOSE:
                self.on_closed(key)
        except Exception:  # noqa: BLE001 - never let an exception into winmm's thread
            log.exception("MIDI callback failed")


# ---------------------------------------------------------------------- MidiIn
class MidiIn(QObject):
    """Opens the MIDI inputs something needs and reports pad hits as combos.

    pressed(combo) / released(combo): a pad went down / up (UI thread).
    busy_changed(list[str]): devices another program has open, when that changes."""
    pressed = Signal(str)
    released = Signal(str)
    busy_changed = Signal(list)
    _scanned = Signal(list)   # device names from the scan thread

    def __init__(self, backend=None):
        super().__init__()
        self.backend = backend or WinMM()
        self.backend.on_message = self._on_message
        self.backend.on_closed = self._on_closed
        self.busy: list[str] = []
        self._wanted: set[str] = set()
        self._capturing = False
        self._open: dict[str, tuple[int, object]] = {}   # name -> (key, handle)
        self._names: dict[int, str] = {}                   # key -> name (callback thread)
        self._dead: set[int] = set()
        self._cc: dict[tuple[int, int], bool] = {}         # (key, cc) -> is down
        self._held: dict[int, set[str]] = {}               # key -> pads down right now
        self._next_key = 1
        self._lock = threading.Lock()
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self.sync)
        # winmm's device list can take seconds (the first call loads every MIDI driver:
        # it froze the hotkey dialog for 6 s), so the real one is read on a thread
        self._async = getattr(self.backend, "slow", False)
        self._devs: list[str] = []
        self._scanning = False
        self._scanned.connect(self._on_scanned)

    # -- what to open
    def want(self, devices: set[str]):
        """The devices hotkeys use; everything else is closed (unless capturing)."""
        self._wanted = set(devices)
        self.sync()

    def capture(self, on: bool):
        """Open every device while the hotkey dialog listens for a pad."""
        self._capturing = on
        self.sync()

    def devices(self) -> list[str]:
        """Connected input devices (duplicate names numbered: 'LPD8', 'LPD8 (2)')."""
        return list(self._scan())

    def _scan(self) -> dict[str, int]:
        """Connected devices: display name -> winmm index."""
        seen: dict[str, int] = {}
        out = {}
        devs = self._devs if self._async else self.backend.devices()
        for i, name in enumerate(devs):
            if not name:
                continue
            seen[name] = seen.get(name, 0) + 1
            out[name if seen[name] == 1 else f"{name} ({seen[name]})"] = i
        return out

    def sync(self):
        """Open what's needed and connected, close the rest; retry busy ones later."""
        if self._async and (self._capturing or self._wanted) and not self._scanning:
            self._scanning = True
            threading.Thread(target=self._scan_thread, daemon=True, name="midi-scan").start()
        self._apply()

    def _scan_thread(self):
        try:
            names = list(self.backend.devices())
        except Exception:  # noqa: BLE001 - no devices this time; tried again next poll
            log.exception("MIDI: listing devices failed")
            names = list(self._devs)
        self._scanned.emit(names)

    def _on_scanned(self, names: list):
        self._scanning = False
        if names != self._devs:
            self._devs = names
            self._apply()
            if self._capturing:
                self.busy_changed.emit(list(self.busy))   # the dialog's device list

    def _apply(self):
        needed = None if self._capturing else self._wanted
        present = self._scan() if (self._capturing or self._wanted) else {}
        for name, (key, _h) in list(self._open.items()):
            if (key in self._dead or name not in present
                    or (needed is not None and name not in needed)):
                self._close(name)
        busy = []
        for name, idx in present.items():
            if name in self._open or (needed is not None and name not in needed):
                continue
            key = self._next_key
            self._next_key += 1
            with self._lock:
                self._names[key] = name
            try:
                self._open[name] = (key, self.backend.open(idx, key))
                log.info("MIDI: opened %s", name)
            except OSError as e:
                with self._lock:
                    self._names.pop(key, None)
                if isinstance(e, Busy):
                    busy.append(name)
                else:
                    log.warning("MIDI: can't open %s: %s", name, e)
        if busy != self.busy:
            if busy:
                log.info("MIDI devices in use by another program: %s", busy)
            self.busy = busy
            self.busy_changed.emit(list(busy))
        if (self._capturing or self._wanted) and not self._timer.isActive():
            self._timer.start()
        elif not (self._capturing or self._wanted):
            self._timer.stop()

    def close_all(self):
        self._wanted, self._capturing = set(), False
        self.sync()

    def _close(self, name: str):
        key, h = self._open.pop(name)
        with self._lock:
            self._names.pop(key, None)
            self._dead.discard(key)
            held = self._held.pop(key, set())
        self._cc = {k: v for k, v in self._cc.items() if k[0] != key}
        try:
            self.backend.close(h)
        except OSError:
            pass   # unplugged: the handle is already gone
        log.info("MIDI: closed %s", name)
        for combo in sorted(held):   # no note-off is coming: let hold-to-play pads go
            self.released.emit(combo)

    # -- winmm's thread
    def _on_message(self, key: int, msg: int):
        ev = decode(msg)
        if ev is None:
            return
        with self._lock:
            name = self._names.get(key)
        if name is None:
            return
        what, kind, num = ev
        if kind == "cc":   # held CC pads repeat values: only the crossings count
            down = what == "press"
            if self._cc.get((key, num), False) == down:
                return
            self._cc[(key, num)] = down
        combo = make(kind, num, name)
        if kind != "pc":   # a program change has no release
            with self._lock:
                held = self._held.setdefault(key, set())
                (held.add if what == "press" else held.discard)(combo)
        (self.pressed if what == "press" else self.released).emit(combo)

    def _on_closed(self, key: int):
        with self._lock:
            if key in self._names:
                self._dead.add(key)   # unplugged: sync() reopens it when it's back
