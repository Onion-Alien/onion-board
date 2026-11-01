"""Phase 2: bounded decoding, the int16 cache, imports, clips and dedupe."""
import io
import logging
import os
import threading
import time
from types import SimpleNamespace
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from soundboard.sounds import library
from soundboard.sounds.library import (SR, SoundMeta, cache_path, fingerprint, import_file,
                                       load_cached, load_sound, prune_cache, save_clip,
                                       store_cached, to_float32, to_int16)


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
    assert cache_path("abc").exists() and not list(library.CACHE_DIR.glob("*.tmp.npy"))
    back = load_cached("abc")
    assert back.dtype == np.int16 and np.array_equal(back, i)
    cache_path("abc").write_bytes(b"garbage")
    assert load_cached("abc") is None
    np.save(cache_path("abc"), np.zeros((10, 3), np.int16))     # wrong shape
    assert load_cached("abc") is None
    assert load_cached("nope") is None


def test_two_writers_of_one_cache_leave_a_whole_file_and_no_temp(app_dir, monkeypatch, caplog):
    """A pack import or Undo during a slow first load could store one sound's cache on
    two threads at once. With one shared temp name the second writer overwrote the
    first's half-written file and then found it gone; each has its own now."""
    a = np.full((SR, 2), 0.25, np.float32)
    b = np.full((SR, 2), -0.5, np.float32)
    both = threading.Barrier(2, timeout=10)
    real = library.np.save

    def save(path, arr, *k, **kw):   # both are halfway through writing when they meet
        buf = io.BytesIO()
        real(buf, arr, *k, **kw)
        data = buf.getvalue()
        with open(path, "wb") as f:
            f.write(data[:len(data) // 2])
            f.flush()
            both.wait()
            f.write(data[len(data) // 2:])
    monkeypatch.setattr(library.np, "save", save)
    got = {}
    ts = [threading.Thread(target=lambda n=n, x=x: got.__setitem__(n, store_cached("dup", x)))
          for n, x in (("a", a), ("b", b))]
    with caplog.at_level(logging.WARNING, logger=library.log.name):
        for t in ts:
            t.start()
        for t in ts:
            t.join(10)
    assert not [r for r in caplog.records if "couldn't write cache" in r.getMessage()]
    back = load_cached("dup")
    assert back is not None and any(np.array_equal(back, to_int16(x)) for x in (a, b))
    assert np.array_equal(got["a"], to_int16(a)) and np.array_equal(got["b"], to_int16(b))
    assert not list(library.CACHE_DIR.glob("*.tmp.npy"))


def test_load_all_skips_sounds_an_earlier_load_is_still_decoding(app_dir, monkeypatch):
    """_load_all again while the first is still on a slow sound (a pack import, Undo)
    doesn't decode that sound a second time; its thread ends after the first one's."""
    from soundboard.ui.window import soundscontrol as mw
    slow, other = (SoundMeta(id="slow", name="slow", file="slow.wav"),
                    SoundMeta(id="other", name="other", file="o.wav"))
    started, go = threading.Event(), threading.Event()
    decoded = []

    def load(m):
        decoded.append(m.id)
        if m.id == "slow":
            started.set()
            go.wait(10)
        return np.zeros((10, 2), np.int16)
    monkeypatch.setattr(mw, "load_sound", load)
    for f in ("prune_cache", "cache_keep"):
        monkeypatch.setattr(mw, f, lambda *a: set())
    monkeypatch.setattr(mw.thumbs, "prune", lambda *a: None)
    monkeypatch.setattr(mw.trash, "prune", lambda *a: None)
    sounds = [slow]
    win = SimpleNamespace(cfg=SimpleNamespace(sounds=sounds), audio={},
                          engine=SimpleNamespace(prepare=lambda *a: None),
                          bridge=SimpleNamespace(loaded=SimpleNamespace(emit=lambda *a: None)))
    w = SimpleNamespace(soundctl=SimpleNamespace(mw=win, _loading=set(), _load_thread=None,
                                                 _tidied=True,
                                                 _live_metas=lambda: list(sounds)))
    mw.SoundsControl._load_all(w.soundctl)
    first = w.soundctl._load_thread
    assert started.wait(10)
    sounds.append(other)   # added while "slow" is still loading
    mw.SoundsControl._load_all(w.soundctl)
    second = w.soundctl._load_thread
    second.join(0.5)
    assert second.is_alive()   # waits for the sound it left to the first
    go.set()
    first.join(10)
    second.join(10)
    assert sorted(decoded) == ["other", "slow"] and not w.soundctl._loading


def test_load_sound_decodes_once_then_uses_the_cache(app_dir, monkeypatch):
    p = wav(app_dir / "s.wav")
    m = SoundMeta(id="s1", name="s", file=str(p))
    calls = []
    real = library._read
    monkeypatch.setattr(library, "_read", lambda path, *a: calls.append(path) or real(path, *a))
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


def test_import_of_ffmpeg_decoded_file_stores_mp3_not_the_source(app_dir, monkeypatch):
    src = wav(app_dir / "video.wav").rename(app_dir / "video.mp4")   # pretend it's a video
    real = library._read
    monkeypatch.setattr(library, "_read", lambda p, *a: (real(p)[0], True))
    meta, _ = import_file(str(src), "#123456")
    assert meta.file.endswith(".mp3") and sf.info(meta.file).format == "MP3"
    assert not any(p.suffix == ".mp4" for p in library.SOUNDS_DIR.rglob("*"))


def test_save_clip_writes_mp3_on_time_and_returns_int16(app_dir):
    t = np.arange(SR // 2) / SR
    x = np.stack([0.3 * np.sin(2 * np.pi * 440 * t), 0.2 * np.sin(2 * np.pi * 1000 * t)],
                 1).astype(np.float32)
    meta, data = save_clip(x, "My clip 12.00.00", "#abcdef")
    assert meta.file.endswith(".mp3") and data.dtype == np.int16
    back, rate = sf.read(meta.file, dtype="float32")
    # the same length, no gap at the start (a pad's hit stays on time), close to it
    assert rate == SR and back.shape == x.shape
    assert np.sqrt(np.mean((back - x) ** 2)) < 0.01


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


# ---------------------------------------------------------------- long sounds: streamed

def _music(path, seconds, rate, channels=2, loud=1.0, subtype="FLOAT"):
    """Tones + noise with silence in the middle; `loud` > 1 goes over full scale."""
    rng = np.random.default_rng(5)
    t = np.arange(int(seconds * rate)) / rate
    x = loud * (0.6 * np.sin(2 * np.pi * 220 * t) + 0.3 * np.sin(2 * np.pi * 331 * t)
                + 0.1 * rng.standard_normal(len(t)))
    x[len(t) // 3: len(t) // 2] = 0.0
    sf.write(path, np.stack([x * (1 - 0.3 * c) for c in range(channels)], 1), rate, subtype=subtype)
    return path


@pytest.mark.parametrize("rate,channels,loud", [(SR, 2, 0.5), (44100, 2, 1.4), (22050, 1, 0.8),
                                                (96000, 2, 1.2)])
def test_a_streamed_import_makes_what_a_whole_one_does(app_dir, monkeypatch, rate, channels, loud):
    """Over STREAM_S a sound is decoded a second at a time straight into its cache: the
    same int16 audio, length and level as decoding it whole (to the sample when no
    resampling is involved; resampled, within a sample step at the very edges)."""
    src = _music(app_dir / "song.wav", 3.3, rate, channels, loud)
    whole, a = import_file(str(src), "#000000")
    monkeypatch.setattr(library, "STREAM_S", 1)
    calls = []
    real = library._stream
    monkeypatch.setattr(library, "_stream", lambda *a, **k: calls.append(1) or real(*a, **k))
    streamed, b = import_file(str(src), "#000000")
    assert calls, "it wasn't streamed"
    assert b.dtype == np.int16 and b.shape == a.shape
    assert streamed.duration == whole.duration
    assert streamed.level_gain == pytest.approx(whole.level_gain, rel=1e-6)
    diff = np.abs(np.asarray(b, np.int32) - np.asarray(a, np.int32))
    assert diff.max() <= (0 if rate == SR else 1)
    assert np.array_equal(np.load(cache_path(streamed.id)), np.asarray(b))
    assert not list(library.CACHE_DIR.glob("*.tmp.npy"))   # nothing left half-written


def test_a_streamed_import_over_full_scale_is_limited_not_clipped(app_dir, monkeypatch):
    src = _music(app_dir / "loud.wav", 3.0, SR, loud=1.6)
    monkeypatch.setattr(library, "STREAM_S", 1)
    _, data = import_file(str(src), "#000000")
    whole = to_int16(library.decode(str(src)))
    assert np.array_equal(np.asarray(data), whole)
    flat = np.sum(np.abs(np.asarray(data, np.int32)) >= 32767)
    assert flat < 10   # a clipped one would have thousands of flat tops


def test_a_streamed_import_of_a_converted_file_saves_the_same_copy(app_dir, monkeypatch):
    """A format the library converts (here one libsndfile reads under a name outside
    AUDIO_EXTS) is saved while it's decoded: the stored file holds the same audio."""
    src = _music(app_dir / "odd.w64", 2.5, 44100, subtype="PCM_16")
    whole, _ = import_file(str(src), "#000000")
    monkeypatch.setattr(library, "STREAM_S", 1)
    streamed, _ = import_file(str(src), "#000000")
    assert Path(streamed.file).suffix == Path(whole.file).suffix == library.stored_ext()
    x, _sr = sf.read(whole.file, dtype="float32")
    y, _sr = sf.read(streamed.file, dtype="float32")
    assert x.shape == y.shape and np.max(np.abs(x - y)) < 2 / 32767


def test_a_streamed_import_that_fails_leaves_nothing_behind(app_dir, monkeypatch):
    src = _music(app_dir / "odd.w64", 3.0, SR, subtype="PCM_16")
    monkeypatch.setattr(library, "STREAM_S", 1)
    real = library._sf_pieces

    def broken(f, left):
        for i, x in enumerate(real(f, left)):
            if i == 2:
                raise OSError(28, "No space left on device")
            yield x

    monkeypatch.setattr(library, "_sf_pieces", broken)
    with pytest.raises(OSError, match="Sounds folder"):
        import_file(str(src), "#000000")
    assert not [p for p in library.SOUNDS_DIR.rglob("*") if p.is_file()]
    assert not list(library.CACHE_DIR.glob("*"))


def test_load_original_streams_a_long_sound_back_into_the_cache(app_dir, monkeypatch):
    src = _music(app_dir / "long.wav", 3.0, 44100)
    meta, a = import_file(str(src), "#000000")
    library.unlink_cache(meta.id)
    monkeypatch.setattr(library, "STREAM_S", 1)
    b = library.load_original(meta)
    assert np.abs(np.asarray(b, np.int32) - np.asarray(a, np.int32)).max() <= 1
    assert cache_path(meta.id).exists()


def test_decode_int16_streams_a_long_link_into_its_own_cache_file(app_dir, monkeypatch):
    src = _music(app_dir / "link.wav", 3.0, SR, loud=1.3)
    whole = (to_int16(library.decode(str(src))), library.level_gain(library.decode(str(src))))
    monkeypatch.setattr(library, "STREAM_S", 1)
    data, gain = library.decode_int16(str(src))
    assert np.array_equal(np.asarray(data), whole[0]) and gain == pytest.approx(whole[1], rel=1e-6)
    assert [p.name.startswith("play-") for p in library.CACHE_DIR.glob("*.npy")] == [True]
