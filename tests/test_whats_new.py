"""What's new after an update (ui/whatsnew.py) and the privacy settings surviving an
older version (library.Config: privacy.json). The real MainWindow, offscreen."""
import json

import pytest

from soundboard import __version__, library, net
from soundboard.library import Config
from soundboard.ui import whatsnew
from test_mainwindow import window as main_window  # noqa: F401 - the real window, offscreen


@pytest.fixture
def window(main_window):  # noqa: F811
    main_window.cfg.setup_done = True
    main_window.show()
    return main_window


@pytest.fixture
def shown(monkeypatch):
    """Every WhatsNewDialog exec'd: (dialog's heading texts, updated). Answer with the
    page in `shown.press` ("" = Close)."""
    class Shown(list):
        press = ""
    out = Shown()

    def exec_(dlg):
        from PySide6.QtWidgets import QLabel
        out.append([lbl.text() for lbl in dlg.findChildren(QLabel)])
        if out.press:
            dlg.settings_btn.click()
        return 0
    monkeypatch.setattr(whatsnew.WhatsNewDialog, "exec", exec_)
    return out


def test_an_upgraded_config_sees_it_once_and_its_button_opens_the_newest_page(window, shown,
                                                                              monkeypatch):
    opened = []
    monkeypatch.setattr(window, "open_settings", lambda page="privacy": opened.append(page))
    window.cfg.whats_new_seen = ""   # as loaded from an older version's config
    shown.press = "tabs"
    window.after_update()
    assert len(shown) == 1 and any("Privacy & security" in t for t in shown[0])
    assert any("Update Onion Pocket" in t for t in shown[0])
    assert opened == ["tabs"]   # the newest note with a Settings page
    assert window.cfg.whats_new_seen == __version__
    window.after_update()   # the next start: nothing new
    assert len(shown) == 1


def test_after_an_update_it_replaces_the_plain_updated_note(window, shown, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    boxes = []
    monkeypatch.setattr(QMessageBox, "exec", lambda box: boxes.append(box.windowTitle()))
    window.cfg.whats_new_seen = "1.6.4"
    window.cfg.update_pending = __version__
    window.after_update()
    assert len(shown) == 1 and any(f"Updated to Onion Board {__version__}" in t
                                   for t in shown[0])
    assert boxes == [] and window.cfg.update_pending == ""


def test_old_configs_have_seen_nothing_and_first_starts_everything(app_dir):
    raw = Config().to_raw()
    del raw["whats_new_seen"]
    assert Config.from_raw(raw).whats_new_seen == ""
    assert Config().whats_new_seen == __version__
    assert whatsnew.unseen(__version__) == []
    assert whatsnew.unseen("") and whatsnew.unseen("1.6.4")


def test_notes_for_a_version_after_this_one_wait(monkeypatch):
    future = whatsnew.Note("99.0.0", "Later", (("shield", "x", "y"),))
    monkeypatch.setattr(whatsnew, "NOTES", (future,) + whatsnew.NOTES)
    assert future not in whatsnew.unseen("")


def test_it_waits_for_the_tray_and_the_setup_guide(window, shown):
    window.cfg.whats_new_seen = ""
    window.cfg.setup_done = False
    window.after_update()
    assert shown == [] and window.cfg.whats_new_seen == ""
    window.cfg.setup_done = True
    window.hide()
    window.after_update()
    assert shown == []
    window.whats_new(window._whats_new_later)   # what showEvent's timer does
    assert shown == []   # still hidden
    window.show()
    from conftest import process_events
    from PySide6.QtWidgets import QApplication
    assert process_events(QApplication.instance(), lambda: len(shown) == 1, 5)


def _write(raw: dict):
    library.CONFIG_PATH.write_text(json.dumps(raw), encoding="utf-8")


def test_privacy_survives_an_older_version_saving_over_it(app_dir):
    cfg = Config(net_mode="tor", net_off=["radio", "sounds_web.youtube"], net_offline=True,
                 netlog_keep=True, tor_bridges="snowflake", net_proxy="socks5h://h:1")
    cfg.save()
    raw = json.loads(library.CONFIG_PATH.read_text(encoding="utf-8"))
    for k in library.PRIVACY_KEYS:   # what 1.6.4 writes back: none of them
        raw.pop(k)
    _write(raw)
    back = Config.load()
    assert (back.net_mode, back.net_off, back.net_offline, back.netlog_keep,
            back.tor_bridges, back.net_proxy) == (
        "tor", ["radio", "sounds_web.youtube"], True, True, "snowflake", "socks5h://h:1")


def test_whats_new_seen_survives_an_older_version_saving_over_it(app_dir):
    """Seen on this version, back to 1.6.4 (which drops whats_new_seen with the privacy
    settings), then this version again: What's new doesn't show a second time."""
    Config(whats_new_seen=__version__).save()
    side = json.loads((app_dir / "privacy.json").read_text(encoding="utf-8"))
    assert side["whats_new_seen"] == __version__
    raw = json.loads(library.CONFIG_PATH.read_text(encoding="utf-8"))
    for k in library.SIDE_KEYS:   # what 1.6.4 writes back
        raw.pop(k)
    _write(raw)
    back = Config.load()
    assert back.whats_new_seen == __version__ and whatsnew.unseen(back.whats_new_seen) == []
    # a first upgrade from an old version (no side copy yet) still gets What's new
    (app_dir / "privacy.json").unlink()
    _write(raw)
    assert Config.load().whats_new_seen == ""


def test_a_config_with_its_own_privacy_settings_wins(app_dir):
    Config(net_off=["radio"]).save()
    raw = json.loads(library.CONFIG_PATH.read_text(encoding="utf-8"))
    raw["net_off"] = []   # switched back on, in this version
    _write(raw)
    assert Config.load().net_off == []


def test_first_upgrade_from_an_old_version_gets_the_defaults(app_dir):
    raw = Config().to_raw()
    for k in library.PRIVACY_KEYS:
        raw.pop(k)
    _write(raw)
    cfg = Config.load()
    assert (cfg.net_mode, cfg.net_off, cfg.net_offline, cfg.tor_bridges) == (
        "direct", [], False, "")
    net.configure_from(cfg)
    assert all(net.allowed(k) for k in net.FEATURES)


def test_a_damaged_privacy_copy_is_ignored(app_dir):
    raw = Config().to_raw()
    for k in library.PRIVACY_KEYS:
        raw.pop(k)
    _write(raw)
    (app_dir / "privacy.json").write_text('{"net_mode": "warp", "net_off": "radio"',
                                         encoding="utf-8")
    assert Config.load().net_mode == "direct"
    (app_dir / "privacy.json").write_text('{"net_mode": "warp", "net_off": 5}',
                                         encoding="utf-8")
    cfg = Config.load()
    assert cfg.net_mode == "proxy" and cfg.net_off == []   # unknown mode: fails closed
