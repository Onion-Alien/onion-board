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
    p.fx.cb_preset.setCurrentText("Robot")
    spec = seen[-1]
    assert spec["enabled"] and spec["preset"] == "Robot"
    assert spec["effects"]["robot"]["on"] and not spec["effects"]["pitch"]["on"]
    p.chain.process(np.zeros((32, 2), np.float32), 48000)
    assert [e.type for e in p.chain._effects] == ["robot", "reverb"]


def test_editing_a_slider_switches_to_custom(panel):
    p, _ = panel
    p.fx.cb_preset.setCurrentText("Chipmunk")
    row = p.fx.rows["pitch"]
    row.sliders[0].slider.setValue(row.sliders[0].slider.value() - 3)
    assert p.fx.cb_preset.currentText() == "Custom"
    assert p.fx.spec()["effects"]["pitch"]["semitones"] == 5


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
