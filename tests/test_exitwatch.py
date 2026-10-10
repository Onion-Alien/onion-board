"""exitwatch.py: why the last run ended without closing itself."""
import json
import time

import pytest

from soundboard import __version__, applog, exitwatch, usage


@pytest.fixture
def app_dir(tmp_path, monkeypatch):
    monkeypatch.setitem(applog._state, "log_path", tmp_path / applog.LOG_NAME)
    yield tmp_path
    exitwatch.stopped()


def _native(stack_file=r"D:\Apps\OnionBoard\soundboard\engine.py"):
    return ("Windows fatal exception: access violation\n\n"
            "Thread 0x0000aaaa (most recent call first):\n"
            '  File "soundboard\\radio.py", line 12 in run\n\n'
            "Current thread 0x0000bbbb (most recent call first):\n"
            '  File "PySide6\\QtCore.py", line 3 in exec\n'
            f'  File "{stack_file}", line 1090 in _callback\n'
            '  File "soundboard\\app.py", line 500 in main\n')


def test_a_clean_quit_leaves_nothing_to_explain(app_dir):
    w = exitwatch.start(app_dir)
    state, native = exitwatch.read_last(app_dir)
    assert state["pid"] == w.state["pid"] and state["version"] == __version__
    assert not state["quitting"] and native == ""
    exitwatch.quitting()
    assert exitwatch.read_last(app_dir)[0]["quitting"] is True
    exitwatch.stopped()
    assert exitwatch.read_last(app_dir) == ({}, "")
    assert not (app_dir / exitwatch.NATIVE).exists()


def test_a_native_crash_names_the_error_and_our_deepest_line():
    assert exitwatch.native_summary(_native()) == ("access-violation",
                                                   "soundboard/engine.py:1090")
    assert exitwatch.diagnose({}, _native(), [], 0) == (
        "native-crash", "access-violation@soundboard/engine.py:1090")
    assert exitwatch.native_summary(
        "Windows fatal exception: code 0xc0000409\n\nCurrent thread 0x1 (most recent "
        "call first):\n  <no Python frame>\n") == ("fast-fail", "")
    assert exitwatch.native_summary("Fatal Python error: Aborted\n") == ("aborted", "")


def _events(*items):
    out = []
    for provider, data in items:
        d = "".join(f"<Data>{x}</Data>" for x in data)
        out.append('<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">'
                   f"<System><Provider Name='{provider}'/></System>"
                   f"<EventData>{d}</EventData></Event>")
    return "\r\n".join(out)


def test_windows_log_events_for_this_pid_only():
    err = ["OnionBoard.exe", "1.9.9.0", "0x1", "Qt6Core.dll", "6.11", "0x2", "c0000005",
           "0x1c8d8", "0x1f40", "0x1dd", r"C:\x\OnionBoard.exe"]
    other_pid = list(err)
    other_pid[8] = "0x10"
    other_app = ["python.exe", *err[1:]]
    hang = ["OnionBoard.exe", "1.9.9.0", "1f40", "01dd", "4294967295"]
    xml = _events(("Application Error", other_pid), ("Application Error", other_app),
                  ("Application Error", err), ("Application Hang", hang))
    assert exitwatch.parse_events(xml, 0x1F40) == [
        {"kind": "windows-error", "code": "access-violation", "module": "Qt6Core.dll"},
        {"kind": "not-responding", "code": "", "module": ""}]
    assert exitwatch.parse_events("garbage <Event>not xml", 5) == []


@pytest.mark.parametrize("state, events, booted, want", [
    ({}, [{"kind": "windows-error", "code": "0xdeadbeef", "module": ""}], 0,
     ("windows-error", "0xdeadbeef")),
    ({"quitting": True}, [{"kind": "not-responding", "code": "", "module": ""}], 0,
     ("not-responding", "")),
    ({"quitting": True, "stuck_s": 30}, [], 0, ("while-closing", "")),
    ({"stuck_s": 12.5, "alive": 100}, [], 200, ("frozen", "")),
    ({"stuck_s": 0, "alive": 100}, [], 200, ("pc-restarted", "")),
    ({"stuck_s": 0, "alive": 300}, [], 200, ("ended", "")),
    ({}, [], 0, ("ended", "")),
])
def test_the_why_most_certain_first(state, events, booted, want):
    assert exitwatch.diagnose(state, "", events, booted) == want


def test_check_last_counts_it_and_saves_a_report_not_counted_twice(app_dir, monkeypatch):
    monkeypatch.setattr(exitwatch, "windows_events", lambda pid: [])
    monkeypatch.setattr(exitwatch, "boot_time", lambda: 0.0)
    (app_dir / applog.LOG_NAME).write_text(
        "x Onion Board 1.9.8 starting\nold line\nlast words\n"
        "x Onion Board 1.9.9 starting\nthis run\n", encoding="utf-8")
    (app_dir / exitwatch.STATE).write_text(json.dumps(
        {"version": "1.9.8", "pid": 42, "started": time.time() - 60, "alive": time.time(),
         "stuck_s": 0, "quitting": True}), encoding="utf-8")
    (app_dir / exitwatch.NATIVE).write_text(_native(), encoding="utf-8")
    state, native = exitwatch.read_last(app_dir)
    exitwatch.start(app_dir)   # this run's black box replaces the files...
    assert exitwatch.read_last(app_dir)[1] == ""
    event, path = exitwatch.check_last(app_dir, state, native, "unclean-exit/1.9.8")
    assert event == "unclean-exit/1.9.8/native-crash/access-violation@soundboard/engine.py:1090"
    text = path.read_text(encoding="utf-8")
    assert "Why:      native-crash" in text and "Closing:  yes" in text
    assert "last words" in text and "this run" not in text   # the last run's log only
    # already counted as unclean-exit/: not again as an error/ report
    assert usage.problems(app_dir, 0) == ([], path.stat().st_mtime)


def test_the_heartbeat_notes_a_stuck_window(app_dir, monkeypatch):
    monkeypatch.setattr(exitwatch, "HEARTBEAT_S", 0.02)
    exitwatch.start(app_dir, lambda: 9.0)
    deadline = time.time() + 5
    while time.time() < deadline:
        if exitwatch.read_last(app_dir)[0].get("stuck_s") == 9.0:
            break
        time.sleep(0.02)
    assert exitwatch.read_last(app_dir)[0]["stuck_s"] == 9.0


def test_a_native_error_that_was_caught_is_cleared_at_the_next_heartbeat(app_dir, caplog):
    w = exitwatch.start(app_dir)
    w._native.write(_native())   # as faulthandler would, for an error someone caught
    w._native.flush()
    with caplog.at_level("WARNING"):
        w._survived()
    assert exitwatch.read_last(app_dir)[1] == ""
    assert "caught and survived" in caplog.text
    w._survived()   # nothing new: nothing logged twice
    assert caplog.text.count("caught and survived") == 1


_COM = ("Windows fatal exception: code 0x8001010d\n\n"
        "Thread 0x00004bbc (most recent call first):\n"
        '  File "threading.py", line 359 in wait\n'
        '  File "soundboard\\thumbs.py", line 259 in _read_loop\n')


def test_a_harmless_windows_code_is_not_a_warning_or_a_crash(app_dir, caplog):
    """0x8001010d is COM saying "not now" and catching it itself: faulthandler still
    writes it down, but it's no warning, and no reason a run ended."""
    w = exitwatch.start(app_dir)
    w._native.write(_COM)
    w._native.flush()
    with caplog.at_level("WARNING"):
        w._survived()
    assert "caught and survived" not in caplog.text
    assert exitwatch.read_last(app_dir)[1] == ""   # cleared all the same
    assert exitwatch.only_harmless(_COM)
    assert exitwatch.diagnose({}, _COM, [], 0.0) == ("ended", "")
    # a real crash alongside it still counts
    both = _COM + "\n" + _native()
    assert not exitwatch.only_harmless(both)
    assert exitwatch.diagnose({}, both, [], 0.0)[0] == "native-crash"
    assert not exitwatch.only_harmless("Windows fatal exception: code 0xc0000005\n")
    assert not exitwatch.only_harmless("")
