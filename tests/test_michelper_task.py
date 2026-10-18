"""The mic helper for real: a SYSTEM scheduled task, started on demand, answering the
app's requests through the real queue folders and their access rules. The admin step
it runs is faked (no mic is touched): what's tested is the task, the queue and ask().

CI only: Windows runners are admin and throwaway. It registers a task, so it never
runs on a developer's PC (test_michelper.py covers the same logic without Windows)."""
from __future__ import annotations

import ctypes
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from soundboard.mic import directmic as dm
from soundboard.mic import michelper as mh

REAL_SCHTASKS = mh._schtasks   # (the conftest guard replaces it in every test)
ROOT = Path(__file__).resolve().parent.parent
GUID = "{0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0}"

pytestmark = pytest.mark.skipif(
    os.name != "nt" or not os.environ.get("CI") or not ctypes.windll.shell32.IsUserAnAdmin(),
    reason="registers a real SYSTEM task: CI's Windows runners only")

# the task's program: the helper's serve() with a fake admin step, on this queue
SERVE = """\
import sys, time
from pathlib import Path
sys.path.insert(0, {root!r})
from soundboard.mic import michelper as mh
queue = Path(sys.argv[1])
mh.queue_dir = lambda: queue

def run(args):
    if args[0] == "cleanup":
        time.sleep(600)   # the test kills it half-way
    return 7

sys.exit(mh.serve(run=run))
"""


@pytest.fixture
def task(monkeypatch):
    queue = Path(os.environ["ProgramData"]) / f"OnionBoardCI-{secrets.token_hex(4)}"
    name = rf"\Onion Board CI\Mic helper {secrets.token_hex(4)}"
    sid = mh._token_sid()
    assert sid and mh._SID.fullmatch(sid), sid
    monkeypatch.setattr(mh, "_schtasks", REAL_SCHTASKS)
    monkeypatch.setattr(mh, "TASK", name)
    monkeypatch.setattr(mh, "queue_dir", lambda: queue)
    dm._secure_dir(queue, dm._BASE_SDDL)
    dm._secure_dir(mh.results_dir(), dm._BASE_SDDL)
    dm._secure_dir(mh.requests_dir(), mh._queue_sddl([sid]))
    script = queue / "serve.py"
    script.write_text(SERVE.format(root=str(ROOT)), encoding="utf-8")
    exe = Path(getattr(sys, "_base_executable", sys.executable))   # (not the venv's
    # launcher: ending the task must end the helper itself)
    arguments = f'"{script}" "{queue}"'
    xml = queue / "task.xml"
    xml.write_text(mh.task_xml(exe, [sid], arguments, workdir=ROOT), encoding="utf-16")
    assert REAL_SCHTASKS("/create", "/tn", name, "/xml", str(xml), "/f") == 0
    try:
        yield exe, sid, arguments
    finally:
        REAL_SCHTASKS("/end", "/tn", name)
        REAL_SCHTASKS("/delete", "/tn", name, "/f")
        shutil.rmtree(queue, ignore_errors=True)


def test_the_registered_task_is_ours(task):
    exe, sid, arguments = task
    assert mh.verify_task(exe, [sid], arguments)
    assert not mh.verify_task(exe, [sid, "S-1-5-21-1-2-3-1001"], arguments)


def test_a_round_trip_through_system(task):
    assert mh.ask(["uninstall"], wait_s=60) == 7
    assert not list(mh.requests_dir().iterdir())


def test_a_request_the_helper_refuses(task):
    rid = secrets.token_hex(16)
    (mh.requests_dir() / f"{rid}.req").write_bytes(b"install C:\\evil.dll")
    assert REAL_SCHTASKS("/run", "/tn", mh.TASK) == 0
    res = mh.results_dir() / f"{rid}.res"
    deadline = time.monotonic() + 60
    while not res.exists() and time.monotonic() < deadline:
        time.sleep(0.2)
    assert res.read_text() == "2"


def test_a_killed_helper_is_noticed_and_the_next_request_works(task, monkeypatch):
    """The helper took the request and died half-way: ask() gives up once the
    heartbeat stops (not after the full wait), and the next request is answered."""
    monkeypatch.setattr(mh, "STALE_S", 10.0)
    got = []
    asking = threading.Thread(target=lambda: got.append(mh.ask(["cleanup", GUID],
                                                                 wait_s=600)))
    start = time.monotonic()
    asking.start()
    deadline = start + 60
    while not list(mh.results_dir().glob("*.ack")) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert list(mh.results_dir().glob("*.ack")), "the helper never took the request"
    time.sleep(3)   # a few heartbeats: still waiting
    assert asking.is_alive()
    subprocess.run(["schtasks", "/end", "/tn", mh.TASK], capture_output=True, timeout=30)
    asking.join(60)
    assert got == [None] and time.monotonic() - start < 60
    assert mh.ask(["uninstall"], wait_s=60) == 7
