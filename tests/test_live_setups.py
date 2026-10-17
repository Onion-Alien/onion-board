"""My setups in Live controls (ui.livesetups, soundboard.livesetup): a voice setup on
every sound, the radio or the programs the Apps tab sends. The voice changer part is on
at once; an AI voice is made first (sounds) or started first (streams), with a Cancel."""
import numpy as np
from test_mainwindow import window  # noqa: F401  (the real MainWindow)

from soundboard import library, livesetup, renderworker, voicesetups
from soundboard.library import SR

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
    live.pick("sounds", "Bear")
    assert live.names["sounds"] == "Bear"
    sid = window.cfg.sounds[0].id
    window.audio.setdefault(sid, (tone() * 32767).astype(np.int16))
    assert live.for_play(sid, window.audio[sid]) is None   # made first, then played
    for _ in range(200):
        qapp.processEvents()
        if live._job is None and not live._jobs:
            break
    assert made == ["bear"]
    assert live.for_play(sid, window.audio[sid]) is not None   # ready now: plays at once
    # Cancel while a setup's AI voice was being made: the one before comes back
    live._before["sounds"], live._from_pick = "", True
    live.cancel("sounds")
    assert live.names["sounds"] == "" and live._ai is None
