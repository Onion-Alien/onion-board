"""A damaged or hand-edited config.json never stops the app starting, and the user
is told when their settings came from a backup or the defaults."""
import json

from soundboard import library
from soundboard.library import Config


def _write(path, raw):
    path.write_text(json.dumps(raw), encoding="utf-8")


def test_wrong_typed_values_fall_back_to_defaults(app_dir):
    _write(library.CONFIG_PATH, {"tab": "1", "theme": ["x"], "sound_vol": 1, "tray": "yes",
                                 "sounds": [{"id": "a", "name": "A", "file": "a.wav",
                                             "volume": "loud", "tags": None}]})
    cfg = Config.load()
    d = Config()
    assert cfg.tab == d.tab and cfg.theme == d.theme and cfg.tray == d.tray
    assert cfg.sound_vol == 1.0 and isinstance(cfg.sound_vol, float)   # int is fine
    assert len(cfg.sounds) == 1 and cfg.sounds[0].volume == library.SoundMeta("", "", "").volume
    assert cfg.load_note == ""   # nothing was lost, so nothing to say


def test_sounds_not_a_list_is_ignored(app_dir):
    _write(library.CONFIG_PATH, {"sounds": None})
    assert Config.load().sounds == []


def test_broken_config_uses_the_newest_backup_that_loads(app_dir):
    library.CONFIG_PATH.write_text("{not json", encoding="utf-8")
    library.CONFIG_PATH.with_name("config.json.1").write_text("{also broken", encoding="utf-8")
    _write(library.CONFIG_PATH.with_name("config.json.2"), {"stop_hotkey": "f9"})
    cfg = Config.load()
    assert cfg.stop_hotkey == "f9"
    assert "config.json.2" in cfg.load_note
    assert list(app_dir.glob("config.json.broken-*"))   # the damaged file is kept


def test_nothing_loadable_says_so(app_dir):
    library.CONFIG_PATH.write_text("{not json", encoding="utf-8")
    cfg = Config.load()
    assert cfg.sounds == [] and "default settings" in cfg.load_note


def test_first_start_has_defaults_and_nothing_to_say(app_dir):
    cfg = Config.load()
    assert cfg.sounds == [] and cfg.load_note == ""


def test_missing_config_with_backups_recovers_the_newest(app_dir):
    _write(library.CONFIG_PATH.with_name("config.json.1"),
           {"stop_hotkey": "f9", "sounds": [{"id": "a", "name": "A", "file": "a.wav"}]})
    _write(library.CONFIG_PATH.with_name("config.json.2"), {"stop_hotkey": "f7"})
    cfg = Config.load()
    assert cfg.stop_hotkey == "f9" and [s.id for s in cfg.sounds] == ["a"]
    assert "missing" in cfg.load_note and "config.json.1" in cfg.load_note
    assert not list(app_dir.glob("config.json.broken-*"))   # nothing to set aside


def test_missing_config_with_only_bad_backups_says_so(app_dir):
    library.CONFIG_PATH.with_name("config.json.1").write_text("{bad", encoding="utf-8")
    cfg = Config.load()
    assert cfg.sounds == [] and "missing" in cfg.load_note
    assert "default settings" in cfg.load_note


def test_load_note_is_never_saved(app_dir):
    cfg = Config()
    cfg.load_note = "x"
    assert "load_note" not in cfg.to_raw()


def test_save_survives_a_locked_backup(app_dir, monkeypatch):
    Config().save()
    monkeypatch.setattr(library, "_rotate_backups", lambda: (_ for _ in ()).throw(
        PermissionError("locked")))
    cfg = Config()
    cfg.stop_hotkey = "f8"
    assert cfg.save()
    assert json.loads(library.CONFIG_PATH.read_text(encoding="utf-8"))["stop_hotkey"] == "f8"


def test_config_saved_with_a_bom_still_loads(app_dir):
    """Notepad and some scripts save UTF-8 with a byte-order mark: not damage."""
    library.CONFIG_PATH.write_text("﻿" + json.dumps({"stop_hotkey": "f9"}),
                                   encoding="utf-8")
    cfg = Config.load()
    assert cfg.stop_hotkey == "f9" and cfg.load_note == ""


def test_config_that_isnt_an_object_uses_the_backup(app_dir):
    library.CONFIG_PATH.write_text("[]", encoding="utf-8")
    _write(library.CONFIG_PATH.with_name("config.json.1"), {"stop_hotkey": "f9"})
    cfg = Config.load()
    assert cfg.stop_hotkey == "f9" and "config.json.1" in cfg.load_note


def test_another_programs_soundboard_folder_is_left_alone(tmp_path, monkeypatch):
    r"""%APPDATA%\Soundboard is a generic name: only move it if it's this app's."""
    old, new = tmp_path / "Soundboard", tmp_path / "OnionBoard"
    monkeypatch.setattr(library, "OLD_APP_DIR", old)
    monkeypatch.setattr(library, "APP_DIR", new)
    monkeypatch.setattr(library, "SOUNDS_DIR", new / "sounds")
    monkeypatch.setattr(library, "CONFIG_PATH", new / "config.json")
    (old / "Local Storage").mkdir(parents=True)
    _write(old / "config.json", {"boards": [{"name": "Other app"}], "volume": 0.4})
    library.migrate_from_soundboard()
    assert (old / "config.json").exists() and not new.exists()
    # one of ours (a config with sounds / a version, or a sounds folder) still moves
    _write(old / "config.json", {"version": 1, "sounds": []})
    library.migrate_from_soundboard()
    assert not old.exists() and (new / "config.json").exists()


def test_any_sounds_folder_isnt_enough_to_take_the_old_folder(tmp_path, monkeypatch):
    old, new = tmp_path / "Soundboard", tmp_path / "OnionBoard"
    monkeypatch.setattr(library, "OLD_APP_DIR", old)
    monkeypatch.setattr(library, "APP_DIR", new)
    monkeypatch.setattr(library, "SOUNDS_DIR", new / "sounds")
    monkeypatch.setattr(library, "CONFIG_PATH", new / "config.json")
    (old / "sounds").mkdir(parents=True)
    (old / "sounds" / "airhorn.wav").write_bytes(b"x")   # another program's
    library.migrate_from_soundboard()
    assert old.exists() and not new.exists()
    (old / "sounds" / "0123456789_bruh.wav").write_bytes(b"x")   # one of ours
    library.migrate_from_soundboard()
    assert not old.exists() and (new / "sounds" / "0123456789_bruh.wav").exists()


def test_config_from_a_newer_version_is_kept_before_it_is_saved_over(app_dir):
    raw = {"version": library.CONFIG_VERSION + 1, "stop_hotkey": "f9", "future_thing": [1]}
    _write(library.CONFIG_PATH, raw)
    cfg = Config.load()
    assert cfg.stop_hotkey == "f9"
    newer = library.CONFIG_PATH.with_name("config.json.newer")
    assert json.loads(newer.read_text(encoding="utf-8")) == raw
    cfg.stop_hotkey = "f8"
    assert cfg.save()
    Config.load()   # only the first copy is kept
    assert json.loads(newer.read_text(encoding="utf-8")) == raw


def test_current_config_isnt_copied_aside(app_dir):
    _write(library.CONFIG_PATH, {"version": library.CONFIG_VERSION})
    Config.load()
    assert not library.CONFIG_PATH.with_name("config.json.newer").exists()


def test_locked_config_isnt_set_aside_or_saved_over(app_dir, monkeypatch):
    """A file another program holds isn't damaged: a backup is loaded, but nothing is
    saved over the user's newest settings, and the file isn't renamed."""
    _write(library.CONFIG_PATH, {"stop_hotkey": "f9"})
    _write(library.CONFIG_PATH.with_name("config.json.1"), {"stop_hotkey": "f7"})
    real = type(library.CONFIG_PATH).read_text

    def locked(self, *a, **k):
        if self == library.CONFIG_PATH:
            raise PermissionError(13, "The process cannot access the file")
        return real(self, *a, **k)
    with monkeypatch.context() as m:
        m.setattr(type(library.CONFIG_PATH), "read_text", locked)
        m.setattr(library.time, "sleep", lambda s: None)
        cfg = Config.load()
    assert cfg.stop_hotkey == "f7" and "locked" in cfg.load_note
    assert not list(app_dir.glob("config.json.broken-*"))
    assert not cfg.save()
    assert json.loads(library.CONFIG_PATH.read_text(encoding="utf-8"))["stop_hotkey"] == "f9"
    assert not Config.read_only   # only that instance
