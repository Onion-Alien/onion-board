"""scripts/build_michelper.py: telling PyInstaller's stock bootloader from one compiled
here, on fake bootloader files (no PyInstaller build)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_michelper as bm  # noqa: E402


def _bootloaders(folder: Path, data: bytes = b"stock") -> Path:
    for name in bm.BOOTLOADERS:
        (folder / name).write_bytes(data + name.encode())
    return folder


def test_no_marker_is_stock(tmp_path):
    assert bm.stock_bootloader(_bootloaders(tmp_path))


def test_marker_matching_both_is_compiled_here(tmp_path):
    folder = _bootloaders(tmp_path, b"ours")
    (folder / bm.MARKER).write_text(bm.bootloader_hashes(folder), encoding="utf-8")
    assert bm.stock_bootloader(folder) == ""


def test_stock_reinstalled_over_marker_is_stock(tmp_path):
    # pip leaves the marker behind when a stock wheel replaces the compiled one
    folder = _bootloaders(tmp_path, b"ours")
    (folder / bm.MARKER).write_text(bm.bootloader_hashes(folder), encoding="utf-8")
    (folder / "run.exe").write_bytes(b"stock run")
    assert bm.stock_bootloader(folder)


def test_the_shipped_helper_is_listed_after_the_runtime_clean_up():
    """vc_runtime.py overwrites older C++ runtime DLLs anywhere under _internal, the
    bundled helper's too: build.ps1 must list the helper's files again after it, or the
    shipped build never matches its manifest and the helper is never set up."""
    text = (ROOT / "build.ps1").read_text(encoding="utf-8")
    assert "write_manifest" in text
    assert text.index("write_manifest") > text.index(r"scripts\vc_runtime.py dist\OnionBoard")


def test_the_probe_lists_modules_that_need_what_the_helper_leaves_out(tmp_path):
    """PyInstaller follows imports inside functions too: directmic's lazy ones put the
    whole app in the helper. What can't load there (it needs numpy, Qt...) is left out."""
    import subprocess
    pkg = tmp_path / "soundboard"
    (pkg / "ui").mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "fine.py").write_text("import json\n")
    (pkg / "needsnumpy.py").write_text("import numpy\n")
    (pkg / "viaother.py").write_text("from soundboard import needsnumpy\n")
    (pkg / "lazy.py").write_text("def f():\n    import numpy\n")
    (pkg / "ui" / "__init__.py").write_text("")
    (pkg / "ui" / "window.py").write_text("from PySide6 import QtWidgets\n")
    r = subprocess.run([sys.executable, "-c", bm.PROBE, *bm.EXCLUDE], cwd=tmp_path,
                       capture_output=True, text=True, timeout=60, check=True)
    assert r.stdout.split() == ["soundboard.needsnumpy", "soundboard.ui.window",
                                "soundboard.viaother"]


def test_the_build_stops_if_the_helper_itself_would_be_left_out(monkeypatch):
    import subprocess

    import pytest
    monkeypatch.setattr(bm.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 0, "soundboard.ui.mainwindow\nsoundboard.appaudio\n", ""))
    with pytest.raises(RuntimeError, match="soundboard.appaudio"):
        bm.unloadable()
    monkeypatch.setattr(bm.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 0, "soundboard.ui.mainwindow\n", ""))
    assert bm.unloadable() == ["soundboard.ui.mainwindow"]
