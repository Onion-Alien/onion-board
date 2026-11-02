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
    assert "noise suppression" in win.step_lbl.text() and "Clean mic" in win.step_lbl.text()
    monkeypatch.setattr(cleanmic, "available", lambda: False)
    win.statusctl._update_status()
    assert "noise suppression" in win.step_lbl.text() and "Clean mic" not in win.step_lbl.text()


def test_another_device_is_sent_to_and_the_cable_never_takes_its_place(win, opened, devices):  # noqa: F811
    win.routectl.set_route("device", "Speakers")
    assert opened["main"][-1] == "Speakers"
    assert win.statusctl.setup_state == "ok"
    assert "Speakers" in win.pill.accessibleName()
    assert "Audio Output Capture" in win.step_lbl.text()
    assert win.btn_install.isHidden() and win.btn_chat.isHidden()   # no cable, no Discord mic
    assert win.cb_route.currentText() == "Speakers"   # picked by name
    # the cable missing changes nothing, and the cable showing up doesn't take over
    devices["cable"] = False
    win.devctl.refresh_devices()
    assert win.cfg.main_device == "Speakers" and win.statusctl.setup_state == "ok"
    devices["cable"] = True
    win.devctl.refresh_devices()
    assert win.cfg.main_device == "Speakers" and opened["main"][-1] == "Speakers"


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
    assert "My mic" in win.step_lbl.text() and "plugged in" not in win.step_lbl.text()
    assert "Not sending" in win.pill.accessibleName()


def test_nowhere_closes_the_send_and_frees_the_cable_for_the_stream_output(win, opened):
    win.routectl.set_obs_device(CABLE)            # the cable is what others hear: not for OBS too
    assert opened["obs"][-1] is None
    win.routectl.set_route("off")
    assert opened["main"][-1] is None and opened["obs"][-1] == CABLE
    assert win.statusctl.setup_state == "ok"       # picked on purpose: the Setup tab doesn't nag
    assert "Not sending" in win.pill.accessibleName()
    assert win.cb_route.currentData() == "off"
    assert win.cfg.main_device == CABLE  # kept for switching back
    win.routectl.set_route("cable")
    assert opened["main"][-1] == CABLE and opened["obs"][-1] is None
    assert win.cb_route.currentText() == CABLE


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


def test_the_route_picker_and_its_settings_mirror(win, opened):
    """One box: your mic, nobody, or a device by name (never the headphones)."""
    cb = win.cb_route
    texts = [cb.itemText(i) for i in range(cb.count())]
    assert texts[:2] == ["My mic (normal)", "Nobody: only I hear them"]
    assert CABLE in texts and "Speakers" in texts and PHONES not in texts
    assert not any("cable" in t.lower() and t != CABLE for t in texts)
    cb.setCurrentIndex(cb.findData(ROUTE_DEVICE + "Speakers"))
    win.routectl.on_device(cb, "route")
    devices_done(win)
    assert win.cfg.route == "device" and opened["main"][-1] == "Speakers"
    d = SettingsDialog(win, "audio")
    route = next(c for c, src in d.dev_combos if src is win.cb_route)
    assert route.currentText() == "Speakers"
    route.activated.emit(route.findData("off"))
    devices_done(win)
    assert win.cfg.route == "off" and opened["main"][-1] is None
    route.activated.emit(route.findData(ROUTE_DEVICE + CABLE))
    devices_done(win)
    assert win.cfg.route == "cable" and opened["main"][-1] == CABLE   # a cable is a cable
    assert route.currentText() == CABLE
    d.close()


def test_the_guide_can_send_to_another_device(wizard, devices):  # noqa: F811
    w, wiz = wizard
    devices["cable"] = False
    w.devctl.refresh_devices()
    wiz.go(wiz.send_index)
    # not set up: Next with the reason beside it, gone once a device works
    assert wiz.btn_next.text().startswith("Next") and not wiz.next_why.isHidden()
    wiz.btn_other.click()
    assert not wiz.other_box.isHidden()
    choices = [b.text() for b in wiz.other_box.findChildren(setupwizard.ChoiceTile)]
    assert PHONES not in choices and "Speakers" in choices and wizardkit.NOWHERE in choices
    wiz._pick_route("Speakers")
    assert w.cfg.route == "device" and devices["picked"]["set_main_device"] == "Speakers"
    assert "Sending to Speakers" in wiz.cable_status.text()
    assert wiz.btn_next.text().startswith("Next") and wiz.next_why.isHidden()
    wiz.go(wiz.discord_index)
    assert "Audio Output Capture" in wiz.discord_text.text()
    assert wiz.btn_discord.isHidden() and wiz.btn_steam.isHidden()
    wiz.finish()
    assert w.cfg.setup_done and w.cfg.route == "device"


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
    minus = rows.widgets[-1]
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
    minus = win.also_rows.widgets[-1]
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
    rows.widgets[rows.widgets.index(rows.kinds[0].parentWidget()) + 1].click()   # −
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
                e.set_tap_device("CABLE")
                e._open_copy("CABLE")
            warned = [r for r in caplog.records if r.levelno >= logging.WARNING]
            assert len(warned) == 1 and "CABLE" in warned[0].getMessage()
            fail.clear()
            e.set_tap_device("CABLE")   # back: said once, and a later loss warns again
            assert any("also sending into CABLE" in r.getMessage() for r in caplog.records)
            fail.add("CABLE")
            e.set_tap_device("CABLE")
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


def test_leaving_settings_on_a_new_non_cable_device_asks_once(win, monkeypatch):
    from soundboard.ui.settings import routewarn
    assert routewarn.needs_warning("device", "Speakers", PHONES)
    assert not routewarn.needs_warning("device", CABLE, PHONES)   # a cable: fine
    assert not routewarn.needs_warning("device", "VoiceMeeter Input (VB-Audio)", PHONES)
    assert not routewarn.needs_warning("device", PHONES, PHONES)   # has its own hint
    assert not routewarn.needs_warning("mic", "Speakers", PHONES)
    picked, installs = [], []
    monkeypatch.setattr(win.routectl, "set_route", lambda r, d=None, **k: picked.append((r, d)))
    monkeypatch.setattr(win.micctl, "install_cable", lambda: installs.append(1))

    def leave_on(device):
        win.setctl.open_settings("audio")
        win.cfg.route, win.cfg.main_device = "device", device
        win.routectl._show_route()
        win.setctl.close_settings()
        return win.setctl._route_warning
    # the cable picked in Settings: nothing asked
    win.setctl.open_settings("audio")
    win.setctl.close_settings()
    assert getattr(win.setctl, "_route_warning", None) is None
    # speakers picked in Settings: asked on the way out, Keep leaves it be
    box = leave_on("Speakers")
    assert box is not None and box.keep.text() == "Keep it"
    assert box.to_cable.text() == "Use the virtual cable"   # one is installed
    box.keep.click()
    assert picked == [] and win.setctl._route_warning is None
    # not asked again while it stays on the speakers
    win.setctl.open_settings("audio")
    win.setctl.close_settings()
    assert win.setctl._route_warning is None
    # [Use my mic]
    leave_on("Monitor (HDMI)").to_mic.click()
    assert picked[-1] == ("mic", None)
    # [Use the virtual cable]: on the cable, and Setup shows it
    leave_on("TV (HDMI)").to_cable.click()
    assert picked[-1] == ("cable", CABLE) and installs == []
    assert win.tabs.currentWidget() is win.setup_page


def test_without_a_cable_the_warning_offers_to_install_one(win, devices, monkeypatch):  # noqa: F811
    devices["cable"] = False
    win.devctl.refresh_devices()
    picked, installs = [], []
    monkeypatch.setattr(win.routectl, "set_route", lambda r, d=None, **k: picked.append((r, d)))
    monkeypatch.setattr(win.micctl, "install_cable", lambda: installs.append(1))
    win.setctl.open_settings("audio")
    win.cfg.route, win.cfg.main_device = "device", "Speakers"
    win.routectl._show_route()
    win.setctl.close_settings()
    box = win.setctl._route_warning
    assert box.to_cable.text() == "Install a virtual cable"
    box.to_cable.click()
    assert picked == [("cable", None)] and installs == [1]
    assert win.tabs.currentWidget() is win.setup_page


VM_IN = "Voicemeeter In 1 (VB-Audio Voicemeeter VAIO)"


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
    assert "Voicemeeter" in win.setup_hint.text()   # whatever listens there gets them
    assert "not connected" not in win.flow_out.text()
    assert "Voicemeeter" in win.step_lbl.text()
    assert win.statusctl.setup_state == "ok"
    assert "click to fix" not in win.setup_connection.text()


def test_picking_my_mic_from_another_route_says_what_windows_asks(win, monkeypatch):
    """"Send my sounds to: My mic" from another route: the route only turns to the mic once
    the set-up worked, so the card said nothing about Windows' prompt meanwhile, nor about
    a No after it (the box just went back to the old device: "it doesn't choose it")."""
    from soundboard.mic import michelper
    monkeypatch.setattr(michelper, "will_ask", lambda: True)
    assert win.cfg.route == "cable"
    win._attaching = True
    win.statusctl._update_flow()
    assert "Yes" in win.step_lbl.text() and not win.step_lbl.isHidden()
    assert not win.btn_install.isHidden()
    win._attaching = False
    win.micctl._declined = True
    win.statusctl._update_flow()
    assert "You clicked" in win.step_lbl.text() and not win.step_lbl.isHidden()
    win.routectl.set_route("device", "Speakers")   # picked something else: that's over
    devices_done(win)
    assert not win.micctl._declined and "You clicked" not in win.step_lbl.text()
