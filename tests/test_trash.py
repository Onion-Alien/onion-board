"""Recently deleted: removed sounds, forgotten programs, removed destination modes
and a hand-made voice mix can all be brought back."""
import time
from pathlib import Path

import pytest
from conftest import own_time, process_events
from test_appspanel import music
from test_appspanel import tab as apps_tab  # noqa: F401 - the Apps tab with fake captures
from test_mainwindow import window  # noqa: F401 - the real MainWindow, offscreen

from soundboard.sounds import library
from soundboard import trash
from soundboard.sounds.library import SoundMeta
from soundboard.ui.deleted import DeletedDialog


def _sound(tmp: Path, sid: str) -> SoundMeta:
    library.SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    library.THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    f = library.SOUNDS_DIR / f"{sid}.wav"
    f.write_bytes(b"RIFF")
    img = library.THUMBS_DIR / f"{sid}.png"
    img.write_bytes(b"png")
    return SoundMeta(id=sid, name=f"Sound {sid}", file=str(f), image=str(img),
                     hotkey="f5", tags=["Memes"], volume=1.5)


def test_a_binned_sound_keeps_its_files_and_pad_and_comes_back(app_dir):
    m = _sound(app_dir, "a1")
    trash.put_sound(m, 3)
    assert not Path(m.file).exists() and not Path(m.image).exists()
    [it] = trash.items(trash.SOUND)
    assert it.name == "Sound a1" and it.index == 3
    assert (trash.folder() / "a1.wav").exists()
    back = trash.take(it.id)
    m2 = trash.meta_of(back)
    assert Path(m2.file) == library.SOUNDS_DIR / "a1.wav" and Path(m2.file).exists()
    assert Path(m2.image).exists() and m2.hotkey == "f5" and m2.tags == ["Memes"]
    assert m2.volume == 1.5 and trash.items() == []


def test_old_entries_go_for_good(app_dir):
    m = _sound(app_dir, "old")
    trash.put_sound(m, 0)
    items = trash.load()
    items[0].when = time.time() - (trash.KEEP_DAYS + 1) * 86400
    trash._save(items)
    trash.prune()
    assert trash.items() == [] and not (trash.folder() / "old.wav").exists()


def test_forgetting_a_program_leaves_old_sounds_for_later(app_dir, monkeypatch):
    # it's asked on the UI thread: sending old audio to the Recycle Bin there froze
    # the window. The next start lets go of them
    trash.put_sound(_sound(app_dir, "old"), 0)
    items = trash.load()
    items[0].when = time.time() - (trash.KEEP_DAYS + 1) * 86400
    trash._save(items)
    gone = []
    with monkeypatch.context() as m:
        m.setattr(trash, "_destroy", gone.append)
        trash.put_app("game.exe", {"vol": 0.5}, "Game")
    assert gone == [] and len(trash.items()) == 2
    trash.prune()
    assert [i.kind for i in trash.items()] == [trash.APP]
    assert not (trash.folder() / "old.wav").exists()


def test_forget_deletes_the_files(app_dir):
    trash.put_sound(_sound(app_dir, "f1"), 0)
    trash.forget(trash.items()[0].id)
    assert trash.items() == [] and not (trash.folder() / "f1.wav").exists()


def test_a_damaged_bin_reads_as_empty(app_dir):
    trash.folder().mkdir(parents=True)
    (trash.folder() / "deleted.json").write_text("{nope", encoding="utf-8")
    assert trash.items() == []


def test_ago():
    assert trash.ago(100, 110) == "just now"
    assert trash.ago(0, 300) == "5 min ago"
    assert trash.ago(0, 3 * 86400) == "3 days ago"


def test_a_removed_sound_is_in_recently_deleted_after_the_undo_bar(window, qapp):  # noqa: F811
    assert process_events(qapp, lambda: all(m.id in window.audio for m in window.cfg.sounds))
    m = window.meta("s1")
    window.rmctl.remove_sound("s1")
    window.rmctl._finish_removals()                   # the Undo bar went
    window.rmctl._wait_bin()
    assert window.meta("s1") is None   # (a file outside the library stays put)
    [it] = trash.items(trash.SOUND)
    dlg = DeletedDialog(trash.SOUND, "sounds", window.rmctl._restore_deleted, window)
    assert dlg.list.count() == 1 and m.name in dlg.list.item(0).text()
    dlg.bring_back()
    assert [s.id for s in window.cfg.sounds] == ["s0", "s1"]    # back in its place
    assert Path(window.meta("s1").file).exists() and trash.items() == []
    assert process_events(qapp, lambda: "s1" in window.audio)   # and playable


def test_a_forgotten_program_can_be_undone_or_brought_back(apps_tab):  # noqa: F811
    tab = apps_tab
    tab._on_apps([music(pid=100)])
    row = tab.rows["music.exe"]
    row.btn_send.setChecked(True)
    row.vol.spin.setValue(250)
    row.btn_send.setChecked(False)
    tab.cfg.apps["music.exe"] = {"vol": 2.5, "monitor": True}   # remembered, not sending
    tab._on_apps([])                                           # it closed
    tab._on_forget(tab.rows["music.exe"])
    assert "music.exe" not in tab.cfg.apps and "music.exe" not in tab.rows
    assert tab.undo_bar.active() and not tab.btn_bin.isHidden()
    tab.undo_bar.undo()
    assert tab.cfg.apps["music.exe"] == {"vol": 2.5, "monitor": True}
    row = tab.rows["music.exe"]
    assert row.vol.value() == pytest.approx(2.5) and row.chk_hear.isChecked()
    # later, from the Forgotten programs window
    tab._on_forget(row)
    tab.undo_bar.finish()
    dlg = DeletedDialog(trash.APP, "programs", tab._unforget, tab)
    dlg.bring_back()
    assert "music.exe" in tab.cfg.apps and "music.exe" in tab.rows



def test_x_on_a_running_program_takes_it_off_the_list_until_brought_back(apps_tab):  # noqa: F811
    tab = apps_tab
    tab._on_apps([music(pid=100)])
    tab.rows["music.exe"].btn_forget.click()
    assert "music.exe" not in tab.rows and tab.cfg.apps_hidden == ["music.exe"]
    assert tab.undo_bar.text == "Removed “Music”"
    tab._on_apps([music(pid=100)])                 # still running: stays off the list
    assert "music.exe" not in tab.rows
    tab.undo_bar.undo()
    assert tab.cfg.apps_hidden == [] and "music.exe" not in tab.cfg.apps
    tab._on_apps([music(pid=100)])                 # the next listing brings it back
    assert "music.exe" in tab.rows
    # ...and from the Forgotten programs window
    tab.rows["music.exe"].btn_forget.click()
    tab.undo_bar.finish()
    tab._on_apps([music(pid=100)])
    assert "music.exe" not in tab.rows
    DeletedDialog(trash.APP, "programs", tab._unforget, tab).bring_back()
    tab._on_apps([music(pid=100)])
    assert "music.exe" in tab.rows and tab.cfg.apps_hidden == []

def test_a_removed_destination_mode_can_be_undone(window):  # noqa: F811
    from soundboard.ui.destpanel import CustomDestDialog, DestPanel
    panel = DestPanel(window)
    dlg = CustomDestDialog(window, panel)
    dlg.add()
    raw = dict(window.cfg.dest["custom"][0])
    window.cfg.dest["mode"] = raw["key"]
    dlg.list.setCurrentRow(0)
    dlg.remove()
    assert window.cfg.dest["custom"] == [] and window.cfg.dest["mode"] == "off"
    dlg.undo_bar.undo()
    assert window.cfg.dest["custom"] == [raw] and window.cfg.dest["mode"] == raw["key"]
    dlg.accept()


def test_removing_from_the_menu_asks_first_and_deleted_sounds_stay_in_library(window, monkeypatch):  # noqa: F811
    from PySide6.QtWidgets import QMessageBox
    assert window.btn_bin.isHidden()
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.Cancel)
    assert not window.rmctl.ask_remove(["s0"]) and window.meta("s0") is not None
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.Yes)
    assert window.rmctl.ask_remove(["s0"]) and window.meta("s0") is None
    window.rmctl._finish_removals()
    window.rmctl._wait_bin()
    assert window.btn_bin.isHidden()
    assert len(trash.items()) == 1
    deleted = next(a for a in window.btn_more.menu().actions()
                   if a.text() == "Recently deleted sounds")
    assert deleted.isEnabled() and deleted.isVisible()


def test_a_locked_bin_list_is_never_saved_over(app_dir, monkeypatch):
    """Antivirus or OneDrive holding deleted.json while a sound is binned: the rest
    of the bin must survive (it used to read as empty and be saved over)."""
    for sid in ("k1", "k2"):
        trash.put_sound(_sound(app_dir, sid), 0)
    assert len(trash.items()) == 2
    real = Path.read_text
    locked = {"n": 0}

    def read_text(self, *a, **k):
        if self.name == "deleted.json":
            locked["n"] += 1
            raise PermissionError(32, "being used by another process")
        return real(self, *a, **k)

    own_time(monkeypatch, trash, sleep=lambda _s: None)
    monkeypatch.setattr(Path, "read_text", read_text)
    trash.put_sound(_sound(app_dir, "k3"), 0)
    assert locked["n"] > 1                     # tried again before giving up
    monkeypatch.setattr(Path, "read_text", real)
    assert sorted(i.data["id"] for i in trash.items()) == ["k1", "k2"]


def _failing_picture_move(monkeypatch):
    real = trash._move

    def move(src, dest_dir):
        if src.suffix == ".png":
            raise PermissionError("picture locked")
        return real(src, dest_dir)
    monkeypatch.setattr(trash, "_move", move)


def test_a_failed_restore_leaves_the_entry_whole(app_dir, monkeypatch):
    """The audio comes back, then the picture can't: the audio goes back in the bin,
    so the entry still works next time."""
    trash.put_sound(_sound(app_dir, "b1"), 0)
    [it] = trash.items(trash.SOUND)
    with monkeypatch.context() as m:
        _failing_picture_move(m)
        assert trash.take(it.id) is None
    assert (trash.folder() / "b1.wav").exists()
    back = trash.meta_of(trash.take(it.id))
    assert Path(back.file).exists() and Path(back.image).exists()


def test_a_picture_that_cant_go_in_the_bin_doesnt_lose_the_sound(app_dir, monkeypatch):
    m = _sound(app_dir, "c1")
    _failing_picture_move(monkeypatch)
    trash.put_sound(m, 0)
    [it] = trash.items(trash.SOUND)   # listed, so it can come back
    back = trash.meta_of(trash.take(it.id))
    assert Path(back.file).exists() and Path(back.image) == Path(m.image)


def _restart(qapp):
    """Start the app again on the same settings (the window fixture's fakes still on)."""
    from PySide6.QtCore import QEvent

    from soundboard.ui import mainwindow as main
    w = main.MainWindow()
    w.soundctl._load_thread.join(15)
    ids = [m.id for m in w.cfg.sounds]
    w.close()
    w.soundctl._load_thread.join(15)
    w.deleteLater()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)
    return ids


def test_a_crash_while_the_undo_bar_is_up_still_bins_the_removed_sound(window, qapp):  # noqa: F811
    m = window.meta("s1")
    m.hotkey, m.volume, m.tags = "f7", 1.5, ["Memes"]
    window.rmctl.remove_sound("s1")
    assert window._saver.flush()   # saved without it...
    window.rmctl._removed.clear()   # ...then the app dies before the Undo bar goes
    assert trash.items(trash.SOUND) == []
    assert _restart(qapp) == ["s0"]
    [it] = trash.items(trash.SOUND)   # in Recently deleted, with its pad
    back = trash.meta_of(it)
    assert (back.id, back.name, back.hotkey, back.volume, back.tags, it.index) == \
        ("s1", "Airhorn", "f7", 1.5, ["Memes"], 1)
    assert not (trash.folder() / "removing.json").exists()
    _restart(qapp)                    # only once
    assert len(trash.items(trash.SOUND)) == 1


def test_undo_and_the_undo_bar_closing_leave_nothing_to_finish(window, qapp):  # noqa: F811
    window.rmctl.remove_sound("s1")
    window.rmctl.undo_remove()
    assert not (trash.folder() / "removing.json").exists()
    window.rmctl.remove_sound("s0")
    window.rmctl._finish_removals()
    window.rmctl._wait_bin()
    assert not (trash.folder() / "removing.json").exists() and window._saver.flush()
    assert _restart(qapp) == ["s1"] and len(trash.items(trash.SOUND)) == 1


def test_finish_held_skips_sounds_still_on_the_board_or_already_binned(app_dir):
    a, b, c = (_sound(app_dir, s) for s in ("h1", "h2", "h3"))
    trash.hold([(a, 0), (b, 1), (c, 2)])
    trash.put_sound(b, 1)   # it stopped while the bar's sounds were going in
    assert trash.finish_held({"h1"}) == 1   # h1: the settings weren't saved yet
    assert sorted(i.data["id"] for i in trash.items()) == ["h2", "h3"]
    assert Path(a.file).exists() and (trash.folder() / "h3.wav").exists()
    assert trash.finish_held(set()) == 0   # done: the note is gone


def test_a_second_removal_doesnt_drop_the_first_still_going_into_the_bin(app_dir):
    a, b = _sound(app_dir, "r1"), _sound(app_dir, "r2")
    trash.hold([(a, 0)])
    trash.hold([(b, 1)])        # removed while r1 was still on its way to the bin
    trash.put_sounds([(a, 0)])
    trash.release(["r1"])       # r1's worker is done: r2 is still noted
    assert trash.finish_held(set()) == 1
    assert sorted(i.data["id"] for i in trash.items()) == ["r1", "r2"]


def test_removing_50_sounds_writes_the_bin_list_once(app_dir, monkeypatch):
    """A whole pack going into the bin: one read and one save of deleted.json, not
    one of each per sound (that froze the window for a 100-sound pack)."""
    sounds = [(_sound(app_dir, f"p{n}"), n) for n in range(50)]
    saves, reads = [], []
    real_save, real_read = trash._save, trash._read
    monkeypatch.setattr(trash, "_save", lambda items: saves.append(1) or real_save(items))
    monkeypatch.setattr(trash, "_read", lambda *a, **k: reads.append(1) or real_read(*a, **k))
    assert trash.put_sounds(sounds) == 50
    assert len(saves) == 1 and len(reads) == 1
    assert len(trash.items(trash.SOUND)) == 50
    assert not any(Path(m.file).exists() for m, _i in sounds)


def test_finishing_a_removal_leaves_the_disk_work_to_a_worker(window, qapp, monkeypatch):  # noqa: F811
    import threading
    ui = threading.current_thread()
    seen = []
    real = trash.put_sounds

    def put_sounds(removed):
        seen.append(threading.current_thread())
        return real(removed)

    def on_ui(*_a, **_k):
        raise AssertionError("bin disk work on the UI thread")
    monkeypatch.setattr(trash, "put_sounds", put_sounds)
    monkeypatch.setattr(trash, "put_sound", on_ui)
    monkeypatch.setattr(trash, "items", on_ui)   # the bin's count comes from the worker
    window.rmctl.remove_sounds(["s0", "s1"])
    window.rmctl._finish_removals()
    window.rmctl._wait_bin()
    assert seen and all(t is not ui for t in seen)
    assert process_events(qapp, lambda: window.btn_bin.text() == "Recently deleted (2)")
