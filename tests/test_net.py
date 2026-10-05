"""soundboard.net: proxy addresses, SOCKS5 / HTTP CONNECT, failing closed, loopback
staying direct, the relay and its secret, and applying a change at once."""
import base64
import http.server
import os
import socket
import threading
import urllib.error
import urllib.request

import pytest

from fakeproxy import HttpConnect, Socks5, no_leaks
from soundboard import net

F = "app_update"   # the feature these tests' requests are for (any switched-on one)


@pytest.fixture(autouse=True)
def direct_after():
    yield
    net.configure(net.DIRECT)


class Site:
    """A plain HTTP server on 127.0.0.1 that says which path it was asked for."""

    def __init__(self):
        self.paths = []
        srv = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                srv.paths.append(self.path)
                if self.path == "/away":
                    self.send_response(302)
                    self.send_header("Location", "ftp://files.test/x")
                    self.end_headers()
                    return
                body = f"hello {self.path}".encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def site():
    s = Site()
    yield s
    s.close()


@pytest.fixture
def socks(site):
    p = Socks5({"site.test": ("127.0.0.1", site.port)})
    yield p
    p.close()


def dead_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ---------------------------------------------------------------- addresses

@pytest.mark.parametrize("text, kind, host, port", [
    ("socks5h://127.0.0.1:9050", "socks5", "127.0.0.1", 9050),
    ("socks5://proxy.example.com:1080", "socks5", "proxy.example.com", 1080),
    ("127.0.0.1:9150", "socks5", "127.0.0.1", 9150),          # bare: SOCKS5, names remote
    ("http://203.0.113.2:8080", "http", "203.0.113.2", 8080),
    ("HTTP://[::1]:3128/", "http", "::1", 3128),
])
def test_proxy_addresses_parse(text, kind, host, port):
    p = net.parse(text)
    assert (p.kind, p.host, p.port) == (kind, host, port)


def login(user: str, pw: str, where: str, scheme: str = "socks5h") -> str:
    cred = f"{user}:{pw}"
    return f"{scheme}://{cred}@{where}"


def test_a_login_is_kept_but_never_described():
    p = net.parse(login("me", "p%40ss", "127.0.0.1:9050"))
    assert (p.user, p.password) == ("me", "p@ss")
    assert p.url() == login("me", "p%40ss", "127.0.0.1:9050")
    net.configure(net.PROXY, login("me", "secretword", "127.0.0.1:9050"))
    assert "secretword" not in net.describe() and "127.0.0.1:9050" in net.describe()


@pytest.mark.parametrize("bad", ["", "   ", "socks4://127.0.0.1:9050", "https://h:1",
                                 "socks5h://127.0.0.1", "http://h:99999", "http://h:80/path",
                                 "socks5h://:9050"])
def test_unusable_addresses_say_why(bad):
    with pytest.raises(ValueError) as e:
        net.parse(bad)
    assert str(e.value)


@pytest.mark.parametrize("host, local", [
    ("127.0.0.1", True), ("127.8.9.1", True), ("::1", True), ("[::1]", True),
    ("localhost", True), ("LOCALHOST", True), ("::ffff:127.0.0.1", True),
    ("203.0.113.1", False), ("example.com", False), ("evil.localhost", False), ("", False),
])
def test_loopback_is_recognised_without_a_lookup(host, local, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: pytest.fail("looked up"))
    assert net.is_loopback(host) is local


# ---------------------------------------------------------------- urllib

def test_direct_mode_connects_straight(site):
    with net.urlopen(f"http://127.0.0.1:{site.port}/plain", timeout=5, feature=F) as r:
        assert r.read() == b"hello /plain"
    # yt-dlp still goes through the relay (it's where a switched-off site is stopped)
    assert net.ytdlp_proxy("sounds_web").startswith("http://sounds_web:")
    assert not net.active()


def test_socks5_carries_names_unresolved(site, socks, monkeypatch):
    net.configure(net.PROXY, socks.url())
    with no_leaks(monkeypatch) as leaks:
        with net.urlopen(f"http://site.test:{site.port}/a?b=1", timeout=5, feature=F) as r:
            assert r.read() == b"hello /a?b=1"
    assert leaks == [] and socks.asked == [("site.test", site.port)]


def test_socks5_login(site):
    p = Socks5({"site.test": ("127.0.0.1", site.port)}, login=("user", "pw"))
    try:
        net.configure(net.PROXY, p.url())
        with net.urlopen(f"http://site.test:{site.port}/in", timeout=5, feature=F) as r:
            assert r.read() == b"hello /in"
        net.configure(net.PROXY, login("user", "wrong", f"127.0.0.1:{p.port}"))
        with pytest.raises(urllib.error.URLError, match="turned down"):
            net.urlopen(f"http://site.test:{site.port}/in", timeout=5, feature=F)
        net.configure(net.PROXY, f"socks5h://127.0.0.1:{p.port}")
        with pytest.raises(urllib.error.URLError, match="wants a login"):
            net.urlopen(f"http://site.test:{site.port}/in", timeout=5, feature=F)
    finally:
        p.close()


def test_http_connect_proxy(site, monkeypatch):
    p = HttpConnect({"site.test": ("127.0.0.1", site.port)})
    try:
        net.configure(net.PROXY, p.url())
        with no_leaks(monkeypatch) as leaks:
            with net.urlopen(f"http://site.test:{site.port}/h", timeout=5, feature=F) as r:
                assert r.read() == b"hello /h"
            with pytest.raises(urllib.error.URLError, match="Bad Gateway"):
                net.urlopen("http://nowhere.test/", timeout=5, feature=F)
        assert leaks == [] and p.hosts_asked() == {"site.test", "nowhere.test"}
    finally:
        p.close()


def test_an_unreachable_proxy_fails_closed(site, monkeypatch):
    net.configure(net.PROXY, f"socks5h://127.0.0.1:{dead_port()}")
    with no_leaks(monkeypatch) as leaks:
        with pytest.raises(urllib.error.URLError) as e:
            net.urlopen(f"http://site.test:{site.port}/x", timeout=5, feature=F)
    assert "Couldn't reach the proxy" in str(e.value) and "without it" in str(e.value)
    assert leaks == [] and site.paths == []
    assert "Couldn't reach the proxy" in net.last_failure()


def test_a_bad_address_fails_closed_too(monkeypatch):
    net.configure(net.PROXY, "socks4://127.0.0.1:1")
    assert net.active() and net.proxy() is None
    with no_leaks(monkeypatch), pytest.raises(urllib.error.URLError, match="isn't usable"):
        net.urlopen("https://example.com/", timeout=5, feature=F)


def test_an_unknown_mode_fails_closed():
    net.configure("i2p", "")          # a newer version's mode, read by this one
    assert net.mode() == net.PROXY
    with pytest.raises(OSError, match="isn't usable"):
        net.connect("example.com", 443, feature=F)


def test_a_server_on_this_pc_stays_direct(site, socks):
    net.configure(net.PROXY, socks.url())
    with net.urlopen(f"http://127.0.0.1:{site.port}/me", timeout=5, feature=F) as r:
        assert r.read() == b"hello /me"
    with net.urlopen(f"http://localhost:{site.port}/me2", timeout=5, feature=F) as r:
        assert r.read() == b"hello /me2"
    assert socks.asked == []


def test_a_redirect_cant_leave_http(site, socks):
    net.configure(net.PROXY, socks.url())
    with pytest.raises(urllib.error.URLError):
        net.urlopen(f"http://site.test:{site.port}/away", timeout=5, feature=F)
    assert socks.hosts_asked() == {"site.test"}


def test_environment_proxies_dont_steer_the_proxy_opener(site, socks, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{dead_port()}")
    net.configure(net.PROXY, socks.url())
    with net.urlopen(f"http://site.test:{site.port}/env", timeout=5, feature=F) as r:
        assert r.read() == b"hello /env"


def test_the_test_button_tries_the_typed_address(site, socks):
    net.configure(net.DIRECT)
    msg = net.test(socks.url(), ("site.test", site.port), timeout=5)
    assert msg.startswith("It works") and socks.asked == [("site.test", site.port)]
    assert not net.active()                       # testing doesn't switch anything
    with pytest.raises(OSError, match="unreachable"):
        net.test(socks.url(), ("nowhere.test", 443), timeout=5)
    with pytest.raises(ValueError):
        net.test("nonsense://x", timeout=5)


# ---------------------------------------------------------------- relay

def relay_request(raw: bytes) -> bytes:
    port = int(net.relay_url(F).rsplit(":", 1)[1])
    with socket.create_connection(("127.0.0.1", port), timeout=5) as c:
        c.sendall(raw)
        out = b""
        while chunk := c.recv(65536):
            out += chunk
    return out


def relay_auth() -> str:
    url = net.relay_url(F)
    cred = url.split("//", 1)[1].rsplit("@", 1)[0]
    return base64.b64encode(cred.encode()).decode()


def test_the_relay_needs_its_secret(site, socks):
    net.configure(net.PROXY, socks.url())
    req = f"GET http://site.test:{site.port}/r HTTP/1.1\r\nHost: site.test\r\n"
    assert relay_request((req + "\r\n").encode()).startswith(b"HTTP/1.1 407")
    wrong = base64.b64encode(f"{F}:guess".encode()).decode()
    assert relay_request((req + f"Proxy-Authorization: Basic {wrong}\r\n\r\n").encode()
                         ).startswith(b"HTTP/1.1 407")
    assert socks.asked == [] and site.paths == []
    ok = relay_request((req + f"Proxy-Authorization: Basic {relay_auth()}\r\n\r\n").encode())
    assert ok.startswith(b"HTTP/1.0 200") and ok.endswith(b"hello /r")
    assert socks.asked == [("site.test", site.port)]


def test_the_relay_tunnels_connect_and_refuses_local_targets(site, socks):
    net.configure(net.PROXY, socks.url())
    auth = f"Proxy-Authorization: Basic {relay_auth()}\r\n"
    out = relay_request(f"CONNECT site.test:{site.port} HTTP/1.1\r\n{auth}\r\n"
                        f"GET /t HTTP/1.0\r\n\r\n".encode())
    assert out.startswith(b"HTTP/1.1 200 Connection established") and out.endswith(b"hello /t")
    for target in ("127.0.0.1:80", "169.254.1.1:80", "[::1]:80", "router.local:80"):
        out = relay_request(f"CONNECT {target} HTTP/1.1\r\n{auth}\r\n".encode())
        assert out.startswith(b"HTTP/1.1 403"), target
    out = relay_request(f"CONNECT nowhere.test:443 HTTP/1.1\r\n{auth}\r\n".encode())
    assert out.startswith(b"HTTP/1.1 502") and b"unreachable" in out


def test_every_mode_points_ffmpeg_at_the_relay_as_the_radio(socks, monkeypatch):
    monkeypatch.setattr(net, "_env_saved", None)
    monkeypatch.setenv("HTTP_PROXY", "http://users-own:1")
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("ALL_PROXY", raising=False)
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1,users-own.example")
    for mode in (net.PROXY, net.DIRECT):
        net.configure(mode, socks.url())
        assert os.environ["HTTP_PROXY"] == os.environ["HTTPS_PROXY"] == net.relay_url("radio")
        # nothing FFmpeg goes straight to: a station redirecting to this PC (127.0.0.1)
        # would step around the relay
        assert "NO_PROXY" not in os.environ
    assert net.ytdlp_proxy("sounds_web") == net.relay_url("sounds_web")
    # a program that outlives the app (the update installer) gets the user's own
    own = net.own_env()
    assert own["http_proxy"] == "http://users-own:1"
    assert own["no_proxy"] == "localhost,127.0.0.1,users-own.example"
    assert not {k.upper() for k in own} & {"HTTPS_PROXY", "ALL_PROXY"}
    # a child process that goes online still reaches this PC directly
    assert "127.0.0.1" in net.child_env("addons")["no_proxy"]


def test_a_change_reaches_listeners_and_qt_and_drops_relayed_connections(qapp, site, socks):
    from PySide6.QtNetwork import QNetworkAccessManager, QNetworkProxy
    calls = []

    class L:
        def changed(self):
            calls.append(1)
    lis = L()
    net.on_change(lis.changed)
    nam = QNetworkAccessManager()
    net.apply_qt(nam, F)
    # the relay, in every mode, with the feature as its user name
    assert nam.proxy().type() == QNetworkProxy.HttpProxy and nam.proxy().user() == F
    net.configure(net.PROXY, socks.url())
    assert nam.proxy().type() == QNetworkProxy.HttpProxy and nam.proxy().hostName() == "127.0.0.1"
    assert calls == [1]
    net.configure(net.PROXY, socks.url())          # unchanged: nothing happens
    assert calls == [1]
    port = int(net.relay_url(F).rsplit(":", 1)[1])
    c = socket.create_connection(("127.0.0.1", port), timeout=5)
    c.sendall(f"CONNECT site.test:{site.port} HTTP/1.1\r\nProxy-Authorization: Basic "
              f"{relay_auth()}\r\n\r\n".encode())
    assert c.recv(100).startswith(b"HTTP/1.1 200")
    net.configure(net.DIRECT)
    assert nam.proxy().type() == QNetworkProxy.HttpProxy and calls == [1, 1]
    assert c.recv(100) == b""                      # the old route was closed
    c.close()
    del lis
    net.configure(net.PROXY, socks.url())
    assert calls == [1, 1]                         # a dead listener isn't called


# ---------------------------------------------------------------- switches

def test_switches_allow_and_refuse():
    assert all(net.allowed(f) for f in net.FEATURES) and net.allowed("sounds_web.youtube")
    for bad in (None, "", "nonsense", "radio.youtube", "sounds_web.nowhere"):
        assert not net.allowed(bad)                # unknown keys never may
    net.configure_features(["radio", "sounds_web.soundcloud", "from-a-newer-version"])
    assert not net.allowed("radio") and net.allowed("app_update")
    assert not net.allowed("sounds_web.soundcloud") and net.allowed("sounds_web.youtube")
    net.configure_features(["sounds_web"])         # a site needs its feature on too
    assert not net.allowed("sounds_web.youtube")
    net.configure_features([], offline=True)
    assert not any(net.allowed(f) for f in [*net.FEATURES, net.TEST]) and not net.any_allowed()
    assert "Offline mode" in net.off_message("radio")
    net.configure_features()
    assert net.allowed(net.TEST)


@pytest.mark.parametrize("off, feature, says", [
    (["radio"], "radio", "Radio is switched off in Settings > Privacy & security."),
    (["setup_downloads"], "setup_downloads", "vb-audio.com"),
    (["sounds_web.myinstants"], "sounds_web.myinstants", "Getting sounds from Myinstants"),
    ([], None, "didn't say which setting"),
    ([], "made-up", "didn't say which setting"),
])
def test_an_off_or_untagged_request_is_refused_before_any_lookup(off, feature, says, site,
                                                                 socks, monkeypatch):
    net.configure_features(off)
    for mode in (net.DIRECT, net.PROXY):
        net.configure(mode, socks.url())
        with no_leaks(monkeypatch) as leaks:
            with pytest.raises(net.FeatureOff, match=says):
                net.urlopen(f"http://site.test:{site.port}/x", timeout=5, feature=feature)
            with pytest.raises(net.FeatureOff, match=says):
                net.connect("example.com", 443, feature=feature)
        assert leaks == [] and socks.asked == [] and site.paths == []
    assert says in net.last_failure()       # what Qt / FFmpeg errors are explained with


def test_this_pc_stays_reachable_while_offline_but_not_untagged(site):
    net.configure_features([], offline=True)
    with net.urlopen(f"http://127.0.0.1:{site.port}/here", timeout=5,
                     feature="voice_servers") as r:
        assert r.read() == b"hello /here"
    with pytest.raises(net.FeatureOff):
        net.urlopen(f"http://127.0.0.1:{site.port}/here", timeout=5)


def test_the_test_button_is_refused_while_offline(site, socks):
    net.configure_features([], offline=True)
    with pytest.raises(net.FeatureOff, match="Offline"):
        net.test(socks.url(), ("site.test", site.port), timeout=5)
    assert socks.asked == []


def relay_get(feature: str, url: str) -> bytes:
    auth = base64.b64encode(net.relay_url(feature).split("//", 1)[1].rsplit("@", 1)[0]
                            .encode()).decode()
    return relay_request(f"GET {url} HTTP/1.1\r\nHost: x\r\nProxy-Authorization: Basic "
                         f"{auth}\r\n\r\n".encode())


@pytest.mark.parametrize("mode", [net.DIRECT, net.PROXY])
def test_the_relay_refuses_a_switched_off_features_login(mode, site, socks, monkeypatch):
    net.configure(mode, socks.url())
    net.configure_features(["radio"])
    # in Direct mode the relay connects straight: let it reach the test site by name
    real = socket.create_connection
    monkeypatch.setattr(socket, "create_connection", lambda addr, *a, **k: real(
        ("127.0.0.1", addr[1]) if addr[0] == "site.test" else addr, *a, **k))
    off = relay_get("radio", f"http://site.test:{site.port}/radio")
    assert off.startswith(b"HTTP/1.1 403") and b"Radio is switched off" in off
    assert site.paths == [] and socks.asked == []
    on = relay_get("app_update", f"http://site.test:{site.port}/upd")
    assert on.startswith(b"HTTP/1.0 200") and site.paths == ["/upd"]
    unknown = relay_get("someone-else", f"http://site.test:{site.port}/who")
    assert unknown.startswith(b"HTTP/1.1 403") and site.paths == ["/upd"]
    assert ("radio", "site.test", "off") in net.relay_seen()


def test_switching_off_closes_only_that_features_relayed_connections(qapp, site, socks):
    calls = []

    class L:
        def changed(self):
            calls.append(1)
    lis = L()
    net.on_change(lis.changed)
    net.configure(net.PROXY, socks.url())
    calls.clear()
    port = int(net.relay_url("radio").rsplit(":", 1)[1])

    def tunnel(feature):
        auth = base64.b64encode(net.relay_url(feature).split("//", 1)[1].rsplit("@", 1)[0]
                                .encode()).decode()
        c = socket.create_connection(("127.0.0.1", port), timeout=5)
        c.sendall(f"CONNECT site.test:{site.port} HTTP/1.1\r\nProxy-Authorization: Basic "
                  f"{auth}\r\n\r\n".encode())
        assert c.recv(100).startswith(b"HTTP/1.1 200")
        return c
    radio, upd = tunnel("radio"), tunnel("app_update")
    net.configure_features(["radio"])
    assert calls == [1]                     # listeners hear about it (a station stops)
    assert radio.recv(100) == b""          # the radio's route was closed...
    upd.sendall(b"GET /still HTTP/1.0\r\n\r\n")
    got = b""
    while chunk := upd.recv(1000):
        got += chunk
    assert got.endswith(b"hello /still")   # ...the updater's wasn't
    radio.close()
    upd.close()
    net.configure_features(["radio"])      # unchanged: nothing happens
    assert calls == [1]


def test_child_processes_get_their_own_features_login(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://users-own:1")
    env = net.child_env("addons")
    assert env["http_proxy"] == env["https_proxy"] == net.relay_url("addons")
    assert "HTTP_PROXY" not in env and "HF_HUB_OFFLINE" not in env
    net.configure_features(["voices"])
    env = net.child_env("voices")
    assert env["http_proxy"] == net.relay_url("voices") and env["HF_HUB_OFFLINE"] == "1"


def test_https_handshake_matches_stock_urllib():
    """Cloudflare (Myinstants) refused the app's searches with 403 because its TLS
    handshake lacked what stock urllib sends: ALPN http/1.1 and post-handshake auth."""
    import http.client
    https = next(h for h in net._opener("search").handlers
                 if isinstance(h, urllib.request.HTTPSHandler))
    ours = https._context
    stock = http.client._create_https_context(http.client.HTTPConnection._http_vsn)
    assert ours.post_handshake_auth is True and stock.post_handshake_auth is True
    assert ours.verify_mode == stock.verify_mode and ours.check_hostname
    assert ours.minimum_version == stock.minimum_version


def test_the_relay_cuts_a_side_that_stopped_reading(monkeypatch):
    monkeypatch.setattr(net, "PIPE_SEND_S", 0.5)
    a, client = socket.socketpair()
    b, site = socket.socketpair()
    for s in (b, site):
        s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
    done = threading.Event()

    def run():
        with pytest.raises(OSError):
            net._Relay._pipe(a, b)
        done.set()
    threading.Thread(target=run, daemon=True).start()
    client.setblocking(False)
    chunk = b"x" * 65536
    for _ in range(400):            # the site never reads what the client sends
        try:
            client.send(chunk)
        except BlockingIOError:
            pass
        if done.wait(0.01):
            break
    assert done.wait(5)             # timed out instead of waiting for ever
    for s in (a, b, client, site):
        s.close()
