"""The labelled rail output controls drive the real mute and setup actions."""
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from test_mainwindow import window  # noqa: F401


def test_labelled_output_switch_controls_engine_and_tracks_other_controls(window, qapp):  # noqa: F811
    window.resize(1180, 720)
    window.show()
    window.rail.set_open(True)
    qapp.processEvents()
    output = window.rail.output
    assert window.mode_btn.isHidden() and window.mode_btn not in window.rail.status
    assert window.stop_btn.isVisible()
    assert output.isVisible() and window.btn_air.isHidden() and window.pill.isHidden()
    output.switch.setFocus(Qt.TabFocusReason)
    QTest.keyClick(output.switch, Qt.Key_Space)
    assert not window.engine.sending and not window.btn_air.isChecked()
    assert "Muted" in output.switch.accessibleDescription()
    QTest.keyClick(output.switch, Qt.Key_Tab)
    assert output.setup.hasFocus()
    window.btn_air.setChecked(True)
    assert output.switch.isChecked() and window.engine.sending
    for _ in range(8):
        output.switch.click()
    assert output.switch.isChecked() and window.engine.sending
    output.setup.setFocus(Qt.TabFocusReason)
    QTest.keyClick(output.setup, Qt.Key_Space)
    assert window.tabs.currentWidget() is window.setup_page
    window.rail.set_open(False)
    assert output.isVisible() and window.btn_air.isHidden()
    assert output.title.isHidden() and output.setup.isHidden()
    output.switch.click()
    window.rail.set_open(True)
    assert not output.switch.isChecked() and not window.engine.sending


def test_connected_output_hides_setup_and_shrinks_then_restores(window, qapp, monkeypatch):  # noqa: F811
    window.resize(1180, 720)
    window.show()
    window.rail.set_open(True)
    window.cfg.route = "device"
    monkeypatch.setattr(window, "_main_name", lambda: None)
    window._update_flow()
    qapp.processEvents()
    output = window.rail.output
    assert output.status_text.text() == "Not connected"
    height = output.height()
    stream = window.engine.main_stream
    try:
        monkeypatch.setattr(window, "_main_name", lambda: "Selected output")
        window.engine.main_stream = object()
        window._update_flow()
        qapp.processEvents()
        assert output.status_text.text() == "Connected"
        assert output.setup.isHidden() and output.height() < height
        for icon, label in [(output.mark, output.title),
                            (output.status_icon, output.status_text)]:
            icon_y = icon.mapTo(output, QPoint()).y() + icon.height() / 2
            label_y = label.mapTo(output, QPoint()).y() + label.height() / 2
            assert abs(icon_y - label_y) <= 1
        window.rail.set_open(False)
        assert window.pill.isHidden() and not window.rail.toggle.property("dot")
        window.engine.main_stream = None
        window._update_flow()
        qapp.processEvents()
        assert window.rail.toggle.property("dot")
        window.rail.set_open(True)
        qapp.processEvents()
        assert output.status_text.text() == "Not connected" and output.setup.isVisible()
        assert output.height() >= height
    finally:
        window.engine.main_stream = stream


@pytest.mark.parametrize("direction", [Qt.LeftToRight, Qt.RightToLeft])
def test_bottom_controls_follow_tab_column_during_drag(window, qapp, direction):  # noqa: F811
    window.setLayoutDirection(direction)
    window.resize(1180, 720)
    window.show()
    window.rail.set_open(False)
    for width in (70, 115, 160, 90, 43):
        window.rail.drag_width(width)
        qapp.processEvents()
        rail = window.rail
        tab = rail.buttons[0]
        center = tab.mapTo(rail, QPoint()).x() + tab.width() / 2
        for widget in (rail.output.mark, rail.output.switch, window.stop_btn, rail.toggle):
            actual = widget.mapTo(rail, QPoint()).x() + widget.width() / 2
            assert abs(actual - center) <= 1
        assert window.stop_btn.width() == tab.width()
    window.rail.finish_resize()


@pytest.mark.parametrize("direction", [Qt.LeftToRight, Qt.RightToLeft])
def test_output_block_stays_inside_rail_at_normal_and_narrow_sizes(window, qapp, direction):  # noqa: F811
    window.setLayoutDirection(direction)
    window.show()
    window.rail.set_open(True)
    for width, height in [(1180, 720), (800, 600), (440, 600), (1180, 720)]:
        window.resize(width, height)
        qapp.processEvents()
        output = window.rail.output
        if output.isVisible():
            assert window.rail.rect().contains(output.geometry())
            for widget in (output.mark, output.title, output.switch,
                           output.status_text, output.setup):
                if not widget.isVisible():
                    continue
                pos = widget.mapTo(output, QPoint())
                assert pos.x() >= 0 and pos.y() >= 0
                assert pos.x() + widget.width() <= output.width()
                assert pos.y() + widget.height() <= output.height()
