"""A browser the app starts for a link mustn't inherit the relay as its proxy."""
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from soundboard import net
from soundboard.ui import weblinks


def _started(monkeypatch):
    started = []
    monkeypatch.setattr(weblinks.subprocess, "Popen",
                        lambda cmd, **kw: started.append((cmd, kw["env"])))
    return started


def test_links_open_without_the_relay_proxy(qapp, monkeypatch):
    relay = net.relay_url("radio")   # has the per-launch secret
    for k in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY"):
        monkeypatch.setenv(k, relay)
    monkeypatch.setattr(net, "_env_saved", {"http_proxy": None, "https_proxy": None,
                                            "all_proxy": None, "no_proxy": None})
    started = _started(monkeypatch)
    weblinks.install()
    try:
        assert QDesktopServices.openUrl(QUrl("https://discord.gg/abc?x=1&y=2"))
    finally:
        for scheme in weblinks.SCHEMES:
            QDesktopServices.unsetUrlHandler(scheme)
    (cmd, env), = started
    assert cmd[-1] == "https://discord.gg/abc?x=1&y=2"
    assert not any(net._relay.secret in v for v in env.values())
    assert not any(k.lower().endswith("_proxy") for k in env)


def test_windows_links_never_go_to_explorer(monkeypatch):
    """explorer.exe opens Documents for a link with a query string."""
    monkeypatch.setattr(weblinks.sys, "platform", "win32")
    cmd = weblinks.opener("https://tally.so/r/x?version=1.9.23")
    assert "explorer" not in cmd[0].lower()
    assert cmd[-1] == "https://tally.so/r/x?version=1.9.23"


def test_the_users_own_proxy_is_kept(monkeypatch):
    monkeypatch.setenv("https_proxy", net.relay_url("radio"))
    monkeypatch.setattr(net, "_env_saved", {"https_proxy": "http://corp.example.com:8080"})
    started = _started(monkeypatch)
    assert weblinks.open_clean("https://example.com/")
    (_cmd, env), = started
    assert env["https_proxy"] == "http://corp.example.com:8080"
