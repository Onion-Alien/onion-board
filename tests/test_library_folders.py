"""The sounds folder reads like a music library: a folder per place the sounds came
from (YouTube, TikTok, Recordings, My sounds) and files named after the sounds, not
"<id>_<video id>.flac". Old flat files move in at the start; the bin, restore points
and backups keep each sound's folder."""
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from soundboard.core import backup, reset, trash
from soundboard.sounds import library
from soundboard.audio.engine import SR
from soundboard.sounds.library import Config, SoundMeta


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
    assert clip.file == str(library.SOUNDS_DIR / "Recordings" / "Replay 12.30.00.mp3")
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


def test_the_moves_list_stays_until_the_settings_are_on_the_disk(app_dir, monkeypatch):
    """Deleted after a save that never reached the disk, a power cut would leave the
    sounds naming files that moved, with nothing to move them back."""
    cfg = _old_board(app_dir)
    before = [m.file for m in cfg.sounds]
    real_fsync, real_replace = library.os.fsync, library.os.replace

    def fsync(fd):   # the moves list's own fsync is fine; the settings' fails
        if list(app_dir.glob("config.json.*.tmp")):
            raise OSError(5, "I/O error")
        real_fsync(fd)

    def stuck(a, b):   # a file open in another program won't go back
        if "Air horn" in str(a):
            raise PermissionError(32, "in use")
        return real_replace(a, b)

    with monkeypatch.context() as mp:
        mp.setattr(library.os, "fsync", fsync)
        mp.setattr(library.os, "replace", stuck)
        assert library.tidy_files(cfg) == 0
    assert (app_dir / "tidy-moves.txt").exists()   # the next start puts it back
    assert [m.file for m in Config.load().sounds] == before
    assert library._undo_tidy(Config.load()) == 1
    assert all(Path(f).is_file() for f in before)
    assert not (app_dir / "tidy-moves.txt").exists()


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


def test_a_crash_before_the_save_is_undone_at_the_next_start(app_dir, monkeypatch):
    cfg = _old_board(app_dir)
    before = [m.file for m in cfg.sounds]

    def power_cut(self):
        raise KeyboardInterrupt   # the app gone between the moves and the save
    with monkeypatch.context() as mp:
        mp.setattr(Config, "save", power_cut)
        try:
            library.tidy_files(cfg)
        except KeyboardInterrupt:
            pass
    assert not Path(before[0]).exists()   # moved, but the settings still name it
    cfg = Config.load()
    assert [m.file for m in cfg.sounds] == before
    assert library.tidy_files(cfg) == 3   # put back, then moved again and saved
    assert all(Path(m.file).is_file() for m in Config.load().sounds)
    assert not (app_dir / "tidy-moves.txt").exists()
    assert sorted(p.name for p in (library.SOUNDS_DIR / "YouTube").iterdir()) == \
        ["Never Gonna.flac"]   # no "Never Gonna (2)" left from the first try


def test_the_moves_list_leaves_saved_moves_and_drops_unused_names(app_dir):
    cfg = _old_board(app_dir)
    assert library.tidy_files(cfg) == 3
    claimed = library.new_file("Never used", ".wav", "My sounds")   # empty, never filled
    (app_dir / "tidy-moves.txt").write_text(
        f"{cfg.sounds[0].file}.old\t{cfg.sounds[0].file}\n"   # saved already: stays
        f"{library.SOUNDS_DIR / 'x.wav'}\t{claimed}\n"
        "cut short by the power cut", encoding="utf-8")
    assert library.tidy_files(cfg) == 0
    assert Path(cfg.sounds[0].file).is_file() and not claimed.exists()
    assert not (app_dir / "tidy-moves.txt").exists()


def test_an_add_cut_off_by_a_crash_is_taken_out_at_the_next_start(app_dir, tmp_path,
                                                                    monkeypatch):
    """The app closed (End task, a crash, the power) while a download was converted,
    or before the settings with its pad were saved: its file stayed in the sounds
    folder with no pad for good, and adding it again made "Song (2)"."""
    monkeypatch.setattr(library, "USE_RECYCLE_BIN", False)
    kept, _ = library.import_file(str(_wav(tmp_path / "a.wav")), "#1", name="Kept",
                                  folder="YouTube")
    whole, _ = library.import_file(str(_wav(tmp_path / "b.wav")), "#1", name="Song",
                                   folder="SoundCloud")   # no pad: its save never came
    half = library.new_file("Long mix", ".mp3", "SoundCloud")   # cut off while written
    half.write_bytes(b"ID3" + b"\0" * 100)
    claimed = library.new_file("Clip", ".mp3", "Recordings")    # cut off before a byte
    # the next launch: what the earlier run noted
    from soundboard.sounds import files
    monkeypatch.setattr(files, "_STARTED", files.time.time() + 5)
    assert library.drop_unfinished([kept.file]) == 3
    assert Path(kept.file).is_file()
    assert not Path(whole.file).exists() and not half.exists() and not claimed.exists()
    assert not (library.SOUNDS_DIR / "Recordings").exists()   # emptied: gone too
    assert not list((app_dir / "adding").iterdir())            # the notes are done with
    again, _ = library.import_file(str(_wav(tmp_path / "b.wav")), "#1", name="Song",
                                   folder="SoundCloud")
    assert again.file == whole.file   # its own name again, not "Song (2)"


def test_an_add_still_going_is_left_alone(app_dir, tmp_path, monkeypatch):
    """Only an earlier run's adds are tidied: this run's may still be on their way to a
    pad, and a file a sound uses (or moved by the start-up tidy) is never touched."""
    monkeypatch.setattr(library, "USE_RECYCLE_BIN", False)
    going, _ = library.import_file(str(_wav(tmp_path / "a.wav")), "#1", name="Going",
                                   folder="YouTube")
    moved = library.new_file("Old", ".wav", "My sounds", note=False)
    assert library.drop_unfinished([]) == 0
    assert Path(going.file).is_file() and moved.is_file()
    from soundboard.sounds import files
    monkeypatch.setattr(files, "_STARTED", files.time.time() + 5)
    assert library.drop_unfinished([going.file]) == 0   # it got its pad
    assert Path(going.file).is_file() and moved.is_file()
