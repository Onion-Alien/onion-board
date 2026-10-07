"""A long song's cut shares are saved next to its cache file and reused next start."""
import gc
import json
import os

import numpy as np

from soundboard import destination, sharestore
from soundboard import engine as eng
from soundboard.engine import SR, Engine


def _mapped(path, seconds=3.0, amp=0.3):
    t = np.arange(int(seconds * SR)) / SR
    x = (amp * 32767 * np.sin(2 * np.pi * 50 * t)).astype(np.int16)
    np.save(path, np.stack([x, x], 1))
    return np.asarray(np.load(path, mmap_mode="r"))


def _counting(monkeypatch):
    calls = []
    real = destination.cut_shares
    monkeypatch.setattr(eng.destination, "cut_shares",
                        lambda d, r, *a, **k: calls.append(1) or real(d, r, *a, **k))
    return calls


def _fresh_start():
    sharestore.save()
    sharestore._dirs.clear()   # what a new app run sees: only the file


def test_saved_shares_are_reused_next_start(tmp_path, monkeypatch):
    calls = _counting(monkeypatch)
    song = _mapped(tmp_path / "s.npy")
    first = Engine().cut_shares("s", song)
    assert calls == [1] and first
    _fresh_start()
    assert json.loads((tmp_path / sharestore.NAME).read_text())["files"]["s.npy"]
    again = Engine().cut_shares("s", np.asarray(np.load(tmp_path / "s.npy", mmap_mode="r")))
    assert calls == [1]                     # read back, not worked out
    assert again == first


def test_a_changed_file_is_worked_out_again(tmp_path, monkeypatch):
    calls = _counting(monkeypatch)
    e = Engine()
    e.cut_shares("s", _mapped(tmp_path / "s.npy"))
    _fresh_start()
    gc.collect()                            # unmapped: Windows can replace it now
    song = _mapped(tmp_path / "s.npy", seconds=4.0, amp=0.1)   # an effects re-bake
    Engine().cut_shares("s", song)
    assert len(calls) == 2


def test_sounds_in_ram_are_not_saved(tmp_path, monkeypatch):
    calls = _counting(monkeypatch)
    Engine().cut_shares("c", np.full((SR, 2), 100, np.int16))
    _fresh_start()
    assert calls == [1] and not (tmp_path / sharestore.NAME).exists()


def test_a_broken_or_old_file_is_ignored(tmp_path, monkeypatch):
    calls = _counting(monkeypatch)
    song = _mapped(tmp_path / "s.npy")
    st = os.stat(tmp_path / "s.npy")
    (tmp_path / sharestore.NAME).write_text(json.dumps({
        "version": 0, "cuts": list(destination.LOWCUTS),
        "files": {"s.npy": [st.st_size, st.st_mtime_ns, SR, {"60": 9.0}]}}))
    sharestore._dirs.clear()
    assert Engine().cut_shares("s", song).get(60) != 9.0 and calls == [1]
    (tmp_path / sharestore.NAME).write_text("{not json")
    sharestore._dirs.clear()
    Engine().cut_shares("s2", song)
    assert len(calls) == 2


def test_files_that_are_gone_are_left_out(tmp_path):
    a = _mapped(tmp_path / "a.npy")
    Engine().cut_shares("a", a)
    (table,) = [t for t in sharestore._dirs.values() if "a.npy" in t]
    table["gone.npy"] = [1, 2, SR, {}]
    _fresh_start()
    files = json.loads((tmp_path / sharestore.NAME).read_text())["files"]
    assert set(files) == {"a.npy"}
