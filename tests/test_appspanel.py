"""The Apps tab's logic with the Windows capture stood in by fakes: rows follow the
programs that are running, Send starts a capture that feeds the engine, programs
are remembered and picked up again when they restart, and a capture that fails
says so and isn't remembered."""
import numpy as np
import pytest

from soundboard import appaudio
from soundboard.appaudio import App
from soundboard.engine import Engine
from soundboard.library import Config
from soundboard.ui import appspanel
from soundboard.ui.appspanel import AppsTab
from soundboard.ui.widgets import Meter


class FakeCapture:
    made = []
    fail = False
    slow = False   # Windows still opening it (start(wait=False) returned already)

    def __init__(self, pid, sink, include_tree=True, name=""):
        self.pid, self.sink, self.name = pid, sink, name
        self.error = None
        self.ended = False
        self.started = self.stopped = False
        FakeCapture.made.append(self)

    def start(self, timeout=0, wait=True):
        if FakeCapture.fail:
            self.error = "Windows refused (fake)."
            return False
        self.started = True
        return True

    @property
    def ready(self):
        return self.started and self.error is None and not FakeCapture.slow

    def stop(self):
        self.stopped = True

    @property
    def running(self):
        return self.started and not self.stopped and not self.ended and self.error is None


@pytest.fixture
def tab(qapp, monkeypatch):
    monkeypatch.setattr(appaudio, "AppCapture", FakeCapture)
    monkeypatch.setattr(appaudio, "list_apps", lambda: [])
    FakeCapture.made = []
    FakeCapture.fail = FakeCapture.slow = False
    cfg = Config()
    saved = []
    t = AppsTab(Engine(), cfg, lambda: saved.append(1), Meter)
    t.saved = saved
    yield t
    t.shutdown()


def music(pid=100, active=True):
    return App(pid, "music.exe", r"C:\Programs\music.exe", "Music Thing", active, 0.3, ["Speakers"])


def test_card_size_reflows_and_survives_reopening(tab, qapp):
    tab.resize(1060, 640)
    tab.show()
    tab._on_apps([App(100 + i, f"player{i}.exe") for i in range(4)])
    tab.card_size.setValue(240)
    qapp.processEvents()
    small_columns = tab.grid.columns(tab.list.width())
    tab.card_size.setValue(480)
    qapp.processEvents()
    assert tab.grid.columns(tab.list.width()) < small_columns
    assert tab.cfg.app_card_width == 480 and tab.saved
    reopened = AppsTab(Engine(), tab.cfg, lambda: None, Meter)
    assert reopened.card_size.value() == 480 and reopened.grid.min_w == 480
    reopened.shutdown()


def test_rows_follow_running_programs_and_send_captures_into_the_engine(tab):
    assert tab.empty.isVisibleTo(tab)
    tab._on_apps([music(), App(200, "game.exe")])
    assert set(tab.rows) == {"music.exe", "game.exe"} and not tab.empty.isVisibleTo(tab)
    assert tab.grid.count() == 2                 # a card each, in the grid
    row = tab.rows["music.exe"]
    assert row.name.text() == "Music" and "Music Thing" in row.sub.text()
    assert not row.sending and tab.engine.aux == ()

    row.btn_send.setChecked(True)                # click Send
    assert row.sending and row.capture is not None and row.capture.started
    assert row.capture.pid == 100
    assert [a.key for a in tab.engine.aux] == [("app", "music.exe")]
    assert tab.cfg.apps == {"music.exe": {"vol": 1.0, "monitor": False,
                                          "path": r"c:\programs\music.exe"}} and tab.saved
    src = row.src
    src.ring_main.prefill = 0
    tab.engine.main_stream = object()            # a cable output is open
    row.capture.sink(np.full((480, 2), 0.5, np.float32))
    out = np.zeros((480, 2), np.float32)
    tab.engine._main(out, 480)
    assert out.any() and tab.engine.aux_on_air()
    row.vol.spin.setValue(50)                    # its own volume, remembered
    row.chk_hear.setChecked(True)
    assert src.vol == 0.5 and src.monitor is True
    assert tab.cfg.apps["music.exe"] == {"vol": 0.5, "monitor": True,
                                         "path": appspanel.path_key(music().path)}

    row.btn_send.setChecked(False)               # Send off: stopped and forgotten
    assert row.capture is None and tab.engine.aux == () and "music.exe" not in tab.cfg.apps
    assert FakeCapture.made[0].stopped


def test_unremembered_program_that_closes_is_dropped(tab):
    tab._on_apps([App(200, "game.exe")])
    tab._on_apps([])
    assert tab.rows == {} and tab.empty.isVisibleTo(tab)


def test_tab_reports_programs_being_sent_for_the_live_dot(tab):
    seen = []
    tab.active_changed.connect(seen.append)
    tab._on_apps([music(), App(200, "game.exe")])
    assert not tab.is_active() and seen == []
    tab.rows["music.exe"].btn_send.setChecked(True)
    assert seen == [True] and tab.is_active() and tab.live_tip() == "● ON: sending Music"
    tab.rows["game.exe"].btn_send.setChecked(True)    # said again: the tip names both
    assert seen == [True, True] and "Music" in tab.live_tip() and "Game" in tab.live_tip()
    tab.rows["game.exe"].btn_send.setChecked(False)
    assert seen == [True, True, True] and tab.is_active()
    tab.stop_all()
    assert seen == [True, True, True, False] and not tab.is_active()
    tab.rows["music.exe"].btn_send.setChecked(True)
    tab._on_apps([])                                   # the program closed while sent
    assert seen[-2:] == [True, False] and not tab.is_active()


def test_remembered_program_is_picked_up_again_when_it_restarts(tab):
    tab._on_apps([music(pid=100)])
    tab.rows["music.exe"].btn_send.setChecked(True)
    first = tab.rows["music.exe"].capture
    tab._on_apps([])                             # it closed
    row = tab.rows["music.exe"]
    assert first.stopped and row.capture is None and not row.sending
    assert row.app is None and "Not running" in row.sub.text()
    assert "music.exe" in tab.cfg.apps           # still remembered
    tab._on_apps([music(pid=101)])               # it's back, under a new pid
    assert row.sending and row.capture is not None and row.capture.pid == 101
    assert row.capture is not first


def test_a_capture_that_dies_is_restarted_and_a_restarted_program_is_followed(tab):
    tab._on_apps([music(pid=100)])
    row = tab.rows["music.exe"]
    row.btn_send.setChecked(True)
    cap = row.capture
    cap.ended = True                             # the capture thread noticed the program go
    tab._on_apps([music(pid=100)])
    assert row.capture is not cap and row.capture.started and cap.stopped
    cap2 = row.capture
    tab._on_apps([music(pid=102)])               # same .exe, new process
    assert row.capture is not cap2 and row.capture.pid == 102 and cap2.stopped


def test_a_capture_that_errors_says_so_and_stops_sending(tab):
    tab._on_apps([music(pid=100)])
    row = tab.rows["music.exe"]
    row.btn_send.setChecked(True)
    cap = row.capture
    cap.error = "Sending this program's sound failed. Switch Send on to try again."
    tab._on_apps([music(pid=100)])
    assert cap.stopped and row.capture is None and not row.sending
    assert "Switch Send on" in row.sub.text() and tab.engine.aux == ()
    n = len(FakeCapture.made)
    tab._on_apps([music(pid=100)])               # no silent restart loop
    assert len(FakeCapture.made) == n and "Switch Send on" in row.sub.text()
    row.btn_send.setChecked(True)                # trying again clears it
    assert row.sending and "Switch Send on" not in row.sub.text()


def test_clearing_an_error_line_takes_the_red_off(qapp):
    from soundboard.ui.appspanel import AppRow
    row = AppRow("music.exe", Meter)
    row.set_app(music())
    row.set_status("It failed", error=True)
    assert row.sub.property("tone") == "error"
    row.set_status("")
    assert row.sub.property("tone") == "" and row.sub.text() != "It failed"


def test_remembered_programs_start_from_the_config_and_auto_send(qapp, monkeypatch):
    monkeypatch.setattr(appaudio, "AppCapture", FakeCapture)
    FakeCapture.made, FakeCapture.fail, FakeCapture.slow = [], False, False
    cfg = Config()
    cfg.apps = {"music.exe": {"vol": 0.8, "monitor": True}}
    t = AppsTab(Engine(), cfg, lambda: None, Meter)
    try:
        row = t.rows["music.exe"]
        assert row.app is None and row.vol.value() == 0.8 and row.chk_hear.isChecked()
        assert not row.btn_send.isEnabled()
        t._on_apps([music()])
        assert row.sending and row.capture is not None
        assert row.src.vol == 0.8 and row.src.monitor is True
        t.stop_all()                             # Stop all switches it off but keeps it
        assert row.capture is None and not row.sending and "music.exe" in cfg.apps
        t._on_apps([music()])                    # still running: stays off until you say so
        assert not row.sending
        row.btn_forget.click()
        assert "music.exe" not in cfg.apps
    finally:
        t.shutdown()


def test_a_damaged_remembered_volume_does_not_stop_the_app_starting(qapp, monkeypatch):
    """A hand-edited or damaged config ("loud", NaN, huge) used to crash the window."""
    monkeypatch.setattr(appaudio, "list_apps", lambda: [])
    cfg = Config()
    cfg.apps = {"a.exe": {"vol": "loud"}, "b.exe": {"vol": float("nan")},
                "c.exe": {"vol": 1e9}, "d.exe": {"vol": -2}, "e.exe": {"vol": None},
                "f.exe": {"vol": "0.5"}}
    t = AppsTab(Engine(), cfg, lambda: None, Meter)
    try:
        vols = {exe: row.vol.value() for exe, row in t.rows.items()}
    finally:
        t.shutdown()
    assert vols == {"a.exe": 1.0, "b.exe": 1.0, "c.exe": appspanel.MAX_VOL, "d.exe": 0.0,
                    "e.exe": 1.0, "f.exe": 0.5}


def test_a_failed_capture_reports_and_is_not_remembered(tab):
    FakeCapture.fail = True
    tab._on_apps([music()])
    row = tab.rows["music.exe"]
    row.btn_send.setChecked(True)
    assert not row.sending and row.capture is None
    assert "refused" in row.sub.text() and tab.engine.aux == ()
    assert "music.exe" not in tab.cfg.apps
    tab._on_apps([music()])                      # the next refresh keeps the message up
    assert "refused" in row.sub.text()
    FakeCapture.fail = False
    row.btn_send.setChecked(True)                # trying again clears it
    assert row.sending and "refused" not in row.sub.text()


def test_a_capture_opens_without_freezing_the_window_and_can_fail_later(tab):
    FakeCapture.slow = True                      # Windows takes its time
    tab._on_apps([music()])
    row = tab.rows["music.exe"]
    row.btn_send.setChecked(True)
    assert row.sending and "Connecting" in row.sub.text()
    assert "music.exe" not in tab.cfg.apps       # remembered once it's really up
    FakeCapture.slow = False
    tab._meters()
    assert "Connecting" not in row.sub.text() and "music.exe" in tab.cfg.apps
    row.btn_send.setChecked(False)
    FakeCapture.slow = True
    row.btn_send.setChecked(True)
    row.capture.error = "Windows refused (fake, late)."
    tab._meters()
    assert not row.sending and row.capture is None and "late" in row.sub.text()
    assert "music.exe" not in tab.cfg.apps and tab.engine.aux == ()
    FakeCapture.slow = False


def test_a_program_can_go_to_the_stream_only(qapp, monkeypatch):
    """Music for the viewers but not the call: the choice shows once a stream output
    is set, and is remembered with the program."""
    monkeypatch.setattr(appaudio, "AppCapture", FakeCapture)
    FakeCapture.made, FakeCapture.fail, FakeCapture.slow = [], False, False
    cfg = Config()
    e = Engine()
    t = AppsTab(e, cfg, lambda: None, Meter)
    try:
        t._on_apps([music()])
        row = t.rows["music.exe"]
        assert row.cb_to.isHidden()                  # no stream output: nothing to pick
        e.names["obs"] = "Stream (fake)"
        t._on_apps([music()])
        assert not row.cb_to.isHidden()
        row.btn_send.setChecked(True)
        assert row.src.live and row.src.stream       # both, by default
        row.cb_to.setCurrentIndex(appspanel.TO_KEYS.index("stream"))
        assert not row.src.live and row.src.stream
        assert not e.aux_on_air()                    # the call doesn't hear it: no push-to-talk
        assert cfg.apps["music.exe"]["to"] == "stream"
    finally:
        t.shutdown()
    e.names["obs"] = None
    t = AppsTab(e, cfg, lambda: None, Meter)
    try:
        row = t.rows["music.exe"]
        assert row.to == "stream" and not row.cb_to.isHidden()   # set: stays in sight
        t._on_apps([music()])
        assert row.sending and not row.src.live and row.src.stream
    finally:
        t.shutdown()


def test_shutdown_stops_every_capture(tab):
    tab._on_apps([music(), App(200, "game.exe")])
    for row in tab.rows.values():
        row.btn_send.setChecked(True)
    assert len(tab.engine.aux) == 2
    tab.shutdown()
    assert tab.engine.aux == () and all(c.stopped for c in FakeCapture.made)


def test_windows_only_warning(qapp, monkeypatch):
    monkeypatch.setattr(appaudio, "supported", lambda: (False, "Needs Windows 11."))
    t = AppsTab(Engine(), Config(), lambda: None, Meter)
    assert t.warn.isVisibleTo(t) and "Windows 11" in t.warn.text()
    t.shutdown()


def test_lister_hands_results_to_the_ui_thread(qapp, monkeypatch):
    monkeypatch.setattr(appaudio, "list_apps", lambda: [music()])
    got = []
    lister = appspanel._Lister()
    lister.ready.connect(got.append)
    lister.refresh()
    for _ in range(100):
        qapp.processEvents()
        if got:
            break
        import time
        time.sleep(0.02)
    assert got and got[0][0].exe == "music.exe"
    lister.stop()


def test_a_listing_failure_skips_the_update(qapp, monkeypatch):
    def boom():
        raise OSError("COM hiccup")
    monkeypatch.setattr(appaudio, "list_apps", boom)
    got = []
    lister = appspanel._Lister()
    lister.ready.connect(got.append)
    lister._work()                               # an empty list would stop every capture
    qapp.processEvents()
    assert got == [] and not lister._busy
    lister.stop()


def test_record_waits_for_sound_then_adds_a_clip_without_sending(tab, monkeypatch, tmp_path):
    monkeypatch.setattr(appspanel.library, "APP_DIR", tmp_path)
    clips = []
    tab.clip_ready.connect(lambda data, name: clips.append((data, name)))
    tab._on_apps([music()])
    row = tab.rows["music.exe"]

    row.btn_rec.setChecked(True)                 # click Record: armed, nothing sent
    cap = row.capture
    assert cap is not None and cap.started and row.src is None and tab.engine.aux == ()
    for _ in range(50):                          # 0.5 s of silence isn't recorded
        cap.sink(np.zeros((480, 2), np.float32))
    tab._meters()
    assert not row.rec.triggered and row.btn_rec.text().startswith("Waiting")
    for _ in range(100):                         # the program starts playing: 1 s
        cap.sink(np.full((480, 2), 0.3, np.float32))
    tab._meters()
    assert row.rec.triggered and row.btn_rec.text().startswith("Stop")

    row.btn_rec.setChecked(False)                # click again: the clip is handed over
    assert len(clips) == 1
    data, name = clips[0]
    assert name.startswith("Music ")
    assert 0.9 * appspanel.SR < len(data) < 1.4 * appspanel.SR   # the silence isn't in it
    assert cap.stopped and row.capture is None and "Saved" in row.sub.text()
    assert not list(tmp_path.iterdir())          # the spool file is gone


def test_record_that_never_hears_anything_saves_nothing(tab, monkeypatch, tmp_path):
    monkeypatch.setattr(appspanel.library, "APP_DIR", tmp_path)
    clips = []
    tab.clip_ready.connect(lambda *a: clips.append(a))
    tab._on_apps([music()])
    row = tab.rows["music.exe"]
    row.btn_rec.setChecked(True)
    row.capture.sink(np.zeros((4800, 2), np.float32))
    row.btn_rec.setChecked(False)
    assert clips == [] and "didn't make a sound" in row.sub.text()


def test_record_and_send_share_one_capture(tab, monkeypatch, tmp_path):
    monkeypatch.setattr(appspanel.library, "APP_DIR", tmp_path)
    tab._on_apps([music()])
    row = tab.rows["music.exe"]
    row.btn_send.setChecked(True)
    row.btn_rec.setChecked(True)
    assert len(FakeCapture.made) == 1
    row.btn_send.setChecked(False)               # Send off: still recording
    assert row.capture is not None and not row.capture.stopped and tab.engine.aux == ()
    tab.stop_all()
    assert row.rec is not None
    row.btn_rec.setChecked(False)
    assert FakeCapture.made[0].stopped and row.capture is None


def test_armed_recorder_keeps_a_short_preroll(tmp_path):
    from soundboard.recorder import ArmedRecorder
    rec = ArmedRecorder(tmp_path / "r.wav")
    for _ in range(100):
        rec.push(np.zeros((480, 2), np.float32))
    rec.push(np.full((480, 2), 0.5, np.float32))
    data = rec.stop()
    pre = len(data) - 480
    want = ArmedRecorder.PREROLL_S * appspanel.SR
    assert want <= pre <= want + 480
    assert np.allclose(data[-480:], 0.5, atol=1e-3)


def test_cards_tighten_when_narrow_and_keep_the_meter(qapp):
    """A narrow card: the typed volume and the buttons' words give way, in that
    order, so it fits; the level meter has its own line and stays."""
    from PySide6.QtWidgets import QWidget

    from soundboard.ui.appspanel import AppRow
    holder = QWidget()                 # a card is always inside the list, never a window
    row = AppRow("music.exe", Meter)
    row.setParent(holder)
    row.set_app(music())
    holder.show()
    row.setGeometry(0, 0, 800, 140)   # (test fonts run wide)
    assert row.vol.spin.isVisibleTo(row) and row.btn_rec.text() == "Record"
    row.setGeometry(0, 0, 150, 140)
    assert row.meter.isVisibleTo(row) and row.btn_rec.text() == ""
    assert not row.vol.spin.isVisibleTo(row) and row.chk_hear.text() == "Hear"
    row.set_sending(True)                         # the words stay away when it changes
    assert row.btn_send.text() == ""
    row.setGeometry(0, 0, 800, 140)
    assert row.vol.spin.isVisibleTo(row) and row.btn_send.text() == "Sending"
    holder.hide()


def test_programs_are_cards_several_across(tab, qapp, monkeypatch):
    """A wide window shows the programs side by side, an equal-width card each."""
    apps = [music(), App(200, "game.exe"), App(300, "call.exe")]
    monkeypatch.setattr(appaudio, "list_apps", lambda: apps)   # still running when shown
    tab._on_apps(apps)
    tab.resize(1200, 600)
    tab.show()
    qapp.processEvents()
    cards = [tab.rows[k] for k in ("music.exe", "game.exe", "call.exe")]
    tops = {c.geometry().top() for c in cards}
    widths = {c.width() for c in cards}
    assert len(tops) == 1 and len(widths) == 1 and cards[0].width() >= appspanel.CARD_MIN_W
    tab.resize(400, 600)
    qapp.processEvents()
    assert len({c.geometry().top() for c in cards}) == 3   # one per line when narrow
    tab.hide()


def test_cards_settle_instead_of_jumping(tab, qapp, monkeypatch):
    """A card that only just needs tightening is shorter tight than full: it settles
    on one, instead of flipping between them on every relayout (the cards jumped up
    and down in a big window)."""
    import time

    from PySide6.QtCore import QEvent, QObject

    apps = [music(), App(200, "game.exe"), App(300, "call.exe")]
    monkeypatch.setattr(appaudio, "list_apps", lambda: apps)
    tab._on_apps(apps)
    cards = [tab.rows[k] for k in ("music.exe", "game.exe", "call.exe")]

    class Count(QObject):
        n = 0

        def eventFilter(self, obj, ev):
            if ev.type() == QEvent.Resize:
                Count.n += 1
            return False
    counter = Count()
    for c in cards:
        c.installEventFilter(counter)
    tab.show()
    for width in range(500, 1500, 20):   # some width lands each card on the edge
        tab.resize(width, 500)
        for _ in range(5):
            qapp.processEvents()
        Count.n = 0
        end = time.monotonic() + 0.05
        while time.monotonic() < end:
            qapp.processEvents()
        assert Count.n == 0, f"cards still resizing at {width} px"
    tab.hide()


# ---------------------------------------------------------------- same name, other folder

def player(pid, folder, title=""):
    return App(pid, "player.exe", rf"C:\{folder}\player.exe", title)


def test_path_key_lower_cases_and_ignores_version_folders():
    assert appspanel.path_key(r"C:\Apps\Discord\app-1.0.9156\Discord.exe") == \
        r"c:\apps\discord\*\discord.exe"
    assert appspanel.path_key("C:/Tools/24.1.3/x.exe") == r"c:\tools\*\x.exe"
    assert appspanel.path_key(r"C:\Games\Doom 2\doom.exe") == r"c:\games\doom 2\doom.exe"
    assert appspanel.is_path_key(appspanel.path_key(r"C:\a.exe"))
    assert not appspanel.is_path_key("a.exe")


def test_two_programs_of_one_name_get_a_card_each_and_are_sent_apart(tab):
    tab._on_apps([player(100, "Music"), player(200, "Tools")])
    music_key, tools_key = "player.exe", r"c:\tools\player.exe"
    assert set(tab.rows) == {music_key, tools_key}
    a, b = tab.rows[music_key], tab.rows[tools_key]
    assert a.name.text() == "Player (music)" and b.name.text() == "Player (tools)"
    b.btn_send.setChecked(True)                    # only the second one goes out
    assert b.capture.pid == 200 and a.capture is None
    assert [s.key for s in tab.engine.aux] == [("app", tools_key)]
    assert tab.cfg.apps == {}                      # an older version sees nothing of it
    assert tab.cfg.apps_paths == {tools_key: {"vol": 1.0, "monitor": False,
                                              "exe": "player.exe"}}
    a.btn_send.setChecked(True)
    assert tab.cfg.apps["player.exe"]["path"] == r"c:\music\player.exe"
    tab._on_apps([])                               # both close
    tab._on_apps([player(301, "Tools"), player(302, "Music")])   # back, other order
    assert a.capture.pid == 302 and b.capture.pid == 301 and a.sending and b.sending
    assert a.vol is not b.vol


def test_a_remembered_program_does_not_auto_send_another_one_of_its_name(tab):
    tab.cfg.apps["player.exe"] = {"vol": 1.0, "monitor": False, "path": r"c:\music\player.exe"}
    tab._on_apps([player(100, "Tools")])           # same name, another folder
    assert set(tab.rows) == {r"c:\tools\player.exe"}
    other = tab.rows[r"c:\tools\player.exe"]
    assert not other.sending and other.capture is None


def test_an_update_into_a_new_version_folder_is_still_the_same_program(tab):
    old = r"C:\Apps\Chat\app-1.0.1\chat.exe"
    tab._on_apps([App(100, "chat.exe", old)])
    tab.rows["chat.exe"].btn_send.setChecked(True)
    tab._on_apps([])
    tab._on_apps([App(101, "chat.exe", old.replace("1.0.1", "1.0.2"))])
    row = tab.rows["chat.exe"]
    assert set(tab.rows) == {"chat.exe"} and row.sending and row.capture.pid == 101


def test_a_program_remembered_by_name_only_takes_the_first_folder_seen(tab):
    tab.cfg.apps["player.exe"] = {"vol": 0.5, "monitor": False}   # by an older version
    tab._on_apps([player(100, "Music"), player(200, "Tools")])
    row = tab.rows["player.exe"]
    assert row.sending and row.capture.pid == 100
    assert tab.cfg.apps["player.exe"]["path"] == r"c:\music\player.exe"
    assert not tab.rows[r"c:\tools\player.exe"].sending


def test_forgetting_and_bringing_back_a_second_program_of_a_name(tab, monkeypatch):
    from soundboard import trash
    put = []

    def fake_put(exe, spec, name, hidden=False, path=""):
        put.append(trash.Item("id1", trash.APP, name, 0.0,
                              {"exe": exe, "spec": dict(spec), "hidden": hidden,
                               **({"path": path} if path else {})}))
        return put[-1]
    monkeypatch.setattr(trash, "put_app", fake_put)
    monkeypatch.setattr(trash, "items", lambda kind: put)
    key = r"c:\tools\player.exe"
    tab._on_apps([player(100, "Music"), player(200, "Tools")])
    tab.rows[key].btn_send.setChecked(True)       # remembered, by its folder
    tab._on_forget(tab.rows[key])
    assert key not in tab.rows and key in tab.cfg.apps_hidden and not tab.cfg.apps_paths
    assert put[-1].data["exe"] == "player.exe" and put[-1].data["path"] == key
    tab._on_apps([player(100, "Music"), player(200, "Tools")])
    assert key not in tab.rows and "player.exe" in tab.rows   # stays off the list
    assert tab._unforget(put[-1])
    assert key not in tab.cfg.apps_hidden and key in tab.cfg.apps_paths
    assert "player.exe" not in tab.cfg.apps        # the other one is left as it was
    tab._on_apps([player(100, "Music"), player(200, "Tools")])
    assert tab.rows[key].sending and not tab.rows["player.exe"].sending
