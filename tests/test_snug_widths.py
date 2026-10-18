"""Dropdowns and buttons are as wide as their words, never stretched across a card.

Settings' device boxes were 600-720 px for a 30-letter name and Edit sound's hotkey
button ran 369 px for "Click to set". The app style sizes every dropdown to its
longest choice (capped) unless the code chose otherwise (wheelguard.AppStyle)."""
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import (QApplication, QComboBox, QGridLayout, QHBoxLayout, QVBoxLayout,
                               QWidget)

from soundboard.settings import SettingsDialog
from soundboard.ui.kit.wheelguard import AppStyle
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
    window.setctl.open_settings("audio")
    for __ in range(3):
        QApplication.processEvents()
    d = window.setctl._settings_dlg
    try:
        assert len({cb.width() for cb, _src in d.dev_combos}) == 1
    finally:
        window.setctl.close_settings()


def test_finding_column_mates_leaves_no_stale_layout_items(qapp):
    """Lining a column up must not leave Python wrappers for the layout's items: when
    Qt later frees an item, its wrapper stayed listed at that address, and a menu made
    there reached the style's polish() as a QWidgetItem (a crash report)."""
    import gc

    from PySide6.QtWidgets import QFormLayout, QLabel, QLayoutItem

    def items():   # (by id: other tests' leftovers come and go meanwhile)
        gc.collect()
        return {id(o) for o in gc.get_objects() if isinstance(o, QLayoutItem)}

    box = QWidget()
    outer = QVBoxLayout(box)
    grid, form = QGridLayout(), QFormLayout()
    outer.addLayout(grid)
    outer.addLayout(form)
    before = items()
    for r in range(3):
        grid.addWidget(QLabel("a name"), r, 0)
        cb = QComboBox()
        cb.addItem("Off" * (r + 1))
        grid.addWidget(cb, r, 1)
        f = QComboBox()
        f.addItem("On" * (r + 1))
        form.addRow(f"row {r}", f)
    box.show()
    QApplication.processEvents()
    try:
        assert not items() - before
        assert len({cb.width() for cb in box.findChildren(QComboBox)
                    if grid.indexOf(cb) >= 0}) == 1   # still lined up
    finally:
        box.close()


def test_a_freed_layout_item_never_reaches_polish(qapp):
    """widget_at() reads a layout's widget without leaving the item's wrapper behind,
    and the style shrugs off a stale item instead of raising out of Qt's call."""
    import shiboken6
    from PySide6.QtCore import QObject
    from PySide6.QtWidgets import QLabel, QWidgetItem

    from soundboard.ui.kit.widgets import widget_at

    box = QWidget()
    row = QHBoxLayout(box)
    labels = [QLabel(str(i)) for i in range(3)]
    for lbl in labels:
        row.addWidget(lbl)
    addr = shiboken6.getCppPointer(row.itemAt(1))[0]   # (the old way, to find it)
    assert widget_at(row, 1) is labels[1]
    assert widget_at(row, 7) is None
    labels[1].deleteLater()                            # Qt frees its item itself
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert not isinstance(shiboken6.wrapInstance(addr, QObject), QWidgetItem)
    AppStyle().polish(QWidgetItem(QLabel()))           # must not raise
