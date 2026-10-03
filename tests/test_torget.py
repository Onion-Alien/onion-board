"""Get Tor (soundboard.torget): the download goes through net.urlopen, is checked
against the pinned SHA-256, and only the kept files are unpacked into
%APPDATA%\\OnionBoard\\tor\\bin, where soundboard.tor then finds tor.exe. Also the
Settings button and `OnionBoard.exe --get-tor` (the installer's Tor box). No
network: the tarball is made here and served by a stand-in for net.urlopen."""
import hashlib
import io
import tarfile

import pytest

from conftest import process_events
from soundboard import net, tor, torget


def make_tarball(extra: dict[str, bytes] | None = None, drop: str = "") -> bytes:
    """A stand-in Expert Bundle: every kept member, plus `extra`, minus `drop`."""
    files = {name: f"contents of {name}".encode() for name in torget.KEEP if name != drop}
    files["tor/pluggable_transports/pt_config.json"] = b'{"bridges": {"obfs4": ["x"]}}'
    files.update(extra or {})
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class Response(io.BytesIO):
    def __init__(self, data: bytes, length: bool = True):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))} if length else {}


@pytest.fixture
def served(monkeypatch, app_dir):
    """net.urlopen serves `served.data` (a valid tarball, pinned) and records calls."""
    class Served:
        data = make_tarball()
        calls: list = []
    monkeypatch.setattr(torget, "SHA256", hashlib.sha256(Served.data).hexdigest())

    def fake_urlopen(req, timeout=30, feature=None, direct=False):
        assert feature == torget.FEATURE == "tor_download"
        Served.calls.append((req.full_url, direct))
        return Response(Served.data)
    monkeypatch.setattr(net, "urlopen", fake_urlopen)
    monkeypatch.setattr(tor, "bundle_dirs", lambda: [torget.bin_dir()])   # not vendor/tor
    return Served


def test_get_unpacks_only_the_kept_files_where_tor_looks(served, app_dir):
    served.data = make_tarball({"tor/tor-gencert.exe": b"no", "data/geoip": b"no",
                                "../outside.txt": b"no"})
    torget.SHA256 = hashlib.sha256(served.data).hexdigest()
    seen = []
    assert not tor.available()
    dest = torget.get(lambda done, total: seen.append((done, total)))
    assert dest == app_dir / "tor" / "bin" == torget.bin_dir()
    got = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file())
    assert got == sorted([*torget.KEEP.values(), "VERSION"])
    assert not (app_dir / "outside.txt").exists() and not (app_dir / "tor" / "outside.txt").exists()
    assert torget.installed()
    assert tor.available() and tor.tor_exe() == dest / "tor.exe"
    assert tor.load_pt_config()["bridges"]["obfs4"] == ["x"]
    assert served.calls == [(torget.URL, False)]   # through net.urlopen, never forced direct
    assert seen and seen[-1] == (len(served.data), len(served.data))


def test_a_download_that_doesnt_match_the_checksum_is_never_unpacked(served, app_dir):
    served.data = make_tarball({"tor/evil.exe": b"!"})
    with pytest.raises(torget.GetError, match="checksum"):
        torget.get()
    assert not (app_dir / "tor").exists()
    assert not tor.available()


def test_a_tarball_missing_a_kept_file_leaves_nothing_behind(served, app_dir):
    served.data = make_tarball(drop="tor/pluggable_transports/lyrebird.exe")
    torget.SHA256 = hashlib.sha256(served.data).hexdigest()
    with pytest.raises(torget.GetError, match="lyrebird"):
        torget.get()
    assert not (app_dir / "tor" / "bin").exists()
    assert not (app_dir / "tor" / "bin.partial").exists()


def test_an_update_replaces_an_older_copy(served, app_dir):
    old = torget.bin_dir()
    old.mkdir(parents=True)
    (old / "tor.exe").write_bytes(b"old")
    (old / "VERSION").write_text("14.0 0000\n")
    assert tor.available() and not torget.installed()
    stopped = []
    torget.get(before_unpack=lambda: stopped.append(1))
    assert stopped == [1]
    assert torget.installed() and (old / "tor.exe").read_bytes() != b"old"
    assert not old.with_name("bin.old").exists()


def test_network_failures_say_tor_may_be_blocked(monkeypatch, app_dir):
    def refuse(req, timeout=30, feature=None, direct=False):
        raise OSError("connection reset")
    monkeypatch.setattr(net, "urlopen", refuse)
    monkeypatch.setattr(tor, "bundle_dirs", lambda: [torget.bin_dir()])
    with pytest.raises(torget.GetError, match="blocked"):
        torget.get()


def test_a_proxy_that_fails_is_reported_not_bypassed(monkeypatch, app_dir):
    def closed(req, timeout=30, feature=None, direct=False):
        raise net.ProxyError("Couldn't reach the proxy at 127.0.0.1:9 (refused)")
    monkeypatch.setattr(net, "urlopen", closed)
    with pytest.raises(torget.GetError, match="proxy"):
        torget.get()


def test_far_too_big_a_download_is_refused(monkeypatch, app_dir):
    monkeypatch.setattr(torget, "MAX_BYTES", 10)
    monkeypatch.setattr(net, "urlopen",
                        lambda req, timeout=30, feature=None, direct=False:
                        Response(b"x" * 100, False))
    with pytest.raises(torget.GetError, match="size"):
        torget.get()


def test_tor_mode_without_tor_asks_for_another_connection(monkeypatch, app_dir):
    monkeypatch.setattr(tor, "bundle_dirs", lambda: [torget.bin_dir()])
    monkeypatch.setattr(net, "urlopen", lambda *a, **k: pytest.fail("fetched without Tor"))
    net.configure(net.TOR)
    try:
        with pytest.raises(torget.GetError, match="Direct or Through a proxy"):
            torget.get()
    finally:
        net.configure(net.DIRECT)


def test_get_tor_command_line(served, app_dir, monkeypatch):
    """The installer's box: OnionBoard.exe --get-tor, exit code 0 once Tor is there."""
    from soundboard import app, applog
    monkeypatch.setattr(app, "APP_DIR", app_dir)
    monkeypatch.setattr(applog, "setup", lambda d: d / "log")
    assert app.get_tor() == 0
    assert torget.installed()
    served.calls.clear()
    assert app.get_tor() == 0 and served.calls == []   # already there: no download
    import shutil
    shutil.rmtree(torget.bin_dir())
    served.data = b"not tor"
    assert app.get_tor() == 1


@pytest.mark.parametrize("off", [{"off": ["tor_download"]}, {"offline": True}])
def test_get_tor_is_refused_while_its_switch_is_off(served, app_dir, off):
    net.configure_features(**off)
    with pytest.raises(torget.GetError, match="switched off|Offline mode"):
        torget.get()
    assert served.calls == [] and not torget.installed()


def test_the_get_tor_download_itself_names_its_switch(monkeypatch, app_dir):
    """Through the real net.urlopen: switched off, refused before anything's looked up."""
    monkeypatch.setattr(net.socket, "create_connection",
                        lambda *a, **k: pytest.fail("connected"))
    monkeypatch.setattr(net.socket, "getaddrinfo", lambda *a, **k: pytest.fail("looked up"))
    net.configure_features(off=["tor_download"])
    with pytest.raises(torget.GetError, match="Downloading Tor from the app is switched off"):
        torget.download()


def test_settings_get_tor_button(window, qapp, served, monkeypatch):  # noqa: F811
    from soundboard.settings import SettingsDialog
    d = SettingsDialog(window, "privacy")
    d.show()
    qapp.processEvents()
    assert d.net_get.isVisibleTo(d) and not d.net_tor.isEnabled()
    assert "blocked" in d.net_get_note.text()
    d.net_get.click()
    assert process_events(qapp, lambda: "ready" in d.net_get_note.text())
    assert torget.installed()
    assert d.net_tor.isEnabled()
    assert "ready" in d.net_get_note.text()
    d.close()


def test_settings_get_tor_button_follows_its_switch(window, qapp, served):  # noqa: F811
    from soundboard.settings import SettingsDialog
    d = SettingsDialog(window, "privacy")
    d.show()
    qapp.processEvents()
    assert d.net_get.isEnabled() and "tor_download" in d.net_boxes
    d.net_boxes["tor_download"].setChecked(False)
    assert not d.net_get.isEnabled() and "switched off" in d.net_get.toolTip()
    d.net_boxes["tor_download"].setChecked(True)
    assert d.net_get.isEnabled() and "dist.torproject.org" in d.net_get.toolTip()
    d.close()


from test_mainwindow import window  # noqa: E402, F401  (the real MainWindow fixture)
