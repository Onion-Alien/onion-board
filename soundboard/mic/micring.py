"""The mic effect's ring: the shared file the board writes what others hear into and
the effect publishes the clean mic through (its layout is in directmic.py's
docstring), and DirectMicStream, the send output that runs on the mic's clock."""
from __future__ import annotations

import ctypes
import mmap
import os
import struct
import sys
import threading
import time
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
from soundboard.mic.micbase import log, ring_path


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
            try:
                time.sleep(wait)
            except OSError:   # Windows' high-resolution timer can fail: a coarser wait
                self._log_once("sleep")
                self._stop.wait(wait)


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

