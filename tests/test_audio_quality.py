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


def test_live_pitch_keeps_left_and_right_lined_up():
    # music with stereo width: the right channel 0.3 ms behind the left. Each channel
    # spliced on its own moved that gap around at every splice (a smeared image, and
    # flanging once a call folds it to mono); linked, it stays where it was.
    from soundboard.engine import LivePitch
    rng = np.random.default_rng(1)
    t = np.arange(SR * 2) / SR
    mono = sum(np.sin(2 * np.pi * f * t + rng.uniform(0, 6)) for f in (196, 247, 294, 392, 523))
    mono = (mono / 5 + 0.05 * rng.standard_normal(len(t))).astype(np.float32)
    d = 14   # frames
    x = np.stack([mono[d:], mono[:-d]], 1) * np.float32(0.5)
    lp = LivePitch(SR)
    y = np.concatenate([lp.process(x[i:i + BLOCK], 3.0) for i in range(0, len(x) - BLOCK, BLOCK)])
    lags = []
    for s in range(SR // 2, len(y) - 2048, 1024):
        a, b = y[s:s + 2048, 0], y[s:s + 2048, 1]
        c = [float(np.dot(a[30:-30], b[30 + k:len(b) - 30 + k])) for k in range(-30, 31)]
        lags.append(int(np.argmax(c)) - 30)
    # pitched up 3 st, the 14-frame gap plays as ~11 frames, and stays there
    assert max(lags) - min(lags) <= 1, lags


def test_live_pitch_resampler_keeps_the_top_end():
    # 9 kHz shifted down an octave. Linear interpolation lost 0.8 dB of it and left an
    # image at -27.5 dB; cubic: 0.2 dB and -40 dB.
    from soundboard.engine import LivePitch
    x = np.stack([np.sin(2 * np.pi * 9000 * np.arange(SR) / SR)] * 2, 1).astype(np.float32)
    lp = LivePitch(SR)
    y = np.concatenate([lp.process(x[i:i + BLOCK] * np.float32(0.5), -12.0)
                        for i in range(0, len(x) - BLOCK, BLOCK)])[SR // 4:, 0]
    w = np.hanning(len(y))
    spec = 20 * np.log10(np.abs(np.fft.rfft(y * w)) / (w.sum() / 2) + 1e-12)
    f = np.fft.rfftfreq(len(y), 1 / SR)
    assert abs(spec[np.abs(f - 4500) < 20].max() - 20 * np.log10(0.5)) < 0.4
    assert spec[np.abs(f - 4500) > 200].max() < -35


def thd_db(y, f0):
    """Harmonics 2..19 of f0 against f0 itself, in dB (after the first half second)."""
    y = y[SR // 2:]
    w = np.hanning(len(y))
    sp = np.abs(np.fft.rfft(y * w))
    fr = np.fft.rfftfreq(len(y), 1 / SR)

    def at(f):
        return sp[np.abs(fr - f) < 3].max()
    return 20 * np.log10(np.sqrt(sum(at(k * f0) ** 2 for k in range(2, 20))) / at(f0))


def test_limiter_holds_through_bass_instead_of_riding_it():
    # a 45 Hz bass 6 dB over the ceiling: without a hold the gain crept back up between
    # its peaks and came down at each one, -38.5 dB of distortion (gritty 808s)
    from soundboard.sendfx import Limiter
    t = np.arange(SR * 2) / SR
    x = np.stack([np.sin(2 * np.pi * 45 * t) * 1.4] * 2, 1).astype(np.float32)
    lim = Limiter(SR)
    y = np.concatenate([lim.process(x[i:i + BLOCK]) for i in range(0, len(x), BLOCK)])
    assert thd_db(y[:, 0], 45) < -80


def test_headphones_turn_overlapping_loud_sounds_down_instead_of_bending_them():
    # two loud pads at once in the headphones went over full scale and through the
    # tanh waveshaper: -20 dB of distortion (10%). Now a limiter turns them down.
    e = engine_main()
    e.mon_stream, e.monitor_sounds, e.mon_vol = object(), True, 1.0
    t = np.arange(SR * 2) / SR
    tone = np.stack([np.sin(2 * np.pi * 220 * t) * 0.65] * 2, 1).astype(np.float32)
    e.dest = None
    e.play("a", tone, 1.0, mode="overlap", only="mon")
    e.play("b", tone, 1.0, mode="overlap", only="mon")
    out = np.zeros((BLOCK, 2), np.float32)
    y = []
    for _ in range(len(t) // BLOCK - 2):
        e._mon(out, BLOCK)
        y.append(out[:, 0].copy())
    y = np.concatenate(y)
    assert np.max(np.abs(y)) <= 10 ** (-0.3 / 20) + 1e-6
    assert thd_db(y, 220) < -60


def test_loud_masters_are_stored_without_flat_tops():
    # a loud master decodes ~1 dB over full scale: clipped into the 16-bit cache, every
    # peak had a flat top (crackle). It's turned down around the peaks instead.
    from soundboard.library import to_int16
    t = np.arange(SR * 2) / SR
    x = np.stack([np.sin(2 * np.pi * 220 * t) * 1.12] * 2, 1).astype(np.float32)
    y = to_int16(x).astype(np.float32) / 32767
    assert len(y) == len(x)
    assert np.max(np.abs(y)) < 1.0 and thd_db(y[:, 0], 220) < -60
    q = np.stack([np.sin(2 * np.pi * 220 * t) * 0.5] * 2, 1).astype(np.float32)
    assert np.array_equal(to_int16(q), np.rint(q * 32767).astype(np.int16))   # untouched
    # the limiter's delay is taken back out: the sound lines up with the original
    k = SR // 2
    assert np.corrcoef(y[k:k + 4800, 0], x[k:k + 4800, 0])[0, 1] > 0.999
