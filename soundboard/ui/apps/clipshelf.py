"""Saved clips (the Apps tab, what the clip editor's Save keeps) and Recordings (the
Voice tab, what Record keeps), stored by soundboard.sounds.clipshelf. One list for both:
each clip is a painted row (ClipRowDelegate) with a round play button, its name,
where it came from and when, its waveform (which fills in as it plays) and its
length. The hovered or picked row gets Play through mic, Add to Sounds and More
buttons. Space (or a double-click) plays it in your headphones, Enter through your
mic, Esc stops, F2 renames, Del deletes (the Undo bar brings it back)."""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from types import SimpleNamespace

import numpy as np
from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QLineEdit, QMenu,
                               QPushButton, QStyle, QToolTip, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from soundboard.sounds.clipshelf import Clip, Shelf, VoiceClip
from soundboard.i18n import _
from soundboard.ui.kit import busy, icons
from soundboard.ui.apps.clipeditor import fmt
from soundboard.ui.kit.panel import CONTROL_H, UndoBar, fold_button
from soundboard.ui.kit.restyled import on_restyle
from soundboard.audio.engine import SR
from soundboard.ui.kit.wheelguard import no_wheel
from soundboard.ui.apps.cliprows import (  # noqa: F401
    _locale_time,
    ACT,
    ACTS_W,
    ClipResizeHandle,
    ClipRowDelegate,
    depth,
    GROUP_H,
    ID,
    INDENT,
    LEN_W,
    length_text,
    LIVE_W,
    NAME_W,
    PLAY_D,
    ROW_H,
    WAVE_W,
    when_text,
)
from soundboard.ui.apps.clipshelfactions import ClipShelfActions

log = logging.getLogger(__name__)

VOICE_W = 760            # the Voice tab's Recordings: at most this wide
ROWS_SHOWN = 5           # the list's height, in rows, before it scrolls
PREVIEW = "clipshelf:preview"   # ":preview": headphones only
SEND = "clipshelf-send"


class ClipShelf(ClipShelfActions, QWidget):
    """The saved clips list. `add_to_sounds(audio, name)` asks the window to make
    one a sound (AppsTab passes it on as clip_ready)."""
    add_to_sounds = Signal(object, str)
    layout_changed = Signal()
    size_changed = Signal()
    cleanup_finished = Signal(object)
    restore_finished = Signal(str, object)
    peaks_ready = Signal()
    error = ""   # set by whoever adds it to Sounds, when it can't

    def __init__(self, engine, cfg, parent=None, voice: bool = False):
        """`voice`: the Voice tab's Recordings (its own folder, newest first, kept
        until deleted)."""
        super().__init__(parent)
        self.engine, self.cfg = engine, cfg
        self.voice = voice
        self._key = "voice" if voice else "app"   # its settings: <key>_clips_expanded...
        self._preview_sid = "voiceclips:preview" if voice else PREVIEW
        self._send_sid = "voiceclips-send" if voice else SEND
        self.shelf = Shelf(VoiceClip if voice else Clip)
        expanded = getattr(cfg, f"{self._key}_clips_expanded")
        self._closed = False
        self._worker = None
        self._peaks_worker: threading.Thread | None = None
        self._items: dict[str, QTreeWidgetItem] = {}
        self._clips: dict[str, Clip] = {}
        self._groups: dict[tuple[str, ...], QTreeWidgetItem] = {}
        self._group_counts: dict[tuple[str, ...], int] = {}
        self._purge_workers: list[threading.Thread] = []
        self._pending: list[Clip] = []
        self._pick = ""
        self._visible_count = 0
        self._playing: tuple[str, str] | None = None   # (engine sid, clip id)
        self._progress = 0.0
        self._hover: QTreeWidgetItem | None = None
        name = _("Recordings") if voice else _("Saved clips")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        # the heading: icon, fold, count; then (Apps) find and group; then ⓘ
        self.head = QWidget(self)   # as wide as the list under it
        head = QHBoxLayout(self.head)
        head.setContentsMargins(4, 0, 0, 0)
        head.setSpacing(8)
        self.body = QWidget(self)
        self.icon = QLabel(self)
        icons.set_label_icon(self.icon, "wave" if voice else "scissors", "section", 16)
        head.addWidget(self.icon)
        self.title = fold_button(name, self.body)
        self.title.setMinimumHeight(CONTROL_H)
        self.title.setAccessibleName(name)
        self.title.setChecked(expanded)
        head.addWidget(self.title)
        self.count = QLabel("0", self)
        self.count.setObjectName("pill")
        head.addWidget(self.count, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addStretch(1)
        self.search = QLineEdit(self)
        self.search.setPlaceholderText(_("Find clips"))
        self.search.setAccessibleName(_("Find clips"))
        icons.clear_button(self.search)
        self.search.setMinimumHeight(CONTROL_H)
        self.search.setMinimumWidth(120)
        self.search.setMaximumWidth(260)
        # how clips are grouped: kept as a (hidden) list of choices, picked from the
        # sort icon's menu
        self.group_by = QComboBox(self)
        self.group_by.setAccessibleName(_("Group clips"))
        for text, key in ((_("By app"), "app"), (_("By day"), "day"),
                          (_("Newest first"), "newest")):
            self.group_by.addItem(text, key)
        self.group_by.setCurrentIndex(max(0, self.group_by.findData(
            "newest" if voice else cfg.app_clip_group)))
        no_wheel(self.group_by)
        self.group_by.hide()
        self.sort = self._icon_button("sort", _("Group clips"))
        self.sort.clicked.connect(self._sort_menu)
        if voice:   # a short list of your own takes, newest first: nothing to find or sort
            self.search.hide()
            self.sort.hide()
        else:
            head.addWidget(self.search)
            head.addWidget(self.sort)
        self.hint = self._icon_button("info", _(
            "Space or a double-click plays it for you, Enter plays it through your mic, "
            "Esc stops, F2 renames, right-click for more."))
        self.hint.clicked.connect(lambda: QToolTip.showText(
            self.hint.mapToGlobal(QPoint(0, self.hint.height())), self.hint.toolTip(),
            self.hint))
        self.hint.setVisible(expanded)
        head.addWidget(self.hint)
        if voice:
            self.head.setMaximumWidth(VOICE_W)
        v.addWidget(self.head)
        v.addWidget(self.body)
        v = QVBoxLayout(self.body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        # kept for the old button row's callers and tests: the rows' buttons do it now
        self.btn_add = QPushButton(_("Add to Sounds"), self)
        self.btn_add.clicked.connect(self.add_picked)
        self.btn_add.hide()
        self.clip_buttons: list[QPushButton] = []
        self.list = QTreeWidget()
        self.list.setObjectName("cliplist")
        self.list.setAccessibleName(name)
        on_restyle(self.list, self._fit)   # (measured in the theme's font: see restyled)
        self.list.setColumnCount(4)   # name, length, from, created: painted as one row
        self.list.setHeaderHidden(True)
        for col in (1, 2, 3):
            self.list.setColumnHidden(col, True)
        self.list.setRootIsDecorated(False)
        self.list.setIndentation(0)
        self.list.setUniformRowHeights(False)
        self.list.setMouseTracking(True)
        self.list.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.EditKeyPressed
                                  | QAbstractItemView.EditTrigger.SelectedClicked)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.delegate = ClipRowDelegate(self)
        self.list.setItemDelegate(self.delegate)
        self.list.itemDoubleClicked.connect(   # on the row, not its play button: plays it
            lambda it, _col: self.toggle_play(it)
            if it.data(0, ID) and self.delegate.double_clicked() else None)
        self.list.itemChanged.connect(self._renamed)
        self.list.itemSelectionChanged.connect(self._sync)
        self.list.currentItemChanged.connect(lambda *_a: self._place_actions())
        self.list.entered.connect(self._entered)
        self.list.verticalScrollBar().valueChanged.connect(lambda _v: self._place_actions())
        self.list.viewport().installEventFilter(self)
        if voice:   # narrow, on the left: a short name doesn't need the whole tab's width
            self.list.setMaximumWidth(VOICE_W)
        self._make_row_actions()
        v.addWidget(self.list)
        self.empty = QLabel(_("No matching clips"))
        self.empty.setObjectName("hint")
        v.addWidget(self.empty)
        self.resize_handle = ClipResizeHandle(self)
        if voice:   # centred under the narrow list, not the tab
            self.resize_handle.setMaximumWidth(VOICE_W)
        v.addWidget(self.resize_handle)
        self.undo_bar = UndoBar(_("Put the clip back in the list"))
        v.addWidget(self.undo_bar)
        for keys, slot in ((Qt.Key.Key_Delete, self.delete_picked),
                           (QKeySequence.StandardKey.Copy, self.copy_picked),
                           (Qt.Key.Key_Space, lambda: self.toggle_play()),
                           (Qt.Key.Key_Return, lambda: self.toggle_play(send=True)),
                           (Qt.Key.Key_Enter, lambda: self.toggle_play(send=True)),
                           (Qt.Key.Key_Escape, self.stop)):
            a = QAction(self.list)
            a.setShortcut(QKeySequence(keys))
            a.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
            a.triggered.connect(slot)
            self.list.addAction(a)
        self._tick = QTimer(self)   # runs only while a clip plays: its progress
        self._tick.setInterval(50)
        self._tick.timeout.connect(self._tick_play)
        self._fill_timer = QTimer(self)
        self._fill_timer.timeout.connect(self._fill_rows)
        self.search.textChanged.connect(lambda: self.reload())
        self.group_by.currentIndexChanged.connect(self._group_changed)
        self.cleanup_finished.connect(self._cleanup_done)
        self.restore_finished.connect(self._restored)
        self.peaks_ready.connect(lambda: self.list.viewport().update())
        self._cleanup_timer = QTimer(self)
        self._cleanup_timer.setInterval(60_000)
        self._cleanup_timer.timeout.connect(self._maintain)
        if not voice:
            self._cleanup_timer.start()
        self.title.toggled.connect(self._fold)
        self.reload()
        QTimer.singleShot(0, self, self._maintain)

    def _icon_button(self, icon: str, tip: str, parent: QWidget | None = None) -> QPushButton:
        """A quiet icon-only button (no background until hover); its words are the
        tooltip and the accessible name."""
        b = QPushButton(parent or self)
        b.setProperty("quiet", True)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setToolTip(tip)
        b.setAccessibleName(tip)
        side = ACT if parent is not None else 30
        b.setFixedSize(side, side)
        icons.set_icon(b, icon, "muted", size=16 if parent is not None else 18)
        return b

    def _make_row_actions(self):
        """The hovered (or picked) row's buttons, over its right end: one set that moves
        from row to row, so every row looks calm at rest."""
        self.row_actions = QWidget(self.list.viewport())
        row = QHBoxLayout(self.row_actions)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        self.row_actions.buttons = {}   # pyright: ignore[reportAttributeAccessIssue]  # (tests)
        for key, icon, tip, fn in (
                ("mic", "live", _("Play through mic"),
                 lambda: self.toggle_play(self._actions_item, send=True)),
                ("add", "plus", _("Add to Sounds"),
                 lambda: (self._only(self._actions_item), self.add_picked())),
                ("more", "more", _("More options"), self._more)):
            b = self._icon_button(icon, tip, self.row_actions)
            b.clicked.connect(lambda _c=False, f=fn: f())
            row.addWidget(b)
            self.row_actions.buttons[key] = b   # pyright: ignore[reportAttributeAccessIssue]
        self.row_actions.setFixedSize(ACTS_W, ACT)
        self.row_actions.hide()
        self._actions_item: QTreeWidgetItem | None = None

    # ------------------------------------------------------------------ layout
    def row_layout(self, rect: QRect, level: int = 0) -> SimpleNamespace:
        """Where each part of a clip's row goes (the delegate paints them, the row's
        buttons sit at `actions`), `level` groups in. The waveform drops out when the
        row is narrow."""
        full = rect
        rect = QRect(rect.x() + INDENT * level, rect.y(), rect.width() - INDENT * level,
                     rect.height())
        x, cy, w = rect.x(), rect.center().y(), rect.width()
        fixed = 8 + PLAY_D + 12 + 12 + LIVE_W + LEN_W + 8 + ACTS_W + 8
        wave_w = WAVE_W if w >= fixed + NAME_W + 16 + 120 else 0
        if wave_w:
            wave_w = min(WAVE_W, w - fixed - NAME_W - 16)
            name_w = NAME_W
        else:
            name_w = max(60, w - fixed)
        play = QRect(x + 8, cy - PLAY_D // 2, PLAY_D, PLAY_D)
        tx = play.right() + 13
        name = QRect(tx, cy - 18, name_w, 20)
        sub = QRect(tx, cy + 1, name_w, 17)
        nx = tx + name_w + 12
        wave = QRect(nx, cy - 12, wave_w, 24) if wave_w else None
        lx = nx + (wave_w + 16 if wave_w else 0)
        live = QRect(lx, cy - 12, LIVE_W, 24)
        length = QRect(lx + LIVE_W, cy - 10, LEN_W, 20)
        actions = QRect(length.right() + 9, cy - ACT // 2, ACTS_W, ACT)
        out = SimpleNamespace(row=rect, play=play, name=name, sub=sub, wave=wave, live=live,
                              length=length, actions=actions)
        if self.list.layoutDirection() == Qt.LayoutDirection.RightToLeft:
            for key, q in vars(out).items():
                if q is not None:
                    setattr(out, key, QStyle.visualRect(Qt.LayoutDirection.RightToLeft,
                                                        full, q))
        return out

    def _entered(self, index):
        it = self.list.itemFromIndex(index)
        self._hover = it if it is not None and it.data(0, ID) else None
        self._place_actions()

    def eventFilter(self, obj, event):
        if obj is self.list.viewport():
            # (with self as the context: dropped if the shelf goes first)
            if event.type() == QEvent.Type.Leave:
                QTimer.singleShot(0, self, self._left)
            elif event.type() == QEvent.Type.Resize:
                QTimer.singleShot(0, self, self._place_actions)
        return super().eventFilter(obj, event)

    def _left(self):
        if self._closed or self.row_actions.underMouse() or self.list.viewport().underMouse():
            return
        self._hover = None
        self._place_actions()

    def _place_actions(self):
        """Put the row buttons on the hovered row, else on the picked one."""
        if self._closed:
            return
        it = self._hover
        if it is None:
            cur = self.list.currentItem()
            it = cur if cur is not None and cur.isSelected() else None
        parent = it.parent() if it is not None else None
        if it is None or not it.data(0, ID) or it.isHidden() or (
                parent is not None and not parent.isExpanded()):
            self.row_actions.hide()
            self._actions_item = None
            return
        rect = self.list.visualItemRect(it)
        if not rect.isValid() or not self.list.viewport().rect().intersects(rect):
            self.row_actions.hide()
            self._actions_item = None
            return
        self._actions_item = it
        self.row_actions.move(self.row_layout(rect, depth(self.list.indexFromItem(it)))
                              .actions.topLeft())
        cid = it.data(0, ID)
        mic = self.row_actions.buttons["mic"]   # pyright: ignore[reportAttributeAccessIssue]
        sending = self._playing == (self._send_sid, cid)
        if mic.property("sending") != sending:   # the accent while it's live
            mic.setProperty("sending", sending)
            icons.set_icon(mic, "live", "accent" if sending else "muted", size=16)
        tip = _("Stop sending") if sending else _("Play through mic")
        mic.setToolTip(tip)
        mic.setAccessibleName(tip)
        self.row_actions.show()
        self.row_actions.raise_()

    def _only(self, it: QTreeWidgetItem | None):
        if it is not None:
            self.list.clearSelection()
            self.list.setCurrentItem(it)

    def _more(self):
        it = self._actions_item
        if it is None:
            return
        if not it.isSelected():
            self._only(it)
        b = self.row_actions.buttons["more"]   # pyright: ignore[reportAttributeAccessIssue]
        self._menu(None, it=it, at=b.mapToGlobal(QPoint(0, b.height())))

    def _sort_menu(self):
        m = QMenu(self)
        for i in range(self.group_by.count()):
            a = m.addAction(self.group_by.itemText(i))
            a.setCheckable(True)
            a.setChecked(i == self.group_by.currentIndex())
            a.triggered.connect(lambda _c=False, n=i: self.group_by.setCurrentIndex(n))
        m.exec(self.sort.mapToGlobal(QPoint(0, self.sort.height())))

    # ------------------------------------------------------------------ list
    def reload(self, pick: str = ""):
        self._fill_timer.stop()
        current = self.list.currentItem()
        pick = pick or (current.data(0, ID) if current is not None else "")
        self.resize_handle._drag = None
        self._hover = None
        self.list.blockSignals(True)
        self.list.clear()
        self._items.clear()
        self._groups.clear()
        self._group_counts.clear()
        self._pick = pick
        self._pending = self.shelf.snapshot()
        self._pending.sort(key=lambda c: c.made, reverse=True)
        self._clips = {c.id: c for c in self._pending}
        self._visible_count = 0
        self.list.blockSignals(False)
        self._fill_rows()
        if self._pending:
            self._fill_timer.start(0)
        self._draw_waveforms()

    @staticmethod
    def _created(c: Clip) -> str:
        try:
            return datetime.fromtimestamp(c.made).strftime("%Y-%m-%d")
        except (ValueError, OverflowError, OSError):
            return ""

    def _group_changed(self):
        if not self.voice:
            self.cfg.app_clip_group = self.group_by.currentData()
        self.size_changed.emit()
        self.reload()

    def _fill_rows(self):
        self.list.blockSignals(True)
        batch, self._pending = self._pending[:100], self._pending[100:]
        query = self.search.text().strip().casefold()
        mode = self.group_by.currentData()
        for c in batch:
            created = self._created(c)
            if query and query not in f"{c.name} {c.src} {created}".casefold():
                continue
            self._visible_count += 1
            it = QTreeWidgetItem([c.name, fmt(c.seconds * SR), c.src, created])
            it.setData(0, ID, c.id)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable)
            it.setToolTip(0, _("{name}\nDouble-click plays it, F2 renames it, right-click "
                               "adds it to your Sounds.", name=c.name))
            self._items[c.id] = it
            labels = ((c.src or _("Other"), created) if mode == "app"
                      else (created, c.src or _("Other")) if mode == "day" else ())
            parent = None
            for depth, label in enumerate(labels):  # noqa: F402  (clipshelf re-exports cliprows.depth)
                key = labels[:depth + 1]
                group = self._groups.get(key)
                if group is None:
                    group = QTreeWidgetItem([label])
                    group.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    if parent is None:
                        self.list.addTopLevelItem(group)
                    else:
                        parent.addChild(group)
                    group.setExpanded(bool(query) or len(self.shelf.clips) <= 100 or depth > 0)
                    self._groups[key] = group
                count = self._group_counts.get(key, 0) + 1
                self._group_counts[key] = count
                group.setText(0, f"{label} ({count})")
                parent = group
            if parent is None:
                self.list.addTopLevelItem(it)
            else:
                parent.addChild(it)
            if c.id == self._pick:
                ancestor = it.parent()
                while ancestor is not None:
                    ancestor.setExpanded(True)
                    ancestor = ancestor.parent()
                self.list.setCurrentItem(it)
                it.setSelected(True)   # picked, with its buttons showing
        self.list.blockSignals(False)
        if not self._pending:
            self._fill_timer.stop()
        self._fit()
        self.resize_handle.setVisible(self._visible_count > 0)
        self.empty.setVisible(not self._pending and self._visible_count == 0)
        self.setVisible(bool(self.shelf.clips))
        self._sync()
        self._place_actions()
        self.layout_changed.emit()

    def _draw_waveforms(self):
        """Older clips have no waveform picture yet: draw them off the UI thread."""
        if self._closed or (self._peaks_worker is not None and self._peaks_worker.is_alive()):
            return
        if all(c.peaks for c in self._clips.values()):
            return

        def work():
            if self.shelf.fill_peaks() and not self._closed:
                busy.emit(self.peaks_ready)
        self._peaks_worker = threading.Thread(target=work, daemon=True, name="clip-waveforms")
        self._peaks_worker.start()

    def _fold(self, expanded):
        setattr(self.cfg, f"{self._key}_clips_expanded", expanded)
        self.hint.setVisible(expanded)
        self.resize_handle._drag = None
        layout = self.layout()
        assert layout is not None
        layout.activate()
        self.updateGeometry()
        self.size_changed.emit()
        self.layout_changed.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_actions()

    def _fit(self):
        """As tall as the rows it shows (up to ROWS_SHOWN)."""
        groups = len(self._groups)
        clips = min(max(self._visible_count, 1), ROWS_SHOWN)
        groups = min(groups, max(0, ROWS_SHOWN - clips + 1))
        m = self.list.contentsMargins()
        self._fit_height = (clips * ROW_H + groups * GROUP_H + m.top() + m.bottom()
                            + 2 * self.list.frameWidth() + 2 + 8)   # + the list's padding
        self._apply_height()

    def _apply_height(self):
        height = getattr(self.cfg, f"{self._key}_clip_height") if self._visible_count else 0
        self.list.setFixedHeight(min(max(int(height), 72), 600) if height else self._fit_height)

    def resize_clips(self, height):
        if not self._visible_count or not self.title.isChecked():
            return
        setattr(self.cfg, f"{self._key}_clip_height",
                min(max(int(height), 72), 600) if height else 0)
        self._apply_height()
        self.layout_changed.emit()
        self.size_changed.emit()

    def _sync(self):
        self.count.setText(str(len(self.shelf.clips)))
        self.btn_add.setEnabled(bool(self._picked()))
        self._place_actions()

    def _picked(self) -> list[Clip]:
        out = []
        clips = {c.id: c for c in self.shelf.snapshot()}
        cur = self.list.currentItem()
        for it in self.list.selectedItems() or ([cur] if cur else []):
            c = clips.get(it.data(0, ID))
            if c is not None:
                out.append(c)
        return out

    def _item(self, cid: str) -> QTreeWidgetItem | None:
        return self._items.get(cid)

    @property
    def clip_error(self) -> str:
        """SoundsController.on_clip says why a clip couldn't become a sound here."""
        return self.error

    @clip_error.setter
    def clip_error(self, text: str):
        self.error = text

    def add(self, data: np.ndarray, name: str, src: str = "") -> Clip:
        c = self.shelf.add(data, name, src)
        self.search.clear()
        self.reload(pick=c.id)
        self.show()
        return c


    def showEvent(self, event):
        super().showEvent(event)
        self._maintain()   # coming back to the Apps tab: drop clips deleted meanwhile


    def shutdown(self):
        self._closed = True
        self._fill_timer.stop()
        self._cleanup_timer.stop()
        self._tick.stop()
        self.undo_bar.finish()
        if self._worker is not None:
            self._worker.join(5)
        if self._peaks_worker is not None:
            self._peaks_worker.join(5)
        for worker in self._purge_workers:
            worker.join(5)
        if self.voice:   # (no expiry: last-use times don't matter; new waveforms do)
            self.stop()
            self.engine.forget(self._send_sid)
            if self.shelf._dirty:
                self._worker = threading.Thread(target=self.shelf.save, daemon=True,
                                                name="recordings-flush")
                self._worker.start()
                self._worker.join(5)
            return
        # Persist the final activity timestamp off the UI thread as well.
        self._worker = threading.Thread(target=lambda: self.shelf.maintain(True),
                                        daemon=True, name="saved-clips-flush")
        self._worker.start()
        self._worker.join(5)
        self.stop()
        self.engine.forget(self._send_sid)
