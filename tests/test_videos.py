"""Pads made from a video: which video belongs to which sound (videos.json beside the
config, so older versions keep the links), and the player's Video window following
the pad's sound - playing, pausing, seeking and keeping pace with speed effects."""
import json
import tempfile
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from PySide6.QtCore import QEvent
from PySide6.QtMultimedia import QMediaPlayer

from conftest import process_events
from soundboard import engine, library, videos, winkeys
from soundboard.library import SR, Config, SoundMeta
from soundboard.ui.videowindow import VideoWindow


def _video(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not really a video")
    return path


def test_a_linked_video_is_found_until_it_is_moved(app_dir):
    clip = _video(app_dir / "clips" / "funny.mp4")
    assert videos.get("s1") is None
    videos.link("s1", clip)
    assert videos.get("s1") == clip.resolve()
    clip.unlink()
    assert videos.get("s1") is None   # not offered, nothing breaks


def test_the_links_live_beside_the_config_not_in_it(app_dir):
    videos.link("s1", _video(app_dir / "clips" / "a.mp4"))
    assert json.loads((app_dir / "videos.json").read_text(encoding="utf-8")) == {
        "s1": str((app_dir / "clips" / "a.mp4").resolve())}
    # an older version rewriting config.json can't drop them
    Config(sounds=[SoundMeta(id="s1", name="A", file="a.flac")]).save()
    assert videos.get("s1") is not None


def test_import_links_only_videos_that_stay_put(app_dir):
    assert videos.link_import("a", _video(app_dir / "clips" / "a.mp4"))
    assert videos.get("a") is not None
    assert not videos.link_import("b", app_dir / "clips" / "missing.mp4")
    song = app_dir / "clips" / "song.mp3"
    song.write_bytes(b"x")
    assert not videos.link_import("c", song)   # audio: nothing to show
    # replaced by its FLAC when dragged into the Sounds folder
    assert not videos.link_import("d", _video(library.SOUNDS_DIR / "d.mp4"))
    # unpacked from a zip into a temp folder, deleted once it's in
    with tempfile.TemporaryDirectory(prefix="onionboard-zip-") as tmp:
        assert not videos.link_import("e", _video(Path(tmp) / "e.mp4"))
    assert [k for k in ("a", "b", "c", "d", "e") if videos.get(k)] == ["a"]


def test_a_copied_pad_shows_the_same_video(app_dir):
    videos.link("s1", _video(app_dir / "clips" / "a.mp4"))
    videos.copy_link("s1", "s2")
    videos.copy_link("nope", "s3")
    assert videos.get("s2") == videos.get("s1")
    assert videos.get("s3") is None


def test_a_damaged_links_file_is_ignored(app_dir):
    (app_dir / "videos.json").write_text("[1, 2", encoding="utf-8")
    assert videos.get("s1") is None
    videos.link("s1", _video(app_dir / "clips" / "a.mp4"))
    assert videos.get("s1") is not None


class FakePlayer:
    """Stands in for QMediaPlayer: no real video decoding offscreen."""

    def __init__(self, duration=10_000):
        self._dur, self.pos, self.rate = duration, 0, 1.0
        self.state = QMediaPlayer.StoppedState

    def duration(self):
        return self._dur

    def position(self):
        return self.pos

    def setPosition(self, ms):
        self.pos = ms

    def playbackRate(self):
        return self.rate

    def setPlaybackRate(self, r):
        self.rate = r

    def playbackState(self):
        return self.state

    def play(self):
        self.state = QMediaPlayer.PlayingState

    def pause(self):
        self.state = QMediaPlayer.PausedState

    def stop(self):
        self.state = QMediaPlayer.StoppedState

    def setSource(self, _url):
        pass


def test_the_video_follows_the_sound(qapp):
    w = VideoWindow()
    w.player.deleteLater()
    w.player = p = FakePlayer(10_000)
    w.follow((0.5, False), 10.0)
    assert p.state == QMediaPlayer.PlayingState and p.pos == 5000 and p.rate == 1.0
    p.pos = 5100
    w.follow((0.52, False), 10.0)
    assert p.pos == 5100   # close enough: no jump
    w.follow((0.52, True), 10.0)
    assert p.state == QMediaPlayer.PausedState
    w.follow((0.9, False), 10.0)
    assert p.pos == 9000 and p.state == QMediaPlayer.PlayingState   # seeked
    w.follow(None, 10.0)
    assert p.state == QMediaPlayer.PausedState   # stopped
    # sped up 2x by its effects (5 s of audio) and 1.5x live: the video keeps pace
    w.follow((0.1, False), 5.0, 1.5)
    assert p.rate == pytest.approx(3.0) and p.pos == 1000
    w.deleteLater()


# --------------------------------------------------------------------- the real window

def _close(qapp, w):
    w.close()
    if w._load_thread:
        w._load_thread.join(15)
    w.deleteLater()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.fixture
def window(qapp, app_dir, monkeypatch):
    from soundboard.ui import mainwindow as main
    for name in ("set_main_device", "set_mon_device", "set_mic_device"):
        monkeypatch.setattr(engine.Engine, name, lambda self, n, _k=name: None)
    monkeypatch.setattr(winkeys.Hotkeys, "register", lambda self, m: None)
    sounds = []
    for sid in ("vid", "plain"):
        t = np.arange(int(SR * 0.5)) / SR
        f = app_dir / f"{sid}.wav"
        sf.write(str(f), np.stack([np.sin(2 * np.pi * 440 * t)] * 2, 1) * 0.3, SR)
        sounds.append(SoundMeta(id=sid, name=sid, file=str(f)))
    Config(sounds=sounds).save()
    videos.link("vid", _video(app_dir / "clips" / "vid.mp4"))
    w = main.MainWindow()
    w._load_thread.join(15)
    process_events(qapp, lambda: all(p.state == "ready" for p in w.pads.values()), 5)
    yield w
    _close(qapp, w)


def test_the_video_button_shows_only_for_a_video_pad(window, monkeypatch):
    w = window
    w.select("plain")
    w._update_transport({})
    assert w.btn_video.isHidden()
    w.select("vid")
    w._update_transport({})
    assert not w.btn_video.isHidden()
    shown, played = [], []
    monkeypatch.setattr(VideoWindow, "show_for", lambda self, sid, name, path: shown.append(sid))
    monkeypatch.setattr(w, "toggle_play_pause", lambda: played.append(w.current))
    w.btn_video.click()
    assert shown == ["vid"] and played == ["vid"]   # opens it and starts the sound


def test_a_moved_video_takes_the_button_away(window, app_dir):
    w = window
    w.select("vid")
    w._update_transport({})
    (app_dir / "clips" / "vid.mp4").unlink()
    w.btn_video.click()
    assert w.btn_video.isHidden() and w._video_win is None
