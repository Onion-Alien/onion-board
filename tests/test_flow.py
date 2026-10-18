from PySide6.QtWidgets import QPushButton, QWidget
from shiboken6 import delete as qt_delete

from soundboard.ui.kit.panel import Flow


def test_an_item_gone_on_the_qt_side_is_made_again_not_raised_on(qapp):
    """One of its items went on the Qt side once (around loading and removing Onion
    Watch): every layout pass raised on it and the app crashed. Dropping it instead
    left the button where it was while the row took itself for empty (0 px tall), so
    the text under Who's listening's modes sat on top of them. The button keeps its
    place in the row."""
    box = QWidget()
    flow = Flow(box, gap=8)
    a, b = QPushButton("Get"), QPushButton("Cancel")
    flow.addWidget(a)
    flow.addWidget(b)
    qt_delete(flow.itemAt(0))           # its Qt side gone, still in the list
    assert flow.count() == 2 and flow.itemAt(0).widget() is a
    tall = max(a.sizeHint().height(), b.sizeHint().height())
    assert flow.heightForWidth(300) == tall and flow.sizeHint().height() == tall
    box.resize(300, 100)
    box.show()
    qapp.processEvents()
    assert a.geometry().topLeft().x() == 0 and a.geometry().right() < b.geometry().left()
    box.close()


def test_an_item_whose_widget_is_gone_too_is_dropped(qapp):
    box = QWidget()
    flow = Flow(box, gap=8)
    a, b = QPushButton("Get"), QPushButton("Cancel")
    flow.addWidget(a)
    flow.addWidget(b)
    item = flow.itemAt(0)
    qt_delete(a)
    if flow.count() == 2:               # (Qt may have taken it out itself)
        qt_delete(item)
    assert flow.count() == 1 and flow.itemAt(0).widget() is b
    assert flow.heightForWidth(300) == b.sizeHint().height()
    flow.takeAt(0)
    assert flow.count() == 0
