"""Fixes from a network audit: a Tor that dies after connecting, downloads cut off
when the Connection setting or a switch changes, the relay refusing names that lead
home in Direct mode, bad Content-Length headers, Get Tor's folder swap failing
halfway, and Tor held stopped while it's being updated. No real network: test sites
on 127.0.0.1, reached through tests/fakeproxy.py's SOCKS proxy."""
import hashlib
import http.server
import io
import pathlib
import socket
import threading
import time

import pytest

from fakeproxy import Socks5
from soundboard import net, tor, torget, updates
from test_tor import FakeTor, _wait, fake_tor  # noqa: F401 - fake_tor is a fixture
from test_torget import Response, make_tarball, served  # noqa: F401 - served is a fixture

F = "app_update"


@pytest.fixture(autouse=True)
def _direct_after():
    yield
    net.set_tor_gate(tor._tor.gate if tor._tor is not None else None)
    net.configure(net.DIRECT)


# ---------------------------------------------------------------- Tor dying after 100%

def test_a_tor_that_dies_after_connecting_is_noticed(fake_tor):  # noqa: F811
    t = fake_tor()
    t.configure(True)
    t.gate(10)
    proc = t._proc
    proc.kill()
    proc.wait(5)
    # straight away (the watcher may not have seen it yet): no dead port handed out
    with pytest.raises(net.ProxyError, match="Couldn't connect to Tor"):
        t.gate(1)
    assert _wait(lambda: t.state == tor.FAILED, 5)
    assert "tor.exe stopped" in t.message


# ---------------------------------------------------------------- holding Tor for an update

def test_tor_doesnt_start_while_held(fake_tor):  # noqa: F811
    t = fake_tor()
    t.configure(True)
    with tor.hold():
        with pytest.raises(net.ProxyError, match="being updated"):
            t.gate(1)
        t.start()
        assert t.state == tor.OFF and t._proc is None
    assert tor._holds == 0
    assert t.gate(10).port == t.socks_port


def test_get_tor_holds_tor_while_it_unpacks(served, app_dir):  # noqa: F811
    seen = []
    torget.get(before_unpack=lambda: seen.append(tor._holds))
    assert seen == [1] and tor._holds == 0


# ---------------------------------------------------------------- Content-Length

def test_get_tor_takes_a_bad_content_length_as_unknown(served, monkeypatch, app_dir):  # noqa: F811
    def fake_urlopen(req, timeout=30, feature=None, direct=False):
        r = Response(served.data)
        r.headers = {"Content-Length": "lots"}
        return r
    monkeypatch.setattr(net, "urlopen", fake_urlopen)
    totals = []
    torget.get(lambda done, total: totals.append(total))
    assert totals and set(totals) == {0} and torget.installed()


class _Download(io.BytesIO):
    def __init__(self, data, headers, url="https://example.com/x", after=None):
        super().__init__(data)
        self.headers, self._url, self._after = headers, url, after

    def geturl(self):
        return self._url

    def read(self, n=-1):
        chunk = super().read(n)
        if self._after is not None and chunk:
            self._after()
        return chunk


def test_update_fetch_takes_a_bad_content_length_as_unknown(monkeypatch, tmp_path):
    data = b"x" * 5000
    monkeypatch.setattr(updates, "_open", lambda url, feature: _Download(
        data, {"Content-Length": "nope"}))
    totals = []
    dest = updates.fetch("https://example.com/x", hashlib.sha256(data).hexdigest(),
                         tmp_path / "f.bin", ("https://example.com/",), 10_000, "a file",
                         progress=lambda done, total: totals.append(total))
    assert dest.read_bytes() == data and set(totals) == {0}


def test_update_fetch_stops_when_its_switch_goes_off(monkeypatch, tmp_path):
    data = b"x" * (updates.CHUNK * 3)
    monkeypatch.setattr(updates, "_open", lambda url, feature: _Download(
        data, {}, after=lambda: net.configure_features(off=[updates.FEATURE])))
    with pytest.raises(updates.UpdateError, match="switched off"):
        updates.fetch("https://example.com/x", hashlib.sha256(data).hexdigest(),
                      tmp_path / "f.bin", ("https://example.com/",), len(data) * 2, "a file")
    assert not (tmp_path / "f.bin").exists() and not (tmp_path / "f.bin.part").exists()


# ---------------------------------------------------------------- the folder swap

def test_a_failed_swap_puts_the_working_tor_back(monkeypatch, tmp_path):
    dest = tmp_path / "bin"
    dest.mkdir()
    (dest / "tor.exe").write_bytes(b"the working one")
    real = pathlib.Path.rename

    def rename(self, target):
        if self.name.endswith(".partial"):
            raise PermissionError(13, "Access is denied")
        return real(self, target)
    monkeypatch.setattr(pathlib.Path, "rename", rename)
    with pytest.raises(torget.GetError):
        torget.unpack(make_tarball(), dest)
    assert (dest / "tor.exe").read_bytes() == b"the working one"
    assert not (tmp_path / "bin.old").exists() and not (tmp_path / "bin.partial").exists()


# ---------------------------------------------------------------- open downloads cut off

class SlowSite:
    """Sends a big body's first bytes, then waits (until closed)."""

    def __init__(self):
        self.done = threading.Event()
        srv = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "1000000")
                self.end_headers()
                try:
                    self.wfile.write(b"a" * 1000)
                    self.wfile.flush()
                    srv.done.wait(10)
                except OSError:
                    pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.done.set()
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def slow():
    s = SlowSite()
    p = Socks5({"slow.test": ("127.0.0.1", s.port)})
    yield s, p
    p.close()
    s.close()


@pytest.mark.parametrize("change", ["mode", "switch"])
def test_an_open_download_stops_when_the_setting_changes(slow, change):
    site, socks = slow
    net.configure(net.PROXY, socks.url())
    r = net.urlopen(f"http://slow.test:{site.port}/big", timeout=10, feature=F)
    assert r.read(1000) == b"a" * 1000

    def switch():
        time.sleep(0.3)
        if change == "mode":
            net.configure(net.DIRECT)
        else:
            net.configure_features(off=[F])
    threading.Thread(target=switch, daemon=True).start()
    t = time.monotonic()
    with pytest.raises(net.ProxyError,
                       match="setting changed" if change == "mode" else "switched off"):
        r.read(1000)   # was waiting on the site: cut off, not carried on the old way
    assert time.monotonic() - t < 5
    r.close()


def test_an_untouched_download_carries_on(slow):
    site, socks = slow
    net.configure(net.PROXY, socks.url())
    r = net.urlopen(f"http://slow.test:{site.port}/big", timeout=10, feature=F)
    net.configure_features(off=["radio"])   # another feature's switch
    assert r.read(1000) == b"a" * 1000
    r.close()


# ---------------------------------------------------------------- names leading home

def _relay(raw: bytes) -> bytes:
    port = int(net.relay_url(F).rsplit(":", 1)[1])
    with socket.create_connection(("127.0.0.1", port), timeout=5) as c:
        c.sendall(raw)
        out = b""
        while chunk := c.recv(65536):
            out += chunk
    return out


def _auth() -> str:
    import base64
    cred = net.relay_url(F).split("//", 1)[1].rsplit("@", 1)[0]
    return base64.b64encode(cred.encode()).decode()


def _resolving(monkeypatch, table):
    real = socket.getaddrinfo

    def gai(host, *a, **k):
        if host in table:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (table[host], 0))]
        return real(host, *a, **k)
    monkeypatch.setattr(socket, "getaddrinfo", gai)


def test_direct_relay_refuses_names_that_lead_home(monkeypatch):
    _resolving(monkeypatch, {"router.example": "fd00::1",
                             "me.example": "127.0.0.1", "fe.example": "169.254.0.9"})
    net.configure(net.DIRECT)
    for name in ("router.example", "me.example", "fe.example"):
        out = _relay(f"CONNECT {name}:80 HTTP/1.1\r\n"
                     f"Proxy-Authorization: Basic {_auth()}\r\n\r\n".encode())
        assert out.startswith(b"HTTP/1.1 403") and b"home network" in out, name
        assert (F, name, "local") in net.relay_seen()


def test_names_that_lead_out_arent_refused(monkeypatch):
    _resolving(monkeypatch, {"radio.example": "8.8.8.8"})
    assert not net._name_leads_home("radio.example")
    assert not net._name_leads_home("localhost")       # this PC by name: Direct allows it
    assert not net._name_leads_home("fd00::1")     # an address: decided elsewhere


def test_names_arent_looked_up_through_a_proxy(monkeypatch, slow):
    _site, socks = slow
    looked = []
    monkeypatch.setattr(net, "_name_leads_home", lambda h: looked.append(h) or False)
    net.configure(net.PROXY, socks.url())
    _relay(f"CONNECT nowhere.test:80 HTTP/1.1\r\n"
           f"Proxy-Authorization: Basic {_auth()}\r\n\r\n".encode())
    assert looked == []
