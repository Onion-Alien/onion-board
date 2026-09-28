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


def test_transparent_parts_of_a_picture_are_ignored():
    """A cut-out icon (transparent around it) matches whatever is behind it."""
    tmpl = np.full((40, 120), 0.0, np.float32)        # transparent parts saved as black
    b = banner()
    tmpl[8:32, 15:105] = b
    mask = np.zeros(tmpl.shape, bool)
    mask[8:32, 15:105] = True
    s = with_banner(scene(3), 110, 70)                # busy background, not black
    assert sw.match(s, tmpl)[0] < 0.9                 # the black border spoils a plain match
    score, (x, y) = sw.match(s, tmpl, mask)
    assert score > 0.99 and (x, y) == (95, 62)
    assert sw.match(scene(3), tmpl, mask)[0] < 0.6    # and it's still not everywhere


def test_a_picture_cut_at_full_size_matches_the_shrunk_screen():
    big = np.kron(with_banner(scene(), 100, 60), np.ones((4, 4), np.float32))
    tmpl = np.kron(banner(), np.ones((4, 4), np.float32))
    scale = sw.work_scale(big.shape[1], [min(tmpl.shape)])
    assert scale < 1
    small = sw.shrink(big, scale)
    assert sw.match(small, sw.shrink(tmpl, scale))[0] > 0.95


def test_work_scale_keeps_small_pictures_readable():
    assert sw.work_scale(1920, []) == pytest.approx(sw.WORK_WIDTH / 1920)
    assert sw.work_scale(1920, [40]) == pytest.approx(sw.MIN_SIDE / 40)
    assert sw.work_scale(400, []) == 1.0


def test_one_tiny_picture_cannot_make_every_check_full_size():
    """A 6-px picture used to mean matching the whole 4K screen at full size (over a
    second a check, for every trigger): the zoom stops at MAX_ZOOM x WORK_WIDTH."""
    cap = sw.MAX_ZOOM * sw.WORK_WIDTH
    assert sw.work_scale(3840, [6]) == pytest.approx(cap / 3840)
    assert sw.work_scale(1920, [6]) == pytest.approx(cap / 1920)
    assert sw.work_scale(cap // 2, [6]) == 1.0


def outline(h=70, w=240, stroke=3) -> tuple[np.ndarray, np.ndarray]:
    """A cut-out of outlined 'letters': thin strokes, transparent everywhere else."""
    gray = np.zeros((h, w), np.float32)
    mask = np.zeros((h, w), bool)
    for i in range(6):
        x = 8 + i * 38
        box = np.zeros((h, w), bool)
        box[10:58, x:x + 28] = True
        box[10 + stroke:58 - stroke, x + stroke:x + 28 - stroke] = False
        box[34:34 + stroke, x:x + 28] = True
        gray[box] = 1.0 if i % 2 else 0.3
        mask |= box
    return gray, mask


def test_a_cut_out_with_thin_lines_is_still_found():
    """Shrinking the mask used to keep only pixels that were wholly opaque, so 3-px
    outlines wore away to nothing and the picture could never match."""
    gray, mask = outline()
    rng = np.random.default_rng(9)
    screen = np.kron(rng.random((136, 241)).astype(np.float32),
                     np.ones((8, 8), np.float32))[:1080, :1920] * 0.6 + 0.1
    screen[500:570, 800:1040][mask] = gray[mask]
    scale = sw.work_scale(1920, [min(gray.shape)])
    m = sw.shrink_mask(mask, scale)
    assert m.sum() >= sw.MASK_MIN
    score = sw.match(sw.shrink(screen, scale), sw.shrink(gray, scale), m)[0]
    assert score > 0.8
    assert sw.match(sw.shrink(scene(), 1.0), sw.shrink(gray, scale), m)[0] < 0.6


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
    monkeypatch.setattr(sw, "open_grabber", FakeGrabber)   # never the real screen
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


class ModeGrabber(FakeGrabber):
    """A capture whose frames come at `source` size, like Desktop Duplication's: it
    says so, and gives out frames at whatever size the watcher asks for."""
    source = (W, H)
    resized: list = []
    lost = False

    def __init__(self, mon, w, h):
        super().__init__(mon, w, h)
        self.w, self.h = w, h

    def resize(self, w, h):
        self.w, self.h = w, h
        self.size = (w, h)
        ModeGrabber.resized.append((w, h))


def test_watcher_scales_the_pictures_to_the_screen_the_capture_really_sees(monkeypatch):
    """The monitor is listed as WxH but the frames come in at twice that (a game's
    mode, or a DPI-unaware view of the desktop): the pictures are shrunk to match
    what the frames show."""
    monkeypatch.setattr(sw, "monitors", lambda: [Monitor(0, 0, W, H, True)])
    monkeypatch.setattr(sw, "WORK_WIDTH", W)
    # the real screen: 2x the size, the banner at its real size (in real pixels)
    big = with_banner(np.kron(scene(), np.ones((2, 2), np.float32)), x=220, y=140)
    ModeGrabber.source, ModeGrabber.resized = (2 * W, 2 * H), []
    FakeGrabber.frames, FakeGrabber.made = [sw.shrink(big, 0.5)], []   # a (W, H) sample of it
    fired = []
    w = sw.Watcher(fired.append, grabber=ModeGrabber)
    w.interval = 0.001
    w.set_items([sw.Watched("t1", banner(), 0.8, 0.0)])
    w.start()
    try:
        assert run_until(lambda: fired)
        score = w.scores["t1"]
    finally:
        w.stop()
    assert score > 0.8
    assert ModeGrabber.resized == []      # the working size didn't change, only the scale


def test_watcher_refits_when_the_screen_changes_mode(monkeypatch):
    """Mid-run the frames change size (a game went fullscreen at another
    resolution): the pictures are rescaled, nothing dies, and matching goes on."""
    monkeypatch.setattr(sw, "monitors", lambda: [Monitor(0, 0, W, H, True)])
    monkeypatch.setattr(sw, "WORK_WIDTH", W)
    ModeGrabber.source, ModeGrabber.resized = (W, H), []
    plain = scene()
    FakeGrabber.frames, FakeGrabber.made = [plain, plain, plain, plain], []
    fired = []
    w = sw.Watcher(fired.append, grabber=ModeGrabber)
    w.interval = 0.001
    w.set_items([sw.Watched("t1", banner(), 0.8, 0.0)])
    w.start()
    try:
        assert run_until(lambda: "t1" in w.scores)
        # the mode switches to a smaller screen that shows the banner at its real size
        small = with_banner(scene()[:H // 2, :W // 2], x=10, y=20)
        FakeGrabber.frames = [small]
        ModeGrabber.source = (W // 2, H // 2)
        assert run_until(lambda: fired)
    finally:
        w.stop()
    assert ModeGrabber.resized == [(W // 2, H // 2)] and not w.error


def test_watcher_reopens_a_capture_that_is_lost(monkeypatch):
    """A grab that raises CaptureLost closes the grabber, says `lost`, and opens a
    new one a moment later instead of stopping."""
    monkeypatch.setattr(sw, "monitors", lambda: [Monitor(0, 0, W, H, True)])
    monkeypatch.setattr(sw, "WORK_WIDTH", W)
    monkeypatch.setattr(sw, "RETRY_S", 0.05)
    seen_lost = []

    class Losing(FakeGrabber):
        def grab(self):
            if len(FakeGrabber.made) == 1:
                raise sw.CaptureLost("gone")
            return super().grab()

    FakeGrabber.frames, FakeGrabber.made = [with_banner(scene())], []
    fired = []
    w = sw.Watcher(fired.append, grabber=Losing)
    w.interval = 0.001
    w.set_items([sw.Watched("t1", banner(), 0.8, 0.0)])
    w.start()
    try:
        assert run_until(lambda: (seen_lost.append(w.lost), fired)[1])
    finally:
        w.stop()
    assert len(FakeGrabber.made) == 2 and FakeGrabber.made[0].closed
    assert any(seen_lost) and not w.error


def test_watcher_reopens_after_any_capture_error(monkeypatch):
    """A graphics driver reset makes a grab fail with some other error than
    CaptureLost: the capture is opened afresh instead of watching stopping."""
    monkeypatch.setattr(sw, "monitors", lambda: [Monitor(0, 0, W, H, True)])
    monkeypatch.setattr(sw, "WORK_WIDTH", W)
    monkeypatch.setattr(sw, "RETRY_S", 0.05)

    class Resetting(FakeGrabber):
        def grab(self):
            if len(FakeGrabber.made) == 1:
                raise OSError("AcquireNextFrame failed (0x887A0005)")
            return super().grab()

    FakeGrabber.frames, FakeGrabber.made = [with_banner(scene())], []
    fired = []
    w = sw.Watcher(fired.append, grabber=Resetting)
    w.interval = 0.001
    w.set_items([sw.Watched("t1", banner(), 0.8, 0.0)])
    w.start()
    try:
        assert run_until(lambda: fired)
    finally:
        w.stop()
    assert len(FakeGrabber.made) == 2 and FakeGrabber.made[0].closed and not w.error


def test_watcher_waits_for_a_screen_that_is_gone_for_a_moment(monkeypatch):
    """After a loss the monitor list can be empty for a moment (a cable, a dock):
    that's waited out like the rest of the reopen, not the end of watching."""
    monkeypatch.setattr(sw, "WORK_WIDTH", W)
    monkeypatch.setattr(sw, "RETRY_S", 0.05)
    mons = [Monitor(0, 0, W, H, True)]
    monkeypatch.setattr(sw, "monitors", lambda: list(mons))

    class Unplugged(FakeGrabber):
        def grab(self):
            if len(FakeGrabber.made) == 1:
                mons.clear()
                raise sw.CaptureLost("gone")
            return super().grab()

    FakeGrabber.frames, FakeGrabber.made = [with_banner(scene())], []
    fired = []
    w = sw.Watcher(fired.append, grabber=Unplugged)
    w.interval = 0.001
    w.set_items([sw.Watched("t1", banner(), 0.8, 0.0)])
    w.start()
    try:
        assert run_until(lambda: not mons)
        time.sleep(0.2)
        assert w.running and w.lost and not w.error
        mons.append(Monitor(0, 0, W, H, True))            # ...and it's back
        assert run_until(lambda: fired)
    finally:
        w.stop()
    assert not w.error


def test_stop_then_start_during_a_slow_check_leaves_one_thread(monkeypatch):
    """stop() gives up waiting after 2 s; the old thread must still end on its own
    rather than carry on beside the new one."""
    monkeypatch.setattr(sw, "monitors", lambda: [Monitor(0, 0, W, H, True)])
    monkeypatch.setattr(sw, "WORK_WIDTH", W)
    slow = sw.threading.Event()

    class Slow(FakeGrabber):
        def grab(self):
            if len(FakeGrabber.made) == 1 and not slow.is_set():
                slow.set()
                time.sleep(2.5)                  # a hung driver call, say
            return scene()

    FakeGrabber.frames, FakeGrabber.made = [], []
    w = sw.Watcher(lambda _t: None, grabber=Slow)
    w.interval = 0.01
    w.set_items([sw.Watched("t1", banner(), 0.8, 0.0)])
    w.start()
    try:
        assert slow.wait(2)
        w.stop()                                 # times out: the grab is still going
        assert not w.running
        w.start()
        assert w.running
        assert run_until(lambda: sum(t.name == "screenwatch"
                                     for t in sw.threading.enumerate()) == 1)
        assert w.running
    finally:
        w.stop()
    assert run_until(lambda: not any(t.name == "screenwatch" for t in sw.threading.enumerate()))


def test_scores_are_replaced_whole_not_changed_in_place(fake_screen):
    """The UI thread reads and prunes `scores` while the watcher writes it."""
    w = sw.Watcher(lambda _t: None)
    items = [sw.Watched("t1", banner(), 0.8, 0.0)]
    old = w.scores = {"gone": 0.5}
    new = w._check(with_banner(scene()), items, {"t1": (banner(), None)})
    assert old == {"gone": 0.5} and new["t1"] > 0.99
    w.scores = {"t1": 0.9, "gone": 0.5}
    w.set_items(items)
    assert w.scores == {"t1": 0.9}


class FakeDup:
    """A duplication that answers AcquireNextFrame with `hr`."""

    def __init__(self, hr):
        self.hr = hr

    def __bool__(self):
        return True

    def call(self, *_a, **_k):
        return self.hr

    def release(self):
        pass


def test_a_graphics_reset_is_a_lost_capture_not_the_end():
    g = object.__new__(sw.DupGrabber)
    g.dup, g.last, g.lost = FakeDup(0x887A0005 - (1 << 32)), None, False   # DEVICE_REMOVED
    with pytest.raises(sw.CaptureLost):
        g.grab()


def test_a_duplication_that_fails_while_warming_up_is_released(monkeypatch):
    closed = []

    def failing_grab(self, timeout_ms=0):
        raise sw.CaptureLost("no frame")
    monkeypatch.setattr(sw.DupGrabber, "_open", lambda self: None)
    monkeypatch.setattr(sw.DupGrabber, "grab", failing_grab)
    monkeypatch.setattr(sw.DupGrabber, "close", lambda self: closed.append(self))
    with pytest.raises(sw.CaptureLost):
        sw.DupGrabber(Monitor(0, 0, W, H, True), W, H)
    assert len(closed) == 1


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


def test_a_cut_out_picture_is_watched_with_its_mask(tab, qapp):
    img = as_qimage(banner()).convertToFormat(QImage.Format_ARGB32)
    big = QImage(img.width() + 20, img.height() + 20, QImage.Format_ARGB32)
    big.fill(Qt.transparent)
    from PySide6.QtGui import QPainter
    p = QPainter(big)
    p.drawImage(10, 10, img)
    p.end()
    t = tab._new(big, "icon")
    t.sound = "s1"
    gray, mask = triggerspanel.load_picture(t.image)
    assert mask is not None and mask.sum() == banner().size and not mask[0].any()
    tab._sync()
    assert tab.watcher._items[t.id].mask is not None


def test_a_plain_picture_is_refused(tab):
    img = QImage(40, 20, QImage.Format_RGB32)
    img.fill(Qt.black)
    assert tab._new(img, "flat") is None and tab.triggers == []


# --------------------------------------------------------------------------- tab fixes

def plain(w=60, h=30) -> QImage:
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(Qt.black)
    return img


@pytest.fixture
def warnings(monkeypatch):
    said = []
    monkeypatch.setattr(triggerspanel.QMessageBox, "warning",
                        lambda _p, title, text: said.append((title, text)))
    return said


def test_a_refused_picture_keeps_the_old_one_and_leaves_no_file(tab, monkeypatch, tmp_path):
    """The picture used to be saved over <id>.png before it was checked."""
    t = tab._new(as_qimage(banner()), "Died")
    before = triggerspanel.load_picture(t.image)[0]
    p = tmp_path / "flat.png"
    plain().save(str(p))
    monkeypatch.setattr(triggerspanel.QFileDialog, "getOpenFileName",
                        lambda *a, **k: (str(p), ""))
    tab._change_picture(tab.rows[t.id])                # "Picture is one plain colour"
    after = triggerspanel.load_picture(t.image)[0]
    assert after.shape == before.shape and np.array_equal(after, before)
    assert tab._new(plain(), "flat") is None           # a new one: nothing kept at all
    assert sorted(triggerspanel.pictures_dir().iterdir()) == [triggerspanel.Path(t.image)]


def test_pictures_are_kept_pixel_for_pixel(app_dir):
    """A picture bigger than 1600 px used to be shrunk when saved, so it no longer
    had the screen's scale and never matched."""
    wide = np.tile(banner(), (4, 25))                  # 96 x 2250
    got = triggerspanel.load_picture(triggerspanel.save_picture(as_qimage(wide), "wide"))[0]
    assert got.shape == wide.shape
    assert np.allclose(got, np.round(wide * 255) / 255, atol=1 / 255)


def test_a_picture_too_big_is_refused_and_one_bigger_than_the_screen_warned(
        tab, warnings, monkeypatch):
    monkeypatch.setattr(triggerspanel, "MAX_SIDE", 500)
    big = np.tile(banner(), (1, 6))                    # 540 wide: over the limit
    assert tab._new(as_qimage(big), "big") is None and tab.triggers == []
    assert warnings[-1][0] == "Picture too big"
    wide = np.tile(banner(), (1, 4))                   # 360 wide: the fake screen is 320
    assert tab._new(as_qimage(wide), "wide") is not None
    assert "bigger than the screen" in warnings[-1][1]


def test_tiny_and_thin_pictures_are_warned_about(tab, warnings, monkeypatch):
    """On a 1920-wide screen: a picture too small to survive the working scale, and
    a cut-out whose opaque part is a 1-px line, are kept but said to be unreliable."""
    monkeypatch.setattr(sw, "monitors", lambda: [Monitor(0, 0, 1920, 1080, True)])
    monkeypatch.setattr(sw, "WORK_WIDTH", 480)
    assert tab._new(as_qimage(banner()[:10, :40]), "tiny") is not None
    assert "very small" in warnings[-1][1]
    warnings.clear()
    img = QImage(200, 60, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    for x in range(10, 190):
        img.setPixelColor(x, 30, Qt.white if x % 7 < 4 else Qt.red)
    assert tab._new(img, "thin") is not None
    assert len(warnings) == 1 and "see-through" in warnings[0][1]
    warnings.clear()
    assert tab._new(as_qimage(np.tile(banner(), (2, 2))), "fine") is not None
    assert warnings == []


def test_a_trigger_whose_sound_was_removed_says_so_and_stays_quiet(tab):
    t = tab._new(as_qimage(banner()), "Died")
    row = tab.rows[t.id]
    row.sound.setCurrentIndex(row.sound.findData("s1"))
    row._on_sound(row.sound.currentIndex())
    tab.board[:] = [("s2", "Win", "fp2")]              # removed on the Sounds tab
    tab.sounds_changed()
    assert row.sound.currentData() == "s1" and row.sound.currentText() == "Removed sound"
    assert "removed" in row.state.text() and "Plays" not in row.state.text()
    tab.btn_watch.setChecked(True)
    tab._on_fired(t.id)
    assert tab.played == [] and row.state.text() != "Played!"
    tab.board.insert(0, ("s1", "Died", "fp1"))         # Undo brings it back
    tab.sounds_changed()
    assert row.sound.currentText() == "Died" and row.state.text().startswith("Plays")
    tab._on_fired(t.id)
    assert tab.played == ["s1"]


def test_a_sound_file_that_fails_to_add_is_given_up_on(tab, monkeypatch, tmp_path):
    t = tab._new(as_qimage(banner()), "Died")
    row = tab.rows[t.id]
    f = tmp_path / "broken.mp3"
    f.write_bytes(b"not audio")
    monkeypatch.setattr(triggerspanel.QFileDialog, "getOpenFileName",
                        lambda *a, **k: (str(f), ""))
    tab._choose_sound_file(row)
    assert t.pending and row.sound.currentText() == "Adding the sound…"
    row.sound.activated.emit(row.sound.currentIndex())   # picking it again changes nothing
    assert t.pending
    row.sound.activated.emit(row.sound.findData(triggerspanel.FILE))   # then cancelled
    assert row.sound.currentText() == "Adding the sound…" and t.pending
    tab.sounds_changed()                               # still importing: keep waiting
    assert t.pending
    tab.import_done()                                  # the import failed
    assert not t.pending and not t.sound
    assert row.sound.currentIndex() == 0 and row.state.text() == "Pick the sound to play"
    assert tab.cfg.screen["triggers"][0]["pending"] == ""


def test_watching_that_dies_by_itself_stays_on_for_next_launch(tab, qapp, monkeypatch):
    """The thread dying (a capture that can't be opened) stops watching, but isn't
    saved as switched off: next launch tries again."""
    def broken(*_a, **_k):
        raise OSError("no screen")
    monkeypatch.setattr(sw, "open_grabber", broken)
    t = tab._new(as_qimage(banner()), "Died")
    t.sound = "s1"
    tab.set_watching(True)
    assert tab.cfg.screen["on"] is True
    assert process_events(qapp, lambda: not tab.is_active())
    assert tab.cfg.screen["on"] is True and "no screen" in tab.warn.text()
    tab.set_watching(False)                            # switched off by hand: remembered
    assert tab.cfg.screen["on"] is False


def test_the_screen_list_follows_screens_plugged_in_later(qapp, app_dir, fake_screen,
                                                          monkeypatch):
    mons = [Monitor(0, 0, W, H, True)]
    monkeypatch.setattr(sw, "monitors", lambda: list(mons))
    tab = TriggersTab(Config(), lambda: None, lambda: [], lambda _s: None)
    try:
        assert tab.cb_monitor.count() == 1 and not tab.cb_monitor.isVisibleTo(tab)
        mons.append(Monitor(W, 0, W, H))
        tab.set_watching(True)
        assert tab.cb_monitor.count() == 2 and tab.cb_monitor.isVisibleTo(tab)
        tab.set_watching(False)
        mons.pop()
        tab.show()
        qapp.processEvents()
        assert tab.cb_monitor.count() == 1
    finally:
        tab.hide()
        tab.shutdown()


def test_the_screen_list_is_wide_enough_for_its_longest_entry(qapp, app_dir, fake_screen,
                                                              monkeypatch):
    """"Screen 2: 1920×1080" was cut off at "Screen 2: 1920×10": the list must size
    itself to its entries, and again when they're refilled."""
    mons = [Monitor(0, 0, 2560, 1440, True), Monitor(2560, 0, 1920, 1080)]
    monkeypatch.setattr(sw, "monitors", lambda: list(mons))
    tab = TriggersTab(Config(), lambda: None, lambda: [], lambda _s: None)
    try:
        cb = tab.cb_monitor
        longest = max((cb.itemText(i) for i in range(cb.count())), key=len)
        assert longest == "Screen 1: 2560×1440  (main)"
        assert cb.sizeHint().width() >= cb.fontMetrics().horizontalAdvance(longest)
        mons.append(Monitor(0, 1440, 3840, 2160))
        tab.set_watching(True)
        tab.set_watching(False)
        assert cb.count() == 3
        assert cb.sizeHint().width() >= cb.fontMetrics().horizontalAdvance("Screen 3: 3840×2160")
    finally:
        tab.shutdown()
