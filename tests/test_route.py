"""Sending to others without the virtual cable (Config.route): another device
(Voicemeeter, OBS, a mixer) or nowhere. The cable is then never picked in its place,
and the Setup tab, the header pill and the setup guide count either as set up."""
import numpy as np
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
    Config(mon_device=PHONES, mon_follows_default=False, setup_done=True,
           mic_first=True).save()   # (on the cable)
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
    assert win.cb_route.currentText() == "Speakers"   # picked by name
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
    assert "My mic" in win.step_lbl.text() and "plugged in" not in win.step_lbl.text()
    assert "Not sending" in win.pill.text()


def test_nowhere_closes_the_send_and_frees_the_cable_for_the_stream_output(win, opened):
    win.set_obs_device(CABLE)            # the cable is what others hear: not for OBS too
    assert opened["obs"][-1] is None
    win.set_route("off")
    assert opened["main"][-1] is None and opened["obs"][-1] == CABLE
    assert win.setup_state == "ok"       # picked on purpose: the Setup tab doesn't nag
    assert "Not sending" in win.pill.text()
    assert win.cb_route.currentData() == "off"
    assert win.cfg.main_device == CABLE  # kept for switching back
    win.set_route("cable")
    assert opened["main"][-1] == CABLE and opened["obs"][-1] is None
    assert win.cb_route.currentText() == CABLE


def test_the_live_switch_never_says_others_hear_you_while_nothing_is_sent(win):
    win._air_size = 0                    # the full label
    win.set_sending(True)
    assert win.btn_air.text() == "Live — others hear you"
    win.set_route("device", PHONES)      # the headphones: nothing is sent
    assert win.btn_air.text() == "Only you hear sounds"
    win.set_route("off")
    assert win.btn_air.text() == "Only you hear sounds"
    win.set_obs_device("Speakers")       # muting still silences the stream output
    assert win.btn_air.text() == "Live — stream output only"
    win.btn_air.setChecked(False)
    assert win.btn_air.text() == "Muted — others hear nothing"
    win.btn_air.setChecked(True)
    win.set_route("cable")
    assert win.btn_air.text() == "Live — others hear you"


def test_the_route_picker_and_its_settings_mirror(win, opened):
    """One box: your mic, nobody, or a device by name (never the headphones)."""
    cb = win.cb_route
    texts = [cb.itemText(i) for i in range(cb.count())]
    assert texts[:2] == ["My mic (normal)", "Nobody: only I hear them"]
    assert CABLE in texts and "Speakers" in texts and PHONES not in texts
    assert not any("cable" in t.lower() and t != CABLE for t in texts)
    cb.setCurrentIndex(cb.findData(main.ROUTE_DEVICE + "Speakers"))
    win.on_device(cb, "route")
    assert win.cfg.route == "device" and opened["main"][-1] == "Speakers"
    d = SettingsDialog(win, "audio")
    route = next(c for c, src in d.dev_combos if src is win.cb_route)
    assert route.currentText() == "Speakers"
    route.activated.emit(route.findData("off"))
    assert win.cfg.route == "off" and opened["main"][-1] is None
    route.activated.emit(route.findData(main.ROUTE_DEVICE + CABLE))
    assert win.cfg.route == "cable" and opened["main"][-1] == CABLE   # a cable is a cable
    assert route.currentText() == CABLE
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


def test_also_send_to_copies_what_others_hear_into_more_devices(win, monkeypatch):
    """Streamers: more devices at once, each getting a copy (never the headphones, never
    the one already picked), off while sending to nobody, and in Settings too."""
    copies = []
    monkeypatch.setattr(engine.Engine, "set_copy_devices",
                        lambda self, names: (copies.append(list(names)),
                                             setattr(self, "copy_names", tuple(names))))
    win.set_route("cable")
    menu = win.btn_also.menu()
    menu.aboutToShow.emit()
    offered = [a.text() for a in menu.actions()]
    assert "Speakers" in offered and PHONES not in offered and CABLE not in offered
    assert win.btn_also.text().strip().startswith("Nothing else")
    win.set_also_send("Speakers", True)
    assert copies[-1] == ["Speakers"] and win.cfg.also_send == ["Speakers"]
    assert win.btn_also.text().strip() == "Speakers"
    win.set_also_send(PHONES, True)        # the headphones: you'd hear it twice
    assert copies[-1] == ["Speakers"]
    d = SettingsDialog(win, "audio")
    assert d.dev_also.text().strip() == "Speakers"
    d.close()
    win.set_route("off")                   # nobody: nothing goes anywhere
    assert copies[-1] == [] and all(w.isHidden() for w in win.also_row)
    win.set_route("cable")
    assert copies[-1] == ["Speakers"] and not win.btn_also.isHidden()
    win.set_route("device", "Speakers")    # picked as the main one: not twice
    assert copies[-1] == []
    win.set_route("cable")
    win.set_also_send("Speakers", False)
    assert copies[-1] == [] and win.cfg.also_send == [PHONES]


def test_engine_copies_open_close_retry_and_get_the_send_mix(monkeypatch):
    made, fail = [], {"B"}

    class FakeTap:
        def __init__(self, name, latency="low"):
            if name in fail:
                raise RuntimeError("busy")
            self.name, self.got, self.closed = name, [], False
            self.last_cb = engine.time.monotonic()
            made.append(self)

        def write(self, mix):
            self.got.append(mix.copy())

        def close(self):
            self.closed = True
    monkeypatch.setattr(engine, "CableTap", FakeTap)
    e = engine.Engine()
    try:
        e.set_copy_devices(["A", "B"])
        assert [t.name for t in e.copies] == ["A"] and e.copies_down() == ["B"]
        out = np.zeros((480, 2), np.float32)
        e._main(out, 480)
        assert len(made[0].got) == 1 and np.array_equal(made[0].got[0], out)
        fail.clear()
        later = engine.time.monotonic() + engine.RETRY_S
        made[0].last_cb = later              # (A is still playing)
        e._check_copies(later)               # B is tried again
        assert [t.name for t in e.copies] == ["A", "B"] and not e.copies_down()
        a = made[0]
        a.last_cb = engine.time.monotonic()
        e.set_copy_devices(["A"])           # kept open, B closed
        assert e.copies == (a,) and made[1].closed and not a.closed
        a.last_cb -= engine.STALL_S + 1     # stalled: reopened
        e._check_copies(engine.time.monotonic())
        assert a.closed and [t.name for t in e.copies] == ["A"] and e.copies[0] is not a
    finally:
        e.shutdown()
    assert e.copies == () and all(t.closed for t in made)


def test_also_send_is_kept_on_this_pc_and_reset_with_the_devices():
    assert "also_send" in backup.LOCAL_SETTINGS and "also_send" in reset.DEVICE_FIELDS
    assert Config.from_raw({"version": 2, "also_send": ["X"]}).also_send == ["X"]
    assert Config.from_raw({"version": 2, "also_send": "X"}).also_send == []
