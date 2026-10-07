"""Stand-ins for sounddevice's streams in the measured app: the app's real callbacks
run on a thread at the device's pace, but nothing reaches a real device. Output
blocks go nowhere; the mic is a made-up voice (syllables on a moving pitch, with
pauses), mono or stereo.

The pace is kept on a perf_counter schedule (block k is due at start + k * period)
with sleeps only, never a spin. For every block it notes how late the callback
started (waking up plus waiting for the GIL) and how long it ran; a block that ends
after its deadline would have been a glitch on a real device ("late block"), and
falling more than XRUN_PERIODS behind starts the schedule again ("xrun").
"""
from __future__ import annotations

import threading
import time
from collections import deque

import numpy as np

XRUN_PERIODS = 3
KEEP = 20_000   # timings kept per stream per phase (200 s of 10 ms blocks)


class StreamStats:
    """One stream's timings since the last reset()."""

    def __init__(self, key: str):
        self.key = key
        self.lock = threading.Lock()
        self.native_id = 0
        self.reset()

    def reset(self):
        with self.lock:
            self.late: deque[float] = deque(maxlen=KEEP)
            self.took: deque[float] = deque(maxlen=KEEP)
            self.blocks = self.late_blocks = self.xruns = self.errors = 0

    def note(self, late: float, took: float, missed: bool):
        with self.lock:
            self.late.append(late)
            self.took.append(took)
            self.blocks += 1
            self.late_blocks += missed

    def summary(self) -> dict:
        with self.lock:
            late = np.fromiter(self.late, float) * 1000
            took = np.fromiter(self.took, float) * 1000
            blocks, late_blocks, xruns = self.blocks, self.late_blocks, self.xruns
        pick = lambda a, q: round(float(np.percentile(a, q)), 3) if a.size else None  # noqa: E731
        return {"blocks": blocks, "late_blocks": late_blocks, "xruns": xruns,
                "errors": self.errors,
                "late_p50_ms": pick(late, 50), "late_p99_ms": pick(late, 99),
                "late_max_ms": round(float(late.max()), 3) if late.size else None,
                "cb_p50_ms": pick(took, 50), "cb_p99_ms": pick(took, 99),
                "cb_max_ms": round(float(took.max()), 3) if took.size else None}


STATS: dict[str, StreamStats] = {}
_open: list = []
_lock = threading.Lock()


def reset_all():
    for s in list(STATS.values()):
        s.reset()


def summaries() -> dict[str, dict]:
    """Per open stream (closed ones that ran in this phase too)."""
    return {k: s.summary() for k, s in list(STATS.items()) if s.blocks or s.xruns}


def native_ids() -> dict[int, str]:
    return {s.native_id: f"audio callback ({k.split(':')[0]})"
            for k, s in list(STATS.items()) if s.native_id}


def voice_signal(rate: int, channels: int, secs: float = 8.0, seed: int = 3) -> np.ndarray:
    """A voice-like loop: harmonics of a pitch wandering around 110-220 Hz, shaped
    into ~4 syllables a second with short pauses, plus a little room noise."""
    rng = np.random.default_rng(seed)
    n = int(rate * secs)
    t = np.arange(n) / rate
    f0 = 150 + 45 * np.sin(2 * np.pi * 0.31 * t) + 20 * np.sin(2 * np.pi * 1.7 * t)
    phase = 2 * np.pi * np.cumsum(f0) / rate
    x = sum((0.5 / k) * np.sin(k * phase) for k in range(1, 9))
    syll = np.clip(np.sin(2 * np.pi * 4.0 * t), 0, None) ** 0.6
    talk = (np.sin(2 * np.pi * 0.23 * t + 1.0) > -0.6).astype(float)   # pauses
    x = 0.25 * x * syll * talk + 0.002 * rng.standard_normal(n)
    out = np.repeat(x[:, None], channels, axis=1)
    if channels > 1:
        out[:, 1] = 0.95 * out[:, 1] + 0.001 * rng.standard_normal(n)
    return out.astype(np.float32)


class _FakeStream:
    kind = "out"

    def __init__(self, *, samplerate=48000, channels=2, callback=None, blocksize=0,
                 device=None, latency=None, dtype="float32", **_):
        import sounddevice as sd
        self.samplerate = float(samplerate)
        self.channels = int(channels)
        self.dtype = dtype
        self.device = device
        self._cb = callback
        self._frames = int(blocksize) or max(1, int(samplerate) // 100)   # 10 ms
        self.blocksize = self._frames
        self.latency = 0.02 if latency == "high" else 0.0107
        self._flags = sd.CallbackFlags
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        name = device if isinstance(device, str) else _device_name(device)
        with _lock:
            n = sum(1 for k in STATS if k.startswith(f"{self.kind}:"))
            self.key = f"{self.kind}:{name}#{n}"
            STATS[self.key] = self.stats = StreamStats(self.key)

    @property
    def active(self) -> bool:
        return self._thread is not None

    @property
    def stopped(self) -> bool:
        return self._thread is None

    def _block(self) -> np.ndarray:
        return np.zeros((self._frames, self.channels), np.float32)

    def _call(self, buf):
        self._cb(buf, self._frames, None, self._flags())

    def _run(self):
        st = self.stats
        st.native_id = threading.get_native_id()
        period = self._frames / self.samplerate
        buf = self._block()
        due = time.perf_counter() + period
        while not self._stop.is_set():
            now = time.perf_counter()
            if now < due:
                time.sleep(due - now)
                continue
            if now - due > XRUN_PERIODS * period:   # far behind: a device would glitch
                with st.lock:
                    st.xruns += 1
                due = now
            start = time.perf_counter()
            try:
                self._call(buf)
            except Exception:  # noqa: BLE001 - a real stream would swallow it too
                st.errors += 1
                return
            end = time.perf_counter()
            st.note(start - due, end - start, end > due + period)
            due += period

    def start(self):
        if self._thread is None:
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True,
                                            name=f"fake-{self.kind}")
            self._thread.start()
            _open.append(self)

    def stop(self):
        t = self._thread
        if t is not None:
            self._stop.set()
            if t is not threading.current_thread():
                t.join(1)
            self._thread = None
        if self in _open:
            _open.remove(self)

    close = abort = stop

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.stop()


class FakeOutputStream(_FakeStream):
    kind = "out"


class FakeInputStream(_FakeStream):
    kind = "mic"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._voice = voice_signal(int(self.samplerate), self.channels)
        self._pos = 0

    def _call(self, buf):
        n, v = self._frames, self._voice
        if self._pos + n > len(v):
            self._pos = 0
        np.copyto(buf, v[self._pos:self._pos + n])
        self._pos += n
        self._cb(buf, n, None, self._flags())


DEVICES: list[dict] = []


def _device_name(index) -> str:
    if isinstance(index, int) and 0 <= index < len(DEVICES):
        return DEVICES[index]["name"]
    return str(index)


def fake_devices(mic_channels: int = 1) -> list[dict]:
    """Headphones, a virtual cable (both ends), a mono and a stereo mic, a stream
    output: what a typical gamer's PC lists. `mic_channels` picks which mic is the
    Windows default."""
    def dev(name, ins, outs, rate=48000.0):
        return {"name": name, "hostapi": 0, "max_input_channels": ins,
                "max_output_channels": outs, "default_samplerate": rate,
                "default_low_output_latency": 0.01, "default_low_input_latency": 0.01,
                "default_high_output_latency": 0.04, "default_high_input_latency": 0.04}
    return [dev("Headphones (Fake Audio)", 0, 2),
            dev("CABLE Input (VB-Audio Virtual Cable)", 0, 2),
            dev("CABLE Output (VB-Audio Virtual Cable)", 2, 0),
            dev("Microphone (Fake Mono Mic)", 1, 0),
            dev("Microphone (Fake Stereo Mic)", 2, 0),
            dev("Speakers (Fake Stream Output)", 0, 2, 44100.0)]


def install(sd, mic_channels: int = 1):
    """Swap sounddevice's streams and device list for the stand-ins."""
    DEVICES[:] = fake_devices(mic_channels)
    default_in = 3 if mic_channels == 1 else 4

    def query_devices(device=None, kind=None):
        if device is None and kind is None:
            return [dict(d, index=i) for i, d in enumerate(DEVICES)]
        if device is None:
            device = default_in if kind == "input" else 0
        if isinstance(device, str):
            device = next((i for i, d in enumerate(DEVICES) if d["name"] == device), -1)
        if isinstance(device, int) and 0 <= device < len(DEVICES):
            return dict(DEVICES[device], index=device)
        raise ValueError(f"no such device: {device!r}")

    def query_hostapis(index=None):
        api = {"name": "Windows WASAPI", "devices": list(range(len(DEVICES))),
               "default_input_device": default_in, "default_output_device": 0}
        return api if index is not None else (api,)

    sd.query_devices = query_devices
    sd.query_hostapis = query_hostapis
    sd.OutputStream = FakeOutputStream
    sd.InputStream = FakeInputStream
    sd.check_output_settings = lambda *a, **k: None
    sd.check_input_settings = lambda *a, **k: None
    try:
        sd.default.device = (default_in, 0)
    except Exception:  # noqa: BLE001 - an older sounddevice without the setter
        pass
