"""Space plays / pauses on the Sounds and Radio tabs wherever the focus is
(ui/spacekey.py), and the web result in the player shows that it's playing."""
import numpy as np
import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFocusEvent, QKeyEvent
from PySide6.QtWidgets import QApplication

from soundboard import ytdl
from soundboard.engine import SR
from soundboard.ui.linkbar import PLAY_ID as LINK_ID
from soundboard.ui.ytsearch import ResultRow
from test_mainwindow import window as main_window  # noqa: F401 - the real window, offscreen


class FakePlayer:
    """The engine's voices, without audio devices: sid -> [progress, paused]."""

    def __init__(self, window, monkeypatch):
        self.voices = {}
        e = window.engine
        monkeypatch.setattr(e, "state", lambda sid: tuple(self.voices[sid])
                            if sid in self.voices else None)
        monkeypatch.setattr(e, "set_paused", lambda sid, p: self.voices[sid].__setitem__(1, p))
        monkeypatch.setattr(e, "playing", lambda: {s: tuple(v) for s, v in self.voices.items()})
        monkeypatch.setattr(e, "play", lambda sid, *a, **k: self.voices.__setitem__(
            sid, [0.0, False]) or object())

    def paused(self, sid):
        return self.voices[sid][1] if sid in self.voices else None


@pytest.fixture
def window(main_window):  # noqa: F811
    main_window.tabs.setCurrentWidget(main_window.sounds_page)
    main_window.show()
    return main_window


@pytest.fixture
def player(window, monkeypatch):
    window.audio["s0"] = np.zeros((SR * 5, 2), dtype=np.float32)
    return FakePlayer(window, monkeypatch)


def focus(w, reason):
    """Give `w` the focus as a click (MouseFocusReason) or Tab would."""
    w.setFocus(reason)
    QApplication.sendEvent(w, QFocusEvent(QEvent.FocusIn, reason))


def space(w):
    """Space pressed with `w` focused, the way Qt delivers it: the app's filters first."""
    QApplication.sendEvent(w, QKeyEvent(QEvent.KeyPress, Qt.Key_Space, Qt.NoModifier, " "))


def focused(monkeypatch, w):
    monkeypatch.setattr(QApplication, "focusWidget", staticmethod(lambda: w))


def test_space_pauses_the_player_after_a_button_was_clicked(window, player, monkeypatch):
    window.play("s0")
    assert player.paused("s0") is False
    btn = window.btn_yt
    clicks = []
    btn.clicked.connect(lambda: clicks.append(1))
    focused(monkeypatch, btn)
    focus(btn, Qt.MouseFocusReason)
    space(btn)
    assert player.paused("s0") is True and not clicks   # paused, the button not pressed
    space(btn)
    assert player.paused("s0") is False


def test_space_still_presses_a_button_reached_with_tab_and_types_in_text(
        window, player, monkeypatch):
    window.play("s0")
    btn = window.btn_yt
    focused(monkeypatch, btn)
    focus(btn, Qt.TabFocusReason)
    space(btn)
    assert player.paused("s0") is False         # the keyboard's way to press a button
    box = window.search
    focused(monkeypatch, box)
    focus(box, Qt.MouseFocusReason)
    space(box)
    assert player.paused("s0") is False and box.text() == " "


def _link(window, url="https://www.youtube.com/watch?v=abc"):
    """A web result played once, as the link bar does it."""
    data = np.zeros((SR * 5, 2), dtype=np.float32)
    window.linkbar.url = url
    window.engine.play(LINK_ID, data, 1.0, mode="restart")
    window.on_link_played("What Is Love", data, 1.0)
    r = ytdl.Result(id="abc", title="What Is Love", channel="Haddaway", seconds=5)
    row = ResultRow(r)
    row.play.connect(window.ytresults.play)
    window.ytresults.rows.addWidget(row)
    window.ytresults._rows.append(row)
    window.ytresults.show()
    return row


def test_space_on_a_web_result_playing_pauses_it_not_downloads_it_again(
        window, player, monkeypatch):
    row = _link(window)
    fetched = []
    monkeypatch.setattr(window.linkbar, "play_once", lambda: fetched.append(1) or True)
    focused(monkeypatch, row)
    focus(row, Qt.MouseFocusReason)
    space(row)                                    # the row's own Space: it's the one playing
    assert player.paused(LINK_ID) is True and not fetched
    row.btn_play.click()                          # its Play button does the same
    assert player.paused(LINK_ID) is False and not fetched


def test_the_web_result_in_the_player_says_so(window, player):
    row = _link(window)
    window.tick()
    assert row.now == "playing" and row.btn_play.text() == "Pause"
    assert row.property("playing") is True and row.thumb.now == "playing"
    window.toggle_play_pause()
    window.tick()
    assert row.now == "paused" and row.btn_play.text() == "Resume"
    del player.voices[LINK_ID]                    # it finished
    window.tick()
    assert row.now == "" and row.btn_play.text() == "Play" and not row.property("playing")


def test_back_to_my_sounds_stands_out(window):
    b = window.ytresults.btn_back
    assert b.text() == "Back to my sounds" and b.objectName() == "backhome"


def test_space_on_the_radio_tab_plays_and_stops_the_radio(window, monkeypatch):
    window.tabs.setCurrentWidget(window.radio_page)
    calls = []
    monkeypatch.setattr(window.radio, "toggle_play", lambda: calls.append(1), raising=False)
    target = window.tabs.tabBar()
    focused(monkeypatch, target)
    focus(target, Qt.MouseFocusReason)
    space(target)
    assert calls == [1]
    window.tabs.setCurrentIndex(window.tabs.count() - 1)   # Setup: its own Space
    space(target)
    assert calls == [1]
