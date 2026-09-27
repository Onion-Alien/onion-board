"""Voice changer effects and the chain that runs them on the mic."""
import numpy as np
import pytest

from soundboard import voicefx
from soundboard.engine import Engine
from soundboard.voicefx import REGISTRY, VoiceChain, defaults

RATE = 48000


def sine(freq, seconds=1.0, rate=RATE, amp=0.3):
    t = np.arange(int(seconds * rate)) / rate
    return (np.sin(2 * np.pi * freq * t) * amp).astype(np.float32)


def run_blocks(effect, x, block):
    return np.concatenate([effect.run(x[i:i + block], effect.rate)
                           for i in range(0, len(x), block)])


def dominant_hz(x, rate=RATE):
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return np.fft.rfftfreq(len(x), 1 / rate)[np.argmax(spec)]


def spec_for(**fx):
    return {"enabled": True, "effects": {t: {"on": True, **v} for t, v in fx.items()}}


# ---------------------------------------------------------------- effects

@pytest.mark.parametrize("st, want", [(12, 400), (-12, 100), (7, 200 * 2 ** (7 / 12))])
def test_pitch_shift_moves_the_pitch(st, want):
    e = REGISTRY["pitch"](RATE, {"semitones": st})
    y = run_blocks(e, sine(200, 1.5), 480)[RATE // 2:]      # skip the warm-up
    assert abs(dominant_hz(y) - want) < want * 0.03


def test_pitch_zero_is_a_passthrough():
    e = REGISTRY["pitch"](RATE, {"semitones": 0})
    x = sine(300, 0.1)
    assert np.array_equal(e.run(x, RATE), x)


@pytest.mark.parametrize("etype", ["pitch", "distortion", "robot", "echo", "reverb", "radio",
                                   "tone", "chorus"])
def test_block_size_never_changes_the_sound(etype):
    """The mic delivers whatever block size the driver likes; state must carry over."""
    vals = {**defaults(etype), "noise": 0.0, "semitones": 5, "bass": 3, "presence": -2}
    x = (sine(220, 0.6) + sine(1300, 0.6, amp=0.1)).astype(np.float32)
    a = run_blocks(REGISTRY[etype](RATE, vals), x, 480)
    b = run_blocks(REGISTRY[etype](RATE, vals), x, 173)
    assert np.allclose(a, b, atol=1e-5)


def test_pitch_latency_is_a_few_blocks_and_stays_put():
    e = REGISTRY["pitch"](RATE, {"semitones": -7})
    run_blocks(e, sine(150, 3.0), 480)
    pads = e.pads
    run_blocks(e, sine(150, 3.0), 480)
    assert pads == 0 and e.pads == 0          # the head start keeps the resampler fed
    assert len(e.inb) < RATE * 0.06           # ~ SEQ + SEEK + a block of backlog


def test_live_pitch_switching_on_and_off_has_no_gap_or_click():
    """It used to start from silence for its latency (~40 ms) when switched on,
    and jump when switched off."""
    from soundboard.engine import LivePitch
    x = np.repeat(sine(440, 1.0, amp=0.5)[:, None], 2, 1)
    lp = LivePitch(RATE)
    sts = [0.0] * 10 + [3.0] * 30 + [0.0] * 20
    y = np.concatenate([lp.process(x[i * 480:(i + 1) * 480], st) for i, st in enumerate(sts)])
    peaks = np.abs(y).reshape(-1, 480, 2).max(axis=(1, 2))
    assert peaks.min() > 0.3, peaks.round(2)
    assert np.abs(np.diff(y, axis=0)).max() < 0.1
    assert not any(e.running for e in lp._ch)        # faded back to the dry signal
    assert np.array_equal(y[-480:], x[len(sts) * 480 - 480:len(sts) * 480])


def test_echo_repeats_at_the_delay_and_decays():
    e = REGISTRY["echo"](RATE, {"delay": 100, "feedback": 0.5, "mix": 1.0, "tone": 12000})
    x = np.zeros(RATE // 2, np.float32)
    x[0] = 1.0
    y = run_blocks(e, x, 480)
    d = RATE // 10
    assert y[0] == 1.0
    assert y[d] == pytest.approx(1.0)       # first echo, full mix
    assert y[2 * d] == pytest.approx(0.5)   # then scaled by the feedback
    assert y[3 * d] == pytest.approx(0.25)
    assert abs(y[d // 2]) < 1e-6


@pytest.mark.parametrize("rate", [44100, 48000, 96000])
def test_every_preset_is_stable_and_sane(rate):
    rng = np.random.default_rng(0)
    x = np.stack([(rng.standard_normal(rate) * 0.3).astype(np.float32)] * 2, 1)
    for name, fx in voicefx.PRESETS.items():
        c = VoiceChain()
        c.configure(spec_for(**fx))
        y = np.concatenate([c.process(x[i:i + 441], rate) for i in range(0, len(x), 441)])
        assert not c.errors, name
        assert np.all(np.isfinite(y)), name
        assert np.max(np.abs(y)) < 4, f"{name} @ {rate} is far too loud"
        assert np.sqrt(np.mean(y ** 2)) > 0.01, f"{name} @ {rate} went silent"


def test_presets_only_name_real_effects_and_params():
    for name, fx in voicefx.PRESETS.items():
        for etype, vals in fx.items():
            assert etype in REGISTRY, name
            keys = {q.key for q in REGISTRY[etype].params}
            assert set(vals) <= keys, f"{name}: {etype} has unknown {set(vals) - keys}"


def test_params_are_clamped():
    e = REGISTRY["echo"](RATE, {"delay": 99999, "feedback": "junk"})
    assert e.p["delay"] == 1000 and e.p["feedback"] == 0.35


def test_non_finite_params_fall_back_to_the_default():
    e = REGISTRY["echo"](RATE, {"delay": float("nan"), "mix": float("inf")})
    assert e.p["delay"] == 250 and e.p["mix"] == 0.4
    assert np.all(np.isfinite(e.run(np.full(480, 0.1, np.float32), RATE)))


@pytest.mark.parametrize("lo, hi, step", [(1, 1, 0), (0, 1, 2), (2, 1, 0), (0, 1, -1),
                                          (0, float("nan"), 0)])
def test_a_param_with_no_room_to_move_is_refused(lo, hi, step):
    class Stuck(voicefx.Effect):
        type, name = "test.stuck", "Stuck"
        params = (voicefx.Param("k", "K", lo, hi, lo, "", step),)

        def run(self, x, rate):
            return x

    with pytest.raises(ValueError, match="lo < hi"):
        voicefx.register(Stuck)
    assert "test.stuck" not in REGISTRY


@pytest.mark.parametrize("raw, want", [
    (None, {"effects": {}}),
    ([1, 2], {"effects": {}}),
    ({"enabled": "yes", "preset": ["x"], "effects": None}, {"effects": {}}),
    ({"effects": []}, {"effects": {}}),
    ({"effects": {"pitch": None, "echo": [1, 2]}}, {"effects": {}}),
    ({"enabled": True, "preset": "Robot",
      "effects": {"pitch": {"on": "yes", "semitones": "abc", "mix": float("nan")},
                  "echo": {"on": True, "delay": 400, "mix": True}}},
     {"enabled": True, "preset": "Robot",
      "effects": {"pitch": {}, "echo": {"on": True, "delay": 400}}}),
])
def test_a_damaged_saved_spec_is_cleaned(raw, want):
    assert voicefx.clean_spec(raw) == want


# ---------------------------------------------------------------- chain

def test_disabled_chain_returns_the_same_block():
    c = VoiceChain()
    c.configure({"enabled": False, "effects": {"robot": {"on": True}}})
    x = np.ones((480, 2), np.float32)
    assert c.process(x, RATE) is x


def test_effects_run_in_registry_order_and_off_ones_are_skipped():
    c = VoiceChain()
    c.configure({"enabled": True, "effects": {"reverb": {"on": True}, "pitch": {"on": True},
                                              "robot": {"on": False}}})
    c.process(np.zeros((64, 2), np.float32), RATE)
    assert [e.type for e in c._effects] == ["pitch", "reverb"]


def test_moving_a_slider_keeps_the_effect_state():
    c = VoiceChain()
    c.configure(spec_for(echo={"delay": 200}))
    c.process(np.zeros((64, 2), np.float32), RATE)
    first = c._effects[0]
    c.configure(spec_for(echo={"delay": 200, "mix": 0.9}))
    assert c._effects[0] is first and first.p["mix"] == 0.9


def test_rate_change_rebuilds_effects():
    c = VoiceChain()
    c.configure(spec_for(pitch={"semitones": 3}))
    c.process(np.zeros((64, 2), np.float32), 48000)
    c.process(np.zeros((64, 2), np.float32), 44100)
    assert c._effects[0].rate == 44100


def test_a_broken_effect_is_bypassed_not_fatal(monkeypatch):
    class Boom(voicefx.Effect):
        type, name = "test.boom", "Boom"

        def run(self, x, rate):
            raise RuntimeError("kaboom")

    monkeypatch.setitem(REGISTRY, "test.boom", Boom)
    c = VoiceChain()
    c.configure(spec_for(**{"test.boom": {}, "robot": {"mix": 0}}))
    x = np.full((32, 2), 0.25, np.float32)
    y = c.process(x, RATE)                       # the robot (mix 0) still passes the mic
    assert np.allclose(y, 0.25)
    assert "kaboom" in c.errors["test.boom"]
    assert [e.type for e in c._effects] == ["robot"]
    c.configure(spec_for(**{"test.boom": {}}))   # stays off until errors are cleared
    assert c._effects == ()


def test_an_effect_that_cant_start_is_left_out_and_reported(monkeypatch):
    class NoStart(voicefx.Effect):
        type, name = "test.nostart", "No start"

        def __init__(self, rate, values=None):
            raise RuntimeError("missing model file")

    monkeypatch.setitem(REGISTRY, "test.nostart", NoStart)
    c = VoiceChain()
    c.configure(spec_for(**{"test.nostart": {}, "robot": {"mix": 0}}))
    y = c.process(np.full((32, 2), 0.25, np.float32), RATE)
    assert np.allclose(y, 0.25)
    assert "missing model file" in c.errors["test.nostart"]
    assert [e.type for e in c._effects] == ["robot"]


def test_effect_returning_garbage_is_bypassed(monkeypatch):
    class Nan(voicefx.Effect):
        type, name = "test.nan", "NaN"

        def run(self, x, rate):
            return x * np.nan

    monkeypatch.setitem(REGISTRY, "test.nan", Nan)
    c = VoiceChain()
    c.configure(spec_for(**{"test.nan": {}}))
    y = c.process(np.full((32, 2), 0.5, np.float32), RATE)
    assert np.all(np.isfinite(y)) and "test.nan" in c.errors


def test_tap_sees_mono_mic_and_replace_mutes_it():
    got = []
    c = VoiceChain()
    c.tap = lambda m, r: got.append((m.copy(), r))
    c.replace = True
    x = np.stack([np.full(16, 0.2), np.full(16, 0.4)], 1).astype(np.float32)
    y = c.process(x, 44100)
    assert np.allclose(got[0][0], 0.3) and got[0][1] == 44100
    assert not y.any()


def test_a_failing_tap_is_detached():
    c = VoiceChain()
    c.tap = lambda m, r: 1 / 0
    x = np.full((16, 2), 0.2, np.float32)
    c.process(x, RATE)
    assert c.tap is None


# ---------------------------------------------------------------- engine hook

def test_engine_mic_runs_through_the_chain():
    e = Engine()
    e.main_stream = object()             # stands in for an open cable output
    c = VoiceChain()
    c.replace = True
    e.voice_chain = c
    e._mic(np.full((480, 1), 0.5, np.float32))
    assert e.level_mic == pytest.approx(0.5)     # the meter shows the real mic
    e.ring_main.prefill = 0
    out = e.ring_main.read(480)
    assert out is not None and not out.any()     # but the cable got the chain's output


def test_effects_wait_for_the_mic_rate_before_starting(monkeypatch):
    class NeedsRate(voicefx.Effect):
        type, name = "test.needsrate", "Needs rate"

        def __init__(self, rate, values=None):
            super().__init__(rate, values)
            self.step = 1.0 / rate           # a rate of 0 would raise here

        def run(self, x, rate):
            return x

    monkeypatch.setitem(REGISTRY, "test.needsrate", NeedsRate)
    c = VoiceChain()
    c.configure(spec_for(**{"test.needsrate": {}}))   # before the first mic block
    assert c.errors == {} and c._effects == ()
    c.process(np.zeros((32, 2), np.float32), RATE)
    assert [e.type for e in c._effects] == ["test.needsrate"]
