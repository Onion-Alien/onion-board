"""The labelled rail output controls drive the real mute and setup actions."""
import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest

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
    # open: Mute and Stop all, two buttons; the rail's own Live and Stop all are hidden
    assert output.mute.isVisible() and output.stop.isVisible() and window.stop_btn.isHidden()
    assert output.switch.isHidden() and output.title.isHidden()
    assert output.isVisible() and window.btn_air.isHidden() and window.pill.isHidden()
    output.mute.setFocus(Qt.TabFocusReason)
    QTest.keyClick(output.mute, Qt.Key_Space)
    assert not window.engine.sending and not window.btn_air.isChecked()
    assert output.mute.isChecked() and output.mute.accessibleName() == "Muted"
    # off: your plain mic still goes (no voice changer), only the sounds are cut
    assert "only your mic" in output.mute.accessibleDescription()
    QTest.keyClick(output.mute, Qt.Key_Tab)
    assert output.stop.hasFocus()
    QTest.keyClick(output.stop, Qt.Key_Tab)
    assert output.setup.hasFocus()
    window.btn_air.setChecked(True)
    assert not output.mute.isChecked() and window.engine.sending
    for _ in range(8):
        output.mute.click()
    assert not output.mute.isChecked() and window.engine.sending
    output.setup.setFocus(Qt.TabFocusReason)
    QTest.keyClick(output.setup, Qt.Key_Space)
    assert window.tabs.currentWidget() is window.setup_page
    window.rail.set_open(False)
    assert output.isVisible() and window.btn_air.isHidden()
    assert output.title.isHidden() and not output.setup.isVisible() and output.pair.isHidden()
    assert window.stop_btn.isVisible() and output.switch.isVisible()
    output.switch.click()
    window.rail.set_open(True)
    assert output.mute.isChecked() and not window.engine.sending


def _ink_box(img, rect, bg=None):
    """The bounding box of everything in `rect` that isn't the card's background (or
    the colour at `bg`)."""
    bg = QColor(img.pixel(*(bg or (1, img.height() // 2))))
    xs, ys = [], []
    for y in range(rect.top(), rect.bottom() + 1):
        for x in range(rect.left(), rect.right() + 1):
            c = QColor(img.pixel(x, y))
            if sum(abs(a - b) for a, b in zip(c.getRgb()[:3], bg.getRgb()[:3])) > 90:
                xs.append(x)
                ys.append(y)
    return QRect(QPoint(min(xs), min(ys)), QPoint(max(xs), max(ys)))


@pytest.mark.parametrize("theme_name", ["Dark", "Light"])
@pytest.mark.parametrize("direction", [Qt.LeftToRight, Qt.RightToLeft])
def test_collapsed_output_has_equal_visible_vertical_gaps(window, qapp, theme_name,  # noqa: F811
                                                         direction):
    from soundboard import theme

    theme.apply(qapp, theme_name)
    window.setLayoutDirection(direction)
    window.resize(1180, 720)
    window.show()
    rail = window.rail
    for _ in range(2):
        rail.set_open(False)
        qapp.processEvents()
        img = rail.grab().toImage()
        mark, switch, stop = [_ink_box(img, QRect(w.mapTo(rail, QPoint()), w.size()))
                              for w in (rail.output.mark, rail.output.switch, window.stop_btn)]
        above = switch.top() - mark.bottom() - 1
        below = stop.top() - switch.bottom() - 1
        assert abs(above - below) <= 1
        assert above >= 16
        rail.set_open(True)
        qapp.processEvents()
        _assert_pair(rail.output)
        if direction == Qt.LeftToRight:
            _assert_keylines(rail.output)


def _assert_pair(output):
    """Open: Mute and Stop all, the same width, the same padding round them and
    between them, each icon in its button's middle."""
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()
    mute, stop = sorted((output.mute, output.stop), key=lambda b: b.mapTo(output, QPoint()).x())
    left, right = mute.mapTo(output, QPoint()), stop.mapTo(output, QPoint())
    assert mute.width() == stop.width() and mute.height() == stop.height()
    near, far = left.x(), output.width() - right.x() - stop.width()
    gap = right.x() - left.x() - mute.width()
    assert near == far == left.y() and abs(gap - near) <= 1
    img = output.grab().toImage()
    for b in (mute, stop):
        at = b.mapTo(output, QPoint())
        ink = _ink_box(img, QRect(at.x() + 4, at.y() + 4, b.width() - 8, b.height() - 8),
                       (at.x() + 3, at.y() + b.height() // 2))   # (the button's own fill)
        box = QRect(at, b.size())
        assert abs(ink.center().x() - box.center().x()) <= 1.5
        assert abs(ink.center().y() - box.center().y()) <= 1.5


def _assert_keylines(output, setup=True):
    """Every icon is centred on its label's first-line cap height
    (docs/DESIGN.md *Icon and text alignment*)."""
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()   # (a rescale: the rail gives the card its new height)
    img = output.grab().toImage()
    pairs = []
    if setup:
        # the strip's line: its ink centred in the card (to the odd pixel), its icon and
        # chevron on its cap height
        icon = output.status_icon
        y = icon.mapTo(output, QPoint()).y()
        ink = _ink_box(img, QRect(0, y, output.width(), icon.height()), (2, y + 2))
        assert abs(ink.left() - (output.width() - 1 - ink.right())) <= 1
        pairs += [(output.status_icon, output.status_text), (output.arrow, output.status_text)]
    for icon, label in pairs:
        glyph = _ink_box(img, QRect(icon.mapTo(output, QPoint()), icon.size()))
        fm = label.fontMetrics()
        cap = (label.mapTo(output, QPoint()).y() + label.contentsMargins().top()
               + fm.ascent() - fm.capHeight() / 2)
        assert abs((glyph.top() + glyph.bottom() + 1) / 2 - cap) <= 1.5, label.text()


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
    _assert_pair(output)
    assert rail.rect().contains(output.geometry())
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
        # all good: no strip, the switch says it
        assert not output.strip.isVisible() and output.arrow.isHidden()
        assert output.height() < height and output.setup.focusPolicy() == Qt.NoFocus
        assert output.setup.property("action") is False
        window.tabs.setCurrentWidget(window.sounds_page)
        output.setup.click()
        assert window.tabs.currentWidget() is window.sounds_page
        _assert_keylines(output, setup=False)
        window.rail.set_open(False)
        assert window.pill.isHidden() and not window.rail.toggle.property("dot")
        assert output.dot.isVisible() and output.dot.ok   # green: working
        window.engine.main_stream = None
        window._update_flow()
        qapp.processEvents()
        # shut: the dot is on the On Air icon (the arrow has none), and the icon is
        # the way to Setup
        assert output.dot.isVisible() and not output.dot.ok
        assert not window.rail.toggle.property("dot")
        mark = output.mark.geometry()
        assert output.dot.geometry().intersects(mark.adjusted(-4, -4, 4, 4))
        window.tabs.setCurrentWidget(window.sounds_page)
        QTest.mouseClick(output.mark, Qt.LeftButton)
        assert window.tabs.currentWidget() is window.setup_page
        window.tabs.setCurrentWidget(window.sounds_page)   # (Setup is wider: it can shut the rail)
        window.rail.set_open(True)
        qapp.processEvents()
        # the full card: its warning line says it, no dot (CI's wider fonts can keep
        # the small card even fully open: the dot stays then)
        assert output.dot.isVisible() == (not output.property("expanded"))
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
            for widget in (output.mark, output.title, output.switch, output.mute, output.stop,
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
    window.cfg.route = "device"
    window.cfg.main_device = "Speakers (fake)"
    stream = window.engine.main_stream
    try:
        window.engine.main_stream = None
        window._update_flow()
        qapp.processEvents()
        output = window.rail.output
        assert output.status_text.text() == "Not working" and output.arrow.isVisible()
        assert "Speakers (fake)" in output.status_text.toolTip()
    finally:
        window.engine.main_stream = stream


def test_full_card_only_when_every_line_fits(window, qapp):  # noqa: F811
    """Dragging the rail open, the small card stays until the rail snaps fully open:
    never a squeezed in-between card."""
    from soundboard.ui.sidebar import OPEN_W, SHUT_W, SNAP_W
    window.resize(1180, 720)
    window.show()
    window.cfg.route, window.cfg.main_device = "device", None
    window._update_flow()
    window.set_sending(False)
    rail = window.rail
    rail.set_open(True)
    qapp.processEvents()
    try:
        for width in range(SHUT_W, OPEN_W, 3):
            rail.drag_width(width)
            qapp.processEvents()
            out = rail.output
            # the small card in the shut column, then (snapped fully open) the full one
            assert out.pair.isVisible() == (width >= SNAP_W), width
            if out.pair.isVisible():
                assert rail.width() == OPEN_W
                assert out.mute.geometry().right() < out.stop.x(), width
    finally:
        rail.finish_resize()
