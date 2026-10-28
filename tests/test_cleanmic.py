"""Clean mic: RNNoise on the mic before every voice (voicefx.cleanmic, the chain, the card)."""
import numpy as np
import pytest

from soundboard import voicefx
from soundboard.speech import tts
from soundboard.voicefx import cleanmic
from test_voicepanel import FakeEngine

real = pytest.mark.skipif(not cleanmic.available(),
                          reason="RNNoise not fetched (scripts/buildtools/fetch_rnnoise.py)")


class FakeCleaner:
    """Halves the mic: easy to see it ran, and when."""
    made: list = []

    def __init__(self, rate, strength="normal"):
        self.rate, self.strength, self.level = rate, strength, 0.0
        self.closed = False
        FakeCleaner.made.append(self)

    def set_strength(self, s):
        self.strength = s

    def latency(self):
        return 0.03

    def process(self, m):
        self.level = 0.25
        return m * np.float32(0.5)

    def close(self):
        self.closed = True


@pytest.fixture
def fake(monkeypatch):
    FakeCleaner.made = []
    monkeypatch.setattr(cleanmic, "Cleaner", FakeCleaner)
    return FakeCleaner


def block(n=480, v=0.2):
    return np.full((n, 2), v, np.float32)


# ---------------------------------------------------------------- settings
def test_saved_settings_are_cleaned():
    assert cleanmic.clean_settings(None) == {"on": False, "strength": "normal"}
    assert cleanmic.clean_settings({"on": 1, "strength": "max"}) == {"on": False,
                                                                     "strength": "normal"}
    assert cleanmic.clean_settings({"on": True, "strength": "light"}) == {"on": True,
                                                                          "strength": "light"}


# ---------------------------------------------------------------- the chain
def test_chain_cleans_the_mic_with_no_voice_on(fake):
    ch = voicefx.VoiceChain()
    x = block()
    assert ch.process(x, 48000) is x            # off: the mic untouched
    ch.set_clean(True, "light")
    assert ch.active and ch.clean_on and not ch.changes_voice
    y = ch.process(x, 48000)
    assert np.allclose(y, 0.1) and y.shape == x.shape
    assert fake.made[-1].strength == "light" and ch.clean_level() == 0.25
    ch.set_clean(True, "normal")                # a new strength: the same cleaner
    ch.process(x, 48000)
    assert len(fake.made) == 1 and fake.made[0].strength == "normal"
    ch.process(x, 44100)                        # a new mic rate: a new one
    assert len(fake.made) == 2 and fake.made[0].closed and fake.made[1].rate == 44100
    ch.set_clean(False)
    assert ch.process(x, 44100) is x and fake.made[1].closed and ch.clean_level() == 0.0


def test_chain_cleans_before_the_voice_changer(fake):
    ch = voicefx.VoiceChain()
    seen = []
    ch.tap = lambda m, rate: seen.append(float(m[0]))
    ch.set_clean(True)
    ch.process(block(), 48000)
    assert seen == [pytest.approx(0.1)]         # speech recognition hears the cleaned mic


def test_a_failing_cleaner_never_stops_the_mic(monkeypatch):
    class Broken(FakeCleaner):
        def process(self, m):
            raise RuntimeError("boom")
    monkeypatch.setattr(cleanmic, "Cleaner", Broken)
    ch = voicefx.VoiceChain()
    ch.set_clean(True)
    x = block()
    y = ch.process(x, 48000)
    assert np.allclose(y, 0.2) and "boom" in ch.clean_error and ch.cleaner is None
    assert ch.process(x, 48000) is x            # stays off until it's switched again


def test_a_cleaner_that_wont_start_says_why(monkeypatch):
    def no(rate, strength="normal"):
        raise RuntimeError("RNNoise isn't available")
    monkeypatch.setattr(cleanmic, "Cleaner", no)
    ch = voicefx.VoiceChain()
    ch.set_clean(True)
    x = block()
    assert ch.process(x, 48000) is x and "available" in ch.clean_error
    ch.set_clean(False)
    assert ch.clean_error == ""


# ---------------------------------------------------------------- the real RNNoise
def _noisy(rate=48000, seconds=2.0):
    rng = np.random.default_rng(3)
    n = int(rate * seconds)
    noise = rng.standard_normal(n).astype(np.float32) * np.float32(0.02)   # a fan, ~-34 dB
    t = np.arange(n) / rate
    voice = (0.3 * np.sin(2 * np.pi * 180 * t) * (np.sin(2 * np.pi * 3 * t) > 0)).astype(
        np.float32)
    voice[: rate // 2] = 0                    # the first half second: only the noise
    return voice + noise


def _db(x):
    return 10 * np.log10(np.mean(np.asarray(x, np.float64) ** 2) + 1e-20)


@real
@pytest.mark.parametrize("rate", [48000, 44100])
def test_rnnoise_takes_the_noise_out_in_any_block_size(rate):
    x = _noisy(rate)
    c = cleanmic.Cleaner(rate)
    sizes = [128, 441, 480, 512, 1024, 7]
    out, i, k = [], 0, 0
    while i < len(x):
        n = sizes[k % len(sizes)]
        out.append(c.process(x[i:i + n]))
        i, k = i + n, k + 1
    y = np.concatenate(out)
    c.close()
    assert len(y) == len(x) and np.all(np.isfinite(y))
    gap = slice(int(0.15 * rate), int(0.45 * rate))   # noise alone, after the start-up
    lag = int(round(cleanmic.DELAY / cleanmic.RATE * rate)) + 600
    assert _db(y[gap.start + lag:gap.stop + lag]) < _db(x[gap]) - 30


@real
def test_light_leaves_some_noise_and_the_test_clip_lines_up():
    x = _noisy()
    normal = cleanmic.clean_clip(x, 48000, "normal")
    light = cleanmic.clean_clip(x, 48000, "light")
    assert len(normal) == len(light) == len(x)
    gap = slice(int(0.15 * 48000), int(0.45 * 48000))
    assert _db(normal[gap]) < _db(light[gap]) < _db(x[gap]) - 8
    # lined up with the recording: Light's share of the mic as it was sits at no lag
    a, b = light[4800:48000], x[4800:48000]
    lags = range(-1500, 1501, 5)
    assert max(lags, key=lambda L: float(np.dot(a, np.roll(b, L)))) == 0


# ---------------------------------------------------------------- the card
@pytest.fixture
def panel(qapp, monkeypatch, fake):
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: ["Microsoft Zira Desktop"])
    monkeypatch.setattr(cleanmic, "available", lambda: True)
    from soundboard.ui.voice.voicepanel import VoicePanel
    eng = FakeEngine()
    saved = []
    p = VoicePanel(eng, {"enabled": False, "effects": {}}, {"voice": "Microsoft Zira Desktop"})
    p.speech_changed.connect(saved.append)
    yield p, saved
    p.shutdown()
    p.deleteLater()


def test_clean_mic_is_the_first_tab_and_switches_the_chain(panel):
    p, saved = panel
    assert list(p._tabs)[0] == "clean"
    c = p.clean
    assert not c.is_on() and not p.chain.clean_on
    c.b_on.click()
    assert p.chain.clean_on and saved[-1]["clean"] == {"on": True, "strength": "normal"}
    assert c.b_on.text() == "On" and p._tabs["clean"].property("live")
    c.b_strength["light"].click()
    assert p.chain._clean_want == "light" and saved[-1]["clean"]["strength"] == "light"
    assert "Light" in c.lbl_strength.text()


def test_its_chip_shows_and_turns_it_off_and_voices_leave_it_alone(panel):
    p, _saved = panel
    p.clean.b_on.click()
    assert "Clean mic" in p.bar.texts()
    p.set_voices(False)                       # the Voices switch: a voice thing only
    p.set_voices(True)
    assert p.clean.is_on()
    p.toggle_one("clean")                     # its chip clicked
    assert not p.clean.is_on() and not p.chain.clean_on
    assert "Clean mic" not in p.bar.texts()


def test_it_comes_back_on_from_last_time(qapp, monkeypatch, fake):
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    monkeypatch.setattr(cleanmic, "available", lambda: True)
    from soundboard.ui.voice.voicepanel import VoicePanel
    p = VoicePanel(FakeEngine(), {"enabled": False, "effects": {}},
                   {"clean": {"on": True, "strength": "light"}})
    try:
        assert p.clean.is_on() and p.chain._clean_want == "light"
        assert p.clean.b_strength["light"].isChecked()
    finally:
        p.shutdown()
        p.deleteLater()


def test_without_rnnoise_it_says_so_and_cant_be_switched_on(qapp, monkeypatch, fake):
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    monkeypatch.setattr(cleanmic, "available", lambda: False)
    from soundboard.ui.voice.voicepanel import VoicePanel
    p = VoicePanel(FakeEngine(), {"enabled": False, "effects": {}},
                   {"clean": {"on": True}})
    try:
        assert not p.clean.is_on() and not p.chain.clean_on
        assert not p.clean.b_on.isEnabled() and not p.clean.lbl_missing.isHidden()
        assert p.clean.body.isHidden()            # no greyed-out controls under it
    finally:
        p.shutdown()
        p.deleteLater()


def test_hear_the_difference_records_then_plays_before_and_after(panel, monkeypatch, qapp):
    p, _saved = panel
    c = p.clean
    played = []

    class Eng(FakeEngine):
        mic_stream = object()
        taking = False
        rates = {"mic": 48000}

        def start_mic_take(self, processed=False):
            assert not processed            # the real mic: After is cleaned from it
            self.blocks = [np.full((4800, 2), 0.1, np.float32)] * 10
            return self.blocks

        def stop_mic_take(self):
            return self.blocks

        def play(self, sid, data, gain, preview=False, src_rate=48000, **k):
            played.append((preview, float(np.max(data)), src_rate))
            return object()
    c.engine = Eng()
    monkeypatch.setattr(cleanmic, "clean_clip", lambda m, rate, s: m * np.float32(0.5))
    c.b_rec.click()
    assert c._take is not None and "Stop" in c.b_rec.text()
    c._stop_record()
    for _ in range(200):                     # the worker hands the cleaned copy back
        qapp.processEvents()
        if c.b_after.isEnabled():
            break
    assert c.b_before.isEnabled() and c.b_after.isEnabled()
    c.b_before.click()
    c.b_after.click()
    assert played == [(True, pytest.approx(0.1), 48000), (True, pytest.approx(0.05), 48000)]


def test_after_an_error_it_says_the_mic_goes_out_uncleaned(panel):
    p, _saved = panel
    c = p.clean
    c.b_on.click()
    c._tick()
    assert "cleaned one" in c.lbl_now.text() and c.lbl_error.isHidden()
    p.chain.clean_error = "boom"
    c._tick()
    assert "boom" in c.lbl_error.text() and not c.lbl_error.isHidden()
    assert "as it is" in c.lbl_now.text()
    c.b_on.click()                            # off, and on again: a new go, no error
    c.b_on.click()
    c._tick()
    assert c.lbl_error.isHidden() and "cleaned one" in c.lbl_now.text()


def test_hear_the_difference_with_no_mic_says_why(panel):
    p, _saved = panel
    p.clean.b_rec.click()                    # FakeEngine: no mic open
    assert p.clean._take is None and "No mic" in p.clean.lbl_test.text()
