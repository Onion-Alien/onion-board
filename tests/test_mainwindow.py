"""Builds the real MainWindow on Qt's offscreen platform (no window appears, no
audio device is opened, no global hotkey is registered) and exercises the UI
plumbing: pad syncing, the metadata index, the mic-check pulse, the wheel guard."""
import time

import numpy as np
import pytest
import soundfile as sf
from conftest import said, unsay
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (QApplication, QLabel, QMenu, QScrollArea, QSlider, QVBoxLayout,
                               QWidget)

from soundboard import __version__
from soundboard.audio import engine
from soundboard.sounds import library
from soundboard.control import winkeys
from soundboard.sounds.library import SR, Config, SoundMeta
from soundboard.ui.window import mainwindow as main
from soundboard.ui.window import fitcontrol
from soundboard.ui.window.livedot import is_tab_live
from soundboard.ui.window.tabcontrol import TABS
from soundboard.ui.kit.wheelguard import no_wheel


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
    # (on the cable; this version ran last: no update restore point in every test)
    Config(sounds=sounds, mic_first=True, stats_version=__version__).save()
    w = main.MainWindow()
    # the loader thread writes the cache and prunes orphans: it must finish while the
    # temp paths are still patched in, never after the fixture is torn down
    w.soundctl._load_thread.join(15)
    assert not w.soundctl._load_thread.is_alive()
    w.load_triggers()   # now, not on its timer in the middle of a test
    yield w
    w.close()
    w.soundctl._load_thread.join(15)   # a test may have started another load (e.g. Undo) just now
    assert not w.soundctl._load_thread.is_alive()
    # a closed top-level window isn't freed by Qt; left alive, every later test's
    # theme / stylesheet change restyles all of them and the suite crawls
    from PySide6.QtCore import QEvent
    w.deleteLater()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)


def test_triggers_timer_during_start_up(qapp, app_dir, monkeypatch):
    """The splash pumps events while the window is built: a timer can run before
    __init__ ends (load_triggers' once threw AttributeError, _shut_down). So can the
    Discord check's answer on a slow start (_setup_app, CI 2026-10-11): it comes in at
    every pump here. Onion Watch loads during the build, behind the loading screen."""
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
                        lambda self: (calls.append(self), real(self)))

    building = []
    from soundboard.ui.window.windowbuild import WindowBuilder
    real_build = WindowBuilder._build_ui
    monkeypatch.setattr(WindowBuilder, "_build_ui",
                        lambda self: (building.append(self.mw), real_build(self))[1])

    def slow_pump():   # a slow start with the splash up
        time.sleep(0.08)
        for w in building:   # Discord isn't running: what its check says then
            w.bridge.discord.emit(([], None))
        qapp.processEvents()
    monkeypatch.setattr(main.splash, "pump", slow_pump)
    Config(sounds=[]).save()
    w = main.MainWindow()
    try:
        assert calls and not errors
        assert not w.triggers.pending   # loaded while the window was built
    finally:
        w.soundctl._load_thread.join(15)
        w.close()
        from PySide6.QtCore import QEvent
        w.deleteLater()
        qapp.sendPostedEvents(None, QEvent.DeferredDelete)


def test_deleting_the_window_with_the_download_bar_up(qapp, app_dir, monkeypatch):
    """Quitting mid-download: the download bar hides while the window is deleted, after
    the window's C++ side is gone. Fitting the window for it then raised RuntimeError
    and the crash reporter came up (the autouse guard fails the test on that)."""
    from PySide6.QtCore import QEvent
    for name in ("set_main_device", "set_mon_device", "set_mic_device"):
        monkeypatch.setattr(engine.Engine, name, lambda self, n, _k=name: None)
    monkeypatch.setattr(winkeys.Hotkeys, "register", lambda self, m: None)
    Config(sounds=[], mic_first=True, stats_version=__version__).save()
    w = main.MainWindow()
    w.soundctl._load_thread.join(15)
    w.show()
    w.download_bar.show()
    qapp.processEvents()
    assert w.download_bar.isVisible()
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
    window.soundctl.on_reorder("s1", 0)
    assert [m.id for m in window.cfg.sounds] == ["s1", "s0"]
    assert window.pads["s1"] is old["s1"]
    assert [p.meta.id for p in window.grid.pads] == ["s1", "s0"]


def test_mic_check_puts_no_bar_over_the_tabs(window):
    """Its sign is the mixer's own lit button and red mic label, never a bar on top."""
    window.on_mic_check(True)
    assert window.engine.mic_check
    assert all(getattr(window, n).isHidden() for n in window.TOP_BARS)
    window.on_mic_check(False)
    assert not window.engine.mic_check


def test_tick_runs_without_devices(window):
    for _ in range(31):        # crosses the once-a-second watchdog branch
        window.tickctl.tick()


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
    window.playctl._update_chips({})
    assert window.playing_row.isHidden() and not window._chips   # nothing playing
    monkeypatch.setattr(window.engine, "stop", stopped.append)
    window.playctl._update_chips({"s0": (0.2, False)})
    assert not window.playing_row.isHidden() and set(window._chips) == {"s0"}  # one: a chip
    window.playctl.select("s1")
    window.playctl._update_chips({"s0": (0.2, False), "s1": (0.1, False)})
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

    from soundboard.ui.sounds.linkbar import PLAY_ID
    live = {"s0": (0.2, False)}
    monkeypatch.setattr(window.engine, "playing", lambda: dict(live))
    monkeypatch.setattr(window.engine, "stop", lambda sid: live.pop(sid, None))
    window.searchctl.on_link_played("Search hit", np.zeros(4800, np.int16), 1.0)
    live[PLAY_ID] = (0.1, False)
    assert window.current == PLAY_ID
    window.playctl._update_chips(live)
    assert not window.playing_row.isHidden() and set(window._chips) == {"s0", PLAY_ID}
    window.playctl.select("s0")       # back on the board: pick the pad, stop it
    window.playctl.stop_current()
    assert window.current == PLAY_ID   # the player moved to what's still playing
    window.playctl._update_chips(live)
    # one sound left, the player shows it: its chip stays (the row going made it
    # look like ■ had stopped both)
    assert not window.playing_row.isHidden() and set(window._chips) == {PLAY_ID}
    window.playctl.select("s1")       # another pad picked while it plays: its chip stays
    window.playctl._update_chips(live)
    assert not window.playing_row.isHidden() and set(window._chips) == {PLAY_ID}


def test_a_stopped_web_song_leaves_the_player(window, monkeypatch):
    """A web search's song played, then another site picked: its card went, ■ only
    stopped it and its name stayed in the player bar for good."""
    import numpy as np

    from soundboard.ui.sounds.linkbar import PLAY_ID
    live = {}
    monkeypatch.setattr(window.engine, "playing", lambda: dict(live))
    monkeypatch.setattr(window.engine, "stop", lambda sid: live.pop(sid, None))
    window.searchctl.on_link_played("Trap Queen", np.zeros(4800, np.int16), 1.0)
    live[PLAY_ID] = (0.1, False)
    window.searchctl._on_site_picked("soundcloud")   # still playing: the player keeps it
    assert window.current == PLAY_ID
    window.playctl.stop_current()
    assert window.current is None and window.meta(PLAY_ID) is None
    assert window.np_name.text() == "Pick a sound"
    # over by itself, then another site picked: it goes too
    window.searchctl.on_link_played("Trap Queen", np.zeros(4800, np.int16), 1.0)
    window.searchctl._on_site_picked("youtube")
    assert window.current is None and window.meta(PLAY_ID) is None


def test_now_playing_label_lines_up_with_its_chips(window, qapp):
    """The row's "Now playing" label sat at the chips' top edge, higher than them."""
    window.show()
    window.tabs.setCurrentWidget(window.sounds_page)
    window.playctl.select("s1")
    window.playctl._update_chips({"s0": (0.2, False), "s1": (0.1, False)})
    qapp.processEvents()
    lbl = next(w for w in window.playing_row.findChildren(QLabel)
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


def test_a_squeezed_player_name_ends_in_dots_not_mid_letter(window, qapp):
    """At a narrower width the name's room is less than its widest: it was cut for the
    widest, so the label chopped it mid-letter with no "…"."""
    window.tabs.setCurrentWidget(window.sounds_page)
    window.resize(946, 876)
    window.show()
    qapp.processEvents()
    name = "Track 004 04-f816347157f0a9 a long downloaded song name"
    window._set_np_name(name)
    ns = window._name_seek
    ns.resize(ns.SEEK_MIN + ns.GAP + 80, ns.height())   # (as a narrow window leaves it)
    qapp.processEvents()
    shown, fm = window.np_name.text(), window.np_name.fontMetrics()
    assert shown.endswith("…") and shown != name
    assert fm.horizontalAdvance(shown) <= window.np_name.width()
    assert window.np_name.toolTip()   # the whole name is still in the tooltip


def test_no_pad_hint_line_under_the_player(window):
    window.tabs.setCurrentWidget(window.sounds_page)
    assert "click to play" not in said(window)


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


# (480 x 450: every tab on, including Chat, takes one more button on the rail than 420 holds)
@pytest.mark.parametrize("size", [(480, 450), (800, 600)])
def test_window_shrinks_and_still_fits(window, size, qapp):
    """The less important controls give way and what's left fits (every tab counts:
    the tab widget's minimum is the largest page's)."""
    window.show()                            # offscreen: nothing appears
    window.tabs.setCurrentWidget(window.sounds_page)
    window.resize(*size)
    window.fitctl._refit()
    assert not window.fitctl.is_mini()
    need = window._full.minimumSizeHint()
    assert need.width() <= size[0] and need.height() <= size[1]
    assert window.grid.isVisibleTo(window) and window.btn_pp.isVisibleTo(window)
    small = window.fitctl._fit.compact_count()
    assert small > 0
    window.resize(1800, 1000)                # and it comes back (tests have no real
    window.fitctl._refit()                          # fonts, so text is wider than in the app)
    assert window.fitctl._fit.compact_count() < small
    assert window.mixer.isVisibleTo(window) and window.np_name.isVisibleTo(window)


def test_long_download_list_folds_before_the_mini_player(window, qapp):
    """A queue of picks makes the download card tall: at 800x600 it folds (to its running
    row, then its summary line) to fit over the page, the window stays the whole board,
    and it opens again once the window is big enough. It's a card in the page's
    bottom-right corner, never in the page's layout."""
    from PySide6.QtTest import QTest
    from soundboard.ui.window import downloadbar as db
    window.show()
    window.tabs.setCurrentWidget(window.sounds_page)
    bar = window.download_bar
    links = [f"https://www.youtube.com/watch?v={c}" for c in "abcd"]
    window.resize(1400, 1000)
    window.fitctl._refit()
    bar.set_active(links[0], "One", "add", None, "Someone", 90)
    bar.set_queue([{"url": u, "title": "x", "kind": "add", "seconds": 60} for u in links[1:]])
    QTest.qWait(50)   # the bar asks for a refit once it's laid out
    assert bar._room == "open" and bar.scroll_area.isVisibleTo(bar)
    window.resize(800, 600)
    window.fitctl._refit()
    QTest.qWait(50)
    assert not window.fitctl.is_mini() and bar.isVisibleTo(window)
    box = window._tabs_box
    page = bar._in_host(box)
    assert bar.parentWidget().isAncestorOf(box)
    assert bar.geometry().bottom() < bar.parentWidget().height()
    assert bar.y() >= page.top()                                       # it fits the page
    assert bar.geometry().right() == page.right() - db.CARD_MARGIN     # in the corner
    need = window._full.minimumSizeHint()
    assert need.height() <= 600
    window.resize(1400, 1000)
    window.fitctl._refit()
    QTest.qWait(50)
    assert bar._room == "open" and bar.scroll_area.isVisibleTo(bar)
    bar._clear_and_hide()


def test_a_failed_link_after_a_few_adds_folds_the_bar_not_the_window(window, qapp):
    """A link failing after a few added ones gives the bar a long list (the failed row,
    then the added ones). It folds for the room, and the window stays the whole board:
    the folded bar's old height used to stay counted, so nothing seemed to fit and a
    roomy window turned into the mini player, the search box gone with it."""
    from PySide6.QtTest import QTest
    window.show()
    window.tabs.setCurrentWidget(window.sounds_page)
    bar = window.download_bar
    window.resize(1100, 600)
    window.fitctl._refit()
    links = [f"https://www.youtube.com/watch?v={c}" for c in "abcde"]
    for u in links[:4]:
        bar.set_active(u, "Added one", "add", None, "Someone", 60)
        bar.set_done(u, "add", True)
        QTest.qWait(1100)   # each end holds a second for its flash
    bar.set_active(links[4], "Cut off", "add", None, "Someone", 60)
    bar.set_failed(links[4], "add")
    bar.set_done(links[4], "add", False)
    QTest.qWait(1200)   # the flash, then the bar asks for a refit once it's laid out
    assert not window.fitctl.is_mini()
    assert window.search.isVisibleTo(window) and bar.isVisibleTo(window)
    assert window._full.minimumSizeHint().height() <= 600
    bar._clear_and_hide()


def test_tiny_window_becomes_mini_player_and_back(window, qapp):
    """Too small to use: just the player (plus the pads if it's tall enough), and the
    whole window again, pads back in the Sounds tab, once it's big enough."""
    assert window.minimumSize().width() <= 260 and window.minimumSize().height() <= 120
    window.show()
    window.tabs.setCurrentWidget(window.sounds_page)
    window.playctl.select("s1")
    window.resize(260, 120)
    window.fitctl._refit()
    assert window.fitctl.is_mini()
    assert window.mini_pp.isVisibleTo(window) and window.mini_air.isVisibleTo(window)
    assert window.mini_name.text() == "Airhorn"
    assert not window.grid.isVisibleTo(window)    # no room for pads
    window.resize(540, 180)                        # short: one-line rows, not cards
    window.fitctl._refit()
    assert window.fitctl.is_mini() and window.grid.isVisibleTo(window) and window.grid.slim
    assert window.pads["s0"].height() <= 30
    window.resize(360, 700)                        # tall and narrow: the pads come along
    window.fitctl._refit()
    assert window.fitctl.is_mini() and window.grid.isVisibleTo(window) and not window.grid.slim
    window.mini_air.setChecked(False)              # one switch, both buttons
    assert not window.btn_air.isChecked() and window.engine.sending is False
    window.btn_air.setChecked(True)
    assert window.mini_air.isChecked()
    window.resize(1100, 760)
    window.fitctl._refit()
    assert not window.fitctl.is_mini()
    assert window._pads_scroll.parentWidget().parentWidget() is window.sounds_page.parentWidget() \
        or window.grid.isVisibleTo(window)
    assert window._pads_home[0].indexOf(window._pads_scroll) == window._pads_home[1]


def test_refit_leaves_widgets_alone_when_nothing_crosses_an_edge(window, qapp):
    """Resizing only touches the steps at the edge it crossed, so a border drag
    doesn't show and hide half the window on every mouse move (it flashed)."""
    window.show()
    window.resize(930, 700)   # 950-932 held the cards / list switch's own edge
    window.fitctl._refit()
    flips = []
    orig = [s[2] for s in window.fitctl._fit.steps]
    window.fitctl._fit.steps = [(p, a, (lambda c, f=f, i=i: (flips.append((i, c)), f(c))))
                         for i, ((p, a, _), f) in enumerate(zip(window.fitctl._fit.steps, orig))]
    for w in range(930, 916, -2):                  # small moves, no edge crossed (914:
        # the radio's Send button at its narrowest)
        window.resize(w, 700)
        window.fitctl._refit()
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
    window.fitctl._refit()
    page = window.tabs.widget([t for t, _ in TABS].index("Radio"))
    assert page.isAncestorOf(window.radio)
    small = page.minimumSizeHint().height()
    for _ in range(2):
        window.resize(1920, 1040)                  # maximize...
        window.fitctl._refit()
        qapp.processEvents()
        assert not window.radio.genre_box.isHidden()   # (its tab isn't the one showing)
        assert page.minimumSizeHint().height() < small + 120
        assert window._full.minimumSizeHint().height() <= 720
        window.resize(1180, 720)                   # ...and restore
        window.fitctl._refit()
        qapp.processEvents()
        assert not window.fitctl.is_mini() and window.tabs.isVisibleTo(window)


def test_flow_asks_for_its_lines_at_its_width_not_one_chip_a_line(qapp):
    from PySide6.QtWidgets import QPushButton, QWidget

    from soundboard.ui.kit.panel import Flow
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
    window.editctl._rerender(m)
    assert window.pads["s0"].state == "rendering" and "s0" not in window.audio
    assert process_events(qapp, lambda: "s0" in window.audio, 15)
    assert abs(len(window.audio["s0"]) - before / 2) < 10
    assert window.pads["s0"].state == "ready"
    assert abs(m.duration - before / 2 / SR) < 0.01


def test_saving_effects_again_stops_the_render_still_going(qapp, window, monkeypatch):
    from conftest import process_events
    assert process_events(qapp, lambda: "s0" in window.audio, 10)
    m = window.meta("s0")
    before = len(window.audio["s0"])
    stopped = []
    from soundboard.ui.window import editcontrol
    real = editcontrol.load_sound

    def slow(meta, cancel=None, **_k):
        if meta.fx.get("speed") == 2.0:   # the first save: still going when the next comes
            deadline = time.monotonic() + 10
            while not cancel() and time.monotonic() < deadline:
                time.sleep(0.01)
            stopped.append(cancel())
            raise main.library.Cancelled
        return real(meta, cancel)
    monkeypatch.setattr(editcontrol, "load_sound", slow)
    m.fx = {"speed": 2.0}
    window.editctl._rerender(m)
    m.fx = {"speed": 0.5}
    window.editctl._rerender(m)
    assert process_events(qapp, lambda: "s0" in window.audio and stopped, 15)
    assert stopped == [True] and abs(len(window.audio["s0"]) - before * 2) < 10


def test_mainwindow_live_speed_button_drives_the_engine(window):
    window.speed_btn.set_values(0.5, 4, False)
    e = window.engine
    assert (e.sound_speed, e.sound_pitch, e.sound_keep_pitch) == (0.5, 4, False)
    window.speed_btn.reset()
    assert (e.sound_speed, e.sound_pitch) == (1.0, 0.0)


def test_nightcore_preset_sets_the_speed_and_undoes_it(window):
    b, e = window.speed_btn, window.engine
    b.set_values(1.0, 2, True)
    b.fx_presets["Nightcore"].click()                        # 1.3x, the pitch rises with it
    assert (e.sound_speed, e.sound_pitch, e.sound_keep_pitch) == (1.3, 0, False)
    assert e.sound_fx == {"bass": 3} and b.fx_presets["Nightcore"].isChecked()
    b.speed.set_value(1.5)
    b._edited()                                              # moved off it: not lit
    assert not b.fx_presets["Nightcore"].isChecked()
    b.speed.set_value(1.3)
    b._edited()
    b.fx_presets["Nightcore"].click()                        # off: back to before it
    assert (e.sound_speed, e.sound_pitch, e.sound_keep_pitch) == (1.0, 2, True)
    assert e.sound_fx == {}


def test_a_live_stream_gets_nightcore_as_pitch(qapp):
    from soundboard.ui.sounds.speedpitch import SpeedPitchButton
    b = SpeedPitchButton("radio")
    b.fx_presets["Nightcore"].click()                        # no speed: +5 st instead
    assert b.values()[:2] == (1.0, 5) and b.fx_presets["Nightcore"].isChecked()
    b.fx_presets["Slowed + reverb"].click()
    assert b.values()[:2] == (1.0, -4) and not b.fx_presets["Nightcore"].isChecked()


def test_live_effects_drive_the_engine(window):
    b, e = window.speed_btn, window.engine
    assert e.sound_fx == {} and "FX" not in b.text()
    b.fx["bass"].set_value(9)
    b.fx["bass"].changed.emit()
    assert e.sound_fx == {"bass": 9} and "FX" in b.text()
    b.fx_presets["Bass boosted"].click()                     # a preset replaces them all
    assert e.sound_fx == {"bass": 12} and b.fx_presets["Bass boosted"].isChecked()
    b.fx_presets["Bass boosted"].click()                     # clicked again: as before it
    assert e.sound_fx == {"bass": 9}
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
    assert b.pop.height() >= closed                          # room for the rev meter
    assert b.red_box.geometry().bottom() < b.red_box.parentWidget().height()
    b.redline.click()
    qapp.processEvents()
    assert b.pop.height() == closed                          # and gives it back
    b.pop.hide()


def test_every_tab_has_its_own_label(window):
    texts = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    assert texts == [t for t, _ in TABS] and len(set(texts)) == len(texts)
    assert window.tabs.tabToolTip(2) == ""   # the name says it: no hover tip


def test_the_tabs_are_a_rail_down_the_left(window, qapp):
    """Icons only (no hover tips); the button at the bottom opens it out to the names
    and the onion (saved); a narrow window shuts it again."""
    window.show()
    window.resize(1200, 760)
    window.fitctl._refit()
    rail = window.rail
    assert window.tabs.tabBar().isHidden()   # the rail shows the tabs, not the bar
    assert rail.is_open() and window.cfg.sidebar_open   # open by default: names, not just icons
    rail.toggle.click()
    assert not rail.is_open() and rail.width() == main.sidebar.SHUT_W
    b = rail.buttons[1]
    # shut, the icon is all there is: the hover tip gives its name and its Ctrl+number
    assert b.text() == "" and b.toolTip().startswith("Radio  (Ctrl+") and \
        b.accessibleName() == "Radio"
    assert not rail.buttons[0].icon().isNull()
    assert rail.buttons[0].isChecked() == (window.tabs.currentIndex() == 0)
    assert window.wordmark.isHidden()
    rail.toggle.click()
    assert rail.is_open() and window.cfg.sidebar_open
    assert b.text().strip() == "Radio" and b.toolTip() == ""
    assert not window.wordmark.isHidden() and not window.tagline.isHidden()
    rail.buttons[5].click()
    assert window.tabs.currentIndex() == rail.buttons[5].index and rail.buttons[5].isChecked()
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
    window.tickctl.tick()
    assert not is_tab_live(tabs, i)
    playing["s0"] = (0.3, False)
    window.tickctl.tick()
    assert is_tab_live(tabs, i) and tabs.tabToolTip(i).startswith("● ON")
    playing["s0"] = (0.3, True)                  # paused: not live
    window.tickctl.tick()
    assert not is_tab_live(tabs, i)
    playing.clear()
    playing["__test__"] = (0.1, False)           # the mic test's playback isn't a sound
    window.tickctl.tick()
    assert not is_tab_live(tabs, i) and not tabs.tabToolTip(i).startswith("●")
    from soundboard.ui.sounds.linkbar import PLAY_ID  # a web search's Play lights it too
    playing.clear()
    playing[PLAY_ID] = (0.1, False)
    window.tickctl.tick()
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
    window.transctl._show_transport(window.engine.playing())
    assert not bar.isHidden()
    playing["s0"] = (0.3, True)                      # paused: still there to resume
    window.transctl._show_transport(window.engine.playing())
    assert not bar.isHidden()
    playing.clear()
    playing["__test__"] = (0.1, False)               # the mic test's playback isn't a sound
    window.transctl._show_transport(window.engine.playing())
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
    monkeypatch.setattr(window.routectl, "_main_name", lambda: "CABLE Input")
    e = window.engine
    assert window.btn_air.isChecked() and e.sending
    window.btn_air.click()
    # your plain mic still goes out (tests/test_mic_only.py) unless it isn't sent
    assert not e.sending and "only your mic" in window.btn_air.accessibleName()
    window.routectl.on_mic_toggle(False)
    assert "Muted" in window.btn_air.accessibleName()
    out = np.ones((64, 2), np.float32)
    e._main(out, 64)
    assert not out.any()
    window.set_sending(True)
    assert e.sending and window.btn_air.isChecked()
    assert "others hear" in window.btn_air.accessibleName()


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
    """Big pads in a narrow window get narrower instead of running off the edge, a row
    of them stretches to the right edge, and the mini player puts two a row while
    they're still a usable size."""
    window.show()
    window.set_pad_width(240)
    window.resize(1000, 700)
    window.fitctl._refit()
    near_240_to_the_edge(window)
    window.resize(270, 600)
    window.fitctl._refit()
    qapp.processEvents()
    scroll = window._pads_scroll
    assert window.fitctl.is_mini() and scroll.isVisibleTo(window)
    assert scroll.horizontalScrollBar().maximum() == 0
    assert window.grid.width() <= scroll.viewport().width()
    a, b = window.pads["s0"], window.pads["s1"]
    assert a.geometry().right() <= scroll.viewport().width()
    assert a.y() == b.y() and a.width() < 240          # two a row
    window.resize(1000, 700)
    window.fitctl._refit()
    assert not window.fitctl.is_mini()
    near_240_to_the_edge(window)


def near_240_to_the_edge(window):
    """About the picked size, stretched so the row of pads ends at the right edge."""
    grid = window.grid
    cols, w = grid._shape
    assert 240 * 0.8 <= w < 240 * 2 and window.pads["s0"].width() == w
    m = grid.grid.contentsMargins()
    right = m.left() + cols * w + (cols - 1) * grid.grid.spacing()
    assert grid.width() - m.right() - right < cols   # no strip left over on the right


@pytest.mark.windows   # Segoe UI's text widths: with another font the columns fit side by side
def test_setup_stacks_long_controls_without_sideways_scrolling(window, qapp):
    """Long translated controls must fit the viewport, then unfold at a wider size."""

    window.rail.set_open(False)   # the widths below assume the shut rail
    window.cfg.route = "mic"
    window.statusctl._update_flow()
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
            window.fitctl._refit()
        assert not window.fitctl.is_mini()
        assert window.setup_page.horizontalScrollBar().maximum() == 0
        assert window._setup_stacked == (width == 900)


def test_an_empty_board_shrinks_with_the_window(window, qapp):
    """No sounds, then a small window: the "drop sound files here" bunny came along at
    the big window's width, so the mini player showed an empty void you had to
    scroll sideways across."""
    window.cfg.sounds.clear()
    window._rebuild_pads()
    window.show()
    window.resize(1400, 800)
    window.fitctl._refit()
    window.resize(265, 520)
    window.fitctl._refit()
    qapp.processEvents()
    scroll = window._pads_scroll
    assert window.fitctl.is_mini() and window.grid.empty.isVisibleTo(window)
    assert window.grid.width() <= scroll.viewport().width()
    assert window.grid.empty.geometry().right() <= scroll.viewport().width()


def test_the_whole_window_comes_back_after_the_mini_player(window, qapp):
    """Out of the mini player at a size the whole window fits (its hidden page's
    sizes went stale, and it stayed the mini player)."""
    window.show()
    window.tabs.setCurrentWidget(window.sounds_page)
    window.resize(1000, 700)
    window.fitctl._refit()
    for size in ((300, 600), (430, 600), (520, 600)):
        window.resize(*size)
        window.fitctl._refit()
    assert not window.fitctl.is_mini()


@pytest.mark.windows   # Segoe UI's text widths
def test_every_tab_stays_the_whole_window_down_to_the_mini_size(window, qapp):
    """The icon-only tabs' padding alone needed ~480 px, so a window the rest fits
    (480 px is a 600 px window at 125 %) turned into the mini player."""
    from soundboard.ui.window.fitcontrol import MINI_SIZE

    window.show()
    window.resize(1000, 700)
    window.fitctl._refit()
    for page in (window.sounds_page, window.radio_page, window.apps, window.voice,
                 window.setup_page):
        window.tabs.setCurrentWidget(page)
        window.resize(MINI_SIZE.width() + 10, 700)
        window.fitctl._refit()
        assert not window.fitctl.is_mini(), type(page).__name__
        window.resize(1000, 700)
        window.fitctl._refit()


def test_the_mini_player_shows_the_pads_whatever_is_in_the_search_box(window, qapp):
    """A web search's words stay in the search box, which also filters the pads: the
    mini player (no search box) was blank. And a board with every pad filtered out
    says so instead of showing nothing."""
    from soundboard.ui.kit.widgets import PadGrid

    window.show()
    window.tabs.setCurrentWidget(window.apps)
    window.resize(1000, 700)
    window.fitctl._refit()
    window.search.setText("idiot test")             # matches none of the sounds
    assert not any(p.isVisibleTo(window) for p in window.grid.pads)
    window.tabs.setCurrentWidget(window.sounds_page)
    qapp.processEvents()
    assert window.grid.empty.isVisibleTo(window)
    assert window.grid.empty_text.text() == PadGrid.NO_MATCH
    window.tabs.setCurrentWidget(window.apps)
    window.resize(360, 700)
    window.fitctl._refit()
    assert window.fitctl.is_mini()
    assert all(p.isVisibleTo(window) for p in window.grid.pads)
    assert not window.grid.empty.isVisibleTo(window)
    window.resize(1000, 700)
    window.fitctl._refit()
    assert not window.fitctl.is_mini()
    assert window.search.text() == "idiot test"     # still filtering the whole window
    assert not any(p.property("filtered") is False and p.isVisibleTo(window)
                   for p in window.grid.pads)


@pytest.mark.parametrize("theme_name", ["Dark", "Retro 98"])
def test_restoring_a_large_window_keeps_search_results(window, qapp, theme_name):
    """Maximize/restore must keep the full app and the selected search view."""
    from soundboard.ui.kit import theme
    from soundboard.online import ytdl

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
            window.fitctl._refit()
            qapp.processEvents()
            assert not window.fitctl.is_mini()
            window.showNormal()
            qapp.processEvents()
            assert not window.fitctl.is_mini()
            assert window.ytresults.isVisibleTo(window)
            assert window.tabs.isVisibleTo(window)
    finally:
        theme.apply(qapp, old_theme)


@pytest.mark.parametrize("theme_name", ["Dark", "Retro 98", "Comic Sans"])
def test_card_titles_and_the_typed_percent_fit_the_themes_font(qapp, theme_name):
    """Both used to size themselves before the theme's font arrived with its style
    sheet: a title's second line lost its descenders, "1000 %" didn't fit Tahoma."""
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from soundboard.ui.kit import theme
    from soundboard.ui.kit.panel import VolumeControl
    from soundboard.ui.sounds.ytsearch import ClampLabel

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
    window.fitctl._refit()
    qapp.processEvents()
    if not window.fitctl.is_mini():
        assert window._pads_scroll.height() >= window.pads["s0"].height()


def test_the_mini_player_keeps_the_pads_while_one_row_fits(window, qapp):
    """A wide, short window (big pads, 125 % scaling) showed the mini player with
    nothing above it: the pads only came along when two rows fit."""
    window.show()
    window.tabs.setCurrentWidget(window.sounds_page)
    window.set_pad_width(240)
    window.resize(1100, 330)
    window.fitctl._refit()
    size = window._pages.size()
    assert window.fitctl.is_mini()
    fit = window.fitctl
    assert fit._mini_row(size) <= fit._mini_pad_room(size) < 2 * fit._mini_row(size)
    assert window.grid.isVisibleTo(window)


def test_the_window_shows_which_version_is_running(window, monkeypatch):
    from soundboard import __version__
    from soundboard.ui.window import mainwindow
    assert window.windowTitle() == "Onion Board"   # no version in the title bar
    # the rail: who made it and the version, no "from source"
    assert window.tagline.text() == f"by Onion Alien · v{__version__}"
    assert "from source" in window.wordmark.toolTip()
    window.on_mic_check(True)          # the red banner says it; the title stays the app's name
    assert window.windowTitle() == "Onion Board"
    window.on_mic_check(False)
    assert window.windowTitle() == "Onion Board"
    monkeypatch.setattr("sys.frozen", True, raising=False)
    assert mainwindow.version_text() == __version__     # the installed app: just the number


def test_an_empty_board_has_no_status_row(window):
    """No message, no row: the mixer sits at the bottom with only the margin under it,
    and a notice is a toast over the page, never a row of its own."""
    window.resize(1200, 800)
    window.show()
    QApplication.processEvents()
    gap = window._full.height() - window.mixer.geometry().bottom()
    assert gap <= 12
    window.toast("1 audio drop-out since start", "warn")
    QApplication.processEvents()
    assert window._full.height() - window.mixer.geometry().bottom() == gap
    unsay(window)


def test_ctrl_v_pastes_a_copied_picture_on_the_selected_pad(window):
    from PySide6.QtGui import QColor, QImage
    window.playctl.select("s1")
    QApplication.clipboard().setText("just words")
    window.padctl.paste_picture()
    assert not window.meta("s1").image and "copy a picture first" in said(window)
    img = QImage(200, 120, QImage.Format_RGB32)
    img.fill(QColor("#ff00ff"))
    QApplication.clipboard().setImage(img)
    window.padctl.paste_picture()
    pic = window.meta("s1").image
    assert pic and library.Path(pic).is_file() and not window.meta("s0").image
    assert "Airhorn" in said(window)
    window.selection.on_pick("s0", False)   # picked pads win over the selected one
    window.selection.on_pick("s1", False)
    window.padctl.paste_picture()
    assert window.meta("s0").image and window.meta("s1").image != pic
    assert not library.Path(pic).exists()   # the old picture's file is gone


def test_ctrl_v_adds_a_clip_copied_in_the_clip_editor_as_a_sound(window):
    import numpy as np

    from soundboard.ui.apps import clipeditor
    n = len(window.cfg.sounds)
    clipeditor.set_clipboard(np.zeros((int(0.23 * 48000), 2), np.float32))   # even silence
    try:
        window.padctl.paste_picture()
        assert len(window.cfg.sounds) == n + 1
        assert window.cfg.sounds[-1].name.startswith("Clip ")
        QApplication.clipboard().setText("words")      # copied something since: not again
        window.padctl.paste_picture()
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

    from soundboard.sounds.library import SoundMeta
    from soundboard.ui.kit.widgets import Pad, PadGrid

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


def test_a_top_bar_and_a_row_of_playing_sounds_dont_force_the_mini_player(window):
    """Both used to be as wide as all their text: a banner ~780 px, four
    overlapping sounds' chips ~900 px, so a window a bit narrower became the mini
    player in the middle of a session. The bar's words and the chips wrap onto more
    lines."""
    window.show()
    window.tabs.setCurrentWidget(window.sounds_page)
    window.resize(800, 600)
    window.fitctl._refit()
    assert not window.fitctl.is_mini()
    window.urgent_bar.set_message("Discord's noise suppression (Krisp) is wiping out your "
                                  "sounds. Set Noise Suppression to None. " * 3)
    window.urgent_btn.setText("Fix Discord")
    window.urgent_bar.show()
    ids = list(window.pads)
    window.playctl._queue[:] = ids * 3
    window.playctl._update_chips(dict.fromkeys(ids, (0.0, False)))
    window.fitctl._refit()
    assert window.playing_row.isVisibleTo(window)
    assert not window.fitctl.is_mini()
    assert window.urgent_bar.width() <= 800 and window.urgent_bar.text()
    # every playing sound keeps its chip (to stop it): the row wraps instead
    assert set(window._chips) == set(ids)
    row = window.playing_row.rect()
    for chip in window._chips.values():
        assert chip.isVisibleTo(window) and row.contains(chip.geometry())


def test_clamp_label_wraps_once_per_text_width_and_font(qapp):
    """Cards repaint on every hover and scroll: the wrapped lines are kept until the
    text, width or font changes."""
    from soundboard.ui.sounds.ytsearch import ClampLabel
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
    window.langctl._offer_language()
    assert window.lang_bar.isVisibleTo(window)
    assert window.lang_bar.text() == ("Onion Board gibt es auch auf Deutsch. Du kannst die "
                                       "Sprache jederzeit unter Einstellungen → Aussehen → "
                                       "Sprache ändern.")
    assert window.lang_btn.text() == "Zu Deutsch wechseln"
    window.lang_btn.click()
    assert window.cfg.language == "de" and restarts == [1]
    assert not window.lang_bar.isVisibleTo(window)
    window.langctl._offer_language()                     # picked: never offered again
    assert not window.lang_bar.isVisibleTo(window)


def test_turning_down_the_language_offer_is_remembered(window, monkeypatch):
    from soundboard import i18n
    monkeypatch.setattr(i18n, "windows_language", lambda: "ja-JP")
    window.langctl._offer_language()
    assert window.lang_bar.isVisibleTo(window) and window.lang_btn.text() == "日本語に切り替える"
    window.lang_hide.click()
    assert not window.lang_bar.isVisibleTo(window) and window.cfg.language == ""
    window.langctl._offer_language()
    assert not window.lang_bar.isVisibleTo(window)


def test_no_language_offer_on_an_english_windows(window, monkeypatch):
    from soundboard import i18n
    monkeypatch.setattr(i18n, "windows_language", lambda: "en-GB")
    window.langctl._offer_language()
    assert not window.lang_bar.isVisibleTo(window)


def test_setup_not_done_yet_is_one_orange_step_not_red_crosses(window, monkeypatch):
    """Cable route, no cable, mic closed: the card's two lines say what's still to
    do in the warn colour; the red cross is for things that are wrong."""
    from soundboard.audio import engine as eng
    from soundboard.ui.kit import theme
    # the real device list: a PC with a virtual cable installed isn't "no cable"
    monkeypatch.setattr(eng, "virtual_outputs", lambda: [])
    w = window
    w.cfg.route = "cable"
    w.statusctl._update_flow()
    assert w.statusctl.setup_state == "missing"
    text = w.flow_mic.text() + w.flow_out.text()
    from soundboard.ui.kit import icons
    dpr = w.flow_out.devicePixelRatioF()
    assert icons.inline("cross", theme.status("error"), dpr=dpr) not in text
    assert "after the setup below" in w.flow_mic.text()
    assert "not installed yet" in w.flow_out.text()


def test_mic_card_status_uses_painted_marks_on_one_line(window, monkeypatch):
    """The mic card's status lines show the app's own tick and cross (not the font's
    ✓ / ✗), and "not running" fits beside "Into your mic" at 1180x720."""
    from PySide6.QtWidgets import QApplication

    from soundboard.mic import directmic as dm
    from soundboard.audio import engine as eng
    from soundboard.ui.kit import theme
    from soundboard.ui.kit import icons
    w = window
    dead = {"on": True}
    monkeypatch.setattr(dm, "status", lambda name=None: "ready")
    monkeypatch.setattr(eng, "virtual_outputs", lambda: [])
    monkeypatch.setattr(type(w.engine), "effect_alive", lambda self: True)
    monkeypatch.setattr(w.micctl, "_direct_not_running", lambda: dead["on"])
    monkeypatch.setattr(w.engine, "main_stream", object())
    w.cfg.route = "mic"
    w.cfg.mic_device = "Microphone (Example Gaming Headset)"
    w.resize(1180, 720)
    w.show()
    w.tabs.setCurrentWidget(w.setup_page)
    w.statusctl._update_flow()
    for _ in range(6):
        QApplication.processEvents()
    out = w.flow_out
    assert "✗" not in out.text() and "✓" not in w.flow_mic.text() + out.text()
    dpr = out.devicePixelRatioF()
    assert icons.inline("cross", theme.status("error"), dpr=dpr, font=out.font()) in out.text()
    assert out.height() < 2 * out.fontMetrics().lineSpacing()   # one line
    dead["on"] = False
    w.statusctl._update_flow()
    assert icons.inline("check", theme.status("ok"), dpr=dpr, font=out.font()) in out.text()


def test_sounds_toolbar_dropdown_menus_open_with_gap(window, qapp):
    """Dropdown menus on the sound page toolbar open with a short pixel gap from their button."""
    from soundboard.ui.kit.widgets import DropdownMenu
    from soundboard.ui.kit.wheelguard import DROP_GAP
    w = window
    w.show()
    for _ in range(4):   # laid out first, as before any real click
        qapp.processEvents()
    for btn in (w.btn_more, w.btn_keys, w.btn_view):
        menu = btn.menu()
        assert isinstance(menu, DropdownMenu)
        btn.showMenu()
        qapp.processEvents()
        try:
            bottom = btn.mapToGlobal(btn.rect().bottomLeft()).y()
            assert menu.y() - bottom >= DROP_GAP
        finally:
            menu.close()
            qapp.processEvents()



@pytest.mark.parametrize("size", [(800, 600), (1180, 720)])
def test_audit_normal_navigation_returns_from_mini(window, qapp, size):
    window.show()
    window.resize(360, 320)
    qapp.processEvents()
    assert window.fitctl.is_mini()
    window.resize(*size)
    for _ in range(3):
        qapp.processEvents()
    for i in range(window.tabs.count()):
        window.tabs.setCurrentIndex(i)
        window.fitctl._refit()
        assert not window.fitctl.is_mini()
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
    assert not window.fitctl.is_mini() and window.tabs.currentWidget() is window.setup_page


def test_audit_expanded_sidebar_labels_status(window, qapp):
    window.show()
    window.resize(1180, 720)
    window.rail.set_open(True)
    qapp.processEvents()
    for button in (window.btn_air, window.mode_btn, window.stop_btn, window.pill):
        if not button.isHidden():
            assert button.text() and button.accessibleName()


def test_audit_setup_cards_fit_the_first_screen_open(window, qapp):
    """Setup on a 1080p screen: your mic, who's listening, Devices (its boxes showing)
    and the EQ all start on the first screen, open: nothing folds away."""
    window._setup_cols.parentWidget().setMaximumWidth(1500)   # (the offscreen font)
    window.show()
    window.resize(1920, 1080)
    window.tabs.setCurrentWidget(window.setup_page)
    for _ in range(5):
        qapp.processEvents()
        window.fitctl._refit()
    view = window.setup_page.viewport()
    for card in (*window._setup_top, window.dev_card, window.eq_card):
        top = card.mapTo(view, QPoint()).y()
        assert 0 <= top < view.height()
    assert window.cb_route.isVisible() and window.eq.isVisible()
    assert not hasattr(window, "btn_rec")   # the local mix test card is gone


def test_setup_columns_side_by_side_and_stack_when_narrow(window, qapp):
    """Wide: your mic and who's listening side by side and the same height, Devices and
    Connect your chat under your mic, the EQ under who's listening. Narrow: one column,
    mic, who's listening, then the rest. Never a sideways scroll bar."""
    window.themectl.apply_theme("Dark")
    body = window._setup_cols.parentWidget()
    body.setMaximumWidth(1500)   # the offscreen fallback font needs wider columns
    window.tabs.setCurrentWidget(window.setup_page)
    window.show()
    mic, dest = window.how_title.parentWidget(), window.dest_panel.parentWidget()
    cards = (window.dev_card, window.helpcard, window.eq_card)
    for width, height in ((1920, 1080), (1180, 720), (800, 600), (1920, 1080)):
        window.resize(width, height)
        for _ in range(5):
            qapp.processEvents()
            window.fitctl._refit()
        assert not window.fitctl.is_mini()
        assert window.setup_page.horizontalScrollBar().maximum() == 0
        shown = [w for w in (mic, *cards) if not w.isHidden()]
        if not window._setup_stacked:
            assert mic.y() == dest.y() and mic.geometry().right() < dest.x()
            assert mic.height() == dest.height()   # the top cards line up
            for a, b in window._setup_pairs:   # each pair: same top, same bottom
                assert a.y() == b.y() and a.height() == b.height()
            for w, over in ((window.dev_card, mic), (window.helpcard, mic),
                            (window.eq_card, dest)):   # each as wide as the card above
                if not w.isHidden():
                    assert w.x() == over.x() and w.width() == over.width()
                    assert w.y() > over.geometry().bottom()
        else:
            tops = [w.mapTo(body, QPoint()).y() for w in (mic, dest, *shown[1:])]
            assert tops == sorted(tops) and len(set(tops)) == len(tops)
        card = window.dev_card
        for combo in (window.cb_mon, window.cb_mic, window.cb_route):
            assert card.rect().contains(combo.mapTo(card, combo.rect().bottomRight()))
    assert not window._setup_stacked   # (at 1920)
    window.resize(800, 600)
    for _ in range(5):
        qapp.processEvents()
        window.fitctl._refit()
    assert window._setup_stacked


def test_setup_two_columns_never_shut_the_rail(window, qapp):
    """Two columns that only fit with the rail shut: Setup stacks them instead. The
    page asked for their width and the narrow-window step shut the rail for it (open
    it, and it shut again)."""
    window.themectl.apply_theme("Dark")
    window.tabs.setCurrentWidget(window.setup_page)
    window.resize(1180, 720)
    window.show()
    rail = window.rail
    for _ in range(2):
        rail.set_open(False)
        qapp.processEvents()
        rail.set_open(True)
        qapp.processEvents()
        assert rail.is_open()
        assert window._setup_stacked
        assert window.setup_page.horizontalScrollBar().maximum() == 0


def test_drop_target_keeps_the_full_board_width(window, qapp):
    window.show()
    window.tabs.setCurrentIndex(0)
    window.resize(1180, 720)
    qapp.processEvents()
    rect = window.grid.drop_area()
    margins = window.grid.grid.contentsMargins()
    assert rect is not None and rect.height() >= 90
    assert rect.width() == window.grid.width() - margins.left() - margins.right() - 4


def test_toolbar_tabs_and_pads_share_their_edges(window, qapp):
    """The toolbar, the first category tab and the first pad start on one line, and
    the toolbar ends where a full row of pads does (the pads widen to fill the row)."""
    from PySide6.QtTest import QTest
    window.show()
    window.tabs.setCurrentIndex(0)
    g = window.grid
    m = g.grid.contentsMargins()
    for w in (1700, 1275, 1003, 777):
        window.resize(w, 760)
        QTest.qWait(80)
        x = lambda wid, px=0: wid.mapTo(window, QPoint(px, 0)).x()
        bar, tabs = window.sounds_toolbar, window.catctl.cat_tabs
        assert x(bar) == x(tabs, tabs.tabRect(0).x()) == x(g.pads[0]), w
        cols, pw = g._shape
        row_end = x(g) + m.left() + cols * pw + g.grid.horizontalSpacing() * (cols - 1)
        assert x(bar) + bar.width() == row_end, w
        assert 0 <= g.slack() < cols, w


def test_pads_keep_their_height_when_a_row_loses_one(window, qapp):
    """A row losing a pad as the window narrows keeps the pads' height: it followed
    the width, so each re-wrap jolted every row below."""
    from PySide6.QtTest import QTest
    window.show()
    window.tabs.setCurrentIndex(0)
    g = window.grid
    window.resize(1700, 760)
    QTest.qWait(80)
    h, seen = g.pads[0].height(), set()
    for w in range(1700, 1000, -7):
        window.resize(w, 760)
        qapp.processEvents()
        seen.add(g._shape[0])
        assert g.pads[0].height() == h, w
    assert len(seen) > 2   # it did re-wrap, more than once


def test_a_long_name_stays_on_one_line(window, qapp):
    """A name too long for the pad is cut with "…" on one line (hover shows it all):
    wrapped, it jumped between one line and two as a resize changed the width."""
    from PySide6.QtCore import QRectF
    pad = window.grid.pads[0]
    pad.meta.name = "Goldeneye 007 (N64) Rap Beat - Straight Outta Hyrule"
    _f, flags, text = pad._fit_name(QRectF(0, 0, 120, 60))
    assert text.endswith("…") and "\n" not in text and pad.name_cut
    assert flags & Qt.AlignmentFlag.AlignTop
    pad.meta.name = "Boom"
    assert pad._fit_name(QRectF(0, 0, 120, 60))[2] == "Boom" and not pad.name_cut


def test_the_search_box_never_grows_as_the_window_narrows(window, qapp):
    """Narrowing the window drops the card size and the toolbar buttons' words one by
    one; the room they gave up went to the search box, so at some widths a narrower
    window had a wider box (and it shrank again a few pixels later). Swept both ways
    in 5 px steps, the box only ever gets wider with the window."""
    from soundboard.ui.window.fitcontrol import SEARCH_MIN_W
    window.show()
    window.tabs.setCurrentIndex(0)
    seen = []
    for wd in [*range(1500, 659, -5), *range(660, 1501, 5)]:
        window.resize(wd, 860)
        qapp.processEvents()
        window.fitctl._refit()
        seen.append((window.width(), window.search.width()))
    for (w1, s1), (w2, s2) in zip(seen, seen[1:]):
        if w2 < w1:
            assert s2 <= s1, f"{w1} -> {w2} px: the search box grew {s1} -> {s2}"
        elif w2 > w1:
            assert s2 >= s1, f"{w1} -> {w2} px: the search box shrank {s1} -> {s2}"
    # both ends were reached: room to spare, and the box below its usual least
    assert max(s for _w, s in seen) > SEARCH_MIN_W > min(s for _w, s in seen)


def test_full_screen_caps_only_the_search_box(window, qapp):
    """At 1920x1080 the search box stops at SEARCH_MAX_W (the library tools stay at
    the right); the seek bar and the drop box still follow the window."""
    from PySide6.QtTest import QTest
    window.show()
    window.tabs.setCurrentIndex(0)
    window.resize(1920, 1080)
    QTest.qWait(150)   # the window's re-fit runs on a timer
    assert window.search.width() == fitcontrol.SEARCH_MAX_W
    last = window._pad_size[1]   # Pad size: the toolbar's last control
    right = last.mapTo(window.sounds_toolbar, last.rect().topRight()).x()
    assert window.sounds_toolbar.width() - right < 40
    assert window._name_seek.width() > 720   # its old cap: it follows the window now
    margins = window.grid.grid.contentsMargins()
    assert window.grid.drop_area().width() == (
        window.grid.width() - margins.left() - margins.right() - 4)


def test_volume_percent_sits_beside_its_slider_on_the_row_line(window, qapp):
    """The bottom row's 100% / 70% were right-aligned in a box as wide as "1000%":
    25-30 px from their slider, and 1 px under the labels beside them."""
    from PySide6.QtTest import QTest
    window.show()
    window.resize(1180, 720)
    QTest.qWait(150)
    for vol in (window.vol_mic, window.vol_mon):
        spin = vol.spin
        assert spin.alignment() & Qt.AlignLeft and spin.alignment() & Qt.AlignVCenter
        text_x = spin.mapTo(vol, spin.lineEdit().geometry().topLeft()).x()
        assert text_x - vol.slider.geometry().right() <= 12
        assert spin.lineEdit().textMargins().bottom() == 2


def test_medium_footer_uses_the_width_without_empty_control_gaps(window, qapp):
    window.themectl.apply_theme("Dark")
    window.tabs.setCurrentIndex(0)
    window.show()
    for size in ((360, 320), (440, 380), (600, 450), (800, 600)):
        window.resize(*size)
        for _ in range(5):
            qapp.processEvents()
    assert not window.fitctl.is_mini()
    assert window.mixer.height() < 100
    assert window.btn_check.isVisibleTo(window)
    last = window._deck_tabs[2]   # the headphones' icon, after what others hear
    assert last.isVisibleTo(window)
    right = last.mapTo(window.mixer, last.rect().topRight()).x()
    assert window.mixer.width() - right <= 20
    window.np_name.hide()
    qapp.processEvents()
    seek_left = window.seek.mapTo(window.btn_skip.parentWidget(), QPoint()).x()
    assert seek_left - window.btn_skip.geometry().right() <= 24
    buttons = window.rail.buttons
    assert all(b.height() >= 34 for b in buttons)
    assert all(b.y() - a.geometry().bottom() >= 4
               for a, b in zip(buttons, buttons[1:]))


def test_narrow_levels_strip_shows_one_group_and_icons_for_the_others(window, qapp):
    """Too narrow for all three groups, none is dropped: what others hear shows whole
    and your mic and headphones are icons beside it; clicking one brings its group up."""
    window.tabs.setCurrentWidget(window.setup_page)
    window.show()
    window.resize(1700, 800)
    qapp.processEvents()
    assert not window._mixer_one   # room for all three
    assert not any(t.isVisibleTo(window) for t in window._deck_tabs)
    decks = [g[-1] for g in window._decks]
    for width in (900, 640):   # (narrower is the mini player with the tests' wider font)
        window.resize(width, 800)
        qapp.processEvents()
        assert not window.fitctl.is_mini() and window.mixer.isVisibleTo(window)
        assert window._mixer_one
        assert [d.isVisibleTo(window) for d in decks] == [False, True, False]
        assert [t.isVisibleTo(window) for t in window._deck_tabs] == [True, False, True]
        right = window.mixer.mapFromGlobal(window._deck_tabs[2].mapToGlobal(
            window._deck_tabs[2].rect().topRight())).x()
        assert right <= window.mixer.width()
        for i in (0, 2, 1):
            window._deck_tabs[i].click()
            qapp.processEvents()
            assert [d.isVisibleTo(window) for d in decks] == [j == i for j in range(3)]
            for c in decks[i].findChildren(QWidget):
                if c.isVisibleTo(window):   # inside the strip, nothing cut off
                    br = c.mapTo(window.mixer, c.rect().bottomRight())
                    assert window.mixer.rect().contains(br)
    window.resize(1700, 800)
    qapp.processEvents()
    assert not window._mixer_one
    assert all(d.isVisibleTo(window) for d in decks)
    assert window.chk_mic.text() and window.vol_mon.spin.isVisibleTo(window)


def test_others_hear_it_keeps_its_words_in_the_tightest_levels_strip(window, qapp):
    """The mic group open in a tight strip (side rail open): the % boxes go, never the
    "Others hear it" words. An empty box beside the mic icon said nothing, and it's the
    switch the mute warning sends you to."""
    window.tabs.setCurrentWidget(window.sounds_page)
    window.show()
    window.rail.set_open(True)
    squeezed = False
    for width in (1100, 900, 700, 600):
        window.resize(width, 720)
        qapp.processEvents()
        window._focus_deck(0)
        qapp.processEvents()
        if window.fitctl.is_mini() or not window.chk_mic.isVisibleTo(window):
            continue
        assert window.chk_mic.text() == "Others hear it"
        br = window.chk_mic.mapTo(window.mixer, window.chk_mic.rect().bottomRight())
        assert window.mixer.rect().contains(br)
        squeezed = squeezed or not window.vol_mic.spin.isVisibleTo(window)
    assert squeezed   # the % boxes went at the tightest width: the case is reached


@pytest.mark.parametrize("page", [0, -1])   # Sounds, and the last tab (Setup)
def test_the_tab_key_goes_from_the_side_rail_into_the_page(window, qapp, page):
    """Tab walked the rail and its buttons, then stuck on the rail's last button (the
    hidden tab bar was the next stop): a keyboard user never reached the page."""
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    window.resize(1100, 750)
    window.show()
    window.tabs.setCurrentIndex(page % window.tabs.count())
    qapp.processEvents()
    window.rail.toggle.setFocus(Qt.TabFocusReason)
    QTest.keyClick(window.rail.toggle, Qt.Key_Tab)
    qapp.processEvents()
    now = QApplication.focusWidget()
    assert now is not window.rail.toggle
    assert window.tabs.currentWidget().isAncestorOf(now)


def test_the_seek_sliders_have_a_name_a_screen_reader_can_say(window):
    assert window.seek.accessibleName() and window.mini_seek.accessibleName()


def test_add_is_a_menu_of_every_way_in(window, monkeypatch):
    """Add opens a menu (a stray click adds nothing); From a link takes a copied link."""
    from soundboard.i18n import _
    menu = window.btn_add.menu()
    assert menu is not None
    assert [a.text() for a in menu.actions()] == [
        _("Sound files"), _("A whole folder"), _("Record"), _("From a link")]
    # Free sound packs is in the Library menu only, not in two places
    lib = [act.text() for m in window.findChildren(QMenu) if m is not menu
           for act in m.actions()]
    assert lib.count(_("Free sound packs")) == 1
    shown = []
    monkeypatch.setattr(window.searchctl, "_show_link", lambda: shown.append(window.search.text()))
    QApplication.clipboard().setText("https://www.youtube.com/watch?v=abc")
    window.impctl.add_from_link()
    assert window.search.text() == "https://www.youtube.com/watch?v=abc" and shown
    window.search.clear()
    QApplication.clipboard().setText("not a link")
    window.impctl.add_from_link()
    assert window.search.text() == ""


def test_a_link_pasted_in_offline_mode_says_why_nothing_happens(window, monkeypatch):
    """Offline, a pasted link showed nothing at all: now one note names Offline mode."""
    from soundboard.online import net
    said = []
    monkeypatch.setattr(window, "toast", lambda text, *a, **k: said.append(text))
    window.show()                            # offscreen: nothing appears
    window.resize(800, 600)
    window.fitctl._refit()
    assert not window.fitctl.is_mini()
    net.configure_features(offline=True)
    try:
        window.search.setText("https://www.youtube.com/watch?v=abc")
        window.searchctl.on_search_enter()
        window.searchctl.on_search_enter()   # Enter again: still the one note
    finally:
        net.configure_features()
    assert len(said) == 1 and "Offline mode" in said[0]
    assert window.ytresults.isHidden()


@pytest.mark.parametrize("page", ["sounds_page", "radio_page"])
def test_resize_transactions_finish_before_painting(window, qapp, monkeypatch, page):
    window.show()
    window.tabs.setCurrentWidget(getattr(window, page))
    qapp.processEvents()
    original = window.fitctl._fit.fit
    calls = []

    def fit(size):
        assert not window.updatesEnabled()
        result = original(size)
        assert not window.updatesEnabled()
        calls.append(size)
        return result

    monkeypatch.setattr(window.fitctl._fit, "fit", fit)
    for width, height in ((440, 600), (360, 220), (800, 600), (450, 390),
                          (1180, 720), (800, 320), (1700, 1000)):
        window.resize(width, height)
        qapp.processEvents()
        assert window.updatesEnabled()
    assert calls
    assert not window.fitctl.is_mini()
    assert window.tabs.currentWidget() is getattr(window, page)


@pytest.mark.parametrize("size", [(800, 600), (1180, 720)])
def test_setup_tab_in_and_out_again_measures_once(window, size, qapp, monkeypatch):
    """Into and out of Setup, the window worked out what gives way from scratch: every
    step undone and done again, the whole window measured 40-60 times (120 ms a switch
    on a slower PC). Now each side's is kept for the window's size: the second time in
    and out it's put back as it was, measured once to check."""
    from soundboard.ui.window import responsive
    from conftest import process_events
    window.show()
    window.tabs.setCurrentWidget(window.sounds_page)
    window.resize(*size)
    window.fitctl._refit()
    qapp.processEvents()
    fit = window.fitctl._fit
    on_sounds = set(fit.applied())
    measured = []
    real = responsive.Fitter.need

    def need(self):
        if self._known is None:
            measured.append(1)
        return real(self)
    monkeypatch.setattr(responsive.Fitter, "need", need)
    seen = []
    for page in (window.setup_page, window.sounds_page) * 2:
        measured.clear()
        window.tabs.setCurrentWidget(page)
        process_events(qapp, lambda: False, timeout=0.3)   # (a refit comes after it too)
        assert not window.fitctl.is_mini()
        got = window._full.minimumSizeHint()
        assert got.width() <= window._pages.width() and got.height() <= window._pages.height()
        seen.append((set(fit.applied()), len(measured)))
    (in1, _), (out1, _), (in2, m_in2), (out2, m_out2) = seen
    assert out1 == out2 == on_sounds   # back as it was before Setup
    assert in2 == in1                  # Setup as it was worked out the first time
    assert m_in2 <= 4 and m_out2 <= 4, f"measured {m_in2} / {m_out2} times"


def test_keep_on_top_changes_the_window_in_place(window, qapp):
    """setWindowFlag hid the window and made a new native one: it went white for a
    frame (and lost its place in the taskbar) each time Keep window on top was switched."""
    from PySide6.QtCore import QEvent, QObject
    window.show()
    qapp.processEvents()
    hidden = []

    class Watch(QObject):
        def eventFilter(self, obj, ev):
            if obj is window and ev.type() == QEvent.Type.Hide:
                hidden.append(1)
            return False
    watch = Watch()
    window.installEventFilter(watch)
    for on in (True, False):
        window.on_top_toggle(on)
        top = Qt.WindowType.WindowStaysOnTopHint
        assert bool(window.windowFlags() & top) == on
        assert bool(window.windowHandle().flags() & top) == on
        assert window.isVisible()
    window.removeEventFilter(watch)
    assert not hidden and not window.cfg.always_on_top


def test_several_links_pasted_show_a_card_each_and_add_all_queues_them(window, qapp,
                                                                       monkeypatch):
    """Links pasted together: each is looked up and shown as a card, and Add all sends
    every one not on the board yet to the download queue."""
    from soundboard.online import ytdl
    from soundboard.online.ytsites import Result
    urls = ["https://www.youtube.com/watch?v=a", "https://soundcloud.com/x/y",
            "https://www.youtube.com/watch?v=bad"]

    def lookup(url, direct=False):
        if url.endswith("bad"):
            raise RuntimeError("gone")
        return Result(url[-1], url[-1], "x", 3.0, link=url)
    monkeypatch.setattr(ytdl, "lookup", lookup)
    picked = []
    monkeypatch.setattr(window.searchctl, "_from_youtube", lambda r, play: (
        picked.append((r.url, play)), window.ytresults.mark(r.url, "add")))
    window.show()
    window.resize(1100, 700)
    window.fitctl._refit()
    QApplication.clipboard().setText("\n".join(urls))
    window.search.clear()
    window.search.paste()
    assert "\n" not in window.search.text()   # (one line: the line breaks are spaces)
    window.searchctl.flush_search()
    assert window.linkbar.many == urls and not window.linkbar.url
    window.searchctl.on_search_enter()
    res = window.ytresults
    for _ in range(200):
        qapp.processEvents()
        if res._rows:
            break
        time.sleep(0.02)
    assert [r.result.url for r in res._rows] == urls[:2]
    assert res.heading.text().startswith("2 links") and "1 couldn't be used" in res.heading.text()
    assert not res.add_all_btn.isHidden() and res.add_all_btn.text() == "Add all (2)"
    res.add_all_btn.click()
    assert picked == [(urls[0], False), (urls[1], False)]
    from soundboard.core import achievements
    assert achievements.value("bulk_links") >= 2   # (Bulk Buyer at 10)
    assert res.add_all_btn.isHidden()   # all on their way: nothing left to add twice
    res.mark(urls[1], "add", False)     # one didn't work: Add all is back for it
    assert not res.add_all_btn.isHidden() and res.add_all_btn.text() == "Add all (1)"
    res.close_results()
    assert res.add_all_btn.isHidden() and not res.links


def test_a_pasted_playlist_shows_its_videos_with_add_all(window, qapp, monkeypatch):
    """A playlist link: a card per video (a grid, not the one wide card), its name and
    how many of its videos are listed over them, and Add all queues them."""
    from soundboard.online import ytdl
    from soundboard.online.ytsites import Result
    url = "https://www.youtube.com/playlist?list=PLabc"
    vids = [Result(f"vid0000000{i}", f"Song {i}", "Band", 60.0) for i in range(2)]
    monkeypatch.setattr(ytdl, "lookup_all", lambda u, direct=False: ytdl.Playlist(
        "Road trip", vids, 40))
    picked = []
    monkeypatch.setattr(window.searchctl, "_from_youtube", lambda r, play: (
        picked.append(r.url), window.ytresults.mark(r.url, "add")))
    window.show()
    window.resize(1100, 700)
    window.fitctl._refit()
    window.search.setText(url)
    window.searchctl.on_search_enter()
    res = window.ytresults
    for _ in range(200):
        qapp.processEvents()
        if res._rows:
            break
        time.sleep(0.02)
    assert [r.result.url for r in res._rows] == [v.url for v in vids]
    assert all(res.rows.indexOf(r) >= 0 for r in res._rows)   # the grid
    assert res.heading.text() == "Road trip  ·  2 of 40 videos"
    assert res.add_all_btn.text() == "Add all (2)" and res.more_btn.isHidden()
    res.add_all_btn.click()
    assert picked == [v.url for v in vids] and res.add_all_btn.isHidden()
    res.playlist.title = "Chill beats for studying and relaxing late at night"
    res._links_heading()   # a long name is cut short, the count stays
    assert res.heading.text() == "Chill beats for studying and re…  ·  2 of 40 videos"
    window.search.clear()   # the playlist's link gone: its cards go too
    assert res.isHidden() and res.playlist is None


def test_the_first_size_fits_a_small_screen():
    """1180 x 720 and the title bar on a 1366 x 768 screen (728 free over the taskbar):
    the bottom strip sat under the taskbar."""
    from PySide6.QtCore import QRect

    class Screen:
        def __init__(self, w, h):
            self.r = QRect(0, 0, w, h)

        def availableGeometry(self):
            return self.r

    assert main.start_size(Screen(1920, 1040)) == (main.START_W, main.START_H)
    w, h = main.start_size(Screen(1366, 728))
    assert w == main.START_W and h + main.FRAME_ROOM <= 728
    assert main.start_size(None) == (main.START_W, main.START_H)
