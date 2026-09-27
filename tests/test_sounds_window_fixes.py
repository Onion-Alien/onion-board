"""The Sounds tab's categories, copies and imports in the real MainWindow (offscreen):
a renamed / deleted category's hotkey follows it, Undo doesn't bring an old category
back, "Save as new sound" stays in its category, a backup restores sounds that were
just removed, and imported settings a control can't show don't stop the window."""
import json
import zipfile

import numpy as np
import pytest
import soundfile as sf
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QMessageBox

from conftest import process_events
from soundboard import backup, engine, winkeys
from soundboard.library import SR, Config, SoundMeta
from soundboard.ui import mainwindow as main


def _tone(path, seconds=0.1):
    t = np.arange(int(SR * seconds)) / SR
    sf.write(str(path), np.stack([np.sin(2 * np.pi * 440 * t)] * 2, 1) * 0.3, SR)
    return path


def _close(qapp, w):
    w.close()
    if w._load_thread:
        w._load_thread.join(15)
    w.deleteLater()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.fixture
def quiet(monkeypatch):
    """No real devices; the hotkeys each register() call would grab, newest last."""
    for name in ("set_main_device", "set_mon_device", "set_mic_device"):
        monkeypatch.setattr(engine.Engine, name, lambda self, n, _k=name: None)
    registered = []
    monkeypatch.setattr(winkeys.Hotkeys, "register", lambda self, m: registered.append(dict(m)))
    return registered


@pytest.fixture
def window(qapp, app_dir, quiet):
    sounds = [SoundMeta(id=f"s{i}", name=name, file=str(_tone(app_dir / f"{name}.wav")))
              for i, name in enumerate(("Boom", "Airhorn", "Crash"))]
    Config(sounds=sounds).save()
    w = main.MainWindow()
    w._registered = quiet
    w._load_thread.join(15)
    process_events(qapp, lambda: all(p.state == "ready" for p in w.pads.values()), 5)
    yield w
    _close(qapp, w)


def _pack(path, entry, wav):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("s/sound.json", json.dumps({"audio": "a.wav", **entry}))
        z.writestr("s/a.wav", wav)
    return path


# ------------------------------------------------------------------ categories

def test_a_renamed_category_keeps_its_random_hotkey(window):
    window.new_category("s0", name="Memes")
    window.set_category_hotkey("Memes", "f7")
    window.rename_category("Memes", "Jokes")
    assert window._registered[-1].get("f7") == main.RANDOM + "Jokes"
    played = []
    window.play = played.append
    window.on_hotkey(window._registered[-1]["f7"])
    assert played == ["s0"]


def test_a_deleted_category_lets_go_of_its_hotkey(window, monkeypatch):
    window.new_category("s0", name="Memes")
    window.set_category_hotkey("Memes", "f7")
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    window.delete_category("Memes")
    assert "f7" not in window._registered[-1]


def test_undo_after_a_rename_or_delete_does_not_bring_the_old_category_back(window,
                                                                           monkeypatch):
    window.new_category("s0", name="Memes")
    window.new_category("s1", name="Loud")
    window.remove_sound("s0")
    window.rename_category("Memes", "Jokes")
    window.undo_remove()
    assert window.cfg.categories == ["Jokes", "Loud"]
    assert window.meta("s0").tags == ["Jokes"]
    window.remove_sound("s1")
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    window.delete_category("Loud")
    window.undo_remove()
    assert window.cfg.categories == ["Jokes"] and window.meta("s1").tags == []


def test_save_as_new_sound_stays_in_the_category(window, monkeypatch, qapp):
    window.new_category("s0", name="Memes")
    window.set_category("Memes")
    window.meta("s0").fade_in = 1.5

    class AsCopy(main.EditDialog):
        def exec(self):
            self.as_copy = True
            return 1
    monkeypatch.setattr(main, "EditDialog", AsCopy)
    window.edit("s0")
    new = window.cfg.sounds[1]
    assert new.name == "Boom (edit)" and new.tags == ["Memes"] and new.fade_in == 1.5
    assert not window.pads[new.id].property("filtered")
    process_events(qapp, lambda: window.pads[new.id].state == "ready", 5)


def test_the_edit_dialog_does_not_nudge_the_volume(window):
    m = window.meta("s0")
    # the percentages int() used to read one lower (0.29 * 100 = 28.999…)
    drifting = [p for p in range(201) if int(p / 100 * 100) != p]
    assert drifting
    for pct in drifting[:6]:
        m.volume = pct / 100
        d = main.EditDialog(m, window.hotkeys, window.preview, window)
        d.apply()
        d.deleteLater()
        assert round(m.volume * 100) == pct


# ------------------------------------------------------------------ imports

def test_a_backup_restores_sounds_removed_a_moment_ago(window, tmp_path, qapp):
    process_events(qapp, lambda: all(m.fingerprint for m in window.cfg.sounds), 5)
    out = tmp_path / "b.zip"
    backup.export(out, list(window.cfg.sounds))
    window.selection.select_all()
    window.selection.delete()
    assert window.cfg.sounds == []
    window.import_package(str(out))   # still inside the Undo window
    process_events(qapp, lambda: window.status.text().startswith("Imported"), 10)
    window._finish_removals()
    assert [m.name for m in window.cfg.sounds] == ["Boom", "Airhorn", "Crash"]


def test_an_imported_tag_joins_the_category_spelled_differently(window, tmp_path, qapp):
    window.new_category("s0", name="Memes")
    wav = _tone(tmp_path / "w.wav").read_bytes()
    window.import_package(str(_pack(tmp_path / "p.zip", {"name": "x", "tags": ["memes"]},
                                    wav)))
    process_events(qapp, lambda: len(window.cfg.sounds) == 4, 10)
    assert window.cfg.categories == ["Memes"]
    assert window.cfg.sounds[-1].tags == ["Memes"]


def test_an_imported_hotkey_does_not_take_a_categorys(window, tmp_path, qapp):
    window.new_category("s0", name="Memes")
    window.set_category_hotkey("Memes", "f7")
    wav = _tone(tmp_path / "w.wav").read_bytes()
    window.import_package(str(_pack(tmp_path / "p.zip", {"name": "x", "hotkey": "f7"}, wav)))
    process_events(qapp, lambda: len(window.cfg.sounds) == 4, 10)
    assert window.cfg.sounds[-1].hotkey == ""
    assert window.cfg.category_hotkeys == {"Memes": "f7"}
    assert window._registered[-1]["f7"] == main.RANDOM + "Memes"


# ------------------------------------------------------------------ settings

@pytest.mark.parametrize("pad_width", [0, 5000])
def test_pads_are_built_at_a_size_the_slider_can_show(qapp, app_dir, quiet, monkeypatch,
                                                      pad_width):
    cfg = Config(sounds=[SoundMeta(id="a", name="A", file=str(_tone(app_dir / "a.wav")))])
    cfg.pad_width = pad_width
    cfg.save()
    assert Config.load().pad_width == (110 if pad_width < 110 else 240)
    # and the window checks it too, whatever handed it the settings
    monkeypatch.setattr(main.Config, "load", classmethod(lambda cls: cfg))
    w = main.MainWindow()
    try:
        w._load_thread.join(10)
        assert 110 <= w.pads["a"].width() <= 240
        assert w.cfg.pad_width == (110 if pad_width < 110 else 240)
    finally:
        _close(qapp, w)


def test_a_backup_with_damaged_settings_still_opens(qapp, app_dir, quiet, tmp_path):
    """Settings a backup carries that pass the type check but no control can show
    (and voice settings of the wrong shape) mustn't stop the next start."""
    cfg = Config()
    out = tmp_path / "b.zip"
    backup.export(out, [], cfg)
    with zipfile.ZipFile(out) as z:
        files = {n: z.read(n) for n in z.namelist()}
    settings = json.loads(files[backup.SETTINGS])
    settings.update({"sound_vol": 1e9, "mon_vol": 1e300, "pad_width": 0,
                     "eq_enabled": True, "eq_gains": [1e300] * 7,
                     "dest": {"mode": 3, "custom": "nope"},
                     "voice_fx": {"enabled": "yes", "effects": {"robot": "on", "echo": {
                         "on": 1, "mix": "loud"}}},
                     "speech": {"rate": 1e300, "gain": "x", "voice": 3, "model": "evil/x"}})
    files[backup.SETTINGS] = json.dumps(settings)
    with zipfile.ZipFile(out, "w") as z:
        for n, data in files.items():
            z.writestr(n, data)
    pkg = backup.read(out)
    cfg = Config()
    backup.apply_settings(cfg, pkg.settings)
    assert cfg.sound_vol == 10.0 and cfg.eq_gains == [12.0] * 7 and cfg.pad_width == 110
    assert "model" not in cfg.speech and "voice" not in cfg.speech
    cfg.save()
    w = main.MainWindow()
    try:
        w._load_thread.join(10)
        for _ in range(3):
            w.tick()
        assert w.vol_sound.value() == 10.0
    finally:
        _close(qapp, w)
