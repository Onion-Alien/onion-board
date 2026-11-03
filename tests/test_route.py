"""Sending to others without the virtual cable (Config.route): another device
(Voicemeeter, OBS, a mixer) or nowhere. The cable is then never picked in its place,
and the Setup tab, the header pill and the setup guide count either as set up."""
import numpy as np
import pytest

from soundboard.core import backup, reset
from soundboard.audio import engine
from soundboard.sounds.library import Config
from soundboard.ui.setup.sendline import SendLine
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
    assert "Use my mic" in win.step_lbl.text() and "plugged in" not in win.step_lbl.text()
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
    """One box: your mic, a cable, nobody, or a device picked before (never the headphones)."""
    cb = win.cb_route
    texts = [cb.itemText(i) for i in range(cb.count())]
    assert texts == ["My mic (normal)", CABLE, "Nobody: only I hear them"]
    win.routectl.set_route("device", "Speakers")   # (the setup guide's Another device)
    devices_done(win)
    assert win.cfg.route == "device" and opened["main"][-1] == "Speakers"
    d = SettingsDialog(win, "audio")
    line = d.findChild(SendLine)
    assert line.pick.currentText() == "Speakers" and line.back.isVisibleTo(line)
    line.tick.click()
    devices_done(win)
    assert win.cfg.route == "off" and opened["main"][-1] is None
    assert line.words.text() == "Off: only you hear them" and not line.tick.isChecked()
    line.tick.click()   # back the way it was
    devices_done(win)
    assert win.cfg.route == "device" and opened["main"][-1] == "Speakers"
    line.pick.setCurrentIndex(line.pick.findData(ROUTE_DEVICE + CABLE))
    line.pick.activated.emit(line.pick.currentIndex())
    devices_done(win)
    assert win.cfg.route == "cable" and opened["main"][-1] == CABLE   # a cable is a cable
    assert line.pick.currentText() == CABLE
    d.close()


def test_send_line_follows_the_route(win, opened, monkeypatch):
    """Devices names where the sounds go; the switch above picks it, the tick turns it off
    and on again, the same way it was."""
    d = SettingsDialog(win, "audio")
    line = d.findChild(SendLine)
    assert win.cfg.route == "cable" and line.words.text() == CABLE and line.tick.isChecked()
    assert not line.pick.isVisibleTo(line) and not line.back.isVisibleTo(line)   # one cable
    line.tick.click()
    devices_done(win)
    assert win.cfg.route == "off" and win.cfg.route_before_off == "cable"
    line.words.clicked.emit()   # the words tick it too
    devices_done(win)
    assert win.cfg.route == "cable" and line.tick.isChecked()
    win.cfg.route, win.cfg.mic_device = "mic", "Desk Mic"
    win.routectl._show_route()
    assert line.words.text() == "Desk Mic"
    line.tick.click()
    devices_done(win)
    assert win.cfg.route == "off"
    used = []
    monkeypatch.setattr(win.routectl, "use_mic", lambda: used.append(1))
    line.tick.click()
    assert used == [1]   # on the mic before: the mic again
    d.close()


def test_turned_on_with_the_cable_gone_goes_to_the_mic(win, opened, monkeypatch):
    win.routectl.set_route("off", by_hand=True)
    devices_done(win)
    assert win.cfg.route_before_off == "cable"
    win._cable_gone = True
    used = []
    monkeypatch.setattr(win.routectl, "use_mic", lambda: used.append(1))
    win.routectl.set_sending(True)
    assert used == [1]


def test_remove_on_the_cable_tab(win, opened, monkeypatch):
    """Remove sits on the cable's own page; removed from under the sounds, they go to the
    mic. Not offered with nothing of VB-Audio's to remove, or while sending into Voicemeeter."""
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
    win.micctl._rmcable_release = lambda *a: None
    win._cable_gone = False
    win.micctl._cable_removed("no")   # failed: stays on the cable
    assert not win._cable_gone and used == [1]


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
    assert win.cb_mic.currentText() == "Desk Mic"
    assert win.cb_route.currentData() == "mic" and win.seg_mic.isChecked()
    win.seg_cable.click()   # and back: the cable in the box, the real mic kept
    devices_done(win)
    assert win.cfg.route == "cable" and win.cb_route.currentText() == CABLE
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
    assert win.cb_route.currentData() == "mic" and win.how_title.text() == "Send your sounds"
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
    assert win.cb_route.currentData() == "mic"


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
    assert win.cb_route.currentText() == CABLE


def test_the_switch_moves_settings_send_box_and_mic_effect_card_at_once(win, monkeypatch):
    """Settings → Audio has the My mic | Virtual cable switch, its own copy of Send my
    sounds to and the Mic effect card. Clicking the switch there left the copy on the old
    choice and the card on the old route until its next look (5 s)."""
    from soundboard.mic import directmic
    from soundboard.ui.setup.audiorecovery import RecoveryCard
    monkeypatch.setattr(directmic, "mics", lambda names: [])
    monkeypatch.setattr(directmic, "status", lambda name=None: "missing")
    monkeypatch.setattr(win.micctl, "attach_mic", lambda *a, **k: None)
    win.setctl.open_settings("audio")
    d = win.setctl._settings_dlg
    box = win.cb_route
    line = d.findChild(SendLine)
    card = d.findChild(RecoveryCard)
    card._rebuild()   # (its first look runs on a thread)
    assert box.currentText() == CABLE and card.isHidden()   # no mic effect on the cable
    card.timer.stop()   # (no look of its own from here: only the switch moves it)
    win.seg_mic.click()
    _found(win)
    devices_done(win)
    texts = [box.itemText(i) for i in range(box.count())]
    assert texts == ["My mic (normal)", "Nobody: only I hear them"]   # no cable on My mic
    assert box.currentData() == "mic" and not card.isHidden()
    assert line.words.text() == win.cfg.mic_device
    win.statusctl._update_status()
    # the cable is installed: the switch is the way to it, no Use the cable tile too
    assert win.alt_cable.isHidden() and win.how_title.text() == "Send your sounds"
    win.seg_cable.click()
    devices_done(win)
    assert box.currentText() == CABLE and card.isHidden()   # no mic effect on the cable
    win.setctl.close_settings()


def test_send_my_sounds_to_lists_only_what_others_hear_you_through(win, monkeypatch, devices):  # noqa: F811
    """Your mic, each virtual cable once, nobody: never speakers or screens (Also play on
    copies sounds there), unless one was picked before."""
    from test_setupwizard import OUTS
    outs = [*OUTS, "CABLE In 16ch (VB-Audio Virtual Cable)", "VG248 (AMD High Definition Audio)",
            VM_IN]
    monkeypatch.setattr(engine, "list_devices", lambda kind: [
        {"name": n, "index": i} for i, n in enumerate(
            outs if kind == "output" else ["Desk Mic", "CABLE Output (VB-Audio Virtual Cable)"])])
    win.routectl._show_route()
    cb = win.cb_route
    texts = [cb.itemText(i) for i in range(cb.count())]
    assert texts == ["My mic (normal)", CABLE, VM_IN, "Nobody: only I hear them"]
    win.routectl.set_route("cable", "CABLE In 16ch (VB-Audio Virtual Cable)")
    texts = [cb.itemText(i) for i in range(cb.count())]
    assert texts == ["My mic (normal)", "CABLE In 16ch (VB-Audio Virtual Cable)", VM_IN,
                     "Nobody: only I hear them"]   # the picked end, still once
    win.routectl.set_route("device", "Speakers")   # picked before: kept
    assert cb.currentText() == "Speakers"
    cb.setCurrentIndex(cb.findData("mic"))   # My mic from the box: the same as the switch
    used = []
    monkeypatch.setattr(win.routectl, "use_mic", lambda: used.append(1))
    win.routectl.on_device(cb, "route")
    assert used == [1]


def test_another_device_picks_any_output_the_send_box_leaves_out(win, opened):
    """Setup -> Another device -> Pick a device: speakers, a mixer, a capture card (not in
    Send my sounds to any more) or nobody, never the headphones; once picked, Send my
    sounds to shows it."""
    from PySide6.QtWidgets import QApplication, QMenu
    win.micctl._pick_send_device()
    menu = next(m for m in QApplication.topLevelWidgets()
                if isinstance(m, QMenu) and m.isVisible())
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert texts == ["Speakers", CABLE, "Nobody: only I hear them"]
    assert next(a for a in menu.actions() if a.text() == CABLE).isChecked()
    next(a for a in menu.actions() if a.text() == "Speakers").trigger()
    menu.close()
    devices_done(win)
    assert win.cfg.route == "device" and opened["main"][-1] == "Speakers"
    assert win.cb_route.currentText() == "Speakers"


def test_send_line_works_in_setup_and_settings_alike(win, opened):
    """The Setup tab's line and Settings' copy: a tick in one moves the other."""
    setup = win.dev_card.findChild(SendLine)
    d = SettingsDialog(win, "audio")
    copy = d.findChild(SendLine)
    assert setup is not copy and {setup, copy} <= set(win.send_lines)
    assert setup.words.text() == copy.words.text() == CABLE
    setup.tick.click()
    devices_done(win)
    assert win.cfg.route == "off" and opened["main"][-1] is None
    assert not copy.tick.isChecked() and copy.words.text() == setup.words.text()
    copy.tick.click()
    devices_done(win)
    assert win.cfg.route == "cable" and opened["main"][-1] == CABLE
    assert setup.tick.isChecked() and setup.words.text() == CABLE
    d.close()
