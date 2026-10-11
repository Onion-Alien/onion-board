"""Simulate the mic effect's admin install / uninstall and hammer it with failures.

Runs the real `soundboard/directmic.py` code (admin_install / admin_uninstall /
_install_endpoint / _uninstall_endpoint) against the fake registry from
`tests/test_directmic.py`, killing it at every single registry write, and checks the
invariants: a mic always ends up exactly as it started, one mic that won't go back
never strands the others, and the audio-stop retry behaves. Nothing touches the PC's
real registry, audio devices or mic.

    .venv\\Scripts\\python scripts\\sim_directmic.py

Exit 0 = every scenario passed, 1 = something failed (printed). Run it after changing
the mic effect's admin install/uninstall or the ring layout (soundboard/directmic.py),
before opening the PR: the pytest suite covers the normal paths, this covers the ones
cut off half-way (a crash, a reboot) that are hard to reach by hand.
"""
from __future__ import annotations

import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import soundboard.directmic as dm   # noqa: E402
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
        "_audio_service": noop,
        "_register_com": noop,
        "_unregister_com": noop,
    }


def nonempty(reg):
    return {k: dict(v) for k, v in reg.keys.items() if v}


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
    try:
        check("False when it won't stop", dm._audio_service(False) is False)
        check("stop retried", [c[2] for c in ran] ==
              ["audiosrv", "AudioEndpointBuilder", "AudioEndpointBuilder"], ran)
        ran.clear()
        stopped[0] = True
        check("True when it stops", dm._audio_service(False) is True and len(ran) == 2, ran)
    finally:
        dm._run, dm._services_stopped = saved

    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} scenario(s): {FAILS}")
        return 1
    print("All simulation scenarios passed.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
