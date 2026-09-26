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


def test_auto_update_is_opt_in(qapp, app_dir, monkeypatch):
    assert Config().ytdlp_auto_optin is False
    # a config saved while it defaulted to on (under the old name) starts off again
    assert Config.from_raw({"ytdlp_auto_update": True}).ytdlp_auto_optin is False

    def fail(url, dest=None, progress=None, auto_update=True):
        assert auto_update is False
        raise ytdl.FetchError("Sign in to confirm you're not a bot")
    monkeypatch.setattr(ytdl, "download_audio", fail)
    tab = BrowserTab(FakeEngine(), Config(browser_url="about:blank"), lambda: None, FakeMeter)
    tab._download("https://youtu.be/x", "#123456", {})
    assert process_events(qapp, lambda: "Update now" in tab.info.text(), 3)


# ---------------------------------------------------------------- the Sounds tab's link bar

@pytest.mark.parametrize("text, url", [
    ("https://youtu.be/jNQXAC9IVRw", "https://youtu.be/jNQXAC9IVRw"),
    ("  https://www.tiktok.com/@a/video/123 ", "https://www.tiktok.com/@a/video/123"),
    ("www.example.com/clip.mp3", "https://www.example.com/clip.mp3"),
    ("http://example.com", "http://example.com"),
    ("bruh", ""),
    ("air horn", ""),
    ("file:///C:/x.mp3", ""),
    ("javascript:alert(1)", ""),
    ("https://", ""),
])
def test_as_link(text, url):
    assert ytdl.as_link(text) == url


def test_probe_returns_title_and_duration_without_downloading(monkeypatch):
    seen = fake_yt_dlp(monkeypatch, {"title": "Boom [HD]", "duration": 4})
    assert ytdl.probe("https://youtu.be/x") == ("Boom", 4.0)
    assert seen["noplaylist"]
    fake_yt_dlp(monkeypatch, {"_type": "playlist"})
    with pytest.raises(ytdl.DownloadError, match="playlist"):
        ytdl.probe("https://youtu.be/x")
    fake_yt_dlp(monkeypatch, {}, fail="ERROR: Unsupported URL: https://example.com")
    with pytest.raises(ytdl.FetchError, match="^Unsupported URL"):
        ytdl.probe("https://example.com")


def fake_link_download(monkeypatch, tmp_path):
    """download_audio writes a 1 s tone into a fresh folder; returns the call log."""
    calls = []

    def download(url, dest=None, progress=None, auto_update=True):
        calls.append(url)
        folder = tmp_path / f"dl{len(calls)}"
        folder.mkdir()
        t = np.arange(SR) / SR
        p = folder / "vid.wav"
        sf.write(p, np.stack([np.sin(2 * np.pi * 330 * t)] * 2, 1) * 0.5, SR)
        progress(1.0)
        return p, "A Tone"

    monkeypatch.setattr(ytdl, "download_audio", download)
    monkeypatch.setattr(ytdl, "probe", lambda url: ("A Tone", 1.0))
    return calls


def test_link_in_search_shows_the_bar_and_filters_nothing(qapp, window, monkeypatch,  # noqa: F811
                                                          tmp_path):
    fake_link_download(monkeypatch, tmp_path)
    window.search.setText("Boom")
    assert window.linkbar.isHidden()
    assert window.pads["s1"].property("filtered")
    window.search.setText("https://youtu.be/abc")
    assert not window.linkbar.isHidden() and window.linkbar.url == "https://youtu.be/abc"
    assert not any(p.property("filtered") for p in window.pads.values())
    assert process_events(qapp, lambda: "A Tone" in window.linkbar.info.text(), 3)
    window.search.clear()
    assert window.linkbar.isHidden() and window.linkbar.url == ""


def test_link_add_as_sound(qapp, window, monkeypatch, tmp_path):  # noqa: F811
    calls = fake_link_download(monkeypatch, tmp_path)
    window.search.setText("https://youtu.be/abc")
    window.search.returnPressed.emit()                       # Enter = Add as sound
    assert process_events(qapp, lambda: len(window.cfg.sounds) == 3, 5)
    m = window.cfg.sounds[-1]
    assert m.name == "A Tone" and m.id in window.pads and m.id in window.audio
    assert calls == ["https://youtu.be/abc"]
    assert not (tmp_path / "dl1").exists()                   # the download is cleaned up
    assert "Added" in window.linkbar.info.text()
    window.linkbar.add()                                     # the same again: refused
    assert process_events(qapp, lambda: "already in your Sounds" in
                          window.linkbar.info.text(), 5)
    assert len(window.cfg.sounds) == 3


def test_link_play_once_then_add_downloads_once(qapp, window, monkeypatch, tmp_path):  # noqa: F811
    calls = fake_link_download(monkeypatch, tmp_path)
    played = []
    monkeypatch.setattr(window.engine, "play",
                        lambda sid, data, gain, **kw: played.append((sid, len(data))) or object())
    window.search.setText("https://youtu.be/abc")
    assert window.linkbar.play_once()
    assert process_events(qapp, lambda: played, 5)
    assert played == [("__link__", SR)] and len(window.cfg.sounds) == 2   # nothing kept
    assert "Playing" in window.linkbar.info.text()
    window.linkbar.play_once()                               # again: no second download
    assert len(played) == 2 and calls == ["https://youtu.be/abc"]
    window.linkbar.add()
    assert process_events(qapp, lambda: len(window.cfg.sounds) == 3, 5)
    assert calls == ["https://youtu.be/abc"]
    assert not (tmp_path / "dl1").exists()


def test_link_change_drops_the_kept_download(qapp, window, monkeypatch, tmp_path):  # noqa: F811
    fake_link_download(monkeypatch, tmp_path)
    monkeypatch.setattr(window.engine, "play", lambda *a, **kw: object())
    window.search.setText("https://youtu.be/abc")
    window.linkbar.play_once()
    assert process_events(qapp, lambda: window.linkbar._got is not None, 5)
    window.search.setText("https://youtu.be/other")
    assert window.linkbar._got is None and not (tmp_path / "dl1").exists()


def test_link_play_once_shows_in_the_transport_bar(qapp, window, monkeypatch,  # noqa: F811
                                                   tmp_path):
    fake_link_download(monkeypatch, tmp_path)
    monkeypatch.setattr(window.engine, "play", lambda *a, **kw: object())
    window.search.setText("https://youtu.be/abc")
    window.linkbar.play_once()
    assert process_events(qapp, lambda: window.current == "__link__", 5)
    assert window.np_name.text() == "A Tone"
    assert window.meta("__link__").duration == 1.0
    window._update_transport({"__link__": (0.5, False)})
    assert window.btn_pp.isEnabled() and window.seek.value() == 500
    paused = []
    monkeypatch.setattr(window.engine, "state", lambda sid: (0.5, False))
    monkeypatch.setattr(window.engine, "set_paused", lambda sid, p: paused.append((sid, p)))
    window.toggle_play_pause()                               # the ⏸ button pauses it
    assert paused == [("__link__", True)]
    assert window.cfg.sounds and all(m.id != "__link__" for m in window.cfg.sounds)
