"""Automatic focus must not look like a second selected sidebar tab."""
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from soundboard.ui.kit import theme
from soundboard.ui.window.sidebar import SideRail, SideTabs
from test_mainwindow import window  # noqa: F401  (the real MainWindow)


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

        # Expanded: each action gets its own readable row.
        rail.set_open(True)
        qapp.processEvents()
        vis = [b for b in rail.status if b.isVisible()]
        assert vis[0].geometry().bottom() < vis[1].geometry().top()
        assert all(b.width() > 100 for b in vis)
        assert vis[0].geometry().x() == vis[1].geometry().x()
        rail.setLayoutDirection(Qt.RightToLeft)
        qapp.processEvents()
        assert vis[0].geometry().x() == vis[1].geometry().x()
    finally:
        host.close()



def test_the_hidden_bar_filter_never_asks_for_the_bar(qapp, monkeypatch):
    """The filter sees the bar's last events while it's being torn down: asking for
    the bar there wrapped a freed object (an access violation in 2.0.2)."""
    from PySide6.QtCore import QEvent

    tabs = SideTabs()
    tabs.addTab(QWidget(), "Sounds")
    bar = tabs.tabBar()

    def gone():
        raise AssertionError("tabBar() asked for inside the filter")
    monkeypatch.setattr(tabs, "tabBar", gone)
    assert tabs.eventFilter(bar, QEvent(QEvent.Type.Hide)) is False
    assert tabs.eventFilter(bar, QEvent(QEvent.Type.ChildRemoved)) is False
    bar.show()                     # still kept hidden
    qapp.processEvents()
    assert not bar.isVisible()


def test_back_from_settings_by_rail_click_has_no_ring(window):  # noqa: F811
    """Settings, then a click on the Sounds rail tab: hiding Settings handed the focus
    on as if Tab were pressed, and Sounds wore the keyboard ring."""
    from PySide6.QtWidgets import QApplication
    w = window
    w.show()
    w.activateWindow()
    w.tabs.setCurrentWidget(w.sounds_page)
    QApplication.processEvents()
    QTest.mouseClick(w.rail.foot[0], Qt.LeftButton)   # the gear
    QApplication.processEvents()
    assert w.setctl.settings_open()
    QTest.mouseClick(w.rail.buttons[0], Qt.LeftButton)   # Sounds
    QApplication.processEvents()
    assert not w.setctl.settings_open()
    assert [b.index for b in w.rail.buttons if b._kbd_focus] == []
