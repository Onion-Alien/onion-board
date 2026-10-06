"""What stands in for a tab switched off in Settings > Tabs (Config.tabs_off).

The tab is hidden and its real page (the Apps, Triggers or Voice tab) is never built,
so nothing of it loads or runs: no program scanning, no Onion Watch, no voice chain or
voice add-ons. The window still calls the methods it calls on the real page, and these
answer as an idle one would. (The Radio tab's stand-in is radiopanel.RadioOff.)
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QPushButton, QWidget

from soundboard import savedvoices

# the tabs that can be switched off, by key (the main window's attribute for each);
# Sounds and Setup always stay
KEYS = ("radio", "apps", "triggers", "voice")


class TabOff(QWidget):
    """A switched-off tab: hidden, empty, never live."""
    clip_ready = Signal(object, str)
    active_changed = Signal(bool)
    loaded = Signal()
    pending = False   # Triggers: nothing waiting to load
    info = None       # Apps: no ⓘ text; Triggers: no add-on

    def start(self):
        pass

    def stop(self):
        pass

    def stop_all(self):
        pass

    def shutdown(self):
        pass

    def retheme(self):
        pass

    def cancel_pending(self):
        pass

    def sounds_changed(self):
        pass

    def import_done(self):
        pass

    def offer_update(self, _offer):
        pass

    def needs_nudge(self) -> bool:
        return False

    def nudged(self):
        pass

    def poll(self):
        pass

    def is_active(self) -> bool:
        return False

    def live_tip(self) -> str:
        return ""

    def tab_icon(self) -> str:
        return "voice"

    def fit_steps(self):
        return []

    def stack_steps(self):
        return []


class _FxOff(QObject):
    """The voice changer's part of VoiceOff: a power switch that stays off."""
    hear_toggled = Signal(bool)
    chat_help = Signal()
    tip_dismissed = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.btn_power = QPushButton(parent)
        self.btn_power.setCheckable(True)
        self.btn_power.setEnabled(False)
        self.btn_power.hide()

    def set_hearing(self, _on: bool):
        pass

    def set_tip_enabled(self, _on: bool):
        pass

    @staticmethod
    def merge_saved(raw) -> int:
        """A backup's saved voices still go into their file, for when the tab's back."""
        return savedvoices.Store().merge(raw)


class VoiceOff(TabOff):
    """The Voice tab switched off: the mic goes out unchanged."""

    def __init__(self):
        super().__init__()
        self.fx = _FxOff(self)
        self.speech = None
