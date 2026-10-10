"""Builds the real MainWindow on Qt's offscreen platform (no window appears, no
audio device is opened, no global hotkey is registered) and exercises the UI
plumbing: pad syncing, the metadata index, the mic-check pulse, the wheel guard."""
import numpy as np
import pytest
import soundfile as sf
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QScrollArea, QSlider, QVBoxLayout, QWidget

from soundboard import engine
from soundboard import library
from soundboard.ui import mainwindow as main
from soundboard import winkeys
from soundboard.library import SR, Config, SoundMeta
from soundboard.ui.livedot import is_tab_live
from soundboard.wheelguard import no_wheel


@pytest.fixture
def window(qapp, app_dir, monkeypatch):
    # no real devices, no real global hotkeys
    for name in ("set_main_device", "set_mon_device", "set_mic_device"):
        monkeypatch.setattr(engine.Engine, name, lambda self, n, _k=name: None)
    monkeypatch.setattr(winkeys.Hotkeys, "register", lambda self, m: None)
    sounds = []
    for i, name in enumerate(("Boom", "Airhorn")):
        p = app_dir / f"{name}.wav"
        t = np.arange(SR // 10) / SR
        sf.write(p, np.stack([np.sin(2 * np.pi * 440 * t)] * 2, 1) * 0.3, SR)
        sounds.append(SoundMeta(id=f"s{i}", name=name, file=str(p)))
    Config(sounds=sounds, mic_first=True).save()   # (on the cable)
    w = main.MainWindow()
    # the loader thread writes the cache and prunes orphans: it must finish while the
    # temp paths are still patched in, never after the fixture is torn down
    w._load_thread.join(15)
    assert not w._load_thread.is_alive()
    w.load_triggers()   # now, not on its timer in the middle of a test
    yield w
    w.close()
    w._load_thread.join(15)   # a test may have started another load (e.g. Undo) just now
    assert not w._load_thread.is_alive()
    # a closed top-level window isn't freed by Qt; left alive, every later test's
    # theme / stylesheet change restyles all of them and the suite crawls
    from PySide6.QtCore import QEvent
    w.deleteLater()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)


def test_triggers_timer_during_start_up(qapp, app_dir, monkeypatch):
    """The splash pumps events while the window is built: the load_triggers timer can
    run before __init__ ends, and threw AttributeError (_shut_down) when it did."""
    import sys
    import time
    for name in ("set_main_device", "set_mon_device", "set_mic_device"):
        monkeypatch.setattr(engine.Engine, name, lambda self, n, _k=name: None)
    monkeypatch.setattr(winkeys.Hotkeys, "register", lambda self, m: None)
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda t, v, tb: errors.append(v))
    calls = []
    real = main.MainWindow.load_triggers
    monkeypatch.setattr(main.MainWindow, "load_triggers",
                        lambda self, now=True: (calls.append(now), real(self, now)))

    def slow_pump():   # a slow start with the splash up
        time.sleep(main.TRIGGERS_LOAD_MS / 1000 + 0.03)
        qapp.processEvents()
    monkeypatch.setattr(main.splash, "pump", slow_pump)
    Config(sounds=[]).save()
    w = main.MainWindow()
    try:
        assert calls and not errors
    finally:
        w._load_thread.join(15)
        w.close()
        from PySide6.QtCore import QEvent
        w.deleteLater()
        qapp.sendPostedEvents(None, QEvent.DeferredDelete)


def test_window_builds_with_pads_and_index(window):
    assert set(window.pads) == {"s0", "s1"}
    assert window.meta("s1").name == "Airhorn" and window.meta("zz") is None
    assert window.grid.pads == [window.pads["s0"], window.pads["s1"]]


def test_rebuild_keeps_existing_pad_widgets(window):
    old = dict(window.pads)
    window.cfg.sounds.append(SoundMeta(id="s2", name="New", file="x.wav"))
    window._rebuild_pads()
    assert window.pads["s0"] is old["s0"] and window.pads["s1"] is old["s1"]
    assert "s2" in window.pads and window.meta("s2").name == "New"
    window.cfg.sounds.pop(0)
    window._rebuild_pads()
    assert "s0" not in window.pads and window.meta("s0") is None
    assert [p.meta.id for p in window.grid.pads] == ["s1", "s2"]


def test_reorder_moves_without_recreating(window):
    old = dict(window.pads)
    window.on_reorder("s1", 0)
    assert [m.id for m in window.cfg.sounds] == ["s1", "s0"]
    assert window.pads["s1"] is old["s1"]
    assert [p.meta.id for p in window.grid.pads] == ["s1", "s0"]


def test_mic_check_pulse_runs_only_while_on(window):
    window.on_mic_check(True)
    assert window._pulse.on
    assert window.mic_banner.isVisibleTo(window)
    window.mic_banner.click()             # only a sign: the mixer's button is the switch
    assert window.engine.mic_check
    window.on_mic_check(False)
    assert not window._pulse.on and not window._pulse.running()
    assert window._banner_fx.opacity() == 1.0


def test_tick_runs_without_devices(window):
    for _ in range(31):        # crosses the once-a-second watchdog branch
        window.tick()


def wheel(widget):
    ev = QWheelEvent(QPointF(5, 5), widget.mapToGlobal(QPoint(5, 5)), QPoint(0, 0),
                     QPoint(0, -120), Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False)
    QApplication.sendEvent(widget, ev)


def test_wheel_guard_scrolls_the_page_not_the_slider(qapp):
    area = QScrollArea()
    inner = QWidget()
    lay = QVBoxLayout(inner)
    guarded, plain = QSlider(Qt.Horizontal), QSlider(Qt.Horizontal)
    for s in (guarded, plain):
        s.setRange(0, 100)
        s.setValue(50)
        lay.addWidget(s)
    inner.setMinimumHeight(2000)
    area.setWidget(inner)
    area.resize(200, 200)
    no_wheel(guarded)
    wheel(plain)
    assert plain.value() != 50            # an unguarded slider changes
    before = area.verticalScrollBar().value()
    wheel(guarded)
    assert guarded.value() == 50          # a guarded one doesn't...
    assert area.verticalScrollBar().value() != before   # ...the page scrolls instead


def test_window_uses_only_the_temp_config(window, app_dir):
    assert library.CONFIG_PATH == app_dir / "config.json"
    assert len(window.cfg.sounds) == 2


def test_overlapping_sounds_each_get_a_stop_chip(window, monkeypatch):
    stopped = []
    window._update_chips({})
    assert window.playing_row.isHidden() and not window._chips   # nothing playing
    monkeypatch.setattr(window.engine, "stop", stopped.append)
    window._update_chips({"s0": (0.2, False)})
    assert not window.playing_row.isHidden() and set(window._chips) == {"s0"}  # one: a chip
    window.select("s1")
    window._update_chips({"s0": (0.2, False), "s1": (0.1, False)})
    assert not window.playing_row.isHidden() and set(window._chips) == {"s0", "s1"}
    name, stop = window._chips["s0"].findChildren(main.QPushButton)
    name.click()                        # takes s0 into the player, no restart
    assert window.current == "s0" and not stopped
    stop.click()
    assert stopped == ["s0"]


def test_a_web_search_sound_gets_a_chip_and_the_player_follows_it(window, monkeypatch):
    """Play a pad, then a web search result (Play once) over it, then stop the pad:
    the search's sound was in no chip and the player stayed on the stopped pad, so
    only Stop all could reach it."""
    import numpy as np
    from soundboard.ui.linkbar import PLAY_ID
    live = {"s0": (0.2, False)}
    monkeypatch.setattr(window.engine, "playing", lambda: dict(live))
    monkeypatch.setattr(window.engine, "stop", lambda sid: live.pop(sid, None))
    window.on_link_played("Search hit", np.zeros(4800, np.int16), 1.0)
    live[PLAY_ID] = (0.1, False)
    assert window.current == PLAY_ID
    window._update_chips(live)
    assert not window.playing_row.isHidden() and set(window._chips) == {"s0", PLAY_ID}
    window.select("s0")       # back on the board: pick the pad, stop it
    window.stop_current()
    assert window.current == PLAY_ID   # the player moved to what's still playing
    window._update_chips(live)
    # one sound left, the player shows it: its chip stays (the row going made it
    # look like ■ had stopped both)
    assert not window.playing_row.isHidden() and set(window._chips) == {PLAY_ID}
    window.select("s1")       # another pad picked while it plays: its chip stays
    window._update_chips(live)
    assert not window.playing_row.isHidden() and set(window._chips) == {PLAY_ID}


def test_now_playing_label_lines_up_with_its_chips(window, qapp):
    """The row's "Now playing" label sat at the chips' top edge, higher than them."""
    window.show()
    window.tabs.setCurrentWidget(window.sounds_page)
    window.select("s1")
    window._update_chips({"s0": (0.2, False), "s1": (0.1, False)})
    qapp.processEvents()
    lbl = next(w for w in window.playing_row.findChildren(main.QLabel)
               if w.text() == "Now playing")
    for chip in window._chips.values():
        assert abs(lbl.geometry().center().y() - chip.geometry().center().y()) <= 1


def test_mic_check_button_keeps_its_label(window):
    window.btn_check.setChecked(True)
    window.btn_check.setChecked(False)
    assert window.btn_check.text() == "Hear what they hear"


def test_seek_bar_starts_right_after_a_short_name(window, qapp):
    window.resize(946, 876)
    window.show()
    qapp.processEvents()
    window._set_np_name("Pick a sound")
    gap = window.seek.x() - window.np_name.geometry().right()
    assert gap <= 14, gap
    hint = window._name_seek.sizeHint()
    window._set_np_name("A very long sound name that never fits in the player bar")
    assert window.np_name.width() <= 190
    assert window._name_seek.sizeHint() == hint   # no page relayout on a new name
    assert window.seek.width() > 100


def test_no_pad_hint_line_under_the_player(window):
    window.tabs.setCurrentWidget(window.sounds_page)
    assert "click to play" not in window.status.text()


def test_sounds_only_toggle_leaves_the_mic_open(window, monkeypatch):
    opened = []
    monkeypatch.setattr(engine.Engine, "set_mic_device", lambda self, n: opened.append(n))
    window.chk_mic.setChecked(True)
    window.chk_mic.setChecked(False)
    assert window.cfg.mic_enabled is False and window.engine.mic_enabled is False
    assert opened == []                  # only the mix changes; the mic isn't closed
    assert "sounds only" in window.flow_mic.text()
    window.chk_mic.setChecked(True)
    assert window.engine.mic_enabled is True


@pytest.mark.parametrize("size", [(480, 420), (800, 600)])
def test_window_shrinks_and_still_fits(window, size, qapp):
    """The less important controls give way and what's left fits (every tab counts:
    the tab widget's minimum is the largest page's)."""
    window.show()                            # offscreen: nothing appears
    window.tabs.setCurrentWidget(window.sounds_page)
    window.resize(*size)
    window._refit()
    assert not window.is_mini()
    need = window._full.minimumSizeHint()
    assert need.width() <= size[0] and need.height() <= size[1]
    assert window.grid.isVisibleTo(window) and window.btn_pp.isVisibleTo(window)
    small = window._fit.compact_count()
    assert small > 0
    window.resize(1800, 1000)                # and it comes back (tests have no real
    window._refit()                          # fonts, so text is wider than in the app)
    assert window._fit.compact_count() < small
    assert window.mixer.isVisibleTo(window) and window.np_name.isVisibleTo(window)


def test_tiny_window_becomes_mini_player_and_back(window, qapp):
    """Too small to use: just the player (plus the pads if it's tall enough), and the
    whole window again, pads back in the Sounds tab, once it's big enough."""
    assert window.minimumSize().width() <= 260 and window.minimumSize().height() <= 120
    window.show()
    window.tabs.setCurrentWidget(window.sounds_page)
    window.select("s1")
    window.resize(260, 120)
    window._refit()
    assert window.is_mini()
    assert window.mini_pp.isVisibleTo(window) and window.mini_air.isVisibleTo(window)
    assert window.mini_name.text() == "Airhorn"
    assert not window.grid.isVisibleTo(window)    # no room for pads
    window.resize(540, 180)                        # short: one-line rows, not cards
    window._refit()
    assert window.is_mini() and window.grid.isVisibleTo(window) and window.grid.slim
    assert window.pads["s0"].height() <= 30
    window.resize(360, 700)                        # tall and narrow: the pads come along
    window._refit()
    assert window.is_mini() and window.grid.isVisibleTo(window) and not window.grid.slim
    window.mini_air.setChecked(False)              # one switch, both buttons
    assert not window.btn_air.isChecked() and window.engine.sending is False
    window.btn_air.setChecked(True)
    assert window.mini_air.isChecked()
    window.resize(1100, 760)
    window._refit()
    assert not window.is_mini()
    assert window._pads_scroll.parentWidget().parentWidget() is window.sounds_page.parentWidget() \
        or window.grid.isVisibleTo(window)
    assert window._pads_home[0].indexOf(window._pads_scroll) == window._pads_home[1]


def test_refit_leaves_widgets_alone_when_nothing_crosses_an_edge(window, qapp):
    """Resizing only touches the steps at the edge it crossed, so a border drag
    doesn't show and hide half the window on every mouse move (it flashed)."""
    window.show()
    window.resize(950, 700)
    window._refit()
    flips = []
    orig = [s[2] for s in window._fit.steps]
    window._fit.steps = [(p, a, (lambda c, f=f, i=i: (flips.append((i, c)), f(c))))
                         for i, ((p, a, _), f) in enumerate(zip(window._fit.steps, orig))]
    for w in range(950, 930, -2):                  # small moves, no edge crossed
        window.resize(w, 700)
        window._refit()
    # New controls may move an edge into this interval. Each step may tighten once;
    # repeatedly undoing/reapplying it is the flashing this test guards against.
    assert len(flips) == len({i for i, _ in flips})
    assert all(compact for _, compact in flips)


def test_maximizing_doesnt_grow_what_the_window_needs(window, qapp):
    """A maximized window shows the Radio tab's genre chips, and their box used to
    ask for every chip on its own line (~300 px). Every tab counts towards what the
    window needs, so restoring it to an ordinary size made it the mini player. Each
    page now needs about as much big as at an ordinary size."""
    window.show()
    window.tabs.setCurrentWidget(window.sounds_page)
    window.resize(1180, 720)
    window._refit()
    page = window.tabs.widget([t for t, _ in main.TABS].index("Radio"))
    assert page.isAncestorOf(window.radio)
    small = page.minimumSizeHint().height()
    for _ in range(2):
        window.resize(1920, 1040)                  # maximize...
        window._refit()
        qapp.processEvents()
        assert not window.radio.genre_box.isHidden()   # (its tab isn't the one showing)
        assert page.minimumSizeHint().height() < small + 120
        assert window._full.minimumSizeHint().height() <= 720
        window.resize(1180, 720)                   # ...and restore
        window._refit()
        qapp.processEvents()
        assert not window.is_mini() and window.tabs.isVisibleTo(window)


def test_flow_asks_for_its_lines_at_its_width_not_one_chip_a_line(qapp):
    from PySide6.QtWidgets import QPushButton, QWidget

    from soundboard.ui.panel import Flow
    box = QWidget()
    flow = Flow(box, gap=5)
    for i in range(12):
        flow.addWidget(QPushButton(f"Genre {i}"))
    one_line = flow.sizeHint()
    assert one_line.height() == flow.heightForWidth(one_line.width())
    assert one_line.height() < 2 * QPushButton("Genre 0").sizeHint().height()
    box.resize(300, 400)
    flow.activate()
    assert flow.sizeHint().width() == 300
    assert flow.sizeHint().height() == flow.heightForWidth(300) > one_line.height()


# ---------------------------------------------------------------- effects

def test_mainwindow_effects_rerender(qapp, window):
    from conftest import process_events
    assert process_events(qapp, lambda: "s0" in window.audio, 10)
    m = window.meta("s0")
    before = len(window.audio["s0"])
    m.fx = {"speed": 2.0}
    window._rerender(m)
    assert window.pads["s0"].state == "rendering" and "s0" not in window.audio
    assert process_events(qapp, lambda: "s0" in window.audio, 15)
    assert abs(len(window.audio["s0"]) - before / 2) < 10
    assert window.pads["s0"].state == "ready"
    assert abs(m.duration - before / 2 / SR) < 0.01


def test_mainwindow_live_speed_button_drives_the_engine(window):
    window.speed_btn.set_values(0.5, 4, False)
    e = window.engine
    assert (e.sound_speed, e.sound_pitch, e.sound_keep_pitch) == (0.5, 4, False)
    window.speed_btn.reset()
    assert (e.sound_speed, e.sound_pitch) == (1.0, 0.0)


def test_live_effects_drive_the_engine(window):
    b, e = window.speed_btn, window.engine
    assert e.sound_fx == {} and "FX" not in b.text()
    b.fx["bass"].set_value(9)
    b.fx["bass"].changed.emit()
    assert e.sound_fx == {"bass": 9} and "FX" in b.text()
    b.fx_presets["Concert hall"].click()                     # a preset replaces them all
    assert e.sound_fx == {"reverb": 0.55} and b.fx_presets["Concert hall"].isChecked()
    b.fx_presets["Concert hall"].click()                     # clicked again: off
    assert e.sound_fx == {}
    b.set_fx({"echo": 0.5})
    b.set_values(1.5, 2, True)
    b.reset()                                                # Reset all clears the effects
    assert e.sound_fx == {} and (e.sound_speed, e.sound_pitch) == (1.0, 0.0)
    assert "FX" not in b.text()


def test_speed_redline_unlocks_the_silly_range(window):
    b, e = window.speed_btn, window.engine
    assert b.speed.q.hi == 2.0 and b.red_box.isHidden()
    b.speed.set_value(10)                                    # locked: capped at 2x
    assert b.speed.value() == 2.0
    b.redline.setChecked(True)
    assert not b.red_box.isHidden() and b.speed.q.hi == 10 and b.pitch.q.hi == 36
    b.set_values(8.0, -30, True)
    assert (e.sound_speed, e.sound_pitch) == (8.0, -30)
    assert b.meter.speed == 8.0 and "8x" in b.text()
    b.redline.setChecked(False)                              # locking pulls it back in
    assert (e.sound_speed, e.sound_pitch) == (2.0, -12)
    b.set_values(5.0, 0, True)                               # a redline value unlocks it
    assert b.redline.isChecked() and e.sound_speed == 5.0
    b.meter.grab()                                           # paints without errors


def test_speed_popup_shrinks_back_when_redline_locks(window, qapp):
    b = window.speed_btn
    b.click()
    qapp.processEvents()
    closed = b.pop.height()
    b.redline.click()
    qapp.processEvents()
    assert b.pop.height() > closed                           # room for the rev meter
    b.redline.click()
    qapp.processEvents()
    assert b.pop.height() == closed                          # and gives it back
    b.pop.hide()


def test_every_tab_has_its_own_label(window):
    texts = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    assert texts == [t for t, _ in main.TABS] and len(set(texts)) == len(texts)
    assert window.tabs.tabToolTip(2) == ""   # the name says it: no hover tip


def test_the_tabs_are_a_rail_down_the_left(window, qapp):
    """Icons only (no hover tips); the button at the bottom opens it out to the names
    and the onion (saved); a narrow window shuts it again."""
    window.show()
    window.resize(1200, 760)
    window._refit()
    rail = window.rail
    assert window.tabs.tabBar().isHidden()   # the rail shows the tabs, not the bar
    assert not rail.is_open() and rail.width() == main.sidebar.SHUT_W
    b = rail.buttons[1]
    assert b.text() == "" and b.toolTip() == "" and b.accessibleName() == "Radio"
    assert not rail.buttons[0].icon().isNull()
    assert rail.buttons[0].isChecked() == (window.tabs.currentIndex() == 0)
    assert window.wordmark.isHidden()
    rail.toggle.click()
    assert rail.is_open() and window.cfg.sidebar_open
    assert b.text() == "Radio" and b.toolTip() == ""
    assert not window.wordmark.isHidden() and not window.tagline.isHidden()
    rail.buttons[5].click()
    assert window.tabs.currentIndex() == 5 and rail.buttons[5].isChecked()
    window.tabs.setTabVisible(2, False)
    assert rail.buttons[2].isHidden()
    window.tabs.setTabVisible(2, True)
    rail.squeeze(True)   # a narrow window
    assert not rail.is_open() and rail.width() == main.sidebar.SHUT_W
    rail.squeeze(False)
    assert rail.is_open()
    rail.toggle.click()
    assert not window.cfg.sidebar_open


def test_sounds_tab_lights_up_while_a_sound_plays(window, monkeypatch):
    tabs, i = window.tabs, window.tabs.indexOf(window.sounds_page)
    playing = {}
    monkeypatch.setattr(window.engine, "playing", lambda: dict(playing))
    window.tick()
    assert not is_tab_live(tabs, i)
    playing["s0"] = (0.3, False)
    window.tick()
    assert is_tab_live(tabs, i) and tabs.tabToolTip(i).startswith("● ON")
    playing["s0"] = (0.3, True)                  # paused: not live
    window.tick()
    assert not is_tab_live(tabs, i)
    playing.clear()
    playing["__test__"] = (0.1, False)           # the mic test's playback isn't a sound
    window.tick()
    assert not is_tab_live(tabs, i) and not tabs.tabToolTip(i).startswith("●")
    from soundboard.ui.linkbar import PLAY_ID   # a web search's Play lights it too
    playing.clear()
    playing[PLAY_ID] = (0.1, False)
    window.tick()
    assert is_tab_live(tabs, i)


def test_player_bar_follows_to_other_tabs_while_a_sound_plays(window, monkeypatch):
    """Off the Sounds tab the player is there only while a sound plays (or is paused),
    so it can be stopped from anywhere."""
    playing = {}
    monkeypatch.setattr(window.engine, "playing", lambda: dict(playing))
    bar = window.transport
    assert bar.parent() is not window.sounds_page   # under the tabs, not in the page
    window.tabs.setCurrentWidget(window.sounds_page)
    assert not bar.isHidden()                        # always on the Sounds tab
    window.tabs.setCurrentWidget(window.setup_page)
    assert bar.isHidden()                            # nothing playing: out of the way
    playing["s0"] = (0.3, False)
    window._show_transport(window.engine.playing())
    assert not bar.isHidden()
    playing["s0"] = (0.3, True)                      # paused: still there to resume
    window._show_transport(window.engine.playing())
    assert not bar.isHidden()
    playing.clear()
    playing["__test__"] = (0.1, False)               # the mic test's playback isn't a sound
    window._show_transport(window.engine.playing())
    assert bar.isHidden()
    window.tabs.setCurrentWidget(window.sounds_page)
    assert not bar.isHidden()


def test_radio_and_apps_light_their_tabs_while_they_send_sound(window):
    tabs = window.tabs
    for panel in (window.radio, window.apps):
        i = tabs.indexOf(window.radio_page if panel is window.radio else panel)
        assert not is_tab_live(tabs, i)
        panel.active_changed.emit(True)
        assert is_tab_live(tabs, i) and tabs.tabToolTip(i).startswith("● ON")
        panel.active_changed.emit(False)
        assert not is_tab_live(tabs, i) and not tabs.tabToolTip(i).startswith("●")


def test_mute_switch_silences_what_others_hear(window, monkeypatch):
    # a send device, so Live is Live even on a PC (CI) with no cable
    monkeypatch.setattr(window, "_main_name", lambda: "CABLE Input")
    e = window.engine
    assert window.btn_air.isChecked() and e.sending
    window.btn_air.click()
    assert not e.sending and "Muted" in window.btn_air.accessibleName()
    out = np.ones((64, 2), np.float32)
    e._main(out, 64)
    assert not out.any()
    window.set_sending(True)
    assert e.sending and window.btn_air.isChecked() and "Live" in window.btn_air.accessibleName()


def test_closing_the_window_ends_its_computer_voice_thread(window):
    """Every window's computer voice runs a speaker thread. Left behind by each closed
    window, a full test run piled up dozens of them."""
    import threading

    def speakers():
        return sum(t.name == "tts-speaker" for t in threading.enumerate())
    t = window.voice.controller.speaker._thread
    assert t.is_alive()
    before = speakers()
    window.close()
    assert not t.is_alive()
    assert speakers() == before - 1


def test_an_installer_or_log_off_really_closes_the_app(window, monkeypatch):
    """Closing normally hides to the tray; but when Windows asks the app to close
    (log-off, or an installer through the Restart Manager) hiding would veto it and
    the upgrade would fail with "unable to close all applications"."""
    from PySide6.QtGui import QCloseEvent

    class Tray:
        def isVisible(self):
            return True

        def hide(self):
            pass

        def showMessage(self, *a):
            pass

    # its own context: the window fixture's close must find the real shutdown again,
    # or the window's threads (computer voice and all) are never stopped
    with monkeypatch.context() as mp:
        mp.setattr(window, "tray", Tray())
        mp.setattr(window, "shutdown", lambda: None)
        mp.setattr(main.QTimer, "singleShot", staticmethod(lambda *a: None))
        window.cfg.tray = True
        ev = QCloseEvent()
        window.closeEvent(ev)
        assert not ev.isAccepted()                  # the ✕ button: off to the tray
        app = QApplication.instance()          # Windows' request reaches the window...
        assert app.receivers("2commitDataRequest(QSessionManager&)") >= 1
        window._on_session_end()               # ...(emitting it here needs a real session)
        ev = QCloseEvent()
        window.closeEvent(ev)
        assert ev.isAccepted()


def test_pads_fit_the_width_with_no_sideways_scrolling(window, qapp):
    """Big pads in a narrow window get narrower instead of running off the edge, and
    the mini player puts two a row while they're still a usable size."""
    window.show()
    window.set_pad_width(240)
    window.resize(1000, 700)
    window._refit()
    assert window.pads["s0"].width() == 240
    window.resize(270, 600)
    window._refit()
    qapp.processEvents()
    scroll = window._pads_scroll
    assert window.is_mini() and scroll.isVisibleTo(window)
    assert scroll.horizontalScrollBar().maximum() == 0
    assert window.grid.width() <= scroll.viewport().width()
    a, b = window.pads["s0"], window.pads["s1"]
    assert a.geometry().right() <= scroll.viewport().width()
    assert a.y() == b.y() and a.width() < 240          # two a row
    window.resize(1000, 700)
    window._refit()
    assert not window.is_mini() and window.pads["s0"].width() == 240


@pytest.mark.windows   # Segoe UI's text widths: with another font the columns fit side by side
def test_setup_stacks_long_controls_without_sideways_scrolling(window, qapp):
    """Long translated controls must fit the viewport, then unfold at a wider size."""
    from PySide6.QtWidgets import QBoxLayout

    window.cfg.route = "mic"
    window._update_flow()
    window.btn_install.setText("Meine Sounds direkt in mein Mikro legen für Discord und Spiele")
    window.btn_install.setMinimumWidth(650)  # a long translated action
    window.btn_install.show()
    # The offscreen test font needs wider cards than the shipped Segoe UI font.
    window._setup_cols.parentWidget().setMaximumWidth(1500)
    window.tabs.setCurrentWidget(window.setup_page)
    window.show()
    for width in (900, 1600, 900):
        window.resize(width, 700)
        for _ in range(6):
            qapp.processEvents()
            window._refit()
        assert not window.is_mini()
        assert window.setup_page.horizontalScrollBar().maximum() == 0
        assert window._setup_cols.direction() == (
            QBoxLayout.TopToBottom if width == 900 else QBoxLayout.LeftToRight)


def test_an_empty_board_shrinks_with_the_window(window, qapp):
    """No sounds, then a small window: the "drop sound files here" bunny came along at
    the big window's width, so the mini player showed an empty void you had to
    scroll sideways across."""
    window.cfg.sounds.clear()
    window._rebuild_pads()
    window.show()
    window.resize(1400, 800)
    window._refit()
    window.resize(265, 520)
    window._refit()
    qapp.processEvents()
    scroll = window._pads_scroll
    assert window.is_mini() and window.grid.empty.isVisibleTo(window)
    assert window.grid.width() <= scroll.viewport().width()
    assert window.grid.empty.geometry().right() <= scroll.viewport().width()


def test_the_whole_window_comes_back_after_the_mini_player(window, qapp):
    """Out of the mini player at a size the whole window fits (its hidden page's
    sizes went stale, and it stayed the mini player)."""
    window.show()
    window.tabs.setCurrentWidget(window.sounds_page)
    window.resize(1000, 700)
    window._refit()
    for size in ((300, 600), (430, 600), (520, 600)):
        window.resize(*size)
        window._refit()
    assert not window.is_mini()


@pytest.mark.windows   # Segoe UI's text widths
def test_every_tab_stays_the_whole_window_down_to_the_mini_size(window, qapp):
    """The icon-only tabs' padding alone needed ~480 px, so a window the rest fits
    (480 px is a 600 px window at 125 %) turned into the mini player."""
    from soundboard.ui.mainwindow import MINI_SIZE

    window.show()
    window.resize(1000, 700)
    window._refit()
    for page in (window.sounds_page, window.radio_page, window.apps, window.voice,
                 window.setup_page):
        window.tabs.setCurrentWidget(page)
        window.resize(MINI_SIZE.width() + 10, 700)
        window._refit()
        assert not window.is_mini(), type(page).__name__
        window.resize(1000, 700)
        window._refit()


def test_the_mini_player_shows_the_pads_whatever_is_in_the_search_box(window, qapp):
    """A web search's words stay in the search box, which also filters the pads: the
    mini player (no search box) was blank. And a board with every pad filtered out
    says so instead of showing nothing."""
    from soundboard.ui.widgets import PadGrid

    window.show()
    window.tabs.setCurrentWidget(window.apps)
    window.resize(1000, 700)
    window._refit()
    window.search.setText("idiot test")             # matches none of the sounds
    assert not any(p.isVisibleTo(window) for p in window.grid.pads)
    window.tabs.setCurrentWidget(window.sounds_page)
    qapp.processEvents()
    assert window.grid.empty.isVisibleTo(window)
    assert window.grid.empty_text.text() == PadGrid.NO_MATCH
    window.tabs.setCurrentWidget(window.apps)
    window.resize(360, 700)
    window._refit()
    assert window.is_mini()
    assert all(p.isVisibleTo(window) for p in window.grid.pads)
    assert not window.grid.empty.isVisibleTo(window)
    window.resize(1000, 700)
    window._refit()
    assert not window.is_mini()
    assert window.search.text() == "idiot test"     # still filtering the whole window
    assert not any(p.property("filtered") is False and p.isVisibleTo(window)
                   for p in window.grid.pads)


@pytest.mark.parametrize("theme_name", ["Dark", "Retro 98"])
def test_restoring_a_large_window_keeps_search_results(window, qapp, theme_name):
    """Maximize/restore must keep the full app and the selected search view."""
    from soundboard import theme, ytdl

    old_theme = window.cfg.theme
    try:
        theme.apply(qapp, theme_name)
        window.cfg.sounds.clear()
        window._rebuild_pads()
        window.tabs.setCurrentWidget(window.sounds_page)
        window.ytresults.query = "test tone"
        window.ytresults._on_done(0, [
            ytdl.Result("test", "Test tone", "Example", 60, source="myinstants")
        ], "")
        window.ytresults.show()
        window._pads_scroll.hide()
        window.resize(1180, 720)
        window.show()
        qapp.processEvents()
        for _ in range(2):
            window.showMaximized()
            qapp.processEvents()
            # the offscreen screen is 800 x 800: be as big as a real maximized window
            window.resize(1920, 1040)
            window._refit()
            qapp.processEvents()
            assert not window.is_mini()
            window.showNormal()
            qapp.processEvents()
            assert not window.is_mini()
            assert window.ytresults.isVisibleTo(window)
            assert window.tabs.isVisibleTo(window)
    finally:
        theme.apply(qapp, old_theme)


@pytest.mark.parametrize("theme_name", ["Dark", "Retro 98", "Comic Sans"])
def test_card_titles_and_the_typed_percent_fit_the_themes_font(qapp, theme_name):
    """Both used to size themselves before the theme's font arrived with its style
    sheet: a title's second line lost its descenders, "1000 %" didn't fit Tahoma."""
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from soundboard import theme
    from soundboard.ui.panel import VolumeControl
    from soundboard.ui.ytsearch import ClampLabel

    old = theme.current_name
    try:
        theme.apply(qapp, theme_name)
        host = QWidget()
        v = QVBoxLayout(host)
        title, vol = ClampLabel("A title long enough to wrap " * 3), VolumeControl(1.0)
        v.addWidget(title)
        v.addWidget(vol)
        host.resize(220, 200)
        host.show()
        qapp.processEvents()
        assert title.height() == 2 * title.fontMetrics().lineSpacing() + 2
        spin = vol.spin
        assert spin.width() >= spin.fontMetrics().horizontalAdvance("1000%") + 10
        assert not spin.keyboardTracking()   # typing "150" isn't 1 %, 15 %, 150 %
        host.deleteLater()
    finally:
        theme.apply(qapp, old)


def test_a_whole_row_of_pads_before_the_mixer(window, qapp):
    """A short window drops the mixer and the rest before squeezing the pads into a
    slit you'd have to scroll through."""
    window.show()
    window.tabs.setCurrentWidget(window.sounds_page)
    window.resize(700, 400)
    window._refit()
    qapp.processEvents()
    if not window.is_mini():
        assert window._pads_scroll.height() >= window.pads["s0"].height()


def test_the_mini_player_keeps_the_pads_while_one_row_fits(window, qapp):
    """A wide, short window (big pads, 125 % scaling) showed the mini player with
    nothing above it: the pads only came along when two rows fit."""
    window.show()
    window.tabs.setCurrentWidget(window.sounds_page)
    window.set_pad_width(240)
    window.resize(1100, 330)
    window._refit()
    size = window._pages.size()
    assert window.is_mini()
    assert window._mini_row(size) <= window._mini_pad_room(size) < 2 * window._mini_row(size)
    assert window.grid.isVisibleTo(window)


def test_the_window_shows_which_version_is_running(window, monkeypatch):
    from soundboard import __version__
    from soundboard.ui import mainwindow
    assert window.windowTitle() == f"Onion Board {__version__} from source"
    assert window.tagline.text().endswith(f"v{__version__} from source")
    window.on_mic_check(True)          # the red banner says it; the title stays the app's name
    assert window.windowTitle() == f"Onion Board {__version__} from source"
    window.on_mic_check(False)
    assert window.windowTitle() == f"Onion Board {__version__} from source"
    monkeypatch.setattr("sys.frozen", True, raising=False)
    assert mainwindow.version_text() == __version__     # the installed app: just the number


def test_empty_status_line_takes_no_room(window):
    """No message, no row: the mixer sits at the bottom with only the margin under it."""
    window.resize(1200, 800)
    window.show()
    QApplication.processEvents()
    st = window.status
    window.status.setText("")
    QApplication.processEvents()
    assert not st.isVisible()
    gap = window._full.height() - window.mixer.geometry().bottom()
    assert gap <= 12
    st.setText("1 audio drop-out since start")
    assert st.isVisible()
    st.set_room(True)            # window too short: stays hidden, even for a new message
    st.setText("Category: All")
    assert not st.isVisible()
    st.set_room(False)
    assert st.isVisible()
    st.setText("")
    st.set_room(False)           # room again, but nothing to say
    assert not st.isVisible()


def test_ctrl_v_pastes_a_copied_picture_on_the_selected_pad(window):
    from PySide6.QtGui import QColor, QImage
    window.select("s1")
    QApplication.clipboard().setText("just words")
    window.paste_picture()
    assert not window.meta("s1").image and "copy a picture first" in window.status.text()
    img = QImage(200, 120, QImage.Format_RGB32)
    img.fill(QColor("#ff00ff"))
    QApplication.clipboard().setImage(img)
    window.paste_picture()
    pic = window.meta("s1").image
    assert pic and library.Path(pic).is_file() and not window.meta("s0").image
    assert "Airhorn" in window.status.text()
    window.selection.on_pick("s0", False)   # picked pads win over the selected one
    window.selection.on_pick("s1", False)
    window.paste_picture()
    assert window.meta("s0").image and window.meta("s1").image != pic
    assert not library.Path(pic).exists()   # the old picture's file is gone


def test_ctrl_v_adds_a_clip_copied_in_the_clip_editor_as_a_sound(window):
    import numpy as np

    from soundboard.ui import clipeditor
    n = len(window.cfg.sounds)
    clipeditor.set_clipboard(np.zeros((int(0.23 * 48000), 2), np.float32))   # even silence
    try:
        window.paste_picture()
        assert len(window.cfg.sounds) == n + 1
        assert window.cfg.sounds[-1].name.startswith("Clip ")
        QApplication.clipboard().setText("words")      # copied something since: not again
        window.paste_picture()
        assert len(window.cfg.sounds) == n + 1
        # the real key, after switching to the Sounds tab from another one
        from PySide6.QtTest import QTest
        clipeditor.set_clipboard(np.zeros((4800, 2), np.float32))
        window.show()
        window.activateWindow()
        window.tabs.setCurrentWidget(window.apps)
        window.tabs.setCurrentWidget(window.sounds_page)
        QApplication.processEvents()
        QTest.keyClick(QApplication.focusWidget() or window.sounds_page, Qt.Key_V,
                       Qt.ControlModifier)
        assert len(window.cfg.sounds) == n + 2
    finally:
        clipeditor.clipboard = None


def test_new_pads_never_flash_up_as_windows_of_their_own(qapp):
    """A new pad has no parent until the grid takes it: shown before that, it popped
    up on the desktop for a moment as a little blank window (behind the splash)."""
    from PySide6.QtCore import QEvent, QObject

    from soundboard.library import SoundMeta
    from soundboard.ui.widgets import Pad, PadGrid

    flashed = []

    class Watch(QObject):
        def eventFilter(self, o, e):
            if e.type() == QEvent.Show and isinstance(o, Pad) and o.isWindow():
                flashed.append(o)
            return False

    watch = Watch()
    qapp.installEventFilter(watch)
    try:
        grid = PadGrid()
        grid.set_pads([Pad(SoundMeta(id=f"s{i}", name=f"Sound {i}", file=""), 200)
                       for i in range(3)])
        assert not flashed
        assert all(p.parent() is grid for p in grid.pads)
    finally:
        qapp.removeEventFilter(watch)


def test_the_mic_banner_and_a_row_of_playing_sounds_dont_force_the_mini_player(window):
    """Both used to be as wide as all their text: the banner ~780 px, four
    overlapping sounds' chips ~900 px, so a window a bit narrower became the mini
    player in the middle of a session. The chips wrap onto more lines."""
    window.show()
    window.tabs.setCurrentWidget(window.sounds_page)
    window.resize(800, 600)
    window._refit()
    assert not window.is_mini()
    window.mic_banner.show()
    ids = list(window.pads)
    window._queue[:] = ids * 3
    window._update_chips(set(ids))
    window._refit()
    assert window.playing_row.isVisibleTo(window)
    assert not window.is_mini()
    assert window.mic_banner.width() <= 800 and window.mic_banner.text()
    # every playing sound keeps its chip (to stop it): the row wraps instead
    assert set(window._chips) == set(ids)
    row = window.playing_row.rect()
    for chip in window._chips.values():
        assert chip.isVisibleTo(window) and row.contains(chip.geometry())


def test_clamp_label_wraps_once_per_text_width_and_font(qapp):
    """Cards repaint on every hover and scroll: the wrapped lines are kept until the
    text, width or font changes."""
    from soundboard.ui.ytsearch import ClampLabel
    lbl = ClampLabel("A title long enough to wrap " * 3)
    lbl.resize(160, lbl.height())
    lines = lbl._wrapped()
    assert len(lines) == 2 and lines[-1][0].endswith("…")
    assert lbl._wrapped() is lines
    lbl.resize(400, lbl.height())
    assert lbl._wrapped() is not lines
    wide = lbl._wrapped()
    lbl.set_full("Short")
    assert lbl._wrapped() is not wide and [t for t, _ in lbl._wrapped()] == ["Short"]
    lbl.deleteLater()


def test_windows_language_is_offered_in_that_language(window, monkeypatch):
    from soundboard import i18n
    monkeypatch.setattr(i18n, "windows_language", lambda: "de-DE")
    restarts = []
    monkeypatch.setattr(window, "restart_app", lambda: restarts.append(1))
    window._offer_language()
    assert window.lang_bar.isVisibleTo(window)
    assert window.lang_lbl.text() == ("Onion Board gibt es auch auf Deutsch. Du kannst die "
                                      "Sprache jederzeit unter Einstellungen → Aussehen → "
                                      "Sprache ändern.")
    assert window.lang_btn.text() == "Zu Deutsch wechseln"
    window.lang_btn.click()
    assert window.cfg.language == "de" and restarts == [1]
    assert not window.lang_bar.isVisibleTo(window)
    window._offer_language()                     # picked: never offered again
    assert not window.lang_bar.isVisibleTo(window)


def test_turning_down_the_language_offer_is_remembered(window, monkeypatch):
    from soundboard import i18n
    monkeypatch.setattr(i18n, "windows_language", lambda: "ja-JP")
    window._offer_language()
    assert window.lang_bar.isVisibleTo(window) and window.lang_btn.text() == "日本語に切り替えます"
    window.lang_hide.click()
    assert not window.lang_bar.isVisibleTo(window) and window.cfg.language == ""
    window._offer_language()
    assert not window.lang_bar.isVisibleTo(window)


def test_no_language_offer_on_an_english_windows(window, monkeypatch):
    from soundboard import i18n
    monkeypatch.setattr(i18n, "windows_language", lambda: "en-GB")
    window._offer_language()
    assert not window.lang_bar.isVisibleTo(window)


def test_setup_not_done_yet_is_one_orange_step_not_red_crosses(window, monkeypatch):
    """Cable route, no cable, mic closed: the card's two lines say what's still to
    do in the warn colour; the red cross is for things that are wrong."""
    from soundboard import engine as eng
    from soundboard import theme
    # the real device list: a PC with a virtual cable installed isn't "no cable"
    monkeypatch.setattr(eng, "virtual_outputs", lambda: [])
    w = window
    w.cfg.route = "cable"
    w._update_flow()
    assert w.setup_state == "missing"
    text = w.flow_mic.text() + w.flow_out.text()
    assert "✗" not in text and theme.status("error") not in text
    assert "after the setup below" in w.flow_mic.text()
    assert "not installed yet" in w.flow_out.text()


def test_sounds_toolbar_dropdown_menus_open_with_gap(window, qapp):
    """Dropdown menus on the sound page toolbar open with a short pixel gap from their button."""
    from soundboard.ui.widgets import DropdownMenu
    w = window
    w.show()
    for btn in (w.btn_more, w.btn_keys, w.btn_view):
        menu = btn.menu()
        assert isinstance(menu, DropdownMenu)
        btn.showMenu()
        qapp.processEvents()
        try:
            bottom = btn.mapToGlobal(btn.rect().bottomLeft()).y()
            assert menu.y() - bottom >= DropdownMenu.GAP
        finally:
            menu.close()
            qapp.processEvents()



@pytest.mark.parametrize("size", [(800, 600), (1180, 720)])
def test_audit_normal_navigation_returns_from_mini(window, qapp, size):
    window.show()
    window.resize(360, 320)
    qapp.processEvents()
    assert window.is_mini()
    window.resize(*size)
    for _ in range(3):
        qapp.processEvents()
    for i in range(window.tabs.count()):
        window.tabs.setCurrentIndex(i)
        window._refit()
        assert not window.is_mini()
        assert window.rail.isVisibleTo(window)


def test_audit_mini_mic_controls_share_the_mixer_state(window, qapp):
    window.show()
    window.resize(360, 320)
    qapp.processEvents()
    assert window.mini_connection.isVisibleTo(window)
    assert window.mini_connection.text()
    assert window.mini_connection.accessibleName() == window._pill_long
    window.mini_mic.setChecked(False)
    assert not window.cfg.mic_enabled and not window.chk_mic.isChecked()
    assert window.mini_mic.text() == "Mic muted"
    window.chk_mic.setChecked(True)
    assert window.cfg.mic_enabled and window.mini_mic.isChecked()
    window.mini_connection.click()
    qapp.processEvents()
    assert not window.is_mini() and window.tabs.currentWidget() is window.setup_page


def test_audit_expanded_sidebar_labels_status(window, qapp):
    window.show()
    window.resize(1180, 720)
    window.rail.set_open(True)
    qapp.processEvents()
    for button in (window.btn_air, window.mode_btn, window.stop_btn, window.pill):
        if not button.isHidden():
            assert button.text() and button.accessibleName()


def test_audit_setup_routes_and_local_test_precede_advanced_controls(window, qapp):
    window.show()
    window.resize(1180, 720)
    window.tabs.setCurrentWidget(window.setup_page)
    qapp.processEvents()
    view = window.setup_page.viewport()
    for widget in (window.cb_mic, window.cb_route, window.btn_rec):
        assert 0 <= widget.mapTo(view, QPoint()).y() < view.height()
    assert "local" in window.btn_rec.text()
    assert window.cb_route.mapTo(view, QPoint()).y() < window.eq.mapTo(view, QPoint()).y()


def test_drop_target_keeps_the_full_board_width(window, qapp):
    window.show()
    window.tabs.setCurrentIndex(0)
    window.resize(1180, 720)
    qapp.processEvents()
    rect = window.grid.drop_area()
    margins = window.grid.grid.contentsMargins()
    assert rect is not None and rect.height() >= 90
    assert rect.width() == window.grid.width() - margins.left() - margins.right() - 4


def test_medium_footer_uses_the_width_without_empty_control_gaps(window, qapp):
    window.apply_theme("Dark")
    window.tabs.setCurrentIndex(0)
    window.show()
    for size in ((360, 320), (440, 380), (600, 450), (800, 600)):
        window.resize(*size)
        for _ in range(5):
            qapp.processEvents()
    assert not window.is_mini()
    assert window.mixer.height() < 70
    assert window.btn_check.isVisibleTo(window)
    right = window.btn_check.mapTo(window.mixer, window.btn_check.rect().topRight()).x()
    assert window.mixer.width() - right <= 20
    window.np_name.hide()
    qapp.processEvents()
    seek_left = window.seek.mapTo(window.btn_st.parentWidget(), QPoint()).x()
    assert seek_left - window.btn_st.geometry().right() <= 24
    buttons = window.rail.buttons
    assert all(b.height() >= 34 for b in buttons)
    assert all(b.y() - a.geometry().bottom() >= 4
               for a, b in zip(buttons, buttons[1:]))
