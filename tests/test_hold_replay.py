"""Hold-to-play sounds, pads' MIDI hotkeys in the window, and instant replay (the
last seconds of what you heard saved as a pad). The real MainWindow, headless; the
replay's capture is a fake."""
import time

import numpy as np
import pytest

from conftest import process_events
from soundboard import replay as rp
from soundboard.engine import SR
from soundboard.library import SoundMeta
from test_mainwindow import window as main_window  # noqa: F401  (the real MainWindow)


@pytest.fixture
def window(main_window):  # noqa: F811
    return main_window


class FakeCapture:
    """Stands in for appaudio.AppCapture: records what it was asked for, and lets the
    test push audio as the capture thread would."""
    made = []

    def __init__(self, pid, sink, include_tree=True, name=""):
        self.pid, self.sink, self.include_tree = pid, sink, include_tree
        self.error = None
        self.stopped = False
        FakeCapture.made.append(self)

    def start(self, timeout=6.0):
        return True

    def stop(self):
        self.stopped = True

    @property
    def running(self):
        return not self.stopped


def noise(seconds):
    rng = np.random.default_rng(0)
    return (rng.standard_normal((int(seconds * SR), 2)) * 0.2).astype(np.float32)


def test_a_hold_sound_stops_when_its_key_is_let_go(window, monkeypatch):
    w = window
    for sid, hold in (("h", True), ("n", False)):
        w.cfg.sounds.append(SoundMeta(id=sid, name=sid, file=f"{sid}.wav", hold=hold))
        w.audio[sid] = np.zeros((480, 2), np.float32)
    w._index()
    stopped = []
    monkeypatch.setattr(w.engine, "stop", stopped.append)
    w.on_hotkey_released("h")
    w.on_hotkey_released("n")       # an ordinary sound plays on
    w.on_hotkey_released("__stop__")
    assert stopped == ["h"]


def test_midi_pads_are_registered_like_keys(window, monkeypatch):
    w = window
    w.cfg.sounds.append(SoundMeta(id="p", name="p", file="p.wav",
                                  hotkey="midi:note 36:LPD8"))
    w._index()
    sent = []
    monkeypatch.setattr(w.hotkeys, "register", lambda m: sent.append(dict(m)))
    w.register_hotkeys()
    assert sent[-1]["midi:note 36:LPD8"] == "p"


def test_instant_replay_runs_only_while_its_hotkey_is_set(window, qapp, monkeypatch):
    w = window
    FakeCapture.made.clear()
    monkeypatch.setattr(w.replay, "_capture_cls", FakeCapture)
    monkeypatch.setattr(rp.appaudio, "supported", lambda: (True, ""))
    assert not w.replay.enabled
    toasts = []
    monkeypatch.setattr(w, "toast", lambda text, kind="": toasts.append(text))
    w.set_global_hotkey("replay_hotkey", "ctrl+alt+r")
    assert w.replay.enabled
    assert len(toasts) == 1 and "everyone's OK" in toasts[0]   # recording people: ask
    w.set_global_hotkey("replay_hotkey", "ctrl+alt+t")
    assert len(toasts) == 1                                    # only when it goes on
    assert process_events(qapp, lambda: w.replay.running)
    cap = FakeCapture.made[-1]
    import os
    assert cap.pid == os.getpid() and cap.include_tree is False   # everything but us
    cap.sink(noise(1.0))
    n = len(w.cfg.sounds)
    w.on_hotkey("__replay__")
    assert len(w.cfg.sounds) == n + 1
    new = w.cfg.sounds[-1]
    assert new.name.startswith("Replay") and 0.9 < new.duration <= 1.05
    w.set_global_hotkey("replay_hotkey", "")
    assert not w.replay.enabled
    assert process_events(qapp, lambda: cap.stopped)


def test_instant_replay_with_nothing_heard_adds_nothing(window, qapp, monkeypatch):
    w = window
    monkeypatch.setattr(w.replay, "_capture_cls", FakeCapture)
    monkeypatch.setattr(rp.appaudio, "supported", lambda: (True, ""))
    w.set_global_hotkey("replay_hotkey", "ctrl+alt+r")
    process_events(qapp, lambda: w.replay.running)
    FakeCapture.made[-1].sink(np.zeros((SR, 2), np.float32))   # silence
    n = len(w.cfg.sounds)
    w.on_hotkey("__replay__")
    assert len(w.cfg.sounds) == n and "Nothing to save" in w.status.text()


def test_replay_keeps_only_the_last_seconds(qapp):
    r = rp.InstantReplay(seconds=2, capture_cls=FakeCapture)
    r._enabled = True   # (as if its capture were running)
    r._push(noise(1.0) * 0 + 0.5)
    r._push(noise(3.0))
    assert 0 < len(r.clip()) <= 2 * SR


def test_replay_buffer_is_freed_when_switched_off(qapp, monkeypatch):
    """A 120 s buffer is ~46 MB: none until it's on, none once it's off again, and a
    late chunk from the capture being stopped doesn't make a new one."""
    monkeypatch.setattr(rp.appaudio, "supported", lambda: (True, ""))
    r = rp.InstantReplay(seconds=120, capture_cls=FakeCapture)
    assert r._rec.replay is None
    r.set_enabled(True)
    r._push(noise(1.0))
    assert r._rec.replay is not None and len(r.clip())
    r.set_enabled(False)
    assert r._rec.replay is None and len(r.clip()) == 0
    r._push(noise(1.0))
    assert r._rec.replay is None
    r.set_enabled(True)                       # on again: a fresh buffer
    r._push(noise(1.0))
    assert r._rec.replay is not None
    r.stop()


def test_replay_says_why_when_windows_cant(qapp, monkeypatch):
    monkeypatch.setattr(rp.appaudio, "supported", lambda: (False, "needs Windows 11"))
    r = rp.InstantReplay(capture_cls=FakeCapture)
    r.set_enabled(True)
    assert r.error == "needs Windows 11" and not r.running


def test_replay_that_cant_start_backs_off(qapp, monkeypatch):
    """Each failed try can leave Windows' late answer behind: no retry every 3 s forever."""
    monkeypatch.setattr(rp.appaudio, "supported", lambda: (True, ""))
    r = rp.InstantReplay(capture_cls=FakeCapture)
    starts = []
    monkeypatch.setattr(r, "_start", lambda: starts.append(1))
    r._enabled = True
    for n in range(1, 6):
        r._on_started(None, "Windows didn't answer in time.")
        assert r._fails == n
        wait = r._next_try - time.monotonic()
        assert wait == pytest.approx(min(rp.MAX_BACKOFF_S, 3 * 2 ** (n - 1)), abs=0.5)
        r._check()
        assert not starts                     # still waiting
    r._next_try = 0.0
    r._check()
    assert starts                             # the wait is over: tries again
    r._on_started(FakeCapture(1, None), "")   # it worked: the next failure waits 3 s again
    assert r._fails == 0
    r.stop()
