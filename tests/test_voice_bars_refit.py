"""Regression tests for coalescing VoicePanel picked-bar polish and room_changed during refit."""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

from soundboard.audio.engine import Engine
from soundboard.ui.voice.voicepanel import VoicePanel


def test_move_bars_round_trip_skips_redundant_polish_and_mid_loop_signals(qapp):
    """When fit() tries unpinning and immediately re-pinning in the same turn,
    _move_bars must not synchronously unpolish/polish every bar twice or emit
    room_changed mid-loop per bar."""
    vp = VoicePanel(Engine(), {}, {})
    vp.show()
    QApplication.processEvents()

    vp.fx.btn_power.setChecked(True)
    QApplication.processEvents()

    polished: list[object] = []
    orig_polish = vp._polish_bars

    def spy_polish():
        before = dict(vp._polished_pinned)
        orig_polish()
        for _k, panel in vp._barred():
            pid = id(panel.picked)
            if vp._polished_pinned.get(pid) != before.get(pid):
                polished.append(panel.picked)

    vp._polish_bars = spy_polish
    vp._polish_timer.timeout.disconnect()
    vp._polish_timer.timeout.connect(spy_polish)

    rooms: list[int] = []
    vp.room_changed.connect(lambda: rooms.append(vp._scroll.minimumHeight()))

    # Simulate fit()'s retry_all() trial (False -> True -> False) in one turn:
    # bars end up back in their original pinned state, so zero re-polishes should run.
    start_pinned = [bool(p.picked.property("pinned")) for _k, p in vp._barred()]
    vp._move_bars(True)
    vp._move_bars(False)
    QApplication.processEvents()
    assert [bool(p.picked.property("pinned")) for _k, p in vp._barred()] == start_pinned
    assert polished == []
    # At most one room_changed per _move_bars call (never once per bar mid-loop).
    assert len(rooms) <= 2

    # When the state actually changes and stays changed, each bar is polished once.
    vp._move_bars(True)
    QApplication.processEvents()
    assert len(polished) == len(vp._barred())

    # While hidden on another tab, polishing is deferred until showEvent.
    polished.clear()
    vp.hide()
    QApplication.processEvents()
    vp._move_bars(False)
    QApplication.processEvents()
    assert polished == []
    vp.show()
    QApplication.processEvents()
    assert len(polished) == len(vp._barred())
    vp.close()
