"""Set up for the app you're using (soundboard.appsetup): the rules, and the bar in the
real MainWindow (offscreen). Nothing is really listened to: the detectors are stubs."""
import pytest

from soundboard import appsetup, profiles
from soundboard.library import Config
from soundboard.settings import SettingsDialog
from test_mainwindow import window as main_window  # noqa: F401 - the real window, offscreen

DISCORD = appsetup.Seen("discord.exe", "Discord", profiles.VOICE.key)
GAME = appsetup.Seen("valorant.exe", "Valorant", profiles.GAME.key)
ZOOM = appsetup.Seen("zoom.exe", "Zoom", profiles.VOICE.key)


@pytest.fixture
def window(main_window, monkeypatch):  # noqa: F811
    from soundboard import engine as eng
    monkeypatch.setattr(eng, "virtual_mic_for", lambda name: "CABLE Output (fake)")
    main_window.cfg.setup_done = True
    main_window.voice_watch = None
    main_window.listeners = Heard()
    return main_window


class Heard:
    """Stands in for voicesdk.Listeners."""
    found = ()
    apps = ()

    def poll(self, device):
        return self.found if device else ()


def at(window, t):
    """One look at time `t` (a made-up clock: the tests jump it past appsetup.GONE_S)."""
    window._app_setup(window._apps_seen(), now=t)


def hear(window, *apps):
    window.listeners.found = tuple((k, n) for _e, k, n in apps)
    window.listeners.apps = apps


def test_settings_are_made_usable_and_keep_what_they_dont_know():
    cfg = Config()
    cfg.app_setup = {"ask": "yes", "apps": {"Discord.EXE": "voice", 3: "x"},
                     "never": ["Zoom.exe", 5], "newer": 1}
    s = appsetup.settings(cfg)
    assert s == {"ask": True, "apps": {"discord.exe": "voice"}, "never": ["zoom.exe"],
                 "newer": 1}


def test_a_new_app_is_offered_once_unless_its_mode_is_in_use():
    cfg = Config()
    assert appsetup.decide(cfg, [DISCORD], "clean") == ("offer", DISCORD)
    assert appsetup.decide(cfg, [DISCORD], "voice") is None    # already right
    assert appsetup.decide(cfg, [DISCORD], "advanced") is None  # picked by hand: leave it
    assert appsetup.decide(cfg, [DISCORD, GAME], "voice") == ("offer", GAME)
    assert appsetup.decide(cfg, [DISCORD], "clean", {"discord.exe"}) is None   # Not now
    appsetup.never(cfg, "discord.exe")
    assert appsetup.decide(cfg, [DISCORD], "clean") is None
    appsetup.forget(cfg, "discord.exe")
    appsetup.settings(cfg)["ask"] = False
    assert appsetup.decide(cfg, [DISCORD], "clean") is None


def test_a_remembered_app_switches_to_its_mode():
    cfg = Config()
    appsetup.remember(cfg, "discord.exe", "voice")
    assert appsetup.decide(cfg, [DISCORD], "game") == ("switch", DISCORD)
    assert appsetup.decide(cfg, [DISCORD], "voice") is None
    appsetup.remember(cfg, "discord.exe", "clean")   # changed in Settings
    assert appsetup.decide(cfg, [DISCORD], "voice") == (
        "switch", appsetup.Seen("discord.exe", "Discord", "clean"))
    appsetup.settings(cfg)["ask"] = False            # asking off: still switches
    assert appsetup.decide(cfg, [DISCORD], "voice")[0] == "switch"
    appsetup.remember(cfg, "discord.exe", "studio")  # a newer version's mode
    assert appsetup.decide(cfg, [DISCORD], "voice") is None


def test_an_app_is_new_only_after_it_was_gone_a_while():
    t = appsetup.Tracker()
    assert t.update([DISCORD], 0.0) == [DISCORD]
    assert t.update([DISCORD], 1.0) == []
    assert t.update([], 10.0) == [] and t.here("discord.exe", 10.0)
    assert t.update([DISCORD], 20.0) == []           # a short gap: the same visit
    assert not t.here("discord.exe", 60.0)
    assert t.update([DISCORD], 60.0) == [DISCORD]    # back after a while: new again


def test_the_guide_each_app_gets():
    assert DISCORD.guide == "discord" and ZOOM.guide == "meeting"
    assert GAME.guide == "game"
    assert appsetup.Seen("mumble.exe", "Mumble", "voice").guide == ""


def test_offer_set_up_then_switch_by_itself_next_time(window):
    window.cfg.dest = {"simple": "clean", "mode": "off"}
    hear(window, ("discord.exe", "discord", "Discord"))
    at(window, 0.0)
    assert window._setup_state == "offer" and not window.setup_bar.isHidden()
    assert "Discord" in window.setup_lbl.text()
    assert window.cfg.dest["simple"] == "clean"           # only asked
    window.setup_yes.click()
    assert window.cfg.dest["simple"] == "voice"
    assert appsetup.settings(window.cfg)["apps"] == {"discord.exe": "voice"}
    assert window._setup_state == "done" and "Next time" in window.setup_lbl.text()

    window.cfg.dest = {"simple": "clean", "mode": "off"}   # picked by hand meanwhile
    at(window, 5.0)
    assert window.cfg.dest["simple"] == "clean"           # still here: left alone
    window._app_setup([], now=100.0)                      # Discord closed a while
    at(window, 200.0)                                     # and came back
    assert window.cfg.dest["simple"] == "voice"
    assert window._setup_state == "switched" and window.setup_yes.text() == "Undo"
    window.setup_yes.click()                              # Undo
    assert window.cfg.dest["simple"] == "clean" and window.setup_bar.isHidden()


def test_not_now_and_never(window):
    window.cfg.dest = {"simple": "clean", "mode": "off"}
    hear(window, ("zoom.exe", "webrtc", "Zoom"))
    at(window, 0.0)
    window.setup_no.click()
    assert window.setup_bar.isHidden()
    window._app_setup([], now=100.0)
    at(window, 200.0)
    assert window.setup_bar.isHidden()                    # Not now: not again this run
    window._setup_skipped.clear()
    window._app_setup([], now=300.0)
    at(window, 400.0)
    assert window._setup_state == "offer"
    window.setup_x.click()                                # never
    assert appsetup.settings(window.cfg)["never"] == ["zoom.exe"]
    window._app_setup([], now=500.0)
    at(window, 600.0)
    assert window.setup_bar.isHidden()


def test_the_offer_goes_when_the_app_closes(window):
    window.cfg.dest = {"simple": "clean", "mode": "off"}
    hear(window, ("valorant.exe", "game", "Valorant"))
    at(window, 100.0)
    assert window._setup_state == "offer"
    window._app_setup([], now=200.0)
    assert window.setup_bar.isHidden()


def test_meeting_apps_get_a_show_me_how(window, monkeypatch):
    window.cfg.dest = {"simple": "clean", "mode": "off"}
    hear(window, ("zoom.exe", "webrtc", "Zoom"))
    at(window, 0.0)
    window.setup_yes.click()
    assert "noise removal" in window.setup_lbl.text()
    opened = []
    monkeypatch.setattr(window, "show_chat_guide", opened.append)
    window.setup_yes.click()
    assert opened == ["meeting"]


def test_nothing_is_offered_before_the_setup_guide(window):
    window.cfg.setup_done = False
    window.cfg.dest = {"simple": "clean", "mode": "off"}
    hear(window, ("discord.exe", "discord", "Discord"))
    at(window, 0.0)
    assert window.setup_bar.isHidden()


def test_settings_lists_remembered_apps_and_can_forget(window):
    appsetup.remember(window.cfg, "discord.exe", "voice")
    appsetup.never(window.cfg, "zoom.exe")
    dlg = SettingsDialog(window, page="general")
    from PySide6.QtWidgets import QComboBox, QLabel, QPushButton
    rows = [dlg.app_setup_list.itemAt(i).widget() for i in range(dlg.app_setup_list.count())]
    texts = [lb.text() for r in rows for lb in r.findChildren(QLabel)]
    assert "discord.exe" in texts and any("never asks" in t for t in texts)
    cb = rows[0].findChild(QComboBox)
    cb.setCurrentIndex(cb.findData("game"))
    assert appsetup.settings(window.cfg)["apps"]["discord.exe"] == "game"
    rows[0].findChildren(QPushButton)[-1].click()          # Remove
    assert appsetup.settings(window.cfg)["apps"] == {}
    dlg.box_app_setup.setChecked(False)
    assert appsetup.settings(window.cfg)["ask"] is False
    dlg.close()


def test_the_voice_poll_feeds_it(window):
    window.cfg.dest = {"simple": "clean", "mode": "off"}
    hear(window, ("discord.exe", "discord", "Discord"))
    window._poll_voice()
    assert window._setup_state == "offer"
