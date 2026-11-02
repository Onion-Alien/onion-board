"""Critter chatter, Fart, Drum kit, Whistle and Kazoo: your syllables (or your tune)
turned into something else."""
import numpy as np
import pytest

from soundboard import voicefx
from soundboard.voicefx import REGISTRY, VoiceChain, critters, defaults
from tests.test_voicefx import _f0, _speech_like, dominant_hz, run_blocks, sine, spec_for

RATE = 48000
NEW = {"chatter": "Critter chatter", "fart": "Fart", "drums": "Drum kit",
       "whistle": "Whistle", "kazoo": "Kazoo"}


def _syllables(k=3, secs=0.2, gap=0.6, f0=140.0, amp=0.3):
    """k separate syllables (a buzzy vowel each) with quiet between them."""
    x = np.zeros(int(RATE * (0.2 + gap * k)), np.float32)
    t = np.arange(int(RATE * secs)) / RATE
    tone = sum(np.sin(2 * np.pi * f0 * j * t) / j for j in range(1, 12))
    tone = (amp * tone / np.max(np.abs(tone))).astype(np.float32)
    for i in range(k):
        a = int(RATE * (0.1 + gap * i))
        x[a:a + len(tone)] = tone
    return x


def _onsets(y, thresh=0.1):
    env = np.sqrt((y[:len(y) // 480 * 480].reshape(-1, 480) ** 2).mean(1))
    on = env > thresh * env.max()
    return int(np.sum(on[1:] & ~on[:-1])) + int(on[0])


@pytest.mark.parametrize("kind", sorted(NEW))
def test_silence_in_silence_out(kind):
    y = run_blocks(REGISTRY[kind](RATE, defaults(kind)), np.zeros(RATE * 2, np.float32), 480)
    assert np.max(np.abs(y)) == 0.0


@pytest.mark.parametrize("kind", sorted(NEW))
def test_speech_comes_out_about_as_loud_and_under_full_scale(kind):
    x = _speech_like(3.0)
    y = run_blocks(REGISTRY[kind](RATE, defaults(kind)), x, 480)
    assert np.all(np.isfinite(y))
    db = 20 * np.log10(np.sqrt(np.mean(y ** 2)) / np.sqrt(np.mean(x ** 2)))
    assert -7 < db < 7, f"{kind}: {db:+.1f} dB"
    assert np.max(np.abs(y)) < 1.0


@pytest.mark.parametrize("kind", sorted(NEW))
def test_never_blasts_on_a_loud_steady_input(kind):
    x = np.full(RATE, 0.7, np.float32) * np.sign(sine(200, 1.0))
    y = run_blocks(REGISTRY[kind](RATE, defaults(kind)), x, 480)
    assert np.max(np.abs(y)) < 1.0


@pytest.mark.parametrize("kind", sorted(NEW))
@pytest.mark.parametrize("rate, block", [(16000, 160), (44100, 441), (48000, 1024)])
def test_any_rate_and_block_size(kind, rate, block):
    t = np.arange(rate * 2) / rate
    x = (0.3 * np.sin(2 * np.pi * 150 * t) * (np.sin(2 * np.pi * 2 * t) > 0)).astype(np.float32)
    e = REGISTRY[kind](rate, defaults(kind))
    y = np.concatenate([e.run(x[i:i + block], rate) for i in range(0, len(x) - block + 1, block)])
    assert np.all(np.isfinite(y)) and np.max(np.abs(y)) < 1.0
    assert np.sqrt(np.mean(y ** 2)) > 0.005


def test_chatter_blips_once_per_short_syllable_and_more_for_a_long_one():
    e = REGISTRY["chatter"](RATE, defaults("chatter"))
    e.rng = np.random.default_rng(0)
    y = run_blocks(e, _syllables(3, secs=0.07), 480)
    assert _onsets(y) == 3
    e = REGISTRY["chatter"](RATE, defaults("chatter"))
    e.rng = np.random.default_rng(0)
    y = run_blocks(e, _syllables(1, secs=0.6, gap=1.0), 480)
    assert _onsets(y, 0.05) >= 4                       # a long one babbles on


def test_chatter_is_high_and_follows_your_tune():
    def pitch(f0):
        e = REGISTRY["chatter"](RATE, {"note": 0, "follow": 1, "mix": 1})
        e.JITTER_ST = 0.0
        e.home, e.heard = 12 * np.log2(140), 1000      # your usual pitch: 140 Hz
        y = run_blocks(e, _syllables(1, secs=0.09, f0=f0, gap=0.5), 480)
        return dominant_hz(y)
    flat, up = pitch(140), pitch(140 * 2 ** (7 / 12))
    assert 450 < flat < 2000                          # a cute high blip, far above you
    assert up > flat * 1.2                            # you went up: so did it


def test_fart_plays_a_recording_per_syllable(monkeypatch):
    t = np.arange(int(0.25 * RATE)) / RATE
    tone = (np.sin(2 * np.pi * 300 * t) * critters.CALL_RMS * np.sqrt(2)).astype(np.float32)
    monkeypatch.setitem(critters._calls, "fart", (tone, tone.copy(), tone.copy()))
    e = REGISTRY["fart"](RATE, defaults("fart"))
    starts = 0
    x = _syllables(4, secs=0.15, gap=0.5)
    out = []
    for i in range(0, len(x) - 479, 480):
        before = e.played
        out.append(e.run(x[i:i + 480], RATE))
        starts += e.played < before
    assert starts == 4
    y = np.concatenate(out)
    assert abs(dominant_hz(y) - 300) < 20 and np.max(np.abs(y)) < 1.0   # the recording


def test_fart_has_a_made_up_one_until_the_recordings_are_in():
    e = REGISTRY["fart"](RATE, defaults("fart"))
    e.rng = np.random.default_rng(0)
    y = run_blocks(e, _syllables(2), 480)
    assert np.sqrt(np.mean(y ** 2)) > 0.01 and np.max(np.abs(y)) < 1.0
    assert dominant_hz(y) < 400                       # low and rumbly


def test_picking_fart_or_drums_fetches_their_recordings(monkeypatch):
    asked = []
    monkeypatch.setattr(critters, "fetch", asked.append)
    VoiceChain().configure(spec_for(**voicefx.PRESETS["Fart"]))
    VoiceChain().configure(spec_for(**voicefx.PRESETS["Drum kit"]))
    assert asked == ["fart", "drum-kick", "drum-snare", "drum-hat", "drum-crash"]
    for kind in asked:
        assert critters.SOURCES[kind]
        assert all(s.url.startswith(("https://bigsoundbank.com/",
                                     "https://cdn.freesound.org/previews/"))
                   for s in critters.SOURCES[kind])


def test_drums_play_the_recorded_kit_once_its_in(monkeypatch):
    for k, hz in (("kick", 80), ("snare", 300), ("hat", 900), ("crash", 600)):
        t = np.arange(int(0.3 * RATE)) / RATE
        rec = (np.sin(2 * np.pi * hz * t) * critters.CALL_RMS * np.sqrt(2)).astype(np.float32)
        monkeypatch.setitem(critters._calls, "drum-" + k, (rec,))
    e = REGISTRY["drums"](RATE, defaults("drums"))
    y = run_blocks(e, np.concatenate([_syllables(3, secs=0.15, gap=0.3),
                                      np.zeros(RATE, np.float32)]), 480)
    assert e.hits == ["kick"] * 3 + ["crash"]
    assert abs(dominant_hz(y[:int(RATE * 0.9)]) - 80) < 10            # the recorded kick
    assert np.max(np.abs(y)) < 1.0


def test_drums_pick_the_drum_by_how_the_syllable_starts():
    rng = np.random.default_rng(1)

    def first_hit(burst):
        x = np.zeros(int(RATE * 0.6), np.float32)
        x[4800:4800 + len(burst)] = burst
        e = REGISTRY["drums"](RATE, defaults("drums"))
        run_blocks(e, x, 480)
        return e.hits[0]
    low = sine(110, 0.2, amp=0.3)                                  # "boom": a kick
    from soundboard.audio.dsp import butter, sosfilt
    hiss = sosfilt(butter(2, 5000, btype="high", fs=RATE),
                   rng.standard_normal(int(RATE * 0.2))).astype(np.float32) * 0.3
    snap = sosfilt(butter(2, [1500, 4000], btype="band", fs=RATE),
                   rng.standard_normal(int(RATE * 0.2))).astype(np.float32) * 0.3
    assert first_hit(low) == "kick"
    assert first_hit(hiss) == "hat"
    assert first_hit(snap) == "snare"


def test_drums_hit_once_a_syllable_and_crash_when_you_stop():
    e = REGISTRY["drums"](RATE, defaults("drums"))
    x = np.concatenate([_syllables(4, secs=0.15, gap=0.3), np.zeros(RATE, np.float32)])
    y = run_blocks(e, x, 480)
    assert e.hits[:4] == ["kick"] * 4 and e.hits[4:] == ["crash"]
    tail = y[int(RATE * 1.45):int(RATE * 1.9)]                   # after you stopped
    assert np.sqrt(np.mean(tail ** 2)) > 0.005
    e = REGISTRY["drums"](RATE, defaults("drums"))
    run_blocks(e, np.concatenate([_syllables(1), np.zeros(RATE, np.float32)]), 480)
    assert "crash" not in e.hits                                  # one word: no crash


def test_whistle_is_high_and_kazoo_buzzes_at_your_pitch():
    x = sine(160, 1.5, amp=0.3)
    y = run_blocks(REGISTRY["whistle"](RATE, defaults("whistle")), x, 480)
    assert 900 < dominant_hz(y[RATE // 2:]) < 1700           # whistling range
    y = run_blocks(REGISTRY["kazoo"](RATE, defaults("kazoo")), x, 480)
    assert 140 < _f0(y[RATE // 2:RATE // 2 + 4096]) < 180     # your own 160 Hz
    low = run_blocks(REGISTRY["kazoo"](RATE, defaults("kazoo")), sine(90, 1.5, amp=0.3), 480)
    assert _f0(low[RATE // 2:RATE // 2 + 4096]) > 130         # a deep voice lifted


@pytest.mark.parametrize("kind", ["whistle", "kazoo"])
def test_tune_voices_follow_your_tune(kind):
    e = REGISTRY[kind](RATE, defaults(kind))
    e.home, e.heard = 12 * np.log2(160), 1000         # your usual pitch: 160 Hz
    t = np.arange(int(RATE * 2)) / RATE
    f = np.where(t < 1, 160.0, 160.0 * 2 ** (5 / 12))   # you go up a fourth
    x = (0.3 * np.sin(2 * np.pi * np.cumsum(f) / RATE)).astype(np.float32)
    st = []
    for i in range(0, len(x) - 479, 480):
        e.run(x[i:i + 480], RATE)
        st.append(e.st)
    rise = st[125] - st[90]                           # (a third of a second on)
    want = 5 * e.p["follow"]
    assert abs(rise - want) < 1.5, (rise, want)


def test_new_voices_are_grouped_and_have_icons_and_texts():
    from soundboard.ui.kit.iconshapes import SHAPES
    from soundboard.ui.voice.effectrow import FX_ICONS, GROUPS
    from soundboard.ui.voice.voicetiles import VOICE_GROUPS
    from soundboard.voicefx.builtin.texts import shown_texts
    funny = dict((k, n) for k, _t, n in VOICE_GROUPS)["funny"]
    in_groups = {t for _g, types in GROUPS for t in types}
    texts = shown_texts()
    for kind, preset in NEW.items():
        assert preset in funny and preset in voicefx.PRESETS
        assert kind in in_groups and FX_ICONS[kind] in SHAPES
        assert REGISTRY[kind].name in texts and REGISTRY[kind].description in texts
