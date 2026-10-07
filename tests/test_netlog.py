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
    netlog._causes.clear()
    yield
    net.configure(net.DIRECT)
    net.configure_features([])
    netlog.clear()
    netlog._causes.clear()


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


def test_each_connection_says_what_caused_it():
    """The latest cause() of a feature (sub-sites share their main one's) is stamped on
    the connections it makes from then on; one already made keeps its own."""
    first = netlog.begin("sounds_web", "i.ytimg.com", 443)
    assert first.cause == "" and "Why: (not recorded)" in netlog.details(first)
    netlog.cause("sounds_web.youtube", f"You searched YouTube for {netlog.quoted('cats')}")
    netlog.cause("app_update", "Automatic update check")
    a = netlog.begin("sounds_web.youtube", "www.youtube.com", 443)
    b = netlog.begin("sounds_web", "i.ytimg.com", 443)
    c = netlog.begin("app_update", "api.github.com", 443)
    netlog.cause("sounds_web", "You clicked Play on “a video”")
    d = netlog.begin("sounds_web", "i.ytimg.com", 443)
    assert a.cause == b.cause == "You searched YouTube for “cats”"
    assert c.cause == "Automatic update check" and first.cause == ""
    assert d.cause == "You clicked Play on “a video”"
    assert "Why: You searched YouTube for “cats”" in netlog.details(a)
    [_gh, ytimg, _yt] = sorted(netlog.servers(), key=lambda s: s.host)
    assert ytimg.causes == ["You clicked Play on “a video”", "You searched YouTube for “cats”"]
    netlog.clear()                          # the list goes, the causes stand
    assert netlog.begin("radio", "r.test", 80).cause == ""
    assert netlog.begin("sounds_web", "x.test", 443).cause.startswith("You clicked Play")


def test_quoted_cuts_long_text_short():
    assert netlog.quoted("  lofi   beats ") == "“lofi beats”"
    q = netlog.quoted("x" * 100, limit=20)
    assert len(q) == 22 and q.endswith("…”")


def test_the_view_shows_simple_and_detailed(qapp):
    from soundboard.ui.netactivity import NetActivity
    w = NetActivity()
    assert "Nothing has gone online" in w.summary.text() and not w.copy.isEnabled()
    netlog.cause(F, "You clicked Check now")
    e = netlog.begin(F, "api.example.com", 443)
    e.connected("Tor")
    e.request("GET", "/latest?token=abc")
    e.response(200, "OK")
    netlog.blocked("radio", "radio.example.com", 80, "Radio is switched off.")
    w.refresh()
    assert "2 connections to 2 servers, 1 blocked" in w.summary.text()
    assert w.servers.rowCount() == 2 and w.servers.item(0, 0).text() == "radio.example.com"
    assert w.servers.item(1, 1).text() == "You clicked Check now"
    w.detailed.setChecked(True)
    assert w.stack.currentIndex() == 1 and w.conns.rowCount() == 2
    assert w.conns.item(1, 2).text() == "You clicked Check now"
    assert w.conns.item(0, 2).text() == "—"
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
    """A new connection goes in as a row at the top: the rows below move down with
    their cells, the pick stays on the same connection, and only rows still open are
    redrawn. Tooltips are plain text (a reason can quote a server)."""
    from soundboard.ui.netactivity import _TONE, NetActivity
    w = NetActivity()
    w.detailed.setChecked(True)
    a = netlog.begin(F, "a.example.com", 443)
    a.failed("<b>bold</b> refusal")
    w.refresh()
    w.conns.selectRow(0)
    cell = w.conns.item(0, 0)
    assert w.conns.item(0, 5).data(_TONE) == "error"
    assert "&lt;b&gt;bold" in w.conns.item(0, 5).toolTip()
    b = netlog.begin(F, "b.example.com", 443)
    b.connected("direct")
    w.refresh()
    assert w.conns.rowCount() == 2 and w.conns.item(1, 0) is cell   # moved down, kept
    assert w.conns.item(0, 1).text() == "b.example.com:443"
    assert w.conns.item(0, 5).data(_TONE) is None
    assert w.conns.item(1, 5).data(_TONE) == "error"
    assert "a.example.com:443" in w.info.toPlainText()               # still the pick
    w.conns.item(1, 1).setText("untouched")   # a finished row isn't looked at again
    b.add_received(5000)
    w.refresh()
    assert w.conns.item(0, 7).text() == netlog.size(5000)            # an open one is
    assert w.conns.item(1, 1).text() == "untouched"
    b.closed()
    netlog.clear()
    netlog.begin(F, "c.example.com", 443)
    w.refresh()
    assert w.conns.rowCount() == 1 and w.conns.item(0, 1).text() == "c.example.com:443"
    w.deleteLater()


def test_radio_switched_off_lists_what_it_refused(qapp, tmp_path):
    """Radio's own gates (a station, a directory lookup) refuse before any connection
    is tried: each is still listed as blocked, with the switch's message."""
    from soundboard.radio import RadioDirectory, RadioPlayer, Station
    net.configure_features([], offline=True)
    errors, fails = [], []
    p = RadioPlayer()
    p.error.connect(errors.append)
    p.play(Station(uuid="u1", name="Test FM", url="https://stream.example.com:8443/live"))
    d = RadioDirectory(tmp_path, bases=("https://dir.example.com",))
    d._get("/json/stations", lambda _raw: None, fails.append)
    a, b = netlog.entries()
    assert (a.host, a.port, a.state) == ("stream.example.com", 8443, netlog.BLOCKED)
    assert (b.host, b.port, b.state) == ("dir.example.com", 443, netlog.BLOCKED)
    assert a.cause == "Playing the radio station “Test FM”"
    assert errors == [a.reason] and a.reason == net.off_message("radio")
    p.deleteLater()
    d.deleteLater()


def test_activity_columns_stay_bounded_and_last_column_is_reachable(qapp):
    from soundboard.ui.netactivity import _put, _table
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractItemView

    table = _table(["Server", "Why", "Used for", "Connections", "Data", "Last"], 1)
    table.resize(580, 260)
    table.setRowCount(1)
    for col in range(6):
        _put(table, 0, col, "A very long value " * 20)
    table.show()
    qapp.processEvents()
    assert table.columnWidth(0) < 250
    assert table.item(0, 0).toolTip()
    # Settings' default width (a ~460 px table): the columns give way, so Last shows
    # unscrolled
    for width in (580, 462):
        table.resize(width, 260)
        qapp.processEvents()
        assert table.horizontalScrollBar().maximum() == 0, width
        assert all(table.columnWidth(c) >= 64 for c in range(6))
    table.resize(380, 260)   # narrower than even that: it scrolls instead
    qapp.processEvents()
    assert table.horizontalScrollBar().maximum() > 0
    table.scrollToItem(table.item(0, 5), QAbstractItemView.PositionAtCenter)
    qapp.processEvents()
    rect = table.visualItemRect(table.item(0, 5))
    assert table.viewport().rect().intersects(rect)
    assert table.textElideMode() == Qt.ElideRight
    table.close()
