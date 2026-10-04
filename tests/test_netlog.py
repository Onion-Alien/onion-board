"""soundboard.netlog (Settings > Connection > Network activity): every connection the
app makes is listed, with its feature, route and bytes; refused ones as blocked; never
a password or the relay's secret; and the view shows them simply or in detail."""
import time
import urllib.error

import pytest

from fakeproxy import Socks5
from soundboard import net, netlog
from test_net import F, dead_port, login, relay_auth, relay_get, relay_request
from test_net import site, socks  # noqa: F401  (fixtures)


@pytest.fixture(autouse=True)
def fresh():
    netlog.clear()
    yield
    net.configure(net.DIRECT)
    net.configure_features([])
    netlog.clear()


def settled(state=netlog.CLOSED, timeout=5.0) -> list[netlog.Entry]:
    """The entries once none is still open (the relay closes its side last)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        items = netlog.entries()
        if items and all(e.state not in (netlog.CONNECTING, netlog.CONNECTED)
                         for e in items):
            return items
        time.sleep(0.02)
    return netlog.entries()


def test_a_request_is_listed_with_its_route_request_and_bytes(site):  # noqa: F811
    with net.urlopen(f"http://127.0.0.1:{site.port}/plain?x=1", timeout=5,
                     feature="voice_servers") as r:
        assert r.read() == b"hello /plain?x=1"
    [e] = settled()
    assert (e.feature, e.host, e.port, e.how) == ("voice_servers", "127.0.0.1", site.port,
                                                  netlog.APP)
    assert e.route == "this PC" and e.state == netlog.CLOSED
    assert e.requests == ["GET /plain?x=1 → 200 OK"]
    assert e.sent > 0 and e.received >= len(b"hello /plain?x=1")


def test_through_a_proxy_the_route_names_it_but_never_its_password(site):  # noqa: F811
    p = Socks5({"site.test": ("127.0.0.1", site.port)}, login=("user", "s3cret-pw"))
    try:
        net.configure(net.PROXY, login("user", "s3cret-pw", f"127.0.0.1:{p.port}"))
        with net.urlopen(f"http://site.test:{site.port}/p", timeout=5, feature=F) as r:
            r.read()
    finally:
        p.close()
    [e] = settled()
    assert e.host == "site.test" and e.route == f"SOCKS5 proxy 127.0.0.1:{p.port}"
    assert "s3cret-pw" not in netlog.as_text() and "user" not in e.route


def test_a_switched_off_request_is_listed_as_blocked(site):  # noqa: F811
    net.configure_features(["radio"])
    with pytest.raises(net.FeatureOff):
        net.urlopen(f"http://site.test:{site.port}/r", timeout=5, feature="radio")
    with pytest.raises(net.FeatureOff):
        net.connect("example.com", 443, feature="radio")
    a, b = netlog.entries()
    assert (a.host, a.port, a.state) == ("site.test", site.port, netlog.BLOCKED)
    assert (b.host, b.port, b.state) == ("example.com", 443, netlog.BLOCKED)
    assert "Radio is switched off" in a.reason and a.sent == a.received == 0
    assert site.paths == []


def test_a_failure_says_why():
    net.configure(net.PROXY, f"socks5h://127.0.0.1:{(port := dead_port())}")
    with pytest.raises(urllib.error.URLError):
        net.urlopen("http://site.test/", timeout=5, feature=F)
    [e] = netlog.entries()
    assert e.state == netlog.FAILED and "Couldn't reach" in e.reason
    assert e.route == f"SOCKS5 proxy 127.0.0.1:{port}"


def test_the_relay_lists_what_it_carries_but_not_its_secret(site, socks):  # noqa: F811
    net.configure(net.PROXY, socks.url())
    out = relay_get(F, f"http://site.test:{site.port}/via-relay")
    assert out.endswith(b"hello /via-relay")
    auth = f"Proxy-Authorization: Basic {relay_auth()}\r\n"
    out = relay_request(f"CONNECT site.test:{site.port} HTTP/1.1\r\n{auth}\r\n"
                        f"GET /tunnelled HTTP/1.0\r\n\r\n".encode())
    assert out.endswith(b"hello /tunnelled")
    get, tunnel = settled()
    assert get.how == tunnel.how == netlog.RELAY
    assert get.requests == ["GET /via-relay → 200 OK"]
    assert tunnel.requests == ["GET /tunnelled → 200 OK"]   # plain HTTP in a tunnel
    assert tunnel.sent > 0 and tunnel.received > 0
    secret = net.relay_url(F).split(":")[2].split("@")[0]
    assert secret not in netlog.as_text()


def test_the_relay_lists_refusals_too(site, socks):  # noqa: F811
    net.configure(net.PROXY, socks.url())
    net.configure_features(["radio"])
    relay_get("radio", f"http://site.test:{site.port}/off")
    relay_get(F, "http://169.254.1.1/router")
    off, local = netlog.entries()
    assert off.state == local.state == netlog.BLOCKED
    assert "Radio is switched off" in off.reason and "home network" in local.reason


def test_tls_through_the_relay_is_noted_as_unreadable():
    e = netlog.begin(F, "example.com", 443, netlog.RELAY)
    net._sniff(e, b"\x16\x03\x01\x02\x00", from_site=False)
    assert "encrypted end to end" in e.tls and e.requests == []


def test_key_like_query_values_are_masked():
    assert netlog.redact("/s?q=cats&api_key=abc&token=x&page=2") == \
        "/s?q=cats&api_key=•••&token=•••&page=2"
    assert netlog.redact("/plain") == "/plain"


def test_a_login_in_an_absolute_url_is_masked():
    """A proxy client (FFmpeg, Qt) sends the whole URL, login included."""
    url = login("user", "pw", "radio.example.com:8000/live?token=t&x=1", "http")
    assert netlog.redact(url) == "http://•••@radio.example.com:8000/live?token=•••&x=1"
    assert netlog.redact("http://radio.example.com/a@b") == "http://radio.example.com/a@b"
    e = netlog.begin(F, "radio.example.com", 80, netlog.RELAY)
    url = login("me", "s3cret", "radio.example.com/", "http")
    net._sniff(e, f"GET {url} HTTP/1.1\r\n\r\n".encode(), from_site=False)
    assert e.requests and "s3cret" not in netlog.as_text()


def test_an_unexpected_error_doesnt_leave_it_connecting(monkeypatch):
    def broken(*a, **k):
        raise UnicodeError("label too long")   # what IDNA raises for a bad host name
    monkeypatch.setattr(net, "_route", broken)
    with pytest.raises(UnicodeError):
        net.connect("x" * 70 + ".example.com", 443, feature=F)
    [e] = netlog.entries()
    assert e.state == netlog.FAILED and "label too long" in e.reason


def test_the_list_is_capped():
    for i in range(netlog.MAX_ENTRIES + 5):
        netlog.begin(F, f"h{i}.test", 443)
    items = netlog.entries()
    assert len(items) == netlog.MAX_ENTRIES and items[-1].host == f"h{netlog.MAX_ENTRIES + 4}.test"


def test_servers_group_connections():
    netlog.begin(F, "a.test", 443).connected("direct")
    netlog.begin("radio", "a.test", 443).connected("direct")
    netlog.blocked("radio", "b.test", 80, "off")
    a, b = sorted(netlog.servers(), key=lambda s: s.host)
    assert a.connections == 2 and len(a.features) == 2 and a.blocked == 0
    assert b.connections == b.blocked == 1


def test_the_view_shows_simple_and_detailed(qapp):
    from soundboard.ui.netactivity import NetActivity
    w = NetActivity()
    assert "Nothing has gone online" in w.summary.text() and not w.copy.isEnabled()
    e = netlog.begin(F, "api.example.com", 443)
    e.connected("Tor")
    e.request("GET", "/latest?token=abc")
    e.response(200, "OK")
    netlog.blocked("radio", "radio.example.com", 80, "Radio is switched off.")
    w.refresh()
    assert "2 connection(s) to 2 server(s), 1 blocked" in w.summary.text()
    assert w.servers.rowCount() == 2 and w.servers.item(0, 0).text() == "radio.example.com"
    w.detailed.setChecked(True)
    assert w.stack.currentIndex() == 1 and w.conns.rowCount() == 2
    w.conns.selectRow(1)
    text = w.info.toPlainText()
    assert "api.example.com:443" in text and "Route: Tor" in text
    assert "GET /latest?token=••• → 200 OK" in text and "abc" not in text
    w.refresh()                       # nothing changed: the pick stays
    assert w.info.toPlainText() == text
    w._copy()
    assert "api.example.com" in qapp.clipboard().text()
    w._clear()
    assert netlog.entries() == [] and w.conns.rowCount() == 0
    w.deleteLater()


def test_the_view_updates_its_rows_in_place(qapp):
    """New connections push the rows down; the redraw reuses the cells, keeps the pick
    on the same connection and drops a colour a row no longer has. Tooltips are plain
    text (a reason can quote a server)."""
    from soundboard.ui.netactivity import _TONE, NetActivity
    w = NetActivity()
    w.detailed.setChecked(True)
    a = netlog.begin(F, "a.example.com", 443)
    a.failed("<b>bold</b> refusal")
    w.refresh()
    w.conns.selectRow(0)
    cell = w.conns.item(0, 0)
    assert w.conns.item(0, 4).data(_TONE) == "error"
    assert "&lt;b&gt;bold" in w.conns.item(0, 4).toolTip()
    netlog.begin(F, "b.example.com", 443).connected("direct")
    w.refresh()
    assert w.conns.rowCount() == 2 and w.conns.item(0, 0) is cell   # reused
    assert w.conns.item(0, 1).text() == "b.example.com:443"
    assert w.conns.item(0, 4).data(_TONE) is None                   # colour dropped
    assert w.conns.item(1, 4).data(_TONE) == "error"
    assert "a.example.com:443" in w.info.toPlainText()               # still the pick
    w.deleteLater()
