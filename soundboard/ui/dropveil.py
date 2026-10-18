"""The veil over the window while files are dragged onto it: "Drop to add 4 files".

Files can be dropped anywhere on the window, not only on the outlined box, so while a
drag is over it the whole window says so. It watches drags for the window (an
application event filter, since the pads' grid and other children take drags before
the window sees them) and never takes a drop itself: it lets mouse and drag events
through to whatever is under it. Pictures aren't announced: dropped on a pad they
become its picture, not a new sound.
"""
from __future__ import annotations

from pathlib import PurePath

from PySide6.QtCore import QEvent, QObject, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QDragEnterEvent, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from soundboard.ui.kit import theme
from soundboard.i18n import _, ngettext
from soundboard.ui.kit import icons
from soundboard.ui.kit.pixels import snap_to_pixels

PICTURE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".jfif"}


def label_for(paths: list[str]) -> str | None:
    """What the veil says for these dragged paths, or None to stay hidden."""
    if not paths or all(PurePath(p).suffix.lower() in PICTURE_EXTS for p in paths):
        return None
    if any(not PurePath(p).suffix for p in paths):   # a folder: its count isn't known yet
        return _("Drop to add sounds")
    return ngettext("Drop to add {n} file", "Drop to add {n} files", len(paths))


class DropVeil(QWidget):
    EVENTS = (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.DragLeave,
              QEvent.Type.Drop)   # all its eventFilter reads (theme.app_filter)

    def __init__(self, window: QWidget):
        super().__init__(window)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAccessibleName(_("Drop files"))
        self.text = ""
        self._window = window
        # a drag moving from one child to the next leaves one and enters the other:
        # only hide when it's really left the window
        # (PySide takes properties and signals as keywords; the stubs don't know)
        self._leave = QTimer(self, singleShot=True, interval=60, timeout=self._check_left)   # pyright: ignore[reportCallIssue]
        self.hide()
        app = QApplication.instance()
        assert app is not None
        theme.app_filter(app, self)   # (sits out theme switches: 49,000 events each)

    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:
        t = ev.type()
        if t in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.DragLeave,
                 QEvent.Type.Drop) \
                and isinstance(obj, QWidget) and obj.window() is self._window:
            if t == QEvent.Type.DragEnter and isinstance(ev, QDragEnterEvent):
                self._leave.stop()
                paths = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()] \
                    if ev.mimeData().hasUrls() else []
                self.show_for(label_for(paths))
            elif t == QEvent.Type.DragLeave:
                self._leave.start()
            elif t == QEvent.Type.Drop:
                self.hide()
        return False

    def _check_left(self):
        if not self._window.rect().contains(self._window.mapFromGlobal(QCursor.pos())):
            self.hide()

    def show_for(self, text: str | None):
        if not text:
            self.hide()
            return
        self.text = text
        self.setGeometry(self._window.rect())
        self.raise_()
        self.show()
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = QColor(theme.T.get("bg", "#000"))
        bg.setAlpha(200)
        p.fillRect(self.rect(), bg)
        accent = QColor(theme.T.get("accent", "#7c5cff"))
        pen = QPen(accent, 2)
        p.setPen(pen)
        tint = QColor(accent)
        tint.setAlpha(28)
        p.setBrush(tint)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(14, 14, -14, -14), 16, 16)
        # the label: a pill in the middle, icon then words
        f = QFont(self.font())
        f.setPointSizeF(f.pointSizeF() * 1.3)
        f.setBold(True)
        fm = QFontMetrics(f)
        icon_px = 28
        w = icon_px + 12 + fm.horizontalAdvance(self.text) + 48
        h = max(icon_px, fm.height()) + 28
        pill = QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(accent)
        p.drawRoundedRect(pill, h / 2, h / 2)
        on = theme.T.get("on_accent", "#fff")
        rtl = self.isRightToLeft()
        ix = pill.right() - 24 - icon_px if rtl else pill.left() + 24
        p.drawPixmap(int(ix), int(pill.center().y() - icon_px / 2),
                     icons.pixmap("plus", icon_px, on))
        p.setPen(QColor(on))
        p.setFont(f)
        text_rect = pill.adjusted(24 + icon_px + 12, 0, -24, 0) if not rtl \
            else pill.adjusted(24, 0, -(24 + icon_px + 12), 0)
        p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeading,
                   self.text)
        p.end()
