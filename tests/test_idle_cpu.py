"""The window's background work stays cheap: polls whose answer nobody uses are
skipped or slowed down, and animations stop while nobody can see them."""
import threading
import time


from conftest import process_events
from soundboard import appaudio
from test_mainwindow import window  # noqa: F401 - the real window, offscreen


def test_windows_default_output_is_only_asked_while_followed(window, monkeypatch, qapp):  # noqa: F811
    asked = []
    monkeypatch.setattr(appaudio, "default_output_name",
                        lambda: asked.append(threading.current_thread())
                        or "Speakers (Realtek Audio)")
    followed = []
    monkeypatch.setattr(window.devctl, "_follow_default_output", lambda *a: followed.append(a))

    def tick():
        window.devctl._default_tick()
        process_events(qapp, lambda: not window.devctl._default_asking, timeout=5)
    window._default_timer.stop()
    window.cfg.mon_follows_default = False
    tick()
    assert not asked                                  # a device picked by hand: not used
    window.cfg.mon_follows_default = True
    window._ui_live = True
    tick()
    tick()
    assert len(asked) == 2                            # on screen: every tick
    assert threading.main_thread() not in asked       # asked on a thread, not the UI's
    assert followed == [("Speakers (Realtek Audio)",)] * 2   # the answer back on the UI's
    window._ui_live = False
    tick()
    assert len(asked) == 2                            # in the tray: every few seconds
    window.devctl._default_at -= 10
    tick()
    assert len(asked) == 3
    # one thread kept for it: a new one each tick kept the window waiting in
    # Thread.start (2.0.4's freezes at mainwindow.py:2848)
    assert len(set(asked)) == 1


def test_a_slow_default_output_answer_isnt_asked_twice(window, monkeypatch, qapp):  # noqa: F811
    go, asked = threading.Event(), []
    monkeypatch.setattr(appaudio, "default_output_name",
                        lambda: asked.append(1) or go.wait(5) and None)
    window._default_timer.stop()
    window.cfg.mon_follows_default = True
    window._ui_live = True
    window.devctl._default_tick()
    window.devctl._default_tick()                            # the first is still asking
    go.set()
    process_events(qapp, lambda: not window.devctl._default_asking, timeout=5)
    assert len(asked) == 1


def recover(w, qapp):
    """One device check, and its answer (it asks Windows on the device thread)."""
    w.devctl._recover_devices()
    process_events(qapp, lambda: not w.engine.devices.busy, timeout=5)


def test_an_unplugged_device_is_looked_for_less_often(window, monkeypatch, qapp):  # noqa: F811
    e = window.engine
    monkeypatch.setitem(e.names, "mic", "Microphone (USB Mic)")
    monkeypatch.setitem(e.errors, "mic", "device not found")
    e.mic_stream = None
    looks = []
    monkeypatch.setattr(appaudio, "endpoint_names", lambda kind: looks.append(kind) or set())
    for _ in range(10):
        recover(window, qapp)
    assert len(looks) == 4                            # a few quick looks, then it waits
    window.devctl._recover_at = 0.0
    recover(window, qapp)
    assert len(looks) == 5


def test_whos_listening_poll_slows_down_while_hidden(window, monkeypatch):  # noqa: F811
    polls = []
    monkeypatch.setattr(window, "_poll_voice", lambda: polls.append(1))
    window.cfg.dest = {"mode": "off", "auto": False}
    window._ui_live = True
    window._voice_tick()
    window._voice_tick()
    assert len(polls) == 2
    window._ui_live = False
    window._voice_tick()
    assert len(polls) == 2                            # nobody sees the hint
    window.cfg.dest = {"mode": "off", "auto": True}
    window._voice_tick()
    assert len(polls) == 3                            # it switches by itself: keeps up


def test_mic_check_pulse_runs_only_while_shown_in_front(window, monkeypatch, qapp):  # noqa: F811
    """The banner's throb draws the whole banner again on each step: not in the tray,
    minimised or behind a game (there it stands still, fully bright)."""
    from PySide6.QtCore import Qt
    from soundboard.ui import mainwindow as main
    monkeypatch.setattr(main.appstate, "active", lambda: True)
    window._ui_live = True
    window.on_mic_check(True)
    window._set_tick_rate()                           # not shown (offscreen): not live
    assert not window._pulse.running()
    assert window._banner_fx.opacity() == 1.0 and not window._banner_fx.isEnabled()
    window.show()
    assert window._pulse.running() and window._banner_fx.isEnabled()
    monkeypatch.setattr(main.appstate, "active", lambda: False)
    qapp.applicationStateChanged.emit(Qt.ApplicationInactive)    # a game in front
    assert not window._pulse.running() and window._banner_fx.opacity() == 1.0
    monkeypatch.setattr(main.appstate, "active", lambda: True)
    qapp.applicationStateChanged.emit(Qt.ApplicationActive)      # back in front
    assert window._pulse.running()
    window.hide()
    assert not window._pulse.running()
    window.on_mic_check(False)
    window.show()
    assert not window._pulse.running()                # off: shown again, still off
    window.hide()


def test_mic_check_pulse_steps_about_16_times_a_second_along_the_same_curve(window):  # noqa: F811
    from soundboard.ui import mainwindow as main
    pulse = window._pulse
    assert 1000 / pulse.timer.interval() <= 20        # the animation ran at 60
    assert pulse.opacity_at(0) == 1.0
    assert abs(pulse.opacity_at(main.PULSE_MS / 2) - main.PULSE_LOW) < 1e-9
    assert abs(pulse.opacity_at(main.PULSE_MS / 4) - (1 + main.PULSE_LOW) / 2) < 1e-9
    assert pulse.opacity_at(main.PULSE_MS) == 1.0     # and round again


def test_ui_tick_goes_over_only_the_pads_showing_a_sound(window, monkeypatch):  # noqa: F811
    """Nothing playing: no pad is looked at (all of them, 30 times a second, cost more
    than the rest of the tick on a big board). One that stops is cleared on the next
    tick, then left alone."""
    looked = []

    class Pads(dict):
        def get(self, sid, default=None):
            looked.append(sid)
            return super().get(sid, default)
    monkeypatch.setattr(window, "pads", Pads(window.pads))
    pad = window.pads["s0"]
    now = time.monotonic()
    window._tick_visuals({}, now)
    assert looked == []
    window._tick_visuals({"s0": (0.25, False)}, now)
    assert pad.progress == 0.25 and looked == ["s0"]
    window._tick_visuals({"s0": (0.5, True)}, now)    # paused: still shown
    assert pad.progress == 0.5 and pad.paused
    looked.clear()
    window._tick_visuals({}, now)                     # it stopped
    assert looked == ["s0"] and pad.progress is None and pad.bands is None
    looked.clear()
    window._tick_visuals({}, now)
    assert looked == []


def test_the_ui_tick_slows_down_while_nothing_moves(window, monkeypatch, qapp):  # noqa: F811
    from soundboard.ui import mainwindow as main
    assert process_events(qapp, lambda: "s0" in window.audio)
    e = window.engine
    playing = {}
    monkeypatch.setattr(e, "playing", lambda: dict(playing))
    monkeypatch.setattr(main.appstate, "active", lambda: True)   # the app is in front
    monkeypatch.setattr(window, "isVisible", lambda: True)
    window._ui_live = True
    e.level_play = e.level_main = e.level_mic = 0.0
    window.tick()
    assert window.timer.interval() == main.TICK_QUIET_MS    # 10 a second, not 30
    window.play("s0")                                       # back to full pace at once
    assert window.timer.interval() == main.TICK_MS
    playing["s0"] = (0.5, True)                             # paused: nothing moves
    e.level_play = e.level_main = 0.0
    window._tick_busy = False
    window.tick()
    assert window.timer.interval() == main.TICK_QUIET_MS
    playing["s0"] = (0.5, False)
    window.tick()
    assert window.timer.interval() == main.TICK_MS
    playing.clear()
    e.level_main = 0.5                                      # a meter still falling
    window.tick()
    assert window.timer.interval() == main.TICK_MS
    for _ in range(80):                                     # ...until it shows nothing
        window.tick()
    assert window.timer.interval() == main.TICK_QUIET_MS


def test_unfocused_playback_keeps_visible_meters_at_full_pace(window, monkeypatch, qapp):  # noqa: F811
    from PySide6.QtCore import Qt
    from soundboard.ui import mainwindow as main

    monkeypatch.setattr(window, "isVisible", lambda: True)
    monkeypatch.setattr(window, "isMinimized", lambda: False)
    monkeypatch.setattr(main.appstate, "active", lambda: True)
    window._ui_live = True
    window._tick_busy = True
    window._set_tick_rate()
    assert window.timer.interval() == main.TICK_MS

    monkeypatch.setattr(main.appstate, "active", lambda: False)
    qapp.applicationStateChanged.emit(Qt.ApplicationInactive)
    assert window.timer.interval() == main.TICK_MS
    window._tick_busy = False
    window._wake()  # playback starts while the game already has focus
    assert window.timer.interval() == main.TICK_MS

    window._tick_busy = False
    window._set_tick_rate()
    assert window.timer.interval() == main.TICK_QUIET_MS
    monkeypatch.setattr(window, "isMinimized", lambda: True)
    window._tick_busy = True
    window._set_tick_rate()
    assert window.timer.interval() == main.TICK_IDLE_MS


def test_waiting_queues_do_not_keep_paused_playback_busy(window, monkeypatch):  # noqa: F811
    from soundboard.ui import mainwindow as main

    playing = {"s0": (0.5, True)}
    monkeypatch.setattr(window.engine, "playing", lambda: dict(playing))
    monkeypatch.setattr(window.radio, "is_active", lambda: False)
    monkeypatch.setattr(window.linkbar, "up_next", lambda: ["https://example.com/song"])
    monkeypatch.setattr(main.appstate, "active", lambda: True)
    window._queue[:] = ["s1"]
    window.engine.level_play = window.engine.level_main = window.engine.level_mic = 0.0
    monkeypatch.setattr(window.engine, "aux", ())
    window._ui_live = True
    window.tick()
    assert not window._tick_busy
    assert window.timer.interval() == main.TICK_QUIET_MS
    assert window._queue == ["s1"]

    window._ui_live = False
    window.tick()
    assert window.timer.interval() == main.TICK_IDLE_MS
    playing["s0"] = (0.5, False)
    window._ui_live = True
    window.tick()
    assert window._tick_busy
    assert window.timer.interval() == main.TICK_MS

    advanced = []
    monkeypatch.setattr(window, "_next_in_queue", lambda: advanced.append(True))
    monkeypatch.setattr(window.linkbar, "play_next", lambda: False)
    playing.clear()
    window.tick()
    assert advanced == [True]
    assert not window._tick_busy


def test_what_others_hear_shows_your_voice_before_the_mic_effect(window, monkeypatch):  # noqa: F811
    e = window.engine
    monkeypatch.setattr(window, "isVisible", lambda: True)
    monkeypatch.setattr(e, "mic_stream", object())
    e.level_main, e.level_mic = 0.0, 0.6
    window.cfg.route, e.main_direct = "mic", False   # into the mic, effect not set up:
    window._tick_visuals({}, 0.0)                    # apps take the real mic as it is
    assert window.out_meter.level == 0.6
    e.main_direct = True                             # in the mic: only what's sent
    window._tick_visuals({}, 0.0)
    assert window.out_meter.level == 0.0
    window.cfg.route, e.main_direct = "cable", False
    window._tick_visuals({}, 0.0)
    assert window.out_meter.level == 0.0


def test_unticking_others_hear_it_warns_when_the_mic_effect_isnt_on(window, monkeypatch):  # noqa: F811
    from PySide6.QtWidgets import QMessageBox

    from soundboard.ui import mainwindow as main
    shown, attached = [], []
    monkeypatch.setattr(QMessageBox, "exec", lambda box: shown.append(box.text()))
    monkeypatch.setattr(window.micctl, "attach_mic", lambda *a, **k: attached.append(1))
    works = [False]
    monkeypatch.setattr(main.directmic, "works", lambda _s: works[0])
    window.cfg.route = "mic"
    window.routectl._warn_mute_does_nothing(True)             # ticked back on: nothing to say
    assert shown == []
    window.routectl._warn_mute_does_nothing(False)            # unticked, effect not on the mic
    assert len(shown) == 1 and attached == []        # closed: nothing set up
    works[0] = True                                  # on the mic: the box really mutes
    window.routectl._warn_mute_does_nothing(False)
    window.cfg.route, works[0] = "cable", False      # the cable: it mutes there too
    window.routectl._warn_mute_does_nothing(False)
    assert len(shown) == 1


def test_mute_warning_can_be_turned_off_for_good(window, monkeypatch):  # noqa: F811
    from PySide6.QtWidgets import QMessageBox

    from soundboard.ui import mainwindow as main
    shown = []

    def answer(box):
        shown.append(box.text())
        box.checkBox().setChecked(True)              # Don't show this again
    monkeypatch.setattr(QMessageBox, "exec", answer)
    monkeypatch.setattr(main.directmic, "works", lambda _s: False)
    window.cfg.route = "mic"
    window.routectl._warn_mute_does_nothing(False)
    assert len(shown) == 1 and window.cfg.mute_warning_off
    window.routectl._warn_mute_does_nothing(False)            # the next untick says nothing
    assert len(shown) == 1


def test_mini_mic_shows_its_state_with_an_icon(window):  # noqa: F811
    window.cfg.mic_enabled = False
    window._sync_mini_mic()
    off = window.mini_mic.icon().cacheKey()
    assert window.mini_mic.text() == "Mic muted" and window.mini_mic.accessibleName() == "My mic"
    window.cfg.mic_enabled = True
    window._sync_mini_mic()
    assert window.mini_mic.text() == "Mic on" and window.mini_mic.isChecked()
    assert window.mini_mic.icon().cacheKey() != off   # a struck-through mic only when muted
