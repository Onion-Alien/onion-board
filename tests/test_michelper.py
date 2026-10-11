"""The mic helper (soundboard/michelper.py): the admin steps of the mic effect without
Windows' prompt each time. Nothing here touches Task Scheduler or Program Files: the
conftest guard points the helper's folders into tmp_path and fails any schtasks call."""
from __future__ import annotations

import hashlib
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from soundboard import directmic as dm
from soundboard import michelper as mh

GUID = "{0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0}"
SID = "S-1-5-21-1111111111-2222222222-3333333333-1001"
REAL_ELEVATED = dm._elevated   # (the conftest guard replaces it in every test)
ROOT = Path(__file__).resolve().parent.parent

# HELPER_VERSION and the admin code it stands for: change one, change the other
ADMIN_DIGEST = {1: "954b432154c606bb4f825d983e85cefa6463062f255f69f0ecb863a4dc9558b2"}


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
    (bundled / mh.STAMP).write_text("2 aaaa")
    assert not mh.ready()   # no helper stamp
    (mh.helper_dir() / mh.STAMP).write_text("1 aaaa")
    assert mh.ready()       # older helper, same DLL
    (mh.helper_dir() / mh.STAMP).write_text("2 bbbb")
    assert not mh.ready()   # another DLL: Windows asks, and the helper is updated
    monkeypatch.setattr(mh, "installed", lambda: False)
    (mh.helper_dir() / mh.STAMP).write_text("2 aaaa")
    assert not mh.ready()   # its task is gone


def test_make_stamp(tmp_path):
    dll = tmp_path / "obmic.dll"
    dll.write_bytes(b"effect")
    assert mh.make_stamp(dll) == f"{mh.HELPER_VERSION} {hashlib.sha256(b'effect').hexdigest()}"


@pytest.mark.parametrize("args, uses", [
    (["install", GUID], "ready"), (["reinstall", GUID], "ready"),
    (["uninstall"], "installed"), (["cleanup", GUID], "installed"),
    (["remove-all"], "installed")])
def test_admin_steps_go_through_the_helper_when_it_can(monkeypatch, args, uses):
    asked, prompted = [], []
    monkeypatch.setattr(mh, "ready", lambda: uses == "ready")
    monkeypatch.setattr(mh, "installed", lambda: uses == "installed")
    monkeypatch.setattr(mh, "ask", lambda a, wait_s=300.0: asked.append(a) or 0)
    monkeypatch.setattr(dm, "run_elevated", lambda *a, **k: prompted.append(a) or 0)
    assert REAL_ELEVATED(args) == 0
    assert asked == [args] and not prompted


def test_without_a_helper_windows_asks(monkeypatch):
    prompted = []
    monkeypatch.setattr(mh, "ready", lambda: False)
    monkeypatch.setattr(mh, "installed", lambda: True)   # an older DLL's helper
    monkeypatch.setattr(mh, "ask", lambda *a, **k: pytest.fail("asked an unusable helper"))
    monkeypatch.setattr(dm, "run_elevated",
                        lambda exe, params, wait_s: prompted.append(params) or 0)
    assert REAL_ELEVATED(["install", GUID]) == 0
    assert prompted and prompted[0].endswith(f"--direct-mic install {GUID}")


def test_a_helper_that_doesnt_answer_falls_back_to_windows(monkeypatch):
    prompted = []
    monkeypatch.setattr(mh, "installed", lambda: True)
    monkeypatch.setattr(mh, "ask", lambda *a, **k: None)
    monkeypatch.setattr(dm, "run_elevated", lambda *a, **k: prompted.append(a) or 0)
    assert REAL_ELEVATED(["uninstall"]) == 0 and prompted


def test_a_slot_choice_always_asks_windows(monkeypatch):
    """`install <guid> <slot>` (the recovery card's expert choice) isn't a helper step."""
    prompted = []
    monkeypatch.setattr(mh, "ready", lambda: pytest.fail("looked for the helper"))
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
    monkeypatch.setattr(dm.logging, "basicConfig", lambda **k: None)
    monkeypatch.setattr(dm, "capture_endpoints", lambda: [{"guid": GUID, "name": "Mic",
                                                           "active": True}])
    monkeypatch.setattr(dm, "admin_install", lambda guid, slot=None: done.append("install") or 0)
    monkeypatch.setattr(dm, "admin_uninstall", lambda only=None: done.append("uninstall") or 0)
    monkeypatch.setattr(mh, "install_helper", lambda: done.append("helper") or True)
    monkeypatch.setattr(mh, "remove_helper", lambda: done.append("helper gone"))
    return done


def test_the_one_prompt_sets_up_the_helper(admin_cli):
    assert dm.cli(["install", GUID]) == 0
    assert admin_cli == ["install", "helper"]


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
    monkeypatch.setattr(mh, "installed", lambda: True)   # only the helper is left
    assert dm.cli(["remove"]) == 0
    assert admin_cli == ["uninstall", "helper gone"]


def test_the_uninstaller_asks_the_helper_for_remove_all(monkeypatch):
    asked = []
    monkeypatch.setattr(dm, "anything_installed", lambda: True)
    monkeypatch.setattr(dm, "_is_admin", lambda: False)
    monkeypatch.setattr(dm, "_elevated", lambda args, wait_s=300.0: asked.append(args) or 0)
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
    for bad in ("S-1-5-18", "S-1-1-0", f"{SID})(A;;FA;;;WD", "BU"):
        with pytest.raises(ValueError):
            mh.task_xml(Path("x.exe"), bad)


def test_a_helper_request_file_must_be_plain(tmp_path):
    _queue()
    big = mh.requests_dir() / f"{'f' * 32}.req"
    big.write_bytes(b"uninstall" + b" " * 400)
    assert mh._take(big) is None and not big.exists()


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
