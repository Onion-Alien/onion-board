"""Hotkeys and per-sound options other soundboards are asked for: replay the last sound,
switch category, louder / quieter, mic and voice changer keys, all hotkeys off, a set
of hotkeys per category, a sound's queue / wait / cooldown / "only others hear it",
playing a whole category and one-click pads."""
from conftest import said, unsay
import pytest

import numpy as np
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (QApplication, QLabel, QPushButton, QStyle,
                               QStyleOptionButton)

from soundboard import voicefx

from soundboard.ui.window import responsive
from soundboard.ui.kit import toast
from soundboard.core import backup
from soundboard.win import thumbbar
from soundboard.sounds.library import Config, SoundMeta
from soundboard.ui.kit.widgets import Pad
from test_mainwindow import window as main_window  # noqa: F401  (the real MainWindow)


@pytest.fixture
def window(main_window):  # noqa: F811
    w = main_window
    for sid in ("s0", "s1"):
        w.audio[sid] = np.zeros((480, 2), np.float32)
    return w


@pytest.fixture
def calls(window, monkeypatch):
    """What reached the engine: (sid, keyword arguments) per play."""
    got = []
    monkeypatch.setattr(window.engine, "play",
                        lambda sid, data, gain, **kw: got.append((sid, kw)))
    return got


def playing(monkeypatch, w, sids):
    monkeypatch.setattr(w.engine, "playing", lambda: {s: (0.5, False) for s in sids})


def test_last_sound_hotkey_plays_it_again(window, calls):
    w = window
    w.hkctl.on_hotkey("__last__")            # nothing yet: just the fail beep
    assert calls == []
    w.playctl.play("s1")
    w.hkctl.on_hotkey("__last__")
    assert [c[0] for c in calls] == ["s1", "s1"]


def test_category_keys_cycle_through_all_and_the_categories(window):
    w = window
    w.catctl.new_category(name="Memes")
    w.catctl.new_category(name="Music")
    w.catctl.set_category("")
    w.hkctl.on_hotkey("__nextcat__")
    assert w.cfg.category == "Memes"
    w.hkctl.on_hotkey("__nextcat__")
    w.hkctl.on_hotkey("__nextcat__")
    assert w.cfg.category == ""        # wraps round to All
    w.hkctl.on_hotkey("__prevcat__")
    assert w.cfg.category == "Music"


def test_volume_keys_step_the_sounds_volume_by_ten(window):
    w = window
    w.vol_sound.spin.setValue(95)
    w.hkctl.on_hotkey("__volup__")
    assert w.cfg.sound_vol == pytest.approx(1.1)
    w.vol_sound.spin.setValue(0)
    w.hkctl.on_hotkey("__voldown__")
    assert w.cfg.sound_vol == 0.0


def test_mic_and_voice_changer_keys(window):
    w = window
    was = w.cfg.mic_enabled
    w.hkctl.on_hotkey("__mic__")
    assert w.cfg.mic_enabled is (not was)
    power = w.voice.fx.btn_power
    assert not power.isChecked()
    w.hkctl.on_hotkey("__voice__")
    assert power.isChecked()
    w.hkctl.on_hotkey("__voice__")
    assert not power.isChecked()
    w.hkctl.on_hotkey("__voicehold__")      # on while held, back as it was when let go
    assert power.isChecked()
    w.hkctl.on_hotkey_released("__voicehold__")
    assert not power.isChecked()
    w.hkctl.on_hotkey("__voicerandom__")       # the Random voice key: a voice, on
    first = w.voice.fx.preset
    assert power.isChecked() and first in voicefx.PRESETS
    w.hkctl.on_hotkey("__voicerandom__")
    assert power.isChecked() and w.voice.fx.preset != first


def test_all_voices_key_pauses_and_brings_back_the_same_voice(window, monkeypatch):
    """The All voices key is the Voice tab's Voices switch, from in a game."""
    w = window
    registered = []
    monkeypatch.setattr(w.hotkeys, "register", lambda m: registered.append(dict(m)))
    w.hkctl.set_global_hotkey("voices_hotkey", "f9")
    assert registered[-1]["f9"] == "__voices__"
    cues = []
    monkeypatch.setattr(w.playctl, "cue", cues.append)
    power = w.voice.fx.btn_power
    w.voice.fx.pick("Robot")
    w.hkctl.on_hotkey("__voices__")
    assert not power.isChecked() and not w.voice.bar.master.isChecked()
    w.hkctl.on_hotkey("__voices__")
    assert power.isChecked() and w.voice.fx.preset == "Robot"
    assert w.voice.bar.master.isChecked()
    assert cues == ["stop", "start"]


def test_all_hotkeys_off_leaves_only_its_own_key(window, monkeypatch, calls):
    w = window
    registered = []
    monkeypatch.setattr(w.hotkeys, "register", lambda m: registered.append(dict(m)))
    w.meta("s0").hotkey = "f1"
    w.hkctl.set_global_hotkey("hotkeys_off_hotkey", "f12")
    assert registered[-1]["f1"] == "s0"
    w.hkctl.on_hotkey("__hotkeys__")
    assert registered[-1] == {"f12": "__hotkeys__"}
    w.hkctl.on_hotkey("s0")                 # one already queued when they went off
    assert calls == []
    w.hkctl.on_hotkey("__hotkeys__")
    assert registered[-1]["f1"] == "s0"


def test_clearing_the_hotkeys_off_key_while_off_turns_them_back_on(window, monkeypatch):
    w = window
    registered = []
    monkeypatch.setattr(w.hotkeys, "register", lambda m: registered.append(dict(m)))
    w.meta("s0").hotkey = "f1"
    w.hkctl.set_global_hotkey("hotkeys_off_hotkey", "f12")
    w.hkctl.on_hotkey("__hotkeys__")
    assert registered[-1] == {"f12": "__hotkeys__"}
    w.hkctl.set_global_hotkey("hotkeys_off_hotkey", "")   # nothing left to turn them on
    assert not w.hkctl._hotkeys_off and registered[-1]["f1"] == "s0"
    w.hkctl.set_global_hotkey("hotkeys_off_hotkey", "f12")
    w.hkctl.on_hotkey("__hotkeys__")
    w.hkctl.set_global_hotkey("pause_hotkey", "f12")      # the key went to something else
    assert not w.hkctl._hotkeys_off and registered[-1]["f1"] == "s0"
    w.cfg.hotkeys_off_hotkey = ""
    w.hkctl.toggle_hotkeys()                               # no key: they don't go off
    assert not w.hkctl._hotkeys_off


def test_a_set_of_hotkeys_per_category(window, monkeypatch, calls):
    w = window
    registered = []
    monkeypatch.setattr(w.hotkeys, "register", lambda m: registered.append(dict(m)))
    w.catctl.new_category(name="Memes")
    w.catctl.new_category(name="Music")
    a, b = w.meta("s0"), w.meta("s1")
    a.tags, b.tags = ["Memes"], ["Music"]
    w.hkctl.set_scoped_hotkeys(True)
    a.hotkey = "f1"
    w.hkctl._clear_dupe_hotkey(a)
    b.hotkey = "f1"
    w.hkctl._clear_dupe_hotkey(b)           # no category in common: both keep it
    assert a.hotkey == b.hotkey == "f1"
    w.catctl.set_category("Memes")
    assert registered[-1]["f1"] == "s0"
    w.catctl.set_category("Music")
    assert registered[-1]["f1"] == "s1"
    w.hkctl.set_scoped_hotkeys(False)       # one key, one sound again: the first keeps it
    assert (a.hotkey, b.hotkey) == ("f1", "")


def test_queue_sound_waits_for_the_one_playing(window, monkeypatch, calls):
    w = window
    w.meta("s1").mode = "queue"
    playing(monkeypatch, w, ["s0"])
    w.playctl.play("s1")
    assert calls == [] and w.playctl._queue == ["s1"]
    playing(monkeypatch, w, [])
    w.tickctl.tick()
    assert [c[0] for c in calls] == ["s1"] and calls[0][1]["mode"] == "restart"
    assert w.playctl._queue == []


def test_play_next_and_stop_everything_clears_the_queue(window, monkeypatch, calls):
    w = window
    playing(monkeypatch, w, ["s0"])
    w.playctl.queue_sound("s1")
    assert w.playctl._queue == ["s1"]
    w.playctl.stop_all()
    assert w.playctl._queue == []


def test_skip_starts_the_next_queued_sound_now(window, monkeypatch, calls):
    w = window
    stopped = []
    monkeypatch.setattr(w.engine, "stop", stopped.append)
    playing(monkeypatch, w, ["s0"])
    w.playctl.queue_sound("s1")
    w.btn_skip.click()
    assert stopped == ["s0"] and [c[0] for c in calls] == ["s1"] and w.playctl._queue == []


def test_a_web_search_play_waits_for_your_sound_instead_of_playing_over_it(
        window, monkeypatch, calls):
    """Your sound plays, then a search result's Play: it goes in Up next (it used to
    play on top of the song), and starts once yours ends. A looping background
    sound doesn't hold it up. Skip starts it at once."""
    from soundboard.ui.sounds import linkbar

    w = window
    monkeypatch.setattr(linkbar.busy, "toast", lambda *a, **kw: None)
    stopped = []
    monkeypatch.setattr(w.engine, "stop", stopped.append)
    song = np.zeros((480, 2), np.int16)
    playing(monkeypatch, w, ["s0"])
    w.linkbar._play(song, 1.0, "Song", "https://example.com/a")
    assert calls == [] and w.linkbar.up_next() == ["Song"]
    w.tickctl.tick()
    assert calls == []                                 # still waits for s0
    playing(monkeypatch, w, [])
    w.tickctl.tick()
    assert [c[0] for c in calls] == ["__link__"] and w.linkbar.up_next() == []

    calls.clear()                                      # a loop is only a background
    w.meta("s1").loop = True
    playing(monkeypatch, w, ["s1"])
    w.linkbar._play(song, 1.0, "Two", "https://example.com/b")
    assert [c[0] for c in calls] == ["__link__"]

    calls.clear()                                      # Skip: the song starts now
    playing(monkeypatch, w, ["s0"])
    w.linkbar._play(song, 1.0, "Three", "https://example.com/c")
    assert calls == []
    w.btn_skip.click()
    assert stopped == ["s0"] and [c[0] for c in calls] == ["__link__"]


def test_play_next_waits_for_a_web_search_song(window, monkeypatch, calls):
    w = window
    playing(monkeypatch, w, ["__link__"])
    w.playctl.queue_sound("s1")
    assert calls == [] and w.playctl._queue == ["s1"]
    w.tickctl.tick()
    assert calls == []
    playing(monkeypatch, w, [])
    w.tickctl.tick()
    assert [c[0] for c in calls] == ["s1"]


def test_skip_stops_the_web_search_song_your_sound_waits_for(window, monkeypatch, calls):
    """Your sound waits for a web search's song: Skip starts it now and the song makes
    way (it kept playing under it)."""
    w = window
    stopped = []
    monkeypatch.setattr(w.engine, "stop", stopped.append)
    playing(monkeypatch, w, ["__link__"])
    w.playctl.queue_sound("s1")
    w.btn_skip.click()
    # (the fake engine never lets it go, so the sound starting stops it again too)
    assert stopped and set(stopped) == {"__link__"} and [c[0] for c in calls] == ["s1"]


def test_skip_with_nothing_waiting_just_stops_the_players_sound(window, monkeypatch, calls):
    w = window
    stopped = []
    monkeypatch.setattr(w.engine, "stop", stopped.append)
    playing(monkeypatch, w, ["s0"])
    w.playctl.select("s0")
    w.hkctl.on_hotkey("__skip__")
    assert stopped == ["s0"] and calls == []


def test_play_a_whole_category_one_after_another(window, monkeypatch, calls):
    w = window
    w.catctl.new_category(name="Memes")
    for sid in ("s0", "s1"):
        w.meta(sid).tags = ["Memes"]
    monkeypatch.setattr(w.engine, "stop", lambda sid: None)
    playing(monkeypatch, w, [])
    w.playctl.queue_category("Memes", shuffled=False)
    assert [c[0] for c in calls] == ["s0"] and w.playctl._queue == ["s1"]
    w.tickctl.tick()
    assert [c[0] for c in calls] == ["s0", "s1"]


def test_cooldown_ignores_spam(window, calls):
    w = window
    w.meta("s0").cooldown = 30.0
    w.playctl.play("s0")
    w.playctl.play("s0")
    assert len(calls) == 1
    w.playctl._cool.clear()
    w.playctl.play("s0")
    assert len(calls) == 2


def test_wait_before_playing_and_stop_cancels_it(window, calls, qapp):
    from conftest import process_events
    w = window
    w.meta("s0").delay = 0.05
    w.playctl.play("s0")
    assert calls == [] and "s0" in w.playctl._waiting
    process_events(qapp, lambda: calls)
    assert [c[0] for c in calls] == ["s0"]
    w.playctl.play("s0")
    w.playctl.stop_all()
    assert w.playctl._waiting == {}


def test_only_them_skips_my_headphones(window, calls):
    w = window
    w.meta("s0").only_them = True
    w.playctl.play("s0")
    w.playctl.play("s1")
    assert calls[0][1]["only"] == ("main", "obs") and calls[1][1]["only"] is None


def test_new_sound_options_survive_a_save_and_a_backup(app_dir, tmp_path):
    cfg = Config()
    src = tmp_path / "a.wav"
    import soundfile as sf
    sf.write(src, np.zeros((4800, 2), np.float32), 48000)
    m = SoundMeta(id="x", name="A", file=str(src), mode="queue", only_them=True,
                  delay=99.0, cooldown=2.5)
    cfg.sounds.append(m)
    cfg.save()
    back = Config.load().sounds[0]
    assert (back.mode, back.only_them, back.delay, back.cooldown) == ("queue", True, 10.0, 2.5)
    raw = {"sounds": [{"id": "y", "name": "B", "file": str(src), "mode": "nonsense"}]}
    assert Config.from_raw(raw).sounds[0].mode == "restart"
    assert {"only_them", "delay", "cooldown"} <= set(backup.SOUND_FIELDS)


def test_space_on_a_playing_pad_pauses_it_instead_of_restarting(window, monkeypatch):
    from PySide6.QtTest import QTest
    w = window
    played, paused = [], []
    monkeypatch.setattr(w.playctl, "play", played.append)
    state = {}
    monkeypatch.setattr(w.engine, "state", lambda sid: state.get(sid))
    monkeypatch.setattr(w.engine, "set_paused", lambda sid, p: paused.append((sid, p)))
    pad = w.pads["s0"]
    QTest.keyClick(pad, Qt.Key_Space)
    assert played == ["s0"] and paused == []        # not playing: Space plays it
    state["s0"] = (0.3, False)                      # playing
    QTest.keyClick(pad, Qt.Key_Space)
    assert played == ["s0"] and paused == [("s0", True)] and w.current == "s0"
    state["s0"] = (0.3, True)                       # paused: Space resumes it
    QTest.keyClick(pad, Qt.Key_Space)
    assert paused[-1] == ("s0", False) and played == ["s0"]


def test_one_click_plays_a_pad(window, monkeypatch):
    w = window
    played = []
    monkeypatch.setattr(w.playctl, "play", played.append)
    pad = w.pads["s0"]

    def click():
        pos = QPointF(5, 5)
        for kind in (QMouseEvent.MouseButtonPress, QMouseEvent.MouseButtonRelease):
            ev = QMouseEvent(kind, pos, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
            (pad.mousePressEvent if kind == QMouseEvent.MouseButtonPress
             else pad.mouseReleaseEvent)(ev)
    try:
        click()
        assert played == ["s0"]       # the default: a click plays it (new users clicked
        w.set_single_click(False)     # a pad, nothing happened, and they left)
        pad._last_click = -1e9        # (not a double-click with the one before)
        click()
        assert played == ["s0"]       # off: a click only selects it
    finally:
        Pad.single_click = True
    assert Config().single_click   # (saved configs keep what they had)


def test_a_double_click_plays_wherever_the_two_clicks_land(window, monkeypatch):
    w = window
    played = []
    monkeypatch.setattr(w.playctl, "play", played.append)
    pad = w.pads["s0"]
    monkeypatch.setattr(Pad, "single_click", False)   # (Settings: Play pads with one click, off)

    def click(x, y):
        pos = QPointF(x, y)
        for kind in (QMouseEvent.MouseButtonPress, QMouseEvent.MouseButtonRelease):
            ev = QMouseEvent(kind, pos, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
            (pad.mousePressEvent if kind == QMouseEvent.MouseButtonPress
             else pad.mouseReleaseEvent)(ev)
    click(4, 4)                                    # top left: selects it
    assert played == []
    click(pad.width() - 4, pad.height() - 4)       # then bottom right: plays it
    assert played == ["s0"]
    assert pad._press is None                      # and no drag starts from that press
    click(4, 4)                                    # a third click starts over
    assert played == ["s0"]


def test_the_queue_shows_above_the_pads_and_can_be_trimmed(window, monkeypatch, calls):
    w = window
    w._ui_live = True
    playing(monkeypatch, w, ["s0"])
    w.playctl.queue_sound("s1")
    w.playctl._update_chips({"s0": (0.5, False)})
    assert not w.playing_row.isHidden()
    w.playctl._unqueue(0)
    w.playctl._update_chips({})
    assert w.playctl._queue == [] and w.playing_row.isHidden()


def test_a_removed_sound_leaves_up_next(window, monkeypatch, calls):
    """A queued sound taken off the board leaves the queue: Up next's count and list
    never show it (as its raw id) after it's gone."""
    w = window
    w._ui_live = True
    playing(monkeypatch, w, ["s0"])
    w.playctl.queue_sound("s1")
    w.playctl.queue_sound("s0")
    w.rmctl.remove_sounds(["s1"])
    assert w.playctl._queue == ["s0"]
    assert w._up_next_chip.count.text() == "1 waiting"
    assert [i.text for i in w.playctl._up_next_items()] == [w.meta("s0").name]


def test_a_double_click_on_a_queue_chips_x_takes_out_only_that_one(window, monkeypatch, calls):
    w = window
    w._ui_live = True
    playing(monkeypatch, w, ["s0"])
    w.playctl.queue_sound("s1")
    w.playctl.queue_sound("s0")
    w.playctl._update_chips({"s0": (0.5, False)})
    w.playctl.open_up_next()          # Up next's list
    first_x = [b for b in w._up_next_popup.findChildren(QPushButton)
               if b.toolTip() == "Take it out of the queue"][0]
    first_x.click()
    first_x.click()                   # the same ✕ again before the row is remade
    assert w.playctl._queue == ["s0"]


def test_a_double_click_on_stop_doesnt_stop_the_next_queued_sound(window, monkeypatch, calls):
    w = window
    stopped = []
    monkeypatch.setattr(w.engine, "stop", stopped.append)
    w.playctl.select("s0")
    w.playctl.stop_current()
    w.playctl.select("s1")                    # the queue's next sound took the player
    w.playctl.stop_current()                  # the double click's second press
    assert stopped == ["s0"]
    w.playctl._stopped_at = (0.0, "s0")       # a press well after: stops it
    w.playctl.stop_current()
    assert stopped == ["s0", "s1"]


def two_playing(w):
    """s0 then s1 really playing (a stand-in headphone output), their chips up."""
    w._ui_live = True
    w.engine.mon_stream = object()
    w.engine.rates["mon"] = 48000
    for sid in ("s0", "s1"):
        w.audio[sid] = np.full((48000 * 20, 2), 0.01, np.float32)
        w.meta(sid).mode = "overlap"   # layered (the default stops the other one)
    w.playctl.play("s0")
    w.playctl.play("s1")
    w.playctl._update_chips(w.engine.playing())
    assert list(w._chips) == ["s0", "s1"]


def chip_stop(w, sid):
    w._chips[sid].findChildren(QPushButton)[-1].click()
    w.playctl._update_chips(w.engine.playing())


def test_stopping_one_of_two_keeps_the_others_chip(window):
    """Two playing, ■ on the right one: the row used to hide with one sound left, so
    the left one's chip went too and it looked like both had stopped."""
    w = window
    two_playing(w)
    chip_stop(w, "s1")
    assert list(w.engine.playing()) == ["s0"]
    assert list(w._chips) == ["s0"] and not w.playing_row.isHidden()
    w.playctl._stopped_at = (0.0, "s1")       # well after the first press
    chip_stop(w, "s0")                # the last one stops: the row goes
    assert not w.engine.playing() and w.playing_row.isHidden()
    w.playctl.play("s1")                      # one sound on its own: its chip, same as always
    w.playctl._update_chips(w.engine.playing())
    assert list(w._chips) == ["s1"] and not w.playing_row.isHidden()


def test_a_double_click_on_a_now_playing_chips_stop_stops_only_that_one(window):
    """The row is remade after a ■ and another sound's ■ can slide in under the mouse:
    the double click's second press used to stop that one too."""
    w = window
    two_playing(w)
    chip_stop(w, "s1")
    chip_stop(w, "s0")                # the second press, on the ■ now under the mouse
    assert list(w.engine.playing()) == ["s0"]


def test_the_mini_players_stop_all_says_all(window):
    assert window.mini_stop.text() == "All" and window.mini_st.text() == ""
    assert window.mini_stop.accessibleName() == "Stop all"   # a screen reader says it all


def test_the_mini_players_stop_all_is_whole_at_the_smallest_size(window):
    """At its narrowest the row squeezed "■ All" down to "■ A" (CI's fonts are wider)."""
    w = window
    w.show()
    w.resize(responsive.MIN_SIZE.width(), 600)
    QApplication.processEvents()
    assert w.fitctl.is_mini()
    assert w.mini_stop.shown().text == "All"   # whole: the ■ goes first if it must


def test_the_mini_players_full_board_button_brings_the_board_back(window):
    """Dragged under ~460 px the window turned into the mini player by itself, with
    no way back on it but dragging: its Full board button grows it back."""
    w = window
    w.show()
    w.resize(440, 600)
    QApplication.processEvents()
    assert w.fitctl.is_mini() and w.mini_full.isVisibleTo(w)
    assert "mini player" in w.mini_full.toolTip()
    w.mini_full.click()
    QApplication.processEvents()
    assert not w.fitctl.is_mini() and w.width() > 440


def test_the_strip_says_when_the_mic_is_muted(window):
    """Unticked, the bottom strip's mic group still said "My mic": it says "Mic muted"
    then, as the mini player does, and its narrow-strip icon button too."""
    w = window
    w.chk_mic.setChecked(True)
    assert w.mic_lbl.text() == "My mic"
    w.chk_mic.setChecked(False)
    assert w.mic_lbl.text() == "Mic muted" and w.mini_mic.text() == "Mic muted"
    assert w._deck_tabs[0].accessibleName() == "Mic muted"
    w.mini_mic.setChecked(True)
    assert w.mic_lbl.text() == "My mic" and w._deck_tabs[0].toolTip() == "My mic"


def test_muted_with_the_mic_on_the_rail_button_keeps_a_word(window):
    """Muted while your mic still goes out, "Only your mic" didn't fit the rail's
    button and it lost its word: "Mic only" then."""
    w = window
    rail = w.rail.output
    w.btn_air.setProperty("voiceonly", True)
    w.btn_air.setChecked(False)
    rail.refresh()
    fm = rail.mute.fontMetrics()
    room = rail.mute.width() - rail._px(rail.PAIR_ICON) - rail._px(10)
    if fm.horizontalAdvance(" Only your mic") > room >= fm.horizontalAdvance(" Mic only"):
        assert rail.mute.text().strip() == "Mic only"
    assert rail.mute.text().strip() in ("Only your mic", "Mic only", "")


def test_stop_all_turns_the_voice_changer_off_but_the_say_bars_stop_doesnt(window):
    w = window
    w.voice.fx.btn_power.setChecked(True)
    w.voice.speech.say_stop.click()   # the Say bar's Stop: only the typed line
    assert w.voice.fx.btn_power.isChecked()
    w.stop_btn.click()                # the side rail's Stop all: the voices go off too
    assert not w.voice.fx.btn_power.isChecked()
    w.voice.fx.btn_power.setChecked(True)
    w.thumbbar.actions[thumbbar.STOP]()   # the taskbar preview's Stop: the same Stop all
    assert not w.voice.fx.btn_power.isChecked()


def test_the_queue_status_goes_once_the_queue_is_empty(window, monkeypatch, calls):
    w = window
    playing(monkeypatch, w, ["s0"])
    w.playctl.queue_sound("s1")
    w.playctl.queue_sound("s0")
    assert said(w).startswith("Up next: “Airhorn” (+1 more)")
    w.playctl._unqueue(0)                     # the ✕ on Airhorn's chip
    assert said(w).startswith("Up next: “Boom”")
    playing(monkeypatch, w, [])
    w.tickctl.tick()                          # the last one starts: nothing is up next
    assert w.playctl._queue == [] and not said(w).startswith("Up next")
    playing(monkeypatch, w, ["s0"])
    w.playctl.queue_sound("s1")
    w.playctl.stop_all()
    assert not said(w).startswith("Up next")


def test_up_next_is_one_chip_whose_list_reaches_every_queued_sound(window, monkeypatch):
    """13 queued: the row used to show five cut-off names and "+8 more", so the 10th
    couldn't be taken out. Now one chip says how many wait; its list has them all,
    whole names, each with its ✕, and Clear."""
    from soundboard.ui.window.upnext import UpNextChip
    from uicheck import assert_breathing_room
    w = window
    w.resize(1200, 760)
    w.show()
    playing(monkeypatch, w, ["s0"])
    w.playctl._queue = ["s1", "s0"] * 6 + ["s1"]
    w.playctl._update_chips(w.engine.playing())
    chip = w._up_next_chip
    assert isinstance(chip, UpNextChip) and chip.count.text() == "13 waiting"
    assert chip.accessibleName() == "Up next 13 waiting"   # what it shows, not its tooltip
    assert w._chips_hl.indexOf(chip) == w._chips_hl.count() - 1   # after Now playing
    chip.click()
    pop = w._up_next_popup
    assert pop.isVisible() and pop.count.text() == "13"
    assert_breathing_room(pop.card)   # 14 px inside the card, 8 px before the scroll bar
    rows = [pop.rows_v.itemAt(i).widget() for i in range(pop.rows_v.count())]
    rows = [r for r in rows if r is not None]
    assert len(rows) == 13
    tenth = rows[9]
    assert tenth.findChildren(QPushButton)[0].toolTip() == "Boom"   # its whole name
    w.playctl.select("s1")
    tenth.findChildren(QPushButton)[-1].click()                    # the 10th's ✕
    assert len(w.playctl._queue) == 12 and w.playctl._queue[9] == "s1"
    assert pop.isVisible() and pop.count.text() == "12"           # refilled in place
    assert w._up_next_chip.count.text() == "12 waiting"
    assert w._up_next_chip.accessibleName() == "Up next 12 waiting"
    pop.clear.click()                                              # Clear: all of them
    assert w.playctl._queue == [] and not pop.isVisible()
    assert w._up_next_chip is None and set(w.engine.playing()) == {"s0"}


def test_up_next_names_fill_the_room_their_row_gives_them(window, monkeypatch):
    """A long name is cut with "…" once, at the width its row really has: it was cut
    to a width worked out ahead, ~50 px short, a gap before its ▶."""
    from soundboard.ui.window.upnext import _Name
    w = window
    w.resize(1200, 760)
    w.show()
    playing(monkeypatch, w, ["s0"])
    w._meta["s1"].name = "Windows XP shutdown (extra crunchy ver.)"
    w.linkbar._up_next = [("Never Gonna Give You Up - Rick Astley (Official Music Video)",
                           None, 1.0, "https://example.com/v")]
    w.playctl._queue = ["s1"]
    w.playctl._update_chips(w.engine.playing())
    w._up_next_chip.click()
    QApplication.processEvents()
    for row in up_next_rows(w):
        name = row.findChild(_Name)
        shown = name.text().replace("&&", "&")
        assert shown.endswith("…") and shown != name.full
        opt = QStyleOptionButton()
        name.initStyleOption(opt)
        room = name.style().subElementRect(QStyle.SubElement.SE_PushButtonContents,
                                           opt, name).width()
        fm = name.fontMetrics()
        assert fm.horizontalAdvance(shown) <= room
        one_more = name.full[:len(shown)] + "…"   # one letter more: wouldn't fit (no gap)
        assert fm.horizontalAdvance(one_more) > room
        assert name.toolTip() == name.full


def test_up_next_list_shrinks_when_sounds_are_taken_out_while_open(window, monkeypatch):
    """Four waiting, three taken out with the list open: it ends as short as a list
    opened with one (the old height stayed as an empty gap over the last row)."""
    w = window
    w.resize(1200, 760)
    w.show()
    playing(monkeypatch, w, ["s0"])
    w.playctl._queue = ["s0", "s1", "s0", "s1"]
    w.playctl._update_chips(w.engine.playing())
    w._up_next_chip.click()
    QApplication.processEvents()
    pop = w._up_next_popup
    for _i in range(3):
        up_next_rows(w)[0].findChildren(QPushButton)[-1].click()
        QApplication.processEvents()
    assert pop.isVisible() and pop.count.text() == "1"
    shrunk = (pop.height(), up_next_rows(w)[0].mapTo(pop, QPoint(0, 0)).y())
    pop.close()
    w._up_next_chip.click()
    QApplication.processEvents()
    assert shrunk == (pop.height(), up_next_rows(w)[0].mapTo(pop, QPoint(0, 0)).y())


def up_next_rows(w):
    pop = w._up_next_popup
    return [r for r in (pop.rows_v.itemAt(i).widget() for i in range(pop.rows_v.count()))
            if r is not None]


def test_an_up_next_rows_play_plays_it_now_and_the_rest_keep_waiting(window, monkeypatch):
    """Ten waiting and you want the 9th now: its ▶ starts it, the others stay in order."""
    w = window
    w.resize(1200, 760)
    w.show()
    played = []
    playing(monkeypatch, w, ["s0"])
    monkeypatch.setattr(w.playctl, "play", lambda sid, now=False: played.append(sid))
    w.playctl._queue = ["s0"] * 8 + ["s1", "s0"]
    w.playctl._update_chips(w.engine.playing())
    w._up_next_chip.click()
    ninth = up_next_rows(w)[8]
    btn = [b for b in ninth.findChildren(QPushButton) if b.toolTip() == "Play it now"][0]
    btn.click()
    btn.click()                               # a double click: the list moved, nothing more
    assert played == ["s1"] and w.playctl._queue == ["s0"] * 9


def test_an_up_next_row_dragged_by_its_grip_moves_in_the_queue(window, monkeypatch):
    from PySide6.QtTest import QTest
    w = window
    w.resize(1200, 760)
    w.show()
    playing(monkeypatch, w, ["s0"])
    w.playctl._queue = ["s0", "s0", "s1"]
    w.playctl._update_chips(w.engine.playing())
    w._up_next_chip.click()
    QApplication.processEvents()
    rows = up_next_rows(w)
    grip = rows[2].findChildren(QLabel)[0]
    assert grip.toolTip() == "Drag to change the order"
    QTest.mousePress(grip, Qt.MouseButton.LeftButton, pos=QPoint(4, 4))
    top = rows[0].mapToGlobal(QPoint(4, 2))
    QTest.mouseMove(grip, grip.mapFromGlobal(top))
    w._up_next_popup._drag_move(top)   # (offscreen: a move without buttons isn't sent)
    assert up_next_rows(w)[0] is rows[2]   # it moved as the mouse went
    QTest.mouseRelease(grip, Qt.MouseButton.LeftButton, pos=grip.mapFromGlobal(top))
    assert w.playctl._queue == ["s1", "s0", "s0"]


def test_a_link_song_moves_and_plays_now_only_among_link_songs(window):
    w = window
    bar = w.linkbar
    bar._up_next = [("A", None, 1.0, "a"), ("B", None, 1.0, "b"), ("C", None, 1.0, "c")]
    assert bar.move_up_next(2, 0, ("A", "B", "C")) and bar.up_next() == ["C", "A", "B"]
    assert not bar.move_up_next(0, 2, ("A", "B", "C"))   # out of date: nothing
    assert not bar.move_up_next(0, 5) and bar.up_next() == ["C", "A", "B"]


def test_a_trigger_deleted_while_its_pad_waits_or_queues_never_starts_it(window, monkeypatch,
                                                                         calls, qapp):
    """A trigger's sound plays like its pad, with the pad's Wait first or Queue; stopping
    the trigger's tag (sound taken off it, trigger deleted) must stop those too."""
    from conftest import process_events
    from soundboard.ui.triggers.triggershost import BoardHost
    w = window
    host = BoardHost(w)
    w.meta("s0").delay = 0.05
    assert host.play("s0", tag="t1/s0")
    assert "s0" in w.playctl._waiting
    host.stop_tag("t1/s0")
    assert not w.playctl._waiting
    process_events(qapp, lambda: False, 0.2)
    assert calls == []
    w.meta("s1").mode = "queue"
    playing(monkeypatch, w, ["s0"])
    w.playctl.queue_sound("s0")               # queued by hand: stays
    assert host.play("s1", tag="t2/s1")
    assert w.playctl._queue == ["s0", "s1"]
    host.stop_tag("t2/s1")
    assert w.playctl._queue == ["s0"]


def menu_pick(monkeypatch, path):
    """Make the pad menu pick the action at `path` (texts, through submenus); returns
    the top-level menu's texts as it was shown."""
    from PySide6.QtWidgets import QMenu
    from soundboard.ui.window import mainwindow, padcontrol
    shown = []

    class Menu(QMenu):
        def exec(self, *_a):
            shown.extend(a.text() or "---" for a in self.actions())
            acts = self.actions()
            for text in path:
                a = next(a for a in acts if a.text() == text)
                acts = a.menu().actions() if a.menu() else acts
            return a
    monkeypatch.setattr(mainwindow, "QMenu", Menu)
    monkeypatch.setattr(padcontrol, "QMenu", Menu)
    return shown


def test_pad_menu_is_short_grouped_and_shows_the_hotkey(window, monkeypatch):
    w = window
    shown = menu_pick(monkeypatch, ["Set hotkey"])
    from soundboard.ui.settings.settings import HotkeyDialog
    monkeypatch.setattr(HotkeyDialog, "exec",
                        lambda self: setattr(self, "result_combo", "ctrl+alt+7") or True)
    w.padctl.pad_menu("s0", None)
    assert shown == ["Play next", "Volume", "---", "Edit", "Rename",
                     "Set hotkey", "Categories", "---", "Duplicate",
                     "Export", "Open file location", "Remove"]
    assert w.meta("s0").hotkey == "ctrl+alt+7"
    shown = menu_pick(monkeypatch, ["Hotkey: Ctrl+Alt+7", "Remove hotkey"])
    w.padctl.pad_menu("s0", None)
    assert "Hotkey: Ctrl+Alt+7" in shown and "Set hotkey" not in shown
    assert w.meta("s0").hotkey == ""


def test_pad_menu_has_the_sites_entries_only_for_downloads(window, monkeypatch):
    """A sound from YouTube (TikTok, SoundCloud) gets Open on YouTube, Copy link and
    Details under the site's name; any other sound doesn't."""
    LINK = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    from soundboard.ui.kit import busy
    from soundboard.ui.sounds import sourcedialog
    w = window
    shown = menu_pick(monkeypatch, ["Duplicate"])
    monkeypatch.setattr(w.editctl, "duplicate_sound", lambda sid: None)
    w.padctl.pad_menu("s0", None)
    assert "YouTube" not in shown
    w.meta("s0").source = {"site": "youtube", "link": LINK}
    opened = []
    monkeypatch.setattr(busy, "open_url", lambda url, **kw: opened.append(url) or True)
    shown = menu_pick(monkeypatch, ["YouTube", "Open on YouTube"])
    w.padctl.pad_menu("s0", None)
    assert shown.index("YouTube") == shown.index("Export") + 1 and opened == [LINK]
    menu_pick(monkeypatch, ["YouTube", "Copy link"])
    w.padctl.pad_menu("s0", None)
    from PySide6.QtWidgets import QApplication
    assert QApplication.clipboard().text() == LINK
    dialogs = []
    monkeypatch.setattr(sourcedialog.SourceDialog, "show",
                        lambda self: dialogs.append(self))
    from soundboard.online import quality
    monkeypatch.setattr(quality, "current", quality.Prefs(keep_source=False))
    shown = menu_pick(monkeypatch, ["Duplicate"])
    w.padctl.pad_menu("s0", None)
    assert "YouTube" not in shown and w.meta("s0").source   # hidden, still kept
    monkeypatch.setattr(quality, "current", quality.Prefs())
    menu_pick(monkeypatch, ["YouTube", "Details"])
    w.padctl.pad_menu("s0", None)
    [d] = dialogs
    assert d.btn_open.text() == "Open on YouTube" and d.btn_open.toolTip() == LINK
    d.close()


def test_a_key_taken_from_another_sound_or_action_says_so(window):
    w = window
    w.cfg.stop_hotkey = "ctrl+alt+s"
    w.meta("s1").hotkey = "f2"
    w.hkctl.set_sound_hotkey("s0", "f2")
    assert w.meta("s1").hotkey == "" and "it was the key for “Airhorn”" in said(w)
    w.hkctl.set_sound_hotkey("s0", "ctrl+alt+s")   # the Stop everything key stays on that
    assert w.cfg.stop_hotkey == "ctrl+alt+s" and w.meta("s0").hotkey == "f2"
    assert "Stop everything key" in said(w)
    unsay(w)
    w.hkctl.set_sound_hotkey("s1", "f9")         # a free key: just the green card, no warning
    [t] = toast.shown(w)
    assert t.kind == "ok" and "F9 plays" in t.text()


def test_a_global_hotkey_taken_off_a_sound_is_said_out_loud(window, monkeypatch):
    """Settings → Hotkeys: giving Stop everything a key a pad had takes it off the
    pad (a combo does one thing) and a warn toast names what lost it."""
    from soundboard.ui.kit import busy
    toasts = []
    monkeypatch.setattr(busy, "toast", lambda win, text, kind="", ms=0: toasts.append((text, kind)))
    w = window
    w.meta("s0").hotkey = "f1"
    w.cfg.category_hotkeys["All"] = "f1"
    w.hkctl.set_global_hotkey("stop_hotkey", "f1")
    assert w.meta("s0").hotkey == ""
    assert "All" not in w.cfg.category_hotkeys
    assert w.cfg.stop_hotkey == "f1"
    text, kind = toasts[-1]
    assert kind == "warn" and "Boom" in text and "Stop everything" in text and "All" in text
    toasts.clear()
    w.hkctl.set_global_hotkey("pause_hotkey", "f2")   # nothing had F2: no warning
    assert not [t for t in toasts if t[1] == "warn"]


def test_pad_keys_rename_edit_delete_and_find(window, monkeypatch, qapp):
    """F2 renames the pad the keyboard is on, Alt+Enter opens Edit, Delete removes it
    (nothing picked), Ctrl+F lands in the search box."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QInputDialog
    w = window
    w.show()
    w.tabs.setCurrentWidget(w.sounds_page)
    pad = w.pads["s0"]
    pad.setFocus()
    qapp.processEvents()   # the tab shown: a shortcut on a hidden widget doesn't fire
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Big boom", True)))
    QTest.keyClick(pad, Qt.Key_F2)
    assert w.meta("s0").name == "Big boom" and pad.meta.name == "Big boom"
    edited = []
    pad.edit.disconnect()   # (wired to the real Edit sound when the pad was made)
    pad.edit.connect(edited.append)
    QTest.keyClick(pad, Qt.Key_Return, Qt.AltModifier)
    assert edited == ["s0"]
    asked = []
    monkeypatch.setattr(w.rmctl, "ask_remove", lambda sids: asked.append(list(sids)) or False)
    QTest.keyClick(pad, Qt.Key_Delete)
    assert asked == [["s0"]]
    QTest.keyClick(pad, Qt.Key_F, Qt.ControlModifier)
    assert qapp.focusWidget() is w.search


def test_duplicate_and_show_file(window, monkeypatch):
    """Duplicate adds a copy right after the original, with its own file and no
    hotkey; Show the file opens Explorer on it (and says so if the file is gone)."""
    import subprocess
    from pathlib import Path
    w = window
    w.meta("s0").hotkey = "f1"
    new = w.editctl.duplicate_sound("s0")
    assert new is not None and new.id in w.pads
    assert [m.id for m in w.cfg.sounds][:2] == ["s0", new.id]
    assert new.name == "Boom (copy)" and new.hotkey == "" and new.file != w.meta("s0").file
    assert Path(new.file).is_file()
    runs = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, **k: runs.append(args))
    from soundboard.ui.window import mainwindow as mwmod
    monkeypatch.setattr(mwmod.sys, "platform", "win32")
    w.editctl.show_sound_file("s0")
    assert runs and runs[-1][0] == "explorer" and runs[-1][-1] == w.meta("s0").file
    toasts = []
    from soundboard.ui.kit import busy
    monkeypatch.setattr(busy, "toast", lambda win, text, kind="", ms=0: toasts.append(kind))
    w.meta("s0").file = str(Path(w.meta("s0").file).with_name("gone.wav"))
    w.editctl.show_sound_file("s0")
    assert toasts[-1] == "warn" and len(runs) == 1


def test_transport_time_is_blank_until_a_sound_is_picked(window):
    w = window
    assert w.np_time.text() == "" and w.mini_time.text() == ""
    assert w.np_time.isHidden()   # blank: the seek line takes its room
    w.playctl.select("s0")
    w.transctl._update_transport({})   # the player's timer tick
    assert w.np_time.text() and not w.np_time.isHidden()
    w.rmctl.remove_sound("s0")   # back to "Pick a sound"
    assert w.np_time.text() == "" and w.np_time.isHidden()


def test_hotkeys_let_the_game_have_the_key_unless_turned_off(window, monkeypatch):
    """Settings → Hotkeys → Keys in games: on by default, the game still gets a hotkey's
    key (F1 does the game's F1 too). The overlay's keys are always taken while it's up."""
    from PySide6.QtWidgets import QCheckBox

    from soundboard.ui.settings.settings import SettingsDialog
    w = window
    seen = []
    monkeypatch.setattr(w.hotkeys, "register",
                        lambda m: seen.append((dict(m), w.hotkeys.share, set(w.hotkeys.grab))))
    assert Config().hotkeys_share is True
    w.meta("s0").hotkey = "w"
    w.hkctl.register_hotkeys()
    mapping, share, grab = seen[-1]
    assert mapping["w"] == "s0" and share and not grab
    monkeypatch.setattr(w.overlay, "is_open", True)
    w.hkctl.register_hotkeys()
    mapping, share, grab = seen[-1]
    assert share and grab and grab == set(w.overlay.layer()) and "w" not in grab
    monkeypatch.setattr(w.overlay, "is_open", False)
    d = SettingsDialog(w, "hotkeys")
    box = next(b for b in d.findChildren(QCheckBox) if b.text() == "Games get the key too")
    assert box.isChecked()
    box.click()
    assert w.cfg.hotkeys_share is False and seen[-1][1] is False
    d.close()


def test_the_hotkey_box_warns_about_a_bare_letter_only_when_games_lose_it(window, monkeypatch):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication

    from soundboard.ui.settings.settings import HotkeyDialog
    w = window
    monkeypatch.setattr(w.hotkeys, "register", lambda m: None)

    def press_w(d):
        QApplication.sendEvent(d, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_W,
                                            Qt.KeyboardModifier.NoModifier, 0x11, 0x57, 0))

    w.hotkeys.share = True                    # the game still gets W: nothing to warn about
    d = HotkeyDialog(w.hotkeys, pads=False)
    press_w(d)
    assert d.result_combo == "w"
    w.hotkeys.share = False                   # W would be taken from the game and from typing
    d = HotkeyDialog(w.hotkeys, pads=False)
    press_w(d)
    assert d.result_combo is None and "games" in d.hint.text()
    press_w(d)                                # again: use it anyway
    assert d.result_combo == "w"


def test_switching_tab_lets_go_of_a_picked_sound_that_isnt_playing(window, monkeypatch, calls):
    w = window
    w.catctl.new_category(name="Memes")
    w.catctl.set_category("")
    w.playctl.select("s0")                  # clicked, not played
    w.catctl.set_category("Memes")          # an empty tab
    assert w.current is None and not w.pads["s0"].selected
    w.playctl.toggle_play_pause()           # what Space does on Sounds: nothing to play
    assert calls == []
    w.playctl.select("s1")
    monkeypatch.setattr(w.engine, "state", lambda sid: (0.5, False) if sid == "s1" else None)
    w.catctl.set_category("")               # playing: stays, so Space still pauses it
    assert w.current == "s1"


def test_live_controls_save_as_new_pad(window, monkeypatch):
    """Live controls' Save as new pad: a copy of the sound played last, right after it,
    named “Boom (modified)” (then “(modified 2)”), with the live speed, pitch and
    effects saved onto it; nothing played or nothing changed only says so."""
    w = window
    sp = w.speed_btn
    asked = []
    monkeypatch.setattr(w.editctl, "_ask_pad_name", lambda d: asked.append(d) or d)
    toasts = []
    monkeypatch.setattr(w, "toast", lambda text, kind="", **k: toasts.append(kind))
    assert w.editctl.save_live_copy() is None and toasts[-1] == "warn"   # nothing played
    w.playctl._last_sid = "s0"
    assert w.editctl.save_live_copy() is None and toasts[-1] == "warn"   # nothing changed
    assert not asked
    sp.set_values(1.3, 5, True)
    sp.set_fx({"bass": 8, "reverb": 0.3})
    sp.save_btn.click()
    new = w.cfg.sounds[1]
    assert asked == ["Boom (modified)"] and new.name == "Boom (modified)"
    assert [m.id for m in w.cfg.sounds][0] == "s0" and new.id in w.pads
    assert new.fx["speed"] == 1.3 and new.fx["pitch"] == 5 and not new.fx["tape"]
    assert new.fx["live"] == [{"bass": 8.0, "reverb": 0.3}]
    assert w.meta("s0").fx == {} and sp.values() == (1.3, 5, True)   # both stay as they were
    w.editctl.save_live_copy()
    assert asked[-1] == "Boom (modified 2)"
    monkeypatch.setattr(w.editctl, "_ask_pad_name", lambda d: None)   # Cancel
    n = len(w.cfg.sounds)
    assert w.editctl.save_live_copy() is None and len(w.cfg.sounds) == n


def test_live_save_button_only_where_there_is_a_pad(qapp):
    from soundboard.ui.sounds.speedpitch import SpeedPitchButton
    for what, has in (("sounds", True), ("radio", False), ("apps", False)):
        b = SpeedPitchButton(what)
        assert hasattr(b, "save_btn") == has
        b.deleteLater()
