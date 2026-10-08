"""Hotkeys and per-sound options other soundboards are asked for: replay the last sound,
switch category, louder / quieter, mic and voice changer keys, all hotkeys off, a set
of hotkeys per category, a sound's queue / wait / cooldown / "only others hear it",
playing a whole category and one-click pads."""
import pytest

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent

from soundboard import backup
from soundboard.library import Config, SoundMeta
from soundboard.ui.widgets import Pad
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
    w.on_hotkey("__last__")            # nothing yet: just the fail beep
    assert calls == []
    w.play("s1")
    w.on_hotkey("__last__")
    assert [c[0] for c in calls] == ["s1", "s1"]


def test_category_keys_cycle_through_all_and_the_categories(window):
    w = window
    w.new_category(name="Memes")
    w.new_category(name="Music")
    w.set_category("")
    w.on_hotkey("__nextcat__")
    assert w.cfg.category == "Memes"
    w.on_hotkey("__nextcat__")
    w.on_hotkey("__nextcat__")
    assert w.cfg.category == ""        # wraps round to All
    w.on_hotkey("__prevcat__")
    assert w.cfg.category == "Music"


def test_volume_keys_step_the_sounds_volume_by_ten(window):
    w = window
    w.vol_sound.spin.setValue(95)
    w.on_hotkey("__volup__")
    assert w.cfg.sound_vol == pytest.approx(1.1)
    w.vol_sound.spin.setValue(0)
    w.on_hotkey("__voldown__")
    assert w.cfg.sound_vol == 0.0


def test_mic_and_voice_changer_keys(window):
    w = window
    was = w.cfg.mic_enabled
    w.on_hotkey("__mic__")
    assert w.cfg.mic_enabled is (not was)
    power = w.voice.fx.btn_power
    assert not power.isChecked()
    w.on_hotkey("__voice__")
    assert power.isChecked()
    w.on_hotkey("__voice__")
    assert not power.isChecked()
    w.on_hotkey("__voicehold__")      # on while held, back as it was when let go
    assert power.isChecked()
    w.on_hotkey_released("__voicehold__")
    assert not power.isChecked()


def test_all_hotkeys_off_leaves_only_its_own_key(window, monkeypatch, calls):
    w = window
    registered = []
    monkeypatch.setattr(w.hotkeys, "register", lambda m: registered.append(dict(m)))
    w.meta("s0").hotkey = "f1"
    w.set_global_hotkey("hotkeys_off_hotkey", "f12")
    assert registered[-1]["f1"] == "s0"
    w.on_hotkey("__hotkeys__")
    assert registered[-1] == {"f12": "__hotkeys__"}
    w.on_hotkey("s0")                 # one already queued when they went off
    assert calls == []
    w.on_hotkey("__hotkeys__")
    assert registered[-1]["f1"] == "s0"


def test_a_set_of_hotkeys_per_category(window, monkeypatch, calls):
    w = window
    registered = []
    monkeypatch.setattr(w.hotkeys, "register", lambda m: registered.append(dict(m)))
    w.new_category(name="Memes")
    w.new_category(name="Music")
    a, b = w.meta("s0"), w.meta("s1")
    a.tags, b.tags = ["Memes"], ["Music"]
    w.set_scoped_hotkeys(True)
    a.hotkey = "f1"
    w._clear_dupe_hotkey(a)
    b.hotkey = "f1"
    w._clear_dupe_hotkey(b)           # no category in common: both keep it
    assert a.hotkey == b.hotkey == "f1"
    w.set_category("Memes")
    assert registered[-1]["f1"] == "s0"
    w.set_category("Music")
    assert registered[-1]["f1"] == "s1"
    w.set_scoped_hotkeys(False)       # one key, one sound again: the first keeps it
    assert (a.hotkey, b.hotkey) == ("f1", "")


def test_queue_sound_waits_for_the_one_playing(window, monkeypatch, calls):
    w = window
    w.meta("s1").mode = "queue"
    playing(monkeypatch, w, ["s0"])
    w.play("s1")
    assert calls == [] and w._queue == ["s1"]
    playing(monkeypatch, w, [])
    w.tick()
    assert [c[0] for c in calls] == ["s1"] and calls[0][1]["mode"] == "restart"
    assert w._queue == []


def test_play_next_and_stop_everything_clears_the_queue(window, monkeypatch, calls):
    w = window
    playing(monkeypatch, w, ["s0"])
    w.queue_sound("s1")
    assert w._queue == ["s1"]
    w.stop_all()
    assert w._queue == []


def test_play_a_whole_category_one_after_another(window, monkeypatch, calls):
    w = window
    w.new_category(name="Memes")
    for sid in ("s0", "s1"):
        w.meta(sid).tags = ["Memes"]
    monkeypatch.setattr(w.engine, "stop", lambda sid: None)
    playing(monkeypatch, w, [])
    w.queue_category("Memes", shuffled=False)
    assert [c[0] for c in calls] == ["s0"] and w._queue == ["s1"]
    w.tick()
    assert [c[0] for c in calls] == ["s0", "s1"]


def test_cooldown_ignores_spam(window, calls):
    w = window
    w.meta("s0").cooldown = 30.0
    w.play("s0")
    w.play("s0")
    assert len(calls) == 1
    w._cool.clear()
    w.play("s0")
    assert len(calls) == 2


def test_wait_before_playing_and_stop_cancels_it(window, calls, qapp):
    from conftest import process_events
    w = window
    w.meta("s0").delay = 0.05
    w.play("s0")
    assert calls == [] and "s0" in w._waiting
    process_events(qapp, lambda: calls)
    assert [c[0] for c in calls] == ["s0"]
    w.play("s0")
    w.stop_all()
    assert w._waiting == {}


def test_only_them_skips_my_headphones(window, calls):
    w = window
    w.meta("s0").only_them = True
    w.play("s0")
    w.play("s1")
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
    monkeypatch.setattr(w, "play", played.append)
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
    monkeypatch.setattr(w, "play", played.append)
    pad = w.pads["s0"]

    def click():
        pos = QPointF(5, 5)
        for kind in (QMouseEvent.MouseButtonPress, QMouseEvent.MouseButtonRelease):
            ev = QMouseEvent(kind, pos, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
            (pad.mousePressEvent if kind == QMouseEvent.MouseButtonPress
             else pad.mouseReleaseEvent)(ev)
    try:
        click()
        assert played == []           # the default: a click only selects it
        w.set_single_click(True)
        click()
        assert played == ["s0"]
    finally:
        Pad.single_click = False


def test_the_queue_shows_above_the_pads_and_can_be_trimmed(window, monkeypatch, calls):
    w = window
    w._ui_live = True
    playing(monkeypatch, w, ["s0"])
    w.queue_sound("s1")
    w._update_chips({"s0": (0.5, False)})
    assert not w.playing_row.isHidden()
    w._unqueue(0)
    w._update_chips({"s0": (0.5, False)})
    assert w._queue == [] and w.playing_row.isHidden()


def test_the_queue_status_goes_once_the_queue_is_empty(window, monkeypatch, calls):
    w = window
    playing(monkeypatch, w, ["s0"])
    w.queue_sound("s1")
    w.queue_sound("s0")
    assert w.status.text().startswith("Up next: “Airhorn” (+1 more)")
    w._unqueue(0)                     # the ✕ on Airhorn's chip
    assert w.status.text().startswith("Up next: “Boom”")
    playing(monkeypatch, w, [])
    w.tick()                          # the last one starts: nothing is up next
    assert w._queue == [] and not w.status.text().startswith("Up next")
    playing(monkeypatch, w, ["s0"])
    w.queue_sound("s1")
    w.stop_all()
    assert not w.status.text().startswith("Up next")


def test_a_trigger_deleted_while_its_pad_waits_or_queues_never_starts_it(window, monkeypatch,
                                                                         calls, qapp):
    """A trigger's sound plays like its pad, with the pad's Wait first or Queue; stopping
    the trigger's tag (sound taken off it, trigger deleted) must stop those too."""
    from conftest import process_events
    from soundboard.ui.triggershost import BoardHost
    w = window
    host = BoardHost(w)
    w.meta("s0").delay = 0.05
    assert host.play("s0", tag="t1/s0")
    assert "s0" in w._waiting
    host.stop_tag("t1/s0")
    assert not w._waiting
    process_events(qapp, lambda: False, 0.2)
    assert calls == []
    w.meta("s1").mode = "queue"
    playing(monkeypatch, w, ["s0"])
    w.queue_sound("s0")               # queued by hand: stays
    assert host.play("s1", tag="t2/s1")
    assert w._queue == ["s0", "s1"]
    host.stop_tag("t2/s1")
    assert w._queue == ["s0"]


def menu_pick(monkeypatch, path):
    """Make the pad menu pick the action at `path` (texts, through submenus); returns
    the top-level menu's texts as it was shown."""
    from PySide6.QtWidgets import QMenu
    from soundboard.ui import mainwindow
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
    return shown


def test_pad_menu_is_short_grouped_and_shows_the_hotkey(window, monkeypatch):
    w = window
    shown = menu_pick(monkeypatch, ["Set hotkey…"])
    from soundboard.ui import mainwindow
    monkeypatch.setattr(mainwindow.HotkeyDialog, "exec",
                        lambda self: setattr(self, "result_combo", "ctrl+alt+7") or True)
    w.pad_menu("s0", None)
    assert shown == ["Play next", "---", "Edit…", "Effects…", "Set hotkey…",
                     "Categories", "Add picture…", "---", "Export…", "Remove"]
    assert w.meta("s0").hotkey == "ctrl+alt+7"
    shown = menu_pick(monkeypatch, ["Hotkey: Ctrl+Alt+7", "Remove hotkey"])
    w.pad_menu("s0", None)
    assert "Hotkey: Ctrl+Alt+7" in shown and "Set hotkey…" not in shown
    assert w.meta("s0").hotkey == ""


def test_a_key_taken_from_another_sound_or_action_says_so(window):
    w = window
    w.cfg.stop_hotkey = "ctrl+alt+s"
    w.meta("s1").hotkey = "f2"
    w.set_sound_hotkey("s0", "f2")
    assert w.meta("s1").hotkey == "" and "it was the key for “Airhorn”" in w.status.text()
    w.set_sound_hotkey("s0", "ctrl+alt+s")
    assert w.cfg.stop_hotkey == "" and "Stop everything" in w.status.text()
    w.status.setText("")
    w.set_sound_hotkey("s1", "f9")         # a free key: nothing to say
    assert w.status.text() == ""


def test_a_global_hotkey_taken_off_a_sound_is_said_out_loud(window, monkeypatch):
    """Settings → Hotkeys: giving Stop everything a key a pad had takes it off the
    pad (a combo does one thing) and a warn toast names what lost it."""
    from soundboard.ui import busy
    toasts = []
    monkeypatch.setattr(busy, "toast", lambda win, text, kind="", ms=0: toasts.append((text, kind)))
    w = window
    w.meta("s0").hotkey = "f1"
    w.cfg.category_hotkeys["All"] = "f1"
    w.set_global_hotkey("stop_hotkey", "f1")
    assert w.meta("s0").hotkey == ""
    assert "All" not in w.cfg.category_hotkeys
    assert w.cfg.stop_hotkey == "f1"
    text, kind = toasts[-1]
    assert kind == "warn" and "Boom" in text and "Stop everything" in text and "All" in text
    toasts.clear()
    w.set_global_hotkey("pause_hotkey", "f2")   # nothing had F2: no warning
    assert not [t for t in toasts if t[1] == "warn"]
