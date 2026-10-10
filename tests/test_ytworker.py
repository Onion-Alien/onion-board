"""soundboard.ytworker: yt-dlp in a helper process, off the audio callbacks' GIL."""
import pytest

from soundboard import ytdl, ytworker


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
    with pytest.raises(ytdl.FetchError, match="^That link isn.t from a site"):
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
    from soundboard import net
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
