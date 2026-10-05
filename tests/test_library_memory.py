"""The decoded cache's helpers on long sounds: no song-sized temporaries, no whole
file read for a waveform, and no pruning of an import that's still running."""
import os
import time

import numpy as np

from soundboard import library
from soundboard.library import SR, SoundMeta, cache_path, prune_cache, store_cached


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
    x = (rng.standard_normal((5000, 2)) * 0.7).astype(np.float32)   # some past ±1
    x[:4] = [[1.0, -1.0], [2.0, -2.0], [0.5 / library.I16, -0.5 / library.I16], [0, 0]]
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


def test_original_peaks_of_a_long_sound_read_only_a_little(app_dir, monkeypatch):
    m = SoundMeta(id="long1", name="t", file="missing.wav")
    secs = 60
    t = np.arange(SR * secs) / SR
    env = (np.floor(t) % 2).astype(np.float32)          # a second loud, a second quiet
    tone = np.sin(2 * np.pi * 300 * t).astype(np.float32) * env * 0.8
    store_cached(m.id, np.stack([tone, tone], 1))
    real = np.load
    seen = []

    def load(path, mmap_mode=None, **kw):
        a = real(path, mmap_mode=mmap_mode, **kw)
        seen.append(mmap_mode)
        return a
    monkeypatch.setattr(library.np, "load", load)
    got, length = library.original_peaks(m, 60)
    assert seen == ["r"] and length == secs and got.shape == (60,)
    full = library.peaks(library.load_cached(m.id), 60)
    assert np.allclose(got, full, atol=0.02)            # same picture
    assert got[1::2].min() > 0.7 and got[0::2].max() < 0.01


def test_prune_cache_leaves_an_import_in_flight(app_dir):
    store_cached("live", np.zeros((10, 2), np.float32))
    store_cached("new", np.zeros((10, 2), np.float32))    # imported, not in the list yet
    tmp = cache_path("new2").with_suffix(".tmp.npy")
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
