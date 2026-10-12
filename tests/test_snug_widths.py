"""Dropdowns and buttons are as wide as their words, never stretched across a card.

Settings' device boxes were 600-720 px for a 30-letter name and Edit sound's hotkey
button ran 369 px for "Click to set". The app style sizes every dropdown to its
longest choice (capped) unless the code chose otherwise (wheelguard.AppStyle)."""
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import (QApplication, QComboBox, QGridLayout, QHBoxLayout, QVBoxLayout,
                               QWidget)

from soundboard.settings import SettingsDialog
from soundboard.wheelguard import AppStyle
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)

CAP = AppStyle.COMBO_CAP


def test_a_dropdown_in_a_wide_row_keeps_its_own_width(qapp):
    box = QWidget()
    lay = QVBoxLayout(box)
    cb = QComboBox()
    cb.addItems(["Off", "On"])
    lay.addWidget(cb)
    long = QComboBox()
    long.addItem("Microphone (a very long device name from a USB headset driver) #2")
    lay.addWidget(long)
    mine = QComboBox()   # chose its own width: left alone
    mine.setFixedWidth(500)
    lay.addWidget(mine)
    box.resize(1000, 200)
    box.show()
    QApplication.processEvents()
    try:
        assert cb.width() < 200
        assert long.width() == CAP
        assert mine.width() == 500
    finally:
        box.close()


def test_dropdowns_stacked_in_a_column_share_the_widest_width(qapp):
    """Settings -> Devices' three boxes were 300, 358 and 358 px, each fitting its
    own device name: a column of them lines up on the widest (still capped)."""
    box = QWidget()
    grid = QGridLayout(box)
    names = ("Mic (short)", "Headphones (a much longer device name here)", "Off")
    boxes = []
    for r, name in enumerate(names):
        cb = QComboBox()
        cb.addItem(name)
        grid.addWidget(cb, r, 1)
        boxes.append(cb)
    grid.setColumnStretch(2, 1)
    alone = QComboBox()   # another column: its own width
    alone.addItem("Off")
    grid.addWidget(alone, 0, 3)
    box.resize(1200, 200)
    box.show()
    QApplication.processEvents()
    try:
        widths = {cb.width() for cb in boxes}
        assert len(widths) == 1 and widths.pop() <= CAP
        assert alone.width() < boxes[0].width()
    finally:
        box.close()


def test_a_dropdown_grows_when_its_choices_do(qapp):
    box = QWidget()
    lay = QHBoxLayout(box)
    cb = QComboBox()
    cb.addItem("Off")
    lay.addWidget(cb)
    box.resize(900, 60)
    box.show()
    QApplication.processEvents()
    try:
        short = cb.width()
        cb.addItem("Headphones (a longer device name)")   # devices refreshed later
        lay.activate()
        QApplication.processEvents()
        assert short < cb.width() <= CAP
    finally:
        box.close()


def test_settings_device_boxes_are_not_card_wide(window):  # noqa: F811
    d = SettingsDialog(window, "audio")
    d.resize(1020, 760)
    d.show()
    QApplication.processEvents()
    try:
        assert d.dev_combos
        for cb, _src in d.dev_combos:
            assert cb.width() <= CAP
    finally:
        d.close()
        d.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_settings_device_boxes_line_up(window):  # noqa: F811
    """Input / Output / Send my sounds to: one column, one width (300, 358 and 358 px
    before, each fitting its own device name)."""
    window.resize(1280, 900)
    window.show()
    window.open_settings("audio")
    for __ in range(3):
        QApplication.processEvents()
    d = window._settings_dlg
    try:
        assert len({cb.width() for cb, _src in d.dev_combos}) == 1
    finally:
        window.close_settings()
