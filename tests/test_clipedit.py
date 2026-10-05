"""The clip editor's audio side: the rolling listen buffer keeps the newest
LISTEN_S seconds with a waveform that lines up, and a take's edits (cut, paste,
fades, gain, reverse) do what they say and undo exactly."""
import threading

import numpy as np

from soundboard import clipedit
from soundboard.clipedit import BIN, LiveBuffer, Take, bin_peaks
from soundboard.engine import SR


def ramp_audio(n, start=0):
    """Stereo audio whose every frame says where it came from (frame index / 1e7)."""
    v = (np.arange(start, start + n, dtype=np.float64) / 1e7).astype(np.float32)
    return np.stack([v, v], 1)


def test_bin_peaks_takes_the_loudest_of_each_slice():
    x = np.zeros((BIN * 2 + 10, 2), np.float32)
    x[5, 0] = -0.5
    x[BIN + 3, 1] = 0.25
    x[-1, 0] = 2.0   # over full scale: shown as full
    assert np.allclose(bin_peaks(x), [0.5, 0.25, 1.0])
    assert len(bin_peaks(np.zeros((0, 2), np.float32))) == 0


def test_live_buffer_keeps_the_newest_seconds_in_order():
    buf = LiveBuffer(seconds=1.0)
    cap = buf.cols * BIN
    pushed = 0
    for size in (100, 333, BIN, 4096, 17, 9000, 48000, 1):   # odd chunk sizes
        buf.push(ramp_audio(size, pushed))
        pushed += size
    snap = buf.snapshot()
    kept = pushed // BIN * BIN   # a partial BIN waits for the next chunk
    assert len(snap) == min(kept, cap)
    assert buf.total == kept
    # the last frame kept is the newest whole one, and the rest run back from it
    assert np.allclose(snap[:, 0], np.arange(kept - len(snap), kept) / 1e7)
    wave, total = buf.peaks()
    assert total == kept and len(wave) == len(snap) // BIN
    assert np.allclose(wave, bin_peaks(snap))


def test_live_buffer_takes_mono_and_a_huge_chunk():
    buf = LiveBuffer(seconds=0.5)
    buf.push(np.full(SR * 3, 0.1, np.float32))   # 3 s at once into a 0.5 s buffer
    snap = buf.snapshot()
    assert snap.shape == (buf.cols * BIN, 2) and np.allclose(snap, 0.1)
    assert abs(buf.seconds - buf.cols * BIN / SR) < 1e-9
    buf.clear()
    assert len(buf.snapshot()) == 0 and buf.seconds == 0


def test_live_buffer_push_from_another_thread_while_reading():
    buf = LiveBuffer(seconds=0.5)
    stop = threading.Event()

    def feed():
        i = 0
        while not stop.is_set():
            buf.push(ramp_audio(480, i))
            i += 480

    t = threading.Thread(target=feed)
    t.start()
    try:
        for _ in range(200):
            snap = buf.snapshot()
            d = np.diff(snap[:, 0].astype(np.float64)) * 1e7
            assert np.allclose(d, 1.0, atol=0.6)   # always one unbroken run
    finally:
        stop.set()
        t.join()


def take_of(n):
    return Take(ramp_audio(n))


def test_select_is_clamped_and_ordered():
    t = take_of(1000)
    t.select(800, -5)
    assert (t.a, t.b) == (0, 800)
    t.select(900, 5000)
    assert (t.a, t.b) == (900, 1000)
    assert t.span() == (900, 1000)
    t.select(400, 400)
    assert not t.has_selection and t.span() == (0, 1000)


def test_delete_closes_the_gap_and_undo_brings_it_back():
    t = take_of(10000)
    before = t.data.copy()
    t.select(2000, 5000)
    assert t.delete()
    assert len(t) == 7000 and (t.a, t.b) == (2000, 2000) and t.edited
    # away from the click-free join it's the audio either side, untouched
    assert np.allclose(t.data[:1500], before[:1500])
    assert np.allclose(t.data[2500:], before[5500:])
    assert t.undo()
    assert np.array_equal(t.data, before) and (t.a, t.b) == (2000, 5000) and not t.edited
    assert t.redo() and len(t) == 7000


def test_deleting_everything_or_nothing_does_nothing():
    t = take_of(1000)
    assert not t.delete()
    t.select_all()
    assert not t.delete() and not t.crop()
    assert not t.can_undo


def test_crop_keeps_only_the_selection():
    t = take_of(10000)
    t.select(3000, 4000)
    assert t.crop()
    assert len(t) == 1000 and np.allclose(t.data[:, 0], np.arange(3000, 4000) / 1e7)
    assert (t.a, t.b) == (0, 1000)


def test_paste_at_cursor_and_over_selection():
    t = Take(np.zeros((10000, 2), np.float32))
    piece = np.full((500, 2), 0.5, np.float32)
    t.select(2000, 2000)
    assert t.paste(piece)
    assert len(t) == 10500 and (t.a, t.b) == (2000, 2500)
    assert np.allclose(t.data[2150:2350], 0.5)
    t.select(0, 6000)
    assert t.paste(piece)
    assert len(t) == 4500 + 500
    assert not t.paste(np.zeros((0, 2), np.float32))


def test_paste_never_grows_past_the_length_cap(monkeypatch):
    monkeypatch.setattr(clipedit, "MAX_FRAMES", 1200)
    t = take_of(1000)
    t.select(1000, 1000)
    assert t.paste(ramp_audio(500))
    assert len(t) == 1200
    t.select(1200, 1200)
    assert not t.paste(ramp_audio(10))   # full: nothing fits


def test_fades_gain_reverse_and_silence_touch_only_the_selection():
    t = Take(np.full((1000, 2), 0.5, np.float32))
    t.select(100, 200)
    assert t.fade_in()
    assert t.data[100, 0] == 0 and np.isclose(t.data[199, 0], 0.5) and t.data[50, 0] == 0.5
    assert t.fade_out()
    assert t.data[199, 0] == 0
    t.select(500, 600)
    assert t.gain(4.0)
    assert np.allclose(t.data[500:600], 1.0) and t.data[600, 0] == 0.5   # clipped at full
    assert t.silence() and np.allclose(t.data[500:600], 0)
    r = take_of(100)
    r.select(10, 20)
    assert r.reverse()
    assert np.allclose(r.data[10:20, 0], np.arange(19, 9, -1) / 1e7)
    for _ in range(4):
        assert t.undo()
    assert np.allclose(t.data, 0.5) and not t.undo()


def test_with_nothing_selected_edits_apply_to_the_whole_take():
    t = Take(np.full((1000, 2), 0.1, np.float32))
    assert t.normalize()
    assert np.isclose(np.abs(t.data).max(), 0.89)
    assert not Take(np.zeros((100, 2), np.float32)).normalize()   # silence stays silence


def test_undo_memory_is_capped(monkeypatch):
    monkeypatch.setattr(clipedit, "UNDO_BYTES", 3 * 1000 * 2 * 4)   # about 3 steps
    t = Take(np.full((1000, 2), 0.5, np.float32))
    for _ in range(10):
        t.gain(0.9)
    steps = 0
    while t.undo():
        steps += 1
    assert 1 <= steps <= 4
