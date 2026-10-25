"""The Apps tab's cards (ui/apps/appspanel.py): one ``AppRow`` per program (icon and name,
its level, Send, Record, the Clip editor's scissors, the window's eye, call / stream
choice, volume), the category headings and the ``AppGrid`` that lays them out per
category, the ``_Lister`` that reads the programs off the UI thread, and the small
helpers for remembering programs by .exe and folder (path_key)."""
from __future__ import annotations

import logging
import time

from PySide6.QtCore import QEvent, QMimeData, QRect, Qt, Signal
from PySide6.QtGui import (QActionGroup, QColor, QDrag, QFont, QKeySequence, QPainter, QShortcut)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QHBoxLayout, QLabel,
                               QMenu, QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from soundboard.audio import appaudio
from soundboard.ui.kit import theme
from soundboard.sounds.clipedit import LiveBuffer
from soundboard.i18n import _
from soundboard.audio.recorder import ArmedRecorder
from soundboard.ui.kit import icons
from soundboard.ui.apps.clipeditor import ClipEditor
from soundboard.ui.kit.panel import CardGrid, HoverCard, VolumeControl, icon_button
from soundboard.ui.apps.windowview import WindowView
from soundboard.ui.kit.wheelguard import no_wheel
from soundboard.ui.kit.pixels import snap_to_pixels
from soundboard.ui.kit.plaintext import plain_tip
from soundboard.ui.apps.applister import (  # noqa: F401
    _Lister,
    _VERSION_DIR,
    HIDDEN_FULL_S,
    is_path_key,
    MAX_VOL,
    path_key,
    saved_volume,
)
from soundboard.ui.apps.approwparts import AppRowParts

log = logging.getLogger(__name__)

# where a sent program goes (cfg.apps[exe]["to"], cfg.apps_paths[path]["to"]): the
# choice shows once a stream output is set (Also play on → Clean, for streaming), or
# while it's set to anything but both
TO = (("both", _("Call + stream"), _("Others in the call and your stream output both get it")),
      ("call", _("Call only"), _("Only others in the call get it, not your stream output")),
      ("stream", _("Stream only"), _("Only your stream output gets it (music for your "
                                     "viewers), not the call")))
TO_KEYS = tuple(k for k, *__ in TO)

# Exact executable names: a web page's title never decides its browser's category.
APP_CATEGORIES = {
    "Browsers": ("chrome", "msedge", "firefox", "brave", "opera", "vivaldi", "chromium",
                 "waterfox", "librewolf", "zen", "arc", "iexplore"),
    "Music & media": ("spotify", "vlc", "wmplayer", "music.ui", "video.ui", "itunes",
                      "foobar2000", "winamp", "aimp", "mpv", "mpc-hc", "mpc-hc64",
                      "mpc-be", "mpc-be64", "plex", "jellyfinmediaplayer", "audacity",
                      "obs64", "obs32", "potplayermini", "potplayermini64"),
    "Calls & chat": ("discord", "discordcanary", "discordptb", "slack", "teams",
                     "ms-teams", "zoom", "skype", "telegram", "signal", "whatsapp",
                     "element", "mumble", "ts3client_win64", "ts3client_win32"),
    "Games": ("steam", "steamwebhelper", "epicgameslauncher", "battle.net", "riotclientux",
              "minecraft", "minecraft.windows", "robloxplayerbeta", "fortniteclient-win64-shipping",
              "valorant-win64-shipping", "cs2", "dota2", "rocketleague", "overwatch",
              "league of legends", "r5apex", "gta5", "eldenring", "wow", "terraria"),
}
APP_DRAG_MIME = "application/x-onionboard-app-card"
CATEGORY_DRAG_MIME = "application/x-onionboard-app-category"


def category_label(category: str) -> str:
    """A category's shown name: the built-in ones in the app's language, the user's own
    as typed. The config keeps the English name (usage.APPS_BUILT_IN), so a board
    switched to another language, or opened by an older version, still finds them."""
    return {"Browsers": _("Browsers"), "Music & media": _("Music & media"),
            "Calls & chat": _("Calls & chat"), "Games": _("Games"),
            "Other": _("Other")}.get(category, category)


def app_category(exe: str) -> str:
    stem = exe.replace("\\", "/").rsplit("/", 1)[-1].lower().removesuffix(".exe")
    return next((category for category, names in APP_CATEGORIES.items() if stem in names),
                "Other")


class AppCategoryHeading(QLabel):
    reordered = Signal(str, str, bool)    # (source_cat, target_cat, before)
    card_dropped = Signal(object, str)    # (AppRow, target_cat)
    rename_requested = Signal(str)        # (category)
    delete_requested = Signal(str)        # (category)

    def __init__(self, category: str, host: QWidget, custom: bool = False):
        super().__init__(category_label(category), host)
        self.category = category
        self.custom = custom
        self._drag_press = None
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)
        # the keyboard's way to the same menu, as on the cards (DESIGN section 0):
        # Tab reaches the heading (a click doesn't: it's the drag handle), then the
        # Menu key or Shift+F10 opens it under the name
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        for keys in (QKeySequence(Qt.Key.Key_Menu), QKeySequence("Shift+F10")):
            sc = QShortcut(keys, self)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(lambda: self._show_menu(self.rect().bottomLeft()))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_press = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_press = None
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_press is not None and event.buttons() & Qt.MouseButton.LeftButton:
            dist = (event.globalPosition().toPoint() - self._drag_press).manhattanLength()
            if dist >= QApplication.startDragDistance():
                self._drag_press = None
                drag = QDrag(self)
                mime = QMimeData()
                mime.setData(CATEGORY_DRAG_MIME, self.category.encode("utf-8"))
                drag.setMimeData(mime)
                pixmap = self.grab()
                drag.setPixmap(pixmap)
                drag.exec(Qt.DropAction.MoveAction)
                return
        super().mouseMoveEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(CATEGORY_DRAG_MIME):
            src_cat = bytes(event.mimeData().data(CATEGORY_DRAG_MIME)).decode("utf-8")
            if src_cat != self.category:
                event.setDropAction(Qt.DropAction.MoveAction)
                event.accept()
                return
        elif event.mimeData().hasFormat(APP_DRAG_MIME):
            source = event.source()
            if isinstance(source, AppRow) and source.category != self.category:
                event.setDropAction(Qt.DropAction.MoveAction)
                event.accept()
                return
        event.ignore()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, event):
        if event.mimeData().hasFormat(CATEGORY_DRAG_MIME):
            src_cat = bytes(event.mimeData().data(CATEGORY_DRAG_MIME)).decode("utf-8")
            if src_cat != self.category:
                before = event.position().y() < self.height() / 2
                self.reordered.emit(src_cat, self.category, before)
                event.setDropAction(Qt.DropAction.MoveAction)
                event.accept()
                return
        elif event.mimeData().hasFormat(APP_DRAG_MIME):
            source = event.source()
            if isinstance(source, AppRow):
                self.card_dropped.emit(source, self.category)
                event.setDropAction(Qt.DropAction.MoveAction)
                event.accept()
                return
        event.ignore()

    def _show_menu(self, pos):
        menu = QMenu(self)
        menu.addAction(icons.icon("edit"), _("Rename category"),
                       lambda: self.rename_requested.emit(self.category))
        if self.custom:
            menu.addSeparator()
            menu.addAction(icons.icon("trash", "danger_text"), _("Delete category"),
                           lambda: self.delete_requested.emit(self.category))
        menu.exec(self.mapToGlobal(pos))

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        snap_to_pixels(painter)
        if self.hasFocus():   # the focus ring: the rule under it in the accent, solid
            painter.fillRect(0, self.height() - 2, self.width(), 2,
                             QColor(theme.T.get("accent", "#7c5cff")))
            return
        painter.setOpacity(0.25)
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()


class AppGrid(CardGrid):
    """One responsive card grid per category, with a heading above each populated group."""

    def __init__(self, host, categories: list[str] | None = None, **kwargs):
        super().__init__(**kwargs)
        self.host = host
        default_cats = (*APP_CATEGORIES, "Other")
        if categories:
            self.category_order = [c for c in categories if c]
            for cat in default_cats:
                if cat not in self.category_order:
                    self.category_order.append(cat)
        else:
            self.category_order = list(default_cats)

        self.custom_categories = set(self.category_order) - set(default_cats)
        self.headings: dict[str, AppCategoryHeading] = {}
        self.listed = False   # the list view: one program a row, the tab's width
        self._tab_key: list[int] = []   # the shown order the Tab chain was last set to
        for category in self.category_order:
            self._create_heading(category)

    def _create_heading(self, category: str) -> AppCategoryHeading:
        is_custom = category in self.custom_categories
        label = AppCategoryHeading(category, self.host, custom=is_custom)
        label.setContentsMargins(0, 0, 0, 6)
        font = label.font()
        font.setWeight(QFont.Weight.DemiBold)
        label.setFont(font)
        label.hide()
        self.headings[category] = label
        return label

    def add_category(self, category: str) -> AppCategoryHeading | None:
        if category in self.category_order:
            return None
        self.custom_categories.add(category)
        if "Other" in self.category_order:
            idx = self.category_order.index("Other")
            self.category_order.insert(idx, category)
        else:
            self.category_order.append(category)
        label = self._create_heading(category)
        self._sync_headings_order()
        self.invalidate()
        return label

    def remove_category(self, category: str):
        if category not in self.category_order:
            return
        self.custom_categories.discard(category)
        self.category_order.remove(category)
        heading = self.headings.pop(category, None)
        if heading:
            heading.hide()
            heading.deleteLater()
        self.invalidate()

    def rename_category(self, old: str, new: str):
        if old not in self.category_order or not new or new in self.category_order:
            return
        idx = self.category_order.index(old)
        self.category_order[idx] = new
        if old in self.custom_categories:
            self.custom_categories.remove(old)
            self.custom_categories.add(new)
        heading = self.headings.pop(old, None)
        if heading:
            heading.category = new
            heading.setText(category_label(new))
            self.headings[new] = heading
        self._sync_headings_order()
        self.invalidate()

    def reorder_categories(self, source: str, target: str, before: bool):
        if (source == target or source not in self.category_order
                or target not in self.category_order):
            return
        self.category_order.remove(source)
        idx = self.category_order.index(target) + (not before)
        self.category_order.insert(idx, source)
        self._sync_headings_order()
        self.invalidate()

    def _sync_headings_order(self):
        new_headings = {}
        for cat in self.category_order:
            if cat in self.headings:
                new_headings[cat] = self.headings[cat]
        self.headings = new_headings

    def columns(self, width: int) -> int:
        return 1 if self.listed else super().columns(width)

    def _place(self, rect: QRect, move: bool) -> int:
        shown = [item for item in self._items if not item.isEmpty()]
        cols = self.columns(rect.width())
        width = max(1, (rect.width() - self._gap * (cols - 1)) // cols)
        y = rect.y()
        seq: list[QWidget] = []   # headings and cards as shown, for the Tab order
        for category in self.category_order:
            heading = self.headings.get(category)
            if heading is None:
                continue
            group = [item for item in shown if item.widget().category == category]
            is_visible = bool(group) or (category in self.custom_categories)
            if move:
                heading.setVisible(bool(is_visible) and not self.max_cols)
            if not is_visible:
                continue
            seq += [heading, *(item.widget() for item in group)]
            if y != rect.y():
                y += self._gap
            if not self.max_cols:   # the clip editor's big view needs all the space
                height = heading.sizeHint().height() + 4
                if move:
                    heading.setGeometry(QRect(rect.x(), y, rect.width(), height))
                y += height + self._gap
            for i in range(0, len(group), cols):
                line = group[i:i + cols]
                heights = [max(item.heightForWidth(width) if item.hasHeightForWidth()
                               else item.sizeHint().height(), item.minimumSize().height())
                           for item in line]
                if move:
                    for j, item in enumerate(line):
                        item.setGeometry(QRect(rect.x() + j * (width + self._gap), y,
                                               width, heights[j]))
                y += max(heights) + self._gap
        if move and not self.max_cols:
            self._sync_tab_order(seq)
        return max(0, y - self._gap - rect.y())

    def _sync_tab_order(self, seq: list[QWidget]):
        """Tab goes a heading, its cards, the next heading... as shown. The headings are
        made before any card, so by default Tab visited them all first."""
        key = [id(w) for w in seq]
        if key == self._tab_key:
            return
        self._tab_key = key
        chain = []
        for w in seq:
            if isinstance(w, AppCategoryHeading):
                chain.append(w)
                continue
            # a card's controls in the order they were made, read fresh: a list kept
            # on the card held widgets Qt had since deleted (a spin box's line edit),
            # and setTabOrder raising inside this layout pass broke PySide
            # (overridepin.py). Not a drop-down's list: that's a window of its own.
            chain += [c for c in w.findChildren(QWidget)
                      if c.focusPolicy() & Qt.FocusPolicy.TabFocus
                      and c.window() is w.window()]
        for a, b in zip(chain, chain[1:]):
            QWidget.setTabOrder(a, b)


class ElidedLabel(QLabel):
    """A one-line label that ends in "…" when it doesn't fit (the full text in its
    tooltip), instead of being cut off mid-word. With `hide_overflow` it shows nothing
    instead: for interface text half a phrase only looks broken."""

    def __init__(self, text: str = "", hide_overflow: bool = False):
        super().__init__(text)
        self.hide_overflow = hide_overflow

    def paintEvent(self, e):
        text = self.text()
        r = self.contentsRect()
        shown = self.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, r.width())
        if shown != text and self.hide_overflow:
            shown = ""
        tip = plain_tip(text) if shown != text else ""   # (sound names: web / board text)
        if tip != self.toolTip():   # every paint (meters, hover): only when it changes
            self.setToolTip(tip)
        p = QPainter(self)
        snap_to_pixels(p)
        p.setPen(self.palette().color(self.foregroundRole()))
        p.drawText(r, int(self.alignment() | Qt.AlignmentFlag.AlignVCenter), shown)


def _route(src, to: str):
    """Point a sent program (engine.AuxSource) at the call, the stream or both."""
    src.live = to in ("both", "call")
    src.stream = to in ("both", "stream")


class AppRow(AppRowParts, HoverCard):
    """One program, as a card: icon and name, its level, Send and Record, volume and
    Hear it myself."""
    send_toggled = Signal(object, bool)     # row, on
    rec_toggled = Signal(object, bool)
    vol_changed = Signal(object, float)
    hear_toggled = Signal(object, bool)
    to_changed = Signal(object, str)        # row, one of TO_KEYS
    clip_toggled = Signal(object, bool)     # row, the clip editor opened / closed
    forget = Signal(object)
    reordered = Signal(object, object, bool)   # source, target, insert before
    move_to_category = Signal(object, str)

    def __init__(self, exe: str, meter_cls, vol: float = 1.0, hear: bool = False,
                 to: str = "both", key: str = "", path: str = "", category: str = ""):
        super().__init__()
        self.exe = exe
        self.key = key or exe.lower()   # AppsTab.rows' key: the .exe, or a path_key
        self.path = path                # path_key of the program it is ("" not known yet)
        self.category = category or app_category(exe)
        self._drag_press = None
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_card_menu)
        # the keyboard's way to the same menu (DESIGN section 0: never right-click
        # only): the Menu key or Shift+F10 on anything in the card
        for keys in (QKeySequence(Qt.Key.Key_Menu), QKeySequence("Shift+F10")):
            sc = QShortcut(keys, self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(self._menu_from_keyboard)
        self.folder = ""                # shown after the name: two programs share it
        self.app: appaudio.App | None = None
        self.known_name = ""            # the program's own name, once it has been seen
        self.last_sound_at = time.monotonic()
        self.capture: appaudio.AppCapture | None = None
        self.remember_pending = False   # Send clicked: remembered once the capture is up
        self.src = None                 # engine.AuxSource while sending
        self.rec: ArmedRecorder | None = None   # while Record is on
        self.listen: LiveBuffer | None = None   # while the clip editor is open
        self.editor: ClipEditor | None = None   # made the first time it's opened
        self.status_text = ""
        self.status_error = False
        v = self._v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(8)
        self.header = QWidget()
        self.header.setCursor(Qt.CursorShape.OpenHandCursor)
        top = self._top = QHBoxLayout(self.header)
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(10)
        self.icon = QLabel()
        self.icon.setFixedSize(28, 28)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(self.icon)
        names = QVBoxLayout()
        names.setSpacing(1)
        self.name = ElidedLabel(exe)
        bold = self.name.font()   # not a style sheet: each one re-styles the widget
        bold.setWeight(QFont.Weight.DemiBold)
        self.name.setFont(bold)
        self.sub = ElidedLabel()
        self.sub.setObjectName("hint")
        for lbl in (self.name, self.sub):   # long titles give way instead of widening the card
            lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            lbl.setTextFormat(Qt.TextFormat.PlainText)   # window titles are set by web pages
        names.addWidget(self.name)
        names.addWidget(self.sub)
        top.addLayout(names, 1)
        for label in (self.header, self.icon, self.name, self.sub):
            label.setCursor(Qt.CursorShape.OpenHandCursor)
            label.installEventFilter(self)
        self.btn_forget = QPushButton()
        self.btn_forget.setObjectName("small")
        self.btn_forget.setToolTip(_("Take this program off the list"))
        icons.close_button(self.btn_forget, 28)
        self.btn_forget.clicked.connect(lambda: self.forget.emit(self))
        top.addWidget(self.btn_forget, 0, Qt.AlignmentFlag.AlignTop)
        v.addWidget(self.header)
        self.meter = meter_cls()
        self.meter.setMinimumWidth(60)
        v.addWidget(self.meter)
        self.buttons_w = QWidget()
        buttons = QHBoxLayout(self.buttons_w)
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(6)
        self.btn_send = QPushButton()
        self.btn_send.setObjectName("live")
        self.btn_send.setCheckable(True)
        self.btn_send.setToolTip(_("Send this program's sound out to others, the way your "
                                   "sounds go (Setup tab)"))
        icons.set_icon(self.btn_send, "live", checked_color="on_live")
        self.btn_send.toggled.connect(lambda on: self.send_toggled.emit(self, on))
        self.btn_rec = QPushButton(_("Record"))
        self.btn_rec.setObjectName("rec")
        self.btn_rec.setCheckable(True)
        self.btn_rec.setToolTip(_("Record this program to Saved clips. Click again to finish. "
                                  "Nobody hears it unless Send is on."))
        icons.set_icon(self.btn_rec, "record", "danger_text", "#ffffff", size=14)
        self.btn_rec.toggled.connect(lambda on: self.rec_toggled.emit(self, on))
        for b in (self.btn_send, self.btn_rec):
            # as wide as their words
            b.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            buttons.addWidget(b)
        # the eye: a small live picture of the program's window, under the volume
        # (only programs with a window have one)
        self.btn_view = icon_button("eye", _("Show this program's window"))
        self.btn_view.setCheckable(True)
        icons.set_icon(self.btn_view, "eye", checked_color="accent")
        buttons.addWidget(self.btn_view)
        # the scissors: the clip editor folds out under the card (a full-size button,
        # not a small link at the bottom)
        self.btn_clip = icon_button("scissors", _("This program's last minute as a waveform: "
                                                   "pick a bit out of it and keep it as a "
                                                   "clip. It only listens while it's open."))
        self.btn_clip.setCheckable(True)
        icons.set_icon(self.btn_clip, "scissors", checked_color="accent")
        self.btn_clip.toggled.connect(lambda on: self.clip_toggled.emit(self, on))
        buttons.addWidget(self.btn_clip)
        self.cb_to = QComboBox(self)   # hidden/shown before its row is laid out: no flash
        for i, (key, label, tip) in enumerate(TO):
            self.cb_to.addItem(label, key)
            self.cb_to.setItemData(i, tip, Qt.ItemDataRole.ToolTipRole)
        self.cb_to.setToolTip(_("Where this program's sound goes when Send is on"))
        self.cb_to.setCurrentIndex(TO_KEYS.index(to) if to in TO_KEYS else 0)
        self.cb_to.currentIndexChanged.connect(lambda _i: self.to_changed.emit(self, self.to))
        no_wheel(self.cb_to)
        self.cb_to.setVisible(self.to != "both")
        buttons.addWidget(self.cb_to)
        buttons.addStretch(1)
        v.addWidget(self.buttons_w)
        self.mix_w = QWidget()
        mix = QHBoxLayout(self.mix_w)
        mix.setContentsMargins(0, 0, 0, 0)
        mix.setSpacing(8)
        self.vol = VolumeControl(vol, tip=_("This program's volume in the mix"))
        self.vol.slider.setMaximumWidth(16777215)   # the card's width, not a row's sliver
        self.vol.changed.connect(lambda v: self.vol_changed.emit(self, v))
        mix.addWidget(self.vol, 1)
        self.chk_hear = QCheckBox(_("Hear it myself"), self)
        self.chk_hear.setToolTip(_("Also play it into your headphones (off: the program "
                                   "already plays there on its own)"))
        self.chk_hear.setChecked(hear)
        self.chk_hear.toggled.connect(lambda on: self.hear_toggled.emit(self, on))
        self.chk_hear.hide()   # optional duplicate monitoring lives in the card menu
        v.addWidget(self.mix_w)
        self.listed = False
        self._as_line = False    # laid out on one line (the list view, room enough)
        self._line = QWidget(self)   # the list view's one row
        self._line_lay = QHBoxLayout(self._line)
        self._line_lay.setContentsMargins(0, 0, 0, 0)
        self._line_lay.setSpacing(12)
        self._line.hide()
        self.view = WindowView(self)
        self.btn_view.toggled.connect(self._on_view)
        v.addWidget(self.view)
        self._tight = 0   # how many of _TIGHTEN are applied (a narrow window)
        self._label_send()
        self.set_app(None)


    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_press = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_press = None
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_press is not None and event.buttons() & Qt.MouseButton.LeftButton:
            distance = (event.globalPosition().toPoint() - self._drag_press).manhattanLength()
            if distance >= QApplication.startDragDistance():
                self._start_drag()
                return
        super().mouseMoveEvent(event)

    def eventFilter(self, obj, event):
        if obj in (self.header, self.icon, self.name, self.sub):
            if (event.type() == QEvent.Type.MouseButtonPress
                    and event.button() == Qt.MouseButton.LeftButton):
                self._drag_press = event.globalPosition().toPoint()
                return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_press = None
                return True
            if (event.type() == QEvent.Type.MouseMove and self._drag_press is not None
                    and event.buttons() & Qt.MouseButton.LeftButton):
                distance = (event.globalPosition().toPoint() - self._drag_press).manhattanLength()
                if distance >= QApplication.startDragDistance():
                    self._start_drag()
                return True
        return super().eventFilter(obj, event)

    def _start_drag(self):
        self._drag_press = None
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(APP_DRAG_MIME, self.key.encode("utf-8"))
        drag.setMimeData(mime)
        drag.setPixmap(self.grab().scaledToWidth(min(self.width(), 240),
                                                 Qt.TransformationMode.SmoothTransformation))
        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event):
        source = event.source()
        if (event.mimeData().hasFormat(APP_DRAG_MIME) and isinstance(source, AppRow)
                and source is not self and source.parentWidget() is self.parentWidget()):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            self._hover(True)
        else:
            event.ignore()

    dragMoveEvent = dragEnterEvent

    def dragLeaveEvent(self, event):
        self._hover(False)
        event.accept()

    def dropEvent(self, event):
        self.dragEnterEvent(event)
        if event.isAccepted():
            self.reordered.emit(event.source(), self, event.position().x() < self.width() / 2)
        self._hover(False)

    def _menu_from_keyboard(self):
        """Under the focused control (Send, the volume…), or mid-card."""
        f = QApplication.focusWidget()
        at = (f.mapTo(self, f.rect().bottomLeft()) if f is not None and self.isAncestorOf(f)
              else self.rect().center())
        self._show_card_menu(at)

    def _show_card_menu(self, pos):
        menu = QMenu(self)
        parent = self.parentWidget()
        from soundboard.ui.apps.appspanel import AppsTab  # (it imports this module)
        while parent and not isinstance(parent, AppsTab):
            parent = parent.parentWidget()
        if parent:
            # one category per program: the one it's in is ticked (it was greyed out)
            cat_menu = menu.addMenu(icons.icon("tag"), _("Categories"))
            group = QActionGroup(cat_menu)
            for cat in parent.grid.category_order:
                act = cat_menu.addAction(icons.icon("tag", checked_color="accent"),
                                         category_label(cat).replace("&", "&&"))
                act.setCheckable(True)
                act.setChecked(cat == self.category)
                group.addAction(act)
                if cat != self.category:
                    act.triggered.connect(lambda _x=False, _c=cat:
                                          self.move_to_category.emit(self, _c))
            menu.addSeparator()
        monitor = menu.addAction(_("Hear it myself"))
        monitor.setCheckable(True)
        monitor.setChecked(self.chk_hear.isChecked())
        monitor.setToolTip(self.chk_hear.toolTip())
        monitor.toggled.connect(self.chk_hear.setChecked)
        menu.setToolTipsVisible(True)
        gone = menu.addAction(icons.icon("trash", "danger_text"), _("Remove"),
                              lambda: self.forget.emit(self))
        gone.setToolTip(_("Take this program off the list"))
        menu.exec(self.mapToGlobal(pos))
