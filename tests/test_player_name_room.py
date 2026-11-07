"""The player row asks for the same room whatever the sound is called."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication
from test_mainwindow import window  # noqa: F401

SHORT, LONG = "Bot tone", "A really rather long sound name for this row"


def _settle():
    for _ in range(4):
        QApplication.processEvents()


def _fit_for(w, name: str, width: int):
    w._set_np_name(name)
    w.resize(width, 760)
    _settle()
    w.fitctl._fit.reset()
    w.fitctl._refit()
    _settle()
    return set(w.fitctl._fit.applied()), w.chk_monitor.isVisible()


def test_a_long_name_never_takes_the_hear_it_myself_box(window):  # noqa: F811
    w = window
    w.tabs.setCurrentWidget(w.sounds_page)
    w._set_np_time("0:03 / 3:21")
    w.show()
    _settle()
    for width in range(900, 1140, 20):
        short = _fit_for(w, SHORT, width)
        long = _fit_for(w, LONG, width)
        assert long == short, width
    assert LONG in w.np_name.toolTip()   # cut on the row, whole in the tooltip


def test_the_name_is_cut_before_the_slider_gets_short(window):  # noqa: F811
    ns = window._name_seek
    window.tabs.setCurrentWidget(window.sounds_page)
    window.show()
    window._set_np_name(LONG)
    ns.resize(ns.minimumSizeHint().width(), ns.height())
    _settle()
    assert window.seek.width() >= ns.SEEK_MIN
    assert window.np_name.text() != LONG and window.np_name.text().endswith("…")


def test_the_time_showing_up_leaves_the_name_its_room(window):  # noqa: F811
    w = window
    ns = w._name_seek
    w.tabs.setCurrentWidget(w.sounds_page)
    w.show()
    for width in range(900, 1140, 20):
        w._set_np_time("")
        w._set_np_name("Pick a sound")
        w.resize(width, 760)
        _settle()
        w.fitctl._fit.reset()
        w.fitctl._refit()
        _settle()
        w._set_np_name(LONG)
        w._set_np_time("0:03 / 3:21")   # the first pad press, no resize behind it
        _settle()
        assert w.np_name.width() >= ns.NAME_MIN, width
        assert w.seek.width() >= ns.SEEK_MIN - ns.pad_right, width
