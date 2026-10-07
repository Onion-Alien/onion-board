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


def test_a_second_board_backs_off(ring_file, monkeypatch):
    """Two copies of the app (one on a test profile) never both write the mic's ring:
    the second one says so, and takes over once the first one has gone."""
    first = dm.DirectMicStream(lambda out, *a: out.fill(0.5), ring_file)
    first.start()
    try:
        time.sleep(0.05)
        other = os.getpid() + 1
        monkeypatch.setattr(dm.os, "getpid", lambda: other)   # another process
        with pytest.raises(RuntimeError, match="Another Onion Board"):
            dm.DirectMicStream(lambda out, *a: out.fill(0.1), ring_file)
        w = dm.RingWriter(ring_file)
        assert w._get("enabled") == 1   # the first one's ring was left alone
        w.close(owner=False)
    finally:
        monkeypatch.undo()
        first.close()
    monkeypatch.setattr(dm.os, "getpid", lambda: other)
    second = dm.DirectMicStream(lambda out, *a: out.fill(0.1), ring_file)   # first gone
    second.close()
    # a board that crashed (its process is gone) doesn't block the next one
    w = dm.RingWriter(ring_file)
    w._set("board_pid", 0x7FFFFFF0)
    w.set_enabled(True)
    third = dm.DirectMicStream(lambda out, *a: out.fill(0.1), ring_file)
    third.close()
    w.close(owner=False)


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


# ---------------------------------------------------------------------- putting it on / off

class Killed(BaseException):
    """The admin step killed half-way (nothing after it runs)."""


class FakeReg:
    """The registry keys the admin step touches, {path: {name: (value, kind)}}; with
    `kill_at` set, the kill_at-th write never happens (the process died there)."""

    def __init__(self, keys=None):
        self.keys = {k.lower(): dict(v) for k, v in (keys or {}).items()}
        self.writes = 0
        self.kill_at = None

    def write(self):
        self.writes += 1
        if self.kill_at is not None and self.writes >= self.kill_at:
            raise Killed

    def key(self, path, create=True):
        reg, k = self, path.lower()

        class Key:
            created = k not in reg.keys
            if created and not create:
                raise FileNotFoundError(path)

            def __init__(self):
                if self.created:
                    reg.write()
                    reg.keys[k] = {}
                self.vals = reg.keys[k]

            def get(self, name):
                return self.vals.get(name)

            def set(self, name, kind, value):
                reg.write()
                self.vals[name] = (value, kind)

            def set_raw(self, name, kind, data):
                reg.write()
                value = (data.decode("utf-16-le").rstrip("\0") if kind == 2 else
                         int.from_bytes(data, "little") if kind == 11 else data)
                self.vals[name] = (value, kind)

            def delete(self, name):
                reg.write()
                self.vals.pop(name, None)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                pass

        return Key()

    def delete_key(self, root, path):
        self.write()
        self.keys.pop(path.lower(), None)

    def installed_on(self):
        top = dm.ENDPOINTS_KEY.lower() + "\\"
        return [k[len(top):] for k in self.keys if k.startswith(top)]

    def mics(self):
        """The mics' effect settings (an empty key counts as none)."""
        top = dm.CAPTURE_KEY.lower()
        return {k: v for k, v in self.keys.items() if k.startswith(top) and v}


@pytest.fixture
def fake_reg(monkeypatch):
    reg = FakeReg()
    monkeypatch.setattr(dm, "_BackupKey", lambda path, create=True: reg.key(path, create))
    monkeypatch.setattr(dm, "_StateKey", lambda path: reg.key(path))
    monkeypatch.setattr(dm, "installed_on", reg.installed_on)
    monkeypatch.setattr(dm.winreg, "DeleteKey", reg.delete_key)
    monkeypatch.setattr(dm, "_delete_if_empty",
                        lambda path: None if reg.keys.get(path.lower()) else
                        reg.keys.pop(path.lower(), None))
    return reg


GUID = "{11111111-2222-3333-4444-555555555555}"
FXKEY = rf"{dm.CAPTURE_KEY}\{GUID}\FxProperties"
SZ, MULTI, DWORD, BINARY, EXPAND, QWORD = 1, 7, 4, 3, 2, 11
MICS = {
    "no effects at all": None,
    "a stream effect": {dm.FX % 5: ("{S}", SZ), dm.MODES_KEY % 5: ([dm.MODE_DEFAULT], MULTI)},
    "a G733 (EFX + old LFX)": {dm.FX % 7: ("{E}", SZ), dm.FX % 1: ("{E}", SZ),
                               dm.MODES_KEY % 7: ([dm.MODE_DEFAULT], MULTI)},
    "old-style effects only": {dm.FX % 1: ("{L}", SZ), dm.FX % 2: ("{G}", SZ)},
    "a stream effect list": {dm.FX % 13: (["{X}", "{Y}"], MULTI), dm.FX % 5: ("{S}", SZ)},
    "enhancements off, odd kinds": {dm.DISABLE_SYSFX: (1, DWORD), dm.FX % 1: (b"\x01\x02", BINARY),
                                    dm.FX % 2: ("%x%\\{G}", EXPAND), dm.FX % 5: (7, QWORD)},
}


def _mic(reg, values):
    if values is not None:
        reg.keys[FXKEY.lower()] = dict(values)


def _all_ours(reg):
    return [n for v in reg.mics().values() for n, (x, _) in v.items() if dm._is_ours(x)]


@pytest.mark.parametrize("mic", MICS)
def test_taking_it_off_puts_the_mic_back_exactly(fake_reg, mic):
    _mic(fake_reg, MICS[mic])
    before = fake_reg.mics()
    dm._install_endpoint(GUID, None)
    assert _all_ours(fake_reg) and fake_reg.installed_on() == [GUID.lower()]
    dm._uninstall_endpoint(GUID)
    assert fake_reg.mics() == before and not fake_reg.installed_on()
    dm._install_endpoint(GUID, None)   # again (an update), via admin_install's way
    for guid in fake_reg.installed_on():
        dm._uninstall_endpoint(guid)
    dm._install_endpoint(GUID, None)
    dm._uninstall_endpoint(GUID)
    assert fake_reg.mics() == before


@pytest.mark.parametrize("mic", MICS)
def test_a_set_up_cut_off_anywhere_can_be_undone(fake_reg, mic):
    """The admin step killed at every write in turn: taking it off afterwards always
    leaves the mic exactly as it was (the notes are written before any change)."""
    _mic(fake_reg, MICS[mic])
    before = {k: dict(v) for k, v in fake_reg.keys.items()}
    dm._install_endpoint(GUID, None)
    total = fake_reg.writes
    for n in range(1, total + 1):
        fake_reg.keys = {k: dict(v) for k, v in before.items()}
        fake_reg.writes, fake_reg.kill_at = 0, n
        with pytest.raises(Killed):
            dm._install_endpoint(GUID, None)
        fake_reg.kill_at = None
        for guid in fake_reg.installed_on():
            dm._uninstall_endpoint(guid)
        assert fake_reg.mics() == {k: v for k, v in before.items() if v}, n
        assert not _all_ours(fake_reg) and not fake_reg.installed_on()


def test_repair_after_windows_reset_keeps_the_new_driver_effects(fake_reg):
    """A driver update / "Reset sound settings" rewrote the mic's effects: repairing and
    later taking it off leave the driver's new ones, not the stale ones from before."""
    _mic(fake_reg, MICS["a stream effect"])
    dm._install_endpoint(GUID, None)
    fake_reg.keys[FXKEY.lower()] = {dm.FX % 5: ("{NEW}", SZ)}   # Windows reset it
    for guid in fake_reg.installed_on():   # what admin_install does: repair
        dm._uninstall_endpoint(guid)
    assert fake_reg.mics()[FXKEY.lower()] == {dm.FX % 5: ("{NEW}", SZ)}
    dm._install_endpoint(GUID, None)
    assert fake_reg.keys[dm.ENDPOINTS_KEY.lower() + "\\" + GUID.lower()]["Original"][0] == "{NEW}"
    dm._uninstall_endpoint(GUID)
    assert fake_reg.mics()[FXKEY.lower()] == {dm.FX % 5: ("{NEW}", SZ)}


def test_lost_notes_never_leave_the_effect_behind(fake_reg):
    """Our notes gone (someone cleaned the registry) while the effect is on the mic: a
    new set-up doesn't note the effect itself as the mic's own, so taking it off never
    leaves a dead effect on the mic."""
    _mic(fake_reg, MICS["a stream effect"])
    dm._install_endpoint(GUID, None)
    fake_reg.keys.pop(dm.ENDPOINTS_KEY.lower() + "\\" + GUID.lower())
    dm._install_endpoint(GUID, None)
    notes = fake_reg.keys[dm.ENDPOINTS_KEY.lower() + "\\" + GUID.lower()]
    assert notes["Original"][0] == ""
    dm._uninstall_endpoint(GUID)
    assert not _all_ours(fake_reg)


def test_a_mic_that_is_gone_is_just_forgotten(fake_reg):
    _mic(fake_reg, MICS["a stream effect"])
    dm._install_endpoint(GUID, None)
    fake_reg.keys.pop(FXKEY.lower())   # the driver reinstalled: a new endpoint GUID
    dm._uninstall_endpoint(GUID)
    assert not fake_reg.installed_on()


def test_admin_step_brings_the_audio_back_whatever_happens(fake_reg, monkeypatch, tmp_path):
    """The audio service is stopped during the admin step: the helper that starts it
    again is running before it stops, and a failure still starts it."""
    calls = []
    dll = tmp_path / "obmic.dll"
    dll.write_bytes(b"dll")
    monkeypatch.setattr(dm, "bundled_dll", lambda: dll)
    monkeypatch.setattr(dm, "install_dir", lambda: tmp_path / "pf")
    monkeypatch.setattr(dm, "_enable_privileges", lambda *a: None)
    monkeypatch.setattr(dm, "_audio_comes_back", lambda: calls.append("helper"))
    monkeypatch.setattr(dm, "_audio_service", lambda start: calls.append(start))
    monkeypatch.setattr(dm, "_register_com", lambda path: calls.append("com"))
    monkeypatch.setattr(dm, "_make_ring", lambda: None)
    _mic(fake_reg, MICS["a stream effect"])
    assert dm.admin_install(GUID) == 0
    assert calls == ["helper", False, "com", True]
    calls.clear()
    fake_reg.kill_at = fake_reg.writes + 1
    with pytest.raises(Killed):
        dm.admin_install(GUID)
    assert calls[:2] == ["helper", False] and calls[-1] is True


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
    assert set(calls) == {dm.BLOCK}   # whole blocks, as a sound card's would come


def test_stream_sleeps_between_blocks_when_nobody_listens(ring_file):
    """Nobody records the mic: the thread wakes about once a block (10 ms), not every
    2 ms (that was 500 wakeups a second, a third of the board's CPU while idle)."""
    s = dm.DirectMicStream(lambda out, frames, t, status: out.fill(0), ring_file)
    wakes = []
    pump = s.pump
    s.pump = lambda: (wakes.append(1), pump())[1]
    s.start()
    try:
        time.sleep(1.0)
    finally:
        s.close()
    assert 50 <= len(wakes) <= 150, len(wakes)


def test_feed_looks_again_just_in_time(ring_file):
    """When the thread looks again: just before the next mic block when it takes the
    mic itself, just after it when the mic callback does (the thread is only the
    stand-in then), every 2 ms once a block is due, and never more than a block away."""
    s = dm.DirectMicStream(lambda out, frames, t, status: out.fill(0), ring_file)
    try:
        s.mic_live = True
        now = time.perf_counter()
        s._fed_at, s._fed_period, s._fed_here = now, dm.BLOCK_S, True
        assert dm.BLOCK_S - dm.EARLY_S - 0.002 < s._wait() <= dm.BLOCK_S - dm.EARLY_S
        s._fed_here = False   # the mic callback took it
        assert dm.BLOCK_S < s._wait() <= dm.BLOCK_S + dm.POLL_S
        s._fed_period = 0.003   # a mic with short blocks
        assert s._wait() <= 0.003 + dm.POLL_S
        s._fed_at = now - 1.0   # overdue: look every POLL_S
        assert s._wait() == dm.POLL_S
        s._fed_at = None        # mic just (re)started
        assert s._wait() == dm.POLL_S
        s.mic_live, s._due_at = False, time.perf_counter() + 0.007   # on its own clock
        assert 0.005 < s._wait() <= 0.007
        s._due_at = time.perf_counter() + 5.0
        assert s._wait() == dm.BLOCK_S + dm.POLL_S
        s._due_at = None        # the effect reads on its own clock: keep it topped up
        assert s._wait() == dm.POLL_S
    finally:
        s.close()


def test_two_blocks_at_once_still_wait_for_only_one(ring_file):
    """After a hiccup two blocks of mic can come at once: the thread still looks again a
    block later, not two (that would make the board late with the next one)."""
    s = dm.DirectMicStream(lambda out, frames, t, status: out.fill(0), ring_file)
    w = dm.RingWriter(ring_file)
    try:
        s.active = True
        _publish(w, np.zeros((480, 2), np.float32))
        s.pump()
        _publish(w, np.zeros((960, 2), np.float32))
        s.pump()
        assert s._fed_period == dm.BLOCK_S
        assert s._wait() <= dm.BLOCK_S + dm.POLL_S   # (pumped here: the mic callback's timing)
    finally:
        w.close()
        s.close()


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
    f.write(np.full((4000, 2), 3, np.float32))   # a stall: nothing reads it...
    f.write(np.full((480, 2), 4, np.float32))    # ...so the next write drops it
    assert (f.read(480) == 4).all() and f.count == 0


def test_direct_fifo_keeps_a_late_wake_up_whole():
    """The board's thread woke 100 ms late: it writes all that mic at once and renders
    it in 10 ms reads. Every frame goes out, in order (dropping all but the last read
    cut holes in the voice whenever the PC was busy)."""
    from soundboard.engine import DirectFifo
    f = DirectFifo()
    x = np.arange(4800, dtype=np.float32)[:, None].repeat(2, axis=1)
    f.write(x)
    got = np.concatenate([f.read(480) for _ in range(10)])
    assert np.array_equal(got, x) and f.count == 0


def test_late_pump_sends_all_the_voice(ring_file):
    """A late pump in the real engine: the voice sent is the mic it got, with no holes."""
    from soundboard.engine import Engine
    e = Engine()
    e.main_direct = True
    e.main_stream = object()   # "open": the mic goes to the send mix
    voice = (0.3 * np.sin(np.arange(4800) / 7)).astype(np.float32)
    e._mic(np.stack([voice, voice], 1), direct=True)
    out = np.zeros((480, 2), np.float32)
    sent = []
    for _ in range(10):
        e._cb_main(out, 480, None, None)
        sent.append(out[:, 0].copy())
    sent = np.concatenate(sent)
    rms = np.sqrt((sent.reshape(10, 480) ** 2).mean(axis=1))
    assert rms.min() > 0.1, rms   # every 10 ms has voice in it


# ---------------------------------------------------------------------- the real effect

needs_host = pytest.mark.skipif(not (HOST.is_file() and DLL.is_file()),
                                reason="run scripts/build_directmic.py --testhost")


def realtime(test):
    """These run the effect in real time against a Python board in this process: on a
    PC busy with the rest of the suite that board can miss its moment. One retry; a
    real break fails both times."""
    import functools

    @functools.wraps(test)
    def run(*args, **kwargs):
        try:
            return test(*args, **kwargs)
        except AssertionError:
            ring = kwargs.get("ring_file")
            if ring is not None:
                ring.write_bytes(dm.new_ring_bytes())
            return test(*args, **kwargs)
    return run


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
@realtime
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
@realtime
def test_effect_keeps_the_mic_in_add_mode(ring_file):
    (x,), _, _ = _run_host(ring_file, 48000, 2, 1.0, mic=0.1)
    y = x[int(0.3 * 48000):, 0]
    assert abs(y.mean() - 0.1) < 0.01   # the mic (a constant here) is still in there
    assert y.max() > 0.55               # ...with the tone on top


@needs_host
@realtime
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
@realtime
def test_replace_mode_sends_the_boards_voice_soon(ring_file, instances):
    """Replace mode: what comes out of the mic is the board's send mix (here its own
    clean mic, halved), sample for sample, about LEAD_S later, for every app."""
    board = Echo(gain=0.5)
    outs, _, stats = _run_host(ring_file, 48000, 1, 2.5, mic=0.3, instances=instances,
                               mic_hz=-1, callback=board, mic_callback=board.mic,
                               mode=dm.MODE_REPLACE)
    # (how often the board was late, stats["late"], isn't checked: on a loaded test PC
    # this test's own Python board can be late a dozen times. The mic fades in for
    # those moments; what counts is that nearly every block is exact, below)
    assert stats["apps"] == instances
    assert 230 < len(board.blocks) <= 250   # the clean mic: each 10 ms block, once
    lags = []
    for x in outs:
        lag, exact = _delay(x[:, 0], 48000, level=0.15)
        assert lag <= 0.05 * 48000, lag / 48             # under 50 ms
        assert exact > 0.9, exact                        # exact: not a trace of the mic
        lags.append(lag)
    # every app hears it at about the same time (each starts reading on its own block)
    assert max(lags) - min(lags) <= 480 + 48 * 5


class Stalling(Echo):
    """An Echo board that stalls for `stall` s at each of `at` (seconds of its output)."""

    def __init__(self, at, stall, **kw):
        super().__init__(**kw)
        self.at, self.stall, self.made = list(at), stall, 0

    def __call__(self, out, frames, t, status):
        super().__call__(out, frames, t, status)
        self.made += frames
        if self.at and self.made >= self.at[0] * dm.RATE:
            self.at.pop(0)
            time.sleep(self.stall)


@needs_host
@pytest.mark.parametrize("stall", [0.03, 0.08])
@realtime
def test_a_late_board_is_filled_in_with_the_mic_from_then(ring_file, stall):
    """Replace mode, the board late (a busy PC): the effect fills in with the clean mic
    from the moment the board's audio was made from, so the voice goes on without a skip
    or a repeat. (It used to fill in with the mic as it is now, a lead ahead: each
    hiccup cut a bit out of the voice, then the resync played a bit twice.) Here the
    board's voice is the clean mic itself: the output is the mic, a fixed time later,
    sample for sample, hiccups and all."""
    board = Stalling([0.9, 1.5], stall, gain=1.0)
    (x,), _, _ = _run_host(ring_file, 48000, 1, 2.5, mic=0.3, mic_hz=-1, callback=board,
                           mic_callback=board.mic, mode=dm.MODE_REPLACE)
    lag, exact = _delay(x[:, 0], 48000, start_s=0.6, span_s=1.6)
    assert lag <= 0.05 * 48000, lag / 48
    assert exact > 0.98, exact


@needs_host
@realtime
def test_the_feed_keeps_up_with_a_busy_board_while_mostly_asleep(ring_file):
    """Replace mode with a busy thread beside the board (a UI at work): every block of
    its voice is in time, sample for sample the mic a lead later, while the thread
    wakes a couple of times a block instead of every 2 ms."""
    board = Echo(gain=1.0)
    stop = threading.Event()
    wakes = []

    def busy():
        while not stop.is_set():
            sum(i * i for i in range(20000))
            time.sleep(0.001)

    def during(s):
        pump = s.pump

        def counted():
            if threading.current_thread().name == "direct-mic":
                wakes.append(time.perf_counter())
            return pump()
        s.pump = counted
        threading.Thread(target=busy, daemon=True).start()

    try:
        (x,), _, _ = _run_host(ring_file, 48000, 1, 4.0, mic=0.3, mic_hz=-1, callback=board,
                               mic_callback=board.mic, mode=dm.MODE_REPLACE, during=during)
    finally:
        stop.set()
    lag, exact = _delay(x[:, 0], 48000, start_s=0.6, span_s=3.0)
    assert lag <= 0.05 * 48000, lag / 48
    assert exact > 0.98, exact
    assert len(wakes) / (wakes[-1] - wakes[0]) < 300   # was about 450 a second


def _feed_beside_busy_ui(ring_file, taker, seconds, poll_every=None):
    """A stand-in for the effect publishes a 10 ms block of clean mic in real time while
    a UI thread beside the board keeps Python busy (at the app's GIL switch interval).
    Returns the blocks the board took later than the 20 ms lead the effect reads behind
    it (any later and the effect fills in with the clean mic: a gap in the sounds), how
    long it took with those, and the feed thread's wakeups a second. `poll_every`: the
    feed thread looks that often instead (how it was: every 2 ms)."""
    import sys

    from soundboard.app import SWITCH_S
    block, block_s = dm.BLOCK, dm.BLOCK / dm.RATE
    seen = {}   # block number -> when the board took it

    def mic(x, rate):
        now = time.perf_counter()
        for k in np.unique(np.rint(x[:, 0] * 1e4).astype(int)):
            seen.setdefault(int(k), now)

    ring_file.write_bytes(dm.new_ring_bytes())
    s = dm.DirectMicStream(lambda out, frames, t, status: out.fill(0.25), ring_file,
                           mic_callback=mic)
    if poll_every is not None:
        s._wait = lambda: poll_every
    w = dm.RingWriter(ring_file)
    stop = threading.Event()
    wakes = [0]
    pump = s.pump

    def counted():
        if threading.current_thread() is s._thread:
            wakes[0] += 1
        return pump()
    s.pump = counted

    def ui():   # 50 ms of pure-Python work at a time: holds the GIL all it can
        while not stop.is_set():
            end = time.perf_counter() + 0.05
            while time.perf_counter() < end:
                sum(i * i for i in range(500))
            time.sleep(0.002)

    sent, blocks = {}, int(seconds / block_s)
    old = sys.getswitchinterval()
    sys.setswitchinterval(SWITCH_S)
    s.start()
    threading.Thread(target=ui, daemon=True).start()
    try:
        t0 = time.perf_counter()
        for k in range(1, blocks + 1):
            while (d := t0 + k * block_s - time.perf_counter()) > 0:
                time.sleep(d)
            pos = w.mic_write_pos
            w.mic[np.arange(pos, pos + block) % dm.MIC_CAPACITY] = k * 1e-4   # its number
            h = w.h[0]
            h["mic_rate"], h["mic_write_pos"], h["mic_tick"] = 48000, pos + block, dm._tick()
            sent[k] = time.perf_counter()
            if taker == "mic callback":
                s.pump()
        time.sleep(3 * block_s)
        elapsed = time.perf_counter() - t0
    finally:
        stop.set()
        s.close()
        w.close()
        sys.setswitchinterval(old)
    # (the first 0.3 s: the stream starts on whichever block it sees first)
    took = {k: seen[k] - sent[k] if k in seen else float("inf") for k in sent if k > 30}
    late = sorted(k for k, t in took.items() if t >= dm.LEAD_S)
    return late, [round(took[k] * 1e3, 1) for k in late[:5]], wakes[0] / elapsed


@pytest.mark.parametrize("taker", ["feed", "mic callback"])
@realtime
def test_no_underruns_beside_a_busy_ui_thread(ring_file, taker):
    """5 s of clean mic beside a busy UI thread: the board takes every block in time, as
    often as it did when the feed thread looked every 2 ms (run alongside, the same way,
    as the yardstick: on a PC this busy that one misses some too), whether the feed
    thread takes the mic or the board's mic callback does, and the feed thread sleeps
    between blocks."""
    late, ms, rate = _feed_beside_busy_ui(ring_file, taker, 5.0)
    if late:   # how often did looking every 2 ms miss, on this PC right now?
        before, _, _ = _feed_beside_busy_ui(ring_file, taker, 5.0, poll_every=dm.POLL_S)
        assert len(late) <= max(2, 2 * len(before)), (late[:5], ms, len(before))
    assert rate < (350 if taker == "feed" else 150), rate   # was about 450 a second


@needs_host
@realtime
def test_a_late_board_never_lets_a_muted_mic_out(ring_file):
    """Replace mode, the mic muted on the board (it sends silence), the board late: the
    effect's fill-in stays muted. (It used to put the plain mic out for the hiccup.)"""
    board = Stalling([0.9, 1.4], 0.08, gain=0.0)

    def during(s):
        s.set_mic_gain(0.0)

    (x,), _, _ = _run_host(ring_file, 48000, 1, 2.0, mic=0.3, mic_hz=-1, callback=board,
                           mic_callback=board.mic, mode=dm.MODE_REPLACE, during=during)
    assert np.abs(x[int(0.6 * 48000):, 0]).max() < 0.01


def test_board_tells_the_effect_where_its_audio_came_from(ring_file):
    """Each stretch the board renders on the mic's clock comes with the sync pair: ring
    frame -> the clean-mic frame it was made from (minus the board's own voice delay)."""
    w = dm.RingWriter(ring_file)
    w._set("mic_rate", 48000)
    w.close()
    s = dm.DirectMicStream(lambda out, frames, t, st: out.fill(0), ring_file,
                           voice_delay=lambda: 144.0)
    try:
        ring = s._ring
        s.active = True
        ring._mtick[0] = dm._tick()
        ring._mwp[0] = 1000
        s._pump()                      # starts here
        ring._mtick[0] = dm._tick()
        ring._mwp[0] = 1960
        s._pump()                      # 960 frames of mic -> 960 rendered
        assert ring.write_pos == 960
        assert int(ring._get("sync_wp")) == 960 and int(ring._get("sync_mic")) == 1960 - 144
        assert int(ring._get("sync_seq")) % 2 == 0
    finally:
        s.close()


def test_engine_voice_delay_is_what_it_adds(ring_file):
    """Engine._direct_voice_delay matches the delay the send mix really has on the voice
    (limiter lookahead; a resampler's hold-back at other mic rates)."""
    from soundboard.engine import Engine
    for rate in (48000, 44100):
        e = Engine()
        e.main_direct = True
        e.main_stream = object()
        e.rates["mic"] = rate
        e._reconfigure_mic_resamplers()
        rng = np.random.default_rng(1)
        x = (0.1 * rng.standard_normal(2 * rate)).astype(np.float32)
        blk = rate // 100
        out = np.zeros((480, 2), np.float32)
        sent = []
        for i in range(200):
            b = x[i * blk:(i + 1) * blk]
            e._mic(np.stack([b, b], 1), direct=True)
            e._cb_main(out, 480, None, None)
            sent.append(out[:, 0].copy())
        y = np.concatenate(sent).astype(np.float64)
        # the newest voice in y is the mic from `d` frames (at 48 kHz) before its end
        d = e._direct_voice_delay()
        import soxr
        ref = x.astype(np.float64) if rate == 48000 else \
            soxr.resample(x, rate, 48000, quality="VHQ")
        tail = y[-24000:]   # (it settles over the first moments: the end is what counts)
        lags = range(0, 4000)
        k = max(lags, key=lambda lag: float(np.dot(tail, ref[len(y) - 24000 - lag:len(y) - lag])))
        assert abs(k - d) <= 2, (rate, k, d)


@needs_host
@realtime
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


def ramp(seconds):
    """A board whose send mix is a ramp from 0.1 to 0.45 over `seconds`: every ring
    frame has its own value, so a replayed stretch shows."""
    pos = [0]
    total = seconds * dm.RATE

    def cb(out, frames, t, status):
        n = np.arange(pos[0], pos[0] + frames)
        out[:] = (0.1 + 0.35 * np.minimum(n, total) / total).astype(np.float32)[:, None]
        pos[0] += frames
    return cb, pos


def _dips(y):
    """Stretches where the board's ramp is (nearly) gone from y: the mic took over."""
    low = np.abs(y) < 0.01
    return int(np.sum(low[1:] & ~low[:-1]) + low[0])


@needs_host
@pytest.mark.parametrize("how", ["killed", "frozen"])
@realtime
def test_a_dead_or_frozen_board_never_repeats_itself(ring_file, how):
    """The board killed (no word to the effect: its last writes just stop) or frozen for
    150 ms: the mic (silent here) fades back in once, and nothing the board already sent
    is played again. That used to stutter the last 25 ms over and over for 0.2 s."""
    cb, pos = ramp(3)

    def board(out, frames, t, status):
        cb(out, frames, t, status)
        if how == "frozen" and 0.8 * dm.RATE <= pos[0] < 0.8 * dm.RATE + frames:
            time.sleep(0.15)

    def during(s):
        if how == "killed":
            time.sleep(0.8)
            s._stop.set()   # the board's thread stops, the ring stays "on": a crash

    (x,), _, _ = _run_host(ring_file, 48000, 1, 2.0, callback=board, mode=dm.MODE_REPLACE,
                           during=during)
    y = x[int(0.3 * 48000):, 0]
    assert _dips(y) == 1, _dips(y)   # once: it went to the mic (and came back, frozen)
    first = int(np.argmax(np.abs(y) < 0.01))
    last_sent = float(y[:first].max())
    later = y[first:]
    steady = np.abs(np.diff(later)) < 5e-5   # full level, not a fade
    replayed = (later[1:] > 0.01) & (later[1:] < last_sent - 0.003) & steady
    assert not replayed.any(), np.where(replayed)[0][:5] / 48
    if how == "killed":
        assert np.abs(later).max() < 0.01   # the mic alone from then on
    else:
        assert np.abs(x[int(1.7 * 48000):, 0]).min() > 0.1   # the board is back


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
@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_effect_survives_a_fuzzed_ring(ring_file, seed):
    """Every header field and slot overwritten with random values, many times a second,
    while the board and the effect run: nothing crashes, nothing but sound in range
    comes out, and once the ring is sane again the effect is back to normal."""
    rng = np.random.default_rng(seed)
    fields = [n for n in dm.HEAD.names if n not in ("magic", "version", "capacity",
                                                    "mic_capacity", "rate")]

    def junk(kind):
        if kind.kind == "f":
            return rng.choice([np.nan, np.inf, -np.inf, -1e30, 1e30, rng.normal() * 10, 0.5])
        top = np.iinfo(kind).max
        return rng.choice([0, 1, top, rng.integers(0, top, dtype=np.uint64 if kind.kind == "u"
                                                    else np.int64) if top > 2**31 else
                           rng.integers(0, top)])

    def during(s):
        ring = s._ring
        t0 = time.monotonic()
        while time.monotonic() - t0 < 1.2:
            for name in rng.choice(fields, 4):
                v = ring._f_fields[name]
                try:
                    with np.errstate(invalid="ignore"):
                        v[0] = junk(v.dtype)
                except (OverflowError, ValueError):
                    v[0] = 0
            raw = ring.slots.view(np.uint8)
            raw[:] = rng.integers(0, 256, raw.shape, dtype=np.uint8) if rng.random() < 0.3 \
                else raw
            time.sleep(0.003)
        # sane again (what the board itself keeps setting)
        for name, v in (("enabled", 1), ("mode", dm.MODE_ADD), ("gain", 1.0), ("mic_gain", 1.0),
                        ("lead", 0), ("publisher", 0), ("mic_rate", 48000)):
            ring._set(name, v)
        ring.slots.view(np.uint8)[:] = 0

    (x,), _, _ = _run_host(ring_file, 48000, 2, 3.0, mic=0.1, during=during)
    assert np.all(np.isfinite(x)) and np.abs(x).max() <= 1.0
    y = x[int(2.2 * 48000):, 0]
    assert abs(y.mean() - 0.1) < 0.02 and y.max() > 0.5, (y.mean(), y.max())


@needs_host
@pytest.mark.parametrize("damage", ["truncated", "tiny", "empty", "capacity", "version"])
def test_a_damaged_ring_file_leaves_the_mic_exactly_as_it_is(ring_file, damage):
    """A ring file cut short, emptied or with a layout the effect doesn't know: it never
    reads past what's there and hands on the mic untouched."""
    raw = bytearray(ring_file.read_bytes())
    if damage == "truncated":
        raw = raw[:len(raw) // 2]   # the header promises more than the file has
    elif damage == "tiny":
        raw = raw[:100]
    elif damage == "empty":
        raw = bytearray()
    elif damage == "capacity":
        raw[12:16] = (3).to_bytes(4, "little")
    else:
        raw[4:8] = (99).to_bytes(4, "little")
    ring_file.write_bytes(bytes(raw))
    out = ring_file.parent / "out.f32"
    env = dict(os.environ, ProgramData=str(ring_file.parent.parent.parent))
    r = subprocess.run([str(HOST), str(DLL), str(out), "48000", "2", "0.3", "0.2"], env=env,
                       capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stdout + r.stderr
    assert np.all(np.fromfile(out, np.float32) == np.float32(0.2))


@needs_host
@realtime
def test_a_header_gone_bad_puts_the_mic_back_until_it_is_right(ring_file):
    """The layout changing under a running effect (only junk does that: the board makes a
    new file instead): the plain mic until it's right again, then the board is back."""
    def during(s):
        h = s._ring
        time.sleep(0.8)
        h._set("magic", 0)
        time.sleep(0.8)
        h._set("magic", dm.MAGIC)

    (x,), _, _ = _run_host(ring_file, 48000, 2, 2.6, mic=0.1, during=during)
    y = x[:, 0]
    assert np.abs(y[int(0.4 * 48000):int(0.6 * 48000)] - 0.1).max() > 0.3   # board + mic
    bad = y[int(1.0 * 48000):int(1.35 * 48000)]
    assert np.all(bad == np.float32(0.1)), np.abs(bad - 0.1).max()        # the mic alone
    assert np.abs(y[int(2.0 * 48000):int(2.5 * 48000)] - 0.1).max() > 0.3   # board back


FUZZ_HOST = BUILD / "fuzzhost.exe"
FUZZ_DLL = BUILD / "obmic_fuzz.dll"
needs_fuzz = pytest.mark.skipif(not (FUZZ_HOST.is_file() and FUZZ_DLL.is_file()),
                                reason="run scripts/build_directmic.py --fuzz")


@needs_fuzz
def test_a_fault_in_the_effect_puts_the_mic_back(tmp_path):
    """The guard: a fault while the effect runs (the fuzz build's test switch) hands on
    the block exactly as it came in, rests a moment, then the board is back."""
    r = subprocess.run([str(FUZZ_HOST), str(FUZZ_DLL), str(tmp_path), "--selftest"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "SELFTEST OK" in r.stdout, r.stdout + r.stderr


@needs_fuzz
def test_lead_grows_just_enough_and_comes_back(tmp_path):
    """fuzzhost --lead, block by block (no timing luck): a board late by a block once
    takes the lead one step; late every other block, two steps (the same lag counted
    again while a step was still owed took it to 50 ms); then back to the normal lead,
    really read that far behind, with the board's sync pair and without."""
    r = subprocess.run([str(FUZZ_HOST), str(FUZZ_DLL), str(tmp_path), "--lead"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "LEAD OK" in r.stdout, r.stdout + r.stderr


@needs_fuzz
def test_effect_survives_a_short_fuzz(tmp_path):
    """A few seconds of fuzzhost (hostile, truncated and half-written ring files; the
    effect with sanitizer traps): no crash, hang, caught fault or sound out of range.
    scripts/fuzz_directmic.py runs it for longer."""
    r = subprocess.run([str(FUZZ_HOST), str(FUZZ_DLL), str(tmp_path), "4", "12345"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "0 findings" in r.stdout, r.stdout[-3000:] + r.stderr


def test_board_ignores_a_nonsense_mic_rate(ring_file):
    """A ring claiming a 1 Hz mic would make the board render a gigantic stretch for a
    handful of mic frames (a hang): such a rate doesn't count as a live mic."""
    w = dm.RingWriter(ring_file)
    try:
        w._set("mic_rate", 1)
        w._mtick[0] = dm._tick()
        assert not w.mic_live()
        w._set("mic_rate", 48000)
        assert w.mic_live()
    finally:
        w.close()


@needs_host
@pytest.mark.parametrize("stall", [0.03, 0.08])
@realtime
def test_delay_shrinks_back_after_a_hiccup(ring_file, stall):
    """The board late once: the effect reads further behind it (more delay) to ride it
    out, then, once the board has kept time for a while, closes the gap again in a quiet
    moment, back to the normal delay."""
    phase = [0]
    hiccup = [False]

    def bursts(out, frames, t, status):   # 100 ms of tone, 100 ms of silence
        n = np.arange(phase[0], phase[0] + frames)
        on = (n // 4800) % 2 == 0
        out[:] = (0.4 * on * np.sin(2 * np.pi * 440 * n / dm.RATE)).astype(np.float32)[:, None]
        phase[0] += frames
        if phase[0] > 0.6 * dm.RATE and not hiccup[0]:
            hiccup[0] = True
            time.sleep(stall)   # the board stalls (a GIL hog, a page fault storm)

    leads = {}
    base = int(dm.LEAD_S * dm.RATE)

    # "Once the board has kept time": each time it's late again (this Python board, on a
    # PC busy with the rest of the suite, can be) the effect rightly keeps the bigger
    # lead and starts counting again. So: back to normal within ~3 s of the last late
    # block (2 s on time, then a quiet moment per 20 ms step), however long that takes.
    def during(s):
        lead = lambda: int(s._ring.live_slots()["lead"].max())  # noqa: E731
        time.sleep(1.5)
        leads["after"] = lead()
        late, since, end = s.late(), time.monotonic(), time.monotonic() + 7.0
        while time.monotonic() < end and lead() != base:
            if s.late() != late:
                late, since = s.late(), time.monotonic()
            if time.monotonic() - since > 3.2:
                leads["on time"] = "3.2 s and it didn't come back"
                break
            time.sleep(0.05)
        else:
            if lead() != base:
                leads["on time"] = "never 3.2 s on end: the PC was too busy to tell"
        leads["end"], leads["late"] = lead(), s.late()

    (x,), _, _ = _run_host(ring_file, 48000, 1, 9.5, callback=bursts, mode=dm.MODE_REPLACE,
                           during=during)
    assert leads["after"] > base, leads             # it rode the hiccup out
    assert leads["end"] == base, leads              # ...and came back
    assert np.all(np.isfinite(x)) and np.abs(x).max() <= 0.41


@needs_host
@pytest.mark.parametrize("rate, tone, most", [
    (16000, 12000, -60),    # above a 16 kHz mic's top: must not fold back down as noise
    (16000, 20000, -60),
    (44100, 23000, -60),
])
def test_highs_above_the_mic_rate_dont_fold_back(ring_file, rate, tone, most):
    phase = [0]

    def hi(out, frames, t, status):
        n = np.arange(phase[0], phase[0] + frames)
        out[:] = (0.5 * np.sin(2 * np.pi * tone * n / dm.RATE)).astype(np.float32)[:, None]
        phase[0] += frames

    (x,), _, _ = _run_host(ring_file, rate, 1, 1.5, callback=hi, mode=dm.MODE_REPLACE)
    y = x[int(0.6 * rate):, 0]
    level = 20 * np.log10(np.sqrt(np.mean(y ** 2)) / (0.5 / np.sqrt(2)) + 1e-12)
    assert level < most, level


@needs_host
@pytest.mark.parametrize("rate, tone", [(16000, 1000), (16000, 6500), (44100, 1000),
                                        (44100, 19000)])
@realtime
def test_tones_in_the_mics_range_come_through_clean(ring_file, rate, tone):
    phase = [0]

    def sine(out, frames, t, status):
        n = np.arange(phase[0], phase[0] + frames)
        out[:] = (0.5 * np.sin(2 * np.pi * tone * n / dm.RATE)).astype(np.float32)[:, None]
        phase[0] += frames

    (x,), _, _ = _run_host(ring_file, rate, 1, 1.5, callback=sine, mode=dm.MODE_REPLACE)
    y = x[int(0.6 * rate):, 0]
    win = np.blackman(len(y))
    spec = np.abs(np.fft.rfft(y * win)) ** 2
    f = np.fft.rfftfreq(len(y), 1 / rate)
    near = np.abs(f - tone) < 40
    thdn = 10 * np.log10(spec[~near].sum() / spec[near].sum())
    assert thdn < -60, thdn
    rms = np.sqrt(np.mean(y ** 2))
    assert abs(20 * np.log10(rms / (0.5 / np.sqrt(2)))) < 0.5   # level kept


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
    # 1.9.1: settings on the cable move to the mic once; other routes stay put, and a
    # route picked after that move stays as picked
    assert library.Config.from_raw({"version": 4}).route == "mic"
    assert library.Config.from_raw({"version": 4, "route": "cable"}).route == "mic"
    assert library.Config.from_raw({"version": 4, "route": "device"}).route == "device"
    assert library.Config.from_raw({"version": 4, "route": "off"}).route == "off"
    moved = library.Config.from_raw({"version": 4, "route": "cable"})
    assert moved.mic_first
    moved.route = "cable"   # picked by hand afterwards
    assert library.Config.from_raw(moved.to_raw()).route == "cable"


@pytest.mark.parametrize("on, here, in_place, same, expected", [
    ([], True, True, True, "missing"),
    (["{b}"], True, True, True, "other"),
    (["{a}"], True, False, True, "wiped"),       # a driver update took it off
    (["{a}"], True, True, False, "outdated"),    # an older copy (still works)
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
    assert dm.needs_repair(expected) == (expected == "wiped")
    assert dm.works(expected) == (expected in ("ready", "outdated"))


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
    monkeypatch.setattr(eng, "virtual_mic_for",   # (no real cable needed: CI has none)
                        lambda name: name and name.replace("Input", "Output"))
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


# ---------------------------------------------------------------------- 1.9.1: mic first

CABLE_IN = "CABLE Input (VB-Audio Virtual Cable)"


def _routes(w, monkeypatch, state, cables=(CABLE_IN,)):
    from soundboard import engine as eng
    monkeypatch.setattr(dm, "status", lambda name=None: state)
    monkeypatch.setattr(eng, "virtual_outputs", lambda: list(cables))
    w.cfg.route = "mic"
    w.cfg.main_device = None
    w.cfg.mon_device = "Headphones"


@pytest.mark.parametrize("state", ["missing", "wiped", "other"])
def test_nobody_goes_silent_before_the_mic_is_set_up(window, monkeypatch, state):  # noqa: F811
    """On the mic route but not (yet) on the mic: what others hear goes through the
    cable meanwhile, so a voice app set to it still hears you."""
    w = window
    _routes(w, monkeypatch, state)
    assert w._main_name() == CABLE_IN
    _routes(w, monkeypatch, state, cables=())
    assert w._main_name() is None   # no cable either: nothing to send into


@pytest.mark.parametrize("state", ["ready", "missing", "wiped"])
def test_on_the_mic_the_setup_tab_never_talks_about_the_cable(window, monkeypatch, state):  # noqa: F811
    """Straight into the mic is the way: working or not set up yet, the Setup tab
    doesn't say the cable is in use, or tell anyone to pick one. The cable comes up
    only as the "Use the virtual cable instead" fallback button."""
    w = window
    _routes(w, monkeypatch, state)
    monkeypatch.setattr(w, "_direct_not_running", lambda: False)

    class S:
        def stop(self):
            pass
        close = stop
    w.engine.main_stream, w.engine.tap = S(), S()   # the cable still fed alongside
    try:
        w._show_route()
        w._update_status()
        for lbl in (w.flow_out, w.step_lbl, w.setup_hint, w.how_title, w.pill):
            assert "cable" not in lbl.text().lower(), lbl.text()
    finally:
        w.engine.main_stream = w.engine.tap = None


@pytest.mark.parametrize("state, dead", [("ready", True), ("wiped", True),
                                         ("missing", False), ("other", False)])
def test_effect_not_running_check_reads_no_registry(window, monkeypatch, state, dead):  # noqa: F811
    """Checked every second on the UI thread: it uses the cached status instead of
    walking the registry's recording devices each time."""
    w = window
    w.cfg.mic_device = "My mic"
    monkeypatch.setattr(dm, "status", lambda name=None: state)

    def registry(*_a):
        raise AssertionError("walked the registry on the UI thread")
    monkeypatch.setattr(dm, "endpoint_for", registry)
    monkeypatch.setattr(dm, "installed_on", registry)
    monkeypatch.setattr(w.engine, "effect_alive", lambda: False)
    monkeypatch.setattr(w.engine, "mic_stream", object())
    w._direct_dead_since = time.monotonic() - w.DIRECT_GRACE_S - 1
    assert w._direct_not_running() is dead


def test_an_older_working_mic_part_offers_the_update_as_optional(window, monkeypatch):  # noqa: F811
    """Sounds in the mic with an older mic part: the tab says it's all set, and the
    update is plainly optional (not a primary button, not a "needs fixing")."""
    w = window
    _routes(w, monkeypatch, "outdated", cables=())
    monkeypatch.setattr(w, "_direct_not_running", lambda: False)

    class S:
        def stop(self):
            pass
        close = stop
    w.engine.main_stream = S()
    try:
        w._show_route()
        w._update_status()
        assert w.setup_state == "ok"
        step = w.step_lbl.text()
        assert "Nothing to set" in step and "Optional" in step
        assert w.btn_install.text().startswith("Optional")
        assert w.btn_install.objectName() != "primary"
    finally:
        w.engine.main_stream = None


@pytest.mark.parametrize("state", ["ready", "outdated"])
def test_on_the_mic_the_cable_gets_the_same(window, monkeypatch, state):  # noqa: F811
    w = window
    _routes(w, monkeypatch, state)
    opened = []
    monkeypatch.setattr(type(w.engine), "set_tap_device",
                        lambda self, name: (opened.append(name), setattr(self, "tap_name", name)))
    assert w._main_name() == dm.DEVICE   # (an older copy of the effect still works)
    w._apply_send_outputs()
    assert opened == [CABLE_IN]
    _routes(w, monkeypatch, state, cables=())
    w._apply_send_outputs()
    assert opened[-1] is None


@pytest.mark.parametrize("cables", [(CABLE_IN,), ()])
def test_saying_no_to_windows_keeps_the_mic_on_offer(window, monkeypatch, cables):  # noqa: F811
    """The admin prompt turned down: the route stays on the mic (one click still on
    offer), and the cable, if there is one, carries the sounds meanwhile."""
    from PySide6.QtWidgets import QMessageBox
    w = window
    _routes(w, monkeypatch, "missing", cables)
    said = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: said.append(a[2]))
    w._mic_attached("My mic", "Windows' admin prompt was turned down (or didn't finish).")
    assert w.cfg.route == "mic" and w._main_name() == (cables[0] if cables else None)
    assert "cable" not in said[0].lower()   # the mic is the way; the cable just quietly helps
    assert "Try again" in said[0]
    assert "mic" in w.pill.text().lower()


def test_a_slow_status_check_never_holds_up_the_window(monkeypatch):
    """A 1.9.7 freeze: the window asks for the status every second, and re-checking it
    stat()ed the ring file on the UI thread (6 s on a busy disk). After the first
    answer the re-check runs on a thread and the last answer comes back meanwhile."""
    import threading
    import time
    gate, calls, answer = threading.Event(), [], ["ready"]

    def slow(name):
        calls.append(name)
        if len(calls) > 1:
            gate.wait(5)   # the disk is busy
        return answer[0]
    monkeypatch.setattr(dm, "_status", slow)
    dm.forget_status()
    assert dm.status("My mic") == "ready"            # the first answer: worked out now
    monkeypatch.setattr(dm, "STATUS_S", 0.0)          # ...and stale at once
    answer[0] = "wiped"
    start = time.monotonic()
    for _ in range(5):
        assert dm.status("My mic") == "ready"        # the last answer, no waiting
    assert time.monotonic() - start < 0.5
    assert len(calls) == 2                            # one re-check at a time
    gate.set()
    end = time.monotonic() + 5
    while dm._status_busy and time.monotonic() < end:
        time.sleep(0.01)
    monkeypatch.setattr(dm, "STATUS_S", 60.0)
    assert dm.status("My mic") == "wiped"


def test_a_status_check_from_before_forget_status_is_dropped(monkeypatch):
    import threading
    import time
    gate = threading.Event()
    monkeypatch.setattr(dm, "_status", lambda name: "ready")
    dm.forget_status()
    dm.status(None)
    monkeypatch.setattr(dm, "STATUS_S", 0.0)
    monkeypatch.setattr(dm, "_status", lambda name: gate.wait(5) and "wiped")
    dm.status(None)                  # a re-check starts...
    dm.forget_status()               # ...then the user set it up again
    gate.set()
    end = time.monotonic() + 5
    while dm._status_busy and time.monotonic() < end:
        time.sleep(0.01)
    assert None not in dm._status_cache   # the old re-check's answer wasn't kept


def test_the_banner_never_sends_mic_users_to_the_cable(window, monkeypatch):  # noqa: F811
    w = window
    w._pill_short = False
    for state in ("missing", "wiped", "other"):
        _routes(w, monkeypatch, state)
        dm.forget_status()
        w._update_flow()
        assert "virtual cable" not in w.pill.text(), (state, w.pill.text())
        assert "mic" in w.pill.text()
        assert "straight into my mic" in w.btn_install.text() or "Repair" in w.btn_install.text()
        assert not w.btn_install.isHidden() and w.btn_install.objectName() == "primary"
    w.cfg.route = "cable"   # on the cable route, and no cable: the fix offers the mic first
    monkeypatch.setattr(w, "virtual_mic", None)
    w._update_flow()
    assert "virtual cable" not in w.pill.text()
    assert w.btn_attach.objectName() == "primary" and w.btn_install.objectName() != "primary"


class _NoThread:
    """threading.Thread stand-in: counts starts; runs the target there and then if
    `run`, else never (the admin prompt still waiting)."""
    started = 0
    run = False

    def __init__(self, target=None, **_kw):
        self.target = target

    def start(self):
        type(self).started += 1
        if type(self).run:
            self.target()


def _no_threads(monkeypatch, run=False):
    from soundboard.ui import mainwindow as mw
    t = type("T", (_NoThread,), {"started": 0, "run": run})
    monkeypatch.setattr(mw.threading, "Thread", t)
    return t


def test_setting_up_the_mic_shows_it_and_takes_one_click(window, monkeypatch):  # noqa: F811
    """Clicking the one-click button: it says "Setting up…" and ignores more clicks
    until Windows has it running, instead of offering Repair again straight away."""
    from soundboard.ui import busy
    w = window
    w._pill_short = False
    _routes(w, monkeypatch, "missing")
    w.cfg.mic_device = "My mic"
    threads = _no_threads(monkeypatch)
    w.attach_mic()
    assert busy.is_busy(w.btn_install) and w.btn_install.text() == "Setting up…"
    assert not w.btn_install.isHidden() and w.btn_usecable.isHidden()
    assert "setting up" in w.pill.text().lower()
    w.attach_mic()
    w.btn_install.click()   # spam-clicked: still the one admin prompt
    assert threads.started == 1
    # done: Windows loads it, and until the effect runs it's "starting…", still held
    monkeypatch.setattr(dm, "status", lambda name=None: "ready")
    monkeypatch.setattr(type(w.engine), "effect_alive", lambda self: False)
    w._mic_attached("My mic", "")
    assert "starting" in w.flow_out.text() and busy.is_busy(w.btn_install)
    assert "Repair" not in w.btn_install.text() and w.btn_usecable.isHidden()
    w._settle_until = 0.0   # the wait is over: the button is a button again
    w._update_flow()
    assert not busy.is_busy(w.btn_install) and w._attach_release is None


def test_turning_windows_down_lets_go_of_the_button(window, monkeypatch):  # noqa: F811
    from PySide6.QtWidgets import QMessageBox
    from soundboard.ui import busy
    w = window
    _routes(w, monkeypatch, "missing")
    w.cfg.mic_device = "My mic"
    _no_threads(monkeypatch)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: None)
    w.attach_mic()
    w._mic_attached("My mic", "Windows' admin prompt was turned down (or didn't finish).")
    assert not busy.is_busy(w.btn_install) and w._attach_release is None


def _working_on_the_mic(w, monkeypatch, cables=(CABLE_IN,), vbcable=True):
    from pathlib import Path
    from soundboard import cableremove
    _routes(w, monkeypatch, "ready", cables)
    monkeypatch.setattr(w.engine, "main_stream", object())
    monkeypatch.setattr(w, "_direct_not_running", lambda: False)
    monkeypatch.setattr(cableremove, "setup_exe",
                        lambda: Path("VBCABLE_Setup_x64.exe") if vbcable else None)


def test_a_working_mic_offers_to_remove_the_cable(window, monkeypatch):  # noqa: F811
    """Straight into the mic works: the cable is only the fallback, so it's offered for
    removal (and no "also on the virtual cable" on the mic's line)."""
    w = window
    _working_on_the_mic(w, monkeypatch)
    w._update_flow()
    assert "virtual cable" not in w.flow_out.text()
    assert "don't need the virtual cable" in w.rmcable_note.text()
    assert not w.rmcable_note.isHidden() and "cable" not in w.step_lbl.text().lower()
    assert not w.btn_rmcable.isHidden()
    for cables, vbcable in (((), True), ((CABLE_IN,), False)):   # none, or not VB-Cable's
        _working_on_the_mic(w, monkeypatch, cables, vbcable)
        w._update_flow()
        assert w.btn_rmcable.isHidden() and w.rmcable_note.isHidden()


def test_removing_the_cable(window, monkeypatch):  # noqa: F811
    from soundboard import cableremove
    from soundboard.ui import busy
    w = window
    _working_on_the_mic(w, monkeypatch)
    said = []
    monkeypatch.setattr(w, "toast", lambda text, kind="": said.append((text, kind)))
    _no_threads(monkeypatch, run=True)
    monkeypatch.setattr(cableremove, "remove", lambda: "Windows' admin prompt was turned down")
    w.remove_cable()
    assert not w._cable_gone and not busy.is_busy(w.btn_rmcable)
    assert said[-1][1] == "warn"
    monkeypatch.setattr(cableremove, "remove", lambda: None)
    w.remove_cable()
    assert w._cable_gone and w._tap_name() is None and not busy.is_busy(w.btn_rmcable)
    assert "Restart" in said[-1][0]
    w._update_flow()
    assert w.btn_rmcable.isHidden() and w.rmcable_note.isHidden()


@pytest.mark.parametrize("state", ["ready", "missing", "wiped"])
def test_no_cable_or_speaker_hint_on_the_mic(window, monkeypatch, state):  # noqa: F811
    """Straight into the mic has no "send into" device: the Devices card never warns
    "that's a normal speaker, only you will hear the sounds" (it said so on 1.9.2)."""
    w = window
    _routes(w, monkeypatch, state)
    w._update_status()
    hint = w.setup_hint.text()
    assert "speaker" not in hint and "virtual cable" not in hint and "only you" not in hint


def test_cable_remover_finds_vb_audios_setup(tmp_path, monkeypatch):
    from soundboard import cableremove
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "x86"))
    assert cableremove.setup_exe() is None
    assert "isn't on this PC" in cableremove.remove()
    exe = tmp_path / "VB" / "CABLE" / "VBCABLE_Setup_x64.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    assert cableremove.setup_exe() == exe
    ran = []
    monkeypatch.setattr(dm, "run_elevated", lambda *a, **k: ran.append(a) or 0)
    assert cableremove.remove() is None and ran == [(str(exe), "-u -h")]
    monkeypatch.setattr(dm, "run_elevated", lambda *a, **k: None)
    assert "turned down" in cableremove.remove()


def test_cable_tap_plays_the_send_mix_on_the_cables_clock(monkeypatch):
    from soundboard import engine as eng
    monkeypatch.setattr(eng, "find_device", lambda kind, name: 7)
    monkeypatch.setattr(eng.sd, "query_devices", lambda idx: {"default_samplerate": 48000})
    tap = eng.CableTap(CABLE_IN)
    try:
        tap.stream.stop()   # (driven by hand below)
        block = np.full((480, 2), 0.25, np.float32)
        for _ in range(4):
            tap.write(block)
        out = np.zeros((480, 2), np.float32)
        tap._cb(out, 480, None, None)
        assert np.allclose(out[-100:], 0.25, atol=1e-3)   # (it fades in at the start)
    finally:
        tap.close()


def test_engine_feeds_the_cable_only_while_straight_into_the_mic(ring_file, monkeypatch):
    from soundboard.engine import Engine
    monkeypatch.setattr(dm, "ring_path", lambda: ring_file)
    got = []

    class FakeTap:
        def write(self, mix):
            got.append(mix.copy())

        def close(self):
            pass
    e = Engine()
    try:
        e.tap = FakeTap()
        out = np.zeros((480, 2), np.float32)
        e._main(out, 480)
        assert not got   # not on the mic route: the cable is the main output itself
        e.main_direct = True
        e._main(out, 480)
        assert len(got) == 1 and np.array_equal(got[0], out)
    finally:
        e.tap = None
        e.shutdown()


def test_the_cable_copy_opens_at_start(window, monkeypatch):  # noqa: F811
    """Starting up on the mic route opens the cable copy too (not only after a device
    change): a voice app still set to the cable hears you from the first second."""
    w = window
    _routes(w, monkeypatch, "outdated")
    opened = []
    monkeypatch.setattr(type(w.engine), "set_tap_device",
                        lambda self, name: (opened.append(name), setattr(self, "tap_name", name)))
    w._init_devices()
    assert opened[-1] == CABLE_IN
    # the stream output never goes to that same cable (everyone would get it twice)
    assert w._obs_name("CABLE Input (VB-Audio Virtual Cable)") is None


def test_reopening_every_stream_reopens_the_cable_copy(monkeypatch):
    from soundboard.engine import Engine
    e = Engine()
    seen = []
    monkeypatch.setattr(Engine, "set_tap_device", lambda self, name: seen.append(name))
    e.tap_name = CABLE_IN
    for name in ("set_mic_device", "set_main_device", "set_mon_device", "set_obs_device"):
        monkeypatch.setattr(Engine, name, lambda self, n: None)
    e.reopen_all()
    assert seen == [CABLE_IN]


def test_window_starts_on_the_mic_with_the_cable_copy(qapp, app_dir, monkeypatch):
    """A whole start-up on the mic route with the effect working and a cable there
    (an upgraded 1.9.0 cable config): no crash, live in the mic, the copy opened."""
    from soundboard import engine as eng
    from soundboard import library, winkeys
    from soundboard.ui import mainwindow as main
    monkeypatch.setattr(dm, "status", lambda name=None: "outdated")
    monkeypatch.setattr(eng, "virtual_outputs", lambda: [CABLE_IN])
    for name in ("set_main_device", "set_mon_device", "set_mic_device"):
        monkeypatch.setattr(eng.Engine, name, lambda self, n, _k=name: setattr(
            self, "names", {**self.names, _k.split("_")[1]: n}))
    opened = []

    class Tap:   # an open cable copy (so the one-time tip runs during start-up too)
        def write(self, mix):
            pass

        def close(self):
            pass

    def set_tap(self, n):
        opened.append(n)
        self.tap_name, self.tap = n, (Tap() if n else None)
    monkeypatch.setattr(eng.Engine, "set_tap_device", set_tap)
    monkeypatch.setattr(winkeys.Hotkeys, "register", lambda self, m: None)
    raw = library.Config(setup_done=True, main_device=CABLE_IN).to_raw()
    raw["route"] = "cable"
    raw.pop("mic_first")   # saved by 1.9.0
    import json
    library.CONFIG_PATH.write_text(json.dumps(raw), encoding="utf-8")
    w = main.MainWindow()
    try:
        assert w.cfg.route == "mic" and w.cfg.mic_first
        assert w.engine.names["main"] == dm.DEVICE and opened and opened[-1] == CABLE_IN
        w._pill_short = False
        w._update_flow()
        assert "virtual cable" not in w.pill.text()
    finally:
        w._load_thread.join(15)
        w.close()
