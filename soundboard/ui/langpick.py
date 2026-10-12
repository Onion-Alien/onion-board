"""The language picker: a drop-down under Settings → Appearance → Language, a row per
language with its signature letter on a round coin ("ß", "Ñ", "Я", "あ", "ع"), its own
name and its name in the language showing. A search box on top filters the rows as you
type, in any of those names, English or the code. No flags: a flag is a country, not a
language (English, Spanish, Arabic, Chinese would each pick a side), and Windows
doesn't draw flag emoji anyway."""
from __future__ import annotations

import unicodedata

from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from soundboard import i18n, theme
from soundboard.i18n import _

WIDTH = 380            # the drop-down: as wide as the longest name, no wider
ROW_H = 46
ROWS_SHOWN = 8         # then it scrolls
COIN = 34

# each language's signature letter: one its alphabet has and its neighbours' don't,
# or its script's own first letter. Languages without one get their name's first
# letters (glyph()).
MARKS = {
    "en": "Aa", "ar": "ع", "bg": "Ъ", "cs": "Ř", "da": "Æ", "de": "ß", "el": "Ω",
    "es": "Ñ", "es-419": "¿?", "fi": "Ä", "fil": "Ng", "fr": "Ç", "hi": "अ",
    "hu": "Ő", "id": "Ny", "it": "È", "ja": "あ", "ko": "한", "ms": "Sy", "nb": "Ø",
    "nl": "IJ", "pl": "Ł", "pt-BR": "Ã", "pt-PT": "Õ", "ro": "Ș", "ru": "Я",
    "sv": "Å", "th": "ก", "tr": "Ğ", "uk": "Ї", "vi": "Ơ", "zh-CN": "汉", "zh-TW": "漢",
}


def glyph(code: str, own: str) -> str:
    """The coin's mark: the language's signature letter, else the first letters of its
    own name, as many as read as one sign (Hindi's vowel signs kept on their letter)."""
    if code in MARKS:
        return MARKS[code]
    first = own.split()[0] if own.split() else own
    out = first[:2]
    while len(first) > len(out) and unicodedata.category(first[len(out)]) in ("Mn", "Mc"):
        out = first[:len(out) + 1]   # हि, not ह and a stray vowel sign
    return out


def other_name(code: str) -> str:
    """`code`'s name in the language showing ("German" in English), "" when that's
    its own name anyway."""
    from soundboard import langnames
    name = langnames.name(code)
    if name == code:   # not in the CLDR table: Qt's English name
        from PySide6.QtCore import QLocale
        name = QLocale.languageToString(QLocale(code.replace("-", "_")).language())
    return "" if code == i18n.current() or not name else name


def _fold(s: str) -> str:
    """Lower case without accents: "espanol" finds Español."""
    return "".join(c for c in unicodedata.normalize("NFKD", s.casefold())
                   if not unicodedata.combining(c))


def search_words(code: str, own: str) -> str:
    from soundboard import langnames_data
    english = langnames_data.NAMES["en"].get(code, "")
    return _fold(" ".join((own, other_name(code), english, code)))


def paint_coin(p: QPainter, r: QRectF, mark: str, on: bool, font: QFont):
    """The round coin: filled in the accent when it's the language picked, else an
    accent ring on the card colour."""
    t = theme.tokens()
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if on:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t["accent"]))
    else:
        p.setPen(QPen(QColor(t["accent"]), 1.6))
        p.setBrush(QColor(t["card_hi"]))
    p.drawEllipse(r.adjusted(1, 1, -1, -1))
    f = QFont(font)
    f.setBold(True)
    f.setPixelSize(round(r.height() * (0.46 if len(mark) == 1 else 0.36)))
    p.setFont(f)
    p.setPen(QColor(t["on_accent"] if on else t["text_hi"]))
    p.drawText(r, Qt.AlignmentFlag.AlignCenter, mark)
    p.restore()


def coin_icon(mark: str, font: QFont, size: int = 26, dpr: float = 1.0) -> QIcon:
    """The picked language's coin as an icon (the Settings button wears it)."""
    pm = QPixmap(round(size * dpr), round(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    paint_coin(p, QRectF(0, 0, size, size), mark, True, font)
    p.end()
    return QIcon(pm)


class LangButton(QPushButton):
    """Settings' Language button: the picked language's coin, its name and ▾. The coin
    is repainted when the theme changes, so it's always the accent colour."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mark = ""
        self.setIconSize(QSize(26, 26))

    def show_language(self, code: str, own: str):
        self.mark = glyph(code, own)
        self.setText(f"{own}  ▾")
        self._repaint_coin()

    def _repaint_coin(self):
        if self.mark:
            self.setIcon(coin_icon(self.mark, self.font(), 26, self.devicePixelRatioF()))

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() in (QEvent.Type.StyleChange, QEvent.Type.PaletteChange):
            self._repaint_coin()


class LangRow(QPushButton):
    """One language: its coin, its own name and its name in the language showing, a
    tick on the one picked."""

    def __init__(self, code: str, own: str, parent=None):
        super().__init__(parent)
        self.code, self.own, self.other = code, own, other_name(code)
        if self.other.casefold() == own.casefold():
            self.other = ""
        self.mark = glyph(code, own)
        self.words = search_words(code, own)
        self.setObjectName("langrow")
        self.setCheckable(True)
        self.setFixedHeight(ROW_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(f"{own} {self.other}".strip())
        # each row in its own direction: Arabic reads right to left in an English window
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if i18n.is_rtl(code)
                                else Qt.LayoutDirection.LeftToRight)

    def enterEvent(self, e):
        super().enterEvent(e)
        self.update()

    def leaveEvent(self, e):
        super().leaveEvent(e)
        self.update()

    def paintEvent(self, e):
        t = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        lit = self.underMouse() or self.hasFocus()
        if on or lit:
            c = QColor(t["accent"])
            c.setAlpha(46 if on else 22)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 8, 8)
        if self.hasFocus():
            p.setPen(QPen(QColor(t["accent"]), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5), 8, 8)
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        w, h = self.width(), self.height()
        coin = QRectF(w - 8 - COIN if rtl else 8, (h - COIN) / 2, COIN, COIN)
        paint_coin(p, coin, self.mark, on, self.font())
        tick = 26 if on else 0
        text = QRectF(8 + tick, 0, coin.left() - 12 - 8 - tick, h) if rtl \
            else QRectF(coin.right() + 12, 0, w - coin.right() - 12 - 8 - tick, h)
        bold = QFont(self.font())
        bold.setBold(True)
        small = QFont(self.font())
        small.setPointSizeF(small.pointSizeF() * 0.88)
        bfm, sfm = QFontMetrics(bold), QFontMetrics(small)
        own = bfm.elidedText(self.own, Qt.TextElideMode.ElideRight, int(text.width()))
        gap = 8
        rest = int(text.width()) - bfm.horizontalAdvance(own) - gap
        other = ""
        if self.other and rest > 30:
            other = sfm.elidedText(self.other, Qt.TextElideMode.ElideRight, rest)
        align = Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter
        # the own name, then the other name after it on the same line (before it, RTL)
        p.setFont(bold)
        p.setPen(QColor(t["text"]))
        ow = bfm.horizontalAdvance(own)
        own_r = QRectF(text.right() - ow, 0, ow, h) if rtl else QRectF(text.left(), 0, ow + 2, h)
        side = Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft
        p.drawText(own_r, align | side, own)
        if other:
            p.setFont(small)
            p.setPen(QColor(t["muted"]))
            ox = own_r.left() - gap - sfm.horizontalAdvance(other) if rtl \
                else own_r.right() + gap
            p.drawText(QRectF(ox, 1, sfm.horizontalAdvance(other) + 2, h),
                       align | Qt.AlignmentFlag.AlignLeft, other)
        if on:
            f = QFont(self.font())
            f.setBold(True)
            f.setPointSizeF(f.pointSizeF() * 1.15)
            p.setFont(f)
            p.setPen(QColor(t["accent"]))
            tr = QRectF(8, 0, 20, h) if rtl else QRectF(w - 8 - 20, 0, 20, h)
            p.drawText(tr, Qt.AlignmentFlag.AlignCenter, "✓")
        p.end()


class LanguageDialog(QDialog):
    """The drop-down: `chosen` fires with the code picked, `picked` keeps it ("" when
    closed with Esc or a click outside). Open it with `open_under(button)`."""
    chosen = Signal(str)

    def __init__(self, parent=None, current: str | None = None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle(_("Language"))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._opener = None
        self.picked = ""
        current = current or i18n.current()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        frame = QFrame()
        frame.setObjectName("helpcard")   # the help pop-ups' themed card
        outer.addWidget(frame)
        v = QVBoxLayout(frame)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)
        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Search languages"))
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName(_("Search languages"))
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._pick_first)
        self.search.installEventFilter(self)
        v.addWidget(self.search)
        holder = QWidget()
        holder.setObjectName("langlist")
        self.column = QVBoxLayout(holder)
        self.column.setContentsMargins(0, 0, 0, 0)
        self.column.setSpacing(2)
        english, *rest = i18n.available()
        self.tiles: list[LangRow] = []
        for code, own in [english, *sorted(rest, key=lambda c: _fold(c[1]))]:
            row = LangRow(code, own)
            row.setChecked(code == current)
            row.clicked.connect(lambda __=False, c=code: self._pick(c))
            row.installEventFilter(self)
            self.column.addWidget(row)
            self.tiles.append(row)
        self.column.addStretch(1)
        self.none = QLabel()
        self.none.setObjectName("hint")
        self.none.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.none.hide()
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QFrame.Shape.NoFrame)
        self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.area.setWidget(holder)
        self.area.viewport().setAutoFillBackground(False)
        holder.setAutoFillBackground(False)
        self._fit_rows(len(self.tiles))
        v.addWidget(self.area)
        v.addWidget(self.none)
        self.setFixedWidth(WIDTH)
        self.search.setFocus()   # type straight away

    def open_under(self, button: QWidget):
        """Shows the drop-down under `button` (above it when there's no room below),
        the picked language scrolled into view."""
        self._opener = button
        self.adjustSize()
        below = button.mapToGlobal(QPoint(0, button.height() + 4))
        screen = (button.screen() or QApplication.primaryScreen()).availableGeometry()
        x = max(screen.left() + 4, min(below.x(), screen.right() - self.width() - 4))
        y = below.y()
        if y + self.height() > screen.bottom() - 4:
            y = max(screen.top() + 4, button.mapToGlobal(QPoint(0, 0)).y() - 4 - self.height())
        self.move(x, y)
        self.show()
        on = next((t for t in self.tiles if t.isChecked()), None)
        if on is not None:
            self.area.ensureWidgetVisible(on, 0, ROW_H)
        self.search.setFocus()

    def visible_tiles(self) -> list[LangRow]:
        return [t for t in self.tiles if not t.isHidden()]

    def _filter(self, text: str):
        want = _fold(text.strip())
        for t in self.tiles:
            t.setHidden(bool(want) and want not in t.words)
        shown = self.visible_tiles()
        self.none.setText(_("No language matches “{text}”", text=text.strip()))
        self.none.setVisible(not shown)
        self.area.setVisible(bool(shown))
        self._fit_rows(len(shown))

    def _fit_rows(self, n: int):
        """As tall as the rows showing, up to ROWS_SHOWN, then it scrolls."""
        self.area.setFixedHeight(max(1, min(n, ROWS_SHOWN)) * (ROW_H + 2))
        self.adjustSize()

    def eventFilter(self, obj, e):
        """↓ from the search box goes into the list, ↑/↓ move along it, ↑ from the top
        row goes back to the search box."""
        if e.type() == QEvent.Type.KeyPress and e.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            rows = self.visible_tiles()
            if obj is self.search:
                if e.key() == Qt.Key.Key_Down and rows:
                    rows[0].setFocus()
                    return True
            elif obj in rows:
                i = rows.index(obj) + (1 if e.key() == Qt.Key.Key_Down else -1)
                if i < 0:
                    self.search.setFocus()
                elif i < len(rows):
                    rows[i].setFocus()
                    self.area.ensureWidgetVisible(rows[i], 0, 4)
                return True
        if e.type() == QEvent.Type.KeyPress and obj in self.tiles \
                and e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._pick(obj.code)
            return True
        return super().eventFilter(obj, e)

    def _pick_first(self):
        shown = self.visible_tiles()
        if shown:
            self._pick(shown[0].code)

    def _pick(self, code: str):
        self.picked = code
        for t in self.tiles:
            t.setChecked(t.code == code)
        self.chosen.emit(code)
        self.accept()

    def done(self, r):
        super().done(r)
        # the focus back on the Language button, not lost to the window
        b = self._opener
        try:
            if b is not None and b.isVisible():
                b.setFocus(Qt.FocusReason.PopupFocusReason)
        except RuntimeError:   # the button went with its page
            pass
