"""Send feedback's Bun (ui/bun/notebun.py): the same room round him on every side of his
corner, and his timer only running while something moves."""
from types import SimpleNamespace

from PySide6.QtCore import QPoint

from soundboard.core import usage
from soundboard.ui.bun import notebun
from soundboard.ui.kit import feedbackdialog


def test_bun_has_the_same_room_on_every_side(qapp):
    d = feedbackdialog.FeedbackDialog(SimpleNamespace())
    d.show()
    qapp.processEvents()
    bun = d.bun.geometry()
    room = feedbackdialog.BUN_ROOM
    first = d.boxes["sounds"].mapTo(d, QPoint(0, 0))
    assert (bun.left(), bun.top()) == (room, room)
    assert d.heading.mapTo(d, QPoint(0, 0)).x() - (bun.right() + 1) == room
    assert first.y() - (bun.bottom() + 1) == room
    assert first.x() == 18   # the picks stay on the dialog's 18 px margin
    d.deleteLater()


def test_his_box_is_just_him(qapp):
    box = notebun.fit()
    assert 0 < box.width() <= notebun.W + 4 * notebun.ROOM_SIDE
    bun = notebun.NoteBunny()
    assert bun.width() == round(box.width() * notebun.SCALE)
    bun.deleteLater()


def test_he_writes_then_bows_and_his_timer_stops(qapp, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(notebun.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(usage, "improve", lambda *a, **k: True)
    d = feedbackdialog.FeedbackDialog(SimpleNamespace())
    d.bun._blink_at = 1e12
    d.show()
    d.boxes["sounds"].click()
    assert d.bun.writing() and d.bun._timer.isActive()
    d.send_btn.click()
    assert d.bun.sent and not d.bun.writing()
    for _ in range(int((notebun.HEART_AT + notebun.HEART_S) * 30) + 5):
        clock[0] += 1 / 30
        d.bun._tick()
    assert not d.bun._timer.isActive()   # sitting still: nothing ticks
    d.deleteLater()
