"""The Voice panel, offscreen: presets reach the chain, settings round-trip."""
import numpy as np
import pytest

from soundboard import voicefx
from soundboard.speech import tts
from tests.conftest import process_events


class FakeEngine:
    voice_chain = None

    def play(self, *a, **k):
        pass

    def stop(self, sid):
        pass


@pytest.fixture
def panel(qapp, monkeypatch):
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: ["Microsoft Zira Desktop"])
    from soundboard.ui.voicepanel import VoicePanel
    eng = FakeEngine()
    p = VoicePanel(eng, {"enabled": False, "effects": {}},
                   {"voice": "Microsoft Zira Desktop", "rate": 2})
    yield p, eng
    p.shutdown()
    p.deleteLater()


def test_panel_installs_the_chain_on_the_engine(panel):
    p, eng = panel
    assert eng.voice_chain is p.chain
    assert set(voicefx.REGISTRY) <= set(p.fx.rows)       # built-ins and add-ons get rows


def test_preset_turns_the_changer_on_and_configures_the_chain(panel):
    p, _ = panel
    seen = []
    p.fx_changed.connect(seen.append)
    p.fx.pick("Robot")
    spec = seen[-1]
    assert spec["enabled"] and spec["preset"] == "Robot"
    assert spec["effects"]["robot"]["on"] and not spec["effects"]["pitch"]["on"]
    p.chain.process(np.zeros((32, 2), np.float32), 48000)
    assert [e.type for e in p.chain._effects] == ["robot", "reverb"]


def test_editing_a_slider_switches_to_custom(panel):
    p, _ = panel
    p.fx.pick("Chipmunk")
    row = p.fx.rows["pitch"]
    row.sliders[0].slider.setValue(row.sliders[0].slider.value() - 3)
    assert p.fx.preset == "Custom"
    assert p.fx.spec()["effects"]["pitch"]["semitones"] == 5


def test_power_switch_and_hear_button(panel):
    p, _ = panel
    seen, hear = [], []
    p.fx_changed.connect(seen.append)
    p.fx.hear_toggled.connect(hear.append)
    assert not p.fx.btn_power.isChecked() and "OFF" in p.fx.btn_power.text()
    p.fx.pick("Deep voice")                  # picking a voice turns it on
    assert p.fx.btn_power.isChecked() and "ON" in p.fx.btn_power.text()
    assert p.fx._tile["Deep voice"].isChecked()
    p.fx.btn_power.setChecked(False)         # the switch turns it off, voice kept
    assert not seen[-1]["enabled"] and seen[-1]["preset"] == "Deep voice"
    assert not p.fx._tile["Deep voice"].isChecked()   # nothing looks selected while off
    p.fx.btn_hear.setChecked(True)
    assert hear == [True]
    p.fx.set_hearing(False)                  # mirrored from the window: no echo back
    assert hear == [True] and not p.fx.btn_hear.isChecked()


def test_saved_spec_loads_back(qapp, monkeypatch):
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    from soundboard.ui.voicepanel import VoiceFxPanel
    spec = {"enabled": True, "preset": "Custom",
            "effects": {"echo": {"on": True, "delay": 400, "feedback": 0.5, "mix": 0.2}}}
    fx = VoiceFxPanel(spec)
    got = fx.spec()
    assert got["enabled"] and got["effects"]["echo"]["on"]
    assert got["effects"]["echo"]["delay"] == pytest.approx(400)
    assert not got["effects"]["robot"]["on"]


def test_voice_list_arrives_and_selection_is_kept(panel, qapp):
    p, _ = panel
    assert process_events(qapp, lambda: p.speech.cb_voice.isEnabled())
    assert p.speech.cb_voice.currentData() == "Microsoft Zira Desktop"
    assert p.controller.speaker.rate == 2


def test_live_voice_needs_the_addon_set_up(panel):
    p, _ = panel
    # the repo's live-voice module has no .venv in a test checkout -> install hint
    m = p.speech.module
    if m is None or not m.installed:
        assert p.speech.live_box.isHidden() and not p.speech.missing.isHidden()


def test_everything_spoken_lands_in_the_log(panel, monkeypatch):
    p, _ = panel
    s = p.speech
    monkeypatch.setattr(s.ctl, "say", lambda text: None)
    s.ed.setText("typed line")
    s._say()
    s._on_event({"type": "final", "text": "heard line"})
    s._on_event({"type": "final", "text": ""})
    lines = s.said_log.toPlainText().splitlines()
    assert len(lines) == 2
    assert lines[0].endswith("typed line") and lines[1].endswith("heard line")


def test_changer_starts_off_even_if_it_was_left_on(qapp, monkeypatch):
    monkeypatch.setattr(tts.SapiTTS, "warm_up", lambda self: [])
    from soundboard.ui.voicepanel import POWER_TEXT, VoicePanel
    p = VoicePanel(FakeEngine(), {"enabled": True, "preset": "Old telephone", "effects": {}}, {})
    try:
        assert not p.fx.btn_power.isChecked() and not p.chain.enabled
        assert p.fx.btn_power.text() == POWER_TEXT[False]
        assert not any(t.isChecked() for t in p.fx._tile.values())   # nothing looks active
        assert p.fx.preset == "Old telephone"                          # the choice is kept
    finally:
        p.shutdown()
        p.deleteLater()
