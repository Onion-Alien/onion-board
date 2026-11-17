"""The decoded cache's helpers on long sounds: no song-sized temporaries, no whole
file read for a waveform, and no pruning of an import that's still running."""
import os
import time

import numpy as np

from soundboard.sounds import library
from soundboard.sounds.library import SR, SoundMeta, cache_path, prune_cache, store_cached


def _old_to_int16(data):
    return np.ascontiguousarray(np.clip(np.rint(data * library.I16), -library.I16 - 1,
                                        library.I16).astype(np.int16))


def _old_peaks(data, n):
    scale = 1 / library.I16 if data.dtype == np.int16 else 1.0
    edges = np.linspace(0, len(data), n + 1).astype(np.int64)
    out = np.zeros(n, np.float32)
    for i in range(n):
        a, b = edges[i], max(edges[i + 1], edges[i] + 1)
        seg = data[a:min(b, len(data))]
        if len(seg):
            out[i] = float(np.abs(seg.astype(np.float32)).max()) * scale
    return np.clip(out, 0.0, 1.0)


def test_to_int16_is_unchanged():
    rng = np.random.default_rng(1)
    # (within ±1: past it, a limiter turns the peaks down first: test_audio_quality)
    x = (rng.standard_normal((5000, 2)) * 0.7).clip(-1, 1).astype(np.float32)
    x[:4] = [[1.0, -1.0], [-1.0, 1.0], [0.5 / library.I16, -0.5 / library.I16], [0, 0]]
    for data in (x, x[::2], x.astype(np.float64)):
        got = library.to_int16(data)
        assert got.dtype == np.int16 and got.flags.c_contiguous
        assert np.array_equal(got, _old_to_int16(data))
    i16 = np.zeros((3, 2), np.int16)
    assert library.to_int16(i16) is i16


def test_peaks_match_the_slice_by_slice_loop():
    rng = np.random.default_rng(2)
    data = (rng.standard_normal((9_999, 2)) * 9000).clip(-32768, 32767).astype(np.int16)
    data[5, 1] = -32768   # abs() of this one overflows in int16
    for n in (1, 7, 400, 20_000):   # more columns than frames too
        assert np.allclose(library.peaks(data, n), _old_peaks(data, n))
    f = data.astype(np.float32) / library.I16
    assert np.allclose(library.peaks(f, 50), _old_peaks(f, 50))
    assert len(library.peaks(data[:0], 5)) == 5


def _long_sound(sid="long1", secs=60):
    m = SoundMeta(id=sid, name="t", file="missing.wav")
    t = np.arange(SR * secs) / SR
    env = (np.floor(t) % 2).astype(np.float32)          # a second loud, a second quiet
    tone = np.sin(2 * np.pi * 300 * t).astype(np.float32) * env * 0.8
    tone[SR * 7 + 5] = -1.0                              # int16's -32768: abs() overflows
    store_cached(m.id, np.stack([tone, tone * 0.5], 1))
    return m


def test_original_peaks_of_a_long_sound_never_load_it_whole(app_dir, monkeypatch):
    m = _long_sound()
    real = np.load
    seen = []

    def load(path, mmap_mode=None, **kw):
        a = real(path, mmap_mode=mmap_mode, **kw)
        seen.append(mmap_mode)
        return a
    monkeypatch.setattr(library.np, "load", load)
    got, length = library.original_peaks(m, 60)
    assert seen and set(seen) == {"r"} and length == 60 and got.shape == (60,)
    full = library.peaks(library.load_cached(m.id), 60)
    assert np.allclose(got, full)                        # the same picture, exactly
    assert got[1::2].min() > 0.7 and got[0::2].max() < 0.01 + 1 / 2400


def test_a_long_sounds_waveform_is_read_through_once_then_kept(app_dir, monkeypatch):
    """Scattered reads of a long song's cache took up to half a minute on a file Windows
    hadn't read lately (Edit sound froze switching to Advanced, the song playing
    stuttered): it's read once from start to end, and its waveform kept beside it."""
    from soundboard.sounds import decoding
    m = _long_sound()
    data = library.load_cached(m.id)
    reads = []
    real_read = decoding._read_wave
    monkeypatch.setattr(decoding, "_read_wave", lambda *a: reads.append(1) or real_read(*a))
    fine, _ = library.original_peaks(m, decoding.WAVE_PEAKS)
    assert np.allclose(fine, library.peaks(data, decoding.WAVE_PEAKS))
    assert decoding.wave_path(m.id).is_file() and reads == [1]
    small, _ = library.original_peaks(m, 400)            # Simple's: from the kept one
    assert reads == [1] and np.allclose(small, library.peaks(data, 400))
    # the cache made again (a new source): so is the waveform
    later = time.time() + 5
    os.utime(cache_path(m.id), (later, later))
    library.original_peaks(m, 400)
    assert reads == [1, 1]


def test_two_asks_at_once_read_the_song_once(app_dir, monkeypatch):
    """Edit's small and big waveform ask together: one read of the song, not two."""
    import threading

    from soundboard.sounds import decoding
    m = _long_sound("long2", 30)
    reads, go = [], threading.Event()
    real_read = decoding._read_wave

    def slow(*a):
        reads.append(1)
        go.wait(5)
        return real_read(*a)
    monkeypatch.setattr(decoding, "_read_wave", slow)
    got = []
    ts = [threading.Thread(target=lambda n=n: got.append(library.original_peaks(m, n)[0]))
          for n in (400, decoding.WAVE_PEAKS)]
    for t in ts:
        t.start()
    time.sleep(0.2)
    go.set()
    for t in ts:
        t.join(10)
    assert reads == [1] and sorted(len(g) for g in got) == [400, decoding.WAVE_PEAKS]


def test_the_kept_waveform_survives_a_prune_and_goes_with_its_sound(app_dir):
    from soundboard.sounds import decoding
    m = _long_sound("long3", 30)
    library.original_peaks(m, 400)
    w = decoding.wave_path(m.id)
    old = time.time() - 3600
    os.utime(w, (old, old))
    prune_cache(library.cache_keep([m]))
    assert w.is_file()
    prune_cache(library.cache_keep([]))
    assert not w.is_file()


def test_prune_cache_leaves_an_import_in_flight(app_dir):
    store_cached("live", np.zeros((10, 2), np.float32))
    store_cached("new", np.zeros((10, 2), np.float32))    # imported, not in the list yet
    tmp = library.CACHE_DIR / "new2.0123abcd.tmp.npy"
    np.save(tmp, np.zeros((10, 2), np.int16))              # still being written
    stale = cache_path("gone")
    np.save(stale, np.zeros((10, 2), np.int16))
    old = time.time() - library.CACHE_GRACE_S - 60
    os.utime(stale, (old, old))
    replaced = cache_path("live", "oldfx")                 # a replaced effects version
    np.save(replaced, np.zeros((10, 2), np.int16))
    prune_cache({"live"})
    assert cache_path("live").exists() and cache_path("new").exists() and tmp.exists()
    assert not stale.exists() and not replaced.exists()
