"""Space plays / pauses on the Sounds and Radio tabs wherever the focus is
(ui/spacekey.py), and the web result in the player shows that it's playing."""
import numpy as np
import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFocusEvent, QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from soundboard.online import ytdl
from soundboard.audio.engine import SR
from soundboard.ui.sounds.linkbar import PLAY_ID as LINK_ID
from soundboard.ui.sounds.ytsearch import ResultRow
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
        monkeypatch.setattr(e, "stop", lambda sid: self.voices.pop(sid, None))

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


def toolbar_button(window):
    """A plain button on the Sounds toolbar (the real ones there open menus)."""
    btn = QPushButton("x", window.sounds_toolbar)
    btn.show()
    return btn


def focused(monkeypatch, w):
    monkeypatch.setattr(QApplication, "focusWidget", staticmethod(lambda: w))


def test_space_pauses_the_player_after_a_button_was_clicked(window, player, monkeypatch):
    window.playctl.play("s0")
    assert player.paused("s0") is False
    btn = toolbar_button(window)
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
    window.playctl.play("s0")
    btn = toolbar_button(window)
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
    window.searchctl.on_link_played("What Is Love", data, 1.0)
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
    window.tickctl.tick()
    assert row.now == "playing" and row.btn_play.text() == "Pause"
    assert row.property("playing") is True and row.thumb.now == "playing"
    window.playctl.toggle_play_pause()
    window.tickctl.tick()
    assert row.now == "paused" and row.btn_play.text() == "Resume"
    del player.voices[LINK_ID]                    # it finished
    window.tickctl.tick()
    assert row.now == "" and row.btn_play.text() == "Play" and not row.property("playing")


def test_back_to_my_sounds_stands_out(window):
    b = window.ytresults.btn_back
    assert b.text() == "Back" and b.objectName() == "backhome"
    assert b.accessibleName() == "Back to my sounds" and b.toolTip() == ""   # it says Back


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


def test_a_new_sound_stops_the_one_playing_unless_set_to_overlap(window, player, monkeypatch):
    """One sound at a time by default: a pad press stops the others (engine "solo");
    a sound set to Overlap still layers over them."""
    modes = {}
    play = window.engine.play
    monkeypatch.setattr(window.engine, "play", lambda sid, *a, **k: (
        modes.__setitem__(sid, k.get("mode")), play(sid, *a, **k))[1])
    m = window.meta("s0")
    window.playctl.play("s0")
    assert modes["s0"] == "solo"
    m.mode = "overlap"
    window.playctl._cool.clear()
    window.playctl.play("s0")
    assert modes["s0"] == "overlap"


def test_a_web_song_saved_as_a_pad_plays_once_not_twice(window, player, monkeypatch):
    """Played from a search, then added to the board and its pad pressed: one song, so
    the web copy stops and the pad starts from the top (as a second press of a pad
    does), never both side by side in Now playing."""
    _link(window, "https://www.youtube.com/watch?v=abc&list=x")
    m = window.meta("s0")
    monkeypatch.setattr(m, "source", {"link": "https://youtu.be/abc"})
    window.playctl.play("s0")
    assert LINK_ID not in player.voices and "s0" in player.voices


def test_another_pad_leaves_the_web_song_playing(window, player, monkeypatch):
    _link(window)
    monkeypatch.setattr(window.meta("s0"), "source", {"link": "https://youtu.be/other"})
    window.playctl.play("s0")
    assert LINK_ID in player.voices and "s0" in player.voices


def test_playing_a_search_hit_already_on_the_board_plays_its_pad(window, player, monkeypatch):
    monkeypatch.setattr(window.meta("s0"), "source",
                        {"link": "https://www.youtube.com/watch?v=abc"})
    fetched = []
    monkeypatch.setattr(window.linkbar, "play_once", lambda: fetched.append(1) or True)
    r = ytdl.Result(id="abc", title="What Is Love", channel="Haddaway", seconds=5)
    window.searchctl._from_youtube(r, True)
    assert "s0" in player.voices and LINK_ID not in player.voices and not fetched


def test_a_sound_played_at_zero_sounds_volume_says_nobody_else_hears_it(
        window, player, monkeypatch):
    """At 0% Sounds volume a pad still plays in your own headphones, so it looked like it
    worked while nobody else heard it: one toast says so, with a button to set it back."""
    said = []
    monkeypatch.setattr(window, "toast", lambda text, kind="", ms=0, **kw: said.append(
        (text, kw.get("action"))))
    window.cfg.route = "cable"
    window.vol_sound.spin.setValue(0)
    assert window.cfg.sound_vol == 0
    window.playctl.play("s0")
    hint = [(t, a) for t, a in said if "0%" in t]
    assert len(hint) == 1
    window.playctl._cool.clear()
    window.playctl.play("s0")
    assert len([t for t, _ in said if "0%" in t]) == 1   # once, not on every press
    hint[0][1][1]()   # its button
    assert window.cfg.sound_vol == 1.0
    window.vol_sound.spin.setValue(0)   # down again, nothing played in between
    window.playctl._cool.clear()
    window.playctl.play("s0")
    assert len([t for t, _ in said if "0%" in t]) == 2   # up and down again: said again


def test_no_zero_volume_hint_at_a_normal_volume_or_when_not_sending(
        window, player, monkeypatch):
    said = []
    monkeypatch.setattr(window, "toast", lambda text, kind="", ms=0, **kw: said.append(text))
    window.cfg.route = "cable"
    window.vol_sound.spin.setValue(100)
    window.playctl.play("s0")
    window.cfg.route = "off"   # not sending at all: the volume isn't why
    window.vol_sound.spin.setValue(0)
    window.playctl._cool.clear()
    window.playctl.play("s0")
    assert not [t for t in said if "0%" in t]


def test_space_ticks_a_clicked_box_in_settings_over_the_sounds_tab(window, player, monkeypatch):
    """Settings is a page over the tabs: Space there is the box's, not play / pause."""
    window.playctl.play("s0")
    window.setctl.open_settings("privacy")
    box = window.setctl._settings_dlg.offline_box
    focused(monkeypatch, box)
    focus(box, Qt.MouseFocusReason)
    QTest.keyClick(box, Qt.Key_Space)
    assert box.isChecked() and player.paused("s0") is False
    QTest.keyClick(box, Qt.Key_Space)   # and back, so nothing stays offline
    assert not box.isChecked()
    window.setctl.close_settings()
    btn = toolbar_button(window)
    focused(monkeypatch, btn)
    focus(btn, Qt.MouseFocusReason)
    space(btn)
    assert player.paused("s0") is True   # back on Sounds: Space pauses again
