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


def test_one_saver_thread_writes_every_save_however_long_it_sat_idle(app_dir):
    """Starting a thread waits for it to run, and save() runs on the UI thread: a new
    thread after every 30 s idle held the window on a PC short of memory. One thread
    stays (idle waits never time out), and every save still gets written."""
    cfg = Config()
    s = library.Saver(cfg)
    waits = []

    class Watched(threading.Condition):
        def wait(self, timeout=None):
            if threading.current_thread().name == "config-save":   # not flush()'s
                waits.append(timeout)
            return super().wait(timeout)
    s._cond = Watched()
    threads = []
    for theme in ("Light", "Paper", "Synthwave"):
        cfg.theme = theme
        s.save()
        assert s.flush(5)
        threads.append(s._thread)
    assert _on_disk()["theme"] == "Synthwave"
    assert len(set(threads)) == 1 and threads[0].is_alive()
    assert all(t is None for t in waits)   # never a timed idle wait that ends it


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
