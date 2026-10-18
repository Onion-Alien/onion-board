"""The quick-setup guide, on Qt's offscreen platform with fake devices: picks reach
the config and engine, the cable page reacts to the cable being there or not, and
finishing marks setup done (only when the cable exists)."""
import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QDialog

from soundboard import engine
from soundboard.sounds import library
from soundboard.control import winkeys
from soundboard.sounds.library import Config
from soundboard.ui import mainwindow as main
from soundboard.ui import busy, setupwizard

INS = ["Headset Mic (USB)", "Desk Mic", "CABLE Output (VB-Audio Virtual Cable)"]
OUTS = ["Headphones (USB)", "Speakers", "CABLE Input (VB-Audio Virtual Cable)"]
_REAL_RESUME = setupwizard.resume_after_restart   # before the autouse fixture swaps it


@pytest.fixture
def devices(monkeypatch):
    # these walk the cable path (a first start goes straight into the mic, which the
    # mic_wizard tests below and tests/test_directmic.py cover)
    monkeypatch.setattr(Config, "first_start", classmethod(lambda cls: cls()))
    state = {"cable": True, "picked": {}}

    def list_devices(kind):
        names = INS if kind == "input" else OUTS
        if not state["cable"]:
            names = [n for n in names if "CABLE" not in n]
        return [{"name": n, "index": i} for i, n in enumerate(names)]

    monkeypatch.setattr(engine, "list_devices", list_devices)
    monkeypatch.setattr(engine, "default_device_name", lambda kind: None)
    monkeypatch.setattr(engine, "rescan", lambda: True)
    for name in ("set_main_device", "set_mon_device", "set_mic_device"):
        monkeypatch.setattr(engine.Engine, name,
                            lambda self, n, _k=name: state["picked"].__setitem__(_k, n))
    monkeypatch.setattr(winkeys.Hotkeys, "register", lambda self, m: None)
    return state


@pytest.fixture(autouse=True)
def resume(monkeypatch):
    """Never touch the real RunOnce key: record what the guide asks for instead."""
    calls = []
    monkeypatch.setattr(setupwizard, "resume_after_restart", calls.append)
    return calls


@pytest.fixture
def wizard(qapp, app_dir, devices):
    w = main.MainWindow()
    wiz = setupwizard.SetupWizard(w)
    yield w, wiz
    wiz.done(0)
    w.soundctl._load_thread.join(15)
    w.close()
    from PySide6.QtCore import QEvent   # free it (see test_mainwindow's window fixture)
    wiz.deleteLater()
    w.deleteLater()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)


def test_old_configs_skip_the_guide(app_dir):
    assert Config.from_raw({"version": 2, "main_device": "CABLE Input"}).setup_done
    assert not Config.from_raw({"version": 2}).setup_done
    assert not Config().setup_done


def test_picks_reach_config_and_engine(wizard, devices):
    w, wiz = wizard
    # virtual cables are never offered as the mic or the headphones
    mics = [b.property("device") for b in wiz.mic_group.buttons()]
    assert mics == ["Headset Mic (USB)", "Desk Mic"]
    wiz.mic_group.buttons()[1].click()
    assert w.cfg.mic_device == "Desk Mic" and devices["picked"]["set_mic_device"] == "Desk Mic"
    wiz.go(1)
    wiz._pick_headphones("Speakers")
    assert w.cfg.mon_device == "Speakers"


def test_cable_present_routes_output_and_finishes(wizard, devices):
    w, wiz = wizard
    wiz.go(2)
    assert w.cfg.main_device.startswith("CABLE Input")
    assert "Installed" in wiz.cable_status.text() and wiz.btn_next.text().startswith("Next")
    wiz.go(3)
    assert "CABLE Output (VB-Audio Virtual Cable)" in wiz.discord_text.text()
    wiz.next_clicked()
    assert library.Config.load().setup_done


def test_a_working_cable_offers_the_mic_as_a_plain_option(wizard, monkeypatch):
    # "Installed and connected" with the big set-up button under it read as "set it up
    # again"; and a mic set-up that failed still ended Bun's show as a win (the cable
    # worked)
    from soundboard import directmic
    w, wiz = wizard
    wiz.show()
    wiz.go(2)
    assert w.cfg.route == "cable" and "Installed and" in wiz.cable_status.text()
    assert wiz.btn_attach.isHidden() and not wiz.btn_mic_instead.isHidden()
    monkeypatch.setattr(w.micctl, "attach_mic", lambda: None)
    wiz.btn_mic_instead.click()
    assert wiz.setup_show.on and wiz.btn_mic_instead.isHidden()
    results = []
    monkeypatch.setattr(wiz.setup_show, "finish", results.append)
    monkeypatch.setattr(directmic, "status", lambda name=None: "absent")
    w.mic_attached.emit("Headset Mic (USB)", "Windows said no")
    assert results and not any(results)


def test_mic_already_set_up_is_used_not_offered_again(wizard, monkeypatch):
    # on the cable with the mic effect already working: the page said "Installed and
    # connected" and offered to set the mic up again
    from soundboard import directmic
    w, wiz = wizard
    monkeypatch.setattr(directmic, "status", lambda name=None: "ready")
    asked = []
    monkeypatch.setattr(w.micctl, "attach_mic", lambda: asked.append(1))
    w.cfg.route = "cable"
    wiz.show()
    wiz.go(2)
    assert w.cfg.route == "mic" and not asked
    assert wiz.status_card.tone == "ok" and "Working" in wiz.status_card.title.text()
    assert wiz.btn_mic_instead.isHidden()
    wiz._pick_route("cable")   # picked the cable on purpose: it stays
    assert w.cfg.route == "cable"
    wiz.attach_mic()           # and back: no admin prompt, it's already there
    assert w.cfg.route == "mic" and not asked


def test_missing_cable_offers_install_and_finish_is_done(wizard, devices):
    # Finish without sending set up opened the guide again on every start
    devices["cable"] = False
    w, wiz = wizard
    wiz.go(2)
    assert not wiz.btn_cable.isHidden()
    assert wiz.btn_next.text().startswith("Skip")
    wiz.go(3)
    wiz.next_clicked()
    assert library.Config.load().setup_done   # Finish: not shown again by itself


def test_closing_the_guide_stops_it_opening_every_launch(wizard, devices):
    # closed with the X (or Esc), setup_done stayed False, so it popped up every start
    devices["cable"] = False
    w, wiz = wizard
    wiz.go(2)
    wiz.reject()
    assert library.Config.load().setup_done


def test_steam_guide_names_the_cable_mic(wizard, monkeypatch, tmp_path):
    w, wiz = wizard
    wiz.go(3)
    opened = []
    from soundboard.ui import busy
    monkeypatch.setattr(busy.QDesktopServices, "openUrl",
                        lambda url: opened.append(url.toString()) or True)
    g = setupwizard.SteamGuide(wiz, wiz._vm)
    text = " ".join(lbl.text() for lbl in g.findChildren(setupwizard.QLabel))
    assert "CABLE Output (VB-Audio Virtual Cable)" in text and "Voice Input Device" in text
    g.open_steam()
    assert opened == ["steam://settings/voice"]
    g.resize(g.sizeHint())
    g.grab().save(str(tmp_path.parent / "steam-guide.png"))
    wiz.resize(700, 600)
    wiz.grab().save(str(tmp_path.parent / "wizard-last.png"))
    g.done(0)


def test_finish_keeps_the_send_my_voice_choice(wizard, devices):
    w, wiz = wizard
    wiz.chk_send.setChecked(False)
    wiz.go(3)
    wiz.next_clicked()
    assert library.Config.load().mic_enabled is False
    assert not w.chk_mic.isChecked() and w.engine.mic_enabled is False


class _DoneProc:
    def __init__(self, rc):
        self.rc = rc

    def poll(self):
        return self.rc


def test_installer_needing_a_restart_offers_restart_not_reinstall(wizard, devices):
    devices["cable"] = False
    w, wiz = wizard
    wiz.go(2)
    wiz._cable_tries, wiz._proc = 1, _DoneProc(setupwizard.RESTART_NEEDED)
    wiz._tick()
    assert "restart" in wiz.cable_status.text()
    assert not wiz.btn_restart.isHidden() and wiz.btn_cable.isHidden()


def test_failed_install_offers_to_try_again(wizard, devices):
    devices["cable"] = False
    w, wiz = wizard
    wiz.go(2)
    wiz._cable_tries, wiz._proc = 1, _DoneProc(1)
    wiz._tick()
    assert "didn't work" in wiz.cable_status.text()
    assert not wiz.btn_cable.isHidden() and wiz.btn_restart.isHidden()


@pytest.mark.windows   # GetTickCount64 (time since the PC started)
def test_restart_marker_counts_only_until_the_pc_restarts(wizard, devices, app_dir):
    import os
    import time

    devices["cable"] = False
    w, wiz = wizard
    marker = app_dir / "cable-restart-pending"
    marker.write_text("x")
    assert setupwizard.cable_restart_pending()       # written this boot
    wiz.go(2)
    wiz.recheck_cable()
    # restart, or have the installer try waking it once more (never a reinstall)
    assert not wiz.btn_restart.isHidden() and "without restarting" in wiz.btn_cable.text()

    past = time.time() - 10 * 365 * 86400             # written before the last boot
    os.utime(marker, (past, past))
    assert not setupwizard.cable_restart_pending()
    wiz.recheck_cable()
    assert wiz.btn_restart.isHidden() and not wiz.btn_cable.isHidden()


def test_test_sound_is_quiet_and_clickless():
    c = setupwizard.test_tune()
    assert c.dtype.name == "float32" and c.shape[1] == 2
    assert abs(float(abs(c).max()) - setupwizard.TUNE_PEAK) < 1e-4   # not a blast
    assert abs(c[:5]).max() < 0.01 and abs(c[-5:]).max() < 0.01      # no clicks


class _RunningProc:
    rc = None

    def poll(self):
        return self.rc


def test_install_shows_bun_building_and_each_step(wizard, devices, app_dir, monkeypatch):
    devices["cable"] = False
    w, wiz = wizard
    wiz.go(2)
    proc, argv = _RunningProc(), []
    monkeypatch.setattr(setupwizard.subprocess, "Popen",
                        lambda a, **kw: (argv.extend(a), proc)[1])
    wiz.btn_cable.click()
    assert argv == []   # it asks first: the cable is only for those who need it
    box = wiz.findChild(QDialog, "cableconfirm")
    box.cable_button.click()   # Install the cable anyway
    status = app_dir / "cable-install-status.txt"
    assert str(status) in argv
    assert wiz.bun_cable.building and not wiz.cable_bar.isHidden()
    assert wiz.btn_cable.isHidden()

    status.write_text("download|Downloading...", encoding="utf-8-sig")   # PS 5.1 writes a BOM
    wiz._tick()
    status.write_text("install|Installing...", encoding="utf-8-sig")
    wiz._tick()
    steps = wiz.cable_steps.text()
    assert "✓  Fetching the parts" in steps and "▶  Building your cable" in steps
    assert "Waking" not in steps   # only listed if it happens

    status.write_text("wake|...", encoding="utf-8-sig")
    wiz._tick()
    assert "▶  Waking it up" in wiz.cable_steps.text()

    devices["cable"] = True
    proc.rc = 0
    wiz._tick()
    assert not wiz.bun_cable.building and wiz.bun_cable.prop == "star"
    assert wiz.cable_bar.isHidden() and "Installed" in wiz.cable_status.text()


def test_install_that_still_needs_a_restart_stops_bun(wizard, devices, monkeypatch):
    devices["cable"] = False
    w, wiz = wizard
    wiz.go(2)
    proc = _RunningProc()
    monkeypatch.setattr(setupwizard.subprocess, "Popen", lambda a, **kw: proc)
    wiz.install_cable()
    proc.rc = setupwizard.RESTART_NEEDED
    wiz._tick()
    assert not wiz.bun_cable.building and wiz.bun_cable.prop == "plug"
    assert "open by itself" in wiz.cable_status.text()
    # the installer already tried waking it, so only the restart is offered
    assert not wiz.btn_restart.isHidden() and wiz.btn_cable.isHidden()


def test_restart_needed_reopens_the_guide_after_it_then_clears(wizard, devices, resume):
    devices["cable"] = False
    w, wiz = wizard
    wiz.go(2)
    wiz._cable_tries, wiz._proc = 1, _DoneProc(setupwizard.RESTART_NEEDED)
    wiz._tick()
    assert resume[-1] is True          # come back by itself after the restart
    devices["cable"] = True
    wiz.recheck_cable()
    assert resume[-1] is False         # works now: nothing to come back for


def test_resumed_guide_starts_on_the_cable_and_welcomes_them_back(qapp, app_dir, devices):
    w = main.MainWindow()
    wiz = setupwizard.SetupWizard(w, resumed=True)
    try:
        assert wiz.stack.currentIndex() == 2
        assert "Welcome back" in wiz.cable_status.text()
        assert wiz.bun_cable.celebrate
    finally:
        wiz.done(0)
        w.soundctl._load_thread.join(15)
        w.close()


class _FakeKey:
    def __init__(self, store):
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_resume_after_restart_writes_and_removes_the_runonce_entry(monkeypatch):
    import sys
    import types

    store = {}
    fake = types.SimpleNamespace(
        HKEY_CURRENT_USER="HKCU", REG_SZ=1,
        CreateKey=lambda root, path: (store.setdefault("path", path), _FakeKey(store))[1],
        SetValueEx=lambda k, name, _r, _t, val: store.__setitem__(name, val),
        DeleteValue=lambda k, name: store.pop(name) if name in store else
        (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.setitem(sys.modules, "winreg", fake)
    _REAL_RESUME(True)
    assert store["path"].endswith(r"CurrentVersion\RunOnce")
    cmd = store["OnionBoardResumeSetup"]
    assert cmd.endswith(" --resume-setup") and "main.py" in cmd
    _REAL_RESUME(False)
    assert "OnionBoardResumeSetup" not in store
    _REAL_RESUME(False)   # already gone: fine


def test_mid_install_the_guide_stays_put_and_a_reopened_one_picks_it_up(
        qapp, wizard, devices, monkeypatch):
    devices["cable"] = False
    w, wiz = wizard
    wiz.go(2)
    proc, starts = _RunningProc(), []
    monkeypatch.setattr(setupwizard.subprocess, "Popen",
                        lambda a, **kw: (starts.append(a), proc)[1])
    wiz.install_cable()
    assert busy.is_busy(wiz.btn_next) and busy.is_busy(wiz.btn_back)
    asked = []
    monkeypatch.setattr(setupwizard.QMessageBox, "question",
                        lambda *a: (asked.append(a), setupwizard.QMessageBox.StandardButton.No)[1])
    wiz.reject()                                   # Esc: asks, and "No" keeps it open
    assert asked and wiz.result() == 0 and wiz._proc is proc
    again = setupwizard.SetupWizard(w)             # closed anyway, then reopened
    try:
        assert again._proc is proc and again.stack.currentIndex() == 2
        again.install_cable()
        assert len(starts) == 1                    # never a second install
        proc.rc = 0
        again._tick()
        assert not busy.is_busy(again.btn_next) and setupwizard._installer is None
    finally:
        again.done(0)
    wiz._proc = None


def test_resumed_guide_with_the_cable_still_missing_offers_to_install_again(
        qapp, app_dir, devices):
    devices["cable"] = False
    w = main.MainWindow()
    wiz = setupwizard.SetupWizard(w, resumed=True)
    try:
        assert "still isn't showing up after the restart" in wiz.cable_status.text()
        assert not wiz.btn_cable.isHidden() and "again" in wiz.btn_cable.text()
    finally:
        wiz.done(0)
        w.soundctl._load_thread.join(15)
        w.close()


def test_installer_that_cant_start_says_what_to_do(wizard, devices, monkeypatch):
    devices["cable"] = False
    w, wiz = wizard
    wiz.go(2)

    def fail(*a, **kw):
        raise OSError(2, "The system cannot find the file specified")
    monkeypatch.setattr(setupwizard.subprocess, "Popen", fail)
    wiz.install_cable()
    assert "Couldn't start the cable installer" in wiz.cable_status.text()
    assert wiz._proc is None and wiz.btn_next.isEnabled()
    monkeypatch.setattr(setupwizard.QMessageBox, "question",
                        lambda *a: setupwizard.QMessageBox.StandardButton.Yes)
    wiz.restart_pc()
    assert "Start menu" in wiz.cable_status.text()


def test_no_microphone_at_all_says_so(qapp, app_dir, devices, monkeypatch):
    real = engine.list_devices
    monkeypatch.setattr(engine, "list_devices",
                        lambda kind: [] if kind == "input" else real(kind))
    w = main.MainWindow()
    wiz = setupwizard.SetupWizard(w)
    try:
        w.engine.mic_stream = None
        wiz._tick()
        assert "No microphone was found" in wiz.mic_heard.text()
    finally:
        wiz.done(0)
        w.soundctl._load_thread.join(15)
        w.close()


def test_cancelling_the_guide_keeps_an_unplugged_device(qapp, app_dir, devices):
    """Their headset is unplugged: the guide stands in the first mic / output it finds
    (so the meter works), but closing it without choosing must not save that."""
    w = main.MainWindow()
    w.cfg.mic_device, w.cfg.mon_device = "Unplugged Mic", "Unplugged Headphones"
    wiz = setupwizard.SetupWizard(w)
    try:
        assert devices["picked"]["set_mic_device"] == "Headset Mic (USB)"   # stand-in
        wiz.reject()
        saved = library.Config.load()
        assert (saved.mic_device, saved.mon_device) == ("Unplugged Mic",
                                                        "Unplugged Headphones")
        from conftest import devices_done
        devices_done(w)   # reopened on the device thread
        assert devices["picked"]["set_mic_device"] == "Unplugged Mic"   # engine too
    finally:
        _close(qapp, w, wiz)


def test_cancelling_keeps_a_device_they_did_pick(qapp, app_dir, devices):
    w = main.MainWindow()
    w.cfg.mic_device = "Unplugged Mic"
    wiz = setupwizard.SetupWizard(w)
    try:
        wiz.mic_group.buttons()[1].click()
        wiz.reject()
        assert library.Config.load().mic_device == "Desk Mic"
    finally:
        _close(qapp, w, wiz)


def test_steam_guide_is_freed_after_it_closes(wizard, monkeypatch):
    _, wiz = wizard
    wiz.go(3)
    monkeypatch.setattr(setupwizard.SteamGuide, "exec", lambda self: 0)
    for _ in range(3):
        wiz.show_steam_guide()
    assert wiz.findChildren(setupwizard.SteamGuide) == []


def test_steam_guide_text_has_its_spaces(wizard):
    _, wiz = wizard
    g = setupwizard.SteamGuide(wiz, "CABLE Output")
    text = " ".join(lbl.text() for lbl in g.findChildren(setupwizard.QLabel))
    assert ").Onion" not in text
    g.done(0)


def _close(qapp, w, wiz):
    from PySide6.QtCore import QEvent
    wiz.done(0)
    w.soundctl._load_thread.join(15)
    w.close()
    wiz.deleteLater()
    w.deleteLater()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)


def test_only_the_mic_page_ticks_fast_and_the_folder_is_made_once(wizard, devices,
                                                                   monkeypatch):
    """The 40 ms tick is for the mic meter: the other pages tick every 250 ms, and
    following the cable installer doesn't make its folder again on every tick."""
    w, wiz = wizard
    assert wiz.stack.currentIndex() == 0 and wiz.timer.interval() == setupwizard.TICK_MS
    wiz.go(3)
    assert wiz.timer.interval() == setupwizard.SLOW_TICK_MS
    wiz.go(0)
    assert wiz.timer.interval() == setupwizard.TICK_MS
    made = []
    real = type(library.APP_DIR).mkdir
    monkeypatch.setattr(type(library.APP_DIR), "mkdir",
                        lambda self, *a, **k: (made.append(self), real(self, *a, **k)))
    setupwizard.SetupWizard._status_dir = None
    for _ in range(5):
        wiz._read_cable_step()
    assert made == [library.APP_DIR]


FIRST_START = Config.__dict__["first_start"]


@pytest.fixture
def mic_wizard(qapp, app_dir, devices, monkeypatch):
    """A new user's guide: straight into the mic (not set up on it yet)."""
    monkeypatch.setattr(Config, "first_start", FIRST_START)
    w = main.MainWindow()
    wiz = setupwizard.SetupWizard(w)
    yield w, wiz
    wiz.done(0)
    w.soundctl._load_thread.join(15)
    w.close()
    from PySide6.QtCore import QEvent
    wiz.deleteLater()
    w.deleteLater()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)


def test_new_users_are_offered_their_mic_first(mic_wizard, monkeypatch):
    from soundboard import directmic
    w, wiz = mic_wizard
    assert w.cfg.route == "mic"
    wiz.go(wiz.base + 2)
    # the step's one thing to do is Next itself; leaving without it is the quiet Skip
    # that says what it means, and the card has no second button saying the same
    assert "Put my sounds in my mic" in wiz.btn_next.text()
    assert not wiz.btn_skip.isHidden() and "only I'll hear" in wiz.btn_skip.text()
    assert wiz.btn_attach.isHidden()
    assert "asks once" in wiz.cable_status.text()
    # the other ways fold shut under their pill, not buttons under the status
    assert wiz.btn_cable.isHidden() and wiz.btn_other.isHidden()
    assert not wiz.alt_fold_row.isHidden() and wiz.alt_card.isHidden()
    wiz.alt_fold.click()
    assert not wiz.alt_card.isHidden() and not wiz.btn_alt_cable.isHidden()
    wiz.go(wiz.base + 3)   # not on the mic yet: the last page says so
    assert "isn't on your mic yet" in wiz.discord_text.text()
    monkeypatch.setattr(directmic, "status", lambda name=None: "ready")
    wiz.go(wiz.base + 3)
    assert "check Discord" in wiz.discord_title.text()
    assert "nothing to pick" in wiz.discord_text.text()
    assert "noise filter" in wiz.discord_text.text()
    assert wiz.btn_copy.isHidden() and not wiz.btn_discord.isHidden()


def test_next_on_the_send_step_puts_the_sounds_in_the_mic(mic_wizard, monkeypatch):
    from soundboard.core import usage
    w, wiz = mic_wizard
    calls, counted = [], []
    monkeypatch.setattr(w.micctl, "attach_mic", lambda *a, **k: calls.append(1))
    monkeypatch.setattr(usage, "used", counted.append)
    wiz.go(wiz.base + 2)
    wiz.next_clicked()
    assert calls == [1] and wiz.stack.currentIndex() == wiz.base + 2
    wiz.skip_clicked()   # the quiet way past: counted, and on to the last step
    assert wiz.stack.currentIndex() == wiz.base + 3
    assert "setup-skipped-send" in counted and wiz.btn_skip.isHidden()


def test_a_repair_is_offered_as_one(mic_wizard, monkeypatch):
    from soundboard import directmic
    _, wiz = mic_wizard
    monkeypatch.setattr(directmic, "status", lambda name=None: "wiped")
    wiz.go(wiz.base + 2)
    wiz.recheck_cable(rescan=False)
    assert "Repair" in wiz.btn_next.text() and "repair" in wiz.cable_status.text()


def test_cable_instead_doesnt_reinstall_a_cable_that_is_there(mic_wizard, monkeypatch):
    w, wiz = mic_wizard
    monkeypatch.setattr(setupwizard.subprocess, "Popen",
                        lambda *a, **k: pytest.fail("installed the cable again"))
    wiz.go(wiz.base + 2)
    wiz.install_cable()
    assert w.cfg.route == "cable" and wiz._proc is None


def test_a_mic_set_up_finishing_after_the_guide_closed_is_ignored(qapp, app_dir, devices,
                                                                 monkeypatch):
    # The set-up runs on a thread; when it finished after the guide was closed and freed,
    # the guide's handler still ran and touched its deleted buttons (RuntimeError).
    from PySide6.QtCore import QEvent
    w = main.MainWindow()
    wiz = setupwizard.SetupWizard(w)
    wiz.done(0)
    wiz.deleteLater()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)
    calls = []
    monkeypatch.setattr(setupwizard.SetupWizard, "recheck_cable",
                        lambda self, rescan=True: calls.append(rescan))
    w.mic_attached.emit("My mic", "")
    assert calls == []
    w.soundctl._load_thread.join(15)
    w.close()
    w.deleteLater()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)


def test_mic_attach_plays_show_in_wizard_without_blocking_buttons(mic_wizard, monkeypatch):
    from soundboard import directmic
    w, wiz = mic_wizard
    wiz.show()
    wiz.go(wiz.base + 2)
    assert "Put my sounds in my mic" in wiz.btn_next.text()
    assert wiz.setup_show.isHidden()

    monkeypatch.setattr(directmic, "install", lambda name, **k: "")

    wiz.btn_next.click()   # (Next sets it up while it isn't: then it's ready)
    monkeypatch.setattr(directmic, "status", lambda name=None: "ready")
    assert wiz.setup_show.on
    assert not wiz.setup_show.isHidden()
    assert wiz.btn_attach.isHidden()
    assert wiz.btn_cable.isHidden()
    assert wiz.btn_other.isHidden()

    w._attaching = False
    w.mic_attached.emit("Headset Mic (USB)", "")

    assert wiz.setup_show.on
    assert wiz.status_card.tone == "ok" and "Working" in wiz.status_card.title.text()
    assert not busy.is_busy(wiz.btn_next)
    assert wiz.btn_next.text().startswith("Next")

    from soundboard.ui.busy import _Toast
    toast = wiz.findChild(_Toast)
    assert toast is None or toast.isHidden()

    assert wiz.alt_card.isHidden() and wiz.alt_fold_row.isHidden()   # not during the show
    wiz.setup_show._stop()
    assert not wiz.alt_fold_row.isHidden()
    wiz.alt_fold.click()
    assert not wiz.alt_card.isHidden()
    assert not wiz.btn_alt_cable.isHidden() and not wiz.btn_alt_other.isHidden()
    assert wiz.btn_attach.isHidden()


def test_the_guide_stays_open_while_the_mic_is_set_up(mic_wizard, monkeypatch):
    """While Bun puts the sounds into the mic, Back, Next, Esc and the X do nothing:
    closed or moved on mid-way, they couldn't tell how it went. Esc and the X say why
    (the X doesn't look broken). Afterwards they work again, and a set-up that never
    answers lets them go after LOCK_MAX_S."""
    w, wiz = mic_wizard
    notes = []
    monkeypatch.setattr(busy, "toast", lambda win, text, *a, **kw: notes.append(text))
    wiz.show()
    wiz.go(wiz.base + 2)
    w._attaching = True   # the set-up is running
    wiz._update_next()
    assert busy.is_busy(wiz.btn_next) and busy.is_busy(wiz.btn_back)
    for press in (wiz.next_clicked, wiz.back_clicked, wiz.reject, wiz.close):
        press()
        assert wiz.isVisible() and wiz.stack.currentIndex() == wiz.base + 2
    assert notes == ["Bun's almost done, one moment."] * 2   # Esc and the X, not Back / Next
    w._attaching = False   # done
    wiz._tick()
    assert not busy.is_busy(wiz.btn_next) and not busy.is_busy(wiz.btn_back)
    w._attaching = True    # never answers: let go after LOCK_MAX_S
    assert wiz._locked()
    monkeypatch.setattr(setupwizard.time, "monotonic",
                        lambda t=setupwizard.time.monotonic(): t + setupwizard.LOCK_MAX_S)
    assert not wiz._locked()
    w._attaching = False


@pytest.mark.parametrize("err", ["", "Windows said no"])
def test_the_real_mic_set_up_holds_the_guide_until_it_ends(mic_wizard, qapp, monkeypatch,
                                                          err):
    """The real path: the set-up button, the install on its thread (held until we
    let it go), then success or failure. All the while Back, Next, Esc and the X
    do nothing; once it ends, either way, they all work again."""
    import threading
    from soundboard import directmic
    w, wiz = mic_wizard
    release = threading.Event()

    def install(name, **k):
        release.wait(20)
        return err
    monkeypatch.setattr(directmic, "install", install)
    monkeypatch.setattr(directmic, "status",
                        lambda name=None: "missing" if err or not release.is_set() else "ready")
    wiz.show()
    wiz.go(wiz.base + 2)
    page = wiz.stack.currentIndex()
    wiz.btn_attach.click()
    assert w._attaching and wiz.setup_show.on
    for _round in range(3):   # spammed, with time passing in between
        _settle(qapp, 0.3)
        assert busy.is_busy(wiz.btn_next) and busy.is_busy(wiz.btn_back)
        wiz.btn_next.click()
        wiz.btn_back.click()
        wiz.reject()   # Esc
        wiz.close()    # the X
        assert wiz.isVisible() and wiz.stack.currentIndex() == page
    release.set()   # the set-up ends
    deadline = __import__("time").monotonic() + 10
    while w._attaching and __import__("time").monotonic() < deadline:
        _settle(qapp, 0.05)
    _settle(qapp, 0.4)
    assert not w._attaching
    assert not busy.is_busy(wiz.btn_next) and not busy.is_busy(wiz.btn_back)
    wiz.btn_back.click()   # Back works again
    assert wiz.stack.currentIndex() == page - 1
    wiz.btn_next.click()   # and Next
    assert wiz.stack.currentIndex() == page
    wiz.close()            # and the X closes it
    assert not wiz.isVisible()


def _settle(qapp, s=0.25):
    import time
    t = time.monotonic()
    while time.monotonic() - t < s:
        qapp.processEvents()


def test_back_and_next_never_stretch_the_guide(mic_wizard, qapp):
    """Switching steps: the old step goes before the new one shows. Both shown for
    a moment made the window as tall as the screen (and moved it up) until it
    shrank back, a flash on every Back / Next."""
    from PySide6.QtCore import QEvent, QObject
    from soundboard.ui import fit
    _, wiz = mic_wizard
    wiz.show()
    wiz.go(wiz.base + 3)
    _settle(qapp)
    top = wiz.screen().availableGeometry().y() + 10   # room below for every step
    wiz.move(100, top)
    heights = []

    class Spy(QObject):
        def eventFilter(self, obj, ev):
            if ev.type() == QEvent.Type.Resize:
                heights.append(ev.size().height())
            return False
    spy = Spy(wiz)
    wiz.installEventFilter(spy)
    tall = {}
    for i in (wiz.base + 2, wiz.base + 3) * 2:
        wiz.go(i)
        # its size already, before anything's drawn (not squeezed at the old one)
        assert wiz.height() >= fit.needed_height(wiz, wiz.width())
        _settle(qapp)
        tall[i] = wiz.height()
        assert wiz.y() == top   # never moved
    assert heights and max(heights) <= max(tall.values()), (heights, tall)


def test_a_fold_shut_again_puts_the_guide_back(mic_wizard, qapp, monkeypatch):
    """Near the screen's bottom, opening the Discord tip moves the guide up to fit;
    shutting it puts it back where it was (it walked up the screen click by click)."""
    from soundboard import directmic
    from soundboard.ui import fit
    monkeypatch.setattr(directmic, "works", lambda *a: True)
    w, wiz = mic_wizard
    w.cfg.route = "mic"
    w.cfg.mic_device = w.cfg.mic_device or "Mic"
    wiz.show()
    wiz.go(wiz.base + 3)
    _settle(qapp)
    assert wiz.discord_fold.isVisible()
    wiz.discord_fold.click()   # (it starts open: shut first)
    _settle(qapp)
    avail = wiz.screen().availableGeometry()
    wiz.move(100, avail.bottom() - wiz.frameGeometry().height() - 5)
    _settle(qapp)
    home = wiz.y()
    for _ in range(3):
        wiz.discord_fold.click()
        _settle(qapp)
        assert wiz.y() < home   # open: up to fit
        wiz.discord_fold.click()
        # shut: its size at once, no empty band (opening can widen it a little, for
        # a long button: then it's a bit shorter than before)
        assert wiz.height() == fit.needed_height(wiz, wiz.width())
        _settle(qapp)
        assert wiz.y() == home   # and back where it was
    wiz.discord_fold.click()   # dragged by them meanwhile: it stays where they put it
    _settle(qapp)
    wiz.move(100, 50)
    wiz.discord_fold.click()
    _settle(qapp)
    assert wiz.y() == 50


def test_other_ways_card_explains_and_works(mic_wizard, monkeypatch):
    """On the mic: the cable and another device are optional, in their own card with
    what each is for; Pick a device opens the device list in its place."""
    from soundboard import directmic
    w, wiz = mic_wizard
    monkeypatch.setattr(directmic, "status", lambda name=None: "ready")
    wiz.go(wiz.base + 2)
    assert wiz.status_card.tone == "ok" and "Working" in wiz.status_card.title.text()
    assert wiz.alt_card.isHidden()   # folded under its pill
    wiz.alt_fold.click()
    assert not wiz.alt_card.isHidden()
    texts = " ".join(lbl.text() for lbl in wiz.alt_card.findChildren(setupwizard.QLabel))
    assert "driver" in texts and "Voicemeeter" in texts
    wiz.btn_alt_other.click()
    assert not wiz.other_box.isHidden() and wiz.alt_other_row.isHidden()
    wiz.btn_alt_cable.click()   # the driver works: asked first
    wiz._cable_confirm.btn_use.click()   # the cable is there: used, not installed again
    assert w.cfg.route == "cable" and wiz.alt_card.isHidden()


def test_switching_off_a_working_driver_asks_first(mic_wizard, monkeypatch):
    """Use the cable while the driver works on the mic: a small dialog says it's
    installed and working; Keep my mic (the default, and Escape) changes nothing,
    Tell us why opens the feedback box, Use the cable switches."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from soundboard import directmic
    from soundboard.ui import feedbackdialog
    w, wiz = mic_wizard
    monkeypatch.setattr(directmic, "status", lambda name=None: "ready")
    wiz.show()
    wiz.go(wiz.base + 2)
    wiz.btn_alt_cable.click()
    dlg = wiz._cable_confirm
    assert dlg.isVisible() and dlg.btn_keep.isDefault()
    assert "installed" in " ".join(lbl.text() for lbl in dlg.findChildren(setupwizard.QLabel))
    dlg.btn_keep.click()
    assert w.cfg.route == "mic" and not dlg.isVisible()
    wiz.btn_alt_cable.click()
    QTest.keyClick(wiz._cable_confirm, Qt.Key_Escape)
    assert w.cfg.route == "mic"
    opened = []
    monkeypatch.setattr(feedbackdialog, "ask", lambda cfg, parent=None: opened.append(parent))
    wiz.btn_alt_cable.click()
    wiz._cable_confirm.btn_tell.click()
    assert opened == [wiz] and w.cfg.route == "mic" and not wiz._cable_confirm.isVisible()


def test_cable_without_a_working_driver_isnt_questioned(mic_wizard, monkeypatch):
    from soundboard import directmic
    w, wiz = mic_wizard
    monkeypatch.setattr(directmic, "status", lambda name=None: "missing")
    wiz.go(wiz.base + 2)
    wiz.btn_alt_cable.click()   # nothing to give up: straight to the cable
    assert getattr(wiz, "_cable_confirm", None) is None and w.cfg.route == "cable"


def test_status_card_says_each_state_plainly(mic_wizard, monkeypatch):
    from soundboard import directmic
    _, wiz = mic_wizard
    state = {"s": "missing"}
    monkeypatch.setattr(directmic, "status", lambda name=None: state["s"])
    wiz.go(wiz.base + 2)
    for s, tone in (("missing", ""), ("wiped", "warn"), ("ready", "ok")):
        state["s"] = s
        wiz.recheck_cable(rescan=False)
        card = wiz.status_card
        # (no "Not set up" pill repeating the title: only Working has one)
        assert card.tone == tone and card.title.text()
        assert card.pill.isHidden() == (s != "ready")


def test_discord_tip_folds_away(mic_wizard, monkeypatch):
    """On the mic, Discord needs nothing picked, but its noise filter (on by default)
    wipes sounds out: its tip starts open under its heading, which shuts it. On the
    cable Discord's steps are needed, so nothing folds."""
    from soundboard import directmic
    w, wiz = mic_wizard
    monkeypatch.setattr(directmic, "status", lambda name=None: "ready")
    wiz.go(wiz.base + 3)
    assert not wiz.discord_fold.isHidden() and not wiz.discord_body.isHidden()
    assert not wiz.btn_discord.isHidden()
    assert not wiz.discord_tip.text().startswith("<b>")   # its lead-in is the heading
    assert "Noise Suppression" in wiz.discord_tip.text()
    wiz.discord_fold.click()
    assert wiz.discord_body.isHidden()
    wiz.discord_fold.click()
    assert not wiz.discord_body.isHidden()
    assert wiz.discord_fold.toolTip()   # says Show / Hide
    w.routectl.set_route("cable")
    wiz.go(wiz.base + 3)
    assert wiz.discord_fold.isHidden()
    assert wiz.btn_discord.isHidden() or not wiz.discord_body.isHidden()


def test_discord_pill_is_only_as_wide_as_its_words(mic_wizard, monkeypatch):
    from PySide6.QtWidgets import QSizePolicy
    from soundboard import directmic
    _, wiz = mic_wizard
    monkeypatch.setattr(directmic, "status", lambda name=None: "ready")
    wiz.show()
    wiz.go(wiz.base + 3)
    # its words' width, never stretched across the page (the row's stretch takes the rest)
    assert wiz.discord_fold.width() == wiz.discord_fold.sizeHint().width()
    assert wiz.discord_fold.sizePolicy().horizontalPolicy() == QSizePolicy.Fixed


def test_no_empty_band_after_a_step_grows_the_window(mic_wizard, qapp):
    """fit.watch only grows the window; a step switch could leave it far taller than
    any step needs (an empty band under the last step). It settles back."""
    from PySide6.QtTest import QTest
    from soundboard.ui import fit
    _, wiz = mic_wizard
    wiz.show()
    wiz.go(wiz.base + 3)
    QTest.qWait(setupwizard.SETTLE_MS + 100)
    need = fit.needed_height(wiz, wiz.width())
    wiz.resize(wiz.width(), need + 200)
    wiz.go(wiz.base + 3)
    QTest.qWait(setupwizard.SETTLE_MS + 100)
    assert wiz.height() <= max(need, wiz.minimumHeight()) + 2


def test_cards_line_up_with_back_and_next(mic_wizard, monkeypatch, qapp):
    """The cards' and tiles' edges are Back's left and Next's right (the pages used
    to add their own inset: everything sat 9 px in from the buttons)."""
    from PySide6.QtCore import QPoint
    from soundboard import directmic
    _, wiz = mic_wizard
    monkeypatch.setattr(directmic, "status", lambda name=None: "ready")
    wiz.show()
    wiz.go(wiz.base + 2)
    wiz.alt_fold.click()   # the other ways' card, open
    qapp.processEvents()

    def edges(wd):
        x = wd.mapTo(wiz, QPoint(0, 0)).x()
        return x, x + wd.width()
    left, right = edges(wiz.btn_back)[0], edges(wiz.btn_next)[1]
    for card in (wiz.status_card, wiz.alt_card):
        assert edges(card) == (left, right)
    wiz.go(wiz.base)   # the mic tiles: the first one starts on the same edge
    qapp.processEvents()
    tiles = wiz.mic_group.buttons()
    assert edges(tiles[0])[0] == left
    # a full row of tiles ends on Next's edge: no step makes the window wider than that
    assert wiz.width() == setupwizard.CONTENT_W + 2 * setupwizard.MARGIN


def test_header_ends_where_its_words_do(mic_wizard, qapp):
    """Bun is no taller than a step's title and words: the gap under the words is
    HEADER_GAP, not a band left by a Bun taller than the text beside him."""
    from PySide6.QtCore import QPoint
    _, wiz = mic_wizard
    wiz.show()
    qapp.processEvents()
    page = wiz.stack.currentWidget()   # "What's it for?"
    title, words = page.findChildren(setupwizard.QLabel)[:2]
    bun = page.findChildren(setupwizard.BunnyWidget)[0]

    def y(wd, at_bottom=False):
        return wd.mapTo(wiz, QPoint(0, wd.height() if at_bottom else 0)).y()
    assert y(bun) == y(title)   # top-aligned with the title, not centred below it
    # (+ the room he keeps above him so an upright ear isn't cut at the top of his bob)
    assert bun.height() <= setupwizard.BUN_H + 2 * setupwizard.BUN_PAD + bun._head()
    bottom = max(y(words, True), y(bun, True))
    tiles = y(wiz.use_buttons["normal"])
    assert tiles - bottom <= setupwizard.HEADER_GAP + 8   # (+ the page's own spacing)


def test_tiles_are_as_tall_as_their_names_need(mic_wizard, qapp):
    """One-line names get short tiles (no empty band above and below), long ones get
    room for every line; a list's tiles share one height. A picked name keeps its
    weight, so picking never needs more room."""
    from soundboard.ui.choicetile import ChoiceTile
    _, wiz = mic_wizard
    wiz.show()
    qapp.processEvents()
    short = list(wiz.use_buttons.values())
    assert len({t.height() for t in short}) == 1
    assert short[0].height() == max(setupwizard.TILE_MIN_H,
                                    max(t.needed_height() for t in short))
    long_ = ChoiceTile("x", "volume", setupwizard.TILE_W, 50,
                       title="LG ULTRAGEAR (NVIDIA High Definition Audio)")
    one = ChoiceTile("x", "volume", setupwizard.TILE_W, 50, title="Speakers")
    assert long_.needed_height() > one.needed_height()
    before = short[1].needed_height()
    short[1].click()
    assert short[1].needed_height() == before


def test_test_sound_card_and_a_lone_option_span_the_page(mic_wizard, monkeypatch, qapp):
    """The test sound's card is the page's width (it ended at a spot nothing lined up
    with), and with the device list open the cable's tile fills the optional card's
    row instead of sitting at half width beside a hole."""
    from soundboard import directmic
    _, wiz = mic_wizard
    monkeypatch.setattr(directmic, "status", lambda name=None: "ready")
    wiz.show()
    wiz.go(wiz.base + 1)
    qapp.processEvents()
    card = wiz.btn_test.parentWidget()
    assert card.width() == wiz.btn_next.geometry().right() - wiz.btn_back.x() + 1
    wiz.go(wiz.base + 2)
    wiz._show_other(True)
    qapp.processEvents()
    assert wiz.alt_other_row.isHidden()
    inner = wiz.alt_cable_row.parentWidget().contentsRect().width() - 2 * 14
    assert wiz.alt_cable_row.width() >= inner - 2


def test_step_bar_follows_the_pages(mic_wizard):
    _, wiz = mic_wizard
    for i in range(wiz.PAGES):
        wiz.go(i)
        assert wiz.step_bar.current == i and str(i + 1) in wiz.progress.text()


def test_only_a_brand_new_install_is_asked_what_its_for(wizard, app_dir):
    _, wiz = wizard   # an older config (use_mode saved or missing): no question
    assert not wiz._ask_use and wiz.base == 0 and wiz.PAGES == 4
    assert Config.from_raw({"version": 2}).use_mode == "normal"
    assert FIRST_START.__func__(Config).use_mode == ""


def test_picking_what_its_for_never_resizes_the_guide(mic_wizard, qapp):
    """The words under the tiles are one line for some answers and two for others:
    the guide keeps room for the longest, so clicking between them (spamming
    included) never makes the window grow, shrink and jump around."""
    _, wiz = mic_wizard
    wiz.show()
    qapp.processEvents()
    wiz._settle_size()
    sizes = set()
    for _round in range(2):
        for key in ("normal", "streamer", "games", "all"):
            wiz.use_buttons[key].click()
            qapp.processEvents()
            wiz._settle_size()
            sizes.add((wiz.height(), wiz.use_hint.y(), wiz.btn_next.y()))
    assert len(sizes) == 1, sizes


def test_the_first_launch_asks_what_its_for_first(mic_wizard):
    w, wiz = mic_wizard
    assert wiz._ask_use and wiz.PAGES == 6 and wiz.stack.currentIndex() == 0
    assert wiz.use_buttons["normal"].isChecked()
    assert "Step 1 of 6" in wiz.progress.text()
    wiz.use_buttons["games"].click()
    assert "Triggers" in wiz.use_hint.text()
    assert not w.tabctl.tab_on("triggers")   # nothing changes until Next
    wiz.next_clicked()
    assert w.cfg.use_mode == "games" and w.tabctl.tab_on("triggers")
    assert not w.tabctl.tab_on("apps") and not w.tabctl.tab_on("radio")
    assert wiz.stack.currentIndex() == wiz.base   # on to the mic


def test_streaming_adds_the_apps_tab_and_the_streamer_guide(mic_wizard):
    w, wiz = mic_wizard
    wiz.use_buttons["streamer"].click()
    wiz.next_clicked()
    assert w.tabctl.tab_on("apps") and not w.tabctl.tab_on("triggers")
    wiz.go(wiz.PAGES - 1)
    assert not wiz.btn_streamer.isHidden() and wiz.btn_streamer.toolTip()


def test_just_sounds_changes_nothing(mic_wizard):
    w, wiz = mic_wizard
    off = list(w.cfg.tabs_off)
    wiz.next_clicked()
    assert w.cfg.use_mode == "normal" and w.cfg.tabs_off == off
    wiz.go(wiz.PAGES - 1)
    assert wiz.btn_streamer.isHidden()


def test_closing_on_the_question_never_asks_again(mic_wizard):
    w, wiz = mic_wizard
    wiz.done(0)
    assert w.cfg.use_mode == "normal"
    again = setupwizard.SetupWizard(w)
    assert not again._ask_use
    again.done(0)
    again.deleteLater()



def test_picks_open_the_device_off_the_ui_thread(wizard, devices, monkeypatch, qapp):
    """A pick opens the stream on the device thread: with a recovery holding the
    devices, the click comes straight back, and the device opens once it lets go."""
    import threading
    import time

    from conftest import devices_done
    w, wiz = wizard
    devices_done(w)

    def opener(key):
        def open_it(self, n):
            with engine.DEVICES:
                devices["picked"][key] = n
        return open_it
    for key in ("set_mic_device", "set_mon_device"):
        monkeypatch.setattr(engine.Engine, key, opener(key))
    devices["picked"].clear()
    go, held = threading.Event(), threading.Event()

    def hold():
        with engine.DEVICES:
            held.set()
            go.wait(10)
    t = threading.Thread(target=hold, daemon=True)
    t.start()
    try:
        assert held.wait(5)
        t0 = time.monotonic()
        wiz._pick_mic("Desk Mic", by_user=True)
        wiz._pick_headphones("Speakers", by_user=True)
        assert time.monotonic() - t0 < 0.5
        assert w.cfg.mic_device == "Desk Mic" and devices["picked"] == {}
    finally:
        go.set()
        t.join(5)
    devices_done(w)
    assert devices["picked"] == {"set_mic_device": "Desk Mic", "set_mon_device": "Speakers"}


def test_the_cable_page_and_closing_never_wait_on_the_ui_thread(wizard, devices, monkeypatch,
                                                                 qapp):
    """The cable page opened the cable, and closing the guide reopened every device,
    on the UI thread: a recovery holding the devices froze the window."""
    import threading
    import time

    from conftest import devices_done
    w, wiz = wizard
    devices_done(w)

    def opener(key):
        def open_it(self, n):
            with engine.DEVICES:
                devices["picked"][key] = n
        return open_it
    for key in ("set_main_device", "set_mic_device", "set_mon_device"):
        monkeypatch.setattr(engine.Engine, key, opener(key))
    w.cfg.route = "cable"
    devices["picked"].clear()
    go, held = threading.Event(), threading.Event()

    def hold():
        with engine.DEVICES:
            held.set()
            go.wait(10)
    t = threading.Thread(target=hold, daemon=True)
    t.start()
    try:
        assert held.wait(5)
        t0 = time.monotonic()
        wiz.recheck_cable(rescan=False)
        wiz.reject()
        assert time.monotonic() - t0 < 0.5
        assert devices["picked"] == {}
    finally:
        go.set()
        t.join(5)
    devices_done(w)
    assert engine.is_virtual(devices["picked"]["set_main_device"])
    assert "set_mic_device" in devices["picked"]   # every device reopened on close


def test_closing_the_guide_while_a_hint_flashes(wizard, qapp):
    """"Play a test sound" puts "Playing… hear it?" up for 1.5 s; closing the guide
    in that time crashed when the timer put the title back on the freed label."""
    from PySide6.QtCore import QEvent
    from PySide6.QtTest import QTest
    w, wiz = wizard
    other = setupwizard.SetupWizard(w)
    other._flash_hint("Playing… hear it?", 50)
    other.done(0)
    other.deleteLater()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)
    QTest.qWait(150)   # past the flash: nothing left to touch the label


@pytest.mark.parametrize("route, mic_state, cable", [
    ("mic", "missing", True),    # not on the mic yet: no Discord tip, no Discord button
    ("mic", "ready", True),      # working: the tip under its pill
    ("off", "missing", True),    # sounds only for me
    ("cable", "missing", False),  # the cable isn't installed
    ("cable", "missing", True),  # on the cable: the Discord button, no tip
    ("device", "missing", True),  # another device
])
def test_last_step_never_shows_an_empty_box(wizard, devices, monkeypatch, route,
                                            mic_state, cable):
    """The last step's Discord card shows only with something in it (it was an empty
    box between the words and the closing line when the mic wasn't set up yet)."""
    from soundboard import directmic
    w, wiz = wizard
    devices["cable"] = cable
    monkeypatch.setattr(directmic, "status", lambda name=None: mic_state)
    w.cfg.route = route
    if route == "device":
        w.cfg.main_device = "Speakers"
    wiz.show()
    wiz._fill_discord()
    body = wiz.discord_body
    if not body.isHidden():
        assert (wiz.discord_tip.text() or wiz.discord_live.text()
                or not wiz.btn_discord.isHidden())
    if route == "mic" and mic_state == "missing" or route == "off":
        assert body.isHidden()


def test_the_send_step_says_the_mic_works_before_what_is_missing(mic_wizard, monkeypatch):
    """Step 1 heard you; the send step, not set up, says the mic works (green) above
    "Your sounds aren't in your mic yet", so it can't read as the mic breaking."""
    from soundboard import directmic

    class _S:
        def stop(self):
            pass
        close = stop
    w, wiz = mic_wizard
    monkeypatch.setattr(directmic, "status", lambda name=None: "missing")
    monkeypatch.setattr(w.engine, "mic_stream", _S())
    wiz.show()
    wiz.go(wiz.base + 2)
    wiz.recheck_cable(rescan=False)
    assert not wiz.mic_done.isHidden() and "Your mic works" in wiz.mic_done.text()
    assert wiz.status_card.title.text() == "Your sounds aren't in your mic yet"
    assert "your voice, but not your sounds" in wiz.cable_status.text()
    monkeypatch.setattr(w.engine, "mic_stream", None)   # no mic open: not said
    wiz.recheck_cable(rescan=False)
    assert wiz.mic_done.isHidden()


def test_discord_reads_keep_one_thread(mic_wizard, monkeypatch, qapp):
    # a new thread every 2 s kept the window waiting in Thread.start (2.2.2's freeze at
    # setupwizard._read_discord): every read runs on the same kept thread
    import threading

    from conftest import process_events
    from soundboard import discordcfg
    _, wiz = mic_wizard
    threads = []
    monkeypatch.setattr(discordcfg, "signature",
                        lambda: threads.append(threading.current_thread()) or ("same",))
    monkeypatch.setattr(discordcfg, "read", lambda: None)
    for _ in range(3):
        wiz._read_discord()
        assert process_events(qapp, lambda: not wiz._discord_reading)
    assert len(threads) == 3 and len(set(threads)) == 1
    assert threading.main_thread() not in threads


def test_the_first_launch_ends_on_make_it_yours(mic_wizard):
    w, wiz = mic_wizard
    last = wiz.PAGES - 1
    assert wiz.stack.widget(last).isAncestorOf(wiz.lang_button)
    assert [c.name for c in wiz.look_cards] == setupwizard.look_themes()
    assert len(wiz.look_cards) == 9
    # the Discord step isn't the last one any more: it says Next, and so does its text
    wiz.go(wiz.base + 3)
    assert "Last step" not in wiz.discord_title.text()
    assert "Next" in wiz.closing.text() and "Finish" not in wiz.btn_next.text()
    wiz.go(last)
    assert "Finish" in wiz.btn_next.text()


def test_a_later_guide_has_no_make_it_yours_page(wizard):
    w, _wiz = wizard
    w.cfg.use_mode = "normal"   # "What's it for?" answered long ago
    again = setupwizard.SetupWizard(w)
    try:
        assert not hasattr(again, "look_cards")
        assert again.PAGES == setupwizard.SetupWizard.PAGES
        assert "Last step" in again.discord_title.text()
    finally:
        again.done(0)
        again.deleteLater()


def test_the_seasonal_look_gives_way_once_its_over(monkeypatch):
    from soundboard import theme
    monkeypatch.setattr(theme, "offered", lambda name, today=None: name != "Halloween")
    looks = setupwizard.look_themes()
    assert "Halloween" not in looks and setupwizard.SEASONAL_OFF in looks
    assert len(looks) == len(set(looks)) == 9


def test_picking_a_look_switches_the_theme(mic_wizard):
    from soundboard import theme
    w, wiz = mic_wizard
    wiz.go(wiz.PAGES - 1)
    wiz._pick_look("Ocean")
    assert theme.current_name == "Ocean" and w.cfg.theme == "Ocean"
    assert [c.name for c in wiz.look_cards if c.isChecked()] == ["Ocean"]
    wiz._pick_look("Dark")


def test_a_new_language_restarts_into_it_on_finish(mic_wizard, monkeypatch):
    w, wiz = mic_wizard
    picked, restarts = [], []
    monkeypatch.setattr(w.langctl, "switch_language",
                        lambda code, restart=True: picked.append(code))
    monkeypatch.setattr(w, "restart_app", lambda: restarts.append(1))
    monkeypatch.setattr(w, "set_autostart", lambda on: True)
    wiz.go(wiz.PAGES - 1)
    wiz._pick_language("de")
    assert picked == ["de"] and not wiz.lang_note.isHidden() and wiz.lang_note.text()
    wiz.finish()
    QApplication.processEvents()
    assert restarts == [1]


def test_finish_only_touches_windows_startup_when_the_box_changed(mic_wizard, monkeypatch):
    from soundboard.core import autostart
    w, wiz = mic_wizard
    calls = []
    monkeypatch.setattr(autostart, "is_enabled", lambda: False)
    monkeypatch.setattr(w, "set_autostart", lambda on: calls.append(on) or True)
    wiz.go(wiz.PAGES - 1)
    wiz.chk_autostart.setChecked(True)
    wiz.chk_autostart.setChecked(False)   # ticked and unticked: still as it was
    wiz.finish()
    assert calls == []   # Windows' Run key isn't written


def test_finish_turns_on_windows_startup_when_ticked(mic_wizard, monkeypatch):
    from soundboard.core import autostart
    w, wiz = mic_wizard
    calls = []
    monkeypatch.setattr(autostart, "is_enabled", lambda: False)
    monkeypatch.setattr(w, "set_autostart", lambda on: calls.append(on) or True)
    wiz.go(wiz.PAGES - 1)
    wiz.chk_autostart.setChecked(True)
    wiz.finish()
    assert calls == [True]


def test_the_first_launch_backdrop(qapp, app_dir, devices):
    from soundboard.ui.setupbackdrop import Backdrop
    w = main.MainWindow()
    try:
        w.cfg.use_mode = ""   # the very first launch
        w.resize(900, 600)
        bd = w.setup_backdrop()   # (app.py: before the window first shows)
        w.show()
        assert isinstance(bd, Backdrop) and w.setup_backdrop() is bd   # one, kept
        assert bd.geometry() == w.rect()
        w.resize(1000, 700)
        assert bd.geometry() == w.rect()   # follows the window's size
        bd.settle()   # animations off (offscreen): straight to the corner
        assert bd._k == 1.0
        bd.grab()     # paints, in the corner, without the rail's logo shown
        bd.reveal()   # ...and goes at once
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert w.findChild(Backdrop) is None
        w._backdrop = None
        w.cfg.use_mode = "normal"   # anyone who's been through it: no backdrop
        assert w.setup_backdrop() is None
    finally:
        w.soundctl._load_thread.join(15)
        w.close()
        w.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_the_theme_grid_keeps_to_its_columns(qapp):
    from soundboard.ui.settingspages.appearance import ThemeCard, ThemeGrid
    cards = [ThemeCard(n) for n in setupwizard.look_themes()]
    grid = ThemeGrid(cards, max_columns=3)
    grid.resize(900, 400)   # room for five across
    grid.show()
    QApplication.processEvents()
    assert grid.columns == 3
    grid.deleteLater()
