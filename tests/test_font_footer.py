"""The mixer's icon ink follows its words, including live font changes."""
import os
from pathlib import Path

import pytest
import numpy as np
from PySide6.QtCore import QPoint
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QLabel
from test_mainwindow import window  # noqa: F401

@pytest.fixture(autouse=True)
def pixel_fonts(qapp):
    """Load real glyphs for these pixel checks without changing other tests' fonts."""
    font_dir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    ids = [QFontDatabase.addApplicationFont(str(font_dir / name))
           for name in ("bahnschrift.ttf", "consola.ttf", "consolab.ttf", "comic.ttf",
                        "comicbd.ttf") if (font_dir / name).is_file()]
    yield
    for font_id in ids:
        if font_id >= 0:
            QFontDatabase.removeApplicationFont(font_id)


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
        rows = set(ys)
        end = min(rows)
        while end + 1 in rows:
            end += 1
        ys = ys[ys <= end]   # first line only, even when another line starts below it
    return (min(ys) + max(ys)) / 2 + widget.mapTo(parent, QPoint()).y()


@pytest.mark.parametrize("name", ["Dark", "Amber Terminal", "Comic Sans"])
def test_footer_icon_capitals_stay_level(window, name):  # noqa: F811
    window.show()
    window.resize(1700, 900)
    window.themectl.apply_theme(name)
    for _ in range(8):
        QApplication.processEvents()
        window.fitctl._refit()
    marks = [w for w in window.mixer.findChildren(QLabel) if not w.pixmap().isNull()]
    assert len(marks) == 3
    for mark in marks:
        label = mark.parentWidget().findChild(QLabel, "decktitle")
        assert abs(ink_middle(mark, window.mixer)
                   - ink_middle(label, window.mixer, capital=True)) <= 1, label.text()
