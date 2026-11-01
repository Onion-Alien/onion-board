"""New sounds are marked like unread mail (ui/window/newsounds.py): a count on the
Sounds tab while you're elsewhere, a glow on each new card until the mouse goes over
it or you leave Sounds having seen it."""
import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtGui import QEnterEvent

from soundboard.sounds.config import SoundMeta
from soundboard.ui.window.tabcontrol import TAB_INDEX
from test_mainwindow import window as main_window  # noqa: F401 - the real window, offscreen


def _add(w, sid):
    m = SoundMeta(id=sid, name=sid, file=w.cfg.sounds[0].file, duration=1.0)
    w.audio[sid] = np.zeros((480, 2), np.float32)
    w.soundctl.add_to_board(m)


def _count(w):
    return w.tabs.tabBar().property(f"_count{w.tabs.indexOf(w.sounds_page)}") or 0


def _hover(pad):
    c = QPointF(pad.rect().center())
    pad.enterEvent(QEnterEvent(c, c, c))


def test_new_sounds_counted_away_and_glow_until_seen(main_window):  # noqa: F811
    w = main_window
    assert not any(p.fresh for p in w.pads.values())   # the library it started with
    w.tabs.setCurrentIndex(TAB_INDEX["radio"])
    _add(w, "a")
    _add(w, "b")
    assert _count(w) == 2 and w.pads["a"].fresh and w.pads["b"].fresh
    assert "2" in w.rail.buttons[0].accessibleDescription()
    w.tabs.setCurrentIndex(TAB_INDEX["sounds"])
    assert _count(w) == 0 and w.pads["a"].fresh   # looking at the board: still glowing
    _hover(w.pads["a"])
    assert not w.pads["a"].fresh and w.pads["b"].fresh
    _add(w, "c")   # added while on Sounds: glows, not counted
    assert _count(w) == 0 and w.pads["c"].fresh
    w.tabs.setCurrentIndex(TAB_INDEX["radio"])   # left having seen them: all read
    assert not any(p.fresh for p in w.pads.values()) and _count(w) == 0


def test_removed_new_sound_leaves_the_count(main_window):  # noqa: F811
    w = main_window
    w.tabs.setCurrentIndex(TAB_INDEX["radio"])
    _add(w, "a")
    assert _count(w) == 1
    w.cfg.sounds = [m for m in w.cfg.sounds if m.id != "a"]
    w._rebuild_pads()
    assert _count(w) == 0


def test_arrow_while_downloading(main_window, monkeypatch):  # noqa: F811
    w = main_window
    w.tabs.setCurrentIndex(TAB_INDEX["radio"])
    coming = w.tabs.tabBar().property
    monkeypatch.setattr(w.impctl, "_pending_imports", 3)
    w.newctl.follow()
    assert coming(f"_coming{w.tabs.indexOf(w.sounds_page)}") is True
    assert w.newctl._busy_timer.isActive()
    monkeypatch.setattr(w.impctl, "_pending_imports", 0)
    w.newctl._busy_timer.timeout.emit()
    assert coming(f"_coming{w.tabs.indexOf(w.sounds_page)}") is False
    assert not w.newctl._busy_timer.isActive()
