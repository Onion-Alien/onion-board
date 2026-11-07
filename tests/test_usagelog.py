"""Warnings and errors reaching the usage count as anonymous events (usagelog.py)."""
from __future__ import annotations

import json
import logging
import threading
import types

import pytest

from soundboard.core import applog, usage, usagelog
from soundboard.core.usageevents import LOG_ERROR, LOG_WARNING, level_of

SECRET_PATH = r"D:\Music\Jane Doe\my secret sound.mp3"
SECRET_NAME = "Jane's Headset"


@pytest.fixture
def counting(monkeypatch):
    """A counter on the root logger as install() leaves it, with nothing else to hear."""
    monkeypatch.setattr(usage, "enabled", lambda: True)
    monkeypatch.setattr(usage, "_pending", [])
    monkeypatch.setattr(usage, "_warned", set())
    monkeypatch.setattr(usage, "_failed", set())
    monkeypatch.setattr(usagelog, "_counter", None)
    monkeypatch.setattr(usagelog, "_run_start", None)
    monkeypatch.setitem(applog._state, "saved", set())
    root = logging.getLogger()
    assert usagelog.install()
    yield usagelog._counter
    root.removeHandler(usagelog._counter)


def cfg(sent: float = 0.0):
    return types.SimpleNamespace(stats_sent=sent)


def record(name="soundboard.audio.engine", level=logging.WARNING, msg="m", args=None,
           path=r"C:\app\soundboard\audio\engine.py", line=12, func="play", exc_info=None):
    r = logging.LogRecord(name, level, path, line, msg, args, exc_info, func)
    return r


def noted(name=None):
    return [e for e in usage._pending if name is None or e["name"] == name]


def caught():
    try:
        raise KeyError("x")
    except KeyError:
        import sys
        return sys.exc_info()


def test_levels():
    assert level_of(LOG_ERROR) == "error"
    assert level_of(LOG_WARNING) == "warn"
    assert level_of("run.start") == "info"


def test_off_from_source_and_with_no_stats(monkeypatch):
    monkeypatch.setattr(usagelog, "_counter", None)
    before = list(logging.getLogger().handlers)
    assert not usagelog.install()   # tests run from source
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setenv("ONIONBOARD_NO_STATS", "1")
    assert not usagelog.install()
    assert logging.getLogger().handlers == before


def test_a_line_says_its_place_and_nothing_of_its_text(counting):
    logging.getLogger("soundboard.audio.engine").handle(
        record(msg="couldn't open %s on %s", args=(SECRET_PATH, SECRET_NAME)))
    usagelog.flush(cfg(), closing=True)
    [e] = noted(LOG_WARNING)
    assert e["level"] == "warn"
    assert e["attrs"] == {"logger": "soundboard.audio.engine",
                          "file": "soundboard/audio/engine.py", "line": 12, "func": "play"}


def test_a_message_with_a_path_and_a_name_never_reaches_the_wire(counting, monkeypatch):
    """The real way out: a real log call, with the exception's message too, through at_quit
    to the bytes of the request."""
    sent = []

    class Answer:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *_a):
            return False

    def urlopen(req, **_kw):
        sent.append(req.data.decode("utf-8"))
        return Answer()
    monkeypatch.setattr(usage.net, "urlopen", urlopen)
    monkeypatch.setattr(usage, "ENDPOINT", "https://example.com/v2/events")
    log = logging.getLogger("soundboard.fake.module")
    log.warning("can't read %s", SECRET_PATH)
    log.error(f"{SECRET_NAME} went away")
    try:
        raise OSError(f"{SECRET_PATH} on {SECRET_NAME}")
    except OSError:
        log.exception("failed for %s", SECRET_NAME)
    logging.getLogger("some.library").error("%s", SECRET_PATH)

    from soundboard.sounds.config import Config
    c = Config()
    usagelog.ended(c)
    finish = usage.at_quit(c)
    assert finish is not None and finish()
    wire = "".join(sent)
    assert "log.warning" in wire and "log.error" in wire and "run.end" in wire
    assert '"type": "OSError"' in wire
    for word in ("Jane", "secret", "Headset", "Music", "went away", "can't read", "failed for"):
        assert word not in wire


def test_what_its_sent_fits_the_servers_rules(counting):
    logging.getLogger("soundboard.fake").exception("x", exc_info=caught())
    logging.getLogger("qt").warning("QFont %s", SECRET_NAME)
    usagelog.flush(cfg(), closing=True)
    usagelog.ended(cfg())
    assert usage._pending
    for e in usage._pending:
        assert usage.re.fullmatch(r"[a-z][a-z0-9_.]{0,40}", e["name"])
        for k, v in e.get("attrs", {}).items():
            assert usage.re.fullmatch(r"[a-z][a-z0-9_]{0,30}", k)
            for s in v if isinstance(v, list) else [v]:
                assert isinstance(s, int) or usage.re.fullmatch(r"[\w/._:@<>~+-]{1,300}", s)


def test_outside_our_code_is_the_loggers_name_only(counting):
    counting.handle(record("qt", path=r"C:\app\soundboard\core\applog.py"))
    counting.handle(record("urllib3.connectionpool", exc_info=caught()))
    counting.handle(record(r"D:\Jane\plugin"))
    usagelog.flush(cfg(), closing=True)
    assert sorted(e["attrs"]["logger"] for e in noted(LOG_WARNING)) == [
        "other", "qt", "urllib3.connectionpool"]
    assert all(set(e["attrs"]) == {"logger"} for e in noted(LOG_WARNING))


def test_an_exception_says_its_type_and_our_own_stack(counting):
    def inner():
        raise ValueError(SECRET_PATH)
    try:
        inner()
    except ValueError:
        import sys
        exc = sys.exc_info()
    tb = types.SimpleNamespace(
        tb_frame=types.SimpleNamespace(f_code=types.SimpleNamespace(
            co_filename=r"C:\app\soundboard\audio\engine.py", co_name="play")),
        tb_lineno=90, tb_next=types.SimpleNamespace(
            tb_frame=types.SimpleNamespace(f_code=types.SimpleNamespace(
                co_filename=r"C:\app\soundboard\audio\mixer.py", co_name="mix")),
            tb_lineno=7, tb_next=None))
    counting.handle(record(level=logging.ERROR, exc_info=(exc[0], exc[1], tb)))
    usagelog.flush(cfg(), closing=True)
    [e] = noted(LOG_ERROR)
    assert e["attrs"]["type"] == "ValueError"
    assert (e["attrs"]["file"], e["attrs"]["line"]) == ("soundboard/audio/mixer.py", 7)
    assert e["attrs"]["stack"] == ["soundboard/audio/engine.py:90:play",
                                   "soundboard/audio/mixer.py:7:mix"]


def test_the_same_place_is_one_event_with_a_count(counting):
    for _ in range(500):
        counting.handle(record())
    usagelog.flush(cfg(), closing=True)
    [e] = noted(LOG_WARNING)
    assert e["count"] == 500


def test_a_run_counts_at_most_so_many_places(counting):
    for i in range(usagelog.MAX_PLACES + 5):
        counting.handle(record(line=i))
    counting.handle(record(line=0))   # a place it knows still counts
    usagelog.flush(cfg(), closing=True)
    assert len(noted(LOG_WARNING)) == usagelog.MAX_PLACES
    assert noted("problems_dropped")[0]["count"] == 5


def test_a_later_flush_still_counts_a_place_past_the_cap(counting):
    for i in range(usagelog.MAX_PLACES):
        counting.handle(record(line=i))
    usagelog.flush(cfg(), closing=True)
    usage._pending.clear()
    counting.handle(record(line=3))
    usagelog.flush(cfg(), closing=True)
    assert [e["attrs"]["line"] for e in noted(LOG_WARNING)] == [3]


def test_it_never_waits_for_a_lock(counting):
    """An audio callback can log: with every lock of the handler held elsewhere, it goes on."""
    counting.acquire()
    try:
        t = threading.Thread(target=counting.handle, args=(record(),), daemon=True)
        t.start()
        t.join(2)
        assert not t.is_alive()
    finally:
        counting.release()


def test_it_never_raises(counting):
    bad = record()
    bad.pathname = None
    counting.handle(bad)   # an AttributeError inside, swallowed


def test_warnings_and_the_start_wait_for_a_send_going_anyway(counting):
    now = usage.time.time()
    counting.handle(record())
    usagelog.flush(cfg(now))
    assert noted() == []   # not due, nothing wrong: no extra send
    counting.handle(record(level=logging.ERROR))
    usagelog.flush(cfg(now))
    assert noted(LOG_ERROR) and noted(LOG_WARNING) and noted("run.start")


def test_the_daily_count_takes_them(counting):
    counting.handle(record())
    usagelog.flush(cfg(0.0))
    assert noted(LOG_WARNING) and noted("run.start")


def test_run_end_says_how_long_once(counting):
    usagelog.ended(cfg())
    usagelog.ended(cfg())
    [e] = noted("run.end")
    assert e["attrs"] == {"lasted": "under-15m"}
    assert e["level"] == "info"
    assert len(noted("run.start")) == 1


def test_the_count_off_drops_what_waited(counting, monkeypatch):
    counting.handle(record())
    monkeypatch.setattr(usage.net, "allowed", lambda _f: False)
    usagelog.flush(cfg(), closing=True)

    monkeypatch.setattr(usage.net, "allowed", lambda _f: True)
    usagelog.flush(cfg(), closing=True)
    assert noted() == []


def test_a_saved_report_isnt_counted_again(counting, tmp_path, monkeypatch):
    monkeypatch.setitem(applog._state, "log_path", tmp_path / "x.log")
    monkeypatch.setitem(applog._state, "recent", [])
    monkeypatch.setitem(applog._state, "on_problem", None)
    exc = caught()   # (one bug: the same line both times)
    applog._real_report(exc)
    applog._real_report(exc)   # "Same error again"
    usagelog.flush(cfg(), closing=True)
    assert noted(LOG_ERROR) == []


def test_a_report_that_couldnt_be_saved_still_counts(counting, monkeypatch):
    """The usage count reads saved reports: without a file, this bug would go unseen."""
    monkeypatch.setitem(applog._state, "recent", [])
    monkeypatch.setitem(applog._state, "on_problem", None)
    monkeypatch.setattr(applog, "_save", lambda _rep: None)
    applog._real_report(caught())
    usagelog.flush(cfg(), closing=True)
    assert [e["attrs"]["type"] for e in noted(LOG_ERROR)] == ["KeyError"]


def test_an_error_in_a_del_counts(counting):
    """It's logged and no report is saved: until now the count never heard of them."""
    import sys
    t, v, tb = caught()
    applog.log.error("Ignored exception in %r", object(), exc_info=(t, v, tb))
    assert sys.unraisablehook is not None
    usagelog.flush(cfg(), closing=True)
    [e] = noted(LOG_ERROR)
    assert e["attrs"]["logger"] == "crash" and e["attrs"]["type"] == "KeyError"


def test_a_line_logged_on_its_way_to_warned_isnt_counted_twice(counting):
    tb = types.SimpleNamespace(tb_frame=types.SimpleNamespace(f_code=types.SimpleNamespace(
        co_filename=r"C:\app\soundboard\audio\engine.py", co_name="play")),
        tb_lineno=90, tb_next=None)
    usage._warned.add("OSError@soundboard/audio/engine.py:90")
    counting.handle(record(exc_info=(OSError, OSError("x"), tb)))
    usage._failed.add("dl-other/ValueError@soundboard/audio/engine.py:90/http-403")
    counting.handle(record(exc_info=(ValueError, ValueError("x"), tb)))
    counting.handle(record(exc_info=(KeyError, KeyError("x"), tb)))
    usagelog.flush(cfg(), closing=True)
    assert [e["attrs"]["type"] for e in noted(LOG_WARNING)] == ["KeyError"]


def test_events_are_json(counting):
    counting.handle(record(exc_info=caught()))
    usagelog.flush(cfg(), closing=True)
    json.dumps(usage._pending)


def test_warnings_never_push_a_crash_out_of_a_send():
    """A send and the waiting list are cut at a limit: errors stay, whatever came first."""
    from soundboard.core.usageevents import event
    warnings = [event(LOG_WARNING, logger=f"x{i}") for i in range(usage.MAX_PROBLEMS + 5)]
    kept, _newest = usage._with_reports([*warnings, event("unclean_exit", version="1")],
                                        None, 0.0)
    assert kept[0]["name"] == "unclean_exit"
    assert kept[-1]["name"] == "problems_dropped" and kept[-1]["count"] == 6
    c = cfg()
    c.stats_events = []
    many = [event(LOG_WARNING, logger=f"x{i}") for i in range(usage.MAX_PENDING + 5)]
    usage._keep(c, [*many, event("freeze")])
    assert len(c.stats_events) == usage.MAX_PENDING
    assert c.stats_events[0]["name"] == "freeze"


def test_a_saved_crash_report_survives_a_full_list_of_warnings(tmp_path):
    from soundboard.core.usageevents import event
    folder = tmp_path / applog.REPORTS_DIR
    folder.mkdir()
    (folder / "crash-1.txt").write_text(
        "Onion Board crash report\nVersion:  2.9.0\nFatal:    yes\n\n"
        "Traceback (most recent call last):\n"
        '  File "soundboard/audio/engine.py", line 12, in play\n'
        "KeyError: 'x'\n", encoding="utf-8")
    warnings = [event(LOG_WARNING, logger=f"x{i}") for i in range(usage.MAX_PROBLEMS)]
    kept, _newest = usage._with_reports(warnings, tmp_path, 0.0)
    assert kept[0]["name"] == "crash" and kept[0]["attrs"]["type"] == "KeyError"
    assert [e["name"] for e in kept[1:-1]] == [LOG_WARNING] * (usage.MAX_PROBLEMS - 1)
    assert kept[-1]["name"] == "problems_dropped"
