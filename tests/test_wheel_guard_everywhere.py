"""Every dropdown, slider and number box on a scrolling page ignores the mouse wheel.

Scrolling down a page and passing over one used to change it (the Voice tab's
"Speak in" language jumped while the user was just scrolling). The guard is
installed per widget (wheelguard.py), so this walks the real window and Settings
and names any control a new panel forgot to guard."""
from PySide6.QtWidgets import (QAbstractScrollArea, QAbstractSlider, QAbstractSpinBox,
                               QComboBox, QScrollBar, QWidget)

from soundboard.settings import SettingsDialog
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)


def _unguarded(root: QWidget) -> list[str]:
    out = []
    for w in root.findChildren(QWidget):
        if not isinstance(w, (QComboBox, QAbstractSlider, QAbstractSpinBox)) \
                or isinstance(w, QScrollBar) or w.property("noWheel"):
            continue
        p = w.parentWidget()
        while p is not None and not isinstance(p, QAbstractScrollArea):
            p = p.parentWidget()
        if p is None:
            continue   # not on a scrolling page: the wheel has nothing else to do
        out.append(f"{type(w).__name__} {w.objectName() or w.accessibleName() or ''} "
                   f"in {type(w.parentWidget()).__name__}")
    return out


def test_main_window_controls_ignore_the_wheel(window):  # noqa: F811
    assert _unguarded(window) == []


def test_settings_controls_ignore_the_wheel(window):  # noqa: F811
    d = SettingsDialog(window, "audio")
    try:
        for i in range(d.tabs.count()):
            d.tabs.setCurrentIndex(i)   # pages build on first show
        assert _unguarded(d) == []
    finally:
        d.close()
