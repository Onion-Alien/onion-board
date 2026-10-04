"""scripts/version_info.py: OnionBoard.exe's version resource names the app "Onion
Board" (Windows Firewall's prompt shows it) and carries soundboard's real version."""
import ast
import sys
from pathlib import Path

import pytest

import soundboard

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import version_info as vi  # noqa: E402


def strings(text: str) -> dict[str, str]:
    """The StringStruct pairs, read back as Python literals."""
    tree = ast.parse(text)
    return {c.args[0].value: c.args[1].value for c in ast.walk(tree)
            if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "StringStruct"}


def test_the_version_file_matches_soundboards_version(tmp_path):
    out = tmp_path / "version_info.txt"
    assert vi.main([str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    s = strings(text)
    assert s["FileDescription"] == s["ProductName"] == "Onion Board"
    assert s["OriginalFilename"] == "OnionBoard.exe"
    assert s["FileVersion"] == s["ProductVersion"] == soundboard.__version__
    nums = vi.numbers(soundboard.__version__)
    assert f"filevers={nums}" in text and f"prodvers={nums}" in text


def test_pyinstaller_can_read_it():
    versioninfo = pytest.importorskip("PyInstaller.utils.win32.versioninfo")
    info = eval(vi.render("1.6.5"), vars(versioninfo))   # how PyInstaller loads it
    assert info.ffi.fileVersionMS == (1 << 16) | 6 and info.ffi.fileVersionLS == 5 << 16


def test_version_numbers():
    assert vi.numbers("1.6.5") == (1, 6, 5, 0)
    assert vi.numbers("2.0") == (2, 0, 0, 0)
    assert vi.numbers("1.7.0b1") == (1, 7, 0, 0)
    with pytest.raises(ValueError):
        vi.numbers("dev")


def test_build_ps1_uses_it():
    build = (ROOT / "build.ps1").read_text(encoding="utf-8")
    assert "scripts\\version_info.py" in build
    assert "--version-file installer\\version_info.txt" in build
