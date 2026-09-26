"""Settings window: themes, every global hotkey in one place, general options."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import (QCheckBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QTabWidget, QVBoxLayout, QWidget)

import theme
import winkeys
from winkeys import Hotkeys

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
        theme.paint_logo(p, QRectF(r.right() - 36, r.bottom() - 30, 22, 22), t["accent"], t["accent2"])
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
        self.tabs.addTab(self._appearance(), "🎨  Appearance")
        self.tabs.addTab(self._hotkeys(), "⌨  Hotkeys")
        self.tabs.addTab(self._general(), "⚙  General")
        self.tabs.setCurrentIndex({"appearance": 0, "hotkeys": 1, "general": 2}.get(page, 0))
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
        self.hk_buttons: dict[str, QPushButton] = {}
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
        self.hk_buttons[attr] = b

    def _refresh_hk(self):
        for attr, b in self.hk_buttons.items():
            combo = getattr(self.mw.cfg, attr)
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

    def _general(self):
        w, v = self._page()
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
        cue.toggled.connect(lambda b: self.mw._set("cue_sounds", b))
        cv.addWidget(cue)
        v.addWidget(card)
        v.addStretch(1)
        return w
