"""Voice changer effects and the chain that runs them on the mic."""
import numpy as np
import pytest

from soundboard import voicefx
from soundboard.audio.engine import Engine
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
                                   "tone", "chorus", "ringmod", "flanger", "wobble", "harmony",
                                   "bitcrush"])
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
    from soundboard.audio.engine import LivePitch
    x = np.repeat(sine(440, 1.0, amp=0.5)[:, None], 2, 1)
    lp = LivePitch(RATE)
    sts = [0.0] * 10 + [3.0] * 30 + [0.0] * 20
    y = np.concatenate([lp.process(x[i * 480:(i + 1) * 480], st) for i, st in enumerate(sts)])
    peaks = np.abs(y).reshape(-1, 480, 2).max(axis=(1, 2))
    assert peaks.min() > 0.3, peaks.round(2)
    assert np.abs(np.diff(y, axis=0)).max() < 0.1
    assert not lp.shift.running                      # faded back to the dry signal
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
    c.process(np.zeros((64, 2), np.float32), RATE)
    assert c._effects[0] is first and first.p["mix"] == 0.9


def test_rate_change_rebuilds_effects():
    c = VoiceChain()
    c.configure(spec_for(pitch={"semitones": 3}))
    c.process(np.zeros((64, 2), np.float32), 48000)
    c.process(np.zeros((64, 2), np.float32), 44100)
    assert c._effects[0].rate == 44100


def test_configure_racing_a_rate_change_ends_at_the_new_rate(monkeypatch):
    """configure() (UI thread) used to build the effects itself, at the rate it last
    saw. When the mic changed rate meanwhile (the mic thread rebuilt for it in between),
    the UI's effects for the old rate went in last, and process() never rebuilt them:
    the voice played at the wrong pitch until the next change. Now only process()
    builds, for the rate of the block in hand."""
    c = VoiceChain()
    block = np.zeros((64, 2), np.float32)

    class Racy(voicefx.Effect):
        type, name = "test.racy", "Racy"
        armed = False

        def __init__(self, rate, values=None):
            super().__init__(rate, values)
            if rate == 48000 and Racy.armed:
                # built at the old rate, and meanwhile the mic's next block comes at 44.1k
                Racy.armed = False
                c.process(block, 44100)

        def run(self, x, rate):
            return x

    monkeypatch.setitem(REGISTRY, "test.racy", Racy)
    c.configure(spec_for(robot={"mix": 0}))
    c.process(block, 48000)
    Racy.armed = True
    c.configure(spec_for(robot={"mix": 0}, **{"test.racy": {}}))
    for _ in range(2):
        c.process(block, 44100)
        assert [(e.type, e.rate) for e in c._effects] == [("robot", 44100),
                                                          ("test.racy", 44100)]


def test_a_bypass_on_the_mic_thread_isnt_undone_by_the_next_block():
    c = VoiceChain()
    c.configure(spec_for(robot={"mix": 0}))
    c.process(np.zeros((64, 2), np.float32), RATE)
    c.errors["robot"] = "boom"   # as process() records a failing effect
    c._effects = ()
    c.configure(spec_for(robot={"mix": 0.5}))   # a slider moved: still bypassed
    c.process(np.zeros((64, 2), np.float32), RATE)
    assert c._effects == ()
    c.clear_errors()                            # another go
    c.process(np.zeros((64, 2), np.float32), RATE)
    assert [e.type for e in c._effects] == ["robot"]


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
    c.process(x, RATE)
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


def test_the_computer_voice_gets_the_voice_changer():
    import numpy as np

    from soundboard.voicefx import PRESETS, VoiceChain
    rate = 48000
    t = np.arange(rate) / rate
    clip = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    chain = VoiceChain()
    effects = {k: {"on": True, **v} for k, v in PRESETS["Robot"].items()}
    chain.configure({"enabled": False, "effects": effects})
    assert chain.render(clip, rate) is clip            # changer off: untouched
    chain.configure({"enabled": True, "effects": effects})
    out = chain.render(clip, rate)
    assert out.shape == clip.shape and np.all(np.isfinite(out))
    assert not np.allclose(out, clip, atol=1e-3)       # changed


# --------------------------------------------------------------------------- new voices

SR = 48000


def _vowel(f0=120.0, secs=1.5):
    """A buzzy vowel: a pulse train through three formant resonators."""
    from soundboard.audio.dsp import lfilter
    n = int(SR * secs)
    ph = np.cumsum(np.full(n, f0 / SR))
    x = (np.diff(np.floor(ph), prepend=0) > 0).astype(np.float64)
    y = np.zeros(n)
    for f, bw in ((700, 80), (1220, 90), (2600, 120)):
        r = np.exp(-np.pi * bw / SR)
        y += lfilter([1 - r], [1, -2 * r * np.cos(2 * np.pi * f / SR), r * r], x)
    return (y / np.max(np.abs(y)) * 0.3).astype(np.float32)


def _run(etype, cfg, x, block=480):
    e = voicefx.REGISTRY[etype](SR, cfg)
    return np.concatenate([e.run(x[i:i + block], SR) for i in range(0, len(x) - block + 1, block)])


def _centroid(y):
    sp = np.abs(np.fft.rfft(y[SR // 2:]))
    f = np.fft.rfftfreq(len(y) - SR // 2, 1 / SR)
    return float((sp * f).sum() / sp.sum())


def _f0(y):
    from soundboard.voicefx.builtin.parts import _PitchTracker
    tr = _PitchTracker(SR)
    v = [tr.update(y[i:i + 480]) for i in range(SR // 2, len(y) - 480, 480)]
    return float(np.median([a for a in v if a > 0]))


def test_natural_sound_moves_the_pitch_but_keeps_the_voice_shape():
    x = _vowel()
    cartoon = _run("pitch", {"semitones": 5}, x)
    natural = _run("pitch", {"semitones": 5, "natural": 1}, x)
    assert _f0(cartoon) == pytest.approx(120 * 2 ** (5 / 12), rel=0.03)
    assert _f0(natural) == pytest.approx(120 * 2 ** (5 / 12), rel=0.03)
    c0 = _centroid(x)
    assert _centroid(cartoon) > c0 * 1.12            # formants went up with the pitch
    assert abs(_centroid(natural) / c0 - 1) < 0.06   # ...or stayed where they were


def test_voice_size_alone_keeps_the_pitch():
    x = _vowel()
    bigger = _run("pitch", {"size": 4}, x)
    assert _f0(bigger) == pytest.approx(120, rel=0.03)
    assert _centroid(bigger) < _centroid(x) * 0.95


def test_tone_mid_lifts_the_middle_only():
    t = np.arange(SR) / SR
    x = sum(np.sin(2 * np.pi * f * t) for f in (150, 1000, 7000)).astype(np.float32) * 0.1
    y = _run("tone", {"mid": 9}, x)[SR // 2:]
    sp_x = np.abs(np.fft.rfft(x[SR // 2:SR // 2 + len(y)]))
    sp_y = np.abs(np.fft.rfft(y))
    k = len(y) / SR
    gain = {f: 20 * np.log10(sp_y[int(f * k)] / sp_x[int(f * k)]) for f in (150, 1000, 7000)}
    assert gain[1000] == pytest.approx(9, abs=0.5)
    assert abs(gain[150]) < 1.5 and abs(gain[7000]) < 1.5
    # old saves have no "mid": it stays flat
    assert voicefx.REGISTRY["tone"](SR, {"bass": 3}).p["mid"] == 0


def test_voice_size_reshapes_the_blended_in_voice_too():
    """Below 100% Mix your own voice is blended back in: "Voice size on my voice too"
    changes it as well, or the speaker stays recognisable under the effect. Saves from
    before the knob (no key) leave it as it was."""
    x = _vowel()
    y = _run("pitch", {"size": -4, "mix": 0.01, "under": 1}, x)   # almost all own voice
    assert _f0(y) == pytest.approx(120, rel=0.03)
    assert _centroid(y) > _centroid(x) * 1.05
    old = _run("pitch", {"size": -4, "mix": 0.01}, x)
    assert _centroid(old) == pytest.approx(_centroid(x), rel=0.03)


def _onset(y, thr=0.05):
    return int(np.argmax(np.abs(y) > thr * np.max(np.abs(y))))


def test_gap_between_voices_lines_the_blended_in_voice_up():
    """Below 100% Mix your own voice used to come out ~40 ms before the shifted one
    (a slapback echo). Gap 0 holds it back to line up; no key (old saves) keeps it."""
    x = np.concatenate([np.zeros(SR // 4, np.float32), _vowel(secs=0.6)])
    wet = _run("pitch", {"semitones": -7, "mix": 1}, x)
    old = _run("pitch", {"semitones": -7, "mix": 0.0001}, x)
    together = _run("pitch", {"semitones": -7, "mix": 0.0001, "gap": 0}, x)
    assert _onset(old) == pytest.approx(_onset(x), abs=48)
    assert _onset(wet) - _onset(old) > SR * 0.03
    assert _onset(together) == pytest.approx(_onset(wet), abs=SR * 0.004)


def test_blur_puts_a_tail_on_the_new_voice_only():
    """Blur reverbs the shifted voice, not the blended-in own voice; no key = none."""
    x = np.concatenate([_vowel(secs=0.4), np.zeros(SR // 2, np.float32)])
    tail = slice(int(SR * 0.55), int(SR * 0.75))   # after the voice and the shift's delay

    def level(cfg):
        return float(np.sqrt(np.mean(_run("pitch", cfg, x)[tail] ** 2)))

    assert level({"semitones": -7}) < 1e-4
    assert level({"semitones": -7, "blur": 0.6}) > 1e-3
    # at almost 0% Mix only your own voice is left: Blur doesn't touch it
    assert level({"semitones": -7, "mix": 0.001, "blur": 0.6}) < 1e-4


def test_old_pitch_settings_sound_as_before():
    """No natural / size keys (old saves, sounds, music): no formant stage, old delay."""
    e = voicefx.REGISTRY["pitch"](SR, {"semitones": 5})
    assert e.latency() < 0.045
    _run("pitch", {"semitones": 5}, _vowel(secs=0.3))
    assert e.fstage is None


def test_autotune_snaps_to_a_note():
    x = _vowel(f0=120.0)                              # between A#2 and B2
    y = _run("pitch", {"tune": 1}, x)
    assert _f0(y) == pytest.approx(123.47, rel=0.01)  # B2


@pytest.mark.parametrize("mic_db", [-60, -48, -30, -12])
def test_autotune_corrects_quiet_headset_speech(mic_db):
    x = _vowel(f0=120.0)
    x *= 10 ** (mic_db / 20) / np.max(np.abs(x))
    y = _run("pitch", {"tune": 1}, x)
    # Measure at a fixed level so this checks the correction, independently of
    # the output pitch detector's own silence threshold.
    assert _f0(y / np.max(np.abs(y))) == pytest.approx(123.47, rel=0.01)


@pytest.mark.parametrize("mic_db", [-48, -30, -12])
@pytest.mark.parametrize("block", [173, 480, 1024])
def test_autotune_preset_has_character_even_on_an_in_tune_voice(mic_db, block):
    # A3 needs no correction: hard tuning alone sounded like the unchanged mic.
    x = sine(220, amp=10 ** (mic_db / 20))
    chain = VoiceChain()
    chain.configure(spec_for(**voicefx.PRESETS["Autotune"]))
    y = chain.render(x, RATE, block)[RATE // 4:3 * RATE // 4]
    sp = np.abs(np.fft.rfft(y * np.hanning(len(y)))) ** 2
    freq = np.fft.rfftfreq(len(y), 1 / RATE)
    assert sp[freq > 400].sum() > 0.001 * sp.sum()
    assert dominant_hz(y) == pytest.approx(220, abs=3)
    assert np.all(np.isfinite(y)) and np.max(np.abs(y)) < 1


@pytest.mark.parametrize("mic_db", [-48, -30, -12])
@pytest.mark.parametrize("block", [173, 480, 1024])
def test_hothead_preset_changes_normal_speech_without_waiting_for_a_shout(mic_db, block):
    # Equal bass and midrange: the megaphone must audibly narrow the voice from
    # the first words, even on a mic that never reaches the blowout threshold.
    x = sine(150, 0.4, amp=0.5) + sine(1500, 0.4, amp=0.5)
    x *= 10 ** (mic_db / 20)
    chain = VoiceChain()
    chain.configure(spec_for(**voicefx.PRESETS["Hothead"]))
    y = chain.render(x, RATE, block)[RATE // 10:]
    sp = np.abs(np.fft.rfft(y * np.hanning(len(y)))) ** 2
    freq = np.fft.rfftfreq(len(y), 1 / RATE)
    assert sp[freq < 250].sum() < 0.05 * sp[(freq > 1400) & (freq < 1600)].sum()
    assert np.max(np.abs(y)) > 0.1 * np.max(np.abs(x))
    assert np.all(np.isfinite(y)) and np.max(np.abs(y)) < 1


def test_quiet_pitch_tracker_still_rejects_silence_and_unvoiced_noise():
    from soundboard.voicefx.builtin.parts import _PitchTracker
    tracker = _PitchTracker(RATE)
    rng = np.random.default_rng(7)
    for x in (np.zeros(tracker.window, np.float32),
              rng.normal(0, 0.01, tracker.window).astype(np.float32)):
        assert tracker.measure(x) == 0


@pytest.mark.parametrize("name", ["Hothead", "Autotune"])
@pytest.mark.parametrize("block", [64, 173, 1024])
def test_hothead_and_autotune_stream_through_mic_rate_changes(name, block):
    chain = VoiceChain()
    chain.configure(spec_for(**voicefx.PRESETS[name]))
    for rate in (48000, 8000, 16000, 44100, 48000):
        x = sine(120, 0.3, rate=rate, amp=0.01)
        # Pauses and empty callbacks must not disable an effect or leave noise.
        x = np.r_[x, np.zeros(rate // 4, np.float32)]
        out = []
        for i in range(0, len(x), block):
            m = np.repeat(x[i:i + block, None], 2, axis=1)
            y = chain.process(m, rate)
            assert y.shape == m.shape and np.all(np.isfinite(y))
            out.append(y)
            assert chain.process(m[:0], rate).shape == (0, 2)
        y = np.concatenate(out)
        assert np.max(np.abs(y)) < 1
        assert np.max(np.abs(y[:int(rate * 0.3)])) > 0.001
        assert np.max(np.abs(y[-rate // 20:])) < 0.001
        assert not chain.errors


@pytest.mark.parametrize("etype,cfg", [
    ("growl", {"amount": 1}), ("helmet", {}), ("shout", {"threshold": -30}),
    ("robot", {"follow": 1}), ("radio", {"squelch": 1}),
    ("pitch", {"semitones": -7, "natural": 1, "size": 3, "tune": 0.5})])
def test_new_effects_give_finite_audio_of_the_same_length(etype, cfg):
    for block in (64, 480, 1024):
        y = _run(etype, cfg, _vowel(secs=0.5), block)
        assert y.dtype == np.float32 and np.all(np.isfinite(y))
        assert len(y) == (int(SR * 0.5) // block) * block
        assert np.max(np.abs(y)) < 2.0


def test_growl_adds_an_octave_below():
    y = _run("growl", {"amount": 1, "tone": 1000}, _vowel(f0=200.0))
    sp = np.abs(np.fft.rfft(y[SR // 4:]))
    f = np.fft.rfftfreq(len(y) - SR // 4, 1 / SR)
    sub = sp[(f > 95) & (f < 105)].max()
    assert sub > 0.05 * sp[(f > 195) & (f < 205)].max()


def test_walkie_talkie_clicks_when_you_start_and_stop():
    x = np.concatenate([np.zeros(SR // 2), _vowel(secs=0.5), np.zeros(SR)]).astype(np.float32)
    y = _run("radio", {"squelch": 1, "noise": 0}, x)
    start = y[SR // 2:SR // 2 + 1500]
    tail = y[SR + int(SR * 0.3):SR + int(SR * 0.6)]
    assert np.max(np.abs(tail)) > 0.02                 # the "kshh" after you let go
    assert np.max(np.abs(start)) > 0.05


def test_every_preset_runs_and_reports_its_delay():
    x = np.stack([_vowel(secs=0.4)] * 2, 1)
    for name, fx in voicefx.PRESETS.items():
        ch = voicefx.VoiceChain()
        ch.configure({"enabled": True, "effects": {t: {"on": True, **c} for t, c in fx.items()}})
        for i in range(0, len(x) - 479, 480):
            y = ch.process(x[i:i + 480], SR)
            assert np.all(np.isfinite(y))
        assert not ch.errors, name
        assert 0 <= ch.latency() < 0.1, name


def test_every_built_in_text_can_be_translated():
    """The built-in effects' names, descriptions, settings and slider ends and the voices'
    names all have a line in voicefx.builtin.shown_texts(): the Voice tab translates
    through it, while the English stays what settings and share codes keep."""
    from soundboard import i18n
    from soundboard.voicefx import builtin
    table = builtin.shown_texts()
    builtins = [c for c in REGISTRY.values() if c.__module__ == builtin.__name__]
    texts = {t for c in builtins for t in (c.name, c.description)}
    texts |= {t for c in builtins for q in c.params for t in (q.label, *q.ends) if t}
    texts |= set(voicefx.PRESETS)
    assert texts <= set(table), sorted(texts - set(table))
    assert all(k == v for k, v in table.items())      # English: as written
    try:
        i18n.set_language(i18n.PSEUDO)
        assert i18n.is_pseudo(voicefx.shown("Chipmunk"))
        assert voicefx.shown("an add-on's own text") == "an add-on's own text"
    finally:
        i18n.set_language(i18n.ENGLISH)
    assert voicefx.shown("Chipmunk") == "Chipmunk"


# ------------------------------------------------- found by the voice stress test

def test_an_empty_mic_block_bypasses_nothing():
    """A device can hand over an empty block. Six effects failed on one, and a failing
    effect is bypassed for good: a changed voice turned back into yours mid-call."""
    chain = VoiceChain()
    chain.configure(spec_for(**voicefx.PRESETS["Demon"], robot={}, chorus={}))
    x = np.repeat(sine(150, 0.1)[:, None], 2, 1)
    for block in (x[:480], x[:0], np.zeros((0, 1), np.float32), x[480:960]):
        assert chain.process(block, RATE).shape == (len(block), 2)
    assert chain.errors == {}


def _corner(y):
    """The sharpest bend in the waveform after the warm-up: a click is a sharp corner."""
    return float(np.abs(np.diff(y[RATE // 2:], 2)).max())


def _dragged(etype, key, base, change=None):
    """`key` dragged end to end and back once a second in the slider's own steps, on a
    steady tone, the way a hand moves it while you talk."""
    q = next(q for q in REGISTRY[etype].params if q.key == key)
    e = REGISTRY[etype](RATE, base)
    x = sine(220, 2.5)
    out = []
    for k, i in enumerate(range(0, len(x), 480)):
        ph = (k % 100) / 100
        v = q.lo + (2 * ph if ph < 0.5 else 2 - 2 * ph) * (q.hi - q.lo)
        if q.step:
            v = q.lo + round((v - q.lo) / q.step) * q.step
        e.set_values({**base, key: v})
        out.append(e.run(x[i:i + 480], RATE))
    held = max(_corner(run_blocks(REGISTRY[etype](RATE, {**base, key: v}), x, 480))
               for v in (q.lo, base.get(key, q.default), q.hi))
    return _corner(np.concatenate(out)), held


BLEND = {"semitones": -5, "mix": 0.5, "gap": 0, "size": 4, "under": 1}


@pytest.mark.parametrize("etype, key, base", [
    ("pitch", "semitones", {}), ("pitch", "size", {}),
    ("pitch", "mix", BLEND), ("pitch", "gap", BLEND), ("pitch", "semitones", BLEND),
    ("compressor", "boost", {}), ("compressor", "attack", {}), ("radio", "drive", {"noise": 0}),
    ("distortion", "drive", {}), ("polish", "warmth", {}), ("polish", "ceiling", {}),
    ("polish", "deess", {}),
    ("shout", "drive", {"threshold": -40}), ("helmet", "size", {}), ("chorus", "depth", {}),
    ("echo", "delay", {}), ("echo", "tone", {}), ("reverb", "predelay", {}),
    ("reverb", "size", {}), ("ringmod", "freq", {}), ("ringmod", "mix", {}),
    ("flanger", "depth", {}), ("flanger", "feedback", {}), ("wobble", "vibrato", {}),
    ("wobble", "tremolo", {}), ("harmony", "level", {}), ("bitcrush", "mix", {}),
    ("bitcrush", "bits", {}), ("bitcrush", "rate", {})])
def test_dragging_a_slider_while_you_talk_doesnt_click(etype, key, base):
    """Each of these stepped a gain, jumped a delay or restarted a stage from silence
    at every block while its slider moved: a crackle for everyone listening."""
    dragged, held = _dragged(etype, key, base)
    assert dragged <= max(0.02, 5 * held), (dragged, held)


def _syllables(seed, n=24):
    """Sung-ish syllables: a buzzy vowel at a new pitch each time, gliding up to a
    semitone, with short pauses between (what autotune keeps snapping on)."""
    rng = np.random.default_rng(seed)
    parts, ph = [], 0.0
    for _ in range(n):
        m = int(RATE * rng.uniform(0.12, 0.3))
        f = rng.uniform(100, 220) * 2 ** (rng.uniform(-1, 1) / 12 * np.linspace(0, 1, m))
        p = ph + 2 * np.pi * np.cumsum(f) / RATE
        ph = p[-1]
        parts += [sum(np.sin(k * p) / k for k in range(1, 8)) * 0.15 * np.hanning(m),
                  np.zeros(int(RATE * rng.uniform(0, 0.08)))]
    return np.concatenate(parts).astype(np.float32)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_autotune_never_leaves_a_hole(seed):
    """Snapping up a note sped the reading past what the stretcher had ready, and the
    gap was filled with silence; now that block is read a touch slower instead."""
    x = _syllables(seed)
    for st in (-9, -5):
        e = REGISTRY["pitch"](RATE, {"semitones": st, "tune": 1})
        run_blocks(e, x, 480)
        assert e.pads == 0, st


def test_pitch_dragged_up_while_running_never_waits():
    e = REGISTRY["pitch"](RATE, {"semitones": -12, "size": 4})   # (size: it never stops)
    x = sine(220, 2.0)
    for k, i in enumerate(range(0, len(x), 480)):
        e.set_values({"semitones": min(-12 + k * 0.5, 12), "size": 4})
        e.run(x[i:i + 480], RATE)
    assert e.pads == 0 and e.slows > 0


def test_walkie_talkie_clicks_stay_in_the_radio_band():
    # raw white noise on top of the band-limited voice sounded like a hi-hat
    x = np.concatenate([np.zeros(SR // 2), _vowel(secs=0.5), np.zeros(SR)]).astype(np.float32)
    y = _run("radio", {"squelch": 1, "noise": 0, "low": 450, "high": 2700}, x)
    for seg in (y[SR // 2:SR // 2 + 1500], y[SR + int(SR * 0.3):SR + int(SR * 0.6)]):
        sp = np.abs(np.fft.rfft(seg)) ** 2
        f = np.fft.rfftfreq(len(seg), 1 / SR)
        assert sp[f > 5000].sum() < 0.1 * sp.sum()


@pytest.mark.parametrize("mic_db", [-36, -12])
def test_hothead_blows_out_on_shouting_at_any_mic_level(mic_db):
    # a fixed level alone never went off on a quiet mic: it learns how loud you talk
    rng = np.random.default_rng(1)
    words = np.repeat(rng.uniform(0.5, 1.0, 24), SR // 4) * np.tile(
        np.r_[np.ones(SR // 5), np.zeros(SR // 20)], 24)[:SR * 6]
    x = (_vowel(secs=6.0) / 0.55 * words * 10 ** (mic_db / 20)).astype(np.float32)
    x[SR * 4:SR * 5] *= 10 ** (12 / 20)                # one second of shouting
    e = voicefx.REGISTRY["shout"](SR, {"threshold": -14, "drive": 16})
    amt = []
    for i in range(0, len(x), 480):
        e.run(x[i:i + 480], SR)
        amt.append(e.amt)
    amt = np.array(amt)
    assert amt[200:400].max() < 0.3                   # talking normally: clean
    assert amt[420:500].max() > 0.9                    # shouting: blown out


def test_renamed_voice_keeps_its_pick():
    assert voicefx.clean_spec({"preset": "Female voice"})["preset"] == "High voice"
    assert "High voice" in voicefx.PRESETS


# ---------------------------------------------------------------- phase 1: quality

def _off_harmonic_db(y, f0):
    """Energy away from f0's harmonics against the energy on them. A waveshaper's
    aliasing folds harmonics back to places that aren't multiples of f0."""
    y = y[RATE // 4:]
    sp = np.abs(np.fft.rfft(y * np.hanning(len(y))))
    f = np.fft.rfftfreq(len(y), 1 / RATE)
    on = np.zeros(len(f), bool)
    for k in range(1, int(RATE / 2 / f0) + 1):
        on |= np.abs(f - k * f0) < 12
    return 10 * np.log10(np.sum(sp[~on & (f > 50)] ** 2) / np.sum(sp[on] ** 2))


def test_distortion_crunch_is_harmonics_not_aliasing():
    """tanh at the mic's rate folded harmonics past Nyquist back down (-29 dB of fizz
    at full drive); bent at 4x the rate they're cut off on the way back."""
    f0 = 1037.0        # not a divisor of Nyquist: folded harmonics land off the grid
    e = REGISTRY["distortion"](RATE, {"drive": 36, "tone": 12000, "level": 0.5})
    y = run_blocks(e, sine(f0, 1.5), 480)
    assert _off_harmonic_db(y, f0) < -55
    plain = np.tanh(sine(f0, 1.5) * 10 ** (36 / 20)) * 0.5
    assert _off_harmonic_db(plain, f0) > -35


def _level_db(y, a, b):
    return 20 * np.log10(np.max(np.abs(y[a:b])) + 1e-9)


def test_compressor_attack_and_release_follow_the_sliders():
    """-30 dB, then -6 dB for half a second, then -30 again: a snappy attack has the
    loud part squashed within 20 ms, a soft one hasn't; a quick release lets the
    quiet part back up within 50 ms, a slow one holds it down."""
    q, loud = 10 ** (-30 / 20), 0.5
    x = np.concatenate([sine(300, 0.5, amp=q), sine(300, 0.5, amp=loud), sine(300, 0.5, amp=q)])
    s = RATE // 2
    def run(attack, release):
        e = REGISTRY["compressor"](RATE, {"threshold": -20, "ratio": 4, "boost": 0,
                                         "attack": attack, "release": release})
        return run_blocks(e, x, 480)
    snappy, soft = run(0.5, 20), run(50, 1000)
    assert _level_db(snappy, s + 960, s + 1056) < -15        # squashed by 20 ms
    assert _level_db(soft, s + 960, s + 1056) > -10          # still mostly loud at 20 ms
    assert abs(_level_db(soft, s + 19200, s + 19296) + 16.5) < 1   # both settle to -16.5
    assert _level_db(snappy, 2 * s + 2400, 2 * s + 2496) > -31      # back up in 50 ms
    assert _level_db(soft, 2 * s + 2400, 2 * s + 2496) < -34        # still held down


def _vowel_then_s():
    """A buzzy vowel, a 150 ms "sss" (noise in 5-9 kHz), the vowel again."""
    from soundboard.audio.dsp import butter, sosfilt
    t = np.arange(int(RATE * 0.4)) / RATE
    vowel = sum(np.sin(2 * np.pi * 150 * k * t) / k for k in range(1, 20)) * 0.08
    noise = np.random.default_rng(0).standard_normal(int(RATE * 0.15))
    ess = sosfilt(butter(4, [5000, 9000], btype="band", fs=RATE), noise) * 0.6
    return np.concatenate([vowel, ess, vowel]).astype(np.float32)


def _rms_db(y, a, b):
    return 20 * np.log10(np.sqrt(np.mean(y[a:b] ** 2)) + 1e-9)


@pytest.mark.parametrize("amount, cut", [(0, 0.5), (0.5, 5), (1, 5)])
def test_studio_polish_turns_down_an_s_not_the_vowel(amount, cut):
    x = _vowel_then_s()
    e = REGISTRY["polish"](RATE, {"deess": amount, "warmth": 0, "ceiling": 0})
    y = run_blocks(e, x, 480)
    d = int(e.latency() * RATE)
    vowel = _rms_db(y, RATE // 10 + d, RATE // 4 + d) - _rms_db(x, RATE // 10, RATE // 4)
    a, b = int(RATE * 0.42), int(RATE * 0.53)
    ess = _rms_db(y, a + d, b + d) - _rms_db(x, a, b)
    assert abs(vowel) < 0.5
    if amount:
        assert ess < -cut
    else:
        assert abs(ess) < cut


@pytest.mark.parametrize("ceiling", [-1, -6])
def test_studio_polish_limiter_never_passes_the_ceiling(ceiling):
    """A burst 14 dB over: the output peaks exactly at the ceiling, with no clipped
    corners (the gain is down before the burst arrives), and the quiet parts stay put."""
    x = sine(200, 1.0, amp=0.2)
    x[RATE // 2:RATE // 2 + 2400] *= 5
    e = REGISTRY["polish"](RATE, {"deess": 0, "warmth": 0, "ceiling": ceiling})
    y = run_blocks(e, x, 480)
    assert 20 * np.log10(np.max(np.abs(y))) <= ceiling + 0.01
    assert 20 * np.log10(np.max(np.abs(y))) > ceiling - 0.3
    assert abs(_level_db(y, RATE // 8, RATE // 4) - 20 * np.log10(0.2)) < 0.05
    # a limiter that clipped would leave sharp corners on the loud cycles
    burst = y[RATE // 2 + 480:RATE // 2 + 2400]
    assert np.abs(np.diff(burst, 2)).max() < 0.02


def test_studio_polish_warmth_is_level_neutral_and_adds_harmonics():
    x = sine(220, 1.0, amp=0.3)
    def spec(w):
        e = REGISTRY["polish"](RATE, {"deess": 0, "warmth": w, "ceiling": 0})
        y = run_blocks(e, x, 480)[RATE // 4:]
        sp = np.abs(np.fft.rfft(y * np.hanning(len(y))))
        f = np.fft.rfftfreq(len(y), 1 / RATE)
        return y, sp[np.abs(f - 220) < 5].max(), sp[np.abs(f - 660) < 5].max()
    y0, h1, h3 = spec(0)
    assert abs(_rms_db(y0, 0, len(y0)) - _rms_db(x, RATE // 4, len(x))) < 0.05
    assert 20 * np.log10(h3 / h1) < -80
    y1, h1, h3 = spec(1)
    assert abs(_rms_db(y1, 0, len(y1)) - _rms_db(x, RATE // 4, len(x))) < 1.5
    assert 20 * np.log10(h3 / h1) > -30


def test_studio_polish_runs_last_and_reports_its_delay():
    chain = VoiceChain()
    chain.configure(spec_for(reverb={}, polish={}, compressor={}))
    x = np.repeat(sine(150, 0.1)[:, None], 2, 1)
    chain.process(x[:480], RATE)
    assert [e.type for e in chain._effects] == ["compressor", "reverb", "polish"]
    assert 0.001 < REGISTRY["polish"](RATE).latency() < 0.003


def _monk_pitch(y: np.ndarray, secs: float = 0.5) -> float:
    """The lowest strong harmonic of the last `secs`: his note."""
    seg = y[-int(RATE * secs):].astype(np.float64)
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), 8 * len(seg)))
    fr = np.fft.rfftfreq(8 * len(seg), 1 / RATE)
    band = (fr > 60) & (fr < 400)
    peaks = np.flatnonzero(band & (spec > 0.3 * spec[band].max()))
    return float(fr[peaks[0]])


def _monk(x, **cfg):
    e = REGISTRY["monk"](RATE, {"words": 0, **cfg})
    return run_blocks(e, x, 480)


def test_singing_monk_sings_his_own_low_note():
    """Talk at any steady pitch and he sings his note (C3), with a voice of his own:
    a full set of harmonics, not your sine."""
    for hz in (110, 220):
        t = np.arange(RATE * 2) / RATE
        x = (0.1 * np.sin(2 * np.pi * hz * t)).astype(np.float32)
        y = _monk(x)
        assert np.all(np.isfinite(y)) and np.max(np.abs(y)) < 1.5
        assert abs(_monk_pitch(y) / 130.81 - 1) < 0.03
        spec = np.abs(np.fft.rfft(y[-RATE // 2:]))
        fr = np.fft.rfftfreq(RATE // 2, 1 / RATE)
        assert spec[(fr > 600) & (fr < 1500)].max() > 0.1 * spec.max()   # his "a"


def test_singing_monk_pitch_slider_moves_his_note():
    t = np.arange(RATE * 2) / RATE
    x = (0.1 * np.sin(2 * np.pi * 150 * t)).astype(np.float32)
    assert abs(_monk_pitch(_monk(x, note=-5)) / (130.81 * 2 ** (-5 / 12)) - 1) < 0.03


def test_singing_monk_follows_your_tune_on_his_scale():
    """Go up and he goes up too, landing on a note of his five-note scale (held
    long, he slowly takes it as your usual pitch again: talking isn't held notes)."""
    t = np.arange(int(RATE * 2.38)) / RATE
    hz = np.where(t < 2, 150.0, 150 * 2 ** (7 / 12))
    x = (0.1 * np.sin(2 * np.pi * np.cumsum(hz) / RATE)).astype(np.float32)
    e = REGISTRY["monk"](RATE, {"words": 0, "follow": 1})
    y = run_blocks(e, x, 480)
    assert np.max(np.abs(y[-RATE // 10:])) > 0.01           # still singing
    steps = 12 * np.log2(e.f / 130.81)
    assert steps > 2 and min(abs(steps - s) for s in (3, 5, 7, 10, 12)) < 0.3


def test_singing_monk_is_quiet_when_you_are():
    x = np.zeros(RATE, np.float32)
    assert np.max(np.abs(_monk(x))) == 0
    t = np.arange(RATE) / RATE
    talk = (0.1 * np.sin(2 * np.pi * 150 * t)).astype(np.float32)
    y = _monk(np.concatenate([talk, np.zeros(RATE, np.float32)]))
    assert np.max(np.abs(y[-RATE // 2:])) < 1e-3       # he stops when you do


def test_singing_monk_any_block_size_and_rate():
    for rate in (16000, 44100, 48000, 96000):
        t = np.arange(rate) / rate
        x = (0.1 * np.sin(2 * np.pi * 150 * t)).astype(np.float32)
        for block in (64, 441, 2048):
            e = REGISTRY["monk"](rate)
            y = np.concatenate([e.run(x[i:i + block], rate) for i in range(0, len(x), block)]
                               + [e.run(x[:0], rate)])
            assert len(y) == len(x) and np.all(np.isfinite(y)) and np.max(np.abs(y)) < 2


# ---------------------------------------------------------------- phase 2: the room

def _impulse_response(**cfg):
    e = REGISTRY["reverb"](RATE, {"tone": 5000, "mix": 1.0, **cfg})
    x = np.zeros(RATE, np.float32)
    x[0] = 1.0
    return run_blocks(e, x, 480)


def test_reverb_predelay_holds_the_room_back():
    """With 60 ms of pre-delay nothing but the dry voice comes out for 60 ms."""
    ir = _impulse_response(predelay=60, size=0.5)
    dry_share = 1 - 0.6 * 1.0
    gap = int(RATE * 0.06)
    assert abs(ir[0] - dry_share) < 1e-3
    assert np.max(np.abs(ir[1:gap - 48])) < 1e-4
    assert np.max(np.abs(ir[gap:gap + RATE // 20])) > 0.05


def test_reverb_has_early_reflections_before_the_tail():
    """The first bounces land within 60 ms, well before the tail has built up."""
    ir = _impulse_response(predelay=0, size=0.5)
    early = ir[int(RATE * 0.004):int(RATE * 0.062)]
    assert np.max(np.abs(early)) > 0.1
    slots = np.abs(early[:len(early) // 48 * 48]).reshape(-1, 48).max(1)
    assert np.mean(slots > 1e-3) > 0.5


def test_reverb_old_settings_keep_their_tail():
    """Size, Brightness and Mix mean what they did: the decay at Size 0.5 is still
    about a second, and highs die faster than lows."""
    from soundboard.audio.dsp import butter, sosfilt
    ir = _impulse_response(predelay=0, size=0.5)

    def t60(lo, hi):
        y = sosfilt(butter(4, [lo, hi], btype="band", fs=RATE), ir[:RATE])
        e = np.cumsum(y[::-1] ** 2)[::-1]
        db = 10 * np.log10(e / e[0] + 1e-12)
        t = np.arange(len(db)) / RATE
        m = (db < -5) & (db > -25)
        k, _ = np.polyfit(t[m], db[m], 1)
        return -60 / k
    assert 0.8 < t60(500, 2000) < 1.6
    assert t60(2000, 8000) < t60(500, 2000)


# ---------------------------------------------------------------- phase 3: new blocks

def _peak_hz(y, lo, hi):
    y = y[RATE // 4:]
    sp = np.abs(np.fft.rfft(y * np.hanning(len(y))))
    f = np.fft.rfftfreq(len(y), 1 / RATE)
    m = (f > lo) & (f < hi)
    return f[m][np.argmax(sp[m])]


def test_ring_modulator_splits_a_tone_into_sidebands():
    """A 1 kHz tone through a 100 Hz ring modulator comes out at 900 and 1100 Hz,
    and nothing at 1 kHz: the voice's own pitch is gone."""
    y = run_blocks(REGISTRY["ringmod"](RATE, {"freq": 100, "mix": 1}), sine(1000, 1.0), 480)
    seg = y[RATE // 4:]
    sp = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    f = np.fft.rfftfreq(len(seg), 1 / RATE)
    at = lambda hz: sp[np.abs(f - hz) < 4].max()   # noqa: E731
    assert at(900) > 100 * at(1000) and at(1100) > 100 * at(1000)


def test_harmony_adds_voices_at_the_intervals():
    y = run_blocks(REGISTRY["harmony"](RATE, {"first": 4, "second": 7, "level": 1}),
                   sine(200, 2.0), 480)
    for st in (4, 7):
        want = 200 * 2 ** (st / 12)
        assert abs(_peak_hz(y, want * 0.95, want * 1.05) - want) < want * 0.03
    assert abs(_peak_hz(y, 150, 250) - 200) < 5          # your own voice is still there


def test_wobble_vibrato_moves_the_pitch_and_tremolo_the_volume():
    x = sine(1000, 2.0)
    vib = run_blocks(REGISTRY["wobble"](RATE, {"rate": 2, "vibrato": 8, "tremolo": 0}), x, 480)
    # 8 ms of sway at 2 Hz: the pitch swings about +-5 % (measured in 50 ms slices)
    hz = [_peak_hz(np.concatenate([np.zeros(RATE // 4, np.float32), vib[i:i + 2400]]), 900, 1100)
          for i in range(RATE // 2, len(vib) - 2400, 2400)]
    assert max(hz) - min(hz) > 40
    trem = run_blocks(REGISTRY["wobble"](RATE, {"rate": 2, "vibrato": 0, "tremolo": 1}), x, 480)
    env = np.abs(trem[RATE // 2:]).reshape(-1, 480).max(1)
    assert env.min() < 0.05 and env.max() > 0.25


def test_flanger_feedback_is_stable_and_sweeps():
    x = sine(300, 2.0) + sine(2300, 2.0, amp=0.1)
    y = run_blocks(REGISTRY["flanger"](RATE, {"rate": 1, "depth": 5, "feedback": 0.9, "mix": 1}),
                   x.astype(np.float32), 480)
    assert np.all(np.isfinite(y)) and np.max(np.abs(y)) < 4
    # the comb notches move: the 2.3 kHz partial's level changes through the sweep
    lvl = [np.abs(np.fft.rfft(y[i:i + 2400] * np.hanning(2400)))[int(2300 * 2400 / RATE)]
           for i in range(RATE // 2, len(y) - 2400, 1200)]
    assert max(lvl) > 3 * min(lvl)


@pytest.mark.parametrize("name", ["Singing monk", "Dalek", "Haunted radio", "Underwater"])
def test_new_voices_keep_speech_about_as_loud(name):
    x = _vowel(secs=1.0)
    chain = VoiceChain()
    chain.configure(spec_for(**voicefx.PRESETS[name]))
    y = np.concatenate([chain.process(np.repeat(x[i:i + 480, None], 2, 1), SR)[:, 0]
                        for i in range(0, len(x) - 479, 480)])
    assert np.all(np.isfinite(y))
    loss = np.sqrt(np.mean(y[SR // 2:] ** 2)) / np.sqrt(np.mean(x[SR // 2:len(y)] ** 2))
    assert 0.25 < loss < 4.0, loss


def test_every_preset_has_a_group_on_the_voice_tab():
    from soundboard.ui.voice.voicefxpanel import VOICE_GROUPS
    grouped = [n for _k, _t, names in VOICE_GROUPS for n in names]
    assert sorted(grouped) == sorted(voicefx.PRESETS)   # each in one group, none left over


def _speech_like(secs=2.0, f0=120.0):
    """A voice-like test line: a buzzy vowel whose pitch glides, with pauses."""
    t = np.arange(int(SR * secs)) / SR
    f = f0 * (1 + 0.15 * np.sin(2 * np.pi * 0.7 * t))
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = sum(np.sin(k * ph) / k for k in range(1, 30))
    x *= (np.sin(2 * np.pi * 1.5 * t) > -0.3)       # words and gaps
    return (0.3 * x / np.max(np.abs(x))).astype(np.float32)


@pytest.mark.parametrize("name", ["Drunk", "Choir", "Goblin", "Fairy", "Zombie", "Evil twin",
                                  "Giant", "Mecha", "Ship computer", "Pilot",
                                  "Drive-thru speaker", "Old film", "Cathedral",
                                  "Nightcore", "Slowed + reverb", "Cat", "Dog", "Glitch",
                                  "8-bit", "Virtual idol", "80s robot"])
def test_new_voices_keep_the_loudness_of_your_voice(name):
    x = _speech_like()
    ch = VoiceChain()
    ch.configure(spec_for(**voicefx.PRESETS[name]))
    y = np.concatenate([ch.process(np.stack([x[i:i + 480]] * 2, 1), SR)[:, 0]
                        for i in range(0, len(x), 480)])
    db = 20 * np.log10(np.sqrt(np.mean(y ** 2)) / np.sqrt(np.mean(x ** 2)))
    assert -7 < db < 7, f"{name}: {db:+.1f} dB"     # a voice, not a whisper or a blast
    assert np.max(np.abs(y)) < 2.0


def test_wobble_goes_deep_enough_to_sway_a_semitone():
    # Drunk's slow sway: a delay swinging 35 ms at 0.7 Hz moves the pitch about
    # +-7.7%, more than a semitone (6%); the old 10 ms top was a few cents' worth
    e = REGISTRY["wobble"](SR, {"rate": 0.7, "vibrato": 35, "tremolo": 0})
    t = np.arange(SR * 3) / SR
    x = np.sin(2 * np.pi * 200 * t).astype(np.float32)
    y = np.concatenate([e.run(x[i:i + 480], SR) for i in range(0, len(x), 480)])
    z = np.where(np.diff(np.signbit(y[SR // 2:]).astype(np.int8)) != 0)[0]
    per = np.diff(z[::2]) / SR
    f = 1 / per
    assert f.max() / f.min() > 2 ** (2 / 12)            # at least two semitones top to bottom


def test_robot_buzz_from_its_table_is_the_summed_saw():
    """The buzz is read from one cycle made ahead, no longer summed from its 75 sines
    every block: what comes out is the same band-limited saw (within -90 dB)."""
    for freq, follow in ((100, 0), (40, 0), (400, 0), (110, 1)):
        fast = voicefx.REGISTRY["robot"](SR, {"freq": freq, "noise": 0, "follow": follow})
        fast.f = float(freq)
        got = np.concatenate([fast._carrier(480, SR) for _ in range(20)])
        n = np.arange(1, len(got) + 1)
        ph = 2 * np.pi * freq / SR * n
        k = np.arange(1, int(min(fast.HI_HZ, SR * 0.42) / freq) + 1)[:, None]
        want = (np.sin(k * ph) / k).sum(0) * (2 / np.pi)
        assert np.max(np.abs(got - want)) < 3e-4 * np.max(np.abs(want))


@pytest.fixture
def light_off():
    yield
    voicefx.set_light(False)


def test_use_less_cpu_reaches_every_effect_on_the_next_block(light_off):
    """Use less CPU (lite mode's): the chain tells its effects on the next mic block,
    and back again; the robot then has half the bands, the reverb half its lines."""
    chain = VoiceChain()
    chain.configure(spec_for(robot={"freq": 100}, reverb={"mix": 0.3}))
    x = np.stack([_vowel(secs=0.2)] * 2, 1)[:480]
    chain.process(x, SR)
    eff = {e.type: e for e in chain._effects}
    assert eff["robot"].bands == 16 and eff["reverb"]._in_use() == (8, 4)
    voicefx.set_light(True)
    y = chain.process(x, SR)
    assert all(e.light for e in chain._effects)
    assert eff["robot"].bands == 8 and eff["reverb"]._in_use() == (4, 2)
    assert np.all(np.isfinite(y)) and not chain.errors
    voicefx.set_light(False)
    chain.process(x, SR)
    assert eff["robot"].bands == 16 and not any(e.light for e in chain._effects)


def test_an_add_on_effect_without_the_switch_keeps_running(light_off):
    class Old:   # an add-on's effect written before Use less CPU (not an Effect)
        type, name, params = "old", "Old", ()

        def __init__(self, rate, values=None):
            self.rate = rate

        def run(self, x, rate):
            return x * 0.5

        def latency(self):
            return 0.0
    voicefx.REGISTRY["old"] = Old   # pyright: ignore[reportArgumentType]
    try:
        chain = VoiceChain()
        chain.configure(spec_for(old={}))
        voicefx.set_light(True)
        y = chain.process(np.full((480, 2), 0.2, np.float32), SR)
        assert not chain.errors and np.allclose(y, 0.1)
    finally:
        del voicefx.REGISTRY["old"]


def test_use_less_cpu_keeps_every_voice_about_as_loud(light_off):
    x = _vowel(secs=1.5)
    for name in ("Robot", "Talkbox", "Cathedral", "Cave", "Demon", "Mecha"):
        out = []
        for light in (False, True):
            voicefx.set_light(light)
            chain = VoiceChain()
            chain.configure({"enabled": True, "effects": {
                **{t: {"on": True, **c} for t, c in voicefx.PRESETS[name].items()}}})
            y = np.concatenate([chain.process(np.stack([x[i:i + 480]] * 2, 1), SR)[:, 0]
                                for i in range(0, len(x) - 479, 480)])
            assert np.all(np.isfinite(y))
            out.append(20 * np.log10(np.sqrt(np.mean(y[SR // 2:] ** 2)) + 1e-9))
        assert abs(out[0] - out[1]) < 2.5, name


# ------------------------------------------------- cat, dog, glitch, ear destroyer

def _f0(x, rate=RATE):
    """The pitch of a short stretch: its autocorrelation's peak, 70-1200 Hz."""
    x = x - x.mean()
    r = np.correlate(x, x, "full")[len(x) - 1:]
    lo, hi = rate // 1200, rate // 70
    return rate / (lo + int(np.argmax(r[lo:hi])))


def _through(name_or_spec, x, block=480):
    ch = VoiceChain()
    ch.configure(spec_for(**voicefx.PRESETS[name_or_spec]) if isinstance(name_or_spec, str)
                 else name_or_spec)
    return np.concatenate([ch.process(np.stack([x[i:i + block]] * 2, 1), RATE)[:, 0]
                           for i in range(0, len(x) - block + 1, block)])


def test_nightcore_is_a_squeaker_far_above_chipmunk():
    # Chipmunk's 8 semitones were "not actually high pitch": Nightcore goes 19 up, so
    # even a deep voice comes out a chipmunk (the pitch slider now reaches +24)
    assert REGISTRY["pitch"].params[0].hi == 24
    x = sine(150, 2.0)
    hi = {n: _f0(_through(n, x)[RATE:RATE + 4096]) for n in ("Chipmunk", "Nightcore")}
    assert abs(hi["Nightcore"] - 150 * 2 ** (19 / 12)) < 25, hi
    assert hi["Nightcore"] > hi["Chipmunk"] * 1.5


# (the dog's period includes its growl, an octave under the bark)
@pytest.mark.parametrize("kind, lo, hi", [("cat", 400, 900), ("dog", 130, 450)])
def test_animals_answer_a_voice_with_their_own_pitch(kind, lo, hi):
    """Your voice is only listened to: what comes out is the animal's call, at its
    own pitch (a cat far above a 120 Hz voice), and nothing while you're quiet."""
    x = _speech_like(3.0, f0=120)
    e = REGISTRY[kind](RATE, defaults(kind))
    e.rng = np.random.default_rng(0)                # (the dog's rough pitch: the same each run)
    y = run_blocks(e, x, 480)
    assert np.all(np.isfinite(y))
    talk = np.abs(x) > 0.01
    assert np.sqrt(np.mean(y[talk] ** 2)) > 0.02
    # its strongest harmonic while calling, well away from the 120 Hz voice
    loud = y[RATE // 2:RATE // 2 + 4096]
    if np.sqrt(np.mean(loud ** 2)) < 0.01:          # (that stretch was a gap)
        loud = y[RATE:RATE + 4096]
    assert lo < _f0(loud) < hi
    s = run_blocks(REGISTRY[kind](RATE, defaults(kind)), np.zeros(RATE, np.float32), 480)
    assert np.max(np.abs(s)) == 0.0


@pytest.mark.parametrize("kind", ["cat", "dog"])
def test_animals_never_blast_on_a_loud_steady_input(kind):
    # a hum or a held tone at -3 dBFS: the call follows you only up to a shout
    x = np.full(RATE, 0.7, np.float32) * np.sign(sine(200, 1.0))
    y = run_blocks(REGISTRY[kind](RATE, defaults(kind)), x, 480)
    assert np.max(np.abs(y)) < 1.0


def test_dog_barks_once_a_syllable():
    """Three short syllables, three barks; each one gone again before the next."""
    x = np.zeros(int(RATE * 1.8), np.float32)
    for k in range(3):
        a = int(RATE * (0.1 + 0.6 * k))
        x[a:a + int(RATE * 0.2)] = sine(140, 0.2)
    e = REGISTRY["dog"](RATE, defaults("dog"))
    e.rng = np.random.default_rng(0)
    y = run_blocks(e, x, 480)
    env = np.sqrt((y[:len(y) // 480 * 480].reshape(-1, 480) ** 2).mean(1))
    on = env > 0.1 * env.max()
    assert int(np.sum(on[1:] & ~on[:-1])) + int(on[0]) == 3


def test_glitch_at_zero_is_a_passthrough_and_keeps_the_length():
    x = _speech_like(2.0)
    off = REGISTRY["glitch"](RATE, {"amount": 0, "length": 80})
    assert np.array_equal(run_blocks(off, x, 480), x)
    on = REGISTRY["glitch"](RATE, {"amount": 1, "length": 80})
    y = run_blocks(on, x, 480)
    assert len(y) == len(x) and np.all(np.isfinite(y))
    assert np.max(np.abs(y - x)) > 0.05                   # it did glitch
    assert np.max(np.abs(y)) <= np.max(np.abs(x)) * 1.01  # replays you, never louder


def test_glitch_only_glitches_while_you_talk():
    quiet = (np.random.default_rng(0).standard_normal(RATE * 3) * 1e-4).astype(np.float32)
    e = REGISTRY["glitch"](RATE, {"amount": 1, "length": 80})
    run_blocks(e, quiet, 480)
    assert e.slice is None and e.total == 0


def test_distortion_talk_gate_mutes_the_hiss_between_words():
    """Driven hard, a mic's hiss comes out as loud as the words; "Only while I talk"
    keeps the crunch to the words."""
    rng = np.random.default_rng(1)
    hiss = (rng.standard_normal(RATE * 3) * 0.001).astype(np.float32)
    x = hiss.copy()
    x[RATE:RATE + RATE // 2] += sine(150, 0.5)
    gap = slice(int(RATE * 2.2), RATE * 3)                 # well after the word
    word = slice(RATE + 4800, RATE + RATE // 2 - 4800)
    out = {}
    for talk in (0, 1):
        e = REGISTRY["distortion"](RATE, {"drive": 36, "tone": 7000, "level": 1,
                                          "talk": talk})
        out[talk] = run_blocks(e, x, 480)
    rms = lambda y, s: float(np.sqrt(np.mean(y[s] ** 2)))  # noqa: E731
    assert rms(out[0], gap) > 0.02                          # the hiss, 26 dB up
    assert rms(out[1], gap) < 0.001                         # gated
    assert abs(rms(out[1], word) - rms(out[0], word)) < 0.01   # the word as loud as ever


def test_ear_destroyer_is_loud_but_never_past_full_scale():
    x = _speech_like(3.0)
    y = _through("Ear destroyer", x)
    db = 20 * np.log10(np.sqrt(np.mean(y ** 2)) / np.sqrt(np.mean(x ** 2)))
    assert db > 9, db                                       # far louder than you
    assert np.max(np.abs(y)) <= 1.0


# ------------------------------------------------- the recorded meows and barks

def _calls(monkeypatch, kind, n=3, secs=0.8, hz=600.0):
    """Stand-in recordings for `kind`: n tones, each `secs` long, at CALL_RMS."""
    from soundboard.voicefx import critters
    t = np.arange(int(secs * RATE)) / RATE
    tone = np.sin(2 * np.pi * hz * t).astype(np.float32)
    tone *= np.float32(critters.CALL_RMS / np.sqrt(np.mean(tone ** 2)))
    monkeypatch.setitem(critters._calls, kind, tuple(tone.copy() for _ in range(n)))


def _starts(e, x, block=480):
    """Run x through e; the blocks where a recorded call started."""
    out, starts = [], []
    for i in range(0, len(x) - block + 1, block):
        before = e.played
        out.append(e.run(x[i:i + block], RATE))
        if e.played < before:
            starts.append(i // block)
    return np.concatenate(out), starts


def test_picking_cat_fetches_its_recordings_in_the_background(monkeypatch):
    from soundboard.voicefx import critters
    asked = []
    monkeypatch.setattr(critters, "fetch", asked.append)
    VoiceChain().configure(spec_for(**voicefx.PRESETS["Cat"]))
    VoiceChain().configure({"enabled": False, "effects": {"dog": {"on": True}}})   # off: no
    assert asked == ["cat"]


def test_a_meow_is_held_through_short_syllables(monkeypatch):
    """The meows were "way too quick": a new syllable doesn't cut a meow until it's
    had HOLD_S, and a meow plays to its end even after you stop."""
    _calls(monkeypatch, "cat", secs=0.8)
    x = np.zeros(int(RATE * 2.5), np.float32)
    for k in range(6):                               # six quick syllables, 0.2 s apart
        a = int(RATE * (0.1 + 0.2 * k))
        x[a:a + int(RATE * 0.12)] = sine(130, 0.12)
    e = REGISTRY["cat"](RATE, defaults("cat"))
    y, starts = _starts(e, x)
    gaps = np.diff(starts) * 0.01
    assert len(starts) == 2 and np.all(gaps >= e.HOLD_S), starts
    after = y[int(RATE * 1.4):int(RATE * 1.8)]       # you've stopped: the meow goes on
    assert np.sqrt(np.mean(after ** 2)) > 0.01


def test_dog_barks_each_syllable_with_a_recording(monkeypatch):
    _calls(monkeypatch, "dog", secs=0.3, hz=400)
    x = np.zeros(int(RATE * 1.8), np.float32)
    for k in range(3):
        a = int(RATE * (0.1 + 0.6 * k))
        x[a:a + int(RATE * 0.2)] = sine(140, 0.2)
    e = REGISTRY["dog"](RATE, defaults("dog"))
    y, starts = _starts(e, x)
    assert len(starts) == 3
    assert abs(dominant_hz(y) - 400) < 20             # the recording, not your voice
    assert np.max(np.abs(y)) < 1.0


def test_recorded_calls_follow_your_loudness_and_tune(monkeypatch):
    _calls(monkeypatch, "dog", secs=0.3, hz=400)
    def bark(amp, f0):
        x = np.zeros(int(RATE * 0.6), np.float32)
        x[4800:4800 + 9600] = sine(f0, 0.2, amp=amp)
        e = REGISTRY["dog"](RATE, {"note": 0, "follow": 1, "mix": 1})
        e.home, e.heard = 12 * np.log2(140), 1000      # your usual pitch: 140 Hz
        return _starts(e, x)[0]
    quiet, loud = bark(0.02, 140), bark(0.2, 140)
    assert np.sqrt(np.mean(loud ** 2)) > 4 * np.sqrt(np.mean(quiet ** 2))
    up = bark(0.2, 140 * 2 ** (4 / 12))               # you 4 semitones up: so is the bark
    assert abs(dominant_hz(up) - 400 * 2 ** (4 / 12)) < 25


def test_calls_are_cut_faded_and_levelled():
    from soundboard.voicefx import critters
    rng = np.random.default_rng(0)
    x = (rng.standard_normal(critters.RATE * 2) * 0.5).astype(np.float32)
    got = critters._cut(x, ((0.1, 0.5), (1.0, 1.001), (1.2, 1.9)))
    assert len(got) == 2                               # the too-short one is dropped
    for c in got:
        assert abs(np.sqrt(np.mean(c ** 2)) - critters.CALL_RMS) < 0.02
        assert c[0] == 0 and abs(c[-1]) < 1e-3 and np.max(np.abs(c)) <= 0.95


def test_a_changed_download_is_never_used(monkeypatch, tmp_path):
    """Each recording is pinned to its SHA-256: a file that changed upstream (or a
    bad mirror) is thrown away, and the voice keeps its made-up call."""
    import io
    from soundboard.online import net
    from soundboard.voicefx import critters

    class Reply(io.BytesIO):
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False
    seen = []

    def urlopen(req, *a, feature=None, **k):
        seen.append((req.full_url, feature))
        return Reply(b"not the cat")
    monkeypatch.setattr(net, "urlopen", urlopen)
    monkeypatch.setattr(critters, "cache_dir", lambda: tmp_path)
    critters._load("cat")
    assert critters.calls("cat") is None
    assert len(seen) == len(critters.SOURCES["cat"])
    assert all(f == "voices" and u.startswith("https://") for u, f in seen)
    assert list(tmp_path.iterdir()) == []              # nothing kept


def test_every_effect_icon_is_one_the_app_can_draw():
    # an unknown name raised inside Qt's icon engine as the card was painted
    from soundboard.ui.kit.iconshapes import SHAPES
    from soundboard.ui.voice.effectrow import FX_ICONS
    assert set(FX_ICONS.values()) <= set(SHAPES)


def test_bit_crusher_rounds_to_fewer_steps_and_holds_samples():
    x = sine(440, 0.5, amp=0.9)
    y = run_blocks(REGISTRY["bitcrush"](RATE, {"bits": 4, "rate": 6000, "mix": 1}), x, 480)
    # 4 bits: every sample sits on one of the 2^4 steps of -1..1
    assert np.allclose(y / 2 ** -3, np.round(y / 2 ** -3), atol=1e-4)
    assert len(np.unique(y)) <= 17
    # 6 kHz at 48 kHz: each sample is held for 8
    changes = np.count_nonzero(np.diff(y))
    assert changes <= len(y) / 8 + 2


def test_bit_crusher_rate_takes_away_the_top_end():
    """Sample-and-hold at a low rate: a high tone folds down below the new Nyquist."""
    x = sine(5000, 0.5)
    y = run_blocks(REGISTRY["bitcrush"](RATE, {"bits": 16, "rate": 4000, "mix": 1}), x, 480)
    assert dominant_hz(y) < 2000
    clean = run_blocks(REGISTRY["bitcrush"](RATE, {"bits": 16, "rate": 24000, "mix": 1}),
                       sine(1000, 0.5), 480)
    assert abs(dominant_hz(clean) - 1000) < 20


def test_bit_crusher_does_not_depend_on_the_block_size_at_any_rate():
    x = (sine(220, 0.6) + sine(1300, 0.6, amp=0.1)).astype(np.float32)
    for hz in (1000, 7000, 7300, 11025, 24000):
        vals = {"bits": 6, "rate": hz, "mix": 1}
        a = run_blocks(REGISTRY["bitcrush"](RATE, vals), x, 480)
        b = run_blocks(REGISTRY["bitcrush"](RATE, vals), x, 37)
        assert np.array_equal(a, b), hz


def test_bit_crusher_adds_no_delay_and_mix_zero_is_dry():
    x = sine(300, 0.2)
    e = REGISTRY["bitcrush"](RATE, {"mix": 0})
    assert e.latency() == 0
    assert np.allclose(run_blocks(e, x, 480), x, atol=1e-6)


def test_8bit_voice_stays_under_full_scale():
    y = _through("8-bit", _speech_like())
    assert np.all(np.isfinite(y)) and np.max(np.abs(y)) < 1.0
