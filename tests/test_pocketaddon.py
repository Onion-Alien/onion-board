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
