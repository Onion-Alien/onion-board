"""Settings window: themes, every global hotkey in one place, the in-game overlay,
general options."""
from __future__ import annotations

import html
import logging
import threading
import time

from PySide6.QtCore import QObject, QRectF, QSignalBlocker, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QPainter, QPainterPath,
                           QPixmap)
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QColorDialog, QComboBox,
                               QDialog, QFrame,
                               QGridLayout,
                               QHBoxLayout, QLabel, QLayout, QListWidget, QListWidgetItem,
                               QPushButton, QRadioButton, QScrollArea, QSlider, QTabWidget,
                               QVBoxLayout, QWidget)

from shiboken6 import isValid as qt_valid

from soundboard import autostart, midi, theme, winkeys, ytdl
from soundboard.ui import busy, fit, icons
from soundboard.ui import overlay as ovl
from soundboard.wheelguard import no_wheel
from soundboard.winkeys import Hotkeys
from soundboard import errors

log = logging.getLogger(__name__)

# Global hotkey actions: (config attribute, action id, label, what it does).
# Grouped for the Settings window; the action ids go to MainWindow.on_hotkey.
HOTKEY_GROUPS = [
    ("Sounds", [
        ("stop_hotkey", "__stop__", "Stop everything",
         "Stops every sound, the radio and every program."),
        ("pause_hotkey", "__pause__", "Pause / resume sounds",
         "Pauses everything playing; press again to carry on."),
        ("random_hotkey", "__random__", "Play a random sound",
         "From the category showing (All = any sound), never the same one twice in a row. "
         "A category can have its own: right-click its tab."),
        ("last_hotkey", "__last__", "Play the last sound again",
         "Whatever played last, from a pad, a hotkey or the random key."),
        ("vol_up_hotkey", "__volup__", "Sounds louder",
         "Turns your sounds up by 10% (what others hear and what you hear)."),
        ("vol_down_hotkey", "__voldown__", "Sounds quieter",
         "Turns your sounds down by 10%."),
    ]),
    ("Categories", [
        ("next_cat_hotkey", "__nextcat__", "Next category",
         "Shows the next category's pads. The random-sound key and the overlay follow it, "
         "so one key plays a random sound from whichever category you switched to."),
        ("prev_cat_hotkey", "__prevcat__", "Previous category",
         "Shows the category before it."),
    ]),
    ("Mic and voice", [
        ("mic_hotkey", "__mic__", "Send my mic on / off",
         "Others hear your voice with the sounds, or only the sounds."),
        ("voice_hotkey", "__voice__", "Voice changer on / off",
         "Turns the voice changer on with the voice picked on the Voice tab, or off."),
        ("voice_hold_hotkey", "__voicehold__", "Change my voice while held",
         "The voice changer is on only while you hold this key down."),
    ]),
    ("Turn hotkeys off", [
        ("hotkeys_off_hotkey", "__hotkeys__", "All hotkeys off / on",
         "Turns every other hotkey off, so they type normally (in chat, say), and back "
         "on. Hotkeys are always on when Onion Board opens."),
    ]),
    ("Instant replay", [
        ("replay_hotkey", "__replay__", "Save what you just heard",
         "Turns instant replay on: the last 30 seconds of everything your PC plays (a "
         "friend in Discord, the game, a video; not Onion Board's own sounds) are kept "
         "in memory, and this key adds them to your Sounds as a pad. Nothing is saved "
         "until you press it. Clear the key to switch it off. Only keep clips of people "
         "who are fine with it: in some places, recording a call needs everyone's OK."),
    ]),
    ("Overlay", [
        ("overlay_hotkey", "__overlay__", "Open the in-game overlay",
         "Sound tiles over your game; pick one with the number keys. See the Overlay tab."),
    ]),
]
HOTKEY_ACTIONS = [a for _, group in HOTKEY_GROUPS for a in group]

# Settings > About. The note is the author's own words, kept casual on purpose.
NOTE = ("Hey, thanks for actually using this. Onion Board started because every soundboard "
        "I tried was either ugly, full of ads, or quietly phoning home, so I made my own "
        "and it kind of snowballed from there. It's just me building it, a lot of late "
        "nights and a lot of testing, so if something's broken, ugly or confusing, tell "
        "me. Honestly. I'd way rather hear \"this part is cooked\" than have you quietly "
        "uninstall it.\n\nIt's free and it's staying free. Have fun with it, don't be a "
        "menace with it, and go make your friends jump in voice chat.\n\n— OnionAlien")
# Plain words, not a contract: the LICENSE file is the real terms.
DISCLAIMER = (
    "Onion Board is provided as is, with no warranty: use it at your own risk (the "
    "LICENSE file has the full terms). In plain words:"
    "<ul style='margin-left:-24px'>"
    "<li><b>Your sounds are on you.</b> It comes with none of its own. Only download, "
    "play or stream things you have the right to use, and follow the rules of the sites "
    "you get them from.</li>"
    "<li><b>Recording people.</b> Instant replay and radio clips record what your PC "
    "plays. Some places need everyone's OK to record a call, so ask first.</li>"
    "<li><b>Voices.</b> Don't use the voice changer or text-to-speech to pretend to be "
    "a real person, to scam or to harass anyone.</li>"
    "<li><b>Games and servers.</b> Some servers and games don't allow soundboards or "
    "voice changers. Onion Board never changes a game's files or reads its memory, but whether a "
    "server is OK with it is their call, and your account.</li>"
    "<li><b>Your ears.</b> Keep an eye on the volume, yours and your friends'.</li>"
    "<li><b>Names.</b> Discord, YouTube, VB-Audio and every other product named here "
    "belong to their owners. Onion Board isn't affiliated with or endorsed by any of "
    "them.</li>"
    "<li><b>Other people's code.</b> Parts of Onion Board (Qt, yt-dlp and more) "
    "come under their own licenses; THIRD-PARTY-NOTICES.txt next to the app lists "
    "them.</li></ul>")


def pretty_key(combo: str) -> str:
    if not combo:
        return ""
    if midi.is_midi(combo):
        return midi.pretty(combo)

    def part(p: str) -> str:
        if len(p) > 1:
            return p.title()
        if not p.isalnum() and p in winkeys.VK:   # punctuation: as printed on this keyboard
            return (winkeys.key_char(winkeys.VK[p]) or p).upper()
        return p.upper()
    return "+".join(part(p.strip()) for p in combo.split("+"))


def _button_row():
    """Buttons side by side at their own width, wrapping onto a second line only when
    Settings is too narrow (stacked full-width buttons looked like a form)."""
    from soundboard.ui.panel import Flow   # panel imports this module
    return Flow(gap=8)


class HotkeyDialog(QDialog):
    """Asks for a key combo, or (with `pads`) a hit on a MIDI pad controller."""

    def __init__(self, hotkeys: Hotkeys, parent=None, pads: bool = True):
        super().__init__(parent)
        fit.watch(self)   # grows to fit its text (ui/fit.py)
        self.setWindowTitle("Set hotkey")
        self.result_combo = None
        self._midi = hotkeys.midi if pads else None
        lay = QVBoxLayout(self)
        t = QLabel("Press the key or combo you want…")
        t.setStyleSheet("font-size:16px; font-weight:600;")
        lay.addWidget(t)
        self.hint = QLabel("Works globally, even while in-game.  Esc = cancel.")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        self.pads_note = QLabel()
        self.pads_note.setObjectName("hint")
        self.pads_note.setWordWrap(True)
        lay.addWidget(self.pads_note)
        # a way out on screen too (Esc and the title bar's ✕ were the only ones); it
        # takes no focus, so the keys pressed here all go to the capture
        cancel = QPushButton("Cancel")
        cancel.setFocusPolicy(Qt.NoFocus)
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(cancel)
        lay.addLayout(row)
        self._warned_vk = None
        self.setMinimumWidth(340)
        hotkeys.pause()   # so pressing an existing hotkey here doesn't trigger it
        if self._midi is not None:
            self._midi.pressed.connect(self._on_pad)
            self._midi.busy_changed.connect(self._show_pads)
            self._midi.capture(True)
            self.finished.connect(self._stop_pads)
        self._show_pads()

    def _show_pads(self, *_):
        if self._midi is None:
            self.pads_note.hide()
            return
        found = self._midi.devices()
        busy = set(self._midi.busy)
        free = [d for d in found if d not in busy]
        lines = []
        if free:
            lines.append("…or hit a pad on " + ", ".join(free) + ".")
        if busy:
            warn = theme.status("warn")
            lines.append(f"<span style='color:{warn}'>" + ", ".join(sorted(busy))
                         + " is open in another program (a music app?), so its pads can't "
                         "be used here. Close that program and it's picked up in a few "
                         "seconds.</span>")
        self.pads_note.setText("<br>".join(lines))
        self.pads_note.setVisible(bool(lines))

    def _on_pad(self, combo: str):
        if self.result_combo is None and self.isVisible():
            self.result_combo = combo
            self.accept()

    def _stop_pads(self):
        try:
            self._midi.pressed.disconnect(self._on_pad)
            self._midi.busy_changed.disconnect(self._show_pads)
        except (RuntimeError, TypeError):
            pass
        self._midi.capture(False)

    def keyPressEvent(self, e):
        vk = e.nativeVirtualKey()
        if vk == 0x1B:            # Esc
            self.reject()
            return
        if vk in winkeys.MODIFIER_VKS or not vk:
            return                # wait for the real key
        m = e.modifiers()
        mods = ((winkeys.MOD_CONTROL if m & Qt.ControlModifier else 0)
                | (winkeys.MOD_ALT if m & Qt.AltModifier else 0)
                | (winkeys.MOD_SHIFT if m & Qt.ShiftModifier else 0)
                | (winkeys.MOD_WIN if m & Qt.MetaModifier else 0))
        if not mods and is_typing_key(vk) and self._warned_vk != vk:
            # a global hotkey takes the key away from every other program: warn once
            self._warned_vk = vk
            key = pretty_key(winkeys.combo_name(0, vk))
            warn = theme.status("warn")
            self.hint.setText(f"<span style='color:{warn}'><b>{key}</b> on its own would "
                              "stop working for typing everywhere "
                              "(chat, games, browser). Add Ctrl, Alt or Shift — or press it "
                              "again to use it anyway.</span>")
            return
        self.result_combo = winkeys.combo_name(mods, vk)
        self.accept()


def is_typing_key(vk: int) -> bool:
    """Letters, digits, punctuation, Space, Enter, Tab, Backspace, arrows: keys people
    type with. F-keys, the numpad, Insert/Home/…, media keys are fine bare."""
    return (0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A or 0xBA <= vk <= 0xC0
            or 0xDB <= vk <= 0xDF or 0x25 <= vk <= 0x28
            or vk in (0x08, 0x09, 0x0D, 0x20, 0xE2))   # 0xE2: the extra key of ISO keyboards


class _Relay(QObject):
    """Carries a background job's result back to the UI thread."""
    done = Signal(str)


class _ProgressRelay(_Relay):
    """A _Relay that also carries progress (bytes done, bytes in all; 0 = unknown)."""
    progress = Signal(int, int)


class _AddonGrid(QWidget):
    """Settings → Add-ons: each add-on's name, status line and buttons, the buttons in
    shared columns so they line up from one add-on to the next. As many columns as
    fit (4, else 2, else 1): it never makes the page wider than its window."""
    GAP = 8

    def __init__(self, cols: int):
        super().__init__()
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(self.GAP)
        self.grid.setVerticalSpacing(6)
        self.max_cols = self.cols = cols
        self.rows: list[tuple[QLabel, QLabel, list[list[QPushButton]]]] = []

    def add(self, title: QLabel, status: QLabel, cells: list[list[QPushButton]]):
        for cell in cells:
            for b in cell:
                b.setMinimumWidth(40)    # the columns decide; resizeEvent keeps it readable
        self.rows.append((title, status, cells))
        self._place()

    def _need(self, cols: int) -> int:
        w = max((b.sizeHint().width() for _t, _s, cells in self.rows
                 for cell in cells for b in cell), default=0)
        return cols * w + (cols - 1) * self.GAP

    def _place(self):
        g, cols = self.grid, self.cols
        while g.count():
            g.takeAt(0)
        for r in range(g.rowCount()):
            g.setRowMinimumHeight(r, 0)
        r = 0
        for i, (title, status, cells) in enumerate(self.rows):
            if i:
                g.setRowMinimumHeight(r, 6)      # a gap between add-ons
                r += 1
            g.addWidget(title, r, 0, 1, cols)
            g.addWidget(status, r + 1, 0, 1, cols)
            r += 2
            for n, cell in enumerate(cells):
                for b in cell:
                    g.addWidget(b, r + n // cols, n % cols)
            r += (len(cells) + cols - 1) // cols
        for c in range(self.max_cols):
            g.setColumnStretch(c, 1 if c < cols else 0)

    def resizeEvent(self, e):
        cols = self.max_cols
        while cols > 1 and self._need(cols) > e.size().width():
            cols //= 2
        if cols != self.cols:
            self.cols = cols
            self._place()
        super().resizeEvent(e)


class ThemeCard(QPushButton):
    """A clickable mini-preview of a theme."""

    def __init__(self, name: str):
        super().__init__()
        self.name = name
        self.setObjectName("themecard")
        self.setCheckable(True)
        self.setFixedSize(QSize(150, 112))
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, e):
        super().paintEvent(e)   # frame + checked border from the stylesheet
        t = theme.THEMES[self.name]
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(8, 8, -8, -30)
        win = QPainterPath()
        win.addRoundedRect(r, 8, 8)
        p.fillPath(win, QColor(t["bg"]))
        # side panel, pads and a slider, in the theme's own colours
        p.setPen(Qt.NoPen)
        tex = t.get("texture")
        if tex:   # carbon's weave drawn finer, to read at this size
            tile = theme.texture_image(tex, t["panel"], 6 if tex == "carbon" else None)
            p.setBrush(QBrush(QPixmap.fromImage(tile)))
        else:
            p.setBrush(QColor(t["panel"]))
        p.drawRoundedRect(QRectF(r.right() - 44, r.top() + 6, 38, r.height() - 12), 5, 5)
        for i, col in enumerate(("#7c5cff", "#ff5c8a", "#1fb6ff", "#13ce66")):
            x = r.left() + 7 + (i % 2) * 44
            y = r.top() + 7 + (i // 2) * 34
            p.setBrush(QColor(t["card"]))
            p.drawRoundedRect(QRectF(x, y, 40, 28), 5, 5)
            p.setBrush(QColor(col))
            p.drawRoundedRect(QRectF(x + 5, y + 5, 10, 3), 1.5, 1.5)
        p.setBrush(QColor(t["groove"]))
        p.drawRoundedRect(QRectF(r.right() - 39, r.top() + 20, 28, 3), 1.5, 1.5)
        p.setBrush(QColor(t["accent"]))
        p.drawRoundedRect(QRectF(r.right() - 39, r.top() + 20, 17, 3), 1.5, 1.5)
        theme.paint_logo(p, QRectF(r.right() - 36, r.bottom() - 30, 22, 22),
                         t["accent"], t["accent2"])
        # name, in the theme's own font
        p.setPen(QColor(theme.T["text"]))
        f = QFont(self.font())
        f.setFamily(t.get("font", theme.FONT))
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(10, self.height() - 28, self.width() - 20, 22),
                   Qt.AlignLeft | Qt.AlignVCenter, self.name)
        p.end()


class ThemeGrid(QWidget):
    """Keep previews their readable size, using as many columns as fit."""

    def __init__(self, cards):
        super().__init__()
        self.cards = cards
        self.columns = 0
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(12)
        self.grid.setSizeConstraint(QLayout.SetNoConstraint)
        self._reflow(1)

    def minimumSizeHint(self):
        return QSize(150, 112)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow(max(1, min(len(self.cards), (self.width() + 12) // 162)))

    def _reflow(self, columns):
        if columns == self.columns:
            return
        for col in range(self.columns + 1):
            self.grid.setColumnStretch(col, 0)
        while self.grid.count():
            self.grid.takeAt(0)
        for i, card in enumerate(self.cards):
            self.grid.addWidget(card, i // columns, i % columns, Qt.AlignLeft)
        self.grid.setColumnStretch(columns, 1)
        self.columns = columns
        self.updateGeometry()


class SettingsDialog(QDialog):
    """All settings in one place. `mw` is the MainWindow; changes apply immediately."""

    def __init__(self, mw, page: str = "privacy", lazy: bool = False):
        """`lazy`: build only `page` now and each other page the first time it's shown.
        Building all twelve under the app's style sheet took a second or two on every
        click of the cog; the tests build them all at once."""
        super().__init__(mw)
        fit.watch(self)   # grows to fit its text (ui/fit.py)
        self.mw = mw
        if hasattr(mw, "tab_switched"):
            mw.tab_switched.connect(self._tab_switched)
        self.setWindowTitle("Settings")
        # short enough for a 1366x768 laptop at 125 % (the pages scroll): at 600 the
        # Done button sat below the screen
        self.setMinimumSize(720, 420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.hk_buttons: dict[str, list[QPushButton]] = {}
        pages = (("privacy", "Privacy && security", "shield", self._privacy),
                 ("connection", "Connection", "radio", self._connection),
                 ("data", "Data && quality", "wave", self._data),
                 ("general", "General", "settings", self._general),
                 ("tabs", "Tabs", "sounds", self._tabs),
                 ("appearance", "Appearance", "palette", self._appearance),
                 ("audio", "Audio", "volume", self._audio),
                 ("hotkeys", "Hotkeys", "keyboard", self._hotkeys),
                 ("overlay", "Overlay", "gamepad", self._overlay),
                 ("updates", "Updates", "reload", self._updates),
                 ("help", "Add-ons && help", "plus", self._help),
                 ("remote", "Remote", "cable", self._remote),
                 ("about", "About", "star", self._about))
        self.categories = QListWidget()
        self.categories.setObjectName("settingscategories")
        self.categories.setAccessibleName("Settings categories")
        self.categories.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.categories.setFixedWidth(196)
        self._unbuilt: dict[int, object] = {}   # tab index -> its page's builder
        for i, (key, title, icon, build) in enumerate(pages):
            sa = self._scroll()
            if lazy and key != page:
                self._unbuilt[i] = build
            else:
                self._fill(sa, build())
            self.tabs.addTab(sa, title)
            icons.set_tab_icon(self.tabs, i, icon)
            item = QListWidgetItem(icons.icon(icon), title.replace("&&", "&"))
            item.setData(Qt.UserRole, icon)
            item.setSizeHint(QSize(180, 38))
            self.categories.addItem(item)
        self._category_icons()
        self.tabs.tabBar().hide()
        self.categories.currentRowChanged.connect(self.tabs.setCurrentIndex)
        self.tabs.currentChanged.connect(self._build_page)
        self.tabs.currentChanged.connect(self.categories.setCurrentRow)
        keys = self._page_keys = [p[0] for p in pages]
        self.categories.setCurrentRow(keys.index(page) if page in keys else 0)
        self.tabs.setCurrentIndex(keys.index(page) if page in keys else 0)
        self._build_page(self.tabs.currentIndex())   # an unknown page: the first one
        content = QHBoxLayout()
        content.setSpacing(16)
        content.addWidget(self.categories)
        content.addWidget(self.tabs, 1)
        lay.addLayout(content, 1)
        close = QPushButton("Done")
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)
        self._initial_size()

    def _category_icons(self):
        for i in range(self.categories.count()):
            item = self.categories.item(i)
            name = item.data(Qt.UserRole)
            item.setIcon(icons.icon(name, selected="on_accent"))

    # ------------------------------------------------------------------ pages
    @staticmethod
    def _scroll() -> QScrollArea:
        """Pages scroll: a tall one (Hotkeys) otherwise gets squashed, rows on top of
        each other, whenever the window can't grow to fit it (maximized, small screen)."""
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QScrollArea.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        return sa

    @staticmethod
    def _fill(sa: QScrollArea, page: QWidget):
        for label in page.findChildren(QLabel):
            label.setWordWrap(True)
        for combo in page.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(6)
        sa.setWidget(page)

    def _build_page(self, i: int):
        """A lazy page, the first time it's shown."""
        build = self._unbuilt.pop(i, None)
        if build is not None:
            self._fill(self.tabs.widget(i), build())

    def _initial_size(self):
        """Open big enough for the tallest page, as far as the screen allows (a scroll
        area on its own would open at its small default)."""
        screen = self.screen() or QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        # wide enough to show every tab (the bar scrolls only when the screen is too
        # narrow for that)
        width = 1020
        # a page not built yet counts as tall (most are): switching to it later doesn't
        # resize the window
        need = 10_000 if self._unbuilt else 0
        for i in range(self.tabs.count()):
            if i in self._unbuilt:
                continue
            lay = self.tabs.widget(i).widget().layout()
            need = max(need, lay.totalSizeHint().height(),
                       lay.totalHeightForWidth(width - 260) if lay.hasHeightForWidth() else 0)
        # tab bar, Done row, margins; a normal window size, not the whole screen: a
        # tall page scrolls
        height = min(need + 150, 760)
        if avail is not None:
            width = min(width, avail.width() - 40)
            height = min(height, avail.height() - 60)
        self.resize(max(width, self.minimumWidth()), max(height, self.minimumHeight()))
    @staticmethod
    def _card(title: str, hint: str = ""):
        card = QFrame()
        card.setObjectName("setcard")
        v = QVBoxLayout(card)
        v.setContentsMargins(14, 12, 14, 14)
        v.setSpacing(8)
        t = QLabel(title.upper())
        t.setObjectName("section")
        v.addWidget(t)
        if hint:
            h = QLabel(hint)
            h.setObjectName("hint")
            h.setWordWrap(True)
            v.addWidget(h)
        return card, v

    def _page(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 12, 16, 12)
        v.setSpacing(12)
        return w, v

    def _appearance(self):
        w, v = self._page()
        self.theme_cards = []
        # first, above the themes (it sat under every theme card, out of sight)
        card, cv = self._card("Live tabs",
                              "A tab whose feature is on right now (a sound playing, the "
                              "voice changer, the radio…) is marked, so nothing is left on "
                              "without you noticing.")
        row = QVBoxLayout()   # one under the other: side by side made the page too wide
        green = QRadioButton("Tint the tab")
        green.setToolTip("A soft wash and a coloured icon in the theme's colour, easy to spot from "
                         "across the room")
        dot = QRadioButton("A small dot on its icon")
        dot.setToolTip("Quieter: only a dot on the tab's icon")
        modes = QButtonGroup(card)
        for b in (green, dot):
            modes.addButton(b)
            row.addWidget(b)
        (green if self.mw.cfg.live_tab_green else dot).setChecked(True)
        green.toggled.connect(self.mw.set_live_tab_tint)
        self.live_green, self.live_dot = green, dot
        cv.addLayout(row)
        v.addWidget(card)
        v.addWidget(self._highlight_card())
        hints = {"Classic": "Changes the whole app instantly.",
                 "Meme": "For when you want your soundboard to be a bit."}
        for group, names in theme.GROUPS:
            card, cv = self._card(group, hints.get(group, ""))
            cards = []
            for name in names:
                c = ThemeCard(name)
                c.setChecked(name == theme.current_name)
                c.clicked.connect(lambda _=False, n=name: self._pick_theme(n))
                cards.append(c)
                self.theme_cards.append(c)
            cv.addWidget(ThemeGrid(cards))
            v.addWidget(card)
        v.addStretch(1)
        return w

    def _highlight_card(self) -> QFrame:
        """Your own colour for what's on right now (the voice changer, Live, a live tab),
        kept whatever the theme: for when you like a theme but not its colour."""
        card, cv = self._card("Highlight colour",
                              "What's switched on (the voice changer, Live, a live tab) is "
                              "shown in the theme's colour. Slide to pick your own; it stays "
                              "when you change theme.")
        row = QHBoxLayout()
        row.setSpacing(10)
        swatch = QPushButton("On")   # a switched-on button, as it will look
        swatch.setObjectName("power")
        swatch.setCheckable(True)
        swatch.setChecked(True)
        swatch.setFocusPolicy(Qt.NoFocus)
        swatch.setAttribute(Qt.WA_TransparentForMouseEvents)
        swatch.setFixedWidth(64)
        swatch.setAccessibleName("Highlight colour preview")
        hue = QSlider(Qt.Horizontal)
        hue.setObjectName("hue")
        hue.setRange(0, 359)
        hue.setAccessibleName("Highlight colour hue")
        hue.setToolTip("Drag along the rainbow to pick the highlight colour")
        no_wheel(hue)
        row.addWidget(swatch)
        row.addWidget(hue, 1)
        cv.addLayout(row)
        btns = QHBoxLayout()
        more = QPushButton("More colours…")
        more.setToolTip("Pick any colour, including how strong and how bright it is")
        reset = QPushButton("Theme's colour")
        reset.setToolTip("Go back to each theme's own highlight colour")
        btns.addWidget(more)
        btns.addWidget(reset)
        btns.addStretch(1)
        cv.addLayout(btns)
        now = QLabel()
        now.setObjectName("hint")
        now.setWordWrap(True)
        cv.addWidget(now)
        self.hue_slider, self.hue_swatch, self.hue_reset, self.hue_now = hue, swatch, reset, now
        # arrow keys / clicks on the strip come in bursts: apply once they stop
        settle = QTimer(card, singleShot=True, interval=250)
        self.hue_settle = settle

        def own(h: int) -> str:
            """Hue `h` at the strength / brightness of the current colour (a vivid one
            when it's too grey for a hue to show)."""
            c = QColor(theme.T["live"])
            sat, val = c.hsvSaturationF(), c.valueF()
            if sat < 0.35 or val < 0.45:
                sat, val = 0.75, 0.95
            return QColor.fromHsvF(h / 360, sat, val).name()

        def preview(colour: str = ""):
            """Show `colour` on the swatch only (while dragging); "" = what's applied."""
            if colour:
                on = max(("#ffffff", "#111111"), key=lambda c: theme._contrast(c, colour))
                swatch.setStyleSheet(f"QPushButton#power:checked {{ background:{colour}; "
                                     f"border:1px solid {colour}; color:{on}; }}")
            else:
                swatch.setStyleSheet(theme.live_sheet())

        def sync():
            hue.blockSignals(True)
            h = QColor(theme.T["live"]).hsvHue()
            hue.setValue(h if h >= 0 else 0)
            hue.blockSignals(False)
            now.setText("Now: your own colour, in every theme."
                        if theme.live_override else
                        f"Now: {theme.current_name}'s own colour.")
            preview()

        def use(colour: str, btn=None, done: str = "") -> bool:
            settle.stop()
            changed = self.mw.set_live_color(colour)
            sync()
            if btn is not None and done:
                busy.flash(btn, done)
            return changed

        def moved(h: int):
            preview(own(h))
            if not hue.isSliderDown():
                settle.start()
        hue.valueChanged.connect(moved)
        hue.sliderReleased.connect(lambda: use(own(hue.value())))
        settle.timeout.connect(lambda: use(own(hue.value())))

        def pick():
            c = QColorDialog.getColor(QColor(theme.T["live"]), self, "Highlight colour")
            if c.isValid():
                use(c.name(), more, "✓ Changed")

        def back():
            if not theme.live_override:
                busy.flash(reset, "✓ Already the theme's")
            else:
                use("", reset, "✓ Back to the theme's")
        more.clicked.connect(pick)
        reset.clicked.connect(back)
        self._sync_highlight = sync
        sync()
        return card

    def _pick_theme(self, name: str):
        if name == theme.current_name:   # already on: restyling every widget again froze
            for c in self.theme_cards:   # the app for nothing (a click unticks the card)
                c.setChecked(c.name == name)
            return
        self.mw.apply_theme(name)
        self._category_icons()
        if getattr(self, "net_activity", None) is not None:
            self.net_activity.refresh(force=True)   # its status colours are per theme
        self._sync_highlight()   # the theme's own colour, unless you picked one
        for c in self.theme_cards:
            c.setChecked(c.name == name)
            c.update()

    def _hotkeys(self):
        w, v = self._page()
        for group, actions in HOTKEY_GROUPS:
            card, cv = self._card(group)
            for attr, _action, label, desc in actions:
                self._hk_row(cv, attr, label, desc)
            if group == "Categories":   # its keys and the per-category sets go together
                scoped = QCheckBox("Use hotkeys per category")
                scoped.setToolTip("One key can play a different sound in each category: "
                                  "switch category (its tab, or the keys above) and the same "
                                  "keys play that category's sounds. Sounds in no category "
                                  "always keep their keys.")
                scoped.setChecked(self.mw.cfg.scoped_hotkeys)
                scoped.toggled.connect(self.mw.set_scoped_hotkeys)
                cv.addWidget(scoped)
                hint = QLabel("Sound hotkeys only work in the category showing. "
                              "Switch categories to use the same keys for different sounds.")
                hint.setObjectName("hint")
                hint.setWordWrap(True)
                cv.addWidget(hint)
            v.addWidget(card)
        card, cv = self._card("Auto push-to-talk (optional)",
                              "Only if you use push-to-talk in a game or Discord: set your "
                              "push-to-talk key and the app holds it for you while a sound, "
                              "live radio or a program plays. Leave it Off for open mic.")
        self._hk_row(cv, "ptt_key", "Hold this key", "")
        v.addWidget(card)
        card, cv = self._card("Hotkey sounds",
                              "Short beeps in your headphones (only you hear them) when a hotkey "
                              "does something you can't see in a game: switches category (one "
                              "beep per place along, a low one for All), turns your mic, the "
                              "voice changer or the hotkeys on (rising) or off (falling), changes "
                              "the volume, or records or saves a clip.")
        cue = QCheckBox("Play hotkey beeps")
        cue.setChecked(self.mw.cfg.cue_sounds)
        cue.toggled.connect(lambda b: self.mw.set_option("cue_sounds", b))
        cv.addWidget(cue)
        v.addWidget(card)
        note = QLabel("Per-sound hotkeys: right-click a pad → Set hotkey. "
                      "All hotkeys work while you're in a game.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        note.setContentsMargins(14, 0, 14, 0)   # in line with the cards' text
        v.addWidget(note)
        v.addStretch(1)
        self._refresh_hk()
        return w

    def _hk_row(self, lay, attr, label, desc):
        row = QHBoxLayout()
        text = QVBoxLayout()
        text.setSpacing(0)
        t = QLabel(label)
        t.setStyleSheet("font-weight:600;")
        text.addWidget(t)
        if desc:
            d = QLabel(desc)
            d.setObjectName("hint")
            d.setWordWrap(True)
            text.addWidget(d)
        row.addLayout(text, 1)
        b = QPushButton()
        b.setObjectName("hkbtn")
        b.clicked.connect(lambda _=False, a=attr: self._capture(a))
        # each row's buttons say which hotkey they're for (a screen reader read every
        # row as "Click to set…" and "Clear")
        b.setAccessibleName(f"{label} hotkey")
        row.addWidget(b)
        x = QPushButton("✕")
        x.setObjectName("small")
        x.setToolTip(f"Clear the {label} hotkey")
        x.setAccessibleName(f"Clear the {label} hotkey")
        x.clicked.connect(lambda _=False, a=attr: self._set_hk(a, ""))
        row.addWidget(x)
        lay.addLayout(row)
        self.hk_buttons.setdefault(attr, []).append(b)

    def _refresh_hk(self):
        for attr, buttons in self.hk_buttons.items():
            combo = getattr(self.mw.cfg, attr)
            for b in buttons:
                b.setText(pretty_key(combo) or ("Off" if attr == "ptt_key" else "Click to set…"))

    def _capture(self, attr):
        # auto push-to-talk presses the key itself: that can't be a MIDI pad
        d = HotkeyDialog(self.mw.hotkeys, self, pads=attr != "ptt_key")
        if d.exec() and d.result_combo:
            self._set_hk(attr, d.result_combo)
        else:
            self.mw.register_hotkeys()   # capture paused them

    def _set_hk(self, attr, combo):
        self.mw.set_global_hotkey(attr, combo)
        self._refresh_hk()

    def _overlay(self):
        """The in-game overlay: how it opens, which keys pick, how it looks."""
        w, v = self._page()
        s = self.mw.overlay.s
        card, cv = self._card("Open it",
                              "Press the hotkey in a game and your sounds appear on top of it. "
                              "The game keeps your keyboard and mouse, and the overlay's keys "
                              "go back to the game the moment it closes.")
        self._hk_row(cv, "overlay_hotkey", "Overlay hotkey", "")
        test = QPushButton("Open overlay")
        test.setToolTip("Opens it now, the same as the hotkey: pick a sound with its keys "
                        "or a click. Esc, this button or the hotkey closes it")
        test.clicked.connect(lambda: self.mw.overlay.open_by_click())
        row = QHBoxLayout()   # beside how the key works: two lines, not three
        row.setSpacing(8)
        row.addWidget(self._ov_combo("mode", ovl.MODES, s.mode), 1)
        row.addWidget(test)
        cv.addLayout(row)
        v.addWidget(card)

        card, cv = self._card("Pick sounds",
                              "Nine tiles a page, in the same order as your pads — drag pads in "
                              "the Sounds tab to rearrange them.")
        cv.addWidget(self._ov_combo("keys", ovl.KEY_CHOICES, s.keys))
        after = QCheckBox("Hide after picking a sound")
        after.setChecked(s.close_after_play)
        after.toggled.connect(lambda b: self._ov_set("close_after_play", b))
        cv.addWidget(after)
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(QLabel("Auto-hide after"))
        row.addWidget(self._ov_combo("autohide", ovl.AUTOHIDE, s.autohide), 1)
        cv.addLayout(row)
        self.ov_toggle_only = (after, row.itemAt(1).widget())
        v.addWidget(card)

        card, cv = self._card("Where and how it looks",
                              "Or just drag it: grab any empty part of the overlay (its title, "
                              "its edges) and drop it anywhere, on any monitor. It opens there "
                              "from then on. Show preview only shows how it looks: open the "
                              "overlay with its hotkey to try it or move it.")
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.addWidget(QLabel("Monitor"), 0, 0)
        self.ov_monitor = self._ov_combo("monitor", self._monitor_choices(s.monitor), s.monitor)
        self.ov_monitor.setToolTip("With more than one monitor: put the overlay on the one "
                                   "you're gaming on, or keep it on a second one")
        grid.addWidget(self.ov_monitor, 0, 1)
        grid.addWidget(QLabel("Position"), 1, 0)
        self.ov_position = self._ov_combo("position", ovl.POSITIONS, s.position)
        grid.addWidget(self.ov_position, 1, 1)
        grid.addWidget(QLabel("Size"), 2, 0)
        grid.addLayout(self._ov_slider("scale", 60, 160, s.scale), 2, 1)
        grid.addWidget(QLabel("Background"), 3, 0)
        grid.addLayout(self._ov_slider("opacity", 30, 100, s.opacity), 3, 1)
        grid.setColumnStretch(1, 1)
        cv.addLayout(grid)
        # a drag on the overlay changes monitor / position: show it here
        self.mw.overlay.listeners.append(self._ov_dragged)
        self.destroyed.connect(lambda *_: self._ov_forget())
        self.finished.connect(lambda *_: self._ov_forget())
        prev = QPushButton("Show preview")
        prev.setToolTip("Shows the overlay for a few seconds, to see how it looks; any "
                        "click or key closes it")
        prev.clicked.connect(lambda: self.mw.overlay.preview(6))
        row = _button_row()
        row.addWidget(prev)
        cv.addLayout(row)
        v.addWidget(card)

        note = QLabel("Games in true exclusive fullscreen can't have anything drawn over them: "
                      "there the keys still work and you hear beeps instead (turn on hotkey "
                      "beeps above). Borderless / windowed fullscreen shows the overlay. "
                      "Some games also see the number keys you press — if picking a sound "
                      "switches your weapon, use the numpad.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        note.setContentsMargins(14, 0, 14, 0)   # in line with the cards' text
        v.addWidget(note)
        v.addStretch(1)
        self._ov_sync()
        return w

    def _ov_combo(self, key, choices, current):
        cb = QComboBox()
        for value, label in choices:
            cb.addItem(label, value)
        cb.setCurrentIndex(max(0, cb.findData(current)))
        cb.currentIndexChanged.connect(lambda i: self._ov_set(key, cb.itemData(i)))
        no_wheel(cb)
        return cb

    def _ov_slider(self, key, lo, hi, value):
        row = QHBoxLayout()
        sl = QSlider(Qt.Horizontal)
        sl.setRange(lo, hi)
        sl.setValue(value)
        val = QLabel(f"{value} %")
        val.setFixedWidth(48)
        val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        sl.valueChanged.connect(lambda x: (val.setText(f"{x} %"), self._ov_set(key, x)))
        no_wheel(sl)
        row.addWidget(sl, 1)
        row.addWidget(val)
        return row

    def _ov_set(self, key, value):
        d = self.mw.overlay.s.to_dict()
        d[key] = value
        self.mw.overlay.apply(d)
        self.mw.set_option("overlay", self.mw.overlay.s.to_dict())
        self._ov_sync()

    def _monitor_choices(self, current: str) -> list[tuple[str, str]]:
        choices = ovl.monitor_choices(QApplication.screens(), QApplication.primaryScreen())
        if current not in dict(choices):   # a monitor that isn't plugged in right now
            choices.append((current, f"{current.rpartition('@')[0] or current}  (not connected)"))
        return choices

    def _ov_dragged(self):
        """The overlay was dragged somewhere: show its new monitor and position."""
        if not qt_valid(self):
            return
        s = self.mw.overlay.s
        for cb, value, choices in ((self.ov_monitor, s.monitor, self._monitor_choices(s.monitor)),
                                   (self.ov_position, s.position, ovl.POSITIONS)):
            cb.blockSignals(True)
            cb.clear()
            for v, label in choices:
                cb.addItem(label, v)
            cb.setCurrentIndex(max(0, cb.findData(value)))
            cb.blockSignals(False)

    def _ov_forget(self):
        try:
            self.mw.overlay.listeners.remove(self._ov_dragged)
        except ValueError:
            pass

    def _ov_sync(self):
        for wdg in getattr(self, "ov_toggle_only", ()):
            wdg.setEnabled(self.mw.overlay.s.mode == "toggle")   # hold mode: letting go hides

    def _audio(self):
        w, v = self._page()
        v.addWidget(self._devices_card())
        card, cv = self._card("Your mic",
                              "Normally others hear your voice and your sounds together. Untick "
                              "this for sounds only: they hear the sounds but not your mic. "
                              "(Same as the “Others hear it” box under My mic.)")
        send = QCheckBox("Send my mic to others")
        send.setChecked(self.mw.cfg.mic_enabled)
        send.toggled.connect(self.mw.chk_mic.setChecked)   # the window applies it
        cv.addWidget(send)
        v.addWidget(card)
        v.addWidget(self._stream_card())
        v.addWidget(self._voices_card())
        card, cv = self._card("Who's listening",
                              "Voice chat squashes your sounds: mono, no deep bass, and in some "
                              "games nothing above 8-12 kHz. Pick where people hear you and "
                              "they're shaped to get through it. Game and Voice chat work out "
                              "the exact voice chat by themselves; Clean sends them exactly as "
                              "mixed; Advanced lets you pick it yourself.")
        from soundboard.ui.destpanel import DestPanel
        dest = DestPanel(self.mw)
        dest.chk_gate.setText("Mute mic during sounds")
        cv.addWidget(dest)
        v.addWidget(card)
        card, cv = self._card("Audio buffering",
                              "Low keeps your voice and sounds as immediate as possible. If the "
                              "status line reports drop-outs (crackles, stutters), Safer uses "
                              "bigger buffers: a little more delay, far fewer drop-outs.")
        lat = QComboBox()
        lat.addItem("Low (default)", "low")
        lat.addItem("Safer — bigger buffers", "high")
        lat.setCurrentIndex(max(0, lat.findData(self.mw.cfg.latency)))
        lat.currentIndexChanged.connect(lambda i: self.mw.set_latency(lat.itemData(i)))
        no_wheel(lat)
        cv.addWidget(lat)
        e = self.mw.engine
        xr = sum(e.xruns.values())
        stat = QLabel(f"Since start: {xr} drop-out{'s' if xr != 1 else ''}, "
                      f"{e.stalls} device reconnect{'s' if e.stalls != 1 else ''}.")
        stat.setObjectName("hint")
        cv.addWidget(stat)
        v.addWidget(card)
        v.addStretch(1)
        return w

    def _stream_card(self):
        """The stream output: sounds (and your voice) on a device of their own for OBS."""
        from soundboard import engine as eng
        from soundboard.ui.panel import VolumeControl
        mw = self.mw
        c = mw.cfg
        card, cv = self._card(
            "Stream output (OBS)",
            "Streaming? Send what others hear, clean (no voice chat shaping), to a device "
            "of its own, and add it to OBS as its own audio track: your sounds, screen "
            "triggers, live radio and programs, and your voice if you like. In OBS: "
            "Sources → + → Audio Output Capture → pick the same device. Any output you don't "
            "listen on works (with a spare virtual cable, use Audio Input Capture → its "
            "Output end).")
        cb = QComboBox()
        no_wheel(cb)
        cb.addItem("Off", None)
        main = mw._main_name()   # what others hear (None: sending nowhere frees it)
        for d in eng.list_devices("output"):
            if (d["name"] not in (main, c.mon_device)   # those already have a job
                    and not eng.same_cable(d["name"], main)):
                cb.addItem(d["name"], d["name"])
        i = cb.findData(c.obs_device) if c.obs_device else 0
        cb.setCurrentIndex(max(i, 0))
        cb.activated.connect(lambda i: mw.set_obs_device(cb.itemData(i)))
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        grid.addWidget(QLabel("Send to"), 0, 0)
        grid.addWidget(cb, 0, 1, 1, 2)
        grid.addWidget(QLabel("Volume"), 1, 0)
        vol = VolumeControl(c.obs_vol, tip="How loud the stream output is (only OBS hears it)")
        vol.changed.connect(lambda x: mw.set_option("obs_vol", x))
        grid.addWidget(vol, 1, 1)
        grid.setColumnStretch(2, 1)   # the slider and its box stay together on the left
        cv.addLayout(grid)
        voice = QCheckBox("Include my voice")
        voice.setToolTip("Untick if OBS already records your mic on its own")
        voice.setChecked(c.obs_voice)
        voice.toggled.connect(lambda b: mw.set_option("obs_voice", b))
        cv.addWidget(voice)
        note = QLabel("Includes the voice changer when it's on. Untick if OBS "
                      "already records your mic separately.")
        note.setObjectName("hint")
        cv.addWidget(note)
        return card

    def _voices_card(self):
        """Custom text-to-speech voices live on the Voice tab (under More options); this
        card is where people look for them first. Hidden while the tab is switched off
        (Settings > Tabs), and its buttons reach the Voice tab there now: switched off
        and on again while Settings is open, that's a new one."""
        from soundboard.speech import customvoices
        mw = self.mw
        card, cv = self._card(
            "Custom voices (text-to-speech)",
            "Your own voices for typed lines and Talk as a computer voice: a TTS server "
            "running on your PC (Kokoro, AllTalk, any OpenAI-style one), a TTS program, or "
            "Piper voice packs dropped into the voices folder. They join the Voice list on "
            "the Voice tab.")
        row = _button_row()   # one line, wrapping only when the window is narrow
        add = QPushButton("Add a voice server…")
        icons.set_icon(add, "plus")
        add.clicked.connect(lambda: mw.tab_on("voice") and mw.voice.speech._add_voice_server())
        row.addWidget(add)
        folder = QPushButton("Open voices folder")
        folder.setToolTip("Voice packs and voice settings go here; README.txt in it says how")
        folder.clicked.connect(lambda: busy.open_folder(customvoices.ensure_folder, folder))
        row.addWidget(folder)
        show = QPushButton("Show on the Voice tab")

        def go():
            if not mw.tab_on("voice"):
                return
            self.accept()
            mw.tabs.setCurrentWidget(mw.voice)
            mw.voice.speech.show_custom_voices()
        show.clicked.connect(go)
        row.addWidget(show)
        cv.addLayout(row)
        self.voices_card, self.voices_show = card, show
        if not mw.tab_on("voice"):   # (never show() it here: not in its page yet, it'd
            card.hide()              # flash up as a little window of its own)
        return card

    def _devices_card(self):
        """Input / output pickers: the Setup tab's Devices combos, mirrored here so
        people find them where they look first. Picking goes through the window."""
        mw = self.mw
        card, cv = self._card("Devices",
                              "Your mic (input) and where you listen (output). Your "
                              "sounds go into your mic unless you pick somewhere else "
                              "to send them. Plugged something in? Press Re-scan.")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        self.dev_combos = []
        for r, (text, src, attr) in enumerate((
                ("Input — my mic", mw.cb_mic, "mic_device"),
                ("Output — my headphones", mw.cb_mon, "mon_device"),
                ("Send my sounds to", mw.cb_route, "route"))):
            cb = QComboBox()
            cb.setMinimumWidth(120)
            # sized for a short name, the list opens wide enough for whole ones (device
            # names in "Send my sounds to" made the page scroll sideways)
            cb.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(16)
            no_wheel(cb)
            cb.activated.connect(lambda i, src=src, attr=attr: self._pick_device(src, attr, i))
            label = QLabel(text)
            grid.addWidget(label, r, 0)
            grid.addWidget(cb, r, 1)
            self.dev_combos.append((cb, src))
        grid.setColumnStretch(1, 1)
        cv.addLayout(grid)
        from soundboard.ui import alsosend   # (its panel import imports this module)
        # once the grid is in the card: a row added before would be its own window
        alsosend.build(mw, grid, grid.rowCount(), icons_col=False)   # kept up to date by mw
        ref = QPushButton("Re-scan devices")
        icons.set_icon(ref, "reload")
        ref.clicked.connect(lambda: mw.rescan_with_feedback(ref, self._sync_devices))
        cv.addWidget(ref, 0, Qt.AlignLeft)
        self._sync_devices()
        return card

    def _sync_devices(self):
        for cb, src in self.dev_combos:
            cb.clear()
            for i in range(src.count()):
                cb.addItem(src.itemText(i), src.itemData(i))
            cb.setCurrentIndex(src.currentIndex())
            cb.view().setMinimumWidth(cb.view().sizeHintForColumn(0) + 32)   # whole names

    def _pick_device(self, src, attr, i):
        src.setCurrentIndex(i)
        self.mw.on_device(src, attr)
        self._sync_devices()   # "Send my sounds to" never offers the headphones

    def _general(self):
        w, v = self._page()
        card, cv = self._card("Window")
        top = QCheckBox("Keep window on top")
        top.setChecked(self.mw.cfg.always_on_top)
        top.toggled.connect(self.mw.on_top_toggle)
        cv.addWidget(top)
        one = QCheckBox("Play pads with one click")
        one.setToolTip("Then Ctrl+click picks a pad without playing it")
        one.setChecked(self.mw.cfg.single_click)
        one.toggled.connect(self.mw.set_single_click)
        cv.addWidget(one)
        hint = QLabel("Otherwise, double-click to play. Ctrl+click selects without playing.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        cv.addWidget(hint)
        v.addWidget(card)
        v.addWidget(self._background_card())
        v.addWidget(self._backup_card())
        v.addWidget(self._reset_card())
        v.addStretch(1)
        return w

    # Settings > Tabs: what each tab that can be switched off is for (taboff.KEYS)
    TAB_HINTS = {
        "radio": "Internet radio stations from around the world.",
        "apps": "Send another program's sound (a music player, a game) to others.",
        "triggers": "Play a sound when something shows up on your screen (Onion Watch).",
        "voice": "The voice changer, AI voices and talking as a computer voice. Off: "
                 "your mic goes out as it is.",
    }

    def _tabs(self):
        w, v = self._page()
        card, cv = self._card(
            "Tabs",
            "Switch off the tabs you don't use. A switched-off tab is gone from the "
            "window and doesn't load at all, so nothing of it runs in the background. "
            "Switch it back on any time.")
        from soundboard.ui.mainwindow import TABS
        self.tab_boxes: dict[str, QCheckBox] = {}
        for text, _tip in TABS:
            key = text.lower()
            if key in self.TAB_HINTS:
                self.tab_boxes[key] = self._option(
                    cv, text, self.TAB_HINTS[key], self.mw.tab_on(key),
                    lambda on, k=key: self.mw.set_tab_on(k, on))
            else:   # Sounds and Setup: the board itself, and where it sends
                box = self._option(cv, text, "Always on.", True, lambda _on: None)
                box.setEnabled(False)
        v.addWidget(card)
        v.addStretch(1)
        return w

    def _tab_switched(self, key: str, on: bool):
        """A tab was switched off or on (here, or by importing settings): its box, and
        the other pages' parts that belong to it (built already, they'd still point at
        the tab that was there)."""
        box = getattr(self, "tab_boxes", {}).get(key)
        if box is not None and box.isChecked() != on:
            with QSignalBlocker(box):
                box.setChecked(on)
        if key == "triggers" and hasattr(self, "_watch_refresh"):
            self._watch_refresh()
        if key == "voice" and hasattr(self, "voices_card"):
            self.voices_card.setVisible(on)

    def _reset_card(self):
        card, cv = self._card("Start over",
                              "Something's not right? Reset just the parts you pick: "
                              "settings, hotkeys, sounds, Recently deleted, Apps tab "
                              "programs or audio devices. A restore point is saved "
                              "first, so it can always be undone.")
        row = QHBoxLayout()
        rst = QPushButton("Reset…")
        icons.set_icon(rst, "reload")
        rst.clicked.connect(lambda: self._open_reset(points=False))
        pts = QPushButton("Restore points…")
        pts.clicked.connect(lambda: self._open_reset(points=True))
        row.addWidget(rst)
        row.addWidget(pts)
        row.addStretch(1)
        cv.addLayout(row)
        return card

    def _open_reset(self, points: bool):
        from soundboard.ui.resetguide import ResetGuide, RestorePoints
        (RestorePoints if points else ResetGuide)(self.mw, self).exec()

    def _help(self):
        w, v = self._page()
        col = QWidget()
        col.setMaximumWidth(self.ADDONS_W)
        cl = QVBoxLayout(col)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(12)
        cl.addWidget(self._addons_card())
        cl.addWidget(self._feedback_card())
        cl.addWidget(self._support_card())
        row = QHBoxLayout()
        row.addWidget(col, 1)
        row.addStretch(0)
        v.addLayout(row)
        v.addStretch(1)
        return w

    def _updates(self):
        w, v = self._page()
        v.addWidget(self._updates_card())
        v.addWidget(self._downloader_card())
        v.addStretch(1)
        return w

    def _remote(self):
        w, v = self._page()
        v.addWidget(self._remote_card())
        for card in self._remote_addon_cards():
            v.addWidget(card)
        v.addWidget(self._remote_easy_card())
        v.addStretch(1)
        return w

    # ------------------------------------------------------------------ about
    def _about(self):
        w, v = self._page()
        v.addWidget(self._about_card())
        v.addWidget(self._contact_card())
        v.addWidget(self._note_card())
        v.addWidget(self._disclaimer_card())
        v.addStretch(1)
        return w

    def _link_button(self, text: str, url: str, icon: str = "") -> QPushButton:
        btn = QPushButton(text)
        if icon:
            icons.set_icon(btn, icon)
        btn.clicked.connect(lambda: busy.open_url(
            url, btn, opened="✓ Opened in your browser",
            failed="Couldn't open your browser. The page is"))
        return btn

    def _about_card(self):
        """The version (as the title bar shows it), and where the app and its licences
        live."""
        from soundboard.ui.mainwindow import version_text
        from soundboard.updates import REPO
        card, cv = self._card("Onion Board")
        ver = self.about_version = QLabel(f"Version {version_text()}")
        ver.setTextInteractionFlags(Qt.TextSelectableByMouse)
        cv.addWidget(ver)
        hint = QLabel("Free, with no ads and no account. Made by OnionAlien. "
                      "MIT license with the Commons Clause: use it for anything, share it "
                      "for free, never sell it.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        cv.addWidget(hint)
        row = _button_row()
        row.addWidget(self._link_button("Website", "https://onion-alien.github.io/onion-board/",
                                        "browser"))
        row.addWidget(self._link_button("Source code", f"https://github.com/{REPO}"))
        row.addWidget(self._link_button("Licenses", f"https://github.com/{REPO}#license"))
        cv.addLayout(row)
        return card

    def _contact_card(self):
        """Ways to reach the author. All of them only open a page in the browser:
        nothing is sent from the app (feedback.py)."""
        from soundboard import __version__, feedback
        from soundboard.updates import REPO
        card, cv = self._card("Get in touch",
                              "Ideas, bugs, or just want to say hi? The feedback form needs "
                              "no account. Found a security problem? Report it privately "
                              "on GitHub, not in a public issue.")
        row = _button_row()
        send = self._link_button("Send feedback", feedback.feedback_url(__version__), "speech")
        send.setObjectName("primary")
        row.addWidget(send)
        row.addWidget(self._link_button("Report a problem", feedback.problem_url(__version__)))
        row.addWidget(self._link_button(
            "Report a security issue", f"https://github.com/{REPO}/security/advisories/new",
            "shield"))
        cv.addLayout(row)
        return card

    def _note_card(self):
        card, cv = self._card("A note from me")
        note = QLabel(NOTE)
        note.setWordWrap(True)
        cv.addWidget(note)
        return card

    def _disclaimer_card(self):
        card, cv = self._card("The boring bit")
        text = QLabel(DISCLAIMER)
        text.setObjectName("hint")
        text.setWordWrap(True)
        text.setTextFormat(Qt.RichText)
        cv.addWidget(text)
        return card

    # ------------------------------------------------------------------ add-ons
    ADDONS_W = 760   # the Add-ons & help page's cards stop growing here (a wide window
    #                  stretched them into long thin bars with the buttons far apart)

    class _AddonRelay(QObject):
        """A check for a newer add-on, back on the UI thread: (offer, error text)."""
        done = Signal(object, str)

    def _addons_card(self):
        """Every add-on in one place, each with the same row of buttons in the same
        order: Check for updates (Update to X once one is out), Reinstall (a fresh
        copy of the newest; the user's triggers / paired phones are the board's and
        stay), Report a problem, Remove… Not installed: Get it, and Report a problem.
        One grid for all of them (_AddonGrid): the buttons share columns, so they line
        up from one add-on to the next, folding to two columns in a narrow window."""
        card, cv = self._card("Add-ons",
                              "Free add-ons from GitHub. Removing or reinstalling one "
                              "keeps your triggers and paired phones.")
        grid = _AddonGrid(len(self.ADDON_COLUMNS))
        cv.addWidget(grid)      # in the card first: a button shown without a parent
        self._watch_block(grid)  # is a window of its own
        self._pocket_block(grid)
        return card

    # the button columns, in order; "get" stands in for "check" while it isn't in
    ADDON_COLUMNS = (("check", "get"), ("report",), ("reinstall",), ("remove",))

    def _addon_block(self, grid, name: str, blurb: str):
        """An add-on's name and what it's for, a status line, and its buttons, as rows
        of the Add-ons grid. (status label, {key: button})."""
        title = QLabel(f"<b>{html.escape(name)}</b> · {html.escape(blurb)}")
        title.setTextFormat(Qt.RichText)
        title.setWordWrap(True)
        status = QLabel()
        status.setObjectName("hint")
        status.setWordWrap(True)
        btns = {}
        for key, text, icon in (("get", f"Get {name}", ""),
                                ("check", "Check for updates", "reload"),
                                ("reinstall", "Reinstall", ""),
                                ("report", "Report a problem", ""),
                                ("remove", "Remove…", "trash")):
            b = QPushButton(text)
            if icon:
                icons.set_icon(b, icon, "danger_text" if key == "remove" else None)
            btns[key] = b
        btns["get"].setObjectName("primary")
        btns["reinstall"].setToolTip(f"Downloads the newest {name} again and puts it in "
                                     "place of this one. Your own things are kept.")
        btns["report"].setToolTip("Opens a bug report on GitHub in your browser, with "
                                  "the versions filled in")
        grid.add(title, status, [[btns[k] for k in keys] for keys in self.ADDON_COLUMNS])
        return status, btns

    def _addon_report(self, btn, what: str):
        from soundboard import __version__, feedback
        busy.open_url(feedback.problem_url(__version__, what), btn,
                      opened="✓ Opened in your browser",
                      failed="Couldn't open your browser. The page is")

    def _addon_check(self, btn, feature: str, latest, newer_than: str, on_offer):
        """Check for updates: asks GitHub on a thread (`latest()` -> offer or None);
        a newer one calls `on_offer(offer)`, else the button says it's up to date."""
        from soundboard import net, netlog, updates
        if not net.allowed(feature):
            busy.flash(btn, "Add-on downloads are off (Privacy)", 4000)
            return
        release = busy.hold(btn, "Checking…")
        relay = self._AddonRelay(self)
        netlog.cause(feature, "You clicked Check for updates (Settings > Add-ons)")

        def done(offer, error):
            relay.deleteLater()
            if not qt_valid(btn):
                return
            if error:
                release("Couldn't check")
                busy.toast(self, html.escape(error), "warn")
            elif offer is not None and updates.newer(offer.version, newer_than):
                release()
                on_offer(offer)
            else:
                release("✓ Up to date")

        def ask():
            try:
                offer, error = latest(), ""
            except Exception as e:  # noqa: BLE001 - offline, rate-limited, switched off…
                offer, error = None, f"Couldn't reach GitHub ({errors.plain(e)})."
            try:
                relay.done.emit(offer, error)
            except RuntimeError:        # Settings was closed meanwhile
                pass
        relay.done.connect(done)
        threading.Thread(target=ask, daemon=True, name="addon-check").start()

    # ---- Onion Watch (the Triggers tab's add-on, soundboard.watchaddon)
    def _watch_block(self, grid):
        from soundboard import watchaddon
        status, b = self._addon_block(grid, "Onion Watch", "the Triggers tab")
        self.addon_label, self.addon_remove = status, b["remove"]
        self.watch_buttons = b
        state = {}

        def tab():
            """The Triggers tab there now: switched off and on again (Settings > Tabs)
            while this is open, it's a new one; switched off, None (nothing of it is
            loaded)."""
            return self.mw.triggers if self.mw.tab_on("triggers") else None

        def refresh(note: str = ""):
            if not qt_valid(status):
                return
            t = tab()
            if t is None:
                status.setText("The Triggers tab is switched off (Settings > Tabs).")
                for btn in b.values():
                    btn.hide()
                return
            b["report"].setVisible(True)   # back on (Settings > Tabs)
            info = t.info
            have = info is not None and watchaddon.removable(info, t._base())
            status.setText(note or (f"Version {info.version} is installed." if have else
                                    "Onion Watch isn't installed."))
            b["get"].setVisible(not have)
            for k in ("check", "reinstall", "remove"):
                b[k].setVisible(have)
            if not have:
                state.pop("offer", None)
            self._label_update(b["check"], state.get("offer"))

        def run_get(offer, btn, text):
            """tab.get() does the work (and shows it on the Triggers tab too)."""
            t = tab()
            if t is None:
                return
            if t._busy:
                busy.flash(btn, "Already downloading")
                return
            t.offer = offer
            release = busy.hold(btn, text)

            def finished(info, error, _update):
                t._finished.disconnect(finished)
                if not qt_valid(btn):
                    return
                release("✗ Didn't work" if error else "✓ Done")
                state.pop("offer", None)
                refresh(f"Onion Watch wasn't installed: {errors.plain(error)}" if error
                        else (f"Version {info.version} is in. Restart Onion Board to "
                              "start using it." if _update else ""))
                QTimer.singleShot(0, lambda: refresh() if not error and not _update
                                  else None)
            t._finished.connect(finished)
            t.get()

        def check():
            if state.get("offer") is not None:      # "Update to X"
                run_get(state["offer"], b["check"], "Updating…")
                return
            if tab() is None:
                return
            info = tab().info

            def found(offer):
                state["offer"] = offer
                if tab() is not None:
                    tab().offer_update(offer)
                refresh()
            self._addon_check(b["check"], watchaddon.FEATURE, watchaddon.latest,
                              info.version if info else "0", found)

        def remove():
            if tab() is not None:
                tab().remove()              # asks first
            refresh()

        b["get"].clicked.connect(lambda: run_get(None, b["get"], "Getting it…"))
        b["check"].clicked.connect(check)
        b["reinstall"].clicked.connect(lambda: run_get(None, b["reinstall"],
                                                       "Reinstalling…"))
        b["report"].clicked.connect(lambda: self._addon_report(
            b["report"], f"Onion Watch {tab().info.version}"
            if tab() is not None and tab().info else "Onion Watch"))
        b["remove"].clicked.connect(remove)
        self._watch_refresh = refresh   # the Tabs page switched Triggers off or on
        refresh()   # in the card first: shown without a parent, it's a window of its own

    @staticmethod
    def _label_update(btn, offer):
        """Check for updates, or *Update to X* (primary) once a newer one is found."""
        text = f"Update to {offer.version}" if offer is not None else "Check for updates"
        if btn.text() != text and not busy.is_busy(btn):
            btn.setText(text)
            btn.setObjectName("primary" if offer is not None else "")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    # ---- Onion Pocket (the phone remote, soundboard.pocketaddon)
    def _pocket_block(self, grid):
        from soundboard import pocketaddon, updates
        status, b = self._addon_block(grid, "Onion Pocket", "your pads on your phone")
        self.pocket_remove_addons = b["remove"]
        self.pocket_buttons = b
        state = {}

        def refresh(note: str = ""):
            if not qt_valid(status):
                return
            info = self._pocket_info()
            have = info is not None and pocketaddon.removable(info)
            if info is not None and info.error and have:
                note = note or f"Version {info.version} is installed but didn't start: " \
                               f"{info.error}. Reinstall it, or report the problem."
            status.setText(note or (f"Version {info.version} is installed. Its settings "
                                    "are on the Remote page." if have else
                                    "Onion Pocket isn't installed."))
            b["get"].setVisible(not have and pocketaddon.offered())
            for k in ("check", "reinstall", "remove"):
                b[k].setVisible(have)
            offer = state.get("offer")
            if not have or (offer is not None and info is not None
                            and not updates.newer(offer.version, info.version)):
                state.pop("offer", None)
            self._label_update(b["check"], state.get("offer"))

        def check():
            if state.get("offer") is not None:      # "Update to X"
                self._pocket_install(b["check"], state["offer"], "Updating…")
                return
            info = self._pocket_info()

            def found(offer):
                state["offer"] = offer
                self.mw.pocket_offer = offer
                refresh()
            self._addon_check(b["check"], pocketaddon.FEATURE, pocketaddon.latest,
                              info.version if info else "0", found)

        b["get"].clicked.connect(lambda: self._pocket_install(b["get"], None,
                                                              "Getting it…"))
        b["check"].clicked.connect(check)
        b["reinstall"].clicked.connect(lambda: self._pocket_install(b["reinstall"], None,
                                                                    "Reinstalling…"))
        b["report"].clicked.connect(lambda: self._addon_report(
            b["report"], f"Onion Pocket {i.version}" if (i := self._pocket_info())
            else "Onion Pocket"))
        b["remove"].clicked.connect(lambda: self._remove_pocket(b["remove"]))
        self._pocket_refresh = refresh
        refresh()

    def _pocket_install(self, btn, offer, text: str):
        """Get / reinstall / update Onion Pocket from the Add-ons card: downloads it
        (pocketaddon.get), the main window swaps it in for any running copy (paired
        phones stay), and its card on Settings → Remote is replaced by the new one's."""
        from soundboard import netlog, pocketaddon

        class Relay(QObject):
            done = Signal(object)

        release = busy.hold(btn, text)
        netlog.cause(pocketaddon.FEATURE, "You clicked to get Onion Pocket "
                                          "(Settings > Add-ons)")
        relay = Relay(self.mw)   # the main window's: it's loaded even if Settings closes

        def finish(new):
            relay.deleteLater()
            addon = self.mw.load_remote_addon(new) if new is not None else None
            if new is not None:
                self.mw.pocket_offer = None
            if not qt_valid(btn):
                return
            if addon is None:
                release("✗ Didn't work")
                busy.toast(self, "Couldn't get Onion Pocket right now. Check your "
                                 "internet connection and try again.", "warn")
                self._pocket_changed()
                return
            release("✓ Done")
            if getattr(self, "_pocket_slot", None) is not None:
                fresh = self._addon_card(new, addon)
                if fresh is not None:
                    self._pocket_remove_button(fresh, new)
                self._swap_pocket_slot(fresh)
            self._pocket_changed()
            busy.toast(self, f"✓ Onion Pocket {html.escape(new.version)} is in.", "ok")

        relay.done.connect(finish)
        threading.Thread(target=lambda: relay.done.emit(pocketaddon.get(offer=offer)),
                         daemon=True, name="onion-pocket-addons").start()

    # ------------------------------------------------------------------ support
    def _feedback_card(self):
        """Feedback and bug reports: both open a page in the browser, nothing is sent
        from the app (feedback.py)."""
        from soundboard import __version__, feedback
        card, cv = self._card("Feedback and problems",
                              "Found a bug, missing something, or just want to say hi? It "
                              "opens in your browser, and nothing is sent unless you submit "
                              "it there.")
        row = _button_row()
        send = QPushButton("Send feedback")
        send.setObjectName("primary")
        send.clicked.connect(lambda: busy.open_url(
            feedback.feedback_url(__version__), send, opened="✓ Opened in your browser",
            failed="Couldn't open your browser. The page is"))
        icons.set_icon(send, "speech")
        bug = QPushButton("Report a problem on GitHub")
        bug.setToolTip("For people with a GitHub account: opens a new bug report")
        bug.clicked.connect(lambda: busy.open_url(
            feedback.problem_url(__version__), bug, opened="✓ Opened in your browser",
            failed="Couldn't open your browser. The page is"))
        row.addWidget(send)
        row.addWidget(bug)
        cv.addLayout(row)
        self.feedback_btn, self.problem_btn = send, bug
        return card

    def _support_card(self):
        """A link to the GitHub page's Support section: the ways to donate live there,
        not in the app, so they can change without a release and a copy of the app
        with someone else's details swapped in is easy to spot."""
        from soundboard.updates import REPO
        card, cv = self._card("Support Onion Board",
                              "Onion Board is free, with no ads and no account. If it made "
                              "your games or calls more fun, you can chip in. Entirely "
                              "optional. The button opens the project's GitHub page.")
        btn = QPushButton("♥  Support Onion Board")
        btn.clicked.connect(lambda: busy.open_url(
            f"https://github.com/{REPO}#support-onion-board", btn,
            opened="✓ Opened in your browser — thank you!",
            failed="Couldn't open your browser. The page is"))
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addStretch(1)
        cv.addLayout(row)
        return card

    # ------------------------------------------------------------------ background
    def _background_card(self):
        mw = self.mw
        card, cv = self._card("Running in the background",
                              "A soundboard is most useful left running: your hotkeys and the "
                              "overlay work while the window is closed. The tray icon (by the "
                              "clock) opens it again; right-click it to quit.")
        tray = QCheckBox("Close to tray")
        tray.setChecked(mw.cfg.tray)
        tray.toggled.connect(lambda b: mw.set_option("tray", b))
        if mw.tray is None:
            tray.setEnabled(False)
            tray.setToolTip("This desktop has no system tray, so closing the window quits.")
        cv.addWidget(tray)
        auto = QCheckBox("Start when I sign in")
        hidden = QCheckBox("Start in the tray")
        auto.setChecked(autostart.is_enabled())
        hidden.setContentsMargins(22, 0, 0, 0)

        def sync_hidden():
            """Ticked only when it would do something: with sign-in start off it read
            as on by default. The saved choice is kept for when that's turned on."""
            on = auto.isChecked()
            hidden.blockSignals(True)
            hidden.setChecked(on and mw.cfg.autostart_hidden)
            hidden.blockSignals(False)
            hidden.setEnabled(on)
        sync_hidden()

        def set_auto(on: bool):
            if not mw.set_autostart(on):
                auto.blockSignals(True)
                auto.setChecked(autostart.is_enabled())
                auto.blockSignals(False)
                busy.toast(self, "Couldn't change Windows startup — see the log in "
                           r"%APPDATA%\OnionBoard.", "warn")
            sync_hidden()
        auto.toggled.connect(set_auto)
        hidden.toggled.connect(mw.set_autostart_hidden)
        if not autostart.available():
            auto.setEnabled(False)
            hidden.setEnabled(False)
        cv.addWidget(auto)
        cv.addWidget(hidden)
        return card

    # ------------------------------------------------------------------ backup
    def _backup_card(self):
        card, cv = self._card("Backup",
                              "Export puts every sound (with its picture, effects, hotkey and "
                              "categories) and your settings into one .zip: keep it safe, or "
                              "import it on another PC. Importing a friend's sound pack adds "
                              "its sounds; ones you already have are skipped.")
        row = QHBoxLayout()
        exp = QPushButton("Export everything…")
        icons.set_icon(exp, "folder")
        def export():
            mw = self.mw
            mw.export_board()
            if mw._exporting:   # it started (not cancelled in the save dialog)
                busy.hold_until(exp, "Exporting…", mw.bridge.exported,
                                lambda _p, _n, err: "Didn't export" if err else "✓ Exported")
        exp.clicked.connect(export)
        imp = QPushButton("Import…")
        imp.clicked.connect(self.mw.import_dialog)
        row.addWidget(exp)
        row.addWidget(imp)
        row.addStretch(1)
        cv.addLayout(row)
        return card

    # ------------------------------------------------------------------ data & quality
    def _data(self):
        """Settings > Data & quality (soundboard.quality): download size, keeping the
        video, radio bitrate and patience, search extras. Each applies at once."""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtWidgets import QFileDialog, QSizePolicy

        from soundboard import library, quality
        q = quality.current
        w, v = self._page()
        self._data_widgets = {}

        card, cv = self._card("Low data mode",
                              "For a phone hotspot, capped plan or slow internet: smaller "
                              "downloads, lower-bitrate radio, more patience with stations "
                              "that cut out, and no pictures or like counts in web search "
                              "results. Or pick each one below.")
        self.data_low = QCheckBox("Use less data")
        self.data_low.toggled.connect(
            lambda b: self._data_set(**(quality.LOW if b else quality.NORMAL)))
        cv.addWidget(self.data_low)
        v.addWidget(card)

        card, cv = self._card("Downloads",
                              "Sounds added from YouTube, SoundCloud and other links. "
                              "Smaller files are about a third of the size (around 0.5 MB "
                              "a minute instead of 1.5 MB) and still sound fine on a pad.")
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.addWidget(QLabel("Quality"), 0, 0)
        dl = QComboBox()
        for key, (label, _fmt) in quality.DOWNLOADS.items():
            dl.addItem(label, key)
        dl.currentIndexChanged.connect(lambda _i: self._data_set(download=dl.currentData()))
        grid.addWidget(dl, 0, 1)
        grid.setColumnStretch(1, 1)
        cv.addLayout(grid)
        self._data_widgets["download"] = dl
        has_ff = library._ffmpeg() is not None
        self._data_widgets["save_video"] = self._option(
            cv, "Also save the video",
            "Add as sound keeps a copy of the video too (the pad is still just its "
            "sound). Videos use a lot more data: about 5 to 25 MB a minute."
            + ("" if has_ff else " Without ffmpeg installed only lower-quality "
                                 "videos can be saved (usually 360p)."),
            q.save_video, lambda b: self._data_set(save_video=b))
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setContentsMargins(26, 0, 0, 0)
        grid.addWidget(QLabel("Video quality"), 0, 0)
        vh = QComboBox()
        for h in quality.VIDEO_HEIGHTS:
            vh.addItem(f"Up to {h}p", h)
        vh.currentIndexChanged.connect(lambda _i: self._data_set(video_height=vh.currentData()))
        grid.addWidget(vh, 0, 1)
        self._data_widgets["video_height"] = vh
        grid.addWidget(QLabel("Save videos in"), 1, 0)
        self.data_folder = QLabel()
        self.data_folder.setObjectName("hint")
        self.data_folder.setTextInteractionFlags(Qt.TextSelectableByMouse)
        # a path has no spaces to wrap at: it gets cut short instead of widening the page
        self.data_folder.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        grid.addWidget(self.data_folder, 1, 1)
        row = _button_row()
        change = QPushButton("Change…")

        def pick():
            folder = QFileDialog.getExistingDirectory(self, "Save videos in",
                                                      str(quality.current.videos()))
            if folder:
                self._data_set(video_dir=folder)
        change.clicked.connect(pick)
        row.addWidget(change)
        show = QPushButton("Open folder")

        def open_folder():
            folder = quality.current.videos()
            folder.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        show.clicked.connect(open_folder)
        row.addWidget(show)
        grid.addLayout(row, 2, 1)
        grid.setColumnStretch(1, 1)
        cv.addLayout(grid)
        self._data_video_rows = (vh, change, show, self.data_folder)
        v.addWidget(card)

        card, cv = self._card("Radio",
                              "Lower bitrates use less data: 128 kbps is about 58 MB an "
                              "hour, 64 kbps about 29 MB and 32 kbps about 14 MB. With a "
                              "limit, the map and search only show stations at or under it "
                              "(and ones that don't say).")
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.addWidget(QLabel("Stations"), 0, 0)
        kb = QComboBox()
        for kbps, label in quality.RADIO_KBPS.items():
            kb.addItem(label, kbps)
        kb.currentIndexChanged.connect(lambda _i: self._data_radio(kb.currentData()))
        grid.addWidget(kb, 0, 1)
        grid.setColumnStretch(1, 1)
        cv.addLayout(grid)
        self._data_widgets["radio_kbps"] = kb
        self._data_widgets["patient"] = self._option(
            cv, "Slow or patchy connection",
            "Gives a station longer to start and to come back after it cuts out (on mobile "
            "data or weak Wi-Fi) before the Radio tab gives up on it.",
            q.patient, lambda b: self._data_set(patient=b))
        v.addWidget(card)

        card, cv = self._card("Sounds from the web")
        self._data_widgets["web_extras"] = self._option(
            cv, "Show pictures and like counts",
            "Search results load each video's thumbnail and look up its likes and "
            "comments. Off: just the titles, a lot less data per search.",
            q.web_extras, lambda b: self._data_set(web_extras=b))
        v.addWidget(card)
        v.addStretch(1)
        self._data_sync()
        return w

    _data_syncing = False

    def _data_set(self, **kw):
        from soundboard import quality
        if self._data_syncing:
            return
        self.mw.set_option("data", quality.change(**kw))
        self._data_sync()

    def _data_radio(self, kbps):
        """A new bitrate cap: the map's list follows (a lower cap trims the saved list,
        a higher one fetches it again)."""
        from soundboard import quality
        if self._data_syncing:
            return
        old = quality.current.radio_kbps
        self._data_set(radio_kbps=kbps)
        tab = getattr(self.mw, "radio", None)
        directory = getattr(tab, "dir", None)
        if directory is not None and getattr(tab, "_started", False) and kbps != old:
            directory.load_globe(force=not kbps or bool(old and kbps > old))

    def _data_sync(self):
        """Every control on the page shows quality.current."""
        from soundboard import quality
        q = quality.current
        self._data_syncing = True
        try:
            self.data_low.setChecked(q.low_data)
            for key, wdg in self._data_widgets.items():
                val = getattr(q, key)
                if isinstance(wdg, QComboBox):
                    wdg.setCurrentIndex(max(0, wdg.findData(val)))
                else:
                    wdg.setChecked(val)
            for wdg in self._data_video_rows:
                wdg.setEnabled(q.save_video)
            self.data_folder.setText(str(q.videos()))
            self.data_folder.setToolTip(str(q.videos()))
        finally:
            self._data_syncing = False

    # ------------------------------------------------------------------ privacy & security
    def _privacy(self):
        w, v = self._page()
        v.addWidget(self._switches_card())
        v.addWidget(self._online_card())
        v.addStretch(1)
        return w

    def _connection(self):
        w, v = self._page()
        v.addWidget(self._connection_card())
        v.addWidget(self._activity_card())
        v.addStretch(1)
        return w

    def _activity_card(self):
        """Network activity: every connection the app has made (soundboard.netlog)."""
        from soundboard.ui.netactivity import NetActivity
        card, cv = self._card("Network activity")
        self.net_activity = NetActivity(card)
        cv.addWidget(self.net_activity)
        self.netlog_keep_box = self._option(
            cv, "Keep a history between starts",
            "Saves this list on this PC (network-activity.jsonl in the app's folder) and "
            "shows it again next time (the last 1000; Totals adds up all of it). Nothing is "
            "sent anywhere. Unticking it deletes the saved file; Clear empties it.",
            self.mw.cfg.netlog_keep, self._set_netlog_keep)
        return card

    def _set_netlog_keep(self, on: bool):
        from soundboard import library, netlog
        self.mw.set_option("netlog_keep", on)
        netlog.keep(library.APP_DIR / netlog.FILE_NAME if on else None)
        self.net_activity.refresh(force=True)

    def _option(self, cv, text: str, hint: str, on: bool, changed):
        """A checkbox with a short label and its explanation underneath (a long label
        can't wrap, and would make the whole page wider than the window)."""
        box = QCheckBox(text)
        box.setChecked(on)
        box.toggled.connect(changed)
        cv.addWidget(box)
        h = QLabel(hint)
        h.setObjectName("hint")
        h.setWordWrap(True)
        h.setContentsMargins(26, 0, 0, 4)   # under the box's text, not its tick
        cv.addWidget(h)
        return box

    # what each switch contacts, and when (soundboard.net.FEATURES)
    NET_HINTS = {
        "sounds_web": "Searches and pasted links on the Sounds tab go to that site, and "
                      "search results show its thumbnails. Off: the search bar only "
                      "searches your own sounds.",
        "ytdlp_update": "Fetches a newer yt-dlp from PyPI when you press Update now or "
                        "Reset downloader (Updates page), or by itself if you ticked "
                        "Update automatically there.",
        "radio": "The station directory (Radio Browser) and the stations you play. Off: "
                 "the Radio tab contacts nobody.",
        "app_update": "Asks GitHub for the latest release, and downloads its installer "
                      "when you press Update now.",
        "addons": "GitHub, for Onion Watch (Triggers tab) and its updates, and the "
                  "packages an add-on's Install step downloads (pip).",
        "voices": "Translation models (Voice tab), live voice's speech model (Hugging "
                  "Face) and Windows' own voices (Windows Update). Off: live voice still "
                  "works with a model it already has.",
        "voice_servers": "Voices in your voices folder that are a server on the "
                         "internet. Ones on this PC (127.0.0.1) always work.",
        "setup_downloads": "The setup guide's Install button downloads VB-Cable (the "
                           "virtual cable) from vb-audio.com. Not needed if your sounds go "
                           "straight into your mic, to another device or nowhere. Off: "
                           "install it yourself from there.",
        "tor_download": "Get Tor / Update Tor (Connection page) downloads Tor from the "
                        "Tor Project (dist.torproject.org). Off: a Tor that's already "
                        "here still works.",
        "usage_stats": "Once a day, the installed app sends an anonymous \"still here\" "
                       "to our counter (goatcounter.com): the version number and a random "
                       "ID made on this PC, so nobody is counted twice. Nothing else: no "
                       "name, sounds, settings or games. It's how we know if anyone uses "
                       "Onion Board. Off: nothing is sent.",
    }

    def _switches_card(self):
        """Every feature that goes online, each with its own switch (soundboard.net
        enforces them: off means no connection at all, in any Connection mode), and
        Offline mode over all of them."""
        from soundboard import net
        cfg = self.mw.cfg
        card, cv = self._card(
            "What goes online",
            "Onion Board has no account or ads. The only thing it sends us is the "
            "anonymous usage count below, if it's on. These are the only things that go "
            "online. Switch off what you don't want: "
            "off means it makes no connection at all, whatever the Connection setting.")
        self.offline_box = self._option(
            cv, "Offline mode",
            "Nothing goes online at all: every switch below is off until you untick this.",
            cfg.net_offline, self._set_offline)
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 4, 0, 0)
        bl.setSpacing(8)
        self._net_body = body
        self.net_boxes: dict[str, QCheckBox] = {}
        self._net_subs: dict[str, QWidget] = {}
        groups = (
            ("Sounds and radio", ("sounds_web", "radio")),
            ("Voices", ("voices", "voice_servers")),
            ("Updates and add-ons", ("app_update", "ytdlp_update", "addons")),
            ("Setup downloads", ("setup_downloads", "tor_download")),
            ("Usage count", ("usage_stats",)),
        )
        labels = {"sounds_web": "Online sounds", "app_update": "App updates",
                  "ytdlp_update": "Downloader updates", "addons": "Add-on downloads",
                  "voices": "Voice and model downloads", "voice_servers": "Online voice servers",
                  "setup_downloads": "Virtual cable download", "tor_download": "Tor download",
                  "usage_stats": "Count me in"}
        for title, keys in groups:
            section, sv = self._card(title)
            for key in keys:
                self.net_boxes[key] = self._option(
                    sv, labels.get(key, net.FEATURES[key]), self.NET_HINTS[key],
                    key not in cfg.net_off, lambda on, k=key: self._set_feature(k, on))
                sub = QWidget()
                sl = QVBoxLayout(sub)
                sl.setContentsMargins(26, 0, 0, 0)
                sl.setSpacing(6)
                self._net_sub_options(key, sl)
                if sl.count():
                    sv.addWidget(sub)
                    self._net_subs[key] = sub
            bl.addWidget(section)
        cv.addWidget(body)
        note = QLabel("Not covered by these: links you open in your own browser (Support, "
                      "Report a problem, release pages) and the installer's own downloads.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        cv.addWidget(note)
        self._net_sync()
        return card

    def _net_sub_options(self, key: str, sl):
        """The options that belong to one switch, indented under it."""
        from soundboard import net
        cfg = self.mw.cfg
        if key == "sounds_web":
            row = QGridLayout()
            row.setHorizontalSpacing(14)
            for i, (site, name) in enumerate(net.SITES.items()):
                k = f"sounds_web.{site}"
                b = QCheckBox("Other links" if site == "other" else name)
                b.setChecked(k not in cfg.net_off)
                b.toggled.connect(lambda on, k=k: self._set_feature(k, on))
                self.net_boxes[k] = b
                row.addWidget(b, i // 2, i % 2)
            sl.addLayout(row)
            h = QLabel("YouTube also covers YouTube Music and the TikTok search button "
                       "(TikTok's own search needs an account, so it finds TikTok sounds "
                       "on YouTube). Other: any other site's link, including pasted "
                       "TikTok links, which still download from TikTok.")
            h.setObjectName("hint")
            h.setWordWrap(True)
            sl.addWidget(h)
        elif key == "radio":
            def count_plays(on: bool):
                cfg.radio["count_plays"] = on
                self.mw.set_option("radio", cfg.radio)   # saves
            self.plays_box = self._option(
                sl, "Share play counts",
                "Radio Browser ranks stations by how often they're played. Off: starting a "
                "station only contacts the station itself.",
                bool(cfg.radio.get("count_plays", False)), count_plays)
        elif key in ("app_update", "ytdlp_update"):
            go = QPushButton("Update settings")
            go.clicked.connect(lambda: self.tabs.setCurrentIndex(self._page_keys.index("updates")))
            sl.addWidget(go, 0, Qt.AlignLeft)

    def _set_feature(self, key: str, on: bool):
        from soundboard import net
        cfg = self.mw.cfg
        off = [k for k in cfg.net_off if k != key] + ([] if on else [key])
        self.mw.set_option("net_off", off)   # saves
        net.configure_features(cfg.net_off, cfg.net_offline)   # applies at once
        self._net_sync()

    def _set_offline(self, on: bool):
        from soundboard import net
        cfg = self.mw.cfg
        self.mw.set_option("net_offline", on)
        net.configure_features(cfg.net_off, cfg.net_offline)
        self._net_sync()

    def _net_sync(self):
        """Grey out what's under a switch that's off (everything, in Offline mode), and
        the buttons on other pages that would go online for it."""
        from soundboard import net, torget
        body = getattr(self, "_net_body", None)   # None until its page is first shown
        if body is not None:
            if not qt_valid(body):
                return
            body.setEnabled(not net.offline())
            for key, sub in self._net_subs.items():
                sub.setEnabled(key not in self.mw.cfg.net_off)
        for keys, attr in ((("app_update",), "upd_btn"), (("app_update",), "upd_chk"),
                           (("ytdlp_update",), "ytdlp_auto_box")):
            w = getattr(self, attr, None)
            if w is not None and qt_valid(w):
                w.setEnabled(all(net.allowed(k) for k in keys))
                w.setToolTip("" if w.isEnabled() else net.off_message(keys[0]))
        for b in getattr(self, "ytdlp_btns", ()):
            if qt_valid(b):
                b.setEnabled(net.allowed("ytdlp_update"))
                b.setToolTip(b.property("tip") if b.isEnabled()
                             else net.off_message("ytdlp_update"))
        b = getattr(self, "net_get", None)
        if b is not None and qt_valid(b) and not busy.is_busy(b):
            b.setEnabled(net.allowed(torget.FEATURE))
            b.setToolTip(b.property("tip") if b.isEnabled()
                         else net.off_message(torget.FEATURE))

    def _online_card(self):
        """What goes online only when you do something, and the app's local doors."""
        card, cv = self._card(
            "Network information",
            "Everything else goes online only when you do it: a search or a pasted link "
            "goes to that site (YouTube, SoundCloud, TikTok, Myinstants), a radio station "
            "plays straight from that station, and a download you press fetches that one "
            "file. Those sites see your IP address like they would in a browser, unless "
            "you use a proxy or Tor (Connection page). The radio maps ship with the app: opening "
            "them contacts nobody.")
        remote = QLabel()
        remote.setWordWrap(True)
        on = self.mw.cfg.api_enabled
        remote.setText("Remote control is <b>on</b>: scripts and a Stream Deck on this PC "
                        "can play sounds with its key." if on else
                        "Remote control is <b>off</b>: nothing else on this PC can control "
                        "the app.")
        go = QPushButton("Remote settings")
        go.clicked.connect(lambda: self.tabs.setCurrentIndex(self._page_keys.index("remote")))
        cv.addWidget(remote)
        full = QPushButton("Network details")
        full.setToolTip("Opens the full list (SECURITY.md) on GitHub, in your browser")
        from soundboard.updates import REPO
        full.clicked.connect(lambda: busy.open_url(
            f"https://github.com/{REPO}/blob/main/SECURITY.md#what-the-app-does-on-the-network",
            full, self))
        row = _button_row()   # both under the text, on the left
        row.addWidget(go)
        row.addWidget(full)
        cv.addLayout(row)
        return card

    def _connection_card(self):
        """Connection: Direct, through a proxy, or through the app's own Tor
        (soundboard.net, soundboard.tor). Applies at once; a proxy or Tor that can't be
        reached makes requests fail, never go direct."""
        from PySide6.QtWidgets import QButtonGroup, QLineEdit, QRadioButton

        import logging

        from soundboard import net, tor, torget
        cfg = self.mw.cfg
        card, cv = self._card(
            "Connection",
            "Through a proxy or Tor, everything the app fetches (searches, downloads, "
            "radio, updates) goes through it, and site names are looked up there, not on "
            "this PC. If it can't be reached, nothing is fetched: the app never quietly "
            "goes direct. This PC's own addresses (127.0.0.1) stay direct.")
        direct = QRadioButton("Direct")
        direct.setToolTip("Connect straight to each site")
        via = QRadioButton("Through a proxy")
        via.setToolTip("A proxy of your own (or one your VPN app offers)")
        use_tor = QRadioButton("Tor")
        use_tor.setToolTip("The app's own Tor: sites and radio stations don't see your "
                           "address")
        group = QButtonGroup(card)
        row = QHBoxLayout()
        for b in (direct, via, use_tor):
            group.addButton(b)
            row.addWidget(b)
        row.addStretch(1)
        cv.addLayout(row)

        # ---- Get Tor: the app doesn't ship it (soundboard.torget)
        get_box = QWidget()
        row = QHBoxLayout(get_box)
        row.setContentsMargins(0, 0, 0, 0)
        get_note = QLabel()
        get_note.setObjectName("hint")
        get_note.setWordWrap(True)
        row.addWidget(get_note, 1)
        get = QPushButton("Get Tor")
        get.setProperty("tip", f"Download Tor {torget.VERSION} from the Tor Project "
                               "(dist.torproject.org), the way the Connection setting says")
        get.setToolTip(get.property("tip"))
        row.addWidget(get)
        cv.addWidget(get_box)

        def show_get(msg: str = ""):
            have = tor.available()
            outdated = (have and tor.bundle_dir() == torget.bin_dir()
                        and not torget.installed())
            use_tor.setEnabled(have)
            use_tor.setToolTip(
                "The app's own Tor: sites and radio stations don't see your address"
                if have else tor.NOT_INSTALLED)
            if not busy.is_busy(get):
                get.setText("Update Tor" if outdated else "Get Tor")
            get_box.setVisible(bool(msg) or busy.is_busy(get) or not have or outdated)
            get_note.setText(msg or (
                f"A newer Tor ({torget.VERSION}) is ready to download." if outdated else
                "To use Tor, get it first: about 22 MB from the Tor Project, checked "
                "before it's used. " + torget.BLOCKED_HINT))

        # ---- proxy
        proxy_box = QWidget()
        row = QHBoxLayout(proxy_box)
        row.setContentsMargins(0, 0, 0, 0)
        addr = QLineEdit(cfg.net_proxy)
        addr.setPlaceholderText("socks5h://127.0.0.1:9050  or  http://host:8080")
        addr.setToolTip("A SOCKS5 proxy (host names are looked up by the proxy) or an "
                        "HTTP proxy. Add user:password@ before the host if it needs a login.")
        row.addWidget(addr, 1)
        test = QPushButton("Test")
        test.setToolTip("Connect to GitHub through this proxy (only to see that it works)")
        row.addWidget(test)
        cv.addWidget(proxy_box)

        # ---- Tor
        tor_box = QWidget()
        tv = QVBoxLayout(tor_box)
        tv.setContentsMargins(0, 0, 0, 0)
        about = QLabel("Tor sends everything through three volunteer computers around the "
                       "world, so the sites you search and download from and the radio "
                       "stations you play see a Tor address, not yours. It's slower, and "
                       "YouTube often turns Tor away: the app then tries other Tor routes, "
                       "and only goes without Tor if you click to.")
        about.setObjectName("hint")
        about.setWordWrap(True)
        tv.addWidget(about)
        row = QHBoxLayout()
        tor_state = QLabel()
        tor_state.setWordWrap(True)
        row.addWidget(tor_state, 1)
        newnym = QPushButton("New identity")
        newnym.setToolTip("New connections go out through a different Tor route, so sites "
                          "see a different address")
        row.addWidget(newnym)
        tv.addLayout(row)
        row = QHBoxLayout()
        hide = QCheckBox("Hide that I'm using Tor")
        hide.setChecked(bool(cfg.tor_bridges))
        row.addWidget(hide)
        kind = QComboBox()
        kind.addItem("Snowflake", "snowflake")
        kind.addItem("obfs4", "obfs4")
        kind.setItemData(0, "Looks like a video call", Qt.ToolTipRole)
        kind.setItemData(1, "Looks like random noise", Qt.ToolTipRole)
        kind.setCurrentIndex(max(0, kind.findData(cfg.tor_bridges or tor.DEFAULT_BRIDGE)))
        kind.setToolTip("If one doesn't connect, try the other")
        no_wheel(kind)
        row.addWidget(kind)
        row.addStretch(1)
        tv.addLayout(row)
        hide_hint = QLabel("Disguises the connection so your internet provider can't easily "
                           "tell it's Tor. Helps where Tor is blocked or frowned on. It's "
                           "slower, and connecting can take a few minutes.")
        hide_hint.setObjectName("hint")
        hide_hint.setWordWrap(True)
        hide_hint.setContentsMargins(26, 0, 0, 0)   # under the box's text, not its tick
        tv.addWidget(hide_hint)
        cv.addWidget(tor_box)

        note = QLabel()
        note.setObjectName("hint")
        note.setWordWrap(True)
        cv.addWidget(note)
        {net.TOR: use_tor, net.PROXY: via}.get(cfg.net_mode, direct).setChecked(True)

        def show():
            if not qt_valid(note):
                return
            proxy_box.setVisible(via.isChecked())
            addr.setEnabled(via.isChecked())
            test.setEnabled(via.isChecked())
            tor_box.setVisible(use_tor.isChecked())
            note.setVisible(not use_tor.isChecked())
            kind.setEnabled(hide.isChecked())
            t = tor.manager()
            tor_state.setText(t.status_text())
            color = {tor.READY: "ok", tor.FAILED: "error"}.get(t.state)
            tor_state.setStyleSheet(f"color: {theme.status(color)}" if color else "")
            if not busy.is_busy(newnym):
                newnym.setEnabled(t.state == tor.READY)
            if via.isChecked():
                try:
                    net.parse(addr.text())
                except ValueError as e:
                    note.setText(f"{e}. Until it's fixed, nothing goes online.")
                    return
            note.setText(f"Now: {net.describe()}.")

        def apply():
            mode = (net.TOR if use_tor.isChecked() else
                    net.PROXY if via.isChecked() else net.DIRECT)
            text = addr.text().strip()
            bridges = kind.currentData() if hide.isChecked() else ""
            if (mode, text, bridges) != (cfg.net_mode, cfg.net_proxy, cfg.tor_bridges):
                self.mw.set_option("net_mode", mode)     # saves
                self.mw.set_option("net_proxy", text)
                self.mw.set_option("tor_bridges", bridges)
                tor.configure_from(cfg)                  # before net: its gate needs it
                net.configure(mode, text)
                if mode == net.TOR:
                    tor.manager().start()   # picked here: connect now and show how far
            show()

        for b in (direct, via, use_tor):
            b.toggled.connect(lambda on: on and apply())
        addr.editingFinished.connect(apply)
        hide.toggled.connect(lambda _on: apply())
        kind.currentIndexChanged.connect(lambda _i: apply())
        status = tor.qt_status()
        status.changed.connect(show)

        def unhook(*_):
            try:
                status.changed.disconnect(show)
            except (RuntimeError, TypeError):
                pass
        card.destroyed.connect(unhook)

        def run_newnym():
            release = busy.hold(newnym, "Changing…")
            relay = _Relay(self.mw)   # outlives this window if it's closed meanwhile

            def finish(msg):
                relay.deleteLater()
                release("✓ Changed" if msg.startswith("New identity") else "✗ Failed")
                if qt_valid(tor_state):
                    tor_state.setText(msg)

            relay.done.connect(finish)
            threading.Thread(target=lambda: relay.done.emit(tor.new_identity()),
                             daemon=True, name="tor-newnym").start()
        newnym.clicked.connect(run_newnym)

        def run_get():
            release = busy.hold(get, "Downloading…")
            relay = _ProgressRelay(self.mw)   # outlives this window if it's closed meanwhile

            def progress(done, total):
                if qt_valid(get_note):
                    get_note.setText(f"Downloading Tor… {done / 1e6:.1f}" + (
                        f" of {total / 1e6:.1f} MB" if total else " MB"))

            def finish(err):
                relay.deleteLater()
                release("✗ Failed" if err else "✓ Got Tor")
                if qt_valid(get_note):
                    show_get(err or f"Tor {torget.VERSION} is ready: pick Tor above to "
                                    "use it.")
                    show()
                    self._net_sync()

            def work():
                from soundboard import netlog
                netlog.cause(torget.FEATURE, "You clicked to download Tor (Settings > "
                                             "Connection)")
                try:
                    # a running Tor may have carried the download: stopped before its
                    # files are swapped, the next connection starts the new one
                    torget.get(relay.progress.emit, before_unpack=tor.shutdown)
                    relay.done.emit("")
                except torget.GetError as e:
                    relay.done.emit(errors.plain(e))
                except Exception as e:  # noqa: BLE001 - shown, never a stuck button
                    logging.getLogger(__name__).exception("Get Tor failed")
                    relay.done.emit(f"Couldn't get Tor ({errors.plain(e)}).")

            relay.progress.connect(progress)
            relay.done.connect(finish)
            threading.Thread(target=work, daemon=True, name="tor-get").start()
        get.clicked.connect(run_get)

        def run_test():
            text = addr.text()
            release = busy.hold(test, "Testing…")
            relay = _Relay(self.mw)   # outlives this window if it's closed meanwhile

            def finish(msg):
                relay.deleteLater()
                release("✓ Works" if msg.startswith("It works") else "✗ Failed")
                if qt_valid(note):
                    note.setText(msg)

            relay.done.connect(finish)

            def run():
                from soundboard import netlog
                netlog.cause(net.TEST, "You clicked Test (Settings > Connection)")
                try:
                    msg = net.test(text)
                except (ValueError, OSError) as e:
                    msg = f"It didn't work: {errors.plain(e)}"
                relay.done.emit(msg)
            threading.Thread(target=run, daemon=True, name="proxy-test").start()
        test.clicked.connect(run_test)
        self.net_direct, self.net_via, self.net_addr, self.net_test = direct, via, addr, test
        self.net_tor, self.net_hide, self.net_bridge = use_tor, hide, kind
        self.net_tor_state, self.net_newnym = tor_state, newnym
        self.net_get, self.net_get_note = get, get_note
        self.net_note = note
        show_get()
        show()
        self._net_sync()   # Get Tor switched off: greyed, with the reason
        return card

    # ------------------------------------------------------------------ app updates
    def _updates_card(self):
        from soundboard import __version__, updates
        how = ("Update now downloads it and checks it's the file GitHub lists; you pick "
               "when the app restarts to install it. Your sounds and settings are kept."
               if updates.can_install() else
               "This copy runs from source, so it only tells you: update it with git pull.")
        card, cv = self._card("App updates",
                              f"This is Onion Board {__version__}. With the box ticked it asks "
                              "GitHub every few hours whether a newer version is out and tells you "
                              "(with a banner if it's an important fix). "
                              + how)
        chk = self._option(cv, "Check for updates",
                           "Tell me when a new version is out. Nothing is downloaded "
                           "until I press Update now.", self.mw.cfg.update_check,
                           self._updates_optin)
        self.upd_chk = chk
        row = QHBoxLayout()
        self.upd_label = QLabel()
        self.upd_label.setObjectName("hint")
        self.upd_label.setWordWrap(True)
        # the button first, its result beside it: on the right with nothing yet to
        # say, it sat on a line of its own far from everything else
        self.upd_btn = QPushButton("Check now")
        self.upd_btn.clicked.connect(self._updates_check)
        row.addWidget(self.upd_btn)
        row.addWidget(self.upd_label, 1)
        cv.addLayout(row)
        self.mw.update_done.connect(self._updates_done)
        self._net_sync()   # off in Settings > Privacy: greyed, with the reason
        return card

    def _updates_optin(self, on: bool):
        self.mw.set_option("update_check", on)
        if on:
            self.mw.check_updates(why="You turned on update checks")

    def _updates_check(self):
        self._upd_asked = True
        self.upd_btn.setEnabled(False)
        self.upd_label.setText("Checking…")
        self.mw.check_updates(force=True, why="You clicked Check now (Settings > Updates)")

    def _updates_done(self, rel, err: str):
        if not qt_valid(self.upd_label):
            return
        self.upd_btn.setEnabled(True)
        self._net_sync()
        asked, self._upd_asked = getattr(self, "_upd_asked", False), False
        if err:
            self.upd_label.setText(f"Couldn't check: {errors.plain(err)}")
        elif rel is None:
            # a check the user didn't ask for may not have asked GitHub at all (done
            # today already, or the newer version was skipped): don't claim anything
            if asked:
                self.upd_label.setText("You have the newest version.")
        else:
            self.upd_label.setText(f"Version {rel.version} is out.")

    def done(self, r):
        try:
            self.mw.update_done.disconnect(self._updates_done)
        except (RuntimeError, TypeError):
            pass
        super().done(r)

    # ------------------------------------------------------------------ remote control
    def _remote_card(self):
        """The local control API (soundboard.remote): on / off, port, key."""
        from PySide6.QtWidgets import QApplication, QLineEdit, QSpinBox

        from soundboard import remote
        mw, cfg = self.mw, self.mw.cfg
        card, cv = self._card("Remote control (Stream Deck, scripts)",
                              "Lets programs on this PC play your sounds: a Stream Deck (its "
                              "API-request or website buttons, Bitfocus Companion, Touch "
                              "Portal), AutoHotkey or a script. Only this PC can connect, and "
                              "only with the key below — treat it like a password.")
        on = QCheckBox("Enable remote control")
        on.setChecked(cfg.api_enabled)
        cv.addWidget(on)
        row = QGridLayout()
        row.addWidget(QLabel("Port"), 0, 0)
        port = QSpinBox()
        port.setRange(1024, 65535)
        port.setValue(cfg.api_port)
        port.setAccessibleName("Port")
        no_wheel(port)
        row.addWidget(port, 0, 1)
        row.addWidget(QLabel("Key"), 1, 0)
        key = QLineEdit()
        key.setReadOnly(True)
        key.setEchoMode(QLineEdit.Password)
        key.setAccessibleName("Key")
        row.addWidget(key, 1, 1)
        show = QPushButton("Show")
        show.setCheckable(True)
        show.toggled.connect(lambda b: key.setEchoMode(QLineEdit.Normal if b
                                                       else QLineEdit.Password))
        row.addWidget(show, 1, 2)
        new = QPushButton("New key")
        new.setToolTip("Make a new key: anything using the old one stops working")
        row.addWidget(new, 1, 3)
        cv.addLayout(row)
        crow = QHBoxLayout()
        copy = QPushButton("Copy an example link")
        copy.setToolTip("A link that plays a random sound — paste it into a Stream Deck "
                        "website / API-request button, or open it to try it")
        crow.addWidget(copy)
        state = QLabel()
        state.setObjectName("hint")
        state.setWordWrap(True)
        crow.addWidget(state, 1)
        cv.addLayout(crow)
        help_ = QLabel("Endpoints: " + " · ".join(f"/api/{a}" for a in remote.ENDPOINTS)
                       + ". E.g. /api/play?name=Airhorn, /api/random?category=Memes, "
                       "/api/live?on=toggle. Send the key as ?token=…, an X-Token header "
                       "or Authorization: Bearer …. /api/help describes each one.")
        help_.setObjectName("hint")
        help_.setWordWrap(True)
        help_.setTextInteractionFlags(Qt.TextSelectableByMouse)
        cv.addWidget(help_)

        def refresh(err: str = ""):
            key.setText(cfg.api_token)
            for w in (port, key, show, new, copy):
                w.setEnabled(cfg.api_enabled)
            if not cfg.api_enabled:
                state.setText("Off.")
            elif err or not mw.remote.running:
                state.setText(f"Couldn't start: {err or mw.remote.error}")
            else:
                state.setText(f"On: listening on {remote.HOST}:{mw.remote.port}.")

        def set_on(b: bool):
            cfg.api_enabled = b
            cfg.save()
            refresh(mw.apply_remote())

        def set_port():
            if port.value() != cfg.api_port:
                cfg.api_port = port.value()
                cfg.save()
                refresh(mw.apply_remote())

        def new_key():
            cfg.api_token = remote.new_token()
            cfg.save()
            refresh(mw.apply_remote())
            busy.flash(new, "✓ New key made")
            if mw.remote.running:
                state.setText("New key made: anything using the old one has stopped working. "
                              "Copy the example link for the new one.")

        def copy_link():
            QApplication.clipboard().setText(
                f"http://{remote.HOST}:{cfg.api_port}/api/random?token={cfg.api_token}")
            state.setText("Copied. It holds your key: only paste it into your own tools.")

        on.toggled.connect(set_on)
        port.editingFinished.connect(set_port)
        new.clicked.connect(new_key)
        copy.clicked.connect(copy_link)
        refresh()
        self.remote_on = on   # the streamer guide can turn it on: keep the box in step
        return card

    def _remote_addon_cards(self) -> list:
        """The cards of the "remote" add-ons (soundboard.modules), e.g. Onion Pocket.
        They're optional: one that's broken is left out (it's in the log), never an
        error box. Without a working Onion Pocket, a card offering to get it."""
        from soundboard import pocketaddon
        out, have = [], set()
        for info, addon in getattr(self.mw, "remote_addons", []):
            card = self._addon_card(info, addon)
            if card is not None:
                if info.id == pocketaddon.MODULE_ID:
                    self._pocket_update(card, info)
                    self._pocket_remove_button(card, info)
                    self._pocket_slot = card
                out.append(card)
                have.add(info.id)
        if pocketaddon.MODULE_ID not in have and pocketaddon.offered():
            self._pocket_slot = self._get_pocket_card()
            out.append(self._pocket_slot)
        return out

    # ------------------------------------------------------------ Onion Pocket: remove
    def _pocket_info(self):
        """The installed Onion Pocket the app knows of (running or not), or None."""
        from soundboard import pocketaddon
        return next((i for i, _a in getattr(self.mw, "remote_addons", [])
                     if i.id == pocketaddon.MODULE_ID), None)

    def _pocket_remove_button(self, card, info):
        """*Remove Onion Pocket…* at the foot of its own card on Settings → Remote."""
        from soundboard import pocketaddon
        lay = card.layout()
        if lay is None or not pocketaddon.removable(info):
            return
        btn = QPushButton("Remove Onion Pocket…")
        btn.setToolTip("Takes the add-on out of Onion Board: phones can't play your pads "
                       "any more. Paired phones are kept for when you get it again.")
        icons.set_icon(btn, "trash", "danger_text")
        btn.clicked.connect(lambda: self._remove_pocket(btn))
        row = _button_row()
        row.addWidget(btn)
        lay.addLayout(row)
        self.pocket_remove = btn

    def _swap_pocket_slot(self, new):
        """Put `new` (a card, or None) where Onion Pocket's card is on Settings →
        Remote, if that page is built."""
        old = getattr(self, "_pocket_slot", None)
        self._pocket_slot = new
        if old is None or not qt_valid(old):
            return
        lay = old.parentWidget().layout() if old.parentWidget() else None
        if new is not None and lay is not None:
            lay.insertWidget(lay.indexOf(old), new)
        old.hide()
        old.deleteLater()

    def _pocket_changed(self):
        refresh = getattr(self, "_pocket_refresh", None)
        if refresh is not None:
            refresh()

    def _remove_pocket(self, btn):
        """Uninstall Onion Pocket, after asking: its server stops, and its card on
        Settings → Remote turns back into *Get Onion Pocket*."""
        from PySide6.QtWidgets import QMessageBox

        from soundboard import modules, pocketaddon
        info = self._pocket_info()
        if info is None:
            return
        if QMessageBox.question(
                self, "Remove Onion Pocket?",
                "Remove the Onion Pocket add-on from Onion Board? Phones won't be able to "
                "play your pads any more. Paired phones are kept for when you get it "
                "again.\n\nYou can get it again from Settings → Remote any time.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            self.mw.remove_remote_addon(info)
        except modules.ModuleError as e:
            log.warning("Onion Pocket couldn't be removed: %s", e)
            QMessageBox.warning(self, "Onion Pocket wasn't removed",
                                f"Onion Pocket wasn't removed: {errors.plain(e)}")
            return
        self.mw.pocket_offer = None
        if getattr(self, "_pocket_slot", None) is not None:
            self._swap_pocket_slot(self._get_pocket_card() if pocketaddon.offered()
                                   else None)
        self._pocket_changed()
        busy.toast(self, "✓ Onion Pocket removed.", "ok")

    def _addon_card(self, info, addon):
        if addon is None:
            log.info("remote add-on %s left out of Settings: %s", info.id, info.error)
            return None
        try:
            return addon.card(self)
        except Exception as e:  # noqa: BLE001 - an add-on can't break Settings
            log.exception("add-on %s couldn't make its card", info.id)
            info.error = f"its settings failed: {errors.plain(e)}"
            return None

    POCKET_CHECK_S = 3600   # how often Settings → Remote asks GitHub for a newer one

    def _pocket_update(self, card, info):
        """*Update Onion Pocket to X* on its card (soundboard.pocketaddon), once GitHub
        says a newer one is out: asked on a thread when Settings → Remote opens, at most
        once an hour (the answer is kept on the main window). Clicking it downloads the
        new one, and the main window swaps it in for the running copy, settings and
        all; then its new card takes this one's place. Optional and quiet: if anything
        fails, the old copy keeps running and the button just says it didn't work."""
        from soundboard import net, netlog, pocketaddon, updates
        mw = self.mw
        lay = card.layout()
        if lay is None:
            return

        class Relay(QObject):
            found = Signal(object)
            done = Signal(object)

        btn = QPushButton()
        btn.setObjectName("primary")
        btn.hide()
        row = _button_row()
        row.addWidget(btn)
        lay.addLayout(row)
        found = Relay(card)
        state = {}

        def show(offer):
            if offer is None or not qt_valid(btn) or not updates.newer(offer.version,
                                                                       info.version):
                return
            state["offer"] = offer
            btn.setText(f"Update Onion Pocket to {offer.version}")
            btn.setToolTip(f"You have {info.version}. Downloads it from GitHub and "
                           "restarts Onion Pocket: paired phones stay paired.")
            btn.show()

        def checked(offer):
            mw.pocket_offer = offer
            show(offer)

        def finish(new, relay):
            relay.deleteLater()
            addon = mw.load_remote_addon(new) if new is not None else None
            if new is not None:
                mw.pocket_offer = None      # installed: on disk now, whatever happens
            if not qt_valid(btn):
                return                      # Settings was closed: it's loaded anyway
            if addon is None:
                state["release"]("Couldn't update it right now")
                if new is not None:
                    btn.hide()
                return
            box = card.parentWidget().layout() if card.parentWidget() else None
            fresh = self._addon_card(new, addon)
            if fresh is not None and box is not None:
                self._pocket_remove_button(fresh, new)
                self._pocket_slot = card
                self._swap_pocket_slot(fresh)
                self._pocket_changed()
            else:
                state["release"]()
                btn.hide()
            busy.toast(self, f"✓ Onion Pocket {html.escape(new.version)} is in.", "ok")

        def run():
            offer = state.get("offer")
            if offer is None:
                return
            state["release"] = busy.hold(btn, "Updating Onion Pocket…")
            netlog.cause(pocketaddon.FEATURE, "You clicked to update Onion Pocket "
                                              "(Settings > Remote)")
            relay = Relay(mw)   # the main window's: it's swapped in even if Settings closes
            relay.done.connect(lambda new: finish(new, relay))
            threading.Thread(target=lambda: relay.done.emit(pocketaddon.get(offer=offer)),
                             daemon=True, name="onion-pocket-update").start()

        btn.clicked.connect(run)
        found.found.connect(checked)
        self.pocket_update = btn
        offer = getattr(mw, "pocket_offer", None)
        if offer is not None:
            show(offer)
        elif (time.time() - getattr(mw, "pocket_checked", 0.0) >= self.POCKET_CHECK_S
              and (pocketaddon.local_zip() is not None or net.allowed(pocketaddon.FEATURE))):
            mw.pocket_checked = time.time()
            netlog.cause(pocketaddon.FEATURE, "Settings > Remote: is a newer Onion Pocket out?")
            def ask():
                offer = pocketaddon.check_update(info)
                try:
                    found.found.emit(offer)
                except RuntimeError:        # Settings was closed meanwhile
                    pass
            threading.Thread(target=ask, daemon=True, name="onion-pocket-check").start()

    def _get_pocket_card(self):
        """*Get Onion Pocket* (soundboard.pocketaddon): downloads, installs and starts
        it, then its own card takes this one's place. If that fails, this card just
        goes away; Onion Pocket is optional."""
        from soundboard import netlog, pocketaddon

        class Relay(QObject):
            done = Signal(object)

        card, cv = self._card("Onion Pocket: your pads on your phone",
                              "Scan a code with your phone's camera and tap a pad on the "
                              "phone to play it here. iPhone or Android, in the browser: "
                              "nothing to install on the phone. A free add-on from GitHub.")
        get = QPushButton("Get Onion Pocket")
        row = _button_row()
        row.addWidget(get)
        cv.addLayout(row)
        relay = Relay(card)

        def finish(info):
            if not qt_valid(card):
                return
            addon = self.mw.load_remote_addon(info) if info is not None else None
            new = self._addon_card(info, addon) if addon is not None else None
            if new is not None:
                self._pocket_remove_button(new, info)
            self._pocket_slot = card
            self._swap_pocket_slot(new)
            self._pocket_changed()

        def run():
            busy.hold(get, "Getting Onion Pocket…")
            netlog.cause(pocketaddon.FEATURE, "You clicked to get Onion Pocket "
                                              "(Settings > Remote)")
            threading.Thread(target=lambda: relay.done.emit(pocketaddon.get()),
                             daemon=True, name="onion-pocket").start()
        relay.done.connect(finish)
        get.clicked.connect(run)
        self.get_pocket = get
        return card

    def _remote_easy_card(self):
        """The easy way in: the streamer guide, and a prompt for an AI assistant."""
        from soundboard.ui.crashdialog import free_dialog
        from soundboard.ui.streamguide import StreamerGuide, copy_prompt
        mw = self.mw
        card, cv = self._card("Set it up the easy way",
                              "New to this? The streamer guide shows how to put your sounds "
                              "on Stream Deck keys, channel points and chat commands, step by "
                              "step. Or copy a ready-made message for ChatGPT, Claude or any "
                              "AI chat: it explains Onion Board's links and lists your "
                              "sounds, so the AI can set up whatever tools you use with you.")
        # side by side, wrapping (not widening the window) when Settings is narrow
        btns = _button_row()
        guide = QPushButton("Streamer guide…")
        guide.setObjectName("primary")
        btns.addWidget(guide)
        ai = QPushButton("Copy AI prompt")
        icons.set_icon(ai, "copy")
        ai.setToolTip("Paste it into ChatGPT / Claude and say which tools you use")
        btns.addWidget(ai)
        cv.addLayout(btns)
        with_key = QCheckBox("Put my key in the prompt")
        with_key.setToolTip("Saves pasting it in yourself. The key only works on this PC, "
                            "but it's still a password: leave this off if you'd rather the "
                            "AI never sees it")
        cv.addWidget(with_key)
        state = QLabel()
        state.setObjectName("hint")
        state.setWordWrap(True)
        cv.addWidget(state)

        def open_guide():
            g = StreamerGuide(self, mw)
            g.exec()
            free_dialog(g)
            box = getattr(self, "remote_on", None)
            if box is not None and box.isChecked() != mw.cfg.api_enabled:
                box.setChecked(mw.cfg.api_enabled)   # turned on there

        def copy_ai():
            state.setText(copy_prompt(mw, with_key.isChecked()))
            busy.flash(ai, "✓ Copied")

        guide.clicked.connect(open_guide)
        ai.clicked.connect(copy_ai)
        return card

    # ------------------------------------------------------------------ yt-dlp
    def _downloader_card(self):
        card, cv = self._card("Downloader (yt-dlp)",
                              "Searching YouTube / SoundCloud and adding a pasted link use "
                              "yt-dlp. YouTube changes often, so it needs updating now and "
                              "then. Nothing is downloaded unless you click Update now / "
                              "Reset, or tick the box below. If downloads keep failing even "
                              "after updating, Reset deletes it and its cache and installs a "
                              "fresh copy.")
        auto = self._option(cv, "Update automatically",
                            "Check PyPI once a day and after a failed download. Off by "
                            "default: an update is code the app runs.",
                            self.mw.cfg.ytdlp_auto_optin,
                            lambda b: self.mw.set_option("ytdlp_auto_optin", b))
        auto.setToolTip("Off by default: an update is code the app runs. It's checked against "
                        "PyPI's SHA-256 before it's used.")
        self.ytdlp_auto_box = auto
        row = _button_row()
        self.ytdlp_label = QLabel()
        self.ytdlp_label.setObjectName("hint")
        self.ytdlp_label.setWordWrap(True)
        cv.addWidget(self.ytdlp_label)
        self.ytdlp_btns = []
        for text, job, tip in (
                ("Update now", ytdl.update, "Check for a newer yt-dlp and install it"),
                ("Reset downloader", ytdl.reset,
                 "Delete the downloaded yt-dlp and its cache, then install a fresh copy")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setProperty("tip", tip)
            b.clicked.connect(lambda _=False, j=job, t=text: self._ytdlp_run(j, t))
            row.addWidget(b)
            self.ytdlp_btns.append(b)
        cv.addLayout(row)
        self._ytdlp_show()
        self._net_sync()
        return card

    def _ytdlp_show(self, msg: str = ""):
        v, downloaded = ytdl.active_version()
        where = "updated copy" if downloaded else "built in"
        now = f"In use: yt-dlp {v} ({where})." if v else "yt-dlp isn't installed."
        self.ytdlp_label.setText(f"{msg} {now}".strip())

    def _ytdlp_run(self, job, button: str = ""):
        from soundboard import netlog
        netlog.cause(ytdl.UPDATE_FEATURE, f"You clicked {button} (Settings > Updates)"
                     if button else "You asked to update the downloader")
        for b in self.ytdlp_btns:
            b.setEnabled(False)
        self.ytdlp_label.setText("Working…")
        relay = _Relay(self.mw)   # outlives this window if it's closed meanwhile

        def finish(msg):
            relay.deleteLater()
            if qt_valid(self.ytdlp_label):
                for b in self.ytdlp_btns:
                    b.setEnabled(True)
                self._net_sync()
                self._ytdlp_show(msg)

        relay.done.connect(finish)

        def run():
            try:
                msg = job()
            except Exception as e:  # noqa: BLE001 - offline, PyPI down…
                msg = f"Couldn't update: {errors.plain(e)}."
            relay.done.emit(msg)
        threading.Thread(target=run, daemon=True, name="ytdlp-settings").start()
