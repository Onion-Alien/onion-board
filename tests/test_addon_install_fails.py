"""An add-on's install going wrong (soundboard.addons.modules.install): the daily count
says why with a fixed word, a first install that failed leaves nothing half made, the
PC's own Python is only used when the add-ons' packages exist for it, and the live voice
helper's speech model download tries again."""
import sys
import types
from pathlib import Path

import pytest

from soundboard.addons import modules
from soundboard.core import usage
from soundboard.online import net, pyget

LIVE = Path(__file__).resolve().parent.parent / "modules" / "live-voice"
PY = sys.executable
FAIL = "import sys; sys.exit(1)"
MAKE_VENV = ("import pathlib, sys; p = pathlib.Path('.venv/Scripts'); "
             "p.mkdir(parents=True, exist_ok=True); (p / 'python.exe').write_bytes(b'')")


def addon(path: Path, steps) -> modules.ModuleInfo:
    path.mkdir(parents=True, exist_ok=True)
    return modules.ModuleInfo(id="live-voice", name="Live voice", version="1", description="",
                              kind="service", path=path, install_steps=steps,
                              command=["{python}", "{dir}/helper.py"])


@pytest.fixture
def seen(monkeypatch):
    got = []
    monkeypatch.setattr(usage, "used", got.append)
    return got


# the steps the way module.json writes them, each run as a stand-in that fails (or makes
# the environment's python.exe): the words after the code are only its arguments
@pytest.mark.parametrize("step, why", [
    (["{base_python}", "-c", FAIL, "-m", "venv", "{dir}/.venv"], "venv"),
    (["{python}", "-c", FAIL, "-m", "pip", "install", "-r", "x.txt"], "pip"),
    (["{python}", "-c", FAIL, "{dir}/helper.py", "--download", "base.en"], "download"),
    (["{python}", "-c", FAIL], "step"),
])
def test_a_failed_step_is_counted_with_which_step(tmp_path, seen, step, why):
    m = addon(tmp_path / "live-voice", [step])
    assert not modules.install(m, print)
    assert seen == ["addon-failed-live-voice", f"addon-failed-live-voice-{why}"]
    assert set(seen) <= set(usage.FEATURES)


def test_add_ons_switched_off_python_not_got_and_a_hang_say_so(tmp_path, seen, monkeypatch):
    m = addon(tmp_path / "live-voice", [[PY, "-c", "import time; time.sleep(60)"]])
    monkeypatch.setattr(net, "allowed", lambda feature: False)
    assert not modules.install(m, print)
    monkeypatch.setattr(net, "allowed", lambda feature: True)

    def no_python(d, on_line):
        raise pyget.GetError("no")
    real_for_module = pyget.for_module
    monkeypatch.setattr(pyget, "for_module", no_python)
    assert not modules.install(m, print)
    monkeypatch.setattr(pyget, "for_module", real_for_module)
    monkeypatch.setattr(modules, "INSTALL_STEP_TIMEOUT_S", 0.5)
    assert not modules.install(m, print)
    assert seen[1::2] == ["addon-failed-live-voice-off", "addon-failed-live-voice-python",
                          "addon-failed-live-voice-timeout"]
    assert set(seen) <= set(usage.FEATURES)


def test_an_install_that_crashes_is_still_counted(tmp_path, seen, monkeypatch):
    def boom(d, on_line):
        raise OSError("disk gone")
    monkeypatch.setattr(pyget, "for_module", boom)
    with pytest.raises(OSError):
        modules.install(addon(tmp_path / "live-voice", [[PY, "-c", "pass"]]), print)
    assert seen == ["addon-failed-live-voice", "addon-failed-live-voice-other"]


def test_a_failed_first_install_leaves_no_half_made_environment(tmp_path, seen):
    """pip stopping halfway used to leave .venv\\Scripts\\python.exe, so the add-on
    looked installed (no Install button, the installer skipping it) without its
    packages."""
    m = addon(tmp_path / "live-voice", [[PY, "-c", MAKE_VENV], [PY, "-c", FAIL, "-m", "pip"]])
    assert not modules.install(m, print)
    assert not m.installed and not (m.path / ".venv").exists()


def test_an_install_cut_off_by_the_app_closing_isnt_taken_for_installed(tmp_path, seen):
    """The app closed or crashed while pip ran: nothing cleaned up, so the half-made
    .venv\\Scripts\\python.exe used to count as installed, and every voice then failed
    ("No module named 'numpy'") with no Install button to fix it."""
    m = addon(tmp_path / "live-voice", [[PY, "-c", MAKE_VENV]])
    (m.path / ".venv" / "Scripts").mkdir(parents=True)
    (m.path / ".venv" / "Scripts" / "python.exe").write_bytes(b"")
    (m.path / ".venv" / "half.txt").write_text("left by the cut-off install")
    (m.path / modules.INSTALLING).touch()   # what the closed app left behind
    assert not m.installed
    assert modules.install(m, print)        # pressing Install again starts it clean
    assert m.installed and not (m.path / modules.INSTALLING).exists()
    assert not (m.path / ".venv" / "half.txt").exists()


def test_an_install_leaves_no_mark_however_it_ends(tmp_path, seen):
    for steps in ([[PY, "-c", MAKE_VENV]], [[PY, "-c", MAKE_VENV], [PY, "-c", FAIL]]):
        m = addon(tmp_path / f"live-voice-{len(steps)}", steps)
        modules.install(m, print)
        assert not (m.path / modules.INSTALLING).exists()


def test_a_failed_update_keeps_the_working_environment(tmp_path, seen):
    m = addon(tmp_path / "live-voice", [[PY, "-c", FAIL, "-m", "pip"]])
    (m.path / ".venv" / "Scripts").mkdir(parents=True)
    (m.path / ".venv" / "Scripts" / "python.exe").write_bytes(b"")
    assert not modules.install(m, print)
    assert m.installed


def test_only_the_speech_model_failing_keeps_the_environment(tmp_path, seen):
    """Its packages are in: the helper gets the model itself the first time it starts."""
    m = addon(tmp_path / "live-voice", [[PY, "-c", MAKE_VENV],
                                        [PY, "-c", FAIL, "helper.py", "--download", "x"]])
    assert not modules.install(m, print)
    assert m.installed
    assert seen[-1] == "addon-failed-live-voice-download"


# ---------------------------------------------------------------- the PC's own Python
def fake_python(monkeypatch, platform="win-amd64", ensurepip=True):
    """subprocess.run as a Python 3.12 for `platform`: runs the probe pyget sends it
    (python -c CODE) here, with what that Python would answer."""
    import io
    import subprocess
    import sysconfig
    from contextlib import redirect_stdout

    def run(argv, **kw):
        out, code = io.StringIO(), 0
        saved = sys.modules.get("ensurepip")
        real_platform, real_version = sysconfig.get_platform, sys.version_info
        try:
            sysconfig.get_platform = lambda: platform
            sys.version_info = (3, 12, 10, "final", 0)
            if not ensurepip:
                sys.modules["ensurepip"] = None   # import ensurepip -> ImportError
            with redirect_stdout(out):
                exec(argv[argv.index("-c") + 1], {})
        except BaseException:   # noqa: BLE001 - the "Python" exited with an error
            code = 1
        finally:
            sysconfig.get_platform, sys.version_info = real_platform, real_version
            if saved is None:
                sys.modules.pop("ensurepip", None)
            else:
                sys.modules["ensurepip"] = saved
        return subprocess.CompletedProcess(argv, code, out.getvalue() if not code else "",
                                           "")
    monkeypatch.setattr(pyget.subprocess, "run", run)
    monkeypatch.setattr(pyget.shutil, "which",
                        lambda n: r"C:\Python312\python.exe" if n == "python" else None)
    monkeypatch.setattr(pyget.os, "name", "nt")


def test_a_64_bit_pc_python_with_pip_is_used(monkeypatch):
    fake_python(monkeypatch)
    assert pyget.pc_python() == r"C:\Python312\python.exe"


@pytest.mark.parametrize("platform", ["win-arm64", "win32"])
def test_a_pc_python_the_packages_dont_exist_for_isnt_used(monkeypatch, platform):
    """Speech recognition (ctranslate2) has no ARM64 or 32-bit Windows packages: pip
    would fail on it every time. The add-on's own x64 Python is got instead."""
    fake_python(monkeypatch, platform=platform)
    assert pyget.pc_python() is None


def test_a_pc_python_without_pip_isnt_used(monkeypatch):
    """`python -m venv` fails on a Python installed without pip (no ensurepip)."""
    fake_python(monkeypatch, ensurepip=False)
    assert pyget.pc_python() is None


# ---------------------------------------------------------------- the speech model
@pytest.fixture
def helper(monkeypatch):
    monkeypatch.syspath_prepend(str(LIVE))
    for key in ("HF_HUB_DISABLE_XET", "HF_HUB_DOWNLOAD_TIMEOUT", "HF_HUB_ETAG_TIMEOUT"):
        monkeypatch.delenv(key, raising=False)   # put back as they were afterwards
    for name in ("helper", "protocol"):
        sys.modules.pop(name, None)
    import helper
    yield helper
    for name in ("helper", "protocol"):
        sys.modules.pop(name, None)


def fake_whisper(monkeypatch, fails: int):
    """faster_whisper whose download fails `fails` times first (a dropped connection)."""
    calls = {"download": 0, "loaded": []}

    def download_model(name, local_files_only=False):
        calls["download"] += 1
        if calls["download"] <= fails:
            raise OSError("connection reset")
        return f"models/{name}"

    class WhisperModel:
        def __init__(self, name, **kw):
            if "/" not in name:          # a size: it downloads it itself, once
                name = download_model(name)
            calls["loaded"].append(name)

    fw = types.ModuleType("faster_whisper")
    fw.WhisperModel = WhisperModel
    utils = types.ModuleType("faster_whisper.utils")
    utils.download_model = download_model
    utils._MODELS = {"base.en": "Systran/faster-whisper-base.en"}
    fw.utils = utils
    monkeypatch.setitem(sys.modules, "faster_whisper", fw)
    monkeypatch.setitem(sys.modules, "faster_whisper.utils", utils)
    return calls


def test_the_speech_model_download_tries_again(helper, monkeypatch, capsys):
    calls = fake_whisper(monkeypatch, fails=2)
    monkeypatch.setattr(helper.time, "sleep", lambda s: None)
    assert helper.main(["--download", "base.en"]) == 0
    assert calls["download"] == 3 and calls["loaded"] == ["models/base.en"]
    assert "Speech model ready." in capsys.readouterr().out


def test_the_speech_model_download_gives_up_with_a_message(helper, monkeypatch, capsys):
    fake_whisper(monkeypatch, fails=99)
    monkeypatch.setattr(helper.time, "sleep", lambda s: None)
    assert helper.main(["--download", "base.en"]) == 1
    assert "Couldn't download the speech model" in capsys.readouterr().out


def test_hugging_face_waits_longer_than_10_s(helper):
    """Its default 10 s per read drops a download through a slow proxy or Tor."""
    import os
    assert int(os.environ["HF_HUB_DOWNLOAD_TIMEOUT"]) >= 60
    assert int(os.environ["HF_HUB_ETAG_TIMEOUT"]) >= 60


def test_an_install_that_crashes_says_its_type_and_place(tmp_path, seen, monkeypatch):
    from soundboard import __version__
    monkeypatch.setattr(usage, "_pending", [])
    monkeypatch.setattr(usage, "_failed", set())

    def boom(d, on_line):
        raise KeyError("D:/private/x")
    monkeypatch.setattr(pyget, "for_module", boom)
    with pytest.raises(KeyError):
        modules.install(addon(tmp_path / "live-voice", [[PY, "-c", "pass"]]), print)
    [event] = usage._pending
    assert event.startswith(f"failed/{__version__}/addon-other/live-voice/KeyError@"
                            "soundboard/addons/modules.py:")
    assert "private" not in event


@pytest.mark.parametrize("printed, why", [
    ("", "silent"),
    ("ERROR: Could not find a version that satisfies the requirement torch==9", "no-match"),
    ("WARNING: Retrying ... ReadTimeoutError: Read timed out.", "network"),
    ("SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED]'))", "ssl"),
    ("OSError: [Errno 28] No space left on device", "disk"),
    ("ERROR: Could not install packages due to an OSError: [WinError 5] Access is denied",
     "denied"),
    ("OSError: [WinError 206] The filename or extension is too long", "long-path"),
    ("error: Microsoft Visual C++ 14.0 or greater is required", "build"),
    ("something nobody has seen", "other"),
])
def test_a_failed_step_counts_why_from_what_it_printed(tmp_path, monkeypatch, caplog,
                                                       printed, why):
    """"pip failed" told nothing: why it did is read from the end of what it printed, logged
    with those lines, and counted as a fixed word (never the text)."""
    got = []
    monkeypatch.setattr(usage, "used", lambda name: None)
    monkeypatch.setattr(usage, "failed", lambda what, *d: got.append((what, *d)))
    code = f"import sys; print({printed!r}) if {printed!r} else None; sys.exit(1)"
    m = addon(tmp_path / "live-voice", [["{python}", "-c", code, "-m", "pip", "install"]])
    with caplog.at_level("WARNING"):
        assert not modules.install(m, lambda line: None)
    assert got == [("addon-step", "live-voice", "pip", why)]
    assert why in modules.OUTPUT_WORDS
    assert f"({why})" in caplog.text
    if printed:
        assert printed in caplog.text
