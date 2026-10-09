"""The sounds folder reads like a music library: a folder per place the sounds came
from (YouTube, TikTok, Recordings, My sounds) and files named after the sounds, not
"<id>_<video id>.flac". Old flat files move in at the start; the bin, restore points
and backups keep each sound's folder."""
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from soundboard import backup, library, reset, trash
from soundboard.engine import SR
from soundboard.library import Config, SoundMeta


def _wav(path: Path, seconds: float = 0.2) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, np.zeros((int(SR * seconds), 2), np.float32), SR, subtype="PCM_16")
    return path


def test_each_site_gets_its_own_folder():
    f = library.site_folder
    assert f("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "YouTube"
    assert f("https://youtu.be/dQw4w9WgXcQ") == "YouTube"
    assert f("https://music.youtube.com/watch?v=x") == "YouTube"
    assert f("https://vm.tiktok.com/ZM123/") == "TikTok"
    assert f("https://www.tiktok.com/@a/video/123") == "TikTok"
    assert f("https://x.com/a/status/1") == "X"
    assert f("https://example.org/a.mp3") == "Downloads"
    assert f("not a link") == "Downloads"
    assert f("https://notyoutube.com/v") == "Downloads"   # a look-alike isn't YouTube


def test_file_names_windows_takes():
    s = library.file_stem
    assert s('Rick Astley - Never Gonna Give You Up (Official Video)') == \
        'Rick Astley - Never Gonna Give You Up (Official Video)'
    assert s('AC/DC: "Back in Black"?') == 'AC_DC_ _Back in Black__'
    assert s("CON") == "_CON" and s("nul.txt") == "_nul.txt"
    assert s("ends with dots...") == "ends with dots"
    assert s("  ") == "Sound" and s("...") == "Sound"
    assert s("日本語の曲 🎵") == "日本語の曲 🎵"
    assert len(s("x" * 300)) == 80


def test_a_download_is_named_after_its_title_in_the_sites_folder(app_dir, tmp_path):
    src = _wav(tmp_path / "dl" / "dQw4w9WgXcQ.wav")   # yt-dlp names it by video id
    a, _ = library.import_file(str(src), "#123456", name="Never Gonna Give You Up",
                               folder="YouTube")
    assert a.file == str(library.SOUNDS_DIR / "YouTube" / "Never Gonna Give You Up.wav")
    assert a.name == "Never Gonna Give You Up" and Path(a.file).is_file()
    b, _ = library.import_file(str(src), "#123456", name="Never Gonna Give You Up",
                               folder="YouTube")   # the same title again: its own file
    assert b.file == str(library.SOUNDS_DIR / "YouTube" / "Never Gonna Give You Up (2).wav")


def test_files_and_clips_and_copies_have_their_folders(app_dir, tmp_path):
    m, _ = library.import_file(str(_wav(tmp_path / "air_horn.wav")), "#123456")
    assert m.file == str(library.SOUNDS_DIR / "My sounds" / "air horn.wav")
    clip, _ = library.save_clip(np.zeros((SR // 10, 2), np.float32), "Replay 12.30.00",
                                "#123456")
    assert clip.file == str(library.SOUNDS_DIR / "Recordings" / "Replay 12.30.00.flac")
    yt, _ = library.import_file(str(_wav(tmp_path / "id.wav")), "#1", name="Song",
                                folder="YouTube")
    copy = library.duplicate(yt, "Song copy")
    assert copy.file == str(library.SOUNDS_DIR / "YouTube" / "Song copy.wav")
    library.delete_file(copy)   # a sound in a folder is still the library's own
    assert not Path(copy.file).exists()


def test_settings_keep_the_folder_relative_and_load_it_back(app_dir, tmp_path):
    m, _ = library.import_file(str(_wav(tmp_path / "id.wav")), "#1", name="Song",
                               folder="YouTube")
    assert Config(sounds=[m]).save()
    raw = json.loads(library.CONFIG_PATH.read_text(encoding="utf-8"))
    assert raw["sounds"][0]["file"] == "YouTube/Song.wav"   # the folder can move
    assert Config.load().sounds[0].file == m.file


def _old_board(app_dir) -> Config:
    """A library from before folders: every file "<id>_<name>" in sounds itself."""
    d = library.SOUNDS_DIR
    files = [d / "a1a1a1a1a1_dQw4w9WgXcQ.flac", d / "b2b2b2b2b2_air horn.wav",
             d / "c3c3c3c3c3_7312345678901234567.flac", app_dir / "elsewhere" / "x.wav"]
    sounds = [SoundMeta(id=sid, name=name, file=str(_wav(f))) for sid, name, f in
              zip(("a1", "b2", "c3", "d4"), ("Never Gonna", "Air horn", "Tok", "Linked"), files)]
    cfg = Config(sounds=sounds)
    assert cfg.save()
    return cfg


def test_old_flat_files_move_into_folders_under_the_sounds_names(app_dir):
    cfg = _old_board(app_dir)
    assert library.tidy_files(cfg) == 3
    d = library.SOUNDS_DIR
    assert [m.file for m in cfg.sounds] == [
        str(d / "YouTube" / "Never Gonna.flac"), str(d / "My sounds" / "Air horn.wav"),
        str(d / "Downloads" / "Tok.flac"), str(app_dir / "elsewhere" / "x.wav")]
    assert all(Path(m.file).is_file() for m in cfg.sounds)
    assert sorted(p.name for p in d.iterdir()) == ["Downloads", "My sounds", "YouTube"]
    assert [m.file for m in Config.load().sounds] == [m.file for m in cfg.sounds]   # saved
    assert library.tidy_files(cfg) == 0   # once


def test_files_go_back_if_the_settings_cant_be_saved(app_dir, monkeypatch):
    cfg = _old_board(app_dir)
    before = [m.file for m in cfg.sounds]
    monkeypatch.setattr(Config, "save", lambda self: False)
    assert library.tidy_files(cfg) == 0
    assert [m.file for m in cfg.sounds] == before and all(Path(f).is_file() for f in before)


def test_locked_settings_or_a_busy_file_leave_things_as_they_are(app_dir, monkeypatch):
    cfg = _old_board(app_dir)
    cfg.read_only = True
    assert library.tidy_files(cfg) == 0
    cfg.read_only = False
    real = library.os.replace

    def busy(a, b):
        if "air horn" in str(a):
            raise PermissionError(32, "in use")
        return real(a, b)
    monkeypatch.setattr(library.os, "replace", busy)
    assert library.tidy_files(cfg) == 2
    assert Path(cfg.sounds[1].file).name == "b2b2b2b2b2_air horn.wav"   # next start
    assert not (library.SOUNDS_DIR / "My sounds" / "Air horn.wav").exists()


def test_the_bin_brings_a_sound_back_into_its_folder(app_dir, tmp_path):
    m, _ = library.import_file(str(_wav(tmp_path / "id.wav")), "#1", name="Song",
                               folder="TikTok")
    trash.put_sound(m, 0)
    assert not Path(m.file).exists() and (trash.folder() / "TikTok" / "Song.wav").exists()
    [it] = trash.items()
    back = trash.meta_of(trash.take(it.id))
    assert back.file == str(library.SOUNDS_DIR / "TikTok" / "Song.wav")
    assert Path(back.file).is_file()


def test_forgetting_a_binned_sound_in_a_folder_deletes_it(app_dir, tmp_path):
    m, _ = library.import_file(str(_wav(tmp_path / "id.wav")), "#1", name="Song",
                               folder="TikTok")
    trash.put_sound(m, 0)
    [it] = trash.items()
    trash.forget(it.id)
    assert not (trash.folder() / "TikTok" / "Song.wav").exists()


def test_a_restore_point_keeps_the_folders(app_dir, tmp_path):
    m, _ = library.import_file(str(_wav(tmp_path / "id.wav")), "#1", name="Song",
                               folder="YouTube")
    assert Config(sounds=[m]).save()
    reset.schedule_reset([reset.SOUNDS])
    reset.run_pending()
    assert not Path(m.file).exists()
    [point] = reset.points()
    assert (point.path / "sounds" / "YouTube" / "Song.wav").exists()
    reset.schedule_restore(point.id)
    assert reset.run_pending().startswith("Restored")
    [back] = Config.load().sounds
    assert back.file == m.file and Path(back.file).is_file()


def test_a_backup_brings_sounds_back_into_their_folders(app_dir, tmp_path, monkeypatch):
    m, _ = library.import_file(str(_wav(tmp_path / "id.wav")), "#1", name="Song",
                               folder="YouTube")
    out = tmp_path / "b.zip"
    assert backup.export(out, [m]) == 1
    for name, sub in (("SOUNDS_DIR", "sounds"), ("THUMBS_DIR", "thumbs"),
                      ("CACHE_DIR", "cache")):
        monkeypatch.setattr(library, name, tmp_path / "newpc" / sub)
    [got] = backup.install(backup.read(out), set()).sounds
    assert got.file == str(library.SOUNDS_DIR / "YouTube" / "Song.wav")


def test_a_backups_folder_name_cant_leave_the_library():
    assert backup._lib_folder("../../Windows") == "_.._Windows"
    assert backup._lib_folder("..") == library.MY_SOUNDS
    assert backup._lib_folder(None) == library.MY_SOUNDS
    assert backup._lib_folder("YouTube") == "YouTube"
