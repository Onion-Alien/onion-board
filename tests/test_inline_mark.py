"""The tick and cross inside status text sit level with the words, in every theme's
font, with a little space either side (Bahnschrift dropped them 4 px low)."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontMetricsF, QImage, QPainter, QTextDocument

from soundboard.style.palettes import font_families
from soundboard.ui import icons


def _rows(img: QImage, x0: int, x1: int) -> list[int]:
    return [y for y in range(img.height())
            if any(img.pixelColor(x, y).alpha() > 128 for x in range(x0, x1))]


def test_mark_is_level_with_the_words(qapp):
    for family in font_families():
        font = QFont(family)
        font.setPointSizeF(10)
        doc = QTextDocument()
        doc.setDefaultFont(font)
        doc.setDocumentMargin(0)
        doc.setHtml("H" + icons.inline("check", "#13ce66", font=font))
        img = QImage(doc.size().toSize(), QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        doc.drawContents(p)
        p.end()
        split = int(QFontMetricsF(font).horizontalAdvance("H")) + 1
        h = _rows(img, 0, split)
        mark = _rows(img, split, img.width())
        assert h and mark, family
        # middles within a pixel (in half pixels, so the sums)
        assert abs((mark[0] + mark[-1]) - (h[0] + h[-1])) <= 2, family
        cols = [x for x in range(split, img.width())
                if any(img.pixelColor(x, y).alpha() > 128 for y in mark)]
        assert cols[0] - split >= icons._INLINE_GAP - 1, family   # not on the "H"
