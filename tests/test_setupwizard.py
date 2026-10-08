"""The quick-setup guide, on Qt's offscreen platform with fake devices: picks reach
the config and engine, the cable page reacts to the cable being there or not, and
finishing marks setup done (only when the cable exists)."""
import pytest

from soundboard import engine, library, winkeys
from soundboard.library import Config
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
    w._load_thread.join(15)
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


def test_missing_cable_offers_install_and_guide_returns(wizard, devices):
    devices["cable"] = False
    w, wiz = wizard
    wiz.go(2)
    assert not wiz.btn_cable.isHidden()
    assert wiz.btn_next.text().startswith("Skip")
    wiz.go(3)
    wiz.next_clicked()
    assert not library.Config.load().setup_done   # shown again next launch


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
        w._load_thread.join(15)
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
        w._load_thread.join(15)
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
        w._load_thread.join(15)
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
    w._load_thread.join(15)
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
    w._load_thread.join(15)
    w.close()
    from PySide6.QtCore import QEvent
    wiz.deleteLater()
    w.deleteLater()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)


def test_new_users_are_offered_their_mic_first(mic_wizard, monkeypatch):
    from soundboard import directmic
    w, wiz = mic_wizard
    assert w.cfg.route == "mic"
    wiz.go(2)
    assert not wiz.btn_attach.isHidden() and "straight into my mic" in wiz.btn_attach.text()
    assert "permission once" in wiz.cable_status.text()
    assert "instead" in wiz.btn_cable.text()
    wiz.go(3)   # not on the mic yet: the last page says so
    assert "isn't on your mic yet" in wiz.discord_text.text()
    monkeypatch.setattr(directmic, "status", lambda name=None: "ready")
    wiz.go(3)
    assert "nothing to pick" in wiz.discord_title.text()
    assert wiz.btn_copy.isHidden() and not wiz.btn_discord.isHidden()


def test_a_repair_is_offered_as_one(mic_wizard, monkeypatch):
    from soundboard import directmic
    _, wiz = mic_wizard
    monkeypatch.setattr(directmic, "status", lambda name=None: "wiped")
    wiz.go(2)
    wiz.recheck_cable(rescan=False)
    assert "Repair" in wiz.btn_attach.text() and "repair" in wiz.cable_status.text()


def test_cable_instead_doesnt_reinstall_a_cable_that_is_there(mic_wizard, monkeypatch):
    w, wiz = mic_wizard
    monkeypatch.setattr(setupwizard.subprocess, "Popen",
                        lambda *a, **k: pytest.fail("installed the cable again"))
    wiz.go(2)
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
    w._load_thread.join(15)
    w.close()
    w.deleteLater()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)
