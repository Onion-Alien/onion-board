"""Long sounds stay on disk (soundboard.mapped): mapped cache files, warmed before
they play, and deletes that cope with Windows refusing to remove a mapped file."""
import gc
import time

import numpy as np
import pytest
from conftest import process_events
from test_engine import engine_with
from test_mainwindow import window  # noqa: F401 - the real MainWindow, offscreen

from soundboard.sounds import library
from soundboard import mapped, trash
from soundboard.sounds.library import (SR, SoundMeta, cache_path, load_cached, prune_cache,
                                       store_cached)


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


def test_deleting_a_sound_whose_audio_is_still_held_doesnt_fail(app_dir, map_all):
    store_cached("x", song(1.0))
    store_cached("x", song(1.0), "fx1")
    held = load_cached("x")                    # e.g. a voice still fading out
    library.unlink_cache("x")                  # Windows refuses the mapped one: no error
    assert not cache_path("x", "fx1").exists()
    del held
    gc.collect()
    prune_cache(set())                         # later, once it's let go: at once,
    assert not cache_path("x").exists()        # not after the grace a new import gets


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
    window.soundctl._load_all()
    window.soundctl._load_thread.join(10)
    assert process_events(qapp, lambda: all(m.id in window.audio for m in window.cfg.sounds))
    assert all(mapped.is_mapped(window.audio[m.id]) for m in window.cfg.sounds)
    window.playctl.play("s1", now=True)
    window.rmctl.remove_sound("s1")
    window.rmctl.undo_remove()                         # undo keeps the mapped audio
    assert process_events(qapp, lambda: "s1" in window.audio)
    window.rmctl.remove_sound("s1")
    # undo's prepare thread (or a fading voice) may still hold the audio when the
    # removal finishes, as on a loaded CI runner: always so here
    held = window.rmctl._removed[-1][2]
    window.rmctl._finish_removals()                    # into the bin: the cache goes...
    window.rmctl._wait_bin()
    keep = library.cache_keep(window.soundctl._live_metas())
    del held

    def pruned():   # ...or, if it was refused, the next prune once it's let go
        gc.collect()
        prune_cache(keep)
        return not cache_path("s1").exists()
    assert process_events(qapp, pruned)
    assert [i.name for i in trash.items(trash.SOUND)]


def test_a_sound_cached_just_now_is_mapped_too(app_dir, map_all):
    x = song(1.0)
    out = store_cached("new", x)                # decoded, imported or rendered now
    assert mapped.is_mapped(out) and np.array_equal(out, library.to_int16(x))


def test_warm_and_prefetch_ask_for_minutes_not_the_whole_file(app_dir, map_all, monkeypatch):
    """A 2-hour song's whole file took 70 ms just to ask for, at every press and seek."""
    store_cached("long", song(3.0))
    d = load_cached("long")
    asked = []
    monkeypatch.setattr(mapped, "_prefetch", lambda _p, n, arr, _f: asked.append(
        [arr[i].NumberOfBytes for i in range(n)]))
    monkeypatch.setattr(mapped, "AHEAD_S", 1.0)
    mapped.warm(d, 0)
    assert asked[-1] == [SR * 4]                        # one second, not three
    mapped.prefetch(d, int(2.5 * SR), 1.0, wrap=True)   # a loop: the rest from the start
    assert asked[-1] == [SR // 2 * 4, SR // 2 * 4]
    mapped.prefetch(d, int(2.5 * SR), 1.0)              # a one-shot stops at its end
    assert asked[-1] == [SR // 2 * 4]
    mapped.prefetch(np.array(d), 0)                     # in RAM: nothing to ask for
    assert len(asked) == 3


def test_a_long_sound_playing_keeps_its_next_minutes_asked_for(app_dir, map_all, monkeypatch):
    from soundboard import engine as E
    store_cached("long", song(3.0))
    d = load_cached("long")
    asked = []
    monkeypatch.setattr(mapped, "prefetch", lambda a, frame=0, *_a, **_k: asked.append(frame))
    monkeypatch.setattr(mapped, "AHEAD_S", 1.0)
    monkeypatch.setattr(E, "READ_AHEAD_EVERY_S", 0.01)
    e = engine_with("main")
    v = e.play("long", d, 1.0)
    assert e._ahead_on
    v.pos["main"] = 2 * SR                     # played on (or sought) past what was asked
    deadline = time.monotonic() + 5
    while 2 * SR not in asked and time.monotonic() < deadline:
        time.sleep(0.01)
    assert 2 * SR in asked
    e.stop_all()
    v.done.add("main")                         # finished: the thread lets go and ends
    while e._ahead_on and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not e._ahead_on


def test_a_very_long_sound_is_never_copied_at_another_rate(app_dir, map_all, monkeypatch):
    """It plays read at the device's rate: a 2-hour song's copy took 17 s and 1.2 GB."""
    from soundboard import engine as E
    store_cached("long", song(3.0))
    d = load_cached("long")
    e = engine_with("main")
    e.rates["main"] = 44100
    monkeypatch.setattr(E, "NO_COPY_S", 2.0)
    copies = []
    monkeypatch.setattr(e, "_resample_soon", lambda *a: copies.append(a))
    v = e.play("long", d, 1.0)
    assert not copies and v.step["main"] == SR / 44100
    monkeypatch.setattr(E, "NO_COPY_S", 5.0)   # shorter than that: copied as before
    e.play("long", d, 1.0)
    assert len(copies) == 1
