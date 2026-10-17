"""A pad's own controls in the main window: its right-click menu (play next, volume, edit,
rename, hotkey, categories, duplicate, export, open file location, remove), its volume
slider and nudges, its picture (set or pasted), and the board's View menu: how the pads
are sorted and shown (grid or list, row size, the pad size picker).

MainWindow makes one ``PadControl`` (``MainWindow.padctl``); everything here runs on
the UI thread."""
from __future__ import annotations

import html
import time
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QActionGroup, QCursor, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSlider,
    QToolTip,
    QWidget,
    QWidgetAction,
)

from soundboard import library, sourceinfo, thumbs
from soundboard.i18n import _, ngettext
from soundboard.library import SoundMeta
from soundboard.settings import pretty_key
from soundboard.ui import clipeditor, icons, responsive, sourcedialog
from soundboard.ui.controller import Controller
from soundboard.ui.panel import icon_label, steady_number

if TYPE_CHECKING:
    from soundboard.ui.mainwindow import MainWindow


class PadControl(Controller):
    """The pad menu and the pads' view for one MainWindow (``mw``)."""

    def __init__(self, mw: MainWindow):
        super().__init__(mw)

    @staticmethod
    def _sort_names() -> dict[str, str]:
        return {"custom": _("My order"), "name": _("A–Z"), "newest": _("Newest"),
                "plays": _("Most played")}

    def _label_view(self):
        """The order button by the search box: the order it shows, and the list icon in
        the list view."""
        mw = self.mw
        b, c = mw.btn_view, mw.cfg
        b.setText(self._sort_names().get(c.pad_sort, ""))
        icons.set_icon(b, "sort")
        b.setToolTip(_("Sort the pads: my order, A–Z, newest, most played"))

    def _fill_view_menu(self, menu: QMenu):
        mw = self.mw
        menu.clear()
        tips = {"custom": _("As you dragged them"), "name": _("By name"),
                "newest": _("The sounds added last first"),
                "plays": _("The sounds you play most first (counted from now on)")}
        group = QActionGroup(menu)
        sort_icons = {"custom": "sort", "name": "rename", "newest": "history",
                      "plays": "star"}
        for key, name in self._sort_names().items():
            a = menu.addAction(name, lambda k=key: self.set_pad_sort(k))
            icons.set_icon(a, sort_icons[key], checked_color="accent")
            a.setCheckable(True)
            a.setChecked(mw.cfg.pad_sort == key)
            a.setToolTip(tips[key])
            group.addAction(a)

    def set_pad_sort(self, how: str):
        mw = self.mw
        if how not in library.PAD_SORTS or how == mw.cfg.pad_sort:
            return
        mw.cfg.pad_sort = how
        self._label_view()
        mw._save_now()
        mw._rebuild_pads()

    def set_pad_view(self, view: str):
        mw = self.mw
        if view not in library.PAD_VIEWS or view == mw.cfg.pad_view:
            return
        mw.cfg.pad_view = view
        # (the order button's label is left alone: its words may be folded away)
        mw.pad_view_toggle.set_view(view)
        self._show_size_picker()
        mw._save_now()
        mw.grid.set_listed(view == "list")

    @staticmethod
    def _row_names() -> dict[str, str]:
        return {"small": _("Small"), "medium": _("Medium"), "large": _("Large")}

    def _label_rows(self):
        mw = self.mw
        mw.btn_rows.setText(self._row_names().get(mw.cfg.list_rows, ""))

    def _fill_rows_menu(self, menu: QMenu):
        mw = self.mw
        menu.clear()
        group = QActionGroup(menu)
        for key, name in self._row_names().items():
            a = menu.addAction(name, lambda k=key: self.set_list_rows(k))
            a.setCheckable(True)
            a.setChecked(mw.cfg.list_rows == key)
            group.addAction(a)

    def set_list_rows(self, size: str):
        mw = self.mw
        if size not in library.LIST_ROWS or size == mw.cfg.list_rows:
            return
        mw.cfg.list_rows = size
        self._label_rows()
        mw._save_now()
        mw.grid.set_row_size(size)

    def _show_size_picker(self):
        """Card size for the cards, Row size for the list; neither in a narrow window."""
        mw = self.mw
        listed = mw.cfg.pad_view == "list"
        for w in mw._pad_size:
            w.setVisible(not listed and not mw._size_tight)
        for w in mw._row_size:
            w.setVisible(listed and not mw._size_tight)
        responsive.touch(*mw._pad_size, *mw._row_size)

    def _fit_size_picker(self, tight: bool):
        mw = self.mw
        mw._size_tight = tight
        self._show_size_picker()
        mw.selection.sync()

    def _volume_action(self, menu: QMenu, m: SoundMeta) -> QWidgetAction:
        """A pad menu's volume slider: changes it as it's dragged (a playing sound too)."""
        mw = self.mw
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(10, 4, 10, 4)
        h.setSpacing(8)
        h.addWidget(icon_label("volume", _("This sound's volume (Ctrl+wheel on the pad "
                                            "changes it too)")))
        sl = QSlider(Qt.Orientation.Horizontal)
        sl.setRange(0, 200)
        sl.setSingleStep(5)
        sl.setPageStep(10)
        sl.setValue(round(m.volume * 100))
        sl.setFixedWidth(120)
        sl.setAccessibleName(_("Volume"))
        val = QLabel(f"{sl.value()}%")
        val.setObjectName("muted")
        steady_number(val, "200%")

        def moved(v: int):
            val.setText(f"{v}%")
            m.volume = v / 100
            mw.engine.set_gain(m.id, mw.gain_for(m))
        sl.valueChanged.connect(moved)
        h.addWidget(sl)
        h.addWidget(val)
        a = QWidgetAction(menu)
        a.setText(_("Volume"))   # what a screen reader says for the row
        a.setDefaultWidget(w)
        return a

    def nudge_volume(self, sid: str, steps: int):
        """Ctrl+wheel on a pad: its volume in 5 % steps (0-200 %, as in Edit)."""
        mw = self.mw
        m = mw.meta(sid)
        if m is None:
            return
        m.volume = round(min(2.0, max(0.0, m.volume + 0.05 * steps)), 2)
        mw.engine.set_gain(sid, mw.gain_for(m))
        QToolTip.showText(QCursor.pos(), _("{name}: {pct}%", name=m.name,
                                           pct=round(m.volume * 100)), mw.pads.get(sid))
        if not mw.playctl._count_save.isActive():
            mw.playctl._count_save.start()

    def pad_menu(self, sid, pos):
        mw = self.mw
        m = mw.meta(sid)
        if not m:
            return
        if sid in mw.selection.picked and len(mw.selection.picked) > 1:
            mw.selection.menu(pos)   # right-click on a picked pad: act on all of them
            return
        # short labels in three groups (play / change / share & remove); what each does
        # in more words is its tooltip
        menu = QMenu(mw)
        menu.setToolTipsVisible(True)

        def add(icon, text, tip="", parent=menu):
            a = parent.addAction(icons.icon(*icon) if icon else QIcon(), text)
            a.setToolTip(tip or text)
            return a
        a_stop = add(("stop",), _("Stop")) if mw.engine.state(sid) else None
        a_next = add(("play",), _("Play next"), _("Plays it after the sounds playing now"))
        vol_before = m.volume
        menu.addAction(self._volume_action(menu, m))
        menu.addSeparator()
        a_edit = add(("edit",), _("Edit"), _("Name, colour, picture, volume, hotkey, "
                                              "timing and effects"))
        a_ren = add(("rename",), _("Rename"), _("Just the name (F2 on the pad does it too)"))
        a_hk_clear = None
        if m.hotkey:
            hk = menu.addMenu(icons.icon("keyboard"), _("Hotkey: {hotkey}",
                                                        hotkey=pretty_key(m.hotkey)))
            hk.setToolTipsVisible(True)
            a_hk = add(("keyboard",), _("Change"), _("Press a new key or combo for it"), hk)
            a_hk_clear = add(("trash",), _("Remove hotkey"), "", hk)
        else:
            a_hk = add(("keyboard",), _("Set hotkey"), _("A key or combo that plays it, even "
                                                          "in-game"))
        cats = menu.addMenu(icons.icon("tag"), _("Categories"))
        cat_acts = {}
        for c in mw.cfg.categories:
            a = cats.addAction(icons.icon("tag", checked_color="accent"), c.replace("&", "&&"))
            a.setCheckable(True)
            a.setChecked(c in m.tags)
            cat_acts[a] = c
            for sub in mw.cfg.subcategories.get(c, []):   # indented under it
                tag = library.sub_tag(c, sub)
                a = cats.addAction(icons.icon("tag", checked_color="accent"),
                                   "      " + sub.replace("&", "&&"))
                a.setCheckable(True)
                a.setChecked(tag in m.tags)
                cat_acts[a] = tag
        if cat_acts:
            cats.addSeparator()
        a_newcat = cats.addAction(icons.icon("plus"), _("New category"))
        cat_subs = {cats.addAction(icons.icon("plus"), _("New subcategory in {cat}", cat=c)): c
                    for c in mw.cfg.categories if c in m.tags}
        menu.addSeparator()
        a_dup = add(("copy",), _("Duplicate"), _("A second pad with the same sound, to give "
                                                 "its own effects or hotkey"))
        a_export = add(("download",), _("Export"), _("Save it as a file to share with friends"))
        a_src_open = a_src_copy = a_src_info = a_src_share = None
        if src := sourceinfo.shown(m):   # downloaded from YouTube, TikTok…
            site = sourceinfo.site_name(src)
            sm = menu.addMenu(icons.icon(sourceinfo.icon(src)), site)
            sm.setToolTipsVisible(True)
            a_src_open = add(("browser",), _("Open on {site}", site=site), src["link"], sm)
            a_src_copy = add(("copy",), _("Copy link"), src["link"], sm)
            a_src_info = add(("info",), _("Details"), _("Channel, upload date, length, views"),
                             sm)
            # the Store tab can take its link (only the link: whoever adds it downloads it)
            from soundboard import store
            from soundboard.ui.storetab import StoreTab
            if isinstance(mw.store, StoreTab) and store.link_ok(src["link"]):
                a_src_share = add(("store",), _("Share to the store"),
                                  _("Share this link in the Community tab"), sm)
        a_show = add(("folder",), _("Open file location"))
        a_del = add(("trash", "danger_text"), _("Remove"), _("Goes to Recently deleted"))
        act = menu.exec(pos)
        menu.deleteLater()   # its actions stay valid until this returns
        if m.volume != vol_before:
            mw._save_now()
        if act is None:
            return
        if act in cat_acts:
            mw.catctl.toggle_tag(sid, cat_acts[act])
        elif act in cat_subs:
            mw.catctl.new_subcategory(cat_subs[act], sid)
        elif act == a_newcat:
            mw.catctl.new_category(sid)
        elif act == a_export:
            mw.impctl.export_sounds([m], m.name)
        elif act is not None and act == a_src_open:
            sourcedialog.open_link(src, mw)
        elif act is not None and act == a_src_copy:
            sourcedialog.copy_link(src, mw)
        elif act is not None and act == a_src_share:
            mw.store.share(src["link"], m.name)
        elif act is not None and act == a_src_info:
            d = sourcedialog.SourceDialog(m, mw)
            d.forgotten.connect(mw._save_now)
            d.show()
        elif act == a_stop:
            mw.playctl._stop_sound(sid)
        elif act == a_next:
            mw.playctl.queue_sound(sid)
        elif act == a_edit:
            mw.editctl.edit(sid)
        elif act == a_ren:
            mw.soundctl.rename_sound(sid)
        elif act == a_dup:
            mw.editctl.duplicate_sound(sid)
        elif act == a_show:
            mw.editctl.show_sound_file(sid)
        elif act == a_hk:
            mw.hkctl.set_sound_hotkey(sid)
        elif act is not None and act == a_hk_clear:
            mw.hkctl.set_sound_hotkey(sid, "")
        elif act == a_del:
            mw.rmctl.ask_remove([sid])

    def set_picture(self, sid: str, path: str):
        """Put a picture on a pad (an image dropped on it)."""
        mw = self.mw
        m = mw.meta(sid)
        if not m:
            return
        if not thumbs.set_image(m, path):
            mw.tell(_("Couldn't use that picture"),
                      _("{name} isn't a picture this app can read.", name=Path(path).name),
                      "warn")
            return
        mw._save_now()
        mw.pads[sid].update()

    def paste_picture(self):
        """Ctrl+V on the Sounds tab: a clip copied in the Apps tab's editor (or its
        Saved clips) is added as a sound; a copied picture goes on the picked pads,
        or else on the selected one."""
        mw = self.mw
        clip = clipeditor.pasted_clip()
        if clip is not None:
            mw.soundctl.on_clip(clip.copy(), _("Clip {time}", time=time.strftime('%H.%M.%S')))
            return
        sids = [m.id for m in mw.selection.sounds()] or (
            [mw.current] if mw.current in mw.pads else [])
        if not sids:
            return
        img = thumbs.from_clipboard(QApplication.clipboard().mimeData())
        if img is None:
            mw.toast(_("Nothing to paste: copy a picture first (in a browser: "
                         "right-click it → Copy image), then press Ctrl+V on a pad."), "warn")
            return
        done = [sid for sid in sids if (m := mw.meta(sid)) and thumbs.set_image(m, img)]
        if not done:
            return
        mw._save_now()
        for sid in done:
            mw.pads[sid].update()
        m = mw.meta(done[0])
        assert m is not None   # done holds only sounds with a meta
        mw.toast(_("Picture pasted on “{name}”.",
                     name=html.escape(m.name)) if len(done) == 1
                   else ngettext("Picture pasted on {n} pad.",
                                 "Picture pasted on {n} pads.", len(done)), "ok")
