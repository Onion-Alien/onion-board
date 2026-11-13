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


def test_new_classes_are_walked_for_only_after_a_while(qapp, monkeypatch):
    """The collector asks on every tick: the walk over every Qt class runs only WALK_S
    after the last one (a class made in a function), not 10 times a second (about 1%
    of a core with nothing else going on), and not for every module imported."""
    walks = []
    monkeypatch.setattr(overridepin, "pin", lambda: walks.append(1) or 0)
    monkeypatch.setattr(overridepin, "_modules", -1)
    monkeypatch.setattr(overridepin, "_walked", 0.0)
    overridepin.pin_new(now=100.0)
    overridepin.pin_new(now=100.1)
    overridepin.pin_new(now=100.5)
    assert len(walks) == 1
    monkeypatch.setitem(sys.modules, "an_add_on_just_imported", object())
    overridepin.pin_new(now=100.6)
    assert len(walks) == 1
    overridepin.pin_new(now=100.0 + overridepin.WALK_S)
    assert len(walks) == 2


def test_the_timed_walk_waits_until_it_wont_page_the_app_back_in(qapp, monkeypatch):
    """In the tray on a PC short of memory, a walk read every Qt class back from the
    page file with Python's lock held (10 s to over a minute): the full walk waits for
    warm, a module imported there included."""
    walks = []
    monkeypatch.setattr(overridepin, "pin", lambda: walks.append(1) or 0)
    monkeypatch.setattr(overridepin, "_modules", len(sys.modules))
    monkeypatch.setattr(overridepin, "_walked", 100.0)
    later = 100.0 + 10 * overridepin.WALK_S
    overridepin.pin_new(now=later, warm=lambda: False)
    monkeypatch.setitem(sys.modules, "an_add_on_imported_in_the_tray", object())
    overridepin.pin_new(now=later, warm=lambda: False)
    assert walks == []
    overridepin.pin_new(now=later, warm=lambda: True)
    assert len(walks) == 1


def test_a_module_imported_has_its_classes_pinned_without_a_walk(qapp, monkeypatch):
    """A module imported while the app sat in the tray: its own classes are pinned at
    once (they're new, so in RAM), without walking the app's every class."""
    import types as pytypes

    walks = []
    monkeypatch.setattr(overridepin, "pin", lambda: walks.append(1) or 0)
    monkeypatch.setattr(overridepin, "_modules", len(sys.modules))
    monkeypatch.setattr(overridepin, "_walked", 100.0)
    mod = pytypes.ModuleType("an_add_on_with_a_widget")

    class AddOnWidget(QWidget):
        def resizeEvent(self, e):
            pass

        class Inner(QWidget):
            def showEvent(self, e):
                pass
    AddOnWidget.__module__ = mod.__name__
    mod.AddOnWidget = AddOnWidget
    monkeypatch.setitem(sys.modules, mod.__name__, mod)
    assert overridepin.pin_new(now=100.1, warm=lambda: False) == 2
    assert walks == []
    assert sys.getrefcount(AddOnWidget.__dict__["resizeEvent"]) > overridepin.PIN
    assert sys.getrefcount(AddOnWidget.Inner.__dict__["showEvent"]) > overridepin.PIN
    assert overridepin.pin_new(now=100.2, warm=lambda: False) == 0   # nothing new


def test_a_module_still_running_its_code_is_looked_at_once_it_ends(qapp, monkeypatch):
    """Imported on another thread: in sys.modules while its classes are still being
    made. It's looked through on the first tick after it's done."""
    import types as pytypes

    monkeypatch.setattr(overridepin, "pin", lambda: 0)
    monkeypatch.setattr(overridepin, "_modules", len(sys.modules))
    monkeypatch.setattr(overridepin, "_walked", 100.0)
    monkeypatch.setattr(overridepin, "_pending", [])
    mod = pytypes.ModuleType("an_add_on_importing")
    mod.__spec__ = pytypes.SimpleNamespace(_initializing=True)
    monkeypatch.setitem(sys.modules, mod.__name__, mod)
    assert overridepin.pin_new(now=100.1, warm=lambda: False) == 0

    class Late(QWidget):
        def resizeEvent(self, e):
            pass
    mod.Late = Late
    mod.__spec__._initializing = False
    assert overridepin.pin_new(now=100.2, warm=lambda: False) == 1


def test_a_class_freed_is_forgotten(qapp):
    import gc

    class Gone(QWidget):
        def resizeEvent(self, e):
            pass
    overridepin.pin()
    key = id(Gone)
    assert key in overridepin._done
    del Gone
    gc.collect()
    assert key not in overridepin._done
