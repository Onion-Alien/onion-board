"""The labelled rail output controls drive the real mute and setup actions."""
import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest

from soundboard.ui.sidebar import RailTab
from test_mainwindow import window  # noqa: F401


def test_labelled_output_switch_controls_engine_and_tracks_other_controls(window, qapp,  # noqa: F811
                                                                         monkeypatch):
    # a send device, so muting means something even on a PC (CI) with no cable
    monkeypatch.setattr(window, "_main_name", lambda: "CABLE Input")
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
    # off: your plain mic still goes (no voice changer), only the sounds are cut
    assert "only your mic" in output.switch.accessibleDescription()
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


def _ink_box(img, rect):
    """The bounding box of everything in `rect` that isn't the card's background."""
    bg = QColor(img.pixel(1, img.height() // 2))
    xs, ys = [], []
    for y in range(rect.top(), rect.bottom() + 1):
        for x in range(rect.left(), rect.right() + 1):
            c = QColor(img.pixel(x, y))
            if sum(abs(a - b) for a, b in zip(c.getRgb()[:3], bg.getRgb()[:3])) > 90:
                xs.append(x)
                ys.append(y)
    return QRect(QPoint(min(xs), min(ys)), QPoint(max(xs), max(ys)))


def _assert_keylines(output, setup=True):
    """Every icon is centred on its label's first-line cap height and every line of
    words starts on one keyline (docs/DESIGN.md *Icon and text alignment*)."""
    img = output.grab().toImage()
    labels = [output.title, output.status_text]
    starts = {label.mapTo(output, QPoint()).x() + label.contentsMargins().left()
              for label in labels}
    assert starts == {output.TEXT_X}
    pairs = [(output.mark, output.title), (output.status_icon, output.status_text)]
    if setup:
        pairs.append((output.arrow, output.status_text))   # (on its x-height: within 1.5)
    for icon, label in pairs:
        glyph = _ink_box(img, QRect(icon.mapTo(output, QPoint()), icon.size()))
        fm = label.fontMetrics()
        cap = (label.mapTo(output, QPoint()).y() + label.contentsMargins().top()
               + fm.ascent() - fm.capHeight() / 2)
        assert abs((glyph.top() + glyph.bottom() + 1) / 2 - cap) <= 1.5, label.text()
    switch = output.switch.mapTo(output, QPoint()).y() + output.switch.height() / 2
    fm = output.title.fontMetrics()
    title = (output.title.mapTo(output, QPoint()).y() + output.title.contentsMargins().top()
             + fm.ascent() - fm.capHeight() / 2)
    assert abs(switch - title) <= 1.5


def test_output_card_icons_and_words_share_keylines(window, qapp, monkeypatch):  # noqa: F811
    """The card's icons share the tab icons' column, its words one keyline, and a
    long (translated) status wraps without clipping, chevron on its first line."""
    window.resize(1180, 720)
    window.show()
    window.rail.set_open(True)
    window.cfg.route = "device"
    window.cfg.main_device = None   # nothing picked to send to
    monkeypatch.setattr(window, "_main_name", lambda: None)
    window._update_flow()
    qapp.processEvents()
    rail, output = window.rail, window.rail.output
    _assert_keylines(output)
    assert output.title.geometry().right() < output.switch.x()
    img = rail.grab().toImage()
    tab = rail.findChildren(RailTab)[0]
    at = tab.mapTo(rail, QPoint())
    icon = _ink_box(img, QRect(at.x() + 2, at.y() + 4, 26, tab.height() - 8))   # (not its name)
    mark = _ink_box(img, QRect(output.mark.mapTo(rail, QPoint()), output.mark.size()))
    assert abs(icon.center().x() - mark.center().x()) <= 1
    assert output.status_text.text() == "Not configured" and output.arrow.isVisible()
    output.status_text.setText("Ausgabe nicht verbunden")
    output.adjustSize()
    qapp.processEvents()
    label = output.status_text
    assert label.height() >= 2 * label.fontMetrics().height() - 2   # wrapped...
    assert label.geometry().bottom() <= output.setup.contentsRect().bottom()   # ...not clipped
    _assert_keylines(output)


def test_connected_output_is_only_words_then_a_link_again(window, qapp, monkeypatch):  # noqa: F811
    window.resize(1180, 720)
    window.show()
    window.rail.set_open(True)
    window.cfg.route = "device"
    window.cfg.main_device = None   # nothing picked to send to
    monkeypatch.setattr(window, "_main_name", lambda: None)
    window._update_flow()
    qapp.processEvents()
    output = window.rail.output
    assert output.status_text.text() == "Not configured"
    height = output.height()
    stream = window.engine.main_stream
    try:
        monkeypatch.setattr(window, "_main_name", lambda: "Selected output")
        window.engine.main_stream = object()
        window._update_flow()
        qapp.processEvents()
        assert output.status_text.text() == "Connected"
        # the same line, no chevron, no hover, no click, out of the Tab order (no taller:
        # a big font can wrap "Not configured ›", never "Connected")
        assert output.setup.isVisible() and output.arrow.isHidden()
        assert output.height() <= height and output.setup.focusPolicy() == Qt.NoFocus
        assert output.setup.property("action") is False
        window.tabs.setCurrentWidget(window.sounds_page)
        output.setup.click()
        assert window.tabs.currentWidget() is window.sounds_page
        _assert_keylines(output, setup=False)
        window.rail.set_open(False)
        assert window.pill.isHidden() and not window.rail.toggle.property("dot")
        window.engine.main_stream = None
        window._update_flow()
        qapp.processEvents()
        assert window.rail.toggle.property("dot")
        window.rail.set_open(True)
        qapp.processEvents()
        assert output.status_text.text() == "Not configured" and output.arrow.isVisible()
        assert output.setup.property("action") is True
        assert output.setup.focusPolicy() == Qt.TabFocus and output.height() == height
    finally:
        window.engine.main_stream = stream


@pytest.mark.parametrize("direction", [Qt.LeftToRight, Qt.RightToLeft])
def test_bottom_controls_follow_tab_column_during_drag(window, qapp, direction):  # noqa: F811
    window.setLayoutDirection(direction)
    window.resize(1180, 720)
    window.show()
    window.rail.set_open(False)
    for width in (70, 115, 90, 43):   # short of halfway: shut
        window.rail.drag_width(width)
        qapp.processEvents()
        rail = window.rail
        tab = rail.buttons[0]
        center = tab.mapTo(rail, QPoint()).x() + tab.width() / 2
        for widget in (rail.output.mark, rail.output.switch, window.stop_btn, rail.toggle):
            actual = widget.mapTo(rail, QPoint()).x() + widget.width() / 2
            assert abs(actual - center) <= 1
        assert window.stop_btn.width() == tab.width() == 34
        # short of the open layout: one column, centred in the rail, no names yet
        assert abs(center - (rail.width() - 1) / 2) <= 1.5
        assert not tab.text().strip()
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


def test_picked_but_failing_says_not_working(window, qapp, monkeypatch):  # noqa: F811
    """A cable (or device) is picked but won't open: "Not working", never the
    "Not configured" of nothing picked."""
    window.resize(1180, 720)
    window.show()
    window.rail.set_open(True)
    window.cfg.route = "cable"
    window.cfg.main_device = "CABLE Input (fake)"
    stream = window.engine.main_stream
    try:
        window.engine.main_stream = None
        window._update_flow()
        qapp.processEvents()
        output = window.rail.output
        assert output.status_text.text() == "Not working" and output.arrow.isVisible()
        assert "CABLE Input (fake)" in output.status_text.toolTip()
    finally:
        window.engine.main_stream = stream


def test_full_card_once_its_title_row_fits(window, qapp):  # noqa: F811
    """Dragging the rail open, the full output card comes in as soon as "Off Air"
    and its switch fit (the status line may wrap, the card growing taller), never
    with the title squeezed or wrapped."""
    from soundboard.ui.sidebar import OPEN_W, SHUT_W
    window.resize(1180, 720)
    window.show()
    window.cfg.route, window.cfg.main_device = "device", None
    window._update_flow()
    window.set_sending(False)
    rail = window.rail
    rail.set_open(True)
    qapp.processEvents()
    try:
        for width in range(SHUT_W, OPEN_W + 1, 3):
            rail.drag_width(width)
            qapp.processEvents()
            out = rail.output
            if out.title.isVisible():
                assert out.title.text() == "Off Air"
                assert out.title.height() < 2 * out.title.fontMetrics().height() + 8, width
                assert out.title.geometry().right() < out.switch.x(), width
                assert out.switch.geometry().right() <= out.contentsRect().right(), width
                status = out.status_text
                assert status.geometry().bottom() <= out.setup.contentsRect().bottom(), width
    finally:
        rail.finish_resize()
