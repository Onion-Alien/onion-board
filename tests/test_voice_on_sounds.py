"""Edit sound → Effects → Voice: a voice from the Voice tab laid over a sound."""
from test_mainwindow import window  # noqa: F401  (the real MainWindow)

from soundboard import soundfx, voicefx
from soundboard.ui.dialogs import EffectsPanel

ROBOT = {"robot": {"on": True, "freq": 100, "noise": 0.2, "mix": 1}}
SAVED = {"echo": {"on": True, "delay": 200, "feedback": 0.3, "mix": 0.3}}


def voices():
    return [("Robot", "Robot", ROBOT), ("My echo", "My echo", SAVED)]


def test_picking_a_voice_keeps_a_copy_of_it_with_the_sound(qapp):
    p = EffectsPanel({}, None, voices)
    assert p.voice.currentIndex() == 0 and p.fx() == {}          # no voice: untouched
    p.voice.setCurrentIndex(p.voice.findText("My echo"))
    f = p.fx()
    assert f["voice"]["name"] == "My echo" and f["voice"]["effects"]["echo"]["on"]
    p.preset.setCurrentIndex(p.preset.findData("Nightcore"))      # a preset keeps the voice
    f = p.fx()
    assert f["speed"] == 1.25 and f["voice"]["name"] == "My echo"
    p.voice.setCurrentIndex(0)
    assert "voice" not in p.fx() or not p.fx()["voice"]


def test_a_sounds_voice_deleted_since_still_shows_and_plays(qapp):
    gone = {"voice": {"name": "Old one", "effects": SAVED}}
    p = EffectsPanel(gone, None, voices)
    assert p.voice.currentText() == "Old one"
    assert p.fx()["voice"] == soundfx.clean_voice(gone["voice"])


def test_the_voice_list_has_every_built_in_voice_and_the_saved_ones(window):  # noqa: F811
    names = [n for n, _s, _e in window.editctl.voice_choices()]
    assert names[:len(voicefx.PRESETS)] == list(voicefx.PRESETS)
    robot = dict((n, e) for n, _s, e in window.editctl.voice_choices())["Robot"]
    assert all(cfg["on"] for cfg in robot.values())
    if window.tabctl.tab_on("voice"):
        window.voice.fx.store.voices["Zz test voice"] = SAVED
        try:
            assert "Zz test voice" in [n for n, _s, _e in window.editctl.voice_choices()]
        finally:
            del window.voice.fx.store.voices["Zz test voice"]
