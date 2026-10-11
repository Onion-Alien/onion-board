"""Dialog action rows: the main (filled) action first, then the secondary actions,
then a stretch, so actions sit at the logical start and are never right-aligned.
Backlog U1: consistent dialog actions (Settings, Edit sound, Record, Program picker)."""
import numpy as np
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QPushButton

from soundboard.engine import SR, Engine
from soundboard.settings import SettingsDialog
from soundboard.ui.dialogs import EditDialog
from soundboard.ui.panel import action_row
from soundboard.ui.programpick import ProgramPicker
from soundboard.ui.recordmic import RecordDialog

from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)


def left_x(widget, dialog):
    return widget.mapTo(dialog, QPoint(0, 0)).x()


def test_action_row_is_main_first_then_stretch(qapp):
    a, b = QPushButton("A"), QPushButton("B")
    row = action_row(a, b)
    assert row.count() == 3
    assert row.itemAt(0).widget() is a
    assert row.itemAt(1).widget() is b
    assert row.itemAt(2).spacerItem() is not None   # the stretch is last


def test_settings_done_is_primary_and_on_the_left(window, qapp):  # noqa: F811
    d = SettingsDialog(window, "general")
    d.show()
    qapp.processEvents()
    done = next(b for b in d.findChildren(QPushButton) if b.text() == "Done")
    assert done.objectName() == "primary"
    assert left_x(done, d) < d.width() / 2   # left-aligned, not pushed to the right
    d.close()


def test_edit_dialog_save_is_primary_first_preview_left(window, qapp):  # noqa: F811
    d = EditDialog(window.meta("s0"), window.hotkeys, lambda *a: None, window)
    d.show()
    qapp.processEvents()
    save = next(b for b in d.findChildren(QPushButton) if b.text() == "Save")
    copy = next(b for b in d.findChildren(QPushButton) if b.text() == "Save as new sound")
    cancel = next(b for b in d.findChildren(QPushButton) if b.text() == "Cancel")
    assert save.objectName() == "primary"
    assert copy.objectName() != "primary" and cancel.objectName() != "primary"
    assert cancel.property("quiet") is True
    xs = [left_x(b, d) for b in (save, copy, cancel)]
    assert xs == sorted(xs) and xs[0] < d.width() / 2
    assert left_x(d.btn_preview, d) < xs[0]   # preview stays beside its content
    assert save.isDefault()                    # Enter in a field saves
    d.reject()


def test_record_dialog_save_is_primary_first(window, qapp):  # noqa: F811
    e = Engine()
    e.names["mic"] = "Test mic"
    e.mic_stream = object()   # stands in for an open mic
    d = RecordDialog(e, lambda: False, lambda: ["Boom"], lambda data, name: True,
                     lambda: None)
    d.data = np.zeros((SR, 2), dtype=np.float32)
    d._show_state()   # a captured take: Save / Record again appear
    d.show()
    qapp.processEvents()
    close = next(b for b in d.findChildren(QPushButton) if b.text() == "Close")
    assert d.btn_save.objectName() == "primary"
    assert d.btn_again.objectName() != "primary" and close.objectName() != "primary"
    xs = [left_x(b, d) for b in (d.btn_save, d.btn_again, close)]
    assert xs == sorted(xs) and xs[0] < d.width() / 2
    assert d.btn_save.isDefault()   # Enter in the name box saves
    d.deleteLater()


def test_program_picker_add_is_primary_first(qapp):
    d = ProgramPicker("cat", {}, lister=lambda: [])
    d.show()
    qapp.processEvents()
    browse = next(b for b in d.findChildren(QPushButton) if "Browse" in b.text())
    cancel = next(b for b in d.findChildren(QPushButton) if b.text() == "Cancel")
    assert d.btn_ok.objectName() == "primary"
    assert browse.objectName() != "primary" and cancel.objectName() != "primary"
    xs = [left_x(b, d) for b in (d.btn_ok, browse, cancel)]
    assert xs == sorted(xs) and xs[0] < d.width() / 2
    d.deleteLater()
