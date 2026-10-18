"""Saved clip retention and large libraries, using a temporary audio store."""
import json

import numpy as np
import pytest

from soundboard.sounds import clipshelf
from soundboard.sounds.clipshelf import DAY, Shelf
from soundboard.audio.engine import SR


def audio():
    return np.zeros((480, 2), np.float32)


def test_legacy_clips_get_a_full_grace_period_and_keep_creation_date(app_dir, monkeypatch):
    monkeypatch.setattr(clipshelf.time, "time", lambda: 100 * DAY)
    sh = Shelf()
    c = sh.add(audio(), "Old clip")
    rows = json.loads(sh._index().read_text("utf-8"))
    rows[0].pop("last_used")
    rows[0]["made"] = DAY
    sh._index().write_text(json.dumps(rows), "utf-8")
    loaded = Shelf()
    assert loaded.clips[0].made == DAY
    assert loaded.clips[0].last_used == 100 * DAY
    assert loaded.maintain(now=106 * DAY) == []
    assert Shelf().clips[0].last_used == 100 * DAY
    assert loaded.maintain(now=107 * DAY)[0][1].id == c.id


def test_retention_is_per_clip_with_keep_forever_and_playback_protection(app_dir, monkeypatch):
    clock = [DAY]
    monkeypatch.setattr(clipshelf.time, "time", lambda: clock[0])
    sh = Shelf()
    a = sh.add(audio(), "Active")
    b = sh.add(audio(), "Unused")
    c = sh.add(audio(), "Playing")
    clock[0] = 6 * DAY
    sh.touch(a.id)
    assert sh.maintain(keep_forever=True, now=8 * DAY) == []
    gone = sh.maintain(active=c.id, now=8 * DAY)
    assert [clip.id for _at, clip in gone] == [b.id]
    assert b.path.exists()  # Undo can still restore it.
    clock[0] = 8 * DAY
    sh.restore_many(gone)
    assert b.last_used == 8 * DAY
    assert sh.maintain(now=8 * DAY)[0][1].id == c.id
    assert sh.get(a.id) is not None and sh.get(b.id) is not None


def test_rename_activity_is_persisted_and_creation_date_does_not_change(app_dir, monkeypatch):
    monkeypatch.setattr(clipshelf.time, "time", lambda: DAY)
    sh = Shelf()
    c = sh.add(audio(), "First name")
    monkeypatch.setattr(clipshelf.time, "time", lambda: 6 * DAY)
    assert sh.rename(c.id, "New name")
    loaded = Shelf()
    assert loaded.clips[0].made == DAY and loaded.clips[0].last_used == 6 * DAY
    assert loaded.maintain(now=8 * DAY) == []


def test_cleanup_write_failure_preserves_clips(app_dir, monkeypatch):
    sh = Shelf()
    c = sh.add(audio(), "Keep on failure")
    c.last_used = DAY
    def fail():
        raise OSError("disk full")
    monkeypatch.setattr(sh, "save", fail)
    with pytest.raises(OSError):
        sh.maintain(now=8 * DAY)
    assert sh.get(c.id) is c


def test_expired_files_are_removed_after_undo_and_restored_files_are_kept(app_dir):
    sh = Shelf()
    a = sh.add(audio(), "Expired")
    b = sh.add(audio(), "Restored")
    a.last_used = b.last_used = DAY
    gone = sh.maintain(now=8 * DAY)
    assert a.path.exists() and b.path.exists()
    sh.restore_many([entry for entry in gone if entry[1].id == b.id])
    sh.discard_files(gone)
    assert not a.path.exists() and b.path.exists()


def test_two_thousand_clips_are_kept_and_bulk_delete_undo_writes_once(app_dir, monkeypatch):
    sh = Shelf()
    seed = sh.add(audio(), "Example")
    sh.clips = [clipshelf.Clip(str(i), f"Clip {i}", seed.file,
                              seconds=480 / SR, made=DAY, last_used=DAY)
                for i in range(2000)]
    sh.save()
    sh = Shelf()
    assert len(sh.clips) == 2000
    sh.add(audio(), "Another")
    assert len(sh.clips) == 2001 and seed.path.exists()
    writes = []
    save = sh.save
    def counted():
        writes.append(1)
        save()
    monkeypatch.setattr(sh, "save", counted)
    gone = sh.remove_many({c.id for c in sh.clips})
    assert len(gone) == 2001 and not sh.clips and len(writes) == 1
    sh.restore_many(gone)
    assert len(sh.clips) == 2001 and len(writes) == 2


def test_clips_whose_file_was_deleted_by_hand_drop_out_without_an_undo(app_dir):
    sh = Shelf()
    a = sh.add(audio(), "Kept")
    b = sh.add(audio(), "Deleted")
    b.path.unlink()
    assert sh.maintain() == []   # not "removed inactive clips": nothing to undo
    assert [c.id for c in sh.clips] == [a.id] and sh.pruned
    assert [r["id"] for r in json.loads(sh._index().read_text("utf-8"))] == [a.id]
