"""Picking several pads (Ctrl / Shift+click, Ctrl+A) and changing them together, plus the
pads' keyboard and screen-reader side."""
import pytest
import numpy as np
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QAccessible, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from soundboard.library import SoundMeta
from test_mainwindow import window as main_window  # noqa: F401  (the real MainWindow)


@pytest.fixture
def window(main_window):  # noqa: F811
    return main_window


def add_sounds(w, *names):
    for i, n in enumerate(names):
        m = SoundMeta(id=f"x{i}", name=n, file=f"{n}.wav", duration=1.0)
        w.cfg.sounds.append(m)
        w.audio[m.id] = np.zeros((480, 2), np.float32)
    w._rebuild_pads()


def click(pad, mods=Qt.NoModifier):
    pos = QPointF(pad.rect().center())
    for kind in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
        QApplication.sendEvent(pad, QMouseEvent(kind, pos, pad.mapToGlobal(pos),
                                                Qt.LeftButton, Qt.LeftButton, mods))


def key(pad, k, mods=Qt.NoModifier):
    QApplication.sendEvent(pad, QKeyEvent(QEvent.KeyPress, k, mods))


def test_ctrl_click_toggles_and_shift_click_picks_a_range(window):
    w = window
    add_sounds(w, "A", "B")
    order = [p.meta.id for p in w.grid.pads]            # s0 s1 x0 x1
    played = []
    w.play = played.append
    for p in w.pads.values():                           # reconnect to the stub
        p.activated.disconnect()
        p.activated.connect(w.play)
    click(w.pads["s0"], Qt.ControlModifier)
    assert w.selection.picked == {"s0"} and w.pads["s0"].picked
    assert not w.selection.bar.isHidden()
    click(w.pads[order[3]], Qt.ShiftModifier)
    assert w.selection.picked == set(order)
    click(w.pads["s1"], Qt.ControlModifier)
    assert "s1" not in w.selection.picked
    assert played == []                                 # picking never plays
    click(w.pads["s1"])
    assert played == [] and w.current == "s1"           # a plain click only selects
    w.selection.clear()
    assert not w.selection.picked and w.selection.bar.isHidden()
    assert not any(p.picked for p in w.pads.values())


def test_select_all_takes_only_what_is_shown(window):
    w = window
    w.search.setText("boom")
    w.selection.select_all()
    assert w.selection.picked == {"s0"}
    w.selection.picked = {"s0", "s1"}
    w.search.setText("air")                             # s0 filtered away: unpicked
    assert w.selection.picked == {"s1"}


def test_batch_colour_volume_fades_and_category(window):
    w = window
    w.selection.select_all()
    w.selection.set_color("#123456")
    w.selection.set_volume(1.5)
    w.selection.set_fades(0.5, None)
    assert all(m.color == "#123456" and m.volume == 1.5 for m in w.cfg.sounds)
    assert all(m.fade_in == 0.5 and m.fade_out == 0.0 for m in w.cfg.sounds)
    w.new_category(name="Memes")
    w.set_category("")
    w.selection.select_all()
    w.selection.set_category("Memes", True)
    assert all("Memes" in m.tags for m in w.cfg.sounds)
    w.selection.set_category("Memes", False)
    assert not any(m.tags for m in w.cfg.sounds)


def test_batch_delete_asks_first_then_undoes_in_one_go(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    w = window
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.Cancel)
    add_sounds(w, "A", "B")
    w.selection.picked = {"s1"}
    w.selection.delete()                           # said no: nothing removed
    assert len(w.cfg.sounds) == 4 and w.selection.picked == {"s1"}
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.Yes)
    before = [m.id for m in w.cfg.sounds]
    w.selection.picked = {"s1", "x1"}
    w.selection.delete()
    assert [m.id for m in w.cfg.sounds] == ["s0", "x0"]
    assert "2 sounds" in w.undo_lbl.text() and not w.selection.picked
    w.undo_remove()
    assert [m.id for m in w.cfg.sounds] == before
    assert set(w.pads) == set(before)


def test_right_click_on_a_picked_pad_opens_the_batch_menu(window, monkeypatch):
    w = window
    opened = []
    monkeypatch.setattr(w.selection, "menu", lambda pos: opened.append(pos))
    w.selection.picked = {"s0", "s1"}
    w.pad_menu("s0", None)
    assert len(opened) == 1


def test_pads_are_buttons_a_screen_reader_can_read(window):
    w = window
    pad = w.pads["s0"]
    iface = QAccessible.queryAccessibleInterface(pad)
    assert iface.role() == QAccessible.Button
    assert iface.text(QAccessible.Name) == "Boom"
    pad.set_picked(True)
    assert "selected" in pad.accessibleDescription()
    w.meta("s0").hotkey = "ctrl+1"
    pad.describe()
    assert "hotkey Ctrl+1" in pad.accessibleDescription()


def test_keyboard_plays_picks_and_moves_focus(window):
    w = window
    played = []
    pad = w.pads["s0"]
    pad.activated.disconnect()
    pad.activated.connect(played.append)
    key(pad, Qt.Key_Return)
    assert played == ["s0"]
    key(pad, Qt.Key_Space, Qt.ControlModifier)
    assert w.selection.picked == {"s0"}
    moved = []
    pad.step.disconnect()
    pad.step.connect(lambda p, dx, dy: moved.append((p.meta.id, dx, dy)))
    key(pad, Qt.Key_Right)
    assert moved == [("s0", 1, 0)]


def test_click_selects_double_click_plays(window):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    w = window
    played = []
    pad = w.pads["s0"]
    pad.activated.disconnect()
    pad.activated.connect(played.append)
    QTest.mouseClick(pad, Qt.LeftButton, pos=QPoint(10, 10))
    assert played == [] and w.current == "s0"
    QTest.mouseDClick(pad, Qt.LeftButton, pos=QPoint(10, 10))
    assert played == ["s0"]
