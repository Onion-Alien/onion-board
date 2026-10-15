"""Settings → Hotkeys and Overlay: every global hotkey and the in-game overlay."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QGridLayout,
                               QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout)
from shiboken6 import isValid as qt_valid

from soundboard import midi, theme, winkeys
from soundboard.i18n import _
from soundboard.ui import fit, icons, overlay as ovl
from soundboard.ui.settingspages import Page, _button_row
from soundboard.wheelguard import no_wheel
from soundboard.winkeys import Hotkeys


# Global hotkey actions: (config attribute, action id, label, what it does).
# Grouped for the Settings window; the action ids go to HotkeyControl.on_hotkey.
HOTKEY_GROUPS = [
    (_("Sounds"), [
        ("stop_hotkey", "__stop__", _("Stop everything"),
         _("Stops every sound, the radio and every program, and turns the voices off.")),
        ("pause_hotkey", "__pause__", _("Pause / resume sounds"),
         _("Pauses everything playing; press again to carry on.")),
        ("skip_hotkey", "__skip__", _("Skip to the next sound"),
         _("Stops the sound playing and starts the next one in Up next. With nothing "
           "waiting, it just stops the sound.")),
        ("random_hotkey", "__random__", _("Play a random sound"),
         _("From the category showing (All = any sound), never the same one twice in a row. "
           "A category can have its own: right-click its tab.")),
        ("last_hotkey", "__last__", _("Play the last sound again"),
         _("Whatever played last, from a pad, a hotkey or the random key.")),
        ("vol_up_hotkey", "__volup__", _("Sounds louder"),
         _("Turns your sounds up by 10% (what others hear and what you hear).")),
        ("vol_down_hotkey", "__voldown__", _("Sounds quieter"),
         _("Turns your sounds down by 10%.")),
    ]),
    (_("Categories"), [
        ("next_cat_hotkey", "__nextcat__", _("Next category"),
         _("Shows the next category's pads. The random-sound key and the overlay follow it, "
           "so one key plays a random sound from whichever category you switched to.")),
        ("prev_cat_hotkey", "__prevcat__", _("Previous category"),
         _("Shows the category before it.")),
    ]),
    (_("Mic and voice"), [
        ("mic_hotkey", "__mic__", _("Send my mic on / off"),
         _("Others hear your voice with the sounds, or only the sounds.")),
        ("voice_hotkey", "__voice__", _("Voice changer on / off"),
         _("Turns the voice changer on with the voice picked on the Voice tab, or off.")),
        ("voice_hold_hotkey", "__voicehold__", _("Change my voice while held"),
         _("The voice changer is on only while you hold this key down.")),
    ]),
    (_("Turn hotkeys off"), [
        ("hotkeys_off_hotkey", "__hotkeys__", _("All hotkeys off / on"),
         _("Turns every other hotkey off, so they type normally (in chat, say), and back "
           "on. Hotkeys are always on when Onion Board opens.")),
    ]),
    (_("Instant replay"), [
        ("replay_hotkey", "__replay__", _("Save what you just heard"),
         _("Turns instant replay on: the last 30 seconds of everything your PC plays (a "
           "friend in Discord, the game, a video; not Onion Board's own sounds) are kept "
           "in memory, and this key adds them to your Sounds as a pad. Nothing is saved "
           "until you press it. Clear the key to switch it off. Only keep clips of people "
           "who are fine with it: in some places, recording a call needs everyone's OK.")),
    ]),
    (_("Overlay"), [
        ("overlay_hotkey", "__overlay__", _("Open the in-game overlay"),
         _("Sound tiles over your game; pick one with the number keys. See the Overlay tab.")),
    ]),
]


HOTKEY_ACTIONS = [a for __, group in HOTKEY_GROUPS for a in group]
# each group's card heading icon, in HOTKEY_GROUPS' order
HOTKEY_GROUP_ICONS = ("sounds", "tag", "voice", "live_off", "history", "gamepad")
assert len(HOTKEY_GROUP_ICONS) == len(HOTKEY_GROUPS)


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


def is_typing_key(vk: int) -> bool:
    """Letters, digits, punctuation, Space, Enter, Tab, Backspace, arrows: keys people
    type with. F-keys, the numpad, Insert/Home/…, media keys are fine bare."""
    return (0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A or 0xBA <= vk <= 0xC0
            or 0xDB <= vk <= 0xDF or 0x25 <= vk <= 0x28
            or vk in (0x08, 0x09, 0x0D, 0x20, 0xE2))   # 0xE2: the extra key of ISO keyboards


class HotkeyDialog(QDialog):
    """Asks for a key combo, or (with `pads`) a hit on a MIDI pad controller."""

    def __init__(self, hotkeys: Hotkeys, parent=None, pads: bool = True):
        super().__init__(parent)
        fit.watch(self)   # grows to fit its text (ui/fit.py)
        self.setWindowTitle(_("Set hotkey"))
        self.result_combo = None
        self._midi = hotkeys.midi if pads else None
        lay = QVBoxLayout(self)
        t = QLabel(_("Press the key or combo you want…"))
        t.setStyleSheet("font-size:16px; font-weight:600;")
        lay.addWidget(t)
        self.hint = QLabel(_("Works globally, even while in-game.  Esc = cancel."))
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        self.pads_note = QLabel()
        self.pads_note.setObjectName("hint")
        self.pads_note.setWordWrap(True)
        lay.addWidget(self.pads_note)
        # a way out on screen too (Esc and the title bar's ✕ were the only ones); it
        # takes no focus, so the keys pressed here all go to the capture
        cancel = QPushButton(_("Cancel"))
        cancel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
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

    def _show_pads(self, *__):
        if self._midi is None:
            self.pads_note.hide()
            return
        found = self._midi.devices()
        busy = set(self._midi.busy)
        free = [d for d in found if d not in busy]
        lines = []
        if free:
            lines.append(_("…or hit a pad on {devices}.", devices=", ".join(free)))
        if busy:
            warn = theme.status("warn")
            lines.append(_("<span style='color:{warn}'>{devices} is open in another program "
                           "(a music app?), so its pads can't be used here. Close that "
                           "program and it's picked up in a few seconds.</span>",
                           warn=warn, devices=", ".join(sorted(busy))))
        self.pads_note.setText("<br>".join(lines))
        self.pads_note.setVisible(bool(lines))

    def _on_pad(self, combo: str):
        if self.result_combo is None and self.isVisible():
            self.result_combo = combo
            self.accept()

    def _stop_pads(self):
        midi = self._midi
        assert midi is not None   # only connected with one
        try:
            midi.pressed.disconnect(self._on_pad)
            midi.busy_changed.disconnect(self._show_pads)
        except (RuntimeError, TypeError):
            pass
        midi.capture(False)

    def keyPressEvent(self, e):
        vk = e.nativeVirtualKey()
        if vk == 0x1B:            # Esc
            self.reject()
            return
        if vk in winkeys.MODIFIER_VKS or not vk:
            return                # wait for the real key
        m = e.modifiers()
        mods = ((winkeys.MOD_CONTROL if m & Qt.KeyboardModifier.ControlModifier else 0)
                | (winkeys.MOD_ALT if m & Qt.KeyboardModifier.AltModifier else 0)
                | (winkeys.MOD_SHIFT if m & Qt.KeyboardModifier.ShiftModifier else 0)
                | (winkeys.MOD_WIN if m & Qt.KeyboardModifier.MetaModifier else 0))
        if not mods and is_typing_key(vk) and self._warned_vk != vk:
            # a global hotkey takes the key away from every other program: warn once
            self._warned_vk = vk
            key = pretty_key(winkeys.combo_name(0, vk))
            warn = theme.status("warn")
            self.hint.setText(_("<span style='color:{warn}'><b>{key}</b> on its own would stop "
                                "working for typing everywhere (chat, games, browser). Add Ctrl, "
                                "Alt or Shift, or press it again to use it anyway.</span>",
                                warn=warn, key=key))
            return
        combo, why = winkeys.check(winkeys.combo_name(mods, vk))
        if why:   # a key Windows can't take as a hotkey: say so, keep listening
            self.hint.setText(f"<span style='color:{theme.status('warn')}'>{why}</span>")
            return
        self.result_combo = combo
        self.accept()


class KeysPage(Page):
    """Settings → Hotkeys and Overlay: every global hotkey and the in-game overlay."""

    def _hotkeys(self):
        w, v = self._page()
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
        b.clicked.connect(lambda __=False, a=attr: self._capture(a))
        # each row's buttons say which hotkey they're for (a screen reader read every
        # row as "Click to set" and "Clear")
        b.setAccessibleName(_("{label} hotkey", label=label))
        row.addWidget(b)
        x = QPushButton()
        x.setObjectName("small")
        icons.close_button(x, 24)
        x.setAccessibleName(_("Clear the {label} hotkey", label=label))
        x.clicked.connect(lambda __=False, a=attr: self._set_hk(a, ""))
        row.addWidget(x)
        lay.addLayout(row)
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
        row.addWidget(self._ov_combo("mode", ovl.MODES, s.mode))
        row.addWidget(test)   # as wide as its words (it ran to the card's edge)
        row.addStretch(1)
        cv.addLayout(row)
        v.addWidget(card)

        card, cv = self._card(_("Pick sounds"),
                              _("Nine tiles a page, in the same order as your pads. Drag pads "
                                "in the Sounds tab to rearrange them."), icon="sounds")
        cv.addWidget(self._ov_combo("keys", ovl.KEY_CHOICES, s.keys))
        after = QCheckBox(_("Hide after picking a sound"))
        after.setChecked(s.close_after_play)
        after.toggled.connect(lambda b: self._ov_set("close_after_play", b))
        cv.addWidget(after)
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(QLabel(_("Auto-hide after")))
        row.addWidget(self._ov_combo("autohide", ovl.AUTOHIDE, s.autohide))
        row.addStretch(1)   # the choice right after its label, not at the card's far edge
        cv.addLayout(row)
        item = row.itemAt(1)
        assert item is not None
        self.dlg.ov_toggle_only = (after, item.widget())
        v.addWidget(card)

        card, cv = self._card(_("Where and how it looks"),
                              _("Or just drag it: grab any empty part of the overlay (its title, "
                                "its edges) and drop it anywhere, on any monitor. It opens there "
                                "from then on. Show preview only shows how it looks: open the "
                                "overlay with its hotkey to try it or move it."), icon="eye")
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.addWidget(QLabel(_("Monitor")), 0, 0)
        self.dlg.ov_monitor = self._ov_combo("monitor", self._monitor_choices(s.monitor), s.monitor)
        self.dlg.ov_monitor.setToolTip(_("With more than one monitor: put the overlay on the one "
                                         "you're gaming on, or keep it on a second one"))
        grid.addWidget(self.dlg.ov_monitor, 0, 1)
        grid.addWidget(QLabel(_("Position")), 1, 0)
        self.dlg.ov_position = self._ov_combo("position", ovl.POSITIONS, s.position)
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
        return w

    def _ov_combo(self, key, choices, current):
        cb = QComboBox()
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
