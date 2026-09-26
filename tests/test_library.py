import json
from pathlib import Path

import numpy as np
import pytest

from soundboard import library
from soundboard.library import SR, Config, SoundMeta, level_gain, trim_silence


def sine(db, seconds=2.0, hz=440):
    t = np.arange(int(seconds * SR)) / SR
    a = 10 ** (db / 20)
    return np.stack([np.sin(2 * np.pi * hz * t) * a] * 2, 1).astype(np.float32)


# ---------------------------------------------------------------- level_gain

def test_silence_gets_unity_gain():
    assert level_gain(np.zeros((SR, 2), np.float32)) == 1.0
    assert level_gain(np.zeros((0, 2), np.float32)) == 1.0


def test_quiet_sound_is_brought_up_to_target():
    x = sine(-25)                    # -28 dB RMS: within the 6x gain clamp of the target
    g = level_gain(x)
    rms = np.sqrt(((x * g).mean(axis=1) ** 2).mean())
    assert abs(20 * np.log10(rms) - library.TARGET_RMS_DB) < 1.0


def test_loud_sound_is_brought_down_and_gain_is_clamped():
    assert level_gain(sine(-1)) < 1.0
    assert 0.1 <= level_gain(sine(-90)) <= 6.0


def test_leading_silence_does_not_skew_the_level():
    x = sine(-30, seconds=1.0)
    padded = np.concatenate([np.zeros((5 * SR, 2), np.float32), x])
    assert abs(level_gain(x) - level_gain(padded)) / level_gain(x) < 0.05


# ---------------------------------------------------------------- trim_silence

def test_trim_keeps_a_small_pad_around_the_sound():
    x = np.zeros((SR, 2), np.float32)
    x[20000:30000] = 0.5
    y = trim_silence(x, pad_s=0.05)
    pad = int(0.05 * SR)
    assert len(y) == 10000 + 2 * pad - 1


def test_trim_all_silence_is_empty():
    assert len(trim_silence(np.zeros((1000, 2), np.float32))) == 0


# ---------------------------------------------------------------- Config

def test_config_round_trip(app_dir):
    inside = str(library.SOUNDS_DIR / "x.wav")
    c = Config(sound_vol=1.5, stop_hotkey="ctrl+alt+x", latency="high",
               sounds=[SoundMeta(id="abc", name="Boom", file=inside, hotkey="f5"),
                       SoundMeta(id="def", name="Out", file=r"D:\elsewhere\y.wav")])
    assert c.save()
    assert not (app_dir / "config.tmp").exists()          # atomic replace cleaned up
    d = Config.load()
    assert d.sound_vol == 1.5 and d.stop_hotkey == "ctrl+alt+x" and d.latency == "high"
    assert d.sounds == c.sounds                           # absolute again in memory
    raw = json.loads(library.CONFIG_PATH.read_text(encoding="utf-8"))
    assert raw["version"] == library.CONFIG_VERSION
    assert raw["sounds"][0]["file"] == "x.wav"            # library files stored by name...
    assert raw["sounds"][1]["file"] == r"D:\elsewhere\y.wav"   # ...others as they are


def test_v1_config_is_migrated_and_rewritten_relative(app_dir):
    inside = str(library.SOUNDS_DIR / "old.wav")
    raw = {"sound_vol": 0.8, "sounds": [{"id": "a", "name": "n", "file": inside}]}  # no version
    library.CONFIG_PATH.write_text(json.dumps(raw), encoding="utf-8")
    c = Config.load()
    assert c.version == library.CONFIG_VERSION and c.sounds[0].file == inside
    c.save()
    raw2 = json.loads(library.CONFIG_PATH.read_text(encoding="utf-8"))
    assert raw2["version"] == library.CONFIG_VERSION and raw2["sounds"][0]["file"] == "old.wav"


@pytest.mark.parametrize("old, new", [(0, 0), (1, 0), (2, 1), (3, 2), (4, 3), (5, 4)])
def test_v2_config_moves_tabs_down_past_the_removed_browser_tab(old, new):
    c = Config.from_raw({"version": 2, "tab": old, "browser_live": True,
                         "rec_hotkey": "ctrl+alt+r"})
    assert c.tab == new and not hasattr(c, "browser_live") and not hasattr(c, "rec_hotkey")


def test_save_keeps_rotating_backups_only_when_something_changed(app_dir):
    c = Config()
    for vol in (0.1, 0.2, 0.3, 0.4, 0.5):
        c.sound_vol = vol
        c.save()
    c.save()                                              # unchanged: no rotation
    backups = sorted(p.name for p in app_dir.glob("config.json.*"))
    assert backups == ["config.json.1", "config.json.2", "config.json.3"]
    assert json.loads((app_dir / "config.json.1").read_text())["sound_vol"] == 0.4
    assert json.loads((app_dir / "config.json.3").read_text())["sound_vol"] == 0.2


def test_corrupt_config_is_set_aside_and_recovered_from_backup(app_dir, caplog):
    c = Config(sound_vol=0.42, sounds=[SoundMeta(id="k", name="Keep", file="k.wav")])
    c.save()
    c.sound_vol = 0.43
    c.save()                                              # config.json.1 now holds 0.42
    library.CONFIG_PATH.write_text("{not json", encoding="utf-8")
    with caplog.at_level("WARNING"):
        d = Config.load()
    assert d.sounds[0].name == "Keep" and d.sound_vol == 0.42
    assert list(app_dir.glob("config.json.broken-*"))
    assert "recovered settings from backup" in caplog.text


def test_unknown_and_missing_fields_are_tolerated(app_dir):
    raw = {"sound_vol": 0.5, "future_setting": 1,
           "sounds": [{"id": "a", "name": "n", "file": "f", "future_field": True}]}
    library.CONFIG_PATH.write_text(json.dumps(raw), encoding="utf-8")
    c = Config.load()
    assert c.sound_vol == 0.5
    assert c.mon_vol == 0.7                                  # default kept
    assert c.sounds[0].id == "a" and c.sounds[0].volume == 1.0


def test_missing_config_gives_defaults(app_dir):
    assert Config.load() == Config()


def test_corrupt_config_without_backups_gives_defaults_and_is_logged(app_dir, caplog):
    library.CONFIG_PATH.write_text("{not json", encoding="utf-8")
    with caplog.at_level("ERROR"):
        c = Config.load()
    assert c == Config()
    assert "unreadable" in caplog.text
    assert not library.CONFIG_PATH.exists()               # set aside, not overwritten


def test_valid_json_but_bad_config_falls_back_to_backup(app_dir):
    good = Config(sounds=[SoundMeta(id="a", name="A", file=str(app_dir / "a.wav"))])
    good.save()
    good.theme = "Ocean"
    good.save()                                   # a change: leaves config.json.1
    library.CONFIG_PATH.write_text('{"version": "two", "sounds": [{"name": 1}]}',
                                   encoding="utf-8")
    cfg = Config.load()                           # must not raise
    assert [s.id for s in cfg.sounds] == ["a"]


def test_damaged_sound_entries_are_skipped(app_dir):
    library.CONFIG_PATH.write_text(
        '{"version": 2, "sounds": [{"id": "a", "name": "A", "file": "a.wav"}, {"id": "b"}, 7]}',
        encoding="utf-8")
    assert [s.id for s in Config.load().sounds] == ["a"]


def test_a_failed_copy_into_the_library_raises_and_leaves_nothing(app_dir, tmp_path,
                                                                   monkeypatch):
    import pytest
    import soundfile as sf
    src = tmp_path / "boom.wav"
    sf.write(src, np.zeros((SR // 10, 2), np.float32), SR)

    def half_copy(a, b):
        open(b, "wb").write(b"RIFF")    # a partial file, then the disk fills up
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(library.shutil, "copy2", half_copy)
    with pytest.raises(OSError, match="disk isn't full"):
        library.import_file(str(src), "#123456")
    assert not list(library.SOUNDS_DIR.glob("*"))


def _old_folder(tmp_path, monkeypatch):
    r"""An old %APPDATA%\Soundboard with a v0.1.0-style config (full paths)."""
    old, new = tmp_path / "Soundboard", tmp_path / "OnionBoard"
    monkeypatch.setattr(library, "OLD_APP_DIR", old)
    monkeypatch.setattr(library, "APP_DIR", new)
    monkeypatch.setattr(library, "SOUNDS_DIR", new / "sounds")
    monkeypatch.setattr(library, "CONFIG_PATH", new / "config.json")
    (old / "sounds").mkdir(parents=True)
    (old / "sounds" / "a_x.wav").write_bytes(b"RIFF")
    (old / "config.json").write_text(json.dumps({"version": 1, "sounds": [
        {"id": "a", "name": "x", "file": str(old / "sounds" / "a_x.wav")}]}), "utf-8")
    return old, new


def test_migration_moves_the_old_folder_and_fixes_full_paths(tmp_path, monkeypatch):
    old, new = _old_folder(tmp_path, monkeypatch)
    library.migrate_from_soundboard()
    assert not old.exists() and (new / "sounds" / "a_x.wav").exists()
    cfg = library.Config.load()
    assert Path(cfg.sounds[0].file) == new / "sounds" / "a_x.wav"


def test_migration_still_runs_when_the_installer_made_the_new_folder(tmp_path, monkeypatch):
    old, new = _old_folder(tmp_path, monkeypatch)
    new.mkdir()
    (new / "cable-restart-pending").write_text("1")
    library.migrate_from_soundboard()
    assert (new / "config.json").exists() and (new / "sounds" / "a_x.wav").exists()
    assert (new / "cable-restart-pending").read_text() == "1"


def test_migration_leaves_an_existing_new_config_alone(tmp_path, monkeypatch):
    old, new = _old_folder(tmp_path, monkeypatch)
    new.mkdir()
    (new / "config.json").write_text("{}", "utf-8")
    library.migrate_from_soundboard()
    assert (new / "config.json").read_text("utf-8") == "{}" and old.exists()


def test_non_finite_numbers_in_a_config_fall_back_to_defaults():
    assert not library.fits_type(1.0, float("nan"))
    assert not library.fits_type(1.0, float("inf"))
    assert library.fits_type(1.0, 2)
