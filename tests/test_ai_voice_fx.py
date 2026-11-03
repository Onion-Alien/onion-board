"""An AI voice's own Edit voice: the full window, its effects kept per AI voice and run on
the AI voice's audio before the voice changer's."""
import numpy as np

from soundboard import voicefx
from soundboard.ui.voice import aivoicefx

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
