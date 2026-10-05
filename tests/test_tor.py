"""The app's own Tor (soundboard.tor) and Tor mode in soundboard.net / ytdl, without
the Tor network: torrc, the control-port client against a fake control server, the
process manager with a stand-in tor.exe (tests/faketor.py), the job object, failing
closed before Tor is ready, YouTube's Tor blocks, and that nothing leaks around Tor.

Set ONIONBOARD_TEST_TOR=1 to also run the live test (needs Tor, from Get Tor or
scripts/fetch_tor.py's vendor/tor, and the internet): real Tor, check.torproject.org.
Getting Tor itself is tests/test_torget.py."""
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from conftest import process_events
from fakeproxy import Socks5, no_leaks
from soundboard import net, tor, ytdl
from test_net_leaks import NAMES, REAL_GET, Sites   # imported before conftest stubs updates

HERE = Path(__file__).resolve().parent
PT = {"pluggableTransports": {
          "lyrebird": "ClientTransportPlugin meek_lite,obfs4 exec ${pt_path}lyrebird.exe",
          "snowflake": "ClientTransportPlugin snowflake exec ${pt_path}lyrebird.exe"},
      "bridges": {"obfs4": ["obfs4 192.0.2.1:443 AAAA cert=x iat-mode=0",
                            "obfs4 192.0.2.2:80 BBBB cert=y iat-mode=1"],
                  "snowflake": ["snowflake 192.0.2.3:80 CCCC url=https://example.com/"]}}


@pytest.fixture(autouse=True)
def _direct_after():
    yield
    net.set_tor_gate(tor._tor.gate if tor._tor is not None else None)
    net.configure(net.DIRECT)


# ---------------------------------------------------------------- torrc

def test_torrc_is_client_only_on_loopback_with_auto_ports(tmp_path):
    root = tmp_path / "with space #1"
    rc = make = tor.make_torrc(root, owner_pid=1234)
    lines = rc.splitlines()
    for want in ("SocksPort 127.0.0.1:auto", "ControlPort 127.0.0.1:auto",
                 "CookieAuthentication 1", "ClientOnly 1", "SafeLogging 1",
                 "Log notice stdout", "__OwningControllerProcess 1234"):
        assert want in lines
    # paths are quoted with their backslashes escaped (spaces and # survive)
    data = str(root / "data").replace("\\", "\\\\")
    assert f'DataDirectory "{data}"' in lines
    assert "UseBridges 1" not in make and "Bridge " not in make
    assert not any(ln.startswith(("Log info", "Log debug")) for ln in lines)


@pytest.mark.parametrize("kind,plugin,count", [
    ("snowflake", "ClientTransportPlugin snowflake exec pluggable_transports\\lyrebird.exe", 1),
    ("obfs4", "ClientTransportPlugin meek_lite,obfs4 exec pluggable_transports\\lyrebird.exe",
     2)])
def test_torrc_bridges_come_from_pt_config(tmp_path, kind, plugin, count):
    lines = tor.make_torrc(tmp_path, kind, PT).splitlines()
    assert "UseBridges 1" in lines and plugin in lines
    bridges = [ln for ln in lines if ln.startswith("Bridge ")]
    assert len(bridges) == count and all(b.startswith(f"Bridge {kind} ") for b in bridges)


def test_torrc_refuses_a_bridge_kind_it_has_no_lines_for(tmp_path):
    with pytest.raises(ValueError, match="no obfs4"):
        tor.make_torrc(tmp_path, "obfs4", {"pluggableTransports": PT["pluggableTransports"]})


def test_the_shipped_pt_config_has_both_kinds_of_bridges():
    pt = tor.load_pt_config()
    if not pt:
        pytest.skip("vendor/tor isn't here (scripts/fetch_tor.py)")
    for kind in ("snowflake", "obfs4"):
        assert tor.bridge_config(kind, pt)[0] == "UseBridges 1"


# ---------------------------------------------------------------- parsing

def test_bootstrap_status_lines():
    ok = tor.parse_bootstrap('NOTICE BOOTSTRAP PROGRESS=45 TAG=loading_descriptors '
                             'SUMMARY="Loading relay \\"descriptors\\""')
    assert ok == {"progress": 45, "tag": "loading_descriptors",
                  "summary": 'Loading relay "descriptors"', "warning": ""}
    warn = tor.parse_bootstrap('WARN BOOTSTRAP PROGRESS=10 TAG=conn SUMMARY="Connecting" '
                               'WARNING="No route to host" REASON=NOROUTE COUNT=3')
    assert warn["progress"] == 10 and warn["warning"] == "No route to host"
    assert tor.parse_bootstrap("")["progress"] == 0
    assert tor.parse_bootstrap("NOTICE BOOTSTRAP PROGRESS=900")["progress"] == 100


def test_ports_read_back(tmp_path):
    f = tmp_path / "control-port"
    f.write_text("PORT=127.0.0.1:9151\n")
    assert tor.read_control_port(f) == 9151
    assert tor.read_control_port(tmp_path / "missing") is None
    assert tor.parse_listener('"127.0.0.1:9150"') == 9150
    assert tor.parse_listener('"[::1]:9150"') is None


class FakeControl:
    """A control port answering scripted replies, one per command received."""

    def __init__(self, replies: list[bytes]):
        self.got: list[str] = []
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        threading.Thread(target=self._serve, args=(replies,), daemon=True).start()

    def _serve(self, replies):
        c, _ = self.srv.accept()
        f = c.makefile("rb")
        for reply in replies:
            line = f.readline()
            if not line:
                break
            self.got.append(line.decode().rstrip("\r\n"))
            c.sendall(reply)
        c.close()


def test_control_client_speaks_the_protocol():
    srv = FakeControl([
        b"250 OK\r\n",
        b"650 CIRCUIT 1 BUILT\r\n"                       # an event before the reply
        b"250-status/bootstrap-phase=NOTICE BOOTSTRAP PROGRESS=100 SUMMARY=\"Done\"\r\n"
        b"250+config-text=\r\nSocksPort auto\r\n..dotted\r\n.\r\n"
        b"250 OK\r\n",
        b"250 OK\r\n",
        b"552 Unrecognized key \"nope\"\r\n",
    ])
    c = tor.ControlClient(srv.port)
    try:
        c.authenticate(b"\x01\xab" * 16)
        info = c.getinfo("status/bootstrap-phase", "config-text")
        assert tor.parse_bootstrap(info["status/bootstrap-phase"])["progress"] == 100
        assert info["config-text"] == "SocksPort auto\n.dotted"
        c.signal("NEWNYM")
        with pytest.raises(tor.ControlError, match="552"):
            c.getinfo("nope")
    finally:
        c.close()
    assert srv.got == ["AUTHENTICATE " + "01ab" * 16,
                       "GETINFO status/bootstrap-phase config-text", "SIGNAL NEWNYM",
                       "GETINFO nope"]


def test_control_client_notices_a_closed_connection():
    srv = FakeControl([])
    c = tor.ControlClient(srv.port)
    with pytest.raises(OSError):
        c.signal("NEWNYM")
        c.signal("NEWNYM")
    c.close()


# ---------------------------------------------------------------- the manager

class FakeTor(tor.Tor):
    """tor.Tor running tests/faketor.py instead of tor.exe."""

    def _command(self, exe):
        return [sys.executable, str(HERE / "faketor.py")]


def _alive(pid: int) -> bool:
    import ctypes
    k32 = ctypes.WinDLL("kernel32")
    k32.OpenProcess.restype = ctypes.c_void_p
    h = k32.OpenProcess(0x100000, False, pid)   # SYNCHRONIZE
    if not h:
        return False
    try:
        return k32.WaitForSingleObject(ctypes.c_void_p(h), 0) == 0x102   # WAIT_TIMEOUT
    finally:
        k32.CloseHandle(ctypes.c_void_p(h))


def _gone(pid: int, within: float = 5.0) -> bool:
    end = time.monotonic() + within
    while time.monotonic() < end:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return False


def _wait(pred, timeout=10.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


@pytest.fixture
def fake_tor(tmp_path, monkeypatch):
    def make(mode="ok"):
        monkeypatch.setenv("FAKETOR_MODE", mode)
        monkeypatch.setattr(tor, "POLL_S", 0.05)
        monkeypatch.setattr(tor, "STILL_MOVING_S", 0.3)
        t = FakeTor(exe=HERE / "faketor.py", root=tmp_path / "tor", cwd=tmp_path)
        made.append(t)
        return t
    made: list[tor.Tor] = []
    yield make
    for t in made:
        t.stop()


def test_starts_bootstraps_and_hands_net_its_socks_port(fake_tor, tmp_path):
    t = fake_tor()
    seen = []
    t.on_change(lambda: seen.append((t.state, t.progress)))
    t.configure(True)
    assert t.state == tor.OFF                       # nothing needed the network yet
    proxy = t.gate(10)                              # a request: starts it, waits for it
    assert t.state == tor.READY and proxy.kind == "socks5" and proxy.host == "127.0.0.1"
    assert proxy.port == t.socks_port
    assert (tor.STARTING, 50) in seen and seen[-1][0] == tor.READY
    assert "Connected" in t.status_text()
    torrc = (tmp_path / "tor" / "torrc").read_text()
    assert f"__OwningControllerProcess {os.getpid()}" in torrc


def test_new_identity_and_stop(fake_tor, tmp_path, monkeypatch):
    monkeypatch.setattr(tor, "NEWNYM_EVERY_S", 0.0)
    t = fake_tor()
    t.configure(True)
    assert "isn't connected" in t.new_identity()
    t.gate(10)
    assert t.new_identity().startswith("New identity")
    pid = t._proc.pid
    t.stop()
    assert t.state == tor.OFF and _gone(pid)
    assert (tmp_path / "tor" / "data" / "signals").read_text().split() == ["NEWNYM",
                                                                            "SHUTDOWN"]


def test_turning_tor_mode_off_stops_it(fake_tor):
    t = fake_tor()
    t.configure(True)
    t.gate(10)
    pid = t._proc.pid
    t.configure(False)
    assert t.state == tor.OFF and _gone(pid)
    with pytest.raises(net.ProxyError, match="switched off"):
        t.gate(1)


def test_changing_bridges_restarts_a_running_tor(fake_tor, tmp_path, monkeypatch):
    monkeypatch.setattr(tor, "load_pt_config", lambda path=None: PT)
    t = fake_tor()
    t.configure(True)
    t.gate(10)
    first = t._proc.pid
    t.configure(True, "snowflake")
    assert t.gate(10) and t._proc.pid != first and _gone(first)
    assert "Bridge snowflake" in (tmp_path / "tor" / "torrc").read_text()


def test_a_tor_that_dies_reports_why(fake_tor):
    t = fake_tor("die")
    t.configure(True)
    with pytest.raises(net.ProxyError, match="Reading config failed"):
        t.gate(10)
    assert t.state == tor.FAILED and "Reading config failed" in t.status_text()
    # straight after a failure, a request gets that failure without a restart
    with pytest.raises(net.ProxyError, match="Couldn't connect to Tor"):
        t.gate(10)


def test_a_request_waits_on_while_tor_is_still_getting_somewhere(tmp_path, monkeypatch):
    t = tor.Tor(root=tmp_path)
    monkeypatch.setattr(tor, "tor_exe", lambda: tmp_path / "tor.exe")
    monkeypatch.setattr(t, "start", lambda: None)
    monkeypatch.setattr(tor, "STILL_MOVING_S", 0.5)
    t.enabled, t.state, t._run_id = True, tor.STARTING, 1

    def progress():   # 10% more every 0.2 s, then connected
        for pct in range(10, 100, 10):
            time.sleep(0.2)
            t._set(1, progress=pct)
        t.socks_port = 9999
        t._set(1, tor.READY, 100)
    threading.Thread(target=progress, daemon=True).start()
    assert t.gate(0.3).port == 9999      # well past 0.3 s, but it kept moving


def test_a_stuck_bootstrap_fails_closed(fake_tor, monkeypatch):
    t = fake_tor("stall")
    t.configure(True)
    # the fake is a Python process that can take seconds to boot on a busy PC: let it
    # reach its stuck 45% first, or the request below times out still at 0%
    t.start()
    assert _wait(lambda: t.progress == 45)
    with pytest.raises(net.ProxyError, match=r"still connecting \(45%\)"):
        t.gate(1.0)                                  # waits, then fails: never direct
    assert t.state == tor.STARTING and t.progress == 45
    monkeypatch.setattr(tor, "BOOTSTRAP_TIMEOUT_S", 0.0)
    t.stop()
    t.start()
    assert _wait(lambda: t.state == tor.FAILED)
    assert "Connection refused" in t.message and "Hide that I'm using Tor" in t.message


def test_a_tor_that_never_opens_its_control_port(fake_tor, monkeypatch):
    monkeypatch.setattr(tor, "CONTROL_FILE_WAIT_S", 0.5)
    t = fake_tor("hang")
    t.configure(True)
    with pytest.raises(net.ProxyError, match="control port"):
        t.gate(10)
    assert t._proc is None


def test_missing_tor_exe(tmp_path, monkeypatch):
    monkeypatch.setattr(tor, "tor_exe", lambda: None)
    t = tor.Tor(root=tmp_path)
    t.configure(True)
    with pytest.raises(net.ProxyError, match="fetch_tor"):
        t.gate(1)
    assert t.status_text() == tor.NOT_INSTALLED


# ---------------------------------------------------------------- job object

def test_job_object_kills_its_process_when_closed():
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        job = tor.JobObject()
        job.assign(sleeper)
        assert _alive(sleeper.pid)
        job.close()
        assert _gone(sleeper.pid)
    finally:
        if sleeper.poll() is None:
            sleeper.kill()


def test_tor_dies_when_the_app_crashes(tmp_path):
    """A process that put a child in its job object and then dies without cleaning up
    (os._exit, like a crash) takes the child with it."""
    script = tmp_path / "crashy.py"
    script.write_text(
        "import os, subprocess, sys\n"
        f"sys.path.insert(0, {str(HERE.parent)!r})\n"
        "from soundboard.tor import JobObject\n"
        "job = JobObject()\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "job.assign(p)\n"
        "print(p.pid, flush=True)\n"
        "os._exit(3)\n")
    out = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                         timeout=60)
    assert out.returncode == 3, out.stderr
    assert _gone(int(out.stdout.strip()))


# ---------------------------------------------------------------- net in Tor mode

def test_tor_mode_without_tor_fails_closed(monkeypatch):
    net.set_tor_gate(None)
    net.configure(net.TOR)
    with no_leaks(monkeypatch) as leaks:
        with pytest.raises(net.ProxyError, match="Tor isn't available"):
            net.connect("example.com", 443, feature="radio")
        with pytest.raises(OSError):
            net.urlopen("https://example.com/", feature="app_update")
    assert leaks == [] and net.describe() == "through Tor"


def test_requests_before_bootstrap_wait_then_fail_and_never_go_direct(fake_tor, monkeypatch):
    t = fake_tor("stall")
    t.configure(True)
    net.set_tor_gate(t.gate)
    net.configure(net.TOR)
    monkeypatch.setattr(net, "TOR_WAIT_S", 0.8)
    with no_leaks(monkeypatch) as leaks:
        t0 = time.monotonic()
        with pytest.raises(OSError, match="still connecting"):   # urllib wraps it
            net.urlopen("https://example.com/", timeout=5, feature="app_update")
        assert time.monotonic() - t0 >= 0.7      # it waited for Tor first
    assert leaks == [] and "still connecting" in net.last_failure()


def test_loopback_stays_direct_in_tor_mode():
    net.set_tor_gate(None)                      # no Tor at all, yet loopback works
    net.configure(net.TOR)
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    try:
        net.connect("127.0.0.1", srv.getsockname()[1], 5, feature="voice_servers").close()
    finally:
        srv.close()


def test_mode_survives_a_config_round_trip():
    from soundboard.library import clean_setting
    assert clean_setting("net_mode", "tor") == "tor"
    assert clean_setting("net_mode", "i2p") == "proxy"           # unknown: fail closed
    assert clean_setting("tor_bridges", "obfs4") == "obfs4"
    assert clean_setting("tor_bridges", "meek") == "snowflake"   # unknown: still hidden


# ---------------------------------------------------------------- leak test

@pytest.fixture
def tor_socks():
    """Tor mode with a fake SOCKS5 server standing in for Tor's SOCKS port; the sites
    are *.test names only it can resolve."""
    sites = Sites()
    p = Socks5({f"{n}.test": ("127.0.0.1", sites.port) for n in NAMES})
    net.set_tor_gate(lambda _t: net.Proxy("socks5", "127.0.0.1", p.port))
    net.configure(net.TOR)
    yield sites, p
    net.configure(net.DIRECT)
    p.close()
    sites.close()


def test_every_python_connection_goes_through_tor(tor_socks, monkeypatch, app_dir):
    from soundboard import updates
    sites, p = tor_socks
    monkeypatch.setattr(updates, "_get", REAL_GET)
    sites.routes["/releases/latest"] = (b'{"tag_name": "v1"}', "application/json")
    page = ("<button onclick=\"play('/media/sounds/bruh.mp3', 'x')\"></button>"
            '<a href="/en/instant/bruh/" class="instant-link link-secondary">Bruh</a>')
    sites.routes["/en/search/"] = (page.encode(), "text/html")
    monkeypatch.setattr(ytdl, "MYINSTANTS", f"http://myinstants.test:{sites.port}")
    with no_leaks(monkeypatch) as leaks:
        assert updates._get(sites.url("api.github", "/releases/latest"))["tag_name"] == "v1"
        assert [h.title for h in ytdl.search("bruh", source="myinstants")] == ["Bruh"]
        # anything that tried to connect around Tor would raise in no_leaks
        with pytest.raises(AssertionError, match="leaked"):
            socket.create_connection(("192.0.2.1", 80), 1)
    assert leaks == ["connect ('192.0.2.1', 80)"]
    assert p.hosts_asked() == {"api.github.test", "myinstants.test"}


def test_ytdlp_goes_through_tor(tor_socks, monkeypatch, app_dir):
    from test_radio import wav_bytes
    sites, p = tor_socks
    sites.routes["/clip.wav"] = (wav_bytes(1.0), "audio/wav")
    with no_leaks(monkeypatch) as leaks:
        path, _ = ytdl.download_audio(sites.url("media", "/clip.wav"), auto_update=False)
    assert path.read_bytes()[:4] == b"RIFF" and leaks == []
    assert p.hosts_asked() == {"media.test"}


def test_qt_goes_through_tor(qapp, tor_socks, tmp_path):
    from soundboard.radio import RadioDirectory
    from test_radio import api_station
    sites, p = tor_socks
    sites.routes["/json/stations/search"] = (json.dumps([api_station(1)]).encode(),
                                             "application/json")
    d = RadioDirectory(tmp_path, bases=(f"http://radio.test:{sites.port}",))
    got = []
    d.globe_ready.connect(got.append)
    d.load_globe()
    assert process_events(qapp, lambda: got, timeout=15)
    assert p.hosts_asked() == {"radio.test"}


# ---------------------------------------------------------------- YouTube blocks Tor

RELAY = "http://127.0.0.1:1"   # stands in for net.ytdlp_proxy()


def fake_relay(feature, direct=False):
    """net.ytdlp_proxy: the relay, with the direct login for "without Tor"."""
    return f"{RELAY}/{net.DIRECT_LOGIN if direct else ''}{feature}"
BOT = "ERROR: [youtube] abc: Sign in to confirm you’re not a bot. Use --cookies"


@pytest.fixture
def tor_mode(monkeypatch):
    newnyms = []
    monkeypatch.setattr(net, "mode", lambda: net.TOR)
    monkeypatch.setattr(tor, "new_identity", lambda: newnyms.append(1) or "New identity")
    return newnyms


def test_blocked_messages():
    for msg in (BOT, "HTTP Error 429: Too Many Requests", "HTTP Error 403: Forbidden",
                "This content isn't available, try again later."):
        assert ytdl.blocked_by_site(msg)
    assert not ytdl.blocked_by_site("Video unavailable. This video is private")


def test_a_tor_block_gets_new_identities_then_a_clear_error(tor_mode):
    calls = []

    def fetch():
        calls.append(1)
        raise ytdl.FetchError(BOT)
    with pytest.raises(ytdl.TorBlocked, match="without Tor") as e:
        ytdl._over_tor(fetch, "https://www.youtube.com/watch?v=abc")
    assert len(calls) == 1 + ytdl.TOR_TRIES and len(tor_mode) == ytdl.TOR_TRIES
    assert "YouTube turned Tor away" in str(e.value)


def test_a_tor_block_that_clears_on_a_new_identity(tor_mode):
    results = iter([ytdl.FetchError("HTTP Error 429: Too Many Requests"), "ok"])

    def fetch():
        r = next(results)
        if isinstance(r, Exception):
            raise r
        return r
    assert ytdl._over_tor(fetch, "https://youtu.be/abc") == "ok" and len(tor_mode) == 1


def test_other_errors_are_not_retried_over_tor(tor_mode):
    def fetch():
        raise ytdl.FetchError("Video unavailable. This video is private")
    with pytest.raises(ytdl.FetchError, match="private") as e:
        ytdl._over_tor(fetch, "https://youtu.be/abc")
    assert not isinstance(e.value, ytdl.TorBlocked) and tor_mode == []


def test_no_retries_outside_tor_mode(monkeypatch):
    monkeypatch.setattr(tor, "new_identity", lambda: pytest.fail("NEWNYM outside Tor mode"))
    with pytest.raises(ytdl.FetchError) as e:
        ytdl._over_tor(lambda: (_ for _ in ()).throw(ytdl.FetchError(BOT)), "https://x.test")
    assert not isinstance(e.value, ytdl.TorBlocked)


class FakeYDL:
    """yt_dlp.YoutubeDL that records its options and always hits the bot wall."""
    opts: list[dict] = []

    def __init__(self, opts):
        FakeYDL.opts.append(opts)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, *a, **k):
        raise Exception(BOT)   # noqa: TRY002 - yt-dlp's own errors are plain-ish


@pytest.fixture
def fake_ydl(monkeypatch):
    import contextlib
    import types
    FakeYDL.opts = []
    mod = types.SimpleNamespace(YoutubeDL=FakeYDL)
    monkeypatch.setattr(ytdl, "_ydl", lambda: contextlib.nullcontext(mod))
    return FakeYDL.opts


def test_download_never_falls_back_to_direct_on_its_own(tor_mode, fake_ydl, monkeypatch):
    monkeypatch.setattr(net, "ytdlp_proxy", fake_relay)
    monkeypatch.setattr(ytdl, "update", lambda *a: pytest.fail("updated yt-dlp"))
    with pytest.raises(ytdl.TorBlocked):
        ytdl.download_audio("https://www.youtube.com/watch?v=abc")
    assert len(fake_ydl) == 1 + ytdl.TOR_TRIES
    with pytest.raises(ytdl.TorBlocked):
        ytdl.probe("https://www.youtube.com/watch?v=abc")
    with pytest.raises(ytdl.TorBlocked):
        ytdl.search("what is love")
    assert {o["proxy"] for o in fake_ydl} == {fake_relay("sounds_web.youtube")}


def test_without_tor_only_when_asked(tor_mode, fake_ydl, monkeypatch):
    """direct=True is the user's click: one try, through the relay's direct login (so
    the switches still hold, and not the environment's proxy either), no new
    identities."""
    monkeypatch.setattr(net, "ytdlp_proxy", fake_relay)
    for call in (lambda: ytdl.download_audio("https://youtu.be/abc", auto_update=False,
                                             direct=True),
                 lambda: ytdl.probe("https://youtu.be/abc", direct=True),
                 lambda: ytdl.search("what is love", direct=True)):
        fake_ydl.clear()
        with pytest.raises(ytdl.FetchError) as e:
            call()
        assert not isinstance(e.value, ytdl.TorBlocked)
        assert [o["proxy"] for o in fake_ydl] == [fake_relay("sounds_web.youtube", True)]
    assert tor_mode == []


# ---------------------------------------------------------------- the UI

def test_link_bar_offers_without_tor_and_only_its_click_goes_direct(qapp, monkeypatch):
    from soundboard.library import Config
    from soundboard.ui.linkbar import LinkBar
    calls = []

    def fake_download(url, progress=None, auto_update=True, direct=False):
        calls.append(direct)
        if not direct:
            raise ytdl.TorBlocked("YouTube turned Tor away. You can try this one without Tor")
        raise ytdl.DownloadError("stop here")
    monkeypatch.setattr(ytdl, "download_audio", fake_download)
    monkeypatch.setattr(ytdl, "probe", lambda url, direct=False: ("Clip", 3.0))
    bar = LinkBar(engine=None, cfg=Config(), color_for=lambda: "#fff", known_for=dict)
    bar.set_text("https://www.youtube.com/watch?v=abc")
    bar.add()
    assert process_events(qapp, lambda: not bar._busy and calls)
    assert calls == [False] and bar.btn_direct.isVisibleTo(bar)
    assert "without Tor" in bar.info.text()
    bar.btn_direct.click()
    assert process_events(qapp, lambda: not bar._busy and len(calls) == 2)
    assert calls == [False, True] and not bar.btn_direct.isVisibleTo(bar)


def test_search_offers_without_tor(qapp, monkeypatch):
    from soundboard.ui.ytsearch import SearchResults
    calls = []

    def fake_search(query, count=20, source="youtube", direct=False):
        calls.append(direct)
        if not direct:
            raise ytdl.TorBlocked("YouTube turned Tor away")
        return []
    monkeypatch.setattr(ytdl, "search", fake_search)
    panel = SearchResults()
    panel.search("what is love")
    assert process_events(qapp, lambda: calls and not panel.loading.running())
    assert process_events(qapp, lambda: panel.direct_btn.isVisibleTo(panel))
    assert "turned Tor away" in panel.title.text()
    panel.direct_btn.click()
    assert process_events(qapp, lambda: len(calls) == 2 and not panel.loading.running())
    assert calls == [False, True] and not panel.direct_btn.isVisibleTo(panel)


# ---------------------------------------------------------------- live (opt-in)

@pytest.mark.skipif(os.environ.get("ONIONBOARD_TEST_TOR") != "1" or not tor.available(),
                    reason="live Tor test: set ONIONBOARD_TEST_TOR=1 (needs vendor/tor)")
def test_live_tor_bootstraps_and_reaches_check_torproject(tmp_path):
    t = tor.Tor(root=tmp_path / "tor")
    net.set_tor_gate(t.gate)
    t.configure(True, os.environ.get("ONIONBOARD_TEST_TOR_BRIDGES", ""))
    net.configure(net.TOR)
    try:
        with net.urlopen("https://check.torproject.org/api/ip", timeout=60,
                         feature=net.TEST) as r:
            got = json.loads(r.read())
        assert got["IsTor"] is True
    finally:
        t.stop()


# ---------------------------------------------------------------- the switches over Tor

def no_gate(_timeout):
    pytest.fail("asked Tor for a request that's switched off")


def test_a_switched_off_feature_is_refused_before_tor_is_asked(monkeypatch):
    net.set_tor_gate(no_gate)
    net.configure(net.TOR)
    net.configure_features(off=["radio", "sounds_web.youtube"])
    with no_leaks(monkeypatch) as leaks:
        for feature in ("radio", "sounds_web.youtube", None, "nonsense"):
            with pytest.raises(net.FeatureOff):
                net.connect("example.com", 443, feature=feature)
        with pytest.raises(net.FeatureOff, match="Radio is switched off"):
            net.urlopen("https://example.com/", feature="radio")
        with pytest.raises(net.FeatureOff, match="YouTube is switched off"):
            net.urlopen("https://www.youtube.com/", feature="sounds_web.youtube",
                        direct=True)   # "without Tor" skips Tor, not the switch
    assert leaks == []


def test_without_tor_still_needs_the_switch(fake_ydl, monkeypatch):
    monkeypatch.setattr(net, "ytdlp_proxy", fake_relay)
    net.configure_features(off=["sounds_web.youtube"])
    for call in (lambda: ytdl.download_audio("https://youtu.be/abc", direct=True),
                 lambda: ytdl.probe("https://youtu.be/abc", direct=True),
                 lambda: ytdl.search("what is love", direct=True)):
        with pytest.raises(ytdl.SwitchedOff):
            call()
    assert fake_ydl == []


def test_without_tor_goes_direct_only_for_that_request(monkeypatch):
    """connect(direct=True) in Tor mode: straight to the site, and Tor isn't asked."""
    net.set_tor_gate(no_gate)
    net.configure(net.TOR)
    made = []
    monkeypatch.setattr(net.socket, "create_connection",
                        lambda addr, timeout=None: made.append(addr) or "sock")
    assert net.connect("example.com", 443, feature="sounds_web.youtube", direct=True) == "sock"
    assert made == [("example.com", 443)]


def test_the_relays_direct_login_still_follows_the_switch():
    import base64
    net.set_tor_gate(no_gate)
    net.configure(net.TOR)
    net.configure_features(off=["sounds_web"])
    url = net.ytdlp_proxy("sounds_web.youtube", direct=True)
    cred, _, where = url.split("//", 1)[1].rpartition("@")
    assert cred.startswith(net.DIRECT_LOGIN + "sounds_web.youtube:")
    with socket.create_connection(("127.0.0.1", int(where.rsplit(":", 1)[1])), 5) as c:
        auth = base64.b64encode(cred.encode()).decode()
        c.sendall(f"CONNECT www.youtube.com:443 HTTP/1.1\r\nProxy-Authorization: Basic "
                  f"{auth}\r\n\r\n".encode())
        assert c.recv(4096).startswith(b"HTTP/1.1 403")
    assert ("sounds_web.youtube", "www.youtube.com", "off") in net.relay_seen()


def test_offline_mode_never_starts_tor(fake_tor):
    t = fake_tor()
    t.configure(True)
    net.configure_features(offline=True)
    t.start()
    assert t.state == tor.OFF and t._proc is None
    assert "Offline mode" in t.status_text()
    net.set_tor_gate(no_gate)
    net.configure(net.TOR)
    with pytest.raises(net.FeatureOff, match="Offline mode"):
        net.connect("example.com", 443, feature="radio")
    net.configure_features()
    assert t.gate(10).port == t.socks_port   # back online: it starts when needed


def test_offline_mode_stops_a_running_tor(fake_tor, monkeypatch):
    t = fake_tor()
    monkeypatch.setattr(tor, "_tor", t)
    t.configure(True)
    t.gate(10)
    assert t.state == tor.READY
    net.configure_features(offline=True)
    assert _wait(lambda: t.state == tor.OFF)
    net.configure_features()


def test_leaving_offline_refreshes_status_without_starting_tor(fake_tor, monkeypatch):
    t = fake_tor()
    monkeypatch.setattr(tor, "_tor", t)
    t.configure(True)
    shown = []
    t.on_change(lambda: shown.append(t.status_text()))
    net.configure_features(offline=True)
    assert "Offline mode" in shown[-1]
    net.configure_features()
    assert shown[-1] == "Tor starts the next time the app goes online."
    assert t.state == tor.OFF and t._proc is None
