"""Regression tests for audio-path fixes: low-cut makeup only where the cut is,
progress of a voice whose first output is done, the ring overrun, live effects
fading out, COM init ownership, and cable fixing trying every end."""
from types import SimpleNamespace

import numpy as np
import pytest

from soundboard import appaudio, cableformat, livefx
from soundboard.destination import Dest
from soundboard.engine import CH, SR, Engine, Ring, Voice


class FakeStream:
    def stop(self):
        pass

    def close(self):
        pass


def tone(seconds=0.5):
    t = np.arange(int(seconds * SR)) / SR
    return np.stack([np.sin(2 * np.pi * 440 * t)] * 2, 1).astype(np.float32) * 0.5


def engine_with(*outs):
    e = Engine()
    e.send_mono = e.limiter_on = False
    for o in outs:
        setattr(e, f"{o}_stream", FakeStream())
        e.names[o] = f"fake {o}"
    return e


# ----------------------------------------------------------------- low-cut makeup

def _obs_out(dest):
    e = engine_with("obs")
    e.dest = dest
    v = e.play("a", tone(1.0) * 0.4, 1.0, loop=True)
    v.cut_share = {80: 0.75}           # makeup x2 while an 80 Hz cut is on
    out = np.zeros((480, CH), np.float32)
    for _ in range(5):
        e._obs(out, 480)
    return out.copy()


def test_stream_output_gets_no_makeup_without_the_cut():
    plain = _obs_out(None)
    cut = _obs_out(Dest("t", "t", lowcut=80))
    assert np.abs(plain).max() > 0.1
    assert np.allclose(plain, cut)     # the stream output never runs _dest


def test_hear_my_voice_preview_gets_no_makeup():
    def run(dest):
        e = engine_with("mon")
        e.dest = dest
        v = e.play("a", tone(1.0) * 0.4, 1.0, loop=True, preview=True)
        v.cut_share = {80: 0.75}
        out = np.zeros((480, CH), np.float32)
        for _ in range(5):
            e._mon_voice(out, 480)
        return out.copy()
    assert np.allclose(run(None), run(Dest("t", "t", lowcut=80)))


def test_sends_still_get_the_makeup():
    e = engine_with("main")
    e.dest = Dest("t", "t", lowcut=80)
    v = e.play("a", tone(1.0) * 0.2, 1.0, loop=True)
    v.cut_share = {80: 0.75}
    with_makeup = np.abs(e._render("main", 480)).max()
    v.pos["main"] = 0
    e._render("main", 480, makeup=False)   # the gain glides to the new one over a block
    v.pos["main"] = 0
    without = np.abs(e._render("main", 480, makeup=False)).max()
    assert with_makeup > 1.5 * without


# ----------------------------------------------------------------- progress

def test_progress_ignores_a_done_output():
    d = np.zeros((1000, CH), np.int16)
    v = Voice("a", {"main": d, "mon": d.copy()}, 1.0, False)
    v.pos = {"main": 900, "mon": 100}
    v.done.add("main")                 # its pos is frozen there
    assert abs(v.progress() - 0.1) < 1e-9
    v.seek(0.5)
    v.seek_to.pop("mon")               # the live output took its seek; main never will
    v.pos["mon"] = 500
    assert abs(v.progress() - 0.5) < 1e-9
    v.done.add("mon")                  # all done: still answers
    assert 0.0 <= v.progress() <= 1.0


# ----------------------------------------------------------------- ring overrun

def _counter(start, n):
    x = np.zeros((n, CH), np.float32)
    x[:, 0] = np.arange(start, start + n)
    return x


def test_ring_overrun_keeps_the_newest_prefill_frames():
    r = Ring(rate=SR, prefill_s=0.1, max_s=0.6)
    assert (r.cap, r.prefill) == (57600, 4800)
    r.write(_counter(0, 10000))
    r.write(_counter(10000, 50000))    # overwrites unread frames
    assert r.count == r.prefill
    assert r.buf[r.r, 0] == 60000 - 4800
    assert r.buf[(r.r + r.count - 1) % r.cap, 0] == 59999


# ----------------------------------------------------------------- live fx fade-out

def _tone(hz=300.0, seconds=1.0):
    t = np.arange(int(48000 * seconds)) / 48000
    x = (0.3 * np.sin(2 * np.pi * hz * t)).astype(np.float32)
    return np.stack([x, x], axis=1)


def test_effects_fade_out_instead_of_dropping():
    for key in ("crunch", "echo", "reverb"):
        f = livefx.LiveFx(48000)
        x = _tone()
        for i in range(0, 24000, 512):
            f.process(x[i:i + 512], {key: 0.8})
        blk = x[24000:24512]
        y = f.process(blk, {})
        assert not np.allclose(y[:16], blk[:16]), key    # still wet at the start
        assert not f.idle, key                           # halfway through the fade
        blk = x[24512:25024]
        y = f.process(blk, {})                           # FADE (1024) reached
        assert np.allclose(y[-1], blk[-1]), key          # dry at the end of it
        assert f.idle, key                               # and dropped
        blk = x[25024:25536]
        assert np.array_equal(f.process(blk, {}), blk), key


def test_effect_fade_has_no_jump():
    f = livefx.LiveFx(48000)
    x = _tone()
    ys = [f.process(x[i:i + 64], {"echo": 1.0}) for i in range(0, 24000, 64)]
    ys += [f.process(x[i:i + 64], {}) for i in range(24000, 26048, 64)]
    y = np.concatenate(ys)[:, 0]
    dry = x[:len(y), 0]
    jump = np.abs(np.diff(y[23990:26048] - dry[23990:26048])).max()
    assert jump < 0.05


# ----------------------------------------------------------------- COM init

@pytest.mark.windows   # COM
def test_co_init_owns_s_false_but_not_changed_mode(monkeypatch):
    for hr, own in ((0, True), (1, True), (appaudio.RPC_E_CHANGED_MODE, False)):
        monkeypatch.setattr(appaudio, "_ole32",
                            SimpleNamespace(CoInitializeEx=lambda *_a, hr=hr: hr))
        assert appaudio._co_init() is own


# ----------------------------------------------------------------- cable fix

def test_fix_tries_every_end(monkeypatch):
    tried = []

    def set_rate(end, rate=cableformat.RATE):
        tried.append(end.name)
        return end.name != "a"

    monkeypatch.setattr(cableformat, "set_rate", set_rate)
    ends = [cableformat.CableEnd(n, "render", n, 44100, 16, 2) for n in "abc"]
    assert cableformat.fix(ends) is False
    assert tried == ["a", "b", "c"]
