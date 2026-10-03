"""`OnionBoard.exe --set-offline`: the installer's "Offline mode" box (and /OFFLINE=1).
It switches Offline mode on in config.json before the app's first start, keeps every
other setting, and connects to nothing. No window, no network."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from soundboard import app, applog, library, net


@pytest.fixture
def cli(app_dir, monkeypatch):
    monkeypatch.setattr(app, "APP_DIR", app_dir)
    monkeypatch.setattr(applog, "setup", lambda d: d / "log")
    monkeypatch.setattr(net, "urlopen", lambda *a, **k: pytest.fail("went online"))
    yield app_dir
    net.configure_features()


def test_a_first_install_starts_offline(cli):
    assert app.set_offline() == 0
    cfg = library.Config.load()
    assert cfg.net_offline is True
    assert cfg.setup_done is False   # the quick-setup guide still runs on first start
    net.configure_from(cfg)
    assert not any(net.allowed(f) for f in net.FEATURES)
    assert not net.allowed(net.TEST)


def test_an_existing_setup_keeps_its_settings(cli):
    cfg = library.Config()
    cfg.sound_vol, cfg.setup_done, cfg.net_off = 0.42, True, ["radio"]
    assert cfg.save()
    assert app.set_offline() == 0
    cfg = library.Config.load()
    assert cfg.net_offline and cfg.sound_vol == 0.42 and cfg.setup_done
    assert cfg.net_off == ["radio"]
    raw = json.loads((cli / "config.json").read_text(encoding="utf-8"))
    assert raw["net_offline"] is True
    assert app.set_offline() == 0   # running it again changes nothing


def test_a_locked_settings_file_fails_rather_than_overwrite_it(cli, monkeypatch):
    def locked(cls):
        cfg = cls()
        cfg.read_only = True
        return cfg
    monkeypatch.setattr(library.Config, "load", classmethod(locked))
    monkeypatch.setattr(library.Config, "save", lambda self: pytest.fail("saved"))
    assert app.set_offline() == 1


def test_a_failed_save_is_reported(cli, monkeypatch):
    monkeypatch.setattr(library.Config, "save", lambda self: False)
    assert app.set_offline() == 1


def test_the_installer_wires_it_up():
    """The .iss can't run here: at least keep its offline wiring from going missing."""
    iss = Path(__file__).parent.parent / "installer" / "OnionBoard.iss"
    iss = iss.read_text(encoding="utf-8")
    assert "--set-offline" in iss
    assert "{param:OFFLINE|0}" in iss
    for task in ("vbcable", "ffmpeg", "livevoice", "tor"):   # the boxes that download
        assert f"'{task}'" in iss
