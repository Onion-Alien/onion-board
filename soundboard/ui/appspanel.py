"""The Apps tab: send one running program's sound (a music player, a browser, a
game, a call in another app) out to others (the cable, another device or the
stream output, like your sounds), without touching what any other program plays.
Each program is a card: its level, a **Send** switch, its own volume and *Hear it
myself*, and **Record**, which waits for the program to make a sound, records it
until you click again and adds it to your Sounds as a pad. The scissors button
beside Record folds out its *Clip editor* (soundboard.ui.clipeditor): opened, it
keeps the program's last minute as a live waveform to cut bits out of; closed,
nothing of it runs. Its Save puts the bit in *Saved clips* under the cards
(soundboard.ui.clipshelf), and its Big view button gives one card the whole tab.

The capture is Windows' per-process loopback (soundboard.audio.appaudio), a *copy* of
the program's audio: the program keeps playing on your speakers. Programs you
switch on are remembered by their .exe and folder (path_key), and picked up again
next time they run.

The cards, their category headings and grid are in soundboard.ui.approw; the
capture, Record and Clip editor half is soundboard.ui.appcapture (AppsTab.capctl).
"""
from __future__ import annotations

import dataclasses
import logging
import os
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QInputDialog, QLabel, QLayoutItem,
                               QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget)

from soundboard.audio import appaudio
from soundboard.ui.kit import theme
from soundboard.core import trash, usage
from soundboard.sounds import library
from soundboard.i18n import _
from soundboard.ui.kit import a11y, appstate, icons
from soundboard.ui.kit.widgets import InlineNameBox, widget_at
from soundboard.ui.appcapture import METER_MS, AppCapture
# the cards and their helpers live in approw.py; their names stay importable from here
from soundboard.ui.approw import (APP_CATEGORIES, APP_DRAG_MIME,  # noqa: F401
                                  CATEGORY_DRAG_MIME, HIDDEN_FULL_S, MAX_VOL, TO, TO_KEYS,
                                  AppCategoryHeading, AppGrid, AppRow, ElidedLabel,
                                  _Lister, _route, app_category, category_label,
                                  is_path_key, path_key, saved_volume)
from soundboard.ui.bunnywidget import BunnyWidget
from soundboard.ui.clipeditor import WAVE_H
from soundboard.ui.clipshelf import ClipShelf
from soundboard.ui.kit.panel import UndoBar, ViewToggle, hint_label
from soundboard.ui.responsive import FitWidth
from soundboard.ui.speedpitch import SpeedPitchButton
from soundboard.ui.kit.wheelguard import no_wheel

log = logging.getLogger(__name__)

REFRESH_MS = 1500       # how often the list of programs is re-read while the tab is shown
REFRESH_HIDDEN_MS = 5000   # ...and while it isn't (a remembered program still gets picked up)
IDLE_SECONDS = 10 * 60   # quiet, unused cards disappear until their program makes sound again
MAX_REMEMBERED = 30
CARD_MIN_W = 300        # programs are cards, as many across as fit at this width
CARD_MAX_W = 900        # the Card size slider's widest: one big card across most windows
NEW_CARDS = 1           # program cards made per go (see AppsTab._apply_listing)
CARDS_GAP_MS = 6        # ...and the break between goes, for the audio thread
BUN_REST_S = 30.0       # the empty page's Bun moves this long, then holds still until a sound


class AppsTab(QWidget):
    """Lists the programs that have sound and captures the ones you switch on."""
    clip_ready = Signal(object, str)   # audio, suggested name (like RadioTab's)
    clip_error = ""                    # set by whoever saves the clip, when it can't
    active_changed = Signal(bool)      # some program is / no program is sent (the tab's live dot)

    def __init__(self, engine, cfg, save_cb, meter_cls):
        super().__init__()
        self.engine, self.cfg, self._save, self._meter_cls = engine, cfg, save_cb, meter_cls
        if not isinstance(cfg.apps, dict):
            cfg.apps = {}
        if not isinstance(cfg.apps_paths, dict):
            cfg.apps_paths = {}
        self.rows: dict[str, AppRow] = {}     # exe (lower) or path_key -> row
        self._idle_hidden: set[str] = set()   # temporary; unlike explicitly forgotten programs
        self.capctl = AppCapture(self)   # capture, Record and the clip editors
        self._sending: tuple[str, ...] = ()   # the programs being sent, as last reported
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 8, 0, 0)
        v.setSpacing(8)
        # the explanation is behind the ⓘ at the end of the tab bar (MainWindow)
        self.info = (_("Send a program's sound"),
                     _("Pick a program that's playing (a music player, a browser, a game, "
                       "even a call in another app) and it goes out to whoever's listening, "
                       "on its own volume, the same way your sounds do (your mic, the "
                       "cable or the device you picked on the Setup tab, and the stream "
                       "output). Sending to Nobody: only the stream output gets it. Only "
                       "that program: nothing else you play is "
                       "touched, and it keeps playing on your speakers as before. Programs "
                       "you switch on are remembered and picked up again next time they run."))
        self.warn = hint_label("")
        theme.set_tone(self.warn, "warn")
        self.warn.setVisible(False)
        v.addWidget(self.warn)
        self.btn_bin = QPushButton(_("Forgotten programs"))
        self.btn_bin.setToolTip(_("Bring back a program you forgot, with its volume and "
                                  "“Hear it myself”"))
        icons.set_icon(self.btn_bin, "trash")
        self.btn_bin.clicked.connect(self.show_forgotten)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        toolbar.addWidget(self.btn_bin)
        # Live controls: pitch and effects on every program you send (no speed: live)
        self.fx_btn = SpeedPitchButton("apps")
        self.fx_btn.changed.connect(lambda _s, p, _k: setattr(self.engine, "apps_pitch", p))
        self.fx_btn.fx_changed.connect(lambda fx: setattr(self.engine, "apps_fx", fx))
        toolbar.addWidget(self.fx_btn)
        self.btn_add_cat = QPushButton(_("Category"))
        self.btn_add_cat.setObjectName("small")
        self.btn_add_cat.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add_cat.setToolTip(_("New category"))
        icons.set_icon(self.btn_add_cat, "plus", size=12)
        # the name is typed right where the button is (no pop-up)
        self.cat_name_box = InlineNameBox(self.btn_add_cat, _("New category"))
        self.cat_name_box.named.connect(self._add_category)
        toolbar.addWidget(self.cat_name_box)
        toolbar.addWidget(self.btn_add_cat)
        toolbar.addStretch(1)
        self.view_toggle = ViewToggle(cfg.app_view, _("Apps"))
        self.view_toggle.changed.connect(self.set_view)
        size_label = self.size_label = QLabel(_("Card size"))
        size_label.setObjectName("muted")
        toolbar.addWidget(size_label)
        self.card_size = QSlider(Qt.Orientation.Horizontal)
        self.card_size.setRange(240, CARD_MAX_W)
        self.card_size.setValue(cfg.app_card_width)
        self.card_size.setFixedWidth(100)
        self.card_size.setAccessibleName(_("App card size"))
        self.card_size.setToolTip(_("App card size: smaller fits more programs across"))
        no_wheel(self.card_size)
        toolbar.addWidget(self.card_size)
        toolbar.addWidget(self.view_toggle)
        v.addLayout(toolbar)
        self.undo_bar = UndoBar(_("Remember the program again, as it was"))
        v.addWidget(self.undo_bar)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        a11y.scroll_stop(self.scroll_area, _("Apps"))
        self.list = FitWidth()   # the cards re-flow to the width they get (AppRow._fit_width)
        self.list_layout = QVBoxLayout(self.list)
        self.list_layout.setContentsMargins(0, 0, 6, 0)
        self.list_layout.setSpacing(6)
        self.grid = AppGrid(self.list, categories=getattr(cfg, "apps_categories", None),
                            min_w=self.card_size.value(), gap=10, even=False)
        self._wire_headings()
        self.card_size.valueChanged.connect(self._set_card_size)
        self.grid.listed = cfg.app_view == "list"
        # nothing playing: Bun waits, a bit glum, above the how-to, halfway down the page
        self.empty = QWidget()
        ev = QVBoxLayout(self.empty)
        ev.setContentsMargins(0, 12, 0, 0)
        ev.setSpacing(12)
        ev.addStretch(1)
        self.bun = BunnyWidget(height=130, pad=18, sad=0.6,
                               lines=(_("play something?"), _("so quiet…"),
                                      _("music, please?")),
                               joy_lines=(_("hehe!"), _("yay!")), pong=True, naps=True,
                               dances=True, rest_after_s=BUN_REST_S)
        ev.addWidget(self.bun, 0, Qt.AlignmentFlag.AlignHCenter)
        self.empty_text = hint_label(_("Nothing is playing sound right now. Start some music, "
                                       "a video or a call and it'll show up here."))
        self.empty_text.setObjectName("empty")   # the Sounds tab's empty line
        self.empty_text.setStyleSheet("padding:8px 12px; background:transparent;")
        self.empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ev.addWidget(self.empty_text)
        ev.addStretch(1)
        self.list_layout.addWidget(self.empty, 1)
        self._tools_for_rows()
        self.list_layout.addLayout(self.grid)
        self.list_layout.addStretch(0)   # no cards yet: the empty page gets the room
        self.scroll_area.setWidget(self.list)
        v.addWidget(self.scroll_area, 1)
        self.big: AppRow | None = None   # the card in the big view (the rest are hidden)
        # what the clip editors' Save keeps, under the cards
        self.shelf = ClipShelf(engine, cfg, self)
        self.shelf.add_to_sounds.connect(self.capctl._shelf_to_sounds)
        self.shelf.layout_changed.connect(self._fit_big)
        self.shelf.size_changed.connect(self._save)
        self.list_layout.insertWidget(self.list_layout.count() - 1, self.shelf)

        ok, why = appaudio.supported()
        if not ok:
            self.warn.setText(why)
            self.warn.setVisible(True)

        for exe, spec in list(cfg.apps.items())[:MAX_REMEMBERED]:   # remembered programs
            if isinstance(spec, dict):
                self._row(exe, saved_volume(spec.get("vol", 1.0)), bool(spec.get("monitor")),
                          str(spec.get("to", "both")), path=str(spec.get("path") or ""),
                          category=str(spec.get("category") or ""))
        for key, spec in list(cfg.apps_paths.items())[:MAX_REMEMBERED]:
            if isinstance(spec, dict) and is_path_key(key):
                self._row(str(spec.get("exe") or key.rsplit("\\", 1)[-1]),
                          saved_volume(spec.get("vol", 1.0)), bool(spec.get("monitor")),
                          str(spec.get("to", "both")), key=key, path=key,
                          category=str(spec.get("category") or ""))
        self._label_folders()

        self.peaks = appaudio.PeakWatcher()   # live levels; the list is only re-read every 1.5 s
        # no Qt parent: a listing still running when the panel goes (Apps tab off,
        # quitting) must not emit from a deleted object; the thread keeps it alive,
        # and the bound slot drops the result once the panel is gone
        self.lister = _Lister(None, self.peaks)
        self._listing = 0   # listings come in numbered: a newer one replaces a half-done one
        self.lister.ready.connect(self._on_listed)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh)
        self.meter_timer = QTimer(self)
        self.meter_timer.timeout.connect(self.capctl._meters)
        appstate.slow_in_background(self, self.meter_timer, METER_MS)   # behind a game
        # behind a game nobody watches the levels: the meters fall back to the list's
        appstate.pause_in_background(self, self.peaks.start, self.peaks.stop)
        self._started = False
        self._label_bin()
        if self.rows:   # remembered programs are picked up even if this tab is never opened
            QTimer.singleShot(1500, self.start)

    def set_view(self, view: str):
        """Cards, or a list: one program a line."""
        listed = view == "list"
        self.view_toggle.set_view(view)
        if self.cfg.app_view != view:
            self.cfg.app_view = view
            self._save()
        self.grid.listed = listed
        self._tools_for_rows()
        for row in self.rows.values():
            row.set_listed(listed)
        self.grid.invalidate()
        self.list.updateGeometry()
        self.list_layout.activate()

    def _set_card_size(self, width: int):
        self.cfg.app_card_width = width
        self.grid.min_w = width
        self.grid.invalidate()
        self.list.updateGeometry()
        self.list_layout.activate()
        self._save()

    # ------------------------------------------------------------------ lifecycle
    def _layout_apps(self):
        shown = 0
        for row in self.rows.values():
            visible = self.big is None or row is self.big
            row.setVisible(bool(visible))
            shown += bool(visible)
        self.empty.setVisible(not shown)
        # the room under the cards goes to the empty page instead, so it sits centred
        self.list_layout.setStretch(self.list_layout.count() - 1, 1 if shown else 0)
        self.grid.invalidate()
        self.list.updateGeometry()

    def _wire_headings(self):
        for heading in self.grid.headings.values():
            self._wire_heading(heading)

    def _wire_heading(self, heading: AppCategoryHeading):
        heading.reordered.connect(self._on_category_reordered)
        heading.card_dropped.connect(self._on_card_dropped_on_category)
        heading.rename_requested.connect(self._on_rename_category)
        heading.delete_requested.connect(self._on_delete_category)

    def _add_category(self, typed: str):
        name = (library.clean_tags([typed]) or [""])[0]
        if not name or self._category_taken(name):
            return
        usage.used("apps-category-added")
        label = self.grid.add_category(name)
        if label:
            self._wire_heading(label)
        self.cfg.apps_categories = list(self.grid.category_order)
        self._save()
        self._layout_apps()

    def _on_category_reordered(self, source_cat: str, target_cat: str, before: bool):
        usage.used("apps-reorder")
        self.grid.reorder_categories(source_cat, target_cat, before)
        self.cfg.apps_categories = list(self.grid.category_order)
        self._save()
        self._layout_apps()

    def _on_card_dropped_on_category(self, source: AppRow, category: str):
        self._move_row_to_category(source, category)

    def _category_taken(self, name: str) -> bool:
        """A category already has this name, saved or shown ('Spiele' is Games)."""
        return any(name in (c, category_label(c)) for c in self.grid.category_order)

    def _on_rename_category(self, old_cat: str):
        new_name, ok = QInputDialog.getText(self, _("Rename category"),
                                            _("New name:"), text=category_label(old_cat))
        new_name = (library.clean_tags([new_name]) or [""])[0] if ok else ""
        if not new_name or self._category_taken(new_name):
            return   # unchanged too: OK on the shown name renames nothing
        usage.used("apps-category-renamed")
        self.grid.rename_category(old_cat, new_name)
        for row in self.rows.values():
            if row.category == old_cat:
                row.category = new_name
                self._save_row_category(row)
        self.cfg.apps_categories = list(self.grid.category_order)
        self._save()
        self._layout_apps()

    def _on_delete_category(self, category: str):
        usage.used("apps-category-deleted")
        for row in self.rows.values():
            if row.category == category:
                row.category = "Other"
                self._save_row_category(row)
        self.grid.remove_category(category)
        self.cfg.apps_categories = list(self.grid.category_order)
        self._save()
        self._layout_apps()

    def _move_row_to_category(self, source: AppRow, target_cat: str):
        if self.big is not None or source.category == target_cat:
            return
        usage.used("apps-reorder")
        source.category = target_cat
        self._save_row_category(source)
        order = self._grid_rows()
        order.remove(source)
        first_target = next((r for r in order if r.category == target_cat), None)
        if first_target is not None:
            order.insert(order.index(first_target), source)
        else:
            order.append(source)
        items = self._take_grid_items()
        for row in order:
            self.grid.addItem(items[row])
        self.grid.invalidate()
        self.list_layout.activate()

    def _grid_rows(self) -> list[AppRow]:
        """The cards in the grid, in its order."""
        rows = []
        for i in range(self.grid.count()):
            w = widget_at(self.grid, i)
            assert isinstance(w, AppRow)   # the grid holds only cards (headings sit beside it)
            rows.append(w)
        return rows

    def _take_grid_items(self) -> dict[QWidget | None, QLayoutItem]:
        """Every item out of the grid, by its card."""
        taken = [self.grid.takeAt(0) for _ in range(self.grid.count())]
        return {item.widget(): item for item in taken if item is not None}

    def _save_row_category(self, row: AppRow):
        spec = self._spec(row.key)
        if spec is None:
            self.cfg.apps[row.key] = {"vol": row.vol.value(), "monitor": row.chk_hear.isChecked(),
                                      "to": row.to, "category": row.category}
        else:
            spec["category"] = row.category
        self._save()

    def _reorder_apps(self, source: AppRow, target: AppRow, before: bool):
        if (self.big is not None or source is target
                or self.rows.get(source.key) is not source
                or self.rows.get(target.key) is not target):
            return
        usage.used("apps-reorder")
        if source.category != target.category:
            source.category = target.category
            self._save_row_category(source)
        order = self._grid_rows()
        order.remove(source)
        order.insert(order.index(target) + (not before), source)
        # Move layout items, keeping the same cards, captures and clip editors alive.
        items = self._take_grid_items()
        for row in order:
            self.grid.addItem(items[row])
        self.grid.invalidate()
        self.list_layout.activate()

    def showEvent(self, ev):
        super().showEvent(ev)
        self.start()
        self._pace_list()
        self.meter_timer.start(appstate.interval(METER_MS))
        if appstate.active():
            self.peaks.start()

    def hideEvent(self, ev):
        super().hideEvent(ev)
        self.peaks.stop()
        self._pace_list()

    def start(self):
        """Begin watching for programs (also called before the tab is first shown,
        so remembered programs are picked up right after launch)."""
        if self._started:
            return
        self._started = True
        # the meters run while shown / recording; the list is re-read slowly until then
        self._pace_list()
        self.lister.refresh()

    def _refresh(self):
        """The list timer: the whole listing while the tab shows (or a capture needs
        starting again), else the lister's cheap check first."""
        if self.isVisible() or any(
                row.capture is not None and (row.capture.ended or row.capture.error)
                for row in self.rows.values()):
            self.lister.refresh()
            return
        watch = frozenset(row.exe.lower() for row in self.rows.values())
        waiting = frozenset(row.exe.lower() for key, row in self.rows.items()
                            if row.app is None and self._spec(key) is not None)
        self.lister.refresh(watch, waiting)

    def _watching(self) -> bool:
        """Keep checking existing cards while hidden, including their idle deadlines."""
        return bool(self.rows)

    def _pace_list(self):
        """Re-read the list every 1.5 s while shown, every 5 s while hidden, and not
        at all while hidden with no cards left."""
        if not self._started:
            return
        ms = (REFRESH_MS if self.isVisible() else
              REFRESH_HIDDEN_MS if self._watching() else 0)
        if not ms:
            self.timer.stop()
        elif not self.timer.isActive() or self.timer.interval() != ms:
            self.timer.start(ms)

    def shutdown(self):
        self.timer.stop()
        self.meter_timer.stop()
        self.peaks.stop()
        self.lister.stop()
        self.shelf.shutdown()
        for row in list(self.rows.values()):
            row.close_view()
            self.capctl._stop_capture(row, save=False)
            if row.editor is not None:
                row.editor.shutdown()
        end = time.monotonic() + 3.0   # all of them together, not 3 s each
        for cap in self.capctl._stopping:
            cap.join(max(0.0, end - time.monotonic()))
        self.capctl._stopping = []

    def stop_all(self):
        """Stop all: switch every program off (they stay remembered). A recording
        keeps going: nobody hears it."""
        for row in self.rows.values():
            if row.sending:
                row.set_sending(False)
                self.capctl._stop_send(row)
        self._report_active()

    def on_air(self) -> bool:
        return self.engine.aux_on_air()

    def is_active(self) -> bool:
        """Some program's sound is being sent."""
        return any(row.sending for row in self.rows.values())

    def live_tip(self) -> str:
        """The "● ON" line for the Apps tab's tooltip while a program is sent."""
        names = [row.name.text() for row in self.rows.values() if row.sending]
        if not names:
            return _("● ON: sending a program's sound")
        return _("● ON: sending {programs}", programs=", ".join(names))

    def _report_active(self):
        """Tell the tab's live dot when the set of programs being sent changes
        (on / off, and which: its tip names them)."""
        now = tuple(sorted(key for key, row in self.rows.items() if row.sending))
        if now != self._sending:
            self._sending = now
            self.active_changed.emit(bool(now))

    # ------------------------------------------------------------------ rows
    def _row(self, exe: str, vol: float = 1.0, hear: bool = False, to: str = "both",
             key: str = "", path: str = "", category: str = "") -> AppRow:
        key = key or exe.lower()
        row = self.rows.get(key)
        if row is None:
            spec = self._spec(key)
            cat = (category or (spec.get("category") if isinstance(spec, dict) else "")
                   or app_category(exe))
            if cat not in self.grid.category_order:   # gone: the layout would skip the card
                cat = app_category(exe)
            row = self.rows[key] = AppRow(exe, self._meter_cls, vol, hear, to, key, path,
                                          category=cat)
            row.show_to(self._stream_output())
            row.set_listed(self.grid.listed)
            row.send_toggled.connect(self._on_send)
            row.rec_toggled.connect(self.capctl._on_rec)
            row.vol_changed.connect(self._on_vol)
            row.hear_toggled.connect(self._on_hear)
            row.to_changed.connect(self._on_to)
            row.clip_toggled.connect(self.capctl._on_clip)
            row.forget.connect(self._on_forget)
            row.reordered.connect(self._reorder_apps)
            row.move_to_category.connect(self._move_row_to_category)
            self.grid.addWidget(row)
            self._layout_apps()
            self._tools_for_rows()
        return row

    def _tools_for_rows(self):
        """The effects button, the card-size slider and cards / list only mean
        something with a card to apply them to: hidden over the empty page. The list
        view's rows are the tab's width: no card size there."""
        for w in (self.fx_btn, self.btn_add_cat, self.view_toggle):
            w.setVisible(bool(self.rows))
        for w in (self.size_label, self.card_size):
            w.setVisible(bool(self.rows) and not self.grid.listed)

    def _drop_row(self, row: AppRow):
        row.close_view()
        self.capctl._stop_capture(row)
        self.capctl._close_clip(row)
        if self.big is row:
            self._set_big(row, False)
        if row.editor is not None:
            row.editor.shutdown()
        self.rows.pop(row.key, None)
        self.grid.removeWidget(row)
        row.deleteLater()
        self._layout_apps()
        self._tools_for_rows()
        self._report_active()

    def _hidden(self) -> set[str]:
        return {str(e).lower() for e in self.cfg.apps_hidden}

    # ------------------------------------------------------------------ keys
    # A program is remembered by its .exe name (cfg.apps, all an older version reads)
    # and the folder it runs from (spec["path"]). Another program with the same name
    # from another folder gets a row of its own, keyed and remembered by its path
    # (cfg.apps_paths), so the two never share a volume, a Send or an auto-send.
    def _spec(self, key: str) -> dict | None:
        """What's remembered about the row `key`, None if nothing."""
        spec = (self.cfg.apps_paths if is_path_key(key) else self.cfg.apps).get(key)
        return spec if isinstance(spec, dict) else None

    def _keys_for(self, apps: list) -> list[str]:
        """The row key for each listed program: its .exe for the one program of that
        name that "owns" it (the remembered folder; else the one already on the row;
        else the first listed), its path_key for any other one."""
        paths: dict[str, list[str]] = {}
        for app in apps:
            paths.setdefault(app.exe.lower(), []).append(path_key(app.path) if app.path else "")
        owner: dict[str, str] = {}
        for exe, found in paths.items():
            spec = self._spec(exe)
            home = str(spec.get("path") or "") if spec is not None else ""
            row = self.rows.get(exe)
            if home:
                owner[exe] = home
            elif row is not None and row.path and row.path in found:
                owner[exe] = row.path
            else:
                owner[exe] = next((p for p in found if p not in self.cfg.apps_paths), found[0])
        keys = []
        for app in apps:
            exe, p = app.exe.lower(), path_key(app.path) if app.path else ""
            if p and p in self.cfg.apps_paths:
                keys.append(p)
            elif not p or p == owner[exe]:
                keys.append(exe)
            else:
                keys.append(p)
        return keys

    def _label_folders(self):
        """Two rows of the same .exe name: each shows the folder it runs from."""
        count: dict[str, int] = {}
        for row in self.rows.values():
            count[row.exe.lower()] = count.get(row.exe.lower(), 0) + 1
        for row in self.rows.values():
            folder = ""
            if count[row.exe.lower()] > 1 and row.path:
                parts = [p for p in row.path.split("\\")[:-1] if p and p != "*"]
                stem = os.path.splitext(row.exe.lower())[0]
                while len(parts) > 1 and parts[-1] in (stem, "bin", "app", "application"):
                    parts.pop()   # ...\spotify\spotify.exe: "spotify" tells nothing
                folder = f" ({parts[-1]})" if parts else ""
            if folder != row.folder:
                row.folder = folder
                row.name.setToolTip(row.app.path if row.app is not None else row.path)
                row.set_app(row.app)

    def _on_listed(self, listed):
        self._listing += 1
        self._apply_listing(self._listing, *listed)

    def _apply_listing(self, n: int, apps: list, alive: dict[int, str] | None):
        """A listing, NEW_CARDS at a time: making a card is ~10 ms of Qt calls, and
        the first look at the tab with eight programs running made them all at once,
        long enough to skip a sound playing. The rest follow a moment later (unless a
        newer listing came in meanwhile, which picks them up itself)."""
        if n != self._listing:
            return
        hidden = self._hidden()
        new = [key for key in dict.fromkeys(
                   key for app, key in zip(apps, self._keys_for(apps))
                   if key not in self._idle_hidden or self._sound_active(app))
               if key not in self.rows and key not in hidden]
        if len(new) > NEW_CARDS:
            now = set(new[:NEW_CARDS])
            # every copy of a kept program's .exe stays in: which copy gets the .exe's
            # own card is worked out among them
            keep = {app.exe.lower() for app, key in zip(apps, self._keys_for(apps))
                    if key in self.rows or key in now}
            self._on_apps([app for app in apps if app.exe.lower() in keep], alive)
            QTimer.singleShot(CARDS_GAP_MS, self,
                              lambda: self._apply_listing(n, apps, alive))
            return
        self._on_apps(apps, alive)

    def _sound_active(self, app: appaudio.App) -> bool:
        live = self.peaks.peak(app.pid)
        return app.peak > 0 or (live is not None and live > 0)

    def _on_apps(self, apps: list, alive: dict[int, str] | None = None):
        """`apps` the programs with an audio session; `alive` every running process
        (pid -> exe), when known. Quiet processes keep their cards for ten minutes;
        remembered programs, recordings and clip editors stay available."""
        now = time.monotonic()
        stream = self._stream_output()   # set or cleared in Settings meanwhile
        for row in self.rows.values():
            row.show_to(stream)
        by_key: dict[str, appaudio.App] = {}
        hidden = self._hidden()
        for app, key in zip(apps, self._keys_for(apps)):
            if key in hidden and key not in self.rows:
                continue                          # taken off the list with ✕
            audible = self._sound_active(app)
            if key in self._idle_hidden:
                if not audible:
                    continue
                self._idle_hidden.discard(key)
            cur = self.rows.get(key)
            if cur is not None and cur.capture is not None and cur.capture.pid == app.pid:
                by_key[key] = app   # two copies running: stay on the one being captured
            else:
                by_key.setdefault(key, app)
            self._row(app.exe, key=key)
            if audible:
                self.rows[key].last_sound_at = now
        for key, row in list(self.rows.items()):
            app = by_key.get(key)
            if (app is None and alive is not None and row.app is not None
                    and alive.get(row.app.pid) == row.app.exe.lower()):
                # quiet, not closed: no level, no "playing on"
                app = dataclasses.replace(row.app, active=False, peak=0.0, devices=[])
            if app is not None and app.path:
                row.path = path_key(app.path)
                spec = self._spec(key)
                if spec is not None and not is_path_key(key) and not spec.get("path"):
                    spec["path"] = row.path   # remembered by an older version: by name only
                    self._save()
            remembered = self._spec(key) is not None
            if (now - row.last_sound_at >= IDLE_SECONDS and not remembered
                    and not row.sending and row.rec is None and row.listen is None
                    and not self.capctl._has_take(row)):
                self._idle_hidden.add(key)
                self._drop_row(row)
                continue
            if app is None:                       # not running
                self.capctl._stop_capture(row)
                row.set_sending(False)
                if not remembered and row.listen is None and not self.capctl._has_take(row):
                    self._drop_row(row)
                    continue
                if row.app is not None and row.editor is not None and row.listen is not None:
                    # it closed under its open clip editor: nothing new comes in now
                    row.editor.say(_("{name} closed: the clip editor keeps what it heard.",
                                     name=row.app.name), "warn")
                row.set_app(None)
                continue
            appeared = row.app is None
            row.set_app(app)
            if self.capctl._poll_capture(row):   # the capture died: said so, no blind retry
                continue
            cap = row.capture
            if cap is not None and (cap.ended or cap.pid != app.pid):
                rec, row.rec = row.rec, None      # a recording carries on across the restart
                self.capctl._stop_capture(row)    # it closed / restarted / the device changed
                if rec is not None:
                    row.rec = rec
                    if not row.sending and not self.capctl._open_capture(row):
                        self.capctl._finish_rec(row)
            if row.capture is None:
                if remembered and appeared:
                    row.set_sending(True)         # a remembered program just started
                if row.sending:
                    self.capctl._start_capture(row)
                if row.capture is None and row.rec is not None:
                    self.capctl._finish_rec(row)   # reopening failed: nothing feeds the clip
                if row.capture is None and row.listen is not None:
                    self.capctl._open_capture(row)   # the clip editor keeps listening
            elif row.status_text and row.status_error:
                row.set_status("")
        self._label_folders()
        self._layout_apps()
        self._tools_for_rows()
        self._report_active()
        if not self.isVisible():
            self._pace_list()   # the last captured program closed: stop re-reading

    # ------------------------------------------------------------------ big view
    # One card's clip editor gets the whole tab: the other cards hide, the card is as
    # wide as the tab and the waveform as tall as the room left.
    def _set_big(self, row: AppRow, on: bool):
        if on and row.editor is None:
            return
        if on and self.big is not None and self.big is not row and self.big.editor is not None:
            self.big.editor.set_big(False)
        self.big = row if on else None
        self._layout_apps()
        if row.editor is not None:
            row.editor.set_big(on)
        self.grid.max_cols = 1 if on else 0   # the one card shown, the tab's width
        self.card_size.setEnabled(not on)
        self.grid.invalidate()
        self._fit_big()
        if not on:
            self.scroll_area.ensureWidgetVisible(row)

    def _fit_big(self):
        row = self.big
        if row is None or row.editor is None:
            return
        wave = row.editor.wave
        rest = row.sizeHint().height() - max(wave.minimumHeight(), wave.sizeHint().height())
        shelf_h = self.shelf.sizeHint().height() + 12 if self.shelf.isVisible() else 0
        room = self.scroll_area.viewport().height() - rest - shelf_h - 12
        wave.setMinimumHeight(max(WAVE_H, room))
        self.grid.invalidate()
        self.list_layout.activate()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.big is not None:
            QTimer.singleShot(0, self._fit_big)

    # ------------------------------------------------------------------ controls
    def _remember(self, row: AppRow):
        spec = {"vol": row.vol.value(), "monitor": row.chk_hear.isChecked()}
        if row.to != "both":
            spec["to"] = row.to
        if is_path_key(row.key):
            spec["exe"] = row.exe.lower()
            store = self.cfg.apps_paths
        else:
            if row.path:
                spec["path"] = row.path
            store = self.cfg.apps
        store[row.key] = spec
        while len(store) > MAX_REMEMBERED:
            store.pop(next(iter(store)))
        self._save()

    def _unremember(self, key: str) -> dict | None:
        spec = (self.cfg.apps_paths if is_path_key(key) else self.cfg.apps).pop(key, None)
        return spec if isinstance(spec, dict) else None

    def _on_send(self, row: AppRow, on: bool):
        row._label_send()
        if on:
            self.capctl._start_capture(row)
            if row.capture is not None:
                row.remember_pending = True
                self.capctl._poll_capture(row)
        else:
            row.remember_pending = False
            self.capctl._stop_send(row)
            self._unremember(row.key)
            self._save()
            row.btn_forget.setVisible(True)
            if row.app is None:
                self._drop_row(row)
        self._report_active()

    def _on_vol(self, row: AppRow, v: float):
        if row.src is not None:
            row.src.vol = v
        if self._spec(row.key) is not None:
            self._remember(row)

    def _on_to(self, row: AppRow, to: str):
        if row.src is not None:
            _route(row.src, to)
        if self._spec(row.key) is not None:
            self._remember(row)
        self._report_active()

    def _stream_output(self) -> bool:
        """A stream output is set (Also play on → Clean, for streaming)."""
        return bool(self.engine.names.get("obs"))

    def _on_hear(self, row: AppRow, on: bool):
        if row.src is not None:
            row.src.monitor = on
        if self._spec(row.key) is not None:
            self._remember(row)

    def _on_forget(self, row: AppRow):
        """✕: forget what's remembered about the program and take it off the list. A
        running one stays off (cfg.apps_hidden) until it's brought back from the
        Undo bar or *Forgotten programs*."""
        key = row.key
        spec = self._unremember(key) or {}
        running = row.app is not None
        if running and key not in self._hidden():
            self.cfg.apps_hidden.append(key)
        self._save()
        if spec or running:          # something to bring back: keep it in the bin
            name = row.name.text() or row.exe
            item = trash.put_app(row.exe.lower(), spec, name, hidden=running,
                                 path=key if is_path_key(key) else "")
            self._label_bin()
            self.undo_bar.show_for(_("Removed “{name}”", name=name),

                                   lambda: self._undo_forget(item.id))
        self.capctl._stop_send(row)
        self._drop_row(row)
        self._report_active()

    def _undo_forget(self, item_id: str):
        it = trash.take(item_id)
        if it is not None:
            self._unforget(it)

    def show_forgotten(self):
        from soundboard.ui.deleted import DeletedDialog
        self.undo_bar.finish()
        DeletedDialog(trash.APP, "programs", self._unforget, self).exec()
        self._label_bin()

    def _label_bin(self):
        self.btn_bin.setVisible(bool(trash.items(trash.APP)))

    def _unforget(self, item: trash.Item) -> bool:
        """A forgotten program taken out of the bin: remember it again."""
        exe, spec = str(item.data.get("exe", "")).lower(), item.data.get("spec")
        if not exe or not isinstance(spec, dict):
            return False
        key = str(item.data.get("path") or "").lower()
        key = key if is_path_key(key) else exe
        self.cfg.apps_hidden = [e for e in self.cfg.apps_hidden if str(e).lower() != key]
        if not spec:                 # only taken off the list: back on the next listing
            self._save()
            self._label_bin()
            if self._started:
                self.lister.refresh()
            return True
        store = self.cfg.apps_paths if is_path_key(key) else self.cfg.apps
        store[key] = dict(spec)
        while len(store) > MAX_REMEMBERED:
            store.pop(next(iter(store)))
        self._save()
        old = self.rows.get(key)
        app = old.app if old is not None else None
        if old is not None and not old.sending:
            self._drop_row(old)   # built again with the remembered volume
        row = self._row(exe, saved_volume(spec.get("vol", 1.0)), bool(spec.get("monitor")),
                        str(spec.get("to", "both")), key=key,
                        path=key if is_path_key(key) else str(spec.get("path") or ""))
        row.set_app(app)
        self._label_folders()
        self._label_bin()
        if not self._started:
            self.start()
        self._pace_list()
        return True

    def retheme(self):
        for row in self.rows.values():   # a program that isn't running: the placeholder
            row._set_icon(row.app.path if row.app is not None else "", force=True)
