"""Right-clicking the All tab offers Delete all sounds, which only happens after Yes twice."""
import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QMenu

from soundboard.i18n import _
from soundboard.sounds.library import SoundMeta
from soundboard.ui.sounds import deleteall
from soundboard.ui.sounds.deleteall import DeleteAllDialog
from test_mainwindow import window as main_window  # noqa: F401  (the real MainWindow)


@pytest.fixture
def window(main_window):  # noqa: F811
    return main_window


def _board(w, n=3):
    w.cfg.sounds[:] = []
    for i in range(n):
        m = SoundMeta(id=f"x{i}", name=f"X{i}", file=f"x{i}.wav",
                      tags=["Memes"] if i % 2 else [])
        w.cfg.sounds.append(m)
        w.audio[m.id] = np.zeros((480, 2), np.float32)
    w._rebuild_pads()
    w.catctl._fill_categories()


def _no_arm(monkeypatch):
    monkeypatch.setattr(deleteall, "ARM_S", 0)


def test_needs_yes_twice(qapp, monkeypatch):
    _no_arm(monkeypatch)
    d = DeleteAllDialog(3)
    done = []
    d.accepted.connect(lambda: done.append(True))
    assert d.title.text() == _("Are you sure you want to delete all sounds?")
    assert "3" in d.body.text()
    d.btn_yes.click()
    assert d.title.text() == _("Are you really sure?") and not done
    d.btn_yes.click()
    assert done


def test_double_click_only_gets_past_the_first_step(qapp):
    d = DeleteAllDialog(3)
    done = []
    d.accepted.connect(lambda: done.append(True))
    d.btn_yes.click()
    d.btn_yes.click()
    assert d.step == 2 and not done


def test_cancel_is_what_enter_presses_on_both_steps(qapp, monkeypatch):
    _no_arm(monkeypatch)
    d = DeleteAllDialog(3)
    assert d.btn_cancel.isDefault() and not d.btn_yes.autoDefault()
    d.btn_yes.click()
    assert d.step == 2
    assert d.btn_cancel.isDefault() and not d.btn_yes.autoDefault()
    d.btn_cancel.click()
    assert d.result() == QDialog.DialogCode.Rejected


def _right_click_all(w, monkeypatch, pick: bool):
    from soundboard.ui.window import categorycontrol
    shown = []

    class Shown(QMenu):   # Qt's own exec can't be patched on the class
        def exec(self, *a):
            shown.append([a.text() for a in self.actions()])
            return self.actions()[0] if pick else None
    monkeypatch.setattr(categorycontrol, "QMenu", Shown)
    tb = w.catctl.cat_tabs
    w.catctl._category_menu(tb.tabRect(0).center())
    return shown


def test_all_tab_deletes_every_category_and_undo_brings_them_back(window, monkeypatch):
    w = window
    _board(w)
    answers = iter([QDialog.DialogCode.Rejected, QDialog.DialogCode.Accepted])
    monkeypatch.setattr(DeleteAllDialog, "exec", lambda self: next(answers))

    assert _right_click_all(w, monkeypatch, True) == [[_("Delete all sounds")]]
    assert len(w.cfg.sounds) == 3   # said no
    _right_click_all(w, monkeypatch, True)
    assert w.cfg.sounds == []
    w.rmctl.undo_remove()
    assert [m.id for m in w.cfg.sounds] == ["x0", "x1", "x2"]


def test_all_tab_has_no_menu_on_an_empty_board(window, monkeypatch):
    w = window
    _board(w, 0)
    assert _right_click_all(w, monkeypatch, True) == []


def test_escape_says_no(qapp, monkeypatch):
    from PySide6.QtTest import QTest
    d = DeleteAllDialog(3)
    d.show()
    QTest.keyClick(d, Qt.Key.Key_Escape)
    assert d.result() == QDialog.DialogCode.Rejected
