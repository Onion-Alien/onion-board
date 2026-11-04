"""Edit voice's Test voice (your changed voice in your headphones, your mic silent for
others), its on/off switch, and Make your own voice staying on only if it's saved."""
import numpy as np
import pytest

from soundboard.audio.engine import SR, Engine
from soundboard.ui.voice.voicefxpanel import CUSTOM, VoiceFxPanel
from soundboard.voicefx import VoiceChain

BLOCK = 480


def engine() -> Engine:
    e = Engine()
    e.dest, e.limiter_on, e.send_mono = None, False, False   # no shaping, exact samples
    e.duck_db = 0.0
    e.main_stream = object()
    e.names["main"] = "fake main"
    return e


def sent(e: Engine, mic: float) -> float:
    """What the last of a few blocks sends out, with the mic at `mic`."""
    out = np.zeros((BLOCK, 2), np.float32)
    for _ in range(6):   # past every glide
        e.ring_main.write(np.full((BLOCK, 2), mic, np.float32))
        e._main(out, BLOCK)
    return float(np.abs(out).max())


def heard(e: Engine, mic: float) -> float:
    """The loudest sample of the last of a few blocks in your headphones."""
    out = np.zeros((BLOCK, 2), np.float32)
    for _ in range(12):   # past every glide and the path fade
        e.ring_mon.write(np.full((BLOCK, 2), mic, np.float32))
        e._mon(out, BLOCK)
    return float(np.abs(out).max())


def test_nobody_hears_your_mic_while_testing_but_you_do():
    e = engine()
    e.mic_vol = 1.0
    assert sent(e, 0.5) > 0.4
    e.voice_test = True
    assert sent(e, 0.5) < 1e-3
    assert heard(e, 0.5) > 0.2
    e.voice_test = False
    assert sent(e, 0.5) > 0.4


def test_your_sounds_still_go_out_while_testing():
    e = engine()
    e.mic_vol = 1.0
    e.play("song", np.full((SR, 2), 0.25, np.float32), 1.0, loop=True)
    e.voice_test = True
    assert abs(sent(e, 0.5) - 0.25) < 0.05   # the sound alone, no mic on top


@pytest.mark.parametrize("off", ["sending", "mic_enabled"])
def test_you_hear_it_with_your_mic_not_going_out_too(off):
    """Others hear off, Send my mic off: testing doesn't need either, and sends nothing."""
    e = engine()
    e.mic_vol = 1.0
    setattr(e, off, False)
    e.voice_test = True
    assert heard(e, 0.5) > 0.2
    assert sent(e, 0.5) < 1e-3


def test_the_real_mic_is_silenced_when_it_goes_straight_into_the_mic():
    e = engine()
    gains = []

    class Direct:
        def set_mic_gain(self, g):
            gains.append(g)

    e.direct_stream = lambda: Direct()
    e._direct_mic_gain()
    e.voice_test = True
    e._direct_mic_gain()
    assert gains[0] > 0 and gains[1] == 0


def test_mic_block_reaches_headphones_only_while_listening():
    e = engine()
    e.mon_stream = object()
    e.names["mon"] = "fake mon"
    e.ring_mon.prefill = 0
    block = np.full((BLOCK, 2), 0.3, np.float32)
    e._mic(block)
    assert e.ring_mon.read(BLOCK) is None
    e.voice_test = True
    for _ in range(4):
        e._mic(block)
    assert e.ring_mon.read(BLOCK) is not None


def test_a_squeal_stops_the_test():
    e = engine()
    e.voice_test = True

    class Howling:
        rate = e.rates["mic"]

        def feed(self, _x):
            return True

        def reset(self):
            pass

    e._howl = Howling()
    assert e._howling(np.zeros(BLOCK, np.float32))
    assert not e.voice_test and e.howl_stopped


def demon_on(qapp) -> VoiceFxPanel:
    panel = VoiceFxPanel({"enabled": False, "effects": {}})
    panel.pick("Demon")
    panel.dlg.close()
    assert panel.btn_power.isChecked() and panel.preset == "Demon"
    return panel


def test_make_your_own_voice_is_on_only_while_it_is_open(qapp):
    panel = VoiceFxPanel({"enabled": False, "effects": {}})
    panel._tile_clicked(CUSTOM)
    assert panel.dlg.isVisible() and panel.btn_power.isChecked()
    assert panel.spec()["enabled"]
    panel.rows["pitch"].load({"on": True, "semitones": -7})
    panel._edited("pitch")
    panel.dlg.close()
    assert not panel.btn_power.isChecked() and not panel.spec()["enabled"]
    # what you made is still there for next time
    panel._tile_clicked(CUSTOM)
    assert panel.rows["pitch"].state()["semitones"] == -7
    panel.dlg.close()
    assert not panel.spec()["enabled"]


def test_closing_it_puts_the_voice_you_had_back(qapp):
    panel = demon_on(qapp)
    demon = panel.rows["pitch"].state()
    panel._tile_clicked(CUSTOM)
    assert panel.preset == CUSTOM
    panel.rows["pitch"].load({"on": True, "semitones": 7})
    panel._edited("pitch")
    panel.dlg.close()
    assert panel.preset == "Demon" and panel.btn_power.isChecked()
    assert panel.rows["pitch"].state() == demon
    assert panel.spec()["custom"]["pitch"]["semitones"] == 7


def test_saving_it_keeps_it_on(qapp, monkeypatch, tmp_path):
    panel = VoiceFxPanel({"enabled": False, "effects": {}})
    monkeypatch.setattr(panel.store, "put", lambda name, _fx: name)
    monkeypatch.setattr(panel, "_fill_saved", lambda: None)
    monkeypatch.setattr(panel, "_ask_name", lambda *a, **k: "Mine")
    panel._tile_clicked(CUSTOM)
    panel.save_voice()
    panel.dlg.close()
    assert panel.btn_power.isChecked() and panel.preset == "Mine"


def test_picking_a_voice_while_it_is_open_keeps_that_voice(qapp):
    panel = VoiceFxPanel({"enabled": False, "effects": {}})
    panel._tile_clicked(CUSTOM)
    panel._tile_clicked("Demon")
    panel.dlg.close()
    assert panel.btn_power.isChecked() and panel.preset == "Demon"


def test_the_switch_in_edit_voice_is_the_voice_changers_switch(qapp):
    panel = VoiceFxPanel({"enabled": False, "effects": {}})
    panel._tile_clicked(CUSTOM)
    assert panel.dlg_power.isChecked()
    panel.dlg_power.setChecked(False)
    assert not panel.btn_power.isChecked() and not panel.spec()["enabled"]
    panel.btn_power.setChecked(True)
    assert panel.dlg_power.isChecked()
    panel.dlg.close()


def test_turning_it_off_inside_stays_off_after_closing(qapp):
    panel = demon_on(qapp)
    panel._tile_clicked(CUSTOM)
    panel.dlg_power.setChecked(False)
    panel.dlg.close()
    assert not panel.btn_power.isChecked() and panel.preset == "Demon"


def test_testing_runs_the_voice_on_screen_without_saving_it_on(qapp):
    panel = VoiceFxPanel({"enabled": False, "effects": {}})
    panel.edit_voice("Demon")   # shown, not on
    assert not panel.spec()["enabled"] and not panel.chain_spec()["enabled"]
    asked = []
    panel.test_asked.connect(asked.append)
    panel.btn_test.setChecked(True)
    assert panel.chain_spec()["enabled"] and panel.chain_spec()["preset"] == "Demon"
    assert not panel.spec()["enabled"]   # what the settings keep
    panel.dlg.close()
    assert asked == [True, False] and not panel.btn_test.isChecked()
    assert not panel.chain_spec()["enabled"]


def test_the_chain_really_changes_the_voice_while_testing(qapp):
    panel = VoiceFxPanel({"enabled": False, "effects": {}})
    panel.edit_voice("Demon")
    chain = VoiceChain()
    chain.configure(panel.chain_spec())
    assert not chain.enabled
    panel.btn_test.setChecked(True)
    chain.configure(panel.chain_spec())
    assert chain.enabled
    panel.dlg.close()
