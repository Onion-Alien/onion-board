import numpy as np

from soundboard.engine import CH, SR, Ring


def frames(start, n):
    """(n, 2) block whose left channel is a running frame counter."""
    x = np.zeros((n, CH), np.float32)
    x[:, 0] = np.arange(start, start + n)
    x[:, 1] = -x[:, 0]
    return x


F = 4   # Ring.FADE_S at rate 1000: frames faded in after a (re)start or skip


def test_prefill_then_read_in_order():
    r = Ring(rate=1000)               # prefill 15 frames, max_fill 80, cap 500
    assert r.read(10) is None         # empty
    r.write(frames(0, 50))
    out = r.read(10)
    assert out is not None and out.shape == (10, CH)
    assert out[0, 0] == 0                              # faded in, no hard edge
    assert list(out[F:, 0]) == list(range(F, 10))
    out = r.read(10)
    assert list(out[:, 0]) == list(range(10, 20))


def test_underrun_unprimes_until_cushion_refilled():
    r = Ring(rate=1000)
    r.write(frames(0, 30))
    assert r.read(10) is not None     # 30 >= 15 + 10
    out = r.read(30)                  # only 20 left -> underrun: they fade out
    assert out is not None and r.underruns == 1
    assert out[0, 0] == 10 and out[19, 0] == 0 and not out[20:].any()
    assert np.all(np.diff(np.abs(out[:20, 0]) / np.arange(10, 30)) <= 0)
    assert r.read(30) is None         # empty, and waiting for the cushion
    r.write(frames(30, 30))           # 30 buffered, need 15 + 30
    assert r.read(30) is None
    r.write(frames(60, 20))           # 50 buffered
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
    seq = np.concatenate(got)[F:]
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
    assert out is not None and r.overflows == 1
    assert out[0, 0] == 0 and out[F, 0] == 85 + F   # 85 frames skipped, faded back in


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


def test_growing_cushion_after_each_underrun():
    r = Ring(rate=1000, grow_to_s=0.05)   # prefill 15 -> at most 50
    for want in (22, 33, 49, 50, 50):
        r.write(frames(0, r.prefill + 10))
        assert r.read(10) is not None
        r.read(r.count + 1)                # runs dry
        assert r.prefill == want
    assert r.underruns == 5


def test_fixed_cushion_by_default():
    r = Ring(rate=1000)
    r.write(frames(0, 30))
    r.read(10)
    r.read(30)
    assert r.underruns == 1 and r.prefill == 15


def test_restart_after_underrun_fades_in():
    r = Ring(rate=1000)
    r.write(np.ones((30, CH), np.float32))
    r.read(10)
    r.read(30)                             # dry
    r.write(np.ones((40, CH), np.float32))
    out = r.read(10)
    assert out[0, 0] == 0 and np.all(np.diff(out[:F, 0]) > 0) and np.all(out[F:] == 1)


def test_auto_drift_switches_on_after_two_glitches():
    r = Ring(prefill_s=0.01, max_s=0.02, auto_drift=True)
    assert not r.track_drift
    for _ in range(2):   # a writer running fast: the ring overflows and skips ahead
        r.write(np.zeros((int(SR * 0.03), 2), np.float32))
    assert r.overflows >= 2 and r.track_drift
    assert not Ring(prefill_s=0.01, max_s=0.02).track_drift
