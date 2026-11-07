"""Sending to others without the virtual cable (Config.route): another device
(Voicemeeter, OBS, a mixer) or nowhere. The cable is then never picked in its place,
and the Setup tab, the header pill and the setup guide count either as set up."""
import numpy as np
import pytest

from soundboard.core import backup, reset
from soundboard.audio import engine
from soundboard.sounds.library import Config
from soundboard.ui.settings.settings import SettingsDialog
from soundboard.ui.window import mainwindow as main
from soundboard.ui.setup import setupwizard, wizardkit
from soundboard.ui.window.routecontrol import ROUTE_DEVICE
from conftest import devices_done
from test_setupwizard import devices, resume, wizard  # noqa: F401  (fake devices)

CABLE = "CABLE Input (VB-Audio Virtual Cable)"
PHONES = "Headphones (USB)"
VM_IN = "Voicemeeter In 1 (VB-Audio Voicemeeter VAIO)"


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
    w.soundctl._load_thread.join(15)
    yield w
    w.close()
    w.soundctl._load_thread.join(15)
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
    assert win.statusctl.setup_state == "ok"


def test_the_cable_hint_points_to_clean_mic(win, monkeypatch):
    """Pick the cable, switch the app's noise suppression off: Clean mic does it."""
    from soundboard.voicefx import cleanmic
    monkeypatch.setattr(cleanmic, "available", lambda: True)
    win.statusctl._update_status()
    assert "noise suppression" in win.mic_reason.text() and "Clean mic" in win.mic_reason.text()
    monkeypatch.setattr(cleanmic, "available", lambda: False)
    win.statusctl._update_status()
    assert "noise suppression" in win.mic_reason.text() and "Clean mic" not in win.mic_reason.text()


def test_another_device_is_sent_to_and_the_cable_never_takes_its_place(win, opened, devices):  # noqa: F811
    win.routectl.set_route("device", VM_IN)
    assert opened["main"][-1] == VM_IN
    assert win.statusctl.setup_state == "ok"
    assert VM_IN in win.pill.accessibleName()
    assert "Audio Output Capture" in win.mic_reason.text()
    assert win.btn_install.isHidden() and not win.discord_card.wanted   # no cable, no Discord mic
    assert win.cb_route.currentData() == ROUTE_DEVICE + VM_IN   # picked by name
    assert win.seg_device.isChecked() and not win.seg_device.isHidden()   # says what it is
    # the cable missing changes nothing, and the cable showing up doesn't take over
    devices["cable"] = False
    win.devctl.refresh_devices()
    assert win.cfg.main_device == VM_IN and win.statusctl.setup_state == "ok"
    devices["cable"] = True
    win.devctl.refresh_devices()
    assert win.cfg.main_device == VM_IN and opened["main"][-1] == VM_IN


def test_without_any_cable_the_device_route_never_asks_to_install_one(win, devices):  # noqa: F811
    devices["cable"] = False
    win.routectl.set_route("device", "Speakers")
    assert win.statusctl.setup_state == "ok"
    assert win.btn_install.isHidden() and win.btn_rescan.isHidden()


def test_the_headphones_are_never_what_others_hear(win, opened):
    win.routectl.set_route("device", PHONES)
    assert opened["main"][-1] is None    # you'd hear everything twice, your voice too
    assert win.statusctl.setup_state == "unrouted"
    assert "headphones" in win.setup_hint.text()
    assert "Driver" in win.mic_reason.text() and "plugged in" not in win.mic_reason.text()
    assert "Not sending" in win.pill.accessibleName()


def test_nowhere_closes_the_send_and_frees_the_cable_for_the_stream_output(win, opened):
    win.routectl.set_obs_device(CABLE)            # the cable is what others hear: not for OBS too
    assert opened["obs"][-1] is None
    win.routectl.set_route("off")
    assert opened["main"][-1] is None and opened["obs"][-1] == CABLE
    assert win.statusctl.setup_state == "ok"       # picked on purpose: the Setup tab doesn't nag
    assert "Not sending" in win.pill.accessibleName()
    assert win.seg_off.isChecked()
    assert win.cfg.main_device == CABLE  # kept for switching back
    win.routectl.set_route("cable")
    assert opened["main"][-1] == CABLE and opened["obs"][-1] is None
    assert win.cb_route.currentData() == ROUTE_DEVICE + CABLE


def test_the_live_switch_never_says_others_hear_you_while_nothing_is_sent(win):
    # one word on the button; the whole sentence is its accessible name and tooltip
    def said():
        assert win.btn_air.toolTip().startswith(win.btn_air.accessibleName())
        return win.btn_air.property("railtext"), win.btn_air.accessibleName()
    win.set_sending(True)
    assert said() == ("On", "On: others hear you and your sounds")
    win.routectl.set_route("device", PHONES)      # the headphones: nothing is sent
    assert said() == ("Only you", "Only you hear sounds")
    win.routectl.set_route("off")
    assert said() == ("Only you", "Only you hear sounds")
    win.routectl.set_obs_device("Speakers")       # muting still silences the stream output
    devices_done(win)
    assert said() == ("On", "On: only the stream hears your sounds")
    win.btn_air.setChecked(False)
    assert said() == ("Muted", "Muted: others hear nothing")
    win.btn_air.setChecked(True)
    win.routectl.set_route("cable")
    assert said() == ("On", "On: others hear you and your sounds")


def test_the_switch_goes_through_all_three_and_back(win, opened, monkeypatch):
    """Driver, Virtual cable, Nobody: each says so and sends where it says, no prompt."""
    from soundboard.mic import directmic
    monkeypatch.setattr(directmic, "mics", lambda names: [])
    monkeypatch.setattr(directmic, "status", lambda name=None: "missing")
    attached = []
    monkeypatch.setattr(win.micctl, "attach_mic", lambda *a, **k: attached.append(1))
    win.seg_off.click()
    devices_done(win)
    assert win.cfg.route == "off" and win.seg_off.isChecked() and opened["main"][-1] is None
    assert win.mic_line.text() == "Only you hear your sounds" and "Driver" in win.mic_reason.text()
    assert win.mic_pill.text() == "Only you"
    win.seg_cable.click()
    devices_done(win)
    assert win.cfg.route == "cable" and win.seg_cable.isChecked() and opened["main"][-1] == CABLE
    win.seg_mic.click()
    _found(win)
    devices_done(win)
    win.statusctl._update_status()
    assert win.cfg.route == "mic" and win.seg_mic.isChecked() and not win.mic_status.isHidden()
    win.seg_off.click()
    devices_done(win)
    assert win.cfg.route == "off" and attached == []


def test_every_saved_route_loads_and_shows_on_the_switch(win, opened):
    """Old settings keep working: each route lights its own button, and Other device only
    shows while it's the route (a mixer's virtual input picked by hand stays as it is)."""
    c = win.cfg
    for route, device, seg in (("off", None, win.seg_off), ("cable", CABLE, win.seg_cable),
                               ("device", VM_IN, win.seg_device), ("mic", None, win.seg_mic)):
        c.route, c.main_device = route, device
        win.devctl._pick_devices()
        assert c.route == route and seg.isChecked(), route
        assert win.seg_device.isHidden() == (route != "device")
        if device:
            assert c.main_device == device
    c.route, c.main_device, c.mic_device = "device", VM_IN, None   # and with no mic saved
    win.devctl._pick_devices()
    assert c.route == "device" and win.seg_device.isChecked()


def test_the_cable_side_never_starts_an_install_by_itself(win, monkeypatch, devices):  # noqa: F811
    """Not installed: the switch moves, the card says so and its button installs."""
    devices["cable"] = False
    win.routectl.set_route("off")
    installs = []
    monkeypatch.setattr(win.micctl, "install_cable", lambda: installs.append(1))
    win.seg_cable.click()
    devices_done(win)
    win.statusctl._update_status()
    assert win.cfg.route == "cable" and win.seg_cable.isChecked() and installs == []
    assert not win.btn_install.isHidden() and win.btn_install.objectName() == "primary"
    assert "Driver" in win.mic_reason.text()


def test_send_to_shows_only_with_more_than_one_place(win, monkeypatch):
    """One cable: nothing to choose. Two: which one, and picking moves the sound."""
    win.routectl.set_route("cable", CABLE)
    assert win.route_pick.isHidden()
    second = "CABLE-A Input (VB-Audio Cable A)"
    real = engine.list_devices
    monkeypatch.setattr(engine, "list_devices", lambda kind: real(kind) + (
        [{"name": second, "index": 99}] if kind == "output" else []))
    win.routectl._show_route()
    assert not win.route_pick.isHidden()
    cb = win.cb_route
    cb.setCurrentIndex(cb.findData(ROUTE_DEVICE + second))
    win.routectl.on_device(cb, "route")
    devices_done(win)
    assert win.cfg.route == "cable" and win.cfg.main_device == second
    win.routectl.set_route("off")
    assert win.route_pick.isHidden()


def test_no_none_in_the_mic_box_and_it_asks_for_one(win):
    """No "(none)" to get stuck on: nothing picked, it says Pick your mic."""
    routectl, cb = win.routectl, win.cb_mic
    routectl._fill_combo(cb, ["Desk Mic"], None)
    assert cb.currentIndex() == -1 and cb.placeholderText() == "Pick your mic"
    assert [cb.itemText(i) for i in range(cb.count())] == ["Desk Mic"]
    routectl._fill_combo(cb, ["Desk Mic"], "Desk Mic")
    assert cb.currentText() == "Desk Mic"
    routectl._fill_combo(cb, ["Desk Mic"], "Unplugged Headset")   # saved, not there now
    assert cb.currentIndex() == -1 and cb.placeholderText() == "Unplugged Headset"


def test_picking_a_mic_on_the_driver_keeps_the_route(win, opened, monkeypatch):
    from soundboard.mic import directmic
    mics = [{"name": "Desk Mic", "index": 0}, {"name": "Headset Mic", "index": 1}]
    real = engine.list_devices
    monkeypatch.setattr(engine, "list_devices",
                        lambda kind: mics if kind == "input" else real(kind))
    monkeypatch.setattr(directmic, "status", lambda name=None: "missing")
    attached = []
    monkeypatch.setattr(win.micctl, "attach_mic", lambda *a, **k: attached.append(1))
    win.cfg.mic_device, win.cfg.route = "Desk Mic", "mic"
    win.devctl._pick_devices()
    cb = win.cb_mic
    cb.setCurrentIndex(cb.findData("Headset Mic"))
    win.routectl.on_device(cb, "mic_device")
    devices_done(win)
    assert win.cfg.route == "mic" and win.cfg.mic_device == "Headset Mic"
    assert attached == []   # not on another mic: the card has the button


def test_a_real_output_saved_under_send_moves_to_also_play_on(win, opened):
    c = win.cfg
    c.route, c.main_device, c.also_send = "device", "Speakers", []
    win.devctl._pick_devices()
    assert c.route == "mic" and c.also_send == ["Speakers"]
    cb = win.cb_route
    assert "Speakers" not in [cb.itemText(i) for i in range(cb.count())]
    assert win.seg_mic.isChecked()
    c.route, c.main_device = "device", PHONES   # (never a copy into the headphones)
    win.devctl._pick_devices()
    assert c.route == "mic" and c.also_send == ["Speakers"]
    c.route, c.main_device = "device", VM_IN   # a mixer's virtual input stays
    win.devctl._pick_devices()
    assert c.route == "device" and c.main_device == VM_IN


def test_the_16_channel_end_finds_the_cables_mic_end():
    ins = ["Desk Mic", "CABLE Output (VB-Audio Virtual Cable)", "CABLE Output (VB-Audio Point)"]
    assert engine.virtual_mic_for("CABLE In 16 Ch (VB-Audio Virtual Cable)", ins) == ins[1]
    assert engine.virtual_mic_for(CABLE, ins) == ins[1]
    vm = "Voicemeeter Aux Input (VB-Audio Voicemeeter AUX VAIO)"
    assert engine.virtual_mic_for(vm, ins) is None


def test_remove_on_the_cable_tab(win, opened, monkeypatch):
    """Remove sits on the cable's own page; removed from under the sounds, they go to the
    mic. Not offered with nothing of VB-Audio's to remove."""
    win._vb_setup = True
    win.statusctl._update_flow()
    assert win.cfg.route == "cable" and not win.btn_rmcable_on.isHidden()
    win._vb_setup = False
    win.statusctl._update_flow()
    assert win.btn_rmcable_on.isHidden()
    win._vb_setup = True
    used = []
    monkeypatch.setattr(win.routectl, "use_mic", lambda: used.append(1))
    win.micctl._rmcable_release = lambda *a: None
    win.micctl._cable_removed("")
    assert win._cable_gone and used == [1]
    win.routectl._show_route()
    cb = win.cb_route
    assert ROUTE_DEVICE + CABLE not in [cb.itemData(i) for i in range(cb.count())]
    win._cable_gone = False
    win.micctl._cable_removed("no")   # failed: stays on the cable
    assert not win._cable_gone and used == [1]


def test_the_guide_only_offers_what_others_can_hear(wizard, devices):  # noqa: F811
    w, wiz = wizard
    devices["cable"] = False
    w.devctl.refresh_devices()
    wiz.go(wiz.send_index)
    # not set up: Next with the reason beside it, gone once a way is picked
    assert wiz.btn_next.text().startswith("Next") and not wiz.next_why.isHidden()
    wiz.btn_other.click()
    assert not wiz.other_box.isHidden()
    choices = [b.text() for b in wiz.other_box.findChildren(setupwizard.ChoiceTile)]
    assert PHONES not in choices and "Speakers" not in choices and wizardkit.NOWHERE in choices
    assert all("Speakers" not in c for c in choices)
    wiz._pick_route(wizardkit.NOWHERE)
    assert w.cfg.route == "off"
    assert wiz.btn_next.text().startswith("Next") and wiz.next_why.isHidden()


def test_the_guide_can_send_nowhere_and_go_back_to_the_cable(wizard, devices):  # noqa: F811
    w, wiz = wizard
    wiz.go(wiz.send_index)
    wiz.btn_other.click()
    wiz._pick_route(wizardkit.NOWHERE)
    assert w.cfg.route == "off" and wiz.route_ok()
    assert not wiz.btn_use_cable.isHidden()
    wiz.go(wiz.discord_index)
    assert "Nothing to change" in wiz.discord_text.text() and wiz.btn_copy.isHidden()
    wiz.go(wiz.send_index)
    wiz.btn_use_cable.click()
    assert w.cfg.route == "cable" and w.cfg.main_device == CABLE
    assert wiz.other_box.isHidden() and wiz.btn_use_cable.isHidden()


def test_also_send_to_copies_what_others_hear_into_more_devices(win, monkeypatch, devices):  # noqa: F811
    """Streamers: + adds a row per extra device, − takes it off, each one gets a copy
    (never the headphones, never one that gets it already), none while sending to
    nobody, and the same rows in Settings."""
    copies = []
    monkeypatch.setattr(engine.Engine, "set_copy_devices",
                        lambda self, names: (copies.append(list(names)),
                                             setattr(self, "copy_names", tuple(names))))
    win.routectl.set_route("cable")
    rows = win.also_rows
    assert rows.boxes == [] and not rows.add.isHidden()
    assert rows.free() == ["Speakers"]   # not the headphones, not the cable it's on
    rows.add.click()
    assert win.cfg.also_send == ["Speakers"] and copies[-1] == ["Speakers"]
    assert [b.currentData() for b in rows.boxes] == ["Speakers"]
    assert rows.add.isHidden()           # nothing left to add
    d = SettingsDialog(win, "audio")
    mirror = [v for v in win.also_views if v is not rows]
    assert len(mirror) == 1 and [b.currentData() for b in mirror[0].boxes] == ["Speakers"]
    win.routectl.set_route("off")                 # nobody: no copies (+ adds a clean one)
    assert copies[-1] == [] and rows.boxes == [] and not rows.add.isHidden()
    win.routectl.set_route("cable")
    assert copies[-1] == ["Speakers"] and len(rows.boxes) == 1
    win.routectl.set_route("device", "Speakers")  # picked as the main one: not twice
    assert copies[-1] == []
    win.routectl.set_route("cable")
    minus = rows.minuses[-1]
    assert minus.text() == "−"
    minus.click()                        # −
    assert win.cfg.also_send == [] and copies[-1] == [] and rows.boxes == []
    assert [b for b in mirror[0].boxes] == [] and not rows.add.isHidden()
    d.close()
    win.routectl.set_also_send_at(0, PHONES)      # the headphones: you'd hear it twice
    assert copies[-1] == []


def test_also_play_on_label_goes_with_its_add_button(win, monkeypatch, devices):  # noqa: F811
    """No row and no device left to add (a PC with one output): the + hid and its
    "Also play on" label sat there alone, a label with nothing next to it."""
    from soundboard.ui.setup.alsosend import AlsoSendRows, LABEL
    monkeypatch.setattr(engine.Engine, "set_copy_devices",
                        lambda self, names: setattr(self, "copy_names", tuple(names)))
    win.routectl.set_route("cable")
    rows = win.also_rows
    label = next(w for w in rows.widgets if getattr(w, "text", lambda: "")() == LABEL)
    assert not label.isHidden() and not rows.add.isHidden()
    monkeypatch.setattr(AlsoSendRows, "free", lambda self, keep=None: [])
    rows._shown = None
    rows.rebuild()
    label = next(w for w in rows.widgets if getattr(w, "text", lambda: "")() == LABEL)
    assert label.isHidden() and rows.add.isHidden()


def test_also_send_minus_stays_its_own_size(win, monkeypatch, devices, qapp):  # noqa: F811
    """The − sits in the grid's stretch column: on the full-width Devices card it was a
    bar across the card's whole right half."""
    monkeypatch.setattr(engine.Engine, "set_copy_devices",
                        lambda self, names: setattr(self, "copy_names", tuple(names)))
    win.routectl.set_route("cable")
    win.show()
    win.resize(1900, 1000)
    win.tabs.setCurrentWidget(win.setup_page)
    win.also_rows.add.click()
    qapp.processEvents()
    minus = win.also_rows.minuses[-1]
    assert minus.text() == "−" and minus.isVisible()
    assert minus.width() <= minus.sizeHint().width() + 4
    card = win.cb_main.parentWidget()
    assert card.rect().contains(minus.mapTo(card, minus.rect().bottomRight()))
    assert win.setup_page.horizontalScrollBar().maximum() == 0


def test_also_send_row_can_be_the_clean_stream_mix(win, monkeypatch, devices):  # noqa: F811
    """The stream output lives in the Also play on rows: a row set to Clean, for
    streaming is cfg.obs_device (its volume and voice switch under it), one at a time,
    and back to Same as the call it's a copy again. Sending to nobody, it's the only
    kind a row can be. No separate card in Settings any more."""
    from PySide6.QtWidgets import QLabel
    opened = []
    monkeypatch.setattr(engine.Engine, "set_obs_device",
                        lambda self, name: (opened.append(name),
                                            self.names.__setitem__("obs", name)))
    win.routectl.set_route("cable")
    rows = win.also_rows
    rows.add.click()
    assert win.cfg.also_send == ["Speakers"] and rows.stream_vol is None
    kind = rows.kinds[0]
    kind.setCurrentIndex(kind.findData("stream"))
    kind.activated.emit(kind.currentIndex())
    devices_done(win)                    # (opened on the device thread)
    assert win.cfg.obs_device == "Speakers" and win.cfg.also_send == []
    assert opened[-1] == "Speakers"
    assert [k.currentData() for k in rows.kinds] == ["stream"]
    assert rows.stream_vol is not None and rows.stream_voice.isChecked()
    rows.stream_voice.setChecked(False)
    assert win.cfg.obs_voice is False
    assert rows.add.isHidden()           # nothing left to add
    win.routectl.set_send_kind("Speakers", False)  # back to a copy of the call
    devices_done(win)
    assert win.cfg.obs_device is None and win.cfg.also_send == ["Speakers"]
    assert opened[-1] is None and rows.stream_vol is None
    win.routectl.set_also_send_at(0, None)
    win.routectl.set_route("off")                 # nobody: only the clean one makes sense
    assert rows.boxes == [] and not rows.add.isHidden()
    rows.add.click()
    assert win.cfg.obs_device and win.cfg.also_send == []
    assert [rows.kinds[0].itemData(i) for i in range(rows.kinds[0].count())] == ["stream"]
    assert rows.add.isHidden()           # one clean one at a time
    rows.minuses[0].click()   # −
    assert win.cfg.obs_device is None and rows.boxes == []
    d = SettingsDialog(win, "audio")
    assert not [w for w in d.findChildren(QLabel) if "Stream output (OBS)" in w.text()]
    d.close()


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


def test_a_missing_cable_is_warned_about_once_not_every_retry(monkeypatch, caplog):
    """A 1.9.7 freeze ended in this warning's write: it was logged every RETRY_S, on
    the UI thread, for as long as the cable was missing."""
    import logging
    fail = {"CABLE"}

    class FakeTap:
        def __init__(self, name, latency="low"):
            if name in fail:
                raise RuntimeError("busy")
            self.name, self.last_cb = name, engine.time.monotonic()

        def close(self):
            pass
    monkeypatch.setattr(engine, "CableTap", FakeTap)
    e = engine.Engine()
    try:
        with caplog.at_level(logging.INFO, logger="soundboard.audio.engine"):
            for _ in range(5):
                e._open_copy("CABLE")
            warned = [r for r in caplog.records if r.levelno >= logging.WARNING]
            assert len(warned) == 1 and "CABLE" in warned[0].getMessage()
            fail.clear()
            e._open_copy("CABLE")   # back: said once, and a later loss warns again
            assert any("also sending into CABLE" in r.getMessage() for r in caplog.records)
            fail.add("CABLE")
            e._open_copy("CABLE")
            assert len([r for r in caplog.records if r.levelno >= logging.WARNING]) == 2
    finally:
        e.shutdown()


def test_an_unplugged_output_is_warned_about_once_while_retried(monkeypatch, caplog):
    import logging
    e = engine.Engine()

    def gone(*_a, **_k):
        raise RuntimeError("device not found")
    monkeypatch.setattr(e, "_open_out", gone)
    try:
        with caplog.at_level(logging.INFO, logger="soundboard.audio.engine"):
            for _ in range(4):
                e.set_mon_device("Headset")
            warned = [r for r in caplog.records if r.levelno >= logging.WARNING]
            assert len(warned) == 1 and "Headset" in warned[0].getMessage()
            assert e.errors["mon"]   # the window still says it's missing
    finally:
        e.shutdown()


def test_also_send_is_kept_on_this_pc_and_reset_with_the_devices():
    assert "also_send" in backup.LOCAL_SETTINGS and "also_send" in reset.DEVICE_FIELDS
    assert Config.from_raw({"version": 2, "also_send": ["X"]}).also_send == ["X"]
    assert Config.from_raw({"version": 2, "also_send": "X"}).also_send == []


def test_virtual_pairs_read_each_device_list_once(monkeypatch):
    """Voicemeeter adds ~18 virtual devices: a device list per device froze the window
    for seconds while Windows was busy (each list waits up to 0.25 s for PortAudio)."""
    from soundboard.audio import devicelist
    outs = [f"Voicemeeter In {i} (VB-Audio Voicemeeter VAIO)" for i in range(1, 6)] + [
        "Voicemeeter Input (VB-Audio Voicemeeter VAIO)", "Speakers (Realtek)"]
    ins = ["Voicemeeter Out B1 (VB-Audio Voicemeeter VAIO)",
           "Voicemeeter Output (VB-Audio Voicemeeter VAIO)", "Microphone (Realtek)"]
    asked = []

    def list_devices(kind):
        asked.append(kind)
        return [{"name": n, "index": i} for i, n in enumerate(ins if kind == "input" else outs)]
    monkeypatch.setattr(devicelist, "list_devices", list_devices)
    pairs = devicelist.virtual_pairs()
    assert asked == ["output", "input"]
    assert pairs[0] == ("Voicemeeter Input (VB-Audio Voicemeeter VAIO)",
                        "Voicemeeter Output (VB-Audio Voicemeeter VAIO)")   # a pipe: first
    assert dict(pairs)[VM_IN] is None   # through Voicemeeter's mixer, no mic end of its own
    assert "Speakers (Realtek)" not in dict(pairs)
    assert devicelist.virtual_outputs() == [p[0] for p in pairs]


def test_voicemeeter_without_a_mic_end_reads_as_sending_to_it(win, monkeypatch):
    """"Voicemeeter In 1" goes through Voicemeeter's mixer (no "... Out 1" pipe end): the
    Setup tab said "Virtual mic not connected" and "That's a normal speaker/headphone
    device, so only you will hear the sounds", and a user didn't know what to do."""
    monkeypatch.setattr(engine, "virtual_mic_for", lambda name, ins=None: None)
    win.routectl.set_route("cable", VM_IN)
    devices_done(win)
    win.statusctl._update_status()
    assert "speaker" not in win.setup_hint.text() and "only you" not in win.setup_hint.text()
    assert win.mic_line.text() == f"Your sounds go to {VM_IN}"
    assert "Voicemeeter" in win.mic_reason.text()
    assert win.statusctl.setup_state == "ok"
    assert "click to fix" not in win.pill.accessibleName()


def test_picking_my_mic_from_another_route_says_what_windows_asks(win, monkeypatch):
    """Setting up the driver from another route: the route only turns to the mic once
    the set-up worked, so the card said nothing about Windows' prompt meanwhile, nor about
    a No after it (the box just went back to the old device: "it doesn't choose it")."""
    from soundboard.mic import michelper
    monkeypatch.setattr(michelper, "will_ask", lambda: True)
    assert win.cfg.route == "cable"
    win._attaching = True
    win.statusctl._update_flow()
    assert "Yes" in win.mic_reason.text() and not win.mic_reason.isHidden()
    assert win.mic_line.text() == "Setting up…"
    assert not win.btn_install.isHidden()
    win._attaching = False
    win.micctl._declined = True
    win.statusctl._update_flow()
    assert "You clicked" in win.mic_reason.text() and not win.mic_reason.isHidden()
    win.routectl.set_route("device", "Speakers")   # picked something else: that's over
    devices_done(win)
    assert not win.micctl._declined and "You clicked" not in win.mic_reason.text()


def _found(win):
    """Until use_mic's look for the mic Onion Board is on came back from its thread."""
    from PySide6.QtWidgets import QApplication
    from conftest import process_events
    assert process_events(QApplication.instance(), lambda: not win.routectl.finding_mic)


def test_my_mic_switch_moves_both_boxes_to_the_mic_it_is_on_already(win, monkeypatch):
    """Set up on a mic before: the My mic switch puts My mic and Send my sounds to on it,
    with no set-up (no admin prompt) again. Before, it ran the set-up every time, which
    a copy run from source can't (no mic effect built), so it bounced back to the cable,
    and with no mic picked it lit My mic while the sounds stayed on the cable."""
    from soundboard.mic import directmic
    win.cfg.mic_device = None
    monkeypatch.setattr(directmic, "mics", lambda names: [
        {"name": "Headset Mic (USB)", "active": True, "state": "missing",
         "pa": "Headset Mic (USB)"},
        {"name": "Desk Mic", "active": True, "state": "ready", "pa": "Desk Mic"}])
    attached, unsaid = [], []
    monkeypatch.setattr(win.micctl, "attach_mic", lambda *a, **k: attached.append(1))
    monkeypatch.setattr(win, "unsay", unsaid.append)
    assert win.seg_cable.isChecked() and not win.route_switch.isHidden()
    win.seg_mic.click()
    _found(win)
    devices_done(win)
    assert attached == []   # no reinstall (a copy run from source has nothing to install)
    assert "mic-attach-failed" in unsaid   # an earlier try's error toast goes
    assert win.cfg.route == "mic" and win.cfg.mic_device == "Desk Mic"
    assert win.cb_mic.currentText() == "Desk Mic" and win.seg_mic.isChecked()
    win.seg_cable.click()   # and back: the cable in the box, the real mic kept
    devices_done(win)
    assert win.cfg.route == "cable" and win.cb_route.currentData() == ROUTE_DEVICE + CABLE
    assert win.seg_cable.isChecked() and win.cfg.mic_device == "Desk Mic"


def test_my_mic_switch_never_asks_windows_and_the_card_offers_the_set_up(win, monkeypatch):
    """Not on any mic yet: My mic switches to the picked mic (else the first one) with no
    admin prompt, and the card says the sounds aren't in it yet; only its button sets it
    up. It used to run the set-up from the switch and bounce back to the cable when that
    failed ("Couldn't put Onion Board on your mic"), so only Send my sounds to got there."""
    from soundboard.mic import directmic
    monkeypatch.setattr(directmic, "mics", lambda names: [])
    # plugged in, not set up: the same on every PC (CI's has no mics to look up)
    monkeypatch.setattr(directmic, "status", lambda name=None: "missing")
    monkeypatch.setattr(win.micctl, "mic_unplugged", lambda: False)
    win.cfg.mic_device = None
    attached = []
    monkeypatch.setattr(win.micctl, "attach_mic", lambda *a, **k: attached.append(1))
    win.seg_mic.click()
    _found(win)
    devices_done(win)
    win.statusctl._update_status()
    assert attached == []   # no prompt from the switch
    assert win.cb_mic.currentText() == "Headset Mic (USB)"   # none picked: the first real mic
    assert win.cfg.route == "mic" and win.seg_mic.isChecked()
    assert win.how_title.text() == "Your mic"
    assert "aren't in your mic yet" in win.mic_line.text()
    assert win.btn_install.text() == "Put my sounds straight into my mic"
    assert not win.btn_install.isHidden()
    win.btn_install.click()   # the set-up is the button's
    assert attached == [1]


def test_my_mic_switch_with_no_mic_at_all_stays_on_my_mic(win, monkeypatch, devices):  # noqa: F811
    from soundboard.mic import directmic
    monkeypatch.setattr(directmic, "mics", lambda names: [])
    real = engine.list_devices
    monkeypatch.setattr(engine, "list_devices",
                        lambda kind: [] if kind == "input" else real(kind))
    win.devctl.refresh_devices()
    devices_done(win)
    attached = []
    monkeypatch.setattr(win.micctl, "attach_mic", lambda *a, **k: attached.append(1))
    win.seg_mic.click()
    _found(win)
    devices_done(win)
    assert attached == []   # nothing to set up on
    assert win.cfg.route == "mic" and win.seg_mic.isChecked()


def test_virtual_cable_clicked_while_my_mic_is_looked_up_wins(win, monkeypatch):
    from soundboard.mic import directmic
    monkeypatch.setattr(directmic, "mics", lambda names: [
        {"name": "Desk Mic", "active": True, "state": "ready", "pa": "Desk Mic"}])
    win.seg_mic.click()
    win.seg_cable.click()   # before the answer came back
    _found(win)
    from PySide6.QtWidgets import QApplication
    from conftest import process_events
    process_events(QApplication.instance(), lambda: False, timeout=0.3)
    assert win.cfg.route == "cable" and win.seg_cable.isChecked()
    assert win.cb_route.currentData() == ROUTE_DEVICE + CABLE


def test_the_switch_moves_settings_mic_effect_card_at_once(win, monkeypatch):
    """Settings → Audio has Your mic and the Mic effect card. Clicking the switch there
    left the card on the old route until its next look (5 s)."""
    from soundboard.mic import directmic
    from soundboard.ui.setup.audiorecovery import RecoveryCard
    monkeypatch.setattr(directmic, "mics", lambda names: [])
    monkeypatch.setattr(directmic, "status", lambda name=None: "missing")
    monkeypatch.setattr(win.micctl, "attach_mic", lambda *a, **k: None)
    win.setctl.open_settings("audio")
    d = win.setctl._settings_dlg
    assert not any(src is win.cb_route or src is win.cb_mic for _c, src in d.dev_combos)
    card = d.findChild(RecoveryCard)
    card._rebuild()   # (its first look runs on a thread)
    assert card.isHidden()   # (on the cable)
    card.timer.stop()   # (no look of its own from here: only the switch moves it)
    win.seg_mic.click()
    _found(win)
    devices_done(win)
    assert not card.isHidden()
    win.statusctl._update_status()
    win.seg_cable.click()
    devices_done(win)
    assert card.isHidden()   # (on the cable)
    win.setctl.close_settings()


def test_send_to_lists_only_what_others_hear_you_through(win, monkeypatch, devices):  # noqa: F811
    """Each virtual cable once, by its mic end: never speakers or screens (Also play on
    copies sounds there)."""
    from test_setupwizard import OUTS
    outs = [*OUTS, "CABLE In 16ch (VB-Audio Virtual Cable)", "VG248 (AMD High Definition Audio)",
            VM_IN]
    monkeypatch.setattr(engine, "list_devices", lambda kind: [
        {"name": n, "index": i} for i, n in enumerate(
            outs if kind == "output" else ["Desk Mic", "CABLE Output (VB-Audio Virtual Cable)"])])
    win.cfg.mic_device = "Desk Mic"
    win.devctl._pick_devices()
    cb = win.cb_route
    texts = [cb.itemText(i) for i in range(cb.count())]
    assert texts == ["CABLE Output (VB-Audio Virtual Cable)", VM_IN]
    win.routectl.set_route("cable", "CABLE In 16ch (VB-Audio Virtual Cable)")
    texts = [cb.itemText(i) for i in range(cb.count())]
    assert texts == ["CABLE Output (VB-Audio Virtual Cable)", VM_IN]   # the picked end, still once
    assert cb.currentData() == ROUTE_DEVICE + "CABLE In 16ch (VB-Audio Virtual Cable)"


def test_the_cable_says_where_the_voice_comes_from_and_where_it_goes(win, opened):
    """The mic box said one mic and the card called the cable "your new mic": it read as
    two mics fighting. The box is where the voice comes from, the cable where it goes."""
    win.cfg.mic_device, win.cfg.mic_enabled = "Desk Mic", True
    win.routectl.set_route("cable", CABLE)
    devices_done(win)
    win.statusctl._update_status()
    assert win.mic_sub.text() == "Your voice comes from here" and not win.mic_sub.isHidden()
    assert win.mic_line.text() == "Your sounds and voice go into the virtual cable"
    assert "new mic" not in win.mic_line.text() + win.mic_reason.text()
    assert "CABLE Output" in win.mic_reason.text() and not win.mic_status.isHidden()
    assert win.mic_status.isVisibleTo(win.how_home.card)   # (never only its words)
    win.cfg.mic_enabled = False   # sounds only: it doesn't claim the voice goes
    win.statusctl._update_status()
    assert win.mic_line.text() == "Your sounds go into the virtual cable"
    assert win.mic_sub.text() == "Not sent, sounds only"
