"""Automatic focus must not look like a second selected sidebar tab."""
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

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


def test_sidebar_status_buttons_centered_when_extended(qapp):
    host = QWidget()
    tabs = SideTabs()
    for name in ("Sounds", "Radio"):
        tabs.addTab(QWidget(), name)
    b1, b2, b3 = QPushButton("air"), QPushButton("mode"), QPushButton("stop")
    rail = SideRail(tabs, QWidget(), QLabel(), QLabel(), [], False, status=[b1, b2, b3])
    QVBoxLayout(host).addWidget(rail)
    host.show()
    qapp.processEvents()

    try:
        # Shut: stacked vertically with no extra vertical spacing before or after
        assert rail._status_pad_before.geometry().height() == 0
        assert rail._status_pad_after.geometry().height() == 0
        assert b1.geometry().x() == b2.geometry().x() == b3.geometry().x()

        # Extended: centered horizontally
        rail.set_open(True)
        qapp.processEvents()
        vis = [b for b in rail.status if b.isVisible()]
        left_gap = vis[0].geometry().left() - rail.rect().left()
        right_gap = rail.rect().right() - vis[-1].geometry().right()
        assert abs(left_gap - right_gap) <= 1

        # Mirrored (RTL)
        rail.setLayoutDirection(Qt.RightToLeft)
        qapp.processEvents()
        left_gap_rtl = vis[-1].geometry().left() - rail.rect().left()
        right_gap_rtl = rail.rect().right() - vis[0].geometry().right()
        assert abs(left_gap_rtl - right_gap_rtl) <= 1
    finally:
        host.close()

