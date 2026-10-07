"""The mic effect: what others hear goes straight into your real mic, no virtual cable.
Setup -> Devices -> Send my sounds to -> "My mic".

How: a small Windows audio effect (native/directmic/obmic.cpp, an "APO" like Equalizer
APO's) runs inside Windows' audio engine on one microphone, in front of every app that
records it. Discord and games keep using the normal mic, so there's nothing to pick
there, and nothing is injected into any game. Soundpad works this way.

Board <-> effect: a shared file, %ProgramData%\\OnionBoard\\MicPlugin\\ring2.bin (the
folder lets the audio engine's account and signed-in users read and write it):

  header (HEADER bytes; little-endian; offsets in bytes)
  0   u32 magic "OBMC"          4   u32 version (2)
  8   u32 rate (48000)          12  u32 capacity: frames in the main ring (power of 2)
  16  u64 frames written (board)                24  u64 board's last write (GetTickCount64)
  32  u32 enabled (board)       36  u32 mode (board): 0 add, 1 replace
  40  f32 gain (board)          44  f32 mic gain (board, add mode; 0 = muted)
  48  u32 mic capacity: frames in the clean-mic ring (power of 2)
  52  i32 publisher: the slot owner writing the clean mic
  56  u64 clean-mic frames written (effect)    64  u32 the clean mic's rate
  68  u32 lead (board): ring frames the effect reads behind the board (0 = 20 ms)
  72  u64 the clean mic's last block (GetTickCount64)
  80  u32 the running effect's version
  84  u32 the process id of the board writing (another board backs off; the effect
      doesn't read it)
  256 SLOTS slots of 64 bytes, one per app recording the mic (SLOT below)
  HEADER: f32[capacity] what others hear, mono, at `rate`
  then:   f32[mic capacity][2] the clean mic, at the mic's rate

The effect publishes the clean mic (after the mic's own driver effect, before anything
of the board's); the board's mic comes from there, so its meter, mic check and voice
changer never hear its own sounds come back. Each block of clean mic in, the board
renders the same stretch of what others hear and writes it out: it runs on the mic's
clock, so the two never drift apart. In replace mode (the default) that is the whole
send mix, your processed voice included, and the effect puts it in place of the mic
(about 20 ms later); add mode adds only the sounds on top of the mic. The board late
with a block: the effect fills in with the clean mic from the moment that block was
to be made from (`set_sync`), so the voice carries on. The board gone: the effect
crossfades back to the plain mic. Nobody recording
the mic: the effect doesn't run, and the board keeps time on its own clock.

Installing needs admin once (Windows' prompt): `install()` runs this app again as admin
(`--direct-mic install <endpoint>`), which copies the effect DLL to Program Files,
registers it, puts it on the mic (keeping any effect the mic's driver had, which the
effect then runs first) and restarts Windows' audio service. `uninstall()` puts every
mic back as it was. The DLL that's installed is always this app's own copy, never a path
from the command line, so the admin step can't be pointed at another DLL.
"""
from __future__ import annotations

import ctypes
import hashlib
import logging
import mmap
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import winreg
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

FLAG = "--direct-mic"
CLSID = "{C55E76FE-6667-4828-81FD-05B393FD649E}"   # obmic.cpp CLSID_OnionMic
DEVICE = "Your mic (no cable)"         # the send "device" for the engine
DLL_NAME = "obmic.dll"
EFFECT_VERSION = 5                                  # obmic.cpp EFFECT_VERSION

RATE = 48000
CAPACITY = 1 << 16          # ~1.4 s at 48 kHz
MIC_CAPACITY = 1 << 15      # ~0.7 s of clean mic
HEADER = 4096
SLOT_OFFSET, SLOTS = 256, 16
FILE_BYTES = HEADER + CAPACITY * 4 + MIC_CAPACITY * 8
MAGIC = 0x434D424F
VERSION = 2
MODE_ADD, MODE_REPLACE = 0, 1
LEAD_S = 0.02               # how far behind the board the effect reads (its added delay)
BLOCK = 480                 # frames rendered per engine call (10 ms)
ALIVE_MS = 250              # effect heard from this recently: it's running
MIC_LIVE_MS = 150           # the clean mic arrived this recently: the board runs on it
POLL_S = 0.002
OTHER_BOARD_MS = 1000       # another board wrote this recently: it's still running

HEAD = np.dtype({
    "names": ["magic", "version", "rate", "capacity", "write_pos", "board_tick", "enabled",
              "mode", "gain", "mic_gain", "mic_capacity", "publisher", "mic_write_pos",
              "mic_rate", "lead", "mic_tick", "effect_version", "board_pid", "sync_seq",
              "sync_wp", "sync_mic"],
    "formats": ["<u4", "<u4", "<u4", "<u4", "<u8", "<u8", "<u4", "<u4", "<f4", "<f4", "<u4",
                "<i4", "<u8", "<u4", "<u4", "<u8", "<u4", "<u4", "<u4", "<u8", "<u8"],
    "offsets": [0, 4, 8, 12, 16, 24, 32, 36, 40, 44, 48, 52, 56, 64, 68, 72, 80, 84, 88, 96,
                104],
    "itemsize": SLOT_OFFSET})
SLOT = np.dtype({
    "names": ["owner", "rate", "channels", "flags", "tick", "read_pos", "lead", "underruns",
              "blocks"],
    "formats": ["<i4", "<u4", "<u4", "<u4", "<u8", "<u8", "<u4", "<u4", "<u8"],
    "offsets": [0, 4, 8, 12, 16, 24, 32, 36, 40],
    "itemsize": 64})
SLOT_REPLACING, SLOT_PUBLISHING = 1, 2

STATE_KEY = r"SOFTWARE\OnionBoard\MicPlugin"
ENDPOINTS_KEY = STATE_KEY + r"\Endpoints"
CAPTURE_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture"
FX = "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},%d"   # PKEY_FX_* / PKEY_CompositeFX_*
# On a recording device Windows runs the effects in front of each app's stream: SFX (or
# LFX on drivers that only know the old kind), after the device's own EFX if it has one.
LFX, GFX, SFX, MFX, EFX = 1, 2, 5, 6, 7
SLOTS_FX = {"sfx": SFX, "lfx": LFX}                 # where the effect goes on a mic
MODERN = (SFX, MFX, EFX)
LEGACY = (LFX, GFX)
COMPOSITE_SFX = 13                                  # PKEY_CompositeFX_StreamEffectClsid
DISABLE_SYSFX = "{1da5d803-d492-4edd-8c23-e0c0ffee7f0e},5"   # "Audio enhancements: off"
MODES_KEY = "{d3993a3f-99c2-4402-b5ec-a92a0367664b},%d"     # PKEY_*_ProcessingModes_...
MODE_DEFAULT = "{C18E2F7E-933D-4965-B7D1-1EEF228D2AF3}"     # AUDIO_SIGNALPROCESSINGMODE_DEFAULT
NAME_DESC = "{a45c254e-df1c-4efd-8020-67d146a850e0},2"       # "Microphone"
NAME_IFACE = "{b3f8fa53-0004-438e-9003-51a46e139bfc},6"      # "Realtek Audio"
_GUID = re.compile(r"\{[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                   r"[0-9a-fA-F]{12}\}")
_CREATE_NO_WINDOW = 0x08000000


def data_dir() -> Path:
    return Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "OnionBoard" / "MicPlugin"


def ring_path() -> Path:
    return data_dir() / "ring2.bin"   # (ring.bin: the first test build's layout)


def install_dir() -> Path:
    return Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Onion Board Mic"


def _old_install_dirs() -> list[Path]:
    """Where the first test builds put the effect (removed on install / uninstall)."""
    return [install_dir().parent / "Onion Board Mic Plugin"]


def bundled_dll() -> Path:
    """This app's own copy of the effect: next to the frozen app, or the one
    scripts/build_directmic.py built when run from source."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "directmic" / DLL_NAME
    return Path(__file__).resolve().parent.parent / "build" / "directmic" / DLL_NAME


# ---------------------------------------------------------------------- the ring

def _tick() -> int:
    return int(ctypes.windll.kernel32.GetTickCount64()) if sys.platform == "win32" \
        else int(time.monotonic() * 1000)


def new_ring_bytes() -> bytes:
    """A fresh ring file: header filled in, board off, no samples."""
    head = np.zeros(1, HEAD)
    h = head[0]
    h["magic"], h["version"], h["rate"], h["capacity"] = MAGIC, VERSION, RATE, CAPACITY
    h["gain"] = h["mic_gain"] = 1.0
    h["mic_capacity"] = MIC_CAPACITY
    h["mode"] = MODE_REPLACE
    return head.tobytes() + bytes(FILE_BYTES - HEAD.itemsize)


def make_ring(path: Path | None = None) -> bool:
    """Create the ring file if it isn't there (or is another version's). The folder
    lets signed-in users write, so the board can do this without admin. True if it's
    usable now."""
    path = Path(path or ring_path())
    try:
        if path.is_file() and path.stat().st_size == FILE_BYTES:
            with open(path, "rb") as f:
                head = np.frombuffer(f.read(HEAD.itemsize), HEAD)[0]
            if head["magic"] == MAGIC and head["version"] == VERSION \
                    and head["capacity"] == CAPACITY and head["mic_capacity"] == MIC_CAPACITY:
                return True
        tmp = path.with_suffix(".new")
        tmp.write_bytes(new_ring_bytes())
        os.replace(tmp, path)   # a effect still mapping the old one keeps its own copy
        return True
    except OSError:
        log.info("can't make the mic effect's ring at %s", path, exc_info=True)
        return False


class RingWriter:
    """The board's end of the ring file."""

    def __init__(self, path: Path | None = None):
        path = Path(path or ring_path())
        self._f = open(path, "r+b")
        try:
            self._mm = mmap.mmap(self._f.fileno(), FILE_BYTES)
        except (OSError, ValueError):
            self._f.close()
            raise
        self.h = np.ndarray((1,), HEAD, buffer=self._mm)
        h = self.h[0]
        if h["magic"] != MAGIC or h["version"] != VERSION or h["capacity"] != CAPACITY \
                or h["mic_capacity"] != MIC_CAPACITY:
            self.close()
            raise RuntimeError("the mic effect's ring file is from another version")
        self.slots = np.ndarray((SLOTS,), SLOT, buffer=self._mm, offset=SLOT_OFFSET)
        self.data = np.ndarray((CAPACITY,), np.float32, buffer=self._mm, offset=HEADER)
        self.mic = np.ndarray((MIC_CAPACITY, 2), np.float32, buffer=self._mm,
                              offset=HEADER + CAPACITY * 4)
        # one view per field: building them on every access costs more than the access
        f = {name: self.h[name] for name in HEAD.names}
        self._wp, self._btick, self._mwp, self._mtick = (
            f["write_pos"], f["board_tick"], f["mic_write_pos"], f["mic_tick"])
        self._f_fields = f

    def _get(self, name: str):
        return self._f_fields[name][0]

    def _set(self, name: str, value):
        self._f_fields[name][0] = value

    @property
    def write_pos(self) -> int:
        return int(self._wp[0])

    @property
    def mic_write_pos(self) -> int:
        return int(self._mwp[0])

    @property
    def mic_rate(self) -> int:
        return int(self._get("mic_rate"))

    @property
    def effect_version(self) -> int:
        return int(self._get("effect_version"))

    def live_slots(self, now: int | None = None) -> np.ndarray:
        """The slots of instances that ran a block in the last ALIVE_MS."""
        now = _tick() if now is None else now
        s = self.slots.copy()
        return s[(s["owner"] != 0) & (now - s["tick"].astype(np.int64) < ALIVE_MS)]

    @property
    def read_pos(self) -> int:
        """The freshest instance's read position (0 without one)."""
        s = self.live_slots()
        return int(s["read_pos"][s["tick"].argmax()]) if len(s) else 0

    def effect_alive(self, now: int | None = None) -> bool:
        """The effect ran a block lately: something is recording the mic."""
        now = _tick() if now is None else now
        return len(self.live_slots(now)) > 0 or now - int(self._mtick[0]) < ALIVE_MS

    def mic_live(self, now: int | None = None) -> bool:
        """The clean mic is arriving."""
        now = _tick() if now is None else now
        return now - int(self._mtick[0]) < MIC_LIVE_MS and 8000 <= self.mic_rate <= 384000

    def effect_format(self) -> tuple[int, int]:
        s = self.live_slots()
        if not len(s):
            return 0, 0
        top = s[s["tick"].argmax()]
        return int(top["rate"]), int(top["channels"])

    def apps(self) -> int:
        """How many apps' streams the effect runs on right now (the board's own too)."""
        return len(self.live_slots())

    def late(self) -> int:
        """Times, summed over the running instances, the board was late for them."""
        return int(self.live_slots()["underruns"].sum())

    def claim(self):
        """This board writes the ring from now on. Another board still writing it (a
        second copy of the app on its own profile) keeps it: two writing at once would
        put both mixes, chopped up, on the mic."""
        pid, me = int(self._get("board_pid")), os.getpid()
        if pid and pid != me and self._get("enabled") \
                and _tick() - int(self._btick[0]) < OTHER_BOARD_MS and _pid_alive(pid):
            raise RuntimeError("Another Onion Board is already sending into your mic. "
                               "Close it, and this one takes over.")
        self._set("board_pid", me)

    def set_enabled(self, on: bool):
        self._set("enabled", 1 if on else 0)
        self.heartbeat()

    def set_mode(self, mode: int):
        self._set("mode", mode)

    def set_mic_gain(self, g: float):
        self._set("mic_gain", np.float32(g))

    def set_lead(self, seconds: float):
        self._set("lead", int(seconds * RATE))

    def heartbeat(self):
        self._btick[0] = _tick()

    def set_sync(self, wp: int, mic: int):
        """Ring frame `wp` is the board's audio for clean-mic frame `mic`: a board late
        with a block, the effect fills in with the mic from the same moment (no skip or
        repeat in the voice). Odd sync_seq while it changes: the effect reads it then."""
        seq = int(self._get("sync_seq"))
        self._set("sync_seq", (seq + 1) & 0xFFFFFFFF)
        self._set("sync_wp", wp)
        self._set("sync_mic", mic)
        self._set("sync_seq", (seq + 2) & 0xFFFFFFFE)

    def clear_sync(self):
        seq = int(self._get("sync_seq"))
        self._set("sync_seq", (seq + 1) & 0xFFFFFFFF)
        self._set("sync_wp", 0)
        self._set("sync_mic", 0)
        self._set("sync_seq", (seq + 2) & 0xFFFFFFFE)

    def jump(self, pos: int):
        """Start writing at `pos`."""
        self._wp[0] = pos

    def write(self, mono: np.ndarray):
        """Append mono float32 samples; the position moves on only after the data is in."""
        n = len(mono)
        if not n:
            return
        if n > CAPACITY:
            mono, n = mono[-CAPACITY:], CAPACITY
        pos = self.write_pos
        if pos > 1 << 52:   # junk (the effect ignores it): start counting over
            pos = 0
        i = pos & (CAPACITY - 1)
        first = min(n, CAPACITY - i)
        self.data[i:i + first] = mono[:first]
        if first < n:
            self.data[:n - first] = mono[first:]
        self._wp[0] = pos + n
        self.heartbeat()

    def read_mic(self, pos: int, n: int) -> np.ndarray:
        """n frames of clean mic from frame `pos`, (n, 2)."""
        n = min(n, MIC_CAPACITY)
        i = pos & (MIC_CAPACITY - 1)
        first = min(n, MIC_CAPACITY - i)
        if first == n:
            return self.mic[i:i + n].copy()
        return np.concatenate([self.mic[i:], self.mic[:n - first]])

    def close(self, owner: bool = True):
        """`owner`: this board was writing the ring (switch it off on the way out)."""
        try:
            if owner and int(self._get("board_pid")) in (0, os.getpid()):
                self._set("enabled", 0)
                self._set("board_pid", 0)
        except (ValueError, TypeError, AttributeError, KeyError):
            pass
        for name in ("h", "slots", "data", "mic", "_wp", "_btick", "_mwp", "_mtick",
                     "_f_fields"):
            self.__dict__.pop(name, None)   # views pin the map: drop them first
        try:
            self._mm.close()
        except (BufferError, ValueError):
            log.debug("ring map still in use", exc_info=True)
        self._f.close()


class DirectMicStream:
    """Stands in for sounddevice's OutputStream when what others hear goes to the mic
    effect. Each stretch of clean mic the effect publishes is handed to `mic_callback`
    (frames x 2, rate) and the same stretch of the board's output is rendered with
    `callback` (the engine's) and written into the ring, downmixed to mono (voice chat
    is mono anyway). That's a thread polling every POLL_S, plus `pump()` from the
    board's own mic callback, which fires right after the effect ran on its block.
    Without the effect (nobody records the mic) the thread keeps time itself, so
    sounds still play at the right speed."""

    samplerate = RATE

    def __init__(self, callback, path: Path | None = None, mic_callback=None,
                 mode: int = MODE_REPLACE, lead_s: float = LEAD_S, voice_delay=None):
        self._callback = callback
        self._mic_callback = mic_callback
        # () -> frames (at RATE) the voice in what was just rendered is behind the mic
        # handed over (see Engine._direct_voice_delay); None = none
        self._voice_delay = voice_delay
        if path is None:
            make_ring()
        self._ring = RingWriter(path)
        try:
            self._ring.claim()
        except RuntimeError:
            self._ring.close(owner=False)
            raise
        self._ring.set_mode(mode)
        self._ring.set_lead(lead_s)
        self.mode = mode
        self.latency = lead_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.active = False
        self.mic_live = False       # the board is running on the effect's clean mic
        self.mic_rate = 0
        self._mic_pos = 0
        self._acc = 0.0
        self._start = time.perf_counter()
        self._made = 0
        self._buf = np.zeros((BLOCK, 2), np.float32)

    def start(self):
        self._ring.set_enabled(True)
        self.active = True
        self._start, self._made = time.perf_counter(), 0
        self._thread = threading.Thread(target=self._run, daemon=True, name="direct-mic")
        self._thread.start()

    def stop(self):
        self._stop.set()
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(1.0)
        self.active = False

    def close(self):
        self.stop()
        with self._lock:
            self._ring.close()

    def set_mode(self, mode: int):
        self.mode = mode
        self._ring.set_mode(mode)

    def set_mic_gain(self, g: float):
        """Add mode: the effect's own level for the mic (0 = muted)."""
        try:
            self._ring.set_mic_gain(g)
        except (ValueError, KeyError, AttributeError):   # closed
            pass

    def effect_alive(self) -> bool:
        try:
            return self._ring.effect_alive()
        except (ValueError, KeyError, AttributeError):   # closed
            return False

    def apps(self) -> int:
        try:
            return self._ring.apps()
        except (ValueError, KeyError, AttributeError):
            return 0

    def late(self) -> int:
        try:
            return self._ring.late()
        except (ValueError, KeyError, AttributeError):
            return 0

    def pump(self) -> bool:
        """Take whatever clean mic came in and send the same stretch out. Safe from any
        thread; False if another thread is at it (it'll take this block too)."""
        if not self._lock.acquire(blocking=False):
            return False
        try:
            if self.active:
                self._pump()
            return True
        finally:
            self._lock.release()

    def _delay(self) -> float:
        if self._voice_delay is None:
            return 0.0
        try:
            return max(0.0, float(self._voice_delay()))
        except Exception:  # noqa: BLE001 - only the fill-in's timing is off by it
            log.debug("voice delay", exc_info=True)
            return 0.0

    def _render(self, n: int):
        buf = self._buf
        while n > 0:
            k = min(n, BLOCK)
            out = buf[:k]
            self._callback(out, k, None, None)
            self._ring.write(out.mean(axis=1, dtype=np.float32))
            n -= k

    def _pump(self):
        ring = self._ring
        now = _tick()
        if ring.mic_live(now):
            wp, rate = ring.mic_write_pos, ring.mic_rate
            gap = wp - self._mic_pos
            if not self.mic_live or rate != self.mic_rate or gap < 0 or gap > MIC_CAPACITY // 2:
                self._mic_pos, self.mic_rate, self._acc = wp, rate, 0.0   # (re)start here
                self.mic_live = True
                ring.heartbeat()
                return
            if gap == 0:
                ring.heartbeat()
                return
            x = ring.read_mic(self._mic_pos, gap)
            self._mic_pos = wp
            if self._mic_callback is not None:
                self._mic_callback(x, rate)
            self._acc += gap * RATE / rate
            k = int(self._acc)
            self._acc -= k
            self._render(k)
            ring.set_sync(ring.write_pos, max(0, wp - int(round(self._delay() * rate / RATE))))
            self._start, self._made = time.perf_counter(), 0
            return
        if self.mic_live:   # the mic stopped: keep time from here on our own
            self.mic_live = False
            ring.clear_sync()
            self._start, self._made = time.perf_counter(), 0
        due = int((time.perf_counter() - self._start) * RATE)
        if due - self._made > RATE // 5:   # stalled (sleep, a hang): don't catch up
            self._made = due - BLOCK
        need = due - self._made
        if need > 0:
            self._made += need
            self._render(need)
        else:
            ring.heartbeat()

    def _run(self):
        try:
            while not self._stop.is_set():
                self.pump()
                time.sleep(POLL_S)
        except Exception:  # noqa: BLE001 - the engine's watchdog reopens a stalled stream
            log.exception("mic effect feed stopped")


def _pid_alive(pid: int) -> bool:
    """A process with this id is running (one we may not look into counts as running)."""
    if sys.platform != "win32":
        return True
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    h = k32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ctypes.get_last_error() == 5   # access denied: someone else's, running
    try:
        code = ctypes.c_ulong()
        k32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        return bool(k32.GetExitCodeProcess(ctypes.c_void_p(h), ctypes.byref(code))) \
            and code.value == 259   # STILL_ACTIVE
    finally:
        k32.CloseHandle(ctypes.c_void_p(h))


# ---------------------------------------------------------------------- the mics

def capture_endpoints() -> list[dict]:
    """Every recording device Windows knows: {"guid", "name", "active"}."""
    found = []
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, CAPTURE_KEY)
    except OSError:
        return found
    with root:
        i = 0
        while True:
            try:
                guid = winreg.EnumKey(root, i)
            except OSError:
                break
            i += 1
            try:
                with winreg.OpenKey(root, guid) as k:
                    state = winreg.QueryValueEx(k, "DeviceState")[0]
                with winreg.OpenKey(root, guid + r"\Properties") as p:
                    desc = _value(p, NAME_DESC) or "Microphone"
                    iface = _value(p, NAME_IFACE)
            except OSError:
                continue
            name = f"{desc} ({iface})" if iface else desc
            found.append({"guid": guid.lower(), "name": name, "active": state == 1})
    return found


def endpoint_for(name: str | None) -> str | None:
    """The endpoint GUID of the active recording device called `name` (as PortAudio
    lists it: its name may be cut short, so a prefix match counts)."""
    if not name:
        return None
    active = [e for e in capture_endpoints() if e["active"]]
    for e in active:
        if e["name"] == name:
            return e["guid"]
    for e in active:
        if e["name"].startswith(name) or name.startswith(e["name"]):
            return e["guid"]
    return None


def _value(key, name):
    try:
        return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None


def installed_on() -> list[str]:
    """Endpoint GUIDs the effect is installed on."""
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, ENDPOINTS_KEY)
    except OSError:
        return []
    out = []
    with root:
        i = 0
        while True:
            try:
                out.append(winreg.EnumKey(root, i).lower())
            except OSError:
                break
            i += 1
    return out


_status_cache: dict = {}
STATUS_S = 2.0


def forget_status():
    _status_cache.clear()


def status(mic_name: str | None = None) -> str:
    """Where Onion Board stands on the mic called `mic_name` (any mic it's on if None):
      'missing'   not attached to any mic
      'other'     attached, but to another mic
      'wiped'     attached, but Windows (a driver or Windows update) took the effect off
      'outdated'  attached, but with another version of the effect than this app's
      'ready'     attached and working
    'wiped' and 'outdated' need the one-click repair (attaching again). Cached for
    STATUS_S."""
    hit = _status_cache.get(mic_name)
    now = time.monotonic()
    if hit and now - hit[0] < STATUS_S:
        return hit[1]
    result = _status(mic_name)
    _status_cache[mic_name] = (now, result)
    return result


def needs_repair(state: str) -> bool:
    """Windows took it off the mic: it has to be put back (one prompt)."""
    return state == "wiped"


def works(state: str) -> bool:
    """On the mic and working. An older copy of the effect ('outdated') still works:
    the update is offered, not forced."""
    return state in ("ready", "outdated")


def _status(mic_name: str | None) -> str:
    on = installed_on()
    if not on:
        return "missing"
    guid = endpoint_for(mic_name) if mic_name is not None else on[0]
    if guid not in on:
        return "other"
    if not effect_in_place(guid) or not make_ring():
        return "wiped"
    if not same_dll(registered_dll(), bundled_dll()):
        return "outdated"
    return "ready"


def effect_in_place(guid: str) -> bool:
    """Our effect is still in one of the mic's effect slots (a driver update rewrites
    them, Windows' "Reset sound settings" too)."""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            rf"{CAPTURE_KEY}\{guid}\FxProperties") as k:
            return any(_is_ours(_value(k, FX % pid)) for pid in (SFX, LFX, COMPOSITE_SFX))
    except OSError:
        return False


def _is_ours(value) -> bool:
    """An effect slot's value (one CLSID, or a list of them) holds this effect."""
    vals = value if isinstance(value, list) else [value]
    return any(isinstance(x, str) and x.upper() == CLSID for x in vals)


def registered_dll() -> Path | None:
    """The effect DLL Windows loads (the one registered for our CLSID)."""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            rf"SOFTWARE\Classes\CLSID\{CLSID}\InprocServer32") as k:
            v = _value(k, "")
    except OSError:
        return None
    return Path(v) if isinstance(v, str) and v else None


_hashes: dict = {}


def _digest(path: Path) -> str | None:
    try:
        st = path.stat()
    except OSError:
        return None
    key = (str(path), st.st_size, st.st_mtime_ns)
    if key not in _hashes:
        try:
            _hashes[key] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return None
    return _hashes[key]


def same_dll(installed: Path | None, ours: Path) -> bool:
    """The installed effect is this app's own. An app without one of its own (a build
    from source that never built it) can't tell, and takes what's there."""
    if not ours.is_file():
        return installed is not None and installed.is_file()
    if installed is None:
        return False
    a = _digest(installed)
    return a is not None and a == _digest(ours)


# ---------------------------------------------------------------------- admin part
# Everything below runs in the admin copy only (`--direct-mic ...`).

def _enable_privileges(*names: str):
    from ctypes import wintypes

    class LUID(ctypes.Structure):
        _fields_ = [("Low", wintypes.DWORD), ("High", wintypes.LONG)]

    class TOKEN_PRIVILEGES(ctypes.Structure):
        _fields_ = [("Count", wintypes.DWORD), ("Luid", LUID), ("Attributes", wintypes.DWORD)]

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                        ctypes.POINTER(wintypes.HANDLE)]
    advapi.LookupPrivilegeValueW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR,
                                             ctypes.POINTER(LUID)]
    advapi.AdjustTokenPrivileges.argtypes = [wintypes.HANDLE, wintypes.BOOL,
                                             ctypes.POINTER(TOKEN_PRIVILEGES), wintypes.DWORD,
                                             ctypes.c_void_p, ctypes.c_void_p]
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0020 | 0x0008,
                                   ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        for name in names:
            tp = TOKEN_PRIVILEGES(Count=1, Attributes=0x2)   # SE_PRIVILEGE_ENABLED
            if not advapi.LookupPrivilegeValueW(None, name, ctypes.byref(tp.Luid)):
                raise ctypes.WinError(ctypes.get_last_error())
            advapi.AdjustTokenPrivileges(token, False, ctypes.byref(tp), 0, None, None)
            if ctypes.get_last_error():   # ERROR_NOT_ALL_ASSIGNED: not admin
                raise PermissionError(f"can't enable {name}")
    finally:
        kernel.CloseHandle(token)


class _BackupKey:
    """A registry key opened with the backup/restore privileges: Windows' audio keys
    belong to its own services, and these let an admin change them without taking
    ownership or touching their permissions."""

    def __init__(self, path: str, create: bool = True):
        from ctypes import wintypes
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        fn = advapi.RegCreateKeyExW
        fn.argtypes = [wintypes.HKEY, wintypes.LPCWSTR, wintypes.DWORD, wintypes.LPWSTR,
                       wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       ctypes.POINTER(wintypes.HKEY), ctypes.POINTER(wintypes.DWORD)]
        if not create:   # FileNotFoundError if it's not there; denied still means it is
            try:
                winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path).Close()
            except PermissionError:
                pass
        h = wintypes.HKEY()
        disp = wintypes.DWORD()
        err = fn(winreg.HKEY_LOCAL_MACHINE, path, 0, None, 0x4,   # REG_OPTION_BACKUP_RESTORE
                 winreg.KEY_ALL_ACCESS, None, ctypes.byref(h), ctypes.byref(disp))
        if err:
            raise ctypes.WinError(err)
        self.h = h.value
        self.created = disp.value == 1   # REG_CREATED_NEW_KEY

    def get(self, name):
        try:
            return winreg.QueryValueEx(self.h, name)
        except OSError:
            return None

    def set(self, name, kind, value):
        winreg.SetValueEx(self.h, name, 0, kind, value)

    def set_raw(self, name, kind, data: bytes):
        """A value of any kind, byte for byte (winreg converts only the kinds it knows)."""
        from ctypes import wintypes
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        fn = advapi.RegSetValueExW
        fn.argtypes = [wintypes.HKEY, wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       ctypes.c_char_p, wintypes.DWORD]
        err = fn(self.h, name, 0, kind, data, len(data))
        if err:
            raise ctypes.WinError(err)

    def delete(self, name):
        try:
            winreg.DeleteValue(self.h, name)
        except FileNotFoundError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        winreg.CloseKey(self.h)


class _StateKey(_BackupKey):
    r"""Our own notes (HKLM\SOFTWARE\OnionBoard\MicPlugin): a plain admin key."""

    def __init__(self, path: str):
        self.h = winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_ALL_ACCESS)
        self.created = False


def _run(cmd: list[str]) -> int:
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=_CREATE_NO_WINDOW)
    if r.returncode:
        log.warning("%s -> %s %s", " ".join(cmd), r.returncode, (r.stdout + r.stderr).strip())
    return r.returncode


def _audio_comes_back():
    """A small helper that starts Windows' audio again once this process ends, however
    it ends: killed half-way or crashed, the PC must never be left without sound.
    (Starting a service that's already running does nothing.)"""
    script = (f"Wait-Process -Id {os.getpid()} -ErrorAction SilentlyContinue; "
              "Start-Service AudioEndpointBuilder; Start-Service Audiosrv")
    cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]
    for flags in (_CREATE_NO_WINDOW | 0x01000000, _CREATE_NO_WINDOW):   # out of our job
        try:
            subprocess.Popen(cmd, creationflags=flags, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            continue
    log.warning("no helper to bring the audio back if this stops half-way")


def _audio_service(start: bool):
    """Stop / start Windows' audio. The endpoint builder reads the mics' effect settings
    when it starts, so it goes too (the audio service depends on it)."""
    if start:
        _run(["net", "start", "AudioEndpointBuilder"])
        _run(["net", "start", "audiosrv"])
    else:
        _run(["net", "stop", "audiosrv", "/y"])
        _run(["net", "stop", "AudioEndpointBuilder", "/y"])


def _register_com(dll: Path):
    clsid_key = rf"SOFTWARE\Classes\CLSID\{CLSID}"
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, clsid_key, 0, winreg.KEY_ALL_ACCESS) as k:
        winreg.SetValueEx(k, None, 0, winreg.REG_SZ, "Onion Board mic")
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, clsid_key + r"\InprocServer32", 0,
                            winreg.KEY_ALL_ACCESS) as k:
        winreg.SetValueEx(k, None, 0, winreg.REG_SZ, str(dll))
        winreg.SetValueEx(k, "ThreadingModel", 0, winreg.REG_SZ, "Both")
    apo_key = rf"SOFTWARE\Classes\AudioEngine\AudioProcessingObjects\{CLSID}"
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, apo_key, 0, winreg.KEY_ALL_ACCESS) as k:
        for name, value in (("FriendlyName", "Onion Board mic"),
                            ("Copyright", "Onion Board contributors"),
                            ("APOInterface0", "{FD7F2B29-24D0-4B5C-B177-592C39F9CA10}")):
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
        for name, value in (("MajorVersion", 1), ("MinorVersion", 0), ("Flags", 14),
                            ("MinInputConnections", 1), ("MaxInputConnections", 1),
                            ("MinOutputConnections", 1), ("MaxOutputConnections", 1),
                            ("MaxInstances", 0xFFFFFFFF), ("NumAPOInterfaces", 1)):
            winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, value)


def _unregister_com():
    for path in (rf"SOFTWARE\Classes\CLSID\{CLSID}\InprocServer32",
                 rf"SOFTWARE\Classes\CLSID\{CLSID}",
                 rf"SOFTWARE\Classes\AudioEngine\AudioProcessingObjects\{CLSID}"):
        try:
            winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, path)
        except FileNotFoundError:
            pass


def pick_slot(values: dict[int, object]) -> tuple[str, int]:
    """Which effect slot the effect takes on a mic whose FxProperties hold `values`
    ({pid: value}), the way Equalizer APO picks: ('composite', 13) joins the stream
    effect list Windows chains by itself; ('wrap', LFX) on a driver with only the old
    kind of effects; otherwise ('wrap', SFX). 'wrap' replaces that slot's effect, and
    the effect runs the one it replaced first."""
    if values.get(COMPOSITE_SFX):
        return "composite", COMPOSITE_SFX
    if any(values.get(p) for p in LEGACY) and not any(values.get(p) for p in MODERN):
        return "wrap", LFX
    return "wrap", SFX


def _original(values: dict[int, object], pid: int) -> str:
    """The effect the effect runs first in slot `pid`: the slot's own, or (a mic whose
    driver has no stream effect) its old-style LFX, which taking SFX switches off."""
    old = values.get(pid)
    if not old and pid == SFX and not values.get(EFX):
        old = values.get(LFX)
    return old if isinstance(old, str) and not _is_ours(old) else ""


def _install_endpoint(guid: str, slot: str | None):
    """Put the effect on one mic. Everything changed is noted under ENDPOINTS_KEY so
    _uninstall_endpoint can put it back exactly."""
    base = rf"{CAPTURE_KEY}\{guid}"
    with _BackupKey(base + r"\FxProperties") as fx, \
            _StateKey(rf"{ENDPOINTS_KEY}\{guid}") as state:
        values = {p: (fx.get(FX % p) or (None,))[0] for p in (*MODERN, *LEGACY, COMPOSITE_SFX)}
        kind, pid = pick_slot(values) if not slot else ("wrap", SLOTS_FX[slot])
        state.set("FxCreated", winreg.REG_DWORD, 1 if fx.created else 0)
        state.set("Slot", winreg.REG_DWORD, pid)
        # every value this touches, as it was, to put back later (written before anything
        # changes, so a step cut off half-way can still be undone)
        names = (FX % pid, MODES_KEY % SFX, FX % LFX, FX % GFX, DISABLE_SYSFX)
        state.set("Before", winreg.REG_MULTI_SZ, [_note(n, fx.get(n)) for n in names])
        if kind == "composite":
            cur = list(values[COMPOSITE_SFX] or [])
            fx.set(FX % pid, winreg.REG_MULTI_SZ,
                   [CLSID] + [c for c in cur if c.upper() != CLSID])
            state.set("Original", winreg.REG_SZ, "")
        else:
            state.set("Original", winreg.REG_SZ, _original(values, pid))
            fx.set(FX % pid, winreg.REG_SZ, CLSID)
        if pid in (SFX, COMPOSITE_SFX):
            if not fx.get(MODES_KEY % SFX):
                fx.set(MODES_KEY % SFX, winreg.REG_MULTI_SZ, [MODE_DEFAULT])
            # a modern effect on the mic switches the old-style ones off anyway
            fx.delete(FX % LFX)
            fx.delete(FX % GFX)
        if fx.get(DISABLE_SYSFX):   # "Audio enhancements: off" would stop every effect
            fx.delete(DISABLE_SYSFX)
    log.info("mic effect on %s (slot %s)", guid, pid)


def _note(name: str, v) -> str:
    """One value as it was, for the "Before" notes: `name=` (wasn't there),
    `name=sz:...`, `name=multi:a|b`, `name=dword:N`, or `name=raw:<type>:<hex>` for any
    other kind, so it goes back exactly as it was. This effect's own CLSID is never
    noted as an original (notes lost while it was on the mic): it's left out."""
    if v is None:
        return f"{name}="
    value, kind = v
    if kind == winreg.REG_MULTI_SZ and all(isinstance(x, str) for x in value or []):
        return f"{name}=multi:" + "|".join(x for x in value or [] if x.upper() != CLSID)
    if kind == winreg.REG_DWORD:
        return f"{name}=dword:{int(value)}"
    if kind == winreg.REG_SZ and isinstance(value, str):
        return f"{name}=" if value.upper() == CLSID else f"{name}=sz:{value}"
    if isinstance(value, bytes):
        raw = value
    elif isinstance(value, int):
        raw = value.to_bytes(8 if kind == winreg.REG_QWORD else 4, "little", signed=value < 0)
    elif value is None:
        raw = b""
    else:
        raw = (str(value) + "\0").encode("utf-16-le")
    return f"{name}=raw:{kind}:{raw.hex()}"


def _put_back(fx, item: str):
    """Undo one "Before" note (see _note)."""
    name, _, value = item.partition("=")
    if not value:
        fx.delete(name)
    elif value.startswith("multi:"):
        fx.set(name, winreg.REG_MULTI_SZ, value[6:].split("|") if value[6:] else [])
    elif value.startswith("dword:"):
        fx.set(name, winreg.REG_DWORD, int(value[6:]))
    elif value.startswith("raw:"):
        kind, _, data = value[4:].partition(":")
        fx.set_raw(name, int(kind), bytes.fromhex(data))
    else:
        fx.set(name, winreg.REG_SZ, value.removeprefix("sz:"))


def _uninstall_endpoint(guid: str):
    """Put one mic back as it was before _install_endpoint. If Windows already took the
    effect off (a driver update or "Reset sound settings" rewrote the mic's effects),
    what's there now is the driver's own and stays: the notes are only dropped."""
    base = rf"{CAPTURE_KEY}\{guid}"
    with _StateKey(rf"{ENDPOINTS_KEY}\{guid}") as state:
        before = (state.get("Before") or ([],))[0] or []
        created = (state.get("FxCreated") or (0,))[0]
        if not before and state.get("Slot"):   # an early test build's notes
            pid = state.get("Slot")[0]
            before = [f"{FX % pid}=sz:{state.get('Original')[0]}"
                      if (state.get("Original") or ("",))[0] else f"{FX % pid}="]
            if (state.get("ModesCreated") or (0,))[0]:
                before.append(f"{MODES_KEY % state.get('ModesCreated')[0]}=")
            if (state.get("AssocCreated") or (0,))[0]:
                before.append(f"{FX % 0}=")
    try:
        with _BackupKey(base + r"\FxProperties", create=False) as fx:
            ours = any(_is_ours((fx.get(FX % p) or (None,))[0])
                       for p in (SFX, LFX, COMPOSITE_SFX))
            if ours:
                for item in before:
                    _put_back(fx, item)
            else:
                log.info("%s: Windows already took the effect off; left as it is", guid)
        if created and ours:
            _delete_if_empty(base + r"\FxProperties")
    except FileNotFoundError:
        pass   # the mic is gone
    winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, rf"{ENDPOINTS_KEY}\{guid}")
    log.info("mic effect taken off %s", guid)


def _delete_if_empty(path: str):
    with _BackupKey(path, create=False) as k:
        n = winreg.QueryInfoKey(k.h)
    if n[0] == 0 and n[1] == 0:
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        advapi.RegDeleteKeyW(winreg.HKEY_LOCAL_MACHINE, path)


def _make_ring():
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    # The audio engine runs as LOCAL SERVICE with a write-restricted token (so writing
    # needs WRITE RESTRICTED too); the board runs as the signed-in user. Nothing else:
    # not store apps (ALL APPLICATION PACKAGES, which a test build once added by hand).
    _run(["icacls", str(d), "/remove:g", "*S-1-15-2-1", "*S-1-15-2-2", "/T"])
    _run(["icacls", str(d), "/grant", "*S-1-5-19:(OI)(CI)M", "*S-1-5-33:(OI)(CI)M",
          "*S-1-5-11:(OI)(CI)M", "/T"])
    make_ring()
    try:
        (d / "ring.bin").unlink()   # the first test build's
    except OSError:
        pass


def admin_install(guid: str, slot: str | None = None) -> int:
    dll = bundled_dll()
    if not dll.is_file():
        log.error("no effect DLL at %s", dll)
        return 3
    _enable_privileges("SeBackupPrivilege", "SeRestorePrivilege")
    _audio_comes_back()
    _audio_service(False)
    try:
        # a name of its own per version: a copy Windows still holds can't block it
        digest = hashlib.sha256(dll.read_bytes()).hexdigest()[:12]
        target = install_dir() / f"obmic-{digest}.dll"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dll, target)
        _register_com(target)
        for old in [*install_dir().glob("obmic*.dll"), *_old_install_dirs()]:
            if old != target:
                _remove(old)
        _make_ring()
        for other in installed_on():   # one mic at a time; this one is done afresh
            _uninstall_endpoint(other)
        _install_endpoint(guid, slot)
    finally:
        _audio_service(True)
    return 0


def admin_uninstall() -> int:
    _enable_privileges("SeBackupPrivilege", "SeRestorePrivilege")
    _audio_comes_back()
    _audio_service(False)
    try:
        for guid in installed_on():
            _uninstall_endpoint(guid)
        _unregister_com()
        for d in (install_dir(), *_old_install_dirs()):
            _remove(d)
        try:
            winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, ENDPOINTS_KEY)
            winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, STATE_KEY)
        except OSError:
            pass
    finally:
        _audio_service(True)
    return 0


def _remove(path: Path):
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        try:
            path.unlink()
        except OSError:
            log.info("can't remove %s yet", path)


def anything_installed() -> bool:
    return bool(installed_on()) or registered_dll() is not None \
        or any(d.exists() for d in (install_dir(), *_old_install_dirs()))


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def cli(args: list[str]) -> int:
    """`--direct-mic install <endpoint guid> [sfx|lfx]` / `--direct-mic uninstall`: the
    admin copy. `--direct-mic remove`: the uninstaller's, not admin: runs the admin
    `uninstall` (Windows asks first) if Onion Board is on a mic at all. 0 when done."""
    if args == ["remove"]:
        if not anything_installed():
            return 0
        if not _is_admin():
            code = _elevated(["uninstall"], wait_s=120.0)
            return 1 if code is None else code
        args = ["uninstall"]
    logging.basicConfig(filename=str(data_dir().parent / "directmic-admin.log"),
                        level=logging.INFO, format="%(asctime)s %(message)s") \
        if data_dir().parent.exists() or _mkdir(data_dir().parent) else None
    try:
        if args[:1] == ["install"] and len(args) in (2, 3) and _GUID.fullmatch(args[1]) \
                and (len(args) == 2 or args[2] in SLOTS_FX):
            guid = args[1].lower()
            if guid not in {e["guid"] for e in capture_endpoints()}:
                return 2
            return admin_install(guid, args[2] if len(args) == 3 else None)
        if args == ["uninstall"]:
            return admin_uninstall()
        return 2
    except Exception:  # noqa: BLE001
        log.exception("mic effect %s failed", args[:1])
        return 1


def _mkdir(p: Path) -> bool:
    try:
        p.mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------- the app's side

def relaunch_params(args: list[str]) -> str:
    parts = []
    if not getattr(sys, "frozen", False):
        parts.append(f'"{Path(__file__).resolve().parent.parent / "main.py"}"')
    return " ".join(parts + [FLAG] + args)


def _elevated(args: list[str], wait_s: float = 90.0) -> int | None:
    """Run this app's admin copy with `args` (Windows asks first). Its exit code, or
    None if the prompt was turned down or it didn't finish."""
    return run_elevated(sys.executable, relaunch_params(args), wait_s)


def run_elevated(exe: str, params: str, wait_s: float = 90.0) -> int | None:
    """Run `exe` as admin, hidden (Windows asks first). Its exit code, or None if the
    prompt was turned down or it didn't finish in `wait_s`."""
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG),
                    ("hwnd", wintypes.HWND), ("lpVerb", wintypes.LPCWSTR),
                    ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int),
                    ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE),
                    ("hProcess", wintypes.HANDLE)]

    info = SHELLEXECUTEINFOW(cbSize=ctypes.sizeof(SHELLEXECUTEINFOW), fMask=0x40,
                             lpVerb="runas", lpFile=exe, lpParameters=params, nShow=0)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    if not shell32.ShellExecuteExW(ctypes.byref(info)) or not info.hProcess:
        log.info("%s %s not run (error %s)", Path(exe).name, params[-40:],
                 ctypes.get_last_error())
        return None
    try:
        if kernel32.WaitForSingleObject(info.hProcess, int(wait_s * 1000)) != 0:
            return None
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        return code.value
    finally:
        kernel32.CloseHandle(info.hProcess)


def install(mic_name: str | None) -> str | None:
    """Put the effect on the mic called `mic_name` (Windows asks for admin). None when
    done, else what went wrong, in plain words."""
    guid = endpoint_for(mic_name)
    if guid is None:
        return "That mic isn't plugged in (or Windows doesn't list it)."
    if not bundled_dll().is_file():
        return "This copy of Onion Board has no mic effect in it."
    code = _elevated(["install", guid])
    if code is None:
        return "Windows' admin prompt was turned down (or didn't finish)."
    if code:
        return f"Installing failed (code {code}). The log is in {data_dir().parent}."
    return None


def uninstall() -> str | None:
    code = _elevated(["uninstall"])
    if code is None:
        return "Windows' admin prompt was turned down (or didn't finish)."
    return f"Removing failed (code {code})." if code else None
