"""Saved clips (the Apps tab, what the clip editor's Save keeps) and Recordings (the
Voice tab, what Record keeps), stored by soundboard.sounds.clipshelf. One list for both:
each clip is a painted row (ClipRowDelegate) with a round play button, its name,
where it came from and when, its waveform (which fills in as it plays) and its
length. The hovered or picked row gets Play through mic, Add to Sounds and More
buttons. Space (or a double-click) plays it in your headphones, Enter through your
mic, Esc stops, F2 renames, Del deletes (the Undo bar brings it back)."""
from __future__ import annotations

import html
import logging
import threading
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
from PySide6.QtCore import QDate, QEvent, QPoint, QRect, QSize, Qt, QTime, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QFontMetrics, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QLineEdit,
                               QMenu, QPushButton, QStyle, QStyledItemDelegate,
                               QToolTip, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from soundboard.core import errors, usage
from soundboard.ui.kit import theme
from soundboard.sounds.clipshelf import Clip, Shelf, VoiceClip
from soundboard.i18n import _, ngettext
from soundboard.ui.kit import busy, icons
from soundboard.ui.apps import clipeditor
from soundboard.ui.apps.clipeditor import fmt
from soundboard.ui.kit.panel import CONTROL_H, UndoBar, fold_button
from soundboard.ui.kit.restyled import on_restyle
from soundboard.audio.engine import SR
from soundboard.sounds.library import level_gain
from soundboard.ui.kit.wheelguard import no_wheel

log = logging.getLogger(__name__)

VOICE_W = 760            # the Voice tab's Recordings: at most this wide
ROWS_SHOWN = 5           # the list's height, in rows, before it scrolls
ROW_H = 44               # a clip's row
GROUP_H = 30             # a group's label ("Discord (12)")
PREVIEW = "clipshelf:preview"   # ":preview": headphones only
SEND = "clipshelf-send"
ID = Qt.ItemDataRole.UserRole

# a row, left to right (mirrored for right-to-left languages)
PLAY_D = 32              # the round play button
NAME_W = 220             # name and the "where · when" line under it
WAVE_W = 260             # the waveform, when there's room
LIVE_W = 48              # the Live pill (room kept, so the length never jumps)
LEN_W = 44               # "0:03"
ACT = 28                 # one of the row's buttons
ACTS_W = 3 * ACT + 2 * 2
INDENT = 16              # a row inside a group


def length_text(seconds: float) -> str:
    s = max(0, round(seconds))
    return f"{s // 60}:{s % 60:02d}"


def when_text(made: float, today: date | None = None) -> str:
    """"Today 14:02", "Yesterday", then the date."""
    try:
        d = datetime.fromtimestamp(made)
    except (ValueError, OverflowError, OSError):
        return ""
    today = today or date.today()
    if d.date() == today:
        t = QTime(d.hour, d.minute).toString(_locale_time())
        return _("Today {time}", time=t)
    if d.date() == today - timedelta(days=1):
        return _("Yesterday")
    q = QDate(d.year, d.month, d.day)
    return q.toString("d MMM" if d.year == today.year else "d MMM yyyy")


def depth(index) -> int:
    """How many groups a row is inside (the delegate indents it; the tree's own
    indentation is off, so it draws no branch arrows of its own)."""
    d, parent = 0, index.parent()
    while parent.isValid():
        d, parent = d + 1, parent.parent()
    return d


def _locale_time() -> str:
    from PySide6.QtCore import QLocale
    return QLocale().timeFormat(QLocale.FormatType.ShortFormat)


class ClipResizeHandle(QWidget):
    """A mouse and keyboard grip for the saved clips, inside the scrolling page."""

    def __init__(self, shelf):
        super().__init__(shelf)
        self.shelf = shelf
        self.setFixedHeight(20)
        self.setCursor(Qt.CursorShape.SplitVCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        tip = _("Drag to resize saved clips. Double-click to fit the clips.")
        self.setToolTip(tip)
        self.setAccessibleName(tip)
        self._drag = None

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(theme.T["accent"] if self.hasFocus() else theme.T["faint"]), 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        mid = self.width() // 2
        p.drawLine(mid - 16, 10, mid + 16, 10)   # one rounded grip, like a sheet's
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self._drag = (event.globalPosition().y(), self.shelf.list.height())
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag is not None:
            y, height = self._drag
            self.shelf.resize_clips(height + event.globalPosition().y() - y)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag = None

    def mouseDoubleClickEvent(self, event):
        self._drag = None
        self.shelf.resize_clips(0)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.shelf.resize_clips(self.shelf.list.height()
                                    + (36 if event.key() == Qt.Key.Key_Down else -36))
        elif event.key() == Qt.Key.Key_Home:
            self.shelf.resize_clips(0)
        else:
            super().keyPressEvent(event)


class ClipRowDelegate(QStyledItemDelegate):
    """Paints a clip's row (see the module's docstring) and a group's label, and
    handles a click on the round play button."""

    def __init__(self, shelf: ClipShelf):
        super().__init__(shelf.list)
        self.s = shelf
        self.pressed_play = False   # the last press was on a round play button
        self._double = False        # ...and became a double-click: its release does nothing

    def sizeHint(self, option, index):
        return QSize(0, ROW_H if index.data(ID) else GROUP_H)

    # ------------------------------------------------------------------ paint
    def paint(self, p: QPainter, option, index):
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        T = theme.T
        r = QRect(option.rect)
        cid = index.data(ID)
        if not cid:
            self._paint_group(p, option, index, r)
            p.restore()
            return
        c = self.s._clips.get(cid)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        L = self.s.row_layout(r, depth(index))
        if selected or hover:   # neutral, never the accent (DESIGN: lists)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(T["btn_hover" if selected else "card_hi"]))
            p.drawRoundedRect(L.row.adjusted(0, 1, 0, -1), 6, 6)
        now = self.s._playing
        playing = now is not None and now[1] == cid
        sending = now == (self.s._send_sid, cid)
        # the round play button: accent while it plays
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(T["accent"] if playing else T["btn"]))
        p.drawEllipse(L.play)
        glyph = "stop" if playing else "play"
        icons.icon(glyph, "on_accent" if playing else "text_hi").paint(
            p, L.play.adjusted(9, 9, -9, -9))
        # name, then "where · when"
        name_font = QFont(option.font)
        name_font.setBold(True)
        p.setFont(name_font)
        p.setPen(QColor(T["text_hi"]))
        fm = QFontMetrics(name_font)
        name = index.data(Qt.ItemDataRole.DisplayRole) or ""
        align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        p.drawText(L.name, align, fm.elidedText(name, Qt.TextElideMode.ElideRight,
                                                L.name.width()))
        small = QFont(option.font)
        small.setPointSizeF(max(7.5, option.font.pointSizeF() * 0.85))
        p.setFont(small)
        p.setPen(QColor(T["muted"]))
        sub = " · ".join(x for x in ((c.src if c else ""), (when_text(c.made) if c else "")) if x)
        p.drawText(L.sub, align, QFontMetrics(small).elidedText(
            sub, Qt.TextElideMode.ElideRight, L.sub.width()))
        # the waveform: the played part in the accent
        if L.wave is not None and c is not None:
            self._paint_wave(p, L.wave, c.peaks, self.s._progress if playing else 0.0)
        # Live: going out through the mic (a word with the colour, not colour alone)
        if sending:
            pill = L.live.adjusted(0, (L.live.height() - 20) // 2, 0, -(L.live.height() - 20) // 2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(T["accent"]))
            p.drawRoundedRect(pill, 10, 10)
            p.setPen(QColor(T["on_accent"]))
            bold = QFont(small)
            bold.setBold(True)
            p.setFont(bold)
            p.drawText(pill, Qt.AlignmentFlag.AlignCenter, _("Live"))
        # the length, in steady digits
        digits = QFont(small)
        digits.setPointSizeF(option.font.pointSizeF() * 0.95)
        digits.setFeature(QFont.Tag("tnum"), 1)   # same-width digits: 0:11 lines up with 0:03
        p.setFont(digits)
        p.setPen(QColor(T["muted"]))
        p.drawText(L.length, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   length_text(c.seconds) if c else "")
        p.restore()

    def _paint_group(self, p, option, index, r):
        it = self.s.list.itemFromIndex(index)
        open_ = it is not None and it.isExpanded()
        r = self.s.row_layout(r, depth(index)).row
        rtl = self.s.list.layoutDirection() == Qt.LayoutDirection.RightToLeft
        arrow = QRect(r.x() + 6, r.center().y() - 6, 12, 12)
        text = QRect(r.x() + 24, r.y(), r.width() - 28, r.height())
        if rtl:
            arrow = QStyle.visualRect(Qt.LayoutDirection.RightToLeft, r, arrow)
            text = QStyle.visualRect(Qt.LayoutDirection.RightToLeft, r, text)
        icons.icon("fold_open" if open_ else "fold", "muted").paint(p, arrow)
        f = QFont(option.font)
        f.setPointSizeF(max(7.5, option.font.pointSizeF() * 0.85))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(theme.T["muted"]))
        p.drawText(text, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   index.data(Qt.ItemDataRole.DisplayRole) or "")

    def _paint_wave(self, p: QPainter, rect: QRect, peaks: list[float], played: float):
        T = theme.T
        p.setPen(Qt.PenStyle.NoPen)
        if not peaks:   # not drawn yet (an older clip): a flat line until it is
            p.setBrush(QColor(T["faint"]))
            p.drawRoundedRect(QRect(rect.x(), rect.center().y() - 1, rect.width(), 2), 1, 1)
            return
        n = len(peaks)
        step = rect.width() / n
        bar = max(2.0, step * 0.55)
        rtl = self.s.list.layoutDirection() == Qt.LayoutDirection.RightToLeft
        h = rect.height()
        done, rest = QColor(T["accent"]), QColor(T["faint"])
        for i, v in enumerate(peaks):
            bh = max(2.0, float(v) * h)
            x = rect.x() + i * step + (step - bar) / 2
            if rtl:
                x = rect.x() + rect.right() - x - bar
            p.setBrush(done if (i + 0.5) / n <= played else rest)
            p.drawRoundedRect(int(x), int(rect.center().y() - bh / 2), max(2, int(bar)),
                              int(bh), 1, 1)

    # ------------------------------------------------------------------ input
    def editorEvent(self, event, model, option, index):
        kind = event.type()
        if kind not in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
                        QEvent.Type.MouseButtonDblClick):
            return False
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        it = self.s.list.itemFromIndex(index)
        if it is None:
            return False
        pos = event.position().toPoint()
        on_play = bool(index.data(ID)) and self.s.row_layout(
            option.rect, depth(index)).play.contains(pos)
        if kind == QEvent.Type.MouseButtonPress:
            self.pressed_play, self._double = on_play, False
            return False
        if not index.data(ID):   # a group's label: a click folds it
            if kind == QEvent.Type.MouseButtonRelease:
                it.setExpanded(not it.isExpanded())
            return True
        if on_play:
            if kind == QEvent.Type.MouseButtonDblClick:
                self._double = True
            elif not self._double:
                self.s.toggle_play(it)
            return True   # (a double-click on the button isn't a second play)
        return False

    def double_clicked(self) -> bool:
        """A row was double-clicked: False when it was on its play button (the first
        click played it; the rest of the double-click does nothing)."""
        if self.pressed_play:
            self._double = True
            return False
        return True

    def helpEvent(self, event, view, option, index):
        L = self.s.row_layout(option.rect, depth(index))
        if index.data(ID) and L.play.contains(event.pos()):
            playing = self.s._playing == (self.s._preview_sid, index.data(ID))
            QToolTip.showText(event.globalPos(), _("Stop") if playing else _("Play for me"),
                              view)
            return True
        return super().helpEvent(event, view, option, index)

    def updateEditorGeometry(self, editor, option, index):
        L = self.s.row_layout(option.rect, depth(index))
        editor.setGeometry(L.name.adjusted(-4, -3, 4, 3))


class ClipShelf(QWidget):
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
            for depth, label in enumerate(labels):
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

    # ------------------------------------------------------------------ actions
    def _audio(self, c: Clip) -> np.ndarray | None:
        try:
            return c.audio()
        except Exception as e:  # noqa: BLE001 - the file went missing or is damaged
            log.warning("can't read clip %s: %s", c.file, e)
            errors.warn(self, _("Couldn't open that clip"), e)
            return None

    def _count(self, what: str):
        """For the usage count: the Voice tab's recordings or the Apps tab's saved clips,
        and what was done to one (the action's name only)."""
        usage.used(f"{'voice-rec' if self.voice else 'saved-clip'}-{what}")

    def _gain(self, data) -> float:
        return level_gain(data) if getattr(self.cfg, "level_volumes", True) else 1.0

    def toggle_play(self, it: QTreeWidgetItem | None = None, send: bool = False):
        it = it or self.list.currentItem()
        cid = it.data(0, ID) if it is not None else None
        sid = self._send_sid if send else self._preview_sid
        again = self._playing == (sid, cid) and self.engine.state(sid) is not None
        self.stop()
        c = self.shelf.get(cid) if cid else None
        if again or c is None or not cid:
            return
        data = self._audio(c)
        if data is None or not len(data):
            return
        if self.engine.play(sid, data, self._gain(data), mode="restart",
                            preview=not send) is None:
            busy.toast(self, html.escape(
                _("Nowhere to send it: pick where your sounds go on the Setup tab.") if send
                else _("No headphones to play it in: pick them on the Setup tab.")), "error")
            return
        self._count("mic" if send else "play")
        self._playing = (sid, cid)
        self._progress = 0.0
        self.shelf.touch(cid)
        self._tick.start()
        self._repaint(cid)

    def _tick_play(self):
        playing = self._playing
        if playing is None or self._closed:
            self._tick.stop()
            return
        state = self.engine.state(playing[0])
        if state is None:   # it finished
            self._playing = None
            self._tick.stop()
        else:
            self._progress = float(state[0])
        self._repaint(playing[1])

    def _repaint(self, cid: str | None):
        it = self._items.get(cid) if cid else None
        if it is not None:
            self.list.viewport().update(self.list.visualItemRect(it))
        self._place_actions()

    def stop(self):
        if self._playing is not None:
            cid = self._playing[1]
            self.engine.stop(self._playing[0])
            self._playing = None
            self._tick.stop()
            self._repaint(cid)

    def _renamed(self, it: QTreeWidgetItem, col: int):
        if col != 0:
            return
        cid = it.data(0, ID)
        c = self.shelf.get(cid)
        if c is None:
            return
        if not self.shelf.rename(cid, it.text(0)):
            self.list.blockSignals(True)
            it.setText(0, c.name)   # empty: back to what it was
            self.list.blockSignals(False)

    def rename(self, it: QTreeWidgetItem | None = None):
        it = it or self.list.currentItem()
        if it is not None:
            self.list.editItem(it, 0)

    def add_picked(self):
        added = 0
        for c in self._picked():
            data = self._audio(c)
            if data is None:
                continue
            self.error = ""
            self.add_to_sounds.emit(data, c.name)
            if self.error:
                errors.warn(self, _("Couldn't add it to your Sounds"), self.error)
                return
            added += 1
            self.shelf.touch(c.id)
        if added:
            self._count("add")
            self.undo_bar.finish()
            busy.toast(self, ngettext("Added {n} clip to your Sounds",
                                      "Added {n} clips to your Sounds", added), "ok")

    def copy_picked(self):
        picked = self._picked()
        if not picked:
            return
        data = self._audio(picked[0])
        if data is not None:
            self._count("copy")
            clipeditor.set_clipboard(data)
            self.shelf.touch(picked[0].id)
            busy.toast(self, _("Copied “{name}”: Ctrl+V pastes it in an editor or on the "
                               "Sounds tab", name=html.escape(picked[0].name)), "ok")

    def delete_picked(self):
        picked = self._picked()
        for c in picked:
            if self._playing is not None and self._playing[1] == c.id:
                self.stop()
        gone = self.shelf.remove_many({c.id for c in picked})
        if not gone:
            return
        self._count("delete")

        def undo():
            self.shelf.restore_many(gone)
            self.reload(pick=gone[0][1].id)
        what = (_("Deleted “{name}”", name=gone[0][1].name) if len(gone) == 1
                else ngettext("Deleted {n} clip", "Deleted {n} clips", len(gone)))
        self.undo_bar.show_for(what, undo)
        self.reload()

    def _menu(self, pos, it: QTreeWidgetItem | None = None, at: QPoint | None = None):
        if it is None:
            it = self.list.itemAt(pos)
        if it is None or not it.data(0, ID):
            return
        if not it.isSelected():
            self.list.setCurrentItem(it)
        m = QMenu(self)
        cid = it.data(0, ID)
        playing_sid = (self._playing[0] if self._playing is not None and self._playing[1] == cid
                       else None)

        def act(text, slot, icon=None, keys=None):
            a = m.addAction(text)
            if icon:
                a.setIcon(icons.icon(icon))
            if keys:
                a.setShortcut(QKeySequence(keys))   # shown only: the list's own keys do it
            a.triggered.connect(slot)
            return a
        act(_("Stop") if playing_sid == self._preview_sid else _("Play for me"),
            lambda: self.toggle_play(it), "headphones", Qt.Key.Key_Space)
        act(_("Stop sending") if playing_sid == self._send_sid else _("Play through mic"),
            lambda: self.toggle_play(it, send=True), "live", Qt.Key.Key_Return)
        m.addSeparator()
        act(_("Add to Sounds"), self.add_picked, "sounds")
        act(_("Rename"), lambda: self.rename(it), "edit", Qt.Key.Key_F2)
        act(_("Copy"), self.copy_picked, "copy", QKeySequence.StandardKey.Copy)
        m.addSeparator()
        act(_("Delete"), self.delete_picked, "trash", Qt.Key.Key_Delete)
        m.exec(at if at is not None else self.list.viewport().mapToGlobal(pos))

    def _maintain(self):
        # the Voice tab's recordings never expire: nothing to tidy, no worker thread
        if self.voice or self._closed or (self._worker is not None
                                          and self._worker.is_alive()):
            return
        keep = self.voice or self.cfg.app_clips_keep_forever or self.undo_bar.active()
        playing = self._playing
        active = (playing[1] if playing is not None
                  and self.engine.state(playing[0]) is not None else None)
        def work():
            try:
                gone = self.shelf.maintain(keep, active)
            except OSError:
                log.exception("saved clips maintenance failed")
                return
            busy.emit(self.cleanup_finished, gone)
        self._worker = threading.Thread(target=work, daemon=True, name="saved-clips-cleanup")
        self._worker.start()

    def showEvent(self, event):
        super().showEvent(event)
        self._maintain()   # coming back to the Apps tab: drop clips deleted meanwhile

    def _cleanup_done(self, gone):
        if self._closed:
            return
        if self.shelf.pruned:
            self.shelf.pruned = False
            if not gone:
                self.reload()
        if not gone:
            return
        def undo():
            self._restore_background(gone)
        if self.voice or self.cfg.app_clips_keep_forever or self.undo_bar.active():
            undo()
            return
        self.reload()
        self.undo_bar.show_for(_("Removed inactive clips: {n}", n=len(gone)), undo,
                              done=lambda: self._discard(gone))

    def _restore_background(self, gone):
        def work():
            error = None
            try:
                self.shelf.restore_many(gone)
            except OSError as e:
                error = e
            busy.emit(self.restore_finished, gone[0][1].id, error)
        self._worker = threading.Thread(target=work, daemon=True, name="saved-clips-restore")
        self._worker.start()

    def _restored(self, pick, error):
        if self._closed:
            return
        self.reload(pick=pick)
        if error is not None:
            busy.toast(self, html.escape(_("Couldn't save it: {error}",
                                          error=errors.plain(error))), "error")

    def _discard(self, gone):
        worker = threading.Thread(target=lambda: self.shelf.discard_files(gone),
                                  daemon=True, name="saved-clips-delete")
        self._purge_workers = [t for t in self._purge_workers if t.is_alive()]
        self._purge_workers.append(worker)
        worker.start()

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
