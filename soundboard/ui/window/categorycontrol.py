"""Categories in the main window: the category tabs and their sub-category row, picking
one, adding / renaming / deleting / colouring them, a sound's categories (its tags),
and switching category by itself while a chosen program is in front (catswitch.py).

MainWindow makes one ``CategoryControl`` (``MainWindow.catctl``); everything here runs
on the UI thread."""
from __future__ import annotations

import html
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QInputDialog,
    QMenu,
    QMessageBox,
    QPushButton,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from soundboard.sounds import catswitch, library
from soundboard.core import usage
from soundboard.i18n import _, ngettext
from soundboard.sounds.library import SoundMeta
from soundboard.ui.kit.hotkeypick import pretty_key
from soundboard.ui.kit import icons
from soundboard.ui.kit.plaintext import plain_tip   # (names from backups and packs)
from soundboard.ui.window.controller import Controller
from soundboard.ui.sounds.padbatch import fill_colour_menu
from soundboard.ui.kit.panel import Flow
from soundboard.ui.kit.widgets import InlineNameBox

if TYPE_CHECKING:
    from soundboard.ui.window.mainwindow import MainWindow

ALL = _("All")       # the category tab that shows every sound


class SnugTabBar(QTabBar):
    """A tab bar no wider than its tabs. Qt's minimum keeps room for the scroll
    arrows even with one short tab, which left a wide gap before the "+" after it."""

    def minimumSizeHint(self) -> QSize:
        m = super().minimumSizeHint()
        return QSize(min(m.width(), self.sizeHint().width()), m.height())

    def childEvent(self, e):
        # A dragged tab is drawn twice: by the bar where it's being dragged to, and by
        # a picture of it Qt floats on top (a plain QWidget child). Our tabs have no
        # background, so the picture didn't hide the bar's copy: the name showed doubled.
        super().childEvent(e)
        w = e.child()
        if e.type() == QEvent.Type.ChildAdded and type(w) is QWidget:
            w.installEventFilter(self)

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Type.Paint and obj.parent() is self:
            return True   # the floating picture: the bar's own copy is enough
        return super().eventFilter(obj, e)


class CategoryControl(Controller):
    """The categories of one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)
        # Switch category when a program is in front: a cheap look at the window in
        # front each second, only while a rule exists (and runs while the board is hidden)
        self.cat_switch = catswitch.Switcher()
        self._cat_timer = QTimer(mw, interval=catswitch.POLL_MS)
        self._cat_timer.timeout.connect(self._cat_tick)

    # A sound can be in any number of categories (SoundMeta.tags); the bar above the
    # pads shows one at a time. The overlay shows the same category's sounds.
    def _build_categories(self) -> QWidget:
        # two layers: the window's fit hides the outer one when it's short, while web
        # results showing in the pads' place hide the inner row (its tabs pick pads)
        outer = QWidget()
        ov = QVBoxLayout(outer)
        ov.setContentsMargins(0, 0, 0, 0)
        w = self._cat_row = QWidget()
        ov.addWidget(w)
        # the chips under the tabs: the subcategories of the category showing
        self._sub_row = QWidget()
        sv = QVBoxLayout(self._sub_row)   # Flow ignores margins: this one holds them
        sv.setContentsMargins(0, 6, 0, 0)   # the left one: _fit_toolbar
        chips = QWidget()
        self._sub_flow = Flow(chips, 6)
        sv.addWidget(chips)
        self._sub_row.hide()
        ov.addWidget(self._sub_row)
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)   # the left one: _fit_toolbar
        h.setSpacing(4)
        self.cat_tabs = SnugTabBar()
        self.cat_tabs.setAccessibleName(_("Categories"))   # a Tab stop: arrows pick one
        self.cat_tabs.setDrawBase(False)
        self.cat_tabs.setExpanding(False)
        self.cat_tabs.setUsesScrollButtons(True)
        self.cat_tabs.setMovable(True)
        self.cat_tabs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.cat_tabs.customContextMenuRequested.connect(self._category_menu)
        self.cat_tabs.currentChanged.connect(self._on_category_tab)
        self.cat_tabs.tabMoved.connect(self._on_category_moved)
        h.addWidget(self.cat_tabs)
        # "+" right after the last tab, like a browser's new-tab button
        add = QPushButton()
        add.setObjectName("small")
        add.setAccessibleName(_("New category"))
        add.setToolTip(_("New category (a page of pads). Right-click a pad to put it in one; "
                         "right-click a category to rename or delete it."))
        icons.set_icon(add, "plus", size=12)
        # the box the name is typed into, right where the new tab will show
        box = self.cat_name_box = InlineNameBox(add, _("New category"))
        box.named.connect(lambda text: self.new_category(name=text))
        h.addWidget(box, 0, Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(add, 0, Qt.AlignmentFlag.AlignVCenter)
        h.addStretch(1)
        self.btn_cat_add = add
        self._fill_categories()
        return outer

    def _fill_subcategories(self):
        """The chips under the tabs: All, then each subcategory of the category showing,
        then a dashed "+ Subcategory". Only a category that has some shows the row."""
        mw = self.mw
        cfg = mw.cfg
        subs = cfg.subcategories.get(cfg.category, []) if cfg.category else []
        if cfg.subcategory not in subs:
            cfg.subcategory = ""
        flow = self._sub_flow
        while flow.count():
            it = flow.takeAt(0)
            if it is not None and it.widget() is not None:
                old = it.widget()   # hidden and let go of now: deleteLater alone leaves it
                old.hide()          # drawn (full size) until the event loop frees it
                old.setParent(None)
                old.deleteLater()
        self._sub_row.setVisible(bool(subs) and not self._cat_row.isHidden())
        if not subs:
            return
        cat = cfg.category
        if getattr(mw, "_toolbar_hold", None) is not None:
            mw.fitctl._fit_toolbar()   # its margins, before the first resize does

        def chip(text: str, tip: str):
            b = QPushButton(text.replace("&", "&&"))
            b.setObjectName("subchip")
            b.setCheckable(True)
            b.setToolTip(tip)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            flow.addWidget(b)
            return b

        total = sum(1 for m in cfg.sounds if cat in m.tags)
        b = chip(_("All {n}", n=total), "")
        b.setChecked(not cfg.subcategory)
        b.clicked.connect(lambda: self.set_subcategory(""))
        for sub in subs:
            n = sum(1 for m in cfg.sounds if library.sub_tag(cat, sub) in m.tags)
            b = chip(f"{sub} {n}", ngettext("{n} sound", "{n} sounds", n))
            b.setChecked(sub == cfg.subcategory)
            b.clicked.connect(lambda __=False, sub=sub: self.set_subcategory(sub))
            b.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            b.customContextMenuRequested.connect(
                lambda pos, sub=sub, b=b: self._subcategory_menu(sub, b.mapToGlobal(pos)))
        add = QPushButton(_("+ Subcategory"))
        add.setObjectName("subchip")
        add.setProperty("add", True)
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        # the name is typed where the new chip will show
        box = self.sub_name_box = InlineNameBox(add, _("New subcategory"), width=None)
        box.named.connect(lambda text: self.new_subcategory(cat, name=text))
        flow.addWidget(box)
        flow.addWidget(add)

    def set_subcategory(self, sub: str):
        """Show only one subcategory of the category showing ("" = all of it)."""
        mw = self.mw
        cfg = mw.cfg
        sub = sub if sub in cfg.subcategories.get(cfg.category, []) else ""
        if sub != cfg.subcategory:
            cfg.subcategory = sub
            mw.overlay.page = 0
            mw._save_later()
        self._fill_subcategories()
        mw.searchctl.apply_filter(mw.search.text())

    def new_subcategory(self, cat: str, sid: str | None = None, name: str | None = None) -> str:
        """Add a subcategory to `cat` (asking for its name unless given), with `sid`'s
        sound in it when made from a pad's menu. Returns the name, or "" if cancelled."""
        mw = self.mw
        if cat not in mw.cfg.categories:
            return ""
        if name is None:
            name, ok = QInputDialog.getText(mw, _("New subcategory"),
                                            _("Name (a group inside {cat}):", cat=cat))
            name = name if ok else None
        name, cut = self._typed_name(name)
        if not name:
            return ""
        if name.lower() == cat.lower():   # "Memes › Memes" said nothing new
            mw.toast(_("There's already a “{new}”.", new=html.escape(cat)), "warn")
            return ""
        subs: list[str] = mw.cfg.subcategories.setdefault(cat, [])
        name = {x.lower(): x for x in subs}.get(name.lower(), name)
        if name in subs:
            if not sid:   # as new_category: it goes there, and says so
                mw.toast(_("There's already a “{new}”.", new=html.escape(name)), "warn")
        else:
            subs.append(name)
        if sid and mw.meta(sid):
            self.toggle_tag(sid, library.sub_tag(cat, name), on=True)
        mw._save_now()
        self._fill_subcategories()
        if not sid:
            if mw.cfg.category != cat:
                self.set_category(cat)
            self.set_subcategory(name)
        if cut:
            self._say_cut(name)
        return name

    def rename_subcategory(self, sub: str, new: str | None = None):
        mw = self.mw
        cat = mw.cfg.category
        subs = mw.cfg.subcategories.get(cat, [])
        if sub not in subs:
            return
        if new is None:
            new, ok = QInputDialog.getText(mw, _("Rename subcategory"), _("New name:"),
                                           text=sub)
            new = new if ok else None
        new, cut = self._typed_name(new)
        if new == sub and cut:   # cut short to the name it has: say why nothing changed
            self._say_cut(new)
        if not new or new == sub:
            return
        if new.lower() in {x.lower() for x in subs if x != sub} | {cat.lower()}:
            mw.toast(_("There's already a “{new}”.", new=html.escape(new)), "warn")
            return
        old_tag, new_tag = library.sub_tag(cat, sub), library.sub_tag(cat, new)
        subs[subs.index(sub)] = new
        for m in mw.soundctl._live_metas():   # removed ones too, or Undo brings `old` back
            m.tags = [new_tag if t == old_tag else t for t in m.tags]
        if mw.cfg.subcategory == sub:
            mw.cfg.subcategory = new
        mw._save_now()
        self._fill_subcategories()
        self._say_renamed(new, cut)

    def delete_subcategory(self, sub: str):
        """Delete a subcategory. Its sounds stay in the category."""
        mw = self.mw
        cat = mw.cfg.category
        subs = mw.cfg.subcategories.get(cat, [])
        if sub not in subs:
            return
        tag = library.sub_tag(cat, sub)
        n = sum(tag in m.tags for m in mw.cfg.sounds)
        if n and QMessageBox.question(
                mw, _("Delete subcategory"),
                plain_tip(ngettext("Delete the “{name}” subcategory? Its {n} sound stay in "
                                   "{cat}.",
                                   "Delete the “{name}” subcategory? Its {n} sounds stay in "
                                   "{cat}.", n, name=sub, cat=cat))
                ) != QMessageBox.StandardButton.Yes:
            return
        subs.remove(sub)
        if not subs:
            mw.cfg.subcategories.pop(cat, None)
        for m in mw.soundctl._live_metas():
            if tag in m.tags:
                m.tags.remove(tag)
        if mw.cfg.subcategory == sub:
            mw.cfg.subcategory = ""
        mw._save_now()
        self._fill_subcategories()
        mw.searchctl.apply_filter(mw.search.text())

    def _subcategory_menu(self, sub: str, pos):
        mw = self.mw
        menu = QMenu(mw)
        a_ren = menu.addAction(icons.icon("edit"), _("Rename"))
        a_del = menu.addAction(icons.icon("trash", "danger_text"),
                               _("Delete subcategory (keeps the sounds)"))
        act = menu.exec(pos)
        menu.deleteLater()
        if act == a_ren:
            self.rename_subcategory(sub)
        elif act == a_del:
            self.delete_subcategory(sub)

    def _fill_categories(self):
        mw = self.mw
        tb = self.cat_tabs
        tb.blockSignals(True)
        while tb.count():
            tb.removeTab(0)
        tb.addTab(ALL)
        hidden = [c for c in mw.cfg.categories if c in mw.cfg.hidden_from_all]
        tb.setTabToolTip(0, _("Every sound except those in: {names} (right-click one of "
                              "them, Advanced, to show it here again)",
                              names=", ".join(hidden)) if hidden else "")
        for c in mw.cfg.categories:
            n = sum(1 for m in mw.cfg.sounds if c in m.tags)
            i = tb.addTab(c.replace("&", "&&"))   # a lone & would be a shortcut key
            tb.setTabData(i, c)                   # the real name; All's data stays None
            col = mw.cfg.category_colors.get(c)
            tb.setTabIcon(i, self._dot_icon(col) if col else QIcon())
            hk = mw.cfg.category_hotkeys.get(c)
            progs = catswitch.programs_for(mw.cfg.category_programs, c)
            tb.setTabToolTip(i, ngettext("{n} sound", "{n} sounds", n)
                             + (_(" · {hk} plays a random one", hk=pretty_key(hk)) if hk else "")
                             + (_(" · shows by itself when {progs} is in front",
                                  progs=', '.join(progs))
                                if progs else "")
                             + (_(" · hidden from All") if c in mw.cfg.hidden_from_all
                                else "")
                             + _(" · right-click to rename, delete or give it a random-sound "
                                 "hotkey · drag to reorder"))
        cat = mw.cfg.category
        tb.setCurrentIndex(mw.cfg.categories.index(cat) + 1 if cat in mw.cfg.categories
                           else 0)
        tb.blockSignals(False)
        self._fill_subcategories()

    @staticmethod
    def _dot_icon(color: str) -> QIcon:
        """A category's colour on its tab: a round dot."""
        app = QApplication.instance()
        dpr = app.devicePixelRatio() if isinstance(app, QApplication) else 1.0
        pm = QPixmap(round(12 * dpr), round(12 * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        p.drawEllipse(1, 1, 10, 10)
        p.end()
        return QIcon(pm)

    def set_category_color(self, name: str, color: str):
        """A category's colour on its tab and the overlay ("" takes it off)."""
        mw = self.mw
        if color:
            mw.cfg.category_colors[name] = color
        else:
            mw.cfg.category_colors.pop(name, None)
        mw._save_now()
        self._fill_categories()
        if getattr(mw, "overlay", None) is not None:
            mw.overlay.sounds_changed()

    def _on_category_tab(self, i: int):
        mw = self.mw
        self.set_category(mw.cfg.categories[i - 1] if 1 <= i <= len(mw.cfg.categories)
                          else "")

    def _on_category_moved(self, _frm: int, _to: int):
        mw = self.mw
        if self.cat_tabs.tabData(0) is not None:   # All was dragged away from the front
            self._fill_categories()
            return
        names = [self.cat_tabs.tabData(i) for i in range(1, self.cat_tabs.count())]
        if sorted(names) == sorted(mw.cfg.categories):
            mw.cfg.categories = names
            mw._save_later()

    def set_category(self, name: str):
        """Show one category's pads ("" = all of them). The overlay follows."""
        mw = self.mw
        name = name if name in mw.cfg.categories else ""
        changed = name != mw.cfg.category
        mw.cfg.category = name
        if changed:
            mw.cfg.subcategory = ""
            self._fill_subcategories()
        want = mw.cfg.categories.index(name) + 1 if name else 0
        if self.cat_tabs.currentIndex() != want:
            self.cat_tabs.blockSignals(True)
            self.cat_tabs.setCurrentIndex(want)
            self.cat_tabs.blockSignals(False)
        if changed:
            mw.overlay.page = 0
            # a sound picked on the last tab and not playing: off the player, so Space
            # on this tab doesn't play it (one that's playing stays, Space pauses it)
            if mw.current and not mw.engine.state(mw.current):
                mw.playctl.deselect()
            mw.searchctl.apply_filter(mw.search.text())
            mw._save_later()
            if mw.cfg.scoped_hotkeys:   # this category's set of sound hotkeys
                mw.hkctl.register_hotkeys()

    def category_sounds(self) -> list[SoundMeta]:
        mw = self.mw
        return [m for m in mw.cfg.sounds
                if library.in_view(m.tags, mw.cfg.category, mw.cfg.subcategory,
                                   mw.cfg.hidden_from_all)]

    def new_category(self, sid: str | None = None, name: str | None = None) -> str:
        """Add a category (asking for its name unless given), with `sid`'s sound in it
        when made from a pad's menu. Returns the name, or "" if cancelled."""
        mw = self.mw
        if name is None:
            name, ok = QInputDialog.getText(mw, _("New category"),
                                            _("Name (e.g. Memes, Music, Game 1):"))
            name = name if ok else None
        name, cut = self._typed_name(name)
        if name.lower() == ALL.lower():   # would look like the built-in tab
            mw.toast(_("“{all}” is the built-in tab, pick another name", all=ALL), "warn")
            return ""
        if not name:
            return ""
        name = {c.lower(): c for c in mw.cfg.categories}.get(name.lower(), name)
        if name in mw.cfg.categories:
            if not sid:   # the + box: it goes to that tab, and says why nothing new showed
                mw.toast(_("There's already a “{new}”.", new=html.escape(name)), "warn")
        else:
            mw.cfg.categories.append(name)
        m = mw.meta(sid) if sid else None
        if m and name not in m.tags:
            m.tags.append(name)
            if mw.cfg.scoped_hotkeys:   # its key now works only in its categories
                mw.hkctl.register_hotkeys()
        mw._save_now()
        self._fill_categories()
        if not sid:
            self.set_category(name)
        mw.searchctl.apply_filter(mw.search.text())
        if cut:
            self._say_cut(name)
        return name

    def _typed_name(self, typed: str | None) -> tuple[str, bool]:
        """A name typed in a New / Rename box (None: the box was cancelled), cleaned
        by `library.plain_name`, and whether it had to be cut short. A box left empty,
        or with only spaces in it, says so rather than doing nothing."""
        if typed is None:
            return "", False
        name = library.plain_name(typed)
        if not name:
            self.mw.toast(_("Type a name first."), "warn")
            return "", False
        return name, len(library.one_line(typed)) > len(name)

    def _say_cut(self, name: str):
        self.mw.toast(_("Names can be up to {n} characters, so it's “{name}”.",
                        n=library.CATEGORY_MAX, name=html.escape(name)), "warn")

    def _say_renamed(self, new: str, cut: bool):
        if cut:
            self._say_cut(new)
        else:
            self.mw.toast(_("✓ Renamed to “{new}”", new=html.escape(new)), "ok")

    @staticmethod
    def _retag(tag: str, old: str, new: str) -> str:
        """`tag` with category `old` renamed to `new` ("Old / Sub" follows)."""
        cat, sub = library.split_tag(tag)
        if cat != old:
            return tag
        return library.sub_tag(new, sub) if sub else new

    def toggle_tag(self, sid: str, name: str, on: bool | None = None):
        """Put the sound in a category, or in a "Cat / Sub" subcategory (which puts it
        in Cat too), or take it out; `on` says which way, None flips it."""
        mw = self.mw
        m = mw.meta(sid)
        cat, sub = library.split_tag(name)
        if not m or cat not in mw.cfg.categories or (
                sub and sub not in mw.cfg.subcategories.get(cat, [])):
            return
        if on is None:
            on = name not in m.tags
        shown = f"{cat} › {sub}" if sub else cat
        if on:
            for t in (cat, name):
                if t not in m.tags:
                    m.tags.append(t)
            msg = _("✓ Added “{name}” to {category}",
                    name=html.escape(m.name), category=html.escape(shown))
        else:
            # out of a category is out of its subcategories too; out of a subcategory
            # leaves it in the category
            m.tags = [t for t in m.tags
                      if t != name and (sub or library.split_tag(t)[0] != cat)]
            msg = _("Took “{name}” out of {category}",
                    name=html.escape(m.name), category=html.escape(shown))
        if mw.cfg.scoped_hotkeys:   # where its key works changed with its categories
            mw.hkctl.register_hotkeys()
        mw._save_now()
        self._fill_categories()
        mw.searchctl.apply_filter(mw.search.text())
        mw.toast(msg)

    def rename_category(self, old: str, new: str | None = None):
        mw = self.mw
        if new is None:
            new, ok = QInputDialog.getText(mw, _("Rename category"), _("New name:"), text=old)
            new = new if ok else None
        new, cut = self._typed_name(new)
        if new.lower() == ALL.lower():
            mw.toast(_("“{all}” is the built-in tab, pick another name", all=ALL), "warn")
            return
        if new == old and cut:   # cut short to the name it has: say why nothing changed
            self._say_cut(new)
        if not new or new == old or old not in mw.cfg.categories:
            return
        if new.lower() in {c.lower() for c in mw.cfg.categories if c != old}:
            mw.toast(_("There's already a “{new}”.", new=html.escape(new)), "warn")
            return
        mw.cfg.categories[mw.cfg.categories.index(old)] = new
        if old in mw.cfg.category_hotkeys:
            mw.cfg.category_hotkeys[new] = mw.cfg.category_hotkeys.pop(old)
        if old in mw.cfg.category_colors:
            mw.cfg.category_colors[new] = mw.cfg.category_colors.pop(old)
        for exe, cat in mw.cfg.category_programs.items():   # its programs come along
            if cat == old:
                mw.cfg.category_programs[exe] = new
        if self.cat_switch.shown == old:
            self.cat_switch.shown = new
        if self.cat_switch.before == old:
            self.cat_switch.before = new
        mw.playctl.shuffle.forget(old)
        if old in mw.cfg.subcategories:
            mw.cfg.subcategories[new] = mw.cfg.subcategories.pop(old)
        for m in mw.soundctl._live_metas():   # removed ones too, or Undo brings `old` back
            m.tags = [self._retag(t, old, new) for t in m.tags]
        if old in mw.cfg.hidden_from_all:
            mw.cfg.hidden_from_all[mw.cfg.hidden_from_all.index(old)] = new
        if mw.cfg.category == old:
            mw.cfg.category = new
        mw._save_now()
        self._fill_categories()
        mw.hkctl.register_hotkeys()   # its random-sound hotkey now plays `new`
        self._say_renamed(new, cut)

    def delete_category(self, name: str):
        """Delete a category. Its sounds stay (in All and their other categories)."""
        mw = self.mw
        if name not in mw.cfg.categories:
            return
        n = sum(name in m.tags for m in mw.cfg.sounds)
        if n and QMessageBox.question(
                mw, _("Delete category"),
                plain_tip(ngettext("Delete the “{name}” category? Its {n} sound stay in All "
                                   "(and any other categories they're in).",
                                   "Delete the “{name}” category? Its {n} sounds stay in All "
                                   "(and any other categories they're in).", n, name=name))
                ) != QMessageBox.StandardButton.Yes:
            return
        cfg = mw.cfg
        was = {   # for Undo: everything below takes from it
            "at": cfg.categories.index(name), "hotkey": cfg.category_hotkeys.get(name),
            "color": cfg.category_colors.get(name),
            "programs": {e: c for e, c in cfg.category_programs.items() if c == name},
            "subs": cfg.subcategories.get(name),
            "hidden": (cfg.hidden_from_all.index(name)
                       if name in cfg.hidden_from_all else None),
            "picked": (cfg.category, cfg.subcategory) if cfg.category == name else None,
            "tags": [(m, list(m.tags)) for m in mw.soundctl._live_metas()
                     if any(library.split_tag(t)[0] == name for t in m.tags)],
        }
        mw.cfg.categories.remove(name)
        mw.cfg.category_hotkeys.pop(name, None)
        mw.cfg.category_colors.pop(name, None)
        mw.cfg.category_programs = {exe: cat for exe, cat
                                      in mw.cfg.category_programs.items() if cat != name}
        self._update_cat_timer()
        mw.playctl.shuffle.forget(name)
        mw.cfg.subcategories.pop(name, None)
        if name in mw.cfg.hidden_from_all:   # its sounds are in All again
            mw.cfg.hidden_from_all.remove(name)
        for m in mw.soundctl._live_metas():   # removed ones too, or Undo brings it back
            m.tags = [t for t in m.tags if library.split_tag(t)[0] != name]
        if mw.cfg.category == name:
            mw.cfg.category = ""
            mw.cfg.subcategory = ""
        mw._save_now()
        self._fill_categories()
        mw.searchctl.apply_filter(mw.search.text())
        mw.hkctl.register_hotkeys()   # let go of its random-sound hotkey
        mw.toast(_("Deleted the “{name}” category. Its sounds are still in All.",
                   name=html.escape(name)), "ok", 8000, key="category-deleted",
                 action=(_("Undo"), lambda: self._undo_delete(name, was)))

    def _undo_delete(self, name: str, was: dict):
        """The delete's Undo: the category back where it was, with its sounds, hotkey,
        colour, programs and subcategories (unless one by that name was made since)."""
        mw = self.mw
        cfg = mw.cfg
        if name in cfg.categories:
            return
        usage.used("category-undo")
        cfg.categories.insert(min(was["at"], len(cfg.categories)), name)
        if was["hotkey"] and not mw.hkctl._hotkey_taken(was["hotkey"]):
            cfg.category_hotkeys[name] = was["hotkey"]
        if was["color"]:
            cfg.category_colors[name] = was["color"]
        for exe, cat in was["programs"].items():
            cfg.category_programs.setdefault(exe, cat)
        self._update_cat_timer()
        if was["subs"] is not None:
            cfg.subcategories[name] = was["subs"]
        if was["hidden"] is not None:
            cfg.hidden_from_all.insert(min(was["hidden"], len(cfg.hidden_from_all)), name)
        for m, tags in was["tags"]:   # (any tag added since stays)
            m.tags = tags + [t for t in m.tags if t not in tags]
        if was["picked"] and not cfg.category:
            cfg.category, cfg.subcategory = was["picked"]
        mw._save_now()
        self._fill_categories()
        mw.searchctl.apply_filter(mw.search.text())
        mw.hkctl.register_hotkeys()
        mw.toast(_("“{name}” is back.", name=html.escape(name)), "ok",
                 key="category-deleted")

    def _category_menu(self, pos):
        mw = self.mw
        i = self.cat_tabs.tabAt(pos)
        if i < 1:
            return
        name = self.cat_tabs.tabData(i)
        menu = QMenu(mw)
        a_ren = menu.addAction(icons.icon("edit"), _("Rename"))
        a_sub = menu.addAction(icons.icon("plus"), _("Add subcategory…"))
        a_rand = menu.addAction(icons.icon("play"), _("Play a random sound from it"))
        cm = menu.addMenu(icons.icon("palette"), _("Colour"))
        # the same colour list as the bulk Colour menu: names, the current one ticked
        fill_colour_menu(cm, mw.cfg.category_colors.get(name, ""),
                         lambda col: self.set_category_color(name, col), none=True)
        adv = menu.addMenu(icons.icon("sliders"), _("Advanced"))
        hidden = name in mw.cfg.hidden_from_all
        # an icon takes the tick's place, so the ticked one shows a tick icon instead
        a_hide = adv.addAction(icons.icon("check" if hidden else "eye", checked_color="accent"),
                               _("Hide its sounds from All"))
        a_hide.setCheckable(True)
        a_hide.setChecked(hidden)
        hk = mw.cfg.category_hotkeys.get(name, "")
        a_hk = adv.addAction(icons.icon("keyboard"),
                             _("Random-sound hotkey: {hk} (change…)", hk=pretty_key(hk)) if hk
                             else _("Set a random-sound hotkey"))
        a_nohk = adv.addAction(icons.icon("trash"),
                              _("Clear the random-sound hotkey")) if hk else None
        a_exp = adv.addAction(icons.icon("folder"), _("Export as a sound pack"))
        menu.addSeparator()
        a_del = menu.addAction(icons.icon("trash", "danger_text"),
                               _("Delete category (keeps the sounds)"))
        act = menu.exec(self.cat_tabs.mapToGlobal(pos))
        menu.deleteLater()   # its actions stay valid until this returns
        if act is None:
            return
        if act == a_ren:
            self.rename_category(name)
        elif act == a_sub:
            self.new_subcategory(name)
        elif act == a_hk:
            mw.hkctl.set_category_hotkey(name)
        elif act is not None and act == a_nohk:
            mw.hkctl.set_category_hotkey(name, "")
        elif act == a_hide:
            self.set_hidden_from_all(name, a_hide.isChecked())
        elif act == a_rand:
            mw.playctl.play_random(name)
        elif act == a_exp:
            mw.impctl.export_sounds([m for m in mw.cfg.sounds if name in m.tags], name)
        elif act == a_del:
            self.delete_category(name)

    def set_hidden_from_all(self, name: str, hide: bool):
        """Leave a category's sounds out of All (an imported pack you only want on its
        own tab), or put them back. A sound in a hidden category stays out of All even
        when it's in another category too."""
        mw = self.mw
        if name not in mw.cfg.categories or hide == (name in mw.cfg.hidden_from_all):
            return
        if hide:
            mw.cfg.hidden_from_all.append(name)
        else:
            mw.cfg.hidden_from_all.remove(name)
        mw.playctl.shuffle.forget("")   # All's random-sound pool changed
        mw._save_now()
        self._fill_categories()
        mw.searchctl.apply_filter(mw.search.text())
        mw.toast(_("“{name}” is hidden from All. Its sounds stay on its own tab.",
                   name=html.escape(name)) if hide
                 else _("“{name}” shows in All again", name=html.escape(name)), "ok")

    def _update_cat_timer(self):
        mw = self.mw
        on = bool(mw.cfg.category_programs_on and mw.cfg.category_programs)
        if on and not self._cat_timer.isActive():
            self._cat_timer.start()
        elif not on:
            self._cat_timer.stop()
            self.cat_switch.reset()

    def _cat_tick(self):
        mw = self.mw
        sw = self.cat_switch.poll(mw.cfg.category_programs, mw.cfg.category,
                                  mw.cfg.categories)
        if sw is None:
            return
        self.set_category(sw.category)
        names = ["", *mw.cfg.categories]
        n = names.index(sw.category) if sw.category in names else 0
        mw.playctl.cue((523,) if n == 0 else ((784, 0) * min(n, 5))[:-1])   # as step_category
        shown = html.escape(sw.category or ALL)
        mw.toast(_("Back to “{shown}” ({exe} closed)",
                     shown=shown, exe=html.escape(sw.exe)) if sw.back
                   else _("Switched to “{shown}” ({exe} is in front)",
                          shown=shown, exe=html.escape(sw.exe)))

    def add_category_program(self, name: str, exe: str, quiet: bool = False):
        mw = self.mw
        exe = catswitch.exe_name(exe)
        if not exe or name not in mw.cfg.categories:
            return
        mw.cfg.category_programs[exe] = name   # one category per program
        self._category_programs_changed()
        if not quiet:
            mw.toast(_("✓ “{name}” shows by itself when {exe} is in front",
                         name=html.escape(name), exe=html.escape(exe)), "ok")

    def remove_category_program(self, exe: str):
        mw = self.mw
        if mw.cfg.category_programs.pop(exe, None) is not None:
            self._category_programs_changed()

    def set_category_programs_on(self, on: bool):
        mw = self.mw
        mw.cfg.category_programs_on = bool(on)
        self._category_programs_changed()

    def _category_programs_changed(self):
        mw = self.mw
        self.cat_switch.reset()
        self.cat_switch.front_pid = 0   # the program in front now counts as arriving
        self._update_cat_timer()
        mw._save_now()
        self._fill_categories()
        mw.category_programs_changed.emit()

    def _tag_new(self, meta: SoundMeta):
        """A sound added while a category is showing goes into it (so it doesn't seem
        to vanish)."""
        mw = self.mw
        if mw.cfg.category and mw.cfg.category not in meta.tags:
            meta.tags.append(mw.cfg.category)
