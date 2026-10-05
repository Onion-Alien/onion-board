"""The anonymous usage count (soundboard/usage.py): on for new installs, off for
copies from before it existed, off when the installer's box is unticked, never sent
from source, without a key or while switched off, and it says only what SECURITY.md
says it does."""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from soundboard import __version__, app, applog, library, net, reset, usage
from soundboard.library import Config


@pytest.fixture
def sent(app_dir, monkeypatch):
    """The requests the count would make (nothing really goes online)."""
    out = []

    class Answer:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout=None, feature=""):
        out.append((req, feature))
        return Answer()
    monkeypatch.setattr(net, "urlopen", urlopen)
    monkeypatch.setattr(usage, "TOKEN", "count-only-key")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(usage, "threading", SimpleNamespace(Thread=_Inline))
    net.configure_features()
    yield out
    net.configure_features()


class _Inline:
    def __init__(self, target, **kw):
        self.target = target

    def start(self):
        self.target()


def _hits(req) -> list[dict]:
    return json.loads(req.data.decode("utf-8"))["hits"]


def test_a_new_install_counts_once_a_day(sent):
    cfg = Config()
    saved = []
    usage.maybe_send(cfg, lambda: saved.append(1))
    assert len(sent) == 1 and saved == [1]
    req, feature = sent[0]
    assert feature == usage.FEATURE and req.full_url == usage.ENDPOINT
    hits = _hits(req)
    assert [h["path"] for h in hits] == [f"/app/{__version__}", "first-start"]
    assert {h["session"] for h in hits} == {cfg.stats_id} and len(cfg.stats_id) == 32
    # nothing but these fields leaves the PC
    assert all(set(h) <= {"path", "title", "event", "session"} for h in hits)
    usage.maybe_send(cfg)   # the same day: nothing
    assert len(sent) == 1
    cfg.stats_sent -= usage.EVERY_S   # a day later: only the daily one
    usage.maybe_send(cfg)
    assert [h["path"] for h in _hits(sent[1][0])] == [f"/app/{__version__}"]


def test_update_now_is_one_event(sent):
    cfg = Config(stats_sent=1.0)
    usage.maybe_send(cfg, event=usage.update_event("9.9.9"))
    (hit,) = _hits(sent[0][0])
    assert hit["event"] and hit["path"] == f"update-now/{__version__}-to-9.9.9"
    assert cfg.stats_sent == 1.0   # not the daily one


@pytest.mark.parametrize("why", ["switched off", "offline", "source", "no key"])
def test_nothing_is_sent(sent, monkeypatch, why):
    cfg = Config()
    if why == "switched off":
        net.configure_features(["usage_stats"])
    elif why == "offline":
        net.configure_features(offline=True)
    elif why == "source":
        monkeypatch.delattr(sys, "frozen")
    else:
        monkeypatch.setattr(usage, "TOKEN", "")
    usage.maybe_send(cfg)
    usage.maybe_send(cfg, event="update-now/x")
    assert sent == [] and cfg.stats_sent == 0.0


def test_a_failed_send_tries_again_next_time(sent, monkeypatch):
    def down(*a, **k):
        raise OSError("no internet")
    monkeypatch.setattr(net, "urlopen", down)
    cfg = Config()
    usage.maybe_send(cfg)
    assert cfg.stats_sent == 0.0


def test_new_installs_are_on_and_older_configs_are_off(app_dir):
    assert Config.load().net_off == []   # a first start
    Config(net_off=["radio"]).save()
    assert Config.load().net_off == ["radio"]
    raw = Config(net_off=["radio"]).to_raw()
    raw.pop("stats_id")   # saved by a version from before the count
    library.CONFIG_PATH.write_text(json.dumps(raw), encoding="utf-8")
    cfg = Config.load()
    assert cfg.net_off == ["radio", "usage_stats"]
    cfg.save()   # and it stays off once this version saved it
    cfg.net_off.remove("usage_stats")   # until they switch it on
    cfg.save()
    assert Config.load().net_off == ["radio"]


def test_an_old_config_without_privacy_settings_is_off_too(app_dir):
    raw = Config().to_raw()
    for k in (*library.PRIVACY_KEYS, "stats_id"):
        raw.pop(k)
    library.CONFIG_PATH.write_text(json.dumps(raw), encoding="utf-8")
    assert "usage_stats" in Config.load().net_off


def test_a_settings_reset_never_switches_it_back_on(app_dir):
    Config(net_off=["usage_stats", "radio"]).save()
    reset.reset([reset.SETTINGS])
    assert Config.load().net_off == ["usage_stats"]
    Config(net_off=["radio"]).save()
    reset.reset([reset.SETTINGS])
    assert Config.load().net_off == []


@pytest.fixture
def cli(app_dir, monkeypatch):
    monkeypatch.setattr(app, "APP_DIR", app_dir)
    monkeypatch.setattr(applog, "setup", lambda d: d / "log")
    monkeypatch.setattr(net, "urlopen", lambda *a, **k: pytest.fail("went online"))
    yield app_dir


def test_the_installer_box(cli):
    assert app.set_usage_count(False) == 0   # unticked on a first install
    cfg = Config.load()
    assert cfg.net_off == ["usage_stats"] and cfg.setup_done is False
    assert app.set_usage_count(True) == 0   # ticked on a later install
    assert Config.load().net_off == []
    Config(net_off=["radio"], sound_vol=0.42).save()
    assert app.set_usage_count(False) == 0
    cfg = Config.load()
    assert cfg.net_off == ["radio", "usage_stats"] and cfg.sound_vol == 0.42


def test_update_now_fetches_its_own_copy_of_the_installer():
    from soundboard import updates

    def asset(name, sha):
        return {"name": name, "browser_download_url": updates.DOWNLOADS + "v9/" + name,
                "digest": "sha256:" + sha * 64, "size": 5}
    both = {"assets": [asset(updates.ASSET, "a"), asset(updates.UPDATE_ASSET, "b")]}
    assert updates._installer(both)[0].endswith("/" + updates.UPDATE_ASSET)
    old = {"assets": [asset(updates.ASSET, "a")]}   # a release from before it
    assert updates._installer(old) == (updates.DOWNLOADS + "v9/" + updates.ASSET, "a" * 64, 5)
