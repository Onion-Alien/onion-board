"""The browser's "Add as sound": which pages offer it, the yt-dlp wrapper (with a fake yt_dlp, no
network), and the browser tab turning a download into a sound."""
import hashlib
import io
import json
import sys
import time
import types
import zipfile

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
        ytdl.download_audio("https://youtu.be/x", tmp_path, auto_update=False)
    assert str(e.value) == "Video unavailable"
    assert isinstance(e.value, ytdl.FetchError)   # yt-dlp's fault: an update may help


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

    def fake_download(url, dest=None, progress=None, auto_update=True):
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
    monkeypatch.setattr(ytdl, "download_audio", lambda url, dest=None, progress=None, **kw:
                        (p, "Again"))
    tab = BrowserTab(FakeEngine(), Config(browser_url="about:blank"), lambda: None, FakeMeter)
    got = []
    tab.sound_ready.connect(lambda m, d: got.append(m))
    tab._download("https://youtu.be/x", "#123456", known)
    process_events(qapp, lambda: "Old one" in tab.info.text(), 3)
    assert not got and "already in your Sounds" in tab.info.text()


# ---------------------------------------------------------------- keeping yt-dlp current

@pytest.fixture
def pypi(app_dir, monkeypatch):
    """A fake PyPI: `releases[version]` makes a wheel whose yt_dlp says that version.
    Nothing touches the network; the import hook is removed afterwards."""
    state = {"latest": "2099.1.1", "fetched": [], "corrupt": False}

    def wheel(pkg, version):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr(f"{pkg}/__init__.py", f"__version__ = {version!r}\nFAKE = True\n")
            z.writestr(f"{pkg}/sub.py", "X = 1\n")
            z.writestr(f"{pkg}-{version}.dist-info/METADATA", "Name: x\n")
        return buf.getvalue()

    def release(name, version, requires=()):
        data = wheel(name.replace("-", "_"), version)
        url = f"{ytdl.WHEEL_HOST}{name}-{version}-py3-none-any.whl"
        state[url] = data
        digest = "0" * 64 if state["corrupt"] else hashlib.sha256(data).hexdigest()
        return {"info": {"name": name, "version": version, "requires_dist": list(requires)},
                "urls": [{"packagetype": "bdist_wheel", "url": url, "digests": {"sha256": digest},
                          "filename": url.rsplit("/", 1)[1]}]}

    def get(url, limit):
        state["fetched"].append(url)
        if url == ytdl.PYPI.format("yt-dlp"):
            return json.dumps(release("yt-dlp", state["latest"],
                                      ['yt-dlp-ejs==0.9.0; extra == "default"'])).encode()
        if url.endswith("/yt-dlp-ejs/0.9.0/json"):
            return json.dumps(release("yt-dlp-ejs", "0.9.0")).encode()
        return state[url]

    monkeypatch.setattr(ytdl, "_get", get)
    monkeypatch.setattr(ytdl, "bundled_version", lambda: "2026.8.19")
    saved = {n: m for n, m in sys.modules.items() if n.partition(".")[0] in ytdl.PACKAGES}
    yield state
    if ytdl._finder in sys.meta_path:
        sys.meta_path.remove(ytdl._finder)
    ytdl._purge()
    sys.modules.update(saved)


def test_update_installs_a_newer_copy_that_imports_win(pypi):
    assert ytdl.update() == "Updated yt-dlp to 2099.1.1."
    assert ytdl.active_version() == ("2099.1.1", True)
    ytdl.install()
    import yt_dlp
    import yt_dlp.sub
    assert yt_dlp.FAKE and yt_dlp.__version__ == "2099.1.1"
    assert yt_dlp.sub.__file__.startswith(str(ytdl._pkg_dir()))
    assert (ytdl._pkg_dir() / "yt_dlp_ejs" / "__init__.py").is_file()   # its pinned partner
    assert not list(ytdl._pkg_dir().glob("*.dist-info"))
    assert not list(ytdl.root().glob("new-*")) and not list(ytdl.root().glob("old-*"))


def test_update_skips_when_up_to_date(pypi):
    pypi["latest"] = "2026.08.19"
    assert "up to date" in ytdl.update()
    assert pypi["fetched"] == [ytdl.PYPI.format("yt-dlp")]   # no wheel downloaded
    assert not ytdl.due()                                    # but it counts as a check


def test_update_rejects_a_bad_checksum(pypi):
    pypi["corrupt"] = True
    with pytest.raises(ytdl.DownloadError, match="checksum"):
        ytdl.update()
    assert ytdl.active_version() == ("2026.8.19", False)


def test_reset_clears_and_reinstalls(pypi):
    ytdl.update()
    junk = ytdl.cache_dir() / "youtube-sigfuncs" / "x.json"
    junk.parent.mkdir(parents=True)
    junk.write_text("{}")
    pypi["latest"] = "2099.2.2"
    assert "2099.2.2" in ytdl.reset()
    assert not junk.exists()
    assert ytdl.active_version() == ("2099.2.2", True)


def test_reset_offline_falls_back_to_the_built_in_copy(pypi, monkeypatch):
    ytdl.update()

    def offline(url, limit):
        raise OSError("no network")
    monkeypatch.setattr(ytdl, "_get", offline)
    msg = ytdl.reset()
    assert "built-in yt-dlp 2026.8.19" in msg and not ytdl.root().exists()


def test_a_copy_older_than_the_bundled_one_is_dropped(pypi):
    pypi["latest"] = "2099.1.1"
    ytdl.update()
    ytdl._save_state(version="2020.1.1")   # the app has since shipped a newer yt-dlp
    ytdl.install()
    assert ytdl.active_version() == ("2026.8.19", False)


def test_auto_update_only_when_enabled_and_due(pypi):
    ytdl.auto_update(False)
    assert pypi["fetched"] == []
    ytdl.auto_update(True)
    assert ytdl.override_version() == "2099.1.1"
    pypi["fetched"].clear()
    ytdl.auto_update(True)                     # checked a moment ago
    assert pypi["fetched"] == []
    ytdl._save_state(checked=time.time() - ytdl.CHECK_EVERY - 1)
    assert ytdl.due()


def test_a_failed_download_updates_and_retries_once(pypi, monkeypatch, tmp_path):
    calls = []

    def dl(url, dest, progress):
        calls.append(ytdl.override_version())
        if len(calls) == 1:
            raise ytdl.FetchError("Sign in to confirm you're not a bot")
        return tmp_path / "a.m4a", "Title"

    monkeypatch.setattr(ytdl, "_download", dl)
    assert ytdl.download_audio("https://youtu.be/x")[1] == "Title"
    assert calls == ["", "2099.1.1"]           # retried with the new copy

    calls.clear()                               # checked just now: no second update
    with pytest.raises(ytdl.FetchError):
        ytdl.download_audio("https://youtu.be/x")
    assert calls == ["2099.1.1"]


def test_a_refused_download_does_not_update(pypi, monkeypatch):
    def dl(url, dest, progress):
        raise ytdl.DownloadError("That's a playlist")
    monkeypatch.setattr(ytdl, "_download", dl)
    with pytest.raises(ytdl.DownloadError):
        ytdl.download_audio("https://youtu.be/x")
    assert pypi["fetched"] == []


# ---------------------------------------------------------------- Settings → General

from test_mainwindow import window  # noqa: E402,F401  (the real MainWindow fixture)


def test_settings_downloader_card(qapp, window, monkeypatch):  # noqa: F811
    from soundboard.settings import SettingsDialog
    monkeypatch.setattr(ytdl, "active_version", lambda: ("2026.8.19", False))
    monkeypatch.setattr(ytdl, "update", lambda: "Updated yt-dlp to 2099.1.1.")
    d = SettingsDialog(window, "general")
    assert "2026.8.19 (built in)" in d.ytdlp_label.text()
    d.ytdlp_btns[0].click()                               # Update now
    assert not d.ytdlp_btns[0].isEnabled()
    monkeypatch.setattr(ytdl, "active_version", lambda: ("2099.1.1", True))
    assert process_events(qapp, lambda: d.ytdlp_btns[0].isEnabled(), 5)
    assert d.ytdlp_label.text() == ("Updated yt-dlp to 2099.1.1. "
                                    "In use: yt-dlp 2099.1.1 (updated copy).")
    d.close()
