"""Switching on Hear what they hear: the headphones go over to what's sent without a hole
while its cushion fills (EngineBus._sent_filled)."""
import time

import numpy as np
import pytest

from soundboard.audio.engine import SR, Engine

BLOCK = 480


def engine():
    e = Engine()
    e.main_stream, e.mon_stream = object(), object()
    e.mon_vol, e.sound_vol = 1.0, 1.0
    e.monitor_sounds = True
    e.mic_enabled = False
    t = np.arange(6 * SR) / SR
    e.play("tone", np.stack([np.sin(2 * np.pi * 1000 * t)] * 2, 1).astype(np.float32) * 0.2, 1.0)
    return e


def longest_hole_ms(mon):
    """The longest stretch of 1 ms steps under 15% of the usual level."""
    env = np.abs(mon).max(axis=1)[:len(mon) // 48 * 48].reshape(-1, 48).max(axis=1)
    most = run = 0
    for low in env < 0.15 * float(np.median(env)):
        run = run + 1 if low else 0
        most = max(most, run)
    return most


def run(e, blocks, bunch=1, main=True):
    """The headphones' blocks one by one; main's come `bunch` at a time."""
    om, oh, out = np.zeros((BLOCK, 2), np.float32), np.zeros((BLOCK, 2), np.float32), []
    for i in range(blocks):
        if main and i % bunch == 0:
            for _ in range(bunch):
                e._cb_main(om, BLOCK, None, None)
        e._cb_mon(oh, BLOCK, None, None)
        out.append(oh.copy())
    return np.concatenate(out)


@pytest.mark.parametrize("bunch", [1, 2, 3])   # (3: the mic effect's 30 ms batches)
def test_switching_it_on_leaves_no_hole(bunch):
    e = engine()
    run(e, 60, bunch)
    e.mic_check = True
    mon = run(e, 60, bunch)
    assert e._mon_path[3]
    assert longest_hole_ms(mon) <= 8   # (the fade out and in, one block each; was 30-60)


def test_switching_it_on_and_off_again_before_it_filled_changes_nothing():
    e = engine()
    run(e, 60)
    e.mic_check = True
    run(e, 1)
    assert e._sent_want and not e._mon_path[3]
    e.mic_check = False
    mon = run(e, 30)
    assert not e._sent_want and e.ring_sent.count == 0
    assert longest_hole_ms(mon) == 0


def test_a_send_device_that_never_fills_it_is_not_waited_for(monkeypatch):
    e = engine()
    run(e, 60)
    e.mic_check = True
    monkeypatch.setattr(e, "SENT_FILL_S", 0.0)
    e._last_cb["main"] = time.monotonic()
    run(e, 3, main=False)
    assert e._mon_path[3]
