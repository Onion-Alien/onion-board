"""The usage count's whole stacks, timing and context (usagetrace.py, usageevents.py): every
frame named without a path, the exceptions that led to an error, each event's place in its
run, and what the app was doing, all inside the count server's rules."""
from __future__ import annotations

import json
import re
import sys
import threading
import traceback

import pytest

from soundboard.core import usage, usageevents, usagelog, usagereports, usagetrace
from soundboard.core.usageevents import event

# the count server's rules for a value and a list
VALUE_RE = re.compile(r"^[\w/._:@<>~+-]{1,300}$")
MAX_LIST = 32
SECRET = r"D:\Home\Jane Doe\Music\secret.mp3"


@pytest.fixture
def counting(monkeypatch):
    monkeypatch.setattr(usage, "enabled", lambda: True)
    monkeypatch.setattr(usage, "_pending", [])
    monkeypatch.setattr(usage, "_warned", set())
    monkeypatch.setattr(usage, "_timed", {})
    monkeypatch.setattr(usageevents, "_context", {})


def _fits(trace: list[str]) -> bool:
    return 0 < len(trace) <= MAX_LIST and all(VALUE_RE.fullmatch(f) for f in trace)


def _chained():
    try:
        try:
            json.loads("{" + SECRET)
        except ValueError as e:
            raise KeyError(SECRET) from e
    except KeyError:
        raise RuntimeError(SECRET)  # noqa: B904 - on purpose: its context, not a cause


def test_a_library_frame_is_its_module_and_function_never_its_file():
    try:
        json.loads("{nope")
    except ValueError as e:
        trace = usagetrace.tb_trace(e.__traceback__)
    assert trace[0].startswith("tests/") or trace[0].startswith("<") or ":" in trace[0]
    assert any(f.startswith("json.decoder:") and f.endswith(":JSONDecoder.raw_decode")
               for f in trace)
    assert all("\\" not in f and ":/" not in f for f in trace)
    assert _fits(trace)


def test_our_own_frames_keep_their_file_from_the_package_down():
    def ours():
        raise ValueError("x")
    try:
        usagetrace.cut([])
        ours()
    except ValueError as e:
        frame = usagetrace.code_frame(e.__traceback__.tb_frame.f_code, 7, "tests.x")
    assert frame == "tests.x:7:test_our_own_frames_keep_their_file_from_the_package_down"
    code = compile("raise ValueError", r"D:\Jane\soundboard\audio\engine.py", "exec")
    assert usagetrace.code_frame(code, 12, "x") == "soundboard/audio/engine.py:12:<module>"


def test_a_file_outside_the_install_is_only_outside():
    code = compile("x = 1", r"D:\Home\Jane Doe\Desktop\my_script.py", "exec")
    assert usagetrace.code_frame(code, 3, "my_script") == usagetrace.OUTSIDE
    assert usagetrace.code_frame(compile("x", "<string>", "eval"), 1, "x") == usagetrace.OUTSIDE
    # a frozen copy's archive: relative names are its own files
    code = compile("x", "numpy/core/fromnumeric.py", "eval")
    assert usagetrace.code_frame(code, 42, "numpy.core.fromnumeric") == \
        "numpy.core.fromnumeric:42:<module>"


def test_the_exceptions_that_led_to_it_are_linked_stacks_nearest_first():
    try:
        _chained()
    except RuntimeError as e:
        got = usagetrace.exc_trace(e, "MainThread")
    assert got["thread"] == "MainThread"
    assert (got["cause1_type"], got["cause1_how"]) == ("KeyError", "context")
    assert (got["cause2_type"], got["cause2_how"]) == ("JSONDecodeError", "cause")
    assert "cause3_type" not in got
    for key in ("trace", "cause1_trace", "cause2_trace"):
        assert _fits(got[key])
    assert any(f.startswith("json.decoder:") for f in got["cause2_trace"])
    assert "Jane" not in json.dumps(got)


def test_from_none_hides_the_context_as_python_does():
    try:
        try:
            raise KeyError("a")
        except KeyError:
            raise ValueError("b") from None
    except ValueError as e:
        assert "cause1_type" not in usagetrace.exc_trace(e)


def test_a_long_stack_keeps_the_outermost_and_the_deepest():
    frames = [f"m{i}:1:f" for i in range(100)]
    out = usagetrace.cut(frames)
    assert len(out) == usagetrace.MAX_TRACE
    assert out[:usagetrace.HEAD] == frames[:usagetrace.HEAD]
    assert out[usagetrace.HEAD] == f"~{100 - usagetrace.MAX_TRACE + 1}"
    assert out[-1] == "m99:1:f"
    assert usagetrace.cut(["a:1:f", "<outside>", "<outside>", "b:2:g"]) == [
        "a:1:f", "<outside>", "b:2:g"]


def test_a_saved_reports_chain_reads_the_same_without_its_paths():
    try:
        _chained()
    except RuntimeError as e:
        text = "".join(traceback.format_exception(e))
    text = text.replace(str(usagetrace.Path(json.__file__).parent.parent),
                        r"D:\Home\Jane Doe\AppData\Local\Programs\OnionBoard\_internal")
    got = usagetrace.text_attrs(text, "link-dl")
    assert got["thread"] == "link-dl"
    assert (got["cause1_type"], got["cause1_how"]) == ("KeyError", "context")
    assert (got["cause2_type"], got["cause2_how"]) == ("JSONDecodeError", "cause")
    assert any(f.startswith("json.decoder:") for f in got["cause2_trace"])
    assert "Jane" not in json.dumps(got) and "Home" not in json.dumps(got)


def test_a_report_says_the_thread_it_happened_on():
    assert usagetrace.report_thread("Where:    background task 'link-dl'\n") == "link-dl"
    assert usagetrace.report_thread("Version: 1\n") == "MainThread"
    assert usagetrace.thread_tag("Thread-12 (run)") == "Thread-N_run"
    assert usagetrace.thread_tag("(?)") == ""


def test_an_error_report_carries_its_whole_trace(tmp_path):
    f = tmp_path / "crash-x.txt"
    f.write_text(
        "Onion Board crash report\nVersion:  1.9.8\nWhere:    background task 'tts-speaker'\n\n"
        "Traceback (most recent call last):\n"
        '  File "D:\\Bob\\soundboard\\core\\app.py", line 100, in main\n    run()\n'
        '  File "D:\\Bob\\_internal\\numpy\\core\\fromnumeric.py", line 42, in sum\n    x\n'
        '  File "D:\\Bob\\Desktop\\mine.py", line 3, in go\n    y\n'
        "KeyError: 'D:\\Bob\\secret.mp3'\n", encoding="utf-8")
    e = usagereports._report_event(f, 1234567.0)
    assert e["attrs"]["trace"] == ["soundboard/core/app.py:100:main",
                                   "numpy.core.fromnumeric:42:sum", "<outside>"]
    assert e["attrs"]["thread"] == "tts-speaker"
    assert "seq" not in e   # a report from before this run: no place in this one


def test_a_warned_error_carries_its_trace_and_thread(counting):
    try:
        json.loads("{" + SECRET)
    except ValueError as e:
        usage.warned(e)
    [e] = usage._pending
    assert e["attrs"]["thread"] == usagetrace.thread_tag(threading.current_thread().name)
    assert any(f.startswith("json.decoder:") for f in e["attrs"]["trace"])
    assert "Jane" not in json.dumps(e)


def test_events_of_this_run_say_their_order_and_how_far_in():
    a, b = event("x"), event("y")
    assert b["seq"] == a["seq"] + 1
    assert 0 <= a["since_start_s"] <= b["since_start_s"]
    old = event("crash", at=usageevents.BORN_WALL - 3600)   # a report from an earlier run
    assert not set(usageevents.RUN_FIELDS) & set(old)


def test_a_problem_says_what_the_app_was_doing(counting):
    usageevents.set_context(screen="sounds", lite=True, route="mic", addons=["onion-watch"])
    usageevents.set_context(lite=False)   # switched off: left out
    e = event("error", type="KeyError")
    assert {k: v for k, v in e["ctx"].items() if k != "mem"} == {
        "screen": "sounds", "route": "mic", "addons": ["onion-watch"]}
    assert "ctx" not in event(usage.FEATURE_USED, feature="x")   # info: no context
    assert "ctx" in event(usageevents.RUN_END)


def test_no_run_means_no_place_in_one():
    e = event("opt_out", where="settings")
    sent = usageevents.message([e])["events"][0]
    assert not set(usageevents.RUN_FIELDS) & set(sent)


def test_a_kept_event_says_its_run_unless_it_goes_with_that_run():
    e = usageevents.kept(event("updated"))
    assert e["from_run"] == usageevents.RUN
    assert "from_run" not in usageevents.message([e], "u-0", usageevents.RUN)["events"][0]
    assert usageevents.message([e], "u-0", "r-000000000000")["events"][0]["from_run"] == \
        usageevents.RUN


def test_timings_are_summed_and_sent_once(counting):
    for s in (1.0, 3.0, 2.0):
        usage.timed("download", s, site="youtube", ok="yes")
    usage.timed("download", 9.0, site="youtube", ok="timeout")
    usage.timed("nope", 1.0)
    usage.timed("download", -1)
    got = {e["attrs"]["ok"]: e["attrs"] for e in usage.timings()}
    assert got["yes"] == {"what": "download", "n": 3, "avg_s": 2.0, "max_s": 3.0,
                          "min_s": 1.0, "site": "youtube", "ok": "yes"}
    assert got["timeout"]["n"] == 1
    assert usage.timings() == []


def test_timings_go_with_the_next_flush(counting, monkeypatch):
    monkeypatch.setattr(usagelog, "_counter", usagelog._Counter())
    monkeypatch.setattr(usagelog, "_run_start", None)
    usage.timed("mic-setup", 4.2, ok="yes", how="install")
    usagelog.flush(type("C", (), {"stats_sent": 0})(), closing=True)
    [e] = [e for e in usage._pending if e["name"] == usageevents.TIMING]
    assert e["attrs"]["what"] == "mic-setup" and e["attrs"]["avg_s"] == 4.2


def test_a_send_with_long_stacks_stays_under_the_servers_body_limit():
    big = [event("error", trace=[f"some.module.name:{i}:a_function_name" for i in range(32)],
                 cause1_trace=[f"other.module:{i}:f" for i in range(32)]) for _ in range(100)]
    parts = usage.parts(big)
    assert len(parts) > 1 and sum(map(len, parts)) == 100
    assert all(len(json.dumps(usageevents.message(p, "u-0", "r-0"))) < 128 * 1024 for p in parts)
    assert usage.parts([]) == [[]]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' own record of the start")
def test_the_run_counts_from_the_process_start():
    assert 0 < usageevents._process_age() < 3600
