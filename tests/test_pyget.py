"""A Python for the add-ons (soundboard.online.pyget): which one is used, getting python.org's
own copy into the add-on's folder, and repairing an add-on whose Python has gone."""
import hashlib
import io
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

from soundboard.addons import modules
from soundboard.online import net, pyget


def service(path: Path) -> modules.ModuleInfo:
    return modules.ModuleInfo(id="live-voice", name="Live voice", version="1", description="",
                              kind="service", path=path,
                              command=["{python}", "{dir}/helper.py"])


def venv(folder: Path, home: Path | None) -> None:
    """A made environment: its python.exe, and a pyvenv.cfg naming `home`."""
    (folder / ".venv" / "Scripts").mkdir(parents=True)
    (folder / ".venv" / "Scripts" / "python.exe").write_bytes(b"")
    if home is not None:
        (folder / ".venv" / "pyvenv.cfg").write_text(
            f"home = {home}\ninclude-system-site-packages = false\nversion = 3.12.10\n")


def test_an_environment_whose_python_is_gone_is_broken_not_installed(tmp_path):
    base = tmp_path / "Python312"
    base.mkdir()
    (base / "python.exe").write_bytes(b"")
    m = service(tmp_path / "addon")
    assert not m.broken and not m.installed            # never set up: just not installed
    venv(m.path, base)
    assert not m.broken and m.installed
    (base / "python.exe").unlink()                     # Python uninstalled
    assert m.broken and not m.installed
    shutil.rmtree(m.path / ".venv")
    venv(m.path, None)                                 # no pyvenv.cfg: can't tell, so not
    assert not m.broken


def test_install_repairs_a_broken_environment(tmp_path):
    m = service(tmp_path / "addon")
    venv(m.path, tmp_path / "gone")
    (m.path / ".venv" / "old.txt").write_text("x")
    m.install_steps = [["{base_python}", "-c", "print('ran')"]]
    lines = []
    assert modules.install(m, lines.append)
    assert "ran" in lines and not (m.path / ".venv").exists()   # made again from scratch


def test_from_source_the_running_python_is_used(tmp_path):
    assert pyget.for_module(tmp_path, print) == sys.executable


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)


def test_the_add_ons_own_copy_comes_first_then_the_pcs_then_a_download(
        tmp_path, frozen, monkeypatch):
    versions = {}
    monkeypatch.setattr(pyget, "_version", lambda exe: versions.get(exe))
    monkeypatch.setattr(pyget.shutil, "which", lambda n: {"py": r"C:\Windows\py.exe"}.get(n))
    got = []
    monkeypatch.setattr(pyget, "get", lambda d, on_line: got.append(d) or "downloaded")

    versions[r"C:\Windows\py.exe"] = (3, 13)
    assert pyget.for_module(tmp_path, print) == r"C:\Windows\py.exe"
    versions[r"C:\Windows\py.exe"] = (3, 11)           # too old for the add-ons' wheels
    assert pyget.for_module(tmp_path, print) == "downloaded" and got == [tmp_path]
    versions[r"C:\Windows\py.exe"] = (3, 15)           # newer than they're known to work on
    assert pyget.for_module(tmp_path, print) == "downloaded"
    own = pyget.private_python(tmp_path)
    own.parent.mkdir()
    own.write_bytes(b"")
    versions[str(own)] = (3, 12)
    assert pyget.for_module(tmp_path, print) == str(own)   # a repair reuses its own copy


def test_the_store_stub_isnt_a_python(frozen, monkeypatch):
    stub = r"D:\Store\Microsoft\WindowsApps\python.exe"
    monkeypatch.setattr(pyget.shutil, "which", lambda n: stub if n == "python" else None)
    monkeypatch.setattr(pyget, "_version", lambda exe: (3, 12))
    assert pyget.pc_python() is None


def nupkg(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_unpack_takes_only_the_python_folder(tmp_path):
    pkg = tmp_path / "p.nupkg"
    pkg.write_bytes(nupkg({"tools/python.exe": b"exe", "tools/Lib/os.py": b"os",
                           "python.nuspec": b"<x/>", "build/native/x.props": b""}))
    dest = tmp_path / "addon" / ".python"
    dest.parent.mkdir()
    pyget.unpack(pkg, dest)
    assert (dest / "python.exe").read_bytes() == b"exe"
    assert (dest / "Lib" / "os.py").read_bytes() == b"os"
    assert sorted(p.name for p in dest.iterdir()) == ["Lib", "python.exe"]


@pytest.mark.parametrize("bad", ["tools/../../evil.txt", "tools/C:/evil.txt"])
def test_unpack_refuses_a_file_outside_its_folder(tmp_path, bad):
    pkg = tmp_path / "p.nupkg"
    pkg.write_bytes(nupkg({"tools/python.exe": b"exe", bad: b"x"}))
    dest = tmp_path / "addon" / ".python"
    dest.parent.mkdir()
    with pytest.raises(pyget.GetError):
        pyget.unpack(pkg, dest)
    assert not dest.exists() and not (tmp_path / "evil.txt").exists()
    assert list(dest.parent.iterdir()) == []           # the half-made folder went too


class Response(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def test_a_download_that_isnt_the_pinned_python_is_never_unpacked(tmp_path, monkeypatch):
    data = nupkg({"tools/python.exe": b"exe"})
    monkeypatch.setattr(net, "urlopen", lambda req, **k: Response(data))
    with pytest.raises(pyget.GetError, match="isn't the Python"):
        pyget.get(tmp_path, print)
    assert list(tmp_path.iterdir()) == []              # nothing kept, nothing unpacked


def test_get_downloads_checks_and_unpacks_into_the_addon(tmp_path, monkeypatch):
    data = nupkg({"tools/python.exe": b"exe", "tools/Lib/os.py": b"os"})
    monkeypatch.setattr(pyget, "SHA256", hashlib.sha256(data).hexdigest())
    seen = []
    monkeypatch.setattr(net, "urlopen",
                        lambda req, **k: seen.append((req.full_url, k)) or Response(data))
    monkeypatch.setattr(pyget, "_version", lambda exe: (3, 12))
    lines = []
    exe = pyget.get(tmp_path, lines.append)
    assert exe == str(tmp_path / ".python" / "python.exe")
    assert seen[0][0] == pyget.URL and seen[0][1]["feature"] == "addons"
    assert "15 MB" in lines[0] and lines[-1].endswith("100%")
    assert sorted(p.name for p in tmp_path.iterdir()) == [".python"]   # no .partial left


def test_one_that_unpacks_but_wont_start_says_so(tmp_path, monkeypatch):
    data = nupkg({"tools/python.exe": b"exe"})
    monkeypatch.setattr(pyget, "SHA256", hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(net, "urlopen", lambda req, **k: Response(data))
    monkeypatch.setattr(pyget, "_version", lambda exe: None)
    with pytest.raises(pyget.GetError, match="antivirus"):
        pyget.get(tmp_path, print)


def test_a_failed_get_ends_the_install_with_its_reason(tmp_path, frozen, monkeypatch):
    m = service(tmp_path)
    m.install_steps = [["{base_python}", "-m", "venv", "{dir}/.venv"]]

    def fail(d, on_line):
        raise pyget.GetError("Couldn't reach api.nuget.org (timed out).")
    monkeypatch.setattr(pyget, "for_module", fail)
    lines = []
    assert not modules.install(m, lines.append)
    assert lines[-1] == "Couldn't reach api.nuget.org (timed out)."


def test_install_addon_from_the_installer(tmp_path, monkeypatch, capsys):
    from soundboard.core import app
    m = service(tmp_path)
    monkeypatch.setattr(app.applog, "setup", lambda d: None)
    monkeypatch.setattr(modules, "discover", lambda dirs=None: [m])
    ran = []
    monkeypatch.setattr(modules, "install", lambda info, on_line: ran.append(info) or True)
    assert app.install_addon("live-voice") == 0 and ran == [m]
    assert app.install_addon("nope") == 1
    monkeypatch.setattr(modules, "install", lambda info, on_line: False)
    assert app.install_addon("live-voice") == 1


def test_the_voice_cards_offer_repair_for_a_broken_addon(qapp, tmp_path):
    from soundboard.speech.aivoice import AiVoiceController
    from soundboard.ui.voice.aivoicepanel import AiVoicePanel
    from soundboard.voicefx import VoiceChain
    m = service(tmp_path / "ai-voices")
    m.id = "ai-voices"
    venv(m.path, tmp_path / "gone")
    p = AiVoicePanel(AiVoiceController(VoiceChain(), lambda e: None), {}, [m])
    try:
        assert not p.b_install.isHidden() and p.b_install.text() == "Repair"
        assert "stopped working" in p.lbl_missing.text()
        assert "python.org" not in p.lbl_missing.text() + p.b_install.toolTip()
    finally:
        p.shutdown()
        p.deleteLater()


def test_an_install_clears_what_a_cut_short_download_left(tmp_path, frozen, monkeypatch):
    """The app ended mid-download / mid-unpack, and the next install takes the PC's own
    Python: the half package and .python.partial still go."""
    (tmp_path / f"python-{pyget.VERSION}.nupkg.partial").write_bytes(b"half")
    (tmp_path / ".python.partial" / "Lib").mkdir(parents=True)
    monkeypatch.setattr(pyget, "pc_python", lambda: r"C:\Windows\py.exe")
    assert pyget.for_module(tmp_path, print) == r"C:\Windows\py.exe"
    assert not any(tmp_path.iterdir())
