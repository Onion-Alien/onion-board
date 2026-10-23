"""Simulate the mic effect's admin install / uninstall and hammer it with failures.

Runs the real `soundboard/mic/micadmin.py` code (admin_install / admin_uninstall /
_install_endpoint / _uninstall_endpoint) against the fake registry from
`tests/test_directmic.py`, killing it at every single registry write, and checks the
invariants: a mic always ends up exactly as it started, one mic that won't go back
never strands the others, and the audio-stop retry behaves. Nothing touches the PC's
real registry, audio devices or mic.

    .venv\\Scripts\\python scripts\\directmic\\sim_directmic.py

Exit 0 = every scenario passed, 1 = something failed (printed). Run it after changing
the mic effect's admin install/uninstall or the ring layout (soundboard/mic/micadmin.py,
micring.py), before opening the PR: the pytest suite covers the normal paths, this covers the ones
cut off half-way (a crash, a reboot) that are hard to reach by hand.
"""
from __future__ import annotations

import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import soundboard.mic.directmic as dm   # noqa: E402
import test_directmic as t          # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail="") -> None:
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  :: " + str(detail)))
    if not ok:
        FAILS.append(name)


def noop(*_a, **_k):
    return None


@contextmanager
def patched(reg, **extra):
    """Point directmic's registry calls at the fake, plus any extra attributes."""
    saved = []

    def seta(obj, name, value):
        saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    seta(dm, "_BackupKey", lambda path, create=True: reg.key(path, create))
    seta(dm, "_StateKey", lambda path: reg.key(path))
    seta(dm, "installed_on", reg.installed_on)
    seta(dm.winreg, "DeleteKey", reg.delete_key)
    seta(dm, "_delete_if_empty",
         lambda path: None if reg.keys.get(path.lower()) else reg.keys.pop(path.lower(), None))
    for name, value in extra.items():
        seta(dm, name, value)
    try:
        yield
    finally:
        for obj, name, value in reversed(saved):
            setattr(obj, name, value)


def admin_extras(tmp: Path) -> dict:
    """The filesystem / audio / COM bits of admin_install & admin_uninstall: faked."""
    d = tmp / "MicPlugin"
    d.mkdir(exist_ok=True)
    dll = tmp / "obmic.dll"
    dll.write_bytes(b"fake dll")
    return {
        "bundled_dll": lambda: dll,
        "install_dir": lambda: tmp / "pf",
        "_old_install_dirs": lambda: [],
        "_make_ring": noop,
        "data_dir": lambda: d,
        "ring_path": lambda: d / "ring2.bin",
        "_enable_privileges": noop,
        "_running_dependents": lambda: [],
        "_audio_comes_back": noop,
        "_audio_service": lambda *a: True,
        "_register_com": noop,
        "_unregister_com": noop,
        # never this PC's own mics or programs: nothing opened, listened to or asked
        "_mic_is_silent": lambda guid: None,
        "_mics_open": lambda guids: set(),
        "_effect_runs": lambda guids, mark: True,
        "_processes": lambda exe: [],
    }


def nonempty(reg):
    return {k: dict(v) for k, v in reg.keys.items() if v}


# A stand-in for the helper's task (soundboard/mic/michelper.py serve()), as its own
# process on a temporary queue: it stops dead at STOP (the parent kills it there) and
# logs each admin step it would have run.
HELPER = """\
import sys, time
from pathlib import Path
sys.path.insert(0, {root!r})
from soundboard.mic import michelper as mh
queue, stop = Path(sys.argv[1]), sys.argv[2]
mh.queue_dir = lambda: queue

def hang():
    (queue / "stopped").write_text(stop)
    time.sleep(600)

def wrap(name):
    real = getattr(mh, name)
    def step(*a):
        if stop == "before " + name:
            hang()
        out = real(*a)
        if stop == "after " + name:
            hang()
        return out
    setattr(mh, name, step)

wrap("_take")
wrap("_answer")

def run(args):
    with open(queue / "ran.log", "a") as f:
        f.write(" ".join(args) + "\\n")
    if stop == "in the step":
        hang()
    return 7

sys.exit(mh.serve(run=run))
"""
STOPS = ["before _take", "after _take", "in the step", "after _answer"]


def helper_kills():
    """Each kill point: ask() comes back soon (None, or the answer when it was written
    already), leaves no request behind to be redone later, and the next request is
    answered by a fresh helper."""
    import subprocess
    import time

    from soundboard.mic import michelper as mh
    guid = "{11111111-2222-3333-4444-555555555555}"
    saved = mh.queue_dir, mh._schtasks, mh.STALE_S, mh.START_S
    mh.STALE_S, mh.START_S = 2.0, 5.0
    try:
        for stop in STOPS:
            with tempfile.TemporaryDirectory() as td:
                queue = Path(td)
                script = queue / "helper.py"
                script.write_text(HELPER.format(root=str(ROOT)), encoding="utf-8")
                mh.queue_dir = lambda q=queue: q
                mh.requests_dir().mkdir()
                mh.results_dir().mkdir()
                procs, mode = [], [stop]

                def start(*_a, script=script, queue=queue, procs=procs, mode=mode, **_k):
                    procs.append(subprocess.Popen(
                        [sys.executable, str(script), str(queue), mode[0]],
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)))
                    return 0
                mh._schtasks = start
                t0 = time.monotonic()
                killer = _kill_when(queue / "stopped", procs)
                code = mh.ask(["cleanup", guid], wait_s=60)
                killer.join()
                took = time.monotonic() - t0
                want = 7 if stop == "after _answer" else None
                check(f"{stop}: ask() gives {want}", code == want, code)
                check(f"{stop}: in {took:.0f} s, not the full wait", took < 15, took)
                check(f"{stop}: no request left to redo",
                      not list(mh.requests_dir().iterdir()), list(mh.requests_dir().iterdir()))
                (queue / "ran.log").unlink(missing_ok=True)
                mode[0] = "none"
                code = mh.ask(["uninstall"], wait_s=30)
                for p in procs:
                    p.wait(30)
                ran = (queue / "ran.log").read_text().split("\n") if (
                    queue / "ran.log").exists() else []
                check("  then the next request is answered", code == 7, code)
                check("  and only that one is run", ran == ["uninstall", ""], ran)
    finally:
        mh.queue_dir, mh._schtasks, mh.STALE_S, mh.START_S = saved


def _kill_when(marker: Path, procs: list):
    """A thread killing the helper once it stops at its kill point (like Task
    Scheduler ending it, or a crash)."""
    import threading
    import time

    def watch():
        deadline = time.monotonic() + 30
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        for p in procs:
            p.kill()
            p.wait(10)
    t = threading.Thread(target=watch, daemon=True)
    t.start()
    return t


def run() -> int:
    print("== 1. install then uninstall restores every kind of mic, exactly")
    for mic in t.MICS:
        reg = t.FakeReg()
        with patched(reg):
            t._mic(reg, t.MICS[mic])
            before = nonempty(reg)
            dm._install_endpoint(t.GUID, None)
            dm._uninstall_endpoint(t.GUID)
            check(repr(mic),
                  reg.mics() == before and not reg.installed_on() and not t._all_ours(reg),
                  (reg.mics(), before))

    print("== 2. a set-up cut off at every write can still be undone")
    for mic in t.MICS:
        reg = t.FakeReg()
        with patched(reg):
            t._mic(reg, t.MICS[mic])
            before = {k: dict(v) for k, v in reg.keys.items()}
            dm._install_endpoint(t.GUID, None)
            total = reg.writes
            bad = 0
            for n in range(1, total + 1):
                reg.keys = {k: dict(v) for k, v in before.items()}
                reg.writes, reg.kill_at = 0, n
                try:
                    dm._install_endpoint(t.GUID, None)
                except t.Killed:
                    pass
                reg.kill_at = None
                for guid in reg.installed_on():
                    dm._uninstall_endpoint(guid)
                if reg.mics() != {k: v for k, v in before.items() if v} or t._all_ours(reg):
                    bad += 1
            check(f"{mic!r} ({total} cut points)", bad == 0, f"{bad} not restored")

    print("== 3. an uninstall cut off at every write finishes on the next run")
    for mic in t.MICS:
        reg = t.FakeReg()
        with patched(reg):
            t._mic(reg, t.MICS[mic])
            before = nonempty(reg)
            dm._install_endpoint(t.GUID, None)
            reg.writes = 0
            dm._uninstall_endpoint(t.GUID)      # just to count a full uninstall's writes
            total = reg.writes
            reg.keys = {k: dict(v) for k, v in reg.keys.items()}
            reg.writes, reg.kill_at = 0, None
            dm._install_endpoint(t.GUID, None)
            installed = {k: dict(v) for k, v in reg.keys.items()}
            bad = 0
            for n in range(1, total + 1):
                reg.keys = {k: dict(v) for k, v in installed.items()}
                reg.writes, reg.kill_at = 0, n
                try:
                    dm._uninstall_endpoint(t.GUID)
                except t.Killed:
                    pass
                reg.kill_at = None
                for guid in reg.installed_on():   # the retry (a later uninstall)
                    dm._uninstall_endpoint(guid)
                if reg.mics() != before or t._all_ours(reg):
                    bad += 1
            check(f"{mic!r} ({total} cut points)", bad == 0, f"{bad} not restored")

    print("== 4. two mics: install both, uninstall both")
    reg = t.FakeReg()
    with patched(reg):
        t._mic(reg, t.MICS["a gaming headset (EFX + old LFX)"])
        before = nonempty(reg)
        dm._install_endpoint(t.GUID, None)
        dm._install_endpoint("{22222222-3333-4444-5555-666666666666}", None)
        check("both installed", len(reg.installed_on()) == 2, reg.installed_on())
        for guid in reg.installed_on():
            dm._uninstall_endpoint(guid)
        check("both restored", reg.mics() == before and not reg.installed_on(), reg.mics())

    print("== 5. full admin_install -> admin_uninstall round trip")
    for mic in t.MICS:
        reg = t.FakeReg()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            with patched(reg, **admin_extras(tmp)):
                t._mic(reg, t.MICS[mic])
                before = nonempty(reg)
                rc_i = dm.admin_install(t.GUID)
                installed = reg.installed_on()
                rc_u = dm.admin_uninstall()
                gone = not (tmp / "MicPlugin").exists()
                check(repr(mic),
                      rc_i == 0 and installed == [t.GUID.lower()] and rc_u == 0
                      and reg.mics() == before and not reg.installed_on() and gone,
                      (rc_i, installed, rc_u, reg.mics(), before, gone))

    print("== 6. one mic that won't go back doesn't strand the others (admin_uninstall)")
    reg = t.FakeReg()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        ex = admin_extras(tmp)
        tried, com = [], []

        def take(guid):
            tried.append(guid)
            if guid != t.GUID:
                raise OSError("registry locked")

        ex["_uninstall_endpoint"] = take
        ex["_unregister_com"] = lambda: com.append("com")
        with patched(reg, **ex):
            t._mic(reg, t.MICS["a gaming headset (EFX + old LFX)"])
            dm._install_endpoint(t.GUID, None)
            dm._install_endpoint("{22222222-3333-4444-5555-666666666666}", None)
            rc = dm.admin_uninstall()
            check("returns failure", rc == 1, rc)
            check("both mics tried", len(tried) == 2, tried)
            check("nothing unregistered", com == [], com)
            check("the ring folder is kept", (tmp / "MicPlugin").exists())

    print("== 7. audio stop that won't take: retried, then reported")
    ran, stopped = [], [False]
    saved = dm._run, dm._services_stopped
    dm._run = lambda cmd, timeout=60.0: ran.append(cmd) or 0
    dm._services_stopped = lambda: stopped[0]
    saved_wait, dm.STOP_WAIT_S = dm.STOP_WAIT_S, 0.0
    try:
        check("False when it won't stop", dm._audio_service(False) is False)
        check("stop retried", [c[2] for c in ran] ==
              ["audiosrv", "AudioEndpointBuilder", "audiosrv", "AudioEndpointBuilder"], ran)
        ran.clear()
        stopped[0] = True
        check("True when it stops", dm._audio_service(False) is True and len(ran) == 2, ran)
    finally:
        dm._run, dm._services_stopped = saved
        dm.STOP_WAIT_S = saved_wait

    print("== 8. the mic helper killed at every step: the next request still works")
    helper_kills()

    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} scenario(s): {FAILS}")
        return 1
    print("All simulation scenarios passed.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
