"""Every dropdown, slider and number box on a scrolling page ignores the mouse wheel.

Scrolling down a page and passing over one used to change it (the Voice tab's
"Speak in" language jumped while the user was just scrolling). The guard is
installed per widget (wheelguard.py), so this walks the real window and Settings
and names any control a new panel forgot to guard."""
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import (QAbstractScrollArea, QAbstractSlider, QAbstractSpinBox,
                               QApplication, QComboBox, QScrollBar, QWidget)

from soundboard.settings import SettingsDialog
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)


def _unguarded(root: QWidget) -> list[str]:
    out = []
    for w in root.findChildren(QWidget):
        if not isinstance(w, (QComboBox, QAbstractSlider, QAbstractSpinBox)) \
                or isinstance(w, QScrollBar) or w.property("noWheel"):
            continue
        p = w.parentWidget()
        while p is not None and not isinstance(p, QAbstractScrollArea):
            p = p.parentWidget()
        if p is None:
            continue   # not on a scrolling page: the wheel has nothing else to do
        out.append(f"{type(w).__name__} {w.objectName() or w.accessibleName() or ''} "
                   f"in {type(w.parentWidget()).__name__}")
    return out


def test_main_window_controls_ignore_the_wheel(window):  # noqa: F811
    assert _unguarded(window) == []


def test_settings_controls_ignore_the_wheel(window):  # noqa: F811
    d = SettingsDialog(window, "audio")
    try:
        for i in range(d.tabs.count()):
            d.tabs.setCurrentIndex(i)   # pages build on first show
        assert _unguarded(d) == []
    finally:
        d.close()
        d.deleteLater()   # every page was built: don't leave them alive for later tests
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_wheel_never_changes_a_dropdown_or_tab_anywhere(window):  # noqa: F811
    """Off a scrolling page too (the Radio filters), and on tab strips (Onion Watch's
    Triggers / Log flipped as the wheel rolled past): the app style (wheelguard.AppStyle,
    set by conftest as by app.main) says no to both."""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QTabBar

    combos = [c for c in window.findChildren(QComboBox) if c.count() > 1]
    bars = [b for b in window.findChildren(QTabBar) if b.count() > 1]
    assert combos and bars
    for w in combos + bars:
        w.setCurrentIndex(0)
        for dy in (-120, 120):
            QApplication.sendEvent(w, QWheelEvent(
                QPointF(5, 5), QPointF(w.mapToGlobal(QPoint(5, 5))), QPoint(), QPoint(0, dy),
                Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))
        assert w.currentIndex() == 0, f"{type(w).__name__} {w.objectName()} moved"


def test_style_has_no_python_style_hint():
    """Qt asks the style for hints tens of thousands of times per theme switch; a
    Python styleHint makes each one wait for Python's lock (theme switch freezes of
    11 s and 36 s while audio ran). The wheel / slider changes are event filters."""
    from soundboard.wheelguard import AppStyle
    assert "styleHint" not in AppStyle.__dict__
    assert "pixelMetric" not in AppStyle.__dict__


def test_click_on_a_slider_jumps_there_and_drags(qapp):
    """A left click anywhere on a slider's bar moves it there (not a page step), and
    the same press keeps dragging it, for plain and seek sliders alike."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QSlider

    from soundboard.ui.widgets import SeekSlider
    for cls in (QSlider, SeekSlider):
        s = cls(Qt.Orientation.Horizontal)
        s.setRange(0, 100)
        s.setPageStep(10)
        s.resize(300, 24)
        s.show()
        QApplication.processEvents()
        y = s.height() // 2
        QTest.mousePress(s, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(270, y))
        assert s.value() > 80, f"{cls.__name__} page-stepped to {s.value()}"
        assert s.isSliderDown()
        QTest.mouseMove(s, QPoint(60, y))
        assert s.value() < 30, f"{cls.__name__} didn't drag ({s.value()})"
        QTest.mouseRelease(s, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                           QPoint(60, y))
        assert not s.isSliderDown()
        s.close()
        s.deleteLater()
