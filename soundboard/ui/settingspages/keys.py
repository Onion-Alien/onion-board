"""Settings → Hotkeys and Overlay: every global hotkey and the in-game overlay."""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QBoxLayout, QCheckBox, QComboBox, QGridLayout,
                               QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout,
                               QWidget)
from shiboken6 import isValid as qt_valid

from soundboard.i18n import _
from soundboard.ui.kit import icons
from soundboard.ui import overlay as ovl
# the actions, how a combo reads and the key picker live in ui/kit/hotkeypick.py (pads and
# menus use them without loading Settings); here for the page and older imports
from soundboard.ui.kit.hotkeypick import (HOTKEY_ACTIONS, HOTKEY_GROUP_ICONS, HOTKEY_GROUPS,
                                          HotkeyDialog, pretty_key)
from soundboard.ui.settingspages import Page, _button_row
from soundboard.ui.kit.wheelguard import no_wheel

log = logging.getLogger(__name__)

__all__ = ["HOTKEY_ACTIONS", "HOTKEY_GROUP_ICONS", "HOTKEY_GROUPS", "HotkeyDialog", "KeysPage",
           "pretty_key"]


class KeysPage(Page):
    """Settings → Hotkeys and Overlay: every global hotkey and the in-game overlay."""

    def _hotkeys(self):
        w, v = self._page()
        card, cv = self._card(_("Keys in games"),
                              _("With this on, a hotkey still does its normal job too: press F1 "
                                "in a game and the game gets F1 while your sound plays. Off: "
                                "only Onion Board gets the key, so a hotkey on W stops you "
                                "walking."), icon="gamepad")
        share = QCheckBox(_("Games get the key too"))
        share.setChecked(self.mw.cfg.hotkeys_share)
        share.toggled.connect(self.mw.hkctl.set_share_hotkeys)
        cv.addWidget(share)
        v.addWidget(card)
        for (group, actions), icon in zip(HOTKEY_GROUPS, HOTKEY_GROUP_ICONS):
            card, cv = self._card(group, icon=icon)
            for attr, _action, label, desc in actions:
                self._hk_row(cv, attr, label, desc)
            # the Categories group: its keys and the per-category sets go together
            if any(a[0] == "next_cat_hotkey" for a in actions):
                scoped = QCheckBox(_("Use hotkeys per category"))
                scoped.setToolTip(_("One key can play a different sound in each category: switch "
                                    "category (its tab, or the keys above) and the same keys "
                                    "play that category's sounds. Sounds in no category always "
                                    "keep their keys."))
                scoped.setChecked(self.mw.cfg.scoped_hotkeys)
                scoped.toggled.connect(self.mw.hkctl.set_scoped_hotkeys)
                cv.addWidget(scoped)
                hint = QLabel(_("Sound hotkeys only work in the category showing. Switch "
                                "categories to use the same keys for different sounds."))
                hint.setObjectName("hint")
                hint.setWordWrap(True)
                cv.addWidget(hint)
            v.addWidget(card)
        card, cv = self._card(_("Auto push-to-talk (optional)"),
                              _("Only if you use push-to-talk in a game or Discord: set your "
                                "push-to-talk key and the app holds it for you while a sound, "
                                "live radio or a program plays. Leave it Off for open mic."),
                              icon="mic")
        self._hk_row(cv, "ptt_key", _("Hold this key"), "")
        v.addWidget(card)
        card, cv = self._card(_("Hotkey sounds"),
                              _("Short beeps in your headphones (only you hear them) when a "
                                "hotkey does something you can't see in a game: switches "
                                "category (one beep per place along, a low one for All), turns "
                                "your mic, the voice changer or the hotkeys on (rising) or off "
                                "(falling), changes the volume, or records or saves a clip."),
                              icon="volume")
        cue = QCheckBox(_("Play hotkey beeps"))
        cue.setChecked(self.mw.cfg.cue_sounds)
        cue.toggled.connect(lambda b: self.mw.set_option("cue_sounds", b))
        cv.addWidget(cue)
        v.addWidget(card)
        note = QLabel(_("Per-sound hotkeys: right-click a pad → Set hotkey. All hotkeys work "
                        "while you're in a game."))
        note.setObjectName("hint")
        note.setWordWrap(True)
        note.setContentsMargins(14, 0, 14, 0)   # in line with the cards' text
        v.addWidget(note)
        v.addStretch(1)
        self._refresh_hk()
        return w

    def _hk_row(self, lay, attr, label, desc):
        holder = _HotkeyRow()
        row = holder.row
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
        b.clicked.connect(lambda __=False, a=attr: self._capture(a))
        # each row's buttons say which hotkey they're for (a screen reader read every
        # row as "Click to set" and "Clear")
        b.setAccessibleName(_("{label} hotkey", label=label))
        keys = QHBoxLayout()   # the key and its ✕: beside the words, or under them narrow
        keys.setSpacing(8)
        keys.addWidget(b)
        x = QPushButton()
        x.setObjectName("small")
        icons.close_button(x, 24)
        x.setAccessibleName(_("Clear the {label} hotkey", label=label))
        x.clicked.connect(lambda __=False, a=attr: self._set_hk(a, ""))
        keys.addWidget(x)
        keys.setAlignment(Qt.AlignmentFlag.AlignLeft)
        row.addLayout(keys)
        lay.addWidget(holder)
        self.dlg.hk_buttons.setdefault(attr, []).append(b)

    def _refresh_hk(self):
        for attr, buttons in self.dlg.hk_buttons.items():
            combo = getattr(self.mw.cfg, attr)
            for b in buttons:
                b.setText(pretty_key(combo)
                          or (_("Off") if attr == "ptt_key" else _("Click to set")))

    def _capture(self, attr):
        # auto push-to-talk presses the key itself: that can't be a MIDI pad
        d = HotkeyDialog(self.mw.hotkeys, self.dlg, pads=attr != "ptt_key")
        if d.exec() and d.result_combo:
            self._set_hk(attr, d.result_combo)
        else:
            self.mw.hkctl.register_hotkeys()   # capture paused them

    def _set_hk(self, attr, combo):
        self.mw.hkctl.set_global_hotkey(attr, combo)
        self._refresh_hk()

    def _overlay(self):
        """The in-game overlay: how it opens, which keys pick, how it looks."""
        w, v = self._page()
        s = self.mw.overlay.s
        card, cv = self._card(_("Open it"),
                              _("Press the hotkey in a game and your sounds appear on top of it. "
                                "The game keeps your keyboard and mouse, and the overlay's keys "
                                "go back to the game the moment it closes."), icon="keyboard")
        self._hk_row(cv, "overlay_hotkey", _("Overlay hotkey"), "")
        test = QPushButton(_("Open overlay"))
        test.setToolTip(_("Opens it now, the same as the hotkey: pick a sound with its keys or a "
                          "click. Esc, this button or the hotkey closes it"))
        test.clicked.connect(lambda: self.mw.overlay.open_by_click())
        row = QHBoxLayout()   # beside how the key works: two lines, not three
        row.setSpacing(8)
        row.addWidget(self._ov_combo("mode", ovl.MODES, s.mode, _("Open it")))
        row.addWidget(test)   # as wide as its words (it ran to the card's edge)
        row.addStretch(1)
        cv.addLayout(row)
        v.addWidget(card)

        card, cv = self._card(_("Pick sounds"),
                              _("Nine tiles a page, in the same order as your pads. Drag pads "
                                "in the Sounds tab to rearrange them."), icon="sounds")
        cv.addWidget(self._ov_combo("keys", ovl.KEY_CHOICES, s.keys, _("Pick sounds")))
        after = QCheckBox(_("Hide after picking a sound"))
        after.setChecked(s.close_after_play)
        after.toggled.connect(lambda b: self._ov_set("close_after_play", b))
        cv.addWidget(after)
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(QLabel(_("Auto-hide after")))
        row.addWidget(self._ov_combo("autohide", ovl.AUTOHIDE, s.autohide,
                                      _("Auto-hide after")))
        row.addStretch(1)   # the choice right after its label, not at the card's far edge
        cv.addLayout(row)
        from soundboard.ui.kit.widgets import widget_at  # (it imports this module)
        toggle_only = widget_at(row, 1)
        assert toggle_only is not None
        self.dlg.ov_toggle_only = (after, toggle_only)
        v.addWidget(card)

        card, cv = self._card(_("Where and how it looks"),
                              _("Or just drag it: grab any empty part of the overlay (its title, "
                                "its edges) and drop it anywhere, on any monitor. It opens there "
                                "from then on. Show preview only shows how it looks: open the "
                                "overlay with its hotkey to try it or move it."), icon="eye")
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.addWidget(QLabel(_("Monitor")), 0, 0)
        self.dlg.ov_monitor = self._ov_combo("monitor", self._monitor_choices(s.monitor), s.monitor,
                                             _("Monitor"))
        self.dlg.ov_monitor.setToolTip(_("With more than one monitor: put the overlay on the one "
                                         "you're gaming on, or keep it on a second one"))
        grid.addWidget(self.dlg.ov_monitor, 0, 1)
        grid.addWidget(QLabel(_("Position")), 1, 0)
        self.dlg.ov_position = self._ov_combo("position", ovl.POSITIONS, s.position,
                                              _("Position"))
        grid.addWidget(self.dlg.ov_position, 1, 1)
        grid.addWidget(QLabel(_("Size")), 2, 0)
        grid.addLayout(self._ov_slider("scale", 60, 160, s.scale, _("Size")), 2, 1)
        grid.addWidget(QLabel(_("Background")), 3, 0)
        grid.addLayout(self._ov_slider("opacity", 30, 100, s.opacity, _("Background")), 3, 1)
        grid.setColumnStretch(1, 1)
        cv.addLayout(grid)
        # a drag on the overlay changes monitor / position: show it here
        self.mw.overlay.listeners.append(self._ov_dragged)
        self.dlg.destroyed.connect(lambda *__: self._ov_forget())
        self.dlg.finished.connect(lambda *__: self._ov_forget())
        prev = QPushButton(_("Show preview"))
        prev.setToolTip(_("Shows the overlay for a few seconds, to see how it looks; any click "
                          "or key closes it"))
        prev.clicked.connect(lambda: self.mw.overlay.preview(6))
        row = _button_row()
        row.addWidget(prev)
        cv.addLayout(row)
        v.addWidget(card)

        note = QLabel(_("Games in true exclusive fullscreen can't have anything drawn over them: "
                        "there the keys still work and you hear beeps instead (turn on hotkey "
                        "beeps above). Borderless / windowed fullscreen shows the overlay. Some "
                        "games also see the number keys you press. If picking a sound switches "
                        "your weapon, use the numpad."))
        note.setObjectName("hint")
        note.setWordWrap(True)
        note.setContentsMargins(14, 0, 14, 0)   # in line with the cards' text
        v.addWidget(note)
        v.addStretch(1)
        self._ov_sync()
        self._refresh_hk()   # its hotkey button's text (this page is built after Hotkeys)
        return w

    def _ov_combo(self, key, choices, current, name):
        cb = QComboBox()
        cb.setAccessibleName(name)   # what its card or label says, for a screen reader
        for value, label in choices:
            cb.addItem(label, value)
        cb.setCurrentIndex(max(0, cb.findData(current)))
        cb.currentIndexChanged.connect(lambda i: self._ov_set(key, cb.itemData(i)))
        no_wheel(cb)
        return cb

    def _ov_slider(self, key, lo, hi, value, name):
        row = QHBoxLayout()
        sl = QSlider(Qt.Orientation.Horizontal)
        sl.setAccessibleName(name)
        sl.setRange(lo, hi)
        sl.setValue(value)
        val = QLabel(_("{percent}%", percent=value))
        val.setFixedWidth(48)
        val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        sl.valueChanged.connect(lambda x: (val.setText(_("{percent}%", percent=x)),
                                           self._ov_set(key, x)))
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
            choices.append((current, _("{monitor}  (not connected)",
                                       monitor=current.rpartition('@')[0] or current)))
        return choices

    def _ov_dragged(self):
        """The overlay was dragged somewhere: show its new monitor and position."""
        if not qt_valid(self.dlg):
            return
        s = self.mw.overlay.s
        for cb, value, choices in ((self.dlg.ov_monitor, s.monitor,
                                    self._monitor_choices(s.monitor)),
                                   (self.dlg.ov_position, s.position, ovl.POSITIONS)):
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
        for wdg in getattr(self.dlg, "ov_toggle_only", ()):
            wdg.setEnabled(self.mw.overlay.s.mode == "toggle")   # hold mode: letting go hides


class _HotkeyRow(QWidget):
    """One hotkey's row: its name and what it does, then its key and ✕ beside them, or
    under them in a narrow window (beside, the words got a word a line)."""

    NARROW = 420   # px: under this the key goes under the words

    def __init__(self):
        super().__init__()
        self.row = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(16)

    def resizeEvent(self, e):   # noqa: N802 - Qt
        super().resizeEvent(e)
        try:
            way = (QBoxLayout.Direction.TopToBottom if self.width() < self.NARROW
                   else QBoxLayout.Direction.LeftToRight)
            if self.row.direction() != way:   # (only when it changes: no resize loop)
                self.row.setDirection(way)
                # beside: a clear gap from the words; under: just below them
                self.row.setSpacing(6 if way == QBoxLayout.Direction.TopToBottom else 16)
        except Exception:  # noqa: BLE001 - never raise from a Qt override (AGENT-RULES)
            log.exception("hotkey row: resize")
