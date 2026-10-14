"""Right-click menus that really open.

Most menu tests swap QMenu.exec for a stub that records the entries, so the code that runs
only when a menu shows (the popup filters in wheelguard.py, aboutToShow, submenu placement)
never ran in a test. 2.0.2 raised TypeError there on every right-click of a pad or a sidebar
tab, and the user got a crash report, while every test passed. Here each menu opens for real
(offscreen), its submenus open the way the keyboard opens them, and it closes with Escape.
An exception on the way fails the test (conftest's crash-report check)."""
from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QContextMenuEvent, QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu

from test_mainwindow import window as main_window  # noqa: F401  (the real MainWindow)


def _key(w, key):
    QApplication.sendEvent(w, QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


def _visible_menus():
    return [w for w in QApplication.topLevelWidgets() if isinstance(w, QMenu) and w.isVisible()]


class _Hand(QObject):
    """Sees each menu show, then opens its submenus and closes it, inside the menu's own loop."""

    def __init__(self):
        super().__init__()
        self.shown: list[list[str]] = []
        self._busy = False

    def eventFilter(self, obj, ev):  # noqa: N802 (Qt name)
        if ev.type() == QEvent.Type.Show and isinstance(obj, QMenu) and not self._busy:
            QTimer.singleShot(0, lambda m=obj: self._drive(m))
        return False

    def _drive(self, menu):
        if not menu.isVisible():
            return
        self._busy = True
        self.shown.append([a.text() for a in menu.actions()])
        for a in menu.actions():
            if a.menu() is not None and a.isVisible() and a.isEnabled():
                menu.setActiveAction(a)
                _key(menu, Qt.Key.Key_Right)
                QApplication.processEvents()
                if a.menu().isVisible():
                    _key(a.menu(), Qt.Key.Key_Escape)
        self._busy = False
        for m in reversed(_visible_menus()):
            _key(m, Qt.Key.Key_Escape)
        if menu.isVisible():
            menu.hide()


def _context_menu(w, pos: QPoint):
    ev = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, pos, w.mapToGlobal(pos))
    QApplication.sendEvent(w, ev)


def test_right_click_menus_really_open(main_window):  # noqa: F811
    w = main_window
    w.resize(1100, 750)
    w.show()
    w.new_category("s0", "Memes")      # a category tab to right-click as well
    sounds = next(b for b in w.rail.buttons if b.accessibleName() == "Sounds")
    QTest.mouseClick(sounds, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    w.cat_tabs.setCurrentIndex(0)      # All: every pad
    hand = _Hand()
    app = QApplication.instance()
    app.installEventFilter(hand)
    try:
        pads = [p for p in w.pads.values() if p.isVisible()]
        assert len(pads) >= 2, "the board shows no pads to right-click"
        for p in pads:                                   # a pad's own menu
            QTest.mouseClick(p, Qt.MouseButton.RightButton)
        rail = [b for b in w.rail.buttons if b.isVisible()]
        for b in rail:                                   # each sidebar tab's menu
            _context_menu(b, b.rect().center())
        bar = w.cat_tabs
        for i in range(bar.count()):                     # each category tab's menu
            _context_menu(bar, bar.tabRect(i).center())
        for p in pads[:2]:                               # two picked pads: the menu for both
            QTest.mouseClick(p, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier)
        QTest.mouseClick(pads[0], Qt.MouseButton.RightButton)
        pads[1].setFocus()                               # the keyboard's menu key
        QTest.keyClick(pads[1], Qt.Key.Key_Menu)
    finally:
        app.removeEventFilter(hand)
    assert not _visible_menus(), "a menu stayed open"
    expected = len(pads) + len(rail) + (bar.count() - 1) + 2     # the built-in All tab has none
    assert len(hand.shown) >= expected, f"{len(hand.shown)} of {expected} opened: {hand.shown}"
    assert any("Rename" in m for m in hand.shown), hand.shown
