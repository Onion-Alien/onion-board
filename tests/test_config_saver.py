"""Settings are written on a background thread (library.Saver): a slow disk doesn't
freeze the window, the newest settings always win, and a direct save() (on quit)
is never overwritten by an older background one."""
import json
import threading
import time

from soundboard import library
from soundboard.library import Config


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


def test_an_older_snapshot_never_overwrites_a_newer_save(app_dir):
    cfg = Config()
    cfg.theme = "Light"
    old = cfg.snapshot()
    cfg.theme = "Paper"
    assert cfg.save()          # e.g. the save on quit
    assert library._write(old)   # the background one, finishing late: skipped
    assert _on_disk()["theme"] == "Paper"


def test_a_failed_write_is_reported(app_dir, monkeypatch):
    def broken(*_a, **_k):
        raise OSError("disk full")
    monkeypatch.setattr(library.Path, "write_text", broken)
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
