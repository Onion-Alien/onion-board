"""Straight into my mic (soundboard.directmic + native/directmic/obmic.cpp).

The end-to-end tests run the real mic effect DLL in testhost.exe (built by
scripts/build_directmic.py --testhost), which loads it the way Windows' audio engine
does; they're skipped when it isn't built. Nothing touches the PC's audio devices.
"""
from __future__ import annotations

import os
import subprocess
import threading
import json
import time
from pathlib import Path

import numpy as np
import pytest

from conftest import own_module, real_pc_timing, said
from soundboard.ui import toast
from soundboard import directmic as dm
from test_mainwindow import window  # noqa: F401  (fixture)

_REAL_ELEVATED = dm._elevated   # (before the conftest guard replaces it)

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


@pytest.mark.windows   # looks the other board up with OpenProcess
def test_a_second_board_backs_off(ring_file, monkeypatch):
    """Two copies of the app (one on a test profile) never both write the mic's ring:
    the second one says so, and takes over once the first one has gone."""
    first = dm.DirectMicStream(lambda out, *a: out.fill(0.5), ring_file)
    first.start()
    try:
        time.sleep(0.05)
        real_getpid = dm.os.getpid
        other = real_getpid() + 1
        monkeypatch.setattr(dm.os, "getpid", lambda: other)   # another process
        with pytest.raises(RuntimeError, match="Another Onion Board"):
            dm.DirectMicStream(lambda out, *a: out.fill(0.1), ring_file)
        w = dm.RingWriter(ring_file)
        assert w._get("enabled") == 1   # the first one's ring was left alone
        w.close(owner=False)
    finally:
        # just this patch: monkeypatch's undo also drops every fixture's (the real
        # %APPDATA% guard's too)
        monkeypatch.setattr(dm.os, "getpid", real_getpid)
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


def test_make_ring_ok_while_a_board_writes(tmp_path):
    """A writing board locks a few bytes of the ring (claim). Checking the file must not
    read over them: a buffered read did, so the board's own ring looked bad (status
    "wiped", then a repair) and make_ring tried to replace a file in use."""
    p = tmp_path / "ring2.bin"
    assert dm.make_ring(p)
    w = dm.RingWriter(p)
    try:
        w.claim()
        assert dm.make_ring_ok(p)
        assert dm.make_ring(p)
    finally:
        w.close()


def test_make_ring_replaces_one_with_the_wrong_rate(tmp_path):
    """The effect plays the board's audio at the rate the file says: a damaged (or
    tampered) one with another rate the effect accepts, 44.1 kHz, played every sound
    at the wrong speed and pitch until it was made again. It's made again now."""
    p = tmp_path / "ring2.bin"
    assert dm.make_ring(p)
    raw = bytearray(p.read_bytes())
    head = np.frombuffer(raw, dm.HEAD, count=1)
    head["rate"] = 44100
    p.write_bytes(bytes(raw))
    assert not dm.make_ring_ok(p)
    assert dm.make_ring(p)
    assert np.frombuffer(p.read_bytes(), dm.HEAD, count=1)["rate"][0] == dm.RATE


def test_make_ring_leaves_another_processes_temp_alone(tmp_path):
    """The temp has a name of its own now: a stale one from the old fixed name (or
    another board making the ring at the same moment) is never written through."""
    p = tmp_path / "ring2.bin"
    stale = tmp_path / "ring2.new"
    stale.write_bytes(b"someone else's")
    assert dm.make_ring(p) and dm.make_ring_ok(p)
    assert stale.read_bytes() == b"someone else's"
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("values, expected", [
    ({}, ("wrap", 7)),                       # nothing: the endpoint effect (raw gets it)
    ({5: "{S}"}, ("wrap", 7)),               # the driver's SFX stays where it is
    ({7: "{E}", 1: "{E}"}, ("wrap", 7)),     # modern driver (a gaming headset): wrap its EFX
    ({1: "{L}"}, ("wrap", 1)),               # only old-style effects: LFX
    ({1: "{L}", 2: "{G}"}, ("wrap", 1)),
    ({13: ["{X}"], 5: "{S}"}, ("wrap", 7)),  # a stream effect list: left alone
    ({13: ["{X}"], 1: "{L}"}, ("wrap", 7)),
    ({15: ["{X}"], 7: "{E}"}, ("composite", 15)),   # an endpoint effect list: join it
])
def test_pick_slot(values, expected):
    assert dm.pick_slot(values) == expected


@pytest.mark.parametrize("values, pid, expected", [
    ({5: "{S}"}, 5, "{S}"),
    ({1: "{L}"}, 5, "{L}"),             # SFX switches the old LFX off: run it inside
    ({1: "{L}", 7: "{E}"}, 5, ""),      # ...unless an EFX still runs it before us
    ({7: "{E}", 1: "{E}"}, 7, "{E}"),   # EFX: the driver's own endpoint effect first
    ({1: "{L}", 5: "{S}"}, 7, "{L}"),   # no EFX: the LFX it switches off, inside
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
    "a gaming headset (EFX + old LFX)": {dm.FX % 7: ("{E}", SZ), dm.FX % 1: ("{E}", SZ),
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


@pytest.mark.parametrize("mic", MICS)
def test_an_uninstall_cut_off_anywhere_finishes_on_the_next_run(fake_reg, mic):
    """Taking it off killed part-way (a crash, a reboot): the effect may already be out
    of the slot while the rest of the change is still there. A second uninstall must
    still leave the mic exactly as it was (it used to see the effect gone from the slot
    and mistake it for Windows having reset the mic, leaving the rest changed)."""
    _mic(fake_reg, MICS[mic])
    before = {k: dict(v) for k, v in fake_reg.keys.items()}
    dm._install_endpoint(GUID, None)
    installed = {k: dict(v) for k, v in fake_reg.keys.items()}
    fake_reg.writes = 0
    dm._uninstall_endpoint(GUID)
    total = fake_reg.writes
    for n in range(1, total + 1):
        fake_reg.keys = {k: dict(v) for k, v in installed.items()}
        fake_reg.writes, fake_reg.kill_at = 0, n
        with pytest.raises(Killed):
            dm._uninstall_endpoint(GUID)
        fake_reg.kill_at = None
        for guid in fake_reg.installed_on():   # the retry (a later uninstall)
            dm._uninstall_endpoint(guid)
        assert fake_reg.mics() == {k: v for k, v in before.items() if v}, n
        assert not _all_ours(fake_reg) and not fake_reg.installed_on()


def test_repair_after_windows_reset_keeps_the_new_driver_effects(fake_reg):
    """A driver update / "Reset sound settings" rewrote the mic's effects: repairing and
    later taking it off leave the driver's new ones, not the stale ones from before."""
    _mic(fake_reg, MICS["a gaming headset (EFX + old LFX)"])
    dm._install_endpoint(GUID, None)
    fake_reg.keys[FXKEY.lower()] = {dm.FX % 7: ("{NEW}", SZ)}   # Windows reset it
    for guid in fake_reg.installed_on():   # what admin_install does: repair
        dm._uninstall_endpoint(guid)
    assert fake_reg.mics()[FXKEY.lower()] == {dm.FX % 7: ("{NEW}", SZ)}
    dm._install_endpoint(GUID, None)
    assert fake_reg.keys[dm.ENDPOINTS_KEY.lower() + "\\" + GUID.lower()]["Original"][0] == "{NEW}"
    dm._uninstall_endpoint(GUID)
    assert fake_reg.mics()[FXKEY.lower()] == {dm.FX % 7: ("{NEW}", SZ)}


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
    monkeypatch.setattr(dm, "_running_dependents", lambda: ["midisrv"])
    monkeypatch.setattr(dm, "_audio_comes_back", lambda deps: calls.append(("helper", deps)))
    monkeypatch.setattr(dm, "_audio_service",
                        lambda start, deps=(): calls.append((start, deps)) or True)
    monkeypatch.setattr(dm, "_register_com", lambda path: calls.append("com"))
    monkeypatch.setattr(dm, "_make_ring", lambda: None)
    _mic(fake_reg, MICS["a stream effect"])
    assert dm.admin_install(GUID) == 0
    # the services that ran on the audio (Windows' MIDI one...) come back with it
    assert calls == [("helper", ["midisrv"]), (False, ()), "com", (True, ["midisrv"])]
    assert list((tmp_path / "pf").iterdir()) and not list((tmp_path / "pf").glob("*.new"))
    calls.clear()
    fake_reg.kill_at = fake_reg.writes + 1
    with pytest.raises(Killed):
        dm.admin_install(GUID)
    assert calls[:2] == [("helper", ["midisrv"]), (False, ())]
    assert calls[-1] == (True, ["midisrv"])


def _restart_kit(fake_reg, monkeypatch, tmp_path, heard):
    """admin_install with the audio restart faked: `heard` is what each listen to the
    mic says, in turn (True: exact zeros, False: real sound, None: can't tell). The
    first is the listen before the step (_silent_before)."""
    calls = []
    dll = tmp_path / "obmic.dll"
    dll.write_bytes(b"dll")
    monkeypatch.setattr(dm, "bundled_dll", lambda: dll)
    monkeypatch.setattr(dm, "install_dir", lambda: tmp_path / "pf")
    for name in ("_enable_privileges", "_register_com", "_make_ring"):
        monkeypatch.setattr(dm, name, lambda *a: None)
    monkeypatch.setattr(dm, "_running_dependents", lambda: ["midisrv"])
    monkeypatch.setattr(dm, "_audio_comes_back", lambda deps: None)
    monkeypatch.setattr(dm, "_audio_service",
                        lambda start, deps=(): calls.append((start, deps)) or True)
    monkeypatch.setattr(dm, "_mic_is_silent",
                        lambda guid: calls.append(("listen", guid)) or heard.pop(0))
    monkeypatch.setattr(dm.time, "sleep", lambda s: None)
    _mic(fake_reg, MICS["a stream effect"])
    return calls


def test_a_mic_left_silent_by_the_restart_gets_one_more(fake_reg, monkeypatch, tmp_path):
    """A mic can come back from the audio restart sending only exact zeros (an app
    grabbed it the moment it was back), until the audio restarts again. So it's listened
    to after the restart: digital silence gets one more restart, then a second listen."""
    calls = _restart_kit(fake_reg, monkeypatch, tmp_path, [False, True, True, False])
    assert dm.admin_install(GUID) == 0
    assert calls == [("listen", GUID), (False, ()), (True, ["midisrv"]), ("listen", GUID),
                     ("listen", GUID), (False, ()), (True, ["midisrv"]), ("listen", GUID)]


def test_a_mic_still_waking_up_is_listened_to_again(fake_reg, monkeypatch, tmp_path):
    """Silent at first, then sound a moment later: just slow to start, no restart."""
    calls = _restart_kit(fake_reg, monkeypatch, tmp_path, [False, True, False])
    assert dm.admin_install(GUID) == 0
    assert calls == [("listen", GUID), (False, ()), (True, ["midisrv"]), ("listen", GUID),
                     ("listen", GUID)]


def test_a_mic_that_stays_silent_is_tried_a_few_times_then_reported(
        fake_reg, monkeypatch, tmp_path, caplog):
    """Still exact zeros after the extra restart: the audio restarts again, up to
    EXTRA_RESTARTS times, then the admin step says so (MIC_SILENT): the app must never
    call a set-up done while the mic sends nothing."""
    calls = _restart_kit(fake_reg, monkeypatch, tmp_path, [False] + [True] * 40)
    assert dm.admin_install(GUID) == dm.MIC_SILENT
    stops = [c for c in calls if c[0] is False]
    assert len(stops) == 1 + dm.EXTRA_RESTARTS
    assert "still sends only silence" in caplog.text


def test_a_mic_back_on_a_later_restart_stops_the_restarts(fake_reg, monkeypatch, tmp_path):
    calls = _restart_kit(fake_reg, monkeypatch, tmp_path,
                         [False, True, True, True, True, False])
    assert dm.admin_install(GUID) == 0
    assert len([c for c in calls if c[0] is False]) == 3   # the set-up's and two more


def test_a_silent_mic_never_hides_a_failed_step(fake_reg, monkeypatch, tmp_path):
    """The step's own failure is what it reports, silent mic or not."""
    _restart_kit(fake_reg, monkeypatch, tmp_path, [True] * 40)
    monkeypatch.setattr(dm, "_put_on", lambda *a: 1)
    assert dm.admin_install(GUID) == 1


@pytest.mark.parametrize("heard", [False, None])
def test_a_working_or_unknown_mic_is_left_alone(fake_reg, monkeypatch, tmp_path, heard):
    """Real sound, or can't tell (muted, at 0%, not back yet): no extra restart."""
    calls = _restart_kit(fake_reg, monkeypatch, tmp_path, [False, heard])
    assert dm.admin_install(GUID) == 0
    assert calls == [("listen", GUID), (False, ()), (True, ["midisrv"]), ("listen", GUID)]


@pytest.mark.parametrize("op", ["install", "reinstall"])
def test_a_mic_already_silent_before_gets_no_extra_restarts(fake_reg, monkeypatch,
                                                           tmp_path, caplog, op):
    """Only zeros before the step too (a headset switched off, or its mic muted): not
    the step's doing. Restarting the audio again only cut everyone's sound (up to four
    times) and then blamed the step; it's done, and the card says the mic is silent."""
    caplog.set_level("INFO", logger=dm.log.name)
    calls = _restart_kit(fake_reg, monkeypatch, tmp_path, [True] * 40)
    step = dm.admin_install if op == "install" else dm.admin_reinstall
    assert step(GUID) == 0
    assert len([c for c in calls if c[0] is False]) == 1   # the step's own restart only
    assert "switched off or muted?" in caplog.text


def test_a_retry_after_a_silent_mic_still_restarts_for_it(fake_reg, monkeypatch, tmp_path):
    """The step left the mic silent (MIC_SILENT): on the retry it's silent before the
    step too, but that's the stuck mic the retry is for, so it still gets the restarts."""
    calls = _restart_kit(fake_reg, monkeypatch, tmp_path, [False] + [True] * 40)
    dm.data_dir().mkdir(parents=True, exist_ok=True)   # (the admin step secures it first)
    assert dm.admin_install(GUID) == dm.MIC_SILENT
    assert dm._left_silent() == {GUID.lower()}
    calls.clear()
    _restart_kit(fake_reg, monkeypatch, tmp_path, [True] * 5 + [False])
    assert dm.admin_reinstall(GUID) == 0   # silent before, back after the extra restarts
    assert dm._left_silent() == set()      # it's working: forgotten


def test_an_old_silent_note_is_no_retry(fake_reg, monkeypatch, tmp_path):
    calls = _restart_kit(fake_reg, monkeypatch, tmp_path, [True] * 40)
    (dm.data_dir()).mkdir(parents=True, exist_ok=True)
    (dm.data_dir() / dm.LEFT_SILENT).write_text(json.dumps(
        {"at": time.time() - dm.RETRY_S - 5, "mics": [GUID]}), encoding="utf-8")
    assert dm.admin_install(GUID) == 0
    assert len([c for c in calls if c[0] is False]) == 1   # silent before: left alone


def test_the_uninstall_listens_to_the_mic_it_took_the_effect_off(fake_reg, monkeypatch,
                                                                 tmp_path):
    calls = _restart_kit(fake_reg, monkeypatch, tmp_path,
                         [False, False, False, True, True, False])
    assert dm.admin_install(GUID) == 0
    calls.clear()
    assert dm.admin_uninstall() == 0
    assert not fake_reg.installed_on()
    assert calls == [("listen", GUID), (False, ()), (True, ["midisrv"]), ("listen", GUID),
                     ("listen", GUID), (False, ()), (True, ["midisrv"]), ("listen", GUID)]


def test_no_listen_when_the_audio_never_stopped(fake_reg, monkeypatch, tmp_path):
    calls = _restart_kit(fake_reg, monkeypatch, tmp_path, [False])
    monkeypatch.setattr(dm, "_audio_service", lambda start, deps=(): start)   # stop fails
    assert dm.admin_install(GUID) == 6
    assert calls == [("listen", GUID)]   # only the one before the step


def test_a_failing_listen_never_fails_the_install(fake_reg, monkeypatch, tmp_path):
    _restart_kit(fake_reg, monkeypatch, tmp_path, [])

    def broken(guid):
        raise OSError("no audio")
    monkeypatch.setattr(dm, "_mic_is_silent", broken)
    assert dm.admin_install(GUID) == 0


def test_a_failed_set_up_puts_the_mic_back(fake_reg, monkeypatch, tmp_path):
    """An error half-way through putting it on the mic (not the process dying): the
    mic goes back as it was before the admin step says it failed."""
    dll = tmp_path / "obmic.dll"
    dll.write_bytes(b"dll")
    monkeypatch.setattr(dm, "bundled_dll", lambda: dll)
    monkeypatch.setattr(dm, "install_dir", lambda: tmp_path / "pf")
    for name in ("_enable_privileges", "_register_com", "_make_ring"):
        monkeypatch.setattr(dm, name, lambda *a: None)
    monkeypatch.setattr(dm, "_running_dependents", lambda: [])
    monkeypatch.setattr(dm, "_audio_comes_back", lambda deps: None)
    monkeypatch.setattr(dm, "_audio_service", lambda start, deps=(): True)
    _mic(fake_reg, MICS["a gaming headset (EFX + old LFX)"])
    before = fake_reg.mics()
    real = dm._install_endpoint

    def broken(guid, slot):
        real(guid, slot)
        raise OSError("disk went away")
    monkeypatch.setattr(dm, "_install_endpoint", broken)
    with pytest.raises(OSError):
        dm.admin_install(GUID)
    assert fake_reg.mics() == before and not fake_reg.installed_on()


def test_audio_restart_brings_back_what_depended_on_it(monkeypatch):
    ran = []
    monkeypatch.setattr(dm, "_run", lambda cmd, timeout=60.0: ran.append(cmd) or 0)
    dm._audio_service(True, ["midisrv", "AarSvc_1a2b", "bad name; rm"])
    assert ran == [["net", "start", "AudioEndpointBuilder"], ["net", "start", "audiosrv"],
                   ["net", "start", "midisrv"], ["net", "start", "AarSvc_1a2b"]]


def test_a_stop_that_wont_take_is_retried_then_reported(monkeypatch):
    """The endpoint builder only re-reads a mic's effects when it starts, so a stop
    that silently failed matters: it's tried once more, and said so if it still won't."""
    ran, stopped = [], [False]
    monkeypatch.setattr(dm, "_run", lambda cmd, timeout=60.0: ran.append(cmd) or 0)
    monkeypatch.setattr(dm, "_services_stopped", lambda: stopped[0])
    assert dm._audio_service(False) is False
    assert [c[2] for c in ran] == ["audiosrv", "AudioEndpointBuilder", "AudioEndpointBuilder"]
    ran.clear()
    stopped[0] = True
    assert dm._audio_service(False) is True
    assert [c[2] for c in ran] == ["audiosrv", "AudioEndpointBuilder"]   # no retry needed


def test_which_services_depend_on_the_audio(monkeypatch):
    out = "midisrv\nAarSvc_1a2b\nAudiosrv\n\nmidisrv\nodd name\n"
    monkeypatch.setattr(dm.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, out, ""))
    assert dm._running_dependents() == ["midisrv", "AarSvc_1a2b"]

    def hang(*a, **k):
        raise subprocess.TimeoutExpired(a, 30)
    monkeypatch.setattr(dm.subprocess, "run", hang)
    assert dm._running_dependents() == []


def test_a_hung_command_is_stopped(monkeypatch):
    def hang(*a, **k):
        raise subprocess.TimeoutExpired(a, k.get("timeout"))
    monkeypatch.setattr(dm.subprocess, "run", hang)
    assert dm._run(["net", "stop", "audiosrv", "/y"], timeout=1) == -1


def test_a_tool_answering_in_another_code_page_is_read(monkeypatch):
    """A German Windows tool's "ü" is byte 0x81 in its code page, which the default text
    decoding can't read: that raised instead of returning the exit code."""
    import sys
    monkeypatch.setattr(dm, "_CREATE_NO_WINDOW", 0)
    cmd = [sys.executable, "-c",
           "import sys; sys.stdout.buffer.write(b'Ger\\x81t nicht gefunden'); sys.exit(3)"]
    assert dm._run(cmd, timeout=30) == 3


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


def test_publisher_change_restores_the_lead_without_a_stale_heartbeat(ring_file):
    stream = dm.DirectMicStream(lambda out, *args: out.fill(0.4), ring_file)
    stream.active = True
    ring = stream._ring
    try:
        ring._set("publisher", 1)
        _publish(ring, np.zeros((480, 2), np.float32))
        stream.pump()
        slot = ring.slots[0]
        slot["owner"], slot["tick"] = 2, dm._tick()
        slot["read_pos"], slot["lead"] = ring.write_pos + 480, 960
        target = int(slot["read_pos"]) + int(slot["lead"]) + 2 * dm.BLOCK
        # The new effect takes over inside MIC_LIVE_MS; the board never went idle.
        ring._set("publisher", 2)
        _publish(ring, np.zeros((480, 2), np.float32))
        stream.pump()
        assert stream.mic_live and stream._publisher == 2
        assert ring.write_pos == target
        assert np.all(ring.data[:target] == 0)
        _publish(ring, np.zeros((480, 2), np.float32))
        stream.pump()
        assert np.allclose(ring.data[target:target + 480], 0.4)
    finally:
        stream.close()


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


def test_stream_renders_whole_blocks_ahead_while_the_effect_reads(ring_file):
    """The effect runs but sends no clean mic (it reads on its own clock): the ring stays
    a block ahead, rendered a whole block (10 ms) at a time, about 100 engine calls a
    second. In small steps every 2 ms it was 400, four times the CPU, and the window
    froze waiting for the audio thread."""
    calls, ahead = [], []
    s = dm.DirectMicStream(lambda out, frames, t, status: (calls.append(frames),
                                                           out.fill(0))[1], ring_file)
    w = dm.RingWriter(ring_file)
    stop = threading.Event()

    def effect():   # alive, reading LEAD_S (20 ms) behind the board
        t0, start = time.perf_counter(), w.write_pos - int(dm.LEAD_S * dm.RATE)
        while not stop.is_set():
            slot = w.slots[0]
            slot["owner"], slot["tick"] = 2, dm._tick()
            slot["read_pos"] = start + int((time.perf_counter() - t0) * dm.RATE)
            ahead.append(w.write_pos - int(slot["read_pos"]))
            time.sleep(0.01)
    t = threading.Thread(target=effect, daemon=True)
    try:
        s.start()
        time.sleep(0.1)
        t.start()
        time.sleep(0.2)
        calls.clear()
        ahead.clear()
        time.sleep(1.0)
    finally:
        stop.set()
        t.join()
        w.close()
        s.close()
    assert set(calls) == {dm.BLOCK}, set(calls)
    assert 50 <= len(calls) <= 150, len(calls)
    assert min(ahead) >= 0, min(ahead)   # never behind the effect


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


def test_a_mic_callback_that_fails_once_doesnt_stop_the_feed(ring_file):
    """One exception from the mic callback ended the feed's thread for good, silently:
    that block is lost, and the next ones still go to the callback and out."""
    got, made = [], []

    def mic_cb(x, rate):
        got.append(len(x))
        if len(got) == 1:
            raise RuntimeError("boom")

    def cb(out, frames, t, status):
        out.fill(0.5)
        made.append(frames)

    s = dm.DirectMicStream(cb, ring_file, mic_callback=mic_cb)
    w = dm.RingWriter(ring_file)
    try:
        s.active = True   # no thread: pump by hand
        x = np.zeros((480, 2), np.float32)
        _publish(w, x)
        s.pump()          # (finds where the mic is)
        for _ in range(3):
            _publish(w, x)
            assert s.pump()
        assert got == [480] * 3 and sum(made) == 3 * 480
    finally:
        w.close()
        s.close()


def test_the_feeds_thread_goes_on_after_an_exception(ring_file, monkeypatch):
    s = dm.DirectMicStream(lambda out, *a: out.fill(0), ring_file)
    calls = []

    def pump():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        if len(calls) == 3:
            s._stop.set()
        return True

    monkeypatch.setattr(s, "pump", pump)
    monkeypatch.setattr(dm.time, "sleep", lambda t: None)
    try:
        s._run()   # the thread's loop, here: it used to end at the first exception
        assert len(calls) == 3
    finally:
        s.close()


def test_the_engines_clean_mic_failing_is_counted_not_fatal():
    """Engine._mic_direct is guarded like the device mic's callback: the failure shows
    in cb_errors and errors (so the window can say so), and the next block goes in."""
    from soundboard.engine import Engine
    e = Engine()
    seen = []

    def mic(x, direct=False):
        seen.append(direct)
        if len(seen) == 1:
            raise RuntimeError("boom")

    e._mic = mic
    block = np.zeros((480, 2), np.float32)
    e._mic_direct(block, e.rates["mic"])   # raised out of the feed's thread before
    e._mic_direct(block, e.rates["mic"])
    assert seen == [True, True]
    assert e.cb_errors["mic"] == 1 and "boom" in e.errors["mic"]


def test_stream_knows_how_long_the_mic_sent_only_silence(ring_file, monkeypatch):
    """A mic stuck sending exact zeros (after an audio restart Windows thinks went fine)
    is seen for free in the clean mic the effect already hands over: how long it's been
    nothing but zeros, back to 0 at the first real sample or when it stops coming."""
    clock = [100.0]
    monkeypatch.setattr(dm.time, "perf_counter", lambda: clock[0])
    s = dm.DirectMicStream(lambda out, *a: out.fill(0), ring_file)
    w = dm.RingWriter(ring_file)
    try:
        s.active = True
        zeros = np.zeros((480, 2), np.float32)
        assert s.mic_silent_s() == 0.0   # no clean mic at all: can't tell
        _publish(w, zeros)
        s.pump()          # (finds where the mic is)
        _publish(w, zeros)
        s.pump()
        clock[0] += 25.0
        _publish(w, zeros)
        s.pump()
        assert s.mic_silent_s() == pytest.approx(25.0)
        _publish(w, np.full((480, 2), 1e-6, np.float32))   # the faintest real sound
        s.pump()
        assert s.mic_silent_s() == 0.0
        _publish(w, zeros)
        s.pump()
        clock[0] += 5.0
        assert s.mic_silent_s() == pytest.approx(5.0)
        w.h[0]["mic_tick"] = dm._tick() - 10 * dm.MIC_LIVE_MS   # nobody records it now
        s.pump()
        assert s.mic_silent_s() == 0.0
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


def test_mic_rate_goes_back_to_the_devices_when_the_clean_mic_stops(ring_file):
    """The clean mic from the mic effect switched the board's mic to the effect's rate,
    and nothing switched it back: once it stopped, the mic device's 44.1 kHz blocks were
    taken as 48 kHz (mic check, voice effects and recordings at the wrong pitch)."""
    from soundboard.engine import Engine
    e = Engine()
    e.rates["main"] = e.rates["mon"] = e.rates["obs"] = 48000
    e._mic_dev_rate = e.rates["mic"] = 44100   # the mic device's rate
    e._reconfigure_mic_resamplers()
    s = dm.DirectMicStream(lambda out, *a: out.fill(0), ring_file,
                           mic_callback=e._mic_direct, mic_stopped=e._mic_direct_stopped)
    w = dm.RingWriter(ring_file)
    try:
        s.active = True
        block = np.zeros((480, 2), np.float32)
        _publish(w, block)
        s.pump()          # (finds where the mic is)
        _publish(w, block)
        s.pump()
        assert s.mic_live and e.rates["mic"] == 48000 and e._rs_main.src == 48000
        w.h[0]["mic_tick"] = dm._tick() - 10 * dm.MIC_LIVE_MS   # the clean mic stops
        s.pump()
        assert not s.mic_live
        assert e.rates["mic"] == 44100
        assert all((r.src, r.dst) == (44100, 48000) for r in (e._rs_main, e._rs_mon, e._rs_obs))
        _publish(w, block)   # live again, then the stream closes while it is
        s.pump()
        _publish(w, block)
        s.pump()
        assert e.rates["mic"] == 48000
    finally:
        w.close()
        s.close()
    assert e.rates["mic"] == 44100 and e._rs_main.src == 44100


def test_the_device_mic_is_taken_under_the_feeds_lock(ring_file):
    """While straight-into-the-mic is on, the mic device's block runs under the feed's
    lock: its thread can go live on the clean mic (and switch the mic's rate) meanwhile,
    and _mic ran on both threads at once at that flip."""
    from soundboard.engine import Engine
    e = Engine()
    s = dm.DirectMicStream(lambda out, *a: out.fill(0), ring_file)
    e.main_direct, e.main_stream = True, s
    held = []
    e._mic = lambda x, direct=False: held.append(s.lock.locked())
    try:
        e._cb_mic(np.zeros((480, 1), np.float32), 480, None, None)
        assert held == [True]
        s.lock.acquire()   # the feed's thread is at it and goes live meanwhile
        s.mic_live = True
        threading.Timer(0.005, s.lock.release).start()
        e._cb_mic(np.zeros((480, 1), np.float32), 480, None, None)
        assert held == [True]   # the clean mic carries that block now
    finally:
        e.main_stream = None
        s.mic_live = False
        s.close()


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
@real_pc_timing
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


@needs_host
@pytest.mark.parametrize("instances", [1, 2])
@realtime
def test_audio_engine_restart_keeps_the_board_on_the_mic(ring_file, instances, monkeypatch):
    """Windows' audio engine exits and reloads the effect while the board keeps sending."""
    from soundboard.engine import Engine
    from test_engine import tone
    monkeypatch.setattr(dm, "ring_path", lambda: ring_file)
    engine = Engine()
    engine.set_main_device(dm.DEVICE)
    engine.play("tone", tone(10), 1.0)
    env = dict(os.environ, ProgramData=str(ring_file.parent.parent.parent))
    processes = []
    try:
        for index in range(2):
            out = ring_file.parent / f"restart-{index}.f32"
            p = subprocess.Popen([str(HOST), str(DLL), str(out), "48000", "1", "2",
                                  "0.3", str(instances), "300"], env=env, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True)
            processes.append(p)
            if index == 0:
                time.sleep(0.7)
                p.kill()
                p.communicate(timeout=5)
            else:
                log, _ = p.communicate(timeout=10)
                assert p.returncode == 0, log
                for app in range(instances):
                    path = out if app == 0 else Path(f"{out}.{app}")
                    samples = np.fromfile(path, np.float32)[48000:]
                    assert len(samples) == 48000
                    t = np.arange(len(samples)) / dm.RATE
                    level = 2 * abs(np.mean(samples * np.exp(-2j * np.pi * 440 * t)))
                    assert level > 0.1
    finally:
        for p in processes:
            if p.poll() is None:
                p.kill()
                p.communicate(timeout=5)
        engine.shutdown()


@needs_host
@pytest.mark.parametrize("gap", [0.0, 0.005])
@realtime
def test_a_quick_reopen_keeps_the_board_on_the_mic(ring_file, gap):
    """The stream closed and opened again at once (a buffering change reopens every
    stream): the effect read on meanwhile, and the board, paced by the mic, never got
    a lead ahead of it again. Its sounds stayed off the mic until the app restarted."""
    board = Echo(gain=0.0, tone=0.4)   # the board sends only a tone
    held = []

    def during(s):
        time.sleep(0.7)
        s.close()
        time.sleep(gap)
        s2 = dm.DirectMicStream(board, ring_file, mic_callback=board.mic, mode=dm.MODE_REPLACE)
        s2.start()
        held.append(s2)

    try:
        (x,), _, _ = _run_host(ring_file, 48000, 1, 2.5, mic=0.3, mic_hz=-1, callback=board,
                               mic_callback=board.mic, mode=dm.MODE_REPLACE, during=during)
    finally:
        for s in held:
            s.close()
    y = x[int(1.5 * 48000):int(2.4 * 48000), 0]
    t = np.arange(len(y)) / 48000
    assert 2 * abs(np.mean(y * np.exp(-2j * np.pi * 440 * t))) > 0.3   # the tone, not the mic


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
        e.sending = False   # "Others hear" off: your plain voice still goes (mic_only)...
        _publish(w, np.full((480, 2), 0.2, np.float32))
        s.pump()
        assert abs(w.h[0]["mic_gain"] - 0.7) < 1e-6
        e.mic_enabled = False   # ...unless it isn't sent
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
    (["{a}"], False, True, True, "wiped"),       # its DLL deleted: repaired, not "fine"
    (["{a}"], None, True, True, "wiped"),        # its registration gone
])
@pytest.mark.parametrize("slot", [None, 7])
def test_status(monkeypatch, tmp_path, on, here, in_place, same, expected, slot):
    dll = tmp_path / "obmic-1.dll"
    if here:
        dll.write_bytes(b"dll")
    monkeypatch.setattr(dm, "installed_slot", lambda guid: slot)
    monkeypatch.setattr(dm, "installed_on", lambda: on)
    monkeypatch.setattr(dm, "endpoint_for", lambda name: "{a}")
    monkeypatch.setattr(dm, "effect_in_place", lambda guid: in_place)
    monkeypatch.setattr(dm, "same_dll", lambda a, b: same)
    monkeypatch.setattr(dm, "registered_dll", lambda: None if here is None else dll)
    monkeypatch.setattr(dm, "make_ring", lambda path=None: True)
    dm.forget_status()
    assert dm.status("My mic") == expected
    assert dm.needs_repair(expected) == (expected == "wiped")
    assert dm.works(expected) == (expected in ("ready", "outdated"))


@pytest.mark.parametrize("slot, expected", [(5, "outdated"), (13, "outdated"), (1, "ready"),
                                            (7, "ready"), (15, "ready")])
def test_status_offers_the_move_out_of_the_stream_effect(monkeypatch, tmp_path, slot,
                                                         expected):
    """On in the stream effect (before the endpoint one), raw streams (Chrome, Edge,
    Discord Studio) skip it: the update that moves it is offered."""
    dll = tmp_path / "obmic-1.dll"
    dll.write_bytes(b"dll")
    monkeypatch.setattr(dm, "installed_on", lambda: ["{a}"])
    monkeypatch.setattr(dm, "endpoint_for", lambda name: "{a}")
    monkeypatch.setattr(dm, "effect_in_place", lambda guid: True)
    monkeypatch.setattr(dm, "same_dll", lambda a, b: True)
    monkeypatch.setattr(dm, "registered_dll", lambda: dll)
    monkeypatch.setattr(dm, "make_ring", lambda path=None: True)
    monkeypatch.setattr(dm, "installed_slot", lambda guid: slot)
    dm.forget_status()
    assert dm.status("My mic") == expected
    assert dm.endpoint_wide() == (slot in (7, 15))


def test_a_gaming_headset_gets_it_in_the_endpoint_effect(fake_reg):
    _mic(fake_reg, MICS["a gaming headset (EFX + old LFX)"])
    dm._install_endpoint(GUID, None)
    fx = fake_reg.keys[FXKEY.lower()]
    state = fake_reg.keys[dm.ENDPOINTS_KEY.lower() + "\\" + GUID.lower()]
    assert fx[dm.FX % 7][0] == dm.CLSID and dm.FX % 1 not in fx
    assert state["Original"][0] == "{E}" and state["Slot"][0] == 7


def test_a_mic_without_effects_gets_the_endpoint_modes(fake_reg):
    dm._install_endpoint(GUID, None)
    fx = fake_reg.keys[FXKEY.lower()]
    assert fx[dm.FX % 7][0] == dm.CLSID
    assert fx[dm.MODES_KEY % 7][0] == [dm.MODE_DEFAULT]
    dm._uninstall_endpoint(GUID)
    assert not fake_reg.mics()


def test_same_dll(tmp_path):
    a, b, c = tmp_path / "a.dll", tmp_path / "b.dll", tmp_path / "c.dll"
    a.write_bytes(b"one")
    b.write_bytes(b"one")
    c.write_bytes(b"two")
    assert dm.same_dll(a, b) and not dm.same_dll(a, c)
    assert not dm.same_dll(None, b) and not dm.same_dll(tmp_path / "gone.dll", b)
    assert dm.same_dll(a, tmp_path / "none-of-ours.dll")   # a build without one: fine


def test_uninstaller_asks_nothing_when_nothing_is_installed(monkeypatch):
    from soundboard import michelper
    monkeypatch.setattr(dm, "anything_installed", lambda: False)
    monkeypatch.setattr(michelper, "leftover", lambda: False)   # no helper either
    assert dm.cli(["remove"]) == 0   # (_elevated would raise: the conftest guard)


def test_uninstaller_takes_it_off_the_mic(monkeypatch):
    asked = []
    monkeypatch.setattr(dm, "anything_installed", lambda: True)
    monkeypatch.setattr(dm, "_is_admin", lambda: False)
    monkeypatch.setattr(dm, "_elevated", lambda args, wait_s=90.0, **k: asked.append(args) or 0)
    assert dm.cli(["remove"]) == 0 and asked == [["remove-all"]]
    monkeypatch.setattr(dm, "_elevated", lambda args, wait_s=90.0, **k: None)   # turned down
    assert dm.cli(["remove"]) == 1


def test_uninstall_keeps_going_when_one_mic_wont_go_back(monkeypatch):
    """One mic that can't be put back (a locked value, say) mustn't strand the others,
    and mustn't unregister the effect out from under it: everything is left as it is
    for a later uninstall to finish."""
    tried, com = [], []
    other = "{22222222-3333-4444-5555-666666666666}"
    monkeypatch.setattr(dm, "_enable_privileges", lambda *a: None)
    monkeypatch.setattr(dm, "_running_dependents", lambda: [])
    monkeypatch.setattr(dm, "_audio_comes_back", lambda deps=(): None)
    monkeypatch.setattr(dm, "_audio_service", lambda start, deps=(): True)
    monkeypatch.setattr(dm, "installed_on", lambda: [GUID, other])
    monkeypatch.setattr(dm, "_unregister_com", lambda: com.append("com"))

    def take(guid):
        tried.append(guid)
        if guid != GUID:
            raise OSError("the mic's registry is locked")
    monkeypatch.setattr(dm, "_uninstall_endpoint", take)
    assert dm.admin_uninstall() == 1
    assert tried == [GUID, other]   # the second mic was still tried
    assert com == []                # the effect wasn't unregistered while it's on a mic


def test_uninstall_removes_the_ring_folder(monkeypatch, tmp_path):
    """A clean uninstall takes the ring file with it, not just the mic and the keys."""
    d = tmp_path / "MicPlugin"
    d.mkdir()
    (d / "ring2.bin").write_bytes(b"x")
    monkeypatch.setattr(dm, "_enable_privileges", lambda *a: None)
    monkeypatch.setattr(dm, "_running_dependents", lambda: [])
    monkeypatch.setattr(dm, "_audio_comes_back", lambda deps=(): None)
    monkeypatch.setattr(dm, "_audio_service", lambda start, deps=(): True)
    monkeypatch.setattr(dm, "installed_on", lambda: [])
    monkeypatch.setattr(dm, "_unregister_com", lambda: None)
    monkeypatch.setattr(dm, "install_dir", lambda: tmp_path / "pf")
    monkeypatch.setattr(dm, "_old_install_dirs", lambda: [])
    monkeypatch.setattr(dm, "data_dir", lambda: d)
    monkeypatch.setattr(dm.winreg, "DeleteKey", lambda *a: None)
    assert dm.admin_uninstall() == 0
    assert not d.exists()


def test_cli_refuses_odd_arguments():
    assert dm.cli(["install", "not-a-guid"]) == 2
    assert dm.cli(["install", "{00000000-0000-0000-0000-000000000000}", "efx"]) == 2
    assert dm.cli(["frobnicate"]) == 2


@pytest.mark.windows   # Windows' named mutex
def test_one_admin_step_at_a_time(monkeypatch):
    monkeypatch.setattr(dm, "_LOCK_NAME", "Local\\OnionBoardMicEffectTest")
    held = dm._admin_lock()
    assert held is not None
    other = []
    t = threading.Thread(target=lambda: other.append(dm._admin_lock()))
    t.start()
    t.join()
    assert other == [None]   # another copy is at it
    dm._release(held)
    t = threading.Thread(target=lambda: other.append(dm._admin_lock()))
    t.start()
    t.join()
    assert other[-1] is not None
    dm._release(other[-1])
    monkeypatch.setattr(dm, "_admin_lock", lambda: None)
    assert dm.cli(["uninstall"]) == 4


def test_a_data_folder_that_cant_be_made_safe_stops_the_admin_step(monkeypatch):
    ran = []
    monkeypatch.setattr(dm, "_admin_lock", lambda: "lock")
    monkeypatch.setattr(dm, "_release", lambda h: ran.append("released"))
    monkeypatch.setattr(dm, "_enable_privileges", lambda *a: None)

    def unsafe():
        raise PermissionError("not a plain folder")
    monkeypatch.setattr(dm, "secure_data_dirs", unsafe)
    monkeypatch.setattr(dm, "admin_uninstall", lambda: ran.append("uninstall") or 0)
    assert dm.cli(["uninstall"]) == 5 and ran == ["released"]


def test_a_cut_short_name_two_mics_share_picks_neither(monkeypatch):
    mics = [{"guid": "{a}", "name": "Microphone (USB Audio Device)", "active": True},
            {"guid": "{b}", "name": "Microphone (USB Audio Device 2)", "active": True},
            {"guid": "{c}", "name": "Headset Microphone (USB headset)", "active": True}]
    monkeypatch.setattr(dm, "capture_endpoints", lambda: mics)
    assert dm.endpoint_for("Microphone (USB Audio Device)") == "{a}"   # exact wins
    assert dm.endpoint_for("Microphone (USB Audio") is None             # which one?
    assert dm.endpoint_for("Headset Microphone (USB") == "{c}"


# ---------------------------------------------------------------------- the data folder
# The admin step writes into %ProgramData%, where anyone signed in can make folders:
# it must never be steered through a link someone planted there.

def _junction(link, target):
    import _winapi
    _winapi.CreateJunction(str(target), str(link))


def _dacl(path) -> str:
    """The folder's access list as stored (GetFileSecurityW: the raw descriptor, not
    GetNamedSecurityInfo's version, which re-works it against the parent folder)."""
    import ctypes
    from ctypes import wintypes
    advapi = ctypes.WinDLL("advapi32")
    kernel = ctypes.WinDLL("kernel32")
    advapi.GetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p,
                                        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_wchar_p),
        ctypes.c_void_p]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    buf = ctypes.create_string_buffer(8192)
    need = wintypes.DWORD()
    assert advapi.GetFileSecurityW(str(path), 4, buf, len(buf), ctypes.byref(need))
    text = ctypes.c_wchar_p()
    assert advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(buf, 1, 4,
                                                                       ctypes.byref(text), None)
    value = text.value
    kernel.LocalFree(text)
    return value


_TEST_SDDL = "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;AU)"   # no owner: not admin


@pytest.mark.windows   # Windows' links and access lists
def test_a_planted_link_is_replaced_not_followed(tmp_path):
    victim = tmp_path / "Windows"
    victim.mkdir()
    (victim / "system.ini").write_text("keep")
    before = _dacl(victim)
    link = tmp_path / "MicPlugin"
    _junction(link, victim)
    dm._secure_dir(link, _TEST_SDDL)
    assert not dm._is_link(link) and link.is_dir() and not list(link.iterdir())
    assert (victim / "system.ini").read_text() == "keep" and _dacl(victim) == before


@pytest.mark.windows   # Windows' access lists
def test_the_folder_gets_exactly_its_access_and_nothing_inside_changes(tmp_path):
    d = tmp_path / "MicPlugin"
    (d / "inside").mkdir(parents=True)
    inside = _dacl(d / "inside")
    dm._secure_dir(d, _TEST_SDDL)
    assert _dacl(d) == _TEST_SDDL
    assert _dacl(d / "inside") == inside   # no walk through what's in it


def test_the_mic_folder_lets_users_write_files_but_not_swap_it():
    """MicPlugin: signed-in users and the audio engine make and change files, but can't
    delete or rename the folder itself, or make folders in it."""
    sddl = dm._MIC_SDDL
    for sid in ("AU", "LS", "WR"):
        assert f"(A;;{dm._FOLDER_WRITE};;;{sid})" in sddl
        assert f"(A;OICIIO;{dm._MODIFY};;;{sid})" in sddl
    rights = int(dm._FOLDER_WRITE, 16)
    assert rights & 0x2 and not rights & 0x4                  # files yes, subfolders no
    assert not rights & 0x10000 and not rights & 0x40         # no DELETE, no DELETE_CHILD
    assert dm._BASE_SDDL.startswith("O:BAD:P") and "AU" not in dm._BASE_SDDL


@pytest.mark.windows   # Windows' access lists
def test_the_admin_log_folder_drops_what_others_left(tmp_path, monkeypatch):
    base = tmp_path / "OnionBoard"
    (base / "MicPlugin").mkdir(parents=True)
    outside = tmp_path / "hosts"
    outside.write_text("keep")
    os.link(outside, base / "directmic-admin.log")        # a hard link to a system file
    _junction(base / "planted", tmp_path)
    (base / "mine.log").write_text("x")
    owners = {"mine.log": "S-1-5-32-544"}
    monkeypatch.setattr(dm, "_owner", lambda p: owners.get(p.name, "S-1-5-21-1-2-3-1001"))
    dm._clean_base(base)
    assert sorted(p.name for p in base.iterdir()) == ["MicPlugin", "mine.log"]
    assert outside.read_text() == "keep" and (tmp_path / "hosts").exists()


def test_the_admin_ring_never_writes_through_a_link(tmp_path, monkeypatch):
    d = tmp_path / "MicPlugin"
    d.mkdir()
    monkeypatch.setattr(dm, "data_dir", lambda: d)
    monkeypatch.setattr(dm, "ring_path", lambda: d / "ring2.bin")
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"keep")
    os.link(outside, d / "ring2.bin")
    dm._make_ring()
    assert dm.make_ring_ok(d / "ring2.bin")
    assert outside.read_bytes() == b"keep"
    assert not list(d.glob("*.tmp"))


def test_who_is_listening_looks_at_the_mic_itself(window, monkeypatch):  # noqa: F811
    """The simple sound modes find Discord / the game by who records the voice
    device: with straight into my mic that's the real mic, not the cable."""
    w = window
    w.cfg.route = "mic"
    w.cfg.mic_device = "Microphone (Test Headset)"
    monkeypatch.setattr(w.engine, "direct_stream", lambda: object())
    from soundboard import engine as eng
    monkeypatch.setattr(eng, "virtual_outputs", lambda: [])
    assert w.appsetctl._heard_device() == ("Microphone (Test Headset)",)
    monkeypatch.setattr(eng, "virtual_outputs", lambda: ["CABLE Input (VB-Audio Virtual Cable)"])
    monkeypatch.setattr(eng, "virtual_mic_for",   # (no real cable needed: CI has none)
                        lambda name: name and name.replace("Input", "Output"))
    # a voice app still set to the cable counts too
    assert w.appsetctl._heard_device() == ("Microphone (Test Headset)",
                                 "CABLE Output (VB-Audio Virtual Cable)")
    monkeypatch.setattr(w.engine, "direct_stream", lambda: None)
    assert w.appsetctl._heard_device() is None   # not sending into it: nobody hears the board there
    w.cfg.route = "cable"
    monkeypatch.setattr(dm, "status", lambda name=None: "missing")
    assert w.appsetctl._heard_device() != "Microphone (Test Headset)"


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
    assert w.routectl._main_name() == CABLE_IN
    _routes(w, monkeypatch, state, cables=())
    assert w.routectl._main_name() is None   # no cable either: nothing to send into
    w.cfg.main_device = CABLE_IN   # one picked once, not installed now: still nothing
    assert w.routectl._main_name() is None
    assert w.routectl._cable_out() is None


def test_sounds_follow_the_mic_effect_once_it_works(window, monkeypatch):  # noqa: F811
    """The effect started working after the app opened what others hear on the cable
    (Windows loaded it late): the next check switches to it, no restart needed. And
    back to the cable if Windows takes it off."""
    w = window
    _routes(w, monkeypatch, "missing")
    opened = []
    monkeypatch.setattr(w.engine, "set_main_device",
                        lambda name: (opened.append(name), w.engine.names.update(main=name)))
    monkeypatch.setattr(w.devctl, "_device_job", lambda plan, then=None: then(plan()()))
    monkeypatch.setattr(w.micctl, "_cable_ends", lambda *_a: None)
    w.engine.names["main"] = CABLE_IN
    w.micctl._follow_mic_effect()
    assert opened == []   # nothing changed: nothing reopened
    monkeypatch.setattr(dm, "status", lambda name=None: "ready")
    w.micctl._follow_mic_effect()
    assert opened == [dm.DEVICE]
    w.micctl._follow_mic_effect()
    assert opened == [dm.DEVICE]   # only once
    monkeypatch.setattr(dm, "status", lambda name=None: "wiped")
    w.micctl._follow_mic_effect()
    assert opened == [dm.DEVICE, CABLE_IN]
    w._attaching = True   # being set up: set_route applies it when it's on
    monkeypatch.setattr(dm, "status", lambda name=None: "ready")
    w.micctl._follow_mic_effect()
    assert opened == [dm.DEVICE, CABLE_IN]
    w._attaching = False


@pytest.mark.parametrize("state", ["ready", "missing", "wiped"])
def test_on_the_mic_the_setup_tab_never_talks_about_the_cable(window, monkeypatch, state):  # noqa: F811
    """Straight into the mic is the way: working or not set up yet, the Setup tab
    doesn't say the cable is in use, or tell anyone to pick one. The cable comes up
    only as the "Use the virtual cable instead" fallback button."""
    w = window
    _routes(w, monkeypatch, state)
    monkeypatch.setattr(w.micctl, "_direct_not_running", lambda: False)

    class S:
        def stop(self):
            pass
        close = stop
    w.engine.main_stream, w.engine.tap = S(), S()   # the cable still fed alongside
    try:
        w.routectl._show_route()
        w.statusctl._update_status()
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
    w.micctl._direct_dead_since = time.monotonic() - w.DIRECT_GRACE_S - 1
    assert w.micctl._direct_not_running() is dead


def test_an_older_mic_part_asks_for_the_update(window, monkeypatch):  # noqa: F811
    """Sounds in the mic with an older mic part: it still counts as connected, but the
    tab says the part needs updating (an old part may not reach every app), with one
    Update now button, never "nothing to set" or "optional"."""
    w = window
    _routes(w, monkeypatch, "outdated", cables=())
    monkeypatch.setattr(w.micctl, "_direct_not_running", lambda: False)

    class S:
        def stop(self):
            pass
        close = stop
    w.engine.main_stream = S()
    try:
        w.routectl._show_route()
        w.statusctl._update_status()
        assert w.statusctl.setup_state == "ok"
        assert w.step_lbl.isHidden()
        assert not w.mic_update_note.isHidden()
        assert "Update your mic part" in w.mic_update_text.text()
        assert "Optional" not in w.mic_update_text.text()
        assert w.btn_install.isHidden() and w.btn_micupdate.objectName() == "primary"
        _routes(w, monkeypatch, "ready", cables=())
        w.statusctl._update_flow()
        assert w.mic_update_note.isHidden()
        # working: one quiet line, no step and no button
        assert "Your sounds go into your mic" in w.mic_line.text()
        assert w.step_lbl.isHidden() and w.btn_install.isHidden()
    finally:
        w.engine.main_stream = None


@pytest.mark.parametrize("state", ["ready", "outdated"])
def test_on_the_mic_the_cable_gets_the_same(window, monkeypatch, state):  # noqa: F811
    w = window
    _routes(w, monkeypatch, state)
    opened = []
    monkeypatch.setattr(type(w.engine), "set_tap_device",
                        lambda self, name: (opened.append(name), setattr(self, "tap_name", name)))
    assert w.routectl._main_name() == dm.DEVICE   # (an older copy of the effect still works)
    w.routectl._apply_send_outputs()
    assert opened == [CABLE_IN]
    _routes(w, monkeypatch, state, cables=())
    w.routectl._apply_send_outputs()
    assert opened[-1] is None


@pytest.mark.parametrize("cables", [(CABLE_IN,), ()])
def test_saying_no_to_windows_keeps_the_mic_on_offer(window, monkeypatch, cables):  # noqa: F811
    """The admin prompt turned down: the route stays on the mic (one click still on
    offer, the card saying why), and the cable, if there is one, carries the sounds
    meanwhile. No error box: a No isn't an error."""
    w = window
    _routes(w, monkeypatch, "missing", cables)
    w.micctl._mic_attached("My mic", "Windows' admin prompt was turned down (or didn't finish).")
    assert w.cfg.route == "mic" and w.routectl._main_name() == (cables[0] if cables else None)
    assert not [t for t in toast.shown(w) if t.kind == "error"]
    assert "You clicked <b>No</b>" in w.mic_reason.text()
    assert "cable" not in w.mic_reason.text().lower()   # the mic is the way
    assert w.btn_install.text() == "Put my sounds straight into my mic"
    assert "mic" in w.pill.accessibleName().lower()


def test_an_unfinished_prompt_isnt_called_a_no(window, monkeypatch):  # noqa: F811
    """The admin step didn't finish (the prompt left open for minutes, or a PC that
    won't start it): nobody clicked No, so the card mustn't say so. It's an error box,
    and the one click stays on offer."""
    w = window
    _routes(w, monkeypatch, "missing")
    told = []
    monkeypatch.setattr(w, "tell", lambda *a, **k: told.append(a))
    w.micctl._mic_attached("My mic", dm.unfinished())
    assert not w.micctl._declined and "You clicked" not in w.mic_reason.text()
    assert told and "didn't finish" in told[0][1]
    assert w.btn_install.text() == "Put my sounds straight into my mic"


@pytest.mark.parametrize("auto,code,counted", [
    (False, dm.NO_ANSWER, "mic-effect-failed-unanswered"),
    (False, 6, "mic-effect-failed-code-6"),
    (True, None, "mic-effect-fix-failed-no-helper"),
    (True, dm.MIC_SILENT, "mic-effect-fix-failed-silent"),
    (False, None, None)])   # a No: counted as said-no only
def test_why_a_set_up_failed_is_counted_as_its_word(window, monkeypatch, auto, code,  # noqa: F811
                                                    counted):
    """The worker's install() result carries the word; the window counts it for a click
    and for the fix-by-itself (the signal in between hands over a plain str)."""
    from soundboard import usage
    w = window
    _routes(w, monkeypatch, "missing")
    monkeypatch.setattr(usage, "enabled", lambda: True)
    monkeypatch.setattr(usage, "_used", set())
    monkeypatch.setattr(w, "tell", lambda *a, **k: None)
    monkeypatch.setattr(dm, "endpoint_for", lambda name: GUID)
    monkeypatch.setattr(dm, "bundled_dll", lambda: Path(dm.__file__))   # (any file)
    monkeypatch.setattr(dm, "_elevated", lambda *a, **k: code)
    w.micctl._autofixing = auto
    # the worker and its answer, here
    w.micctl._mic_attached(*w.micctl._attach_mic_work("My mic", auto=auto))
    words = {k for k in usage._used if k.startswith("mic-effect-") and "failed-" in k}
    assert words == ({counted} if counted else set())
    assert not w.micctl._mic_fail_kind   # used once


def _fake_shell(monkeypatch, started: bool, error: int = 0, wait: int = 0, code: int = 0):
    """run_elevated's Windows calls: ShellExecuteExW `started` (else failing with
    `error`), WaitForSingleObject giving `wait`, the exit code `code`."""
    class Fn:
        argtypes = restype = None

        def __init__(self, f):
            self.f = f

        def __call__(self, *a):
            return self.f(*a)

    def shell(info):
        if started:
            info._obj.hProcess = 1234   # (byref: the struct is ._obj)
        return int(started)

    def exit_code(h, out):
        out._obj.value = code
        return 1

    class Lib:
        ShellExecuteExW = Fn(shell)
        WaitForSingleObject = Fn(lambda h, ms: wait)
        GetExitCodeProcess = Fn(exit_code)
        CloseHandle = Fn(lambda h: 1)
    monkeypatch.setattr(dm.ctypes, "WinDLL", lambda name, use_last_error=False: Lib())
    monkeypatch.setattr(dm.ctypes, "get_last_error", lambda: error)


def test_run_elevated_tells_a_no_from_no_answer(monkeypatch):
    _fake_shell(monkeypatch, started=False, error=1223)   # ERROR_CANCELLED: a No
    assert dm.run_elevated("x.exe", "") is None
    _fake_shell(monkeypatch, started=False, error=5)      # admin rights denied outright
    assert dm.run_elevated("x.exe", "") == dm.NOT_STARTED
    _fake_shell(monkeypatch, started=True, wait=0x102)    # WAIT_TIMEOUT, no log at all
    assert dm.run_elevated("x.exe", "", wait_s=0.01) == dm.NO_ANSWER
    _fake_shell(monkeypatch, started=True, wait=0, code=7)
    assert dm.run_elevated("x.exe", "", wait_s=0.01) == 7


def test_run_elevated_tells_a_stuck_step_from_an_unanswered_prompt(monkeypatch, tmp_path):
    log_file = tmp_path / "directmic-admin.log"
    _fake_shell(monkeypatch, started=True, wait=0x102)
    assert dm.run_elevated("x.exe", "", wait_s=0.01, progress=log_file) == dm.NO_ANSWER
    marks = iter([None])   # nothing before it ran; its log written once it started
    monkeypatch.setattr(dm, "_file_mark", lambda p: next(marks, (5, 1)))
    assert dm.run_elevated("x.exe", "", wait_s=0.01, progress=log_file) == dm.UNFINISHED


@pytest.mark.parametrize("code", dm.UNFINISHED_CODES)
def test_install_says_what_happened_to_the_prompt(monkeypatch, code):
    monkeypatch.setattr(dm, "bundled_dll", lambda: Path(dm.__file__))   # (any file)
    monkeypatch.setattr(dm, "_elevated", lambda *a, **k: None)
    assert dm.install_on(GUID) == dm.declined()
    monkeypatch.setattr(dm, "_elevated", lambda *a, **k: code)
    assert dm.install_on(GUID) == dm.unfinished()
    assert dm.uninstall() == dm.unfinished() and dm.cleanup(GUID) == dm.unfinished()
    from soundboard import cableremove
    monkeypatch.setattr(cableremove, "setup_exe", lambda: Path("x.exe"))
    monkeypatch.setattr(dm, "run_elevated", lambda *a, **k: code)
    assert cableremove.remove() == dm.unfinished()


@pytest.mark.parametrize("code,ask,kind", [
    (dm.NO_ANSWER, True, "unanswered"), (dm.NOT_STARTED, True, "no-start"),
    (dm.UNFINISHED, True, "stuck"), (dm.MIC_SILENT, True, "silent"),
    (None, False, "no-helper"), (3, True, "code-3"), (6, True, "code-6"),
    (99, True, "code-other")])
def test_install_says_why_as_a_fixed_word(monkeypatch, code, ask, kind):
    monkeypatch.setattr(dm, "bundled_dll", lambda: Path(dm.__file__))   # (any file)
    monkeypatch.setattr(dm, "_elevated", lambda *a, **k: code)
    err = dm.install_on(GUID, ask_windows=ask)
    assert dm.fail_kind(err) == kind and kind in dm.FAIL_KINDS
    assert kind not in err   # the word is counted, never shown


def test_install_failures_before_any_step_have_their_word(monkeypatch):
    assert dm.fail_kind(dm.install_on(None)) == "no-mic"
    monkeypatch.setattr(dm, "bundled_dll", lambda: Path("nowhere/x.dll"))
    assert dm.fail_kind(dm.install_on(GUID)) == "no-effect"
    monkeypatch.setattr(dm, "bundled_dll", lambda: Path(dm.__file__))
    monkeypatch.setattr(dm, "_elevated", lambda *a, **k: None)
    assert dm.install_on(GUID).kind == "said-no"   # counted as said-no, not a failure
    assert dm.fail_kind("any other text") == "code-other"


def test_a_silent_mic_is_never_called_done(monkeypatch):
    """The admin step put the effect on, but the mic still sends only silence after
    every restart: install / uninstall say what to do, so Bun never cheers over it."""
    monkeypatch.setattr(dm, "bundled_dll", lambda: Path(dm.__file__))   # (any file)
    monkeypatch.setattr(dm, "_elevated", lambda *a, **k: dm.MIC_SILENT)
    assert dm.install_on(GUID) == dm.mic_silent()
    assert dm.uninstall() == dm.mic_silent()
    assert "switched off" in dm.mic_silent() and "Restart your PC" in dm.mic_silent()


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
    for state in ("missing", "wiped", "other"):
        _routes(w, monkeypatch, state)
        dm.forget_status()
        w.statusctl._update_flow()
        assert "virtual cable" not in w.pill.accessibleName(), (state, w.pill.accessibleName())
        assert "mic" in w.pill.accessibleName()
        assert "straight into my mic" in w.btn_install.text() or "Repair" in w.btn_install.text()
        assert not w.btn_install.isHidden() and w.btn_install.objectName() == "primary"
    w.cfg.route = "cable"   # on the cable route, and no cable: the fix offers the mic first
    monkeypatch.setattr(w.statusctl, "virtual_mic", None)
    w.statusctl._update_flow()
    assert "virtual cable" not in w.pill.accessibleName()
    assert w.btn_attach.objectName() == "primary" and w.btn_install.objectName() != "primary"


class _NoThread:
    """threading.Thread stand-in: counts starts; runs the target there and then if
    `run`, else never (the admin prompt still waiting)."""
    started = 0
    run = False

    def __init__(self, target=None, args=(), kwargs=None, **_kw):
        self.target, self.args, self.kwargs = target, args, kwargs or {}

    @classmethod
    def setups(cls) -> list:
        """The mic set-ups started (attach_mic's thread), by their args."""
        return cls.__dict__.get("_setups", [])

    def start(self):
        cls = type(self)
        cls.started += 1
        fn = self.args[0] if self.args else None   # (worker.call's)
        if getattr(fn, "__name__", "") == "_attach_mic_work":
            cls._setups = [*cls.setups(), self.kwargs["args"]]
        if cls.run:
            self.target(*self.args, **self.kwargs)


def _no_threads(monkeypatch, run=False):
    from soundboard.ui import worker
    t = type("T", (_NoThread,), {"started": 0, "run": run})
    own_module(monkeypatch, worker, "threading", Thread=t)
    return t


def test_setting_up_the_mic_shows_it_and_takes_one_click(window, monkeypatch):  # noqa: F811
    """Clicking the one-click button: it says "Setting up…" and ignores more clicks
    until Windows has it running, instead of offering Repair again straight away."""
    from soundboard.ui import busy
    w = window
    _routes(w, monkeypatch, "missing")
    w.cfg.mic_device = "My mic"
    threads = _no_threads(monkeypatch)
    w.micctl.attach_mic()
    assert busy.is_busy(w.btn_install) and w.btn_install.text() == "Setting up…"
    assert w.btn_install.isHidden() and w.btn_usecable.isHidden()
    assert "setting up" in w.pill.accessibleName().lower()
    assert w.setup_show.on   # Bun's building it, in the button's place
    w.micctl.attach_mic()
    w.btn_install.click()   # spam-clicked: still the one admin prompt
    assert threads.started == 1
    # done: Windows loads it, and until the effect runs it's "starting…", still held
    monkeypatch.setattr(dm, "status", lambda name=None: "ready")
    monkeypatch.setattr(type(w.engine), "effect_alive", lambda self: False)
    w.micctl._mic_attached("My mic", "")
    assert "starting" in w.flow_out.text() and busy.is_busy(w.btn_install)
    assert "Repair" not in w.btn_install.text() and w.btn_usecable.isHidden()
    assert w.setup_show.on   # still at it while Windows loads it
    w._settle_until = 0.0   # the wait is over: the button is a button again
    w.statusctl._update_flow()
    assert not busy.is_busy(w.btn_install) and w._attach_release is None
    assert not w.setup_show.on   # (off screen here, so no ending to watch)


def test_a_mic_left_silent_by_the_set_up_never_cheers(window, monkeypatch):  # noqa: F811
    """The effect went on, but the mic still sends only silence after every audio
    restart: Bun's show ends badly, no "Done" toast, and a box says what to do."""
    from soundboard.ui import mainwindow as mw
    w = window
    _routes(w, monkeypatch, "missing")
    w.cfg.mic_device = "My mic"
    _no_threads(monkeypatch)
    monkeypatch.setattr(type(w.setup_show), "isVisible", lambda self: True)   # watched
    monkeypatch.setattr(mw.QMessageBox, "warning", lambda *a, **k: None)
    told, said = [], []
    monkeypatch.setattr(w, "tell", lambda *a, **k: told.append(a))
    monkeypatch.setattr(w, "toast", lambda text, kind="", *a, **k: said.append((text, kind)))
    w.micctl.attach_mic()
    assert w.setup_show.on
    monkeypatch.setattr(dm, "status", lambda name=None: "ready")   # (it is on the mic)
    w.micctl._mic_attached("My mic", dm.mic_silent())
    w.statusctl._update_flow()
    assert w.setup_show._result is False
    assert told and told[0][0] == "Is your headset on?" and "Restart your PC" in told[0][1]
    assert told[0][2] == "warn"   # most likely switched off: not an error
    assert not [k for _t, k in said if k == "ok"]


def test_a_failed_mic_update_never_cheers(window, monkeypatch):  # noqa: F811
    """The optional update fails (No to Windows' prompt) while the older mic part still
    works: the status reads fine, but it mustn't be cheered. Bun's show is only for the
    first set-up (the update says it in the card), so it never starts here."""
    from soundboard.ui import mainwindow as mw
    w = window
    _routes(w, monkeypatch, "outdated")
    monkeypatch.setattr(w.engine, "main_stream", object())   # the old part's running
    monkeypatch.setattr(w.micctl, "_direct_not_running", lambda: False)
    monkeypatch.setattr(type(w.engine), "effect_alive", lambda self: True)
    w.cfg.mic_device = "My mic"
    _no_threads(monkeypatch)
    monkeypatch.setattr(type(w.setup_show), "isVisible", lambda self: True)   # watched
    monkeypatch.setattr(mw.QMessageBox, "warning", lambda *a, **k: None)
    said = []
    monkeypatch.setattr(w, "toast", lambda text, kind="", *a, **k: said.append((text, kind)))
    w.micctl.attach_mic()
    assert not w.setup_show.on
    w.micctl._mic_attached("My mic", "Windows said no")
    w.statusctl._update_flow()
    assert not w.setup_show.on and not [k for _t, k in said if k == "ok"]


def test_setting_up_the_mic_shows_no_device_error_for_the_audio_restart(window, monkeypatch):  # noqa: F811
    """Setting it up restarts Windows' audio, so the headphones drop for a moment and
    come back by themselves: no "Audio device problem" meanwhile. Still failing once
    the wait is over, it shows, in plain words."""
    w = window
    _routes(w, monkeypatch, "missing")
    w.cfg.mic_device = "My mic"
    _no_threads(monkeypatch)
    w.micctl.attach_mic()
    w.engine.errors["mon"] = "Device unavailable"
    w.statusctl._update_status()
    assert "problem" not in said(w)
    monkeypatch.setattr(dm, "status", lambda name=None: "ready")
    w.micctl._mic_attached("My mic", "")
    assert "problem" not in said(w)
    w._settle_until = 0.0
    w.statusctl._update_status()
    assert "headphones: Device unavailable" in said(w)
    assert "mon:" not in said(w)


def test_turning_windows_down_lets_go_of_the_button(window, monkeypatch):  # noqa: F811
    from PySide6.QtWidgets import QMessageBox
    from soundboard.ui import busy
    w = window
    _routes(w, monkeypatch, "missing")
    w.cfg.mic_device = "My mic"
    _no_threads(monkeypatch)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: None)
    w.micctl.attach_mic()
    w.micctl._mic_attached("My mic", "Windows' admin prompt was turned down (or didn't finish).")
    assert not busy.is_busy(w.btn_install) and w._attach_release is None


def _working_on_the_mic(w, monkeypatch, cables=(CABLE_IN,), vbcable=True):
    from pathlib import Path
    from soundboard import cableremove
    _routes(w, monkeypatch, "ready", cables)
    monkeypatch.setattr(w.engine, "main_stream", object())
    monkeypatch.setattr(w.micctl, "_direct_not_running", lambda: False)
    monkeypatch.setattr(cableremove, "setup_exe",
                        lambda: Path("VBCABLE_Setup_x64.exe") if vbcable else None)
    w._vb_setup = None            # looked up again (on a thread)


def _flow_settled(w):
    """_update_flow, then again once the thread looking for VB-Cable's setup is back."""
    from PySide6.QtWidgets import QApplication

    from conftest import process_events
    w.statusctl._update_flow()
    assert process_events(QApplication.instance(), lambda: not w._vb_setup_asking, 3)
    w.statusctl._update_flow()


def test_a_working_mic_offers_to_remove_the_cable(window, monkeypatch):  # noqa: F811
    """Straight into the mic works: the cable is only the fallback, so its removal is
    offered beside the card's other ways (and no "also on the virtual cable" on the
    mic's status)."""
    w = window
    _working_on_the_mic(w, monkeypatch)
    _flow_settled(w)
    assert "virtual cable" not in w.mic_line.text()
    assert not w.btn_rmcable.isHidden() and w.btn_rmcable.toolTip()
    assert "remove it" in w.alt_cable_words.text()   # why there's a Use and a Remove
    for cables, vbcable in (((), True), ((CABLE_IN,), False)):   # none, or not VB-Cable's
        _working_on_the_mic(w, monkeypatch, cables, vbcable)
        _flow_settled(w)
        assert w.btn_rmcable.isHidden()


def test_redraws_never_look_for_the_cable_setup_on_the_ui_thread(window, monkeypatch):  # noqa: F811
    """_update_flow runs on every status redraw (and each time you start / stop
    talking): it checked Program Files for VB-Cable's setup every time, which stalls
    on a slow disk. It's looked up once, on a thread, and again after a re-scan."""
    from PySide6.QtWidgets import QApplication

    from conftest import process_events
    from soundboard import cableremove
    w = window
    _working_on_the_mic(w, monkeypatch)
    gate, asked = threading.Event(), []
    monkeypatch.setattr(cableremove, "setup_exe",
                        lambda: (asked.append(1), gate.wait(3), Path("VBCABLE_Setup_x64.exe"))[2])
    t0 = time.monotonic()
    for _ in range(5):
        w.statusctl._update_flow()
    assert time.monotonic() - t0 < 0.5
    assert w.btn_rmcable.isHidden()          # not known yet: not offered
    gate.set()
    app = QApplication.instance()
    assert process_events(app, lambda: not w.btn_rmcable.isHidden(), 3)   # shown when known
    for _ in range(5):
        w.statusctl._update_flow()
    assert len(asked) == 1                   # asked once, not on every redraw
    monkeypatch.setattr(w.engine, "shutdown", lambda: None)
    monkeypatch.setattr(w.devctl, "_init_devices", lambda: None)
    monkeypatch.setattr(w.routectl, "_prepare_all", lambda: None)
    w.devctl.refresh_devices()                      # devices re-scanned: looked up again
    w.statusctl._update_flow()
    assert process_events(app, lambda: len(asked) == 2 and not w._vb_setup_asking, 3)


def test_removing_the_cable(window, monkeypatch):  # noqa: F811
    from soundboard import cableremove
    from soundboard.ui import busy
    w = window
    _working_on_the_mic(w, monkeypatch)
    said = []
    monkeypatch.setattr(w, "toast", lambda text, kind="": said.append((text, kind)))
    _no_threads(monkeypatch, run=True)
    monkeypatch.setattr(cableremove, "remove", lambda: "Windows' admin prompt was turned down")
    w.micctl.remove_cable()
    assert not w._cable_gone and not busy.is_busy(w.btn_rmcable)
    assert said[-1][1] == "warn"
    monkeypatch.setattr(cableremove, "remove", lambda: None)
    w.micctl.remove_cable()
    assert w._cable_gone and w.routectl._tap_name() is None and not busy.is_busy(w.btn_rmcable)
    assert "Restart" in said[-1][0]
    w.statusctl._update_flow()
    assert w.btn_rmcable.isHidden() and w.rmcable_note.isHidden()


def test_a_worker_that_raises_still_clears_the_busy_state(window, monkeypatch):  # noqa: F811
    """VB-Audio's uninstaller, the cable's set-up lookup or the mic set-up raising on
    their thread: the answer still comes back as a failure, so the button and the
    "already asking" flags go back instead of staying busy until a restart."""
    from soundboard import cableremove
    from soundboard.ui import busy
    from soundboard.ui import mainwindow as mw
    w = window
    _working_on_the_mic(w, monkeypatch)
    said = []
    monkeypatch.setattr(w, "toast", lambda text, kind="", *a, **k: said.append((text, kind)))
    monkeypatch.setattr(mw.QMessageBox, "warning", lambda *a, **k: None)
    _no_threads(monkeypatch, run=True)

    def boom(*_a, **_k):
        raise OSError("the uninstaller vanished")
    monkeypatch.setattr(cableremove, "remove", boom)
    w.micctl.remove_cable()
    assert not busy.is_busy(w.btn_rmcable) and not w._cable_gone
    assert said[-1][1] == "warn"

    monkeypatch.setattr(cableremove, "setup_exe", boom)
    w._vb_setup_asking, w._vb_setup = False, None
    w.micctl._ask_cable_setup()
    assert not w._vb_setup_asking and w._vb_setup is False

    monkeypatch.setattr(dm, "install", boom)
    w.cfg.mic_device = "My mic"
    w._attaching = False
    w.micctl.attach_mic()
    assert not w._attaching and w._attach_release is None
    assert not busy.is_busy(w.btn_install)


def test_a_removed_cable_is_never_sent_to(window, monkeypatch):  # noqa: F811
    """Removed: Windows lists the cable until a restart, but it won't open. "Use the
    virtual cable instead" switched to it anyway: sounds went nowhere and the mic had
    to be set up again."""
    from soundboard import cableremove
    w = window
    _working_on_the_mic(w, monkeypatch)
    said = []
    monkeypatch.setattr(w, "toast", lambda text, kind="": said.append((text, kind)))
    _no_threads(monkeypatch, run=True)
    monkeypatch.setattr(cableremove, "remove", lambda: None)
    w.micctl.remove_cable()
    w.statusctl._update_flow()
    assert w.btn_usecable.isHidden()
    w.micctl.use_cable_instead()   # (still there for a moment, or clicked by keyboard)
    assert w.cfg.route == "mic" and "Restart" in said[-1][0] and said[-1][1] == "warn"


def _toasts(w, monkeypatch):
    said = []
    monkeypatch.setattr(w, "toast", lambda text, kind="": said.append(text))
    return said


def test_done_is_said_when_it_works_not_while_it_starts(window, monkeypatch):  # noqa: F811
    """Set up, then Windows takes a few seconds to load it ("starting…", Bun still
    building). "Done" came at once, beside the "starting…" card and the hammering:
    it comes when the card turns green, once."""
    w = window
    _routes(w, monkeypatch, "missing")
    w.cfg.mic_device = "My mic"
    _no_threads(monkeypatch)
    said = _toasts(w, monkeypatch)
    w.micctl.attach_mic()
    monkeypatch.setattr(dm, "status", lambda name=None: "ready")
    monkeypatch.setattr(type(w.engine), "effect_alive", lambda self: False)
    w.micctl._mic_attached("My mic", "")
    assert "starting" in w.flow_out.text() and w.setup_show.on
    assert not [t for t in said if t.startswith("Done")]
    monkeypatch.setattr(w.engine, "main_stream", object())   # Windows has it running
    monkeypatch.setattr(type(w.engine), "effect_alive", lambda self: True)
    monkeypatch.setattr(w.micctl, "_direct_not_running", lambda: False)
    w.statusctl._update_flow()
    w.statusctl._update_flow()
    assert "starting" not in w.flow_out.text()
    assert [t for t in said if t.startswith("Done")] == [
        "Done: Discord and games hear your sounds through your mic now."]


def test_no_done_when_windows_never_loads_it(window, monkeypatch):  # noqa: F811
    w = window
    _routes(w, monkeypatch, "missing")
    w.cfg.mic_device = "My mic"
    _no_threads(monkeypatch)
    said = _toasts(w, monkeypatch)
    w.micctl.attach_mic()
    monkeypatch.setattr(dm, "status", lambda name=None: "ready")
    monkeypatch.setattr(type(w.engine), "effect_alive", lambda self: False)
    w.micctl._mic_attached("My mic", "")
    w._settle_until = 0.0   # the wait ran out and it still isn't running
    w.statusctl._update_flow()
    assert not w.setup_show.on or w.setup_show._result is False
    assert not [t for t in said if t.startswith("Done")] and w._done_toast is None
    monkeypatch.setattr(w.engine, "main_stream", object())   # later on it works:
    monkeypatch.setattr(type(w.engine), "effect_alive", lambda self: True)
    w.statusctl._update_flow()
    assert not [t for t in said if t.startswith("Done")]   # (no stale "Done" then)


def test_bun_stays_on_while_it_starts(window, monkeypatch):  # noqa: F811
    """Bun's show ends by itself when nobody watches (another tab): coming back while
    it's still starting showed a clickable Repair beside "starting…"."""
    from soundboard.ui import busy
    w = window
    _routes(w, monkeypatch, "missing")
    w.cfg.mic_device = "My mic"
    _no_threads(monkeypatch)
    w.micctl.attach_mic()
    monkeypatch.setattr(dm, "status", lambda name=None: "ready")
    monkeypatch.setattr(type(w.engine), "effect_alive", lambda self: False)
    w.micctl._mic_attached("My mic", "")
    w.setup_show._stop()   # (what finish() does while it can't be seen)
    assert w.setup_show.on and "starting" in w.flow_out.text()
    assert w.btn_install.isHidden() and busy.is_busy(w.btn_install)
    w._settle_until = 0.0   # over: the button's back, and Bun's off for good
    w.statusctl._update_flow()
    assert not w.setup_show.on and not busy.is_busy(w.btn_install)


@pytest.mark.parametrize("state", ["ready", "missing", "wiped"])
def test_no_cable_or_speaker_hint_on_the_mic(window, monkeypatch, state):  # noqa: F811
    """Straight into the mic has no "send into" device: the Devices card never warns
    "that's a normal speaker, only you will hear the sounds" (it said so on 1.9.2)."""
    w = window
    _routes(w, monkeypatch, state)
    w.statusctl._update_status()
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


def test_cable_tap_closes_its_stream_when_start_fails(monkeypatch):
    # a busy cable used to leak one PortAudio stream on every retry
    from soundboard import engine as eng
    made = []

    class BusyStream:
        def __init__(self, **kw):
            self.closed = False
            made.append(self)

        def start(self):
            raise RuntimeError("device busy")

        def close(self):
            self.closed = True

    monkeypatch.setattr(eng, "find_device", lambda kind, name: 7)
    monkeypatch.setattr(eng.sd, "query_devices", lambda idx: {"default_samplerate": 48000})
    monkeypatch.setattr(eng.sd, "OutputStream", BusyStream)
    for _ in range(3):
        with pytest.raises(RuntimeError, match="busy"):
            eng.CableTap(CABLE_IN)
    assert len(made) == 3 and all(s.closed for s in made)


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
    w.devctl._init_devices()
    assert opened[-1] == CABLE_IN
    # the stream output never goes to that same cable (everyone would get it twice)
    assert w.routectl._obs_name("CABLE Input (VB-Audio Virtual Cable)") is None


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
        w.statusctl._update_flow()
        assert "virtual cable" not in w.pill.accessibleName()
    finally:
        w.soundctl._load_thread.join(15)
        w.close()


def test_picking_the_mic_asks_for_admin_only_when_it_doesnt_work(window, monkeypatch):  # noqa: F811
    """An older copy of the effect still works: picking the mic route never asks for
    admin for it (the update stays optional). Right after it was put on, Windows may
    still be loading it: the route is applied, not attached (and asked) again."""
    w = window
    w.cfg.mic_device = "My mic"
    tried = []
    monkeypatch.setattr(w.micctl, "attach_mic", lambda: tried.append(1))
    for state in ("outdated", "ready"):
        w.cfg.route = "cable"
        monkeypatch.setattr(dm, "status", lambda name=None, s=state: s)
        w.routectl.set_route("mic")
        assert w.cfg.route == "mic" and not tried
    for state in ("wiped", "missing", "other"):
        w.cfg.route = "cable"
        monkeypatch.setattr(dm, "status", lambda name=None, s=state: s)
        w.routectl.set_route("mic")
        assert w.cfg.route == "cable" and tried == [1]
        tried.clear()
        w.routectl.set_route("mic", attached=True)
        assert w.cfg.route == "mic" and not tried


def test_a_held_old_copy_goes_at_the_next_restart(monkeypatch, tmp_path):
    """The update takes the old effect off completely: a copy Windows still holds is
    marked for removal at the next restart, never left behind for good."""
    marked = []
    monkeypatch.setattr(dm, "_gone_at_restart", lambda p: marked.append(p))
    old = tmp_path / "obmic-old.dll"
    old.write_bytes(b"old")

    def unlink(self, missing_ok=False):
        raise PermissionError("in use") if self.exists() else FileNotFoundError(self)
    monkeypatch.setattr(Path, "unlink", unlink)
    dm._remove(old)
    assert marked == [old]
    dm._remove(tmp_path / "gone.dll")   # already gone: nothing to mark
    assert marked == [old]


# ---------------------------------------------------------------- the mic helper's card

def _helper(monkeypatch, ready):
    """michelper.ready()'s last answer, as the window's check on a thread left it."""
    from soundboard import michelper
    state = (michelper.HelperState() if ready is None
             else michelper.HelperState({True: ready, False: ready}, "test"))
    monkeypatch.setattr(michelper, "state", state)


def _said(w, monkeypatch):
    said = []
    monkeypatch.setattr(w, "toast", lambda text, kind="", *a, **k: said.append((text, kind)))
    return said


def _qt_run(ms=50):
    from PySide6.QtTest import QTest
    QTest.qWait(ms)


def test_windows_taking_it_off_is_fixed_by_itself(window, monkeypatch):  # noqa: F811
    """A Windows or driver update took the effect off the mic, and the mic helper is
    there: it goes back on with no click and no Windows prompt, a toast saying so, then
    "Done". No button, no Bun."""
    w = window
    _routes(w, monkeypatch, "wiped")
    w.cfg.mic_device = "My mic"
    _helper(monkeypatch, True)
    threads = _no_threads(monkeypatch)
    said = _said(w, monkeypatch)
    w.statusctl._update_flow()
    _qt_run()   # (it starts from the event loop, not mid-redraw)
    assert threads.setups() == [("My mic", False, True)]   # auto
    assert said[-1][0].startswith("Fixing your mic")
    assert "Fixing your mic" in w.mic_line.text()
    assert w.btn_install.isHidden() and not w.setup_show.on
    assert "going back on" in w.mic_reason.text() and "Yes" not in w.mic_reason.text()
    assert w.mic_pill.text() == "Fixing…"
    w.statusctl._update_flow()
    _qt_run()
    assert len(threads.setups()) == 1   # redraws while it runs: still the one fix
    _routes(w, monkeypatch, "ready")
    monkeypatch.setattr(w.engine, "main_stream", object())
    monkeypatch.setattr(w.micctl, "_direct_not_running", lambda: False)
    monkeypatch.setattr(type(w.engine), "effect_alive", lambda self: True)
    w.micctl._mic_attached("My mic", "")
    w.statusctl._update_flow()
    assert ("Done: your sounds are back in your mic.", "ok") in said
    assert "Your sounds go into your mic" in w.mic_line.text()


def test_a_mic_sending_only_silence_offers_the_repair(window, monkeypatch):  # noqa: F811
    """Set up and working, but the mic itself has sent nothing but exact zeros for a
    while (Discord and Windows' own mic test hear nothing): the card says so with its
    Repair (which restarts the audio and listens again), once a toast too. Gone at the
    first real sound: a headset's own mute does the same, and talking ends it."""
    w = window
    _routes(w, monkeypatch, "ready")
    w.cfg.mic_device = "My mic"
    monkeypatch.setattr(w.engine, "main_stream", object())
    monkeypatch.setattr(w.micctl, "_direct_not_running", lambda: False)
    monkeypatch.setattr(type(w.engine), "effect_alive", lambda self: True)
    silent = [w.MIC_SILENT_S - 1]
    monkeypatch.setattr(type(w.engine), "direct_mic_silent_s", lambda self: silent[0])
    said = _said(w, monkeypatch)
    w.statusctl._update_flow()
    assert w.mic_line.text() == "Your sounds go into your mic"
    silent[0] = w.MIC_SILENT_S + 1
    assert w.micctl._direct_health() != w._direct_shown   # the once-a-second check redraws it
    w.statusctl._update_flow()
    assert w.mic_line.text() == "Is your headset on?"
    assert "Repair" in w.btn_install.text() and not w.btn_install.isHidden()
    assert "headset is off" in w.mic_reason.text() and "muted" in w.mic_reason.text()
    assert [t for t, k in said if "No sound" in t]
    w.statusctl._update_flow()
    silent[0] = 0.0
    w.statusctl._update_flow()
    assert w.mic_line.text() == "Your sounds go into your mic"
    silent[0] = w.MIC_SILENT_S + 1
    w.statusctl._update_flow()
    assert len([t for t, k in said if "No sound" in t]) == 1   # the toast: once a run


@pytest.mark.parametrize("state", ["ready", "other", "missing"])
def test_an_unplugged_mic_asks_to_plug_it_in(window, monkeypatch, state):  # noqa: F811
    """The picked mic is unplugged (or its headset switched off, so Windows lists it as
    unplugged): the card asks whether it's plugged in, with no Repair or set-up button
    (neither can work without it), and goes back by itself once it's there."""
    w = window
    _routes(w, monkeypatch, state)
    w.cfg.mic_device = "My mic"
    monkeypatch.setattr(w.engine, "main_stream", object())
    monkeypatch.setattr(w.micctl, "_direct_not_running", lambda: False)
    monkeypatch.setattr(type(w.engine), "effect_alive", lambda self: True)
    out = [True]
    monkeypatch.setattr(dm, "unplugged", lambda name: out[0] and name == "My mic")
    w.statusctl._update_flow()
    assert w.mic_line.text() == "Is your headset plugged in?"
    assert w.mic_pill.text() == "Unplugged"
    assert "My mic" in w.mic_reason.text() and "Repair" not in w.mic_reason.text()
    assert w.btn_install.isHidden()
    out[0] = False
    assert w.micctl._direct_health() != w._direct_shown   # the once-a-second check redraws it
    w.statusctl._update_flow()
    assert w.mic_line.text() != "Is your headset plugged in?"


def test_unplugged_follows_the_last_status_check(monkeypatch):
    """status() notes whether the mic it was asked about is one Windows knows but has
    unplugged (or not present: a wireless headset switched off); a mic Windows has
    switched off by hand, or one it doesn't know at all, isn't "unplugged"."""
    mics = [{"guid": "{a}", "name": "Headset Mic (G733)", "active": False, "out": True},
            {"guid": "{b}", "name": "Line In (Realtek)", "active": False, "out": False},
            {"guid": "{c}", "name": "Webcam Mic (USB)", "active": True, "out": False}]
    monkeypatch.setattr(dm, "capture_endpoints", lambda: mics)
    monkeypatch.setattr(dm, "installed_on", lambda: ["{a}"])
    dm.forget_status()
    assert dm.status("Headset Mic (G733)") == "other" and dm.unplugged("Headset Mic (G733)")
    assert dm.status("Line In (Realtek)") == "other" and not dm.unplugged("Line In (Realtek)")
    assert dm.status("Nothing (gone)") == "other" and not dm.unplugged("Nothing (gone)")
    assert not dm.unplugged("Webcam Mic (USB)") and not dm.unplugged(None)
    mics[0] = {**mics[0], "active": True, "out": False}   # plugged back in
    dm.forget_status()
    dm.status("Headset Mic (G733)")
    assert not dm.unplugged("Headset Mic (G733)")
    monkeypatch.setattr(dm, "installed_on", lambda: [])   # nothing set up yet: still told
    mics[0] = {**mics[0], "active": False, "out": True}
    dm.forget_status()
    assert dm.status("Headset Mic (G733)") == "missing" and dm.unplugged("Headset Mic (G733)")
    dm.forget_status()


def test_the_fix_never_asks_windows_by_itself(monkeypatch):
    """The app's own fix goes through the helper only: no helper answer, no prompt."""
    monkeypatch.setattr(dm, "endpoint_for", lambda name: "{G}")
    monkeypatch.setattr(dm, "bundled_dll", lambda: Path(dm.__file__))   # (any file)
    monkeypatch.setattr(dm, "_via_helper", lambda args, wait_s: None)
    monkeypatch.setattr(dm, "run_elevated", lambda *a, **k: pytest.fail("asked Windows"))
    monkeypatch.setattr(dm, "_elevated", _REAL_ELEVATED)
    assert dm.install("My mic", ask_windows=False) == dm.no_helper()


@pytest.mark.parametrize("ready", [False, None])
def test_without_the_helper_the_card_asks_for_the_click(window, monkeypatch, ready):  # noqa: F811
    """No usable helper (missing, too old, or not checked yet): no fix by itself (it
    would need Windows' prompt nobody asked for). Not known yet: "Checking", then the
    answer decides. Missing: one Repair button and the reason, with the Yes."""
    w = window
    _routes(w, monkeypatch, "wiped")
    w.cfg.mic_device = "My mic"
    _helper(monkeypatch, ready)
    checks = []
    monkeypatch.setattr(w.micctl, "_check_helper", lambda: checks.append(1))
    threads = _no_threads(monkeypatch)
    w.statusctl._update_flow()
    _qt_run()
    assert not threads.setups()
    if ready is None:
        assert checks and "Checking your mic" in w.mic_line.text()
        assert w.btn_install.isHidden()
        return
    assert "Windows took Onion Board off your mic" in w.mic_line.text()
    assert "<b>Yes</b> when Windows asks" in w.mic_reason.text()
    assert w.btn_install.text() == "Repair (one click)" and not w.btn_install.isHidden()


def test_a_helper_removed_meanwhile_is_noticed_when_the_window_comes_back(window, monkeypatch):  # noqa: F811
    """Another account removed the helper while this window sat behind a game: coming
    back after RECHECK_S checks it again (on a thread), and the card follows the new
    answer without a restart: "click Yes" is back, and Windows taking the effect off is
    no longer fixed by itself (that would need a prompt nobody asked for)."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from conftest import process_events
    from soundboard import michelper
    from soundboard.ui import appstate
    w = window
    _routes(w, monkeypatch, "missing")
    w.cfg.mic_device = "My mic"
    _helper(monkeypatch, True)
    w.statusctl._update_flow()
    assert "Windows asks" not in w.mic_reason.text()
    gone = []   # (the same build as this app's, but its task is gone)
    monkeypatch.setattr(michelper, "_read_stamp", lambda folder: "8 aaaa")
    monkeypatch.setattr(michelper, "_build_files", lambda folder: {})
    monkeypatch.setattr(michelper, "installed", lambda: gone.append(1) or False)
    monkeypatch.setattr(appstate, "active", lambda: True)
    threads = _no_threads(monkeypatch, run=True)
    w.micctl._app_state(Qt.ApplicationState.ApplicationActive)
    assert not gone   # checked a moment ago: nothing to do
    monkeypatch.setattr(michelper.state, "when", time.monotonic() - michelper.RECHECK_S - 1)
    w.micctl._app_state(Qt.ApplicationState.ApplicationActive)
    assert process_events(QApplication.instance(), lambda: michelper.known() is False)
    _qt_run()
    assert gone and michelper.state.via == "window back"
    assert "Windows asks once: click <b>Yes</b>" in w.mic_reason.text()
    _routes(w, monkeypatch, "wiped")
    w.statusctl._update_flow()
    _qt_run()
    assert not threads.setups()   # no fix by itself
    assert w.btn_install.text() == "Repair (one click)" and not w.btn_install.isHidden()


def test_a_failing_helper_check_backs_off(window, monkeypatch):  # noqa: F811
    """michelper.ready() keeps raising: the card's redraws don't each run another
    check (a schtasks call each), one a minute at most, and back to normal once a
    check works."""
    from PySide6.QtWidgets import QApplication

    from conftest import process_events
    from soundboard import michelper
    from soundboard.ui import miccontrol
    w = window
    _routes(w, monkeypatch, "missing")
    w.cfg.mic_device = "My mic"
    _helper(monkeypatch, None)
    asked, fail = [], [True]

    def ready(same_dll=True, via="ready"):
        asked.append(via)
        if fail[0]:
            raise OSError("schtasks broke")
        michelper.state.set({True: True, False: True}, via)
        return True
    monkeypatch.setattr(michelper, "ready", ready)
    now = [1000.0]
    own_module(monkeypatch, miccontrol, "time", monotonic=lambda: now[0])
    _no_threads(monkeypatch, run=True)
    app = QApplication.instance()
    for _ in range(20):
        w.statusctl._update_flow()
        process_events(app, lambda: not w.micctl._helper_checking, timeout=1.0)
    assert len(asked) == 1
    now[0] += miccontrol.HELPER_RETRY_S + 1
    for _ in range(5):
        w.statusctl._update_flow()
        process_events(app, lambda: not w.micctl._helper_checking, timeout=1.0)
    assert len(asked) == 2
    fail[0] = False
    now[0] += miccontrol.HELPER_RETRY_S + 1
    w.statusctl._update_flow()
    process_events(app, lambda: michelper.known() is True)
    assert len(asked) == 3 and not w.micctl._helper_failed


def test_a_failed_fix_asks_once_and_never_loops(window, monkeypatch):  # noqa: F811
    """The fix by itself failed: a warning toast (no error box over the game), the card
    turns into Try again with the reason, and it isn't tried again by itself. Fixed but
    Windows took it off again straight away: the same, not a loop of audio restarts."""
    w = window
    _routes(w, monkeypatch, "wiped")
    w.cfg.mic_device = "My mic"
    _helper(monkeypatch, True)
    threads = _no_threads(monkeypatch)
    said = _said(w, monkeypatch)
    w.statusctl._update_flow()
    _qt_run()
    w.micctl._mic_attached("My mic", "Installing failed (code 6).")
    w.statusctl._update_flow()
    _qt_run()
    assert len(threads.setups()) == 1
    assert said[-1][1] == "warn" and "by itself" in said[-1][0]
    assert w.btn_install.text() == "Try again" and not w.btn_install.isHidden()
    assert "code 6" in w.mic_reason.text()
    # clicked: tried again (Windows may ask now)
    w.btn_install.click()
    assert threads.setups()[-1] == ("My mic", False, False)
    w.micctl._mic_attached("My mic", "")   # "worked", but it's still (or again) off
    w._settle_until = 0.0
    w.statusctl._update_flow()
    _qt_run()
    assert len(threads.setups()) == 2
    assert w.btn_install.text() == "Try again"   # no third go by itself


def test_the_yes_is_only_mentioned_when_windows_will_ask(window, monkeypatch):  # noqa: F811
    """'Click Yes when Windows asks' only when it will: with the helper set up, a set-up
    or update goes through it without the prompt."""
    w = window
    _routes(w, monkeypatch, "missing")
    w.cfg.mic_device = "My mic"
    _no_threads(monkeypatch)
    for ready in (False, True):
        _helper(monkeypatch, ready)
        w.statusctl._update_flow()
        assert ("Windows asks once" in w.mic_reason.text()) is not ready
        w._attaching = True
        w.statusctl._update_flow()
        assert ("Yes" in w.mic_reason.text()) is not ready
        w._attaching = False
    _routes(w, monkeypatch, "outdated")
    monkeypatch.setattr(w.engine, "main_stream", object())
    monkeypatch.setattr(w.micctl, "_direct_not_running", lambda: False)
    for ready in (False, True):
        _helper(monkeypatch, ready)
        w.statusctl._update_flow()
        assert ("Windows asks" in w.mic_update_text.text()) is not ready


def test_bun_builds_only_the_first_set_up(window, monkeypatch):  # noqa: F811
    """Bun's show explains the first set-up's wait; a repair someone clicks says it in
    the card instead."""
    w = window
    w.cfg.mic_device = "My mic"
    _no_threads(monkeypatch)
    _helper(monkeypatch, False)
    _routes(w, monkeypatch, "wiped")
    w.micctl.attach_mic()
    assert not w.setup_show.on and "Setting up" in w.mic_line.text()
    w.micctl._mic_attached("My mic", "Windows said no")
    _routes(w, monkeypatch, "missing")
    w.micctl.attach_mic()
    assert w.setup_show.on


def test_the_working_card_is_one_line(window, monkeypatch):  # noqa: F811
    """Working: the status box (the mic's name and its live level), the pill, and the
    other ways as plain buttons; no step and no main button."""
    w = window
    _working_on_the_mic(w, monkeypatch, cables=())
    monkeypatch.setattr(w.engine, "mic_stream", object())
    w.cfg.mic_device = "My mic"
    w.statusctl._update_flow()
    assert w.mic_line.text() == "Your sounds go into your mic"
    assert w.mic_sub.text() == "My mic" and not w.card_meter.isHidden()
    assert w.mic_pill.text() == "Connected" and w.mic_pill.property("tone") == "ok"
    for b in (w.btn_install, w.step_lbl, w.mic_flow, w.mic_update_note):
        assert b.isHidden()
    assert not w.btn_usecable.isHidden() and not w.mic_alt.isHidden()   # the tiles
    assert w.btn_guide.isHidden() and not w.helpcard.isHidden()   # (it has the guide)


def test_every_time_windows_takes_it_off_it_is_fixed_again(window, monkeypatch):  # noqa: F811
    """Fixed, worked for a while, then another Windows update took it off: fixed by
    itself again (only a fix that doesn't hold stops it)."""
    w = window
    _routes(w, monkeypatch, "wiped")
    w.cfg.mic_device = "My mic"
    _helper(monkeypatch, True)
    threads = _no_threads(monkeypatch)
    w.statusctl._update_flow()
    _qt_run()
    _routes(w, monkeypatch, "ready")
    monkeypatch.setattr(w.engine, "main_stream", object())
    monkeypatch.setattr(w.micctl, "_direct_not_running", lambda: False)
    w.micctl._mic_attached("My mic", "")
    w._settle_until = 0.0
    w.statusctl._update_flow()   # works
    _routes(w, monkeypatch, "wiped")
    w.statusctl._update_flow()
    _qt_run()
    assert len(threads.setups()) == 2 and "Fixing your mic" in w.mic_line.text()


@pytest.mark.windows
@pytest.mark.parametrize("state", ["starting", "stalled"])
def test_board_claim_is_exclusive_before_enable_and_after_stall(ring_file, state):
    first = dm.RingWriter(ring_file)
    second = dm.RingWriter(ring_file)
    try:
        first.claim()
        if state == "stalled":
            first.set_enabled(True)
            first._btick[0] = 0
        with pytest.raises(RuntimeError, match="Another Onion Board"):
            second.claim()
    finally:
        second.close(owner=False)
        first.close()


@pytest.mark.parametrize("seq", [0, 1, 0xFFFFFFFE, 0xFFFFFFFF])
@pytest.mark.parametrize("clear", [False, True])
def test_sync_recovers_an_interrupted_writer(ring_file, monkeypatch, seq, clear):
    w = dm.RingWriter(ring_file)
    try:
        w._set("sync_seq", seq)
        original = w._set
        observed = []

        def observe(name, value):
            if name in ("sync_wp", "sync_mic"):
                observed.append(int(w._get("sync_seq")))
            original(name, value)

        monkeypatch.setattr(w, "_set", observe)
        if clear:
            w.clear_sync()
        else:
            w.set_sync(100, 200)
        assert all(value & 1 for value in observed), observed
        assert int(w._get("sync_seq")) % 2 == 0
    finally:
        w.close()


@needs_fuzz
@pytest.mark.parametrize("case", ["factory", "slot", "add-stop", "add-stall"])
def test_effect_lifecycle_audit(tmp_path, case):
    r = subprocess.run([str(FUZZ_HOST), str(FUZZ_DLL), str(tmp_path), "--audit", case],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stdout + r.stderr
