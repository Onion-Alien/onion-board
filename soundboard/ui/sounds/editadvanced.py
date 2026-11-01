"""Edit sound's Advanced view (ui/sounds/dialogs.py `EditDialog`): a bigger window with
the sound's waveform big across the top (trim handles, ruler, zoom, the fades drawn on
it) and the Speed & loudness, Effects and Equalizer pages side by side under it (as tabs
when the screen is too narrow for three columns). It shows the same widgets as the Simple
view, moved here, so both views are always the same draft.

`ModeSwitch` is the Simple | Advanced switch, `EffectPicker` the Add effect pop-up."""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QScrollArea, QSizePolicy,
                               QTabWidget, QVBoxLayout, QWidget)

from soundboard import voicefx
from soundboard.i18n import _
from soundboard.sounds.library import original_peaks
from soundboard.ui.kit import busy, icons
from soundboard.ui.kit.layouts import take_out
from soundboard.ui.kit.panel import card, hint_label, section_label
from soundboard.ui.sounds.splicepanel import SpliceBar
from soundboard.ui.voice.effectrow import ADDON_GROUP, FX_ICONS, GROUPS

if TYPE_CHECKING:
    from soundboard.ui.sounds.dialogs import EditDialog

WIDE_PX = 1180      # from this wide, three columns (when they fit: fits()); narrower, tabs
FINE_PEAKS = 2400   # the big waveform's peaks: enough to zoom in sixteen times
PICKER_COLS = 3
EQ_TOP = 5           # px: see attach()
QWIDGETSIZE_MAX = (1 << 24) - 1   # Qt's "no maximum"


def key_names(key: QKeySequence.StandardKey) -> str:
    """The keys that do `key` here, as this system writes them ("Ctrl+Z")."""
    seqs = QKeySequence.keyBindings(key)
    return " / ".join(s.toString(QKeySequence.SequenceFormat.NativeText)
                      for s in seqs[:2] if not s.isEmpty())


class ModeSwitch(QWidget):
    """Simple | Advanced, as two exclusive buttons. `picked(advanced)` on a click."""
    picked = Signal(bool)

    def __init__(self, advanced: bool = False, slim: bool = False):
        """`slim`: as tall as a tab row (it squeezed the words)."""
        super().__init__()
        self.setObjectName("segbox")
        h = QHBoxLayout(self)
        h.setContentsMargins(*((2, 1, 2, 1) if slim else (3, 3, 3, 3)))
        h.setSpacing(2)
        self._group = QButtonGroup(self)
        self.simple = QPushButton(_("Simple"))
        self.advanced = QPushButton(_("Advanced"))
        self.simple.setToolTip(_("The settings most people change, on one page"))
        self.advanced.setToolTip(_("A bigger window: the waveform big, with the effects "
                                   "and the equalizer side by side"))
        for b in (self.simple, self.advanced):
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            self._group.addButton(b)
            h.addWidget(b)
        self.set_advanced(advanced)
        self.simple.clicked.connect(lambda: self.picked.emit(False))
        self.advanced.clicked.connect(lambda: self.picked.emit(True))
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def set_advanced(self, on: bool):
        (self.advanced if on else self.simple).setChecked(True)


class EffectPicker(QFrame):
    """Add effect: every effect in its group as a tile (its icon, name, and what it does
    as the tooltip), a search box over them. The ones on are ticked; a click turns one
    on (or off again). Closes on a click outside or Esc."""

    def __init__(self, effects, parent: QWidget, added=None):
        """`added(etype)`: one was turned on (the list brings it into view)."""
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("card")
        self.effects = effects
        self.added = added
        self.setMinimumWidth(460)
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Search effects"))
        self.search.setAccessibleName(_("Search effects"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        v.addWidget(self.search)
        self.tiles: dict[str, QPushButton] = {}
        self._parts: list[tuple[QLabel, QWidget, list[str]]] = []
        grouped = {t for _t, types in GROUPS for t in types}
        for title, types in (*GROUPS,
                             (ADDON_GROUP, [t for t in effects.rows if t not in grouped])):
            types = [t for t in types if t in effects.rows]
            if not types:
                continue
            head = section_label(title)
            box = QWidget()
            g = QGridLayout(box)
            g.setContentsMargins(0, 0, 0, 0)
            g.setSpacing(8)
            for i, t in enumerate(types):
                cls = effects.rows[t].cls
                b = QPushButton(voicefx.shown(cls.name))
                b.setToolTip(voicefx.shown(cls.description))
                b.setCheckable(True)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.clicked.connect(lambda on, t=t: self._pick(t, on))
                g.addWidget(b, i // PICKER_COLS, i % PICKER_COLS)
                self.tiles[t] = b
            for c in range(PICKER_COLS):
                g.setColumnStretch(c, 1)
            v.addWidget(head)
            v.addWidget(box)
            self._parts.append((head, box, types))
        self.nothing = hint_label(_("No effect has that name."))
        self.nothing.hide()
        v.addWidget(self.nothing)
        self.sync()

    def sync(self):
        """Tick the ones that are on."""
        for t, b in self.tiles.items():
            on = self.effects.rows[t].chk.isChecked()
            b.setChecked(on)
            icons.set_icon(b, "check" if on else FX_ICONS.get(t, "sliders"),
                           "accent_hi" if not on else None, size=14)

    def _pick(self, etype: str, on: bool):
        self.effects.turn_on(etype, on)
        self.sync()
        if on:
            self.close()
            if self.added is not None:
                self.added(etype)

    def _filter(self, text: str):
        words = text.casefold().split()
        any_shown = False
        for head, box, types in self._parts:
            shown = 0
            for t in types:
                b = self.tiles[t]
                hay = f"{b.text()} {b.toolTip()}".casefold()
                ok = all(w in hay for w in words)
                b.setVisible(ok)
                shown += ok
            head.setVisible(bool(shown))
            box.setVisible(bool(shown))
            any_shown = any_shown or bool(shown)
        self.nothing.setVisible(not any_shown)
        self.adjustSize()

    def show_under(self, anchor: QWidget):
        self.sync()
        self.search.clear()
        self.adjustSize()
        at = anchor.mapToGlobal(QPoint(0, anchor.height() + 6))
        screen = anchor.screen().availableGeometry()
        x = min(at.x(), screen.right() - self.width() - 8)
        y = at.y()
        if y + self.height() > screen.bottom() - 8:   # no room under it: above it
            y = anchor.mapToGlobal(QPoint(0, 0)).y() - self.height() - 6
        self.move(max(x, screen.left() + 8), max(y, screen.top() + 8))
        self.show()
        self.search.setFocus(Qt.FocusReason.PopupFocusReason)


class AdvancedView(QWidget):
    """The Advanced layout around EditDialog `d`'s own widgets (see the module doc)."""
    fine_read = Signal(int, object)   # (which sound, peaks) from the waveform worker

    def __init__(self, d: EditDialog):
        super().__init__()
        self.d = d
        eff = d.effects
        self._gen = 0
        self.fine_read.connect(self._on_fine)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)

        # the top line: the sound's name and hotkey (the same as on the Sound tab, which
        # keeps the rest; its volume is in Speed & loudness), then the Simple | Advanced
        # switch
        top = self.top = QHBoxLayout()
        top.setSpacing(8)
        self.name = QLineEdit(d.name.text())
        self.name.setFont(d.name.font())
        self.name.setAccessibleName(_("Name"))
        self.name.setMinimumWidth(180)
        self.name.setMaximumWidth(360)
        self.name.textChanged.connect(lambda t: d.name.text() != t and d.name.setText(t))
        d.name.textChanged.connect(lambda t: self.name.text() != t and self.name.setText(t))
        top.addWidget(self.name, 1)
        self.hk = QPushButton(d.hk_btn.text())
        self.hk.setAccessibleName(_("Hotkey"))
        icons.set_icon(self.hk, "keyboard")
        self.hk.clicked.connect(d._capture)
        top.addWidget(self.hk)
        top.addStretch(1)
        self.switch = ModeSwitch(True)
        top.addWidget(self.switch)
        v.addLayout(top)

        # the editor: its buttons, the trim (big), what the handles do
        self.editor, ev = card()
        bar = self.bar = QHBoxLayout()
        bar.setSpacing(8)
        self.btn_play = QPushButton(_("Preview"))
        icons.set_icon(self.btn_play, "headphones")
        self.btn_play.setToolTip(_("Preview (only you hear it)"))
        self.btn_play.clicked.connect(d.btn_preview.click)
        bar.addWidget(self.btn_play)
        bar.addSpacing(8)
        self.btn_undo = QPushButton(_("Undo"))
        icons.set_icon(self.btn_undo, "back")
        self.btn_undo.setToolTip(_("Undo ({keys})",
                                   keys=key_names(QKeySequence.StandardKey.Undo)))
        self.btn_undo.clicked.connect(d.undo)
        self.btn_redo = QPushButton(_("Redo"))
        icons.set_icon(self.btn_redo, "forward")
        self.btn_redo.setToolTip(_("Redo ({keys})",
                                   keys=key_names(QKeySequence.StandardKey.Redo)))
        self.btn_redo.clicked.connect(d.redo)
        bar.addWidget(self.btn_undo)
        bar.addWidget(self.btn_redo)
        bar.addStretch(1)
        self.splices = SpliceBar(d)
        d.btn_preview.clicked.connect(lambda: self.splices.trim.clear_solo())
        bar.addWidget(self.splices)
        bar.addSpacing(8)
        self.btn_out, self.btn_in = QPushButton("−"), QPushButton("+")
        self.btn_fit = QPushButton()
        icons.set_icon(self.btn_fit, "expand")
        for b, tip in ((self.btn_out, _("Zoom out")), (self.btn_in, _("Zoom in")),
                       (self.btn_fit, _("Show the whole sound"))):
            b.setToolTip(tip)
            b.setAccessibleName(tip)
            b.setFixedWidth(36)
            bar.addWidget(b)
        self.btn_out.clicked.connect(lambda: self._zoom(0.5))
        self.btn_in.clicked.connect(lambda: self._zoom(2.0))
        self.btn_fit.clicked.connect(lambda: self._zoom(None))
        ev.addLayout(bar)
        self.trim_box = QVBoxLayout()
        self.trim_box.setContentsMargins(0, 0, 0, 0)
        ev.addLayout(self.trim_box, 1)
        ev.addWidget(hint_label(eff.trim_kept.text()))
        v.addWidget(self.editor, 5)

        # fades, under Speed & loudness: the Sound tab's own, mirrored, and drawn on
        # the waveform
        self.fades = QWidget()
        fl = QVBoxLayout(self.fades)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(8)
        fl.addWidget(section_label(_("Fades")))
        fg = QGridLayout()
        fg.setHorizontalSpacing(24)
        fl.addLayout(fg)
        self.fade_in = d._fade_cell(fg, 0, 0, _("Fade in"), d.fade_in.value() / 10,
                                    d.fade_in.toolTip())
        self.fade_out = d._fade_cell(fg, 0, 1, _("Fade out"), d.fade_out.value() / 10,
                                     d.fade_out.toolTip())
        for mine, theirs in ((self.fade_in, d.fade_in), (self.fade_out, d.fade_out)):
            mine.valueChanged.connect(theirs.setValue)
            theirs.valueChanged.connect(mine.setValue)
            theirs.valueChanged.connect(self._show_fades)

        # under the editor: three columns, or (narrow) three tabs
        self.cols = QWidget()
        ch = self._cols_lay = QHBoxLayout(self.cols)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.setSpacing(12)
        self.col_boxes = []
        for title, stretch in ((_("Speed & loudness"), 12), (_("Effects"), 13),
                               (_("Equalizer"), 11)):
            c, cv = card(title)
            cv.setContentsMargins(14, 16, 4, 8)   # the page's scroll bar at the edge
            ch.addWidget(c, stretch)
            self.col_boxes.append(cv)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        v.addWidget(self.cols, 6)
        v.addWidget(self.tabs, 6)
        self.tabs.hide()
        self.wide = True
        self._scrolls: list[QScrollArea] = []

        eff.add_effect.clicked.connect(self._pick_effect)
        self.picker: EffectPicker | None = None

    # ------------------------------------------------------------------ in and out
    def attach(self, scrolls: list[QScrollArea], width: int):
        """Show the dialog's three pages (their scroll areas, out of its tabs) here, the
        trim big on top, as columns or tabs for a window `width` wide."""
        d, eff = self.d, self.d.effects
        self._scrolls = scrolls
        for s in scrolls:   # an effect turned on can widen its page: eventFilter()
            if (page := s.widget()) is not None:
                page.installEventFilter(self)
        self.wide = self.fits(width)
        self._place()
        # the trim: out of Simple's Trim card, into the editor
        self._move_trim(self.trim_box)
        eff.trim_hint.hide()
        eff.trim_kept.hide()
        tl = eff.trim_page.layout()
        tl.insertWidget(tl.count() - 1, self.fades)   # before the page's stretch
        self.fades.show()
        for lab in eff.eq.findChildren(QLabel):   # its card says Equalizer already
            if lab.objectName() == "section":
                lab.hide()
        # its first row level with the other columns' (they start with a heading's
        # padding: EQ on is a check box)
        eff.eq.layout().setContentsMargins(0, EQ_TOP, 0, 0)
        eff.set_compact(True)
        self._show_fades()
        self.hk.setText(d.hk_btn.text())

    def detach(self):
        """Give the pages and the trim back to the Simple view."""
        eff = self.d.effects
        for s in self._scrolls:
            if (page := s.widget()) is not None:
                page.removeEventFilter(self)
            self._unplace(s)
        tl = eff.trim_page.layout()
        i = tl.indexOf(self.fades)
        if i >= 0:
            take_out(tl, i)
        self.fades.hide()
        self.fades.setParent(self)
        self._move_trim(eff.trim_box.layout(), 0)
        eff.trim_kept.setVisible(eff.trim.length > 0)
        eff.trim_hint.setVisible(eff.trim.length <= 0)
        for lab in eff.eq.findChildren(QLabel):
            if lab.objectName() == "section":
                lab.show()
        eff.eq.layout().setContentsMargins(0, 0, 0, 0)
        eff.set_compact(False)
        if self.picker is not None:
            self.picker.close()

    def _move_trim(self, layout, at: int = -1):
        eff = self.d.effects
        trim = eff.trim
        old = eff.trim_layout
        i = old.indexOf(trim)
        if i >= 0:
            take_out(old, i)
        if at < 0:
            layout.addWidget(trim, 1)
        else:
            layout.insertWidget(at, trim)
        eff.trim_layout = layout
        big = layout is self.trim_box
        trim.set_big(big)
        if big:
            self._fetch_fine()

    def retrim(self):
        """set_sound made a new trim for another sound: it's already where the old one
        was; make it big and get its peaks."""
        eff = self.d.effects
        self.splices.attach(eff.trim)
        if eff.trim_layout is self.trim_box:
            eff.trim.set_big(True)
            self._fetch_fine()
            self._show_fades()

    def set_wide(self, wide: bool):
        if wide != self.wide:
            for s in self._scrolls:
                self._unplace(s)
            self.wide = wide
            self._place()

    @staticmethod
    def _col_w(s: QScrollArea) -> int:
        """A column's least width: its page whole, beside its scroll bar."""
        page = s.widget()
        return ((page.minimumSizeHint().width() if page is not None else 0)
                + s.verticalScrollBar().sizeHint().width() + 2 * s.frameWidth())

    def fits(self, width: int) -> bool:
        """Three columns in a window `width` wide: each as wide as its page needs (the
        stretch gave the equalizer room Speed & loudness and Effects lacked, and they
        scrolled sideways, cut off), else three tabs (a long language, too)."""
        m = self.d._lay.contentsMargins()
        cv = self.col_boxes[0].contentsMargins()
        need = (sum(self._col_w(s) + cv.left() + cv.right() + 2 for s in self._scrolls)
                + 2 * self._cols_lay.spacing() + m.left() + m.right())
        return width >= max(WIDE_PX, need)

    def eventFilter(self, obj, e):
        try:   # (nothing in a Qt override may raise: AGENT-RULES *Async results*)
            if e.type() == QEvent.Type.LayoutRequest and self.wide and self.isVisible():
                for s in self._scrolls:
                    if s.widget() is obj:
                        s.setMinimumWidth(self._col_w(s))
                self.set_wide(self.fits(self.d.width()))
                self._fit_cols()
        except Exception:  # noqa: BLE001
            pass
        return False

    def resizeEvent(self, e):
        super().resizeEvent(e)
        try:   # (nothing in a Qt override may raise: AGENT-RULES *Async results*)
            self._fit_cols()
        except Exception:  # noqa: BLE001
            pass

    def _fit_cols(self):
        """The columns tall enough for Speed & loudness and the Equalizer whole: the
        waveform gives up the room first, down to its floor (split by stretch alone, a
        1320 x 880 window scrolled the equalizer for its last lines). A ceiling on the
        waveform, not a floor under the columns: that would raise the window's least
        size. Effects isn't counted: with effects on it grows long and scrolls, and the
        waveform shouldn't jump with each one."""
        top = self.editor.maximumHeight()
        if not self.wide or len(self._scrolls) < 3 or not self.cols.isVisible():
            if top != QWIDGETSIZE_MAX:
                self.editor.setMaximumHeight(QWIDGETSIZE_MAX)
            return
        need = 0
        for s in (self._scrolls[0], self._scrolls[2]):
            page = s.widget()
            if page is None or s.height() <= 0:
                continue
            h = page.minimumSizeHint().height()
            if page.hasHeightForWidth():
                h = max(h, page.heightForWidth(s.viewport().width()))
            chrome = self.cols.height() - s.height()   # the card's title and margins
            need = max(need, h + 2 * s.frameWidth() + chrome)
        lay = self.layout()
        first = lay.itemAt(0) if lay is not None else None
        if lay is None or first is None:
            return
        both = self.height() - first.sizeHint().height() - 2 * lay.spacing()
        cap = max(self.editor.minimumSizeHint().height(), both - need)
        if cap != top:
            self.editor.setMaximumHeight(cap)

    def _place(self):
        titles = (_("Speed & loudness"), _("Effects"), _("Equalizer"))
        if self.wide:
            for box, s in zip(self.col_boxes, self._scrolls):
                box.addWidget(s, 1)
                s.setMinimumWidth(self._col_w(s))
                s.show()
        else:
            for s, title in zip(self._scrolls, titles):
                self.tabs.addTab(s, title.replace("&", "&&"))
            self.tabs.setCurrentIndex(1)
        self.cols.setVisible(self.wide)
        self.tabs.setVisible(not self.wide)

    def _unplace(self, s: QScrollArea):
        i = self.tabs.indexOf(s)
        if i >= 0:
            self.tabs.removeTab(i)
        for box in self.col_boxes:
            j = box.indexOf(s)
            if j >= 0:
                take_out(box, j)
        s.setMinimumWidth(0)
        s.setParent(None)

    def show_page(self, page: int):
        """The Trim & speed (0), Effects (1) or Equalizer (2) page, in view."""
        if not self.wide and 0 <= page < self.tabs.count():
            self.tabs.setCurrentIndex(page)

    # ------------------------------------------------------------------ waveform
    def _zoom(self, factor: float | None):
        wave = self.d.effects.trim.wave
        wave.fit() if factor is None else wave.zoom(factor)

    def _show_fades(self, *_a):
        fi, fo = self.d.fades()
        self.d.effects.trim.wave.set_fades(fi, fo)

    def _fetch_fine(self):
        """The waveform's fine peaks, read on a worker (a big file's cache is slow)."""
        self._gen += 1
        gen, meta = self._gen, self.d.meta

        def work():
            try:
                peaks = original_peaks(meta, FINE_PEAKS)[0]
            except Exception:  # noqa: BLE001 - no cache yet: it keeps the coarse ones
                peaks = None
            busy.emit(self.fine_read, gen, peaks)
        threading.Thread(target=work, daemon=True, name="edit-waveform-fine").start()

    def _on_fine(self, gen: int, peaks):
        if gen == self._gen and peaks is not None and len(peaks):
            self.d.effects.trim.wave.set_fine(np.asarray(peaks, np.float32))

    # ------------------------------------------------------------------ effects
    def _pick_effect(self):
        if self.picker is None:
            self.picker = EffectPicker(self.d.effects, self, self._show_effect)
        self.picker.show_under(self.d.effects.add_effect)

    def _show_effect(self, etype: str):
        """Scroll the Effects column (or tab) to the card just turned on."""
        row = self.d.effects.rows.get(etype)
        lay = self.d.effects.fx_page.layout()
        if row is not None and lay is not None and len(self._scrolls) > 1:
            lay.activate()   # (where the card is now, before scrolling to it)
            self._scrolls[1].ensureWidgetVisible(row, 0, 12)
