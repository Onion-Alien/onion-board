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

    def __init__(self, rate, strength="normal", opts=None):
        self.rate, self.strength, self.level = rate, strength, 0.0
        self.opts = opts or {}
        self.closed = False
        FakeCleaner.made.append(self)

    def set_strength(self, s):
        self.strength = s

    def set_options(self, opts):
        self.opts = opts

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
    default = {"on": False, "strength": "normal", "volume": 100, "auto_sense": True,
               "sense_db": -50, "agc": False}
    assert cleanmic.clean_settings(None) == default
    assert cleanmic.clean_settings({"on": 1, "strength": "max"}) == default
    # (a config from before the cog: on and strength only)
    assert cleanmic.clean_settings({"on": True, "strength": "light"}) == {
        **default, "on": True, "strength": "light"}
    assert cleanmic.clean_settings({"strength": "off", "volume": 999, "auto_sense": False,
                                    "sense_db": -300.0, "agc": True}) == {
        **default, "strength": "off", "volume": 200, "auto_sense": False, "sense_db": -100,
        "agc": True}
    assert cleanmic.clean_settings({"volume": "loud", "sense_db": float("nan"),
                                    "auto_sense": 0, "agc": 1}) == default


def test_presets_and_custom():
    s = cleanmic.clean_settings(None)
    assert cleanmic.preset_of(s) == "normal"
    assert cleanmic.preset_of({**s, "strength": "light"}) == "quiet"   # old Light configs
    assert cleanmic.preset_of({**s, "strength": "strong"}) == "custom"
    for key, p in cleanmic.PRESETS.items():
        assert cleanmic.preset_of({**s, **p}) == key
    loud = {**s, **cleanmic.PRESETS["loud"]}
    assert cleanmic.preset_of({**loud, "sense_db": -49}) == "custom"
    assert cleanmic.preset_of({**s, "sense_db": -12}) == "normal"   # (automatic: not used)
    assert cleanmic.options(loud) == {"volume": 100, "sense": -50, "agc": False}
    assert cleanmic.options(s)["sense"] is None


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


def test_chain_hands_the_cleaner_its_settings(fake):
    ch = voicefx.VoiceChain()
    ch.set_clean(True, "off", {"volume": 150, "sense": -40, "agc": True})
    ch.process(block(), 48000)
    assert fake.made[-1].strength == "off" and fake.made[-1].opts["sense"] == -40
    ch.set_clean(True, "off", {"volume": 80, "sense": None, "agc": False})
    ch.process(block(), 48000)
    assert len(fake.made) == 1 and fake.made[0].opts == {"volume": 80, "sense": None,
                                                         "agc": False}


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
    def no(rate, strength="normal", opts=None):
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
    # (against the mic through the same rumble filter: it shifts a low tone's phase)
    a, b = light[4800:48000], cleanmic.Tidy(gate=False).run(x)[4800:48000]
    lags = range(-1500, 1501, 5)
    assert max(lags, key=lambda L: float(np.dot(a, np.roll(b, L)))) == 0


# ---------------------------------------------------------------- after the network
def _tidied(x, gate=True, sizes=(480, 128, 1024, 7)):
    t, out, i, k = cleanmic.Tidy(gate), [], 0, 0
    while i < len(x):
        out.append(t.run(x[i:i + sizes[k % len(sizes)]]))
        i, k = i + sizes[k % len(sizes)], k + 1
    return np.concatenate(out)


def test_rumble_under_80_hz_goes_and_the_voice_stays():
    t = np.arange(48000) / 48000
    rumble = _tidied((0.3 * np.sin(2 * np.pi * 30 * t)).astype(np.float32), gate=False)
    voice = _tidied((0.3 * np.sin(2 * np.pi * 300 * t)).astype(np.float32), gate=False)
    assert len(rumble) == 48000 and np.all(np.isfinite(rumble))
    assert _db(rumble[24000:]) < _db(0.3 * np.sin(2 * np.pi * 30 * t[24000:])) - 15
    assert abs(_db(voice[24000:]) - _db(0.3 * np.sin(2 * np.pi * 300 * t[24000:]))) < 0.5


def _talk_then_room(quiet=0.003):
    """A second of talking, a second of a quiet room (a voice across it, a TV)."""
    rng = np.random.default_rng(5)
    t = np.arange(96000) / 48000
    room = (rng.standard_normal(96000) * quiet).astype(np.float32)
    talk = (0.2 * np.sin(2 * np.pi * 220 * t) * (t < 1.0)).astype(np.float32)
    return talk + room, talk


def test_the_gate_turns_the_room_down_between_words_and_not_the_words():
    x, talk = _talk_then_room()
    y = _tidied(x)
    assert _db(y[48000 + 24000:]) < _db(x[48000 + 24000:]) - 15   # the room, once closed
    assert abs(_db(y[4800:43200]) - _db(x[4800:43200])) < 1        # the words as they were
    assert _db(y[240:1200]) > _db(x[240:1200]) - 3                 # a word's start isn't cut


def test_a_set_sensitivity_opens_the_gate_there():
    x, talk = _talk_then_room(quiet=0.02)          # a loud room: -34 dB
    t = cleanmic.Tidy(sense=-20.0)                 # stricter than the room, under the voice
    y = np.concatenate([t.run(x[i:i + 480]) for i in range(0, len(x), 480)])
    assert _db(y[72000:]) < _db(x[72000:]) - 15 and t.open_db == -20.0
    assert abs(_db(y[4800:43200]) - _db(x[4800:43200])) < 1
    t = cleanmic.Tidy(sense=-5.0)                  # over the voice: it stays down
    y = np.concatenate([t.run(x[i:i + 480]) for i in range(0, len(x), 480)])
    assert _db(y[4800:43200]) < _db(x[4800:43200]) - 15


def test_agc_brings_a_quiet_voice_up_and_holds_between_words():
    rng = np.random.default_rng(7)
    t = np.arange(48000 * 3) / 48000
    words = (np.sin(2 * np.pi * 3 * t) > 0) & (t < 2.0)     # two seconds of words, then none
    talk = (0.02 * np.sin(2 * np.pi * 200 * t) * words      # quiet: about -37 dB
            + rng.standard_normal(len(t)) * 0.0005).astype(np.float32)   # and the room
    tidy, agc, out = cleanmic.Tidy(), cleanmic.Agc(), []
    for i in range(0, len(talk), 480):
        c = tidy.run(talk[i:i + 480])
        out.append(agc.run(c, tidy.talking, tidy.peak_db))
    y = np.concatenate(out)
    assert np.all(np.isfinite(y)) and np.max(np.abs(y)) <= cleanmic.Agc.PEAK + 1e-6
    late = words & (t > 1.5)
    assert _db(y[late]) > _db(talk[late]) + 8   # the voice: up (a second of words in)
    assert agc.gain_db <= cleanmic.Agc.MAX_UP
    # between words the gain holds (and the gate has the room down): never pulled up
    assert _db(y[-24000:]) < _db(talk[-24000:]) + cleanmic.Agc.MAX_UP + 1
    loud = np.full(4800, 0.99, np.float32)                          # never over the top
    assert np.max(np.abs(agc.run(loud, True, -0.1)[-480:])) <= cleanmic.Agc.PEAK + 1e-6


def test_light_keeps_the_room_and_each_strength_sets_the_gate():
    x, _talk = _talk_then_room()
    assert _db(_tidied(x, gate=False)[72000:]) > _db(x[72000:]) - 2
    assert cleanmic.Tidy().gate


@real
def test_the_cleaner_gates_on_normal_not_light():
    c = cleanmic.Cleaner(48000, "light")
    try:
        assert not c._tidy.gate
        c.set_strength("normal")
        assert c._tidy.gate
        c.set_strength("light")
        c.set_options({"sense": -40})               # a sensitivity set: Light gates too
        assert c._tidy.gate and c._tidy.sense == -40
    finally:
        c.close()


@real
def test_off_runs_no_network_but_the_volume_and_the_rest():
    x = _noisy()
    c = cleanmic.Cleaner(48000, "off", {"volume": 200})
    try:
        y = np.concatenate([c.process(x[i:i + 480]) for i in range(0, len(x), 480)])
        assert c.latency() < cleanmic.DELAY / cleanmic.RATE
        talk = slice(48000, 96000)
        lag = c._prime
        assert abs(_db(y[talk.start + lag:talk.stop]) - _db(x[talk.start:talk.stop - lag]) - 6) < 1
    finally:
        c.close()
    assert len(cleanmic.clean_clip(x, 48000, "off", {"agc": True})) == len(x)


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
    assert p.chain.clean_on and saved[-1]["clean"] == {
        "on": True, "strength": "normal", "volume": 100, "auto_sense": True, "sense_db": -50,
        "agc": False}
    assert c.b_on.text() == "On" and p._tabs["clean"].property("live")
    c.b_strength["light"].click()
    assert p.chain._clean_want == "light" and saved[-1]["clean"]["strength"] == "light"
    assert "Light" in c.lbl_strength.text()


def test_the_cog_opens_mic_settings_and_presets_set_them(panel, monkeypatch):
    p, saved = panel
    c = p.clean
    from soundboard.voicefx import deepfilter
    monkeypatch.setattr(deepfilter, "downloaded", lambda: True)
    assert c.settings.isHidden()
    c.b_cog.click()
    assert not c.settings.isHidden() and c.settings.b_preset["normal"].isChecked()
    c.b_on.click()
    c.settings.b_preset["voice"].click()
    s = saved[-1]["clean"]
    assert (s["strength"], s["auto_sense"], s["sense_db"], s["agc"]) == ("strong", False,
                                                                         -40, True)
    assert p.chain._clean_want == "strong"
    assert p.chain._clean_opts == {"volume": 100, "sense": -40, "agc": True}
    assert c.settings.b_preset["voice"].isChecked() and c.settings.sense.isEnabled()
    c.settings.agc.click()                          # a control touched: Custom
    assert not any(b.isChecked() for b in c.settings.b_preset.values())
    assert c.settings.lbl_preset.text().startswith("Custom")
    assert p.chain._clean_opts["agc"] is False and saved[-1]["clean"]["agc"] is False
    c.settings.sense.setValue(-30)
    assert saved[-1]["clean"]["sense_db"] == -30 and p.chain._clean_opts["sense"] == -30
    c.settings.auto.click()                         # automatic: no handle to drag
    assert not c.settings.sense.isEnabled() and p.chain._clean_opts["sense"] is None
    c.settings.volume.slider.setValue(150)
    assert saved[-1]["clean"]["volume"] == 150 and p.chain._clean_opts["volume"] == 150
    c.b_strength["off"].click()
    assert p.chain._clean_want == "off" and "Off" in c.lbl_strength.text()
    c.settings.b_preset["quiet"].click()
    assert saved[-1]["clean"] == {"on": True, "strength": "light", "volume": 100,
                                  "auto_sense": True, "sense_db": -30, "agc": False}
    c._tick()                                       # the sensitivity bar is fed
    c.b_cog.click()
    assert c.settings.isHidden()


def test_a_strong_preset_offers_the_download_first(panel, monkeypatch):
    p, saved = panel
    c = p.clean
    from soundboard.voicefx import deepfilter
    monkeypatch.setattr(deepfilter, "downloaded", lambda: False)
    c.b_cog.click()
    c.settings.b_preset["loud"].click()
    assert c.s["strength"] == "normal" and not c.get_box.isHidden()
    assert c.s["auto_sense"] is False and c.s["sense_db"] == -50


def test_its_bar_shows_pauses_and_goes_and_voices_leave_it_alone(panel):
    """Clean mic has a bar as a voice does (its preset by name, "(Clean mic)", Edit, a
    pause and a ✕), not a chip; the Voices switch leaves it alone."""
    p, _saved = panel
    b = p.clean_bar
    p.resize(1000, 600)
    p.show()
    p.show_tab("fx")
    assert b.picked.isHidden()
    p.clean.b_on.click()
    assert not b.picked.isHidden() and "clean" not in p.bar.chips   # a bar, no chip
    assert (b.picked_name.text(), b.picked_kind.text()) == ("Normal", "(Clean mic)")
    assert b.btn_tweak.text() == "Edit" and b.btn_effects.isHidden()   # not a voice
    assert not b.picked_pic.pixmap().isNull()
    p.set_voices(False)                       # the Voices switch: a voice thing only
    p.set_voices(True)
    assert p.clean.is_on() and not b.picked.isHidden()
    pause, close = p._bar_ctl["clean"]
    pause.click()                             # off, its bar kept, dimmed
    assert not p.clean.is_on() and not p.chain.clean_on
    assert not b.picked.isHidden() and "back on" in pause.toolTip()
    assert p._bar_dim["clean"][0].opacity() < 1
    assert p.current_tab() == "fx"            # a click doesn't jump tabs
    pause.click()                             # ...and back on
    assert p.clean.is_on() and p._bar_dim["clean"][0].opacity() == 1
    close.click()                             # its ✕: off, and its bar goes
    assert not p.clean.is_on() and b.picked.isHidden()
    p.clean.b_on.click()                      # on, off again on its card: no paused bar
    p.clean.b_on.click()
    assert b.picked.isHidden()
    p.clean.b_on.click()
    p.clean.settings.agc.click()              # its own settings: Custom, by name
    assert b.picked_name.text() == "Custom"


def test_its_bar_edit_opens_mic_settings_on_its_tab(panel):
    p, _saved = panel
    p.resize(1000, 600)
    p.show()
    p.show_tab("ai")
    p.clean.b_on.click()
    assert p.clean.settings.isHidden()
    p.clean_bar.btn_tweak.click()
    assert p.current_tab() == "clean" and not p.clean.settings.isHidden()


def test_it_comes_back_on_from_last_time(qapp, monkeypatch, fake):
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    monkeypatch.setattr(cleanmic, "available", lambda: True)
    from soundboard.ui.voice.voicepanel import VoicePanel
    p = VoicePanel(FakeEngine(), {"enabled": False, "effects": {}},
                   {"clean": {"on": True, "strength": "light", "agc": True}})
    try:
        assert p.clean.is_on() and p.chain._clean_want == "light"
        assert p.clean.b_strength["light"].isChecked() and p.chain._clean_opts["agc"]
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
        assert not p.clean.b_cog.isVisibleTo(p.clean)
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
    monkeypatch.setattr(cleanmic, "clean_clip", lambda m, rate, s, o: m * np.float32(0.5))
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
