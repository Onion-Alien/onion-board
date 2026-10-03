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

def test_direct_mode_is_plain_urllib(site):
    with net.urlopen(f"http://127.0.0.1:{site.port}/plain", timeout=5) as r:
        assert r.read() == b"hello /plain"
    assert net.ytdlp_proxy() is None and not net.active()


def test_socks5_carries_names_unresolved(site, socks, monkeypatch):
    net.configure(net.PROXY, socks.url())
    with no_leaks(monkeypatch) as leaks:
        with net.urlopen(f"http://site.test:{site.port}/a?b=1", timeout=5) as r:
            assert r.read() == b"hello /a?b=1"
    assert leaks == [] and socks.asked == [("site.test", site.port)]


def test_socks5_login(site):
    p = Socks5({"site.test": ("127.0.0.1", site.port)}, login=("user", "pw"))
    try:
        net.configure(net.PROXY, p.url())
        with net.urlopen(f"http://site.test:{site.port}/in", timeout=5) as r:
            assert r.read() == b"hello /in"
        net.configure(net.PROXY, login("user", "wrong", f"127.0.0.1:{p.port}"))
        with pytest.raises(urllib.error.URLError, match="turned down"):
            net.urlopen(f"http://site.test:{site.port}/in", timeout=5)
        net.configure(net.PROXY, f"socks5h://127.0.0.1:{p.port}")
        with pytest.raises(urllib.error.URLError, match="wants a login"):
            net.urlopen(f"http://site.test:{site.port}/in", timeout=5)
    finally:
        p.close()


def test_http_connect_proxy(site, monkeypatch):
    p = HttpConnect({"site.test": ("127.0.0.1", site.port)})
    try:
        net.configure(net.PROXY, p.url())
        with no_leaks(monkeypatch) as leaks:
            with net.urlopen(f"http://site.test:{site.port}/h", timeout=5) as r:
                assert r.read() == b"hello /h"
            with pytest.raises(urllib.error.URLError, match="Bad Gateway"):
                net.urlopen("http://nowhere.test/", timeout=5)
        assert leaks == [] and p.hosts_asked() == {"site.test", "nowhere.test"}
    finally:
        p.close()


def test_an_unreachable_proxy_fails_closed(site, monkeypatch):
    net.configure(net.PROXY, f"socks5h://127.0.0.1:{dead_port()}")
    with no_leaks(monkeypatch) as leaks:
        with pytest.raises(urllib.error.URLError) as e:
            net.urlopen(f"http://site.test:{site.port}/x", timeout=5)
    assert "Couldn't reach the proxy" in str(e.value) and "without it" in str(e.value)
    assert leaks == [] and site.paths == []
    assert "Couldn't reach the proxy" in net.last_failure()


def test_a_bad_address_fails_closed_too(monkeypatch):
    net.configure(net.PROXY, "socks4://127.0.0.1:1")
    assert net.active() and net.proxy() is None
    with no_leaks(monkeypatch), pytest.raises(urllib.error.URLError, match="isn't usable"):
        net.urlopen("https://example.com/", timeout=5)


def test_an_unknown_mode_fails_closed():
    net.configure("tor", "")          # a newer version's mode, read by this one
    assert net.mode() == net.PROXY
    with pytest.raises(OSError, match="isn't usable"):
        net.connect("example.com", 443)


def test_a_server_on_this_pc_stays_direct(site, socks):
    net.configure(net.PROXY, socks.url())
    with net.urlopen(f"http://127.0.0.1:{site.port}/me", timeout=5) as r:
        assert r.read() == b"hello /me"
    with net.urlopen(f"http://localhost:{site.port}/me2", timeout=5) as r:
        assert r.read() == b"hello /me2"
    assert socks.asked == []


def test_a_redirect_cant_leave_http(site, socks):
    net.configure(net.PROXY, socks.url())
    with pytest.raises(urllib.error.URLError):
        net.urlopen(f"http://site.test:{site.port}/away", timeout=5)
    assert socks.hosts_asked() == {"site.test"}


def test_environment_proxies_dont_steer_the_proxy_opener(site, socks, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{dead_port()}")
    net.configure(net.PROXY, socks.url())
    with net.urlopen(f"http://site.test:{site.port}/env", timeout=5) as r:
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
    port = int(net.relay_url().rsplit(":", 1)[1])
    with socket.create_connection(("127.0.0.1", port), timeout=5) as c:
        c.sendall(raw)
        out = b""
        while chunk := c.recv(65536):
            out += chunk
    return out


def relay_auth() -> str:
    url = net.relay_url()
    cred = url.split("//", 1)[1].rsplit("@", 1)[0]
    return base64.b64encode(cred.encode()).decode()


def test_the_relay_needs_its_secret(site, socks):
    net.configure(net.PROXY, socks.url())
    req = f"GET http://site.test:{site.port}/r HTTP/1.1\r\nHost: site.test\r\n"
    assert relay_request((req + "\r\n").encode()).startswith(b"HTTP/1.1 407")
    wrong = base64.b64encode(b"onionboard:guess").decode()
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


def test_proxy_mode_points_ffmpeg_and_children_at_the_relay(socks, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://users-own:1")
    monkeypatch.delenv("NO_PROXY", raising=False)
    net.configure(net.PROXY, socks.url())
    assert os.environ["HTTP_PROXY"] == os.environ["HTTPS_PROXY"] == net.relay_url()
    assert net.ytdlp_proxy() == net.relay_url() and "127.0.0.1" in os.environ["NO_PROXY"]
    net.configure(net.DIRECT)
    assert os.environ["HTTP_PROXY"] == "http://users-own:1"     # the user's own is back
    assert "HTTPS_PROXY" not in os.environ and "NO_PROXY" not in os.environ


def test_a_change_reaches_listeners_and_qt_and_drops_relayed_connections(qapp, site, socks):
    from PySide6.QtNetwork import QNetworkAccessManager, QNetworkProxy
    calls = []

    class L:
        def changed(self):
            calls.append(1)
    lis = L()
    net.on_change(lis.changed)
    nam = QNetworkAccessManager()
    net.apply_qt(nam)
    assert nam.proxy().type() == QNetworkProxy.DefaultProxy
    net.configure(net.PROXY, socks.url())
    assert nam.proxy().type() == QNetworkProxy.HttpProxy and nam.proxy().hostName() == "127.0.0.1"
    assert calls == [1]
    net.configure(net.PROXY, socks.url())          # unchanged: nothing happens
    assert calls == [1]
    port = int(net.relay_url().rsplit(":", 1)[1])
    c = socket.create_connection(("127.0.0.1", port), timeout=5)
    c.sendall(f"CONNECT site.test:{site.port} HTTP/1.1\r\nProxy-Authorization: Basic "
              f"{relay_auth()}\r\n\r\n".encode())
    assert c.recv(100).startswith(b"HTTP/1.1 200")
    net.configure(net.DIRECT)
    assert nam.proxy().type() == QNetworkProxy.DefaultProxy and calls == [1, 1]
    assert c.recv(100) == b""                      # the old route was closed
    c.close()
    del lis
    net.configure(net.PROXY, socks.url())
    assert calls == [1, 1]                         # a dead listener isn't called
