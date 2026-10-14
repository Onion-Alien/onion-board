from test_mainwindow import window  # noqa: F401

from soundboard.library import Config, SoundMeta
from PySide6.QtCore import QRectF, QSize
import pytest


@pytest.mark.parametrize("size", [QSize(100, 100), QSize(480, 270), QSize(100, 300)])
def test_background_stretches_whole_thumbnail_with_padding(window, size):  # noqa: F811
    w = window
    w.tabs.setCurrentWidget(w.sounds_page)
    w.cfg.playing_background = True
    w.transctl._update_playing_background({})
    w.resize(1180, 720)
    w.show()
    w.grid.relayout(force=True)
    view = w.grid.parentWidget()
    target = w.grid.background_rect(size)
    assert target.left() == pytest.approx(0)
    assert target.right() == pytest.approx(view.width())
    assert target.top() + w.grid.y() == pytest.approx(0)
    assert target.bottom() + w.grid.y() == pytest.approx(view.height())
    assert w._pad_scroll.viewportMargins().right() == 12
    for pad in w.grid.pads:
        assert pad.x() >= target.left()
        assert pad.x() + pad.width() <= target.right()


@pytest.mark.parametrize("size", [(1180, 720), (800, 600), (440, 720)])
def test_background_board_scrolls_without_partial_rows(
        window, qapp, monkeypatch, size):  # noqa: F811
    w = window
    for n in range(2, 24):
        w.cfg.sounds.append(SoundMeta(id=f"s{n}", name="Sound", file=w.meta("s0").file))
    w._rebuild_pads()
    w.meta("s0").image = "first.jpg"
    playing = {"s0": (0.2, True)}
    monkeypatch.setattr(w.engine, "playing", lambda: playing)
    w.cfg.playing_background = True
    w.tabs.setCurrentWidget(w.sounds_page)
    w.resize(*size)
    w.show()
    w._pad_scroll.verticalScrollBar().setValue(31)
    w.transctl._update_playing_background(playing)
    qapp.processEvents()
    w.transctl._update_playing_background(playing)
    qapp.processEvents()
    bar = w._pad_scroll.verticalScrollBar()
    assert w._pad_scroll.viewportMargins().bottom() == 0
    for value in (0, 31, 120, bar.maximum()):
        bar.setValue(value)
        qapp.processEvents()
        view = w.grid.parentWidget()
        visible = QRectF(0, -w.grid.y(), view.width(), view.height())
        for pad in w.grid.pads:
            rect = QRectF(pad.geometry())
            if visible.intersects(rect):
                assert visible.contains(rect), (value, rect, visible)


def test_background_tracks_first_active_sound(window):  # noqa: F811
    w = window
    w.meta("s0").image = "first.jpg"
    w.meta("s1").image = "second.jpg"
    playing = {"s0": (0.2, False), "s1": (0.4, True)}
    w.transctl._update_playing_background(playing)
    assert w.grid.background_image == ""
    w.cfg.playing_background = True
    w.playctl.select("s1")
    w.transctl._update_playing_background(playing)
    assert w.grid.background_image == "first.jpg"
    w.transctl._update_playing_background({"s0": (0.2, True)})
    assert w.grid.background_image == "first.jpg"
    w.transctl._update_playing_background({"s1": (0.4, False)})
    assert w.grid.background_image == "second.jpg"
    w.meta("s1").image = ""
    w.transctl._update_playing_background({"s1": (0.4, False)})
    assert w.grid.background_image == ""
    w.playctl._queue = ["s0"]
    w.transctl._update_playing_background({})
    assert w.grid.background_image == ""


def test_settings_apply_immediately_and_persist(window, monkeypatch):  # noqa: F811
    w = window
    w.meta("s0").image = "first.jpg"
    monkeypatch.setattr(w.engine, "playing", lambda: {"s0": (0.2, True)})
    w.setctl.open_settings("appearance")
    settings = w.setctl._settings_dlg
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
