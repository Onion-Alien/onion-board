"""A dropdown's list and a button's menu open a short gap from their button, never stuck
to its edge (wheelguard.drop_gap, through the app style): the Store tab's category list
sat right on its button."""
import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QComboBox, QMenu, QPushButton, QWidget

from soundboard.ui.kit.widgets import DropdownMenu
from soundboard.ui.kit.wheelguard import DROP_GAP


def _pump():
    for _ in range(8):
        QApplication.processEvents()


def _gap(opener: QWidget, popup: QWidget) -> int:
    top = opener.mapToGlobal(QPoint(0, 0)).y()
    g = popup.geometry()
    if g.top() >= top:
        return g.top() - (top + opener.height())
    return top - (g.bottom() + 1)


@pytest.fixture
def host(qapp):
    w = QWidget()
    w.resize(300, 200)
    screen = qapp.primaryScreen().availableGeometry()
    w.move(screen.left() + 100, screen.top() + 100)
    w.show()
    yield w
    w.close()
    w.deleteLater()


def test_a_dropdown_list_opens_a_gap_under_its_box(host):
    cb = QComboBox(host)
    cb.addItems([f"Choice {i}" for i in range(6)])
    cb.move(20, 20)
    cb.show()
    _pump()
    cb.showPopup()
    _pump()
    view = cb.view().window()
    try:
        assert view.isVisible()
        assert _gap(cb, view) == DROP_GAP
    finally:
        cb.hidePopup()


@pytest.mark.parametrize("cls", [QMenu, DropdownMenu])
def test_a_button_menu_opens_a_gap_under_it_once(host, cls):
    btn = QPushButton("Pick", host)
    btn.move(20, 20)
    btn.show()
    menu = cls(btn)
    for i in range(3):
        menu.addAction(f"Item {i}")
    btn.setMenu(menu)
    _pump()
    menu.popup(btn.mapToGlobal(btn.rect().bottomLeft()) + QPoint(0, 1))
    _pump()
    try:
        assert _gap(btn, menu) == DROP_GAP   # (DropdownMenu: not twice)
    finally:
        menu.hide()


def test_a_menu_near_the_screen_bottom_opens_a_gap_above(host, qapp):
    screen = qapp.primaryScreen().availableGeometry()
    btn = QPushButton("Pick")
    btn.resize(80, 28)
    btn.move(screen.left() + 100, screen.bottom() - 30)
    btn.show()
    menu = QMenu(btn)
    for i in range(5):
        menu.addAction(f"Item {i}")
    btn.setMenu(menu)
    _pump()
    try:
        top = btn.mapToGlobal(QPoint(0, 0))
        menu.popup(QPoint(top.x(), top.y() - menu.sizeHint().height()))
        _pump()
        assert _gap(btn, menu) == DROP_GAP
    finally:
        menu.hide()
        btn.close()
        btn.deleteLater()


def test_a_context_menu_stays_where_it_was_asked(host):
    menu = QMenu(host)
    menu.addAction("Item")
    at = host.mapToGlobal(QPoint(30, 30))
    menu.popup(at)
    _pump()
    try:
        assert menu.pos() == at
    finally:
        menu.hide()


class _Counted(QPushButton):
    asked = 0

    def menu(self):
        _Counted.asked += 1
        return super().menu()


def test_a_menu_set_on_a_button_elsewhere_finds_it_with_one_look_per_button(host):
    """A menu owned by a deep widget, set on a button beside it: still opens under that
    button, and each button is asked once per popup, not once per parent (a menu deep in
    the window asked every button in the app ~28 times, and froze a PC low on memory)."""
    deep = host
    for _ in range(12):
        deep = QWidget(deep)
    others = [_Counted(f"B{i}", deep) for i in range(19)]   # under every parent
    btn = _Counted("Pick", host)
    btn.move(20, 20)
    btn.show()
    menu = QMenu(deep)
    menu.addAction("Item")
    btn.setMenu(menu)
    _pump()
    _Counted.asked = 0
    menu.popup(btn.mapToGlobal(btn.rect().bottomLeft()) + QPoint(0, 1))
    _pump()
    try:
        assert menu._click_opener is btn
        assert _gap(btn, menu) == DROP_GAP
        assert _Counted.asked <= len(others) + 1
    finally:
        menu.hide()
