from test_mainwindow import window  # noqa: F401

from soundboard.library import Config


def test_background_tracks_first_active_sound(window):  # noqa: F811
    w = window
    w.meta("s0").image = "first.jpg"
    w.meta("s1").image = "second.jpg"
    playing = {"s0": (0.2, False), "s1": (0.4, True)}
    w._update_playing_background(playing)
    assert w.grid.background_image == ""
    w.cfg.playing_background = True
    w.select("s1")
    w._update_playing_background(playing)
    assert w.grid.background_image == "first.jpg"
    w._update_playing_background({"s0": (0.2, True)})
    assert w.grid.background_image == "first.jpg"
    w._update_playing_background({"s1": (0.4, False)})
    assert w.grid.background_image == "second.jpg"
    w.meta("s1").image = ""
    w._update_playing_background({"s1": (0.4, False)})
    assert w.grid.background_image == ""
    w._queue = ["s0"]
    w._update_playing_background({})
    assert w.grid.background_image == ""


def test_settings_apply_immediately_and_persist(window, monkeypatch):  # noqa: F811
    w = window
    w.meta("s0").image = "first.jpg"
    monkeypatch.setattr(w.engine, "playing", lambda: {"s0": (0.2, True)})
    w.open_settings("appearance")
    settings = w._settings_dlg
    assert not settings.playing_background_check.isChecked()
    assert not settings.playing_background_opacity.isEnabled()
    settings.playing_background_check.setChecked(True)
    settings.playing_background_opacity.setValue(45)
    assert (w.grid.background_image, w.grid.background_opacity) == ("first.jpg", 45)
    w.cfg.save()
    loaded = Config.load()
    assert loaded.playing_background and loaded.playing_background_opacity == 45
    settings.playing_background_check.setChecked(False)
    assert w.grid.background_image == ""
