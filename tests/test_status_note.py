"""Dismissed and expired floating notes must not return during layout changes."""
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from soundboard.ui.mainwindow import StatusLine
from test_mainwindow import window  # noqa: F401


def test_clicked_note_stays_gone_after_resize_and_compact_mode(qapp):
    parent = QWidget()
    parent.resize(600, 400)
    note = StatusLine(parent, lambda: 350)
    parent.show()
    try:
        note.setText("Headphones changed")
        QTest.mouseClick(note, Qt.LeftButton)
        parent.resize(700, 450)
        note.set_room(True)
        note.set_room(False)
        qapp.processEvents()
        assert not note.text() and not note.isVisible()
        assert not note.toolTip()
        note.setText("A new message")
        assert note.isVisible()
        assert note._expiry.isActive() and note._expiry.interval() == 8000
    finally:
        parent.close()
        parent.deleteLater()


def test_expiry_clears_note_but_never_a_replacement(qapp):
    parent = QWidget()
    note = StatusLine(parent, lambda: 350)
    parent.show()
    try:
        note.setText("Headphones changed", timeout_ms=20)
        QTest.qWait(60)
        note.set_room(False)
        assert not note.text() and not note.isVisible()
        note.setText("Headphones changed", timeout_ms=20)
        note.setText("An audio error")
        QTest.qWait(60)
        assert note.text() == "An audio error" and note.isVisible()
    finally:
        parent.close()
        parent.deleteLater()


def test_note_sits_centred_in_the_page_not_over_the_rail(window):  # noqa: F811
    note = window.status
    page = note.parentWidget()
    assert page is not window.rail and not page.isAncestorOf(window.rail)
    window.resize(1100, 760)
    window.show()
    note.setText("Added “Socket Adapters are Getting Out of Hand” (900.0s) to Sounds: "
                 "right-click it there to rename or set a hotkey.")
    note.place()
    g = note.geometry()
    assert g.width() <= note.MAX_W
    assert abs(g.center().x() - page.width() // 2) <= 1
    rail_right = window.rail.mapTo(window, window.rail.rect().topRight()).x()
    assert note.mapTo(window, note.rect().topLeft()).x() > rail_right


def test_sidebar_controls_have_no_hover_help_in_both_sizes(window):  # noqa: F811
    rail = window.rail
    for opened in (False, True, False):
        rail.set_open(opened)
        for button in (*rail.buttons, *rail.extras, rail.toggle):
            assert not button.toolTip()
            assert button.accessibleName()
    assert window.gear.accessibleDescription()
