"""Settings window: themes, every global hotkey in one place, the in-game overlay,
general options."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QPushButton, QSlider, QTabWidget, QVBoxLayout, QWidget)

from soundboard import theme, winkeys
from soundboard.ui import icons
from soundboard.ui import overlay as ovl
from soundboard.wheelguard import no_wheel
from soundboard.winkeys import Hotkeys

# Global hotkey actions: (config attribute, action id, label, what it does).
# Grouped for the Settings window; the action ids go to MainWindow.on_hotkey.
HOTKEY_GROUPS = [
    ("Sounds", [
        ("stop_hotkey", "__stop__", "Stop everything",
         "Stops every sound and pauses the browser."),
        ("pause_hotkey", "__pause__", "Pause / resume sounds",
         "Pauses everything playing; press again to carry on."),
    ]),
    ("Browser", [
        ("rec_hotkey", "__rec__", "Record clip: start / stop",
         "Records what the browser plays. Press again to stop: the clip lands in Sounds."),
        ("clip_hotkey", "__clip__", "Save the last 15 seconds",
         "Instant replay: turns what just played into a sound."),
        ("bplay_hotkey", "__bplay__", "Play / pause the browser", ""),
        ("live_hotkey", "__live__", "LIVE on / off",
         "Switch between others hearing the browser and only you."),
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
    return "+".join(p.strip().title() if len(p.strip()) > 1 else p.strip().upper()
                    for p in combo.split("+"))


class HotkeyDialog(QDialog):
    def __init__(self, hotkeys: Hotkeys, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Set hotkey")
        self.result_combo = None
        lay = QVBoxLayout(self)
        t = QLabel("Press the key or combo you want…")
        t.setStyleSheet("font-size:16px; font-weight:600;")
        lay.addWidget(t)
        lay.addWidget(QLabel("Works globally, even while in-game.  Esc = cancel."))
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
        self.result_combo = winkeys.combo_name(mods, vk)
        self.accept()


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
        self.mw = mw
        self.setWindowTitle("Settings")
        self.setWindowIcon(theme.app_icon())
        self.setMinimumSize(720, 600)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._appearance(), "Appearance")
        self.hk_buttons: dict[str, list[QPushButton]] = {}
        self.tabs.addTab(self._hotkeys(), "Hotkeys")
        self.tabs.addTab(self._overlay(), "Overlay")
        self.tabs.addTab(self._general(), "General")
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

    # ------------------------------------------------------------------ pages
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
        card, cv = self._card("Game push-to-talk",
                              "The app holds this key down while a sound or the live browser is "
                              "going out — set it to your game's push-to-talk key.")
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
        card, cv = self._card("Window")
        top = QCheckBox("Keep the window on top of other windows")
        top.setChecked(self.mw.cfg.always_on_top)
        top.toggled.connect(self.mw.on_top_toggle)
        cv.addWidget(top)
        v.addWidget(card)
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
        v.addStretch(1)
        return w
