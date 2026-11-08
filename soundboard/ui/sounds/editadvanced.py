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
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QGraphicsDropShadowEffect,
                               QGridLayout,
                               QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QScrollArea, QSizePolicy,
                               QTabBar, QVBoxLayout, QWidget)

from soundboard import voicefx
from soundboard.audio import soundfx
from soundboard.i18n import _
from soundboard.sounds.library import original_peaks
from soundboard.ui.kit import busy, icons, theme
from soundboard.ui.kit.layouts import take_out
from soundboard.ui.kit.modalframe import SHADOW, ModalFrame
from soundboard.ui.kit.panel import card, hint_label, section_label
from soundboard.ui.sounds.splicepanel import SpliceBar
from soundboard.ui.sounds.trim import line_tip
from soundboard.ui.voice.effectrow import ADDON_GROUP, FX_ICONS, GROUPS

if TYPE_CHECKING:
    from soundboard.ui.sounds.dialogs import EditDialog

WIDE_PX = 1180      # from this wide, three columns (when they fit: fits()); narrower, tabs
FINE_PEAKS = 2400   # the big waveform's peaks: enough to zoom in sixteen times
PICKER_COLS = 3
BUTTON_GROW = 2      # px: the editor's button row, a touch bigger than plain buttons
EQ_TOP = 5           # px: see attach()
EDITOR_ROOM = 330    # px: the waveform's card when the screen has room (EditDialog)
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
        self.setObjectName("modeswitch")   # (themesheet: one track, the picked side lit)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
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


class EffectPicker(QWidget):
    """Add effect: every effect in its group as a tile (its icon, name, and what it does
    as the tooltip), a search box over them, on the shared card frame (a soft shadow,
    its edge, a ✕). The ones on are ticked; a click turns one on (or off again). Closes
    on a click outside, Esc or the ✕."""

    def __init__(self, effects, parent: QWidget, added=None):
        """`added(etype)`: one was turned on (the list brings it into view)."""
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.effects = effects
        self.added = added
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW, SHADOW // 2, SHADOW, SHADOW + 4)   # shadow falls down
        self.frame = ModalFrame(_("Add effect"), mascot="")
        self.frame.setMinimumWidth(460)
        self.frame.close_btn.clicked.connect(self.close)
        self.shadow = QGraphicsDropShadowEffect(self.frame)
        self.shadow.setBlurRadius(32)
        self.shadow.setOffset(0, 6)
        self.frame.setGraphicsEffect(self.shadow)
        outer.addWidget(self.frame)
        v = self.frame.body
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
            box.setObjectName("modalpoint")   # (see-through on the frame)
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
        self._fit()

    def _fit(self):
        """As tall as what's shown now, its top where it was (a search hides tiles:
        without this the frame kept its height and the header slid down its middle)."""
        # the tile grids, then the frame, then this redo their layouts one posted event
        # after another: done now, so the size below is for what's shown now
        for _pass in range(4):
            QApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
        self.resize(self.width(), self.sizeHint().height())

    def show_under(self, anchor: QWidget):
        self.shadow.setColor(QColor(0, 0, 0, 60 if theme.is_light() else 150))   # (the theme now)
        self.sync()
        self.search.clear()
        self.adjustSize()
        self._fit()
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
        self._pinned = None   # the window's size when the waveform's height was pinned
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
        self.btn_out, self.btn_in = QPushButton(), QPushButton()
        self.btn_fit = QPushButton()
        icons.set_icon(self.btn_out, "minus")   # (drawn: a typed + and - sat off centre)
        icons.set_icon(self.btn_in, "plus")
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
        self._bar_words = [(b, b.text()) for b in (self.btn_play, self.btn_undo,
                                                   self.btn_redo, self.splices.cut)]
        self.splices.installEventFilter(self)
        self.editor.installEventFilter(self)
        for b in (self.btn_play, self.btn_undo, self.btn_redo, self.splices.cut,
                  self.splices.list, *self.splices.fades.values(), self.btn_out,
                  self.btn_in, self.btn_fit):
            b.setProperty("roomier", True)   # a touch bigger (the theme: 1 px more padding)
            b.style().unpolish(b)   # (already styled once: its size was asked for)
            b.style().polish(b)
        for b in (self.btn_out, self.btn_in, self.btn_fit):
            b.setFixedWidth(36 + BUTTON_GROW)
        self.trim_box = QVBoxLayout()
        self.trim_box.setContentsMargins(0, 0, 0, 0)
        ev.addLayout(self.trim_box, 1)
        ev.addWidget(hint_label(line_tip()))   # (the hatching shows what's cut)
        v.addWidget(self.editor, 5)

        # a splice clicked: the columns under it are that splice's own now (EffectsPanel)
        self.part_bar = QFrame()
        self.part_bar.setObjectName("partbar")
        pb = QHBoxLayout(self.part_bar)
        pb.setContentsMargins(12, 6, 6, 6)
        pb.setSpacing(10)
        self.part_icon = QLabel()
        pb.addWidget(self.part_icon)
        self.part_text = QLabel()
        self.part_text.setWordWrap(True)
        self.part_text.setToolTip(_("They're heard whenever the sound plays through this "
                                    "splice, and in its own Play now, Save as new pad and "
                                    "Copy (right-click it)"))
        pb.addWidget(self.part_text, 1)
        self.part_whole = QPushButton(_("Back to the whole sound"))
        self.part_whole.setToolTip(_("The settings below change the whole sound again (Esc "
                                     "on the waveform does it too)"))
        self.part_whole.clicked.connect(lambda: self.d.effects.trim.wave.pick(None))
        pb.addWidget(self.part_whole)
        self.part_bar.hide()
        v.addWidget(self.part_bar)
        eff.part_picked.connect(self._show_part)
        self._hook_part_times()

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

        # under the editor: three columns, or (narrow) tabs over one of them. The pages
        # stay in their columns either way: moving one restyles every control on it
        # (0.15 s on a fast PC, so a resize across the line froze a slow one for seconds)
        self.cols = QWidget()
        ch = self._cols_lay = QHBoxLayout(self.cols)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.setSpacing(12)
        self.col_cards, self.col_boxes = [], []
        titles = (_("Speed & loudness"), _("Effects"), _("Equalizer"))
        for title, stretch in zip(titles, (12, 13, 11)):
            c, cv = card(title)
            cv.setContentsMargins(14, 16, 4, 8)   # the page's scroll bar at the edge
            ch.addWidget(c, stretch)
            self.col_cards.append(c)
            self.col_boxes.append(cv)
        self.tabs = QTabBar()
        self.tabs.setDocumentMode(True)
        self.tabs.setExpanding(False)
        for title in titles:
            self.tabs.addTab(title.replace("&", "&&"))
        self.tabs.currentChanged.connect(lambda _i: self._show_cols())
        self.tabs.hide()
        under = QWidget()   # (the tabs close over their card, as a tab page was)
        ul = QVBoxLayout(under)
        ul.setContentsMargins(0, 0, 0, 0)
        ul.setSpacing(4)
        ul.addWidget(self.tabs)
        ul.addWidget(self.cols, 1)
        v.addWidget(under, 6)
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
        self.d._show_line()
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

    def _hook_part_times(self):
        """The banner's times follow the picked splice's edges as they're dragged."""
        wave = self.d.effects.trim.wave
        wave.spliced.connect(lambda: self._show_part(self.d.effects.part))

    def retrim(self):
        """set_sound made a new trim for another sound: it's already where the old one
        was; make it big and get its peaks."""
        eff = self.d.effects
        self._hook_part_times()
        self.splices.attach(eff.trim)
        if eff.trim_layout is self.trim_box:
            eff.trim.set_big(True)
            self._fetch_fine()

    def set_wide(self, wide: bool):
        if wide != self.wide:
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
            if ((obj is self.splices and e.type() == QEvent.Type.LayoutRequest)
                    or (obj is self.editor and e.type() == QEvent.Type.Resize)):
                self._fit_bar()   # (narrower, or a splice's Fade in / Fade out shown)
                return False
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

    def _fit_bar(self):
        """Preview, Undo, Redo and Add splices as their icons alone when the editor's
        button row doesn't fit with their words (their tooltips still say them)."""
        words = self._bar_words
        short = not words[0][0].text()
        need = self.bar.sizeHint().width()
        if short:   # what it needs with the words back
            need += sum(b.fontMetrics().horizontalAdvance(t) + 8 for b, t in words)
        lay = self.editor.layout()
        m = lay.contentsMargins() if lay is not None else None
        room = self.editor.width() - (m.left() + m.right() if m is not None else 0)
        if (need > room) != short:
            for b, t in words:
                b.setText("" if need > room else t)

    def _page_need(self, i: int) -> int:
        """How tall column `i`'s page is whole. Effects without the effects turned on:
        with them it grows long and scrolls, and the waveform shouldn't jump with each
        one (its knobs, presets and Add effect are counted: they scrolled too)."""
        s = self._scrolls[i]
        page = s.widget()
        if page is None:
            return 0
        h = page.minimumSizeHint().height()
        if page.hasHeightForWidth():
            h = max(h, page.heightForWidth(s.viewport().width()))
        if i == 1:
            lay = page.layout()
            gap = lay.spacing() if lay is not None else 0
            h -= sum(r.minimumSizeHint().height() + gap
                     for r in self.d.effects.rows.values() if not r.isHidden())
        return h

    def _banner_room(self) -> int:
        """How much height the splice banner takes, at this width (its text wraps)."""
        lay = self.layout()
        h = self.part_bar.heightForWidth(self.width())
        return (h if h >= 0 else self.part_bar.sizeHint().height()) + (
            lay.spacing() if lay is not None else 0)

    def _fit_cols(self):
        """The columns tall enough for their pages whole: the waveform gives up the
        room first, down to its floor (split by stretch alone, a 1320 x 880 window
        scrolled the equalizer for its last lines). Past that, a floor under the shown
        columns: a window too short for them scrolls as one page (EditDialog's
        adv_scroll), not each column for its last line or two. The room still missing
        when it opens, the window grows by (EditDialog)."""
        for i, s in enumerate(self._scrolls):
            if not self.col_cards[i].isHidden() and s.widget() is not None:   # (shown ones)
                h = self._page_need(i) + 2 * s.frameWidth()
                if s.minimumHeight() != h:
                    s.setMinimumHeight(h)
        lay = self.layout()
        if lay is not None:   # the banner's room, shown or not: it never brings the page's
            # scroll bar, which would narrow the waveform on that click
            room = self._banner_room() if self.part_bar.isHidden() else 0
            h = lay.minimumSize().height() + room
            if self.minimumHeight() != h:
                self.setMinimumHeight(h)
        if self._pinned is not None:
            if self._pinned == self.d.size():
                return
            self._pinned = None
            self.editor.setMinimumHeight(0)
            self.editor.setMaximumHeight(QWIDGETSIZE_MAX)
        top = self.editor.maximumHeight()
        if not self.wide or len(self._scrolls) < 3 or not self.cols.isVisible():
            if top != QWIDGETSIZE_MAX:
                self.editor.setMaximumHeight(QWIDGETSIZE_MAX)
            return
        need = 0
        for i, s in enumerate(self._scrolls):
            if s.widget() is None or s.height() <= 0:
                continue
            chrome = self.cols.height() - s.height()   # the card's title and margins
            need = max(need, self._page_need(i) + 2 * s.frameWidth() + chrome)
        first = lay.itemAt(0) if lay is not None else None
        if lay is None or first is None:
            return
        both = self.height() - first.sizeHint().height() - 2 * lay.spacing()
        # the splice banner's room, shown or not: a click that selects or lets go of a
        # splice never resizes the waveform under the pointer (the columns take it up)
        both -= self._banner_room()
        cap = max(self.editor.minimumSizeHint().height(), both - need)
        if cap != top:
            self.editor.setMaximumHeight(cap)

    def _place(self):
        for box, s in zip(self.col_boxes, self._scrolls):
            if box.indexOf(s) < 0:   # (only on attach: set_wide never moves them)
                box.addWidget(s, 1)
                s.show()
        if not self.wide:
            self.tabs.setCurrentIndex(1)
        self._show_cols()

    def _show_cols(self):
        """Wide: the three columns, each with its title. Narrow: the tabs over the one
        picked (the tab says its title)."""
        cur = self.tabs.currentIndex()
        for i, (c, s) in enumerate(zip(self.col_cards, self._scrolls)):
            c.setVisible(self.wide or i == cur)
            if c.heading_title is not None:
                c.heading_title.setVisible(self.wide)
            # (no title to start level with under the tabs: not its room on top)
            self.col_boxes[i].setContentsMargins(14, 16 if self.wide else 8, 4, 8)
            s.setMinimumWidth(self._col_w(s) if self.wide else 0)
        self.tabs.setVisible(not self.wide)
        self._fit_cols()   # (the tab just picked: its own floor)

    def _unplace(self, s: QScrollArea):
        for box in self.col_boxes:
            j = box.indexOf(s)
            if j >= 0:
                take_out(box, j)
        s.setMinimumWidth(0)
        s.setMinimumHeight(0)
        s.setParent(self.d)   # (hidden, but freed with the window: EditDialog)

    def show_page(self, page: int):
        """The Trim & speed (0), Effects (1) or Equalizer (2) page, in view."""
        if not self.wide and 0 <= page < self.tabs.count():
            self.tabs.setCurrentIndex(page)

    # ------------------------------------------------------------------ waveform
    def _zoom(self, factor: float | None):
        wave = self.d.effects.trim.wave
        wave.fit() if factor is None else wave.zoom(factor)

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

    def _pin_editor(self, banner: bool):
        """The banner about to show or hide: the waveform stays exactly as tall, the
        columns under it take that up (it jumped under the pointer on every click that
        selected or let go of a splice). Till the window changes size (_fit_cols)."""
        if self.isVisible() and self.part_bar.isHidden() == banner:
            self.editor.setFixedHeight(self.editor.height())
            self._pinned = self.d.size()

    def _show_part(self, i):
        """The banner over the columns while splice `i` is picked (None: hidden)."""
        wave = self.d.effects.trim.wave
        if i is None or not 0 <= i < len(wave.splices):
            self._pin_editor(False)
            self.part_bar.hide()
            return
        self.part_icon.setPixmap(icons.pixmap("scissors", 16, icons.resolve("accent_hi")))
        a, b = wave.splices[i]
        self.part_text.setText(_(
            "<b>Splice {n}</b> ({start} to {end}): the settings below change only this "
            "part.", n=i + 1, start=soundfx.fmt_s(a), end=soundfx.fmt_s(b)))
        self._pin_editor(True)
        self.part_bar.show()

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
