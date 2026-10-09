"""Sound library and backup edge cases: settings a control can't show are brought into
range, every file the library keeps comes back from a backup, empty files are refused,
copies keep their categories and fades, and categories match ignoring case."""
import json
import logging
import zipfile

import numpy as np
import pytest
import soundfile as sf

from soundboard import backup, library
from soundboard.library import SR, Config, SoundMeta


def _tone(path, seconds=0.2, fmt=None):
    t = np.arange(int(SR * seconds)) / SR
    sf.write(str(path), np.stack([np.sin(2 * np.pi * 440 * t)] * 2, 1) * 0.3, SR, format=fmt)
    return path


# ------------------------------------------------------------------ settings in range

HUGE = {"sound_vol": 1e9, "mic_vol": -5.0, "mon_vol": 1e300, "pad_width": 5000,
        "eq_gains": [1e300, -1e300, 3, 0, 0, 0, -30]}
HUGE_CLEAN = {"sound_vol": library.VOLUME_MAX, "mic_vol": 0.0, "mon_vol": library.VOLUME_MAX,
              "pad_width": 240, "eq_gains": [12.0, -12.0, 3.0, 0.0, 0.0, 0.0, -12.0]}


def test_out_of_range_settings_are_brought_into_range_on_load(app_dir):
    cfg = Config.from_raw({"version": library.CONFIG_VERSION, **HUGE})
    assert {k: getattr(cfg, k) for k in HUGE} == HUGE_CLEAN
    assert Config.from_raw({"pad_width": 0}).pad_width == 110


@pytest.mark.parametrize("gains", [[], [1.0] * 40, [3.0, 2.0], [1, 2, 3, 4, 5, 6, "x"],
                                   [True] * 7])
def test_eq_gains_of_the_wrong_length_or_kind_fall_back_to_flat(app_dir, gains):
    assert Config.from_raw({"eq_gains": gains}).eq_gains == [0.0] * 7
    cfg = Config()
    backup.apply_settings(cfg, {"eq_gains": gains})
    assert cfg.eq_gains == [0.0] * 7


def test_a_default_device_loads_without_a_warning(app_dir, caplog):
    with caplog.at_level(logging.WARNING):
        cfg = Config.from_raw({"main_device": None, "mon_device": None, "mic_device": "Mic"})
    assert cfg.main_device is None and cfg.mic_device == "Mic"
    assert "ignored" not in caplog.text


def test_imported_settings_are_brought_into_range(app_dir):
    cfg = Config()
    changed = backup.apply_settings(cfg, HUGE)
    assert set(changed) == set(HUGE)
    assert {k: getattr(cfg, k) for k in HUGE} == HUGE_CLEAN


@pytest.mark.parametrize("dest,want", [
    ({"x": 1}, {"x": 1}),
    ({"mode": 3, "custom": "y"}, {}),
    ({"mode": "discord", "custom": [{"key": "a"}, 5, "b"]},
     {"mode": "discord", "custom": [{"key": "a"}]}),
])
def test_a_damaged_destination_setting_is_cleaned(app_dir, dest, want):
    cfg = Config()
    backup.apply_settings(cfg, {"dest": dest})
    assert cfg.dest == want
    assert Config.from_raw({"dest": dest}).dest == want


def test_sound_volume_in_a_hand_edited_config_is_brought_into_range(app_dir):
    cfg = Config.from_raw({"sounds": [
        {"id": "a", "name": "A", "file": "a.wav", "volume": 1e9, "level_gain": -4.0}]})
    assert cfg.sounds[0].volume == 2.0 and cfg.sounds[0].level_gain == 0.1


# ------------------------------------------------------------------ odd file types

@pytest.mark.parametrize("ext,fmt", [(".au", "AU"), (".caf", "CAF"), (".w64", "W64"),
                                     (".aifc", "AIFF")])
def test_a_file_outside_the_audio_types_is_kept_as_mp3_and_round_trips(
        app_dir, tmp_path, ext, fmt):
    src = _tone(tmp_path / f"Beep{ext}", fmt=fmt)
    meta, _ = library.import_file(str(src), "#7c5cff")
    assert meta.file.endswith("Beep.mp3") and meta.name == "Beep"
    out = tmp_path / "backup.zip"
    assert backup.export(out, [meta]) == 1
    pkg = backup.read(out)
    assert len(pkg.sounds) == 1


def test_export_converts_an_older_library_file_of_an_odd_type(app_dir, tmp_path):
    """Sounds imported before the fix are still stored as they came (.caf here):
    exported as a FLAC, so the backup imports them back."""
    library.SOUNDS_DIR.mkdir(parents=True)
    audio = _tone(library.SOUNDS_DIR / "0123456789_Beep.caf", fmt="CAF")
    meta = SoundMeta(id="a", name="Beep", file=str(audio), fingerprint="fp-a",
                     tags=["Memes"])
    out = tmp_path / "backup.zip"
    assert backup.export(out, [meta], categories=["Memes"]) == 1
    with zipfile.ZipFile(out) as z:
        entry = json.loads(z.read("sounds/001 Beep/sound.json"))
        assert entry["audio"] == "Beep.flac" and entry["fingerprint"] == "fp-a"
    pkg = backup.read(out)
    res = backup.install(pkg, set())
    assert not res.failed and len(res.sounds) == 1
    got = res.sounds[0]
    assert got.file.endswith(".flac") and got.tags == ["Memes"]
    assert len(library.decode(got.file)) == len(library.decode(str(audio)))


def test_an_empty_audio_file_is_refused(app_dir, tmp_path):
    zero = tmp_path / "zero.wav"
    sf.write(str(zero), np.zeros((0, 2)), SR)
    with pytest.raises(ValueError, match="no audio"):
        library.import_file(str(zero), "#7c5cff")
    assert not list(library.SOUNDS_DIR.glob("*"))


# ------------------------------------------------------------------ copies, categories

def test_duplicate_keeps_categories_and_fades(app_dir):
    meta, _ = library.import_file(str(_tone(app_dir / "a.wav")), "#7c5cff")
    meta.tags, meta.fade_in, meta.fade_out, meta.hotkey = ["Memes"], 1.0, 2.0, "f5"
    d = library.duplicate(meta, "copy")
    assert (d.tags, d.fade_in, d.fade_out, d.hotkey) == (["Memes"], 1.0, 2.0, "")
    d.tags.append("Other")
    assert meta.tags == ["Memes"]   # a list of its own


def test_merge_tags_uses_the_existing_spelling():
    cats = ["Memes", "Music"]
    assert library.merge_tags(["memes", "NEW", "MUSIC", "new"], cats) == ["Memes", "NEW",
                                                                           "Music"]
    assert cats == ["Memes", "Music", "NEW"]


def test_a_tag_differing_only_in_case_joins_the_category_on_load(app_dir):
    cfg = Config.from_raw({"categories": ["Memes"], "sounds": [
        {"id": "a", "name": "A", "file": "a.wav", "tags": ["memes", "Loud"]}]})
    assert cfg.categories == ["Memes", "Loud"]
    assert cfg.sounds[0].tags == ["Memes", "Loud"]


def test_a_folder_listed_twice_in_the_manifest_is_one_sound(app_dir, tmp_path):
    wav = _tone(tmp_path / "w.wav").read_bytes()
    man = {"format": backup.FORMAT, "format_version": 1, "sounds": ["s", "s", "s"]}
    z = tmp_path / "d.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr(backup.MANIFEST, json.dumps(man))
        zf.writestr("s/sound.json", json.dumps({"name": "x", "audio": "a.wav"}))
        zf.writestr("s/a.wav", wav)
    assert len(backup.read(z).sounds) == 1


def test_a_config_with_a_version_below_one_still_loads():
    from soundboard.library import Config
    c = Config.from_raw({"version": -3, "sound_vol": 0.5})
    assert c.sound_vol == 0.5
