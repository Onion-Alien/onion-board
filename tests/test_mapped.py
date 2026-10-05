"""Long sounds stay on disk (soundboard.mapped): mapped cache files, warmed before
they play, and deletes that cope with Windows refusing to remove a mapped file."""
import gc

import numpy as np
import pytest
from conftest import process_events
from test_engine import engine_with
from test_mainwindow import window  # noqa: F401 - the real MainWindow, offscreen

from soundboard import library, mapped, trash
from soundboard.library import SR, SoundMeta, cache_path, load_cached, prune_cache, store_cached


@pytest.fixture
def map_all(monkeypatch):
    """Every cache file is mapped, however short."""
    monkeypatch.setattr(mapped, "MAP_MIN_BYTES", 0)


def song(seconds=2.0):
    t = np.arange(int(seconds * SR)) / SR
    x = 0.3 * np.sin(2 * np.pi * 220 * t)
    return np.stack([x, -x], 1).astype(np.float32)


def test_long_sounds_are_mapped_short_ones_read_in(app_dir, monkeypatch):
    monkeypatch.setattr(mapped, "MAP_MIN_BYTES", SR * 4)   # over a second is "long"
    short = store_cached("short", song(0.5))
    long_ = store_cached("long", song(2.0))
    a, b = load_cached("short"), load_cached("long")
    assert not mapped.is_mapped(a) and np.array_equal(a, short)
    assert mapped.is_mapped(b) and np.array_equal(b, long_)
    assert type(b) is np.ndarray            # not np.memmap: no Python code per slice
    assert not b.flags.writeable            # nothing can scribble on the cache file


def test_past_the_ram_budget_everything_is_mapped(app_dir, monkeypatch):
    monkeypatch.setattr(mapped, "RAM_BUDGET", 0)
    store_cached("a", song(0.2))
    assert mapped.is_mapped(load_cached("a"))


def test_warm_reads_a_mapped_sound_and_ignores_ram(app_dir, map_all):
    store_cached("w", song(3.0))
    d = load_cached("w")
    for frame in (0, SR, len(d) - 1, len(d) + 99, -5):
        mapped.warm(d, frame)                 # never raises, whatever the position
    mapped.warm(np.zeros((0, 2), np.int16))
    mapped.warm(np.zeros((10, 2), np.int16))


def test_a_mapped_sound_plays_the_same_as_one_in_ram(app_dir, map_all):
    store_cached("p", song(1.0))
    on_disk = load_cached("p")
    outs = []
    for data in (on_disk, np.array(on_disk)):
        e = engine_with("main")
        e.play("p", data, 1.0, start=0.25)
        assert e.seek("p", 0.5)
        out = np.zeros((480, 2), np.float32)
        e._main(out, 480)
        e._main(out, 480)
        outs.append(out.copy())
    assert np.abs(outs[0]).max() > 0.1 and np.array_equal(outs[0], outs[1])


def test_deleting_a_sound_whose_audio_is_still_held_doesnt_fail(app_dir, map_all, monkeypatch):
    monkeypatch.setattr(library, "CACHE_GRACE_S", 0)
    store_cached("x", song(1.0))
    store_cached("x", song(1.0), "fx1")
    held = load_cached("x")                    # e.g. a voice still fading out
    library.unlink_cache("x")                  # Windows refuses the mapped one: no error
    assert not cache_path("x", "fx1").exists()
    del held
    gc.collect()
    prune_cache(set())                         # later, once it's let go
    assert not cache_path("x").exists()


def test_replacing_a_mapped_cache_file_doesnt_fail(app_dir, map_all):
    store_cached("r", song(1.0))
    held = load_cached("r")
    out = store_cached("r", song(1.0))         # the same content again: kept in RAM
    assert np.array_equal(out, held)


def test_binning_a_sound_whose_audio_is_held_still_bins_it(app_dir, map_all):
    f = app_dir / "x.wav"
    f.write_bytes(b"")
    store_cached("b", song(1.0))
    held = load_cached("b")
    trash.put_sound(SoundMeta(id="b", name="B", file=str(f)), 0)
    assert [i.name for i in trash.items(trash.SOUND)] == ["B"]
    assert held.shape[0] == SR


def test_remove_undo_and_bin_with_mapped_sounds(window, qapp, map_all):  # noqa: F811
    window.audio.clear()
    window._load_all()
    window._load_thread.join(10)
    assert process_events(qapp, lambda: all(m.id in window.audio for m in window.cfg.sounds))
    assert all(mapped.is_mapped(window.audio[m.id]) for m in window.cfg.sounds)
    window.play("s1", now=True)
    window.remove_sound("s1")
    window.undo_remove()                         # undo keeps the mapped audio
    assert process_events(qapp, lambda: "s1" in window.audio)
    window.remove_sound("s1")
    window._finish_removals()                    # into the bin: the cache goes
    keep = library.cache_keep(window._live_metas())

    def pruned():   # once the fading voice and undo's prepare thread let go of it
        gc.collect()
        prune_cache(keep)
        return not cache_path("s1").exists()
    assert process_events(qapp, pruned)
    assert [i.name for i in trash.items(trash.SOUND)]


def test_a_sound_cached_just_now_is_mapped_too(app_dir, map_all):
    x = song(1.0)
    out = store_cached("new", x)                # decoded, imported or rendered now
    assert mapped.is_mapped(out) and np.array_equal(out, library.to_int16(x))
