"""Pad pictures (soundboard.sounds.thumbs) and how a playing pad shows its progress."""
import json

import pytest
from PySide6.QtGui import QColor, QImage

from soundboard.sounds import library, thumbs
from soundboard.online import net as thumbs_net
from soundboard.sounds.library import Config, SoundMeta
from soundboard.ui.kit.widgets import Pad


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


def _painted(pad, qapp):
    """The rects `pad` paints until things settle."""
    from PySide6.QtCore import QEvent, QObject

    seen = []

    class Watch(QObject):
        def eventFilter(self, _o, e):
            if e.type() == QEvent.Type.Paint:
                seen.append(e.rect())
            return False
    watch = Watch()
    pad.installEventFilter(watch)
    for _ in range(5):
        qapp.processEvents()
    pad.removeEventFilter(watch)
    return seen


def test_a_playing_pad_only_redraws_the_strip_the_progress_moved_over(qapp):
    pad = Pad(SoundMeta(id="p", name="n", file="f"), 150)
    pad.state = "ready"
    pad.show()
    _painted(pad, qapp)
    pad.set_playing(0.2)
    assert any(r == pad.rect() for r in _painted(pad, qapp))   # it starts: all of it
    pad.set_playing(0.2001)                                    # under a pixel: nothing
    assert pad.progress == 0.2001 and _painted(pad, qapp) == []
    pad.set_playing(0.21)
    rects = _painted(pad, qapp)
    assert rects and all(r.width() < 12 and r.height() == pad.height() for r in rects)
    x = int(2 + (pad.width() - 4) * 0.21)
    assert all(r.left() <= x <= r.right() for r in rects)
    pad.set_playing(0.05)                                      # it looped round
    rects = _painted(pad, qapp)
    assert rects and all(r.left() <= 2 + (pad.width() - 4) * 0.05 for r in rects)
    assert all(r.right() >= int(2 + (pad.width() - 4) * 0.21) for r in rects)
    pad.set_playing(0.05, True)                                # paused: its edge fades
    assert pad.paused and any(r == pad.rect() for r in _painted(pad, qapp))
    pad.set_playing(None)                                      # it stopped
    assert pad.progress is None and any(r == pad.rect() for r in _painted(pad, qapp))
    pad.close()


def test_a_list_row_shows_its_progress_too(qapp):
    from soundboard.ui.kit.pad import ROW_MAX_H
    pad = Pad(SoundMeta(id="p", name="n", file="f"), 300)
    pad.state = "ready"
    pad.setFixedHeight(ROW_MAX_H)
    pad.show()
    _painted(pad, qapp)
    pad.set_playing(0.2)
    _painted(pad, qapp)
    pad.set_playing(0.5)
    rects = _painted(pad, qapp)
    assert rects and pad._cards is not None
    assert not pad.grab().isNull()
    pad.close()


def test_a_strip_from_the_saved_pictures_looks_like_a_full_paint(qapp):
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtGui import QRegion
    pad = Pad(SoundMeta(id="p", name="A name", file="f", duration=3.0), 150)
    pad.state = "ready"
    pad.show()
    _painted(pad, qapp)
    pad.set_playing(0.2)
    _painted(pad, qapp)
    pad.set_playing(0.6)   # the pictures are saved for the first strip
    _painted(pad, qapp)
    assert pad._cards is not None
    strip = QImage(pad.size(), QImage.Format.Format_ARGB32_Premultiplied)
    strip.fill(0)
    pad.render(strip, QPoint(), QRegion(QRect(0, 0, pad.width() - 1, pad.height())))
    assert pad._cards is not None
    full = pad.grab().toImage().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    assert pad._cards is None   # a full paint: something may have changed
    edge = 2 + (pad.width() - 4) * 0.6
    for x in range(pad.width() - 1):
        if abs(x - edge) < 3:   # (the fill's own edge is on a whole pixel in the strip)
            continue
        for y in range(pad.height()):
            a, b = strip.pixelColor(x, y), full.pixelColor(x, y)
            assert abs(a.red() - b.red()) <= 2 and abs(a.blue() - b.blue()) <= 2, (x, y)
    pad.close()


def test_pad_paints_picture_and_progress(qapp, app_dir, tmp_path):
    m = SoundMeta(id="p", name="A very long sound name that wraps", file="f", duration=3.0)
    thumbs.set_image(m, make_image(tmp_path / "a.png", color="#2040ff"))
    pad = Pad(m, 150)
    pad.state = "ready"
    pad.progress = 0.5
    img = pad.grab().toImage()
    assert not img.isNull()
    mid = img.pixelColor(img.width() // 2, img.height() // 3)
    assert mid.blue() > mid.red()          # the picture shows through the shade


# ---------------------------------------------------------------------- in the app

from test_mainwindow import window  # noqa: E402,F401  (the real MainWindow fixture)
from test_ytdl import fake_link_download, fake_yt_dlp  # noqa: E402

from conftest import process_events  # noqa: E402


def test_download_asks_for_the_thumbnail_and_never_returns_it(monkeypatch, tmp_path):
    from soundboard.online import ytdl
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
    from soundboard.online import ytdl
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
    # named after the video in its site's folder, not after the temp file ("vid")
    assert m.file == str(library.SOUNDS_DIR / "YouTube" / "A Tone.wav")


def test_image_dropped_on_a_pad_becomes_its_picture(qapp, window, tmp_path):  # noqa: F811
    window.grid.image_dropped.emit("s0", str(make_image(tmp_path / "a.png")))
    qapp.processEvents()   # drops are handled after the drop returns (queued)
    m = window.meta("s0")
    assert window._saver.flush(10)   # settings are written on a background thread
    assert m.image and Config.load().sounds[0].image == m.image


def test_a_playing_sound_shows_on_its_pad_on_any_tab(qapp, window, monkeypatch):  # noqa: F811
    monkeypatch.setattr(window.engine, "playing", lambda: {"s0": (0.2, False)})
    window.tickctl.tick()
    pad = window.pads["s0"]
    assert pad.progress == 0.2
    window.tabs.setCurrentWidget(window.sounds_page)
    monkeypatch.setattr(window.engine, "playing", lambda: {"s0": (0.3, False)})
    window.tickctl.tick()
    assert pad.progress == 0.3
    monkeypatch.setattr(window.engine, "playing", lambda: {})
    window.tickctl.tick()
    assert pad.progress is None


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


class _Reply:
    def __init__(self, body: bytes, kind: str):
        self.body, self.kind = body, kind
        self.headers = self

    def get_content_type(self):
        return self.kind

    def read(self, n=-1):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


ROUTER = "192.168.1.1"  # sensitive-scan: allow (test address)


def fake_web(monkeypatch, pages: dict):
    """net.urlopen answering from `pages` {url: (bytes, content type)}; returns the
    list of URLs asked for (and the feature each was asked under)."""
    asked = []

    def urlopen(req, timeout=30, feature=None, direct=False):
        asked.append((req.full_url, feature))
        thumbs_net.check(feature)
        if req.full_url not in pages:
            raise OSError("404")
        return _Reply(*pages[req.full_url])
    monkeypatch.setattr(thumbs_net, "urlopen", urlopen)
    return asked


def png_bytes(tmp_path) -> bytes:
    return make_image(tmp_path / "p.png").read_bytes()



def test_fetch_takes_an_image_link_or_a_pages_preview_picture(qapp, tmp_path, monkeypatch):
    png = png_bytes(tmp_path)
    page = (b'<html><head><meta property="og:image" content="/pics/a.png?x=1&amp;y=2">'
            b"</head></html>")
    asked = fake_web(monkeypatch, {"https://ex.com/a.png": (png, "image/png"),
                                   "https://ex.com/post/1": (page, "text/html"),
                                   "https://ex.com/pics/a.png?x=1&y=2": (png, "image/png")})
    assert not thumbs.fetch("https://ex.com/a.png").isNull()
    assert not thumbs.fetch("ex.com/post/1").isNull()   # no https:// typed: added
    assert [u for u, __ in asked] == ["https://ex.com/a.png", "https://ex.com/post/1",
                                      "https://ex.com/pics/a.png?x=1&y=2"]
    assert {f for __, f in asked} == {"sounds_web.other"}   # "Other pasted links" switch


def test_a_pages_preview_picture_is_only_fetched_from_the_web(qapp, tmp_path, monkeypatch):
    # og:image comes from the page, not the user: a file:// one would open a file on
    # this PC, or a share on another (file:////host/share: Windows connects to it)
    pic = tmp_path / "p.png"
    pic.write_bytes(png_bytes(tmp_path))
    # nor one on this PC / the home network: the page's site would reach into the LAN
    for bad in (pic.as_uri(), "file:////attacker.example/share/a.png",
                f"http://{ROUTER}/x.png", "http://127.0.0.1/x.png", "http://nas.lan/a.png"):
        page = f'<html><meta property="og:image" content="{bad}"></html>'.encode()
        asked = fake_web(monkeypatch, {"https://ex.com/post": (page, "text/html")})
        with pytest.raises(thumbs.LinkError, match="no picture"):
            thumbs.fetch("https://ex.com/post")
        assert [u for u, __ in asked] == ["https://ex.com/post"]


def test_fetch_goes_straight_to_a_youtube_videos_thumbnail(qapp, tmp_path, monkeypatch):
    asked = fake_web(monkeypatch, {"https://i.ytimg.com/vi/HEXWRTEbj1I/hqdefault.jpg":
                                   (png_bytes(tmp_path), "image/jpeg")})
    for link in ("https://www.youtube.com/watch?v=HEXWRTEbj1I&t=30",
                 "https://youtu.be/HEXWRTEbj1I", "youtube.com/shorts/HEXWRTEbj1I"):
        assert not thumbs.fetch(link).isNull()
    assert len(asked) == 3
    assert {f for __, f in asked} == {"sounds_web.youtube"}   # YouTube's switch, not "other"


def test_a_youtube_picture_link_is_refused_with_youtube_switched_off(qapp, tmp_path,
                                                                     monkeypatch):
    """Switching YouTube off stops its pictures too: a YouTube link, i.ytimg.com itself,
    or a page (another site, still allowed) whose preview picture is on i.ytimg.com."""
    from soundboard.online import netlog
    png = png_bytes(tmp_path)
    page = b'<html><meta property="og:image" content="https://i.ytimg.com/vi/x/a.jpg"></html>'
    asked = fake_web(monkeypatch, {"https://i.ytimg.com/vi/HEXWRTEbj1I/hqdefault.jpg":
                                   (png, "image/jpeg"),
                                   "https://i.ytimg.com/vi/x/a.jpg": (png, "image/jpeg"),
                                   "https://ex.com/post": (page, "text/html"),
                                   "https://ex.com/a.png": (png, "image/png")})
    thumbs_net.configure_features(off=["sounds_web.youtube"])
    try:
        for link in ("https://www.youtube.com/watch?v=HEXWRTEbj1I",
                     "https://i.ytimg.com/vi/x/a.jpg", "https://ex.com/post"):
            with pytest.raises(thumbs_net.FeatureOff, match="YouTube"):
                thumbs.fetch(link)
        assert not thumbs.fetch("https://ex.com/a.png").isNull()   # other links: still on
    finally:
        thumbs_net.configure_features()
    # nothing reached YouTube: each was refused by its switch before connecting
    assert all(f == "sounds_web.youtube" for u, f in asked if "ytimg" in u)
    assert "picture from the link" in netlog._causes["sounds_web"]   # the activity list says why


def test_fetch_says_why_it_couldnt(qapp, monkeypatch):
    fake_web(monkeypatch, {"https://ex.com/page": (b"<html>no picture</html>", "text/html")})
    for link, says in (("not a link", "isn't a web link"), ("ftp://ex.com/a.png",
                       "isn't a web link"), ("https://ex.com/page", "no picture"),
                       ("https://ex.com/gone.png", "Couldn't get the picture")):
        with pytest.raises(thumbs.LinkError, match=says):
            thumbs.fetch(link)
    thumbs_net.configure_features(off=["sounds_web.other"])
    try:
        with pytest.raises(thumbs_net.FeatureOff):
            thumbs.fetch("https://ex.com/page")
    finally:
        thumbs_net.configure_features()


def test_picture_from_a_link_goes_on_the_pad(qapp, window, tmp_path, monkeypatch):  # noqa: F811
    """Edit… → Picture → the link button: fetched off the UI thread, shown, and put on
    the pad only on Save; a link with no picture says so and changes nothing."""
    from PySide6.QtWidgets import QInputDialog
    from soundboard.ui.sounds.dialogs import EditDialog
    img = QImage(str(make_image(tmp_path / "a.png")))
    monkeypatch.setattr(thumbs, "fetch", lambda url: img if url == "https://ex.com/a" else
                        (_ for _ in ()).throw(thumbs.LinkError("There's no picture at that link.")))
    m = window.meta("s0")
    d = EditDialog(m, window.hotkeys, lambda *a: None, window)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: (" https://ex.com/a ", True))
    d.btn_pic_link.click()
    assert process_events(qapp, lambda: d.picture is not None)
    assert not m.image                       # not until Save
    d.apply()
    assert thumbs.Path(m.image).parent == library.THUMBS_DIR

    from soundboard.ui.kit import toast
    d2 = EditDialog(window.meta("s1"), window.hotkeys, lambda *a: None, window)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("https://ex.com/b", True))
    d2.btn_pic_link.click()
    assert process_events(qapp, lambda: toast.shown(d2))
    assert "There's no picture at that link." in toast.shown(d2)[-1].text()
    assert d2.picture is None
    d2.apply()
    assert not window.meta("s1").image
    d.deleteLater()
    d2.deleteLater()
