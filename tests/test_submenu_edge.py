"""A submenu opens just outside its menu, never over its edge: on the right, flipped
to the left near the screen's edge, and right to left (wheelguard.AppStyle)."""
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu


def _pump():
    for _ in range(8):
        QApplication.processEvents()


@pytest.mark.parametrize("rtl", [False, True])
@pytest.mark.parametrize("near_right_edge", [False, True])
def test_a_submenu_never_covers_its_menu(qapp, rtl, near_right_edge):
    QApplication.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
    menu = QMenu()
    try:
        for i in range(4):
            menu.addAction(f"Item {i}")
        sub = menu.addMenu("More")
        for i in range(3):
            sub.addAction(f"Sub {i}")
        screen = qapp.primaryScreen().availableGeometry()
        x = screen.right() - 260 if near_right_edge else screen.left() + 200
        menu.popup(QPoint(x, screen.top() + 100))
        _pump()
        menu.setActiveAction(sub.menuAction())
        QTest.keyClick(menu, Qt.Key_Left if rtl else Qt.Key_Right)
        _pump()
        assert sub.isVisible()
        pg, g = menu.geometry(), sub.geometry()
        gap = g.left() - pg.right() - 1 if g.left() > pg.center().x() else \
            pg.left() - g.right() - 1
        assert 0 < gap <= 4, (pg, g)
        first = sub.actionGeometry(sub.actions()[0])
        item = menu.actionGeometry(sub.menuAction())
        assert sub.mapToGlobal(first.topLeft()).y() == menu.mapToGlobal(item.topLeft()).y()
    finally:
        menu.hide()
        menu.deleteLater()
        QApplication.setLayoutDirection(Qt.LeftToRight)
