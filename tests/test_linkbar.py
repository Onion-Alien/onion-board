"""The link bar holds a whole decoded download for Play once / Play after Add: it
must let go of it with the link, and never do the song-sized maths on the UI thread."""
import numpy as np
import pytest

from soundboard.sounds.library import Config, SoundMeta
from soundboard.ui.sounds.linkbar import LinkBar


def _fake_threads(monkeypatch, module, worker):
    """`module` starts `worker` for its threads; every other module keeps real threads
    (patching threading.Thread itself also caught the app's network relay restarting
    in a later fixture, on whichever test ran after the relay was stopped)."""
    import threading
    import types
    fake = types.SimpleNamespace(**{k: getattr(threading, k) for k in dir(threading)
                                    if not k.startswith("__")})
    fake.Thread = worker
    monkeypatch.setattr(module, "threading", fake)


URL = "https://www.youtube.com/watch?v=abc"


class Eng:
    def __init__(self):
        self.played = []
        self.modes = []

    def play(self, sid, data, gain, **kw):
        self.played.append((sid, len(data), gain))
        self.modes.append(kw.get("mode"))
        return object()

    def stop(self, sid):
        pass

    def playing(self):
        return getattr(self, "now", {})


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
    from soundboard.ui.sounds import linkbar

    bar, eng = _bar()
    data = np.zeros((480, 2), np.int16)
    path = tmp_path / "clip.wav"
    meta = SoundMeta(id="x1", name="Clip", file="x.wav", level_gain=0.5)
    downloads, added, done, workers = [], [], [], []
    monkeypatch.setattr(linkbar.ytdl, "download_audio",
                        lambda url, **kw: (downloads.append(url) or path, "Clip"))
    monkeypatch.setattr(linkbar, "decode_int16", lambda path: (data, 0.5))
    monkeypatch.setattr(linkbar, "fingerprint", lambda path: "fp")
    monkeypatch.setattr(linkbar, "import_file", lambda path, color, **kw: (meta, data))
    monkeypatch.setattr(linkbar.thumbs, "find_in", lambda folder: None)
    monkeypatch.setattr(eng, "prepare", lambda *args: None, raising=False)

    class Worker:
        def __init__(self, target, args, **kw):
            workers.append(lambda: target(*args))

        def start(self):
            pass

    _fake_threads(monkeypatch, linkbar, Worker)
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
    from soundboard.ui.sounds import linkbar

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


def test_a_sound_already_had_is_not_counted_as_a_failed_download(qapp, monkeypatch,
                                                                  tmp_path):
    from soundboard.ui.sounds import linkbar

    bar, eng = _bar()
    data = np.zeros((480, 2), np.int16)
    failed, imported, already = [], [], []
    monkeypatch.setattr(linkbar, "fingerprint", lambda path: "fp")
    monkeypatch.setattr(linkbar, "import_file", lambda *a, **kw: imported.append(a))
    monkeypatch.setattr(linkbar.usage, "failed", lambda *a: failed.append(a))
    bar.already_have.connect(already.append)
    bar._busy, bar._busy_url = "add", URL
    bar._work("add", URL, (URL, tmp_path / "clip.wav", data, 1.0), "#fff",
              {"fp": "Clip"}, False)
    assert already == ["fp"] and not imported
    assert failed == []   # its own count (dl-already-have), not "another reason"


OTHER = "https://www.youtube.com/watch?v=other"


def _fake_start(bar, monkeypatch):
    """_start without a worker thread: the test sends the worker's messages itself."""
    from soundboard.ui.sounds import linkbar

    class Worker:
        def __init__(self, *a, **kw):
            pass

        def start(self):
            pass

    _fake_threads(monkeypatch, linkbar, Worker)


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


def test_a_new_play_waits_for_the_one_still_loading(qapp, monkeypatch, tmp_path):
    from soundboard.ui.sounds import linkbar

    bar, eng = _bar()
    _fake_start(bar, monkeypatch)
    monkeypatch.setattr(linkbar.busy, "toast", lambda *args, **kw: None)
    done = []
    bar.done.connect(lambda *args: done.append(args))
    bar.play_once()
    first = bar._job
    bar.open(OTHER, "Other")
    bar.play_once()
    assert done == [] and bar._busy_url == URL   # the first isn't dropped
    assert [q["url"] for q in bar._queue_list] == [OTHER]
    data = np.zeros((480, 2), np.int16)
    bar._on_msg("play", URL, (tmp_path / "a.wav", data, 1.0), first)
    assert len(eng.played) == 1 and bar._busy_url == OTHER
    eng.now = {"__link__": (0.0, False)}           # the first is playing
    bar._on_msg("play", OTHER, (tmp_path / "b.wav", data, 1.0), bar._job)
    assert len(eng.played) == 1 and bar.up_next() == ["Other"]   # not cut off
    eng.now = {}
    assert bar.play_next() and len(eng.played) == 2 and bar.up_next() == []


def test_a_play_still_plays_after_another_card_is_queued_and_removed(qapp, monkeypatch,
                                                                     tmp_path):
    """Play on one card, Add on another while it loads (it waits), then ✕ on the
    waiting one: the Play that was loading still plays when it lands, not dropped
    without a word because a different card was the one showing."""
    bar, eng = _bar()
    _fake_start(bar, monkeypatch)
    done, played = [], []
    bar.done.connect(lambda *args: done.append(args))
    bar.played.connect(lambda title, *_a: played.append(title))
    bar.open(URL, "Shrek")
    bar.play_once()
    job = bar._job
    bar.open(OTHER, "Random")
    assert bar.add()                       # waits behind the Play
    bar.cancel(OTHER)                      # its ✕ in the download bar
    assert done == [(OTHER, "add", False)] and bar._busy == "play"
    data = np.zeros((480, 2), np.int16)
    bar._on_msg("play", URL, (tmp_path / "a.wav", data, 1.0), job)
    assert eng.played == [("__link__", 480, 1.0)] and played == ["Shrek"]
    assert done[-1] == (URL, "play", True) and not bar._busy


def test_picks_queue_behind_an_add_and_a_full_queue_says_so(qapp, monkeypatch):
    from soundboard.ui.sounds import linkbar

    bar, _eng = _bar()
    _fake_start(bar, monkeypatch)
    toasts, queued, done = [], [], []
    monkeypatch.setattr(linkbar.busy, "toast", lambda *args, **kw: toasts.append(args))
    bar.queued.connect(lambda *args: queued.append(args))
    bar.done.connect(lambda *args: done.append(args))
    bar.add()
    for i in range(linkbar.MAX_QUEUED):
        bar.open(f"{OTHER}{i}", f"Other {i}")
        assert bar.add()
    assert len(queued) == linkbar.MAX_QUEUED and queued[0] == (f"{OTHER}0", "add")
    bar.open(OTHER, "One too many")
    assert not bar.add() and toasts   # no crash, a message instead
    bar.cancel(f"{OTHER}1")           # a waiting pick: its row is told it's off
    assert done == [(f"{OTHER}1", "add", False)]
    assert [q["url"] for q in bar._queue_list] == [
        f"{OTHER}{i}" for i in range(linkbar.MAX_QUEUED) if i != 1]


def test_play_now_goes_before_adds_after_waiting_plays(qapp, monkeypatch):
    from soundboard.ui.sounds import linkbar

    bar, _eng = _bar()
    _fake_start(bar, monkeypatch)
    monkeypatch.setattr(linkbar.busy, "toast", lambda *args, **kw: None)
    done, lists = [], []
    bar.done.connect(lambda *args: done.append(args))
    bar.queue_updated.connect(lambda q: lists.append([(x["url"], x["kind"]) for x in q]))
    bar.add()                                   # downloading one song...
    for i in range(2):                          # ...two more waiting to be added
        bar.open(f"{OTHER}a{i}", "Add")
        bar.add()
    bar.open(f"{OTHER}p1", "Play")
    assert bar.play_once()
    # Play now: next up, the running Add untouched
    assert lists[-1] == [(f"{OTHER}p1", "play"), (f"{OTHER}a0", "add"),
                         (f"{OTHER}a1", "add")]
    assert bar._busy == "add" and bar._busy_url == URL
    # a second Play waits after the first, both before the Adds (none dropped)
    bar.open(f"{OTHER}p2", "Play")
    bar.play_once()
    assert [u for u, _k in lists[-1][:2]] == [f"{OTHER}p1", f"{OTHER}p2"]
    assert len(lists[-1]) == 4 and not done
    # a full queue of Adds still takes a Play
    bar.open(f"{OTHER}a2", "Add")
    bar.add()
    bar.open(f"{OTHER}p3", "Play")
    assert bar.play_once() and lists[-1][2] == (f"{OTHER}p3", "play")
    # the Add finishes: the Plays start before the other Adds
    bar._on_msg("error", URL, "nope", bar._job)
    assert bar._busy == "play" and bar._busy_url == f"{OTHER}p1"


def test_downloads_are_counted_by_site_and_how_they_were_picked(qapp, monkeypatch):
    from soundboard.core import usage
    calls = []
    monkeypatch.setattr(usage, "downloaded", lambda cfg, *a: calls.append(a))
    monkeypatch.setattr(usage, "_used", set())
    bar, eng = _bar()                          # a pasted link
    bar._busy, bar._busy_url = "play", URL
    bar._on_msg("play", URL, ("x.wav", np.zeros(4, np.int16), 1.0))
    bar.open(OTHER, "Other", 3.0)              # a web search pick
    bar._busy, bar._busy_url = "add", OTHER
    bar._on_msg("why", OTHER, "bot")           # why it failed, before the error
    assert bar._busy == "add"                  # not the end of the download
    bar._on_msg("error", OTHER, "Couldn't download it")
    assert calls == [(URL, "link", "play", True, ""), (OTHER, "search", "add", False, "bot")]
    bar._busy, bar._busy_url = "add", OTHER    # already in the library: not a failure
    bar._on_msg("dup", OTHER, None)
    bar._on_msg("error", OTHER, "It's already in your Sounds")
    assert len(calls) == 2 and "dl-already-have" in usage._used


def test_downloading_is_true_only_while_a_link_runs(qapp):
    bar, _eng = _bar()
    assert not bar.downloading()
    bar._busy, bar._busy_url = "add", URL
    assert bar.downloading()


@pytest.mark.parametrize("ffmpeg", [None, "ffmpeg.exe"])
def test_add_with_save_video_says_why_no_video_was_kept(qapp, monkeypatch, tmp_path, ffmpeg):
    """Also save the video, but the download is only the sound (SoundCloud has no video;
    YouTube has none without ffmpeg to merge it): the sound is still added, and the bar
    says why there's no video, naming FFmpeg when that's what's missing."""
    from soundboard.sounds import library
    from soundboard.ui.sounds import linkbar

    bar, eng = _bar()
    data = np.zeros((480, 2), np.int16)
    meta = SoundMeta(id="x1", name="Clip", file=str(tmp_path / "Clip.mp3"))
    audio = tmp_path / "abc.m4a"
    audio.write_bytes(b"x")
    asked = []
    monkeypatch.setattr(linkbar.ytdl, "download_audio",
                        lambda url, **kw: (asked.append(kw), (audio, "Clip"))[1])
    monkeypatch.setattr(library, "_ffmpeg", lambda: ffmpeg)
    monkeypatch.setattr(linkbar, "fingerprint", lambda path: "fp")
    monkeypatch.setattr(linkbar, "import_file", lambda path, color, **kw: (meta, data))
    monkeypatch.setattr(linkbar.thumbs, "find_in", lambda folder: None)
    monkeypatch.setattr(eng, "prepare", lambda *args: None, raising=False)
    added = []
    bar.sound_ready.connect(lambda *args: added.append(args))
    bar._busy, bar._busy_url = "add", URL
    bar._work("add", URL, None, "#fff", {}, False, video=True)
    assert asked[0].get("video") and len(added) == 1
    text = bar.info.text()
    assert "No video was saved" in text
    assert ("needs FFmpeg" in text) == (ffmpeg is None), text


def test_the_switched_off_line_follows_the_switches(qapp):
    """Offline mode's line stayed up after Offline mode was switched off and only the
    sounds switch was: the line is redone whenever a switch changes."""
    from soundboard.online import net
    try:
        net.configure_features(offline=True)
        bar, __ = _bar()
        assert "Offline mode" in bar.info.text() and bar._shown
        net.configure_features(off=["sounds_web"])
        qapp.processEvents()
        assert "Offline mode" not in bar.info.text()
        assert bar.info.text() and bar._shown          # says it's switched off instead
        net.configure_features()
        qapp.processEvents()
        assert bar.info.text() == "" and not bar._shown
    finally:
        net.configure_features()


def test_play_now_plays_over_a_link_playing_and_play_once_waits(qapp):
    """The Store's Play: over the link that's playing, not after it (its Play next is
    Play once: Up next)."""
    bar, eng = _bar()
    data = np.zeros((480, 2), np.int16)
    bar._got = (URL, None, data, 1.0)
    eng.now = {"__link__": (0.3, False)}   # another link plays
    bar.play_once()
    assert eng.played == [] and bar.up_next() == ["Link"]
    bar.drop_up_next()
    bar.play_now()
    assert eng.played == [("__link__", 480, 1.0)] and bar.up_next() == []
    assert bar.playing_url == URL
    assert eng.modes == ["restart"]   # (the board's sounds play on)


def test_community_play_stops_the_sounds_playing_as_a_pad_does(qapp):
    """The Community tab's Play (a link, or an upload's audio) plays as a pad's press:
    the sounds playing stop (engine mode solo), and nothing waits in Up next."""
    bar, eng = _bar()
    data = np.zeros((480, 2), np.int16)
    bar._got = (URL, None, data, 1.0)
    eng.now = {"pad1": (0.3, False)}   # one of your sounds plays
    bar.play_now(solo=True)
    assert eng.modes == ["solo"] and bar.up_next() == []
    assert bar.play_audio(data, 1.0, "Horn", "community:abc", now=True)
    assert eng.modes == ["solo", "solo"] and bar.playing_url == "community:abc"
    eng.now = {"__link__": (0.3, False)}
    bar.play_audio(data, 1.0, "Horn 2", "community:def", now=False)   # its Play next waits
    assert bar.up_next() == ["Horn 2"] and len(eng.modes) == 2
