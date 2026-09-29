"""Settings window: themes, every global hotkey in one place, the in-game overlay,
general options."""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import (QBrush, QColor, QDesktopServices, QFont, QPainter, QPainterPath,
                           QPixmap)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QPushButton, QScrollArea, QSlider, QTabWidget,
                               QVBoxLayout, QWidget)

from shiboken6 import isValid as qt_valid

from soundboard import autostart, theme, winkeys, ytdl
from soundboard.ui import fit, icons
from soundboard.ui import overlay as ovl
from soundboard.wheelguard import no_wheel
from soundboard.winkeys import Hotkeys

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
    ]),
    ("Overlay", [
        ("overlay_hotkey", "__overlay__", "Open the in-game overlay",
         "Sound tiles over your game; pick one with the number keys. See the Overlay tab."),
    ]),
]
HOTKEY_ACTIONS = [a for _, group in HOTKEY_GROUPS for a in group]


def pretty_key(combo: str) -> str:
    if not combo:
        return ""

    def part(p: str) -> str:
        if len(p) > 1:
            return p.title()
        if not p.isalnum() and p in winkeys.VK:   # punctuation: as printed on this keyboard
            return (winkeys.key_char(winkeys.VK[p]) or p).upper()
        return p.upper()
    return "+".join(part(p.strip()) for p in combo.split("+"))


class HotkeyDialog(QDialog):
    def __init__(self, hotkeys: Hotkeys, parent=None):
        super().__init__(parent)
        fit.watch(self)   # grows to fit its text (ui/fit.py)
        self.setWindowTitle("Set hotkey")
        self.result_combo = None
        lay = QVBoxLayout(self)
        t = QLabel("Press the key or combo you want…")
        t.setStyleSheet("font-size:16px; font-weight:600;")
        lay.addWidget(t)
        self.hint = QLabel("Works globally, even while in-game.  Esc = cancel.")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        self._warned_vk = None
        self.setMinimumWidth(340)
        hotkeys.pause()   # so pressing an existing hotkey here doesn't trigger it

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
        p.setBrush(QBrush(QPixmap.fromImage(theme._carbon_image(t["panel"], 6)))
                   if t.get("texture") else QColor(t["panel"]))
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
        # name
        p.setPen(QColor(theme.T["text"]))
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(10, self.height() - 28, self.width() - 20, 22),
                   Qt.AlignLeft | Qt.AlignVCenter, self.name)
        p.end()


class SettingsDialog(QDialog):
    """All settings in one place. `mw` is the MainWindow; changes apply immediately."""

    def __init__(self, mw, page: str = "appearance"):
        super().__init__(mw)
        fit.watch(self)   # grows to fit its text (ui/fit.py)
        self.mw = mw
        self.setWindowTitle("Settings")
        self.setMinimumSize(720, 600)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._scroll(self._appearance()), "Appearance")
        self.hk_buttons: dict[str, list[QPushButton]] = {}
        self.tabs.addTab(self._scroll(self._hotkeys()), "Hotkeys")
        self.tabs.addTab(self._scroll(self._overlay()), "Overlay")
        self.tabs.addTab(self._scroll(self._general()), "General")
        for i, name in enumerate(("palette", "keyboard", "gamepad", "settings")):
            icons.set_tab_icon(self.tabs, i, name)
        self.tabs.setCurrentIndex(
            {"appearance": 0, "hotkeys": 1, "overlay": 2, "general": 3}.get(page, 0))
        lay.addWidget(self.tabs, 1)
        close = QPushButton("Done")
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)
        self._initial_size()

    # ------------------------------------------------------------------ pages
    @staticmethod
    def _scroll(page: QWidget) -> QScrollArea:
        """Pages scroll: a tall one (General) otherwise gets squashed, rows on top of
        each other, whenever the window can't grow to fit it (maximized, small screen)."""
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QScrollArea.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sa.setWidget(page)
        return sa

    def _initial_size(self):
        """Open big enough for the tallest page, as far as the screen allows (a scroll
        area on its own would open at its small default)."""
        screen = self.screen() or QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        width = 860
        need = 0
        for i in range(self.tabs.count()):
            lay = self.tabs.widget(i).widget().layout()
            need = max(need, lay.totalSizeHint().height(),
                       lay.totalHeightForWidth(width - 60) if lay.hasHeightForWidth() else 0)
        # tab bar, Done row, margins; a normal window size, not the whole screen: the
        # tall General page scrolls
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
        v.setContentsMargins(0, 12, 0, 0)
        v.setSpacing(12)
        return w, v

    def _appearance(self):
        w, v = self._page()
        card, cv = self._card("Theme", "Changes the whole app instantly.")
        grid = QGridLayout()
        grid.setSpacing(12)
        self.theme_cards = []
        for i, name in enumerate(theme.THEMES):
            c = ThemeCard(name)
            c.setChecked(name == theme.current_name)
            c.clicked.connect(lambda _=False, n=name: self._pick_theme(n))
            grid.addWidget(c, i // 4, i % 4)
            self.theme_cards.append(c)
        cv.addLayout(grid)
        v.addWidget(card)
        v.addStretch(1)
        return w

    def _pick_theme(self, name: str):
        self.mw.apply_theme(name)
        for c in self.theme_cards:
            c.setChecked(c.name == name)
            c.update()

    def _hotkeys(self):
        w, v = self._page()
        for group, actions in HOTKEY_GROUPS:
            card, cv = self._card(group)
            for attr, _action, label, desc in actions:
                self._hk_row(cv, attr, label, desc)
            v.addWidget(card)
        card, cv = self._card("Auto push-to-talk (optional)",
                              "Only if you use push-to-talk in a game or Discord: set your "
                              "push-to-talk key and the app holds it for you while a sound, "
                              "live radio or a program plays. Leave it Off for open mic.")
        self._hk_row(cv, "ptt_key", "Hold this key", "")
        v.addWidget(card)
        note = QLabel("Per-sound hotkeys: right-click a pad → Set hotkey. "
                      "All hotkeys work while you're in a game.")
        note.setObjectName("hint")
        note.setWordWrap(True)
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
        row.addWidget(b)
        x = QPushButton("✕")
        x.setObjectName("small")
        x.setToolTip("Clear")
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
        d = HotkeyDialog(self.mw.hotkeys, self)
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
        cv.addWidget(self._ov_combo("mode", ovl.MODES, s.mode))
        v.addWidget(card)

        card, cv = self._card("Pick sounds",
                              "Nine tiles a page, in the same order as your pads — drag pads in "
                              "the Sounds tab to rearrange them.")
        cv.addWidget(self._ov_combo("keys", ovl.KEY_CHOICES, s.keys))
        after = QCheckBox("Hide the overlay after picking a sound")
        after.setChecked(s.close_after_play)
        after.toggled.connect(lambda b: self._ov_set("close_after_play", b))
        cv.addWidget(after)
        row = QHBoxLayout()
        row.addWidget(QLabel("Hide when untouched for"))
        row.addWidget(self._ov_combo("autohide", ovl.AUTOHIDE, s.autohide), 1)
        cv.addLayout(row)
        self.ov_toggle_only = (after, row.itemAt(1).widget())
        v.addWidget(card)

        card, cv = self._card("Look")
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.addWidget(QLabel("Position"), 0, 0)
        grid.addWidget(self._ov_combo("position", ovl.POSITIONS, s.position), 0, 1)
        grid.addWidget(QLabel("Size"), 1, 0)
        grid.addLayout(self._ov_slider("scale", 60, 160, s.scale), 1, 1)
        grid.addWidget(QLabel("Background"), 2, 0)
        grid.addLayout(self._ov_slider("opacity", 30, 100, s.opacity), 2, 1)
        grid.setColumnStretch(1, 1)
        cv.addLayout(grid)
        prev = QPushButton("Show preview")
        prev.setToolTip("Shows the overlay for a few seconds")
        prev.clicked.connect(lambda: self.mw.overlay.preview())
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(prev)
        cv.addLayout(row)
        v.addWidget(card)

        note = QLabel("Games in true exclusive fullscreen can't have anything drawn over them: "
                      "there the keys still work and you hear beeps instead (turn on hotkey "
                      "beeps in General). Borderless / windowed fullscreen shows the overlay. "
                      "Some games also see the number keys you press — if picking a sound "
                      "switches your weapon, use the numpad.")
        note.setObjectName("hint")
        note.setWordWrap(True)
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

    def _ov_sync(self):
        for wdg in getattr(self, "ov_toggle_only", ()):
            wdg.setEnabled(self.mw.overlay.s.mode == "toggle")   # hold mode: letting go hides

    def _general(self):
        w, v = self._page()
        card, cv = self._card("Your mic",
                              "Normally others hear your voice and your sounds together. Untick "
                              "this for sounds only: they hear the sounds but not your mic. "
                              "(Same as the “send” box next to My mic.)")
        send = QCheckBox("Send my mic to others")
        send.setChecked(self.mw.cfg.mic_enabled)
        send.toggled.connect(self.mw.chk_mic.setChecked)   # the window applies it
        cv.addWidget(send)
        v.addWidget(card)
        card, cv = self._card("Who's listening",
                              "Voice chat runs your sounds through a mono voice codec that drops "
                              "the sub-bass and, in some games, everything above 8-12 kHz. Pick "
                              "where your sounds are going and they're shaped to survive it: the "
                              "lost bass becomes harmonics that get through, the level is evened "
                              "out for the service's gate, and you hear the same thing they do. "
                              "Off sends them exactly as mixed.")
        from soundboard.ui.destpanel import DestPanel
        cv.addWidget(DestPanel(self.mw))
        v.addWidget(card)
        card, cv = self._card("Window")
        top = QCheckBox("Keep the window on top of other windows")
        top.setChecked(self.mw.cfg.always_on_top)
        top.toggled.connect(self.mw.on_top_toggle)
        cv.addWidget(top)
        v.addWidget(card)
        v.addWidget(self._background_card())
        v.addWidget(self._backup_card())
        v.addWidget(self._updates_card())
        v.addWidget(self._remote_card())
        card, cv = self._card("Hotkey sounds",
                              "Short beeps in your headphones (only you hear them) when a hotkey "
                              "starts or stops a recording or saves a clip — so you know it worked "
                              "while you're in a game.")
        cue = QCheckBox("Play hotkey beeps")
        cue.setChecked(self.mw.cfg.cue_sounds)
        cue.toggled.connect(lambda b: self.mw.set_option("cue_sounds", b))
        cv.addWidget(cue)
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
        v.addWidget(self._downloader_card())
        v.addWidget(self._support_card())
        v.addStretch(1)
        return w

    # ------------------------------------------------------------------ support
    def _support_card(self):
        """A link to the GitHub page's Support section: the ways to donate live there,
        not in the app, so they can change without a release and a copy of the app
        with someone else's details swapped in is easy to spot."""
        from soundboard.updates import REPO
        card, cv = self._card("Support Onion Board",
                              "Onion Board is free, with no ads and no tracking. If it made "
                              "your games or calls more fun, you can chip in. Entirely "
                              "optional. The button opens the project's GitHub page.")
        btn = QPushButton("♥  Support Onion Board")
        btn.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl(f"https://github.com/{REPO}#support-onion-board")))
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
        tray = QCheckBox("Closing the window keeps Onion Board running in the tray")
        tray.setChecked(mw.cfg.tray)
        tray.toggled.connect(lambda b: mw.set_option("tray", b))
        if mw.tray is None:
            tray.setEnabled(False)
            tray.setToolTip("This desktop has no system tray, so closing the window quits.")
        cv.addWidget(tray)
        auto = QCheckBox("Start Onion Board when I sign in to Windows")
        hidden = QCheckBox("…straight to the tray, without opening the window")
        auto.setChecked(autostart.is_enabled())
        hidden.setChecked(mw.cfg.autostart_hidden)
        hidden.setEnabled(auto.isChecked())
        hidden.setContentsMargins(22, 0, 0, 0)

        def set_auto(on: bool):
            if not mw.set_autostart(on):
                auto.blockSignals(True)
                auto.setChecked(autostart.is_enabled())
                auto.blockSignals(False)
            hidden.setEnabled(auto.isChecked())
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
        exp.clicked.connect(self.mw.export_board)
        imp = QPushButton("Import…")
        imp.clicked.connect(self.mw.import_dialog)
        row.addWidget(exp)
        row.addWidget(imp)
        row.addStretch(1)
        cv.addLayout(row)
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
                              "GitHub once a day whether a newer version is out and tells you. "
                              + how)
        chk = QCheckBox("Tell me when a new version is out (checks GitHub once a day)")
        chk.setChecked(self.mw.cfg.update_check)
        chk.toggled.connect(self._updates_optin)
        cv.addWidget(chk)
        row = QHBoxLayout()
        self.upd_label = QLabel()
        self.upd_label.setObjectName("hint")
        self.upd_label.setWordWrap(True)
        row.addWidget(self.upd_label, 1)
        self.upd_btn = QPushButton("Check now")
        self.upd_btn.clicked.connect(self._updates_check)
        row.addWidget(self.upd_btn)
        cv.addLayout(row)
        self.mw.update_done.connect(self._updates_done)
        return card

    def _updates_optin(self, on: bool):
        self.mw.set_option("update_check", on)
        if on:
            self.mw.check_updates()

    def _updates_check(self):
        self._upd_asked = True
        self.upd_btn.setEnabled(False)
        self.upd_label.setText("Checking…")
        self.mw.check_updates(force=True)

    def _updates_done(self, rel, err: str):
        if not qt_valid(self.upd_label):
            return
        self.upd_btn.setEnabled(True)
        asked, self._upd_asked = getattr(self, "_upd_asked", False), False
        if err:
            self.upd_label.setText(f"Couldn't check: {err}")
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
        on = QCheckBox("Let programs on this PC control the soundboard")
        on.setChecked(cfg.api_enabled)
        cv.addWidget(on)
        row = QHBoxLayout()
        row.addWidget(QLabel("Port"))
        port = QSpinBox()
        port.setRange(1024, 65535)
        port.setValue(cfg.api_port)
        port.setAccessibleName("Port")
        no_wheel(port)
        row.addWidget(port)
        row.addSpacing(12)
        row.addWidget(QLabel("Key"))
        key = QLineEdit()
        key.setReadOnly(True)
        key.setEchoMode(QLineEdit.Password)
        key.setAccessibleName("Key")
        row.addWidget(key, 1)
        show = QPushButton("Show")
        show.setObjectName("small")
        show.setCheckable(True)
        show.toggled.connect(lambda b: key.setEchoMode(QLineEdit.Normal if b
                                                       else QLineEdit.Password))
        row.addWidget(show)
        new = QPushButton("New key")
        new.setObjectName("small")
        new.setToolTip("Make a new key: anything using the old one stops working")
        row.addWidget(new)
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
        help_ = QLabel("Endpoints: /api/play?name=Airhorn · /api/play?id=… · /api/stop · "
                       "/api/pause · /api/random?category=Memes · /api/sounds · "
                       "/api/status. Send the key as ?token=…, an X-Token header or "
                       "Authorization: Bearer ….")
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

        def copy_link():
            QApplication.clipboard().setText(
                f"http://{remote.HOST}:{cfg.api_port}/api/random?token={cfg.api_token}")
            state.setText("Copied. It holds your key: only paste it into your own tools.")

        on.toggled.connect(set_on)
        port.editingFinished.connect(set_port)
        new.clicked.connect(new_key)
        copy.clicked.connect(copy_link)
        refresh()
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
        auto = QCheckBox("Update it automatically from PyPI (checks once a day, and when a "
                         "download fails)")
        auto.setToolTip("Off by default: an update is code the app runs. It's checked against "
                        "PyPI's SHA-256 before it's used.")
        auto.setChecked(self.mw.cfg.ytdlp_auto_optin)
        auto.toggled.connect(lambda b: self.mw.set_option("ytdlp_auto_optin", b))
        cv.addWidget(auto)
        row = QHBoxLayout()
        self.ytdlp_label = QLabel()
        self.ytdlp_label.setObjectName("hint")
        self.ytdlp_label.setWordWrap(True)
        row.addWidget(self.ytdlp_label, 1)
        self.ytdlp_btns = []
        for text, job, tip in (
                ("Update now", ytdl.update, "Check for a newer yt-dlp and install it"),
                ("Reset downloader", ytdl.reset,
                 "Delete the downloaded yt-dlp and its cache, then install a fresh copy")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, j=job: self._ytdlp_run(j))
            row.addWidget(b)
            self.ytdlp_btns.append(b)
        cv.addLayout(row)
        self._ytdlp_show()
        return card

    def _ytdlp_show(self, msg: str = ""):
        v, downloaded = ytdl.active_version()
        where = "updated copy" if downloaded else "built in"
        now = f"In use: yt-dlp {v} ({where})." if v else "yt-dlp isn't installed."
        self.ytdlp_label.setText(f"{msg} {now}".strip())

    def _ytdlp_run(self, job):
        for b in self.ytdlp_btns:
            b.setEnabled(False)
        self.ytdlp_label.setText("Working…")
        relay = _Relay(self.mw)   # outlives this window if it's closed meanwhile

        def finish(msg):
            relay.deleteLater()
            if qt_valid(self.ytdlp_label):
                for b in self.ytdlp_btns:
                    b.setEnabled(True)
                self._ytdlp_show(msg)

        relay.done.connect(finish)

        def run():
            try:
                msg = job()
            except Exception as e:  # noqa: BLE001 - offline, PyPI down…
                msg = f"Couldn't update: {e}."
            relay.done.emit(msg)
        threading.Thread(target=run, daemon=True, name="ytdlp-settings").start()
