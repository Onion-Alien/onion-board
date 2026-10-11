"""The mic helper (soundboard/michelper.py): the admin steps of the mic effect without
Windows' prompt each time. Nothing here touches Task Scheduler or Program Files: the
conftest guard points the helper's folders into tmp_path and fails any schtasks call."""
from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from soundboard import directmic as dm
from soundboard import michelper as mh

GUID = "{0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0}"
SID = "S-1-5-21-1111111111-2222222222-3333333333-1001"
SID2 = "S-1-5-21-1111111111-2222222222-3333333333-1002"
ENTRA = "S-1-12-1-1234567890-1234567890-1234567890-1234567890"   # work / school account
REAL_ELEVATED = dm._elevated   # (the conftest guard replaces it in every test)
REAL_SCHTASKS = mh._schtasks   # (so is this)
ROOT = Path(__file__).resolve().parent.parent

# HELPER_VERSION and the admin code it stands for: change one, change the other
ADMIN_DIGEST = {3: "89146326524eb7d36f3526e5f7b561046e846aa1ef2afccecba4c37132f4c620",
                4: "b49bed37327a635032e846b3f51e1b47fc5ebcaef7ee4078d03c95528a142370",
                5: "bcb73271a6c0e0f7fc1730791a24626a6dedf6ea39d258831ef5aca196012467",
                6: "9b83750c3d3586a89804c5ec5c97618fc1ce30b511723e4e3cf3525513c9a534"}


def _queue():
    mh.requests_dir().mkdir(parents=True, exist_ok=True)
    mh.results_dir().mkdir(parents=True, exist_ok=True)


def _request(rid: str, text: bytes):
    (mh.requests_dir() / f"{rid}.req").write_bytes(text)


@pytest.mark.parametrize("args", [
    ["uninstall"], ["remove-all"], ["install", GUID], ["reinstall", GUID],
    ["cleanup", GUID], ["uninstall", GUID]])
def test_the_helper_runs_the_admin_steps(args):
    assert mh.allowed(args) and mh.parse(" ".join(args).encode()) == args


@pytest.mark.parametrize("raw", [
    b"remove", b"install", b"install " + GUID.encode() + b" efx",   # slot: the app never asks
    b"install C:\\evil.dll", b"install " + GUID.encode() + b" " + GUID.encode(),
    b"uninstall ..\\..", "install {é}".encode(), b"\xff\xfe", b"x" * 300, b""])
def test_anything_else_is_refused(raw):
    assert mh.parse(raw) is None


def test_serve_answers_every_request(monkeypatch):
    _queue()
    ran = []
    _request("a" * 32, f"install {GUID}".encode())
    _request("b" * 32, b"install C:\\evil.dll")
    _request("not-a-request-id", b"uninstall")
    assert mh.serve(run=lambda args: ran.append(args) or 0) == 0
    assert ran == [["install", GUID]]
    assert (mh.results_dir() / f"{'a' * 32}.res").read_text() == "0"
    assert (mh.results_dir() / f"{'b' * 32}.res").read_text() == "2"   # refused
    assert not list(mh.requests_dir().iterdir())   # all taken, the odd one too


def test_a_failing_step_still_gets_an_answer():
    _queue()
    _request("c" * 32, b"uninstall")

    def boom(args):
        raise OSError("registry went away")
    mh.serve(run=boom)
    assert (mh.results_dir() / f"{'c' * 32}.res").read_text() == "1"


def test_remove_all_takes_the_helper_away_after_answering(monkeypatch):
    _queue()
    order = []
    monkeypatch.setattr(mh.time, "sleep", lambda s: order.append("wait"))
    monkeypatch.setattr(mh, "remove_helper", lambda: order.append("removed"))
    _request("d" * 32, b"remove-all")
    _request("e" * 32, b"uninstall")
    mh.serve(run=lambda args: order.append(args) or 0)
    assert order[-3:] == [["remove-all"], "wait", "removed"]
    assert (mh.results_dir() / f"{'d' * 32}.res").read_text() == "0"


def test_ask_round_trip(monkeypatch):
    """The app leaves a request and starts the task; the task (here: serve() at once)
    answers; the app gets the code."""
    _queue()
    ran = []

    def schtasks(*args, timeout=30.0):
        assert args == ("/run", "/tn", mh.TASK)
        mh.serve(run=lambda a: ran.append(a) or 7)
        return 0
    monkeypatch.setattr(mh, "_schtasks", schtasks)
    assert mh.ask(["cleanup", GUID], wait_s=5) == 7
    assert ran == [["cleanup", GUID]]
    with pytest.raises(ValueError):
        mh.ask(["install", "C:\\evil.dll"])


def test_ask_gives_up_when_the_task_wont_start(monkeypatch):
    _queue()
    monkeypatch.setattr(mh, "_schtasks", lambda *a, **k: 1)
    assert mh.ask(["uninstall"], wait_s=5) is None
    assert not list(mh.requests_dir().iterdir())


def test_ask_gives_up_when_nobody_picks_it_up(monkeypatch):
    _queue()
    monkeypatch.setattr(mh, "_schtasks", lambda *a, **k: 0)
    monkeypatch.setattr(mh, "START_S", 0.2)
    assert mh.ask(["uninstall"], wait_s=5) is None
    assert not list(mh.requests_dir().iterdir())


def test_ready_needs_the_same_effect_dll(monkeypatch, tmp_path):
    """Only another effect DLL makes the app ask Windows: an older helper with the
    same DLL still does the job (the next prompt updates it anyway)."""
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    monkeypatch.setattr(mh, "bundled_helper", lambda: bundled)
    monkeypatch.setattr(mh, "installed", lambda: True)
    mh.helper_dir().mkdir(parents=True)
    monkeypatch.setattr(mh, "HELPER_VERSION", 5)
    monkeypatch.setattr(mh, "MIN_HELPER_VERSION", 3)
    (bundled / mh.STAMP).write_text("5 aaaa")
    assert not mh.ready() and not mh.ready(same_dll=False)   # no helper stamp
    (mh.helper_dir() / mh.STAMP).write_text("4 aaaa")
    assert mh.ready()       # older helper, same DLL
    (mh.helper_dir() / mh.STAMP).write_text("5 bbbb")
    assert not mh.ready()   # another DLL: Windows asks, and the helper is updated
    assert mh.ready(same_dll=False)   # it can still take the effect off
    (mh.helper_dir() / mh.STAMP).write_text("2 aaaa")
    assert not mh.ready() and not mh.ready(same_dll=False)   # older than the minimum
    monkeypatch.setattr(mh, "installed", lambda: False)
    (mh.helper_dir() / mh.STAMP).write_text("5 aaaa")
    assert not mh.ready()   # its task is gone


def test_ready_needs_all_of_this_apps_build(monkeypatch, tmp_path):
    """This app's own build missing a file can't start: Windows' prompt (which puts it
    back) at once, not a wait for a helper that never answers first. An older helper
    is packed its own way: not held to this build's files."""
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    monkeypatch.setattr(mh, "bundled_helper", lambda: bundled)
    monkeypatch.setattr(mh, "installed", lambda: True)
    for folder in (bundled, mh.helper_dir()):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / mh.STAMP).write_text(f"{mh.HELPER_VERSION} aaaa")
        (folder / mh.EXE_NAME).write_bytes(b"MZ")
    (bundled / "obmichelper.pkg").write_bytes(b"PKG")
    assert not mh.ready() and not mh.ready(same_dll=False)
    (mh.helper_dir() / "obmichelper.pkg").write_bytes(b"PKG")
    assert mh.ready() and mh.ready(same_dll=False)
    (mh.helper_dir() / "obmichelper.pkg").unlink()
    (mh.helper_dir() / mh.STAMP).write_text(f"{mh.HELPER_VERSION - 1} aaaa")
    assert mh.ready()   # an older helper, same DLL: as before


def test_a_request_gone_meanwhile_doesnt_stop_the_rest(monkeypatch):
    """Listed, then deleted by the app (it gave up waiting) before it was looked at."""
    _queue()
    real = mh.requests_dir()
    _request("a" * 32, f"install {GUID}".encode())
    gone = real / ("b" * 32 + ".req")

    class Listing:
        calls = 0

        def glob(self, pattern):
            Listing.calls += 1
            return [*real.glob(pattern), gone] if Listing.calls == 1 else real.glob(pattern)
    monkeypatch.setattr(mh, "requests_dir", Listing)
    ran = []
    assert mh.serve(run=lambda args: ran.append(args) or 0) == 0
    assert ran == [["install", GUID]]
    assert (mh.results_dir() / ("a" * 32 + ".res")).read_text() == "0"


def test_make_stamp(tmp_path):
    dll = tmp_path / "obmic.dll"
    dll.write_bytes(b"effect")
    assert mh.make_stamp(dll) == f"{mh.HELPER_VERSION} {hashlib.sha256(b'effect').hexdigest()}"


@pytest.mark.parametrize("args, same_dll", [
    (["install", GUID], True), (["reinstall", GUID], True),
    (["uninstall"], False), (["cleanup", GUID], False), (["remove-all"], False)])
def test_admin_steps_go_through_the_helper_when_it_can(monkeypatch, args, same_dll):
    asked, prompted = [], []
    monkeypatch.setattr(mh, "ready", lambda same_dll=True: asked.append(same_dll) or True)
    monkeypatch.setattr(mh, "ask", lambda a, wait_s=300.0: asked.append(a) or 0)
    monkeypatch.setattr(dm, "run_elevated", lambda *a, **k: prompted.append(a) or 0)
    assert REAL_ELEVATED(args) == 0
    assert asked == [same_dll, args] and not prompted


def test_without_a_helper_windows_asks(monkeypatch):
    prompted = []
    monkeypatch.setattr(mh, "ready", lambda same_dll=True: not same_dll)   # older DLL's
    monkeypatch.setattr(mh, "ask", lambda *a, **k: pytest.fail("asked an unusable helper"))
    monkeypatch.setattr(dm, "run_elevated",
                        lambda exe, params, wait_s: prompted.append(params) or 0)
    monkeypatch.setattr(mh, "_token_sid", lambda: SID)
    assert REAL_ELEVATED(["install", GUID]) == 0
    # (and who asked: a standard user typing an admin's password gets the helper too)
    assert prompted and prompted[0].endswith(f"--direct-mic install {GUID} --for {SID}")


def test_only_set_up_steps_say_who_asked(monkeypatch):
    monkeypatch.setattr(mh, "_token_sid", lambda: SID)
    assert mh.for_user(["cleanup", GUID]) == ["--for", SID]
    assert mh.for_user(["uninstall"]) == [] and mh.for_user(["remove-all"]) == []
    monkeypatch.setattr(mh, "_token_sid", lambda: "S-1-5-18")
    assert mh.for_user(["install", GUID]) == []


def test_a_helper_that_doesnt_answer_falls_back_to_windows(monkeypatch):
    prompted = []
    monkeypatch.setattr(mh, "ready", lambda same_dll=True: True)
    monkeypatch.setattr(mh, "ask", lambda *a, **k: None)
    monkeypatch.setattr(dm, "run_elevated", lambda *a, **k: prompted.append(a) or 0)
    assert REAL_ELEVATED(["uninstall"]) == 0 and prompted


def test_a_slot_choice_always_asks_windows(monkeypatch):
    """`install <guid> <slot>` (the recovery card's expert choice) isn't a helper step."""
    prompted = []
    monkeypatch.setattr(mh, "ready", lambda **k: pytest.fail("looked for the helper"))
    monkeypatch.setattr(dm, "run_elevated", lambda *a, **k: prompted.append(a) or 0)
    assert REAL_ELEVATED(["install", GUID, "efx"]) == 0 and prompted


@pytest.fixture
def admin_cli(monkeypatch):
    """dm.cli as the admin copy, with the steps themselves faked."""
    done = []
    monkeypatch.setattr(dm, "_admin_lock", lambda: object())
    monkeypatch.setattr(dm, "_release", lambda h: None)
    monkeypatch.setattr(dm, "_enable_privileges", lambda *a: None)
    monkeypatch.setattr(dm, "secure_data_dirs", lambda: None)
    monkeypatch.setattr(dm, "log_to", lambda path: None)
    monkeypatch.setattr(dm, "capture_endpoints", lambda: [{"guid": GUID, "name": "Mic",
                                                           "active": True}])
    monkeypatch.setattr(dm, "admin_install", lambda guid, slot=None: done.append("install") or 0)
    monkeypatch.setattr(dm, "admin_uninstall", lambda only=None: done.append("uninstall") or 0)
    monkeypatch.setattr(mh, "install_helper", lambda user=None: done.append(
        f"helper for {user}" if user else "helper") or True)
    monkeypatch.setattr(mh, "remove_helper", lambda: done.append("helper gone"))
    return done


def test_the_one_prompt_sets_up_the_helper(admin_cli):
    assert dm.cli(["install", GUID]) == 0
    assert admin_cli == ["install", "helper"]


def test_the_admin_copy_sets_it_up_for_whoever_asked(admin_cli):
    assert dm.cli(["install", GUID, "--for", SID2]) == 0
    assert admin_cli == ["install", f"helper for {SID2}"]


def test_the_helper_never_installs_a_helper(admin_cli, monkeypatch):
    monkeypatch.setattr(mh, "is_helper", lambda: True)
    assert dm.cli(["install", GUID]) == 0
    assert admin_cli == ["install"]


def test_taking_it_off_keeps_the_helper(admin_cli):
    assert dm.cli(["uninstall"]) == 0
    assert admin_cli == ["uninstall"]


def test_uninstalling_the_app_removes_the_helper(admin_cli, monkeypatch):
    monkeypatch.setattr(dm, "_is_admin", lambda: True)
    monkeypatch.setattr(dm, "anything_installed", lambda: False)
    monkeypatch.setattr(mh, "leftover", lambda: True)   # only (some of) the helper is left
    assert dm.cli(["remove"]) == 0
    assert admin_cli == ["uninstall", "helper gone"]


def test_nothing_left_nothing_to_remove(admin_cli, monkeypatch):
    monkeypatch.setattr(dm, "anything_installed", lambda: False)
    monkeypatch.setattr(mh, "leftover", lambda: False)
    monkeypatch.setattr(dm, "_elevated", lambda *a, **k: pytest.fail("asked for admin"))
    assert dm.cli(["remove"]) == 0 and admin_cli == []


def test_any_trace_of_a_helper_is_a_leftover(monkeypatch):
    """A half-done update's folder, or the task with its folder gone (the app folder
    deleted by hand, an older version's uninstall): the uninstaller still clears it."""
    tasks = []
    monkeypatch.setattr(mh, "_schtasks", lambda *a, **k: tasks.append(a) or 1)
    assert not mh.leftover()
    old = mh.helper_dir().with_name(mh.helper_dir().name + ".old")
    old.mkdir(parents=True)
    assert mh.leftover()
    old.rmdir()
    monkeypatch.setattr(mh, "_schtasks", lambda *a, **k: 0)   # the task alone
    assert mh.leftover()


def test_the_uninstaller_asks_the_helper_for_remove_all(monkeypatch):
    asked = []
    monkeypatch.setattr(dm, "anything_installed", lambda: True)
    monkeypatch.setattr(dm, "_is_admin", lambda: False)
    monkeypatch.setattr(dm, "_elevated", lambda args, wait_s=300.0, **k: asked.append(args) or 0)
    assert dm.cli(["remove"]) == 0 and asked == [["remove-all"]]


def test_task_xml():
    xml = mh.task_xml(Path(r"C:\Program Files\Onion Board Mic Helper\obmichelper.exe"), SID)
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    root = ET.fromstring(xml.split("\n", 1)[1])   # (the declaration says UTF-16)
    assert root.find("t:Principals/t:Principal/t:UserId", ns).text == "S-1-5-18"
    assert root.find("t:Triggers", ns) is not None and not list(root.find("t:Triggers", ns))
    sd = root.find("t:RegistrationInfo/t:SecurityDescriptor", ns).text
    assert f"(A;;GRGX;;;{SID})" in sd and sd.startswith("D:P")
    assert root.find("t:Actions/t:Exec/t:Arguments", ns).text == mh.SERVE
    assert root.find("t:Settings/t:MultipleInstancesPolicy", ns).text == "Queue"
    for bad in ("S-1-5-18", "S-1-1-0", f"{SID})(A;;FA;;;WD", "BU", "S-1-5-32-545",
                "S-1-12-1-1-2-3", f"{ENTRA}-5", "S-1-5-21-1-2", []):
        with pytest.raises(ValueError):
            mh.task_xml(Path("x.exe"), bad)


def test_work_and_school_accounts_get_a_helper_too():
    """Microsoft Entra ID accounts (S-1-12-1-...) are people too: they always got
    Windows' prompt before."""
    assert "(A;;GRGX;;;" + ENTRA + ")" in mh.task_sddl(ENTRA)
    assert mh.task_sddl([SID, ENTRA]) == (
        f"D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;GRGX;;;{SID})(A;;GRGX;;;{ENTRA})")


def test_every_account_that_set_it_up_keeps_it(monkeypatch):
    """A second account setting it up never takes it away from the first (they'd
    each get the prompt every other time). Accounts gone from the PC drop out."""
    mh.helper_dir().mkdir(parents=True)
    gone = "S-1-5-21-1111111111-2222222222-3333333333-1099"
    (mh.helper_dir() / mh.USERS).write_text(f"{SID}\n{gone}\nS-1-1-0\n{ENTRA}\n")
    monkeypatch.setattr(mh, "_has_profile", lambda sid: sid != gone)
    assert mh.helper_users(SID2) == [SID, ENTRA, SID2]
    assert mh.helper_users(SID) == [SID, ENTRA]
    sddl = mh._queue_sddl([SID, SID2])
    assert f"(A;;{dm._FOLDER_WRITE};;;{SID})(A;;{dm._FOLDER_WRITE};;;{SID2})" in sddl
    assert sddl.endswith(f"(A;OICIIO;{dm._MODIFY};;;CO)")   # each changes only its own


@pytest.fixture
def helper_setup(monkeypatch, tmp_path):
    """install_helper() with a bundled build, its folders and schtasks faked."""
    src = tmp_path / "bundled"
    src.mkdir()
    (src / mh.EXE_NAME).write_bytes(b"MZ")
    (src / mh.STAMP).write_text("5 aaaa")
    monkeypatch.setattr(mh, "bundled_helper", lambda: src)
    monkeypatch.setattr(mh, "_has_profile", lambda sid: True)
    monkeypatch.setattr(mh, "_token_sid", lambda: SID)
    monkeypatch.setattr(dm, "_secure_dir", lambda path, sddl: path.mkdir(
        parents=True, exist_ok=True))
    calls, registered = [], {}

    def schtasks(*args, timeout=30.0, out=None):
        calls.append(args[0])
        if args[0] == "/create":
            registered["xml"] = Path(args[args.index("/xml") + 1]).read_text(
                encoding="utf-16")
        elif args[0] == "/query" and out is not None:
            out.append(registered.get("readback", registered.get("xml", "")))
        return 0
    monkeypatch.setattr(mh, "_schtasks", schtasks)
    return calls, registered


def test_install_helper_keeps_the_first_user(helper_setup):
    calls, registered = helper_setup
    assert mh.install_helper()
    assert mh.install_helper(SID2)   # a second account, its own prompt
    assert (mh.helper_dir() / mh.USERS).read_text().split() == [SID, SID2]
    assert mh.task_sddl([SID, SID2]) in registered["xml"]
    assert calls.count("/create") == 2 and "/delete" not in calls


def test_install_helper_repairs_a_build_with_the_same_stamp(helper_setup, monkeypatch):
    """The stamp names the helper version and effect DLL only: a helper packed another
    way (the .pkg beside the exe) or missing a file (a virus scanner took it) has the
    same stamp, and Windows' prompt must still put this app's build in place, or every
    mic step waits for a helper that can't start and then asks again, for ever."""
    src = mh.bundled_helper()
    (src / "obmichelper.pkg").write_bytes(b"PKG")
    copies = []
    real_copytree = mh.shutil.copytree
    monkeypatch.setattr(mh.shutil, "copytree",
                        lambda a, b: copies.append(a) or real_copytree(a, b))
    dest = mh.helper_dir()
    assert mh.install_helper() and len(copies) == 1
    assert mh.install_helper() and len(copies) == 1   # the same build: left as it is
    (dest / "obmichelper.pkg").unlink()
    assert mh.install_helper() and len(copies) == 2
    assert (dest / "obmichelper.pkg").read_bytes() == b"PKG"
    (dest / mh.EXE_NAME).write_bytes(b"MZ old packing")   # same stamp, another exe
    assert mh.install_helper() and len(copies) == 3
    assert (dest / mh.EXE_NAME).read_bytes() == b"MZ"
    assert (dest / mh.USERS).read_text().split() == [SID]   # users kept through it


def test_install_helper_checks_who_asked(helper_setup, monkeypatch):
    """`--for` comes from the user's side: only a real account of this PC."""
    calls, _ = helper_setup
    assert not mh.install_helper("S-1-5-18") and not mh.install_helper("S-1-1-0")
    monkeypatch.setattr(mh, "_has_profile", lambda sid: False)
    assert not mh.install_helper(SID2)
    assert calls == []


def test_a_task_windows_registered_differently_is_removed(helper_setup):
    """Read back after registering: a task without our security descriptor (or not
    SYSTEM's, or running something else) is deleted, never left for anyone to start."""
    calls, registered = helper_setup
    registered["readback"] = "<Task/>"   # (it ignored what was asked for)
    assert not mh.install_helper()
    assert calls[-1] == "/delete"


def test_verify_task_reads_back_what_was_registered(monkeypatch):
    exe = Path(r"C:\Program Files\Onion Board Mic Helper\obmichelper.exe")
    xml = mh.task_xml(exe, [SID])
    shown: list[str] = []
    monkeypatch.setattr(mh, "_schtasks", lambda *a, out=None, **k: out.append(shown[0]) or 0)
    shown[:] = [xml]
    assert mh.verify_task(exe, [SID])
    assert not mh.verify_task(exe, [SID, SID2])   # someone's missing
    assert not mh.verify_task(Path(r"C:\evil.exe"), [SID])
    for before, after in [("S-1-5-18</UserId>", f"{SID}</UserId>"),
                          ("<Triggers />", "<Triggers><BootTrigger /></Triggers>"),
                          ("(A;;FA;;;BA)", "(A;;FA;;;BA)(A;;GA;;;WD)")]:
        shown[:] = [xml.replace(before, after)]
        assert not mh.verify_task(exe, [SID]), after
    shown[:] = ["ERROR: not xml"]
    assert not mh.verify_task(exe, [SID])


def test_a_helper_request_file_must_be_plain(tmp_path):
    _queue()
    big = mh.requests_dir() / f"{'f' * 32}.req"
    big.write_bytes(b"uninstall" + b" " * 400)
    assert mh._take(big) is None and not big.exists()


def test_a_request_with_a_second_name_is_refused():
    """A hard link: the request is someone else's file under a second name."""
    _queue()
    other = mh.requests_dir().parent / "other.txt"
    other.write_bytes(b"uninstall")
    link = mh.requests_dir() / f"{'1' * 32}.req"
    os.link(other, link)
    assert mh._take(link) is None
    assert not link.exists() and other.read_bytes() == b"uninstall"   # only our name went


def test_a_linked_request_is_refused():
    _queue()
    target = mh.requests_dir().parent / "target.txt"
    target.write_bytes(b"uninstall")
    link = mh.requests_dir() / f"{'2' * 32}.req"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("making symlinks needs Developer Mode here")
    assert mh._take(link) is None
    assert not os.path.lexists(link) and target.exists()   # the link went, never its target


def test_a_folder_named_like_a_request_is_refused():
    _queue()
    d = mh.requests_dir() / f"{'3' * 32}.req"
    d.mkdir()
    assert mh._take(d) is None


def test_a_plain_request_is_read_and_gone():
    _queue()
    req = mh.requests_dir() / f"{'4' * 32}.req"
    req.write_bytes(f"cleanup {GUID}".encode())
    assert mh._take(req) == ["cleanup", GUID] and not req.exists()


# ---------------------------------------------------------------- heartbeat

def test_the_helper_beats_while_it_works(monkeypatch):
    _queue()
    monkeypatch.setattr(mh, "BEAT_S", 0.05)
    ack = mh.results_dir() / f"{'5' * 32}.ack"
    seen = []

    def slow(args):
        first = ack.stat().st_mtime_ns
        time.sleep(0.4)
        seen.append(ack.stat().st_mtime_ns > first)   # touched while working
        return 0
    _request("5" * 32, b"uninstall")
    mh.serve(run=slow)
    assert seen == [True]
    assert not ack.exists() and (mh.results_dir() / f"{'5' * 32}.res").read_text() == "0"


def _fake_task(monkeypatch, work):
    """schtasks /run starts `work(rid)` on a thread, like the real task would."""
    def schtasks(*args, timeout=30.0, out=None):
        rid = next(mh.requests_dir().glob("*.req")).stem
        threading.Thread(target=work, args=(rid,), daemon=True).start()
        return 0
    monkeypatch.setattr(mh, "_schtasks", schtasks)


def test_a_working_helper_is_waited_for_past_the_timeout(monkeypatch):
    """While its heartbeat is fresh the app keeps waiting: Windows' prompt now would
    only find the helper holding the lock (code 4) and fail."""
    _queue()
    monkeypatch.setattr(mh, "BEAT_S", 0.05)

    def work(rid):
        mh.serve(run=lambda args: time.sleep(0.8) or 3)
    _fake_task(monkeypatch, work)
    assert mh.ask(["uninstall"], wait_s=0.2) == 3


def test_a_helper_killed_half_way_falls_back_quickly(monkeypatch):
    """It took the request, then died (its heartbeat stops): the app gives up after
    STALE_S, not the full wait, and leaves the next step to Windows' prompt."""
    _queue()
    monkeypatch.setattr(mh, "STALE_S", 0.3)

    def work(rid):   # took it, wrote the ack once, then nothing
        mh._take(mh.requests_dir() / f"{rid}.req")
        (mh.results_dir() / f"{rid}.ack").write_bytes(b"")
    _fake_task(monkeypatch, work)
    start = time.monotonic()
    assert mh.ask(["uninstall"], wait_s=60) is None
    assert time.monotonic() - start < 5


def test_a_helper_killed_before_reading_leaves_nothing_to_redo(monkeypatch):
    """Its heartbeat started, then it died with the request still there: the app
    takes the request back, so the next run never does it after Windows' prompt did."""
    _queue()
    monkeypatch.setattr(mh, "STALE_S", 0.3)
    _fake_task(monkeypatch, lambda rid: (mh.results_dir() / f"{rid}.ack").write_bytes(b""))
    assert mh.ask(["uninstall"], wait_s=60) is None
    assert not list(mh.requests_dir().iterdir())


def test_an_older_helper_without_a_heartbeat_gets_the_full_wait(monkeypatch):
    _queue()

    def work(rid):   # a v2-v3 helper: takes it, answers later, no .ack
        args = mh._take(mh.requests_dir() / f"{rid}.req")
        time.sleep(0.5)
        mh._answer(rid, 0 if args else 2)
    _fake_task(monkeypatch, work)
    assert mh.ask(["uninstall"], wait_s=5) == 0


def test_the_next_request_works_after_a_killed_one(monkeypatch):
    """A helper killed mid-job leaves its .ack behind: the next run answers the next
    request as normal (the old .ack goes with the hour-old results)."""
    _queue()
    (mh.results_dir() / f"{'6' * 32}.ack").write_bytes(b"")   # the dead one's
    _request("7" * 32, b"uninstall")
    mh.serve(run=lambda args: 0)
    assert (mh.results_dir() / f"{'7' * 32}.res").read_text() == "0"
    old = time.time() - mh.RESULT_KEEP_S - 10
    os.utime(mh.results_dir() / f"{'6' * 32}.ack", (old, old))
    mh._prune(time.time())
    assert not (mh.results_dir() / f"{'6' * 32}.ack").exists()


# ---------------------------------------------------------------- logs, UI thread

def test_admin_logs_stay_small(tmp_path, monkeypatch):
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", [])
    monkeypatch.setattr(dm, "LOG_BYTES", 2000)
    path = tmp_path / "directmic-admin.log"
    dm.log_to(path)
    try:
        for i in range(200):
            logging.getLogger("soundboard.directmic").warning("line %d %s", i, "x" * 40)
    finally:
        for h in root.handlers:
            h.close()
    assert path.stat().st_size <= 2100
    assert (tmp_path / "directmic-admin.log.1").exists()
    assert not (tmp_path / "directmic-admin.log.2").exists()   # one old copy only


def test_schtasks_on_the_ui_thread_is_flagged(qapp, monkeypatch, caplog):
    """installed() / ready() run schtasks: never on the UI thread (AGENT-RULES)."""
    monkeypatch.setattr(mh.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, b"", b""))
    with caplog.at_level(logging.WARNING, logger=mh.__name__):
        REAL_SCHTASKS("/query", "/tn", mh.TASK)
    assert "UI thread" in caplog.text
    caplog.clear()
    t = threading.Thread(target=REAL_SCHTASKS, args=("/query", "/tn", mh.TASK))
    t.start()
    t.join()
    assert "UI thread" not in caplog.text


def test_the_admin_part_runs_without_numpy():
    """The helper build leaves numpy out: the admin part (and the ring file it makes)
    must not need it."""
    code = ("import sys; sys.modules['numpy'] = None\n"
            "from soundboard import directmic as dm, michelper as mh\n"
            "assert dm.np is None and len(dm.new_ring_bytes()) == dm.FILE_BYTES\n"
            "assert mh.allowed(['uninstall'])\n")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 0, r.stderr


def test_ring_bytes_match_the_layout():
    np = pytest.importorskip("numpy")
    h = np.frombuffer(dm.new_ring_bytes(), dm.HEAD, count=1)[0]
    assert (h["magic"], h["version"], h["rate"], h["capacity"], h["mic_capacity"]) \
        == (dm.MAGIC, dm.VERSION, dm.RATE, dm.CAPACITY, dm.MIC_CAPACITY)
    assert h["mode"] == dm.MODE_REPLACE and h["gain"] == 1.0 and h["mic_gain"] == 1.0
    assert h["enabled"] == 0 and h["write_pos"] == 0


def admin_source_digest() -> str:
    src = (ROOT / "soundboard" / "directmic.py").read_text(encoding="utf-8")
    rule = "# " + "-" * 70 + " "
    start, end = src.index(rule + "admin part"), src.index(rule + "the app's side")
    helper = (ROOT / "soundboard" / "michelper.py").read_text(encoding="utf-8")
    text = (src[start:end] + helper).replace("\r\n", "\n")
    return hashlib.sha256(text.encode()).hexdigest()


def test_helper_version_follows_the_admin_code():
    """Installed helpers run the admin code they were built with. When it changes, bump
    michelper.HELPER_VERSION and put the new digest here, so the next admin step
    updates them."""
    assert ADMIN_DIGEST.get(mh.HELPER_VERSION) == admin_source_digest(), (
        f"the mic helper's admin code changed: bump michelper.HELPER_VERSION and set "
        f"ADMIN_DIGEST[{mh.HELPER_VERSION}] = {admin_source_digest()!r}")


def test_a_reinstall_makes_the_ring_folder_again(monkeypatch):
    """A reinstall's uninstall removes the data folder when no board holds the ring
    open: putting the effect back makes it again (found on a real PC, through the
    helper: the set-up failed half-way and left the mic without the effect)."""
    made = []

    def secure():
        made.append(True)
        dm.ring_path().parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(dm, "secure_data_dirs", secure)
    dm._make_ring()
    assert made and dm.make_ring_ok(dm.ring_path())
