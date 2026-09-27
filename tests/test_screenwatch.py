"""Screen triggers: the matcher finds a picture in a made-up screen whatever its
brightness and after shrinking, the gate fires once per appearance (and respects
the cooldown), the watcher thread runs on a fake capture (the real screen is never
read), and the Triggers tab turns a match into a sound after the chosen wait."""
import time

import numpy as np
import pytest
from conftest import process_events
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from soundboard import screenwatch as sw
from soundboard.library import Config
from soundboard.screenwatch import Gate, Monitor, Trigger
from soundboard.ui import triggerspanel
from soundboard.ui.triggerspanel import TriggersTab

W, H = 320, 180


def scene(seed=0) -> np.ndarray:
    """A busy grey 'game screen' (blurred noise, so it has shapes, not static)."""
    rng = np.random.default_rng(seed)
    x = rng.random((H // 4, W // 4)).astype(np.float32)
    return np.kron(x, np.ones((4, 4), np.float32)) * 0.6 + 0.1


def banner() -> np.ndarray:
    """A 'YOU DIED'-ish picture: bars of text on a dark band."""
    b = np.full((24, 90), 0.05, np.float32)
    for i, x in enumerate(range(4, 86, 9)):
        b[5:19, x:x + 5] = 0.9 if i % 2 else 0.7
        b[11:13, x:x + 8] = 0.8
    return b


def with_banner(screen: np.ndarray, x=110, y=70, gain=1.0, lift=0.0) -> np.ndarray:
    s = screen.copy()
    b = banner()
    s[y:y + b.shape[0], x:x + b.shape[1]] = b * gain + lift
    return s


# --------------------------------------------------------------------------- matching

def test_match_finds_the_picture_and_where_it_is():
    score, (x, y) = sw.match(with_banner(scene(), 110, 70), banner())
    assert score > 0.99 and (x, y) == (110, 70)
    assert sw.match(scene(), banner())[0] < 0.6      # not on screen: a poor match


def test_match_ignores_brightness_and_contrast():
    """A darker or washed-out game (gamma, a flash, HDR) still matches."""
    s = with_banner(scene(), gain=0.5, lift=0.2)
    assert sw.match(s, banner())[0] > 0.99


def test_match_gives_up_on_flat_or_oversized_pictures():
    assert sw.match(scene(), np.full((20, 20), 0.5, np.float32))[0] == 0.0
    assert sw.match(scene(), np.random.default_rng(1).random((H + 1, 10)))[0] == 0.0
    blank = np.zeros((H, W), np.float32)             # a blank screen matches nothing
    assert sw.match(blank, banner())[0] == 0.0


def test_a_picture_cut_at_full_size_matches_the_shrunk_screen():
    big = np.kron(with_banner(scene(), 100, 60), np.ones((4, 4), np.float32))
    tmpl = np.kron(banner(), np.ones((4, 4), np.float32))
    scale = sw.work_scale(big.shape[1], [min(tmpl.shape)])
    assert scale < 1
    small = sw.shrink(big, scale)
    assert sw.match(small, sw.shrink(tmpl, scale))[0] > 0.95


def test_work_scale_keeps_small_pictures_readable():
    assert sw.work_scale(1920, []) == pytest.approx(sw.WORK_WIDTH / 1920)
    assert sw.work_scale(1920, [20]) == pytest.approx(sw.MIN_SIDE / 20)
    assert sw.work_scale(400, []) == 1.0


def test_gray_2x_averages_blocks_into_luma():
    px = np.zeros((4, 4, 4), np.uint8)
    px[:2, :2, 2] = 255                              # a red block
    px[2:, 2:, :3] = 255                             # a white block
    g = sw.gray_2x(px)
    assert g.shape == (2, 2)
    assert g[0, 0] == pytest.approx(77 / 256, abs=0.01) and g[1, 1] == pytest.approx(1.0, abs=0.01)
    assert g[0, 1] == 0.0


# --------------------------------------------------------------------------- gate

def test_gate_fires_once_per_appearance():
    g = Gate()
    seq = [0.1, 0.9, 0.95, 0.9, 0.78, 0.9, 0.2, 0.9]   # 0.78: dipped, but not gone
    fired = [g.update(s, t, 0.8, 0.0) for t, s in enumerate(seq)]
    assert fired == [False, True, False, False, False, False, False, True]


def test_gate_waits_out_the_cooldown():
    g = Gate()
    assert g.update(0.9, 0.0, 0.8, 5.0)
    assert not g.update(0.1, 1.0, 0.8, 5.0)
    assert not g.update(0.9, 2.0, 0.8, 5.0)          # back too soon: ignored...
    assert not g.update(0.1, 3.0, 0.8, 5.0)
    assert g.update(0.9, 6.0, 0.8, 5.0)              # ...but fine after 5 s


def test_trigger_settings_are_checked_when_loaded():
    t = Trigger.from_raw({"id": "a", "name": 3, "delay": -1, "cooldown": "x",
                          "threshold": 5, "enabled": 1, "sound": "s1"})
    assert (t.name, t.delay, t.cooldown, t.threshold, t.enabled, t.sound) == \
        ("Trigger", 0.0, 3.0, 0.99, True, "s1")
    assert Trigger.from_raw({"name": "no id"}) is None and Trigger.from_raw("x") is None
    assert Trigger.from_raw({"id": "b", "delay": 2}).delay == 2.0


# --------------------------------------------------------------------------- watcher

class FakeGrabber:
    """Stands in for the screen: hands out the frames in `FakeGrabber.frames`."""
    frames: list = []
    made: list = []

    def __init__(self, mon, w, h):
        self.size = (w, h)
        self.closed = False
        FakeGrabber.made.append(self)

    def grab(self):
        f = FakeGrabber.frames
        return f.pop(0) if len(f) > 1 else (f[0] if f else None)

    def close(self):
        self.closed = True


@pytest.fixture
def fake_screen(monkeypatch):
    monkeypatch.setattr(sw, "monitors", lambda: [Monitor(0, 0, W, H, True)])
    monkeypatch.setattr(sw, "Grabber", FakeGrabber)
    monkeypatch.setattr(sw, "WORK_WIDTH", W)
    FakeGrabber.frames, FakeGrabber.made = [], []
    return FakeGrabber


def run_until(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        time.sleep(0.005)
    return cond()


def test_watcher_fires_when_the_picture_appears(fake_screen):
    plain, hit = scene(), with_banner(scene())
    fake_screen.frames = [plain, plain, hit, hit, hit, plain, plain, hit, plain]
    fired = []
    w = sw.Watcher(fired.append)
    w.interval = 0.001
    w.set_items([sw.Watched("t1", banner(), 0.8, 0.0)])
    w.start()
    try:
        assert run_until(lambda: len(fake_screen.frames) == 1 and len(fired) >= 2)
    finally:
        w.stop()
    assert fired == ["t1", "t1"] and fake_screen.made[0].closed
    assert not w.running and w.scores == {}


def test_watcher_says_when_it_only_sees_black(fake_screen):
    fake_screen.frames = [np.zeros((H, W), np.float32)]
    w = sw.Watcher(lambda _t: None)
    w.interval = 0.001
    w.set_items([sw.Watched("t1", banner(), 0.8, 0.0)])
    w.start()
    try:
        assert run_until(lambda: w.black)
    finally:
        w.stop()


def test_watcher_reports_a_capture_that_fails(monkeypatch):
    def broken(*_a):
        raise OSError("no screen")
    monkeypatch.setattr(sw, "monitors", lambda: [Monitor(0, 0, W, H, True)])
    w = sw.Watcher(lambda _t: None, grabber=broken)
    w.set_items([sw.Watched("t1", banner(), 0.8, 0.0)])
    w.start()
    assert run_until(lambda: not w.running)
    assert w.error == "no screen"


# --------------------------------------------------------------------------- the tab

def as_qimage(gray: np.ndarray) -> QImage:
    a = np.ascontiguousarray((gray * 255).clip(0, 255).astype(np.uint8))
    img = QImage(a.data, a.shape[1], a.shape[0], a.shape[1], QImage.Format_Grayscale8)
    return img.copy()


@pytest.fixture
def tab(qapp, app_dir, fake_screen):
    cfg = Config()
    board = [("s1", "Died", "fp1"), ("s2", "Win", "fp2")]
    played, saved = [], []
    t = TriggersTab(cfg, lambda: saved.append(1), lambda: list(board), played.append)
    t.board, t.played, t.saved = board, played, saved
    yield t
    t.shutdown()


def test_pasted_picture_becomes_a_trigger_that_plays_its_sound(tab, qapp):
    qapp.clipboard().setImage(as_qimage(banner()))
    tab.add_from_clipboard()
    assert len(tab.triggers) == 1
    t = tab.triggers[0]
    row = tab.rows[t.id]
    assert t.image.startswith(str(triggerspanel.pictures_dir()))
    row.sound.setCurrentIndex(row.sound.findData("s1"))
    row._on_sound(row.sound.currentIndex())
    assert t.sound == "s1" and tab.cfg.screen["triggers"][0]["sound"] == "s1"

    fake_screen = sw.Grabber
    plain, hit = scene(), with_banner(scene())
    fake_screen.frames = [plain, plain, hit, hit]
    tab.watcher.interval = 0.001
    tab.set_watching(True)
    assert tab.cfg.screen["on"] is True
    assert process_events(qapp, lambda: tab.played == ["s1"])
    tab.set_watching(False)
    assert not tab.watcher.running


def test_the_wait_delays_the_sound_and_stop_all_cancels_it(tab, qapp):
    tab._new(as_qimage(banner()), "Died")
    t = tab.triggers[0]
    t.sound, t.delay = "s2", 0.2
    tab.btn_watch.setChecked(True)
    start = time.monotonic()
    tab._on_fired(t.id)
    assert tab.played == []
    assert process_events(qapp, lambda: tab.played == ["s2"])
    assert time.monotonic() - start >= 0.19
    tab._on_fired(t.id)
    tab.cancel_pending()                           # Stop all while it's waiting
    process_events(qapp, lambda: False, timeout=0.4)
    assert tab.played == ["s2"]


def test_a_sound_file_picked_here_is_attached_once_it_is_added(tab, monkeypatch, tmp_path):
    tab._new(as_qimage(banner()), "Died")
    t = tab.triggers[0]
    f = tmp_path / "boom.wav"
    f.write_bytes(b"RIFF fake")
    monkeypatch.setattr(triggerspanel.QFileDialog, "getOpenFileName",
                        lambda *a, **k: (str(f), ""))
    asked = []
    tab.add_sound.connect(asked.append)
    tab._choose_sound_file(tab.rows[t.id])
    assert asked == [str(f)] and t.pending and not t.sound
    tab.board.append(("s3", "Boom", t.pending))      # the board finished importing it
    tab.sounds_changed()
    assert t.sound == "s3" and not t.pending


def test_triggers_are_remembered_and_removing_one_deletes_its_picture(tab, qapp, fake_screen):
    tab._new(as_qimage(banner()), "Died")
    t = tab.triggers[0]
    t.sound = "s1"
    tab.rows[t.id].threshold.setValue(70)
    assert tab.cfg.screen["triggers"][0]["threshold"] == pytest.approx(0.7)
    again = TriggersTab(tab.cfg, lambda: None, lambda: list(tab.board), lambda _s: None)
    try:
        assert [x.name for x in again.triggers] == ["Died"]
        assert again.triggers[0].threshold == pytest.approx(0.7)
    finally:
        again.shutdown()
    path = t.image
    tab._remove(tab.rows[t.id])
    assert tab.triggers == [] and tab.cfg.screen["triggers"] == []
    assert not triggerspanel.Path(path).exists()


def test_a_plain_picture_is_refused(tab):
    img = QImage(40, 20, QImage.Format_RGB32)
    img.fill(Qt.black)
    assert tab._new(img, "flat") is None and tab.triggers == []
