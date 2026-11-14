"""Getting Onion Pocket (soundboard.addons.pocketaddon) and its tab (ui/pocket/pockettab.py).
It's optional: when getting it fails, or the installed copy is broken, the tab offers to
get it again; never an error box, never a stopped app. No network: a local zip stands in
for GitHub, and failures are made up."""
import json
import zipfile

from PySide6.QtWidgets import QLabel

from conftest import process_events
from soundboard.addons import modules, pocketaddon
from soundboard.online import net
from soundboard.core import updates
from soundboard.ui.settings.settings import SettingsDialog
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)
from test_remote_addons import ADDON, _module

MANIFEST = {"id": "onion-pocket", "name": "Onion Pocket", "version": "0.2.0",
            "kind": "remote", "package": "onion_pocket_t", "entry": "onion_pocket_t",
            "api_version": 1, "imports": ["PySide6"]}


def _zip(tmp_path, manifest=MANIFEST):
    path = tmp_path / "OnionPocket-module.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("onion-pocket/module.json", json.dumps(manifest))
        z.writestr("onion-pocket/onion_pocket_t/__init__.py", "def create(host):\n    pass\n")
    return path


def test_get_installs_the_zip(tmp_path, monkeypatch):
    monkeypatch.setenv(pocketaddon.LOCAL_ENV, str(_zip(tmp_path)))
    info = pocketaddon.get(tmp_path / "modules")
    assert info is not None and info.id == "onion-pocket" and info.version == "0.2.0"
    assert (tmp_path / "modules" / "onion-pocket" / "module.json").is_file()


def test_get_failing_is_just_none(tmp_path, monkeypatch):
    monkeypatch.setenv(pocketaddon.LOCAL_ENV, str(tmp_path / "missing.zip"))
    assert pocketaddon.get(tmp_path / "modules") is None
    wrong = dict(MANIFEST, kind="triggers")
    monkeypatch.setenv(pocketaddon.LOCAL_ENV, str(_zip(tmp_path, wrong)))
    assert pocketaddon.get(tmp_path / "modules") is None     # not the add-on it says
    monkeypatch.delenv(pocketaddon.LOCAL_ENV)

    def offline(*a, **k):
        raise OSError("no internet")
    monkeypatch.setattr(updates, "_get", offline)
    assert pocketaddon.get(tmp_path / "modules") is None
    monkeypatch.setattr(updates, "_get", lambda *a, **k: {"tag_name": "v0.2.0", "assets": []})
    assert pocketaddon.get(tmp_path / "modules") is None     # a release without the zip
    assert not (tmp_path / "modules" / "onion-pocket").exists()


def test_only_offered_while_add_ons_may_go_online(monkeypatch):
    monkeypatch.delenv(pocketaddon.LOCAL_ENV, raising=False)
    monkeypatch.setattr(net, "allowed", lambda f: f != pocketaddon.FEATURE)
    assert not pocketaddon.offered()
    monkeypatch.setattr(net, "allowed", lambda f: True)
    assert pocketaddon.offered()


def _tab(w):
    """The Pocket tab, switched on, following the add-ons the window has now."""
    w.tabctl.set_tab_on("pocket", True)
    w.remctl._pocket_card()
    return w.pocket


def _texts(tab):
    return " ".join(lb.text() for lb in tab.findChildren(QLabel) if lb.isVisibleTo(tab))


def test_without_it_the_tab_offers_it_and_a_broken_one_says_why(qapp, window, tmp_path,  # noqa: F811
                                                                monkeypatch):
    monkeypatch.setattr(net, "allowed", lambda f: True)
    info = _module(tmp_path, "onion-pocket", "broken_pocket_t",
                   "def create(host):\n    raise RuntimeError('boom')\n")
    window.remctl.remote_addons = [(info, window.remctl._start_remote_addon(info))]
    tab = _tab(window)
    tab.show()
    assert tab.stack.currentWidget() is tab.get_page and tab.btn_get.isVisibleTo(tab)
    assert "boom" in tab.error.text() and tab.error.isVisibleTo(tab)
    d = SettingsDialog(window, "remote")   # Remote has no card for it now: it's the tab's
    assert not any("Onion Pocket" in lb.text()
                   for lb in d.tabs.currentWidget().widget().findChildren(QLabel))
    d.close()
    window.remctl.remote_addons = []


def test_getting_it_fails_and_the_tab_says_so(qapp, window, monkeypatch):  # noqa: F811
    monkeypatch.setattr(net, "allowed", lambda f: True)
    monkeypatch.setattr(pocketaddon, "get", lambda *a, **k: None)
    window.remctl.remote_addons = []
    tab = _tab(window)
    tab.show()
    tab.btn_get.click()
    assert process_events(qapp, lambda: tab.error.isVisibleTo(tab), timeout=3)
    assert "Couldn't get Onion Pocket" in tab.error.text()
    assert tab.stack.currentWidget() is tab.get_page and window.remctl.remote_addons == []


def test_getting_it_puts_its_own_card_in_the_tab(qapp, window, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(net, "allowed", lambda f: True)
    info = _module(tmp_path, "onion-pocket", "got_pocket_t", ADDON)
    monkeypatch.setattr(pocketaddon, "get", lambda *a, **k: info)
    window.remctl.remote_addons = []
    tab = _tab(window)
    tab.show()
    tab.btn_get.click()
    assert process_events(qapp, lambda: "the test card" in _texts(tab), timeout=3)
    assert [i.id for i, a in window.remctl.remote_addons if a is not None] == ["onion-pocket"]
    assert tab.stack.currentWidget() is tab.have_page
    window.remctl._stop_remote_addons()
    window.remctl.remote_addons = []
    modules._forget("got_pocket_t")


# ---------------------------------------------------------------------- updating it
POCKET = '''
__version__ = "{v}"
from PySide6.QtWidgets import QLabel

stops = []


class Pocket:
    def __init__(self, host):
        if {fail}:
            raise RuntimeError("the new one is broken")
        self.host = host
        self.server = host.server(("status",), (b"<p>hi</p>", {{"Content-Type": "text/html"}}),
                                  "test pocket")
        self.applied = 0

    def apply(self):
        self.applied += 1
        return ""

    def card(self, parent=None):
        card, cv = self.host.card("Test pocket", "")
        cv.addWidget(QLabel("pocket card {v}"))
        return card

    def stop(self):
        stops.append("{v}")
        self.server.stop()


def create(host):
    return Pocket(host)
'''
PKG = "upd_pocket_t"


def _pocket_dir(base, version, fail=False):
    d = base / "onion-pocket"
    (d / PKG).mkdir(parents=True)
    (d / PKG / "__init__.py").write_text(POCKET.format(v=version, fail=fail))
    (d / "module.json").write_text(json.dumps(dict(MANIFEST, version=version, package=PKG,
                                                   entry=PKG)))
    return d


def _pocket_zip(tmp_path, version, fail=False):
    src = _pocket_dir(tmp_path / f"src-{version}", version, fail)
    path = tmp_path / f"OnionPocket-{version}.zip"
    with zipfile.ZipFile(path, "w") as z:
        for f in src.rglob("*"):
            if f.is_file():
                z.write(f, f"onion-pocket/{f.relative_to(src).as_posix()}")
    return path


def _running_old(w, tmp_path):
    info = modules._read(_pocket_dir(tmp_path / "old", "0.1.0"))
    w.remctl.remote_addons = [(info, w.remctl._start_remote_addon(info))]
    assert w.remctl.remote_addons[0][1] is not None, info.error
    w.cfg.remote_addons["onion-pocket"] = {"enabled": True, "port": 8799,
                                                "token": "keep-me"}
    w.pocket_offer = None
    return info, w.remctl.remote_addons[0][1]


def _cleanup(w):
    w.remctl._stop_remote_addons()
    w.remctl.remote_addons = []
    modules._forget(PKG)


def test_latest_and_check_update(tmp_path, monkeypatch):
    monkeypatch.delenv(pocketaddon.LOCAL_ENV, raising=False)
    url = pocketaddon.DOWNLOADS + "v0.1.1/" + pocketaddon.ASSET
    rel = {"tag_name": "v0.1.1", "html_url": "https://evil.example/x",
           "assets": [{"name": pocketaddon.ASSET, "browser_download_url": url,
                       "digest": "sha256:" + "ab" * 32, "size": 40_000}]}
    asked = []
    monkeypatch.setattr(updates, "_get", lambda *a, **k: asked.append(a) or rel)
    monkeypatch.setattr(net, "allowed", lambda f: True)
    o = pocketaddon.latest()
    assert (o.version, o.url, o.page) == ("0.1.1", url, pocketaddon.RELEASES)
    old = modules._read(_pocket_dir(tmp_path / "a", "0.1.0"))
    assert pocketaddon.check_update(old).version == "0.1.1"
    same = modules._read(_pocket_dir(tmp_path / "b", "0.1.1"))
    assert pocketaddon.check_update(same) is None
    assert pocketaddon.check_update(None) is None
    n = len(asked)
    monkeypatch.setattr(net, "allowed", lambda f: f != pocketaddon.FEATURE)
    assert pocketaddon.check_update(old) is None and len(asked) == n   # nothing asked

    def offline(*a, **k):
        raise OSError("no internet")
    monkeypatch.setattr(net, "allowed", lambda f: True)
    monkeypatch.setattr(updates, "_get", offline)
    assert pocketaddon.check_update(old) is None
    monkeypatch.setenv(pocketaddon.LOCAL_ENV, str(_pocket_zip(tmp_path, "0.3.0")))
    assert pocketaddon.check_update(old).version == "0.3.0"


def test_the_tab_finds_the_update_and_swaps_it_in(qapp, window, tmp_path,  # noqa: F811
                                                 monkeypatch):
    monkeypatch.setattr(net, "allowed", lambda f: f != pocketaddon.FEATURE)
    monkeypatch.setenv(pocketaddon.LOCAL_ENV, str(_pocket_zip(tmp_path, "0.2.0")))
    try:
        info, old = _running_old(window, tmp_path)
        stops = __import__(PKG).stops
        tab = _tab(window)
        tab.show()
        assert "pocket card 0.1.0" in _texts(tab)
        tab.btn_check.click()
        assert process_events(qapp, lambda: tab.btn_check.text() == "Update to 0.2.0",
                              timeout=3)
        tab.btn_check.click()
        assert process_events(qapp, lambda: "pocket card 0.2.0" in _texts(tab), timeout=5)
        (new, addon), = window.remctl.remote_addons
        assert new.version == "0.2.0" and addon is not None and addon is not old
        assert stops == ["0.1.0"]                       # the old one let go of its port
        assert window.cfg.remote_addons["onion-pocket"] == {
            "enabled": True, "port": 8799, "token": "keep-me"}
        assert tab.btn_check.text() == "Check for updates"
    finally:
        _cleanup(window)


def test_a_failed_update_keeps_the_old_one_running(qapp, window, tmp_path,  # noqa: F811
                                                   monkeypatch):
    monkeypatch.setattr(net, "allowed", lambda f: True)
    try:
        info, old = _running_old(window, tmp_path)
        monkeypatch.setattr(pocketaddon, "check_update",
                            lambda i: pocketaddon.Offer("0.2.0"))
        monkeypatch.setattr(pocketaddon, "get", lambda *a, **k: None)    # offline, bad zip…
        tab = _tab(window)
        tab.show()
        tab.btn_check.click()
        assert process_events(qapp, lambda: tab.btn_check.text() == "Update to 0.2.0",
                              timeout=3)
        tab.btn_check.click()
        assert process_events(qapp, lambda: tab.error.text() != "", timeout=3)
        assert window.remctl.remote_addons == [(info, old)] and old.server is not None
        assert __import__(PKG).stops == []
        assert "pocket card 0.1.0" in _texts(tab)
    finally:
        _cleanup(window)


def test_a_new_copy_that_wont_start_puts_the_old_one_back(window, tmp_path):  # noqa: F811
    try:
        info, old = _running_old(window, tmp_path)
        mod = __import__(PKG)
        bad = modules._read(_pocket_dir(tmp_path / "new", "0.2.0", fail=True))
        assert window.remctl.load_remote_addon(bad) is None
        assert window.remctl.remote_addons == [(info, old)]
        assert __import__(PKG) is mod and mod.stops == ["0.1.0"] and old.applied == 1
    finally:
        _cleanup(window)
