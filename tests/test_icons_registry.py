"""The live-retheme registry in soundboard.ui.icons lets deleted widgets go."""
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QLabel, QTabWidget, QWidget

from soundboard.ui import icons


def test_registry_drops_deleted_labels_and_tab_widgets(qapp):
    """A dialog's labels and Settings' tabs went on the list each time it opened
    (6 -> 66 entries in a churn test)."""
    def churn():
        box = QWidget()
        label = QLabel(box)
        tabs = QTabWidget(box)
        for i in range(3):
            tabs.addTab(QWidget(), str(i))
            icons.set_tab_icon(tabs, i, "settings")
        icons.set_label_icon(label, "settings")
        icons.set_label_icon(label, "settings")         # again: still one entry for it
        box.deleteLater()
        qapp.sendPostedEvents(None, QEvent.DeferredDelete)

    churn()
    labels, tabs = len(icons._labels), len(icons._tabs)
    for _ in range(10):
        churn()
    assert len(icons._labels) <= labels and len(icons._tabs) <= tabs
