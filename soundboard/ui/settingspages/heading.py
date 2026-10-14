"""Settings' heading row, level with the window's side rail, and the narrow layout."""
from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QPushButton, QStyle, QStyleOptionButton, QWidget
from shiboken6 import isValid as qt_valid

from soundboard.ui import icons
from soundboard.ui.settingspages import Page


def _ink_rows(img: QImage) -> float:
    """The middle of an image's ink between its top and bottom edge, in device px from
    its top: a blurred end row counts by how much of a typical inked row it covers."""
    img = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    line, data = img.bytesPerLine(), bytes(img.constBits())
    ink = [sum(data[y * line + 3:y * line + img.width() * 4:4]) for y in range(img.height())]
    rows = [y for y, a in enumerate(ink) if a]
    if not rows:
        return img.height() / 2
    typical = sorted(ink[y] for y in rows)[len(rows) // 2]
    first, last = rows[0], rows[-1]
    return (first + 1 - min(1.0, ink[first] / typical) + last + min(1.0, ink[last] / typical)) / 2


_DRAWN: dict[tuple, tuple[QPixmap, float]] = {}   # (_draw_icon)


def _draw_icon(p: QPainter, w: QWidget, name: str, color: str, side: int, x: float,
               mid: float):
    """Icon `name` drawn `side` px at `x` with its ink's middle (not its box's: an
    icon's drawing isn't always in the middle of its picture) on `mid`, in `w`, to a
    fraction of a screen pixel: a picture lands on whole ones, 0.4 px off at 125%."""
    k = w.devicePixelRatioF()
    px = max(1, round(side * k))
    wy = w.mapTo(w.window(), QPoint(0, 0)).y()
    plain = _DRAWN.get((name, px))
    if plain is None:
        pm = icons.pixmap(name, px, "#000000")
        plain = _DRAWN[(name, px)] = (pm, _ink_rows(pm.toImage()))
    at = (wy + mid) * k - plain[1]   # the picture's top, in screen px
    whole = math.floor(at)
    frac = round((at - whole) * 8) / 8
    key = (name, px, icons.resolve(color), frac)
    drawn = _DRAWN.get(key)
    if drawn is None:
        if len(_DRAWN) > 64:
            _DRAWN.clear()
        pm = icons.pixmap(name, px, key[2], frac)
        pm.setDevicePixelRatio(k)
        drawn = _DRAWN[key] = (pm, 0.0)
    p.drawPixmap(QPointF(x, whole / k - wy), drawn[0])


class _Mark(QWidget):
    """The heading's cog, drawn `dy` px below its box's middle (_draw_icon): a label's
    picture moves in whole px, 1.25 screen px at 125%."""

    dy = 0.0

    def __init__(self, name: str, color: str, side: int):
        super().__init__()
        self.name, self.color, self.side = name, color, side
        self.setFixedWidth(side)

    def sizeHint(self):
        return QSize(self.side, self.side)

    def paintEvent(self, e):
        p = QPainter(self)
        _draw_icon(p, self, self.name, self.color, self.side, 0,
                   self.height() / 2 + self.dy)
        p.end()


class _BackArrow(QPushButton):
    """The heading's back arrow, drawn `dy` px below the button's middle to the screen
    pixel (as _Mark): its button, hover and focus look as any quiet one's."""

    dy = 0.0
    BACK_LEFT = 3   # (the padding's left: SettingsDialog.BACK_PAD)

    def paintEvent(self, e):
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        opt.icon = QIcon()
        p = QPainter(self)
        self.style().drawControl(QStyle.ControlElement.CE_PushButton, opt, p, self)
        side, left = self.iconSize().height(), self.BACK_LEFT
        _draw_icon(p, self, "back", "text" if self.isEnabled() else "muted", side,
                   left + (self.width() - left - side) / 2, self.height() / 2 + self.dy)
        p.end()


class Heading(Page):
    """Settings' heading row, level with the window's side rail, and the narrow layout."""

    def _caps_mid(self, label: QLabel, dy: int = 0) -> float:
        """The middle of a one-line label's capitals in the window, in screen pixels
        (what the eye lines up: not the box, not the descenders), were it `dy` px lower.
        Measured on an "H" drawn the way the label draws its text, on the same part of a
        pixel: where Qt and the font's hinting put a line can't be worked out from the
        font's numbers (Consolas and Tahoma at 125% drew theirs up to 2 px off them)."""
        k = label.devicePixelRatioF()
        at = (label.mapTo(self.dlg.window(), QPoint(0, 0)).y() + dy) * k
        whole = math.floor(at)
        rect = label.contentsRect()
        key = (label.font().key(), rect.getRect(), int(label.alignment()), k, at - whole)
        mid = self.dlg._caps_cache.get(key)
        if mid is None:   # (not an alpha-only image: Windows drew its text 4 px off)
            img = QImage(max(1, math.ceil(label.width() * k)),
                         math.ceil(label.height() * k) + 2,
                         QImage.Format.Format_ARGB32_Premultiplied)
            img.setDevicePixelRatio(k)
            img.fill(0)
            p = QPainter(img)
            p.translate(0, (at - whole) / k)
            p.setFont(label.font())
            p.setPen(Qt.GlobalColor.black)
            p.drawText(rect, int(label.alignment()), "H")
            p.end()
            mid = _ink_rows(img)   # (the H's top and bottom edge)
            self.dlg._caps_cache[key] = mid
        return whole + mid

    def _level_with_rail(self):
        """The heading row moves down until the middle of "Settings"' capitals is level
        with the rail's "Onion Board" (the arrow and cog are centred on it); with the
        name hidden (the rail shut) or a bar above the pages, it sits where the pages
        start."""
        if not qt_valid(self.dlg) or self.dlg.back_btn is None:
            return
        lay = self.dlg.layout()
        if lay is not None:
            lay.activate()   # (a lift just set: measured where it put the row)
        side = self.dlg._side.contentsMargins()
        lift = self.dlg.PAGE_TOP
        wm = getattr(self.mw, "wordmark", None)
        if wm is not None and qt_valid(wm) and wm.isVisible():
            want = self._caps_mid(wm)
            titled = self.dlg.page_title.isVisible()
            k = self.dlg.back_btn.devicePixelRatioF()
            at = self.dlg.back_btn.mapTo(self.dlg.window(), QPoint(0, 0)).y()

            def off(dy):   # how far off the name, in screen pixels, dy px lower
                if titled:
                    return abs(self._caps_mid(self.dlg.page_title, dy) - want)
                return abs((at + dy + self.dlg.back_btn.height() / 2) * k - want)   # (narrow)
            # the whole-pixel lifts either side of the exact one: the nearer on screen
            near = (want - self._caps_mid(self.dlg.page_title)) / self.dlg.devicePixelRatioF()
            dy = min(range(math.floor(near) - 1, math.ceil(near) + 2), key=off)
            lift = max(0, min(self.dlg.PAGE_TOP, side.top() + dy))
        if lift != side.top():
            self.dlg._side.setContentsMargins(side.left(), lift, side.right(), side.bottom())
            if lay is not None:
                lay.activate()
        self._level_icons()

    def _level_icons(self):
        """The arrow and cog centred on the middle of "Settings"' capitals as drawn,
        wherever the theme's font puts them (_caps_mid): Consolas and Tahoma draw theirs
        lower in the line than Bahnschrift, Comic Sans higher."""
        title = self.dlg.page_title
        if not title.isVisible():   # (narrow: the arrow on its own, in its middle)
            if self.dlg.back_btn.dy:
                self.dlg.back_btn.dy = 0.0
                self.dlg.back_btn.update()
            return
        caps = (self._caps_mid(title) / title.devicePixelRatioF()
                - self.dlg.mapTo(self.dlg.window(), QPoint(0, 0)).y())
        # both to the screen pixel (_BackArrow, _Mark)
        for w in (self.dlg.back_btn, self.dlg.title_cog):
            dy = caps - w.mapTo(self.dlg, QPoint(0, 0)).y() - w.height() / 2
            if abs(dy - w.dy) > 0.01:
                w.dy = dy
                w.update()

    def _fit_width(self, width: int):
        """Narrow: the categories as an icon column (the name is the tip) and the
        search box over the page, so a 440 px window has room for the page itself."""
        narrow = width < self.dlg.NARROW_W
        if narrow == self.dlg._narrow:
            return
        self.dlg._narrow = narrow
        box = self.dlg.search_box
        (self.dlg._side if narrow else self.dlg._right).removeWidget(box)
        if narrow:
            self.dlg._right.insertWidget(0, box)
            box.setMinimumWidth(0)
            box.setMaximumWidth(16777215)
        else:
            self.dlg._side.insertWidget(1 if self.dlg.back_btn is not None else 0, box)
            box.setFixedWidth(196)
        if self.dlg.back_btn is not None:
            self.dlg.page_title.setVisible(not narrow)
            self.dlg.title_cog.setVisible(not narrow)
        self.dlg._content.setSpacing(8 if narrow else 16)
        for i in range(self.dlg.categories.count()):
            item = self.dlg.categories.item(i)
            title = item.data(Qt.ItemDataRole.UserRole + 1)
            item.setText("" if narrow else title)
            item.setToolTip(title if narrow else "")
            item.setSizeHint(QSize(40 if narrow else 180, 38))
        self.dlg.categories.setFixedWidth(48 if narrow else 196)
