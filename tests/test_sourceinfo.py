"""A sound downloaded from YouTube, YouTube Music, TikTok or SoundCloud keeps where it
came from (link, channel, upload date, length, views) out of the download's own reply,
as SoundMeta.source and a text file next to its audio; the pad menu opens, copies or
shows it. Other sounds get none of it."""
import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from soundboard import library, sourceinfo, trash, ytdl
from soundboard.engine import SR
from soundboard.library import Config, SoundMeta

INFO = {"id": "dQw4w9WgXcQ", "title": "Never Gonna Give You Up (Official Video)",
        "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "channel": "Rick Astley", "channel_url": "https://www.youtube.com/channel/UCuAXF",
        "upload_date": "20091025", "duration": 213, "view_count": 1700000000,
        "like_count": 18000000, "comment_count": 2300000}
SRC = {"site": "youtube", "link": INFO["webpage_url"], "title": INFO["title"],
       "channel": "Rick Astley", "channel_link": INFO["channel_url"],
       "uploaded": "2009-10-25", "seconds": 213, "views": 1700000000, "added": "2026-10-11"}


def _wav(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, np.zeros((SR // 5, 2), np.float32), SR, subtype="PCM_16")
    return path


def test_picks_the_easy_fields_and_never_likes_or_comments():
    src = sourceinfo.pick(INFO, "https://youtu.be/dQw4w9WgXcQ")
    assert {k: v for k, v in src.items() if k != "added"} == {
        k: v for k, v in SRC.items() if k != "added"}
    assert "likes" not in json.dumps(src) and "comment" not in json.dumps(src)


@pytest.mark.parametrize("url,site", [
    ("https://music.youtube.com/watch?v=abc", "ytmusic"),
    ("https://www.tiktok.com/@a/video/1", "tiktok"),
    ("https://soundcloud.com/a/b", "soundcloud"),
    ("https://m.youtube.com/watch?v=abc", "youtube")])
def test_each_kept_site(url, site):
    assert sourceinfo.pick({"webpage_url": url}, url)["site"] == site


@pytest.mark.parametrize("url,key,name", [
    ("https://www.instagram.com/reel/1", "instagram", "Instagram"),
    ("https://x.com/a/status/1", "x", "X"), ("https://vimeo.com/1", "vimeo", "Vimeo"),
    ("https://www.myinstants.com/media/sounds/a.mp3", "myinstants", "Myinstants"),
    ("https://www.some-other-site.example/v/1", "web", "some-other-site.example")])
def test_every_download_site_keeps_it_named_after_the_site(url, key, name):
    src = sourceinfo.pick({"webpage_url": url, "title": "x"}, url)
    assert src["site"] == key and sourceinfo.site_name(src) == name


@pytest.mark.parametrize("url", ["", "file:///C:/x.mp3", "C:/Music/x.mp3", "ftp://a/b"])
def test_not_a_web_link_keeps_nothing(url):
    assert sourceinfo.pick({"title": "x"}, url) == {}


def test_a_stored_source_is_cleaned():
    assert sourceinfo.clean(SRC) == SRC
    assert sourceinfo.clean({"link": "javascript:alert(1)", "site": "youtube"}) == {}
    assert sourceinfo.clean({"link": "https://a.example/w", "site": "youtube"})["site"] == "web"
    assert sourceinfo.clean("nonsense") == {} and sourceinfo.clean(None) == {}
    odd = sourceinfo.clean({"link": SRC["link"], "site": "bogus", "views": -3,
                            "channel_link": "file:///c:/x"})
    assert odd == {"link": SRC["link"], "site": "youtube"}


def test_the_text_file_reads_plainly(tmp_path):
    audio = tmp_path / "YouTube" / "Song.mp3"
    audio.parent.mkdir()
    sourceinfo.write(audio, SRC)
    txt = (tmp_path / "YouTube" / "Song.txt").read_text(encoding="utf-8-sig")
    assert "Link:" in txt and SRC["link"] in txt and "Rick Astley" in txt
    assert "1,700,000,000 (when added)" in txt and "3:33" in txt and "2009-10-25" in txt
    sourceinfo.remove(audio)
    assert not (tmp_path / "YouTube" / "Song.txt").exists()
    sourceinfo.write(audio, {})   # nothing to say: no file
    assert not (tmp_path / "YouTube" / "Song.txt").exists()


def test_the_download_leaves_its_info_for_the_link_bar(tmp_path):
    f = tmp_path / "dQw4w9WgXcQ.webm"
    f.write_bytes(b"x")
    path, title = ytdl._found(INFO["webpage_url"], tmp_path, f, INFO)
    assert (path, title) == (f, "Never Gonna Give You Up")
    assert sourceinfo.read_from(tmp_path)["link"] == INFO["webpage_url"]
    other = tmp_path / "other"
    other.mkdir()
    g = other / "a.mp3"
    g.write_bytes(b"x")
    ytdl._found("C:/not/a/link.mp3", other, g, {"title": "a"})
    assert sourceinfo.read_from(other) == {}


def test_the_source_and_its_text_file_follow_the_sound(app_dir, tmp_path):
    m, _d = library.import_file(str(_wav(tmp_path / "id.wav")), "#1", name="Song",
                                folder="YouTube")
    m.source = dict(SRC)
    sourceinfo.write(m.file, m.source)
    txt = Path(m.file).with_suffix(".txt")
    assert Config(sounds=[m]).save()
    assert Config.load().sounds[0].source == SRC   # kept in the settings
    copy = library.duplicate(m, "Song copy")
    assert copy.source == SRC and Path(copy.file).with_suffix(".txt").is_file()
    library.delete_file(copy)
    assert not Path(copy.file).with_suffix(".txt").exists()
    trash.put_sound(m, 0)   # the bin: the copy goes, it's written again on the way back
    assert not txt.exists()
    [it] = trash.items()
    back = trash.meta_of(trash.take(it.id))
    assert back.source == SRC and txt.is_file()


def test_a_sound_from_elsewhere_has_no_source(app_dir, tmp_path):
    m, _d = library.import_file(str(_wav(tmp_path / "air_horn.wav")), "#1")
    assert m.source == {}
    assert Config(sounds=[m]).save()
    assert Config.load().sounds[0].source == {}


def test_the_link_bar_keeps_the_source_on_the_new_sound(qapp, monkeypatch, tmp_path):
    from soundboard.ui import linkbar
    dl = tmp_path / "dl"
    dl.mkdir()
    path = dl / "dQw4w9WgXcQ.wav"
    path.write_bytes(b"x")
    sourceinfo.save_for(dl, INFO, INFO["webpage_url"])
    audio = tmp_path / "YouTube" / "Never Gonna Give You Up.wav"
    audio.parent.mkdir()
    meta = SoundMeta(id="x1", name="Never Gonna Give You Up", file=str(audio))
    data = np.zeros((480, 2), np.int16)
    monkeypatch.setattr(linkbar.ytdl, "download_audio", lambda url, **kw: (path, "Never"))
    monkeypatch.setattr(linkbar, "fingerprint", lambda p: "")
    monkeypatch.setattr(linkbar, "import_file", lambda p, color, **kw: (meta, data))
    monkeypatch.setattr(linkbar.thumbs, "find_in", lambda folder: None)

    class Eng:
        def prepare(self, *a):
            pass
    bar = linkbar.LinkBar(engine=Eng(), cfg=Config(), color_for=lambda: "#fff",
                          known_for=dict)
    bar._work("add", INFO["webpage_url"], None, "#fff", {}, False)
    assert meta.source["link"] == INFO["webpage_url"]
    assert audio.with_suffix(".txt").is_file()


def test_details_box_shows_the_fields_and_opens_the_link(qapp, monkeypatch):
    from PySide6.QtWidgets import QLabel
    from soundboard.ui import busy, sourcedialog
    opened = []
    monkeypatch.setattr(busy, "open_url", lambda url, **kw: opened.append(url) or True)
    music = "https://music.youtube.com/watch?v=dQw4w9WgXcQ"
    d = sourcedialog.SourceDialog(SoundMeta(id="a", name="Song", file="x.mp3",
                                            source=dict(SRC, link=music)))
    texts = {lab.text() for lab in d.findChildren(QLabel)}
    assert {"Uploaded", "2009-10-25", "3:33", "Views", "1,700,000,000 (when added)"} <= texts
    assert d.windowTitle() == "YouTube Music"
    d.btn_open.click()
    assert opened == [music]
    d.close()
