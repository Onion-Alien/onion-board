"""Hotkey names and the key picker: the global hotkey actions, how a combo reads
("Ctrl+1"), and the window that asks for one. Pads, menus, Edit sound and Settings
all use them; they live here so none of those has to load the Settings window."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from soundboard.control import midi, winkeys
from soundboard.ui.kit import theme
from soundboard.i18n import _
from soundboard.ui.kit import fit
from soundboard.control.winkeys import Hotkeys


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
        ("voices_hotkey", "__voices__", _("All voices on / off"),
         _("The Voice tab's Voices switch: turns off everything changing your mic (the "
           "voice changer, the AI voice, the computer voice, translating), and the next "
           "press brings exactly those back.")),
        ("voice_hold_hotkey", "__voicehold__", _("Change my voice while held"),
         _("The voice changer is on only while you hold this key down.")),
        ("voice_random_hotkey", "__voicerandom__", _("Random voice"),
         _("Turns the voice changer on with a voice picked at random from the ones the "
           "Voice tab shows (your favorites, when Favorites is picked).")),
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


class HotkeyDialog(QDialog):
    """Asks for a key combo, or (with `pads`) a hit on a MIDI pad controller, or (with
    `mouse`) a click of a mouse side button on it. `in_app`: a key only this window
    reads (a tab's), said as the hint; any key will do, it takes nothing from games."""

    def __init__(self, hotkeys: Hotkeys, parent=None, pads: bool = True, mouse: bool = False,
                 in_app: str = ""):
        super().__init__(parent)
        fit.watch(self)   # grows to fit its text (ui/kit/fit.py)
        self.setWindowTitle(_("Set hotkey"))
        self.result_combo = None
        self._midi = hotkeys.midi if pads else None
        lay = QVBoxLayout(self)
        t = QLabel(_("Press the key or combo you want…"))
        t.setStyleSheet("font-size:16px; font-weight:600;")
        lay.addWidget(t)
        self._mouse = mouse
        self.hint = QLabel(in_app or (
            _("…or click a mouse side button (Mouse 4 / 5) in this window. Esc = cancel.")
            if mouse else _("Works globally, even while in-game.  Esc = cancel.")))
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
        self._takes_keys = not hotkeys.share and not in_app   # read before pause() below
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

    def mousePressEvent(self, e):
        button = {Qt.MouseButton.XButton1: "mouse 4",
                  Qt.MouseButton.XButton2: "mouse 5"}.get(e.button())
        if self._mouse and button and self.result_combo is None:
            self.result_combo = button
            self.accept()
            return
        super().mousePressEvent(e)

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
        if self._takes_keys and not mods and winkeys.is_typing_key(vk) and self._warned_vk != vk:
            # a hotkey that takes its key (games don't get it) away from every other
            # program: warn once. Shared keys still reach the game, so no warning there
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
