"""Downloading and searching with yt-dlp: which pages offer "Add as sound", the yt-dlp
wrapper (with a fake yt_dlp, no network), the link bar and the web search."""
import hashlib
import io
import json
import sys
import tempfile
import threading
import os
import time
import types
import zipfile
from pathlib import Path
from collections import namedtuple

import numpy as np
import pytest
import soundfile as sf

from conftest import process_events
from soundboard.online import net, ytdl
from soundboard.audio.engine import SR
from soundboard.sounds.library import Config
from PySide6.QtWidgets import QLabel, QPushButton


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


def test_clean_title_reads_html_entities_and_drops_the_myinstants_suffix():
    """Seen on real links: TikTok's titles come with "&amp;", and a pasted Myinstants
    page is titled "<name> - Sound Button"."""
    assert ytdl.clean_title("Scramble up ur name &amp; I&#39;ll guess it") == \
        "Scramble up ur name & I'll guess it"
    assert ytdl.clean_title("VINE BOOM SOUND - Sound Button") == "VINE BOOM SOUND"
    assert ytdl.clean_title("Sound Button") == "Sound Button"


def test_ytdlp_can_impersonate_a_browser():
    """TikTok answers only a real browser: without curl_cffi (or with a version this
    yt-dlp refuses) every pasted TikTok link fails with "Unexpected response"."""
    from yt_dlp import YoutubeDL
    with YoutubeDL({"quiet": True}) as ydl:
        assert ydl._get_available_impersonate_targets()


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


def test_a_dead_proxy_is_named_not_the_internet(monkeypatch, tmp_path):
    """Through a proxy that didn't answer, the download said "Check your internet
    connection" (seen with a real dead proxy); radio already named the proxy."""
    fake_yt_dlp(monkeypatch, {}, fail="ERROR: Unable to download webpage: connection refused")
    monkeypatch.setattr(ytdl.net, "mode", lambda: ytdl.net.PROXY)
    monkeypatch.setattr(ytdl.net, "last_failure",
                        lambda since=0.0: "Couldn't reach the proxy at 127.0.0.1:1.")
    with pytest.raises(ytdl.DownloadError) as e:
        ytdl.download_audio("https://youtu.be/x", tmp_path, auto_update=False)
    assert "proxy at 127.0.0.1:1" in str(e.value)
    monkeypatch.setattr(ytdl.net, "mode", lambda: ytdl.net.DIRECT)   # direct: as before
    with pytest.raises(ytdl.DownloadError) as e:
        ytdl.download_audio("https://youtu.be/x", tmp_path, auto_update=False)
    assert "internet connection" in str(e.value)


def test_a_playlist_with_a_private_video_first_is_still_a_playlist(monkeypatch, tmp_path):
    """Its entries were resolved before _check: the first one's "Private video" was
    shown for a playlist link."""
    seen = fake_yt_dlp(monkeypatch, {"_type": "playlist", "title": "x"})
    real = ytdl.sys.modules["yt_dlp"].YoutubeDL.extract_info

    def extract_info(self, url, download=True):
        if seen.get("extract_flat") != "in_playlist":
            raise Exception("ERROR: [youtube] abc: Private video")
        return real(self, url, download)
    monkeypatch.setattr(ytdl.sys.modules["yt_dlp"].YoutubeDL, "extract_info", extract_info)
    with pytest.raises(ytdl.DownloadError, match="playlist"):
        ytdl.download_audio("https://www.youtube.com/playlist?list=PLx", tmp_path,
                            auto_update=False)


@pytest.mark.parametrize("url, to, words", [
    # a share link of a deleted video lands on the home page: the video is gone
    ("https://www.tiktok.com/t/ZTabc/", "https://www.tiktok.com/?_r=1",
     "That video isn't available any more."),
    ("https://vm.tiktok.com/ZMabc/", "https://www.tiktok.com/",
     "That video isn't available any more."),
    # a page yt-dlp really can't read
    ("https://example.com/some/page", "https://example.com/some/page",
     "That page has no sound Onion Board can add."),
])
def test_a_link_that_went_nowhere_says_the_video_is_gone(monkeypatch, tmp_path, url, to,
                                                         words):
    fake_yt_dlp(monkeypatch, {}, fail=f"ERROR: Unsupported URL: {to}")
    with pytest.raises(ytdl.DownloadError) as e:
        ytdl.download_audio(url, tmp_path, auto_update=False)
    assert str(e.value) == words


def test_a_failed_download_leaves_no_temp_folder(monkeypatch, tmp_path):
    fake_yt_dlp(monkeypatch, {}, fail="ERROR: Video unavailable")
    monkeypatch.setattr(ytdl.tempfile, "tempdir", str(tmp_path))
    with pytest.raises(ytdl.DownloadError):
        ytdl.download_audio("https://youtu.be/x", auto_update=False)
    assert not list(tmp_path.glob("sb-ytdl-*"))


# ---------------------------------------------------------------- keeping yt-dlp current

@pytest.fixture
def listed(app_dir, monkeypatch):
    """A fake approved list (ytdl.APPROVED_URL) and PyPI file host: `latest` is listed,
    out for `age` days, with a wheel whose yt_dlp says that version. Nothing touches the
    network; the import hook is removed afterwards."""
    # requires: version -> requires_python, listed instead of `latest` when set;
    # broken: versions whose yt_dlp doesn't import (like one written for a newer Python);
    # ages: version -> days on PyPI, for the ones that differ from `age`
    # pypi: version -> requires_python, what PyPI itself has (for Force update)
    state = {"latest": "2099.1.1", "fetched": [], "corrupt": False, "requires": {},
             "broken": set(), "age": 10, "ages": {}, "pypi": {}}

    def wheel(pkg, version):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            body = ("def broken(:\n" if pkg == "yt_dlp" and version in state["broken"] else
                    f"__version__ = {version!r}\nFAKE = True\n")
            z.writestr(f"{pkg}/__init__.py", body)
            z.writestr(f"{pkg}/sub.py", "X = 1\n")
            z.writestr(f"{pkg}-{version}.dist-info/METADATA", "Name: x\n")
        return buf.getvalue()

    def file(name, version, requires=None):
        data = wheel(name.replace("-", "_"), version)
        filename = f"{name.replace('-', '_')}-{version}-py3-none-any.whl"
        url = f"{ytdl.WHEEL_HOST}packages/ab/cd/{filename}"
        state[url] = data
        digest = "0" * 64 if state["corrupt"] else hashlib.sha256(data).hexdigest()
        return {"name": name, "version": version, "filename": filename, "url": url,
                "sha256": digest, "requires_python": requires or ""}

    def entry(version, requires=None):
        days = state["ages"].get(version, state["age"])
        uploaded = time.strftime("%Y-%m-%dT%H:%M:%S.123456Z",
                                 time.gmtime(time.time() - days * 86400))
        return {"version": version, "uploaded": uploaded,
                "wheels": [file("yt-dlp", version, requires), file("yt-dlp-ejs", "0.9.0")]}

    def get(url, limit):
        state["fetched"].append(url)
        if url == ytdl.APPROVED_URL:
            versions = state["requires"] or {state["latest"]: None}
            return json.dumps({"versions": [entry(v, r) for v, r in versions.items()]}
                              ).encode()
        if url.startswith(ytdl.PYPI):   # PyPI's JSON: <name>/json or <name>/<version>/json
            parts = url.removeprefix(ytdl.PYPI).split("/")
            if parts[0] == "yt-dlp-ejs":
                return json.dumps(pypi_release("yt-dlp-ejs", parts[1])).encode()
            if len(parts) == 3:
                return json.dumps(pypi_release("yt-dlp", parts[1])).encode()
            return json.dumps({"info": {"name": "yt-dlp", "version": "x"}, "releases": {
                v: pypi_release("yt-dlp", v)["urls"] for v in state["pypi"]}}).encode()
        return state[url]

    def pypi_release(name, version):
        f = file(name, version, state["pypi"].get(version))
        return {"info": {"name": name, "version": version,
                         "requires_dist": ['yt-dlp-ejs==0.9.0; extra == "default"']
                         if name == "yt-dlp" else []},
                "urls": [{"packagetype": "bdist_wheel", "filename": f["filename"],
                          "url": f["url"], "digests": {"sha256": f["sha256"]},
                          "requires_python": f["requires_python"]}]}

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


def test_update_installs_a_newer_copy_that_imports_win(listed):
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


def test_update_skips_when_up_to_date(listed):
    listed["latest"] = "2026.08.19"
    assert "up to date" in ytdl.update()
    assert listed["fetched"] == [ytdl.APPROVED_URL]           # no wheel downloaded
    assert not ytdl.due()                                    # but it counts as a check


def test_update_rejects_a_bad_checksum(listed):
    listed["corrupt"] = True
    with pytest.raises(ytdl.DownloadError, match="checksum"):
        ytdl.update()
    assert ytdl.active_version() == ("2026.8.19", False)


def test_a_swap_that_fails_halfway_keeps_the_copy_in_use(listed, monkeypatch):
    ytdl.update()
    listed["latest"] = "2099.2.2"
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


def test_leftovers_of_a_cut_short_update_are_tidied_at_startup(listed):
    ytdl.update()
    ytdl._pkg_dir().rename(ytdl.root() / "old-1")   # stopped between the two renames
    (ytdl.root() / "new-abc" / "yt_dlp").mkdir(parents=True)
    long_ago = time.time() - ytdl.TIDY_AFTER_S - 60   # left by an earlier run
    os.utime(ytdl.root() / "new-abc", (long_ago, long_ago))
    ytdl.install()
    assert ytdl.active_version() == ("2099.1.1", True)
    assert (ytdl._pkg_dir() / "yt_dlp" / "__init__.py").is_file()
    assert not list(ytdl.root().glob("old-*")) and not list(ytdl.root().glob("new-*"))


def test_tidying_leaves_an_update_in_progress_alone(listed):
    """A download helper starting up (ytworker: a new process, so ytdl.install() runs
    _tidy again) while the app is unpacking or swapping in a new yt-dlp: its fresh
    new-* folder, and the copy just moved aside before the new one is in place, are
    the app's, not leftovers."""
    ytdl.update()
    moved = ytdl.root() / f"old-{time.time_ns()}"
    ytdl._pkg_dir().rename(moved)                    # mid-swap: no current copy yet
    (ytdl.root() / "new-abc" / "yt_dlp").mkdir(parents=True)   # mid-unpack
    ytdl._tidy()
    assert moved.is_dir() and (ytdl.root() / "new-abc" / "yt_dlp").is_dir()
    assert not ytdl._pkg_dir().exists()             # the swap's own rename comes next


def test_reset_clears_and_reinstalls(listed):
    ytdl.update()
    junk = ytdl.cache_dir() / "youtube-sigfuncs" / "x.json"
    junk.parent.mkdir(parents=True)
    junk.write_text("{}")
    listed["latest"] = "2099.2.2"
    assert "2099.2.2" in ytdl.reset()
    assert not junk.exists()
    assert ytdl.active_version() == ("2099.2.2", True)


def test_reset_offline_falls_back_to_the_built_in_copy(listed, monkeypatch):
    ytdl.update()

    def offline(url, limit):
        raise OSError("no network")
    monkeypatch.setattr(ytdl, "_get", offline)
    msg = ytdl.reset()
    assert "built-in yt-dlp 2026.8.19" in msg and not ytdl.root().exists()


def test_a_copy_older_than_the_bundled_one_is_dropped(listed):
    listed["latest"] = "2099.1.1"
    ytdl.update()
    ytdl._save_state(version="2020.1.1")   # the app has since shipped a newer yt-dlp
    ytdl.install()
    assert ytdl.active_version() == ("2026.8.19", False)


def test_auto_update_only_when_enabled_and_due(listed):
    ytdl.auto_update(False)
    assert listed["fetched"] == []
    ytdl.auto_update(True)
    assert ytdl.override_version() == "2099.1.1"
    listed["fetched"].clear()
    ytdl.auto_update(True)                     # checked a moment ago
    assert listed["fetched"] == []
    ytdl._save_state(checked=time.time() - ytdl.CHECK_EVERY - 1)
    assert ytdl.due()


def test_a_failed_download_updates_and_retries_once(listed, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(ytdl, "RETRY_PAUSE_S", 0)

    def dl(url, dest, progress, *_feature, again=False):
        calls.append(ytdl.override_version())
        if len(calls) <= 2:   # the first try and its second try by itself
            raise ytdl.FetchError("Sign in to confirm you're not a bot")
        return tmp_path / "a.m4a", "Title"

    monkeypatch.setattr(ytdl, "_download", dl)
    assert ytdl.download_audio("https://youtu.be/x")[1] == "Title"
    assert calls == ["", "", "2099.1.1"]       # then retried with the new copy

    calls.clear()                               # checked just now: no second update
    with pytest.raises(ytdl.FetchError):
        ytdl.download_audio("https://youtu.be/x")
    assert calls == ["2099.1.1", "2099.1.1"]


@pytest.mark.parametrize("raw, again", [
    ("ERROR: [youtube] abc: Sign in to confirm you're not a bot", True),
    ("ERROR: unable to download video data: HTTP Error 403: Forbidden", True),
    ("ERROR: [youtube] abc: Requested format is not available", True),
    ("The read operation timed out", True),
    ("HTTP Error 503: Service Unavailable", True),
    ("ERROR: [youtube] abc: Video unavailable. This video is private", False),
    ("ERROR: [youtube] abc: Sign in to confirm your age", False),
    ("ERROR: [youtube] abc: The uploader has not made this video available in your "
     "country", False),
])
def test_a_youtube_refusal_is_tried_once_more_with_other_players(monkeypatch, tmp_path,
                                                                  raw, again):
    """Users gave up (and uninstalled) after a YouTube download failed: a refusal or a
    dropped connection is tried again by itself, asking YouTube as other players
    (RETRY_CLIENTS), before any error shows. A private or locked video isn't."""
    monkeypatch.setattr(ytdl, "RETRY_PAUSE_S", 0)
    counted = []
    monkeypatch.setattr(ytdl, "_count_used", counted.append)
    seen = []

    class YDL:
        def __init__(self, opts):
            self.opts = opts
            seen.append(opts.get("extractor_args"))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            if len(seen) == 1:
                raise Exception(raw)
            return {"title": "Boom", "duration": 3, "id": "abc", "ext": "m4a"}

        def process_ie_result(self, info, download=True):
            (tmp_path / "abc.m4a").write_bytes(b"audio")
            return info

        def prepare_filename(self, info):
            return str(tmp_path / "abc.m4a")

    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=YDL))
    if again:
        assert ytdl.download_audio("https://youtu.be/abc", tmp_path, auto_update=False)[1] \
            == "Boom"
        assert seen == [None, {"youtube": {"player_client": list(ytdl.RETRY_CLIENTS)}}]
        assert counted == ["dl-retried-ok"]
    else:
        with pytest.raises(ytdl.FetchError):
            ytdl.download_audio("https://youtu.be/abc", tmp_path, auto_update=False)
        assert seen == [None] and counted == []


def test_no_second_try_over_tor(monkeypatch, tmp_path):
    """Tor has its own tries with new identities (_over_tor): none on top."""
    monkeypatch.setattr(ytdl, "RETRY_PAUSE_S", 0)
    monkeypatch.setattr(ytdl.net, "mode", lambda: ytdl.net.TOR)
    assert not ytdl._worth_another_try(ytdl.FetchError("HTTP Error 403: Forbidden"))
    monkeypatch.setattr(ytdl.net, "mode", lambda: ytdl.net.DIRECT)
    assert ytdl._worth_another_try(ytdl.FetchError("HTTP Error 403: Forbidden"))


@pytest.mark.parametrize("spec, ok", [
    (None, True), ("", True), (">=3.10", True), (">=3.12", True), (">=3.13", False),
    (">=3.10,<4", True), ("<3.12", False), ("!=3.12.*", False), ("==3.12.*", True),
    ("~=3.11", True), ("~=3.12.5", False), (">=3.9, !=3.11.*", True), ("junk", False)])
def test_requires_python_is_read_for_this_python(spec, ok):
    assert ytdl._py_ok(spec, (3, 12, 4)) is ok


def test_update_skips_a_release_that_needs_a_newer_python(listed):
    """yt-dlp drops old Pythons now and then: the app (frozen on its Python) keeps
    getting the newest release that still runs on it, never one that can't import."""
    listed["requires"] = {"2099.1.1": ">=3.99", "2098.5.5": ">=3.10", "2097.1.1": ">=3.10",
                        "2099.2.2.123.dev0": ">=3.10"}   # a nightly: never taken
    assert ytdl.update() == "Updated yt-dlp to 2098.5.5."
    assert ytdl.active_version() == ("2098.5.5", True)

    listed["requires"] = {"2099.1.1": ">=3.99"}            # nothing runs here
    assert "up to date" in ytdl.update(force=True)
    assert ytdl.active_version() == ("2098.5.5", True)  # the copy in use stays


def test_update_only_asks_the_list_and_takes_its_wheels_from_pypi(listed):
    ytdl.update()
    assert listed["fetched"][0] == ytdl.APPROVED_URL
    assert ytdl.APPROVED_URL.startswith("https://raw.githubusercontent.com/")
    assert ytdl.APPROVED_URL.endswith("/main/pins/yt-dlp.json")
    assert [u.rsplit("/", 1)[1] for u in listed["fetched"][1:]] == [
        "yt_dlp-2099.1.1-py3-none-any.whl", "yt_dlp_ejs-0.9.0-py3-none-any.whl"]
    assert all(u.startswith(ytdl.WHEEL_HOST) for u in listed["fetched"][1:])


def test_an_approved_version_waits_until_its_3_days_old(listed):
    """A hacked release is usually caught and pulled within days: a version that went
    up on PyPI less than 3 days ago isn't installed yet, an older approved one is."""
    listed["requires"] = {"2099.2.2": None, "2099.1.1": None}
    listed["ages"] = {"2099.2.2": 2.5}
    assert ytdl.update() == "Updated yt-dlp to 2099.1.1."
    listed["ages"] = {"2099.2.2": 3.1}
    assert ytdl.update() == "Updated yt-dlp to 2099.2.2."

    listed["requires"] = {}
    listed["latest"], listed["age"] = "2099.3.3", 0.5    # the only one listed is too new
    listed["fetched"].clear()
    assert "up to date" in ytdl.update(force=True)
    assert listed["fetched"] == [ytdl.APPROVED_URL]       # nothing downloaded
    assert ytdl.active_version() == ("2099.2.2", True)


def test_update_never_installs_one_older_than_the_built_in_copy(listed):
    """The list can lag behind an app release that ships a newer yt-dlp."""
    listed["latest"] = "2026.1.1"
    assert ytdl.update(force=True) == "yt-dlp 2026.8.19 is up to date."
    assert "up to date" in ytdl.reset()
    assert ytdl.active_version() == ("2026.8.19", False)
    assert not any(u.endswith(".whl") for u in listed["fetched"])


@pytest.mark.parametrize("change", [
    lambda e: e["wheels"][0].update(url="https://evil.example/" + e["wheels"][0]["filename"]),
    lambda e: e["wheels"][1].update(url=ytdl.WHEEL_HOST + "x/other-1.0-py3-none-any.whl"),
    lambda e: e["wheels"][0].update(sha256="nope"),
    lambda e: e["wheels"][0].update(filename="yt_dlp-2099.1.1.tar.gz"),
    lambda e: e.update(version="2099.1.1.dev0"),
    lambda e: e.update(uploaded="yesterday"),
    lambda e: e.update(wheels=[]),
    lambda e: e.pop("wheels"),
])
def test_a_listed_version_that_isnt_a_checked_pypi_wheel_is_never_taken(listed, monkeypatch,
                                                                        change):
    get = ytdl._get

    def edited(url, limit):
        data = get(url, limit)
        if url == ytdl.APPROVED_URL:
            raw = json.loads(data)
            change(raw["versions"][0])
            data = json.dumps(raw).encode()
        return data
    monkeypatch.setattr(ytdl, "_get", edited)
    assert "up to date" in ytdl.update()
    assert ytdl.active_version() == ("2026.8.19", False)
    assert listed["fetched"] == [ytdl.APPROVED_URL]


def test_a_wheel_that_doesnt_match_the_lists_hash_is_refused(listed, monkeypatch):
    """The hash comes from the approved list, not PyPI: different bytes at the listed
    address (PyPI or the connection tampered with) are never unpacked."""
    url = f"{ytdl.WHEEL_HOST}packages/ab/cd/yt_dlp_ejs-0.9.0-py3-none-any.whl"
    real = ytdl._get

    def swapped(u, limit):
        data = real(u, limit)
        return b"PK" + data[2:-1] if u == url else data
    monkeypatch.setattr(ytdl, "_get", swapped)
    with pytest.raises(ytdl.DownloadError, match="yt_dlp_ejs-0.9.0.*checksum"):
        ytdl.update()
    assert ytdl.active_version() == ("2026.8.19", False)
    assert not ytdl._pkg_dir().exists() and not list(ytdl.root().glob("new-*"))


@pytest.mark.parametrize("off, offline", [(["ytdlp_update"], False), ([], True)])
def test_switched_off_or_offline_nothing_is_asked(listed, off, offline):
    net.configure_features(off, offline=offline)
    try:
        with pytest.raises(ytdl.SwitchedOff):
            ytdl.update()
        with pytest.raises(ytdl.SwitchedOff):
            ytdl.reset()
        ytdl.auto_update(True)                    # the daily check skips itself
    finally:
        net.configure_features()
    assert listed["fetched"] == []
    assert ytdl.active_version() == ("2026.8.19", False)


def test_force_update_takes_pypis_newest_right_away(listed):
    """Downloads broke and nothing approved fixes them yet (the fix is a day old):
    Force update installs PyPI's newest that runs here, without the list or the wait."""
    listed["latest"], listed["age"] = "2099.2.2", 0.5     # approved, too new for Update now
    listed["pypi"] = {"2099.1.1": None, "2099.2.2": None, "2099.3.3.123.dev0": None,
                      "2099.9.9": ">=3.99"}               # a nightly, one for a newer Python
    assert "up to date" in ytdl.update()
    listed["fetched"].clear()
    assert ytdl.force_newest() == "Updated yt-dlp to 2099.2.2."
    assert ytdl.active_version() == ("2099.2.2", True)
    assert (ytdl._pkg_dir() / "yt_dlp_ejs" / "__init__.py").is_file()   # its pinned partner
    assert ytdl.APPROVED_URL not in listed["fetched"]
    assert all(u.startswith((ytdl.PYPI, ytdl.WHEEL_HOST)) for u in listed["fetched"])
    assert "up to date" in ytdl.force_newest()           # already the newest


def test_force_update_never_goes_below_the_copy_in_use(listed):
    listed["pypi"] = {"2026.1.1": None}
    assert ytdl.force_newest() == "yt-dlp 2026.8.19 is up to date."
    assert ytdl.active_version() == ("2026.8.19", False)
    assert not any(u.endswith(".whl") for u in listed["fetched"])


def test_force_update_checks_pypis_hash(listed):
    listed["pypi"] = {"2099.2.2": None}
    listed["corrupt"] = True
    with pytest.raises(ytdl.DownloadError, match="checksum"):
        ytdl.force_newest()
    assert ytdl.active_version() == ("2026.8.19", False)


@pytest.mark.parametrize("answer", [b"<html>down</html>", b"[]", b'{"releases": {}}'])
def test_force_update_says_so_when_pypi_answers_junk(monkeypatch, answer):
    monkeypatch.setattr(ytdl, "_get", lambda url, limit: answer)
    with pytest.raises(ytdl.DownloadError, match="PyPI"):
        ytdl.force_newest()


@pytest.mark.parametrize("off, offline", [(["ytdlp_update"], False), ([], True)])
def test_force_update_switched_off_or_offline_asks_nobody(listed, off, offline):
    listed["pypi"] = {"2099.2.2": None}
    net.configure_features(off, offline=offline)
    try:
        with pytest.raises(ytdl.SwitchedOff):
            ytdl.force_newest()
    finally:
        net.configure_features()
    assert listed["fetched"] == []


def test_a_downloaded_copy_that_doesnt_import_falls_back_and_is_never_fetched_again(listed):
    listed["broken"].add("2099.1.1")
    assert ytdl.update() == "Updated yt-dlp to 2099.1.1."
    with ytdl._ydl() as yt_dlp:               # the built-in one, not an error
        assert not getattr(yt_dlp, "FAKE", False)
    assert ytdl.active_version() == ("2026.8.19", False)
    assert not ytdl._pkg_dir().exists() and not list(ytdl.root().glob("bad-*"))
    assert ytdl._state()["bad"] == ["2099.1.1"]
    listed["requires"] = {"2099.1.1": ">=3.10"}  # still the newest listed: skipped now
    assert "up to date" in ytdl.update()
    assert ytdl.active_version() == ("2026.8.19", False)


def test_link_bar_offers_to_update_the_downloader_and_tries_again(qapp, monkeypatch):
    from soundboard.ui.sounds.linkbar import LinkBar
    calls, version = [], ["2026.8.19"]

    def fake_download(url, progress=None, auto_update=True):
        calls.append(auto_update)
        raise ytdl.FetchError("ERROR: [youtube] abc: Signature extraction failed")
    monkeypatch.setattr(ytdl, "download_audio", fake_download)
    monkeypatch.setattr(ytdl, "active_version", lambda: (version[0], True))

    def update():
        version[0] = "2099.1.1"
        return "Updated yt-dlp to 2099.1.1."
    monkeypatch.setattr(ytdl, "update", update)
    bar = LinkBar(engine=None, cfg=Config(), color_for=lambda: "#fff", known_for=dict)
    bar.set_text("https://www.youtube.com/watch?v=abc")
    bar.add()
    assert process_events(qapp, lambda: not bar._busy and calls)
    assert calls == [False] and bar.btn_update.isVisibleTo(bar)   # auto-update is opt-in
    assert "A newer downloader may fix this." in bar.info.text()
    bar.btn_update.click()                                         # updates, then retries
    assert process_events(qapp, lambda: len(calls) == 2 and not bar._busy)
    assert bar.btn_update.isVisibleTo(bar)                         # failed again: offered again
    bar.btn_update.click()                                         # nothing newer this time
    assert process_events(qapp, lambda: "already the newest" in bar.info.text())
    assert len(calls) == 2 and not bar.btn_update.isVisibleTo(bar)


def test_link_bar_doesnt_offer_an_update_when_its_switched_off_or_a_site_refused(
        qapp, monkeypatch):
    from soundboard.online import net
    from soundboard.ui.sounds.linkbar import LinkBar
    errors = [ytdl.FetchError("ERROR: Sign in to confirm you're not a bot")]
    monkeypatch.setattr(ytdl, "download_audio", lambda url, progress=None, auto_update=True:
                        (_ for _ in ()).throw(errors[0]))
    bar = LinkBar(engine=None, cfg=Config(), color_for=lambda: "#fff", known_for=dict)
    bar.set_text("https://www.youtube.com/watch?v=abc")
    bar.add()
    assert process_events(qapp, lambda: not bar._busy and bar.info.text())
    assert not bar.btn_update.isVisibleTo(bar)     # a bot check: about the address
    errors[0] = ytdl.FetchError("ERROR: Signature extraction failed")
    real = net.allowed
    monkeypatch.setattr(net, "allowed", lambda f: f != ytdl.UPDATE_FEATURE and real(f))
    bar.set_text("https://www.youtube.com/watch?v=xyz")
    bar.add()
    assert process_events(qapp, lambda: not bar._busy and bar.info.text())
    assert not bar.btn_update.isVisibleTo(bar)     # updating is switched off


def test_a_refused_download_does_not_update(listed, monkeypatch):
    def dl(url, dest, progress, *_feature):
        raise ytdl.DownloadError("That's a playlist")
    monkeypatch.setattr(ytdl, "_download", dl)
    with pytest.raises(ytdl.DownloadError):
        ytdl.download_audio("https://youtu.be/x")
    assert listed["fetched"] == []


# ---------------------------------------------------------------- Settings → Updates

from test_mainwindow import window  # noqa: E402,F401  (the real MainWindow fixture)


def test_settings_ytdlp_row(qapp, window, monkeypatch):  # noqa: F811
    """Updates > Helper programs: yt-dlp's Update now says how it went on its row."""
    from soundboard.ui.settings.settings import SettingsDialog
    from soundboard.ui.kit import busy
    monkeypatch.setattr(ytdl, "active_version", lambda: ("2026.8.19", False))
    monkeypatch.setattr(ytdl, "update", lambda: "Updated yt-dlp to 2099.1.1.")
    d = SettingsDialog(window, "updates")
    assert [b.text() for b in d.ytdlp_btns] == ["Update now", "Reinstall", "Force update"]
    assert not d.ytdlp_auto_box.isChecked()               # opt-in
    d.ytdlp_btns[0].click()                               # Update now
    assert busy.is_busy(d.ytdlp_btns[0]) and d.ytdlp_btns[0].isEnabled()
    monkeypatch.setattr(ytdl, "active_version", lambda: ("2099.1.1", True))
    assert process_events(qapp, lambda: not busy.is_busy(d.ytdlp_btns[0]), 5)
    assert process_events(qapp, lambda: d.ytdlp_state.text() == "Working: version 2099.1.1", 5)
    assert d.ytdlp_note.text() == "Updated yt-dlp to 2099.1.1."
    d.close()


def test_force_update_warns_first(qapp, window, monkeypatch):  # noqa: F811
    """Force update installs nothing until the warning's Install anyway; Cancel does
    nothing at all."""
    from soundboard.ui.settings.settings import SettingsDialog
    from soundboard.ui.kit import busy
    calls = []
    monkeypatch.setattr(ytdl, "active_version", lambda: ("2026.8.19", False))
    monkeypatch.setattr(ytdl, "force_newest",
                        lambda: calls.append(1) or "Updated yt-dlp to 2099.2.2.")
    d = SettingsDialog(window, "updates")
    d.ytdlp_force_btn.click()
    box = d.ytdlp_force_box
    assert box.isVisible() and "approved" in box.findChildren(QLabel)[1].text()
    [cancel] = [b for b in box.findChildren(QPushButton) if b.text() == "Cancel"]
    cancel.click()
    qapp.processEvents()
    assert calls == [] and not busy.is_busy(d.ytdlp_force_btn)

    d.ytdlp_force_btn.click()
    [go] = [b for b in d.ytdlp_force_box.findChildren(QPushButton)
            if b.text() == "Install anyway"]
    assert go.objectName() == "danger"
    go.click()
    assert process_events(qapp, lambda: calls and not busy.is_busy(d.ytdlp_force_btn), 5)
    assert process_events(qapp, lambda: d.ytdlp_note.text() == "Updated yt-dlp to 2099.2.2.", 5)
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
    with pytest.raises(ytdl.FetchError, match="^That page has no sound"):
        ytdl.probe("https://example.com")


def no_thumbnail_fetch(monkeypatch, window):  # noqa: F811
    """Search results' thumbnail requests answered by nothing; returns the list of
    (url, feature) asked for."""
    asked = []

    class Nam:
        def __init__(self, feature):
            self.feature = feature

        def get(self, req):
            asked.append((req.url().toString(), self.feature))
            signal = types.SimpleNamespace(connect=lambda f: None)
            return types.SimpleNamespace(finished=signal, downloadProgress=signal,
                                         setReadBufferSize=lambda n: None)
    monkeypatch.setattr(window.ytresults, "_nam", Nam)
    return asked


def fake_link_download(monkeypatch, tmp_path):
    """download_audio writes a 1 s tone into a fresh folder; returns the call log."""
    calls = []

    def download(url, dest=None, progress=None, auto_update=True, **kw):
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
    monkeypatch.setattr(ytdl, "lookup", lambda url, direct=False: ytdl.Result(
        "abc", "A Tone", "Tone Channel", 1.0, source="link", link=url))
    monkeypatch.setattr(ytdl, "lookup_all", ytdl.lookup)   # one video, not a playlist
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    return calls


def test_link_in_search_shows_its_card_and_filters_nothing(qapp, window, monkeypatch,  # noqa: F811
                                                           tmp_path):
    calls = fake_link_download(monkeypatch, tmp_path)
    window.search.setText("Boom")
    assert window.linkbar.isHidden()
    assert window.pads["s1"].property("filtered")
    window.search.setText("https://youtu.be/abc")
    assert window.linkbar.url == "https://youtu.be/abc"
    assert window.linkbar.isHidden()                  # no bar of buttons: the card is it
    assert not any(p.property("filtered") for p in window.pads.values())
    assert process_events(qapp, lambda: window.ytresults._rows, 3)
    rows = window.ytresults._rows
    assert rows[0].result.title == "A Tone" and rows[0].result.url == "https://youtu.be/abc"
    assert window._pads_scroll.isHidden()
    assert calls == []                                # looked up, nothing downloaded
    window.search.clear()
    assert window.ytresults.isHidden() and window.linkbar.url == ""
    assert not window._pads_scroll.isHidden()


def test_link_add_as_sound(qapp, window, monkeypatch, tmp_path):  # noqa: F811
    calls = fake_link_download(monkeypatch, tmp_path)
    window.search.setText("https://youtu.be/abc")
    window.search.returnPressed.emit()                       # Enter: its card, at once
    rows = window.ytresults._rows
    assert process_events(qapp, lambda: rows, 3)
    assert calls == [] and len(window.cfg.sounds) == 2       # nothing downloaded yet
    rows[0].btn_add.click()
    assert process_events(qapp, lambda: len(window.cfg.sounds) == 3, 5)
    assert rows[0].btn_add.text() == "✓ Added"
    m = window.cfg.sounds[-1]
    assert m.name == "A Tone" and m.id in window.pads and m.id in window.audio
    assert calls == ["https://youtu.be/abc"]
    assert not (tmp_path / "sb-ytdl-1").exists()                   # the download is cleaned up
    assert "Added" in window.linkbar.info.text()
    window.linkbar.add()                                     # repeated Add is already done
    assert "Added" in window.linkbar.info.text()
    assert calls == ["https://youtu.be/abc"] and len(window.cfg.sounds) == 3
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
    window.transctl._update_transport({"__link__": (0.5, False)})
    assert window.btn_pp.isEnabled() and window.seek.value() == 500
    paused = []
    monkeypatch.setattr(window.engine, "state", lambda sid: (0.5, False))
    monkeypatch.setattr(window.engine, "set_paused", lambda sid, p: paused.append((sid, p)))
    window.playctl.toggle_play_pause()                               # the ⏸ button pauses it
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
    no_thumbnail_fetch(monkeypatch, window)
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
    window.ytresults.site_actions["soundcloud"].trigger()  # another site: searches again
    assert process_events(qapp, lambda: searched[-1:] == ["soundcloud"], 5)
    assert searched == ["youtube", "youtube", "soundcloud"]
    assert "No SoundCloud results" not in window.ytresults.title.text()
    window.ytresults.close_results()
    assert not window._pads_scroll.isHidden() and window.ytresults.isHidden()


@pytest.mark.parametrize("url, ok", [
    ("https://i.ytimg.com/vi/x/mqdefault.jpg", True),
    ("HTTP://cdn.example.com/a.jpg", True),
    ("file://host/share/x.jpg", False),
    ("file:///C:/Windows/win.ini", False),
    (r"\\host\share\x.jpg", False),   # UNC
    ("//host/share/x.jpg", False),
    ("ftp://host/x.jpg", False),
    ("https://", False),
    ("", False),
])
def test_web_url_lets_only_http_links_through(url, ok):
    from soundboard.online import net
    assert bool(net.web_url(url)) is ok


def test_a_file_share_thumbnail_is_never_fetched(qapp, window, monkeypatch):  # noqa: F811
    """A page's own og:image becomes the result's picture: one that isn't a web link
    is dropped, with no request at all."""
    asked = no_thumbnail_fetch(monkeypatch, window)
    bad = ytdl.Result("x", "Evil", "page", 3, source="generic",
                      link="https://evil.example/page", art="file://host/share/x.jpg")
    good = ytdl.Result("y", "Fine", "page", 3, source="generic",
                       link="https://ok.example/page", art="https://ok.example/pic.jpg")
    assert bad.thumb == ""
    window.ytresults._add_rows([bad, good], window.ytresults._gen)
    assert asked == [("https://ok.example/pic.jpg", "sounds_web.other")]


def test_search_thumbnails_obey_the_switch_of_the_site_they_are_on(qapp, window,  # noqa: F811
                                                                   monkeypatch):
    """A thumbnail goes out under its own server's site switch: with YouTube off (and
    other links on), i.ytimg.com isn't asked, even for a result from another site."""
    from soundboard.online import net
    asked = no_thumbnail_fetch(monkeypatch, window)
    yt = ytdl.Result("HEXWRTEbj1I", "What Is Love", "Haddaway", 241)   # i.ytimg.com
    page = ytdl.Result("y", "Page", "page", 3, source="generic",
                       link="https://ok.example/page", art="https://i.ytimg.com/vi/y/a.jpg")
    other = ytdl.Result("z", "Fine", "page", 3, source="generic",
                        link="https://ok.example/page2", art="https://ok.example/pic.jpg")
    window.ytresults._add_rows([yt, page, other], window.ytresults._gen)
    assert asked == [(yt.thumb, "sounds_web.youtube"), (page.thumb, "sounds_web.youtube"),
                     ("https://ok.example/pic.jpg", "sounds_web.other")]
    asked.clear()
    net.configure_features(off=["sounds_web.youtube"])
    try:
        window.ytresults._add_rows([yt, page, other], window.ytresults._gen)
    finally:
        net.configure_features()
    assert asked == [("https://ok.example/pic.jpg", "sounds_web.other")]


@pytest.mark.parametrize("url, site", [
    ("https://i.ytimg.com/vi/x/mqdefault.jpg", "youtube"),
    ("https://yt3.ggpht.com/a.jpg", "youtube"),
    ("https://i1.sndcdn.com/artworks-x.jpg", "soundcloud"),
    ("https://notytimg.com/a.jpg", "other"),
])
def test_a_sites_picture_servers_are_that_site(url, site):
    assert ytdl.site_of(url) == site


def test_web_results_hide_the_empty_category_bar(qapp, window,  # noqa: F811
                                                 monkeypatch):
    """The category bar's empty row stayed in the layout while web results showed,
    which left a gap between the toolbar and the results' buttons. It now goes with
    the results and comes back when they close."""
    monkeypatch.setattr(ytdl, "search", lambda q, count=20, source="youtube": [])
    m = window.ytresults.layout().contentsMargins()
    assert m.top() == m.left()   # Back as far in from the card's top as its side
    window.search.setText("cat")
    window.search.returnPressed.emit()
    assert process_events(qapp, lambda: not window.ytresults.isHidden(), 5)
    assert window.cat_bar.isHidden()
    window.ytresults.close_results()
    assert process_events(qapp, lambda: window.ytresults.isHidden(), 5)
    assert not window.cat_bar.isHidden()


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
    from soundboard.sounds import sourceinfo  # the pad menu's Open on Myinstants
    assert sourceinfo.read_from(tmp_path)["link"] == r[0].url


def test_results_spin_while_searching_and_offer_every_site(qapp, monkeypatch):
    from soundboard.ui.sounds.ytsearch import SearchResults
    gate = threading.Event()
    monkeypatch.setattr(ytdl, "search", lambda q, count=20, source="youtube": (
        gate.wait(5), [])[1])
    panel = SearchResults()
    assert set(panel.site_actions) == set(ytdl.SOURCES) >= {"tiktok", "myinstants", "ytmusic"}
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
    # its search thread still reports back: let it, before the panel is freed (else it
    # emits on a deleted widget, a segfault in whichever test runs next)
    assert process_events(qapp, lambda: not any(
        t.name == "web-search" for t in threading.enumerate()), 5)


def test_searching_shows_a_centred_mascot_then_the_results(qapp, monkeypatch):
    from soundboard.ui.bun.bunnywidget import BunnyWidget
    from soundboard.style.owl import OwlWidget
    from soundboard.ui.sounds.ytsearch import SearchResults
    gate = threading.Event()
    hit = ytdl.Result(id="x", title="Bruh", channel="c", seconds=3.0, source="myinstants")
    monkeypatch.setattr(ytdl, "search", lambda q, count=20, source="youtube": (
        gate.wait(5), [hit])[1])
    panel = SearchResults()
    panel.resize(700, 500)
    panel.search("bruh")
    qapp.processEvents()
    view = panel.loading
    assert view.isVisible() and not panel.scroll_area.isVisible()
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
    assert panel.scroll_area.isVisible() and len(panel._rows) == 1
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


def test_a_direct_download_that_isnt_an_mp3_is_not_kept(monkeypatch, tmp_path):
    """A page, or anything else, sent under a sound's .mp3 name is refused and removed."""
    monkeypatch.setattr(ytdl.net, "urlopen",
                        lambda *a, **k: _Resp(b"<!doctype html><title>x</title>" + b" " * 200))
    monkeypatch.setattr(ytdl.tempfile, "tempdir", str(tmp_path))
    with pytest.raises(ytdl.DownloadError):
        ytdl._download_direct("https://www.myinstants.com/media/sounds/vine-boom.mp3", None, None)
    assert not list(tmp_path.glob("sb-ytdl-*"))


def test_a_direct_download_cut_short_is_refused_and_cleared(monkeypatch, tmp_path):
    """The connection dropped part way: http's read() just ends (no error), so the
    bytes got are checked against Content-Length and a short file isn't kept."""
    class Short(_Resp):
        headers = {"Content-Length": "1000"}
    monkeypatch.setattr(ytdl.net, "urlopen", lambda *a, **k: Short(b"ID3" + b"\0" * 97))
    monkeypatch.setattr(ytdl.tempfile, "tempdir", str(tmp_path))
    url = "https://www.myinstants.com/media/sounds/vine-boom.mp3"
    with pytest.raises(ytdl.DownloadError):
        ytdl._download_direct(url, None, None)
    assert not list(tmp_path.glob("sb-ytdl-*"))   # its own folder: removed
    dest = tmp_path / "dest"
    dest.mkdir()
    with pytest.raises(ytdl.DownloadError):
        ytdl._download_direct(url, dest, None)
    assert not list(dest.iterdir())               # the caller's folder: the file removed


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


@pytest.mark.parametrize("answer", [b"<html>down for maintenance</html>", b'{"x": 1}', b"[]",
                                    b'{"versions": {"2099.1.1": 1}}'])
def test_update_says_so_when_the_list_is_junk(monkeypatch, answer):
    monkeypatch.setattr(ytdl, "_get", lambda url, limit: answer)
    with pytest.raises(ytdl.DownloadError, match="list of approved yt-dlp versions"):
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
    window.searchctl._from_youtube(R("https://youtu.be/one", "One", 1.0), play=False)
    window.searchctl._from_youtube(R("https://youtu.be/second", "Two", 1.0), play=False)
    assert "is next" in window.linkbar.info.text()
    gate.set()
    assert process_events(qapp, lambda: len(window.cfg.sounds) == 4, 10)
    assert [m.name for m in window.cfg.sounds[-2:]] == ["one", "ond"]


def test_result_counts_are_only_what_the_search_gave():
    from soundboard.ui.sounds.ytsearch import fmt_count, stats_text
    yt = ytdl._youtube_hit({"id": "HEXWRTEbj1I", "title": "What Is Love",
                            "view_count": 497635348})
    assert (yt.views, yt.likes, yt.comments) == (497635348, None, None)
    sc = ytdl._soundcloud_hit({"id": "1", "title": "t", "webpage_url":
                               "https://soundcloud.com/a/b", "view_count": 373794,
                               "like_count": 6152, "comment_count": 28})
    assert (sc.views, sc.likes, sc.comments) == (373794, 6152, 28)
    assert [fmt_count(n) for n in (999, 1234, 12_345, 4_553_746, 2_000_000_000)] == [
        "999", "1.2K", "12K", "4.6M", "2B"]
    # no video page is fetched for the rest: what the search didn't say isn't shown
    assert stats_text(yt) == ("498M views", "497,635,348 views")
    assert stats_text(sc) == ("374K views · 6.2K likes · 28 comments",
                              "373,794 views, 6,152 likes, 28 comments")
    assert not hasattr(ytdl, "stats")


def test_a_download_shows_its_progress_and_leaves_the_other_cards_free(qapp, monkeypatch):
    from soundboard.ui.kit import busy
    from soundboard.i18n import _
    from soundboard.ui.sounds.ytsearch import SearchResults
    hits = [ytdl.Result(f"vid{i}xxxxxx", f"Song {i}", "c", 60, "myinstants",
                        f"https://example.com/{i}.mp3") for i in range(3)]
    panel = SearchResults()
    panel.query = "song"
    panel._on_done(0, hits, "")
    a, b, c = panel._rows
    panel.mark(hits[0].url, "add")                   # Add on the first card
    assert a.fill == 0.0
    assert a.btn_add.text() == _("Parsing…")      # no "0%" until bytes arrive
    assert busy.is_busy(a.btn_add) and not busy.is_busy(a.btn_play)   # Play after it: fine
    # the others stay clickable: a Play replaces a loading Play, an Add waits its turn
    assert not any(busy.is_busy(x) for r in (b, c) for x in (r.btn_play, r.btn_add))
    panel.queued(hits[1].url, "add")
    assert b.btn_add.text() == _("Queued") and busy.is_busy(b.btn_add)
    from soundboard.core import jobprogress
    panel.progress(hits[0].url, 0.42)   # the download's stretch of the one bar
    got = jobprogress.LOOKED_UP + (jobprogress.FETCHED - jobprogress.LOOKED_UP) * 0.42
    assert a.fill == pytest.approx(got) and f"{got * 100:.0f}%" in a.btn_add.text()
    panel.mark(hits[0].url, "play")                  # ...and Play on it too
    assert a.fill == pytest.approx(got)       # no reset for a shared download
    panel.progress(hits[0].url, -1)   # converting: the bar goes on, it doesn't fill up
    assert a.fill == jobprogress.FETCHED
    assert a.thumb.progress_frac == jobprogress.FETCHED
    assert "Processing" in a.btn_play.text()
    panel.mark(hits[0].url, "add", True)
    assert a.btn_add.text() == "✓ Added" and a.fill >= 0   # still playing
    panel.mark(hits[0].url, "play", True)
    assert a.fill < 0 and busy.is_busy(a.btn_add)       # added stays added
    panel.mark(hits[1].url, "add", False)            # its wait was cancelled
    assert not any(busy.is_busy(x) for r in (b, c) for x in (r.btn_play, r.btn_add))


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


def test_download_progress_is_reported_at_most_ten_times_a_second():
    seen = []
    hook = ytdl._opts(progress=seen.append)["progress_hooks"][0]
    for k in range(1, 1001):            # a fast download: a thousand blocks at once
        hook({"status": "downloading", "downloaded_bytes": k, "total_bytes": 1000})
    assert seen[0] == 0.001 and seen[-1] == 1.0 and len(seen) <= 3


def test_a_pasted_link_shows_only_its_own_card(qapp, window, monkeypatch, tmp_path):  # noqa: F811
    from soundboard.ui.sounds.ytsearch import ResultRow
    fake_link_download(monkeypatch, tmp_path)
    hits = [ytdl.Result(f"id{i}", f"Hit {i}", "Chan", 3) for i in range(3)]
    monkeypatch.setattr(ytdl, "search", lambda q, **kw: hits)
    window.search.setText("vine boom")
    window.searchctl.search_youtube()
    assert process_events(qapp, lambda: len(window.ytresults._rows) == 3, 3)
    window.search.setText("https://youtu.be/abc")
    window.search.returnPressed.emit()
    assert process_events(qapp, lambda: len(window.ytresults._rows) == 1, 3)
    shown = window.ytresults.list.findChildren(ResultRow)
    assert [w.result.title for w in shown if not w.isHidden()] == ["A Tone"]
    assert shown and all(w.wide for w in shown if not w.isHidden())   # its own big card


def test_show_more_adds_the_next_page_under_the_cards_up_to_the_cap(qapp, monkeypatch):
    from soundboard.ui.sounds import ytsearch
    from soundboard.ui.sounds.ytsearch import PAGE, SearchResults

    asked = []

    def fake(q, count=PAGE, source="youtube", start=1, **kw):
        asked.append((start, count))
        return [ytdl.Result(f"v{i:06d}xxxxx", f"Song {i}", "c", 60)
                for i in range(start - 1, min(count, 45))]   # the site has 45 hits

    class Now:   # the worker, run on the spot
        def __init__(self, target, args=(), kwargs=None, **kw):
            self.run = lambda: target(*args, **(kwargs or {}))

        def start(self):
            self.run()

    monkeypatch.setattr(ytdl, "search", fake)
    panel = SearchResults()   # before Now: its network relay's thread must really run
    monkeypatch.setattr(ytsearch.threading, "Thread", Now)
    panel.search("song")
    assert process_events(qapp, lambda: len(panel._rows) == PAGE, 5)
    assert not panel.more_btn.isHidden()
    panel.more_btn.click()
    assert process_events(qapp, lambda: len(panel._rows) == 2 * PAGE, 5)
    assert asked[-1] == (PAGE + 1, 2 * PAGE)   # only the new page is asked for
    panel.more_btn.click()                      # 5 left: shown, and still offered
    assert process_events(qapp, lambda: len(panel._rows) == 45, 5)
    panel.more_btn.click()                      # nothing new: the button goes
    assert process_events(qapp, lambda: panel.more_btn.isHidden(), 5)
    assert len({r.result.url for r in panel._rows}) == 45
    monkeypatch.setattr(ytsearch, "MAX_RESULTS", PAGE)
    panel.search("again")                       # at the cap: no Show more
    assert process_events(qapp, lambda: len(panel._rows) == PAGE, 5)
    panel.more_btn.click()
    assert process_events(qapp, lambda: panel.more_btn.isHidden(), 5)


def test_open_results_follow_a_theme_switch(qapp):
    from soundboard.ui.kit import theme
    from soundboard.ui.sounds.ytsearch import SearchResults
    panel = SearchResults()
    panel.query = "x"
    panel._on_done(0, [ytdl.Result("vid0xxxxxxx", "Song", "c", 60)], "")
    row = panel._rows[0]
    try:
        theme.apply(qapp, "Dark")
        panel.retheme()
        dark = row.btn_play.styleSheet()
        theme.apply(qapp, "Light")
        panel.retheme()
        assert row.btn_play.styleSheet() != dark   # no Dark-only colours left on Light
    finally:
        theme.apply(qapp, "Dark")


def test_spammed_enter_waits_for_the_search_already_running(qapp, window,  # noqa: F811
                                                             monkeypatch):
    import threading
    go, calls = threading.Event(), []

    def search(q, count=20, source="youtube"):
        calls.append(q)
        go.wait(5)
        return [ytdl.Result("HEXWRTEbj1I", "What Is Love", "Haddaway", 241)]
    monkeypatch.setattr(ytdl, "search", search)
    no_thumbnail_fetch(monkeypatch, window)
    window.search.setText("what is love")
    for _i in range(20):
        window.search.returnPressed.emit()                   # held: one search only
    process_events(qapp, lambda: False, timeout=0.2)
    assert calls == ["what is love"] and window.ytresults.loading.running()
    go.set()
    assert process_events(qapp, lambda: window.ytresults._rows, 5)
    assert len(window.ytresults._rows) == 1                  # one set of cards
    window.search.returnPressed.emit()                       # done: Enter searches again
    assert process_events(qapp, lambda: len(calls) == 2, 5)
    window.search.setText("rick astley")                     # new words: searched at once
    window.search.returnPressed.emit()
    assert process_events(qapp, lambda: calls[-1] == "rick astley", 5)


def test_a_dead_proxy_behind_the_relay_is_named_not_the_site(monkeypatch, tmp_path):
    """yt-dlp goes through the app's relay, which answers 502 when the proxy didn't:
    a dead proxy said "The site is having trouble right now"."""
    fake_yt_dlp(monkeypatch, {}, fail="ERROR: [generic] x: Unable to download webpage: "
                                      "HTTP Error 502: Bad Gateway")
    monkeypatch.setattr(ytdl.net, "mode", lambda: ytdl.net.PROXY)
    monkeypatch.setattr(ytdl.net, "proxy", lambda: ytdl.net.parse("socks5h://127.0.0.1:9"))
    monkeypatch.setattr(ytdl.net, "last_failure",
                        lambda since=0.0: "Couldn't reach the proxy at 127.0.0.1:9.")
    with pytest.raises(ytdl.DownloadError) as e:
        ytdl.download_audio("https://example.com/a.mp3", tmp_path, auto_update=False)
    assert "proxy at 127.0.0.1:9" in str(e.value)
    assert "Settings > Connection" in str(e.value)       # and where to change it
    assert ytdl.errors.describe(e.value).text == str(e.value)   # what the panels show
    assert e.value.proxy
    monkeypatch.setattr(ytdl.net, "mode", lambda: ytdl.net.DIRECT)   # direct: the site's
    with pytest.raises(ytdl.DownloadError) as e:
        ytdl.download_audio("https://example.com/a.mp3", tmp_path, auto_update=False)
    assert "having trouble" in str(e.value)


def test_a_download_cut_off_is_said_in_plain_words():
    p = ytdl.errors.describe(Exception("ERROR: Got error: Downloaded 32336 bytes, expected "
                                       "97009 bytes"), downloader=True)
    assert p.text == "The download was cut off before the end. Try again."
    assert not p.reportable


def test_several_links_pasted_together_are_a_list():
    from soundboard.online import ytdl
    two = "https://youtu.be/a\nhttps://soundcloud.com/x/y"
    assert ytdl.as_links(two) == ["https://youtu.be/a", "https://soundcloud.com/x/y"]
    assert ytdl.as_links("https://youtu.be/a, www.tiktok.com/@b/video/1  https://youtu.be/a") \
        == ["https://youtu.be/a", "https://www.tiktok.com/@b/video/1"]
    assert ytdl.as_links("https://youtu.be/a") == []              # one link: as_link's
    assert ytdl.as_links("https://youtu.be/a funny sound") == []  # words: a search
    many = " ".join(f"https://youtu.be/{i}" for i in range(40))
    assert len(ytdl.as_links(many)) == ytdl.MAX_LINKS


def test_a_pasted_playlist_lists_its_videos_instead_of_failing(monkeypatch):
    """A playlist link is no error: its first MAX_LINKS videos come back as hits, read
    from YouTube's list (no look-up per video), private or repeated ones left out."""
    asked = []
    entries = [{"ie_key": "Youtube", "id": f"vid{i:08d}", "title": f"Song {i}",
                "channel": "Band", "duration": 60 + i} for i in range(ytdl.MAX_LINKS)]
    entries[3] = None                                  # a private video
    entries[4] = dict(entries[5])                      # the same one twice
    entries[6] = dict(entries[6], title="[Deleted video]", duration=None)

    def extract(target, opts, keep=False):
        asked.append(opts)
        return {"_type": "playlist", "title": "Road trip [Official Audio]",
                "playlist_count": 120, "entries": entries}
    monkeypatch.setattr(ytdl, "_extract", extract)
    monkeypatch.setattr(ytdl.net, "mode", lambda: ytdl.net.DIRECT)
    pl = ytdl.lookup_all("https://www.youtube.com/playlist?list=PLabc", direct=True)
    assert isinstance(pl, ytdl.Playlist)
    assert pl.title == "Road trip" and pl.total == 120
    assert len(pl) == ytdl.MAX_LINKS - 3
    assert pl[0].url == "https://www.youtube.com/watch?v=vid00000000" and pl[0].seconds == 60
    assert asked[0]["extract_flat"] == "in_playlist"
    assert asked[0]["playlistend"] == ytdl.MAX_LINKS and asked[0]["ignoreerrors"]


def test_a_soundcloud_set_is_looked_up_track_by_track(monkeypatch):
    """SoundCloud's quick list has no track names: each track is looked up instead."""
    asked = []

    def extract(target, opts, keep=False):
        asked.append(opts)
        return {"_type": "playlist", "title": "Set", "entries": [
            {"extractor_key": "Soundcloud", "id": "1", "title": "City ports",
             "webpage_url": "https://soundcloud.com/a/city-ports", "duration": 142.2}]}
    monkeypatch.setattr(ytdl, "_extract", extract)
    pl = ytdl.lookup_all("https://soundcloud.com/a/sets/set", direct=True)
    assert "extract_flat" not in asked[0]
    assert [(r.title, r.url) for r in pl] == [("City ports",
                                               "https://soundcloud.com/a/city-ports")]
    assert pl.total == 0   # not said: the heading counts the cards


def test_a_video_link_still_looks_up_one_video(monkeypatch):
    monkeypatch.setattr(ytdl, "_extract", lambda target, opts, keep=False: {
        "id": "abc", "title": "One song (Official Video)", "duration": 9})
    r = ytdl.lookup_all("https://www.youtube.com/watch?v=abc&list=PLx", direct=True)
    assert not isinstance(r, ytdl.Playlist) and r.title == "One song" and r.seconds == 9


def test_an_empty_playlist_or_a_failed_one_says_why(monkeypatch):
    monkeypatch.setattr(ytdl, "_extract", lambda target, opts, keep=False: {
        "_type": "playlist", "title": "Gone", "entries": [None, None]})
    with pytest.raises(ytdl.DownloadError, match="empty"):
        ytdl.lookup_all("https://www.youtube.com/playlist?list=PLx", direct=True)

    def extract(target, opts, keep=False):
        if opts.get("ignoreerrors"):
            return None   # yt-dlp hid the error
        raise ytdl.FetchError("That video isn't available any more.")
    monkeypatch.setattr(ytdl, "_extract", extract)
    with pytest.raises(ytdl.FetchError, match="available"):
        ytdl.lookup_all("https://www.youtube.com/playlist?list=PLx", direct=True)
