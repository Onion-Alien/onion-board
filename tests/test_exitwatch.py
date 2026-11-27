"""exitwatch.py: why the last run ended without closing itself."""
import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from soundboard import __version__
from soundboard.core import applog, exitwatch, usage


@pytest.fixture
def app_dir(tmp_path, monkeypatch):
    monkeypatch.setitem(applog._state, "log_path", tmp_path / applog.LOG_NAME)
    yield tmp_path
    exitwatch.stopped()


def _native(stack_file=r"D:\Apps\OnionBoard\soundboard\audio\engine.py"):
    return ("Windows fatal exception: access violation\n\n"
            "Thread 0x0000aaaa (most recent call first):\n"
            '  File "soundboard\\online\\radio.py", line 12 in run\n\n'
            "Current thread 0x0000bbbb (most recent call first):\n"
            '  File "PySide6\\QtCore.py", line 3 in exec\n'
            f'  File "{stack_file}", line 1090 in _callback\n'
            '  File "soundboard\\core\\app.py", line 500 in main\n')


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


def test_faulthandler_is_armed_early_and_exitwatch_takes_over(app_dir):
    """app.py reads the last run's native-crash.txt, then arm_faulthandler before the
    window is built (a native crash while Qt/modules load is caught); ExitWatch's own
    handle replaces the early one at start()."""
    (app_dir / exitwatch.NATIVE).write_text("old run's stacks", encoding="utf-8")
    _, native = exitwatch.read_last(app_dir)
    assert native == "old run's stacks"        # app.py reads it first...
    exitwatch.arm_early(app_dir)               # ...then arms faulthandler (a fresh file)
    assert exitwatch._early_native is not None
    assert (app_dir / exitwatch.NATIVE).read_text(encoding="utf-8") == ""
    w = exitwatch.start(app_dir)               # ExitWatch's own handle takes over
    assert exitwatch._early_native is None and w._native is not None
    exitwatch.stopped()


def test_a_native_crash_names_the_error_and_our_deepest_line():
    assert exitwatch.native_summary(_native()) == ("access-violation",
                                                   "soundboard/audio/engine.py:1090")
    assert exitwatch.diagnose({}, _native(), [], 0) == (
        "native-crash", "access-violation@soundboard/audio/engine.py:1090")
    assert exitwatch.native_summary(
        "Windows fatal exception: code 0xc0000409\n\nCurrent thread 0x1 (most recent "
        "call first):\n  <no Python frame>\n") == ("fast-fail", "")
    assert exitwatch.native_summary("Fatal Python error: Aborted\n") == ("aborted", "")
    # two folders down (the tabs' own folders) is still ours
    assert exitwatch.native_summary(
        _native(r"D:\Apps\OnionBoard\soundboard\ui\apps\appspanel.py")) == (
        "access-violation", "soundboard/ui/apps/appspanel.py:1090")


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
        {"kind": "windows-error", "code": "access-violation", "module": "Qt6Core.dll",
         "offset": "0x1c8d8"},
        {"kind": "not-responding", "code": "", "module": "", "offset": ""}]
    assert exitwatch.parse_events("garbage <Event>not xml", 5) == []


@pytest.mark.parametrize("state, events, booted, want", [
    ({}, [{"kind": "windows-error", "code": "0xdeadbeef", "module": ""}], 0,
     ("windows-error", "0xdeadbeef")),
    ({"quitting": True}, [{"kind": "not-responding", "code": "", "module": ""}], 0,
     ("not-responding", "")),
    ({"quitting": True, "stuck_s": 30}, [], 0, ("while-closing", "")),
    ({"quitting": True, "closed_by_windows": True, "alive": 100}, [], 200,
     ("windows-closed", "")),
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
    now = time.time()
    (app_dir / exitwatch.STATE).write_text(json.dumps(
        {"version": "1.9.8", "pid": 42, "started": now - 60, "alive": now,
         "stuck_s": 0, "quitting": True, "run": "r-0123456789ab"}), encoding="utf-8")
    (app_dir / exitwatch.NATIVE).write_text(_native(), encoding="utf-8")
    state, native = exitwatch.read_last(app_dir)
    exitwatch.start(app_dir)   # this run's black box replaces the files...
    assert exitwatch.read_last(app_dir)[1] == ""
    event, path = exitwatch.check_last(
        app_dir, state, native, usage.event("unclean_exit", version="1.9.8"))
    assert event["attrs"] == {"version": "1.9.8", "why": "native-crash",
                              "detail": "access-violation@soundboard/audio/engine.py:1090",
                              "closing": "yes", "lasted_s": 60}
    # read with the run that crashed (it came in with no run, so its events couldn't
    # be matched), not with this fresh start's place and screen
    assert event["from_run"] == "r-0123456789ab"
    assert not {"seq", "since_start_s", "ctx"} & event.keys()
    text = path.read_text(encoding="utf-8")
    assert "Why:      native-crash" in text and "Closing:  yes" in text
    assert "last words" in text and "this run" not in text   # the last run's log only
    # already counted as unclean-exit/: not again as an error/ report
    assert usage.problems(app_dir, 0) == ([], path.stat().st_mtime)


@pytest.mark.parametrize("closed_by_windows, booted", [(True, 0.0), (False, 1e12)])
def test_ended_by_windows_or_a_restart_is_not_a_problem(app_dir, monkeypatch,
                                                        closed_by_windows, booted):
    """A log-off, a PC restart or the update installer ending the app mid-quit came in
    as unclean-exit/…/while-closing and …/pc-restarted: false alarms."""
    monkeypatch.setattr(exitwatch, "windows_events", lambda pid: [])
    monkeypatch.setattr(exitwatch, "boot_time", lambda: booted)
    w = exitwatch.start(app_dir)
    if closed_by_windows:   # Windows asked, the quit started, then Windows ended it
        exitwatch.closed_by_windows()
        exitwatch.quitting()
    state, native = exitwatch.read_last(app_dir)
    assert state.get("closed_by_windows", False) is closed_by_windows
    w._stop.set()   # ...and the process is ended here, before stopped()
    assert exitwatch.check_last(
        app_dir, state, native, usage.event("unclean_exit", version="1.9.8")) == (None, None)
    assert not list((app_dir / applog.REPORTS_DIR).glob("crash-*.txt"))


def test_an_installer_that_didnt_start_takes_the_mark_back(app_dir):
    """Marked before the update installer starts (it can end the app before it's back);
    when it couldn't start, the app goes on and a later crash counts again."""
    w = exitwatch.start(app_dir)
    exitwatch.closed_by_windows()
    exitwatch.staying()
    state, _native = exitwatch.read_last(app_dir)
    assert "closed_by_windows" not in state
    w.stopped()


def test_the_heartbeat_notes_a_stuck_window(app_dir, monkeypatch):
    monkeypatch.setattr(exitwatch, "HEARTBEAT_S", 0.02)
    exitwatch.start(app_dir, lambda: 9.0)
    # one read that saw it: a second one can land while the heartbeat swaps the file in,
    # which Windows refuses (read_last then says {}, as it would for no file)
    seen, deadline = None, time.time() + 5
    while seen != 9.0 and time.time() < deadline:
        seen = exitwatch.read_last(app_dir)[0].get("stuck_s")
        time.sleep(0.02)
    assert seen == 9.0


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
        '  File "soundboard\\sounds\\thumbs.py", line 259 in _read_loop\n')


def test_a_thread_that_was_only_running_is_never_blamed():
    """No stack for the crashing thread: it crashed on a thread Python doesn't know (a
    driver's, Qt's). The relay thread listed first was only waiting in select, so the
    count names the DLL from Windows' log, not that line."""
    dump = ("Windows fatal exception: access violation\n\n"
            "Thread 0x0000265c (most recent call first):\n"
            '  File "soundboard\\online\\netrelay.py", line 309 in _pipe\n'
            '  File "threading.py", line 994 in run\n')
    assert exitwatch.native_summary(dump) == ("access-violation", "")
    assert exitwatch.diagnose({}, dump, [], 0.0) == ("native-crash", "access-violation")
    events = [{"kind": "windows-error", "code": "access-violation", "module": "Qt6Core.dll"}]
    kind, tag = exitwatch.diagnose({}, dump, events, 0.0)
    assert kind == "native-crash" and tag.startswith("access-violation@")   # (split: not
    assert tag.endswith("Qt6Core.dll")                                      # an e-mail)
    # our own line on the crashing thread, and the DLL after it: the line is often only
    # where Python was (the event loop) when the DLL's own code crashed
    kind, tag = exitwatch.diagnose({}, _native(), events, 0.0)
    assert kind == "native-crash"
    assert tag.startswith("access-violation@soundboard/audio/engine.py:1090@")
    assert tag.endswith("Qt6Core.dll")


def test_the_report_says_where_in_the_dll():
    """The fault's offset in the DLL goes in the saved report (to look the function
    up), never in the count."""
    events = [{"kind": "windows-error", "code": "access-violation", "module": "Qt6Gui.dll",
               "offset": "0x1c8d8"}]
    kind, tag = exitwatch.diagnose({}, _native(), events, 0.0)
    assert "0x1c8d8" not in tag
    text = exitwatch.report_text({}, _native(), events, kind, tag, "")
    assert "Qt6Gui.dll+0x1c8d8" in text


def test_a_dump_of_a_harmless_code_cut_off_by_a_crash_is_a_crash():
    """Walking another thread's frames for a harmless code crashed mid-line: not harmless,
    and named after the crash, not the code that set off the dump."""
    cut = _COM + ('  File "numpy\\_core\\fromnumeric.py", line 0 in max\n'
                  "  File Windows fatal exception: access violation\n\n")
    assert not exitwatch.only_harmless(cut)
    assert exitwatch.diagnose({}, cut, [], 0.0) == ("native-crash", "access-violation")


def test_the_line_is_the_crashs_own_not_a_harmless_code_before_it():
    """A harmless COM code on one thread, then a real crash on another before the next
    heartbeat cleared the file: each wrote only its own thread's stack. The count names
    the crash and the line on ITS thread, never the line the COM code was raised on."""
    com = ("Windows fatal exception: code 0x8001010d\n\n"
           "Stack (most recent call first):\n"
           '  File "soundboard\\ui\\kit\\seek.py", line 30 in paintEvent\n'
           '  File "soundboard\\core\\app.py", line 500 in main\n\n')
    crash = ("Windows fatal exception: access violation\n\n"
             "Stack (most recent call first):\n"
             '  File "soundboard\\voicefx\\cleanmic.py", line 406 in _send\n'
             '  File "threading.py", line 994 in run\n')
    assert exitwatch.native_summary(com + crash) == ("access-violation",
                                                     "soundboard/voicefx/cleanmic.py:406")
    # the crash's thread unknown to Python: no line, not the COM code's
    unknown = "Windows fatal exception: access violation\n\nStack (most recent call first):\n" \
              "  <no Python frame>\n"
    assert exitwatch.native_summary(com + unknown) == ("access-violation", "")
    # and a crash first, a harmless code after it: still the crash's line
    assert exitwatch.native_summary(crash + "\n" + com) == (
        "access-violation", "soundboard/voicefx/cleanmic.py:406")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' own exceptions")
def test_faulthandler_never_walks_the_other_threads(tmp_path):
    """A real (caught) access violation through arm_early. Only this thread's stack: the
    walk over other running threads is what crashed the app on a harmless COM code."""
    folder = tmp_path / "soundboard"
    folder.mkdir()
    script = folder / "crasher.py"
    script.write_text(textwrap.dedent(f"""
        import ctypes, pathlib, sys, threading, time
        sys.path.insert(0, {str(Path(exitwatch.__file__).parents[2])!r})
        from soundboard.core import exitwatch
        exitwatch.arm_early(pathlib.Path({str(tmp_path)!r}))
        threading.Thread(target=time.sleep, args=(30,), daemon=True, name="parked").start()
        time.sleep(0.2)
        try:
            ctypes.string_at(0)   # ctypes turns it into an OSError: the process lives
        except OSError:
            pass
        """), encoding="utf-8")
    subprocess.run([sys.executable, "-I", str(script)], check=True, timeout=60,
                   capture_output=True)
    dump = (tmp_path / exitwatch.NATIVE).read_text(encoding="utf-8")
    assert "time.sleep" not in dump and "Thread 0x" not in dump, dump
    err, where = exitwatch.native_summary(dump)
    assert err == "access-violation"
    assert where.startswith("soundboard/crasher.py:")


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


def test_a_qt_fatal_is_kept_for_the_next_start(tmp_path, monkeypatch):
    """A real qFatal (a QThread freed while it runs) through applog's Qt message handler:
    the process ends with Windows' fast-fail (0xC0000409, in Qt6Core.dll), which
    faulthandler never sees and before the log writer gets the line. qt-fatal.txt has
    what Qt said and our line, and the next start counts both."""
    folder = tmp_path / "soundboard"
    folder.mkdir()
    script = folder / "qtkiller.py"
    script.write_text(textwrap.dedent(f"""
        import pathlib, sys
        sys.path.insert(0, {str(Path(exitwatch.__file__).parents[2])!r})
        import shiboken6
        from PySide6.QtCore import QCoreApplication, QThread
        from soundboard.core import applog
        app = QCoreApplication([])
        applog.install_hooks(pathlib.Path({str(tmp_path)!r}) / applog.LOG_NAME, "9.9.9")

        def free_it():
            t = QThread()
            t.setObjectName("my-private-name")
            t.start()
            shiboken6.delete(t)   # Qt: "QThread: Destroyed while thread ... is still running"

        free_it()
        """), encoding="utf-8")
    r = subprocess.run([sys.executable, "-I", str(script)], timeout=60, capture_output=True)
    if sys.platform == "win32":
        assert r.returncode & 0xFFFFFFFF == 0xC0000409, (hex(r.returncode), r.stderr)
    assert r.returncode != 0
    state, native = exitwatch.read_last(tmp_path)
    qt = state["qt_fatal"]
    assert "Destroyed while thread" in qt["message"] and qt["thread"] == "MainThread"
    assert qt["frames"][-1].startswith("soundboard/qtkiller.py:") and \
        qt["frames"][-1].endswith(":free_it")

    monkeypatch.setitem(applog._state, "log_path", tmp_path / applog.LOG_NAME)
    monkeypatch.setattr(exitwatch, "windows_events", lambda pid: [
        {"kind": "windows-error", "code": "fast-fail", "module": "Qt6Core.dll"}])
    monkeypatch.setattr(exitwatch, "boot_time", lambda: 0.0)
    try:
        exitwatch.start(tmp_path)   # this run starts with none of the last run's
        assert not (tmp_path / exitwatch.QT_FATAL).exists()
        event, path = exitwatch.check_last(
            tmp_path, state, native, usage.event("unclean_exit", version="9.9.9"))
    finally:
        exitwatch.stopped()
    attrs = event["attrs"]
    assert attrs["why"] == "windows-error"
    assert attrs["detail"] == "@".join(("fast-fail", "Qt6Core.dll"))
    assert attrs["qt_fatal"] == "qthread-destroyed-while-thread-is-still-running"
    assert attrs["qt_thread"] == "MainThread"
    assert attrs["qt_where"].startswith("soundboard/qtkiller.py:")
    assert "my-private-name" not in json.dumps(event)   # the quoted name stays local
    text = path.read_text(encoding="utf-8")
    assert "Qt ended it (qFatal)" in text and "my-private-name" in text


def test_a_qt_fatal_key_keeps_only_qts_own_words():
    key = exitwatch.qt_fatal_key
    assert key("QThread: Destroyed while thread 'bob' is still running") == \
        "qthread-destroyed-while-thread-is-still-running"
    assert key('ASSERT failure in QList::at: "index out of range", '
               r"file D:\Apps\bob\x.h, line 459") == "assert-failure-in-qlist-at-file-d-h-line"
    assert key("") == "" and len(key("word " * 50)) <= 60


def test_a_clean_quit_or_a_new_start_drops_the_qt_fatal(app_dir):
    (app_dir / exitwatch.QT_FATAL).write_text("message: old\nthread: Dummy-3\n",
                                              encoding="utf-8")
    state, _ = exitwatch.read_last(app_dir)
    assert exitwatch.qt_fatal_attrs(state) == {"qt_fatal": "old", "qt_thread": "Dummy-N"}
    exitwatch.start(app_dir)
    assert not (app_dir / exitwatch.QT_FATAL).exists()
    exitwatch.note_qt_fatal(app_dir, "again")
    exitwatch.stopped()
    assert not (app_dir / exitwatch.QT_FATAL).exists()
    assert exitwatch.qt_fatal_attrs({}) == {}


def test_closing_is_sent_with_a_windows_error(app_dir, monkeypatch):
    """A windows-error wins over while-closing, so whether a quit had started is its own
    attribute: a crash at close and one hours in are told apart."""
    monkeypatch.setattr(exitwatch, "windows_events", lambda pid: [
        {"kind": "windows-error", "code": "fast-fail", "module": "Qt6Core.dll"}])
    monkeypatch.setattr(exitwatch, "boot_time", lambda: 0.0)
    now = time.time()
    state = {"version": "1", "pid": 7, "started": now - 5, "alive": now, "quitting": True}
    event, _ = exitwatch.check_last(app_dir, state, "", usage.event("unclean_exit"))
    assert event["attrs"]["closing"] == "yes"
    state["quitting"] = False
    event, _ = exitwatch.check_last(app_dir, state, "", usage.event("unclean_exit"))
    assert "closing" not in event["attrs"]


def test_stuck_where_is_recorded_for_not_responding_and_frozen(app_dir, monkeypatch):
    """HangWatch notes where the UI thread froze so a Not Responding kill or frozen exit
    says which line was stuck (and clears it once the window responds again)."""
    w = exitwatch.start(app_dir)
    exitwatch.note_stuck("soundboard/ui/window/mainwindow.py:867", 6.2)
    state, _ = exitwatch.read_last(app_dir)
    assert state["stuck_where"] == "soundboard/ui/window/mainwindow.py:867"
    assert state["stuck_s"] == 6.2
    assert exitwatch.diagnose(
        state, "", [{"kind": "not-responding", "code": "", "module": "", "offset": ""}], 0.0
    ) == ("not-responding", "soundboard/ui/window/mainwindow.py:867")
    assert exitwatch.diagnose(state, "", [], 0.0) == (
        "frozen", "soundboard/ui/window/mainwindow.py:867")
    text = exitwatch.report_text(state, "", [], "not-responding",
                                 "soundboard/ui/window/mainwindow.py:867", "")
    assert "Window stuck at: soundboard/ui/window/mainwindow.py:867" in text
    exitwatch.note_unstuck()
    cleared, _ = exitwatch.read_last(app_dir)
    assert "stuck_where" not in cleared and cleared["stuck_s"] == 0.0
    # tampered or non-soundboard paths in last-run.json are never sent
    assert exitwatch.diagnose(
        {"stuck_s": 9.0, "stuck_where": "other/secret.py:1"}, "", [], 0.0
    ) == ("frozen", "")
    w.stopped()


def test_quitting_step_is_persisted_on_slow_shutdown_and_diagnosed(app_dir, monkeypatch):
    """quitting_step() records the active shutdown step in memory (zero UI-thread disk
    I/O); if shutdown takes longer than QUITTING_BEAT_S, the heartbeat persists it."""
    monkeypatch.setattr(exitwatch, "QUITTING_BEAT_S", 0.02)
    w = exitwatch.start(app_dir)
    exitwatch.quitting()
    exitwatch.quitting_step("tor.shutdown")
    seen, deadline = "", time.time() + 5
    while seen != "tor.shutdown" and time.time() < deadline:
        seen = exitwatch.read_last(app_dir)[0].get("quit_step", "")
        time.sleep(0.02)
    assert seen == "tor.shutdown"
    state, _ = exitwatch.read_last(app_dir)
    assert exitwatch.diagnose(state, "", [], 0.0) == ("while-closing", "tor.shutdown")
    text = exitwatch.report_text(state, "", [], "while-closing", "tor.shutdown", "")
    assert "Closing step: tor.shutdown" in text
    # when a windows-error happens during shutdown, closing_step goes in attrs too
    monkeypatch.setattr(exitwatch, "windows_events", lambda pid: [
        {"kind": "windows-error", "code": "access-violation", "module": "Qt6Gui.dll",
         "offset": "0x1c8d8"}])
    monkeypatch.setattr(exitwatch, "boot_time", lambda: 0.0)
    event, _ = exitwatch.check_last(app_dir, state, "", usage.event("unclean_exit"))
    assert event["attrs"]["closing"] == "yes"
    assert event["attrs"]["closing_step"] == "tor.shutdown"
    assert event["attrs"]["offset"] == "0x1c8d8"
    assert "0x1c8d8" not in event["attrs"]["detail"]
    w.stopped()
