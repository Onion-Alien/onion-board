"""Downloading and searching with yt-dlp: which pages offer "Add as sound", the yt-dlp
wrapper (with a fake yt_dlp, no network), the link bar and the web search."""
import hashlib
import io
import json
import sys
import tempfile
import threading
import time
import types
import zipfile
from pathlib import Path
from collections import namedtuple

import numpy as np
import pytest
import soundfile as sf

from conftest import process_events
from soundboard import ytdl
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
            seen["query"] = url
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
    assert str(e.value) == "That video isn't available any more."   # errors.describe
    assert isinstance(e.value, ytdl.FetchError)   # yt-dlp's fault: an update may help


def test_a_failed_download_leaves_no_temp_folder(monkeypatch, tmp_path):
    fake_yt_dlp(monkeypatch, {}, fail="ERROR: Video unavailable")
    monkeypatch.setattr(ytdl.tempfile, "tempdir", str(tmp_path))
    with pytest.raises(ytdl.DownloadError):
        ytdl.download_audio("https://youtu.be/x", auto_update=False)
    assert not list(tmp_path.glob("sb-ytdl-*"))


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
    if ytdl._finder in sys.meta_path:   # an earlier test's search put it in: start without
        sys.meta_path.remove(ytdl._finder)
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


def test_a_swap_that_fails_halfway_keeps_the_copy_in_use(pypi, monkeypatch):
    ytdl.update()
    pypi["latest"] = "2099.2.2"
    real = Path.rename

    def rename(self, target):
        if self.name.startswith("new-"):
            raise PermissionError("in use")
        return real(self, target)
    with monkeypatch.context() as m:
        m.setattr(Path, "rename", rename)
        with pytest.raises(ytdl.DownloadError):
            ytdl.update()
    assert ytdl.active_version() == ("2099.1.1", True)
    assert (ytdl._pkg_dir() / "yt_dlp" / "__init__.py").is_file()
    assert not list(ytdl.root().glob("old-*")) and not list(ytdl.root().glob("new-*"))


def test_leftovers_of_a_cut_short_update_are_tidied_at_startup(pypi):
    ytdl.update()
    ytdl._pkg_dir().rename(ytdl.root() / "old-1")   # stopped between the two renames
    (ytdl.root() / "new-abc" / "yt_dlp").mkdir(parents=True)
    ytdl.install()
    assert ytdl.active_version() == ("2099.1.1", True)
    assert (ytdl._pkg_dir() / "yt_dlp" / "__init__.py").is_file()
    assert not list(ytdl.root().glob("old-*")) and not list(ytdl.root().glob("new-*"))


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

    def dl(url, dest, progress, *_feature):
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
    def dl(url, dest, progress, *_feature):
        raise ytdl.DownloadError("That's a playlist")
    monkeypatch.setattr(ytdl, "_download", dl)
    with pytest.raises(ytdl.DownloadError):
        ytdl.download_audio("https://youtu.be/x")
    assert pypi["fetched"] == []


# ---------------------------------------------------------------- Settings → Updates

from test_mainwindow import window  # noqa: E402,F401  (the real MainWindow fixture)


def test_settings_downloader_card(qapp, window, monkeypatch):  # noqa: F811
    from soundboard.settings import SettingsDialog
    monkeypatch.setattr(ytdl, "active_version", lambda: ("2026.8.19", False))
    monkeypatch.setattr(ytdl, "update", lambda: "Updated yt-dlp to 2099.1.1.")
    d = SettingsDialog(window, "updates")
    assert "2026.8.19 (built in)" in d.ytdlp_label.text()
    d.ytdlp_btns[0].click()                               # Update now
    assert not d.ytdlp_btns[0].isEnabled()
    monkeypatch.setattr(ytdl, "active_version", lambda: ("2099.1.1", True))
    assert process_events(qapp, lambda: d.ytdlp_btns[0].isEnabled(), 5)
    assert d.ytdlp_label.text() == ("Updated yt-dlp to 2099.1.1. "
                                    "In use: yt-dlp 2099.1.1 (updated copy).")
    d.close()


def test_auto_update_is_opt_in():
    assert Config().ytdlp_auto_optin is False
    # a config saved while it defaulted to on (under the old name) starts off again
    assert Config.from_raw({"ytdlp_auto_update": True}).ytdlp_auto_optin is False


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
    with pytest.raises(ytdl.FetchError, match="^That link isn.t from a site"):
        ytdl.probe("https://example.com")


def fake_link_download(monkeypatch, tmp_path):
    """download_audio writes a 1 s tone into a fresh folder; returns the call log."""
    calls = []

    def download(url, dest=None, progress=None, auto_update=True):
        calls.append(url)
        folder = tmp_path / f"sb-ytdl-{len(calls)}"   # the link bar only deletes these
        folder.mkdir()
        t = np.arange(SR) / SR
        p = folder / "vid.wav"
        sf.write(p, np.stack([np.sin(2 * np.pi * 330 * t)] * 2, 1) * 0.5, SR)
        progress(1.0)
        return p, "A Tone"

    monkeypatch.setattr(ytdl, "download_audio", download)
    monkeypatch.setattr(ytdl, "probe", lambda url: ("A Tone", 1.0))
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
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
    assert not (tmp_path / "sb-ytdl-1").exists()                   # the download is cleaned up
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
    assert not (tmp_path / "sb-ytdl-1").exists()


def test_link_change_drops_the_kept_download(qapp, window, monkeypatch, tmp_path):  # noqa: F811
    fake_link_download(monkeypatch, tmp_path)
    monkeypatch.setattr(window.engine, "play", lambda *a, **kw: object())
    window.search.setText("https://youtu.be/abc")
    window.linkbar.play_once()
    assert process_events(qapp, lambda: window.linkbar._got is not None, 5)
    window.search.setText("https://youtu.be/other")
    assert window.linkbar._got is None and not (tmp_path / "sb-ytdl-1").exists()


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


def test_search_lists_videos_and_skips_live_and_junk(monkeypatch):
    seen = fake_yt_dlp(monkeypatch, {"_type": "playlist", "entries": [
        {"id": "HEXWRTEbj1I", "title": "What Is Love", "channel": "Haddaway", "duration": 241},
        {"id": "abcdefghijk", "title": "Live now", "live_status": "is_live"},
        {"id": "not-a-video-id", "title": "A channel"},
        {"id": "zGG4kWoN8Zc", "title": "Remix", "uploader": "Someone"},
    ]})
    r = ytdl.search("  what   is love ", 5)
    assert seen["query"] == "ytsearch5:what is love"
    assert seen["extract_flat"] == "in_playlist" and "outtmpl" not in seen
    assert [x.id for x in r] == ["HEXWRTEbj1I", "zGG4kWoN8Zc"]
    assert (r[0].title, r[0].channel, r[0].seconds) == ("What Is Love", "Haddaway", 241)
    assert r[1].channel == "Someone" and r[1].seconds == 0
    assert r[0].url == "https://www.youtube.com/watch?v=HEXWRTEbj1I"
    assert r[0].thumb == "https://i.ytimg.com/vi/HEXWRTEbj1I/mqdefault.jpg"
    assert ytdl.search("   ") == []
    fake_yt_dlp(monkeypatch, {}, fail="ERROR: network down")
    with pytest.raises(ytdl.FetchError, match="^The downloader ran into a problem: network down"):
        ytdl.search("x")


def test_search_soundcloud_links_the_track_page_and_its_bigger_art(monkeypatch):
    seen = fake_yt_dlp(monkeypatch, {"_type": "playlist", "entries": [
        {"id": "556218435", "title": "bruh sound effect #2", "uploader": "SHYNEZ",
         "duration": 145.6, "webpage_url": "https://soundcloud.com/someone/bruh-2",
         "url": "https://api.soundcloud.com/tracks/soundcloud%3Atracks%3A556218435",
         "thumbnails": [{"url": "https://i1.sndcdn.com/artworks-abc-mini.jpg"},
                        {"url": "https://i1.sndcdn.com/artworks-abc-small.jpg"}]},
        {"id": "1", "title": "Not SoundCloud", "url": "https://example.com/x"},
        None,
    ]})
    r = ytdl.search("bruh", 10, source="soundcloud")
    assert seen["query"] == "scsearch10:bruh"
    assert len(r) == 1 and r[0].source == "soundcloud"
    assert (r[0].title, r[0].channel, r[0].seconds) == ("bruh sound effect #2", "SHYNEZ", 145.6)
    assert r[0].url == "https://soundcloud.com/someone/bruh-2"
    assert r[0].thumb == "https://i1.sndcdn.com/artworks-abc-t300x300.jpg"


def test_enter_searches_youtube_and_a_result_plays_through_the_link_bar(
        qapp, window, monkeypatch, tmp_path):  # noqa: F811
    calls = fake_link_download(monkeypatch, tmp_path)
    hits = [ytdl.Result("HEXWRTEbj1I", "What Is Love", "Haddaway", 241)]
    searched = []
    monkeypatch.setattr(ytdl, "search", lambda q, count=20, source="youtube": (
        searched.append(source), hits)[1])
    monkeypatch.setattr(window.engine, "play", lambda *a, **kw: object())
    window.ytresults.net.get = lambda req: types.SimpleNamespace(   # no thumbnail fetch
        finished=types.SimpleNamespace(connect=lambda f: None))
    window.search.setText("what is love")
    window.search.returnPressed.emit()                       # Enter: search YouTube
    assert process_events(qapp, lambda: window.ytresults._rows, 5)
    assert window._pads_scroll.isHidden() and not window.ytresults.isHidden()
    window.ytresults._rows[0].btn_play.click()
    assert process_events(qapp, lambda: window.current == "__link__", 5)
    assert calls == ["https://www.youtube.com/watch?v=HEXWRTEbj1I"]
    assert window.np_name.text() == "What Is Love" and len(window.cfg.sounds) == 2
    window.search.returnPressed.emit()                       # Enter again: searches, no add
    assert process_events(qapp, lambda: window.ytresults._rows, 5)
    assert len(window.cfg.sounds) == 2
    window.ytresults._rows[0].btn_add.click()                # Add: reuses the download
    assert process_events(qapp, lambda: len(window.cfg.sounds) == 3, 5)
    assert len(calls) == 1
    window.ytresults.site_btns["soundcloud"].click()       # another site: searches again
    assert process_events(qapp, lambda: searched[-1:] == ["soundcloud"], 5)
    assert searched == ["youtube", "youtube", "soundcloud"]
    assert "No SoundCloud results" not in window.ytresults.title.text()
    window.ytresults.close_results()
    assert not window._pads_scroll.isHidden() and window.ytresults.isHidden()


def test_search_tiktok_and_youtube_music_go_through_youtube(monkeypatch):
    seen = fake_yt_dlp(monkeypatch, {"_type": "playlist", "entries": [
        {"id": "HEXWRTEbj1I", "title": "What Is Love"}]})
    r = ytdl.search("what is love", 5, source="tiktok")
    assert seen["query"] == "ytsearch5:what is love tiktok sound"
    assert r[0].url == "https://www.youtube.com/watch?v=HEXWRTEbj1I" and r[0].thumb
    ytdl.search("what is love", 5, source="ytmusic")
    assert seen["query"] == "https://music.youtube.com/search?q=what+is+love#songs"
    assert seen["playlistend"] == 5


MYINSTANTS_PAGE = """
<div class="instant"><button class="small-button"
  onclick="play('/media/sounds/vine-boom.mp3', 'loader-1', 'vine-boom-1')"></button>
<a href="/en/instant/vine-boom-1/" class="instant-link link-secondary">VINE BOOM &amp; CO</a></div>
<div class="instant"><button class="small-button"
  onclick="play('/media/sounds/bruh.mp3', 'loader-2', 'bruh-2')"></button>
<a href="/en/instant/bruh-2/" class="instant-link link-secondary">bruh</a></div>
"""


class _Resp(io.BytesIO):
    headers: dict = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_search_myinstants_reads_the_buttons_and_downloads_the_mp3(monkeypatch, tmp_path):
    asked = []

    def urlopen(req, timeout=0, feature=None, direct=False):
        asked.append((req.full_url, req.headers.get("User-agent", "")))
        return _Resp(MYINSTANTS_PAGE.encode() if "/search/" in req.full_url else b"ID3mp3")
    monkeypatch.setattr(ytdl.net, "urlopen", urlopen)
    r = ytdl.search("vine  boom", 1, source="myinstants")
    assert asked[0][0] == "https://www.myinstants.com/en/search/?name=vine+boom"
    assert "Mozilla" in asked[0][1]
    assert len(r) == 1 and r[0].title == "VINE BOOM & CO" and r[0].thumb == ""
    assert r[0].url == "https://www.myinstants.com/media/sounds/vine-boom.mp3"
    assert len(ytdl.search("vine boom", 10, source="myinstants")) == 2
    assert ytdl.probe(r[0].url) == ("Vine boom", 0.0)
    path, title = ytdl.download_audio(r[0].url, dest=tmp_path)   # no yt-dlp involved
    assert path == tmp_path / "vine-boom.mp3" and path.read_bytes() == b"ID3mp3"
    assert title == "Vine boom"


def test_results_spin_while_searching_and_offer_every_site(qapp, monkeypatch):
    from soundboard.ui.ytsearch import SearchResults
    gate = threading.Event()
    monkeypatch.setattr(ytdl, "search", lambda q, count=20, source="youtube": (
        gate.wait(5), [])[1])
    panel = SearchResults()
    assert set(panel.site_btns) == set(ytdl.SOURCES) >= {"tiktok", "myinstants", "ytmusic"}
    panel.set_source("tiktok")
    panel.search("bruh")
    assert panel.spinner.running() and "TikTok sounds" in panel.title.text()
    gate.set()
    assert process_events(qapp, lambda: not panel.spinner.running(), 5)
    assert "No TikTok results" in panel.title.text()
    panel.search("again")
    assert panel.spinner.running()
    panel.close_results()                        # closing stops it too
    assert not panel.spinner.running()


def test_searching_shows_a_centred_mascot_then_the_results(qapp, monkeypatch):
    from soundboard.ui.bunnywidget import BunnyWidget
    from soundboard.ui.owl import OwlWidget
    from soundboard.ui.ytsearch import SearchResults
    gate = threading.Event()
    hit = ytdl.Result(id="x", title="Bruh", channel="c", seconds=3.0, source="myinstants")
    monkeypatch.setattr(ytdl, "search", lambda q, count=20, source="youtube": (
        gate.wait(5), [hit])[1])
    panel = SearchResults()
    panel.resize(700, 500)
    panel.search("bruh")
    qapp.processEvents()
    view = panel.loading
    assert view.isVisible() and not panel.scroll.isVisible()
    assert view.kind in ("bunny", "owl")
    assert isinstance(view.mascot, OwlWidget if view.kind == "owl" else BunnyWidget)
    assert view.mascot.isVisible() and view.bar.ticking()
    assert "Searching YouTube for <b>bruh</b>" in view.label.text()
    centre = view.rect().center()
    for w in (view.mascot, view.bar, view.label):    # stacked down the middle
        assert abs(w.geometry().center().x() - centre.x()) <= 2
    assert view.mascot.geometry().top() > 20 and view.label.geometry().bottom() < view.height() - 20
    assert view.mascot.geometry().bottom() < view.bar.geometry().top() \
        < view.label.geometry().top()
    panel.resize(300, 120)                            # no room: the mascot steps aside
    qapp.processEvents()
    assert not view.mascot.isVisible() and view.label.isVisible()
    assert view.label.geometry().bottom() <= view.height()
    panel.resize(700, 500)
    qapp.processEvents()
    assert view.mascot.isVisible()
    kinds = set()
    for _ in range(40):                               # a coin toss each search
        view.start("x")
        kinds.add(view.kind)
    assert kinds == {"bunny", "owl"}
    gate.set()
    assert process_events(qapp, lambda: not view.running(), 5)
    assert not view.isVisible() and not view.bar.ticking()
    assert panel.scroll.isVisible() and len(panel._rows) == 1
    assert not panel.title.isVisible()   # results need no caption
    panel.close_results()


@pytest.mark.parametrize("url", [
    "https://www.myinstants.com/media/sounds/real.mp3?x=%5C..%5C..%5Cx.bat",
    "https://www.myinstants.com/media/sounds/real.mp3#%5C..%5Cx.bat",
    "https://www.myinstants.com/media/sounds/x.bat",
])
def test_direct_download_refuses_names_that_leave_its_folder(url, monkeypatch):
    monkeypatch.setattr(ytdl.net, "urlopen", lambda *a, **k: pytest.fail("fetched"))
    with pytest.raises(ytdl.DownloadError):
        ytdl._download_direct(url, None, None)


def test_direct_leaf_keeps_only_a_plain_file_name():
    assert ytdl._direct_leaf("https://www.myinstants.com/media/sounds/vine-boom.mp3") \
        == "vine-boom.mp3"
    leaf = ytdl._direct_leaf("https://www.myinstants.com/media/sounds/%2e%2e%5cStartup%5cx.mp3")
    assert "\\" not in leaf and "/" not in leaf and not leaf.startswith(".")


def test_yt_dlp_is_shared_and_an_update_waits_for_its_users():
    """One slow lookup mustn't hold up a search; swapping in a new copy waits for both."""
    order = []
    first_in, release = threading.Event(), threading.Event()

    def slow_user():
        with ytdl._lock.shared():
            first_in.set()
            release.wait(5)
            order.append("slow done")

    def updater():
        with ytdl._lock.exclusive():
            order.append("swapped")

    a = threading.Thread(target=slow_user)
    a.start()
    assert first_in.wait(5)
    with ytdl._lock.shared():            # a search gets in while the lookup is still going
        order.append("search")
    u = threading.Thread(target=updater)
    u.start()
    u.join(0.3)
    assert u.is_alive() and order == ["search"]   # the swap waits for the lookup
    release.set()
    a.join(5)
    u.join(5)
    assert order == ["search", "slow done", "swapped"]


@pytest.mark.parametrize("answer", [b"<html>down for maintenance</html>", b'{"x": 1}', b"[]"])
def test_update_says_so_when_pypi_answers_junk(monkeypatch, answer):
    monkeypatch.setattr(ytdl, "_get", lambda url, limit: answer)
    with pytest.raises(ytdl.DownloadError, match="PyPI"):
        ytdl.update()


def test_add_on_a_second_result_while_one_downloads_adds_both(qapp, window, monkeypatch,  # noqa: F811
                                                                tmp_path):
    fake_link_download(monkeypatch, tmp_path)
    gate = threading.Event()

    def slow(url, dest=None, progress=None, auto_update=True):
        gate.wait(5)
        folder = tmp_path / f"sb-ytdl-{url[-3:]}"
        folder.mkdir()
        t = np.arange(SR) / SR
        p = folder / "vid.wav"   # a different tone per video, or the second is a duplicate
        sf.write(p, np.stack([np.sin(2 * np.pi * len(url) * 20 * t)] * 2, 1) * 0.5, SR)
        return p, url[-3:]
    monkeypatch.setattr(ytdl, "download_audio", slow)
    R = namedtuple("R", "url title seconds")
    window._from_youtube(R("https://youtu.be/one", "One", 1.0), play=False)
    window._from_youtube(R("https://youtu.be/second", "Two", 1.0), play=False)
    assert "is next" in window.linkbar.info.text()
    gate.set()
    assert process_events(qapp, lambda: len(window.cfg.sounds) == 4, 10)
    assert [m.name for m in window.cfg.sounds[-2:]] == ["one", "ond"]


_real_stats = ytdl.stats   # conftest swaps it for an offline stand-in in every test


def test_result_counts_come_from_the_search_or_one_look_up_per_video(monkeypatch):
    from soundboard.ui.ytsearch import fmt_count, stats_text
    yt = ytdl._youtube_hit({"id": "HEXWRTEbj1I", "title": "What Is Love",
                            "view_count": 497635348})
    assert (yt.views, yt.likes, yt.comments) == (497635348, None, None)
    assert ytdl.needs_stats(yt)
    sc = ytdl._soundcloud_hit({"id": "1", "title": "t", "webpage_url":
                               "https://soundcloud.com/a/b", "view_count": 373794,
                               "like_count": 6152, "comment_count": 28})
    assert (sc.views, sc.likes, sc.comments) == (373794, 6152, 28)
    assert not ytdl.needs_stats(sc)
    assert [fmt_count(n) for n in (999, 1234, 12_345, 4_553_746, 2_000_000_000)] == [
        "999", "1.2K", "12K", "4.6M", "2B"]
    assert stats_text(yt, waiting=True)[0] == "498M views · … likes · … comments"
    assert stats_text(sc) == ("374K views · 6.2K likes · 28 comments",
                              "373,794 views, 6,152 likes, 28 comments")
    seen = {}

    class YoutubeDL:
        def __init__(self, opts):
            seen["opts"] = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=True, process=True):
            seen.update(url=url, download=download, process=process)
            return {"view_count": 5, "like_count": 4, "comment_count": None}
    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=YoutubeDL))
    monkeypatch.setattr(ytdl, "install", lambda *a, **k: None)
    assert _real_stats(yt) == (5, 4, None)
    assert seen["url"] == yt.url and not seen["download"] and not seen["process"]
    assert "format" not in seen["opts"]


def test_a_download_locks_the_other_cards_and_shows_its_progress(qapp, monkeypatch):
    from soundboard.ui import busy
    from soundboard.ui.ytsearch import SearchResults
    hits = [ytdl.Result(f"vid{i}xxxxxx", f"Song {i}", "c", 60, "myinstants",
                        f"https://example.com/{i}.mp3") for i in range(3)]
    panel = SearchResults()
    panel.query = "song"
    panel._on_done(0, hits, "")
    a, b, c = panel._rows
    panel.mark(hits[0].url, "add")                   # Add on the first card
    assert a.bar.maximum() == 1000 and a.bar.value() == 0
    assert "0%" in a.btn_add.text()
    assert busy.is_busy(a.btn_add) and not busy.is_busy(a.btn_play)   # Play after it: fine
    assert all(busy.is_busy(x) for r in (b, c) for x in (r.btn_play, r.btn_add))
    assert not panel._quiet.is_set()                 # like counts wait for downloads
    panel.progress(hits[0].url, 0.42)
    assert a.bar.isVisibleTo(a) and a.bar.value() == 420 and "42%" in a.btn_add.text()
    panel.mark(hits[0].url, "play")                  # ...and Play on it too
    assert a.bar.value() == 420                      # no reset for a shared download
    panel.progress(hits[0].url, -1)                  # conversion is a separate phase
    assert a.bar.maximum() == 1000 and a.bar.value() == 420
    assert "Processing" in a.btn_play.text()
    panel.mark(hits[0].url, "add", True)
    assert a.btn_add.text() == "✓ Added" and a.bar.isVisibleTo(a)   # still playing
    assert busy.is_busy(b.btn_play)
    panel.mark(hits[0].url, "play", True)
    assert not a.bar.isVisibleTo(a) and busy.is_busy(a.btn_add)       # added stays added
    assert not any(busy.is_busy(x) for r in (b, c) for x in (r.btn_play, r.btn_add))
    assert panel._quiet.is_set()


def test_play_after_add_plays_the_added_audio_without_downloading_again(
        qapp, window, monkeypatch, tmp_path):  # noqa: F811
    calls = fake_link_download(monkeypatch, tmp_path)
    monkeypatch.setattr(window.engine, "play", lambda *a, **kw: object())
    had = len(window.cfg.sounds)
    window.linkbar.open("https://www.youtube.com/watch?v=HEXWRTEbj1I", "What Is Love", 60)
    assert window.linkbar.add()
    assert window.linkbar.play_once()                # pressed while Add downloads: waits
    assert process_events(qapp, lambda: window.current == "__link__", 5)
    assert len(calls) == 1 and len(window.cfg.sounds) == had + 1
