import numpy as np

from soundboard.engine import CH, Ring


def frames(start, n):
    """(n, 2) block whose left channel is a running frame counter."""
    x = np.zeros((n, CH), np.float32)
    x[:, 0] = np.arange(start, start + n)
    x[:, 1] = -x[:, 0]
    return x


def test_prefill_then_read_in_order():
    r = Ring(rate=1000)               # prefill 15 frames, max_fill 80, cap 500
    assert r.read(10) is None         # empty
    r.write(frames(0, 50))
    out = r.read(10)
    assert out is not None and out.shape == (10, CH)
    assert list(out[:, 0]) == list(range(10))
    out = r.read(10)
    assert list(out[:, 0]) == list(range(10, 20))


def test_underrun_unprimes_until_cushion_refilled():
    r = Ring(rate=1000)
    r.write(frames(0, 30))
    assert r.read(10) is not None     # 30 >= 15 + 10
    assert r.read(30) is None         # only 20 left -> underrun
    r.write(frames(30, 10))           # 30 buffered, need 15 + 30
    assert r.read(30) is None
    r.write(frames(40, 20))           # 50 buffered
    assert r.read(30) is not None


def test_wraps_around_capacity_without_losing_order():
    r = Ring(rate=1000)
    pos = 0
    got = []
    for _ in range(40):               # 40 * 40 = 1600 frames > cap (500)
        r.write(frames(pos, 40))
        pos += 40
        out = r.read(40)
        if out is not None:
            got.append(out[:, 0])
    seq = np.concatenate(got)
    assert len(seq) > 1000
    assert np.all(np.diff(seq) == 1), "frames came out of order across the wrap"


def test_overfill_skips_ahead_to_keep_latency_low():
    r = Ring(rate=1000)               # max_fill 80
    r.write(frames(0, 70))
    r.write(frames(70, 30))           # 100 > 80 -> drop down to prefill (15)
    assert r.count == 15
    out = r.read(5)                   # primes: 15 >= 15 + 5? no -> None
    assert out is None
    r.write(frames(100, 10))
    out = r.read(5)
    assert out is not None
    assert out[0, 0] == 85            # the oldest 85 frames were skipped


def test_drift_tracking_always_returns_n_frames_and_stays_finite():
    r = Ring(rate=1000, track_drift=True)
    r.write(frames(0, 60))
    outs = []
    for i in range(200):
        r.write(frames(60 + i * 10, 10))
        out = r.read(10)
        assert out is None or out.shape == (10, CH)
        if out is not None:
            outs.append(out)
    seq = np.concatenate(outs)[:, 0]
    assert np.all(np.isfinite(seq))
    assert np.all(np.diff(seq) > 0), "stretched output must still be monotonic"
    assert 1 - Ring.DRIFT_MAX <= r.ratio <= 1 + Ring.DRIFT_MAX


def test_clear_resets_fill_and_priming():
    r = Ring(rate=1000)
    r.write(frames(0, 50))
    assert r.read(10) is not None
    r.clear()
    assert r.count == 0 and not r.primed
    assert r.read(10) is None
