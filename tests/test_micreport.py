"""The mic set-up log: what it finds, who it never names, and when it's sent."""
from __future__ import annotations

import sys

import pytest

from soundboard.mic import micdiag
from soundboard.online import micreport


GUID = "{11111111-2222-3333-4444-555555555555}"


def test_scrub_takes_out_who_this_is():
    home = "C:" + r"\Users\Sam Jones"
    env = {"USERPROFILE": home, "USERNAME": "Sam Jones", "COMPUTERNAME": "SAMS-PC"}
    other = "D:" + r"\Users\other"
    text = (home + r"\AppData\x.dll and " + other + r"\y.dll by Sam Jones on SAMS-PC, "
            "sam@example.com, Microphone (Blue Yeti)")
    out = micreport.scrub(text, env)
    for gone in ("Sam Jones", "SAMS-PC", "sam@example.com", "other"):
        assert gone not in out
    assert "Microphone (Blue Yeti)" in out   # the mic's name stays: it's what the log is for


@pytest.mark.parametrize("sddl,want", [
    ("D:P(A;OICI;FA;;;SY)(A;;0x1201bb;;;LS)", True),
    ("D:P(A;OICI;FA;;;SY)(A;OICI;0x1200a9;;;BU)", False),      # read only
    ("D:(D;;FW;;;LS)(A;;FA;;;LS)", False),                     # a Deny wins
    ("D:(A;OICIIO;0x1301bf;;;LS)", False),                     # inherit-only says nothing here
])
def test_access_list_read_for_the_effects_account(sddl, want):
    assert micdiag._lets(sddl, micdiag._RIGHTS_WRITE) is want


def test_enhancements_off_only_when_set():
    assert micdiag.enhancements_off({micdiag.DISABLE_SYSFX: "1"})
    assert not micdiag.enhancements_off({micdiag.DISABLE_SYSFX: "0"})
    assert not micdiag.enhancements_off({})


def looks(monkeypatch, **over):
    """findings() with every look at Windows answered by `over`, else "all fine"."""
    fine = {"dll_lines": ([], []), "log_lines": ([], []), "ring_lines_causes": ([], []),
            "service_lines": ([], []), "event_lines": ([], []), "protection_lines": [],
            "device_lines": [], "mic_check_lines": ([], []), "_run_by_eapo": False}
    fx = over.pop("fx", lambda g: {micdiag.FX % 6: micdiag.CLSID})
    for name, value in {**fine, **over}.items():
        monkeypatch.setattr(micdiag, name, lambda *a, v=value: v)
    monkeypatch.setattr(micdiag, "fx_dump", fx)


@pytest.mark.parametrize("over,word", [
    ({"dll_lines": ([], ["effect-not-registered"])}, "effect-not-registered"),
    ({"dll_lines": (["effect file: not there"], ["effect-file-missing"])}, "effect-file-missing"),
    ({"log_lines": ([], ["log-file-denied"])}, "log-file-denied"),
    ({"event_lines": ([], ["blocked-by-code-integrity"])}, "blocked-by-code-integrity"),
    ({"mic_check_lines": ([], ["mic-held-exclusively"])}, "mic-held-exclusively"),
])
def test_each_cause_reaches_the_verdict(monkeypatch, over, word):
    looks(monkeypatch, **over)
    micdiag._stages.clear()
    lines = micdiag.findings([GUID])
    assert word in next(s for s in lines if s.startswith("verdict:"))


def test_enhancements_off_and_lost_settings_reach_the_verdict(monkeypatch):
    looks(monkeypatch, fx=lambda g: {micdiag.DISABLE_SYSFX: "1"})
    micdiag._stages.clear()
    verdict = next(s for s in micdiag.findings([GUID]) if s.startswith("verdict:"))
    assert "enhancements-off" in verdict and "settings-lost" in verdict


def test_settings_rewritten_across_the_restart(monkeypatch):
    looks(monkeypatch, fx=lambda g: {micdiag.FX % 6: micdiag.CLSID + "|other"})
    micdiag._stages.clear()
    micdiag._stages["after the write"] = {GUID: {micdiag.FX % 6: micdiag.CLSID}}
    verdict = next(s for s in micdiag.findings([GUID]) if s.startswith("verdict:"))
    assert "settings-rewritten" in verdict
    micdiag._stages.clear()


def test_a_look_that_breaks_is_a_line_and_the_rest_go_on(monkeypatch):
    def broken():
        raise OSError("no")
    looks(monkeypatch, event_lines=([], ["blocked-by-defender"]))
    monkeypatch.setattr(micdiag, "dll_lines", broken)
    lines = micdiag.findings([])
    assert any("broken failed" in s or "failed: OSError" in s for s in lines)
    assert "blocked-by-defender" in next(s for s in lines if s.startswith("verdict:"))


def test_the_step_writes_its_report_as_it_goes(monkeypatch, tmp_path):
    monkeypatch.setattr(micdiag, "report_path", lambda: tmp_path / "r.log")
    monkeypatch.setattr(micdiag, "findings", lambda g, code=None: ["=== why", "verdict: x"])
    monkeypatch.setattr(micdiag, "fx_dump", lambda g: {micdiag.FX % 7: "b"})
    micdiag.begin(["install", GUID])
    micdiag.stage("before the write", [GUID])
    for _i in range(3):
        micdiag.log.warning("a line the step logged")
    micdiag.end(8, [GUID])
    text = (tmp_path / "r.log").read_text(encoding="utf-8")
    for want in ("step: install", "--- before the write", " = b", "a line the step logged",
                 "verdict: x", "exit code: 8"):
        assert want in text
    assert text.count("a line the step logged") == 1 and "2 more times" in text
    assert not micdiag.active()
    micdiag.stage("after the step", [GUID])   # nothing begun: no writes, no error
    assert "after the step" not in (tmp_path / "r.log").read_text(encoding="utf-8")


def test_a_look_never_fails_the_step(monkeypatch, tmp_path):
    def boom():
        raise PermissionError("denied")
    monkeypatch.setattr(micdiag, "report_path", boom)
    micdiag.begin(["install", GUID])   # no exception
    assert not micdiag.active()


class Cfg:
    net_off: list = []


@pytest.fixture
def sends(monkeypatch):
    got = []
    monkeypatch.setattr(micreport, "_sends", 0)
    monkeypatch.setattr(micreport, "allowed", lambda cfg: True)
    monkeypatch.setattr(micreport, "build", lambda kind, mic, guid=None: f"{kind} {mic}")
    monkeypatch.setattr(micreport, "_post", lambda kind, body: got.append((kind, body)) or True)
    monkeypatch.setattr(micreport, "_spawn", lambda run: run())   # (here, at once)
    return got


def test_a_failure_sends_its_log_a_few_times_a_launch(sends):
    for _i in range(5):
        micreport.send(Cfg(), "code-8", "Mic")
    assert sends == [("code-8", "code-8 Mic")] * micreport.MAX_SENDS


def test_a_kind_is_only_a_fixed_word(sends):
    micreport.send(Cfg(), "name with spaces\n", "Mic")
    assert sends[0][0] == "other"


def test_nothing_goes_with_the_count_off(monkeypatch, sends):
    monkeypatch.setattr(micreport, "allowed", lambda cfg: False)
    assert micreport.send(Cfg(), "code-8", "Mic") is False
    assert not sends


def test_a_switch_turned_off_while_the_log_is_built_sends_nothing(monkeypatch, sends):
    """Building the log takes seconds. A test that turned the count on for a moment had
    its fakes undone by then, and the log went to the real server from the test run."""
    later = []
    monkeypatch.setattr(micreport, "_spawn", later.append)
    assert micreport.send(Cfg(), "code-8", "Mic")
    monkeypatch.setattr(micreport, "allowed", lambda cfg: False)
    (run,) = later
    run()
    assert not sends


def test_no_test_starts_a_real_send():
    from conftest import NO_SPAWN
    assert micreport._spawn is NO_SPAWN   # (the guard in conftest)


def test_it_goes_to_the_stores_server():
    from soundboard.online import store
    assert micreport.URL == store.BASE + "/v1/miclog"


def test_later_stages_show_only_what_changed():
    a, b = micdiag.FX % 6, "{0000-tuning},1"
    assert micdiag.fx_changes({a: "x", b: "1"}, {a: "x", b: "1"}) == ["no change"]
    said = micdiag.fx_changes({a: "x"}, {a: "y", b: "2"})
    assert len(said) == 2 and any("x -> y" in s for s in said)
    assert any("(none) -> 2" in s for s in said)
    assert "tuning" not in "\n".join(micdiag.fx_lines({a: "x", b: "1"}))


def test_source_runs_never_send(monkeypatch):
    monkeypatch.delenv("ONIONBOARD_NO_STATS", raising=False)
    assert not micreport.allowed(Cfg())   # (a test run isn't frozen)


def test_the_log_stays_under_the_servers_limit(monkeypatch, tmp_path):
    from soundboard.mic import directmic
    monkeypatch.setattr(directmic, "data_dir", lambda: tmp_path / "MicPlugin")
    (tmp_path / "MicPlugin").mkdir()
    report = tmp_path / "r.log"
    report.write_text("verdict: effect-file-missing\n" + "x" * 200_000, encoding="utf-8")
    monkeypatch.setattr(micdiag, "report_path", lambda: report)
    monkeypatch.setattr(micdiag, "snapshot", lambda g: ["=== now", "verdict: nothing-found"])
    body = micreport.build("code-8", "Microphone", GUID)
    assert len(body.encode()) <= micreport.MAX_BYTES
    assert body.startswith("Onion Board")


def test_a_windows_report_that_isnt_a_crash_isnt_called_one(monkeypatch):
    """Windows Error Reporting's RADAR_PRE_LEAK_64 report about audiodg (it uses a lot of
    memory) is event 1001 too: it made the verdict say the audio engine crashed, on PCs
    where it ran fine and only never loaded the effect. A real crash still counts."""
    leak = {"id": 1001, "time": "2026-11-07T14:57:05",
            "text": "1423403552265764565 | 5 | RADAR_PRE_LEAK_64 | Not available | 0 | "
                    "audiodg.exe | 10.0.26100.9711"}
    crash = {"id": 1001, "time": "2026-11-07T15:00:00",
             "text": "2213 | 4 | BEX64 | Not available | 0 | audiodg.exe | obmic-1.dll"}
    error = {"id": 1000, "time": "2026-11-07T15:00:00",
             "text": "audiodg.exe | 10.0.26100.1 | obmic-1.dll | c0000005"}

    def events(found):
        return lambda channel, query, count: (found if "EventID=1000" in query else [], "")
    monkeypatch.setattr(micdiag, "_events", events([leak]))
    lines, causes = micdiag.event_lines()
    assert "audio-engine-crashed" not in causes
    assert "audio engine crashes this week: 0" in lines
    for real in (crash, error):
        monkeypatch.setattr(micdiag, "_events", events([leak, real]))
        lines, causes = micdiag.event_lines()
        assert "audio-engine-crashed" in causes and "audio engine crashes this week: 1" in lines


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' byte-range locks")
def test_the_ring_line_reads_while_a_board_holds_its_lock(monkeypatch, tmp_path):
    """A running board locks 4 bytes of the ring's header (RingWriter.claim): the look
    read past them, buffered, and said "can't read it (PermissionError)" whenever a board
    ran, so the log never showed whether the effect was running."""
    import msvcrt
    import struct

    from soundboard.mic import micring
    ring = tmp_path / "ring2.bin"
    raw = bytearray(micring.new_ring_bytes())
    struct.pack_into("<Q", raw, 72, micring._tick())
    struct.pack_into("<I", raw, 80, 5)
    ring.write_bytes(bytes(raw))
    monkeypatch.setattr(micdiag, "ring_path", lambda: ring)
    with open(ring, "r+b") as board:   # as the board holds it
        board.seek(84)
        msvcrt.locking(board.fileno(), msvcrt.LK_NBLCK, 4)
        try:
            (line,), ran = micdiag.ring_lines()
        finally:
            board.seek(84)
            msvcrt.locking(board.fileno(), msvcrt.LK_UNLCK, 4)
    assert "effect version 5" in line and "last block 0.0 s ago" in line, line
    assert ran


def test_a_failure_that_went_away_while_its_log_was_built_sends_nothing(sends):
    """The effect running again by the time the log is built (its stream restarted, over
    by itself): no log. Still failing: it goes."""
    micreport.send(Cfg(), "not-running", "Mic", still=lambda: False)
    assert not sends
    micreport.send(Cfg(), "not-running", "Mic", still=lambda: True)
    assert sends == [("not-running", "not-running Mic")]


def test_the_ring_line_says_a_block_from_before_the_last_restart(monkeypatch, tmp_path):
    """The tick restarts at boot, so a block from before a restart is ahead of the clock:
    the line said "last block -15868.9 s ago". It says when it was, and never "ran"."""
    import struct

    from soundboard.mic import micring
    ring = tmp_path / "ring2.bin"
    raw = bytearray(micring.new_ring_bytes())
    struct.pack_into("<Q", raw, 72, micring._tick() + 15_868_900)
    struct.pack_into("<I", raw, 80, 5)
    ring.write_bytes(bytes(raw))
    monkeypatch.setattr(micdiag, "ring_path", lambda: ring)
    (line,), ran = micdiag.ring_lines()
    assert "last block before the last restart" in line and " -" not in line, line
    assert not ran


def _verdict(lines):
    return next(s for s in lines if s.startswith("verdict:"))


def test_a_mic_the_effect_shut_is_the_verdict_not_what_taking_it_off_left(monkeypatch):
    """Exit code 10: the effect came off a mic that wouldn't open with it (a Bluetooth
    hands-free headset's), which unregisters it and empties the mic's settings. Those were
    in the verdict as if they were why it failed."""
    looks(monkeypatch, dll_lines=([], ["effect-not-registered"]), fx=lambda g: {},
          mic_check_lines=([], ["engine-did-not-load-effect"]))
    micdiag._stages.clear()
    verdict = _verdict(micdiag.findings([GUID], micdiag.MIC_SHUT_UNDONE))
    assert verdict == "verdict: mic-wont-open-with-effect"
    assert "effect-not-registered" in _verdict(micdiag.findings([GUID], 8))


def _effect_log(monkeypatch, tmp_path, text):
    monkeypatch.setattr(micdiag, "data_dir", lambda: tmp_path)
    (tmp_path / micdiag.APO_LOG).write_text(text, encoding="utf-8")


def test_formats_the_effect_was_asked_for_and_never_ran_with(monkeypatch, tmp_path):
    """The engine loaded it and asked it for formats, but never locked it: on two PCs a
    USB mic behind Intel's audio asked only for formats it doesn't take."""
    old = ("1 pid 1: dll loaded in AUDIODG.EXE\n"
           "2 pid 1: format asked: tag 65534, 48000 Hz, 2 ch, 32 bits (other side set)\n"
           "3 pid 1: lock: 48000 Hz, 2 ch, float 1\n")
    new = ("4 pid 2: dll loaded in AUDIODG.EXE\n"
           "5 pid 2: initialize: endpoint {X}, 56 bytes, discovery 0, child no\n"
           "6 pid 2: format asked: tag 65534, 48000 Hz, 1 ch, 32 bits (other side set)\n"
           "7 pid 2: format asked: tag 65534, 48000 Hz, 1 ch, 16 bits (other side set)\n")
    _effect_log(monkeypatch, tmp_path, old + new)
    lines, causes = micdiag.effect_said()
    assert causes == ["format-refused"]
    assert "48000 Hz, 1 ch, 32 bits, tag 65534, 48000 Hz, 1 ch, 16 bits" in lines[0]
    _effect_log(monkeypatch, tmp_path, old)   # it ran: nothing to say
    assert micdiag.effect_said() == ([], [])


def test_not_loaded_is_found_without_rights_to_the_audio_engine(monkeypatch, tmp_path):
    """As admin the engine's files can't be listed (error 5): the verdict said
    nothing-found, and the same set-up as SYSTEM said engine-did-not-load-effect. The
    effect writing nothing and running on nothing while the mic is open says it too."""
    from soundboard.audio import appaudio

    def opens(guid, during):
        during()
        return {"opens": True, "format": "48000 Hz"}
    monkeypatch.setattr(appaudio, "mic_open_report", opens)
    monkeypatch.setattr(micdiag, "_audiodg_files", lambda: (None, "can't look inside it"))
    monkeypatch.setattr(micdiag, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(micdiag, "ring_lines", lambda: ([], False))
    assert "engine-did-not-load-effect" in micdiag.mic_check_lines(GUID)[1]
    assert micdiag.mic_check_lines(GUID, ours=False)[1] == []   # it isn't on the mic
    (tmp_path / micdiag.APO_LOG).write_text("x", encoding="utf-8")   # it wrote: it loaded
    assert micdiag.mic_check_lines(GUID)[1] == []


def test_an_older_apps_effect_file_is_named(monkeypatch, tmp_path):
    installed, bundled = tmp_path / "obmic-old.dll", tmp_path / "obmic.dll"
    installed.write_bytes(b"old")
    bundled.write_bytes(b"new")
    monkeypatch.setattr(micdiag, "_key_values", lambda root, path: {"": str(installed)})
    monkeypatch.setattr(micdiag, "bundled_dll", lambda: bundled)
    monkeypatch.setattr(micdiag, "_sddl", lambda p: "")
    assert "effect-file-old" in micdiag.dll_lines()[1]
    bundled.write_bytes(b"old")
    assert "effect-file-old" not in micdiag.dll_lines()[1]


def test_equalizer_apo_in_the_effects_place_is_named(monkeypatch):
    eapo = "{EACD2258-FCAC-4FF4-B36D-419E924A6D79}"
    looks(monkeypatch, fx=lambda g: {micdiag.FX % 5: eapo})
    monkeypatch.setattr(micdiag, "_effect_name",
                        lambda c: "EqualizerAPO Pre-Mix Class EqualizerAPO.dll")
    micdiag._stages.clear()
    assert _verdict(micdiag.findings([GUID])) == "verdict: settings-lost equalizer-apo-on-mic"


def test_one_verdict_on_top_the_admin_steps(monkeypatch, tmp_path):
    """The step as SYSTEM and the look as the user both wrote one, and they were both put
    on top, saying opposite things."""
    from soundboard.mic import directmic
    monkeypatch.setattr(directmic, "data_dir", lambda: tmp_path / "MicPlugin")
    (tmp_path / "MicPlugin").mkdir()
    report = tmp_path / "r.log"
    report.write_text("+  72.28s verdict: engine-did-not-load-effect\n", encoding="utf-8")
    monkeypatch.setattr(micdiag, "report_path", lambda: report)
    monkeypatch.setattr(micdiag, "snapshot", lambda g: ["=== now", "verdict: nothing-found"])
    head = micreport.build("code-8", "Microphone", GUID).split("\n\n")[0].splitlines()
    assert [s for s in head if "verdict" in s] == ["verdict: engine-did-not-load-effect"]
    report.unlink()   # no step: the look's
    head = micreport.build("not-running", "Microphone", GUID).split("\n\n")[0]
    assert head.endswith("verdict: nothing-found")
    head = micreport.build("virtual-mic", "Microphone", GUID).split("\n\n")[0]
    assert head.endswith("verdict: virtual-mic-skipped")
