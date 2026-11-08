"""Send feedback's Bun (ui/bun/notebun.py): a card's mascot in its header, and his timer
only running while something moves."""
from types import SimpleNamespace

from PySide6.QtCore import QPoint

from soundboard.core import usage
from soundboard.ui.bun import notebun
from soundboard.ui.kit import feedbackdialog


def test_bun_is_the_cards_mascot_and_the_picks_start_on_the_titles_line(qapp):
    from soundboard.ui.kit import modalframe
    d = feedbackdialog.FeedbackDialog(SimpleNamespace())
    d.show()
    qapp.processEvents()
    assert d.bun.height() == modalframe.MASCOT and d.frame.picture is d.bun
    bun = d.bun.mapTo(d.frame, QPoint(0, 0))
    heading = d.heading.mapTo(d.frame, QPoint(0, 0)).x()
    assert heading - (bun.x() + d.bun.width()) == modalframe.GAP
    assert d.boxes["sounds"].mapTo(d.frame, QPoint(0, 0)).x() == heading
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
