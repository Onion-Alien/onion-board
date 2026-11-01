"""Shared UI building blocks: the bar / card / divider helpers every tab is built
from, the compact volume control (slider + typed %), and the equalizer. They own
their widgets and emit plain values; the main window maps those onto the config
and the engine."""
from __future__ import annotations

import html

from PySide6.QtCore import QEvent, QObject, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QRegion
from shiboken6 import isValid as qt_valid
from PySide6.QtWidgets import (QApplication, QBoxLayout, QFrame, QHBoxLayout, QLabel, QListWidget,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from soundboard.audio.eq import PRESETS as EQ_PRESETS  # noqa: F401  (EqPanel's presets, as before)
from soundboard.ui.kit import theme
from soundboard.ui.kit import icons
from soundboard.i18n import _
from soundboard.ui.kit.panellabels import hint_label, section_label, steady_number  # noqa: F401
from soundboard.ui.kit.panellayouts import CardGrid, Flow, keep_focus_off, ShownStack  # noqa: F401
from soundboard.ui.kit.panelcontrols import (  # noqa: F401
    _LevelDot,
    _Pct,
    EqPanel,
    UndoBar,
    VolumeControl,
)

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


class HoverCard(QFrame):
    """A card whose hover surface stays active over its child labels and controls."""

    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        theme.vary_texture(self)
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
    theme.vary_texture(f)
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

    def empty_text(self) -> str:
        """What it says now: "" while it has rows."""
        return "" if self.count() else self._empty_text

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


class ViewToggle(QFrame):
    """Cards or a list: two icon buttons side by side, the one in use lit. The same
    switch at the top right of the Sounds, Apps and Voice tabs."""
    changed = Signal(str)   # "grid" or "list"

    def __init__(self, view: str = "grid", what: str = ""):
        super().__init__()
        self.setObjectName("viewtoggle")
        h = QHBoxLayout(self)
        h.setContentsMargins(3, 3, 3, 3)   # the same room on every side of the buttons
        h.setSpacing(2)
        self.buttons: dict[str, QPushButton] = {}
        self._compact = False
        for key, icon, tip in (("grid", "sounds", _("Show as cards")),
                               ("list", "list", _("Show as a list"))):
            b = QPushButton()
            b.setObjectName("viewbtn")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setFixedSize(26, 26)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            icons.set_icon(b, icon, "muted", "on_accent", size=16)
            b.setToolTip(tip)
            b.setAccessibleName(f"{what}: {tip}" if what else tip)
            b.clicked.connect(lambda __=False, k=key: self._pick(k))
            h.addWidget(b)
            self.buttons[key] = b
        self.set_view(view)

    def view(self) -> str:
        return "list" if self.buttons["list"].isChecked() else "grid"

    def set_view(self, view: str):
        self.buttons["list" if view == "list" else "grid"].setChecked(True)
        self._show_buttons()

    def set_compact(self, on: bool):
        """A very narrow window: only the other view's icon, one click away."""
        self._compact = on
        self._show_buttons()

    def _show_buttons(self):
        for b in self.buttons.values():
            b.setVisible(not (self._compact and b.isChecked()))
        lay = self.layout()
        if lay is not None:
            lay.invalidate()
        self.updateGeometry()   # the toolbar's cached size of it is stale otherwise

    def _pick(self, key: str):
        had_focus = self.buttons[key].hasFocus()
        self._show_buttons()
        if had_focus and self._compact:   # the clicked icon went: focus to the one left
            self.buttons["grid" if key == "list" else "list"].setFocus()
        self.changed.emit(key)


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
    b.toggled.connect(lambda _on: paint_once_settled(b))   # first: before anything grows
    icons.set_icon(b, "fold", "muted", "text", size=12)
    b.toggled.connect(lambda on: icons.set_icon(b, "fold_open" if on else "fold", "muted",
                                                "text", size=12))
    if body is not None:
        body.hide()
        b.toggled.connect(body.setVisible)
    return b


def paint_once_settled(w: QWidget):
    """Draw `w`'s window again only once the change just made has been laid out. A fold
    opening in a scrolling page is laid out twice: first in the page's old height (the
    cards above squashed, Devices jumping ~150 px up), then in its new one. Each pass was
    drawn, so the cards flashed out of place for a moment."""
    top = w.window()
    if not top.updatesEnabled():   # already waiting
        return
    top.setUpdatesEnabled(False)

    def done():
        # the new parts get their style (and so their size), then the card → column →
        # page → scroll area are laid out again, one level per pass
        for _pass in range(6):
            QApplication.sendPostedEvents()
        top.setUpdatesEnabled(True)
    QTimer.singleShot(0, top, done)   # after the other toggled slots fill it


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
