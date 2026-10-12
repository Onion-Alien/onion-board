from PySide6.QtWidgets import QPushButton, QWidget
from shiboken6 import delete as qt_delete

from soundboard.ui.panel import Flow


def test_an_item_gone_on_the_qt_side_is_skipped_not_raised_on(qapp):
    """One of its items went on the Qt side once (after removing Onion Watch): every
    layout pass raised on it, the buttons were left on top of each other and the app
    crashed soon after."""
    box = QWidget()
    flow = Flow(box, gap=8)
    a, b = QPushButton("Get"), QPushButton("Cancel")
    flow.addWidget(a)
    flow.addWidget(b)
    qt_delete(flow.itemAt(0))           # its Qt side gone, still in the list
    assert flow.count() == 1 and flow.itemAt(0).widget() is b
    assert flow.heightForWidth(300) == b.sizeHint().height()
    assert flow.sizeHint().width() > 0 and not flow.minimumSize().isEmpty()
    box.resize(300, 100)
    box.show()
    qapp.processEvents()
    assert b.geometry().topLeft().x() == 0
    box.close()
