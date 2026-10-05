"""Straight into my mic (soundboard.directmic + native/directmic/obmic.cpp).

The end-to-end tests run the real mic effect DLL in testhost.exe (built by
scripts/build_directmic.py --testhost), which loads it the way Windows' audio engine
does; they're skipped when it isn't built. Nothing touches the PC's audio devices.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from soundboard import directmic as dm
from test_mainwindow import window  # noqa: F401  (fixture)

BUILD = Path(__file__).resolve().parent.parent / "build" / "directmic"
HOST = BUILD / "testhost.exe"
DLL = BUILD / "obmic.dll"


@pytest.fixture
def ring_file(tmp_path):
    d = tmp_path / "OnionBoard" / "MicPlugin"
    d.mkdir(parents=True)
    p = d / "ring2.bin"
    p.write_bytes(dm.new_ring_bytes())
    return p


def noise(n: int, start: int = 0, level: float = 0.3) -> np.ndarray:
    """testhost's fake mic with mic_hz < 0: frame f is noise(f)."""
    z = (np.arange(start, start + n, dtype=np.uint64) * np.uint64(2654435761)) \
        & np.uint64(0xFFFFFFFF)
    z ^= z >> np.uint64(15)
    z = (z * np.uint64(2246822519)) & np.uint64(0xFFFFFFFF)
    z ^= z >> np.uint64(13)
    return (level * ((z & np.uint64(0xFFFF)).astype(np.float32) / 32768.0 - 1.0)).astype(np.float32)


# ---------------------------------------------------------------------- the ring

def test_ring_layout_matches_the_effect(ring_file):
    """The offsets obmic.cpp's RingHeader / Slot use."""
    assert dm.HEAD.fields["write_pos"][1] == 16 and dm.HEAD.fields["enabled"][1] == 32
    assert dm.HEAD.fields["mic_write_pos"][1] == 56 and dm.HEAD.fields["mic_tick"][1] == 72
    assert dm.HEAD.fields["effect_version"][1] == 80
    assert dm.SLOT.itemsize == 64 and dm.SLOT.fields["read_pos"][1] == 24
    assert dm.SLOT.fields["underruns"][1] == 36 and dm.SLOT.fields["blocks"][1] == 40
    src = (Path(__file__).resolve().parent.parent / "native" / "directmic"
           / "obmic.cpp").read_text()
    assert f"HEADER_BYTES = {dm.HEADER};" in src and f"SLOTS = {dm.SLOTS};" in src
    assert f"RING_VERSION = {dm.VERSION};" in src
    assert f"EFFECT_VERSION = {dm.EFFECT_VERSION};" in src
    w = dm.RingWriter(ring_file)
    try:
        assert len(ring_file.read_bytes()) == dm.FILE_BYTES
        h = w.h[0]
        assert h["rate"] == dm.RATE and h["capacity"] == dm.CAPACITY
        assert h["gain"] == 1.0 and h["mic_gain"] == 1.0 and h["mode"] == dm.MODE_REPLACE
        assert h["enabled"] == 0   # off until a stream starts
    finally:
        w.close()


def test_ring_write_wraps(ring_file):
    w = dm.RingWriter(ring_file)
    try:
        w.jump(dm.CAPACITY - 3)
        w.write(np.arange(1, 8, dtype=np.float32))
        assert w.write_pos == dm.CAPACITY + 4
        assert list(w.data[-3:]) == [1, 2, 3]
        assert list(w.data[:4]) == [4, 5, 6, 7]
        assert w.h[0]["board_tick"] > 0   # heartbeat
    finally:
        w.close()


def test_ring_reads_the_clean_mic_across_the_wrap(ring_file):
    w = dm.RingWriter(ring_file)
    try:
        w.mic[-2:] = [[1, 1], [2, 2]]
        w.mic[:3] = [[3, 3], [4, 4], [5, 5]]
        x = w.read_mic(dm.MIC_CAPACITY * 7 - 2, 5)
        assert x.shape == (5, 2) and list(x[:, 0]) == [1, 2, 3, 4, 5]
    finally:
        w.close()


def test_ring_rejects_other_versions(ring_file):
    raw = bytearray(ring_file.read_bytes())
    raw[4] = 9
    ring_file.write_bytes(bytes(raw))
    with pytest.raises(RuntimeError):
        dm.RingWriter(ring_file)


def test_make_ring_replaces_an_old_layout(tmp_path):
    p = tmp_path / "ring2.bin"
    assert dm.make_ring(p) and p.stat().st_size == dm.FILE_BYTES
    raw = bytearray(p.read_bytes())
    raw[100] = 7   # someone's data in it: a good file is left alone
    p.write_bytes(bytes(raw))
    assert dm.make_ring(p) and p.read_bytes()[100] == 7
    p.write_bytes(b"x" * 100)   # the wrong size / version: made afresh
    assert dm.make_ring(p)
    dm.RingWriter(p).close()
    assert not dm.make_ring(tmp_path / "no" / "such" / "dir" / "ring2.bin")


@pytest.mark.parametrize("values, expected", [
    ({}, ("wrap", 5)),                                    # nothing: a stream effect (SFX)
    ({5: "{S}"}, ("wrap", 5)),                            # wrap the driver's SFX
    ({7: "{E}", 1: "{E}"}, ("wrap", 5)),                  # modern driver (a G733): SFX
    ({1: "{L}"}, ("wrap", 1)),                            # only old-style effects: LFX
    ({1: "{L}", 2: "{G}"}, ("wrap", 1)),
    ({13: ["{X}"], 5: "{S}"}, ("composite", 13)),         # a list: join it
])
def test_pick_slot(values, expected):
    assert dm.pick_slot(values) == expected


@pytest.mark.parametrize("values, pid, expected", [
    ({5: "{S}"}, 5, "{S}"),
    ({1: "{L}"}, 5, "{L}"),             # SFX switches the old LFX off: run it inside
    ({1: "{L}", 7: "{E}"}, 5, ""),      # ...unless an EFX still runs it before us
    ({1: "{L}"}, 1, "{L}"),
    ({}, 5, ""),
])
def test_original_effect_kept(values, pid, expected):
    assert dm._original(values, pid) == expected


# ---------------------------------------------------------------------- the stream

def test_stream_keeps_time_without_the_effect(ring_file):
    """Nobody records the mic: the board renders at real-time speed by its own clock."""
    calls = []

    def cb(out, frames, t, status):
        out.fill(0.25)
        calls.append(frames)

    s = dm.DirectMicStream(cb, ring_file)
    s.start()
    try:
        assert s._ring.h[0]["enabled"] == 1
        time.sleep(0.5)
        assert not s.mic_live
    finally:
        s.close()
    made = sum(calls)
    assert 0.35 * dm.RATE < made < 0.65 * dm.RATE
    assert max(calls) <= dm.BLOCK


def _publish(w: dm.RingWriter, x: np.ndarray, rate: int = 48000):
    """Stand in for the effect: append clean mic (frames, 2)."""
    pos = w.mic_write_pos
    for i, frame in enumerate(x):
        w.mic[(pos + i) % dm.MIC_CAPACITY] = frame
    h = w.h[0]
    h["mic_rate"] = rate
    h["mic_write_pos"] = pos + len(x)
    h["mic_tick"] = dm._tick()


def test_stream_runs_on_the_clean_mic(ring_file):
    """Each stretch of clean mic in, the same stretch of output out, right away."""
    got, made = [], []

    def mic_cb(x, rate):
        got.append((x.copy(), rate))

    def cb(out, frames, t, status):
        out.fill(0.5)
        made.append(frames)

    s = dm.DirectMicStream(cb, ring_file, mic_callback=mic_cb)
    w = dm.RingWriter(ring_file)
    try:
        s.active = True   # no thread: pump by hand
        _publish(w, np.zeros((480, 2), np.float32))
        s.pump()          # the first block only finds where the mic is
        assert s.mic_live and not got
        x = np.stack([noise(441, 0), noise(441, 9)], 1)
        _publish(w, x, 44100)
        s.pump()   # a new rate: start over there
        _publish(w, x, 44100)
        s.pump()
        assert len(got) == 1 and np.array_equal(got[0][0], x) and got[0][1] == 44100
        assert sum(made) == 480   # 441 frames at 44.1 kHz = 480 at 48 kHz
        _publish(w, x[:100], 44100)
        s.pump()
        assert sum(made) == 480 + 108   # (the fraction carries over)
        assert s._ring.write_pos == sum(made)
    finally:
        w.close()
        s.close()


def test_direct_fifo_pads_once_then_keeps_up():
    from soundboard.engine import DirectFifo
    f = DirectFifo()
    assert f.read(480) is None
    f.write(np.ones((470, 2), np.float32))   # a resampler's start-up: 10 short
    x = f.read(480)
    assert (x[:10] == 0).all() and (x[10:] == 1).all()
    for _ in range(5):
        f.write(np.full((480, 2), 2, np.float32))
        assert (f.read(480) == 2).all()
    f.write(np.full((4000, 2), 3, np.float32))   # a pile-up: dropped to one read
    assert len(f.read(480)) == 480 and f.count == 0


# ---------------------------------------------------------------------- the real effect

needs_host = pytest.mark.skipif(not (HOST.is_file() and DLL.is_file()),
                                reason="run scripts/build_directmic.py --testhost")


def _run_host(ring_file, rate, ch, seconds, mic=0.0, instances=1, mic_hz=0.0,
              callback=None, mic_callback=None, mode=dm.MODE_ADD, during=None):
    """The board runs DirectMicStream (a 440 Hz tone at 0.5 unless `callback`) while the
    real effect runs in testhost on `instances` apps at `rate` / `ch`. Returns each
    app's output (frames, ch), testhost's stdout and the stream's stats."""
    phase = [0]

    def tone(out, frames, t, status):
        n = np.arange(phase[0], phase[0] + frames)
        out[:] = (0.5 * np.sin(2 * np.pi * 440 * n / dm.RATE)).astype(np.float32)[:, None]
        phase[0] += frames

    s = dm.DirectMicStream(callback or tone, ring_file, mic_callback=mic_callback, mode=mode)
    s.start()
    out = ring_file.parent / "out.f32"
    env = dict(os.environ, ProgramData=str(ring_file.parent.parent.parent))
    stats = {}
    try:
        p = subprocess.Popen([str(HOST), str(DLL), str(out), str(rate), str(ch), str(seconds),
                              str(mic), str(instances), str(mic_hz)], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if during is not None:
            during(s)
        time.sleep(min(1.0, seconds / 2))
        stats = {"apps": s.apps(), "late": s.late(), "alive": s.effect_alive(),
                 "mic_live": s.mic_live}
        stdout, _ = p.communicate(timeout=seconds + 20)
    finally:
        s.close()
    assert p.returncode == 0, stdout
    outs = [np.fromfile(out if n == 0 else f"{out}.{n}", np.float32).reshape(-1, ch)
            for n in range(instances)]
    return outs, stdout, stats


def _block_rms(y, rate):
    b = rate // 100
    return np.sqrt((y[: len(y) // b * b].reshape(-1, b) ** 2).mean(axis=1))


@needs_host
@pytest.mark.parametrize("rate, ch", [(48000, 2), (44100, 1), (16000, 4)])
def test_effect_adds_the_board_to_the_mic(ring_file, rate, ch):
    (x,), log, stats = _run_host(ring_file, rate, ch, 2.0)
    assert "float format supported: 0x00000000" in log
    assert stats["alive"] and stats["apps"] == 1 and stats["mic_live"]
    assert np.all(np.isfinite(x)) and np.abs(x).max() <= 1.0
    assert np.allclose(x[:, 0:1], x)   # every channel gets it
    y = x[int(0.3 * rate):, 0]           # after it settled
    rms = _block_rms(y, rate)
    # a steady 0.5 sine is 0.354 rms: no block dropped out or doubled up
    assert rms.min() > 0.3 and rms.max() < 0.4, (rms.min(), rms.max())
    spec = np.abs(np.fft.rfft(y * np.hanning(len(y))))
    freqs = np.fft.rfftfreq(len(y), 1 / rate)
    assert abs(freqs[spec.argmax()] - 440) < 3
    # clean: everything away from the tone is far below it (no clicks or gaps)
    assert spec[np.abs(freqs - 440) > 40].max() < spec.max() * 0.01


@needs_host
def test_effect_keeps_the_mic_in_add_mode(ring_file):
    (x,), _, _ = _run_host(ring_file, 48000, 2, 1.0, mic=0.1)
    y = x[int(0.3 * 48000):, 0]
    assert abs(y.mean() - 0.1) < 0.01   # the mic (a constant here) is still in there
    assert y.max() > 0.55               # ...with the tone on top


@needs_host
def test_add_mode_mic_gain_mutes_the_mic_only(ring_file):
    def during(s):
        s.set_mic_gain(0.0)

    (x,), _, _ = _run_host(ring_file, 48000, 1, 1.0, mic=0.1, during=during)
    y = x[int(0.4 * 48000):, 0]
    assert abs(y.mean()) < 0.01 and y.max() > 0.45   # the tone without the mic


@needs_host
def test_effect_leaves_the_mic_alone_when_the_board_is_off(ring_file):
    w = dm.RingWriter(ring_file)
    w.close()   # never enabled: the effect must leave the mic alone
    out = ring_file.parent / "out.f32"
    env = dict(os.environ, ProgramData=str(ring_file.parent.parent.parent))
    r = subprocess.run([str(HOST), str(DLL), str(out), "48000", "2", "0.5", "0.2"], env=env,
                       capture_output=True, text=True, timeout=20)
    assert r.returncode == 0
    assert np.allclose(np.fromfile(out, np.float32), 0.2)


class Echo:
    """A board in replace mode whose send mix is its (clean) mic, gain `gain`, plus
    `tone` if set; mic blocks it got are kept in `blocks`."""

    def __init__(self, gain=1.0, tone=0.0):
        self.gain, self.tone = gain, tone
        self.pending = np.zeros(0, np.float32)
        self.lock = threading.Lock()
        self.blocks = []
        self.phase = 0

    def mic(self, x, rate):
        assert rate == dm.RATE
        self.blocks.append(len(x))
        with self.lock:
            self.pending = np.concatenate([self.pending, x[:, 0]])

    def __call__(self, out, frames, t, status):
        with self.lock:
            k = min(frames, len(self.pending))
            out.fill(0)
            out[:k, 0] = self.pending[:k] * self.gain
            self.pending = self.pending[k:]
        if self.tone:
            n = np.arange(self.phase, self.phase + frames)
            out[:, 0] += self.tone * np.sin(2 * np.pi * 440 * n / dm.RATE).astype(np.float32)
            self.phase += frames
        out[:, 1] = out[:, 0]


def _delay(y, rate, start_s=0.6, span_s=1.0, level=0.3):
    """Frames by which output y lags the fake noise mic (at the end of the span), and
    the share of 10 ms blocks in the span that are exactly it, that late."""
    a, n = int(start_s * rate), int(span_s * rate)
    seg = y[a:a + n]
    tail = slice(n - rate // 5, n)
    lags = range(0, int(0.1 * rate))
    best = max(lags, key=lambda lag: float(np.dot(seg[tail], noise(n, a - lag, level)[tail])))
    err = np.abs(seg - noise(n, a - best, level))
    b = rate // 100
    return best, float((err[: n // b * b].reshape(-1, b).max(axis=1) < 1e-4).mean())


@needs_host
@pytest.mark.parametrize("instances", [1, 3])
def test_replace_mode_sends_the_boards_voice_soon(ring_file, instances):
    """Replace mode: what comes out of the mic is the board's send mix (here its own
    clean mic, halved), sample for sample, about LEAD_S later, for every app."""
    board = Echo(gain=0.5)
    outs, _, stats = _run_host(ring_file, 48000, 1, 2.5, mic=0.3, instances=instances,
                               mic_hz=-1, callback=board, mic_callback=board.mic,
                               mode=dm.MODE_REPLACE)
    # (a loaded test PC can make the board late now and then: the mic fades in for
    # that moment, and the effect reads a little further behind from then on)
    assert stats["apps"] == instances and stats["late"] <= 3 * instances   # (summed per app)
    assert 230 < len(board.blocks) <= 250   # the clean mic: each 10 ms block, once
    lags = []
    for x in outs:
        lag, exact = _delay(x[:, 0], 48000, level=0.15)
        assert lag <= 0.05 * 48000, lag / 48             # under 50 ms
        assert exact > 0.9, exact                        # exact: not a trace of the mic
        lags.append(lag)
    # every app hears it at about the same time (each starts reading on its own block)
    assert max(lags) - min(lags) <= 480 + 48 * 5


@needs_host
def test_replace_mode_falls_back_to_the_mic_when_the_board_stops(ring_file):
    board = Echo(gain=0.0, tone=0.4)   # the board sends only a tone

    def during(s):
        time.sleep(0.8)
        s.close()   # the board quits mid-way

    (x,), _, _ = _run_host(ring_file, 48000, 1, 2.0, mic=0.3, mic_hz=-1, callback=board,
                           mic_callback=board.mic, mode=dm.MODE_REPLACE, during=during)
    y = x[:, 0]
    mid = y[int(0.4 * 48000):int(0.7 * 48000)]
    t = np.arange(int(0.4 * 48000), int(0.7 * 48000))
    tone = 0.4 * np.sin(2 * np.pi * 440 * t / 48000)
    assert np.corrcoef(mid, tone)[0, 1] > 0.99 or np.abs(mid).max() > 0.35   # the board's
    end = y[int(1.4 * 48000):]
    assert np.abs(end - noise(len(end), int(1.4 * 48000))).max() < 1e-6   # the mic again
    rms = _block_rms(y[int(0.3 * 48000):], 48000)
    assert rms.min() > 0.1, np.round(rms[rms.argmin() - 4:rms.argmin() + 4], 3)   # no gap


@needs_host
def test_effect_survives_a_hostile_ring(ring_file):
    """Anyone signed in can write the ring: NaN, huge values and nonsense header
    fields must not crash the audio engine or put garbage on the mic."""
    def evil(out, frames, t, status):
        out[:] = np.float32(np.nan)
        out[::7] = np.float32(1e30)

    def during(s):
        h = s._ring.h[0]
        for _ in range(30):
            h["gain"] = np.float32(np.inf)
            h["mic_gain"] = np.float32(-5)
            h["lead"] = 0xFFFFFFFF
            h["mode"] = 77
            h["publisher"] = 12345
            h["capacity"] = 3          # (read once, when the effect opened the ring)
            time.sleep(0.02)

    (x,), _, _ = _run_host(ring_file, 48000, 2, 1.0, mic=0.1, callback=evil, during=during)
    assert np.all(np.isfinite(x)) and np.abs(x).max() <= 1.0


@needs_host
def test_more_apps_than_slots(ring_file):
    """Past SLOTS apps the rest still get the mic (and the sounds, from no slot)."""
    outs, _, stats = _run_host(ring_file, 48000, 1, 1.0, instances=dm.SLOTS + 2)
    assert stats["apps"] == dm.SLOTS
    for x in outs:
        assert np.all(np.isfinite(x)) and np.abs(x[int(0.4 * 48000):, 0]).max() > 0.4


# ---------------------------------------------------------------------- the engine

def test_engine_runs_on_the_clean_mic(ring_file, monkeypatch):
    """Route "mic": the board's mic is the clean mic the effect hands over (the
    board's own mic stream carries its sounds by then, so it's ignored), and in
    replace mode the send mix carries the processed voice."""
    from soundboard.engine import Engine
    monkeypatch.setattr(dm, "ring_path", lambda: ring_file)
    e = Engine()
    e.set_main_device(dm.DEVICE)
    s = e.main_stream
    try:
        assert e.main_direct and isinstance(s, dm.DirectMicStream)
        assert "main" not in e.errors and e.rates["main"] == dm.RATE
        s.stop()   # pump by hand from here
        s.active = True
        w = dm.RingWriter(ring_file)
        _publish(w, np.zeros((480, 2), np.float32))
        s.pump()
        e.mic_vol = 0.5
        voice = np.full((480, 2), 0.2, np.float32)
        for _ in range(10):
            _publish(w, voice)
            s.pump()
            e._cb_mic(np.full((480, 1), 0.9, np.float32), 480, None, None)   # ignored
        assert abs(e.level_mic - 0.2) < 1e-6   # the clean mic, not the 0.9 block
        out = w.data[w.write_pos - 480:w.write_pos]
        assert np.allclose(out, 0.1, atol=1e-3)   # the voice at mic volume, mono
        e.mic_muted = True
        for _ in range(3):   # (the limiter looks a little ahead)
            _publish(w, voice)
            s.pump()
        assert np.abs(w.data[w.write_pos - 480:w.write_pos]).max() < 1e-6
        w.close()
    finally:
        e.shutdown()


def test_engine_add_mode_leaves_the_voice_to_the_effect(ring_file, monkeypatch):
    from soundboard.engine import Engine
    monkeypatch.setattr(dm, "ring_path", lambda: ring_file)
    e = Engine()
    e.direct_mode = dm.MODE_ADD
    e.set_main_device(dm.DEVICE)
    s = e.main_stream
    try:
        s.stop()
        s.active = True
        w = dm.RingWriter(ring_file)
        _publish(w, np.zeros((480, 2), np.float32))
        s.pump()
        e.mic_vol = 0.7
        for _ in range(5):
            _publish(w, np.full((480, 2), 0.2, np.float32))
            s.pump()
        assert np.abs(w.data[:w.write_pos]).max() < 1e-6   # no voice in the ring
        assert abs(w.h[0]["mic_gain"] - 0.7) < 1e-6        # the effect keeps it, at 70%
        e.sending = False
        _publish(w, np.full((480, 2), 0.2, np.float32))
        s.pump()
        assert w.h[0]["mic_gain"] == 0.0
        w.close()
    finally:
        e.shutdown()


def test_engine_reports_a_missing_effect(tmp_path, monkeypatch):
    from soundboard.engine import Engine
    monkeypatch.setattr(dm, "ring_path", lambda: tmp_path / "nope" / "ring2.bin")
    e = Engine()
    e.set_main_device(dm.DEVICE)
    assert e.main_stream is None and "attached" in e.errors["main"]


# ---------------------------------------------------------------------- set-up states

def test_new_users_go_straight_into_their_mic_old_settings_keep_the_cable(app_dir):
    from soundboard import library
    assert library.Config.load().route == "mic"   # no settings yet: a first start
    assert library.Config().route == "cable"
    assert library.Config.from_raw({"version": 4}).route == "cable"   # saved before routes
    assert library.Config.from_raw({"version": 4, "route": "mic"}).route == "mic"
    assert library.Config.from_raw({"version": 4, "route": "device"}).route == "device"


@pytest.mark.parametrize("on, here, in_place, same, expected", [
    ([], True, True, True, "missing"),
    (["{b}"], True, True, True, "other"),
    (["{a}"], True, False, True, "wiped"),       # a driver update took it off
    (["{a}"], True, True, False, "outdated"),    # an older copy of the effect
    (["{a}"], True, True, True, "ready"),
])
def test_status(monkeypatch, tmp_path, on, here, in_place, same, expected):
    monkeypatch.setattr(dm, "installed_on", lambda: on)
    monkeypatch.setattr(dm, "endpoint_for", lambda name: "{a}")
    monkeypatch.setattr(dm, "effect_in_place", lambda guid: in_place)
    monkeypatch.setattr(dm, "same_dll", lambda a, b: same)
    monkeypatch.setattr(dm, "registered_dll", lambda: None)
    monkeypatch.setattr(dm, "make_ring", lambda path=None: True)
    dm.forget_status()
    assert dm.status("My mic") == expected
    assert dm.needs_repair(expected) == (expected in ("wiped", "outdated"))


def test_same_dll(tmp_path):
    a, b, c = tmp_path / "a.dll", tmp_path / "b.dll", tmp_path / "c.dll"
    a.write_bytes(b"one")
    b.write_bytes(b"one")
    c.write_bytes(b"two")
    assert dm.same_dll(a, b) and not dm.same_dll(a, c)
    assert not dm.same_dll(None, b) and not dm.same_dll(tmp_path / "gone.dll", b)
    assert dm.same_dll(a, tmp_path / "none-of-ours.dll")   # a build without one: fine


def test_uninstaller_asks_nothing_when_nothing_is_installed(monkeypatch):
    monkeypatch.setattr(dm, "anything_installed", lambda: False)
    assert dm.cli(["remove"]) == 0   # (_elevated would raise: the conftest guard)


def test_uninstaller_takes_it_off_the_mic(monkeypatch):
    asked = []
    monkeypatch.setattr(dm, "anything_installed", lambda: True)
    monkeypatch.setattr(dm, "_is_admin", lambda: False)
    monkeypatch.setattr(dm, "_elevated", lambda args, wait_s=90.0: asked.append(args) or 0)
    assert dm.cli(["remove"]) == 0 and asked == [["uninstall"]]
    monkeypatch.setattr(dm, "_elevated", lambda args, wait_s=90.0: None)   # turned down
    assert dm.cli(["remove"]) == 1


def test_cli_refuses_odd_arguments():
    assert dm.cli(["install", "not-a-guid"]) == 2
    assert dm.cli(["install", "{00000000-0000-0000-0000-000000000000}", "efx"]) == 2
    assert dm.cli(["frobnicate"]) == 2


def test_who_is_listening_looks_at_the_mic_itself(window, monkeypatch):  # noqa: F811
    """The simple sound modes find Discord / the game by who records the voice
    device: with straight into my mic that's the real mic, not the cable."""
    w = window
    w.cfg.route = "mic"
    w.cfg.mic_device = "Microphone (Test Headset)"
    monkeypatch.setattr(w.engine, "direct_stream", lambda: object())
    from soundboard import engine as eng
    monkeypatch.setattr(eng, "virtual_outputs", lambda: [])
    assert w._heard_device() == ("Microphone (Test Headset)",)
    monkeypatch.setattr(eng, "virtual_outputs", lambda: ["CABLE Input (VB-Audio Virtual Cable)"])
    # a voice app still set to the cable counts too
    assert w._heard_device() == ("Microphone (Test Headset)",
                                 "CABLE Output (VB-Audio Virtual Cable)")
    monkeypatch.setattr(w.engine, "direct_stream", lambda: None)
    assert w._heard_device() is None   # not sending into it: nobody hears the board there
    w.cfg.route = "cable"
    monkeypatch.setattr(dm, "status", lambda name=None: "missing")
    assert w._heard_device() != "Microphone (Test Headset)"


def test_listeners_look_at_every_device_given():
    from soundboard import voicesdk

    class A:
        def __init__(self, exe):
            self.exe, self.path, self.name = exe, "", exe
    seen = {"Mic": [A("Discord.exe")], "CABLE Output": [A("chrome.exe")]}
    lis = voicesdk.Listeners(lister=lambda d: seen.get(d, []), scanner=lambda p: None)
    both = lis.look(("Mic", "CABLE Output"))
    assert both == (voicesdk.VOICE_APPS["discord.exe"], voicesdk.VOICE_APPS["chrome.exe"])
    assert lis.look("Mic") == lis.look(("Mic",)) == (voicesdk.VOICE_APPS["discord.exe"],)
