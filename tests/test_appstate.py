"""Meters that keep running behind a game tick less often there (ui/appstate.py)."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget

from soundboard.ui import appstate


def test_a_running_timer_slows_down_behind_a_game_and_back(qapp, monkeypatch):
    w = QWidget()
    t = QTimer(w)
    appstate.slow_in_background(w, t, 50)
    front = [True]
    monkeypatch.setattr(appstate, "active", lambda: front[0])
    t.start(appstate.interval(50))
    assert t.interval() == 50
    front[0] = False
    qapp.applicationStateChanged.emit(Qt.ApplicationInactive)
    assert t.interval() == appstate.BG_METER_MS and t.isActive()
    front[0] = True
    qapp.applicationStateChanged.emit(Qt.ApplicationActive)
    assert t.interval() == 50
    t.stop()
    front[0] = False
    qapp.applicationStateChanged.emit(Qt.ApplicationInactive)
    assert not t.isActive()   # a stopped timer stays stopped
