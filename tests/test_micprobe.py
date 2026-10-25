"""The mic check after a set-up (soundboard/mic/micprobe.py): the quiet probe is found
in a recording of the mic by correlation, never in one without it, and the app shows
what it found (the card, a toast for a mic another app lost)."""
from __future__ import annotations

import numpy as np
import pytest

from soundboard.mic import directmic as dm
from soundboard.mic import micprobe as mp
from test_mainwindow import window  # noqa: F401  (fixture)

REAL = "{11111111-2222-3333-4444-555555555555}"
APP = "{22222222-3333-4444-5555-666666666666}"


def _room(seconds: float, db: float, seed: int = 1, rate: int = mp.SR) -> np.ndarray:
    return (np.random.default_rng(seed).standard_normal(int(rate * seconds))
            * 10 ** (db / 20)).astype(np.float32)


def _with_probe(x: np.ndarray, at: int) -> np.ndarray:
    y = x.copy()
    p = mp.probe()
    y[at:at + len(p)] += p
    return y


def test_the_probe_is_quiet_and_in_the_voice_band():
    p = mp.probe()
    assert len(p) == int(mp.SR * mp.PROBE_S)
    assert 20 * np.log10(np.sqrt(np.mean(p ** 2))) == pytest.approx(mp.PROBE_DB, abs=0.1)
    spec = np.abs(np.fft.rfft(p))
    hz = np.fft.rfftfreq(len(p), 1 / mp.SR)
    inside = spec[(hz >= mp.BAND[0]) & (hz <= mp.BAND[1])].sum()
    assert inside / spec.sum() > 0.95
    assert abs(p[0]) < 1e-4 and abs(p[-1]) < 1e-4   # faded: no click
    assert np.array_equal(p, mp.probe())             # the same each time: it's looked for


@pytest.mark.parametrize("room_db", [-60, -45, -35])
def test_the_probe_is_found_under_room_noise_and_never_without_it(room_db):
    for seed in range(5):
        room = _room(2.0, room_db, seed)
        assert mp.score(_with_probe(room, 12000 + seed * 3000)) >= mp.FOUND
        assert mp.score(room) < mp.FOUND / 1.5


def test_a_mic_at_another_rate_still_finds_it():
    rec = _with_probe(_room(2.0, -50), 20000)
    t = np.arange(int(len(rec) * 44100 / mp.SR)) * (mp.SR / 44100)
    at_44k = np.interp(t, np.arange(len(rec)), rec).astype(np.float32)
    assert mp.score(at_44k, 44100) >= mp.FOUND
    assert mp.score(np.zeros(100, np.float32)) == 0.0   # too short: nothing to find


def _fake_mics(monkeypatch, recordings):
    """micprobe's recorder faked: `recordings` = {guid: (samples, rate) | None}, handed
    out once play() was called (the probe goes in while they record)."""
    played = []

    def record(guid, seconds, started=None):
        if started is not None:
            started.set()
        for _ in range(200):   # (what the real one records happens around play())
            if played:
                break
            import time
            time.sleep(0.01)
        return recordings[guid]
    monkeypatch.setattr(mp, "_record", record)
    monkeypatch.setattr(mp, "LEAD_S", 0.0)
    return played


def test_check_finds_the_probe_in_the_mic(monkeypatch):
    played = _fake_mics(monkeypatch, {REAL: (_with_probe(_room(1.8, -55), 15000), mp.SR)})
    res = mp.check(lambda: played.append(1), REAL)
    assert played == [1] and res.real is True and res.dead == []
    assert res.scores[REAL] >= mp.FOUND


def test_check_says_when_the_probe_never_came_out(monkeypatch):
    played = _fake_mics(monkeypatch, {REAL: (_room(1.8, -55), mp.SR)})
    assert mp.check(lambda: played.append(1), REAL).real is False


def test_a_mic_that_cant_be_recorded_is_no_verdict(monkeypatch):
    """Muted, at 0% or not back yet: "can't tell", never "not working"."""
    played = _fake_mics(monkeypatch, {REAL: None})
    assert mp.check(lambda: played.append(1), REAL).real is None


def test_another_mic_gone_dead_is_named_one_with_sound_isnt(monkeypatch):
    """An app's own mic (a virtual one between the mic and a voice chat) had sound
    before the set-up: only exact zeros now = cut off. Sound without the probe isn't:
    its own noise removal may take it out."""
    other = "{33333333-4444-5555-6666-777777777777}"
    played = _fake_mics(monkeypatch, {
        REAL: (_with_probe(_room(1.8, -55), 15000), mp.SR),
        APP: (np.zeros(int(mp.SR * 1.8), np.float32), mp.SR),
        other: (_room(1.8, -60, 3), mp.SR)})
    res = mp.check(lambda: played.append(1), REAL, [APP, other, REAL])
    assert res.real is True and res.dead == [APP]


def test_a_failing_recording_is_no_verdict(monkeypatch):
    def broken(guid, seconds, started=None):
        raise OSError("no audio")
    monkeypatch.setattr(mp, "_record", broken)
    monkeypatch.setattr(mp, "LEAD_S", 0.0)
    res = mp.check(lambda: None, REAL, [APP])
    assert res.real is None and res.dead == []


def test_alive_lists_the_mics_with_sound(monkeypatch):
    answers = {REAL: False, APP: True, "{x}": None}   # sound / only zeros / can't tell
    monkeypatch.setattr(mp, "_is_silent", lambda g: answers[g])
    assert mp.alive(list(answers)) == {REAL}


# ---------------------------------------------------------------------------- the app

def _on_the_mic(w, monkeypatch):
    from soundboard.audio import engine as eng
    monkeypatch.setattr(dm, "status", lambda name=None: "ready")
    monkeypatch.setattr(eng, "virtual_outputs", lambda: [])
    monkeypatch.setattr(dm, "endpoint_for", lambda name: REAL)
    w.cfg.route = "mic"
    w.cfg.mic_device = "My mic"


def test_a_missing_probe_turns_the_card_to_repair(window, monkeypatch):  # noqa: F811
    w = window
    _on_the_mic(w, monkeypatch)
    w.micctl._probe_missing = True
    reason, button = w.micctl._show_mic_status("ready", "ok", False, "")
    assert "test sound" in reason and button == "Repair (one click)"
    assert w.mic_line.text() == "Your sounds aren't in your mic yet"
    w.micctl._probe_missing = False
    reason, button = w.micctl._show_mic_status("ready", "ok", False, "")
    assert button is None and w.mic_line.text() == "Your sounds go into your mic"


def test_the_probe_result_reaches_the_card_and_names_a_cut_off_mic(window, monkeypatch):  # noqa: F811
    from soundboard.core import usage
    from soundboard.ui.window import miccontrol
    w = window
    _on_the_mic(w, monkeypatch)
    monkeypatch.setattr(miccontrol, "PROBE_SHOWS", True)
    said, counted = [], []
    monkeypatch.setattr(w, "toast", lambda text, kind="", *a, **k: said.append((text, kind)))
    monkeypatch.setattr(usage, "used", counted.append)
    monkeypatch.setattr(dm, "capture_endpoints", lambda: [
        {"guid": APP, "name": "Some App - Microphone (Virtual Audio)", "active": True,
         "device": "Virtual Audio"}])
    w.micctl._probing = True
    w.micctl._mic_probed(mp.Result(real=False, dead=[APP]))
    assert w.micctl._probe_missing and not w.micctl._probing
    assert [k for t, k in said if "<b>Some App - Microphone</b>" in t] == ["warn"]
    assert counted == ["mic-probe-missing", "mic-probe-app-cut-off"]
    said.clear()
    w.micctl._mic_probed(mp.Result(real=True))
    assert said == []


@pytest.mark.parametrize("real, count", [(True, "mic-probe-heard"),
                                         (False, "mic-probe-missing"),
                                         (None, "mic-probe-unsure")])
def test_for_now_the_probe_is_only_counted(window, monkeypatch, real, count):  # noqa: F811
    """Count only (PROBE_SHOWS off): what it found goes into the usage count, and the
    card and the toasts stay as they were."""
    from soundboard.core import usage
    w = window
    _on_the_mic(w, monkeypatch)
    said, counted = [], []
    monkeypatch.setattr(w, "toast", lambda *a, **k: said.append(a))
    monkeypatch.setattr(usage, "used", counted.append)
    w.micctl._mic_probed(mp.Result(real=real, dead=[APP]))
    assert counted == [count, "mic-probe-app-cut-off"]
    assert said == [] and not w.micctl._probe_missing


def test_the_probe_runs_once_after_a_set_up_into_the_mic_only(window, monkeypatch):  # noqa: F811
    """After a set-up that works: once, played to others only (never your headphones),
    loud enough again when the sounds' volume to others is turned down."""
    from soundboard.ui.window import miccontrol
    w = window
    _on_the_mic(w, monkeypatch)
    plays, runs = [], []
    monkeypatch.setattr(w.engine, "play", lambda *a, **k: plays.append((a, k)))
    w.engine.main_stream = object()
    w.engine.sound_vol = 0.5

    def run(fn, signal=None, name="", **k):
        runs.append(name)
        fn()
    monkeypatch.setattr(miccontrol.worker, "run", run)
    monkeypatch.setattr(mp, "check", lambda play, real, others: play() or mp.Result(True))
    try:
        w.micctl.probe_mic()
        assert runs == []                  # no set-up just now: nothing to check
        w.micctl._probe_due = True
        w.micctl.probe_mic()
        w.micctl.probe_mic()               # once
        assert runs == ["mic-probe"]
        (args, kw), = plays
        assert args[0] == "__probe__" and kw["only"] == "main" and args[2] == 2.0
    finally:
        w.engine.main_stream = None


@pytest.mark.parametrize("why", ["muted", "voice only", "no sounds volume"])
def test_no_probe_when_nothing_goes_to_others(window, monkeypatch, why):  # noqa: F811
    from soundboard.ui.window import miccontrol
    w = window
    _on_the_mic(w, monkeypatch)
    runs = []
    monkeypatch.setattr(miccontrol.worker, "run", lambda *a, **k: runs.append(1))
    w.engine.main_stream = object()
    if why == "muted":
        monkeypatch.setattr(w.engine, "sending", False)
    elif why == "voice only":
        monkeypatch.setattr(w.engine, "mic_only", lambda: True)
    else:
        w.engine.sound_vol = 0.0
    try:
        w.micctl._probe_due = True
        w.micctl.probe_mic()
        assert runs == [] and not w.micctl._probe_due
    finally:
        w.engine.main_stream = None
        w.engine.sound_vol = 1.0


def test_a_new_set_up_clears_the_old_verdict(window, monkeypatch):  # noqa: F811
    from soundboard.ui.window import miccontrol
    w = window
    _on_the_mic(w, monkeypatch)
    monkeypatch.setattr(miccontrol.worker, "run", lambda *a, **k: None)
    w.micctl._probe_missing = True
    w.micctl.attach_mic()
    assert not w.micctl._probe_missing
    w._attaching = False


def test_the_probe_plays_through_the_real_mixer():
    """The probe is mono; the mix is stereo. Played as it was, the first block raised in
    the audio callback ("operands could not be broadcast together with shapes (480,2)
    (480,) (480,2)") and every fresh set-up showed it as an audio device problem."""
    from soundboard.audio.engine import Engine
    e = Engine()
    e.main_stream = object()
    e.dest, e.limiter_on, e.send_mono = None, False, False
    e.play("__probe__", mp.probe(), 2.0, mode="restart", src_rate=mp.SR, only="main")
    out = np.concatenate([e._sounds("main", 480) for _ in range(30)])
    assert out.shape == (30 * 480, 2) and np.abs(out).max() > 0
    assert np.array_equal(out[:, 0], out[:, 1])   # the same in both channels
