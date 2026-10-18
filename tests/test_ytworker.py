"""soundboard.online.ytworker: yt-dlp in a helper process, off the audio callbacks' GIL."""
import sys
import threading
import time
from contextlib import nullcontext

import pytest

from soundboard.online import ytdl, ytworker


@pytest.fixture
def helper(monkeypatch):
    monkeypatch.setattr(ytworker, "enabled", True)
    yield
    ytworker.drop_all()


@pytest.mark.windows   # the helper process imports the app
def test_a_helper_answers_and_is_kept_for_the_next_call(helper):
    pid, _version = ytworker.run("ping")
    assert pid and ytworker.run("ping")[0] == pid          # the same warm one
    with pytest.raises(ytworker.RemoteError) as e:
        ytworker.run("no-such-op")
    assert e.value.kind == "builtins.KeyError"
    assert ytworker.run("ping")[0] == pid                   # an error doesn't lose it
    ytworker.drop_all()                                     # yt-dlp updated: a new one
    assert ytworker.run("ping")[0] != pid


def _helper_command(monkeypatch, code: str) -> list:
    """The helper runs `code` instead of the app; returns the processes started."""
    started = []

    def popen(*a, **kw):
        started.append(real(*a, **kw))
        return started[-1]
    real = ytworker.subprocess.Popen
    monkeypatch.setattr(ytworker.subprocess, "Popen", popen)
    monkeypatch.setattr(ytworker, "_command", lambda: [sys.executable, "-c", code])
    return started


def _accept_threads():
    return [t for t in threading.enumerate() if t.name == "ytdl-helper-accept"]


def test_a_helper_that_quits_at_start_fails_at_once_and_isnt_retried(helper, monkeypatch):
    ytworker.drop_all()
    started = _helper_command(monkeypatch, "raise SystemExit(3)")
    t0 = time.monotonic()
    with pytest.raises(ytworker.Unavailable, match="code 3"):
        ytworker.run("ping")
    assert time.monotonic() - t0 < 5        # not START_TIMEOUT_S (30 s)
    assert started[0].returncode == 3       # waited for
    assert not _accept_threads()            # no accept() left blocked
    t0 = time.monotonic()
    with pytest.raises(ytworker.Unavailable):
        ytworker.run("ping")                # straight to in-process: no second start
    assert time.monotonic() - t0 < 0.5 and len(started) == 1
    ytworker.drop_all()                     # yt-dlp updated: worth a new try
    with pytest.raises(ytworker.Unavailable):
        ytworker.run("ping")
    assert len(started) == 2


def test_a_helper_that_never_connects_is_killed_and_its_wait_ends(helper, monkeypatch):
    ytworker.drop_all()
    monkeypatch.setattr(ytworker, "START_TIMEOUT_S", 0.5)
    started = _helper_command(monkeypatch, "import time; time.sleep(60)")
    with pytest.raises(ytworker.Unavailable, match="didn't start"):
        ytworker.run("ping")
    assert started[0].returncode is not None
    assert not _accept_threads()


def test_lookups_go_to_the_helper_without_hooks_and_come_back_worded(monkeypatch):
    sent = []

    def run(op, target, opts, **kw):
        sent.append((op, target, opts))
        if target.endswith("bad"):
            raise ytworker.RemoteError("yt_dlp.utils.DownloadError",
                                       "ERROR: Unsupported URL: https://example.com/bad")
        return {"title": "Boom [HD]", "duration": 4, "uploader": "Chan",
                "thumbnail": "https://img/x.jpg", "view_count": 12}
    monkeypatch.setattr(ytworker, "enabled", True)
    monkeypatch.setattr(ytworker, "run", run)
    r = ytdl.lookup("https://youtu.be/x")
    assert (r.title, r.channel, r.seconds, r.thumb, r.views, r.url) == (
        "Boom", "Chan", 4.0, "https://img/x.jpg", 12, "https://youtu.be/x")
    op, _target, opts = sent[0]
    assert op == "lookup" and "progress_hooks" not in opts and "logger" not in opts
    with pytest.raises(ytdl.FetchError, match="^That page has no sound"):
        ytdl.probe("https://example.com/bad")


def test_no_helper_means_it_runs_here(monkeypatch):
    def run(*a, **kw):
        raise ytworker.Unavailable("no helper")
    monkeypatch.setattr(ytworker, "enabled", True)
    monkeypatch.setattr(ytworker, "run", run)
    import test_ytdl
    test_ytdl.fake_yt_dlp(monkeypatch, {"title": "Here", "duration": 2})
    assert ytdl.probe("https://youtu.be/x") == ("Here", 2.0)


class _Conn:
    def __init__(self):
        self.sent = []

    def send(self, msg):
        self.sent.append(msg)


class _FakeYdl:
    """yt-dlp downloading 20 chunks half a second apart, of a size it doesn't know."""

    def __init__(self, opts, clock):
        self.hook, self.clock = opts["progress_hooks"][0], clock

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download):
        return {"title": "t"}

    def process_ie_result(self, info, download):
        for i in range(20):
            self.clock[0] += 0.5
            self.hook({"status": "downloading", "downloaded_bytes": 1000 * i})
        return info

    def prepare_filename(self, info):
        return "t.webm"


def test_a_download_of_unknown_size_still_says_it_is_moving(monkeypatch):
    """No total from the site: the helper says it's alive about once a second, so the
    app doesn't take it for stuck (ytdl.DOWNLOAD_QUIET_S) and kill a slow download."""
    from tests.conftest import own_time
    clock = [0.0]
    own_time(monkeypatch, ytworker, monotonic=lambda: clock[0])
    fake = type("yt_dlp", (), {"YoutubeDL": lambda self, opts: _FakeYdl(opts, clock)})()
    conn = _Conn()
    ytworker._download(conn, fake, "https://ex.com/v", {}, 600)
    assert conn.sent and all(m == ("alive", None) for m in conn.sent)
    assert 9 <= len(conn.sent) <= 10          # 10 s of downloading, once a second


class _CutYdl(_FakeYdl):
    """A server that cuts every piece off: yt-dlp keeps asking for the same bytes and
    says it's downloading, 90% done, without ever getting further."""

    def process_ie_result(self, info, download):
        for _ in range(1000):
            self.clock[0] += 0.2
            self.hook({"status": "downloading", "downloaded_bytes": 900,
                       "total_bytes": 1000})
        return info


def test_a_download_that_stops_growing_fails_instead_of_hanging(monkeypatch):
    """Progress messages kept the app's quiet timer happy while nothing arrived: the
    card sat on "Adding... 90%" for good. Bytes that don't grow for STALL_S end it."""
    from tests.conftest import own_time
    clock = [0.0]
    own_time(monkeypatch, ytworker, monotonic=lambda: clock[0])
    fake = type("yt_dlp", (), {"YoutubeDL": lambda self, opts: _CutYdl(opts, clock)})()
    with pytest.raises(ytworker.Stalled):
        ytworker._download(_Conn(), fake, "https://ex.com/v", {}, 600)
    assert ytworker.STALL_S <= clock[0] < ytworker.STALL_S + 1


class _QuietConn:
    """The helper's pipe: a few progress messages, then nothing at all (yt-dlp asking a
    server that cuts every piece off for the same bytes again, without a word)."""

    def __init__(self, said):
        self.said, self.waits = list(said), []

    def send(self, msg):
        pass

    def poll(self, wait):
        self.waits.append(wait)
        return bool(self.said)

    def recv(self):
        return self.said.pop(0)


def test_a_download_that_goes_quiet_after_starting_is_stuck_sooner():
    h = object.__new__(ytworker._Helper)
    h.conn, killed = _QuietConn([("progress", 0.5), ("progress", 0.9)]), []
    h.kill = lambda: killed.append(True)
    with pytest.raises(TimeoutError):
        h.call(("download",), 300)
    assert h.conn.waits[0] == 300                    # before any data: the long wait
    assert h.conn.waits[-1] == ytworker.STALL_S       # once it was moving: the short one
    assert killed


def test_a_stalled_helper_download_says_it_stopped_moving(monkeypatch):
    def run(*a, **kw):
        raise ytworker.RemoteError("soundboard.online.ytworker.Stalled", "no new data for 60 s")
    monkeypatch.setattr(ytworker, "run", run)
    with pytest.raises(ytdl.FetchError, match="stopped moving"):
        ytdl._run_helper("https://www.youtube.com/watch?v=x", {}, None)


class _SearchYdl:
    """yt-dlp's YouTube search: reads YouTube's settings, then asks the API. `fail`
    makes the API turn down settings marked old."""
    fetched: list = []
    fail = False

    def __init__(self, opts):
        self.ie = type("IE", (), {})()
        self.ie._download_ytcfg = self._fetch

    def _fetch(self, client, video_id):
        _SearchYdl.fetched.append(client)
        return {"VISITOR_DATA": f"v{len(_SearchYdl.fetched)}"}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_info_extractor(self, key):
        if key != "YoutubeMusicSearchURL":
            raise KeyError(key)    # one that yt-dlp no longer has: left alone
        return self.ie

    def extract_info(self, target, download):
        cfg = self.ie._download_ytcfg("web_music", "q")
        if _SearchYdl.fail and cfg["VISITOR_DATA"] == "v1":
            raise RuntimeError("HTTP Error 400: Bad Request")
        return {"entries": [], "cfg": cfg["VISITOR_DATA"]}


@pytest.fixture
def search_ydl(monkeypatch):
    _SearchYdl.fetched, _SearchYdl.fail = [], False
    ytworker.forget_configs()
    yield type("yt_dlp", (), {"YoutubeDL": _SearchYdl})
    ytworker.forget_configs()


def test_searches_reuse_youtubes_settings_only_when_asked(search_ydl, monkeypatch):
    for _ in range(3):
        assert ytworker.extract(search_ydl, "q", {}, keep=True)["cfg"] == "v1"
    assert _SearchYdl.fetched == ["web_music"]                 # fetched once, then kept
    ytworker.extract(search_ydl, "q", {})
    assert len(_SearchYdl.fetched) == 2                        # not asked: fetched again
    from tests.conftest import own_time
    clock = [10.0**6]
    own_time(monkeypatch, ytworker, monotonic=lambda: clock[0])
    ytworker.forget_configs()
    ytworker.extract(search_ydl, "q", {}, keep=True)
    clock[0] += ytworker.CONFIG_KEEP_S + 1                     # too old: fetched again
    ytworker.extract(search_ydl, "q", {}, keep=True)
    assert len(_SearchYdl.fetched) == 4


def test_a_search_failing_with_kept_settings_is_done_again_the_old_way(search_ydl):
    ytworker.extract(search_ydl, "q", {}, keep=True)           # keeps "v1"
    _SearchYdl.fail = True
    assert ytworker.extract(search_ydl, "q", {}, keep=True)["cfg"] == "v2"
    assert ytworker.extract(search_ydl, "q", {}, keep=True)["cfg"] == "v2"  # v2 kept now
    ytworker.forget_configs()
    _SearchYdl.fetched = []                                    # fresh ones failing: no retry
    with pytest.raises(RuntimeError):
        ytworker.extract(search_ydl, "q", {}, keep=True)
    assert len(_SearchYdl.fetched) == 1


def test_youtube_settings_are_kept_in_direct_mode_only(monkeypatch):
    from soundboard.online import net
    keeps = []
    monkeypatch.setattr(ytdl, "_gate", lambda source: "sounds_web")
    monkeypatch.setattr(ytdl, "_over_tor", lambda fn, site: fn())
    monkeypatch.setattr(ytdl, "_extract", lambda t, o, keep=False: keeps.append(keep) or {})
    for mode, source, want in ((net.DIRECT, "ytmusic", True), (net.DIRECT, "youtube", True),
                               (net.DIRECT, "soundcloud", False), (net.TOR, "ytmusic", False),
                               (net.PROXY, "youtube", False)):
        monkeypatch.setattr(net, "mode", lambda m=mode: m)
        ytdl.search("tes", source=source)
        assert keeps.pop() is want, (mode, source)


def test_alive_messages_keep_the_wait_going():
    from multiprocessing import Pipe
    mine, theirs = Pipe()
    h = ytworker._Helper.__new__(ytworker._Helper)
    h.conn, h.proc = mine, None
    for msg in (("alive", None), ("progress", 0.5), ("alive", None), ("ok", 7)):
        theirs.send(msg)
    seen = []
    assert h.call(("download",), timeout=5, progress=seen.append) == ("ok", 7)
    assert seen == [0.5]


def test_helper_waits_for_work_and_exits_when_idle(monkeypatch):
    waits = []

    class Conn:
        def poll(self, timeout):
            waits.append(timeout)
            return False

        def recv(self):
            pytest.fail("read without a request")

    monkeypatch.setenv(ytworker.ADDR_ENV, "test-helper")
    monkeypatch.setenv(ytworker.KEY_ENV, "00")
    monkeypatch.setattr(ytworker, "Client", lambda *a, **kw: Conn())
    monkeypatch.setattr(ytdl, "_ydl", lambda: nullcontext(None))
    assert ytworker.child_main() == 0
    assert waits == [ytworker.IDLE_S]
    assert ytworker.IDLE_S > 0


def test_a_soundcloud_search_asks_the_picture_server_nothing():
    """yt-dlp checks every result's full-size cover with a request of its own; the
    card only uses the listed one (and none at all with search pictures off)."""
    yt_dlp = pytest.importorskip("yt_dlp")
    with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
        ytworker._listed_art_only(ydl)
        ie = ydl.get_info_extractor("SoundcloudSearch")
        ie._request_webpage = lambda *a, **k: pytest.fail("asked the picture server")
        art = "https://i1.sndcdn.com/artworks-abc-large.jpg"
        assert ie._extract_thumbnails({"id": 1, "artwork_url": art}) == [{"url": art}]
        avatar = "https://i1.sndcdn.com/avatars-abc-large.jpg"
        only_avatar = {"id": 1, "user": {"avatar_url": avatar}}
        assert ie._extract_thumbnails(only_avatar) == [{"url": avatar}]
        assert ie._extract_thumbnails({"id": 1}) is None
        hit = ytdl._soundcloud_hit({"id": 1, "title": "t", "thumbnails": [{"url": art}],
                                    "webpage_url": "https://soundcloud.com/a/b"})
        assert hit.art == "https://i1.sndcdn.com/artworks-abc-t300x300.jpg"


def test_a_soundcloud_result_keeps_its_cover_through_the_helper():
    """The helper slims what it sends back, but a search card's picture stays."""
    small = "https://i1.sndcdn.com/artworks-abc-small.jpg"
    art = "https://i1.sndcdn.com/artworks-abc-large.jpg"
    entry = {"id": 1, "title": "t", "webpage_url": "https://soundcloud.com/a/b",
             "thumbnails": [{"url": small}, {"url": art, "width": 100}],
             "formats": [{"url": "x"}]}
    slim = ytworker._slim({"_type": "playlist", "entries": [entry, {"id": 2}]})
    one, bare = slim["entries"]
    assert one["thumbnails"] == [{"url": art}] and "formats" not in one
    assert "thumbnails" not in bare
    assert ytdl._soundcloud_hit(one).art == "https://i1.sndcdn.com/artworks-abc-t300x300.jpg"
    del entry["thumbnails"]
    entry["thumbnail"] = art
    assert ytdl._soundcloud_hit(ytworker._slim(entry)).art.endswith("-t300x300.jpg")
