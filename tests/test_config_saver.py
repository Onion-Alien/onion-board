"""Settings are written on a background thread (library.Saver): a slow disk doesn't
freeze the window, the newest settings always win, and a direct save() (on quit)
is never overwritten by an older background one."""
import dataclasses
import json
import sys
import threading
import time

from soundboard.sounds import library
from soundboard.sounds.library import Config


def _on_disk() -> dict:
    return json.loads(library.CONFIG_PATH.read_text(encoding="utf-8"))


def test_the_saver_writes_the_newest_settings(app_dir):
    cfg = Config()
    results = []
    s = library.Saver(cfg, done=results.append)
    for theme in ("Light", "Paper", "Synthwave"):
        cfg.theme = theme
        s.save()
    assert s.flush(10)
    assert _on_disk()["theme"] == "Synthwave"
    assert results and all(results)


def test_a_slow_disk_doesnt_hold_up_the_caller(app_dir, monkeypatch):
    gate = threading.Event()
    real = library._write_privacy

    def slow(text):   # an antivirus scan of the new file
        gate.wait(5)
        real(text)
    monkeypatch.setattr(library, "_write_privacy", slow)
    cfg = Config()
    s = library.Saver(cfg)
    start = time.monotonic()
    s.save()
    cfg.theme = "Light"   # changing the config meanwhile is safe: save() took a copy
    s.save()
    assert time.monotonic() - start < 0.5
    gate.set()
    assert s.flush(10)
    assert _on_disk()["theme"] == "Light"


def test_saving_again_while_the_disk_is_busy_doesnt_freeze(app_dir, monkeypatch):
    """A 1.7.2 freeze: the second save waited for the first to finish on the disk,
    on the UI thread, just to copy the settings."""
    writing, gate = threading.Event(), threading.Event()
    real = library._write_privacy

    def slow(text):
        writing.set()
        gate.wait(5)
        real(text)
    monkeypatch.setattr(library, "_write_privacy", slow)
    cfg = Config()
    s = library.Saver(cfg)
    s.save()
    assert writing.wait(5)   # the writer is on the disk now, holding the write lock
    start = time.monotonic()
    cfg.theme = "Light"
    s.save()
    assert time.monotonic() - start < 0.5
    gate.set()
    assert s.flush(10)
    assert _on_disk()["theme"] == "Light"


def test_an_older_snapshot_never_overwrites_a_newer_save(app_dir):
    cfg = Config()
    cfg.theme = "Light"
    old = cfg.snapshot()
    cfg.theme = "Paper"
    assert cfg.save()          # e.g. the save on quit
    assert library._write(old)   # the background one, finishing late: skipped
    assert _on_disk()["theme"] == "Paper"


def test_save_then_is_handed_back_once_its_copy_is_written(app_dir, monkeypatch):
    """save(then): finished() gives `then` back with that write's result, only once a
    write covers its copy, never one from an older copy that was already on its way."""
    writing, gate = threading.Event(), threading.Event()
    real = library._write
    results = iter([True, False])

    def slow(snap):
        writing.set()
        gate.wait(5)
        real(snap)
        return next(results)
    monkeypatch.setattr(library, "_write", slow)
    s = library.Saver(Config())
    s.save()
    assert writing.wait(5)          # the first copy is on its way to the disk
    told = []
    s.save(lambda ok: told.append(ok))
    assert s.finished() == []
    gate.set()
    assert s.flush(10)
    (then, ok), = s.finished()      # the second write (the one that failed) covers it
    assert ok is False and s.finished() == []
    then(ok)
    assert told == [False]


def test_a_failed_write_is_reported(app_dir, monkeypatch):
    def broken(*_a, **_k):
        raise OSError("disk full")
    monkeypatch.setattr(library.os, "fsync", broken)
    results = []
    s = library.Saver(Config(), done=results.append)
    s.save()
    assert s.flush(10)
    assert results == [False]


def test_a_read_only_config_isnt_written(app_dir):
    cfg = Config()
    cfg.read_only = True
    results = []
    library.Saver(cfg, done=results.append).save()
    assert results == [False] and not library.CONFIG_PATH.exists()


def test_a_save_as_the_idle_wait_ends_is_still_written(app_dir):
    """The saver thread's 30 s idle wait timed out, and a save() took the lock before
    the wait got it back: the thread saw a timeout, left with that save pending, and
    it was never written (flush() then gave up on it at quit)."""
    cfg = Config()
    s = library.Saver(cfg)
    raced = []

    class Racy(threading.Condition):
        def wait(self, timeout=None):
            if timeout == 30 and not raced:   # the idle wait: time it out, with a save
                raced.append(1)               # slipping in just as it does
                cfg.theme = "Paper"
                s._pending = cfg.snapshot()
                return False
            return super().wait(timeout)
    s._cond = Racy()
    cfg.theme = "Light"
    s.save()
    end = time.monotonic() + 10
    while not raced and time.monotonic() < end:   # the first write done, then idle
        time.sleep(0.01)
    assert raced and s.flush(5)
    assert _on_disk()["theme"] == "Paper"


def _big_config(n: int) -> Config:
    return Config(theme="Light", eq_gains=[1.0] * 7, sounds=[library.SoundMeta(
        id=str(i), name=f"Sound {i}", file=str(library.SOUNDS_DIR / f"{i}.mp3"),
        tags=["Memes"], fx={"speed": 1.5, "eq": [0.0] * 7}, source={"url": "u"})
        for i in range(n)])


def test_the_settings_copy_is_a_full_copy(app_dir):
    cfg = _big_config(3)
    raw = cfg.to_raw()
    assert raw["sounds"][1] == {**dataclasses.asdict(cfg.sounds[1]), "file": "1.mp3"}
    assert {k: v for k, v in raw.items() if k != "sounds"} == {
        k: v for k, v in dataclasses.asdict(cfg).items() if k != "sounds"}
    cfg.sounds[0].fx["eq"][0] = 9.0   # changed after the copy: the copy keeps its own
    cfg.sounds[0].tags.append("Music")
    cfg.eq_gains[0] = 0.0
    assert raw["sounds"][0]["fx"]["eq"][0] == 0.0
    assert raw["sounds"][0]["tags"] == ["Memes"]
    assert raw["eq_gains"][0] == 1.0


def test_copying_a_big_library_stays_cheap(app_dir):
    """Every save copies every sound on the window thread. asdict() made ~70 Python
    calls per sound for it (a 2.7.1 freeze report was caught inside it)."""
    cfg = _big_config(500)
    cfg.to_raw()   # the stored file names are remembered after the first save
    calls = 0

    def count(frame, event, arg):
        nonlocal calls
        if event == "call":
            calls += 1
    sys.setprofile(count)
    try:
        cfg.to_raw()
    finally:
        sys.setprofile(None)
    assert calls < 10 * len(cfg.sounds), calls
