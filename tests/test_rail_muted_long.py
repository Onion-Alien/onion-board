"""Muted for over a minute: the On Air card gets a yellow ring and says how long, so a
forgotten mute isn't taken for a broken app (the time only on the open rail). Live
again: both go."""
from PySide6.QtWidgets import QPushButton, QWidget

from soundboard.ui.window import sidebar


def test_long_mute_shows_ring_and_time(qapp, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(sidebar.time, "monotonic", lambda: now[0])
    power, connection = QPushButton(), QPushButton()
    power.setCheckable(True)
    power.setChecked(True)
    host = QWidget()
    host.resize(60, 200)
    out = sidebar.OutputBlock(power, connection)
    out.setParent(host)
    host.show()
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
    assert out.caption.text() == "Muted"   # shut: the ring alone
    now[0] += 120
    out._muted_tick()
    assert out.muted_for() == "3 min"
    # drawn over the card (its switch), not under it
    assert out._ring.isVisible() and out._ring.parentWidget() is host
    power.setChecked(True)
    assert out.muted_for() == ""
    assert out.caption.text() == "On"
    assert not out._muted_clock.isActive()
    assert not out._ring.isVisible()
    host.close()
