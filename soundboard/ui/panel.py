"""Shared UI building blocks: the bar / card / divider helpers every tab is built
from, the compact volume control (slider + typed %), and the equalizer. They own
their widgets and emit plain values; the main window maps those onto the config
and the engine."""
from __future__ import annotations

import html

import math

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QRegion
from shiboken6 import isValid as qt_valid
from PySide6.QtWidgets import (QBoxLayout, QCheckBox, QComboBox, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLayout, QListWidget, QPushButton,
                               QSizePolicy, QSlider, QSpinBox, QStyle, QVBoxLayout, QWidget)

from soundboard import theme
from soundboard.eq import BAND_LABELS as EQ_LABELS
from soundboard.eq import MAX_DB as EQ_MAX_DB
from soundboard.eq import PRESETS as EQ_PRESETS
from soundboard.ui import icons
from soundboard.ui.widgets import CrispSlider, EqCurve, Meter
from soundboard.wheelguard import no_wheel
from soundboard.i18n import _
from soundboard.ui.pixels import snap_to_pixels

# the two heights the main window's controls and bars share (DESIGN.md "size")
CONTROL_H = 36   # a toolbar button, the search box, the player's buttons
BAR_H = 48       # a bar holding one row of them: the Sounds toolbar, the bottom bars


class RoundedFrame(QFrame):
    """Clip a panel and its children to the same corners as the app's cards."""

    def resizeEvent(self, event):
        super().resizeEvent(event)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 12, 12)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))


def section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("section")
    return lbl


def steady_number(lbl: QLabel, widest: str) -> QLabel:
    """A number that changes in place (9% → 100%) keeps its width: same-width digits,
    room for the widest value, right-aligned, so nothing beside it moves."""
    lbl.ensurePolished()
    f = lbl.font()
    f.setFeature(QFont.Tag("tnum"), 1)
    lbl.setFont(f)
    text = lbl.text()
    lbl.setText(widest)                 # its size hint counts the stylesheet's padding too
    lbl.setMinimumWidth(lbl.sizeHint().width() + 2)
    lbl.setText(text)
    lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return lbl


def hint_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setObjectName("hint")
    return lbl


def vsep() -> QFrame:
    """A thin vertical divider between groups in a bar."""
    f = QFrame()
    f.setObjectName("vsep")
    f.setFixedWidth(1)
    return f


def bar(margins=(10, 5, 12, 6)) -> tuple[QFrame, QHBoxLayout]:
    """The rounded control bar every tab has along its bottom (and the mixer strip).
    A theme's 1 px top edge plus 5 + 6 around a CONTROL_H row makes BAR_H."""
    f = QFrame()
    f.setObjectName("transport")
    f.setMinimumHeight(BAR_H)
    h = QHBoxLayout(f)
    h.setContentsMargins(*margins)
    h.setSpacing(10)
    return f, h


class Flow(QLayout):
    """Lays its widgets out left to right, wrapping onto new lines (the Radio tab's
    genre chips, the Triggers tab's settings)."""

    def __init__(self, parent=None, gap: int = 6):
        super().__init__(parent)
        self._items, self._gap = [], gap
        self._widgets: list = []   # each item's widget (None for a spacer), in step
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)
        self._widgets.append(item.widget())

    def _alive(self) -> list:
        """Its items, with any whose Qt side is already gone made again for their widget
        (or dropped, the widget gone too). One went once, around loading and removing
        Onion Watch: every layout pass raised on it and the app crashed; dropping it
        then left its button where it was while the row thought itself empty, 0 px
        tall, so the line under Who's listening's modes sat on top of them."""
        if all(qt_valid(it) for it in self._items):
            return self._items
        items, widgets, again = [], [], []
        for it, w in zip(self._items, self._widgets):
            if qt_valid(it):
                items.append(it)
                widgets.append(w)
            elif w is not None and qt_valid(w):
                again.append((len(items) + len(again), w))
        self._items, self._widgets = items, widgets
        for i, w in again:   # Qt makes (and owns) its new item, appended by addItem
            self.addWidget(w)
            self._items.insert(i, self._items.pop())
            self._widgets.insert(i, self._widgets.pop())
        return self._items

    def count(self):
        return len(self._alive())

    def itemAt(self, i):
        items = self._alive()
        return items[i] if 0 <= i < len(items) else None

    def takeAt(self, i):
        items = self._alive()
        if not 0 <= i < len(items):
            return None
        self._widgets.pop(i)
        return items.pop(i)

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._place(QRect(0, 0, w, 0), move=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._place(rect, move=True)

    def sizeHint(self):
        # its lines at the width it has (all on one line before it's been laid out).
        # Not the narrowest width: Qt sizes a widget holding this at the height for
        # its hint's width, and a box whose height can't shrink (the Radio tab's genre
        # chips) then asked for every chip on its own line. That made the Radio tab
        # need ~300 px more whenever the window was big enough to show the chips, so
        # a maximized window restored to an ordinary size became the mini player.
        w = self.geometry().width()
        if w <= 0:
            w = sum(it.sizeHint().width() + self._gap for it in self._alive()
                    if not it.isEmpty()) - self._gap
        w = max(w, self.minimumSize().width())
        return QSize(w, self.heightForWidth(w))

    def minimumSize(self):
        size = QSize()
        for it in self._alive():
            size = size.expandedTo(it.minimumSize())
        return size

    def _place(self, rect: QRect, move: bool) -> int:
        """Each item is centred on its line's height: a label beside taller chips
        ("Now playing" before the sounds' ■ chips) sat at their top edge instead."""
        x, y, line = rect.x(), rect.y(), 0
        row: list = []   # (item, x, hint) of the line being filled

        owner = self.parentWidget()
        rtl = owner is not None and owner.layoutDirection() == Qt.LayoutDirection.RightToLeft

        def put():
            if move:
                for it, ix, hint in row:
                    r = QRect(QPoint(ix, y + (line - hint.height()) // 2), hint)
                    # Arabic: the lines fill from the right, like the rest of the app
                    it.setGeometry(QStyle.visualRect(Qt.LayoutDirection.RightToLeft, rect, r)
                                   if rtl else r)
            row.clear()

        for it in self._alive():
            if it.isEmpty():
                continue
            hint = it.sizeHint()
            if hint.width() > rect.width() > 0:   # wider than the whole row: as narrow
                hint.setWidth(max(rect.width(), it.minimumSize().width()))   # as it goes
            if line and x + hint.width() > rect.right() + 1:
                put()
                x, y, line = rect.x(), y + line + self._gap, 0
            row.append((it, x, hint))
            x += hint.width() + self._gap
            line = max(line, hint.height())
        put()
        return y + line - rect.y()


class CardGrid(QLayout):
    """Lays its widgets out as a grid of equal-width cards, as many across as fit
    at `min_w` each (at most `max_cols`), stretched to fill the row. Each row is as
    tall as its tallest card; the cards in it too, unless `even` is off (the Apps
    tab: one card's open clip editor mustn't stretch its neighbours)."""

    def __init__(self, parent=None, min_w: int = 240, gap: int = 10, max_cols: int = 0,
                 even: bool = True):
        super().__init__(parent)
        self._items, self._gap = [], gap
        self.min_w, self.max_cols = min_w, max_cols
        self.even = even   # False: each card keeps its own height, top-aligned in its row
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._place(QRect(0, 0, w, 0), move=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._place(rect, move=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        return QSize(self.min_w, 0)

    def columns(self, width: int) -> int:
        """How many cards fit across `width`."""
        n = max(1, (width + self._gap) // (self.min_w + self._gap))
        return min(n, self.max_cols) if self.max_cols else n

    def _place(self, rect: QRect, move: bool) -> int:
        shown = [it for it in self._items if not it.isEmpty()]
        if not shown:
            return 0
        cols = self.columns(rect.width())
        cw = max(1, (rect.width() - self._gap * (cols - 1)) // cols)
        y = rect.y()
        for i in range(0, len(shown), cols):
            line = shown[i:i + cols]
            hs = [max(it.heightForWidth(cw) if it.hasHeightForWidth() else it.sizeHint().height(),
                      it.minimumSize().height()) for it in line]
            h = max(hs)
            if move:
                for j, it in enumerate(line):
                    it.setGeometry(QRect(rect.x() + j * (cw + self._gap), y, cw,
                                         h if self.even else hs[j]))
            y += h + self._gap
        return y - self._gap - rect.y()


class HoverCard(QFrame):
    """A card whose hover surface stays active over its child labels and controls."""

    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        self.setProperty("interactive", True)
        self.setProperty("hovered", False)

    def _hover(self, on: bool):
        if self.property("hovered") != on:
            self.setProperty("hovered", on)
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()

    def enterEvent(self, event):
        self._hover(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover(False)
        super().leaveEvent(event)


# the widest the Setup and Voice pages' cards get: on a full-screen window they
# spread to half the screen each, every button and list a bar ~900 px long
PAGE_MAX_W = 1180


def capped(body: QWidget, outer: QWidget | None = None, *,
           margins: tuple[int, int, int, int] = (0, 0, 0, 0)) -> QWidget:
    """`body` no wider than PAGE_MAX_W, centred in `outer` (a new QWidget if None)."""
    outer = outer if outer is not None else QWidget()
    body.setMaximumWidth(PAGE_MAX_W)
    h = QHBoxLayout(outer)
    h.setContentsMargins(*margins)
    h.setSpacing(0)
    # the body takes all the width up to its cap (so its left edge lines up with the
    # download bar and the other tabs), the two sides only what's left past the cap
    h.addStretch(0)
    h.addWidget(body, 1)
    h.addStretch(0)
    return outer


class _HeadingAlignment(QObject):
    """Keep a heading on its current font's capitals after polish and theme changes."""

    def __init__(self, title: QLabel, boxes: dict[QWidget, QVBoxLayout]):
        super().__init__(title)
        self.title, self.boxes = title, boxes
        self.pending = False
        for widget in boxes:
            widget.installEventFilter(self)
        self.align()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange,
                            QEvent.Type.Show, QEvent.Type.Resize):
            if not self.pending:
                self.pending = True
                QTimer.singleShot(0, self.align)
        return False

    def align(self):
        self.pending = False
        if not qt_valid(self.title):
            return
        fm = self.title.fontMetrics()
        centre = fm.ascent() - (fm.capHeight() + 1) / 2
        tops = {w: round(centre - (max(w.minimumHeight(), w.sizeHint().height()) - 1) / 2)
                for w in self.boxes if w is not self.title}
        lead = max([0, *(-top for top in tops.values())])
        tops[self.title] = 0
        for widget, box in self.boxes.items():
            top = tops[widget] + lead
            if box.contentsMargins().top() != top:
                box.setContentsMargins(0, top, 0, 0)


def heading_row(title: str, icon: str = "", *, beside=(), end=()
                ) -> tuple[QHBoxLayout, QLabel, list[QWidget]]:
    """A card's heading line (DESIGN section 4, *Card headings*): the icon, the title,
    `beside` right after it (an ⓘ), then `end` at the far end (a status pill). Every
    part is centred on the title's cap height, worked out from its font, never by eye
    or a hand-tuned margin; a part taller than the line pushes the title down instead
    of sticking up. Returns the row, the title and the parts centred on it (the icon,
    `beside` and `end`), which tests/test_card_headings.py measures on the ink."""
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    lbl = section_label(title)
    lbl.setProperty("head", True)   # (no padding above: the row places it)
    lbl.ensurePolished()
    marks: list[QWidget] = []
    if icon:
        marks.append(icon_label(icon, color="text"))
    marks += [*beside, *end]
    boxes = {}
    for w in marks:
        w.ensurePolished()

    def pin(w: QWidget):
        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        box.addWidget(w)
        box.addStretch(1)
        row.addLayout(box)
        boxes[w] = box

    if icon:
        pin(marks[0])
    pin(lbl)
    for w in beside:
        pin(w)
    row.addStretch(1)
    for w in end:
        pin(w)
    _HeadingAlignment(lbl, boxes)   # owned by the title, including the queued callback
    return row, lbl, marks


class Card(QFrame):
    """A `QFrame#card` that remembers its heading_row() parts."""
    heading_row: QHBoxLayout | None = None
    heading_title: QLabel | None = None
    heading_marks: list[QWidget] = []


def card(title: str = "", hint: str = "", *, roomy: bool = False, icon: str = "",
         beside=(), end=()) -> tuple[Card, QVBoxLayout]:
    """A titled card, the building block of the Voice and Setup pages. Its heading is
    heading_row(): `icon` in front of the title, `beside` right after it (an ⓘ that
    explains the card: DESIGN section 4), `end` at the far end (a status pill). The
    card keeps them as `heading_title`, `heading_marks` and `heading_row`."""
    f = Card()
    f.setObjectName("card")
    v = QVBoxLayout(f)
    f.setProperty("roomy", roomy)
    # every titled card's heading starts at the same height: its top margin plus 8
    v.setContentsMargins(*((18, 18, 18, 18) if roomy else (14, 16, 14, 14)))
    v.setSpacing(12 if roomy else 6)
    beside = (beside,) if isinstance(beside, QWidget) else tuple(beside or ())
    if title:
        row, f.heading_title, f.heading_marks = heading_row(title, icon, beside=beside, end=end)
        f.heading_row = row
        v.addLayout(row)
    if hint:
        v.addWidget(hint_label(hint))
    return f, v


def icon_label(name: str, tip: str = "", color: str = "muted") -> QLabel:
    """A small painted icon used as a label in the bars."""
    lbl = QLabel()
    icons.set_label_icon(lbl, name, color)
    lbl.setToolTip(tip)
    lbl.setObjectName("iconlabel")
    return lbl


class EmptyList(QListWidget):
    """A list that says so when it's empty: a faint icon over a muted line, centred in
    the list, instead of a first row of grey text in its corner. `set_empty(text,
    icon)` changes what it says (a "Looking…" while a list is being filled)."""

    def __init__(self, text: str = "", icon: str = "info", parent=None):
        super().__init__(parent)
        self._empty_text, self._empty_icon = text, icon

    def set_empty(self, text: str, icon: str | None = None):
        self._empty_text = text
        if icon is not None:
            self._empty_icon = icon
        self.viewport().update()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.count() or not self._empty_text:
            return
        vp = self.viewport()
        p = QPainter(vp)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = 32
        box = vp.rect().adjusted(24, 0, -24, 0)
        p.setFont(self.font())
        flags = int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
                    | Qt.TextFlag.TextWordWrap)
        text_h = p.fontMetrics().boundingRect(box, flags, self._empty_text).height()
        top = max(8, (vp.height() - side - 12 - text_h) // 2)
        if self._empty_icon:
            pm = icons.pixmap(self._empty_icon, side, theme.T.get("faint", "#888"))
            p.drawPixmap(vp.width() // 2 - side // 2, top, pm)
        p.setPen(QColor(theme.T.get("muted", "#888")))
        p.drawText(QRect(box.left(), top + side + 12, box.width(), text_h), flags,
                   self._empty_text)
        p.end()


def alt_tile(icon: str, title: str, words: str, *buttons: QPushButton
             ) -> tuple[QFrame, QLabel]:
    """One of the "other ways" side by side in a card: an inner area with an icon,
    a bold name, why you'd want it, then its buttons along the bottom edge. Gives the
    tile and its words (changed when its state does). Setup tab and the setup guide."""
    box = QFrame()
    box.setObjectName("alttile")   # an inner area (DESIGN.md: cards)
    box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    v = QVBoxLayout(box)
    v.setContentsMargins(14, 12, 14, 14)
    v.setSpacing(8)
    top = QHBoxLayout()
    top.setSpacing(8)
    pic = QLabel()
    icons.set_label_icon(pic, icon, "accent", size=18)
    top.addWidget(pic)
    top.addWidget(QLabel(f"<b>{html.escape(title)}</b>"))
    top.addStretch(1)
    v.addLayout(top)
    text = hint_label(words)
    text.setTextFormat(Qt.TextFormat.RichText)
    v.addWidget(text)
    v.addStretch(1)
    row = Flow(gap=8)   # at their own size, wrapping when the tile is narrow
    for b in buttons:
        row.addWidget(b)
    v.addLayout(row)
    return box, text


class TileRow(QWidget):
    """`alt_tile`s side by side, sharing the width; stacked one under the other when
    the row is too narrow for each tile's name and buttons (a tile never clips)."""

    def __init__(self, spacing: int = 12):
        super().__init__()
        self._box = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self._box.setContentsMargins(0, 0, 0, 0)
        self._box.setSpacing(spacing)
        self._tiles: list[QWidget] = []   # not layout.itemAt(): its wrappers outlive the items

    def addTile(self, tile: QWidget) -> None:
        self._box.addWidget(tile, 1)
        self._tiles.append(tile)
        self._fit(self.width())

    def stacked(self) -> bool:
        return self._box.direction() == QBoxLayout.Direction.TopToBottom

    def _need(self) -> int:
        """The width side by side needs: each shown tile's narrowest fit, plus gaps."""
        tiles = [t.layout() for t in self._tiles if qt_valid(t) and not t.isHidden()]
        tiles = [lay for lay in tiles if lay is not None]
        if not tiles:
            return 0
        return (sum(lay.minimumSize().width() for lay in tiles)
                + self._box.spacing() * (len(tiles) - 1))

    def _fit(self, width: int) -> None:
        d = (QBoxLayout.Direction.TopToBottom if width < self._need()
             else QBoxLayout.Direction.LeftToRight)
        if self._box.direction() != d:
            self._box.setDirection(d)

    def resizeEvent(self, e) -> None:   # a Qt override: must never raise
        try:
            self._fit(e.size().width())
        except Exception:   # noqa: BLE001 - keep the last shape rather than raise
            pass
        super().resizeEvent(e)


def icon_button(name: str, tip: str, *, quiet: bool = True, size: int = 18,
                hover: bool = True) -> QPushButton:
    """An icon-only button (section 4: a picture says it, quiet, 28-32 px).

    `tip` is the button's whole meaning: it is the tooltip and the screen-reader name
    (`setAccessibleName`), so nothing depends on the drawing alone. Its words stay in
    every catalog: pass an already-translated string to `tip`. With `hover` off it is
    only the screen-reader name: for a picture anyone reads (a folder, a stop square),
    where a tooltip would only repeat it."""
    b = QPushButton()
    b.setObjectName("iconbutton")
    b.setProperty("quiet", quiet)
    icons.set_icon(b, name, size=size)
    if hover:
        b.setToolTip(tip)
    b.setAccessibleName(tip)
    return b


def info_button(tip: str) -> QPushButton:
    """The ⓘ beside a card's heading: 24 px (the smallest target), so the heading's
    row doesn't grow. `tip` is its tooltip and screen-reader name."""
    b = icon_button("info", tip, size=16)
    b.setObjectName("infobutton")
    b.setFixedSize(24, 24)
    return b



def fold_button(text: str, body: QWidget | None = None) -> QPushButton:
    """The one look for a card's inline extras (DESIGN section 0: a few fields expand
    in place): a quiet checkable link with the fold arrow, which turns when it's open.
    `body` (hidden to start) shows and hides with it."""
    b = QPushButton(text)
    b.setObjectName("fold")
    b.setCheckable(True)
    icons.set_icon(b, "fold", "muted", "text", size=12)
    b.toggled.connect(lambda on: icons.set_icon(b, "fold_open" if on else "fold", "muted",
                                                "text", size=12))
    if body is not None:
        body.hide()
        b.toggled.connect(body.setVisible)
    return b


def reset_button(tip: str, *, hover: bool = True) -> QPushButton:
    """The one look for putting a part back to how it starts, beside that part (an
    effect, Live controls, a sound's effects): small, quiet, the reset arrow and the
    word, so it reads the same everywhere (a slim muted link: it never makes a card's
    heading row taller). `tip` says what goes back: the tooltip, or with `hover` off
    (the part it sits on already says it) only the screen-reader name."""
    b = QPushButton(_("Reset"))
    b.setObjectName("reset")
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    icons.set_icon(b, "reload", "muted", size=12)
    if hover:
        b.setToolTip(tip)
    else:
        b.setAccessibleName(tip)
    return b

class _LevelDot(Meter):
    """Audio activity beside a volume control, without a second slider-like track."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(6, 6)
        self.setAccessibleName(_("Audio activity"))
        self.setToolTip(_("Audio activity: green is signal, amber is loud, red is near clipping"))

    def paintEvent(self, e):
        frac, color = self._bar()
        p = QPainter(self)
        snap_to_pixels(p)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color if frac > 0 else theme.T["groove"]))
        p.drawEllipse(self.rect())
        p.end()


class _Pct(QSpinBox):
    """The typeable %: as wide as its longest value in the font the theme gives it
    (known only once styled: "1000 %" in Retro 98's Tahoma didn't fit a fixed 58 px).
    Typing sets the volume once, on Enter or leaving it: as each digit came in,
    "150" went 1 %, 15 %, 150 % (a dip on a live mic) and saved three times."""

    def __init__(self):
        super().__init__()
        self.setKeyboardTracking(False)

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            text = f"{self.maximum()}{self.suffix()}"
            self.setFixedWidth(max(58, self.fontMetrics().horizontalAdvance(text) + 14))


class VolumeControl(QWidget):
    """Slider to `slider_max` %, plus a % you can click and type an exact value into
    (up to `typed_max`). `changed` carries the gain as a factor (1.0 = 100 %).
    With `meter`, a small audio-activity dot (`.meter`) sits beside the slider."""
    changed = Signal(float)

    def __init__(self, value: float, slider_max: int = 300, typed_max: int = 1000,
                 tip: str = "", meter: bool = False):
        super().__init__()
        self.slider_max = slider_max
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        self.slider = CrispSlider(Qt.Orientation.Horizontal)
        self.meter = _LevelDot() if meter else None
        if self.meter is not None:
            h.addWidget(self.meter)
        self.slider.setRange(0, slider_max)
        self.slider.setMinimumWidth(70)
        self.slider.setMaximumWidth(150)
        self.spin = _Pct()
        self.spin.setObjectName("pct")   # reads as plain text until hovered / typed in
        self.spin.setRange(0, typed_max)
        self.spin.setSuffix("%")
        self.spin.setFixedWidth(58)   # until it's styled (_Pct)
        # beside its slider, on the row's centre line: right-aligned in a box as wide as
        # "1000%", "70%" sat 30-40 px away from its slider
        self.spin.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        # its text box rounds the centring down: the digits sat 1-1.5 px under the
        # slider and the labels beside it (measured ink); 2 px less at the bottom
        # moves the centre up by one
        self.spin.lineEdit().setTextMargins(0, 0, 0, 2)
        self.spin.setToolTip(_("Type an exact volume (0–{typed_max}%)", typed_max=typed_max))
        if tip:
            self.slider.setToolTip(tip)
        h.addWidget(self.slider, 1)
        h.addWidget(self.spin)
        no_wheel(self.slider, self.spin)

        pct0 = int(round(value * 100))
        self.slider.setValue(min(pct0, slider_max))
        self.spin.setValue(pct0)
        self._paint(pct0)
        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)

    def value(self) -> float:
        return self.spin.value() / 100

    def _paint(self, pct):
        col = ("" if pct <= 100 else f"color:{theme.status('warn' if pct <= 300 else 'error')};")
        sheet = f"{col} font-weight:600;"   # normal: the theme's text colour
        if sheet != self.spin.styleSheet():   # each set re-polishes it: only on a change
            self.spin.setStyleSheet(sheet)

    def _from_slider(self, pct):
        self.spin.blockSignals(True)
        self.spin.setValue(pct)
        self.spin.blockSignals(False)
        self._paint(pct)
        self.changed.emit(pct / 100)

    def _from_spin(self, pct):
        self.slider.blockSignals(True)
        self.slider.setValue(min(pct, self.slider_max))
        self.slider.blockSignals(False)
        self._paint(pct)
        self.changed.emit(pct / 100)


class EqPanel(QWidget):
    """On/off, target, preset, curve and the seven band sliders.
    `changed(gains, enabled, target, preset)` fires on any change. `fold`: while the EQ
    is off, only its heading and on/off row show (the Setup tab: seven flat sliders and
    an empty curve took a third of it)."""
    changed = Signal(list, bool, str, str)

    def __init__(self, enabled: bool, target: str, preset: str, gains: list[float],
                 fold: bool = False):
        super().__init__()
        self.fold = fold
        pv = QVBoxLayout(self)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(8)
        if not fold:   # (Setup's: the card it's in has the title)
            pv.addWidget(section_label(_("Equalizer")))
        row = QHBoxLayout()
        self.chk_on = QCheckBox(_("EQ on"))
        self.chk_on.setChecked(enabled)
        row.addWidget(self.chk_on)
        self.lbl_for = QLabel(_("for"))
        row.addWidget(self.lbl_for)
        self.cb_target = QComboBox()
        for label, key in ((_("My voice"), "voice"), (_("My sounds"), "sounds"),
                           (_("Both"), "all")):
            self.cb_target.addItem(label, key)
        icons.set_item_icons(self.cb_target, ["mic", "volume", "wave"])
        self.cb_target.setCurrentIndex(max(0, self.cb_target.findData(target)))
        row.addWidget(self.cb_target)
        row.addStretch(1)
        pv.addLayout(row)
        self.body = QWidget()   # everything under the on/off row (folds away: `fold`)
        bv = QVBoxLayout(self.body)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(8)
        pv.addWidget(self.body)

        self.cb_preset = QComboBox()
        # the item data is the preset's key, "Custom" for none; the keys are saved in
        # config, so they keep their old dash and only the shown name drops it
        for name in EQ_PRESETS:
            self.cb_preset.addItem(name.replace(" — ", ": "), name)
        self.cb_preset.addItem(_("Custom"), "Custom")
        bv.addWidget(self.cb_preset)
        no_wheel(self.cb_target, self.cb_preset)

        self.curve = EqCurve()
        bv.addWidget(self.curve)

        grid = QGridLayout()
        grid.setHorizontalSpacing(2)
        grid.setVerticalSpacing(2)
        self.sliders, self.vals = [], []
        for i, lab in enumerate(EQ_LABELS):
            val = QLabel("0")
            val.setAlignment(Qt.AlignmentFlag.AlignCenter)
            val.setObjectName("eqlabel")
            s = QSlider(Qt.Orientation.Vertical)
            s.setRange(-EQ_MAX_DB * 2, EQ_MAX_DB * 2)   # half-dB steps
            s.setFixedHeight(96)
            s.setAccessibleName(_("{lab} Hz", lab=lab))   # its label is under it
            f = QLabel(lab)
            f.setAlignment(Qt.AlignmentFlag.AlignCenter)
            f.setObjectName("eqlabel")
            grid.addWidget(val, 0, i)
            grid.addWidget(s, 1, i, Qt.AlignmentFlag.AlignHCenter)
            grid.addWidget(f, 2, i)
            s.valueChanged.connect(self._on_slider)
            self.sliders.append(s)
            self.vals.append(val)
        no_wheel(*self.sliders)
        bv.addLayout(grid)
        bv.addWidget(hint_label(_("Low = bass (left) · high = treble (right). Drag up to boost, "
                                  "down to cut. Double-click the curve to reset.")))

        self._set_sliders(gains)
        self._show_preset(preset)
        self.chk_on.toggled.connect(lambda _on: self._emit())
        self.cb_target.currentIndexChanged.connect(lambda _i: self._emit())
        self.cb_preset.currentIndexChanged.connect(
            lambda _i: self._on_preset(self.cb_preset.currentData()))
        self.curve.reset.connect(self._reset)
        self._refresh(emit=False)

    # ---- state
    def gains(self) -> list[float]:
        return [s.value() / 2 for s in self.sliders]

    def set_gains(self, gains: list[float], preset: str = "Custom"):
        """Load gains, turning the EQ on unless they're flat. Emits `changed`."""
        self._set_sliders(gains)
        self.cb_preset.blockSignals(True)
        self._show_preset(preset)
        self.cb_preset.blockSignals(False)
        self.chk_on.blockSignals(True)
        self.chk_on.setChecked(any(abs(g) >= 0.05 for g in self.gains()))
        self.chk_on.blockSignals(False)
        self._emit()

    def state(self) -> tuple[list[float], bool, str, str]:
        return (self.gains(), self.chk_on.isChecked(), self.cb_target.currentData(),
                self.cb_preset.currentData())

    # ---- internals
    def _show_preset(self, preset: str):
        """Select `preset` (a key of EQ_PRESETS) in the box, or Custom."""
        key = preset if preset in EQ_PRESETS else "Custom"
        self.cb_preset.setCurrentIndex(max(0, self.cb_preset.findData(key)))

    def _set_sliders(self, gains):
        # a damaged config can hand us anything: a band that isn't a finite number, or
        # a list of the wrong length, is flat (0 dB) instead of an error
        if not isinstance(gains, (list, tuple)) or len(gains) != len(self.sliders):
            gains = [0.0] * len(self.sliders)
        for s, g in zip(self.sliders, gains):
            ok = isinstance(g, (int, float)) and not isinstance(g, bool) and math.isfinite(g)
            s.blockSignals(True)
            s.setValue(int(round(min(max(g, -EQ_MAX_DB), EQ_MAX_DB) * 2)) if ok else 0)
            s.blockSignals(False)
        self._refresh_labels()

    def _refresh_labels(self):
        for s, lab in zip(self.sliders, self.vals):
            g = s.value() / 2
            lab.setText(f"{g:+g}" if g else "0")

    def _on_slider(self, _v):
        self._refresh_labels()
        self.cb_preset.blockSignals(True)
        self._show_preset("Custom")
        self.cb_preset.blockSignals(False)
        if not self.chk_on.isChecked():
            self.chk_on.setChecked(True)   # touching the EQ means you want it on (emits)
            return
        self._emit()

    def _reset(self):
        """Double-click on the curve: flat and off, even if it already says Flat."""
        self.cb_preset.blockSignals(True)
        self._show_preset("Flat (off)")
        self.cb_preset.blockSignals(False)
        self._on_preset("Flat (off)")

    def _on_preset(self, name):
        if name in EQ_PRESETS:
            self._set_sliders(EQ_PRESETS[name])
            # "Flat (off)" means off, like set_gains with flat gains; any other turns it on
            on = name != "Flat (off)"
            if self.chk_on.isChecked() != on:
                self.chk_on.setChecked(on)   # emits
                return
        self._emit()

    def _refresh(self, emit=True):
        gains, on, _target, _preset = self.state()
        self.curve.set_gains(gains, on)
        self.body.setVisible(on or not self.fold)
        for w in self.sliders + [self.cb_target]:
            if bool(w.property("dim")) != (not on):
                w.setProperty("dim", not on)
                w.style().unpolish(w)   # a property change alone doesn't restyle it
                w.style().polish(w)
                w.update()
        if emit:
            self.changed.emit(*self.state())

    def _emit(self):
        self._refresh(emit=True)


class UndoBar(QWidget):
    """"Deleted X · Undo" for a few seconds after something is thrown away, as a corner
    card (ui/toast.py) with an Undo button; this widget itself is never seen.
    show_for(text, undo, done): Undo calls `undo`; the card timing out, being closed,
    or showing something else calls `done` (if given) instead."""
    SECONDS = 10

    def __init__(self, tip: str = ""):
        super().__init__()
        self.tip = tip or _("Put it back, exactly as it was")
        self.text = ""
        self._undo = self._done = None
        self._key = f"undo-{id(self)}"
        self.hide()

    def active(self) -> bool:
        """Is its card up (Undo still possible)?"""
        return self._undo is not None or self._done is not None

    def show_for(self, text: str, undo, done=None):
        from soundboard.ui import busy
        self.finish()
        self.text = text
        self._undo, self._done = undo, done
        t = busy.toast(self, html.escape(text), "", self.SECONDS * 1000, key=self._key,
                       action=(_("Undo"), self.undo), on_close=self.finish)
        if t is not None:
            t.card.action.setToolTip(self.tip)

    def _take_down(self):
        from soundboard.ui import toast
        toast.close(self, self._key)

    def undo(self):
        cb, self._undo, self._done = self._undo, None, None
        self._take_down()
        if cb is not None:
            cb()

    def finish(self):
        cb, self._undo, self._done = self._done, None, None
        self._take_down()
        if cb is not None:
            cb()
