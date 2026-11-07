"""Moving a sound to another category: from the pad menu, in a batch, and by dragging a pad
onto a category's tab."""
import numpy as np
import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QDragMoveEvent, QDropEvent

from soundboard.sounds.library import SoundMeta
from soundboard.ui.kit.pad import PAD_MIME
from test_mainwindow import window as main_window  # noqa: F401  (the real MainWindow)


@pytest.fixture
def window(main_window):  # noqa: F811
    w = main_window
    w.cfg.categories = ["test", "lol"]
    for i, tags in enumerate((["test"], ["test"], [])):
        m = SoundMeta(id=f"s{i}", name=f"s{i}", file=f"s{i}.wav", duration=1.0, tags=list(tags))
        w.cfg.sounds.append(m)
        w.audio[m.id] = np.zeros((480, 2), np.float32)
    w._rebuild_pads()
    w.catctl._fill_categories()
    return w


def test_moving_leaves_the_showing_category_and_joins_the_new_one(window):
    window.catctl.set_category("test")
    window.catctl.move_to_category(["s0"], "lol")
    assert window.meta("s0").tags == ["lol"]
    assert window.meta("s1").tags == ["test"]


def test_moving_from_all_only_adds(window):
    window.catctl.set_category("")
    window.catctl.move_to_category(["s0", "s2"], "lol")
    assert window.meta("s0").tags == ["test", "lol"]
    assert window.meta("s2").tags == ["lol"]


def test_moving_takes_the_subcategories_along_and_ignores_the_same_category(window):
    window.cfg.subcategories = {"test": ["a"]}
    window.meta("s0").tags = ["test", "test / a"]
    window.catctl.set_category("test")
    window.catctl.move_to_category(["s0"], "test")
    assert window.meta("s0").tags == ["test", "test / a"]
    window.catctl.move_to_category(["s0"], "lol")
    assert window.meta("s0").tags == ["lol"]


KEEP = []   # Qt events point at their mime data: it must outlive them


def drag(bar, kind, i, sid="s0"):
    md = QMimeData()
    KEEP.append(md)
    md.setData(PAD_MIME, sid.encode())
    pos = QPointF(bar.tabRect(i).center())
    ev = kind(pos.toPoint(), Qt.MoveAction, md, Qt.LeftButton, Qt.NoModifier) \
        if kind is not QDropEvent else QDropEvent(pos, Qt.MoveAction, md, Qt.LeftButton,
                                                  Qt.NoModifier)
    ev.setAccepted(False)
    bar.event(ev)
    return ev


def test_dropping_a_pad_on_a_tab_moves_it_and_all_takes_nothing(window):
    bar = window.catctl.cat_tabs
    window.catctl.set_category("test")
    assert drag(bar, QDragMoveEvent, 0).isAccepted() is False      # All
    assert drag(bar, QDragMoveEvent, 1).isAccepted() is False      # the tab showing
    assert drag(bar, QDragMoveEvent, 2).isAccepted() is True       # lol
    assert bar._drop_i == 2
    assert drag(bar, QDropEvent, 2).isAccepted() is True
    assert window.meta("s0").tags == ["lol"]
    assert bar._drop_i == -1


def test_batch_menu_lists_the_other_categories_and_moves_them(window, monkeypatch):
    from test_padbatch import menu_shows
    window.catctl.set_category("test")
    seen = []
    menu_shows(monkeypatch, lambda m: seen.append(
        next(a for a in next(a for a in m.actions() if a.text() == "Categories").menu().actions()
             if a.text() == "Move to category").menu()))
    window.selection.picked = {"s0", "s1"}
    window.selection.menu(QPoint(0, 0))
    sub, = seen
    assert [a.text() for a in sub.actions()] == ["lol"]
    sub.actions()[0].trigger()
    assert window.meta("s0").tags == window.meta("s1").tags == ["lol"]
