import sys

from PySide6.QtWidgets import QVBoxLayout, QWidget

from soundboard import overridepin


def test_an_override_raising_cannot_free_another_widgets_method(qapp):
    """PySide drops a reference it never took from a method looked up for the first
    time while another override's exception is waiting: unpinned, Fresh.resizeEvent
    is freed here and the next resize runs whatever took its memory."""
    class Raises(QWidget):
        def showEvent(self, e):
            raise RuntimeError("an override's bug")

    class Fresh(QWidget):
        def resizeEvent(self, e):
            pass

    assert overridepin.pin() >= 2
    assert overridepin.pin() == 0   # done once per class
    method = Fresh.__dict__["resizeEvent"]
    before = sys.getrefcount(method)
    assert before > overridepin.PIN
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.addWidget(Raises())
    lay.addWidget(Fresh())
    try:
        box.show()   # Raises.showEvent raises, then Fresh is resized for the first time
    except RuntimeError as e:
        assert "an override's bug" in str(e)
    box.hide()
    # PySide took one (2026-10-14, 6.11.2): unpinned, that was the class's last one
    assert sys.getrefcount(method) > overridepin.PIN
    box.resize(300, 200)   # Fresh's resizeEvent still runs as itself
    box.deleteLater()


def test_only_qt_methods_are_pinned(qapp):
    class Own(QWidget):
        def resizeEvent(self, e):
            pass

        def helper(self):
            pass

    overridepin.pin()
    assert sys.getrefcount(Own.__dict__["resizeEvent"]) > overridepin.PIN
    assert sys.getrefcount(Own.__dict__["helper"]) < 10
