"""Voice switches and page hops must not retain an intermediate responsive layout."""
import pytest
from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtTest import QTest

from soundboard.ui.window import fitcontrol
from soundboard.ui.window.tabcontrol import TAB_KEYS
from test_mainwindow import window  # noqa: F401


class PaintPositions(QObject):
    def __init__(self, button, root):
        super().__init__(button)
        self.root = root
        self.positions = []
        button.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Paint:
            self.positions.append(obj.mapTo(self.root, QPoint()).y())
        return False


@pytest.mark.parametrize("theme", ["Dark", "Light"])
@pytest.mark.parametrize("size", [(1100, 800), (900, 700)])
def test_voice_switches_keep_the_same_fit_and_master_target(window, monkeypatch, theme, size):  # noqa: F811
    w, v = window, window.voice
    monkeypatch.setattr(fitcontrol, "SETTLE_MS", 400)
    monkeypatch.setattr(v, "problem", lambda: "")
    monkeypatch.setattr(v.clean, "ok", True)
    monkeypatch.setattr(v.clean, "_apply", lambda: None)
    v.clean.b_on.setEnabled(True)
    w.themectl.apply_theme(theme)
    w.resize(*size)
    w.show()
    rail = {TAB_KEYS[b.index]: b for b in w.rail.buttons}
    QTest.mouseClick(rail["voice"], Qt.LeftButton)
    QTest.mouseClick(v._tabs["fx"], Qt.LeftButton)
    v.fx.pick("Robot")
    QTest.qWait(700)

    def placement():
        return (tuple(bool(p.picked.property("pinned")) for _k, p in v._barred()),
                v._scroll.height(), w.mixer.isVisible(), w.fitctl.is_mini())

    before = placement()
    y = v.bar.master.mapTo(w, QPoint()).y()
    observer = PaintPositions(v.bar.master, w)
    for _ in range(12):
        QTest.mouseClick(v.bar.master, Qt.LeftButton)
        QTest.qWait(65)
    QTest.qWait(700)
    assert v.fx.btn_power.isChecked() and v.clean.is_on()
    assert placement() == before
    assert observer.positions and set(observer.positions) == {y}
    for _ in range(4):
        for key in ("clean", "ai", "speak", "fx"):
            QTest.mouseClick(v._tabs[key], Qt.LeftButton)
            QTest.qWait(25)
        for key in ("sounds", "setup", "voice"):
            QTest.mouseClick(rail[key], Qt.LeftButton)
            QTest.qWait(25)
    QTest.qWait(700)
    assert placement() == before
