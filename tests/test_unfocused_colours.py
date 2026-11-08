"""Gaining or losing focus (Alt+Tab) must not repaint the whole window."""
from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from soundboard.core.app import same_colours_unfocused


class _Paints(QObject):
    def __init__(self):
        super().__init__()
        self.n = 0

    def eventFilter(self, o, e):
        if e.type() == QEvent.Type.Paint:
            self.n += 1
        return False


def test_focus_change_repaints_nothing(qapp):
    before = qapp.palette()
    try:
        # what Windows hands Qt: another selection colour for a window without focus
        pal = QPalette(before)
        pal.setColor(QPalette.ColorGroup.Inactive, QPalette.ColorRole.Highlight, QColor("#1e1e1e"))
        qapp.setPalette(pal)
        same_colours_unfocused(qapp)
        got = qapp.palette()
        assert got.isEqual(QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive)
        assert got.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Highlight) == \
            pal.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Highlight)

        w = QWidget()
        lay = QVBoxLayout(w)
        for i in range(20):
            lay.addWidget(QLabel(f"pad {i}"))
        w.show()
        for _ in range(5):
            qapp.processEvents()
        paints = _Paints()
        qapp.installEventFilter(paints)
        try:
            for kind in (QEvent.Type.WindowDeactivate, QEvent.Type.WindowActivate) * 3:
                QApplication.sendEvent(w, QEvent(kind))
                qapp.processEvents()
        finally:
            qapp.removeEventFilter(paints)
            w.close()
        assert paints.n == 0
    finally:
        qapp.setPalette(before)
