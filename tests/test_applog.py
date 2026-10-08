"""Crash reporting: every unhandled error is logged, saved (scrubbed) and offered
to the user once, from whichever thread it happened on."""
import threading
from pathlib import Path

import pytest

from conftest import own_time
from soundboard import applog


@pytest.fixture(autouse=True)
def _real_reporter(monkeypatch):
    """conftest swaps report() for one that fails the test; these tests are about it."""
    monkeypatch.setattr(applog, "report", applog._real_report)


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    """A clean reporter writing into tmp_path; dialogs recorded instead of shown."""
    log_path = tmp_path / applog.LOG_NAME
    log_path.write_text("line one\nline two\n", encoding="utf-8")
    monkeypatch.setattr(applog, "_state", {"log_path": log_path, "version": "9.9",
                                           "dialogs": 0, "seen": set(), "open": None,
                                           "bridge": None})
    shown = []
    monkeypatch.setattr(applog, "_show_dialog", shown.append)
    return log_path, shown


def _raise(exc):
    try:
        raise exc
    except Exception as e:  # noqa: BLE001
        return e


def test_scrub_hides_home_and_user_name(monkeypatch):
    monkeypatch.setenv("USERNAME", "alice")
    monkeypatch.setenv("COMPUTERNAME", "ALICE-PC")
    home = str(Path.home())
    text = applog.scrub(f"File {home}\\x.py, {home.replace(chr(92), '/')}/y, alice on alice-pc, "
                        "malice stays")
    assert home not in text and "%USERPROFILE%" in text
    assert "<user> on <pc>" in text
    assert "malice" in text   # only whole words


def test_report_saves_scrubbed_file_and_offers_it(fresh):
    log_path, shown = fresh
    rep = applog.report(_raise(ValueError(f"bad file {Path.home()}\\a.wav")), where="loading")
    assert rep is not None and rep.title.startswith("ValueError: bad file %USERPROFILE%")
    assert "Version:  9.9" in rep.text and "Where:    loading" in rep.text
    assert "line two" in rep.text   # the log tail rides along
    assert rep.path is not None and rep.path.read_text(encoding="utf-8") == rep.text
    assert str(Path.home()) not in rep.path.read_text(encoding="utf-8")
    assert shown == [rep]


def test_same_bug_is_offered_once(fresh):
    _, shown = fresh

    def boom():
        raise KeyError("x")
    for _ in range(3):
        try:
            boom()
        except KeyError:
            applog.report()
    assert len(shown) == 1


def test_dialog_cap_and_open_dialog_collects_more(fresh):
    _, shown = fresh
    first = applog.report(_raise(ValueError("a")))
    applog._state["open"] = first
    applog.report(_raise(TypeError("b")))
    assert len(shown) == 1 and first.extra == ["TypeError: b"]
    applog._state["open"] = None
    applog._state["dialogs"] = applog.MAX_DIALOGS
    applog.report(_raise(OSError("c")))
    assert len(shown) == 1   # capped, still logged and saved


def test_report_with_nothing_to_report(fresh):
    assert applog.report() is None


def test_report_never_raises(fresh, monkeypatch):
    monkeypatch.setattr(applog, "build_report", lambda *a, **k: 1 / 0)
    assert applog.report(_raise(ValueError("x"))) is None


def test_old_reports_are_pruned(fresh):
    log_path, _ = fresh
    folder = log_path.parent / applog.REPORTS_DIR
    folder.mkdir()
    for i in range(applog.KEEP_REPORTS + 5):
        (folder / f"crash-2000010{i:02d}-000000-1.txt").write_text("x")
    applog.report(_raise(ValueError("new")))
    assert len(list(folder.glob("crash-*.txt"))) == applog.KEEP_REPORTS


def test_thread_error_reaches_the_ui_thread(qapp, tmp_path, monkeypatch):
    log_path = tmp_path / applog.LOG_NAME
    monkeypatch.setattr(applog, "_state", {"log_path": log_path, "version": "t", "dialogs": 0,
                                           "seen": set(), "open": None, "bridge": None})
    got = []
    monkeypatch.setattr(applog, "_show_dialog", lambda rep: got.append(
        (rep, threading.current_thread() is threading.main_thread())))
    applog.ui_ready()   # binds the (patched) _show_dialog on this, the UI thread
    t = threading.Thread(target=lambda: applog.report(_raise(ZeroDivisionError("w")),
                                                      where="worker"))
    t.start()
    t.join()
    assert got == []   # not shown from the worker thread itself
    qapp.processEvents()
    assert len(got) == 1 and got[0][1] is True
    assert "Where:    worker" in got[0][0].text


def test_crash_dialog_copies_report(qapp, monkeypatch):
    from PySide6.QtGui import QGuiApplication

    from soundboard.ui import crashdialog
    rep = applog.Report(title="ValueError: x", text="REPORT BODY")
    rep.extra.append("TypeError: y")
    opened = []
    monkeypatch.setattr(crashdialog.QDesktopServices, "openUrl",
                        lambda url: opened.append(url.toString()) or True)
    dlg = crashdialog.CrashDialog(rep, None)
    dlg.open_issue()
    clip = QGuiApplication.clipboard().text()
    assert clip.startswith("REPORT BODY") and "TypeError: y" in clip
    assert opened and opened[0].startswith(crashdialog.ISSUE_URL)
    assert "Crash" in opened[0] and "REPORT BODY" not in opened[0]   # report stays local
    assert not dlg.folder_btn.isEnabled()
    dlg.close()


def _state_in(tmp_path, monkeypatch):
    log_path = tmp_path / applog.LOG_NAME
    log_path.write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(applog, "_state", {"log_path": log_path, "version": "t",
                                           "dialogs": 0, "seen": set(), "open": None,
                                           "bridge": None, "pending": None})
    return log_path


def test_held_back_report_is_shown_once_the_app_is_in_front(qapp, tmp_path, monkeypatch):
    """An error while a game had the focus waits; it must appear when the user comes
    back (applicationStateChanged fires before activeWindow() is set: not enough)."""
    from PySide6.QtWidgets import QApplication, QWidget

    from soundboard.ui import crashdialog
    from conftest import process_events
    _state_in(tmp_path, monkeypatch)
    shown = []

    class FakeDialog:
        def __init__(self, rep, *_a, **_k):
            shown.append(rep)
            self.finished = type("Sig", (), {"connect": lambda self, f: None})()

        def show(self):
            pass

        def raise_(self):
            pass
    monkeypatch.setattr(crashdialog, "CrashDialog", FakeDialog)
    applog.ui_ready()
    try:
        assert QApplication.activeWindow() is None
        rep = applog.report(_raise(ValueError("boom")))
        assert applog._state["pending"] is rep and shown == []
        w = QWidget()
        w.show()
        w.activateWindow()
        process_events(qapp, lambda: bool(shown), 3)
        w.close()
        assert shown == [rep] and applog._state["pending"] is None
    finally:
        qapp.focusWindowChanged.disconnect(applog._show_pending)


USERS = r"C:\Users"   # + a made-up profile folder in each test


def test_long_title_is_scrubbed_before_it_is_cut(monkeypatch):
    monkeypatch.setenv("USERNAME", "ExampleUser")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path(USERS, "ExampleUser")))
    msg = rf"in use: '{USERS}\ExampleUser\AppData\Roaming\OnionBoard\config.json'"
    pad = "x" * (197 - len("PermissionError: ") - msg.index("ExampleUser") - 6)
    rep = applog.build_report((PermissionError, PermissionError(pad + msg), None))
    assert "Exampl" not in rep.title and len(rep.title) <= 200


@pytest.mark.parametrize("text", [
    rf'File "{USERS}\EXAMPL~1\AppData\Local\Temp\x.webm"',     # 8.3 short form (%TEMP%)
    repr(rf"{USERS}\EXAMPL~1\AppData"),                         # ...in a repr
    "file:///" + USERS.replace("\\", "/") + "/Example%20User/Music/a.mp3",   # a file URL
])
def test_scrub_catches_other_spellings_of_the_home_folder(monkeypatch, text):
    monkeypatch.setenv("USERNAME", "Example User")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path(USERS, "Example User")))
    out = applog.scrub(text)
    assert "EXAMPL" not in out.upper() and "Example%20User" not in out
    assert "%USERPROFILE%" in out


def test_device_names_carrying_the_owners_name_are_cut_from_the_log(tmp_path, monkeypatch):
    """Windows names Bluetooth headsets after their owner, and the log names devices."""
    log_path = _state_in(tmp_path, monkeypatch)
    log_path.write_text("INFO soundboard.engine: opened mic: Headset (Alex's AirPods Pro)\n"
                        "INFO it's fine\n", encoding="utf-8")
    rep = applog.build_report((ValueError, ValueError("x"), None))
    assert "Alex" not in rep.text and "Headset (<name>'s AirPods Pro)" in rep.text
    assert "it's fine" in rep.text


def test_two_reports_in_the_same_second_keep_both_files(tmp_path, monkeypatch):
    _state_in(tmp_path, monkeypatch)
    monkeypatch.setattr(applog, "_show_dialog", lambda rep: None)
    real = applog.time.strftime
    monkeypatch.setattr(applog.time, "strftime",
                        lambda fmt, *a: "20260101-120000" if fmt == "%Y%m%d-%H%M%S"
                        else real(fmt, *a))
    a = applog.report(_raise(ValueError("first")))
    b = applog.report(_raise(KeyError("second")))
    assert a.path != b.path
    assert a.path.read_text(encoding="utf-8") == a.text
    assert b.path.read_text(encoding="utf-8") == b.text


def test_same_bug_again_skips_the_file_and_logs_one_counted_line(fresh, monkeypatch):
    """A paint handler or timer can throw every frame: only the first one costs a
    traceback, a log read and a file; the rest are counted on a rate-limited line."""
    log_path, shown = fresh
    folder = log_path.parent / applog.REPORTS_DIR
    lines = []
    monkeypatch.setattr(applog.log, "error", lambda fmt, *a: lines.append(fmt % a))
    monkeypatch.setattr(applog.log, "critical", lambda *a, **k: None)
    built = []
    real_build = applog.build_report
    monkeypatch.setattr(applog, "build_report",
                        lambda *a, **k: built.append(1) or real_build(*a, **k))
    now = [1000.0]
    own_time(monkeypatch, applog, monotonic=lambda: now[0])

    def boom():
        raise KeyError("x")
    reps = []
    for _ in range(50):
        try:
            boom()
        except KeyError:
            reps.append(applog.report())
    assert reps[0] is not None and reps[1:] == [None] * 49
    assert len(built) == 1 and len(list(folder.glob("crash-*.txt"))) == 1
    assert len(shown) == 1
    assert len(lines) == 1 and "1 time since" in lines[0]   # the first repeat
    now[0] += applog.REPEAT_LOG_S
    try:
        boom()
    except KeyError:
        applog.report()
    assert len(lines) == 2 and "49 times since" in lines[1]


def test_a_fatal_repeat_is_still_reported(fresh):
    _, shown = fresh
    applog.report(_raise(ValueError("a")))
    rep = applog.report(_raise(ValueError("a")), fatal=True)
    assert rep is not None and rep.path is not None and shown[-1] is rep


def test_open_dialog_lists_at_most_max_extra(fresh):
    first = applog.report(_raise(ValueError("a")))
    applog._state["open"] = first
    for i in range(applog.MAX_EXTRA + 10):
        # same line, new exception type each time: a new bug each time
        applog.report(_raise(type(f"E{i}", (Exception,), {})(str(i))))
    assert len(first.extra) == applog.MAX_EXTRA


@pytest.fixture
def root_logging(monkeypatch):
    """setup() replaces the root logger's handlers: put pytest's back afterwards."""
    import logging
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    monkeypatch.setattr(applog, "_state", dict(applog._state, log_path=None))
    monkeypatch.setattr(applog.sys, "stderr", None)
    yield root
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()
    for h in handlers:
        root.addHandler(h)
    root.setLevel(level)


def test_app_log_follows_the_config(tmp_path, root_logging):
    """Settings' "Keep an app log": on unless config.json says false."""
    assert applog.wanted(tmp_path)   # no config yet
    (tmp_path / "config.json").write_text('{"app_log": false}', encoding="utf-8")
    assert not applog.wanted(tmp_path)
    path = applog.setup(tmp_path)
    root_logging.info("a site failed")
    assert not path.exists() and not applog.keeping()
    # a crash report still gets this run's last lines, from memory
    assert "a site failed" in applog._log_tail(path, 10)


def test_unticking_the_app_log_deletes_it_and_ticking_starts_it_again(tmp_path,
                                                                       root_logging):
    path = applog.setup(tmp_path, keep_log=True)
    (tmp_path / (applog.LOG_NAME + ".1")).write_text("older\n", encoding="utf-8")
    root_logging.info("before")
    assert path.exists() and applog.keeping()
    applog.keep(False)
    root_logging.info("while off")
    assert not path.exists() and not (tmp_path / (applog.LOG_NAME + ".1")).exists()
    tail = applog._log_tail(path, 10)
    assert "before" in tail and "while off" in tail
    applog.keep(True)
    root_logging.info("back on")
    applog.flush()
    text = path.read_text(encoding="utf-8")
    assert "back on" in text and "while off" not in text


def test_a_slow_disk_doesnt_hold_up_a_log_line(tmp_path, root_logging):
    """A 1.9.7 freeze: a warning on the UI thread waited 5 s for the log file's flush.
    Lines are written on the log's own thread now."""
    import time
    path = applog.setup(tmp_path, keep_log=True)
    h = next(h for h in root_logging.handlers if isinstance(h, applog._Background))
    gate, real = threading.Event(), h.file.emit

    def slow(record):   # a disk that's busy (or an antivirus scan of the log)
        gate.wait(5)
        real(record)
    h.file.emit = slow
    start = time.monotonic()
    root_logging.warning("can't also send into %s", "a cable")
    assert time.monotonic() - start < 0.5
    gate.set()
    applog.flush()
    line = path.read_text(encoding="utf-8").strip().splitlines()[-1]
    assert line.endswith("root: can't also send into a cable") and "WARNING" in line


def test_a_traceback_logged_off_the_ui_thread_keeps_its_lines(tmp_path, root_logging):
    path = applog.setup(tmp_path, keep_log=True)
    try:
        raise ValueError("bad thing")
    except ValueError:
        root_logging.exception("it failed")
    applog.flush()
    text = path.read_text(encoding="utf-8")
    assert "it failed" in text and "ValueError: bad thing" in text and "Traceback" in text


def test_app_commands_under_test_never_log_into_the_real_app_folder():
    """app.py took its own copy of APP_DIR: a test of --uninstall-count set up the log
    in the real app folder (%APPDATA%), and every later test's lines went there."""
    import os

    from soundboard import app, library, updates
    real = Path(os.environ.get("APPDATA", Path.home())) / "OnionBoard"
    for d in (app.APP_DIR, updates.APP_DIR, library.APP_DIR):
        assert not Path(d).is_relative_to(real), d


@pytest.mark.parametrize("exc", [
    OSError(28, "No space left on device"),
    PermissionError(13, "Permission denied"),
    MemoryError(),
    ConnectionResetError(104, "reset"),
])
def test_the_pcs_situation_is_said_plainly_not_reported_as_a_crash(fresh, monkeypatch, exc):
    """A full disk or a file another program holds isn't a bug: no crash dialog, no
    saved report (it would count as an error/<version> problem), a plain message."""
    log_path, shown = fresh
    said = []
    monkeypatch.setattr(applog, "_show_plain", said.append)
    assert applog.report(_raise(exc), where="saving a clip") is None
    assert shown == [] and len(said) == 1
    assert not (log_path.parent / applog.REPORTS_DIR).exists()
    applog.report(_raise(exc), where="saving a clip")   # the same again: said once
    assert len(said) == 1


def test_a_missing_file_is_still_a_bug_worth_a_report(fresh):
    _log_path, shown = fresh
    assert applog.report(_raise(FileNotFoundError(2, "No such file"))) is not None
    assert len(shown) == 1


def test_a_late_callback_to_a_closed_window_is_saved_but_not_shown(fresh):
    # a timer / signal reaching a freed widget: still counted, but the user lost nothing
    _, shown = fresh
    rep = applog.report(_raise(RuntimeError(
        "Internal C++ object (QPushButton) already deleted.")))
    assert rep is not None and rep.path is not None and rep.path.exists()
    assert shown == []
    try:   # another line, so not "the same bug again"
        raise RuntimeError("something else")
    except RuntimeError as e:
        assert applog.report(e)
    assert len(shown) == 1
