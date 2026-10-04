"""Settings > General > Reset: parts go back to the start at the next launch, a
restore point is saved first, and restoring it puts back settings and files."""
import json
from pathlib import Path

from PySide6.QtWidgets import QPushButton
from test_mainwindow import window  # noqa: F401 - the real MainWindow, offscreen

from soundboard import library, reset, trash
from soundboard.library import Config, SoundMeta


def _board(app_dir) -> Config:
    library.SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    library.THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    sounds = []
    for sid in ("a1", "b2"):
        f = library.SOUNDS_DIR / f"{sid}.wav"
        f.write_bytes(b"RIFF" + sid.encode())
        img = library.THUMBS_DIR / f"{sid}.png"
        img.write_bytes(b"png")
        sounds.append(SoundMeta(id=sid, name=f"Sound {sid}", file=str(f), image=str(img),
                                hotkey="f5" if sid == "a1" else "", tags=["Memes"]))
    cfg = Config(sounds=sounds, categories=["Memes"], theme="Neon", always_on_top=True,
                 stop_hotkey="f9", random_hotkey="f10", main_device="Cable",
                 setup_done=True, apps={"game.exe": {"vol": 0.5}}, ptt_key="v",
                 radio={"favorites": [{"name": "Jazz"}], "vol": 0.3})
    assert cfg.save()
    return cfg


def _run(parts) -> tuple[str, Config]:
    reset.schedule_reset(parts)
    note = reset.run_pending()
    return note, Config.load()


def test_settings_reset_keeps_sounds_devices_hotkeys_and_radio_favourites(app_dir):
    _board(app_dir)
    note, cfg = _run([reset.SETTINGS])
    assert "Settings" in note and "Restore points" in note
    assert cfg.theme == Config().theme and not cfg.always_on_top and cfg.ptt_key == "v"
    assert [m.id for m in cfg.sounds] == ["a1", "b2"] and cfg.categories == ["Memes"]
    assert cfg.main_device == "Cable" and cfg.setup_done
    assert cfg.stop_hotkey == "f9" and cfg.apps
    assert cfg.radio == {"favorites": [{"name": "Jazz"}]}
    assert not reset._pending_path().exists()   # runs once, not on every start


def test_hotkeys_reset_and_sound_hotkeys(app_dir):
    _board(app_dir)
    _, cfg = _run([reset.HOTKEYS])
    assert cfg.stop_hotkey == "ctrl+alt+s" and cfg.random_hotkey == "" and cfg.ptt_key == ""
    assert cfg.sounds[0].hotkey == "f5" and cfg.theme == "Neon"
    _, cfg = _run([reset.SOUND_KEYS])
    assert all(m.hotkey == "" for m in cfg.sounds)


def test_programs_and_devices(app_dir):
    _board(app_dir)
    _, cfg = _run([reset.PROGRAMS, reset.DEVICES])
    assert cfg.apps == {} and cfg.main_device is None
    assert not cfg.setup_done   # the quick setup picks them again


def test_sounds_and_bin_go_into_the_restore_point_and_come_back(app_dir):
    _board(app_dir)
    m = SoundMeta(id="z9", name="Old one", file=str(library.SOUNDS_DIR / "z9.wav"))
    Path(m.file).write_bytes(b"RIFFz9")
    trash.put_sound(m, 0)
    assert len(trash.items()) == 1
    _, cfg = _run([reset.SOUNDS, reset.BIN])
    assert cfg.sounds == [] and cfg.categories == [] and trash.items() == []
    assert not (library.SOUNDS_DIR / "a1.wav").exists()
    [point] = reset.points()
    assert point.label == "Before reset" and point.describe() == "Sounds, Recently deleted"
    assert (point.path / "sounds" / "a1.wav").exists()
    # a sound added after the reset is kept by the restore
    new = library.SOUNDS_DIR / "c3.wav"
    new.write_bytes(b"RIFFc3")
    cfg.sounds.append(SoundMeta(id="c3", name="New", file=str(new)))
    cfg.save()
    reset.schedule_restore(point.id)
    note = reset.run_pending()
    assert note.startswith("Restored")
    cfg = Config.load()
    assert [m.id for m in cfg.sounds] == ["a1", "b2", "c3"]
    assert Path(cfg.sounds[0].file).read_bytes() == b"RIFFa1"
    assert Path(cfg.sounds[0].image).exists() and cfg.sounds[0].hotkey == "f5"
    assert cfg.categories == ["Memes"]
    [binned] = trash.items()
    assert binned.name == "Old one" and (trash.folder() / "z9.wav").exists()
    # the used point is gone; a "Before restoring" one undoes the restore
    assert [p.label for p in reset.points()] == ["Before restoring"]


def test_restore_puts_settings_back(app_dir):
    _board(app_dir)
    _run([reset.SETTINGS, reset.HOTKEYS])
    [point] = reset.points()
    reset.schedule_restore(point.id)
    reset.run_pending()
    cfg = Config.load()
    assert cfg.theme == "Neon" and cfg.stop_hotkey == "f9" and cfg.always_on_top


def test_only_the_newest_points_are_kept(app_dir):
    _board(app_dir)
    for _ in range(reset.MAX_POINTS + 2):
        _run([reset.PROGRAMS])
    assert len(reset.points()) == reset.MAX_POINTS


def test_a_broken_pending_file_or_point_doesnt_stop_start_up(app_dir):
    _board(app_dir)
    reset._pending_path().write_text("{nope", encoding="utf-8")
    assert reset.run_pending() == ""
    reset.schedule_restore("missing")
    assert "gone" in reset.run_pending()
    assert reset.run_pending() == ""
    assert json.loads(library.CONFIG_PATH.read_text(encoding="utf-8"))["theme"] == "Neon"


def test_guide_picks_parts_and_restarts(window, monkeypatch, qapp):  # noqa: F811
    from soundboard.settings import SettingsDialog
    from soundboard.ui.resetguide import ResetGuide, RestorePoints
    d = SettingsDialog(window, "general")
    assert any(b.text() == "Reset…" for b in d.findChildren(QPushButton))
    restarts = []
    monkeypatch.setattr(window, "restart_app", lambda: restarts.append(1))
    g = ResetGuide(window)
    assert not g.btn_next.isEnabled() and not g.sound_keys.isVisibleTo(g)
    g.boxes[reset.HOTKEYS].setChecked(True)
    assert g.sound_keys.isVisibleTo(g) and g.btn_next.isEnabled()
    g.sound_keys.setChecked(True)
    g.boxes[reset.BIN].setChecked(True)
    assert g.parts() == [reset.HOTKEYS, reset.SOUND_KEYS, reset.BIN]
    g.btn_next.click()
    assert g.page() == 1 and "emptied" in g.summary.text()
    g.btn_go.click()
    qapp.processEvents()
    assert restarts == [1]
    assert json.loads(reset._pending_path().read_text()) == {
        "reset": [reset.HOTKEYS, reset.SOUND_KEYS, reset.BIN]}
    reset.run_pending()
    r = RestorePoints(window)
    assert r.list.count() == 1 and r.btn_restore.isEnabled()
    assert "Hotkeys, Sound hotkeys, Recently deleted" in r.list.item(0).text()


def test_restart_starts_a_copy_that_waits_for_this_one(window, monkeypatch):  # noqa: F811
    import os
    import subprocess
    import sys
    calls, quits = [], []
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: calls.append(args))
    monkeypatch.setattr(window, "quit_app", lambda: quits.append(1))
    monkeypatch.setattr(sys, "argv", ["main.py", "--tray", "--restart-after", "1"])
    window.restart_app()
    assert calls == [[sys.executable, "main.py", "--restart-after", str(os.getpid())]]
    assert quits == [1]
