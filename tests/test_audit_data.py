"""Data-safety fixes: nothing a damaged or locked side file, a failed restore or a
newer version's settings hold is quietly lost."""
import json
import struct
from pathlib import Path

import pytest

from conftest import own_time
from soundboard import library, reset, resanance, soundux, trash, videos
from soundboard.library import Config, SoundMeta


def _lock(monkeypatch, name: str):
    """`name` is held by another program: reading it fails."""
    real = Path.read_text

    def read_text(self, *a, **k):
        if self.name == name:
            raise PermissionError(32, "being used by another process")
        return real(self, *a, **k)
    monkeypatch.setattr(Path, "read_text", read_text)
    own_time(monkeypatch, trash, sleep=lambda s: None)
    return real


def _sound(sid: str) -> SoundMeta:
    library.SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    f = library.SOUNDS_DIR / f"{sid}.wav"
    f.write_bytes(b"RIFF" + sid.encode())
    return SoundMeta(id=sid, name=f"Sound {sid}", file=str(f))


# --------------------------------------------------------------------------- reset
def _point_with_bin(app_dir) -> reset.Point:
    cfg = Config(sounds=[_sound("a1")])
    assert cfg.save()
    trash.put_sound(_sound("z9"), 0)
    reset.schedule_reset([reset.BIN, reset.SOUNDS])
    reset.run_pending()
    [point] = reset.points()
    return point


def test_a_restore_keeps_a_bin_that_couldnt_come_back(app_dir, monkeypatch):
    point = _point_with_bin(app_dir)
    real = _lock(monkeypatch, "deleted.json")   # the restore point's bin list too
    note = reset.restore(point.id)
    monkeypatch.setattr(Path, "read_text", real)
    assert "Restored" in note and "kept in this restore point" in note
    assert [m.id for m in Config.load().sounds] == ["a1"]
    assert (point.path / "deleted" / "z9.wav").exists()        # not deleted with it
    assert point.id in [p.id for p in reset.points()]
    assert "Restored" in reset.restore(point.id)               # and it comes in later
    assert [i.data["id"] for i in trash.items()] == ["z9"]
    assert not point.path.exists()


def test_a_restore_keeps_files_whose_name_is_taken(app_dir):
    cfg = Config(sounds=[_sound("a1")])
    assert cfg.save()
    reset.schedule_reset([reset.SOUNDS])
    reset.run_pending()
    [point] = reset.points()
    (library.SOUNDS_DIR / "a1.wav").write_bytes(b"other")   # something took its name
    reset.restore(point.id)
    assert (point.path / "sounds" / "a1.wav").read_bytes() == b"RIFFa1"


def test_a_restore_that_cant_save_puts_the_files_back(app_dir, monkeypatch):
    cfg = Config(sounds=[_sound("a1")])
    assert cfg.save()
    reset.schedule_reset([reset.SOUNDS])
    reset.run_pending()
    [point] = reset.points()
    monkeypatch.setattr(Config, "save", lambda self: False)
    assert reset.restore(point.id) == "Couldn't save the restored settings. Nothing was changed."
    assert (point.path / "sounds" / "a1.wav").exists()
    assert not (library.SOUNDS_DIR / "a1.wav").exists()


def test_a_restore_failing_partway_puts_the_files_back(app_dir, monkeypatch):
    cfg = Config(sounds=[_sound("a1")])
    assert cfg.save()
    reset.schedule_reset([reset.SOUNDS])
    reset.run_pending()
    [point] = reset.points()

    def boom(*a):
        raise OSError("disk gone")
    monkeypatch.setattr(library, "merge_tags", boom)
    with pytest.raises(OSError):
        reset.restore(point.id)
    assert (point.path / "sounds" / "a1.wav").exists()


def test_resetting_devices_drops_a_newer_route(app_dir):
    raw = Config().to_raw()
    raw["route"] = "a-newer-route"
    library.CONFIG_PATH.write_text(json.dumps(raw), encoding="utf-8")
    reset.schedule_reset([reset.DEVICES])
    reset.run_pending()
    # back to the default for this PC: straight into the mic (the main way since 1.9.1)
    assert json.loads(library.CONFIG_PATH.read_text(encoding="utf-8"))["route"] == "mic"


# --------------------------------------------------------------------------- videos
def test_unreadable_videos_json_is_never_saved_over(app_dir, monkeypatch):
    videos.link("a1", app_dir / "a.mp4")
    real = _lock(monkeypatch, "videos.json")
    videos.link("b2", app_dir / "b.mp4")
    videos.copy_link("a1", "c3")
    monkeypatch.setattr(Path, "read_text", real)
    assert set(videos._load()) == {"a1"}


def test_damaged_videos_json_is_set_aside(app_dir):
    videos._path().write_text("{nope", encoding="utf-8")
    videos.link("a1", app_dir / "a.mp4")
    assert set(videos._load()) == {"a1"}
    assert list(app_dir.glob("videos.json.broken-*"))


# --------------------------------------------------------------------------- trash
def test_a_damaged_bin_list_is_set_aside_before_starting_over(app_dir):
    trash.folder().mkdir(parents=True)
    trash._index().write_text("{nope", encoding="utf-8")
    trash.put_sound(_sound("a1"), 0)
    assert [i.data["id"] for i in trash.items()] == ["a1"]
    [broken] = trash.folder().glob("deleted.json.broken-*")
    assert broken.read_text(encoding="utf-8") == "{nope"


def test_a_sound_binned_while_the_list_is_locked_isnt_left_unlisted(app_dir, monkeypatch):
    trash.put_sound(_sound("k1"), 0)
    real = _lock(monkeypatch, "deleted.json")
    m = _sound("a1")
    trash.put_sound(m, 0)
    monkeypatch.setattr(Path, "read_text", real)
    assert not (trash.folder() / "a1.wav").exists()   # removed, as before the bin
    assert [i.data["id"] for i in trash.items()] == ["k1"]


def test_emptying_part_of_a_locked_bin_keeps_the_rest(app_dir, monkeypatch):
    trash.put_sound(_sound("k1"), 0)
    trash.put_app("game.exe", {"vol": 0.5}, "Game")
    real = _lock(monkeypatch, "deleted.json")
    trash.empty(trash.APP)
    monkeypatch.setattr(Path, "read_text", real)
    assert len(trash.items()) == 2 and (trash.folder() / "k1.wav").exists()


def test_a_newer_versions_pad_fields_survive_the_bin(app_dir):
    m = _sound("a1")
    m._raw_extra = {"sparkle": 3}
    m._raw_kept = {"mode": ("restart", "a-newer-mode")}
    trash.put_sound(m, 0)
    [it] = trash.items()
    back = trash.meta_of(trash.take(it.id))
    assert back.mode == "restart"   # safe in this version
    s = Config(sounds=[back]).to_raw()["sounds"][0]
    assert s["sparkle"] == 3 and s["mode"] == "a-newer-mode"


# --------------------------------------------------------------------------- library
def test_a_newer_versions_settings_survive_a_save(app_dir):
    raw = Config(sounds=[_sound("a1")]).to_raw()
    raw.update(route="a-newer-route", net_mode="i2p", future_setting={"x": 1})
    raw["sounds"][0].update(mode="a-newer-mode", future_pad_field=[1, 2])
    library.CONFIG_PATH.write_text(json.dumps(raw), encoding="utf-8")
    cfg = Config.load()
    assert cfg.route == "cable" and cfg.net_mode == "proxy"   # safe in this version
    assert cfg.sounds[0].mode == "restart"
    cfg.theme = "Neon"
    assert cfg.save()
    saved = json.loads(library.CONFIG_PATH.read_text(encoding="utf-8"))
    assert saved["route"] == "a-newer-route" and saved["net_mode"] == "i2p"
    assert saved["future_setting"] == {"x": 1} and saved["theme"] == "Neon"
    assert saved["sounds"][0]["mode"] == "a-newer-mode"
    assert saved["sounds"][0]["future_pad_field"] == [1, 2]


def test_a_changed_setting_isnt_put_back_to_the_newer_value(app_dir):
    raw = Config().to_raw()
    raw["route"] = "a-newer-route"
    cfg = Config.from_raw(raw)
    cfg.route = "device"
    assert cfg.to_raw()["route"] == "device"


@pytest.mark.parametrize("text", ['{"version": 1e999}', '{"version": -1e999}'])
def test_an_infinite_version_reads_as_damaged(app_dir, text):
    library.CONFIG_PATH.write_text(text, encoding="utf-8")
    cfg = Config.load()   # used to raise OverflowError
    assert cfg.load_note
    with pytest.raises(ValueError):
        Config.from_raw(json.loads(text))


def test_duplicate_keeps_only_them_delay_and_cooldown(app_dir):
    m = _sound("a1")
    m.only_them, m.delay, m.cooldown = True, 1.5, 4.0
    d = library.duplicate(m, "Copy")
    assert d.only_them and d.delay == 1.5 and d.cooldown == 4.0


def test_a_damaged_config_isnt_rotated_into_the_backups(app_dir, monkeypatch):
    assert Config(theme="Good").save()
    assert Config(theme="Good2").save()           # config.json.1 is a good copy now
    good = library.CONFIG_PATH.with_name("config.json.1").read_text(encoding="utf-8")
    library.CONFIG_PATH.write_text("{nope", encoding="utf-8")
    monkeypatch.setattr(Config, "_set_aside", classmethod(lambda cls: ""))   # couldn't be
    cfg = Config.load()
    assert cfg.theme == "Good"
    assert cfg.save()
    assert library.CONFIG_PATH.with_name("config.json.1").read_text(encoding="utf-8") == good
    assert "{nope" not in [p.read_text(encoding="utf-8")
                           for p in app_dir.glob("config.json.*")]


# --------------------------------------------------------------------------- imports
def test_resanance_negative_lengths_dont_loop_forever():
    for t, payload in ((0x02, struct.pack("<i", -20)), (0x05, struct.pack("<i", -20) + b"\0")):
        body = bytes([t]) + b"k\0" + payload + b"\0" * 8
        doc = struct.pack("<i", 4 + len(body) + 1) + body + b"\0"
        with pytest.raises(ValueError):
            resanance._bson(doc, 0)
    with pytest.raises(ValueError):
        resanance._bson(struct.pack("<i", -8) + b"\0" * 8, 0)


@pytest.mark.parametrize("data", [None, [], "x", 3])
def test_soundux_odd_data_is_not_a_config(tmp_path, data):
    p = tmp_path / "soundux.json"
    p.write_text(json.dumps({"data": data}), encoding="utf-8")
    with pytest.raises(ValueError):
        soundux.read(p)
