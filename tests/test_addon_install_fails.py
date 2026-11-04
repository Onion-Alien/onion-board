"""An add-on's install going wrong (soundboard.addons.modules.install): the daily count
says why with a fixed word, a first install that failed leaves nothing half made, the
PC's own Python is only used when the add-ons' packages exist for it, and the live voice
helper's speech model download tries again."""
import socket
import sys
import types
from pathlib import Path

import pytest

from soundboard.addons import modules
from soundboard.core import usage
from soundboard.online import net, netrelay, pyget

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


@pytest.fixture(autouse=True)
def no_waiting_between_tries(monkeypatch):
    monkeypatch.setattr(modules, "STEP_RETRY_WAIT_S", (0, 0), raising=False)


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
    ("SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED]'))", "cert"),
    ("SSLError(SSLEOFError(8, '[SSL: UNEXPECTED_EOF_WHILE_READING]'))", "ssl"),
    ("Couldn't download the speech model (502 Bad Gateway). Check your internet", "proxy"),
    ("An error happened while trying to locate the file on the Hub", "network"),
    ("Unable to copy 'venvlauncher.exe' to '.venv/Scripts/python.exe'", "denied"),
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


# ---------------------------------------------------------------- what the relay saw
def through_the_relay(url="https://pypi.example/simple/"):
    """A step that goes online the way pip does: through the relay child_env gives it,
    hearing only its "502 Bad Gateway" or "403 Forbidden". Fails the way pip then does."""
    return ("import sys, urllib.request\n"
            f"try: urllib.request.urlopen({url!r}, timeout=20)\n"
            "except OSError as e: print('WARNING: Retrying:', e)\n"
            "print('ERROR: No matching distribution found for numpy')\n"
            "sys.exit(1)\n")


@pytest.fixture
def counted(monkeypatch):
    got = []
    monkeypatch.setattr(usage, "used", lambda name: None)
    monkeypatch.setattr(usage, "failed", lambda what, *d: got.append((what, *d)))
    net.configure("direct")
    return got


@pytest.mark.parametrize("error, why, words", [
    (socket.gaierror(11001, "getaddrinfo failed"), "dns", "couldn't connect to pypi.example"),
    (TimeoutError("timed out"), "conn-timeout", "couldn't connect to pypi.example"),
    (ConnectionRefusedError(10061, "refused"), "refused", "couldn't connect to pypi.example"),
    (OSError(10051, "unreachable"), "no-connect", "couldn't connect to pypi.example"),
    (net.ProxyError("Couldn't reach the proxy at h:1. Nothing was sent without it."), "proxy",
     "Couldn't reach the proxy at h:1. Nothing was sent without it"),
])
def test_what_pip_cant_reach_is_said_tried_again_and_counted(tmp_path, monkeypatch, counted,
                                                             error, why, words):
    """pip through the relay only says "Cannot connect to proxy", in Direct mode too, then
    "No matching distribution": counted as a proxy problem, and the user read "failed
    (exit code 1)". The relay knows what really happened."""
    tries = []

    def cant(host, port, **kw):
        tries.append(host)
        raise error
    monkeypatch.setattr(netrelay.netconnect, "_open", cant)
    lines = []
    m = addon(tmp_path / "live-voice", [[PY, "-c", through_the_relay(), "-m", "pip"]])
    assert not modules.install(m, lines.append)
    assert counted == [("addon-step", "live-voice", "pip", why)]
    assert why in modules.OUTPUT_WORDS
    assert len(tries) == modules.STEP_TRIES
    assert lines[-1].startswith(words)   # the last line is what the failed toast shows


def test_a_name_leading_home_is_said_and_not_tried_again(tmp_path, monkeypatch, counted):
    tries = []

    def home(host, port, **kw):
        tries.append(host)
        raise net.LeadsHome(f"Not connecting to {host}: it leads to this PC or your home network")
    monkeypatch.setattr(netrelay.netconnect, "_open", home)
    lines = []
    m = addon(tmp_path / "live-voice", [[PY, "-c", through_the_relay(), "-m", "pip"]])
    assert not modules.install(m, lines.append)
    assert counted == [("addon-step", "live-voice", "pip", "home")]
    assert tries == ["pypi.example"]
    assert lines[-1] == "Not connecting to pypi.example: it leads to this PC or your home network"


def test_an_old_relay_failure_isnt_blamed_on_a_later_step(tmp_path, monkeypatch, counted):
    def cant(host, port, **kw):
        raise TimeoutError("timed out")
    monkeypatch.setattr(netrelay.netconnect, "_open", cant)
    m = addon(tmp_path / "live-voice", [[PY, "-c", through_the_relay(), "-m", "pip"]])
    modules.install(m, print)
    assert net.relay_failure("addons", 0.0) is not None
    assert net.relay_failure("voices", 0.0) is None
    counted.clear()
    code = "import sys; print('something nobody has seen'); sys.exit(1)"
    modules.install(addon(tmp_path / "live-voice2", [[PY, "-c", code, "-m", "pip"]]), print)
    assert counted == [("addon-step", "live-voice", "pip", "other")]


# ---------------------------------------------------------------- trying a step again
def fails_first(tmp_path, printed: str, times: int = 1) -> str:
    """A step printing `printed` and failing its first `times` runs, then working."""
    n = tmp_path / "runs.txt"
    return (f"import pathlib, sys; f = pathlib.Path({str(n)!r}); "
            "k = int(f.read_text()) if f.exists() else 0; f.write_text(str(k + 1)); "
            f"print({printed!r}) if k < {times} else None; sys.exit(k < {times})")


@pytest.mark.parametrize("printed, word", [
    ("Error: [WinError 5] Access is denied", "venv"),   # a virus scan holding the new .exe
    ("OSError: [WinError 32] being used by another process", "venv"),
    ("WARNING: Retrying ... ReadTimeoutError: Read timed out.", "pip"),
    ("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred", "pip"),
])
def test_a_step_that_can_pass_is_tried_again(tmp_path, seen, printed, word):
    lines = []
    m = addon(tmp_path / "live-voice",
              [[PY, "-c", fails_first(tmp_path, printed), "-m", word, "x"]])
    assert modules.install(m, lines.append)
    assert seen == ["addon-installed-live-voice"]
    assert any("trying again" in ln for ln in lines)


@pytest.mark.parametrize("printed", [
    "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed",
    "ERROR: No matching distribution found for numpy",
    "OSError: [Errno 28] No space left on device",
    "something nobody has seen",
])
def test_a_step_that_wont_pass_isnt(tmp_path, seen, printed):
    m = addon(tmp_path / "live-voice", [[PY, "-c", fails_first(tmp_path, printed, 9), "-m", "pip"]])
    assert not modules.install(m, print)
    assert (tmp_path / "runs.txt").read_text() == "1"


def test_it_gives_up_after_its_tries(tmp_path, seen):
    m = addon(tmp_path / "live-voice",
              [[PY, "-c", fails_first(tmp_path, "Access is denied", 9), "-m", "venv", "x"]])
    assert not modules.install(m, print)
    assert (tmp_path / "runs.txt").read_text() == str(modules.STEP_TRIES)
    assert seen == ["addon-failed-live-voice", "addon-failed-live-voice-venv"]


@pytest.mark.parametrize("printed, words", [
    ("Error: [WinError 5] Access is denied", "antivirus"),
    ("[SSL: CERTIFICATE_VERIFY_FAILED]", "secure connection"),
    ("OSError: [Errno 28] No space left on device", "disk is full"),
])
def test_the_last_line_says_what_to_do(tmp_path, seen, printed, words):
    """It's what the failed toast shows: it used to be "failed (exit code 1)"."""
    lines = []
    m = addon(tmp_path / "live-voice", [[PY, "-c", fails_first(tmp_path, printed, 9), "-m", "pip"]])
    assert not modules.install(m, lines.append)
    assert words in lines[-1]
    assert not lines[-1].endswith(".")   # the toast's sentence goes on after it


def test_a_half_made_environment_that_cant_be_removed_isnt_taken_for_installed(tmp_path, seen,
                                                                               monkeypatch):
    """An antivirus holding python.exe: it stayed behind and the add-on looked installed,
    with no packages and no Install button."""
    m = addon(tmp_path / "live-voice", [[PY, "-c", MAKE_VENV], [PY, "-c", FAIL, "-m", "pip"]])
    monkeypatch.setattr(modules.shutil, "rmtree", lambda *a, **kw: None)
    assert not modules.install(m, print)
    assert (m.path / ".venv" / "Scripts" / "python.exe").exists()
    assert not m.installed


# ---------------------------------------------------------------- a VPN's fake addresses
def answers(monkeypatch, ip):
    connected = []
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))])
    monkeypatch.setattr(socket, "create_connection",
                        lambda addr, timeout=None: connected.append(addr) or "sock")
    return connected


def test_a_vpn_apps_fake_address_isnt_the_home_network(monkeypatch):
    """In "fake IP" mode a VPN app answers every name with 198.18.x.x: everything going
    through the relay was refused as "leads to your home network"."""
    connected = answers(monkeypatch, "198.18.0.5")
    assert net._connect_away("pypi.org", 443, 5) == "sock"
    assert connected == [("198.18.0.5", 443)]


@pytest.mark.parametrize("parts", [(192, 168, 1, 1), (10, 0, 0, 1), (127, 0, 0, 1),
                                   (100, 64, 0, 1), (169, 254, 1, 1)])
def test_a_name_leading_home_is_still_refused(monkeypatch, parts):
    connected = answers(monkeypatch, ".".join(map(str, parts)))
    with pytest.raises(net.LeadsHome):
        net._connect_away("x.example", 443, 5)
    assert connected == []


def test_just_past_the_fake_range_is_an_ordinary_address(monkeypatch):
    connected = answers(monkeypatch, "198.20.0.1")
    assert net._connect_away("x.example", 443, 5) == "sock"
    assert connected == [("198.20.0.1", 443)]
