"""Tooltips wait until the mouse has rested on a control, every time."""
from PySide6.QtCore import QEvent, QPoint
from PySide6.QtGui import QEnterEvent, QHelpEvent
from PySide6.QtWidgets import QApplication, QPushButton

from soundboard import wheelguard


def test_a_tooltip_waits_and_restarts_on_each_control(qapp, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(wheelguard, "time", type("Clock", (), {
        "monotonic": staticmethod(lambda: clock[0])}))
    monkeypatch.setattr(wheelguard, "TIP_DELAY", 1.0)
    shown = []

    class Tipped(QPushButton):
        def event(self, e):
            if e.type() == QEvent.Type.ToolTip:
                shown.append(self.text())
                return True
            return super().event(e)

    a, b = Tipped("a"), Tipped("b")
    for w in (a, b):
        w.ensurePolished()   # AppStyle puts its filter on it

    def hover(w):
        QApplication.sendEvent(w, QEnterEvent(QPoint(5, 5), QPoint(5, 5), QPoint(5, 5)))

    def ask(w):
        QApplication.sendEvent(w, QHelpEvent(QEvent.Type.ToolTip, QPoint(5, 5), QPoint(5, 5)))

    hover(a)
    clock[0] += 0.7   # Qt's own wait: too soon
    ask(a)
    assert shown == []
    clock[0] += 0.3
    ask(a)
    assert shown == ["a"]
    QApplication.sendEvent(a, QEvent(QEvent.Type.Leave))
    hover(b)   # straight on to the next one: Qt would show it at once
    clock[0] += 0.02
    ask(b)
    assert shown == ["a"]
    clock[0] += 0.98
    ask(b)
    assert shown == ["a", "b"]
