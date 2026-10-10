"""Adversarial checks for the release audit, using isolated files and silent Qt."""
from pathlib import Path

import pytest

from soundboard import backup, library, reset
from soundboard.library import Config, SoundMeta
from test_mainwindow import window as main_window  # noqa: F401


@pytest.fixture
def window(main_window):  # noqa: F811 - expose the imported fixture under a local name
    return main_window


def test_restore_keeps_original_audio_when_a_new_sound_reuses_its_name(app_dir):
    original = library.new_file("Same name", ".wav", library.RECORDINGS)
    original.write_bytes(b"original recording")
    assert Config(sounds=[SoundMeta(id="old", name="Same name", file=str(original))]).save()
    reset.reset([reset.SOUNDS])
    point, = reset.points()
    replacement = library.new_file("Same name", ".wav", library.RECORDINGS)
    replacement.write_bytes(b"new recording")
    cfg = Config.load()
    cfg.sounds.append(SoundMeta(id="new", name="Same name", file=str(replacement)))
    assert cfg.save()
    reset.restore(point.id)
    restored = {m.id: m for m in Config.load().sounds}
    assert Path(restored["old"].file).read_bytes() == b"original recording"
    assert Path(restored["new"].file).read_bytes() == b"new recording"
    assert restored["old"].file != restored["new"].file


def test_kept_folder_pack_identity_changes_when_equal_size_audio_changes(app_dir, tmp_path):
    folder = tmp_path / "Pack"
    folder.mkdir()
    audio = folder / "sound.wav"
    audio.write_bytes(b"first sound")
    first = backup.keep_pack(backup.Package(path=folder))
    audio.write_bytes(b"other sound")
    second = backup.keep_pack(backup.Package(path=folder))
    assert first != second


def test_a_removed_download_can_be_added_again(qapp, monkeypatch):
    import numpy as np
    from test_linkbar import URL, _bar
    bar, _eng = _bar()
    meta = SoundMeta(id="download", name="Clip", file="clip.wav")
    bar.sound_ready.connect(lambda m, data: bar.cfg.sounds.append(m))
    bar._busy = "add"
    bar._on_msg("added", URL, (meta, np.zeros((48, 2), np.int16), "Clip", ""))
    bar.cfg.sounds.remove(meta)
    starts = []
    monkeypatch.setattr(bar, "_start", starts.append)
    bar.add()
    assert starts == ["add"]


@pytest.mark.parametrize("reset_first", [False, True])
def test_removing_a_pack_does_not_remove_a_preexisting_personal_sound(
        window, app_dir, tmp_path, qapp, reset_first):
    import zipfile
    from conftest import process_events
    from test_sounds_window_fixes import _three_pack
    package = _three_pack(tmp_path)
    own_file = app_dir / "personal.wav"
    with zipfile.ZipFile(package) as archive:
        own_file.write_bytes(archive.read("0 Door/a.wav"))
    original = SoundMeta(id="personal", name="My own sound", file=str(own_file),
                         fingerprint=library.fingerprint(str(own_file)), volume=1.7)
    window.cfg.sounds.append(original)
    window._rebuild_pads()
    window.import_package(str(package))
    assert process_events(qapp, lambda: len(window.cfg.sounds) == 5, 10)
    pid, = backup.packs()
    if reset_first:
        window.reset_pack(pid, ask=False)
        assert process_events(qapp, lambda: len(window.cfg.sounds) == 6, 10)
        assert original.name == "My own sound" and original.volume == 1.7
        assert original.pack == ""
    window.remove_pack(pid, ask=False)
    assert original in window.cfg.sounds


def test_failed_ai_status_does_not_claim_voice_masking_when_backup_is_real_mic(window):
    ai = window.voice.ai
    ai.cb_backup.setCurrentIndex(ai.cb_backup.findData("mic"))
    ai._set_ui(True, "Starting")
    ai._on_event({"type": "error", "text": "Model failed"})
    window.voice._update_bar()
    chip = window.voice.bar.chips["ai"]
    assert "built-in voice covers you" not in chip.toolTip()


def test_setup_failure_disappears_with_isolated_device_inventory(window, monkeypatch):
    from soundboard import engine
    from test_mainwindow import test_setup_not_done_yet_is_one_orange_step_not_red_crosses
    monkeypatch.setattr(engine, "virtual_outputs", lambda: [])
    test_setup_not_done_yet_is_one_orange_step_not_red_crosses(window, monkeypatch)


@pytest.mark.parametrize("save_ok", [True, False])
def test_restore_collision_shared_audio_and_images_roll_back(app_dir, monkeypatch, save_ok):
    audio = library.new_file("Shared", ".wav", library.RECORDINGS)
    audio.write_bytes(b"old audio")
    library.THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    image = library.THUMBS_DIR / "shared.png"
    image.write_bytes(b"old image")
    assert Config(sounds=[SoundMeta(id=key, name=key, file=str(audio), image=str(image))
                          for key in ("old1", "old2")]).save()
    reset.reset([reset.SOUNDS])
    point, = reset.points()
    audio.write_bytes(b"new audio")
    image.write_bytes(b"new image")
    cfg = Config.load()
    cfg.sounds.append(SoundMeta(id="new", name="new", file=str(audio), image=str(image)))
    assert cfg.save()
    if not save_ok:
        monkeypatch.setattr(Config, "save", lambda self: False)
    note = reset.restore(point.id)
    restored = {m.id: m for m in Config.load().sounds}
    assert audio.read_bytes() == b"new audio" and image.read_bytes() == b"new image"
    if save_ok:
        assert restored["old1"].file == restored["old2"].file != str(audio)
        assert restored["old1"].image == restored["old2"].image != str(image)
        assert Path(restored["old1"].file).read_bytes() == b"old audio"
        assert Path(restored["old1"].image).read_bytes() == b"old image"
    else:
        assert "Nothing was changed" in note
        assert list(restored) == ["new"]
        kept_audio = point.path / "sounds" / library.RECORDINGS / audio.name
        assert kept_audio.read_bytes() == b"old audio"
        assert (point.path / "thumbs" / image.name).read_bytes() == b"old image"
        assert sorted(audio.parent.iterdir()) == [audio]
        assert sorted(image.parent.iterdir()) == [image]


def test_folder_and_zip_pack_identity_match_and_metadata_changes_count(app_dir, tmp_path):
    import zipfile
    folder = tmp_path / "Pack"
    folder.mkdir()
    (folder / "sound.wav").write_bytes(b"audio")
    metadata = folder / "sound.json"
    metadata.write_text('{"name":"First"}')
    first = backup.keep_pack(backup.Package(path=folder))
    archive = tmp_path / "pack.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for p in folder.iterdir():
            z.write(p, p.name)
    assert backup.keep_pack(backup.Package(path=archive)) == first
    metadata.write_text('{"name":"Other"}')
    assert backup.keep_pack(backup.Package(path=folder)) != first


def test_restore_does_not_cascade_filename_rewrites(app_dir):
    files = [library.new_file("Clip", ".wav", library.RECORDINGS) for _i in range(2)]
    for i, path in enumerate(files):
        path.write_bytes(f"original {i}".encode())
    assert Config(sounds=[SoundMeta(id=str(i), name="Clip", file=str(path))
                          for i, path in enumerate(files)]).save()
    reset.reset([reset.SOUNDS])
    point, = reset.points()
    files[0].write_bytes(b"new recording")
    reset.restore(point.id)
    for m in Config.load().sounds:
        assert Path(m.file).read_bytes() == f"original {m.id}".encode()
    assert files[0].read_bytes() == b"new recording"


def test_overlapping_pack_reset_and_removal_preserve_first_pack(window, tmp_path, qapp,
                                                               monkeypatch):
    import json
    import zipfile
    from conftest import process_events
    from test_sounds_window_fixes import _three_pack
    first = _three_pack(tmp_path)
    baseline = len(window.cfg.sounds)
    window.import_package(str(first))
    assert process_events(qapp, lambda: len(window.cfg.sounds) == baseline + 3, 10)
    originals = list(window.cfg.sounds[baseline:])
    first_id = originals[0].pack
    second = tmp_path / "Overlapping.zip"
    with zipfile.ZipFile(first) as source, zipfile.ZipFile(second, "w") as dest:
        for name in source.namelist():
            content = source.read(name)
            if name.endswith("sound.json"):
                entry = json.loads(content)
                entry["name"] = "Second " + entry["name"]
                content = json.dumps(entry).encode()
            dest.writestr(name, content)
    window.import_package(str(second))
    assert process_events(qapp, lambda: "already" in window.status.text(), 10)
    second_id, = set(backup.packs()) - {first_id}
    assert all(m.pack == first_id for m in originals)
    monkeypatch.setattr(window, "_take_pack_hotkeys", lambda *args: False)
    window.reset_pack(second_id, ask=False)
    assert process_events(qapp, lambda: len(window.cfg.sounds) == baseline + 6, 10)
    window.remove_pack(second_id, ask=False)
    assert window.cfg.sounds[baseline:] == originals
    assert all(m.pack == first_id and not m.name.startswith("Second") for m in originals)


@pytest.mark.parametrize("mode, heard", [("voice", "built-in voice"),
                                       ("mic", "my real voice"), ("mute", "silence")])
def test_ai_fallback_is_consistent_during_start_failure_and_retry(window, monkeypatch, mode, heard):
    ai = window.voice.ai
    ai.cb_backup.setCurrentIndex(ai.cb_backup.findData(mode))
    ai._set_ui(True, ai._starting_text())
    assert heard in ai.lbl_state.text()
    ai._on_event({"type": "error", "text": "Model failed"})
    window.voice._update_bar()
    assert heard in ai.lbl_state.text()
    assert heard in window.voice.bar.chips["ai"].toolTip()
    ai._connected, ai._retried, ai.module = False, False, object()
    monkeypatch.setattr(type(ai.ctl), "running", property(lambda self: True))
    monkeypatch.setattr(ai, "_start_helper", lambda: True)
    ai._on_event({"type": "stopped"})
    assert ai.status() == "starting" and heard in ai.lbl_state.text()
