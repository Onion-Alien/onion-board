"""Picking several pads (Ctrl / Shift+click, Ctrl+A) and changing them together, plus the
pads' keyboard and screen-reader side."""
import pytest
import numpy as np
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QAccessible, QColor, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QColorDialog, QMenu

from soundboard.i18n import _
from soundboard.sounds.library import PAD_COLORS, SoundMeta
from soundboard.ui.kit.widgets import Pad
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


def menu_shows(monkeypatch, look):
    """Menus open as a QMenu subclass that hands itself to `look` instead of blocking
    (Qt's own exec can't be patched on the class)."""
    from soundboard.ui.window import categorycontrol, mainwindow
    from soundboard.ui.sounds import padbatch

    class Shown(QMenu):
        def exec(self, *a):
            look(self)
    for mod in (mainwindow, padbatch, categorycontrol):
        monkeypatch.setattr(mod, "QMenu", Shown)


def key(pad, k, mods=Qt.NoModifier):
    QApplication.sendEvent(pad, QKeyEvent(QEvent.KeyPress, k, mods))


@pytest.mark.parametrize("colors", [(PAD_COLORS[0], PAD_COLORS[0]),
                                   (PAD_COLORS[0], PAD_COLORS[1])])
def test_bulk_colour_menu_marks_shared_value_and_applies_choice(window, colors):
    window.selection.picked = {"s0", "s1"}
    for sid, color in zip(("s0", "s1"), colors):
        window.meta(sid).color = color
    menu = QMenu(window)
    window.selection._fill_colors(menu)
    actions = [a for a in menu.actions() if not a.isSeparator()][:-1]   # minus Custom colour…
    assert all(action.isCheckable() for action in actions)
    # by name, not "#7c5cff"
    from soundboard.ui.sounds.dialogs import COLOUR_NAMES
    assert [a.text() for a in actions] == [COLOUR_NAMES[c] for c in PAD_COLORS]
    expected = [COLOUR_NAMES[colors[0]]] if colors[0] == colors[1] else []
    assert [action.text() for action in actions if action.isChecked()] == expected
    actions[1].trigger()
    assert all(window.meta(sid).color == PAD_COLORS[1] for sid in ("s0", "s1"))
    assert [a.text() for a in actions if a.isChecked()] == [COLOUR_NAMES[PAD_COLORS[1]]]


def test_bulk_category_menu_names_a_subcategory_s_parent(window):
    # a subcategory reads "Parent › sub", so one called like a category isn't a look-alike
    window.cfg.categories = ["Memes", "test"]
    window.cfg.subcategories = {"Memes": ["test"]}
    window.selection.picked = {"s0"}
    menu = QMenu(window)
    window.selection._fill_cats(menu)
    labels = [a.text() for a in menu.actions() if a.isCheckable()]
    assert labels == ["Memes", "Memes › test", "test"]


def test_bulk_menu_starts_with_its_actions_not_a_blank_section(window, monkeypatch):
    window.selection.picked = {"s0", "s1"}
    seen = []
    menu_shows(monkeypatch, lambda m: seen.extend(m.actions()))
    window.selection.menu(window.mapToGlobal(window.rect().center()))
    assert not seen[0].isSeparator() and seen[0].menu() is not None   # Colour


def test_category_colour_menu_is_the_bulk_one_with_no_colour(window, monkeypatch):
    """A category tab's Colour menu: names and a real tick, like the bulk one (it had
    a "  âœ“" typed after the name and bold text)."""
    from soundboard.ui.sounds.dialogs import COLOUR_NAMES
    w = window
    w.cfg.categories = ["Memes"]
    w.cfg.category_colors["Memes"] = PAD_COLORS[2]
    w.catctl._fill_categories()
    i = next(i for i in range(w.catctl.cat_tabs.count()) if w.catctl.cat_tabs.tabData(i) == "Memes")
    subs = []

    def grab(m):
        for act in m.actions():
            if act.menu() is not None and act.text() == _("Colour"):
                subs.append(act.menu().actions())
    menu_shows(monkeypatch, grab)
    w.catctl._category_menu(w.catctl.cat_tabs.tabRect(i).center())
    acts = [a for a in subs[0] if not a.isSeparator()]
    assert [a.text() for a in acts[:-2]] == [COLOUR_NAMES[c] for c in PAD_COLORS]
    assert acts[-2].text() == _("Custom colour…")
    assert [a.text() for a in acts if a.isChecked()] == [COLOUR_NAMES[PAD_COLORS[2]]]
    acts[-1].trigger()                                  # No colour
    assert not w.cfg.category_colors.get("Memes")

    # Custom colour…: the colour wheel's pick lands on the tab, and shows ticked next time
    monkeypatch.setattr(QColorDialog, "getColor", staticmethod(lambda *a: QColor("#123456")))
    acts[-2].trigger()
    assert w.cfg.category_colors["Memes"] == "#123456"
    subs.clear()
    w.catctl._category_menu(w.catctl.cat_tabs.tabRect(i).center())
    acts = [a for a in subs[0] if not a.isSeparator()]
    assert [a.text() for a in acts if a.isChecked()] == [_("Custom")]
    # a cancelled wheel changes nothing
    monkeypatch.setattr(QColorDialog, "getColor", staticmethod(lambda *a: QColor()))
    acts[-2].trigger()
    assert w.cfg.category_colors["Memes"] == "#123456"


def test_ctrl_click_toggles_and_shift_click_picks_a_range(window, monkeypatch):
    monkeypatch.setattr(Pad, "single_click", False)   # (Settings: Play pads with one click, off)
    w = window
    add_sounds(w, "A", "B")
    order = [p.meta.id for p in w.grid.pads]            # s0 s1 x0 x1
    played = []
    w.playctl.play = played.append
    for p in w.pads.values():                           # reconnect to the stub
        p.activated.disconnect()
        p.activated.connect(w.playctl.play)
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
    w.catctl.new_category(name="Memes")
    w.catctl.set_category("")
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
    from soundboard.ui.kit import toast
    assert any("2 sounds" in t.text() for t in toast.shown(w)) and not w.selection.picked
    w.rmctl.undo_remove()
    assert [m.id for m in w.cfg.sounds] == before
    assert set(w.pads) == set(before)


def test_right_click_on_a_picked_pad_opens_the_batch_menu(window, monkeypatch):
    w = window
    opened = []
    monkeypatch.setattr(w.selection, "menu", lambda pos: opened.append(pos))
    w.selection.picked = {"s0", "s1"}
    w.padctl.pad_menu("s0", None)
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


def test_tab_stops_once_on_the_pads_between_categories_and_player_bar(window, qapp):
    """Every pad was its own Tab stop, and the pads sat at the end of the Tab order (after
    the player bar): with 40 sounds, 40 Tabs to reach Stop all or Settings. Now Tab goes
    categories, one pad, the player bar; the arrows move between the pads."""
    from PySide6.QtTest import QTest
    w = window
    add_sounds(w, *(f"Pad {i}" for i in range(12)))
    w.resize(1180, 720)
    w.show()
    w.activateWindow()
    w.tabs.setCurrentWidget(w.sounds_page)
    qapp.processEvents()
    shown = [p for p in w.grid.pads if p.isVisible()]
    new_cat = w.catctl.btn_cat_add
    new_cat.setFocus(Qt.TabFocusReason)
    QTest.keyClick(new_cat, Qt.Key_Tab)
    assert QApplication.focusWidget() is shown[0]
    QTest.keyClick(shown[0], Qt.Key_Tab)
    after = QApplication.focusWidget()
    assert after.parentWidget() is w.btn_st.parentWidget()   # the player bar
    QTest.keyClick(after, Qt.Key_Backtab)
    assert QApplication.focusWidget() is shown[-1]   # back into the pads: the last one
    QTest.keyClick(shown[-1], Qt.Key_Backtab)
    assert QApplication.focusWidget() is new_cat


def test_click_selects_double_click_plays(window, monkeypatch):
    monkeypatch.setattr(Pad, "single_click", False)   # (Settings: Play pads with one click, off)
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
    QTest.mouseRelease(pad, Qt.LeftButton, pos=QPoint(10, 10))   # mouseDClick ends held
    assert played == ["s0"]
