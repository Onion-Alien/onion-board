"""An AI voice's own Edit voice: the full window, its effects kept per AI voice and run on
the AI voice's audio before the voice changer's."""
import numpy as np

from soundboard import voicefx
from soundboard.ui.voice import aivoicefx

from test_aivoice import fake_module
from test_mainwindow import window  # noqa: F401


class Louder:
    """A stand-in AI voice: twice as loud, 10 ms behind."""

    def process(self, m, rate):
        return m * 2

    def latency(self):
        return 0.01


def test_ai_voice_effects_run_on_the_ai_voice_before_the_voice_changer():
    chain = voicefx.VoiceChain()
    chain.source = Louder()
    chain.source_fx = voicefx.VoiceChain()
    chain.source_fx.configure({"enabled": True, "effects": {
        "pitch": {**voicefx.defaults("pitch"), "on": True, "semitones": -5.0}}})
    x = np.tile(np.sin(np.arange(1024, dtype=np.float32) / 8)[:, None], (1, 2)) * 0.2
    for _ in range(20):
        y = chain.process(x, 48000)
    assert y.shape == x.shape and np.all(np.isfinite(y))
    assert not chain.errors and not chain.source_fx.errors
    assert chain.latency() > 0.01   # the AI voice's delay and its pitch effect's
    chain.source_fx.configure({})   # none: the AI voice as it is
    assert np.allclose(chain.process(x, 48000), x * 2)


def test_saved_ai_effects_are_cleaned_and_old_settings_load():
    assert aivoicefx.clean_all(None) == {}
    assert aivoicefx.clean_all({"bear": "junk", "": {}, 3: {}}) == {}
    got = aivoicefx.clean_all({"bear": {"pitch": {"on": True, "semitones": -4},
                                        "echo": {"on": False}}})
    assert got == {"bear": {"pitch": {"on": True, "semitones": -4}}}


def test_ai_voice_edit_voice_keeps_each_voices_own_effects(window):  # noqa: F811
    vp = window.voice
    ai = vp.ai
    ai.set_modules([], voices=[{"id": "duke", "name": "Duke"}, {"id": "ivy", "name": "Ivy"}])
    ai.edit_voice("ivy")                         # a card's right-click Edit voice
    ed = vp.ai_edit
    assert ed is not None and ed.dlg.isVisible() and ed.voice_id == "ivy"
    assert ed.dlg_name.text() == "Ivy" and ai.sl_pitch.isVisibleTo(ed.dlg)
    assert "backdrop" not in [t for _title, cards in ed._ordered_cards()
                              for t, r in ed.rows.items() if r in cards]
    ed.rows["pitch"].chk.setChecked(True)        # deeper still
    assert vp.ai_fx["ivy"]["pitch"]["on"] and vp.speech.s["ai_fx"]["ivy"]
    assert vp.chain.source_fx.enabled and ed.dlg_name.text() == "Ivy, changed"
    assert not vp.fx.btn_power.isChecked()       # the voice changer is its own
    assert ai.btn_tweak.text() == "Edit voice  ·  1 on"
    ed.rows["echo"].chk.setChecked(True)
    assert ai.btn_tweak.text() == "Edit voice  ·  2 on"

    ai.pick("duke")                              # another voice: its own (none)
    assert ed.voice_id == "duke" and not any(r.chk.isChecked() for r in ed.rows.values())
    assert not vp.chain.source_fx.enabled and ai.btn_tweak.text() == "Edit voice"
    ai.pick("ivy")                               # and back: Ivy's are still hers
    assert ed.rows["pitch"].chk.isChecked() and ed.rows["echo"].chk.isChecked()
    ed.reset_edits()                             # Reset: Ivy as she is, no effects
    assert "ivy" not in vp.ai_fx and not vp.chain.source_fx.enabled
    ed.dlg.close()
    ai.btn_tweak.click()                         # the bar's Edit voice opens it too
    assert ed.dlg.isVisible() and ed.voice_id == "ivy"
    ed.dlg.close()


def _ai_edit_open(window, monkeypatch):  # noqa: F811
    """Edit voice open on an AI voice that can start, with a mic and headphones."""
    vp = window.voice
    ai = vp.ai
    ai.set_modules([], voices=[{"id": "duke", "name": "Duke"}, {"id": "ivy", "name": "Ivy"}])
    ai.module = fake_module()
    ai.b_start.setEnabled(True)
    monkeypatch.setattr(ai.ctl, "start", lambda *a: None)
    monkeypatch.setattr("soundboard.ui.voice.aivoicepanel.model_downloaded", lambda _m: True)
    vp.engine.mic_stream = vp.engine.mon_stream = object()
    ai.edit_voice("ivy")
    return vp, ai, vp.ai_edit


def test_ai_voice_edit_voice_switch_turns_that_voice_on_and_off(window, monkeypatch):  # noqa: F811
    vp, ai, ed = _ai_edit_open(window, monkeypatch)
    assert ed.dlg_power_box.isVisibleTo(ed.dlg) and ed.dlg_power_label.text() == "AI voices"
    assert not ed.dlg_power.isChecked()
    ed.dlg_power.click()
    assert ai.is_on() and ai.current_voice() == "ivy" and ed.dlg_power.isChecked()
    ed.dlg_power.click()
    assert not ai.is_on() and not ed.dlg_power.isChecked()
    ai.b_start.setChecked(True)                  # switched on its card: it says so here
    assert ed.dlg_power.isChecked()
    assert not vp.fx.btn_power.isChecked()       # the voice changer is its own
    ed.dlg.close()
    assert ai.is_on()                            # closing leaves it as it is
    ai.stop()


def test_ai_voice_test_runs_a_voice_that_is_off_only_for_the_test(window, monkeypatch):  # noqa: F811
    vp, ai, ed = _ai_edit_open(window, monkeypatch)
    ed.btn_test.setChecked(True)
    assert vp.engine.voice_test and ai.is_on()
    assert not ed.dlg_power.isChecked()          # never turned on for real
    ed.btn_test.setChecked(False)
    assert not vp.engine.voice_test and not ai.is_on()
    ed.dlg.close()


def test_ai_voice_that_was_on_stays_on_after_a_test(window, monkeypatch):  # noqa: F811
    vp, ai, ed = _ai_edit_open(window, monkeypatch)
    ed.dlg_power.click()
    ed.btn_test.setChecked(True)
    ed.btn_test.setChecked(False)
    assert ai.is_on() and ed.dlg_power.isChecked()
    ed.btn_test.setChecked(True)
    ed.dlg_power.click()                         # off during the test: off when it ends
    assert ai.is_on() and not ed.dlg_power.isChecked()
    ed.dlg.close()                               # closing the window ends the test
    assert not vp.engine.voice_test and not ai.is_on()


def test_ai_voice_switched_on_during_a_test_stays_on(window, monkeypatch):  # noqa: F811
    _vp, ai, ed = _ai_edit_open(window, monkeypatch)
    ed.btn_test.setChecked(True)
    ed.dlg_power.click()
    assert ed.dlg_power.isChecked()
    ed.btn_test.setChecked(False)
    assert ai.is_on()
    ed.dlg.close()
    ai.stop()


def test_ai_voice_paused_from_its_bar_is_paused_again_after_a_test(window, monkeypatch):  # noqa: F811
    vp, ai, ed = _ai_edit_open(window, monkeypatch)
    ed.dlg_power.click()
    vp.toggle_one("ai")
    assert not ai.is_on() and "ai" in vp._back
    ed.btn_test.setChecked(True)
    assert ai.is_on()
    vp._update_bar()                             # (the voice's own events do this)
    ed.btn_test.setChecked(False)
    assert not ai.is_on() and "ai" in vp._back
    ed.dlg.close()


def test_ai_voice_that_cannot_start_says_why_and_does_not_test(window, monkeypatch):  # noqa: F811
    vp, ai, ed = _ai_edit_open(window, monkeypatch)
    ai.module = None
    ai.b_start.setEnabled(False)
    ai.b_start.setToolTip("Voices are missing")
    ed.btn_test.setChecked(True)
    assert not ed.btn_test.isChecked() and not vp.engine.voice_test and not ai.is_on()
    ed.dlg.close()


def test_a_squeal_stops_an_ai_voice_the_test_started(window, monkeypatch):  # noqa: F811
    vp, ai, ed = _ai_edit_open(window, monkeypatch)
    ed.btn_test.setChecked(True)
    assert vp.stop_voice_test() and not ed.btn_test.isChecked() and not ai.is_on()
    ed.dlg.close()
