"""Edit sound follows the pad played (EditControl.follow): once the sound it shows has
stopped, it shows the new one with that sound's saved settings, the old draft dropped."""
import numpy as np

from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)


def test_a_new_pad_shows_in_the_open_window(window, monkeypatch):  # noqa: F811
    w = window
    w.audio["s1"] = np.zeros((48000, 2), np.float32)
    # (tests have no audio device: the engine says it started, and nothing plays)
    monkeypatch.setattr(w.engine, "play", lambda *a, **k: object())
    monkeypatch.setattr(w.engine, "playing", lambda: {})
    d = w.editctl.edit("s0")
    saved = dict(w.meta("s0").fx)
    d.effects.set_own_speed(1.5)            # an unsaved change on s0
    w.playctl.play("s1")
    assert d.meta.id == "s1" and w.editctl._editors == {"s1": d}
    assert d.name.text() == w.meta("s1").name
    assert d.effects.fx() == w.meta("s1").fx   # its own settings, not s0's draft
    assert w.meta("s0").fx == saved           # the draft wasn't saved onto s0
    d.reject()


def test_it_stays_while_its_sound_still_plays(window, monkeypatch):  # noqa: F811
    w = window
    d = w.editctl.edit("s0")
    monkeypatch.setattr(w.engine, "playing", lambda: {"s0": (0.2, False)})
    w.editctl.follow("s1")
    assert d.meta.id == "s0"
    monkeypatch.setattr(w.engine, "playing", lambda: {})
    w.editctl.follow("s1")
    assert d.meta.id == "s1"
    d.reject()


def test_two_windows_open_neither_moves(window):  # noqa: F811
    w = window
    d0, d1 = w.editctl.edit("s0"), w.editctl.edit("s1")
    w.editctl.follow("s2")
    assert (d0.meta.id, d1.meta.id) == ("s0", "s1")
    d0.reject()
    d1.reject()
