"""Crash reporting: every unhandled error is logged, saved (scrubbed) and offered
to the user once, from whichever thread it happened on."""
import threading
from pathlib import Path

import pytest

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
