"""The rail's foot: alerts above the on-air controls, Settings with the open / shut
arrow beside it."""
from PySide6.QtWidgets import QApplication, QBoxLayout, QLabel, QPushButton, QWidget

from test_mainwindow import window  # noqa: F401

from soundboard.ui.sidebar import SideRail, SideTabs


def _rail(qapp, is_open):
    tabs = SideTabs()
    tabs.addTab(QWidget(), "One")
    alert, live, gear = QPushButton(), QPushButton(), QPushButton("Settings")
    alert.setObjectName("pill")
    rail = SideRail(tabs, QWidget(), QLabel(), QLabel(), [], is_open, [gear], status=[live],
                    alerts=[alert])
    rail.resize(rail.width(), 600)
    alert.hide()
    rail.show()
    QApplication.processEvents()
    return rail, alert, live, gear


def test_alerts_come_first_and_the_line_under_them_follows_them(qapp):
    rail, alert, live, _gear = _rail(qapp, True)
    assert rail.status == [alert, live]   # drawn (and tabbed) in this order
    assert rail.div_alerts.isHidden()
    alert.show()
    QApplication.processEvents()
    QApplication.processEvents()
    assert not rail.div_alerts.isHidden()
    assert alert.geometry().bottom() < rail.div_alerts.geometry().top() < live.geometry().top()
    alert.hide()
    QApplication.processEvents()
    QApplication.processEvents()
    assert rail.div_alerts.isHidden()
    rail.close()


def test_settings_and_the_arrow_share_a_row_open_and_stack_shut(qapp):
    rail, _alert, _live, gear = _rail(qapp, True)
    assert rail._foot_box.direction() == QBoxLayout.LeftToRight
    assert gear.geometry().center().y() == rail.toggle.geometry().center().y()
    rail.set_open(False)
    QApplication.processEvents()
    assert rail._foot_box.direction() == QBoxLayout.TopToBottom
    assert gear.geometry().bottom() < rail.toggle.geometry().top()
    rail.close()


def test_a_rail_without_alerts_has_no_stray_window(qapp):
    tabs = SideTabs()
    tabs.addTab(QWidget(), "One")
    rail = SideRail(tabs, QWidget(), QLabel(), QLabel(), [], False)
    rail.show()
    QApplication.processEvents()
    assert not rail.div_alerts.isVisible() and rail.div_alerts.parentWidget() is None
    rail.close()


def test_shut_rail_hides_the_alerts_and_shows_a_dot_instead(qapp):
    rail, alert, _live, _gear = _rail(qapp, True)
    alert.setProperty("railfull", "Not connected")
    alert.show()
    QApplication.processEvents()
    QApplication.processEvents()
    assert alert.isVisible() and not rail.toggle.property("dot")
    rail.set_open(False)
    QApplication.processEvents()
    assert not alert.isVisible()                  # out of sight shut...
    assert rail.toggle.property("dot")            # ...but not forgotten
    assert "Not connected" in rail.toggle.toolTip()
    rail.set_open(True)
    QApplication.processEvents()
    assert alert.isVisible() and not rail.toggle.property("dot") and rail.toggle.toolTip() == ""
    rail.close()


def test_shut_tabs_have_a_hover_name_with_their_key_and_open_ones_do_not(qapp):
    tabs = SideTabs()
    for name in ("One", "Two"):
        tabs.addTab(QWidget(), name)
    rail = SideRail(tabs, QWidget(), QLabel(), QLabel(), [], False)
    rail.show()
    QApplication.processEvents()
    assert [b.toolTip() for b in rail.buttons] == ["One  (Ctrl+1)", "Two  (Ctrl+2)"]
    rail.set_open(True)
    assert [b.toolTip() for b in rail.buttons] == ["", ""]
    rail.close()


def test_ctrl_numbers_and_ctrl_tab_move_between_tabs(window):  # noqa: F811
    window.show()
    QApplication.processEvents()
    shown = [b for b in window.rail.buttons if b.isVisible()]
    assert len(shown) >= 3
    window._go_tab(1, absolute=True)
    assert shown[1].isChecked()
    window._go_tab(1)
    assert shown[2].isChecked()
    window._go_tab(-1)
    assert shown[1].isChecked()
    window._go_tab(-2)   # wraps round
    assert shown[-1].isChecked()
    window._go_tab(99, absolute=True)   # no such tab: nothing happens
    assert shown[-1].isChecked()


def test_the_header_version_opens_whats_new_and_stop_all_has_its_own_icon(window, monkeypatch):  # noqa: F811
    from soundboard.ui import whatsnew
    shown = []
    monkeypatch.setattr(whatsnew.WhatsNewDialog, "exec", lambda self: shown.append(self.page))
    window.tagline.clicked.emit()
    assert shown == [""]
    assert not window.stop_btn.icon().isNull()
    from soundboard.ui import icons
    assert "stop_all" in icons.SHAPES and icons.SHAPES["stop_all"] is not icons.SHAPES["stop"]
