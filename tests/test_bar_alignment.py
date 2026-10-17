"""Matching playback and output bars must never change the mixer's layout."""
from PySide6.QtCore import QPoint
from PySide6.QtTest import QTest

from test_mainwindow import window  # noqa: F401


def test_meter_at_minimum_does_not_start_a_spacing_cycle(window, qapp):  # noqa: F811
    w = window
    w.resize(1180, 720)
    w.tabs.setCurrentWidget(w.sounds_page)
    w.show()
    qapp.processEvents()
    meter = w.out_meter
    meter.hide()
    w._bar_edges.match()
    meter.show()
    meter.setMinimumWidth(meter.width())
    # The seek end is just short of a meter that cannot give up any more width.
    end = meter.mapTo(w, QPoint(meter.width(), 0)).x()
    start = w.seek.mapTo(w, QPoint(0, 0)).x()
    w.seek.resize(end - start - 5, w.seek.height())
    row = w._deck_rows[1]
    before = row.minimumSize().width()
    for _ in range(12):
        w._bar_edges.match()
        assert row.minimumSize().width() == before


def test_seek_alignment_settles_and_survives_playback_stop(window, qapp):  # noqa: F811
    w = window
    w.resize(1180, 720)
    w.tabs.setCurrentWidget(w.sounds_page)
    w.show()
    w.playctl.select("s0")
    w.speed_btn.set_values(1.2, 3, True)
    w.speed_btn.set_fx({"bass": 8})
    w.speed_btn._open()
    try:
        for playing in ({"s0": (0.75, False)}, {}, {"s0": (0.2, False)}, {}):
            w.transctl._update_transport(playing)
            for _ in range(8):
                qapp.processEvents()
            before = tuple((x.x(), x.width()) for x in (w.seek, w.out_meter, w.btn_check))
            for _ in range(12):
                w._bar_edges.match()
                w.transctl._update_transport(playing)
                QTest.qWait(1)
                assert tuple((x.x(), x.width()) for x in
                             (w.seek, w.out_meter, w.btn_check)) == before
    finally:
        w.speed_btn.pop.close()
