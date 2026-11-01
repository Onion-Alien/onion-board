"""A slow effects render (a song said in an AI voice took minutes): it shows how far it
is on the pad and in the Edit window, the window can be closed while it goes on, ✕
stops it with the old effects back, and the render itself runs outside the app's
process (renderworker) so it can't stutter the audio or lag the window."""
import threading
import time

import numpy as np
import pytest
from conftest import process_events
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from test_mainwindow import window  # noqa: F401

from soundboard.sounds import library
from soundboard.audio import renderworker, soundfx
from soundboard.sounds.library import SR, SoundMeta
from soundboard.ui.window import editcontrol

VOICE = {"voice": {"name": "Bear", "ai": {"id": "bear", "name": "Bear", "pitch": 0.0}}}


class SlowRender:
    """Stands in for load_sound: says how far it is when told, and finishes (or sees
    the cancel) when told."""

    def __init__(self, monkeypatch):
        self.real = editcontrol.load_sound
        self.frac: list[float] = []      # progress to report, in order
        self.go = threading.Event()      # finish now
        self.cancelled: list[bool] = []
        self.running = threading.Event()
        monkeypatch.setattr(editcontrol, "load_sound", self)

    def __call__(self, meta, cancel=None, progress=None):
        if not soundfx.clean(meta.fx)["voice"]:
            return self.real(meta, cancel)
        self.running.set()
        end = time.monotonic() + 20
        while not self.go.is_set() and time.monotonic() < end:
            if cancel():
                self.cancelled.append(True)
                raise library.Cancelled
            if self.frac and progress is not None:
                progress(self.frac.pop(0))
            time.sleep(0.01)
        return self.real(SoundMeta(id=meta.id, name=meta.name, file=meta.file), None)


def _ready(qapp, w, sid="s0"):
    assert process_events(qapp, lambda: sid in w.audio, 10)
    return w.meta(sid)


def _toasts(w, monkeypatch):
    said = []
    monkeypatch.setattr(w, "toast", lambda text, *a, **k: said.append(text))
    return said


def test_the_pad_shows_how_far_a_render_is_and_says_why_it_cant_play(qapp, window,  # noqa: F811
                                                                      monkeypatch):
    w = window
    m = _ready(qapp, w)
    slow = SlowRender(monkeypatch)
    said = _toasts(w, monkeypatch)
    old = dict(m.fx)
    m.fx = dict(VOICE)
    w.editctl._rerender(m, old)
    p = w.pads["s0"]
    assert p.state == "rendering" and p.render_frac == 0.0 and p.can_stop
    slow.frac = [0.42]
    assert process_events(qapp, lambda: p.render_frac == pytest.approx(0.42), 5)
    assert w.editctl.render_words("s0").startswith("42%")
    assert "42%" in p.accessibleDescription()
    w.playctl.play("s0")   # pressed (or its hotkey) while it renders
    assert said and "can't play until its effects are applied (42%" in said[-1]
    slow.go.set()
    assert process_events(qapp, lambda: p.state == "ready", 10)
    assert p.render_frac is None and w.editctl.rendering("s0") is None
    assert soundfx.key(m.fx) == soundfx.key(VOICE)   # kept: it finished


def test_the_pads_x_stops_the_render_and_puts_the_old_effects_back(qapp, window,  # noqa: F811
                                                                   monkeypatch):
    w = window
    m = _ready(qapp, w)
    before = w.audio["s0"]
    slow = SlowRender(monkeypatch)
    said = _toasts(w, monkeypatch)
    old = {"speed": 1.0}
    m.fx = dict(VOICE)
    w.editctl._rerender(m, old)
    assert slow.running.wait(5)
    w.show()
    p = w.pads["s0"]
    p.grab()   # painted: the ✕ is where it was drawn
    assert p._stop_rect is not None
    c = p._stop_rect.center()
    QTest.mouseClick(p, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(int(c.x()), int(c.y())))
    assert process_events(qapp, lambda: p.state == "ready" and slow.cancelled, 10)
    assert m.fx == old and w.audio["s0"] is before   # straight back, nothing re-rendered
    assert any("keeps its old effects" in t for t in said)
    assert not list((library.CACHE_DIR).glob("*.tmp.npy"))


def test_a_click_elsewhere_on_a_rendering_pad_says_it_cant_play_yet(qapp, window,  # noqa: F811
                                                                    monkeypatch):
    w = window
    m = _ready(qapp, w)
    slow = SlowRender(monkeypatch)
    said = _toasts(w, monkeypatch)
    m.fx = dict(VOICE)
    w.editctl._rerender(m, {})
    w.show()
    p = w.pads["s0"]
    p.grab()
    QTest.mouseClick(p, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(p.width() // 2, p.height() // 3))
    assert said and "can't play until" in said[-1]
    assert w.editctl.rendering("s0") is not None   # still going
    slow.go.set()
    assert process_events(qapp, lambda: p.state == "ready", 10)


def test_save_with_a_voice_keeps_the_edit_window_open_with_its_progress(qapp, window,  # noqa: F811
                                                                        monkeypatch):
    w = window
    m = _ready(qapp, w)
    slow = SlowRender(monkeypatch)
    monkeypatch.setattr(editcontrol, "DONE_TOAST_S", 0.0)
    said = _toasts(w, monkeypatch)
    d = w.editctl.edit("s0", "effects")
    monkeypatch.setattr(d.effects, "fx", lambda: dict(VOICE))
    d.accept()   # Save
    assert d.isVisible() and d.render_shown()            # stays open, showing the render
    assert soundfx.key(m.fx) == soundfx.key(VOICE)        # saved straight away
    assert d._bb.isHidden() and not d.simple.isEnabled()
    slow.frac = [0.5]
    assert process_events(qapp, lambda: d.render_bar.value() == 500, 5)
    assert "50%" in d.render_words.text()
    slow.go.set()
    assert process_events(qapp, lambda: not d.isVisible(), 10)   # done: it closes itself
    assert w.pads["s0"].state == "ready" and soundfx.key(m.fx) == soundfx.key(VOICE)
    assert any("ready to play" in t for t in said)


def test_closing_the_edit_window_lets_the_render_go_on(qapp, window, monkeypatch):  # noqa: F811
    w = window
    m = _ready(qapp, w)
    slow = SlowRender(monkeypatch)
    d = w.editctl.edit("s0", "effects")
    monkeypatch.setattr(d.effects, "fx", lambda: dict(VOICE))
    d.accept()
    d.render_close.click()
    assert not d.isVisible()
    assert w.pads["s0"].state == "rendering" and w.editctl.rendering("s0") is not None
    slow.frac = [0.3]
    assert process_events(qapp, lambda: w.pads["s0"].render_frac == pytest.approx(0.3), 5)
    d2 = w.editctl.edit("s0", "effects")   # opened again: it shows the render still going
    assert d2.render_shown() and "30%" in d2.render_words.text()
    slow.go.set()
    assert process_events(qapp, lambda: w.pads["s0"].state == "ready", 10)
    assert soundfx.key(m.fx) == soundfx.key(VOICE) and not slow.cancelled


def test_the_edit_windows_x_stops_it_and_goes_back_to_editing(qapp, window,  # noqa: F811
                                                             monkeypatch):
    w = window
    m = _ready(qapp, w)
    slow = SlowRender(monkeypatch)
    old = dict(m.fx)
    d = w.editctl.edit("s0", "effects")
    monkeypatch.setattr(d.effects, "fx", lambda: dict(VOICE))
    d.accept()
    assert slow.running.wait(5)
    d.render_stop.click()
    assert d.isVisible() and not d.render_shown()          # back to the draft
    assert not d._bb.isHidden() and d.simple.isEnabled()
    assert m.fx == old
    assert process_events(qapp, lambda: w.pads["s0"].state == "ready" and slow.cancelled, 10)
    d.reject()


def test_progress_is_split_between_the_ai_voice_and_the_rest(monkeypatch):
    from soundboard.speech import soundvoice
    seen = []

    def fake(mono, rate, vid, pitch=0.0, progress=None, **_k):
        for k in (0.25, 0.5, 1.0):
            progress(k)
        return mono
    monkeypatch.setattr(soundvoice, "render", fake)
    x = np.full((SR * 20, 2), 0.2, np.float32)
    parts = []
    soundfx.render_into(x, {**VOICE, "pitch": 3.0}, parts.clear, parts.append,
                        progress=seen.append)
    share = soundfx.AI_COST / (soundfx.AI_COST + soundfx.FX_COST)
    assert seen[:3] == pytest.approx([share * 0.25, share * 0.5, share])
    assert seen == sorted(seen) and seen[-1] == pytest.approx(1.0)


def test_a_cancelled_ai_voice_isnt_logged_as_left_out(monkeypatch, caplog):
    from soundboard.speech import soundvoice

    def stopped(*_a, **_k):
        raise soundvoice.Unavailable("stopped")
    monkeypatch.setattr(soundvoice, "render", stopped)
    x = np.full((4800, 2), 0.4, np.float32)
    soundfx._say(x, VOICE["voice"], cancel=lambda: True)
    assert "left out" not in caplog.text


def test_a_slow_render_runs_in_its_own_process_and_stops_when_asked(app_dir, monkeypatch):
    """The helper process writes the same cache file render_cached would (the app only
    maps it), and a cancel stops it with nothing left behind."""
    import soundfile as sf
    monkeypatch.setenv("APPDATA", str(app_dir))   # the helper never sees the real one
    f = app_dir / "tone.wav"
    t = np.arange(SR * 2) / SR
    sf.write(f, np.stack([np.sin(2 * np.pi * 330 * t)] * 2, 1) * 0.3, SR)
    m = SoundMeta(id="rw1", name="Tone", file=str(f), duration=2.0, fx={"pitch": 4.0})
    seen = []
    renderworker.render(m, lambda: False, seen.append)
    out = library.load_cached(m.id, soundfx.key(m.fx))
    assert out is not None and len(out) > SR
    want = library.render_cached("rw2", library.load_original(m), m.fx)
    assert np.array_equal(np.asarray(out), np.asarray(want))
    # stopped partway: Cancelled, and no file of it (whole or half) is kept
    long = app_dir / "long.wav"
    t = np.arange(SR * 30) / SR
    sf.write(long, np.stack([np.sin(2 * np.pi * 330 * t)] * 2, 1) * 0.3, SR)
    m2 = SoundMeta(id="rw3", name="Long", file=str(long), duration=30.0, fx={"speed": 0.7})
    began = []
    with pytest.raises(library.Cancelled):
        renderworker.render(m2, lambda: bool(began), began.append)
    assert began and not [p for p in library.CACHE_DIR.glob("rw3.*") if p.name != "rw3.npy"]


def test_the_app_renders_a_voice_in_the_helper_not_on_its_own_threads(qapp, window,  # noqa: F811
                                                                      monkeypatch):
    """The lag fix: with the helper on, the app's process does none of the rendering
    (render_cached on one of its threads took the GIL from the audio for minutes)."""
    w = window
    m = _ready(qapp, w)
    calls = []

    def helper(meta, cancel, progress=None):   # renders "elsewhere": writes the file
        calls.append(meta.id)
        progress(0.5)
        library.render_cached(meta.id, library.load_original(meta), {"pitch": 2.0})
        key = soundfx.key({"pitch": 2.0})
        src = library.cache_path(meta.id, key)
        src.replace(library.cache_path(meta.id, soundfx.key(meta.fx)))
    in_app = []
    monkeypatch.setattr(renderworker, "enabled", True)
    monkeypatch.setattr(renderworker, "render", helper)
    monkeypatch.setattr(editcontrol, "load_sound",
                        lambda *a, **k: in_app.append(1) or library.load_sound(*a, **k))
    m.fx = dict(VOICE)
    w.editctl._rerender(m, {})
    assert process_events(qapp, lambda: w.pads["s0"].state == "ready", 10)
    assert calls == ["s0"] and not in_app
