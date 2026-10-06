"""No piece of a screen is shown while it has no parent: on Windows each one flashed up
on the desktop as a little blank window of its own for a moment, and lagged the app."""
import numpy as np
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QWidget

from soundboard.library import SoundMeta
from soundboard.ui import dialogs
from soundboard.ui.appspanel import AppRow
from soundboard.ui.widgets import Meter


def windows_shown(qapp, build) -> list[str]:
    """What `build()` shows (or gives a native window) while it has no parent."""
    stray = []

    class Spy(QObject):
        def eventFilter(self, obj, ev):
            if (ev.type() in (QEvent.Show, QEvent.WinIdChange) and isinstance(obj, QWidget)
                    and obj.isWindow() and obj.parent() is None):
                stray.append(type(obj).__name__)
            return False

    spy = Spy()
    qapp.installEventFilter(spy)
    try:
        build()
        qapp.processEvents()
    finally:
        qapp.removeEventFilter(spy)
    return stray


def test_an_app_card_sending_one_way_shows_its_list_inside_the_card(qapp):
    made = []
    assert windows_shown(qapp, lambda: made.append(AppRow("music.exe", Meter, to="call"))) == []
    assert made[0].cb_to.parent() is made[0]


def test_editing_a_loaded_sound_shows_its_trim_inside_the_dialog(qapp, monkeypatch):
    monkeypatch.setattr(dialogs, "original_peaks", lambda m: (np.zeros(40), 3.0))
    made = []
    assert windows_shown(qapp, lambda: made.append(dialogs.EffectsPanel(
        {}, SoundMeta(id="s1", name="Horn", file="")))) == []
    assert made[0].trim.parent() is made[0]
