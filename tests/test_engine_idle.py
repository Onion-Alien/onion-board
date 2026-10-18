"""With nothing playing, the output callbacks skip the mixer (Engine._bus_idle). That
must be invisible: every scenario here runs twice, once with the shortcut and once
mixing every block as before, and what comes out has to be the same samples."""
import numpy as np
import pytest

from soundboard import destination
from soundboard.engine import SR, Engine
from soundboard.sendfx import Limiter, SafetyLimiter

N = 480   # one 10 ms block


class FakeStream:
    latency = 0.01

    def stop(self):
        pass

    def close(self):
        pass


def song(seconds=0.6, hz=220.0, amp=0.9):
    """Starts at full level on the first sample (a hard start), loud enough for the
    limiters to work."""
    t = np.arange(int(seconds * SR)) / SR
    x = np.stack([np.cos(2 * np.pi * hz * t), np.cos(2 * np.pi * hz * 1.5 * t)], 1)
    return (x * amp * 32767).astype(np.int16)


def voice(blocks, seed=0):
    rng = np.random.default_rng(seed)
    x = rng.standard_normal((blocks * N, 1)) * 0.01
    x[len(x) // 3: len(x) // 2] *= 30   # some talking in the middle
    return x.astype(np.float32)


def run(fast, steps, setup=None, blocks=260, mic=True, obs=False, direct=False):
    """Drive the engine by hand: each block the mic, then the send device, the
    headphones (and the stream output). steps: {block: fn(engine)} done before it."""
    e = Engine()
    e.IDLE_FAST = fast
    e.main_stream, e.mon_stream = FakeStream(), FakeStream()
    if obs:
        e.obs_stream = FakeStream()
    e.mic_stream = FakeStream() if mic else None
    e.main_direct = direct   # "straight into my mic": the mic comes in through the fifo
    if setup:
        setup(e)
    m = voice(blocks)
    outs = {"main": [], "mon": [], "obs": []}
    levels = []
    for b in range(blocks):
        if b in steps:
            steps[b](e)
        if mic:
            e._mic(m[b * N:(b + 1) * N], direct=direct)
        for key in ("main", "mon") + (("obs",) if obs else ()):
            buf = np.full((N, 2), 7.0, np.float32)   # stale junk: every block must be written
            getattr(e, f"_{key}")(buf, N)
            outs[key].append(buf)
        levels.append((e.level_main, e.level_mon, e.level_play))
        if b % 10 == 0:
            e.playing()   # the UI's poll, which drops finished voices
    return {k: np.concatenate(v) if v else None for k, v in outs.items()}, levels, e


def same(steps, **kw):
    a, la, ea = run(False, steps, **kw)
    b, lb, eb = run(True, steps, **kw)
    for k in a:
        if a[k] is not None:
            assert np.array_equal(a[k], b[k]), k
    assert la == lb
    return eb


def play(sid="a", **kw):
    return lambda e: e.play(sid, song(), 0.8, **kw)


def test_the_shortcut_is_used_while_nothing_plays():
    calls = []
    _, _, e = run(True, {}, setup=lambda e: setattr(
        e, "_sounds", lambda *a, **k: calls.append(1) or Engine._sounds(e, *a, **k)))
    # half a second to know the filters rang out, then nothing mixed for the rest
    assert 0 < len(calls) < 2 * 60


def test_a_sound_after_a_long_quiet_comes_out_the_same():
    same({150: play()})


def test_a_sound_after_quiet_in_a_voice_chat_mode_with_everything_on():
    def setup(e):
        e.dest = destination.BUILTIN_BY_KEY["discord"]
        e.duck_db = -12.0
        e.eq_gains = [3.0, -2.0, 0.0, 4.0, 1.0, -3.0, 2.0]
        e.eq_target = "all"
        e.mic_gate = True
    same({100: play(), 200: play("b", fade_in=0.05)}, setup=setup)


def test_stopping_and_starting_again_comes_out_the_same():
    def stop(e):
        e.stop("a")
    same({10: play(loop=True), 60: stop, 140: play(), 150: stop, 230: play()})


def test_live_pitch_switched_on_while_quiet_starts_the_same():
    def pitch(e):
        e.sound_pitch = 3.0
    same({5: play(), 140: pitch, 170: play("b")}, blocks=300)

    # sent at volume 0, the send bus counts as quiet while the song still plays, so
    # the shortcut starts the moment it ends, with the song still in the live pitch's
    # history: switching the pitch on right after must start from that history
    def silent(e):
        e.sound_vol = 0.0

    def loud(e):
        e.sound_vol = 1.0
        e.sound_pitch = 3.0
    e = same({0: silent, 5: play(), 72: loud, 73: play("b")}, blocks=140)
    assert e._spitch["main"].shift.running


def test_live_effects_and_speed_after_quiet_come_out_the_same():
    def fx(e):
        e.sound_fx = {"muffle": 0.7}

    def off(e):
        e.sound_fx = {}

    def speed(e):
        e.sound_speed = 1.25
    same({5: play(), 80: fx, 90: play("b"), 120: off, 200: speed, 220: play("c")}, blocks=320)


def test_the_radio_arriving_after_quiet_comes_out_the_same():
    t = np.arange(SR) / SR
    r = (0.5 * np.sin(2 * np.pi * 330 * t)[:, None] * np.ones((1, 2))).astype(np.float32)

    def radio(e):
        e.radio_live = True
        e.feed_radio(r)
    same({120: radio})


def test_mic_check_muting_and_volumes_while_quiet_come_out_the_same():
    def check(e):
        e.mic_check = True

    def uncheck(e):
        e.mic_check = False

    def mute(e):
        e.sending = False
        e.mon_vol = 0.3

    def unmute(e):
        e.sending = True
        e.sound_vol = 0.5
    same({80: check, 120: uncheck, 150: mute, 180: unmute, 200: play()}, blocks=280)


def test_no_mic_and_mic_off_come_out_the_same():
    same({150: play()}, mic=False)
    same({150: play()}, setup=lambda e: setattr(e, "mic_enabled", False))


def test_straight_into_my_mic_comes_out_the_same():
    same({150: play()}, direct=True)


def test_the_stream_output_and_the_taps_are_the_same():
    def taps(e):
        e.main_tap = []
        e.start_test_record(0.5)
        e.start_play_take()
    e = same({60: taps, 100: play()}, obs=True)
    assert e.main_tap and len(e.main_tap) == 200


def test_the_stream_output_skips_the_mixer_while_nothing_plays(monkeypatch):
    """_obs mixed, EQ'd and limited silence every block while the stream output was
    open: it now takes the same idle shortcut as the send device and the headphones."""
    calls = []
    for kind in (Limiter, SafetyLimiter):
        real = kind.process
        monkeypatch.setattr(kind, "process",
                            lambda self, x, real=real: (calls.append(self), real(self, x))[1])

    def setup(e):
        e.limiter_on = True
        e.eq_gains = [3.0, -2.0, 0.0, 4.0, 1.0, -3.0, 2.0]
        e.eq_target = "all"
        sounds, eq = e._sounds, e._eq
        e._sounds = lambda out, *a, **k: (calls.append(("sounds", out)), sounds(out, *a, **k))[1]
        e._eq = lambda out, *a: (calls.append(("eq", out)), eq(out, *a))[1]

    def mark(e):
        calls.append("mark")
    _, _, e = run(True, {100: mark}, setup=setup, mic=False, obs=True, blocks=160)
    stages = {e._send.get(("obs", "Limiter")), e._send.get(("obs", "SafetyLimiter"))}
    obs = [c for c in calls if c == "mark" or c in stages
           or (isinstance(c, tuple) and c[1] == "obs")]
    assert len(obs) > 1 and obs[-1] == "mark"   # it did work at first, none after

    # and a sound after the quiet comes out the same as mixing every block
    same({150: play()}, setup=setup, obs=True, mic=False)


def test_a_quiet_limiter_skips_its_work_only_once_it_rests():
    for kind in (Limiter, SafetyLimiter):
        a, b = kind(SR), kind(SR)
        loud = np.full((N, 2), 1.5, np.float32)
        zeros = np.zeros((N, 2), np.float32)
        a.process(loud)
        b.process(loud)
        skipped = 0
        for _ in range(80):   # the release takes a while: it must play out in full
            want = a.process(zeros)
            got = b.silence(N)
            if got is None:
                skipped += 1
                got = zeros
            assert np.array_equal(want, got)
        assert skipped > 0
        assert np.array_equal(a.process(loud), b.process(loud))   # and back to work as one

        # blocks shorter than the lookahead: the delay line still holds sound after
        # the first quiet one, and that has to come out before it can be skipped
        a, b = kind(SR), kind(SR)
        small = np.full((16, 2), 0.5, np.float32)   # under the ceiling: gain stays 1
        for _ in range(20):
            a.process(small)
            b.process(small)
        for _ in range(20):
            want = a.process(np.zeros((16, 2), np.float32))
            got = b.silence(16)
            assert np.array_equal(want, np.zeros_like(want) if got is None else got)


@pytest.mark.parametrize("rate", [44100, 48000])
def test_quiet_headphones_at_any_rate_write_silence(rate):
    e = Engine()
    e.mon_stream = FakeStream()
    e.rates["mon"] = rate
    buf = np.full((441, 2), 7.0, np.float32)
    for _ in range(100):
        e._mon(buf, 441)
    assert not buf.any() and e.level_mon < 1e-6



def test_merged_peak_passes_match_the_separate_ones():
    """finite_peak / limit_peak (one pass over |x|) give the same samples and level
    as finite + peak and soft_limit + peak, NaNs and peaks over the knee included."""
    from soundboard.engineparts import finite, finite_peak, limit_peak, peak, soft_limit
    rng = np.random.default_rng(2)
    for i in range(400):
        x = (rng.standard_normal((N, 2)) * (0.05, 0.5, 1.5)[i % 3]).astype(np.float32)
        if i % 7 == 0:
            x[rng.integers(N), rng.integers(2)] = (np.nan, np.inf, -np.inf)[i % 3]
        a, b = x.copy(), x.copy()
        pa = peak(finite(a))
        assert finite_peak(b) == pa and np.array_equal(a, b)
        pa = peak(soft_limit(a))
        assert limit_peak(b) == pa and np.array_equal(a, b)
    empty = np.zeros((0, 2), np.float32)
    assert finite_peak(empty) == limit_peak(empty) == 0.0


def test_mono_and_stereo_mics_go_out_the_same_as_before(monkeypatch):
    """The mic callback's merged level pass: a mono mic, and a stereo one with a dead
    channel, with a NaN now and then, give the level and samples sent they did with
    the separate passes."""
    from soundboard import engine as eng
    from soundboard.engineparts import finite, peak

    def run(ch):
        e = Engine()
        e.main_stream, e.mon_stream = FakeStream(), FakeStream()
        rng = np.random.default_rng(ch)
        sent, levels = [], []
        for b in range(120):
            x = (rng.standard_normal((N, ch)) * 0.1).astype(np.float32)
            if ch == 2:
                x[:, 1] *= 0.001   # (a dead channel: the live one is copied over it)
            if b % 13 == 5:
                x[3, 0] = np.nan
            e._mic(x)
            buf = np.zeros((N, 2), np.float32)
            e._main(buf, N)
            sent.append(buf)
            levels.append((e.level_mic, e.level_main))
        return np.concatenate(sent), levels

    for ch in (1, 2):
        a, la = run(ch)
        with monkeypatch.context() as mp:   # the separate passes, as before
            mp.setattr(eng, "finite_peak", lambda x: peak(finite(x)))
            b, lb = run(ch)
        assert np.array_equal(a, b) and la == lb and np.isfinite(a).all()
