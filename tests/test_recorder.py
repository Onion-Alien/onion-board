import numpy as np

from soundboard.recorder import CLIP_S, Recorder
from soundboard.engine import SR


def chunk(start, n=1024):
    x = np.zeros((n, 2), np.float32)
    x[:, 0] = (np.arange(start, start + n) % 1000) / 1000 * 0.5
    x[:, 1] = -x[:, 0]
    return x


def test_replay_buffer_returns_the_last_clip_seconds(tmp_path):
    r = Recorder(tmp_path / "spool.wav")
    assert len(r.last()) == 0
    pos = 0
    for _ in range(CLIP_S * SR // 1024 + 50):      # more than the buffer holds
        r.push(chunk(pos))
        pos += 1024
    last = r.last()
    assert len(last) == CLIP_S * SR
    assert np.allclose(last[-1024:], chunk(pos - 1024))


def test_recording_spools_to_disk_and_reads_back(tmp_path):
    spool = tmp_path / "spool.wav"
    r = Recorder(spool)
    assert not r.recording and len(r.stop()) == 0
    r.start()
    assert r.recording and spool.exists()
    pos = 0
    for _ in range(20):
        r.push(chunk(pos))
        pos += 1024
    assert r.rec_frames == pos
    data = r.stop()
    assert not r.recording and not spool.exists()
    assert data.shape == (pos, 2) and data.dtype == np.float32
    assert np.max(np.abs(data[:1024] - chunk(0))) < 1 / 32767 * 2      # 16-bit spool


def test_recording_falls_back_to_memory_if_spool_cannot_open(tmp_path):
    r = Recorder(tmp_path / "no_such_dir_file" / "x" / "spool.wav")
    (tmp_path / "no_such_dir_file").write_text("a file, not a dir")   # mkdir will fail
    r.start()
    assert r.recording and r._spool is None
    r.push(chunk(0))
    data = r.stop()
    assert np.array_equal(data, chunk(0))


def test_replay_buffer_is_made_on_first_push_and_can_be_freed(tmp_path):
    r = Recorder(tmp_path / "spool.wav")
    assert r.replay is None and len(r.last()) == 0     # nothing allocated yet
    r.push(chunk(0))
    assert r.replay is not None and np.array_equal(r.last(), chunk(0))
    r.release_replay()
    assert r.replay is None and len(r.last()) == 0
    r.push(chunk(5))
    assert np.array_equal(r.last(), chunk(5))
