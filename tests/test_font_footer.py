"""The mixer's icon ink follows its words, including live font changes."""
import pytest
import numpy as np
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QLabel
from test_mainwindow import window  # noqa: F401


def pixels(widget):
    img = widget.grab().toImage()
    img = img.convertToFormat(img.Format.Format_RGBA8888)
    return np.asarray(img.bits()).reshape(img.height(), img.width(), 4).copy()


def ink_middle(widget, parent, capital=False):
    before = pixels(widget)
    text, pixmap = widget.text(), widget.pixmap()
    widget.clear()
    after = pixels(widget)
    if text:
        widget.setText(text)
    else:
        widget.setPixmap(pixmap)
    mask = np.max(np.abs(before.astype(int) - after.astype(int)), axis=2) > 45
    ys, xs = np.where(mask)
    assert len(ys)
    if capital:
        ys = ys[xs < min(xs) + widget.fontMetrics().horizontalAdvance(text[0])]
    return (min(ys) + max(ys)) / 2 + widget.mapTo(parent, QPoint()).y()


@pytest.mark.parametrize("name", ["Dark", "Amber Terminal", "Comic Sans"])
def test_footer_icon_capitals_stay_level(window, name):  # noqa: F811
    window.show()
    window.resize(1700, 900)
    window.apply_theme(name)
    for _ in range(8):
        QApplication.processEvents()
        window._refit()
    marks = [w for w in window.mixer.findChildren(QLabel) if not w.pixmap().isNull()]
    assert len(marks) == 3
    for mark in marks:
        label = mark.parentWidget().findChild(QLabel, "decktitle")
        assert abs(ink_middle(mark, window.mixer)
                   - ink_middle(label, window.mixer, capital=True)) <= 1, label.text()
