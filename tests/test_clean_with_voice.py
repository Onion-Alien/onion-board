"""Clean mic switches on with a voice (Settings > Audio's "Turn on Clean mic with a
voice", on by default): only ever on, and a Clean mic switched off by hand stays off
until the next voice."""
import pytest

from soundboard.control import remote
from soundboard.sounds.config import Config
from test_mainwindow import window as main_window  # noqa: F401  (the real MainWindow)
from test_voicepanel import ZH, panel  # noqa: F401


def _clean_ready(monkeypatch, p):
    monkeypatch.setattr(p.clean, "ok", True)   # as if RNNoise were there
    monkeypatch.setattr(p.clean, "_apply", lambda: None)
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


def test_a_voice_going_off_leaves_clean_mic_alone(voice):
    p = voice
    p.fx.pick("Robot")
    p.fx.btn_power.setChecked(False)
    assert p.clean.is_on()
    p.set_voices(False)
    p.reset_voices()
    assert p.clean.is_on()


def test_undo_of_reset_puts_back_and_turns_nothing_on(voice):
    p = voice
    p.fx.pick("Robot")
    p.reset_voices()
    p.clean.set_on(False)
    p.reset_undo.undo()
    assert p.fx.btn_power.isChecked() and not p.clean.is_on()


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
