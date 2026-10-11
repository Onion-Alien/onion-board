"""The link bar holds a whole decoded download for Play once / Play after Add: it
must let go of it with the link, and never do the song-sized maths on the UI thread."""
import numpy as np
import pytest

from soundboard.library import Config, SoundMeta
from soundboard.ui.linkbar import LinkBar

URL = "https://www.youtube.com/watch?v=abc"


class Eng:
    def __init__(self):
        self.played = []

    def play(self, sid, data, gain, **kw):
        self.played.append((sid, len(data), gain))
        return object()

    def stop(self, sid):
        pass


def _bar():
    eng = Eng()
    bar = LinkBar(engine=eng, cfg=Config(), color_for=lambda: "#fff", known_for=dict)
    bar.set_text(URL)
    return bar, eng


def test_play_uses_the_workers_gain_and_is_dropped_with_the_link(qapp, tmp_path):
    bar, eng = _bar()
    bar.cfg.level_volumes = True
    data = np.zeros((480, 2), np.int16)
    bar._busy = "play"
    bar._on_msg("play", URL, (tmp_path / "a.wav", data, 0.5))
    assert eng.played == [("__link__", 480, 0.5)]
    bar.play_once()                       # again, from what it kept
    assert eng.played[-1] == ("__link__", 480, 0.5)
    bar.cfg.level_volumes = False
    bar.play_once()
    assert eng.played[-1] == ("__link__", 480, 1.0)
    bar.set_text("https://www.youtube.com/watch?v=other")
    assert bar._got is None


def test_the_added_audio_is_kept_for_play_only_while_its_link_shows(qapp):
    bar, eng = _bar()
    bar.cfg.level_volumes = True
    data = np.zeros((480, 2), np.int16)
    meta = SoundMeta(id="x1", name="Clip", file="x.wav", level_gain=2.0)
    bar._busy = "add"
    bar._on_msg("added", URL, (meta, data, "Clip", ""))
    assert bar._kept is not None
    bar.play_once()                       # Play after Add: no download, its own gain
    assert eng.played == [("__link__", 480, 2.0)]
    bar.set_text("")                      # the link is gone: so is the audio
    assert bar._kept is None and bar._got is None


@pytest.mark.parametrize("first", ["add", "play"])
def test_add_and_play_share_one_download(qapp, monkeypatch, tmp_path, first):
    from soundboard.ui import linkbar

    bar, eng = _bar()
    data = np.zeros((480, 2), np.int16)
    path = tmp_path / "clip.wav"
    meta = SoundMeta(id="x1", name="Clip", file="x.wav", level_gain=0.5)
    downloads, added, done, workers = [], [], [], []
    monkeypatch.setattr(linkbar.ytdl, "download_audio",
                        lambda url, **kw: (downloads.append(url) or path, "Clip"))
    monkeypatch.setattr(linkbar, "decode", lambda path: data)
    monkeypatch.setattr(linkbar, "to_int16", lambda audio: audio)
    monkeypatch.setattr(linkbar, "level_gain", lambda audio: 0.5)
    monkeypatch.setattr(linkbar, "fingerprint", lambda path: "fp")
    monkeypatch.setattr(linkbar, "import_file", lambda path, color, **kw: (meta, data))
    monkeypatch.setattr(linkbar.thumbs, "find_in", lambda folder: None)
    monkeypatch.setattr(eng, "prepare", lambda *args: None, raising=False)

    class Worker:
        def __init__(self, target, args, **kw):
            workers.append(lambda: target(*args))

        def start(self):
            pass

    monkeypatch.setattr(linkbar.threading, "Thread", Worker)
    bar.sound_ready.connect(lambda *args: added.append(args))
    bar.sound_ready.connect(lambda meta, _data: bar.cfg.sounds.append(meta))
    bar.done.connect(lambda *args: done.append(args))
    assert (bar.add() if first == "add" else bar.play_once())
    # Repeated activation mustn't queue a duplicate of the running action.
    assert (bar.add() if first == "add" else bar.play_once())
    assert (bar.play_once() if first == "add" else bar.add())
    assert (bar.play_once() if first == "add" else bar.add())
    while workers:
        workers.pop(0)()
    assert downloads == [URL]
    assert len(added) == 1 and len(eng.played) == 1
    assert sorted(done) == [(URL, "add", True), (URL, "play", True)]
    assert not bar._busy and not bar._queued
    assert bar.add()   # an already completed Add is also idempotent
    assert not workers and len(added) == 1


def test_failed_download_finishes_both_actions_without_retry(qapp, monkeypatch):
    bar, eng = _bar()
    bar._busy, bar._busy_url = "add", URL
    done, starts = [], []
    bar.done.connect(lambda *args: done.append(args))
    monkeypatch.setattr(bar, "_start", lambda *args: starts.append(args))
    assert bar.play_once()
    bar._on_msg("error", URL, "Couldn't download it")
    assert done == [(URL, "add", False), (URL, "play", False)]
    assert not starts and not eng.played and not bar._queued


def test_thumbnail_failure_does_not_fail_successful_import(qapp, monkeypatch, tmp_path):
    from soundboard.ui import linkbar

    bar, eng = _bar()
    data = np.zeros((480, 2), np.int16)
    meta = SoundMeta(id="x1", name="Clip", file="x.wav")
    monkeypatch.setattr(linkbar, "fingerprint", lambda path: "fp")
    monkeypatch.setattr(linkbar, "import_file", lambda path, color, **kw: (meta, data))
    monkeypatch.setattr(linkbar.thumbs, "find_in", lambda folder: tmp_path / "pic.jpg")
    def fail_thumbnail(*args):
        raise OSError("thumbnail could not be saved")
    monkeypatch.setattr(linkbar.thumbs, "store", fail_thumbnail)
    monkeypatch.setattr(eng, "prepare", lambda *args: None, raising=False)
    added, done = [], []
    bar.sound_ready.connect(lambda *args: added.append(args))
    bar.done.connect(lambda *args: done.append(args))
    bar._busy, bar._busy_url = "add", URL
    bar._work("add", URL, (URL, tmp_path / "clip.wav", data, 1.0), "#fff", {}, False)
    assert len(added) == 1
    assert done == [(URL, "add", True)]


OTHER = "https://www.youtube.com/watch?v=other"


def _fake_start(bar, monkeypatch):
    """_start without a worker thread: the test sends the worker's messages itself."""
    from soundboard.ui import linkbar

    class Worker:
        def __init__(self, *a, **kw):
            pass

        def start(self):
            pass

    monkeypatch.setattr(linkbar.threading, "Thread", Worker)


def test_a_cancelled_play_never_plays_when_its_download_lands(qapp, monkeypatch, tmp_path):
    bar, eng = _bar()
    _fake_start(bar, monkeypatch)
    done = []
    bar.done.connect(lambda *args: done.append(args))
    assert bar.play_once()
    old = bar._job
    bar.cancel()
    assert done == [(URL, "play", False)] and not bar._busy
    # the worker keeps going: many progress ticks, then the audio. None of it counts.
    data = np.zeros((480, 2), np.int16)
    for f in (0.2, 0.6, "processing"):
        bar._on_msg("progress", URL, f, old)
    bar._on_msg("play", URL, (tmp_path / "a.wav", data, 1.0), old)
    assert eng.played == [] and old not in bar._dropped


def test_a_new_play_replaces_the_one_still_loading(qapp, monkeypatch, tmp_path):
    bar, eng = _bar()
    _fake_start(bar, monkeypatch)
    done = []
    bar.done.connect(lambda *args: done.append(args))
    bar.play_once()
    first = bar._job
    bar.open(OTHER, "Other")
    bar.play_once()
    assert done == [(URL, "play", False)] and bar._busy_url == OTHER
    data = np.zeros((480, 2), np.int16)
    bar._on_msg("play", URL, (tmp_path / "a.wav", data, 1.0), first)   # late: dropped
    assert eng.played == [] and bar._busy == "play"
    bar._on_msg("play", OTHER, (tmp_path / "b.wav", data, 1.0), bar._job)
    assert len(eng.played) == 1


def test_picks_queue_behind_an_add_and_a_full_queue_says_so(qapp, monkeypatch):
    from soundboard.ui import linkbar

    bar, _eng = _bar()
    _fake_start(bar, monkeypatch)
    toasts, queued, done = [], [], []
    monkeypatch.setattr(linkbar.busy, "toast", lambda *args, **kw: toasts.append(args))
    bar.queued.connect(lambda *args: queued.append(args))
    bar.done.connect(lambda *args: done.append(args))
    bar.add()
    for i in range(linkbar.MAX_QUEUED):
        bar.open(f"{OTHER}{i}", f"Other {i}")
        assert bar.play_once()
    assert len(queued) == linkbar.MAX_QUEUED and queued[0] == (f"{OTHER}0", "play")
    bar.open(OTHER, "One too many")
    assert not bar.add() and toasts   # no crash, a message instead
    bar.cancel(f"{OTHER}1")           # a waiting pick: its row is told it was a Play
    assert done == [(f"{OTHER}1", "play", False)]
    assert [q["url"] for q in bar._queue_list] == [f"{OTHER}0", f"{OTHER}2"]


def test_downloads_are_counted_by_site_and_how_they_were_picked(qapp, monkeypatch):
    from soundboard import usage
    calls = []
    monkeypatch.setattr(usage, "downloaded", lambda cfg, *a: calls.append(a))
    monkeypatch.setattr(usage, "_used", set())
    bar, eng = _bar()                          # a pasted link
    bar._busy, bar._busy_url = "play", URL
    bar._on_msg("play", URL, ("x.wav", np.zeros(4, np.int16), 1.0))
    bar.open(OTHER, "Other", 3.0)              # a web search pick
    bar._busy, bar._busy_url = "add", OTHER
    bar._on_msg("error", OTHER, "Couldn't download it")
    assert calls == [(URL, "link", "play", True), (OTHER, "search", "add", False)]
    bar._busy, bar._busy_url = "add", OTHER    # already in the library: not a failure
    bar._on_msg("dup", OTHER, None)
    bar._on_msg("error", OTHER, "It's already in your Sounds")
    assert len(calls) == 2 and "dl-already-have" in usage._used
