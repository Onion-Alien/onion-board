"""Picking several pads at once (Ctrl+click, Shift+click, Ctrl+A) and changing them
together: remove (one Undo brings them all back), colour, volume, fades, categories.

A pick is separate from the sound shown in the transport bar (MainWindow.current):
clicking a pad still plays it, and the pick stays until Esc, the bar's ✕, or the
picked pads are filtered out of view."""
from __future__ import annotations

import html
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QInputDialog, QLabel, QMenu, QPushButton,
                               QWidget)

from soundboard.library import MAX_FADE_S, PAD_COLORS, SoundMeta
from soundboard.ui import icons
from soundboard.i18n import _, ngettext

if TYPE_CHECKING:
    from soundboard.ui.mainwindow import MainWindow


def swatch(color: str, size: int = 14) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(1, 1, size - 2, size - 2)
    p.end()
    return QIcon(pm)


def count(n: int) -> str:
    """"1 sound" / "3 sounds"."""
    return ngettext("{n} sound", "{n} sounds", n)


class PadSelection(QObject):
    """The picked pads of `mw`'s grid, and the "3 selected · …" bar under it."""

    def __init__(self, mw: MainWindow, keys_on: QWidget):
        super().__init__(mw)
        self.mw = mw
        self.picked: set[str] = set()
        self.anchor: str | None = None      # where a Shift+click range starts
        self.bar = self._build_bar()
        for seq, fn in ((QKeySequence.SelectAll, self.select_all),
                        (QKeySequence(Qt.Key_Escape), self.clear),
                        (QKeySequence.Delete, self._delete_key)):
            sc = QShortcut(seq, keys_on)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)

    # ------------------------------------------------------------------ the bar
    def _build_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("chip")
        h = QHBoxLayout(bar)
        h.setContentsMargins(10, 4, 4, 4)
        h.setSpacing(6)
        self.lbl = QLabel()
        h.addWidget(self.lbl, 1)
        for text, tip, fn in (
                (_("Colour"), _("Give every picked pad the same colour"), self._color_menu),
                (_("Volume…"), _("Set every picked sound's volume"), self.ask_volume),
                (_("Fades…"), _("Set every picked sound's fade in / fade out"),
                 self.ask_fades),
                (_("Categories"), _("Put the picked sounds in a category, or take them out"),
                 self._cats_menu)):
            b = QPushButton(text)
            b.setObjectName("small")
            b.setToolTip(tip)
            b.clicked.connect(lambda __=False, b=b, fn=fn: fn(b))
            h.addWidget(b)
        rm = QPushButton(_("Remove"))
        rm.setObjectName("small")
        rm.setToolTip(_("Remove the picked sounds (Undo brings them back)"))
        icons.set_icon(rm, "trash", "danger_text", size=12)
        rm.clicked.connect(self.delete)
        h.addWidget(rm)
        x = QPushButton()
        x.setObjectName("chipstop")
        x.setToolTip(_("Clear the selection (Esc)"))
        x.setAccessibleName(_("Clear the selection"))
        x.setFixedSize(24, 24)
        icons.set_icon(x, "stop", size=10)
        x.clicked.connect(self.clear)
        h.addWidget(x)
        bar.hide()
        return bar

    def _refresh(self):
        n = len(self.picked)
        self.lbl.setText(_("{count} selected · Ctrl+click adds or removes one, Shift+click a "
                           "range", count=count(n)))
        self.bar.setVisible(n > 0)
        for sid, pad in self.mw.pads.items():
            on = sid in self.picked
            if pad.picked != on:
                pad.set_picked(on)

    # ------------------------------------------------------------------ picking
    def visible_order(self) -> list[str]:
        return [p.meta.id for p in self.mw.grid.pads if not p.property("filtered")]

    def sounds(self) -> list[SoundMeta]:
        """The picked sounds, in board order."""
        return [m for m in self.mw.cfg.sounds if m.id in self.picked]

    def on_pick(self, sid: str, shift: bool):
        """A Ctrl+click (toggle one) or Shift+click (the range from the last pick)."""
        order = self.visible_order()
        if shift and self.anchor in order and sid in order:
            a, b = sorted((order.index(self.anchor), order.index(sid)))
            self.picked |= set(order[a:b + 1])
        else:
            if sid in self.picked:
                self.picked.discard(sid)
            else:
                self.picked.add(sid)
            self.anchor = sid
        self._refresh()

    def select_all(self):
        self.picked = set(self.visible_order())
        self._refresh()

    def clear(self, *__):
        if self.picked:
            self.picked.clear()
            self.anchor = None
            self._refresh()

    def sync(self):
        """Forget picks that were removed or filtered out of view."""
        keep = set(self.visible_order())
        if self.picked - keep:
            self.picked &= keep
            self._refresh()

    # ------------------------------------------------------------------ actions
    def menu(self, pos):
        """Right-click on a picked pad: the actions for all of them."""
        n = len(self.picked)
        m = QMenu(self.mw)
        m.addSection(count(n))
        self._fill_colors(m.addMenu(swatch(PAD_COLORS[0]), _("Colour")))
        m.addAction(icons.icon("volume"), _("Volume…"), self.ask_volume)
        m.addAction(_("Fade in / out…"), self.ask_fades)
        self._fill_cats(m.addMenu(_("Categories")))
        m.addAction(icons.icon("folder"), _("Export…"),
                    lambda: self.mw.export_sounds(
                        self.sounds(), count(n)))
        m.addSeparator()
        m.addAction(_("Clear selection"), self.clear)
        m.addAction(icons.icon("trash", "danger_text"), _("Remove {count}",
                                                          count=count(n)), self.delete)
        m.exec(pos)

    def _popup(self, button: QPushButton, fill):
        m = QMenu(self.mw)
        fill(m)
        m.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def _color_menu(self, button):
        self._popup(button, self._fill_colors)

    def _cats_menu(self, button):
        self._popup(button, self._fill_cats)

    def _fill_colors(self, menu: QMenu):
        for c in PAD_COLORS:
            menu.addAction(swatch(c), c, lambda c=c: self.set_color(c))

    def _fill_cats(self, menu: QMenu):
        sounds = self.sounds()
        for c in self.mw.cfg.categories:
            have = sum(1 for m in sounds if c in m.tags)
            a = menu.addAction(c.replace("&", "&&"))   # a lone & is a shortcut marker
            a.setCheckable(True)
            a.setChecked(have == len(sounds) and have > 0)
            # all of them in it: takes them out; otherwise puts them all in
            a.triggered.connect(lambda __=False, c=c, out=have == len(sounds):
                                self.set_category(c, not out))
        if self.mw.cfg.categories:
            menu.addSeparator()
        menu.addAction(icons.icon("plus"), _("New category…"), self.new_category)

    def _changed(self, sids=None):
        for sid in sids or self.picked:
            if sid in self.mw.pads:
                self.mw.pads[sid].update()
        self.mw.cfg.save()

    def _said(self, what: str):
        """Volume and fades don't show on the pads: say the change happened."""
        n = len(self.sounds())
        self.mw.toast(_("{what} on {count}", what=what, count=count(n)), "ok")

    def set_color(self, color: str):
        for m in self.sounds():
            m.color = color
        self._changed()

    def set_volume(self, volume: float):
        volume = min(max(volume, 0.0), 2.0)
        for m in self.sounds():
            m.volume = volume
            self.mw.engine.set_gain(m.id, self.mw.gain_for(m))
        self._changed()
        self._said(_("✓ Volume {pct}%", pct=round(volume * 100)))

    def ask_volume(self, *__):
        sounds = self.sounds()
        if not sounds:
            return
        vols = {round(m.volume * 100) for m in sounds}
        start = vols.pop() if len(vols) == 1 else 100
        v, ok = QInputDialog.getInt(self.mw, _("Volume"), _("Volume for {count} (%):",
                                                         count=count(len(sounds))),
                                    start, 0, 200, 5)
        if ok:
            self.set_volume(v / 100)

    def set_fades(self, fade_in: float | None, fade_out: float | None):
        for m in self.sounds():
            if fade_in is not None:
                m.fade_in = min(max(fade_in, 0.0), MAX_FADE_S)
            if fade_out is not None:
                m.fade_out = min(max(fade_out, 0.0), MAX_FADE_S)
        self._changed()
        self._said(_("✓ Fades set"))

    def ask_fades(self, *__):
        sounds = self.sounds()
        if not sounds:
            return
        got = []
        for label, attr in ((_("Fade in"), "fade_in"), (_("Fade out"), "fade_out")):
            vals = {getattr(m, attr) for m in sounds}
            v, ok = QInputDialog.getDouble(
                self.mw, label, _("{label} for {count} (seconds, 0 = off):",
                                  label=label, count=count(len(sounds))),
                vals.pop() if len(vals) == 1 else 0.0, 0.0, MAX_FADE_S, 1)
            if not ok:
                return
            got.append(v)
        self.set_fades(*got)

    def set_category(self, name: str, on: bool):
        if name not in self.mw.cfg.categories:
            return
        for m in self.sounds():
            if on and name not in m.tags:
                m.tags.append(name)
            elif not on and name in m.tags:
                m.tags.remove(name)
        n = len(self.sounds())
        self.mw._save_now()
        self.mw._fill_categories()
        self.mw.apply_filter(self.mw.search.text())
        self.mw.toast(_("✓ Added {count} to {name}", count=count(n), name=html.escape(name)) if on
                      else _("Took {count} out of {name}", count=count(n), name=html.escape(name)))

    def new_category(self, *__):
        keep = set(self.picked)   # the new, empty category shows: that unpicks them
        name = self.mw.new_category()
        if not name:
            return
        self.picked = keep & {m.id for m in self.mw.cfg.sounds}
        self.set_category(name, True)
        self._refresh()

    def delete(self, *__):
        sids = [m.id for m in self.sounds()]
        if not sids or not self.mw.ask_remove(sids):
            return
        self.picked.clear()
        self.anchor = None
        self._refresh()

    def _delete_key(self):
        if self.picked:
            self.delete()
