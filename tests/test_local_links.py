"""Storage choices must share playback and never damage an external source."""
import zipfile
from pathlib import Path

import numpy as np
import pytest
from conftest import process_events
from test_cache_and_import import wav
from test_engine import engine_with
from test_mainwindow import window  # noqa: F401

from soundboard import backup, eq, library, mapped, soundfx, trash


def test_setting_defaults_and_roundtrips(app_dir):
    assert not library.Config.from_raw({}).copy_local_sounds
    cfg = library.Config(copy_local_sounds=True)
    assert library.Config.from_raw(cfg.to_raw()).copy_local_sounds


@pytest.mark.parametrize("speed", [0.75, 1.0, 1.5])
@pytest.mark.parametrize("use_map", [False, True])
def test_link_and_copy_share_cache_effects_and_live_playback(app_dir, monkeypatch, speed, use_map):
    if use_map:
        monkeypatch.setattr(mapped, "MAP_MIN_BYTES", 1)
    src = wav(app_dir / "local.wav")
    linked, a = library.import_file(str(src), "#123456", copy=False)
    copied, b = library.import_file(str(src), "#123456")
    assert linked.file == str(src) and not library.owns(linked.file)
    assert library.owns(copied.file)
    np.testing.assert_array_equal(a, b)
    assert mapped.is_mapped(a) == use_map
    assert mapped.is_mapped(b) == use_map
    # Simulate restart: the only permitted reads are from the common decoded cache.
    monkeypatch.setattr(library, "decode", lambda *args: pytest.fail("source decoded again"))
    for meta in (linked, copied):
        meta.fx = {"speed": 1.25, "eq": [6.0] + [0.0] * (len(eq.BANDS) - 1)}
    a, b = library.load_sound(linked), library.load_sound(copied)
    np.testing.assert_array_equal(a, b)
    assert library.cache_path(linked.id, soundfx.key(linked.fx)).exists()
    engines = [engine_with("mon"), engine_with("mon")]
    heard = []
    for e, data in zip(engines, (a, b)):
        e.sound_speed = speed
        e.sound_fx = {"bass": 12.0}
        e.play("tone", data, 1.0)
        blocks = []
        for __ in range(30):
            out = np.zeros((480, 2), np.float32)
            e._mon(out, 480)
            blocks.append(out)
        heard.append(np.concatenate(blocks))
    np.testing.assert_array_equal(*heard)
    assert np.abs(heard[0]).max() > 0


def test_link_reload_after_cache_pruned_and_delete_preserves_source(app_dir):
    src = wav(app_dir / "local.wav")
    meta, data = library.import_file(str(src), "#123456", copy=False)
    library.unlink_cache(meta.id)
    np.testing.assert_array_equal(library.load_original(meta), data)
    trash.put_sound(meta, 0)
    assert src.exists()
    item = trash.items(trash.SOUND)[0]
    restored = trash.take(item.id)
    assert restored.data["file"] == str(src)
    library.delete_file(meta)
    assert src.exists()


def test_linked_video_stays_linked_and_backup_contains_audio(app_dir, tmp_path):
    src = wav(tmp_path / "video.wav").rename(tmp_path / "video.mp4")
    meta, data = library.import_file(str(src), "#123456", copy=False)
    assert meta.file == str(src)
    out = tmp_path / "backup.zip"
    assert backup.export(out, [meta]) == 1
    pkg = backup.read(out)
    assert len(pkg.sounds) == 1
    assert pkg.sounds[0].audio.endswith(".flac")
    library.unlink_cache(meta.id)
    np.testing.assert_array_equal(library.load_original(meta), data)


def test_missing_link_fails_after_cache_is_cleared(app_dir):
    src = wav(app_dir / "missing.wav")
    meta, data = library.import_file(str(src), "#123456", copy=False)
    src.unlink()
    np.testing.assert_array_equal(library.load_original(meta), data)
    library.unlink_cache(meta.id)
    with pytest.raises(RuntimeError):
        library.load_original(meta)


@pytest.mark.parametrize("copy", [False, True])
def test_local_import_obeys_setting_and_zip_keeps_file(window, qapp, tmp_path, copy):  # noqa: F811
    window.cfg.copy_local_sounds = copy
    src = wav(tmp_path / "local.wav", hz=880)
    window.import_files([str(src)])
    assert process_events(qapp, lambda: not window._pending_imports)
    added = window.cfg.sounds[-1]
    assert library.owns(added.file) == copy
    assert src.exists()
    archive = tmp_path / "sounds.zip"
    other = wav(tmp_path / "zipped.wav", hz=1200)
    with zipfile.ZipFile(archive, "w") as z:
        z.write(other, "zipped.wav")
    window.import_files([str(archive)])
    assert process_events(qapp, lambda: not window._pending_imports)
    added = window.cfg.sounds[-1]
    assert library.owns(added.file) and Path(added.file).exists()
    library.unlink_cache(added.id)
    assert len(library.load_original(added))


def test_settings_toggle_applies_and_survives_reload(window):  # noqa: F811
    d = window.open_settings("data")
    assert d.back_btn is not None
    assert not d.copy_local_sounds.isChecked()
    d.copy_local_sounds.setChecked(True)
    assert window.cfg.copy_local_sounds
    assert library.Config.from_raw(window.cfg.to_raw()).copy_local_sounds
    d.copy_local_sounds.setChecked(False)
    assert not window.cfg.copy_local_sounds
    window.close_settings()
