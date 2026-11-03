"""An add-on's environment gets Microsoft's C++ runtime from the app (modules.cpp_runtime):
on a new PC without it, onnxruntime (AI voices), ctranslate2 and sentencepiece (live voice)
failed with "DLL load failed", so the AI voices said they "aren't fully installed" and
live voice's install stopped at its download step."""
import sys
from pathlib import Path

from soundboard.addons import modules
from soundboard.online import net, pyget

PY = sys.executable


def venv_with(root: Path, *files: str) -> Path:
    venv = root / ".venv"
    for f in files:
        p = venv / "Lib" / "site-packages" / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    return venv


def test_each_compiled_package_gets_the_runtime_once(tmp_path):
    venv = venv_with(tmp_path, "onnxruntime/capi/onnxruntime_pybind11_state.pyd",
                     "ctranslate2/ctranslate2.dll", "own/_x.pyd", "own/MSVCP140.dll",
                     "numpy.libs/msvcp140-abc.dll", "plain/__init__.py")
    sp = venv / "Lib" / "site-packages"
    assert modules.cpp_runtime(venv) > 0
    for pkg in ("onnxruntime/capi", "ctranslate2"):
        for name in modules.CPP_RUNTIME:
            assert (sp / pkg / name).is_file(), (pkg, name)
    assert (sp / "own" / "MSVCP140.dll").read_bytes() == b"x"   # its own copy is kept
    assert not (sp / "numpy.libs" / "VCRUNTIME140.dll").exists()
    assert not (sp / "plain" / "VCRUNTIME140.dll").exists()     # no compiled code there
    assert modules.cpp_runtime(venv) == 0                         # done: not looked at again


def test_no_environment_is_left_alone(tmp_path):
    assert modules.cpp_runtime(tmp_path / ".venv") == 0
    assert not (tmp_path / ".venv").exists()


def test_a_pip_step_gives_the_runtime_before_the_next_step(tmp_path, monkeypatch):
    monkeypatch.setattr(net, "allowed", lambda feature: True)
    monkeypatch.setattr(pyget, "for_module", lambda d, on_line: PY)
    d = tmp_path / "live-voice"
    d.mkdir()
    pip = ("import pathlib; s = pathlib.Path('.venv/Lib/site-packages/ctranslate2'); "
           "s.mkdir(parents=True); (s / 'ctranslate2.dll').write_bytes(b'x'); "
           "p = pathlib.Path('.venv/Scripts'); p.mkdir(parents=True); "
           "(p / 'python.exe').write_bytes(b'')")
    need = ("import pathlib, sys; sys.exit(0 if pathlib.Path("
            "'.venv/Lib/site-packages/ctranslate2/MSVCP140.dll').is_file() else 3)")
    m = modules.ModuleInfo(id="live-voice", name="Live voice", version="1", description="",
                           kind="service", path=d, command=["{python}", "{dir}/helper.py"],
                           install_steps=[[PY, "-c", pip, "-m", "pip", "install"],
                                          [PY, "-c", need, "{dir}/helper.py", "--download"]])
    assert modules.install(m, print)


def test_starting_an_older_install_gives_it_the_runtime(tmp_path):
    venv = venv_with(tmp_path, "onnxruntime/capi/onnxruntime_pybind11_state.pyd")
    (venv / "Scripts").mkdir(parents=True)
    (venv / "Scripts" / "python.exe").write_bytes(b"")
    m = modules.ModuleInfo(id="ai-voices", name="AI voices", version="1", description="",
                           kind="service", path=tmp_path, command=["{python}", "{dir}/helper.py"])
    m.resolved_command()
    assert (venv / "Lib" / "site-packages" / "onnxruntime" / "capi" / "MSVCP140.dll").is_file()
