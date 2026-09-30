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
    Config(sounds=sounds).save()
    w = main.MainWindow()
    # the loader thread writes the cache and prunes orphans: it must finish while the
    # temp paths are still patched in, never after the fixture is torn down
    w._load_thread.join(15)
    assert not w._load_thread.is_alive()
    yield w
    w.close()
    w._load_thread.join(15)   # a test may have started another load (e.g. Undo) just now
    assert not w._load_thread.is_alive()
    # a closed top-level window isn't freed by Qt; left alive, every later test's
    # theme / stylesheet change restyles all of them and the suite crawls
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
    assert window._pulse.state() == window._pulse.State.Running
    assert window.mic_banner.isVisibleTo(window)
    window.on_mic_check(False)
    assert window._pulse.state() == window._pulse.State.Stopped
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
    monkeypatch.setattr(window.engine, "stop", stopped.append)
    window._update_chips({"s0": (0.2, False)})
    assert window.playing_row.isHidden() and not window._chips   # one sound: no chips
    window.select("s1")
    window._update_chips({"s0": (0.2, False), "s1": (0.1, False)})
    assert not window.playing_row.isHidden() and set(window._chips) == {"s0", "s1"}
    name, stop = window._chips["s0"].findChildren(main.QPushButton)
    name.click()                        # takes s0 into the player, no restart
    assert window.current == "s0" and not stopped
    stop.click()
    assert stopped == ["s0"]


def test_mic_check_button_keeps_its_label(window):
    window.btn_check.setChecked(True)
    window.btn_check.setChecked(False)
    assert window.btn_check.text() == "Hear what they hear"


def test_pad_hints_show_only_on_the_sounds_tab(window):
    window.tabs.setCurrentWidget(window.sounds_page)
    assert "click to play" in window.status.text()
    window.tabs.setCurrentWidget(window.setup_page)
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


@pytest.mark.parametrize("size", [(300, 300), (480, 420), (800, 600)])
def test_window_shrinks_and_still_fits(window, size, qapp):
    """Down to 300 x 300 the less important controls give way and what's left fits
    (every tab counts: the tab widget's minimum is the largest page's)."""
    assert window.minimumSize().width() <= 300 and window.minimumSize().height() <= 300
    window.show()                            # offscreen: nothing appears
    window.tabs.setCurrentWidget(window.sounds_page)
    window.resize(*size)
    window._refit()
    need = window.centralWidget().minimumSizeHint()
    assert need.width() <= size[0] and need.height() <= size[1]
    assert window.grid.isVisibleTo(window) and window.btn_pp.isVisibleTo(window)
    small = window._fit.compact_count()
    assert small > 0
    window.resize(1800, 1000)                # and it comes back (tests have no real
    window._refit()                          # fonts, so text is wider than in the app)
    assert window._fit.compact_count() < small
    assert window.mixer.isVisibleTo(window) and window.np_name.isVisibleTo(window)


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


def test_every_tab_has_its_own_label(window):
    texts = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    assert texts == [t for t, _ in main.TABS] and len(set(texts)) == len(texts)
    window._tab_icons_only(True)
    assert window.tabs.tabText(1) == "" and window.tabs.tabToolTip(1).startswith("Radio")
    window._tab_icons_only(False)
    assert window.tabs.tabText(2) == "Apps"


def test_radio_and_apps_light_their_tabs_while_they_send_sound(window):
    tabs = window.tabs
    for panel in (window.radio, window.apps):
        i = tabs.indexOf(panel)
        assert not is_tab_live(tabs, i)
        panel.active_changed.emit(True)
        assert is_tab_live(tabs, i) and tabs.tabToolTip(i).startswith("● ON")
        panel.active_changed.emit(False)
        assert not is_tab_live(tabs, i) and not tabs.tabToolTip(i).startswith("●")


def test_mute_switch_silences_what_others_hear(window):
    e = window.engine
    assert window.btn_air.isChecked() and e.sending
    window.btn_air.click()
    assert not e.sending and "Muted" in window.btn_air.text()
    out = np.ones((64, 2), np.float32)
    e._main(out, 64)
    assert not out.any()
    window.set_sending(True)
    assert e.sending and window.btn_air.isChecked() and "Live" in window.btn_air.text()


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

    monkeypatch.setattr(window, "tray", Tray())
    monkeypatch.setattr(window, "shutdown", lambda: None)
    monkeypatch.setattr(main.QTimer, "singleShot", staticmethod(lambda *a: None))
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


def test_valorant_running_gets_the_push_to_talk_notice_once(window, monkeypatch):
    """Valorant's anti-cheat drops the keys auto push-to-talk presses: the first time
    it's seen running, a tray notification (never a window) says to hold the key."""
    from soundboard import appaudio
    shown = []

    class Tray:
        def isVisible(self):
            return True

        def showMessage(self, title, body, *a):
            shown.append((title, body))

    monkeypatch.setattr(window, "tray", Tray())
    exes = {"explorer.exe"}
    monkeypatch.setattr(appaudio, "running_exes", lambda: set(exes))
    window._check_input_blocking_game(100.0)
    assert shown == [] and not window.cfg.anticheat_tip_shown
    exes.add("valorant-win64-shipping.exe")
    window._check_input_blocking_game(101.0)      # looked 1 s ago: not yet
    assert shown == []
    window._check_input_blocking_game(100.0 + main.GAME_CHECK_S)
    assert len(shown) == 1 and "Valorant" in shown[0][0] and "hold" in shown[0][1]
    assert window.cfg.anticheat_tip_shown
    window._check_input_blocking_game(1000.0)      # once ever
    assert len(shown) == 1
