import sys

from PySide6.QtWidgets import QVBoxLayout, QWidget

from soundboard.core import overridepin


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
    except (RuntimeError, SystemError) as e:
        # the app-wide event filter (theme) can be the next Python call while the bug's
        # exception waits: it then comes out as its SystemError instead
        assert "an override's bug" in str(e) or "exception set" in str(e)
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


def test_new_classes_are_walked_for_only_after_an_import_or_a_while(qapp, monkeypatch):
    """The collector asks on every tick: the walk over every Qt class runs only when a
    module came in since, or WALK_S later (a class made in a function), not 10 times a
    second (about 1% of a core with nothing else going on)."""
    walks = []
    monkeypatch.setattr(overridepin, "pin", lambda: walks.append(1) or 0)
    monkeypatch.setattr(overridepin, "_walked", (-1, 0.0))
    overridepin.pin_new(now=100.0)
    overridepin.pin_new(now=100.1)
    overridepin.pin_new(now=100.5)
    assert len(walks) == 1
    monkeypatch.setitem(sys.modules, "an_add_on_just_imported", object())
    overridepin.pin_new(now=100.6)
    assert len(walks) == 2
    overridepin.pin_new(now=100.6 + overridepin.WALK_S)
    assert len(walks) == 3
