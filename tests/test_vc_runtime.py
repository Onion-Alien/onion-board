"""scripts/vc_runtime.py: older copies of the C++ runtime are overwritten by the
newest, on a fake tree with fake file versions (no pefile, no real DLLs)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import vc_runtime as vr  # noqa: E402

OLD, NEW = (14, 29, 30133, 0), (14, 44, 35211, 0)


def make(path: Path, version) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(".".join(map(str, version)))
    return path


def fake_version(path: Path):
    return tuple(int(x) for x in path.read_text().split("."))


def test_an_older_copy_is_overwritten_by_the_newest(tmp_path):
    internal = tmp_path / "OnionBoard" / "_internal"
    old = make(internal / "MSVCP140.dll", OLD)
    new = make(internal / "shiboken6" / "msvcp140.dll", NEW)
    same = make(internal / "vcruntime140.dll", NEW)
    make(internal / "shiboken6" / "vcruntime140.dll", NEW)
    moves = vr.plan(tmp_path / "OnionBoard", None, fake_version)
    assert moves == [(new, old)]
    assert all(dst != same for _, dst in moves)


def test_renamed_copies_and_other_dlls_are_left_alone(tmp_path):
    internal = tmp_path / "OnionBoard" / "_internal"
    make(internal / "numpy.libs" / "msvcp140-abc123.dll", OLD)
    make(internal / "msvcp140.dll", NEW)
    make(internal / "PySide6" / "Qt6Core.dll", OLD)
    assert vr.plan(tmp_path / "OnionBoard", None, fake_version) == []


def test_the_build_pythons_shiboken6_counts(tmp_path):
    internal = tmp_path / "OnionBoard" / "_internal"
    old = make(internal / "msvcp140.dll", OLD)
    venv = tmp_path / "venv" / "shiboken6"
    new = make(venv / "msvcp140.dll", NEW)
    added = make(venv / "msvcp140_1.dll", NEW)
    make(venv / "vcamp140.dll", NEW)   # nothing in the app ships it: not added
    moves = vr.plan(tmp_path / "OnionBoard", venv, fake_version)
    assert sorted(moves) == sorted([(new, old),
                                    (added, internal / "shiboken6" / "msvcp140_1.dll")])


def test_dry_run_changes_nothing(tmp_path, monkeypatch):
    internal = tmp_path / "OnionBoard" / "_internal"
    old = make(internal / "msvcp140.dll", OLD)
    make(internal / "shiboken6" / "msvcp140.dll", NEW)
    monkeypatch.setattr(vr, "_version_pefile", fake_version)
    monkeypatch.setattr(vr, "shiboken_dir", lambda: None)
    monkeypatch.setattr(vr.plan, "__defaults__", (None, fake_version))
    assert vr.main([str(tmp_path / "OnionBoard"), "--dry-run"]) == 0
    assert fake_version(old) == OLD
    assert vr.main([str(tmp_path / "OnionBoard")]) == 0
    assert fake_version(old) == NEW
