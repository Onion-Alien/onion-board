"""Clean mic switches on with a voice (Settings > Audio's "Turn on Clean mic with a
voice", on by default), and off again when every voice goes off, but only when a voice
switched it on: switched on or off by hand, it's yours and stays as it is."""
import pytest

from soundboard.control import remote
from soundboard.sounds.config import Config
from test_mainwindow import window as main_window  # noqa: F401  (the real MainWindow)
from test_voicepanel import ZH, panel  # noqa: F401


def _clean_ready(monkeypatch, p):
    monkeypatch.setattr(p.clean, "ok", True)   # as if RNNoise were there
    monkeypatch.setattr(p.clean, "_apply", lambda: None)
    p.clean.b_on.setEnabled(True)              # (its switch, clickable as with RNNoise)
    p.clean.set_on(False)


@pytest.fixture
def voice(panel, monkeypatch):  # noqa: F811
    p, _eng = panel
    _clean_ready(monkeypatch, p)
    return p


def test_picking_a_voice_turns_clean_mic_on(voice):
    p = voice
    p.fx.pick("Robot")
    assert p.clean.is_on()


def test_the_voice_changers_switch_and_random_voice_turn_it_on(voice):
    p = voice
    p.fx.pick("Robot")
    p.fx.btn_power.setChecked(False)
    p.clean.set_on(False)
    p.fx.btn_power.setChecked(True)
    assert p.clean.is_on()
    p.clean.set_on(False)
    assert p.fx.roll()
    assert p.clean.is_on()


def test_voices_on_and_a_grey_chip_turn_it_on(voice):
    p = voice
    p.fx.pick("Robot")
    p.set_voices(False)
    p.clean.set_on(False)
    p.set_voices(True)
    assert p.on_keys() == ["fx"] and p.clean.is_on()
    p.toggle_one("fx")
    p.clean.set_on(False)
    p.toggle_one("fx")
    assert p.clean.is_on()


def test_an_ai_voice_and_a_language_turn_it_on(voice, monkeypatch):
    p = voice
    on = []
    monkeypatch.setattr(p.ai, "is_on", lambda: bool(on))
    on.append(True)
    p.ai.live_changed.emit(True)
    assert p.clean.is_on()
    p.clean.set_on(False)
    p.ai.s["voice"] = "another"            # another AI voice picked while it's on
    p.ai.changed.emit(dict(p.ai.s))
    assert p.clean.is_on()
    on.clear()
    p.ai.live_changed.emit(False)
    p.clean.set_on(False)
    monkeypatch.setattr(type(p.speech), "translating", lambda self: ZH)
    p.speech.lang_changed.emit()
    assert p.clean.is_on()


def test_switched_off_by_hand_it_stays_off_until_the_next_voice(voice):
    p = voice
    p.fx.pick("Robot")
    p.toggle_one("clean")                  # its bar's pause: off by hand
    assert not p.clean.is_on()
    p.fx._edited("pitch")                  # editing the voice picks none
    p.fx.changed.emit(p.fx.spec())
    assert not p.clean.is_on()
    p.fx.pick("Chipmunk")                  # the next voice: on again
    assert p.clean.is_on()


def test_turned_on_by_a_voice_it_goes_off_with_it(voice):
    p = voice
    p.fx.pick("Robot")
    assert p.clean.is_on() and p.clean.by_voice()
    p.fx.pick("Chipmunk")                  # another voice: still a voice on, stays
    assert p.clean.is_on()
    p.fx.btn_power.setChecked(False)       # the voice off: Clean mic off with it
    assert not p.clean.is_on()


@pytest.mark.parametrize("how", ["switch", "voices", "stop_all", "chip", "forget", "reset"])
def test_every_way_of_turning_the_voice_off_takes_it_along(voice, how):
    p = voice
    p.fx.pick("Robot")
    {"switch": lambda: p.fx.btn_power.setChecked(False),
     "voices": lambda: p.set_voices(False),
     "stop_all": p.stop_all,
     "chip": lambda: p.toggle_one("fx"),
     "forget": lambda: p.forget_one("fx"),
     "reset": p.reset_voices}[how]()
    assert not p.clean.is_on()


def test_switched_on_by_hand_it_stays_on(voice):
    p = voice
    p.clean.set_on(True)                   # yours, before any voice
    p.fx.pick("Robot")
    p.fx.btn_power.setChecked(False)
    assert p.clean.is_on() and not p.clean.by_voice()


def test_touched_by_hand_after_a_voice_it_is_yours(voice):
    """A voice turned it on; you switched it off and on again yourself: it's yours."""
    p = voice
    p.fx.pick("Robot")
    p.clean.b_on.click()
    p.clean.b_on.click()
    assert p.clean.is_on() and not p.clean.by_voice()
    p.fx.btn_power.setChecked(False)
    assert p.clean.is_on()


def test_changing_its_strength_keeps_it_the_voices(voice):
    """Only switching it on or off makes it yours, not its settings."""
    p = voice
    p.fx.pick("Robot")
    p.clean._edited({"volume": 120})
    p.fx.btn_power.setChecked(False)
    assert not p.clean.is_on()


def test_one_voice_still_on_keeps_it(voice, monkeypatch):
    p = voice
    on = []
    monkeypatch.setattr(p.ai, "is_on", lambda: bool(on))
    p.fx.pick("Robot")
    on.append(True)
    p.ai.live_changed.emit(True)           # the AI voice on too
    p.fx.btn_power.setChecked(False)       # the voice changer off, the AI voice still on
    assert p.clean.is_on()
    on.clear()
    p.ai.live_changed.emit(False)          # the last voice off
    assert not p.clean.is_on()


def test_voices_on_again_brings_it_back(voice):
    p = voice
    p.fx.pick("Robot")
    p.set_voices(False)
    assert not p.clean.is_on()
    p.set_voices(True)
    assert p.clean.is_on() and p.clean.by_voice()


def test_undo_of_reset_puts_clean_mic_back_too(voice):
    p = voice
    p.fx.pick("Robot")
    p.reset_voices()
    assert not p.clean.is_on()
    p.reset_undo.undo()
    assert p.fx.btn_power.isChecked() and p.clean.is_on() and p.clean.by_voice()


def test_undo_of_reset_leaves_your_own_clean_mic(voice):
    p = voice
    p.clean.set_on(True)                   # yours
    p.fx.pick("Robot")
    p.reset_voices()
    assert p.clean.is_on()                 # reset left it: it's yours
    p.clean.set_on(False)
    p.reset_undo.undo()
    assert not p.clean.is_on()


def test_who_turned_it_on_is_saved():
    from soundboard.voicefx import cleanmic
    assert cleanmic.clean_settings({"on": True, "by_voice": True})["by_voice"] is True
    assert cleanmic.clean_settings({"on": True})["by_voice"] is False      # older settings
    assert cleanmic.clean_settings({"on": False, "by_voice": True})["by_voice"] is False
    assert cleanmic.clean_settings({"on": True, "by_voice": "x"})["by_voice"] is False


def test_after_a_restart_it_still_goes_off_with_the_voice(voice):
    p = voice
    p.fx.pick("Robot")
    assert p.speech.s["clean"]["by_voice"] is True   # what gets saved


def test_with_the_setting_off_nothing_changes(voice):
    p = voice
    p.clean_with_voice = lambda: False
    p.fx.pick("Robot")
    p.fx.roll()
    assert not p.clean.is_on()


def test_a_new_panel_turns_nothing_on(qapp, monkeypatch):
    """The voice changer always starts off: nothing is picked at start-up."""
    from test_voicepanel import FakeEngine
    from soundboard.ui.voice.voicepanel import VoicePanel
    p = VoicePanel(FakeEngine(), {"enabled": True, "preset": "Robot", "effects": {}}, {})
    try:
        assert not p.clean.is_on() and p._voices_seen == {}
    finally:
        p.shutdown()
        p.deleteLater()


def test_hotkeys_tray_and_remote_turn_it_on(main_window, monkeypatch):  # noqa: F811
    w = main_window
    _clean_ready(monkeypatch, w.voice)
    fx = w.voice.fx
    name = sorted(fx.voice_names())[0]
    w.hkctl.on_hotkey("__pickvoice__:" + name)
    assert w.voice.clean.is_on()
    for key in ("__voice__", "__voices__", "__voicerandom__"):
        fx.btn_power.setChecked(False)
        w.voice.clean.set_on(False)
        w.hkctl.on_hotkey(key)
        assert fx.btn_power.isChecked() and w.voice.clean.is_on(), key
    fx.btn_power.setChecked(False)
    w.voice.clean.set_on(False)
    w.hkctl.pick_voice(name)               # the tray's voices
    assert w.voice.clean.is_on()
    w.voice.clean.set_on(False)
    assert remote.dispatch(w, "voice", {"name": "chipmunk"})[0] == 200
    assert w.voice.clean.is_on()
    w.set_option("clean_with_voice", False)
    w.voice.clean.set_on(False)
    remote.dispatch(w, "voice", {"name": "robot"})
    assert not w.voice.clean.is_on()


def test_the_setting_is_on_by_default_and_old_settings_load():
    assert Config().clean_with_voice is True
    assert Config.from_raw({}).clean_with_voice is True          # from before it
    assert Config.from_raw({"clean_with_voice": False}).clean_with_voice is False
    assert Config.from_raw({"clean_with_voice": "x"}).clean_with_voice is True


def test_settings_switch_saves_it(main_window):  # noqa: F811
    from PySide6.QtWidgets import QCheckBox
    w = main_window
    w.setctl.open_settings("audio")
    box = next(c for c in w.findChildren(QCheckBox)
               if c.text() == "Turn on Clean mic with a voice")
    assert box.isChecked()
    box.setChecked(False)
    assert w.cfg.clean_with_voice is False
