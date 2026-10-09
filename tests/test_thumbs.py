"""Pad pictures (soundboard.thumbs) and the playing pad's spectrum visualizer."""
import json

import numpy as np
from PySide6.QtGui import QColor, QImage

from soundboard import library, thumbs
from soundboard.library import SR, Config, SoundMeta
from soundboard.ui.widgets import Pad, spectrum


def make_image(path, w=800, h=450, color="#ff0000"):
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(color))
    assert img.save(str(path))
    return path


def test_store_scales_down_into_the_library(qapp, app_dir, tmp_path):
    src = make_image(tmp_path / "big.png", 1920, 1080)
    out = thumbs.store(src, "abc")
    assert out and library.THUMBS_DIR in thumbs.Path(out).parents
    img = QImage(out)
    assert img.width() <= 2 * thumbs.MAX_W and img.height() <= thumbs.MAX_H + 1
    assert img.width() >= thumbs.MAX_W or img.height() >= thumbs.MAX_H   # covers the box


def test_store_rejects_what_isnt_a_picture(qapp, app_dir, tmp_path):
    bad = tmp_path / "x.png"
    bad.write_bytes(b"not a picture")
    assert thumbs.store(bad, "abc") == ""


def test_set_image_replaces_and_clear_removes_the_file(qapp, app_dir, tmp_path):
    m = SoundMeta(id="s1", name="n", file="f.wav")
    assert thumbs.set_image(m, make_image(tmp_path / "a.png"))
    first = thumbs.Path(m.image)
    assert thumbs.set_image(m, make_image(tmp_path / "b.jpg", color="#00ff00"))
    assert not first.exists() and thumbs.Path(m.image).exists()
    thumbs.clear(m)
    assert m.image == "" and not list(library.THUMBS_DIR.iterdir())


def test_picture_cache_forgets_replaced_pictures_and_stays_small(qapp, app_dir, tmp_path,
                                                                  monkeypatch):
    m = SoundMeta(id="s1", name="n", file="f.wav")
    thumbs.set_image(m, make_image(tmp_path / "a.png"))
    old = m.image
    assert thumbs.pixmap(old) is not None and old in thumbs._pixmaps
    thumbs.set_image(m, make_image(tmp_path / "b.png"))
    assert old not in thumbs._pixmaps                  # the replaced one is let go
    monkeypatch.setattr(thumbs, "MAX_CACHED", 3)
    pics = [str(make_image(tmp_path / f"p{i}.png", 40, 30)) for i in range(5)]
    for p in pics:
        assert thumbs.pixmap(p) is not None
    thumbs.pixmap(pics[2])                             # drawn again: kept longest
    thumbs.pixmap(m.image)
    assert len(thumbs._pixmaps) == 3
    assert pics[2] in thumbs._pixmaps and m.image in thumbs._pixmaps
    assert pics[0] not in thumbs._pixmaps
    assert thumbs.pixmap(pics[0]) is not None          # reloads when needed again


def test_image_is_stored_relative_and_survives_a_round_trip(qapp, app_dir, tmp_path):
    m = SoundMeta(id="s1", name="n", file=str(library.SOUNDS_DIR / "s1.wav"))
    thumbs.set_image(m, make_image(tmp_path / "a.png"))
    cfg = Config(sounds=[m])
    raw = cfg.to_raw()
    assert raw["sounds"][0]["image"] == thumbs.Path(m.image).name
    back = Config.from_raw(json.loads(json.dumps(raw)))
    assert back.sounds[0].image == m.image


def test_duplicate_gets_its_own_picture_and_delete_removes_it(qapp, app_dir, tmp_path):
    src = library.SOUNDS_DIR / "s1.wav"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"RIFF")
    m = SoundMeta(id="s1", name="n", file=str(src))
    thumbs.set_image(m, make_image(tmp_path / "a.png"))
    copy = library.duplicate(m, "copy")
    assert copy.image and copy.image != m.image and thumbs.Path(copy.image).exists()
    library.delete_file(m)
    assert not thumbs.Path(m.image).exists() and thumbs.Path(copy.image).exists()


def test_prune_keeps_pictures_in_use_and_recent_ones(qapp, app_dir, tmp_path):
    import os
    used = thumbs.store(make_image(tmp_path / "a.png"), "a")
    old = thumbs.store(make_image(tmp_path / "b.png"), "b")
    fresh = thumbs.store(make_image(tmp_path / "c.png"), "c")
    os.utime(old, (0, 0))
    os.utime(used, (0, 0))
    thumbs.prune({used})
    assert os.path.exists(used) and not os.path.exists(old) and os.path.exists(fresh)


def test_find_in_picks_the_thumbnail_next_to_a_download(tmp_path):
    (tmp_path / "abc.webm").write_bytes(b"x")
    assert thumbs.find_in(tmp_path) is None
    (tmp_path / "abc.webp").write_bytes(b"x")
    assert thumbs.find_in(tmp_path).name == "abc.webp"


def test_find_in_takes_tiktoks_untyped_thumbnail(tmp_path):
    (tmp_path / "123.mp4").write_bytes(b"x")
    (tmp_path / "123.image").write_bytes(b"x")
    assert thumbs.find_in(tmp_path).name == "123.image"


def test_spectrum_puts_a_tone_in_the_right_band():
    t = np.arange(SR) / SR
    for freq in (100, 1000, 8000):
        tone = (np.sin(2 * np.pi * freq * t) * 0.5 * 32767).astype(np.int16)
        bands = spectrum(np.stack([tone, tone], axis=1), 0.3, 16)
        edges = np.geomspace(50, 14000, 17)
        want = int(np.searchsorted(edges, freq)) - 1
        assert abs(int(np.argmax(bands)) - want) <= 1
        assert bands.max() > 0.6


def test_spectrum_of_silence_is_flat_and_it_shows_what_was_just_played():
    assert spectrum(np.zeros((SR, 2), np.int16), 0.5, 12).max() == 0.0
    noise = (np.random.default_rng(1).standard_normal((SR, 2)) * 3000).astype(np.int16)
    quiet_then_loud = np.concatenate([np.zeros((SR, 2), np.int16), noise])
    # half way: the stretch just played (silence), never the one ahead, which a long
    # sound may still be reading from disk (mapped.py): a frame waited for it
    assert spectrum(quiet_then_loud, 0.5, 12).max() == 0.0
    assert spectrum(quiet_then_loud, 0.6, 12).max() > 0.3
    assert len(spectrum(None, 0.5, 10)) == 10


def _spectrum_one_band_at_a_time(data, frac, n):
    """The plain version of spectrum(): a loop over the bands (what it used to be)."""
    from soundboard.ui.widgets import _FREQS, _HANN, FFT_N
    pos = max(0, int(min(max(frac, 0.0), 1.0) * len(data)) - FFT_N)
    seg = data[pos:pos + FFT_N]
    if len(seg) < FFT_N:
        seg = np.concatenate([seg, np.zeros((FFT_N - len(seg), 2), seg.dtype)])
    mono = seg.mean(axis=1, dtype=np.float32)
    if data.dtype == np.int16:
        mono /= 32768.0
    mag = np.abs(np.fft.rfft(mono * _HANN)) * (4.0 / FFT_N)
    idx = np.clip(np.searchsorted(_FREQS, np.geomspace(50, 14000, n + 1)), 1, len(mag) - 1)
    out = np.empty(n, np.float32)
    for i in range(n):
        a, b = idx[i], max(idx[i + 1], idx[i] + 1)
        out[i] = np.sqrt(np.mean(mag[a:b] ** 2))
    db = 20 * np.log10(out + 1e-9) + np.linspace(0, 14, n)
    return np.clip((db + 62) / 52, 0.0, 1.0).astype(np.float32)


def test_spectrum_matches_the_band_by_band_sum():
    rng = np.random.default_rng(7)
    for n in (1, 5, 16, 28, 48):
        loud = (rng.standard_normal((SR, 2)) * rng.uniform(10, 20000)).astype(np.int16)
        quiet = (rng.standard_normal((SR // 2, 2)) * 1e-3).astype(np.float32)
        for data in (loud, quiet):
            for frac in (0.0, 0.37, 0.99):
                got, want = spectrum(data, frac, n), _spectrum_one_band_at_a_time(data, frac, n)
                assert np.abs(got - want).max() < 1e-5


def test_pad_bars_jump_up_and_fall_back(qapp):
    pad = Pad(SoundMeta(id="p", name="n", file="f"), 150)
    pad.set_levels(np.full(pad.n_bands, 0.9))
    pad.set_levels(np.zeros(pad.n_bands))
    assert 0.6 < pad.bands[0] < 0.9 and pad.peaks[0] >= pad.bands[0]
    pad.set_levels(np.ones(pad.n_bands))
    assert pad.bands[0] == 1.0
    pad.set_levels(None)
    assert pad.bands is None


def test_pad_paints_picture_and_visualizer(qapp, app_dir, tmp_path):
    m = SoundMeta(id="p", name="A very long sound name that wraps", file="f", duration=3.0)
    thumbs.set_image(m, make_image(tmp_path / "a.png", color="#2040ff"))
    pad = Pad(m, 150)
    pad.state = "ready"
    pad.progress = 0.5
    pad.set_levels(np.linspace(0, 1, pad.n_bands))
    img = pad.grab().toImage()
    assert not img.isNull()
    mid = img.pixelColor(img.width() // 2, img.height() // 3)
    assert mid.blue() > mid.red()          # the picture shows through the shade


# ---------------------------------------------------------------------- in the app

from test_mainwindow import window  # noqa: E402,F401  (the real MainWindow fixture)
from test_ytdl import fake_link_download, fake_yt_dlp  # noqa: E402

from conftest import process_events  # noqa: E402


def test_download_asks_for_the_thumbnail_and_never_returns_it(monkeypatch, tmp_path):
    from soundboard import ytdl
    seen = fake_yt_dlp(monkeypatch, {"title": "Boom", "duration": 3})
    path, _ = ytdl.download_audio("https://youtu.be/x", tmp_path)
    assert seen["writethumbnail"]
    path.unlink()
    (tmp_path / "vid.webp").write_bytes(b"x")         # only the thumbnail is left
    (tmp_path / "vid.opus").write_bytes(b"a")
    monkeypatch.setattr(ytdl.Path, "is_file", lambda p: p.name != "vid.m4a" and
                        p.exists())
    path, _ = ytdl._download("https://youtu.be/x", tmp_path, None)
    assert path.suffix != ".webp"


def test_link_add_uses_the_video_thumbnail(qapp, window, monkeypatch, tmp_path):  # noqa: F811
    from soundboard import ytdl
    fake_link_download(monkeypatch, tmp_path)
    real = ytdl.download_audio

    def with_thumb(*a, **kw):
        path, title = real(*a, **kw)
        make_image(path.parent / "vid.webp", 1280, 720)
        return path, title
    monkeypatch.setattr(ytdl, "download_audio", with_thumb)
    window.search.setText("https://youtu.be/abc")
    window.search.returnPressed.emit()                   # its card; then its Add
    assert process_events(qapp, lambda: window.ytresults._rows, 5)
    window.ytresults._rows[0].btn_add.click()
    assert process_events(qapp, lambda: len(window.cfg.sounds) == 3, 5)
    m = window.cfg.sounds[-1]
    assert m.image and thumbs.Path(m.image).parent == library.THUMBS_DIR
    assert thumbs.pixmap(m.image) is not None


def test_image_dropped_on_a_pad_becomes_its_picture(qapp, window, tmp_path):  # noqa: F811
    window.grid.image_dropped.emit("s0", str(make_image(tmp_path / "a.png")))
    qapp.processEvents()   # drops are handled after the drop returns (queued)
    m = window.meta("s0")
    assert window._saver.flush(10)   # settings are written on a background thread
    assert m.image and Config.load().sounds[0].image == m.image


def test_playing_pad_gets_visualizer_levels(qapp, window, monkeypatch):  # noqa: F811
    assert process_events(qapp, lambda: "s0" in window.audio, 5)
    monkeypatch.setattr(window.engine, "playing", lambda: {"s0": (0.2, False)})
    window.tick()
    pad = window.pads["s0"]
    assert pad.bands is None and pad.progress == 0.2   # another tab showing: no spectrum
    window.tabs.setCurrentWidget(window.sounds_page)
    window.tick()
    assert pad.bands is not None and pad.bands.max() > 0.3 and pad.progress == 0.2
    monkeypatch.setattr(window.engine, "playing", lambda: {})
    window.tick()
    assert pad.bands is None and pad.progress is None


def test_from_clipboard_takes_a_copied_image_or_a_copied_picture_file(qapp, tmp_path):
    from PySide6.QtCore import QMimeData, QUrl
    img = QImage(40, 30, QImage.Format_RGB32)
    img.fill(QColor("#0000ff"))
    copied = QMimeData()
    copied.setImageData(img)
    assert thumbs.from_clipboard(copied).size() == img.size()
    files = QMimeData()
    files.setUrls([QUrl.fromLocalFile(str(tmp_path / "notes.txt")),
                   QUrl.fromLocalFile(str(make_image(tmp_path / "p.png", 64, 48)))])
    assert thumbs.from_clipboard(files).width() == 64
    text = QMimeData()
    text.setText("hello")
    assert thumbs.from_clipboard(text) is None and thumbs.from_clipboard(None) is None


def test_fitted_keeps_one_size_per_picture_and_trim_lets_all_go(qapp, app_dir, tmp_path):
    """Pads draw the picture at their own size: a new size (Pad size dragged) replaces
    the old one instead of piling up, and to the tray the cache is let go (it's made
    again from the small files when the window is back)."""
    thumbs.trim()
    p = str(make_image(tmp_path / "a.png", 480, 300))
    a = thumbs.fitted(p, 150, 93, 1.0)
    assert a is not None and (a.width(), a.height()) == (150, 93)
    assert thumbs.fitted(p, 150, 93, 1.0) is a                # cached
    b = thumbs.fitted(p, 200, 124, 1.25)
    assert (b.width(), b.height()) == (200, 124)
    assert [k[:4] for k in thumbs._fitted] == [(p, 200, 124, 1.25)]   # the old size went
    assert thumbs._fitted_bytes == 200 * 124 * 4
    thumbs.trim()
    assert not thumbs._fitted and not thumbs._pixmaps
    assert thumbs._fitted_bytes == thumbs._bytes == 0
    c = thumbs.fitted(p, 200, 124, 1.25)                      # made again on the next paint
    assert c is not None and c.toImage() == b.toImage()
