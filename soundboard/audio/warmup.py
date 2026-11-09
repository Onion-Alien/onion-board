"""Run the audio maths that cost something the first time once, ahead of time, so the
first live change (Nightcore, an effect knob, a pitch or voice change) is instant.

The first block through a filter, the pitch shifter, a reverb or a resampler pays a
one-time cost the rest never do: the native library's first call paging its code in,
NumPy's BLAS starting its thread pool, soxr building its state. It adds up to tens of
milliseconds, and if it lands on the audio thread mid-song it's heard as a short gap.
Running it here moves that cost into the loading screen, where there's nothing to stutter.

It's pure NumPy / native / soxr work with no Qt and its own throwaway objects (it never
touches the running engine), so it's safe on a worker thread while the splash is up."""
from __future__ import annotations

import logging
import threading

import numpy as np

log = logging.getLogger(__name__)

_started = False
_lock = threading.Lock()


def _warm() -> None:
    import soxr

    from soundboard.audio import livefx
    from soundboard.audio.engineparts import CH, SR

    block = np.ascontiguousarray(
        (np.random.default_rng(0).standard_normal((1024, CH)) * 0.1).astype(np.float32))

    # the same NumPy warnings a real toggle would raise (a filter design's divide), but
    # on this thread only, so warming up doesn't print them at every start
    with np.errstate(all="ignore"):
        # every live effect on one sound at once: the shelf (bass / treble / muffle),
        # distortion, echo, reverb and the over-100 % volume limiter. Two blocks: a few
        # effects only build their state once they're first asked for.
        fx = {"bass": 4.0, "treble": 3.0, "muffle": 20.0, "crunch": 50.0,
              "echo": 40.0, "reverb": 40.0, "volume": 150.0}
        lf = livefx.LiveFx(SR)
        for _ in range(2):
            lf.process(block, fx)

        # the pitch shifter and a live stage, as a sound's own live stage runs them
        stage = livefx.SoundStage(SR)
        st = (1.0, 4.0, ({"bass": 4.0},), 1.0)
        for _ in range(2):
            stage.process(block, st)

        # a sample-rate change, as the engine resamples (tape speed, a device off 48 kHz)
        rs = soxr.ResampleStream(SR, 44100, CH, dtype="float32", quality="HQ")
        rs.resample_chunk(block)


def warm_up() -> None:
    """Warm the audio maths once, on a daemon thread. Safe to call more than once; later
    calls do nothing."""
    global _started
    with _lock:
        if _started:
            return
        _started = True

    def run() -> None:
        try:
            _warm()
        except Exception:   # noqa: BLE001 - a warm-up that fails just means the old cost
            log.debug("audio warm-up skipped", exc_info=True)

    threading.Thread(target=run, daemon=True, name="audio-warmup").start()
