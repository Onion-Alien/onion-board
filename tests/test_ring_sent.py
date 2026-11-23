"""Regression tests for Engine.ring_sent's headphone monitor cushion."""
from __future__ import annotations

import numpy as np

from soundboard.audio.engine import Engine
from soundboard.audio.engineparts import (
    CH,
    LITE_BLOCK_S,
    SENT_RING_BIG_S,
    SENT_RING_S,
    SR,
)


def test_ring_sent_absorbs_bunched_mic_blocks():
    """With Straight into my mic, _main is paced by clean mic blocks that often arrive
    two 10 ms blocks at a time (20 ms gap, then 20 ms burst). ring_sent must absorb
    that jitter without running dry on the headphones."""
    eng = Engine()
    r = eng.ring_sent
    r.configure(SR)
    block = 480  # 10 ms at 48 kHz
    tone = np.full((block, CH), 0.25, np.float32)

    # Prime with steady 10 ms blocks until the ring starts delivering audio.
    for _ in range(10):
        r.write(tone)
        if r.read(block) is not None:
            break
    assert r.primed
    assert r.underruns == 0

    # Simulate bunched delivery: 20 ms bursts (two blocks written at once) while the
    # headphone callback reads steadily every 10 ms.
    burst = np.full((block * 2, CH), 0.25, np.float32)
    for _ in range(50):
        assert r.read(block) is not None
        assert r.read(block) is not None
        r.write(burst)
    assert r.underruns == 0


def test_ring_sent_grows_cushion_on_underrun_and_keeps_it_across_set_block():
    """A transient stall grows ring_sent's prefill up to grow_to_s, and set_block
    preserves ring_sent's larger cushion instead of resetting it to MIC_RING_S."""
    eng = Engine()
    r = eng.ring_sent
    assert (r.prefill_s, r.max_s, r.grow_to_s) == SENT_RING_S

    r.configure(SR)
    start_prefill = r.prefill
    block = 480
    tone = np.full((block, CH), 0.25, np.float32)
    while not r.primed:
        r.write(tone)
        r.read(block)
    # Drain completely to force one underrun.
    while r.underruns == 0:
        r.read(block)
    assert r.prefill > start_prefill
    assert r.prefill <= int(SR * SENT_RING_S[2])

    eng.set_block(LITE_BLOCK_S)
    assert (r.prefill_s, r.max_s, r.grow_to_s) == SENT_RING_BIG_S
    eng.set_block(0)
    assert (r.prefill_s, r.max_s, r.grow_to_s) == SENT_RING_S
