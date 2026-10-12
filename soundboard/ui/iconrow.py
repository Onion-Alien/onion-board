"""A label icon placed on the first line's capital ink rather than its line box."""
import math
from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QPainter, QTextDocumentFragment
from PySide6.QtWidgets import QLabel, QSizePolicy

from soundboard.ui import icons


class CapIcon(QLabel):
    """Follow a neighboring label's metrics at paint time, including live themes."""

    def __init__(self, label: QLabel, name: str, *, color: str = "muted", size: int = 18,
                 tip: str = ""):
        super().__init__()
        self.label, self.glyph_size = label, size
        self.setFixedWidth(size)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setToolTip(tip)
        icons.set_label_icon(self, name, color, size)
        label.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange,
                            QEvent.Type.Resize, QEvent.Type.Show):
            self.updateGeometry()
            self.update()
        return False

    def sizeHint(self):
        fm = self.label.fontMetrics()
        # Enough room on both sides of the capital for a taller icon, even when the
        # line's ascent/descent are asymmetric. The containing row may grow further.
        return QSize(self.glyph_size, max(self.glyph_size,
                     fm.height() + self.glyph_size - fm.capHeight()))

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, event):
        pm = self.pixmap()
        if pm.isNull():
            return
        label = self.label
        fm = label.fontMetrics()
        text = label.text()
        if label.textFormat() == Qt.TextFormat.RichText or "<" in text:
            text = QTextDocumentFragment.fromHtml(text).toPlainText()
        rect = label.contentsRect()
        text_h = fm.height()
        if label.wordWrap():
            block = fm.boundingRect(QRect(0, 0, rect.width(), 100000),
                                    int(Qt.TextFlag.TextWordWrap), text)
            lines = max(1, round(block.height() / fm.lineSpacing()))
            text_h += (lines - 1) * fm.lineSpacing()
        align = label.alignment()
        top = rect.top()
        if align & Qt.AlignmentFlag.AlignVCenter:
            top += (rect.height() - text_h) / 2
        elif align & Qt.AlignmentFlag.AlignBottom:
            top += rect.height() - text_h
        base = math.floor(top + fm.ascent() + 0.5)
        cap = base - fm.capHeight() / 2
        origin = self.mapFromGlobal(label.mapToGlobal(QPoint()))
        painter = QPainter(self)
        painter.drawPixmap(0, round(origin.y() + cap - (self.glyph_size - 1) / 2), pm)
        painter.end()
