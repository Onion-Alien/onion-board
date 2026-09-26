"""The browser's "Add as sound": which pages offer it, the yt-dlp wrapper (with a fake yt_dlp, no
network), and the browser tab turning a download into a sound."""
import sys
import types

import numpy as np
import pytest
import soundfile as sf
from PySide6.QtWidgets import QWidget

from conftest import process_events
from soundboard import ytdl
from soundboard.browser import BrowserTab
from soundboard.engine import SR
from soundboard.library import Config


@pytest.mark.parametrize("url, ok", [
    ("https://www.youtube.com/watch?v=jNQXAC9IVRw", True),
    ("https://www.youtube.com/watch?v=jNQXAC9IVRw&list=PL123", True),
    ("https://m.youtube.com/shorts/abcdefGHIJK", True),
    ("https://youtu.be/jNQXAC9IVRw", True),
    ("https://soundcloud.com/artist/track", True),
    ("https://www.youtube.com/", False),
    ("https://www.youtube.com/results?search_query=bruh", False),
    ("https://soundcloud.com/", False),
    ("about:blank", False),
    ("file:///C:/x.html", False),
])
def test_downloadable(url, ok):
    assert ytdl.downloadable(url) is ok


def test_clean_title_drops_video_noise():
    assert ytdl.clean_title("Song Name (Official Music Video)") == "Song Name"
    assert ytdl.clean_title("Bruh Sound Effect #2 [HD]") == "Bruh Sound Effect #2"
    assert ytdl.clean_title("Just a title") == "Just a title"


def fake_yt_dlp(monkeypatch, info, write=b"audio", fail=None):
    """Install a stand-in `yt_dlp` module; returns the options it was given."""
    seen = {}

    class YoutubeDL:
        def __init__(self, opts):
            seen.update(opts)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=True):
            if fail:
                raise Exception(fail)
            return dict(info)

        def process_ie_result(self, info, download=True):
            for hook in seen["progress_hooks"]:
                hook({"status": "downloading", "downloaded_bytes": 5, "total_bytes": 10})
            self.path = seen["outtmpl"].replace("%(id)s", "vid").replace("%(ext)s", "m4a")
            with open(self.path, "wb") as f:
                f.write(write)
            return info

        def prepare_filename(self, info):
            return self.path

    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=YoutubeDL))
    return seen


def test_download_audio_returns_file_and_clean_title(monkeypatch, tmp_path):
    seen = fake_yt_dlp(monkeypatch, {"title": "Boom (Official Audio)", "duration": 3})
    got = []
    path, title = ytdl.download_audio("https://youtu.be/x", tmp_path, got.append)
    assert path.read_bytes() == b"audio" and path.parent == tmp_path
    assert title == "Boom"
    assert got == [0.5]
    assert seen["noplaylist"] and seen["format"].startswith("bestaudio")


def test_download_audio_refuses_playlists_and_live(monkeypatch, tmp_path):
    fake_yt_dlp(monkeypatch, {"_type": "playlist", "title": "x"})
    with pytest.raises(ytdl.DownloadError, match="playlist"):
        ytdl.download_audio("https://youtu.be/x", tmp_path)
    fake_yt_dlp(monkeypatch, {"is_live": True, "title": "x"})
    with pytest.raises(ytdl.DownloadError, match="live"):
        ytdl.download_audio("https://youtu.be/x", tmp_path)


def test_download_audio_errors_are_readable(monkeypatch, tmp_path):
    fake_yt_dlp(monkeypatch, {}, fail="ERROR: \x1b[0;31mVideo unavailable\x1b[0m")
    with pytest.raises(ytdl.DownloadError) as e:
        ytdl.download_audio("https://youtu.be/x", tmp_path)
    assert str(e.value) == "Video unavailable"


class FakeEngine:
    level_browser = 0.0
    browser_live = browser_monitor = False
    browser_vol = 1.0

    def __init__(self):
        self.prepared = []

    def prepare(self, sid, data):
        self.prepared.append(sid)


class FakeMeter(QWidget):
    def set_level(self, _level):
        pass


def test_tab_download_becomes_a_sound(qapp, app_dir, monkeypatch, tmp_path):
    folder = tmp_path / "dl"
    folder.mkdir()

    def fake_download(url, dest=None, progress=None):
        t = np.arange(SR) / SR
        p = folder / "vid.wav"
        sf.write(p, np.stack([np.sin(2 * np.pi * 440 * t)] * 2, 1) * 0.5, SR)
        progress(1.0)
        return p, "A Tone"

    monkeypatch.setattr(ytdl, "download_audio", fake_download)
    eng = FakeEngine()
    tab = BrowserTab(eng, Config(browser_url="about:blank"), lambda: None, FakeMeter)
    got = []
    tab.sound_ready.connect(lambda m, d: got.append((m, d)))
    tab._downloading = True
    tab._download("https://youtu.be/x", "#123456", {})
    assert process_events(qapp, lambda: got and not tab._downloading, 5)
    meta, data = got[0]
    assert meta.name == "A Tone" and abs(meta.duration - 1.0) < 0.01
    assert eng.prepared == [meta.id] and len(data) == SR
    assert not folder.exists()                       # the download is cleaned up
    assert "Added" in tab.info.text() and tab.btn_add.text() == "Add as sound"


def test_tab_download_skips_a_sound_already_in_the_library(qapp, app_dir, monkeypatch,
                                                           tmp_path):
    p = tmp_path / "dl" / "vid.wav"
    p.parent.mkdir()
    sf.write(p, np.zeros((SR, 2)) + 0.1, SR)
    from soundboard.library import fingerprint
    known = {fingerprint(str(p)): "Old one"}
    monkeypatch.setattr(ytdl, "download_audio", lambda url, dest=None, progress=None:
                        (p, "Again"))
    tab = BrowserTab(FakeEngine(), Config(browser_url="about:blank"), lambda: None, FakeMeter)
    got = []
    tab.sound_ready.connect(lambda m, d: got.append(m))
    tab._download("https://youtu.be/x", "#123456", known)
    process_events(qapp, lambda: "Old one" in tab.info.text(), 3)
    assert not got and "already in your Sounds" in tab.info.text()
