"""The mic set-up log: what it finds, who it never names, and when it's sent."""
from __future__ import annotations

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
    monkeypatch.setattr(micdiag, "findings", lambda g: ["=== why", "verdict: x"])
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

    class Now:
        def __init__(self, target, **kw):
            self.target = target

        def start(self):
            self.target()
    monkeypatch.setattr(micreport.threading, "Thread", Now)
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
