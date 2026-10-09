"""Phase 2: bounded decoding, the int16 cache, imports, clips and dedupe."""
import os
import time

import numpy as np
import pytest
import soundfile as sf

from soundboard import library
from soundboard.library import (SR, SoundMeta, cache_path, fingerprint, import_file, load_cached,
                     load_sound, prune_cache, save_clip, store_cached, to_float32, to_int16)


def wav(path, seconds=1.0, rate=SR, hz=440, channels=2):
    t = np.arange(int(seconds * rate)) / rate
    x = 0.5 * np.sin(2 * np.pi * hz * t)
    sf.write(path, np.stack([x] * channels, 1), rate, subtype="PCM_16")
    return path


# ---------------------------------------------------------------- int16 <-> float

def test_int16_round_trip_is_transparent():
    x = np.tanh(np.random.default_rng(0).standard_normal((1000, 2))).astype(np.float32)
    i = to_int16(x)
    assert i.dtype == np.int16 and to_int16(i) is i
    assert np.max(np.abs(to_float32(i) - x)) < 0.5 / 32767 + 1e-6     # rounded, not truncated


def test_int16_never_wraps():
    # (over full scale it's turned down by a limiter, not clipped: test_audio_quality)
    x = np.array([[2.0, -2.0]], np.float32)
    left, right = to_int16(x)[0]
    assert 32000 < left <= 32767 and -32768 <= right < -32000


# ---------------------------------------------------------------- decoding

def test_decode_reads_only_the_first_max_seconds(app_dir, monkeypatch):
    monkeypatch.setattr(library, "MAX_SECONDS", 1)
    p = wav(app_dir / "long.wav", seconds=3.0)
    assert len(library.decode(str(p))) == SR


def test_decode_resamples_and_widens_mono(app_dir):
    p = wav(app_dir / "m.wav", seconds=0.5, rate=22050, channels=1)
    d = library.decode(str(p))
    assert d.shape == (SR // 2, 2) and d.dtype == np.float32
    assert np.allclose(d[:, 0], d[:, 1])


# ---------------------------------------------------------------- cache

def test_cache_round_trip_and_damage_tolerance(app_dir):
    x = (np.random.default_rng(1).standard_normal((SR, 2)) * 0.2).astype(np.float32)
    i = store_cached("abc", x)
    assert cache_path("abc").exists() and not cache_path("abc").with_suffix(".tmp.npy").exists()
    back = load_cached("abc")
    assert back.dtype == np.int16 and np.array_equal(back, i)
    cache_path("abc").write_bytes(b"garbage")
    assert load_cached("abc") is None
    np.save(cache_path("abc"), np.zeros((10, 3), np.int16))     # wrong shape
    assert load_cached("abc") is None
    assert load_cached("nope") is None


def test_load_sound_decodes_once_then_uses_the_cache(app_dir, monkeypatch):
    p = wav(app_dir / "s.wav")
    m = SoundMeta(id="s1", name="s", file=str(p))
    calls = []
    real = library.decode
    monkeypatch.setattr(library, "decode", lambda path: calls.append(path) or real(path))
    a = load_sound(m)
    b = load_sound(m)
    assert calls == [str(p)]
    assert a.dtype == np.int16 and np.array_equal(a, b)


def test_prune_cache_removes_orphans_only(app_dir):
    store_cached("keep", np.zeros((10, 2), np.float32))
    store_cached("gone", np.zeros((10, 2), np.float32))
    old = time.time() - library.CACHE_GRACE_S - 60   # a fresh one is left alone a while
    os.utime(cache_path("gone"), (old, old))
    prune_cache({"keep"})
    assert cache_path("keep").exists() and not cache_path("gone").exists()


# ---------------------------------------------------------------- import / clip

def test_import_copies_plain_audio_and_caches_it(app_dir):
    src = wav(app_dir / "boom_sound.wav")
    meta, data = import_file(str(src), "#123456")
    assert data.dtype == np.int16 and len(data) == SR
    assert meta.name == "boom sound" and meta.duration == pytest.approx(1.0)
    assert meta.file == str(library.SOUNDS_DIR / "My sounds" / "boom sound.wav")
    assert os.path.exists(meta.file)
    assert cache_path(meta.id).exists()
    assert meta.fingerprint == fingerprint(str(src))


def test_import_of_ffmpeg_decoded_file_stores_flac_not_the_source(app_dir, monkeypatch):
    src = wav(app_dir / "video.wav").rename(app_dir / "video.mp4")   # pretend it's a video
    real = library._decode
    monkeypatch.setattr(library, "_decode", lambda p: (real(p)[0], True))
    meta, _ = import_file(str(src), "#123456")
    assert meta.file.endswith(".flac")
    assert sf.info(meta.file).subtype == "PCM_16"
    assert not any(p.suffix == ".mp4" for p in library.SOUNDS_DIR.iterdir())


def test_save_clip_writes_flac_and_returns_int16(app_dir):
    x = (np.random.default_rng(2).standard_normal((SR // 2, 2)) * 0.1).astype(np.float32)
    meta, data = save_clip(x, "My clip 12.00.00", "#abcdef")
    assert meta.file.endswith(".flac") and data.dtype == np.int16
    back, rate = sf.read(meta.file, dtype="float32")
    assert rate == SR and np.max(np.abs(back - x)) < 1 / 32767 * 2


def test_delete_removes_library_file_and_cache(app_dir):
    meta, _ = import_file(str(wav(app_dir / "x.wav")), "#000000")
    library.delete_file(meta)
    assert not cache_path(meta.id).exists()
    assert not (library.SOUNDS_DIR / f"{meta.id}_x.wav").exists()


def test_fingerprint_identifies_same_content(app_dir):
    a = wav(app_dir / "a.wav")
    b = wav(app_dir / "b.wav")
    c = wav(app_dir / "c.wav", hz=880)
    assert fingerprint(str(a)) == fingerprint(str(b)) != fingerprint(str(c))
    assert fingerprint(str(app_dir / "missing.wav")) == ""


def test_fingerprint_tells_apart_long_files_that_differ_only_at_the_end(app_dir):
    head = bytes(range(256)) * 8192   # 2 MB, the same in both
    a, b = app_dir / "a.bin", app_dir / "b.bin"
    a.write_bytes(head + b"ending one")
    b.write_bytes(head + b"ending two")
    assert fingerprint(str(a)) != fingerprint(str(b))


def test_import_of_a_name_made_only_of_underscores_keeps_the_pad(app_dir):
    """`_.wav` has no name once underscores become spaces, and the config drops
    sounds without one: it falls back to "Sound"."""
    meta, _ = import_file(str(wav(app_dir / "_.wav")), "#000000")
    assert meta.name == "Sound"
    cfg = library.Config(sounds=[meta])
    assert [m.id for m in library.Config.from_raw(cfg.to_raw()).sounds] == [meta.id]
