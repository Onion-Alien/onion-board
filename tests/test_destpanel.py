"""Settings → General → Who's listening, and the custom-mode editor."""
from PySide6.QtWidgets import QComboBox

from soundboard import destination
from soundboard.library import Config
from soundboard.settings import SettingsDialog
from soundboard.ui.destpanel import CustomDestDialog, DestPanel, describe
from test_mainwindow import window  # noqa: F401  (the real MainWindow fixture)


def _dest_combo(page) -> QComboBox:
    return next(cb for cb in page.findChildren(QComboBox) if cb.findData("steam") >= 0)


def test_picking_a_mode_applies_and_saves(window):  # noqa: F811
    assert window.engine.dest is None
    d = SettingsDialog(window, "general")
    combo = _dest_combo(d.tabs.currentWidget())
    combo.setCurrentIndex(combo.findData("steam"))
    assert window.engine.dest is not None and window.engine.dest.key == "steam"
    assert window.cfg.dest["mode"] == "steam"
    assert window._save_timer.isActive()
    combo.setCurrentIndex(combo.findData("off"))
    assert window.engine.dest is None
    d.close()


def test_saved_mode_is_applied_at_startup(qapp, app_dir, monkeypatch):
    from test_mainwindow import engine, main, winkeys
    for name in ("set_main_device", "set_mon_device", "set_mic_device"):
        monkeypatch.setattr(engine.Engine, name, lambda self, n, _k=name: None)
    monkeypatch.setattr(winkeys.Hotkeys, "register", lambda self, m: None)
    Config(dest={"mode": "discord"}).save()
    w = main.MainWindow()
    try:
        w._load_thread.join(15)
        assert w.engine.dest is not None and w.engine.dest.key == "discord"
    finally:
        w.close()


def test_custom_mode_add_edit_pick_remove(window):  # noqa: F811
    panel = DestPanel(window)
    dlg = CustomDestDialog(window, panel)
    dlg.add()
    assert len(window.cfg.dest["custom"]) == 1
    dlg.name.setText("Mumble")
    dlg.name.textEdited.emit("Mumble")
    dlg.ceiling.setCurrentIndex(dlg.ceiling.findData(16000))
    dlg.bass.setValue(30)
    dlg.mono.setChecked(False)
    raw = window.cfg.dest["custom"][0]
    assert raw["label"] == "Mumble" and raw["ceiling"] == 16000
    assert abs(raw["bass"] - 0.3) < 1e-9 and raw["mono"] is False
    assert dlg.list.item(0).text() == "Mumble"
    dlg.accept()

    panel.refresh()
    assert panel.combo.findData(raw["key"]) >= 0
    panel.combo.setCurrentIndex(panel.combo.findData(raw["key"]))
    e = window.engine.dest
    assert e is not None and e.custom and e.ceiling == 16000 and not e.mono
    assert "16 kHz" in panel.desc.text()

    # editing the mode in use reaches the engine straight away
    dlg = CustomDestDialog(window, panel)
    dlg.list.setCurrentRow(0)
    dlg.comp.setValue(80)
    assert abs(window.engine.dest.comp - 0.8) < 1e-9
    # removing it falls back to Off
    dlg.remove()
    assert window.cfg.dest["custom"] == [] and window.cfg.dest["mode"] == "off"
    assert window.engine.dest is None
    dlg.accept()
    panel.refresh()
    assert panel.combo.currentData() == "off"


def test_copy_builtin_starts_from_its_settings(window, monkeypatch):  # noqa: F811
    from PySide6.QtWidgets import QInputDialog
    steam = destination.BUILTIN_BY_KEY["steam"]
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: (steam.label, True)))
    dlg = CustomDestDialog(window)
    dlg.copy_builtin()
    raw = window.cfg.dest["custom"][0]
    assert raw["ceiling"] == 12000 and raw["key"] not in destination.BUILTIN_BY_KEY
    assert raw["label"].endswith("(copy)")
    dlg.accept()


def test_describe_lines():
    assert describe(destination.OFF) == destination.OFF.note
    s = describe(destination.BUILTIN_BY_KEY["steam"])
    assert "mono" in s and "12 kHz" in s and "harmonics 60%" in s
