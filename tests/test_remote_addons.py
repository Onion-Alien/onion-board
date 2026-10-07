"""Remote add-ons (soundboard.modules kind "remote", soundboard.ui.remotehost), with a
tiny add-on made for the test: found and loaded at start-up, its card on Settings →
Remote, a broken one left out of Settings, and the lan server it gets from the
host: its page with no key, the API with its key, only its actions, wrong-key
lock-out, only local peers. A real server on a free 127.0.0.1 port stands in for the
PC's address on the Wi-Fi."""
import http.client
import ipaddress
import json
import threading

import pytest
from PySide6.QtWidgets import QLabel

from conftest import process_events
from soundboard import backup, modules, remote
from soundboard.settings import SettingsDialog
from soundboard.ui.remotehost import RemoteHost
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)

ADDON = '''
__version__ = "1"
from PySide6.QtWidgets import QLabel


class Addon:
    def __init__(self, host):
        self.host = host
        self.server = host.server(("status", "sounds", "play"),
                                  (b"<p>hi</p>", {"Content-Type": "text/html"}), "test add-on")
        self.stopped = 0

    def card(self, parent=None):
        card, cv = self.host.card("Test add-on", "what it does")
        cv.addWidget(QLabel("the test card"))
        return card

    def stop(self):
        self.stopped += 1
        self.server.stop()


def create(host):
    return Addon(host)
'''


def _module(base, mid, pkg, code, api=1):
    d = base / mid
    (d / pkg).mkdir(parents=True)
    (d / pkg / "__init__.py").write_text(code)
    (d / "module.json").write_text(json.dumps({
        "id": mid, "name": mid.title(), "version": "1", "kind": "remote", "package": pkg,
        "entry": pkg, "api_version": api, "imports": ["PySide6"]}))
    return modules._read(d)


@pytest.fixture(scope="module")
def addon_dir(tmp_path_factory):
    """One folder for the whole file: Python loads a package once per run."""
    base = tmp_path_factory.mktemp("addons")
    _module(base, "test-remote", "remote_test_addon", ADDON)
    return base


@pytest.fixture
def loaded(window, addon_dir, monkeypatch):  # noqa: F811
    monkeypatch.setattr(modules, "discover",
                        lambda dirs=None: [modules._read(addon_dir / "test-remote")])
    window.remote_addons = window._load_remote_addons()
    (info, addon), = window.remote_addons
    assert info.id == "test-remote" and addon is not None, info.error
    yield addon
    addon.stop()


def call(qapp, srv, path, headers=None, method="GET"):
    """(status, body bytes), with Qt answering while the request waits."""
    out = {}

    def run():
        c = http.client.HTTPConnection(srv.host, srv.port, timeout=5)
        c.request(method, path, headers=dict(headers or {}))
        r = c.getresponse()
        out["r"] = (r.status, r.read())
        c.close()
    t = threading.Thread(target=run)
    t.start()
    assert process_events(qapp, lambda: not t.is_alive())
    return out["r"]


def api(qapp, srv, path, key):
    status, body = call(qapp, srv, path, {"X-Token": key} if key else None, "POST")
    return status, json.loads(body or b"null")


def test_a_remote_add_on_for_a_newer_app_is_refused(tmp_path):
    info = _module(tmp_path, "future", "future_pkg", "", api=modules.REMOTE_API[1] + 1)
    assert "needs a newer Onion Board" in info.error


def test_it_loads_and_gets_its_card_on_settings(qapp, window, loaded):  # noqa: F811
    d = SettingsDialog(window, "remote")
    texts = [lb.text() for lb in d.tabs.currentWidget().widget().findChildren(QLabel)]
    assert "TEST ADD-ON" in texts and "the test card" in texts
    d.close()
    window._stop_remote_addons()
    assert loaded.stopped == 1


def test_its_settings_stay_on_this_pc(window, loaded):  # noqa: F811
    loaded.host.settings["token"] = "k"
    assert window.cfg.remote_addons["test-remote"] == {"token": "k"}
    assert "remote_addons" in backup.LOCAL_SETTINGS
    with pytest.raises(ValueError):
        RemoteHost(window, "x").server(("play", "format_the_disk"))


def test_its_server_page_key_and_short_list(qapp, window, loaded):  # noqa: F811
    srv = loaded.server
    assert srv.start(0, "add-on-key", "127.0.0.1")
    assert call(qapp, srv, "/") == (200, b"<p>hi</p>")       # the page needs no key
    assert api(qapp, srv, "/api/status", "")[0] == 401
    status, sounds = api(qapp, srv, "/api/sounds", "add-on-key")
    assert status == 200 and all("color" in s for s in sounds)
    mic = window.cfg.mic_enabled
    status, body = api(qapp, srv, "/api/mic?on=toggle", "add-on-key")
    assert status == 404 and "/api/mic" not in body["endpoints"]
    assert window.cfg.mic_enabled == mic and not window.remote.running


def test_wrong_keys_lock_an_address_out_for_a_while(qapp, loaded, monkeypatch):
    monkeypatch.setattr(remote, "LOCK_S", 0.3)
    srv = loaded.server
    assert srv.start(0, "add-on-key", "127.0.0.1")
    for _ in range(remote.FAIL_LIMIT):
        assert api(qapp, srv, "/api/status", "guess")[0] == 401
    assert api(qapp, srv, "/api/status", "add-on-key")[0] == 429   # even the right key
    assert process_events(qapp, lambda: not srv.locked("127.0.0.1"), timeout=2)
    assert api(qapp, srv, "/api/status", "add-on-key")[0] == 200


def test_only_local_peers_and_its_own_address(loaded):
    srv = loaded.server
    internet = str(ipaddress.IPv4Address(2 ** 31 + 5))   # an ordinary public address
    assert srv.peer_ok("127.0.0.1") and srv.peer_ok("fe80::1")
    assert not srv.peer_ok(internet) and not srv.peer_ok("nonsense")
    srv.host, srv.port = "pc.example", 7475
    assert srv.host_ok("pc.example:7475") and not srv.host_ok("evil.example:7475")
    assert not srv.host_ok("localhost:7475")
    loop = remote.RemoteControl(lambda a, p: (200, {}))
    assert loop.peer_ok(internet) and not loop.locked("x")   # Stream Deck side unchanged


def test_a_broken_remote_add_on_never_stops_the_app(qapp, window, tmp_path,  # noqa: F811
                                                    monkeypatch):
    info = _module(tmp_path, "broken", "broken_remote_addon",
                   "__version__ = '1'\ndef create(host):\n    raise RuntimeError('boom')\n")
    monkeypatch.setattr(modules, "discover", lambda dirs=None: [info])
    loaded = window._load_remote_addons()
    assert [(i.id, a) for i, a in loaded] == [("broken", None)]
    assert "boom" in info.error
    window.remote_addons = loaded
    d = SettingsDialog(window, "remote")
    texts = " ".join(lb.text() for lb in d.tabs.currentWidget().widget().findChildren(QLabel))
    assert "Broken" not in texts and "boom" not in texts   # optional: just left out
    d.close()


def test_the_key_never_goes_in_the_url_on_the_wifi(qapp, loaded):
    srv = loaded.server
    assert srv.start(0, "add-on-key", "127.0.0.1")
    assert call(qapp, srv, "/api/status?token=add-on-key")[0] == 401
    assert api(qapp, srv, "/api/status", "add-on-key")[0] == 200
    loop = remote.RemoteControl(lambda a, p: (200, {}))   # Stream Deck side unchanged
    loop.token = "k"
    assert loop.authorised({}, {"token": ["k"]})


def test_a_flood_of_connections_cant_pile_up_threads(qapp, loaded, monkeypatch):
    """A device on the Wi-Fi with no key opening connection after connection: past
    the limit they're closed straight away, and once they go a phone gets in again."""
    import socket
    monkeypatch.setattr(remote, "PEER_CONNECTIONS", 3)
    srv = loaded.server
    assert srv.start(0, "add-on-key", "127.0.0.1")
    before = threading.active_count()
    held = [socket.create_connection((srv.host, srv.port), timeout=5) for _ in range(20)]
    for s in held:
        s.sendall(b"GET / HTTP/1.1\r\n")   # half a request: its thread waits for more
    assert process_events(qapp, lambda: threading.active_count() - before >= 3, timeout=2)
    process_events(qapp, lambda: False, timeout=0.3)
    assert threading.active_count() - before <= 3
    closed = waiting = 0
    for s in held:
        s.settimeout(0.2)
        try:
            closed += s.recv(1) == b""
        except TimeoutError:   # one of the few let in, still waiting for its request
            waiting += 1
        except OSError:        # reset: closed too
            closed += 1
    assert waiting <= 3 and closed == 20 - waiting
    for s in held:
        s.close()
    assert process_events(qapp, lambda: not srv._server._open, timeout=3)
    assert call(qapp, srv, "/")[0] == 200


def test_never_on_a_network_windows_calls_public(qapp, window, loaded,  # noqa: F811
                                                 monkeypatch):
    """A café's Wi-Fi: no server, whatever Windows Firewall would let in; and one
    already listening stops when its network turns Public, saying so."""
    from soundboard import netcategory
    srv = loaded.server
    monkeypatch.setattr(netcategory, "category", lambda ip: netcategory.PUBLIC)
    assert not srv.start(0, "add-on-key", "127.0.0.1") and not srv.running
    assert srv.error == remote.public_network()
    monkeypatch.setattr(netcategory, "category", lambda ip: None)   # can't tell: on
    assert srv.start(0, "add-on-key", "127.0.0.1")
    monkeypatch.setattr(netcategory, "category", lambda ip: netcategory.PRIVATE)
    srv._check_network()
    assert srv.running
    monkeypatch.setattr(netcategory, "category", lambda ip: netcategory.PUBLIC)
    srv._check_network()
    assert not srv.running and srv.error == remote.public_network()
    assert "Public" in window.status.text()
    loop = remote.RemoteControl(lambda a, p: (200, {}))   # Stream Deck side: 127.0.0.1
    assert loop.start(0, "k") and loop.running
    loop.stop()


def test_the_network_category_never_raises():
    from soundboard import netcategory
    assert netcategory.category("203.0.113.9") is None   # no adapter has it
    assert netcategory.category("not an address") is None


def _sig(key, request, ts=None, nonce=None):
    import base64
    import hashlib
    import hmac
    import secrets
    import time
    ts = int(time.time()) if ts is None else ts
    nonce = nonce or secrets.token_urlsafe(16)
    mac = hmac.new(key.encode(), f"{ts}.{nonce}.{request}".encode(), hashlib.sha256)
    return f"{ts}.{nonce}." + base64.urlsafe_b64encode(mac.digest()).decode().rstrip("=")


def test_a_signed_request_never_sends_the_key(qapp, loaded):
    """What someone reading the Wi-Fi sees: a signature good for that one request,
    once, now. Sent again, for another request, old, or made with another key: no."""
    import time
    srv = loaded.server
    assert loaded.host.signed_requests
    assert srv.start(0, "add-on-key", "127.0.0.1")
    good = _sig("add-on-key", "POST /api/sounds")
    assert call(qapp, srv, "/api/sounds", {"X-Sig": good}, "POST")[0] == 200
    assert call(qapp, srv, "/api/sounds", {"X-Sig": good}, "POST")[0] == 401    # replayed
    other = _sig("add-on-key", "POST /api/sounds")
    assert call(qapp, srv, "/api/play?id=x", {"X-Sig": other}, "POST")[0] == 401
    srv.succeeded("127.0.0.1")
    old = _sig("add-on-key", "POST /api/status", ts=int(time.time()) - remote.SIG_WINDOW_S - 5)
    status, body = call(qapp, srv, "/api/status", {"X-Sig": old}, "POST")
    assert status == 401 and abs(json.loads(body)["now"] - time.time()) < 5
    assert call(qapp, srv, "/api/status", {"X-Sig": _sig("guess", "POST /api/status")},
                "POST")[0] == 401
    srv.succeeded("127.0.0.1")
    for junk in ("", "x", "1.2.3", "99999999999999.aaaaaaaaaaaaaaaa.x", ". . ."):
        assert not srv.signed(junk, "POST /api/status")
    assert api(qapp, srv, "/api/status", "add-on-key")[0] == 200   # older Pocket pages


def test_remembered_nonces_stay_bounded(loaded, monkeypatch):
    monkeypatch.setattr(remote, "NONCES_MAX", 3)
    srv = loaded.server
    srv.token = "k"
    sigs = [_sig("k", "POST /api/status") for _ in range(4)]
    assert all(srv.signed(s, "POST /api/status") for s in sigs[:3])
    assert not srv.signed(sigs[3], "POST /api/status")   # full of fresh ones: refused
    assert len(srv._nonces) == 3


def test_onion_pocket_can_be_removed_from_its_card_and_add_ons(qapp, window,  # noqa: F811
                                                               monkeypatch):
    """*Remove Onion Pocket…* on its card (Settings → Remote) and on the Add-ons card:
    asks first, stops it, deletes its folder, keeps its settings, and the card turns
    back into *Get Onion Pocket*."""
    from PySide6.QtWidgets import QMessageBox

    from soundboard import library, pocketaddon
    base = library.APP_DIR / "modules"
    info = _module(base, pocketaddon.MODULE_ID, "pocket_remove_test_addon", ADDON)
    monkeypatch.setattr(modules, "discover", lambda dirs=None: [modules._read(info.path)])
    monkeypatch.setattr(pocketaddon, "offered", lambda: True)
    window.pocket_checked = 1e18          # no update check over the network
    window.remote_addons = window._load_remote_addons()
    (info, addon), = window.remote_addons
    window.cfg.remote_addons[info.id] = {"token": "kept"}
    d = SettingsDialog(window, "remote", lazy=False)
    assert not d.pocket_remove.isHidden() and not d.pocket_remove_addons.isHidden()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    d.pocket_remove.click()
    assert info.path.is_dir() and window.remote_addons    # said no: nothing happens
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    d.pocket_remove_addons.click()
    assert not info.path.exists() and window.remote_addons == []
    assert addon.stopped == 1 and window.cfg.remote_addons[info.id] == {"token": "kept"}
    assert d.pocket_remove_addons.isHidden()   # Add-ons: not installed
    assert d.get_pocket.isVisibleTo(d)                     # Remote offers it again
    d.close()


def test_add_ons_card_checks_reinstalls_and_reports(qapp, window,  # noqa: F811
                                                    monkeypatch):
    """Settings → Add-ons & help, Onion Pocket's row: Check for updates turns into
    Update to X when GitHub has a newer one, Reinstall swaps in a fresh copy, and
    Report a problem opens a bug report naming the add-on and its version."""

    from soundboard import feedback, library, net, pocketaddon
    from soundboard.ui import busy
    base = library.APP_DIR / "modules"
    info = _module(base, pocketaddon.MODULE_ID, "pocket_addons_card_test", ADDON)
    monkeypatch.setattr(modules, "discover", lambda dirs=None: [modules._read(info.path)])
    monkeypatch.setattr(net, "allowed", lambda feature: True)
    window.pocket_checked = 1e18
    window.remote_addons = window._load_remote_addons()
    d = SettingsDialog(window, "help")
    b = d.pocket_buttons
    assert b["get"].isHidden() and not b["check"].isHidden()
    monkeypatch.setattr(pocketaddon, "latest",
                        lambda cancelled=None: pocketaddon.Offer("2", "u", "s"))
    b["check"].click()
    assert process_events(qapp, lambda: b["check"].text() == "Update to 2", timeout=3)
    got = []
    monkeypatch.setattr(pocketaddon, "get", lambda offer=None, **k: got.append(offer)
                        or modules._read(info.path))
    b["reinstall"].click()
    assert process_events(qapp, lambda: got and not busy.is_busy(b["reinstall"]), timeout=3)
    assert got == [None] and len(window.remote_addons) == 1
    opened = []
    monkeypatch.setattr(busy, "open_url", lambda url, *a, **k: opened.append(url))
    b["report"].click()
    assert "title=Onion%20Pocket%3A%20" in opened[0] and "Onion%20Pocket%201" in opened[0]
    assert "title" not in feedback.problem_url("1.0")
    d.close()
    window._stop_remote_addons()
