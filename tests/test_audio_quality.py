"""How the sounds themselves sound: no aliasing when sped up, no tick at a loop's
seam, no pop at a hard start, no steps when a volume moves. Each test measures the
problem it guards against (on synthesised audio), so a regression shows as a number."""
import numpy as np

from soundboard.engine import SR, Engine

BLOCK = 480


def sine(hz, seconds, amp=0.5, phase=0.0):
    t = np.arange(int(seconds * SR)) / SR
    return np.stack([np.sin(2 * np.pi * hz * t + phase)] * 2, 1).astype(np.float32) * amp


def engine_main():
    e = Engine()
    e.main_stream = object()
    e.dest, e.limiter_on, e.send_mono = None, False, False   # no shaping, no delay
    return e


def render(e, blocks, out="main"):
    return np.concatenate([e._render(out, BLOCK) for _ in range(blocks)])


def level_db(x, hz):
    """Level of the `hz` component of x (mono, Hann window), in dB re full scale."""
    w = np.hanning(len(x))
    spec = np.abs(np.fft.rfft(x * w)) / (w.sum() / 2)
    k = int(round(hz * len(x) / SR))
    return 20 * np.log10(spec[max(k - 3, 0):k + 4].max() + 1e-12)


def test_speeding_up_doesnt_fold_highs_back_down():
    # 18 kHz read at 2x is 36 kHz: above the output's 24 kHz it would fold back to
    # 12 kHz as an inharmonic whine. It must be filtered out instead.
    e = engine_main()
    e.sound_speed = 2.0
    e.play("hi", sine(18000, 1.0), 1.0, loop=True)
    y = render(e, 40)[BLOCK * 4:, 0]
    assert level_db(y, 12000) < -60
    # ...while what fits stays: 5 kHz at 2x is a clean 10 kHz, full level
    e2 = engine_main()
    e2.sound_speed = 2.0
    e2.play("mid", sine(5000, 1.0), 1.0, loop=True)
    y2 = render(e2, 40)[BLOCK * 4:, 0]
    assert abs(level_db(y2, 10000) - 20 * np.log10(0.5)) < 0.5


def test_a_loop_not_cut_at_a_zero_crossing_doesnt_tick():
    # 0.1 s of 441 Hz ends mid-cycle: a hard wrap jumps ~0.5 in one sample
    d = sine(441.3, 0.1, phase=0.4)
    for speed in (1.0, 1.5):
        e = engine_main()
        e.sound_speed = speed
        e.play("loop", d, 1.0, loop=True)
        y = render(e, 60)[:, 0]
        # a 441 Hz sine at 0.5 moves at most 2*pi*441/SR*0.5 ~ 0.03 (x speed) a sample
        assert np.max(np.abs(np.diff(y))) < 0.045 * speed


def test_a_sound_that_starts_mid_waveform_rises_instead_of_popping():
    d = np.full((SR // 10, 2), 0.6, np.float32)   # starts at 0.6
    e = engine_main()
    e.play("dc", d, 1.0)
    y = e._render("main", BLOCK)[:, 0]
    assert y[0] < 0.01 and np.max(np.abs(np.diff(y))) < 0.02
    assert abs(y[200] - 0.6) < 1e-6                  # up by 2 ms: drums keep their punch
    # a start position part-way in rises the same way
    e = engine_main()
    e.play("tone", sine(440, 0.5), 1.0, start=0.3)
    y = e._render("main", BLOCK)[:, 0]
    assert abs(y[0]) < 0.02


def test_volume_changes_glide_instead_of_stepping():
    e = engine_main()
    e.play("dc", np.full((SR, 2), 0.5, np.float32), 1.0, loop=True)
    out = np.zeros((BLOCK, 2), np.float32)
    e._main(out, BLOCK)
    e._main(out, BLOCK)
    a = out[:, 0].copy()
    e.sound_vol = 0.2
    e._main(out, BLOCK)
    b = out[:, 0].copy()
    y = np.concatenate([a, b])
    assert np.max(np.abs(np.diff(y))) < 0.01             # no one-sample jump
    assert abs(b[-1] - a[-1] * 0.2) < 0.01               # ...and there by the block's end


def test_mute_fades_out_instead_of_cutting():
    e = engine_main()
    e.play("dc", np.full((SR, 2), 0.5, np.float32), 1.0, loop=True)
    out = np.zeros((BLOCK, 2), np.float32)
    e._main(out, BLOCK)
    e.sending = False
    e._main(out, BLOCK)
    assert out[0, 0] > 0.4 and out[-1, 0] == 0 and np.max(np.abs(np.diff(out[:, 0]))) < 0.01
    e._main(out, BLOCK)
    assert not out.any()


def test_per_sound_gain_glides():
    e = engine_main()
    e.play("dc", np.full((SR, 2), 0.5, np.float32), 1.0, loop=True)
    a = e._render("main", BLOCK)[:, 0]
    e.set_gain("dc", 0.0)
    b = e._render("main", BLOCK)[:, 0]
    assert np.max(np.abs(np.diff(np.concatenate([a, b])))) < 0.01 and b[-1] == 0
