"""The quick-setup guide, on Qt's offscreen platform with fake devices: picks reach
the config and engine, the cable page reacts to the cable being there or not, and
finishing marks setup done (only when the cable exists)."""
import pytest

from soundboard import engine, library, winkeys
from soundboard.library import Config
from soundboard.ui import mainwindow as main
from soundboard.ui import setupwizard

INS = ["Headset Mic (USB)", "Desk Mic", "CABLE Output (VB-Audio Virtual Cable)"]
OUTS = ["Headphones (USB)", "Speakers", "CABLE Input (VB-Audio Virtual Cable)"]


@pytest.fixture
def devices(monkeypatch):
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


@pytest.fixture
def wizard(qapp, app_dir, devices):
    w = main.MainWindow()
    wiz = setupwizard.SetupWizard(w)
    yield w, wiz
    wiz.done(0)
    w._load_thread.join(15)
    w.close()


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
    monkeypatch.setattr(setupwizard.QDesktopServices, "openUrl",
                        lambda url: opened.append(url.toString()))
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
    assert not wiz.btn_restart.isHidden() and wiz.btn_cable.isHidden()

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
