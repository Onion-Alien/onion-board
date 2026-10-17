"""My setups in Live controls (ui.livesetups, soundboard.livesetup): a voice setup on
every sound, the radio or the programs the Apps tab sends. The voice changer part is on
at once; an AI voice is made first (sounds) or started first (streams), with a Cancel."""
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from test_mainwindow import window  # noqa: F401  (the real MainWindow)

from soundboard import library, livesetup, renderworker, voicesetups
from soundboard.library import SR
from soundboard.ui import toast

ROBOT = {"robot": {"on": True, "freq": 100, "noise": 0.2, "mix": 1}}
BEAR = {"id": "bear", "name": "Bear", "pitch": 0.0}


def tone(n=4800):
    t = np.arange(n, dtype=np.float32) / SR
    x = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    return np.stack([x, x], 1)


def test_a_setup_splits_into_its_live_part_and_its_ai_voice():
    setup = {"name": "Robo bear", "effects": ROBOT, "ai": BEAR}
    assert livesetup.chain_spec(setup) == {"enabled": True, "effects": ROBOT}
    assert livesetup.chain_spec({"ai": BEAR}) == {} and livesetup.chain_spec(None) == {}
    assert livesetup.ai_of(setup) == BEAR and livesetup.ai_of({"effects": ROBOT}) is None
    # a sound keeps its own effects; the AI voice goes into its voice
    fx = livesetup.sound_fx({"speed": 1.5}, setup)
    assert fx["speed"] == 1.5 and fx["voice"]["ai"]["id"] == "bear"
    assert livesetup.sound_fx({"speed": 1.5}, {"effects": ROBOT}) is None


def test_a_stream_gets_the_voice_changer_at_once():
    sv = livesetup.StreamVoice()
    x = tone()
    assert sv.process(x, SR) is x                       # nothing on: untouched
    sv.set_setup({"effects": ROBOT})
    y = sv.process(x, SR)
    assert y.shape == x.shape and not np.allclose(y, x)  # straight away, no waiting
    sv.stop()
    assert sv.process(x, SR) is x


def test_a_stream_waits_for_its_ai_voice_then_goes_on(monkeypatch):
    sv = livesetup.StreamVoice()
    started = []
    monkeypatch.setattr(sv.ai, "start", lambda module, voice, **kw: started.append(voice))
    sv.set_setup({"ai": BEAR}, module=object())
    assert started == ["bear"] and sv.waiting
    assert not np.any(sv.process(tone(), SR))            # held back while it gets ready
    sv._event({"type": "ready"})
    assert not sv.waiting
    # without the add-on only the voice changer part goes on, with no wait
    sv.set_setup({"effects": ROBOT, "ai": BEAR}, module=None)
    assert not sv.waiting and np.any(sv.process(tone(), SR))


def test_the_engine_puts_it_on_the_sounds_the_radio_and_programs(window):  # noqa: F811
    eng = window.engine
    eng.set_sound_voice({"enabled": True, "effects": ROBOT})
    x = tone(1024)
    y = eng._sound_voice_fx("main", x)
    assert y.shape == x.shape and not np.allclose(y, x)
    sv = eng.radio_voice = livesetup.StreamVoice()
    sv.set_setup({"effects": ROBOT})
    taps = eng.radio_tap = []
    eng.feed_radio(x)
    assert taps and not np.allclose(taps[0], x)          # the radio went through it
    eng.radio_tap = None
    eng.set_apps_setup({"effects": ROBOT})
    eng.add_aux("prog")
    try:
        assert eng._aux_voice["prog"].chain.enabled
    finally:
        eng.remove_aux("prog")
    assert "prog" not in eng._aux_voice
    eng.set_apps_setup(None)


def test_live_controls_lists_the_setups_and_puts_one_on(window, app_dir):  # noqa: F811
    voicesetups.Store().put("Robo", {"fx": "Robot", "effects": ROBOT})
    btn = window.speed_btn
    btn._open()
    try:
        assert set(btn._setup_chips) == {"", "Robo"}       # "No voice" and the setup
        assert btn._setup_chips[""].isChecked()
        btn._setup_chips["Robo"].click()
        assert window.engine.sound_voice["effects"] == ROBOT
        assert btn._setup_chips["Robo"].isChecked() and "Robo" in btn.text()
        btn.reset()                                       # Reset takes it off too
        assert window.engine.sound_voice == {} and btn.setup_name == ""
        radio = window.livesetups.button("radio")
        if radio is not None:
            window.livesetups.pick("radio", "Robo")
            assert window.engine.radio_voice.chain.enabled
            assert "Robo" in radio.text()
    finally:
        btn.pop.close()
        window.livesetups.pick("radio", "")


def test_a_sound_is_made_in_the_ai_voice_first_and_cancel_puts_it_back(
        window, app_dir, monkeypatch, qapp):  # noqa: F811
    voicesetups.Store().put("Bear", {"ai": BEAR})
    monkeypatch.setattr(livesetup, "ai_module", lambda: object())
    monkeypatch.setattr(renderworker, "enabled", False)
    made = []

    def load_sound(meta, cancel=None, progress=None):
        made.append(meta.fx["voice"]["ai"]["id"])
        return (tone() * 32767).astype(np.int16)
    monkeypatch.setattr(library, "load_sound", load_sound)
    live = window.livesetups
    asked = []
    monkeypatch.setattr(live, "ask", lambda tab, name, lang=None: asked.append(name) or False)
    live.pick("sounds", "Bear")                    # "this may take a while": No
    assert asked == ["Bear"] and live.names["sounds"] == "" and live._ai is None
    monkeypatch.setattr(live, "ask", lambda tab, name, lang=None: asked.append(name) or True)
    live.pick("sounds", "Bear")                    # Yes
    assert live.names["sounds"] == "Bear"
    sid = window.cfg.sounds[0].id
    window.audio.setdefault(sid, (tone() * 32767).astype(np.int16))
    assert live.for_play(sid, window.audio[sid]) is None   # made first, then played
    for _ in range(200):
        qapp.processEvents()
        if live._job is None and not live._jobs:
            break
    assert made == ["bear"]
    assert any("ready to play" in t.text() for t in toast.shown(window))
    assert live.for_play(sid, window.audio[sid]) is not None   # ready now: plays at once
    # Cancel while a setup's AI voice was being made: the one before comes back
    live._before["sounds"], live._from_pick = "", True
    live.cancel("sounds")
    assert live.names["sounds"] == "" and live._ai is None



# ---------------------------------------------------------------- a setup's language
LIVE = Path(__file__).resolve().parent.parent / "modules" / "live-voice"


class FakeTTS:
    """A computer voice: each line is a 0.2 s tone."""

    def __init__(self):
        self.said = []

    def synth(self, text, voice="", rate=0):
        self.said.append((text, voice))
        return tone(int(0.2 * 16000))[:, 0].copy(), 16000


def fake_lang(tts=None):
    """German, heard by the real live-voice helper in its test mode (no model: each
    line it hears is "utterance N (…s)")."""
    module = SimpleNamespace(id="live-voice", name="Live voice", path=LIVE,
                             resolved_command=lambda extra: [
                                 sys.executable, str(LIVE / "helper.py"), "--fake", *extra])
    return livesetup.Lang("de", "German", module, (), "", tts or FakeTTS())


def talk(plan, rate=SR):
    """Noise standing in for speech: (seconds, loud?) pairs, as (n, 2)."""
    rng = np.random.default_rng(0)
    x = np.concatenate([(rng.standard_normal(int(s * rate)) * (0.2 if loud else 0.002))
                        .astype(np.float32) for s, loud in plan])
    return np.stack([x, x], 1)


def wait_for(cond, timeout=30.0):
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        time.sleep(0.02)
    return cond()


def test_a_setup_has_its_language_and_the_helper_hears_any():
    assert livesetup.lang_of({"language": "de"}) == "de" and livesetup.lang_of(None) == ""
    target = SimpleNamespace(id="translate-de", language="de", path=Path("x"))
    args = livesetup.lang_args("base.en", target)
    # a stream or a sound can be in any language: a multilingual model, into English
    assert args[:6] == ["--model", "small", "--language", "auto", "--task", "translate"]
    assert args[6] == "--translate"
    assert livesetup.lang_args("not-ours", target)[1] == "small"


def test_the_helper_hears_a_whole_sound_and_says_when_each_line_starts():
    x = talk([(0.5, False), (1.0, True), (1.0, False), (0.8, True), (0.3, False)])
    seen = []
    lines = livesetup.hear_lines(fake_lang(), x[:, 0], SR, progress=seen.append)
    assert len(lines) == 2                     # the last one ended by the sound's end
    (a, t1), (b, t2) = lines
    assert t1.startswith("utterance 1") and t2.startswith("utterance 2")
    assert 0.1 < a < 0.5 and 2.1 < b < 2.5     # where each was said (with its preroll)
    assert seen and seen[-1] == 1.0


def test_a_sound_is_said_again_where_each_line_was(monkeypatch):
    tts = FakeTTS()
    lang = fake_lang(tts)
    monkeypatch.setattr(livesetup, "hear_lines",
                        lambda lang, mono, rate, cancel, progress: [(0.0, "hallo"),
                                                                    (0.1, "welt")])
    x = (tone(SR) * 32767).astype(np.int16)
    y = livesetup.translate_sound(x, lang)
    assert tts.said == [("hallo", ""), ("welt", "")]
    assert y.shape == (SR, 2) and y.dtype == np.float32
    assert np.any(y[:int(0.2 * SR)]) and np.any(y[int(0.2 * SR):int(0.4 * SR)])
    assert not np.any(y[int(0.45 * SR):])      # the second waited for the first
    # nothing said in it: the sound as it is
    monkeypatch.setattr(livesetup, "hear_lines", lambda *a: [])
    assert np.allclose(livesetup.translate_sound(x, lang), x / 32767.0)


def test_a_stream_is_said_in_the_language_in_place_of_itself():
    tts = FakeTTS()
    events = []
    sv = livesetup.StreamVoice(events.append)
    try:
        sv.set_setup({"language": "de"}, lang=fake_lang(tts))
        assert sv.starting == "lang"
        assert wait_for(lambda: sv.starting == "")          # the helper said "ready"
        assert any(e["type"] == "ready" and e["part"] == "language" for e in events)
        block = 480
        x = talk([(1.0, True), (1.0, False)])
        out = [sv.process(x[i:i + block], SR) for i in range(0, len(x), block)]
        assert not np.any(np.concatenate(out))              # the stream itself is muted
        assert wait_for(lambda: bool(tts.said))             # ...and what it said is said
        assert tts.said[0][0].startswith("utterance 1")
        assert wait_for(lambda: np.any(sv.process(np.zeros((block, 2), np.float32), SR)),
                        5)                                  # in its place
        sv.set_setup(None)
        assert sv.process(x[:block], SR) is x[:block] or not sv.chain.replace
        assert sv.chain.tap is None and not sv.chain.replace    # off: the stream again
    finally:
        sv.shutdown()


def test_live_controls_asks_before_a_language_and_names_it(window, app_dir):  # noqa: F811
    live = window.livesetups
    lang = fake_lang()
    for tab, words in (("sounds", "put into German"), ("radio", "radio goes quiet"),
                       ("apps", "programs go quiet")):
        box = live.ask_box(tab, "Berlin", lang)
        assert "German" in box.text() and words in box.text()
        assert box.windowTitle() == "Use “Berlin”?"
        box.deleteLater()


def test_a_language_without_its_download_says_so(window, app_dir, monkeypatch):  # noqa: F811
    voicesetups.Store().put("Berlin", {"effects": ROBOT, "language": "de"})
    live = window.livesetups
    monkeypatch.setattr(live, "lang_for", lambda setup: (None, "German" if setup else ""))
    asked = []
    monkeypatch.setattr(live, "ask", lambda *a: asked.append(a) or True)
    live.pick("sounds", "Berlin")             # nothing slow left: no question
    assert not asked and live.names["sounds"] == "Berlin" and live._lang is None
    assert window.engine.sound_voice["effects"] == ROBOT     # the rest of it is on
    assert any("German" in t.text() for t in toast.shown(window))
    live.pick("sounds", "")


def test_a_sound_is_made_in_the_language_first(window, app_dir, monkeypatch,  # noqa: F811
                                               qapp):
    voicesetups.Store().put("Berlin", {"language": "de"})
    lang = fake_lang()
    live = window.livesetups
    monkeypatch.setattr(live, "lang_for", lambda setup: (lang, "German") if setup else (None, ""))
    asked = []
    monkeypatch.setattr(live, "ask", lambda tab, name, lang=None: asked.append(lang) or True)
    made = []

    def translate(audio, lang, ai, cancel, progress):
        progress(0.5)
        made.append(lang.code)
        return tone(SR)
    monkeypatch.setattr(livesetup, "translate_sound", translate)
    monkeypatch.setattr(library, "load_sound",
                        lambda meta, cancel=None, progress=None:
                        (tone() * 32767).astype(np.int16))
    live.pick("sounds", "Berlin")
    assert asked == [lang] and live._lang is lang
    sid = window.cfg.sounds[0].id
    window.audio.setdefault(sid, (tone() * 32767).astype(np.int16))
    assert live.for_play(sid, window.audio[sid]) is None   # made first, then played
    for _ in range(200):
        qapp.processEvents()
        if live._job is None and not live._jobs:
            break
    assert made == ["de"]
    assert any("ready to play" in t.text() for t in toast.shown(window))
    got = live.for_play(sid, window.audio[sid])
    assert got is not None and len(got) == SR and got.dtype == np.int16
    live.pick("sounds", "")
    assert live._lang is None and live.for_play(sid, window.audio[sid]) is window.audio[sid]


def test_a_stream_says_its_translation_is_starting(window, app_dir, monkeypatch):  # noqa: F811
    voicesetups.Store().put("Berlin", {"language": "de"})
    live = window.livesetups
    lang = fake_lang()
    monkeypatch.setattr(live, "lang_for", lambda setup: (lang, "German") if setup else (None, ""))
    monkeypatch.setattr(live, "ask", lambda *a: True)
    got = []

    def set_lang(self, lang, ai_on):
        got.append(lang)
        self.lang_waiting = lang is not None
    monkeypatch.setattr(livesetup.StreamVoice, "_set_lang", set_lang)
    live.pick("radio", "Berlin")
    try:
        assert got == [lang] and live._waiting("radio") == "lang"
        radio = live.button("radio")
        if radio is not None:
            assert radio.busy_text.text() == "Starting the translation…"
        live._on_event("radio", {"type": "error", "text": "no model", "part": "language"})
        assert any("Couldn't translate" in t.text() for t in toast.shown(window))
    finally:
        live.pick("radio", "")


def test_a_setups_language_runs_with_the_voice_tabs_downloads(window, app_dir):  # noqa: F811
    live = window.livesetups
    speech = window.voice.speech
    de = SimpleNamespace(id="translate-de", language="de", language_name="German",
                         installed=False, path=Path("x"))
    old = speech.langs, speech.module
    speech.langs, speech.module = [de], SimpleNamespace(installed=True, id="live-voice")
    try:
        assert live.lang_for({"effects": ROBOT}) == (None, "")
        lang, name = live.lang_for({"language": "de"})
        assert lang is None and name                   # not downloaded: named, not run
        de.installed = True
        lang, name = live.lang_for({"language": "de"})
        assert lang is not None and lang.code == "de" and lang.module is speech.module
        assert "--translate" in lang.args and lang.tts is speech.ctl.tts
        assert live.lang_for({"language": "fr"})[0] is None    # no such download
    finally:
        speech.langs, speech.module = old
