"""The Store tab: free sounds anyone can add to their board (soundboard.online.store), the best
voted first, in categories, and a way to share your own. Sounds the server brings in from
Myinstants are links like any shared one: played and added from that site.

Nothing goes online until the tab is first opened. Every call runs on a worker thread
and comes back through busy.emit, so a closed tab or window never gets a late answer.

A sound's card is storerow.py, the *Share a sound* window storeshare.py; how the tab fits
its width (storefit.py) and playing from it (storeplay.py) are StoreTab's mixins."""
from __future__ import annotations

import html
import logging
import threading
import time
from collections.abc import Callable

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu,
                               QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from soundboard.core import achievements, usage
from soundboard.ui.kit import wheelguard
from soundboard.online import net, store
from soundboard.i18n import _
from soundboard.ui.kit import busy, icons
from soundboard.ui.store import storelook
from soundboard.ui.kit.panel import hint_label, icon_button, section_label
from soundboard.ui.store.storefit import CARD_GAP, LIST_GAP, CutCombo, StoreFit
from soundboard.ui.store.storeplay import StorePlay
from soundboard.ui.store.storerow import SoundRow, count_text
from soundboard.ui.store.storeshare import ShareDialog, error_text
# (callers import these from here too)
from soundboard.ui.store.storefit import CARD_MIN_W, ONE_ROW  # noqa: F401
from soundboard.ui.store.storerow import COUNT_W, _blocked, meta_line  # noqa: F401
from soundboard.ui.store.storeshare import _title  # noqa: F401

log = logging.getLogger(__name__)

PREVIEW = "__store_preview"   # the store's "hear it first" voice (headphones only)
SEARCH_WAIT_MS = 400          # typing pauses this long before the store is searched
LINK_TICK_MS = 250            # how often the cards look at what the player is doing
KEEP_S = 300                  # a list (and the categories) shown again this long without asking
# the Sounds dropdown's first two (every sound, in an order): the order -> its key there
TOPS = {"trending": "@trending", "top": "@top", "new": "@new"}
# ... then Community uploads (the store's own sounds, store.OURS), then a line and the categories
TOP_ROWS = len(TOPS) + 1


class StoreTab(StoreFit, StorePlay, QWidget):
    """The Store tab. `add_file(path)` adds a fetched sound to the board; `play(data,
    gain)` plays one to the headphones only (None stops it) and says whether it could;
    `open_privacy()` opens Settings > Privacy & security."""
    clip_ready = Signal(object, str)   # (the window wires every tab's; never sent here)
    active_changed = Signal(bool)
    _listed = Signal(int, object, bool, str)     # worker -> UI: (serial, sounds, more, error)
    _fetched = Signal(object, object, str)       # (row, (what, path), error): "play" / "add"
    _voted = Signal(object, object, str)         # (row, (up, down, mine) or None, error)
    _decoded = Signal(object, object, float, int)   # (row, data, gain, serial)
    _cats = Signal(object)                       # [(category, how many)], all; None: failed

    def __init__(self, cfg, add_file: Callable[[str], None],
                 play: Callable[[object, float], bool], open_privacy: Callable[[], object],
                 save: Callable[[], None] = lambda: None,
                 link: Callable[[str, str, str], None] = lambda url, name, kind: None,
                 voices=None, link_state: Callable[[str], str] = lambda url: ""):
        super().__init__()
        self.cfg = cfg
        self.voices = voices   # ui.storevoices.VoiceHooks: the Voices list (None: Sounds only)
        self._mode = "sounds"  # or "voices": community voices instead of sounds
        self._kind = ""        # the Voices list's kind ("" all)
        self._save = save
        # (url, name, kind): the window's link downloader and player. "now" plays it over
        # a link that's playing, "play" after it, "add"; "pause" (or resume) and "stop"
        self._link = link
        self._link_state = link_state   # a link's state in the player (SoundRow.link_look)
        self._add_file = add_file
        self.used = 0   # Play or Add pressed here (its first-visit tour waits on it)
        self._play = play
        self._open_privacy = open_privacy
        self._closed = False
        self._serial = 0          # the newest list asked for (older answers are dropped)
        self._hear_serial = 0
        self._loaded = False
        self._off = False   # showing "The store is off"
        self._offset = 0
        self._rows: list[SoundRow] = []
        self._need: tuple[int, int] | None = None   # (_card_needs)
        self._playing: SoundRow | None = None
        self._busy: set[tuple[str, str]] = set()   # (sound id, "play" / "add" / "vote")
        self._listed.connect(self._on_listed)
        self._fetched.connect(self._on_fetched)
        self._voted.connect(self._on_voted)
        self._decoded.connect(self._on_decoded)
        self._cats.connect(self._on_cats)
        self._link_tick = QTimer(self, interval=LINK_TICK_MS)   # (while the tab shows)
        self._link_tick.timeout.connect(self._follow_links)
        net.on_change(self._net_changed)   # Settings > Privacy's switch, Offline mode
        self._cat = ""            # the category picked ("" all)
        self._have_cats = False   # the categories came (the dropdown has more than its tops)
        # the lists already had, by (mode, order, search, category, kind): (when, items,
        # more), so switching back shows one at once; Refresh asks again
        self._kept: dict[tuple, tuple[float, list, bool]] = {}
        self._kept_cats: tuple[float, object] | None = None

        # the whole tab's width, as the Sounds tab: a wide window gets more cards a row
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(12)
        # still new: a green Beta tag right after the title
        beta = QLabel(_("Beta"))
        beta.setObjectName("pill")
        beta.setProperty("tone", "beta")
        beta.setToolTip(_("The sound store is new and still changing."))
        # the banner: Bun in his headphones, the title big, what the store is under it
        head = self.banner = storelook.StoreBanner()
        hv = QVBoxLayout(head)
        hv.setContentsMargins(14, 12, 14, 14)
        hv.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(12)
        self.bun = storelook.make_bun(72)
        top.addWidget(self.bun, 0, Qt.AlignmentFlag.AlignVCenter)
        words = QVBoxLayout()
        words.setSpacing(2)
        words.addStretch(1)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.title = QLabel(_("Community"))
        self.title.setObjectName("storetitle")
        # the kit's display size (a whole page's title); a style sheet, as the theme's
        # QLabel font would win over setFont
        self.title.setStyleSheet("font-size: 17pt; font-weight: 800; background: transparent;")
        title_row.addWidget(self.title)
        title_row.addWidget(beta, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch(1)
        words.addLayout(title_row)
        # (one line for Sounds and Voices: the same words as the tab's tooltip)
        self.tagline = hint_label(_("Sounds and voices players share, voted on by everyone: "
                                    "add them to your board or share your own"))
        words.addWidget(self.tagline)
        words.addStretch(1)
        top.addLayout(words, 1)
        hv.addLayout(top)
        # the toolbar: Sounds or Voices, the search, the category, Share and Refresh. One
        # row in a wide tab; two in a narrow one, so the card fits the smallest window
        # (wider, a narrow window became the mini player)
        self.mode_btns: dict[str, QPushButton] = {}
        self.modes_box = QWidget()
        modes = QHBoxLayout(self.modes_box)
        modes.setContentsMargins(0, 0, 0, 0)
        modes.setSpacing(4)
        if voices is not None:
            for key, text, icon in (("sounds", _("Sounds"), "sounds"),
                                    ("voices", _("Voices"), "voice")):
                b = QPushButton(text)
                b.setCheckable(True)
                b.setAutoExclusive(True)
                b.setChecked(key == "sounds")
                icons.set_icon(b, icon, "text", "on_accent")
                b.clicked.connect(lambda _c=False, k=key: self.set_mode(k))
                modes.addWidget(b)
                self.mode_btns[key] = b
        else:
            self.modes_box.hide()
        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Search sounds"))
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName(_("Search sounds"))
        self.search.setMinimumWidth(120)
        self._search_wait = QTimer(self, singleShot=True, interval=SEARCH_WAIT_MS)
        self._search_wait.timeout.connect(self.reload)
        self.search.textChanged.connect(lambda _t: self._search_wait.start())
        # the sounds' categories (or the voices' kinds), each with how many
        self.cat_pick = CutCombo()
        self.cat_pick.setAccessibleName(_("Category"))
        self.cat_pick.setToolTip(_("Category"))
        self.cat_pick.setPlaceholderText(_("All categories"))   # every sound, by Added
        self.cat_pick.activated.connect(self._cat_picked)
        self.btn_share = QPushButton(_("Share a sound"))
        self.btn_share.setObjectName("primary")
        self._share_words = True   # (a narrow tab: its icon only, the words its tooltip)
        icons.set_icon(self.btn_share, "upload", "on_accent", "on_accent")
        self.btn_share.clicked.connect(lambda: self.share_voice() if self._mode == "voices"
                                       else self.share())
        self.btn_reload = icon_button("reload", _("Refresh"))
        self.btn_reload.clicked.connect(lambda: self.reload(fresh=True))
        # (in a box that only asks for the two rows' width: asking for one row's, a
        # narrow tab could never get narrow enough to switch to two)
        self.toolbar = QWidget()
        self.toolbar.setObjectName("storebar")   # (theme.py: Share greyed out while down)
        tv = QVBoxLayout(self.toolbar)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(10)
        self._bars = (QHBoxLayout(), QHBoxLayout())
        for bar in self._bars:
            bar.setSpacing(8)
            tv.addLayout(bar)
        hv.addWidget(self.toolbar)
        self._one_row: bool | None = None
        self._cat_short: list[str] = []   # the dropdown's names it always has room for
        self._lay_toolbar(False)
        col.addWidget(head)
        self._sort = "trending"   # the default (the dropdown picks Most liked)

        # the list, or a message in its place (loading, nothing found, off, failed)
        self.stack = QStackedWidget()
        scroll = self.list_area = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # Tab goes straight to the cards' buttons
        scroll.viewport().installEventFilter(self)   # resized: the columns line up again
        body = QWidget()
        self._list = QVBoxLayout(body)
        self._list.setContentsMargins(0, 0, LIST_GAP, 0)   # cards end before the scroll bar
        self._list.setSpacing(CARD_GAP)
        self._grid = QGridLayout()   # the cards: as many a row as fit (_fit_columns)
        self._grid.setSpacing(CARD_GAP)
        self._cols = 0
        self._list.addLayout(self._grid)
        self._fill_cats([])
        self.btn_more = QPushButton(_("Show more"))
        self.btn_more.clicked.connect(self.more)
        self.btn_more.hide()
        self._list.addWidget(self.btn_more, 0, Qt.AlignmentFlag.AlignHCenter)
        self._list.addStretch(1)
        scroll.setWidget(body)
        self.stack.addWidget(scroll)
        self.message = QWidget()
        mv = QVBoxLayout(self.message)
        mv.setContentsMargins(12, 8, 12, 8)
        mv.setSpacing(6)
        mv.addStretch(1)
        self.msg_icon = QLabel()
        self.msg_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mv.addWidget(self.msg_icon)
        self.msg_title = section_label("")
        self.msg_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mv.addWidget(self.msg_title)
        self.msg_text = hint_label("")
        self.msg_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mv.addWidget(self.msg_text)
        br = QHBoxLayout()
        br.addStretch(1)
        self.msg_btn = QPushButton()
        self.msg_btn.clicked.connect(self._message_action)
        br.addWidget(self.msg_btn)
        br.addStretch(1)
        mv.addLayout(br)
        mv.addStretch(2)
        self._msg_do: Callable[[], object] | None = None
        self.stack.addWidget(self.message)
        # the list couldn't be had (the store's down, no connection): sad Bun says so
        from soundboard.ui.kit import oops
        self.oops = oops.OopsPanel()
        self.oops_page = oops.centred(self.oops)
        self.stack.addWidget(self.oops_page)
        self.failed = False   # the list couldn't be had (the tab's tour asks, tabtours.py)
        col.addWidget(self.stack, 1)
        self.note = QLabel()   # the last action's result, for screen readers and tests
        self.note.hide()

    def install(self) -> str:
        """This install's store id (made, and saved, the first time)."""
        new = not getattr(self.cfg, "store_id", "")
        sid = store.install_id(self.cfg)
        if new:
            self._save()
        return sid

    # ------------------------------------------------------------------ the main window
    def start(self):
        pass

    def stop(self):
        self._stop_preview()

    def stop_all(self):
        self._stop_preview()

    def is_active(self) -> bool:
        return False

    def retheme(self):
        self._need = None   # (another style's padding: the cards measured again)
        QTimer.singleShot(0, self, lambda: self._fit_columns(force=True))

    def shutdown(self):
        self._closed = True
        self._search_wait.stop()
        self._link_tick.stop()
        self._stop_preview()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_buns()
        self._fit_toolbar()

    def _fit_buns(self):
        """The banner's Bun when there's room (`fits`), never while the red card's sad
        Bun is out (one Bun at a time)."""
        self.bun.setVisible(storelook.fits(self.width(), self.height())
                            and not getattr(self, "failed", False))

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Type.Resize and obj is self.list_area.viewport():
            self._fit_columns()
            self._hold_rows()
        return super().eventFilter(obj, e)

    def showEvent(self, e):
        super().showEvent(e)
        # nothing goes online until the tab is first opened; switched back on in
        # Settings meanwhile, the list comes when it's shown again
        if not self._loaded or (self._off and net.allowed(store.FEATURE)):
            self._loaded = True
            QTimer.singleShot(0, self, self.reload)
        self._link_tick.start()

    def _net_changed(self):
        QTimer.singleShot(0, self, self._follow_switch)   # (any thread)

    def _follow_switch(self):
        """Switched off while a list loads, its cut connection's late failure said
        "Couldn't open the store": say it's off at once (and drop that answer). Back
        on, the list comes again if the tab is showing."""
        if self._closed or not self._loaded:
            return
        on = net.allowed(store.FEATURE)
        if not on and not self._off or on and self._off and self.isVisible():
            back = on and self._off
            self.reload()
            if back:   # (the list just went to "Loading": say why it came back)
                busy.toast(self, _("✓ The store is on again: loading it."), "ok",
                           key="store-switch")

    def hideEvent(self, e):
        self._stop_preview()   # another tab: the sample stops (a link plays on)
        self._link_tick.stop()
        super().hideEvent(e)

    # ------------------------------------------------------------------ the list
    def _sort_key(self) -> str:
        return self._sort

    def set_sort(self, key: str):
        """Trending (popular right now, the default), Votes (the best voted first, "top")
        or Added (the newest first, "new")."""
        self._sort = key if key in ("top", "new") else "trending"
        self._show_picked(self._cat)
        self.reload()

    def _pick_top(self, key: str):
        """The dropdown's first three: every sound, Trending, Most liked ("top") or
        Newest ("new")."""
        self._cat = ""
        self.set_sort(key)

    def set_cat(self, key: str):
        """Only one category's sounds ("" all of them)."""
        self._cat = key if key in store.CATS else ""
        self._show_picked(self._cat)
        self.reload()

    def _show_picked(self, key: str):
        if not key and self._mode == "sounds":   # every sound: the top that matches the order
            key = TOPS.get(self._sort, "")
        i = self.cat_pick.findData(key)
        if i >= 0 or not key:
            self.cat_pick.setCurrentIndex(i)

    def _cat_picked(self, i: int):
        key = self.cat_pick.itemData(i) or ""
        if self._mode == "voices":
            self.set_kind(key)
        elif key in TOPS.values():
            sort = next(k for k, v in TOPS.items() if v == key)
            if sort != "trending":
                usage.used(f"store-sort-{sort}")
            self._pick_top(sort)
        else:
            if key:
                usage.used("store-category")
            self.set_cat(key)

    def set_mode(self, mode: str):
        """Sounds or Voices: the list, its chips and the Share button change with it."""
        self._mode = "voices" if mode == "voices" and self.voices is not None else "sounds"
        if self._mode in self.mode_btns:
            self.mode_btns[self._mode].setChecked(True)
        voices = self._mode == "voices"
        self._share_look()
        self.search.setPlaceholderText(_("Search the voices") if voices
                                       else _("Search sounds"))
        self._show_cats()
        self.reload()

    def set_kind(self, kind: str):
        """Only one kind of voice ("" all of them)."""
        self._kind = kind if kind in ("fx", "ai", "setup") else ""
        self._show_picked(self._kind)
        self.reload()

    def _show_cats(self):
        """The dropdown's choices: the sounds' categories, or the voices' kinds."""
        if self._mode == "sounds":
            self._fill_cats([])
            self._fetch_cats()
            return
        from soundboard.ui.store.storevoices import kind_chips
        self._fill_cats([(key, text, storelook.KIND_ICON.get(key, storelook.ALL_ICON))
                         for key, text in kind_chips() if key])
        self._show_picked(self._kind)

    def _fill_cats(self, items: list[tuple[str, str, str]]):
        """The sounds: Trending, Most liked and Newest (every sound), Community uploads (only
        the sounds shared here, none brought in from other sites), then (key, text, icon name)
        for each category. The voices: "All categories", then each kind."""
        self.cat_pick.clear()
        if self._mode == "sounds":
            items = [(TOPS["trending"], _("Trending"), "flame"),
                     (TOPS["top"], _("Most liked"), "like"),
                     (TOPS["new"], _("Newest"), "history"),
                     (store.OURS, _("Community uploads"), storelook.CAT_ICON[store.OURS]),
                     *items]
        else:
            items = [("", _("All categories"), storelook.ALL_ICON), *items]
        # (the voices' kinds are short: room for them all)
        self._cat_short = [t for _k, t, _i in items[:len(TOPS) if self._mode == "sounds" else None]]
        for key, text, _icon in items:
            self.cat_pick.addItem(text, key)
        names = [i for _k, _t, i in items]
        if self._mode == "sounds" and len(items) > TOP_ROWS:
            # a line under the orders: "Most liked" read like one more category
            self.cat_pick.insertSeparator(TOP_ROWS)
            names.insert(TOP_ROWS, "")
        icons.set_item_icons(self.cat_pick, names)
        self._show_picked(self._kind if self._mode == "voices" else self._cat)
        wheelguard.snug_combo(self.cat_pick)
        # the list as wide as its longest name (+ padding and scroll bar), never cut off
        view = self.cat_pick.view()
        view.setMinimumWidth(view.sizeHintForColumn(0) + 40)
        if self._one_row is not None:   # (its width changed: still room for one row?)
            self._fit_toolbar()

    def _fetch_cats(self):
        kept = self._kept_cats
        if kept is not None and time.monotonic() - kept[0] < KEEP_S:
            self._on_cats(kept[1])
            return
        install = self.install()

        def run():
            try:
                got = store.categories(install)
                self._kept_cats = (time.monotonic(), got)
                busy.emit(self._cats, got)
            except Exception as e:  # noqa: BLE001 - the list says why; the chips just wait
                log.info("couldn't read the store's categories: %s", e)
                busy.emit(self._cats, None)
        threading.Thread(target=run, daemon=True, name="store-cats").start()

    def _on_cats(self, got):
        if self._closed:
            return
        self._share_look()
        if got is None or self._mode != "sounds":
            return
        cats, _total = got
        self._have_cats = True
        # the biggest first; the name, then how many in brackets (a bare number after
        # the name read as part of it: "Memes 7")
        self._fill_cats([(key, f"{store.cat_name(key)} ({count_text(n)})",
                          storelook.CAT_ICON.get(key, storelook.ALL_ICON))
                         for key, n in sorted(cats, key=lambda c: -c[1])
                         if key != store.OURS])   # (it's up with the orders)
        self._show_picked(self._cat)

    def _say(self, icon: str, title: str, text: str, button: str = "",
             do: Callable[[], object] | None = None):
        """The page in place of the list: `icon` over a title, a line and a button
        (a list that couldn't be had: `_problem`)."""
        self.failed = False
        self.msg_icon.setPixmap(icons.pixmap(icon, 44, icons.resolve("muted")))
        self._fit_buns()
        # Bun's down when the store can't show anything, fine while it loads
        self.bun.sad = 0.0 if icon == "store" and not button else 0.7
        self.msg_title.setText(title)
        self.msg_text.setText(text)
        self.msg_text.setVisible(bool(text))
        self.msg_btn.setText(button)
        self.msg_btn.setVisible(bool(button))
        self._msg_do = do
        self.stack.setCurrentWidget(self.message)

    def _problem(self, title: str, line: str, fixable: bool = True):
        """The list couldn't be had (the store's down, no connection): the red card in
        its place, Try again reloads. `fixable=False`: the server's down, nothing for
        the user to do but wait."""
        self.failed = True
        self._fit_buns()
        self.oops.show_problem(title, html.escape(line, quote=False),
                               lambda: self.reload(fresh=True),
                               fixable=fixable)
        self.stack.setCurrentWidget(self.oops_page)

    def _message_action(self):
        if self._msg_do is not None:
            self._msg_do()

    def reload(self, fresh: bool = False):
        """The list again from the top (the search, the order or the category changed,
        Refresh). One had in the last few minutes is shown again as it was; `fresh`
        (Refresh, Try again) asks the store for everything again."""
        self._search_wait.stop()
        self._offset = 0
        if fresh:
            self._kept.clear()
            self._kept_cats = None
            if self._have_cats and self._mode == "sounds":   # (their counts too)
                self._fetch_cats()
        self._fetch_list(replace=True)

    def _list_key(self) -> tuple:
        return (self._mode, self._sort_key(), self.search.text().strip(), self._cat, self._kind)

    def more(self):
        self._fetch_list(replace=False)

    def _fetch_list(self, replace: bool):
        if self._closed:
            return
        self._off = not net.allowed(store.FEATURE)
        if self._off:
            self._serial += 1   # a list still on its way would say "Couldn't open" over this
            busy.set_busy(self.btn_more, False)
            self._clear()
            self._say("offline", _("The store is off"), net.off_message(store.FEATURE),
                      _("Privacy && security settings"), self._open_privacy)
            return
        key = self._list_key()
        kept = self._kept.get(key) if replace else None
        if kept is not None and time.monotonic() - kept[0] < KEEP_S:
            self._serial += 1
            busy.set_busy(self.btn_more, False)
            self._on_listed(self._serial, (True, list(kept[1]), False, None), kept[2], "")
            return
        self._serial += 1
        serial, sort, query, offset, cat = (self._serial, self._sort_key(), self.search.text(),
                                            0 if replace else self._offset, self._cat)
        install, voices, kind = self.install(), self._mode == "voices", self._kind
        if replace:
            self._say("store", _("Loading the store…"), "")
            if not self._have_cats and not voices:
                self._fetch_cats()
        else:
            busy.set_busy(self.btn_more, True)

        def run():
            try:
                if voices:
                    from soundboard.online import storevoices
                    found, more = storevoices.browse(install, kind, sort, query, offset)
                else:
                    found, more = store.browse(install, sort, query, offset, cat)
                busy.emit(self._listed, serial, (replace, found, False, key), more, "")
            except Exception as e:  # noqa: BLE001 - offline, switched off, the server…
                log.info("couldn't read the store: %s", e)
                busy.emit(self._listed, serial,
                          (replace, None, e if isinstance(e, store.StoreDown) else None, None),
                          False,
                          error_text(e))
        threading.Thread(target=run, daemon=True, name="store-list").start()

    def _on_listed(self, serial: int, got, more: bool, err: str):
        if self._closed or serial != self._serial:
            return
        replace, found, down, key = got
        busy.set_busy(self.btn_more, False)
        self._share_look()
        if found is None:
            if replace and down:
                usage.used("store-maintenance" if down.back else "store-down")
                self._clear()
                self._problem(*store.down_words(down.back), fixable=False)
            elif replace:
                self._clear()
                self._problem(_("Couldn't open the store"), err)
            else:
                busy.toast(self.window(), html.escape(err), "error")
            return
        if key is not None:   # (None: shown from _kept)
            now = time.monotonic()
            self._kept = {k: v for k, v in self._kept.items() if now - v[0] < KEEP_S}
            had = None if replace else self._kept.get(key)
            self._kept[key] = ((had[0], had[1] + list(found), more) if had
                               else (now, list(found), more))
        if replace:
            self._clear()
        self._offset += len(found)
        from soundboard.online.storevoices import Voice
        from soundboard.ui.store.storevoices import VoiceRow
        for s in found:
            if isinstance(s, Voice):
                r = VoiceRow(s, self)
                r.set_where("", s.created)   # (its kind starts its second line)
            else:
                r = SoundRow(s, self)
                r.set_where(store.cat_name(s.cat), s.created)
            self._rows.append(r)
        self.btn_more.setVisible(more)
        if not self._rows:
            if self.search.text().strip():
                self._say("search", _("Nothing matches"), _("Try other words."))
            elif self._mode == "voices" and self._kind:
                self._say("search", _("Nothing matches"), "", _("All"), lambda: self.set_kind(""))
            elif self._mode == "voices":
                if store.is_down():   # (no Share button while it's down)
                    self._say("voice", _("No voices here yet"), store.down_share())
                else:
                    self._say("voice", _("No voices here yet"),
                              _("Be the first: share a voice you made."), _("Share a voice"),
                              self.share_voice)
            elif self._cat:   # a way back to All, right here
                self._say("search", _("Nothing matches"), "", _("All"), lambda: self.set_cat(""))
            else:
                if store.is_down():   # (no Share button while it's down)
                    self._say("store", _("No sounds here yet"), store.down_share())
                else:
                    self._say("store", _("No sounds here yet"),
                              _("Be the first: share a sound you made."), _("Share a sound"),
                              self.share)
            return
        self.bun.sad = 0.0
        self.failed = False
        self._fit_buns()
        self.stack.setCurrentWidget(self.list_area)
        self._fit_columns(force=True)
        self._follow_links()
        if replace:   # a new list starts at its top (_hold_rows may have moved it)
            QTimer.singleShot(0, self, self._to_top)

    def _to_top(self):
        """(Where the list is now is where _hold_rows keeps it from here on.)"""
        self.list_area.verticalScrollBar().setValue(0)
        self._list_top = self.list_area.viewport().mapTo(self.window(), QPoint(0, 0)).y()

    def _clear(self):
        self._stop_preview()
        for r in self._rows:
            self._grid.removeWidget(r)
            r.deleteLater()
        self._rows.clear()
        self._cols = 0
        self.btn_more.hide()

    def _row_alive(self, row: SoundRow) -> bool:
        return not self._closed and row in self._rows

    # ------------------------------------------------------------------ hear and add
    def _get(self, row: SoundRow, what: str):
        """Fetch the row's file (once), then play or add it."""
        key = (row.sound.id, what)
        if key in self._busy:
            return
        self._busy.add(key)
        s = row.sound

        def run():
            try:
                busy.emit(self._fetched, row, (what, str(store.fetch(s))), "")
            except Exception as e:  # noqa: BLE001 - never a crash
                log.info("couldn't fetch store sound %s: %s", s.id, e)
                busy.emit(self._fetched, row, (what, ""), error_text(e))
        threading.Thread(target=run, daemon=True, name="store-fetch").start()

    def _on_fetched(self, row: SoundRow, got, err: str):
        what, path = got
        self._busy.discard((row.sound.id, what))
        if not self._row_alive(row):
            return
        if what == "add":
            busy.set_busy(row.btn_add, False)
        if not path:
            if what == "play":
                self._stop_preview()
            busy.toast(self.window(), html.escape(_("Couldn't get “{name}”: {error}",
                                                    name=row.sound.name, error=err)), "error")
            return
        if what == "add":
            usage.used("store-added")
            self.bun.cheer()
            self._add_file(path)   # (the window says "Added …" itself)
        else:
            self._decode(row, path)

    def add(self, row: SoundRow):
        self.used += 1
        if self._is_voice(row):
            assert self.voices is not None   # (only listed with them)
            said = self.voices.take(row.sound)
            usage.used("store-voice-added")
            busy.toast(self.window(), html.escape(said), "ok")
            return
        if row.sound.is_link:   # downloaded from its site, as a pasted link is
            usage.used("store-added")
            self.bun.cheer()
            self._link(row.sound.link, row.sound.name, "add")
            return
        if (row.sound.id, "add") in self._busy:
            return
        busy.set_busy(row.btn_add, True)
        self._get(row, "add")

    # ------------------------------------------------------------------ votes and reports
    def vote(self, row: SoundRow, value: int):
        s = row.sound
        if (s.id, "vote") in self._busy:
            row.show_votes()   # (a click while one is on its way: shown as it was)
            return
        value = 0 if s.mine == value else value   # the same thumb again takes it back
        old = (s.up, s.down, s.mine)
        # shown at once; the store's answer puts in the real counts
        s.up += (value == 1) - (s.mine == 1)
        s.down += (value == -1) - (s.mine == -1)
        s.mine = value
        row.show_votes()
        if value == 1:
            self.bun.burst(4)
        self._busy.add((s.id, "vote"))
        install = self.install()

        def run():
            try:
                if self._is_voice(row):
                    from soundboard.online import storevoices
                    busy.emit(self._voted, row, storevoices.vote(install, s.id, value), "")
                else:
                    busy.emit(self._voted, row, store.vote(install, s.id, value), "")
            except Exception as e:  # noqa: BLE001
                busy.emit(self._voted, row, old, error_text(e))
        threading.Thread(target=run, daemon=True, name="store-vote").start()

    def _on_voted(self, row: SoundRow, counts, err: str):
        self._busy.discard((row.sound.id, "vote"))
        for _t, items, _m in self._kept.values():   # the same sound in the other lists kept
            for s in items:
                if s.id == row.sound.id and s is not row.sound:
                    s.up, s.down, s.mine = counts
        if not self._row_alive(row):
            return
        row.sound.up, row.sound.down, row.sound.mine = counts
        row.show_votes()
        if err:
            busy.toast(self.window(), html.escape(_("Your vote didn't go through: {error}",
                                                    error=err)), "error")
        else:
            usage.used("store-voted")
            achievements.voted(row.sound.id, row.sound.mine)

    def report_menu(self, row: SoundRow):
        m = QMenu(self)
        m.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        reasons = ((("offensive", _("It's offensive")), ("broken", _("It doesn't work")),
                    ("other", _("Something else"))) if self._is_voice(row) else
                   (("copyright", _("It's someone else's sound")),
                    ("offensive", _("It's offensive")),
                    ("broken", _("It doesn't play")),
                    ("other", _("Something else"))))
        for key, text in reasons:
            m.addAction(text, lambda k=key: self.report(row, k))
        m.popup(row.btn_report.mapToGlobal(row.btn_report.rect().bottomLeft()))

    def report(self, row: SoundRow, reason: str):
        s, install = row.sound, self.install()

        voice = self._is_voice(row)

        def run():
            try:
                if voice:
                    from soundboard.online import storevoices
                    storevoices.report(install, s.id, reason)
                else:
                    store.report(install, s.id, reason)
                busy.emit(self._voted, row, (s.up, s.down, s.mine), "")
            except Exception as e:  # noqa: BLE001
                busy.emit(self._voted, row, (s.up, s.down, s.mine), error_text(e))
        busy.toast(self.window(), html.escape(_("Thanks: the voice will be checked.") if voice
                                              else _("Thanks: the sound will be checked.")), "ok")
        threading.Thread(target=run, daemon=True, name="store-report").start()

    # ------------------------------------------------------------------ sharing
    def share(self, link: str = "", name: str = ""):
        """The Share a sound window; with `link`, on that link (a sound of yours that
        was downloaded from it)."""
        if not net.allowed(store.FEATURE):
            busy.toast(self.window(), html.escape(net.off_message(store.FEATURE)), "error")
            return
        if store.is_down():
            busy.toast(self.window(), html.escape(store.down_share()), "warn")
            return
        dlg = ShareDialog(self.install(), self, link, name)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.show()

    def share_voice(self, pick: str = ""):
        """The Share a voice window (`pick`: the one picked first, as its list shows it)."""
        if self.voices is None:
            return
        if not net.allowed(store.FEATURE):
            busy.toast(self.window(), html.escape(net.off_message(store.FEATURE)), "error")
            return
        from soundboard.ui.store.storevoices import open_share
        dlg = open_share(self, self.install(), self.voices, pick)
        if dlg is not None:
            dlg.accepted.connect(lambda: self._mode == "voices" and self.reload(fresh=True))


