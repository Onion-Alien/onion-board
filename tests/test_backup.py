"""Export / import (soundboard.backup): a board round-trips through a zip, sound packs
and single sound folders import too, and a crafted archive can't write outside the
library, smuggle in opt-ins or blow up the disk."""
import json
import zipfile

import numpy as np
import pytest
import soundfile as sf

from soundboard import backup, library
from soundboard.library import SR, Config, SoundMeta


def _tone(path, seconds=0.2, freq=440):
    t = np.arange(int(SR * seconds)) / SR
    sf.write(path, np.stack([np.sin(2 * np.pi * freq * t)] * 2, 1) * 0.3, SR)
    return path


@pytest.fixture
def board(app_dir):
    """Two sounds in the library, one with a picture, effects and categories."""
    library.SOUNDS_DIR.mkdir(parents=True)
    library.THUMBS_DIR.mkdir(parents=True)
    a = _tone(library.SOUNDS_DIR / "0123456789_Air horn.wav")
    b = _tone(library.SOUNDS_DIR / "abcdef0123_boom.wav", freq=220)
    pic = library.THUMBS_DIR / "s1.jpg"
    from PySide6.QtGui import QColor, QImage
    img = QImage(8, 8, QImage.Format_RGB32)
    img.fill(QColor("#ff0000"))
    assert img.save(str(pic))
    sounds = [SoundMeta(id="s0", name="Air horn", file=str(a), hotkey="f1", volume=1.5,
                        fx={"speed": 1.5, "start": 0.05}, tags=["Memes"],
                        fingerprint=library.fingerprint(str(a))),
              SoundMeta(id="s1", name="Boom", file=str(b), image=str(pic), color="#13ce66",
                        tags=["Memes", "Game"], fingerprint=library.fingerprint(str(b)))]
    cfg = Config(sounds=sounds, categories=["Memes", "Game", "Empty"], theme="Light",
                 main_device="Speakers (Realtek)", ytdlp_auto_optin=True, stop_hotkey="f9")
    return cfg


def test_export_writes_a_readable_self_describing_zip(board, tmp_path):
    out = tmp_path / "b.zip"
    assert backup.export(out, board.sounds, board, board.categories) == 2
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        man = json.loads(z.read("onionboard.json"))
        s0 = json.loads(z.read("sounds/001 Air horn/sound.json"))
        settings = json.loads(z.read("settings.json"))
    assert man["format"] == "onionboard-board" and man["format_version"] == 1
    assert man["sounds"] == ["sounds/001 Air horn", "sounds/002 Boom"]
    assert man["categories"] == ["Memes", "Game", "Empty"]
    # the library's "<id>_" prefix is dropped: the file has its own name again
    assert "sounds/001 Air horn/Air horn.wav" in names
    assert "sounds/002 Boom/picture.jpg" in names
    assert s0["audio"] == "Air horn.wav" and s0["hotkey"] == "f1" and s0["tags"] == ["Memes"]
    assert s0["fx"]["speed"] == 1.5 and "file" not in s0 and "id" not in s0
    # this PC's devices and the network / code opt-ins never leave it
    assert settings["theme"] == "Light" and settings["stop_hotkey"] == "f9"
    for k in ("main_device", "ytdlp_auto_optin", "sounds", "setup_done"):
        assert k not in settings
    assert not (tmp_path / "b.zip.part").exists()


def test_board_round_trips_into_a_fresh_library(board, tmp_path, app_dir, monkeypatch):
    out = tmp_path / "b.zip"
    backup.export(out, board.sounds, board, board.categories)
    # "a new PC": an empty library somewhere else
    new = tmp_path / "newpc"
    for name, sub in (("SOUNDS_DIR", "sounds"), ("THUMBS_DIR", "thumbs"),
                      ("CACHE_DIR", "cache")):
        monkeypatch.setattr(library, name, new / sub)
    pkg = backup.read(out)
    assert pkg.is_board and len(pkg.sounds) == 2 and pkg.settings["theme"] == "Light"
    res = backup.install(pkg, set())
    assert [m.name for m in res.sounds] == ["Air horn", "Boom"] and not res.failed
    a, b = res.sounds
    assert a.id not in ("s0", "s1") and a.id != b.id
    assert a.hotkey == "f1" and a.volume == 1.5 and a.fx["speed"] == 1.5
    assert a.tags == ["Memes"] and b.tags == ["Memes", "Game"] and b.color == "#13ce66"
    for m in res.sounds:
        assert library.Path(m.file).parent == library.SOUNDS_DIR
        assert library.Path(m.file).is_file()
    assert b.image and library.Path(b.image).parent == library.THUMBS_DIR
    # the audio is the same, and plays
    assert len(library.load_sound(a)) > 0
    cfg = Config()
    changed = backup.apply_settings(cfg, pkg.settings)
    assert cfg.theme == "Light" and cfg.stop_hotkey == "f9" and "theme" in changed
    assert cfg.main_device is None and cfg.ytdlp_auto_optin is False


def test_importing_twice_skips_what_is_already_there(board, tmp_path):
    out = tmp_path / "b.zip"
    backup.export(out, board.sounds, None, board.categories)
    known = {m.fingerprint for m in board.sounds}
    res = backup.install(backup.read(out), known)
    assert res.sounds == [] and res.skipped == ["Air horn", "Boom"]


def test_sound_pack_without_settings(board, tmp_path):
    out = tmp_path / "pack.zip"
    backup.export(out, board.sounds[1:], None, board.categories)
    pkg = backup.read(out)
    assert pkg.settings is None and pkg.categories == ["Memes", "Game"]   # only used ones
    assert [s.entry["name"] for s in pkg.sounds] == ["Boom"]


def test_single_sound_zip_and_folder_import(app_dir, tmp_path):
    folder = tmp_path / "Bruh"
    folder.mkdir()
    _tone(folder / "bruh.wav")
    (folder / "sound.json").write_text(json.dumps({"name": "Bruh", "audio": "bruh.wav",
                                                   "volume": 0.5, "tags": ["Memes"]}))
    pkg = backup.read(folder)                       # an unzipped folder
    assert not pkg.is_board and len(pkg.sounds) == 1
    zp = tmp_path / "bruh.zip"
    with zipfile.ZipFile(zp, "w") as z:            # a zip with the sound at its root
        z.write(folder / "bruh.wav", "bruh.wav")
        z.write(folder / "sound.json", "sound.json")
    res = backup.install(backup.read(zp), set())
    (m,) = res.sounds
    assert m.name == "Bruh" and m.volume == 0.5 and m.tags == ["Memes"] and m.fingerprint


def test_crafted_archive_is_contained(app_dir, tmp_path):
    zp = tmp_path / "evil.zip"
    audio = _tone(tmp_path / "x.wav")
    with zipfile.ZipFile(zp, "w") as z:
        z.write(audio, "../../escape.wav")
        z.write(audio, "a/x.wav")
        z.writestr("a/sound.json", json.dumps({"name": "ok", "audio": "x.wav",
                                               "picture": "../../../pic.jpg",
                                               "volume": 99, "mode": "rm -rf",
                                               "color": "red; drop", "hotkey": 5}))
        z.writestr("b/sound.json", json.dumps({"name": "path", "audio": "../../escape.wav"}))
        z.writestr("c/sound.json", json.dumps({"name": "exe", "audio": "x.exe"}))
        z.writestr("c/x.exe", b"MZ")
    pkg = backup.read(zp)
    assert [s.folder for s in pkg.sounds] == ["a"]    # only the well-formed one
    assert pkg.sounds[0].picture == ""
    (m,) = backup.install(pkg, set()).sounds
    assert library.Path(m.file).parent == library.SOUNDS_DIR
    assert m.volume == 2.0 and m.mode == "restart" and m.color.startswith("#")
    assert m.hotkey == ""                                   # wrong type: default
    assert not (tmp_path.parent / "escape.wav").exists()


def test_oversized_entries_are_refused(app_dir, tmp_path, monkeypatch):
    zp = tmp_path / "big.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("s/big.wav", b"\0" * 200_000)   # compresses to almost nothing
        z.writestr("s/sound.json", json.dumps({"name": "big", "audio": "big.wav"}))
    monkeypatch.setattr(backup, "MAX_FILE", 100_000)
    res = backup.install(backup.read(zp), set())
    assert res.sounds == [] and "too big" in res.failed[0]
    assert not list(library.SOUNDS_DIR.glob("*"))


@pytest.mark.parametrize("make, msg", [
    (lambda p: p.write_bytes(b"not a zip"), "damaged or uses a format"),
    (lambda p: zipfile.ZipFile(p, "w").writestr("readme.txt", "hi"), "isn't an Onion Board"),
    (lambda p: zipfile.ZipFile(p, "w").writestr(
        "onionboard.json", json.dumps({"format": "onionboard-board", "format_version": 99,
                                       "app_version": "9.0"})), "newer Onion Board"),
])
def test_unreadable_archives_explain_themselves(tmp_path, make, msg):
    p = tmp_path / "x.zip"
    make(p)
    with pytest.raises(backup.BackupError, match=msg):
        backup.read(p)


def _manifest(p, **kw):
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("onionboard.json", json.dumps({"format": "onionboard-board", **kw}))
        z.writestr("s/sound.json", json.dumps({"name": "x", "audio": "x.wav"}))
        z.writestr("s/x.wav", b"RIFF")


def test_odd_manifest_values_are_read_or_refused_politely(tmp_path):
    p = tmp_path / "x.zip"
    _manifest(p, format_version="1.0", sounds=None)
    assert [s.folder for s in backup.read(p).sounds] == ["s"]
    _manifest(p, format_version="one")
    with pytest.raises(backup.BackupError, match="damaged or uses a format"):
        backup.read(p)


def test_a_corrupt_zip_stream_is_a_backup_error(tmp_path):
    p = tmp_path / "x.zip"
    body = json.dumps({"format": "onionboard-board", "pad": "abc" * 5000}).encode()
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("onionboard.json", body)
    raw = bytearray(p.read_bytes())
    start = raw.index(b"onionboard.json") + len("onionboard.json")
    raw[start + 5:start + 60] = bytes([0xFF]) * 55      # scramble the deflate stream
    p.write_bytes(bytes(raw))
    with pytest.raises(backup.BackupError, match="damaged"):
        backup.read(p)


def test_an_unexpected_error_fails_one_sound_and_leaves_no_file(app_dir, tmp_path,
                                                                monkeypatch):
    folder = tmp_path / "Bruh"
    folder.mkdir()
    _tone(folder / "bruh.wav")
    (folder / "sound.json").write_text(json.dumps({"name": "Bruh", "audio": "bruh.wav"}))
    pkg = backup.read(folder)

    def boom(*a):
        raise RuntimeError("odd")
    monkeypatch.setattr(backup, "_fill_meta", boom)
    res = backup.install(pkg, set())
    assert res.sounds == [] and res.failed and res.failed[0].startswith("Bruh:")
    assert not list(library.SOUNDS_DIR.glob("*"))


def test_apply_settings_checks_types_and_skips_local_ones():
    cfg = Config()
    changed = backup.apply_settings(cfg, {"theme": 5, "sound_vol": 2, "mic_enabled": "yes",
                                          "pad_width": 180, "cue_sounds": False,
                                          "mic_device": "Evil", "update_check": False,
                                          "no_such_setting": 1})
    assert cfg.theme == Config().theme and cfg.mic_enabled is True
    assert cfg.sound_vol == 2.0 and cfg.pad_width == 180 and cfg.cue_sounds is False
    assert cfg.mic_device is None and cfg.update_check is True
    assert sorted(changed) == ["cue_sounds", "pad_width", "sound_vol"]


def _sound_zip(p, entry, sizes=(("s", 1000),)):
    """A zip with a sound folder per (folder, audio bytes); `entry` goes in each."""
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        for folder, n in sizes:
            z.writestr(f"{folder}/x.wav", b"\0" * n)
            z.writestr(f"{folder}/sound.json", json.dumps({"audio": "x.wav", **entry}))
    return p


def test_non_finite_numbers_in_sound_json_fall_back_to_defaults(app_dir, tmp_path):
    zp = _sound_zip(tmp_path / "nan.zip", {"name": "nan", "volume": float("nan"),
                                           "level_gain": float("inf"),
                                           "fx": {"speed": float("-inf")}})
    assert b"NaN" in zipfile.ZipFile(zp).read("s/sound.json")   # json writes it as is
    (m,) = backup.install(backup.read(zp), set()).sounds
    d = SoundMeta(id="", name="", file="")
    assert m.volume == d.volume and m.level_gain == d.level_gain and m.fx == d.fx


def test_apply_settings_rejects_non_finite_numbers():
    cfg = Config()
    nan = float("nan")
    changed = backup.apply_settings(cfg, {"sound_vol": nan, "mic_vol": float("inf"),
                                          "eq_gains": [0.0, nan, 0, 0, 0, 0, 0],
                                          "voice_fx": {"effects": {"pitch": {"x": nan}}},
                                          "mon_vol": 0.5})
    assert changed == ["mon_vol"]
    assert cfg.sound_vol == 1.0 and cfg.eq_gains == [0.0] * 7 and cfg.voice_fx == {}


def test_apply_settings_eq_gains_must_be_numbers():
    cfg = Config()
    assert backup.apply_settings(cfg, {"eq_gains": ["loud"] * 7}) == []
    assert backup.apply_settings(cfg, {"eq_gains": [1, 2.5, 0, 0, 0, 0, 0]}) == ["eq_gains"]


def test_one_import_is_capped_in_total(app_dir, tmp_path, monkeypatch):
    zp = _sound_zip(tmp_path / "many.zip", {"name": "x"},
                    sizes=[(f"s{i}", 50_000) for i in range(4)])   # each fine on its own
    monkeypatch.setattr(backup, "MAX_TOTAL", 120_000)
    with pytest.raises(backup.BackupError, match="one import can take"):
        backup.install(backup.read(zp), set())
    assert not list(library.SOUNDS_DIR.glob("*"))


def test_import_checks_free_disk_space_first(app_dir, tmp_path, monkeypatch):
    zp = _sound_zip(tmp_path / "x.zip", {"name": "x"}, sizes=[("s", 50_000)])

    class Usage:
        free = 10 << 20
    monkeypatch.setattr(backup.shutil, "disk_usage", lambda p: Usage)
    with pytest.raises(backup.BackupError, match="enough free disk space"):
        backup.install(backup.read(zp), set())
    assert not list(library.SOUNDS_DIR.glob("*"))


def test_writing_more_than_the_archive_declared_stops(app_dir, tmp_path, monkeypatch):
    zp = _sound_zip(tmp_path / "x.zip", {"name": "x"}, sizes=[("a", 1000), ("b", 1000)])
    monkeypatch.setattr(backup, "_check_room", lambda src, pkg: 1500)   # as if it lied
    res = backup.install(backup.read(zp), set())
    assert len(res.sounds) == 1 and "holds more than it says" in res.failed[0]
    assert sorted(p.name for p in library.SOUNDS_DIR.glob("*")) == \
        [library.Path(res.sounds[0].file).name]            # no partial file left


def test_apply_settings_drops_unknown_speech_models_and_languages():
    cfg = Config()
    backup.apply_settings(cfg, {"speech": {"model": "someone/evil-repo", "language": "../x",
                                           "voice": "David", "rate": 2}})
    assert cfg.speech == {"voice": "David", "rate": 2}
    backup.apply_settings(cfg, {"speech": {"model": "small", "language": "auto"}})
    assert cfg.speech == {"model": "small", "language": "auto"}
    backup.apply_settings(cfg, {"speech": {"model": "tiny.en", "language": "de"}})
    assert cfg.speech == {"model": "tiny.en", "language": "de"}
    backup.apply_settings(cfg, {"speech": {"model": 5, "language": "EN"}})
    assert cfg.speech == {}


def test_speech_model_allowlist_matches_the_voice_panel():
    from soundboard.ui import voicepanel
    assert set(backup.SPEECH_MODELS) == {key for _, key in voicepanel.MODELS}


def test_apply_settings_type_checks_radio_fields():
    cfg = Config()
    st = {"uuid": "u", "name": "R", "url": "https://example.com/s"}
    backup.apply_settings(cfg, {"radio": {"vol": "loud", "monitor": "yes", "junk": 1,
                                          "favorites": [st, "x", 3], "recent": "no",
                                          "last": ["x"]}})
    assert cfg.radio == {"favorites": [st]}
    backup.apply_settings(cfg, {"radio": {"vol": 99, "monitor": False, "last": st}})
    assert cfg.radio == {"vol": 10.0, "monitor": False, "last": st}


def _audio_zip(p, tmp_path, names):
    wav = _tone(tmp_path / "tone.wav").read_bytes()
    with zipfile.ZipFile(p, "w") as z:
        for n in names:
            z.writestr(n, wav)
    return p


def test_a_plain_zip_of_sounds_is_found_and_unpacked_safely(app_dir, tmp_path):
    p = _audio_zip(tmp_path / "memes.zip", tmp_path,
                   ["b/Boom.wav", "Air horn.wav", "__MACOSX/._Air horn.wav", "../../evil.wav"])
    with zipfile.ZipFile(p, "a") as z:
        z.writestr("readme.txt", "hi")
    names = backup.loose_audio(p)
    assert names == ["../../evil.wav", "Air horn.wav", "b/Boom.wav"]
    out = tmp_path / "out"
    res = backup.extract_loose(p, names, out)
    assert all(dest is not None and not err for _n, dest, err in res)
    got = [dest for _n, dest, _e in res]
    assert [d.name for d in got] == ["evil.wav", "Air horn.wav", "Boom.wav"]
    assert all(d.resolve().is_relative_to(out.resolve()) and d.stat().st_size for d in got)


def test_backups_packs_and_zips_without_audio_are_not_loose(board, tmp_path):
    pack = tmp_path / "pack.zip"
    backup.export(pack, board.sounds)
    assert backup.loose_audio(pack) == []
    empty = tmp_path / "empty.zip"
    zipfile.ZipFile(empty, "w").writestr("readme.txt", "hi")
    assert backup.loose_audio(empty) == []
    (tmp_path / "bad.zip").write_bytes(b"not a zip")
    assert backup.loose_audio(tmp_path / "bad.zip") == []
    assert backup.loose_audio(tmp_path) == []


def test_a_zip_of_sounds_too_big_to_import_is_refused(app_dir, tmp_path, monkeypatch):
    p = _audio_zip(tmp_path / "big.zip", tmp_path, ["a.wav", "b.wav"])
    monkeypatch.setattr(backup, "MAX_TOTAL", 10)
    with pytest.raises(backup.BackupError, match="Import it in parts"):
        backup.extract_loose(p, backup.loose_audio(p), tmp_path / "out")
    assert not (tmp_path / "out").exists()   # refused before anything is written
