"""How the Store tab fits its width (`StoreFit`, a mixin of StoreTab): the toolbar on one
row or two, *Share a sound* with or without its words, and as many cards a row as fit."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (QComboBox, QGridLayout, QHBoxLayout, QLayout, QLineEdit, QPushButton,
                               QScrollArea, QStyle, QStyleOptionComboBox, QStylePainter, QWidget)

from soundboard.online import store
from soundboard.i18n import _
from soundboard.ui.store.storerow import SoundRow

CARD_MIN_W = 300              # a card's narrowest: as many across as fit at this width
CARD_GAP = 8                  # between the cards
LIST_GAP = 8                  # between the cards and the scroll bar (DESIGN.md, *Breathing room*)
ONE_ROW = 720                 # a narrower tab puts the toolbar on two rows


class CutCombo(QComboBox):
    """The category dropdown: squeezed below its words (a narrow tab), its choice ends
    in "…" instead of a letter cut in half."""

    def paintEvent(self, e):
        p = QStylePainter(self)
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        p.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, opt)
        room = self.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, opt,
                                           QStyle.SubControl.SC_ComboBoxEditField, self).width()
        if not opt.currentIcon.isNull():
            room -= opt.iconSize.width() + 4   # (the style's gap after the icon)
        opt.currentText = self.fontMetrics().elidedText(opt.currentText,
                                                        Qt.TextElideMode.ElideRight, room)
        p.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, opt)


# what the mixin gets from StoreTab, for the type checker only: at run time
# it is a plain class (StoreTab itself is the widget)
_Base = QWidget if TYPE_CHECKING else object


class StoreFit(_Base):
    """StoreTab's toolbar and card grid, as the tab's width changes."""
    if TYPE_CHECKING:
        _bars: tuple[QHBoxLayout, QHBoxLayout]
        _cat_short: list[str]
        _cols: int
        _grid: QGridLayout
        _list_top: int | None
        _mode: str
        _need: tuple[int, int] | None
        _one_row: bool | None
        _rows: list[SoundRow]
        _share_words: bool
        btn_reload: QPushButton
        btn_share: QPushButton
        cat_pick: QComboBox
        list_area: QScrollArea
        modes_box: QWidget
        search: QLineEdit
        toolbar: QWidget

    def _hold_rows(self):
        """The rows stay where they are on screen when something above the tab comes or
        goes: the download bar opening for a played link pushed the list down, so the row
        just clicked slid away (it looked like a jump back up the list)."""
        vp = self.list_area.viewport()
        top = vp.mapTo(self.window(), QPoint(0, 0)).y()
        was, self._list_top = getattr(self, "_list_top", None), top
        if was is not None and top != was and self.isVisible():
            sb = self.list_area.verticalScrollBar()
            sb.setMaximum(max(sb.maximum(), sb.value() + top - was))   # (its range catches up)
            sb.setValue(sb.value() + top - was)

    def _toolbar_parts(self) -> list[QWidget]:
        return [w for w in (self.modes_box, self.search, self.cat_pick, self.btn_share,
                            self.btn_reload) if not w.isHidden()]

    def _fit_toolbar(self):
        """One row when the card has room for all of it (and the tab is wide), else two."""
        room = self.width() - 28   # (the banner's side margins)
        parts = self._toolbar_parts()
        full = self._share_w(self._share_label())
        need = sum(full if w is self.btn_share else w.minimumSizeHint().width()
                   if w is self.search else w.sizeHint().width()
                   for w in parts) + 8 * (len(parts) - 1)
        self._lay_toolbar(self.width() >= ONE_ROW and room >= need)
        # the first of two rows, Sounds / Voices and Share, wanted 487 px with Share's
        # words: wider than the mini player's cut-off, so the window went mini on it
        words = bool(self._one_row) or room >= self._modes_w() + 8 + full
        if words != self._share_words:
            self._share_words = words
            self._share_look()

    def _share_label(self) -> str:
        return _("Share a voice") if self._mode == "voices" else _("Share a sound")

    def _share_look(self):
        """Share's words on it, or (narrow) its icon only with the words as its tooltip.
        Greyed out, saying why, while the store's server is down."""
        label = self._share_label()
        down = store.is_down()
        self.btn_share.setEnabled(not down)
        self.btn_share.setText(label if self._share_words else "")
        self.btn_share.setToolTip(store.down_share() if down
                                  else "" if self._share_words else label)
        self.btn_share.setAccessibleName(label)

    def _share_w(self, text: str) -> int:
        """The Share button's width with `text` on it."""
        b = self.btn_share
        was = b.text()
        if was == text:
            return b.sizeHint().width()
        b.setText(text)
        w = b.sizeHint().width()
        b.setText(was)
        return w

    def _modes_w(self) -> int:
        return self.modes_box.sizeHint().width() * (not self.modes_box.isHidden())

    def _cat_floor(self) -> int:
        """The category dropdown's narrowest: room for the names in _cat_short (the
        orders: Trending, Most liked, Newest). A longer one (Community uploads, a
        category) is cut short in a narrow tab: counted whole, it made the window go
        mini at 480 px."""
        cb = self.cat_pick
        whole = cb.sizeHint().width()
        names = [cb.itemText(i) for i in range(cb.count())]
        if not self._cat_short or not names:
            return whole
        fm = cb.fontMetrics()
        longest = max(fm.horizontalAdvance(t) for t in names)
        short = max(fm.horizontalAdvance(t) for t in self._cat_short)
        return whole - max(0, longest - short)

    def _lay_toolbar(self, one: bool):
        """The toolbar in one row (a wide tab), or two: Sounds / Voices and Share, then
        the search, the category and Refresh."""
        floor = self._cat_floor()
        self.cat_pick.setMinimumWidth(floor)
        # the box asks for the two rows' width, whichever is shown
        rows = (self._modes_w() + 8 + self._share_w(""),
                self.search.minimumSizeHint().width() + floor
                + self.btn_reload.sizeHint().width() + 16)
        self.toolbar.setMinimumWidth(max(rows))
        if one == self._one_row:
            return
        self._one_row = one
        for bar in self._bars:
            while bar.count():
                bar.takeAt(0)   # (the widgets stay the card's; the stretch goes)
        first, second = self._bars[0], self._bars[0 if one else 1]
        first.addWidget(self.modes_box)
        if not one:
            first.addStretch(1)
            first.addWidget(self.btn_share)
        second.addWidget(self.search, 1)
        second.addWidget(self.cat_pick)
        if one:
            second.addWidget(self.btn_share)
        second.addWidget(self.btn_reload)

    # ------------------------------------------------------------------ the table
    def _fit_columns(self, force: bool = False):
        """As many cards a row as fit the list with their buttons' words (CARD_MIN_W
        each, or the widest card's smallest if other fonts make it wider). Not even one
        fits: every card shows their pictures only, as many a row as fit that way.
        Measured on every card at its widest, so longer words, other fonts or a link's
        Stop never cut a card off."""
        if not self._rows:
            return
        if force:
            self._need = None
        w = self.list_area.viewport().width() - LIST_GAP
        full, small = self._card_needs()
        compact = w < full
        least = max(CARD_MIN_W, small if compact else full)
        cols = max(1, (w + CARD_GAP) // (least + CARD_GAP))
        if force or cols != self._cols:
            self._cols = cols
            for r in self._rows:
                self._grid.removeWidget(r)
            for i, r in enumerate(self._rows):
                self._grid.addWidget(r, i // cols, i % cols)
            for c in range(max(cols, self._grid.columnCount())):
                self._grid.setColumnStretch(c, 1 if c < cols else 0)
        for r in self._rows:
            r.compact(compact)

    def _card_needs(self) -> tuple[int, int]:
        """(with words, pictures only): the widest card's smallest width, each card as wide
        as it gets (Play's longest word, a link's Stop out). Kept until the list changes."""
        if self._need is None:
            words = [_("Play"), _("Pause"), _("Resume"), _("Stop")]
            full = small = 0
            for r in self._rows:
                r.ensurePolished()   # (its style's padding: a new card has none yet)
                was, text, hid = r._compact, r.btn_play.text(), r.btn_stop.isHidden()
                r.btn_stop.setHidden(r.btn_queue.isHidden())   # (only a link plays on)
                r.compact(True)
                small = max(small, self._needs(r))
                r.compact(False)
                for word in words:
                    r.btn_play.setText(word)
                    full = max(full, self._needs(r))
                r.btn_play.setText(text)
                r.btn_stop.setHidden(hid)
                r.compact(was)
            self._need = (full, small)
        return self._need

    @staticmethod
    def _needs(r) -> int:
        """The card's smallest width, as its buttons are now (its own frame included).
        Every layout in it is redone first: a card not shown yet keeps its old sizes."""
        lay = r.layout()
        if lay is None:
            return r.minimumSizeHint().width()
        for sub in [*r.findChildren(QLayout), lay]:
            sub.invalidate()
        return max(lay.minimumSize().width(), r.minimumSizeHint().width())
