"""Add-ons that install their updates by themselves (soundboard.addons.autoupdate)."""
from __future__ import annotations

from types import SimpleNamespace

from conftest import process_events
from test_triggerstab import FakeHost, addon_zip, pkg  # noqa: F401 - fixtures

from soundboard.addons import aiaddon, autoupdate, pocketaddon, watchaddon
from soundboard.core import updates
from soundboard.online import net
from soundboard.ui.triggers.triggerstab import TriggersTab


def _cfg(**kw):
    return SimpleNamespace(**{"update_auto": True, "update_check": True, **kw})


def test_only_with_install_updates_by_themselves_on_an_installed_copy(monkeypatch):
    monkeypatch.setattr(updates, "can_install", lambda: True)
    monkeypatch.setattr(net, "allowed", lambda feature: True)
    assert autoupdate.wanted(_cfg())
    assert not autoupdate.wanted(_cfg(update_auto=False))
    assert not autoupdate.wanted(_cfg(update_check=False))
    monkeypatch.setattr(net, "allowed", lambda feature: feature != "addons")
    assert not autoupdate.wanted(_cfg())      # add-ons switched off in Privacy & security
    monkeypatch.setattr(net, "allowed", lambda feature: True)
    monkeypatch.setattr(updates, "can_install", lambda: False)
    assert not autoupdate.wanted(_cfg())      # run from source: git brings them


def _info(version, installed=True):
    return SimpleNamespace(version=version, installed=installed)


def test_check_finds_the_newer_ones_and_leaves_shipped_copies_alone(monkeypatch):
    monkeypatch.setattr(aiaddon, "installed", lambda: _info("0.3.0"))
    monkeypatch.setattr(aiaddon, "removable", lambda info: True)
    monkeypatch.setattr(aiaddon, "latest", lambda: aiaddon.Offer("0.4.0"))
    monkeypatch.setattr(pocketaddon, "installed", lambda: _info("0.2.0"))
    monkeypatch.setattr(pocketaddon, "removable", lambda info: True)
    monkeypatch.setattr(pocketaddon, "check_update", lambda info: pocketaddon.Offer("0.3.0"))
    found = autoupdate.check()
    assert found.ai.version == "0.4.0" and found.pocket.version == "0.3.0"

    monkeypatch.setattr(aiaddon, "removable", lambda info: False)       # came with the app
    monkeypatch.setattr(pocketaddon, "removable", lambda info: False)
    found = autoupdate.check()
    assert found.ai is None and found.pocket is None


def test_check_skips_what_is_current_not_set_up_or_cannot_be_asked(monkeypatch):
    monkeypatch.setattr(aiaddon, "removable", lambda info: True)
    monkeypatch.setattr(aiaddon, "latest", lambda: aiaddon.Offer("0.4.0"))
    monkeypatch.setattr(pocketaddon, "installed", lambda: None)
    monkeypatch.setattr(aiaddon, "installed", lambda: _info("0.4.0"))
    assert autoupdate.check().ai is None                  # already the newest
    monkeypatch.setattr(aiaddon, "installed", lambda: _info("0.3.0", installed=False))
    assert autoupdate.check().ai is None                  # downloaded but never set up

    def offline():
        raise OSError("offline")
    monkeypatch.setattr(aiaddon, "installed", lambda: _info("0.3.0"))
    monkeypatch.setattr(aiaddon, "latest", offline)
    assert autoupdate.check() == autoupdate.Found()       # logged, never raised


def test_a_loaded_onion_watch_updates_itself_for_the_next_start(qapp, tmp_path, addon_zip):  # noqa: F811
    watchaddon.install(addon_zip("0.2.0", "old"), tmp_path / "modules")
    tab = TriggersTab(FakeHost(), [tmp_path / "modules"])
    assert tab.load()
    tab.auto_update(watchaddon.Offer("0.3.0", local=addon_zip("0.3.0", "new")))
    assert process_events(qapp, lambda: "Restart Onion Board" in tab.update_text.text())
    assert watchaddon.installed([tmp_path / "modules"]).version == "0.3.0"
    assert not tab.update_bar.isHidden() and tab.btn_update.isHidden()
    assert tab.btn_later.text() == "OK" and not tab._busy
    tab.shutdown()


def test_a_waiting_onion_watch_loads_the_new_one(qapp, tmp_path, addon_zip):  # noqa: F811
    watchaddon.install(addon_zip("0.2.0", "old"), tmp_path / "modules")
    tab = TriggersTab(FakeHost(), [tmp_path / "modules"], defer=True)
    assert not tab.needed_now() and tab.pending and tab.panel is None   # not shown yet
    tab.auto_update(watchaddon.Offer("0.3.0", local=addon_zip("0.3.0", "new")))
    assert process_events(qapp, lambda: not tab._busy)
    assert tab.info.version == "0.3.0" and tab.update_bar.isHidden()
    assert tab.load() and tab.info.version == "0.3.0"
    tab.shutdown()


def test_a_failed_auto_update_offers_the_update_button(qapp, tmp_path, addon_zip, monkeypatch):  # noqa: F811
    watchaddon.install(addon_zip("0.2.0", "old"), tmp_path / "modules")
    tab = TriggersTab(FakeHost(), [tmp_path / "modules"])
    assert tab.load()

    def broken(offer, *a, **k):
        raise updates.UpdateError("the download stopped")
    monkeypatch.setattr(watchaddon, "fetch", broken)
    tab.auto_update(watchaddon.Offer("0.3.0", url="https://example.com/x.zip"))
    assert process_events(qapp, lambda: not tab._busy)
    assert tab.update_text.text() == "Onion Watch 0.3.0 is out."
    assert not tab.btn_update.isHidden()
    assert watchaddon.installed([tmp_path / "modules"]).version == "0.2.0"
    tab.shutdown()


def test_one_shipped_with_the_app_is_only_offered(qapp, tmp_path, addon_zip, monkeypatch):  # noqa: F811
    watchaddon.install(addon_zip("0.2.0", "old"), tmp_path / "modules")
    tab = TriggersTab(FakeHost(), [tmp_path / "modules"])
    assert tab.load()
    monkeypatch.setattr(watchaddon, "removable", lambda info, base=None: False)
    tab.auto_update(watchaddon.Offer("0.3.0", local=addon_zip("0.3.0", "new")))
    assert not tab._busy and not tab.btn_update.isHidden()
    assert watchaddon.installed([tmp_path / "modules"]).version == "0.2.0"
    tab.shutdown()


def test_a_downloaded_language_missing_its_voice_gets_it(monkeypatch):
    from soundboard.speech import translation
    from soundboard.ui.voice.speechinstall import SpeechInstalls
    es = SimpleNamespace(voice={"url": "x"}, language="es", language_name="Spanish", ready=True,
                         has_voice=False)
    fr = SimpleNamespace(voice={"url": "x"}, language="fr", language_name="French", ready=False,
                         has_voice=False)
    monkeypatch.setattr(translation, "is_downloaded", lambda m: m.ready)
    monkeypatch.setattr(translation, "voice_ready", lambda m: m.has_voice)
    monkeypatch.setattr(net, "offline", lambda: False)
    monkeypatch.setattr(net, "allowed", lambda feature: True)
    got = []
    fake = SimpleNamespace(_dl_busy=None, p=SimpleNamespace(voices_need="", langs=[fr, es]),
                           _download=lambda m, why="": got.append(m.language))
    SpeechInstalls.auto_get_voice(fake)
    assert got == ["es"]                   # French was never downloaded: left alone
    fake.p.voices_need = "get"             # no AI voices to read it yet
    SpeechInstalls.auto_get_voice(fake)
    assert got == ["es"]
