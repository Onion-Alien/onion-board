"""Automatic focus must not look like a second selected sidebar tab."""
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from soundboard import theme
from soundboard.ui.sidebar import SideRail, SideTabs


def test_sidebar_focus_ring_follows_keyboard_navigation(qapp):
    host = QWidget()
    tabs = SideTabs()
    for name in ("Sounds", "Apps"):
        tabs.addTab(QWidget(), name)
    rail = SideRail(tabs, QWidget(), QLabel(), QLabel(), [], False)
    QVBoxLayout(host).addWidget(rail)
    host.setStyleSheet(theme.stylesheet())
    host.show()
    qapp.processEvents()
    sounds, apps = rail.buttons
    try:
        sounds.setFocus(Qt.OtherFocusReason)
        tabs.setCurrentIndex(1)
        qapp.processEvents()
        automatic = sounds.grab().toImage()
        assert sounds.hasFocus() and not sounds.isChecked() and apps.isChecked()
        sounds.clearFocus()
        qapp.processEvents()
        assert sounds.grab().toImage() == automatic

        sounds.setFocus(Qt.TabFocusReason)
        qapp.processEvents()
        assert sounds.grab().toImage() != automatic
        QTest.keyClick(sounds, Qt.Key_Down)
        qapp.processEvents()
        assert apps.hasFocus() and apps._kbd_focus and apps.isChecked()

        QTest.mouseClick(sounds, Qt.LeftButton)
        qapp.processEvents()
        assert sounds.isChecked() and not apps.isChecked()
        assert not sounds._kbd_focus and not apps._kbd_focus

        sounds.clearFocus()
        sounds.setFocus(Qt.BacktabFocusReason)
        qapp.processEvents()
        assert sounds._kbd_focus
    finally:
        host.close()
