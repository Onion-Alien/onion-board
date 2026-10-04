"""Sending to others without the virtual cable (Config.route): another device
(Voicemeeter, OBS, a mixer) or nowhere. The cable is then never picked in its place,
and the Setup tab, the header pill and the setup guide count either as set up."""
import pytest

from soundboard import backup, engine, reset
from soundboard.library import Config
from soundboard.settings import SettingsDialog
from soundboard.ui import mainwindow as main
from soundboard.ui import setupwizard
from test_setupwizard import devices, resume, wizard  # noqa: F401  (fake devices)

CABLE = "CABLE Input (VB-Audio Virtual Cable)"
PHONES = "Headphones (USB)"


class _Stream:
    def stop(self):
        pass

    close = stop


@pytest.fixture
def opened(monkeypatch, devices):  # noqa: F811
    """What the engine was asked to send into, with a stand-in stream for each."""
    log = {"main": [], "obs": []}

    def opener(key):
        def set_device(self, name):
            log[key].append(name)
            self.names[key] = name
            setattr(self, f"{key}_stream", _Stream() if name else None)
        return set_device
    monkeypatch.setattr(engine.Engine, "set_main_device", opener("main"))
    monkeypatch.setattr(engine.Engine, "set_obs_device", opener("obs"))
    return log


@pytest.fixture
def win(qapp, app_dir, opened):
    Config(mon_device=PHONES, mon_follows_default=False, setup_done=True).save()
    w = main.MainWindow()
    w._load_thread.join(15)
    yield w
    w.close()
    w._load_thread.join(15)
    from PySide6.QtCore import QEvent
    w.deleteLater()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)


def test_route_is_cleaned_kept_on_this_pc_and_reset_with_the_devices():
    assert Config().route == "cable"
    assert Config.from_raw({"version": 2, "route": "device"}).route == "device"
    assert Config.from_raw({"version": 2, "route": "smoke-signals"}).route == "cable"
    assert "route" in backup.LOCAL_SETTINGS   # another PC may not have that device
    assert "route" in reset.DEVICE_FIELDS


def test_the_cable_route_still_picks_the_cable(win, opened):
    assert win.cfg.route == "cable" and win.cfg.main_device == CABLE
    assert opened["main"][-1] == CABLE
    assert win.setup_state == "ok"


def test_another_device_is_sent_to_and_the_cable_never_takes_its_place(win, opened, devices):  # noqa: F811
    win.set_route("device", "Speakers")
    assert opened["main"][-1] == "Speakers"
    assert win.setup_state == "ok"
    assert "Speakers" in win.pill.text()
    assert "Audio Output Capture" in win.step_lbl.text()
    assert win.btn_install.isHidden() and win.btn_chat.isHidden()   # no cable, no Discord mic
    assert win.main_row[1].text() == "Send to"
    # the cable missing changes nothing, and the cable showing up doesn't take over
    devices["cable"] = False
    win.refresh_devices()
    assert win.cfg.main_device == "Speakers" and win.setup_state == "ok"
    devices["cable"] = True
    win.refresh_devices()
    assert win.cfg.main_device == "Speakers" and opened["main"][-1] == "Speakers"


def test_without_any_cable_the_device_route_never_asks_to_install_one(win, devices):  # noqa: F811
    devices["cable"] = False
    win.set_route("device", "Speakers")
    assert win.setup_state == "ok"
    assert win.btn_install.isHidden() and win.btn_rescan.isHidden()


def test_the_headphones_are_never_what_others_hear(win, opened):
    win.set_route("device", PHONES)
    assert opened["main"][-1] is None    # you'd hear everything twice, your voice too
    assert win.setup_state == "unrouted"
    assert "headphones" in win.setup_hint.text()
    assert "Not sending" in win.pill.text()


def test_nowhere_closes_the_send_and_frees_the_cable_for_the_stream_output(win, opened):
    win.set_obs_device(CABLE)            # the cable is what others hear: not for OBS too
    assert opened["obs"][-1] is None
    win.set_route("off")
    assert opened["main"][-1] is None and opened["obs"][-1] == CABLE
    assert win.setup_state == "ok"       # picked on purpose: the Setup tab doesn't nag
    assert "Not sending" in win.pill.text()
    assert all(w.isHidden() for w in win.main_row)
    assert win.cfg.main_device == CABLE  # kept for switching back
    win.set_route("cable")
    assert opened["main"][-1] == CABLE and opened["obs"][-1] is None
    assert not win.main_row[1].isHidden() and win.main_row[1].text() == "Send into (the cable)"


def test_the_route_picker_and_its_settings_mirror(win, opened):
    i = win.cb_route.findData("device")
    win.cb_route.setCurrentIndex(i)
    win.on_device(win.cb_route, "route")
    assert win.cfg.route == "device"
    d = SettingsDialog(win, "audio")
    route = next(cb for cb, src in d.dev_combos if src is win.cb_route)
    label, send = d.dev_main
    assert label.text() == "Send to" and route.currentData() == "device"
    route.activated.emit(route.findData("off"))
    assert win.cfg.route == "off" and opened["main"][-1] is None
    assert label.isHidden() and send.isHidden()
    route.activated.emit(route.findData("cable"))
    assert win.cfg.route == "cable" and label.text() == "Send into (the cable)"
    d.close()


def test_the_guide_can_send_to_another_device(wizard, devices):  # noqa: F811
    w, wiz = wizard
    devices["cable"] = False
    w.refresh_devices()
    wiz.go(2)
    assert wiz.btn_next.text().startswith("Skip")
    wiz.btn_other.click()
    assert not wiz.other_box.isHidden()
    choices = [b.text() for b in wiz.other_box.findChildren(setupwizard.QRadioButton)]
    assert PHONES not in choices and "Speakers" in choices and setupwizard.NOWHERE in choices
    wiz._pick_route("Speakers")
    assert w.cfg.route == "device" and devices["picked"]["set_main_device"] == "Speakers"
    assert "Sending to Speakers" in wiz.cable_status.text()
    assert wiz.btn_next.text().startswith("Next")
    wiz.go(3)
    assert "Audio Output Capture" in wiz.discord_text.text()
    assert wiz.btn_discord.isHidden() and wiz.btn_steam.isHidden()
    wiz.finish()
    assert w.cfg.setup_done and w.cfg.route == "device"


def test_the_guide_can_send_nowhere_and_go_back_to_the_cable(wizard, devices):  # noqa: F811
    w, wiz = wizard
    wiz.go(2)
    wiz.btn_other.click()
    wiz._pick_route(setupwizard.NOWHERE)
    assert w.cfg.route == "off" and wiz.route_ok()
    assert not wiz.btn_use_cable.isHidden()
    wiz.go(3)
    assert "Nothing to change" in wiz.discord_text.text() and wiz.btn_copy.isHidden()
    wiz.go(2)
    wiz.btn_use_cable.click()
    assert w.cfg.route == "cable" and w.cfg.main_device == CABLE
    assert wiz.other_box.isHidden() and wiz.btn_use_cable.isHidden()
