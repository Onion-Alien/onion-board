"""A label icon placed on the first line's capital ink rather than its line box."""
import math
from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QPainter, QTextDocument
from PySide6.QtWidgets import QLabel, QSizePolicy

from soundboard.ui.kit import icons


class CapIcon(QLabel):
    """Follow a neighboring label's metrics at paint time, including live themes."""

    def __init__(self, label: QLabel, name: str, *, color: str = "muted", size: int = 18,
                 tip: str = ""):
        super().__init__()
        self.label, self.glyph_size = label, size
        self._rich_key, self._rich_line = None, (0.0, 0.0)
        self._ink_key, self._ink_mid = None, (size - 1) / 2
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
        if pm.cacheKey() != self._ink_key:
            img = pm.toImage()
            rows = [y for y in range(img.height())
                    if any(img.pixelColor(x, y).alpha() > 40 for x in range(img.width()))]
            if rows:
                self._ink_mid = (rows[0] + rows[-1]) / (2 * pm.devicePixelRatio())
            self._ink_key = pm.cacheKey()
        label = self.label
        fm = label.fontMetrics()
        text = label.text()
        rect = label.contentsRect()
        rich = label.textFormat() == Qt.TextFormat.RichText or "<" in text
        if rich:
            key = (text, label.font().key(), rect.width(), label.wordWrap())
            if key != self._rich_key:
                doc = QTextDocument()
                doc.setDocumentMargin(0)
                doc.setDefaultFont(label.font())
                doc.setHtml(text)
                doc.setTextWidth(rect.width() if label.wordWrap() else -1)
                height = doc.size().height()
                line = doc.firstBlock().layout().lineAt(0)
                self._rich_line = (height, line.y() + line.ascent())
                self._rich_key = key
            text_h, ascent = self._rich_line
        else:
            text_h, ascent = fm.height(), fm.ascent()
        if label.wordWrap() and not rich:
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
        base = math.floor(top + ascent + 0.5)
        # Ink ends on the row before the baseline, as in panel.heading_row().
        cap = base - (fm.capHeight() + 1) / 2
        origin = self.mapFromGlobal(label.mapToGlobal(QPoint()))
        painter = QPainter(self)
        painter.drawPixmap(0, round(origin.y() + cap - self._ink_mid), pm)
        painter.end()
