"""Per-sound effects (soundfx), their cache in the library, and the engine's live
speed / pitch. Audio is synthesised; pitch is checked by finding the strongest
frequency, speed by the length or the read position."""
import numpy as np
import pytest
import soundfile as sf

from soundboard import library, soundfx
from soundboard.engine import SR, Engine
from soundboard.library import SoundMeta


def sine(hz=440.0, seconds=1.0, amp=0.5):
    t = np.arange(int(seconds * SR)) / SR
    return np.stack([np.sin(2 * np.pi * hz * t)] * 2, 1).astype(np.float32) * amp


def peak_hz(x: np.ndarray) -> float:
    """Strongest frequency of the middle half (skips the edges' fades)."""
    m = x[len(x) // 4: 3 * len(x) // 4, 0].astype(np.float64)
    spec = np.abs(np.fft.rfft(m * np.hanning(len(m))))
    return float(np.argmax(spec) * SR / len(m))


def rms(x):
    return float(np.sqrt(np.mean(np.asarray(x, np.float64) ** 2)))


# ---------------------------------------------------------------- settings

def test_clean_fills_defaults_clamps_and_drops_junk():
    f = soundfx.clean({"speed": 99, "pitch": "x", "gain_db": -1000, "eq": [50] * 7,
                       "effects": {"echo": {"on": True}, "bad": 3}, "nonsense": 1})
    assert f["speed"] == soundfx.SPEED_RANGE[1]
    assert f["pitch"] == 0.0                                  # unparseable -> default
    assert f["gain_db"] == soundfx.GAIN_RANGE[0]
    assert all(g == soundfx.eq.MAX_DB for g in f["eq"])
    assert f["effects"] == {"echo": {"on": True}} and "nonsense" not in f
    assert soundfx.clean(None) == soundfx.neutral()
    assert soundfx.clean({"eq": [1, 2]})["eq"] == [0.0] * 7   # wrong length -> flat


def test_neutral_key_and_summary():
    assert soundfx.is_neutral({}) and soundfx.is_neutral(None)
    assert soundfx.key({}) == "" and soundfx.summary({}) == ""
    # an effect that is switched off, or unknown, changes nothing
    assert soundfx.is_neutral({"effects": {"echo": {"on": False}, "nope": {"on": True}}})
    a, b = {"speed": 1.5}, {"speed": 1.5, "pitch": 0}
    assert soundfx.key(a) == soundfx.key(b) != ""             # same settings, same key
    assert soundfx.key(a) != soundfx.key({"speed": 1.25})
    s = soundfx.summary({"speed": 0.5, "pitch": -3, "gain_db": 12, "reverse": True,
                         "effects": {"reverb": {"on": True}}})
    assert "0.5x" in s and "-3 st" in s and "+12 dB" in s and "Reverb" in s and "reversed" in s


def test_every_preset_is_valid_and_renders():
    x = sine(seconds=0.4)
    assert soundfx.is_neutral(soundfx.PRESETS["None (original)"])
    for name, fx in soundfx.PRESETS.items():
        assert soundfx.clean(fx) == fx, name                   # stored exactly as cleaned
        y = soundfx.render(x, fx)
        assert y.dtype == np.float32 and y.ndim == 2 and y.shape[1] == 2, name
        assert len(y) > 0 and np.all(np.isfinite(y)) and np.abs(y).max() <= 1.0, name


# ---------------------------------------------------------------- speed / pitch

@pytest.mark.parametrize("factor", [0.5, 0.8, 1.25, 2.0])
def test_stretch_changes_length_not_pitch(factor):
    x = sine(440, 1.0)
    y = soundfx.stretch(x, factor)
    assert len(y) == int(round(len(x) * factor))
    assert abs(peak_hz(y) - 440) < 8
    assert 0.6 < rms(y) / rms(x) < 1.4                          # no big level change


def test_stretch_by_one_is_a_passthrough():
    x = sine(seconds=0.1)
    assert np.array_equal(soundfx.stretch(x, 1.0), x)
    assert len(soundfx.stretch(x[:0], 2.0)) == 0


@pytest.mark.parametrize("speed, semis, tape, hz, length", [
    (1.0, 12, False, 880, 1.0),      # an octave up, same length
    (1.0, -12, False, 220, 1.0),     # an octave down
    (2.0, 0, False, 440, 0.5),       # twice as fast, same pitch
    (0.5, 0, False, 440, 2.0),
    (2.0, 0, True, 880, 0.5),        # tape: faster is also higher
    (0.8, 0, True, 352, 1.25),       # slowed (the "slowed + reverb" speed)
    (2.0, -12, True, 440, 0.5),      # tape up an octave, pitched back down
])
def test_speed_and_pitch_are_independent(speed, semis, tape, hz, length):
    x = sine(440, 1.0)
    y = soundfx.change_speed_pitch(x, speed, semis, tape)
    assert abs(len(y) / SR - length) < 0.01
    assert abs(peak_hz(y) - hz) < hz * 0.02


def test_render_gain_eq_reverse_and_int16_input():
    x = sine(440, 0.5, amp=0.1)
    i16 = library.to_int16(x)
    y = soundfx.render(i16, {"gain_db": 12})
    assert abs(rms(y) / rms(x) - 10 ** (12 / 20)) < 0.05       # int16 in, scaled correctly
    loud = soundfx.render(x, {"gain_db": 36})
    assert np.abs(loud).max() <= 1.0                            # clips, never beyond full scale
    ramp = np.linspace(0, 0.5, 1000, dtype=np.float32)
    r = soundfx.render(np.stack([ramp, ramp], 1), {"reverse": True})
    assert np.allclose(r[:, 0], ramp[::-1], atol=1e-6)
    low = soundfx.render(sine(60, 0.5), {"eq": [12, 0, 0, 0, 0, 0, 0]})
    assert rms(low) > rms(sine(60, 0.5)) * 2                   # the bass shelf boosts 60 Hz
    assert np.array_equal(soundfx.render(x, {}), x)             # neutral: untouched


def test_render_runs_voice_effects_in_stereo_with_a_tail():
    x = np.zeros((SR // 2, 2), np.float32)
    x[:2400, 0] = 0.5                                            # a burst, left only
    y = soundfx.render(x, {"effects": {"echo": {"on": True, "delay": 200, "feedback": 0.5,
                                                "mix": 0.8}}})
    assert len(y) > len(x) - 1                                   # never shorter than the sound
    assert np.abs(y[int(0.2 * SR): int(0.25 * SR), 0]).max() > 0.1   # the echo is there
    assert np.abs(y[:, 1]).max() < 1e-6                          # channels stay separate


def test_a_broken_module_effect_is_skipped_not_fatal(monkeypatch):
    from soundboard import voicefx

    class Broken(voicefx.Effect):
        type, name = "test.broken", "Broken"

        def run(self, x, rate):
            raise RuntimeError("boom")

    monkeypatch.setitem(voicefx.REGISTRY, Broken.type, Broken)
    x = sine(seconds=0.2)
    y = soundfx.render(x, {"effects": {Broken.type: {"on": True}}})
    assert np.allclose(y[:len(x)], x, atol=1e-6)


def test_a_module_effect_that_cant_start_is_skipped(monkeypatch):
    from soundboard import voicefx

    class NoStart(voicefx.Effect):
        type, name = "test.nostart", "No start"

        def __init__(self, rate, values=None):
            raise RuntimeError("missing model file")

    monkeypatch.setitem(voicefx.REGISTRY, NoStart.type, NoStart)
    x = sine(seconds=0.2)
    y = soundfx.render(x, {"effects": {NoStart.type: {"on": True}}})
    assert np.allclose(y[:len(x)], x, atol=1e-6)


# ---------------------------------------------------------------- library cache

@pytest.fixture
def sound(app_dir):
    p = app_dir / "s.wav"
    sf.write(p, sine(440, 0.5), SR, subtype="PCM_16")
    return SoundMeta(id="s1", name="s", file=str(p))


def test_load_sound_renders_effects_once_and_caches_them(sound, monkeypatch):
    plain = library.load_sound(sound)
    sound.fx = {"speed": 2.0}
    calls = []
    real = soundfx.render
    monkeypatch.setattr(soundfx, "render", lambda d, fx: calls.append(1) or real(d, fx))
    a = library.load_sound(sound)
    b = library.load_sound(sound)
    assert calls == [1]                                          # rendered once, then cached
    assert np.array_equal(a, b) and a.dtype == np.int16
    assert abs(len(a) - len(plain) / 2) < 10
    key = soundfx.key(sound.fx)
    assert library.cache_path("s1", key).exists() and library.cache_path("s1").exists()
    assert np.array_equal(library.load_original(sound), plain)


def test_cache_keep_and_prune_drop_replaced_effect_versions(sound):
    sound.fx = {"pitch": 5}
    library.load_sound(sound)
    old = library.cache_path("s1", soundfx.key(sound.fx))
    sound.fx = {"pitch": -5}
    library.load_sound(sound)
    new = library.cache_path("s1", soundfx.key(sound.fx))
    keep = library.cache_keep([sound])
    assert keep == {"s1", new.name[:-len(".npy")]}
    library.prune_cache(keep)
    assert new.exists() and library.cache_path("s1").exists() and not old.exists()


def test_fx_survive_a_config_round_trip(app_dir, sound):
    sound.fx = {"speed": 0.8, "tape": True}
    library.Config(sounds=[sound]).save()
    assert library.Config.load().sounds[0].fx == {"speed": 0.8, "tape": True}


def test_duplicate_is_independent_of_the_original(app_dir, sound):
    sound.hotkey, sound.fx = "ctrl+1", {"pitch": 3}
    library.load_sound(sound)
    copy = library.duplicate(sound, "s (ear rape)")
    assert copy.id != sound.id and copy.file != sound.file and copy.hotkey == ""
    assert copy.fx == sound.fx and copy.fx is not sound.fx
    copy.fx["pitch"] = 0
    assert sound.fx == {"pitch": 3}
    library.delete_file(copy)
    assert np.array_equal(library.load_original(sound), library.load_cached("s1"))
    assert library.cache_path("s1", soundfx.key(sound.fx)).exists()


def test_delete_removes_every_effect_version(app_dir, sound):
    sound.fx = {"speed": 1.5}
    library.load_sound(sound)
    library.store_cached("s10", np.zeros((4, 2), np.float32))   # another id with the same prefix
    library.delete_file(sound)
    assert not list(library.CACHE_DIR.glob("s1.*"))
    assert library.cache_path("s10").exists()


# ---------------------------------------------------------------- engine, live

def engine_main():
    e = Engine()
    e.main_stream = object()
    return e


def test_live_speed_reads_faster_and_ends_sooner():
    e = engine_main()
    d = sine(440, 0.1)                                   # 4800 frames
    e.sound_speed, e.sound_keep_pitch = 2.0, False
    v = e.play("a", d, 1.0)
    out = np.zeros((1200, 2), np.float32)
    e._main(out, 1200)
    assert abs(v.pos["main"] - 2400) < 2                # two frames of sound per frame played
    e._main(out, 1200)
    assert v.finished                                   # done in half the time


def test_live_speed_loops_and_half_speed():
    e = engine_main()
    d = sine(440, 0.05)                                 # 2400 frames
    e.sound_speed = 0.5
    v = e.play("a", d, 1.0, loop=True)
    out = np.zeros((6000, 2), np.float32)
    e._main(out, 6000)
    assert not v.finished and 0 <= v.pos["main"] < len(d)
    assert abs(v.pos["main"] - (3000 % len(d))) < 2


def test_render_speed_interpolates():
    ramp = np.linspace(0, 1, 101, dtype=np.float32)
    data = np.stack([ramp, ramp], 1)
    dst = np.zeros((10, 2), np.float32)
    p = Engine._render_speed(dst, data, 0.0, 0.5, np.float32(1), False)
    assert p == pytest.approx(5.0)
    assert np.allclose(dst[:, 0], np.arange(10) * 0.5 / 100, atol=1e-6)


@pytest.mark.parametrize("speed, keep, pitch, want", [
    (1.0, True, 12, 880),       # pitch alone
    (2.0, False, 0, 880),       # tape: twice as fast is an octave up
    (2.0, True, 0, 440),        # keep pitch: the shifter undoes the speed's octave
])
def test_live_pitch_on_the_sounds_bus(speed, keep, pitch, want):
    e = engine_main()
    e.sound_speed, e.sound_keep_pitch, e.sound_pitch = speed, keep, pitch
    e.play("a", sine(440, 3.0), 1.0)
    blocks = []
    for _ in range(40):
        out = np.zeros((1024, 2), np.float32)
        e._main(out, 1024)
        blocks.append(out.copy())
    y = np.concatenate(blocks)[8192:]
    assert abs(peak_hz(y) - want) < want * 0.04


# ---------------------------------------------------------------- UI

def test_edit_dialog_presets_apply_and_reset(qapp):
    from soundboard.ui.dialogs import EditDialog
    from soundboard.winkeys import Hotkeys
    m = SoundMeta(id="a", name="Boom", file="x.wav")
    previews = []
    d = EditDialog(m, Hotkeys(), lambda *a: previews.append(a), tab="effects")
    assert d.tabs.currentIndex() == 1 and d.effects.fx() == {}
    assert "pitch" not in d.effects.rows            # the Pitch slider covers it
    d.effects.preset.setCurrentText("Nightcore")
    assert d.effects.fx() == soundfx.PRESETS["Nightcore"]
    assert "1.2x" in d.fx_note.text()
    d.effects.pitch.set_value(3)
    d.effects._edited()
    assert d.effects.preset.currentText() == "Custom"
    d.apply()
    assert m.fx["pitch"] == 3 and m.fx["speed"] == 1.25 and m.fx["tape"]
    d2 = EditDialog(m, Hotkeys(), lambda *a: None)   # opens with what was saved
    assert d2.effects.fx() == m.fx
    d2.effects.preset.setCurrentText("None (original)")
    d2.apply()
    assert m.fx == {}
