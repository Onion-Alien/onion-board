"""A sound said in an AI voice (Edit sound → Effects → Voice), rendered once and cached
with the sound's other effects (soundfx).

    sound (mono) ─ ServiceHost.feed ──(16 kHz)──> ai-voices helper ──(24 kHz, b"B")──> back

The same helper the live AI voice uses, started just for this and stopped after: it
converts audio as fast as it gets it (no real-time pacing), so a few seconds of sound
take about as long as the voice model needs. The clip is fed in paced blocks (the host
drops the oldest blocks when more than QUEUE_BLOCKS wait), then some silence so the
helper's last chunk and its delay come out too. Nothing here touches Qt.
"""
from __future__ import annotations

import logging
import threading
import time

import numpy as np

from soundboard import library, net
from soundboard.speech import aivoice, resample
from soundboard.speech.service import QUEUE_BLOCKS, ServiceHost

log = logging.getLogger(__name__)

HELPER_RATE = 24000      # what the helper sends back (aivoice.VOICE_RATE)
BLOCK_S = 0.02           # fed in 20 ms blocks, like the mic
TAIL_S = 0.6             # silence after the sound: the helper's last chunk and delay
READY_S = 90.0           # the first start loads the model (and times this PC once)
MAX_S = 600.0            # longer sounds aren't converted (minutes of CPU for a song)
MODEL_FILES = ("stream.onnx", "speaker.onnx", "voices.npz")   # ui.aivoicepanel.model_downloaded


class Unavailable(Exception):
    """The AI voice can't be used here (no add-on, no model, it failed to start)."""


def module():
    """The installed AI voices add-on, ready to run, or None."""
    from soundboard import modules
    for m in modules.discover():
        if (m.id == aivoice.MODULE_ID and not m.error and m.installed
                and all((m.path / "model" / f).is_file() for f in MODEL_FILES)):
            return m
    return None


def render(mono: np.ndarray, rate: int, voice_id: str, pitch: float = 0.0,
           auto_pitch: bool = True, mod=None, cancel=lambda: False,
           progress=None) -> np.ndarray:
    """`mono` (float32 at `rate`) in the AI voice `voice_id`, the same length and rate.
    Raises Unavailable if it can't be done. Slow: call it off the UI thread (a song takes
    about a third of its length). progress(frac): how much of it has come back, 0..1."""
    if len(mono) / rate > MAX_S:
        raise Unavailable(f"longer than {MAX_S:.0f} s")
    mod = mod or module()
    if mod is None:
        raise Unavailable("the AI voices add-on isn't installed")
    argv = ["--voice", voice_id, "--pitch", f"{float(pitch):g}"]
    if not auto_pitch:
        argv.append("--no-auto-pitch")
    ready, failed = threading.Event(), []
    got: list[bytes] = []
    lock = threading.Lock()

    def on_event(ev: dict):
        t = ev.get("type")
        if t == "ready":
            ready.set()
        elif t in ("error", "stopped"):
            failed.append(str(ev.get("text") or t))
            ready.set()

    back = [0]   # bytes of it back so far

    def on_audio(pcm: bytes):
        with lock:
            got.append(pcm)
            back[0] += len(pcm)

    host = ServiceHost(mod.resolved_command(argv), on_event, cwd=mod.path,
                       log_path=library.APP_DIR / f"module-{mod.id}.log", name=mod.id,
                       env=net.child_env("voices"), on_audio=on_audio,
                       make_resampler=resample.make)
    try:
        host.start()
    except RuntimeError as e:
        raise Unavailable(str(e)) from None
    try:
        if not _wait(ready.is_set, READY_S, cancel) or failed:
            raise Unavailable(failed[0] if failed else "the AI voice didn't start")
        x = np.concatenate([np.asarray(mono, np.float32),
                            np.zeros(int(TAIL_S * rate), np.float32)])
        step = max(1, int(BLOCK_S * rate))
        want = int(len(x) / rate * HELPER_RATE) - int(0.05 * HELPER_RATE)

        def have() -> int:
            with lock:
                return back[0] // 2

        def told():
            if progress is not None:
                progress(min(1.0, have() / max(1, want)))
        for i in range(0, len(x), step):
            while host._q.qsize() > QUEUE_BLOCKS // 2:   # let the sender catch up
                if cancel() or not host.running:
                    raise Unavailable("stopped")
                time.sleep(0.005)
            host.feed(x[i:i + step], rate)
            if progress is not None and i % (step * 25) == 0:   # every half second of it
                told()
        # it converts faster than real time on most PCs; give a slow one 3x the length
        if not _wait(lambda: have() >= want or bool(failed), 20 + 3 * len(x) / rate, cancel,
                     told):
            raise Unavailable("stopped" if cancel() else "the AI voice was too slow")
    finally:
        host.stop()
    with lock:
        y = np.frombuffer(b"".join(got), "<i2").astype(np.float32) / 32768.0
    if rate != HELPER_RATE:
        y = resample.make(HELPER_RATE, rate).resample_chunk(y)
    y = y[delay(mono, y, rate):]
    out = np.zeros(len(mono), np.float32)
    n = min(len(out), len(y))
    out[:n] = y[:n]
    return out


def delay(a: np.ndarray, b: np.ndarray, rate: int, most_s: float = 0.3) -> int:
    """How many samples `b` (the voice) runs behind `a` (the sound): the shift that
    lines their loudness up best, in 10 ms steps (the model holds back ~30 ms)."""
    step = max(1, rate // 100)
    k = min(len(a), len(b)) // step
    if k < 20:
        return 0

    def env(x):
        return np.sqrt((np.asarray(x[:k * step], np.float64).reshape(k, step) ** 2).mean(1))
    ea, eb = env(a), env(b)
    best, score = 0, -2.0
    for d in range(min(int(most_s * 100), k - 10)):
        x, y = ea[:k - d], eb[d:]
        if x.std() < 1e-9 or y.std() < 1e-9:
            continue
        c = float(np.corrcoef(x, y)[0, 1])
        if c > score:
            best, score = d, c
    return best * step


def _wait(done, seconds: float, cancel, tick=None) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if done():
            return True
        if cancel():
            return False
        if tick is not None:
            tick()
        time.sleep(0.02)
    return done()
