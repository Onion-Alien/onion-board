"""The mic helper (soundboard/mic/michelper.py): the admin steps of the mic effect without
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

from soundboard.mic import directmic as dm
from soundboard.mic import michelper as mh

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
                6: "9b83750c3d3586a89804c5ec5c97618fc1ce30b511723e4e3cf3525513c9a534",
                7: "562d4f9cdb4cd0a53071284bf83aef9bbf8b2563c5ba7a3368dc190942d22c66",
                8: "2e6e7bce58fff25b999c3779c61576bc676a39765c974e83b62ad437f5a15a2d",
                9: "f60c119dabaad07489532ae0fbb58b600cc3ac6f864f4b52622a5a95476a8894",
               10: "e9d84913fb40a44975302aed80f4875feeb7ae9626065a410678e62a3f3b4383",
               11: "eeedff2b4f38cd99b8f919dd3f60f120d0977ab0be28055f52330e587103119b",
               12: "3b389974f12790f2d46748bd7ce4b2574784de39c3e5e8b326d4df433a948f67",
               13: "2b9a8b2aa795c38c77edac07e71c306a9011b81e2df7e37c9137d5699167b47c",
               14: "d4c592e4156e26c16ab50fa4674833da0e125264091e8ac31bc52c69abec9c3b",
               15: "ea2dc4a0f029bf08234ab38dbcd610cff162e69fa15c42aabdb293dc3f368abd",
               # 16 again when the modules moved into soundboard/mic/ and audio/: only
               # import paths and comments changed, so installed helpers needn't update
               # (no UAC prompt)
               16: "a88bc311c59231f8598a2af1f7bfa639e3221e6a1d24f67ad4f319e558dbc675",
               17: "f493b9f566da540a98e44f595f0ccd60c26dc71570206c58d0b2262e34ce2234",
               18: "18c5bd83e7a504aa96ba2995292b386647013d1ae464ac612947c9bc7b141fb9",
               19: "ef4ee762319ea5dad59381fa26471f23cdc4cf60cdd1031227b08d5806bed559",
               20: "e7b210a56344ec4b5420e6b7ddc1fca9d93eec6640657f4b0bf235a87cc0ad1e",
               21: "fc1d64c720b1acf922be82d6812192cb81f939a15593cd58487237cc5b718c47",
               22: "fded1edfd0a79368a14c8b46b8319db148aeebc4a2372a470c26d80ac5b426e6",
               23: "bd64dfb3ce017760cfd4859b8d74a840465736c52a5793b58a949f6b11f5c520",
               24: "5924cdd998ab33b703a2abcd8338a11b1503d2945c6f56a5bb7fc5a98ce539e3",
               25: "61009c7366fe22f4e795fd16de72c85e19e8bf26c9b554c9d929aecfc4ca61aa",
               26: "819ed89c03f11cb9c066b3a9529062e67e55cf96228875ce8364cbf1cac04181",
               27: "227b9e0bb915510ae86c33c5ab34ac6b4fd30df207998b3c26748c55743a5a09",
               28: "b4dfd79b8e41fc286dc4b56debd3888a55feb95f8d28265b9947608d6465198f",
               # 29 again when directmic.py was split and its admin part became
               # micadmin.py: the code was only moved, so installed helpers needn't update
               29: "efce7b0d8d513100903f17e229d74e37eede59d62a9a6ac7867dcd751f7fe90a",
               30: "acebab9e7257e67c5c98260264c3c5a28d5b9b7cfaa648cbc18e736c4bae25a4",
               31: "833eac929852c4838d3869ec238e99f23dc2067746815520de7839ed51e54b85",
               32: "5fe573c21a645bad90ed641ff87d1686174da445c20b2e5c1179210457ddd33d",
               33: "764a71a6d5c4dc9e6c69afdf4287b2a18e1bf85580d918d223d57b91dc103c61",
               34: "ee19b11a3aa9e4975834a8e67181997441592b476a6d5681d7c235dc2b0c2fd4"}


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
    mh.write_manifest(bundled)
    assert not mh.ready() and not mh.ready(same_dll=False)
    (mh.helper_dir() / "obmichelper.pkg").write_bytes(b"PKG")
    mh.write_manifest(mh.helper_dir())
    assert mh.ready() and mh.ready(same_dll=False)
    (mh.helper_dir() / "obmichelper.pkg").unlink()
    monkeypatch.setattr(mh, "MIN_HELPER_VERSION", 2)   # (while old ones are allowed)
    (mh.helper_dir() / mh.STAMP).write_text(f"{mh.MANIFEST_SINCE - 1} aaaa")
    assert mh.ready()   # an older helper (no manifest yet), same DLL: as before


def test_a_request_gone_meanwhile_doesnt_stop_the_rest(monkeypatch):
    """Listed, then deleted by the app (it gave up waiting) before it was looked at."""
    _queue()
    real = mh.requests_dir()
    _request("a" * 32, f"install {GUID}".encode())
    gone = real / ("b" * 32 + ".req")
    listed, calls = mh._requests, []

    def listing():
        calls.append(1)
        return [*listed(), gone] if len(calls) == 1 else listed()
    monkeypatch.setattr(mh, "_requests", listing)
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
    monkeypatch.setattr(mh, "ready",
                        lambda same_dll=True, via="": asked.append((same_dll, via)) or True)
    monkeypatch.setattr(mh, "ask", lambda a, wait_s=300.0: asked.append(a) or 0)
    monkeypatch.setattr(dm, "run_elevated", lambda *a, **k: prompted.append(a) or 0)
    assert REAL_ELEVATED(args) == 0
    assert asked == [(same_dll, "before a step"), args, (True, "after a step")]
    assert not prompted


def test_without_a_helper_windows_asks(monkeypatch):
    prompted = []
    monkeypatch.setattr(mh, "ready", lambda same_dll=True, via="": not same_dll)   # older DLL's
    monkeypatch.setattr(mh, "ask", lambda *a, **k: pytest.fail("asked an unusable helper"))
    monkeypatch.setattr(dm, "run_elevated",
                        lambda exe, params, wait_s, **k: prompted.append(params) or 0)
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
    monkeypatch.setattr(mh, "ready", lambda same_dll=True, via="": True)
    monkeypatch.setattr(mh, "ask", lambda *a, **k: None)
    monkeypatch.setattr(dm, "run_elevated", lambda *a, **k: prompted.append(a) or 0)
    assert REAL_ELEVATED(["uninstall"]) == 0 and prompted


def test_a_slot_choice_always_asks_windows(monkeypatch):
    """`install <guid> <slot>` (the recovery card's expert choice) isn't a helper step."""
    prompted = []
    monkeypatch.setattr(mh, "ready", lambda via="", **k: via == "after a step"
                        or pytest.fail("looked for the helper first"))
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


def test_a_set_up_left_with_a_silent_mic_still_sets_up_the_helper(admin_cli, monkeypatch):
    """The effect went on (only the mic came back silent): the helper is set up as
    after any set-up, and the app hears MIC_SILENT."""
    monkeypatch.setattr(dm, "admin_install",
                        lambda guid, slot=None: admin_cli.append("install") or dm.MIC_SILENT)
    assert dm.cli(["install", GUID]) == dm.MIC_SILENT
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


# ------------------------------------------------- switched off in Settings

def test_the_helper_is_on_by_default_and_old_settings_keep_it():
    from soundboard.sounds.config import Config
    assert Config().mic_helper is True
    assert Config.from_raw({}).mic_helper is True   # settings from before the switch
    assert Config.from_raw({"mic_helper": False}).mic_helper is False


def test_switched_off_every_step_asks_windows_and_sets_up_no_helper(monkeypatch):
    prompted = []
    monkeypatch.setattr(mh, "ready", lambda *a, **k: pytest.fail("looked for the helper"))
    monkeypatch.setattr(mh, "ask", lambda *a, **k: pytest.fail("used the helper"))
    monkeypatch.setattr(dm, "run_elevated",
                        lambda exe, params, wait_s, **k: prompted.append(params) or 0)
    monkeypatch.setattr(mh, "_token_sid", lambda: SID)
    dm.set_helper(False)
    assert REAL_ELEVATED(["install", GUID]) == 0
    assert prompted[0].endswith(f"--direct-mic install {GUID} --no-helper")
    assert mh.will_ask() and mh.will_ask(False)   # the texts say Windows asks
    assert dm.helper_note() == ""


def test_the_admin_copy_sets_up_no_helper_when_told(admin_cli):
    assert dm.cli(["install", GUID, "--no-helper"]) == 0
    assert admin_cli == ["install"]


def test_switched_on_again_the_next_prompt_puts_it_back(monkeypatch, admin_cli):
    prompted = []
    monkeypatch.setattr(mh, "ready", lambda same_dll=True, via="": False)
    monkeypatch.setattr(dm, "run_elevated",
                        lambda exe, params, wait_s, **k: prompted.append(params) or 0)
    monkeypatch.setattr(mh, "_token_sid", lambda: SID)
    dm.set_helper(False)
    dm.set_helper(True)
    assert REAL_ELEVATED(["install", GUID]) == 0
    assert prompted[0].endswith(f"--direct-mic install {GUID} --for {SID}")
    assert dm.cli(["install", GUID, "--for", SID]) == 0
    assert admin_cli == ["install", f"helper for {SID}"]
    assert "Settings > Audio" in dm.helper_note()


def test_removing_the_helper_asks_windows_never_the_helper(monkeypatch):
    prompted = []
    monkeypatch.setattr(dm, "_elevated", REAL_ELEVATED)
    monkeypatch.setattr(mh, "ready", lambda same_dll=True, via="": True)
    monkeypatch.setattr(mh, "ask", lambda *a, **k: pytest.fail("the helper removed itself"))
    monkeypatch.setattr(dm, "run_elevated",
                        lambda exe, params, wait_s, **k: prompted.append(params) or 0)
    assert dm.remove_helper() == 0
    assert prompted[0].endswith("--direct-mic remove-helper")


def test_the_admin_copy_removes_only_the_helper(admin_cli):
    assert dm.cli(["remove-helper"]) == 0
    assert admin_cli == ["helper gone"]


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
    mh.write_manifest(src)
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
    mh.write_manifest(src)
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


def test_install_helper_never_raises(helper_setup, monkeypatch):
    """It runs after the effect went on: a check that raises (a file of the build held
    open, say) is a False, never the set-up's exit code 1."""
    calls, _ = helper_setup
    monkeypatch.setattr(mh, "verify_build", lambda src: (_ for _ in ()).throw(
        PermissionError(13, "denied")))
    assert mh.install_helper() is False
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


@pytest.mark.windows   # Windows' junctions
def test_a_requests_folder_turned_into_a_link_is_never_looked_into(monkeypatch, tmp_path):
    """The accounts the helper is set up for may write in requests, so they can make the
    empty folder a junction to a folder of their own (or to \\RPC Control): SYSTEM then
    deleted whatever the names in there pointed at. The link goes, nothing behind it is
    read or deleted, and the folder is made again."""
    import _winapi
    _queue()
    theirs = tmp_path / "theirs"
    theirs.mkdir()
    (theirs / f"{'5' * 32}.req").write_bytes(b"uninstall")
    (theirs / "victim.txt").write_text("keep")
    mh.requests_dir().rmdir()
    _winapi.CreateJunction(str(theirs), str(mh.requests_dir()))
    secured = []

    def secure(path, sddl):
        secured.append(path)
        os.rmdir(path)   # (the link itself)
        path.mkdir()
    monkeypatch.setattr(dm, "_secure_dir", secure)
    monkeypatch.setattr(mh, "helper_users", lambda: [SID])
    ran = []
    assert mh.serve(run=lambda args: ran.append(args) or 0) == 0
    assert ran == [] and secured == [mh.requests_dir()]
    assert sorted(p.name for p in theirs.iterdir()) == [f"{'5' * 32}.req", "victim.txt"]
    assert not dm._is_link(mh.requests_dir())


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


def test_a_request_queued_behind_a_long_one_is_waited_for(monkeypatch):
    """Two requests at once (another account's, or one the helper is still on): the
    helper does them in turn. The second must not give up at START_S while the
    first is being worked on (then Windows' prompt found the helper holding the
    lock: code 4)."""
    _queue()
    monkeypatch.setattr(mh, "START_S", 0.3)
    monkeypatch.setattr(mh, "BEAT_S", 0.05)
    started = threading.Event()

    def schtasks(*args, timeout=30.0, out=None):
        if not started.is_set():   # one task run: it finds both (the second one later)
            started.set()
            threading.Thread(target=lambda: mh.serve(run=lambda a: time.sleep(0.8) or 0),
                             daemon=True).start()
        return 0
    monkeypatch.setattr(mh, "_schtasks", schtasks)
    out = {}
    t = threading.Thread(target=lambda: out.__setitem__("a", mh.ask(["uninstall"], wait_s=5)))
    t.start()
    time.sleep(0.2)   # the helper has taken the first
    out["b"] = mh.ask(["cleanup", GUID], wait_s=5)
    t.join()
    assert out == {"a": 0, "b": 0}


def test_a_stale_heartbeat_of_another_request_doesnt_hold_ours(monkeypatch):
    """A helper killed on someone else's request left its .ack: ours still gives up
    at START_S (nobody is at work), never waits the task's whole time limit."""
    _queue()
    monkeypatch.setattr(mh, "_schtasks", lambda *a, **k: 0)
    monkeypatch.setattr(mh, "START_S", 0.2)
    dead = mh.results_dir() / f"{'8' * 32}.ack"
    dead.write_bytes(b"")
    old = time.time() - mh.STALE_S - 10
    os.utime(dead, (old, old))
    start = time.monotonic()
    assert mh.ask(["uninstall"], wait_s=5) is None
    assert time.monotonic() - start < 3


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
    mh._prune(time.time(), mono=time.monotonic() + mh.RESULT_KEEP_S + 10)
    assert not (mh.results_dir() / f"{'6' * 32}.ack").exists()


def test_a_clock_put_forward_never_prunes_a_fresh_answer(monkeypatch):
    """The wall clock jumps an hour and more forward between the helper's answer and
    the app reading it, and another run starts meanwhile: the answer is still there."""
    _queue()
    _request("8" * 32, b"uninstall")
    mh.serve(run=lambda args: 0)
    res = mh.results_dir() / f"{'8' * 32}.res"
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 2 * mh.RESULT_KEEP_S)
    mh.serve(run=lambda args: 0)   # (a run with nothing to do: it only prunes)
    mh._prune(time.time())
    assert mh._result(res) == 0


def test_old_results_from_an_earlier_run_are_pruned():
    _queue()
    old = mh.results_dir() / f"{'9' * 32}.res"
    old.write_text("0")
    t = time.time() - mh.RESULT_KEEP_S - 10
    os.utime(old, (t, t))
    mono = time.monotonic()
    mh._prune(time.time(), mono=mono)   # first seen now: kept, however old it looks
    assert old.exists()
    mh._prune(time.time(), mono=mono + mh.RESULT_KEEP_S + 10)
    assert not old.exists()
    gone = mh.results_dir() / f"{'a' * 32}.ack"   # seen before a restart
    gone.write_bytes(b"")
    os.utime(gone, (t, t))
    mh._prune(time.time(), mono=mono)
    mh._prune(time.time(), mono=1.0)
    assert not gone.exists()


# ---------------------------------------------------------------- logs, UI thread

def test_admin_logs_stay_small(tmp_path, monkeypatch):
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", [])
    monkeypatch.setattr(dm, "LOG_BYTES", 2000)
    path = tmp_path / "directmic-admin.log"
    dm.log_to(path)
    try:
        for i in range(200):
            logging.getLogger("soundboard.mic.directmic").warning("line %d %s", i, "x" * 40)
    finally:
        for h in root.handlers:
            h.close()
    assert path.stat().st_size <= 2100
    assert (tmp_path / "directmic-admin.log.1").exists()
    assert not (tmp_path / "directmic-admin.log.2").exists()   # one old copy only


def test_schtasks_on_the_ui_thread_is_flagged(qapp, monkeypatch, caplog):
    """installed() / ready() run schtasks: never on the UI thread."""
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
    must not need it, nor the listen-to-the-mic check after the audio restart (in the
    helper that failed with "No module named 'numpy'", so a mic left silent was never
    restarted again)."""
    code = ("import sys; sys.modules['numpy'] = None\n"
            "from soundboard.mic import directmic as dm, michelper as mh\n"
            "assert dm.np is None and len(dm.new_ring_bytes()) == dm.FILE_BYTES\n"
            "assert mh.allowed(['uninstall'])\n"
            "from soundboard.audio import appaudio\n"
            "assert appaudio.np is None and callable(appaudio.mic_is_silent)\n")
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
    admin = (ROOT / "soundboard" / "mic" / "micadmin.py").read_text(encoding="utf-8")
    helper = (ROOT / "soundboard" / "mic" / "michelper.py").read_text(encoding="utf-8")
    safe = (ROOT / "soundboard" / "mic" / "safefs.py").read_text(encoding="utf-8")
    text = (admin + helper + safe).replace("\r\n", "\n")
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


# ---------------------------------------------------------------- sleep, clock jumps

def _jump_monotonic(monkeypatch, by: float, after: int = 5):
    """time.monotonic() jumps `by` seconds once, after `after` calls: the PC slept."""
    real, calls = time.monotonic, [0]

    def mono():
        calls[0] += 1
        return real() + (by if calls[0] > after else 0.0)
    monkeypatch.setattr(mh.time, "monotonic", mono)


def _shift_clock(monkeypatch, by: float):
    real = time.time
    monkeypatch.setattr(mh.time, "time", lambda: real() + by)


def _beating_helper(monkeypatch, seconds: float = 0.8, code: int = 3):
    monkeypatch.setattr(mh, "BEAT_S", 0.05)
    monkeypatch.setattr(mh, "STALE_S", 0.3)
    _fake_task(monkeypatch, lambda rid: mh.serve(run=lambda a: time.sleep(seconds) or code))


def test_a_clock_correction_mid_step_doesnt_look_like_a_dead_helper(monkeypatch):
    """The clock jumps an hour ahead while the helper works: its heartbeat looks an
    hour old by the wall clock, but it is still beating, so the app keeps waiting
    (asking Windows now would find the helper holding the lock: code 4)."""
    _queue()
    _beating_helper(monkeypatch)
    _shift_clock(monkeypatch, 3600)
    assert mh.ask(["uninstall"], wait_s=60) == 3


def test_a_sleep_mid_step_doesnt_look_like_a_dead_helper(monkeypatch):
    """The laptop sleeps half-way (the app's clock jumps past the task's time limit and
    the wall clock with it): the time asleep doesn't count, the helper goes on."""
    _queue()
    _beating_helper(monkeypatch)
    _jump_monotonic(monkeypatch, mh.HARD_S + 100)
    _shift_clock(monkeypatch, mh.HARD_S + 100)
    assert mh.ask(["uninstall"], wait_s=60) == 3


def test_a_dead_helper_is_noticed_after_the_clock_went_back(monkeypatch):
    """A helper died half-way and the clock was set back: its .ack looks brand new by
    the wall clock for an hour. It never changes, so the app still gives up at STALE_S."""
    _queue()
    monkeypatch.setattr(mh, "STALE_S", 0.3)
    _shift_clock(monkeypatch, -3600)

    def work(rid):
        mh._take(mh.requests_dir() / f"{rid}.req")
        (mh.results_dir() / f"{rid}.ack").write_bytes(b"")
    _fake_task(monkeypatch, work)
    start = time.monotonic()
    assert mh.ask(["uninstall"], wait_s=60) is None
    assert time.monotonic() - start < 5


def test_a_dead_heartbeat_of_another_request_that_looks_new_doesnt_hold_ours(monkeypatch):
    """Another request's .ack left by a dead helper, dated now (or later, after a clock
    correction): it never changes, so ours still gives up at START_S."""
    _queue()
    monkeypatch.setattr(mh, "_schtasks", lambda *a, **k: 0)
    monkeypatch.setattr(mh, "START_S", 0.2)
    dead = mh.results_dir() / f"{'8' * 32}.ack"
    dead.write_bytes(b"")
    later = time.time() + 3600
    os.utime(dead, (later, later))
    start = time.monotonic()
    assert mh.ask(["uninstall"], wait_s=5) is None
    assert time.monotonic() - start < 3


def test_the_heartbeat_says_something_new_each_beat(monkeypatch):
    """A new helper writes a count into its .ack (what a new app watches) and the write
    moves its time too (what an app of version 7 or older watches)."""
    _queue()
    monkeypatch.setattr(mh, "BEAT_S", 0.05)
    ack = mh.results_dir() / f"{'9' * 32}.ack"
    seen = []

    def slow(args):
        for _ in range(4):
            seen.append((ack.read_bytes(), ack.stat().st_mtime_ns))
            time.sleep(0.15)
        return 0
    _request("9" * 32, b"uninstall")
    mh.serve(run=slow)
    texts, times = [s[0] for s in seen], [s[1] for s in seen]
    assert all(texts) and len(set(texts)) == len(texts)
    assert times == sorted(times) and len(set(times)) > 1


def test_a_new_app_still_watches_an_older_helper_that_only_touches(monkeypatch):
    """A helper of version 5 to 7 only touches an empty .ack: the app sees the time
    move and keeps waiting past STALE_S until it answers."""
    _queue()
    monkeypatch.setattr(mh, "STALE_S", 0.3)

    def work(rid):
        args = mh._take(mh.requests_dir() / f"{rid}.req")
        ack = mh.results_dir() / f"{rid}.ack"
        ack.write_bytes(b"")
        for _ in range(16):
            time.sleep(0.05)
            os.utime(ack)
        mh._answer(rid, 0 if args else 2)
        ack.unlink()
    _fake_task(monkeypatch, work)
    assert mh.ask(["uninstall"], wait_s=60) == 0


# ---------------------------------------------------------------- what the UI knows

def test_ready_refreshes_both_answers_at_once(monkeypatch):
    """A step that only needed one answer (taking the effect off) refreshes the other
    too, with one Task Scheduler look: the set-up text never keeps an old answer."""
    looks = []
    monkeypatch.setattr(mh, "state", mh.HelperState())
    monkeypatch.setattr(mh, "MIN_HELPER_VERSION", 2)   # (an old one, without a manifest)
    monkeypatch.setattr(mh, "_read_stamp", lambda folder: "8 aaaa")
    monkeypatch.setattr(mh, "_build_files", lambda folder: {})
    monkeypatch.setattr(mh, "installed", lambda: looks.append(1) or True)
    assert mh.known(True) is None and mh.checked_ago() is None
    assert mh.ready(same_dll=False, via="step") is True
    assert looks == [1]
    assert mh.known(True) is True and mh.known(False) is True and not mh.will_ask()
    assert mh.state.via == "step" and mh.checked_ago() < 5
    monkeypatch.setattr(mh, "installed", lambda: False)   # removed meanwhile
    mh.ready(same_dll=False)
    assert mh.known(True) is False and mh.will_ask() and mh.will_ask(False)


def test_a_stale_answer_is_noticed(monkeypatch):
    monkeypatch.setattr(mh, "state", mh.HelperState({True: True, False: True}, "test"))
    assert mh.checked_ago() < 5
    monkeypatch.setattr(mh.state, "when", time.monotonic() - mh.RECHECK_S - 1)
    assert mh.checked_ago() > mh.RECHECK_S
    mh.state.forget()
    assert mh.known() is None and mh.checked_ago() is None and mh.will_ask()


@pytest.mark.parametrize("helper", [True, False])
def test_every_admin_step_checks_the_helper_again(monkeypatch, helper):
    """Through the helper or Windows' prompt (which may have set it up, or not), the
    answers the UI reads are checked again after the step, both of them."""
    checks = []
    monkeypatch.setattr(dm, "_elevated", REAL_ELEVATED)
    monkeypatch.setattr(dm, "_via_helper", lambda args, wait_s: 0 if helper else None)
    monkeypatch.setattr(dm, "run_elevated", lambda *a, **k: 0)
    monkeypatch.setattr(mh, "ready", lambda same_dll=True, via="": checks.append(via) or True)
    assert dm._elevated(["install", GUID, "efx"]) == 0   # (a slot choice sets it up too)
    assert checks == ["after a step"]


# ---------------------------------------------------------------- the build's manifest

def test_a_build_matches_its_manifest(tmp_path):
    (tmp_path / mh.EXE_NAME).write_bytes(b"MZ")
    (tmp_path / mh.STAMP).write_text(f"{mh.HELPER_VERSION} aaaa")
    (tmp_path / "_internal").mkdir()
    (tmp_path / "_internal" / "python313.dll").write_bytes(b"py")
    mh.write_manifest(tmp_path)
    assert mh.verify_build(tmp_path)
    (tmp_path / mh.USERS).write_text(SID)   # what install_helper adds: not the build's
    assert mh.verify_build(tmp_path)
    (tmp_path / "_internal" / "extra.dll").write_bytes(b"?")
    assert not mh.verify_build(tmp_path)    # a file the build never had
    (tmp_path / "_internal" / "extra.dll").unlink()
    (tmp_path / mh.EXE_NAME).write_bytes(b"MZ evil")
    assert not mh.verify_build(tmp_path)    # changed
    (tmp_path / mh.MANIFEST).unlink()
    assert not mh.verify_build(tmp_path) and mh.verify_build(tmp_path, required=False)


def test_a_tampered_bundled_build_is_refused(helper_setup, caplog):
    """The admin copy installs the helper from the app's own folder: a build whose files
    don't match its manifest is never put in Program Files to run as SYSTEM. The mic
    step itself still worked (through Windows' prompt)."""
    calls, _registered = helper_setup
    (mh.bundled_helper() / mh.EXE_NAME).write_bytes(b"MZ evil")
    with caplog.at_level(logging.WARNING, logger="soundboard.mic.michelper"):
        assert not mh.install_helper()
    assert "manifest" in caplog.text
    assert not (mh.helper_dir() / mh.EXE_NAME).exists() and "/create" not in calls


def test_an_untouched_build_installs_with_its_manifest(helper_setup):
    assert mh.install_helper()
    assert mh.verify_build(mh.helper_dir())


def test_a_tampered_installed_helper_is_replaced_on_the_next_prompt(helper_setup,
                                                                    monkeypatch):
    """ready() fails fast on an installed helper that doesn't match its manifest (no
    request left for it), so Windows' prompt comes up, and its step puts this app's
    build back."""
    src = mh.bundled_helper()
    (src / mh.STAMP).write_text(f"{mh.HELPER_VERSION} aaaa")
    mh.write_manifest(src)
    assert mh.install_helper()
    monkeypatch.setattr(mh, "installed", lambda: True)
    assert mh.ready()
    (mh.helper_dir() / mh.EXE_NAME).write_bytes(b"MZ evil")
    assert not mh.ready() and not mh.ready(same_dll=False)
    assert mh.install_helper()
    assert (mh.helper_dir() / mh.EXE_NAME).read_bytes() == b"MZ" and mh.ready()


def test_an_older_helper_without_a_manifest_is_still_used(helper_setup, monkeypatch):
    """Helpers from before the manifest (version 9 and older) have none: still fine
    (while MIN_HELPER_VERSION allows them)."""
    monkeypatch.setattr(mh, "MIN_HELPER_VERSION", 2)
    monkeypatch.setattr(mh, "installed", lambda: True)
    dest = mh.helper_dir()
    dest.mkdir(parents=True)
    (dest / mh.EXE_NAME).write_bytes(b"MZ")
    (dest / mh.STAMP).write_text("9 aaaa")
    (mh.bundled_helper() / mh.STAMP).write_text(f"{mh.HELPER_VERSION} aaaa")
    assert mh.ready()


def test_a_helper_older_than_the_minimum_is_not_used(helper_setup, monkeypatch):
    """Helpers before MIN_HELPER_VERSION restart all of Windows' audio for a set-up
    (it cut off the apps in between a mic and a voice chat): the app asks Windows once
    more instead, and that puts this version's helper in place."""
    monkeypatch.setattr(mh, "installed", lambda: True)
    dest = mh.helper_dir()
    dest.mkdir(parents=True)
    (dest / mh.EXE_NAME).write_bytes(b"MZ")
    (dest / mh.STAMP).write_text(f"{mh.MIN_HELPER_VERSION - 1} aaaa")
    (mh.bundled_helper() / mh.STAMP).write_text(f"{mh.HELPER_VERSION} aaaa")
    assert not mh.ready() and not mh.ready(same_dll=False)


# ---------------------------------------------------------------- measured waits

def _task_status(monkeypatch, status: str | None, take_after: float | None = None):
    """schtasks: /run starts nothing at once; /query /v says `status` (None: fails).
    `take_after`: the helper picks the request up (and answers 0) that late."""
    def schtasks(*args, timeout=30.0, out=None):
        if args[0] == "/run":
            if take_after is not None:
                def late():
                    time.sleep(take_after)
                    mh.serve(run=lambda a: 0)
                threading.Thread(target=late, daemon=True).start()
            return 0
        if args[0] == "/query" and "/v" in args:
            if status is None:
                return 1
            if out is not None:
                out.append(f"HostName: PC\r\nTaskName: {mh.TASK}\r\nStatus: {status}\r\n"
                           "Last Result: 0\r\n")
            return 0
        return 0
    monkeypatch.setattr(mh, "_schtasks", schtasks)


@pytest.mark.parametrize("status", ["Running", "Queued"])
def test_a_task_scheduler_says_is_starting_is_waited_for(monkeypatch, status):
    """A slow PC (or a busy Task Scheduler) starts the task late: past START_S, but it
    says the task is running or queued, so the app keeps waiting for it."""
    _queue()
    monkeypatch.setattr(mh, "START_S", 0.2)
    monkeypatch.setattr(mh, "STATUS_EVERY_S", 0.05)
    _task_status(monkeypatch, status, take_after=0.8)
    assert mh.ask(["uninstall"], wait_s=5) == 0


@pytest.mark.parametrize("status", ["Ready", "Disabled", "Bereit", None])
def test_a_task_that_isnt_running_is_given_up_on_at_start_s(monkeypatch, status):
    """Not running at all (or a status it can't read: another language, schtasks
    failed): Windows' prompt after START_S, as before."""
    _queue()
    monkeypatch.setattr(mh, "START_S", 0.2)
    monkeypatch.setattr(mh, "STATUS_EVERY_S", 0.05)
    _task_status(monkeypatch, status)
    start = time.monotonic()
    assert mh.ask(["uninstall"], wait_s=5) is None
    assert time.monotonic() - start < 3
    assert not list(mh.requests_dir().iterdir())


@pytest.mark.parametrize("text, want", [
    ("Status: Running\r\nLast Result: 267009", True),
    ("Status:                               Queued", True),
    ("Statut : En cours\r\nDernier résultat : 267009", True),   # the running code, any language
    ("Status: Ready\r\nLast Result: 0", False),
    ("Statut : Prêt\r\nDernier résultat : 0", False),
    ("", False)])
def test_task_running_reads_schtasks(text, want):
    assert mh.task_running_in(text) is want


def test_the_prompt_wait_stops_once_silent(tmp_path):
    """An admin step that does nothing (its prompt left open, no log written): given
    up at wait_s, as before."""
    start = time.monotonic()
    assert not dm.wait_for(lambda s: time.sleep(s) or False, 0.3, tmp_path / "admin.log",
                           cap_s=10, poll_s=0.05)
    assert 0.25 < time.monotonic() - start < 2


def test_the_prompt_wait_goes_on_while_the_log_grows(tmp_path):
    """A slow PC: the admin step is still writing its log past wait_s, so it isn't
    stuck: waited for until it finishes."""
    logf = tmp_path / "admin.log"
    end = time.monotonic() + 1.0

    def grow():
        while time.monotonic() < end:
            with open(logf, "a") as f:
                f.write("step\n")
            time.sleep(0.05)
    threading.Thread(target=grow, daemon=True).start()
    assert dm.wait_for(lambda s: time.sleep(s) or time.monotonic() > end + 0.1, 0.3, logf,
                       cap_s=10, poll_s=0.05)


def test_the_prompt_wait_has_a_hard_cap(tmp_path):
    logf = tmp_path / "admin.log"
    stop = threading.Event()

    def grow():
        while not stop.is_set():
            with open(logf, "a") as f:
                f.write("again\n")
            time.sleep(0.03)
    threading.Thread(target=grow, daemon=True).start()
    start = time.monotonic()
    try:
        assert not dm.wait_for(lambda s: time.sleep(s) or False, 0.2, logf, cap_s=0.6,
                               poll_s=0.05)
    finally:
        stop.set()
    assert time.monotonic() - start < 2


@pytest.mark.windows   # Windows' sharing rules
def test_a_request_still_being_written_is_waited_for_not_refused():
    """The helper can list a request while the app is still writing it (open): it was
    refused then. It's waited for, and read once the app has closed it."""
    _queue()
    req = mh.requests_dir() / f"{'6' * 32}.req"
    f = open(req, "wb")
    f.write(b"cleanup ")
    threading.Timer(0.3, lambda: (f.write(GUID.encode()), f.close())).start()
    assert mh._take(req) == ["cleanup", GUID] and not req.exists()
