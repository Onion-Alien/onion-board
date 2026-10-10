"""soundboard.ytworker: yt-dlp in a helper process, off the audio callbacks' GIL."""
import pytest

from soundboard import ytdl, ytworker


@pytest.fixture
def helper(monkeypatch):
    monkeypatch.setattr(ytworker, "enabled", True)
    yield
    ytworker.drop_all()


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
