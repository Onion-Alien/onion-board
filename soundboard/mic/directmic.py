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

After that first prompt the admin steps go through the mic helper (soundboard/
michelper.py: a SYSTEM scheduled task running a frozen copy of this module's admin
part with its own DLL), with no prompt; `_elevated` tries it first and falls back to
Windows' prompt.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import logging
import mmap
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import winreg
from collections.abc import Collection, Mapping, Sequence
from typing import TYPE_CHECKING
from pathlib import Path

if TYPE_CHECKING:
    import numpy as np
else:
    try:
        import numpy as np
    except ImportError:   # the mic helper (soundboard/mic/michelper.py) ships without numpy:
        np = None         # it only runs the admin part, which never needs it

from soundboard.i18n import _
from soundboard.core.pollthread import PollThread

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
CUSHION_S = 0.11            # ...while something plays (the effect takes 0.12 at most): see
                            # Engine.cushion
BLOCK = 480                 # frames rendered per engine call (10 ms)
ALIVE_MS = 250              # effect heard from this recently: it's running
MIC_LIVE_MS = 150           # the clean mic arrived this recently: the board runs on it
POLL_S = 0.002              # how often the feed looks while a block is due (or overdue)
EARLY_S = 0.002             # the feed itself takes the mic: it looks again this long before
                            # the next block is due (blocks come a bit early now and then)
BLOCK_S = BLOCK / RATE
OTHER_BOARD_MS = 1000       # another board wrote this recently: it's still running

if np is not None:
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
RENDER_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render"
FX = "{d04e05a6-594b-4fb6-a80d-01af5eed7d1d},%d"   # PKEY_FX_* / PKEY_CompositeFX_*
# On a recording device Windows runs the effects in front of each app's stream: SFX (or
# LFX on drivers that only know the old kind), after the device's own EFX if it has one.
# An app asking for a raw stream (Chrome and Edge whenever the mic offers raw, Discord's
# Studio profile) skips SFX/MFX but not EFX, the endpoint's always-on effect: one copy
# for every app recording the mic. So the effect goes in EFX.
LFX, GFX, SFX, MFX, EFX = 1, 2, 5, 6, 7
SLOTS_FX = {"sfx": SFX, "lfx": LFX, "efx": EFX}     # where the effect goes on a mic
MODERN = (SFX, MFX, EFX)
LEGACY = (LFX, GFX)
COMPOSITE_SFX = 13                                  # PKEY_CompositeFX_StreamEffectClsid
COMPOSITE_EFX = 15                                  # PKEY_CompositeFX_EndpointEffectClsid
ENDPOINT_SLOTS = (EFX, COMPOSITE_EFX)               # raw streams get these too
OUR_SLOTS = (SFX, LFX, COMPOSITE_SFX, EFX, COMPOSITE_EFX)
# Equalizer APO works like this effect: it takes a slot and runs the effect it replaced,
# noted per mic under EAPO_KEY\<endpoint> as "<FX % pid>" (or "!VALUE": none) plus
# PreMixChild / PostMixChild. Put on the mic after this effect, it runs this one: that
# counts as on the mic, and this effect never wraps it back (obmic.cpp EAPO_*).
EAPO_KEY = r"SOFTWARE\EqualizerAPO\Child APOs"
EAPO_CLSIDS = ("{EACD2258-FCAC-4FF4-B36D-419E924A6D79}",   # its pre-mix effect
               "{EC1CC9CE-FAED-4822-828A-82A81A6F018F}")   # its post-mix effect
EAPO_NONE = "!VALUE"
DISABLE_SYSFX = "{1da5d803-d492-4edd-8c23-e0c0ffee7f0e},5"   # "Audio enhancements: off"
MODES_KEY = "{d3993a3f-99c2-4402-b5ec-a92a0367664b},%d"     # PKEY_*_ProcessingModes_...
MODE_DEFAULT = "{C18E2F7E-933D-4965-B7D1-1EEF228D2AF3}"     # AUDIO_SIGNALPROCESSINGMODE_DEFAULT
NAME_DESC = "{a45c254e-df1c-4efd-8020-67d146a850e0},2"       # "Microphone"
NAME_IFACE = "{b3f8fa53-0004-438e-9003-51a46e139bfc},6"      # "Realtek Audio"
NAME_ENUM = "{a45c254e-df1c-4efd-8020-67d146a850e0},24"      # "USB", "BTHHFENUM" (Bluetooth)
UNPLUGGED_STATES = (4, 8)   # DEVICE_STATE_NOTPRESENT, _UNPLUGGED (2 is switched off by hand)
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
    scripts/directmic/build_directmic.py built when run from source."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "directmic" / DLL_NAME
    return Path(__file__).resolve().parents[2] / "build" / "directmic" / DLL_NAME


# ---------------------------------------------------------------------- the ring

def _tick() -> int:
    return int(ctypes.windll.kernel32.GetTickCount64()) if sys.platform == "win32" \
        else int(time.monotonic() * 1000)


def new_ring_bytes() -> bytes:
    """A fresh ring file: header filled in, board off, no samples. (struct, not HEAD:
    the admin step makes it in the mic helper too, which has no numpy.)"""
    out = bytearray(FILE_BYTES)
    struct.pack_into("<4I", out, 0, MAGIC, VERSION, RATE, CAPACITY)   # magic .. capacity
    struct.pack_into("<I2fI", out, 36, MODE_REPLACE, 1.0, 1.0, MIC_CAPACITY)   # mode .. mic cap
    return bytes(out)


def make_ring_ok(path: Path) -> bool:
    """The ring file at `path` is there and this version's layout, at the board's rate
    (the effect plays the board's audio at the rate the file says)."""
    try:
        if not (path.is_file() and path.stat().st_size == FILE_BYTES):
            return False
        # unbuffered: a buffered read asks Windows for 8 KB, over the bytes a running
        # board keeps locked (RingWriter.claim), and failed: a board that was writing
        # made its own ring look "wiped", and an install tried to replace it
        with open(path, "rb", buffering=0) as f:
            raw = f.read(52)
        magic, version, rate, capacity = struct.unpack_from("<4I", raw, 0)
        mic_capacity, = struct.unpack_from("<I", raw, 48)
    except (OSError, ValueError, struct.error):
        return False
    return (magic, version, rate, capacity, mic_capacity) \
        == (MAGIC, VERSION, RATE, CAPACITY, MIC_CAPACITY)


def make_ring(path: Path | None = None) -> bool:
    """Create the ring file if it isn't there (or is another version's). The folder
    lets signed-in users write, so the board can do this without admin. True if it's
    usable now."""
    path = Path(path or ring_path())
    try:
        if make_ring_ok(path):
            return True
        # a name of its own: two boards starting at once mustn't write the same temp
        tmp = path.parent / f"ring2.{os.getpid()}-{int(time.monotonic() * 1000)}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0))
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(new_ring_bytes())
            os.replace(tmp, path)   # replaces the entry itself, never a link's target
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return True
    except OSError as e:
        # status() asks every few seconds: the same failure is logged in full once, not
        # a traceback each time (a missing folder is the admin step's to make: a repair)
        key = (str(path), type(e).__name__, e.errno)
        if key in _ring_failed:
            log.debug("still can't make the mic effect's ring at %s: %s", path, e)
        else:
            _ring_failed.add(key)
            log.info("can't make the mic effect's ring at %s", path, exc_info=True)
        return False


_ring_failed: set = set()   # make_ring's failures logged in full already


class RingWriter:
    """The board's end of the ring file."""

    def __init__(self, path: Path | None = None):
        path = Path(path or ring_path())
        self._claimed = False
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
        f = {name: self.h[name] for name in HEAD.names or ()}
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
        if self._claimed:
            return
        if sys.platform == "win32":
            import msvcrt

            # Held for this writer's lifetime, including startup and stalled callbacks.
            # A process crash closes the handle and releases it. Never on the APO thread.
            self._f.seek(84)
            try:
                msvcrt.locking(self._f.fileno(), msvcrt.LK_NBLCK, 4)
            except OSError:
                raise RuntimeError(_("Another Onion Board is already sending into your mic. "
                                     "Close it, and this one takes over.")) from None
        pid, me = int(self._get("board_pid")), os.getpid()
        if pid and pid != me and self._get("enabled") \
                and _tick() - int(self._btick[0]) < OTHER_BOARD_MS and _pid_alive(pid):
            raise RuntimeError(_("Another Onion Board is already sending into your mic. "
                                 "Close it, and this one takes over."))
        self._set("board_pid", me)
        self._claimed = True

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
        seq = int(self._get("sync_seq")) | 1
        self._set("sync_seq", seq)
        self._set("sync_wp", wp)
        self._set("sync_mic", mic)
        self._set("sync_seq", (seq + 1) & 0xFFFFFFFE)

    def clear_sync(self):
        seq = int(self._get("sync_seq")) | 1
        self._set("sync_seq", seq)
        self._set("sync_wp", 0)
        self._set("sync_mic", 0)
        self._set("sync_seq", (seq + 1) & 0xFFFFFFFE)

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
    is mono anyway). That's a thread, plus `pump()` from the board's own mic callback,
    which fires right after the effect ran on its block. The thread sleeps until the
    next block is due (it used to look every POLL_S, 500 times a second): when it
    takes the mic itself, it looks every POLL_S from just before then; when the mic
    callback takes it, the thread only steps in if that's late. Without the effect
    (nobody records the mic) the thread keeps time itself, a whole block at a time,
    so sounds still play at the right speed."""

    samplerate = RATE

    def __init__(self, callback, path: Path | None = None, mic_callback=None,
                 mode: int = MODE_REPLACE, lead_s: float = LEAD_S, voice_delay=None,
                 mic_stopped=None):
        self._callback = callback
        self._mic_callback = mic_callback
        # () called (under `lock`) when the clean mic stops coming, or the stream closes
        # while it came: the board's mic is back on its own device and rate
        self._mic_stopped = mic_stopped
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
        self.lock = self._lock   # held while a block is taken: see Engine._cb_mic
        self.active = False
        self.mic_live = False       # the board is running on the effect's clean mic
        self.mic_rate = 0
        self._mic_pos = 0
        self._publisher = 0
        self._acc = 0.0
        self._start = time.perf_counter()
        self._made = 0
        self._buf = np.zeros((BLOCK, 2), np.float32)
        # when the thread looks next (see _wait): the last clean mic taken (perf_counter),
        # how long a block of it lasts, and whether the thread took it (or the mic
        # callback did); on its own clock, when the next whole block is due
        self._fed_at: float | None = None
        self._fed_period = BLOCK_S
        self._fed_here = True
        self._due_at: float | None = None
        # since when (perf_counter) the clean mic has been nothing but exact zeros
        self._zeros_since: float | None = None
        # what has failed on the feed's thread and been logged: once each, not every block
        self._logged: set[str] = set()

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
            if self.mic_live:
                self.mic_live = False
                self._stopped()
            self._ring.close()

    def _stopped(self):
        if self._mic_stopped is not None:
            try:
                self._mic_stopped()
            except Exception:  # noqa: BLE001 - the feed goes on regardless
                log.exception("mic stopped callback")

    def set_mode(self, mode: int):
        self.mode = mode
        self._ring.set_mode(mode)

    def set_lead(self, seconds: float):
        """How far behind the board the effect reads from now on."""
        try:
            self._ring.set_lead(seconds)
        except (ValueError, KeyError, AttributeError):   # closed
            return
        self.latency = seconds

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

    def mic_silent_s(self) -> float:
        """How long the clean mic has been nothing but exact zeros: a mic stuck that way
        after an audio restart (every app hears nothing). A quiet room still has noise,
        so a working mic is never at it long. 0 at the first real sample, and without
        any clean mic (nobody records the mic: nothing to tell)."""
        since = self._zeros_since
        return 0.0 if since is None or not self.mic_live else time.perf_counter() - since

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

    def _catch_up(self):
        """(Re)starting on the clean mic: the effect went on reading meanwhile. Paced by
        the mic from here on, the board never got back a lead ahead of where it reads,
        and the effect waits for just that: after a quick reopen (a buffering change)
        or a change of publisher, the board's sounds stayed off the mic. Silence up to
        a lead past it fixes that."""
        ring = self._ring
        slots = ring.live_slots()
        if not len(slots):
            return
        short = (int(slots["read_pos"].max()) + int(slots["lead"].max()) + 2 * BLOCK
                 - ring.write_pos)
        if 0 < short <= CAPACITY // 4:
            ring.write(np.zeros(short, np.float32))

    def _pump(self):
        ring = self._ring
        now = _tick()
        if ring.mic_live(now):
            wp, rate = ring.mic_write_pos, ring.mic_rate
            publisher = int(ring._get("publisher"))
            gap = wp - self._mic_pos
            # A new effect can take over before the old mic's heartbeat expires.
            # Its recorders read on during that gap, so restore our lead here too.
            if (not self.mic_live or publisher != self._publisher or rate != self.mic_rate
                    or gap < 0 or gap > MIC_CAPACITY // 2):
                self._publisher = publisher
                self._mic_pos, self.mic_rate, self._acc = wp, rate, 0.0   # (re)start here
                self.mic_live = True
                self._zeros_since = None
                self._catch_up()
                ring.heartbeat()
                return
            if gap == 0:
                ring.heartbeat()
                return
            x = ring.read_mic(self._mic_pos, gap)
            self._mic_pos = wp
            if x.any():
                self._zeros_since = None
            elif self._zeros_since is None:
                self._zeros_since = time.perf_counter()
            # (never counted as more than a block: after a hiccup two can come at once,
            # and the next one is still only a block away)
            self._fed_at, self._fed_period = time.perf_counter(), min(gap / rate, BLOCK_S)
            self._fed_here = threading.current_thread() is self._thread
            if self._mic_callback is not None:
                # guarded per block: one bad block must not end the feed (the engine's
                # own guard counts it in cb_errors; this is for any other callback)
                try:
                    self._mic_callback(x, rate)
                except Exception:  # noqa: BLE001 - that block of the mic is lost, no more
                    self._log_once("mic callback")
            self._acc += gap * RATE / rate
            k = int(self._acc)
            self._acc -= k
            self._render(k)
            ring.set_sync(ring.write_pos, max(0, wp - int(round(self._delay() * rate / RATE))))
            self._start, self._made = time.perf_counter(), 0
            return
        if self.mic_live:   # the mic stopped: keep time from here on our own
            self.mic_live = False
            self._zeros_since = None
            self._fed_at = None
            ring.clear_sync()
            self._stopped()
            self._start, self._made = time.perf_counter(), 0
        due = int((time.perf_counter() - self._start) * RATE)
        if due - self._made > RATE // 5:   # stalled (sleep, a hang): don't catch up
            self._made = due - BLOCK
        need = due - self._made
        if ring.effect_alive(now):
            # the effect reads the ring on its own clock (no clean mic from it): keep
            # the ring full, a whole block ahead as soon as one is started, and sleep
            # till the next one starts. (In small steps every POLL_S it ran the engine
            # 400 times a second, not 100: four times the CPU, and the window waited.)
            if need > 0:
                need += -need % BLOCK
            self._due_at = self._start + (self._made + max(need, 0)) / RATE
        else:
            # nobody listens: render whole blocks as they come due, and sleep between
            need -= need % BLOCK
            self._due_at = self._start + (self._made + need + BLOCK) / RATE
        if need > 0:
            self._made += need
            self._render(need)
        else:
            ring.heartbeat()

    def _wait(self) -> float:
        """How long the thread sleeps before it looks again."""
        now = time.perf_counter()
        if self.mic_live:
            if self._fed_at is None:
                return POLL_S
            # the thread takes the mic: look from just before the next block is due.
            # The mic callback does: step in only if it's late with the next one.
            nxt = self._fed_at + self._fed_period + (-EARLY_S if self._fed_here else POLL_S)
        elif self._due_at is not None:
            nxt = self._due_at
        else:
            return POLL_S
        return min(max(nxt - now, POLL_S if self.mic_live else 0.0005), BLOCK_S + POLL_S)

    def _log_once(self, what: str):
        if what not in self._logged:
            self._logged.add(what)
            log.exception("mic effect feed: %s failed", what)

    def _run(self):
        # the try is inside the loop: one exception skips that block, and the feed goes
        # on (outside it, one stopped the thread for good, and nothing reported it)
        while not self._stop.is_set():
            try:
                self.pump()
                wait = self._wait()
            except Exception:  # noqa: BLE001 - logged once; the next block is tried as usual
                self._log_once("pump")
                wait = POLL_S
            time.sleep(wait)


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
    """Every recording device Windows knows: {"guid", "name", "active", "out": unplugged
    (or its USB or Bluetooth headset switched off), "device": the part of the name in
    brackets ("AirPods Pro Hands-Free"), "bt": a Bluetooth headset's}."""
    return _endpoints(CAPTURE_KEY)


def render_endpoints() -> list[dict]:
    """Every playback device Windows knows, as capture_endpoints()."""
    return _endpoints(RENDER_KEY)


def _endpoints(key: str) -> list[dict]:
    found = []
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key)
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
                    enum = _value(p, NAME_ENUM)
            except OSError:
                continue
            name = f"{desc} ({iface})" if iface else desc
            found.append({"guid": guid.lower(), "name": name, "active": state == 1,
                          "out": state in UNPLUGGED_STATES, "device": iface or "",
                          "bt": str(enum or "").upper().startswith("BTH")})
    return found


_HANDS_FREE = re.compile(r"\s*hands[- ]?free(\s+ag\s+audio)?\s*$", re.I)


def _sound_only(mic_name: str) -> str | None:
    """The name of the Bluetooth headset `mic_name` is the mic of, when Windows has the
    headset on for sound but its mic off: a Bluetooth headset (AirPods most of all)
    connects its sound and its phone-call mic separately, and the mic half drops out
    while the sound keeps playing (a phone took it, or Windows never connected it).
    None for anything else. Reads the registry: not on the UI thread."""
    off = [e for e in _near(mic_name, [e for e in capture_endpoints() if not e["active"]])
           if e.get("bt")]
    if not off:
        return None
    halves = {_squash(_HANDS_FREE.sub("", e.get("device", ""))) for e in off} - {""}
    for e in render_endpoints():
        headset = _HANDS_FREE.sub("", e.get("device", ""))
        if e["active"] and e.get("bt") and _squash(headset) in halves:
            return headset
    return None


def endpoint_for(name: str | None) -> str | None:
    """The endpoint GUID of the active recording device called `name` (as PortAudio
    lists it: its name may be cut short, so a prefix match counts)."""
    return mic_lookup(name)[0]


def mic_lookup(name: str | None) -> tuple[str | None, str]:
    """(endpoint GUID, "") of the active mic called `name`, else (None, why): "off"
    Windows knows it but it's unplugged or switched off, "unsure" two active mics start
    like that name (a cut-short one) and either could be it, "gone" Windows doesn't
    know it at all (an old mic, or renamed: "Microphone (2- USB Audio)" in another port).
    The why is counted (FAIL_KINDS no-mic-<why>), never the name."""
    if not name:
        return None, "gone"
    endpoints = capture_endpoints()
    active = [e for e in endpoints if e["active"]]
    guid = _match(name, active)
    if guid is not None:
        return guid, ""
    # the engine finds a saved name more loosely (engine.find_device): the mic it opened
    # (and the meter shows working) is the one meant. Uninstall feedback: "it said it
    # couldn't find my mic, but it was showing it picked up my mic sound just fine"
    opened = _engine_name(name)
    if opened and opened != name:
        exact = [e for e in active if _squash(e["name"]) == _squash(opened)]
        if len(exact) == 1:
            return exact[0]["guid"], ""
    # the same mic in another USB port: Windows numbers it ("Microphone (2- USB Audio)"
    # for the saved "Microphone (USB Audio)", or the other way round). Only when one fits
    same = [e for e in active if _unnumbered(e["name"]) == _unnumbered(name)]
    if len(same) == 1:
        return same[0]["guid"], ""
    if len(_near(name, active)) > 1:
        return None, "unsure"
    others = [e for e in endpoints if not e["active"]]
    if _near(name, others):
        return None, "off"
    return None, "gone"


def fallback_mic(name: str | None) -> str | None:
    """The mic to set up instead when the picked `name` isn't one Windows knows (none
    picked, an old mic, renamed): Windows' default recording device, the one the board
    records then too. Never a virtual cable (our own sounds fed back in), never `name`
    itself, and None unless Windows has it on now. An unplugged or switched-off mic
    isn't swapped: it's the one meant, and it's back when it's plugged in."""
    try:
        from soundboard.audio import engine
        other = engine.default_device_name("input")
    except Exception:  # noqa: BLE001 - no audio devices to ask: nothing to fall back on
        log.debug("default mic lookup failed", exc_info=True)
        return None
    if not other or other == name or engine.is_virtual(other):
        return None
    return other if endpoint_for(other) is not None else None


def _engine_name(name: str) -> str | None:
    """The name of the recording device the engine opens for the saved `name`."""
    try:
        from soundboard.audio import engine
        idx = engine.find_device("input", name)
        return None if idx is None else engine.list_name(idx)
    except Exception:  # noqa: BLE001 - no audio devices to ask: the registry's answer stands
        log.debug("engine name lookup failed", exc_info=True)
        return None


def _squash(name: str) -> str:
    """A name with Windows' odd spacing and case ironed out (as engine.find_device)."""
    return " ".join(name.split()).lower()


def _unnumbered(name: str) -> str:
    """_squash(name) without the port number Windows puts in front of a second copy's
    name: "Microphone (2- USB Audio)" -> "microphone (usb audio)"."""
    return re.sub(r"\(\d+-\s*", "(", _squash(name))


def _near(name: str, mics: list[dict]) -> list[dict]:
    n = _squash(name)
    return [e for e in mics if _squash(e["name"]).startswith(n)
            or n.startswith(_squash(e["name"]))]


def _match(name: str, active: list[dict]) -> str | None:
    for e in active:
        if e["name"] == name:
            return e["guid"]
    for e in active:
        if _squash(e["name"]) == _squash(name):
            return e["guid"]
    near = _near(name, active)
    # one mic only: two that start the same (a cut-short name) could be the wrong one
    return near[0]["guid"] if len(near) == 1 else None


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
_status_gen = [0]          # forget_status() bumps it: a refresh started before is dropped
_status_busy: set = set()  # mic names being re-checked on a thread
# One thread kept for the re-checks: starting a new one each time made the window wait
# in Thread.start until Windows had it running (a 2.2.1 freeze)
_status_poll = PollThread("mic-effect-status")
_status_lock = threading.Lock()
_unplugged: dict = {}   # mic name -> unplugged at the last status() check
_sound_only_on: dict = {}   # mic name -> its Bluetooth headset, on for sound only (or None)
STATUS_S = 2.0


def forget_status():
    with _status_lock:
        _status_cache.clear()
        _unplugged.clear()
        _sound_only_on.clear()
        _status_gen[0] += 1


def status(mic_name: str | None = None) -> str:
    """Where Onion Board stands on the mic called `mic_name` (any mic it's on if None):
      'missing'   not attached to any mic
      'other'     attached, but to another mic
      'wiped'     attached, but Windows (a driver or Windows update) took the effect off,
                  or its DLL file (or that file's registration) is gone
      'outdated'  attached, but with another version of the effect than this app's
      'ready'     attached and working
    'wiped' and 'outdated' need the one-click repair (attaching again).

    The first answer is worked out at once; after that it's re-checked every STATUS_S
    on a thread, and the last answer comes back meanwhile. The check reads the
    registry and the ring file, and the window asks every second: on a busy disk the
    stat alone froze it for 6 s (1.9.7)."""
    with _status_lock:
        hit = _status_cache.get(mic_name)
        now = time.monotonic()
        if hit and now - hit[0] < STATUS_S:
            return hit[1]
        if hit:
            if mic_name not in _status_busy:
                _status_busy.add(mic_name)
                gen = _status_gen[0]
                _status_poll.run(lambda: _refresh_status(mic_name, gen))
            return hit[1]
        gen = _status_gen[0]
    result = _status(mic_name)
    with _status_lock:
        if gen == _status_gen[0]:
            _status_cache[mic_name] = (time.monotonic(), result)
    return result


def _refresh_status(mic_name: str | None, gen: int):
    try:
        result = _status(mic_name)
    except Exception:  # noqa: BLE001 - keep the last answer; tried again later
        log.warning("couldn't check the mic effect", exc_info=True)
        result = None
    with _status_lock:
        _status_busy.discard(mic_name)
        if gen != _status_gen[0]:
            return
        hit = _status_cache.get(mic_name)
        _status_cache[mic_name] = (time.monotonic(),
                                   result if result is not None else hit[1] if hit else "missing")


def needs_repair(state: str) -> bool:
    """Windows took it off the mic: it has to be put back (one prompt)."""
    return state == "wiped"


def works(state: str) -> bool:
    """On the mic and working. An older copy of the effect ('outdated') still works:
    the update is offered, not forced."""
    return state in ("ready", "outdated")


def unplugged(mic_name: str | None) -> bool:
    """The mic called `mic_name` isn't there right now: unplugged, its headset or Windows
    switched it off, or Windows forgot it (as the last status() for it found: no I/O)."""
    return bool(mic_name) and _unplugged.get(mic_name, False)


def sound_only(mic_name: str | None) -> str | None:
    """The headset's name when the mic called `mic_name` isn't there because it's a
    Bluetooth headset's that Windows has on for sound only, its mic off (as the last
    status() for it found). "Is it plugged in?" is wrong then: it is, and it plays."""
    return _sound_only_on.get(mic_name) if mic_name else None


def _status(mic_name: str | None) -> str:
    on = installed_on()
    if mic_name is None:
        return _state(on[0], on) if on else "missing"
    guid = endpoint_for(mic_name)
    gone = _unplugged[mic_name] = guid is None and _not_here(mic_name)
    _sound_only_on[mic_name] = _sound_only(mic_name) if gone else None
    if not on:
        return "missing"
    return _state(guid, on)


def _not_here(mic_name: str) -> bool:
    """The mic isn't there: unplugged, switched off, or forgotten by Windows once it was
    pulled out (and nothing the engine can open goes by that name either). Nothing to
    set up or repair until it's back: the card asks whether it's plugged in, no louder."""
    why = mic_lookup(mic_name)[1]
    return why == "off" or why == "gone" and _engine_name(mic_name) is None


def _state(guid: str | None, on: list[str]) -> str:
    """status() for one mic by its endpoint GUID, given installed_on()."""
    if not on:
        return "missing"
    if guid not in on:
        return "other"
    dll = registered_dll()
    # the DLL deleted (a cleaner, an antivirus) or its registration gone: Windows has
    # nothing to load, so sounds stop reaching the mic. Not 'outdated' (which counts as
    # working, so nothing happened): the repair copies it back.
    if not effect_in_place(guid) or dll is None or not dll.is_file() or not make_ring():
        return "wiped"
    if not same_dll(dll, bundled_dll()) \
            or installed_slot(guid) in (SFX, COMPOSITE_SFX):   # raw streams skip it
        return "outdated"
    return "ready"


def status_on(guid: str) -> str:
    """status() for the mic with endpoint GUID `guid`, worked out now (no cache)."""
    return _state(guid.lower(), installed_on())


def mics(names: Sequence[str] = ()) -> list[dict]:
    """The mics the recovery card offers, each by its endpoint GUID (two mics can share
    a name): every plugged-in one, plus an unplugged one the effect is still on.
    {"guid", "name", "active", "state" (as status()), "pa": the name in `names` (the
    app's device list) that is this mic, or None}. Reads the registry: not on the UI
    thread."""
    found = capture_endpoints()
    on = installed_on()
    active = [e for e in found if e["active"]]
    pa = {}
    for n in names:
        # a name two plugged-in mics share can't say which it is: neither gets it
        twins = sum(e["name"] == n for e in active) > 1
        guid = None if twins else _match(n, active)
        if guid and guid not in pa:
            pa[guid] = n
    out = []
    for e in found:
        if not e["active"] and e["guid"] not in on:
            continue
        try:
            state = _state(e["guid"], on)
        except OSError:
            state = "unknown"
        out.append({**e, "state": state, "pa": pa.get(e["guid"])})
    out.sort(key=lambda m: (not m["active"], m["name"].lower()))
    return out


def installed_slot(guid: str) -> int | None:
    """The effect slot the effect was put in on this mic (None: not on it)."""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{ENDPOINTS_KEY}\{guid}") as k:
            return int(winreg.QueryValueEx(k, "Slot")[0])
    except (OSError, ValueError):
        return None


def endpoint_wide() -> bool:
    """The effect sits in the mic's endpoint effect: every app recording the mic gets it,
    raw streams too, through one shared copy (so its stream count isn't per app)."""
    return any(installed_slot(g) in ENDPOINT_SLOTS for g in installed_on())


def effect_in_place(guid: str) -> bool:
    """Our effect is still in one of the mic's effect slots (a driver update rewrites
    them, Windows' "Reset sound settings" too)."""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            rf"{CAPTURE_KEY}\{guid}\FxProperties") as k:
            slots = [_value(k, FX % pid) for pid in OUR_SLOTS]
    except OSError:
        return False
    return any(_is_ours(v) for v in slots) \
        or any(_is_eapo(v) for v in slots) and bool(eapo_runs_us(guid))


def _is_eapo(value) -> bool:
    """An effect slot's value is Equalizer APO's effect."""
    return isinstance(value, str) and value.upper() in EAPO_CLSIDS


def eapo_runs_us(guid: str) -> list[str]:
    """The names of Equalizer APO's notes for this mic that hold this effect (it was put
    on the mic after this one, and runs it): [] if none, or no Equalizer APO."""
    out = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{EAPO_KEY}\{guid}") as k:
            i = 0
            while True:
                try:
                    name, value, _kind = winreg.EnumValue(k, i)
                except OSError:
                    break
                i += 1
                if _is_ours(value):
                    out.append(name)
    except OSError:
        pass
    return out


def _eapo_hand_back(guid: str, original: str) -> bool:
    """Equalizer APO runs this effect on this mic: point its notes at the effect this one
    ran (`original`, "" for none) instead, so it runs that. False if it doesn't run us."""
    names = eapo_runs_us(guid)
    if not names:
        return False
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{EAPO_KEY}\{guid}", 0,
                        winreg.KEY_SET_VALUE) as k:
        for name in names:
            # its slot notes say "none" with a word, its *Child notes with ""
            gone = EAPO_NONE if name.startswith("{") else ""
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, original or gone)
    log.info("%s: Equalizer APO runs the mic's own effect again", guid)
    return True


def without_ours(value):
    """An effect slot's value with this effect taken out: (changed, new value or None
    to delete it). Only our own CLSID goes; every other effect in a list stays."""
    if isinstance(value, list):
        rest = [x for x in value if not (isinstance(x, str) and x.upper() == CLSID)]
        return len(rest) != len(value), (rest or None)
    return (True, None) if _is_ours(value) else (False, value)


def _fx_values(guid: str) -> dict:
    """Every effect-slot value on a mic ({name: value}); {} if it has none."""
    out = {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            rf"{CAPTURE_KEY}\{guid}\FxProperties") as k:
            i = 0
            while True:
                try:
                    name, value, _kind = winreg.EnumValue(k, i)
                except OSError:
                    break
                i += 1
                if name.lower().startswith(FX.split(",")[0].lower() + ","):
                    out[name] = value
    except OSError:
        pass
    return out


def leftovers(guid: str) -> bool:
    """Something of Onion Board's is still on this mic although the notes say it isn't
    (a set-up cut off, notes lost): our CLSID in one of its effect slots, or, with the
    effect on no mic at all, its registration or files. Reads only: no admin."""
    if guid.lower() in installed_on():
        return True   # on it properly: Remove takes it off
    if any(without_ours(v)[0] for v in _fx_values(guid).values()):
        return True
    return not installed_on() and anything_installed()


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
        assert h.value is not None   # it opened
        self.h: int | winreg.HKEYType = h.value
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


def _run(cmd: list[str], timeout: float = 60.0) -> int:
    """Run a command, hidden. Its exit code; -1 if it hung (it's stopped after `timeout`)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout,
                           creationflags=_CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        log.warning("%s: no answer in %.0f s, stopped", " ".join(cmd), timeout)
        return -1
    if r.returncode:
        log.warning("%s -> %s %s", " ".join(cmd), r.returncode, (r.stdout + r.stderr).strip())
    return r.returncode


AUDIO_SERVICES = ("AudioEndpointBuilder", "Audiosrv")
_SERVICE_NAME = re.compile(r"[A-Za-z0-9_.-]{1,80}")


def _running_dependents() -> list[str]:
    """The services running now that depend on Windows' audio ("Windows MIDI Service",
    "Agent Activation Runtime", some sound-card vendors' own): stopping the audio stops
    them too, and Windows doesn't start them again with it, so they're started by hand."""
    script = (f"Get-Service -Name {','.join(AUDIO_SERVICES)} -DependentServices "
              "-ErrorAction SilentlyContinue | Where-Object Status -eq Running | "
              "ForEach-Object Name")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                           capture_output=True, text=True, errors="replace", timeout=30,
                           creationflags=_CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        log.warning("couldn't list the services that depend on the audio")
        return []
    names = [n.strip() for n in r.stdout.splitlines()]
    return [n for n in dict.fromkeys(names) if _SERVICE_NAME.fullmatch(n)
            and n.lower() not in {s.lower() for s in AUDIO_SERVICES}]


def _audio_comes_back(dependents: Sequence[str] = ()):
    """A small helper that starts Windows' audio again once this process ends, however
    it ends: killed half-way or crashed, the PC must never be left without sound.
    (Starting a service that's already running does nothing.)"""
    names = [*AUDIO_SERVICES, *(n for n in dependents if _SERVICE_NAME.fullmatch(n))]
    script = (f"Wait-Process -Id {os.getpid()} -ErrorAction SilentlyContinue; "
              + "; ".join(f"Start-Service '{n}' -ErrorAction SilentlyContinue" for n in names))
    cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]
    for flags in (_CREATE_NO_WINDOW | 0x01000000, _CREATE_NO_WINDOW):   # out of our job
        try:
            subprocess.Popen(cmd, creationflags=flags, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            continue
    log.warning("no helper to bring the audio back if this stops half-way")


def _services_stopped() -> bool:
    """Windows' audio is really stopped. The endpoint builder re-reads a mic's effect
    settings when it starts, so a stop that silently failed leaves the change unread
    until a restart: worth knowing."""
    script = ("(Get-Service -Name " + ",".join(AUDIO_SERVICES) + " -ErrorAction SilentlyContinue"
              " | Where-Object Status -ne 'Stopped' | Measure-Object).Count")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                           capture_output=True, text=True, errors="replace", timeout=15,
                           creationflags=_CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.stdout.strip() == "0"


def _audio_service(start: bool, dependents: Sequence[str] = ()) -> bool:
    """Stop / start Windows' audio. The endpoint builder reads the mics' effect settings
    when it starts, so it goes too (the audio service depends on it). `dependents`: the
    services that were running on it (_running_dependents), started again after it.
    True when the audio ended up in the state asked for (a stop that didn't take is
    logged: the effect's change may not be read until a restart)."""
    if start:
        _run(["net", "start", "AudioEndpointBuilder"])
        _run(["net", "start", "audiosrv"])
        for name in dependents:
            if _SERVICE_NAME.fullmatch(name):
                _run(["net", "start", name], timeout=30.0)
        return True
    _run(["net", "stop", "audiosrv", "/y"])
    _run(["net", "stop", "AudioEndpointBuilder", "/y"])
    if _stopped_soon():
        return True
    # a dependency held it, or net gave up while it was still stopping: once more
    _run(["net", "stop", "audiosrv", "/y"])
    _run(["net", "stop", "AudioEndpointBuilder", "/y"])
    if _stopped_soon():
        return True
    log.warning("Windows' audio wouldn't stop: the mic effect may need a restart to take")
    return False


STOP_WAIT_S = 10.0   # how long a service still "stopping" gets before it counts as stuck


def _stopped_soon(wait_s: float | None = None) -> bool:
    """_services_stopped(), given up to STOP_WAIT_S: a slow sound-card driver keeps the
    audio "stopping" for seconds after net stop has returned (exit code 6 on a PC
    where it would have stopped a moment later)."""
    give_up = time.monotonic() + (STOP_WAIT_S if wait_s is None else wait_s)
    while True:
        if _services_stopped():
            return True
        if time.monotonic() >= give_up:
            return False
        time.sleep(1.0)


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


def pick_slot(values: Mapping[int, object]) -> tuple[str, int]:
    """Which effect slot the effect takes on a mic whose FxProperties hold `values`
    ({pid: value}): ('wrap', LFX) on a driver with only the old kind of effects;
    ('composite', 15) joins an endpoint effect list Windows chains by itself; otherwise
    ('wrap', EFX), the endpoint effect raw streams get too. 'wrap' replaces that slot's
    effect, and the effect runs the one it replaced first."""
    if any(values.get(p) for p in LEGACY) and not any(values.get(p) for p in MODERN) \
            and not values.get(COMPOSITE_SFX):
        return "wrap", LFX
    if values.get(COMPOSITE_EFX):
        return "composite", COMPOSITE_EFX
    return "wrap", EFX


def _original(values: Mapping[int, object], pid: int) -> str:
    """The effect the effect runs first in slot `pid`: the slot's own, or (a mic whose
    driver has no endpoint effect) its old-style LFX, which a modern slot switches off."""
    old = values.get(pid)
    if not old and pid in (SFX, EFX) and not values.get(EFX):
        old = values.get(LFX)
    return old if isinstance(old, str) and not _is_ours(old) else ""


def _install_endpoint(guid: str, slot: str | None):
    """Put the effect on one mic. Everything changed is noted under ENDPOINTS_KEY so
    _uninstall_endpoint can put it back exactly."""
    base = rf"{CAPTURE_KEY}\{guid}"
    with _BackupKey(base + r"\FxProperties") as fx, \
            _StateKey(rf"{ENDPOINTS_KEY}\{guid}") as state:
        values = {p: (fx.get(FX % p) or (None,))[0]
                  for p in (*MODERN, *LEGACY, COMPOSITE_SFX, COMPOSITE_EFX)}
        kind, pid = pick_slot(values) if not slot else ("wrap", SLOTS_FX[slot])
        if _is_eapo(values.get(pid)) and eapo_runs_us(guid):
            # Equalizer APO went on after this effect and runs it: wrapping it back
            # would make each run the other. Notes kept (or, lost, made: nothing to
            # put back in the slot, Equalizer APO is handed the effect it ran)
            if not state.get("Slot"):
                state.set("Slot", winreg.REG_DWORD, pid)
                state.set("Before", winreg.REG_MULTI_SZ, [])
                state.set("Original", winreg.REG_SZ, "")
            log.info("mic effect on %s: run by Equalizer APO (slot %s)", guid, pid)
            return
        modes = SFX if pid in (SFX, COMPOSITE_SFX) else EFX if pid in ENDPOINT_SLOTS else None
        state.set("FxCreated", winreg.REG_DWORD, 1 if fx.created else 0)
        state.set("Slot", winreg.REG_DWORD, pid)
        # every value this touches, as it was, to put back later (written before anything
        # changes, so a step cut off half-way can still be undone)
        names = (FX % pid, MODES_KEY % SFX, MODES_KEY % EFX, FX % LFX, FX % GFX, DISABLE_SYSFX)
        state.set("Before", winreg.REG_MULTI_SZ, [_note(n, fx.get(n)) for n in names])
        if kind == "composite":
            cur = list(values[pid] or [])
            fx.set(FX % pid, winreg.REG_MULTI_SZ,
                   [CLSID] + [c for c in cur if c.upper() != CLSID])
            state.set("Original", winreg.REG_SZ, "")
        else:
            state.set("Original", winreg.REG_SZ, _original(values, pid))
            fx.set(FX % pid, winreg.REG_SZ, CLSID)
        if modes is not None:
            if not fx.get(MODES_KEY % modes):
                fx.set(MODES_KEY % modes, winreg.REG_MULTI_SZ, [MODE_DEFAULT])
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


def _note_value(item: str):
    """The value a "Before" note puts back (None: it wasn't there). A raw note (an odd
    kind) can't be compared to what's there: `_MISSING`."""
    _, _, value = item.partition("=")
    if not value:
        return None
    if value.startswith("multi:"):
        return value[6:].split("|") if value[6:] else []
    if value.startswith("dword:"):
        return int(value[6:])
    if value.startswith("raw:"):
        return _MISSING
    return value.removeprefix("sz:")


_MISSING = object()


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
    what's there now is the driver's own and stays: the notes are only dropped. If the
    uninstall itself was cut off half-way (a crash, a reboot), the slot already matches
    the notes and the rest of the change is finished now."""
    base = rf"{CAPTURE_KEY}\{guid}"
    with _StateKey(rf"{ENDPOINTS_KEY}\{guid}") as state:
        before = (state.get("Before") or ([],))[0] or []
        created = (state.get("FxCreated") or (0,))[0]
        slot = (state.get("Slot") or (None,))[0]
        original = (state.get("Original") or ("",))[0]
        if not before and slot is not None:   # an early test build's notes
            before = [f"{FX % slot}=sz:{original}" if original else f"{FX % slot}="]
            modes_created = (state.get("ModesCreated") or (0,))[0]
            if modes_created:
                before.append(f"{MODES_KEY % modes_created}=")
            if (state.get("AssocCreated") or (0,))[0]:
                before.append(f"{FX % 0}=")
    try:
        with _BackupKey(base + r"\FxProperties", create=False) as fx:
            if slot is None:
                restore = any(_is_ours((fx.get(FX % p) or (None,))[0]) for p in OUR_SLOTS)
            else:
                cur = (fx.get(FX % slot) or (None,))[0]
                want = _note_value(next((b for b in before
                                         if b.partition("=")[0] == FX % slot),
                                        f"{FX % slot}="))
                # our CLSID still in the slot, or the slot already matches the notes (an
                # uninstall cut off half-way): finish it. A slot holding some other value
                # means Windows reset the mic: leave it all.
                restore = _is_ours(cur) or cur == want
                if not restore and _is_eapo(cur):
                    # Equalizer APO took the slot after this effect and runs it: it
                    # runs the mic's own effect again instead. The rest stays as it set
                    # it (the old "Audio enhancements: off" would switch it off too)
                    _eapo_hand_back(guid, original)
            if restore:
                for item in before:
                    _put_back(fx, item)
            else:
                log.info("%s: Windows already took the effect off; left as it is", guid)
        if created and restore:
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


# Who may do what in the data folders. %ProgramData%\OnionBoard: admins only (its logs
# are the admin step's). MicPlugin: the audio engine (LOCAL SERVICE with a write-
# restricted token, so WRITE RESTRICTED too) and signed-in users make and change files
# in it, but can't delete, rename or swap the folder itself, nor make folders in it.
# Nothing for store apps. Owner: Administrators.
_READ = "0x1200a9"          # read & run
_FOLDER_WRITE = "0x1201bb"  # read, make files, write attributes: no delete, no subfolders
_MODIFY = "0x1301bf"
_BASE_SDDL = f"O:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;{_READ};;;BU)"
_MIC_SDDL = _BASE_SDDL + "".join(f"(A;;{_FOLDER_WRITE};;;{s})(A;OICIIO;{_MODIFY};;;{s})"
                                 for s in ("AU", "LS", "WR"))
_ADMIN_SIDS = ("S-1-5-32-544", "S-1-5-18")   # Administrators, SYSTEM
_REPARSE = 0x400                             # FILE_ATTRIBUTE_REPARSE_POINT


def _is_link(path: Path) -> bool:
    """A symlink, junction or other reparse point (never followed by the admin step)."""
    try:
        return bool(getattr(os.lstat(path), "st_file_attributes", 0) & _REPARSE)
    except OSError:
        return False


def _remove_entry(path: Path):
    """Remove one folder entry itself, never what a link points at."""
    if _is_link(path):
        try:
            os.rmdir(path)    # a junction / folder link
        except OSError:
            os.unlink(path)   # a file link
    elif path.is_dir():
        shutil.rmtree(path)   # (doesn't follow links inside)
    else:
        path.unlink()


def _secure_dir(path: Path, sddl: str) -> str | None:
    """Make `path` a real folder owned by Administrators with exactly `sddl`'s access, set
    on an open handle to the folder itself: never through a link, and without touching
    anything inside (no inheritance walk a planted link could steer). Its owner SID
    before (None if it was made just now)."""
    from ctypes import wintypes
    if _is_link(path) or (path.exists() and not path.is_dir()):
        log.warning("%s wasn't a plain folder: replaced", path)
        _remove_entry(path)
    made = not path.exists()
    if made:
        path.mkdir()
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.HANDLE]
    kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    advapi.SetKernelObjectSecurity.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p]
    advapi.GetSecurityInfo.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.DWORD,
                                       ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
                                       ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.POINTER(ctypes.c_void_p)]
    advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
    # READ_CONTROL | WRITE_DAC | WRITE_OWNER; FILE_FLAG_BACKUP_SEMANTICS | OPEN_REPARSE_POINT
    h = kernel.CreateFileW(str(path), 0x000E0000, 7, None, 3, 0x02200000, None)
    if h in (None, wintypes.HANDLE(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        info = (ctypes.c_ulong * 13)()   # BY_HANDLE_FILE_INFORMATION
        if not kernel.GetFileInformationByHandle(wintypes.HANDLE(h), info):
            raise ctypes.WinError(ctypes.get_last_error())
        if info[0] & _REPARSE or not info[0] & 0x10:   # swapped for a link since the check
            raise PermissionError(f"{path} isn't a plain folder")
        owner = None
        if not made:
            sid, sd = ctypes.c_void_p(), ctypes.c_void_p()
            # SE_FILE_OBJECT, OWNER_SECURITY_INFORMATION
            if not advapi.GetSecurityInfo(h, 1, 1, ctypes.byref(sid), None, None, None,
                                          ctypes.byref(sd)):
                text = ctypes.c_wchar_p()
                if advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)):
                    owner = text.value
                    kernel.LocalFree(text)
                kernel.LocalFree(sd)
        sd = ctypes.c_void_p()
        if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, 1, ctypes.byref(sd), None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            # (OWNER |) DACL | PROTECTED_DACL: the folder's own security only, no walk
            what = 0x80000004 | (1 if sddl.startswith("O:") else 0)
            if not advapi.SetKernelObjectSecurity(h, what, sd):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            kernel.LocalFree(sd)
    finally:
        kernel.CloseHandle(h)
    return owner


def _owner(path: Path) -> str | None:
    """The owner SID of one entry itself (links are never asked: they're removed first)."""
    from ctypes import wintypes
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi.GetNamedSecurityInfoW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD,
                                             ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
                                             ctypes.c_void_p, ctypes.c_void_p,
                                             ctypes.POINTER(ctypes.c_void_p)]
    advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    sid, sd = ctypes.c_void_p(), ctypes.c_void_p()
    if advapi.GetNamedSecurityInfoW(str(path), 1, 1, ctypes.byref(sid), None, None, None,
                                    ctypes.byref(sd)):
        return None
    try:
        text = ctypes.c_wchar_p()
        if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            return None
        value = text.value
        kernel.LocalFree(text)
        return value
    finally:
        kernel.LocalFree(sd)


def _clean_base(base: Path):
    """Once the base folder is admins-only (nobody else can add to it), drop what someone
    else could have put there before: links, hard links, anything not admin-owned. The
    admin step writes its log there, and must never write through a planted link."""
    for entry in list(base.iterdir()):
        if entry.name == "MicPlugin":
            continue
        try:
            st = os.lstat(entry)
            if getattr(st, "st_file_attributes", 0) & _REPARSE or st.st_nlink > 1 \
                    or _owner(entry) not in _ADMIN_SIDS:
                log.warning("removed %s from the data folder (not the admin step's)", entry.name)
                _remove_entry(entry)
        except OSError:
            log.warning("couldn't check %s", entry, exc_info=True)


def secure_data_dirs():
    """Admin step, first thing: %ProgramData%\\OnionBoard and its MicPlugin folder made
    safe before anything is written there (anyone signed in can make folders in
    %ProgramData%, so either could be someone else's, or a link to a system folder)."""
    base = data_dir().parent
    base.parent.mkdir(parents=True, exist_ok=True)
    owner = _secure_dir(base, _BASE_SDDL)
    if owner is not None and owner not in _ADMIN_SIDS:
        log.warning("%s belonged to %s: taken over", base, owner)
    _clean_base(base)
    _secure_dir(data_dir(), _MIC_SDDL)


def _make_ring():
    """A fresh ring file for the effect to find when the audio starts, made without
    ever writing through a link someone else put in the (user-writable) folder: a new
    file of our own, then swapped in by name."""
    path = ring_path()
    if make_ring_ok(path):
        return
    if not path.parent.is_dir():
        # a reinstall's uninstall removed the folder (nothing held the ring open, as a
        # running board does): made again, as safe as the admin step makes it at first
        secure_data_dirs()
    tmp = path.parent / f"ring2.{os.getpid()}-{int(time.monotonic() * 1000)}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(new_ring_bytes())
        os.replace(tmp, path)   # replaces the entry itself, never a link's target
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:
        (path.parent / "ring.bin").unlink()   # the first test build's (unlink: the entry itself)
    except OSError:
        pass


def _audio_off(work, also: Sequence[str] = ()) -> int:
    """Run `work` (it returns an exit code) with Windows' audio stopped: the endpoint
    builder reads the mics' effect settings when it starts. The audio always starts
    again, however `work` ends; if it won't stop, nothing is touched (6). `work` done
    but a mic still sends only silence after every restart (_mics_come_back_live):
    MIC_SILENT. A mic (the effect's, or `also`: the one it goes on) that was already
    silent before isn't the step's doing: a headset that's switched off, or its mic
    muted, sends only zeros too, and restarting the audio for it only cut the sound."""
    _enable_privileges("SeBackupPrivilege", "SeRestorePrivilege")
    dependents = _running_dependents()
    _audio_comes_back(dependents)
    # a mic the last step left silent (MIC_SILENT, just now) is silent before this retry
    # too, but that's the stuck mic the retry is for: it still gets the extra restarts
    quiet = _silent_before([*installed_on(), *also]) - _left_silent()
    mics: list[str] | None = None
    code = None
    try:
        if not _audio_service(False):
            return 6   # don't rewrite a live endpoint if Windows couldn't stop its audio
        mics = installed_on()   # the one it comes off is listened to as well
        code = work()
    finally:
        _audio_service(True, dependents)
        live = mics is None or _mics_come_back_live(mics, dependents, quiet)
    return MIC_SILENT if code == 0 and not live else code


def _silent_before(guids: Sequence[str]) -> set[str]:
    """The mics among `guids` sending only exact zeros now (a check: never fails)."""
    quiet = set()
    for g in dict.fromkeys(g.lower() for g in guids):
        try:
            if _mic_is_silent(g):
                quiet.add(g)
        except Exception:  # noqa: BLE001
            log.info("couldn't listen to mic %s before the step", g, exc_info=True)
    if quiet:
        log.info("%s already sends only silence (switched off or muted?): not the "
                 "step's doing", ", ".join(sorted(quiet)))
    return quiet


MIC_SILENT = 7        # the step was done, but a mic still sends only silence
EXTRA_RESTARTS = 3    # ...after this many more restarts of Windows' audio
LEFT_SILENT = "left-silent.json"   # in data_dir(): the mics a step's MIC_SILENT named
RETRY_S = 30 * 60     # a step this soon after one counts as its retry


def _left_silent() -> set[str]:
    """The mics the last step left sending only silence, if it was under RETRY_S ago
    (a check: never fails)."""
    try:
        got = json.loads((data_dir() / LEFT_SILENT).read_text(encoding="utf-8"))
        if 0 <= time.time() - float(got["at"]) < RETRY_S:
            mics = {str(g).lower() for g in got["mics"]}
            if mics:
                log.info("%s left silent by the last step: still restarting for it",
                         ", ".join(sorted(mics)))
            return mics
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return set()


def _remember_silent(mics: Sequence[str]) -> None:
    """Note the mics this step left silent for the next one (none: forget them)."""
    path = data_dir() / LEFT_SILENT
    try:
        if mics:
            path.write_text(json.dumps({"at": time.time(), "mics": sorted(mics)}),
                            encoding="utf-8")
        else:
            path.unlink(missing_ok=True)
    except OSError:
        log.info("couldn't note the silent mics", exc_info=True)


def _mic_is_silent(guid: str) -> bool | None:
    """appaudio.mic_is_silent: True when the mic sends only exact zeros."""
    from soundboard.audio import appaudio
    return appaudio.mic_is_silent(guid)


def _silent(guid: str) -> bool:
    """Only exact zeros, twice 2 s apart (a mic still waking up can be silent a moment)."""
    heard = _mic_is_silent(guid)
    if heard:
        log.info("mic %s silent just after the audio restart: listening again", guid)
        time.sleep(2)
        heard = _mic_is_silent(guid)
    log.info("mic %s after the audio restart: %s", guid,
             {True: "only silence", False: "sound", None: "can't tell"}[heard])
    return bool(heard)


def _mics_come_back_live(before: Sequence[str], dependents: Sequence[str],
                          quiet: Collection[str] = ()) -> bool:
    """After the audio restart a mic can come back sending only exact zeros (an app
    such as a voice chat grabbed it the moment it was back), to every app and to Windows'
    own mic test, until the audio restarts again. So the mics the effect was on (`before`)
    and is on now are listened to: digital silence gets another restart, up to
    EXTRA_RESTARTS of them. False if a mic still sends only silence after those (the app
    then says so); True otherwise, "can't tell" and a failed check included. Mics in
    `quiet` were silent before the step already (_silent_before): left alone."""
    try:
        silent = [g for g in dict.fromkeys([*before, *installed_on()])
                  if g.lower() not in quiet and _silent(g)]
        for n in range(1, EXTRA_RESTARTS + 1):
            if not silent:
                break
            log.warning("%s sends only silence after the audio restart: restarting the "
                        "audio again (%d of %d)", ", ".join(silent), n, EXTRA_RESTARTS)
            try:
                _audio_service(False)
            finally:
                _audio_service(True, dependents)
            silent = [g for g in silent if _silent(g)]
            if not silent:
                log.info("the mic is back after %d more restart(s)", n)
        _remember_silent(silent)
        if silent:
            log.warning("%s still sends only silence after %d more restarts",
                        ", ".join(silent), EXTRA_RESTARTS)
            return False
    except Exception:  # noqa: BLE001 - a check: never fails the install or uninstall
        log.warning("couldn't check the mic after the audio restart", exc_info=True)
    return True


def admin_install(guid: str, slot: str | None = None, source: Path | None = None) -> int:
    """Put the effect on the mic `guid`: this app's own copy, or `source` (only
    admin_reinstall's saved copy of the part that was there, to put it back)."""
    dll = source or bundled_dll()
    if not dll.is_file():
        log.error("no effect DLL at %s", dll)
        return 3

    def work() -> int:
        # a file Windows' audio hasn't let go of yet, a registry key still being
        # written: such a failure is gone a moment later, so it's tried once more
        result = _try_put_on(guid, dll, slot)
        if result:
            log.warning("the mic effect didn't go on (%s): trying once more", result)
            time.sleep(2)
            result = _try_put_on(guid, dll, slot)
        return result
    return _audio_off(work, also=(guid,))


def _put_on(guid: str, slot: str | None, dll: Path) -> int:
    """admin_install()'s work, with the audio stopped."""
    # a name of its own per version: a copy Windows still holds can't block it
    digest = hashlib.sha256(dll.read_bytes()).hexdigest()[:12]
    target = install_dir() / f"obmic-{digest}.dll"
    target.parent.mkdir(parents=True, exist_ok=True)
    # this version is there already (a set-up again, a repair): kept as it is. Writing
    # over it failed while a program that hadn't let go of Windows' audio yet still
    # had it loaded (exit code 1)
    if _digest(target) != _digest(dll):
        tmp = target.with_suffix(".new")
        shutil.copyfile(dll, tmp)   # whole, then in place: never a half-copied effect
        os.replace(tmp, target)
    _register_com(target)
    for old in [*install_dir().glob("obmic*.dll"), *_old_install_dirs()]:
        if old != target:
            _remove(old)
    _make_ring()
    for other in installed_on():   # one mic at a time; this one is done afresh
        _uninstall_endpoint(other)
    for e in capture_endpoints():
        # an older version's set-up cut off (or its notes lost) left the effect in
        # this mic's slots with nothing to put back: just take it out
        if e["guid"] != guid and any(without_ours(v)[0]
                                     for v in _fx_values(e["guid"]).values()):
            _strip_endpoint(e["guid"])
    try:
        _install_endpoint(guid, slot)
    except BaseException:
        # cut off half-way: the mic goes back as it was rather than half set up
        try:
            _uninstall_endpoint(guid)
        except Exception:  # noqa: BLE001 - the notes stay; a later uninstall finishes
            log.exception("couldn't put %s back after a failed set-up", guid)
        raise
    return 0


def admin_reinstall(guid: str) -> int:
    """The old effect off completely, then this app's on: one admin prompt, one lock
    and one restart of Windows' audio (it was two, ~35 s; now ~18 s). Never leaves the
    mic without a working effect: a failed install is tried once more, and if that
    fails too the part that was there is put back."""
    dll = bundled_dll()
    if not dll.is_file():
        return 3
    # Read the complete source before touching Windows: unreadable or empty builds
    # must leave the existing setup alone. _put_on copies it atomically.
    if not dll.read_bytes():
        return 3
    # a copy of the part that's there now, in the admins-only data folder (the
    # uninstall removes its own folder): what goes back if the new one won't go on
    old, backup = registered_dll(), None
    if guid in installed_on() and old is not None and old.is_file():
        try:
            backup = data_dir().parent / "obmic-previous.dll"
            tmp = backup.with_suffix(".new")
            shutil.copyfile(old, tmp)
            os.replace(tmp, backup)
        except OSError:
            log.warning("couldn't keep a copy of the mic effect there now", exc_info=True)
            backup = None

    def work() -> int:
        result = _take_off(None)
        if result:
            return result   # keep the failed endpoint's recovery notes for another attempt
        result = _try_put_on(guid, dll)
        if result:
            log.warning("the new mic effect didn't go on (%s): trying once more", result)
            time.sleep(2)
            result = _try_put_on(guid, dll)
        if result and backup is not None:
            log.warning("the new mic effect didn't go on (%s): the old one goes back", result)
            if _try_put_on(guid, backup):
                log.error("couldn't put the old mic effect back either")
        return result
    try:
        return _audio_off(work, also=(guid,))
    finally:
        if backup is not None:
            _remove(backup)


def _try_put_on(guid: str, dll: Path, slot: str | None = None) -> int:
    """_put_on(), an exception counted as a failure (1)."""
    try:
        return _put_on(guid, slot, dll)
    except Exception:  # noqa: BLE001 - reported by the caller, which tries again
        log.exception("mic effect install failed")
        return 1


def admin_uninstall(only: str | None = None) -> int:
    """Take the effect off every mic, or only off the mic `only` (a GUID): then the
    rest stays, and the effect itself is removed once it's on no mic at all."""
    return _audio_off(lambda: _take_off(only))


def _take_off(only: str | None) -> int:
    """admin_uninstall()'s work, with the audio stopped."""
    failed = False
    for guid in installed_on():
        if only is not None and guid != only:
            continue
        try:
            _uninstall_endpoint(guid)
        except Exception:  # noqa: BLE001 - one mic left behind mustn't strand the rest
            failed = True
            log.exception("couldn't take the mic effect off %s", guid)
    if failed:
        # its notes stay, and the effect is still registered and on a mic: leaving
        # everything in place lets a later uninstall finish the job
        return 1
    if installed_on():
        return 0   # still on another mic: it stays registered for that one
    _unregister_com()
    for d in (install_dir(), *_old_install_dirs(), data_dir()):
        _remove(d)
    try:
        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, ENDPOINTS_KEY)
        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, STATE_KEY)
    except OSError:
        pass
    return 0


def admin_remove_all() -> int:
    """The app is being uninstalled: the effect off every mic, then the mic helper."""
    from soundboard.mic import michelper
    code = admin_uninstall()
    if code == 0 and not michelper.is_helper():
        michelper.remove_helper()   # (the helper removes itself after answering)
    return code


def _strip_endpoint(guid: str):
    """Take this effect out of every effect slot on one mic that has no notes. What it
    replaced isn't known, so the slot is left without it: everything else stays."""
    try:
        with _BackupKey(rf"{CAPTURE_KEY}\{guid}\FxProperties", create=False) as fx:
            for name, value in _fx_values(guid).items():
                changed, rest = without_ours(value)
                if not changed:
                    continue
                if rest is None:
                    fx.delete(name)
                else:
                    fx.set(name, winreg.REG_MULTI_SZ, rest)
                log.info("%s: took a leftover effect out of %s", guid, name)
    except FileNotFoundError:
        pass   # the mic is gone


def admin_cleanup(guid: str) -> int:
    """Clean up after the effect on a mic it isn't (by our notes) on: our CLSID out of
    its effect slots, then, if no mic uses the effect, its registration and files. A
    mic it is on properly is uninstalled the normal way (its notes put it back)."""
    if guid in installed_on():
        return admin_uninstall(guid)
    _enable_privileges("SeBackupPrivilege", "SeRestorePrivilege")
    if any(without_ours(v)[0] for v in _fx_values(guid).values()):
        dependents = _running_dependents()
        _audio_comes_back(dependents)
        try:
            if not _audio_service(False):
                return 6   # never rewrite a live mic
            _strip_endpoint(guid)
        finally:
            _audio_service(True, dependents)
    if not installed_on() and anything_installed():
        return admin_uninstall()   # on no mic: the rest of it goes too
    return 0


def _remove(path: Path):
    """Delete a file or folder of ours. What Windows still holds open (an old copy of
    the effect) goes at the next restart instead of staying behind for good."""
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
        if path.exists():   # files first, deepest folders next, the folder itself last
            left = sorted(path.rglob("*"), key=lambda p: (p.is_dir(), -len(p.parts)))
            for entry in [*left, path]:
                _gone_at_restart(entry)
    else:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            _gone_at_restart(path)


def _gone_at_restart(path: Path):
    log.info("can't remove %s yet: it goes at the next restart", path)
    try:
        # MOVEFILE_DELAY_UNTIL_REBOOT (admin only: the admin step is)
        if not ctypes.windll.kernel32.MoveFileExW(str(path), None, 4):
            log.warning("couldn't mark %s for removal", path)
    except (AttributeError, OSError):
        log.warning("couldn't mark %s for removal", path, exc_info=True)


def anything_installed() -> bool:
    return bool(installed_on()) or registered_dll() is not None \
        or any(d.exists() for d in (install_dir(), *_old_install_dirs()))


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def cli(args: list[str]) -> int:
    """`--direct-mic install <endpoint guid> [sfx|lfx|efx]` /`--direct-mic uninstall`: the
    admin copy. `--direct-mic remove`: the uninstaller's, not admin: runs the admin
    `remove-all` (the mic helper, or Windows asks first) if Onion Board is on a mic or
    its helper (or any of it) is there at all. 0 when done. The app adds `--for <SID>`
    (the account that asked) to the steps that may set up the helper."""
    from soundboard.mic import michelper
    user = None
    if len(args) >= 2 and args[-2] == michelper.FOR:
        user, args = args[-1], args[:-2]   # (install_helper checks it)
    if args == ["remove"]:
        if not anything_installed() and not michelper.leftover():
            return 0
        if not _is_admin():
            code = _elevated(["remove-all"])
            return 1 if code is None or code < 0 else code
        args = ["remove-all"]
    if args[:1] == ["reinstall"] and len(args) == 2 and _GUID.fullmatch(args[1]):
        guid = args[1].lower()
        if guid not in {e["guid"] for e in capture_endpoints()}:
            return 2
        step = lambda: admin_reinstall(guid)  # noqa: E731
    elif args[:1] == ["install"] and len(args) in (2, 3) and _GUID.fullmatch(args[1]) \
            and (len(args) == 2 or args[2] in SLOTS_FX):
        guid = args[1].lower()
        if guid not in {e["guid"] for e in capture_endpoints()}:
            return 2
        step = lambda: admin_install(guid, args[2] if len(args) == 3 else None)  # noqa: E731
    elif args == ["uninstall"]:
        step = admin_uninstall
    elif args == ["remove-all"]:
        step = admin_remove_all
    elif args[:1] == ["cleanup"] and len(args) == 2 and _GUID.fullmatch(args[1]):
        guid = args[1].lower()
        step = lambda: admin_cleanup(guid)  # noqa: E731
    elif args[:1] == ["uninstall"] and len(args) == 2 and _GUID.fullmatch(args[1]):
        guid = args[1].lower()   # an unplugged mic too: its settings are still there
        step = lambda: admin_uninstall(guid)  # noqa: E731
    else:
        return 2
    lock = _admin_lock()
    if lock is None:
        return 4   # another copy is at it (a set-up the board stopped waiting for)
    try:
        try:
            _enable_privileges("SeBackupPrivilege", "SeRestorePrivilege")
            secure_data_dirs()   # before the log or anything else is written there
        except Exception:  # noqa: BLE001 - nowhere safe to log to: just say it failed
            return 5
        log_to(data_dir().parent / "directmic-admin.log")
        try:
            code = step()
        except Exception:  # noqa: BLE001
            log.exception("mic effect %s failed", args[:1])
            return 1
        if code in (0, MIC_SILENT) and args[0] in ("install", "reinstall", "cleanup") \
                and not michelper.is_helper():
            # the one prompt also sets up (or updates) the helper: no prompt next time
            michelper.install_helper(user)
        return code
    finally:
        _release(lock)


LOG_BYTES = 1 << 20


def log_to(path: Path):
    """The admin logs (directmic-admin.log, michelper.log): about 1 MB each, with one
    older copy, instead of growing for good. Nothing if logging is set up already."""
    from logging.handlers import RotatingFileHandler
    root = logging.getLogger()
    if root.handlers:
        return
    handler = RotatingFileHandler(path, maxBytes=LOG_BYTES, backupCount=1,
                                  encoding="utf-8", delay=True)
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    root.addHandler(handler)
    root.setLevel(logging.INFO)


_LOCK_NAME = "Global\\OnionBoardMicEffect"


def _admin_lock():
    """One admin step at a time, machine-wide: a handle to hold, or None if another copy
    holds it (two at once would each stop the audio and rewrite the same mic)."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    h = kernel.CreateMutexW(None, False, _LOCK_NAME)
    if not h:
        return None
    if kernel.WaitForSingleObject(h, 0) not in (0, 0x80):   # got it / its owner died
        kernel.CloseHandle(h)
        return None
    return h


def _release(h):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.ReleaseMutex(h)
    kernel.CloseHandle(h)


# ---------------------------------------------------------------------- the app's side

def relaunch_params(args: list[str]) -> str:
    parts = []
    if not getattr(sys, "frozen", False):
        parts.append(f'"{Path(__file__).resolve().parents[2] / "main.py"}"')
    return " ".join(parts + [FLAG] + args)


def _elevated(args: list[str], wait_s: float = 300.0, *,
              ask_windows: bool = True) -> int | None:
    """Run the admin command `args`: through the mic helper when it's set up (no
    prompt), else this app's admin copy (Windows asks first; not with `ask_windows`
    False: the app's own repair, which nobody clicked). Its exit code, or None if the
    prompt was turned down, not allowed, or it didn't finish. The audio stop/start and
    the dependent services can take a while on a slow PC, so allow generously."""
    from soundboard.mic import michelper
    try:
        code = _via_helper(args, wait_s)
        if code is not None or not ask_windows:
            return code
        return run_elevated(sys.executable,
                            relaunch_params(args + michelper.for_user(args)), wait_s,
                            progress=data_dir().parent / "directmic-admin.log")
    finally:
        # what the UI shows follows the helper as it is now: the prompt's step may
        # have set it up, and another account may have removed it meanwhile
        _helper_check("after a step")


def _helper_check(via: str = "check") -> bool:
    """michelper.ready() again, so michelper.will_ask() is current (on a worker).
    False if the check itself failed."""
    from soundboard.mic import michelper
    try:
        michelper.ready(via=via)
        return True
    except Exception:  # noqa: BLE001 - only the texts' "click Yes" depends on it
        log.warning("couldn't check the mic helper", exc_info=True)
        return False


def _via_helper(args: list[str], wait_s: float) -> int | None:
    """`args` run by the mic helper, or None to ask Windows instead. Setting up needs a
    helper with this app's effect DLL; taking it off works with any helper."""
    from soundboard.mic import michelper
    try:
        if not michelper.allowed(args):
            return None
        usable = michelper.ready(same_dll=args[0] in ("install", "reinstall"),
                                 via="before a step")
        return michelper.ask(args, wait_s) if usable else None
    except Exception:  # noqa: BLE001 - Windows' prompt still works
        log.warning("the mic helper failed", exc_info=True)
        return None


# run_elevated's "no answer came" codes (each reads as unfinished(); counted apart):
UNFINISHED = -1    # it started (its log changed), then went silent for wait_s
NOT_STARTED = -2   # Windows couldn't start it (an error other than a No)
NO_ANSWER = -3     # silent from the start: the prompt still open, or it never got going
UNFINISHED_CODES = (UNFINISHED, NOT_STARTED, NO_ANSWER)


PROMPT_CAP_S = 900.0   # an admin step still writing its log is waited for up to this


def wait_for(done, wait_s: float, progress: Path | None, cap_s: float = PROMPT_CAP_S,
             poll_s: float = 1.0) -> bool:
    """Wait for `done(seconds)` (blocks up to that long; True once finished) while
    `progress` (an admin log) keeps changing, up to `cap_s`: a slow PC still at work
    isn't cut off at a fixed time. False once it has been silent for `wait_s`."""
    start = last = time.monotonic()
    mark = _file_mark(progress)
    while True:
        if done(poll_s):
            return True
        now = time.monotonic()
        seen = _file_mark(progress)
        if seen != mark:
            mark, last = seen, now
        if now - start > cap_s or now - last > wait_s:
            return False


def _file_mark(path: Path | None) -> tuple[int, int] | None:
    try:
        st = path.stat() if path is not None else None
    except OSError:
        return None
    return None if st is None else (st.st_size, st.st_mtime_ns)


def run_elevated(exe: str, params: str, wait_s: float = 90.0,
                 progress: Path | None = None) -> int | None:
    """Run `exe` as admin, hidden (Windows asks first). Its exit code; None if the
    prompt was turned down (ERROR_CANCELLED: a No, or a PC that denies admin rights to
    this account); one of UNFINISHED_CODES if it couldn't start otherwise (NOT_STARTED)
    or didn't finish (silent for `wait_s`: the log `progress` didn't change either;
    NO_ANSWER if it never changed, the prompt may still be open: nobody clicked No)."""
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
    before = _file_mark(progress)
    if not shell32.ShellExecuteExW(ctypes.byref(info)) or not info.hProcess:
        error = ctypes.get_last_error()
        log.info("%s %s not run (error %s)", Path(exe).name, params[-40:], error)
        return None if error == 1223 else NOT_STARTED   # ERROR_CANCELLED: turned down
    try:
        handle = info.hProcess
        if not wait_for(lambda t: kernel32.WaitForSingleObject(handle, int(t * 1000)) == 0,
                        wait_s, progress, max(PROMPT_CAP_S, wait_s)):
            log.info("%s %s didn't finish (silent for %.0f s)", Path(exe).name,
                     params[-40:], wait_s)
            return UNFINISHED if _file_mark(progress) != before else NO_ANSWER
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        return code.value
    finally:
        kernel32.CloseHandle(info.hProcess)


def declined() -> str:
    """What install/uninstall return when Windows' admin prompt was turned down."""
    return _("Windows' admin prompt was turned down (or didn't finish).")


def unfinished() -> str:
    """What install/uninstall return when the admin step didn't finish (or couldn't
    start): not a No, so the card never says one was clicked."""
    return _("Windows' admin step didn't finish. If its prompt is still open, answer it; "
             "then try again.")


def mic_silent() -> str:
    """What a step returns when it was done, but the mic still sends only silence after
    every restart of Windows' audio (MIC_SILENT)."""
    return _("Your mic sends no sound. Is your headset switched off, or its mic muted? "
             "Turn it on or unmute it. Still nothing? Restart your PC, then try again.")


def no_helper() -> str:
    """What install returns when the mic helper couldn't do it and Windows wasn't asked."""
    return _("Onion Board's mic helper didn't answer.")


def no_mic() -> str:
    """What install returns when the mic isn't plugged in (or Windows doesn't list it)."""
    return _("That mic isn't plugged in (or Windows doesn't list it).")


def mic_gone() -> str:
    """What install returns when Windows doesn't know the picked mic at all."""
    return _("Windows doesn't know that mic any more. Pick your mic again (Setup tab → Devices).")


def mic_unsure() -> str:
    """What install returns when two mics start like the picked mic's name."""
    return _("Two mics have names like that one. Pick yours again (Setup tab → Devices).")


def no_effect() -> str:
    """What install returns when this copy has no mic effect DLL bundled."""
    return _("This copy of Onion Board has no mic effect in it.")


# why a set-up failed, as counted (usage MIC_FAILS): the admin step's prompt left
# unanswered (NO_ANSWER), it couldn't start (NOT_STARTED) or it stopped half-way
# (UNFINISHED); the mic silent after it; the mic helper not answering (only the app's
# own repair, which never asks Windows); no such mic; no effect in this copy; or the
# admin step's own exit code: 1 it raised, 2 the mic isn't listed to admins, 3 the effect
# file missing or empty, 4 another copy at it, 5 its data folder couldn't be secured,
# 6 Windows' audio wouldn't stop. Never the message, the mic or a path.
FAIL_CODES = (1, 2, 3, 4, 5, 6)
# no such mic, and why (mic_lookup): unplugged or off, two that look alike, unknown.
# Plain "no-mic" is a set-up given no mic at all (and what 2.2 and older counted).
NO_MIC_KINDS = ("no-mic-off", "no-mic-unsure", "no-mic-gone")
FAIL_KINDS = ("unanswered", "no-start", "stuck", "silent", "no-helper", "no-mic",
              *NO_MIC_KINDS, "no-effect", *(f"code-{c}" for c in FAIL_CODES), "code-other")
_UNFINISHED_KIND = {NO_ANSWER: "unanswered", NOT_STARTED: "no-start", UNFINISHED: "stuck"}


class Failure(str):
    """install()'s reason in plain words, with `kind`: a fixed word from FAIL_KINDS
    (or "said-no") to count, so nothing matches the translated message."""
    kind: str

    def __new__(cls, text: str, kind: str):
        self = super().__new__(cls, text)
        self.kind = kind
        return self


def fail_kind(err: str) -> str:
    """Which of FAIL_KINDS install()'s result `err` is ("code-other" for any other text)."""
    kind = getattr(err, "kind", "")
    return kind if kind in FAIL_KINDS else "code-other"


def install(mic_name: str | None, *, clean: bool = False,
            ask_windows: bool = True) -> str | None:
    """Put the effect on the mic called `mic_name` (Windows asks for admin, unless the
    mic helper does it, or `ask_windows` is False). None when done, else what went
    wrong, in plain words."""
    guid = endpoint_for(mic_name)
    if guid is None:
        why = mic_lookup(mic_name)[1] or "gone"
        text = {"off": no_mic, "unsure": mic_unsure}.get(why, mic_gone)()
        return Failure(text, f"no-mic-{why}")
    return install_on(guid, clean=clean, ask_windows=ask_windows)


def install_on(guid: str | None, *, clean: bool = False,
               ask_windows: bool = True) -> str | None:
    """install() for the mic with endpoint GUID `guid` (it comes off any other mic)."""
    if guid is None:
        return Failure(no_mic(), "no-mic")
    if not bundled_dll().is_file():
        return Failure(no_effect(), "no-effect")
    code = _elevated(["reinstall" if clean else "install", guid], ask_windows=ask_windows)
    if code is None:
        return Failure(declined(), "said-no") if ask_windows else \
            Failure(no_helper(), "no-helper")
    if code in UNFINISHED_CODES:
        return Failure(unfinished(), _UNFINISHED_KIND[code])
    if code == MIC_SILENT:
        return Failure(mic_silent(), "silent")
    if code:
        return Failure(_("Installing failed (code {code}). The log is in {folder}.",
                         code=code, folder=data_dir().parent),
                       f"code-{code}" if code in FAIL_CODES else "code-other")
    return None


def cleanup(guid: str) -> str | None:
    """admin_cleanup() on the mic with endpoint GUID `guid` (Windows asks first)."""
    code = _elevated(["cleanup", guid])
    if code is None:
        return declined()
    if code in UNFINISHED_CODES:
        return unfinished()
    return _("Cleaning up failed (code {code}).", code=code) if code else None


def uninstall(guid: str | None = None) -> str | None:
    """Take the effect off every mic, or only off the mic with endpoint GUID `guid`."""
    code = _elevated(["uninstall", guid] if guid else ["uninstall"])
    if code is None:
        return declined()
    if code in UNFINISHED_CODES:
        return unfinished()
    if code == MIC_SILENT:
        return mic_silent()
    return _("Removing failed (code {code}).", code=code) if code else None
