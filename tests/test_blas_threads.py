"""OpenBLAS (numpy's and scipy's maths library) starts one idle thread per CPU and
reserves ~32 MB for each unless it's told otherwise before numpy loads: the app tells
it, as the first thing any entry point imports."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

import soundboard
from soundboard import net

ROOT = Path(__file__).resolve().parent.parent
PROBE = ("import os, sys; sys.path.insert(0, {root!r}); import {mod}; import numpy; "
         "print(os.environ.get('OPENBLAS_NUM_THREADS'), os.environ.get('{mark}'))")


def run(mod: str, **env) -> list[str]:
    e = {k: v for k, v in os.environ.items()
         if k not in ("OPENBLAS_NUM_THREADS", soundboard.BLAS_MARK)}
    e.update(env)
    code = PROBE.format(root=str(ROOT), mod=mod, mark=soundboard.BLAS_MARK)
    r = subprocess.run([sys.executable, "-c", code], env=e, capture_output=True, text=True,
                       timeout=120, cwd=str(ROOT))
    assert r.returncode == 0, r.stderr
    return r.stdout.split()


@pytest.mark.windows   # starts the app in a child process
@pytest.mark.parametrize("entry", ["main", "soundboard.app", "soundboard.directmic"])
def test_starting_the_app_caps_the_maths_threads(entry):
    # main.py (the shortcuts, the frozen exe), python -m soundboard, the admin helpers
    assert run(entry) == [soundboard.BLAS_THREADS, "1"]


@pytest.mark.windows   # starts the app in a child process
def test_a_cap_the_user_set_is_kept():
    assert run("soundboard.app", OPENBLAS_NUM_THREADS="8") == ["8", "None"]


def test_a_restarted_app_still_knows_the_cap_was_its_own():
    # the app restarting itself (or the installer starting it) hands its env on
    out = run("soundboard", OPENBLAS_NUM_THREADS="4", **{soundboard.BLAS_MARK: "1"})
    assert out == [soundboard.BLAS_THREADS, "1"]


def test_helper_processes_dont_get_the_apps_cap(monkeypatch):
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", soundboard.BLAS_THREADS)
    monkeypatch.setenv(soundboard.BLAS_MARK, "1")
    env = net.child_env("voices")
    assert "OPENBLAS_NUM_THREADS" not in env and soundboard.BLAS_MARK not in env
    assert os.environ["OPENBLAS_NUM_THREADS"] == soundboard.BLAS_THREADS   # the app's own


def test_helper_processes_keep_a_cap_the_user_set(monkeypatch):
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "3")
    monkeypatch.delenv(soundboard.BLAS_MARK, raising=False)
    assert net.child_env("addons")["OPENBLAS_NUM_THREADS"] == "3"
