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
    window._fit.steps = [(p, a, (lambda c, f=f: (flips.append(c), f(c))))
                         for (p, a, _), f in zip(window._fit.steps, orig)]
    for w in range(950, 930, -2):                  # small moves, no edge crossed
        window.resize(w, 700)
        window._refit()
    assert len(flips) <= 2


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
        i = tabs.indexOf(window.radio_page if panel is window.radio else panel)
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
            window.showNormal()
            qapp.processEvents()
            assert not window.is_mini()
            assert window.ytresults.isVisibleTo(window)
            assert window.tabs.isVisibleTo(window)
    finally:
        theme.apply(qapp, old_theme)


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
    window.on_mic_check(True)                           # the warning keeps the version
    assert window.windowTitle().endswith(f"Onion Board {__version__} from source")
    window.on_mic_check(False)
    assert window.windowTitle() == f"Onion Board {__version__} from source"
    monkeypatch.setattr("sys.frozen", True, raising=False)
    assert mainwindow.version_text() == __version__     # the installed app: just the number
