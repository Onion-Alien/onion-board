"""The link bar holds a whole decoded download for Play once / Play after Add: it
must let go of it with the link, and never do the song-sized maths on the UI thread."""
import numpy as np

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
