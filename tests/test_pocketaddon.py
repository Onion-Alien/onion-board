"""Getting Onion Pocket (soundboard.pocketaddon) and its card on Settings → Remote. It's
optional: when getting it fails, or the installed copy is broken, the card just isn't
there; never an error box, never a stopped app. No network: a local zip stands in for
GitHub, and failures are made up."""
import json
import zipfile

from PySide6.QtWidgets import QLabel, QPushButton
from shiboken6 import isValid as qt_valid

from conftest import process_events
from soundboard import modules, net, pocketaddon, updates
from soundboard.settings import SettingsDialog
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


def _texts(d):
    return " ".join(lb.text() for lb in d.tabs.currentWidget().widget().findChildren(QLabel))


def _get_button(d):
    return next((b for b in d.tabs.currentWidget().widget().findChildren(QPushButton)
                 if b.text() == "Get Onion Pocket"), None)


def test_without_it_settings_offers_it_and_a_broken_one_is_left_out(qapp, window, tmp_path,  # noqa: F811
                                                                    monkeypatch):
    monkeypatch.setattr(net, "allowed", lambda f: True)
    info = _module(tmp_path, "onion-pocket", "broken_pocket_t",
                   "def create(host):\n    raise RuntimeError('boom')\n")
    window.remote_addons = [(info, window._start_remote_addon(info))]
    d = SettingsDialog(window, "remote")
    assert "boom" in info.error and "boom" not in _texts(d) and "didn't load" not in _texts(d)
    assert _get_button(d) is not None
    d.close()
    monkeypatch.setattr(net, "allowed", lambda f: f != pocketaddon.FEATURE)   # add-ons off
    d = SettingsDialog(window, "remote")
    assert _get_button(d) is None and "Onion Pocket" not in _texts(d)
    d.close()


def test_getting_it_fails_and_the_card_just_goes(qapp, window, monkeypatch):  # noqa: F811
    monkeypatch.setattr(net, "allowed", lambda f: True)
    monkeypatch.setattr(pocketaddon, "get", lambda *a, **k: None)
    window.remote_addons = []
    d = SettingsDialog(window, "remote")
    d.show()
    btn = _get_button(d)
    card = btn.parentWidget()
    btn.click()
    assert process_events(qapp, lambda: not qt_valid(card) or not card.isVisible(),
                          timeout=3)
    assert window.remote_addons == []
    d.close()


def test_getting_it_puts_its_own_card_in_place(qapp, window, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(net, "allowed", lambda f: True)
    info = _module(tmp_path, "onion-pocket", "got_pocket_t", ADDON)
    monkeypatch.setattr(pocketaddon, "get", lambda *a, **k: info)
    window.remote_addons = []
    d = SettingsDialog(window, "remote")
    d.show()
    _get_button(d).click()
    assert process_events(qapp, lambda: "the test card" in _texts(d), timeout=3)
    assert [i.id for i, a in window.remote_addons if a is not None] == ["onion-pocket"]
    assert _get_button(d) is None or not _get_button(d).isVisible()
    d.close()
    window._stop_remote_addons()
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
    w.remote_addons = [(info, w._start_remote_addon(info))]
    assert w.remote_addons[0][1] is not None, info.error
    w.cfg.remote_addons["onion-pocket"] = {"enabled": True, "port": 8799,
                                                "token": "keep-me"}
    w.pocket_offer, w.pocket_checked = None, 0.0
    return info, w.remote_addons[0][1]


def _update_button(d):
    return next((b for b in d.tabs.currentWidget().widget().findChildren(QPushButton)
                 if b.text().startswith("Update Onion Pocket")), None)


def _cleanup(w):
    w._stop_remote_addons()
    w.remote_addons = []
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


def test_settings_offers_the_update_and_swaps_it_in(qapp, window, tmp_path,  # noqa: F811
                                                    monkeypatch):
    monkeypatch.setattr(net, "allowed", lambda f: f != pocketaddon.FEATURE)
    monkeypatch.setenv(pocketaddon.LOCAL_ENV, str(_pocket_zip(tmp_path, "0.2.0")))
    try:
        info, old = _running_old(window, tmp_path)
        stops = __import__(PKG).stops
        d = SettingsDialog(window, "remote")
        d.show()
        assert process_events(qapp, lambda: _update_button(d) is not None
                              and _update_button(d).isVisible(), timeout=3)
        assert _update_button(d).text() == "Update Onion Pocket to 0.2.0"
        _update_button(d).click()
        assert process_events(qapp, lambda: "pocket card 0.2.0" in _texts(d), timeout=5)
        (new, addon), = window.remote_addons
        assert new.version == "0.2.0" and addon is not None and addon is not old
        assert stops == ["0.1.0"]                       # the old one let go of its port
        assert window.cfg.remote_addons["onion-pocket"] == {
            "enabled": True, "port": 8799, "token": "keep-me"}
        assert window.pocket_offer is None
        d.close()
        d = SettingsDialog(window, "remote")             # nothing newer than 0.2.0
        process_events(qapp, lambda: False, timeout=0.3)
        assert _update_button(d) is None or not _update_button(d).isVisible()
        d.close()
    finally:
        _cleanup(window)


def test_a_failed_update_keeps_the_old_one_running(qapp, window, tmp_path,  # noqa: F811
                                                   monkeypatch):
    monkeypatch.setattr(net, "allowed", lambda f: True)
    try:
        info, old = _running_old(window, tmp_path)
        window.pocket_offer = pocketaddon.Offer("0.2.0")
        monkeypatch.setattr(pocketaddon, "get", lambda *a, **k: None)    # offline, bad zip…
        d = SettingsDialog(window, "remote")
        d.show()
        btn = _update_button(d)
        assert btn is not None and btn.isVisible()     # known already: nothing asked
        btn.click()
        assert process_events(qapp, lambda: "Couldn't" in btn.text(), timeout=3)
        assert window.remote_addons == [(info, old)] and old.server is not None
        assert __import__(PKG).stops == []
        assert "pocket card 0.1.0" in _texts(d)
        d.close()
    finally:
        _cleanup(window)


def test_a_new_copy_that_wont_start_puts_the_old_one_back(window, tmp_path):  # noqa: F811
    try:
        info, old = _running_old(window, tmp_path)
        mod = __import__(PKG)
        bad = modules._read(_pocket_dir(tmp_path / "new", "0.2.0", fail=True))
        assert window.load_remote_addon(bad) is None
        assert window.remote_addons == [(info, old)]
        assert __import__(PKG) is mod and mod.stops == ["0.1.0"] and old.applied == 1
    finally:
        _cleanup(window)
