"""How the saved clips list (ui/apps/clipshelf.py) draws its rows: the row sizes, the
`ClipRowDelegate` that paints a clip's play button, name, "where · when", waveform, Live pill
and length (and a group's label), the clips' length and date text, and the handle that resizes
the list. `clipshelf` re-exports it all."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from PySide6.QtCore import QDate, QEvent, QRect, QSize, QTime, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QToolTip, QWidget

from soundboard.i18n import _
from soundboard.ui.kit import icons, theme

if TYPE_CHECKING:
    from soundboard.ui.apps.clipshelf import ClipShelf


ROW_H = 44               # a clip's row
GROUP_H = 30             # a group's label ("Discord (12)")


ID = Qt.ItemDataRole.UserRole

# a row, left to right (mirrored for right-to-left languages)
PLAY_D = 32              # the round play button
NAME_W = 220             # name and the "where · when" line under it
WAVE_W = 260             # the waveform, when there's room
LIVE_W = 48              # the Live pill (room kept, so the length never jumps)
LEN_W = 44               # "0:03"
ACT = 28                 # one of the row's buttons
ACTS_W = 3 * ACT + 2 * 2
INDENT = 16              # a row inside a group


def length_text(seconds: float) -> str:
    s = max(0, round(seconds))
    return f"{s // 60}:{s % 60:02d}"


def when_text(made: float, today: date | None = None) -> str:
    """"Today 14:02", "Yesterday", then the date."""
    try:
        d = datetime.fromtimestamp(made)
    except (ValueError, OverflowError, OSError):
        return ""
    today = today or date.today()
    if d.date() == today:
        t = QTime(d.hour, d.minute).toString(_locale_time())
        return _("Today {time}", time=t)
    if d.date() == today - timedelta(days=1):
        return _("Yesterday")
    q = QDate(d.year, d.month, d.day)
    return q.toString("d MMM" if d.year == today.year else "d MMM yyyy")


def depth(index) -> int:
    """How many groups a row is inside (the delegate indents it; the tree's own
    indentation is off, so it draws no branch arrows of its own)."""
    d, parent = 0, index.parent()
    while parent.isValid():
        d, parent = d + 1, parent.parent()
    return d


def _locale_time() -> str:
    from PySide6.QtCore import QLocale
    return QLocale().timeFormat(QLocale.FormatType.ShortFormat)


class ClipResizeHandle(QWidget):
    """A mouse and keyboard grip for the saved clips, inside the scrolling page."""

    def __init__(self, shelf):
        super().__init__(shelf)
        self.shelf = shelf
        self.setFixedHeight(20)
        self.setCursor(Qt.CursorShape.SplitVCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        tip = _("Drag to resize saved clips. Double-click to fit the clips.")
        self.setToolTip(tip)
        self.setAccessibleName(tip)
        self._drag = None

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(theme.T["accent"] if self.hasFocus() else theme.T["faint"]), 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        mid = self.width() // 2
        p.drawLine(mid - 16, 10, mid + 16, 10)   # one rounded grip, like a sheet's
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self._drag = (event.globalPosition().y(), self.shelf.list.height())
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag is not None:
            y, height = self._drag
            self.shelf.resize_clips(height + event.globalPosition().y() - y)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag = None

    def mouseDoubleClickEvent(self, event):
        self._drag = None
        self.shelf.resize_clips(0)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.shelf.resize_clips(self.shelf.list.height()
                                    + (36 if event.key() == Qt.Key.Key_Down else -36))
        elif event.key() == Qt.Key.Key_Home:
            self.shelf.resize_clips(0)
        else:
            super().keyPressEvent(event)


class ClipRowDelegate(QStyledItemDelegate):
    """Paints a clip's row (see the module's docstring) and a group's label, and
    handles a click on the round play button."""

    def __init__(self, shelf: ClipShelf):
        super().__init__(shelf.list)
        self.s = shelf
        self.pressed_play = False   # the last press was on a round play button
        self._double = False        # ...and became a double-click: its release does nothing

    def sizeHint(self, option, index):
        return QSize(0, ROW_H if index.data(ID) else GROUP_H)

    # ------------------------------------------------------------------ paint
    def paint(self, p: QPainter, option, index):
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        T = theme.T
        r = QRect(option.rect)
        cid = index.data(ID)
        if not cid:
            self._paint_group(p, option, index, r)
            p.restore()
            return
        c = self.s._clips.get(cid)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        L = self.s.row_layout(r, depth(index))
        if selected or hover:   # neutral, never the accent (DESIGN: lists)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(T["btn_hover" if selected else "card_hi"]))
            p.drawRoundedRect(L.row.adjusted(0, 1, 0, -1), 6, 6)
        now = self.s._playing
        playing = now is not None and now[1] == cid
        sending = now == (self.s._send_sid, cid)
        # the round play button: accent while it plays
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(T["accent"] if playing else T["btn"]))
        p.drawEllipse(L.play)
        glyph = "stop" if playing else "play"
        icons.icon(glyph, "on_accent" if playing else "text_hi").paint(
            p, L.play.adjusted(9, 9, -9, -9))
        # name, then "where · when"
        name_font = QFont(option.font)
        name_font.setBold(True)
        p.setFont(name_font)
        p.setPen(QColor(T["text_hi"]))
        fm = QFontMetrics(name_font)
        name = index.data(Qt.ItemDataRole.DisplayRole) or ""
        align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        p.drawText(L.name, align, fm.elidedText(name, Qt.TextElideMode.ElideRight,
                                                L.name.width()))
        small = QFont(option.font)
        small.setPointSizeF(max(7.5, option.font.pointSizeF() * 0.85))
        p.setFont(small)
        p.setPen(QColor(T["muted"]))
        sub = " · ".join(x for x in ((c.src if c else ""), (when_text(c.made) if c else "")) if x)
        p.drawText(L.sub, align, QFontMetrics(small).elidedText(
            sub, Qt.TextElideMode.ElideRight, L.sub.width()))
        # the waveform: the played part in the accent
        if L.wave is not None and c is not None:
            self._paint_wave(p, L.wave, c.peaks, self.s._progress if playing else 0.0)
        # Live: going out through the mic (a word with the colour, not colour alone)
        if sending:
            pill = L.live.adjusted(0, (L.live.height() - 20) // 2, 0, -(L.live.height() - 20) // 2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(T["accent"]))
            p.drawRoundedRect(pill, 10, 10)
            p.setPen(QColor(T["on_accent"]))
            bold = QFont(small)
            bold.setBold(True)
            p.setFont(bold)
            p.drawText(pill, Qt.AlignmentFlag.AlignCenter, _("Live"))
        # the length, in steady digits
        digits = QFont(small)
        digits.setPointSizeF(option.font.pointSizeF() * 0.95)
        digits.setFeature(QFont.Tag("tnum"), 1)   # same-width digits: 0:11 lines up with 0:03
        p.setFont(digits)
        p.setPen(QColor(T["muted"]))
        p.drawText(L.length, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   length_text(c.seconds) if c else "")
        p.restore()

    def _paint_group(self, p, option, index, r):
        it = self.s.list.itemFromIndex(index)
        open_ = it is not None and it.isExpanded()
        r = self.s.row_layout(r, depth(index)).row
        rtl = self.s.list.layoutDirection() == Qt.LayoutDirection.RightToLeft
        arrow = QRect(r.x() + 6, r.center().y() - 6, 12, 12)
        text = QRect(r.x() + 24, r.y(), r.width() - 28, r.height())
        if rtl:
            arrow = QStyle.visualRect(Qt.LayoutDirection.RightToLeft, r, arrow)
            text = QStyle.visualRect(Qt.LayoutDirection.RightToLeft, r, text)
        icons.icon("fold_open" if open_ else "fold", "muted").paint(p, arrow)
        f = QFont(option.font)
        f.setPointSizeF(max(7.5, option.font.pointSizeF() * 0.85))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(theme.T["muted"]))
        p.drawText(text, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   index.data(Qt.ItemDataRole.DisplayRole) or "")

    def _paint_wave(self, p: QPainter, rect: QRect, peaks: list[float], played: float):
        T = theme.T
        p.setPen(Qt.PenStyle.NoPen)
        if not peaks:   # not drawn yet (an older clip): a flat line until it is
            p.setBrush(QColor(T["faint"]))
            p.drawRoundedRect(QRect(rect.x(), rect.center().y() - 1, rect.width(), 2), 1, 1)
            return
        n = len(peaks)
        step = rect.width() / n
        bar = max(2.0, step * 0.55)
        rtl = self.s.list.layoutDirection() == Qt.LayoutDirection.RightToLeft
        h = rect.height()
        done, rest = QColor(T["accent"]), QColor(T["faint"])
        for i, v in enumerate(peaks):
            bh = max(2.0, float(v) * h)
            x = rect.x() + i * step + (step - bar) / 2
            if rtl:
                x = rect.x() + rect.right() - x - bar
            p.setBrush(done if (i + 0.5) / n <= played else rest)
            p.drawRoundedRect(int(x), int(rect.center().y() - bh / 2), max(2, int(bar)),
                              int(bh), 1, 1)

    # ------------------------------------------------------------------ input
    def editorEvent(self, event, model, option, index):
        kind = event.type()
        if kind not in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
                        QEvent.Type.MouseButtonDblClick):
            return False
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        it = self.s.list.itemFromIndex(index)
        if it is None:
            return False
        pos = event.position().toPoint()
        on_play = bool(index.data(ID)) and self.s.row_layout(
            option.rect, depth(index)).play.contains(pos)
        if kind == QEvent.Type.MouseButtonPress:
            self.pressed_play, self._double = on_play, False
            return False
        if not index.data(ID):   # a group's label: a click folds it
            if kind == QEvent.Type.MouseButtonRelease:
                it.setExpanded(not it.isExpanded())
            return True
        if on_play:
            if kind == QEvent.Type.MouseButtonDblClick:
                self._double = True
            elif not self._double:
                self.s.toggle_play(it)
            return True   # (a double-click on the button isn't a second play)
        return False

    def double_clicked(self) -> bool:
        """A row was double-clicked: False when it was on its play button (the first
        click played it; the rest of the double-click does nothing)."""
        if self.pressed_play:
            self._double = True
            return False
        return True

    def helpEvent(self, event, view, option, index):
        L = self.s.row_layout(option.rect, depth(index))
        if index.data(ID) and L.play.contains(event.pos()):
            playing = self.s._playing == (self.s._preview_sid, index.data(ID))
            QToolTip.showText(event.globalPos(), _("Stop") if playing else _("Play for me"),
                              view)
            return True
        return super().helpEvent(event, view, option, index)

    def updateEditorGeometry(self, editor, option, index):
        L = self.s.row_layout(option.rect, depth(index))
        editor.setGeometry(L.name.adjusted(-4, -3, 4, 3))
