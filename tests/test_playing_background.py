from test_mainwindow import window  # noqa: F401

from soundboard.library import Config
from PySide6.QtCore import QSize
import pytest


@pytest.mark.parametrize("size", [QSize(100, 100), QSize(480, 270), QSize(100, 300)])
def test_background_fits_whole_thumbnail_with_padding(window, size):  # noqa: F811
    w = window
    w.tabs.setCurrentWidget(w.sounds_page)
    w.resize(1180, 720)
    w.show()
    w.grid.relayout(force=True)
    view = w.grid.parentWidget()
    target = w.grid.background_rect(size)
    assert target.width() / target.height() == pytest.approx(size.width() / size.height())
    assert target.left() >= 12 - 1e-6
    assert target.right() <= view.width() - 12 + 1e-6
    assert target.top() + w.grid.y() >= 12 - 1e-6
    assert target.bottom() + w.grid.y() <= view.height() - 12 + 1e-6


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
