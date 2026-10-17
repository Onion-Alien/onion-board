"""Muted for over a minute: the On Air card gets a yellow ring and says how long, so a
forgotten mute isn't taken for a broken app. Live again: both go."""
from PySide6.QtWidgets import QPushButton

from soundboard.ui import sidebar


def test_long_mute_shows_ring_and_time(qapp, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(sidebar.time, "monotonic", lambda: now[0])
    power, connection = QPushButton(), QPushButton()
    power.setCheckable(True)
    power.setChecked(True)
    out = sidebar.OutputBlock(power, connection)
    out.set_expanded(False)
    power.setChecked(False)
    assert out.muted_for() == ""   # just muted: nothing yet
    assert out._muted_clock.isActive()
    now[0] += 59
    out._muted_tick()
    assert out.muted_for() == ""
    now[0] += 2
    out._muted_tick()
    assert out.muted_for() == "1 min"
    assert out.caption.text() == "Muted\n1 min"
    now[0] += 120
    out._muted_tick()
    assert out.caption.text() == "Muted\n3 min"
    power.setChecked(True)
    assert out.muted_for() == ""
    assert out.caption.text() == "Live"
    assert not out._muted_clock.isActive()
