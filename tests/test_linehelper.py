"""The computer voice's lines render in a helper process (voicefx.linehelper), so a line
can't fight the audio callbacks for the GIL, and what it can't do renders in the app."""
from __future__ import annotations

import time
from types import SimpleNamespace

import numpy as np
import pytest

from soundboard import voicefx
from soundboard.speech.live import SpeechController
from soundboard.voicefx import VoiceChain, linehelper

RATE = 48000
SPEC = {"echo": {"on": True}, "reverb": {"on": True, "mix": 0.3}}


def line(seconds=0.5):
    t = np.arange(int(seconds * RATE)) / RATE
    return (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def chain(spec=SPEC) -> VoiceChain:
    c = VoiceChain()
    c.configure({"enabled": True, "effects": spec})
    return c


def ready(helper: linehelper.LineHelper, seconds=60.0):
    """The helper's running: its first line renders in the app, as a real first line does."""
    assert helper.render(SPEC, line(0.01), RATE) is None
    end = time.monotonic() + seconds
    while helper._conn is None:
        assert time.monotonic() < end, "the helper didn't start"
        time.sleep(0.05)


@pytest.fixture
def helper(monkeypatch):
    monkeypatch.setattr(linehelper, "enabled", True)
    h = linehelper.LineHelper()
    yield h
    h.close()


def test_a_line_from_the_helper_sounds_the_same_as_one_rendered_here(helper):
    ready(helper)
    x = line()
    y = helper.render(chain().render_effects(), x, RATE)
    assert y is not None
    assert np.array_equal(y, chain().render(x, RATE))
    assert not np.array_equal(y, x)


def test_the_helper_stays_for_the_next_line(helper):
    ready(helper)
    proc = helper._proc
    assert helper.render(SPEC, line(), RATE) is not None
    assert helper.render(SPEC, line(), RATE) is not None
    assert helper._proc is proc and proc is not None and proc.poll() is None


def test_a_helper_that_died_is_started_again(helper):
    ready(helper)
    proc = helper._proc
    assert proc is not None
    proc.kill()
    proc.wait(5)
    assert helper.render(SPEC, line(), RATE) is None   # this line renders in the app
    end = time.monotonic() + 60
    while helper.render(SPEC, line(0.01), RATE) is None:
        assert time.monotonic() < end, "it never came back"
        time.sleep(0.05)
    assert helper._proc is not proc


def test_closing_ends_the_helper(helper):
    ready(helper)
    proc = helper._proc
    assert proc is not None
    helper.close()
    assert proc.poll() is not None
    assert helper.render(SPEC, line(), RATE) is None


def test_off_in_tests_and_scripts(monkeypatch):
    monkeypatch.setattr(linehelper, "enabled", False)
    h = linehelper.LineHelper()
    assert h.render(SPEC, line(), RATE) is None
    assert h._conn is None and not h._starting


@pytest.mark.parametrize("etype", ["backdrop", "cat", "whistle"])
def test_effects_that_need_the_app_stay_in_the_app(etype):
    """The backdrop plays the app's loops; an effect with `prepare` fetches what it plays."""
    assert not linehelper.can_render({etype: {"on": True}})


def test_an_add_ons_effect_stays_in_the_app(monkeypatch):
    class Addon(voicefx.Effect):
        pass
    monkeypatch.setitem(voicefx.REGISTRY, "addon", Addon)
    assert not linehelper.can_render({"addon": {"on": True}})
    assert linehelper.can_render(SPEC)


def test_render_effects_are_what_render_runs():
    c = chain({"echo": {"on": True}, "reverb": {"on": False}, "extra_echo": {"on": True}})
    assert set(c.render_effects()) == {"echo", "extra_echo"}
    assert set(c.render_effects(top_only=True)) == {"extra_echo"}
    c.errors["echo"] = "failed"
    assert set(c.render_effects()) == {"extra_echo"}
    c.configure({"enabled": False, "effects": {"echo": {"on": True}}})
    assert not c.render_effects()


class Spy:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def render(self, effects, mono, rate, light):
        self.calls.append(set(effects))
        return self.answer

    def close(self):
        pass


def speech(spec=SPEC) -> SpeechController:
    return SpeechController(SimpleNamespace(), chain(spec), lambda ev: None, tts=SimpleNamespace())


def test_a_spoken_line_goes_to_the_helper():
    c = speech()
    done = np.ones(10, np.float32)
    c._lines = Spy(done)
    assert c._effects(line(), RATE) is done
    assert c._lines.calls == [set(SPEC)]


def test_a_spoken_line_renders_here_when_the_helper_cant():
    c = speech()
    c._lines = Spy(None)
    x = line()
    assert np.array_equal(c._effects(x, RATE), chain().render(x, RATE))


def test_no_effects_leave_a_line_alone():
    c = speech()
    c.voice_fx = False
    c._lines = Spy(np.zeros(1, np.float32))
    x = line()
    assert c._effects(x, RATE) is x
    assert not c._lines.calls
